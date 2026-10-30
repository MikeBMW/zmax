#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""👁️ Z-MAX 记忆层常驻监控 (只读) —— 监控 + 自主进化判据

2026-10-30 老倪: 「保持监控, 自主进化」

每 15s 取一次证, 每 60s 落一行台账; 七条判据逐条给数, 不给形容词:
  ① 回路心跳   canvas_loop.tick 在涨 · age<3s · 单拍 cost<100ms (10Hz 预算) · err 为空
  ② L2 肌肉    ar_muscle.json n 在涨 · 各 kind kl2 相邻采样变化 <3% ⇒ 已收敛 (固化)
  ③ L3 节拍    最近一圈 uph ≥ 300 (tact ≤ 12.0s/件) · 圈墙钟 ≈ acc (无虚报)
  ④ L4 安全    big_jumps=0 (没被线性插值硬拉) · overspeed=0 · v_cap 未被动收紧
  ⑤ 图像位姿   记录器帧龄<3s · 今日帧数在涨 · 图-位姿同拍 skew<50ms
  ⑥ 建图       8801 /map/status ready · 地图产物可读
  ⑦ 零指令     actuator_calls.log 不存在或大小不变 (550C 不发机器人指令)

输出:
  /dev/shm/zmax_mem/watch.json        最新一次 (供页面/CLI 读)
  zmax_data/ss_live/mem_watch.jsonl   每 60s 一行 (留最近 2000 行)
  zmax_data/ss_live/mem_alert.txt     判据翻转时写一次 (不刷屏)
