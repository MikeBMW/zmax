#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""insert_force_advance.py — 用「里萨如力控」一步步把模块压进去(只在力控里前进, 不做盲推)。

老倪 2026-10-20 现场: 「你正在光模块插入的口, 你自己记住了。然后向前自己插入, 调用里萨如力控算法」。

为什么不直接发一条 47mm 的直线:
  · `precheck_move.py` 对「光模块插入点」判 FAIL(连杆6/夹爪包络/直线 侵入「检测设备」106/73/72mm) ——
    插孔本来就在那个围栏盒里, 盲推一旦有偏差就是硬顶。
  · 产线配方也是"先到口 → 直推 → 力控搜索", 直推段没有任何力保护。
  ⇒ 这里改成**只用产线的 /lissajous_force_search**(6N 沿工具 Z, 搜索盒 ±10mm、原点=当前位姿),
    每次最多前进 10mm, 每次都比 TCP 真值: 有进展就继续, 一次调完位移 <0.5mm 就判"到底了/挡住了"并停。

每一发都走执行器收口(L2.lissa_search, 同一份产线配方), 因此:
  · 要过真动授权(ctl_auth) · 全程不发夹爪指令 · 服务回执 success=False 立即中止不重发

用法:
  gui-venv311/bin/python tools/insert_force_advance.py --max-steps 6            # 真插
  gui-venv311/bin/python tools/insert_force_advance.py --max-steps 1 --dry      # 只读体检(不下发)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time

ROOT = "/home/ubuntu/zmax"
FIFO = os.path.join(ROOT, "zmax_data/l2_cmd.fifo")
LOG = os.path.join(ROOT, "zmax_data/l2_daemon_stdout.log")
TCP = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ctl_auth as CA                                                    # noqa: E402


def tcp_now():
    with open(TCP, encoding="utf-8") as f:
        d = json.load(f)
    age = time.time() - os.path.getmtime(TCP)
    return [float(d["x"]), float(d["y"]), float(d["z"])], age


def wait_still(tol=2e-5, need=3, timeout=8.0):
    """连续 need 次采样位置不动 ⇒ (pos, ok)。"""
    t0 = time.time()
    prev, still = None, 0
    while time.time() - t0 < timeout:
        p, age = tcp_now()
        if prev is not None and max(abs(p[i] - prev[i]) for i in range(3)) < tol:
            still += 1
            if still >= need:
                return p, True
        else:
            still = 0
        prev = p
        time.sleep(0.28)
    return (prev or [0, 0, 0]), False


