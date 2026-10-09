#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_console_consistency.py —— 控制台"全面一致性"体检 (2026-10-10 老倪要求)。

为什么需要: 侧边栏/首页/架构页里的数字 (功能 74 · 参数 162 · 节点 89 · 特征 18 …) 是**手写字符串**,
而真值在 data/database/zmax/zmax_engineering.db。改完数据没人改字符串 ⇒ 界面说谎。
本脚本: ① 从库里取真值 ② 从 GUI 源码里抓带数字的文案 ③ 逐条判一致性, 输出可修的清单。

用法: python3 tools/audit_console_consistency.py [--json]
"""
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
GUI_FILES = [os.path.join(ROOT, "tools", "gui", f) for f in
             ("studio.py", "model_tree.py", "param_center.py", "dataset_viewer.py",
              "status_panel.py", "simulink_module.py", "state_space_sim_real.py")]
SLIM = ["studio.py", "model_tree.py", "param_center.py", "dataset_viewer.py",
        "status_panel.py", "simulink_module.py", "state_space_sim_real.py"]


def truth():
    c = sqlite3.connect(DB)
    q = lambda s: c.execute(s).fetchone()[0]          # noqa: E731
    t = {
        "参数": q("select count(*) from params"),
        "参数可写": q("select count(*) from params where writable=1"),
        "功能": q("select count(*) from functions"),
        "画布节点": None,      # 下面从画布真源取 (89; DB 只存非背景带 74, 见 画布节点·DB非背景)
        "画布连线": q("select count(*) from canvas_links"),
        "画布节点·DB非背景": q("select count(*) from canvas_nodes"),
        "参数链接": q("select count(*) from param_links"),
    }
    try:
        cj = json.load(open(os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas",
                                         "state_space_obs.json"), encoding="utf-8"))
        t["画布节点"] = len(cj.get("nodes") or [])
        t["画布连线"] = len(cj.get("links") or [])
    except Exception as _e:                                                # noqa: BLE001
        t["画布节点"] = t["画布节点·DB非背景"]
    for sid in ("sys0", "sys1", "sys2", "plat"):
        try:
            t["功能·" + sid] = q("select count(*) from functions where sys_id='%s'" % sid)
        except Exception:                                                  # noqa: BLE001
            pass
    try:
        t["子系统"] = q("select count(*) from subsystems")
    except Exception:                                                      # noqa: BLE001
        pass
    return t


def scan_texts():
    """抓 GUI 源码里带数字的**文案** (中文标签里的数字), 报文件:行:文案。

    支持两种语序: 「功能 74」 与 「162 个可改数字」(数字在前, 现场最常这么写)。
    """
    pat = re.compile(r"[\"']([^\"'\n]{4,90})[\"']")
    num = re.compile(r"(功能|参数|节点|连线|数字|特征|条|项|个|模块|系统)\s*[:：]?\s*(\d{1,5})"
                     r"|(\d{1,5})\s*(个|条|项|路)?(可改)?(数字|功能|参数|节点|连线|特征)")
    hits = []
    for p in GUI_FILES:
        if not os.path.exists(p):
            continue
        for i, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
            s = line.strip()
            if (not s) or s.startswith("#"):
                continue
            if len(line) > 240:
                continue        # 版本变更历史 (长行叙述) 不是界面文案, 不参与一致性比对
            for m in pat.finditer(line):                      # 只查显示字符串
                for mm in num.finditer(m.group(1)):
                    if mm.group(2):                            # 语序①「功能 74」
                        hits.append({"file": os.path.basename(p), "line": i, "text": m.group(1)[:80],
                                     "ctx": line.strip()[:200], "kw": mm.group(1), "n": int(mm.group(2))})
                    elif mm.group(3):                          # 语序②「162 个可改数字」
                        hits.append({"file": os.path.basename(p), "line": i, "text": m.group(1)[:80],
                                     "ctx": line.strip()[:200], "kw": mm.group(6), "n": int(mm.group(3))})
    return hits


# 口径不同 ⇒ 不参与全局比对 (演示管道/全览/状态行 里的"节点"不是画布节点总数)
_OTHER_SCOPE = ("一键搭建", "一键加载", "全览", "审计中", "逐步搭建", "对比管道", "实验总结", "节点: 0",
                "发现ROS", "ROS2节点")


# 解释性文字 (docstring 里拿旧数字举例说明) 不是界面文案
_NARRATIVE = ("为什么", "以前", "之前", "旧值", "例如")


def _scoped_away(h):
    if any(k in h["text"] or k in h.get("ctx", "") for k in _NARRATIVE):
        return True
    if any(k in h["text"] or k in h.get("ctx", "") for k in _OTHER_SCOPE):
        return True
    # 「画布 L5 节点显示进度」里的 5 是层号, 不是节点数
    return bool(re.search(r"L[0-9]\s*节点|节点\s*L[0-9]", h["text"] + h.get("ctx", "")))


def _truth_key(h, t):
    """关键字→真值键; 按子系统计数的文案(卡面写 'L4/L5 … 功能 30')要跟**子系统**真值比, 不是全局 74。"""
    k = h["kw"]
    if k == "功能":
        ctx = (h.get("ctx") or "") + h["text"]          # 卡面副标题在单独字符串里 ⇒ 用整行做上下文
        if "L4/L5" in ctx or "System 2" in ctx or '"sys2"' in ctx:
            return "功能·sys2"
        if "L3" in ctx or "System 1" in ctx or '"sys1"' in ctx:
            return "功能·sys1"
        if "L2" in ctx or "System 0" in ctx or '"sys0"' in ctx:
            return "功能·sys0"
        return "功能"
    return {"参数": "参数", "节点": "画布节点", "连线": "画布连线", "数字": "参数",
            "特征": None, "条": None, "项": None, "个": None, "模块": None, "系统": None}.get(k)


def main():
    t = truth()
    hits = [h for h in scan_texts() if not _scoped_away(h)]
    bad = []
    for h in hits:
        k = _truth_key(h, t)
        if not k or k not in t:
            continue
        if h["n"] != t[k]:
            bad.append(h)
    out = {"truth": t, "num_texts": len(hits), "mismatch": bad}
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("══ 库里真值 ══")
    for k, v in t.items():
        print("  %-12s %s" % (k, v))
    print("\n══ 文案里带数字的 %d 处; 与真值**不符** %d 处 ══" % (len(hits), len(bad)))
    for h in bad:
        print("  %-18s:%-6d %s  → %s=%d (真值 %s)" % (h["file"], h["line"], h["text"][:50], h["kw"],
                                                     h["n"], t[_truth_key(h, t) or "参数"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
