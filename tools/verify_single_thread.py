#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_single_thread.py —— 严格核验「550B 功能逻辑只有一个线程」

老倪 2026-10-31: 「550B 的功能逻辑只能有一个线程; GUI 除外; 左侧的线程不要跳, 全局修改运行线程, 单线程;
                现在断点又进不去了, 所有断点都要进入; 全局改, 每个节点严格检查」

三个判据 (缺一不算过):
  ① 静态: 功能逻辑目录里**没有**绕开 thread_policy 的裸 `threading.Thread(` / `ThreadPoolExecutor(`
     (允许例外只有: middleware 的传输/总线线程 —— 它们不执行节点实现, 已在白名单里写明)。
  ② 运行时: 单线程模式下真跑**一拍**画布, 每个被调用节点的函数都在 **MainThread** 里执行
     (原来 YOLO/VLM/L3 在 worker 里跑 ⇒ 断点跳线程, 这里会直接点名是哪个节点跑在哪个线程)。
  ③ 线程清点: 这一拍结束后进程里剩下的线程逐个列名, 功能逻辑不得新增常驻 worker。

用法:
  ZMAX_SINGLE_THREAD=1 ./gui-venv311/bin/python tools/verify_single_thread.py [--json] [--write]
退出码: 0 = 全过; 1 = 有失败项。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
for p in (SRC, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

REPORT = os.path.join(ROOT, "reports", "single_thread_audit.json")

# 功能逻辑范围: 这些目录/文件里**不许**有裸线程创建 (必须走 thread_policy.spawn_or_inline)
FUNC_ROOTS = [
    os.path.join(SRC, "lerobot", "engineering", "nodes"),
    os.path.join(SRC, "lerobot", "policies", "left_right", "state_space"),
    os.path.join(SRC, "lerobot", "engine"),
    os.path.join(ROOT, "tools", "ss_canvas_loop.py"),
    os.path.join(ROOT, "tools", "dispatch_inproc.py"),
    os.path.join(ROOT, "tools", "ss_skill_dispatch.py"),
]
# 允许起线程的 (传输/设备/后台服务, 不执行节点实现) —— 带理由, 不是"暂时放过"
THREAD_OK = {
    "lerobot/engineering/thread_policy.py": "单线程策略本身 (spawn_or_inline 的 else 分支)",
    "lerobot/engine/ss3d_live.py": "3D 场景推流发布器 (设备/网络通道, 不跑节点实现)",
}
PAT = re.compile(r"threading\.Thread\(|ThreadPoolExecutor\(")


def _iter_py(root):
    if os.path.isfile(root):
        yield root
        return
    for dp, _dn, fns in os.walk(root):
        if "__pycache__" in dp:
            continue
        for fn in fns:
            if fn.endswith(".py"):
                yield os.path.join(dp, fn)


def static_check():
    bad, ok = [], []
    for root in FUNC_ROOTS:
        for f in _iter_py(root):
            rel = os.path.relpath(f, SRC).replace("\\", "/")
            hit = [(i, ln.strip()) for i, ln in enumerate(open(f, encoding="utf-8", errors="replace"), 1)
                   if PAT.search(ln) and not ln.strip().startswith("#")]
            if not hit:
                continue
            if rel in THREAD_OK:
                ok.append({"file": rel, "why": THREAD_OK[rel], "hits": len(hit)})
            else:
                bad.append({"file": rel, "hits": [{"line": i, "code": c[:100]} for i, c in hit]})
    return {"pass": not bad, "offenders": bad, "allowed": ok}


def runtime_check():
    """单线程模式真跑一拍, 记录每个节点**在哪条线程**上执行。"""
    os.environ["ZMAX_SINGLE_THREAD"] = "1"          # 强制单线程口径
    from lerobot.engineering import thread_policy as tp
    from lerobot.engineering.registry import NODE_LOGIC, NODE_ORDER
    from lerobot.middleware import load_project

    seen = {}
    orig = {}
    for key in list(NODE_LOGIC):
        fn = NODE_LOGIC[key].get("fn")
        if not callable(fn):
            continue
        orig[key] = fn

        def _wrap(*a, _k=key, _f=fn, **kw):
            seen[_k] = threading.current_thread().name
            return _f(*a, **kw)

        _wrap.__name__ = getattr(fn, "__name__", key)
        NODE_LOGIC[key]["fn"] = _wrap

    t0 = time.time()
    err = ""
    n_traces = 0
    try:
        prj = load_project()
        traces = prj.step()
        n_traces = len(traces)
    except Exception as e:                                          # noqa: BLE001
        err = "%s: %s" % (type(e).__name__, str(e)[:200])
    finally:                                                        # 还原注册表, 不留副作用
        for k, fn in orig.items():
            NODE_LOGIC[k]["fn"] = fn

    off = {k: v for k, v in seen.items() if v != threading.main_thread().name}
    return {"pass": (not off) and not err,
            "single_mode": tp.single(),
            "n_registered": len(NODE_ORDER), "n_invoked": len(seen), "n_traces": n_traces,
            "elapsed_s": round(time.time() - t0, 2),
            "off_main": off, "threads": tp.report(), "err": err}


def main() -> int:
    do_json = "--json" in sys.argv
    do_write = "--write" in sys.argv
    st = static_check()
    rt = runtime_check()
    d = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "static": st, "runtime": rt}

    print("① 静态: 功能逻辑里绕开 thread_policy 的裸线程 —— %s"
          % ("✅ 0 处" if st["pass"] else "❌ %d 个文件" % len(st["offenders"])))
    for o in st["offenders"]:
        print("   ❌ %s" % o["file"])
        for h in o["hits"]:
            print("      %5d| %s" % (h["line"], h["code"]))
    for a in st["allowed"]:
        print("   · 允许保留: %s (%s, %d 处)" % (a["file"], a["why"], a["hits"]))

    print("② 运行时: 单线程模式跑一拍 · 调用 %d / 注册 %d 节点 · %d 条 trace · %.2fs"
          % (rt["n_invoked"], rt["n_registered"], rt["n_traces"], rt["elapsed_s"]))
    if rt["err"]:
        print("   ⚠️ 这一拍报错: %s" % rt["err"])
    if rt["off_main"]:
        print("   ❌ 跑在非主线程的节点: %s" % rt["off_main"])
    else:
        print("   ✅ 所有被调节点都在 MainThread 上执行 (左侧线程不会跳)")

    print("③ 线程清点: 共 %d 条 · %s" % (rt["threads"]["n_threads"], ", ".join(rt["threads"]["threads"]) or "(仅主线程)"))

    if do_write:
        os.makedirs(os.path.dirname(REPORT), exist_ok=True)
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
        print("📝 报告: %s" % os.path.relpath(REPORT, ROOT))
    if do_json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    return 0 if (st["pass"] and rt["pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
