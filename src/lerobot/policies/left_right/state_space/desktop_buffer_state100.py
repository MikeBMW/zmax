#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desktop_buffer_state100.py — 桌面「级联缓冲」工位的 100D 统一状态空间 (v2)

设计依据: 离散制造中的级联缓冲 (Cascading Buffering)
  慢速瓶颈 = 固件刷写机 (串行, 一次一件)
  快节奏   = 桌面机械臂 (上下料)
  目标     = 异步双工: 刷写机在刷的 t_flash 期间, 机械臂必须去伺候**前后两个缓冲区**,
             而不是在刷写机旁等。串行 = 450 UPH, 双工 = 900 UPH
             (t_flash 4s / t_load 2s / t_unload 2s)。

升级纪律 (同 43→55 的前两次):
  ① 前 55 维语义一字不动 (老权重/老数据/老标定直接吃)
  ② 55:100 是本工位语义, 每通道有 名字/单位/来源/判据
  ③ 无来源 ⇒ 0 + 标"沉睡", 不编造; 派生量口径唯一 (fill/UPH/水位只在一处算)

55:100 的 45 维分 8 组, 与设计的三个维度一一对应:
  物理拓扑  infeed_slot / loader_slot / outfeed_slot / insp_slot / scrap_slot   (5×3=15)
  队列逻辑  infeed+outfeed 占用/占用率 (4) · 高低水位 (2) · 槽位四态计数 (3) · FIFO/重试 (3)
  控制策略  刷写站状态机 (3) · 机器人状态/双工重叠/实测节拍/断供堵塞 (8) · UPH 兑现 (4)
  安全兜底  backpressure / global_pause / scrap_ratio (3)
  合计 15+4+2+3+3+3+8+4+3 = 45

槽位四态 (与设计严格一致): EMPTY / OCCUPIED_UNPROCESSED / PROCESSING / OCCUPIED_PROCESSED
逐槽明细走 2bit/槽 位图 (pack_slots/unpack_slots), 进状态向量的只是四态计数。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# 前 55 维: 直接复用 (不复制定义, 避免两套口径漂移)
from .unified_state55 import UnifiedState55D, ALL_SEGMENTS as SEG55, OBS55_DIM

STATE100_DIM = 100

# ── 槽位四态 ───────────────────────────────────────────────────────────────
SLOT_EMPTY, SLOT_UNPROC, SLOT_INFLIGHT, SLOT_DONE = 0, 1, 2, 3
SLOT_STATE_NAMES = {SLOT_EMPTY: "EMPTY", SLOT_UNPROC: "OCCUPIED_UNPROCESSED",
                    SLOT_INFLIGHT: "PROCESSING", SLOT_DONE: "OCCUPIED_PROCESSED"}

# ── 刷写站 / 机器人 状态 ───────────────────────────────────────────────────
FLASH_IDLE, FLASH_LOADING, FLASH_RUNNING, FLASH_DONE, FLASH_ERROR = 0, 1, 2, 3, 4
FLASH_NAMES = {0: "IDLE", 1: "LOADING", 2: "RUNNING", 3: "DONE", 4: "ERROR"}
ROBOT_IDLE, ROBOT_LOAD, ROBOT_UNLOAD, ROBOT_TRAVEL, ROBOT_WAIT = 0, 1, 2, 3, 4
ROBOT_NAMES = {0: "IDLE", 1: "LOAD_FLASH", 2: "UNLOAD_FLASH", 3: "TRAVEL", 4: "WAIT"}

# ── 调度意图 (上层只给意图, 执行由 L2 收口) ─────────────────────────────────
ACT_PICK_INFEED = "PICK_INFEED"
ACT_LOAD_FLASH = "LOAD_FLASH"
ACT_UNLOAD_FLASH = "UNLOAD_FLASH"
ACT_STORE_OUTFEED = "STORE_OUTFEED"
ACT_RETRY_FLASH = "RETRY_FLASH"
ACT_TO_INSPECT = "TO_INSPECT"
ACT_TO_SCRAP = "TO_SCRAP"
ACT_PAUSE = "PAUSE"
ACT_THROTTLE = "THROTTLE"
ACT_IDLE = "IDLE"


@dataclass(frozen=True)
class Field:
    """一个通道的完整定义 (能力特征库口径: 名字/单位/来源/含义 缺一不可)。"""
    name: str
    start: int
    stop: int
    unit: str
    source: str
    note: str

    @property
    def dim(self) -> int:
        return self.stop - self.start


