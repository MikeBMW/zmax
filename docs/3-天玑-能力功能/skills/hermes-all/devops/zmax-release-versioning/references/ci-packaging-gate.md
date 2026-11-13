# CI 打包闸红了：诊断顺序与四类根因

`Build Desktop (Windows .exe + macOS .app)` 红的时候，别先改代码 —— 先定位是哪一道闸、哪一类根因。

## 诊断顺序（省时间的就是这个顺序）

1. `GET /actions/runs/<id>/jobs` —— 每个 job 的 `steps[]` 给「失败步名 + 成功 N/总 M」。
   只看总 `conclusion` 没用，`in_progress` 也确实不等于卡住。
2. `GET /check-runs/<check_run_id>/annotations`（job JSON 里的 `check_run_url`）—— 小而快，
   直接给 `::error::` 行 + warning 摘要。**两个平台各拉一次**：Windows 常卡在早期步、macOS 在后期步，
   只看到一条就下结论必错。
3. 需要上下文再拉 **run 级别 zip**：`GET /actions/runs/<id>/logs`（实测百 KB 级、十几秒）。
   单 job 流式 `/actions/jobs/<id>/logs` 可能十分钟都下不完，不要用它等。
4. 修完一处就重推：commit → `git tag -f vX.Y.Z` → `git push -f origin vX.Y.Z`。
   **不要用 `workflow_dispatch` 复用旧 tag** —— 它重建同一个未修复的 commit。

## 闸有四道，失败位置决定症状

| 闸 | 位置 | 失败形态 |
|---|---|---|
| pack_guard / 画布断言 | PyInstaller **之前** | `git status` 全绿但 step 早段 exit 1；日志里能 grep 到 `仍是软链` / `nodes 94` 一类统计行 |
| 资产核验 | 包**建完之后** | 打出一行统计（`metaworld stock XML: N · 工程包(节点逻辑): NE · 画布真源: NJ …`），某一项是 0 |
| 冻结核验 | 包**建完之后** | 真跑产物 `--engine-selftest`，`exit=1` + `engine_selftest*.json` 里有 `cause` / `trace` |
| 上传/Release | 最后 | 文件传了但 release 没有该资产 ⇒ 必须回读 `releases/tags/<tag>` |

## 四类根因（按踩到的频度）

### ① 仓库里存着 symlink(120000)，又要在 CI 里打包

Windows 检出成**占位文本**、macOS 检出成**真链接** —— 同一个 symlink 两种形态，两平台都判「仍是软链」。
修法：该文件**不入库**（`git rm --cached` + `.gitignore`），改由 CI 的 materialize 步骤按真源生成；
生成时 **`rm -f <dst>` 再 `cp -f`** —— macOS 上 `cp -f` 到 symlink 会顺着链接写同一 inode，链接还在、断言照旧红。

### ② 闸脚本 `print` 带 emoji/中文

Windows runner 控制台是 cp1252 ⇒ `UnicodeEncodeError`，崩在修数组环**之前**（`--fix` 静默失效，
只剩 `::warning::`，真正的失败点在后面几百行）。修法：脚本入口
`sys.stdout.reconfigure(encoding='utf-8', errors='replace')`（stderr 同），
**以及 workflow 里的 inline python 断言块也要自己 reconfigure** —— 那一段不在闸脚本里，修了脚本它照样崩。

### ③ 核验判据还在查已删除的路径

重构删掉了一个目录（例如「节点归 middleware」把 `engineering/nodes/` 删了），而资产核验公式里还写着旧路径
⇒ 该项永远 0 ⇒ 与真实打包内容无关的**假失败**，而且能连跨几个版本没人发现。
判据：失败步的统计行里只有一项是 0、其余全 1~3。
修法：`git log -- <旧路径>` 确认是重构删的；**判据改成「新路径 或 旧路径命中任一个」**，不要只换成新路径
（下次重构又断）。推之前本地建个假目录结构把 `find` 表达式跑一遍。

### ④ 新增 `src/lerobot/**` 子包没加进 `--add-data`

症状：冻结核验在 GUI 导入链深处报 `ModuleNotFoundError: No module named 'lerobot.policies.<x>'`，
而打包闸与资产核验全绿 —— 因为它们是清点文件，只有冻结核验（真跑 `--engine-selftest`）会真 import。
修法：**三处 pyinstaller 命令都要加**（Windows onefile / Windows onedir 免解包版 / macOS），
路径写成与目录一一对应的 `--add-data "…/src/lerobot/policies/<x>;src/lerobot/policies/<x>"`（macOS 用 `:`）。
加完在本地 `sys.path=src` import 一次，确认包自身没有别的重依赖（torch/ultralytics 之类应在 try/except 里）。

## 验收（缺一条不算出包）

- 两 job 全 success：`Windows .exe 27/27`、`macOS .app 22/22` 这个粒度的成功步数。
- `GET /releases/tags/<tag>` 回读 `assets[].name/size/state=uploaded`，把文件名+体积报给用户。
- 产物有缺项要主动说（如内置演示视频从 runner 下载失败被脚本占位放行），不能当它存在。
- 冻结核验里 `render_ok:false` **不算失败**（无 GPU 的 runner 必然 GL 失败），别照着它去修。
