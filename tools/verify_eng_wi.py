#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 工程配置 (A/B/C 三档) + 操作手册 (WI) 是否「真能工程实现」。

判三件事:
  1) 唯一依据完整: 三档各有 硬件/软件/标定/安全/WI, 每条 WI 都有 命令+期望+失败处理
  2) 命令真跑: need=local 的每一步**现场执行**, 输出必须匹配 expect (不是嘴上说能跑)
  3) 界面真出: 工程配置页有 A/B/C 切换、四张表、每步「▶ 跑」按钮, 点了状态真的变 ✅
  4) 文档同源: docs/deliverables/工程操作手册_三档_A_B_C.md 的步骤与唯一依据一致

跑法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_eng_wi.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SPEC = os.path.join(ROOT, "tools", "spec", "eng_profiles.json")
DOC = os.path.join(ROOT, "docs", "deliverables", "工程操作手册_三档_A_B_C.md")

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + str(detail)) if detail else ""))


def main():
    spec = json.load(open(SPEC, encoding="utf-8"))
    profs = spec.get("profiles") or []
    chk("① 唯一依据三档 A/B/C", [p.get("id") for p in profs] == ["A", "B", "C"], [p.get("id") for p in profs])

    # ── 1) 结构与完备
    for p in profs:
        pid = p.get("id")
        chk("%s 有 硬件清单 (≥3 项)" % pid, len(p.get("hardware") or []) >= 3, len(p.get("hardware") or []))
        chk("%s 有 软件栈" % pid, len(p.get("software") or []) >= 2, len(p.get("software") or []))
        chk("%s 有 标定项" % pid, len(p.get("calib") or []) >= 2, len(p.get("calib") or []))
        chk("%s 有 安全要求" % pid, len(p.get("safety") or []) >= 2, len(p.get("safety") or []))
        wi = p.get("wi") or []
        chk("%s WI 步骤 ≥6" % pid, len(wi) >= 6, "%d 步" % len(wi))
        chk("%s 每步都有 命令/期望/失败处理/在哪做" % pid,
            all(w.get("cmd") and w.get("expect") and w.get("fail") and w.get("need") for w in wi),
            [w.get("id") for w in wi if not (w.get("cmd") and w.get("expect") and w.get("fail"))])
        chk("%s 有 交付验收清单" % pid, len(p.get("acceptance") or []) >= 2, p.get("acceptance"))
        chk("%s 步骤号带档位前缀" % pid, all(str(w.get("id", "")).startswith(pid) for w in wi),
            [w.get("id") for w in wi][:3])

    # ── 2) 命令真跑 (local 类; 跳过自指的验收步骤, 避免递归)
    ran = ok_n = 0
    gaps = []
    slow = []
    for p in profs:
        for w in p.get("wi") or []:
            if w.get("need") != "local":
                continue
            cmd = w.get("cmd") or ""
            if "verify_config_active_task" in cmd or "verify_eng_wi" in cmd:
                slow.append(w.get("id"))
                continue
            ran += 1
            try:
                r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=120)
                out = ((r.stdout or "") + (r.stderr or "")).strip()
                ok = (w.get("expect") or "") in out
            except Exception as e:                                              # noqa: BLE001
                out, ok = repr(e), False
            if w.get("gate") == "gap":
                # 已知缺口 (如数据未采够): 手册如实标红, 判据要求「确实跑不通」才算缺口真实
                chk("② %s 缺口真实存在 (%s)" % (w.get("id"), w.get("title")[:16]), not ok,
                    (out.replace("\n", " ⏎ ")[:90] or "无输出"))
                gaps.append("%s: %s" % (w.get("id"), out.replace("\n", " ")[:40]))
                continue
            ok_n += 1 if ok else 0
            chk("② %s 真验证通过过 (%s)" % (w.get("id"), w.get("title")[:18]), ok,
                (out.replace("\n", " ⏎ ")[:90] or "无输出"))
    chk("② 本机步骤全部真跑 (跳过 %d 条自指验收: %s)" % (len(slow), ",".join(slow)), ran >= 10,
        "%d/%d 通过 · 缺口 %d 条" % (ok_n, ran, len(gaps)))
    if gaps:
        print("   已知缺口(手册已标红): " + " ; ".join(gaps))

    # ── 3) 界面
    from PyQt5.QtWidgets import QApplication, QPushButton
    app = QApplication.instance() or QApplication([])
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    import veh6_config_page as V

    page = V.ConfigCenterPage()
    tab = None
    for i in range(page.tabs.count()):
        if "工程配置" in page.tabs.tabText(i):
            tab = page.tabs.widget(i)
            break
    chk("③ 有「工程配置」页", tab is not None, page.tabs.tabText(0) if tab else "无")
    blk = getattr(page, "eng_profile_card", None)
    chk("③ 有 A/B/C 工程配置块", blk is not None, type(blk).__name__ if blk else "无")
    chk("③ 三档都在", getattr(page, "eng_profile_tiers", []) == ["A", "B", "C"],
        getattr(page, "eng_profile_tiers", None))
    if blk is not None:
        tab.resize(1700, 2600)
        tab.show()
        for _ in range(12):
            app.processEvents()
        wi_t = page.eng_wi_table
        chk("③ A 档 WI 行数 = 唯一依据 9", wi_t.rowCount() == len(profs[0].get("wi") or []),
            "%d 行" % wi_t.rowCount())
        chk("③ 硬件/软件/标定 三表都有行",
            page.eng_hw_table.rowCount() >= 3 and page.eng_sw_table.rowCount() >= 2
            and page.eng_calib_table.rowCount() >= 2,
            (page.eng_hw_table.rowCount(), page.eng_sw_table.rowCount(), page.eng_calib_table.rowCount()))
        # 点「▶ 跑」: A1 五路服务在位 → 状态必须变 ✅ (真跑, 非假动作)
        btn = wi_t.cellWidget(0, 6)
        chk("③ 本机步骤有「▶ 跑」按钮", btn is not None, type(btn).__name__ if btn else "无")
        if btn is not None:
            btn.click()
            for _ in range(6):
                app.processEvents()
            st = wi_t.item(0, 5).text()
            chk("③ 点「跑」后状态真变 ✅", st.startswith("✅"), st)
            chk("③ 跑的输出可回看 (tooltip)", bool(wi_t.item(0, 5).toolTip()), (wi_t.item(0, 5).toolTip() or "")[:60])
        # 切档: B 档 WI = 8 行, 硬件 ≥4
        bts = {b.text()[:1]: b for b in blk.findChildren(QPushButton) if "档" in b.text()}
        chk("③ 三个档位切换按钮", len(bts) >= 3, sorted(bts))
        if "B" in bts:
            bts["B"].click()
            for _ in range(6):
                app.processEvents()
            chk("③ 切到 B 档: WI 行数跟着变", wi_t.rowCount() == len(profs[1].get("wi") or []),
                "%d 行" % wi_t.rowCount())
            chk("③ 切到 B 档: 步骤号变 B*", (wi_t.item(0, 0).text() or "").startswith("B"),
                wi_t.item(0, 0).text())
            chk("③ 切到 B 档: 硬件表变多", page.eng_hw_table.rowCount() == len(profs[1].get("hardware") or []),
                "%d vs %d" % (page.eng_hw_table.rowCount(), len(profs[1].get("hardware") or [])))
        # 复制本档 WI
        cp = next((b for b in blk.findChildren(QPushButton) if "复制本档 WI" in b.text()), None)
        if cp is not None:
            cp.click()
            app.processEvents()
            txt = QApplication.clipboard().text()
            chk("③ 复制本档 WI 真进剪贴板", txt.count("\n") >= 6 and "B1" in txt, "行数 %d" % txt.count("\n"))
        tab.widget().grab().save(os.path.join(ROOT, "docs/eval/config_eng_profile_B.png")) if hasattr(tab, "widget") else tab.grab().save(os.path.join(ROOT, "docs/eval/config_eng_profile_B.png"))

    # ── 4) 文档同源
    chk("④ 操作手册存在", os.path.exists(DOC), os.path.relpath(DOC, ROOT))
    if os.path.exists(DOC):
        txt = open(DOC, encoding="utf-8").read()
        n_wi = sum(len(p.get("wi") or []) for p in profs)
        chk("④ 文档步骤数 = 唯一依据", txt.count("| **") == n_wi, "%d vs %d" % (txt.count("| **"), n_wi))
        chk("④ 三档标题都在", all(("%s 档 · " % p.get("id")) in txt for p in profs), [p.get("id") for p in profs])
        chk("④ 每条命令都进了文档",
            all((w.get("cmd") or "")[:26] in txt for p in profs for w in (p.get("wi") or [])), "逐条核对")
        chk("④ 无密钥泄漏", "sk-" not in txt and "API_KEY=" not in txt, "已核")
        chk("④ 三档对比表在", "选档规则" in txt and "降档可以, 跳档不行" in txt, "有")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "export_wi_doc.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    chk("④ export_wi_doc --check 通过", r.returncode == 0, (r.stdout or "").strip().replace("\n", " | ")[:120])

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
