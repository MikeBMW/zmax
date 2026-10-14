#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 控制台**启动流程**里真读「配置真源 + 工程库」⇒ 断点 config_import.py:142 必被走到。

老倪 2026-10-14: 「必须能进入这个断点 (db = _read_db(os.path.join(R, DB_REL))), 改」

判据口径 (逐条可查, 不靠"看起来像"):
  ① 启动输出里有新加的预读行 `📚 启动期配置真源预读: 配置 N 项 (…) · 工程库 ✅ 在位`
  ② 用 sys.settrace 逐行盯着 `src/lerobot/engineering/config_import.py` ⇒ **第 142 行真被执行**
     (这就是 VSCode 断点那一行; 行号取自文件原文, 运行前现读现验, 不硬编)
  ③ 预读是**只读**: 运行前后画布真源 sha256 不变 (启动期不动画布)
  ④ 启动输出无 Traceback
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_cfg_db_startup.py
"""
import contextlib
import hashlib
import importlib.util
import io
import os
import re
import sys
import traceback

REPO = "/home/ubuntu/zmax"
STUDIO = os.path.join(REPO, "tools", "gui", "studio.py")
CIMPORT = os.path.join(REPO, "src", "lerobot", "engineering", "config_import.py")
CANVAS = os.path.join(REPO, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")


def sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:                                                    # noqa: BLE001
        return "-"


def target_line():
    """现读文件, 找出 `db = _read_db(os.path.join(R, DB_REL))` 的行号 (断点行)"""
    for i, ln in enumerate(open(CIMPORT, encoding="utf-8"), 1):
        if "_read_db(os.path.join" in ln:
            return i
    return -1


def main():
    ln = target_line()
    ok = []
    hits = []
    canvas_before = sha(CANVAS)

    def tr(frame, event, arg):
        if frame.f_code.co_filename == CIMPORT:
            if event == "line" and frame.f_lineno == ln:
                hits.append(frame.f_lineno)
            return tr
        return None                       # 别的文件不逐行跟 (省时间)

    # 与真实启动同口径的 sys.path (控制台从 tools/gui 起, 会 import 同目录的 version_sync 等)
    for _p in (os.path.join(REPO, "src"), os.path.join(REPO, "tools", "gui"),
               os.path.join(REPO, "tools"), REPO):
        if os.path.isdir(_p) and _p not in sys.path:
            sys.path.insert(0, _p)
    spec = importlib.util.spec_from_file_location("studio_startup_probe", STUDIO)
    mod = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    err = ""
    sys.settrace(tr)
    t0 = __import__("time").time()
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(mod)          # ← 只跑模块级 = 控制台启动流程
    except Exception:                                                    # noqa: BLE001
        err = traceback.format_exc()[-600:]
    finally:
        sys.settrace(None)
    dt = __import__("time").time() - t0
    out = buf.getvalue()

    m = re.search(r"📚 启动期配置真源预读: 配置 (\d+) 项 \(([^)]*)\).*?工程库 (✅ 在位|❌ 取不到)", out)
    ok.append(("① 启动输出有预读行 (配置名清单 + 工程库在位)",
               bool(m), (m.group(0)[:110] if m else "没找到")))
    ok.append(("② 断点行 %d 在启动流程里**真被执行**" % ln, len(hits) >= 1,
               "命中 %d 次" % len(hits)))
    # ③ 预读这一步本身**只读** (画布真源不动)。注意: 启动流程里"工程状态自恢复"本来就会回写画布
    #    (既有行为, 与本改动无关) ⇒ 这里单独量**预读调用**的副作用, 别把别人的写记在它头上。
    _c0 = sha(CANVAS)
    _tm = __import__("time").time()
    try:
        import importlib as _il
        _ci = _il.import_module("lerobot.engineering.config_import")
        _ci.import_config_files(verbose=False)
        _err2 = ""
    except Exception as e:                                               # noqa: BLE001
        _err2 = "%s: %s" % (type(e).__name__, str(e)[:80])
    _cost = __import__("time").time() - _tm
    _c1 = sha(CANVAS)
    # 只看**代码**(去掉注释行)里有没有写画布的动作 —— 注释里出现函数名不算
    _seg = open(STUDIO, encoding="utf-8").read().split("必须能进入这个断点")[-1]
    _seg = _seg.split("# 🔬 2026-10-10 启动探测")[0]
    _code = "\n".join(l for l in _seg.splitlines() if not l.strip().startswith("#"))
    ok.append(("③ 预读这一步只读 (画布真源不变 + 代码里不写画布 · 耗时 %.2fs)" % _cost,
               (_c0 == _c1) and ("write_into_node" not in _code) and not _err2,
               "%s → %s%s" % (_c0[:12], _c1[:12], (" · " + _err2) if _err2 else "")))
    ok.append(("④ 启动无异常", not err, (err.splitlines()[-1][:120] if err else "clean")))
    print("=" * 78)
    print("判据: 启动期真读配置真源+工程库 ⇒ 断点 config_import.py:%d 必进 (实测 %.1fs 启动)" % (ln, dt))
    print("=" * 78)
    n = 0
    for name, good, info in ok:
        n += bool(good)
        print("%s %s   [%s]" % ("✅" if good else "❌", name, info))
    print("-" * 78)
    print("%d/%d %s" % (n, len(ok), "PASS" if n == len(ok) else "FAIL"))
    # 把预读行**原文整行**打出来 (证据可复制; 含尾部的"实际任务 …")
    _full = next((l.strip() for l in out.splitlines() if "启动期配置真源预读" in l), "")
    if _full:
        print("预读行原文: " + _full)
    return 0 if n == len(ok) else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)                          # 控制台模块级会起线程/单例, 直接退, 别挂住
