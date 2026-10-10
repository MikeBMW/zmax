#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景数据快照 —— 把 data/scene (场景树 + 仿真真源) 存成带清单的归档, 落到数据盘。

老倪 2026-10-10: 「小版本迭代，保存数据，推代码」。
  - data/ 不入代码库 (设计如此: 真源可再由 tools/sim_scene_def.py 重建), 但现场编辑过的场景
    必须落一份可校验的存档, 否则丢了没处找。
  - 归档落 zmax_data/snapshots/scene_<时间戳>.tar.gz, 同目录写 MANIFEST.json (逐文件 sha256 前 16 位)。

用法:
  ./gui-venv311/bin/python tools/scene_data_snapshot.py            # 快照 + 打印归档路径
  ./gui-venv311/bin/python tools/scene_data_snapshot.py --verify   # 只校验最近一份归档
"""
import hashlib
import json
import os
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "scene")
OUT = os.path.join(ROOT, "zmax_data", "snapshots")
TAG = time.strftime("%Y%m%d_%H%M%S")


def _sha16(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def _files():
    out = []
    for dp, _dn, fn in os.walk(SRC):
        for f in sorted(fn):
            if f.endswith((".bak", ".pyc")) or ".bak_" in f:
                continue
            p = os.path.join(dp, f)
            out.append(p)
    return sorted(out)


def snapshot() -> dict:
    os.makedirs(OUT, exist_ok=True)
    files = _files()
    arc = os.path.join(OUT, "scene_%s.tar.gz" % TAG)
    man = {"format": "zmax-scene-snapshot", "version": "1.0", "created": TAG,
           "root": os.path.relpath(SRC, ROOT), "files": {}, "why": "现场场景编辑存档 (可校验)"}
    with tarfile.open(arc, "w:gz") as tf:
        for p in files:
            rel = os.path.relpath(p, ROOT)
            tf.add(p, arcname=rel)
            man["files"][rel] = {"sha256_16": _sha16(p), "bytes": os.path.getsize(p)}
    man["count"] = len(files)
    man["archive"] = os.path.relpath(arc, ROOT)
    man["archive_sha256_16"] = _sha16(arc)
    with open(os.path.join(OUT, "MANIFEST_%s.json" % TAG), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"archive": man["archive"], "archive_sha256_16": man["archive_sha256_16"],
                   "count": man["count"], "created": TAG}, f, ensure_ascii=False, indent=1)
    return man


def verify() -> dict:
    lp = os.path.join(OUT, "latest.json")
    if not os.path.isfile(lp):
        return {"ok": False, "msg": "没有 latest.json — 先跑一次快照"}
    d = json.load(open(lp, encoding="utf-8"))
    arc = os.path.join(ROOT, d["archive"])
    if not os.path.isfile(arc):
        return {"ok": False, "msg": "归档不在: %s" % arc}
    got = _sha16(arc)
    man_p = os.path.join(OUT, "MANIFEST_%s.json" % d["created"])
    miss = []
    if os.path.isfile(man_p):
        man = json.load(open(man_p, encoding="utf-8"))
        with tarfile.open(arc) as tf:
            names = set(tf.getnames())
        for rel, meta in (man.get("files") or {}).items():
            if rel not in names:
                miss.append(rel)
    return {"ok": got == d["archive_sha256_16"] and not miss,
            "archive": d["archive"], "sha_expected": d["archive_sha256_16"], "sha_got": got,
            "files": d["count"], "missing_in_archive": miss[:5], "created": d["created"]}


def main(argv):
    if "--verify" in argv:
        r = verify()
        print(("✅ 归档可校验: %s (%d 文件, sha %s)" % (r.get("archive"), r.get("files"), r.get("sha_got")))
              if r.get("ok") else ("⛔ 校验不过: %s" % r))
        return 0 if r.get("ok") else 1
    m = snapshot()
    print("📦 场景快照: %s" % m["archive"])
    print("   文件 %d 个 · 归档 sha256[:16] %s · 清单 %s"
          % (m["count"], m["archive_sha256_16"], os.path.relpath(
              os.path.join(OUT, "MANIFEST_%s.json" % TAG), ROOT)))
    v = verify()
    print("   自校验: %s" % ("✅ 过" if v.get("ok") else "⛔ 不过 %s" % v))
    return 0 if v.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
