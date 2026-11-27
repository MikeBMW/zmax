---
name: zmax-product-eval-baseline-gate
description: Use when 做产品级评估分析/设升级门槛(基线版对比).
---

# Z-MAX 产品级评估分析 (基线产品 → 有提升才准升级)

## 何时用
- 老倪要「系统的评估分析」: 某版本设为**基线产品**, 以后必须评估出**性能提升**才允许升级。
- 要「配置中心所有性能指标科学地与基线对比」, 或要一个有准入门槛的评估功能页。
- 要判某次改动到底算不算「提升」(而不是只看不回退)。

## 三层真源 (改一处即可, 别在页面里算)
| 层 | 文件 | 职责 |
|---|---|---|
| 指标定义 | `config/platform/zmax_perf_spec.json` (A–F 共 58 条: 运动学/视觉/电口/光口/节拍/环境) | 指标名 · 单位 · **目标** · how(怎么测) · std |
| 采集口径 | `tools/eval_probes.py` | 每条指标**怎么量** (只写量法, 不抄指标名/目标) |
| 基线锁 | `config/eval/baseline_v<版本>.json` (**冻结**) | 该版本逐条基线值; 覆盖必须 `--relock "理由"` |

引擎 `tools/eval_analysis.py` 跑采集→判定→报告 `zmax_data/eval/eval_report.json` + 台账 `eval_history.jsonl`;
页面只**读报告**(单一显示口径): `studio.py::EvalModule`。判据 `tools/verify_eval_analysis.py`。

## 证据类必须标出来 (这是评测可信度的全部)
`实测` (真源文件+帧龄) / `标定·配置` (标定真源) / `推导` (写算式) / `设计声明(BOM)` / `未测` (写采集条件)。
- **未测 = value 必须 None**, 绝不用 0 或设计值冒充实测 (0 是「测得为零」, 不是「没测」)。
- **声明≠实测**: BOM/厂商规格/设计要求值一律判 `待现场实测`, 不许记「达标」(否则假达标混进升级结论)。
- **样本不足不判定**: n < 判定所需 (如 3σ 要 ≥30 次) ⇒ 达标列写「样本不足」, 只报值。

## 元任务 ↔ 性能配置 ↔ 物理参数 全链对应 (老倪 2026-10-15)

老倪: 「从任务配置开始, 从每一个元任务开始, 给出完整的元任务配置与性能配置的对应关系, 给出所有性能指标的
物理值验证结果, 每个 L2 的原子技能都要全过程验证一遍, 不留死角, 每个标准状态, 每个原子技能, 每个物理参数,
都要全系统验证。元任务定义/配置, 性能指标定义, 物理值验证结果报告, 完成后发到飞书端」。

**链条与真源 (一处取, 不硬编数字):**

| 环节 | 真源 | 说明 |
|---|---|---|
| 元任务定义/配置 | `tools/export_meta_doc.py::build_meta_tasks()` | 75 条 = 功能(FN-SYSx-N)+参数+依赖+验证方法+层 |
| 任务配置 | `config/tasks/tasks.json` (7 任务) | steps / applies_segments / targets / overrides |
| 任务真跑的段序列 | `zmax_data/task_runs/*/run_summary.json` | judges[].stages + ct_s/dx/dy/dz/yaw |
| 段→技能 | `atomic_skills.py` 类属性 + `SKILL_BY_STAGE` | 别自己编号 (SK07 同号两支: 插入/放入) |
| 物理参数 | `config/calib/zmax_skill_physics.json::stages[段][量]` | `{value,min,max,unit,src}`; 13 段 × 9 量 = 117 |
| 性能指标 | `config/platform/zmax_perf_spec.json` | 58 条 / 6 组 / 目标值 + how + std + links |
| phase 归属 | `config/eval/phase_metric_map.json` (自建真源) | 58/58 映射 + 物理载体; 没写进去的算未映射报红 |
| L2 闸门实测 | `zmax_data/ss_live/skill_phys.json` · `skill_latest.json` | 逐技能实测+包络; 过闸计数 |

**phase 归属口径 (老倪给的关键词, 别自己发明):** Phase 0 反馈速度延迟 (单拍时延/分辨率/整定) ·
Phase 1 对位残差 (一次动作后的残差/重复性) · Phase 2 成功率·节拍 (一件/一批的结果) ·
Phase 3 稳定性 (长期/扰动) · Phase 4 可靠性·准确性 (寿命/故障/ESD/安全/结构余量)。

