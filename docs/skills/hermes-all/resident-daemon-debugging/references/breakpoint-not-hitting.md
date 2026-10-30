# 断点不命中 · 命令清单

按顺序跑，每步都留下可复现输出。任一步已证伪就停在那一步，不要继续“改配置试试”。

## 1. 谁在写数据 / 代码跑在哪个进程

```bash
systemctl is-active <loop 服务>
python - <<'PY'
import json, os, time
p = "zmax_data/ss_live/engine_latest.json"
print({"mtime_ago_s": round(time.time() - os.path.getmtime(p), 2),
       "idx": json.load(open(p)).get("idx")})
PY
tail -3 zmax_data/ss_live/actuator_calls.log    # 节点入口写的「时间 pid 名字」
ps -o lstart= -p <调试pid>                      # 启动时间 vs 最后一次改代码的时间
```

节点入口埋点（写一次就够，之后永久可用）：

```python
try:
    p = os.path.join(ROOT, "zmax_data", "ss_live", "actuator_calls.log")
    with open(p, "a") as f:
        f.write("%s pid=%s\n" % (time.strftime("%H:%M:%S"), os.getpid()))
except Exception:
    pass
```

判读: mtime≈0 但日志里没有调试进程的 pid ⇒ 数据是别的进程写的。
**限制**: 该埋点只覆盖“走这个入口”的路径；引擎直连调用（`self.execr.execute(...)`）不经过它，
所以日志为空只能说明“这个入口没走”，不能说明函数没被调用。要证函数被调，靠 py-spy 栈或在函数自身内埋点。

## 1b. 认准调试进程（debugpy 多进程会把子进程也挂上）

```bash
# 启动器 cmdline 尾部那个路径 = VSCode 真正 launch 的 program
for p in /proc/[0-9]*; do c=$( { tr '\0' ' ' < $p/cmdline; } 2>/dev/null ) || continue;
  case "$c" in *pydevd*|*debugpy*launcher*) echo "== ${p#/proc/} ppid=$(awk '{print $4}' $p/stat)"
    tr '\0' '\n' < $p/cmdline | tail -2;; esac; done
wmctrl -lp | grep -i <GUI 标题>      # 窗口属主 pid = GUI 本体
sed -n 's/.*pid=\([0-9]*\).*/\1/p' zmax_data/ss_live/actuator_calls.log | sort | uniq -c | sort -rn | head
```

三条合起来判：
- 栈在 `model_autoload.load_l3 → from_pretrained`（HF 下载）之类 ≠ 主调试进程 —— 那是 GUI 启动时派生、
  被 debugpy `--multiprocess` 顺手挂上的**子进程**；GUI 本体的栈应在 Qt 事件循环（`_tick → main (studio.py…)`）。
- `wmctrl -lp` 的窗口属主 pid 才是界面本体；`ppid` 指向 launcher 的是 pydevd 注入进程，不要当程序本体。
- 调用日志里目标 pid **计数 0** ⇒ 这个进程从没执行过该节点；计数几千的 pid 是当时的常驻宿主。
  节点宿主历史上会换十几个 pid（各代 GUI / 常驻循环 / 单次脚本），所以调试配置要指向“会执行该节点的入口”，
  不是“现在开着的任意 GUI”。

## 2. 调试进程此刻在干什么

```bash
sudo py-spy dump --pid <pid>
```

- MainThread 只有 `paintEvent / _sphere / QApplication.exec` ⇒ 没有节点在执行。
- `pydevd.Writer / Reader / CommandThread` 是调试器线程，属正常。
- 栈顶 `active+gil` = 它在持续算（界面会显得“有数据在动”）。

## 2b. 自己看界面，别让用户反复重启

用户说“都重启了还是不行”时，去看真实屏幕状态；界面自己会写清它到底跑没跑。

