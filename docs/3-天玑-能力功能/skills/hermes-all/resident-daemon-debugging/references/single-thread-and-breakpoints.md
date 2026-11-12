# 单线程(550B) + 断点全覆盖 实操口径

## 一、功能逻辑单线程: 只走一条通道
- 真源开关: `nodes/_single_thread.enabled()` (读 ZMAX_SINGLE_THREAD / ZMAX_MULTI_THREAD)。
  `thread_policy.single()` 只委托它, 不要在别处再造第二套判断。
- 新代码别再裸写 `threading.Thread(...).start()`; 用 `lerobot.engineering.thread_policy.spawn_or_inline(name, fn)`:
  单线程 ⇒ 当场同步跑完并返回 None (断点恒在 MainThread); 多线程 ⇒ 起同名线程并返回 Thread。
  单线程下若被从非主线程调用, 它会打一行红字并记进 `report()["violations"]` —— 这就是"严格执行"的痕迹。
- 已改的 3 处重量级节点: `library.py` ss_yolo_detect / ss_vlm, `smolvla_lew_l3.py` l3-smolvla。
  单线程下 YOLO/VLM 变同步: 一拍从 ~30ms 变 ~200ms+, 这是单线程档的代价, 不要"优化"回去。
- 允许保留线程的只有: Qt/渲染/WebEngine/相机取流/DDS·relay 传输/`engine/ss3d_live.py` 推流。
  线程清点里那条 `Thread-1 (_post)` 就是 ss3d_live 的推流发布线程, 不是节点逻辑, 汇报时点名别含糊。

## 二、严格执行 = 开关钉在入口脚本里, 不靠 systemd / shell
- 只给 unit 加 `Environment=ZMAX_SINGLE_THREAD=1` 不算严格执行: 换入口 (手跑 / 另一份 unit / F5 / 子进程)
  就漏。做法是在**功能逻辑入口脚本**里, 于 **`from lerobot...` 之前** 自钉:

  ```python
  if os.environ.get("ZMAX_MULTI_THREAD", "").strip().lower() not in ("1", "true", "yes", "on"):
      os.environ["ZMAX_SINGLE_THREAD"] = "1"
  ```

  本仓钉在 `tools/ss_canvas_loop.py`、`tools/ss_engine_loop.py`、`tools/ss_skill_dispatch.py`;
  GUI 侧 `tools/gui/studio.py` 更早 (启动即 re-exec 补 env)。留 `ZMAX_MULTI_THREAD=1` 作 550A/550C 压测出口。
- **必须在导入推理栈之前**: torch/cv2/OMP 的线程数在 import 时定, 导入后再改 env 没用。
- 🔴 **灌 env 的那段别用 `if ZMAX_SINGLE_THREAD != "1"` 当门**: 启动器 (launch.json/F5) 已经设了 SINGLE 时
  整块被跳过 ⇒ OMP/OPENBLAS/MKL/GDAL 的线程数从来没进进程, 现场表现是"明明开了单线程档, 线程还是有二三十条"。
  门只该看 `ZMAX_MULTI_THREAD != "1"`, 其余用 `os.environ.setdefault` (用户显式设过就不覆盖), 最后再强制
  `ZMAX_SINGLE_THREAD="1"`。

### 验证"入口真的自钉了"(不解释器启动服务)
把文件里**钉开关那一行为止**的代码头单独取出, 注入 `__file__` 后用**干净 env** 跑子进程, 打印环境变量与线程数:

```python
pin = next(i for i, ln in enumerate(src) if 'os.environ["ZMAX_SINGLE_THREAD"] = "1"' in ln)
head = "".join(src[:pin + 1]).replace("from __future__ import annotations\n", "")
probe = "from __future__ import annotations\nimport os\n__file__ = %r\n" % ap + head + \
        "\nimport threading\nprint(os.environ.get('ZMAX_SINGLE_THREAD'), threading.active_count())\n"
# 两个环境各跑一次: ①剔掉 ZMAX_SINGLE_THREAD/MULTI_THREAD/FUNC_THREADS ②加 ZMAX_MULTI_THREAD=1
```

