---
name: resident-daemon-debugging
description: "Use when 调试常驻 FIFO/daemon 或 10Hz 循环, 断点不命中或进程停不下。"
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [debugging, daemon, fifo, vscode, debugpy, zmax]
    related_skills: [real-arm-motion-control, live-service-change-discipline, systematic-debugging]
---

# 调试常驻服务 / FIFO 执行器

## 触发
- 在常驻进程（FIFO 消费者、看门狗、推流服务、信号库守护）里下的断点**不停**。
- 用户问「我怎么 debug X.py，断点放哪里」。
- 需要看执行分支/中间量，但**不能停进程**（在跑生产动作）。

## 铁律

1. **断点只绑定到"加载了同一文件的那个调试进程"**。按 F5 起的往往只是 GUI/主程序，常驻服务是另一个
   plain-python 进程 ⇒ 断点永远不命中。判断方式:

   ```bash
   for p in /proc/[0-9]*; do cmd=$(tr '\0' ' ' < $p/cmdline 2>/dev/null);
     case "$cmd" in *<文件>.py*) echo "${p#/proc/} $(ps -o lstart= -p ${p#/proc/})"; echo "  ${cmd:0:160}";; esac; done
   ss -ltnp | grep -E '5678|5679'      # 无监听 = 没有调试会话
   ```

   命令行含 `debugpy/launcher … -- <file>` 才是被调试的进程。

2. **在常驻进程上停下 = 冻住它**，而下游（机械臂、推流、队列）按上一条指令继续。要下断点只允许两种场合:
   离线台（不读生产输入、不下发）或强制 dry 的分离实例。

3. **分离实例必须分开三样东西**: 输入通道、单实例锁、输出日志。只换输入不换锁 ⇒ 新实例会按
   "新实例赢"的锁策略把线上实例 SIGTERM 掉（这是防多实例抢 FIFO 的设计，不是 bug）。

4. **改完代码必须重启服务，断点才有意义**（运行中的进程是旧代码，行号与逻辑都可能对不上）。

5. **生产实例上只取证，不下断点**: `tail` 日志（含原始日志尾）、服务自己的回执接口、
   `py-spy dump --pid <pid>`（不暂停进程）。

## 断点静默不绑: 动态加载的节点模块 (2026-10-31 实测)

**症状**: 红点在、代码确实在跑、永远不停, 且无任何报错; pdb 能停、VSCode 不停。

**四个叠在一起的根因**:
1. 模块用 `spec_from_file_location(...).loader.exec_module(m)` 或 `exec(compile(...))` 直装 ——
   绕开 `builtins.__import__`, pydevd 的导入钩子看不到该文件, 编译期不注入断点;
   本机 debugpy 又没编 `_pydevd_frame_eval/*.so`, 运行时补绑也失效。
2. `_EXTERNAL_LOC` 把"右键源码"指到 **class/def 头那一行** —— class 体只在 import 时执行一次,
   断点永远不中。用户看到的就是"我右键进来的这段代码不运行"。
3. **显示层还会拿符号串自己再搜一遍**: `sourceview.get_node_location` 读到映射后, 又用
   `行首 startswith(symbol)` 搜**第一处** `def`/`class` 并覆盖行号 ⇒ 只把 `_EXTERNAL_LOC` 的行号校准到 return
   **完全无效**, 右键永远弹回函数头。修法: 映射行号落在函数体内就直接用它; 不在才按符号找定义、再取该函数
   第一条 return。改完必须**在真进程里现取一次**判据: `sourceview.get_node_location(key)` 返回的必须是 return 行。
4. 同一个 key 的 `_EXTERNAL_LOC` 在一份文件里**可能写了好几遍**, 后一条静默覆盖前一条 ⇒ 改前面那条是死改动。
   改之前先数: `grep -c '_EXTERNAL_LOC\["<key>"\]'`; 重复的只保留最后一条 (运行时口径), 其余删掉。

**修法**:
- 加载统一走 `lerobot/engineering/modload.py::load(name, path)`: 先 `importlib.import_module`
  (自动探 sys.path + 注册别名, 名字≠文件名也能解析), 失败才退 spec 并打印原因;
  兜底时记进 `SPEC_LOADED` 台账, 验证工具据此判"这个文件绑不上"。
- `tools/fix_node_source_loc.py --apply`: 用**真执行行**记录把落点改到该节点实现函数的 return 行。

**批量替换 spec 三行块的坑**: 原块通常是 `spec = spec_from_file_location(...)` 紧跟
`m = module_from_spec(spec)`, 下游全用 `m.xxx()`; 机械替换只改首行 ⇒ `spec` 成了模块对象而下游仍用 `m`
⇒ NameError, 而节点实现外面普遍 `except Exception → 直通`, 现场表现是"节点没执行、连日志都没有"。
每个块替换完都要核对**变量名与下游一致**(`m`/`qc`/`bm`/`_m`), 再 `py_compile` + 真跑一拍。

**终端必须有模型台账** (用户问的是"到底加载了没"): 每个模型真加载后打一行
`[模型] L2 YOLO 目标检测 ← <路径> · 存在=是 · 6.2MB · 加载 OK · 0.14s · 类别 …`;
统一用 `lerobot/engineering/model_log.py::note(layer,name,path,ok,detail,elapsed)`, 同一 (层,名,路径) 只打一次,
**失败也打一行带原因**, 不许静默。

**验证工具** (改完必跑):
- `tools/verify_node_breakpoints.py --write` → 每节点: 打开位置、该文件是否真被执行、return 命中数
- `tools/model_ledger.py` → L2/L3/L4/L5 每个模型真加载一行台账 (存在?/大小/耗时/参数量/设备)

逐节点全量审计的循环、判定分类 (PASS / NEED-INPUT / FAIL-NOTRUN / FAIL-NORET / SUBPROC / SKIP) 与验收口径见
`references/node-breakpoint-audit.md` —— 用户要求“每个节点都验证好”时直接按那份跑, 别用单点采样交差。

**辅助坑**: 部分节点会 `QWidget()` —— 无 QApplication 直接 SIGABRT 审计进程;
验证脚本开头要 `QT_QPA_PLATFORM=offscreen` 并建一个 `QApplication` 实例。

## 断点下错副本: 同一段代码按分段复制了 N 份 + 单射在职调度

**症状**: 用户贴出自己下断点的那段 `return`, 说"这就是唯一的一段代码, 为什么进不了这个断点"。

两个成因通常同时成立, **两个都要证**: ①这段代码在文件里被**复制**了 8~9 份(一类一份), 而调度每拍只调
**在职**那一个类的 `clamp()`, 其余类"沿用上一拍结果、不重算" ⇒ 断点落在非在职副本上**一行都不执行**;
②真正执行的那个**进程**未必是用户 F5 的那个 —— 先量一量: `/proc/<pid>/cmdline` 里 `grep -c pydevd` = 0 就不是
被调试的进程。取"现在哪一份在跑": 读实时状态文件的在职标志(`skill_phys.json` 的 `在职 == 1`, 龄 <1s)。

**派发宿主已改为"状态空间进程内"(独立派发器停用)**: 技能派发现在是 `tools/ss_canvas_loop.py` 每拍内调
`dispatch_inproc.tick("ss_canvas_loop")` ⇒ 想让断点命中, **F5/attach 的对象就是这个画布循环进程**;
独立 `tools/ss_skill_dispatch.py` 单元已 stopped+disabled, 且脚本本身在无 `--once`/`ZMAX_DISPATCH_STANDALONE=1` 时
**打印"已停用"并 exit 0** —— 所以「找不到那个独立进程」是预期, 不是环境坏了，更不要为了调试把它重新拉起
(那会把双写者、断点永不命中的老毛病一并拉回来)。单拍看结果用 `--once`。
⚠️ 读到 `canvas_loop.json` 的 `dispatch` 字段为 `null` 时别判"没在派发": 同一份状态文件可能被**旧代码的**
第二份画布循环 (例如用户早先 F5 那个) 最后落盘。真判据是 `skill_phys.json` 帧龄 <1s + 宿主日志首行
`🧩 技能派发: 本进程内每拍派发 SK01~SK08 (pid N)`。

**交付口径**: 回答"为什么进不了这个断点"必须同时给 **哪一份副本**(类名 + 当前 return 行号) 与
**哪个进程**(pid + pydevd 计数), 再给一条能真停的命令 —— 只给一样等于没答。
命令与判读: `references/breakpoint-not-hitting.md` §1c。

## 断点不命中的完整分诊链（按顺序跑，每步都能独立证伪）

