# 控制台各页面的真值源 (查「这格数据从哪来」先看这张表)

原则：页面上任何一格数都应有唯一真源；找不到真源就该写「未接入 + 原因」，不写占位。

## 版本与基线

| 项 | 真源 |
|---|---|
| 当前版本 | `VERSION.md` 表首 `\| **vX.Y.Z** \|`（与 `tools/gui/update_checker.CURRENT_VERSION` 同源） |
| 基线产品 | 独立常量 `v5.50.735`（`tools/eval_analysis.py` 的 `BASELINE_VERSION`）+ `config/eval/baseline_v5_50_735.json` |

- 报告 / 表头 / 功能卡文案一律从上面派生。写死 `VERSION = "vX.Y.Z"` ⇒ 升版后报告自称旧版。
- 拿当前版本拼基线文件名 ⇒ 文件不存在时 `base_version` 退化成当前版，页面显示「基线=当前」而不报错。

## 评估分析页

- `zmax_data/eval/eval_report.json`：`version_current` / `version_baseline` / `n_metrics` /
  `n_measured` / `n_untested` / `verdicts` / `gate{upgrade_allowed,conditions,reasons}` / `metrics[]`
- `zmax_data/eval/iteration_roadmap.json`：`meta{version, baseline, ts_str, n_phases, n_metrics}`
- 生成器：`tools/eval_analysis.py`、`tools/iteration_roadmap.py`。重跑这两个才能刷新「当前」列。

## 实时监控页 / 硬件页

**8793 `/station/status` 是硬件真值聚合**（与工位总览页同一个源）：

| 字段 | 内容 |
|---|---|
| `ctl.robot` | `ok / power / operation / estop / collision / src / age_s`（`src=topic_cache(...)` 且 `age_s` 很大 = 陈旧，要显示「状态陈旧」而不是 ✅） |
| `ctl.tcp` | `xyz`(米) / `abc_deg` / `quat` / `age_s` / `stale` / `err` / `src_file`（位姿真值文件 `zmax_data/rokae_sdk/tcp_out/latest.json`） |
| `ctl.motion` | `ok / skill / age_s` |
| `ctl.auth` | `armed / mode / window_s` |
| `stats.<cam>` | `online / fps / age_s / stalled / label / src_err`，相机键：`arm` `local` `local2` `depth` `aoi_gold` `aoi_surface` |
| `aoi` | `10082` / `10083`：`ok / err / t / url` |

- 相机流单独端点 `8791 /stats`，结构同上六个键（带 `src_url` 与 `src_err`）。
- 监控页顶部「远程监控·同源」的端点清单在 `tools/remote_monitor_aggregate.py` 的 `_build_catalog()`：
  默认只探本机 6 项 + Orin 8792 + AOI 10082/10083（共 10 项）；ECS 那 8 条定义保留但默认不探
  （云端已下线，`/etc/hosts` 把 `datadrive.world` 指到 127.0.0.1），要恢复用 `--with-ecs` 或 `ZMAX_MONITOR_ECS=1`。
- 塔灯只有下发通道 `/tower_light/command`（Orin ROS domain 23），没有状态回读 ⇒ 面板写「无硬件反馈通道」，
  点完按钮把回执记在自己的字段里，不要让 1s 定时渲染把它覆盖。

## 系统架构页

- 顶部实时条读 `tools/arch_graph.py --json`（platform → product → subsystem → 功能(配置/标定/诊断) → 模块库）。
- 下面的 L2/L3/L4 阶梯卡是**产品定义**（不是数据），别把它当假数据去改。

## 全局数据空间页

- `tools/gui/data_space.py` 的 `GlobalDataSpace.scan()` 全扫磁盘：`reports/train_curve_*.json` ·
  `outputs/train/*` · `reports/rollout_*` · `reports/*.pdf` · `reports/*对比*.mp4` · 数据集目录 · 模块库节点。
- 它是实扫，条目少只说明盘上产物少，不代表链坏。

## 模型引擎页

- 清单：`tools/model_inventory.py --json` 的 `all_models`（枚举全部权重，带 `kind/active/size_h/mtime/train_cmd`）。
- 动作：`tools/model_engine_ctl.py`（`--set-active` / `--train` / `--stop` / `--status`）。
- 细节与坑见 `references/model-engine-all-models.md`。

## 已被删除的链路（不要再往页面上接）

- 云端 ECS / `datadrive.world`：模型推送、推理包下载、relay command、摄像头快照轮询等入口全部已下线。
  控制台里若还有按钮走这些 URL，点下去必失败 —— 先确认替代链路（Orin 走 bridge 4060→39071→Orin 39061）再改。