判据: 干净 env ⇒ `SINGLE='1'`; 给了 `ZMAX_MULTI_THREAD=1` ⇒ `SINGLE=None`。两条都成立才算钉住。
坑: 探测脚本里 `import os` 不能放在 `from __future__` 前面, 否则 `SyntaxError: from __future__ imports must
occur at the beginning of the file`; 入口脚本用 `__file__` 推仓库根, 探针必须先把 `__file__` 赋成真实路径。

## 三、核验工具 (证据判据, 不看文档)
- `tools/verify_single_thread.py [--write]`: ①静态扫功能逻辑目录的裸线程(必须 0, 白名单 ss3d_live 除外);
  ②单线程模式真跑一拍, 逐节点记录执行线程(必须全 MainThread); ③线程清点。报告 `reports/single_thread_audit.json`。
- `tools/verify_node_breakpoints.py [--exec-all] [--write]`: 79 节点逐个判 PASS / NEED-INPUT / SUBPROC / SKIP / FAIL-NORET。
  判据 = **真跑命中的 return 行**, 不是"文档说这里有断点"。
- `--exec-all` 会加载重模型 (一拍 16~25s, 线程仍 3~4 条), 内存紧时别连跑两次 (工具机 ≈8GB, 超则 OOM)。
- 四种"不算坏"的结论要分清: NEED-INPUT = 该分支要真图/真轨迹/标定; SUBPROC = 跑在子进程脚本里 (在那边下断点);
  SKIP = 审计主动跳过重模型; 只有 FAIL-NORET 是真问题 (落点错)。

## 四、FAIL-NORET 的根因与修法
- 现象: 文件执行了, 但"右键打开"落到的函数这条路径根本不调用 ⇒ 断点永不命中 (例: sssched 指
  cognition.ActionModulator.advance, 实际跑 library.node_ss_s3)。
- 修法: `tools/fix_breakpoint_landing.py --apply` —— 取该节点 real_returns_hit 的行, 写回 `_EXTERNAL_LOC[key]`
  (无映射的补一条, 键名用报告的 `key`, 显示层就是按这个键查)。8 条 FAIL-NORET → 0, PASS 44 → 52 (exec-all 下 54)。
- 外层函数名要取**最外层**那个 (target 落在闭包里时会取到 `_ret` 这类内层名, 报给用户等于没报)。
- ⚠️ 陷阱: `_EXTERNAL_LOC[...]` 有多行元组写法, 正则 `^_EXTERNAL_LOC\["k"\]\s*=.*$` 只吃第一行会把续行留成
  IndentationError。改完必须 `py_compile` 并 grep `^\s+[0-9]+, "def ` 查残骸。

## 三·五、目标口径 = 恰好两条 Python 线程 (主线程 + zmax)
- 老倪口径: 「就两个线程。MainThread 是 GUI, zmax 是工程线程」——不是"1 条", 是这 2 条。
- 实现: `tools/gui/zmax_thread.py` (单例 `zmax_thread`): `start()` / `submit(fn)` / `every(key, 秒, fn)`。
  主线程只做界面与绘制; 一切周期活/阻塞 IO 排进 zmax 线程顺序跑, 结果用 `_oneshot` 回主线程。
- 单线程档 (`ZMAX_SINGLE_THREAD=1`) 已被改造掉的线程源: WebEngine AR 预载(≈33 条, 改成点 🥽AR 才建)、
  canoe 采样 3 源+话题目录 4 条(改成点「▶采样」才起)、YOLO 预热/ultralytics 遥测 2 条、tqdm 1 条、
  orin 状态轮询(单飞)、状态灯 QThread + status_panel QThread + model_engine 取数 QThread(全改 zmax.every)、
  信号监听(改 zmax 线程上 select 0 超时单拍)、warm_ssh(改 submit)。
- 判定证据: 用 sitecustomize 钩 `threading.Thread.start` 记创建栈 + 定时 dump `threading.enumerate()`;
  目标是 dump 里**只有** MainThread/zmax(自建探针 Timer 也会出现在列表里, 别误判)。
