#!/usr/bin/env python3
"""NPU 侧: 静态 IR 编译 + 时延 (1/2 请求并发)。编译可能要几分钟, 每步都 flush。"""
import statistics
import sys
import time

import numpy as np
import openvino as ov

IR = "/home/intel/edge_models/ir/sam3_enc_static.xml"
core = ov.Core()
m = core.read_model(IR)
x = np.load("/tmp/parity_x.npy")
ref = np.load("/tmp/parity_ref.npy")
print("openvino", ov.__version__, "| 设备", core.available_devices, flush=True)

for nreq in (int(sys.argv[1]) if len(sys.argv) > 1 else 2,):
    t = time.time()
    try:
        cm = core.compile_model(m, "NPU")
    except Exception as e:                                              # noqa: BLE001
        print("NPU 编译失败 (%.0fs): %s" % (time.time() - t, str(e)[-500:].replace("\n", " ")), flush=True)
        raise SystemExit(2)
    print("NPU 编译 %.0f s" % (time.time() - t), flush=True)
    reqs = [cm.create_infer_request() for _ in range(nreq)]
    for k, r in enumerate(reqs):
        t = time.time()
        r.infer({0: x})
        print("  请求%d 首帧 %.0f ms" % (k, (time.time() - t) * 1000), flush=True)
    ts = []
    for _ in range(5):
        t = time.time()
        for r in reqs:
            r.infer({0: x})
        ts.append((time.time() - t) / nreq * 1000)
    med = statistics.median(ts)
    y = np.asarray(reqs[0].get_output_tensor(0).data)
    d = np.abs(y - ref)
    print("NPU %d 并发: 中位 %.1f ms/帧 = %.2f fps | p95 %.1f ms | max|Δ| vs torch %.3e"
          % (nreq, med, 1000 / med, max(ts), d.max()), flush=True)
