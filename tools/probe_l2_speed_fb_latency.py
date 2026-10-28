#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_l2_speed_fb_latency.py — 【只读】Phase 0 · L2 原子技能「速度反馈延迟」逐技能实测。

老倪 2026-10-15: 「一步一步迭代 phase0 所有L2层的原子技能, 速度反馈延迟, 全测」

口径 (速度反馈延迟 = 速度指令到达 → 速度反馈可见, 三段腿分开量, 不混成一个数):
  腿① 引擎→块    : chunk_latest.json 相邻 ts 之差 (= 回路块周期; hz_target 10Hz ⇒ 100ms 标称)
  腿② 块→派发    : 技能派发服务认领新块的时间差 —— 唯一依据 skill_latest.json 的「块帧龄_s」(服务自报, 现测)
  腿③ 派发→反馈  : skill_phys.json 里该技能 v_mms **首次反映新指令值**时的 ts − 那块的 chunk.ts
  (物理腿)       : skill_phys.json 每技能 pose_age_s = 真机位姿反馈帧龄; 停更 ⇒ 记「不可测」并给原因

  主指标 = 腿② + 腿③ = 「指令进块 → 该技能速度反馈落地」的端到端延迟 (逐技能, 同机同钟 time.time())。

做法 (纯读, 不下发任何真机指令, 不改任何服务):
  · 高频采样两个唯一依据文件 (默认 200Hz), 逐技能检测「指令值变化」与「反馈值变化」并配对算 Δt;
  · 指令值来源与派发服务**同一映射** (STAGES + atomic_skills 的 CODE_BY_STAGE, 不手写编号);
  · 配对窗口内没有反馈变化 ⇒ 计一次「未配对」(report 里单列, 不当作 0)。

用法:
  ./gui-venv311/bin/python tools/probe_l2_speed_fb_latency.py --seconds 240 --hz 200
  ./gui-venv311/bin/python tools/probe_l2_speed_fb_latency.py --seconds 20 --smoke
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics as st
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
CHUNK = os.path.join(LIVE, "chunk_latest.json")
PHYS = os.path.join(LIVE, "skill_phys.json")
LATEST = os.path.join(LIVE, "skill_latest.json")
ENGINE = os.path.join(LIVE, "engine_loop_status.json")
OUT_DEF = os.path.join(ROOT, "zmax_data", "eval", "l2_speed_fb_latency.json")

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

# 口径常数 (预先固定并标注, 免得"多小算变化/多大算跟上"两处打架):
CMD_EPS_MMS = 1.0     # 指令或反馈的**速度变化** ≥ 1 mm/s 才算一次真实事件 (滤掉浮点噪声)
RESP_TOL_MMS = 0.5    # 反馈与新指令之差 ≤ 0.5 mm/s ⇒ 判「已跟上」(未被闸削)
EXPIRE_S = 3.0        # 指令后 3s 内反馈没动静 ⇒ 记「未响应/陈旧」, 不计入延迟


def _codes():
    """技能号↔阶段 唯一依据 (与派发服务同源, 不手写)。取不到就退回 SK01..SK08 顺序号并标注降级。"""
    try:
        from lerobot.policies.left_right.state_space.skills.atomic_skills import (  # noqa: E402
            SKILLS, SKILLS_TRAY)
        m = {}
        for c in list(SKILLS) + list(SKILLS_TRAY):
            m.setdefault(c.stage, c.code)
        if m:
            return m, "atomic_skills 类属性 (与派发服务同源)"
    except Exception as e:                                                     # noqa: BLE001
        return {}, "降级: 技能库导入失败 %s: %s" % (type(e).__name__, str(e)[:60])
    return {}, "降级: 技能库无 stage→code"


