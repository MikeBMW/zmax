#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""desktop_buffer_state100.py — 面向「桌面缓冲区工位」的 100D 统一状态空间

升级纪律与 43→55 完全一致 (这是同一套口径的第三次升级):
  ① 前 55 维语义一字不动 —— 老权重/老数据/老标定直接吃前 55 位, 升级瞬间逐位相同
  ② 新增 45 维在模型侧零行初始化 ⇒ 输出逐位不变, 之后靠数据"觉醒"
  ③ 每个新通道都有名字 / 单位 / 来源 / 判据, 不许匿名塞数

为什么是"缓冲区"而不是再加一堆传感器通道
现场是**桌面缓冲工位**: 上料盘 → (取料) → 设备插孔 firmware loading → (拔出) → AOI 检测点
→ 下料盘 / 废料盘。这天然就是计算机中间件的**环形缓冲区 + 多级队列 + 背压**:
  生产者 = 上料盘取料             消费者 = 设备插孔 (firmware 站)
  二级队列 = AOI 检测站            旁路 = 废料盘 (NG 分流)
  水位线/背压/溢出 = 不许机械臂"空转等"或"堆件堵死"
所以 55:100 这 45 维按中间件语义设计, 而不是按"还能读什么传感器"堆:
  · 环缓冲: write/read 指针, count/capacity, fill_ratio   → 一眼看出堆没堆满
  · 水位:   high/low watermark, backpressure, overflow    → 该加速/该停/已溢出
  · 队列:   fw_* / oi_* (qlen, in_flight, pass, fail)     → 两站的吞吐与在制
  · 节拍:   cycle_time / throughput / avg_wait            → 队列律 L=λW 可对账
  · 分流:   scrap_count / scrap_ratio                     → 废料率
  · 几何:   上料/下料/废料/插孔/检测点 + 障碍向量/净空 + tcp 速度 (实际轨迹的导数)

坐标口径: 全部为**桌面工位坐标系**, 单位米 (现场段表给的是 mm, 装载时 /1000)。
未标定/无来源的通道一律 0, 并在 `awake()` 里如实列出 —— 不编造。

用法:
    from desktop_buffer_state100 import DesktopBuffer100
    st = DesktopBuffer100()
    x100 = st.fuse(obs55, buf={"ring_count": 3, "ring_capacity": 8,
                               "insert_slot_xyz": (0.767, 0.228, 0.340), ...})
    st.describe(x100)          # 带单位/来源的表
    st.consistency()           # 队列律自洽检查 (L, λW, 偏差)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

# 前 55 维: 直接复用 (不复制定义, 避免两套口径漂移)
from .unified_state55 import UnifiedState55D, ALL_SEGMENTS as SEG55, OBS55_DIM

STATE100_DIM = 100


@dataclass(frozen=True)
class Field:
    """一个物理通道的完整定义 (能力特征库口径: 名字/单位/来源/判据 缺一不可)。"""
    name: str
    start: int
    stop: int
    unit: str
    source: str
    note: str
    norm: str = "raw"        # raw | 0..1 | flag | m | m/s | s | pph

    @property
    def dim(self) -> int:
        return self.stop - self.start


