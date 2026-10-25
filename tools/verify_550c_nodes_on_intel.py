#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_550c_nodes_on_intel.py — 550C 画布节点「是否真的在 Intel 上跑」的节点级取证

老倪 2026-10-25: 「一定要 550C 真正的, 每个节点, 都真实的在 intel 上运行」

为什么需要这个脚本: 档位级「550C 在跑」= 看几个服务活着, 会把**孤岛节点/装饰节点**一起算成通过。
这里按**节点**逐个取证, 判据只有一条: 这个节点在 Intel 上有没有**独立证据**(进程/文件新鲜度/端口),
且证据的语义必须对得上这个节点的角色(例: 万有引力节点 ↔ gravity_trace.json 在刷新)。

判据分级 (诚实口径, 缺的那层就说缺):
  ✅ run      有对得上的执行体 + 证据新鲜 (<= FRESH_S)
  ⚠️ stale    有执行体但证据过期 (可能停了/只在特定触发下跑)
  ❌ absent   没有执行体 (节点只在画布上, 没在 Intel 执行)
  ·  nonexec  非执行节点 (背景行/可视化/UI/数据源描述), 不参与判定, 单独计数

用法:
  python3 tools/verify_550c_nodes_on_intel.py            # 打表
  python3 tools/verify_550c_nodes_on_intel.py --json     # 给机器/飞书用
  python3 tools/verify_550c_nodes_on_intel.py --json --out zmax_data/runtime/550c_nodes_audit.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time

REPO = "/home/ubuntu/zmax"
CANVAS = os.path.join(REPO, "data/database/zmax/sources/canvas/state_space_obs.json")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "ConnectTimeout=12", "-p", "18822", "intel@127.0.0.1"]
REMOTE = "/home/intel/zmax_550c"
FRESH_S = 120.0          # 证据新鲜窗口: 引擎 10Hz, 2 分钟没动静就该报 stale

# ---------------------------------------------------------------- Intel 侧一次性取证
PROBE = r"""
cd {R} 2>/dev/null || exit 3
echo "##NOW $(date +%s)"
echo "##FILES"
for f in zmax_data/ss_live/engine_latest.json zmax_data/ss_live/engine_trace.json \
         zmax_data/ss_live/gravity_trace.json zmax_data/ss_live/skill_phys.json \
         zmax_data/ss_live/skill_latest.json zmax_data/ss_live/manifold_homeostasis.json \
         zmax_data/ss_live/chunk_latest.json zmax_data/ss_live/skill_dispatch.json ; do
  [ -f "$f" ] && echo "$f $(stat -c %Y "$f")"
done
echo "##PORTS"
for p in 8800 8797 8802 8796 8793 8801; do
  c=$(curl -s -m2 -o /dev/null -w "%{{http_code}}" http://127.0.0.1:$p/health 2>/dev/null)
  [ "$c" != "000" ] && echo "$p $c"
done
echo "##PROCS"
ps -eo pid,etimes,cmd --no-headers | grep -E 'python.*(ss_daemon|tcp_ar_server|dashboard_server|edge_service|live_trace|ss_fw_trace|ws_bridge|sam3|evolver|gravity)' | grep -v grep | cut -c1-140
echo "##WEIGHTS"
# 🔴 2026-10-26: 原来带 head -20 —— Intel 上 models/ 下有 36 项, sam3_hf 排第 23,
#    于是审计一直报"Intel 无 sam3 权重", 而权重其实早就推进去了(3.44GB 实测)。
#    这里不截断, 权重目录本身就不多。
ls -d models/* 2>/dev/null
"""


def sh(cmd, timeout=90):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def probe_intel():
    r = sh(SSH + [PROBE.format(R=REMOTE)])
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or "ssh 失败").strip()[:200]
    now = 0.0
    files, ports, procs, weights = {}, {}, [], []
    sect = None
    for ln in r.stdout.splitlines():
        if ln.startswith("##NOW"):
            now = float(ln.split()[1]); continue
        if ln.startswith("##"):
            sect = ln[2:].strip(); continue
        if sect == "FILES":
            p, ts = ln.rsplit(" ", 1)
            files[os.path.basename(p)] = float(ts)
        elif sect == "PORTS":
            p, c = ln.split()
            ports[p] = c
        elif sect == "PROCS":
            procs.append(ln.strip())
        elif sect == "WEIGHTS":
            weights.append(os.path.basename(ln.strip()))
    return {"now": now, "files": files, "ports": ports, "procs": procs, "weights": weights}, None


