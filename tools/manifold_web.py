#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifold_web.py — 流形引擎 · 相空间安全通道 网页 (只读, 手机可开)

老倪 2026-11-20: 「你先把流形的网页给我，我自己打开」

    http://192.168.23.50:8819/          ← 页面 (自适应手机)
    http://192.168.23.50:8819/api/state ← 真值 + 通道判据 (JSON)

只暴露两样东西: 一张页面 + 一个只读 JSON。**不挂仓库根目录** (仓库里有 secrets)。
数字全部实时算: se3 真值取 zmax_data/se3/se3_state_live.json (zmax-se3-geom, 5Hz),
通道 V/τ/门控用 src/lerobot/manifold/phase_corridor.py 现场算, 不写死。
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

LIVE = os.path.join(ROOT, "zmax_data/se3/se3_state_live.json")
HIST = os.path.join(ROOT, "zmax_data/se3/se3_state_history.jsonl")
PAGE = os.path.join(ROOT, "reports/manifold_site/index.html")
PORT = int(os.environ.get("ZMAX_MANIFOLD_WEB_PORT") or 8819)

_CORR = None


# ── 昨天的 se3 服务 (8815 分层几何看板 / 8817 跟随 / 5Hz 状态) ───────────────
SERVICES = [("zmax-se3-geom", 8815, "SE(3) 分层几何看板"),
            ("zmax-se3-state", 0, "A–E 状态向量 5Hz"),
            ("zmax-se3-follow", 8817, "跟随真机 · 五流形")]


def _systemctl(unit):
    import subprocess
    try:
        out = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState",
                              "-p", "ExecMainPID", "-p", "ActiveEnterTimestampMonotonic"],
                             capture_output=True, text=True, timeout=3).stdout
        d = dict(l.split("=", 1) for l in out.strip().splitlines() if "=" in l)
        return {"active": d.get("ActiveState") == "active", "state": d.get("SubState"),
                "pid": int(d.get("ExecMainPID") or 0)}
    except Exception:
        return {"active": False, "state": "unknown", "pid": 0}


def _svc_block():
    import urllib.request
    rows = []
    for unit, port, note in SERVICES:
        s = _systemctl(unit)
        s.update({"unit": unit, "port": port, "note": note})
        if port:
            s["url"] = "http://192.168.23.50:%d/" % port
        rows.append(s)
    geo = None
    try:                                     # 8815 的分层数据 (R3 / S3 / S2 / S1)
        with urllib.request.urlopen("http://127.0.0.1:8815/api/se3", timeout=2) as r:
            g = json.loads(r.read().decode("utf-8"))
        geo = {"tcp_mm": g.get("tcp_mm"), "quat": g.get("quat"), "phi_deg": g.get("phi_deg"),
               "axis_err_deg": g.get("axis_err_deg"), "n": g.get("n"),
               "nearest": g.get("nearest"), "age_s": g.get("age_s"), "truth_src": g.get("truth_src")}
    except Exception as e:                                                # noqa: BLE001
        geo = {"error": "%s: %s" % (type(e).__name__, e)}
    fol = None
    try:                                     # 8817 五流形 A~E (昨天的跟随服务)
        with urllib.request.urlopen("http://127.0.0.1:8817/api/follow", timeout=2) as r:
            f = json.loads(r.read().decode("utf-8"))
        fol = {k: f.get(k) for k in ("A", "B", "C", "D", "E", "age_s", "n_truth", "truth_src", "err")}
        fol["ts"] = f.get("ts")
    except Exception as e:                                                # noqa: BLE001
        fol = {"error": "%s: %s" % (type(e).__name__, e)}
    return {"services": rows, "geom": geo, "follow": fol}



def _corr():
    global _CORR
    if _CORR is None:
        from lerobot.manifold.phase_corridor import CorridorMetric, PhaseSpaceCorridor
        _CORR = PhaseSpaceCorridor(CorridorMetric(payload_kg=0.1), epsilon=0.30, alpha=1.5, lam=2.0)
    return _CORR


