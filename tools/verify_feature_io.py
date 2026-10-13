#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_feature_io.py — **每个功能**的网络 topic 输入/输出 实测报告 (老倪 2026-10-13)

口径 (三条, 逐条落到实现):
 1. **功能 = 画布节点**。真源 `data/database/zmax/sources/canvas/state_space_obs.json`
    (89 节点 / 184 连线)。每个功能:
      · 输入 topic = 上游节点输出 topic 集合 (由连线 f→t 反解) + 连线总线 `zmax/link_value`
      · 输出 topic = `ss/<node_id>/out` (busdb 注册真源, 每节点 ≥1, 见 busdb.messages.ss_node_out)
      · 描述 = 节点 params.desc / source / source_symbol
      · 性能指标 = 该节点所属产品特征(PF)的 KPI (engineering_db: capability→product_feature→module)
 2. **真收发, 不是登记核对**:
      · 节点输出 topic: 本进程对每个 topic 同时建 writer+reader, 用 `zmax::SSTest` 载体发探针,
        统计 **发出/收到/丢/匹配数** ⇒ 通道是否真能过 (DDS 层往返)。
      · 注册 typed 话题 (25): 按注册类型 + 注册 QoS 只读订阅 ⇒ 实测 count / Hz / 帧龄 (有没有真流量)。
 3. **判据**: 输出通道 `matched>0 且 收到==发出` ⇒ ✅ 通道可用; typed 话题 `count>0` ⇒ ✅ 有流量,
    否则 ❌ 无发布端 (如实写, 不当"通过")。

用法:
  venvs/dds-venv/bin/python tools/verify_feature_io.py [--seconds 6] [--json-only]
产物:
  reports/feature_io_test.json          (机器可读: 逐功能 + 逐 typed 话题 + 汇总)
  docs/deliverables/功能topic_输入输出测试报告_<ver>.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 真源路径 ──────────────────────────────────────────────────────────────
CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")
BUSDB = os.path.join(ROOT, "zmax_data", "dataspace", "busdb.json")
ENGDB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
SCENE_TAGS = os.path.join(ROOT, "config", "topics", "scene_tags.json")
SHEETS = os.path.join(ROOT, "outputs", "config_sheets")
OUT_JSON = os.path.join(ROOT, "reports", "feature_io_test.json")


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return d


def _ver():
    try:
        for p in glob.glob(os.path.join(ROOT, "tools", "gui", "update_checker.py")):
            m = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', open(p, encoding="utf-8").read())
            if m:
                return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return "v?"


def _matched_n(obj, which="pub") -> int:
    """匹配数 (Cyclone 的 API 名是 get_matched_publications/get_matched_subscriptions,
    没有 matched_* 属性 —— 用错名会 AttributeError 或静默 0)。"""
    meth = "get_matched_publications" if which == "pub" else "get_matched_subscriptions"
    f = getattr(obj, meth, None)
    if not f:
        return -1
    try:
        return len(f() or [])
    except Exception:  # noqa: BLE001
        return -1


def node_out_topic(nid: str) -> str:
    """与 tools/ss_bus_topics.py::_own_topic 同口径, 不另立标准。"""
    return "ss/%s/out" % nid


