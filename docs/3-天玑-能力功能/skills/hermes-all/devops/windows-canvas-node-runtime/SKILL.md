---
name: windows-canvas-node-runtime
description: "Use when Windows 打包版画布节点跑不起来/缺依赖/VSCode 打不开。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [windows, canvas, nodes, pyinstaller, torch, vscode, zmax]
    related_skills: [state-space-canvas-engineering, zmax-state-space-architecture, vscode-host-workspace-config]
---

# Windows 打包版画布节点: 可运行 / 可调试 / 可打开

## When to Use
- 老倪说「每个节点都要可运行」「可以用 VSCode 打开」「windows 平台要兼容」「vscode 怎么打不开」。
- app9 里节点 import 失败、`No module named X`、冒烟超时、点「打开源代码」没反应。

## 踩坑: Copy-Item 把「目录」拷成同名文件

`Copy-Item $srcFile $dstDir -Force` 当 **$dstDir 尚不存在**时, 不会建目录, 而是把源文件**拷成名为 $dstDir 的文件**。
症状: 后续 `Test-Path $dst\file.py` = False, `Get-Item` 显示 `Attributes=Archive`(不是 Directory), `rmdir` 返回 267(目录名无效), robocopy 返回 16。
正确做法: `New-Item -ItemType Directory -Force -Path $d` **再** `robocopy $srcDir $d /E`; 或 Copy-Item 时目标写全文件名。
判据: 拷完必须 `(Get-Item $d).Attributes` 含 `Directory`, 且 `(Get-ChildItem $d -File).Count` 与源一致。

## 踩坑: 跨平台校验只看回显会漏

SSH 回显中文是 GBK 乱码, 不能靠肉眼看。同步判据固定为三项: 目标 `Test-Path`=True + `Get-FileHash MD5` == 源 md5 + 文件 size 相等。

## 部署更新 app9 (不重打包 exe)

Windows 上真实运行的是 **onedir 包** `C:\Users\Mike\zmax_console\app9`，
`Z-MAX_Console.exe` 旁边就是可改的 `_internal\{src,tools,flows,config,data,models}`。
所以「发 Windows 版本」= **同步这三块，不动 exe**：

```
_internal\src    ~2318 文件   ← 代码真身
_internal\tools  ~2524 文件
_internal\flows  ~49  文件     ← 画布
```

改前先 `Copy-Item` 备份成 `src_bak_<date>` / `tools_bak_<date>` / `flows_bak_<date>`；
用 `robocopy <src> <dst> /E /NFL /NDL /NJH /NJS /R:1 /W:1`（**/E 不删目标多余文件**，
这是故意的：app9 里有 `_single_thread.py` 这类 Linux 仓里没有的补丁文件，不能删）。

🔴 **`C:\home\ubuntu\zmax` 是 Junction → `C:\Users\Mike\zmax`**（`Get-Item -Force` 看 `LinkType`）。
launch.vbs 里 `ZMAX_ROOT=C:\Users\Mike\zmax` ⇒ 两个路径是同一份，写哪个都行，不要以为是两份各改一遍。

### 中文文件名/路径传输（结论取决于方向与 tar 实现）

🔴 **先判方向，别一律否掉 tar**：`tar -cf - -C <src> <file> | ssh host 'tar -xf - -C <dst>'` 在
**两端都是 GNU tar** 时（git-bash 写、Linux 读），中文文件名与中文目录名完整保留、两端 md5 一致 ——
实测传 `流形引擎…框架.pptx` 这类名字无碍，`-z` 可加可不加。上表那两行失败的是
**Windows 的 bsdtar 当写入端**（本地打包 / Linux→Windows 方向）。判据：接收端是 Windows bsdtar 就换
zip(UTF-8) 路线；接收端是 Linux 就直接走 tar 管道，别白白多一步 rename。

| 通道 | 结果 |
|---|---|
| `tar -czf - \| ssh 'tar -xf -'` | ❌ `Invalid empty pathname`，还留下乱码目录 |
| `zip -r -UTF-8` | ❌ 这版 zip 不认该选项（`option 'F' ... not negatable`） |
| `Z-MAX_Console.exe -c "..."` | ❌ 静默无输出，不执行 |
| **`zipfile` 打包 + `_internal\_pyenv\python.exe` 解压** | ✅ 实测中文目录/文件名全对 |

