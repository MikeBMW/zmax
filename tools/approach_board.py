#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把臂从当前位置摆到标定靶前（四段纯平移，逐段核真值）。

老倪 2026-10-25 现场授权: 「授权了，现场安全」
口径（照 real-arm-motion-control 技能）:
  · 一条一段、绝不并发; 每段到位判据 = 连续 3 次 |Δ|<2mm 且真值帧龄新鲜
  · 段内若 25s 位置没变 ⇒ 判"没动"中止(不重发)
  · 抬升 +30mm 优先(天花板 0.3885, 留 44mm); 全程不与姿态混段(不改 quat)
  · 目标: x 0.330→0.737 / y 0.322→0.203 / z 0.314→0.344
用法: ./gui-venv311/bin/python tools/approach_board.py [--dry]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8793/ctl/move"
AUTH = "/home/ubuntu/zmax/zmax_data/ctl_auth.json"
NM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")
REMOTE = (
    'source /opt/ros/humble/setup.bash 2>/dev/null; '
    'for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done; '
    'export ROS_DOMAIN_ID=0; timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose'
)


def pose():
    """直读 Orin 宿主 ROS 的 TCP 真值 (pos3 + quat4)，失败返回 None。"""
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "orin",
                            "bash", "-lc", REMOTE], capture_output=True, text=True, timeout=25)
        v = [float(x) for x in NM.findall(r.stdout)]
        return v[:7] if len(v) >= 7 else None
    except Exception:                                                        # noqa: BLE001
        return None


def auth_left():
    try:
        d = json.load(open(AUTH, encoding="utf-8"))
        return d.get("until", 0) - time.time(), bool(d.get("armed", True))
    except Exception:                                                        # noqa: BLE001
        return 0.0, False


def send(skill, d_mm, speed=100, dry=False):
    body = json.dumps({"skill": skill, "d_mm": d_mm, "speed_mm_s": speed,
                       "arm": 0 if dry else 1}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:                                      # 403 = 未授权
        return {"ok": False, "denied": True, "code": e.code, "msg": e.read().decode()[:160]}
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "msg": str(e)[:160]}


def wait_arrive(target, tag, timeout=180.0):
    """等到位: 连续 3 次 |err|<2mm; 中途 25s 纹丝不动判没动。"""
    t0 = time.time()
    hits = 0
    last = None
    last_change = time.time()
    while time.time() - t0 < timeout:
        v = pose()
        now = time.time()
        if v is None:
            print("   [%s] 真值读不到，重试" % tag, flush=True)
            time.sleep(2)
            continue
        err = [target[i] - v[i] for i in range(3)]
        d = sum(x * x for x in err) ** 0.5
        print("   [%s] t=%4.1fs pos=(%.4f,%.4f,%.4f) err=%.1fmm" %
              (tag, now - t0, v[0], v[1], v[2], d * 1000), flush=True)
        if last is not None:
            moved = sum((v[i] - last[i]) ** 2 for i in range(3)) ** 0.5
            if moved > 0.0005:
                last_change = now
        last = v
        if d < 0.002:
            hits += 1
            if hits >= 3:
                return True, v
        else:
            hits = 0
        if now - last_change > 25.0:
            print("   [%s] ⛔ 25s 位置未变 ⇒ 判未执行，中止(不重发)" % tag, flush=True)
            return False, v
        time.sleep(1.0)
    return False, last


def main() -> int:
    dry = "--dry" in sys.argv
    v = pose()
    if not v:
        print("✗ 读不到 TCP 真值，先修链路")
        return 2
    cur = v[:3]
    print("起点 TCP  (%.4f, %.4f, %.4f)" % tuple(cur), flush=True)
    q0 = v[3:7]

    # 四段: (技能, 距离mm, 说明)
    plan = [("L2.lift", 30.0, "① 就地抬升 +30mm (朝天花板留余量)"),
            ("L2.forward", 300.0, "② 前进 +X 300mm"),
            ("L2.forward", 107.0, "③ 前进 +X 107mm (累计 +407)"),
            ("L2.right", 119.0, "④ 向右 −Y 119mm")]

    for skill, d_mm, note in plan:
        left, armed = auth_left()
        if not armed or left < 45:
            print("⛔ 授权剩余 %.0fs，不足以再发一段 —— 停" % left)
            return 3
        cur = pose()
        if not cur:
            print("⛔ 真值读不到 —— 停")
            return 3
        # 目标方向: lift=+z / forward=+x / right=-y
        tgt = list(cur[:3])
        if skill == "L2.lift":
            tgt[2] += d_mm / 1000.0
        elif skill == "L2.forward":
            tgt[0] += d_mm / 1000.0
        elif skill == "L2.right":
            tgt[1] -= d_mm / 1000.0
        print("\n%s\n   当前 (%.4f,%.4f,%.4f) → 目标 (%.4f,%.4f,%.4f) · 授权剩 %.0fs"
              % (note, cur[0], cur[1], cur[2], tgt[0], tgt[1], tgt[2], left), flush=True)
        r = send(skill, d_mm, speed=100, dry=dry)
        print("   回执: %s" % json.dumps({k: r.get(k) for k in ("ok", "dry", "denied", "msg")},
                                          ensure_ascii=False)[:300], flush=True)
        if dry:
            continue
        if not r.get("ok"):
            print("⛔ 下发被拒，中止")
            return 4
        ok, got = wait_arrive(tgt, skill, timeout=90 + d_mm / 6.0)
        if not ok:
            print("⛔ 未按预期到位，中止 —— 绝不重发。最后真值: %s"
                  % (["%.4f" % x for x in got[:3]] if got else "无"))
            return 5
        print("   ✅ 到位 err<2mm ×3", flush=True)

    fin = pose()
    print("\n终点 TCP (%.4f, %.4f, %.4f)" % tuple(fin[:3]) if fin else "\n终点读不到")
    if fin:
        dq = sum((fin[3 + i] - q0[i]) ** 2 for i in range(4)) ** 0.5
        print("姿态变化 (四元数差范数) %.5f  ← 应为 ~0 (纯平移)" % dq)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
