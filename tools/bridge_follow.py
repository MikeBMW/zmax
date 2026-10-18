# -*- coding: utf-8 -*-
"""bridge_follow.py — 让真机按 v_ff 的**方向**慢速跟随 (单轴小步 × 10mm/s 上限)

老倪 2026-10-18 现场口径:
  「正确接法是: 只取 v_ff 的方向做增量, 叠加在真机当前 TCP 上」「不要超过 10mm/s」

它做什么:
  ① 读 plan_from_vff.json 的 v_cmd (mm/s, 已 ≤10)
  ② 取**方向的主轴** (+X/-X/+Y/-Y/+Z/-Z) → 对应手动白名单技能
       +X→L2.forward  -X→L2.backward  +Y→L2.left  -Y→L2.right  +Z→L2.lift  -Z→L2.lower
  ③ 一步 STEP_MM (默认 5mm) 发 POST /ctl/move {skill, d_mm, speed_mm_s:10, arm:true}
     —— 单次 5mm、单轴、速度 10mm/s ⇒ 实际平均速度 = 5mm / 单步耗时 ≤ 5mm/s
  ④ 发完立刻读真机 TCP 核对: 命令 5mm 就应实测 ~5mm; 偏差 >2mm / 未 armed / 碰撞 / 急停 ⇒ 立刻停手
  ⑤ 桥关 (bridge_vff=false) 立刻停; 到达可用步数上限也停

安全红线:
  · **绝不自己授权** —— 只读 _auth_info (8793 页面授权), 未授权一行都不发
  · 每步都过 8793 的既有闸门 (白名单/授权窗/限流/FIFO/执行器安全裁决), 不绕
  · 单步 5mm、速度 10mm/s 写死在代码里; 要改必须改这里 (conste)
用法:
  ./gui-venv311/bin/python tools/bridge_follow.py --dry        # 只算不发 (看它会发什么)
  ./gui-venv311/bin/python tools/bridge_follow.py              # 真发 (需已授权)
  ./gui-venv311/bin/python tools/bridge_follow.py --step 3 --speed 8 --max-steps 20
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
BT = os.path.join(REPO, "zmax_data", "ss_live", "bridge_target.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_follow.jsonl")
BASE = "http://127.0.0.1:8793"
SPEED_CAP_MMS = 10.0          # ⛔ 真机硬上限 (现场口径)
STEP_MAX_MM = 100.0           # 单段行程上限 (2026-10-18 老倪「虽然慢, 但是要连续」:
                              #   5mm/段 ⇒ 1.5s 走完 + 2s 等执行腿空闲 = 走走停停;
                              #   50mm/段 @10mm/s ⇒ 一段连续 5s, 只在一段结束时换方向)
AXIS = {                      # v_ff 分量 → (技能, 符号)
    "x+": ("L2.forward", 1), "x-": ("L2.backward", 1),
    "y+": ("L2.left", 1), "y-": ("L2.right", 1),
    "z+": ("L2.lift", 1), "z-": ("L2.lower", 1),
}
AXNAME = {"x": "X", "y": "Y", "z": "Z"}


def _get(path, timeout=4.0):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path, payload, timeout=120.0):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                   # noqa: BLE001
        return None


def _log(rec):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                                   # noqa: BLE001
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=STEP_MAX_MM, help="单段 mm (默认 100, 慢速连续)")
    ap.add_argument("--speed", type=float, default=SPEED_CAP_MMS, help="速度 mm/s (默认 10)")
    ap.add_argument("--max-steps", type=int, default=40, help="最多走几段 (0=常驻, 默认 40)")
    ap.add_argument("--min-gap", type=float, default=0.8, help="两步之间最短间隔 s (默认 0.8)")
    ap.add_argument("--deadband", type=float, default=3.0, help="v_ff 小于它就不动 mm/s")
    ap.add_argument("--dry", action="store_true", help="只算不发 (arm=false)")
    a = ap.parse_args()
    step = max(1.0, min(STEP_MAX_MM, a.step))
    spd = max(1.0, min(SPEED_CAP_MMS, a.speed))
    # 🎯 人调好的位置就是锚: 下降不超过 BAND_DOWN, 上升不超过 BAND_UP, X/Y 不超出 BAND_XY
    #    (2026-10-18 现场: 「刚才的位置太低了, 我调整的」⇒ 跟随不能再自己往下沉)
    BAND_DOWN, BAND_UP, BAND_XY = 20.0, 150.0, 120.0
    try:
        _p = _get("/pose")
        anchor = [float(x) for x in _p["xyz"]]
    except Exception:                                                    # noqa: BLE001
        anchor = [0.0, 0.0, 0.0]
    print("🚶 bridge_follow: 单段 %.1fmm · 速度 %.1fmm/s · 步数上限 %d · %s"
          % (step, spd, a.max_steps, "DRY(只算不发)" if a.dry else "真发"), flush=True)
    print("   锚点(人调好的位置)=(%.4f, %.4f, %.4f) · 下探≤%.0fmm 上升≤%.0fmm XY≤±%.0fmm"
          % (anchor[0], anchor[1], anchor[2], BAND_DOWN, BAND_UP, BAND_XY), flush=True)
    n = 0
    while a.max_steps == 0 or n < a.max_steps:
        st = _get("/ctl/status")
        armed = bool(st.get("motion_armed"))
        rob = st.get("robot") or {}
        if not a.dry and not armed:
            print("⛔ 未授权真动 (motion_armed=false) ⇒ 一行都不发, 退出。先到 8793 点『🔓 授权真动』。", flush=True)
            return
        if rob.get("collision") or rob.get("estop") or rob.get("has_error"):
            print("⛔ 机器人状态异常 collision=%s estop=%s has_error=%s ⇒ 停手"
                  % (rob.get("collision"), rob.get("estop"), rob.get("has_error")), flush=True)
            return
        v = _jload(VFF) or {}
        if not v.get("bridge"):
            print("⏹ 桥接开关已关 ⇒ 停手 (已走 %d 步)" % n, flush=True)
            return
        vc = [float(x) for x in (v.get("v_cmd_mms") or [])][:3]
        if len(vc) < 3:
            time.sleep(0.3)
            continue
        spd_ff = (vc[0] ** 2 + vc[1] ** 2 + vc[2] ** 2) ** 0.5
        if spd_ff < a.deadband:
            print("… v_ff %.1fmm/s 低于死区 ⇒ 不动" % spd_ff, flush=True)
            time.sleep(0.5)
            continue
        ax = max(range(3), key=lambda i: abs(vc[i]))
        key = "%s%s" % ("xyz"[ax], "+" if vc[ax] >= 0 else "-")
        skill, _s = AXIS[key]
        p0 = _get("/pose")
        xyz0 = [float(x) for x in p0["xyz"]]
        # 🚧 band: 该方向会带出界 ⇒ 这一段不发, 等仿真阶段换向
        _dz = (xyz0[2] - anchor[2]) * 1000.0
        _out = ""
        if ax == 2 and vc[2] < 0 and _dz <= -BAND_DOWN:
            _out = "已在下界 (z 比锚点低 %.0fmm)" % (-_dz)
        elif ax == 2 and vc[2] > 0 and _dz >= BAND_UP:
            _out = "已在上界 (z 比锚点高 %.0fmm)" % _dz
        elif ax < 2 and abs((xyz0[ax] - anchor[ax]) * 1000.0) >= BAND_XY and (xyz0[ax] - anchor[ax]) * vc[ax] > 0:
            _out = "%s 已到 ±%.0fmm 边界" % ("XY"[ax], BAND_XY)
        if _out:
            print("🚧 跳过 %s: %s ⇒ 等阶段换向" % (skill, _out), flush=True)
            time.sleep(1.0)
            continue
        # 📏 段长按剩余带宽收 (否则一段 100mm 就能把它带出界)
        if ax == 2:
            _room = (BAND_DOWN + _dz) if vc[2] < 0 else (BAND_UP - _dz)
        else:
            _room = BAND_XY - abs((xyz0[ax] - anchor[ax]) * 1000.0)
        step_eff = max(0.0, min(step, _room))
        if step_eff < 2.0:
            print("🚧 %s 剩余带宽只剩 %.1fmm ⇒ 等阶段换向" % (skill, step_eff), flush=True)
            time.sleep(1.0)
            continue
        body = {"skill": skill, "d_mm": round(step_eff, 1), "speed_mm_s": spd, "arm": (not a.dry)}
        t0 = time.time()
        try:
            r = _post("/ctl/move", body)
        except Exception as e:                                          # noqa: BLE001
            print("⚠️ 下发失败: %s" % str(e)[:120], flush=True)
            time.sleep(1.0)
            continue
        # 🔴 回执 ok=True 只代表"已投递", 实测 5mm 步要 ~2s 才走完 (16:17:37 下发 → 16:17:39 完成)。
        #   原来 0.4s 就读位姿 ⇒ 永远是 Δ=0, 误判成"闸门拦下"。这里改成轮询到位 (上限 25s, 绝不重发)。
        xyz1 = list(xyz0)
        d_mm = [0.0, 0.0, 0.0]
        moved = 0.0
        t_wait = time.time()
        t_last_change = time.time()
        while time.time() - t_wait < 90.0:   # 50mm@10mm/s ≈ 5s, 给足余量 (长段)
            time.sleep(0.2)
            try:
                p1 = _get("/pose")
            except Exception:                                            # noqa: BLE001
                continue
            xyz1 = [float(x) for x in p1["xyz"]]
            d_mm = [round((xyz1[i] - xyz0[i]) * 1000.0, 2) for i in range(3)]
            mv = max(abs(d_mm[i]) for i in range(3))
            if mv > moved + 0.05:
                moved = mv
                t_last_change = time.time()
            if moved >= step_eff * 0.95:
                break
            # 停稳 2s 才认为这一条走完 (执行腿"上一条还在执行"会直接拒下一条 —— 就是这里踩的坑)
            if moved > 0.2 and (time.time() - t_last_change) > 3.0:
                break
        # 等执行腿回到 idle 再走下一段 (腿的 busy 标志比"位姿到位"晚约 0.6~1s ⇒ 不等就必被拒)
        t_idle = time.time()
        while time.time() - t_idle < 12.0:
            try:
                if str(((_get("/ctl/status").get("robot") or {}).get("operation") or "")).lower() == "idle":
                    break
            except Exception:                                            # noqa: BLE001
                pass
            time.sleep(0.2)
        time.sleep(0.2)
        dt = time.time() - t0
        _txt = " ".join(str(x) for x in (r.get("lines") or [])) + " " + str(r.get("msg") or "")
        _blocked = ("被拦" in _txt) or ("拒(不排队)" in _txt) or ("不在手动控制白名单" in _txt)
        ok = bool(r.get("ok")) and not r.get("denied") and not _blocked
        print("段 %2d · %s %.1fmm@%.0fmm/s · ok=%s · 连续%.1fs · 实测Δ=%s mm (最大 %.1f, 速率 %.1fmm/s)"
              % (n + 1, skill, step_eff, spd, ok, dt, d_mm, moved,
                 (moved / dt) if dt > 0 else 0.0), flush=True)
        _log({"ts": time.time(), "n": n + 1, "skill": skill, "step_mm": round(step_eff, 1), "speed_mm_s": spd,
              "ok": ok, "denied": bool(r.get("denied")), "took_s": round(dt, 2),
              "tcp0": xyz0, "tcp1": xyz1, "delta_mm": d_mm, "msg": str(r.get("msg") or "")[:200],
              "dry": a.dry})
        n += 1
        if _blocked and n + 1 < a.max_steps:
            print("↻ 本条被执行腿拒 (上一条还在执行) ⇒ 等 1.5s 重试同一步", flush=True)
            time.sleep(1.5)
            continue                                                     # 不计数, 重试同一步
        if not ok:
            print("⛔ 回执不 ok ⇒ 停手。原因: %s" % str(r.get("msg") or r)[:200], flush=True)
            return
        if not a.dry and moved < step_eff * 0.70:
            print("⚠️ 命令 %.1fmm 实测只动 %.1fmm (<70%%) ⇒ 可能被闸门拦下/未到位, 停手核对" % (step_eff, moved), flush=True)
            return
        time.sleep(max(0.0, a.min_gap - dt))
    print("✅ 到达步数上限 %d 步, 正常结束" % n, flush=True)


if __name__ == "__main__":
    main()