# ── 55:100 新增 45 维 (与 55D 首尾相接, 无重叠) ──────────────────────────────
BUF_FIELDS: tuple[Field, ...] = (
    # ① 实际轨迹的导数 (轨迹本身已在 55D 的 tcp_p[0:3])
    Field("tcp_vel", 55, 58, "m/s", "diff(tcp_p)/dt", "末端速度 (避障/节拍都要它)", "m/s"),
    # ② 桌面工位几何锚 (现场段表 l2_300uph_closure 有真值, 装载时 mm→m)
    Field("feed_slot_xyz", 58, 61, "m", "上料盘 当前取料槽", "生产者位置: 料从这来", "m"),
    Field("out_slot_xyz", 61, 64, "m", "下料盘 当前放料槽", "良品出口", "m"),
    Field("scrap_slot_xyz", 64, 67, "m", "废料盘槽位", "NG 分流出口", "m"),
    Field("insert_slot_xyz", 67, 70, "m", "设备插孔口 (当前目标孔)", "firmware 站: 插这里才算加载", "m"),
    Field("cam_inspect_xyz", 70, 73, "m", "AOI 检测点/相机视场中心", "光学检测站位", "m"),
    # ③ 障碍与净空 (避障的判据量, 不是"感知一堆点")
    Field("obstacle_vec", 73, 76, "m", "argmin‖p_obs−p_tcp‖ − p_tcp", "最近障碍相对向量", "m"),
    Field("obstacle_dist", 76, 77, "m", "‖obstacle_vec‖", "最近障碍距离", "m"),
    Field("clearance_min", 77, 78, "m", "min(通道净空)", "规划通道最小净空 (小于臂半径 ⇒ 必撞)", "m"),
    # ④ 环形缓冲区 (中间件核心)
    Field("ring_write", 78, 79, "0..1", "write_idx / capacity", "写指针 (生产者侧)", "0..1"),
    Field("ring_read", 79, 80, "0..1", "read_idx / capacity", "读指针 (消费者侧)", "0..1"),
    Field("ring_count", 80, 81, "件", "写后未取的件数", "当前占用 (队列长度 L)", "raw"),
    Field("ring_fill", 81, 82, "0..1", "count / capacity", "占用率", "0..1"),
    Field("hi_watermark", 82, 83, "0..1", "配置", "高水位 (超过 ⇒ 停止取料)", "0..1"),
    Field("lo_watermark", 83, 84, "0..1", "配置", "低水位 (低于 ⇒ 允许继续上料)", "0..1"),
    Field("backpressure", 84, 85, "flag", "fill ≥ hi_wm", "背压: 1=上游必须停", "flag"),
    Field("overflow", 85, 86, "件", "累计溢出件数", "溢出就丢件 ⇒ 不许静默", "raw"),
    # ⑤ firmware loading 站
    Field("fw_qlen", 86, 87, "件", "该站排队件数", "待加载队列", "raw"),
    Field("fw_inflight", 87, 88, "flag", "站内有件", "在制 (设备占用中)", "flag"),
    Field("fw_pass", 88, 89, "件", "累计成功", "加载成功计数", "raw"),
    Field("fw_fail", 89, 90, "件", "累计失败", "加载失败计数 (进废料或重试)", "raw"),
    # ⑥ 光学检测站
    Field("oi_qlen", 90, 91, "件", "该站排队件数", "待测队列", "raw"),
    Field("oi_inflight", 91, 92, "flag", "站内有件", "在制 (占检测位)", "flag"),
    Field("oi_pass", 92, 93, "件", "累计合格", "检测合格计数", "raw"),
    Field("oi_fail", 93, 94, "件", "累计不合格", "检测不合格计数 (→ 废料盘)", "raw"),
    # ⑦ 节拍 (队列律可对账)
    Field("cycle_time", 94, 95, "s", "最近一件 CT", "单件节拍", "s"),
    Field("throughput", 95, 96, "pph", "3600 / cycle_time", "折算 UPH", "pph"),
    Field("avg_wait", 96, 97, "s", "Σ等待/件数", "平均排队等待 W (队列律 L=λW)", "s"),
    # ⑧ 分流与槽位进度
    Field("scrap_count", 97, 98, "件", "累计废料", "废弃件计数", "raw"),
    Field("scrap_ratio", 98, 99, "0..1", "scrap_count / 已处理", "废料率", "0..1"),
    Field("slot_progress", 99, 100, "0..1", "已处理槽位 / 总槽位", "盘面进度 (还剩多少件)", "0..1"),
)

ALL_FIELDS: tuple[Field, ...] = tuple(
    [Field(s.name, s.start, s.stop, s.unit, s.source, s.note) for s in SEG55] + list(BUF_FIELDS)
)
SLICE100: dict[str, slice] = {f.name: slice(f.start, f.stop) for f in ALL_FIELDS}


def validate_layout() -> None:
    """段表自身必须有判据: 首尾相接、覆盖 0:100、无重叠、字段无重名。"""
    pos = 0
    names = set()
    for f in ALL_FIELDS:
        if f.start != pos:
            raise ValueError("段 %s 起点 %d != 期望 %d (出现缺口/重叠)" % (f.name, f.start, pos))
        if f.stop <= f.start:
            raise ValueError("段 %s 宽度非法 (%d:%d)" % (f.name, f.start, f.stop))
        if f.name in names:
            raise ValueError("通道重名: %s" % f.name)
        names.add(f.name)
        pos = f.stop
    if pos != STATE100_DIM:
        raise ValueError("覆盖到 %d, 应为 %d" % (pos, STATE100_DIM))


