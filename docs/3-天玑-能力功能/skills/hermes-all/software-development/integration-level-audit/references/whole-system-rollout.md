# 节点逐个替换 · 串行推理 · 三机就绪 (交付清单)

用户口径：「所有模型要真正运行，保证 AR 300UPH，一个节点一个节点替换；达不到 300UPH 可以不接入，
但代码要跑通、训练要有 pipeline；算力不够要串行推理；550B 代码通、550A 训练通、550C 部署通打 MAC。」

## 1. 节点逐个替换: 三分类 + 预算

| 判据 | 怎么量 | 不满足时 |
|---|---|---|
| 能跑通 | 模块 import + `compute(ctx)` 不抛异常 | 待补 (记异常原文) |
| 真发值 | 端口 `value` 非空 (`None`/`{}`/`[]` 不算) | 待补 (记"缺真帧/力/权重") |
| 吃得住拍子 | 单次 ms ≤ `ZMAX_TICK_BUDGET_MS` (默认 60) | 转串行推理队列 |

参考量级 (10Hz 循环里实测的单次耗时，都超预算、都不该进拍子):
意图解码 9.0s · 技能库 4.0s · 特征验证 4.1s · L4 记忆 3.7s · YOLO 2.1s · Web 桥 2.1s · HIL 1.7s ·
势场 0.97s · SAM3 0.58s · AOI 0.51s · 元任务 0.20s。

两条容易做错的:
- 候选清单**写画布节点 id**（`ssdec` / `ssyolo` / `ss_seg` / `ssaoi` / `ss_mem_l4` / `n_intent_direct` /
  `ss_mem_field` / `n_l2_muscle`），写模块名（`n_decoder` / `n_yolo`）会得到一排"无实现"的假结论。
- 判完要把结果落成三张名单（接入 / 串行 / 待补）并写进交付报告；只说"都接入了"或"都不行"都是错的。

## 2. 串行推理队列 (显存/算力不够)

- 一个进程、严格串行：上一个 `compute()` 返回后才进下一个；不许并发（显存打满会让耗时跳变/超时）。
- 每轮记录：每模型 ms、是否真发值、错误原文、本轮合计；落盘 `zmax_data/ss_live/serial_inference.json`，
  带 `round` 计数 —— 判活看这个文件的 `round` 增长与 mtime 龄，不看进程是否在。
- 与 10Hz 循环解耦：验收时同时报"队列一轮 X s"与"循环仍 Y ms/拍"，两条都要有数字。
- 常驻起法：`setsid nohup <venv>/bin/python tools/serial_inference.py --loop 30 >> /tmp/serial.log 2>&1`，
  起完隔 60s 回读 `round` 与龄。

## 3. 三机就绪 (代码 / 训练 / 部署打 MAC)

三项都**真跑**，不写"应该没问题"：

```
代码通   py_compile 全仓 .py (报总数与失败数+首个错误) · 核心模块 import · 跑验收脚本取 PASS/FAIL (正则解析)
训练通   训练入口 --help 退出码 · 数据与配置存在性 · torch CUDA 设备名/版本 · (可选) 1 步真训
部署通   git sha · 版本号 · 交付件 sha256 · 各网卡 MAC ⇒ 清单 JSON (可直接贴给现场)
```

- 版本号/参数真源在 `config/platform/*.json`，别从 PPT 或对话里抄。
- MAC 取 `/sys/class/net/<nic>/address`，跳过 `lo`；容器网卡（docker0）也列上并标注用途。
- 交付件 hash 用 `sha256` 前 16 位 + 文件大小，两边对账时按 path 比 hash 而不是行数。
- 可复用入口 `tools/three_host_readiness.py`，输出 `zmax_data/ss_live/three_host_readiness.json`。

## 4. 边界与汇报

以上全部只走读取与计算：不调授权接口、不碰下发守护、不动真机。报告末尾必须写一句
「真机这条线没动，下发需授权」—— 不要把仿真/链路结论当成真机证据。
