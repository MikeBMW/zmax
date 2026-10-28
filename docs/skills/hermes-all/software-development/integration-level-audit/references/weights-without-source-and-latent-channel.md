# 裸权重 → 真潜通道: 反推、体检、接进引擎

何时用: 盘上只有权重 (仓库里找不到对应的训练脚本), 用户问「代码在哪 / 这个模型真接了么」;
或要把任一外部潜模型 (视觉编码器 / 世界模型) 挂到 `ManifoldEngine` 上而不破坏它的几何与目标语义。

## A. 从 state_dict 反推结构 —— 报错就是规格

```python
ck = torch.load(p, map_location="cpu", weights_only=False)   # 常是裸 OrderedDict, 不是 {"state_dict": …}
net = build_guess(); missing, unexpected = net.load_state_dict(ck, strict=False)
```

- **只按键名/形状判层类型**: 成对的 `(d,)` 张量 = `LayerNorm(d)` (weight+bias), **不是** Linear;
  三个 0 维标量 `gate.0/1/2` = `nn.ParameterList([Parameter(torch.zeros(()))]*3)` —— 写成单个
  `Parameter(tensor([1.,1.,1.]))` 会报「缺 gate / 多 gate.0..2」, 那是规格提示, 不是失败。
- 循环到 `missing == unexpected == []`; 把 **张量数 + 参数量** 当硬证据写进判据 (实测 71 张量 / 2.68M)。
- `size mismatch` 报出的目标形状直接告诉你该层输出维 ⇒ 用它定 `d_z1/d_z2/d_z3`
  (实测 256/256/128; 融合层输入 640 = 三层之和, 用来交叉验证)。
- 权重**推不出来**的: conv stride/padding、残差注入顺序、gate 用原值还是 sigmoid。
  用**可测的量级线索**定口径, 并在文件头写明反推边界: 末层是 LayerNorm ⇒ 每层 `‖z‖≈√d`;
  实测 gate 原值 −3.0 时 `‖z₁‖=53 ≫ 16` (残差压过特征), `sigmoid(−3)≈0.047` 时 `‖z₁‖≈16.4` 与 LayerNorm 自洽
  ⇒ 取 sigmoid 口径, 并把两种口径的数字留在注释里供后人复核。

## B. 先体检输入, 再判模型 (顺序不能反)

- **帧内容体检**: 抽帧算 `mean/std`; `std≈1.3/255` 的是黑帧/冻结帧 (相机掉线的常见产物)。
  按 std 排序挑内容帧 —— 否则会把「没喂进内容」错判成「模型不看图」(实测某目录 40 张全黑, 差点得出错误结论)。
- **敏感度三测** (都便宜, 都要报数):
  1. 画面: 固定 state, 换 8 张真帧, 比 `v_enc` 输出余弦 (实测 0.9982~1.0000 ⇒ 图像支路近似常数);
  2. state: 单维 ±0.3 后比 `z_concat` 余弦 (实测 0.980~0.992 ⇒ state 真在用);
  3. 输出有限性 + 头维度 (实测头 98 维 = 7×14, 只报维度不宣称语义)。
- **判据线写死不许抬**: 图像支路生效取 `cos < 0.995`; 过不了就红着报, 结论写成
  「该权重 state 主导 / 欠训练, 不能当视觉编码器」, 不许抬阈值换绿再对外说已接入视觉。

## C. 接进引擎: 加第三通道, 不换主编码器

主编码器 (`Encoder` PCA 或 `latent_provider`) 决定 `p` / `goal_point` / Φ 的语义 ⇒ **不许顶掉**;
否则 `goal_point` 由轨迹潜空间变成"当前帧自己", Φ 恒 0、∇Φ 恒 0, 看着在跑其实没目标。加一个观测通道:

```python
# manifold_engine.py
def set_x_provider(self, provider, note=""):   # provider: callable() -> dict(ok/z1/z2/z3/z_concat/energy/ms)
    self.x_provider, self.x_note = provider, str(note or "")

def _x_read(self):                            # 在 step() 末尾 rec["x"] = …
    … 分层范数 + 每层能量 + 世界模型残差 …
```

- **世界模型残差才有信息**: `surprise = ‖z_now − 上一帧 z_pred‖ / ‖z_now‖`; 只存单帧前向等于存一个常数。
- **常驻回路里 state 在 attach 时还没到**: `build_engine()` 后立刻 attach ⇒ `state_fn()` 返回 None ⇒
  provider 起不来, 而 attach 只在"源变了"时重入 ⇒ **整段跑完都没有该通道** (日志只有一句接不上)。
  修法两条一起上: `state_fn` 回退到轨迹真源末帧 (真数据, 不拿零填充) + 每周期懒重试 (上限 3 次, 失败明写)。
- 权重/注入系数放 env, **默认 0 (只观测)**: 判据里把 `w` 打出来, 让人一眼看出是"只观测"还是"参与势场";
  `w>0` 会改动作, 属新档位, 必须单独授权过闸。
- 新增 `--encoder <name>` 时 **argparse 的 `choices` 也要加**, 否则报 `invalid choice` —— 看着像功能没实现, 其实只是参数解析。
- 画布节点三档降级, 禁止 `return True` 回显参数: ①引擎在跑 ⇒ 读 `engine_latest*.json` 里那一路真值;
  ②否则自己加载权重跑一次; ③权重/state 缺 ⇒ `return False` + 说明缺什么。

## D. 验收四件套 (顺序固定)

1. **strict 对齐**: 张量数 + 参数量 (结构反推与权重一致的唯一硬证据);
2. **引擎回读**: 隔离实例跑常驻回路 → 读 `engine_latest_<instance>.json` 里那段
   (实测 `ok/z_dim=640/norms/energy/surprise/ms` 齐; CPU 5~16ms/步, 10Hz 回路能扛);
3. **一致性**: 引擎里的 `norms.z1` == 独立前向 `‖z₁‖` (<1e-3) ⇒ 证明引擎吃的是同一次前向, 不是各算一套;
4. **零回归**: 另起一台**干净**引擎不接 provider ⇒ `rec` 里没有该键, `Δφ=0`, `max|Δa|=0`。
另跑原有回归 (`verify_engine_encoder_model.py` / `verify_l4_latent_space.py`) 确认 PCA 与 INTACT 两条路没动。

## E. 坑

- 🔴 **ndarray 真值判断会炸**: `out.get("z_concat") or np.concatenate([...])` 对数组直接
  `ValueError: truth value of an array … is ambiguous`, 还被 try/except 包成「输出解析异常」⇒ 看着像前向失败。
  一律写 `x if x is not None else default`。同一写法曾在验收脚本与引擎 hook 里各踩一次。
- 仓库里"看着相关"的训练脚本可能结构完全不同 (三个同族版本都对不上权重) ⇒ 先比 state_dict,
  别拿不匹配的类硬套, 也别据此说权重坏; 汇报时写「仓库无对应训练脚本, 结构由权重反推」, 边界要露出来。
- 大文件 (`nodes/library.py`、`studio.py`) 里 `grep -rn` 会把成片注释打出来 ⇒ 先 `grep -n` 定位行号再按段读。