class DesktopBuffer100:
    """100D = 55D 统一状态 (原样) + 45D 桌面缓冲区语义 (环缓冲/两站队列/几何锚/避障)。"""

    def __init__(self, base55: UnifiedState55D | None = None) -> None:
        self.base = base55 or UnifiedState55D()
        self.current_state = np.zeros(STATE100_DIM, dtype=np.float64)
        self.named: dict[str, np.ndarray] = {}
        self.filled: dict[str, bool] = {f.name: False for f in BUF_FIELDS}
        self.note = ""

    # ---- 融合 ----------------------------------------------------------------
    def fuse(self, obs55=None, visual_39d=None, tactile_4d=None,
             buf: dict[str, float | Iterable[float]] | None = None,
             extra: dict | None = None, tcp_prev=None, dt: float = 0.0) -> np.ndarray:
        """拼 100D。

        obs55: 现成的 55 维 (引擎/npz 里就有); 若不给, 用 39+4 现场融出前 55 维。
        buf:   45 维缓冲区通道, 按名给 (未给=0 并在 awake() 里显示"沉睡")。
        """
        if obs55 is not None:
            base = np.asarray(obs55, dtype=np.float64).ravel()
            if base.size != OBS55_DIM:
                raise ValueError("obs55 必须是 %d 维, 收到 %d" % (OBS55_DIM, base.size))
        else:
            if visual_39d is None or tactile_4d is None:
                raise ValueError("要么给 obs55, 要么给 visual_39d + tactile_4d")
            base = self.base.fuse(visual_39d, tactile_4d, extra=extra)

        # 每拍重置"有无来源"的判定 —— 上一拍的 awake 绝不许漏到这一拍 (否则派生量会静默为 0)
        self.filled = {f.name: False for f in BUF_FIELDS}
        tail = np.zeros(STATE100_DIM - OBS55_DIM, dtype=np.float64)
        # ring_capacity 是**配置量**(不是状态量) ⇒ 先摘出来, 不当通道校验, 只用于派生 fill
        _cap_cfg = float((buf or {}).get("ring_capacity") or 0.0)
        buf = {k: v for k, v in (buf or {}).items() if k != "ring_capacity"}
        named: dict[str, np.ndarray] = {f.name: base[f.start:f.stop] for f in ALL_FIELDS if f.stop <= OBS55_DIM}
        # ③ tcp_vel 可以由相邻两拍 tcp 差出来 —— 有真值就不靠外部填
        if tcp_prev is not None and float(dt) > 0:
            v = (base[SLICE100["tcp_p"]] - np.asarray(tcp_prev, dtype=np.float64).ravel()) / float(dt)
            buf = dict(buf or {})
            buf.setdefault("tcp_vel", v)
        for k, val in (buf or {}).items():
            if k not in SLICE100 or SLICE100[k].start < OBS55_DIM:
                raise KeyError("未注册的缓冲区通道: %r (只允许 55:100 的 %s)"
                               % (k, [f.name for f in BUF_FIELDS]))
            f = next(f for f in BUF_FIELDS if f.name == k)
            arr = np.atleast_1d(np.asarray(val, dtype=np.float64)).ravel()
            if arr.size != f.dim:
                raise ValueError("通道 %s 需要 %d 维, 收到 %d" % (k, f.dim, arr.size))
            tail[f.start - OBS55_DIM:f.stop - OBS55_DIM] = arr
            self.filled[k] = True
        # 派生量: throughput 由 cycle_time 算; ring_fill 由 count/capacity 算 (口径唯一, 不许各处各算)
        if not self.filled.get("throughput") and self.filled.get("cycle_time"):
            ct = float(tail[SLICE100["cycle_time"].start - OBS55_DIM])
            if ct > 0:
                tail[SLICE100["throughput"].start - OBS55_DIM] = 3600.0 / ct
                self.filled["throughput"] = True
        if not self.filled.get("ring_fill") and self.filled.get("ring_count") and _cap_cfg > 0:
            cnt = float(tail[SLICE100["ring_count"].start - OBS55_DIM])
            tail[SLICE100["ring_fill"].start - OBS55_DIM] = cnt / _cap_cfg
            self.filled["ring_fill"] = True

        for f in BUF_FIELDS:
            named[f.name] = tail[f.start - OBS55_DIM:f.stop - OBS55_DIM]
        x = np.concatenate([base, tail])
        if x.size != STATE100_DIM:
            raise ValueError("应为 %d 维, 实际 %d" % (STATE100_DIM, x.size))
        self.named = named
        self.current_state = x
        self._buf_last = dict(buf or {})
        return x

    # ---- 读 ----------------------------------------------------------------
    def get(self, name: str, state=None) -> np.ndarray:
        x = self.current_state if state is None else np.asarray(state, dtype=np.float64).ravel()
        if name not in SLICE100:
            raise KeyError("未注册通道: %r" % name)
        sl = SLICE100[name]
        return x[sl]

    def awake(self) -> list[str]:
        """本拍真正有来源的通道 (其余=0 是"没有数", 不是"等于零")。"""
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

    # ---- 队列律自洽 (L = λW) ----------------------------------------------
    def consistency(self) -> dict:
        """中间件缓冲区必须满足的守恒: 平均队长 L ≈ λ·W。

        L = ring_count, λ = throughput(件/s), W = avg_wait(s)。
        |L − λW| > 0.5 件 ⇒ 记录口径有错 (例如 throughput 用 CT 算而 W 用了另一段时间窗)。
        """
        L = float(self.get("ring_count")[0])
        pph = float(self.get("throughput")[0])
        W = float(self.get("avg_wait")[0])
        lam = pph / 3600.0
        dev = L - lam * W
        return {"L": L, "lambda_pps": round(lam, 6), "W_s": W,
                "lambda_w": round(lam * W, 6), "dev": round(dev, 6), "ok": abs(dev) <= 0.5}


