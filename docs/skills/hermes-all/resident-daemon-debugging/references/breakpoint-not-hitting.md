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

## 4b. 加载器有没有让断点可绑（spec 加载的三个必要条件）

```bash
# 1) 注册进 sys.modules 了吗？不注册 ⇒ 该文件所有断点静默失效
python -c "import sys;sys.path.insert(0,'src');<触发一次节点>;print('<模块名>' in sys.modules)"
# 2) 是 spec 加载还是 exec(compile())？后者取消断点后无法重新绑定
python -c "import sys;sys.path.insert(0,'src');<触发一次节点>;m=sys.modules['<模块名>'];print(m.__spec__, m.__loader__)"
# 3) debugpy 有没有编译 frame eval？没有 ⇒ 不能运行时加/删断点
find <debugpy>/_vendored/pydevd/_pydevd_frame_eval -name "*.so"
```

| 现象 | 机制 | 修法 |
|---|---|---|
| 该文件所有断点都不停, 同仓库其它文件正常 | 加载器没写 `sys.modules[name]=m` | 加载处补一行注册 |
| 首次能停, 取消再添加就不停 | `exec(compile())` 造的模块无 `__loader__` | 改 `spec_from_file_location` 并注册 |
| 只有模块首次加载时能停 | debugpy 无 `_pydevd_frame_eval`(.so 缺失) | 每次运行前清模块缓存强制重编译 |

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
