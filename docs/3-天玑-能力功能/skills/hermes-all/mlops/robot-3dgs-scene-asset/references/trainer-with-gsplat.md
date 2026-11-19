# 用 gsplat 自写训练器 (已知位姿数据集 → 3DGS)

## 前提: gsplat 只有库, 没有训练器
`uv pip install gsplat` 装到的是**光栅化库**(`gsplat/` 下有 `cuda/ strategy/ rendering.py exporter.py`, **没有**
`examples/simple_trainer.py`, 也没有 `nerfview`/`imageio`)。要训就二选一:
① 把上游 repo 的 `examples/` 拉下来(依赖多: nerfview/imageio); ② **自写一个紧凑训练器**(本次采用, 好控可控)。
自写所需的部件 gsplat 全都给了: 光栅化 + `strategy.DefaultStrategy`(致密化/剪枝全部逻辑) + `export_splats`。

## 先 introspect 再写代码(版本间 API 会变, 别照旧版记忆写)
```python
import inspect, gsplat
print(inspect.signature(gsplat.rasterization))
from gsplat.strategy import DefaultStrategy
print([n for n in dir(DefaultStrategy) if not n.startswith('_')])
for m in ('initialize_state','step_pre_backward','step_post_backward'):
    print(m, inspect.signature(getattr(DefaultStrategy, m)))
print(inspect.signature(gsplat.export_splats))
```
实测(gsplat 1.5.3)形状:
- `rasterization(means, quats, scales, opacities, colors, viewmats, Ks, width, height, sh_degree=,
  packed=True, near_plane=, backgrounds=)` → `(renders, alphas, info)`; `viewmats` 是 **world→cam**
  (= `inv(T_cam2world)`)。
- `strategy.absgrad` 为真时必须 `info["means2d"].retain_grad()`, 否则反向传播报错/梯度拿不到。
- 调色要用 SH 系数拼(`torch.cat([sh0, shN], dim=1)`, 形状 `[N,(deg+1)^2,3]`), SH 阶取 2 已够(比 3 快且省显存)。
- `export_splats(means, scales, quats, opacities, sh0, shN, format='ply'|'splat', save_to=path)` ——
  **能直接写 `.splat`**: 网页查看器吃这个格式 ⇒ 这是给用户看的最自然交付物(一个 HTML + 一个 .splat)。

## 训练循环骨架(标准 gsplat 模式)
```python
params = torch.nn.ParameterDict({...means/scales(log)/quats/opacities(logit)/sh0/shN...})
lrs = {"means": 1.6e-4*scene_scale, "scales": 5e-3, "quats": 1e-3,
       "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3/20}
opts = {k: torch.optim.Adam([{"params": [params[k]], "lr": v}], betas=(0.9, 0.999)) for k, v in lrs.items()}
strategy = DefaultStrategy(verbose=True); st = strategy.initialize_state(scene_scale=...)
for step in range(1, steps+1):
    out, info = rasterize(one_view)                     # packed=True
    if strategy.absgrad: info["means2d"].retain_grad()
    loss = 0.8*L1(out, gt) + 0.2*(1 - ssim(out, gt))    # 3DGS 原口径
    strategy.step_pre_backward(params, opts, st, step, info)
    loss.backward()
    strategy.step_post_backward(params, opts, st, step, info, packed=True)
    for o in opts.values(): o.step(); o.zero_grad(set_to_none=True)
```
- **场景先归一化**(`x' = S*(x - center)`, `S = 1/max|cam_center - center|`): 上面的学习率是按归一化尺度定的,
  真尺度(米)直接喂会训得极慢。**导出时反归一化回真尺度**: `means' = means/S + center`、`scales' = scales/S`
  (均匀缩放, quats 不变), 并把 `center/S` 一并写进 report —— 仿真侧要的是真实尺度和 base_link 坐标。
- 无稀疏点云(没跑 COLMAP)时的初值: 相机前向 ~0.28m 的**中位视点**为中心, 取一个覆盖面盒
  (如 0.30×0.30×0.20m, 再乘 S), 均匀撒 ~10 万点, scales=1e-2·S, opacity 0.1, 颜色用灰(SH dc)。
  剩余交给 DefaultStrategy 致密化/剪枝。
