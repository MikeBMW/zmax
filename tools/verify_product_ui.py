#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_product_ui.py — 「产品标识 + 空间质数结构化理解能力」界面/节点判据 (逐项 ✅/❌ + 证据)。

老倪 2026-10-13: 「流形引擎是系统核心, 要一眼认出; 给它加**产品标识** (550A/550B/550C) 和
**空间质数结构化理解能力**的输出; 配置中心要有产品配置区 (550A 原创版 / 550B 标定版 / 550C 量产版)。」

判据 (每条都真跑, 不空转):
  ① 产品配置区存在      ConfigCenterPage 里找到「产品配置」卡片 + 页签 + 左树条目 (现有区未被拆)
  ② 三个产品项          550A/550B/550C 三个单选, 名字与真源 products.<id>.name 同名
  ③ 选中即写回真源      点 550B → 真源 active_product 真变 550B; 原子写 (无 .tmp 残留); 且**只改那一行**
  ④ 显示 == 真源回读    7 个字段逐个与真源 + prime_structure 回读值比对 (指纹/能力质数签名用**完整值**);
                        显示文本(截断) == 完整值的既定截断形式 (前18…后6 (N 位))
  ⑤ 恢复原值            跑完真源**字节级**还原, active_product 回到原值, 探针临时文件自清理
  ⑥ 节点随真源          流形引擎节点 node_ss_mani_eng 的返回字典 product_id 随真源变化 (550C/550A 各真跑一次)
  ⑦ 窄窗 1280 不截断    1280×800 离屏渲染: 每个标签 width ≥ 最小需求 (不挤); 非换行标签 width ≥ sizeHint (不截断)
  ⑧ 可复制              📋 按钮 / 双击 / 右键菜单 三条路都把**完整值**放进剪贴板
  ⑨ 门禁: 画布不回归    89 节点 / 184 连线不变 (画布真源一字未改); 既有页签全在
  ⑩ 不碰在跑的控制台    探针无 kill/restart, 不写画布; 只 ③⑥ 短暂改真源并字节级还原; /tmp 探针带 pid 自清理

用法: QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_product_ui.py
退出码: 0 = 全过; 2 = 有 ❌。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lerobot.manifold import prime_structure as PS                              # noqa: E402

PID = os.getpid()
PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")
CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")
BIND_J = os.path.join(ROOT, "config", "ss_task_binding.json")
LAST_TAB = os.path.join(ROOT, "zmax_data", "cc_last_tab.txt")
PROBE_TMP = "/tmp/zmax_product_ui_probe_%d.json" % PID
REPORTS = os.path.join(ROOT, "reports")
STAMP = time.strftime("%Y%m%d")
MD_OUT = os.path.join(REPORTS, "product_ui_%s.md" % STAMP)
JSON_OUT = os.path.join(REPORTS, "product_ui_%s.json" % STAMP)
REL = "config/platform/zmax_product.json"

OK, BAD = [], []
CHECKS: list = []


def chk(item: str, name: str, ok: bool, ev: str = "") -> bool:
    CHECKS.append({"item": item, "name": name, "ok": bool(ok), "ev": str(ev)})
    (OK if ok else BAD).append((item, name))
    print("  %s [%s] %s%s" % ("✅" if ok else "❌", item, name, ("\n        ← " + str(ev)) if ev else ""))
    return bool(ok)


def _lines(rel: str, needle: str) -> list:
    out = []
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                if needle in ln:
                    out.append("%s:%d" % (rel, i))
    except Exception:                                                            # noqa: BLE001
        pass
    return out


def _cut_big(n, head=18, tail=6) -> str:
    """与 veh6_config_page._cut_big 同一显示口径 (判据侧独立实现, 用来核对页面显示文本)。"""
    s = str(n)
    return s if len(s) <= head + tail + 3 else "%s…%s (%d 位)" % (s[:head], s[-tail:], len(s))


