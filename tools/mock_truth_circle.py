#!/usr/bin/env python3
"""Mock 真值服务: 让一台假机器人走一圈圆 (验证 se3_follow 的学习/闭环/E 相位逻辑)。
只在本机 8819 上跑, 与真机链路完全隔离。
"""
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

T0 = time.time()
R = 120.0          # mm
OMEGA = 0.5        # rad/s  ⇒ 一圈 12.6 s, 弧长 ~754 mm


def pose():
    t = time.time() - T0
    a = OMEGA * t
    # 真值单位是**米** (8797 /api/tcp 口径); 圆的 R 在毫米里算完再 /1000
    x = (663.0 + R * math.cos(a)) / 1000.0
    y = (-29.0 + R * math.sin(a)) / 1000.0
    z = 291.0 / 1000.0
    # 姿态绕 z 缓慢转, 让 B/C/D 也动起来
    hz = 0.5 * a
    qx, qy, qz, qw = 0.766 * math.cos(hz), 0.075 * math.cos(hz), 0.615, 0.167
    nn = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    return {"ok": True, "x": x, "y": y, "z": z, "quat": [qx / nn, qy / nn, qz / nn, qw / nn],
            "joints": [0.1 * math.sin(a)] * 6, "age_s": 0.01}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        b = json.dumps(pose()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


if __name__ == "__main__":
    print("[mock] :8819 圆 R=%.0fmm omega=%.2f" % (R, OMEGA), flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8819), H).serve_forever()
