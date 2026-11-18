#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AOI 3D 位姿引导 —— probe/solve 标定闭环(单轴 Y, 只走 2mm)。

为什么要 probe: mm/px 与「世界 Y 正负 ↔ 屏幕左右」两件都不知道。
  · mm/px 估值带宽 0.0118~0.0177(差 50%) ⇒ 按错的走 344px 会偏 2mm;
  · 轴符号猜错 ⇒ 反方向跑, 越走越远。
所以先走 2mm 测符号和比例, 反算完再给终值。

安全:
  · 只动 Y, x/z/姿态全锁(姿态从桥实时读, 原样回填, 不让它漂);
  · speed 默认 5mm/s ⇒ 2mm 约 0.4s, 慢到肉眼可拦;
  · 前置: powerState=on + operateMode=idle, 不满足直接拒;
  · 授权: 认 zmax_data/ctl_auth.json(与 8793/8797 同一份唯一依据);
  · --dry 只算不发。

用法:
  ./gui-venv311/bin/python tools/aoi_guide_probe.py --dry     # 只算
  ./gui-venv311/bin/python tools/aoi_guide_probe.py           # 真走 2mm 并 solve
  ./gui-venv311/bin/python tools/aoi_guide_probe.py --undo    # 走完想退回: 反向 2mm
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.environ.get("ZMAX_BRIDGE_URL", "http://192.168.23.66:39061")
AOI = os.environ.get("ZMAX_AOI_URL", "http://192.168.23.23:10082")
AUTH = os.path.join(REPO, "zmax_data", "ctl_auth.json")


def _post(url, payload, timeout=90):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _rpy2quat(rx, ry, rz):
    """ZYX 欧拉(rad) → 四元数 (x,y,z,w)。珞石 endInRef 后三位按 Rz·Ry·Rx 口径。"""
    cx, cy, cz = math.cos(rx / 2), math.cos(ry / 2), math.cos(rz / 2)
    sx, sy, sz = math.sin(rx / 2), math.sin(ry / 2), math.sin(rz / 2)
    return [
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    ]


def _pose_now():
    """桥实时读数 ⇒ (p[m], q, rpy_deg, raw)。不用缓存, 也不用手推。"""
    d = _get(BRIDGE + "/status")
    s = d.get("status") or {}
    e = s.get("endInRef") or []
    if len(e) < 6:
        raise RuntimeError("桥 status 没有 endInRef: %r" % (list(s.keys()),))
    p = [float(e[0]), float(e[1]), float(e[2])]
    rpy = [float(e[3]), float(e[4]), float(e[5])]
    return p, _rpy2quat(*rpy), [math.degrees(v) for v in rpy], s


