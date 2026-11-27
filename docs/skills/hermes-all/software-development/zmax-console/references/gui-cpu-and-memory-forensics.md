# 控制台 CPU 吃满 / 界面发涩 / 内存增长: 取证与降载定式

适用范围: 用户说「电脑变慢了」「界面发涩」「控制台卡」以及给 studio.py 做性能改动后的验收。
所有数字必须现场采, 不许引用启动期均值。

## 0. 先分清是哪一类「慢」

1. **整机会话层**(键鼠/拖窗/切窗口要等几秒) ⇒ 走 `linux-host-maintenance` §1b/§1c (GPU 争用、swap、自己的排查进程)。
2. **控制台自身发涩**(页面滚动/切页卡) ⇒ 本文。特征: 整机 CPU 总量不高(32 核里 3~4 核)、load 4 上下,
   但 studio.py 的**主线程**被 `paintEvent` 占住 —— Qt 的绘制在 GUI 线程, 任何一帧算不完就整窗掉帧。
3. **内存增长** ⇒ 本文 §4。

## 1. 采 CPU: 用 /proc 差分, 不要用 `ps %CPU`

`ps -eo pcpu` 是**生命周期均值**: 一个跑了 2 分钟、启动时烧了 90% 的实例会一直背着那个数;
反过来刚重启的实例看起来很低。同一口径的差分采样:

```python
# 读两次 /proc/<pid>/stat 的 utime+stime (字段 14/15), 间隔 5~8s
st = open(f'/proc/{pid}/stat').read().rsplit(')',1)[1].split()
util = int(st[11]) + int(st[12])          # 注意: rsplit(')') 后索引前移 2
cpu% = (util2 - util1) / 100.0 / dt * 100
```

- 求和报**核数换算**: 「合计 328% = 3.3 核 / 32 核」比一个百分比有用。
- 分进程列表阈值取 >2%, 否则噪声一堆小进程把结论淹没。

### 🔴 前后台同口径铁律
窗口**在后台时 Qt 不重绘**(`paintEvent` 根本不被调用) ⇒ 同一个进程在后台 22%、切到前台 120%,
这不是优化生效, 是测量状态变了。做过改动要给真实降幅时, 必须在**同一可见页面**下前后各采一次;
拿不到就如实说「改前那次是面板在前台测的, 现在面板在后台, 两个数不能直接比」—— 别给出假降幅。
判据: `xdotool getactivewindow getwindowname` 看前台是谁; `py-spy dump` 看 MainThread 是否在 `paintEvent` 里。

## 2. 定位到函数: py-spy record + **加权**解析 raw

```bash
sudo env "PATH=$PATH" <venv>/bin/py-spy record --pid <pid> --duration 15 --rate 100 --format raw -o /tmp/spy.txt
```

raw 格式每行是 `<帧;帧;帧> <count>` —— **必须乘 count 再累加**: 直接把行当样本会把 4275 个样本算成 540,
百分比全错(实测踩过)。解析模板:

```python
import collections, re
leaf, incl, tot = collections.Counter(), collections.Counter(), 0
for line in open('/tmp/spy.txt'):
    m = re.match(r'^(.*) (\d+)$', line.strip())
    if not m: continue
    frames = [f.strip() for f in m.group(1).split(';') if f.strip()]
    c = int(m.group(2)); tot += c
    leaf[frames[-1]] += c
    for f in set(frames): incl[f] += c      # inclusive 才看得出"这一整条路径"
```

- 判读: `leaf` 给「独占」(谁在真烧), `incl` 给「路径」(哪条业务链在烧)。
  实测一次: `take`(DDS 取样) 14% · `run`(队列消费) ×2 各 13% · `read` 9% ⇒ 是**多个 0.1~0.3 核的常驻线程叠加**,
  不是单点 bug; 这种要按线程逐个降频, 别指望一处改完。
