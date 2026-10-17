#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 A/B: 真物理路开"原子技能驱动动作"(ZMAX_SKILL_FF) 到底行不行

结论 (2026-10-18, seed104/500 步): **不行, 默认关**。
  A 现状(解析伺服+反馈)  done=True  348 拍 插深 64.3mm 横向 2.5mm
  C 技能驱动 k=6        done=False 500 拍 插深 41.9mm 横向 18.9mm
  C 技能驱动 k=10       done=False 500 拍 插深 34.4mm 横向 14.3mm
根因: 纯 P 到名义目标即停 (skill_cmd reached=True, u=0), 插孔要的是接触后自适应
      (两段式/螺旋/夹持锁存), 这些在现场目标与反馈里, 覆盖 u_ff 等于丢掉它们。

用法: ./gui-venv311/bin/python tools/ab_skill_ff_real.py
落盘: zmax_data/eval/ab_skill_ff_real.json
"""
import os, sys, json
os.environ.setdefault("MUJOCO_GL","egl"); sys.path.insert(0,"/home/ubuntu/zmax/src")
rows=[]
for tag, sff, k in (("A 现状", "0", 6.0), ("C 技能驱动 k=6", "1", 6.0), ("C 技能驱动 k=10", "1", 10.0)):
    os.environ["ZMAX_SKILL_FF"]=sff; os.environ["ZMAX_SKILL_K"]=str(k); os.environ["ZMAX_L2_GATE"]="0"
    for m in [x for x in list(sys.modules) if x.startswith("lerobot.engine")]: del sys.modules[m]
    from lerobot.engine.runtime import RealStateSpaceSim, ss_insert_metrics
    sim=RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *a: None)
    tr=sim.run(max_steps=500)
    geo=ss_insert_metrics(sim.env, sim._site_ph, sim.geom["hole"], sim.geom["goal"],
                          stage=sim.sched.stage(), grasped=getattr(sim,"grasped",None), step=-1)
    r={"臂":tag,"done":bool(tr["done"][-1]),"拍":len(tr.get("stage_u") or tr["stage"]),
       "插深mm":geo.get("depth_mm"),"横向mm":geo.get("lateral_mm"),
       "skill_cmd":getattr(sim,"skill_cmd",None)}
    rows.append(r)
    print(f"{tag:<16} done={r['done']} 拍={r['拍']} 插深={r['插深mm']} 横向={r['横向mm']} cmd={r['skill_cmd']}", flush=True)
json.dump(rows, open("/home/ubuntu/zmax/zmax_data/eval/ab_skill_ff_real.json","w"), ensure_ascii=False, indent=1)