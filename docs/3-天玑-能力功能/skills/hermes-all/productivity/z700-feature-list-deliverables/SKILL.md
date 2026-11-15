---
name: z700-feature-list-deliverables
description: Use when 出 Z700 功能清单与解决方案套件 (Excel·Word·PPT).
---

# Z700 功能清单与解决方案交付套件

产出四份+一份：Excel 功能清单、Word 解决方案、Word 立项、Word 竞品、PPT。全部由 Python 数据模块驱动，数字从实测文件读，不手填。

## 代码位置（可复用）

```
tools/z700/z700_metrics.py          性能指标+负载计算 → outputs/z700/metrics.json
tools/z700/z700_features.py         165 条功能(七阵) — 纯数据, 唯一真源
tools/z700/z700_xlsx.py             17 工作表 Excel
tools/z700/z700_docx.py             Doc 类(封面/H1-3/TABLE/NOTE/页码)
tools/z700/z700_build_solution.py   解决方案 18 章
tools/z700/z700_build_project.py    立项报告
tools/z700/z700_build_competitor.py 竞品(读 competitor_data.json)
tools/z700/z700_build_pptx.py       27 页汇报
```

跑法：`z700_metrics.py` → `z700_build_competitor.py`（顺带生成 standards_rows.json）→ 再跑 xlsx/solution/project/pptx。

## 七阵结构（配置中心）

天枢 PB-产品边界 / 天璇 OP-作业任务 / 天玑 CF-能力功能 / 天权 MA-模型算法 / 玉衡 IX-指标验收 / 开阳 EN-工程落地 / 瑶光 RC-记录追溯。

每条功能 12 字段：id/阵/层/名称/描述/判据/EVT/DVT/PVT/国标/证据来源/优先级。

## 三阶段判据口径

- **EVT**：能演出来。写成「已实现 · 演示 X 次」，环境是 ar3d 场景 + 真机，游标要跟得上。
- **DVT**：在哪都能做。七类扰动（温/湿/电源/振动/ESD/洁净/光照）+ 标定参数固化。
- **PVT**：能一直做下去。72h/≥5000 次、换型 ≤0.5h、MES/AOI 联动、异常自恢复。

## 坑（都踩过）

1. **中文引号必须用「」**。在 Python 字符串里写 ASCII `"中文"` 会截断字符串报 `invalid character '（'`。写完跑 `ast.parse` 复核；用正则 `[\u4e00-\u9fff]"[\u4e00-\u9fff]` 定位，但收尾引号前后是空格/标点的会误判，必须逐条看。
2. **`outputs` 是软链** 指向 `external/lerobot-smolvla-lew/outputs`，write_file 报解析后路径属正常。
3. **插入力必须分档**：SFP ≤18N / QSFP ≤60N / QSFP-DD ≤90N（SFF-8432 / SFF-8661 / TE 108-60122）。写「插入力 ≤40N」覆盖不了 QSFP-DD，会被客户按标准上限挑错。「≤2N」是接触阈值，不是插拔力。
4. **标准号三个雷**：GB 5226.1-2019 已由强制转推荐性 **GB/T**；GB/T 16855.1 引 **2025 版**（2018 版已废止，改名《机械安全 安全控制系统》）；GB/T 20868 引 **2024 版**。GB/T 12645 与 GB/T 32304（航天）不适用，别引。
5. **ISO/TS 15066 附录 A** 是「人机接触」安全力阈值，不是工艺插入力。分表列出，禁止用插拔力证明符合附录 A。
6. **Z700 是自家产品代号**（甲方苏州智蜂创元已对外披露），竞品表里不能列 Z700，只作对标基准。
7. **节拍两套口径不可混算**：录制真值 0.199s/点（42.85s/轮·84UPH）vs 实跑逐点 2.028s/点（436s/轮·8.3UPH）。逐点每点 ~0.33s 固定开销是根因。

## 负载口径

可用负载 = 额定 5000g − 末端 1500g = **3500g**。单颗 15–200g（5.7%）；吸塑满盘 1.88–2.46kg（53.7–70.3%，可搬）；金属满盘 2.99kg（85.4%，临界）；整箱 8.92kg（254.9%，必须 AMR）。负载不是瓶颈，真约束是夹持力 0.1N 分辨率与末端惯量对节拍的影响。

## L2~L5 联合训练（tools/joint_train_all.py）

```bash
./gui-venv311/bin/python tools/joint_train_all.py --only L4,L3,L2,L5,LLM --steps 200
```

四个坑：

1. **L3 必 OOM（8G 卡）**。SmolVLA 配的是 7 帧视频窗（`num_video_frames=n_obs_steps=7`，需重训 pos_embedding），batch=4 要 6.12G、再申请 426MB 就炸。**必须 `--l3-batch 1`**，实测显存 5.18G、1.22s/step、200 步 4 分钟。
2. **L2 的 live eval 可能是废的**。`yolo_live_eval` 会从相机现采 40 帧、只留 13 帧，若臂停在远处/画面无目标，13 帧 mean/std 完全相同（首末帧差 mean≈2.3）——此时 新/在役 都是 0/13，判定“持平/回退”但其实根本没测到东西。**先看帧的 std 和帧数多样性；>1 个灰度级才算合格评测集**，否则重采（臂开到抓取位、目标在视野内、至少 3 个位姿）。
3. **L5 LoRA 常比基座差**。n=12 时合法率 0.833→0.500。样本 <20 不得下结论，更不得进默认档。
4. **交付门槛**：有提升非仅不回退。L2/L5 无同口径提升证据就不上默认档，即使 rc=0、loss 在降。

## 投递飞书

```bash
./gui-venv311/bin/python tools/feishu_send_file.py --text-file outputs/z700/feishu_text.txt <files...>
./gui-venv311/bin/python tools/feishu_check_messages.py --n 8   # 回读核验, 不信发送返回值
```

`--text-file` 避免多行中文被 shell 转义破坏；发完必须从服务端读回确认。
