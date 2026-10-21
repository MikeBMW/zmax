#!/usr/bin/env python3
"""SAM3 编码器 定点重导: 把位置编码 Tiling 固化成常量 ⇒ 全静态图 ⇒ NPU 才编得动。

为什么: 原 IR 在 /enc/backbone/embeddings 有 3 个动态维节点
        (Tile [?,?,?,?] → Slice_1 → Transpose), VPUX 只吃全静态图, 编译器就在融合阶段崩,
        报的是 "dense resource buffer 1179648 vs tensor<4xsi64>" 这种迷惑性错误。

做法: Sam3ViTEmbeddings._tile_position_embeddings 在 tracing 时**永远**走 Tiling 分支
      (`if not torch.jit.is_tracing() and ...` ⇒ 导出时必然 tile) ⇒ 图里带 Tile/Slice。
      这里把整段换成"预计算一次 → 缓存 → 导出时直接当常量", 输入固定 1008 ⇒ 72x72 patch 网格。

产物: sam3_enc_static.onnx + sam3_enc_static.xml/.bin (fp16)
校验: ① 动态维节点数必须 = 0  ② 与 torch 输出同输入对照 max|Δ|
"""
import os
import sys
import time

import torch

P = "/home/ubuntu/zmax/zmax_data/models/sam3_hf"
ONNX = "/home/ubuntu/zmax/zmax_data/models/ir/sam3_enc_static.onnx"
IR = "/home/ubuntu/zmax/zmax_data/models/ir/sam3_enc_static.xml"
H = W = 1008


class Wrap(torch.nn.Module):
    def __init__(self, enc):
        super().__init__()
        self.enc = enc

    def forward(self, pixel_values):
        o = self.enc(pixel_values=pixel_values)
        if isinstance(o, torch.Tensor):
            return o
        for k in ("last_hidden_state", "hidden_states", "pooler_output"):
            v = getattr(o, k, None)
            if isinstance(v, torch.Tensor):
                return v
        if isinstance(o, (tuple, list)):
            return o[0]
        raise RuntimeError("encoder 输出形状不认识: %r" % (type(o),))


def main():
    t0 = time.time()
    from transformers import Sam3Model

    print("[1/6] load Sam3Model fp32 …", flush=True)
    m = Sam3Model.from_pretrained(P, torch_dtype=torch.float32, low_cpu_mem_usage=True).eval()
    enc = m.get_encoder(modality="image")
    emb = enc.backbone.embeddings
    orig_tile = emb._tile_position_embeddings
    cache = {}

    def static_tile(position_embeddings, height, width):
        key = (int(height), int(width))
        if key not in cache:
            with torch.no_grad():
                cache[key] = orig_tile(position_embeddings, key[0], key[1]).detach().clone()
            print("    预计算位置编码 %s → %s (缓存为常量)" % (key, tuple(cache[key].shape)), flush=True)
        return cache[key]

    emb._tile_position_embeddings = static_tile

    print("[2/6] 预热一次(填缓存, 非 tracing)…", flush=True)
    x = torch.zeros(1, 3, H, W, dtype=torch.float32)
    with torch.no_grad():
        y = Wrap(enc)(x)
    print("    torch 输出 %s" % (tuple(y.shape),), flush=True)

    print("[3/6] 导出 ONNX (opset17, 静态)…", flush=True)
    with torch.no_grad():
        torch.onnx.export(Wrap(enc), (x,), ONNX, opset_version=17, do_constant_folding=True,
                          input_names=["pixel_values"], output_names=["features"], dynamo=False)
    print("    ONNX %.0f MB" % (os.path.getsize(ONNX) / 1e6,), flush=True)

    print("[4/6] 转 IR fp16 …", flush=True)
    import openvino as ov
    ir_model = ov.convert_model(ONNX)
    dyn = [n for n in ir_model.get_ordered_ops()
           if any(o.get_partial_shape().is_dynamic for o in n.outputs())]
    print("    动态维节点: %d" % len(dyn), flush=True)
    for n in dyn[:8]:
        print("      ·", n.get_type_name(), n.get_friendly_name()[:60], flush=True)
    if dyn:
        print("!! 仍有动态维, NPU 依旧编不动 —— 需要继续固化", flush=True)
    ov.save_model(ir_model, IR, compress_to_fp16=True)
    print("    IR %.0f MB bin" % (os.path.getsize(IR.replace('.xml', '.bin')) / 1e6,), flush=True)

    print("[5/6] 语义对照: IR(GPU) vs torch …", flush=True)
    core = ov.Core()
    cm = core.compile_model(IR, "GPU")
    xi = (torch.rand(1, 3, H, W) * 0.5 + 0.25)
    ref = Wrap(enc)(xi).detach().numpy()
    got = cm({0: xi.numpy()})[cm.output(0)]
    print("    max|Δ|=%.3e mean|Δ|=%.3e shape %s vs %s"
          % (abs(got - ref).max(), abs(got - ref).mean(), got.shape, ref.shape), flush=True)

    print("[6/6] 本机 GPU 时延参考…", flush=True)
    import statistics
    ts = []
    for _ in range(3):
        t = time.time()
        cm({0: xi.numpy()})
        ts.append((time.time() - t) * 1000)
    print("    本机 GPU 中位 %.1f ms/帧" % statistics.median(ts), flush=True)
    print("DONE %.1f 分钟" % ((time.time() - t0) / 60), flush=True)


if __name__ == "__main__":
    sys.exit(main())
