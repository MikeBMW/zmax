# 把带动态维的导出图固化成全静态 (以 SAM3 ViT 编码器为例)

场景: 目标设备 (Intel NPU/vpux) 只吃全静态图, 而导出的 ONNX/IR 里有若干个“? 维度”,
编译器报的是完全无关的常量错误 (`dense resource buffer ... tensor<4xsi64>`)。

## 0. 先量化问题

```python
m = ov.Core().read_model(IR)
dyn = [n for n in m.get_ordered_ops() if any(o.get_partial_shape().is_dynamic for o in n.outputs())]
print(len(dyn), [(n.get_type_name(), n.get_friendly_name()) for n in dyn[:5]])
```

实测: 只有 3 个, 全在 `.../embeddings` 下 `Tile → Slice_1 → Transpose` (= 位置编码插值),
输入 `[1,3,1008,1008]` 与输出 `[1,5184,1024]` 本来就是静态的。

## 1. 为什么会带动态维: tracing 一定走插值分支

DETR/SAM 系的视觉 embedding 模块形如:

```python
def position_embeddings(self, pixel_values):
    h, w = pixel_values.shape[-2] // self.patch_size
    if not torch.jit.is_tracing() and (h, w) == (self.pretrain_h, self.pretrain_w):
        return self.positions          # 只有非 tracing 且尺寸相同才短路
    return self._tile_position_embeddings(self.positions, h, w)   # 导出时必然走这里 → Tile/Slice
```

⇒ 只在导出侧“告诉它已经算好了”最省事: 把 tiling 换成**预计算 + 缓存**, tracing 命中缓存就是常量。

## 2. 固化做法 (导出脚本里加十几行, 不动模型代码)

```python
emb, orig_tile, cache = enc.backbone.embeddings, enc.backbone.embeddings._tile_position_embeddings, {}

def static_tile(position_embeddings, height, width):
    key = (int(height), int(width))            # tracing 时可能是 tensor, 必须 int()
    if key not in cache:
        with torch.no_grad():
            cache[key] = orig_tile(position_embeddings, key[0], key[1]).detach().clone()
    return cache[key]                          # 返回纯常量 → 图里不再出现 Tile/Slice

emb._tile_position_embeddings = static_tile
with torch.no_grad():                          # 先非 tracing 预热一次, 把缓存填上
    Wrap(enc)(torch.zeros(1, 3, H, W))
torch.onnx.export(Wrap(enc), (x,), ONNX, opset_version=17, do_constant_folding=True,
                  input_names=["pixel_values"], output_names=["features"], dynamo=False)
```

实例属性覆盖必须用**普通函数** (不绑 self), 因为 forward 里是 `self.embeddings._tile_position_embeddings(h, w)` 形式调用。

## 3. 三项校验 (缺一项就是没做完)

1. **动态维 = 0**: 转 IR 后重跑步骤 0 的判据。
2. **语义没变**: 新旧 IR 对同一份 torch 参考比**误差分布** (见 SKILL.md 7.5); 逐项相同才算“只是去掉了动态”。
   实测: max|Δ| 12.03 / mean 5.3e-3 / p99 3.0e-2 / |rel| 中位 6.2e-3 — 新旧完全一致 ⇒ 改动无害, 大 max 属 fp16 量化。
3. **目标设备实测 ms/帧 对得上再谈上线** (见 7.6: NPU 编译成功但 0.48 fps ⇒ 弃用)。

## 4. 如果固化后仍编不过

按代价递增往下走: `onnxsim` 常量折叠 (GB 级模型吃 >8 GB 内存, 换台内存大的机器跑) →
拆两段 (patch-embed conv 上 NPU / transformer blocks 上 GPU) → 放弃该设备改 iGPU。

## 5. 远端长编译/大文件传输纪律 (都是实测代价)

- 远端脚本一律 `python -u` 且输出重定向到文件: `ssh host 'python -u x.py | grep -v X | tail'` 在管道块缓冲下,
  进程一被 `timeout` 杀就整段输出全丢 (只剩第一行), 看起来像“没跑”。
- ssh 会话活不过 ~25 min: 实测 1500 s 报 `Timeout, server ... not responding` + `Broken pipe`, 远端进程跟着没了。
  长编译 (`nohup ... > log 2>&1 &`) 起在远端, 本地只 `tail` + `ps -o etime,pcpu,rss` 轮询判活; 编译期无进度输出属正常,
  用 CPU%/RSS 判, 不要重启 (重来就是整套编译时间)。
- GB 级 IR 过慢隧道 (0.15~0.46 MB/s, 会波动): `rsync -P --append-verify` 循环续传, 收尾比 **sha256**;
  传之前先量一次速率 (`stat` 两次差分) 再给 ETA, 别拿首次速度当全程。