“断点不进”有四层原因，**先证进程，再证代码，最后才改配置**。跳过前两层去改 launch/env，会陷入
“改配置 → 让用户重启 → 还是不进”的死循环（本项目连改五轮 launch/env/加载方式都没解决，真因是第一层）。

### ① 代码跑在哪个进程（最常见）
GUI 显示“未运行 / 没点 ▶ 运行”，而 `ss_live/engine_latest.json` 的 mtime 每 0.1s 在刷 —— 刷新者是
**systemd 常驻服务**，不是用户 F5 起的 GUI。断点打在 GUI 进程里 ⇒ 永不可能命中。

```bash
systemctl is-active <loop 服务名>
python -c "import os,time;print(round(time.time()-os.path.getmtime('zmax_data/ss_live/engine_latest.json'),2))"
tail -3 zmax_data/ss_live/actuator_calls.log     # 节点入口写的「时间 + pid」
```

正向取证: 在节点入口加一行**每次调用 append 时间+pid** 的日志（本仓 `zmax_data/ss_live/actuator_calls.log`）。
判读要带一条限制: 这种埋点只覆盖**走那个入口**的路径。引擎里常见的直连调用
（如 `u_vec = self.execr.execute(u_sat)`）根本不经过节点实现文件 ⇒ **日志为空不等于 execute 没被调**，
只能证明“那个入口没走”。要证“函数真被调过”，用 py-spy 棨或在该函数自己里埋点。

**同一个埋点文件里 pid 一直在变 = 节点在“每次新的进程”里跑** (点一次运行/单步起一个子进程, 或每次 F5 一个新
debuggee)。此时断点绑在哪个旧会话上都不会命中; 对策是让调试配置**直接 launch 节点宿主脚本**
(本仓 `tools/dbg_actuator.py`: 只跑一拍指定节点就退出), 而不是 launch GUI/常驻服务。
带真输入也在这里解决: `ZMAX_DBG_U="0.12,-0.05,0.30,0.0"` 注入 u_sat, 否则停在 execute 里看到的全是 0。
注意节点顺序: 先跑 `sslimit` 会重算 u_sat 把注入值覆盖成 0, 要喂真指令就**只跑 `ssact`**。

**py-spy 读到的那条栈不一定是“F5 起的那个程序”**: debugpy 的 `--multiprocess` 会把它派生的**子进程**也挂上
调试器, 子进程 cmdline 同样是 `pydevd.py … --file <子脚本>`。GUI 启动时后台线程拉起的 `model_autoload.py`
就这样被当成主调试进程 (实际 GUI 本体是父进程, 栈应在 Qt 事件循环里)。认主调三条, 别只看一条:

```bash
for p in /proc/[0-9]*; do c=$( { tr '\0' ' ' < $p/cmdline; } 2>/dev/null ) || continue;
  case "$c" in *pydevd*|*debugpy*launcher*) echo "${p#/proc/} ppid=$(awk '{print $4}' $p/stat)";
    tr '\0' '\n' < $p/cmdline | tail -2;; esac; done   # 启动器 cmdline 尾部路径 = 真正 launch 的 program
wmctrl -lp | grep -i <GUI 标题>          # 窗口属主 pid = GUI 本体
sed -n 's/.*pid=\([0-9]*\).*/\1/p' zmax_data/ss_live/actuator_calls.log | sort | uniq -c | sort -rn | head
```

三条读数合起来才下结论: “目标 pid 在调用日志里计数 **0**” ⇒ 这个进程从没执行过该节点, 断点放它上面毫无意义;
历史上出现过的十几个 pid 说明节点宿主一直在换 (GUI 各版本 / 常驻循环 / 单次脚本), 所以调试配置要指向
**会执行该节点的那个入口**, 而不是“当前开着的任何 GUI”。

**F5 默认跑 launch.json 的「第一条」**: 列表顺序就是默认行为。按模板重生成 launch.json (条数从 1 变十几条)
等于把默认程序换掉, 用户按 F5 会多起一个他没想到的进程。要让断点落在本次任务上, 就把那条配置放**列表第一位**,
其余位置不动; 然后回读 (`json.load` 打印条数 + `names[0]`) 报给用户, 别只说“加好了”。

要它跑: 先停常驻服务，再在界面点 ▶ 运行/右键运行节点。不想每次靠人记得点，就在调试模式下
**启动自动跑一次业务代码**（本仓 `ZMAX_DEBUG_MODE=1` 时 GUI 建完窗口后调一次仿真启动函数，
`ZMAX_AUTO_RUN=0` 可关）—— 这是把“断点不进”真正关掉的那一步，只改配置永远到不了。
窗口往往是**异步建好**的，所以用 QTimer 每秒轮询 `app.allWidgets()` 找带目标方法的实例（上限约 60 次），
一次性 `singleShot` 会在窗口存在前就执行并落空。
验收口径: 自动跑后日志里出现 `[brk:<tag>] 到达` 或 py-spy 栈里出现该函数。
调试完把常驻服务 start 回来（`sudo systemctl start <loop 服务名>`），别让生产循环一直停着。

**“界面在跑、但跑的是回放”= 技能链一次都没走 (最隐蔽的一层)**: 画布数据源是「操作视频同源 episode」时,
▶运行 走的是回放计划, **不经过 `sched.decide → skill_step → clamp`** ⇒ 技能断点永远不停, 而画面/日志全“正常”。
十秒判据: `zmax_data/ss_live/trace_live.json` 的 `src` 写着 `操作视频同源 episode … N 步` 且帧数在涨,
同时 `skill_phys.json` 帧龄很老、`skill_calls.log` 里没有该 GUI pid 的计数 ⇒ 是回放。
**同一形态的第二种分支: 数据源 =「AR场景」** —— `start_sim()` 的 `_ar_src` 分支只写
`zmax_data/ss_live/ar_play.json`(`{"action":"start","by":"simulink.run","src":"AR场景"}`) 并播双臂动画,
引擎同样一次不跑、技能一次不调。切回引擎分支的落法: 画布 JSON 里 `ssdata.params.src_state` 要是「插拔场景」,
再用命令通道 `ss_canvas` 重载画布(它 `open_state_space()` 重读文件) → 隔几秒 `ss_run`。
回答顺序固定为
**当前数据源是回放还是实时 → 回放不经过决定层 → 技能不执行 → 断点无对象**, 别把它说成“断点没绑”。
驱动本仓 GUI 走命令通道 `/tmp/zmax_nav_cmd`(`ss_canvas`/`ss_run`/`mparam`/`ds_win`/`ov_page`/`open_all` …),
别盲点坐标; 两个坑(同文件写 `ss_canvas`+`ss_run` 会抢跑、`ss_run` 按档位/数据源分流)见
`references/vscode-debug-session-driving.md` §6~§7。

### ② 这个进程此刻在干什么
```bash
sudo py-spy dump --pid <pid>
```
MainThread 栈只有 `paintEvent → _sphere` 这类绘制代码、没有任何 `run/execute/step` ⇒ 进程里没有节点在执行
（同时它 `active+gil` 还在持续算，界面反而显得“有数据在动”，最具误导性）。栈里出现 `pydevd_*` 线程是调试器
自己的，不要误判。

**栈里出现 `socket.connect → httpcore → huggingface_hub.list_repo_tree → from_pretrained` ⇒ 不是断点问题, 是调试会话
在启动阶段就卡在拉权重/网络**。这一拍根本没走完 ⇒ 后面的节点(含你要停的那个)永远轮不到, `actuator_calls.log`
里也就没有它的 pid —— 表现和“断点没绑”一模一样。先证网络再谈断点:

```bash
curl -m 6 -so /dev/null -w '%{http_code}/%{time_total}s\n' https://huggingface.co   # 000 = 不通
ss -tnp | grep <pid> | grep SYN-SENT                                                # 卡在 TCP 握手
```

修法: 调试配置的 `env` 加 `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`（离线只读本地缓存, 跳过 `list_repo_tree`
那次网络调用）。实测对比: 离线 `AutoProcessor` 0.14s、VLM 507M 权重 0.6s, 在线则一直挂住。
验收: 用同一组 env 手动跑那条循环 60~90s, `actuator_calls.log` 出现**该进程自己的 pid**（每拍一条）
⇒ 那一拍真走完了, 断点才有目标; 只有先确认“这一拍走完”, 才有资格说“断点绑不上”。

