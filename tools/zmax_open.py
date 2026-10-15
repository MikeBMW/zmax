#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚀 Z-MAX 标准打开流程 (老倪 2026-10-12 定的规矩)

老倪原话:
    「现在确定一下 zmax 项目的标准打开流程, 第一步, 打开, 加载 zmax 项目;
      第二步, 弹出配置中心的窗口, 在配置中心, 确定配置, 然后统一打开工程」

标准流程 (两步, 与本脚本一一对应)
    第一步  `zmax_open.py step1`  : ①确认控制台在跑 (没跑就起) ②等工程状态自恢复 (场景/数据源/活跃任务)
                                   ③把配置中心弹到前台 (老倪第二步的"弹出配置中心的窗口")
                                   ④打印当前配置摘要 (活跃任务/场景/配方/工艺步数/启用节点/档位)
    第二步  `zmax_open.py step2`  : ①按绑定真源确定任务 (可选 --activate 真激活) ②应用场景到画布 (ss_scene_switch)
                                   ③统一打开工程 = 状态空间画布 + 3D 场景 + 信号分析
                                   ④回到配置中心并选中该任务行 ⑤逐条报结果 (真值来自控制台状态文件)
    一步到底 `zmax_open.py auto`  : step1 + step2 (开机/无人值守走这条)
    只看现状 `zmax_open.py status`

真源口径 (不另算一套)
    · 活跃任务/场景 → config/ss_task_binding.json active_task  (tools/ss_task_bind.py 是生产者)
    · 配置参数      → outputs/config_sheets/配置单_<TASK>_latest.json (tools/config_sheet.py 是生产者)
    · 控制台状态    → /tmp/zmax_console_state.json (控制台自己写的当前页/上一步动作, 带时间戳)
    · 窗口          → wmctrl -l (真窗口, 不是自述)

安全: 本脚本只做「启动控制台 / 写导航命令 / 打开窗口」, **不下发任何运动指令**;
      真机动作仍由 8793 授权窗 (motion_armed) 单独管控, 与本流程无关。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAV = "/tmp/zmax_nav_cmd"
CONSOLE_STATE = "/tmp/zmax_console_state.json"
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")
SHEET_DIR = os.path.join(ROOT, "outputs", "config_sheets")
SCENE_SWITCH = os.path.join(ROOT, "tools", "ss_scene_switch.py")
STUDIO_CTL = os.path.join(ROOT, "tools", "studio_ctl.sh")

WIN_CONSOLE = "XSpace ZMAX"
WIN_3D = "3D场景"
WIN_SIGNAL = "Graphic 信号分析"
PAGE_CONFIG = ("配置", "配置中心")


def _log(msg=""):
    print(msg, flush=True)


def _run(cmd, timeout=120, **kw):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT, **kw)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                                       # noqa: BLE001
        return 1, str(e)


def _wmctrl():
    """真窗口列表: [(win_id, x, y, w, h, title)]"""
    try:
        r = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True, timeout=15,
                           env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")})
    except Exception:                                                            # noqa: BLE001
        return []
    out = []
    for ln in (r.stdout or "").splitlines():
        p = ln.split(None, 7)
        if len(p) < 8:
            continue
        try:
            out.append((p[0], int(p[2]), int(p[3]), int(p[4]), int(p[5]), p[7]))
        except Exception:                                                        # noqa: BLE001
            continue
    return out


def _wins_matching(*subs):
    return [w for w in _wmctrl() if any(s in w[5] for s in subs)]


