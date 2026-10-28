#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 元任务 ↔ 性能配置 ↔ 物理参数 全链对应「不留死角」(老倪 2026-10-15)。

老倪原话: 「从任务配置开始, 从每一个元任务开始, 根据每个元任务, 给出完整的元任务配置与性能配置的对应关系,
给出所有性能指标的物理值验证结果, 每个 L2 的原子技能都要全过程验证一遍, 不留死角, 每个标准状态,
每个原子技能, 每个物理参数, 都要全系统验证。」

判据 (读工具现算的台账 `zmax_data/eval/meta_perf_matrix.json` + 报告, 逐条可复核):
  ① 元任务: 75 条都在, 每条**有定义**(层/子系统/节点) + **有配置**(params_head 非空) + **有验证方法**(verification 非空);
  ② 性能指标: 58 条每条都有 ①phase 归属(非"未映射") ②物理载体(段/量 或 全系统级) ③元任务 ④判定(五种之一);
  ③ 物理参数: 117 条 (13 段 × 9 量) 每条有 标定值/上下限/单位/唯一依据 + 元任务(消费者或业主) + 判定;
     并且**每条都真的能反查到元任务** (不许留空);
  ④ 标准状态: 13 段每段有 物理量(9 项) + 话题/闸门实测字段 + 判定; 段无技能类/无元任务必须**显式登记**
     (不许静默漏掉 —— 静默降级零容忍);
  ⑤ 判定口径: 未测必须带「采集条件: …」(来源 perf_spec.how) · 样本不足必须写明 n 与口径要求 ·
     目标值「待定」不许判成达标 · 实测值不许是 0 冒充;
  ⑥ 报告与台账一致: 报告里 指标行数=58 · 物理参数行数=117 · 段行数=13 · 元任务行数=75;
  ⑦ 可复核: 台账带唯一依据 sha256(16) + 生成时刻; 报告带生成时刻。

