#!/usr/bin/env python3
"""信号 → 目标场景 标签 (单一真源) —— 信号分析页按 绿/蓝/紫/白 标记与排序 (老倪 2026-10-12 逐字要求)。

老倪: 「每个场景对应不同的信号分析…信号分析主窗口的信号是有目标场景的, 你得标记出来…
       信号分析也用 绿色 蓝色 紫色 代表对应不同的场景; 信号分析要有个排序的功能, 即按照 绿色/蓝色/紫色/白色 来排列,
       白色就是所有颜色的信号都显示, 没有分类的信号都是白色」

颜色/任务 → 场景 的映射**不在这里重写**, 统一从 tools/ss_scene_switch.py 取(那才是唯一映射表):
    插拔场景 #2e8b57 (绿 · TASK-01-FW) / 摆盘场景 #1f6feb (蓝 · TASK-06-TRAY) / AR场景 #8957e5 (紫 · TASK-07-AOI)

信号→场景的证据来源(谁有证据就按谁, 没证据就是白/未分类, 不硬猜):
  ① config/topics/ar_aoi_signals.json 的组 → AR场景(紫)   [AR/AOI 话题是真算出来的, 见组内 src]
  ② zmax_data/task_runs/<TASK>/ 下的运行产物里真出现过的信号名 → 该任务对应场景(--from-runs)
  ③ config/topics/scene_tags.json 的 overrides (人工/学习到的补充, 可编辑)

用法:
  ./gui-venv311/bin/python tools/sig_scene_tags.py --build [--from-runs]   # 生成/刷新注册表
  ./gui-venv311/bin/python tools/sig_scene_tags.py --summary               # 各场景信号数
  ./gui-venv311/bin/python tools/sig_scene_tags.py --tag "光学质量检测.判决"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

OUT = os.path.join(ROOT, "config", "topics", "scene_tags.json")
AR_REG = os.path.join(ROOT, "config", "topics", "ar_aoi_signals.json")
RUNS = os.path.join(ROOT, "zmax_data", "task_runs")
WHITE = "#ffffff"          # 未分类 = 白

sys.path.insert(0, ROOT)
try:
    import ss_scene_switch as SSW                      # 颜色/任务映射的唯一真源
    TASK_SCENE = dict(SSW.TASK_SCENE)
    SCENE_COLOR = dict(SSW.SCENE_COLOR)
except Exception:                                                             # noqa: BLE001
    TASK_SCENE = {"TASK-01-FW": {"scene": "插拔场景", "color": "#2e8b57"},
                  "TASK-06-TRAY": {"scene": "摆盘场景", "color": "#1f6feb"},
                  "TASK-07-AOI": {"scene": "AR场景", "color": "#8957e5"}}
    SCENE_COLOR = {"插拔场景": "#2e8b57", "摆盘场景": "#1f6feb", "AR场景": "#8957e5", "真机": "#c9d1d9"}
SCENES = [v["scene"] for v in TASK_SCENE.values()]


def scenes_payload() -> dict:
    """给 UI 用的场景表(颜色+任务+scn, 顺序 = 绿 蓝 紫)。"""
    out = []
    for tid in ("TASK-01-FW", "TASK-06-TRAY", "TASK-07-AOI"):
        m = TASK_SCENE.get(tid) or {}
        if not m:
            continue
        out.append({"task": tid, "scene": m["scene"], "scn": m.get("scn", ""), "color": m["color"],
                    "label": m.get("name") or m["scene"]})
    return out


def _registry() -> dict:
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                         # noqa: BLE001
        return {"signals": {}, "overrides": {}}


def _ar_signals() -> dict:
    """AR/AOI 注册表里的信号名(裸名, 不带 ar. 前缀) → 组名。"""
    out = {}
    try:
        with open(AR_REG, encoding="utf-8") as f:
            d = json.load(f)
        for g, items in (d.get("groups") or {}).items():
            for it in (items or []):
                k = it.get("key") if isinstance(it, dict) else it
                if k:
                    out[str(k)] = g
    except Exception:                                                         # noqa: BLE001
        pass
    return out


def _run_signals() -> dict:
    """扫描 zmax_data/task_runs/<TASK>/ 的运行产物, 取真出现过的信号名 → 该任务的场景 (有证据才标)。"""
    out = {}
    if not os.path.isdir(RUNS):
        return out
    for tid in os.listdir(RUNS):
        scene = (TASK_SCENE.get(tid) or {}).get("scene")
        if not scene:
            continue
        base = os.path.join(RUNS, tid)
        for root, _d, files in os.walk(base):
            for fn in files:
                if not fn.endswith((".json", ".jsonl")):
                    continue
                p = os.path.join(root, fn)
                try:
                    if fn.endswith(".jsonl"):
                        with open(p, encoding="utf-8", errors="ignore") as f:
                            for ln in f:
                                try:
                                    _walk_keys(json.loads(ln), out, scene)
                                except Exception:                             # noqa: BLE001
                                    pass
                    else:
                        with open(p, encoding="utf-8", errors="ignore") as f:
                            _walk_keys(json.load(f), out, scene)
                except Exception:                                             # noqa: BLE001
                    continue
    return out


def _walk_keys(obj, acc: dict, scene: str, depth: int = 0):
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.setdefault(str(k), scene)
            _walk_keys(v, acc, scene, depth + 1)
    elif isinstance(obj, list) and obj:
        _walk_keys(obj[0], acc, scene, depth + 1)


def _node_signal_tags(universe) -> dict:
    """按**任务启用的节点名**给信号打标 —— 信号名的既有约定是 `节点名.字段`(如 光学质量检测.判决)。

    证据链: config/ss_task_binding.json 每任务的 enabled_nodes(真源) → 画布节点 id→name → 前缀匹配。
    这样"每个场景对应不同的信号集合"是**按真实配置推出来的**, 不是我拍脑袋分类; 推不出来的一律白。
    """
    out = {}
    try:
        with open(os.path.join(ROOT, "config", "ss_task_binding.json"), encoding="utf-8") as f:
            b = json.load(f)
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.engineering import flows
        d, _e = flows.load_canvas()
        id2name = {str(n.get("id")): str(n.get("name") or "") for n in (d.get("nodes") or [])}
    except Exception:                                                         # noqa: BLE001
        return out
    for t in (b.get("tasks") or []):
        scene = (TASK_SCENE.get(t.get("task_id")) or {}).get("scene")
        if not scene:
            continue
        for nid in (t.get("enabled_nodes") or []):
            nm = (id2name.get(str(nid)) or "").strip()
            if not nm or len(nm) < 2:
                continue
            # 节点名常带 emoji/括号说明(如 "🔍 光学质量检测 (金手指…)"); 信号名只取主名 ⇒ 归一后再前缀匹配
            import re as _re
            core = nm.split("(")[0].split("（")[0].strip()
            core = _re.sub(r"[^\w\u4e00-\u9fff]", "", core)
            if len(core) < 2:
                continue
            for sig in universe:
                bare = sig[3:] if sig.startswith("ar.") else sig
                if bare.startswith(core + ".") and sig not in out:
                    out[sig] = scene
    return out


# ── 场景专属关键词表 (2026-10-12 老倪: 「插拔信号绿色; 摆盘信号蓝色; AOI信号紫色」) ──
#  依据 = **各场景自己定义原文里的对象/步骤**(真源 flows/scenes_5jobs.json, 下面每条括注出处),
#  不是拍脑袋: 只有出现在场景定义里的词才算该场景的信号; 两边都沾(如 光模块/料盘/夹爪共用词)一律不猜 ⇒ 留白。
SCENE_KEYWORDS = {
    "插拔场景": {   # SCN-01-FW「FW Loading + EEPROM 写/读校验」: 力控拉出/夹爪夹持/对位/插入/固件校验
        "孔", "插入", "插拔", "力控", "夹爪", "夹持", "接触", "对位", "固件", "eeprom", "qsfp", "pull", "ins",
    },
    "摆盘场景": {   # SCN-06-TRAY「光模块摆盘 (周转盘 → 上料 Tray 盘)」: 周转盘/上料/下料/取件/槽位 · 目标「单颗CT/取放精度」
        "真空", "吸盘", "周转盘", "料盘", "槽位", "放置", "取件", "上料", "下料", "摆盘", "takt", "vac", "place", "tray",
    },
    "AR场景": {     # SCN-07-AOI「AR 光学质量检测 (AOI 联合检查)」: 光学质量/判决/金手指/侧面观察/取像/像素坐标/倾角
        "aoi", "光学", "金手指", "表面", "判决", "缺陷", "划伤", "污点", "清晰度", "灰度", "边缘占比", "取像", "倾角",
    },
}
# 共用词: 只有信号名里**除了这些词之外没有任何场景专属词**时才算不猜(留白)。
#   ⚠️ 不能拿"光模块"当一票否决 ——「光模块头到孔_mm」是插拔专属(孔), 之前一否决就被错留白了。
_AMBIGUOUS = ("夹爪",)


def _keyword_tags(universe) -> dict:
    """按场景定义里的专属关键词给信号打标; 命中多个场景或命中共用词 ⇒ 不打标(白)。"""
    out = {}
    for sig in universe:
        _s = (sig[3:] if str(sig).startswith("ar.") else str(sig)).lower()
        if any(w in _s for w in _AMBIGUOUS):
            continue
        _hit = [sc for sc, kws in SCENE_KEYWORDS.items() if any(k in _s for k in kws)]
        if len(_hit) == 1:
            out[sig] = _hit[0]
    return out


def _live_universe() -> set:
    """现场信号名全集 —— 从 zmax_data/ss_live/*.json 递归取键(等价信号分析窗口里会出现的那批),
    这样「按场景关键词打标」是在**真实信号名**上算的, 不是在想象中的名字上算的。"""
    import glob as _glob
    out = set()
    for p in _glob.glob(os.path.join(ROOT, "zmax_data", "ss_live", "*.json")):
        try:
            if os.path.getsize(p) > 3_000_000:
                continue
            with open(p, encoding="utf-8") as f:
                _acc = {}
                _walk_keys(json.load(f), _acc, "", 0)      # 注意: _walk_keys 收 dict(setdefault), 不是 set
                out |= set(_acc.keys())
        except Exception:                                                     # noqa: BLE001
            continue
    return out


def _source_scenes() -> dict:
    """来源族 → 场景 (2026-10-12 老倪: 「之前说的, 绿色topic是插拔任务, 你怎么没有将topic设置成绿色的?」)

    证据链(**不是拍脑袋分类**, 每一条都能复核):
      · `sstrace.*` = 状态空间引擎轨迹快照 (zmax_data/ss_live/trace_live.json), 由**画布数据源那一个场景**
        的这一次运行写出 —— 画布数据源真源 = `tools/ss_scene_switch.now()['src_state']`。
      · `ros./robot/force_torque.*` · `ros./gripper_pos.*` = 力控插入/夹持专用话题, 插拔链独用
        (摆盘走真空吸盘、AR 走 AOI 取像)。
      · `ros./robot/tcp_pose.*` = 真机末端位姿, 三个场景共用的平台量 ⇒ **留白**(要它绿就写进 overrides)。
    """
    out = {}
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import ss_scene_switch as _ssw
        sc = (_ssw.now() or {}).get("src_state") or ""
        if sc in SCENES:
            out["sstrace."] = sc
            out["ros./robot/force_torque"] = sc
            out["ros./gripper_pos"] = sc
    except Exception:                                                         # noqa: BLE001
        pass
    return out


def build(from_runs: bool = False) -> dict:
    """生成注册表: AR/AOI(紫) + 运行证据 + overrides。返回统计。"""
    reg = _registry()
    overrides = dict(reg.get("overrides") or {})
    sig = {}
    universe = set(_ar_signals().keys()) | set("ar." + k for k in _ar_signals().keys())
    universe |= _live_universe()            # 现场信号名(等价于信号分析窗口里会出现的那批)
    try:
        with open(OUT, encoding="utf-8") as f:      # 旧注册表里的名字也别丢
            universe |= set((json.load(f).get("signals") or {}).keys())
    except Exception:                                                         # noqa: BLE001
        pass
    src_scenes = _source_scenes()      # 来源族铺底(逐信号规则可覆盖)
    for _k in universe:
        for _pre, _sc in sorted(src_scenes.items(), key=lambda x: -len(x[0])):
            if str(_k).startswith(_pre):
                sig[_k] = _sc
                break
    for k, sc in _node_signal_tags(universe).items():
        sig[k] = sc
    for k, sc in _keyword_tags(universe).items():       # 场景专属关键词(证据=场景定义原文)
        sig[k] = sc
    for k in _ar_signals():
        sig[k] = "AR场景"
        sig["ar." + k] = "AR场景"          # 页面里 AR 信号带 ar. 前缀(来源前缀), 两种写法都认
    n_runs = 0
    if from_runs:
        for k, sc in _run_signals().items():
            if k not in sig:
                sig[k] = sc
                n_runs += 1
    for k, sc in overrides.items():        # 人工补充优先级最高
        sig[str(k)] = str(sc)
    doc = {"schema": 1,
           "note": "信号→目标场景 标签真源 (signal→scene)。颜色/任务映射见 tools/ss_scene_switch.py; 未列出的 = 白(未分类)。",
           "scenes": scenes_payload(),
           "colors": {"插拔场景": SCENE_COLOR.get("插拔场景"), "摆盘场景": SCENE_COLOR.get("摆盘场景"),
                      "AR场景": SCENE_COLOR.get("AR场景"), "未分类": WHITE},
           "rules": {"AR场景": ["ar.*", "AR/AOI 注册表组内信号 (config/topics/ar_aoi_signals.json)"],
                     "插拔场景": ["TASK-01-FW 运行产物里出现过的信号",
                                  "来源族 sstrace.* (引擎轨迹快照=画布数据源场景那一次运行)",
                                  "ros./robot/force_torque.* · ros./gripper_pos.* (力控插入/夹持专用)"],
                     "摆盘场景": ["TASK-06-TRAY 运行产物里出现过的信号"],
                     "未分类": ["其余一律白 (含三场景共用的 ros./robot/tcp_pose.*); 排序选『白』= 全部显示"]},
           "source_scenes": src_scenes,
           "signals": dict(sorted(sig.items())),
           "overrides": overrides,
           "counts": _counts(sig)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    doc["_n_from_runs"] = n_runs
    return doc


def _counts(sig: dict) -> dict:
    c = {s: 0 for s in SCENES}
    c["未分类"] = 0
    for _k, sc in sig.items():
        c[sc if sc in c else "未分类"] = c.get(sc if sc in c else "未分类", 0) + 1
    return c


def tag(key: str) -> str:
    """信号名(带或不带来源前缀) → 场景名; 没有分类的返回 '' (UI 按白处理)。"""
    reg = _registry()
    sig = reg.get("signals") or {}
    k = str(key or "")
    if k in sig:
        return sig[k]
    # 来源前缀层: 窗口里的键可能带 ar./sstrace./host./ros./catalog. 等前缀, 逐个剥再查
    _cand = [k]
    _parts = k.split(".")
    for _i in range(1, min(3, len(_parts))):
        _cand.append(".".join(_parts[_i:]))
    for _b in _cand:
        if _b in sig:
            return sig[_b]
    for _pre in sorted((reg.get("source_scenes") or {}), key=len, reverse=True):
        if k.startswith(_pre):
            return (reg.get("source_scenes") or {})[_pre]
    bare = k.split(".", 1)[1] if k.startswith("ar.") else k
    if k.startswith("ar.") or bare.startswith("光学质量检测.") or bare.startswith("AOI."):
        return "AR场景"                    # AR/AOI 前缀兜底: 注册表没刷也认得(照实标场景, 不丢颜色)
    return ""


def color(key: str) -> str:
    sc = tag(key)
    return SCENE_COLOR.get(sc, WHITE) if sc else WHITE


def summary() -> dict:
    reg = _registry()
    sig = reg.get("signals") or {}
    live = {}
    try:
        p = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
        with open(p, encoding="utf-8") as f:
            live = json.load(f)
    except Exception:                                                         # noqa: BLE001
        live = {}
    live_keys = [k for k in (live.get("signals") or live).keys()] if live else []
    return {"scenes": scenes_payload(), "colors": reg.get("colors") or {},
            "counts": reg.get("counts") or _counts(sig),
            "registry_signals": len(sig), "live_keys": len(live_keys),
            "registry": os.path.relpath(OUT, ROOT)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--from-runs", action="store_true", help="同时扫 task_runs 的运行证据")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.build:
        d = build(from_runs=a.from_runs)
        print("✅ 写 %s · 信号标签 %d 条 · 各场景: %s (运行证据新增 %d)"
              % (os.path.relpath(OUT, ROOT), len(d["signals"]), d["counts"], d.get("_n_from_runs", 0)))
        for s in scenes_payload():
            print("   %s %s → %s" % ("🟢🔵🟣"[["插拔场景", "摆盘场景", "AR场景"].index(s["scene"])], s["scene"], s["color"]))
        return 0
    if a.tag:
        print("%s → %r (色 %s)" % (a.tag, tag(a.tag), color(a.tag)))
        return 0
    s = summary()
    print("信号→场景 标签 (真源 %s)" % s["registry"])
    for x in s["scenes"]:
        print("   %-8s %-12s %s" % (x["scene"], x["label"], x["color"]))
    print("   计数: %s" % s["counts"])
    print("   注册表信号 %d 条 · AR live 文件键 %d 个" % (s["registry_signals"], s["live_keys"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
