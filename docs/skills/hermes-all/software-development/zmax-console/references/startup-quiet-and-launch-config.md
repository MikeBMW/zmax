# 控制台启动: 静音 · 单实例 · launch.json 只留一条

三件事都在同一个诉求下: 用户看到终端刷屏、看到控制台“自己又起来了”、看到调试配置一堆没用的。

## 1. 运行纪律 (先记住这条, 其余都是配套)

- **只可停, 不可起/重启**: GUI、systemd 服务、任何进程都不许自己 `start`/`restart`(含 `systemctl --user`)。
  改代码要生效时, 交付话术里写“**需要重启控制台才生效**”, 然后等他点。
- 被问“你怎么又重启了”时, 拿计数结案, 不拿“我没动”结案:
  ```bash
  for u in zmax-ss-canvas-loop zmax-ss-engine-loop zmax-ss-skill-dispatch; do
    echo "== $u"; systemctl show -p NRestarts -p ActiveEnterTimestamp -p MainPID $u; done
  ```
  自己碰过的服务 `NRestarts=0` 就是清白证据; 真有重启的是 `Restart=always` 的单元, 点名它们。

## 2. 控制台“自己又起来了” / 抢焦点 —— 查 user 单元, 不是查进程

`studio.py` 的父进程常是 `systemd --user`(pid 1 之下那层 = 由会话管理器/`.desktop` 拉起), 这本身就说明不是你起的。
```bash
systemctl --user list-units --type=service --all | grep -Ei 'studio|zmax|gui'
systemctl --user show -p Restart -p NRestarts -p MainPID -p ExecMainStartTimestamp zmax-studio.service
ps -eo pid,ppid,lstart,cmd | grep "studio\.py" | grep -v grep | grep -v WebEngine
```
- `Restart=always` + `NRestarts` 在涨 ⇒ 它崩一次就被拉起一次, 用户看到的就是“自己又开一个窗口/抢我光标/还在重启”。
  处置: `systemctl --user stop zmax-studio.service`(只停), 再确认 `pgrep -af "studio\.py$"` 为空。
- 焦点/指针被抢的定位手法(只读, 不注入): 定时采样
  `DISPLAY=:0 xdotool getactivewindow getwindowname` + `xdotool getmouselocation`, 看焦点从哪个窗口跳到哪个。
  用 `for` 循环包一层就会被后台化, 采样别写成死循环。
- **多开 GUI 的另一个来源是 launch.json 里的“550B 单线程 debug”配置**(program = `simulink_module.py`):
  F5 落到那条就等于又起一个控制台实例。删掉它比事后关窗口有用。

## 3. 启动静音闸 `tools/gui/boot_quiet.py`

实测一次完整启动 stdout **365 行**(📌 上次工作状态 / 📚 8 项配置 / ⏱ 启动计时 三行一组**重复 3 遍** + 各页面自述
`[status_panel] geo=…` / `⚡ 后台页面全部建完` / `[模型] L2 YOLO …`), 真正有用只有末尾两行。

落法(两处调用, 缺一不可):
```python
# studio.py 顶部 (_BOOT_T0 = _time.time() 之后, 任何 print 之前)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boot_quiet import install as _bq_install, release as _bq_release
try:
    _bq_install()
except Exception:
    _bq_install = _bq_release = None

# 主窗口 win.show() / raise_() / activateWindow() 之后, 打印“启动计时/首个界面”之前
try:
    if _bq_release is not None:
        _bq_release()
except Exception:
    pass
```

实现要点:
- 用**普通类**(不继承 `io.TextIOBase`)包住 `sys.stdout`: 基类把 `encoding`/`errors` 定成只读属性, 覆写会报类型错;
  `write` 只写日志文件并返回 `len(s)`; 补齐 `flush/isatty/fileno/writable/encoding/errors/buffer`,
  第三方库(transformers/tqdm/PyQt)才不会因为 `sys.stdout.buffer` 之类踩空。
- **日志全量保留**: 每行照写 `ZMAX_BOOT_LOG`(默认 `/tmp/zmax_boot.log`, 追加 + 行缓冲), 并在开头写一条
  `===== 启动 <时间> (pid N) =====`, 事后能按 pid/时间段翻。
- **stderr 一个字都不拦**: 崩了 traceback 还必须看得见; 否则“静音”会把真故障也一起藏掉。
- 逃生口 `ZMAX_BOOT_VERBOSE=1` 完全恢复旧行为(排查启动慢/启动失败时用)。
- 放开时打一行汇总: `✅ 启动静音: 吞掉 N 行启动播报 · 全量见 /tmp/zmax_boot.log`。

验收(不许为此启动 GUI):
```bash
# 默认: 终端 0 行, 日志文件收走
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python -c "import sys;sys.path.insert(0,'tools/gui');import studio" > /tmp/imptest.out 2>/tmp/imptest.err
wc -l /tmp/imptest.out /tmp/zmax_boot.log /tmp/imptest.err   # 期望 0 / >0 / 0
# 逃生口仍然通
ZMAX_BOOT_VERBOSE=1 QT_QPA_PLATFORM=offscreen gui-venv311/bin/python -c "import sys;sys.path.insert(0,'tools/gui');import studio" | head -3
```
注意: 静音期连自己的 `print` 也被吞 ⇒ 验证脚本里要断言“输出为空 + 日志有行”, 不要用 print 当成功标记。