def _vec2sample(v):
    """16 维向量 → 样本: [x,y,z, ax,ay,az, dev, qw,qx,qy,qz, roll, s, arc, i, age]"""
    return {
        "pos_mm": [round(v[0], 1), round(v[1], 1), round(v[2], 1)],
        "axis": [round(v[3], 4), round(v[4], 4), round(v[5], 4)],
        "axis_err_deg": round(v[6], 2),
        "quat": [round(v[7], 4), round(v[8], 4), round(v[9], 4), round(v[10], 4)],   # qw,qx,qy,qz
        "roll_rad": round(v[11], 4),
        "s": round(v[12], 6),
        "arc_mm": round(v[13], 2),
        "nearest_i": int(v[14]),
        "age_s": round(v[15], 3),
    }


def _tail(n=400, back=400_000):
    """历史尾部 → [(ts, vector16)]；ts 取记录里的 ts (不是 t)，零位姿样本丢掉。"""
    out = []
    try:
        with open(HIST, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - back))
            chunk = f.read().decode("utf-8", "ignore").splitlines()
        for ln in chunk[-n:]:
            try:
                d = json.loads(ln)
            except Exception:
                continue
            v = d.get("vector") or d.get("vec")
            ts = d.get("ts") or d.get("t")
            if not isinstance(v, list) or len(v) < 16 or ts is None:
                continue
            if all(abs(x) < 1e-9 for x in v[:3]):          # 全 0 = 陈旧/未就绪, 不做数
                continue
            out.append((float(ts), v))
    except Exception:
        return []
    return out


def _vel(prev, cur):
    """两个样本 → 线速度 m/s + 角速度 rad/s（真实差分，不外推）。"""
    import numpy as np
    dt = max(1e-3, float(cur[0]) - float(prev[0]))
    dp = (np.array(cur[1][:3], float) - np.array(prev[1][:3], float)) / 1000.0 / dt      # m/s
    q0 = _qnorm(prev[1][7:11])
    q1 = _qnorm(cur[1][7:11])
    # 相对四元数 → 角速度（小角近似足够 5Hz 差分）
    w0, x0, y0, z0 = q0
    w1, x1, y1, z1 = q1
    dw = w0 * w1 + x0 * x1 + y0 * y1 + z0 * z1
    sgn = 1.0 if dw >= 0 else -1.0
    dq = np.array([w1 - sgn * w0, x1 - sgn * x0, y1 - sgn * y0, z1 - sgn * z0]) * sgn
    om = 2.0 * dq[1:4] / dt
    return dp.tolist(), om.tolist()


def _qnorm(q):
    import math
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return [x / n for x in q]