```bash
wmctrl -l                       # 哪些窗口真开着（标题常直接露文件名/路径）
scrot -o ~/.hermes/cache/scratch/screen.png
tesseract screen.png out -l chi_sim+eng && grep -nE "未运行|运行|Pdb|Traceback" out.txt
```

带坐标版（要点击某按钮时）:

```bash
tesseract screen.png out -l chi_sim+eng tsv
awk -F'\t' 'NR>1 && $12!="" {printf "%s @ %d,%d\n", $12, $7+$9/2, $8+$10/2}' out.tsv | grep 运行
```

实测界面自述「未运行(没点 ▶ 运行)」= 铁证: 该进程从未跑过业务代码。比任何日志推断都直。

## 2c. 启动阶段就被外部依赖卡住（最像“断点没绑”的真因）

循环/服务类入口在**第一拍**里懒加载模型时，会卡在网络或权重解析上。此时断点完全没有机会被触发，
而调用日志也一条不写 —— 与“断点绑不上”无法从表面区分。判据只要一条栈:

```bash
sudo py-spy dump --pid <调试pid> | sed -n '1,40p'
# 命中以下任一 ⇒ 不是断点问题, 是阻塞:
#   socket.connect / httpcore → huggingface_hub.list_repo_tree → transformers from_pretrained
#   time.sleep / threading.Event.wait / subprocess 等待外部进程
```

再证网络（两条都要，缺一条可能是别的原因）:

```bash
curl -m 6 -so /dev/null -w '%{http_code}/%{time_total}s\n' https://huggingface.co   # 000 = 不通
ss -tnp | grep <pid> | grep SYN-SENT        # 卡在 TCP 握手 = 连不出去, 不是“慢”
```

修法（写进模板的 `env`，否则右键重写会丢）:

```json
"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"
```

离线只读本地缓存并跳过 `list_repo_tree` 这次 Hub 查询。实测对比: 离线 `AutoProcessor.from_pretrained` 0.14s、
`AutoModelForImageTextToText` 507M 权重 0.6s; 同一调用在线时无限挂住。要在线下权重时才临时去掉这两个 key。

验收（不动机器人、只跑计算链）:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 timeout 90 ./gui-venv311/bin/python tools/<循环入口>.py > /tmp/loop_offline.log 2>&1
tail -3 zmax_data/ss_live/actuator_calls.log     # 出现该进程自己的 pid, 每拍一条 = 每一拍真的走完了
```

判读纪律: 只有在“这一拍确实跑完”被证之后，才可以继续怀疑断点绑定；顺序反了会把网络故障当成断点问题，
改一圈 launch/env 也修不好。

## 3. env 有没有真进进程

```bash
for p in $(pgrep -f "debugpy.*<入口>.py" | head -3); do
  echo "--- $p"; ps -o lstart= -p $p
  tr '\0' '\n' < /proc/$p/environ | grep -E "ZMAX_|PYDEVD|OMP_NUM|MKL"
  tr '\0' ' ' < /proc/$p/cmdline | cut -c1-160
