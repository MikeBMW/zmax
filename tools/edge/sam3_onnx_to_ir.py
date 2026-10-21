#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAM3 编码器 ONNX → OpenVINO IR (fp16 权重), 在工程机上转好再传给 intel (省一半传输量)。"""
import os
import time

import openvino as ov

SRC = "/home/ubuntu/zmax/zmax_data/models/ir/sam3_enc.onnx"
DST = "/home/ubuntu/zmax/zmax_data/models/ir/sam3_enc.xml"

t0 = time.time()
print("[1/3] convert_model(%s)…" % os.path.basename(SRC), flush=True)
m = ov.convert_model(SRC)
print("    inputs: %s" % [(i.get_any_name(), i.get_partial_shape()) for i in m.inputs], flush=True)
print("    outputs: %s" % [(o.get_any_name(), o.get_partial_shape()) for o in m.outputs], flush=True)
print("[2/3] save IR fp16…", flush=True)
ov.save_model(m, DST, compress_to_fp16=True)
b = os.path.getsize(DST.replace(".xml", ".bin")) / 1e6
print("    IR = %.1f MB (bin) + %.2f MB (xml) · %.1f 分钟" % (b, os.path.getsize(DST) / 1e6, (time.time() - t0) / 60), flush=True)
print("[3/3] 本机 CPU 单帧校验…", flush=True)
c = ov.Core()
cm = c.compile_model(DST, "CPU")
import numpy as np                                                            # noqa: E402
x = np.zeros([d.get_length() for d in cm.inputs[0].get_partial_shape()], dtype=np.float32)
t = time.perf_counter()
cm(x)
print("    CPU 单帧 %.0f ms · 输出 %s" % ((time.perf_counter() - t) * 1000,
                                          [tuple(o.shape) for o in cm.outputs]), flush=True)
print("DONE", flush=True)
