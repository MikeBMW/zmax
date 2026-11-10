# -*- coding: utf-8 -*-
"""verify_l2_linkage — L2 节点链路**真跑**核验 (不是静态读代码)。

老倪 2026-11-10: 「代码你也看到了, 你要保证这些L2的节点, 信息, 信号是真正联通的,
不要骗我」

做法:
  1. 读画布真源 flows/state_space_obs.json 的 nodes + links (94 节点 / 222 边)
  2. 取 L2 子图, 按拓扑序**真的调用**每个节点的实现函数
  3. 每个节点的 ctx 里填入上游 outN 实际产出的 payload
  4. 逐条边判定三态:
       OK    上游 outN 有值 且 下游 inM 也拿到值
       空口  上游 outN 是 None (节点没交结果)
       崩    节点执行异常 (转调缺失/依赖不全)
  5. 同时核对 registry 绑定 (画布节点名 → 执行函数) 是否正确

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l2_linkage.py
"""
import ast
import glob as _glob
import json
import os
import re
import signal
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.middleware.nodes.impl import shared_runtime  # noqa: F401,E402  触发全部 _reg
from lerobot.engineering.registry import NODE_LOGIC, match_node  # noqa: E402

FLOW = os.path.join(ROOT, "flows/state_space_obs.json")

# L2 链路节点 (老倪这几轮问的 + 它们的上下游)
WANTED = [
    "ssdata", "ssobs", "ssyolo", "ss2d3d", "sstactile", "ssaoi",
    "ssest", "sspred", "ssff", "ssinnov", "ss_mani_eng",
    "n_geoplan", "ssphys", "ssworld", "n_exec",
    "sssched", "sslimit", "ssact", "sssensor", "ssmode",
]

TIMEOUT_S = 15

# ── --engine: 真跑一次流形引擎 ───────────────────────────────────────────
# sslat / ssmani_exp / ss_lora_l4 只从 ctx["module"]._ss_tr 取轨迹 (GUI 播放态内存),
# 离线时必然 return False 说「无引擎轨迹」。这里读 ss_traj_last.json 的 357 帧 obs,
# 逐帧真调 eng.step(), 把引擎算出的潜坐标组装成 _ss_tr, 作为 module 桩传进去。
_MODULE = None
if "--engine" in sys.argv:
    import numpy as _np
    _tp = os.path.join(ROOT, "data/database/zmax/sources/canvas/ss_traj_last.json")
    with open(_tp, encoding="utf-8") as _fh:
        _d = json.load(_fh)
    _obs = _np.asarray(_d["obs"], dtype=float)
    _ue = _np.asarray(_d.get("u_exec_vec") or [], dtype=float)
    from lerobot.manifold.manifold_engine import ManifoldEngine        # noqa: E402
    # ⚠️ 常驻回路 tools/ss_engine_loop.py 已在 10Hz 跑并写 ss_live/manifold_homeostasis.json;
    #    这里关掉内稳态盘写, 否则两个引擎抢同一个 .tmp → os.replace FileNotFoundError
    _eng = ManifoldEngine(homeostasis=False)
    _lat, _pri, _cor = [], [], []
    _res_l, _usat_l, _cp_l = [], [], []
    # ⚠️ 必须先把编码器 fit 到**整条轨迹**: 引擎默认 z_source 是「内建 PCA 编码器
    #    (Encoder.fit, 对当前状态拟合)」, 单帧拟合单样本 ⇒ PCA 方差为 0 ⇒ z 恒全零。
    #    GUI 点 ▶ 运行状态空间时是先 fit 全轨迹再逐帧 step 的, 这里补上同一口径。
    _fit = _eng.fit(_obs)
    print("⚙️ 编码器 fit 全轨迹: %s" % {k: _fit.get(k) for k in list(_fit)[:5]})
    _t0 = time.time()
    for _i in range(len(_obs)):
        _rec = _eng.step(_obs[_i], dt=0.1)
        for _k, _acc in (("z", _lat), ("p_next", _pri), ("p", _cor)):
            _v = _np.asarray(_rec.get(_k) if _rec.get(_k) is not None else [0, 0, 0, 0], dtype=float).ravel()
            _acc.append(_v[:4] if _v.size >= 4 else _np.pad(_v, (0, max(0, 4 - _v.size))))
        # ss_calib 要读这三列 (u_sat 标量范数 / residual / contact_p), 引擎 rec 里都有:
        _a = _np.asarray(_rec.get("action") if _rec.get("action") is not None else [0, 0, 0, 0],
                         dtype=float).ravel()
        _usat_l.append(float(_np.linalg.norm(_a)))
        _r = float(_rec.get("residual") or 0.0)
        _res_l.append(_r)
        _cp_l.append(float(1.0 / (1.0 + _np.exp(-8.0 * abs(_r)))))   # σ(8·‖residual‖), 与引擎同口径
    _stage = [str((_d.get("stage") or ["对位"] * len(_obs))[_i]) for _i in range(len(_obs))] \
        if isinstance(_d.get("stage"), list) and len(_d["stage"]) == len(_obs) else ["对位"] * len(_obs)
    _tr = {
        "t": [round(_i * 0.1, 3) for _i in range(len(_obs))],
        "stage": _stage,
        "obs": _obs.tolist(),
        "latent_vec": [x.tolist() for x in _lat],
        "prior_vec": [x.tolist() for x in _pri],
        "corrected_vec": [x.tolist() for x in _cor],
        "x": _obs[:, 0:3].tolist(),
        "peg_head": _obs[:, 11:14].tolist(),
        "peg": _obs[:, 11:14].tolist(),          # ss_vlm/ss_lora_l4 用 tr["peg"] (与 peg_head 同源)
        "grasped": [float(_obs[i][39]) for i in range(len(_obs))],
        "key_frames": {},                         # 无真帧: 各节点据此如实标「几何对照/无编码」
        "target": _obs[:, 36:39].tolist(),
        "v_vec": (_ue[:, 0:3].tolist() if _ue.ndim == 2 and _ue.shape[0] == len(_obs) else [[0, 0, 0]] * len(_obs)),
        "u_sat": _usat_l, "residual": _res_l, "contact_p": _cp_l,
        "u_sat_vec": [[0.0, 0.0, 0.0]] * len(_obs),
    }

    class _Mod:
        _ss_tr = _tr
        _ss_round = len(_obs) - 1

    _MODULE = _Mod()
    print("⚙️ --engine: 真跑 %d 帧 引擎 step %.2fs (潜维 %s, 末帧 z=%s)"
          % (len(_obs), time.time() - _t0, len(_lat[0]), _np.round(_lat[-1], 3).tolist()))