done
```

- 一项都没有 ⇒ 启动配置没进进程。改成改**模板函数**再重生成 launch.json。
- cmdline 里要能看到 `-X frozen_modules=off`。

## 3b. launch.json 默认顺序 / 模板重生成

```bash
python -c "import json;d=json.load(open('.vscode/launch.json'));n=[c['name'] for c in d['configurations']];print(len(n), n[:3])"
```

- F5 未选配置时跑**第一条**；条数/顺序变了就等于默认程序变了（列表从 1 条变十几条 ⇒ 默认回到 GUI，
  用户会问“为什么这个也在运行”）。
- 手改 launch.json 会被右键「打开 VSCode」按模板整份重写；唯一模板 =
  `tools/gui/simulink_module.py::_vscode_launch_cfg(root)`。要加/调配置：改模板 → 从模板重生成 → 回读。

```bash
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python -c "
import sys, json; sys.path.insert(0,'tools/gui'); sys.path.insert(0,'src')
import simulink_module as sm
cfg = sm._vscode_launch_cfg('/home/ubuntu/zmax')
n = [c['name'] for c in cfg['configurations']]
print(len(n), [x for x in n if n.count(x) > 1] or 'no dup', '| first:', n[0])
json.dump(cfg, open('.vscode/launch.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
print('readback:', len(json.load(open('.vscode/launch.json'))['configurations']))"
```

- 当前任务的断点配置放**列表第一位**（其余位置不动），重生成后把“条数 / 首条 / 位置”回读报给用户。
- 单次节点宿主配置（用这条停 `execute`，别拿 10Hz 常驻循环当断点台——每拍都停没法用）:
  `program: tools/dbg_actuator.py` · `args: ["ssact"]` · `env: {ZMAX_DBG_U: "0.12,-0.05,0.30,0.0"}` ·
  `pythonArgs: ["-X", "frozen_modules=off"]` · `justMyCode: false`。

## 4. 断点位置是否仍然有效

```bash
grep -n "def <函数名>" <文件>
sed -n '<def行>,<def行+8>p' <文件>
grep -rn "class <类名>" --include=*.py .     # 常有多份同名副本，只有一份是最新真身
```

pdb 验证（动态加载模块唯一可信的方式）：

```bash
python -m pdb -c "b /abs/path/file.py:LINE" -c c -c "p 变量" -c q tools/<脚本>.py
```

命中会打印 `> file.py(93)execute()  ->  a = np.asarray(...)`；
若回 `*** Blank or comment` 说明该行不是可执行语句，断点没被设置。
路径必须绝对；相对路径匹配不上 `co_filename`。
断点行要是**函数体第一条可执行语句**: 打 `def` 行停不住（停时参数还没绑定, `p u` 会 NameError）。

## 4b. 加载器有没有让断点可绑

```bash
# 是否 spec 直装? 先看模块名——`state_space.execution` 这种 = 动态路径, 断点不绑;
# `lerobot.policies.left_right.state_space.execution` = 正常 import, 能绑
python -c "import sys;sys.path.insert(0,'src');<触发一次节点>;print([n for n in sys.modules if n.endswith('<模块>')])"
# debugpy 有没有编译 frame eval? 没有 ⇒ 不能运行时加/删断点
find <debugpy>/_vendored/pydevd/_pydevd_frame_eval -name "*.so"
```

**唯一可靠的修法是让它走正常 import** (`importlib.import_module`, sys.path 里放 `src/`,
旧名登记成别名 `sys.modules[old]=m`)。本仓统一入口: `lerobot/engineering/modload.py::load(name, path)` ——
自动探 sys.path (名字≠文件名、`tools/` 脚本、包内模块都能解析), 失败才退 spec 并打一行原因。

| 现象 | 机制 | 修法 |
|---|---|---|
| 该文件所有断点都不停, 同仓库其它文件正常 | spec/exec 直装, 绕开 `builtins.__import__` | 改走 `modload.load()` (正常 import) |
| 同上但只补了 `sys.modules[name]=m` 仍不停 | **注册只是让 pydevd 能按名找文件, 不触发注入** | 仍然必须改正常 import |
| 首次能停, 取消再添加就不停 | 无 frame eval, 只能编译期注入 | 每次运行前清 `_SS_MODS` + `sys.modules` 前缀缓存强制重编译 |

`modload` 把兜底的文件记进 `SPEC_LOADED`; 验证工具据此判"这个文件绑不上", 不靠猜。

## 4c. 右键源码的落点是不是"真执行的那一行"

两件都会让红点落在死位置:

1. 映射指到 **class/def 头一行** —— class 体只在 import 时执行一次。
2. **显示层自己又按符号搜一遍**: `sourceview.get_node_location` 读到 `_EXTERNAL_LOC` 后,
   用 `行首 startswith(symbol)` 搜第一处 `def`/`class` 并**覆盖行号** ⇒ 只校准映射行号无效。
   现口径: 映射行落在函数体内就直接用, 否则按符号找定义再取该函数首条 return。

```bash
# 现场取一次判据 (必须是 return 行)
HF_HUB_OFFLINE=1 ./gui-venv311/bin/python -c "
import sys; sys.path.insert(0,'src')
from lerobot.engineering import nodes, sourceview as sv, registry as rg
for n in ['🤖 机器人执行器','📡 融合定位建图']:
    k = rg.match_node(n); print(k, sv.get_node_location(k))"
```

同一个 key 的 `_EXTERNAL_LOC` 可能写了多遍 (后者静默覆盖前者) —— 改之前 `grep -c '_EXTERNAL_LOC\["<key>"\]'`。

## 4d. 逐节点验收 (不是只验一个节点)

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ZMAX_SINGLE_THREAD=1 \
  ./gui-venv311/bin/python tools/verify_node_breakpoints.py --write   # → reports/node_breakpoints.json
```

每个节点给四件事: 右键落点 · 该文件是否真被执行 · 打开函数的每个 return 行 · 本次命中几处。判定分级:
`PASS` / `NEED-INPUT`(绑得上但这一拍没走到, 要真数据) / `SUBPROC`(实现在子进程脚本里) /
`FAIL-BIND`(还是 spec) / `FAIL-NORET`(跑了但没到 return 分支)。
两坑: ① 空输入会早退 ⇒ 第二遍喂合成输入再判; ② 有节点会 `QWidget()` —— 无 QApplication 直接 SIGABRT
整个审计, 脚本开头要 `QT_QPA_PLATFORM=offscreen` + 建一个 `QApplication`。

## 5. 兜底：文件开关断点

```python
_brk_flag = os.path.join(ROOT, "zmax_data", "ss_live", "BREAK")
if os.path.exists(_brk_flag):
    breakpoint()
    return
```

- `ROOT` 用 `__file__` 上溯算，**按该文件实际深度数**：`nodes/x.py` = 5 层，
  `policies/left_right/state_space/x.py` = 6 层。套错一层会指到 `src/zmax_data/...` 而永不命中，
  且被 `except: pass` 吞掉 ⇒ 看起来像“代码没执行”。算完打印一次真实路径核对。
- 流程: 停常驻服务 → `touch .../BREAK` → 起 GUI → 触发节点 → 终端出现 `(Pdb)`。
- 完事 `rm -f .../BREAK`，否则常驻服务里同一节点一起停住。

## 5b. 让它真跑起来（否则前 5 步全白做）

停掉常驻服务后，GUI 自己是“未运行”状态 —— 必须让代码在**调试进程**里跑一次。

```bash
sudo systemctl stop <loop 服务> <engine 服务>
# 调试模式启动时自动跑一次业务代码（推荐，不靠人记得点）
```

自动跑的实现要点（PyQt）：
- 窗口是**异步建好**的，一次性 `QTimer.singleShot(2500, fn)` 会在窗口存在前就执行并落空。
- 用 1s 轮询 `app.allWidgets()` 找带目标方法的实例（上限约 60 次），找到再调。
- 开关用 env（如 `ZMAX_DEBUG_MODE=1`，`ZMAX_AUTO_RUN=0` 关），只在调试档生效。
- 验收: 日志里出现 `[brk:<tag>] 到达` 或 py-spy 栈里出现 `execute/run`。

收工: `rm -f .../BREAK` + `sudo systemctl start <loop 服务> <engine 服务>`。

## 6. 用户侧口径

- 只给能停的那条路（pdb 或文件开关），不说“F5 应该能停”。
- 同时说明哪一步会让程序真的跑起来（点 ▶ 运行 / 右键运行节点）——“进源码打断点”只是打开文件。
- 报当前准确行号，并提示旧断点已失效。