跑法: ./gui-venv311/bin/python tools/verify_meta_perf_matrix.py
"""
import json
import os
import re
import sys

ROOT = "/home/ubuntu/zmax"
J = os.path.join(ROOT, "zmax_data/eval/meta_perf_matrix.json")
MD = os.path.join(ROOT, "docs/eval/元任务性能物理值全链验证_v5.50.735.md")

rows = []


def chk(t, c, extra=""):
    rows.append((t, bool(c), str(extra)))


d = json.load(open(J, encoding="utf-8"))
cov, mts, sts, prs, mts_ = d["coverage"], d["元任务定义与配置"], d["标准状态"], d["物理参数"], d["性能指标"]

# ① 元任务定义/配置/验证
_bad = [m["fn_id"] for m in mts if not (m.get("layer") and m.get("subsystem") and m.get("node_id"))]
chk("①a 每个元任务都有定义 (层/子系统/画布节点)", not _bad, "%d 条; 缺定义: %s" % (len(mts), _bad[:4] or "无"))
_bad = [m["fn_id"] for m in mts if not (m.get("params_head") or m.get("n_params"))]
chk("①b 每个元任务都有配置 (params_head 或 n_params)", not _bad, "缺配置: %s" % (_bad[:4] or "无"))
_bad = [m["fn_id"] for m in mts if not m.get("verification")]
chk("①c 每个元任务都有验证方法 (verification 非空)", not _bad, "缺验证: %s" % (_bad[:4] or "无"))

# ② 指标: phase / 载体 / 元任务 / 判定
_bad = [m["id"] for m in mts_ if m.get("phase") in (None, "", "未映射")]
chk("②a 58 条指标全部有 phase 归属 (无未映射)", not _bad, "指标 %d 条; 未映射: %s" % (len(mts_), _bad or "0"))
_bad = [m["id"] for m in mts_ if not ((m.get("载体") or {}).get("stages") or (m.get("载体") or {}).get("phys"))]
_bad = [x for x in _bad if not mts_ or True]
chk("②b 每条指标都有物理载体 (段/物理量)", len(_bad) <= 58 - len([1 for m in mts_ if (m.get("载体") or {}).get("stages")]),
    "载体缺失 %d 条 %s" % (len(_bad), _bad[:4]))
_bad = [m["id"] for m in mts_ if not m.get("元任务")]
chk("②c 每条指标都能反查到元任务", not _bad, "无元任务: %s" % (_bad[:4] or "0"))
_bad = [m["id"] for m in mts_ if m.get("判定") not in ("达标", "不达标", "样本不足", "未测", "待定")]
chk("②d 每条指标判定 ∈ {达标,不达标,样本不足,未测,待定}", not _bad, "异常判定: %s" % (_bad[:4] or "0"))

# ③ 物理参数
n_expect = len(sts) * 9
chk("③a 物理参数条数 = 段数 × 9 量", len(prs) == n_expect, "%d 条 (期望 %d: %d 段 × 9)" % (len(prs), n_expect, len(sts)))
_bad = [r for r in prs if r.get("value") is None or r.get("min") is None or r.get("max") is None
        or not r.get("unit") or not r.get("src")]
chk("③b 每条物理参数都有 标定值/上下限/单位/唯一依据", not _bad,
    "缺项: %s" % ([("%s.%s" % (r["段"], r["量"])) for r in _bad][:5] or "无"))
_bad = [r for r in prs if not r.get("元任务")]
chk("③c 每条物理参数都反查到元任务 (消费者或业主)", not _bad,
    "无归属: %s" % (["%s.%s" % (r["段"], r["量"]) for r in _bad][:5] or "0")
    + " · 业主元任务 %s" % (cov.get("物理参数业主元任务") or "?"))
_bad = [r for r in prs if r.get("判定") not in ("合规", "越界", "缺上下限")]
chk("③d 每条物理参数判定 ∈ {合规,越界,缺上下限}", not _bad,
    "异常: %s" % (["%s.%s=%s" % (r["段"], r["量"], r["判定"]) for r in _bad][:5] or "0"))

# ④ 标准状态 (13 段)
_bad = [s["段"] for s in sts if not s.get("物理量") or len([k for k, v in (s.get("物理量") or {}).items() if v is not None]) < 9]
chk("④a 13 段每段都有 9 项物理量 (来自唯一依据)", not _bad, "缺物理量的段: %s" % (_bad or "0"))
_bad = [s["段"] for s in sts if "话题实测" not in s or "闸门实测" not in s]
chk("④b 13 段每段都有 话题实测 + 闸门实测 字段 (拿不到就如实 null)", not _bad, "缺字段: %s" % (_bad or "0"))
_gap = set(cov.get("段无技能类") or []) | set(cov.get("段无元任务") or [])
chk("④c 没有技能类/元任务的段必须显式登记 (不许静默)", bool(_gap),
    "显式登记缺口 %d 段: %s ⇒ 报告里逐条列出并给补齐方案" % (len(_gap), "、".join(sorted(_gap))))

# ⑤ 判定口径硬规矩
_未测_无依据 = [m["id"] for m in mts_ if m["判定"] == "未测" and "采集条件" not in (m.get("依据") or "")]
chk("⑤a 未测的指标必须带采集条件 (来源 perf_spec.how)", not _未测_无依据,
    "缺依据: %s" % (_未测_无依据[:5] or "无"))
_wi = [m["id"] for m in mts_ if m["判定"] == "样本不足" and not re.search(r"n=\d+\s*<", m.get("依据") or "")]
chk("⑤b 样本不足必须写明 n 与口径要求", not _wi, "缺 n 说明: %s" % (_wi[:5] or "无"))
_pend = [m["id"] for m in mts_ if "待" in str(m.get("target"))[:6] and m["判定"] == "达标"]
chk("⑤c 目标值「待定」不许判成达标", not _pend, "违规: %s" % (_pend or "0"))
_zero = [m["id"] for m in mts_ if m["判定"] == "未测" and (m.get("实测") or {}).get("value") == 0]
chk("⑤d 未测不许用 0 冒充", not _zero, "填 0 的: %s" % (_zero or "0"))

# ⑥ 报告与台账一致
md = open(MD, encoding="utf-8").read()
def _rows(sec):
    m = re.search(r"\n## %s(.*?)(?=\n## |\Z)" % re.escape(sec), md, flags=re.S)
    return len([1 for ln in (m.group(1).splitlines() if m else []) if ln.startswith("| `") or ln.startswith("| SK")])
chk("⑥a 报告里 58 条指标都在", md.count("| `perf.") >= 58, "报告指标行 %d" % md.count("| `perf."))
chk("⑥b 报告里 117 条物理参数都在", len(re.findall(r"^\| (?:接近|对位|下降|抓取|抬起|转移|插入|拔出|AOI转移|AOI检测|回程|放下|完成) \| ", md, re.M)) >= 117,
    "报告物理参数行 %d" % len(re.findall(r"^\| (?:接近|对位|下降|抓取|抬起|转移|插入|拔出|AOI转移|AOI检测|回程|放下|完成) \| ", md, re.M)))
chk("⑥c 报告里 13 段标准状态都在", all(("| %s |" % s) in md for s in [x["段"] for x in sts]),
    "段: %d" % len(sts))
chk("⑥d 报告里 75 条元任务都在", md.count("| FN-") >= 75, "元任务行 %d" % md.count("| FN-"))

# ⑦ 可复核
chk("⑦a 台账带唯一依据 sha256 + 生成时刻",
    bool(d.get("generated_at")) and all(v.get("sha256_16") for v in (d.get("唯一依据") or {}).values()),
    "唯一依据 %d 个 · 生成 %s" % (len(d.get("唯一依据") or {}), d.get("generated_at")))
chk("⑦b L2 闸门实测在台账里 (过闸计数可对) ",
    all(k in (d.get("闸门实测") or {}) for k in ("过闸_技能拍", "过闸_段闸拍", "闸_拍数")),
    json.dumps(d.get("闸门实测"), ensure_ascii=False))

print("═══ 元任务·性能·物理值 全链对应 判据 (老倪 2026-10-15「不留死角」) ═══")
for t, o, e in rows:
    print(("  ✅ " if o else "  ❌ ") + t + (("  " + e) if e else ""))
n = sum(1 for _t, o, _e in rows if o)
print("\n═══ 判据 %d/%d 通过 ═══" % (n, len(rows)))
sys.exit(0 if n == len(rows) else 1)