# 可选: --nodes a,b,c 只跑指定子图 (默认 L2 主干)
if "--nodes" in sys.argv:
    _i = sys.argv.index("--nodes")
    if _i + 1 < len(sys.argv):
        WANTED = [x.strip() for x in sys.argv[_i + 1].split(",") if x.strip()]

# --all: 画布全部节点 (94 节点 / 222 边, L2~L5 + 执行层一次跑完)
if "--all" in sys.argv:
    with open(FLOW, encoding="utf-8") as _fh:
        WANTED = [n["id"] for n in json.load(_fh)["nodes"]]


class _TO(Exception):
    pass


def _alarm(signum, frame):
    raise _TO("节点执行超时 %ds" % TIMEOUT_S)


def call_with_timeout(fn, ctx):
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT_S)
    try:
        return fn(ctx)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# ── 语义契约 (ZMP-2026-015 步骤4) ─────────────────────────────────────────
# 从 impl 源码提取 _pick("inN", ("k1","k2",...)) 的取值键序列。
# 判据: 上游载荷非空, 但下游取值键与载荷键集合**无交集** ⇒ 语义错读
#   (端口有值、日志干净、功能实际失效 —— 比"空口"更隐蔽的一类断点)
# 只加诊断, **不改变四态计数**, 所以真联通率基线不受影响。
def _semantic_contract() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    out: dict = {}
    for fp in _glob.glob(os.path.join(root, "src/lerobot/middleware/nodes/impl/*.py")):
        try:
            txt = open(fp, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        # 用 AST 取真实调用 —— 正则会把 docstring/注释里「原来是这样写的」历史代码当成契约,
        # 实测误报: safety_limit_impl 的 in5 明明已改成质量门, 正则仍从 docstring 抓到旧键。
        try:
            _tree = ast.parse(txt)
        except SyntaxError:
            continue
        _found: dict = {}
        for node in ast.walk(_tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Name) and f.id == "_pick"):
                continue
            if len(node.args) < 2:
                continue
            a0, a1 = node.args[0], node.args[1]
            if not (isinstance(a0, ast.Constant) and isinstance(a0.value, str)):
                continue
            keys: list = []
            if isinstance(a1, (ast.Tuple, ast.List)):
                for e in a1.elts:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        keys.append(e.value)
            if keys:
                _found.setdefault(a0.value, tuple(keys))
        for port, keys in _found.items():
            out.setdefault(os.path.basename(fp), {})[port] = keys
    return out