**“一直加载 / 日志刷屏”先查共享源文件有没有被每拍重写**: 无条件的调试 print 每拍一条只是表象, 放大器是
消费者每 N 秒判定“源文件变了”就整份重载（模型/配置/节点全重建）⇒ 每拍都打印, 看起来永不停止。判据:
`stat -c %Y <源文件>` 连续采样几次 + `ls -t <归档目录> | wc -l` —— mtime 每几秒变、归档数每拍 +1 ⇒ 有写者
在**每拍整份重写**。修法: 写回幂等（值没变就只改内存、不落盘、不归档）, 调试打印挂到训练态或 env 开关
（如 `SS_L3_DEBUG=1`）; 归档爆量时保留最近 N 份即可（本项目曾堆到 1.4 万份 / 1.9G）。

**幂等判据必须把时间戳字段从“比较双方”都剔掉**（含嵌套的 `loaded_at` / `*_at`）。只把顶层
`m_loaded_at` 排除、或只在一侧归一化, 都白搭: 只要比较里还带着“写入时刻”, 值永远算变 ⇒ 每拍照样落盘,
循环照样重启。判据不看代码看行为: 同一循环跑 40~50s, 日志里“加载画布/重载”只出现 **1** 次、目标文件
mtime 不动、备份文件数不涨, 三条同时成立才算修好。

**“循环卡住了”先证伪, 别急着修**: 常驻循环多数只在启动/加载/报错/节点自己打印时输出, 修完刷屏问题后
它会变得**一片安静** —— 安静被当成卡死是误判。硬证据是循环自己落的状态文件 (本仓
`zmax_data/ss_live/canvas_loop.json`: `tick` / `cost_ms` / `budget_ms` / `traces[].ms` / `err`) ——
`tick` 在涨、帧龄 <2s ⇒ 在跑; 再配 `py-spy dump` **隔 2~3s 采 2~3 次**:
栈在变(不同节点/HTTP/json.dump) ⇒ 在跑; 连续几次同一行 ⇒ 才叫挂住。判定完再决定修什么。
配套改进是给循环加**心跳行** (每 ~5s 打 `💓 tick=N · Xms/预算Yms · K 节点`), 让终端永远不可能看起来冻住。

**终端只剩「… N 行已省略 (全量: /tmp/xxx.log)」= 节流器在干活, 不是日志丢了**: 本仓 `tools/loop_quiet.py`
把 stdout 限速 (每秒 N 行 + 每 10s 一行省略统计), 全文原样落 `ZMAX_LOOP_LOG`。默认值在**代码里是 "0"**
(`os.environ.get("ZMAX_LOOP_TERM_LINES","0")`) ⇒ 终端一行都不放、只剩统计行，看着像输出被吞；
而同一文件的 docstring 写着「默认 2」—— **以代码为准**。判读三步: ① `grep -c '行已省略' <全量日志>` 应为 0
(0 = 一行未丢) ② `wc -l` + 体积给底账 ③ 要看就 `ZMAX_LOOP_TERM_LINES=2`(限速) 或 `ZMAX_LOOP_VERBOSE=1`(全关)。
汇报给两个数（每秒放几行、全量在哪个文件），不说"日志被截断了"；用户追问"这些省略干啥呢"= 那行统计本身没信息量，
正解是把统计换成有内容的摘要（本拍阶段/速度/偏差）而不仅是改行数。

**每拍重扫真源是节拍杀手**: 每拍都读 8 个配置 + 重算 sha 的节点实测占 85ms/拍 (预算 100ms) ⇒ 循环
一直“超节拍”。按 `(路径, mtime_ns, size)` 签名 + 短 TTL (2s) 缓存, 文件没动就复用上一次结果 ⇒ 同一节点
降到 0.4ms。凡是在 `10Hz` 循环里跑的“读文件/算哈希/扫目录”都按这条处理; 改完用状态文件的 `traces[].ms`
逐节点报耗时, 别只报总耗时。**共享库 (sqlite 工程库/工单库) 别把 mtime 放进签名**: 别的进程 (GUI/工单)
一直在写它, mtime 每次都变 ⇒ 判永远是“变了” ⇒ 照旧每拍整轮重扫 (实测 80ms 尖峰只出现在 db 被写的那些拍)。
签名里对这种库只比 `size`, 真正的内容查询单独给 5s TTL 缓存。

**重节点各自节流, 别让两个重节点撞同一拍**: 偶发超节拍的典型形态是“每 N 拍超一次” —— 一个重节点按固定周期
真算一次 (其余拍回放缓存), 那一拍再撞上另一个 20~40ms 的节点就破预算。给第二个节点也加同款节流:
`ZMAX_<X>_PERIOD_S` + 缓存回放 (返回上次结果并附 `cached_ago_s`), 下游每拍照样有值, 尖峰即消失。
加之前先看 `traces[].ms`, 确定峰值那一拍到底谁占大头, 别凭猜。

**单次 40~200ms 的重推理可以挪后台线程, 光靠“每 N 拍一次”不够 —— 但只限多线程档**: 🔴 前提是
`ZMAX_MULTI_THREAD=1`。550B 单线程档**禁止**把推理挪线程: 必须走 `thread_policy.spawn_or_inline()` 当场同步算完,
否则实现跑在 worker 里、断点在主线程永远不停、下游拿的还是上一拍结果。单线程的代价 (一拍 30ms → 200ms+) 要认,
不要拿本节去“优化”回来。开关钉法/验证配方/审计口径见 `references/single-thread-and-breakpoints.md`。
多线程档做法: YOLO/sam3 这类推理即使每 0.5s 才真跑一次,
落到那一拍照样破预算 (显存被别的进程抢时更久)。做法: 主线程只做便宜部分 (env.render / 取帧 ≈10ms),
推理交给常驻单线程, 本拍返回**上一帧**结果 + `cached_ago_s`; 冷启还没有任何结果时同步算一次, 保证下游第一拍有值;
后台线程内异常必须自己接住 (存进状态字段), 绝不让它冒到主循环。分工底线: **渲染/环境留在主线程** (mujoco/PIL
跨线程有风险), 只有纯推理进线程。验收: 该节点 `traces[].ms` 均值 26ms → ~1ms、总超预算次数 → 0。

**目标频率总是差几个百分点 ⇒ 查 pacing 的结算口径, 别查节点**: `dt = 1/HZ - cost` 若 `cost` 只量了 `step()`
的墙钟, 每拍杂项 (keepalive 续期 / 心跳打印 / 写状态文件 ≈7ms) 就不在预算里 ⇒ 10Hz 恒跑成 9.3Hz, 而逐节点
`traces[].ms` 全部在预算内, 从节点耗时才永远发现不了。改成按**整拍墙钟**结算: 迭代开头取 `t_iter = monotonic()`,
结尾 `dt = 1/HZ - (monotonic() - t_iter)`。验收用状态文件 `tick` 增量 ÷ 墙钟算 Hz (别数心跳行, 5s 才一行)。

**测节拍/耗时前先证只有一个实例**: 同一循环起两份 (用户 F5 一份 + 自己测试一份) 会同时写同一份状态文件 ⇒
tick 增量翻倍, 读出 65Hz 这种荒唐值; 两份还抢同一块 GPU, 推理尖峰更凶。
`ps -eo pid,lstart,cmd | grep "[t]ools/<loop>.py"` 列全, 只留一份再采样; 报数时说明是“干净单进程”窗口。

**判“超节拍”要统计, 不能看心跳散点**: 心跳每 ~5s 才打一拍, 恰好没抽到尖峰就会出现“心跳 0 次超节拍、
实际一成拍超标”的自相矛盾读数。口径: 按拍采样状态文件 (注意 `STATE_EVERY` 决定它每 N 拍才写一次, 只能代表抽样),
报 **均值 / p95 / 最大 / 超标拍数** 四项; 重推理节点 (YOLO / sam3) 偶发 3~5 倍尖峰先查争抢 ——
`nvidia-smi --query-compute-apps=pid,used_memory` 配上 `ps -o cmd= -p <pid>` 映射出占卡进程, 显存接近打满时
推理耗时会跳变, 那不是循环逻辑的问题。

**心跳超标时直接点名**那一拍最贵的两个节点 (`⚠️ 超节拍 ← ssyolo 56ms · ss_mani_eng 38ms`);
只写“超节拍”用户下一句必然是“怎么超的”, 又得回去采样猜。