- `py-spy dump --pid` 看线程名 + 当前栈: `"Thread-N (_run)"` + `take (zmax_node.py:167)` 能直接指到 DDS 轮询线程。
- 权限: 不加 `sudo env "PATH=$PATH"` 会报 `Permission Denied` (同一台机器上 sudo 可用时就这么跑)。

## 3. 3D 面板(`orbital_arch.py`)发涩的已知大户: 每帧新建 QFont/QFontMetrics

**症状**: `paintEvent` 独占 5~13%, 里面是 `_block`(画文字块) / `_labels`(避让布局) / `_wrap`(按像素宽换行)。
**根因**: 每个文字块都 `QFont("DejaVu Sans"); setPixelSize(size); p.setFont(f)`, `_fm()` 每次 new 一个
`QFontMetrics`, `_wrap` 里又被 `_fit_lines` 反复调 `QFontMetrics.width` —— 一帧几十次, 全在 GUI 线程。

**修法**: 模块级按 `(字号, bold)` 缓存 font/metrics + 换行结果缓存。实测微观基准:

```
旧: 每次新建 QFont+QFontMetrics   13.7 us / 次量宽
新: 复用缓存的 metrics            4.5 us / 次量宽    (3 倍)
```

⚠️ **换行/量宽缓存必须有上限**: 缓存的 key 里含**实时数值文本**(`前馈加速器 v_ff=10.74 mm/s`),
值每帧变 ⇒ key 无限新增 ⇒ 缓存自己变成泄漏源。定式:

```python
if len(_WRAP_CACHE) > 3000: _WRAP_CACHE.clear()      # 换行结果
if len(_FM_W) > 20000:      _FM_W.clear()            # 单条文本宽度
```

改完自证两件事: ① `py-spy dump` 里 MainThread 不再整帧卡在 `_block`/`_labels`;
② 同类栈的 inclusive 占比下降(注意 §1 的前后台口径)。

## 4. 信号页轮询频率(`canoe_graphic.py::HOST_POLL_HZ`)

50Hz 轮询本机文件源, 一个线程就 ~0.25 核; 曲线在屏幕上根本分辨不出 50 与 20Hz 的差别。
降到 20 不丢真值(落盘文件仍按生产者节拍写, 只是进曲线库的采样密度变了) —— 但**要在注释里写清是采样密度**,
否则下次有人以为数据丢了。同理 `studio.py` 里那些 `while waited < self.interval: sleep(0.1)` 的取数线程,
先看 interval 是多少再谈优化; 它们的 CPU 花在 `self.card._collect()`(文件/HTTP 读), 不在 sleep 上。

## 5. 内存增长: 段差分判「增长源」

工具 `tools/probe_rss_seg.py --wait 240`(对**当前** pid 采, 前后各一次 `/proc/<pid>/smaps` 差分)。
判读:

- 增长集中在**新增的 anon rw-p 段**, 且段大小整齐(66/64/64/64/29/24/14 MB…) ⇒ **glibc malloc arena** 形状
  (每线程一套, 64MB 一块, 只增不还)。处置: 启动时 `MALLOC_ARENA_MAX=4` + `MALLOC_TRIM_THRESHOLD_=131072`
  (已在 `tools/restart_studio.sh` 里) —— 但**用别的方式起的实例没有这两个 env, 会照涨**; 报内存前先
  `sudo tr '\0' '\n' < /proc/<pid>/environ | grep MALLOC` 看它到底带没带。
- **线程数恒定而 RSS 照涨 ⇒ arena 不是主因**。此时看**按需扩容的缓冲**: 信号环形缓冲惰性分配(初始 64KB/信号),
  被画的信号写满后翻倍长到 CAP(200000 点 ≈ 3.05MB/信号), 1000+ 个 key 上限就在 GB 级 ——
  这是**有界填桶**, 不是无限泄漏。判据只能是**长时间(≥30min)看是否走平台**, 不能凭 5 分钟斜率下结论。