def main():
    flow = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in flow["nodes"]}
    links = flow["links"]
    sub = [n for n in WANTED if n in nodes]
    sub_set = set(sub)
    in_sub = [l for l in links if l["f"] in sub_set and l["t"] in sub_set]

    print("=" * 86)
    print("L2 链路真跑核验 — 子图 %d 节点 / 子图内 %d 条边 (全图 94/222)"
          % (len(sub), len(in_sub)))
    print("=" * 86)

    # ── ① registry 绑定核对 ──────────────────────────────────────────────
    print("\n① 画布节点 → 执行函数 绑定核对")
    print("   %-12s %-24s %-14s %s" % ("id", "name", "key", "fn"))
    bind = {}
    for nid in sub:
        nm = nodes[nid].get("name", "")
        key = match_node(nm)
        fn = (NODE_LOGIC.get(key) or {}).get("fn")
        fname = getattr(fn, "__name__", "None")
        bind[nid] = (key, fn)
        flag = "" if fn else "  ❌ 无绑定"
        print("   %-12s %-24s %-14s %s%s" % (nid, nm[:22], key, fname, flag))
    # 同一函数被多个节点复用 = 绑定错位
    from collections import defaultdict
    byfn = defaultdict(list)
    for nid, (k, f) in bind.items():
        if f:
            byfn[id(f)].append(nid)
    dups = {k: v for k, v in byfn.items() if len(v) > 1}
    if dups:
        print("\n   ⚠️ 同一函数被多个节点复用 (绑定错位):")
        for k, v in dups.items():
            print("      %s ← %s" % (getattr(NODE_LOGIC[match_node(nodes[v[0]]['name'])]['fn'],
                                             '__name__', '?'), ", ".join(v)))
    else:
        print("\n   ✅ 无函数复用")

    # ── ② 拓扑序 ────────────────────────────────────────────────────────
    indeg = {n: 0 for n in sub}
    adj = {n: [] for n in sub}
    for l in in_sub:
        adj[l["f"]].append(l["t"])
        indeg[l["t"]] += 1
    order, q = [], [n for n in sub if indeg[n] == 0]
    while q:
        n = q.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    cyc = [n for n in sub if n not in order]
    if cyc:
        print("\n   ⚠️ 成环节点(将排在最后跑): %s" % ", ".join(cyc))
        order += cyc

    # ── ③ 真跑 (跑两拍: 环上的边第一拍拿不到上一拍的值, 第二拍才通) ──────
    print("\n② 按拓扑序真调 ×2 拍 (环上边需第二拍; 每节点超时 %ds)" % TIMEOUT_S)
    produced = {}      # (nid, "out1") -> payload  (跨拍累积)
    got = {}           # (nid, "in1") -> 实际喂进的值 (取最后一拍)
    exec_log = {}
    logs = []
    _multi = []        # (节点, 端口, 上游条数, 其中非空条数)

    for _pass in (1, 2):
        if _pass == 2:
            print("   ── 第 2 拍 (用第 1 拍的产出回灌环上输入) ──")
        for nid in order:
            n = nodes[nid]
            key, fn = bind[nid]
            if not fn:
                exec_log[nid] = ("skip", "无绑定")
                continue
            ctx = {"log": lambda m, _n=nid: logs.append((_n, str(m)[:120])),
                   "params": n.get("params") or {}, "name": n.get("name")}
            if _MODULE is not None:
                ctx["module"] = _MODULE        # --engine: 真跑引擎后的 GUI 播放态桩
            # 同一入端口可能有多个上游 (如 ssdec.in5 ← 接触流形/性能流形/潜空间 三条线):
            #   判定「下游能不能拿到」要用**任一非空**, 不能只看最后一条 (后写覆盖 → 误报未送达)
            _port_vals = {}
            for l in in_sub:
                if l["t"] != nid:
                    continue
                v = produced.get((l["f"], l["f_port"]))
                _port_vals.setdefault(l["t_port"], []).append(v)
                ctx[l["t_port"]] = v          # 保真: 引擎侧也是最后一条覆盖
            for _p, _vs in _port_vals.items():
                _nb = [v for v in _vs if v is not None]
                got[(nid, _p)] = _nb[0] if _nb else None
                if len(_vs) > 1:
                    _multi.append((nid, _p, len(_vs), len(_nb)))
            t0 = time.time()
            try:
                out = call_with_timeout(fn, ctx)
                dt = time.time() - t0
                if isinstance(out, dict):
                    nout = 0
                    for k, v in out.items():
                        if str(k).startswith("out") and v is not None:
                            produced[(nid, k)] = v
                            nout += 1
                    exec_log[nid] = ("ok", "%d 个端口有值 / %.2fs" % (nout, dt))
                    if _pass == 2:
                        print("   ✅ %-12s %d 端口有值  %.2fs" % (nid, nout, dt))
                elif out is None:
                    exec_log[nid] = ("ok-empty", "返回 None")
                    if _pass == 2:
                        print("   ⚪ %-12s 返回 None (未产端口值)  %.2fs" % (nid, dt))
                else:
                    exec_log[nid] = ("ok-other", "返回 %s" % type(out).__name__)
                    if _pass == 2:
                        print("   ⚠️  %-12s 返回 %s 非 dict  %.2fs" % (nid, type(out).__name__, dt))
            except _TO as e:
                exec_log[nid] = ("timeout", str(e))
                if _pass == 2:
                    print("   ⏱  %-12s 超时" % nid)
            except Exception as e:  # noqa: BLE001
                exec_log[nid] = ("crash", "%s: %s" % (type(e).__name__, str(e)[:90]))
                if _pass == 2:
                    print("   ❌ %-12s %s: %s" % (nid, type(e).__name__, str(e)[:80]))

    # ── ④ 逐边判定 ───────────────────────────────────────────────────────
    print("\n③ 逐条边判定 (共 %d 条)" % len(in_sub))
    rows = []
    for l in in_sub:
        up = produced.get((l["f"], l["f_port"]))
        dn = got.get((l["t"], l["t_port"]))
        up_ok = up is not None
        dn_ok = dn is not None
        if up_ok and dn_ok:
            st = "OK"
        elif not up_ok and exec_log.get(l["f"], ("", ""))[0] == "crash":
            st = "崩(上游)"
        elif not up_ok:
            st = "空口"
        elif not dn_ok:
            st = "未送达"
        else:
            st = "OK"
        rows.append((st, l["f"], l["f_port"], l["t"], l["t_port"], l.get("label", "")))

    # ── 语义错读细分 (ZMP-2026-015 步骤4): 载荷非空但下游取值键全不命中 ──
    _sem = _semantic_contract()
    _node_src = {}
    for _n in (flow.get("nodes") or []):
        _s = (_n.get("params") or {}).get("source")
        if _s:
            _node_src[_n.get("id")] = os.path.basename(str(_s))
    _misread = []
    _rows2 = []
    for st, f, fp, t, tp, lab in rows:
        if st == "未送达":
            _up = produced.get((f, fp))
            if _up not in (None, {}, [], "") and isinstance(_up, dict):
                _impl = _node_src.get(t)
                _keys = (_sem.get(_impl) or {}).get(tp) if _impl else None
                if _keys:
                    _have = tuple(_up.keys())
                    if not (set(_keys) & set(_have)):
                        st = "未送达·语义错读"
                        _misread.append((t, tp, _impl, _keys, _have))
        _rows2.append((st, f, fp, t, tp, lab))
    rows = _rows2

    order_st = {"OK": 0, "空口": 1, "未送达": 2, "未送达·语义错读": 2, "崩(上游)": 3}
    rows.sort(key=lambda r: order_st.get(r[0], 9))
    for st, f, fp, t, tp, lab in rows:
        icon = {"OK": "✅", "空口": "⚪", "未送达": "❌", "未送达·语义错读": "🔍",
                "崩(上游)": "💥"}.get(st, "?")
        print("   %s %-10s %-6s → %-10s %-6s %-6s %s" % (icon, f, fp, t, tp, st, lab[:24]))

    if _misread:
        print("\n   🔍 语义错读 %d 处 (端口有值、日志干净、功能失效):" % len(_misread))
        for t, tp, impl, keys, have in _misread:
            print("      %-11s %-5s ← %s" % (t, tp, impl))
            print("         取值键  %s" % (keys,))
            print("         载荷键  %s" % (have[:8],))

    # ── ⑤ 汇总 ───────────────────────────────────────────────────────────
    if _multi:
        print("\n④ 多上游共用同一入端口 (引擎侧是「最后一条覆盖」, 会丢掉前面的信号):")
        _last = {}
        for nid, p, n_tot, n_ok in _multi:
            _last[(nid, p)] = (n_tot, n_ok)
        for (nid, p), (n_tot, n_ok) in _last.items():
            print("   %-13s %-5s ← %d 条上游, 其中 %d 条有值%s"
                  % (nid, p, n_tot, n_ok, "" if n_ok == n_tot else "   ⚠️ 有信号被覆盖"))
    from collections import Counter
    cnt = Counter(r[0] for r in rows)
    print("\n" + "=" * 86)
    print("汇总: " + "  ".join("%s=%d" % (k, v) for k, v in cnt.items()))
    total = len(rows) or 1
    print("真联通率: %.1f%%  (%d/%d)" % (100.0 * cnt.get("OK", 0) / total,
                                          cnt.get("OK", 0), len(rows)))
    print("\n节点执行结果:")
    for nid in order:
        st, note = exec_log.get(nid, ("?", ""))
        print("   %-12s %-10s %s" % (nid, st, note))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
