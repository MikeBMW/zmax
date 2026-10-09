# Z-MAX 状态空间工程存档格式 v2 + 🗂 总工程 zmax_space (2026-10-09)

老倪(两轮话合并):
1. 「需要保存 状态空间工程的所有配置，包括画布的模型，右侧侧面栏的所有配置，标定，测量，
   以及主参数，都要有相应的文件，你来设计一下工程存档文件」
2. 「增加新功能，每次打开工程，要从工程文件打开，你来定义一个 zmax_space 工程，将所有状态空间
   工程文件，标定，配置，主参数等，都整合进这个总工程文件，通过主窗口的文件 → 打开/加载工程
   的方式，集成式打开；不像现在，还得手动加载，太散乱了。」

---

## 1. 文件格式 (`.zmaxproj`, schema `zmax.statespace.project/2`)

一个**自包含 JSON**（拿走一个文件就能在别处复原这次调试），7 段 + 1 张指纹表：

| 段 | 内容 | 来源 (真源) | 界面出处 |
|---|---|---|---|
| ① `canvas` | 画布模型全文 (nodes/links/坐标) + md5 + 统计 | `flows/state_space_obs.json` | 状态空间画布 |
| ② `panel` | 右侧栏所有配置：当前视图/页签 + 6 个运行开关勾选 + 画布栈索引 | 控制台实时读 (`ModelTreeDock` + `chk_*`) | 右侧侧边栏 |
| ③ `calibration` | 标定真源**全文快照** + 每文件 sha256/mtime/字节数 + 未标定项 + 现场标定命令 | `config/calib/*.json` | 🎛 标定页 |
| ④ `master_param` | 主参数 M / inertia / 范围 / 单位 / 流形含义 + 画布 M 节点 7 段快照 + sha256 | `config/calib/zmax_manifold.json` + 画布 M 节点 | 🧮 主参数 M 页 |
| ⑤ `measure` | `measure_view`(测量量/源/判据/命令) + `diagnose_view` + 数据总线配置(模式/固定格式映射/行数) | 画布 M 节点 (由 `ss_node_sync.py` 从真源同步) | 📏 测量 / 诊断页 |
| ⑥ `tasks` | 任务/工单/段覆盖绑定全文 + 活跃任务 | `config/ss_task_binding.json` | 📋 任务配置页 |
| ⑦ `fingerprints` | 每个真源文件的 sha256 + mtime + 字节数 | 5 个真源文件 | —— 用于**判定"存档与现场是否同源"** |
| 兼容键 | `run_cfg` / `ui` (v1 原样保留) | —— | 老代码不用改 |

`explode` 可把存档拆成"人能直接看的相应文件"：
`canvas.json` · `panel.json` · `master_param.json` · `measure.json` · `tasks.json` ·
`fingerprints.json` · `calibration/zmax_calib.json` · `calibration/zmax_manifold.json` · `MANIFEST.md`
(每段 sha256 + 与现场的漂移)。

## 2. 🔴 真源唯一（格式的核心设计，别改成"存档即真相"）

* 真源**永远**是仓库里的文件：画布 `flows/state_space_obs.json` · 标定 `config/calib/*.json` ·
  任务绑定 `config/ss_task_binding.json`。存档只是**某时刻的快照 + 指纹**。
* 写盘一律走各自工具自己的写口，不自己 `os.replace` 到软链：
  画布 → `flows.save_canvas()`（自带校验 + 备份到 `flows/_archive/`）；
  标定 → 逐文件 `*.bak_<时间戳>` → 写 → **回读 sha256 比对**（老倪定的三段纪律）；
  任务 → `tools/ss_task_bind.py --activate`。
* 漂移比对要**剥掉时间戳**（`_meta`/`generated_at`/`updated_at`）再比，否则每次写都会假报"漂移"
  （实测踩到：任务绑定只因 `generated_at` 变化就报漂移）。

## 3. 🗂 总工程 `zmax_space`（集成式）

* 位置固定：`reports/projects/zmax_space.zmaxproj`（`project_file.space_path()`），
  文件里带 `kind="zmax_space"` + `integrated=[canvas, calibration, master_param, tasks, panel]`。
