# 断点不进 / "没反应" 的取证工具集（只读，不改被测程序）

前提：不相信“日志说成功了”“我刚改好了”，也不相信用户描述的间接结论。
四个观测面：**窗口 → 界面文字 → 进程栈 → 进程环境/产物文件**。

## 1. 哪个窗口在前台（VSCode 打开的是不是这个工作区）
```bash
wmctrl -l                       # 窗口 ID + 标题；标题常带打开的文件绝对/波浪号路径
xdotool getwindowgeometry <0xID>
```
标题是判据：`~/zmax/.../execution.py - Visual Studio Code` 说明 VSCode 确实开着那个文件；
没有 VSCode 窗口就说明用户所谓的“在 VSCode 里打断点”根本不存在。

## 2. 拽到前台截屏 + OCR（读界面自己写的状态）
```bash
echo $DISPLAY                                  # 必须是 :0 这类真实会话
xdotool windowactivate --sync <0xID>; sleep 1; scrot -o /tmp/s.png
tesseract /tmp/s.png /tmp/s -l chi_sim+eng     # 全文
tesseract /tmp/s.png /tmp/st -l chi_sim+eng tsv   # 每词 x/y/w/h
awk -F'\t' 'NR>1 && $12 ~ /运行|执行器/ {printf "%s @ %d,%d\n", $12, $7+$9/2, $8+$10/2}' /tmp/st.tsv
```
- 界面上的字样比任何推理都硬：「未运行(没点 ▶ 运行)」「帧龄 9.15s」= 引擎停着。
- 大图先裁再 OCR（PIL `crop` + `LANCZOS` 放大）比整屏识别准；4K 屏全屏 OCR 会把字糊成一行。
- `tsv` 的坐标可直接喂 `xdotool mousemove x y click 3`，用来自己点一次那个控件。

## 3. 进程真在干什么（决定性，一眼拆穿“两个进程”）
```bash
py-spy dump --pid <pid> | head -40
```
- 主线程栈只有 `paintEvent → <画图函数>` ⇒ 这个进程没在跑业务，只在重绘。
- 栈里出现 `debugpy/adapter/launcher` ⇒ 它是 VSCode 起的调试进程。
- 树里出现 `state_space_sim/engine` ⇒ 它真的在跑引擎（而不是“界面有数”就等于在跑）。

## 4. 启动环境到底有没有进进程
```bash
tr '\0' '\n' < /proc/<pid>/environ | grep -E 'ZMAX_|PYDEVD|OMP_NUM'
tr '\0' ' '  < /proc/<pid>/cmdline      # 有没有 -X frozen_modules=off
```
`launch.json` 写了不代表进了进程；**只有 /proc 是事实**。全空 ⇒ 先去查 launch 模板是否把文件重写回去了。

## 5. 谁在写活真源（区分“常驻服务在跑”与“我的进程在跑”）
```bash
ls -l --time-style=+%H:%M:%S <live_dir>/*.json      # mtime 距今多久、哪个最鲜
sudo lsof <live_dir>/<file>.json                   # 谁打开的
```
文件在更新 ≠ 你的进程在跑。常见误判：`engine_latest.json` 是常驻服务写的，GUI 不写它（GUI 只写播放态/轨迹）。
判“GUI 有没有自己跑引擎”要看 GUI 侧产物（记账文件、它自己的日志行），不是这个文件。

## 6. 记账文件：回答“这个函数被调用了吗、哪个 pid”
在函数入口（放在被测逻辑之前、且不影响关键函数的行号）追加：
```python
with open(os.path.join(ROOT, "ss_live", "<who>_calls.log"), "a", encoding="utf-8") as f:
    f.write("%s pid=%s tag=%s\n" % (time.strftime("%H:%M:%S"), os.getpid(), tag))
```
读法：
- `wc -l` → 一轮调用多少次（一轮 369 次说明引擎真的在跑）
- `awk '{print $2}' | sort -u` → 是哪个 pid（与你 `ps -o lstart= -p` 对齐就是你的进程）
- `tail -3` → 最近是什么时候

🔴 `ROOT` 一定要按文件**真实目录层级**上溯并回读验证；少一层就写到不存在的目录，被 `except: pass` 吞掉，
得到“代码在、日志永远空”的假象——排查代价极高。写完先造一次真实调用证明文件真的产出。

## 7. 两个进程 vs 一个进程的典型形态
| 现象 | 真因 |
|---|---|
| 界面有数据、帧龄几秒，但断点永不进 | 常驻服务在跑业务；GUI 只显示 |
| 界面写“未运行”，但有数 | 数是别人写的（服务/上一个进程），不是它 |
| 启动时停一次，之后再运行不停 | 兜底断点用“只停一次”去重，或整轮跑完落在时间窗内 |
| 右键运行节点什么都没发生 | 轨迹取不到就中止 / 节点执行的 except 静默吞 |

## 8. 「取消断点后再添加就不进」= 模块没有 loader