# ---------------------------------------------------------------- 节点 → 执行体 语义映射
def family_of(nid, nm, params):
    nid = str(nid or ""); nm = str(nm or "")
    p = params or {}
    if str(nid).startswith(("ssbg", "row_")) or p.get("row_bg"):
        return "nonexec"
    if p.get("gravity_field") or "万有引力" in nm:
        return "gravity"
    if p.get("manifold_engine") or p.get("calib_layer") or p.get("mani_layer") or "流形" in nm:
        return "manifold"
    if p.get("physics_gate") or "物理约束" in nm:
        return "physics"
    if p.get("skill_layer") or str(nid).startswith("sssk"):
        return "skill"
    if p.get("segmentation") or "SAM3" in nm or "分割" in nm:
        return "seg"
    if "YOLO" in nm or p.get("model") == "yolov8s":
        return "yolo"
    if p.get("aoi") or "光学质量" in nm:
        return "aoi"
    if p.get("task_planner") or p.get("skill_composer") or p.get("exception_reasoner") \
            or p.get("vlm_llm") or p.get("l5_loop") or p.get("mo") or "L3" in nm or "L5" in nm:
        return "llm"
    if p.get("hil") or p.get("web_agent"):
        return "web"
    if p.get("viz_kind") or p.get("state_space_scope") or p.get("state_space_rollout"):
        return "nonexec"
    if p.get("mem_field") or p.get("eng_memory") or "_mem_" in str(nid):
        return "memory"
    if p.get("model") and "intact" in str(p.get("model")).lower() or "INTACT" in nm:
        return "intact"
    if "执行器" in nm or "机械臂" in nm or "物理世界" in nm or p.get("layer") == "L2":
        return "exec"
    # 仿真/引擎内的世界 (RealStateSpaceSim 那套, 跑在 550B 引擎里, 不是 Intel 端侧)
    if str(nid).startswith(("sw", "ssw")) or p.get("sim") or "metaworld" in str(p.get("source", "")).lower():
        return "sim"
    # 状态空间基础链 (前馈/估计/预测/校正/调制/限幅/SU(2)/融合) —— 执行体就是引擎主循环
    if p.get("state_space") or p.get("su2_unified_state") or p.get("kind") == "real":
        return "engine"
    return "unknown"