**“循环在跑但还是空转”= 执行链末端 u_sat 恒为 0, 不是循环问题**: tick 在涨、检测有结果、执行器每秒被调,
但 `u_sat=[0,0,0,0]`, 现场就是“一直在循环、什么都不动”。三个成因按概率排:
1. **白名单漏了写共享状态的那个节点**。执行器读的是共享态里的 `u_sat`
   (`robot_actuator_impl.py: u_sat = _SS_STATE.get("u_sat", np.zeros(4))`), 而全仓只有安全限幅节点写它
   (`safety_limit_impl.py: _SS_STATE["u_sat"] = …`)。白名单 (`ZMAX_CANVAS_ONLY`) 少写这一个 id ⇒ 默认零走遍全链。
   修: 白名单里补上该节点 id, 且**同时改 `launch.json` 与生成它的模板** (`simulink_module._vscode_launch_cfg`),
   否则用户下一次右键「打开源码」就被模板覆盖回去。挑白名单的正确顺序 = 按数据依赖倒推“谁写我读的字段”, 不是挑看着重要的。
2. **模型加载失败被永久熔断**。策略加载失败时若写成“失败即熔断、后续拍不再试”, 一旦这次失败是环境性的
   (显存被占满 ⇒ `RuntimeError: CUDA error: out of memory`), 之后显存空出来也永不恢复, u 恒 0。
   修: 熔断改成**冷却重试** —— 记 `failed_t`, 隔 `<X>_RETRY_S` (默认 60s) 再试一次, 保留强制重试 env。
3. **两个循环实例抢同一块 GPU**。8G 卡上两份循环 (各 ~2.3GB) + 分割/检测常驻件 (2.3GB) ⇒ 显存打满 ⇒ 策略加载 OOM。
   单实例时显存从 7717MiB 回落到 3056MiB, 策略 5.6s 加载成功。

**“这一秒真算出了什么”要每秒打一行, 只靠心跳用户会判成空转**: 心跳只证明“节拍在走”, 不证明“产物在变”。
在循环里每秒汇总一次并打印, 例如 `✅ 1s: 检测 3 点 · frame=world · 执行器 1 次 · u=[0.03,-0.09,-0.18,0.01]`;
数据从本拍 `traces[]` 的 payload 里取, 缺字段打 `—` 不造假值。判据: u 每秒在变 = 链路真在干活; u 恒 0 ⇒ 按上面三条查。
并行的取证是模型台账里有没有 `未加载/失败 → …` 那一行 —— 两条一起看才能立刻分清“没算”还是“算了但没下发”。

**常驻循环没有“跑完”语义, 用户必然问“怎么还在检测 / 没完没了”**: 10Hz 循环默认永不停, 别只解释设计。给三个开关并写进 launch 配置与模板: `ZMAX_LOOP_MAX_TICKS=N`(跑够 N 拍退出, 0=无限)、`ZMAX_LOOP_EVIDENCE=0`(只留心跳)、`ZMAX_L2_PERIOD_S`(检测周期)。**退出不许用裸 `return`**: 解释器正常退出会去析构 mujoco/EGL 与后台推理线程 ⇒ `FATAL: exception not rethrown` + dumped core ⇒ 先 `sys.stdout.flush()` 再 `os._exit(0)`(Ctrl+C 用 `os._exit(130)`)。验收: `ZMAX_LOOP_MAX_TICKS=30` 跑满打印结束行、退出码 0、日志 0 次 core。

**“为什么检测这么久”先分项计时再回答, 别凭推理耗时猜**: 稳态单次 ≈ reset 6ms + render 8ms + detect_3d 10ms + 2D 框 4ms = 28ms; 冷启首帧 ~600ms(render 150 + detect_3d 448, CUDA/渲染上下文初始化, 只一次)、aligner 就绪 ~2s。用户体感的“慢”通常是**节流周期**(默认 0.5s ⇒ 2Hz, 其余拍回放缓存), 不是推理本身; 周期降到 0.1s 实测该节点均值 10.6ms / 峰 29ms, 仍装得进 100ms 预算。

**“反复执行”多数是时间驱动的节拍规划, 不是死循环**: 规划节点按 `elapsed_s` 推段(每件 ~50 段 / 11.47s, UPH~314), 不按到位事件推进 ⇒ 一件走完接下一件、永远循环。别争辩, 把 `段N 标签 · t=…s · 件K` 打进每秒证据行, 让“在推进”自己可见(实测 33s 内 段21→段28→件2 段1→…→段50→件4)。真要“走完就停”得另做一次性执行(起点/终点/到位判据/结束信号)。

**循环里跑的模型/节点要能被用户按需降频或关掉**: 交付时把可调项(节拍 HZ、检测周期、证据行、最大拍数)一次性告诉用户, 并说明各自的取值与后果; 用户连续问“太慢 / 没完没了 / 为什么这么多”往往是**没有控制面**, 不是参数值不对。

### ③ 断点本身（三个机械陷阱，都与“断点有没有坏”无关）
- **行号漂移**: 反复编辑同一文件会把函数整体后移几十行，用户留在旧行号上的断点落在注释/空行 ⇒
  解释器**根本不会设置它**（pdb 只回 `*** Blank or comment`），界面红点还在、跑起来永不停。
  交付时必须报**当前** `def` 行与第一条可执行语句行，并明说“旧断点已失效”。
- **launch.json 被 GUI 自己整份重写**: 手改 `.vscode/launch.json` 加 env，用户下一次右键「打开源码」就被
  模板函数覆盖回默认（本仓模板在 `simulink_module._vscode_launch_cfg`）。要加 env 只能**改模板再让模板重生成**；
  判据是起进程后读 `/proc/<pid>/environ` 与 `cmdline`，不是看 json 里写了什么。
- **frozen modules**: debugpy 自报 `frozen modules … may make the debugger miss breakpoints`。Python 3.11 起
  必须在 launch 配置里给 `pythonArgs: ["-X","frozen_modules=off"]`（`args` 是给程序的，不生效）+
  env `PYDEVD_DISABLE_FILE_VALIDATION=1`。
- **脚本参数写进 `pythonArgs` ⇒ 调试目标一次都没启动**: `pythonArgs` 是解释器自己的开关位 (`-X`/`-u`)，
  脚本参数必须放 `args`。放错的现场三连: 集成终端只有一行 `unknown option --steps` + usage ⇒ VSCode 弹
  `Timed out waiting for debuggee to spawn` ⇒ `Call Stack` 空但工具栏“重启/停止”还亮(半死会话)。
  这时别去怀疑断点绑不上, 先看集成终端原话; 那个超时模态框会挡住下一次 F5, 先 `Escape` 关掉再重跑。
  字段分工、会话活着/已暂停的判据、替用户操作 VSCode 的约束见 `references/vscode-debug-session-driving.md`。
- **加载器连 `sys.modules` 都没注册**: 连补偿都做不到(pydevd 按模块名定位文件)。但注册上也**仍然不够** ——
  见下一条“动态加载”。同一仓库常有的模块注册了、有的漏了, 逐个核, 别假设“同一个 repo 的加载方式都一样”。自查:
  `python -c "import sys;sys.path.insert(0,'src');<触发一次节点>;print('<模块名>' in sys.modules)"`。
- **模块是“动态加载”的（不是 `import` 进来的）= 该文件里断点必然静默失效**: `spec_from_file_location`
  + `loader.exec_module(m)` 与 `exec(compile(...))` 都**绕开 `builtins.__import__`**，pydevd 的导入钩子
  看不到这个文件 ⇒ 编译那一刻不注入；debugpy 没编 frame eval（下一条）⇒ 运行时也补不上。表现: 红点在、
  跑起来永不停、函数照跑不报错。**注册 `sys.modules[name]` 救不了** —— 那只让 pydevd 按名找到文件,
  不触发注入。判据（最快）: 加载后打印 `type(Obj).__module__` —— `state_space.execution` 这种 = 走的动态
  路径, 断点不会绑; `lerobot.policies.left_right.state_space.execution` 这种 = 走正常 import, 能绑。
  修法: 加载器改成正常 import —— `sys.path` 里放 `src/`, `importlib.import_module("<pkg>.state_space.<mod>")`,
  再把旧名登记成别名 `sys.modules["state_space.<mod>"] = m` 给按旧名取模块的代码用; 同时把“运行前清模块
  缓存”那处的前缀列表补上新名（否则清不到）。改不了加载器就在**静态 import 的调用点**下断点:
  本仓 `src/lerobot/engineering/nodes/robot_actuator_impl.py:55` (`u_vec = _ex.execute(...)`),
  停在那里能看 `u_sat`(入参) / 走一行拿 `u_vec`(出参) / `_chk`(校验结论), 与进入 execute 等价。