```python
# Linux 侧: Python zipfile 打包会自动给中文名打 UTF-8 flag(bit 11)
with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as z:
    for root,dirs,files in os.walk(src):
        for f in files: z.write(os.path.join(root,f), os.path.relpath(os.path.join(root,f),src))
```
```powershell
# Windows 侧: 真 python 在 _pyenv 里, 不是 C:\Python313
& 'C:\Users\Mike\zmax_console\app9\_internal\_pyenv\python.exe' -c "import zipfile;zipfile.ZipFile(r'...').extractall(r'...')"
```

🔴 **`_pyenv\python.exe` 只能当解压/文件工具，不能跑节点**：它是嵌入式 3.12，
import `_internal\numpy` 会 `AttributeError: module 'numpy' has no attribute 'ndarray'`，torch/cv2 也缺。
节点只在 `Z-MAX_Console.exe` 的 PyInstaller 环境里能跑。验证画布能否加载用
`json.load(_internal/flows/state_space_obs.json)` 数节点（实测 94），不要试图 import registry。

### 软链必须解引用（老坑，每次打包都会碰到）

`flows/state_space_obs.json` 是**两级软链**：
`zmax/flows/... -> ../src/lerobot/engineering/flows/... -> ../../../../data/database/zmax/sources/canvas/...`。
`os.walk` 遇到软链若 `continue` 跳过 ⇒ **画布根本不会进包**，部署完一看 md5 还是旧的。
正确做法：`src = os.path.realpath(full) if os.path.islink(full) else full`，按原 arc 名写。
验收必查这 3 处 md5 相等：`zmax/flows/` · `zmax/src/lerobot/engineering/flows/` · `app9/_internal/flows/`。

### 生效纪律

控制台是**常驻 GUI**（实测 3 个 Z-MAX_Console 进程）⇒ 覆盖文件后**必须重启一次才生效**，
且不能擅自重启（规矩: 只可停不可起、重启须点名）。部署完先 `Remove-Item` 各 `__pycache__`
（robocopy 不删旧 pyc），再告知用户「磁盘已就位，重启控制台即生效」。

## 🔴 先分清三层, 否则 38 个「坏节点」里 37 个是误判
一个节点的真值在 registry, 不在画布 JSON:

| 层 | 位置 | 判据 |
|---|---|---|
| 契约 | `src/lerobot/middleware/nodes/n_<x>.py` | `NODE_ID` / `IMPL_KEY` / `PORTS_*` / `manifest()` |
| 实现 | `src/lerobot/middleware/nodes/impl/<impl_key>.py` | `impl_manifest.json` 的 `func` 在文件里 |
| 算法 | `policies/manifold/memory/...` | `SOURCE` + `SOURCE_SYMBOL` 能解析到 |

**唯一运行真值**: `lerobot.engineering.registry.NODE_LOGIC[impl_key]['fn']`（157 个 key，含 `fn/module/file/line`）。
`import registry` 只要 0.3s（不拉 torch）。判「能不能跑」就查这个, 别查画布 `params.source`。

画布 `params.source` **经常是过期路径**（`engineering/nodes/library.py` 早被重构成 `middleware/nodes/impl/*`）。
修法: 新增 `exec_source/exec_symbol/exec_line` 指向 registry 真身, 失效旧值存 `source_stale`, **有效旧指针（如 `parallel.py:FeedforwardAccelerator`）不要覆盖** —— 那是算法出处文档指针。

## 工具（已落地 `app9/_internal/tools/`）
- `ss_nodes_doctor.py --report | --fix [--dry] | --smoke` — 体检 / 修标注 / 逐节点真调（子进程隔离 + `ZMAX_SMOKE_TIMEOUT`）
- `_smoke_one.py <impl_key>` — 单节点靶子, 打 `SMOKE_JSON {...}`
- `debug_node.py <node_id> [--no-wait]` — VSCode attach 靶子（debugpy listen 5678）
- `ss_bench.py --rounds N` — 冷导入 / 每节点 p50-p95 / 一轮全扫 Hz

## 🔴 app9 是裁剪包, 缺的是运行时不缺代码（全部实测补法）
app9 `_internal` 只有 cv2/numpy/scipy/PyQt5/mujoco/metaworld, **没有 torch/torchvision/ultralytics/huggingface_hub**;
`base_library.zip` 只打 155 个标准库模块; `PIL/` 只有 6 个 `.pyd` 没有 `.py`。

