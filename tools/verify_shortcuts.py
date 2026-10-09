#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_shortcuts.py — 快捷键唯一性 + 打开工程的两处「默认按钮/留痕」取证

🐛 背景 (2026-10-09 老倪: 「加载工程文件后还是没反应」): 实机日志里出现
    QAction::event: Ambiguous shortcut overload: Ctrl+Shift+O
   —— 画布菜单「📂 加载 JSON…」和文件菜单「📂 加载工程文件…」都注册了 Ctrl+Shift+O,
   Qt 判定冲突后**两个快捷键都不触发** (用户按快捷键 = 完全没反应)。
   本判据枚举主窗口全部 QAction, 任何重复快捷键直接判失败 (这类 bug 只能靠机器守)。

用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_shortcuts.py
"""
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QAction, QApplication                                 # noqa: E402

app = QApplication(sys.argv)
import studio as ST                                                               # noqa: E402

ok = [0, 0]


def chk(cond, msg):
    ok[0] += 1
    if not cond:
        ok[1] += 1
    print(("  ✅ " if cond else "  ❌ ") + msg, flush=True)


win = ST.StudioMainWindow()
app.processEvents()

# ① 收集全部快捷键
buckets = {}
for a in win.findChildren(QAction):
    k = a.shortcut().toString()
    if k:
        buckets.setdefault(k, []).append(a.text().replace("&", "").strip())
dups = {k: v for k, v in buckets.items() if len(v) > 1}
print("① 快捷键唯一性 (共 %d 个带快捷键的 QAction)" % sum(len(v) for v in buckets.values()), flush=True)
chk(not dups, "无重复快捷键%s" % ("" if not dups else " —— 冲突: " +
                                  "; ".join("%s = %s" % (k, " | ".join(v)) for k, v in dups.items())))
for k in sorted(buckets):
    print("     %-16s %s" % (k, " | ".join(buckets[k])), flush=True)

# ② 三个关键入口必须各自可达 (快捷键内容固定, 防"修好了又被人改回去")
print("② 打开/加载 入口快捷键", flush=True)
chk(buckets.get("Ctrl+Shift+O") == ["📂 加载工程文件…  (接着上次调试)"],
    "Ctrl+Shift+O 只归「📂 加载工程文件…」→ %s" % buckets.get("Ctrl+Shift+O"))
chk(buckets.get("Ctrl+Alt+O") == ["🗂 打开总工程 (zmax_space)…"],
    "Ctrl+Alt+O 只归「🗂 打开总工程」→ %s" % buckets.get("Ctrl+Alt+O"))
chk(buckets.get("Ctrl+Shift+L") == ["📂 加载 JSON…"],
    "画布「📂 加载 JSON…」已改到 Ctrl+Shift+L → %s" % buckets.get("Ctrl+Shift+L"))
chk(buckets.get("Ctrl+Alt+F") == ["⛶ 浮动画布 (独立窗口)"],
    "画布「⛶ 浮动画布」已改到 Ctrl+Alt+F → %s" % buckets.get("Ctrl+Alt+F"))

# ③ 「打开工程」确认框: 默认按钮必须是「是」+ 按钮文字是动作名 (不是「是/否」)
print("③ 确认框默认按钮 (老倪「点了没反应」根因之一: 默认=否 ⇒ 回车静默取消)", flush=True)
import inspect                                                                    # noqa: E402
p = inspect.signature(ST._msg_ask).parameters
chk("default_yes" in p, "_msg_ask 支持 default_yes (默认按钮可指定)")
chk(p.get("default_yes").default is False, "默认仍是「否」(危险操作不擅自确认)")
chk("yes_text" in p and "no_text" in p, "_msg_ask 支持把按钮写成动作名 (打开工程/取消)")
src = open(os.path.join(ROOT, "tools/gui/studio.py"), encoding="utf-8").read()
chk(src.count('yes_text="🗂 打开工程"') == 1 and src.count('yes_text="📂 加载工程"') == 1,
    "两条打开路径都用了动作名按钮 (🗂 打开工程 / 📂 加载工程)")
chk(src.count("default_yes=True") >= 2, "两条打开路径都设了 default_yes=True (回车=打开)")

# ④ 留痕: 打开/加载 全链写 zmax_data/logs/open_project.log
print("④ 失败可取证: 打开工程留痕", flush=True)
chk(callable(getattr(ST, "_proj_trace", None)), "_proj_trace 存在")
chk(src.count("_proj_trace(") >= 10, "打开/加载全链留痕 (%d 处调用)" % src.count("_proj_trace("))
_log = os.path.join(os.path.expanduser("~/zmax"), "zmax_data", "logs")
ST._proj_trace("verify_shortcuts: 留痕自检")
_fp = os.path.join(_log, "open_project.log")
chk(os.path.exists(_fp) and "留痕自检" in open(_fp, encoding="utf-8").read()[-400:],
    "留痕文件可写: %s" % _fp)

print("\n%s — %d 项" % ("✅ 全部通过" if ok[1] == 0 else "❌ 失败 %d 项 / 共 %d 项" % (ok[1], ok[0]),
                        ok[0]), flush=True)
sys.stdout.flush()
os._exit(1 if ok[1] else 0)