- **debugpy 没编译 frame eval**: `find <debugpy>/_vendored/pydevd/_pydevd_frame_eval -name "*.so"` 为空
  ⇒ `PYDEVD_USE_FRAME_EVAL=NO` ⇒ **不能对已加载模块在运行时加/删断点**，只在 compile 那一刻注入。
  对策: 每次运行前清模块缓存（`library._SS_MODS` 与 `sys.modules` 里的 `state_space.*`/`ss_real.*`）
  强制重编译，新断点在编译时被注入；代价几十 ms。两个入口都要清: ▶运行 与 右键运行节点。

### 断点命中频率 ≠ 顺序执行 (用户会拿"一个反复进、一个总不进"来质疑)

同一进程里节点按拓扑序逐个跑, **不代表两个函数被调用的次数一样**: 命中频率 = 调用点个数 × 宿主节拍。
- 例: `safety.saturate()` 被画布节点 `sslimit` 每拍调一次 (10Hz ⇒ 10 次/秒), 而技能 `clamp()` 只在派发段调、
  且只调**在职**那一个类 ⇒ 表面就是"一个反复停、一个几乎不停"。先数调用点再回答:
  `grep -rn "<fn>(" src/ tools/ | grep -v "def "`, 然后对每个调用点问"它在哪个宿主、什么频率";
  动态侧看产物帧龄/计数 (不涨 = 一次都没走到)。
- 🔴 **把断点放在每拍必经的高频函数上 = 把循环冻成每拍一停**: 10Hz 循环里 `saturate` 断一次就停一次,
  界面/派发全卡住。要停在高频点上必须用**条件断点** (`np.abs(u).max() > 0.6`、`why` 含某条削因),
  或文件开关只记录不停。
- 回答顺序: ①谁在调它 (调用点 + 宿主) ②宿主节拍 ③那个宿主是不是用户正在调试的进程
  ⇒ 三条齐了再谈"为什么进不去"; 只答"你下错地方了"会被继续追问。

### 调试配置默认 = 整个 GUI, 不是常驻循环

用户口径: 「调试的配置, 不要 loop, 要启动整个 GUI」—— F5 起的应是界面本体 (`tools/gui/studio.py`),
常驻循环只是背后一环; 要在界面代码里打断点, 调试器就必须挂在 GUI 进程上。
- **启动口径照抄启动脚本, 不许凭记忆重建**: 读 `tools/gui/launch_studio.sh` 的 `exec` 行 ⇒`cwd=tools/gui`、
  `program=studio.py`、`DISPLAY=:0`、`QT_QPA_PLATFORM=xcb` (脚本先 `unset` 再 `export`: 离屏判据会把 offscreen
  继承下去 ⇒ 进程活着但没窗口)。再加 `ZMAX_SINGLE_THREAD=1` (550B 单线程) + `pythonArgs:["-X","frozen_modules=off"]`
  + `PYDEVD_DISABLE_FILE_VALIDATION=1`。
- ⚠️ **不要顺手加 `ZMAX_DEBUG_MODE=1`**: 它让 GUI 建完窗口再自动跑一遍引擎, 页面建完要 25~36s;
  调界面本身不需要, 要看引擎另用单拍入口。
- **模板与文件必须同时改**: 界面「打开 VSCode」会用模板整份重写 `.vscode/launch.json`, 只改 json 下次就丢。
  两边写完再**逐字段对拍** (`ast.get_source_segment` 取模板函数源码 → 带假 root `exec` → 与 json 比
  name/program/cwd/pythonArgs/env), 并回读 `configs` 条数。
- ⚠️ 用 patch 替换函数体内整段 `configurations` 时, new_string 自带收尾 `],}` 而旧 dict 没一起删 ⇒ 留下悬空块
  ⇒ `IndentationError`; 删完立刻 `py_compile`, 别等 GUI 启动才发现。

### 要“Call Stack 能看出是哪个画布节点”: 改函数真名, 别指望栈能按顺序排

- 中间件节点模块入口全叫 `compute` ⇒ 栈里十几层同名帧, 用户看到的就是“这些函数不是我要的节点”。
  定式: 真名带身份 `def compute_<文件名去前缀>(ctx)` (如 `compute_n_actuator`), 文件末尾
  `compute = compute_n_actuator` 保留接口名 (`Node.compute` 只认 `module.compute`) ⇒ 帧名可读、行为零变化。
  批量改完必须 `py_compile` 全部 + 真跑一拍确认 status 仍是「实现执行」。
- **栈不可能按画布顺序叠**: `Project.step()` 是 `for nid in order` 逐个调, 任何时刻栈里只有当前节点。
  要给顺序就另给: `ZMAX_SS_CHAIN=1` 每拍把序号/节点 id/名称/耗时/状态写 `/tmp/ss_chain.txt`, 与栈顶帧对照。
  别为“栈按顺序”改成节点互调 —— 那是改语义, 不是改调试体验。
- 讲解顺序: impl 内部 (`execute`/`run`) → `node_<id>` → `compute_n_<x>` → `Node.compute/step` → `Project.step`。
  用户说“看到的不是 L2 node 函数”时, 先问断点打在哪个文件, 再按这条链说清他在第几层。

### ④ 验证“能不能停”只有两条硬口径

**别用裸 DAP 客户端去验 `debugpy --listen` 的断点**: 手搓 DAP 客户端会得到 `setBreakpoints → "Server is not available"`
(必须先 attach), 而 `attach` 带 processId 会走 gdb 注入 (`ptrace: No such process`), processId=null 又报
`issubclass() arg 1 must be a class`。这条路径只证明“客户端写错了”, 不证明断点好坏。真要用/接手时三个硬约束:
`clientOS` 必须是 `"UNIX"` (写 `"linux"` 直接 AssertionError 断连)、`--listen` 模式不一定发 `initialized` 事件
(别死等, 3s 软等即可)、`attach` 请求不可省。证书完用下面两条:
```bash
python -m pdb -c "b /abs/path/file.py:LINE" -c c -c "p 变量" tools/<跑一次节点的脚本>.py
```
- 路径必须**绝对**（相对路径匹配不上 `co_filename`），行号必须落在可执行语句。
- 动态 `exec(compile(src, path, "exec"))` 加载的模块 **pdb 能停、debugpy 的 UI 断点未必** —— 两者要分开证，
  别拿 pdb 停住了就宣布 VSCode 也能停。

**进程内没有公开 API 能替 VSCode 下“真行断点”**: 这版 debugpy 的 `PyDB` 只有 `set_break_on_system_exit`,
没有 `set_break` —— 行断点只能由编辑器经 DAP `setBreakpoints` 下发, 别去猜私有 API 或指望进程自己装断点。
能落地的是在目标函数**体里**放一行 `debugpy.breakpoint()` 钩子(先用 `is_client_connected()`/`get_global_debugger()`/`sys.gettrace()` 判空,
没连调试器就立即返回 ⇒ 生产零开销),
停下来的帧就是那个函数本身; 用 wrapper 在外面包一层只会停在 wrapper 帧, Call Stack 差一层。
🔴 `breakpoint()` **绝不能包在 `try/except Exception` 里** —— pydevd 靠抛异常挂栈, 被接住后暂停点落到 `except` 的
`pass` 行(界面显示 `Paused on breakpoint`, 但当前行是 `pass`、帧顶是钩子) ⇒ 用户判成“没停在技能里”。
armed 判定可以带 try, 只有 `breakpoint()` 必须是裸语句。
🔴 加了 `_zmax_bp_armed()` 之类的调用点就 `grep -c "^def _zmax_bp_armed"` 确认名字**真定义了**: 漏定义时
每拍 `NameError` 被上游 `except → 直通` 吞掉, 运行照跑、断点一次不停, 表现与“调试器没接管”一模一样。
钩子会改行号 —— 交付时必须用 AST 重算并报当前行号。见 `references/vscode-debug-session-driving.md` §4。

🔴 **代码里的断点钩子会停在用户根本没点断点的那一行 ⇒ 交付前必须删掉**: 用户看到黄箭头停在自己没下红点的
`_out = {...}` 上, 只会得出"这调试器乱停"的结论 (原话形态: 「这里没有断点, 你怎么还停止?」)。钩子只许当**当轮临时诊断**用:
用完全处删除 (连 `_zmax_bp_armed` 这类辅助函数一起删, 否则 `grep debugpy` 还留着遗迹, 下次谁也不知道哪个还生效),
`py_compile` 通过后 **重启调试会话** —— 运行中的进程握着旧 code object, 不重启照旧停。自证"没有隐藏断点"用**产物连续增长**:
触发一次运行, 调用日志行数一路上涨 (`wc -l` 连采两次递增)、进程 CPU 时间持续累加 ⇒ 代码里确实没东西在停;
随后把暂停权交回用户 —— 只报当前行号, 让他自己在 gutter 点。