BUF_FIELDS: tuple[Field, ...] = (
    # ① 物理拓扑: 五个锚 (桌面坐标系, m)
    Field("infeed_slot_xyz", 55, 58, "m", "Infeed 缓冲区 当前取料槽", "待刷写缓冲区槽位 (生产者侧)"),
    Field("loader_slot_xyz", 58, 61, "m", "刷写机进料口", "慢速瓶颈工位的取放点"),
    Field("outfeed_slot_xyz", 61, 64, "m", "Outfeed 缓冲区 当前放料槽", "已刷写缓冲区槽位 (下游侧)"),
    Field("insp_slot_xyz", 64, 67, "m", "AOI 检测位/相机视场中心", "光学检测站"),
    Field("scrap_slot_xyz", 67, 70, "m", "废料盘槽位", "NG 分流"),
    # ② 缓冲占用与水位 (N/M 容量是配置量, 不进向量)
    Field("infeed_count", 70, 71, "件", "Σ槽位态∈{UNPROC,INFLIGHT,DONE}", "Infeed 占用"),
    Field("infeed_fill", 71, 72, "0..1", "infeed_count / N", "Infeed 占用率"),
    Field("outfeed_count", 72, 73, "件", "Σ outfeed 槽 occupied", "Outfeed 占用"),
    Field("outfeed_fill", 73, 74, "0..1", "outfeed_count / M", "Outfeed 占用率 (溢出保护)"),
    Field("hi_watermark", 74, 75, "0..1", "配置", "Infeed 高水位 ⇒ 背压上游"),
    Field("lo_watermark", 75, 76, "0..1", "配置", "Infeed 低水位 ⇒ 断供预警"),
    # ③ 槽位四态计数 (位图聚合)
    Field("n_unproc", 76, 77, "件", "槽位态 = OCCUPIED_UNPROCESSED", "有料待刷"),
    Field("n_inflight", 77, 78, "件", "槽位态 = PROCESSING", "在刷 (已被夹走)"),
    Field("n_done", 78, 79, "件", "槽位态 = OCCUPIED_PROCESSED", "已刷待下道"),
    # ④ 队列逻辑: FIFO + 重试优先
    Field("fifo_len", 79, 80, "件", "FIFO 队列长度", "标准先进先出"),
    Field("retry_len", 80, 81, "件", "重试队列长度", "刷写失败待重刷 (不许排尾)"),
    Field("retry_head_slot", 81, 82, "0..1", "重试队首槽号 / N", "优先重刷件所在槽"),
    # ⑤ 刷写站状态机
    Field("flash_state", 82, 83, "枚举", "0 IDLE/1 LOADING/2 RUNNING/3 DONE/4 ERROR", "设备在手状态"),
    Field("flash_elapsed", 83, 84, "s", "now − t_loaded", "当前件已刷时长"),
    Field("flash_retry", 84, 85, "件", "本件累计重试次数", "重试计数"),
    # ⑥ 机器人 + 异步双工
    Field("robot_state", 85, 86, "枚举", "0 IDLE/1 LOAD/2 UNLOAD/3 TRAVEL/4 WAIT", "机械臂当前动作"),
    Field("robot_wait", 86, 87, "flag", "robot_state == WAIT", "1=在设备旁干等 (目标恒 0)"),
    Field("overlap_ratio", 87, 88, "0..1", "min(1,(t_load+t_unload)/t_flash)", "刷写窗口内机械臂有活干的比例"),
    Field("t_load", 88, 89, "s", "抓取→送入→退出 实测", "上料耗时"),
    Field("t_unload", 89, 90, "s", "取出→放入 Outfeed 实测", "下料耗时"),
    Field("t_travel", 90, 91, "s", "站间移动实测", "空走 (双工里可被隐藏)"),
    Field("starve_time", 91, 92, "s", "累计 Infeed 无料时长", "断供累计 (设备空转)"),
    Field("block_time", 92, 93, "s", "累计 Outfeed 无位时长", "堵塞累计 (取出无处放)"),
    # ⑦ 节拍与 UPH 兑现
    Field("uph_target", 93, 94, "pph", "承诺值 900", "目标产能"),
    Field("uph_actual", 94, 95, "pph", "3600 / cycle_time", "实测产能"),
    Field("cycle_time", 95, 96, "s", "相邻两件完成时间差", "单件节拍 (瓶颈决定)"),
    Field("buffer_margin", 96, 97, "件", "N_eff − N_need", "缓冲余量 (负 ⇒ 必断供)"),
    # ⑧ 安全兜底
    Field("backpressure", 97, 98, "flag", "infeed_fill ≥ hi_watermark", "上游必须停送"),
    Field("global_pause", 98, 99, "flag", "outfeed_count ≥ M 或 flash ERROR", "全局暂停"),
    Field("scrap_ratio", 99, 100, "0..1", "scrap / 已处理", "废料率"),
)