- 留出视角(~20 张, 每 k 张取一)不参与训练, 用来报 **PSNR** —— 交付数据必须是同口径留出集, 不能只报训练 loss。
- 显卡: 4060 Laptop 8G ⇒ 一次只跑一个模型进程; **操作员正在现场跑臂时不要开训**(GPU 要留给安全层/VLM 慢层)。

## 数据准备上的真坑
- **先把每帧富化成统一结构再切训练/留出**: 数据集里的 frame 字典只有 `T_cam2world`, **没有** `R`;
  训练/评估直接拿原始 frame 用 ⇒ 在 `c["R"]` 上 `KeyError`。富化(`R`,`t`,`T`) 必须**写在切 tr/te 之前**
  (顺序错了就是 `NameError/KeyError` 这种一眼假错, 但也真会白跑一轮)。
- 图像常驻内存用 uint8(`N×640×480×3`), 每步只把当前 batch 搬上卡并 `/255` —— 别一开始就 cvt 成 float 全存。
- SSIM 不想引依赖就自己写(11×11 高斯窗的可分离卷积, ~20 行), 与 3DGS 原版口径一致。
- 先把**相机位姿跨度**量出来(`np.ptp(pos)`): 几十毫米只能出浅浮雕, 几百毫米(本例 291mm / 视差基线 433mm)
  才值得开训 —— 开训前把这个数报给用户, 别默默烧 GPU。
- **数据集声明的 W/H 必须是真实像素, 不是相机档位常量**。相机换分辨率(如 640×480 → 1280×720)而 `cameras.json`
  仍写 640 ⇒ 训练日志 `RuntimeError: The size of tensor a (640) must match the size of tensor b (1280)`,
  每轮必崩; 而站点页照样能打开(它挂的是上一版旧资产), 于是用户只看到"3DGS 一直没改进"。
  实测这种静默崩跑了 26 小时零产出, 唯一线索是 `last_train_ts` 停在上一天、`n_rounds` 不再增长 ——
  **判"训练有没有真跑"看 `last_train_ts`/`error`, 不看页面上有没有图**。
  硬闸两处: ① 采集端写 `cameras.json` 用**会话真实帧尺寸**(帧记录里往往没有 w/h 字段, 兜底写死 640 就是坑,
  要用 `sess["w"]/["h"]` 或直接量图片); ② 训练端入口先量第一张图实际尺寸, 与 `cameras.json` 不符就按图重算,
  并打印一行结论(不要静默改正, 否则下次又不知道差在哪)。
- **K 不能靠缩放凑分辨率**。635 档的内参乘 `(W'/W, H'/H)` 当新分辨率用是错的口径(不同档位的视场/裁剪方式不同,
  各轴缩放系数也不一样), 实测这样训出来留出 PSNR 从 17.74 掉到 10.44 —— 比改之前还差。
  要么取该分辨率的真实 `camera_info`, 要么把相机调回已验证的那一档(顺便训练便宜 4 倍)。
- **PSNR 只在同口径下可比**: 换分辨率、换留出集、换步数之后, 旧 PSNR 就不再是对照基线。
  要报"改进了"必须三同: 同分辨率 + 同留出集 + 同步数, 否则先报数再解释。
- **采集侧先查位姿新鲜度**: 桥自报 `pose_age_s` 几百秒而 `ros2 topic hz <pose_topic>` 还有 48Hz,
  说明订阅哑了(重启桥, 或加"超 5s 不更新就读本机 latest.json"的兜底)。此时采下来的帧全是同一个陈旧位姿,
  训了也是错几何。

## 本次实测产物(可作交付形状参考)
`~/zmax_data/gs_assets/<会话>/`: `images/`(300) + `cameras.json` + `transforms.json` + `meta.json`
→ 训练后 `gs.ply`(真尺度) · `gs.splat`(网页查看器) · `renders/holdout_XX[_gt].png` ·
`train_report.json`(步数/高斯数/留出 PSNR/耗时/归一化 center+S)。
给用户的交付形态: 把 `.splat` + 一个静态查看器页挂到站点, 发链接 —— 手机/桌面都能拖转看场景。