def _load(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                          # noqa: BLE001
        return None


def _cmd_map(chunk, code_by_stage):
    """块里逐技能的速度指令 (mm/s): st = STAGES[stage_idx + i] (与派发服务同一映射)。"""
    out = {}
    if not isinstance(chunk, dict):
        return out
    u = chunk.get("u") or []
    try:
        si = int(chunk.get("stage_idx") or 0)
    except Exception:                                                          # noqa: BLE001
        si = 0
    for i, a in enumerate(u):
        j = si + i
        if j >= len(STAGES):
            break
        stg = STAGES[j]
        try:
            v = math.sqrt(sum(float(x) * float(x) for x in list(a)[:3])) * 1000.0
        except Exception:                                                      # noqa: BLE001
            continue
        out[code_by_stage.get(stg, "SK%02d" % (j + 1))] = {"v_mms": v, "stage": stg, "step": i,
                                                          "cur": (i == 0)}
    return out


def _pct(xs, q):
    if not xs:
        return None
    ys = sorted(xs)
    k = (len(ys) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return round(ys[lo] + (ys[hi] - ys[lo]) * (k - lo), 2)


def probe(seconds: float, hz: float, code_by_stage, quiet=False) -> dict:
    period = 1.0 / max(1.0, hz)
    t_end = time.time() + seconds
    # 逐技能状态: 待配对指令队列 (FIFO) / 上一条反馈值
    cmd_prev, fb_prev, pend = {}, {}, {}
    events = {}
    miss = {}            # code → 指令变化但窗口内反馈未动的次数
    cur_n = {}           # code → 该技能作为「当前阶段(i=0)」出现的块数
    chunk_ts_seq, phys_ts_seq, block_age, pose_age = [], [], [], []
    n_samp = n_chunk_read = n_phys_read = 0
    t_last_block_seen = None
    while time.time() < t_end:
        t0 = time.perf_counter()
        ck = _load(CHUNK)
        ph = _load(PHYS)
        lt = _load(LATEST)
        if ck:
            n_chunk_read += 1
            cts = ck.get("ts")
            if isinstance(cts, (int, float)):
                if not chunk_ts_seq or abs(cts - chunk_ts_seq[-1]) > 1e-9:
                    chunk_ts_seq.append(float(cts))
                t_last_block_seen = float(cts)
        if ph:
            n_phys_read += 1
            pts = ph.get("ts")
            if isinstance(pts, (int, float)):
                phys_ts_seq.append(float(pts))
            _m = ph.get("skills") or {}
            _pose = ph.get("pose") or {}
            if isinstance(_pose.get("pose_age_s"), (int, float)):
                pose_age.append(float(_pose["pose_age_s"]))
            for code, r in _m.items():
                if code == "_元" or not isinstance(r, dict):
                    continue
                v = r.get("v_mms")
                if not isinstance(v, (int, float)) or v < 0:
                    continue
                miss.setdefault(code, 0)
                q = pend.get(code) or []
                if q and isinstance(pts, (int, float)):
                    v0 = fb_prev.get(code)
                    moved = (v0 is not None and abs(v - v0) > CMD_EPS_MMS)      # 反馈真的动了
                    for _i, e in enumerate(q):
                        reached = abs(v - e["cmd_v"]) <= max(RESP_TOL_MMS, 0.01 * abs(e["cmd_v"]))
                        if not (reached or moved):
                            continue
                        if pts < e["t_cmd"] - 1e-3:                                  # 反馈早于指令 ⇒ 不配
                            continue
                        dt_ms = (float(pts) - e["t_cmd"]) * 1000.0
                        events.setdefault(code, []).append({
                            "t_cmd": round(e["t_cmd"], 4), "t_fb": round(float(pts), 4),
                            "dt_ms": round(dt_ms, 2), "cmd_v_mms": round(e["cmd_v"], 3),
                            "prev_v_mms": round(e["prev_v"], 3), "fb_v_mms": round(v, 3),
                            "到达": bool(reached), "削过": bool(not reached and moved),
                            "stage": e["stage"], "step": e["step"]})
                        del q[:_i + 1]
                        break
                fb_prev[code] = v
        if ck:
            for code, c in _cmd_map(ck, code_by_stage).items():
                cts = ck.get("ts")
                if not isinstance(cts, (int, float)):
                    continue
                if c.get("cur"):                      # 该技能是「当前阶段」(i=0)
                    cur_n[code] = cur_n.get(code, 0) + 1
                p = cmd_prev.get(code)
                if p is None or abs(c["v_mms"] - p["v_mms"]) > CMD_EPS_MMS:
                    # 真实速度阶跃 (≥1mm/s): 记一条指令事件 (带上一拍速度, 便于判"跟上/被削")
                    q = pend.setdefault(code, [])
                    q.append({"t_cmd": float(cts), "cmd_v": c["v_mms"],
                              "prev_v": (p or {}).get("v_mms", c["v_mms"]),
                              "stage": c["stage"], "step": c["step"]})
                    if len(q) > 8:                       # 队列积压 ⇒ 最早的算未响应 (不静默丢)
                        q.pop(0)
                        miss[code] = miss.get(code, 0) + 1
                    cmd_prev[code] = c
        if isinstance((lt or {}).get("块帧龄_s"), (int, float)):
            block_age.append(float((lt or {})["块帧龄_s"]))
        # 过期: 指令后 EXPIRE_S 内反馈没动静 ⇒ 记「未响应/陈旧」(不计入延迟)
        _now = time.time()
        for code, q in list(pend.items()):
            while q and (_now - q[0]["t_cmd"]) > EXPIRE_S:
                q.pop(0)
                miss[code] = miss.get(code, 0) + 1
        n_samp += 1
        if not quiet and n_samp % max(1, int(hz * 15)) == 0:
            tot = sum(len(v) for v in events.values())
            print("  … %4.0fs 采样 %d · 配对 %d 条" % (seconds - (t_end - time.time()), n_samp, tot), flush=True)
        slp = period - (time.perf_counter() - t0)
        if slp > 0:
            time.sleep(slp)
    # 结构腿
    d_blk = [round((b - a) * 1000.0, 2) for a, b in zip(chunk_ts_seq, chunk_ts_seq[1:]) if 0 < (b - a) < 5]
    d_tick = [round((b - a) * 1000.0, 3) for a, b in zip(phys_ts_seq, phys_ts_seq[1:]) if 0 < (b - a) < 1]
    per_skill = {}
    all_dt = []
    for code in sorted(set(list(events) + list(fb_prev) + list(cmd_prev) + list(cur_n))):
        ev = events.get(code) or []
        dts = [e["dt_ms"] for e in ev if e["到达"]]          # 延迟总体 = 只算「反馈到达新指令」的
        cut_dts = [e["dt_ms"] for e in ev if e["削过"]]
        all_dt += dts
        per_skill[code] = {
            "stage": (cmd_prev.get(code) or {}).get("stage") or ((ev[-1]["stage"]) if ev else None),
            "n": len(dts), "P50_ms": _pct(dts, 0.5), "P95_ms": _pct(dts, 0.95),
            "min_ms": (round(min(dts), 2) if dts else None), "max_ms": (round(max(dts), 2) if dts else None),
            "到达(未被削)": len(dts), "削过(值不跟随)": len(cut_dts),
            "削过_P50_ms": _pct(cut_dts, 0.5),
            "未响应_3s内反馈不动": int(miss.get(code, 0)),
            "当前阶段块数": int(cur_n.get(code, 0)), "样本不足": len(dts) < 20,
            "样本": [e for e in ev if e["到达"]][:60],
            "样本_削过": [e for e in ev if e["削过"]][:20],
        }
    eng = _load(ENGINE) or {}
    return {
        "ts": round(time.time(), 3), "ts_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "口径": "速度反馈延迟 = 指令进块(chunk.ts) → 该技能速度反馈落地(skill_phys.ts); 逐技能",
        "采样": {"hz": hz, "seconds": seconds, "n": n_samp, "chunk_read": n_chunk_read, "phys_read": n_phys_read},
        "腿① 引擎→块_周期_ms": {"P50": _pct(d_blk, 0.5), "P95": _pct(d_blk, 0.95), "n": len(d_blk)},
        "腿② 块→派发_块帧龄_ms": {"现测P50": (round(st.median(block_age) * 1000.0, 2) if block_age else None),
                              "现测Max": (round(max(block_age) * 1000.0, 2) if block_age else None), "n": len(block_age)},
        "腿③ 派发→反馈_ms": {"P50": _pct(d_tick, 0.5), "P95": _pct(d_tick, 0.95), "n": len(d_tick)},
        "物理腿_位姿反馈帧龄_s": {"现测": (round(max(pose_age), 1) if pose_age else None),
                            "说明": ">5s 即停更(派发服务同口径) ⇒ 物理速度反馈不可采"},
        "引擎": {"hz_target": eng.get("hz_target"), "last_ms": eng.get("last_ms"),
               "updated": eng.get("updated"), "cycles": eng.get("cycles"), "M": eng.get("M")},
        "技能": per_skill,
        "全技能合计": {"n": len(all_dt), "P50_ms": _pct(all_dt, 0.5), "P95_ms": _pct(all_dt, 0.95),
                  "min_ms": (round(min(all_dt), 2) if all_dt else None),
                  "max_ms": (round(max(all_dt), 2) if all_dt else None)},
    }


def probe_shm(seconds: float, hz: float, quiet: bool = False) -> dict:
    """逐技能腿: 读派发服务给**每个技能**留的共享内存唯一依据 (60Hz 每拍刷) —— 8 个技能一次全测。

    /dev/shm/zmax_ss_engine/skill_<i>_<stage>.json 里: action(过闸后可执行速度)/step/ts/
    age_s(距认领当前动作的时间 = 该技能速度反馈的迟滞)/block_ts(给它这一拍的块)/big+why(削因)。
    ⇒ 能同时拿到「谁被当前块覆盖(新鲜)」与「谁停在旧块(陈旧)」, 不必等轨迹扫到那一段。
    """
    shm = os.environ.get("ZMAX_SHM_DIR", "/dev/shm/zmax_ss_engine")
    files = sorted(glob.glob(os.path.join(shm, "skill_*.json")))
    if not files:
        return {"ok": False, "note": "共享内存里没有 skill_*.json (派发服务没在跑?)"}
    period = 1.0 / max(1.0, hz)
    t_end = time.time() + seconds
    st = {}
    n = 0
    while time.time() < t_end:
        t0 = time.perf_counter()
        for p in files:
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:                                                  # noqa: BLE001
                continue
            name = os.path.basename(p)
            s = st.setdefault(name, {"stage": d.get("stage"), "age": [], "ivl": [], "big": 0, "n": 0,
                                     "prev": None, "prev_ts": None, "blk_age": [], "v": []})
            if isinstance(d.get("age_s"), (int, float)):
                s["age"].append(float(d["age_s"]))
            if isinstance(d.get("block_ts"), (int, float)):
                s["blk_age"].append(max(0.0, time.time() - float(d["block_ts"])))
            try:
                sig = (d.get("step"), round(float(sum(float(x) ** 2 for x in (d.get("action") or [])[:3]) ** 0.5), 6))
            except Exception:                                                  # noqa: BLE001
                sig = (d.get("step"), None)
            if s["prev"] is not None and sig != s["prev"] and isinstance(d.get("ts"), (int, float)):
                s["ivl"].append(round(float(d["ts"]) - float(s["prev_ts"] or d["ts"]), 4))
                s["n"] += 1
            s["prev"], s["prev_ts"] = sig, d.get("ts")
            if d.get("big"):
                s["big"] += 1
            if isinstance(d.get("action"), list):
                try:
                    s["v"].append(round(float(sum(float(x) ** 2 for x in d["action"][:3]) ** 0.5) * 1000.0, 3))
                except Exception:                                              # noqa: BLE001
                    pass
        n += 1
        if not quiet and n % max(1, int(hz * 20)) == 0:
            print("  … 技能腿 %d 拍" % n, flush=True)
        slp = period - (time.perf_counter() - t0)
        if slp > 0:
            time.sleep(slp)
    out = {}
    for name, s in sorted(st.items()):
        ages, ivl = s["age"], [x for x in s["ivl"] if x > 0]
        out[name.replace(".json", "")] = {
            "stage": s["stage"], "样本": len(ages),
            "age_s_P50": _pct(ages, 0.5), "age_s_P95": _pct(ages, 0.95),
            "age_s_Max": (round(max(ages), 3) if ages else None),
            "反馈更新次数": s["n"], "更新间隔_s_P50": _pct(ivl, 0.5),
            "更新间隔_s_Max": (round(max(ivl), 3) if ivl else None),
            "块新鲜度_s_P50": _pct(s["blk_age"], 0.5), "块新鲜度_s_Max": (round(max(s["blk_age"]), 3) if s["blk_age"] else None),
            "削因拍数": s["big"], "v_mms_P50": _pct(s["v"], 0.5),
        }
    return {"ok": True, "采样": {"hz": hz, "seconds": seconds, "n": n, "技能文件": len(files)}, "逐技能": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=240.0)
    ap.add_argument("--hz", type=float, default=200.0)
    ap.add_argument("--out", default=OUT_DEF)
    ap.add_argument("--smoke", action="store_true", help="只执行一遍打印, 不落盘")
    ap.add_argument("--shm", action="store_true", default=True, help="同时跑逐技能腿 (共享内存, 默认开)")
    ap.add_argument("--no-shm", dest="shm", action="store_false")
    a = ap.parse_args()
    code_by_stage, src_note = _codes()
    print("🎯 L2 原子技能「速度反馈延迟」只读实测 (不下发任何指令)")
    print("   技能号↔阶段唯一依据: %s" % src_note)
    print("   采样 %.0fHz × %.0fs · 唯一依据 %s + %s" % (a.hz, a.seconds,
                                                  os.path.relpath(CHUNK, ROOT), os.path.relpath(PHYS, ROOT)), flush=True)
    r = probe(a.seconds, a.hz, code_by_stage)
    r["技能号唯一依据"] = src_note
    if a.shm:
        print("\n🗂  逐技能腿 (共享内存唯一依据 /dev/shm/zmax_ss_engine/skill_*.json, 60Hz 每拍刷)")
        sh = probe_shm(a.seconds, a.hz)
        r["逐技能腿_共享内存"] = sh
        if sh.get("ok"):
            print("  %-12s %-6s %5s %10s %10s %10s %8s %9s %7s" %
                  ("技能文件", "阶段", "样本", "age_P50s", "age_P95s", "age_Maxs", "更新次数", "块新鲜P50", "削因拍"))
            for k, v in sorted(sh["逐技能"].items()):
                print("  %-12s %-6s %5d %10s %10s %10s %8d %9s %7d" %
                      (k, v["stage"], v["样本"], v["age_s_P50"], v["age_s_P95"], v["age_s_Max"],
                       v["反馈更新次数"], v["块新鲜度_s_P50"], v["削因拍数"]))
    t = r["全技能合计"]
    print("\n腿① 引擎→块周期: P50 %s ms · P95 %s ms (n=%s)" %
          (r["腿① 引擎→块_周期_ms"]["P50"], r["腿① 引擎→块_周期_ms"]["P95"], r["腿① 引擎→块_周期_ms"]["n"]))
    print("腿② 块→派发块帧龄: P50 %s ms · Max %s ms" %
          (r["腿② 块→派发_块帧龄_ms"]["现测P50"], r["腿② 块→派发_块帧龄_ms"]["现测Max"]))
    print("腿③ 派发拍期:     P50 %s ms · P95 %s ms (n=%s)" %
          (r["腿③ 派发→反馈_ms"]["P50"], r["腿③ 派发→反馈_ms"]["P95"], r["腿③ 派发→反馈_ms"]["n"]))
    print("物理腿 位姿反馈帧龄: %s s %s" % (r["物理腿_位姿反馈帧龄_s"]["现测"], r["物理腿_位姿反馈帧龄_s"]["说明"]))
    print("\n逐技能「指令阶跃 → 反馈跟上」延迟:")
    print("  %-6s %-6s %6s %6s %9s %9s %9s %9s %6s %6s %8s" %
          ("技能", "阶段", "n", "当前块", "P50_ms", "P95_ms", "min", "max", "到达", "削过", "未响应"))
    for code in sorted(r["技能"]):
        s = r["技能"][code]
        print("  %-6s %-6s %6d %6d %9s %9s %9s %9s %6d %6d %8d%s" %
              (code, s["stage"] or "-", s["n"], s["当前阶段块数"], s["P50_ms"], s["P95_ms"], s["min_ms"], s["max_ms"],
               s["到达(未被削)"], s["削过(值不跟随)"], s["未响应_3s内反馈不动"], "  (样本不足)" if s["样本不足"] else ""))
    t = r["全技能合计"]
    print("  %-6s %-6s %5d %5s %9s %9s %9s %9s" % ("合计", "-", t["n"], "-", t["P50_ms"], t["P95_ms"], t["min_ms"], t["max_ms"]))
    if not a.smoke:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=1)
        print("\n📄 落盘: %s" % os.path.relpath(a.out, ROOT))
    return r


if __name__ == "__main__":
    main()
