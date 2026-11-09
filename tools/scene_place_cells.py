#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景位置细胞运行时 —— L2 记忆库的「位置细胞」层(给检测/规划查"这是哪儿")。

老倪 2026-11-09: 「L2 层的记忆库, 要记录所有这些位置信息, 与大脑神经元的位置细胞同样作用」。

数据: data/skills/l2_atomic/place_cells.json (由 tools/scene_places_build.py 从测量真源生成, 禁手改)
本模块只读 + 只算, 不下发任何动作; 口径全部 base_link / mm。

对外三件事:
  fire(p_mm)     一个 3D 点 → 哪些细胞在发放(高斯场, 距离/自身尺度), 像位置细胞的空间发放曲线
  contains(p_mm) 点落在哪个盒体里(料盘/槽/插孔/工装) —— 用于"模块在4号槽"这类占位判断
  anchor(p_mm)   L2 定位口径: 归属细胞 + 属于哪个料盘 + 第几槽 + 该槽的抓取位姿(号位) + 插孔位姿

用法:
  python3 tools/scene_place_cells.py selftest
  python3 tools/scene_place_cells.py fire 516,347,109
  python3 tools/scene_place_cells.py anchor 516,347,109
  python3 tools/scene_place_cells.py list slot

代码里:
  from scene_place_cells import fire, contains, anchor
