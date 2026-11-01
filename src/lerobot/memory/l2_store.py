#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 L2 记忆库 —— 唯一真源 (技能定义 / 功能接口 / 固定点位 / 工艺卡 / 标杆 / 台账)

老倪 2026-11-02: 「技能点的定义、功能接口 → L2 肌肉记忆技能库; 固定轨迹点、工艺编排好的
工艺卡 → L2 肌肉记忆操作; 需要记忆的工程配置/操作/点位都在 L2 记忆节点保存, 其它节点只是调用查询。」

设计 (两层库, 写只走记忆节点, 读谁都可以):
  技能库 (技能点 = 能不能做 / 怎么做 / 参数是什么)      → skills.json
  操作库 (做到哪 / 按什么顺序 / 实测多快)               → ops_points.json, ops_cards.json, ops_seq.json
  记忆体 (练出来的标杆 + 实测台账)                      → champs.json, ledger.json

只读接口 (其它节点唯一入口, 不直读原始 json):
    from lerobot.memory.l2_store import query, skill, iface, card, point, champ, stats
    query({"skill": "L2.lift"}) / query({"card": "SCN-01-FW"}) / query({"point": "slot_pick_place"})
    query({"champ": [104, "接近"]}) / query({"stats": True})

写接口 (只允许记忆节点调用, writer 必须是 n_l2_muscle / ss_mem_l2):
    put_skill(entry, writer=...)  put_card(...)  put_point(...)  put_champs(...)  put_ledger(...)

真源血统: 每条 entry 带 `src` (原文件) + `sha` (内容指纹) + `at` (入库时间) —— 可回溯, 不手改。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
# src/lerobot/memory/l2_store.py → 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
STORE = os.path.join(ROOT, "data", "memory", "l2_store")
BANKS = {
    "skills": os.path.join(STORE, "skills.json"),
    "points": os.path.join(STORE, "ops_points.json"),
    "cards": os.path.join(STORE, "ops_cards.json"),
    "seq": os.path.join(STORE, "ops_seq.json"),
    "champs": os.path.join(STORE, "champs.json"),
    "ledger": os.path.join(STORE, "ledger.json"),
    "index": os.path.join(STORE, "index.json"),
}
WRITERS = ("n_l2_muscle", "ss_mem_l2")     # 只有这两个记忆节点能落库

_CACHE: dict = {}                          # name -> (mtime_ns, size, data)


# ─────────────────────────────────────────────────────────────── 低层读写
def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def _read(name):
    p = BANKS[name]
    if not os.path.exists(p):
        return {}
    st = os.stat(p)
    key = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(name)
    if hit and hit[0] == key:
        return hit[2]
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    _CACHE[name] = (key[0], key[1], d)
    return d


def _write(name, data, writer):
    if writer not in WRITERS:
        raise PermissionError("L2 记忆库只允许记忆节点写 (%s); 传入 writer=%r" % (WRITERS, writer))
    os.makedirs(STORE, exist_ok=True)
    tmp = BANKS[name] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BANKS[name])
    _CACHE.pop(name, None)
    _reindex(writer)
    return BANKS[name]


