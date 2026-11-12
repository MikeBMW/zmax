# 让 VSCode 调试会话真的起来 / 真的停住

断点“不进”的最后一段路常常不是断点问题，而是**会话根本没起来**或**停在别处**。按下面顺序走，每步都有判据。

## 1. launch.json 字段分工（最常见的死法）

| 字段 | 放什么 | 放错的后果 |
|---|---|---|
| `python` | 解释器绝对路径 | 用系统 python ⇒ 缺项目包，import 报错 |
| `pythonArgs` | **只放解释器开关**：`-X frozen_modules=off`、`-u` | 放了脚本参数 ⇒ `python --steps` ⇒ `unknown option --steps` |
| `args` | **脚本自己的参数**：`--steps 120`、`--quiet` | 放成 pythonArgs 时同一句报错 |
| `program` | 绝对路径 | 相对路径 ⇒ cwd 不对时找不到 |
| `env` | `DISPLAY`、`QT_QPA_PLATFORM`、离线开关、业务开关 | 缺 `frozen_modules=off` 时断点可能被跳过 |

写错 `pythonArgs` 的现场三连：①集成终端只有一行 `unknown option --xxx` + usage ②随后弹模态框
`Timed out waiting for debuggee to spawn` ③左侧 `Call Stack` 空，但工具栏「重启 / 停止」仍亮 = **半死会话**。
改完先 `py_compile`/`json.load` 回读，再按 F5；那个超时模态框会拦住下一次 F5，**先按 Escape 关掉**。

## 2. F5 到底跑哪条配置

- VSCode 记住的是下拉里**上次选中**那条，列表顺序只对“从未选过”生效。
- 想让它必跑目标那条，最省事的做法是**临时只留一条** `configurations`（根 `.vscode/launch.json` 与
  `.code-workspace` 的 `launch` 段两处都改），跑完再恢复。
- 多根工作区只读 `.code-workspace` 里的 `launch`，不读根 `.vscode/launch.json`；两者都写才两头保险。
- 判断实际跑的是哪条：读 launcher cmdline 尾部 program，别看 json 顺序。

```bash
ps -eo pid,ppid,stat,etimes,pcpu,args | grep -E "debugpy/launcher" | grep -v grep
# 尾部 `-- /abs/path/script.py --steps 120` = 真正被 launch 的 program 与参数
```

## 3. 会话活着 / 已暂停（不用 DAP 客户端）

```bash
T=<target pid>            # launcher 的 python 子进程，cmdline 带 --connect
ps -o pid,stat,etimes,pcpu,time -p $T     # etimes 在涨、time(CPU 时间) 不涨 ⇒ 停着
cat /proc/$T/wchan; grep -E "^(State|Threads)" /proc/$T/status   # S / futex_do_wait = 等调试器
```

再加一条业务侧判据：**目标函数之后的落盘日志不再增长**（若日志写在函数返回之后，停住时行数冻结）。
三个读数一起才敢说“停在断点上”；只看进程还在就会被“启动阶段卡网络”骗过去。

第四条（不用眼睛也能读界面，且比视觉子代理快一到两个数量级）: **本地 OCR 截当前窗口**。

```bash
W=$(xdotool getactivewindow); xdotool getactivewindow getwindowname   # ← 先确认抓的是不是 VSCode
scrot -u /tmp/vs.png && tesseract /tmp/vs.png /tmp/vs -l eng+chi_sim --psm 11 tsv
# 在 tsv 里 grep `PAUSED` / `Breakpoint` / `clamp` / 目标文件名 ⇒ 直接得到“已暂停 + 栈顶帧 + 当前行”
```

- 🔴 `scrot -u` 抓的是**当前活动窗口**；`wmctrl -ia` 有时不真生效 ⇒ 你会 OCR 到终端/别的窗口，
  读出一堆乱码还以为界面没变。每次都先 `xdotool getactivewindow getwindowname` 回读窗口名。
- 判据取词: `PAUSED` / `ON BREAKPOINT` / 栈帧函数名 / 目标文件名；能把 `Paused on breakpoint` 与栈顶帧一起读到，
  就不必再截第二次屏或叫视觉子代理。

## 4. 程序参数下不来真行断点 ⇒ 在函数体里放钩子

