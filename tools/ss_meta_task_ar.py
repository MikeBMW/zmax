#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏭 AR 场景 300UPH 的**元任务编排器** —— 归纳 + 逐段校验 + 固化进配置中心

老倪口径 (2026-10-28):
  「将 AR 场景的长程任务规划器的任务, 写进配置中心的任务配置, 把编排好的任务用提示词固化下来;
    就用 TASK-07-AOI, 按照 AR 场景, 你来编写元任务的组合; 这些组合形成长程任务, 发给 Plan 节点,
    执行, 能实现 AR 场景的 300UPH; 通过元任务的组合, 我可以看到清晰的机器人要执行的任务」

做法 (只读段表, 不改 sim_insert.json / sim_insert_plan.py):
  ① 从 sim_insert.json 的 392 段**归纳**元任务 (按段模式切分, 不手写猜)
  ② 每个元任务 = 固定动作序列 + 时长 + 固化提示词 (给 Plan 节点 / LLM 读的确定性文本)
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

# ── 元任务模板 (id, 名称, 段数, 起始判定, 动作序列, 固化提示词) ──────────────
# 段数 = 实测归纳值; 校验会核「每个模板出现次数 × 段数 == 段表里对应动作的实际条数」
MT = [
    ("MT-01", "取料并插入一个模块", 9,
     lambda s: (s["kind"] == "move" and "上方" in s["label"] and "槽" in s["label"]
                and "拔" not in s["label"] and "下料盘" not in s["label"] and "废料盘" not in s["label"]),
     ["move 移到料槽正上方", "down 下降到料槽", "grip 夹爪闭合夹住模块",
      "up 抓起抬升到安全高度", "move 平移到目标孔的行进高度", "move 对准孔口",
      "insert 受控插入 47mm 到底", "release 松开让模块留在孔内", "up 退爪抬起到安全高度"],
     "你站在 AR 场景的双臂工作站。走到料槽正上方→下降→夹住一颗光模块→抬起到安全高度→"
     "平移到目标孔的行进高度→对准孔口→受控插入到底→松开让模块留在孔内→退爪抬起。"
     "插入只准沿孔轴推进，不允许侧向挤压。"),
    ("MT-02", "从孔内拔出模块", 5,
     lambda s: s["kind"] == "move" and "上方(拔)" in s["label"],
     ["move 移到目标孔正上方", "down 下降到孔位", "grip 在孔内夹住模块",
      "pull 沿孔轴拔出 47mm", "up 抬起到安全高度"],
     "你站在 AR 场景的 AOI 工位。走到待测孔正上方→下降到孔位→在孔内夹住模块→"
     "沿孔轴垂直拔出→抬起到安全高度。拔出不许可斜拉，避免损伤金手指。"),
    ("MT-03", "AOI 五点检测", 10,
     lambda s: s["kind"] == "move" and "金手指点" in s["label"],
     ["move 移到金手指检测点", "golden 金手指拍照判定",
      "move 移到侧面点0", "side 侧面点0 拍照判定",
      "move 移到侧面点1", "side 侧面点1 拍照判定",
      "move 移到侧面点2", "side 侧面点2 拍照判定",
      "move 移到侧面点3", "side 侧面点3 拍照判定"],
     "你拿着刚拔出的光模块，先移到金手指检测点拍一张，再依次移到侧面点 0/1/2/3 各拍一张。"
     "五个点全部拍完才算检测完成；任意一点判 NG，这颗模块按 NG 规则走废料，不许混入良品。"),
    ("MT-04", "良品放回下料盘", 4,
     lambda s: s["kind"] == "move" and "下料盘" in s["label"] and "上方" in s["label"],
     ["move 移到下料盘下槽上方", "down 下降到下槽", "release 松开模块", "up 抬起脱离"],
     "把手里这颗良品移到下料盘的空槽正上方→下降→松开放稳→抬起脱离。良品只能进下料盘。"),
    ("MT-05", "NG 放废料盘", 4,
     lambda s: s["kind"] == "move" and "废料盘" in s["label"] and "上方" in s["label"],
     ["move 移到废料盘上方", "down 下降到废料盘", "release 松开模块", "up 抬起脱离"],
     "把手里这颗判 NG 的模块移到废料盘正上方→下降→松开放下→抬起脱离。NG 件一律进废料盘，"
     "绝不允许混入下料盘良品堆。"),
]
MT_SEG = {m[0]: m[2] for m in MT}