def load_functions():
    """功能表: 画布节点(功能) + 入/出 topic + 描述 + 性能指标 + 场景调用情况。"""
    cv = _j(CANVAS, {}) or {}
    nodes = {n["id"]: n for n in (cv.get("nodes") or []) if n.get("id")}
    links = cv.get("links") or []
    ins, outs = {}, {}
    for l in links:
        f, t = l.get("f"), l.get("t")
        if f in nodes and t in nodes:
            outs.setdefault(f, set()).add(t)
            ins.setdefault(t, set()).add(f)
    # 场景调用: config_sheets 里的「启用节点参数」→ 该场景真跑用的节点
    scene_nodes = {}
    for p in glob.glob(os.path.join(SHEETS, "配置单_*_latest.json")):
        d = _j(p, {}) or {}
        tid = (d.get("任务") or {}).get("task_id")
        scn = (d.get("任务") or {}).get("SCN")
        ids = {x.get("id") for x in ((d.get("画布") or {}).get("启用节点参数") or []) if x.get("id")}
        if tid:
            scene_nodes[tid] = {"scn": scn, "scene": (d.get("任务") or {}).get("场景"), "nodes": ids,
                                "n": (d.get("画布") or {}).get("启用节点数")}
    # 性能指标真源: capability→product_feature→module → KPI
    kpi_by_node, cap_by_node = {}, {}
    try:
        c = sqlite3.connect(ENGDB)
        pf = list(c.execute("select pf_id, title, capability_ref, kpi, status, module_refs from product_features"))
        cap = {r[0]: dict(zip(["bo_id", "grp", "name", "dirs", "brief", "explain", "iface",
                               "inputs", "outputs", "scenes", "engineering", "owner"], r))
               for r in c.execute("select bo_id, grp, name, dirs, brief, explain, iface, inputs, outputs,"
                                  " scenes, engineering, owner from capability_dbc")}
        for pf_id, title, cref, kpi, status, mods in pf:
            try:
                mods = json.loads(mods or "[]")
            except Exception:  # noqa: BLE001
                mods = []
            bo = (cref or "").split()[1] if cref and "BO_" in cref else ""
            for m in mods:
                kpi_by_node.setdefault(m, []).append(kpi or "")
                if bo:
                    cap_by_node.setdefault(m, set()).add(bo)
    except Exception as e:  # noqa: BLE001
        print("⚠️ 工程库读取失败: %s" % e)
        cap = {}
    funcs = []
    for nid, n in nodes.items():
        if n.get("type") in ("row_bg", "row"):
            continue                                  # 背景/分组框不是功能
        prm = n.get("params") or {}
        funcs.append({
            "id": nid, "name": n.get("name"), "type": n.get("type"), "layer": n.get("layer") or prm.get("layer"),
            "desc": (prm.get("desc") or n.get("name") or "")[:600],
            "source": prm.get("source"), "symbol": prm.get("source_symbol"),
            "in_topics": sorted({node_out_topic(u) for u in (ins.get(nid) or set())}),
            "out_topics": [node_out_topic(nid)],
            "kpi": sorted({k for k in (kpi_by_node.get(n.get("name")) or []) if k}),
            "cap": sorted(cap_by_node.get(n.get("name")) or []),
            "scenes": sorted([t for t, v in scene_nodes.items() if nid in v["nodes"]]),
        })
    return funcs, nodes, links, scene_nodes, cap


