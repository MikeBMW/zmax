"""SE(3) 分层几何看板服务 (8815)。

一张页面把状态口径按流形对象画出来, 另开一个只读 JSON 给页面标"现在":
  位置 ∈ ℝ³   → 路径 + 包围盒 + 停留点 (主图)
  姿态 ∈ S³   → 四元数轴角球 (点 = 虚部, 半径 = sin(θ/2))
  S² 轴       → 单位球 + 轴轨迹 + 孔轴参考 + 轴误差
  S¹ 滚转     → 表盘指针 φ + Δφ/帧
  TQ 速度     → 沿路径的切向箭头 (颜色 = flow 四档)
  S¹ 相位     → 弧长相位环 + s 读数 (traj_phase.json)

刻意不做的事: 不改任何轨迹/执行文件, 只读 tools/web/real_traj_joints.json、
zmax_data/rokae_sdk/traj_hopf.json、traj_phase.json 和真值 tcp_out/latest.json。
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

REPO = "/home/ubuntu/zmax"
WEB = os.path.join(REPO, "tools", "web")
SDK = os.path.join(REPO, "zmax_data", "rokae_sdk")
_J = {}


def _load(path, key):
    """带 mtime 缓存: 文件改了才重读, 免得每 1s 都 parse 一次 30KB JSON。"""
    try:
        m = os.path.getmtime(path)
    except OSError:
        return None
    hit = _J.get(key)
    if hit and hit[0] == m:
        return hit[1]
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        return hit[1] if hit else None
    _J[key] = (m, d)
    return d


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):                                           # 静音, 不刷 journal
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                                    # noqa: N802
        p = urlparse(self.path).path
        if p in ("/", "/index.html", "/se3", "/se3/"):
            try:
                h = open(os.path.join(WEB, "se3_geom.html"), "rb").read()
            except OSError as e:
                return self._send(500, {"ok": False, "why": "看板文件缺失: %s" % e})
            return self._send(200, h, "text/html; charset=utf-8")
        if p == "/api/se3":
            return self._send(200, self._live())
        if p == "/healthz":
            return self._send(200, {"ok": True, "svc": "zmax-se3-geom", "ts": time.time()})
        return self._send(404, {"ok": False, "why": "not found: %s" % p})

    def _live(self):
        """现在: 真机 TCP 最近点投影 → (i, s) + 该点姿态/速度; 不做任何下发。"""
        traj = _load(os.path.join(WEB, "real_traj_joints.json"), "traj")
        hopf = _load(os.path.join(SDK, "traj_hopf.json"), "hopf")
        phase = _load(os.path.join(SDK, "traj_phase.json"), "phase")
        tcp = _load(os.path.join(SDK, "tcp_out", "latest.json"), "tcp")
        out = {"ok": True, "ts": time.time(), "svc": "zmax-se3-geom"}
        if not traj:
            out.update({"ok": False, "why": "traj 缺失"})
            return out
        P = [[c * 1000.0 for c in f["p"]] for f in traj["frames"]]
        out["n"] = len(P)
        if tcp:
            q = [tcp["x"] * 1000.0, tcp["y"] * 1000.0, tcp["z"] * 1000.0]
            d = [((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2) ** 0.5 for p in P]
            i = d.index(min(d))
            out["tcp_mm"] = [round(v, 1) for v in q]
            out["age_s"] = round(time.time() - float(tcp.get("ts") or 0), 2)
            out["nearest"] = {"i": i, "dist_mm": round(min(d), 1)}
            if phase:
                r = phase["frames"][i]
                out["nearest"].update({"s": r["s"], "s_mm": r["s_mm"]})
            if hopf:
                hf = hopf["frames"][i]
                out["nearest"].update({"n": hf.get("n"), "phi_deg": hf.get("phi_deg")})
            if tcp.get("joints"):
                out["joints_deg"] = [round(v * 180.0 / 3.141592653589793, 2) for v in tcp["joints"]]
        # 🌀 实时姿态 → Hopf 拆 S²(轴) + S¹(滚转), 公式与 tools/se3_hopf.py 同源:
        #    n=(2(xz+wy), 2(yz-wx), w²+z²-x²-y²),  φ=2·atan2(z,w)
        if tcp and tcp.get("qw") is not None:
            w = float(tcp["qw"]); x = float(tcp["qx"]); y = float(tcp["qy"]); z = float(tcp["qz"])
            nn = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
            w, x, y, z = w / nn, x / nn, y / nn, z / nn
            n = [2.0 * (x * z + w * y), 2.0 * (y * z - w * x), w * w + z * z - x * x - y * y]
            ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
            out["quat"] = [round(v, 6) for v in (w, x, y, z)]
            out["n"] = [round(v / ln, 6) for v in n]
            out["phi_deg"] = round(2.0 * __import__("math").degrees(__import__("math").atan2(z, w)), 3)
            # 与孔轴(插入段参考)的夹角, 现场看姿态偏没偏
            ref = (hopf or {}).get("frames", [{}])[30].get("n")
            if ref:
                d = sum(a * b for a, b in zip(out["n"], ref))
                out["axis_err_deg"] = round(__import__("math").degrees(
                    __import__("math").acos(max(-1.0, min(1.0, d)))), 2)
        out["summary"] = (phase or {}).get("summary") if phase else None
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8815)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print("zmax-se3-geom on http://%s:%d/  (看板 / · 实时 /api/se3 · 健康 /healthz)" % (a.host, a.port),
          flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
