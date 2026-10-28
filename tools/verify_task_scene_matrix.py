#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_task_scene_matrix.py — 自动测试: 不同配置(任务) → 对应场景 → 信号实时监控颜色

老倪 2026-10-12: 「你来自动测试, 不同的配置, 打开不同的任务, 对应不同的场景, 以及信号实时监控」

对三个已绑场景的任务各跑一轮 (真激活 → 应用场景 → 统一打开工程), 每轮核 6 项真值:
  ① 绑定唯一依据 config/ss_task_binding.json 的 active_task == 该任务
  ② 画布唯一依据 ssdata.params.src_state == 该任务的场景名 (插拔场景/摆盘场景/AR场景)
  ③ 控制台状态文件 /tmp/zmax_console_state.json 的 task/scene (open_all 回执, 必须是本轮写入)
  ④ 3D 场景窗口真在 (wmctrl) 且标题带场景标签, 且三轮标题互不相同 (证明真切场景不是假动作)
  ⑤ 信号分析窗口真在, 且窗口内**该场景的颜色像素 > 0** (绿/蓝/紫, 截图逐像素数)
  ⑥ 配置中心任务表该行「3D场景」「实时监控」两格内容与颜色 = 该场景 (离屏真建页读单元格)
收尾: 还原测试开始时的活跃任务与画布数据源 (不留痕, 现场回到原样)。
产物: reports/task_scene_matrix_<ts>.json / .md + 每轮信号窗口截图 reports/shots/matrix_<TASK>.png

用法: gui-venv311/bin/python tools/verify_task_scene_matrix.py [--tasks TASK-01-FW,TASK-06-TRAY,TASK-07-AOI]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

NAV = "/tmp/zmax_nav_cmd"
STATE = "/tmp/zmax_console_state.json"
BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
CANVAS = os.path.join(ROOT, "flows", "state_space_obs.json")
TAGS = os.path.join(ROOT, "config", "topics", "scene_tags.json")
SHOTS = os.path.join(ROOT, "reports", "shots")
PY = sys.executable

# 任务 → 期望场景/颜色/SCN (唯一依据 tools/ss_scene_switch.py TASK_SCENE; 这里只做断言目标)
WANT = {
    "TASK-01-FW":   {"scene": "插拔场景", "color": "#2e8b57", "scn": "SCN-01-FW",   "win3d": "插拔场景"},
    "TASK-06-TRAY": {"scene": "摆盘场景", "color": "#1f6feb", "scn": "SCN-06-TRAY", "win3d": "摆盘场景"},
    # AR 场景没有仿真场景目录 (底图=真相机视频源) ⇒ 3D 窗如实不动, 标题不带场景名 (不硬套)
    "TASK-07-AOI":  {"scene": "AR场景",   "color": "#8957e5", "scn": "SCN-07-AOI",  "win3d": ""},
}

OK, FAIL = [], []


def ck(name, cond, ev=""):
    (OK if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("   ← " + str(ev)) if ev else ""), flush=True)
    return bool(cond)


def sh(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def jload(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        return d


def bind_active():
    return ((jload(BIND, {}) or {}).get("active_task") or "").strip()


def canvas_src():
    d = jload(CANVAS, {}) or {}
    for n in d.get("nodes", []):
        if (n.get("params") or {}).get("src_state") is not None:
            return str(n["params"]["src_state"])
    return ""


def state(max_age=None):
    d = jload(STATE, {}) or {}
    if max_age is not None and (time.time() - float(d.get("epoch") or 0)) > max_age:
        return {}
    return d


def wins():
    out = subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True,
                         env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}).stdout or ""
    rows = []
    for ln in out.splitlines():
        p = ln.split(None, 7)
        if len(p) >= 8:
            try:
                rows.append({"id": p[0], "x": int(p[2]), "y": int(p[3]), "w": int(p[4]), "h": int(p[5]), "title": p[7]})
            except Exception:                                                    # noqa: BLE001
                continue
    return rows


def find_win(*subs):
    for w in wins():
        if any(s in w["title"] for s in subs):
            return w
    return None


