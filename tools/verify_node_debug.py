#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/verify_node_debug.py — 判据: 六节点「可 debug / 可单步」是真的

老倪 2026-10-16 要求: 「按照这个原理(投影→度量→导航 + 四种连接方式) 再次 review 流形引擎/
流形专家/接触流形/性能流形/DiT/加速器 节点的代码, 要在 550B 标定版本, 可以 debug, 可以代码
单步执行, 我要看到实际的代码编写」⇒ 本判据核这五件事:

  A 结构   六节点在册 · 入口 file:line 真命中 `def node_*` · 算法真体文件存在 · 三环节齐全
  B 真源   引擎轨迹真源 357×43 · 权重 npz 在位 · 观测通道划分与 su2.py 注释一致 (不各说各话)
  C 执行   六节点**真跑**: 每步输出非空 · 引擎 ‖p‖=1 · 接触/性能两处重算逐位一致 · 前馈 cos>0.9
  D 档位   550B 允许深调试 · 550A/550C 拒深调试 (读产品真源) · --list/--src 任何档位不拦
  E 调试   --pdb/ZMAX_DEBUG_BREAK 真进断点 · --step 可交互喂步 · --all --json 写全
  F 诚实   未训练权重标注不冒充在役 · 真源缺失时报缺 (exit≠0), 不填 0 不编数
