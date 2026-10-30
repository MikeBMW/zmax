#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布节点「能不能进断点」的逐节点审计 (2026-10-31 老倪「所有画布节点都要可以进断点」)

判据只有一条:**该节点的真实现函数 (registry[key].fn) 在这一拍被真正调用了**。
断点打在真实现里, 这个函数不被调, 断点就永远不进 —— 与调试器设置无关。

三道闸, 各自有不同的失败文案:
  ① 模块缺失      → status 「模块缺失」
  ② PURE=False    → status 「直通 (PURE=False: 只走数据面)」   ← 59 个节点过去卡在这
  ③ 实现未注册    → status 「直通 (实现未注册: <key>)」
本工具在 ZMAX_NODE_PURE_ALL=1 下装载画布(全局调试闸, 见 middleware/node.py::_load_module),
然后**逐个节点单独走一拍**, 用计数包装 registry 的真函数来判断"到底调没调"。

用法:
  ZMAX_NODE_PURE_ALL=1 ./gui-venv311/bin/python tools/node_breakpoint_audit.py
  ... --only n_exec,ssact          # 只审这几个
  ... --json zmax_data/ss_live/x.json
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

CALLS = []          # 真实现被调用的 key 序列


class _Timeout(Exception):
    pass


def _alarm(_s, _f):
    raise _Timeout()


def wrap_registry():
    """把每个已注册真函数包一层计数 (不动原函数, 只换 registry 里那一格)。"""
    from lerobot.engineering import registry as reg
    wrapped = 0
    for key, info in list(reg.NODE_LOGIC.items()):
        fn = info.get("fn")
        if not callable(fn) or getattr(fn, "_bp_counted", False):
            continue
        def mk(k, f):
            def w(*a, **kw):
                CALLS.append(k)
                return f(*a, **kw)
            setattr(w, "_bp_counted", True)
            setattr(w, "__wrapped__", f)
            return w
        info["fn"] = mk(key, fn)
        wrapped += 1
    return wrapped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=float, default=25.0)
    ap.add_argument("--json", default=os.path.join(ROOT, "zmax_data", "ss_live", "node_breakpoint_audit.json"))
    a = ap.parse_args()

    from lerobot.middleware import load_project
    from lerobot.middleware import node as node_mod
    from lerobot.engineering import registry as reg

    # 有些节点会 new QWidget (AR/视频/画布类)。无 QApplication 时 Qt 直接 qFatal 整个进程退出,
    # 表现为审计跑到某个节点就无输出死掉 (实测 "QWidget: Must construct a QApplication before a QWidget")。
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication          # noqa: F401
        _APP = QApplication.instance() or QApplication([])
        print("Qt: offscreen QApplication 已建 (%s)" % os.environ.get("QT_QPA_PLATFORM"))
    except Exception as e:                                              # noqa: BLE001
        print("Qt: 未建 QApplication (%s: %s) —— 遇 QWidget 节点会整进程退出"
              % (type(e).__name__, str(e)[:60]))

    n_wrapped = wrap_registry()
    t_load = time.monotonic()
    prj = load_project()
    load_s = time.monotonic() - t_load
    ids = [x for x in prj.nodes if not a.only or x in a.only.split(",")]

    print("画布 %d 节点 · 装载 %.2fs · ZMAX_NODE_PURE_ALL=%s · 调试闸覆写 %d 个模块 · registry 包装 %d"
          % (len(prj.nodes), load_s, os.environ.get("ZMAX_NODE_PURE_ALL", "0"),
             len(node_mod.NODE_PURE_FLIPPED), n_wrapped))

    rows = []
    signal.signal(signal.SIGALRM, _alarm)
    for nid in ids:
        n = prj.nodes[nid]
        mod = n.module
        key = getattr(mod, "IMPL_KEY", "") if mod is not None else ""
        info = reg.get(key) if key else None
        registered = bool(info and callable(info.get("fn")))
        pure = getattr(mod, "PURE", None) if mod is not None else None
        CALLS.clear()
        err = st = ""
        t0 = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, a.timeout)
        try:
            tr = prj.step(only=[nid])
            st = (tr[0].get("status") if tr else "") or ""
        except _Timeout:
            st, err = "超时(%.0fs, 已跳过)" % a.timeout, "timeout"
        except Exception as e:                                          # noqa: BLE001
            st, err = "异常", "%s: %s" % (type(e).__name__, str(e)[:120])
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        ms = round((time.monotonic() - t0) * 1000, 1)
        called = key in CALLS if key else False
        rows.append({"id": nid, "pure": pure, "impl_key": key, "registered": registered,
                     "impl_called": called, "status": st, "ms": ms, "err": err,
                     "module": getattr(mod, "__name__", "")})
        # 逐行即时打印 + 落 jsonl: 有节点会让整个进程死掉(Qt abort / os._exit), 不能攒到最后才输出
        if rows == [rows[-1]]:
            print("%-22s %-6s %-22s %-5s %-5s %-7s %s" % ("节点", "PURE", "impl_key", "注册", "调用", "ms", "status"))
        print("%-22s %-6s %-22s %-5s %-5s %-7s %s%s"
              % (nid, str(pure), key or "-", "Y" if registered else "N",
                 "✅" if called else "❌", ms, st[:34], ("  " + err) if err else ""), flush=True)
        try:
            with open(a.json + "l", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")
        except OSError:
            pass

    ok = [r for r in rows if r["impl_called"]]
    bad = [r for r in rows if not r["impl_called"]]
    print("\n合计 %d · 真实现被调用(可断点) %d · 未调用 %d" % (len(rows), len(ok), len(bad)))
    if bad:
        print("未调用明细: " + ", ".join("%s[%s]" % (r["id"], r["status"][:22]) for r in bad))

    try:
        os.makedirs(os.path.dirname(a.json), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "n": len(rows), "ok": len(ok),
                       "pure_all": os.environ.get("ZMAX_NODE_PURE_ALL", "0"),
                       "flipped": sorted(node_mod.NODE_PURE_FLIPPED), "rows": rows}, f,
                      ensure_ascii=False, indent=1)
        print("落盘 %s" % a.json)
    except OSError as e:
        print("落盘失败: %s" % e)
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
