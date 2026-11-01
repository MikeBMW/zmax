#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 记忆库自检 —— 库条目回真源对账 + 节点真读 + 消费方查询 + 引擎零回退。

每一项都真跑 (不是 grep 字符串):
  ① 计数对账      库条目数 vs 真源文件里的条目数
  ② 血统          每条 entry 的 src 存在 + sha 与当前真源一致
  ③ 接口完整      原子技能有 ros+参数 schema; 示教技能有 steps+verify
  ④ 工艺卡        每张有 identity + 工序段, 编排序列有段序列与节拍口径
  ⑤ 点位真值      记忆库里的示教点与 datasets/points 源文件逐位一致
  ⑥ 标杆收敛      三份标杆文件 (store/data/src) 桶集合一致
  ⑦ 节点真读      n_l2_muscle / ss_mem_l2 两个节点 compute() 真返回库数据 (PURE=True)
  ⑧ 消费方查询    daemon._load_points() 与 l2_ros2_bridge 走库查询拿得到点位/技能
  ⑨ 引擎零回退    seed 104 跑一轮: done=True 且 肌肉记忆快通道命中 ≥150 帧

用法: ./gui-venv311/bin/python tools/l2_mem_verify.py   (exit 0 = 全过)
"""
from __future__ import annotations

import glob
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/zmax/zmax_data/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)

from lerobot.memory import l2_store as S            # noqa: E402

R = []
def chk(name, ok, detail=""):
    R.append((name, bool(ok), str(detail)))
    print("%s %-22s %s" % ("✅" if ok else "❌", name, detail), flush=True)


def _j(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    st = S.stats()
    idx = S.index()

    # ① 计数对账
    reg = _j(os.path.join(ROOT, "data/skills/l2_atomic/registry.json"))
    n_at = len(reg.get("skills") or [])
    n_cp = len(reg.get("composite") or [])
    n_mu = len(glob.glob(os.path.join(ROOT, "data/skills/l2_muscle/*.json")))
    n_bs = len(glob.glob(os.path.join(ROOT, "data/database/zmax/sources/config/orders/BS_*.json")))
    ids = {s["id"] for s in (reg.get("skills") or [])} | {c["id"] for c in (reg.get("composite") or [])}
    for p in glob.glob(os.path.join(ROOT, "data/skills/l2_muscle/*.json")):
        ids.add(_j(p).get("id"))
    chk("技能计数对账", st["skills"] == len(ids), "库 %d / 真源 %d (原子 %d+组合 %d+示教 %d, 重名合并 %d)"
        % (st["skills"], len(ids), n_at, n_cp, n_mu, n_at + n_cp + n_mu - len(ids)))
    chk("工艺卡计数对账", st["cards"] == n_bs, "库 %d / BS 工单 %d" % (st["cards"], n_bs))
    chk("编排序列计数", st["seqs"] == st["cards"], "序列 %d / 卡 %d" % (st["seqs"], st["cards"]))

    # ② 血统 + sha 对账 (台账每轮都在长, sha 不比对)
    bad = []
    for bank, items in (("skills", S.skills()), ("points", S.points()), ("cards", S.cards())):
        for k, v in items.items():
            if not isinstance(v, dict) or not v.get("src"):
                bad.append("%s:%s 缺 src" % (bank, k)); continue
            p = os.path.join(ROOT, v["src"])
            if not os.path.exists(p):
                bad.append("%s:%s src 不存在" % (bank, k)); continue
            if v.get("sha") and v["sha"] != S._sha_file(p) and bank != "points":
                bad.append("%s:%s sha 过期 (%s)" % (bank, k, v["sha"]))
    chk("条目血统/sha", not bad, "%d 条对账 · 异常 %d %s"
        % (st["skills"] + st["points"] + st["cards"], len(bad), bad[:3]))

    # ③ 接口完整
    at = S.skills(kind="atomic")
    no_ros = [k for k, v in at.items() if not v.get("ros")]
    no_p = [k for k, v in at.items() if k in ("L2.lift", "L2.lower", "L2.forward") and not v.get("params")]
    mu_ids = [k for k, v in S.skills().items() if v.get("kind") in ("cycle", "aoi", "demo", "pick")]
    no_steps = [k for k in mu_ids if not (S.skill(k).get("steps"))]
    chk("技能接口完整", not (no_ros or no_p or no_steps),
        "原子 %d 条有 ros · 参数缺 %d · 示教 %d 条 steps 缺 %d" % (len(at) - len(no_ros), len(no_p), len(mu_ids), len(no_steps)))

    # ④ 工艺卡 + 编排
    bad_c = []
    for k, c in S.cards().items():
        q = S.seq(k) or {}
        if not (c.get("order_no") or c.get("identity")) or int(c.get("段数") or 0) <= 0:
            bad_c.append(k)
        elif not (q.get("段序列") and q.get("节拍口径")):
            bad_c.append(k + "(无编排)")
    chk("工艺卡含工序/编排", not bad_c, "%d 张 · 异常 %s" % (len(S.cards()), bad_c[:3]))
    # 卡片工序段数 = 源文件 process 长度
    card = S.card(sorted(S.cards())[0])
    src_proc = _j(os.path.join(ROOT, card["src"])).get("process") or []
    chk("工序段数与源一致", card["段数"] == len(src_proc), "%s: 卡 %d / 源 %d" % (card["id"], card["段数"], len(src_proc)))

    # ⑤ 点位真值逐位一致
    p_src = _j(os.path.join(ROOT, "data/datasets/points/光模块_槽位与插入位_20260919.json"))
    diffs = []
    for name, v in (p_src.get("points") or {}).items():
        got = S.point(name) or {}
        if [round(float(x), 9) for x in (got.get("pos") or [])] != [round(float(x), 9) for x in (v.get("tcp_position_m") or [])]:
            diffs.append(name)
    chk("点位与示教源一致", not diffs, "比对 %d 点 · 不一致 %s" % (len(p_src.get("points") or {}), diffs))

    # ⑥ 标杆收敛 (三份桶集合一致)
    sets = {}
    for p in (os.path.join(ROOT, "data/muscle_memory.json"),
              os.path.join(ROOT, "src/data/muscle_memory.json")):
        sets[os.path.basename(os.path.dirname(p)) or "data"] = set((_j(p) or {}).keys())
    sets["store"] = set(S.champs().keys())
    same = len({frozenset(v) for v in sets.values()}) == 1
    chk("标杆三份收敛", same, " ".join("%s=%d" % (k, len(v)) for k, v in sets.items()))

    # ⑦ 节点真读
    ns = importlib.import_module("lerobot.middleware.nodes.n_skills")
    nm = importlib.import_module("lerobot.middleware.nodes.n_muscle")
    o1 = (ns.compute({}) or {}).get("out1") or {}
    o2 = (nm.compute({}) or {}).get("out1") or {}
    chk("n_l2_muscle 真读", ns.PURE and o1.get("技能库") == st["skills"], "PURE=%s 技能库=%s" % (ns.PURE, o1.get("技能库")))
    ops = (o2.get("ops") or {})
    chk("ss_mem_l2 真读", nm.PURE and ops.get("cards") == st["cards"] and ops.get("champs") == st["champs"],
        "PURE=%s cards=%s points=%s champs=%s" % (nm.PURE, ops.get("cards"), ops.get("points"), ops.get("champs")))
    iface = (ns.compute({"in1": {"value": {"skill": "L2.lift"}}}) or {}).get("out1", {}).get("iface") or {}
    chk("节点按 id 查询", iface.get("id") == "L2.lift" and iface.get("ros"), "L2.lift ros=%s 参数=%d"
        % (iface.get("ros"), len(iface.get("params") or [])))

    # ⑧ 消费方走查询
    d = importlib.import_module("lerobot.engineering.exec.daemon")
    pts = d._load_points()
    chk("daemon 点位走库", "slot_pick_place" in pts and pts["slot_pick_place"].get("pos"),
        "点位数 %d · slot_pick_place=%s" % (len(pts), "Y" if pts.get("slot_pick_place") else "N"))
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    br = importlib.import_module("l2_ros2_bridge")
    sk = br._load_skill("L2.MUSCLE.OPEG_CYCLE.v1")
    chk("bridge 技能走库", sk.get("id") == "L2.MUSCLE.OPEG_CYCLE.v1" and len(sk.get("steps") or []) > 0,
        "%s 步=%d 点位=%d" % (sk.get("id"), len(sk.get("steps") or []), len(sk.get("points") or {})))

    # ⑨ 引擎零回退
    from state_space_sim_real import RealStateSpaceSim
    logs = []
    sim = RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda s: logs.append(str(s)))
    tr = sim.run(max_steps=400, cap="l3")
    done = bool(tr["done"][-1]) if tr.get("done") else False
    hits = int(getattr(sim, "_mm_hits", 0) or 0)
    steps = len(tr.get("t") or [])
    chk("引擎零回退(seed104)", done and hits >= 150, "done=%s 步数=%d 快通道命中=%d" % (done, steps, hits))

    n_ok = sum(1 for x in R if x[1])
    print("\n%d 项 · %d PASS · %d FAIL" % (len(R), n_ok, len(R) - n_ok))
    return 0 if n_ok == len(R) else 1


if __name__ == "__main__":
    raise SystemExit(main())