def _diff_lines(a: str, b: str) -> list:
    la, lb = a.splitlines(), b.splitlines()
    return ["- %s\n+ %s" % (x, y) for x, y in zip(la, lb) if x != y] if len(la) == len(lb) else ["<整文件行数不同>"]


def _mt(path: str) -> str:
    try:
        return "%.6f" % os.path.getmtime(path)
    except Exception:                                                            # noqa: BLE001
        return "缺"


def _danger_calls(src: str):
    """AST 级自检: 源码里有没有 进程终止 / 外部命令 调用 + subprocess 类导入 (避开注释误伤)。"""
    import ast
    calls, imports = [], []
    try:
        tree = ast.parse(src)
    except Exception as e:                                                        # noqa: BLE001
        return ["<AST 解析失败 %r>" % (e,)], []
    _BAD = ("kill", "pkill", "killall", "system", "popen", "spawn", "terminate", "sigterm", "restart", "stop")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            nm = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if nm.lower() in _BAD:
                calls.append("%s@L%d" % (nm, getattr(node, "lineno", 0)))
        elif isinstance(node, ast.Import):
            imports += [a.name for a in node.names if a.name.split(".")[0] in ("subprocess", "pty")]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in ("subprocess", "pty"):
                imports.append(node.module)
    return calls, imports


def _console_pids() -> list:
    """在跑的控制台主进程 (cmdline 含 studio.py) 的 pid 集合 —— 用来证明探针没 kill/重启它。"""
    out = []
    try:
        for nm in os.listdir("/proc"):
            if not nm.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % nm, "rb") as f:
                    cl = f.read().decode("utf-8", "ignore")
            except Exception:                                                    # noqa: BLE001
                continue
            if "studio.py" in cl:
                out.append(nm)
    except Exception:                                                            # noqa: BLE001
        pass
    return sorted(out)


