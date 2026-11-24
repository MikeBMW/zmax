#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_engine_gate.py — 引擎闸判据 (真跑, 不通过 exit 1)

① 缺 src_engine       enforce ⇒ 拒 / warn ⇒ 放行但记账
② 缺 gate.force_ok    enforce ⇒ 拒
③ gate 双真           ⇒ 放行, 且不写 reject 记录
④ 未知引擎名          ⇒ enforce 拒
⑤ 人工点动            ⇒ 放行 + bypass 记账 (不拦现场)
⑥ 自动通道用人工签名  ⇒ 拒 (任何档位)
⑦ ZMAX_ENGINE_GATE=off ⇒ 放行 + 记账, 且 mode 自证
⑧ 记录落盘            ⇒ jsonl 末行可解析, 字段齐
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))

TMP = tempfile.mkdtemp(prefix="gate_")
os.environ["ZMAX_SS_LIVE"] = TMP
from lerobot.engineering.exec import engine_gate as G  # noqa: E402

rows = []


def chk(name, detail, ok):
    rows.append((name, detail, ok))


def log_lines():
    p = os.path.join(TMP, "engine_gate.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(x) for x in open(p, encoding="utf-8").read().splitlines() if x.strip()]


GOOD = {"src_engine": "ss_mani10", "gate": {"force_ok": True, "conf_ok": True}, "skill": "insert"}

os.environ["ZMAX_ENGINE_GATE"] = "enforce"
r = G.validate({"skill": "insert"}, kind="auto")
chk("① 缺 src_engine (enforce)", r["reason"][:40], r["ok"] is False)

os.environ["ZMAX_ENGINE_GATE"] = "warn"
r = G.validate({"skill": "insert"}, kind="auto")
chk("① 缺 src_engine (warn)", "放行但记账: %s" % (r["ok"] is True), r["ok"] is True and any(
    x["reason"].startswith("缺 src_engine") for x in log_lines()))

os.environ["ZMAX_ENGINE_GATE"] = "enforce"
r = G.validate({"src_engine": "ss_mani10", "gate": {"force_ok": True, "conf_ok": False}}, kind="auto")
chk("② gate 缺 conf_ok", r["reason"][:40], r["ok"] is False)

n0 = len(log_lines())
r = G.validate(GOOD, kind="auto")
chk("③ 全齐 ⇒ 放行", r["reason"], r["ok"] is True and len(log_lines()) == n0)

r = G.validate({"src_engine": "my_hack", "gate": {"force_ok": True, "conf_ok": True}}, kind="auto")
chk("④ 未知引擎名", r["reason"][:44], r["ok"] is False)

r = G.validate({"skill": "jog_x+"}, kind="manual")
chk("⑤ 人工点动", "%s · bypass=%s" % (r["src_engine"], r["bypass"]), r["ok"] is True and r["bypass"])

r = G.validate({"src_engine": "manual_jog", "gate": {}}, kind="auto")
chk("⑥ 自动通道用人工签名", r["reason"][:38], r["ok"] is False)

os.environ["ZMAX_ENGINE_GATE"] = "off"
r = G.validate({"skill": "x"}, kind="auto")
chk("⑦ off 档", "mode=%s bypass=%s" % (r["mode"], r["bypass"]), r["ok"] is True and r["mode"] == "off")

last = log_lines()[-1]
need = {"t", "kind", "ok", "mode", "src_engine", "bypass", "reason"}
chk("⑧ 落盘字段", "%d 条 · 缺 %s" % (len(log_lines()), sorted(need - set(last)) or "无"),
    not (need - set(last)))

for name, detail, ok in rows:
    print("  %-26s %-52s %s" % (name, detail, "PASS" if ok else "FAIL"))
n_ok = sum(1 for _, _, ok in rows if ok)
print("  => %d/%d 通过 · 记录文件 %s/engine_gate.jsonl" % (n_ok, len(rows), TMP))
raise SystemExit(0 if n_ok == len(rows) else 1)
