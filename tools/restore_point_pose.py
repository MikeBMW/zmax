#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""restore_point_pose.py — 把一个点位的位姿恢复成"同姿态参考点"的位姿 (2026-10-12)

为什么要有这个工具:
  点位台账/示教库都只存**最后一次**写入的值, 覆盖后原值就没了(台账不在 git 里, 没历史)。
  2026-10-12 我做「新增安全点按钮延迟」实测时, 用已有点名(安全点1)跑了真实 POST ⇒ 把老倪
  15:34:58 记的 安全点1(standby 位姿) 覆盖成了当时机械臂所在的那个位姿。
  当时臂正停在同一个 standby 位姿上的两个点(金手指点1/点2) 还留着同姿态的 pos+quat
  ⇒ 用它们做**同姿态参考**精确恢复, 而不是"猜一个坐标"。

用法:
  python3 tools/restore_point_pose.py --name 安全点1 --like 金手指点1 --why "误覆盖恢复" [--at "2026-10-12 15:34:58"] [--write]

不加 --write 只演练(打印将写入什么)。写入后自动跑一次 task_build 让配置中心/画布同步。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
LEDGER = os.path.join(ROOT, "reports/aoi_points")
TAUGHT = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
SPACE = os.path.join(ROOT, "data/skills/l2_atomic/space_points.json")


def load_pose(name: str):
    """按 台账 → 示教库 → 空间点库 找这个点的 pos/quat/abc。"""
    p = os.path.join(LEDGER, name + ".json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        return {"pos": d.get("pos"), "quat": d.get("quat"), "abc": d.get("abc"), "src": p,
                "desc": d.get("desc"), "recorded_at": d.get("recorded_at"), "source": d.get("source")}
    for f in (TAUGHT, SPACE):
        if os.path.exists(f):
            d = json.load(open(f, encoding="utf-8"))
            e = (d.get("points") or {}).get(name) or d.get(name)
            if e:
                return {"pos": e.get("pos"), "quat": e.get("quat"), "abc": e.get("abc"), "src": f,
                        "desc": e.get("desc"), "recorded_at": e.get("recorded_at"), "source": e.get("source")}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="要恢复的点")
    ap.add_argument("--like", required=True, help="同姿态参考点(拿它的 pos/quat)")
    ap.add_argument("--why", default="", help="写进台账的原因")
    ap.add_argument("--at", default="", help="恢复成哪个时刻的记录(默认沿用参考点时刻, 只作留痕)")
    ap.add_argument("--write", action="store_true", help="真写(默认只演练)")
    a = ap.parse_args()

    ref = load_pose(a.like)
    if not ref or not ref.get("pos"):
        print("❌ 找不到参考点 %s" % a.like)
        return 1
    print("参考点 %s ← %s\n  pos=%s\n  quat=%s\n  abc=%s" % (a.like, ref["src"], ref["pos"], ref["quat"], ref["abc"]))
    print("目标点 %s 当前 = %s" % (a.name, json.dumps(load_pose(a.name), ensure_ascii=False)[:200]))

    # abc 一律重算(同姿态), 用唯一口径 pt_pose
    abc = ref.get("abc")
    try:
        from pt_pose import abc_deg                                # type: ignore
        if ref.get("quat"):
            abc = list(abc_deg(ref["quat"]))
    except Exception as e:                                        # noqa: BLE001
        print("  ⚠️ pt_pose 换算不可用(%s), 沿用参考点 abc=%s" % (str(e)[:60], abc))

    now = a.at or ref.get("recorded_at") or ""
    ent = {"pos": ref["pos"], "quat": ref["quat"], "abc": abc,
           "desc": (ref.get("desc") or "") + (" · " + a.why if a.why else ""),
           "recorded_at": now if a.at else (ref.get("recorded_at") or ""),
           "source": "恢复(参考 %s, 同姿态)" % a.like + (" · " + a.why if a.why else ""),
           "restored_from": a.like}
    print("\n将写入:\n  %s\n  %s\n  %s.json" % (TAUGHT, ledger_ := os.path.join(LEDGER, a.name + ".json"), a.name))
    print("  台账内容 =", json.dumps({k: ent[k] for k in ("pos", "quat", "abc", "recorded_at", "source")}, ensure_ascii=False))
    if not a.write:
        print("\n(演练: 没写。加 --write 才真写)")
        return 0

    # 台账
    led = {"point": a.name, "pos": ent["pos"], "quat": ent["quat"], "abc": abc,
           "recorded_at": ent["recorded_at"], "source": ent["source"],
           "desc": ent["desc"], "restored_from": a.like}
    os.makedirs(LEDGER, exist_ok=True)
    json.dump(led, open(os.path.join(LEDGER, a.name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 示教库: 🔴 真源结构是 {"points": {点名: {...}}} —— 必须写进 points 里!
    #   (2026-10-12 我第一版写成**顶层**键 ⇒ 服务读 points 看不到, 页面继续显示旧值, 台账与库判不一致。
    #    自己踩的坑: 写共享状态文件前先确认嵌套层级, 写完必须用**服务自己的读法**回读。)
    t = json.load(open(TAUGHT, encoding="utf-8")) if os.path.exists(TAUGHT) else {}
    if "points" not in t or not isinstance(t["points"], dict):
        t["points"] = {}
    for _k in list(t):                      # 清掉同名顶层键(旧版误写留下的)
        if _k == a.name and isinstance(t.get(_k), dict):
            t.pop(_k)
    t["points"][a.name] = ent
    t["updated_at"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
    json.dump(t, open(TAUGHT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  ✅ 已写台账 + 示教库(points.%s)" % a.name)
    # 配置同步(与 8793 记录口同一动作)
    r = subprocess.run([sys.executable or "python3", os.path.join(ROOT, "tools", "task_build.py")],
                       capture_output=True, text=True, timeout=120)
    print("  配置同步 task_build rc=%s" % r.returncode)
    back = load_pose(a.name)
    print("  ↺ 回读: pos=%s quat=%s" % (back.get("pos"), back.get("quat")))
    same = all(abs(float(x) - float(y)) < 1e-9 for x, y in zip(back["pos"], ref["pos"]))
    print("  %s 回读与参考点同值" % ("✅" if same else "❌"))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
