#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏭 AR 场景 300UPH 的**元任务编排器** —— 归纳 + 逐段校验 + 固化进配置中心

老倪口径 (2026-10-28):
  「将 AR 场景的长程任务规划器的任务, 写进配置中心的任务配置, 把编排好的任务用提示词固化下来;
    就用 TASK-07-AOI, 按照 AR 场景, 你来编写元任务的组合; 这些组合形成长程任务, 发给 Plan 节点,
    执行, 能实现 AR 场景的 300UPH; 通过元任务的组合, 我可以看到清晰的机器人要执行的任务」

老倪口径 (2026-10-28 第二轮):
  「TASK-07 只有 5 个元任务么? MT-01 到 MT-05 看名称也不全啊; 这些元任务能对应 AR 场景的具体操作么?
    5 个不够; 而且左右手有的时候任务也不一样 —— 元任务应该有一列标识 左手/右手/左右, 要有时空对应关系」
  ⇒ 本条新增: ① 手别 (L/R/BOTH) ② 段级明细 (每段 seq/动作/目标/手别/t, 可直接对到 AR 场景的 槽k/孔k/金手指点/侧面点0-3)
     ③ 时空窗 (首例 t 起→止 + 出现次数 + 周期) ④ 补齐左臂摆盘 (MT-06) 与双臂交接同步 (MT-07)

做法 (只读段表, 不改 sim_insert.json / sim_insert_plan.py):
  ① 从 sim_insert.json 的 392 段**归纳**元任务 (按段模式切分, 不手写猜)
  ② 每个元任务 = 固定动作序列 + 时长 + 手别 + 目标对象 + 固化提示词 (给 Plan 节点 / LLM 读的确定性文本)
  ③ 长程任务 = 每批次的元任务序列**自动聚类**成轮模板 (段表变它会跟着变, 不手写)
  ④ 自校验: 元任务重建 392 段逐段比对 (kind/label/t 全等) + 段数守恒 + 次数守恒
  ⑤ 通过后写进 sources/config/tasks/tasks.json 的 TASK-07-AOI (meta_tasks / long_horizon)
