#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_zmax_open_flow.py — 判据: Z-MAX 标准打开流程 (老倪 2026-10-12 定的规矩)

老倪: 「确定一下 zmax 项目的标准打开流程, 第一步, 打开, 加载 zmax 项目;
      第二步, 弹出配置中心的窗口, 在配置中心, 确定配置, 然后统一打开工程」

判据(真跑, 不读代码空断言):
  ① 接线在位: 控制台有统一打开执行体 + 命令通道认识 open_all + 导航时写状态文件 + 页面拿到回调
  ② 配置中心有「🚀 确认配置 · 统一打开工程」按钮 + 按任务ID选中行 + 无回调时退回命令通道
  ③ 驱动脚本 tools/zmax_open.py 四步入口齐 + step2 走 open_all 且能回退三连命令
  ④ **安全门**: 这套流程里没有任何运动下发 (真机动作仍只从 8793 授权窗走)
  ⑤ 真起配置中心页: select_task_row 真选中该行 (currentRow 行首 == 任务ID)
  ⑥ 真点按钮(有回调): 回调收到 task/activate/page, 页面日志显示逐条结果
  ⑦ 真点按钮(无回调): /tmp/zmax_nav_cmd 真的被写成 open_all (兜底通道)
  ⑧ 驱动脚本真跑 status: 退出码 0 且真读到绑定真源