- `probe_rss_seg` 的假数字指纹: `RSS 0 MB · Δ −1858MB` ⇒ 目标 pid 中途被替换(控制台单实例机制杀旧起新),
  采样脚本没跟上。重采前先确认 pid 还是那个 `lstart`。

## 6. 反复重启控制台会把 swap 攒起来(会话发涩的隐形来源)

每次重启峰值 1.4~3.6GB, 十几次之后 swap 里就躺着几 GB, 桌面碰到被换出的页就顿。
回收前先确认装得下: `MemAvailable` 必须 > swap 已用, 然后

```bash
sudo swapoff -a && sudo swapon -a        # 实测 3.9G 换回内存用 15.8s
```

报数要写「swap 已用 X G → 0」, 不要写「清理了一下」。

## 7. 重启脚本的实例竞态(会同时出现两个控制台)

`restart_studio.sh` 在**起新实例之前**判"残留"并有 sleep, 期间旧实例或别处的启动会插进来 ⇒
起完之后 `head -1` 抓到的可能是**别人那个**, 于是两个实例并存(各 1.3~1.4GB)。
定式:

1. 杀只认 `cat /proc/<pid>/comm` 以 `python` 开头 —— `pgrep -f studio.py` 会命中**你自己那条 bash 包装**
   (命令行里就有这个字符串), 把当前 shell 打死。
2. 起完按 `ps -o lstart=` 只留**最新那个**, 其余 TERM。
3. 复核三件: 实例数 == 1 · 窗口 `IsViewable` · 数据面(trace/信号文件)帧龄 <1s。

## 8. 汇报格式(老倪要看的是结论+数字)

按「占总账 / 大头是谁 / 改了什么 / 实测前后」四段, 每段带数字与单位(核、GB、ms、us)。
不要写「已优化性能」; 不要把后台态的数字和前台态的比; 拿不到同口径就明说拿不到。

## 9. "卡住了" 第一动作: `py-spy dump` 抓主线程栈 (周期性 tick 死循环)

`py-spy dump --pid <pid>` 一次就够 —— 若 `MainThread (active+gil)` 反复停在同一条链上, 那就是 4Hz 级死循环,
不必先 record。实测形状(一条栈直接点出问题):

```
_tick → _update_tree_values → _on_item_changed → _draw_order → _trim_selected → _log
```

判读: `_tick` = 定时器; `_update_tree_values` 只写"值变了的行"; `_on_item_changed` 被这次写入触发;
`_draw_order` 里做"超过上限就裁"。这条链等于**写入 → itemChanged → 重算 → 裁剪 → 再写**闭成了环。

根因(可推广的规则): **周期性 tick 里的"裁到 N 条"如果只裁内存列表、不回写控件状态, 下一拍的
`if checked == (key in selected): return` 守卫对被裁的行不成立 ⇒ 整棵重取 + `set_curves(几百条)` +
再裁 + 每拍一行日志**, 4Hz 就把主线程吃满(实测 103% of one core; `ps %CPU` 是生命周期均值, 看不出来)。

修法三层(缺一层都复发):

1. **裁掉的同时改控件状态**: 对被裁的 key `setCheckState(0, Qt.Unchecked)` —— 取消勾选会发 `itemChanged`,
   但此时 key 已不在 selected ⇒ 守卫直接 return, 不会递归。
2. **日志节流**: 同一溢出状态 10s 只报一次(`time.monotonic()` 记 `_trim_log_t`); `_log` 会同时写页面标签与
   日志面板, 每拍一次 = 刷盘。
3. **所有入径走同一收口**: 别的入口(watch 前缀自动勾选等)直接 `set_curves(self.selected)` 会绕过裁剪 ⇒
   统一改调 `set_curves(self._draw_order())`, 否则溢出从另一条路又长回来。

验收必须给两个数: ① `/proc/<pid>/stat` 差分(改动前后同一可见页面) ② `py-spy dump` 里 MainThread 回到 `idle`。
实测口径: 103% → 23% of one core, 主线程 idle 且栈里不再出现 `_trim_selected`。