- ⚠️ 启动播报会被"启动静音"吞掉: 屏幕上看不到自己的 print, 必须去 `/tmp/zmax_boot.log` 里 grep。
- ⚠️ `/proc/<pid>/environ` 是 execve 时的快照, 运行时 `os.environ[...] = ...` 不会出现 —— 别用它判断"env 没被设上"。
- ⚠️ ultralytics 遥测线程: 关 `~/.config/Ultralytics/settings.json` 的 `sync=false` (代码里改 `Events.__call__` 太晚,
  包 `__init__` 导入阶段就已经发过一次)。

## 三·六、"断点还是不进" ⇒ 查两件事: 连线有没有, 节点有没有真执行

断点在技能 `clamp` 的 `return` 上却永不命中, 与线程无关, 而是**连线/执行脱节**。两条必查:

1. **连线缺失**: 画布上 `sssskill`(L3 序列编排) 只连了 `sssk2~sssk8`, 漏了 `sssk1`(① 接近) ⇒
   「接近」那条支路在设计图上就不存在, SK01 一拍都不跑。判据一行:
   ```python
   ins = {t: [l['f'] for l in d['links'] if l['t'] == t] for t in ('sssk1',...)}
   ```
   修: 直接给 `data/database/zmax/sources/canvas/state_space_obs.json` 补 link (`f=ssskill,t=ssskN,
   f_port=out1,t_port=in1`), 改前 cp 备份; 补完把 `sssk1 上游` 打出来核。
2. **节点只回放不执行**: `node_ss_atomic` 原来只按引擎轨迹打「激活/待命」日志, **不调 `clamp`** ⇒
   线连着、数据没流、断点不进。修法 = 节点激活时走统一调用口:
   ```python
   import dispatch_inproc as _dpi           # tools/ 已在 sys.path
   _gate = _dpi.step_stage(stg, np.asarray(u[:3], float))   # 真调 atomic_skills.<SKxx>.clamp
   ```
   `Dispatcher.step_stage()` 里先 `_activate(st)`(单一在职) 再 `_phys()`(过闸), 于是
   **连线 = 执行 = 断点** 落在同一行; `dispatch_inproc` 记 `node_ts`, 同拍 `tick()` 自动让位, 不会二次过闸。
   验收(不用开 GUI): 假 module 给 `_ss_tr={t,stage,target,u_exec_vec}`, 调 `node_ss_atomic(ctx)`,
   判据 = 打出 `⚖ 过闸 → |u|=… 削因 …` 且 `d.n_gate_skill==1`。
3. 在职技能还跟着规划块段号走时, 块一卡就永远卡在同一个技能 (实测停在「插入」)。`_state_stage()` 用
   视野点(hand/光模块/hole)+夹爪指令按 d_xy/dz/夹持判 8 段, 连续 2 拍一致才切, 视野过期就退回块段号。
4. **控制链根本不经过技能类** —— 这是"所有技能的 return 都不进"最常见的一条。本仓有三条出动作的路,
   每条都要单独证:
   - `ActionModulator.decide()`: 原来只在 `ZMAX_L2_GATE=1` 时调 `limiter.limit()`, 默认 0 ⇒ 走等比缩放,
     SK01-08 的 clamp **一拍都不执行**。
   - 模型直驱 `_direct_act → env.step(act)`: 整条绕开调制与技能 (L4/INTACT 直驱档默认就走这条)。
   - 画布节点 `node_ss_atomic`: 只回放日志, 不调 clamp (见上条 2)。

   **修法 = 一个公共口 + 三处调用**: `ActionModulator.skill_step(u_req, stage=None, token=None)`:
   按当前段取技能类 → 真调 `clamp` → 记 `skill_calls[st]` → 结果写 `self.gate`; 是否采用技能输出由
   **另一个开关**决定 (默认 0 ⇒ 返回 None, 调用方动作逐位不变; 实测 GATE=1 会让接近段变慢卡段
   ⇒ 未证明提升不进默认档)。调用点: `decide()`、直驱 `env.step(act)` 之前、
   `dispatch_inproc.step_stage()` (画布节点)。
   🔴 **token 去重**: 引擎主循环开头写 `self.sched._skill_tok = step`, `skill_step` 同一 token 第二次调用
   直接返回 ⇒ 否则 decide 与 env.step 两处都过闸, 技能行程/削因一拍记两次 (实测 119 次 / 60 步)。
   验收: `tools/debug_run_engine.py --steps 120` 末行 `合计 120 次 / 步数 120`; insert 全链 348 步段次
   接近→…→完成, 与改前 150 步段序完全一致 (改行为才算回归, 只加执行不算)。
