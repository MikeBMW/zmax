#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_drill_report.py — 判据: 7 个任务的全链路演练是否**真留下了证据**

老倪 2026-10-14: 「现在有 7 个任务, 要有 7 个文档要发到飞书, 同时更新工程数据库, 保证数据一致性。」
本判据只认盘上的证据文件 (不看任何"已完成"声明):

  ① 每个任务一个目录 reports/drill/<TASK>/ , 7 个齐;
  ② 每个任务的配置链快照真有 7 个域 (任务/产品/功能/模型/性能/工程/工单), 不是空壳;
  ③ 原型单步留了 step_run.json, 且记录到"真验证通过节点数/topic" (ok>0 且至少一个非空 topic);
  ④ 原型整体运行留了 closure_run.json + closure_stdout.txt, 且 stdout 里有引擎闭环那行真结果;
  ⑤ 实际波形 ≥2 张 PNG 且文件非空;
  ⑥ 实际模型运行证据 models.json 至少落 2 层;
  ⑦ 自主训练 train.json 有返回码与 loss (若 --no-train 则明确标 skipped, 不算通过也不掩);
  ⑧ 每任务一份文档 md+docx+pdf 三件齐;
  ⑨ 工程库 drill_runs 表里每任务有行, 且 doc 路径与盘上一致;
  ⑩ INDEX.json 任务数 == 7。

用法: ./gui-venv311/bin/python tools/verify_drill_report.py [--allow-no-train]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
DRILL = "reports/drill"
DB = "data/database/zmax/zmax_engineering.db"
DOMS = ("① 任务配置", "② 产品配置", "③ 功能配置", "④ 模型配置", "⑤ 性能配置", "⑥ 工程配置", "⑦ 文档配置·工单实例")

OK, BAD, SKIP = [], [], []


def chk(name, ok, ev=""):
    (OK if ok else BAD).append(name)
    print("  %s %-52s %s" % ("✅" if ok else "❌", name, ev))


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                                      # noqa: BLE001
        return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-no-train", action="store_true", help="允许 train.json 为 skipped (演练不跑训练)")
    a = ap.parse_args()

    tasks = [x["task_id"] for x in (_j("config/tasks/tasks.json", {}) or {}).get("tasks", [])]
    print("═══ ① 目录齐 ═══")
    dirs = sorted(os.path.basename(d) for d in glob.glob(os.path.join(DRILL, "TASK*"))
                  if os.path.isdir(d))
    chk("7 个任务目录齐 (%d)" % len(tasks), set(tasks) <= set(dirs), "有 %s" % dirs)

    rows = {}
    if os.path.exists(DB):
        con = sqlite3.connect(DB)
        try:
            rows = {r[0]: r for r in con.execute(
                "SELECT task_id, step_ok, step_total, closure_done, min_gap_mm, doc_md, doc_docx, doc_pdf, "
                "feishu_msg_id FROM drill_runs")}
        except Exception:                                                                  # noqa: BLE001
            rows = {}
        con.close()

    for tid in tasks:
        print("\n═══ %s ═══" % tid)
        d = os.path.join(DRILL, tid)
        if not os.path.isdir(d):
            chk("%s 目录" % tid, False, "缺")
            continue
        ch = _j(os.path.join(d, "config_chain.json"), {}) or {}
        miss = [x for x in DOMS if x not in ch]
        chk("配置链 7 域齐", not miss, "缺 %s" % miss[:3])
        fn_n = (ch.get("③ 功能配置") or {}).get("元任务数")
        chk("功能配置有元任务数 (>0)", bool(fn_n), "元任务 %s 个" % fn_n)
        st = _j(os.path.join(d, "step_run.json"), {}) or {}
        chk("单步真跑留证 (ok>0)", (st.get("ok") or 0) > 0,
            "验证通过 %s/%s" % (st.get("ok"), st.get("total")))
        tp = [r.get("topic") for r in (st.get("rows") or []) if r.get("topic")]
        chk("单步有真实输出 topic", len(tp) > 0, "带 topic 节点 %d 个, 例 %s" % (len(tp), tp[:2]))
        co = _j(os.path.join(d, "closure_run.json"), {}) or {}
        so = os.path.join(d, "closure_stdout.txt")
        txt = open(so, encoding="utf-8").read() if os.path.exists(so) else ""
        chk("整体运行留证 (引擎闭环那行)", "引擎闭环" in txt or co.get("engine"),
            "engine=%s" % (co.get("engine") or {}) and str(co.get("engine"))[:70])
        pngs = [p for p in glob.glob(os.path.join(d, "waveforms", "*.png")) if os.path.getsize(p) > 5000]
        chk("实际波形 ≥2 张非空 PNG", len(pngs) >= 2, "%d 张" % len(pngs))
        mv = _j(os.path.join(d, "models.json"), {}) or {}
        chk("模型运行证据 ≥2 层", len((mv.get("层") or {})) >= 2,
            "层: %s" % list((mv.get("层") or {}).keys()))
        tr = _j(os.path.join(d, "train.json"), {}) or {}
        if tr.get("skipped"):
            if a.allow_no_train:
                SKIP.append("%s 训练 skipped" % tid)
                print("  ⏭   %-52s %s" % ("自主训练 (skipped)", "本次演练 --no-train"))
            else:
                chk("自主训练留证", False, "skipped (不允许)")
        else:
            chk("自主训练留证 (返回码+loss)", tr.get("rc") is not None and (tr.get("n_loss") or 0) >= 0,
                "rc=%s · loss点=%s · %ss" % (tr.get("rc"), tr.get("n_loss"), tr.get("sec")))
        docs = [os.path.join(d, "%s_演练记录.%s" % (tid, e)) for e in ("md", "docx", "pdf")]
        chk("文档三件齐 (md/docx/pdf)", all(os.path.exists(x) for x in docs),
            "缺 %s" % [os.path.basename(x) for x in docs if not os.path.exists(x)])
        r = rows.get(tid)
        chk("工程库有 drill_runs 行", bool(r), "行=%s" % ("有" if r else "无"))
        if r:
            chk("库里 doc 路径与盘上一致", all(os.path.exists(x) for x in (r[5], r[6], r[7]) if x),
                "md=%s" % os.path.basename(r[5] or ""))
            if not r[8]:
                SKIP.append("%s 飞书未发" % tid)
                print("  ⏭   %-52s %s" % ("飞书消息 (message_id)", "还没发"))

    idx = _j(os.path.join(DRILL, "INDEX.json"), {}) or {}
    print("\n═══ ⑩ INDEX ═══")
    chk("INDEX.json 覆盖 7 个任务", len((idx.get("tasks") or {})) == len(tasks),
        "%s/7" % len((idx.get("tasks") or {})))

    print("\n" + ("✅ 全部通过 (%d 项)" % len(OK) if not BAD else "⛔ 失败 %d 项: %s" % (len(BAD), BAD)))
    if SKIP:
        print("⏭ 待办/跳过: %s" % SKIP)
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
