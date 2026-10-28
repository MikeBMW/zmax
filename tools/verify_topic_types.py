# -*- coding: utf-8 -*-
"""全局检查: 每个 topic 的类型是否有明确数据意义、是否挂在主要发送节点上。

老倪 2026-10-17: 「topic 的 type 太随意…一个 topic 有明确的数据意义, 至少有一个主要的发送 Tx 节点;
   将 topic 的类型重新命名, 要与主要的发送节点关联上; 有的节点只是复用, 你要根据状态空间工程
   全局检查所有 topic, 更新全局数据空间的实用性」

判据 (全绿才算过):
  ① 覆盖: 画布每个端口都有类型, 0 个未登记节点/端口
  ② 出口: 类型名 = 主要 Tx 节点语义 (zmax::<Stem>...), 不允许再出现信封名 SSNodePort
  ③ 唯一: 一个类型只有一个主 Tx 节点 (端口); 同一节点多出口必须类型互不相同
  ④ 入口: 类型 = 唯一上游出口类型; 多上游 (fan-in) 必须显式标 zmax::<Stem>In 并列出生产者
  ⑤ 落库: 工程库 mw_topic.type 与注册表逐条一致
  ⑥ 命名: ^zmax::[A-Z][A-Za-z0-9]*$ (英文驼峰, 不夹中文/空格/下划线)

命令行: ./gui-venv311/bin/python tools/verify_topic_types.py [-v]
"""
from __future__ import annotations

import collections
import re
import sys

sys.path.insert(0, "src")

from lerobot.middleware import db                                       # noqa: E402
from lerobot.middleware import topic_types as tt                        # noqa: E402

PAT = re.compile(r"^zmax::[A-Z][A-Za-z0-9]*$")


def main() -> int:
    verbose = "-v" in sys.argv
    doc = tt.registry()
    nodes = (doc.get("nodes") or {})
    live = db.node_rows()
    live_ids = {n["node_id"] for n in live}
    ok = True
    fails = []

    def chk(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            fails.append(msg)
        return cond

    # ① 覆盖
    chk(bool(nodes), "注册表为空 (先跑 tools/gen_topic_types.py)")
    missing = sorted(live_ids - set(nodes))
    extra = sorted(set(nodes) - live_ids)
    chk(not missing, "注册表缺节点: %s" % missing)
    chk(not extra, "注册表多了画布没有的节点: %s" % extra)
    n_topic = n_out = n_in = 0
    for nid, nd in nodes.items():
        for p in nd.get("outs") or {}:
            n_out += 1
        for p in nd.get("ins") or {}:
            n_in += 1
    n_topic = n_out + n_in

    # ② 出口 = 主 Tx 语义; ③ 唯一
    owner = collections.defaultdict(list)
    for nid, nd in nodes.items():
        outs = nd.get("outs") or {}
        types_here = []
        for port, o in outs.items():
            t = o.get("type") or ""
            chk(t.startswith("zmax::"), "%s.%s 没有类型" % (nid, port))
            chk(t != "zmax::SSNodePort", "%s.%s 还是信封名 SSNodePort (没有数据意义)" % (nid, port))
            chk(bool(PAT.match(t)), "%s.%s 命名不合规: %s" % (nid, port, t))
            owner[t].append("%s.%s" % (nid, port))
            types_here.append(t)
        chk(len(types_here) == len(set(types_here)),
            "%s 内部多出口类型重名 (下游无法区分): %s" % (nid, types_here))
    shared = {t: w for t, w in owner.items() if len(w) > 1}
    chk(not shared, "类型被多个出口共用 (难以说明谁是主 Tx): %s" % shared)

    # ④ 入口 = 唯一上游类型
    fan_in = []
    for nid, nd in nodes.items():
        for port, i in (nd.get("ins") or {}).items():
            prod = i.get("producers") or []
            up_types = [t for u in prod for t, ws in owner.items()
                        if any(w == u or w.startswith(u + ".") for w in ws)]
            uniq = sorted(set(up_types))
            if len(uniq) == 1:
                chk(i["type"] == uniq[0],
                    "%s.%s 入口类型 %s ≠ 上游 %s" % (nid, port, i["type"], uniq[0]))
            else:
                fan_in.append((nid, port, i["type"], len(uniq), prod))
                chk(i["type"].endswith("In") or "In" in i["type"],
                    "%s.%s 多上游 %d 种却叫 %s (应该叫 <Stem>In)" % (nid, port, len(uniq), i["type"]))

    # ⑤ 落库一致
    conn = db.connect()
    try:
        rows = list(conn.execute("SELECT node_id,port,dir,type,topic FROM mw_topic"))
    finally:
        conn.close()
    bad = [(r[0], r[1], r[3]) for r in rows
           if (r[3] or "") != ((nodes.get(r[0]) or {}).get("outs", {}).get(r[1], {}) or
                               (nodes.get(r[0]) or {}).get("ins", {}).get(r[1], {})).get("type", "")] 
    chk(len(rows) == n_topic, "库里话题 %d ≠ 注册表 %d" % (len(rows), n_topic))
    chk(not bad, "库与注册表不一致 %d 条 (例: %s) —— 跑 db.sync() 重新落库" % (len(bad), bad[:3]))
    chk(all((r[3] or "") != "zmax::SSNodePort" for r in rows), "库里还有信封名 SSNodePort")

    # 统计
    print("=" * 78)
    print("topic 类型全局检查 · 工程 %s" % db.project_of())
    print("  话题 %d  (出口 %d · 入口 %d) · 节点 %d · 语义类型 %d 种"
          % (n_topic, n_out, n_in, len(nodes), len(owner)))
    print("  fan-in 入口 %d 条 (多上游语义不同, 类型 = <Stem>In + 生产者清单)" % len(fan_in))
    top = collections.Counter()
    for t, ws in owner.items():
        top[t.split("::")[-1]] += 1
    print("  主 Tx 类型示例: %s" % ", ".join(sorted(top)[:12]))
    if verbose:
        print("\n  ── 出口类型 (主 Tx) ──")
        for nid, nd in sorted(nodes.items()):
            for port, o in (nd.get("outs") or {}).items():
                print("    %-16s %-6s %-30s %s" % (nid, port, o["type"], o.get("cn") or ""))
        if fan_in:
            print("\n  ── fan-in 入口 ──")
            for r in fan_in[:20]:
                print("    %-16s %-6s %-26s 上游 %d: %s" % (r[0], r[1], r[2], r[3], ",".join(r[4])))
    print("-" * 78)
    if ok:
        print("✅ 全部通过: 每个 topic 都有语义类型, 且类型挂在唯一的主发送节点上")
        return 0
    for f in fails:
        print("❌ " + f)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