兜底断点用**文件开关**而不是 env: `touch <仓库>/zmax_data/ss_live/BREAK` ⇒ 代码里 `os.path.exists()` 无条件
`breakpoint()`。它不依赖 env、不依赖 `debugpy.is_client_connected()`，是唯一能区分“代码没到”与“调试器没接管”的开关。
三个必做:
- **路径层级按该文件实际深度数，不要套别的文件**: `nodes/x.py` 上溯 5 层到仓库根，但
  `policies/left_right/state_space/x.py` 要 **6** 层。套错一层就指到 `src/` 下不存在的目录 ⇒ 开关和记账
  文件全部静默失效。算完立刻打印真实路径核对一次。
- **用完立刻删**: 常驻服务里的同一节点也会被停住，整条循环卡死。
- **写据点的兜底分支不许 `except: pass`**: 路径算错 + 静默吞异常 = 表现成“代码没执行”，排查代价极高。
  至少落一行日志，或让路径算错本身可见。

**默认值必须是“只记录不停”**: GUI 主线程一 `breakpoint()`，Qt 事件循环停转 —— 界面冻结、鼠标点不动，
连新断点都点不了（py-spy 栈顶会显示 `_do_wait_suspend (pydevd.py)`）。代码内置断点只作**显式**通道
（文件开关 / `ZMAX_DEBUG_BREAK`），默认只打印“到达”一行。去重也不能用“一辈子只停一次”的集合 ——
那样第一次停完就永不再停（现场表现为“启动能进、再运行不进”）；要按**运行轮次/时间窗**去重。
要看变量用终端 pdb 通道，GUI 不受影响。

### 交付口径
每次说"改好了"都附**一条可复现命令 + 它的真实输出**。没跑 pdb、没看 py-spy 栈就说"还没验证",
不说"应该能停"。一个未验证的"已修复"被否一次，用户之后会要求把每个结论重新证明一遍。

**用户说"你把 VSCode 配好 / 全程你操作" ⇒ 环境由我配、证据由我跑**, 只把「下拉选哪条配置 + 按 F5」留给他:
① 改写/新增 `launch.json` 后回读条数与每条 `program` 是否存在; ② 用无窗口直达脚本
(`tools/debug_run_engine.py`) 自己跑到"每步恰好一次技能 clamp"; ③ 用 `python -m pdb -c "b <abs>:<line>"`
真停一次, 把命中行 + 调用栈贴给他。不要反过来让用户去点按钮/重启/截图代跑 —— 那不叫"全程你操作"。
⚠️ 用户一旦说「用 vscode, 别用 pdb」: pdb 只能当我这边的内部自证,**不把 pdb 命令丢给他、也不开一个 pdb 终端
窗口当交付物**; 交付证据改成 VSCode 会话本身 (断点行的当前行号 · 集成终端原话 · 会话已暂停的 `/proc` 读数 · 界面截图),
且把他要按的键减到最少 (`Escape` 关残留模态框 + F5)。
配方: `references/single-thread-and-breakpoints.md` §三·七。

**问“到底是不是 X / 别扯蛋 / 说人话” ⇒ 第一句就给结论**（是/不是 + 一句范围或代价），不回顾历史实现
（“以前是 worker 现在改了”这类叙述一律不要），不列备选方案，结尾不加“要不要我…”。
**问哪一块就只答那一块**: 用户问“功能逻辑”时只讲节点/推理/派发的执行线程, 不要把 GUI 线程、systemd 服务、
其他档位扯进来 (多扯一句就会被回“别扯蛋”)。要给边界就一句“GUI 自己那几条不算”, 然后停。
用户把同一个问题问第二遍，几乎都是上一轮答成了背景介绍而不是结论。

命令清单与判据见 `references/breakpoint-not-hitting.md`；单线程档与逐节点断点验收见
`references/single-thread-and-breakpoints.md`（§6 = 线程数怎么量/怎么归属/哪些搬不动；
§三·六~§三·十 = 技能 return 断点为什么不进：控制链绕开技能 · 连线缺失 · return 行里的列表推导
停在 `<listcomp>` 帧 · 用执行落盘日志把“没执行”和“调试器没停”分开 · “全程你操作”时能做到/不能做到的边界）。

**用户说"你还有 N 条线程" ⇒ 先用 `ls /proc/<pid>/task | wc -l` 实测再回答**, 不许用"已经单线程了"顶回去。
两个硬坑: ①`/proc/<pid>/environ` 是 execve 时的快照, 运行期 `os.environ[...]=...` 不会出现 ⇒ 查不到不等于没生效;
②GUI 的隐形大头是**启动就自动 prewarm 一个隐藏 WebEngine 窗口** (≈+33 条), 改懒建那一项就能从 45 降到 17。
量线程/归属创建点的脚本: `scripts/measure_threads.sh <脚本> <秒数>` + `PYTHONPATH` 注入 `sitecustomize.py` 包
`threading.Thread.start` 记栈 (C 层线程不会出现在里面 = 不是我代码起的)。

**目标口径 = 恰好两条 Python 线程** (MainThread 管界面, `zmax` 工程线程跑一切周期活/阻塞 IO; 实现 `tools/gui/zmax_thread.py`
的 `submit()/every()`)。三条总是成立、必须分开报的数: ①Python 线程数 (目标 2) ②OS 线程数 (Qt/libiomp/CUDA 十几条, 不算违约)
③python **子进程**数 (周期刷新写 `subprocess.run([python, tool.py --json])` 的, 一律改同进程 `collect()`/`build()` 调用)。
用户抱怨"还是跳"时, 问题不在条数而在工程线程在调试器眼皮下停站: 每拍先判 `sys.gettrace() is not None` 就跳过周期任务。
配方与归属判据见 `references/single-thread-and-breakpoints.md` §6.1~§6.7。

## 🐢 「节点全打开」后 10Hz 循环卡死 (计算面解锁的回归)

**症状**: 把"吞结果"那类模板坑修好 (或打开 `ZMAX_NODE_PURE_ALL`) 之后, 循环 tick **停在同一数字几十秒**,
`canvas_loop.json` 的龄一路涨, 而 AR/数据空间还"看着有值"(快车道在跑) ⇒ 很容易被误判成"在跑"。

定性顺序不能反:
1. `canvas_loop.json` 的 `tick`/`cost_ms` 是否在涨 (冻结 = 一拍照样卡死; `STATE_EVERY` 决定它每 N 拍才写);
2. `py-spy dump --pid <MainPID>` **隔 2~3s 采两次**: 同一行不动才是卡死;
3. 看栈底那几帧落在哪个节点 (`compute → step → project.step → main`), 不要把"节点在算"当成循环坏了。

**根因是结构性的**: 以前这些节点 `PURE=False` 直通 0ms, 一旦真跑, 单次 0.4~9s 的重节点
(意图解码/技能库/世界模型记忆/YOLO/SAM3/AOI/元任务) 与回路外节点 (验证层的 sim 并行前向、HIL/LLM/Web 的
https 调用 —— 断网时 `getaddrinfo` 卡死, socket timeout 管不住 DNS) 全都挤进 10Hz 拍子。

**修法 = 三档, 都用 env 落地, 可回滚**:

| 档 | env | 语义 |
|---|---|---|
| 每拍核心链 | `ZMAX_CORE_IDS=ssobs,n_geoplan,sssched,sslimit,ssphys,n_moveit,n_exec,ssact,ssworld,…` | 状态→动作→限幅→规划→执行 |
| 每 N 拍全量 | `ZMAX_FULL_EVERY=30` | 保证在役节点不饿死 |
| 永不进循环 | `ZMAX_NODE_PURE_OFF=<ids>` | 回路外 (验证层/LLM/Web/HIL) + 单次 >0.4s 的重计算 |

验收: `cost_ms` 回到预算内 (实测 25s → 15~21ms)、`tick` 每几秒推进、`NRestarts=0`、日志 `Traceback` 0。

**两个必踩的坑**:
- 🔴 `FULL_EVERY` 与 `SLOW_EVERY` 设成同一个数 ⇒ 全量拍再被 SLOW 过滤一次 ⇒ **慢节点永远轮不到**,
  而每拍读数 15ms 看着很健康。要么慢节点单独计数, 要么直接进 `PURE_OFF`。
- 🔴 先量再改档: 拿每节点 `ms` 排序 (在线 `traces[].ms`, 或离线按同一套 env 跑一拍统计) 再决定谁 OFF,
  别凭"看着重"猜; 关掉一个 9s 的节点与关掉一个 0.4s 的节点, 对拍子的意义完全不同。

