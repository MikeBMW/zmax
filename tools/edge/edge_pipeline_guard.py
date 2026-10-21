#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edge_pipeline_guard.py — 让 Intel 端「全模型并行推理」常驻且自愈。

老倪 2026-10-21: 「所有模型都要在 intel上稳定推理部署运行」「将 NPU GPU 最大化使用」
做法: 这个脚本不自己跑推理, 只做三件事 (轻, 零依赖, 只 stdlib):
  ① 调 edge_service 的 POST /pipeline/start 把 NPU / GPU 各自的模型组拉起来;
  ② 每 15s 读 /pipeline/stats, 判「在跑 + 计数在涨 + 无 err」, 不满足就重启流水线, 连续失败就重启 zmax-edge;
  ③ 把每次判定和实测 fps/占空 落到 journal (systemd), 事后可查。

为什么不用 cron: 需要秒级发现 stall (NPU 崩了但进程还在), 且必须与 edge_service 生命周期解耦。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.environ.get("EDGE_BASE", "http://127.0.0.1:8800")
NPU = os.environ.get("EDGE_NPU_MODELS", "yolo_peg_live,intact_enc")
GPU = os.environ.get("EDGE_GPU_MODELS", "intact_pred,intact_enc")
IMG = os.environ.get("EDGE_SAT_IMG", "/home/intel/edge_models/20260917_124517_611.jpg")
STREAMS = os.environ.get("EDGE_STREAMS", "1")        # "2" 或 "NPU:GPU" 形如 "2:1"
HINT = os.environ.get("EDGE_HINT", "0")              # 1 = THROUGHPUT 编译 (实测反而更慢, 默认关)
TICK = float(os.environ.get("EDGE_GUARD_TICK", "15"))
MAX_FAIL = int(os.environ.get("EDGE_GUARD_MAX_FAIL", "3"))


def _get(path, timeout=8):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(path, timeout=20):
    req = urllib.request.Request(BASE + path, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def log(msg):
    print("[guard %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def start_pipeline():
    q = "/pipeline/start?npu=%s&gpu=%s&img=%s&streams=%s&hint=%s" % (NPU, GPU, IMG, STREAMS, HINT)
    try:
        r = _post(q)
        log("已启动流水线: %s" % json.dumps(r.get("plan"), ensure_ascii=False))
        return True
    except Exception as e:                                            # noqa: BLE001
        log("启动失败: %s: %s" % (type(e).__name__, str(e)[:120]))
        return False


def main():
    fails = 0
    last_n = {}
    while True:
        try:
            st = _get("/pipeline/stats")
        except Exception as e:                                        # noqa: BLE001
            log("服务不可达 (%s) → 重启 zmax-edge" % str(e)[:80])
            subprocess.run(["sudo", "-n", "systemctl", "restart", "zmax-edge"], check=False)
            time.sleep(12)
            start_pipeline()
            last_n = {}
            continue

        devs = st.get("devices") or {}
        if not st.get("on") or not devs:
            log("流水线未在跑 → 拉起")
            start_pipeline()
        else:
            bad = []
            for dev, d in devs.items():
                n = d.get("n") or 0
                if d.get("err"):
                    bad.append("%s err=%s" % (dev, d["err"]))
                if dev in last_n and n <= last_n[dev]:
                    bad.append("%s 计数不涨 (%s→%s)" % (dev, last_n[dev], n))
                last_n[dev] = n
            if bad:
                fails += 1
                log("判活不过 (%d/%d): %s" % (fails, MAX_FAIL, "; ".join(bad)))
                if fails >= MAX_FAIL:
                    log("连续 %d 次不过 → 重启 zmax-edge 再拉起" % fails)
                    subprocess.run(["sudo", "-n", "systemctl", "restart", "zmax-edge"], check=False)
                    time.sleep(12)
                    fails = 0
                    last_n = {}
                start_pipeline()
            else:
                fails = 0
                summary = " | ".join(
                    "%s %s fps 占空 %s%% 均值 %sms" % (d, v.get("fps"), v.get("duty_pct"), v.get("avg_ms"))
                    for d, v in devs.items())
                log("OK 合计 %s fps: %s" % (st.get("total_fps"), summary))
        time.sleep(TICK)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        print(json.dumps(_get("/pipeline/stats"), ensure_ascii=False, indent=2))
        sys.exit(0)
    main()
