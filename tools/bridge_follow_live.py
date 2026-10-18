# -*- coding: utf-8 -*-
"""bridge_follow_live.py — 真机「小幅度 · 跟仿真同节奏」跟随 v_ff

老倪 2026-10-18 现场 (逐条):
  「正确接法是: 只取 v_ff 的方向做增量, 叠加在真机当前 TCP 上」
  「虽然慢, 但是要连续啊」「不要走那么远, 先短距离, 平顺的移动」
  「移动的距离可以小, 但是频率要跟仿真一样」「你的频率太慢了, 都是局域网, 为什么这么慢? 跟上节奏啊」

机制:
  · 幅度: 目标 = 锚点 + (仿真位置 − 仿真起点) × k, k 自适应使最大幅度 = --band (默认 15mm)
  · 速度: 取**仿真当期速度** |u_ff|, 上限 --max-speed (默认 60mm/s)
    慢的根源是速度被压到 10mm/s: 仿真一个动作走 30~80mm, 真机只走 15mm, 若还按 10mm/s
    就要 1.5s 才走完 ⇒ 永远滞后。幅度小 + 速度跟仿真 ⇒ 每个动作 0.2~0.5s 同起同落。
  · 下发: SDK 腿里 moveAppend 流式追加 (每 50ms 一点), 中间不停
  · 安全: 授权撤/桥接关/方向流>1.5s旧/报警/急停/碰撞 ⇒ 立刻 stop(); 幅度硬卡 band

用法:
  ./gui-venv311/bin/python tools/bridge_follow_live.py --band 15 --max-speed 60
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
DIRF = os.path.join(REPO, "zmax_data", "rokae_sdk", "follow", "dir.json")
STF = os.path.join(REPO, "zmax_data", "rokae_sdk", "follow", "status.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_follow_live.jsonl")
BASE = "http://127.0.0.1:8793"
STOP = {"flag": False}


def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                     # noqa: BLE001
        return None


def _fifo(req):
    try:
        fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        os.close(fd)
        return True
    except OSError as e:
        print("⚠️ FIFO 写入失败: %s" % e, flush=True)
        return False


def _armed():
    try:
        with urllib.request.urlopen(BASE + "/ctl/status", timeout=3) as r:
            d = json.loads(r.read().decode("utf-8"))
        return bool(d.get("motion_armed"))
    except Exception:                                                     # noqa: BLE001
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", type=float, default=15.0, help="最大幅度 mm (默认 15)")
    ap.add_argument("--max-speed", type=float, default=60.0, help="速度上限 mm/s (默认 60)")
    ap.add_argument("--hz", type=float, default=20.0, help="目标流频率 Hz")
    ap.add_argument("--max-s", type=float, default=900.0, help="最长运行秒数")
    a = ap.parse_args()
    band = max(3.0, min(40.0, a.band))
    maxv = max(5.0, min(80.0, a.max_speed))

    if not _armed():
        print("⛔ 未授权真动 ⇒ 一行都不发。先到 8793 页面点『🔓 授权真动』(二次确认)。", flush=True)
        return 2
    os.makedirs(os.path.dirname(DIRF), exist_ok=True)
    if not _fifo({"cmd": "follow", "on": True, "speed": maxv, "band_mm": band,
                  "step_mm": max(1.0, maxv / 20.0), "zone_mm": 5.0}):
        return 3
    print("🌊 跟随: 幅度 ≤%.0fmm · 速度 ≤%.0fmm/s · 节奏=仿真 (k 自适应)" % (band, maxv), flush=True)

    def _sig(_s, _f):
        STOP["flag"] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    t0 = time.time()
    t_st = 0.0
    t_armed = time.time()
    armed = True
    rmax = 0.0
    try:
        while not STOP["flag"] and (time.time() - t0) < a.max_s:
            v = _jload(VFF) or {}
            on = bool(v.get("bridge"))
            if time.time() - t_armed > 1.0:
                armed = _armed()
                t_armed = time.time()
            pos = v.get("tcp_pose") or {}
            anc = v.get("anchor_xyz") or [0.0, 0.0, 0.0]
            rel = [0.0, 0.0, 0.0]
            if all(k in pos for k in ("x", "y", "z")):
                rel = [(float(pos[k]) - float(anc[i])) * 1000.0 for i, k in enumerate("xyz")]
            rmax = max(rmax, max(abs(x) for x in rel))
            k = min(1.0, band / max(20.0, rmax))
            tgt = [max(-band, min(band, k * x)) for x in rel]
            uff = [float(x) for x in (v.get("u_ff_mms") or [])][:3]
            simv = (sum(x * x for x in uff) ** 0.5) if len(uff) == 3 else 0.0
            spd = max(3.0, min(maxv, simv if simv > 1.0 else 3.0))
            payload = {"ts": time.time(), "on": on, "armed": armed, "target_mm": tgt,
                       "band_mm": band, "speed_mm_s": spd}
            try:
                with open(DIRF + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(DIRF + ".tmp", DIRF)
            except Exception:                                          # noqa: BLE001
                pass
            if not armed:
                print("🔒 授权已撤 ⇒ 停", flush=True)
                break
            if not on:
                print("⏹ 桥接开关已关 ⇒ 停", flush=True)
                break
            if time.time() - t_st >= 1.0:
                t_st = time.time()
                s = _jload(STF) or {}
                print("…. 仿真位移 %s mm (半径 %.0f) k=%.2f ⇒ 目标 %s mm · 速度 %.0fmm/s · "
                      "追加 %s 点 · 离锚 %.1fmm · %s"
                      % ([round(x, 1) for x in rel], rmax, k, [round(x, 1) for x in tgt], spd,
                         s.get("n") or 0, s.get("travel_mm") or 0.0, (s.get("why") or "-")[:30]),
                      flush=True)
                try:
                    with open(LOG, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": time.time(), "rel": rel, "k": k, "tgt": tgt,
                                            "spd": spd, "status": s}, ensure_ascii=False) + "\n")
                except Exception:                                       # noqa: BLE001
                    pass
            time.sleep(max(0.01, 1.0 / a.hz))
    finally:
        _fifo({"cmd": "follow", "on": False})
        time.sleep(0.6)
        s = _jload(STF) or {}
        print("🛑 已停: 追加 %s 点 · 离锚 %smm · 原因: %s"
              % (s.get("n") or 0, s.get("travel_mm"), (s.get("why") or "-")[:50]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