5. 段名与技能类名不一致也会漏: STAGES[11]=「放下」(摆盘链 PLACE_IDX), 类声明的是「放入」⇒
   `skill_for('放下')`=None, SK07Place 永不执行。修法: `SKILL_BY_STAGE.setdefault('放下', SKILL_BY_STAGE.get('放入'))`。
   「完成」是终止段 (done 后直接 break), 不调 SK08 —— 别当成 bug 追杀。

## 三·七、调技能/引擎断点: 用「引擎直达」脚本, 不要跑 GUI

GUI 跑一轮 5~9 分钟 (建窗口/加载模型/建模), 调技能断点时时间全浪费在别处。定式:

1. **写一个无窗口入口** (`tools/debug_run_engine.py`): 组路径 (仓库根 + `src` + `tools` + `tools/gui`)
   → `os.chdir(tools/gui)` (metaworld 资源按该目录找) → `RealStateSpaceSim(seed, vision=False, mode)`
   → `run(max_steps)` → 末尾打印 `sched.skill_calls`。`--steps` 默认 120 (insert 全链约 348 步走完);
   日志用 `--quiet` 关掉, 断点调试时终端只留自己的输出。
2. **`launch.json` 加「第二条」配置**, 第一条 (整个 GUI) 原样不动 —— F5 默认跑第一条, 重排等于换掉用户
   按 F5 会起的程序。直达配置: `program` 指该脚本, `pythonArgs=["-X","frozen_modules=off","--steps","120"]`,
   env 带 `ZMAX_SINGLE_THREAD=1` / `MUJOCO_GL=egl`。写完回读 json 并核两个 program 路径都存在。
3. **判据不看界面**: 末行 `skills clamp 调用次数 {接近:26, 对位:31, 下降:63} 合计 == 步数` ⇒ 每步恰好一次
   = 技能真在链路里; 合计是步数的 2 倍 ⇒ 两处调用点都过闸、token 去重失效。
4. **断点行号每次改文件都要重算** (ast 扫 `ClassDef → clamp → 第一个 Return.lineno`), 并把行号表随结论
   一起给用户 (SK01≈417 / SK02≈527 / SK03≈638 / SK04≈749 / SK05≈859 / SK06≈970 / SK07≈1082 /
   SK07Place≈1199 / SK08≈1309 —— 只作对拍起点, 不信旧值)。
5. **pdb 硬验证** (与 VSCode 同一套行断点机制):
   `python -m pdb -c "b <abs>:<line>" -c c -c "w" -c c tools/debug_run_engine.py --steps 60 --quiet`
   输出 `> …atomic_skills.py(<line>)clamp()` 且栈含 `runtime.run → cognition.skill_step → clamp` 才算"能停"。
   🔴 **判据是帧名 `clamp()`, 不是 `<listcomp>()`**: `return {"u": [float(x) for x in u_out], …}` 这种行里
   的推导式是**独立 code object**, 首行号与 return 同号 ⇒ 断点先命中 `<listcomp>` 帧, 用户看到的就是
   "技能 return 的断点全都不进" (而且这个现象**跟线程、跟在哪下断点都无关**, 改成纯语句才消失)。
   真修法 = 把推导式提到 dict 之前, 让断点那一行属于函数体:
   ```python
   _u_list = [float(x) for x in u_out]      # 纯语句, 在 clamp 帧里
   _v_list = [float(x) for x in u_req[:3]]
   _e_list = [float(x) for x in err]
   _out = {"u": _u_list, "v_req": _v_list, "err": _e_list, …}
   return _out                              # 断点下在 _out = { 这一行
   ```
   9 个技能类一次全改 (同一个 OLD 文本块 `s.replace()` 计数应为 9), 改完 `py_compile` + 重算行号表再给用户
   —— **行号会整体后移, 旧行号上的红点全部失效**, 必须明说。

## 三·八、自检会碰到真机执行器, 要说明
- 跑 `verify_*` 真拍时 `ssact` 会调 `RobotExecutor.execute()` 并打印「🤖 机器人执行器 (真实)」,
  同时往 `zmax_data/ss_live/actuator_calls.log` 追加一行 —— 这是**只读记录**, 真下发仍只走 l2_daemon + 8793 授权。