def _armed():
    """与 8793/8797 同一份唯一依据。debug 档 = armed(现场调试期常驻)。"""
    try:
        d = json.load(open(AUTH))
    except Exception as e:                                                   # noqa: BLE001
        return False, "读不到授权文件: %s" % (e,)
    until = float(d.get("until") or 0.0)
    mode = str(d.get("mode") or "")
    if mode == "debug":
        return True, "debug 档"
    if until > time.time():
        return True, "定时窗口 剩 %.0fs" % (until - time.time())
    return False, "未授权(mode=%s until=%.0f 已过期)" % (mode, until)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只算不发")
    ap.add_argument("--undo", action="store_true", help="反向走回 2mm")
    ap.add_argument("--axis", default="Y")
    ap.add_argument("--speed", type=float, default=5.0, help="mm/s, 上限 20(本工具自限)")
    ap.add_argument("--step", type=float, default=2.0, help="试探位移 mm")
    args = ap.parse_args()

    p0, q0, rpy0, st = _pose_now()
    print("① 桥实时位姿 p=%.3f/%.3f/%.3f mm  rpy=%.2f/%.2f/%.2f°" %
          (p0[0] * 1000, p0[1] * 1000, p0[2] * 1000, rpy0[0], rpy0[1], rpy0[2]))
    print("   powerState=%s operateMode=%s" % (st.get("powerState"), st.get("operateMode")))

    ok, why = _armed()
    print("② 授权: %s (%s)" % ("✅" if ok else "❌", why))
    if not ok and not args.dry:
        return 2
    _ps = str(st.get("powerState") or "").lower()
    if not args.dry and not ("on" in _ps and "off" not in _ps):
        print("❌ powerState=%s 未上电, 拒发" % st.get("powerState"))
        return 3
    # 珞石: operateMode = automatic(自动, 可接受 SDK 下发) / manual(手动示教, 拒发)。
    #   ⚠️ 不要拿 idle 判 —— idle 是 operation_state(是否在运动中), 不是模式。
    _om = str(st.get("operateMode") or "")
    if not args.dry and "automatic" not in _om.lower():
        print("❌ operateMode=%s 不是 automatic(手动示教态), 拒发" % _om)
        return 3

    # ③ 问 10082 要引导: probe 给的是「沿 axis 走 step mm」的目标位姿
    mode = "probe" if not args.undo else "probe"
    req = {"pose": {"x": p0[0] * 1000, "y": p0[1] * 1000, "z": p0[2] * 1000},
           "axis": args.axis, "mode": mode, "max_step_mm": args.step}
    g = _post(AOI + "/guide_pose", req)
    gold = g.get("gold") or {}
    guide = g.get("guide") or {}
    print("③ 10082 gold: n=%s center=%s off_px=%s pitch=%s" %
          (gold.get("n"), gold.get("center_px"), gold.get("off_px"), gold.get("pitch_px")))
    print("   10082 guide: act=%s d_mm=%s target=%s" %
          (guide.get("act"), guide.get("d_mm"), guide.get("pose_target")))
    tgt = guide.get("pose_target") or {}
    if not tgt:
        print("❌ 10082 没给 pose_target: %s" % str(g.get("msg"))[:80])
        return 4

    d_mm = float(guide.get("d_mm") or 0.0)
    if args.undo:
        d_mm = -d_mm
    axis_i = {"X": 0, "Y": 1, "Z": 2}[args.axis]
    p1 = list(p0)
    p1[axis_i] = float(tgt.get("x" if axis_i == 0 else ("y" if axis_i == 1 else "z"))) / 1000.0

    print("④ 目标 p=%.3f/%.3f/%.3f mm (Δ%s=%+.2fmm) speed=%.1fmm/s" %
          (p1[0] * 1000, p1[1] * 1000, p1[2] * 1000, args.axis, (p1[axis_i] - p0[axis_i]) * 1000, args.speed))

    if args.dry:
        print("🧪 DRY-RUN 未下发")
        return 0

    t0 = time.time()
    res = _post(BRIDGE + "/move_pose", {"p": p1, "q": q0, "speed": args.speed, "dry": False}, timeout=120)
    print("⑤ 下发: ok=%s why=%s (%s) %.1fs" %
          (res.get("ok"), str(res.get("why"))[:80], res.get("via") or "", time.time() - t0))
    if not res.get("ok"):
        return 5

    # ⑥ 等真到位: 连续 3 次读数都不动才算稳(不认回执, 只认真值)
    tgt_mm = [(p1[i] - p0[i]) * 1000 for i in range(3)]
    last, stable, moved = None, 0, False
    for k in range(40):
        time.sleep(0.6)
        try:
            pn, _, rn, sn = _pose_now()
        except Exception:                                                    # noqa: BLE001
            continue
        d = [(pn[i] - p0[i]) * 1000 for i in range(3)]
        if max(abs(d[i]) for i in range(3)) > 0.15:
            moved = True
        if last is not None and max(abs((pn[i] - last[i]) * 1000) for i in range(3)) < 0.03:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        last = pn
    pn, _, rn, sn = _pose_now()
    d = [(pn[i] - p0[i]) * 1000 for i in range(3)]
    rot = max(abs(rn[i] - rpy0[i]) for i in range(3))
    print("⑥ 真值位移 Δ=%+.3f/%+.3f/%+.3f mm 姿态漂 %.3f° operateMode=%s" %
          (d[0], d[1], d[2], rot, sn.get("operateMode")))
    if not moved:
        print("❌ 回执说成功但真值一位没变 ⇒ 假到位, 不写标定")
        return 6

    # ⑦ solve: 用前后 center_px 反算 mm/px 与轴符号
    req2 = dict(req)
    req2["mode"] = "solve"
    req2["pose"] = {"x": pn[0] * 1000, "y": pn[1] * 1000, "z": pn[2] * 1000}
    g2 = _post(AOI + "/guide_pose", req2)
    print("⑦ solve: ok=%s %s" % (g2.get("ok"), json.dumps(g2.get("guide") or g2.get("calib") or {},
                                                             ensure_ascii=False)[:300]))
    print("   实测位移 → %s" % json.dumps({"delta_mm": [round(v, 3) for v in d]}, ensure_ascii=False))
    return 0 if g2.get("ok") else 7


if __name__ == "__main__":
    sys.exit(main())
