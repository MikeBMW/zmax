#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_canvas_gs_recon.py — 校验画布新接线(sssensor.out3 → ssobs.in2)自洽, 且没引入新问题。

重要口径(2026-11-19 实测): 这个画布本来就有 ~130 条"端口未声明"的存量问题 —— GUI 对隐式端口是容忍的
(端口按连线动态生成)。所以本脚本**不做全量否决**, 而是:
  ① 与最近一次备份(.bak_gsrecon_*)逐条对比, 只报**新增**问题(存量问题不算回归)
  ② 单独硬断言: out3 已声明 / 连线存在且端口名匹配 / params 记录了真源·脚本·服务·API
  ③ 节点 id 唯一 · 坐标整数 · link id 重复(排除 None)
退出码 0 = 无新增问题且硬断言全过。
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")


def _collect(path: str):
    """返回 (nodes, links, errs, by)。errs = 数据一致性问题(不区分新增/存量)。"""
    errs, by = [], {}
    d = json.load(open(path, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    for n in nodes:
        if n["id"] in by:
            errs.append("节点 id 重复: %s" % n["id"])
        by[n["id"]] = n
        for k in ("x", "y", "w", "h"):
            if k in n and not isinstance(n[k], int):
                errs.append("%s.%s 非整数: %r" % (n["id"], k, n[k]))
    lids = set()
    for l in links:
        lid = l.get("id")
        if lid is not None and lid in lids:
            errs.append("连线 id 重复: %s" % lid)
        lids.add(lid)
        f, t = l.get("f"), l.get("t")
        if f not in by or t not in by:
            errs.append("连线 %s 引用不存在节点: %s → %s" % (lid, f, t))
            continue
        if l.get("f_port") and l["f_port"] not in by[f].get("outputs", []):
            errs.append("连线 %s 源端口不存在: %s.%s" % (lid, f, l["f_port"]))
        if l.get("t_port") and l["t_port"] not in by[t].get("inputs", []):
            errs.append("连线 %s 目标端口不存在: %s.%s" % (lid, t, l["t_port"]))
    return nodes, links, errs, by


def main() -> int:
    fails = []
    try:
        nodes, links, errs, by = _collect(FLOW)
    except Exception as e:
        print("FAIL 解析 %s: %s" % (FLOW, e))
        return 1

    baks = sorted(glob.glob(FLOW + ".bak_gsrecon_*"))
    base_errs = set()
    if baks:
        _, _, base_list, _ = _collect(baks[-1])
        base_errs = set(base_list)
    new_errs = [e for e in errs if e not in base_errs]

    src = by.get("sssensor", {})
    if "out3" not in src.get("outputs", []):
        fails.append("sssensor 缺 out3")
    if not any(l.get("id") == "lk_gs_recon" and l.get("f") == "sssensor"
               and l.get("f_port") == "out3" and l.get("t") == "ssobs"
               and l.get("t_port") == "in2" for l in links):
        fails.append("缺连线 sssensor.out3 → ssobs.in2")
    p = src.get("params", {})
    for k in ("out3_source", "out3_tool", "out3_service", "out3_api"):
        if not p.get(k):
            fails.append("sssensor.params 缺 %s" % k)

    print("节点 %d · 连线 %d" % (len(nodes), len(links)))
    print("存量问题(基线 %s): %d 条" % (os.path.basename(baks[-1]) if baks else "无", len(base_errs)))
    print("新增问题: %d 条" % len(new_errs))
    for e in new_errs:
        print("  NEW", e)
    for f in fails:
        print("  FAIL", f)
    ok = not new_errs and not fails
    print("RESULT", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
