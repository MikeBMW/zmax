# 进程 RSS 只增不减: 定位与修复定式

用于"某个进程把整机内存吃满 → 全局换页 → 桌面卡死"这类事故。核心原则: **先量哪一块在涨, 再抓谁在分配**,
不要靠读代码猜泄漏点(本轮实测: 猜错了 3 次, 换成段 diff + bpftrace 一轮就命中)。

## 1. 先分清三种"涨"

| 类型 | 特征 | 判据 |
|---|---|---|
| 真泄漏 | 对象被引用永不放, 线性增长不停 | 段 diff 里同一批段持续长; 抓栈能看到具体业务函数 |
| 分配器不还 | CPython pymalloc arena / glibc arena 碎片化后只增不落 | 大量 256KB~64MB 段持续"新映射", 但配对的 munmap 不出现 |
| 正常热缓存 | 启动后收敛 | **跑够 15~30 分钟进平台期就停**; 只测 3~5 分钟会把启动缓存误判成泄漏 |

先把时间拉够再下定论。本轮踩过的坑: 启动 4 分钟时 RSS 1.58GB 就判"还在漏", 但那段时间本来就在灌缓存。

## 2. 段级 diff (第一件事)

```bash
sudo python3 scripts/probe_rss_seg.py --pid <pid> --wait 120
```

输出 = 增长最大的具体映射段。判读表:

| 现象 | 含义 |
|---|---|
| `[anon]` rw-p 增长 | numpy 大数组 / GL·VBO 缓冲 / 线程栈(8MB/线程) |
| `[heap]` 增长 | 小对象(both pymalloc 大对象走 mmap 时也能看到 brk 增长) |
| **56~72MB 段反复"新映射"** | glibc arena(默认上限 8×核数, 每 arena 最多 64MB, 只增不还) |
| **128KB~1MB 段高频新增** | CPython pymalloc arena(`_PyObject_ArenaMmap` 每次 mmap 256KB) |
| 大额带文件名的映射 | 数据集/模型/字体缓存, 通常不是泄漏 |

⚠️ 只按映射名聚合(全归到 `[anon]`)不够用 —— 必须按 `(起址, 权限, 名字)` 对齐两快照, 才能看出"是持续新增还是同一个段在长大"。

## 3. 抓分配者 (决定性证据)

```bash
P=$(pgrep -f '<脚本名>[.]py' | head -1)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_mmap /pid == '"$P"'/ { @u[ustack(5)] = count(); }
                  interval:s:40 { exit(); }' > /tmp/bt.txt 2>&1
# bpftrace 自己 exit 才会打印 map; 被 timeout SIGTERM 时可能什么都不出。
# 输出里最大的栈在**最后**, 用 tail 而不是 head; 或用正则聚合 '\]: (\d+)'。
```

已知栈型 → 结论:

| 栈顶几帧 | 结论 |
|---|---|
| `_PyObject_ArenaMmap ← _PyObject_Malloc ← PyDict_SetItem ← scan_once_unicode / scanstring_unicode` | **高频 json 解析**(轮询循环每拍全量 `json.load`) |
| `_PyObject_ArenaMmap ← … ← PyUnicode_New / dict_merge` | 高频拼字符串 / 建字典(日志格式化、扁平化) |
| `sysmalloc_mmap.isra.0 ← _int_malloc ← __libc_malloc` | C 侧大块 malloc(OpenCV/numpy/字体) |
| `PyArray_*` 相关 | numpy 数组分配 —— 看是否有 `concatenate`/`np.zeros` 在刷新路径里 |

辅助: `py-spy record -f raw -r 100 -d 45 -o /tmp/x.folded --pid <pid> --nonblocking` 后按栈聚合看 CPU 热点。
**CPU 热点 ≠ 分配点**, 但能指路(本轮热点是信号页采样循环, 分配就是它里面的 json 解析)。

