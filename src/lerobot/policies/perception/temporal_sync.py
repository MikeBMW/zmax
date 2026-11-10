# -*- coding: utf-8 -*-
"""temporal_sync — 多模态时间对齐 (统一状态空间的"theta 绑定"层)。

老倪 2026-11-10: 「统一状态空间, 作为空间细胞, 用于同步视觉、触觉、动作状态等多模态,
时间同步, 空间同步, 合理不?」

现状 (实测, 不是推测):
  fuse_sensors() 的实现就是 np.concatenate([obs39(视觉39D), tactile(4D)]) —— **纯拼接, 零时间对齐**。
  两段数据各自有自己的采集时刻, 拼在一起就被当成"同一时刻"。
  实测各通道帧龄: 相机 28ms / 末端 139ms / 力 945ms / 机器人状态 1140ms ⇒ 最大差 1112ms。
  按 30mm/s 运动速度换算 = 33mm 位置错位, 比重复定位精度 0.03mm 差 1000 倍。

本模块补的就是这一层 —— 神经科学里对应海马 theta 节律 (4~12Hz, ~100ms 窗) 把不同来源的
信息绑定到同一时间帧; 工程上就是"给每维打时间戳 + 对齐到目标时刻 + 报告一致性"。

三条规矩:
  1. 不插值超过 max_hold_s 的旧值 —— 那是编造, 不是同步; 超时维度标记 stale 并保留标记位。
  2. 对齐结果必须带 skew_s / stale_ratio, 让下游知道这一帧"拼得有多齐", 不许静默。
  3. 默认零阶保持 (ZOH): 机械臂位姿是阶梯式到达, 线性插值会造出不存在的中间姿态。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple


class TimedFrame:
    """带时间戳的一帧多模态数据。每维可独立标记来源与采集时刻。"""

    __slots__ = ("t", "values", "stamps", "sources")

    def __init__(self, values: Dict[str, float], t: Optional[float] = None,
                 sources: Optional[Dict[str, str]] = None):
        self.t = time.time() if t is None else float(t)
        self.values = dict(values)
        self.stamps = {k: self.t for k in self.values}
        self.sources = dict(sources or {})

    def put(self, key: str, value: float, t: float, source: str = "") -> None:
        """写入一维, 带它自己的采集时刻 (不是整帧时刻)。"""
        self.values[key] = float(value)
        self.stamps[key] = float(t)
        if source:
            self.sources[key] = source

    def ages(self, now: Optional[float] = None) -> Dict[str, float]:
        now = time.time() if now is None else now
        return {k: now - s for k, s in self.stamps.items()}

    def skew_s(self, now: Optional[float] = None) -> float:
        """本帧内各维采集时刻的最大跨度 (越小越"同时")。"""
        if not self.stamps:
            return 0.0
        vals = list(self.stamps.values())
        return max(vals) - min(vals)

    def stale_ratio(self, max_hold_s: float, now: Optional[float] = None) -> float:
        if not self.values:
            return 0.0
        ages = self.ages(now)
        n_stale = sum(1 for a in ages.values() if a > max_hold_s)
        return n_stale / len(self.values)


class MultimodalSync:
    """多模态对齐器: 缓存各通道最近一帧, 按目标时刻对齐输出。"""

    def __init__(self, max_hold_s: float = 0.5):
        self.max_hold_s = float(max_hold_s)
        self.last: Dict[str, Dict[str, Any]] = {}   # source → {value, t}

    def update(self, source: str, key: str, value: float, t: Optional[float] = None) -> None:
        self.last[key] = {"value": float(value), "t": time.time() if t is None else float(t),
                          "src": source}

    def align(self, t_target: Optional[float] = None) -> TimedFrame:
        """把所有已知通道对齐到 t_target (默认 now), 返回带年龄/陈旧标记的帧。

        零阶保持: 取"目标时刻之前最近"的那个值, 不跨时间外推。
        """
        t_target = time.time() if t_target is None else float(t_target)
        vals: Dict[str, float] = {}
        frame = TimedFrame({}, t=t_target)
        stale: List[str] = []
        for key, rec in self.last.items():
            if rec["t"] > t_target:          # 未来数据: 不用 (时钟漂移/回拨)
                continue
            age = t_target - rec["t"]
            if age > self.max_hold_s:
                stale.append(key)
                continue                      # 不编造: 过期就不进这一帧
            vals[key] = rec["value"]
            frame.stamps[key] = rec["t"]
            frame.sources[key] = rec.get("src", "")
        frame.values = vals
        frame.t = t_target
        return frame

    def report(self, t_target: Optional[float] = None) -> Dict[str, Any]:
        """一致性报告 —— 给下游/日志用, 不许静默拼接。

        ⚠️ stale 必须基于**全部已知通道**算, 不能基于已进帧的键 ——
        否则被拒的通道在 stamps 里根本不存在, stale_keys 恒为空, 监控就撒谎了 (实测踩过)。
        """
        f = self.align(t_target)
        now = f.t
        ages = {k: round(now - r["t"], 4) for k, r in self.last.items() if r["t"] <= now}
        stale = [k for k, a in ages.items() if a > self.max_hold_s]
        return {"n_dims": len(f.values),
                "n_channels": len(self.last),
                "skew_s": round(f.skew_s(now), 4),
                "max_age_s": round(max(ages.values()), 4) if ages else 0.0,
                "stale_ratio": round(len(stale) / len(ages), 3) if ages else 0.0,
                "stale_keys": stale,
                "ages": ages}
