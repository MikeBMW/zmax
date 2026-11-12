---
name: vscode-host-workspace-config
description: "Use when 配置/修 VSCode 宿主工作区、标题、Source Control 面板。"
version: 1.0.0
author: Hermes Agent
license: MIT
trigger: "Use when 用户说'工作空间怎么分的''代码看不到了''路径你得显示啊''source control 帮我设置好''VSCode 怎么打开/重启'。"
metadata:
  hermes:
    tags: [vscode, workspace, scm, git, host]
    related_skills: [zmax-console, zmax-vscode-extension, gnome-desktop-launchers]
---

# VSCode 宿主配置 (多根工作区 · 标题 · Source Control · 进程)

## When to Use
- 用户问「工作空间怎么分的」「原来的代码怎么看不到了」「路径你得显示啊」「source control 帮我设置好」
  「这个 vscode 怎么打开」「怎么重启 VSCode」。
- 要改 `ZMAX.code-workspace` / `.vscode/settings.json`, 或重启/杀 VSCode 实例, 或查 VSCode 崩溃。
- 只管**宿主**(工作区/标题/面板/进程); 自研扩展的开发与打包见 `zmax-vscode-extension`。

## 用户口径 (先立住这几条, 否则改完还得返工)
1. 界面极简: 字少 / 不挤 / **不许截断**; **路径必须看得见**(会直接说「路径你得显示啊」)。
2. **禁止为"防崩溃"擅自砍工作区根** —— 实测精简根照崩(SIGTRAP/SIGILL 与挂载范围无关),
   却立刻换来「原来的代码怎么都看不到了」。要减负就减 `files.watcherExclude` / `search.exclude`, 不减根。
3. `window.title` 里**不许写自造文字**(用户会当场问「这几个字哪来的」); 要路径就用 `${activeEditorLong}` 模板。
4. 改完必**回读 + 核窗口标题**(`wmctrl -l | grep -i "visual studio"`), 不能只说"改好了"。

## 步骤
1. 读现状: `ZMAX.code-workspace` 的 `folders`/`settings` + `.vscode/settings.json` 的 git/watcher 段 +
   `DISPLAY=:0 wmctrl -l | grep -i "visual studio"`(当前标题长什么样)。
2. 改根: 名称**带路径**; 前几个用 `~` 简写(≤约 24 字符防侧栏截断), 仓库根那个写**完整绝对路径**。
   本机口径四根: `框架 (~/zmax/src/lerobot)` / `控制台 (~/zmax/tools/gui)` / `文档 (~/zmax/docs)` / `工程 (/home/ubuntu/zmax)`。
   子目录根 + 整仓根同挂会重复显示(多根不去重) —— 用户要就给, 先说明一句。
3. 改设置: 直接抄 `references/settings-blocks.md`(工作区 + 标题 + git 面板 + 排除项, 已实测)。
4. 验证: `node -e "JSON.parse(require('fs').readFileSync('<文件>','utf8'))"` 校验;
   工作区文件的改动 VSCode 会**自动重载**, `sleep 8` 后核标题/根是否生效。
   要验标题模板可用 `code -r <某文件绝对路径>` 让活动编辑器落到该文件, 再 `wmctrl -l` 看标题含不含路径。
5. 需要重载才生效的项(如 `autoRepositoryDetection`)告诉用户自己按 `Ctrl+Shift+P` → **Reload Window**;
   **绝不在他正在调试时替他重载/杀实例** —— 会连带杀掉他的调试会话。

## 坑 (每条带机制)
1. **`.vscode/` 通常被仓库 `.gitignore` 忽略** ⇒ `git add .vscode/settings.json` 报
   `The following paths are ignored by one of your .gitignore files: .vscode`。这是仓库既有约定,
   **不要 `-f` 硬塞**; 如实说明"设置只在本地生效、不进库"(用户要入库再单独确认)。
2. **Source Control 面板"像没配置"就查两个开关**: `git.autoRepositoryDetection: "openEditors"`(没打开文件时
   认不到仓库) + `git.autorefresh: false`(改了文件面板也不刷新)。复原为 `true`。
   判"面板坏了"前先核底层三件: `git config user.name/user.email`、`credential.helper`、`git status -sb` 有无 upstream。
