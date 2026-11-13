# -*- coding: utf-8 -*-
"""桌面缓冲区图 (BufferGraph) —— 离散槽位 × 连续位姿 × 时间张量 × 各向异性度规。

职责边界 (这条是设计结论, 不是可选项):
  1. **容器在 BufferGraph, 不在 SU(2)**: SU(2)≅S³ 只装朝向(3 自由度), 槽号/料盘/队列/时间戳
     都不是转动, 塞进群元素会丢信息(有界映射不可逆)。每个槽的位姿按 SE(3)=(U∈SU(2), t∈R³) 存。
  2. **SU(2) 只做两件事**: ① 每槽朝向 U_slot 与对位误差 θ_err=2·arccos|w| (U=I ⇔ 对位);
     ② 场景层合成/收敛判据 (交给 su2.compose_scene, 本模块不重复实现)。
  3. **各向异性度规由本模块给出, 喂流形引擎**: Δξ = −α·M⁻¹∇V, M 是刚度张量(容差小 ⇒ 刚度大)。
     插入区 M 径向 ≫ 轴向 ⇒ 径向步长被压到 (σ_rad/σ_free)² 倍。
  4. **动态度规只许放宽自由区**: 插入区 σ_radial 锁死 (fail-closed), 否则就是拿刮擦换节拍。

100D 状态向量 = 本图的**压缩投影** (aggregate() 直接回 100D 的 buf dict, 前 100 维语义零改动)。
DDS 传输用既有通用载荷 SSNodePort(topic/ts/json), **不新建 IDL 类型**: 加字段不改 IDL、不重建类型;
BufferNode 的 JSON 序列化见 to_payload()/from_payload()。
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from .su2 import SU2Element

# 区域
ZONE_INFEED, ZONE_FLASH, ZONE_OUTFEED, ZONE_SCRAP = 0, 1, 2, 3
ZONE_INSPECT = 4
ZONE_NAMES = {ZONE_INFEED: "infeed", ZONE_FLASH: "flash", ZONE_OUTFEED: "outfeed",
              ZONE_SCRAP: "scrap", ZONE_INSPECT: "inspect"}

# 槽位四态 (与 desktop_buffer_state100.SLOT_STATE_NAMES 同一口径)
EMPTY, UNPROC, PROCESSING, DONE = 0, 1, 2, 3
STATE_NAMES = {EMPTY: "EMPTY", UNPROC: "OCCUPIED_UNPROCESSED",
               PROCESSING: "PROCESSING", DONE: "OCCUPIED_PROCESSED"}

# 自由区基准容差 (m): 用来给出"插入区相对自由区被压紧多少倍"的可读数
SIGMA_FREE = 1.0e-3


@dataclass(frozen=True)
class MetricTensor:
    """各向异性物理约束: 径向(垂直主轴)容差小 ⇒ 纠偏敏感; 轴向容差大 ⇒ 推进宽容。

    axis 是**约束主轴**, 单位向量。刚度张量 M = (1/σ_ax²)·nnᵀ + (1/σ_rad²)(I − nnᵀ)。
    步长张量 M⁻¹ = σ_ax²·nnᵀ + σ_rad²(I − nnᵀ)  ⇒ 引擎用 Δξ = −α·M⁻¹·∇V 即自动"径向紧、轴向松"。
    """
    sigma_radial: float = SIGMA_FREE
    sigma_axial: float = SIGMA_FREE
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    zone: int = -1

    def __post_init__(self) -> None:
        if self.sigma_radial <= 0 or self.sigma_axial <= 0:
            raise ValueError("sigma 必须 > 0 (收到 %r/%r)" % (self.sigma_radial, self.sigma_axial))
        n = np.asarray(self.axis, dtype=np.float64).ravel()
        if n.size != 3 or np.linalg.norm(n) < 1e-9:
            raise ValueError("axis 必须是 3 维非零向量")
        object.__setattr__(self, "axis", tuple((n / np.linalg.norm(n)).tolist()))

    def _n(self) -> np.ndarray:
        return np.asarray(self.axis, dtype=np.float64)

    def stiffness_matrix(self) -> np.ndarray:
        """M (刚度). 迹 = 1/σ_ax² + 2/σ_rad²."""
        n = self._n()
        nn = np.outer(n, n)
        return (1.0 / self.sigma_axial ** 2) * nn + (1.0 / self.sigma_radial ** 2) * (np.eye(3) - nn)

    def step_matrix(self) -> np.ndarray:
        """M⁻¹ (直接乘梯度得步长), 与 stiffness_matrix() 严格互逆。"""
        n = self._n()
        nn = np.outer(n, n)
        return self.sigma_axial ** 2 * nn + self.sigma_radial ** 2 * (np.eye(3) - nn)

    def step(self, grad: Sequence[float], alpha: float = 1.0) -> np.ndarray:
        """Δξ = −α·M⁻¹·∇V (流形引擎的硬约束形式)。"""
        g = np.asarray(grad, dtype=np.float64).ravel()
        if g.size != 3:
            raise ValueError("grad 必须 3 维")
        return -float(alpha) * (self.step_matrix() @ g)

    def radial_ratio(self, sigma_free: float = SIGMA_FREE) -> dict:
        """相对自由区的压紧/放大倍数 —— 报数用, 不是内部计算用。"""
        return {"radial_step_x": round((self.sigma_radial / sigma_free) ** 2, 6),
                "axial_step_x": round((self.sigma_axial / sigma_free) ** 2, 6),
                "anisotropy": round((self.sigma_axial / self.sigma_radial) ** 2, 3)}

    def to_dict(self) -> dict:
        return {"sigma_radial": self.sigma_radial, "sigma_axial": self.sigma_axial,
                "axis": list(self.axis), "zone": self.zone}


def metric_for_zone(zone: int, axis: Sequence[float] = (0, 0, 1)) -> MetricTensor:
    """区域 → 度规。插入区(flash)强各向异性, 其余各向同性。"""
    if zone == ZONE_FLASH:
        return MetricTensor(0.3e-3, 6.0e-3, tuple(axis), zone)   # 径向 0.3mm / 轴向 6mm
    return MetricTensor(SIGMA_FREE, SIGMA_FREE, (0, 0, 1), zone)


@dataclass
class BufferNode:
    """一个物理槽位 = 图节点。空槽也发布 (状态 EMPTY), 供调度预留。"""
    node_id: str
    parent_tray_id: str = ""
    zone_type: int = ZONE_INFEED
    t: np.ndarray = field(default_factory=lambda: np.zeros(3))       # 平移 (m) —— 不是 SU(2)
    U: SU2Element = field(default_factory=SU2Element.identity)       # 朝向 (SU(2))
    target_t: np.ndarray = field(default_factory=lambda: np.zeros(3))
    target_U: SU2Element = field(default_factory=SU2Element.identity)
    metric: MetricTensor = field(default_factory=MetricTensor)
    slot_state: int = EMPTY
    t_in: float = 0.0        # 入队时刻 (时间张量 τ)
    t_out: float = 0.0       # 出队/完成时刻
    item_id: str = ""

    def __post_init__(self) -> None:
        self.t = np.asarray(self.t, dtype=np.float64).ravel()
        self.target_t = np.asarray(self.target_t, dtype=np.float64).ravel()
        if self.t.size != 3 or self.target_t.size != 3:
            raise ValueError("node %s: t/target_t 必须 3 维" % self.node_id)
        if self.slot_state not in STATE_NAMES:
            raise ValueError("node %s: 非法槽位态 %r" % (self.node_id, self.slot_state))

    # --- SE(3) 误差: 位置 mm + 姿态 deg(物理角, 不是 S³ 测地角) ---
    def pose_error(self) -> dict:
        dt = self.t - self.target_t
        u_err = self.U.inv() * self.target_U
        return {"d_mm": float(np.linalg.norm(dt) * 1000.0),
                "d_vec_mm": [round(float(v) * 1000.0, 3) for v in dt],
                "theta_deg": math.degrees(u_err.theta()),
                "aligned": bool(np.linalg.norm(dt) < 1e-4 and u_err.theta() < math.radians(0.5))}

    def occupied(self) -> bool:
        return self.slot_state != EMPTY

    def age(self, now: float | None = None) -> float:
        """时间张量: 元素在该槽已停留秒数 (空槽 0)。"""
        if not self.occupied():
            return 0.0
        now = time.time() if now is None else float(now)
        return max(0.0, now - self.t_in)

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "parent_tray_id": self.parent_tray_id,
                "zone_type": self.zone_type, "zone_name": ZONE_NAMES.get(self.zone_type, "?"),
                "pos": [float(v) for v in self.t], "quat": [self.U.w, self.U.x, self.U.y, self.U.z],
                "target_pos": [float(v) for v in self.target_t],
                "target_quat": [self.target_U.w, self.target_U.x, self.target_U.y, self.target_U.z],
                "metric": self.metric.to_dict(),
                "slot_state": int(self.slot_state), "slot_state_name": STATE_NAMES[self.slot_state],
                "t_in": float(self.t_in), "t_out": float(self.t_out), "item_id": self.item_id,
                "pose_error": self.pose_error()}


class BufferGraph:
    """桌面缓冲区的唯一真源: 逐槽节点 + 时间张量 + 聚合投影。"""

    def __init__(self, uph_target: float = 900.0) -> None:
        self.nodes: dict[str, BufferNode] = {}
        self.uph_target = float(uph_target)
        self.done_ts: list[float] = []      # 每个件完成时刻 (滑动窗口算 UPH)
        self.scrap_n = 0
        self.hi_watermark, self.lo_watermark = 0.80, 0.20

    # ---------- 建图 ----------
    def add(self, node: BufferNode) -> BufferNode:
        if node.node_id in self.nodes:
            raise ValueError("节点重名: %s" % node.node_id)
        self.nodes[node.node_id] = node
        return node

    def by_zone(self, zone: int) -> list[BufferNode]:
        return [n for n in self.nodes.values() if n.zone_type == zone]

    def get(self, node_id: str) -> BufferNode:
        if node_id not in self.nodes:
            raise KeyError("未知槽位: %s" % node_id)
        return self.nodes[node_id]

    # ---------- 状态转移 (唯一写口) ----------
    def put(self, node_id: str, item_id: str, now: float | None = None,
            state: int = UNPROC) -> BufferNode:
        """放料: EMPTY → OCCUPIED_UNPROCESSED (下料槽可放已刷完件 ⇒ state=DONE)。"""
        n = self.get(node_id)
        if n.slot_state != EMPTY:
            raise ValueError("%s 非空 (态=%s), 不许覆盖" % (node_id, STATE_NAMES[n.slot_state]))
        if state not in (UNPROC, DONE):
            raise ValueError("put 只接受 UNPROC/DONE, 收到 %r" % (state,))
        n.slot_state, n.item_id = int(state), item_id
        n.t_in = time.time() if now is None else float(now)
        n.t_out = 0.0
        return n

    def take(self, node_id: str, now: float | None = None) -> BufferNode:
        """取走: → PROCESSING (件在臂上/在设备里), 槽位腾空但记录保留。"""
        n = self.get(node_id)
        if n.slot_state != UNPROC:
            raise ValueError("%s 态=%s, 只能取有料待刷件" % (node_id, STATE_NAMES[n.slot_state]))
        n.slot_state = PROCESSING
        return n

    def finish(self, node_id: str, ok: bool = True, now: float | None = None) -> BufferNode:
        """刷写完成: 成功 → OCCUPIED_PROCESSED(待下料), 失败 → 回 UNPROC(重试队列)。"""
        n = self.get(node_id)
        if n.slot_state != PROCESSING:
            raise ValueError("%s 态=%s, 不能结算" % (node_id, STATE_NAMES[n.slot_state]))
        now = time.time() if now is None else float(now)
        if ok:
            n.slot_state, n.t_out = DONE, now
            self.done_ts.append(now)
        else:
            n.slot_state = UNPROC       # 重试: 不记完成, 不排尾
        return n

    def clear(self, node_id: str, scrap: bool = False, now: float | None = None) -> BufferNode:
        """下料/换件: → EMPTY。scrap=True 计入废料。"""
        n = self.get(node_id)
        if n.slot_state != DONE and not scrap:
            raise ValueError("%s 态=%s, 只能下已刷完件" % (node_id, STATE_NAMES[n.slot_state]))
        if scrap:
            self.scrap_n += 1
        n.slot_state, n.item_id = EMPTY, ""
        n.t_in = n.t_out = 0.0
        return n

    # ---------- 聚合 → 100D 的 buf dict (前 100 维语义零改动) ----------
    def aggregate(self, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        infeed = self.by_zone(ZONE_INFEED)
        outfeed = self.by_zone(ZONE_OUTFEED)
        N = max(1, len(infeed))
        M = max(1, len(outfeed))
        n_unproc = sum(1 for n in self.nodes.values() if n.slot_state == UNPROC)
        n_inflight = sum(1 for n in self.nodes.values() if n.slot_state == PROCESSING)
        n_done = sum(1 for n in self.nodes.values() if n.slot_state == DONE)
        infeed_count = len([n for n in infeed if n.occupied()])
        outfeed_count = len([n for n in outfeed if n.occupied()])
        processed = len(self.done_ts) + self.scrap_n
        ct = self.cycle_time()
        return {
            "infeed_count": float(infeed_count), "infeed_fill": infeed_count / N,
            "outfeed_count": float(outfeed_count), "outfeed_fill": outfeed_count / M,
            "hi_watermark": self.hi_watermark, "lo_watermark": self.lo_watermark,
            "n_unproc": float(n_unproc), "n_inflight": float(n_inflight), "n_done": float(n_done),
            "uph_target": self.uph_target,
            "cycle_time": float(ct) if ct > 0 else 0.0,
            "scrap_ratio": (self.scrap_n / processed) if processed else 0.0,
        }

    # ---------- 时间张量 ----------
    def wait_times(self, now: float | None = None) -> dict:
        """逐槽等待时长 (W) + 均值; 只统计有料/在制槽。"""
        now = time.time() if now is None else float(now)
        per = {n.node_id: round(n.age(now), 3) for n in self.nodes.values() if n.occupied()}
        vals = list(per.values())
        return {"per_slot_s": per, "mean_wait_s": (sum(vals) / len(vals)) if vals else 0.0,
                "n_waiting": len(vals)}

    def cycle_time(self, window: int = 20) -> float:
        """相邻两件完成时间差的中位数 (窗口内)。样本 <2 ⇒ 0 (没有数, 不是 0 秒节拍)。"""
        ts = sorted(self.done_ts)[-int(window):]
        if len(ts) < 2:
            return 0.0
        d = np.diff(ts)
        return float(np.median(d))

    def uph(self, window_s: float = 60.0, now: float | None = None) -> float:
        """滑动窗口实测 UPH (件/小时)。"""
        now = time.time() if now is None else float(now)
        k = sum(1 for t in self.done_ts if now - t <= window_s)
        return float(k) * 3600.0 / float(window_s)

    def queue_law(self, now: float | None = None) -> dict:
        """Little 定律 L = λW 自检: L=平均在制, λ=吞吐(件/s), W=平均停留。"""
        now = time.time() if now is None else float(now)
        L = sum(1 for n in self.nodes.values() if n.occupied())
        w = self.wait_times(now)["mean_wait_s"]
        ct = self.cycle_time()
        lam = (1.0 / ct) if ct > 0 else 0.0
        return {"L": float(L), "lambda_per_s": round(lam, 6), "W_s": round(w, 3),
                "lambda_W": round(lam * w, 4), "dev": round(abs(L - lam * w), 4),
                "ok": bool(ct > 0 and abs(L - lam * w) <= 0.5)}

    # ---------- 意图 (Flow Matching 的上游, 不含轨迹) ----------
    def intents(self, now: float | None = None) -> dict:
        """按异步双工策略出**意图**: 插完立刻转 PROCESSING 并给出下一条。

        优先级与 100D schedule() 同口径: PAUSE > RETRY > UNLOAD > LOAD > THROTTLE > IDLE。
        输出只有 source/target/意图名 —— 轨迹与执行由 L2 收口, 这里不下发动作。
        """
        now = time.time() if now is None else float(now)
        infeed = self.by_zone(ZONE_INFEED)
        outfeed = self.by_zone(ZONE_OUTFEED)
        flash = self.by_zone(ZONE_FLASH)
        M = max(1, len(outfeed))
        outfeed_occ = len([n for n in outfeed if n.occupied()])

        retry = [n for n in self.nodes.values() if n.slot_state == UNPROC and n.t_out > 0]
        done = [n for n in self.nodes.values() if n.slot_state == DONE]
        unproc = [n for n in infeed if n.slot_state == UNPROC]
        inflight = [n for n in self.nodes.values() if n.slot_state == PROCESSING]

        if outfeed_occ >= M:
            return {"intent": "PAUSE", "reason": "outfeed 满 (%d/%d) ⇒ 送件无处放" % (outfeed_occ, M),
                    "pose": None}
        if retry:
            n = sorted(retry, key=lambda z: z.t_out)[0]
            return {"intent": "RETRY_FLASH", "source": n.node_id, "target": flash[0].node_id if flash else "",
                    "reason": "重试队列优先, 不许排尾", "pose": (n.t, n.U)}
        if done:
            n = sorted(done, key=lambda z: z.t_out)[0]
            dst = next((o for o in outfeed if not o.occupied()), None)
            return {"intent": "UNLOAD", "source": n.node_id, "target": dst.node_id if dst else "",
                    "reason": "刷完必须立刻取出 (双工窗口)", "pose": (n.t, n.U)}
        if unproc and flash:
            n = sorted(unproc, key=lambda z: z.t_in)[0]     # FIFO
            if inflight:
                # 设备在刷: 不许 WAIT —— 把下一件搬到待插位 (预取), 抢回双工窗口
                return {"intent": "PREP_NEXT", "source": n.node_id,
                        "target": flash[0].node_id if flash else "",
                        "reason": "设备在刷 ⇒ 预取下一件到待插位 (禁止 robot_wait)",
                        "pose": (n.t, n.U), "is_blind_insert": False}
            return {"intent": "LOAD", "source": n.node_id, "target": flash[0].node_id,
                    "reason": "设备空闲且有料", "pose": (n.t, n.U),
                    "is_blind_insert": bool(math.dist(n.t, flash[0].t) < 0.05)}
        inf_occ = len([n for n in infeed if n.occupied()])
        if inf_occ / max(1, len(infeed)) >= self.hi_watermark:
            return {"intent": "THROTTLE", "reason": "infeed 高水位 %.0f%%" % (100.0 * inf_occ / max(1, len(infeed))),
                    "pose": None}
        return {"intent": "IDLE", "reason": "无件可搬 / 设备在刷", "pose": None}

    def insert_inserts_done(self, node_id: str, ok: bool = True, now: float | None = None) -> dict:
        """插完的原子动作: finish() + 立刻给下一条意图 (双工的关键一跳)。"""
        self.finish(node_id, ok=ok, now=now)
        return self.intents(now=now)

    # ---------- 度规安全闸 ----------
    def relax_metric(self, node_id: str, factor: float) -> dict:
        """动态度规放宽 (UPH 落后时)。**插入区 fail-closed**: 不许拿刮擦换节拍。"""
        n = self.get(node_id)
        if n.zone_type == ZONE_FLASH:
            return {"ok": False, "why": "插入区 σ_radial 锁死 (0.3mm)：放宽=刮擦风险, 拒绝",
                    "sigma_radial": n.metric.sigma_radial}
        if not (1.0 < float(factor) <= 2.0):
            return {"ok": False, "why": "放宽倍数必须 ∈ (1,2], 收到 %r" % (factor,)}
        free = metric_for_zone(n.zone_type, n.metric.axis)
        n.metric = MetricTensor(free.sigma_radial * float(factor), free.sigma_axial * float(factor),
                                free.axis, n.zone_type)
        return {"ok": True, "factor": float(factor), "sigma_radial": n.metric.sigma_radial}

    # ---------- SU(2) 接线 (只做朝向/收敛判据) ----------
    def pose_su2(self, node_id: str) -> dict:
        """单槽朝向的 SU(2) 读数: θ_err 物理角, U=I ⇔ 对位。"""
        n = self.get(node_id)
        u_err = n.U.inv() * n.target_U
        return {"node_id": node_id, "theta_deg": math.degrees(u_err.theta()),
                "axis": [round(float(v), 4) for v in u_err.axis()],
                "w_abs": abs(u_err.w), "aligned": bool(u_err.theta() < math.radians(0.5))}

    def scene_pose(self) -> SU2Element:
        """全桌面朝向的群合成 (槽序稳定排序, 保证可复现)。"""
        us = [n.U for _, n in sorted(self.nodes.items())]
        return SU2Element.compose(us) if us else SU2Element.identity()

    # ---------- DDS 载荷 (不新建 IDL) ----------
    def to_payload(self, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        return {"system_time": now, "uph_target": self.uph_target,
                "aggregate": self.aggregate(now), "wait": self.wait_times(now),
                "queue_law": self.queue_law(now), "intent": self.intents(now),
                "all_slots": [n.to_dict() for _, n in sorted(self.nodes.items())]}

    def to_json(self, now: float | None = None) -> str:
        return json.dumps(self.to_payload(now), ensure_ascii=False, default=str)

    @staticmethod
    def from_payload(d: dict) -> "BufferGraph":
        """回灌: 只恢复节点事实, 不恢复统计窗口 (统计要靠真实事件重放)。"""
        g = BufferGraph(float(d.get("uph_target", 900.0)))
        for s in d.get("all_slots", []):
            q = s.get("quat", [1, 0, 0, 0])
            tq = s.get("target_quat", [1, 0, 0, 0])
            m = s.get("metric", {}) or {}
            g.add(BufferNode(
                node_id=s["node_id"], parent_tray_id=s.get("parent_tray_id", ""),
                zone_type=int(s.get("zone_type", ZONE_INFEED)),
                t=np.asarray(s.get("pos", [0, 0, 0]), dtype=np.float64),
                U=SU2Element(*[float(v) for v in q], normalize=True),
                target_t=np.asarray(s.get("target_pos", [0, 0, 0]), dtype=np.float64),
                target_U=SU2Element(*[float(v) for v in tq], normalize=True),
                metric=MetricTensor(float(m.get("sigma_radial", SIGMA_FREE)),
                                    float(m.get("sigma_axial", SIGMA_FREE)),
                                    tuple(m.get("axis", (0, 0, 1))), int(m.get("zone", -1))),
                slot_state=int(s.get("slot_state", EMPTY)),
                t_in=float(s.get("t_in", 0.0)), t_out=float(s.get("t_out", 0.0)),
                item_id=s.get("item_id", "")))
        return g


# ── 现场默认拓扑 (几何锚来自 100D 参考: l2_300uph_closure_20261102.json, mm→m) ──
DEFAULT_ANCHORS = {
    "infeed": (0.490, 0.499, 0.240),
    "flash": (0.767, 0.228, 0.340),
    "outfeed": (0.490, 0.075, 0.198),
    "inspect": (0.360, -0.117, 0.654),
    "scrap": (0.469, -0.402, 0.200),
}


def build_default_graph(n_infeed: int = 8, n_outfeed: int = 6,
                        tray_y_pitch: float = 0.05, insert_axis=(0.0, 0.0, -1.0),
                        uph_target: float = 900.0) -> BufferGraph:
    """按现场锚件搭默认拓扑。槽位沿 y 等间距 (段表本身没区分槽号, 用 pitch 展开并在报告里标注)。"""
    g = BufferGraph(uph_target=uph_target)
    ax, ay, az = DEFAULT_ANCHORS["infeed"]
    for i in range(n_infeed):
        t = np.array([ax, ay + i * tray_y_pitch, az])
        g.add(BufferNode("Infeed_Slot_%02d" % (i + 1), "Infeed_Tray", ZONE_INFEED, t.copy(), target_t=t.copy(),
                         metric=metric_for_zone(ZONE_INFEED)))
    fx, fy, fz = DEFAULT_ANCHORS["flash"]
    ft = np.array([fx, fy, fz])
    g.add(BufferNode("Flash_Port_01", "Flash_Machine", ZONE_FLASH, ft.copy(), target_t=ft.copy(),
                     metric=metric_for_zone(ZONE_FLASH, insert_axis)))
    ox, oy, oz = DEFAULT_ANCHORS["outfeed"]
    for i in range(n_outfeed):
        t = np.array([ox, oy + i * tray_y_pitch, oz])
        g.add(BufferNode("Outfeed_Slot_%02d" % (i + 1), "Outfeed_Tray", ZONE_OUTFEED, t.copy(), target_t=t.copy(),
                         metric=metric_for_zone(ZONE_OUTFEED)))
    ix, iy, iz = DEFAULT_ANCHORS["inspect"]
    g.add(BufferNode("Inspect_01", "AOI", ZONE_INSPECT, np.array([ix, iy, iz]), target_t=np.array([ix, iy, iz]),
                     metric=metric_for_zone(ZONE_INSPECT)))
    sx, sy, sz = DEFAULT_ANCHORS["scrap"]
    g.add(BufferNode("Scrap_Slot_01", "Scrap_Tray", ZONE_SCRAP, np.array([sx, sy, sz]),
                     target_t=np.array([sx, sy, sz]), metric=metric_for_zone(ZONE_SCRAP)))
    return g