用法: gui-venv311/bin/python tools/verify_zmax_open_flow.py
"""
import os
import re
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication                                                         # noqa: E402

OK, FAIL, SKIP = [], [], []
STUDIO = os.path.join(ROOT, "tools", "gui", "studio.py")
PAGE = os.path.join(ROOT, "tools", "gui", "veh6_config_page.py")
DRIVER = os.path.join(ROOT, "tools", "zmax_open.py")
NAV = "/tmp/zmax_nav_cmd"
# 真机运动下发词: 这套「打开流程」里出现任何一个都是越界 (安全门)
MOTION_WORDS = ("move_joint", "move_line", "move_pose", "move_sequence", "target_relative_joint",
                "target_joint_state", "gripper_driver", "lissajous", "robot_stop", "recover_estop")


def ck(name, cond, ev=""):
    (OK if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("   ← " + str(ev)) if ev else ""))
    return bool(cond)


def skip(name, why):
    SKIP.append(name)
    print("  ⏭ %s   ← %s" % (name, why))


def rd(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:                                                                            # noqa: BLE001
        return ""


def main():
    s, p, d = rd(STUDIO), rd(PAGE), rd(DRIVER)
    print("① 接线在位 (控制台 / 命令通道 / 状态文件 / 页面回调)")
    ck("studio._open_all_cmd 执行体在位", "def _open_all_cmd(" in s)
    ck("命令通道认识 open_all", 'line == "open_all"' in s and "_open_all_cmd" in s)
    ck("导航时写控制台状态文件", "def _write_console_state" in s and 'self._write_console_state(page=names[idx]' in s)
    ck("配置中心页拿到 on_open_all 回调", "self.cfg_page.on_open_all = self._open_all_cmd" in s)
    ck("执行体按绑定真源取任务 (不另算一套)", 'config", "ss_task_binding.json"' in s and "active_task" in s)
    ck("执行体应用场景走 ss_scene_switch", "ss_scene_switch.py" in s and '"--task"' in s)

    print("② 配置中心页 (按钮 / 选中行 / 兜底通道)")
    ck("按钮「🚀 确认配置 · 统一打开工程」在位", "🚀 确认配置 · 统一打开工程" in p)
    ck("按钮连到 _open_all_clicked", "_open_all_clicked()" in p and "def _open_all_clicked" in p)
    ck("select_task_row 按任务ID选中", "def select_task_row" in p and "setCurrentCell" in p)
    ck("无回调 ⇒ 退回命令通道 open_all", '"/tmp/zmax_nav_cmd"' in p and '"open_all\\n"' in p)

    print("③ 驱动脚本 tools/zmax_open.py")
    ck("四个入口齐 (step1/step2/auto/status)",
       all(x in d for x in ('"step1"', '"step2"', '"auto"', '"status"')))
    ck("第一步: 确认控制台 + 弹配置中心", "ensure_console" in d and 'send_nav("config")' in d)
    ck("第二步: 走 open_all + 回退三连", 'send_nav("open_all")' in d and '"ss_canvas", "ss_3d", "monitor"' in d)
    ck("报结果读真值 (状态文件 + wmctrl)", "zmax_console_state.json" in d and "wmctrl" in d)

    print("④ 安全门: 流程里不许有运动下发")
    hits = sorted({w for w in MOTION_WORDS if re.search(r"\b%s\b" % w, s) and w in d})
    ck("驱动脚本零运动词", not any(w in d for w in MOTION_WORDS), hits)
    _new = s[s.find("def _open_all_cmd("):s.find("def _open_all_cmd(") + 6000]
    ck("_open_all_cmd 零运动词", not any(w in _new for w in MOTION_WORDS))

    print("⑤~⑦ 真起配置中心页 (选中行 / 点按钮两条路径)")
    import veh6_config_page as V                                                                 # noqa: E402
    app = QApplication.instance() or QApplication([])
    th = {k: v for k, v in vars(V).items() if k.startswith("C_")}
    pg = V.build_config_center(None, th)

    class _Stub:
        def __init__(self):
            self.calls = []

        def __call__(self, task="", activate=False, page=None):
            self.calls.append({"task": task, "activate": activate, "page": page})
            return [("活跃任务 (绑定真源)", True, task or "(空)"),
                    ("统一打开工程 (桩)", True, "回调已被真调用")]

    stub = _Stub()
    pg.on_open_all = stub
    task = "TASK-06-TRAY"
    rows = pg.tasks_table.rowCount()
    got = False
    try:
        pg.select_task_row(task)
        _r = pg.tasks_table.currentRow()
        got = (_r >= 0 and (pg.tasks_table.item(_r, 0).text() or "").strip() == task)
    except Exception as e:                                                                        # noqa: BLE001
        print("     (select_task_row 异常: %s)" % e)
    ck("select_task_row 真选中 %s" % task, got, "表格 %d 行" % rows)

    pg._open_all_clicked()
    _c = stub.calls[0] if stub.calls else {}
    ck("按钮→回调 (task/activate/page 都对)",
       bool(stub.calls) and _c.get("task") == task and _c.get("activate") is True and _c.get("page") is pg,
       str(_c.get("task")))
    # ⑤b 真渲染: 按钮在窄窗口(1280/1400)里也**完整可见不被挤** (老倪口径: 界面不许挤/字不许截断)
    from PyQt5.QtCore import QPoint                                                                  # noqa: E402
    from PyQt5.QtWidgets import QPushButton                                                          # noqa: E402
    _bad = []
    for _w in (1280, 1400, 1920):
        pg.resize(_w, 820)
        pg.show()
        app.processEvents()
        _b = [b for b in pg.findChildren(QPushButton) if "统一打开工程" in (b.text() or "")]
        if not _b:
            _bad.append("%d: 找不到按钮" % _w)
            continue
        _b = _b[0]
        _x = _b.mapTo(pg, QPoint(0, 0)).x()
        if _b.width() < _b.sizeHint().width() or (_x + _b.width()) > pg.width():
            _bad.append("%d: 实宽 %d/需 %d, 右边缘 %d > 页宽 %d" % (_w, _b.width(), _b.sizeHint().width(),
                                                                  _x + _b.width(), pg.width()))
    ck("🚀 按钮在 1280/1400/1920 宽下都完整可见 (不挤不截断)", not _bad, " ; ".join(_bad))
    _txt = pg.out.toPlainText()
    ck("页内日志显示逐条结果", "统一打开工程" in _txt and "统一打开工程 (桩)" in _txt)
    ck("页内日志如实标失败 (有❌才说失败)", ("有失败" in _txt) == ("❌" in _txt), _txt.splitlines()[0][:60] if _txt else "")

    _bak = rd(NAV)
    try:
        if os.path.isfile(NAV):
            os.remove(NAV)
        pg.on_open_all = None
        pg._open_all_clicked()
        _w = rd(NAV).strip()
        ck("无回调 ⇒ 命令通道真被写成 open_all", _w == "open_all", repr(_w))
    finally:
        try:
            if _bak:
                with open(NAV, "w", encoding="utf-8") as f:
                    f.write(_bak)
        except Exception:                                                                         # noqa: BLE001
            pass

    print("⑧ 驱动脚本真跑 status")
    try:
        r = subprocess.run([sys.executable, DRIVER, "status"], capture_output=True, text=True, timeout=180,
                           cwd=ROOT)
        _o = (r.stdout or "") + (r.stderr or "")
        ck("status 退出码 0", r.returncode == 0, "rc=%d" % r.returncode)
        ck("status 真读到绑定真源", "绑定真源" in _o and "active_task" in _o)
        ck("status 真读窗口 (wmctrl)", "窗口" in _o)
    except Exception as e:                                                                        # noqa: BLE001
        ck("status 真跑", False, str(e)[:120])

    print("⑨ 端到端回执 (控制台支持 open_all 时才验, 否则如实跳过)")
    try:
        import json as _j
        st = _j.load(open("/tmp/zmax_console_state.json", encoding="utf-8"))
        if "open_all_ok" in st:
            ck("控制台最近一次统一打开已回执", isinstance(st.get("open_all_ok"), bool),
               "task=%s ok=%s scene=%s" % (st.get("task"), st.get("open_all_ok"), (st.get("scene") or "")[:40]))
            ck("回执含逐步结果", isinstance(st.get("open_all_steps"), list) and len(st["open_all_steps"]) >= 4,
               "%d 步" % len(st.get("open_all_steps") or []))
        else:
            skip("控制台 open_all 回执", "状态文件里还没有 open_all_ok (控制台还没重启到含本流程的版本)")
    except Exception as e:                                                                        # noqa: BLE001
        skip("控制台 open_all 回执", "没有状态文件: %s" % str(e)[:60])

    print("\n%s  %d/%d PASS%s" % ("✅" if not FAIL else "❌", len(OK), len(OK) + len(FAIL),
                                  ("  (%d 跳过)" % len(SKIP)) if SKIP else ""))
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)      # Qt 退出期线程偶发崩溃 ⇒ 判据结论以打印为准, 直接硬退


if __name__ == "__main__":
    main()
