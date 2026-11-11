#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把录下来的位姿同步进 AR 场景 (8797 三维), 走 fences 的 type=points, 可显示/可回退。

    ./.venv-aoi310/bin/python tools/pose_to_ar.py --rec latest            # 整条路径一条轨迹点
    ./.venv-aoi310/bin/python tools/pose_to_ar.py --rec latest --per-seg  # 每段一条(不同颜色)
    ./.venv-aoi310/bin/python tools/pose_to_ar.py --rec rec_2026... --tol 1.0 --dry

口径:
- 点来自 `zmax_data/pose_records/<rec>/poses.jsonl` 的**真值**(米), 不重采样不带插值;
  RDP 抽稀只为画得动(默认 1.5mm 容差), 抽稀后的点仍逐点落在原路径上。
- 写的是 `type=points` ⇒ 只显示/留档, **不进碰撞判定**(不会把自己要走的路堵死)。
- 写完回读 `/api/fence` 对账: 条目在 + 点数一致 + 名字对得上, 才算同步成功。
- 要撤销: 页面左栏「↩ 回退」或 POST /api/fence/delete {id}。
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "zmax_data/pose_records")
AR = "http://127.0.0.1:8797"
RDP_TOL_MM = 1.5


def _post(path, obj, timeout=20):
    req = urllib.request.Request(AR + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def _get(path, timeout=20):
    with urllib.request.urlopen(AR + path, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def load_rec(name):
    if name in ("latest", "", None):
        ds = sorted([d for d in os.listdir(BASE) if d.startswith("rec_")]) if os.path.isdir(BASE) else []
        if not ds:
            raise SystemExit("没有录制目录")
        name = ds[-1]
    d = os.path.join(BASE, name)
    rows = []
    with open(os.path.join(d, "poses.jsonl")) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if "x" in o:
                rows.append(o)
    if len(rows) < 2:
        raise SystemExit("样本太少: %d" % len(rows))
    return name, rows


def rdp(pts, eps):
    if len(pts) < 3:
        return list(range(len(pts)))

    def dist(p, a, b):
        vx, vy, vz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        L2 = vx * vx + vy * vy + vz * vz
        if L2 == 0:
            return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2 + (p[2] - a[2]) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy + (p[2] - a[2]) * vz) / L2))
        c = (a[0] + t * vx, a[1] + t * vy, a[2] + t * vz)
        return ((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2) ** 0.5

    keep = [0, len(pts) - 1]
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            dd = dist(pts[k], pts[i], pts[j])
            if dd > best:
                best, bi = dd, k
        if best > eps:
            keep.append(bi)
            stack.append((i, bi))
            stack.append((bi, j))
    return sorted(set(keep))


def segments(rows):
    out, cur = [], None
    for i, r in enumerate(rows):
        if r.get("moving"):
            cur = {"i0": i, "i1": i} if cur is None else {"i0": cur["i0"], "i1": i}
        elif cur is not None:
            if cur["i1"] > cur["i0"]:
                out.append(cur)
            cur = None
    if cur is not None and cur["i1"] > cur["i0"]:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rec", default="latest")
    ap.add_argument("--tol", type=float, default=RDP_TOL_MM, help="抽稀容差 mm")
    ap.add_argument("--per-seg", action="store_true", help="每段单独一条(颜色循环)")
    ap.add_argument("--per-run", action="store_true", help="按空闲>4s 分轮, 每轮一条(跳过<50mm 的抖动轮)")
    ap.add_argument("--color", default="#22d3ee")
    ap.add_argument("--name", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    rec, rows = load_rec(a.rec)
    mm = [[r["x"] * 1000, r["y"] * 1000, r["z"] * 1000] for r in rows]
    keep = rdp(mm, a.tol)
    pts = [[round(v / 1000.0, 5) for v in mm[k]] for k in keep]
    span = 0.0
    for k in range(len(mm) - 1):
        span += ((mm[k + 1][0] - mm[k][0]) ** 2 + (mm[k + 1][1] - mm[k][1]) ** 2 +
                 (mm[k + 1][2] - mm[k][2]) ** 2) ** 0.5
    segs = segments(rows)

    base_name = a.name or ("流程录制 %s" % rec.replace("rec_", ""))
    note = ("位姿真值全程录制: %s → %s · 样本 %d · 时长 %.1fs · 路程 %.0fmm · 抽稀 %.1fmm→%d点 · 段 %d"
            % (rows[0].get("t"), rows[-1].get("t"), len(rows),
               rows[-1]["ts"] - rows[0]["ts"], span, a.tol, len(pts), len(segs)))

    payloads = []
    if a.per_run:
        runs, cur = [], None
        for s in segs:
            if cur and rows[s["i0"]]["ts"] - rows[cur[-1]["i1"]]["ts"] > 4.0:
                runs.append(cur)
                cur = [s]
            else:
                cur = (cur or []) + [s]
        if cur:
            runs.append(cur)
        pal = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#facc15"]
        k = 0
        for r in runs:
            i0, i1 = r[0]["i0"], r[-1]["i1"]
            sub = mm[i0:i1 + 1]
            kk = rdp(sub, a.tol)
            pp = [[round(v / 1000.0, 5) for v in sub[j]] for j in kk]
            if len(pp) < 2:
                continue
            Lr = sum(((sub[j + 1][0] - sub[j][0]) ** 2 + (sub[j + 1][1] - sub[j][1]) ** 2 +
                      (sub[j + 1][2] - sub[j][2]) ** 2) ** 0.5 for j in range(len(sub) - 1))
            if Lr < 50.0:
                continue
            k += 1
            payloads.append({"type": "points", "pts": pp,
                             "name": "%s · 轮%d" % (base_name, k),
                             "color": pal[(k - 1) % len(pal)],
                             "note": "%s · 轮%d %s→%s · %d段 · %.0fmm"
                                     % (note, k, rows[i0].get("t"), rows[i1].get("t"),
                                        len(r), Lr)})
    elif a.per_seg and segs:
        pal = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#facc15"]
        for n, s in enumerate(segs):
            sub = mm[s["i0"]:s["i1"] + 1]
            kk = rdp(sub, a.tol)
            pp = [[round(v / 1000.0, 5) for v in sub[k]] for k in kk]
            if len(pp) < 2:
                continue
            payloads.append({"type": "points", "pts": pp,
                             "name": "%s · 段%d" % (base_name, n + 1),
                             "color": pal[n % len(pal)],
                             "note": "%s · 段%d %s→%s" % (note, n + 1,
                                                          rows[s["i0"]].get("t"), rows[s["i1"]].get("t"))})
    else:
        payloads.append({"type": "points", "pts": pts, "name": base_name,
                         "color": a.color, "note": note})

    out = {"rec": rec, "n_samples": len(rows), "n_pts": len(pts), "span_mm": round(span, 1),
           "segments": len(segs), "payloads": payloads, "dry": a.dry}
    if a.dry:
        print(json.dumps({k: v for k, v in out.items() if k != "payloads"}, ensure_ascii=False))
        print(json.dumps({"first_pts": pts[:3], "last_pts": pts[-2:]}, ensure_ascii=False))
        return 0

    added = []
    for p in payloads:
        r = _post("/api/fence/add", p)
        added.append({"ok": r.get("ok"), "id": (r.get("item") or {}).get("id"),
                      "name": (r.get("item") or {}).get("name"),
                      "n": (r.get("item") or {}).get("n"), "err": r.get("err")})
    # 回读对账
    got = _get("/api/fence")
    items = got.get("items") or []
    check = []
    for a1 in added:
        if not a1.get("id"):
            check.append({"id": None, "found": False})
            continue
        it = next((x for x in items if x.get("id") == a1["id"]), None)
        check.append({"id": a1["id"], "found": bool(it),
                      "n_server": (it or {}).get("n"), "n_sent": a1.get("n"),
                      "same": bool(it) and (it or {}).get("n") == a1.get("n")})
    # 落一份给审计
    d = os.path.join(BASE, rec)
    with open(os.path.join(d, "ar_sync.json"), "w") as f:
        json.dump({"at_ar": AR, "added": added, "check": check, "n_items": len(items)}, f,
                  ensure_ascii=False, indent=1)
    out.update({"added": added, "check": check, "n_items_server": len(items)})
    print(json.dumps(out, ensure_ascii=False))
    return 0 if all(c.get("same") for c in check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