ALL_FIELDS: tuple[Field, ...] = tuple(
    [Field(s.name, s.start, s.stop, s.unit, s.source, s.note) for s in SEG55] + list(BUF_FIELDS)
)
SLICE100: dict[str, slice] = {f.name: slice(f.start, f.stop) for f in ALL_FIELDS}
BY_NAME: dict[str, Field] = {f.name: f for f in ALL_FIELDS}


def validate_layout() -> None:
    """段表自身的判据: 首尾相接、覆盖 0:100、无重叠、无重名。"""
    pos, names = 0, set()
    for f in ALL_FIELDS:
        if f.start != pos:
            raise ValueError("段 %s 起点 %d != %d (缺口/重叠)" % (f.name, f.start, pos))
        if f.stop <= f.start:
            raise ValueError("段 %s 宽度非法 (%d:%d)" % (f.name, f.start, f.stop))
        if f.name in names:
            raise ValueError("通道重名 %s" % f.name)
        names.add(f.name)
        pos = f.stop
    if pos != STATE100_DIM:
        raise ValueError("覆盖到 %d != %d" % (pos, STATE100_DIM))


# ── 槽位位图 (2 bit/槽, 用于落盘/跨进程传状态) ──────────────────────────────
def pack_slots(states: Sequence[int]) -> int:
    if len(states) > 32:
        raise ValueError("位图最多 32 槽, 收到 %d" % len(states))
    m = 0
    for i, s in enumerate(states):
        if int(s) not in SLOT_STATE_NAMES:
            raise ValueError("非法槽位态 %r" % (s,))
        m |= int(s) << (2 * i)
    return m


def unpack_slots(mask: int, n: int) -> list[int]:
    return [(int(mask) >> (2 * i)) & 0b11 for i in range(n)]


def slot_counts(states: Sequence[int]) -> dict[str, int]:
    c = {SLOT_STATE_NAMES[k]: 0 for k in SLOT_STATE_NAMES}
    for s in states:
        c[SLOT_STATE_NAMES[int(s)]] += 1
    return c


def uph_model(t_flash: float, t_load: float, t_unload: float, t_travel: float = 0.0,
              uph_target: float = 900.0, stall_max: float = 0.0) -> dict:
    """串行 vs 异步双工 产能模型 + 缓冲需求 (设计文档的那笔账, 落成可跑的判据)。

    serial CT = t_load + t_flash + t_unload            (机械臂在设备旁等刷完)
    duplex CT = max(t_flash, t_load + t_unload + t_travel)  (刷写期间去伺候两个缓冲)
    双工成立的前提: t_load + t_unload + t_travel ≤ t_flash; 否则瓶颈变成机械臂。
    缓冲需求: 设备停机 stall_max 秒不断供 ⇒ N_need = ceil(stall_max / duplexCT) + 1
    """
    ct_serial = t_load + t_flash + t_unload
    ct_duplex = max(t_flash, t_load + t_unload + t_travel)
    robot_hidden = (t_load + t_unload + t_travel) <= t_flash + 1e-9
    return {
        "ct_serial_s": round(ct_serial, 3),
        "uph_serial": round(3600.0 / ct_serial, 1) if ct_serial > 0 else 0.0,
        "ct_duplex_s": round(ct_duplex, 3),
        "uph_duplex": round(3600.0 / ct_duplex, 1) if ct_duplex > 0 else 0.0,
        "bottleneck": "flash" if robot_hidden else "robot",
        "robot_hidden_in_flash": robot_hidden,
        "reach_target": (3600.0 / ct_duplex) >= uph_target - 1e-9 if ct_duplex > 0 else False,
        "uph_target": uph_target,
        "n_need_for_stall": int(math.ceil(stall_max / ct_duplex) + 1) if ct_duplex > 0 else 0,
        "overlap_ratio": round(min(1.0, (t_load + t_unload) / t_flash), 4) if t_flash > 0 else 0.0,
    }


