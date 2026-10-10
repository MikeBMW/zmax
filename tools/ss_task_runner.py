#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_task_runner.py — 任务配置驱动状态空间**功能** (老倪: 「这个工程, 是通过配置改变功能」)

老倪 2026-10-10: 配置中心切任务 → 状态空间换功能 → 真跑(仿真) → 出结果 → 发飞书。

配置真源 (只读):  config/ss_task_binding.json   (config_center bind / tools/ss_task_bind.py 生成)
    tasks[TASK].ss_mode        insert | tray      ← **功能模式**, 由任务工艺机械推出
    tasks[TASK].enabled_nodes  该任务该开的节点
    tasks[TASK].disabled_nodes 该任务该关的节点 (配置把功能剪掉的那部分)
    tasks[TASK].run_cfg        六档位
    tasks[TASK].overrides      参数覆盖

按 mode 选 episode 执行链 (两条链**都是状态空间六层源码直接执行**, 不是各写一套):
    insert → tools/gen_ss_metaworld_episode.py   插拔: 接近→对位→下降→抓取→抬起→转移→插入→拔出→AOI
    tray   → tools/gen_tray_place_video.py       摆盘: 接近→对位→下降→抓取→抬起→转移→**放入**→完成 (真空吸附)

用法:
    python3 tools/ss_task_runner.py --list
    python3 tools/ss_task_runner.py --task TASK-06-TRAY --push
    python3 tools/ss_task_runner.py --task TASK-01-FW   --no-video
输出:
    reports/ss_task_run_<TASK>_<ts>.json   本次配置 + L2 原子技能表 + 结果判据 + 产物
    reports/ss_task_run_<TASK>_latest.json 同一份的 latest 指针
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")
REPORTS = os.path.join(ROOT, "reports")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
FEISHU = os.path.join(ROOT, "tools", "feishu_send.py")

# mode → (生成器, 说明)
CHAIN = {
    "insert": ("tools/gen_ss_metaworld_episode.py",
               "插拔链 (SK07=插入): 孔口对位 + 接触推入 + 保持力"),
    "tray": ("tools/gen_tray_place_video.py",
             "取放链 (SK07=放入): 真空吸附取件 → 槽位下放, 无孔口/无推入"),
}


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return d


def load_binding() -> dict:
    d = _j(BINDING)
    if not d:
        raise SystemExit("⛔ 缺 config/ss_task_binding.json —— 先跑 python3 tools/ss_task_bind.py")
    return d


def task_of(bind: dict, task_id: str | None) -> dict:
    tasks = bind.get("tasks") or []
    if not task_id:
        task_id = bind.get("active_task")
    t = next((x for x in tasks if x["task_id"] == task_id), None)
    if not t:
        raise SystemExit(f"⛔ 无此任务: {task_id} (可选: {[x['task_id'] for x in tasks]})")
    return t


def l2_skills(mode: str) -> list:
    """L2 原子技能表 (由 mode 选出第 7 段语义: 插入 / 放入)"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.policies.left_right.state_space.skills import atomic_skills as A
        rows = []
        for cls in A.skills_for_mode(mode):
            rows.append({"code": getattr(cls, "code", "?"), "stage": getattr(cls, "stage", "?"),
                         "name": getattr(cls, "name", cls.__name__),
                         "desc": (cls.__doc__ or "").strip().split("\n")[0][:120]})
        return rows
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {e}"}]


def stages_of(mode: str) -> list:
    """L3 八阶段链 (真源 = cognition.ActionModulator.STAGES; 摆盘 = 前 6 段 + 放入(放下) + 完成)"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.policies.left_right.state_space.cognition import ActionModulator as AM
        if str(mode).lower() == "tray":
            return list(AM.STAGES[:6]) + ["放入(=放下)", AM.STAGES[-1]]
        return list(AM.STAGES)
    except Exception as e:  # noqa: BLE001
        return [f"(读不到 STAGES: {type(e).__name__}: {e})"]


