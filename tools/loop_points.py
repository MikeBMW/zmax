#!/usr/bin/env python3
"""loop_points.py — 助手侧「N 点循环移动」: 逐点下发 → 真值到位判据 → 落证据。

与页面按钮**同一条**下发链 (POST 127.0.0.1:8793/ctl/move {skill}), 因此:
  · 授权窗 / 收口 / 包络 / 执行腿 / 安全裁决 一个都不绕;
  · 每跳**之前**重读一次授权+上电 (窗中途到期就当场停, 不发半步);
  · 到位判据 = TCP 真值 < --settle-mm 且连续 --settle-s 秒稳定 (不用超时猜到位);
  · 下发被拒 / 连续 --max-fail 次失败 / 会话目录出现 STOP / 授权失效 ⇒ 立刻停。

产物: <session>/loop_hops.jsonl (每跳一行: 目标/下发回执/到位耗时/实测速率/姿态差)
      ~/zmax/zmax_data/gs_map/loop_status.json (给人看的当前步)

用法:
  python tools/loop_points.py --session ~/zmax/zmax_data/gs_assets/loop_XXXX \
      [--order 1,2,3,4,5,6,7 --pingpong] [--cycles 0=until STOP] [--speed 120] [--capture]
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP_JSON = os.path.join(REPO, "data/skills/l2_atomic/space_points.json")
POSE_JSON = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")
BASE = "http://127.0.0.1:8793"
HOP_LOG = os.path.join(os.path.expanduser("~/zmax/zmax_data/gs_map"), "loop_hops_fallback.jsonl")
STATUS = os.path.expanduser("~/zmax/zmax_data/gs_map/loop_status.json")


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(os.path.join(os.path.dirname(HOP_LOG), "loop.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:                                                      # noqa: BLE001
        pass


def jline(rec):
    try:
        with open(HOP_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                                      # noqa: BLE001
        pass


def api_get(path, timeout=6):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:                                                 # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:110])}


def api_post(path, body, timeout=30):
    try:
        req = urllib.request.Request(BASE + path, method="POST",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:                                                 # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:110])}


def gate():
    """→ (ok, why)。上电 + 授权 缺一不可; 读不到如实当不满足。"""
    s = api_get("/ctl/status")
    if not isinstance(s, dict):
        return False, "读不到 8793 /ctl/status"
    r = s.get("robot") if isinstance(s.get("robot"), dict) else {}
    pw = str(r.get("power") or s.get("power") or "").lower()
    if pw not in ("on", "true", "powerstate.on"):
        return False, "机械臂未上电(power=%s)" % (pw or "?")
    if not s.get("motion_armed"):
        return False, "真动授权不在(motion_armed=false)"
    if r.get("estop") or r.get("collision") or r.get("has_error"):
        return False, "控制器异常(estop=%s collision=%s err=%s)" % (r.get("estop"), r.get("collision"), r.get("has_error"))
    return True, "armed 剩 %.0fs · power=on · %s/%s" % (
        ((s.get("auth") or {}).get("left_s") or 0), r.get("mode"), r.get("operation"))


def pose(max_age=2.0):
    try:
        st = os.stat(POSE_JSON)
        if time.time() - st.st_mtime > max_age:
            return None
        d = json.load(open(POSE_JSON, encoding="utf-8"))
        return d
    except Exception:                                                      # noqa: BLE001
        return None


def dist_mm(p, xyz):
    return math.dist([p.get(k) for k in ("x", "y", "z")], list(xyz)) * 1000.0


def quat_ang_deg(a, b):
    try:
        d = abs(sum(float(x) * float(y) for x, y in zip(a, b)))
        return math.degrees(2.0 * math.acos(min(1.0, d)))
    except Exception:                                                      # noqa: BLE001
        return None


def main():
    global HOP_LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--order", default="", help="逗号分隔的点序号, 默认点位文件里的 spaceN 升序")
    ap.add_argument("--pingpong", action="store_true", help="来回: 1..7 再 7..1 (少一次大跨跳)")
    ap.add_argument("--cycles", type=int, default=0, help="0 = 一直走, 直到会话目录出现 STOP")
    ap.add_argument("--speed", type=float, default=120.0)
    ap.add_argument("--settle-mm", type=float, default=3.0)
    ap.add_argument("--settle-s", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=300.0, help="单跳最长等多久(秒)")
    ap.add_argument("--max-fail", type=int, default=3, help="连续失败几次就停")
    ap.add_argument("--capture", action="store_true", help="同时起 gs_capture 覆盖整段移动")
    ap.add_argument("--dry-run", action="store_true", help="只算不发(看判据/姿态差)")
    args = ap.parse_args()

    sess = os.path.abspath(os.path.expanduser(args.session))
    os.makedirs(sess, exist_ok=True)
    HOP_LOG = os.path.join(sess, "loop_hops.jsonl")
    STOP = os.path.join(sess, "STOP")

    pts = json.load(open(SP_JSON, encoding="utf-8"))["points"]
    if args.order:
        names = ["space%s" % t.strip() for t in args.order.split(",") if t.strip()]
    else:
        names = sorted([k for k in pts if k.startswith("space") and pts[k].get("pos") and pts[k].get("quat")],
                       key=lambda k: int(k.replace("space", "")))
    seq = list(names) + (list(reversed(names)) if args.pingpong else [])
    missing = [n for n in seq if n not in pts or not pts[n].get("pos")]
    if missing:
        log("⛔ 点位缺 pos: %s ⇒ 停" % missing)
        return 2
    log("循环序列: %s%s · 速度 %.0f · 到位 <%.0fmm 稳定 %.1fs · 会话 %s"
        % (" → ".join(seq), " (来回)" if args.pingpong else "", args.speed, args.settle_mm, args.settle_s, sess))
    print("ORDER=" + ",".join(seq), flush=True)

    cap = None
    if args.capture and not args.dry_run:
        cj = os.path.join(sess, "capture.log")
        log("🎥 起采(覆盖整段移动) → %s" % sess)
        cap = subprocess.Popen(["bash", "-lc",
                                "cd %s && %s tools/gs_capture.py --out %s --secs 0 >> %s 2>&1"
                                % (REPO, sys.executable, sess, cj)])
    cyc, i, fails = 0, 0, 0
    try:
        while True:
            if os.path.exists(STOP):
                log("STOP 文件出现 ⇒ 收工")
                break
            if args.cycles and cyc >= args.cycles:
                log("跑满 %d 轮 ⇒ 收工" % cyc)
                break
            tgt_name = seq[i % len(seq)]
            if i % len(seq) == 0:
                cyc += 1
            tgt = pts[tgt_name]["pos"]
            ok, why = gate()
            if not ok:
                log("⛔ 前置不满足: %s ⇒ 停(不发半步)" % why)
                jline({"t": time.strftime("%F %T"), "hop": i, "to": tgt_name, "verdict": "GATE_FAIL", "why": why})
                break
            p0 = pose()
            if p0 is None:
                log("⛔ 位姿真源不新鲜(>2s) ⇒ 停")
                break
            ang = quat_ang_deg([p0.get(k) for k in ("qx", "qy", "qz", "qw")], pts[tgt_name].get("quat") or [0, 0, 0, 0])
            d0 = dist_mm(p0, tgt)
            try:
                json.dump({"running": True, "step": "point", "to": tgt_name,
                           "status_line": "(第%d轮) 去 %s · 当前距 %.0fmm · %s" % (cyc, tgt_name, d0, why),
                           "hop": i, "ts": time.strftime("%F %T")}, open(STATUS, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:                                                  # noqa: BLE001
                pass
            log("→ %s (当前距 %.0fmm · 姿态差 %s°)" % (tgt_name, d0, "?" if ang is None else "%.1f" % ang))
            if args.dry_run:
                i += 1
                time.sleep(0.2)
                continue
            t0 = time.time()
            r = api_post("/ctl/move", {"skill": "L2.goto_" + tgt_name, "arm": 1, "speed": args.speed,
                                       "by": "助手: %d点循环" % len(names)})
            rec = {"t": time.strftime("%F %T"), "hop": i, "cycle": cyc, "to": tgt_name,
                   "d0_mm": round(d0, 1), "quat_delta_deg": None if ang is None else round(ang, 1),
                   "send_ok": bool(r.get("ok")), "send_reply": {k: r.get(k) for k in ("ok", "msg", "err", "verdict", "id") if k in r}}
            if not r.get("ok"):
                fails += 1
                rec["verdict"] = "DISPATCH_REJECTED"
                log("  ⛔ 下发被拒: %s" % str(r.get("msg") or r.get("err") or r)[:160])
                jline(rec)
                if fails >= args.max_fail:
                    log("⛔ 连续 %d 次被拒 ⇒ 停" % fails)
                    break
                i += 1
                time.sleep(1.0)
                continue
            stable, dev = None, None
            while time.time() - t0 < args.timeout:
                if os.path.exists(STOP):
                    break
                p = pose()
                if p is not None:
                    dev = dist_mm(p, tgt)
                    if dev < args.settle_mm:
                        stable = stable or time.time()
                        if time.time() - stable >= args.settle_s:
                            break
                    else:
                        stable = None
                time.sleep(0.2)
            took = time.time() - t0
            p1 = pose()
            arrived = bool(stable is not None and dev is not None and dev < args.settle_mm)
            path_mm = d0
            rec.update({"arrived": arrived, "resid_mm": None if dev is None else round(dev, 1),
                        "took_s": round(took, 1), "speed_mm_s": round(path_mm / took, 2) if took > 0 else None,
                        "quat_now_vs_taught_deg": None if (p1 is None) else round(
                            quat_ang_deg([p1.get(k) for k in ("qx", "qy", "qz", "qw")],
                                         pts[tgt_name].get("quat") or [0, 0, 0, 0]) or 0, 1)})
            jline(rec)
            if arrived:
                fails = 0
                log("  ✓ 到位 (残差 %.1fmm · %.1fs · 实速 %.2fmm/s)" % (dev, took, path_mm / took if took else 0))
            else:
                fails += 1
                log("  ⚠ 未到位 (残差 %s mm · 等满 %.0fs) ⇒ fail %d/%d"
                    % ("?" if dev is None else "%.1f" % dev, args.timeout, fails, args.max_fail))
                if fails >= args.max_fail:
                    log("⛔ 连续 %d 跳未到位 ⇒ 停" % fails)
                    break
            i += 1
    finally:
        if cap is not None:
            try:
                open(os.path.join(sess, "STOP"), "w").close()
                cap.wait(timeout=25)
                log("采集收工")
            except Exception:                                                  # noqa: BLE001
                cap.terminate()
        try:
            json.dump({"running": False, "step": "done", "status_line": "循环结束 (共 %d 跳)" % i,
                       "ts": time.strftime("%F %T")}, open(STATUS, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:                                                      # noqa: BLE001
            pass
        log("结束: 共 %d 跳 · 证据 %s" % (i, HOP_LOG))
    return 0


if __name__ == "__main__":
    sys.exit(main())
