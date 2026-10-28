# 力 / 合力 / 四元数 的逐字段唯一依据 (太阳系 + 万有引力表)

一句话结论：屏幕上那四层「力」**不是**“模型张量 → 流形主参数 → 驱动力矩/四元数”算出来的。
它们是**速度指令的矢量(m/s)**：L4 在 ▶ 运行且勾了模型执行时才是真模型输出，L3/L2 是限幅/融合后的速度，
L5 是回放值或构造量；四元数是**显示编码**；力矩那条支路默认断开。

## 逐字段唯一依据表

| 界面元素 | 唯一依据 | 单位 | 性质 |
|---|---|---|---|
| 表的 L4 列 / 合力箭头的主力分量 | `trace_live.json` 的 `前馈速度_*`(← `u_ff_vec`) | m/s | 实时模型输出(前馈 MLP forward)，否则回放数组 |
| L3 列 | `u_limit_vec`(`安全边界_*`) | m/s | 限幅后的速度 |
| L2 列 | `u_fuse_vec`(`动作调制_*`) | m/s | 融合后实际执行速度 |
| L5 列 | `prior_vec` / 规划方向×\|u_ff\| | m/s | **回放**(最近一集) 或**构造量**(意图只给方向, 不给力度) |
| 表的 q | `vec_to_quat(v, u_ref)` = (\|F\|/u_ref, Fx/u_ref, Fy/u_ref, Fz/u_ref) | — | **显示编码**，可逐位相加，故意不归一 |
| 太阳系 q̂ / 箭头长度 | 同上归一；`L = arrow_max_px·√(\|F\|/arrow_ref_mps)` | — / px | 显示口径；绝对尺度 ⇒ 同一 \|F\| 永远同长 |
| 表“本刻主力” | `config/calib/force_field.json: u_ff_gain` (α>1 ⇒ L4) | — | 显示口径，不动控制回路 |
| 驱动扭矩 τ | `tools/tdrive_bus.py::compute()`: τ = M·(−∇Φ + α·u_ff) | N·m | `apply_to_tau=false` 时 α·u_ff 项**不生效** |
| 主参数 M | `engine_latest.metric_M` / `torque_live.metric_M` ← `config/calib/zmax_manifold.json` | — | **标定标量**，不参与这些力的换算 |
| 姿态(a/b/c) | `tcp_out/latest.json` 的 rx/ry/rz | — | 唯一依据目前为 None ⇒ 写“未建模”，不伪造 |

## 三个“看起来像，但实际不是”

1. **q 不是单位四元数**：平方和 = 2(\|F\|/u_ref)²，设计目的是让 `q(合力) = Σ q_i` 与矢量相加逐位对得上账；
   屏上 q̂ 才是归一的，模恒为 1 ⇒ 只能承载方向，**不能编码强度**(强度看数字/箭头长度)。
2. **M 不参与“力 → 四元数”的换算**：M 只出现在 τ 公式里；这些力是速度矢量，没有乘质量/度量。
   “模型张量 → 主流形参数 → 力矩”这条链目前只有“模型 → 速度指令 → 显示”是真的。
3. **档位 L2 时 L3/L4/L5 不该有值**：未启用层必须清空并写“未调用(档位 Lx)”；
   出现数值即说明读的是回放数组(档位门控见 zmax-console 的 `force-field-visualization.md`)。

## 自查命令

```bash
# 力场构造开关：α 与“是否进 τ”
python3 -c "import json;d=json.load(open('config/calib/force_field.json'));print(d['u_ff_gain'], d['apply_to_tau'])"
# 本帧速度唯一依据（键名是 _mms，消费端要 /1000）
python3 -c "import json;d=json.load(open('zmax_data/ss_live/trace_live.json'));print({k:v for k,v in d.items() if '前馈' in k or '帧' in k or '时间' in k})"
# 这一帧是本轮实时还是旧回放：看 帧/时间_s 有没有随 ▶ 推进，以及文件 mtime
stat -c '%y %n' zmax_data/ss_live/trace_live.json reports/ss_episode_latest.npz
```

判“本轮实时”的唯一硬证据是 `帧` / `时间_s` 在跟着 ▶ 往前走；文件新鲜但帧号不动 = 唯一写入方(3D 面板/控制台 tick)
没在跑，界面上剩的是旧值。

## 回答口径（老倪会追问“实际怎么执行的”）

按这三段报，不要合成一句“模型算的”：
1. **哪一段是真模型**：前馈 MLP 每步 forward 的证据(`🧠 前馈加速器: MLP 真身执行 #N`, `SS_USE_MLP=1`)；
   没开/没进 forward 就是解析式或回放，如实说。
2. **哪一段是回放/构造**：L5 列、位姿、阶段名，标出帧龄。
3. **哪一段压根没接通**：τ 的 α·u_ff 项(`apply_to_tau`)、姿态四元数(无唯一依据)、流形主参数(不在这条链上)。