"""
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(REPO, "data", "skills", "l2_atomic", "place_cells.json")
_CACHE = {"mtime": None, "doc": None}


def load(path=None, reload=False):
    p = path or PATH
    mt = os.path.getmtime(p)
    if reload or _CACHE["doc"] is None or _CACHE["mtime"] != mt or _CACHE.get("path") != p:
        with open(p, encoding="utf-8") as f:
            _CACHE["doc"] = json.load(f)
        _CACHE["mtime"], _CACHE["path"] = mt, p
    return _CACHE["doc"]


def cells(kind=None, tag=None, path=None):
    out = []
    for c in load(path)["cells"]:
        if kind and c.get("kind") != kind and not str(c.get("kind", "")).startswith(kind + "."):
            continue
        if tag and tag not in (c.get("tags") or []):
            continue
        out.append(c)
    return out


def by_id(cid, path=None):
    for c in load(path)["cells"]:
        if c["id"] == cid:
            return c
    return None


def by_name(name, path=None):
    for c in load(path)["cells"]:
        if c.get("name") == name:
            return c
    return None


def _dist(a, b):
    return math.sqrt(sum((float(a[k]) - float(b[k])) ** 2 for k in range(3)))


def radius_mm(c, floor=20.0):
    """细胞的空间尺度: 盒体=半对角线(它"管"的空间有多大) · 点=floor(示教点本身没有体积)。"""
    s = c.get("size_mm")
    if s and all(isinstance(v, (int, float)) for v in s) and max(s) > 0:
        r = 0.5 * math.sqrt(sum(float(v) ** 2 for v in s))
        return max(r, floor)
    return floor


def fire(p_mm, k=5, kinds=None, path=None):
    """位置细胞的发放: w = exp(-½·(d/r)²), r = 该细胞自身尺度。返回 [(cell, d_mm, w)] 降序。

    口径: 不是"最近的一个点", 而是一组细胞同时按距离衰减发放 —— 同盘邻槽/插孔会一起亮,
    这样 L2 拿到一个像素反投影点也能看出"它在 4 号槽附近, 但离 3 号槽也不远"。
    """
    res = []
    for c in load(path)["cells"]:
        if not c.get("pos_mm") or any(v is None for v in c["pos_mm"]):
            continue
        if kinds and c.get("kind") not in kinds:
            continue
        d = _dist(p_mm, c["pos_mm"])
        r = radius_mm(c)
        res.append((c, round(d, 1), round(math.exp(-0.5 * (d / r) ** 2), 4)))
    res.sort(key=lambda t: (-t[2], t[1]))
    return res[:k]


def contains(p_mm, tol=0.0, path=None):
    """点落在哪些盒体细胞里(含 tol 余量)。返回 [(cell, 到盒面的最大越界量 mm)]。"""
    out = []
    for c in load(path)["cells"]:
        s, pos = c.get("size_mm"), c.get("pos_mm")
        if c.get("shape") != "box" or not s or not pos or any(v is None for v in pos + s):
            continue
        over = max(0.0, max(abs(float(p_mm[k]) - float(pos[k])) - (float(s[k]) / 2.0 + tol) for k in range(3)))
        if over <= 0:
            out.append((c, 0.0))
        elif over <= tol:
            out.append((c, round(over, 1)))
    return out


def slot_of(p_mm, k=1, path=None):
    """最近的槽(位置细胞里的 slot 类), 返回 [(slot, d_mm, w)]。"""
    return fire(p_mm, k=k, kinds={"slot"}, path=path)


def grasp_pose_for(cell, path=None):
    """槽 → 该槽的抓取位姿(示教号位)。

    口径(实测): 只有**右盘 1~7 号位**有示教抓取位姿; 左盘/下盘/废料盘零示教 ⇒ 必须返回 None,
    不许拿同名 slotN 顶替 —— 曾经因此把「下槽3」答成右盘 slot3 的 648,407,108(错 200mm)。
    """
    if isinstance(cell, str):
        cell = by_id(cell, path) or by_name(cell, path)
    if not cell:
        return None
    if cell.get("kind") == "approach_pose":
        return cell
    if cell.get("kind") != "slot":
        return None
    parent = cell.get("parent")
    if parent != "cell.tray.right":
        return None
    num = cell["id"].rsplit("slot", 1)[-1]
    if not num.isdigit():
        return None
    pose = by_name("slot%s" % num, path)
    return pose if pose and pose.get("parent") == parent else None


def insert_poses(path=None):
    """插孔相关示教位姿(口/到位)。"""
    return {"mouth": by_name("光模块插入口", path), "deep": by_name("光模块插入点", path),
            "socket": by_id("cell.socket.optical", path)}


def anchor(p_mm, path=None):
    """L2 定位口径: 一个 3D 点 → 归属细胞/料盘/槽号/抓取位姿/插孔距离。

    返回 dict: cell(最强发放的细胞) · inside(包住它的盒体名) · tray · slot · slot_d_mm ·
              grasp(该槽的抓取位姿名+mm) · socket_d_mm · note
    """
    f = fire(p_mm, k=6, path=path)
    inside = contains(p_mm, path=path)
    inside.sort(key=lambda t: -radius_mm(t[0]))
    top = f[0][0] if f else None
    tray = next((c for c, _ in inside if c.get("kind") == "tray"), None)
    if tray is None and top is not None:
        tray = by_id(top.get("parent") or "", path)
    slot = slot_of(p_mm, k=1, path=path)
    slot, slot_d = (slot[0][0], slot[0][1]) if slot else (None, None)
    grasp = grasp_pose_for(slot or top, path=path) if (slot or top) else None
    ip = insert_poses(path).get("mouth")
    return {
        "p_mm": [round(float(v), 1) for v in p_mm],
        "cell": top and {"id": top["id"], "name": top["name"], "kind": top["kind"]},
        "inside": [{"id": c["id"], "name": c["name"], "kind": c["kind"]} for c, _ in inside[:4]],
        "tray": tray and tray["id"],
        "slot": slot and {"id": slot["id"], "name": slot["name"], "d_mm": slot_d},
        "grasp": grasp and {"name": grasp["name"], "pos_mm": grasp["pos_mm"]},
        "socket_d_mm": round(_dist(p_mm, ip["pos_mm"]), 1) if ip and ip.get("pos_mm") else None,
    }


# ─────────────────────────────── 自检(硬判据) ───────────────────────────────
def selftest(verbose=True):
    doc = load(reload=True)
    ok, fails = [], []

    def chk(cid, cond, detail):
        (ok if cond else fails).append((cid, detail))

    chk("cells.total", doc["total"] >= 100, "细胞 %d 枚 · %d 类" % (doc["total"], len(doc["counts"])))
    chk("cells.checks", all(c["ok"] for c in doc["checks"]) and len(doc["checks"]) >= 5,
        "构建期对拍 %d 条全过" % len(doc["checks"]))

    # 1) 仿真光模块(基座系 [518.8,347.8,112.1]) → 必在右料盘盒内, 最近槽=槽4
    gm = [518.8, 347.8, 112.1]
    ins = [c["id"] for c, _ in contains(gm)]
    s = slot_of(gm, k=1)
    chk("fire.module_in_tray", "cell.tray.right" in ins, "仿真模块落在 %s" % (ins or "无盒体"))
    chk("fire.module_slot", bool(s) and s[0][0]["name"] == "槽4",
        "最近槽 = %s (%.1fmm)" % (s[0][0]["name"], s[0][1]) if s else "无槽")
    a = anchor(gm)
    chk("anchor.grasp_exists", bool(a["grasp"]), "模块 → 抓取位姿 %s mm" % (
        (a["grasp"] or {}).get("pos_mm")))

    # 2) 插孔 [790.5,228,278] → 插孔细胞, 且示教口/到位与围栏一致
    ip = insert_poses()
    sk = ip["socket"]
    f = fire(sk["pos_mm"], k=1)
    chk("fire.socket_top", f[0][0]["id"] == "cell.socket.optical", "插孔点最强发放 = %s" % f[0][0]["id"])
    chk("socket.mouth_present", ip["mouth"] is not None and ip["deep"] is not None,
        "示教口 %s / 到位 %s" % ((ip["mouth"] or {}).get("pos_mm"), (ip["deep"] or {}).get("pos_mm")))

    # 3) 号位-槽 偏移一致性(号位是抓取位姿, 不是槽中心; 7 个号位必须同向同量)
    offs = []
    for n in range(1, 8):
        p, g = by_name("slot%d" % n), by_id("cell.tray.right.slot%d" % n)
        if p and g:
            offs.append([p["pos_mm"][k] - g["pos_mm"][k] for k in range(3)])
    dev = max(max(abs(o[k] - sum(x[k] for x in offs) / len(offs)) for k in range(3)) for o in offs) if offs else 1e9
    chk("taught.offset_consistent", len(offs) == 7 and dev <= 20,
        "%d 个号位, 偏移最大偏离 %.1fmm(≤20)" % (len(offs), dev))

    # 4) 每个槽都有活着的父料盘
    orphan = [c["id"] for c in cells("slot") if not by_id(c.get("parent") or "")]
    chk("slot.parent_alive", not orphan, "孤儿槽 %s" % (orphan[:3] or "无"))

    # 5) 结构件齐全(箱体/桌/地面/顶视相机) —— 工程配置要"全都在"
    need = {"cell.structure.chassis", "cell.structure.table", "cell.structure.floor", "cell.sensor.top_cam"}
    miss = need - {c["id"] for c in doc["cells"]}
    chk("structure.complete", not miss, "缺 %s" % (miss or "无"))

    # 6) 负控: 无示教的槽必须返回 None(不许拿同名 slotN 顶替) ; 7) 正控: 右盘槽3 → slot3
    a_out = anchor([492, -22, 118])          # 下槽3
    a_r3 = anchor([492, 401, 118])           # 右盘槽3
    chk("anchor.no_fake_grasp", a_out["grasp"] is None,
        "下槽3 抓取位姿 = %s (无示教必须 None)" % ((a_out["grasp"] or {}).get("name")))
    chk("anchor.right_grasp", (a_r3["grasp"] or {}).get("name") == "slot3",
        "右盘槽3 抓取位姿 = %s" % ((a_r3["grasp"] or {}).get("pos_mm")))

    if verbose:
        for cid, d in ok:
            print("  ✅ %-26s %s" % (cid, d))
        for cid, d in fails:
            print("  ❌ %-26s %s" % (cid, d))
        print("自检: %d 过 / %d 失败" % (len(ok), len(fails)))
    return not fails


def _pm(s):
    return [float(x) for x in s.replace(" ", "").split(",")]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "selftest":
        return 0 if selftest() else 1
    if cmd == "list":
        kind = args[1] if len(args) > 1 else None
        for c in cells(kind):
            print("%-34s %-16s %-26s %s" % (c["id"], c["kind"], c["name"], c["pos_mm"]))
        return 0
    if cmd in ("fire", "anchor", "contains"):
        p = _pm(args[1])
        if cmd == "fire":
            for c, d, w in fire(p, k=6):
                print("%-34s %-16s d=%7.1fmm w=%.3f %s" % (c["id"], c["kind"], d, w, c["name"]))
        elif cmd == "anchor":
            print(json.dumps(anchor(p), ensure_ascii=False, indent=1))
        else:
            print([(c["id"], o) for c, o in contains(p)])
        return 0
    print("未知命令: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
