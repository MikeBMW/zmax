# -*- coding: utf-8 -*-
"""bridge_stage_move.py — 仿真每个动作 → 真机一次**三轴合成**的小动作 (含平移)

老倪 2026-10-18:
  「都放行, 按照你的建议来」
  「刚才我没有看到平移的动作, 而仿真有, 为什么?」
  —— 原因: 上一版只取 u_ff 的**主轴**, 用单轴技能 (forward/backward/left/right/lift/lower),
     横向分量 (比如 接近 [110,37,-60] 里的 Y=37) 被整块丢掉, 所以只有升降、没有平移。

这一版:
  · 直接给 SDK 腿下 **move-rel dx,dy,dz** (base 系直线, 姿态不变) ⇒ 速度矢量与仿真同向同比例, 平移是真的
  · 方向 = 阶段切换后 150ms 内 u_ff 的均值 (不是看瞬时值 ⇒ 不再错拍)
  · 幅度 = --step (默认 15mm) 沿方向矢量分配, 各轴独立
  · 硬包络 = anchor ± --band (默认 25mm), 写进 guard_box 交给腿的**实时扫掠闸门**:
    每 0.15s 比真值, 出界立刻 stop() —— 小幅度跟随也不会走远
  · 授权: 每步复查 8793 的 motion_armed, 未授权一行不发

用法:
  ./gui-venv311/bin/python tools/bridge_stage_move.py --step 15 --speed 100 --band 25
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
RES = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "agent_result.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_stage_move.jsonl")
BASE = "http://127.0.0.1:8793"


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return {}


def _get(p, timeout=4.0):
    with urllib.request.urlopen(BASE + p, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fifo(req):
    fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    os.close(fd)


def _stage():
    return str(_j(TR).get("阶段") or "")


def _uff():
    v = _j(VFF)
    u = [float(x) for x in (v.get("u_ff_mms") or [])][:3]
    return u if len(u) == 3 else [0.0, 0.0, 0.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=15.0, help="每个动作位移 mm (默认 15)")
    ap.add_argument("--speed", type=float, default=100.0, help="速度 mm/s (默认 100)")
    ap.add_argument("--band", type=float, default=40.0, help="锚点周围硬包络 ±mm (默认 40)")
    ap.add_argument("--settle", type=float, default=0.15, help="阶段切换后采样窗口 s")
    ap.add_argument("--max-actions", type=int, default=40)
    a = ap.parse_args()

    st = _get("/ctl/status")
    if not st.get("motion_armed"):
        print("⛔ 未授权真动 ⇒ 一行都不发。", flush=True)
        return 2
    p0 = _get("/pose")
    anchor = [float(x) for x in p0["xyz"]]
    gbox = {ax: [anchor[i] - a.band / 1000.0, anchor[i] + a.band / 1000.0] for i, ax in enumerate("xyz")}
    print("🎬 三轴小动作: 每动作 %.0fmm@%.0fmm/s · 包络 ±%.0fmm · 锚点 (%.4f, %.4f, %.4f)"
          % (a.step, a.speed, a.band, *anchor), flush=True)

    last = _stage()
    n = 0
    while n < a.max_actions:
        time.sleep(0.05)
        s = _stage()
        if not s or s == last:
            continue
        last = s
        # 在该阶段的窗口内取 u_ff 均值 (避免读到下一阶段的瞬时值)
        t_end = time.time() + a.settle
        vs = []
        while time.time() < t_end:
            vs.append(_uff())
            time.sleep(0.02)
        m = [sum(v[i] for v in vs) / max(1, len(vs)) for i in range(3)]
        mag = sum(x * x for x in m) ** 0.5
        if mag < 2.0:
            print("… 阶段 %-6s 速度太小 (%.1fmm/s) ⇒ 不动" % (s, mag), flush=True)
            continue
        u = [x / mag for x in m]
        cur = [float(x) for x in _get("/pose")["xyz"]]
        d = [u[i] * a.step for i in range(3)]
        # 包络收口: 会让某轴出界的部分等比缩掉
        scale = 1.0
        for i in range(3):
            room = a.band - abs((cur[i] - anchor[i]) * 1000.0)
            if abs(d[i]) > 1e-6 and (cur[i] - anchor[i]) * d[i] > 0:
                scale = min(scale, max(0.0, room / abs(d[i])))
        d = [x * scale for x in d]
        if max(abs(x) for x in d) < 2.0:
            print("🚧 阶段 %-6s 已到包络边界 (离锚 %.1fmm) ⇒ 跳过"
                  % (s, max(abs((cur[i] - anchor[i]) * 1000.0) for i in range(3))), flush=True)
            continue
        # 🔄 回中: 累计偏移超过包络 60% 就先往回走一半, 否则动作会一路撞到扫掠闸
        #    (2026-10-18 实测: 转移 -13.9mm + 转移·接触 -11.9mm = -25.8mm, 正好撞 ±25 边界被急停)
        off = [(cur[i] - anchor[i]) * 1000.0 for i in range(3)]
        if max(abs(x) for x in off) > a.band * 0.6:
            back = [-x * 0.6 for x in off]
            print("🔄 回中: 当前离锚 %s mm ⇒ 先往回走 %s mm"
                  % ([round(x, 1) for x in off], [round(x, 1) for x in back]), flush=True)
            rid0 = "rc_%d_%d" % (int(time.time()), n)
            try:
                _fifo({"id": rid0, "cmd": "move-rel", "tag": "bridge",
                       "dx": round(back[0], 2), "dy": round(back[1], 2), "dz": round(back[2], 2),
                       "speed": min(100.0, a.speed), "cap_mm": 30.0, "guard_box": gbox})
            except OSError as e:
                print("⚠️ 回中下发失败: %s" % e, flush=True)
            t_rc = time.time()
            while time.time() - t_rc < 20:
                time.sleep(0.15)
                if str(_j(RES).get("id")) == rid0:
                    break
            cur = [float(x) for x in _get("/pose")["xyz"]]
            d = [u[i] * a.step for i in range(3)]      # 回中后按原方向重算余量
        st = _get("/ctl/status")
        if not st.get("motion_armed"):
            print("🔒 授权已撤 ⇒ 停", flush=True)
            return 0
        rid = "stg_%d_%d" % (int(time.time()), n)
        req = {"id": rid, "cmd": "move-rel", "tag": "bridge",
               "dx": round(d[0], 2), "dy": round(d[1], 2), "dz": round(d[2], 2),
               "speed": min(100.0, a.speed), "cap_mm": 30.0, "guard_box": gbox}
        t0 = time.time()
        try:
            _fifo(req)
        except OSError as e:
            print("⚠️ FIFO 失败: %s" % e, flush=True)
            continue
        res = {}
        t_w = time.time()
        while time.time() - t_w < 25:
            time.sleep(0.15)
            r = _j(RES)
            if str(r.get("id")) == rid:
                res = r
                break
        out = res.get("out") or {}
        delta = out.get("delta_mm") or {}
        dm = [abs(float(delta.get(k) or 0.0)) for k in "xyz"] if delta else []
        dt = round(time.time() - t0, 2)
        n += 1
        print("动作 %2d · %-8s 方向(%+.2f,%+.2f,%+.2f) → 命令(%+.1f,%+.1f,%+.1f)mm@%.0f · %.2fs · %s · 实测Δ=%s"
              % (n, s, u[0], u[1], u[2], d[0], d[1], d[2], a.speed, dt,
                 (res.get("verdict") or "?")[:26],
                 [round(x, 1) for x in dm] if dm else "?"), flush=True)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "stage": s, "u": u, "cmd_mm": d,
                                    "verdict": res.get("verdict"), "delta_mm": dm,
                                    "took_s": dt, "speed_mm_s": a.speed},
                                   ensure_ascii=False) + "\n")
        except Exception:                                                # noqa: BLE001
            pass
        if res.get("rc") not in (0, None):
            print("⛔ 执行失败 ⇒ 停手: %s" % (res.get("verdict") or "")[:120], flush=True)
            return 3
    print("✅ 完成 %d 个动作" % n, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