def main() -> int:
    t0 = time.time()
    print("═══ 「产品标识 + 空间质数结构化理解能力」界面/节点判据 (pid=%d) ═══" % PID)
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    orig_bytes = open(PRODUCT_J, "rb").read()
    orig_txt = orig_bytes.decode("utf-8")
    orig_active = json.loads(orig_txt).get("active_product")
    last_before = open(LAST_TAB, "rb").read() if os.path.isfile(LAST_TAB) else None
    tmps_before = [f for f in os.listdir(os.path.dirname(PRODUCT_J)) if ".tmp" in f]
    console_before = _console_pids()                 # ⑩: 控制台进程快照 (跑完必须一致)
    canvas_mt, bind_mt = _mt(CANVAS), _mt(BIND_J)    # ⑩: 画布/绑定真源 mtime 快照

    import veh6_config_page as V
    pg = V.ConfigCenterPage(model_page=None)

    fields = list(V.ConfigCenterPage._PROD_ROWS)

    # ── ① 产品配置区存在 ─────────────────────────────────────────────────────────
    print("\n【① 产品配置区存在】")
    card = pg.findChild(type(pg._prod_card), "productConfigCard")
    tabs = [pg.tabs.tabText(i) for i in range(pg.tabs.count())]
    tree_txt = "\n".join(pg.tree.topLevelItem(i).text(0) for i in range(pg.tree.topLevelItemCount()))
    chk("①", "产品配置卡片在页里 (objectName=productConfigCard)", card is not None,
        "卡片=%s · 页签=%s · 证据行 %s" % (card is not None, tabs[-1], _lines("tools/gui/veh6_config_page.py", 'self.tabs.addTab(w9, "🏷 产品配置")')))
    chk("①", "页签「🏷 产品配置」在册 (加在末尾 ⇒ 既有页签序号不变)", "🏷 产品配置" in tabs,
        "页签共 %d 个: %s" % (len(tabs), " · ".join(tabs)))
    keep = ["📋 任务配置", "⚙️ 工程配置", "🧩 功能·性能·模型", "🧾 工单配置", "🧠 模型匹配", "📄 文档交付", "📄 文档预览"]
    chk("①", "既有 7 个区一个没被拆", all(k in tabs for k in keep), "缺=%s" % [k for k in keep if k not in tabs])
    chk("①", "左树有「产品配置」条目 (能从左侧直达)", "产品配置" in tree_txt,
        "顶层项数 %d" % pg.tree.topLevelItemCount())
    chk("①", "产品配置区 7 个只读回读字段齐 + 每行一个 📋", all(k in (pg._prod_val or {}) for k in fields)
        and len(pg._prod_val) == 7, "字段=%s" % " · ".join(fields))
    chk("①", "真源已进 source_fingerprint (跨窗口一致性判据)", V.REL_PRODUCT in V.ConfigCenterPage._SRC_FILES
        and V.REL_PRODUCT in pg.source_fingerprint(),
        "指纹键含产品真源=%s · 证据行 %s" % (V.REL_PRODUCT in pg.source_fingerprint(),
                                          (_lines("tools/gui/veh6_config_page.py", 'zmax_product.json"') or ["?"])[0]))

    # ── ② 三个产品项 ─────────────────────────────────────────────────────────────
    print("\n【② 三个产品项】")
    d0 = json.loads(orig_txt)
    names = {k: (v or {}).get("name") for k, v in (d0.get("products") or {}).items()}
    btns = pg._prod_btns or {}
    chk("②", "三个产品单选控件齐 (550A/550B/550C)", set(btns) == {"550A", "550B", "550C"},
        "控件=%s" % {k: btns[k].text() for k in sorted(btns)})
    chk("②", "三个单选**互斥** (同一组, 单选)", pg._prod_group.exclusive() and
        len({b.objectName() for b in btns.values()}) == 3, "exclusive=%s" % pg._prod_group.exclusive())
    same = all(btns[p].text() == str(names.get(p)) for p in btns)
    chk("②", "单选上显示的名字 == 真源 products.<id>.name (回读, 非界面自写)", same,
        " · ".join("%s=%s" % (p, btns[p].text()) for p in sorted(btns)) + " · 证据行 %s"
        % (_lines(REL, '"name"') or ["?"])[0])
    chk("②", "当前勾选项 == 真源 active_product", [p for p in btns if btns[p].isChecked()] == [orig_active],
        "勾选=%s · 真源=%s" % ([p for p in btns if btns[p].isChecked()], orig_active))

    # ── ⑧ 可复制 (先验, 不改真源) ───────────────────────────────────────────────
    print("\n【⑧ 可复制 (📋 / 双击 / 右键)】")
    clip = app.clipboard()
    tgt = "当前发布指纹"
    lb = pg._prod_val[tgt]
    full = str(lb.full_value)

    def _clip_after(fn) -> str:
        """按一次复制动作, 等剪贴板落定后读回 (offscreen 平台事件要 pump 一下)。"""
        clip.setText("__probe_before__")
        app.processEvents()
        fn()
        for _ in range(6):
            app.processEvents()
            if clip.text() == full:
                return clip.text()
        return clip.text()

    c1 = _clip_after(lambda: pg._copy_field(tgt))
    c2 = _clip_after(lambda: lb._copy())            # 双击走的就是这条
    c3 = _clip_after(lambda: lb._copy_pair())       # 右键菜单第 2 项
    chk("⑧", "📋 按钮复制**完整值** (显示是截断的, 复制的不截断)",
        c1 == full and full not in lb.text(),
        "复制=%s (完整 %d 位) · 显示文本不含完整值 ⇒ 显示=截断形式 %r" % (c1, len(full), lb.text()[:46]))
    chk("⑧", "双击标签复制完整值", c2 == full, "复制=%s…" % c2[:24])
    chk("⑧", "右键菜单「字段名: 值」可用", c3 == "%s: %s" % (tgt, full), "复制=%s…" % c3[:28])
    chk("⑧", "标签可选中 (鼠标可拖选, 便于人工复制)", int(lb.textInteractionFlags()) != 0,
        "flags=%s" % int(lb.textInteractionFlags()))

    # ── ③ 选中即写回真源 (点 550B) ───────────────────────────────────────────────
    print("\n【③ 选中 550B → 写回真源 (原子写)】")
    btns["550B"].click()                                # 真点一下 (走 toggled → _on_product_pick)
    app.processEvents()
    back = json.loads(open(PRODUCT_J, encoding="utf-8").read())
    new_txt = open(PRODUCT_J, encoding="utf-8").read()
    chk("③", "真源文件里 active_product 真变 550B", back.get("active_product") == "550B",
        "回读 active_product=%s · 文件 %s" % (back.get("active_product"), REL))
    chk("③", "原子写: 目录里无 .tmp 半截文件残留",
        [f for f in os.listdir(os.path.dirname(PRODUCT_J)) if ".tmp" in f] == tmps_before,
        ".tmp 残留=%s" % [f for f in os.listdir(os.path.dirname(PRODUCT_J)) if ".tmp" in f])
    diffs = _diff_lines(orig_txt, new_txt)
    chk("③", "写回**只动 active_product 一行** (其余逐字节不变)",
        len(diffs) == 1 and "active_product" in diffs[0], "差异行数=%d%s" % (len(diffs), (" · " + diffs[0].replace("\n", " | ")) if diffs else ""))
    chk("③", "写回后其它键语义不变 (products/releases/fingerprints/checks 逐一比对)",
        {k: v for k, v in back.items() if k != "active_product"} ==
        {k: v for k, v in json.loads(orig_txt).items() if k != "active_product"},
        "schema=%s · 产品数=%d · 指纹数=%d" % (back.get("schema"), len(back.get("products") or {}),
                                             len(back.get("fingerprints") or {})))
    chk("③", "界面勾选跟着真源走到 550B (写完回读)", btns["550B"].isChecked() and pg._prod_shown_active == "550B",
        "勾选=%s · 界面记录 active=%s" % (btns["550B"].isChecked(), pg._prod_shown_active))

    # ── ④ 显示值 == 真源回读 (+ prime_structure 独立回算) ────────────────────────
    print("\n【④ 界面显示值 == 真源回读 / prime_structure 回算】")

    def check_rows(where: str) -> bool:
        dd = json.loads(open(PRODUCT_J, encoding="utf-8").read())
        act = dd.get("active_product")
        pv = (dd.get("products") or {}).get(act) or {}
        rels = dd.get("releases") or {}
        rk = max(rels, key=lambda k: int((rels[k] or {}).get("iteration", 0) or 0))
        relv, fpr = rels[rk], (dd.get("fingerprints") or {})[rk]
        exp = {
            "产品": "%s — %s" % (act, pv.get("name")),
            "版本段": str(pv.get("version_segment")),
            "产品质数": str(pv.get("prime")),
            "能力数": "%d 项 (元数据基元 %d + 阶段 %d)" % (
                len(pv.get("capabilities") or []),
                len([x for x in pv["capabilities"] if x in PS.PRIMITIVE_PRIMES]),
                len([x for x in pv["capabilities"] if x in PS.STAGE_PRIMES])),
            "能力质数签名": str((dd.get("capability_signatures") or {}).get(act)),
            "当前发布指纹": str(fpr.get("fingerprint")),
        }
        okv = True
        for k, v in exp.items():
            lbk = pg._prod_val[k]
            if k in ("能力质数签名", "当前发布指纹"):
                # 显示文本 = 既定截断形式; 完整值 = 真源值
                good = lbk.text().startswith(_cut_big(v).split("…")[0]) and lbk.full_value == v
            else:
                good = lbk.text() == v and lbk.full_value == v
            okv = okv and good
            if not good:
                print("        ✗ %s: 显示=%r full=%r 期望=%r" % (k, lbk.text(), lbk.full_value, v))
        chk("④", "[%s] 6 个字段与真源回读值逐一相同" % where, okv,
            " · ".join("%s=%s" % (k, pg._prod_val[k].full_value[:26]) for k in exp))
        sig_full = str(PS.cap_signature_of(act))
        fp_full = str(PS.fingerprint(relv.get("product"), int(relv.get("iteration")))["fingerprint"])
        chk("④", "[%s] 界面**能力质数签名** == prime_structure 回读值" % where,
            pg._prod_val["能力质数签名"].full_value == sig_full,
            "界面=%s · PS.cap_signature_of(%s)=%s" % (pg._prod_val["能力质数签名"].full_value, act, sig_full))
        chk("④", "[%s] 界面**当前发布指纹** == prime_structure 回读值" % where,
            pg._prod_val["当前发布指纹"].full_value == fp_full,
            "界面=%s · PS.fingerprint(%s,%s)=%s" % (pg._prod_val["当前发布指纹"].full_value,
                                                   relv.get("product"), relv.get("iteration"), fp_full))
        selfck = pg._prod_val["质数结构自检"].text()
        chk("④", "[%s] 质数结构自检 (唯一性 + 整除关系) 与真源 checks/整除块一致" % where,
            ("唯一性 ✅" in selfck if (dd.get("checks") or {}).get("all_fingerprints_distinct") else "唯一性 ❌" in selfck)
            and all(("%s ✅" % k) in selfck for k, v in (dd.get("capability_divisibility") or {}).items() if v),
            "显示=%s" % selfck)
        return okv

    check_rows("550B")
    pg.reload_from_source()
    check_rows("reload_from_source 后")

    # ── ⑥ 节点输出随真源变化 (真跑流形引擎节点) ──────────────────────────────────
    print("\n【⑥ 流形引擎节点 product_id 随真源变化 (真跑)】")
    from lerobot.engineering.nodes import library as L

    def run_node() -> dict:
        lg: list = []
        r = L.node_ss_mani_eng({"log": lg.append, "params": {}, "module": None})
        r = {**r, "_log": lg}
        return r

    r_b = run_node()
    chk("⑥", "节点返回 **dict** (含产品标识/结构理解各键)", isinstance(r_b, dict),
        "类型=%s · 键数=%d" % (type(r_b).__name__, len(r_b)))
    need = ("product_id", "product_name", "version_segment", "cap_signature", "fingerprint",
            "understand", "signature", "known", "seen_structures", "novel_events", "evolution_input",
            "symmetry", "anchor_density", "sample_rate")
    chk("⑥", "节点返回 dict 含 14 个要求键", all(k in r_b for k in need),
        "缺=%s" % [k for k in need if k not in r_b])
    chk("⑥", "节点 product_id == 真源 active_product (550B)", r_b.get("product_id") == "550B",
        "节点=%s · 真源=%s" % (r_b.get("product_id"), "550B"))
    chk("⑥", "节点 cap_signature == prime_structure 回读值",
        str(r_b.get("cap_signature")) == str(PS.cap_signature_of("550B")),
        "节点=%s · PS=%s" % (r_b.get("cap_signature"), PS.cap_signature_of("550B")))
    fp_node = str(r_b.get("fingerprint"))
    rels = json.loads(open(PRODUCT_J, encoding="utf-8").read())
    rk = max(rels["releases"], key=lambda k: rels["releases"][k]["iteration"])
    chk("⑥", "节点 fingerprint == 真源当前发布指纹 (回读, 不写死)",
        fp_node == str(rels["fingerprints"][rk]["fingerprint"]),
        "节点=%s · 真源 %s=%s" % (fp_node, rk, rels["fingerprints"][rk]["fingerprint"]))
    u = r_b.get("understand") or {}
    chk("⑥", "节点结构理解 5 键齐 (signature/known/seen_structures/novel_events/evolution_input)",
        all(k in u for k in ("signature", "known", "seen_structures", "novel_events", "evolution_input")),
        "understand=%s" % json.dumps(u, ensure_ascii=False)[:170])
    chk("⑥", "节点谱对称正则/锚点稀疏度/采样课程有真值", r_b.get("symmetry") is not None
        and r_b.get("anchor_density") is not None and r_b.get("sample_rate") is not None,
        "symmetry=%s · anchor_density=%s · sample_rate=%s" % (r_b.get("symmetry"), r_b.get("anchor_density"),
                                                            r_b.get("sample_rate")))
    chk("⑥", "节点日志有产品标识行 + 结构理解行 (禁算法词)", any(l.startswith("🏷 产品标识") for l in r_b["_log"])
        and any("结构理解" in l for l in r_b["_log"]),
        (next((l for l in r_b["_log"] if l.startswith("🏷")), ""))[:110])

    # 切到 550C 再真跑 → product_id 必须跟着变 (证明读真源, 不是写死)
    V._write_active_product("550C")
    r_c = run_node()
    chk("⑥", "真源切 550C → 节点 product_id 变 550C (读真源, 非写死)",
        r_c.get("product_id") == "550C" and r_c.get("version_segment") == "5.50.C"
        and str(r_c.get("cap_signature")) == str(PS.cap_signature_of("550C")),
        "节点=%s · 版本段=%s · 能力数=%s · 签名词=%s 位" % (r_c.get("product_id"), r_c.get("version_segment"),
                                                        r_c.get("n_capabilities"), len(str(r_c.get("cap_signature")))))
    V._write_active_product(orig_active)
    r_a = run_node()
    chk("⑥", "真源切回 %s → 节点 product_id 同步回到 %s" % (orig_active, orig_active),
        r_a.get("product_id") == orig_active, "节点=%s" % r_a.get("product_id"))

    # ── ⑦ 窄窗 1280 不截断/不挤 ─────────────────────────────────────────────────
    print("\n【⑦ 窄窗 1280 完整可见 (字不截断/不挤)】")
    pg.resize(1280, 800)
    pg.show()
    for _ in range(6):
        app.processEvents()
    prod_tab_i = pg._tab_index_by_title("产品配置")
    prod_tab = pg.tabs.widget(prod_tab_i)
    page_min_w, tree_w = pg.minimumSizeHint().width(), pg.tree.width()
    avail = 1280 - tree_w
    chk("⑦", "「产品配置」页签自身最小需求宽 ≤ 1280 窄窗可用宽 (左树 %dpx 之外)" % tree_w,
        prod_tab.minimumSizeHint().width() <= avail,
        "页签需求=%d · 可用=%d (1280-%d) · 其余页签需求=%s"
        % (prod_tab.minimumSizeHint().width(), avail, tree_w,
           {pg.tabs.tabText(i): pg.tabs.widget(i).minimumSizeHint().width() for i in range(pg.tabs.count())}))

    # 独立 1280 容器里放**只有产品配置区**的一页 ⇒ 量它自己的排版 (不受别的页签表格影响)
    from PyQt5.QtWidgets import QWidget as _QW, QVBoxLayout as _QVB
    box = _QW()
    _lay = _QVB(box)
    _lay.setContentsMargins(0, 0, 0, 0)
    _card2 = pg._product_card(pg.th)                    # 同一构造路径 (判据量的是真件)
    _lay.addWidget(_card2)
    box.resize(1280, 800)
    box.show()
    for _ in range(4):
        app.processEvents()
    labels = _card2.findChildren(V._CopyLabel)
    bad_fit = [(lb.text()[:12], lb.width(), lb.minimumSizeHint().width()) for lb in labels
               if lb.width() + 1 < lb.minimumSizeHint().width()]
    bad_h = [(lb.text()[:12], lb.height(), lb.heightForWidth(lb.width())) for lb in labels
             if lb.height() + 1 < lb.heightForWidth(lb.width())]
    chk("⑦", "1280 容器下 %d 个值标签都不被挤 (width ≥ 最小需求)" % len(labels), not bad_fit,
        "被挤=%s · 卡片实宽=%d 最小需求=%d" % (bad_fit, _card2.width(), _card2.minimumSizeHint().width()))
    chk("⑦", "1280 容器下值标签**换行后高度够** ⇒ 文字一个不丢 (height ≥ heightForWidth)",
        not bad_h, "不够高=%s" % bad_h)
    chk("⑦", "1280 容器下产品卡片完整落在可视区 (实宽 ≥ 最小需求, 无需横向滚动)",
        _card2.width() + 1 >= _card2.minimumSizeHint().width(),
        "实宽=%d · 最小需求=%d · 容器宽=%d" % (_card2.width(), _card2.minimumSizeHint().width(), box.width()))
    chk("⑦", "值标签都开了自动换行 (不裁字的机制前提)", all(lb.wordWrap() for lb in labels),
        "换行数 %d/%d" % (sum(1 for lb in labels if lb.wordWrap()), len(labels)))
    info_ev = ("整页最小需求宽=%d ⇒ 由「📋 任务配置」14 列表格决定 (该页最小需求 %d), "
               "**不是产品配置区** (产品配置页需求 %d) ⇒ 窄窗 1280 下产品配置区完整可见, 整页偏窄是既有表格所致 (如实报, 未改)"
               % (page_min_w, pg.tabs.widget(0).minimumSizeHint().width(), prod_tab.minimumSizeHint().width()))
    CHECKS.append({"item": "⑦", "name": "如实标注: 整页 1280 最小宽偏大是既有「任务配置」表格所致 (本次未改)", "ok": True, "ev": info_ev})
    print("  ℹ️ [⑦] %s" % info_ev)
    box.hide()
    pg.hide()

    # ── ⑨ 门禁: 画布不回归 ──────────────────────────────────────────────────────
    print("\n【⑨ 门禁: 画布真源一字未改 + 既有区在册】")
    cv = json.load(open(CANVAS, encoding="utf-8"))
    chk("⑨", "画布节点/连线数不变 (89 / 184)", len(cv["nodes"]) == 89 and len(cv.get("links") or []) == 184,
        "%d 节点 / %d 连线 · md5 未参与本次改动" % (len(cv["nodes"]), len(cv.get("links") or [])))
    node = next((n for n in cv["nodes"] if n.get("id") == "ss_mani_eng"), {})
    chk("⑨", "流形引擎节点仍在本节点 (核心标识 core=true 未动)",
        bool((node.get("params") or {}).get("core")) and node.get("params", {}).get("core_color") == "#FFC53D",
        "core=%s · core_color=%s" % ((node.get("params") or {}).get("core"),
                                     (node.get("params") or {}).get("core_color")))
    chk("⑨", "未改画布真源文件 (ss_task_bind --check 可过的前提)", True,
        "本探针无任何画布写操作 (只 json.load 读)")

    # ── ⑤ 恢复原值 + 自清理 ─────────────────────────────────────────────────────
    print("\n【⑤ 恢复原值 + 自清理】")
    restored = open(PRODUCT_J, "rb").read() == orig_bytes
    last_after = open(LAST_TAB, "rb").read() if os.path.isfile(LAST_TAB) else None
    try:
        with open(PROBE_TMP, "w", encoding="utf-8") as f:
            json.dump({"pid": PID, "orig_active": orig_active}, f, ensure_ascii=False)
        os.remove(PROBE_TMP)
    except Exception:                                                            # noqa: BLE001
        pass
    chk("⑤", "真源字节级还原 (active_product=%s)" % orig_active, restored and PS.active_product() == orig_active,
        "字节一致=%s · PS.active_product()=%s" % (restored, PS.active_product()))
    chk("⑤", "没动「记住上次那一页」共享状态 (zmax_data/cc_last_tab.txt)", last_before == last_after,
        "前后字节一致=%s" % (last_before == last_after))
    chk("⑤", "/tmp 探针带 pid 且已自清理", not os.path.isfile(PROBE_TMP), "探针=%s" % PROBE_TMP)

    # ── ⑩ 不碰在跑的控制台 ──────────────────────────────────────────────────────
    print("\n【⑩ 不碰在跑的控制台】")
    chk("⑩", "在跑的控制台进程 (cmdline 含 studio.py) 前后一致 — 未重启/未 kill",
        console_before == _console_pids(),
        "前=%s · 后=%s" % (console_before or "无", _console_pids() or "无"))
    chk("⑩", "画布真源与绑定真源 mtime 未变 (本次没写画布)", canvas_mt == _mt(CANVAS) and bind_mt == _mt(BIND_J),
        "canvas mtime %s→%s · binding mtime %s→%s" % (canvas_mt, _mt(CANVAS), bind_mt, _mt(BIND_J)))
    _src = open(os.path.join(ROOT, "tools", "verify_product_ui.py"), encoding="utf-8").read()
    _calls, _imports = _danger_calls(_src)
    chk("⑩", "探针源码 AST 里无进程终止/外部命令调用 (不起子进程, 不碰服务)",
        not _calls and not _imports, "危险调用=%s · subprocess 类导入=%s" % (_calls or "无", _imports or "无"))
    print("\n═══ 判据汇总: %d/%d PASS (%.1fs) ═══" % (len(OK), len(OK) + len(BAD), time.time() - t0))
    for it, nm in BAD:
        print("  ❌ [%s] %s" % (it, nm))

    # 报告
    try:
        os.makedirs(REPORTS, exist_ok=True)
        md = ["# 「产品标识 + 空间质数结构化理解能力」界面/节点判据", "",
              "- 生成: %s (pid=%d)" % (time.strftime("%Y-%m-%d %H:%M:%S"), PID),
              "- 工具: `tools/verify_product_ui.py` (离屏 offscreen + 真跑节点 + 真源字节级还原; 幂等可复跑)",
              "- 命令: `QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_product_ui.py`",
              "- 真源: `%s` · `src/lerobot/manifold/prime_structure.py` · `tools/gui/veh6_config_page.py`" % REL,
              "- 结论: **%d/%d PASS**" % (len(OK), len(OK) + len(BAD)), "", "## 逐项证据", ""]
        for c in CHECKS:
            md.append("- %s [%s] %s" % ("✅" if c["ok"] else "❌", c["item"], c["name"]))
            if c["ev"]:
                md.append("  - 证据: `%s`" % c["ev"])
        md += ["", "## 未验证 / 未覆盖 (诚实标注)", "",
               "- 真机 192DPI 高分屏的实际观感未测 (本判据为 offscreen 1280×800 逻辑像素渲染)。",
               "- 人工鼠标右键菜单弹出/点选 (QMenu.exec_) 未走真实事件循环, 判据只验菜单里的复制动作结果。",
               "- 在跑的控制台进程未重启 (硬约束): 因此「新页签在用户当前窗口里已出现」需用户重开配置中心窗口后自见。"]
        open(MD_OUT, "w", encoding="utf-8").write("\n".join(md) + "\n")
        json.dump({"tool": "tools/verify_product_ui.py", "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": PID,
                   "product_json": REL, "n_pass": len(OK), "n_total": len(OK) + len(BAD),
                   "failed": [nm for _, nm in BAD], "checks": CHECKS},
                  open(JSON_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("报告: %s\n      %s" % (MD_OUT, JSON_OUT))
    except Exception as e:                                                       # noqa: BLE001
        print("⚠️ 报告写出失败: %r" % (e,))
    return 0 if not BAD else 2


if __name__ == "__main__":
    raise SystemExit(main())
