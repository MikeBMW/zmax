#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""proj_state.py — 💾 调试状态自动存档到 .proj 工程文件 (下次接着调)  2026-10-11

老倪原话: 「你要自动保存这种状态到 proj项目文件中, 下次我可以继续调试」

存什么 (全部从真源取, 不手填):
  active_task (config/ss_task_binding.json) · src_state (画布 ssdata 📦 数据源节点 params)
  · scene_id / scene_dir (src_state → data/scene/scenes/<ID>) · 画布真源 md5 · 任务三态快照 · 主参数 M · 版本/时间
写哪: 工程文件 (默认 reports/projects/SS_主工程_任务配置.zmaxproj) 的 **debug_state 段** ——
      原子写 + 自动备份 + 回读校验 (其他段逐字节不动); 文件不存在先用真生产者 tools/ss_task_bind.py --export 生成。
恢复: restore() → 设 ZMAX_SCENE_DIR (场景真源) + 存档任务与当前绑定不一致时走 ss_task_bind --activate;
      画布/标定由 project_file.load_project 负责, 本模块不重复写画布。
自动: 数据源切换 / 活跃属性下拉 后各存一次; 打开工程文件后自动恢复。
CLI: python tools/proj_state.py save|show|restore [--path P] [--reason R]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.environ.get("ZMAX_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS = os.path.join(ROOT, "flows", "state_space_obs.json")          # 画布真源 (软链到 src/.../flows/…)
BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
VERSION = os.path.join(ROOT, "VERSION.md")
DEFAULT_PROJ = os.path.join(ROOT, "reports", "projects", "SS_主工程_任务配置.zmaxproj")
SRC_SCENE_ID = {"插拔场景": "SS-EPI-CORNER", "摆盘场景": "SS-TRAY-PLACE"}
SECTION = "debug_state"


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return d


def _md5(p):
    try:
        h = hashlib.md5()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 16), b""):
                h.update(b)
        return h.hexdigest()[:16]
    except Exception:                                                          # noqa: BLE001
        return None


def _version():
    try:
        with open(VERSION, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    return ln.strip().lstrip("# ").strip()[:40]
    except Exception:                                                          # noqa: BLE001
        pass
    return None


def _src_state():
    """画布上 📦 数据源节点的 src_state (老工程可能是 '仿真' ⇒ 归一成插拔场景)。"""
    c = _j(CANVAS, {}) or {}
    for n in (c.get("nodes") or []):
        p = n.get("params") or {}
        if p.get("src_switch") or p.get("src_state"):
            v = str(p.get("src_state") or "").strip()
            return "插拔场景" if v in ("仿真", "sim", "metaworld") else (v or "真机")
    return ""


def capture():
    """当前调试状态快照 (真源取)。"""
    bind = _j(BIND, {}) or {}
    src = _src_state()
    sid = SRC_SCENE_ID.get(src)
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import ss_task_state as _ts
        st = {r["task_id"]: r["state"] for r in _ts.build(write=False)["tasks"]}
    except Exception:                                                          # noqa: BLE001
        st = {}
    cal = _j(CALIB, {}) or {}
    return {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "zmax_version": _version(),
            "active_task": bind.get("active_task"), "src_state": src, "scene_id": sid,
            "scene_dir": (os.path.join(ROOT, "data", "scene", "scenes", sid) if sid else ""),
            "scene_dir_rel": ("data/scene/scenes/%s" % sid if sid else ""),
            "canvas_md5": _md5(CANVAS), "task_states": st,
            "M": (cal.get("manifold_engine") or {}).get("M"),
            "workspace": "state_space", "note": "继续调试用: 打开工程文件会自动恢复这一段"}


def ensure_proj(path):
    """工程文件不存在 → 用真生产者 (tools/ss_task_bind.py --export) 生成。"""
    if os.path.isfile(path):
        return True, "已存在"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--export", path],
                       capture_output=True, text=True, timeout=600, cwd=ROOT)
    ok = os.path.isfile(path)
    return ok, ("已生成 (%d B)" % os.path.getsize(path) if ok
                else "生成失败: %s" % ((r.stderr or r.stdout or "")[-200:]))


