# Windows 冻结包「静默失败」: 远程取证 + 三类真因

补 SKILL.md 的编码条目与 `references/frozen-runtime-subprocess-and-macos-gl.md`(frozen 子进程 / 入口派发)。
共同特征: **源码模式全好, 打包后在中文 Windows 上静默坏**, 界面只弹一句泛化错误
(「集成式打开失败」「没有这个文件」), 日志里没有 traceback —— 因为异常发生在 print / 写盘这类
「边角」代码上, 而没人想到它们能把业务掀翻。

---

## 0. 先取证: 把窗口版 exe 当 python 解释器, 在目标机上取真 traceback

前提: 入口已做 argv 派发(`argv[1]` 是 `.py` / `-c` / `-m` 时同进程执行), 见
`frozen-runtime-subprocess-and-macos-gl.md` §1b。有了它, 就能在**没有 python 的机器上**
用 exe 自己跑一段诊断代码, 把只在弹窗里出现过的异常原文拿回来。

```powershell
$exe = 'C:\...\App.exe'
$out = "$env:TEMP\py_out.txt"; $err = "$env:TEMP\py_err.txt"
$code = @'
import sys, os, traceback
sys.path.insert(0, os.path.join(getattr(sys, "_MEIPASS", "."), "src"))   # 见下面第 3 条
import project_file as pj
print("repo_root=", pj.repo_root())
try:
    r = pj.open_space(yes=True); print("ok=", r.get("ok"))
except Exception:
    traceback.print_exc()
'@
$f = "$env:TEMP\probe.py"
[IO.File]::WriteAllText($f, $code, (New-Object Text.UTF8Encoding($false)))   # 不许有 BOM
Start-Process -FilePath $exe -ArgumentList '-c', "exec(open(r'$f',encoding='utf-8').read())" `
  -WorkingDirectory '<app 目录>' -NoNewWindow -Wait `
  -RedirectStandardOutput $out -RedirectStandardError $err
Get-Content $out; Get-Content $err
```

三条硬约束(每条都单独踩过, 少一条就只能拿到空输出):
- 🔴 **GUI 子系统 exe 用 `& $exe ...` 拿不到任何输出**: PowerShell 不等它、也不捕获 ——
  表现是「探针跑了但输出是空的」, 很像派发没生效。必须 `Start-Process -Wait -RedirectStandardOutput/-Error`。
- 🔴 **探针文件必须无 BOM**: PS 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM ⇒ `SyntaxError:
  invalid non-printable character U+FEFF`。用 `[IO.File]::WriteAllText(..., UTF8Encoding($false))`。
- 🔴 **`sys.path` 要按包内真实布局补**, 否则拿到假故障: 很多业务包在冻结包里只是 `--add-data` 的**数据**,
  不是可 import 的模块 ⇒ 裸 `import <pkg>` 报 `ModuleNotFoundError`。判据:
  「同一段代码在 GUI 里能跑、在你探针里 import 失败」= 探针环境坏了, 不是产品坏了。

产物口径: 拿到 traceback 之前不要改业务代码 —— 「集成式打开失败」这种泛化文案对应的可能只是
一句 print, 猜着改会把真因埋掉。

---

## 1. print 崩溃 = 业务崩溃 (中文 Windows 的 GBK)

`sys.stdout` 在中文 Windows 是 **GBK(cp936)**。代码里任何带 emoji 的 `print` 都抛 `UnicodeEncodeError`,
而它**不是「少打一行日志」**: 异常从 print 抛出, 直接掀翻调用它的业务函数。实测爆炸半径:
- `save_canvas()` 里一句 emoji print ⇒ 整个「打开工程」抛异常 ⇒ 用户看到「集成式打开失败」;
- 画布初始化路径同理 ⇒ `_init_simulink` 每轮都失败 ⇒ 被重试 41 轮 × 10s ≈ 410s ⇒ 用户说
  「启动怎么这么慢」(看着像包体/杀软问题, 其实是同一个 print)。

修法(两条都要, 只做一条仍会炸):
1. 入口最顶部(**GUI / 重依赖 import 之前**)把 stdio 钉成 utf-8 + replace:
```python
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
```
2. 静音闸 / 日志 sink 的文件一律 `open(..., encoding="utf-8", errors="replace")` —— stdout 换了,
   写进 GBK 文件照样炸。

⚠️ **只设 `PYTHONIOENCODING=utf-8` 不够**: PyInstaller 的 windowed bootloader 自己造流, 实测子进程
继承了该变量后仍报 `'gbk' codec can't encode`。必须在代码里 reconfigure。

⚠️ **落在 Qt 槽函数里时表现不是弹框, 是崩溃**: 同一条 emoji print 若在按钮回调/QTimer 里抛,
PyQt5 会 qFatal **直接杀进程** —— 用户只说「点一下就崩了」, 日志/事件查看器全空。修法与取证
见 SKILL.md「槽函数里抛异常 = 进程直接消失」节; 别把崩溃当内存/显卡/杀软问题查。

判别捷径: 弹窗错误是泛化的、日志里没 traceback、而**同一操作在 Linux 上正常** ⇒ 优先怀疑编码, 别先查业务。

---

## 2. 文本模式写盘 ⇒ `\n` 变 `\r\n` ⇒ sha256 对不上

凡「写完回读 sha256 与存档 / 另一平台比对」的文件(标定、配置快照、清单), Windows 上
`open(p, "w", encoding="utf-8")` 会把 `\n` 翻译成 `\r\n` ⇒ 哈希必然不同 ⇒ 校验段永远 ❌、
整体判失败(文件内容其实一字不差)。
```python
with open(tmp, "w", encoding="utf-8", newline="\n") as f:   # 钉死换行, 跨平台同哈希
    json.dump(content, f, ensure_ascii=False, indent=1)
```
判据: 同一文件在 Linux 上 sha 对、Windows 上只差在 `\r` ⇒ 就是这个坑, 别去查内容逻辑或 `ensure_ascii`。
凡参与跨平台比对的文本产物, 写入处一律显式 `newline="\n"`。

---

## 3. 打包无条件拷「空骨架」默认数据 ⇒ 功能装完就是空的

CI 里 `Copy-Item defaults/canvas/x.json <包>/flows/` 这种「先放个默认值」在真数据存在时会把
**空骨架**(实测 168 字节 / 0 节点)覆盖进包 ⇒ 用户看到画布空白, 而工程文件里明明有 94 节点 / 222 连线。
定式: **有真源拷真源, 缺失才回落骨架**, 并在构建日志里断言条数(小于阈值就让构建失败, 别让空包发出去):
```powershell
$src = 'data/database/zmax/sources/canvas/state_space_obs.json'
$def = 'defaults/canvas/state_space_obs.json'
$pick = if (Test-Path $src) { $src } else { $def }
Copy-Item $pick '<包>/flows/state_space_obs.json' -Force
$n = @((Get-Content $pick -Raw | ConvertFrom-Json).nodes).Count
Write-Host "canvas nodes=$n from $pick"
if ($n -lt 1) { exit 1 }
```
注意这条**不能只靠发布新包解决在役机器**: 已经装出去的实例要就地补数据文件(见
`windows-plant-host-operations` §10.3 数据种子), 两条一起做才闭环。
