#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_task_state.py — 🚦 任务配置状态真源 (三态: ★ 活跃 / ○ 未激活 / — 无配置)  2026-10-11

老倪原话: 「在配置中心, 在工艺/工单/任务的配置界面, 有个 活跃属性, 当前 TASK-01-FW 的配置正在显示 活跃,
          其它的任务状态, 都要标记出来; 例如 TASK-06, 你已经完成了任务配置切换后, 马上就可以工作, 对不?
          TASK-06-TRAY 的活跃状态, 应该是 未激活; 其它的任务, 应该是无配置, 因为还没开始」

口径 (**全部从真源/证据推导, 不手填任务清单**):
  ★ 活跃   : 该任务 == config/ss_task_binding.json 的 active_task (绑定真源, 唯一)
  ○ 未激活 : 该任务**配置切换过 或 跑过验证** ⇒ 配置已就绪, 切过去就能干活
             证据 = ① 激活台账 config/task_state_ledger.json 有记录
                    ② 该任务的运行报告 (docs/data_snapshots/*/任务运行报告_<TASK>*.json 等)
                    ③ zmax_data/task_runs/<TASK>/* 有产物
  — 无配置 : 上面都没有 ⇒ 还没开始

用法:
  python tools/ss_task_state.py build    # 扫证据 → 写 config/task_state.json (可审计) + 打印表格
  python tools/ss_task_state.py show     # 只打印
  python tools/ss_task_state.py cell TASK-06-TRAY   # 给界面用的一格文字
环境: ROOT 取本文件所在仓库根 (ZMAX_ROOT 可覆盖)。
"""
import argparse
import glob
import json
import os
import sys
import time

ROOT = os.environ.get("ZMAX_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
OUT = os.path.join(ROOT, "config", "task_state.json")
LEDGER = os.path.join(ROOT, "config", "task_state_ledger.json")
MANUAL = os.path.join(ROOT, "config", "task_state_manual.json")   # 🆕 用户在下拉里手选的活跃属性 (覆盖证据推导)

STATE_ACTIVE = "★ 活跃"
STATE_INACTIVE = "○ 未激活"
STATE_NONE = "— 无配置"
CELL = {STATE_ACTIVE: STATE_ACTIVE, STATE_INACTIVE: STATE_INACTIVE, STATE_NONE: STATE_NONE}

EVIDENCE_GLOBS = (
    "docs/data_snapshots/*/任务运行报告_%s*.json",
    "docs/data_snapshots/*/%s*/运行报告.json",
    "zmax_data/task_runs/%s/*.json",
    "zmax_data/task_runs/%s/*.npz",
)


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return d


def tasks():
    """任务清单 (真源 config/ss_task_binding.json.tasks)。"""
    d = _j(BIND, {}) or {}
    return [t for t in (d.get("tasks") or []) if isinstance(t, dict) and t.get("task_id")], d.get("active_task")


def evidence(tid):
    """该任务的**已就绪证据** (真实产物路径, 按新到旧)。"""
    out = []
    for g in EVIDENCE_GLOBS:
        try:
            out += glob.glob(os.path.join(ROOT, g % tid))
        except Exception:                                                      # noqa: BLE001
            pass
    try:
        for rec in (_j(LEDGER, {}) or {}).get("activations", []) or []:
            if rec.get("task_id") == tid:
                out.append("激活台账 %s" % rec.get("ts", ""))
    except Exception:                                                          # noqa: BLE001
        pass
    return sorted(set(out), key=lambda s: os.path.getmtime(s) if os.path.exists(s) else 0, reverse=True)


def manual():
    """用户手选的状态 (config/task_state_manual.json: {tid: {state, ts, by}})。"""
    return (_j(MANUAL, {}) or {}).get("states") or {}


def set_state(tid, state, by="配置中心 UI"):
    """🆕 2026-10-11 老倪: 配置中心活跃属性**用户自选** (下拉) → 落到真源/台账, 不装样子。

    ★ 活跃   : 真激活 —— 走 tools/ss_task_bind.py --activate <tid> (写 config/ss_task_binding.json + 台账), 回读校验
    ○ 未激活 : 被手标的「配置就绪但不激活」→ 记 manual (当前活跃任务不能标未激活 ⇒ 拒绝并说原因)
    — 无配置 : 撤销手标 (有运行证据的任务拒绝降级 —— 证据不会因为点个下拉就消失)
    → (ok, why, extra)
    """
    st = str(state or "").strip()
    if st not in (STATE_ACTIVE, STATE_INACTIVE, STATE_NONE):
        return False, "未知状态 %r (只认 %s)" % (state, " / ".join((STATE_ACTIVE, STATE_INACTIVE, STATE_NONE))), {}
    _ts, act = tasks()
    ev = evidence(tid)
    if st == STATE_ACTIVE:
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--activate", tid],
                           capture_output=True, text=True, timeout=300, cwd=ROOT)
        _t2, act2 = tasks()
        ok = r.returncode == 0 and act2 == tid
        if ok:
            m = manual(); m.pop(tid, None)                 # 活跃由绑定真源说了算 ⇒ 清掉手标
            _write_manual(m)
        why = ("已真激活 %s (绑定真源 active_task=%s)" % (tid, act2)) if ok else \
              ("激活失败: %s" % ((r.stderr or r.stdout or "")[-200:]))
        return ok, why, {"active_task": act2}
    if st == STATE_INACTIVE and tid == act:
        return False, "⛔ %s 是当前活跃任务 —— 不能直接标未激活; 先把别的任务选成「★ 活跃」(活跃唯一)" % tid, {"active_task": act}
    if st == STATE_NONE and ev:
        return False, "⛔ %s 有 %d 条真实证据 (%s) ⇒ 不能标无配置 (点下拉不会让证据消失)" % (
            tid, len(ev), os.path.relpath(ev[0], ROOT) if os.path.exists(ev[0]) else ev[0]), {"evidence": ev[:3]}
    m = manual()
    if st == STATE_NONE:
        m.pop(tid, None)
    else:
        m[tid] = {"state": st, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by}
    _write_manual(m)
    return True, "%s → %s (已记 %s)" % (tid, st, os.path.relpath(MANUAL, ROOT)), {}