class DesktopBuffer100:
    """100D = 55D 统一状态 (原样) + 45D 级联缓冲语义 (拓扑/队列/双工/水位)。"""

    def __init__(self, base55: UnifiedState55D | None = None) -> None:
        self.base = base55 or UnifiedState55D()
        self.current_state = np.zeros(STATE100_DIM, dtype=np.float64)
        self.named: dict[str, np.ndarray] = {}
        self.filled: dict[str, bool] = {f.name: False for f in BUF_FIELDS}
        self.cfg: dict[str, float] = {"N": 16.0, "M": 8.0, "uph_target": 900.0,
                                      "t_flash": 4.0, "stall_max": 0.0}

    # ---- 融合 ---------------------------------------------------------------
    def fuse(self, obs55=None, visual_39d=None, tactile_4d=None, buf: dict | None = None,
             extra: dict | None = None, tcp_prev=None, dt: float = 0.0, **cfg) -> np.ndarray:
        """拼 100D。配置量 (N/M/uph_target/t_flash/stall_max) 走 kwargs, 不进向量。"""
        if obs55 is not None:
            base = np.asarray(obs55, dtype=np.float64).ravel()
            if base.size != OBS55_DIM:
                raise ValueError("obs55 必须 %d 维, 收到 %d" % (OBS55_DIM, base.size))
        else:
            if visual_39d is None or tactile_4d is None:
                raise ValueError("要么 obs55, 要么 visual_39d + tactile_4d")
            base = self.base.fuse(visual_39d, tactile_4d, extra=extra)

        self.filled = {f.name: False for f in BUF_FIELDS}     # 每拍重置, 不许跨拍漏判
        buf = dict(buf or {})
        c = dict(self.cfg)
        c.update({k: float(v) for k, v in {**buf, **cfg}.items()
                  if k in ("N", "M", "uph_target", "t_flash", "stall_max")})
        for k in ("N", "M", "uph_target", "t_flash", "stall_max"):
            buf.pop(k, None)
        N, M = float(c["N"]), float(c["M"])
        tail = np.zeros(STATE100_DIM - OBS55_DIM, dtype=np.float64)

        def put(name: str, val) -> None:
            f = BY_NAME[name]
            arr = np.atleast_1d(np.asarray(val, dtype=np.float64)).ravel()
            if arr.size != f.dim:
                raise ValueError("通道 %s 需要 %d 维, 收到 %d" % (name, f.dim, arr.size))
            tail[f.start - OBS55_DIM:f.stop - OBS55_DIM] = arr
            self.filled[name] = True

        if tcp_prev is not None and float(dt) > 0:
            buf.setdefault("tcp_vel", (base[SLICE100["tcp_p"]] -
                                      np.asarray(tcp_prev, dtype=np.float64).ravel()) / float(dt))
        for k, v in buf.items():
            if k not in BY_NAME or BY_NAME[k].start < OBS55_DIM:
                raise KeyError("未注册的缓冲区通道: %r" % (k,))
            put(k, v)

        def g(name: str) -> float:
            return float(tail[SLICE100[name].start - OBS55_DIM])

        # 派生量 (口径唯一, 不许调用方各算各的)
        if not self.filled["infeed_fill"] and self.filled["infeed_count"] and N > 0:
            put("infeed_fill", g("infeed_count") / N)
        if not self.filled["outfeed_fill"] and self.filled["outfeed_count"] and M > 0:
            put("outfeed_fill", g("outfeed_count") / M)
        if not self.filled["uph_actual"] and self.filled["cycle_time"] and g("cycle_time") > 0:
            put("uph_actual", 3600.0 / g("cycle_time"))
        if not self.filled["backpressure"] and self.filled["infeed_fill"] and self.filled["hi_watermark"]:
            put("backpressure", 1.0 if g("infeed_fill") >= g("hi_watermark") else 0.0)
        if not self.filled["global_pause"] and self.filled["outfeed_count"]:
            paused = g("outfeed_count") >= M or (self.filled["flash_state"] and int(g("flash_state")) == FLASH_ERROR)
            put("global_pause", 1.0 if paused else 0.0)
        if not self.filled["robot_wait"] and self.filled["robot_state"]:
            put("robot_wait", 1.0 if int(g("robot_state")) == ROBOT_WAIT else 0.0)

        for f in ALL_FIELDS:
            if f.stop <= OBS55_DIM:                      # 前 55: 来自统一状态本体
                self.named[f.name] = base[f.start:f.stop]
            else:                                        # 55:100: 来自缓冲区尾段
                self.named[f.name] = tail[f.start - OBS55_DIM:f.stop - OBS55_DIM]
        x = np.concatenate([base, tail])
        if x.size != STATE100_DIM:
            raise ValueError("应为 %d 维, 实际 %d" % (STATE100_DIM, x.size))
        self.current_state = x
        self.cfg.update({k: float(v) for k, v in c.items()})
        return x

    # ---- 读 -----------------------------------------------------------------
    def get(self, name: str, state=None) -> np.ndarray:
        if name not in SLICE100:
            raise KeyError("未注册通道: %r" % (name,))
        x = self.current_state if state is None else np.asarray(state, dtype=np.float64).ravel()
        return x[SLICE100[name]]

    def awake(self) -> list[str]:
        return [f.name for f in BUF_FIELDS if self.filled.get(f.name)]

    def asleep(self) -> list[str]:
        return [f.name for f in BUF_FIELDS if not self.filled.get(f.name)]

    def describe(self, state=None) -> list[dict]:
        x = self.current_state if state is None else np.asarray(state, dtype=np.float64).ravel()
        rows = []
        for f in ALL_FIELDS:
            v = x[f.start:f.stop]
            rows.append({"name": f.name, "unit": f.unit, "idx": "%d:%d" % (f.start, f.stop),
                         "value": (float(v[0]) if f.dim == 1 else [round(float(t), 6) for t in v]),
                         "source": f.source, "note": f.note,
                         "awake": bool(self.filled.get(f.name, True))})
        return rows

    # ---- 调度状态机 (异步双工意图层) ----------------------------------------
    def schedule(self, state=None, n_slots: int | None = None) -> dict:
        """按级联缓冲策略给**下一步意图** (不含轨迹, 执行由 L2 收口)。

        优先级:
          1 Outfeed 满/设备 ERROR → PAUSE            (否则取出无处放, 把设备一起堵死)
          2 重试队列非空          → RETRY_FLASH      (插队, 不许排尾)
          3 设备 DONE             → UNLOAD→STORE    (机械臂此刻必须动)
          4 设备 IDLE 且有料      → PICK→LOAD       (进刷写窗口)
          5 设备 RUNNING          → 去伺候 Outfeed/AOI, **绝不允许 WAIT**
          6 Infeed 高水位         → THROTTLE        (背压上游)
        """
        x = self.current_state if state is None else np.asarray(state, dtype=np.float64).ravel()
        g = lambda n: float(x[SLICE100[n]][0])          # noqa: E731
        has = lambda n: bool(self.filled.get(n))        # noqa: E731
        N = float(self.cfg.get("N", 16))
        M = float(self.cfg.get("M", 8))
        steps, why = [], []

        flash = int(g("flash_state")) if has("flash_state") else FLASH_IDLE
        retry = g("retry_len") if has("retry_len") else 0.0
        infeed_n = g("infeed_count") if has("infeed_count") else 0.0
        out_n = g("outfeed_count") if has("outfeed_count") else 0.0
        robot_wait = bool(g("robot_wait")) if has("robot_wait") else False

        if out_n >= M or flash == FLASH_ERROR:
            steps.append(ACT_PAUSE)
            why.append("Outfeed 满(%d/%d)或设备故障: 取出无处放 ⇒ 全局暂停, 等下游取货" % (out_n, M))
        elif retry > 0:
            steps.append(ACT_RETRY_FLASH)
            why.append("重试队列 %d 件: 优先插队重刷 (不许排尾打乱顺序)" % retry)
        elif flash == FLASH_DONE:
            steps += [ACT_UNLOAD_FLASH, ACT_STORE_OUTFEED]
            why.append("刷写完成: 取出→放入 Outfeed (此刻机械臂必须动)")
        elif flash in (FLASH_IDLE, FLASH_ERROR) and infeed_n > 0:
            steps += [ACT_PICK_INFEED, ACT_LOAD_FLASH]
            why.append("设备空闲且有料: 取件送入 (PICK→LOAD), 进入刷写窗口")
        elif flash == FLASH_RUNNING:
            if out_n > 0:
                steps.append(ACT_STORE_OUTFEED)
                why.append("刷写中: 用这段时间把 Outfeed 的件送下道 (时间重叠)")
            else:
                steps.append(ACT_TO_INSPECT if has("insp_slot_xyz") else ACT_IDLE)
                why.append("刷写中且 Outfeed 空: 去 AOI/预取下一件, 不许在设备旁干等")
        elif infeed_n <= 0:
            steps.append(ACT_IDLE)
            why.append("断供: Infeed 无料 ⇒ 上游必须送料 (计入 starve_time)")
        else:
            steps.append(ACT_IDLE)
            why.append("无触发条件")

        if has("infeed_fill") and has("hi_watermark") and g("infeed_fill") >= g("hi_watermark") \
                and ACT_PAUSE not in steps:
            steps.append(ACT_THROTTLE)
            why.append("Infeed 到高水位 (%.2f≥%.2f): 背压上游停送" % (g("infeed_fill"), g("hi_watermark")))
        if robot_wait:
            why.append("⚠ robot_wait=1: 机械臂在设备旁干等 —— 直接吃掉 UPH, 必须消除")
        return {"actions": steps, "reason": why, "robot_wait": robot_wait,
                "flash_state": FLASH_NAMES.get(flash, str(flash)),
                "infeed": [infeed_n, N], "outfeed": [out_n, M]}

    # ---- 队列律 (L = λW) ----------------------------------------------------
    def consistency(self) -> dict:
        """Infeed 缓冲的守恒: L ≈ λ·W。W 用实测 t_load+t_unload 作服务窗。"""
        L = float(self.get("infeed_count")[0])
        pph = float(self.get("uph_actual")[0])
        lam = pph / 3600.0
        W = 0.0
        if self.filled.get("t_load") and self.filled.get("t_unload"):
            W = float(self.get("t_load")[0]) + float(self.get("t_unload")[0])
        dev = L - lam * W
        return {"L": L, "lambda_pps": round(lam, 6), "W_s": round(W, 3),
                "lambda_w": round(lam * W, 6), "dev": round(dev, 6), "ok": abs(dev) <= 0.5}