- 汇报时必须点名: 哪次自检碰了执行器, 位姿真值有没有变 (latest.json 时间戳不变 = 没有真运动)。

## 三·九、断点折腾到最后: 先用“执行落盘”把两种失败分开

用户反复说"还是进不去"时, 不要再口头保证, 也不要在调试器配置上继续改 —— 先让**代码自己写证据**:

```python
# 技能/节点的公共口 (本例 ActionModulator.skill_step) 里, 真执行成功就 append 一行
with open(os.path.join(LIVE, "skill_calls.log"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"t": round(time.time(), 3), "pid": os.getpid(), "stage": st,
                         "cls": type(sk).__name__, "tok": token,
                         "why": r.get("why"), "err_mm": round(float(r["err_norm"]) * 1000, 3)},
                        ensure_ascii=False) + "\n")
```

跑完一次只看两个数就能分流:
- **有行** ⇒ 代码真执行了, 问题在断点位置/调试器 (去改行号、帧、launch 配置);
- **没行** ⇒ 那条控制路径根本没走到这类代码 (去查开关/直驱/连线), 调调试器是白费。
汇报时把行数对拍报出来: `20 步 = 20 行 · pid 2516579 · 全是 SK01Approach` 这种数字才算证据。

### 三个会让上面这些机制静默失效的坑
1. **仓库根不能靠单个目录名上溯**: 本仓 `src/` 下也有个 `zmax_data` ⇒ 循环遇到第一个含 `zmax_data`
   的目录就 break, 实际落在 `src/zmax_data/ss_live/` (不存在) ⇒ 日志一行没写、`except: pass` 又吞掉异常,
   现场表现还是"断点不进"。要求**同时**有 `src` + `tools` + `zmax_data` 才算根; 算完打印真实路径核一次。
   同一原则适用于任何"上溯找仓库根": 标记要组合, 不能单名。
2. **写证据的分支不许 `except: pass`**: 路径算错 + 静默 = 把"写失败"伪装成"代码没执行"。至少落一行日志
   或让异常可见; 没日志时先用 `ZMAX_<X>_LOG_PATH=/tmp/x.log` 显式指定路径跑一次, 能写就说明是路径算错。
3. **`pkill -f` 会杀掉自己这条 shell**: 模式字符串只要出现在**本命令行任何位置** (
   比如同一条命令后面还跟着启动该进程的命令行) 就会自匹配 ⇒ `exit -15`, 看起来像"工具/终端坏了"。
   括号写法 `pk[ ]ill -f "pat[.]tern"` 只能防模式本身自匹配, **防不住字面量出现在同命令行其它位置**。
   最稳: 按端口/pid 停 (`ss -ltnp | grep <port>` 拿 pid), 或把 kill 单独发一次。

## 三·十、用户说「你给我配好 / 停止在断点上 / 全程你操作」时的交付边界

先把能做到与做不到分清楚, 否则只能反复说"配好了"而断点不进:

1. **行断点必须由调试器下发**。这版 debugpy 没有 `PyDB.set_break`, 进程内也没有公开 API 能替 VSCode
   点一行: `debugpy.breakpoint()` 只能触发一次中断, 而且**停在调用它的那层包装帧**, 不是目标函数。
   所以交付 = ①把**当前**行号算准给他 (ast 扫, 改一次文件就重算一次) ②用 pdb 硬验一次真能停
   ③告诉他下拉选哪条、按 F5。**不要承诺"我替你下好了断点"**。
2. **能在屏幕上留一个真停住的现场** (用户要"停止在断点上"时最直观): 在 `:0` 上起一个带标题的终端跑 pdb,
   它就会停在 `(Pdb)` 提示符等人:
   ```bash
   DISPLAY=:0 setsid gnome-terminal --title="<项目> 断点 (<类>.<方法>:<行>)" -- bash -lc \
     'cd <repo> && <venv>/bin/python -m pdb -c "break <abs>:<line>" -c "continue" -c "where" <跑一次的脚本>; exec bash'
   ```
   核实用的是**进程状态**而不是窗口标题: `grep ^State /proc/<pid>/status` 为 `S` 且跑到加载完之后仍不退出
   ⇒ 正停在提示符; `DISPLAY=:0 wmctrl -l` 里能看到那个标题 ⇒ 窗口真在他屏幕上。
