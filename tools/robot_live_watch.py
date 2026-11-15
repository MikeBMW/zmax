#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖 真机只读监视器 (老倪 2026-11-15「我现在运行, 你检查机器人」)

只读纪律: 只读文件 + 只读 HTTP, **不发任何指令**, 不改任何状态文件。
盯四样东西:
  ① TCP 位姿真值 zmax_data/rokae_sdk/tcp_out/latest.json   (帧龄 / 连续性)
  ② 出口 action   zmax_data/ss_live/action.json            (src / 目标位姿 / step / 夹爪)
  ③ 派单事实      zmax_data/rokae_sdk/{traj_step_state,last_sent}.json
  ④ 执行器留痕    zmax_data/ss_live/actuator_calls.log (尾 200 行)

结束条件: 12 分钟内没动 / 动过之后静 90s。产出一份 JSON + 人话摘要。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
ACTION = os.path.join(ROOT, "zmax_data/ss_live/action.json")
TSTATE = os.path.join(ROOT, "zmax_data/rokae_sdk/traj_step_state.json")
SENT = os.path.join(ROOT, "zmax_data/rokae_sdk/last_sent.json")
CALLS = os.path.join(ROOT, "zmax_data/ss_live/actuator_calls.log")
OUT = os.path.join(ROOT, "zmax_data/reports", "robot_watch_%s.json" % time.strftime("%H%M%S"))

MAX_WAIT_S = 720.0
QUIET_DONE_S = 90.0
DT = 0.2


def _rd(p):
    try:
        st = os.stat(p)
        return json.load(open(p, encoding="utf-8")), st.st_mtime
    except Exception:                                                      # noqa: BLE001
        return None, None


def _pose():
    d, mt = _rd(LATEST)
    if not d:
        return None
    try:
        return {"x": round(float(d["x"]) * 1000, 2), "y": round(float(d["y"]) * 1000, 2),
                "z": round(float(d["z"]) * 1000, 2), "age": round(time.time() - mt, 3)}
    except Exception:                                                      # noqa: BLE001
        return None


