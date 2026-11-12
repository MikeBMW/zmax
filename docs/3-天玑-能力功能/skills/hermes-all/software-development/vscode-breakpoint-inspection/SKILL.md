---
name: vscode-breakpoint-inspection
description: Use when 要在 VSCode 停断点并看变量值。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [debugging, vscode, debugpy, breakpoint, numpy]
    related_skills: [zmax-console, su2-unified-state-space]
---

# 在 VSCode 里把断点真停住, 并让值可读

pdb / debugpy 的基础用法见已装的 `python-debugpy`; 本文只补两件它不管的事: **替用户在 GUI 里起会话并自证停住**, **把没有语义的数组改成带物理量的名字**。

## 何时用
- 「用 vscode 定义一个断点, 停在 X 的输出/return, 我看看实际的输出」
- 「在 vscode 里看不到这个变量的物理含义」—— 大数组/结构体在 Locals 里只有下标
- 需要在用户屏幕上留一个**已经停住**的会话, 而不是给他一串操作步骤

## 铁律
1. **交付物是"已停住的会话"**。他说"你给我运行"= 你去点、去按、去起, 不许让他自己 F5。
2. **断点必须门控**: 共享库里裸 `breakpoint()` 会把常驻服务挂死。
   ```python
   if os.environ.get("ZMAX_DEBUG_<TAG>") == "1":
       breakpoint()
   ```
   门控变量只出现在调试 launch 配置的 `env` 里; 常驻服务环境没这个变量 ⇒ 生产路径逐位不变。
3. **先让变量有名有单位, 再让他看** —— 见第三节。
4. **自证停住**: py-spy 抓到 `_do_wait_suspend (pydevd)` + 你的函数帧, 才算停住。进程状态 `S` 分不出"停住"和"在跑"。
5. 不许把 `patch` 当探针: 写进去的 `"X"`、删掉的一行就是真代码。改完用 `py_compile` + AST 裸 name 扫描 + 真跑验。

## 一、配置与启动
- 单文件夹窗口读 `.vscode/launch.json`; 用户若开的是 `.code-workspace`, **同一份配置还要写进该文件顶层 `"launch": {"configurations": [...]}`**, 否则选择器里根本没有它。两份都要 JSON 校验。
- 必填: `"type": "python"`, `"request": "launch"`, `"program": <绝对路径>`, `"justMyCode": false`, `"console": "integratedTerminal"`, `env` 带门控变量; 配置名加个显眼前缀(如 `🧪 断点 · …`)方便唯一匹配。
- 起会话(**别用裸 F5**: 它复用上次用过的配置, 可能是个又重又无关的 GUI 配置):
  ```bash
  DISPLAY=:0 wmctrl -a "Visual Studio Code"; sleep 1
  DISPLAY=:0 xdotool key --clearmodifiers ctrl+shift+p; sleep 1.5
  DISPLAY=:0 xdotool type --delay 25 "Debug: Select and Start Debugging"; sleep 1.5
  DISPLAY=:0 xdotool key Return; sleep 2
  DISPLAY=:0 xdotool type --delay 25 "<配置名里的唯一词>"; sleep 1.5
  DISPLAY=:0 xdotool key Return
  ```
- 重来: `shift+F5` 停掉旧会话再按上面重起 —— 暂停中的旧会话指着旧代码, 改了文件不重起等于没改。

## 二、自证停住(唯一可信证据)
```bash
pgrep -f '<script 名>'                 # debugpy 起的是孙进程: adapter → launcher → <hash> script.py, 取最后一个
sudo py-spy dump --pid <pid>           # 期望: _do_wait_suspend (pydevd) → do_wait_suspend → <你的函数>
sudo py-spy dump --pid <pid> --locals  # locals 内容; numpy 显示成 <ndarray at 0x…>
```
- py-spy 跨 uid / ptrace 范围需要 sudo。
- 每次报"停在哪个文件第几行": 改代码后行号会变, 上一轮的行号不能复用。
- 无 GUI 兜底(先跑它确认门控真的生效): `ZMAX_DEBUG_<TAG>=1 python -m pdb driver.py` → `c` → `p x.shape`。

## 三、让向量"有物理含义"(最常被提的要求)
他看到的不该是"55 个数", 而是 `tcp_p` / `peg_xyz` / `hole_xyz` … 各自带单位。

```python
named = {seg.name: vec[seg.start - base:seg.stop - base] for seg in SEGMENTS}
x = np.concatenate([named[s.name] for s in SEGMENTS])   # 顺序只由段表决定
self.named, self.named_units = named, {s.name: s.unit for s in SEGMENTS}
```
- 段表(`SLICE` / `layout_table()`)是唯一口径, 调用点禁止自己数下标。
- 再给 `describe(x) -> [{name, unit, idx, value, meaning}]`: 调试控制台一句 `us.describe(x)` 出带单位的表, 比让他在 Locals 里逐项点开快得多。
- **零回归是硬门槛**: `np.array_equal(新x, 旧concat)` 多组随机输入全 True 才敢说"只是可读了"。少一个/错一位下标形状不变, 下游全部数字静默错。
- **dtype 保持原样**: float64 转 float32 会引入 ~1e-8 差, "与旧口径逐位相同"就不成立。
- 段名手打必错(`grip_scalar` 不是 `gripper_scalar`): 名字从段表取。

## 四、收尾怎么说
- 三句话给全: 停在哪个文件哪行 · Locals 展开哪个键看到什么 · 调试控制台敲哪几条命令。
- 他还要往下走就预告: F5 会依次再停在哪几处, 每处哪几段非零、为什么是 0(如"无示教几何 ⇒ peg/hole=0, 几何误差 e=0")。
- 提交前 `git grep -n 'breakpoint()'` 确认剩下的都是门控版本。

## 常见坑
- **裸 F5 选错配置** ⇒ 起的是别的程序, 用户以为断点没生效。
- **只有 `.vscode/launch.json` 而用户开的是 workspace 文件** ⇒ 选择器里找不到配置, F5 静默用了别的。
- **断点在不执行的分支上**(某个输入下根本走不到) ⇒ 现象是"跑完没停"; 先确认该行在本轮输入下会执行, 或挪到公共出口。
- **靠编辑器行断点** ⇒ 格式化/加注释就漂; 用门控 `breakpoint()`, 行号变了也还在。
- **只说"已停住"没有帧栈证据** ⇒ 用户按 F5 发现程序早结束了。