def activate(task_id: str) -> dict:
    r = subprocess.run([PY, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--activate", task_id],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    return {"rc": r.returncode, "out": (r.stdout or "").strip()[-300:]}


def run_chain(mode: str, extra: list) -> dict:
    gen, why = CHAIN[mode]
    cmd = [PY, os.path.join(ROOT, gen)] + list(extra)
    env = dict(os.environ, MUJOCO_GL="egl", MUJOCO_EGL_DEVICE="0", ZMAX_L4_ROOT=ROOT,
               PYTHONIOENCODING="utf-8")
    t0 = time.time()
    logf = os.path.join("/tmp", f"ss_task_{mode}_{int(t0)}.log")
    lines = []
    with open(logf, "w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, cwd=os.path.join(ROOT, "tools"), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        for ln in p.stdout:
            f.write(ln)
            ln = ln.rstrip("\n")
            if "前馈加速器" not in ln:          # MLP 每步一行太吵, 报告不搬
                lines.append(ln)
                print(ln, flush=True)
        p.wait()
    return {"mode": mode, "chain": gen, "chain_why": why, "cmd": cmd, "rc": p.returncode,
            "sec": round(time.time() - t0, 2), "log": logf, "lines": lines}


def parse_result(mode: str, run: dict) -> dict:
    """从生成器输出/产物里提判据 (不重算, 只搬运真凭据)"""
    lines = run["lines"]
    out = {"per_module": [], "summary": None, "npz_meta": None}
    if mode == "tray":
        for ln in lines:
            s = ln.strip()
            if s.startswith("→ 槽"):
                out["per_module"].append(s)
            if s.startswith("📊"):
                out["summary"] = s
    else:
        for ln in lines:
            s = ln.strip()
            if any(k in s for k in ("✅", "❌", "判定", "成功", "失败")):
                out["per_module"].append(s)
        for ln in lines:
            if ln.strip().startswith("📊"):
                out["summary"] = ln.strip()
    npz = os.path.join(REPORTS, "ss_episode_latest.npz" if mode == "insert"
                       else "tray_place_latest.npz")
    if os.path.isfile(npz):
        try:
            import numpy as np
            z = np.load(npz, allow_pickle=True)
            if "meta" in z.files:
                m = z["meta"]
                out["npz_meta"] = json.loads(str(m.item() if hasattr(m, "item") else m))
            out["npz"] = npz
        except Exception as e:  # noqa: BLE001
            out["npz_meta"] = {"read_error": f"{type(e).__name__}: {e}"}
    return out


def artifacts(mode: str) -> list:
    pats = (["reports/tray_place_*.mp4", "reports/tray_place_*.npz"] if mode == "tray"
            else ["reports/ss_episode_*.mp4", "reports/ss_episode_*.npz"])
    files = []
    for pat in pats:
        for p in sorted(glob.glob(os.path.join(ROOT, pat)), key=os.path.getmtime)[-4:]:
            files.append({"path": os.path.relpath(p, ROOT), "bytes": os.path.getsize(p),
                          "mtime": time.strftime("%F %T", time.localtime(os.path.getmtime(p)))})
    return files


def feishu(text: str, image: str = "") -> dict:
    cmd = [PY, FEISHU, "--text", text]
    if image:
        cmd = [PY, FEISHU, "--image", image, "--text", text]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    return {"rc": r.returncode, "out": (r.stdout or "").strip()[-400:],
            "err": (r.stderr or "").strip()[-200:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--push", action="store_true", help="结果发飞书报告群")
    ap.add_argument("--image", default="", help="一起发的图 (默认取最新判据图)")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--modules", type=int, default=3, help="摆盘链: 摆几颗")
    ap.add_argument("--no-run", action="store_true", help="只出配置清单/技能表, 不真跑")
    a = ap.parse_args()

    bind = load_binding()
    if a.list:
        print(f"工程: {(bind.get('project') or {}).get('name')} · 活跃任务 {bind.get('active_task')}")
        for t in bind.get("tasks") or []:
            print(f"  {t['task_id']:18s} mode={t.get('ss_mode'):6s} 开 {len(t.get('enabled_nodes') or []):2d} "
                  f"关 {len(t.get('disabled_nodes') or []):2d}  {t['name']}")
        return 0

    t = task_of(bind, a.task)
    mode = str(t.get("ss_mode") or "insert")
    gen, why = CHAIN.get(mode, CHAIN["insert"])
    rep = {
        "schema": "zmax.statespace.taskrun/1",
        "started_at": time.strftime("%F %T"),
        "task": {k: t.get(k) for k in ("task_id", "name", "recipe_type", "scene_ref", "site",
                                       "ss_mode", "applies_segments", "excluded_segments",
                                       "trigger", "loop", "targets", "safety")},
        "config_effect": {
            "mode": mode, "chain": gen, "chain_why": why,
            "enabled_nodes": len(t.get("enabled_nodes") or []),
            "disabled_nodes": t.get("disabled_nodes") or [],
            "run_cfg_on": [v["label"] for v in (t.get("run_cfg") or {}).values() if v.get("checked")],
            "overrides": t.get("overrides") or {},
        },
        "layers": {"L5": "下指令 (任务意图)", "L4": "保安全 (安全闸/可行域)",
                   "L3": "编流程 (八阶段状态机)", "L2": "操作 (原子技能)",
                   "moveit": "执行 (仿真: MuJoCo 物理; 真机: MoveIt/下位机)"},
        "l2_skills": l2_skills(mode),
        "stages": stages_of(mode),
    }
    print(f"🧩 任务 {t['task_id']} ({t['name']})")
    print(f"   功能模式: {mode}  ← 由工艺推出 (配置改变功能, 不是改代码)")
    print(f"   执行链: {gen}   {why}")
    print(f"   配置效果: 开 {rep['config_effect']['enabled_nodes']} 节点 · "
          f"关 {len(t.get('disabled_nodes') or [])} 节点 {t.get('disabled_nodes') or ''}")
    print(f"   档位(开): {' · '.join(rep['config_effect']['run_cfg_on']) or '—'}")
    print(f"   L2 原子技能 {len(rep['l2_skills'])} 段: "
          + " → ".join(f"{s.get('code')}:{s.get('stage')}" for s in rep["l2_skills"][:9]))
    print(f"   L3 八阶段: {' → '.join(str(s) for s in rep['stages'][:12])}")

    rep["activate"] = activate(t["task_id"])
    print(f"   活跃任务已写盘: rc={rep['activate']['rc']} {rep['activate']['out'][:80]}")

    if not a.no_run:
        extra = (["--modules", str(a.modules)] if mode == "tray" else [])
        if a.no_video:
            extra.append("--no-video")
        if mode == "tray" and (t.get("overrides") or {}):
            simple = {k: v for k, v in (t["overrides"] or {}).items()
                      if isinstance(v, (int, float, str, bool))}
            if simple:
                extra += ["--params-json", json.dumps(simple, ensure_ascii=False)]
        print(f"\n▶ 真跑: {' '.join(extra) or '(默认参数)'}")
        run = run_chain(mode, extra)
        rep["run"] = {k: run[k] for k in ("mode", "chain", "rc", "sec", "log")}
        rep["result"] = parse_result(mode, run)
        rep["artifacts"] = artifacts(mode)
        ok = (run["rc"] == 0)
        print(f"\n{'✅' if ok else '❌'} 跑完 rc={run['rc']} {run['sec']}s")
        for ln in rep["result"]["per_module"][-6:]:
            print(f"   {ln}")
        if rep["result"]["summary"]:
            print(f"   {rep['result']['summary']}")

    tp = os.path.join(REPORTS, f"ss_task_run_{t['task_id']}_{time.strftime('%Y%m%d_%H%M%S')}.json")
    os.makedirs(REPORTS, exist_ok=True)
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    lp = os.path.join(REPORTS, f"ss_task_run_{t['task_id']}_latest.json")
    with open(lp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(f"📄 报告: {os.path.relpath(tp, ROOT)}  (+ {os.path.relpath(lp, ROOT)})")

    if a.push:
        pm = rep.get("result", {}).get("per_module") or []
        msg = (f"🧩 {t['task_id']} {t['name']}\n"
               f"配置改变功能: mode={mode} ({why})\n"
               f"开 {rep['config_effect']['enabled_nodes']} 节点 / 关 "
               f"{len(t.get('disabled_nodes') or [])} 节点\n"
               f"L2 原子段: " + "→".join(str(s.get("code")) for s in rep["l2_skills"]) + "\n"
               + ("\n".join(pm[-4:]) + "\n" if pm else "")
               + f"{rep.get('result', {}).get('summary') or ''}\n"
               + "报告: " + os.path.relpath(tp, ROOT))
        img = a.image or ""
        if not img:
            c = sorted(glob.glob(os.path.join(REPORTS, "tray_place_*judge*.png"))
                       + glob.glob(os.path.join(REPORTS, "*latest*.png")), key=os.path.getmtime)
            img = c[-1] if c else ""
        rep["feishu"] = feishu(msg, img)
        print(f"📨 飞书: rc={rep['feishu']['rc']} {rep['feishu']['out'][:160]}")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
