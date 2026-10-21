#!/usr/bin/env python3
"""GPU 侧: 静态 IR vs torch 参考的数值一致性 + 时延。"""
import statistics
import time

import numpy as np
import openvino as ov

IR = "/home/intel/edge_models/ir/sam3_enc_static.xml"
core = ov.Core()
m = core.read_model(IR)
dyn = [n for n in m.get_ordered_ops() if any(o.get_partial_shape().is_dynamic for o in n.outputs())]
print("动态维节点:", len(dyn), "| 输入", [str(i.get_partial_shape()) for i in m.inputs], flush=True)

x = np.load("/tmp/parity_x.npy")
ref = np.load("/tmp/parity_ref.npy")
t = time.time()
cm = core.compile_model(m, "GPU")
print("GPU 编译 %.0f ms" % ((time.time() - t) * 1000), flush=True)
t = time.time()
got = cm({0: x})[cm.output(0)]
print("首帧 %.0f ms" % ((time.time() - t) * 1000), flush=True)
d = np.abs(got - ref)
print("vs torch: max|Δ|=%.3e mean|Δ|=%.3e |rel|=%.2e"
      % (d.max(), d.mean(), (d / np.maximum(np.abs(ref), 1e-6)).mean()), flush=True)
ts = []
for _ in range(5):
    t = time.time()
    cm({0: x})
    ts.append((time.time() - t) * 1000)
med = statistics.median(ts)
print("GPU 中位 %.1f ms/帧 = %.2f fps | p95 %.1f ms" % (med, 1000 / med, max(ts)), flush=True)
