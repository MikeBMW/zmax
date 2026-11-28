# 在 Windows 本机重新打包 PyInstaller 应用（源码改动不生效时）

前提：磁盘上有源码树，但改 `.py` 不生效（模块在 exe 的 PYZ 里）。这是把修复真正落盘的唯一路。

别一上来就想着“通知别人/另一台机器去打包”——仓库的 CI workflow 就是完整配方（Python 版本、依赖、前置步骤、pyinstaller 命令行），本机凑齐这些就能自己打完，比协调人快得多，也不用等谁。

## 0. 先证明磁盘源码确实没被加载

在模块顶层或 `main()` 最前面插一句**写文件**的探针，重启程序，看文件是否出现：

```python
try:
    open(r'D:\<app>\_probe_loaded.txt', 'a', encoding='utf-8').write('module loaded\n')
except Exception:
    pass
```

- 文件不出现 ⇒ 确认为 frozen 版，只能重新打包（不要再去改其它 `.py` 浪费一轮重启）
- 文件出现 ⇒ 源码版，直接改代码重启即可

探针只写文件、不改行为，验证完删掉。

## 1. 找回构建配方（CI workflow）

构建命令通常躺在 CI 里，即使工作区把它删了，git 里还在：

```bash
git show HEAD:.github/workflows/build-win-exe.yml | head -300
# 工作区被删的其他跟踪文件同样手法恢复：
git show HEAD:<path> > <path>
```

从里面抄四个东西：Python 版本、pip 依赖清单、打包前的准备步骤、完整 pyinstaller 命令行。

## 2. 对齐版本与依赖

Python 版本按 frozen 包里的 `_internal/python3NN.dll` 对齐（`python312.dll` ⇒ 3.12）。版本不对，PyQt5 等二进制轮子装不上。

```powershell
winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
& 'C:\Program Files\Python312\python.exe' -m venv D:\<build>_venv
& 'D:\<build>_venv\Scripts\python.exe' -m pip install pyinstaller PyQt5 numpy pillow grpcio protobuf python-pptx pyqtgraph PyOpenGL cyclonedds opencv-python
& 'D:\<build>_venv\Scripts\python.exe' -m pip install mujoco metaworld glfw gymnasium imageio
```

装完先 `-c "import PyQt5, cv2, numpy, PyInstaller"` 自查，再进打包。

## 3. 补齐打包前准备（CI 在 checkout 后做的三件事）

- **staging 目录**：CI 常把仓库根的 `tools\*.py` 复制成一个 `pkgtools/` 再 `--add-data`。本地照抄：把 `tools\*.py` 全 cop8 到 `<repo>\pkgtools`（一次上千个文件，脚本 copy 别手摆）
- **图标**：仓库里往往只有 `.png`，CI 现场转 ico：`Image.open('logo.png').save('logo.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])`
- **版本资源**：CI 用脚本生成 `version_info.txt`（VSVersionInfo 模板），版本号从 `VERSION.md` 正则取；模板里 `filevers` 必须是纯数字四元组，写成字符串会 `NameError: name '<x>' is not defined`

## 4. 跑打包

关键：**在包含入口 `studio.py` 的那个子目录里跑**（CI 是 `cd tools\gui`），因为 `--add-data` 里有大量相对路径（`logo.png`、`docs_sync.py`、`dds_hw.py`…）相对的是 cwd，不是仓库根。

```powershell
Set-Location '<repo>\tools\gui'
& $PYV -m PyInstaller --onedir --windowed --icon logo.ico --name '<App>' `
    --version-file version_info.txt --runtime-hook <hook>.py `
    --distpath dist_nounpack --workpath build_nounpack `
    --add-data "<repo>\flows;flows" ... studio.py
```

参数直接从 workflow 那行抄，只做两处替换：`$env:GITHUB_WORKSPACE` → 仓库根、`pyinstaller `（前缀）→ `& $PYV -m PyInstaller `。

### 两个会让构建白跑的坑

1. **`%PYV%` 是 cmd 语法**，写进 `.ps1` 直接 `CommandNotFoundException`，依赖白装一轮。PowerShell 里必须 `& $PYV`。
2. **`--add-data` 源不存在直接报错中止**。先把命令行里所有 `--add-data "<src>;<dst>"` 的 `<src>` 抽出来逐个 `Test-Path`；缺的目录（比如视频帧缓存）建空目录 + `.placeholder` 占位，别让它卡在打包最后一步。

## 5. 验收与替换

产物在 `dist_nounpack/<App>/`（exe + `_internal/`），**不碰生产目录**，先在原目录外跑：

```powershell
$env:ZMAX_ROOT = '<repo>\'; $env:ZMAX_REPO = '<repo>'
$env:PATH = '<repo>\_stubs;' + $env:PATH      # 有 IFEO/包装的照旧带上
Start-Process -FilePath '<...>\dist_nounpack\<App>\<App>.exe' -WorkingDirectory '<repo>'
```

对照项：exe 大小与旧版同量级、主窗口出现、服务端口数量一致、`Responding=True`、以及本次要修的症状消失。全过了再备份旧 exe/`_internal` 并替换。

参考量级（一个 470MB 级的 Qt 应用）：依赖安装 5~10 分钟，PyInstaller 本体 8 分钟左右，产物 exe ~24MB + `_internal` ~520MB。

替换的落地顺序：停全部进程 → 旧 `exe` 与 `_internal` 改名加 `.bak-<日期>` → 复制新产物 → 启动。_internal 动辄 500MB+，同盘复制很快；备份先改名再复制，比“先复制后备份”少一次全量拷贝。

## 6. 换 `_internal` 会覆盖外部脚本（最容易翻车的一步）

程序里被 worker 直接 `python xxx.py` 拉起的**外部脚本**（`_internal/tools/*.py`，如推流服务、AR 服务）不是打包产物。新打的 `_internal` 里这些脚本来自 staging 的 `tools/*.py`：

- 之前直接改 `_internal/tools/foo.py` 打的补丁，**换包时会被静默覆盖回旧版**，表现成“修好的功能又坏了”（实测：换完位姿变空、相机帧变成几十字节的无效图）
- 正确做法：这类修复一律改 `<repo>\tools\foo.py`（源码），打包时由 staging 自动带上；换包前把 `_internal/tools/*.py` 与 `_internal.bak-*/tools/*.py` diff 一遍，确认没有只活在旧包里的改动

## 7. 替换后的验收按数据链路逐条抽查

换完 exe / `_internal` 别只数端口。凡是本次或以前修过的功能，逐个打一次真实请求（位姿 API 的坐标字段、相机快照的字节数、状态接口的 online/fps），判据用**业务返回值**而不是“进程起来了”。重新打包会重置源码树之外的一切手工改动，这一步就是拦它的。
