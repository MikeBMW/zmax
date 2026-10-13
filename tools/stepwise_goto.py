#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stepwise_goto.py — 点位转移「分段到位」执行器 (2026-10-13)

背景: 从 准备点 去 侧面点0 的单段 MoveL 被控制器拒:
  `MoveL · rc=6 · 残差 [77.63,347.21,-255.97] mm · CHECK · 最大偏差 347.212mm · 报警变化=True · 疑似 50102 奇异点`
  (438mm 位移 + 171.5° 姿态差塞进一段 = 控制器不干)。现场口径(real-arm-motion-control 技能):
  ① 就地抬升(纯平移) ② **原地转身(只转不移, 每段 ≤10°)** ③ 横移到目标 XY ④ 精确落位。
  逐段下发, 每段**等到位再发下一段**(绝不在上一条起步前发下一条 —— 相对量会按陈旧位姿算)。

闸门: 全部走 **8793 /ctl/move**(服务端白名单 + 真动授权 + 限流 + FIFO + 执行器 epoch 校验),
      不绕任何闸门。姿态分解在**工具系**(与执行器 pose_rot 的 q_new=q_cur·q_axis(θ) 同口径)。

用法:
  gui-venv311/bin/python tools/stepwise_goto.py --to 侧面点0 --dry     # 只出计划(零运动)
  gui-venv311/bin/python tools/stepwise_goto.py --to 侧面点0 --yes     # 真下发(逐段等到位)
选项: --speed 100 (线性 speed/10 ≈ mm/s)  --rot-speed 150  --chunk-mm 50  --chunk-deg 10
      --max-total-mm 1200  --report reports/stepwise_goto_<ts>.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSE = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
LEDGER = os.path.join(ROOT, "reports/aoi_points/%s.json")
API = "http://127.0.0.1:8793/ctl/move"
REPDIR = os.path.join(ROOT, "reports")


def log(*a):
    print(*a, flush=True)


def read_pose():
    with open(POSE, encoding="utf-8") as fh:
        d = json.load(fh)
    return {"ts": float(d["ts"]), "p": np.array([float(d[k]) for k in ("x", "y", "z")]),
            "q": np.array([float(d[k]) for k in ("qx", "qy", "qz", "qw")]), "src": d.get("src", "")}


def pose_age(p):
    return time.time() - p["ts"]


def quat_R(xyzw):
    x, y, z, w = [float(v) for v in xyzw]
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def quat_angle(qa, qb):
    """两个四元数(xyzw)之间的旋转角(度)。"""
    d = abs(float(np.dot(np.asarray(qa, float), np.asarray(qb, float))))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, d))))


def euler_xyz(Rm):
    """工具系 XYZ 分解 ⇒ R = Rz(z)·Ry(y)·Rx(x); 依次施加 A(X)→B(Y)→C(Z) 即可到目标姿态。"""
    sy = -Rm[2, 0]
    y = math.asin(max(-1.0, min(1.0, sy)))
    if abs(sy) < 0.9999:
        x = math.atan2(Rm[2, 1], Rm[2, 2])
        z = math.atan2(Rm[1, 0], Rm[0, 0])
    else:
        x = math.atan2(-Rm[1, 2], Rm[1, 1])
        z = 0.0
    return [math.degrees(v) for v in (x, y, z)]


def call(skill, val_key, val, speed, timeout=180, dry=False):
    body = {"skill": skill, val_key: float(val), "speed": float(speed), "arm": 0 if dry else 1}
    req = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": repr(e)[:160], "t": round(time.time() - t0, 2), "body": body}
    out["_t"] = round(time.time() - t0, 2)
    out["_body"] = body
    return out


def wait_arrive(cmd_mm, timeout, settle_count=5, tol_mm=0.2):
    """到位判据: 累计位移 ≥ max(0.5mm, 30%指令) 且 连续 settle_count 次 < tol_mm 且 真值帧龄<1s。"""
    t0 = time.time()
    p0 = read_pose()
    still = 0
    last = p0
    moved = 0.0
    while time.time() - t0 < timeout:
        time.sleep(0.25)
        try:
            cur = read_pose()
        except Exception:                                                         # noqa: BLE001
            continue
        if pose_age(cur) > 1.0:
            continue
        d = float(np.linalg.norm(cur["p"] - last["p"])) * 1000.0
        moved = float(np.linalg.norm(cur["p"] - p0["p"])) * 1000.0
        if d < tol_mm:
            still += 1
            if still >= settle_count and moved >= max(0.5, 0.3 * abs(cmd_mm)):
                return {"ok": True, "moved_mm": round(moved, 2), "t_s": round(time.time() - t0, 1)}
        else:
            still = 0
        last = cur
    return {"ok": False, "moved_mm": round(moved, 2), "t_s": round(time.time() - t0, 1),
            "why": "超时未判到位 (位移 %.2fmm)" % moved}


