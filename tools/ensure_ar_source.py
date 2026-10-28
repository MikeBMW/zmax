#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔀 数据源守护 — 让画布「数据源 = AR场景」不用每次手动改

老倪 2026-10-28: 「画布你要记下我之前的配置, 我每次启动控制台, 我都要手动修改数据源到 AR场景, 你要记下来」

为什么需要它 (根因, 不是猜):
  · 画布唯一依据 data/database/zmax/sources/canvas/state_space_obs.json 里 📦数据源节点
    params.src_state 已经是「AR场景」(src/lerobot/engineering/flows/ 那份是软链, 同一份文件);
  · 但控制台打开工程 / 点「🔀 数据源切换」会把 src_state 写成别的值 (并在下次保存后落盘),
    于是每次启动都要人工再点回去。
  · GUI 是在役界面, 不改它; 用这个守护在旁把**用户的意图**兜住。

判据 (只认意图, 不瞎改):
  · exec_switches.json 的 ar_scene=true 且新鲜  ⇒ 用户此刻就想跑 AR 场景
        -> src_state 必须是「AR场景」, 不是就改回来 (备份 + 回读核对)
  · ar_scene=false (用户自己关了 AR) ⇒ 什么都不做, 尊重用户
  · real_auth 永不读、永不写 (真机授权红线)

用法:
  python3 tools/ensure_ar_source.py            # 检查并按需修正 (幂等)
  python3 tools/ensure_ar_source.py --check    # 只看, 不改 (判据用)
  python3 tools/ensure_ar_source.py --status   # 打印当前三处真值
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
SW = os.path.join(ROOT, "zmax_data/ss_live/exec_switches.json")
WANT = "AR场景"
SRC_FRESH_S = 1800.0


def _read_sw():
    try:
        d = json.load(open(SW, encoding="utf-8"))
    except Exception:                                             # noqa: BLE001
        return None, None
    age = None
    try:
        age = time.time() - float(d.get("ts") or d.get("t") or 0)
    except Exception:                                             # noqa: BLE001
        pass
    return d, age


def _ar_wanted(d, age):
    """用户此刻是否想跑 AR: 开关为真且新鲜"""
    if not isinstance(d, dict):
        return False, "开关文件读不到"
    raw = bool(d.get("ar_scene") or (d.get("switches") or {}).get("ar_scene"))
    if not raw:
        return False, "ar_scene=false (用户关了 AR, 不动)"
    if age is not None and age > SRC_FRESH_S:
        return False, "ar_scene 已过期 %.0fs (不据此改画布)" % age
    return True, "ar_scene=true 且新鲜"


def canvas_src_state():
    try:
        cv = json.load(open(CANVAS, encoding="utf-8"))
    except Exception as e:                                        # noqa: BLE001
        return None, "画布读不到: %s" % e
    for n in cv.get("nodes", []):
        if n.get("id") == "ssdata":
            return (n.get("params") or {}).get("src_state"), "ok"
    return None, "画布里没有 ssdata 节点"


def set_src_state(new):
    """改画布 ssdata.params.src_state (备份 + 回读核对)"""
    bak = CANVAS + time.strftime(".bak_%Y%m%d_%H%M%S")
    shutil.copy2(CANVAS, bak)
    cv = json.load(open(CANVAS, encoding="utf-8"))
    hit = False
    for n in cv.get("nodes", []):
        if n.get("id") == "ssdata":
            n.setdefault("params", {})["src_state"] = new
            hit = True
            break
    if not hit:
        return False, "没找到 ssdata, 未写"
    json.dump(cv, open(CANVAS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    back, _ = canvas_src_state()
    ok = (back == new)
    return ok, ("回读=%s" % back) + ("" if ok else " ✗ 回读不一致") + " | 备份=%s" % os.path.basename(bak)


def main():
    args = set(sys.argv[1:])
    cur, why = canvas_src_state()
    d, age = _read_sw()
    want, wwhy = _ar_wanted(d, age)

    if "--status" in args or "--check" in args:
        print("画布 src_state   : %s (%s)" % (cur, why))
        print("ar_scene 开关    : %s (龄 %s)" % (
            (d or {}).get("ar_scene") if isinstance(d, dict) else "读不到",
            ("%.1fs" % age) if age is not None else "?"))
        print("用户想跑 AR      : %s (%s)" % (want, wwhy))
        print("判定             : %s" % (
            "已是 AR场景, 无需动作" if cur == WANT else
            ("应改回 AR场景" if want else "不同源但不该改 (尊重用户)")))
        return 0 if (cur == WANT or not want) else 1

    if cur == WANT:
        print("✅ 画布数据源已是「%s」, 无需动作" % WANT)
        return 0
    if not want:
        print("⏭  数据源=%s, 但 %s ⇒ 不改 (尊重用户当前选择)" % (cur, wwhy))
        return 0

    ok, msg = set_src_state(WANT)
    print("%s 数据源 %s → %s | %s" % ("✅" if ok else "❌", cur, WANT, msg))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