"""
from __future__ import annotations

import io as _io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import node_debug as nd                                                      # noqa: E402

PY = sys.executable
OK, BAD = [], []


def chk(name, ok, detail=""):
    (OK if ok else BAD).append(name)
    print("%s %-62s %s" % ("✅" if ok else "❌", name, detail))


def _run(args, stdin="", timeout=900):
    p = subprocess.run([PY, os.path.join(ROOT, "tools/node_debug.py")] + args, cwd=ROOT,
                       input=stdin, capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    return p.returncode, p.stdout + p.stderr


def main():
    print("═" * 96)
    print("判据: 六节点单步调试器 (tools/node_debug.py) · 550B 标定/调试档")
    print("═" * 96)

    # ── A 结构 ────────────────────────────────────────────────────────────────
    chk("A1 六节点在册 (引擎/专家/接触/性能/DiT/加速器)", len(nd.NODES) == 6,
        " / ".join(nd.NODES.keys()))
    bad_entry = []
    lib = _io.open(os.path.join(ROOT, nd.ENTRY), encoding="utf-8").read().splitlines()
    for nid, n in nd.NODES.items():
        f, fn, ln = n["entry"]
        line = lib[ln - 1] if ln - 1 < len(lib) else ""
        if not line.startswith("def %s(" % fn):
            bad_entry.append("%s→%s:%d" % (nid, fn, ln))
    chk("A2 入口 file:line 逐条真命中 `def node_*` (行号不是编的)", not bad_entry,
        "坏: %s" % (bad_entry or "无"))
    miss = [m for n in nd.NODES.values() for m in n["modules"]
            if not os.path.isfile(os.path.join(ROOT, m))]
    chk("A3 算法真体文件全部在位 (不指向不存在的源码)", not miss, "缺: %s" % (miss or "无"))
    few = [nid for nid, n in nd.NODES.items() if n["links"].count("/") < 2]
    chk("A4 每个节点都标了投影/度量/导航三环节", not few, "缺环节: %s" % (few or "无"))
    # 四种连接方式 → 源码锚点必须真存在 (符号级)
    bad_anchor = []
    src_all = ""
    for rel in ("src/lerobot/manifold/manifold_engine.py", "src/lerobot/manifold/manifold_layer.py",
                "src/lerobot/policies/smolvla_lew/state_space_action_head.py",
                "src/lerobot/policies/left_right/state_space/parallel.py"):
        src_all += _io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
    for sym in ("def project", "def gradient_flow", "def step", "class MetricCalculator",
                "def channel_axis", "def tangent_gradient", "class StateSpaceActionHead",
                "class ContactManifold"):
        if sym not in src_all:
            bad_anchor.append(sym)
    chk("A5 四种连接方式的源码锚点真存在 (投影/度量/约束流形/条件空间)", not bad_anchor,
        "缺符号: %s" % (bad_anchor or "无"))

    # ── B 真源 ────────────────────────────────────────────────────────────────
    g, err = nd.load_traj(200, None)
    chk("B1 引擎轨迹真源可读 (画布落盘 ss_traj_last.json)", bool(g), err or
        "帧 %d/%d · %s" % ((g or {}).get("idx", -1), (g or {}).get("n", 0), (g or {}).get("saved_at")))
    chk("B2 真源维度 357×43 (与 su2 通道划分同源)", bool(g) and (g or {}).get("n") == 357,
        "n=%s" % (g or {}).get("n"))
    chk("B3 引擎权重 npz 在位", os.path.exists(os.path.join(ROOT, nd.SRC_WEIGHTS)),
        nd.SRC_WEIGHTS)
    su2 = _io.open(os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/su2.py"),
                   encoding="utf-8").read()
    chk("B4 观测通道划分与 su2.py 注释逐字一致 (不各说各话)",
        "[0:3]手位置" in su2 and "[36:39]孔位" in su2 and "[0:3]手 [3]夹爪 [4:7]光模块 [36:39]孔位" in OBSCHK(),
        OBSCHK()[:60])
    chk("B5 几何量由真源帧真算 (e = 光模块头−孔位, 与 su2.obs43_geometry 同式)",
        bool(g) and _same_geometry(g), "e=%s" % (nd._v(g["e"]) if g else "真源缺"))

    # ── C 执行 (六节点真跑) ───────────────────────────────────────────────────
    buf, results = _io.StringIO(), []
    old = sys.stdout
    sys.stdout = buf
    try:
        for nid in nd.NODES:
            results.append(nd.run_node(nid, g))
    finally:
        sys.stdout = old
    chk("C1 六节点真跑完成 (无异常中断)", len(results) == 6, "跑完 %d 个" % len(results))
    chk("C2 六节点不变量自检 6/6 全通过", all(r["checks_ok"] for r in results),
        "未过: %s" % ([r["node"] for r in results if not r["checks_ok"]] or "无"))
    chk("C3 每节点每步都有真输出 (非空, 不是占位)", all(len(r["values"]) >= 3 and
        all(isinstance(v, dict) and v for v in r["values"]) for r in results),
        "步数: %s" % {r["node"]: len(r["values"]) for r in results})
    eng = [r for r in results if r["node"] == "ss_mani_eng"][0]
    chk("C4 流形引擎: 投影 ‖p‖=1 (真在单位球上)", _norm1(eng["values"][1].get("p")),
        "‖p‖=%s" % _n1(eng["values"][1].get("p")))
    chk("C5 流形引擎: 度量给出非零下降方向 (不空转)",
        float(eng["values"][2].get("grad_norm") or 0) > 0,
        "‖∇Φ‖=%s · φ=%s" % (eng["values"][2].get("grad_norm"), eng["values"][2].get("phi")))
    cm = [r for r in results if r["node"] == "ssmani_c"][0]
    chk("C6 接触流形: 独立重算与 decompose 逐位一致 (同源)",
        _close(cm["values"][1]["progress"], cm["values"][2]["progress"]) and
        _close(cm["values"][1]["risk"], cm["values"][2]["risk"]) and
        _close(cm["values"][1]["V"], cm["values"][2]["V"]),
        "进度 %s/%s · V %s/%s" % (nd._f(cm["values"][1]["progress"]), nd._f(cm["values"][2]["progress"]),
                                  nd._f(cm["values"][1]["V"]), nd._f(cm["values"][2]["V"])))
    pm = [r for r in results if r["node"] == "ssmani_p"][0]
    chk("C7 性能流形: V_p/η 与 evaluate 一致 + ∇V_p = Wδ",
        _close(pm["values"][1]["V_p"], pm["values"][2]["Vp"]) and
        _close(pm["values"][1]["eta"], pm["values"][2]["eta"]),
        "V_p %s/%s · η %s/%s" % (nd._f(pm["values"][1]["V_p"]), nd._f(pm["values"][2]["Vp"]),
                                 nd._f(pm["values"][1]["eta"]), nd._f(pm["values"][2]["eta"])))
    ff = [r for r in results if r["node"] == "ss_ff"][0]
    chk("C8 前馈加速器: 方向 == 误差方向 (cos>0.9, 与 _error 同源参考)",
        float(ff["values"][2].get("cos_mlp_mix") or 0) > 0.9,
        "cos=%s (%s°)" % (nd._f(ff["values"][2].get("cos_mlp_mix")),
                          nd._f(nd._deg(ff["values"][2].get("cos_mlp_mix")))))
    dt = [r for r in results if r["node"] == "ssdec"][0]
    chk("C9 DiT: 条件 z⁷ 7 维 + 动作块 4×H 真前向",
        len(dt["values"][0]["z7"]) == 7 and len(dt["values"][2]["action_chunk"]) >= 4,
        "z⁷ 维 %d · 动作块 %d" % (len(dt["values"][0]["z7"]), len(dt["values"][2]["action_chunk"])))
    ex = [r for r in results if r["node"] == "ssmani_exp"][0]
    chk("C10 流形专家: 流形读出 6 维 (与引擎真值列对齐)", int(ex["values"][1]["dim"]) == 6,
        "dim=%d" % int(ex["values"][1]["dim"]))

    # ── D 档位 ────────────────────────────────────────────────────────────────
    gate_b = nd._product_gate("550B")
    gate_a = nd._product_gate("550A")
    gate_c = nd._product_gate("550C")
    chk("D1 550B = 标定/调试档 (debug_allowed 真从产品真源读)",
        bool(gate_b["debug_allowed"]), "active=%s · 键=%s" % (gate_b["active"], gate_b["cfg_keys"]))
    chk("D2 非调试档拒深调试 (550A=%s · 550C=%s)" % (gate_a["debug_allowed"], gate_c["debug_allowed"]),
        not gate_a["debug_allowed"] and not gate_c["debug_allowed"],
        "550A/550C 均不许深调试")
    rc, out = _run(["--node", "ss_mani_eng", "--trace", "--product", "550C"])
    chk("D3 真拦: --product 550C --trace 被拒 (exit≠0 + 说明)",
        rc != 0 and "不是调试档" in out, "exit=%d" % rc)
    rc2, out2 = _run(["--list"])
    chk("D4 只读入口任何档位都不拦 (--list 恒可用)", rc2 == 0 and "ss_mani_eng" in out2,
        "exit=%d" % rc2)

    # ── E 调试能力 ────────────────────────────────────────────────────────────
    rc, out = _run(["--node", "ssmani_p", "--trace", "--pdb"], stdin="c\nc\nc\nc\nc\nc\nc\nc\n")
    chk("E1 --pdb 真进断点并跑完 (pdb 提示 + 不变量块都在)",
        "断点" in out and "不变量自检" in out and rc == 0, "exit=%d" % rc)
    rc, out = _run(["--node", "ssmani_c", "--step"], stdin="\n\n\n\n\n")
    chk("E2 --step 真可交互喂步 (逐步行 + 收尾自检)",
        "① " in out and "③ " in out and "不变量自检" in out, "exit=%d" % rc)
    rc, out = _run(["--node", "ss_ff", "--src"])
    chk("E3 --src 打印源码绝对路径+行号 (VSCode 断点可进)",
        os.path.join(ROOT, "src") in out and ":143" in out and "code -g" in out, "exit=%d" % rc)
    jp = os.path.join(ROOT, "reports/node_debug/_judge.json")
    rc, out = _run(["--all", "--json", "reports/node_debug/_judge.json"])
    ok_json = False
    if os.path.exists(jp):
        d = json.load(open(jp, encoding="utf-8"))
        ok_json = len(d.get("nodes", [])) == 6 and all("stages" in n for n in d["nodes"])
    chk("E4 --all --json 写全六节点轨迹 (供文档/报告)", rc == 0 and ok_json,
        "exit=%d · json=%s" % (rc, "ok" if ok_json else "缺"))
    with open(os.path.join(ROOT, "tools/node_debug.py"), encoding="utf-8") as f:
        ndsrc = f.read()
    chk("E5 pdb 钩子写在源码里 (不是假开关)", "pdb.set_trace()" in ndsrc and
        "ZMAX_DEBUG_BREAK" in ndsrc, "pdb.set_trace + ZMAX_DEBUG_BREAK")

    # ── F 诚实性 ──────────────────────────────────────────────────────────────
    chk("F1 未训练权重如实标注 (DiT/专家不冒充在役)",
        "未训练" in json.dumps(dt["values"], ensure_ascii=False) or
        "随机" in json.dumps(dt["values"], ensure_ascii=False),
        "DiT 权重说明: %s" % str(dt["values"][2].get("weights"))[:52])
    old_src = nd.SRC_TRAJ
    nd.SRC_TRAJ = "data/database/zmax/sources/canvas/_not_exist.json"
    g2, err2 = nd.load_traj(0, None)
    nd.SRC_TRAJ = old_src
    chk("F2 真源缺失时报缺 (不填 0 不编数)", (g2 is None) and bool(err2), str(err2)[:60])
    rc, out = _run(["--node", "ss_mani_eng", "--trace", "--product", "550A"])
    chk("F3 非调试档 --trace 也不偷偷跑 (口径一致)", rc != 0, "exit=%d" % rc)
    chk("F4 调试器只读真源 (源码里没有写真源的口, 唯一写入口=--json 报告)",
        _readonly_check(), "写口: --json 报告")

    print("═" * 96)
    print("判据 %d 条: PASS %d · FAIL %d" % (len(OK) + len(BAD), len(OK), len(BAD)))
    if BAD:
        print("未过: %s" % BAD)
    print("═" * 96)
    return 1 if BAD else 0


def OBSCHK():
    return nd.OBS_CH


def _same_geometry(g):
    """e 必须 == su2.obs43_geometry(obs) (逐位), 用真源码算子复核"""
    try:
        import numpy as np
        su2 = nd._load("src/lerobot/policies/left_right/state_space/su2.py", "zm_su2_judge")
        e = su2.obs43_geometry(g["obs"])
        return bool(np.allclose(e, np.asarray(g["e"], float), atol=1e-12))
    except Exception:                                                        # noqa: BLE001
        return False


def _norm1(a):
    try:
        import numpy as np
        return abs(float(np.linalg.norm(np.asarray(a, float))) - 1.0) < 1e-6
    except Exception:                                                        # noqa: BLE001
        return False


def _n1(a):
    try:
        import numpy as np
        return "%.9f" % float(np.linalg.norm(np.asarray(a, float)))
    except Exception:                                                        # noqa: BLE001
        return "n/a"


def _close(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    except Exception:                                                        # noqa: BLE001
        return False


def _readonly_check():
    """调试器不得写任何真源: 唯一 open(...,'w') 必须在 --json 报告那一段 (main 里 out 变量)"""
    src = _io.open(os.path.join(ROOT, "tools/node_debug.py"), encoding="utf-8").read()
    lines = src.splitlines()
    for i, line in enumerate(lines, 1):
        if "open(" in line and ("'w'" in line or '"w"' in line):
            ctx = " ".join(lines[max(0, i - 4):i + 2])
            if "json.dump" not in ctx and "out" not in ctx:
                return False
    return True


if __name__ == "__main__":
    sys.exit(main())
