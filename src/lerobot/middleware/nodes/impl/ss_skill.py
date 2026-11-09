# -*- coding: utf-8 -*-
"""ss_skill — 节点实现正文 (文件名 = 画布节点: ss_skill)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_skill   ·   registry key: ss_skill
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _SS_DIR,
    _load_mod,
    _skill_spec_from_env,
    os,
)

def node_ss_skill(ctx):
    """🛠 技能编排器 — 新型号规格 → 新技能序列 + 力阈值/节拍 (双击=编排演示)"""
    log = ctx.get("log")
    try:
        path = os.path.join(_SS_DIR, "planner.py")
        m = _load_mod("state_space.planner", path)          # 正常 import (断点可绑)
        c = m.SkillComposer()
        spec_text = (ctx.get("params") or {}).get("spec") or _skill_spec_from_env(log)
        if log:
            log(f"   📥 环境输入口径: 数据源/真机实况 (in1/in2) + 场景理解 + 宏观记忆建议 → 规格文本 "
                f"(见 _skill_spec_from_env; 缺哪一路会如实打印)")
        out = c.compose(spec_text)
        if log:
            log(f"🛠 技能编排器: 规格「{spec_text}」")
            for i, t in enumerate(out["sequence"], 1):
                log(f"   {i}. {t}")
            pr = out["params"]
            log(f"   ⚙ 参数: 力阈值 {pr.get('force_limit')}N · 节拍 {pr.get('tact_time')}s · "
                f"插入深度 {pr.get('insert_depth')}m")
            log(f"   📚 新技能序列已注册进 🧠任务规划器技能库")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 技能编排器演示失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_skill
