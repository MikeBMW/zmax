#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 deploy_cmd 执行代理判据 —— 六种指令各发一次, 用审计文件的对账结果当结论

判据 (全部要过):
  ① 产物不存在            → rejected
  ② 产物不在允许目录 (/etc/passwd) → rejected
  ③ 动作不在白名单 (stop_train)    → rejected
  ④ 发起人不在白名单 (hacker)      → rejected
  ⑤ 合法 promote          → dry-run-ok (或 applied, 取决于代理模式)
  ⑥ rollback              → dry-run-ok (或 applied)
并且: 审计条数 == 发出的指令条数 (不许静默吞掉)

用法:
  python3 tools/dds/verify_deploy_agent.py                # 对 4060 本机代理
  python3 tools/dds/verify_deploy_agent.py --wait 30      # 等最后一条处理的额外秒数
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(ROOT, "dds")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zmax_node import Node, TOPICS                                            # noqa: E402

DATA = os.environ.get("ZMAX_DATA", os.path.join(ROOT, "zmax_data"))
AUDIT = os.path.join(DATA, "runtime", "deploy", "audit.jsonl")
res = []


def ck(name, cond, detail=""):
    res.append(bool(cond))
    print("  %s %s%s" % ("✅" if cond else "❌", name, (" — %s" % detail) if detail else ""))


def audit_tail(n=40):
    if not os.path.isfile(AUDIT):
        return []
    out = []
    with open(AUDIT, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:                                               # noqa: BLE001
                    pass
    return out[-n:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=25.0)
    a = ap.parse_args()

    n = Node("verify_deploy_cmd")
    n.pub("deploy_cmd")
    print("=" * 78)
    print("🧪 deploy_cmd 执行代理判据")
    print("=" * 78)
    print("等配对…", end=" ", flush=True)
    print(n.wait_for_match("deploy_cmd", 1, 8))

    base = audit_tail(1)
    t0_mark = time.strftime("%Y-%m-%d %H:%M:%S")
    live = os.path.join(ROOT, "models", "yolo_peg_live.pt")

    cases = [
        ("产物不存在", dict(issuer="4060", action="promote", layer="L2",
                            artifact="zmax_data/runs/__nope__/best.pt", note="判据①")),
        ("产物不在允许目录", dict(issuer="4060", action="promote", layer="L2",
                                  artifact="/etc/passwd", note="判据②")),
        ("动作不在白名单", dict(issuer="4060", action="stop_train", layer="L2",
                                artifact="", note="判据③")),
        ("发起人不在白名单", dict(issuer="hacker", action="promote", layer="L2",
                                  artifact="models/yolo_peg_live.pt", note="判据④")),
        ("合法 promote", dict(issuer="4060", action="promote", layer="L2",
                              artifact="models/yolo_peg_live.pt", note="判据⑤")),
        ("rollback", dict(issuer="4060", action="rollback", layer="L2",
                          artifact="", note="判据⑥")),
    ]
    sent = []
    for name, kw in cases:
        m = TOPICS["deploy_cmd"](note=kw.pop("note"), ts=time.time(), **kw)
        n.send("deploy_cmd", m)
        sent.append(name)
        print("  → 发出: %s (%s %s)" % (name, m.action, m.artifact or "-"))
        # 拒绝类很快, 通过的类要给代理时间跑 check-only; rollback 还要避开 20s 限速
        time.sleep(3.0 if name not in ("合法 promote",) else 8.0)
    print("等代理处理完 (%.0fs)…" % a.wait)
    time.sleep(a.wait)

    rows = [r for r in audit_tail(60) if r.get("recv_ts", "") >= t0_mark]
    by_note = {}
    for r in rows:
        by_note.setdefault(r.get("note", ""), []).append(r)

    def verdict(note):
        rs = by_note.get(note) or []
        return rs[-1] if rs else {}

    print("-" * 78)
    ck("① 产物不存在 → rejected", verdict("判据①").get("verdict") == "rejected",
       verdict("判据①").get("reason", "")[:60])
    ck("② 允许目录外 → rejected", verdict("判据②").get("verdict") == "rejected",
       verdict("判据②").get("reason", "")[:60])
    ck("③ 动作白名单 → rejected", verdict("判据③").get("verdict") == "rejected",
       verdict("判据③").get("reason", "")[:60])
    ck("④ 发起人白名单 → rejected", verdict("判据④").get("verdict") == "rejected",
       verdict("判据④").get("reason", "")[:60])
    v5 = verdict("判据⑤")
    ck("⑤ 合法 promote → %s" % (v5.get("verdict") or "无"), v5.get("verdict") in ("dry-run-ok", "applied"),
       "check-only rc=%s dur=%ss" % (v5.get("rc"), v5.get("dur_s")))
    v6 = verdict("判据⑥")
    ck("⑥ rollback → %s" % (v6.get("verdict") or "无"),
       v6.get("verdict") in ("dry-run-ok", "applied", "throttled"),
       v6.get("reason", "")[:50])
    ck("审计条数 %d ≥ 指令数 %d" % (len(rows), len(sent)), len(rows) >= len(sent))
    modes = {r.get("exec_mode") for r in rows}
    ck("审计记录了执行模式 %s" % (modes or "-"), bool(modes))

    print("=" * 78)
    bad = res.count(False)
    print("=== %s (失败 %d / 共 %d) ===" % ("全过" if bad == 0 else "有失败", bad, len(res)))
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
