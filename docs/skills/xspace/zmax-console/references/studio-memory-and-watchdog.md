# 控制台内存泄漏 / 看门狗 / 重启

studio.py 是长期常驻的 PyQt5 GUI(用户经常开着不关), 它的内存问题是**整机事故**, 不是“控制台慢一点”。

## 1. 事故形态(已有实录)

单实例跑 8h53m → RSS **20.2GB** + swap 8.5GB ⇒ 内存+swap 双耗尽 ⇒ 全局换页 ⇒ Mutter 卡死 ⇒ 只能强重启。
内核 **没有** OOM-kill 记录(`journalctl -b -1` 无 `Out of memory`/`Killed process`, `systemd-oomd` 无动作) ——
这是 "thrash 到无响应", 别按 OOM killer 去查。

排查方法论(段级 diff + bpftrace 抓 mmap 用户栈)见 `linux-host-maintenance` 的 §12 与
`references/process-rss-growth-forensics.md`。

## 2. 信号页的五处内存结构(改一个不算改)

1. **每信号预分配大环形缓冲** —— `canoe_graphic.SignalBuffer` 原本 `np.zeros(CAP)`×2 且 `CAP=200000`
   ⇒ **3.05MB/信号**(不管有没有数据) × 1013 个 key = 3.1GB。
   改法: `CAP_MIN`(4096, 64KB) 惰性扩容 + `CAP_SOFT`(32768, 未显示上限) + `CAP`(只给真在屏上画的曲线)。
2. **"在显示"的判据不能用 `arrays()`** —— 刷新树/状态栏也会调 `arrays()`, 在那里标 `_used=True` 会让 1013 个信号
   全部当成"在显示" ⇒ 又回到 3.1GB。**只有真正渲染曲线的 `_refresh_inner` 才能标记**。
3. **`arrays()` 回绕时 `concatenate`** —— 每次刷新新建 n×8 字节(strace 里 1MB 级 mmap 5.7 次/秒)。
   改法: 复用预分配连续缓冲 + `(n, head, cap)` 版本缓存, 回绕用 `copyto`。
4. **元数据字段被当曲线画** —— `ds.<话题>` 前缀下的 `hz/count/qos/allowed` 这类 829 个字段会被一次全选, 全都长到 CAP。
   改法: `MAX_CURVES` 限制同时显示条数(如 64) + 裁掉时用 note 说清数量, 不静默。
5. **高频全量 json 解析(真根因)** —— `host_sources.topics()` 被主循环 ~10Hz 调用, 而它对 `FILES` 里 14 个文件
   **每个都全量 `json.load` + flatten**, 不看文件变没变 ⇒ 每秒上百次解析、上万个临时 dict/str ⇒
   CPython pymalloc arena 只增不减(bpftrace 栈: `_PyObject_ArenaMmap ← _PyObject_Malloc ← PyDict_SetItem ← scan_once_unicode`)。
   改法: `read_file()` 按 `(mtime_ns, size)` 缓存 —— 文件没变就零解析, 只刷新 `age_s`(帧龄)。
   实测: 40 秒内 >200KB 的 mmap **426 次 → 0 次**。

## 3. 判据脚本(改完必须跟一个)

| 脚本 | 覆盖 |
|---|---|
| `tools/verify_signal_buffer_grow.py` | 惰性扩容省内存且不改语义(与朴素 list 逐点一致、回绕顺序、CSV 导入不被截断、`arrays()` 不污染 `_used`、零分配) |
| `tools/verify_host_sources_cache.py` | 50 次读只解析 1 次、返回副本、文件一变立刻重解、`age_s` 每次刷新、`topics()` 连调不产生额外解析 |
| `tools/probe_rss_seg.py` | 段级 RSS 增长定位(也用于验收) |

判据写法坑: 断言高频入口"解析次数 == 0"会误报 FAIL —— 总有个别唯一依据正在被写(mtime 变了), 正常重解析。
断言用 `<= 少数几次`。

## 4. 看门狗 + 自动拉起(必须成对)

```bash
bash tools/install_studio_mem_guard.sh      # zmax-studio-mem-guard.service + .timer(每 2 分钟, User=ubuntu)
tail -3 zmax_data/ops/studio_guard.log      # JSONL 台账
python3 tools/studio_mem_guard.py --status  # 只看现状
```
- 三档阈值: 单实例 `STUDIO_MAX_GB`(默认 8) · 孤儿(`ppid==1` 且 `debugged`) `STUDIO_ORPHAN_GB`(2) · 合计 `STUDIO_TOTAL_GB`(12)。
- 想早兜就写 drop-in: `/etc/systemd/system/zmax-studio-mem-guard.service.d/threshold.conf` 改 `4`/`6`,
  **但阈值要按实测增速算**(1.5GB 起 + 5GB/h ⇒ 8GB 要 1.3h 才动作)。
- **杀掉必须自动拉起**(`STUDIO_AUTO_RESTART=1` 默认开): 只 SIGTERM 不拉 ⇒ 用户看到的是"控制台自己没了"
  却不知道原因。拉前要 `sleep 3` 再用 `scan()` 复核, 否则会把刚杀的算成"还在跑"而不拉;
  只在**全杀光**时才拉, 否则会开第二个窗口。

## 5. 重启控制台(不要反复重启, 但该重启时要会)

```bash
bash tools/restart_studio.sh
```
- 必须 `export DISPLAY=:0` + `XAUTHORITY=/run/user/1000/gdm/Xauthority` + `PYTHONUNBUFFERED=1` + `setsid nohup … &`;
  窗口上屏约 11~14s, 日志 `zmax_data/ops/studio.log`。
- **按 `comm` 过滤 pid**, 不要 `pgrep -f "studio.py"`: 脚本自己 + 调用它的 shell 的 cmdline 里都含这个串, 会自杀
  (`exit -15`, 后续步骤全不执行, 用户看到"窗口闪没了"). 定式见 `linux-host-maintenance` §10b。
- **IDE 侧也要跟**: `.vscode/launch.json` 里 `"🚀 全新调试进程 (studio.py)"` 的 `env` 要加
  `MALLOC_ARENA_MAX=4` / `MALLOC_TRIM_THRESHOLD_=131072`。用户平时是 F5 起控制台, 只改命令行启动器等于没改。

## 6. 未完项(下一轮第一件事)

四处修完后仍 ~3.5GB/h(原 5GB/h), 形态是**每 2 分钟一批 ~120MB 的周期分配**, 尚未定位到具体代码。
下一轮不要从零开始: 直接 `probe_rss_seg.py --wait 150` 跟一个完整周期, 再用 bpftrace 抓那一波的 `ustack`。