3. **先证"有没有真的在跑"再改任何配置**: `wmctrl -lp` 拿到界面窗口的属主 pid 与标题 —— 标题写着
   「未运行 / 点 ▶运行」就是**业务一次没跑**, 此时任何断点都不可能进; 进程 `lstart` 早于文件 mtime 就是旧代码。
   两句话就能把用户从"断点坏了"拉回"还没点运行 / 跑的是旧进程"。
4. 用户问「你到底执行了么」= 他要的是**我这边跑出来的数与行**。给一条可复现命令 + 它的真实尾部
   (`合计 120 次 / 步数 120`、`> …atomic_skills.py(424)clamp()`) + 落盘日志的行数/pid, 不要讲过程。

## 六、"还有 N 条线程" —— 怎么量、怎么归属、哪些搬不动

用户拿 Call Stack 里的线程数说话时, 不要回"已经是单线程了", 直接给**实测前后数字 + 每条来源**。

### 6.1 量
```bash
ls /proc/<pid>/task | wc -l                                   # 条数
for t in /proc/<pid>/task/*; do cat $t/comm; done | sort | uniq -c | sort -rn   # 名字分布
```
反复采样 (离屏起 + 每 6s 采一次 + 结束杀掉) 用 `scripts/measure_threads.sh <脚本> <秒数>`,
能同时得到"启动期"与"稳态"两个数。

🔴 **必须量一个跑着新代码的进程.** 用户屏幕上那个进程的 `lstart` 早于你改完的文件 mtime ⇒ 他看到的永远是旧数,
他会说"你还是没改啊"。报数前先 `ps -o lstart= -p <pid>` 与 `date -r <改动文件>` 对一下; 要对得上就离屏起一份新的来量,
并把"我量的是离屏新进程, 你手上那条要重启"写在结论里。

🔴 **`/proc/<pid>/environ` 是 execve 那一刻的快照, 运行期 `os.environ[...]=...` 不会出现在里面。**
拿它判"pin 有没有进进程"必然误判 (env 里查不到 ≠ 没生效)。要证 env 生效, 打印进程内
`threading.active_count()` 或让代码自己打一行生效证据。

### 6.2 归属每一条 (Python 线程)
用 `PYTHONPATH` 注入一个 `sitecustomize.py`, 包住 `threading.Thread.start` 记栈:

```python
import threading, traceback
_orig = threading.Thread.start
def start(self):
    with open('/tmp/thread_spawn.log', 'a') as f:
        f.write("\n=== %s\n" % (self.name or 'unnamed')); f.write("".join(traceback.format_stack()[-10:]))
    return _orig(self)
threading.Thread.start = start
```

取每块里**最后一个落在本仓库**的帧 = 创建点 (行号可直接改)。C 层线程 (OMP/CUDA/Qt/Chromium) 不会出现在
这份日志里 —— 那本身就是"不是我代码起的"的证据。

### 6.3 Qt/GUI 的地板与隐形大头
- 空 `QApplication` = **2 条** (MainThread + QDBusConnection), 灌好 OMP 等 env 也还是 2。
- `import PyQt5.QtWebEngineWidgets` **不建线程** (必须在 QApplication 之前 import, 别因此以为它贵);
  **建一个 QWebEngineView 才贵**: +约 33 条 (Chrome_IOThread / NetworkService / VizCompositorTh /
  sandbox_ipc_thr / ThreadPool ×4 / inotify_reader / VideoCaptureThr …)。
- `--single-process --no-zygote` **不是优化**: 实测 41 条 > 默认 39 条, 还多 AudioThread/Compositor。别试。
- 隐形大头是**启动时的自动 prewarm**: 建一个隐藏 WebEngine 窗口做预热 ⇒ 用户没点那个页面, 进程也背着
  整套 Chromium。改成"第一次点才建"(`ZMAX_AR_PREWARM=1` 保留回退) 后 45 → 17 条, 功能不受影响,
  代价只是首次打开多约 1s。