def log_tail_new(off: int) -> str:
    try:
        with open(LOG, "rb") as f:
            f.seek(off)
            return f.read().decode("utf-8", "ignore")
    except Exception:                                                    # noqa: BLE001
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-steps", type=int, default=6)
    ap.add_argument("--force", type=float, default=6.0, help="期望力 N (产线第一次 6N / 第二次 8N)")
    ap.add_argument("--skill", default="L2.lissa_search")
    ap.add_argument("--speed", type=float, default=30.0)
    ap.add_argument("--min-progress-mm", type=float, default=0.5)
    ap.add_argument("--max-total-mm", type=float, default=55.0)
    ap.add_argument("--wait-s", type=float, default=95.0, help="单发最长等回执")
    ap.add_argument("--dry", action="store_true", help="只打印现状与将要下发的内容, 不写 FIFO")
    a = ap.parse_args()

    ok, why = CA.check()
    pos0, age0 = tcp_now()
    print("=== 插入前体检 ===")
    print("  真动授权: %s · %s" % ("✅" if ok else "🛑", why))
    print("  TCP 真值: [%.5f, %.5f, %.5f] · 帧龄 %.2fs" % (pos0[0], pos0[1], pos0[2], age0))
    p_still, still_ok = wait_still()
    print("  静止判定: %s (采样极差 <0.02mm)" % ("✅ 静止" if still_ok else "⚠️ 仍在动"))
    print("  技能: %s (产线 /lissajous_force_search 配方, %.0fN 沿工具Z, 盒±10mm 原点=当前位姿)" % (a.skill, a.force))
    if not ok:
        print("🛑 未授权 ⇒ 一条也不发。请现场在 8793 点『🔓 授权真动』(或让老倪确认)。")
        return 2
    if not still_ok:
        print("🛑 没停稳 ⇒ 不发。")
        return 2
    if a.dry:
        print("  将要写入 FIFO: %s" % json.dumps({"skill": a.skill, "speed": a.speed}, ensure_ascii=False))
        print("  (--dry: 未下发)")
        return 0

    total = 0.0
    rows = []
    prev = p_still
    for i in range(1, a.max_steps + 1):
        off = os.path.getsize(LOG)
        spec = {"skill": a.skill, "speed": a.speed}
        try:
            with open(FIFO, "w", encoding="utf-8") as f:
                f.write(json.dumps(spec, ensure_ascii=False) + "\n")
        except Exception as e:                                           # noqa: BLE001
            print("🛑 写 FIFO 失败: %s" % e)
            return 3
        t0 = time.time()
        receipt, verdict = None, None
        while time.time() - t0 < a.wait_s:
            time.sleep(0.5)
            new = log_tail_new(off)
            m = re.search(r"阶段 \d+/\d+「[^」]*」服务回执: ([^\n]*)", new)
            if m:
                receipt = m.group(1).strip()
                if "success=True" in receipt:
                    verdict = True
                elif "success=False" in receipt:
                    verdict = False
                break
            if "🛑 被拦(真动授权)" in new:
                receipt, verdict = "被授权闸拦下", False
                break
        dt = time.time() - t0
        p_after, age_a = tcp_now()
        dx = (p_after[0] - prev[0]) * 1000.0
        dy = (p_after[1] - prev[1]) * 1000.0
        dz = (p_after[2] - prev[2]) * 1000.0
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        total += dist
        rows.append((i, verdict, dt, dx, dy, dz, dist, p_after))
        print("  #%d %s · %.1fs · Δ=(%+.2f, %+.2f, %+.2f)mm |Δ|=%.2f · 累计 %.1fmm · TCP=[%.5f, %.5f, %.5f]"
              % (i, "✅" if verdict else "❌", dt, dx, dy, dz, dist, total, p_after[0], p_after[1], p_after[2]))
        if receipt:
            print("      回执: %s" % receipt[:300])
        if verdict is None:
            print("🛑 没拿到 success 字段(超时/服务没起) ⇒ 中止, 不重发")
            break
        if verdict is False:
            print("🛑 服务回执 success=False ⇒ 中止, 不重发(原因见上面回执原文)")
            break
        if dist < a.min_progress_mm:
            print("✅ 这一发力控只走了 %.2fmm (<%.1fmm 门槛) ⇒ 判「到底/到位」, 停在这里" % (dist, a.min_progress_mm))
            break
        if total > a.max_total_mm:
            print("⚠️ 累计 %.1fmm 超过上限 %.0fmm ⇒ 停" % (total, a.max_total_mm))
            break
        prev = p_after

    print("\n=== 汇总 ===")
    print("  共 %d 发 · 累计前进 %.2fmm (沿 +X 分量 %.2fmm)" % (len(rows), total, (rows[-1][7][0] - pos0[0]) * 1000.0 if rows else 0.0))
    print("  起点 [%.5f, %.5f, %.5f] → 终点 [%.5f, %.5f, %.5f]"
          % (pos0[0], pos0[1], pos0[2], (rows[-1][7] if rows else pos0)[0], (rows[-1][7] if rows else pos0)[1],
             (rows[-1][7] if rows else pos0)[2]))
    out = os.path.join(ROOT, "zmax_data/reports", "insert_force_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"start": pos0, "end": rows[-1][7] if rows else pos0, "total_mm": round(total, 3),
                   "force_n": a.force, "skill": a.skill,
                   "rows": [{"i": r[0], "ok": r[1], "s": round(r[2], 2), "d_mm": [round(r[3], 2), round(r[4], 2), round(r[5], 2)],
                             "dist_mm": round(r[6], 2)} for r in rows]}, f, ensure_ascii=False, indent=1)
    print("  取证: %s" % out)
    return 0 if rows and all(r[1] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
