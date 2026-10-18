# -*- coding: utf-8 -*-
"""bridge_episode_path.py — 一整轮仿真轨迹 → **一条**多点路径, 保证平顺

老倪 2026-10-18: 「你得保证平顺啊」

为什么这样才平顺 (已实测):
  · 一条 move-rel = 一段直线, 走完就停 ⇒ 走一段停一段 (一顿一顿)
  · 一次性 append 多点 + **一次** moveStart ⇒ 控制器一口气走完整条 (实测 10 点 50mm/2.8s, 残差 0.0mm)
  · 所以要平顺, 就必须"整轮排完再 moveStart": 一轮仿真轨迹 = 一条路径, 中途不停

做法:
  ① 先录一轮: 20Hz 采仿真真值 + 阶段, 从某阶段回到起始阶段 = 一轮结束 ⇒ 得到轨迹模板
  ② 之后每轮开始, 把模板按 scale 缩放、重采样成 --npts 个点, 一次下发;
     速度 = 路径长 / 本轮时长 ⇒ 和仿真同起同落, 中途不停
  ③ 包络 anchor ± --band 交给腿的实时扫掠闸; 授权每拍复查; 桥接开关=总闸

用法:
  ./gui-venv311/bin/python tools/bridge_episode_path.py --scale 1.0 --npts 80 --band 250
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
TR = os.path.join(REPO, "zmax_data", "ss_live", "trace_live.json")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
TPL = os.path.join(REPO, "zmax_data", "ss_live", "episode_template.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_episode_path.jsonl")
PIDF = os.path.join(REPO, "zmax_data", "ss_live", "bridge_episode.pid")
BASE = "http://127.0.0.1:8793"
START_STAGE = "接近"      # 插拔场景的起始阶段; 摆盘用 frame 回绕判定 (摆盘无"接近")


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                     # noqa: BLE001
        return {}


def _get(p, timeout=3.0):
    with urllib.request.urlopen(BASE + p, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fifo(req):
    fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    os.close(fd)


def _truth():
    t = _j(VFF).get("truth_xyz")
    if isinstance(t, (list, tuple)) and len(t) >= 3:
        return [float(x) * 1000.0 for x in t]
    return None


def _resample(path, n):
    """把折线等弧长重采样成 n 个点 (含首尾), 返回相邻增量列表"""
    if len(path) < 2:
        return []
    segs = [((path[i + 1][0] - path[i][0]) ** 2 + (path[i + 1][1] - path[i][1]) ** 2
             + (path[i + 1][2] - path[i][2]) ** 2) ** 0.5 for i in range(len(path) - 1)]
    total = sum(segs)
    if total <= 0:
        return []
    out, acc, j = [], 0.0, 0
    prev = list(path[0])
    for k in range(1, n + 1):
        want = total * k / n
        while j < len(segs) and acc + segs[j] < want:
            acc += segs[j]
            j += 1
        if j >= len(segs):
            nxt = list(path[-1])
        else:
            r = (want - acc) / segs[j] if segs[j] > 0 else 0.0
            nxt = [path[j][i] + (path[j + 1][i] - path[j][i]) * r for i in range(3)]
        out.append([nxt[i] - prev[i] for i in range(3)])
        prev = nxt
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="轨迹缩放 (默认 1.0)")
    ap.add_argument("--npts", type=int, default=80, help="路径点数 (默认 80, 越多越圆滑)")
    ap.add_argument("--band", type=float, default=250.0, help="包络 ±mm")
    ap.add_argument("--dur-scale", type=float, default=1.0, help="时长压缩系数 (1=与仿真同节奏, 0.5=快一倍)")
    ap.add_argument("--max-path", type=float, default=40.0, help="整轮总行程硬上限 mm (默认 40, 老倪: 不要走太远)")
    ap.add_argument("--max-episodes", type=int, default=0, help="0=常驻")
    a = ap.parse_args()

    if not _get("/ctl/status").get("motion_armed"):
        print("⛔ 未授权真动 ⇒ 一行都不发。", flush=True)
        return 2
    anchor = [float(x) for x in _get("/pose")["xyz"]]
    gbox = {ax: [anchor[i] - a.band / 1000.0, anchor[i] + a.band / 1000.0] for i, ax in enumerate("xyz")}
    try:
        with open(PIDF, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:                                                     # noqa: BLE001
        pass
    print("🎞 整轮一条路径: scale=%.2f npts=%d 包络±%.0fmm 锚点(%.4f,%.4f,%.4f)"
          % (a.scale, a.npts, a.band, *anchor), flush=True)
    print("   第 1 轮先录轨迹 (臂不动), 录完自动开始回放", flush=True)

    buf, t_start, last_stage, ep, last_frame = [], None, "", 0, 0
    next_replay = 0.0
    tpl = _j(TPL).get("path") if _j(TPL).get("path") else None
    if tpl:
        print("   已有轨迹模板 %d 点, 直接回放" % len(tpl), flush=True)
    while a.max_episodes == 0 or ep < a.max_episodes:
        time.sleep(0.05)
        if not _j(VFF).get("bridge"):
            print("⏹ 桥接开关已关 ⇒ 停", flush=True)
            break
        v = _j(VFF)
        s = str(_j(TR).get("阶段") or "")
        fr = int(v.get("frame") or 0)
        t = _truth()
        if not s or t is None:
            continue
        # 一轮的边界 = frame 回绕 (摆盘场景阶段表里没有"接近": 下降→抓取→抬起→转移→放下)
        wrap = (fr < last_frame) if last_frame else False
        last_frame = fr
        # 小幅度循环: 不等 frame 回绕, 走完就接着下一轮 (幅度 40mm, 时间 ~8s)
        if tpl and len(tpl) > 2 and time.time() >= next_replay:
            _dur = float(_j(TPL).get("dur_s") or 10.0)
            _dur_eff = max(1.0, _dur * a.dur_scale)
            segs = _resample([[x * a.scale for x in q] for q in tpl], a.npts)
            total = sum((sum(x * x for x in q) ** 0.5) for q in segs)
            if total > a.max_path and total > 0:
                _k = a.max_path / total
                segs = [[x * _k for x in q] for q in segs]
                total = a.max_path
            if segs and total >= 3.0 and _get("/ctl/status").get("motion_armed"):
                spd = max(2.0, min(200.0, total / _dur_eff))
                _fifo({"id": "rst_%d" % int(time.time() * 1000), "cmd": "reset"})
                time.sleep(0.2)
                _fifo({"id": "ep_%d" % int(time.time() * 1000), "cmd": "path",
                       "points": [[round(x, 3) for x in q] for q in segs],
                       "speed": round(spd, 1), "zone": 10, "guard_box": gbox})
                ep += 1
                print("🎞 第 %d 轮: %d 点 · 路径 %.0fmm · %.1fs · 速度 %.1fmm/s"
                      % (ep, len(segs), total, _dur_eff, spd), flush=True)
                next_replay = time.time() + _dur_eff + 0.3
        if wrap:
            if len(buf) > 20:
                rel = [[p[i] - buf[0][i] for i in range(3)] for p in buf]
                dur = max(0.5, time.time() - (t_start or time.time()))
                try:
                    with open(TPL, "w", encoding="utf-8") as f:
                        json.dump({"path": rel, "dur_s": round(dur, 2),
                                   "stamp": time.strftime("%F %T")}, f, ensure_ascii=False)
                    print("   ✅ 录完一轮: %d 点 · %.1fs" % (len(rel), dur), flush=True)
                except Exception:                                         # noqa: BLE001
                    pass
                tpl = rel
            buf, t_start = [], time.time()
            # 回放上一轮模板 (同一场景循环 ⇒ 这一轮形状基本一致)
            if tpl and len(tpl) > 2:
                _dur = float(_j(TPL).get("dur_s") or 10.0)
                segs = _resample([[x * a.scale for x in q] for q in tpl], a.npts)
                total = sum((sum(x * x for x in q) ** 0.5) for q in segs)
                if total > a.max_path and total > 0:           # 总行程硬上限: 超了等比缩
                    _k = a.max_path / total
                    segs = [[x * _k for x in q] for q in segs]
                    total = a.max_path
                if segs and total >= 3.0 and _get("/ctl/status").get("motion_armed"):
                    _dur_eff = max(1.0, _dur * a.dur_scale)
                    spd = max(2.0, min(200.0, total / _dur_eff))
                    # 🧹 清掉可能残留的旧队列 (上一轮/上一个进程排的命令), 否则新旧叠着走会很远
                    _fifo({"id": "rst_%d" % int(time.time() * 1000), "cmd": "reset"})
                    time.sleep(0.3)
                    _fifo({"id": "ep_%d" % int(time.time() * 1000), "cmd": "path",
                           "points": [[round(x, 3) for x in q] for q in segs],
                           "speed": round(spd, 1), "zone": 10, "guard_box": gbox})
                    ep += 1
                    print("🎞 第 %d 轮回放: %d 点 · 路径 %.0fmm · %.1fs · 速度 %.0fmm/s"
                          % (ep, len(segs), total, _dur_eff, spd), flush=True)
                    # ⏳ 等这一整轮走完再发下一轮 (否则两轮 1002mm 叠着排队, 会跑很远)
                    _t_wait = time.time()
                    _last = None
                    while time.time() - _t_wait < _dur_eff * 1.5:
                        time.sleep(0.2)
                        try:
                            _p = [float(x) for x in _get("/pose")["xyz"]]
                        except Exception:                                  # noqa: BLE001
                            continue
                        if _last is not None and max(abs(_p[i] - _last[i]) for i in range(3)) < 5e-5:
                            break
                        _last = _p
            continue
        # —— 录制 ——
        if s == START_STAGE and last_stage and last_stage != START_STAGE:
            if len(buf) > 20:
                rel = [[p[i] - buf[0][i] for i in range(3)] for p in buf]
                dur = float(time.time() - (t_start or time.time()))
                try:
                    with open(TPL, "w", encoding="utf-8") as f:
                        json.dump({"path": rel, "dur_s": round(dur, 2),
                                   "stamp": time.strftime("%F %T")}, f, ensure_ascii=False)
                    print("   ✅ 录完一轮: %d 点 · %.1fs" % (len(rel), dur), flush=True)
                except Exception:                                         # noqa: BLE001
                    pass
                tpl = rel
            buf, t_start = [], time.time()
        if t_start is None:
            t_start = time.time()
        buf.append(t)
        last_stage = s
        # —— 回放: 每轮起始阶段发一条整轮路径 ——
        if s == START_STAGE and tpl and len(tpl) > 2:
            dur = float(_j(TPL).get("dur_s") or 10.0)
            pts = [[x * a.scale for x in p] for p in tpl]
            segs = _resample(pts, a.npts)
            total = sum((sum(x * x for x in p) ** 0.5) for p in segs)
            if not segs or total < 3.0:
                continue
            spd = max(5.0, min(200.0, total / max(1.0, dur)))
            if not _get("/ctl/status").get("motion_armed"):
                print("🔒 授权已撤 ⇒ 停", flush=True)
                break
            _fifo({"id": "ep_%d" % int(time.time() * 1000), "cmd": "path",
                   "points": [[round(x, 3) for x in p] for p in segs],
                   "speed": round(spd, 1), "zone": 10, "guard_box": gbox})
            ep += 1
            print("🎞 第 %d 轮: %d 点 · 路径 %.0fmm · %.1fs · 速度 %.0fmm/s ⇒ 一条路径走完整轮"
                  % (ep, len(segs), total, dur, spd), flush=True)
            try:
                with open(LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.time(), "ep": ep, "total_mm": round(total, 1),
                                        "dur_s": dur, "speed_mm_s": round(spd, 1)},
                                       ensure_ascii=False) + "\n")
            except Exception:                                             # noqa: BLE001
                pass
            time.sleep(min(3.0, dur * 0.9))          # 让它走完这一段 (期间不再插命令)
    print("✅ 结束 (回放 %d 轮)" % ep, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