def wait_rot(cmd_deg, timeout, tol_deg=1.0):
    """转身段的到位判据: 姿态相对**下发前**至少转过 (指令-1)° 或连续静止(变化<0.05°/0.3s)。
    实测坑: 不等落地就发下一段 ⇒ 两段按同一旧姿态算, 点 20° 只转 10°。"""
    t0 = time.time()
    q0 = read_pose()["q"]
    last = np.array(q0, float)
    still = 0
    got = 0.0
    while time.time() - t0 < timeout:
        time.sleep(0.3)
        try:
            cur = read_pose()
        except Exception:                                                         # noqa: BLE001
            continue
        if pose_age(cur) > 1.0:
            continue
        got = quat_angle(q0, cur["q"])
        step = quat_angle(last, cur["q"])
        if step < 0.05:
            still += 1
        else:
            still = 0
        last = np.array(cur["q"], float)
        if got >= max(0.5, abs(cmd_deg) - tol_deg):
            return {"ok": True, "rotated_deg": round(got, 2), "t_s": round(time.time() - t0, 1)}
        if still >= 4 and got > 0.2:
            return {"ok": True, "rotated_deg": round(got, 2), "t_s": round(time.time() - t0, 1),
                    "note": "静止判到位(转过 %.2f°/目标 %.2f°)" % (got, cmd_deg)}
    return {"ok": False, "rotated_deg": round(got, 2), "t_s": round(time.time() - t0, 1),
            "why": "超时未转到位 (转过 %.2f°/目标 %.2f°)" % (got, cmd_deg)}


HEART = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/agent_heartbeat.json")


def is_idle():
    """控制器是否空闲 (operationState)。读不到 ⇒ None(不阻断, 只警告)。"""
    try:
        with open(HEART, encoding="utf-8") as fh:
            d = json.load(fh)
        st = d.get("state") or d
        return str(st.get("operationState") or "") == "OperationState.idle"
    except Exception:                                                             # noqa: BLE001
        return None


def wait_idle(timeout=60, still_need=5):
    """下发前空闲闸: operationState=idle + 位姿连续 still_need 次 <0.2mm + 真值帧龄<1s。
    实测坑(2026-10-13): 上一条腿还在走就发下一段 ⇒ 控制器 `rc=3 ABORT 前置条件不满足: 机器人不空闲`,
    该段零下发(不是动作失败), 但整条转移必须中止重算。"""
    t0 = time.time()
    last = None
    still = 0
    while time.time() - t0 < timeout:
        try:
            cur = read_pose()
        except Exception:                                                         # noqa: BLE001
            time.sleep(0.3)
            continue
        if pose_age(cur) > 1.0:
            still = 0
            time.sleep(0.3)
            continue
        p = cur["p"]
        if last is not None and float(np.linalg.norm(p - last)) * 1000.0 < 0.2:
            still += 1
        else:
            still = 0
        last = p
        if still >= still_need and is_idle() is not False:
            return {"ok": True, "t_s": round(time.time() - t0, 1), "idle": is_idle()}
        time.sleep(0.3)
    return {"ok": False, "t_s": round(time.time() - t0, 1), "idle": is_idle(),
            "why": "下发前未获空闲 (operationState 非 idle 或仍在动)"}