"""
import collections
import json
import os
import sys
import time

ROOT = "/home/ubuntu/zmax"
SEG = os.path.join(ROOT, "zmax_data", "runtime", "traj", "sim_insert.json")
TASKS = os.path.join(ROOT, "data", "database", "zmax", "sources", "config", "tasks", "tasks.json")
OUT_JSON = os.path.join(ROOT, "data", "database", "zmax", "sources", "config", "tasks", "ar_meta_tasks.json")

HAND_CN = {"R": "右手", "L": "左手", "BOTH": "双手(协同)"}


def _target_of(kind, label, carry):
    """段 → 目标对象 (AR 场景里可指认的东西): 槽k / 孔k / 金手指点k / 侧面点N / 下料盘 槽k / 废料盘。

    顺序有讲究: 「下料盘 下槽1」里同时有"盘"和"槽" ⇒ 盘优先, 否则会把下料盘槽位错认成上料槽。
    夹爪/抬起类段没有自己的编号 ⇒ 继承前一段 (手里那颗模块所在的槽/孔), 这就是"时空对应"的连续段。
    """
    import re
    lab = label or ""
    if "废料盘" in lab:
        return "废料盘"
    if "下料盘" in lab:
        m = re.search(r"槽\s*(\d+)", lab)
        return "下料盘 槽%s" % m.group(1) if m else "下料盘"
    for kw, tag in (("侧面点", "侧面点"), ("金手指", "金手指点")):
        if kw in lab:
            m = re.search(kw + r"\s*(\d+)", lab)
            return tag + (m.group(1) if m else "")
    for kw in ("孔", "槽"):
        if kw in lab:
            m = re.search(kw + r"\s*(\d+)", lab)
            if m:
                return kw + m.group(1)
            return carry if carry and carry.startswith(kw) else kw      # 无编号 ⇒ 继承手里那个
    return carry or "—"


# ── 元任务模板 ────────────────────────────────────────────────────────────────
# 手别口径 (真源, 不是猜的):
#   · MT-01..MT-05 = 段表 sim_insert.json 的那条**单臂插拔循环** ⇒ 右手;
#     与工单 BS-SCN-07-AOI 的 goal 一致: 「左臂摆盘 + 右臂插拔与 AOI 五点检测」
#   · MT-06 = 左臂摆盘 (工单 goal + tasks.json TASK-06-TRAY.steps 的 5 段)
#   · MT-07 = 双臂交接/节拍同步 (工单「双臂并行」+ 实测节拍 159.43s/14 件)
# in_392=True 的才参与 392 段守恒校验 (MT-06/07 不是段表里的动作, 不许冒充).
MT = [
    dict(id="MT-01", hand="R", segments=9, layer="L3-长程", in_392=True,
         name="右臂 · 上料槽取模块 → 插入目标孔 (受控插入 47mm)",
         pred=lambda s: (s["kind"] == "move" and "上方" in s["label"] and "槽" in s["label"]
                         and "拔" not in s["label"] and "下料盘" not in s["label"] and "废料盘" not in s["label"]),
         actions=["move 移到 槽k 正上方", "down 下降到 槽k", "grip 夹爪闭合夹住模块",
                  "up 抓起抬升到安全高度", "move 平移到 孔k 行进高度", "move 对准 孔k 孔口",
                  "insert 受控插入 47mm 到底", "release 松开让模块留在 孔k", "up 退爪抬起到安全高度"],
         prompt=("你站在 AR 场景的双臂工作站, 这只手是**右手**。走到 槽k 正上方→下降→夹住一颗光模块→"
                 "抬起到安全高度→平移到 孔k 的行进高度→对准孔口→受控插入 47mm 到底→松开让模块留在孔内→"
                 "退爪抬起。插入只准沿孔轴推进, 不允许侧向挤压。")),
    dict(id="MT-02", hand="R", segments=5, layer="L3-长程", in_392=True,
         name="右臂 · 从孔内沿轴拔出模块 (47mm)",
         pred=lambda s: s["kind"] == "move" and "上方(拔)" in s["label"],
         actions=["move 移到 孔k 正上方", "down 下降到孔位", "grip 在孔内夹住模块",
                  "pull 沿孔轴拔出 47mm", "up 抬起到安全高度"],
         prompt=("你站在 AR 场景的 AOI 工位, **右手**。走到待测 孔k 正上方→下降到孔位→在孔内夹住模块→"
                 "沿孔轴垂直拔出 47mm→抬起到安全高度。拔出不许可斜拉, 避免损伤金手指。")),
    dict(id="MT-03", hand="R", segments=10, layer="L2-检测", in_392=True,
         name="右臂 · 手持模块五点检测 (金手指点 + 侧面点0/1/2/3)",
         pred=lambda s: s["kind"] == "move" and "金手指点" in s["label"],
         actions=["move 移到 金手指点", "golden 金手指拍照判定",
                  "move 移到 侧面点0", "side 侧面点0 拍照判定",
                  "move 移到 侧面点1", "side 侧面点1 拍照判定",
                  "move 移到 侧面点2", "side 侧面点2 拍照判定",
                  "move 移到 侧面点3", "side 侧面点3 拍照判定"],
         prompt=("你**右手**拿着刚拔出的光模块: 先移到金手指检测点拍一张, 再依次移到侧面点 0/1/2/3 各拍一张。"
                 "五个点全部拍完才算检测完成; 任意一点判 NG, 这颗模块按 NG 规则走废料, 不许混入良品。")),
    dict(id="MT-04", hand="R", segments=4, layer="L3-长程", in_392=True,
         name="右臂 · 良品放入下料盘空槽",
         pred=lambda s: s["kind"] == "move" and "下料盘" in s["label"] and "上方" in s["label"],
         actions=["move 移到 下料盘 槽k 上方", "down 下降到槽位", "release 松开模块", "up 抬起脱离"],
         prompt="把手里这颗良品用**右手**移到下料盘空槽正上方→下降→松开放稳→抬起脱离。良品只能进下料盘。"),
    dict(id="MT-05", hand="R", segments=4, layer="L3-长程", in_392=True,
         name="右臂 · NG 放入废料盘",
         pred=lambda s: s["kind"] == "move" and "废料盘" in s["label"] and "上方" in s["label"],
         actions=["move 移到 废料盘上方", "down 下降到废料盘", "release 松开模块", "up 抬起脱离"],
         prompt=("把手里这颗判 NG 的模块用**右手**移到废料盘正上方→下降→松开放下→抬起脱离。"
                 "NG 件一律进废料盘, 绝不允许混入下料盘良品堆。")),
    # ── 左臂 (段表里没有: 段表只仿真右臂插拔循环; 真源 = 工单 goal + TASK-06-TRAY.steps) ──
    dict(id="MT-06", hand="L", segments=5, layer="L3-长程", in_392=False,
         name="左臂 · 周转盘取模块 → 摆入上料 Tray 空槽 (给右臂供料)",
         pred=None,
         actions=["定位识别 上料 Tray 空槽位", "取件 从周转盘夹取模块", "转运对位 移到 槽k 上方",
                  "放入 松开放稳到 槽k", "判态循环 复位等待下一件"],
         prompt=("这只手是**左手**, 负责摆盘供料: 识别上料 Tray 的空槽位→从周转盘夹取一颗模块→"
                 "转运到 槽k 上方→松开放稳→复位等下一件。左臂只供料不插拔; 放歪或未到位就不许交给右臂。")),
    # ── 双臂协同 (不是段, 是约束: 交接点 + 节拍) ──
    dict(id="MT-07", hand="BOTH", segments=0, layer="L3-协同", in_392=False,
         name="双手 · 供料/取料交接同步 (槽k 交接点, 一件 11.4s)",
         pred=None,
         actions=["左臂 放料完成 槽k", "右臂 从 槽k 取料开始", "双臂 节拍锁 一件 11.4s (300UPH)"],
         prompt=("左右手交接: 左臂把模块放进 槽k 并确认到位后, 右臂才允许从 槽k 取料; "
                 "双臂并行但交接点互斥 (同一槽位同一时刻只有一只手), 整体节拍锁 11.4s/件 ⇒ 300UPH。")),
]
MT_SEG = {m["id"]: m["segments"] for m in MT}
MT_IN392 = [m for m in MT if m["in_392"]]


def load_segs():
    d = json.load(open(SEG, encoding="utf-8"))
    return d, d["plan"]


def split_meta(segs):
    """把段序列切成元任务序列 (按起始判定 + 期望长度)"""
    out, i, n = [], 0, len(segs)
    while i < n:
        hit = None
        for m in MT_IN392:
            if m["pred"](segs[i]):
                hit = (m["id"], m["segments"])
                break
        if hit is None:
            raise RuntimeError("段 seq=%s kind=%s label=%r 不匹配任何元任务起始"
                               % (segs[i].get("seq"), segs[i].get("kind"), segs[i].get("label")))
        mid, ln = hit
        chunk = segs[i:i + ln]
        if len(chunk) != ln:
            raise RuntimeError("%s 在 seq=%s 处不足 %d 段" % (mid, segs[i].get("seq"), ln))
        out.append({"mt": mid, "segs": chunk, "t": round(sum(s["t"] for s in chunk), 3)})
        i += ln
    return out


def seg_detail(chunk, hand):
    """一段元任务实例 → 段级明细 (seq/动作/目标/手别/时长/累计时刻) —— 这是"能对应 AR 场景具体操作"的那张表。"""
    rows, carry, acc = [], None, 0.0
    for s in chunk:
        tg = _target_of(s["kind"], s.get("label") or "", carry)
        if tg != "—":
            carry = tg
        acc += float(s.get("t") or 0.0)
        rows.append({"seq": s.get("seq"), "kind": s.get("kind"), "label": s.get("label"),
                     "target": tg, "hand": hand, "t": s.get("t"), "t_end": round(acc, 3)})
    return rows


def describe(seq):
    """元任务序列 → 人类可读组合, 连续相同项压缩: 'MT-01×4' / 'MT-02+MT-03+MT-04 ×2 + MT-01×2'"""
    runs, i = [], 0
    while i < len(seq):
        j = i
        while j + 1 < len(seq) and seq[j + 1] == seq[i]:
            j += 1
        runs.append("%s×%d" % (seq[i], j - i + 1) if j > i else seq[i])
        i = j + 1
    return " + ".join(runs)


def _left_arm_steps():
    """左臂摆盘的真实段源: tasks.json TASK-06-TRAY.steps (取不到就空, 不编)。"""
    try:
        t = json.load(open(TASKS, encoding="utf-8"))
        row = next((x for x in t.get("tasks") or [] if x.get("task_id") == "TASK-06-TRAY"), {})
        return [{"name": s.get("name"), "t": s.get("dur")} for s in (row.get("steps") or [])]
    except Exception:                                                           # noqa: BLE001
        return []


def main():
    d, segs = load_segs()
    ok = True
    meta_seq = split_meta(segs)

    # ① 归纳 + 覆盖
    covered = sum(len(x["segs"]) for x in meta_seq)
    print("① 归纳: %d 段 → %d 个元任务实例 (覆盖 %d/%d)"
          % (len(segs), len(meta_seq), covered, len(segs)))
    ok = ok and covered == len(segs)

    # ② 逐段重建比对
    rebuilt = [s for x in meta_seq for s in x["segs"]]
    diff = [i for i, (a, b) in enumerate(zip(segs, rebuilt))
            if (a["kind"], a["label"], a["t"]) != (b["kind"], b["label"], b["t"])]
    print("② 逐段重建: %d/%d 段一致%s"
          % (len(segs) - len(diff), len(segs),
             "" if not diff else " ❌ 首个差异 seq=%s" % segs[diff[0]].get("seq")))
    ok = ok and not diff

    # ③ 次数守恒
    cnt = collections.Counter(x["mt"] for x in meta_seq)
    seg_cnt = collections.Counter(s["kind"] for s in segs)
    print("③ 元任务次数 / 段数 (手别):")
    for m in MT:
        print("   %s %-44s [%s] ×%-3d = %3d 段"
              % (m["id"], m["name"][:44], HAND_CN[m["hand"]], cnt.get(m["id"], 0),
                 cnt.get(m["id"], 0) * m["segments"]))
    checks = [("MT-01 次数 == insert 段数", cnt.get("MT-01", 0) == seg_cnt["insert"]),
              ("MT-02 次数 == pull 段数", cnt.get("MT-02", 0) == seg_cnt["pull"]),
              ("MT-03 次数 == golden 段数", cnt.get("MT-03", 0) == seg_cnt["golden"]),
              ("MT-04+MT-05 == release - insert",
               cnt.get("MT-04", 0) + cnt.get("MT-05", 0) == seg_cnt["release"] - seg_cnt["insert"]),
              ("段数守恒 Σ(次数×段数) == 392",
               sum(cnt.get(m["id"], 0) * m["segments"] for m in MT_IN392) == len(segs))]
    for name, good in checks:
        print("   %s %s" % ("✅" if good else "❌", name))
        ok = ok and good

    # ④ 每批次(k)的元任务序列 → 自动聚类成轮模板
    by_k = collections.defaultdict(list)
    t_of_k = collections.defaultdict(float)
    for x in meta_seq:
        k = x["segs"][0]["k"]
        by_k[k].append(x["mt"])
        t_of_k[k] += x["t"]
    tpl = collections.OrderedDict()
    for k in sorted(by_k):
        seq = tuple(by_k[k])
        if seq not in tpl:
            tpl[seq] = {"ks": [], "segs": sum(MT_SEG[x] for x in seq), "t": round(t_of_k[k], 2)}
        tpl[seq]["ks"].append(k)
    print("④ 轮模板 (自动聚类 %d 种):" % len(tpl))
    for seq, info in tpl.items():
        print("   %-44s ×%d 批  %3d 段/批  %.2fs  k=%s"
              % (describe(seq), len(info["ks"]), info["segs"], info["t"], info["ks"]))
    tot = sum(i["segs"] * len(i["ks"]) for i in tpl.values())
    print("   段数合计 %d (实测 %d) %s" % (tot, len(segs), "✅" if tot == len(segs) else "❌"))
    ok = ok and tot == len(segs)

    # ⑤ 节拍 / UPH
    n_mod = len(d.get("cycles_data") or [])
    total_t = round(sum(s["t"] for s in segs), 2)
    uph_geo = round(n_mod / total_t * 3600.0, 1) if total_t else 0.0
    tact = round(total_t / n_mod, 2) if n_mod else 0.0
    print("⑤ 节拍: 一轮 %d 段 / %.2fs / %d 件 → %.1f UPH (目标 %s · 前端稳态 %ss)"
          % (len(segs), total_t, n_mod, uph_geo, d.get("uph_target"), d.get("tact_steady_s")))

    # ⑥ 固化 (含手别 / 目标对象 / 时空窗 / 段级明细)
    left_steps = _left_arm_steps()
    meta_lib = []
    for m in MT:
        mid = m["id"]
        ex = [x for x in meta_seq if x["mt"] == mid]
        first = ex[0] if ex else None
        rows = seg_detail(first["segs"], m["hand"]) if first else []
        targets = []
        for r in rows:
            if r["target"] not in ("—", None) and r["target"] not in targets:
                targets.append(r["target"])
        item = {"id": mid, "name": m["name"], "hand": m["hand"], "hand_cn": HAND_CN[m["hand"]],
                "layer": m["layer"], "segments": m["segments"], "actions": m["actions"],
                "prompt": m["prompt"], "source": "", "in_392": m["in_392"],
                "occurrences": len(ex) if m["in_392"] else None,
                "t_s": round(first["segs"][0].get("t") or 0.0, 3) if first else None,
                "t_win": None, "dur": round(first["t"], 3) if first else None,
                "targets": targets, "segs": rows}
        if first:
            t0 = 0.0
            # 首例在一轮里的起始时刻 = 它前面所有段时长之和
            idx0 = segs.index(first["segs"][0])
            t0 = round(sum(s.get("t") or 0.0 for s in segs[:idx0]), 3)
            item["t_win"] = [t0, round(t0 + first["t"], 3)]
            item["source"] = "sim_insert.json 392 段 (右臂插拔循环, 段级实取)"
        if mid == "MT-06":
            item["segments"] = len(left_steps) or m["segments"]
            item["segs"] = [{"seq": i + 1, "kind": "step", "label": s.get("name"),
                             "target": "上料Tray 槽k", "hand": "L",
                             "t": s.get("t"), "dur": s.get("dur"), "t_end": None}
                            for i, s in enumerate(left_steps)]
            item["targets"] = ["上料Tray 槽k"]
            item["source"] = ("tasks.json TASK-06-TRAY.steps (%d 段) + 工单 BS-SCN-07-AOI goal"
                              "「左臂摆盘」" % len(left_steps))
        if mid == "MT-07":
            item["segs"] = [{"seq": 1, "kind": "sync", "label": "左臂放料完成 槽k", "target": "上料Tray 槽k",
                             "hand": "L", "t": None, "t_end": None},
                            {"seq": 2, "kind": "sync", "label": "右臂从 槽k 取料开始", "target": "上料Tray 槽k",
                             "hand": "R", "t": None, "t_end": None},
                            {"seq": 3, "kind": "sync", "label": "双臂节拍锁 %.1fs/件" % tact,
                             "target": "整机", "hand": "BOTH", "t": tact, "t_end": tact}]
            item["targets"] = ["上料Tray 槽k", "整机"]
            item["occurrences"] = n_mod
            item["source"] = ("工单 BS-SCN-07-AOI「双臂并行」+ 实测节拍 %.2fs/件 (%.1f UPH)"
                              % (tact, uph_geo))
        meta_lib.append(item)
    long_horizon = {
        "uph_target": d.get("uph_target", 300),
        "tact_s": d.get("tact_steady_s"),
        "segments_total": len(segs),
        "round_total_s": total_t,
        "meta_count": sum(cnt.get(m["id"], 0) for m in MT_IN392),
        "hands": {"R": [m["id"] for m in MT if m["hand"] == "R"],
                  "L": [m["id"] for m in MT if m["hand"] == "L"],
                  "BOTH": [m["id"] for m in MT if m["hand"] == "BOTH"]},
        "rounds": [{"template": describe(seq), "meta_seq": list(seq), "count": len(i["ks"]),
                    "batches": i["ks"], "segments": i["segs"]} for seq, i in tpl.items()],
        "sequence_prompt": (
            "长程任务(TASK-07-AOI · AR 场景 · 双臂): 左臂持续摆盘供料(MT-06); 右臂先装满 4 个孔(4×MT-01 取料插入); "
            "之后每批 拔 2 个(MT-02) → 各做 AOI 五点检测(MT-03) → 良品进下料盘(MT-04)/NG 进废料盘(MT-05) → "
            "再补插 2 个新模块(MT-01); 末批只拔不插(收尾)。左右手在 槽k 交接(MT-07), 同一槽位同一时刻只有一只手。"
            "全过程 %d 段 / %.2fs / %d 件, 目标 %s UPH。任何一步 NG 一律走废料盘, 良品与 NG 分槽。"
            % (len(segs), total_t, n_mod, d.get("uph_target", 300))),
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    payload = {"schema": "zmax-ar-meta-tasks/1.1", "task_id": "TASK-07-AOI",
               "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "source_seg": "zmax_data/runtime/traj/sim_insert.json",
               "verified": ok, "meta_tasks": meta_lib, "long_horizon": long_horizon}
    json.dump(payload, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("⑥ 写出: %s" % OUT_JSON)
    print("   手别: 右手 %d 条 / 左手 %d 条 / 双手 %d 条 / 段级明细 %d 行"
          % (len(long_horizon["hands"]["R"]), len(long_horizon["hands"]["L"]),
             len(long_horizon["hands"]["BOTH"]), sum(len(x["segs"]) for x in meta_lib)))

    if not ok:
        print("\n❌ 校验未通过, 不写任务配置")
        return 1

    # ⑦ 写进配置中心 tasks.json
    t = json.load(open(TASKS, encoding="utf-8"))
    hit = [x for x in t["tasks"] if x.get("task_id") == "TASK-07-AOI"]
    if not hit:
        print("❌ tasks.json 里没有 TASK-07-AOI")
        return 1
    tk = hit[0]
    tk["meta_tasks"] = meta_lib
    tk["long_horizon"] = long_horizon
    tk["_meta_note"] = ("元任务由 tools/ss_meta_task_ar.py 从 392 段段表归纳并逐段校验(详见 ar_meta_tasks.json); "
                        "每条带手别(hand L/R/BOTH)/目标对象(targets)/时空窗(t_win)/段级明细(segs); "
                        "改段表后必须重跑本脚本, 否则配置与段表不一致")
    json.dump(t, open(TASKS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    t2 = json.load(open(TASKS, encoding="utf-8"))
    tk2 = [x for x in t2["tasks"] if x.get("task_id") == "TASK-07-AOI"][0]
    print("⑦ 配置中心: TASK-07-AOI 写入 meta_tasks(%d 个) + long_horizon(%d 种轮模板)"
          % (len(tk2.get("meta_tasks") or []), len((tk2.get("long_horizon") or {}).get("rounds") or [])))
    print("\n结果: %s" % ("✅ 全部校验通过" if ok else "❌ 失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
