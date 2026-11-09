# -*- coding: utf-8 -*-
"""sw_world — 节点实现正文 (文件名 = 画布节点: sw_world)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_sw_world   ·   registry key: sw_world
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _sw_paths,
    _sw_status,
    _sw_task,
    _sw_wait,
    os,
)

def node_sw_world(ctx):
    """🌍 L4 硬件层 — Z-MAX 引擎 / stable-world (动作真下发 env.step)"""
    log = ctx["log"]
    root = str(ctx.get("root") or os.getcwd())
    tsk = _sw_task(root)
    _, fr, st, vd = _sw_paths(root)
    d0 = _sw_status(st)
    log(f"🌍 {'Z-MAX 引擎 (RealStateSpaceSim · metaworld 真物理)' if tsk == 'optical_insert' else 'SW 仿真世界引擎'}"
        f" [L4]: env={d0.get('env', 'swm/OGBCube-v0')} · 动作真下发 env.step")
    d = _sw_wait(st, lambda s: s.get("stage") == "done", 900.0, log, "SW 引擎")
    if not d:
        log("❌ 引擎: 超时无终态 (看 reports/intact_sw/bridge.log)")
        return False
    rows = d.get("rows") or []
    nmod = len([r for r in rows if r.get("model")])
    log(f"   引擎真跑 {d.get('steps')} 步 (模型在环) · 回合 {d.get('ep_done')} · "
        f"模型真推理 {d.get('model_calls')} 次")
    log(f"   解析链对照 (同 seed 同引擎, 可达性基线): {d.get('succ')}/{len(rows)} 成功 "
        f"= {d.get('success_rate')}%")
    for r in rows:
        a = r.get("analytic") or {}
        m = r.get("model") or {}
        fc = (a.get("full_chain") or {})
        log(f"     seed {r.get('seed')}: 解析链 done={a.get('done')} 插入={a.get('insert_mm')}mm"
            + (f" · 全链(插→拔→AOI) done={fc.get('done')} aoi={fc.get('aoi_ok')}" if fc else "")
            + (f" ‖ 模型直驱 done={m.get('done')} 插入={m.get('insert_mm')}mm "
               f"真推理={m.get('model_calls')} 阶段末={str(m.get('stages'))[:60]}" if m else ""))
    log(f"   模型直驱 (在环): {d.get('model_succ')}/{nmod} 成功 = {d.get('model_success_rate')}% · "
        f"帧均值 std={d.get('frame_std')} (>5 真图)")
    _pfx = "optical_insert_" if tsk == "optical_insert" else "cube_sw_"
    _vs = sorted(x for x in os.listdir(vd) if x.endswith(".mp4") and x.startswith(_pfx))
    log(f"   视频 ({len(_vs)} 个, 从引擎取出): " + (" · ".join(_vs[-4:]) or "尚未产出"))
    if d.get("honest_note"):
        log(f"   ⚠️ 诚实标注: {d.get('honest_note')}")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_sw_world
