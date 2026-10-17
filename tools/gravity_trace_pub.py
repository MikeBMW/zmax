#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gravity_trace_pub.py — 把「万有引力表」(主参数 M 页) 的力, 每拍发成一帧信号流

老倪 2026-10-16: 「将万有引力的所有信号, 都加到插拔场景的信号分析窗口, 我要运行检查」
         + 「4元数, 你集中显示力的大小吧」/「力的大小, 和力的实部即可」

因此本发布器只发**两个口径**(不铺四元数的四个分量):
  · 力的大小 |F|  —— 该格/该合力这一拍真实的力幅值 (m/s 口径, 与表上 tooltip 的 |F| 同源)
  · 力的实部 w    —— 力四元数的实部 = |F| / u_ref (表上格子里第一个数)

信号全集 (= 表上真实存在的每一格, 一个不多一个不少):
  ① 8 个状态空间项 × L2/L3/L4/L5  → 力大小 + 实部            (8×4×2 = 64)
  ② 每行合力 (表最后一列)          → 力大小 + 实部            (8×2 = 16)
  ③ 每列合力 (表最下一行)          → 力大小 + 实部            (4×2 = 8)
  ④ 右下角 全表总合力              → 力大小 + 实部            (2)
  ⑤ 表的标量伴生量: 参考速度 u_ref / 全表一致度 / 主力(层号·项序号)   (4)

真源与算法**不在这里重写**: 直接 import 表自己的数据层 `tools/gui/gravity_table.py::GravityField`
(与画布右侧栏那张表同一个类、同一拍同一批真源: meta_tasks/skill_latest/chunk_latest/engine_latest/
 ss_traj_last + trace_live.json + ss_episode_latest.npz) ⇒ 信号分析窗口的数与表上屏幕上看到的数
天然同源, 不会出现"表是 A、波形是 B"。

场景标签: 只认 task_id 前缀 **TASK-01-FW**(插拔 FW 加载) 才发布 ⇒ 这一族固定标「插拔场景·绿」
(tools/sig_scene_tags.py::tag 里 `gravity.*` 前缀直判插拔, 与 sseng.* 同口径), 跑别的任务就不发。

用法:
  gravity_trace_pub.py [--hz 5] [--out zmax_data/ss_live/gravity_trace.json] [--once] [--selftest]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

import gravity_table as GT                                                  # noqa: E402

DST = os.path.join(ROOT, "zmax_data", "ss_live", "gravity_trace.json")
TASK_OK = "TASK-01-FW"          # 插拔 FW 加载 (场景标签=插拔场景·绿 的唯一依据)
STAGES = list(GT.STAGES)
LAYERS = list(GT.LAYERS)


def _mag3(vec3):
    return math.sqrt(sum(float(x) * float(x) for x in vec3))


def _layer_no(lk):
    """'L2' → 2 (主力层号发数值通道; 阶段名/层名是字符串, 波形里只能靠序号表达)"""
    try:
        return float(str(lk)[1:])
    except Exception:                                                       # noqa: BLE001
        return 0.0


def build_frame(f, t_s: float, running: bool = True) -> dict:
    """GravityField → 一帧样本 (只搬运 + 只做表上同口径的幅值/实部, 不造数)。

    缺项不写那个键 (页面就该看不见, 不许拿 0 冒充"力为零")。
    """
    sig = {}

    # ① 8 项 × 4 层 (表体)
    for r in f.rows:
        st = r["stage"]
        for lk, _nm in LAYERS:
            c = r["cells"].get(lk) or {}
            _m, _q = c.get("mag"), c.get("q")
            if _m is not None:
                sig["%s·%s 力大小_mps" % (st, lk)] = float(_m)
            if _q:
                sig["%s·%s 实部" % (st, lk)] = float(_q[0])
        # ② 该行合力 (表最后一列) —— |F合| 用矢量和的模 (与 tooltip 的 |F合| 同一口径)
        _q, _dev = f.row_resultant(r)
        sig["%s·合力 力大小_mps" % st] = float(r.get("mag_res") or 0.0)
        sig["%s·合力 实部" % st] = float(_q[0])

    # ③ 每列合力 (表最下一行)
    for lk, _nm in LAYERS:
        _q, _coh = f.col_resultant(lk)
        sig["列%s·合力 力大小_mps" % lk] = _mag3(_q[1:4])       # 四元数 xyz = F/u_ref ⇒ 模 = |F|
        sig["列%s·合力 实部" % lk] = float(_q[0])

    # ④ 右下角: 全表总合力
    _qt, _coht = f.total_resultant()
    sig["总合力 力大小_mps"] = _mag3(_qt[1:4])
    sig["总合力 实部"] = float(_qt[0])

    # ⑤ 标量伴生量
    sig["参考速度 u_ref_mps"] = float(f.u_ref or 0.0)
    sig["一致度"] = float(_coht)
    _ds, _dl = f.dominant_now()
    sig["主力层号"] = _layer_no(_dl)
    sig["主力项序号"] = float(STAGES.index(_ds) + 1) if _ds in STAGES else 0.0

    for k in list(sig.keys()):            # 非有限值一律不发 (nan/inf 会把波形画花)
        v = sig[k]
        if not isinstance(v, float) or v != v or v in (float("inf"), float("-inf")):
            sig.pop(k, None)

    return {"ts": float(time.time()),
            "时间_s": round(float(t_s), 3),
            "运行": 1.0 if running else 0.0,
            "task_id": str(getattr(f, "task_id", "") or ""),
            "阶段": str(getattr(f, "stage_now", "") or ""),
            "s": sig}