这是与"代码没执行"完全不同的故障: **第一次能停、取消再添加就不进**。机制不是行为, 是绑定:

| 加载方式 | `__spec__` / `__loader__` | 首次绑定 | 取消后重新添加 |
|---|---|---|---|
| `exec(compile(src, path, "exec"))` | 都 None | 按 `co_filename` 能命中 | **没有 loader 可重新定位 ⇒ 静默不绑** |
| `spec_from_file_location` + `sys.modules[name] = m` | SourceFileLoader | 命中 | 命中 |

所以「为了断点能绑上而改成 exec」是反向操作 —— 它买到了首次绑定, 弄丢了重新绑定。

正确写法（三处加载器统一: 引擎 `runtime._load` / `sim._load` / 注册表 `_ss_import`）:
```python
spec = importlib.util.spec_from_file_location(mod_name, path)
m = importlib.util.module_from_spec(spec)
sys.modules[mod_name] = m      # pydevd 按模块名解析文件; dataclass 也查这里
spec.loader.exec_module(m)
```
`exec(compile())` 只保留为降级分支, 且**必须打印告警**（"无 __spec__, 断点取消/重加会失效"）。

验收（一条命令跑完四项）:
```python
m = _ss_import('execution')
print(m.__spec__ is not None, type(m.__spec__.loader).__name__, 'state_space.execution' in sys.modules)
print(m.RobotExecutor.execute.__code__.co_filename)   # 必须与文件绝对路径逐字相同
```
只要 `__spec__` 为 None, 就别再浪费轮次重启 —— 先把加载方式改对。

## 9. 让 GUI 自己跑一轮（否则断点无处可停）+ 什么算"停对了"

调试进程若只在重绘, 代码永远跑不到断点。调试档（`ZMAX_DEBUG_MODE=1`, 由 launch env 带入）下让 GUI
启动后**自动跑一轮引擎**, 是让"有代码在跑"不依赖用户记不记得点 ▶ 运行的可重复做法:
- 主窗口是**异步建好的** ⇒ 用 1s 轮询找"带运行入口的窗口实例"再调, 不要一次性 `singleShot` 就假定窗口已存在
  (`topLevelWidgets` 常在 `app.exec_()` 之前还拿不到; 换成遍历 `app.allWidgets()` + 重试上限)。
- 留逃生口 `ZMAX_AUTO_RUN=0`; 自动跑只属调试档, 不能推广成"打开就自动播放"。

"停对了"的三条硬指标（缺一条就別说改好了）:
1. 记账文件多出一批行, pid == 调试进程 (`tail` + `awk '{print $2}' | sort -u`);
2. 一轮的调用次数是**几百量级**（引擎逐步调用）而不是 1 次;
3. 停住时 VSCode 高亮的是"下一条语句" —— 因此 `_brk()` 在 `a = np.asarray(...)` 上一行停住, 界面看起来
   像停在普通赋值行。用户会问"我没在这行打断点怎么停了", 先把这条讲清楚。

## 10. UI 断点永不进 = 调试进程根本不执行这段代码 (先 py-spy 对栈, 别改代码)

症状: VSCode F5 起来, 断点打在 `execution.py` 的 `RobotExecutor.execute` 函数体, 一直不停;
而页面/数据/`ar_cmd.json` 一切正常。

实测事实链 (550B, 2026-10-30):
- VSCode 调试的是 `tools/gui/studio.py`(launch「🚀 全新调试进程」)。`py-spy dump` 主线程只有
  `paintEvent (orbital_arch.py:1145) ← main (studio.py:16679)`, **全程没有 state_space/execute** —— GUI 只在重绘。
- 真正每 100ms 调 `RobotExecutor.execute` 的是 systemd 服务 `zmax-ss-canvas-loop`
  (`tools/ss_canvas_loop.py`), 栈 = `main(ss_canvas_loop.py:110) → project.step → node.step → compute`;
  `zmax_data/ss_live/canvas_loop.json` 里 `ssact` 每拍 `status=实现执行`。
⇒ 断点挂在了**不执行该代码的进程**上。改代码/改加载方式都是白做。

判据 (两条栈都要读):
```bash
PS=$(ls -d ~/.hermes/tools/python-3.14*/bin/py-spy | head -1)
sudo -n "$PS" dump --pid <VSCode调试进程传studio.py的那个> | head -20
sudo -n "$PS" dump --pid $(systemctl show -p MainPID --value zmax-ss-canvas-loop) | head -20
```
调试进程用 `/proc/*/cmdline` 找 `debugpy/launcher ... -- <program>`, 别用 `ps|grep 名字`。

修法 (三选一, 按"用户要不要在 IDE 里看红点"定):
1. **VSCode UI 断点**: `.vscode/launch.json` 加一条 `program=tools/ss_canvas_loop.py`, env 抄 unit 的
   `ZMAX_CANVAS_ONLY / ZMAX_CANVAS_HZ / ZMAX_UPH_AR_PUB / ZMAX_YOLO_SHARE`(已加为「🧪 断点 · 状态空间常驻循环」)。
   🔴 启动前 `sudo systemctl stop zmax-ss-canvas-loop`, 否则两个进程同时写 `ar_cmd.json`、AR 页面也会被旧进程冻住; 测完 start 回去。