## 三步配方

### ① 离线台（零风险，日常首选）

给服务写一个只调"计算层"的入口: import 模块 → 直接调纯函数（算目标/算分段/算路由），
不打开输入管道、不写下游。断点随便下，改参数重跑秒级。

示例（Z-MAX 执行器）:

```bash
./gui-venv311/bin/python tools/l2_debug_offline.py L2.forward --d_mm 10
./gui-venv311/bin/python tools/l2_debug_offline.py L2.goto_space1 --speed 32 --manual
```

配套写法: 用 `importlib.util.spec_from_file_location` 加载服务模块（确认 import 无副作用: 线程只在
`main()` 里起），从真值文件读当前状态，逐阶段调 `plan_stage()` 打印目标/Δ/call。

### ② 分离 dry 实例（全链路）

服务要提供 env 开关，默认行为不变:

| env | 作用 | 不设的后果 |
|---|---|---|
| `<SVC>_INPUT`（如 `ZMAX_L2_FIFO`） | 换输入管道 | 与线上实例抢同一条管道，命令被分食 |
| `<SVC>_LOCK`（如 `ZMAX_L2_LOCK`） | 换单实例锁 | 新实例接管并 **SIGTERM** 线上实例 |
| `<SVC>_DEBUG_DRY=1`（如 `ZMAX_L2_DEBUG_DRY`） | 收到的任何指令强制 dry | 断点停在动作中，下游继续执行 |

```bash
ZMAX_L2_FIFO=/tmp/l2_dbg.fifo ZMAX_L2_LOCK=/tmp/l2_dbg.lock ZMAX_L2_DEBUG_DRY=1 \
  ./gui-venv311/bin/python -m debugpy --listen 5678 --wait-for-client tools/l2_daemon.py
echo '{"skill":"L2.forward","d_mm":10,"speed":32}' > /tmp/l2_dbg.fifo
```

VSCode `launch.json` 里把这三项写进 `env`，`"justMyCode": false`，`program` 用**绝对**
`${workspaceFolder}/...`（路径不一致断点也不绑）。

### ③ 生产实例: 只读取证

```bash
tail -f <服务日志>
curl -s 'http://127.0.0.1:<port>/<回执端点>'      # 服务自己的原始回执
py-spy dump --pid <pid>                            # 卡住时看栈，不暂停
```

## 断点该下在哪: 先认分支

常驻服务通常按「任务形态」分流，不同按钮走不同函数 —— 断错函数就会以为"命令没到"。以 Z-MAX
执行器为例:

```
steps 非空      → run_stages() → plan_stage()      (空间点/号位/安全点 等多段技能)
ros=pose_rot    → run_rot_chunks()                 (A/B/C 绕工具轴)
ros=j6_rot      → run_j6_rot()                     (J6 自转)
其它(相对/单步)  → build_move()                     (方向键 前进/后退/左右/升降)
```

断点条件用**变量**不用行号: `spec.get("skill")=="L2.forward"`、`i==1`。

取证顺序: ①入口解析 ②`dispatch()` ③算目标（`build_move`/`plan_stage`）④闸门 ⑤最终下发（`_send_via_sdk`
→ `_T.exec_call`）⑥等到位（`wait_arrive`）。

## 🚫 指令被拒 `FIFO 打不开([Errno 6] No such device or address)` = 两个根因, 别只查一个

`Errno 6 / ENXIO` 在 FIFO 写端(`os.open(path, O_WRONLY|O_NONBLOCK)`)只有一个含义: **此刻没有读端**。
FIFO 文件存在、权限对、mtime 正常 —— 全都不代表有人读。实测两处(2026-10-20 老倪「操作机器人的指令被拒」):

1. **守护进程根本没在跑**(最常见)。`ls -l zmax_data/l2_cmd.fifo` 是 09:00 留下的空文件, 照样好看。
   判活别用 `pgrep -f <名字>`(会匹配到自己这条命令, 甚至把自己 kill 掉), 扫 cmdline:
   `for p in /proc/[0-9]*; do c=$( { tr '\0' ' ' < $p/cmdline; } 2>/dev/null ) || continue; case "$c" in *python*[l]2_daemon.py*) echo ${p#/proc/};; esac; done`
2. **在跑也照样被拒**: 主循环写成 `while True: with open(FIFO) as f: for line in f:` = **开-读-关**循环。
   关闭那一瞬到下次打开之间没有读端 ⇒ 恰好此刻点的指令 ENXIO; 更致命的是 **指令执行期间整条 FIFO 是关的**
   (一路 20s 的动作走完才回到 open) ⇒ 动作进行中点的每一条全被拒, 而现场表现是「点了没反应」。

**修法(服务自己持常驻读端)**: 启动时 `_fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)`(O_RDWR 让它自己也是写端
⇒ 别的写端永不 ENXIO), 主循环用 `select.select([_fd], [], [], 0.5)` 等数据, `os.read(_fd, 65536)` 取块,
按 `\n` 切行、**尾段不完整就留到下一轮**(`_buf`)。保留原有逐行处理体: 把 `with open(FIFO) as f:` 换成
`with io.StringIO("\n".join(lines)) as f:` 即可**不用重排缩进**(逐行体里的 `continue` 语义不变)。

**自证顺序**(不动机器人): ①`ls -l /proc/<pid>/fd | grep fifo` 看到那条 FIFO ⇒ 读端锚在;
②投一条**未知技能**探针 `printf '{"skill":"__pipe_probe__"}\n' > fifo` ⇒ 日志出现「拒绝: 未知技能」
且进程存活 ⇒ 管道通且没有下发运动。只在需要验运动时才用真技能。

常驻件都要有 `start|stop|restart|status` 的 ctl 脚本, 且 **status 必须直接报「FIFO reader 有没有」**——
「进程在」不等于「能收命令」, 这两件事在这套系统里已经各自出过一次事故。

## 坑

- **FIFO 没人读, 先查"保活是不是被人关了"**: `crontab -l | grep -i keepalive` 可能看到
  `# [关机暂停 <日期>] */5 * * * * …` —— 关机前手工注释掉、开机后**没人恢复**, 于是执行器从此没人拉起,
  现场表现就是「点了没反应 / 被拒: FIFO 打不开(Errno 6)」。修: 按原样取消注释 `crontab /tmp/ct_after.txt`, 再
  用手册脚本(cron 里那个 keepalive, **不是**简单 start)拉起 —— keepalive 会带上 `ZMAX_VL_INTENT_WAIT_S=600`
  这类裁决等待环境变量, 少了它们慢层重试轮次必然超时 ⇒ 落"未给裁决⇒从严不安全" ⇒ 所有动作被拒。
  起完三个判据一起看: ①`/proc/<pid>/fd` 挂着 FIFO ②`tr '\0' '\n' < /proc/<pid>/environ | grep ZMAX_VL` 有 600Σ
  ③投 `{"skill":"__pipe_probe__"}` ⇒ 日志「拒绝: 未知技能」且进程存活。

- **重启计数一路涨 + 日志只有一句「已有写入器在跑」= pid 文件陈旧 + pid 被系统复用**, 不是"真有实例在跑"。
  单实例锁只判 `os.kill(pid, 0)` 存活是不够的: 进程崩掉后那个 pid 会被内核回收、分给**别的**活进程,
  于是每次启动都判"已有实例"→ 直接退出。实测症状 = `systemctl show -p NRestarts` 六百多次、
  服务 `active` 但产物文件几小时不更新, 而 `journalctl -u` 里**没有 traceback**(只有 `status=1`)。
  诊断: `cat <pid文件>` → `ps -p <pid>` 看不见但 `os.kill(pid,0)` 不抛 ⇒ 读 `/proc/<pid>/cmdline`
  看它其实是谁(实测是另一个常驻件 pull 到了同一个号)。
  修法: 存活检查 + **cmdline 校验**双条件 —— `"<自己的模块名>" not in /proc/<pid>/cmdline` 就当陈旧锁接管并打日志。
  只判存活必然复发。
- **`journalctl -u` 只有 `Main process exited, code=exited, status=1` 时, 真错误在别处**: 看 unit 的
  `StandardOutput/StandardError` 指向的日志文件(如 `/var/log/<svc>.log`), 或前台手动跑一次同一 ExecStart 命令
  —— 锁/路径/依赖类退出在这两条里才有原话。