def _read_run_flag():
    """实跑判定: 与表同口径 (engine_latest/chunk_latest 新鲜) —— 没在跑就发 运行=0 (表定格)。"""
    try:
        return bool(GT.run_state()[0])
    except Exception:                                                       # noqa: BLE001
        return False


def write_atomic(out: str, obj: dict) -> None:
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, out)                                                   # 页面读到的一定是完整帧


def load_last_t(out: str) -> float:
    try:
        with open(out, encoding="utf-8") as f:
            return float(json.load(f).get("时间_s") or 0.0)
    except Exception:                                                       # noqa: BLE001
        return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--out", default=DST)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--force", action="store_true", help="忽略 task_id 过滤 (只给判据造两分支用)")
    a = ap.parse_args()

    if a.selftest:
        f = GT.GravityField()
        fr = build_frame(f, 1.25, True)
        print("表真源: %s" % os.path.relpath(GT.SRC["meta"], ROOT))
        print("task_id = %r · 发布许可 = %s" % (f.task_id, str(f.task_id).startswith(TASK_OK)))
        print("阶段 = %r · u_ref = %.4f · 实跑 = %s" % (f.stage_now, f.u_ref, f.running))
        print("信号 %d 条 (表体 %d 格 ×2 + 行合力 %d×2 + 列合力 4×2 + 总合力 2 + 标量 4):"
              % (len(fr["s"]), len(STAGES) * len(LAYERS), len(STAGES)))
        for k, v in fr["s"].items():
            print("   %-28s %s" % (k, v))
        return 0

    t_s = load_last_t(a.out)
    t0 = time.monotonic()
    n = 0
    f = GT.GravityField()
    print("▶ 发布万有引力表信号 → %s (%.0fHz, 只认 %s*)" % (a.out, a.hz, TASK_OK), flush=True)
    while True:
        try:
            f.reload()
        except Exception as e:                                              # noqa: BLE001
            print("⚠️ 表重算失败: %s" % e, flush=True)
            time.sleep(1.0)
            continue
        tid = str(getattr(f, "task_id", "") or "")
        if not a.force and not tid.startswith(TASK_OK):
            print("… 当前元任务 %r 不是 %s* ⇒ 本进程不发布(场景标签不能乱标)" % (tid, TASK_OK), flush=True)
            time.sleep(2.0)
            continue
        t_s += 1.0 / a.hz                       # 横轴按真实发布节拍推进 (页面 x = 时间_s)
        fr = build_frame(f, t_s, running=_read_run_flag())
        try:
            write_atomic(a.out, fr)
        except Exception as e:                                              # noqa: BLE001
            print("⚠️ 写 %s 失败: %s" % (a.out, e), flush=True)
        n += 1
        if n == 1 or n % 150 == 0:
            print("  已发 %d 帧 · 时间_s=%.1f · 信号 %d 条 · 阶段=%s · 总合力实部=%s · 一致度=%s"
                  % (n, t_s, len(fr["s"]), fr.get("阶段"),
                     fr["s"].get("总合力 实部"), fr["s"].get("一致度")), flush=True)
        if a.once:
            return 0
        dt = time.monotonic() - t0
        want = n / a.hz
        if dt < want:
            time.sleep(want - dt)


if __name__ == "__main__":
    sys.exit(main())
