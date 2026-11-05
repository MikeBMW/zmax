#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗺 从位姿日志离线建工作空间覆盖图 (影子模式/历史会话通用)。

输入: poses.jsonl (影子模式) 或 frames.jsonl (历史建图会话, 取 pose_before)
输出: <out>/map.json + <out>/summary.json + <out>/shadow_3d.html
"""
import argparse, json, math, os, subprocess, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Coverage:
    def __init__(self, cell=0.02):
        self.cell = cell
        self.cells = {}
        self.bbox = [9e9, 9e9, 9e9, -9e9, -9e9, -9e9]
        self.zmin, self.zmax, self.n = 9e9, -9e9, 0
        self.path = 0.0
        self.prev = None

    def add(self, x, y, z):
        if not (-3 < x < 3 and -3 < y < 3 and -1 < z < 2):
            return
        k = (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))
        self.cells[k] = self.cells.get(k, 0) + 1
        b = self.bbox
        b[0], b[1], b[2] = min(b[0], x), min(b[1], y), min(b[2], z)
        b[3], b[4], b[5] = max(b[3], x), max(b[4], y), max(b[5], z)
        self.zmin, self.zmax, self.n = min(self.zmin, z), max(self.zmax, z), self.n + 1
        if self.prev:
            self.path += math.dist(self.prev, (x, y, z))
        self.prev = (x, y, z)

    def summary(self):
        return {"samples": self.n, "cells": len(self.cells), "cell_m": self.cell,
                "area_m2": round(len(self.cells) * self.cell ** 2, 4),
                "bbox_m": [round(v, 3) for v in self.bbox],
                "z_range_m": [round(self.zmin, 3), round(self.zmax, 3)],
                "tcp_path_m": round(self.path, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poses", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cell", type=float, default=0.02)
    ap.add_argument("--dedup-time", type=float, default=0.0, help=">0 则按该秒数抽稀")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cov = Coverage(a.cell)
    sess_out = os.path.join(a.out, "poses.jsonl")
    last = -1e9
    n_in = 0
    with open(a.poses, encoding="utf-8") as f, open(sess_out, "w", encoding="utf-8") as w:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            p = d.get("tcp") or d.get("pose_before")
            if not p:
                continue
            try:
                xyz = [float(p["x"]), float(p["y"]), float(p["z"])] if isinstance(p, dict) else [float(v) for v in p[:3]]
                t = float(d.get("t") or (p.get("ts") if isinstance(p, dict) else 0) or 0)
            except Exception:
                continue
            if a.dedup_time > 0 and t - last < a.dedup_time:
                continue
            last = t
            cov.add(*xyz)
            n_in += 1
            w.write(json.dumps({"t": t, "p": xyz}, ensure_ascii=False) + "\n")
    summ = cov.summary()
    json.dump({"samples": n_in, "elapsed_s": None, "frames": n_in, "keyframes": None,
               "ended": "offline:" + os.path.basename(a.poses)}, open(os.path.join(a.out, "summary.json"), "w"), ensure_ascii=False)
    json.dump({"frame": "base_link", "cell_m": cov.cell,
               "cells": [{"i": i, "j": j, "n": n} for (i, j), n in cov.cells.items()],
               "coverage": summ, "note": "TCP 轨迹占据栅格 (离线重算, 非点云)"},
              open(os.path.join(a.out, "map.json"), "w"), ensure_ascii=False)
    print(json.dumps({"ok": True, "poses": n_in, "coverage": summ}, ensure_ascii=False))
    subprocess.run([os.path.join(ROOT, "gui-venv311/bin/python"),
                    os.path.join(ROOT, "tools/shadow_map_html.py"), a.out], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
