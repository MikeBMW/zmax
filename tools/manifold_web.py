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


def _tail(n=40):
    out = []
    try:
        with open(HIST, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            chunk = f.read().decode("utf-8", "ignore").splitlines()
        for ln in chunk[-n:]:
            try:
                d = json.loads(ln)
            except Exception:
                continue
            v = d.get("vector") or d.get("vec")
            if isinstance(v, list) and len(v) >= 16 and any(abs(x) > 1e-9 for x in v[:3]):
                out.append((float(d.get("t") or v[15] and 0 or 0), v))
    except Exception:
        return []
    return out


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

    # 相空间: 以 0.2s 前的记忆样本为中心线, 当前为实测
    hist = _tail(40)
    if hist:
        tcur = time.time()
        ref = None
        for t, vv in reversed(hist):
            if tcur - (t or 0) >= 0.2:
                ref = vv
                break
        ref = ref or hist[-1][1]
        try:
            qc, qr = _qnorm(cur["quat"]), _qnorm(_vec2sample(ref)["quat"])
            r = _corr().compute(
                {"pos": [x / 1000.0 for x in cur["pos_mm"]], "quat": qc, "s1": cur["s"] * 6.283185,
                 "vel": [0.0] * 3, "omega": [0.0] * 3},
                {"pos": [x / 1000.0 for x in _vec2sample(ref)["pos_mm"]], "quat": qr,
                 "s1": _vec2sample(ref)["s"] * 6.283185, "vel": [0.0] * 3, "omega": [0.0] * 3},
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