补齐方案（不重打包 exe）:
1. `_pylibs/` 目录 + `src/lerobot/__init__.py` 顶部注入:
   `sys.path.append(_pylibs)`, 标准库补全 `sys.path.insert(0, _pylibs/_stdlib)`。
   **标准库必须 insert(0)**: 排在 `base_library.zip` 后面时 `html.cookies`/`graphlib` 仍会命中残缺同名包。
2. torch 从旧版打包目录（如 app8 `_internal/torch`, 2.15.0+cpu / 458MB）整目录拷 `_pylibs/`；
   纯 python 单文件包（debugpy / mergedeep / pyparsing / typing_inspect）用
   `uv pip install --target _pylibs --no-deps --python 3.12 <pkg>`。
   🔴 **带依赖的包不能 `--no-deps`**：`huggingface_hub` 要 httpx2/httpcore2/hf-xet，
   `draccus` 要 typing_inspect→mypy_extensions，逐个补会一条接一条冒出来（每次只报第一个缺失）。
   这两个直接 `uv pip install --target _pylibs --python 3.12 huggingface_hub draccus` 让它自己解析依赖，
   或在装完后跑 `python -c "import lerobot.policies"` 把这条链上的缺失一次性暴露出来再决定补哪个。
   uv 的 target 路径必须写 `C:/Users/...` 原生形式 —— 写 `/c/Users/...` 会被拼成 `C:\c\Users\...` 建错目录。
3. 标准库全量: 下 `python-3.12.10-embed-amd64.zip`, 解 `python312.zip` 到 `_pylibs/_stdlib`
   （**必须与解释器同版本**, 看 `_internal/python312.dll`）。
4. `PIL/*.py` 从完整打包目录拷进来（97 个文件）—— 否则 `torchvision.transforms` 一导就 `cannot import name 'ImageEnhance'`。
5. `_single_thread.py` 在 `middleware/nodes/impl/` 缺失会让 6 个 impl 直接 ImportError（`from ._single_thread import brk`），从旧包补。
6. 🔴 **`src/lerobot/__init__.py` 顶部的 `_pylibs` 注入会被重新部署/整包同步冲掉** —— 症状是原本
   跑得通的节点某天集体 `No module named 'huggingface_hub'`。这时别查依赖，先 `head -20 src/lerobot/__init__.py`
   看那 15 行路径注入还在不在；丢了就补回（`_pylibs` 目录通常还在，只是没人把它加进 `sys.path`）。
   只要部署流程是「把 Linux 仓的 src 同步过来」，而注入是在 Windows 侧手改的，就一定会复现。

## 冒烟的两个判读陷阱
1. **超时阈值**: 首载 torch+ultralytics 的节点要 21–24s。设 20s 会把 6 个好节点报成 TIMEOUT。默认 60s。
2. **`OK` ≠ 业务成功**: 返回 `{'ok': False, 'error': 'No such file ...best.pt'}` 是**缺权重/运行时数据**, 不是代码坏。
   分类报: 进程级 OK（不崩、能调、能返回）vs 业务降级（缺资产）。别把降级算成不可运行。

## Windows 上让 VSCode 真的能开能调
- winget 装不上时（`stdin is not a tty`）: 直接下 `https://update.code.visualstudio.com/latest/win32-x64-user/stable`
  （约 256MB）, `./VSCodeUserSetup-x64.exe /VERYSILENT /MERGETASKS=!runcode,addtopath /NORESTART`。
- **装了不等于已运行的进程能看见**: PATH 只对新进程生效, 8793 那个 GUI 还在旧 PATH 里,
  它的「打开 VSCode」按钮会继续报「未找到 code 命令」。报错来自 `tools/gui/simulink_module.py`,
  根治是把查找改成 PATH → `%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd` → `Program Files` 三级兜底。
- 解释器就用 `Z-MAX_Console.exe`（它支持 `-c` 和跑任意 .py）, 但**不支持 `-m`** ⇒ 不能用 `-m debugpy`,
  调试只能走 attach 靶子（`debug_node.py` + launch `request: attach`, port 5678）。
- 扩展: `ms-python.python` / `debugpy` / `pylance` / `python-envs` 都要装, 否则 F5 下拉是空的。

## 已验证口径 (2026-11-10, app9)
65 个 model 节点 → 修完 65/65 进程级 OK；一轮全扫 29.83s（瓶颈是 YOLO/torch 首载, 不是节点逻辑）。
标注同步四处落点 md5 一致: `_internal/flows/` · `src/lerobot/engineering/flows/` · `<ZMAX_ROOT>/flows/` · `<ZMAX_ROOT>/data/database/zmax/sources/canvas/`。
