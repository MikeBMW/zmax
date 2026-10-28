# 掩膜 → base 系 3D (引导用) — 链路、门控、取证口径

## 何时用
- 被问"某个分割/开放词汇模型能不能用来做来料位姿识别 / 3D 引导"时。
- 要把 2D 掩膜接成可供下游规划的 base 系目标位姿时。
- 掩膜算出的 3D 位置不对、或 "3D 看起来有了但抓不准" 时。

## 代码路径 (单一真源, 别另写一份)
- 外参/内参/投影全部复用 `tools/scene_overlay.py` (`load_handeye` / `read_tcp` / `load_intrinsics`);
  掩膜→3D 的收口在 `src/lerobot/policies/<seg 模型>/geometry3d.py::mask_3d(mask, cam)`。
- 该模块用 `_scene_overlay()` 惰性 import 共享真源 —— 为避免各写一份投影/手眼/TCP 读法。

## 链路数学
```
valid = isfinite(z) & Z_MIN<z<Z_MAX (0.05~3.0 m)      # 掩膜内有效深度像素
Pc = [(u-cx)/fx*z, (v-cy)/fy*z, z]                     # RealSense 深度 = 沿光轴 z 的反投影
Pb = R_tcp @ (R_x @ Pc + t_x) + t_tcp                  # 手眼 X = 相机→末端; t_tcp = 实时 TCP 真值
中心 = median(Pb); 足印 = minAreaRect(Pb[:, :2]); yaw = 主轴角 (minAreaRect 的宽边方向才是 angle)
```
- `z_mm` 是**相机系**中位深度; **base 系高度**看 `center_base[2]` 与 `z_p20_p80_mm` (两者不是同一个量, 报告别混)。
- 返回还带 `extent_mm`(base 系三轴跨度) 与 `handeye_closed_loop_std_mm` (标定自洽残差, 不是定位精度)。

## 门控 (任一不满足 → `{ok: False, reason}` 原样上抛, 不猜填)
| 门 | 阈值/来源 | 备注 |
|---|---|---|
| 深度源新鲜度 | `ZMAX_DEPTH_DEAD_S` (默认 20s), 读 `depth_meta.json` 的 `t` | 容器未常驻时必触发 |
| 深度文件在位 | `ZMAX_DEPTH_NPY` / `ZMAX_DEPTH_META` | `.npy` + meta 成对 |
| 掩膜内有效深度像素 | `<30` 即拒 | 小目标/遮挡/黑帧必触发 |
| 手眼标定 | `handeye_result.json` 可用 (带闭环残差) | |
| TCP 真值 | 珞石 SDK 采样器落的 latest.json | 全 0 = 会话陈旧, 要重启采样容器 |
| 相机 | 只有腕上深度相机有手眼外参 | 本机/顶摄无外参 ⇒ 直接拒 |

## 实测回执 (真机活帧, 用于回答"能不能用"的硬证据)
腕上 D405 一帧 + 上游给的区域框(非模型自己找) → 单次前向 434ms → 掩膜 3189px / 10 点多边形 →
`center_base=(0.687, 0.029, 0.198) m` · `z_mm=292` · 足印 `58×27 mm` · `yaw=1.8°` · 深度龄 0.1s · 手眼闭环 ±1.74mm。
同帧三个领域文本概念 → **0 实例** (文本提示不可靠的直接证据)。

## 回答"这模型能不能做 X"的三段式 (这个用户的验收口径)
1. **实测回执**: 真帧 + 真数 (帧时间/帧龄/耗时/掩膜px/center_base) —— 不给印象、不给"应该可以"。
2. **能力边界**: 能给 / 给不了 / 必须拒答的条件, 三列写清; 把"模型出掩膜"与"位姿由外链算"分开说。
3. **一句话定位**: 它是掩膜前端 (不是位姿模型、不是找料模型), 以及要变强需要什么 (更大留出集/人工掩膜/更严判据)。
别列选项让用户挑; 直给结论 + 证据。

## 取证图约定 (用户会把画面当结果, 画面必须自证状态)
- 原始帧上叠: 掩膜多边形(黄描边, 与原提示框区分色) + 原提示框。
- 顶部深底(alpha≈190)+白字横幅四行: ①模型口径(默认档/可选档) ②center_base/z/足印/yaw
  ③掩膜px·深度龄·手眼闭环·推理ms ④抓帧时间+帧龄+**提示来源**("上游给的区域框, 非模型自己找料")。
- 中文字体: `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` (PIL `truetype`), 缺失则回退 DejaVu ⇒ 中文豆腐块。
- 一次性可跑: `scripts/probe_mask3d_evidence.py`。

## Pitfalls
- 把 `z_mm` 当 base 系高度报 ⇒ 量纲错一层 (它是相机系沿光轴深度)。
- 拿 `handeye_closed_loop_std_mm` 当定位精度报 ⇒ 那是**自洽**指标 (见技能 `same-source-eval-discipline` 铁律 6)。
- 掩膜分辨率与深度图不一致时必须先 resize 掩膜 (最近邻) 再取深度, 否则索引错位。
- 掩膜包含大片背景 (框给大了) ⇒ 中位深度落到背景上; 深度取掩膜内中位前先看有效像素占比。
