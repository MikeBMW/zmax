---
name: manifold-engine-math-verify
description: "Use when 要自证流形引擎/SU(2)/势场门控的数学真的成立。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [manifold, su2, verify, patent, world-model]
    related_skills: [windows-canvas-node-runtime, state-space-canvas-engineering, manifold-sphere-geometry]
---

# 流形引擎数学内核: 怎么自证它成立

## When to Use
- 要对外/对评审说「这套数学是自洽的」, 需要实测数字而不是论文引用。
- 汇总专利(尤其 003/004/007/010)时, 要给每条技术主张配一条可复现证据。

## 工具 (已落地 `app9/_internal/tools/`)
| 脚本 | 作用 |
|---|---|
| `verify_manifold_math.py` | 13 项断言实测: 群公理/双覆盖/指数映射/Bloch 球/投影残差/门控单调 |
| `hjepa_mr_layers._selftest()` | 作者自带的四层门控自测, 20 项检查 |
| `_smoke_one.py <impl_key>` | 单节点冒烟(流形类节点 key: ss_mani_eng / ss_mani_c / ss_mani_p / ss_pred / ss_lat / ss_grav_h / ss_calib / ss_mem_field / ss_mem_l4) |
| `ss_bench.py` | 全画布一轮耗时 |

## 断言的写法 (每项都必须是可算的判据, 不是描述)
- 群公理: 随机 2000 组算 `‖(ab)c−a(bc)‖` / `|‖U‖−1|` / `‖U·U⁻¹−I‖`, 容差 1e-12。
- 双覆盖: `from_axis_angle(z, 2π)` 必须得到 `−I`(‖U+I‖≈0), `4π` 才得 `+I` —— 能区分"真 SU(2)"与"拿四元数当向量用"。
- 指数映射: `‖exp(log U) − U‖`, 容差 1e-10 (主值分支不该有近似误差)。
- Bloch 球: 任意元素的 `‖r‖−1` 恒为 0 (1e-12)。
- 投影器: `ManifoldProjector(type).project(z)` 返回 `(p, residual, meta)`, 判 `residual` 与 `‖p‖=半径`。
- 门控单调: `l2_gate` 的 gain 随法线偏离单调降并在 6° 归零; `l4_metric` 的 M 随 σ 减小单调升。

## 坑
1. **`l4_metric` 收 dict 不收对象**: `mr` 必须是 `{"ok":True, "d_normal":rad, "d_se3":m, "xi":[6], "log_sigma":[9]}`, 传对象会 `AttributeError: '_MR' object has no attribute 'get'`。
2. **`lerobot.policies.__init__` 会拖一串重依赖** (draccus→typing_inspect→mypy_extensions, huggingface_hub→httpx2, safetensors, einops)。只想用 `su2.py` 也会被拦; 用 `--no-deps` 逐个补很痛苦, 直接 `uv pip install --target _pylibs --python 3.12 huggingface_hub draccus` 让它自解析。
3. **`lerobot/__init__.py` 顶部的 `_pylibs` 注入会被重新部署/同步冲掉** —— 症状是突然 `No module named 'huggingface_hub'`。重新 patch 那 15 行即可(先查 `head -20`)。
4. 实测基线 (2026-11-10, app9): 13/13 通过, 最差 1.5e-15; 9/9 流形节点 0–0.18s; 全画布 65/65, 一轮 29.83s。

## PPT 落地
专利→技术→证据三向对照表是最好用的形态: 每行 = 技术主张 / 权利要求号 / 实测值 / 它保证了什么。
生成器与 deck 同目录 (`docs/1-天枢-产品边界/deliverables/7-流形引擎与世界模型/`), 改脚本重生成, 不手改 pptx。