- 行断点只能由编辑器通过 DAP `setBreakpoints` 下发；这版 debugpy 的 `PyDB` 没有 `set_break`，
  不要试着用私有 API 替编辑器下断点。
- 能落地的是在目标函数**体里**（return 之前）放一行 `debugpy.breakpoint()`：

```python
def _zmax_bp_armed():
    """只在真连了调试器时为 True ⇒ 生产运行零开销、行为逐位不变。"""
    import os, sys
    if os.environ.get("ZMAX_BREAK_SKILL", "1").strip() == "0":
        return False
    try:
        import debugpy
        if getattr(debugpy, "is_client_connected", None) and debugpy.is_client_connected():
            return True
        if debugpy.get_global_debugger() is not None:
            return True
    except Exception:
        pass
    return sys.gettrace() is not None

# 在目标函数体里 (return 之前) 写两行:
#     if _zmax_bp_armed():
#         import debugpy; debugpy.breakpoint()
```

停下来的帧就是那个函数本身；用 wrapper 在外面包一层只会停在 wrapper 帧，Call Stack 少一层。

🔴 **`debugpy.breakpoint()` 绝不许包在 `try/except Exception` 里**。pydevd 是靠抛异常把栈挂起来的，
被 `except` 接住后调用栈继续往下走，暂停点落到 `except` 分支的 `pass` 行 —— VSCode 确实显示
`Paused on breakpoint`，但当前行是 `pass`、帧顶是钩子函数，用户看到的就是“没停在技能里”。
判据: 暂停行号应当**等于 `debugpy.breakpoint()` 那一行的行号**，Call Stack 第一帧就是目标函数。
armed 判定放 `try` 里没关系（它不抛挂起异常），只有 `breakpoint()` 必须在裸语句位置。

🔴 **加了 `_zmax_bp_armed()` 调用点就必须确认这个名字在同模块里真定义了**。漏定义时每个 clamp 都
`NameError`，而调用链上游普遍 `except Exception → 直通` ⇒ 运行照跑、日志照写(上游返回后)、断点一次不停，
表现与“调试器没接管”完全一样。落地检查: `grep -c "^def _zmax_bp_armed" <文件>` 必须是 1，
再跑一次无调试器离线单拍 `python tools/debug_run_engine.py --steps 12`，期望 `12 次 clamp / 12 步` 且零中断。

- 钩子会**改变行号**（每插入一行，后面的行整体 +1）：交付时说清“当前行号”，并让用户按新行号改断点。
  批量插 2 行 × N 个类之后不要手算，用 AST 报一份表：`ast.walk` 找 `func.attr == "breakpoint"` 的
  `Call.lineno`、`Assign → _out` 的行、以及 `Return` 行，一次贴给用户。

## 5. 替用户操作 VSCode / GUI 的硬约束

- `xdotool windowactivate` 常常不真生效，用 `wmctrl -ia <win>`，再用
  `xdotool getactivewindow getwindowname` 回读确认，然后**不带 `--window`** 发键（带了会被部分应用忽略）。
- `pkill -f "<含本命令的字符串>"` 会把自己这条 shell 杀掉（`exit -15`）。按 pid 停；或把 kill 单独发一次。
- 盲点按钮要两条腿: ①**本地 OCR 直读**(快, 秒级) `scrot -u /tmp/w.png` + `tesseract /tmp/w.png out -l chi_sim+eng --psm 11 tsv`,
  解析 tsv 的 `left/top/width/height` 得到目标文字的**像素坐标**再换算屏幕坐标 —— 比“截图交给视觉子代理”快一到两个数量级,
  只有 OCR 认不出图标按钮时才升级到视觉子代理; ②视觉子代理给坐标(图标类按钮用这个)。
- **先找命令通道, 再考虑点坐标**: 能通过应用自己的命令文件/接口触发同一个处理函数时, 一律走那条路(见 §6),
  盲点坐标是最后手段 —— 图标按钮的 OCR 文本往往是乱码(`NS` / `riz`), 误点“停止/重启”的代价很高。

## 6. GUI 的「▶ 运行」不一定跑引擎 ⇒ 技能一条不执行