3. **杀实例禁止 `pkill -f "<cmdline 子串>"`** —— pkill 匹配**整条命令行**, 会连你自己这条 bash 一起匹配上
   ⇒ 自杀(exit -15)且同一行后半段命令静默不执行。用 `PIDS=$(pgrep -x code | tr '\n' ' '); kill $PIDS`,
   或 `systemctl --user stop zmax-vscode-<ts>.scope`。
4. **起独立实例**用 `systemd-run --user --scope --no-block --collect --unit=zmax-vscode-$(date +%s) /usr/bin/code <工作区>`。
   裸 `Popen` 会让它落在控制台服务的 **cgroup** 里, 控制台一停/一崩 systemd 按 cgroup 连它一起收走
   (用户看到的现象是"VSCode 卡住")。
5. **核凭证禁止 cat/grep `~/.git-credentials`** —— 随手写的正则会把 token 连用户名一起打出来
   (首尾字符也算泄露)。`git config --get credential.helper` + `git remote -v` 足够。
6. **VSCode 崩溃 ≠ 用户的工程/扩展坏了**: 先取证再下结论。入库证据 = `dmesg` 的 `trap invalid opcode`、
   VSCode 自记 `CodeWindow: renderer process gone (reason: crashed, code: 132)`、`/var/crash` 的 core;
   exthost 里那几行 `Unable to refresh tree view ...: Canceled` / `Extension host exiting with code 0`
   是渲染进程死后的**连坐记录**, 不是扩展报错。排除项还要量: 可用内存 / oom-killer / CPU 指令集。
   取证模板见 `zmax-console 技能的 references/console-child-processes-and-crash-forensics.md`。
7. `~/.vscode/argv.json` 的 `disable-hardware-acceleration: true` = 全软件渲染(历史为治 SIGTRAP 设的)。
   软件光栅/JIT 恰是 SIGILL 型崩溃的高发区 ⇒ 现象照旧时值得**反向对照一次**, 改前 `cp argv.json argv.json.bak_<原因>`,
   并如实告诉用户这是"对照实验, 结果待观察", 不要写成已修复。
8. 版本:**不自主升级** VSCode/工程版本; 宿主随官方源走 (`apt-get install -y --only-upgrade code`),
   定制全部走自研 vsix, 不碰 VSCode 源码。
9. **「打开 VSCode 到 X 的代码」= 定位文件, 不是重建工作区**: 已有实例就用
   `code -g <绝对路径>:1` 复用窗口开 tab (连开多个 = 一组 tab, 最后一个为激活), 然后靠窗口标题自证
   (`wmctrl -l | grep -i "visual studio"` 显示 `文件名 — Visual Studio Code`)。
   **不要** `code <某子目录>` 另起实例 —— 那会把用户的多根工作区换掉, 他会说"原来代码怎么都看不到了"。
   只有**没有任何实例**时才 `systemd-run … /usr/bin/code <ZMAX.code-workspace>`, 起完再 `code -g` 开文件。
   一次定位多处用重复 `-g`(`code -r -g /abs/a.py:311 -g /abs/a.py:346 -g /abs/b.py:196`), 窗口标题只显示当前那个
   ⇒ 回复里必须**逐条列 绝对路径:行号 + 该行是什么函数/职责**, 让他能直接复制跳转; 只回"已打开"等于没交付。
   提问是"某段数据从哪来/在哪转换"时, 行号选在**转换发生的那一行**(如编码/投影/融合调用处), 不要笼统给文件头。

## 用户接着会问的两件事 (先备好)
- **怎么打开这个工作区**: 桌面 `Z-MAX工程.desktop`(`Exec=/usr/bin/code <工作区文件>`) / `code <工作区文件>` /
  `文件 → 打开最近`。标题里的 `(Workspace)` 是 VSCode 对工作区文件的标注, 不是错误;
  想彻底去掉就让用户「打开文件夹」(排除项来自仓库内 `.vscode/settings.json`, 照样生效)。做桌面入口见 `gnome-desktop-launchers`。
- **怎么在里面调试工程**: F5 下拉已有现成配置 —— `🚀 全新调试进程 (studio.py)`(要先停常驻控制台, 否则两个实例
  抢相机/引擎/共享内存) 与 `🔌 Attach 现有控制台 (5678)`(只对带 `ZMAX_DEBUG=1` 起来的实例有效,
  桌面/服务起的默认不 listen)。断点绑定/空心的**根因清单**(惰性 import · 路径层数 · 模块加载方式 · 实例属性顶替 ·
  独立进程 · frozen modules · 断点行不是可执行语句) 与「不靠 VSCode 的 pdb 自救法」见 `zmax-console 技能的 references/vscode-debug-breakpoints.md`。

