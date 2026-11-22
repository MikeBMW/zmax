#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_v2_phase.py —— 从「手走重录」的 239 点新表生成 8815 相位看板要用的三件套

背景(老倪 2026-11-21): 旧 215 点表在插入段垂直下压 38mm 撞机, 现场重走一遍后
重采样出 239 点新表 `real_traj_joints_v2.json`。看板(8815)原来只认 215 点的
traj_phase/traj_hopf, 所以这里为新表补齐:

  zmax_data/rokae_sdk/traj_phase_v2.json   frames[i].{s, prog, s_mm, su, t}
  zmax_data/rokae_sdk/traj_hopf_v2.json    frames[i].{n, phi_deg, p_mm, s, s_mm}
  tools/web/real_traj_joints_v2.json       看板 _live() 读的那份(米)
  zmax_data/rokae_sdk/sectors_v2.json      节拍扇区(来自回放日志的实测块耗时)

相位口径与旧表一致: s = 沿 TCP 折线的弧长 / 末帧弧长 (0→1), s_mm = 累计毫米。
Hopf 口径与 tools/se3_hopf.py 一致: 由 rpy → 四元数 → n=(2(xz+wy),2(yz-wx),w²+z²-x²-y²), φ=2·atan2(z,w)。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(REPO, "zmax_data", "rokae_sdk")
WEB = os.path.join(REPO, "tools", "web")


def _quat_from_rpy(r, p, y):
    """roll/pitch/yaw(rad) → (w,x,y,z)，与珞石 rpy 同一约定(z-y-x 内旋)。"""
    cr, sr = math.cos(r / 2.0), math.sin(r / 2.0)
    cp, sp = math.cos(p / 2.0), math.sin(p / 2.0)
    cy, sy = math.cos(y / 2.0), math.sin(y / 2.0)
    return (cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy)


def build(src: str, stop_f: str, chunk_log: str | None, head_secs: float = 45.0) -> dict:
    tj = json.load(open(src, encoding="utf-8"))
    fr = tj["frames"]
    P = [[c * 1000.0 for c in f["p"][:3]] for f in fr]

    # ① 弧长(相位): 逐帧 TCP 折线累计
    s_mm, cum = [0.0], 0.0
    for a, b in zip(P, P[1:]):
        cum += sum((b[k] - a[k]) ** 2 for k in range(3)) ** 0.5
        s_mm.append(cum)
    tot = s_mm[-1] or 1.0

    # ② Hopf: rpy → 四元数 → n(轴) / φ(滚转)
    ph, hf = [], []
    for k, f in enumerate(fr):
        s = s_mm[k] / tot
        ph.append({"i": k, "s": round(s, 6), "prog": round(s, 6),
                   "su": round(math.sqrt(max(0.0, s * (1.0 - s))), 6),
                   "s_mm": round(s_mm[k], 1),
                   "ds_mm": round(s_mm[k] - (s_mm[k - 1] if k else 0.0), 1),
                   "t": f.get("t")})
        r, p_, y = (f.get("rpy") or [0.0, 0.0, 0.0])[:3]
        w, x, yy, z = _quat_from_rpy(r, p_, y)
        nn = (w * w + x * x + yy * yy + z * z) ** 0.5 or 1.0
        w, x, yy, z = w / nn, x / nn, yy / nn, z / nn
        n = [2.0 * (x * z + w * yy), 2.0 * (yy * z - w * x),
             w * w + z * z - x * x - yy * yy]
        ln = math.sqrt(sum(v * v for v in n)) or 1.0
        n = [v / ln for v in n]
        hf.append({"i": k, "n": [round(v, 6) for v in n],
                   "phi_deg": round(math.degrees(2.0 * math.atan2(z, w)), 3),
                   "dn_deg": 0.0, "dphi_deg": 0.0,
                   "p_mm": [round(v, 1) for v in P[k]],
                   "s": round(s, 6), "su": round(math.sqrt(max(0.0, s * (1.0 - s))), 6),
                   "phi": round(s, 6), "s_mm": round(s_mm[k], 1), "prog": round(s, 6)})

    summary = {"n_frames": len(fr), "len_mm": round(tot, 1),
               "dur_s": tj.get("dur_s"), "src": os.path.basename(src)}
    json.dump({"frames": ph, "summary": summary},
              open(os.path.join(SDK, "traj_phase_v2.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    json.dump({"frames": hf, "summary": summary},
              open(os.path.join(SDK, "traj_hopf_v2.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    shutil.copyfile(src, os.path.join(WEB, "real_traj_joints_v2.json"))

    # ③ 节拍扇区: 从回放日志的 chunk 行取实测秒数(没有日志就按弧长均匀摊)
    ss = [f["s"] for f in ph]
    blocks = []
    if chunk_log and os.path.exists(chunk_log):
        for ln in open(chunk_log, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if not ln.startswith('{"step": "chunk"'):
                continue
            try:
                st = json.loads(ln)
            except Exception:                                            # noqa: BLE001
                continue
            i0, i1 = int(st["i0"]), int(st["i1"])
            if not (0 <= i0 < len(ss) and 0 <= i1 < len(ss)):
                continue
            blocks.append({"i0": i0, "i1": i1, "n_pts": i1 - i0 + 1,
                           "s0": ss[i0], "s1": ss[i1], "t_s": st.get("secs"),
                           "speed": st.get("speed"), "err": st.get("err_deg"),
                           "axis_max": 0.0, "roll_max": 0.0,
                           "stop": bool(st.get("stop")), "name": st.get("name")})
    # 日志可能被截头(第一条 chunk 不是 #0) ⇒ 给起点补一块, 否则环上 0 段是空的
    if blocks and blocks[0]["i0"] > 0:
        _h = blocks[0]["i0"] - 1
        blocks.insert(0, {"i0": 0, "i1": _h, "n_pts": _h + 1, "s0": ss[0], "s1": ss[_h],
                          "t_s": head_secs, "speed": 15.0, "err": None,
                          "axis_max": 0.0, "roll_max": 0.0, "stop": False,
                          "name": "起点→首个停点", "synthetic": True})
    if not blocks:
        blocks = [{"i0": 0, "i1": len(ss) - 1, "n_pts": len(ss), "s0": 0.0, "s1": 1.0,
                   "t_s": tj.get("dur_s"), "speed": None, "err": None,
                   "axis_max": 0.0, "roll_max": 0.0, "stop": False}]
    json.dump({"blocks": blocks, "summary": summary},
              open(os.path.join(SDK, "sectors_v2.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    stops = json.load(open(stop_f, encoding="utf-8")) if os.path.exists(stop_f) else {}
    named = [(int(k), v.get("name")) for k, v in stops.items() if v.get("stop")]
    named.sort()
    return {"n_frames": len(fr), "len_mm": round(tot, 1), "n_blocks": len(blocks),
            "n_stop": len(named), "stops": named[:3] + ["..."] + named[-2:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(SDK, "real_traj_joints_v2.json"))
    ap.add_argument("--stops", default=os.path.join(SDK, "point_stops_v2.json"))
    ap.add_argument("--chunks", default=None, help="回放日志(含 chunk 行), 缺省按弧长摊")
    ap.add_argument("--head-secs", type=float, default=45.0,
                    help="日志被截头时, 起点到首个 chunk 的实测秒数(#0→#31 实测≈45s)")
    a = ap.parse_args()
    out = build(a.src, a.stops, a.chunks, a.head_secs)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
