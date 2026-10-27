# -*- coding: utf-8 -*-
"""traj_from_named.py —— 把「页面上高亮的命名轨迹」变成**可执行的段表**

老倪 2026-10-26:
「我看你现在的逻辑是，蓝色高亮表示显示，黑色表示不显示对不？那就点击轨迹按钮，
  高亮成蓝色按钮是，就在三维空间中显示对应的轨迹，我看着，然后点击执行就可以发出指令了。」

问题(改之前是真的): 页面上『▶ 执行轨迹』执行的是 **规划航路** (traj_plan.py 的
planned_traj.json), 跟你在三维视图里看到的那条命名轨迹(小红/正方/建图/安全/实时)
**根本不是同一条**。看着小红、按下执行, 机器走的是别的路 —— 这是最危险的那种"不一致"。

本文件做的就是把这条链补上:
  命名轨迹点(41/54/21 个) → RDP 抽骨架 → 每两个骨架点之间拆成轴对齐段
  (先 Z, 再 X, 再 Y; 单段 ≤ 300mm, 与 registry 上限同口径)
  → 逐点净空预检(复用 traj_plan.precheck_point, 门槛 20mm)
  → 写 planned_traj.json (执行器读的那份) + plan_latest.json (550C 桥读的那份)
  → 画到 overlay_spec (页面能看见)
起点闸: 真机当前 TCP 必须离轨迹首点 ≤ 20mm, 否则拒绝(不许"从老远的地方飞过去")。

用法:
  python tools/traj_from_named.py --k xiaohong            # 小红 → 段表(可执行)
  python tools/traj_from_named.py --k map --force        # 建图(示意坐标, 默认拒绝)
  python tools/traj_from_named.py --k xiaohong --dry-run  # 只算不写
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import traj_plan as TP                                                    # noqa: E402

# 单段上限 mm: 默认沿用 registry 的 300, 但实测 **222mm 一条 straight MoveL 会被控制器静默丢弃**
# (moveAppend/moveStart 都 ec=0, 但 25s 内一动不动; 同一位置拆成 100mm 就正常) ⇒ 覆盖扫描这类
# 长直线必须用 --seg-max 100 拆开。ZMAX_SEG_MAX_MM 环境变量可覆盖。
LIMIT = float(os.environ.get("ZMAX_SEG_MAX_MM") or TP.LIMIT)
START_GATE_MM = 20.0            # 起点闸: 与 550C 执行器同一口径
# 只显示、不打算给真机走的轨迹 (坐标不是真机可达语义)
NOT_EXECUTABLE = {
    "map": "建图轨迹是 2D 栅格平移到台面的**示意坐标**(32x30 @20cm), 不是真机可达点; 真要拿它走路得先做栅格→base 真值标定",
    "real_legacy": "实时轨迹(old)=真机走过的记录, 不是待执行路径",
}
SERVER = os.environ.get("ZMAX_AR_SERVER", "http://127.0.0.1:8797")


def fetch_named(k: str, target: str | None = None) -> dict:
    url = "%s/api/traj/named?k=%s&_=%d" % (SERVER, k, int(time.time() * 1000))
    if target:
        url += "&target=" + urllib.parse.quote(str(target))
    with urllib.request.urlopen(url, timeout=15) as r:                    # noqa: S310
        return json.load(r)


def _dist(a, b) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def rdp(pts, eps: float):
    """RDP 折线抽稀 (3D 点到线段距离), 保留形状骨架。"""
    if len(pts) < 3:
        return list(pts)
    a, b = pts[0], pts[-1]
    ab = [b[i] - a[i] for i in range(3)]
    den = sum(v * v for v in ab)
    dmax, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        p = pts[i]
        if den <= 1e-12:
            d = _dist(p, a)
        else:
            t = max(0.0, min(1.0, sum((p[j] - a[j]) * ab[j] for j in range(3)) / den))
            q = [a[j] + ab[j] * t for j in range(3)]
            d = _dist(p, q)
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = rdp(pts[:idx + 1], eps)
        right = rdp(pts[idx:], eps)
        return left[:-1] + right
    return [a, b]


def axis_segs(p_from, p_to):
    """两点 → 轴对齐段序列 (先 Z 再 X 再 Y), 每段 ≤ LIMIT。"""
    out = []
    for axis, up, down in ((2, "lift", "lower"), (0, "forward", "backward"), (1, "left", "right")):
        d = p_to[axis] - p_from[axis]
        if abs(d) < 0.5:            # 0.5mm 以下不动 (小于重复定位精度, 硬发就是抖)
            continue
        signed = up if d > 0 else down
        rest = abs(d)
        while rest > 1e-6:
            step = min(rest, LIMIT)
            out.append({"axis": axis, "dir": signed, "d_mm": round(step, 1)})
            rest -= step
            if rest > 1e-6 and rest < 0.5:      # 尾巴太短, 并进上一段
                out[-1]["d_mm"] = round(out[-1]["d_mm"] + rest, 1)
                rest = 0.0
    return out


def build(k: str, tol: float, force: bool, lead_in: bool = False, target: str | None = None):
    d = fetch_named(k, target)
    if not d.get("ok"):
        raise SystemExit("⛔ 取不到轨迹 %s: %s" % (k, d.get("note")))
    pts_m = [[float(v) for v in p] for p in (d.get("pts") or [])]
    if k == "real" and len(pts_m) > 8:
        # 实时: 服务端现在给的是**成形路径**(当前点 → 升到安全高 → 平移 → 落点, 4 点);
        # 只有老格式(几十点的长直线)才压成两端, 否则会被拆成几十个碎段。
        # 成形路径不能压: 压掉就等于低空斜插过去(看着A执行B)。
        pts_m = [pts_m[0], pts_m[-1]]
    if len(pts_m) < 2:
        raise SystemExit("⛔ 轨迹 %s 只有 %d 点, 不能规划" % (k, len(pts_m)))
    # 🔴 2026-10-26: 建图轨迹的数据源已换成 explore_traj_fenced.json ——
    #   那份是**按工程配置围栏扣减后重规划的真 base 坐标**(逐点过 fence_store.check_point),
    #   不再是老的"2D 栅格平移到台面"的示意坐标。所以这里不能再用 k=='map' 一刀切拒:
    #   按 src 判, 指出是 fenced 版就放行(起点闸/净空预检照旧跑), 老的示意源继续拒。
    _src = str(d.get("src") or "")
    _fenced = ("explore_traj_fenced" in _src) or ("避让围栏" in _src)
    # 轨迹5「实时」= 当前 TCP → 安全点1 的待执行路径 (服务端已按实时位姿生成点列),
    # 起点就是当前 TCP ⇒ 起点闸天然过。以前它被列进 NOT_EXECUTABLE(实测记录不可执行), 现在放行。
    if k == "real":
        pass
    elif k in NOT_EXECUTABLE and not force and not _fenced:
        raise SystemExit("⛔ %s 不可执行: %s\n   (确要试就加 --force)" % (k, NOT_EXECUTABLE[k]))
    rec = build_from_points(pts_m, k, tol, d.get("label") or k, d.get("src") or "", lead_in=lead_in)
    return rec, d


def build_from_points(pts_m, k, tol, label_named, src, lead_in=False):
    """纯计算: 点列(米) → 段表 + 预检。selftest 与线上走同一套代码。

    lead_in=True: 允许"当前 TCP 不在首点"的情况 —— 把 TCP→首点这段也拆成轴对齐段
    一起写进同一份段表(段表起点 = 当前 TCP), 这样 550C 的起点闸照样过。
    用于覆盖扫描类轨迹(建图): 它的起点在别处, 但不需要先单独发一次"去起点"。
    """
    tcp, q, age = TP.live_tcp()
    first = [v * 1000.0 for v in pts_m[0]]
    gap = _dist(tcp, first)
    if gap > START_GATE_MM and not lead_in:
        raise SystemExit(
            "⛔ 起点闸: 当前 TCP [%.1f, %.1f, %.1f] 离轨迹首点 [%.1f, %.1f, %.1f] 差 %.1fmm > %.0fmm\n"
            "   ⇒ 不规划(真机上「先去起点」本身就是一次运动, 得单独下发, 不能混在轨迹里)"
            % (tcp[0], tcp[1], tcp[2], first[0], first[1], first[2], gap, START_GATE_MM))

    # 🔴 单位必须统一: 点列是**米**, tol 是**毫米** —— 之前直接 rdp(pts_m, tol) 等于拿 5.0(米)
    #   当容差, 120mm 的方框整条被抽成一个点 ⇒ 报「轨迹全部点与当前 TCP 重合」。
    #   现在先换成 mm 再抽稀, tol 就真的是 5mm。
    anchors_mm = rdp([[v * 1000.0 for v in p] for p in pts_m], tol)
    segs = []
    cur = list(tcp)
    pts_walk = [list(cur)]
    i = 0
    # 🥽 2026-10-26 老倪「从当前点去准备点，走直线是最近的，你却升高后又绕远；改成直线」
    #   / 「不对，你怎么没有走直线？」
    #   轨迹5「实时」= 两点直线, 必须**按弧长等分走斜线**, 不能用下面那条轴对齐拆段:
    #     轴对齐 = 先 Z 再 X 再 Y ⇒ 画出来是直角阶梯, 而且实测 4 段 277mm 跑完 x/z 到位、
    #     y 差 53mm 没走(某轴段被丢) —— 总长比直线长 54%。
    #   斜线口径: 中间点严格落在起点→终点连线上, 每段 ≤90mm(>100mm 控制器会零位移静默丢弃),
    #   一律用 L2.forward + abs_mm(build_move 末尾用 abs_mm 覆盖目标 ⇒ 真斜线 MoveL)。
    if k == "real":
        _end = [v * 1000.0 for v in pts_m[-1]]
        _L = _dist(tcp, _end)
        _n = max(1, int(math.ceil(_L / 90.0)))
        for _j in range(1, _n + 1):
            _u = _j / float(_n)
            _nx = [tcp[_k2] + (_end[_k2] - tcp[_k2]) * _u for _k2 in range(3)]
            i += 1
            segs.append({"i": i, "skill": TP.SKILL["forward"], "dir": "forward",
                         "axis": 0, "sign": 1, "cn": TP.CN["forward"],
                         "d_mm": round(_dist(cur, _nx), 1), "line": True,
                         "from_mm": [round(v, 1) for v in cur],
                         "to_mm": [round(v, 1) for v in _nx],
                         "abs_mm": [round(v, 1) for v in _nx]})
            pts_walk.append(list(_nx))
            cur = list(_nx)
    for a in anchors_mm:
        if k == "real":
            break                       # 斜线已生成(上面), 不再走轴对齐
        if _dist(cur, a) < 0.5:
            continue
        for s in axis_segs(cur, a):
            i += 1
            cur = list(cur)
            cur[s["axis"]] += (1 if s["dir"] in ("lift", "forward", "left") else -1) * s["d_mm"]
            s["i"] = i
            s["skill"] = TP.SKILL[s["dir"]]
            s["sign"] = 1 if s["dir"] in ("lift", "forward", "left") else -1
            s["cn"] = TP.CN[s["dir"]]
            s["from_mm"] = [round(v, 1) for v in pts_walk[-1]]
            s["to_mm"] = [round(v, 1) for v in cur]
            s["abs_mm"] = [round(v, 1) for v in cur]
            segs.append(s)
            pts_walk.append(list(cur))
        # 轴对齐拆段后位置应回到锚点 (误差只来自四舍五入)
        if _dist(cur, a) > 1.0:
            raise SystemExit("内部错误: 拆段后没回到锚点 (%.2fmm)" % _dist(cur, a))
    if not segs:
        raise SystemExit("⛔ 轨迹全部点与当前 TCP 重合, 没有可执行的段")
    # 550C 执行器的硬闸: 1 <= n_seg <= 24 (plan_exec_550c.py 收包校验), 超过就发不出去。
    # 覆盖扫描(建图)一排一排走天然 12 段, 所以上限已经从 8 提到 24。
    if len(segs) > 24:
        raise SystemExit("⛔ 拆出 %d 段, 超过 550C 闸门上限 24 段 ⇒ 调大 --tol 抽稀, 或减少航点"
                         % len(segs))

    checks, worst, ok = [], 1e9, True
    for p in pts_walk:
        c = TP.precheck_point(p)
        c["pos_mm"] = [round(v, 1) for v in p]
        checks.append(c)
        worst = min(worst, c["clear_mm"])
        ok = ok and c["ok"]

    total = sum(s["d_mm"] for s in segs)
    label = "命名轨迹 %s · %d段 / %.0fmm" % (label_named, len(segs), total)
    rec = {
        "ts": time.time(), "src": "tools/traj_from_named.py", "k": k,
        "note": "由命名轨迹 %s 生成 (骨架 %d 点, 原始 %d 点, RDP tol %.1fmm · src=%s)"
                % (label_named, len(anchors_mm), len(pts_m), tol, src),
        "tcp0_mm": [round(v, 1) for v in tcp], "pose_age_s": round(age, 2),
        "segs": segs, "pts_mm": [[round(v, 1) for v in p] for p in pts_walk],
        "pts_m": [[round(v / 1000.0, 5) for v in p] for p in pts_walk],
        "total_mm": round(total, 1), "n_seg": len(segs),
        "precheck": {"ok": ok, "worst_mm": round(worst, 1), "min_clear_mm": TP.MIN_CLEAR,
                     "points": checks},
        "label": label,
    }
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", required=True, help="xiaohong / square / map / safe / real")
    ap.add_argument("--target", default="",
                    help="轨迹5(实时) 的目标点(工程配置点位台账里的点名, 缺省 安全点1)")
    ap.add_argument("--tol", type=float, default=5.0, help="RDP 抽稀容差 mm (默认 5)")
    ap.add_argument("--force", action="store_true", help="允许规划 示意坐标/实时 轨迹")
    ap.add_argument("--dry-run", action="store_true", help="只算不写 (不动 planned_traj.json)")
    ap.add_argument("--seg-max", type=float, default=0.0,
                    help="单段最大长度 mm (0=沿用默认 300; 长直线实测要用 100, 否则控制器不动)")
    ap.add_argument("--lead-in", action="store_true",
                    help="当前 TCP 不在首点时, 把 TCP→首点也拆成段一起下发 (覆盖扫描类轨迹用)")
    ap.add_argument("--self-test", action="store_true",
                    help="自检: 用当前 TCP 附近合成的 240mm 方框点验证 拆段/预检 数学 (不写文件)")
    a = ap.parse_args()

    if a.self_test:
        tcp, q, age = TP.live_tcp()
        c = [v / 1000.0 for v in tcp]
        side = 0.06                                  # ±60mm ⇒ 120mm 边长 (真机安全小框)
        # 起点必须**就是当前 TCP** (否则起点闸会挡, 那是设计如此): 从当前位置出发画一个方框
        corners = [[c[0], c[1], c[2]], [c[0] + 2 * side, c[1], c[2]],
                   [c[0] + 2 * side, c[1] + 2 * side, c[2]], [c[0], c[1] + 2 * side, c[2]]]
        pts = []
        for i in range(4):                           # 每边插 10 点 ⇒ 41 点闭环, 模拟真实密度
            A, B = corners[i], corners[(i + 1) % 4]
            for t in range(11):
                pts.append([A[j] + (B[j] - A[j]) * t / 10.0 for j in range(3)])
        rec = build_from_points(pts, "selftest", a.tol, "自检方框 120mm", "synthetic")
        print("[self-test] 合成点 %d → 骨架后 %d 段 / %.0fmm · 预检 %s (最差净空 %.1fmm)" %
              (len(pts), rec["n_seg"], rec["total_mm"],
               "PASS" if rec["precheck"]["ok"] else "FAIL", rec["precheck"]["worst_mm"]))
        for s in rec["segs"]:
            print("  %-2d %-9s %6.1fmm → %s" % (s["i"], s["dir"], s["d_mm"],
                                                [round(v, 1) for v in s["to_mm"]]))
        # 闭环校验: 走完后应回到起点
        end = rec["segs"][-1]["to_mm"]
        print("[self-test] 终点 %s vs 起点 %s · 闭环误差 %.2fmm" %
              (end, rec["tcp0_mm"], _dist(end, rec["tcp0_mm"])))
        return 0 if rec["precheck"]["ok"] else 2

    global LIMIT
    if a.seg_max and a.seg_max > 0:
        LIMIT = float(a.seg_max)
    elif a.k == "real":
        LIMIT = 100.0       # 去安全点要抬 264mm; 超过 ~220mm 的单段实测会被控制器丢掉
    rec, d = build(a.k, a.tol, a.force, lead_in=a.lead_in, target=(a.target or None))

    print("命名轨迹: %s  (%d 点, 来源 %s)" % (d.get("label"), d.get("n"), d.get("src")))
    print("起点 TCP = [%.1f, %.1f, %.1f] mm (帧龄 %.1fs) · 起点闸 ✅" %
          (rec["tcp0_mm"][0], rec["tcp0_mm"][1], rec["tcp0_mm"][2], rec["pose_age_s"]))
    for s in rec["segs"]:
        print("  %-2d %-9s %6.0fmm  →  %s" % (s["i"], s["dir"], s["d_mm"],
                                              [round(v, 1) for v in s["to_mm"]]))
    pc = rec["precheck"]
    print("总长 %.1fmm · %d 段 · 最差净空 %.1fmm ⇒ 预检 %s" %
          (rec["total_mm"], rec["n_seg"], pc["worst_mm"], "✅ PASS" if pc["ok"] else "❌ FAIL"))
    if not pc["ok"]:
        for c in pc["points"]:
            if not c["ok"]:
                print("   · %s 净空 %.1fmm (对 %s)" % (c["pos_mm"], c["clear_mm"], c["obj"]))

    if a.dry_run:
        print("(dry-run: 没写 planned_traj.json)")
        return 0
    if not pc["ok"]:
        print("⛔ 预检没过 ⇒ 不写段表(执行器也会拒发)")
        return 2

    tmp = TP.PLAN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TP.PLAN)
    print("✅ 段表 → %s" % TP.PLAN)

    # 550C 桥读的那份 (字段口径与 traj_plan 一致, 不另造一套)
    try:
        segs_pub = [{"id": s["i"], "name": s["skill"], "pos": [v / 1000.0 for v in s["to_mm"]],
                     "speed": None, "dir": s["cn"], "lin_mm": s["d_mm"], "quat": None,
                     "service": False, "abs_mm": s["abs_mm"]} for s in rec["segs"]]
        pub = {"skill": "TRAJ.planned", "backend": "traj", "src": "tools/traj_from_named.py",
               "n": len(segs_pub), "segs": segs_pub, "lin_total_mm": rec["total_mm"],
               "note": rec["note"], "precheck_ok": pc["ok"], "worst_clear_mm": pc["worst_mm"],
               "start_mm": rec["tcp0_mm"], "k": a.k,
               "t": time.time(), "t_pub": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        pdir = os.path.join(REPO, "zmax_data", "runtime", "plan")
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "plan_latest.json"), "w", encoding="utf-8") as f:
            json.dump(pub, f, ensure_ascii=False, indent=1)
        print("✅ 段表 → %s (550C 桥读这份)" % os.path.join(pdir, "plan_latest.json"))
    except Exception as e:                                                # noqa: BLE001
        print("⚠ plan_latest.json 没写成功: %s (不影响 550C 之外的链路)" % str(e)[:80])

    try:
        print(TP.draw(rec["pts_m"], rec["label"]))
    except Exception as e:                                                # noqa: BLE001
        print("⚠ 画线失败: %s" % str(e)[:80])
    return 0


if __name__ == "__main__":
    sys.exit(main())