## 让用户自己「停在断点看变量」: attach 靶子 (不改产品代码)

用户说「debug、停在断点上、我看看变量」时, **不要**把 `breakpoint()` 插进业务源码交给他 —— 它会跟着提交跑进产线,
而且停住的是服务进程本身(整条链一起冻)。正确做法是起一个 **靶子脚本** (放 scratch, 不进仓库):

```python
import debugpy
debugpy.listen(("0.0.0.0", 5678))   # 0.0.0.0: 他可能从 LAN 网段连; 绑 127.0.0.1 就只有本机能连
debugpy.wait_for_client()           # 阻塞到有人 attach
sys.path[:0] = ["<repo>/src", "<repo>/tools"]
import <module> as M
debugpy.breakpoint()                # 连上即停, 立刻有 Locals 可看
M.<真函数>(...)                      # 只调真函数真源, 不写仿制实现
```

- `launch.json` 追加一条 attach: `type: python` · `request: attach` · `connect:{host,port}` · `justMyCode:false` ·
  `pathMappings:[{localRoot:<repo>, remoteRoot:<repo>}]`。**先备份再 json load→append→dump** —— 用户往往已有
  「断点 · 整个 GUI」之类的配置, 整份 `write_file` 会把它冲掉, 他下次 F5 就找不到自己那条了。
- **交接前必须自验 attach 真能停**, 否则他连上是一片空白。最小 DAP 客户端足够:
  `initialize` → `attach` → `setBreakpoints` → `configurationDone` → 等 `stopped` → `scopes`/`variables` 打 Locals。
  两个硬点: debugpy 的 attach **`arguments` 不能省**(省了回 `AttachRequest.__init__() missing 1 required
  positional argument`); 收包要按 `request_seq` 对响应, 否则事件与响应串台、`scopes` 会 KeyError。
- 自验会占掉**唯一**客户端, 断开后靶子就失活 ⇒ **交付给他之前重启一次靶子**并确认端口在 LISTEN。
- 靶子阻塞在 `wait_for_client`, 必须后台起; 回复里逐条给 `绝对路径:行号`(可直接粘贴) + 停住后 Locals 里会出现
  哪些变量(取帧的 arr/path/meta、检测的 det2d/det3d), 只说「你设个断点」等于没交付。

### 多根工作区 (`.code-workspace`): launch 配置写在工作区文件里, 不是根 `.vscode/launch.json`

🔴 **打开 `.code-workspace` 时, 根目录的 `.vscode/launch.json` 不被读取** —— 多根工作区的调试配置来自
工作区文件自己的 `"launch"` 段 (`{"launch": {"version": "0.2.0", "configurations": [...]}}`),
或各根目录各自的 `.vscode/` (下拉里显示成 `文件夹 : 配置名`)。只改根 `.vscode/launch.json` 时: 文件看着完全正确、
`json.load` 也对, 但 F5 下拉里根本没有它 ⇒ 表现为"按了 F5 什么都没发生", 而人还在怀疑断点/代码。
所以**两处都要有**: 工作区级 `launch` 段 (用户 F5 真正读的那份) + 根 `.vscode/launch.json` (用户改为"打开文件夹"时生效)。
- 工作区 `launch` 段里的 `program` / `python` / `cwd` 一律写**绝对路径** (多根下 `${workspaceFolder}` 有歧义)。
- 改完回读校验三件: 工作区 JSON 能解析 · 每条配置的 `program`/`python` 存在 · `cwd` 是目录; 再把
  "下拉里选哪条 + 要按 Reload Window" 告诉用户。

🔴 **"F5 之后断点不进"先证"到底有没有进程起来"**, 这一步能一次排掉一大片方向:
```bash
ps -eo pid,lstart,args | grep -E "debugpy/(launcher|adapter)|--connect 127.0.0.1" | grep -v grep
wmctrl -lp | grep -i "<界面标题>"     # 窗口属主 pid + 标题本身就是状态读数
```
没有 launcher 进程 = 脚本压根没启动 (配置没被读到); 有进程但标题写着「未运行 — 点 ▶运行」= 程序起来了、
业务没跑; 两者都与断点无关。`lstart` 早于你改的文件 mtime = 他跑的是旧代码。

