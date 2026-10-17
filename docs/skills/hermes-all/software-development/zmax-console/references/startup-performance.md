# 控制台启动性能：先量再改 (2026-10-17 实测 47s → 9.9s)

老倪口径：「控制台启动最多 10 秒」。下面这套流程能在不改业务逻辑的前提下把「慢在哪」钉死。

## 一、先拿真实基线（不要靠体感）

窗口出现的准确时刻有现成台账：`/tmp/studio_show_diag.log`（studio.py 在构造完、show 前各写一行 `time.time()`）。
拿进程真实启动时刻对比：

```bash
ps -o pid,lstart,etime -p <studio_pid>
# 与 /tmp/studio_show_diag.log 里 _show_ready / after show 那一行比对 ⇒ 得出「启动→窗口可见」秒数
tail -3 /tmp/studio_show_diag.log
```

实测实例：`STARTED 09:53:39` → `after show visible=True 09:54:26` = **47 秒**。

## 二、定位热点：py-spy 采启动过程（最有效）

```bash
# 起一个 offscreen 实例（不抢老倪窗口、不抢相机；引擎/相机已 kind=off 时更干净）
cd ~/zmax && QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python -u tools/gui/studio.py > /tmp/offscr.log 2>&1 &

# ptrace 需要 root
PSPY=/home/ubuntu/.hermes/hermes-agent/venv/bin/py-spy
sudo env "PATH=$PATH" $PSPY record -o /tmp/boot.speedscope.json -f speedscope -d 35 --rate 120 --pid <pid>
```

然后按「栈顶自身耗时」汇总 speedscope 的 samples/weights（叶子帧 = 正在执行的函数）：

```python
d = json.load(open('/tmp/boot.speedscope.json'))
p = d['profiles'][0]; names = [f['name'] for f in d['shared']['frames']]
for st, w in zip(p['samples'], p['weights']):
    self_t[names[st[-1]]] += w
```

本次就是这样抓到 `_max_alloc_mb` 占栈顶 64%。

## 三、永久手段：启动路径加分段计时

studio.py 已内置（2026-10-17 起）：
- 文件顶部 `_BOOT_T0 = _time.time()`
- 三处打印：内存探测 / 搭主窗口 / 窗口显示，形如
  `⏱ 启动计时：控制台主窗口已经显示出来，从进程启动算起一共用了 9.93 秒。`

以后任何人启动，`/tmp/studio_launch.log` 里直接有这三段。日志按「完整句子」写（见 log-writing-style.md）。

## 四、本次真根因（教训）

`tools/gui/startup_probe.py::_max_alloc_mb()` 为了给 Windows exe「双击 MemoryError」留证，
在启动路径上**逐档真分配** 16/32/…/1024MB 的 `bytearray` 并触碰首尾。CPython 的 `bytearray(n)`
**分配即 memset** ⇒ 累计写 **32.5GB**，本机实测 **11.8 秒**；控制台又在同一时刻起 model_autoload 子进程
（L3 SmolVLM 17.9s、占内存带宽）⇒ 二者抢带宽，这一段在真实启动里膨胀到 **30 秒以上**。

修法：
- Linux/macOS：读 `/proc/meminfo` 的 `MemAvailable`（口径等价「一次还能分到多少」，0.001 秒）
- Windows：保留真分配（没有 /proc），但 cap 1024→256、step 16→32
- 需要还原全量实测：`ZMAX_ALLOC_PROBE_MB=1024`（注意 Linux 仍走 meminfo 快路径）

实测结果（真机无 GPU 依赖，X11 口径，老倪控制台并行运行中）：
| 段 | 改前 | 改后 |
|---|---|---|
| 内存探测 | 11.8s（有并发时 30s+） | 0.00s |
| 搭主窗口 | — | 4.78s |
| **启动→窗口显示** | **47s** | **9.93s** |

## 五、别踩的坑

- **不要用 `xdotool search --class studio.py` 测窗口出现**：本机常有老倪正在用的实例，会匹配到旧窗口 ⇒ 测出 7 秒的假数据。要么先 `xdotool getwindowpid` 核对 PID，要么用 show_diag 日志。
- **不要为了测启动去 kill 老倪的实例**：用 offscreen 实例测同类路径；真要测 X11 口径，用 `timeout 80 python tools/gui/studio.py` 起临时实例，测完自动退。
- `main()` 里 `Popen(model_autoload, start_new_session=True)` 的子进程**不随父进程退出**；用完 `pgrep -af model_autoload[.]py` 查孤儿。
- 采样窗口要覆盖启动全程：先起进程再 record 会漏掉最早的 import 段，必要时 `-d 60`。