尺寸分布也抓一下: `@sz[args->len] = count()`, 非 2 的幂的怪尺寸(147456/512000/552960…)都是 4096 的倍数,
说明走的是 malloc 的 mmap 路径而不是大数组直接 mmap。

## 4. 修法(按命中类型)

1. **高频重复解析** → 按 `(mtime_ns, size)` 缓存解析结果。缓存键必须含 **size**(同秒重写但内容不同),
   返回**副本**给下游, **age/帧龄这类随墙钟变的字段在命中路径上单独刷新**。
2. **缓冲预分配** → 惰性初始容量 + 分档上限: `CAP_MIN`(初始 64KB) / `CAP_SOFT`(没在显示的上限) /
   `CAP`(真在屏上画的才允许长)。**不要**用"被读取过"当"在显示"的判据 —— 刷新树/状态栏也会读。
3. **每次刷新都新建数组** → 复用预分配连续缓冲 + 版本缓存(`(n, head, cap)` 做 key), 环形缓冲回绕时
   用 `copyto` 进预分配缓冲, 不要 `concatenate`。
4. **元数据被当数据画** → 给"同时显示"设上限(如 64 条), 并记一条日志说明裁掉了多少, 不静默。
5. **glibc arena 只增不还** → 启动器与 IDE launch 配置**两处**都加:
   `MALLOC_ARENA_MAX=4` + `MALLOC_TRIM_THRESHOLD_=131072`。

## 5. 采样缓存定式 (Python)

```python
_RF_CACHE = {}          # abs path -> ((mtime_ns, size), parsed)
_RF_CACHE_MAX = 256

def read_file(...):
    try:
        st = os.stat(p)          # 注意: OSError 要直接返回, 别拿它当"解析失败"
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _RF_CACHE.get(p)
    if hit is not None and hit[0] == key:
        return {"fields": dict(hit[1]["fields"]), "ts": hit[1]["ts"],
                "age_s": round(max(0.0, time.time() - st.st_mtime), 2)}   # 只刷新会变的
    raw = json.load(open(p, encoding="utf-8"))
    parsed = {"fields": read(prefix, raw), "ts": float(raw.get("ts") or st.st_mtime)}
    if len(_RF_CACHE) >= _RF_CACHE_MAX:
        _RF_CACHE.clear()
    _RF_CACHE[p] = (key, parsed)
    return {"fields": dict(parsed["fields"]), "ts": parsed["ts"],
            "age_s": round(max(0.0, time.time() - st.st_mtime), 2)}
```

实测收益: 40 秒内 >200KB 的 mmap 从 **426 次 → 0 次**。

## 6. 判据怎么写(这是交付的硬证据)

小脚本 + 落盘 JSON, 五条起步:
1. 文件没变: N 次读取只解析 **1** 次(用 monkeypatch 包住 `json.load` 计数)
2. 返回的是副本: 下游改了字段, 缓存不被污染
3. 文件一变: 立刻重新解析并拿到新值
4. **age_s / 帧龄每次调用都刷新**(不被缓存冻住)
5. 高频入口(如 `topics()`)连调 20 次: 解析次数 ≤ 少数几次(**允许个别唯一依据正在被写 ⇒ 正常重解析**, 断言 `== 0` 会误报 FAIL)

## 7. 报告口径 (用户会拿它当结果看)

- 改一处、测一处: 重启后采 5/10/20 分钟三点 RSS, 出 **GB/h 前后对比**。
- **只认“增速掉下来”**。单点 RSS 变小、或“分配次数归零”都不是全部结论。
- 没完全止住就写「从 X GB/h 降到 Y GB/h, 剩余 Z 未定位」, **不写“已根治”**;
  同时把兼底说清楚(看门狗阈值 / 自动拉起 / 日志路径)。
- 配器级旋钮(arena)单独提一句: 它可能只是次要项 —— 本轮加了 `MALLOC_ARENA_MAX=4` 仍按原速涨,
  真正的大头是解析缓存。**先修分配量, 再考虑分配器参数**。
