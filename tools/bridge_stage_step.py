# -*- coding: utf-8 -*-
"""bridge_stage_step.py — 按**仿真阶段事件**驱动真机: 每个动作一次短促移动

老倪 2026-10-18 现场:
  「仿真就那么几个动作, 接近, 抓取, 提升, 转移, 你只要能跟仿真的方向一致就可以, 不要走那么远」
  「移动的距离可以小, 但是频率要跟仿真一样」「你的频率太慢了…跟上节奏啊」

做法 (不再是持续流式, 而是**事件驱动**):
  · 盯 trace_live.json 的『阶段』; 阶段一变 = 仿真做了一个动作 ⇒ 真机立刻做一次对应的小动作
  · 动作方向 = 该阶段 u_ff 的主轴 (+X→L2.forward / −X→backward / +Y→left / −Y→right / +Z→lift / −Z→lower)
  · 幅度 --step (默认 12mm), 速度 --speed (默认 40mm/s ⇒ 0.3s 走完, 和仿真同拍)
  · 幅度累计受 --band (默认 20mm) 限制: 到边界就不再往外走 (等仿真换向)
  · 全程走 8793 的既有闸门 (白名单/授权/FIFO/VL/包络); 未授权一行不发

用法:
  ./gui-venv311/bin/python tools/bridge_stage_step.py --step 12 --speed 40 --band 20
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
TR = os.path.join(REPO, "zmax_data", "ss_live", "trace_live.json")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_stage_step.jsonl")
BASE = "http://127.0.0.1:8793"
AXIS = {"x+": "L2.forward", "x-": "L2.backward", "y+": "L2.left",
        "y-": "L2.right", "z+": "L2.lift", "z-": "L2.lower"}


def _get(p, timeout=4.0):
    with urllib.request.urlopen(BASE + p, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(p, body, timeout=120.0):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=12.0, help="每个动作走多少 mm (默认 12)")
    ap.add_argument("--speed", type=float, default=40.0, help="速度 mm/s (默认 40)")
    ap.add_argument("--band", type=float, default=20.0, help="累计幅度上限 mm (默认 20)")
    ap.add_argument("--max-actions", type=int, default=40, help="最多做几个动作")
    a = ap.parse_args()

    st = _get("/ctl/status")
    if not st.get("motion_armed"):
        print("⛔ 未授权真动 ⇒ 一行都不发。先到 8793 点『🔓 授权真动』。", flush=True)
        return 2
    p0 = _get("/pose")
    anchor = [float(x) for x in p0["xyz"]]
    print("🎬 阶段事件驱动: 每动作 %.0fmm@%.0fmm/s · 幅度上限 %.0fmm · 锚点 (%.4f, %.4f, %.4f)"
          % (a.step, a.speed, a.band, *anchor), flush=True)

    last_stage = str(_j(TR).get("阶段") or "")
    n = 0
    while n < a.max_actions:
        time.sleep(0.15)
        tr = _j(TR)
        stage = str(tr.get("阶段") or "")
        if not stage or stage == last_stage:
            continue
        last_stage = stage
        v = _j(VFF)
        u = [float(x) for x in (v.get("u_ff_mms") or [])][:3]
        if len(u) < 3 or max(abs(x) for x in u) < 1.0:
            continue
        ax = max(range(3), key=lambda i: abs(u[i]))
        key = "%s%s" % ("xyz"[ax], "+" if u[ax] >= 0 else "-")
        skill = AXIS[key]
        cur = [float(x) for x in _get("/pose")["xyz"]]
        room = a.band - abs((cur[ax] - anchor[ax]) * 1000.0)
        if (cur[ax] - anchor[ax]) * u[ax] > 0:
            step = max(0.0, min(a.step, room))
        else:
            step = a.step                                   # 往锚点方向回来不限制
        if step < 3.0:
            print("🚧 %-8s → %s 跳过: 已到幅度边界 (离锚 %.1fmm)"
                  % (stage, skill, abs((cur[ax] - anchor[ax]) * 1000.0)), flush=True)
            continue
        st = _get("/ctl/status")
        if not st.get("motion_armed"):
            print("🔒 授权已撤 ⇒ 停", flush=True)
            return 0
        rob = st.get("robot") or {}
        if rob.get("collision") or rob.get("estop") or rob.get("has_error"):
            print("⛔ 机器人异常 ⇒ 停", flush=True)
            return 3
        t0 = time.time()
        try:
            r = _post("/ctl/move", {"skill": skill, "d_mm": round(step, 1),
                                    "speed_mm_s": a.speed, "arm": 1})
        except Exception as e:                                           # noqa: BLE001
            print("⚠️ 下发失败: %s" % str(e)[:100], flush=True)
            continue
        txt = " ".join(str(x) for x in (r.get("lines") or []))
        ok = bool(r.get("ok")) and "被拦" not in txt and "拒" not in txt
        # 等停稳再看真值
        moved = 0.0
        t_w = time.time()
        while time.time() - t_w < 20:
            time.sleep(0.2)
            p = _get("/pose")
            moved = max(abs((float(p["xyz"][i]) - cur[i]) * 1000.0) for i in range(3))
            if moved >= step * 0.9:
                break
            if str((_get("/ctl/status").get("robot") or {}).get("operation") or "").lower() == "idle" and moved > 0.5:
                break
        dt = time.time() - t0
        n += 1
        print("动作 %2d · 仿真阶段 %-6s → %-12s %.1fmm@%.0f · ok=%s · %.2fs · 实测 %.1fmm"
              % (n, stage, skill, step, a.speed, ok, dt, moved), flush=True)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "stage": stage, "skill": skill,
                                    "step_mm": step, "speed_mm_s": a.speed, "ok": ok,
                                    "took_s": round(dt, 2), "moved_mm": round(moved, 2)},
                                   ensure_ascii=False) + "\n")
        except Exception:                                                # noqa: BLE001
            pass
    print("✅ 做完 %d 个动作, 结束" % n, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
