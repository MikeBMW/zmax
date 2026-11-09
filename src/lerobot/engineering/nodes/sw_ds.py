# -*- coding: utf-8 -*-
"""sw_ds — 节点实现正文 (文件名 = 画布节点: sw_ds)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_sw_ds   ·   registry key: sw_ds
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _SW_S,
    _sw_alive,
    _sw_async,
    _sw_start,
    _sw_status,
    _sw_task,
    os,
    time,
)

def node_sw_ds(ctx):
    """🧪 L4 数据源 — INTACT 环境渲染图像 (stable-world 逐帧渲染真图)
    本节点负责启动桥; 常驻循环里**不阻塞**(异步档), GUI 手动档仍等到桥跑完"""
    log = ctx["log"]
    root = str(ctx.get("root") or os.getcwd())
    ok, st, fr, vd = _sw_start(root, log)
    if not ok:
        return False
    tsk = _sw_task(root)
    _env = "Z-MAX 引擎 RealStateSpaceSim (metaworld peg-insert-side-v3 真物理)" if tsk == "optical_insert" \
        else "stable-world swm/OGBCube-v0"
    log(f"📦 数据源 [L4·{'光模块插拔' if tsk == 'optical_insert' else 'cube'}]: 环境渲染图像 "
        f"(224×224 RGB, EGL 离屏渲染) · 环境={_env} · 帧 spool: {fr}")
    if _sw_async():                                   # 常驻循环: 不占拍, 下游读当前态
        _cur = _sw_status(st)
        log(f"   ⏳ 异步档(常驻循环): 桥在跑 不阻塞本拍 · stage={_cur.get('stage')} "
            f"step={_cur.get('step')} 真推理={_cur.get('model_calls')}")
        return True
    t0 = time.time()
    last = {}
    _budget = float(os.environ.get("SW_CHAIN_TIMEOUT", "2400"))
    while time.time() - t0 < _budget:
        last = _sw_status(st)
        if last.get("stage") == "done":
            break
        if not _sw_alive() and last.get("stage") not in ("done", "error"):
            time.sleep(0.8)
            last = _sw_status(st)
            if last.get("stage") not in ("done", "error"):
                log(f"   ❌ 桥进程异常退出 (stage={last.get('stage')}) → reports/intact_sw/bridge.log")
                return False
            break
        _s = last.get("step")
        if _s is not None and int(_s) % 25 == 0 and int(_s) != _SW_S.get("laststep"):
            _SW_S["laststep"] = int(_s)
            log(f"   ⏳ {last.get('stage')} … step={_s} std={last.get('frame_std')} "
                f"阶段={last.get('stage_label')} 插入深度={last.get('insert_mm')}mm "
                f"真推理={last.get('model_calls')}")
        time.sleep(0.8)
    n = len([x for x in os.listdir(fr) if x.endswith(".jpg")]) if os.path.isdir(fr) else 0
    log(f"   ✅ 渲染帧 {n} 帧 (真图判据 frame_std={last.get('frame_std')} > 5) · "
        f"回合 {last.get('ep_done')} · 起点 {last.get('eval_episodes')}@{last.get('start_steps')}"
        f" · 累计真推理 {last.get('model_calls')} 次")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_sw_ds