def save(path=None, reason=""):
    """把当前调试状态写进工程文件的 debug_state 段 (原子写 + 备份 + 回读校验)。"""
    path = os.path.abspath(path or DEFAULT_PROJ)
    ok, why = ensure_proj(path)
    if not ok:
        return {"ok": False, "why": why, "path": path}
    proj = _j(path, {}) or {}
    if SECTION in proj:
        proj["_prev_debug_state"] = proj[SECTION]              # 保留上一份, 便于回看
    proj[SECTION] = capture()
    proj[SECTION]["reason"] = reason
    others_before = {k: v for k, v in proj.items() if k not in (SECTION, "_prev_debug_state")}
    bak = ""
    try:
        if os.path.exists(path):
            bak = "%s.bak_%s" % (path, time.strftime("%Y%m%d_%H%M%S"))
            shutil.copy2(path, bak)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(proj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception as e:                                                     # noqa: BLE001
        return {"ok": False, "why": "写盘失败: %s: %s" % (type(e).__name__, e), "path": path}
    back = _j(path, {}) or {}
    same = back.get(SECTION) == proj[SECTION]
    others_ok = {k: v for k, v in back.items() if k not in (SECTION, "_prev_debug_state")} == others_before
    return {"ok": bool(same and others_ok), "path": path, "backup": bak, "readback": same,
            "others_unchanged": others_ok, "state": back.get(SECTION), "why": why}


def restore(path=None, log=None, respect_newer_binding=False):
    """打开工程文件后: 恢复场景真源 + 存档里的活跃任务 (画布由 load_project 负责)。

    respect_newer_binding: 控制台**启动自恢复**传 True —— 操作员在控制台里显式激活的任务
    (绑定真源比工程存档新) 不能被一份更老的存档顶掉。2026-10-13 实测: 激活摆盘 TASK-06-TRAY
    后重启, 被存档里的 TASK-07-AOI 恢复回来 ⇒ 界面「末端工具」判成夹持、实时监控/信号分组的
    场景跟着错, 老倪要的"摆盘末端 x y z"整条链就串了。
    而"打开工程文件"是**显式用户动作** ⇒ 默认 False: 存谁的档就回谁的状态。
    """
    path = os.path.abspath(path or DEFAULT_PROJ)
    proj = _j(path, {}) or {}
    ds = proj.get(SECTION) or {}
    out = {"ok": False, "path": path, "has_state": bool(ds), "applied": {}}
    if not ds:
        out["why"] = "存档里没有 debug_state 段 (老存档) ⇒ 无可恢复"
        return out
    sid = ds.get("scene_id")
    d = ds.get("scene_dir") or (os.path.join(ROOT, "data", "scene", "scenes", sid) if sid else "")
    if d and os.path.isdir(d):
        os.environ["ZMAX_SCENE_DIR"] = d
        try:                                                                   # 已导入的场景模块全局也跟上
            m = sys.modules.get("dreamview_scene_edit")
            if m is not None:
                m.SCENE_DIR = d
                m.OBJECTS3D = os.path.join(d, "objects3d.json")
        except Exception:                                                      # noqa: BLE001
            pass
        out["applied"]["scene_dir"] = d
    else:
        out["applied"]["scene_dir"] = None
        out["scene_why"] = "场景目录不存在或存档没记: %s" % (d or "—")
    # 📌 2026-10-11 实测: 控制台重启时会把画布 src_state 写成默认「真机」(22:39:24 那次), 老倪选的摆盘就丢了
    #   ⇒ 自恢复时按存档把 src_state 写回画布真源 —— 字节级只改这一个值, 其余排版/字节一字不动 (留 .bak)
    _want_src = ds.get("src_state")
    if _want_src:
        try:
            _txt = open(CANVAS, encoding="utf-8").read()
            _cur_src = ""
            try:
                for _n in ((_j(CANVAS, {}) or {}).get("nodes") or []):
                    _p = _n.get("params") or {}
                    if _p.get("src_state"):
                        _cur_src = _p["src_state"]
                        break
            except Exception:                                                   # noqa: BLE001
                _cur_src = ""
            if _cur_src != _want_src:
                import re as _re
                _new = _re.sub(r'("src_state"\s*:\s*")[^"]*(")',
                               lambda m: m.group(1) + _want_src + m.group(2), _txt, count=1)
                if _new != _txt:
                    shutil.copy2(CANVAS, CANVAS + ".bak_before_proj_restore")
                    open(CANVAS, "w", encoding="utf-8").write(_new)
                    print("📌 画布数据源按工程存档回写: %r → %r" % (_cur_src or "(空)", _want_src))
                    out["applied"]["src_state_written"] = _want_src
            else:
                out["applied"]["src_state_written"] = None
        except Exception as _e:                                                 # noqa: BLE001
            print("画布数据源回写跳过: %r" % (_e,))
    want = ds.get("active_task")
    cur = (_j(BIND, {}) or {}).get("active_task")
    out["applied"]["active_task_saved"], out["applied"]["active_task_now"] = want, cur
    # 🔴 2026-10-13: 原来这里**无条件**用存档任务覆盖绑定真源 ⇒ 操作员刚激活的摆盘被更老的存档顶掉。
    #   规则: 启动自恢复时, 绑定真源比工程存档新 ⇒ 听操作员的 (只记差异, 不动绑定)。
    _bnewer = False
    if respect_newer_binding and want and want != cur:
        try:
            _bnewer = os.path.getmtime(BIND) > (os.path.getmtime(path) + 1.0)
        except Exception:                                                       # noqa: BLE001
            _bnewer = False
    if _bnewer:
        out["task_kept"] = ("保留当前 %s —— 绑定真源比工程存档新 (操作员显式激活过), 不回填存档任务 %s"
                            % (cur, want))
        out["applied"]["task_kept"] = cur
        if log:
            log(out["task_kept"])
    elif want and want != cur:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--activate", want],
                           capture_output=True, text=True, timeout=600, cwd=ROOT)
        now = (_j(BIND, {}) or {}).get("active_task")
        out["applied"]["active_task_now"] = now
        out["task_reactivated"] = (now == want)
        if now != want:
            out["task_why"] = "激活失败: %s" % ((r.stderr or r.stdout or "")[-160:])
    out["ok"] = bool(out["applied"].get("scene_dir")) and (not want or out["applied"]["active_task_now"] == want)
    out["src_state"], out["saved_ts"] = ds.get("src_state"), ds.get("ts")
    if callable(log):
        try:
            log("💾 工程文件调试状态已恢复: 场景 %s · 任务 %s (存档 %s)"
                % (os.path.basename(str(d)) or "—", out["applied"]["active_task_now"], ds.get("ts")))
        except Exception:                                                      # noqa: BLE001
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="save", choices=["save", "show", "restore", "capture"])
    ap.add_argument("--path", default=None)
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.cmd == "capture":
        print(json.dumps(capture(), ensure_ascii=False, indent=1)); return 0
    if a.cmd == "show":
        p = os.path.abspath(a.path or DEFAULT_PROJ)
        ds = (_j(p, {}) or {}).get(SECTION) or {}
        print(json.dumps(ds or {"why": "无 debug_state 段: %s" % p}, ensure_ascii=False, indent=1)); return 0
    if a.cmd == "restore":
        r = restore(a.path, log=print); print(json.dumps(r, ensure_ascii=False, indent=1)); return 0 if r.get("ok") else 2
    r = save(a.path, a.reason)
    print("  %s %s · 备份 %s · 回读 %s · 其他段未动 %s"
          % ("✅" if r.get("ok") else "❌", r.get("path"), os.path.basename(r.get("backup") or "—"),
             r.get("readback"), r.get("others_unchanged")))
    if r.get("state"):
        s = r["state"]
        print("     debug_state: 任务 %s · 数据源 %s · 场景 %s · 画布 %s · %s"
              % (s.get("active_task"), s.get("src_state"), os.path.basename(s.get("scene_dir") or ""),
                 s.get("canvas_md5"), s.get("ts")))
    return 0 if r.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
