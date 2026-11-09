# -*- coding: utf-8 -*-
"""n_eng_mem — 节点实现正文 (文件名 = 画布节点: n_eng_mem)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_eng_mem   ·   registry key: n_eng_mem
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _REPO_ROOT,
    _SS_STATE,
    os,
    sys,
)

def node_ss_eng_mem(ctx):
    """📚 工程记忆 · 技能与经验库 → 🧠 总装记忆中枢 (老倪 2026-09-19: 与飞书端商量好, 工程记忆同步到总装)

    读**真实文件**: docs/7-瑶光-记录追溯/*.md (跨端同步记忆) + ~/.hermes/memories/*.md (Hermes 记忆) +
    ~/.hermes/skills/**/SKILL.md (技能库) → 汇总条数/最新更新 → 追加式同步进顶层宏观记忆
    (macro_memory.engineering, 幂等指纹去重 + 原子写 + 回读校验)。
    """
    log = ctx.get("log")
    try:
        sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))
        from lerobot.memory.eng_memory import EngMemory                         # noqa: PLC0415
        m = EngMemory(repo=_REPO_ROOT)
        snap = m.collect()
        c = snap["counts"]
        if log:
            log(f"📚 工程记忆 (真实文件): 同步文档 {c['docs_memory_files']} 篇 · "
                f"Hermes 记忆 {c['hermes_memory_files']} 个 · 技能 {c['skills']} 条 "
                f"(小节 {c['skill_sections']}) · 记忆条目 {c['memory_items(§)']} 条 · "
                f"**机器人可执行技能 {c.get('l2_skills', 0)} 条**")
            _l2 = snap.get("l2_skills") or []
            _aoi = [s2.get("name") for s2 in _l2 if s2.get("group") == "AOI检测"]
            if _aoi:
                log(f"   🤖 可执行技能 (AOI检测组 {len(_aoi)} 条): " + " / ".join(_aoi[-4:]))
            n = snap.get("newest") or {}
            log(f"   最新: {n.get('mtime_str')} · {os.path.basename(n.get('path', ''))}")
        r = m.sync_to_macro()
        if log:
            if r.get("ok"):
                log(f"   ⮕ 已同步进 🧠总装记忆中枢 (macro_memory.engineering): "
                    f"{'写入 %d 个文件条目' % r.get('added_files', 0) if r.get('wrote') else '内容未变(幂等跳过)'}"
                    f" · llm={r.get('llm')}")
                if r.get("note"):
                    log(f"   ℹ️ {r['note']}")
            else:
                log(f"   ⚠️ 同步失败: {r.get('why')}")
        _SS_STATE["eng_memory"] = {"counts": c, "ok": bool(r.get("ok")), "wrote": bool(r.get("wrote"))}
        return bool(r.get("ok"))
    except Exception as e:
        if log:
            log(f"⚠️ 工程记忆同步失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_eng_mem
