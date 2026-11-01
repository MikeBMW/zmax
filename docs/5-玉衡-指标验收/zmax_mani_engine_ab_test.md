# 流形引擎节点有效性 · A/B 对照（2026-10-30）

## 设计

同 probe、同输入、同单线程，只切一个变量：

- open：`ZMAX_MANI_ENG_OFF=0` → /tmp/mani_open.json（07:00:17）
- closed：`ZMAX_MANI_ENG_OFF=1` → /tmp/mani_closed.json（07:00:55）

工具：`tools/mani_ab_compare.py`

## 结果

① 开关生效：`实现执行 34.6ms` → `直通 21.9ms`

③ 直接下游 `ssmani_c`：9 项可比数值，**有差异 0 项**（逐项相同）

④ 动作头 `ssdec`：`l4_cond_injected` open=False / closed=False 相同；`degraded` 相同；`nominal_src` 相同

⑤ 执行侧：单跑无上游上下文，`u_sat` 两侧均 0（不构成证据）

## 结论

- **计算层有效**：流形引擎每帧真跑 34.6ms，投影/度量/测地线/反馈都执行，几何量正常
- **因果层无效**：开关对直接下游 `ssmani_c` 零影响，`l4_cond_injected=False` 说明动作头不消费 L4 条件
- 因此**不能宣称流形引擎影响了动作**。它现在是"每帧真算、但不进控制链"

`nominal_L3` 两组数值不同（-0.0848 vs 0.0465），但这是 L3 模型两次独立采样的噪声，**不能归因于流形开关**——③零差异已经排除了这条通路。

## 修法

不是调参，是打通传导：

1. 重训 L3 动作头，把 192 维 `l4_cond` 作为真输入通道（当前 ckpt 未训该通道）
2. 训练后同口径复测：`l4_cond_injected=True` 且 `nominal_L3` 随条件变化
3. 再跑本 A/B，期望 ③ 出现非零差异

在此之前，对外口径只能说"流形引擎计算有效"，不说"提升 300UPH 靠流形"。