### 单线程调试档 (550B) 的 launch 配置

那条配置的 `env` 必须给全, 少一项就不是"单线程 550B 调试":
`OMP/MKL/OPENBLAS/NUMEXPR/VECLIB/TORCH_NUM_THREADS=1` · `MALLOC_ARENA_MAX=2` ·
`ZMAX_SINGLE_THREAD=1` · `ZMAX_DEBUG_MODE=1` · `ZMAX_PRODUCT=550B` · `PYTHONUNBUFFERED=1`
· `PYDEVD_DISABLE_FILE_VALIDATION=1`，并且那条配置要带 `"pythonArgs": ["-X", "frozen_modules=off"]`：
Python 3.11 的 frozen bytecode 会让 debugpy 漏断点(它自己会在 stderr 警告)，`args` 是传给被调程序的、必须用 `pythonArgs`。
少了这一项的表现不是报错，而是**断点永远不停**。

🔴 **`"env": {}` 是最常见的陷阱**: 用户自己贴/手写的配置块往往空着。程序仍能 F5 起来、界面也正常,
但档位门只看 `ZMAX_PRODUCT` —— 缺了就不在标定/调试档, 深调试被下游拒掉。**报错不在启动时, 在下游**, 难查。
改之前先跑一遍逐字段比对(把用户贴的 JSON 当期望值, 与文件里那条逐键 diff 并说明在第几条), 别只回一句"是的"。

**"单线程"要三层都做, 缺一层就还有线程在别处算**:
1. 解释器早期灌 BLAS env(必须在第一行 `import numpy/torch` 之前; 事后 `torch.set_num_threads()` 改不了
   已建好的 OpenBLAS 池)。放程序入口模块顶部, 留 `ZMAX_MULTI_THREAD=1` 逃生口, 不做静默切换。
2. 运行期再压 torch/cv2(`set_num_threads(1)` / `set_num_interop_threads(1)` / `cv2.setNumThreads(1)`) ——
   env 只影响首次初始化。
3. 节点内自己起的后台线程(`Thread(target=_job)` 那种异步推理)在单线程下要切同步分支 —— 否则人停在主线程,
   算在别的线程跑, 断点停不住、线程数也说不清。输出里标 `mode="sync"` 让下游看得出是真算还是回放。

**判"单线程"看计算线程, 不看进程线程总数**: GUI 的 Qt 线程与第三方监视线程(transformers 的 `tqdm_monitor`)
一直在, `ls /proc/<pid>/task | wc -l` 永远不会等于 1。自证一行:
`import torch, threading; torch.get_num_threads(), threading.current_thread().name` → `(1, 'MainThread')`。
常驻服务(画布/引擎循环)不受这些 env 影响, 它们不是调试档 —— 别为了让调试单线程去改服务 unit。

🔴 **env 没进进程时先查「文件被谁重写」, 再谈 Reload Window —— 顺序反了会连着几轮白改**:
`.vscode/launch.json` 这类产物可能由程序自己的模板**整份重写** (本项目 `simulink_module._vscode_launch_cfg()`,
右键「打开 VSCode / 进入源码」就触发)。手工 patch 的 env 会在那一刻被冲回 `{}`, 而 patch/diff 当时是成功的、
文件里看不出任何异常, 用户按你说的 Reload / 重启也永远好不了。排查顺序:
1. `tr '\0' '\n' < /proc/<pid>/environ | grep -E 'ZMAX_PRODUCT|ZMAX_SINGLE_THREAD|OMP_NUM_THREADS'`
   —— 全空 = 配置根本没进进程 (这一步能直接排掉"代码/断点"方向);
2. `grep -rn "launch.json" --include=*.py .` 找重写者; 有模板就**只改模板**, 再用模板重新生成并**回读盘上文件确认字段在**;
3. 最后才提 Reload Window —— 它只对"文件本身已经对了、VSCode 缓存旧配置"这一种情形有效。

改了源码/配置要判"新东西到底进没进那个进程"不用猜: `ps -o lstart= -p <调试进程 pid>` 与 `stat -c %y` 比一下 ——
进程启动时间早于文件 mtime 就是还在用旧的。用 `pgrep -af "debugpy/launcher.*<入口>.py"` 找那个 pid,
不要 `pkill -f`。