**物理参数 → 元任务 的双向归属 (这是「每个物理参数都要有对应的元任务」的答案):**
`owner` = 名字含「物理约束 · … SK01-08」的那条元任务 (覆盖全部 117 条); `consumer` = 该段自己的 SKxx 元任务
(只有 8 段有)。5 段 (拔出/AOI转移/AOI检测/回程/放下) 引擎有段但技能库/画布无条目 ⇒ 无 consumer ⇒
**如实登记缺口 + 补齐方案, 不许假装有**。

**取证/交付:**
```bash
./gui-venv311/bin/python tools/meta_perf_matrix.py            # 台账 + 报告
./gui-venv311/bin/python tools/meta_perf_matrix.py --feishu   # 推摘要 (走 tools/feishu_send.py)
./gui-venv311/bin/python tools/verify_meta_perf_matrix.py     # 判据 (不留死角)
```

### 坑
1. **指标 links 大多是业务目标 (BO_*), 不是功能号 (FN_*)**: 58 条里只有 12 条直连 FN。其余要走
   「物理载体段 → 该段元任务」关联, 并在报告里**写明关联方式** (别让人以为是直连)。载体是「全部段」的
   (关节分辨率/MTBF/温湿度) 落到 owner 元任务, 标「全系统级」。
2. **判定五种, 不许混**: 达标/不达标/样本不足/未测/待定。`3σ`/`RP`/`AP` 口径要 ≥30 次样本 ⇒ n=3 只能判
   「样本不足并报值」; 目标值「待定」的**不许判达标**; 未测必须带 `采集条件:` (取自 how)。
3. **飞书发送结果字段是扁平的**: `feishu_send.send_text` 返回 `{ok, code, msg, message_id, http, attempts}`,
   不是 `{data:{message_id}}` —— 判成功要读 `message_id` (否则送达了也报「未送达」)。
4. 报告/台账落 `docs/eval/` 与 `zmax_data/eval/`; **config/ 是符号链接进 data/ (被 gitignore)** ⇒ 自建真源
   (phase map / 基线锁) 不在代码库里, 交付时要说清。

## 判定与准入
1. 阈值达标: 从 target 文本抠 `≤x` / `≥x` 定方向, 出 达标/不达标 + 差距。
2. 基线对比: Δ vs 基线 (0.5% 容差内算持平) ⇒ 提升/持平/回退。
3. **三闸准入** `upgrade_allowed = ①零回退 ∧ ②有净提升 ∧ ③全局一致性零冲突`; 未测/样本不足**不计入净提升**, 单列计数。

## 全局数据一致性 (三链交叉核)
- 指标定义唯一真源 (条数与页面/报告一致)
- 版本一致 (studio / docs_sync / 基线锁同版本)
- L2 包络 == 标定真源 (`config/calib/zmax_skill_physics.json`) 逐条比对

改坏任一条 ⇒ 冲突数 >0 ⇒ 一致性闸不过 (判据里用沙箱篡改验证「改了一定会红」)。

## 现在能实测量的 (真源在手, 别凭感觉)
- 节拍/成功率/对位残差: `zmax_data/task_runs/*/run_summary.json` (judges: ct_s/takt_s/dx_mm/dy_mm/dz_mm/yaw_err_deg)
- 主参数 M: `task_runs/TASK-01-FW/chain_*.jsonl` (度规特征值上下限 ⇒ 条件数, 度规正定)
- 通道/实时性: `zmax_data/dataspace/live.json`
- 物理参数: `zmax_data/ss_live/skill_phys.json` ↔ 标定真源
- 像素当量: `config/calib/zmax_calib.json` 的 fx (`距离/fx`)
- 规格类: `config/platform/zmax_project_bom.json` items[].note (半径/负载/重复精度/行程/ESD/安全等级)

## 坑 (踩过的)
- 通道达标率分母要用**有发布端**的话题 (hz>0); `hz=-1` 的登记话题是「未接生产者」, 不是不达标。
- `--lock` 之后当次必须**重读基线**再判定, 否则首轮报告全是「无基线」。
- 报告/页面别各自算: 页面只读 eval_report.json, 否则出现两个数 (老倪最反这个)。
- 判据自己不许留痕: 跑完基线锁**字节级**不变; 沙箱篡改要立刻复原。
- 语义像 ≠ 同一个量 (L2 `s_step` 是单拍位移上限, 不是插深分辨率; 摆盘 `dz` 不是插拔插深误差) ⇒ 对不上写未测。

## 页面要求 (老倪)
不挤不截断 · 显示内容可复制可导出 (TSV/MD/JSON) · 实时量标帧龄 · 未测显示「—」不显示 0 ·
准入结论大字 + 「为什么不能升级」逐条列出 · 保留既有能力 (训练历史等) 不重写。