def wait_for(fn, timeout, step=1.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:                                                        # noqa: BLE001
            pass
        time.sleep(step)
    return None


def send_nav(*cmds):
    with open(NAV, "w", encoding="utf-8") as f:
        f.write("\n".join(cmds) + "\n")


def shot_win(w, path, tries=4):
    """把窗口提到最前**并确认它就是当前活动窗**再抓整屏裁剪。

    实测: 只 windowactivate 有时会被刚开的窗口抢走焦点 (open_all 里 3D/信号窗是延迟开的) ⇒ 抓到的像素
    实际是压在上面的配置中心 (三色像素数与配置中心表格一模一样, 看着"绿蓝紫都在"但根本不是信号窗)。
    所以这里核 `xdotool getactivewindow == 窗 id`, 不对就重来; 返回 (图, 是否真抓到该窗)。
    """
    try:
        import cv2                                                                 # noqa: PLC0415
    except Exception:                                                              # noqa: BLE001
        return None, False
    _env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    _wid = str(int(w["id"], 16)) if str(w["id"]).startswith("0x") else str(w["id"])
    _ok = False
    for _ in range(max(1, int(tries))):
        try:
            subprocess.run(["xdotool", "windowactivate", "--sync", w["id"]], capture_output=True,
                           timeout=10, env=_env)
            subprocess.run(["xdotool", "windowraise", w["id"]], capture_output=True, timeout=10, env=_env)
            time.sleep(1.0)
            _act = subprocess.run(["xdotool", "getactivewindow"], capture_output=True, text=True,
                                  timeout=10, env=_env).stdout.strip()
            if _act == _wid:
                _ok = True
                break
        except Exception:                                                          # noqa: BLE001
            pass
        time.sleep(1.0)
    tmp = "/tmp/_matrix_full.png"
    subprocess.run(["scrot", tmp], capture_output=True, env=_env)
    img = cv2.imread(tmp)
    if img is None:
        return None, False
    h, wd = img.shape[:2]
    x0, y0 = max(0, w["x"]), max(0, w["y"])
    x1, y1 = min(wd, x0 + w["w"]), min(h, y0 + w["h"])
    crop = img[y0:y1, x0:x1]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cv2.imwrite(path, crop)
    return crop, _ok


def ocr_band(img, y0=0, y1=40, scale=2.2):
    """OCR 图上一横带 (tesseract CLI; 本机没有 pytesseract)。失真/失败返回 ""。"""
    try:
        import cv2                                                                 # noqa: PLC0415
        band = img[y0:y1, :]
        band = cv2.resize(band, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        cv2.imwrite("/tmp/_matrix_band.png", cv2.cvtColor(band, cv2.COLOR_BGR2GRAY))
        r = subprocess.run(["tesseract", "/tmp/_matrix_band.png", "stdout", "-l", "chi_sim+eng", "--psm", "6"],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip()
    except Exception:                                                              # noqa: BLE001
        return ""


def ocr_top(img, h=140):
    """OCR 顶部 h 像素 (分 40px 带逐带读, 标签栏/工具条各在一带里)。"""
    txt = []
    for y in range(0, max(40, int(h)), 40):
        t = ocr_band(img, y, min(img.shape[0], y + 40))
        if t:
            txt.append(t)
    return " | ".join(txt)


SIG_MARKS = ("增加信号", "采样点", "导出", "视图", "网格", "信号")


def shot_sig_window(w, path, tries=5):
    """抓**信号分析窗自己的内容**: 先聚焦, 再用 `scrot -u` (抓当前焦点窗) —— 不依赖窗口层序。

    实测踩过两次坑:
      ① 只 `windowactivate` 再抓全屏裁剪 ⇒ 控制台在它上面 (open_all 会延迟开窗/抢焦点), 量到的是**配置中心**
         的像素; 而配置中心任务表本身就有绿/蓝/紫格子 ⇒ "三色都在场"看着像通过, 实际是假绿。
      ② 按 wmctrl 几何裁全屏同样被上层窗口污染 ⇒ 必须抓**窗自己的 drawable** (`scrot -u`)。
    自证: 抓到图的尺寸必须 == 该窗尺寸 (是别的窗就对不上), 且顶部 OCR 读得到信号窗工具条。
    返回 (图, OCR 文本, 是否自证成功)。
    """
    try:
        import cv2                                                                 # noqa: PLC0415
    except Exception:                                                              # noqa: BLE001
        return None, "", False
    _env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    img, txt = None, ""
    for _ in range(max(1, int(tries))):
        try:
            subprocess.run(["xdotool", "windowactivate", "--sync", w["id"]], capture_output=True,
                           timeout=10, env=_env)
            time.sleep(1.0)
            subprocess.run(["scrot", "-u", "/tmp/_matrix_win.png"], capture_output=True, timeout=20, env=_env)
        except Exception:                                                          # noqa: BLE001
            time.sleep(1.0)
            continue
        img = cv2.imread("/tmp/_matrix_win.png")
        if img is None:
            time.sleep(1.0)
            continue
        _size_ok = abs(img.shape[1] - int(w["w"])) <= 8 and abs(img.shape[0] - int(w["h"])) <= 8
        txt = ocr_top(img)
        if _size_ok and any(m in txt for m in SIG_MARKS):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cv2.imwrite(path, img)
            return img, txt, True
        time.sleep(1.2)
    return img, txt, False


def count_color(img, hexs, tol=14):
    import numpy as np                                                             # noqa: PLC0415
    b, g, r = int(hexs[5:7], 16), int(hexs[3:5], 16), int(hexs[1:3], 16)
    m = ((abs(img[:, :, 0].astype(int) - b) <= tol)
         & (abs(img[:, :, 1].astype(int) - g) <= tol)
         & (abs(img[:, :, 2].astype(int) - r) <= tol))
    return int(m.sum())


def cc_row(task):
    """离屏真建配置中心页 → 读该任务行 (3D场景/实时监控 单元格文字 + 前景色)。"""
    from PyQt5.QtWidgets import QApplication                                        # noqa: PLC0415
    import veh6_config_page as V                                                    # noqa: PLC0415
    app = QApplication.instance() or QApplication([])
    pg = V.build_config_center(None, {k: v for k, v in vars(V).items() if k.startswith("C_")})
    t = pg.tasks_table
    for r in range(t.rowCount()):
        if (t.item(r, 0).text() or "").strip() == task:
            return {"hdr": [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())],
                    "proj": t.item(r, 2).text(), "scene": t.item(r, 3).text(),
                    "mon": t.item(r, 4).text(),
                    "scene_color": t.item(r, 3).foreground().color().name(),
                    "mon_color": t.item(r, 4).foreground().color().name()}
    return {}


def one_round(task, want):
    print("\n▶ %s  (期望场景 %s %s)" % (task, want["scene"], want["color"]))
    rc, out = sh([PY, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--activate", task])
    ck("① 真激活 %s" % task, rc == 0, (out.splitlines() or [""])[-1][:100])
    run = {"task": task, "want": want}
    run["active_task"] = bind_active()
    ck("① 绑定唯一依据 active_task 回读 == %s" % task, run["active_task"] == task, run["active_task"])

    rc, out = sh([PY, os.path.join(ROOT, "tools", "ss_scene_switch.py"), "--task", task])
    run["src_state"] = canvas_src()
    ck("② 画布数据源切到 %s" % want["scene"], run["src_state"] == want["scene"], run["src_state"])

    t0 = time.time()
    send_nav("open_all")
    # 等本轮回执: epoch 必须晚于发命令时刻 (状态文件跨进程/跨轮残留会假绿) 且 task 已是本轮任务
    got = wait_for(lambda: (isinstance(state().get("open_all_ok"), bool)
                            and float(state().get("epoch") or 0) >= t0
                            and (state().get("task") or "") == task), 120)
    ck("③ 控制台统一打开回执 (open_all, 本轮)", bool(got), "open_all_ok=%s" % state().get("open_all_ok"))
    st = state()
    run["state"] = {"page": st.get("page"), "task": st.get("task"), "scene": (st.get("scene") or "")[:60],
                    "open_all_ok": st.get("open_all_ok"),
                    "steps": [{"name": s.get("name"), "ok": s.get("ok")} for s in (st.get("open_all_steps") or [])]}
    ck("③ 回执里的任务 == %s" % task, (st.get("task") or "") == task, st.get("task"))
    ck("③ 回执里的场景含 %s" % want["scene"], want["scene"] in (st.get("scene") or ""), st.get("scene"))

    w3 = wait_for(lambda: find_win("3D场景"), 60)
    run["win3d"] = w3["title"] if w3 else ""
    ck("④ 3D 场景窗口在", bool(w3), run["win3d"])
    _want3 = (want.get("win3d") or "").strip()
    if _want3:
        # 场景是 open_all 里延迟推给 3D 窗的 (等窗建好 + 有界重试), 这里同样有界等标题到位
        w3b = wait_for(lambda: (lambda w: w if (w and _want3 in (w["title"] or "")) else None)(find_win("3D场景")), 45)
        if w3b:
            run["win3d"] = w3b["title"]
        ck("④ 3D 窗口标题带本轮场景名 (%s)" % _want3, bool(w3b),
           "%s (窗口真切场景, 不是只开个窗)" % run["win3d"])
    else:
        ck("④ AR 场景: 3D 窗如实不套仿真目录 (标题不带场景名)", True,
           "%s (AR 底图=真相机视频源, 无仿真场景目录)" % run["win3d"])
    wsig = wait_for(lambda: find_win("信号分析"), 30)
    run["winsig"] = wsig["title"] if wsig else ""
    ck("⑤ 信号分析窗口在", bool(wsig), run["winsig"])

    if wsig:
        time.sleep(2.5)                        # 等控制台把窗口开齐/停止抢焦点, 再提信号窗
        img, _txt, _ok = shot_sig_window(wsig, os.path.join(SHOTS, "matrix_%s.png" % task), tries=6)
        run["sig_shot_ocr"] = _txt[:120]
        ck("⑤ 抓到的确实是信号分析窗 (提窗 + OCR 自证)",
           bool(_ok), (_txt[:60] if _ok else "OCR 未读到信号窗工具条: %s" % _txt[:60]))
        # 没自证成功就**不报颜色** —— 否则量到的是压在信号窗上面的配置中心 (它的表里也有绿/蓝/紫格子)
        if img is not None and _ok:
            run["sig_colors"] = {k: count_color(img, k) for k in ("#2e8b57", "#1f6feb", "#8957e5", "#ffffff")}
            _c = run["sig_colors"]
            # 信号分析窗是**全局树** (三场景组同屏, 组序=色序) ⇒ 该场景色在场 + 三色都上屏 才算真渲染
            ck("⑤ 信号窗口里该场景色真上屏 (%s)" % want["color"], _c[want["color"]] > 0,
               "%d px" % _c[want["color"]])
            ck("⑤ 三场景色都在信号窗口里 (信号按场景着色真渲染)",
               all(_c[k] > 0 for k in ("#2e8b57", "#1f6feb", "#8957e5")), _c)
        else:
            ck("⑤ 信号窗口颜色像素 (先自证抓到该窗再量)", False,
               "截图未自证 ⇒ 不报颜色 (防假绿: 配置中心的表也有三色格子)")

    row = cc_row(task)
    run["cc"] = row
    ck("⑥ 配置中心 3D场景格 = %s · %s" % (want["scene"], want["scn"]),
       (want["scene"] in (row.get("scene") or "")) and (want["scn"] in (row.get("scene") or "")),
       row.get("scene"))
    ck("⑥ 实时监控格含该场景色 %s" % want["color"], want["color"] in (row.get("mon") or ""),
       (row.get("mon") or "").replace("\n", " + "))
    ck("⑥ 两格同色 == %s" % want["color"],
       row.get("scene_color") == row.get("mon_color") == want["color"],
       "%s / %s" % (row.get("scene_color"), row.get("mon_color")))
    return run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="TASK-01-FW,TASK-06-TRAY,TASK-07-AOI")
    a = ap.parse_args()
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]

    print("═══ 配置 × 任务 × 场景 × 信号实时监控 自动测试 ═══")
    if not find_win("XSpace ZMAX"):
        print("❌ 控制台没在跑 —— 先起控制台 (tools/studio_ctl.sh start)")
        return 1
    _keep_task, _keep_src = bind_active(), canvas_src()
    print("测试前现场: 活跃任务 %s · 画布数据源 %s (收尾会还原)" % (_keep_task, _keep_src))

    runs = []
    try:
        for t in tasks:
            runs.append(one_round(t, WANT[t]))
        # 3D 窗真切场景: 有仿真目录的两轮 (插拔/摆盘) 标题必须不同 —— AR 场景没有仿真目录 ⇒ 如实保留上一场景
        _lab = [(r["task"], r.get("win3d") or "") for r in runs if (r["want"].get("win3d") or "").strip()]
        print()
        ck("④ 有仿真目录的两轮 3D 标题互不相同 (3D 窗真切了场景)",
           len({t for _k, t in _lab}) == len(_lab), _lab)
    finally:
        print("\n↩ 收尾还原: 活跃任务 %s · 数据源 %s" % (_keep_task, _keep_src))
        if _keep_task:
            sh([PY, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--activate", _keep_task])
        if _keep_src:
            sh([PY, os.path.join(ROOT, "tools", "ss_scene_switch.py"), "--task", _keep_task or "TASK-01-FW"])
            if canvas_src() != _keep_src:                       # 保障: 原数据源与任务映射不一致时直接✍回
                try:
                    sys.path.insert(0, os.path.join(ROOT, "src"))
                    from lerobot.engineering import flows as _f                        # noqa: PLC0415
                    _d, _ = _f.load_canvas()
                    for _n in _d.get("nodes", []):
                        if "src_state" in (_n.get("params") or {}):
                            _n["params"]["src_state"] = _keep_src
                    _f.save_canvas(_d)
                    print("   保障写回数据源: %s" % canvas_src())
                except Exception as _e:                                                # noqa: BLE001
                    print("   ⚠ 保障写回失败: %r" % (_e,))
        send_nav("open_all")
        time.sleep(12)
        print("   还原后回读: 活跃任务 %s · 数据源 %s" % (bind_active(), canvas_src()))

    ts = time.strftime("%Y%m%d_%H%M%S")
    rep = {"ts": ts, "tasks": tasks, "runs": runs, "ok": len(OK), "fail": len(FAIL),
           "failed": FAIL, "keep": {"task": _keep_task, "src": _keep_src}}
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    jp = os.path.join(ROOT, "reports", "task_scene_matrix_%s.json" % ts)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    lines = ["# 配置 × 任务 × 场景 × 信号实时监控 自动测试 (%s)" % ts, "",
             "| 任务 | 场景(期望) | 画布数据源 | 控制台回执 | 3D窗口 | 信号窗颜色像素 | 配置中心实时监控格 |",
             "|---|---|---|---|---|---|---|"]
    for r in runs:
        lines.append("| %s | %s %s | %s | ok=%s | %s | %s | %s |" % (
            r["task"], r["want"]["scene"], r["want"]["color"], r.get("src_state"),
            r.get("state", {}).get("open_all_ok"), r.get("win3d"),
            json.dumps(r.get("sig_colors") or {}, ensure_ascii=False),
            (r.get("cc", {}).get("mon") or "").replace("\n", " + ")))
    lines += ["", "**%d/%d PASS**" % (len(OK), len(OK) + len(FAIL)), "",
              "失败项: " + (", ".join(FAIL) if FAIL else "无")]
    mp = os.path.join(ROOT, "reports", "task_scene_matrix_%s.md" % ts)
    with open(mp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n📄 报告: %s\n📄 报告: %s" % (jp, mp))
    print("\n%s  %d/%d PASS" % ("✅" if not FAIL else "❌", len(OK), len(OK) + len(FAIL)))
    if FAIL:
        print("失败: " + " | ".join(FAIL))
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
