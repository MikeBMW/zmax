#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_sor_multi.py — **第二份 SOR** (插拔/插接类): TASK-01-FW + TASK-05-ATS 光纤插拔

老倪 2026-10-13: 「你来出第二份 SOR，先有配置单，任务是 TASK-01-FW 和 TASK-05-ATS 光纤插拔，
给出配置单和 供应商 SOR」。

口径:
  · **配置单先行**: 本 SOR 的全部任务参数取自 `outputs/config_sheets/配置单_<task>_latest.json`
    (画布/参数注册表/标定真源/点位台账), SOR 里逐份登记 sha256 + 画布 md5, 可回读核对。
  · **一份 SOR 覆盖两个插接类任务**: 任务级章节 (项目与场景 / 性能指标 / 作业要求(工艺技能) / 验收) 逐任务展开,
    平台级章节 (采购范围与分工 / 功能清单与接口 / 数据平台 / 交付物 / 待填项) 共用 —— 复用第一份 SOR 的生成器,
    文案与判据口径完全一致 (不另立标准)。
  · 硬指标仍写明 **成功率 ≥99% · 节拍 ≤3.5s**; 任务真源未定义节拍的一律如实写「真源未定义」。

用法: gui-venv311/bin/python tools/delivery/gen_sor_multi.py --tasks TASK-01-FW,TASK-05-ATS --ver 5.50.C
产物: docs/deliverables/SOR_供应商要求_插拔类_TASK-01-FW_TASK-05-ATS_<ver>.md + .docx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "delivery"))
from gen_contract_pack import blocks_sor, render_md, render_docx  # noqa: E402

DLV = os.path.join(ROOT, "docs", "deliverables")
SHEET = os.path.join(ROOT, "outputs", "config_sheets")


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return d


