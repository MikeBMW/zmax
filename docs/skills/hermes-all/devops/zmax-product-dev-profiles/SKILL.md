---
name: zmax-product-dev-profiles
description: "Use when 改/查 550A/550B/550C 产品档位或产品开关。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [zmax, product, profiles, 550A, 550B, 550C, topics, shm, vscode]
    related_skills: [zmax-console, state-space-canvas-engineering, dds-messaging]
---

# Z-MAX 三产品开发分工 (550A / 550B / 550C)

## When to Use
- 用户提到 550A/550B/550C 的差异、产品档位、要在某档开关某功能。
- 要新增一个“只对某档生效”的能力 (话题 / 通讯 / 界面 / 算法准入)。
- 现场报“某个功能在产线上不该开”“为什么这台机器不发 topic”。

## 老倪 2026-10-15 定的分工 (原话口径, 不改写)
| 档 | 定位 | 关键开关 |
|---|---|---|
| **550A** | 开发版: 新技能 / 新算法 / 逻辑最多 (允许不稳) | `new_algorithms=on` · `logic_depth=max` · topics=core |
| **550B** | 调试版: 所有 TOPIC 全开 + 最大化 debug + 允许 VSCode 联调 | `topics=all` · `vscode_debug=true` · 信号分析/3D 全开 |
| **550C** | 量产版: 稳定性优先 | 未验证算法**全关**(只放 `verified_algorithms`) · `comm=shm`(**不发序列化 topic**, 共享内存直传) · 信号分析**不开** · 3D 场景**不开** · 只留**远程旁路**(远程运行 + 真机部署) · vscode_debug=false |

## 真源 / 读取口 / 判据 (改任何一条都动这三处)
```
真源   config/platform/zmax_product.json → products[<档>].dev_profile   (人可编·进 git)
读取口 tools/zmax_profile.py  → topics_mode() / comm_mode() / gui_on('signal_analysis'|'scene_3d')
                               / vscode_ok() / remote_bypass_ok() / algo_policy() / algo_allowed(name)
                               / dds_topics_allowed(topics) / summary(档)
判据   tools/verify_product_dev_profiles.py (①真源逐条对上老倪原话 ②读取口三档取值 ③**四处真接线** ④子进程实测)
```
`ZMAX_PRODUCT=550C` 环境变量可**覆盖**当前档做验证 (不碰真源、不动现场)。

## 已接线的四处 (加了新开关就在这里接)
| 开关 | 接在哪 | 行为 |
|---|---|---|
| 信号分析开合 | `tools/gui/studio.py` MonitorModule 建 tab 处 | C 档不建波形页, 给一行说明 + 指向共享内存目录 |
| 3D 场景开合 | `tools/gui/simulink_module.py::open_ss_3d` | C 档拒绝并说明 (不静默) |
| VSCode 联调 | `tools/gui/simulink_module.py::open_in_vscode` | 只有调试档放行 |
| DDS 序列化话题 | `tools/dds/ss_daemon.py::allowed()` | 档位**只能收窄**运行模式的集合: C 档全拒 (走共享内存), A 档核心集, B 档全开 |

## 铁律 (踩过的坑)
1. **档位只能收窄, 不能放宽**: `allowed()` 先按运行模式判, 再用产品档收一道。反过来会把现场能力悄悄放开。
2. **配置写了没人读 = 假接线**: 每加一个开关, 必须落一处**真调用点**并在判据③里 grep 钉住。
3. **读取失败一律按“全开”兜底**, 但**必须打印一行** (不许静默变成“打不开”)。
4. **C 档“未验证算法全关”要有 `verified_algorithms` 名单才站得住**: 名单是老倪签字的地方, 不许自己往里加。
5. **共享内存不是新东西**: 引擎已在写 `/dev/shm/zmax_ss_engine/engine_default.jsonl`; C 档只是关掉 DDS、让信号走这条路。
6. **不要为了让某个档“干净”去删别的档的能力**: 三档是同一套代码的三种配置, 差异只在 `dev_profile`。

## 验收命令
```bash
./gui-venv311/bin/python tools/gen_dev_profiles.py             # 重新写 dev_profile (改完真源后)
./gui-venv311/bin/python tools/verify_product_dev_profiles.py  # 判据 (含子进程实测)
./gui-venv311/bin/python tools/zmax_profile.py 550C           # 一行摘要看某档现在是什么
```
