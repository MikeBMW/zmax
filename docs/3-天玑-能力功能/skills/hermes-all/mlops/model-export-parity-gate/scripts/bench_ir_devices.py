#!/usr/bin/env python3
"""IR 逐设备实测 (NPU / GPU / CPU) —— 导出对账第 5 步「报数」用的通用探针。

用法 (目标机上, 用装好 OpenVINO 的 python):
    <venv>/bin/python bench_ir_devices.py /path/model.xml 1,3,640,640
    <venv>/bin/python bench_ir_devices.py /path/model.xml 1,3,1008,1008 --iters 6

口径要点:
  · NPU 单请求会被串行化 (实测 +31ms) ⇒ 同时开多个 InferRequest 才是真实吞吐;
    NPU 插件不支持 NUM_STREAMS, 靠多 request 并发。
  · 编译失败**不是**失败退出: 逐个设备报「编译失败: <类型>: <首 300 字>」—— 编译器 diagnostic 里点名的节点/类型就是根因。
  · 目标机上若已有服务占着加速器, 先停再量, 否则量到的是争抢后的数; 量完恢复并回读占空。
"""
import argparse
import statistics
import sys
import time

import numpy as np
import openvino as ov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ir")
    ap.add_argument("shape", help="逗号分隔, 如 1,3,640,640")
    ap.add_argument("--devices", default="NPU,GPU,CPU")
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--npu-reqs", type=int, default=2)
    a = ap.parse_args()
    shape = tuple(int(v) for v in a.shape.split(","))

    core = ov.Core()
    model = core.read_model(a.ir)
    print("openvino", ov.__version__)
    print("输入:", model.input(0).get_partial_shape(), model.input(0).get_element_type(),
          "| 输出:", model.output(0).get_partial_shape())
    x = np.random.rand(*shape).astype(np.float32) * 0.5 + 0.25

    for dev in [d.strip() for d in a.devices.split(",") if d.strip()]:
        try:
            t0 = time.time()
            cm = core.compile_model(model, dev)
            cms = (time.time() - t0) * 1000
        except Exception as e:                                          # noqa: BLE001
            print("%-4s 编译失败: %s: %s" % (dev, type(e).__name__, str(e)[:300]))
            continue
        nreq = a.npu_reqs if dev == "NPU" else 1
        reqs = [cm.create_infer_request() for _ in range(nreq)]
        for r in reqs:
            r.infer({0: x})
        ts = []
        for _ in range(a.iters):
            t0 = time.time()
            for r in reqs:
                r.infer({0: x})
            ts.append((time.time() - t0) / nreq * 1000.0)
        med = statistics.median(ts)
        out = reqs[0].get_output_tensor(0).data
        print("%-4s 编译 %6.0f ms | %d 请求并发 | 中位 %8.2f ms/帧 = %7.2f fps | p95 %8.2f ms | 输出 %s %s"
              % (dev, cms, nreq, med, 1000.0 / med, max(ts), out.shape, out.dtype))
    return 0


if __name__ == "__main__":
    sys.exit(main())