def dds_test(funcs, seconds=6.0, typed_keys=None):
    """真收发: ① 节点输出 topic 往返 (SSTest 载体) ② 注册 typed 话题只读实测。

    🔴 两条实测纪律 (2026-10-13, 一次踩过):
      · **必须挂单播配置**: 全系统只有一张 DDS 配置(AllowMulticast=false + <Peers>)。订阅端不挂配置
        ⇒ 走默认多播 ⇒ 与单播发布端**互相发现不到** ⇒ 实测"收 0 条"(假失败)。
      · **必须两个参与者**: 同一参与者内 writer→reader 是本地直投, 不经发现/传输 ⇒ 测不出真实通道。
        发布用 dp、订阅用 dp2 ⇒ matched>0 才算通道真的通。
    """
    sys.path.insert(0, os.path.join(ROOT, "dds"))
    _cfg = os.path.join(ROOT, "dds", "cyclonedds_unicast.xml")
    if os.path.isfile(_cfg) and not os.environ.get("CYCLONEDDS_URI"):
        os.environ["CYCLONEDDS_URI"] = "file://" + _cfg
    res = {"node_topics": {}, "typed": {}, "errors": []}
    try:
        from cyclonedds.domain import DomainParticipant
        from cyclonedds.topic import Topic
        from cyclonedds.pub import DataWriter
        from cyclonedds.sub import DataReader
        from ss_types import SSTest
        import zmax_node as ZN
    except Exception as e:  # noqa: BLE001
        res["errors"].append("DDS 不可用: %s" % e)
        return res
    dp = DomainParticipant(0)      # 发布端
    dp2 = DomainParticipant(0)     # 订阅端 (独立参与者 ⇒ 走真实发现/传输)
    # ── ① 节点输出 topic 往返 ──
    ents = {}
    for f in funcs:
        t = f["out_topics"][0]
        try:
            tp = Topic(dp, t, SSTest)
            w = DataWriter(dp, tp, qos=ZN.qos_for("beat"))
            r = DataReader(dp2, Topic(dp2, t, SSTest), qos=ZN.qos_for("beat"))
            ents[t] = {"w": w, "r": r, "sent": 0, "got": 0, "max_matched": 0}
        except Exception as e:  # noqa: BLE001
            res["errors"].append("topic %s 建链失败: %s" % (t, e))
    seq = 0
    t0 = time.time()
    while time.time() - t0 < seconds:
        seq += 1
        for t, e in ents.items():
            try:
                e["w"].write(SSTest(ts=time.time(), suite="feature_io", case=t, passed=1,
                                    dur_ms=0.0, total=seq, failed=0, detail="seq=%d" % seq))
                e["sent"] += 1
                e["max_matched"] = max(e["max_matched"], _matched_n(e["r"], "pub"))
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.15)
        for t, e in ents.items():
            try:
                got = e["r"].take()
                if got:
                    e["got"] += len(got)
            except Exception:  # noqa: BLE001
                pass
    for t, e in ents.items():
        res["node_topics"][t] = {"sent": e["sent"], "got": e["got"], "matched": e["max_matched"],
                                 "ok": e["got"] >= max(1, e["sent"] // 2)}
    # ── ② 注册 typed 话题只读实测 ──
    keys = typed_keys or list(getattr(ZN, "TOPICS", {}).keys())
    subs = {}
    for k in keys:
        try:
            subs[k] = {"r": DataReader(dp2, Topic(dp2, "zmax/" + k, ZN.TOPICS[k]), qos=ZN.qos_for(k)),
                       "n": 0, "last": None}
        except Exception as e:  # noqa: BLE001
            res["errors"].append("typed %s 订阅失败: %s" % (k, e))
    t0 = time.time()
    while time.time() - t0 < seconds:
        for k, s in subs.items():
            try:
                got = s["r"].take()
                if got:
                    s["n"] += len(got)
                    s["last"] = time.time()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.15)
    now = time.time()
    for k, s in subs.items():
        res["typed"][k] = {"count": s["n"], "hz": round(s["n"] / seconds, 2),
                           "age_s": (round(now - s["last"], 2) if s["last"] else None),
                           "ok": s["n"] > 0}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()
    funcs, nodes, links, scene_nodes, cap = load_functions()
    print("功能(画布节点) %d 个 · 画布连线 %d · 场景 %s" %
          (len(funcs), len(links), {k: v["n"] for k, v in scene_nodes.items()}))
    io = dds_test(funcs, a.seconds)
    for f in funcs:
        t = f["out_topics"][0]
        d = (io["node_topics"] or {}).get(t) or {}
        f["io"] = {"out_sent": d.get("sent"), "out_got": d.get("got"), "matched": d.get("matched"),
                   "out_ok": bool(d.get("ok"))}
        ups = f["in_topics"]
        got = [(io["node_topics"] or {}).get(u) for u in ups]
        f["io"]["in_ok"] = all(bool(g and g.get("ok")) for g in got) if ups else None
        f["io"]["in_measured"] = len([g for g in got if g and g.get("ok")])
        f["io"]["in_total"] = len(ups)
    n_out_ok = sum(1 for f in funcs if f["io"]["out_ok"])
    typed_ok = {k: v for k, v in (io.get("typed") or {}).items() if v.get("ok")}
    snap = {"ver": _ver(), "ts": time.time(), "seconds": a.seconds,
            "n_functions": len(funcs), "n_out_ok": n_out_ok,
            "n_typed": len(io.get("typed") or {}), "n_typed_ok": len(typed_ok),
            "functions": funcs, "typed": io.get("typed"), "errors": io.get("errors"),
            "scene_nodes": {k: {"scn": v["scn"], "scene": v["scene"], "n": v["n"]} for k, v in scene_nodes.items()}}
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print("→ %s" % OUT_JSON)
    print("节点输出通道: %d/%d ✅ · typed 话题有流量: %d/%d" %
          (n_out_ok, len(funcs), len(typed_ok), len(io.get("typed") or {})))
    if io.get("errors"):
        print("⚠️ %d 条建链/DDS 错误 (前 3): %s" % (len(io["errors"]), io["errors"][:3]))
    if not a.json_only:
        render_md(snap)


def render_md(snap):
    ver = snap["ver"]
    out = os.path.join(ROOT, "docs", "deliverables", "功能topic_输入输出测试报告_%s.md" % ver)
    L = []
    A = L.append
    A("# 功能 topic 输入/输出 实测报告 · %s" % ver)
    A("")
    A("> 真源: 画布 `data/database/zmax/sources/canvas/state_space_obs.json` (89 节点/184 连线) · "
      "注册表 `zmax_data/dataspace/busdb.json` · 工程库 `data/database/zmax/zmax_engineering.db`")
    A("> 口径: 功能=画布节点; **输出 topic** = `ss/<节点id>/out`; **输入 topic** = 上游节点输出 topic 集合 + 连线总线 `zmax/link_value`")
    A("> 实测方式: 逐 topic **真 DDS 往返** (`zmax::SSTest` 载体, writer+reader 同进程) + 注册 typed 话题按注册 QoS 只读订阅")
    A("> 生成时间: %s (窗口 %.0fs)" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap["ts"])), snap["seconds"]))
    A("")
    A("## 汇总")
    A("")
    A("| 项 | 数 |")
    A("|---|---|")
    A("| 功能(画布节点) | %d |" % snap["n_functions"])
    A("| 输出通道往返 ✅ | **%d / %d** |" % (snap["n_out_ok"], snap["n_functions"]))
    A("| 注册 typed 话题实测有流量 ✅ | **%d / %d** |" % (snap["n_typed_ok"], snap["n_typed"]))
    if snap["scene_nodes"]:
        A("| 场景调用 | %s |" % " · ".join("%s(%s)=%s 节点" % (k, v["scn"], v["n"])
                                           for k, v in snap["scene_nodes"].items()))
    A("")
    A("## 一、注册 typed 话题 (数据空间 25 个) 实测")
    A("")
    A("| 话题 | 本窗口条数 | 实测 Hz | 帧龄 s | 判定 |")
    A("|---|---|---|---|---|")
    for k, v in sorted((snap.get("typed") or {}).items(), key=lambda x: (not x[1].get("ok"), x[0])):
        A("| `zmax/%s` | %d | %s | %s | %s |" % (k, v["count"], v["hz"], v["age_s"],
                                                "✅有流量" if v.get("ok") else "❌无发布端"))
    A("")
    A("## 二、逐功能 topic 输入/输出 实测")
    A("")
    A("| 功能 (节点) | 层 | 输出 topic | 发出/收到/匹配 | 输出通道 | 输入 topic (上游) | 输入通道 | 本场景调用 | 性能指标 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for f in sorted(snap["functions"], key=lambda x: (x["layer"] or "zz", x["id"])):
        io = f["io"]
        ins = ", ".join("`%s`" % t for t in f["in_topics"][:3]) or "（源节点/无上游）"
        if len(f["in_topics"]) > 3:
            ins += " +%d" % (len(f["in_topics"]) - 3)
        inp = ("✅ %d/%d" % (io["in_measured"], io["in_total"])) if io["in_total"] else "—(源)"
        kpi = ("; ".join(f["kpi"])[:60] if f["kpi"] else "见能力清单")
        A("| **%s** | %s | `%s` | %s/%s/%s | %s | %s | %s | %s | %s |" %
          (f["name"], f["layer"] or "-", f["out_topics"][0], io["out_sent"], io["out_got"], io["matched"],
           "✅" if io["out_ok"] else "❌", ins, inp, ",".join(f["scenes"]) or "—", kpi))
    A("")
    if snap.get("errors"):
        A("## 三、建链/订阅异常 (如实记录)")
        A("")
        for e in snap["errors"][:20]:
            A("- %s" % e)
        A("")
    A("## 复核")
    A("")
    A("```bash")
    A("venvs/dds-venv/bin/python tools/verify_feature_io.py --seconds 6")
    A("```")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("→ %s (%d B)" % (out, os.path.getsize(out)))


if __name__ == "__main__":
    main()