def _state(max_age=None):
    """控制台状态文件 (控制台自己写的); max_age 秒内才算新鲜。"""
    try:
        d = json.load(open(CONSOLE_STATE, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        return {}
    if max_age is not None:
        try:
            if time.time() - float(d.get("epoch") or 0) > float(max_age):
                return {}
        except Exception:                                                        # noqa: BLE001
            return {}
    return d


def _binding():
    try:
        return json.load(open(BINDING, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        return {}


def _sheet(task):
    """配置单摘要 (真源 = config_sheet.py 产物)。"""
    if not task:
        return {}
    p = os.path.join(SHEET_DIR, "配置单_%s_latest.json" % task)
    if not os.path.isfile(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        return {}
    return d if isinstance(d, dict) else {}


def _dig(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
    return default if d is None else d


def _summary(task):
    """人话摘要 (真源 = config_sheet.py 产出的配置单; 缺就如实标缺, 不编数字)。"""
    s = _sheet(task)
    b = _binding()
    rows = []
    rows.append(("活跃任务", task or _dig(b, "active_task", default="?")))
    rows.append(("参数真源", ("配置单 %s" % os.path.relpath(
        os.path.join(SHEET_DIR, "配置单_%s_latest.json" % task), ROOT)) if s
        else "绑定真源 config/ss_task_binding.json (还没导出配置单)"))
    if not s:
        return rows
    t = s.get("任务") or {}
    for lab, v in (("任务名", t.get("name")), ("配方", t.get("recipe_type")),
                   ("场景", "%s %s" % (t.get("场景") or "", t.get("场景色") or "")),
                   ("场景ID", t.get("SCN")), ("站点", t.get("site")), ("ss_mode", t.get("ss_mode"))):
        if v:
            rows.append((lab, str(v).strip()))
    st = t.get("工艺步骤")
    if isinstance(st, list) and st:
        rows.append(("工艺", "%d 步: %s" % (len(st), " → ".join(
            str((x.get("name") if isinstance(x, dict) else x)) for x in st)[:110])))
    for lab, key in (("适用段", "适用段"), ("档位", "档位"), ("参数覆盖", "参数覆盖")):
        v = t.get(key)
        if isinstance(v, dict):
            rows.append((lab, "%d 项" % len(v)))
        elif isinstance(v, list):
            rows.append((lab, "%d 项" % len(v)))
    c = s.get("画布") or {}
    if c:
        rows.append(("画布工程", "%s · %s 节点 / %s 连线 · 启用 %s"
                     % (c.get("工程") or "?", c.get("节点"), c.get("连线"), c.get("启用节点数"))))
    pr = s.get("参数注册表") or {}
    if pr.get("总数"):
        rows.append(("参数注册表", "%s 项 (%s)" % (pr.get("总数"),
                                                 " · ".join("%s%d" % (k, v) for k, v in
                                                            (pr.get("分组计数") or {}).items())[:90])))
    for lab, key in (("标定真源", "标定真源"), ("点位台账", "点位台账")):
        v = s.get(key)
        if isinstance(v, list):
            rows.append((lab, "%d 项" % len(v)))
    blk = t.get("blocked_by_site")
    if blk:
        rows.append(("缺口", "缺站点几何 %d 项 (有缺口的项不进默认档)" % len(blk)))
    gen = _dig(s, "_meta", "generated_at")
    if gen:
        rows.append(("配置单时间", str(gen)))
    return rows


def console_running():
    return bool(_wins_matching(WIN_CONSOLE))


def ensure_console(wait_s=600, start=True):
    """确保控制台在跑; 返回 (ok, 说明)。不在跑且 start=True 就拉起并等就绪。"""
    if console_running():
        return True, "控制台已在运行"
    if not start:
        return False, "控制台没在运行 (--no-start: 不自动拉起)"
    if not os.path.isfile(STUDIO_CTL):
        return False, "找不到 %s" % STUDIO_CTL
    _log("▶ 控制台没在跑 ⇒ 正在拉起 (tools/studio_ctl.sh start)…")
    try:
        subprocess.Popen(["bash", STUDIO_CTL, "start"], cwd=ROOT, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:                                                        # noqa: BLE001
        return False, "拉起失败: %s" % e
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(5)
        if console_running():
            return True, "控制台已就绪 (等了 %.0fs)" % (time.time() - t0)
        if int(time.time() - t0) % 30 < 5:
            _log("   … 等待控制台窗口出现 (已 %.0fs / 上限 %ds)" % (time.time() - t0, wait_s))
    return False, "等到 %ds 控制台窗口还没出现 (查 tools/studio_ctl.sh status 与日志)" % wait_s


def send_nav(*cmds):
    with open(NAV, "w", encoding="utf-8") as f:
        f.write("\n".join(cmds) + "\n")
    return list(cmds)


def _wait_for(fn, timeout, step=1.0, label=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                return True
        except Exception:                                                        # noqa: BLE001
            pass
        time.sleep(step)
    return False


def step1(args):
    """第一步: 打开 + 加载 zmax 项目 + 弹配置中心 (+ 配置摘要)。"""
    _log("═══ 第一步 · 打开并加载 zmax 项目 ═══")
    ok, why = ensure_console(wait_s=args.wait, start=not args.no_start)
    _log("  %s 控制台: %s" % ("✅" if ok else "❌", why))
    if not ok:
        return 1
    st = _state(max_age=args.state_max_age)
    if st:
        _log("  ✅ 工程状态自恢复: 场景 %s · 数据源 %s · 存档任务 %s · 当前页 %s"
             % (st.get("scene") or st.get("scene_dir") or "?", st.get("src_state") or "?",
                st.get("task") or "?", st.get("page") or "?"))
    else:
        _log("  ⚠️ 还没读到控制台状态文件 %s (老版本控制台可能只有第二步才写)" % CONSOLE_STATE)
    _log("  ▶ 弹出配置中心…")
    _t0 = time.time()
    send_nav("config")
    # ⚠️ 必须等**本次**写入 (epoch ≥ 发命令时刻) —— 状态文件跨进程残留, 只判 page 会把上次的当本次 (实测踩到)
    hit = _wait_for(lambda: (_state().get("page") in PAGE_CONFIG
                            and float(_state().get("epoch") or 0) >= _t0 - 2), args.wait_page)
    st = _state()
    if hit:
        _log("  ✅ 配置中心已在前台 (状态文件: page=%s)" % st.get("page"))
    else:
        _log("  ⚠️ 状态文件还没显示「配置中心」(page=%s) —— 请在界面上确认; 老版本控制台不写状态文件"
             % (st.get("page") or "无"))
    task = st.get("task") or _dig(_binding(), "active_task", default="")
    _log("  ── 当前配置 ──")
    for k, v in _summary(task):
        _log("     %-10s %s" % (k, v))
    _log("")
    _log("  下一步: 在配置中心确认任务/场景 → 运行  python tools/zmax_open.py step2")
    _log("          (或点配置中心那个「🚀 确认配置 · 统一打开工程」按钮)")
    return 0 if hit else 1


def step2(args):
    """第二步: 确定配置 → 统一打开工程 (画布 + 3D 场景 + 信号分析)。"""
    _log("═══ 第二步 · 确定配置 → 统一打开工程 ═══")
    ok, why = ensure_console(wait_s=60, start=False)
    _log("  %s 控制台: %s" % ("✅" if ok else "❌", why))
    if not ok:
        _log("  ⇒ 先跑第一步: python tools/zmax_open.py step1")
        return 1
    task = (args.task or _dig(_binding(), "active_task", default="") or "").strip()
    if not task:
        _log("  ❌ 绑定真源里没有 active_task, 也没给 --task")
        return 1
    if args.activate:
        rc, out = _run([sys.executable, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--activate", task])
        _log("  %s 激活任务 %s: %s" % ("✅" if rc == 0 else "❌", task, out.strip().splitlines()[-1][:120] if out.strip() else ""))
    else:
        _log("  ·  任务 (绑定真源 active_task): %s" % task)
    rc, out = _run([sys.executable, SCENE_SWITCH, "--task", task])
    _last = (out.strip().splitlines() or [""])[-1][:140]
    _log("  %s 应用场景: %s" % ("✅" if rc == 0 else "⚠️", _last))
    _log("  ▶ 统一打开工程 (状态空间画布 · 3D 场景 · 信号分析)…")
    _t0 = time.time()
    send_nav("open_all")
    # 同理: 只认本次回执 (状态文件跨进程残留)
    got = _wait_for(lambda: (isinstance(_state().get("open_all_ok"), bool)
                             and float(_state().get("epoch") or 0) >= _t0 - 2), args.wait_open)
    used = "open_all (控制台内同源执行体)"
    if not got:
        used = "回退三连命令 (老版本控制台没有 open_all 命令)"
        _log("  ·  open_all 命令没回执 ⇒ %s" % used)
        send_nav("ss_canvas", "ss_3d", "monitor")
        _wait_for(lambda: bool(_wins_matching(WIN_3D, WIN_SIGNAL)), args.wait_open)
    st = _state()
    steps = st.get("open_all_steps") or []
    if steps:
        for s in steps:
            _log("  %s %s : %s" % ("✅" if s.get("ok") else "❌",
                                   s.get("name"), (s.get("detail") or "")[:140]))
    # 窗口是延迟开的 (3D/信号分析 各延迟 0.7/0.9s 才建窗, 而回执先落) ⇒ 有界等窗口到齐再报,
    #   否则会把"还没开出来"假报成"窗口不在" (实测踩到)
    _wait_for(lambda: bool(_wins_matching(WIN_3D)) and bool(_wins_matching(WIN_SIGNAL)), 25)
    _log("  ── 窗口真值 (wmctrl) ──")
    wins = [("状态空间画布/控制台", _wins_matching(WIN_CONSOLE)), ("3D 场景", _wins_matching(WIN_3D)),
            ("信号分析", _wins_matching(WIN_SIGNAL))]
    n_ok = 0
    for lab, ws in wins:
        if ws:
            n_ok += 1
            w = ws[0]
            _log("     ✅ %-16s %s  (%dx%d @ %d,%d)  「%s」" % (lab, w[0], w[3], w[4], w[1], w[2], w[5][:48]))
        else:
            _log("     ❌ %-16s 窗口不在" % lab)
    ok_all = (n_ok >= 2) and (bool(st.get("open_all_ok")) or not steps)
    _log("")
    _log("  路径: %s" % used)
    _log("  %s 统一打开工程 %s" % ("✅" if ok_all else "⚠️", "完成" if ok_all else "未全绿 (逐条见上)"))
    return 0 if ok_all else 1


def status(args):
    """只看现状, 不改任何东西。"""
    _log("═══ Z-MAX 打开流程现状 ═══")
    _log("  控制台: %s" % ("✅ 在跑 (XSpace Studio 窗口在)" if console_running() else "❌ 没在跑"))
    st = _state()
    if st:
        age = time.time() - float(st.get("epoch") or 0)
        _log("  状态文件: page=%s · task=%s · scene=%s · last_action=%s · 帧龄 %.0fs%s"
             % (st.get("page") or "?", st.get("task") or "?", st.get("scene") or "?",
                st.get("last_action") or "-", age,
                "  ⚠️ 陈旧(上一进程残留)" if age > 120 else ""))
    else:
        _log("  状态文件: 无 (%s)" % CONSOLE_STATE)
    for lab, subs in (("画布/控制台", (WIN_CONSOLE,)), ("3D 场景", (WIN_3D,)), ("信号分析", (WIN_SIGNAL,))):
        ws = _wins_matching(*subs)
        _log("  窗口 %-10s %s" % (lab, ("%s (%dx%d @ %d,%d)" % (ws[0][0], ws[0][3], ws[0][4], ws[0][1], ws[0][2]))
                                 if ws else "❌ 不在"))
    b = _binding()
    _log("  绑定真源: active_task=%s (canvas %s 节点)" % (_dig(b, "active_task", default="?"),
                                                        _dig(b, "project", "nodes", default="?")))
    for k, v in _summary(_dig(b, "active_task", default="")):
        _log("     %-10s %s" % (k, v))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 标准打开流程 (第一步 加载工程+弹配置中心 / 第二步 确定配置+统一打开工程)")
    ap.add_argument("cmd", choices=["step1", "step2", "auto", "status"], help="要执行的步骤")
    ap.add_argument("--task", default="", help="任务ID (默认 = 绑定真源 active_task)")
    ap.add_argument("--activate", action="store_true", help="真激活该任务 (写绑定真源 + 台账; 默认只读)")
    ap.add_argument("--no-start", action="store_true", help="控制台没在跑时不要自动拉起")
    ap.add_argument("--wait", type=int, default=600, help="等控制台就绪的上限秒数 (默认 600)")
    ap.add_argument("--wait-page", type=int, default=25, help="等配置中心上前的秒数")
    ap.add_argument("--wait-open", type=int, default=60, help="等统一打开的秒数")
    ap.add_argument("--state-max-age", type=int, default=1800, help="状态文件多久算新鲜 (秒)")
    a = ap.parse_args()
    if a.cmd == "step1":
        return step1(a)
    if a.cmd == "step2":
        return step2(a)
    if a.cmd == "status":
        return status(a)
    rc1 = step1(a)
    _log("")
    rc2 = step2(a)
    return rc1 or rc2


if __name__ == "__main__":
    sys.exit(main())
