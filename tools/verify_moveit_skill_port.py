#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 判据: MoveIt 的目标是否真由「原子技能口」给 (而不是人工点名)

老倪 (2026-10-16): 「最终的 moveit 是怎么选择实际的原子任务动作的」
改前: `moveit_plan_req.py` 目标只有 `--to 示教点` / `--goal-xyz` 人工两档, 与技能无关。
改后: `--stage <段>` 或 `--auto`(读引擎发布的 skill_gate.json 当前段) ⇒ 目标 = 示教点 + 本段偏置,
      由技能类 `SK0x.next_target()` 算 (与仿真/真机同一份规则), MoveIt 只把目标规划成轨迹。

判据:
 ① 8 段技能口目标 == 示教点 + 声明偏置 (逐位)
 ② 写出的 plan_req.json 带 goal_src=skill / goal_stage, 且 xyz 与技能口一致
 ③ 段真值陈旧 ⇒ --auto 不猜 (报帧龄, 退回人工)
 ④ 无技能类的段 (拔出/AOI…) ⇒ 明确拒绝 (不硬编目标)
 ⑤ 规划是否真跑 (容器状态如实报告, 不假报)
用法: python3 tools/verify_moveit_skill_port.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "tools"))

ROWS = []


def ck(name, ok, detail=""):
    ROWS.append({"判据": name, "结果": "PASS" if ok else "FAIL", "实测": detail})
    print(("✅ " if ok else "❌ ") + name + (": " + detail if detail else ""))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def main() -> int:
    mr = _load("vmsp_mreq", os.path.join(REPO, "tools", "moveit_plan_req.py"))
    SK = mr._atomic()
    ck("⓪ 技能库可被规划请求侧加载 (与引擎同一份文件)", SK is not None, mr.SKILLS_PY)

    pts_all = json.load(open(mr.TAUGHT, encoding="utf-8"))
    pts = pts_all.get("points") or pts_all          # 唯一依据结构: {version,points{name:{pos,quat}}}
    nm = "slot1" if "slot1" in pts else next(iter(pts))
    base = pts[nm]["pos"]
    print("   示教点 %s = %s" % (nm, [round(float(v), 5) for v in base]))

    # ① 8 段: 技能口 = 点位 + 偏置
    stages = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
    bad = []
    for st in stages:
        cls = SK.skill_for(st)
        t = cls.next_target(points={nm: pts[nm]}, spec={"point": nm}) if cls else None
        exp = {
            "接近": SK.SK01Approach.params["hover_h"], "对位": SK.SK02Align.params["hover_h"],
            "下降": SK.SK03Descend.params["descend_h"], "抓取": 0.0,
            "抬起": SK.SK05Lift.params["lift_h"], "转移": SK.SK06Transfer.params["hover"],
            "插入": 0.0, "完成": 0.0,
        }[st]
        if t is None:
            bad.append((st, "None"))
            continue
        dz = float(t["xyz"][2]) - (float(base[2]) + float(exp))
        dxy = max(abs(float(t["xyz"][0]) - float(base[0])), abs(float(t["xyz"][1]) - float(base[1])))
        if abs(dz) > 1e-12 or dxy > 1e-12:
            bad.append((st, "dz=%.3g dxy=%.3g" % (dz, dxy)))
    ck("①8 段技能口目标 == 示教点 + 声明偏置", not bad, f"{nm} · 不一致 {bad or '无'}")

    # ② 端到端: 让 --stage 走一遍 (真机 tap 无数据时不许阻塞 → 用假状态喂 real_state)
    _stub = {"jpos": [0.0] * 7, "tcp": [0.6488, 0.4983, 0.1104], "tcp_quat": [-0.7392, 0.0035, -0.6734, 0.0088],
             "t": time.time()}
    mr.real_state = lambda: _stub
    req_backup = mr.REQ
    tmp_req = os.path.join(mr.PLAN_DIR, "plan_req.judge.json")
    mr.REQ = tmp_req
    sys.argv = ["moveit_plan_req.py", "--stage", "接近", "--to", nm, "--once"]
    try:
        rc = mr.main()
    except SystemExit as e:                                          # noqa: PERF203
        rc = int(e.code or 0)
    ok2 = os.path.exists(tmp_req)
    rec = json.load(open(tmp_req, encoding="utf-8")) if ok2 else {}
    t_sk = SK.SK01Approach.next_target(points={nm: pts[nm]}, spec={"point": nm})
    same = ok2 and max(abs(a - b) for a, b in zip(rec.get("goal_xyz") or [9, 9, 9], t_sk["xyz"])) < 1e-9
    ck("②写出的 plan_req.json 来自技能口", same and rec.get("goal_src") == "skill"
       and rec.get("goal_stage") == "接近",
       f"rc={rc} goal_src={rec.get('goal_src')} stage={rec.get('goal_stage')} "
       f"xyz={[round(v, 5) for v in (rec.get('goal_xyz') or [])]}")

    # ③ 段真值陈旧 ⇒ --auto 不猜
    _old = json.dumps({"ts": time.time() - 3600, "stage": "插入"})
    mr.GATE_F = os.path.join(REPO, "zmax_data", "ss_live", "skill_gate.judge.json")
    open(mr.GATE_F, "w", encoding="utf-8").write(_old)

    class A:
        stage = None
        auto = True
    nm_stage, src = mr._stage_of(A())
    ck("③段真值陈旧 ⇒ --auto 不猜 (报帧龄)", nm_stage is None, f"返回 {nm_stage!r} · 说明已打印帧龄")
    os.remove(mr.GATE_F)

    # ④ 无技能类的段 ⇒ 明确拒绝
    mr.REQ = os.path.join(mr.PLAN_DIR, "plan_req.judge2.json")
    sys.argv = ["moveit_plan_req.py", "--stage", "拔出", "--to", nm, "--once"]
    try:
        rc4 = mr.main()
    except SystemExit as e:                                          # noqa: PERF203
        rc4 = int(e.code or 0)
    ck("④无技能类的段 (拔出) ⇒ 明确拒绝, 不硬编目标", rc4 == 2
       and not os.path.exists(mr.REQ), f"rc={rc4}")

    # ⑤ 容器/规划真跑没跑 — 如实报告
    import subprocess
    ps = subprocess.run(["sudo", "docker", "ps", "--format", "{{.Names}}"],
                        capture_output=True, text=True)
    running = "zmax-moveit" in (ps.stdout or "")
    ck("⑤规划容器在跑 (才谈得上'已规划')", running,
       "zmax-moveit 在跑" if running else "容器 zmax-moveit 未起 ⇒ 请求已就绪但**规划未跑** (不假报)")

    # 收尾
    for p in (tmp_req, mr.REQ):
        if os.path.exists(p) and "judge" in p:
            os.remove(p)
    mr.REQ = req_backup
    n = sum(1 for r in ROWS if r["结果"] == "PASS")
    print("\n" + "=" * 80)
    print(f"判据 {n}/{len(ROWS)} PASS")
    out = os.path.join(REPO, "zmax_data", "eval", "verify_moveit_skill_port.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"rows": ROWS, "pass": n, "total": len(ROWS), "container_up": running},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("落盘: " + out)
    # ⑤ 只报事实, 不参与退出码 (容器是外部条件)
    core = [r for r in ROWS if not r["判据"].startswith("⑤")]
    return 0 if all(r["结果"] == "PASS" for r in core) else 3


if __name__ == "__main__":
    raise SystemExit(main())