"""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request

ROOT = os.environ.get("WATCH_ROOT", os.path.expanduser("~/zmax"))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
MEM = os.path.join(ROOT, "data", "memory")
OUT_JSON = os.environ.get("WATCH_OUT", "/dev/shm/zmax_mem/watch.json")
OUT_JSONL = os.path.join(LIVE, "mem_watch.jsonl")
ALERT = os.path.join(LIVE, "mem_alert.txt")
REC_STATUS = os.environ.get("WATCH_REC", "/dev/shm/zmax_rec/status.json")
FEED = os.environ.get("ZMAX_MEM_FEED", "/dev/shm/zmax_mem/feed.json")
MAP_URL = os.environ.get("WATCH_MAP", "http://127.0.0.1:8801/map/status")
ACT_LOG = os.path.join(LIVE, "actuator_calls.log")
UPH_MIN = float(os.environ.get("WATCH_UPH_MIN", "300"))
TACT_MAX = float(os.environ.get("WATCH_TACT_MAX", "12.0"))
COST_MAX = float(os.environ.get("WATCH_COST_MS", "100"))
PERIOD = float(os.environ.get("WATCH_PERIOD_S", "15"))
ROW_EVERY = float(os.environ.get("WATCH_ROW_S", "60"))

_prev = {}


def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                          # noqa: BLE001
        return None


def _jlines_tail(p, n=200):
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 256 * 1024))
            ls = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
        out = []
        for ln in reversed(ls[-n:]):
            try:
                out.append(json.loads(ln))
            except Exception:                                  # noqa: BLE001
                pass
        return list(reversed(out))
    except Exception:                                          # noqa: BLE001
        return []


def _age(p):
    try:
        return round(time.time() - os.path.getmtime(p), 2)
    except OSError:
        return None


def _get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:                                          # noqa: BLE001
        return None


def check():
    c = {}
    # ① 回路
    cl = _jload(os.path.join(LIVE, "canvas_loop.json")) or {}
    tick = cl.get("tick")
    c["loop"] = {"tick": tick, "age_s": _age(os.path.join(LIVE, "canvas_loop.json")),
                 "cost_ms": cl.get("cost_ms"), "n_ran": cl.get("n_ran"),
                 "err": (cl.get("err") or "")[:60],
                 "ok": bool(tick is not None and (cl.get("cost_ms") or 999) < COST_MAX
                            and (_age(os.path.join(LIVE, "canvas_loop.json")) or 99) < 3.0
                            and not (cl.get("err") or ""))}
    if _prev.get("tick") is not None and tick is not None:
        d_tick = tick - _prev["tick"]
        # 只在合理区间报频率 (重启/长停顿后的跳变不算速率, 否则会出现 -278Hz 这种假数)
        if 0 < d_tick <= 60 * PERIOD:
            c["loop"]["tick_rate_hz"] = round(d_tick / max(PERIOD, 0.1), 2)
    _prev["tick"] = tick

    # ② L2 肌肉记忆 + 收敛判定
    am = _jload(os.path.join(MEM, "ar_muscle.json")) or {}
    kinds = am.get("kinds") or {}
    n_tot = int(am.get("total_segs") or 0)
    last_cyc = (_jlines_tail(os.path.join(MEM, "ar_cycles.jsonl"), 1) or [{}])[-1]
    kl2 = last_cyc.get("kl2") or {}
    prev_kl = _prev.get("kl2") or {}
    _ds = [abs(float(kl2[k]) - float(prev_kl[k])) for k in kl2 if k in prev_kl]
    drift = round(max(_ds), 4) if _ds else None
    stable = (drift is not None and drift < 0.03)
    n_grow = (_prev.get("n_tot") is not None and n_tot > _prev["n_tot"])
    c["l2"] = {"n_total": n_tot, "kinds": len(kinds), "kl2": kl2,
               "kl2_max_drift": drift, "converged": bool(stable and len(kl2) >= 6),
               "n_growing": n_grow,
               "ok": bool(len(kinds) >= 6 and (n_grow or _prev.get("n_tot") is None))}
    _prev["n_tot"] = n_tot
    _prev["kl2"] = dict(kl2)

    # ③ L3 节拍
    cyc = last_cyc or {}
    uph = cyc.get("uph")
    tact = cyc.get("tact_s")
    acc = cyc.get("acc_s")
    wall = cyc.get("wall_s")
    c["l3"] = {"round": cyc.get("round"), "wall_s": wall, "n_mods": cyc.get("n_mods"),
               "tact_s": tact, "uph": uph, "acc_s": acc, "travel_s": cyc.get("travel_s"),
               "scale": cyc.get("scale"),
               "wall_matches_acc": (abs(float(wall) - float(acc)) < 1.0) if (wall and acc) else None,
               "ok": bool(uph is not None and float(uph) >= UPH_MIN and float(tact or 99) <= TACT_MAX)}

    # ④ L4 安全
    sf = _jload(os.path.join(MEM, "ar_safety.json")) or {}
    c["l4"] = {"v_cap_mm_s": sf.get("v_cap_mm_s"), "dv_cap_mm_s": sf.get("dv_cap_mm_s"),
               "big_jumps": cyc.get("big_jumps"), "big_jump_max_mm": cyc.get("big_jump_max_mm"),
               "jumps_blended": cyc.get("jumps"), "overspeed": int(sf.get("overspeed") or 0),
               "ok": bool(int(cyc.get("big_jumps") or 0) == 0 and int(sf.get("overspeed") or 0) == 0
                          and float(sf.get("v_cap_mm_s") or 0) >= 600)}

    # ⑤ 图像+位姿记录
    rs = _jload(REC_STATUS) or {}
    n_rec = rs.get("n_ok")
    c["record"] = {"src": rs.get("src"), "n_ok": n_rec, "n_today": rs.get("n_today"),
                   "frame_age_s": (round(time.time() - float(rs["t"]), 1) if rs.get("t") else None),
                   "skew_ms_p50": rs.get("skew_ms_p50"),
                   "pose_clock_drift_ms": rs.get("pose_clock_drift_ms"),
                   "disk_gb": rs.get("disk_gb"), "err": rs.get("err") or "",
                   "growing": bool(_prev.get("n_rec") is not None and (n_rec or 0) > _prev["n_rec"]),
                   "ok": bool(rs.get("ok") and (_prev.get("n_rec") is None or (n_rec or 0) > (_prev.get("n_rec") or 0))
                              and abs(float(rs.get("skew_ms_p50") or 0)) < 50)}
    _prev["n_rec"] = n_rec

    # ⑥ 建图
    m = _get(MAP_URL) or {}
    c["map"] = {"ready": m.get("ready"), "state": m.get("state"),
                "points": ((m.get("meta") or {}).get("raw_points") or None),
                "ok": bool(m.get("ready"))}

    # ⑦ 零机器人指令
    try:
        sz = os.path.getsize(ACT_LOG)
        c["no_robot_cmd"] = {"actuator_log_bytes": sz, "ok": sz == 0,
                             "note": "日志不存在/0 字节 = 没有下发过动作"}
    except OSError:
        c["no_robot_cmd"] = {"actuator_log_bytes": None, "ok": True,
                             "note": "actuator_calls.log 不存在 ⇒ 从未下发动作"}

    # 总判 + 待办建议 (自主进化: 只提建议, 不动安全参数)
    fails = [k for k in ("loop", "l2", "l3", "l4", "record", "map", "no_robot_cmd")
             if not (c.get(k) or {}).get("ok")]
    c["summary"] = {"ok": not fails, "fails": fails, "t": round(time.time(), 3),
                    "t_str": time.strftime("%Y-%m-%d %H:%M:%S")}
    adv = []
    if "l3" in fails and cyc.get("uph"):
        adv.append("节拍 %.1fUPH <%.0f ⇒ 跨件 travel 上限需 ≥%.0fmm/s 或缩短换位距离"
                   % (float(cyc["uph"]), UPH_MIN,
                      (14.9 / max(0.1, (float(acc or 0) - (167.702 - 8.271)) )) * 1000.0 if acc else 0))
    if "l4" in fails and int(cyc.get("big_jumps") or 0) > 0:
        adv.append("有 %s 处段间大跳未连续化 (最大 %smm) ⇒ 段表缺过渡段"
                   % (cyc.get("big_jumps"), cyc.get("big_jump_max_mm")))
    if not c["record"]["ok"]:
        adv.append("记录器不达标 (帧龄/增长/skew) ⇒ 查 zmax-ts-recorder 与相机")
    if not c["map"]["ok"]:
        adv.append("建图服务不 ready ⇒ 查 zmax-map-intel 与深度源")
    c["advice"] = adv
    return c


def main():
    t_row = 0.0
    last_sig = None
    print("[watch] root=%s period=%.0fs uph_min=%.0f" % (ROOT, PERIOD, UPH_MIN), flush=True)
    while True:
        try:
            c = check()
            os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
            tmp = OUT_JSON + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False)
            os.replace(tmp, OUT_JSON)
            now = time.time()
            if now - t_row >= ROW_EVERY:
                t_row = now
                try:
                    with open(OUT_JSONL, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": round(now, 3), **c}, ensure_ascii=False) + "\n")
                    if os.path.getsize(OUT_JSONL) > 3_000_000:
                        keep = open(OUT_JSONL, encoding="utf-8").read().splitlines()[-2000:]
                        with open(OUT_JSONL, "w", encoding="utf-8") as f:
                            f.write("\n".join(keep) + "\n")
                except Exception:                              # noqa: BLE001
                    pass
            sig = (tuple(c["summary"]["fails"]), tuple(c.get("advice") or []))
            if sig != last_sig:
                last_sig = sig
                try:
                    with open(ALERT, "a", encoding="utf-8") as f:
                        f.write("%s %s %s\n" % (c["summary"]["t_str"],
                                                "OK" if c["summary"]["ok"] else "FAIL",
                                                " | ".join(c.get("advice") or []) or "-"))
                except Exception:                              # noqa: BLE001
                    pass
                print("[watch] %s fails=%s" % (c["summary"]["t_str"], c["summary"]["fails"]), flush=True)
        except Exception as e:                                 # noqa: BLE001
            print("[watch] 异常 %s: %s" % (type(e).__name__, e), flush=True)
        time.sleep(PERIOD)


if __name__ == "__main__":
    main()
