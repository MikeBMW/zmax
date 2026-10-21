#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NPU 单帧 31ms 是不是"空闲唤醒"开销 —— 用多流连续压测对比 (只读, 不碰服务)。"""
import concurrent.futures as cf
import time

import numpy as np
import openvino as ov

XML = "/home/intel/edge_models/ir/intact_enc.xml"
N = 40
c = ov.Core()


def run(streams, parallel):
    # NPU 插件不支持 NUM_STREAMS ⇒ 用同一个 compiled model 上开多个 infer request (这也是 edge_service 的做法)
    m = c.compile_model(XML, "NPU", {"PERFORMANCE_HINT": "LATENCY"})
    _in = m.inputs[0]
    x = np.zeros([d.get_length() for d in _in.get_partial_shape()], dtype=np.float32)
    reqs = [m.create_infer_request() for _ in range(streams)]
    for r in reqs:
        r.infer({_in: x})
    t = time.perf_counter()
    if parallel:
        with cf.ThreadPoolExecutor(streams) as ex:
            list(ex.map(lambda k: [reqs[k].infer({_in: x}) for _ in range(N // streams)], range(streams)))
    else:
        for r in reqs:
            for _ in range(N // streams):
                r.infer({_in: x})
    dt = time.perf_counter() - t
    print("%d 流 · %s: %6.1f fps · 每次 %5.2f ms" % (streams, "并行" if parallel else "串行",
                                                     N / dt, dt / N * 1000), flush=True)


for s in (1, 2, 4):
    run(s, s > 1)
run(1, False)