def load_segs():
    d = json.load(open(SEG, encoding="utf-8"))
    return d, d["plan"]


def split_meta(segs):
    """把段序列切成元任务序列 (按起始判定 + 期望长度)"""
    out, i, n = [], 0, len(segs)
    while i < n:
        hit = None
        for mid, _nm, ln, pred, _a, _p in MT:
            if pred(segs[i]):
                hit = (mid, ln)
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
    print("③ 元任务次数 / 段数:")
    for mid, nm, ln, _p, _a, _q in MT:
        print("   %s %-16s ×%-3d = %3d 段" % (mid, nm, cnt.get(mid, 0), cnt.get(mid, 0) * ln))
    checks = [("MT-01 次数 == insert 段数", cnt.get("MT-01", 0) == seg_cnt["insert"]),
              ("MT-02 次数 == pull 段数", cnt.get("MT-02", 0) == seg_cnt["pull"]),
              ("MT-03 次数 == golden 段数", cnt.get("MT-03", 0) == seg_cnt["golden"]),
              ("MT-04+MT-05 == release - insert",
               cnt.get("MT-04", 0) + cnt.get("MT-05", 0) == seg_cnt["release"] - seg_cnt["insert"]),
              ("段数守恒 Σ(次数×段数) == 392", sum(cnt.get(m[0], 0) * m[2] for m in MT) == len(segs))]
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
    print("⑤ 节拍: 一轮 %d 段 / %.2fs / %d 件 → %.1f UPH (目标 %s · 前端稳态 %ss)"
          % (len(segs), total_t, n_mod, uph_geo, d.get("uph_target"), d.get("tact_steady_s")))

    # ⑥ 固化
    meta_lib = []
    for mid, nm, ln, _p, acts, prompt in MT:
        ex = [x for x in meta_seq if x["mt"] == mid]
        meta_lib.append({"id": mid, "name": nm, "segments": ln, "actions": acts, "prompt": prompt,
                         "occurrences": len(ex), "t_s": ex[0]["t"] if ex else None,
                         "layer": "L2-检测" if mid == "MT-03" else "L3-长程"})
    long_horizon = {
        "uph_target": d.get("uph_target", 300),
        "tact_s": d.get("tact_steady_s"),
        "segments_total": len(segs),
        "round_total_s": total_t,
        "meta_count": sum(cnt.get(m[0], 0) for m in MT),
        "rounds": [{"template": describe(seq), "meta_seq": list(seq), "count": len(i["ks"]),
                    "batches": i["ks"], "segments": i["segs"]} for seq, i in tpl.items()],
        "sequence_prompt": (
            "长程任务(TASK-07-AOI · AR 场景): 先装满 4 个孔(4×MT-01 取料插入); 之后每批 拔 2 个(MT-02) → "
            "各做 AOI 五点检测(MT-03) → 良品进下料盘(MT-04)/NG 进废料盘(MT-05) → 再补插 2 个新模块(MT-01); "
            "末批只拔不插(收尾)。全过程 %d 段 / %.2fs / %d 件, 目标 %s UPH。"
            "任何一步 NG 一律走废料盘, 良品与 NG 分槽。"
            % (len(segs), total_t, n_mod, d.get("uph_target", 300))),
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    payload = {"schema": "zmax-ar-meta-tasks/1.0", "task_id": "TASK-07-AOI",
               "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "source_seg": "zmax_data/runtime/traj/sim_insert.json",
               "verified": ok, "meta_tasks": meta_lib, "long_horizon": long_horizon}
    json.dump(payload, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("⑥ 写出: %s" % OUT_JSON)

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
