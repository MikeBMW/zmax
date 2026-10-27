#!/usr/bin/env python3
"""右臂插拔全流程规划 · 4 插孔 / 1 分钟驻留 / 拔出后 AOI (2026-10-27 改版)

老倪: 「在插孔右边，再增加3个插孔，重新编排插拔流程。插入光模块后有等待时间，1分钟，
      以拔除后再做AOI检查。可以先插入1 2 孔，然后去拔除3 4 孔；再插入3 4 孔，拔除1 2 孔，依次类推」

编排口径
--------
4 个插孔沿 +Y 并排(间距 60mm)，插入方向仍是 +X(入孔 47mm)。
批对交替，一对插、一对拔 —— 驻留时间被另一对的作业吃掉:
    R1: 插孔1,2            → 等够 60s
    R2: 插孔3,4  拔孔1,2   → 孔1,2 驻留 60s；拔出后 AOI(金手指+侧面四面) → 下料/废料
    R3: 插孔1,2  拔孔3,4
    ... 依次类推
    R8: 只有拔(最后一对), 让 14 个模块全部走完 AOI 与落盘。
节拍 = 60s / 2 个 = 30.0 s/个(驻留决定，不是机械手速度决定) ⇒ 120 个/h。
要回到 190 个/h 需 6 个孔(三对交替) —— 本文件顶部 PITCH/HOLES 一行即可加。

输出: zmax_data/runtime/traj/sim_insert.json
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("ZMAX_SI_OUT") or os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_insert.json")

SLOTS = [
    ("槽1",  [490, 499, 118]), ("槽2",  [491, 449, 118]), ("槽3",  [492, 401, 118]),
    ("槽4",  [492, 353, 118]), ("槽5",  [493, 303, 118]), ("槽6",  [492, 255, 118]),
    ("槽7",  [494, 205, 118]), ("槽8",  [617, 501, 118]), ("槽9",  [615, 451, 118]),
    ("槽10", [615, 404, 118]), ("槽11", [618, 355, 118]), ("槽12", [614, 307, 118]),
    ("槽13", [614, 260, 118]), ("槽14", [617, 212, 118]),
]

# ── 4 个插孔: 全部落在「检测设备」柜体内部, 等距 60mm ─────────────────────
# 检测设备 bbox: x 711.7~843.7 · y -91.4~301.6 · z 0~340 (fences.json 真值)
# 老倪: 「4 个插孔应该都在检测设备内部, 等距离排列, 你现在的插孔已经超出边框了」
# 孔1 保留实测插入点(767→814, y=228), 其余 3 个朝 -Y 等距排, 4 孔全在柜内:
#   y = 228 / 168 / 108 / 48   (下沿 48-7.2=40.8 > -91.4 ✓, 上沿 228+7.2=235.2 < 301.6 ✓)
DEVICE_BOX = (711.7, -91.4, 843.7, 301.6)      # x1,y1,x2,y2 (mm)
# 0 = 不压缩(正常按速度算); 仅做"假如总时间 X 秒"的对照时才给非 0
T_TARGET = float(os.environ.get("ZMAX_R_TACT", "0"))
Y0, PITCH = 228, -60                            # 从实测孔位往 -Y 排, 间距 60mm 等距
HOLES = [{"id": i + 1, "name": "孔%d" % (i + 1),
          "mouth": [767, Y0 + i * PITCH, 278],
          "insert": [814, Y0 + i * PITCH, 278]}
         for i in range(4)]
HALF_W = 7.2                                    # 插孔宽 14.4mm 的一半

def _inside_device(h):
    x1, y1, x2, y2 = DEVICE_BOX
    return (x1 <= h["mouth"][0] and h["insert"][0] <= x2
            and y1 <= h["mouth"][1] - HALF_W and h["mouth"][1] + HALF_W <= y2)

for _h in HOLES:
    assert _inside_device(_h), "孔%d 超出检测设备边框: %s" % (_h["id"], _h["mouth"])

GOLDEN = [360, -117, 654]
SIDES = [("侧面点0", [399, -406, 546]), ("侧面点1", [401, -435, 555]),
         ("侧面点2", [384, -434, 551]), ("侧面点3", [408, -408, 569])]
DY_LOWER = -423.4
SCRAP = [[469, -402, 120], [569, -402, 120]]
NG_SPEC = {4: ("golden", "金手指 NG"), 11: ("side2", "侧面点2 NG(上下两面)")}

LIFT, TRAV_Z = 100, 340
TACT_GRIP_EQ = 120          # 夹爪动作折算成等效位移(mm) —— 与左臂同一口径


def left_arm_speed():
    """左臂的等效移动速度(mm/s): 左臂每循环固定 3.0 s(老倪敲定), 循环内等效位移
    = 各段实际位移 + 抓起/放下折 120 mm。右臂末端速度取同一个值 —— 老倪:
    「我说的是右臂末端执行器的移动速度, 与左臂一样, 不是总时间 3 秒」。"""
    try:
        d = json.load(open(os.path.join(REPO, "zmax_data/runtime/traj/sim_transport.json"),
                          encoding="utf-8"))
        byk = {}
        for s in d["segs"]:
            byk.setdefault(s["k"], []).append(s)
        tot, n = 0.0, 0
        for arr in byk.values():
            w = 0.0
            for s in arr:
                dx = s["p_to"][0] - s["p_from"][0]
                dy = s["p_to"][1] - s["p_from"][1]
                dz = s["p_to"][2] - s["p_from"][2]
                dist = (dx * dx + dy * dy + dz * dz) ** 0.5 * 1000.0
                if "抓起" in s.get("label", "") or "放下" in s.get("label", ""):
                    dist += TACT_GRIP_EQ
                w += max(dist, 1.0)
            tot += w
            n += 1
        return (tot / max(1, n)) / 3.0
    except Exception:
        return 200.0


V = float(os.environ.get("ZMAX_R_V") or round(left_arm_speed(), 1))
T_GRIP = float(os.environ.get("ZMAX_R_GRIP") or round(TACT_GRIP_EQ / V, 3))
T_RELEASE = float(os.environ.get("ZMAX_R_REL") or T_GRIP)
T_CHECK_GOLDEN = float(os.environ.get("ZMAX_R_GOLD", 0.8))
T_CHECK_SIDE = float(os.environ.get("ZMAX_R_SIDE", 0.5))
T_DWELL = 60.0          # 插入后驻留(秒) —— 物理工艺要求
MODS_PER_ROUND = 2


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def seg(plan, r, kind, label, a, b, carry_from, carry_to, t=None, check=None,
        mod=None, hole=None, at=None):
    if t is None:
        t = max(0.30, round(dist(a, b) / V, 2))
        t = round(t, 2)
    item = {"k": r, "seq": 1 + sum(1 for p in plan if p["k"] == r), "kind": kind,
            "label": label, "a": [round(v, 1) for v in a], "b": [round(v, 1) for v in b],
            "t": t, "carry_from": carry_from, "carry_to": carry_to}
    if check:
        item["check"] = check
    if mod is not None:
        item["mod"] = mod
    if hole is not None:
        item["hole"] = hole
    if at:
        item["at"] = at
    plan.append(item)


def main():
    plan, rounds, modules = [], [], []
    cur = [490, 499, 240]
    lower_k = scrap_k = 0
    hole_of, target_of, verdict_of = {}, {}, {}

    # 先算每个模块的落点与判定(与插入顺序解耦)
    for i, (name, slot) in enumerate(SLOTS, start=1):
        ng_key, ng_label = NG_SPEC.get(i, (None, None))
        ng = ng_key is not None
        checks = {"golden": "OK", "side0": "OK", "side1": "OK", "side2": "OK", "side3": "OK"}
        if ng:
            checks[ng_key] = "NG"
        if ng:
            target, tkind, tlabel = SCRAP[scrap_k % len(SCRAP)], "scrap", "废料盘(不良品)"
            scrap_k += 1
        else:
            lower_k += 1
            target, tkind, tlabel = [slot[0], round(slot[1] + DY_LOWER, 1), 118], "lower", "下料盘 下槽%d" % lower_k
        target_of[i] = (target, tkind, tlabel)
        verdict_of[i] = dict(verdict="NG" if ng else "OK", fail_reason=ng_label, checks=checks)
        module = dict(k=i, slot_name=name, slot=slot, verdict=verdict_of[i]["verdict"],
                      fail_reason=ng_label, checks=checks, target_kind=tkind,
                      target=target, target_label=tlabel, hole=None,
                      insert_round=None, pull_round=None, dwell_s=T_DWELL)
        modules.append(module)

    def insert_module(r, m, hole):
        name, slot = SLOTS[m - 1][0], SLOTS[m - 1][1]
        above = [slot[0], slot[1], slot[2] + LIFT]
        hz = [hole["mouth"][0], hole["mouth"][1], TRAV_Z]
        seg(plan, r, "move", "→ %s 上方" % name, cur, above, False, False, mod=m)
        seg(plan, r, "down", "下降到 %s" % name, above, slot, False, False, mod=m)
        seg(plan, r, "grip", "夹爪闭合", slot, slot, False, True, t=T_GRIP, mod=m)
        seg(plan, r, "up", "抓起抬起", slot, above, True, True, mod=m)
        seg(plan, r, "move", "→ %s 行进高度" % hole["name"], above, hz, True, True, mod=m, hole=hole["id"])
        seg(plan, r, "move", "→ %s 孔口" % hole["name"],
            hz, hole["mouth"], True, True, mod=m, hole=hole["id"])
        seg(plan, r, "insert", "插入 %s 47mm" % hole["name"],
            hole["mouth"], hole["insert"], True, True, mod=m, hole=hole["id"])
        seg(plan, r, "release", "松开(模块留在 %s)" % hole["name"],
            hole["insert"], hole["insert"], True, False, t=T_RELEASE,
            mod=m, hole=hole["id"], at="hole")
        seg(plan, r, "up", "退爪抬起", hole["insert"],
            [hole["insert"][0], hole["insert"][1], TRAV_Z], False, False, mod=m, hole=hole["id"])

    def pull_module(r, m, hole):
        h, info = hole, modules[m - 1]
        hz = [h["insert"][0], h["insert"][1], TRAV_Z]
        seg(plan, r, "move", "→ %s 上方(拔)" % h["name"], cur, hz, False, False, mod=m, hole=h["id"])
        seg(plan, r, "down", "下降到 %s 孔位" % h["name"],
            hz, [h["insert"][0], h["insert"][1], h["insert"][2]], False, False, mod=m, hole=h["id"])
        seg(plan, r, "grip", "夹住(在孔内)", h["insert"], h["insert"], False, True, t=T_GRIP, mod=m, hole=h["id"])
        seg(plan, r, "pull", "拔出 %s 47mm" % h["name"],
            h["insert"], h["mouth"], True, True, mod=m, hole=h["id"])
        seg(plan, r, "up", "拔出抬起", h["mouth"], [h["mouth"][0], h["mouth"][1], TRAV_Z],
            True, True, mod=m, hole=h["id"])
        # 拔出后 AOI: 金手指 + 侧面四面
        seg(plan, r, "move", "→ 金手指点1",
            [h["mouth"][0], h["mouth"][1], TRAV_Z], GOLDEN, True, True, mod=m)
        seg(plan, r, "golden", "📷 金手指检测(AOI)", GOLDEN, GOLDEN, True, True, t=T_CHECK_GOLDEN,
            check={"kind": "golden", "result": info["checks"]["golden"], "camera": "金手指相机(前方上方)"}, mod=m)
        prev = GOLDEN
        for j, (sname, spos) in enumerate(SIDES):
            seg(plan, r, "move", "→ %s" % sname, prev, spos, True, True, mod=m)
            seg(plan, r, "side", "📷 %s 检测(AOI)" % sname, spos, spos, True, True, t=T_CHECK_SIDE,
                check={"kind": "side", "face": sname, "result": info["checks"]["side%d" % j],
                       "camera": "侧面相机(右侧上方)"}, mod=m)
            prev = spos
        target, _, tlabel = target_of[m]
        tab = [target[0], target[1], target[2] + 80]
        seg(plan, r, "move", "→ %s 上方" % tlabel, prev, tab, True, True, mod=m)
        seg(plan, r, "down", "下降到 %s" % tlabel, tab, target, True, True, mod=m)
        seg(plan, r, "release", "松开", target, target, True, False, t=T_RELEASE, mod=m, at="tray")
        seg(plan, r, "up", "抬起脱离", target, tab, False, False, mod=m)
        return tab

    # ── 4 孔轮转: 先全插满, 之后每阶段「拔一对 → AOI → 插同一对」, 不插等待 ─────
    # 老倪: 「不用等待, 第一次全都依次插入 1 2 3 4, 然后拔除 1 2 → 检测 AOI → 插入 1 2
    #        → 拔除 3 4 → 检测 AOI → 插入 3 4 → 再拔除 1 2 …」
    pair_holes = {1: [HOLES[0], HOLES[1]], 2: [HOLES[2], HOLES[3]]}
    ins_round, pull_round = {}, {}
    queue = list(range(1, len(SLOTS) + 1))
    occupied = {1: [], 2: []}

    # ① 预插: 孔1→2→3→4 依次插满(模块 1~4), 中间不停
    k = 1
    for h in HOLES:
        m = queue.pop(0)
        insert_module(k, m, h)
        ins_round[m] = k
        modules[m - 1]["hole"] = h["id"]
        modules[m - 1]["insert_round"] = k
        occupied[1 if h["id"] <= 2 else 2].append(m)
    t_pre = round(sum(p["t"] for p in plan if p["k"] == k), 2)
    rounds.append(dict(r=k, pair=0, holes=[h["id"] for h in HOLES],
                       insert_mods=[1, 2, 3, 4], pull_mods=[],
                       t_round=t_pre, t_work=t_pre, t_wait=0.0))

    # ② 轮转: 先拔孔1,2 → AOI → 插孔1,2 → 再拔孔3,4 → AOI → 插孔3,4 → …
    pair_turn = 1
    while queue or occupied[1] or occupied[2]:
        k += 1
        pair = pair_turn
        holes = pair_holes[pair]
        pulled = []
        for m, h in zip(list(occupied[pair]), holes):
            pull_module(k, m, h)
            pull_round[m] = k
            modules[m - 1]["pull_round"] = k
            pulled.append(m)
        occupied[pair] = []
        newmods = []
        for h in holes:
            if not queue:
                break                      # 料盘空了就只拔不插(收尾)
            m = queue.pop(0)
            insert_module(k, m, h)
            ins_round[m] = k
            modules[m - 1]["hole"] = h["id"]
            modules[m - 1]["insert_round"] = k
            newmods.append(m)
        occupied[pair] = newmods
        tt = round(sum(p["t"] for p in plan if p["k"] == k), 2)
        rounds.append(dict(r=k, pair=pair, holes=[h["id"] for h in holes],
                           insert_mods=newmods, pull_mods=pulled,
                           t_round=tt, t_work=tt, t_wait=0.0))
        pair_turn = 1 if pair == 2 else 2

    # ── 驻留时长(只测不补): 老倪这版要求「不用等待」, 驻留就是自然值 ──────────
    def measure():
        cum, tt = [], 0.0
        for p in plan:
            cum.append(tt)
            tt += p["t"]
        ii, pp = {}, {}
        for i, p in enumerate(plan):
            if p["kind"] == "release" and p.get("at") == "hole":
                ii[p["mod"]] = cum[i] + p["t"]
            elif p["kind"] == "grip" and p.get("hole"):
                pp[p["mod"]] = cum[i]
        return {m: round(pp[m] - ii[m], 2) for m in ii}

    dwell_final = measure()
    # ── 每模块时间构成: 插入→拔除(在孔) / 拔出后 AOI(纯检测+移动) / 落盘 ────────
    cum2, tt2 = [], 0.0
    for p in plan:
        cum2.append(round(tt2, 3))
        tt2 += p["t"]
    marks = {}
    for i, p in enumerate(plan):
        mk = p.get("mod")
        if not mk:
            continue
        d = marks.setdefault(mk, {})
        if p["kind"] == "release" and p.get("at") == "hole":
            d["t_ins"] = round(cum2[i] + p["t"], 3)
        elif p["kind"] == "grip" and p.get("hole"):
            d["t_pull"] = cum2[i]
        elif p["kind"] in ("golden", "side"):
            d.setdefault("t_aoi0", cum2[i])
            d["t_aoi1"] = round(cum2[i] + p["t"], 3)
            d["aoi_check_s"] = round(d.get("aoi_check_s", 0.0) + p["t"], 3)
        elif p["kind"] == "release" and p.get("at") == "tray":
            d["t_placed"] = round(cum2[i] + p["t"], 3)
    for mod in modules:
        mk = mod["k"]
        d = marks.get(mk, {})
        ins, pull = d.get("t_ins"), d.get("t_pull")
        mod["dwell_s"] = round(pull - ins, 2) if (ins is not None and pull is not None) else 0.0
        a0, a1 = d.get("t_aoi0"), d.get("t_aoi1")
        mod["aoi_s"] = round(a1 - a0, 2) if (a0 is not None and a1 is not None) else 0.0
        mod["aoi_check_s"] = d.get("aoi_check_s", 0.0)          # 纯检测停留
        mod["aoi_move_s"] = round(mod["aoi_s"] - mod["aoi_check_s"], 2)  # 检测点之间移动
        placed = d.get("t_placed")
        mod["place_s"] = round(placed - a1, 2) if (placed is not None and a1 is not None) else 0.0
        mod["t_ins"], mod["t_pull"] = ins, pull
        mod["t_aoi0"], mod["t_aoi1"], mod["t_placed"] = a0, a1, placed
        mod["t_work"] = round(sum(p["t"] for p in plan if p.get("mod") == mk and p["k"] == ins_round[mk]), 2) + \
                        round(sum(p["t"] for p in plan if p.get("mod") == mk and p["k"] == pull_round[mk]), 2)

    # ── 提速到目标节拍: 等比压缩段时长 ────────────────────────────────────────
    # 代价必须明说: 系数同时压掉固定动作(夹爪 0.4/0.35 s)和检测(0.8/0.5 s),
    # 等效臂速会被放大到不现实的量级 —— 这是「目标节拍」口径, 不是真机可达值。
    base_total = round(sum(p["t"] for p in plan), 2)
    k = round((T_TARGET * len(modules)) / base_total, 4) if T_TARGET > 0 else 1.0
    if abs(k - 1.0) > 1e-6:
        for p in plan:
            p["t"] = max(0.01, round(p["t"] * k, 3))
        for rd in rounds:
            rd["t_round"] = round(sum(x["t"] for x in plan if x["k"] == rd["r"]), 2)
            rd["t_work"] = rd["t_round"]
            rd["t_wait"] = 0.0
        dwell_final = measure()
        for mod in modules:
            mk = mod["k"]
            mod["dwell_s"] = dwell_final.get(mk, 0.0)

    total = round(sum(p["t"] for p in plan), 2)
    # 稳态节拍 = 满负荷阶段(拔2+插2)的「时长 ÷ 2 个」
    st = [rd["t_round"] / 2.0 for rd in rounds
          if len(rd["pull_mods"]) == 2 and len(rd["insert_mods"]) == 2]
    steady = round(sorted(st)[len(st) // 2], 2) if st else round(total / len(modules), 2)
    dws = [m["dwell_s"] for m in modules]
    # ── 稳态循环块: 「全流程 UPH」按它无限循环, 每块 mods 件 ────────────────
    steady_rounds = [r for r in rounds if len(r.get("pull_mods") or []) == 2
                     and len(r.get("insert_mods") or []) == 2]
    loop_ks = [r["r"] for r in steady_rounds[:2]] if len(steady_rounds) >= 2 \
              else [r["r"] for r in rounds[1:3]]
    loop_segs = [p for p in plan if p["k"] in loop_ks]
    loop_dur = round(sum(p["t"] for p in loop_segs), 3)
    loop_mods = len([p for p in loop_segs if p["kind"] == "release" and p.get("at") == "tray"])
    loop_block = {"ks": loop_ks, "dur": loop_dur, "mods": loop_mods,
                  "tact_s": round(loop_dur / max(1, loop_mods), 3),
                  "uph": round(3600.0 / (loop_dur / max(1, loop_mods)), 1),
                  "note": "两块相邻稳态轮次可无缝平铺: 每块落盘 %d 件, 首尾四孔占用状态相同" % loop_mods}
    print("  稳态循环块: 轮 %s · %.2fs / %d 件 ⇒ %.2f s/件 · UPH %.0f"
          % (loop_ks, loop_dur, loop_mods, loop_block["tact_s"], loop_block["uph"]))

    out = {
        "ok": True, "cycles": len(rounds), "n_segs": len(plan), "total_t": total,
        "flow": "预插 孔1→2→3→4 → 之后 拔1,2·AOI·插1,2 → 拔3,4·AOI·插3,4 → 循环",
        "dwell_required_s": None,   # 本版不要求固定驻留(老倪: 不用等待)
        "dwell_min_s": min(dws), "dwell_max_s": max(dws),
        "dwell_gate_ok": None,
        "mods": len(modules), "ok_count": sum(1 for m in modules if m["verdict"] == "OK"),
        "ng_count": sum(1 for m in modules if m["verdict"] == "NG"),
        "ng_slots": [m["slot_name"] for m in modules if m["verdict"] == "NG"],
        "ng_reasons": {m["slot_name"]: m["fail_reason"] for m in modules if m["verdict"] == "NG"},
        "src_tray": "黑色料盘(左侧第二个盘) 槽1~14",
        "dst_ok": "下料盘 下槽1~%d" % lower_k, "dst_ng": "废料盘",
        "holes": HOLES, "hole_pitch_mm": abs(PITCH), "dwell_s": None,   # 本版不要求固定驻留
        "device_box_mm": list(DEVICE_BOX),
        "holes_inside_device": all(_inside_device(h) for h in HOLES),
        "mods_per_cycle": MODS_PER_ROUND, "tact_steady_s": steady,
        "loop": loop_block,
        "uph_target": 300,          # 老倪定: UPH 目标 300(不是稳态 314)
        "ng_ratio": 1.0 / 125.0,    # 不良率 0.8% ⇒ 良率 99.2% > 99%(每 125 件 1 件不良)
        "yield_target": 0.99,
        "speed_profile": {"v_mm_s": round(V, 1), "grip_s": T_GRIP, "release_s": T_RELEASE,
                          "check_golden_s": T_CHECK_GOLDEN, "check_side_s": T_CHECK_SIDE,
                          "rule": "右臂末端速度 = 左臂等效速度(左臂每循环 3.0 s · 等效位移 %.1f mm)" % (V * 3.0)},
        "time_scale": k, "base_total_t": base_total,
        "base_tact_s": round(base_total / len(modules), 2), "target_tact_s": T_TARGET,
        "implied_speed_mm_s": round(V / k), "implied_grip_s": round(T_GRIP * k, 3),
        "implied_check_golden_s": round(T_CHECK_GOLDEN * k, 3),
        "implied_check_side_s": round(T_CHECK_SIDE * k, 3),
        "tact_module_s": round(total / len(modules), 2),
        "points": {"prep": [691, 227, 271], "golden": GOLDEN, "sides": [p for _, p in SIDES]},
        "cycles_data": modules, "rounds": rounds, "plan": plan,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("写入", OUT)
    print("  轮次 %d · 模块 %d · 段 %d · 全程 %.1fs · 稳态节拍 %.1f s/个 · 均摊 %.2f s/个"
          % (len(rounds), len(modules), len(plan), total, steady, out["tact_module_s"]))
    print("  驻留(自然值, 不插等待): min %.2fs / max %.2fs" % (out["dwell_min_s"], out["dwell_max_s"]))
    print("  提速: 基准 %.2fs/个(一批 %.1fs) → 目标 %.2fs/个 · 压缩系数 %.4f · 等效臂速 %.0f mm/s · 等效检测 %.2f/%.2f s"
          % (out["base_tact_s"], base_total, out["tact_steady_s"], k,
             out["implied_speed_mm_s"], out["implied_check_golden_s"], out["implied_check_side_s"]))
    x1, y1, x2, y2 = DEVICE_BOX
    print("  4 孔 y = %s · 等距 %dmm · 全在检测设备内: %s (柜 y %.1f~%.1f)"
          % ("/".join(str(h["mouth"][1]) for h in HOLES), abs(PITCH),
             out["holes_inside_device"], y1, y2))
    for rd in rounds:
        print("   R%-2d 孔%-6s 插 %-10s 拔 %-10s 作业 %5.1fs 等待 %5.1fs"
              % (rd["r"], str(rd["holes"]), str(rd["insert_mods"]), str(rd["pull_mods"]),
                 rd["t_work"], rd["t_wait"]))
    dws2 = [m["dwell_s"] for m in modules]
    aois = [m["aoi_s"] for m in modules]
    print("  在孔(插入→拔除): %.1f~%.1f s · AOI(含移动): %.2f~%.2f s (纯检测 %.2f s) · 落盘 %.2f s"
          % (min(dws2), max(dws2), min(aois), max(aois),
             modules[0]["aoi_check_s"], modules[0]["place_s"]))
    for m in modules:
        print("   %2d %-6s → %-6s 插R%d 拔R%d 驻留 %.0fs %s → %s"
              % (m["k"], m["slot_name"], "孔%d" % m["hole"], m["insert_round"], m["pull_round"],
                 m["dwell_s"], m["verdict"], m["target_label"]))


if __name__ == "__main__":
    main()