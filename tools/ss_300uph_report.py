#!/usr/bin/env python3
"""Z-MAX 300UPH 自主进化 · 状态报告 (飞书每 10 分钟)

只读: 不写 /control, 不发真机指令。全部数据来自 zmax_data/ss_live 与 8797 只读接口。
用法: python3 tools/ss_300uph_report.py [--feishu] [--save]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "zmax_data", "ss_live")
AR = "http://127.0.0.1:8797"
RENDER = "http://127.0.0.1:8802"


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return default if default is not None else {}


def jget(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:                                                   # noqa: BLE001
        return {"_err": "%s: %s" % (type(e).__name__, e)}


def age(path):
    try:
        return round(time.time() - os.path.getmtime(path), 1)
    except Exception:                                                        # noqa: BLE001
        return None


def fmt(v, n=4):
    if isinstance(v, float):
        return ("%." + str(n) + "f") % v
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(fmt(x, n) for x in list(v)[:6]) + ("]" if len(v) <= 6 else ", …]")
    if isinstance(v, dict):
        return "{" + ", ".join("%s=%s" % (k, fmt(x, n)) for k, x in list(v.items())[:4]) + "}"
    return str(v)


def section_uph() -> list:
    L = ["【① 节拍 / UPH 目标】"]
    si = jload(os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_insert.json"))
    api = jget(AR + "/api/sim_insert")
    sp = api.get("speed_profile") or {}
    tact = api.get("tact_steady_s") or si.get("tact_steady_s")
    uph = round(3600.0 / float(tact), 1) if tact else None
    L.append("  目标 uph_target = %s   ·   回放标杆 tact_steady_s = %ss ⇒ %.0f UPH"
             % (api.get("uph_target") or si.get("uph_target"), tact, uph or 0))
    L.append("  段表 %s 段 / %s 件 / 总 %ss · 每轮 %s 件"
             % (api.get("n_segs"), api.get("mods"), api.get("total_t"), api.get("mods_per_cycle")))
    if sp:
        L.append("  速度剖面 v=%smm/s · grip=%ss · 金手指检测=%ss · 侧面检测=%ss"
                 % (sp.get("v_mm_s"), sp.get("grip_s"), sp.get("check_golden_s"), sp.get("check_side_s")))
        L.append("  ⚠ 段表里 %s 段全部 arm=none —— 左臂只按等效时间计入, 没有自己的段"
                 % api.get("n_segs"))
    return L


def section_layers() -> list:
    L = ["【② 各层模型 真跑/直通 (实测)】"]
    snap = jload(os.path.join(LIVE, "model_io_snapshot.json"))
    st = {"run": [], "pass": []}
    for g, gv in (snap.get("groups") or {}).items():
        for n in gv.get("nodes", []):
            s = str(n.get("status") or "")
            (st["run"] if s.startswith("实现执行") else st["pass"]).append(
                "%s(%s)" % (n["id"], ("%dms" % int(n.get("ms") or 0))))
    L.append("  真跑 %d: %s" % (len(st["run"]), ", ".join(st["run"])))
    L.append("  直通 %d: %s" % (len(st["pass"]), ", ".join(st["pass"])))
    L.append("  快照龄 %ss" % age(os.path.join(LIVE, "model_io_snapshot.json")))
    return L


def section_signals() -> list:
    L = ["【③ 关键信号 (实测值)】"]
    p = os.path.join(LIVE, "l3_latest.json")
    _raw = jload(p)
    l3 = (_raw.get("out1") if isinstance(_raw.get("out1"), dict) else _raw) or {}
    if l3:
        L.append("  L3 ssdec: %s · degraded=%s · l4_cond_injected=%s · 龄=%ss"
                 % (str(l3.get("nominal_src"))[:44], l3.get("degraded"),
                    l3.get("l4_cond_injected"), age(p)))
        if l3.get("nominal_L3"):
            L.append("     nominal_L3 = %s   base_L2 = %s"
                     % (fmt(l3.get("nominal_L3")), fmt(l3.get("base_L2"))))
    else:
        L.append("  L3 ssdec: 无 l3_latest.json")
    gl = jload(os.path.join(LIVE, "engine_latest.json"))
    if gl:
        L.append("  L2 执行 ssact: action=%s · src=%s"
                 % (fmt(gl.get("action")), str(gl.get("source"))[:40]))
    eng = jget(RENDER + "/state.json")
    t = eng.get("truth") or {}
    if t:
        L.append("  AR 双臂真值: tcpL=%s tcpR=%s" % (fmt(t.get("tcpL")), fmt(t.get("tcpR"))))
    s2 = jget(RENDER + "/status.json")
    L.append("  AR 渲染站: ok=%s n=%s gold_px=%s 帧龄=%ss err=%s"
             % (s2.get("ok"), s2.get("n"), s2.get("gold_px"), s2.get("age_s"),
                str(s2.get("err"))[:40]))
    return L


def section_uph() -> list:
    """300UPH 口径：段表节拍（保守）+ 执行信号推进（状态空间驱动）。"""
    L = ["【③ 300UPH 口径】"]
    p = os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_insert.json")
    d = jload(p)
    tact = d.get("tact_steady_s")
    tgt = d.get("uph_target")
    if tact:
        L.append("  段表节拍 %.2f s/件 ⇒ %d UPH（保守口径）· 目标 %s"
                 % (float(tact), round(3600.0 / float(tact)), tgt))
    tr = jload(os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_transport.json"))
    if tr.get("n_segs"):
        L.append("  左臂段表 sim_transport: %s 段（14 槽 × 8 段）" % tr.get("n_segs"))
    ac = jload(os.path.join(LIVE, "ar_cmd.json"))
    if ac:
        el = ac.get("elapsed_s")
        md = ac.get("mod")
        if el and md:
            L.append("  执行信号: seq=%s mod=%s elapsed=%.1fs ⇒ 累计 %d UPH"
                     % (ac.get("seq"), md, float(el), round(float(md) / (float(el) / 3600.0))))
    return L


def section_blockers() -> list:
    L = ["【④ 仍未闭环（如实）】"]
    items = []
    snap = jload(os.path.join(LIVE, "model_io_snapshot.json"))
    slow = []
    for g, gv in (snap.get("groups") or {}).items():
        for n in gv.get("nodes", []):
            ms = float(n.get("ms") or 0)
            if ms > 300:
                slow.append((n["id"], int(ms)))
    for nid, ms in sorted(slow, key=lambda x: -x[1])[:3]:
        items.append("%s 冷启 %dms（一次性；热态见进程内实测）" % (nid, ms))
    # u_cmd 真读（engine_latest.action 是引擎侧占位恒 0，实值在节点快照 ssact 的 u_cmd）
    snap2 = jload(os.path.join(LIVE, "model_io_snapshot.json"))
    _ucmd = None
    for _g, _gv in (snap2.get("groups") or {}).items():
        for _n in _gv.get("nodes", []):
            if _n.get("id") == "ssact":
                _o2 = _n.get("out1") or {}
                if isinstance(_o2, dict):
                    _ucmd = _o2.get("u_cmd")
    try:
        if _ucmd and all(abs(float(x)) < 1e-9 for x in _ucmd[:4]):
            items.append("ssact u_cmd 全 0（上游无有效动作）")
    except (TypeError, ValueError):
        pass
    l3 = jload(os.path.join(LIVE, "l3_latest.json"))
    _l3 = (l3.get("out1") if isinstance(l3.get("out1"), dict) else l3) or {}
    if _l3.get("degraded"):
        items.append("L3 degraded（模型未出结果，落到测地线块）")
    if _l3.get("l4_cond_injected") is False:
        items.append("L4→L3 条件未注入（ckpt 未训 l4_cond 通道）")
    items.append("段表 arm 字段=none：左右臂两张表并行，非同一张表标注归属")
    items.append(".23 离线：工控机 10082/10083 远程模型未接（本机图像处理口径已对齐）")
    items.append("L5 三个节点（ss_l5/n_dsvl/n_vlm_llm）仍 PURE=False")
    for i, s in enumerate(items, 1):
        L.append("  %d. %s" % (i, s))
    return L


def build() -> str:
    L = ["🤖 Z-MAX 300UPH 自主进化 · 状态报告",
         "时间 %s · 主机 %s · 全程 AR 场景仿真 (真机零指令)"
         % (time.strftime("%F %T"), os.uname().nodename), ""]
    L += section_uph(); L.append("")
    L += section_layers(); L.append("")
    L += section_signals(); L.append("")
    L += section_blockers()
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--feishu", action="store_true")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    txt = build()
    print(txt)
    if a.save:
        p = os.path.join(LIVE, "uph_300_report.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        print("\n已写", p)
    if a.feishu:
        r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "feishu_notify.py"),
                            "--text", txt, "--keyword", "dataworld"],
                           capture_output=True, text=True, timeout=60)
        print("\n飞书:", (r.stdout or r.stderr)[-300:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