- **keepalive/看门狗每 N 分钟拉起服务**: 分离 dry 实例在跑时它可能认为"服务已在"从而不拉起线上实例 ⇒
  调试期间线上执行是停的；要恢复就 kill 调试实例，等看门狗拉起。
- 服务启动时会 unlink + 重建自己的输入 FIFO ⇒ 第二个实例会抢走路径，先起的实例读的是**已删除的 inode**
  （看起来活着，收不到命令）。
- 断点停在"等下游回执"的循环里最危险（下游可能已经动了）。要么 dry，要么把断点放在**下发之前**。
- 离线台要读**真实状态文件**（不是内存缓存），否则算出来的目标与线上不一致。
- **调试期间别按名字杀循环进程**: `pkill -f "tools/<loop>.py"` 会把用户 F5 起的 debug 会话一起 SIGTERM
  (而且这条命令自己也匹配得上, 先把自己这条 shell 杀掉 —— 括号写法 `pkill -f "pat[.]tern"` 只防模式本身,
  字面量出现在**同一条命令的其它位置** (比如后面还跟着启动该进程的命令) 照样自匹配 ⇒ `exit -15`,
  看着像终端/工具坏了; 最稳是按端口或 pid 停, `ss -ltnp | grep <port>` 拿 pid 再 kill, 或把 kill 单独发一次)。
  现场表现是“用户那边突然没输出了 / 还是卡着”,
  然后你又会去怀疑代码。做法: `ps -eo pid,etimes,cmd | grep "[t]ools/<loop>.py"` 列出全部, 按 **pid**
  只停自己起的测试实例; 要批量停又不想误伤自己, 用 `ps -eo pid,args | awk '$2 ~ /python$/ && $3 ~ /<loop>.py/ {print $1}'`
  (bash -c 的 $2 是 `-c`, 天然被排除), 写完先在 `$(seq)` 里 `echo` 一遍再执行。 万一已经误杀, 直接说“是我杀的, 按 F5 重开”, 别让他继续等日志。
- **用户说“还是卡 / 没变化”先比代码版本**: `ps -o lstart= -p <pid>` 早于补丁文件的 mtime ⇒ 他跑的是旧代码,
  让他重启比继续查代码省事得多。改完必须让用户重启一次才谈验证结论。
- **用户在 VSCode 里按 F5 调试 GUI 时，断点下在执行器文件上是必然不命中的 —— 先解释进程归属，
  再给配好的 launch 配置，别先让用户去"重启试试"。
- **别只用“日志/端口正常”证明节点在跑**: 界面数据可能来自另一个进程写的文件。要证“我要调的那段代码在这个
  pid 里执行过”，只有两种证据: 该 pid 打出的调用日志，或 py-spy 栈里出现那个函数。
- 「用户说都重启了好几次」= 停止让他重试: 改成自己去取证（`/proc/<pid>/environ` · `py-spy dump` ·
  `wmctrl -l` + 截图 OCR · 写 pid 到调用日志）。让用户反复重启而不给出新证据，是在消耗信任。
- **用户问「为什么 X 也在运行」先读 launch.json 列表 + 认启动器的 program**: 重生成/重排 `launch.json` 之后 F5 未必
  换成你要的那条 —— VSCode 记住的是下拉里**上次选中**的配置, 顺序只在“从未选过”时才算默认。判断实际跑的是哪条,
  只看 launcher cmdline 尾部的 program 路径(`tr '\0' '\n' < /proc/<pid>/cmdline | tail -3`)与 `wmctrl -lp` 的窗口属主 pid,
  不要用列表顺序推断, 也不要去猜用户点了什么。交付时说清“下拉里要选哪条”, 别只说“我把它放第一位了”。
- **要 100% 落到某条配置, 只留那一条**: 改顺序、加进多根工作区文件的 `launch` 段、重写模板都不保证 F5 换过去
  (VSCode 用的是下拉里**上次选中**那条, 实测三次 F5 仍起旧配置)。硬办法是把 `.vscode/launch.json` 与
  多根工作区文件 (`<名字>.code-workspace` 的 `launch.configurations`) 都临时裁成**只剩目标那一条**, 跑完再恢复并回读条数;
  中途靠 Ctrl+Shift+F5 重启会话即可换代码, 不必让用户重开窗口。
- **`torch.from_numpy(np.asarray(PIL.Image))` 拿到的是只读缓冲 ⇒ 每拍刷一行 `non-writable tensor` 警告**:
  PIL 出来的 ndarray 不可写, torch 只是警告不报错, 现场看起来像“报错刷屏”其实是每拍过一次就刷一次。
  修法 `np.array(..., copy=True)` (或 `.astype`) 显式复制, 别用 `asarray` 省这一步。
- **把常驻任务从独立服务搬进宿主进程时, 三件套缺一不可**: ①宿主每拍调用 (放在 `step()` 之后) ②**归属闸**
  (`owner()`/`ZMAX_DISPATCH_HOST` 单一名额, 其它宿主调 tick 直接返回 None ⇒ 不会双写状态文件)
  ③**旧入口默认拒绝启动** (没有显式 `--standalone` 就打印原因 `exit 0`, 别让它崩成 Restart 循环)。
  搬运后验收看 **产物帧龄 + 宿主 pid 一致性**: `systemctl show -p MainPID --value <宿主unit>` 要等于状态文件里
  记的 `dispatch.pid`, 且产物文件 (如 `skill_phys.json`) 帧龄 <1s; 只看「进程在」不算。
- **用户拿到工具返回的 pid 就问"为什么是独立进程 / 技能派发为什么独立"**: 那是这条 shell 命令自己的 bash
  子进程(长命令被工具转后台时也是同一个 pid, 不会另起一个), 与技能无关 —— 技能就是本会话里读 SKILL.md 后自己敲命令,
  没有派生 agent。一句话说清 pid 属于哪条命令, 别把工具层行为解释成"派发机制"。
  ⚠️ 但**别顺手否认机制存在**: 回答前先 `systemctl list-units '<前缀>*' --all --no-pager` +
  `systemctl --user list-units '<前缀>*'` + 扫 `/proc/*/cmdline`; 用户问“为什么是独立进程”往往是他已经看到那个单元在跑,
  “我这边只是在敲命令”只能证明自己没起, 证明不了单元不在。先取证再结论。
- **用户说「别自己启动」= 连自启钩子一起清, 不只是不敲 `systemctl start`**: 他会把你停掉的服务几分钟后又回来
  当成"你又启动了"。先认元凶 (`cat /proc/<pid>/cgroup`、`systemctl --user is-active <unit>`、
  `systemctl show -p Restart -p NRestarts`), 常见是 `zmax-studio-mem-guard.timer` 这种 `--enforce` 看门狗
  (`studio_mem_guard.py` 会 `bash restart_studio.sh` 把 GUI 拉起来)。清法: crontab 先 `crontab -l > bak` 再清空;
  timer/service 先 `disable --now` 再 **mv 到 `~/.hermes/autostart_removed_<ts>/`** (不 rm, 可回滚);
  `~/.hermes/scripts/*.sh` 全移; 收尾回读 `crontab -l | wc -l` / `systemctl list-timers | grep -c zmax` /
  `ls ~/.config/systemd/user/*.service`。只 disable 不 mv 的, 下次开机照旧回来。
  · **停 GUI 本身也要走单元, 不能只 kill pid**: `kill <pid>` 会被 `Restart=always` 在数秒内拉回, 用户看到的就是
  “你根本没关掉/又自己启动”。用 `systemctl --user stop <gui-unit>`, 停完按 `comm` 过滤复核进程为空
  (python 开头那种), 别用 `pgrep -f` 撞到自己这条命令。
  · 清完 `systemctl daemon-reload`（`--user` 那边也要）, 否则 `list-timers` 里还挂着已移走的单元 ⇒ 误判“没清掉”。
  · 报告口径: 点名“停掉哪几个单元 · 备份目录路径 · 还剩哪些 enabled 的 service 会在开机/崩溃自起”, 不写“已全部关闭”。
- **`linux` 上重启控制台用既有 unit, 别手搓 python**: `systemctl --user restart zmax-studio`
  (`ExecStart=tools/gui/launch_studio.sh`) —— 启动脚本里 `unset QT_QPA_PLATFORM` + `export QT_QPA_PLATFORM=xcb`
  是踩过坑写进去的: 在同一个 shell 里跑过离屏判据(`QT_QPA_PLATFORM=offscreen`)后继承下去, GUI 会“进程活着、
  日志正常、就是没有窗口”。重启后验三条: unit `active` · `wmctrl -l` 有窗口 · `/tmp/studio_launch.log` 尾部无 Traceback。
