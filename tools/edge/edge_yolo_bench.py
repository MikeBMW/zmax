#!/usr/bin/env python3
"""550C 端侧实时性实测: yolo_peg_live (L2 现役检测权重) 在 Intel Nodka (X7 358H / Arc B390 / NPU) 上跑 OpenVINO.
只做一件事: 给出可信的 ms/帧 与 FPS, 分 NPU / GPU / CPU 三档。
用法: python edge_yolo_bench.py <onnx 路径> [--ir-dir DIR] [--iters 100] [--imgsz 640]
"""
import argparse
import json
import os
import time

import numpy as np
import openvino as ov


def to_ir(onnx_path, ir_dir, imgsz=640):
    base = os.path.join(ir_dir, os.path.splitext(os.path.basename(onnx_path))[0])
    if os.path.isfile(base + ".xml"):
        return base + ".xml"
    ovc = os.environ.get("OVC", "")
    m = ov.convert_model(onnx_path, input=[1, 3, imgsz, imgsz])
    ov.save_model(m, base + ".xml", compress_to_fp16=True)
    return base + ".xml"


def bench(xml, device, iters=100, imgsz=640):
    core = ov.Core()
    model = core.read_model(xml)
    # 线程数只对 CPU 插件合法; NPU/GPU 插件收到未知键会直接 NOT_FOUND 报错
    cfg = {"INFERENCE_NUM_THREADS": str(min(8, os.cpu_count() or 4))} if device.upper().startswith("CPU") else {}
    t0 = time.perf_counter()
    cm = core.compile_model(model, device, cfg)
    compile_ms = (time.perf_counter() - t0) * 1000.0
    out = cm.output(0)
    x = np.random.rand(1, 3, imgsz, imgsz).astype(np.float32)

    for _ in range(10):          # 预热
        cm(x)
    lat = []
    for _ in range(iters):
        t = time.perf_counter()
        y = cm(x)[out]
        lat.append((time.perf_counter() - t) * 1000.0)
    lat = np.array(lat)
    # async 吞吐 (队列并发 = 最优, 常用 2~4)
    q = ov.AsyncInferQueue(cm, 4)
    done = {"n": 0}

    def cb(req, userdata):
        done["n"] += 1

    q.set_callback(cb)
    for _ in range(10):
        q.start_async(x)
    q.wait_all()
    done["n"] = 0
    t = time.perf_counter()
    for _ in range(iters):
        q.start_async(x)
    q.wait_all()
    thr_ms = (time.perf_counter() - t) * 1000.0 / iters
    return {
        "device": device,
        "compile_ms": round(compile_ms, 1),
        "latency_ms_median": round(float(np.median(lat)), 2),
        "latency_ms_p95": round(float(np.percentile(lat, 95)), 2),
        "fps_single": round(1000.0 / float(np.median(lat)), 1),
        "async4_ms_per_frame": round(thr_ms, 2),
        "fps_async4": round(1000.0 / thr_ms, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("onnx")
    ap.add_argument("--ir-dir", default=os.path.expanduser("~/edge_models/ir"))
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--devices", default="NPU,GPU,CPU")
    a = ap.parse_args()
    os.makedirs(a.ir_dir, exist_ok=True)
    xml = to_ir(a.onnx, a.ir_dir, a.imgsz)
    print("IR:", xml, os.path.getsize(xml) // 1024, "KB (xml) +", os.path.getsize(xml[:-4] + ".bin") // 1024, "KB (bin)")
    rows = []
    for dev in [d.strip() for d in a.devices.split(",") if d.strip()]:
        try:
            r = bench(xml, dev, a.iters, a.imgsz)
            rows.append(r)
            print(json.dumps(r, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"device": dev, "error": str(e)[:200]}, ensure_ascii=False))
    print("\n== 汇总 ==")
    for r in rows:
        if "fps_single" in r:
            print("%-5s 单帧 %6.2f ms (p95 %6.2f) = %6.1f FPS | 并发4 %6.2f ms/帧 = %6.1f FPS | 编译 %5.1f ms"
                  % (r["device"], r["latency_ms_median"], r["latency_ms_p95"], r["fps_single"],
                     r["async4_ms_per_frame"], r["fps_async4"], r["compile_ms"]))
    with open(os.path.join(a.ir_dir, "bench_result.json"), "w") as f:
        json.dump({"model": a.onnx, "imgsz": a.imgsz, "iters": a.iters, "rows": rows,
                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
