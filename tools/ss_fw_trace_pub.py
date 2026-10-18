#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_fw_trace_pub.py — 把插拔链常驻引擎回路的真值按帧发出来, 让「实时监控·信号分析」主窗口有波形

老倪 2026-10-15: 「信号分析, 主窗口, 没有波形信号啊」

真根因(两条, 都已核过):
  ① 波形曲线的勾选被非当前场景的重名行摘掉了 ⇒ self.selected 空 ⇒ 一条曲线都不画(已在
     canoe_graphic._on_item_changed 修: 勾选只由当前场景那一份行说了算)。
  ② **没数据可画**: zmax_data/ss_live/trace_live.json 的唯一发布者是 3D 面板
     (tools/gui/ss_dreamview.publish_trace_live) —— 3D 不播放就不写 ⇒ sstrace.* 每个键只有 1 个样本
     ⇒ 单点画不出线(帧龄还会飙到几千秒)。

本进程补第 ② 条: 把**常驻引擎回路**(zmax-ss-engine-loop.service, 10Hz)每周期的真值转成一帧一帧的
时序流 zmax_data/ss_live/engine_trace.json (关键字段与 trace_live.json 同口径: ts + 时间_s ⇒ 页面按
"场景时刻"铺点), 于是**波形不依赖 3D 面板是否在播放**。

不造数: 全部字段都从 engine_latest.json 搬(engine loop 每周期原子写), 一个不臆造:
    控制周期/循环耗时_ms/控制环_hz/势能_phi/梯度范数/动量M/置信度/内稳态紧迫度/内稳态否决/
    动作调制_mps(=‖action[:3]‖, 回路真实输出)/元任务数/潜表示_p0..p3
安全: 只认 task_id 前缀 **TASK-01-FW**(插拔 FW 加载)⇒ 场景标签(插拔·绿)不会说谎; 跑别的任务就不发。

用法: ss_fw_trace_pub.py [--hz 10] [--out zmax_data/ss_live/engine_trace.json] [--once] [--selftest]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "zmax_data", "ss_live", "engine_latest.json")
DST = os.path.join(ROOT, "zmax_data", "ss_live", "engine_trace.json")
TASK_OK = "TASK-01-FW"          # 插拔 FW 加载 (场景标签=插拔场景·绿 的唯一依据)


def _f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def load_last_t(out: str) -> float:
    """时间_s 连续: 重启后接着上一段的时刻往下走 (否则横轴回跳, 波形会断成两截)。"""
    try:
        with open(out, encoding="utf-8") as f:
            return _f(json.load(f).get("时间_s"), 0.0) or 0.0
    except Exception:                                                          # noqa: BLE001
        return 0.0


def build_frame(d: dict, t_s: float) -> dict:
    """engine_latest.json → 一帧时序样本 (只搬运, 不加工; 缺键就不写那个键)。"""
    act = d.get("action") or []
    an = 0.0
    try:
        an = (float(act[0]) ** 2 + float(act[1]) ** 2 + float(act[2]) ** 2) ** 0.5
    except Exception:                                                          # noqa: BLE001
        an = _f(d.get("action_norm"), 0.0) or 0.0
    p = d.get("p") or []
    fr = {
        "ts": float(d.get("ts") or time.time()),
        "时间_s": round(t_s, 3),
        "帧": d.get("cycle"),
        "总帧": d.get("cycle"),
        "控制周期": d.get("cycle"),
        "循环耗时_ms": _f(d.get("ms")),
        "控制环_hz": _f(d.get("hz")),
        "势能_phi": _f(d.get("phi")),
        "梯度范数": _f(d.get("grad_norm")),
        "动量M": _f(d.get("M")),
        "置信度": _f(d.get("confidence")),
        "内稳态紧迫度": _f(d.get("hom_urgency")),
        "内稳态否决": 1.0 if d.get("hom_veto") else 0.0,
        "动作调制_mms": round(an * 1000.0, 2),   # 🔢 mm/s (原 m/s ×1000)
        # 🔴 2026-10-15 老倪: 「动作调制器要变成 action, 至少有 x y z a b c, 怎么就一个 mps?」
        #   上面的 动作调制_mps 只是**模长** ‖action[:3]‖; 完整动作是 **4 维**
        #   [vx, vy, vz (m/s), 夹爪 0/1] (engine_latest.action, 真源 ss_engine_loop 每周期输出)。
        #   拆成分量发出来, 面板上才是真正的动作向量。姿态(rx/ry/rz)不在本出口 (由 L2 状态机/技能段 +
        #   执行器内环负责)。
        "动作调制_x_mms": round(_f(act[0]) * 1000.0, 2) if len(act) > 0 else None,
        "动作调制_y_mms": round(_f(act[1]) * 1000.0, 2) if len(act) > 1 else None,
        "动作调制_z_mms": round(_f(act[2]) * 1000.0, 2) if len(act) > 2 else None,
        "动作调制_夹爪": _f(act[3]) if len(act) > 3 else None,
        # 🧩 动作块 (老倪 2026-10-15): 常驻回路平铺的块键 (chunk.H / chunk.块步N_mps / chunk.λN / 平滑_转角…)
        #   原样搬过来 ⇒ 信号分析里块与其它曲线同一根钟、同一画法。回路没出块 (ZMAX_CHUNK_H<=1) 时这里为空。
        **{k: v for k, v in ((d.get("chunk_keys") or {}).items())},
        "元任务数": _f(d.get("meta_n")),
    }
    for i in range(min(4, len(p))):
        fr[f"潜表示_p{i}"] = _f(p[i])
    return {k: v for k, v in fr.items() if v is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--out", default=DST)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        with open(SRC, encoding="utf-8") as f:
            d = json.load(f)
        fr = build_frame(d, 1.25)
        print("源 %s" % SRC)
        print("task_id =", d.get("task_id"), "| 发布许可 =", str(d.get("task_id") or "").startswith(TASK_OK))
        print("帧字段 %d 个:" % len(fr))
        for k, v in fr.items():
            print("   %-14s %s" % (k, v))
        return 0

    t_s = load_last_t(a.out)
    t0 = time.monotonic()
    n = 0
    print("▶ 发布插拔链真值帧 → %s (%.0fHz, 只认 %s*)" % (a.out, a.hz, TASK_OK), flush=True)
    while True:
        try:
            with open(SRC, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                                                      # noqa: BLE001
            time.sleep(1.0 / a.hz)
            continue
        tid = str(d.get("task_id") or "")
        if not tid.startswith(TASK_OK):
            print("… 当前回路任务 %r 不是 %s* ⇒ 本进程不发布(场景标签不能乱标)" % (tid, TASK_OK), flush=True)
            time.sleep(2.0)
            continue
        t_s += 1.0 / a.hz                       # 横轴按真实发布节拍推进 (页面 x = 时间_s)
        fr = build_frame(d, t_s)
        tmp = a.out + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(fr, f, ensure_ascii=False)
            os.replace(tmp, a.out)              # 原子: 页面读到的一定是完整帧
        except Exception as e:                                                 # noqa: BLE001
            print("⚠️ 写 %s 失败: %s" % (a.out, e), flush=True)
        n += 1
        if n == 1 or n % 300 == 0:
            print("  已发 %d 帧 · 时间_s=%.1f · φ=%s · 耗时=%sms"
                  % (n, t_s, fr.get("势能_phi"), fr.get("循环耗时_ms")), flush=True)
        if a.once:
            return 0
        dt = time.monotonic() - t0
        want = n / a.hz
        if dt < want:
            time.sleep(want - dt)


if __name__ == "__main__":
    sys.exit(main())