def build_plan(target, speed, rot_speed, chunk_mm, chunk_deg, max_total_mm, skip_rot=False):
    cur = read_pose()
    tp = np.array([float(x) for x in target["pos"][:3]])
    tq = np.array([float(x) for x in target["quat"]])
    dd = (tp - cur["p"]) * 1000.0
    ang = quat_angle(cur["q"], tq)
    Rrel = quat_R(cur["q"]).T @ quat_R(tq)
    e = euler_xyz(Rrel)
    steps = []

    def chunks(total, size, name_pos, name_neg, key):
        out = []
        n = int(math.ceil(abs(total) / float(size) - 1e-9))
        per = abs(total) / n
        sk = name_pos if total > 0 else name_neg
        for _ in range(n):
            out.append({"skill": sk, key: round(per, 3)})
        return out

    # 🔧 2026-10-13 现场纠正(老倪: 「你怎么又自己自动升高了? 差点碰撞」):
    #    **不许**在起点上方按"目标更高"一次把高度升完 —— 起点上方往往有横梁/工装(抬升>10cm 是红线)。
    #    固定顺序(与"先到目标上方再落位"同口径):
    #      ① 就地抬 ≤50mm(离开工装) ② 原地转身(只转不移, 在低位小半径) ③ 横移到目标 XY(在低位)
    #      ④ **在目标 XY 上方**小步升/降到点位高度 ⑤ 残余微调
    # 小挪动(水平≤100mm 且 |Δz|≤50mm) = 观察位之间的微调 ⇒ 不套"先抬 5cm"的转移铁律(那条是防跨越工装的大转移)
    horiz = float(np.hypot(dd[0], dd[1]))
    nudge = (horiz <= 100.0 and abs(dd[2]) <= 50.0)
    pre_up = 0.0
    if not nudge:
        pre_up = min(float(chunk_mm), 50.0, max(0.0, dd[2]))
        if pre_up < 1.0:
            pre_up = 50.0                 # 目标不高也要先抬 5cm 才能横移(老倪铁律)
        for s in chunks(pre_up, float(chunk_mm), "L2.lift", "L2.lift", "d_mm"):
            steps.append({**s, "phase": "①就地抬升(≤50mm)", "speed": speed})
    # ② 原地转身(只转不移) —— 工具系 A(X)→B(Y)→C(Z), 每段 ≤10°
    #    ⚠️ 2026-10-13 实测: pose_rot 这条腿现在**转了也不生效** —— 执行器报 `✅ SDK 腿到位 残差 0.0mm`,
    #    但姿态实测与下发前夹角 0.26°(距目标 20.49°): 控制器 `50113 [奇异规避] 路径中改变的姿态最大值超过阈值`
    #    把姿态变化拒了, 而那条腿只比**位置**残差 ⇒ 假到位。--skip-rot 走"只把位置送到位"的口径。
    for name, val in (() if skip_rot else (("a", e[0]), ("b", e[1]), ("c", e[2]))):
        if abs(val) < 0.5:
            continue
        for s in chunks(val, chunk_deg, "L2.rot_%s_pos" % name, "L2.rot_%s_neg" % name, "deg"):
            steps.append({**s, "phase": "②原地转身", "speed": rot_speed})
    # ③ 横移到目标 XY (base 系: +X 前 / -X 后 / +Y 左 / -Y 右)
    for axis, val in (("x", dd[0]), ("y", dd[1])):
        if abs(val) < 1.0:
            continue
        pos, neg = ("L2.forward", "L2.backward") if axis == "x" else ("L2.left", "L2.right")
        for s in chunks(val, chunk_mm, pos, neg, "d_mm"):
            steps.append({**s, "phase": "③水平横移(低位)", "speed": speed})
    # ④ 到目标 XY 上方后再升降剩下的垂直量 (这里才是"目标上方", 开阔)
    rest = dd[2] - pre_up
    if abs(rest) > 1.0:
        for s in chunks(rest, min(float(chunk_mm), 50.0), "L2.lift", "L2.lower", "d_mm"):
            steps.append({**s, "phase": "④在目标上方升降", "speed": speed})
    total_mm = float(np.linalg.norm(dd))
    plan = {"start": {"p": [round(float(v), 5) for v in cur["p"]], "q": [round(float(v), 5) for v in cur["q"]],
                      "src": cur["src"], "age_s": round(pose_age(cur), 2)},
            "target": {"point": target.get("point"), "p": [round(float(v), 5) for v in tp],
                       "q": [round(float(v), 5) for v in tq], "recorded_at": target.get("recorded_at")},
            "delta_mm": [round(float(v), 2) for v in dd], "dist_mm": round(total_mm, 1),
            "d_att_deg": round(ang, 2), "tool_euler_deg": [round(v, 2) for v in e],
            "n_steps": len(steps), "steps": steps}
    if total_mm > max_total_mm:
        plan["ok"] = False
        plan["why"] = "总位移 %.0fmm > 上限 %smm" % (total_mm, max_total_mm)
    else:
        plan["ok"] = True
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="侧面点0")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--speed", type=float, default=100.0)
    ap.add_argument("--rot-speed", type=float, default=150.0)
    ap.add_argument("--chunk-mm", type=float, default=50.0)
    ap.add_argument("--chunk-deg", type=float, default=10.0)
    ap.add_argument("--max-total-mm", type=float, default=1200.0)
    ap.add_argument("--skip-rot", action="store_true", help="跳过转身段(该腿当前不生效), 只把位置送到位")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    with open(LEDGER % a.to, encoding="utf-8") as fh:
        target = json.load(fh)
    target["point"] = a.to

    plan = build_plan(target, a.speed, a.rot_speed, a.chunk_mm, a.chunk_deg, a.max_total_mm, skip_rot=a.skip_rot)
    log("── 分段计划: 当前 → %s ──" % a.to)
    log("  起点 %s (帧龄 %ss, 源 %s)" % (plan["start"]["p"], plan["start"]["age_s"], plan["start"]["src"]))
    log("  目标 %s (录于 %s)" % (plan["target"]["p"], plan["target"]["recorded_at"]))
    log("  Δ = %s mm · |Δ| = %.1f mm · 姿态差 %.2f°" % (plan["delta_mm"], plan["dist_mm"], plan["d_att_deg"]))
    log("  工具系欧拉 = A %.2f° / B %.2f° / C %.2f° ⇒ 分 %d 段" % (*plan["tool_euler_deg"], plan["n_steps"]))
    for i, s in enumerate(plan["steps"], 1):
        log("   %2d %-14s %-7s %8.2f  speed=%-6s" % (i, s["phase"], s["skill"].replace("L2.", ""),
                                                     s.get("d_mm", s.get("deg")), s["speed"]))
    if not plan["ok"]:
        log("  ❌ %s" % plan["why"])
        return 1
    if a.dry:
        log("  (dry: 只出计划, 零下发)")
        return 0
    if not a.yes:
        log("  (未带 --yes ⇒ 零下发)")
        return 0

    # ── 真下发: 逐段, 每段等到位再发下一段 ──
    rep = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"), "to": a.to, "plan": plan, "steps": []}
    log("\n── 真下发 (逐段等到位) ──")
    for i, s in enumerate(plan["steps"], 1):
        key = "d_mm" if "d_mm" in s else "deg"
        val = s[key]
        g = wait_idle(timeout=90)
        if not g.get("ok"):
            log("  ⛔ 第 %d 段下发前未获空闲(控制器忙/仍在动) ⇒ 中止 (零下发)" % i)
            rep["steps"].append({"i": i, "skill": s["skill"], "aborted_before_send": True, "gate": g})
            break
        cmd_mm = val if key == "d_mm" else 0.0
        tmo = int(max(30, min(240, abs(cmd_mm) / max(0.1, s["speed"] / 10.0) * 2.5 + 20)))
        out = call(s["skill"], key, val, s["speed"], timeout=tmo + 60)
        lines = [l for l in (out.get("lines") or []) if l.strip()][-3:]
        log("  [%2d/%2d] %s %.2f (speed=%s)" % (i, len(plan["steps"]), s["skill"], val, s["speed"]))
        for l in lines:
            log("        | %s" % l[:150])
        ok_call = bool(out.get("ok", True))
        refused = any(("拒" in l) or ("🛑" in l) or ("❌" in l) for l in lines)
        w = {"ok": False, "why": "未下发/被拒"}
        if ok_call and not refused and not out.get("dry"):
            w = wait_arrive(cmd_mm, timeout=tmo) if key == "d_mm" else wait_rot(abs(val), timeout=tmo)
        rec = {"i": i, "skill": s["skill"], key: val, "phase": s["phase"], "speed": s["speed"],
               "http_ok": ok_call, "refused": refused, "wait": w, "lines": lines[:6], "_t": out.get("_t"), "err": out.get("err")}
        rep["steps"].append(rec)
        if not w.get("ok"):
            log("  ⛔ 第 %d 段未到位/被拒 ⇒ 中止剩余段 (绝不重发)" % i)
            break
    fin = read_pose()
    tp = np.array([float(x) for x in target["pos"][:3]])
    tq = np.array([float(x) for x in target["quat"]])
    rep["final"] = {"p": [round(float(v), 5) for v in fin["p"]], "q": [round(float(v), 5) for v in fin["q"]],
                    "pos_err_mm": round(float(np.linalg.norm(fin["p"] - tp)) * 1000, 2),
                    "att_err_deg": round(quat_angle(fin["q"], tq), 2), "age_s": round(pose_age(fin), 2)}
    log("\n── 终态 ──")
    log("  实测 %s" % [round(float(v), 5) for v in fin["p"]])
    log("  目标 %s" % [round(float(v), 5) for v in tp])
    log("  位置差 %.2f mm · 姿态差 %.2f°" % (rep["final"]["pos_err_mm"], rep["final"]["att_err_deg"]))
    rp = a.report or os.path.join(REPDIR, "stepwise_goto_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    log("  报告: %s" % rp)
    return 0 if rep["final"]["att_err_deg"] < 5 and rep["final"]["pos_err_mm"] < 30 else 1


if __name__ == "__main__":
    sys.exit(main())