* **打开语义**（这是与普通存档的唯一区别）：
  * 普通存档（snapshot）：默认只回填画布 + 面板；标定/主参数**只核对不覆盖**（安全默认）。
  * 总工程（zmax_space）：**集成式打开** —— 一次全量回填，顺序 = 标定 → 主参数(回读) → 任务 →
    画布 → 面板；每步先备份再写再回读，最后给一页"恢复了什么"的报告（`lines`）。
* 入口（主窗口 → 文件）：
  * `🗂 保存总工程 (zmax_space)…`  `Ctrl+Alt+S`
  * `🗂 打开总工程 (zmax_space)…`  `Ctrl+Alt+O`
  * 老的 `📂 加载工程文件…` 选中总工程时**自动识别 `kind` 并走集成式打开**（同一个菜单，不用记两条路）。
* 确认框把"要回填什么 + 每个文件会备份到哪 + 当前现场与总工程的漂移"逐条列出来，点确定才动手。

## 4. 命令行（`tools/project_archive.py`）

```bash
python tools/project_archive.py space-save                # 🗂 存总工程 (集成式)
python tools/project_archive.py space-open [file] --yes   # 🗂 集成式打开 (全量回填, 先备份)
python tools/project_archive.py space-show [file]         # 看总工程里有什么 + 与现场漂移
python tools/project_archive.py save [--out x] [--note n] # 存一份普通存档 (快照)
python tools/project_archive.py inspect|diff|verify <file># 档案内容 / 漂移明细 / 自检
python tools/project_archive.py restore <file> [--with-calib --yes]   # 只画布+面板 / 连标定一起
python tools/project_archive.py explode <file> [--dir d]  # 拆成人看的文件 + MANIFEST.md
python tools/project_archive.py list                      # 列出现有存档 + 逐段漂移
python tools/project_archive.py upgrade <v1file> [--out]  # 老 v1 存档升 v2
```

## 5. 判据（`tools/verify_project_archive.py`，一次跑完 ⑨ 段）

| 段 | 断到的事 |
|---|---|
| ① | 7 段都在且与真源同源：canvas 89 节点/184 连线 · calibration 2 文件带全文 + 未标定 3 项 · M=1.0 · measure_view 源 6 条 · tasks 5 个 · fingerprints 5 文件 |
| ② | CLI 全链路：save → verify 自检 → inspect 逐段一致 → explode 9 个文件 + MANIFEST 写明"真源唯一" → diff 一致 |
| ③ | **漂移能抓**：现场 M 改 1.5 → diff 报 `calibration` 与 `master_param` 漂移，并指出 `M: 存档 1.0 → 现场 1.5` |
| ④ | `restore` 默认只回填画布+面板：标定真源 sha256 **一个字节没变**，输出明说"标定/主参数未恢复" |
| ⑤ | `--with-calib --yes` 才恢复：不给 `--yes` 拒跑；恢复后回读 sha256 == 存档 sha256；留 `*.bak_<ts>` |
| ⑥ | 控制台在时 `panel` 段真读到 6 个运行开关 + 当前视图；`apply_run_cfg` 能把开关拨回存档态 |
| ⑦ | v1 老存档仍可读 + `upgrade` 升 v2 且**不动原画布内容** |
| ⑧ | 总工程：`space-save` → 搅乱三处（画布坐标 +37 / M=2.5 / 活跃任务 TASK-02）→ `space-open --yes` → 画布 md5 回、M 回 1.0、活跃任务回 TASK-01-FW；`diff` 逐段一致 |
| ⑨ | 主窗口真有 `🗂 保存总工程`/`🗂 打开总工程` 两项且处理函数已绑定；带控制台保存的 `panel` 段含 6 开关 + 视图 |

## 6. 已知边界（如实记）

* **没有**做"控制台启动自动打开总工程"——那会在每次开机时覆盖现场画布/标定，风险大于便利。
  现在是一键（菜单/快捷键）集成式打开，且打开前把"回填什么+备份到哪+漂移"摆出来给老倪确认。
  真要自动，加一个开关即可（下次提需求时再定）。
* `panel` 段里的"运行开关/视图"是**界面态**，命令行存档时读不到（会如实标注"控制台没打开"）；
  在控制台里存才会带上。
* 标定里 `T_base_cam`/`plane_z`/`cell_geometry` 仍是**未标定**（存档不改这个事实，只如实带着缺口 +
  现场标定命令）。

---

## 7. 补 (2026-10-09 老倪两处反馈)