def main():
    samples, t0 = [], time.time()
    moved, last_move = False, None
    while True:
        now = time.time()
        p = _pose()
        act, act_mt = _rd(ACTION)
        st, _ = _rd(TSTATE)
        sent, _ = _rd(SENT)
        s = {"t": round(now - t0, 2)}
        if p:
            s.update({"px": p["x"], "py": p["y"], "pz": p["z"], "age": p["age"]})
        if act:
            s.update({"src": act.get("src"), "ax": act.get("x"), "ay": act.get("y"), "az": act.get("z"),
                      "i": act.get("i"), "i_plan": act.get("i_plan"),
                      "step": (act.get("align") or {}).get("step_mm"),
                      "truth_fresh": (act.get("align") or {}).get("truth_fresh"),
                      "grip_mm": act.get("grip_mm"), "grip_act": act.get("grip_act"),
                      "why": (act.get("why") or "")[:40], "act_age": round(now - act_mt, 2) if act_mt else None})
        if st:
            s.update({"run": st.get("running"), "cursor": st.get("cursor"),
                      "n": st.get("n"), "start": st.get("start")})
        if sent:
            s.update({"sent_cursor": sent.get("cursor"), "sent_round": sent.get("round")})
        samples.append(s)
        # 动没动: 位姿变化 > 0.5mm
        if len(samples) > 1 and "px" in s and "px" in samples[-2]:
            d = abs(s["px"] - samples[-2]["px"]) + abs(s["py"] - samples[-2]["py"]) + abs(s["pz"] - samples[-2]["pz"])
            if d > 0.5:
                moved, last_move = True, now
        if moved and last_move and now - last_move > QUIET_DONE_S:
            break
        if not moved and now - t0 > MAX_WAIT_S:
            break
        time.sleep(DT)

    # ── 判读 ───────────────────────────────────────────────────────────
    rep = {"window_s": round(time.time() - t0, 1), "samples": len(samples), "moved": moved}
    pw = [s for s in samples if "px" in s]
    if pw:
        rep["pose_first"] = [pw[0]["px"], pw[0]["py"], pw[0]["pz"]]
        rep["pose_last"] = [pw[-1]["px"], pw[-1]["py"], pw[-1]["pz"]]
        rep["path_span_mm"] = round(sum(abs(pw[k]["px"] - pw[k - 1]["px"]) +
                                        abs(pw[k]["py"] - pw[k - 1]["py"]) +
                                        abs(pw[k]["pz"] - pw[k - 1]["pz"]) for k in range(1, len(pw))), 1)
        rep["truth_age_max_s"] = max(s["age"] for s in pw)
        rep["truth_age_p95_s"] = sorted(s["age"] for s in pw)[int(0.95 * (len(pw) - 1))]
        # 相邻采样最大位移(0.2s 窗口) + 真值断档
        gaps = [round(pw[k]["t"] - pw[k - 1]["t"], 2) for k in range(1, len(pw))]
        rep["sample_gap_max_s"] = max(gaps) if gaps else None
        jumps = []
        for k in range(1, len(pw)):
            d = ((pw[k]["px"] - pw[k - 1]["px"]) ** 2 + (pw[k]["py"] - pw[k - 1]["py"]) ** 2 +
                 (pw[k]["pz"] - pw[k - 1]["pz"]) ** 2) ** 0.5
            jumps.append((round(d, 2), pw[k]["t"]))
        jumps.sort(reverse=True)
        rep["jump_top3"] = jumps[:3]
    aw = [s for s in samples if s.get("ax") is not None and "px" in s]
    if aw:
        rep["src_set"] = sorted({str(s.get("src")) for s in aw})
        rep["step_max_mm"] = max([s["step"] for s in aw if s.get("step")] or [0])
        rep["delta_max_mm"] = round(max(((s["ax"] - s["px"]) ** 2 + (s["ay"] - s["py"]) ** 2 +
                                        (s["az"] - s["pz"]) ** 2) ** 0.5 for s in aw), 2)
        rep["act_age_max_s"] = max([s.get("act_age") or 0 for s in aw])
        rep["truth_fresh_all"] = all(s.get("truth_fresh") in (True, None) for s in aw)
        rep["over_step_25"] = sum(1 for s in aw if (s.get("step") or 0) > 25.0)
        grips = [(s["t"], s.get("grip_act"), s.get("grip_mm")) for s in samples if s.get("grip_act")]
        rep["grip_events"] = [g for k, g in enumerate(grips) if k == 0 or g[1] != grips[k - 1][1]]
    if os.path.exists(CALLS):
        try:
            lines = open(CALLS, encoding="utf-8", errors="ignore").read().splitlines()[-300:]
            rep["calls_tail_lines"] = len(lines)
            rep["reject_lines"] = [ln[:160] for ln in lines if "拒收" in ln][-5:]
        except Exception:                                                  # noqa: BLE001
            pass
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"report": rep, "samples": samples}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("=== 真机只读监视 ===")
    print("  窗口 %.1fs · 采样 %d · %s" % (rep["window_s"], rep["samples"],
                                       "动过" if moved else "没动(未派单/未授权)"))
    if pw:
        print("  起点 %.1f/%.1f/%.1f → 终点 %.1f/%.1f/%.1f · 累计行程 %.1fmm"
              % (*rep["pose_first"], *rep["pose_last"], rep["path_span_mm"]))
        print("  真值帧龄 max %.2fs / p95 %.2fs · 采样断档 max %ss"
              % (rep["truth_age_max_s"], rep["truth_age_p95_s"], rep["sample_gap_max_s"]))
        print("  单窗口最大位移 top3: %s" % rep["jump_top3"])
    if aw:
        print("  action 来源 %s · 单拍 step max %.1fmm · 超 25mm 次数 %d · 目标-实测最大偏差 %.1fmm"
              % (rep["src_set"], rep["step_max_mm"], rep["over_step_25"], rep["delta_max_mm"]))
        print("  真值新鲜(全程) %s · 夹爪事件 %s" % (rep["truth_fresh_all"], rep["grip_events"]))
        if rep.get("reject_lines"):
            print("  ⚠ 执行器拒收: %s" % rep["reject_lines"])
    print("  报告:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
