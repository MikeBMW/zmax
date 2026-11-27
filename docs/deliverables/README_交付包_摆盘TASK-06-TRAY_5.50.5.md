# Z-MAX 交付文档包 · 摆盘 TASK-06-TRAY · v5.50.5

- 工程根: `/home/ubuntu/zmax`  ·  版本: **v5.50.5**(= 开发工程同版本, 取自 `tools/gui/update_checker.py::CURRENT_VERSION`, 不手写)
- 任务: TASK-06-TRAY 光模块摆盘(周转盘 → 上料 Tray 盘)  ·  场景: SCN-06-TRAY(摆盘, 蓝 #1f6feb)
- 交付分工: **供应商** = 摆盘作业具身模型(L3 取放循环/序列规划/多型号配方/异常处置); **我方** = 工程集成与收口(L2 执行链/几何真值/安全红线)
- 生成日期: 2026-10-13

## 包内文件(8 件)

| # | 文件 | 说明 |
|---|---|---|
| 1 | `供应商SOR_摆盘_TASK-06-TRAY_5.50.5_20261013.docx` | 供应商外发 SOR(Word · 15 章 + 附录 A–J) |
| 2 | `供应商SOR_摆盘_TASK-06-TRAY_5.50.5_20261013.md` | 同上 Markdown(由导出器**同源渲染**, 非手写第二份) |
| 3 | `供应商SOR_摆盘_TASK-06-TRAY_5.50.5_20261013.json` | 结构化导出(逐章/逐表, 供系统对接) |
| 4 | `供应商SOR_摆盘_TASK-06-TRAY_5.50.5_20261013.manifest.json` | 导出清单与指纹 |
| 5 | `全系统配置清单_5.50.5.md` | 全系统总配置表(11 章, 从在役系统扫描生成) |
| 6 | `全系统配置清单_5.50.5.json` | 同上 JSON |
| 7 | `摆盘性能对账_5.50.5.md` | **性能指标对账 + 主参数 M 映射与落役对账**(现取现算) |
| 8 | `摆盘性能对账_5.50.5.json` | 同上 JSON(附数据来源 sha256 指纹) |

本包新增(SOR 附录 H/I/J): 性能指标对账表 / 单颗节拍分解 / 配置项→节拍可达性(代码级证据) / 达标路径 / 主参数 M 定义·映射(R1–R5)·测量与验收 / 验收试验设计(样本量与红线口径)。

## 已经证明的(有实测证据)

- **取放精度**: 单边最大 0.597 mm(目标 ≤1 mm)、姿态偏差最大 0.042°(目标 ≤1°)——3 颗全过。
- **功能链**: 摆盘 3 颗连续取放完成, 逐颗判据落盘; 摆盘场景末端工具判定 = **真空吸盘**(非夹爪), 判据 `verify_tray_vacuum.py` 全过。
- **驱动扭矩话题**(流形引擎输出 `ss_torque` = M·(−∇Φ)): 判据 **30 项 / 29 通过 / 1 未过**, 未过项为真录像依赖(办公模式无相机源, 与扭矩链无关); 10 Hz 常驻, 场景标签与活跃场景一致(SCN-06-TRAY)。
- **数据空间发现层**: 修复前 10/10 话题黑灯(单播配置缺失 + 常驻 IP 变化 ⇒ 本机自己都收不到); 修复后 hw_state / heartbeat / ss_diag / ss_torque 为绿(真数据 9.6~19.8 Hz)。

## 未达标 / 未验证(如实列明, 未柔化)

- **单颗节拍**: 实测 10.637 / 11.550 / 11.625 s, 目标 ≤3.15 s(硬上限 3.5 s)⇒ **未达标(约 3.4~3.7×)**。
  根因(代码级): L5 速度指令闸 `speed_scale = max(1.0, min(1.5, takt/est))`, `est=11.0` 为源码硬编码,
  takt 3.15 s ≤ est ⇒ 恒返回 1.0, **无论怎么改节拍配置都不可能达标**; 且上限 1.5× < 需要的 3.38×。
- **成功率 ≥99%**: 现有 3/3(单 seed)**不构成 99% 的证据**; 按统计口径需 **≥299 颗连续 0 失效**(95% 置信下限)。
- **真空建立**: 实测 425 / 537.5 / 525 ms vs 配置上限 200 ms ⇒ **3 颗全部不合格**。
- **真空保持**: 实测 5.49 s vs 配置 5.0 s(超 9.7%), 直接吃掉节拍余量。
- **连续盘数 ≥12 盘**: 未测。
- **主参数 M 落役**: 配置单按 R1–R5 算得 **M=4.423(dim 6 / isotropic)**, 在役真源为 **M=3.283(dim 3 / full)**
  ⇒ **不一致 = 摆盘配置单尚未落到在役主参数**(映射链与节点判据 23/23 已在, 差的是写盘与作业链消费)。
- **数据空间部分话题**: `ss_state / ss_action / ss_link_value / ss_plan / ss_energy` 仍为黑(办公模式无机器人/状态空间引擎未跑, 无发布者);
  `ss_calib` 灯红 = 设计速率 0.2 Hz 与实测 19.84 Hz 相差约 99×(发布端每 tick 重发, 缺速率闸)。

## 复核命令(逐条可跑)

```bash
# 性能对账(含主参数 M / 节拍分解 / 判定) —— 数字全部现取现算
python3 tools/delivery/gen_tray_perf_report.py --ver 5.50.5

# 摆盘场景末端工具 = 真空吸盘(非夹爪)
gui-venv311/bin/python tools/verify_tray_vacuum.py

# 驱动扭矩话题端到端(定义式复算 + DDS 真订阅 + 时效性)
gui-venv311/bin/python tools/verify_driving_torque_topic.py    # → reports/driving_torque_judge.json

# 数据空间话题灯与字段
python3 -c "import json;d=json.load(open('zmax_data/dataspace/live.json'));print(d['lamp_tally']);print(d['topics']['ss_torque'])"

# 主参数 M: 配置单映射 vs 在役真源
python3 tools/config_to_M.py --task TASK-06-TRAY
python3 tools/verify_metric_main_param.py

# 重新导出本文档(改配置后必须重导)
gui-venv311/bin/python tools/sor_export.py --project PROJ-TH-TRAY --task TASK-06-TRAY --json
python3 tools/delivery/gen_config_inventory.py --ver 5.50.5
python3 tools/ss_task_bind.py --check && python3 tools/engineering_db.py check
```

## 口径说明(本包不做什么)

- 不使用"白盒交付"表述; 对外统一为「符合 5 个场景的具身方案技术协议」。
- 文档内所有数字由工具从真源现取现算; 未标定项一律标「待实测」, 不用概念值充数。
- 性能数字**不手写**: 附录 H/I/J 的内容来自 `摆盘性能对账_5.50.5.json`(同一份生成器输出)。
