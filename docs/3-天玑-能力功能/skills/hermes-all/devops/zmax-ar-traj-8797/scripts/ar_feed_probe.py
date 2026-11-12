#!/usr/bin/env python3
"""8797 AR 页驱动源一键体检: 四条源各给年龄 + 仿真骨骼是否真在动。

用法:
    python3 scripts/ar_feed_probe.py
    python3 scripts/ar_feed_probe.py --ar http://127.0.0.1:8797 --render http://127.0.0.1:8802

只读、不下发任何指令。退出码: 0=至少一条新鲜, 2=四条全过期(页面只可能画静态几何)。
判据口径: 真机位姿 <=8s 且非 stale / ar_cmd <=3s / 相机看 online / 骨骼看 L,R 两次采样位移,
不看 /bones.json 的 n(n 是物理计数, 停机时照样涨)。
"""
import argparse
import json
import sys
import time
import urllib.request


def get(base, path, timeout=4.0):
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore")), None
    except Exception as e:                                          # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:120])


def bones_motion(render, wait=1.2):
    a, ea = get(render, "/bones.json")
    if ea:
        return None, ea
    time.sleep(wait)
    b, eb = get(render, "/bones.json")
    if eb:
        return None, eb
    mx = 0.0
    for side in ("L", "R"):
        for s1, s2 in zip(a.get(side) or [], b.get(side) or []):
            for p, q in zip(s1, s2):
                mx = max(mx, max(abs(p[i] - q[i]) for i in range(3)))
    return {"dmax_m": round(mx, 4), "n0": a.get("n"), "n1": b.get("n")}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ar", default="http://127.0.0.1:8797")
    ap.add_argument("--render", default="http://127.0.0.1:8802")
    ap.add_argument("--pose-max-age", type=float, default=8.0)
    ap.add_argument("--cmd-max-age", type=float, default=3.0)
    args = ap.parse_args()

    rows, fresh = [], 0

    tcp, err = get(args.ar, "/api/tcp")
    if err:
        rows.append(("真机位姿 /api/tcp", "-", "ERR " + err))
    else:
        age = tcp.get("age_s")
        stale = bool(tcp.get("stale"))
        ok = isinstance(age, (int, float)) and age <= args.pose_max_age and not stale
        fresh += 1 if ok else 0
        rows.append(("真机位姿 /api/tcp",
                     ("%.1fs" % age) if isinstance(age, (int, float)) else "-",
                     ("新鲜" if ok else "过期")
                     + (" · stale" if stale else "")
                     + ("" if tcp.get("ok") else " · ok=false")))

    cmd, err = get(args.ar, "/api/ar/cmd")
    if err:
        rows.append(("动作帧 /api/ar/cmd", "-", "ERR " + err))
    else:
        age = cmd.get("age_s")
        ok = bool(cmd.get("fresh")) and isinstance(age, (int, float)) and age <= args.cmd_max_age
        fresh += 1 if ok else 0
        rows.append(("动作帧 /api/ar/cmd",
                     ("%.1fs" % age) if isinstance(age, (int, float)) else "-",
                     ("新鲜" if ok else "过期") + " · src=%s" % (cmd.get("src") or "-")))

    cams, err = get(args.ar, "/api/cams")
    if err:
        rows.append(("相机 /api/cams", "-", "ERR " + err))
    else:
        cs = (cams or {}).get("cams") or {}
        on = [k for k, v in cs.items() if (v or {}).get("online") is True]
        fresh += 1 if on else 0
        rows.append(("相机 /api/cams", "%d/%d 在线" % (len(on), len(cs)),
                     "有底图" if on else "全 offline(画面没有相机底图)"))

    mv, err = bones_motion(args.render)
    if err:
        rows.append(("仿真骨骼 /bones.json", "-", "ERR " + err))
    else:
        moving = mv["dmax_m"] > 0.0005
        fresh += 1 if moving else 0
        rows.append(("仿真骨骼 /bones.json", "%.1fmm/1.2s" % (mv["dmax_m"] * 1000),
                     ("在动" if moving else "静止")
                     + " · n %s -> %s (n 涨不等于臂在动)" % (mv["n0"], mv["n1"])))

    width = max(len(r[0]) for r in rows)
    print("源".ljust(width), "  年龄/量      判定")
    for name, age, verdict in rows:
        print(name.ljust(width), " ", str(age).ljust(12), verdict)
    print("-" * (width + 52))
    if fresh == 0:
        print("verdict: 四条源全过期 => 页面只能画静态几何。先查网络/位姿桥(39071), 再谈页面。")
        return 2
    print("verdict: %d 条新鲜 => 页面应该能画出来; 仍为空就查对应层的开关与渲染闸。" % fresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
