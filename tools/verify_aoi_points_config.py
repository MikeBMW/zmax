#!/usr/bin/env python3
"""判据: 任务7 AOI 的示教点位(含「金手指点1 的位置」)在**配置中心的配置里**查得到。

老倪 2026-10-12: 「更新记录这个 金手指点1 的位置, 要在配置中心的配置里找到这个数据」

判定 (真跑, 不看返回值):
  ① 任务配置 config/tasks/tasks.json 的 TASK-07-AOI.overrides 里有 pt.<点名> / pthist.<点名>
  ② 配置里的数值 == 台账真源 reports/aoi_points/<点名>.json 的 pos (逐位相同 — 真源驱动, 不是手抄)
  ③ pthist 的更新次数 == 该点 history.jsonl 行数, 且 old→new 与最后一行一致
  ④ 配置中心页 (真起窗口): AOI 行的 tooltip + 底部面板 都能看到 金手指点1 的位置
  ⑤ 生成器只读台账: 重跑 tools/task_build.py 后台账文件内容不变 (单一真源, 不反向写)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
PTDIR = os.path.join(ROOT, "reports", "aoi_points")

P = F = 0


def ck(cond, name, extra=""):
    global P, F
    if cond:
        P += 1
        print("  ✅ " + name + (("  · " + str(extra)) if extra else ""))
    else:
        F += 1
        print("  ⛔ " + name + (("  · " + str(extra)) if extra else ""))


def _task():
    with open(TASKS, encoding="utf-8") as f:
        tk = json.load(f)
    for t in (tk.get("tasks") or []):
        if t.get("task_id") == "TASK-07-AOI":
            return t
    return {}


def _file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def main():
    t = _task()
    ov = t.get("overrides") or {}
    print("\n=== ① 配置里有点位条目 ===")
    pts = {k[3:]: v for k, v in ov.items() if k.startswith("pt.")}
    hist = {k[7:]: v for k, v in ov.items() if k.startswith("pthist.")}
    ck(bool(pts), "任务7 AOI 的配置里有 pt.* 点位条目", "%d 条: %s" % (len(pts), ", ".join(sorted(pts))))
    ck("金手指点1" in pts, "其中就有「金手指点1」", pts.get("金手指点1", ""))
    ck(bool(hist), "有 pthist.* 更新记录", "%d 条" % len(hist))
    ck(ov.get("pt.dir") == "reports/aoi_points", "配置里写明台账目录 pt.dir", ov.get("pt.dir"))

    print("\n=== ② 配置数值 == 台账真源 (逐位) ===")
    if os.path.isdir(PTDIR):
        for f in sorted(os.listdir(PTDIR)):
            if not f.endswith(".json"):
                continue
            with open(os.path.join(PTDIR, f), encoding="utf-8") as fh:
                j = json.load(fh)
            pos = j.get("pos") or []
            nm = str(j.get("point") or f[:-5])
            if len(pos) != 3:
                continue
            val = pts.get(nm, "")
            want = "x=%.6f y=%.6f z=%.6f m" % (pos[0], pos[1], pos[2])
            ck(want in val, "%-6s 配置值 = 台账 pos" % nm, val[:58] + ("…" if len(val) > 58 else ""))
            ck((j.get("recorded_at") or "-") in val, "%-6s 配置里带记录时间" % nm, j.get("recorded_at"))

    print("\n=== ③ 更新记录 == 台账 history.jsonl ===")
    for nm in ("金手指点1", "金手指点2"):
        hp = os.path.join(PTDIR, nm + ".history.jsonl")
        if not os.path.exists(hp):
            ck(False, "%s 有 history.jsonl" % nm, hp)
            continue
        with open(hp, encoding="utf-8") as fh:
            lines = [json.loads(x) for x in fh.read().splitlines() if x.strip()]
        val = hist.get(nm, "")
        ck(("%d 次更新" % len(lines)) in val, "%s 更新次数 与 jsonl 行数一致" % nm, val)
        if lines:
            last = lines[-1]
            np_ = last.get("new_pos") or []
            if len(np_) == 3:
                ck(("(%.6f, %.6f, %.6f)" % tuple(np_)) in val, "%s 最近一次 new 值 一致" % nm, np_)

    print("\n=== ④ 配置中心页真起窗口: 能看到金手指点1 的位置 ===")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication          # noqa: E402
        import veh6_config_page as V                      # noqa: E402
        app = QApplication.instance() or QApplication([])
        page = V.build_config_center()
        tips, out = [], ""
        tab = getattr(page, "tasks_table", None)
        if tab is not None:
            for r in range(tab.rowCount()):
                it = tab.item(r, 0)
                if it is not None and "TASK-07-AOI" in str(it.text()):
                    tips.append(it.toolTip() or "")
        te = getattr(page, "out", None)
        if te is not None:
            out = te.toPlainText()
        tip_all = "\n".join(tips)
        ck("金手指点1" in tip_all, "AOI 行 tooltip 里有「金手指点1」")
        ck("0.489774" in tip_all, "tooltip 里带 x=0.489774", tip_all.split("金手指点1")[-1][:60] if "金手指点1" in tip_all else "")
        ck("金手指点1" in out and "0.489774" in out, "底部面板(可复制) 里有金手指点1 的位置")
        del page
    except Exception as e:                                                  # noqa: BLE001
        ck(False, "配置中心页起窗口", repr(e)[:120])

    print("\n=== ⑤ 生成器只读台账 (重跑 build 不改台账) ===")
    before = {}
    for f in sorted(os.listdir(PTDIR)):
        if f.endswith(".json") or f.endswith(".jsonl"):
            before[f] = _file_hash(os.path.join(PTDIR, f))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "task_build.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    ck(r.returncode == 0, "tools/task_build.py 重跑成功", "rc=%d" % r.returncode)
    after = {}
    for f in sorted(os.listdir(PTDIR)):
        if f.endswith(".json") or f.endswith(".jsonl"):
            after[f] = _file_hash(os.path.join(PTDIR, f))
    ck(before == after, "台账文件逐个 hash 不变 (只读真源)", "%d 个文件" % len(before))
    t2 = _task()
    ck(((t2.get("overrides") or {}).get("pt.金手指点1") == ov.get("pt.金手指点1")),
       "重跑后配置里金手指点1 的值稳定(幂等)")

    print("\n=== 汇总: PASS %d · FAIL %d ===" % (P, F))
    return 0 if F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
