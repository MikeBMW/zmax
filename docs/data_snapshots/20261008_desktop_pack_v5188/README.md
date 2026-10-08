# 2026-10-08 · 桌面版打包坏包修复 (v5.18.8)

## 背景 / 现象
老倪报 Windows 版**双击即崩**：
```
studio.py:258 → simulink_module.py:26 → node_logic.py:25
ModuleNotFoundError: No module named 'lerobot'
```

## 根因（实证，不是推测）
09-28 把 141 条节点逻辑从 `tools/gui/node_logic.py` 整体迁进 `src/lerobot/engineering`，
`node_logic.py` 只留一层 compat shim（`dirname(__file__)/../../src` 上溯 + `import lerobot.engineering`）。
两个后果叠加：

1. **打包漏带这个包** —— `build-win-exe.yml` 的 win/mac 两个 job 都 `--add-data` 了
   `policies/left_right` `yolo_3d` `calibration` `manifold` `verification` `memory`，**唯独漏了 `engineering`**；
2. **核验假绿** —— 冻结核验（`exe --engine-selftest`）只 import `mujoco/metaworld` 并建场景步进，
   **完全没覆盖应用自己启动的导入链** ⇒ 每个 tag 都"构建成功 + 核验通过"，坏包一路发出（老倪手上是 v5.18.6）。

## 修复
| 文件 | 改动 |
|---|---|
| `tools/gui/node_logic.py` | 冻结感知：工程根按候选表找（`_MEIPASS/src` → `<here>/src` → `ZMAX_SRC_DIR` → 源码上溯），缺包给人话提示 |
| `.github/workflows/build-win-exe.yml` | win/mac **加 `--add-data src/lerobot/engineering`**；包内断言新增"工程包(节点逻辑) / 画布真源"两项；A/B 基线 job 同步补上（其契约 = 只少 runtime-hook） |
| `tools/gui/studio.py` | 冻结核验扩到 **GUI 启动导入链**：`node_logic → simulink_module → project_file → node_logic_dialog` + 断言注册节点数 ≥100 且画布 JSON 在位 |
| `tools/fix_venv_shebangs.py`（新） | 顺带修 `gui-venv311/bin` **56 个** CLI 的破损 shebang（家目录整合遗留老路径） |

## 本目录文件
| 文件 | 是什么 |
|---|---|
| `frozen_ab_A_with_package.json` | 本地冻结探针（带工程包）自检输出：`node_logic_keys=151`、画布真源在位、rc=0 |
| `frozen_ab_B_without_package.json` | 同一探针**不带**工程包：逐字复现现场报错 `No module named 'lerobot'`、rc=1（证明根因 + 证明核验有牙） |
| `probe_frozen_node_logic.py` | 上面那个探针本体（冻结包里判定工程包是否可达） |
| `frozen_ab_onedir.sh` | A/B 构建脚本。**注意**：本机 venv 带 torch/ultralytics，`--onefile` 归档会超 4GB 报 `struct.error` ⇒ 本地取证统一用 **onedir**（`sys._MEIPASS=<dist>/<name>/_internal`，冻结语义一致） |
| `ci_frozen_selftest.json` / `ci_frozen_selftest_log.txt` | CI 在**真 exe / 真 .app 里**跑冻结核验的完整日志与抽出的 json |
| `release_exe_archive_check.txt` | 从 GitHub Release **下载回来的 exe** 的归档清单里，工程包相关 26 条（`src/lerobot/engineering/**` + `state_space_obs.json`） |

## 当天实测数字
- 本地 A/B（onedir 冻结探针）：带包 **rc=0 / 151 条节点逻辑 / 画布 JSON 在位**；不带包 **rc=1**，错误串与现场同源。
- CI（run 37755212807，两个 job 全 success）真产物自检：
  Windows exe `frozen=true, mujoco=3.3.0, node_logic_keys=151, logic_home=library.py, canvas_json=state_space_obs.json, gui_import_chain=true, rc=0`；
  macOS .app 同（`meipass=.../Contents/Frameworks`）。
- 包内断言输出（Windows）：`metaworld 资产 563 · stock XML 1 · L4 场景 XML 2 · 工程包(节点逻辑) 1 · 画布真源 2 · mujoco 运行时库 1 · 插件 1`。
- 已发布产物：`Z-MAX_Console.exe` 169,862,752 B（169.9 MB）md5 `c13e0c637d07185e433d46c3c7c7c2c1`；`Z-MAX_Console-macOS.zip` 133.8 MB。
- 版本号六处一致（`integrity_check` 通过 v5.18.8），`repo_guard` 干净。

## 诚实边界
- Windows exe 本机跑不了 ⇒ 端到端证据 = **CI 真产物自检** + **归档离线校验**两条；真机双击确认由老倪做。
- `secret_scan` 的 3 处 agent-hub token 是**既有**命中（`tools/publish_status.py` · `tools/ss3d_live_push.py` · `tools/web/ss3d_push.php`），本轮未动，待轮换后清历史。

## 关联
- Release：https://github.com/MikeBMW/zmax/releases/tag/v5.18.8
- 技能沉淀：`pyqt5-distribution`（新增「冻结包必须验 GUI 启动链」+ `.github` 需 `git add -f`）、`zmax-console`（小版本迭代清单顶部三条硬教训）
- 同日其它快照：`20261008_safety_gates_v5184` / `..._zfloor_tol_v5186` / `..._goldpt1_gripper_v5187` / `..._aoi_gold_judge_v21`
