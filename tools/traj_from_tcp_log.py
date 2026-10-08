#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traj_from_tcp_log.py — 从 TCP 直读流水里抽出"人手动拖动的那段轨迹", 生成可复现技能。

老倪 2026-10-08: 「你得按照我拖动的轨迹走」—— 人手拖过的路径天然安全(现场目视过),
把它变成执行器能逐点走的小段航点(每 25mm 一个), 单段位移小 ⇒ 不会触发 50121/50113 奇异规避。

用法:
  python3 tools/traj_from_tcp_log.py --path <tcp_direct_*.jsonl> \
      --from "13:11:13" --to "13:12:49" --spacing 25 --reverse \
      --skill-id L2.replay_traj --out /tmp/traj.json [--register]

--reverse: 从轨迹终点走回起点(比如把臂开回起点)。
--register: 把技能写进 data/skills/l2_atomic/registry.json(先自动备份到 /tmp)。
"""
import argparse, json, math, os, shutil, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")


def load(path, t_from, t_to):
    sz = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, sz - 16 * 1024 * 1024))
        f.readline()
        rows = []
        for l in f:
            try:
                d = json.loads(l)
            except Exception:
                continue
            if all(k in d for k in ("ts", "x", "y", "z")):
                rows.append(d)
    def hhmm(ts):
        return time.strftime("%H:%M:%S", time.localtime(ts))
    sel = [r for r in rows if (not t_from or hhmm(r["ts"]) >= t_from) and (not t_to or hhmm(r["ts"]) <= t_to)]
    return sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--from", dest="t_from", default=None)
    ap.add_argument("--to", dest="t_to", default=None)
    ap.add_argument("--spacing", type=float, default=25.0, help="航点间距(mm)")
    ap.add_argument("--reverse", action="store_true")
    ap.add_argument("--skill-id", default="L2.replay_traj")
    ap.add_argument("--out", default=None)
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args()

    seg = load(a.path, a.t_from, a.t_to)
    if len(seg) < 10:
        raise SystemExit("❌ 该时间段只有 %d 条采样, 不够" % len(seg))
    path = [seg[0]]
    for p, q in zip(seg, seg[1:]):
        if math.dist((p["x"], p["y"], p["z"]), (q["x"], q["y"], q["z"])) * 1000 > 0.3 and (q["ts"] - p["ts"]) < 2.0:
            path.append(q)
    L = sum(math.dist((p["x"], p["y"], p["z"]), (q["x"], q["y"], q["z"])) * 1000 for p, q in zip(path, path[1:]))
    zs = [p["z"] for p in path]
    print("轨迹 %d 点 · 路径 %.0fmm · z %.4f～%.4f" % (len(path), L, min(zs), max(zs)))
    print("起点 (%.4f,%.4f,%.4f) · 终点 (%.4f,%.4f,%.4f)"
          % (path[0]["x"], path[0]["y"], path[0]["z"], path[-1]["x"], path[-1]["y"], path[-1]["z"]))
    if a.reverse:
        path = list(reversed(path))
    wp = [path[0]]
    acc = 0.0
    for p, q in zip(path, path[1:]):
        acc += math.dist((p["x"], p["y"], p["z"]), (q["x"], q["y"], q["z"])) * 1000
        if acc >= a.spacing:
            wp.append(q); acc = 0.0
    if wp[-1] is not path[-1]:
        wp.append(path[-1])
    steps = [{"stage": i + 1, "to_pos": [round(w["x"], 6), round(w["y"], 6), round(w["z"], 6)],
              "to_label": "traj_%03d" % (i + 1),
              "note": "轨迹复现 %d/%d 点" % (i + 1, len(wp)),
              "guard": {"dz_down_limit_mm": 100}, "tol_mm": 2.0, "timeout_s": 40, "dwell_s": 0.3}
             for i, w in enumerate(wp)]
    print("航点 %d 个(每 %.0fmm) · 单段最大 %.1fmm · 单步最大Δz %.1fmm"
          % (len(wp), a.spacing,
             max(math.dist((p["x"],p["y"],p["z"]),(q["x"],q["y"],q["z"]))*1000 for p,q in zip(wp,wp[1:])),
             max(abs(q["z"]-p["z"])*1000 for p,q in zip(wp,wp[1:]))))
    if a.out:
        json.dump(steps, open(a.out, "w"), indent=1)
        print("→", a.out)
    if a.register:
        shutil.copy(REG, "/tmp/registry.json.bak_traj")
        reg = json.load(open(REG, encoding="utf-8"))
        reg["skills"] = [s for s in reg["skills"] if s.get("id") != a.skill_id]
        reg["skills"].append({"id": a.skill_id, "name": "🧭 按拖动轨迹走", "icon": "🧭", "ros": "line_abs",
                              "speed_max": 150, "param": {}, "point_locked": False,
                              "guard": {"max_lin_mm": 120.0},
                              "steps": steps,
                              "note": "沿人手动拖动的轨迹逐点复现; 只走位置, 姿态保持当前; 点位内联(to_pos)",
                              "group": "建图轨迹"})
        json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("已注册技能 %s(备份 /tmp/registry.json.bak_traj)" % a.skill_id)


if __name__ == "__main__":
    main()
