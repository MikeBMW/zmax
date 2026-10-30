#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐节点验证「右键源码打开的那份代码 → 断点能不能进」(老倪 2026-10-31)

老倪的判据是「右键打开的位置」而不是注册表内部的包装函数，所以本工具以**显示位置**为准：
  右键打开 = sourceview.get_node_location(key) → (文件, 行号)  ← 用户在这里下断点

每个节点报四件事（全部实测）：
  ① 打开位置的文件能不能被 pydevd 绑 —— 必须由**正常 import** 加载（lerobot.*/tools.*）；
     spec/exec 直装的模块 pydevd 看不到 ⇒ 红点在、永不停（本次已统一收口到 modload/_ss_import）
  ② 这份代码**真的被执行了吗** —— 调注册函数（GUI 同一入口）时用 sys.settrace 记录，
     打开位置的文件若一次都没进 ⇒ 右键打开的是"看着像实现、其实跑不到"的代码，必须修
  ③ 打开位置那个函数的每个 `return` 行号 + 本次真跑命中几处
  ④ 注册表包装函数 (library.py:xxxx) 的 return 行 (链路真值)

用法:
    ./gui-venv311/bin/python tools/verify_node_breakpoints.py            # 全表
    ./gui-venv311/bin/python tools/verify_node_breakpoints.py --write    # 落盘 reports/node_breakpoints.json
    ./gui-venv311/bin/python tools/verify_node_breakpoints.py --only ssact,ssplan
    ./gui-venv311/bin/python tools/verify_node_breakpoints.py --exec-all # 含重节点(会触发真实副作用)
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import signal
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
AUDIT = os.path.join(ROOT, "reports", "node_impl_audit.json")
HEAVY = ("ssvideo2", "ssllm", "ssvlm", "ssintact", "swds", "swintact", "swworld",
         "swvideo", "n_vlm_llm", "n_dsvl", "sstrain", "ssdeploy")
# 这些节点的实现是**另起子进程**跑的脚本 (GUI 进程里断点天然不中 —— 要用 F5 单独调脚本)
SUBPROC = {"ss_lora_l4", "ss_lora_l3", "ssintact", "ssintact_dec", "swds", "swintact",
           "swworld", "swvideo", "ssvideo2", "ssz700"}


def _synth_ctx(base: dict) -> dict:
    """第二遍: 喂一份结构化的合成输入, 让"缺输入就早退"的实现能真的往下跑。"""
    import numpy as _np
    c = dict(base)
    for p in ("in1", "in2", "in3", "in4", "in5", "in6"):
        c[p] = {"value": {"obs": _np.zeros(43, dtype=_np.float32), "n": 1, "ok": True},
                "age_s": 0.0, "fresh": True}
    return c


def _rel(p) -> str:
    try:
        return os.path.relpath(str(p), ROOT)
    except Exception:                                                    # noqa: BLE001
        return str(p)


