# -*- coding: utf-8 -*-
"""🧩 插拔全流程规划 · **L2 Plan 节点本体** (2026-10-28 从 tools/sim_insert_plan.py 迁入)

老倪: 「所有层的所有节点，要真正的状态空间代码执行」「从 L2 的 plan 节点开始逐个替换」
  ⇒ 段表不再由 tools 脚本生成后喂给节点; 节点(ssplan → plan_long_impl)自己算。
  tools/sim_insert_plan.py 现在只是薄壳 CLI (`from ...cycle_plan import build, write`) 用于出盘/对拍。

口径(未变, 保证与当前 AR 动画一致):
  4 孔沿 +Y 并排(间距 60mm), 插入 +X 47mm; 批对交替: 一对插、一对拔;
  R1 插孔1,2 → R2 插3,4 拔1,2 → ... → R8 只拔最后一对; 14 模块各走 AOI + 落盘。
  节拍由机械手速度决定(本版不插固定等待), 稳态 %.2fs/个 ⇒ 约 314 个/h > 300 目标。

点位真源: config/points/cell_points.json (frame=sim_base, mm)。读不到就抛, 不用旧常量兜底。
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))   # ~/zmax
OUT = os.environ.get("ZMAX_SI_OUT") or os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_insert.json")

# ── 点位真源 = 工程配置 (2026-10-28 老倪: 槽位/孔位必须从配置读, 代码里不许再留常量) ──
#    config/points/cell_points.json   (frame=sim_base, 单位 mm)
#    改一个槽位 → 重新跑本脚本 → 段表对应段跟着变; 读不到配置就退出, 不用旧常量兜底。
POINTS_PATH = os.environ.get("ZMAX_CELL_POINTS") or os.path.join(
    REPO, "config", "points", "cell_points.json")
try:
    _CFG = json.load(open(POINTS_PATH, encoding="utf-8"))
except Exception as _e:                                                     # noqa: BLE001
    raise SystemExit("❌ 点位配置读不到: %s (%s: %s) —— 拒绝用代码里的旧常量兜底"
                     % (POINTS_PATH, type(_e).__name__, _e))

SLOTS = [(s["name"], [float(v) for v in s["pos"]]) for s in _CFG["slots"]]
HOLES = [{"id": int(h["id"]), "name": h["name"],
          "mouth": [float(v) for v in h["mouth"]],
          "insert": [float(v) for v in h["insert"]]} for h in _CFG["holes"]]
DEVICE_BOX = tuple(float(v) for v in _CFG["device_box_mm"])      # x1,y1,x2,y2 (mm)
PITCH = -abs(float(_CFG.get("hole_pitch_mm") or 60))
Y0 = float(HOLES[0]["mouth"][1])
HALF_W = float((_CFG.get("layout") or {}).get("half_w_mm") or 7.2)


def _inside_device(h):
    x1, y1, x2, y2 = DEVICE_BOX
    return (x1 <= h["mouth"][0] and h["insert"][0] <= x2
            and y1 <= h["mouth"][1] - HALF_W and h["mouth"][1] + HALF_W <= y2)


for _h in HOLES:
    assert _inside_device(_h), "孔%d 超出检测设备边框: %s" % (_h["id"], _h["mouth"])

GOLDEN = [float(v) for v in _CFG["golden"]]
SIDES = [(s["name"], [float(v) for v in s["pos"]]) for s in _CFG["sides"]]
SCRAP = [[float(v) for v in s["pos"]] for s in _CFG["scrap"]]
_L = _CFG.get("layout") or {}
DY_LOWER = float(_L["dy_lower_mm"])
LIFT = float(_L["lift_mm"])
TRAV_Z = float(_L["trav_z_mm"])
NG_SPEC = {4: ("golden", "金手指 NG"), 11: ("side2", "侧面点2 NG(上下两面)")}
# 0 = 不压缩(正常按速度算); 仅做"假如总时间 X 秒"的对照时才给非 0
T_TARGET = float(os.environ.get("ZMAX_R_TACT", "0"))
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


def cfg_sha():
    """点位配置指纹 —— 用来判"磁盘段表还是不是这份配置算出来的"。"""
    import hashlib
    try:
        raw = open(POINTS_PATH, "rb").read()
    except OSError:
        return ""
    return hashlib.sha1(raw).hexdigest()[:12]


def write(out=None, path=None):
    """把段表落到磁盘 (工具/对拍用; 节点自算不依赖它)。"""
    out = out if out is not None else build()
    out["cfg_sha"] = cfg_sha()
    pth = path or OUT
    os.makedirs(os.path.dirname(pth), exist_ok=True)
    with open(pth, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return pth


def build():
    """🧩 L2 Plan 节点本体: 从工程配置算出整轮插拔段表 (纯计算, 不写盘/不下发)."""
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
        "cfg_sha": cfg_sha(),
    }
    return out
