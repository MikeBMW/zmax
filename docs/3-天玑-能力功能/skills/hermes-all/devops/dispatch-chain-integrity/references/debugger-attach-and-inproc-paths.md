# 「断点不进」取证与同进程调试通道

用户说「技能没有进入断点 / 这个 clamp 也没有断点」时，**不要先改代码、也不要先解释进程模型**。
先把「他调试的到底是哪个文件、那条语句在不在这个进程里」用 /proc 读出来。

## 1. 认调试目标（一条命令，不靠问）

```bash
# 找调试器适配器 → 它拉起的 debuggee 就是"用户按 F5 的那个进程"
for p in /proc/[0-9]*; do c=$(tr '\0' ' ' < $p/cmdline 2>/dev/null);
  case "$c" in *debugpy*) echo "$(basename $p) $c";; esac; done

P=<debuggee pid>
tr '\0' ' ' < /proc/$P/cmdline; echo        # ← 目标脚本名就在末尾：是哪个 .py
readlink /proc/$P/cwd                        # 工作目录 (确认是哪份代码)
tr '\0' '\n' < /proc/$P/environ | grep -E 'ZMAX_|PYDEVD|PYTHONPATH'
```

实测形态：debugpy 的 debuggee 参数末尾是 `tools/ss_canvas_loop.py`，环境里带
`ZMAX_CANVAS_ONLY=ssplan,ssact,ssyolo,ssdec,sslimit,ssphys,...` ⇒ **这个进程只跑那几个画布节点，
里面根本没有技能派发那一段**，`SKxx.clamp` 只存在于派发器进程（`systemctl show ExecMainPID`）。
⇒ 结论：不是断点问题，是**调试目标和执行目标不是同一个文件**。

⚠️ `ss -ltnp | grep 5678` 为空**不能**说明没挂调试器：pydevd 是**反向**连 IDE，不监听端口。
⚠️ 别用 `grep <pattern> /proc/<pid>/maps` 判断模块有没有被导入 —— `.py` 是读入的不是 mmap 的，
永远查不到；要判导入就看行为/计数（闸拍数、产物 mtime）或 `ls /proc/<pid>/fd`。

## 2. 修法：给宿主循环一个「同进程节拍」

```python
# tools/dispatch_inproc.py —— 宿主每拍调一次 tick()
def under_debugger():
    return "pydevd" in sys.modules or "pydevd_frame_eval" in sys.modules or sys.gettrace() is not None

def enabled():
    return os.environ.get("ZMAX_DISPATCH_INPROC") in ("1", "true", "yes", "on") or under_debugger()
```

- **检测到调试器就自动启用**：用户按 F5 要的就是单进程可断点，不该再让他去配 env。
  生产进程没有 pydevd/tracer ⇒ 立即返回 None，零影响。
- 挂接点选**他真实在跑的那个循环**（画布 `tools/ss_canvas_loop.py` 的 `while True`、
  GUI `SimulinkModule._tick`、引擎循环都可以），并且用 `try/except` 包住 —— 调试器不能把宿主拖死。
- **调试模式默认写隔离目录**：`$TMPDIR/zmax_dbg_live`，首次从生产的 `chunk_latest.json`/`trace_live.json`
  拷一份（只拷、不写回），同时 `ZMAX_LIVE_DIR`/`ZMAX_SHM_DIR` 指过去。否则合成数据会写进用户正在看的页面。

## 3. 单射调度下的第二重前提：强制在职段

「一轮只有一个技能在职」时，你给 SK05 打断点而当前在职是 SK03 ⇒ 它这一拍**本就不执行**。
加一个调试开关，强制某段在职（段不在当前块覆盖范围里时，造一条调试请求，否则没有动作就没有 clamp 调用）：

```python
_act = STAGES[si]
_dbg = os.environ.get("ZMAX_DEBUG_STAGE", "").strip()
if _dbg in STAGES:
    _act = _dbg
    if _act not in self.cur:            # 块只覆盖 stage_idx..7
        vc = limits_for(_act)["v_cap"]
        self.cur[_act] = {"action": [0, 0, -vc, 1.0], "step": 0, "ts": now, "dbg_synth": 1}
```

生产不设这个 env，行为完全不变。

## 4. 没有 IDE 也能自证（假调试器）

```bash
ZMAX_DEBUG_STAGE=接近 ZMAX_CANVAS_ONLY=sslimit ZMAX_LOOP_MAX_TICKS=4 ZMAX_LOOP_EVIDENCE=0 \
./gui-venv311/bin/python -c "
import sys; sys.settrace(lambda *a: None)      # 让 gettrace() 非 None = 假装挂了调试器
sys.argv=['ss_canvas_loop.py']
import runpy; runpy.run_path('tools/ss_canvas_loop.py', run_name='__main__')
"
# 判据看产物，不看终端：
python -c "import json;d=json.load(open('$TMPDIR/zmax_dbg_live/skill_latest.json'));
print(d['在职技能'], d['闸_拍数'], d['两条闸对账'])"     # 4 拍 ⇒ 在职=接近 闸拍=4 对账=一致
```

`sys.settrace(lambda *a: None)` 只让 tracer 非空、不跟踪行，开销可忽略，足以验证「调试器门控的路径」
真的被执行。另可用 `--probe` 式子类包装计数（`cls.clamp` 包一层数次数）直接打出「本进程 pid X 里
SK03Descend.clamp 被调 60 次」。

## 5. 坑

- 🔴 **终端没输出 ≠ 没在跑**：常驻循环默认静音（`tools/loop_quiet.py` 把 `ZMAX_LOOP_TERM_LINES` 默认 0），
  判定一律看产物（隔离目录里的 `skill_latest.json`、闸拍数、mtime），不看 stdout。
- 🔴 **改完必须重启调试会话**：进程里是旧代码，F5 重来才加载；同理常驻单元要 `systemctl restart`。
- 🔴 **别把生产的 live 目录当调试输出地**：先 `sudo systemctl stop` 那个常驻单元，或直接用隔离目录，
  两个写者会让「在职/对账」口径打架。
- 🔴 汇报时给的是**证据三元组**：调试目标文件（/proc cmdline）、同进程调用次数、隔离目录里的闸拍数/对账；
  不要只说「改了，应该能停了」。