## 4. `.vscode/launch.json` = 模板生成物

真源只有一个: `tools/gui/simulink_module.py::_vscode_launch_cfg(root)`(右键「打开 VSCode」就用它整份重写该文件)。
要加/删配置**只改模板**, 然后重生成:
```bash
cd ~/zmax && gui-venv311/bin/python - <<'EOF'
import importlib.util, json
spec = importlib.util.spec_from_file_location("sm", "tools/gui/simulink_module.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cfg = m._vscode_launch_cfg("/home/ubuntu/zmax")
open("/home/ubuntu/zmax/.vscode/launch.json", "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
print([c["name"] for c in cfg["configurations"]])
EOF
gui-venv311/bin/python -c "import json;d=json.load(open('/home/ubuntu/zmax/.vscode/launch.json'));print(d['version'],len(d['configurations']))"
```
- 必须用**项目 venv** 跑(模板所在文件 import 了 PyQt5; `execute_code` 的沙箱解释器没有 PyQt5 会直接 ModuleNotFoundError)。
  导入模板会执行一组模块级启动日志 —— 只影响输出, 不会起窗口。
- 删配置的口径是**用户实际在用哪条**: 他明说“就剩下这个”就只留那一条, 其余(INTACT×4 / 流形引擎×5 / 配置导入×2 /
  550B studio×1 / Attach / 工具脚本)全删; 删前 `cp .vscode/launch.json /tmp/launch.json.bak_<ts>`。
- 🔴 顺手同步白名单: 模板里 `ZMAX_CANVAS_ONLY` 容易落后于 systemd drop-in(实测缺 `sslimit`/`ssphys`)。
  用这条配置调试若漏了节点, 等于把约束闸关掉再调试, 现象是“代码改了没反应”。
- 删完要回读文件确认条数与 `version`, 并 `pgrep -af "studio\\.py$"` 确认生成过程没顺手起进程。
- 🔴 调试配置里的 `ZMAX_LOOP_MAX_TICKS` 必须写 `0`: 写成 600 就是“跑满 60 秒正常退出”,
  用户看到的是**进程无声消失**, 会问“你怎么退出了/启动不成功”。同理 `ZMAX_LOOP_EVIDENCE` 置 `0`(每拍一行证据也是刷屏源)。
  判定依据: 日志末行是 `🏁 已跑满 N 拍 … 正常结束` 而不是 traceback ⇒ 不是崩, 是配置写的自停。

## 5. 常驻循环降噪 `tools/loop_quiet.py`

启动静音只管到窗口上屏; 之后 10Hz 循环里 **每个被白名单跑到的节点实现每拍各打一行**
(`[sslimit]`/`[ssact]`/`[ssphys]`/`[ssplan]`/`[ssmani_p]`…), 一秒几十行, 调试终端直接糊掉。
用户的原话不会说“循环刷屏”, 只会说「每次运行你都刷屏」「一点都没变」。

落法(一处): `tools/ss_canvas_loop.py` 在 `from lerobot.middleware import load_project` 之后、任何节点跑之前
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loop_quiet; loop_quiet.install()
```

实现口径:
- 终端默认 **0 行/秒**(`ZMAX_LOOP_TERM_LINES` 可调), 连续重复行合并计数; 省略统计**最多 10 秒一行**
  —— 限成“每秒一行省略提示”本身就是新的刷屏。
- 全量照写 `ZMAX_LOOP_LOG`(默认 `/tmp/ss_canvas_loop.log`), 用户贴回来的 `… N 行已省略 (全量: …)` 就是它的出口。
- **stderr 不动**; `ZMAX_LOOP_VERBOSE=1` 恢复原样(排查单节点时用)。
- `__getattr__` 透传 `isatty/fileno/encoding/buffer` 给真 stdout, 否则 tqdm/transformers 会踩空。

验收(不必起 GUI, 用真实节点跑有限拍数):
```bash
ZMAX_CANVAS_ONLY=<与 service 同一份白名单> ZMAX_LOOP_MAX_TICKS=30 timeout 90 \
  gui-venv311/bin/python tools/ss_canvas_loop.py >/tmp/q.out 2>&1; wc -l </tmp/q.out   # 期望 0
```

## 6. “别刷屏”指的可能不是进程, 是你自己的回复

同一天里“刷屏”被投诉了 5 次, 前几次是进程输出, 后几次是**回答本身太长**(一屏数据表)。
定位顺序: ① 先看用户贴的是终端文本还是对话 ⇒ 终端文本查日志/进程; ② 只说结论就一句话 + 一个数字,
细节留日志路径让他自己翻; ③ 他越急, 回复越要短(`停。` / 一句结论), 长解释会被当成新的刷屏。