# ── 现场几何锚装载 (真源: L2 300UPH 闭合段表, mm → m) ────────────────────────
def anchors_from_segment_table(path: str) -> dict:
    """从现场段表抽 5 个锚; 抽不到就报缺项, 绝不用默认坐标顶替。"""
    import json
    rows = json.load(open(path))["rows"]
    want = {
        "infeed_slot_xyz": ("槽1 上方",),
        "loader_slot_xyz": ("插入 孔1",),
        "outfeed_slot_xyz": ("下降到 下料盘 下槽1",),
        "insp_slot_xyz": ("金手指检测(AOI)",),
        "scrap_slot_xyz": ("下降到 废料盘(不良品)",),
    }
    out, missing = {}, []
    for key, pats in want.items():
        hit = None
        for r in rows:
            if any(p in str(r.get("label", "")) for p in pats) and isinstance(r.get("a"), list) and len(r["a"]) == 3:
                hit = tuple(float(v) / 1000.0 for v in r["a"])
                break
        if hit:
            out[key] = hit
        else:
            missing.append(key)
    return {"anchors": out, "missing": missing, "src": path}


validate_layout()

if __name__ == "__main__":
    st = DesktopBuffer100()
    base = np.linspace(0, 1, OBS55_DIM)
    x = st.fuse(obs55=base, buf={"infeed_count": 6, "outfeed_count": 2, "hi_watermark": 0.875,
                                 "lo_watermark": 0.125, "flash_state": FLASH_RUNNING,
                                 "t_load": 2.0, "t_unload": 2.0, "t_travel": 0.5,
                                 "cycle_time": 4.0, "uph_target": 900},
                N=16, M=8, t_flash=4.0)
    print("100D:", x.shape, "| 前 55 零回归:", np.array_equal(x[:OBS55_DIM], base))
    print("字段:", len(ALL_FIELDS), "| awake:", len(st.awake()), "| asleep:", len(st.asleep()))
    print("UPH 模型:", uph_model(4.0, 2.0, 2.0, 0.5, 900))
    print("调度:", st.schedule())