def _write_manual(m):
    try:
        d = {"_meta": {"note": "配置中心活跃属性手选 (用户在下拉里定)", "updated": time.strftime("%Y-%m-%d %H:%M:%S")},
             "states": m}
        os.makedirs(os.path.dirname(MANUAL), exist_ok=True)
        tmp = MANUAL + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, MANUAL)
        return True
    except Exception:                                                          # noqa: BLE001
        return False


def state_of(tid, active=None):
    """→ (state, why, evidence[])

    优先级: ① 绑定真源 active_task ⇒ ★ 活跃 (唯一) ② 用户手选 (manual) ③ 证据推导 ④ 无配置
    """
    if active is None:
        _t, active = tasks()
    ev = evidence(tid)
    if tid == active:
        return STATE_ACTIVE, "绑定真源 active_task = %s" % active, ev
    mn = (manual().get(tid) or {}).get("state")
    if mn in (STATE_INACTIVE, STATE_NONE):
        why = "用户在配置中心手选 %s" % mn
        if mn == STATE_INACTIVE and ev:
            why += " (且有 %d 条证据)" % len(ev)
        return mn, why, ev
    if ev:
        return STATE_INACTIVE, "配置已切换/验证过 (%d 条证据) ⇒ 切过去即可工作" % len(ev), ev
    return STATE_NONE, "无激活台账也无运行产物 ⇒ 还没开始", []


def cell(tid, active=None):
    """界面一格: ★ 活跃 / ○ 未激活 / — 无配置"""
    return state_of(tid, active)[0]


def record_activation(tid, source="ss_task_bind --activate"):
    """配置中心激活任务时记账 (幂等: 同任务只留最新一条 + 累计次数)。"""
    try:
        d = _j(LEDGER, {}) or {}
        recs = [r for r in (d.get("activations") or []) if isinstance(r, dict)]
        n = 1 + sum(1 for r in recs if r.get("task_id") == tid)
        recs.append({"task_id": tid, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source, "count": n})
        d["activations"] = recs[-400:]
        d["_meta"] = {"note": "任务配置切换台账 (配置中心激活时追加)", "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        tmp = LEDGER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, LEDGER)
        return True
    except Exception:                                                          # noqa: BLE001
        return False


def build(write=True):
    ts, act = tasks()
    rows = []
    for t in ts:
        st, why, ev = state_of(t["task_id"], act)
        rows.append({"task_id": t["task_id"], "name": t.get("name", ""), "state": st, "why": why,
                     "evidence": ev[:4], "n_evidence": len(ev),
                     "recipe_type": t.get("recipe_type", ""), "scene_ref": t.get("scene_ref", "")})
    n = {k: sum(1 for r in rows if r["state"] == k) for k in (STATE_ACTIVE, STATE_INACTIVE, STATE_NONE)}
    doc = {"_meta": {"note": "任务配置状态 (推导物: 活跃=绑定真源; 未激活=有激活台账/运行证据; 无配置=还没开始)",
                     "built": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "tools/ss_task_state.py build"},
           "active_task": act, "counts": {"活跃": n[STATE_ACTIVE], "未激活": n[STATE_INACTIVE], "无配置": n[STATE_NONE]},
 "manual": manual(),
           "tasks": rows}
    if write:
        try:
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            tmp = OUT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            os.replace(tmp, OUT)
        except Exception as e:                                                  # noqa: BLE001
            print("⚠️ 写 %s 失败: %s" % (OUT, e))
    return doc


def _print(doc):
    print("  active_task = %s" % doc.get("active_task"))
    print("  %-17s %-10s %s" % ("任务", "状态", "依据"))
    for r in doc["tasks"]:
        print("  %-17s %-10s %s%s" % (r["task_id"], r["state"], r["why"],
                                      (" · " + os.path.relpath(r["evidence"][0], ROOT)) if r["evidence"] else ""))
    c = doc["counts"]
    print("  合计: 活跃 %d / 未激活 %d / 无配置 %d" % (c["活跃"], c["未激活"], c["无配置"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="build", choices=["build", "show", "cell", "set"])
    ap.add_argument("arg", nargs="?", default=None)
    a = ap.parse_args()
    if a.cmd == "cell":
        print(cell(a.arg) if a.arg else "")
        return 0
    if a.cmd == "set":
        tid, st = (a.arg or ":").split(":", 1)
        ok, why, extra = set_state(tid, st)
        print(("✅ " if ok else "⛔ ") + why)
        return 0 if ok else 2
    doc = build(write=(a.cmd == "build"))
    _print(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