- `Thread (pooled)` 是 Qt 线程池; `python:traceq0/gdrv0/sh0/disk$0` 是 libiomp 内部线程, 首次并行区之后常驻。
  torch / numpy 单独实测 `OMP_NUM_THREADS=1` 都只 1 条 ⇒ 见到这些线程说明是**别的库**开的池, 不是 env 没设。

### 6.4 定时轮询别叠加线程
`_refresh_xxx()` 每次都 `Thread(target=_work).start()` ⇒ 慢网时同刻挂 3~4 条。改**单飞**:
`if getattr(self, "_busy", False): return` / `finally: self._busy = False`, 稳态最多 1 条。
同理, 一进页面就 `_autostart()` 起 3~4 条采样线程的页面, 在单线程档改成"点按钮才起"。

### 6.5 汇报口径 (用户要的是数, 不是形容词)
- 给 **before → after 实测条数** + 按来源分类的清单 (Qt 自身 / CUDA / libiomp / 我们的 polling / 已干掉的大头)。
- **两个数分开报: Python 线程 vs OS 线程.** VSCode Call Stack 只列 Python 线程; `/proc/<pid>/task` 数的是 OS 线程
  (还含 Qt 的 QDBusConnection/QXcbEventQueue、libiomp 的 traceq0/gdrv0、CUDA 驱动、Qt 线程池)。目标口径 = **Python 线程恰好 2 条**
  (MainThread + zmax), OS 层十几条不算违约 —— 混着报会让用户以为没改。
- 只有**第三方 C 运行时**线程搬不动 (torch/cv2/Qt 在进程里 import 就有), 归属为"我们的 polling"那些必须清零。
  别再答"要真 1 条只能把推理栈搬出 GUI"—— 那是没量清楚之前的话; 2 条是够的。
- 生效需要重启控制台: 说清"你手上这条是旧进程", 不要替用户重启 GUI (只可停不可起)。

### 6.6 周期刷新不许用 subprocess (用户的下一句就是"怎么有 subprocess")
GUI 里每 2s/5s/60s 刷一次的取数, 常见写法是 `subprocess.run([sys.executable, "tools/x.py", "--json"])`。
后果: 调试器里多出 python 子进程、断点跟随、`ps` 里一片 python。改法 = **同进程函数调用 + zmax 线程**:

| 原命令 | 改成 |
|---|---|
| `tools/status_lights.py --json` | `import status_lights; status_lights.collect()` |
| `tools/model_inventory.py --json` | `import model_inventory; model_inventory.build()` |
| `tools/remote_monitor_aggregate.py --json` | `import remote_monitor_aggregate as m; m.collect(m._build_catalog())` |

前提是脚本已经暴露 `collect()/build()`; 没有就先把它拆出来 (脚本 `main()` 只负责 argparse + 打印)。
QThread 形态的取数器统一改法: 把 `run()` 的循环体抽成 `poll_once()`, 单线程档不 `start()`, 改
`zmax_thread.every(key, 秒, poll_once)`, 结果仍写回原来的队列供主线程的 QTimer 消费 (界面路径不动)。
以命令列表为参数的通用控件 (LiveStrip/LiveTable 这种) 要加**可调用分支**: `cmd` 可以是函数, 结果经
`pyqtSignal(object)` 回主线程 (`data_ready.emit(...)` 跨线程是安全的, 历史崩溃是跨线程析构 QObject 不是 emit)。
一次性子进程可留 (权重重载); 但要在**调试会话里跳过** (如 `ZMAX_AUTOLOAD_IN_DEBUG=1` 才跑), 否则用户一按 F5
就看见它。

### 6.7 "还是跳" = 周期任务在调试器眼皮下停站
线程数与"跳"是两个问题: 即使只剩 2 条, 工程线程每 2s 停一次, 单步时调试器就从 MainThread 切到 zmax。
做法: 工程线程主循环每拍先判 `sys.gettrace() is not None` (pydevd 在场即有 trace) ⇒ **整段跳过周期任务**,
只保留用户手动触发的队列任务; 再给 `ZMAX_ZT_IDLE=1` 作显式开关。判据: 调试会话里单步不再被拉走,
非调试运行时周期活照旧 (状态灯时间戳仍在刷新)。