def state():
    d = json.load(open(LIVE, encoding="utf-8"))
    v = d.get("vector")
    cur = _vec2sample(v) if v else {
        "pos_mm": d["pos_mm"], "axis": d["axis_S2"], "axis_err_deg": d["axis_err_deg"],
        "quat": d["quat_S3"], "roll_rad": d["roll_rad"], "s": d["s"],
        "arc_mm": d["arc_mm"], "nearest_i": d["nearest_i"], "age_s": 0.0,
    }
    out = {"ok": True, "ts": d.get("ts") or time.time(), "svc": d.get("svc", "zmax-se3-geom"),
           "truth_src": d.get("truth_src", ""), "se3": cur, "corridor": None, "engine": {}}

    # 相空间: 以 0.2s 前的真机记忆样本为中心线, 当前为实测; 速度取真差分
    hist = _tail(400)
    if len(hist) >= 2:
        t_now = hist[-1][0]
        ref, ref_ts = None, None
        for t, vv in reversed(hist):
            if t_now - t >= 0.2:
                ref, ref_ts = vv, t
                break
        if ref is None:
            ref, ref_ts = hist[0][1], hist[0][0]
        try:
            rs = _vec2sample(ref)
            v_cur, w_cur = _vel(hist[-2], hist[-1])
            v_ref, w_ref = (v_cur, w_cur) if len(hist) < 3 else _vel(hist[-3], hist[-2])
            qc, qr = _qnorm(cur["quat"]), _qnorm(rs["quat"])
            out["vel_mm_s"] = round((v_cur[0] ** 2 + v_cur[1] ** 2 + v_cur[2] ** 2) ** 0.5 * 1000, 1)
            out["ref"] = {"pos_mm": rs["pos_mm"], "s": rs["s"], "dt_s": round(t_now - ref_ts, 3)}
            out["trail"] = [[round(v[0], 1), round(v[1], 1), round(v[2], 1), round(float(t) - t_now, 3)]
                            for t, v in hist[-300:]]
            _p = hist[-300:]
            _span = max((max(v[i] for _, v in _p) - min(v[i] for _, v in _p)) for i in range(3))
            # 实测: 臂停着时 5Hz 真值仍有 ~1.1mm 抖动 ⇒ 2mm 内且速度 <2mm/s 算静止
            out["idle"] = (_span < 2.0) and (out.get("vel_mm_s") or 0.0) < 2.0
            if out["idle"]:                       # 静止时给一段更早的真实轨迹, 免页面只有一个点
                bg = _tail(6000, back=3_000_000)
                step = max(1, len(bg) // 900)
                out["trail_bg"] = [[round(v[0], 1), round(v[1], 1), round(v[2], 1)]
                                   for _, v in bg[::step]]
                out["trail_bg_span_min"] = round((bg[-1][0] - bg[0][0]) / 60, 1) if bg else 0
            r = _corr().compute(
                {"pos": [x / 1000.0 for x in cur["pos_mm"]], "quat": qc, "s1": cur["s"] * 6.283185,
                 "vel": v_cur, "omega": w_cur},
                {"pos": [x / 1000.0 for x in rs["pos_mm"]], "quat": qr,
                 "s1": rs["s"] * 6.283185, "vel": v_ref, "omega": w_ref},
                axis=cur["axis"])
            d = r.as_dict()
            tau = list(d.get("tau_safe") or [0, 0, 0, 0, 0, 0])
            out["corridor"] = {
                "gate": bool(d.get("gate")),
                "inside": bool(d.get("inside")),
                "V_phase": round(float(d.get("V_phase") or 0.0), 5),
                "V_pos": round(float(d.get("V_pos") or 0.0), 5),
                "V_vel": round(float(d.get("V_vel") or 0.0), 5),
                "tau_safe": [round(float(x), 3) for x in tau],
                "tau_norm": round(max(abs(float(x)) for x in tau), 3),
                "monotone": bool(d.get("monotone")),
                "alpha_eff": round(float(d.get("alpha_eff") or 0.0), 4),
                "phase_err_deg": round(float(d.get("phase_err_rad") or 0.0) * 57.2958, 2),
                "eps": (d.get("detail") or {}).get("eps"),
            }
        except Exception as e:                                              # noqa: BLE001
            out["corridor"] = {"error": "%s: %s" % (type(e).__name__, e)}

    try:
        out["service"] = _svc_block()
    except Exception as e:                                                  # noqa: BLE001
        out["service"] = {"error": "%s: %s" % (type(e).__name__, e)}

    try:
        from lerobot.manifold import manifold_engine as me
        reg = getattr(me, "MANIFOLD_REGISTRY", {}) or {}
        out["engine"] = {
            "manifolds": [k for k, v in reg.items() if str((v or {}).get("status", "ready")) == "ready"],
            "planned": [k for k, v in reg.items() if str((v or {}).get("status", "")) == "planned"],
            "M_default": getattr(me, "MANIFOLD_M_DEFAULT", None),
            "selftest": "python -m lerobot.manifold.manifold_engine --selftest",
        }
    except Exception as e:                                                  # noqa: BLE001
        out["engine"] = {"error": "%s: %s" % (type(e).__name__, e)}
    return out


class H(BaseHTTPRequestHandler):
    server_version = "zmax-manifold/1.0"

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                                       # noqa: N802
        p = self.path.split("?")[0]
        try:
            if p in ("/", "/index.html", "/manifold"):
                self._send(200, open(PAGE, "rb").read(), "text/html; charset=utf-8")
            elif p == "/api/state":
                self._send(200, json.dumps(state(), ensure_ascii=False))
            elif p == "/api/health":
                self._send(200, json.dumps({"ok": True, "t": time.time(), "port": PORT}))
            else:
                self._send(404, json.dumps({"ok": False, "why": "只提供 / 与 /api/state"}))
        except Exception as e:                                              # noqa: BLE001
            self._send(500, json.dumps({"ok": False, "err": "%s: %s" % (type(e).__name__, e)},
                                       ensure_ascii=False))

    def log_message(self, fmt, *a):                                          # 静音
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("流形引擎网页: http://0.0.0.0:%d/  (只读, 页面 + /api/state)" % PORT, flush=True)
    srv.serve_forever()