def _reindex(writer):
    """index.json = 库的目录 + 指纹 + 计数 (其它节点/大屏只看这一份)。"""
    idx = {"version": 1, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "root": STORE, "banks": {}, "counts": {}, "writer": writer}
    for name in ("skills", "points", "cards", "seq", "champs", "ledger"):
        p = BANKS[name]
        if not os.path.exists(p):
            continue
        st = os.stat(p)
        idx["banks"][name] = {"file": os.path.basename(p), "sha": _sha_file(p),
                              "bytes": st.st_size, "at": time.strftime("%Y-%m-%d %H:%M:%S",
                                                                      time.localtime(st.st_mtime))}
        idx["counts"][name] = _count(name)
    os.makedirs(STORE, exist_ok=True)
    with open(BANKS["index"], "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    _CACHE.pop("index", None)
    return idx


def _count(name):
    d = _read(name)
    if name == "skills":
        return len(d.get("skills") or {})
    if name == "points":
        return len(d.get("points") or {})
    if name == "cards":
        return len(d.get("cards") or {})
    if name == "seq":
        return len(d.get("seqs") or {})
    if name == "champs":
        return len(d.get("buckets") or {})
    if name == "ledger":
        return len((d.get("kinds") or {}))
    return 0


# ─────────────────────────────────────────────────────────────── 读接口
def index():
    return _read("index") or _reindex("read")


def skills(kind=None, tag=None):
    """技能点全表 (可按 kind: atomic|cycle|aoi|demo, 或 tag 过滤)。"""
    d = (_read("skills").get("skills") or {})
    out = {}
    for k, v in d.items():
        if kind and str(v.get("kind")) != str(kind):
            continue
        if tag and tag not in (v.get("tags") or []):
            continue
        out[k] = v
    return out


def skill(sid):
    """技能点定义: 做什么 / 谁执行 / 判据 / 参数; 找不到返回 None (调用方自己兜底)。"""
    return (_read("skills").get("skills") or {}).get(sid)


def iface(sid):
    """技能的功能接口 (其它节点只读这一层: ros 接口 / 参数 schema / 步骤引用)。"""
    s = skill(sid)
    if not s:
        return None
    return {"id": s.get("id"), "name": s.get("name"), "ros": s.get("ros"),
            "params": s.get("params") or [], "returns": s.get("returns") or {},
            "pre": s.get("pre") or [], "verify": s.get("verify") or {},
            "steps": s.get("steps") or [], "src": s.get("src")}


def cards(scene_type=None):
    d = (_read("cards").get("cards") or {})
    if not scene_type:
        return d
    return {k: v for k, v in d.items()
            if scene_type in str(v.get("scene_type", "")) or scene_type in str(v.get("scene_id", ""))}


def card(cid):
    """工艺卡 (工艺编排好的工序): identity / process / recipe / targets / safety / poka_yoke。

    查法: 先按工单号 (BS-SCN-07-AOI-0007) 精确查; 再按场景号 (SCN-07-AOI) 取主工单。
    """
    d = _read("cards").get("cards") or {}
    if cid in d:
        return d[cid]
    for v in d.values():
        if v.get("scene_id") == cid:
            return v
    return None


def seq(scene):
    """该场景的段序列 + 节拍口径 (计划 vs 实测)。"""
    return (_read("seq").get("seqs") or {}).get(scene)


def points():
    return _read("points").get("points") or {}


def point(name):
    """固定轨迹点: {pos:[x,y,z], quat:[x,y,z,w], desc, src, at}"""
    return points().get(name)


def champs():
    return _read("champs").get("buckets") or {}


def champ(seed, stage):
    """固化标杆 (练出来的 u 序列); 无 → (None, None) —— 调用方必须能接受空。"""
    b = champs().get("%s|%s" % (seed, stage)) or {}
    cu, cx = b.get("champ_u"), b.get("champ_x")
    return (cu or None), (cx or None)


def measured(kind):
    """实测台账: {n, mean_t, plan_t, ratio} —— 计划值来自段表, 实测来自真跑。"""
    k = (_read("ledger").get("kinds") or {}).get(str(kind)) or {}
    return k or None


def stats():
    """一句话摘要 (节点输出 / 大屏 / 报告都用这一份, 口径一致)。"""
    idx = index()
    c = idx.get("counts") or {}
    sk = skills()
    kinds = {}
    for v in sk.values():
        kinds[str(v.get("kind"))] = kinds.get(str(v.get("kind")), 0) + 1
    led = (_read("ledger").get("kinds") or {})
    worst = None
    for k, v in led.items():
        r = v.get("ratio")
        if r and (worst is None or r > worst[1]):
            worst = (k, r)
    return {"skills": c.get("skills", 0), "skill_kinds": kinds,
            "cards": c.get("cards", 0), "points": c.get("points", 0),
            "seqs": c.get("seq", 0), "champs": c.get("champs", 0),
            "ledger_kinds": c.get("ledger", 0),
            "worst_ratio": worst, "built_at": idx.get("built_at"),
            "sha": {k: v.get("sha") for k, v in (idx.get("banks") or {}).items()}}


def query(q):
    """统一只读入口 — 其它节点只调这一个函数。

    q 形如 {"skill": "L2.lift"} / {"iface": "L2.lift"} / {"card": "SCN-01-FW"} /
            {"point": "slot_pick_place"} / {"champ": [104, "接近"]} / {"measured": "move"} /
            {"seq": "SCN-01-FW"} / {"stats": True} / {"skills": {"kind": "atomic"}}
    """
    if not isinstance(q, dict):
        return None
    for k, v in q.items():
        if k == "skill":
            return skill(v)
        if k == "iface":
            return iface(v)
        if k == "card":
            return card(v)
        if k == "cards":
            return cards(v if isinstance(v, str) else None)
        if k == "point":
            return point(v)
        if k == "points":
            return points()
        if k == "champ":
            return champ(*v) if isinstance(v, (list, tuple)) and len(v) == 2 else None
        if k == "champs":
            return champs()
        if k == "measured":
            return measured(v)
        if k == "seq":
            return seq(v)
        if k == "skills":
            return skills(**(v or {})) if isinstance(v, dict) else skills()
        if k == "stats":
            return stats()
    return None


# ─────────────────────────────────────────────────────────────── 写接口 (记忆节点专用)
def put_skill(entry, writer):
    d = _read("skills") or {"version": 1, "skills": {}}
    d.setdefault("skills", {})[entry["id"]] = entry
    _write("skills", d, writer)


def put_skills(entries, writer, mode="merge"):
    d = _read("skills") or {"version": 1, "skills": {}}
    sk = {} if mode == "replace" else dict(d.get("skills") or {})
    for e in entries:
        sk[e["id"]] = e
    d["skills"] = sk
    d["version"] = 1
    _write("skills", d, writer)


def put_point(name, entry, writer):
    d = _read("points") or {"version": 1, "points": {}}
    d.setdefault("points", {})[name] = entry
    _write("points", d, writer)


def put_points(entries, writer, mode="merge"):
    d = _read("points") or {"version": 1, "points": {}}
    pts = {} if mode == "replace" else dict(d.get("points") or {})
    pts.update(entries)
    d["points"] = pts
    _write("points", d, writer)


def put_cards(entries, writer, mode="merge"):
    d = _read("cards") or {"version": 1, "cards": {}}
    cs = {} if mode == "replace" else dict(d.get("cards") or {})
    cs.update(entries)
    d["cards"] = cs
    _write("cards", d, writer)


def put_seqs(entries, writer, mode="merge"):
    d = _read("seq") or {"version": 1, "seqs": {}}
    seqs = {} if mode == "replace" else dict(d.get("seqs") or {})
    seqs.update(entries)
    d["seqs"] = seqs
    _write("seq", d, writer)


def put_champs(buckets, writer):
    d = {"version": 1, "buckets": buckets}
    _write("champs", d, writer)


def put_ledger(kinds, writer, src=""):
    d = {"version": 1, "kinds": kinds, "src": src}
    _write("ledger", d, writer)


# ─────────────────────────────────────────────────────────────── 自检
def verify():
    """库自洽: 条目有血统 / 接口字段齐 / 点位有坐标 / 卡有工序 / 标杆有帧。返回 [(项, ok, 说明)]。"""
    out = []
    idx = index()
    out.append(("索引在位", bool(idx.get("counts")), idx.get("built_at", "")))
    sk = skills()
    no_src = [k for k, v in sk.items() if not v.get("src")]
    out.append(("技能条目带血统", not no_src, "%d 条 · 缺 src %d" % (len(sk), len(no_src))))
    bad_iface = [k for k, v in sk.items() if v.get("kind") != "card" and not (v.get("ros") or v.get("steps"))]
    out.append(("技能有接口(ros/步骤)", not bad_iface, "缺 %d %s" % (len(bad_iface), bad_iface[:3])))
    pts = points()
    bad_pt = [k for k, v in pts.items() if not (v.get("pos") and len(v["pos"]) == 3 and v.get("quat"))]
    out.append(("点位坐标完整", not bad_pt, "%d 点 · 缺 %d" % (len(pts), len(bad_pt))))
    cs = cards()
    bad_card = [k for k, v in cs.items() if not (v.get("process") or v.get("identity"))]
    out.append(("工艺卡有工序", not bad_card, "%d 张 · 缺 %d" % (len(cs), len(bad_card))))
    ch = champs()
    empty = [k for k, v in ch.items() if not (v.get("champ_u") or [])]
    out.append(("标杆有帧序列", not empty, "%d 桶 · 空 %d" % (len(ch), len(empty))))
    led = _read("ledger").get("kinds") or {}
    bad_led = [k for k, v in led.items() if not v.get("mean_t")]
    out.append(("台账有实测均值", not bad_led, "%d 类 · 缺 %d" % (len(led), len(bad_led))))
    # 读接口冒烟: 三条最常用的查询必须真返回
    probe = [("iface", iface("L2.lift")), ("card", card(sorted(cs)[0]) if cs else None),
             ("point", point(sorted(pts)[0]) if pts else None)]
    out.append(("查询接口冒烟", all(v for _, v in probe),
                " ".join("%s=%s" % (k, "Y" if v else "N") for k, v in probe)))
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="L2 记忆库 (只读查询 / 自检)")
    ap.add_argument("--skill"); ap.add_argument("--iface"); ap.add_argument("--card")
    ap.add_argument("--point"); ap.add_argument("--champ", nargs=2, metavar=("SEED", "STAGE"))
    ap.add_argument("--measured"); ap.add_argument("--stats", action="store_true")
    ap.add_argument("--list", choices=["skills", "cards", "points", "champs"])
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.verify:
        rows = verify()
        for n, ok, d in rows:
            print("%s %-20s %s" % ("✅" if ok else "❌", n, d))
        return 0 if all(x[1] for x in rows) else 1
    if a.stats:
        print(json.dumps(stats(), ensure_ascii=False, indent=1)); return 0
    if a.list:
        d = {"skills": skills, "cards": cards, "points": points, "champs": champs}[a.list]()
        print("\n".join("%-34s %s" % (k, (v.get("name") if isinstance(v, dict) else "")) for k, v in d.items()))
        return 0
    for key, val in (("skill", a.skill), ("iface", a.iface), ("card", a.card),
                     ("point", a.point), ("measured", a.measured)):
        if val:
            print(json.dumps(query({key: val}), ensure_ascii=False, indent=1)); return 0
    if a.champ:
        cu, cx = champ(a.champ[0], a.champ[1])
        print(json.dumps({"seed": a.champ[0], "stage": a.champ[1],
                          "frames": len(cu or []), "champ_u_head": (cu or [])[:2]}, ensure_ascii=False, indent=1))
        return 0
    print(json.dumps(stats(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