**① 后缀改成 `.proj`** — 「zmax_space.zmaxproj 工程文件后缀应该是 proj」
* `project_file.EXT = ".proj"`; 总工程默认名 `reports/projects/zmax_space.proj` (已改名迁移)。
* **老档案不作废**: 读档按**内容**识别 (schema/kind), 不看后缀; 文件对话框同时列 `*.proj *.zmaxproj`;
  另有 `find_space()` — 新后缀在就用它, 不在就退回老的 `zmax_space.zmaxproj`。

**② 「点击 open 没反应? 应该打开 simulink 的画布啊」** — 真因 + 修法:
* 真因: 打开后那行代码把存档里的 `canvas_stack_index` 当成"要切到哪一页"(`setCurrentIndex(idx)`),
  而那份总工程是 5 号页存的 ⇒ 打开后停在**第 5 页**, 画布 tab (10) 没被前置 —— 看着就像"没反应"
  (其实真源全写好了, 备份也做了)。
* 修法: 打开(集成式/普通加载)后**一律切到 Simulink 画布 tab** (`setCurrentWidget(sim)`), 存档里的
  页索引只当信息不再当指令; 画布是懒创建的 → `sim is None` 时直接 `_init_simulink()` 建出来再切
  (并给 `_init_simulink` 加幂等闸, 防插第二份画布); 状态栏 + 日志明写"已切到 🧮 Simulink 画布"。
* 取证 `tools/probe_open_space.py` (真建主窗口 + 替身对话框): 打开后 `当前页=画布=True`,
  `画布场景项=272` (89 节点 + 184 连线) ⇒ 已进判据集 (`run_gui_verifiers.sh` 的 `open_space`)。

---

## 8. 再补 (2026-10-09 老倪: 「加载工程文件后，还是没反应」) — 实机取证

这次不看代码猜, 直接**在他正在跑的控制台 (v5.26.2, pid 1262666) 上取证**:

**证据 1 (实机日志)**
```
$ grep 'Ambiguous' /tmp/studio_launch.log
QAction::event: Ambiguous shortcut overload: Ctrl+Shift+O     ← 按 Ctrl+Shift+O 两次, 两次都被 Qt 拒绝
```
⇒ 画布菜单「📂 加载 JSON…」和文件菜单「📂 加载工程文件…」**都注册了 Ctrl+Shift+O**
  → Qt 判冲突后 **两个快捷键都不触发** (按钮迁移到菜单时撞的, 我自己引入的回归)。
  实机点测: `Ctrl+Alt+O` (打开总工程) 正常弹文件框 ✅ → 说明接线没坏, 坏的只是这条快捷键。

**证据 2 (确认框默认按钮)**
```
def _msg(...): mb.setStandardButtons(Yes|No); mb.setDefaultButton(QMessageBox.No)
```
⇒ 打开/加载工程的确认框 **默认按钮是「否」**, 且按钮写「是/否」(不是「打开/取消」)。
  回车 = 静默取消, 只剩状态栏 2.5s 一行「已取消: 未打开总工程」→ 用户看到的就是"点了没反应"。
  实机验证: 文件框选好 `zmax_space.proj` → 确认框弹出 → 回车 → 画布真源 mtime **没变、备份也没新生成**
  ⇒ 确实是在确认框那一步被取消掉了 (整条写盘链一步都没走)。

**修法 (v5.26.3)**
1. 快捷键去重: 画布「📂 加载 JSON…」→ **Ctrl+Shift+L**; 画布「⛶ 浮动画布」→ **Ctrl+Alt+F**
   (它和「视图→🖥 窗口适配屏幕」撞了 Ctrl+Shift+F, 也是同类问题)。
2. `_msg/_msg_ask` 增加 `default_yes` + `yes_text/no_text`; 两条打开路径都改成
   **默认「🗂 打开工程 / 📂 加载工程」、回车=确认、取消按钮写「取消」** (危险操作仍旧默认「否」)。
3. **留痕**: 打开/加载工程每一步写 `zmax_data/logs/open_project.log` (入口/选了哪个文件/确认结果/
   写盘异常/界面回填+画布场景项数) —— 以后"没反应"直接看这个文件, 不用再靠猜。
4. 判据: 新增 `tools/verify_shortcuts.py` (枚举主窗口全部 QAction → **任何重复快捷键直接判失败**;
   另查默认按钮/动作名按钮/留痕可写), 已入 `run_gui_verifiers.sh` 的 `shortcuts` 项。
