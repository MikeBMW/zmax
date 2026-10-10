#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能指标清单导出 (老倪: 「显示内容要可复制可导出」)

真源 config/platform/zmax_perf_spec.json → 供应商可用的 CSV + 人可读 Markdown 清单。
不产生第二份真相: 只读真源, 输出带真源 sha256 与条数, 便于核对。
用法: python tools/perf_spec_export.py            # 输出到 outputs/perf_spec/<ts>/
      config_center.py perf                      # 同一入口
"""
import csv
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "config/platform/zmax_perf_spec.json")
OUT_ROOT = os.path.join(ROOT, "outputs/perf_spec")
COLS = ["组", "组名", "指标ID", "指标", "单位", "目标值(规格)", "状态", "口径/标准", "验收阶段", "测量/实测入口", "关联功能/能力"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def rows():
    d = json.load(open(SRC, encoding="utf-8"))
    out = []
    for g in d["groups"]:
        for m in g["metrics"]:
            _t = str(m.get("target") or "待确认")
            out.append([g["gid"], g["name"], m["id"], m["cn"], m.get("unit") or "-", _t,
                        "目标值待确认" if _t.startswith("待") else "指标定义(目标值=规格)",
                        m.get("std", "-"), m.get("stage", "-"),
                        m.get("how", ""), " · ".join(m.get("links") or [])])
    return d, out


def main():
    d, rs = rows()
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_ROOT, ts)
    os.makedirs(out, exist_ok=True)
    csvp = os.path.join(out, "性能指标清单_%s.csv" % ts)
    with open(csvp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rs)
    mdp = os.path.join(out, "性能指标清单_%s.md" % ts)
    L = ["# System 1 光模块精细操作 · 性能指标清单", "",
         "- 真源: `config/platform/zmax_perf_spec.json` sha256 `%s`" % sha(SRC),
         "- 条数: %d 条 / %d 组 · 导出 %s" % (len(rs), len(d["groups"]), time.strftime("%F %T")),
         "- 口径: value = 目标值(规格); 实测值在各阶段验收时填入, 未实测不填数", ""]
    L += ["## 引用标准", ""]
    for k, v in d["standards"].items():
        L.append("- **%s** — %s" % (k, v))
    for g in d["groups"]:
        L += ["", "## %s %s (%d 条)" % (g["gid"], g["name"], len(g["metrics"])), "",
              "| 指标 | 单位 | 目标值 (规格) | 口径/标准 | 阶段 |", "|---|---|---|---|---|"]
        for m in g["metrics"]:
            L.append("| %s | %s | %s | %s | %s |" % (m["cn"], m.get("unit") or "-",
                                                     str(m.get("target") or "待确认").replace("|", "/"),
                                                     m.get("std", "-"), m.get("stage", "-")))
        L.append("")
        for m in g["metrics"]:
            L.append("- `%s` 测量/实测入口: %s" % (m["id"], m.get("how", "")))
    open(mdp, "w", encoding="utf-8").write("\n".join(L) + "\n")
    n_gap = sum(1 for r in rs if r[5].startswith("待"))
    print("✅ 性能指标清单: %d 条 / %d 组 (指标已定义 %d · 目标值待确认 %d)"
          % (len(rs), len(d["groups"]), len(rs) - n_gap, n_gap))
    print("   CSV : %s" % csvp)
    print("   MD  : %s" % mdp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