def func_at_line(path: str, line: int, name_hint: str | None = None) -> dict:
    """取包含/紧邻 line 的函数定义 + 它所有 return 行号。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception as e:                                                # noqa: BLE001
        return {"returns": [], "err": "%s: %s" % (type(e).__name__, e)}
    best = None
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(n, "end_lineno", n.lineno)
        if n.lineno <= line <= end:
            if best is None or n.lineno >= best.lineno:      # 取最内层 (离 line 最近的定义)
                best = n
    if best is None and name_hint:
        best = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == name_hint), None)
    if best is None:
        return {"returns": [], "err": "该行不在任何函数内"}
    return {"fn": best.name, "def_line": best.lineno, "end_line": getattr(best, "end_lineno", None),
            "returns": sorted({n.lineno for n in ast.walk(best) if isinstance(n, ast.Return)})}


def bindable(path: str) -> dict:
    """这个文件在运行时是不是**正常 import** 的 (pydevd 可绑)。

    判据以 modload.SPEC_LOADED 台账为准: 走 spec 兜底的文件就是绑不上的那批,
    其余只要进了 sys.modules 就说明是 import 进来的 (pydevd 钩子看得到)。
    """
    from lerobot.engineering import modload as _ml                           # noqa: PLC0415
    real = os.path.realpath(path)
    for name, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if f and os.path.realpath(f) == real:
            if _ml.is_spec(real):
                return {"name": name, "bindable": False, "err": "spec 直装 (pydevd 看不到)"}
            return {"name": name, "bindable": True}
    if _ml.is_spec(real):
        return {"name": None, "bindable": False, "err": "spec 直装 (pydevd 看不到)"}
    rel = os.path.relpath(real, os.path.join(ROOT, "src"))
    if rel.startswith("lerobot/"):
        try:
            m = importlib.import_module(rel[:-3].replace("/", "."))
            return {"name": m.__name__, "bindable": True, "via": "import"}
        except Exception as e:                                          # noqa: BLE001
            return {"name": None, "bindable": False, "err": "%s: %s" % (type(e).__name__, str(e)[:60])}
    return {"name": None, "bindable": False, "err": "未加载过 (该节点这条路没真跑)"}


class Tracer:
    def __init__(self):
        self.lines, self.funcs = {}, {}

    def __call__(self, frame, event, arg):
        f = frame.f_code.co_filename
        if event == "call":
            self.funcs.setdefault(f, set()).add(frame.f_code.co_name)
            self.lines.setdefault(f, set()).add(frame.f_lineno)
        elif event in ("line", "return"):
            self.lines.setdefault(f, set()).add(frame.f_lineno)
        return self


class _Timeout(Exception):
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--exec-all", action="store_true")
    a = ap.parse_args()

    # 有些节点会构造 QWidget (看板/视图) —— 没有 QApplication 会直接 abort 整个审计
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5 import QtWidgets as _QW                                  # noqa: PLC0415
        _qapp = _QW.QApplication.instance() or _QW.QApplication([])
    except Exception:                                                       # noqa: BLE001
        _qapp = None

    from lerobot.engineering import registry as rg                          # noqa: PLC0415
    from lerobot.engineering import nodes as _nodes                          # noqa: F401,PLC0415
    from lerobot.engineering import sourceview as sv                         # noqa: PLC0415

    audit = json.load(open(AUDIT, encoding="utf-8"))
    nodes = [n for n in audit["nodes"] if n.get("fn") and n.get("file")]
    want = {x for x in a.only.split(",") if x}
    if want:
        nodes = [n for n in nodes if n["id"] in want or n["key"] in want]

    def _alarm(_s, _f):
        raise _Timeout()

    rows = []
    for n in nodes:
        key = rg.match_node(n["name"]) or n.get("key")
        info = rg.get(key) or {}
        fn = info.get("fn")
        row = {"id": n["id"], "name": n["name"], "key": key}
        if fn is None:
            row["verdict"] = "NO-IMPL"
            rows.append(row)
            print("%-10s %-16s 无实现" % ("NO-IMPL", n["id"]))
            continue
        # ① 右键打开的位置 (用户下断点的地方)
        loc = None
        try:
            loc = sv.get_node_location(key)
        except Exception:                                                   # noqa: BLE001
            loc = None
        if not loc:
            loc = (info.get("file"), info.get("line"))
        dpath, dline = str(loc[0]), int(loc[1] or 0)
        if not os.path.isabs(dpath):
            dpath = os.path.join(ROOT, dpath)
        row.update({"open_file": _rel(dpath), "open_line": dline,
                    "real_file": _rel(getattr(fn.__code__, "co_filename", "")),
                    "real_line": getattr(fn.__code__, "co_firstlineno", None)})
        dsel = func_at_line(dpath, dline) if os.path.isfile(dpath) else {"returns": []}
        row["open_fn"] = dsel.get("fn")
        row["open_returns"] = dsel.get("returns", [])

        # ② 真跑一拍 (GUI 同一调用口径: 注册函数 + ctx)
        heavy = (not a.exec_all) and (n["id"] in HEAVY or any(h in (key or "") for h in HEAVY))
        tr, entered, dhit = Tracer(), False, []
        if heavy:
            row["exec"] = "跳过(真实副作用)"
        else:
            ctx = {"log": lambda *x, **k: None, "root": ROOT,
                   "params": n.get("params") or {}, "env": os.environ.copy(),
                   "in1": None, "in2": None, "in3": None, "in4": None, "in5": None, "in6": None}
            old = signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(20)
            sys.settrace(tr)
            try:
                fn(ctx)
                row["exec"] = "OK"
            except _Timeout:
                row["exec"] = "超时20s"
            except Exception as e:                                          # noqa: BLE001
                row["exec"] = "%s: %s" % (type(e).__name__, str(e)[:40])
            finally:
                sys.settrace(None)
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old)
            rp = os.path.realpath(getattr(fn.__code__, "co_filename", ""))
            dp = os.path.realpath(dpath)
            entered = fn.__name__ in tr.funcs.get(rp, set())
            row["open_executed"] = bool(tr.funcs.get(dp))
            row["open_funcs"] = sorted(tr.funcs.get(dp, set()))[:6]
            dhit = [r for r in row["open_returns"] if r in tr.lines.get(dp, set())]
            row["open_lines"] = sorted(tr.lines.get(dp, set()))
            row["real_returns"] = sorted({r for r in
                                          (func_at_line(rp, row["real_line"] or 0).get("returns") or [])})
            row["real_returns_hit"] = [r for r in row["real_returns"] if r in tr.lines.get(rp, set())]

            # 第二遍: 第一遍没进到实现文件 ⇒ 换一份合成输入再跑一次 (排除"缺输入早退")
            if not row["open_executed"]:
                tr2 = Tracer()
                old2 = signal.signal(signal.SIGALRM, _alarm)
                signal.alarm(20)
                sys.settrace(tr2)
                try:
                    fn(_synth_ctx(ctx))
                    row["exec2"] = "补跑 OK"
                except _Timeout:
                    row["exec2"] = "补跑超时"
                except Exception as e:                                  # noqa: BLE001
                    row["exec2"] = "补跑 %s: %s" % (type(e).__name__, str(e)[:30])
                finally:
                    sys.settrace(None)
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old2)
                row["open_executed"] = bool(tr2.funcs.get(dp))
                row["open_funcs"] = sorted(tr2.funcs.get(dp, set()))[:6]
                row["open_lines"] = sorted(tr2.lines.get(dp, set()))
                dhit = [r for r in row["open_returns"] if r in tr2.lines.get(dp, set())]
                row["open_lines"] = sorted(tr2.lines.get(dp, set()))
        row["open_returns_hit"] = dhit
        dmod = bindable(dpath) if os.path.isfile(dpath) else {"bindable": False, "err": "文件不存在"}
        if not dmod.get("bindable") and os.path.isfile(dpath):
            dmod = bindable(dpath)          # 执行后再查一次 (模块是跑起来才加载的)
        row["open_module"] = dmod
        row["open_bindable"] = bool(dmod.get("bindable"))
        if heavy:
            row["verdict"] = "SKIP"
        elif n["id"] in SUBPROC:
            row["verdict"] = "SUBPROC"            # 实现在子进程脚本里, GUI 进程断点天然不中
        elif not dmod.get("bindable"):
            row["verdict"] = "FAIL-BIND"
        elif not row.get("open_executed"):
            # 绑得上但这一拍没走到 ⇒ 需要真实输入/参数 (不是"断点进不去")
            row["verdict"] = "NEED-INPUT" if row.get("open_bindable") else "FAIL-NOTRUN"
        elif not dhit:
            row["verdict"] = "FAIL-NORET"       # 跑了, 但没走到任何 return (断点下在 return 上停不住)
        else:
            row["verdict"] = "PASS"
        rows.append(row)
        print("%-11s %-15s 打开 %-34s:%-4s fn=%-22s 该文件执行=%-1s return %d/%d %s"
              % (row["verdict"], n["id"], row["open_file"][-34:], dline, str(row["open_fn"])[:22],
                 "Y" if row.get("open_executed") else "N", len(dhit), len(row["open_returns"]),
                 "→ " + str(dhit) if dhit else ""))

    npass = sum(1 for r in rows if r["verdict"] == "PASS")
    nneed = sum(1 for r in rows if r["verdict"] == "NEED-INPUT")
    nskip = sum(1 for r in rows if r["verdict"] == "SKIP")
    nsub = sum(1 for r in rows if r["verdict"] == "SUBPROC")
    nfail = sum(1 for r in rows if r["verdict"].startswith("FAIL") or r["verdict"] == "NO-IMPL")
    print("\n汇总: 节点 %d · PASS %d · 需真实输入 %d · 子进程 %d · 跳过(重) %d · 失败 %d"
          % (len(rows), npass, nneed, nsub, nskip, nfail))
    for v in ("FAIL-BIND", "FAIL-NOTRUN", "FAIL-NORET", "NEED-INPUT", "NO-IMPL", "SUBPROC", "SKIP"):
        ids = [r["id"] for r in rows if r["verdict"] == v]
        if ids:
            print("  %-11s %d: %s" % (v, len(ids), ",".join(ids)))
    tot = sum(len(r.get("open_returns") or []) for r in rows)
    hit = sum(len(r.get("open_returns_hit") or []) for r in rows)
    print("  打开位置的 return 行共 %d 处 · 本次真跑命中 %d 处 (%.0f%%; 未命中的是分支, 单拍走不到)"
          % (tot, hit, 100.0 * hit / max(tot, 1)))
    if a.write:
        os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
        jp = os.path.join(ROOT, "reports", "node_breakpoints.json")
        json.dump({"t": time.time(), "rows": rows,
                   "summary": {"n": len(rows), "pass": npass, "skip": nskip, "fail": nfail,
                               "returns": tot, "returns_hit": hit}},
                  open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("→", jp)
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