调试“技能断点”时，最隐蔽的一层是：**界面确实在跑、界面确实在动，但跑的是回放**。回放不走
`sched.decide → skill_step → clamp`，所以技能断点永远不停，而日志/画面都“正常”。

判据（两个文件对撞，十秒可判）：

```bash
# ① 现在跑的是什么源: src 里写 "操作视频同源 episode … N 步" 且帧数在涨 ⇒ 回放
python -c "import json;d=json.load(open('zmax_data/ss_live/trace_live.json'));print(d.get('src'),d.get('帧'))"
# ② 技能链到底有没有被这个进程走过: 该 pid 在技能取证日志里计数为 0 ⇒ 没走
sed -n 's/.*"pid": *\([0-9]*\).*/\1/p' zmax_data/ss_live/skill_calls.log | sort | uniq -c | sort -rn | head
ls -l --time-style=+%H:%M:%S zmax_data/ss_live/skill_phys.json   # 帧龄很老 = 派发链没跑
# ③ AR 分支的另一份铁证: 有 start 且 src=AR场景 ⇒ 走的是 AR 播放, 引擎没跑
cat zmax_data/ss_live/ar_play.json      # {"ts":…,"action":"start","by":"simulink.run","src":"AR场景","task":"…"}
```

**切回引擎分支**: 画布 JSON(`data/database/zmax/sources/canvas/state_space_obs.json`)里 `ssdata.params.src_state`
要是「插拔场景」; 运行中的模块可能是早先切过的 AR 状态 ⇒ 用命令通道 `ss_canvas` 让它 `open_state_space()` 重读画布,
隔几秒再 `ss_run`。跑起来后的正面判据: `skill_calls.log` 出现**该 GUI pid** 的记录、`trace_live.json` 的 `src`
不再是 episode/AR。

结论口径（用户问“为什么断点不进”时必须按这个顺序说）：**当前数据源是回放 / 实时** → 回放不经过决定层 →
技能一次不执行 → 断点无对象。要把技能跑起来得把画布数据源切到实时/仿真再点运行。别把这一层说成“断点没绑”。

## 7. 驱动本仓 GUI 的命令通道（先查有没有, 别盲点）

`tools/gui/studio.py` 轮询 `/tmp/zmax_nav_cmd`（一行一个命令，读完即删），写文件即等于点按钮：

```bash
printf 'ss_canvas\n' > /tmp/zmax_nav_cmd     # 建/切到状态空间画布页 (懒创建)
printf 'ss_run\n'    > /tmp/zmax_nav_cmd     # 调 start_sim() —— 等价画布 ▶运行
```

可用命令: `simulink` · `ss_canvas` · `ss_run` · `ss_3d` · `ss_focus_seg` · `mparam` · `mparam_shot` ·
`orbital` · `gt_dump` · `model_engine` · `ss_model_engine` · `ds_win` · `monitor` · `ov_page` ·
`station_page` · `roadmap_geo` · `l5_status` · `l5_diag` · `l5_interact` · `open_all` · `config` · `home`。

三个坑：
1. **别把 `ss_canvas` 和 `ss_run` 写在同一个文件里**：两者都是延迟 `_oneshot`（画布 600ms、运行 300ms），
   同轮读取 ⇒ `ss_run` 先打而 `self.simulink` 还是 `None` ⇒ 静默什么都不做。分两次写，中间隔几秒。
2. **`ss_run` 不等于“跑引擎”**：`start_sim()` 按档位/数据源分流（L5 档 → 标注训练闭环；AR 数据源 → AR 播放；
   `real_l2` 模式 → 真机采集闭环）。只有“数据源 = 实时/仿真”那一支才走 `decide → skill_step → clamp`。
   所以 `ss_run` 之后必须用 §6 的两个文件判据确认走的是哪一支，不能假定。
3. 命令被吃了也不报错：`studio.py` 的命令分支大量 `except Exception` 直通。写完用**副作用文件**（
   `ui_run.json` / `trace_live.json` 的 mtime、`skill_calls.log` 的 pid）判它到底执行了没有。
- 点之前必须先确认**当前在哪一页**：截图上找不到目标按钮通常不是坐标问题，而是窗口停在首页 / 别的页，
  先导航再截第二张。盲点只会误触其它卡片。