2. **不动服务**: 命令行 pdb(见 §11), 立刻能停, 不打扰在役循环。
3. **「我都给你调好、我看着」= 交一个 attach 就绪的进程**(用户这句话的语义是**别再让他按步骤操作**):
   stop 服务 → 用 `python -m debugpy --listen 127.0.0.1:5678 <loop.py>` 起(模板 `scripts/run_canvas_loop_debug.sh`,
   env 逐条抄 unit) → 只告诉他 attach + 哪一行。🔴 **不要加 `--wait-for-client`**: 那会把进程卡在第一行,
   产物停更、页面冻住, 他看到的第一个现象就是"画面卡了"; 不加则进程正常 10Hz 跑, 5678 一直可连。
   交付前**自己先连一遍**证明能停(`scripts/dap_probe_breakpoint.py`), 他只需按 F5。
   ⚠ debugpy 一次只服务一个客户端, 但**断开后可重连** —— 探针退出后 5678 仍在听, 不影响他随后 attach。

## 12. 用 DAP 探针自证"断点真能进"(不依赖 IDE、不依赖人点)
```bash
./gui-venv311/bin/python scripts/dap_probe_breakpoint.py \
    --path /abs/repo/src/lerobot/policies/left_right/state_space/execution.py --line 111
```
输出即证据链: `setBreakpoints verified=true` → `event stopped reason=breakpoint` → 调用栈逐帧
(`execute:111 ← run:55 ← node_ss_exec:2788 ← compute:84 ← step:104 ← main:110`) → 现场变量。
拿到这段再回答"修好了没有", 别拿"代码改了/服务重启了"当证据。

四个 DAP 协议坑 (都实测踩到, 写探针/读日志时直接对上):
1. **`attach` 的 response 晚到**: 实测它排在 `setBreakpoints`/`configurationDone` 之后才回来。
   用 `wait_response(attach)` 阻塞等在原地 ⇒ 超时退出、什么都没验到。
   定式: attach **不阻塞等响应**, 直接往下发请求, 以 `event stopped` 为唯一成功判据。
2. **StackFrame 的字段是 `id`, 不是 `frameId`** (`frameId` 只是 evaluate 请求的参数名)。
   取 `f["frameId"]` ⇒ KeyError, 而栈已经打印出来了, 很容易误以为"这个协议拿不到变量"。
3. **停在哪一行决定变量在不在**: 停在 `def` 行时形参未绑定、停在首句之前时局部变量未赋值 ⇒
   `evaluate("a.shape")` 回 `success=false`。这是**行号选错的信号**, 不是变量接口不通。
4. 🔴 **探针异常退出 = 被测进程可能停在断点上不恢复**: 不发 `disconnect{terminateDebuggee:false}`,
   进程就冻在断点, live 产物(如 `ar_cmd.json`)停更, 用户看到的是"页面卡住了";
   探针必须 `try/finally` 发 disconnect, 跑完再核一次产物 mtime 是否恢复。

## 11. pdb 打动态加载的模块: 相对文件名会 not found, def 行读不到参数

- `b execution.py:59` → `*** 'execution.py' not found from sys.path`。该文件在
  `src/lerobot/policies/left_right/state_space/`, 由 `_ss_import` 按绝对路径加载, 从不在 sys.path。
  ⇒ 必须绝对路径: `b /home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py:111`。
- 行号坑: **109 是 `def execute(self, u):` 本身**, 停在那里参数未绑定(`p u` → NameError, 看着像"没进函数体");
  要打 **111**(函数体第一行 `a = np.asarray(u, dtype=float).ravel()`)。
- 停对了的样子(实测):
```
> .../execution.py(111)execute()
-> a = np.asarray(u, dtype=float).ravel()
(Pdb) p u            → array([0., 0., 0., 0.])
(Pdb) p self._LIMIT  → 1.0
(Pdb) p self.max_rate→ 0.35
```
⚠ `tools/dbg_actuator.py` 的 ctx 为空 ⇒ `u` 恒 0。这是"停住 + 能读参数"的证明, 不是真实指令; 要看真指令
用 launch 配置跑常驻循环(白名单带 sslimit/ssact, ctx 里有上游 u_sat)。
- `_ss_import` 的 `except Exception` 会吞 `BdbQuit`(调试器退出信号) 并降级成 `exec`, 日志
  `⚠️ _ss_import spec 加载失败: BdbQuit → 退回 exec`; 断在模块加载期后按 q 就会触发, 属正常路径, 但一旦走了 exec 分支,
  取消/重加断点又绑不上(见 §8)。用 `b <abs>:111` 打函数体可避开在模块加载期停住。