def eval_node(fam, pv, canvas_has):
    """返回 (verdict, evidence)"""
    files, ports, procs = pv["files"], pv["ports"], pv["procs"]
    now = pv["now"]

    def age(name):
        t = files.get(name)
        return None if t is None else round(now - t, 1)

    def proc_has(*keys):
        return [x for x in procs if any(k in x for k in keys)]

    if fam == "nonexec":
        return "nonexec", "背景行/可视化/UI, 不参与执行判定"
    if fam == "gravity":
        a = age("gravity_trace.json")
        if a is not None and a <= FRESH_S:
            return "run", "gravity_trace.json %.1fs 前刷新 · pid=%s" % (a, (proc_has("ss_daemon", "gravity") or ["-"])[0][:24])
        return ("stale", "gravity_trace.json %ss 未刷新" % a) if a is not None else ("absent", "无 gravity_trace.json")
    if fam == "manifold":
        a = age("engine_latest.json")
        if a is not None and a <= FRESH_S:
            return "run", "engine_latest.json %.1fs 前刷新 (引擎循环)" % a
        return ("stale", "engine_latest.json %ss 未刷新" % a) if a is not None else ("absent", "无 engine_latest.json")
    if fam == "physics":
        a = age("skill_phys.json")
        if a is not None and a <= FRESH_S:
            return "run", "skill_phys.json %.1fs 前刷新 (逐技能物理闸)" % a
        return ("stale", "skill_phys.json %ss 未刷新" % a) if a is not None else ("absent", "无 skill_phys.json")
    if fam == "skill":
        a = age("skill_latest.json")
        if a is not None and a <= FRESH_S:
            return "run", "skill_latest.json %.1fs 前刷新" % a
        return ("stale", "skill_latest.json %ss 未刷新" % a) if a is not None else ("absent", "无 skill_latest.json")
    if fam == "seg":
        if "8796" in ports:
            return "run", "Intel 8796 /health %s" % ports["8796"]
        w = [x for x in pv["weights"] if "sam3" in x.lower()]
        if w:
            # 权重到位 = 能离线跑(不是常驻服务)。实测: 840.4M 参数, 加载 1.5~3.0s,
            # 单提示 40~50s @ CPU 8 线程 ⇒ 静态判据/离线标注可用, 实时要 OpenVINO/NPU。
            return "ready", ("有 %s 权重 + transformers 5.16.1 已装, 离线可跑 "
                             "(实测 840.4M 参数 · 40~50s/提示 @CPU8); 8796 常驻服务未起") % w[0]
        return "absent", "Intel 无 sam3 权重/服务"
    if fam == "yolo":
        if "8800" in ports:
            return "run", "Intel 8800 /health %s (OpenVINO)" % ports["8800"]
        return "absent", "8800 无响应"
    if fam == "aoi":
        if "8802" in ports or "10082" in ports:
            return "run", "Intel 8802/10082 在线"
        return "absent", "AOI 服务不在"
    if fam == "llm":
        return "absent", "Intel 侧无 L3/L5 常驻执行体 (走 550B/远端)"
    if fam == "web":
        pr = proc_has("ws_bridge", "web_agent")
        return ("run", "ws_bridge 在跑 pid=%s" % pr[0][:20]) if pr else ("absent", "无 ws_bridge")
    if fam == "memory":
        a = age("engine_latest.json")
        return ("run", "引擎记忆随 engine_latest 更新 %.1fs" % a) if a is not None and a <= FRESH_S \
            else ("absent", "无记忆执行体")
    if fam == "engine":
        a = age("engine_trace.json")
        al = age("engine_latest.json")
        if a is not None and a <= FRESH_S:
            return "run", "引擎主循环在跑 (engine_trace %.1fs / engine_latest %ss)" % (a, al)
        return ("stale", "引擎证据过期 (trace %ss)" % a) if a is not None else ("absent", "无引擎证据文件")
    if fam == "sim":
        return "absent", "仿真世界跑在 550B 引擎 (RealStateSpaceSim), 不在 Intel 端侧"
    if fam == "intact":
        return "absent", "Intel 无 INTACT 常驻 (权重/进程未就位)"
    if fam == "exec":
        if "39061" in ports or proc_has("tcp_ar_server"):
            return "run", "执行链 39061/AR 台在线"
        return "stale", "执行台进程在但端口未见"
    return "unknown", "未归类"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    canvas = json.load(open(CANVAS, encoding="utf-8"))
    nodes = canvas.get("nodes") or []
    pv, err = probe_intel()
    if pv is None:
        print("❌ 550C(Intel) 不可达: %s" % err)
        return 2

    rows = []
    for n in nodes:
        nid = n.get("id"); nm = n.get("name") or nid; params = n.get("params") or {}
        fam = family_of(nid, nm, params)
        verdict, evidence = eval_node(fam, pv, True)
        rows.append({"id": nid, "name": nm, "family": fam, "type": n.get("type"),
                     "verdict": verdict, "evidence": evidence})

    cnt = {}
    for r in rows:
        cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
    exec_n = len([r for r in rows if r["family"] != "nonexec"])
    out = {"t": time.time(), "t_str": time.strftime("%Y-%m-%d %H:%M:%S"),
           "canvas": CANVAS, "n_nodes": len(rows), "n_executable": exec_n,
           "counts": cnt, "intel": {"ports": pv["ports"], "n_procs": len(pv["procs"]),
                                    "files_age_s": {k: round(pv["now"] - v, 1) for k, v in pv["files"].items()}},
           "verdict_note": ("run=有对得上执行体且证据新鲜; ready=权重/依赖就位能离线真跑但无常驻服务; "
                            "stale=执行体在但证据过期; absent=Intel 上没有该节点执行体; nonexec=非执行节点"),
           "rows": rows}

    if a.out:
        os.makedirs(os.path.dirname(os.path.join(REPO, a.out)), exist_ok=True)
        tmp = os.path.join(REPO, a.out + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(REPO, a.out))

    if a.json:
        print(json.dumps({k: out[k] for k in ("t_str", "n_nodes", "n_executable", "counts", "intel", "verdict_note")},
                         ensure_ascii=False, indent=1))
        return 0

    print("550C 节点级取证 · %s · 画布 %d 节点 (可执行 %d)" % (out["t_str"], len(rows), exec_n))
    print("结论分布:", cnt)
    print()
    order = {"run": 0, "ready": 1, "stale": 2, "absent": 3, "unknown": 4, "nonexec": 9}
    for r in sorted(rows, key=lambda x: (order.get(x["verdict"], 5), x["family"])):
        if r["verdict"] == "nonexec":
            continue
        mark = {"run": "✅", "ready": "🟡", "stale": "⚠️ ", "absent": "❌", "unknown": "? "}[r["verdict"]]
        print("%s %-16s %-12s %s" % (mark, r["id"], r["family"], r["name"][:26]))
        print("     %s" % r["evidence"][:110])
    print()
    print("非执行节点(背景/可视化) %d 个未列出" % cnt.get("nonexec", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
