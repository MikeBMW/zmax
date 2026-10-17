#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中间件判据 (middleware) —— 逐层取证, 不信自述。

① 工程加载: 节点数/连线数/拓扑序/模块就位数 与画布真源一致
② 节点模块: 每个节点 1 个模块文件, 端口 == 工程 JSON 由连线推出的端口 (逐节点)
③ 数据面: 真注入一个值 → 跑一拍 → 上游发到总线 → 下游从总线读到 (跨节点, 走总线不是传参)
④ 后端门控: 550B=DDS 开 · 550A/550C=DDS 关 · 详细原因可打印
⑤ 跨进程共享内存总线: A 进程发 → B 进程读 (真实双进程)
⑥ 右键落点: 先到中间件节点模块 (能看到 PORTS_IN/OUT), 并给出真实现位置
用法: ./gui-venv311/bin/python tools/verify_middleware.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lerobot.middleware import (bus_enabled, load_project, make_bus,  # noqa: E402
                                parse_canvas, resolve_open_target)
from lerobot.middleware.bus import MemBus, ShmBus                     # noqa: E402

RES = []


def ck(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(("✅ " if ok else "❌ ") + name + ((" — " + detail) if detail else ""))
    return ok


def main():
    specs, links, meta = parse_canvas()
    print("真源:", meta["canvas"])

    # ① 工程加载
    prj = load_project(bus=MemBus())
    st = prj.stats()
    ck("① 工程加载: 节点/连线/序 与画布一致",
       st["nodes"] == meta["nodes"] and st["links"] == meta["links"] and st["order"] == meta["nodes"],
       "%d 节点 · %d 连线 · 拓扑序 %d · 反馈边 %d" % (st["nodes"], st["links"], st["order"], st["feedback"]))
    ck("① 节点模块全部就位", st["module_ok"] == st["nodes"],
       "%d/%d (实现绑定 %d)" % (st["module_ok"], st["nodes"], st["impl_bound"]))

    # ② 逐节点: 模块端口 == JSON 端口
    bad = []
    for sid, nd in prj.nodes.items():
        m = nd.module
        if m is None:
            bad.append("%s: 无模块" % sid)
            continue
        if list(getattr(m, "PORTS_IN", [])) != list(nd.spec.inputs):
            bad.append("%s: PORTS_IN %s != JSON %s" % (sid, getattr(m, "PORTS_IN", None), nd.spec.inputs))
        if list(getattr(m, "PORTS_OUT", [])) != list(nd.spec.outputs):
            bad.append("%s: PORTS_OUT %s != JSON %s" % (sid, getattr(m, "PORTS_OUT", None), nd.spec.outputs))
        if getattr(m, "NODE_ID", None) != sid:
            bad.append("%s: NODE_ID 不符 (%s)" % (sid, getattr(m, "NODE_ID", None)))
    ck("② 每个节点的模块端口 == 工程 JSON 端口", not bad,
       "逐节点核对 %d 个" % len(prj.nodes) if not bad else "; ".join(bad[:3]))

    # ③ 数据面: 注入 → 上游发总线 → 下游从总线读
    #    找一条 in 端口是 in1 的线, 在源节点的 in1 注值
    #    找一条"可注入"的线: 源节点的对应输入口没有上游写者 (注入不会被覆盖),
    #    且源在序里先于目标 (单趟就能看到值 → 证明是本拍走总线到的下游)
    rank = {nid: i for i, nid in enumerate(prj.order)}
    writers = {}
    for l in prj.links:
        writers.setdefault((l["t"], l["t_port"]), []).append(l["f"])
    cand = None
    for l in prj.links:
        src, dst = prj.nodes.get(l["f"]), prj.nodes.get(l["t"])
        if not (src and dst) or src.spec.exec_mode != "pure":
            continue
        if l["f_port"] not in src.spec.outputs or l["t_port"] not in dst.spec.inputs:
            continue
        idx = src.spec.outputs.index(l["f_port"])
        if idx >= len(src.spec.inputs):
            continue
        in_port = src.spec.inputs[idx]
        if writers.get((src.spec.id, in_port)):
            continue                     # 该输入口有上游常写 → 注入会被下一拍覆盖
        if len(writers.get((dst.spec.id, l["t_port"]), [])) != 1:
            continue                     # 下游该口有多个写者 → 判据不干净
        if rank[src.spec.id] > rank[dst.spec.id]:
            continue                     # 反序边属闭环反馈 (延迟一拍), 不用于单拍判据
        cand = (l, idx, in_port)
        break
    ok3 = False
    det3 = "找不到可注入的干净连线"
    if cand:
        l, idx, in_port = cand
        src, dst = prj.nodes[l["f"]], prj.nodes[l["t"]]
        prj.inject(src.spec.id, in_port, {"probe": 4242})
        prj.step()
        up_v, up_ts = prj.bus.latest(src.topic(l["f_port"]))
        dn_v, dn_ts = prj.bus.latest(dst.topic(l["t_port"]))
        ok3 = (up_v is not None and dn_v is not None and dn_v == up_v)
        det3 = "%s.%s(%s) → %s.%s = %r · 上游话题=%r" % (
            src.spec.id, in_port, l["f_port"], dst.spec.id, l["t_port"], dn_v, up_v)
    ck("③ 数据面: 上游发到总线 / 下游从总线读到", ok3, det3)

    # ④ 后端门控 (550B 开 / 550A・550C 关)
    env = dict(os.environ)
    got = {}
    for prod in ("550A", "550B", "550C"):
        env["ZMAX_PRODUCT"] = prod
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "mw_project.py"), "bus"],
                             capture_output=True, text=True, env=env, cwd=ROOT)
        first = (out.stdout or "").splitlines()[0] if out.stdout else ""
        got[prod] = ("True" in first.split("|")[0])
    ck("④ DDS 只对 550B 开 (A/C 关)", got == {"550A": False, "550B": True, "550C": False},
       "实测 " + json.dumps(got, ensure_ascii=False))
    okb, why = bus_enabled("550B")
    ck("④ 门控原因可打印", bool(why), why)

    # ⑤ 跨进程共享内存总线 (双进程真验)
    ns = "verify_mw"
    path = os.path.join("/dev/shm", "zmax_mw", "%s.bus.jsonl" % ns)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:                                                     # noqa: BLE001
        pass
    code_pub = (
        "import sys;sys.path.insert(0,%r)\n"
        "from lerobot.middleware.bus import ShmBus\n"
        "b=ShmBus(ns=%r);b.publish('ss.node.proc.probe', 777);b.close();print('PUB_OK')" % (SRC, ns))
    code_sub = (
        "import sys;sys.path.insert(0,%r)\n"
        "from lerobot.middleware.bus import ShmBus\n"
        "b=ShmBus(ns=%r);v,ts=b.latest('ss.node.proc.probe');print('GOT',v,ts)" % (SRC, ns))
    p1 = subprocess.run([sys.executable, "-c", code_pub], capture_output=True, text=True)
    p2 = subprocess.run([sys.executable, "-c", code_sub], capture_output=True, text=True)
    ok5 = "GOT 777" in (p2.stdout or "")
    ck("⑤ 共享内存总线跨进程可达", ok5,
       "发: %s · 收: %s" % ((p1.stdout or p1.stderr or "").strip()[-40:],
                            (p2.stdout or p2.stderr or "").strip()[-60:]))

    # ⑥ 右键落点 = 中间件节点模块
    ok6, det6 = 0, []
    sample = [prj.nodes[i] for i in prj.order[:3]]
    for nd in sample:
        t = resolve_open_target(nd.spec, root=ROOT)
        p = t.get("path") or ""
        good = p.endswith("%s.py" % nd.spec.module_name) and (t.get("line") or 0) > 0
        ok6 += 1 if good else 0
        det6.append("%s→%s:%s" % (nd.spec.id, os.path.basename(p), t.get("line")))
    ck("⑥ 右键先进入节点模块 (含输入输出)", ok6 == len(sample), " · ".join(det6))

    # 收尾
    # ⑦ 550B 真 DDS 后端: 加载完整工程 → 注入 → 下游输入话题从 DDS 读到
    try:
        pd = load_project(product="550B")
        src, dst = pd.nodes["n_eng_mem"], pd.nodes["ss_mem_share"]
        pd.inject("n_eng_mem", "in1", {"probe": "dds550b"})
        pd.step()
        v, ts = pd.bus.latest(dst.topic("in5"))
        ok7 = (pd.bus_info.get("backend") == "dds") and v == {"probe": "dds550b"}
        det7 = "后端=%s · %s.in5=%r" % (pd.bus_info.get("backend"), dst.spec.id, v)
        pd.close()
    except Exception as e:                                                # noqa: BLE001
        ok7, det7 = False, "%s: %s" % (type(e).__name__, e)
    ck("⑦ 550B: 整工程走真 DDS 后端 (话题级路由)", ok7, det7)

    # ⑧ 550A/550C 不开 DDS (真实后端名)
    backs = {}
    for prod in ("550A", "550C"):
        b, info = make_bus(product=prod, ns="chk_" + prod)
        backs[prod] = info.get("backend")
        b.close()
    ck("⑧ 550A/550C 不用 DDS 后端", backs.get("550A") != "dds" and backs.get("550C") != "dds",
       json.dumps(backs))

    prj.close()
    npass = sum(1 for _, ok, _ in RES if ok)
    print("\n===== %d/%d 通过 =====" % (npass, len(RES)))
    for name, ok, det in RES:
        if not ok:
            print("  ❌", name, "—", det)
    return 0 if npass == len(RES) else 3


if __name__ == "__main__":
    raise SystemExit(main())