# ── 现场几何锚装载 (真源: L2 300UPH 闭合段表, mm → m) ────────────────────────
def anchors_from_segment_table(path: str) -> dict:
    """从现场段表抽 55:100 需要的几何锚 (上料/下料/废料/插孔/检测点)。

    只认真实标签, 抽不到就不给 (返回缺项列表), 绝不用默认坐标顶替。
    """
    import json
    rows = json.load(open(path))["rows"]
    want = {
        "feed_slot_xyz": ("槽1 上方",),
        "insert_slot_xyz": ("孔1 孔口",),
        "cam_inspect_xyz": ("金手指检测(AOI)",),
        "out_slot_xyz": ("下降到 下料盘 下槽1",),
        "scrap_slot_xyz": ("下降到 废料盘(不良品)",),
    }
    out, missing = {}, []
    for key, pats in want.items():
        hit = None
        for r in rows:
            lb = str(r.get("label", ""))
            a = r.get("a")
            if any(pt in lb for pt in pats) and isinstance(a, list) and len(a) == 3:
                hit = tuple(float(v) / 1000.0 for v in a)     # mm → m
                break
        (out.__setitem__(key, hit) if hit else missing.append(key))
    return {"anchors": out, "missing": missing, "src": path}


validate_layout()

if __name__ == "__main__":
    st = DesktopBuffer100()
    # 自检: 前 55 位逐位不动 + 段表覆盖 + 队列律
    base = np.linspace(0, 1, OBS55_DIM)
    x = st.fuse(obs55=base, buf={"ring_count": 3, "ring_capacity": 8, "hi_watermark": 0.75,
                                 "lo_watermark": 0.25, "backpressure": 0, "cycle_time": 12.0,
                                 "avg_wait": 18.0, "insert_slot_xyz": (0.767, 0.228, 0.340)})
    print("100D:", x.shape, "| 前 55 位零回归:", np.array_equal(x[:OBS55_DIM], base))
    print("字段数:", len(ALL_FIELDS), "| awake:", len(st.awake()), "| asleep:", len(st.asleep()))
    print("队列律:", st.consistency())
