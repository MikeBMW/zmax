# 节点代码 review — 流形链路六节点 (v5.50.736 · 550B 标定/调试档)

老倪 2026-10-16 口径
> 「按照这个原理 (神经网路 ↔ 流形连接: 投影 → 度量 → 导航, 以及四种连接方式), 再次 review
> 流形引擎 / 流形专家 / 接触流形 / 性能流形 / DiT / 加速器 节点的代码, 要在 550B 标定版本,
> 可以 debug, 可以代码单步执行, 我要看到实际的代码编写。」

本次交付 = **代码 review (逐条带源码行号) + 单步调试器**:
- 工具 `tools/node_debug.py` — 六节点真实单步执行器 (每步调的是节点自己在跑的那个函数)
- 判据 `tools/verify_node_debug.py` — **33/33** (结构 / 真源 / 执行 / 档位 / 调试能力 / 诚实性)
- 调试四件套: `--list` · `--node <id> --step` (回车走一步) · `--pdb` (pdb.set_trace 真进源码) ·
  `--src` (打印每个环节的绝对路径+行号, `code -g file:line` 直接断点)

---

## 1. 六节点 → 真实代码位置 (画布薄壳 + 算法真体)

| 画布节点 | 画布名 | 薄壳入口 (library.py) | 算法真体 | 三环节落点 |
|---|---|---|---|---|
| `ss_mani_eng` | 🧮 流形引擎 | `node_ss_mani_eng` **:5227** | `manifold/manifold_engine.py` | 投影 `:691` → 度量 `:748` → 导航 `:738`/`:786` → 反馈 `:763` |
| `ssmani_exp` | 🧠 流形专家 (JEPA) | `node_ss_pred` **:4219** | `manifold/predictor_layer.py` | 投影 `LatentPredictor.forward:67` → 度量 `ManifoldReadout.forward:107` → 导航 `state_space_action_head.py:52` |
| `ssmani_c` | 🧮 接触流形 | `node_ss_mani` **:3957** | `manifold/manifold_layer.py` | 投影 `_error:111` → 度量 `channel_axis:101`+V `:141` → 导航 `decompose:116` |
| `ssmani_p` | 🧮 性能流形 | `node_ss_mani` **:3957** | `manifold/manifold_layer.py` | 投影 `evaluate:184` (δ=头−孔底) → 度量 `Vp:187`/`η:188` → 导航 `∇V_p:189` |
| `ssdec` | 🎯 Flow-Matching Action Head (DiT) | `node_ss_dec` **:4332** | `policies/smolvla_lew/state_space_action_head.py` | 投影 z⁷ (Δ目标‖Δ光模块‖夹爪) → 度量 5 路条件汇总 `:37` → 导航 `forward:52` |
| `ss_ff` | ⚡ 前馈加速器 | `node_ss_s2` **:2364** | `left_right/state_space/parallel.py` | 投影 `forward:143` → 度量 限幅 ±0.6 / `analytic_forward:184` → 导航 快路径语义 |

## 2. 四种连接方式 → 本仓库落地锚点 (判据 A5 核过符号真存在)

| 连接方式 (老倪原文) | 本仓库锚点 | 实测 |
|---|---|---|
| ① 投影到流形 + 沿流形导航 | `ManifoldEngine.project:691` → `Navigator.step:438` → `great_circle_path:430` | 投影后 **‖p‖=1.000000000**; 寻址走测地线 |
| ② 度量张量决定切空间长度/角度 | `MetricCalculator:301` · `tangent_gradient:336` · `M`/度规特征值 | `M=3.643` (在役) · 调试器目标取真源末帧 ⇒ φ=3.53e-4, ‖∇Φ‖=0.0266 |
| ③ 流形是约束流形 (越界=风险) | `ContactManifold.channel_axis:101` → 法向 `e⊥` → `risk` 三档 (`在流形/贴边缘/离流形:135-140`) | 真源帧 200 (自由空间): 进度 0.1250m · 风险 0.0000m · V=7.78e-3 |
| ④ 流形是条件空间 (条件注入 DiT) | 画布真连线 `ssmani_c`/`ssmani_p`/潜空-流形/L4 LoRA/VLM → `ssdec` (`action_head:37`) | 判据 B2/B3 已核: 直连 ‖ 旁路双通道 + ≥3 路并联汇总 |

## 3. review 发现 (全部带源码行号; 3 处已改, 1 处如实记录)

1. **`gradient_flow` 目标未设时静默给 0**（`manifold_engine.py:753-761`）
   原实现: `goal_point is None` ⇒ 势 φ 恒 `0.0`、梯度恒 `0` —— 调用方**分不清「已到目标」与
   「根本没设目标」**，看起来正常其实空转（与老倪「静默降级零容忍 / 未测不许冒充 0」冲突）。
   **已改**（`:759` 起加 `no_goal` 显式标记 + `note` 文案，数值口径不变，向后兼容）。
   佐证: 在役引擎 `engine_latest.json` φ=0.4627 · ‖∇Φ‖=0.962 ⇒ 在役控制台是设了目标的，不受影响。

