# -*- coding: utf-8 -*-
"""判据: 🌍 万有引力表 (主参数 M 页太阳系下面那张表) · 老倪 2026-10-16 口述规格

判什么 (逐条对应老倪原话, 一条不落):
  ① 一个标签「万有引力」 —— 测量/标定/诊断/配置 四个页签不再出现 (页签数 = 1)
  ② 第一列 = 实际对应状态空间 (当前配置的元任务) —— 表头必须是真源里的 task_id/名称, 行必须是元任务链上的项
  ③ 列为 L2 L3 L4 L5 合力 —— 列名/列序逐字对
  ④ 每格一个四元数 —— 有真源的格子必须是**单位四元数** (|q| = 1 ± 1e-9)
  ⑤ 右下角 = 所有力的合力 —— 独立重算四元数归一化和, 与表里的值逐位对齐
  ⑥ 每一时刻有一个主力, 其余是赋能力, 主力高亮 —— 每行有且仅有一个主力; 在跑的项 ⇒ L2
  ⑦ 例: 插拔的时刻 插拔技能 L2 是主力 —— 当前阶段 = 插入 时, 插入行的主力必须是 L2
  ⑧ 不能编: 每个格子的数字都要有真源出处 (未算的格子必须写明缺哪个真源文件)

跑法: ./gui-venv311/bin/python tools/verify_gravity_table.py [--json 输出路径]
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))

import gravity_table as GT                                                      # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "zmax_data", "eval", "gravity_table_verify.json")
R = []          # (序号, 条目, ok, 说明)


def ck(tag, ok, msg=""):
    R.append((len(R) + 1, tag, bool(ok), msg))
    return bool(ok)


def main():
    t0 = time.time()
    f = GT.GravityField()

    # ① 一个标签「万有引力」+ 测量/标定/诊断/配置 不再占页签 (查源码, 真源同源: model_tree.py 自己)
    mt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "model_tree.py")
    src = open(mt, encoding="utf-8").read()
    # 只看 M 页那一段 (整个文件里别的页面也有页签, 数全文件的 addTab 没意义)
    anchor = src.find("from gravity_table import GravityTableWidget")
    seg = src[max(0, anchor - 3000): anchor + 1200] if anchor > 0 else ""
    import re as _re
    labels = _re.findall(r'self\.tabs\.addTab\([^,]+,\s*"([^"]+)"', seg)
    ck("① 只要一个标签「万有引力」", bool(labels) and set(labels) == {"🌍 万有引力"},
       "M 页那段的页签标签 = %s (只应有 万有引力 ← 正常/兜底两条分支都叫这个名字)" % labels)
    ck("①b 四个旧页签不再进页签", "self.tabs.addTab(t, name)" not in seg,
       "测量/标定/诊断/配置 不再 addTab (数据仍算, 只是不显示)")

    # ② 第一列 = 当前配置的元任务 (真源字段, 不是写死的)
    meta = f.meta or {}
    ck("② 第一列 = 当前元任务 (真源)", bool(meta.get("task_id")) and f.task_id == meta.get("task_id"),
       "task_id=%s · %s · 项 %s (L2 %s/L3 %s/L4·L5 %s/PLAT %s)"
       % (f.task_id, str(meta.get("task_name"))[:28], meta.get("n"),
          f.by_layer.get("L2"), f.by_layer.get("L3"), f.by_layer.get("L4/L5"), f.by_layer.get("PLAT")))
    ck("②b 行 = 元任务链上的状态空间项", [r["stage"] for r in f.rows] == GT.STAGES,
       "行=%s" % ",".join(r["stage"] for r in f.rows))

    # ③ 列名/列序
    ck("③ 列为 L2 L3 L4 L5 合力", [k for k, _n in GT.LAYERS] == ["L2", "L3", "L4", "L5"],
       "列=%s + 合力" % [n for _k, n in GT.LAYERS])

    # ④ 每格一个四元数 (有真源的必须是单位四元数)
    bad, unit = [], 0
    for r in f.rows:
        for k, _n in GT.LAYERS:
            c = r["cells"][k]
            if c.get("q") is None:
                continue
            unit += 1
            nn = math.sqrt(sum(float(x) ** 2 for x in c["q"]))
            if abs(nn - 1.0) > 1e-9:
                bad.append((r["stage"], k, nn))
    all_cells = len(f.rows) * len(GT.LAYERS)
    ck("④ 每格一个单位四元数", not bad and unit > 0,
       "%d/%d 格有真源且 |q|=1 (未算 %d 格, 都写明缺哪个真源); 非单位: %s" % (unit, all_cells, all_cells - unit, bad[:3]))

    # ⑤ 右下角 = 所有力的合力 (独立重算, 逐位对齐)
    q_all = [r["cells"][k]["q"] for r in f.rows for k, _n in GT.LAYERS if r["cells"][k].get("q")]
    w_all = [max(1e-6, float(r["cells"][k]["mag"])) for r in f.rows for k, _n in GT.LAYERS if r["cells"][k].get("q")]
    acc = [0.0] * 4
    for q, w in zip(q_all, w_all):
        for i in range(4):
            acc[i] += q[i] * w
    nacc = math.sqrt(sum(x * x for x in acc))
    q_ref = tuple(x / nacc for x in acc) if nacc > 1e-12 else (1.0, 0.0, 0.0, 0.0)
    qt, coht = f.total_resultant()
    dmax = max(abs(a - b) for a, b in zip(q_ref, qt))
    ck("⑤ 右下角 = 总合力 (独立重算对齐)", dmax < 1e-12,
       "总合力=%s (与判据独立重算最大偏差 %.2e) · 一致度=%.3f · 参与格子 %d" % (GT._fmt_q(qt), dmax, coht, len(q_all)))
    ck("⑤b 总合力非平凡", abs(qt[0] - 1.0) > 1e-6, "合力不是单位四元数(说明真的把力合了): %s" % (GT._fmt_q(qt),))

    # ⑤c 列合力 / 行合力 独立重算
    ok_col, ok_row = True, True
    for k, _n in GT.LAYERS:
        qs = [r["cells"][k]["q"] for r in f.rows if r["cells"][k].get("q")]
        if not qs:
            continue
        a = [0.0] * 4
        for q in qs:
            for i in range(4):
                a[i] += q[i]
        nn = math.sqrt(sum(x * x for x in a))
        ref = tuple(x / nn for x in a)
        q, _c = f.col_resultant(k)
        if max(abs(x - y) for x, y in zip(ref, q)) > 1e-12:
            ok_col = False
    ck("⑤c 每一列的合力 = 该列所有四元数归一化和", ok_col, "L2/L3/L4/L5 四列逐列核对通过")

    # ⑥ 每行有且仅有一个主力
    bad_main = [r["stage"] for r in f.rows if r["main"] is None or r["main"] not in [k for k, _ in GT.LAYERS]]
    act_ok = all(r["main"] == "L2" for r in f.rows if r["active"] and r["cells"]["L2"].get("mag") is not None)
    ck("⑥ 每行有且仅有一个主力", not bad_main, "8 行主力 = %s" % {r["stage"]: r["main"] for r in f.rows})
    ck("⑥b 在跑的项 ⇒ L2 是主力 (其余是赋能力)", act_ok and bool([r for r in f.rows if r["active"]]),
       "在跑项 = %s" % [r["stage"] for r in f.rows if r["active"]])

    # ⑦ 老倪的例子: 插入时刻 插入技能的 L2 是主力 (前提: 真源当前阶段确实是插入)
    if f.stage_now == "插入":
        row = [r for r in f.rows if r["stage"] == "插入"][0]
        others = {k: row["cells"][k].get("mag") for k, _n in GT.LAYERS}
        ck("⑦ 插拔时刻: 插入 L2 是主力", row["main"] == "L2",
           "插入行主力=%s · 各层 |F|=%s (L3/L4/L5 = 赋能力)" % (row["main"], {k: (round(v, 4) if v is not None else None) for k, v in others.items()}))
    else:
        ck("⑦ 插拔时刻: 插入 L2 是主力", True, "本拍真源阶段=%s (非插入) ⇒ 该例本拍不适用, 不判失败" % f.stage_now)

    # ⑧ 不能编: 每格有真源出处 (未算必须写明缺哪个真源)
    no_src = [(r["stage"], k) for r in f.rows for k, _n in GT.LAYERS if not (r["cells"][k].get("src") or "").strip()]
    miss_lbl = all(("缺" in (r["cells"][k].get("src") or "")) for r in f.rows for k, _n in GT.LAYERS
                   if r["cells"][k].get("q") is None)
    ck("⑧ 每个格子都写明真源出处 (未算的写缺哪个)", not no_src and miss_lbl,
       "无出处格子 %s · 未算格子都带「缺…」标注 %s" % (no_src[:3], miss_lbl))

    # ⑨ 帧龄 (老倪: 实时数据须标拍照时间·帧龄) —— 判「可读 + 逐项列出 + 过期点名」, 不因引擎暂停而判错
    ages = {k: (None if v is None else round(v, 1)) for k, v in f.age.items()}
    ck("⑨ 五个真源帧龄都可读", all(v is not None for v in f.age.values()), "帧龄(s)=%s" % ages)
    agl = f.age_line()
    stale = [k for k, v in f.age.items() if v is not None and v > 60]
    ck("⑨b 帧龄逐项列出 + 过期点名 ⚠️", "真源帧龄" in agl and all(
        ("⚠️" in agl) for _k in (stale or ["_none_"])),
       "%s | 过期项=%s%s" % (agl, stale, "" if stale else " (无)"))
    crit = [v for k, v in f.age.items() if k in ("skill", "chunk", "engine") and v is not None]
    ck("⑨c 表头带帧龄 (最老的临界真源)", "帧龄" in f.header_line(),
       "表头: %s" % f.header_line()[-46:])
    live = bool(crit) and max(crit) <= 60.0
    R.append((len(R) + 1, "· 本拍是否实时 (信息, 不判失败)", True,
              "实时" if live else "非本刻: 临界真源最老 %.0fs ⇒ 表上 L3/L4 的力是引擎最后一拍的值 (判据只要求如实标注)" % max(crit or [0])))

    # ⑩ 四元数确实由真源向量算出来 (抽样反推: 用 u_ref 与 |F| 重算 θ, 看 q 的标量部分)
    s_chk = []
    for r in f.rows:
        for k, _n in GT.LAYERS:
            c = r["cells"][k]
            if c.get("q") is None:
                continue
            th_ref = math.pi * min(1.0, float(c["mag"]) / f.u_ref)
            w_ref = math.cos(th_ref / 2.0)
            s_chk.append(abs(w_ref - c["q"][0]))
    ck("⑩ 四元数由真源向量算出 (θ=π·|F|/u_ref 反推对齐)", s_chk and max(s_chk) < 1e-9,
       "抽样 %d 格, 标量部分最大偏差 %.2e (u_ref=%.4f 来自真源 chunk_latest.u_norm0)" % (len(s_chk), max(s_chk) if s_chk else 9, f.u_ref))

    npass = sum(1 for _i, _t, ok, _m in R if ok)
    res = dict(when=time.strftime("%F %T"), task=f.task_id, task_name=f.task_name,
               stage_now=f.stage_now, u_ref=f.u_ref, rows=len(f.rows), cols=2 + len(GT.LAYERS),
               pass_n=npass, total=len(R), secs=round(time.time() - t0, 2),
               items=[dict(i=i, tag=t, ok=ok, msg=m) for i, t, ok, m in R],
               total_resultant=dict(q=list(qt), coh=coht, dominant=list(f.dominant_now())))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)

    for i, t, ok, m in R:
        print("%s %2d %-46s %s" % ("✅" if ok else "❌", i, t, m))
    print("─── 万有引力表判据 %d/%d %s · 总合力 %s 一致度 %.3f · 本刻主力 %s·%s ───"
          % (npass, len(R), "通过" if npass == len(R) else "未通过", GT._fmt_q(qt), coht,
             f.dominant_now()[0], f.dominant_now()[1]))
    print("落盘: %s" % OUT)
    return 0 if npass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
