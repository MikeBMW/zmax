# -*- coding: utf-8 -*-
"""bridge_target.py — plan 节点桥接: 仿真 v_ff 的**方向** → 真机 target 点的慢速增量

老倪 2026-10-18 现场口径（逐字）:
  「正确接法是: 只取 v_ff 的方向做增量, 叠加在真机当前 TCP 上」
  「真正输出的速度, 你要控制, 不能用仿真的速度直接输出。你要慢」「不要超过 10mm/s」

本文件只做**目标点**这一件事, 不动作:
  · 目标 = 真机当前 TCP(8793 /pose 真值) + 偏移; 偏移按 v_ff 的**单位方向** × v_cmd(≤10mm/s) 积分
  · 姿态 = 真机当前 quat 原样照抄（桥没有旋转, 不编姿态）
  · 领先量上限 LEAD_MAX_MM: 真机没动时目标不会一路跑飞（防"目标跑出可达域"）
  · 只写 plan_req.json（现有规划请求格式, goal_src=bridge_vff）+ 状态文件
  · **绝不** POST /ctl/move, 绝不写动作授权; 要真动仍走 8793 授权 + L2 收口

用法:
  ./gui-venv311/bin/python tools/bridge_target.py                 # 20Hz 跑, Ctrl-C 停 (停=目标回到真机位姿)
  ./gui-venv311/bin/python tools/bridge_target.py --rate 20 --lead-max 30
  ./gui-venv311/bin/python tools/bridge_target.py --dry-print     # 只打印不进 plan_req.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
LIVE = os.path.join(REPO, "zmax_data", "ss_live")
PLAN_DIR = os.path.join(REPO, "zmax_data", "runtime", "moveit_plan")
REQ = os.path.join(PLAN_DIR, "plan_req.json")
VFF = os.path.join(LIVE, "plan_from_vff.json")
STATUS = os.path.join(LIVE, "bridge_target.json")
POSE_URL = "http://127.0.0.1:8793/pose"
CAP_MAX_MMS = 10.0                      # ⛔ 真机硬上限 (与画布/控制台同一个数)


def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                   # noqa: BLE001
        return None


def real_pose():
    """真机当前 TCP + 姿态 (8793 /pose, 50Hz 真值, 带帧龄)。失败返回 None, 不编数。"""
    try:
        with urllib.request.urlopen(POSE_URL, timeout=2.0) as r:
            d = json.loads(r.read().decode("utf-8"))
        xyz = [float(v) for v in (d.get("xyz") or [])][:3]
        quat = [float(v) for v in (d.get("quat") or [])][:4]
        if len(xyz) != 3:
            return None
        return {"xyz": xyz, "quat": quat, "age_s": float(d.get("age_s") or -1.0),
                "file_age_s": float(d.get("file_age_s") or -1.0)}
    except Exception:                                                   # noqa: BLE001
        return None


def real_state():
    """真机 jpos(6) —— 规划请求要带起点关节 (与 moveit_plan_req 同源: SDK 直采优先, 退只读 tap)。

    🔴 SDK 直采文件 = rokae_tcp_sampler 的 tcp_out/latest.json (50Hz 真值, joint[:6] 就是真 6 关节)。
       只读 tap(state_*.jsonl) 里 jpos 常为空 —— 实测本机 tap 最新一行没有 jpos,
       所以原来只读 tap ⇒ real_state() 返回 None ⇒ plan_req.json 根本不写 (目标永远不动)。
    """
    import glob
    sdk = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
    try:
        if time.time() - os.path.getmtime(sdk) <= 2.0:
            with open(sdk, encoding="utf-8") as f:
                d = json.load(f)
            jp = d.get("joint")
            if isinstance(jp, list) and len(jp) >= 6:
                return {"jpos": [float(v) for v in jp[:6]],
                        "tcp": [float(d.get(k, 0.0)) for k in ("x", "y", "z")],
                        "tcp_quat": [float(d.get(k, 0.0)) for k in ("qx", "qy", "qz", "qw")],
                        "t": d.get("t"), "src_file": "rokae_sdk/tcp_out/latest.json"}
    except Exception:                                                   # noqa: BLE001
        pass
    cand = sorted(glob.glob(os.path.join(LIVE, "state_*.jsonl")), key=os.path.getmtime, reverse=True)
    if not cand:
        return None
    p = cand[0]
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:                                           # noqa: BLE001
                continue
            jp = d.get("jpos")
            if isinstance(jp, list) and len(jp) == 6:
                return {"jpos": [float(v) for v in jp],
                        "tcp": [float(v) for v in (d.get("tcp") or [])][:3],
                        "tcp_quat": [float(v) for v in (d.get("tcp_quat") or [])][:4],
                        "t": d.get("t"), "src_file": os.path.basename(p)}
    except Exception:                                                   # noqa: BLE001
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, default=20.0, help="控制频率 Hz (默认 20)")
    ap.add_argument("--lead-max", type=float, default=30.0, help="目标领先真机的上限 mm (默认 30)")
    ap.add_argument("--dry-print", action="store_true", help="只打印, 不写 plan_req.json")
    a = ap.parse_args()

    dt = 1.0 / max(1.0, a.rate)
    off = [0.0, 0.0, 0.0]          # 目标相对真机 TCP 的偏移 (m)
    t_prev = time.time()
    n = 0
    print("🌉 bridge_target 起: %.0fHz · 领先上限 %.0fmm · 硬上限 %.0fmm/s · 只写目标不下发"
          % (a.rate, a.lead_max, CAP_MAX_MMS), flush=True)
    try:
        while True:
            now = time.time()
            _dt = min(0.2, max(0.0, now - t_prev))
            t_prev = now
            v = _jload(VFF) or {}
            st = real_pose()
            if not st:
                print("⚠️ 读不到真机位姿 (8793 /pose), 跳过本拍, 不编目标", flush=True)
                time.sleep(dt)
                continue
            on = bool(v.get("bridge"))
            vc = [float(x) / 1000.0 for x in (v.get("v_cmd_mms") or [0, 0, 0])][:3]
            if len(vc) < 3:
                vc = [0.0, 0.0, 0.0]
            spd = (vc[0] ** 2 + vc[1] ** 2 + vc[2] ** 2) ** 0.5
            if not on:
                off = [0.0, 0.0, 0.0]                 # 桥关 ⇒ 目标贴回真机当前位姿
            else:
                cap = min(float(v.get("cap_mms") or CAP_MAX_MMS), CAP_MAX_MMS)
                if spd > cap and spd > 0:              # 双保险: 只按方向, 幅值再压一次
                    vc = [x * (cap / spd) for x in vc]
                    spd = cap
                off = [off[i] + vc[i] * _dt for i in range(3)]
                lead = (off[0] ** 2 + off[1] ** 2 + off[2] ** 2) ** 0.5 * 1000.0
                if lead > a.lead_max:                  # 领先量封顶 (真机没动时目标不跑飞)
                    k = (a.lead_max / lead)
                    off = [x * k for x in off]
            tgt = [st["xyz"][i] + off[i] for i in range(3)]
            lead_mm = (off[0] ** 2 + off[1] ** 2 + off[2] ** 2) ** 0.5 * 1000.0

            payload = {
                "ts": now, "on": on, "mode": "target_only(不下发)",
                "real_xyz": [round(x, 6) for x in st["xyz"]],
                "target_xyz": [round(x, 6) for x in tgt],
                "offset_mm": [round(x * 1000.0, 2) for x in off],
                "lead_mm": round(lead_mm, 2),
                "v_cmd_mms": [round(x * 1000.0, 2) for x in vc],
                "speed_cmd_mms": round(spd * 1000.0, 2), "cap_mms": CAP_MAX_MMS,
                "pose_age_s": st["age_s"], "vff_frame": v.get("frame"),
                "note": ("桥开: 只跟 v_ff 方向, 目标慢速增量 (≤%.0fmm/s, 领先≤%.0fmm)"
                         % (CAP_MAX_MMS, a.lead_max)) if on else "桥关: 目标 = 真机当前位姿 (不动)",
            }
            try:
                tmp = STATUS + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(tmp, STATUS)
            except Exception:                                           # noqa: BLE001
                pass

            if on and not a.dry_print:
                rs = real_state()
                if rs:
                    rec = {"ts": now, "goal_name": "bridge_vff", "goal_xyz": [round(x, 6) for x in tgt],
                           "goal_quat": st["quat"], "goal_src": "bridge_vff", "goal_stage": "",
                           "jpos": rs["jpos"], "tcp": st["xyz"], "tcp_quat": st["quat"],
                           "real_t": rs.get("t"), "src": "real(SDK/tap readonly)"}
                    try:
                        tmp = REQ + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(rec, f, ensure_ascii=False)
                        os.replace(tmp, REQ)
                    except Exception as e:                              # noqa: BLE001
                        print("⚠️ 写 plan_req 失败: %s" % str(e)[:100], flush=True)

            n += 1
            if n % int(max(1, a.rate)) == 0:
                print("🌉 %s 目标=(%.3f,%.3f,%.3f) 真机=(%.3f,%.3f,%.3f) 领先%.1fmm 输出%.1fmm/s%s"
                      % ("开" if on else "关", tgt[0], tgt[1], tgt[2], st["xyz"][0], st["xyz"][1], st["xyz"][2],
                         lead_mm, spd * 1000.0, "  (只打印)" if a.dry_print else ""), flush=True)
            time.sleep(dt)
    except KeyboardInterrupt:
        print("⏹ 停: 目标回到真机当前位姿 (最后不写请求)", flush=True)


if __name__ == "__main__":
    main()