def _sha16(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return "?"


def _slice(blocks, head_prefix):
    """取 blocks 里某个 h2 段 (到下一个 h2 为止)。"""
    out, on = [], False
    for k, v in blocks:
        if k == "h2":
            on = str(v).startswith(head_prefix)
            if on:
                out.append((k, v))
            continue
        if on:
            out.append((k, v))
    return out


def _sheet(task):
    return os.path.join(SHEET, "配置单_%s_latest.json" % task)


def build(tasks, ver):
    B = []
    A = B.append
    A(("h1", "供应商要求 SOR · 第二份 (插拔/插接类: 光纤插拔 · FW 校验) · %s" % ver))
    A(("p", "文件编号: SOR-MULTI-%s-%s　版本: %s (开发版 5.50.6)　生成: %s"
              % ("-".join(t.split("-")[1] for t in tasks), ver.replace(".", ""), ver,
                 time.strftime("%Y-%m-%d"))))
    A(("p", "**明确目标 (硬指标)**: 插接类任务连续动作成功率 **≥99%** · 单件节拍 **≤3.5s** "
            "(任务目标 ≤3.15s, 3.5s 为硬上限)。未达即不予验收。"))
    A(("p", "覆盖任务 (%d): %s —— 均为「取件→对位→插入→校验/测试→拔出/回位」型作业, "
            "共用同一状态空间工程与数据空间, 差异只在任务配置 (配方/参数覆盖/档位)。"
            % (len(tasks), " · ".join("`%s`" % t for t in tasks))))
    # ── §0 配置单 (先行) ──
    A(("h2", "0. 配置单 (本 SOR 的配置真源, 先行生成 √)"))
    A(("p", "本 SOR 的每条任务要求都来自对应配置单; 配置单由 `tools/config_sheet.py --task <任务>` 从**在役真源**扫描生成 "
            "(画布 / 参数注册表 / 标定真源 / 点位台账), 可回读复现。"))
    rows = []
    for t in tasks:
        p = _sheet(t)
        d = _j(p, {}) or {}
        st = d.get("任务") or {}
        cv = d.get("画布") or {}
        reg = d.get("参数注册表") or {}
        md5 = os.path.join(SHEET, "配置单_%s_latest.md" % t)
        rows.append(["%s" % t, st.get("name"), st.get("recipe_type"), st.get("ss_mode"),
                     "`%s`" % os.path.basename(md5),
                     "%d 项" % (reg.get("总数") or 0),
                     "md5 `%s` · %s 节点/%s 连线 · 启用 %s" % (cv.get("md5"), cv.get("节点"), cv.get("连线"),
                                                             cv.get("启用节点数")),
                     "`%s`" % _sha16(md5)])
    A(("table", (["任务", "名称", "配方", "模式", "配置单文件", "参数注册表", "画布", "sha256(16)"], rows)))
    A(("p", "标定真源: " + "; ".join(
        "%s sha `%s`" % (x.get("file"), x.get("sha256_16"))
        for x in ((_j(_sheet(tasks[0]), {}) or {}).get("标定真源") or [])) +
        " · 点位台账: " + "; ".join(
        "%s %s 条 sha `%s`" % (x.get("label"), x.get("count"), x.get("sha256_16"))
        for x in ((_j(_sheet(tasks[0]), {}) or {}).get("点位台账") or []))))
    # ── 任务级章节 (逐任务展开) ──
    per = {t: blocks_sor(t, ver) for t in tasks}
    for tag in ("1. 项目与场景", "3. 性能指标要求", "4. 场景作业要求", "7. 验收要求"):
        A(("h2", tag))
        for t in tasks:
            A(("h2", "【%s】" % t))
            for k, v in _slice(per[t], tag):
                if k == "h2":
                    continue
                A((k, v))
        if tag.startswith("3."):
            A(("p", "**口径注 (逐项来源)**: 表中「硬指标 成功率 / 节拍」行是**项目级明确要求**"
                    "(成功率 ≥99% · 节拍 ≤3.5s · 目标 3.15s, 用户 2026-10-13 明确), 对每个任务生效; "
                    "其余行为任务真源 (`config/tasks/tasks.json` + 任务配置的 targets/参数覆盖) 或插接类模板继承项。"
                    "任务真源未定义的项 (如 ATS 的 `ins.depth` 为空) 一律记「待现场标定/采购附件确认」, **不代填数值**。"))
    # ── 平台级章节 (共用, 取第一个任务的口径) ──
    for tag in ("2. 采购范围与交付分工", "5. 功能清单与接口要求", "6. 数据平台与接口",
                "8. 交付物与文档", "9. 待商务/待现场项"):
        A(("h2", tag))
        for k, v in _slice(per[tasks[0]], tag):
            if k == "h2":
                continue
            A((k, v))
    # ── 本份 SOR 的补充: 两任务的差异对照 ──
    A(("h2", "10. 两任务差异对照 (同工程不同配置 —— 迁移不变量)"))
    sts = [(_j(_sheet(t), {}) or {}).get("任务") or {} for t in tasks]
    keys = ["recipe_type", "ss_mode", "trigger", "loop", "orders_rule", "targets", "参数覆盖", "档位", "适用段"]
    rows = []
    for k in keys:
        rows.append([k] + [json.dumps(s.get(k), ensure_ascii=False)[:220] for s in sts])
    A(("table", (["配置项"] + list(tasks), rows)))
    A(("p", "**迁移不变量 (同工程下换任务只改配置)**: ①画布与连线不变 (同一 `state_space_obs.json`); "
            "②数据空间话题与 QoS 不变; ③安全链为站点级不可覆盖; ④末端工具/工装按任务更换但接口契约不变; "
            "⑤标定真源 (`T_base_cam`/`plane_z`/`cell_geometry.points`) 未标定前, 一切坐标类要求记「待实测」。"))
    return B


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="TASK-01-FW,TASK-05-ATS")
    ap.add_argument("--ver", default="5.50.C")
    a = ap.parse_args()
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
    B = build(tasks, a.ver)
    base = os.path.join(DLV, "SOR_供应商要求_插拔类_%s_%s" % ("_".join(tasks), a.ver))
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(render_md(B))
    render_docx(B, base + ".docx")
    print("→ %s.md (%d B) + .docx (%d B)" % (base, os.path.getsize(base + ".md"), os.path.getsize(base + ".docx")))


if __name__ == "__main__":
    main()