2. **同一物理量两个键名**：`PerformanceManifold.evaluate` 返回 `Vp`（`manifold_layer.py:197`），
   而文档/消费侧（`verification_layer.py` 兼容取值、`node_func_tree.py:1229` 文案）写 `V_p`
   ⇒ 两套键名容易各取一个各算一套。**已改**：`evaluate` 同时给 `V_p` 别名（同一份数，`Vp` 保留）。

3. **设计文档与代码口径不一致**（`docs/design/zmax_intent_bundle_3layer.md:21`）
   文档写「接触流形势 V=½‖e⊥‖²」，**代码是 `V=½‖e‖²`**（`manifold_layer.py:141`，总误差势；
   自由空间段 `e∥=e`、风险=0，见 `:123-128`）。**已改**为与代码一致并注明行号。

4. **前馈加速器是「解析守卫 + MLP 混路」**（`parallel.py:143`）：真源帧 200 实测
   `n_calls=3 / n_mlp=3 / n_guard=0 · loaded=True`；输出方向与误差方向 **cos=0.9980 (夹角 3.65°)**，
   解析律 cos=1.0000 ⇒ 方向语义正确（FNff05 成立）。
   ⚠️ 注意参考方向必须与 `ContactManifold._error` 同源：自由空间段误差是 **阶段目标−末端**，
   拿「光模块头−孔位」当参考会算出 cos≈0.56 的假偏差（这次踩过一次，已写进判据口径）。

## 4. 单步调试怎么用 (550B 才允许深调试)

```bash
python3 tools/node_debug.py --list                      # 六节点表 (任何档位可用)
python3 tools/node_debug.py --node ss_mani_c --step     # 单步: 回车走一步 (投影→度量→导航)
python3 tools/node_debug.py --node ss_mani_eng --pdb    # 每步前 pdb 断点 (VSCode 可进真实源码)
python3 tools/node_debug.py --node ssdec --src          # 打印每个环节的绝对路径+行号
python3 tools/node_debug.py --all --json reports/node_debug/node_debug_latest.json
ZMAX_DEBUG_BREAK=1 python3 tools/node_debug.py --node ss_ff --trace   # 与画布「右键源码断点」同口径
```

真源(只读): `data/database/zmax/sources/canvas/ss_traj_last.json` (357×43 obs + u_exec_vec) ·
`zmax_data/ss_live/engine_latest.json` · `models/manifold_engine.npz`。
观测通道划分与 `su2.py:253` 注释逐字一致 (`[0:3]手 [3]夹爪 [4:7]光模块 [36:39]孔位`)，判据 B4 核过。

## 5. 六节点单步实测 (真源帧 200 · 2026-10-15 16:58:53 落盘)

| 节点 | 关键实测值 | 不变量 |
|---|---|---|
| 流形引擎 | ‖p‖=1.000000000 · φ=3.53e-4 · ‖∇Φ‖=0.0266 · M=1.0000 | ✅ 投影在单位球 / 度量非零 / 导航有位移 |
| 流形专家 | z_pred 范数 0.0994 · 流形读出 dim=6 · 动作块 4×7 | ✅ 读出 6 维与引擎真值列对齐 |
| 接触流形 | 进度 0.1250m(=decompose 0.1250) · 风险 0.0000m · V=7.78e-3(两处逐位一致) | ✅ 独立重算 == 真函数 |
| 性能流形 | V_p=0.1290(== evaluate) · η=0.0000 · ∇V_p=[0.0848 −0.4813 −0.0917] | ✅ V_p/η/∇ 三项一致 |
| DiT | z⁷ 7 维 · 动作块 28 = 4×7 | ✅ 结构可执行；⚠️ 权重未加载 ⇒ 标「未训练」 |
| 前馈加速器 | ‖u_ff‖=0.1486 · cos(输出,e)=0.9980 · 限幅 0.6 内 | ✅ 方向语义 = 误差方向 |

## 6. 遗留 (如实记录, 不藏)

- DiT / 流形专家 **未加载 ckpt**（随机权重）⇒ 只证结构可执行与条件注入路径；真动作要
  `smolvla_lew` 训练产物落地后再测（工具已如实标「未训练」，不冒充在役）。
- DiT 的 5 路条件值在 `engine_latest.json` 里**没有对应字段** ⇒ 调试器报「未测」而不是 0；
  连线真源已核（判据 B2/B3），条件**数值**要等引擎把条件发布出来才能逐路对照。
- 接触流形 `v`（末端速度）在真源里没有速度通道，调试器用**相邻帧差分**并标注 `v_src`。
