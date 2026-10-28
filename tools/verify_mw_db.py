#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中间件工程库判据 (话题名/端口/连线的落库唯一依据)。

    ① 表就位且行数对 (节点/端口/连线/话题)
    ② 库里读回的 specs == 画布 JSON 解析的 specs (逐节点 id/名字/端口)
    ③ mw_topic 每一条 == bus.topic() 派生值 (话题名一字不差)
    ④ load_project(source="db") 能跑一拍 (75 节点)
    ⑤ 临时画布改过 → 自动判定库过期并回写 (stale 检测真的有效)
    ⑥ source="json" 强制走 JSON 也一致 (两条路同源)
    ⑦ 改库里的一个话题名 → 重新加载后 Node.topic() 立刻用库里的名字 (证明话题名真从库来)

用法: PYTHONPATH=src python tools/verify_mw_db.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.middleware import db, spec                        # noqa: E402
from lerobot.middleware import load_project                     # noqa: E402
from lerobot.middleware.bus import topic as bus_topic           # noqa: E402

ok_all = True


def judge(name, cond, detail=""):
    global ok_all
    ok_all = ok_all and bool(cond)
    print("%s %s%s" % ("✅" if cond else "❌", name, (" — " + detail) if detail else ""))


canvas = spec.find_canvas()
project = db.project_of(canvas)
specs_json, links_json, _ = spec.parse_canvas(canvas)
db.sync(specs_json, links_json, canvas_path=canvas)

# ① 表行数
conn = db.connect()
try:
    cnt = {t: conn.execute("SELECT count(*) FROM %s WHERE project=?" % t, (project,)).fetchone()[0]
           for t in ("mw_node", "mw_port", "mw_link", "mw_topic")}
finally:
    conn.close()
ports = sum(len(s.inputs) + len(s.outputs) for s in specs_json)
judge("① 表就位", cnt["mw_node"] == len(specs_json) and cnt["mw_link"] == len(links_json)
      and cnt["mw_port"] == ports and cnt["mw_topic"] == ports,
      "节点 %d/%d · 端口 %d/%d · 连线 %d/%d · 话题 %d/%d"
      % (cnt["mw_node"], len(specs_json), cnt["mw_port"], ports,
         cnt["mw_link"], len(links_json), cnt["mw_topic"], ports))

# ② 库 specs == JSON specs
specs_db, links_db, meta_db = db.load(project=project)
by_db = {s.id: s for s in specs_db}
by_js = {s.id: s for s in specs_json}
diff = []
for nid, a in by_js.items():
    b = by_db.get(nid)
    if b is None:
        diff.append("%s 缺" % nid)
        continue
    if (a.name != b.name or list(a.inputs) != list(b.inputs)
            or list(a.outputs) != list(b.outputs) or a.module_name != b.module_name):
        diff.append("%s 不一致 (in %s/%s out %s/%s)" % (nid, a.inputs, b.inputs, a.outputs, b.outputs))
judge("② 库读回 == 画布解析", not diff, "%d 个节点逐一对齐" % len(by_js) if not diff else "; ".join(diff[:3]))

# ③ 话题名逐条
tmap = db.topic_map(project=project)
bad = [(k, v, bus_topic(*k)) for k, v in tmap.items() if v != bus_topic(*k)]
judge("③ 话题注册表 == 派生值", not bad and len(tmap) == ports,
      "%d 条话题逐条一致" % len(tmap) if not bad else "不一致 %s" % bad[:3])

# ④ 从库加载跑一拍
prj_db = load_project(source="db", quiet=True)
tr = prj_db.step()
judge("④ source=db 能跑", prj_db.meta.get("source") == "db" and len(prj_db.nodes) == len(specs_json)
      and len(tr) == len(specs_json),
      "source=%s · 节点 %d · 一拍 %d 条轨迹" % (prj_db.meta.get("source"), len(prj_db.nodes), len(tr)))

# ⑤ 过期检测: 复制画布改一个名字 → 新工程应判 stale 并回写
tmpd = tempfile.mkdtemp(prefix="mwdb_")
tmp_canvas = os.path.join(tmpd, "state_space_obs_copy.json")
shutil.copy(canvas, tmp_canvas)
d = json.load(open(tmp_canvas, encoding="utf-8"))
d["nodes"][0]["name"] = (d["nodes"][0].get("name") or "") + " · 判据改名"
json.dump(d, open(tmp_canvas, "w", encoding="utf-8"), ensure_ascii=False)
info = db.ensure_synced(tmp_canvas, quiet=True)
stale_ok = info.get("loaded_from") == "json→db"
# 再 ensure 一次: sha 已一致 → 应直接认库
info2 = db.ensure_synced(tmp_canvas, quiet=True)
judge("⑤ 库过期自动回写", stale_ok and info2.get("loaded_from") == "db",
      "首次=%s · 再次=%s" % (info.get("loaded_from"), info2.get("loaded_from")))

# ⑥ 强制 JSON 路径一致
prj_js = load_project(source="json", quiet=True)
judge("⑥ source=json 同源", len(prj_js.nodes) == len(prj_db.nodes)
      and set(prj_js.nodes) == set(prj_db.nodes),
      "两条路都是 %d 个节点" % len(prj_js.nodes))

# ⑦ 改库里的一个话题名 → 重新加载立刻生效 (证明话题真从库来)
conn = db.connect()
try:
    tgt = ("sssched", "in1")
    old = conn.execute("SELECT topic FROM mw_topic WHERE project=? AND node_id=? AND port=?",
                       (project, tgt[0], tgt[1])).fetchone()[0]
    conn.execute("UPDATE mw_topic SET topic=? WHERE project=? AND node_id=? AND port=?",
                 ("ss.node.sssched.in1.DBCHECK", project, tgt[0], tgt[1]))
    conn.commit()
    prj2 = load_project(source="db", quiet=True)
    got = prj2.nodes["sssched"].topic("in1")
    conn.execute("UPDATE mw_topic SET topic=? WHERE project=? AND node_id=? AND port=?",
                 (old, project, tgt[0], tgt[1]))
    conn.commit()
finally:
    conn.close()
prj3 = load_project(source="db", quiet=True)
judge("⑦ 话题名真从库来", got == "ss.node.sssched.in1.DBCHECK"
      and prj3.nodes["sssched"].topic("in1") == old,
      "改库 → %s · 改回 → %s" % (got, prj3.nodes["sssched"].topic("in1")))

shutil.rmtree(tmpd, ignore_errors=True)
# 清掉判据造出来的副本工程
conn = db.connect()
try:
    conn.execute("DELETE FROM mw_node WHERE project LIKE '%copy%'")
    conn.execute("DELETE FROM mw_port WHERE project LIKE '%copy%'")
    conn.execute("DELETE FROM mw_link WHERE project LIKE '%copy%'")
    conn.execute("DELETE FROM mw_topic WHERE project LIKE '%copy%'")
    conn.execute("DELETE FROM mw_project WHERE project LIKE '%copy%'")
    conn.commit()
finally:
    conn.close()

print("\n===== %s =====" % ("全部通过" if ok_all else "有失败"))
raise SystemExit(0 if ok_all else 1)
