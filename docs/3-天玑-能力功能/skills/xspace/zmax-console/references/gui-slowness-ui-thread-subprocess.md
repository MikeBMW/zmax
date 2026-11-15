# GUI 慢/卡顿: UI 线程被自己堵住（子进程 / 大 JSONL / 全盘 du 三类）

## 症状
点画布节点（右键菜单）、翻页一顿一顿；但 `curl http://127.0.0.1:8799/` 仍然 <1ms。
⇒ **不是服务慢、也不是机器不行**，是 Qt 事件循环被堵住。用户此时问“GUI 怎么还是这么慢”，不要拿负载数字回他。

先取证再改：**一次 profile 定乾坤**，不要靠猜。
```bash
sudo py-spy record --pid $(pgrep -f '/gui-venv311/bin/python studio.py') \
     --duration 15 --rate 60 --format raw --output /tmp/studio.raw
# 再按叶子/栈内频次聚合 (raw 格式是 '栈; 栈; 叶子 N')
```
聚合时同时看 **叶子热点** 和 **栈内 5 层高频**：叶子告诉你时间花在哪，栈内高频告诉你谁在触发它。

---

## 第一类: UI 线程里的同步子进程

### 判据
```bash
sudo py-spy dump --pid $(pgrep -f '/gui-venv311/bin/python studio.py')
# 主线程栈: select (selectors.py) ← _communicate ← communicate ← run (subprocess.py:550)
#           ← _poll_train_state ← _poll_ext_log ← _show_node_menu ← mousePressEvent
ps -eo pcpu,pid,args --sort=-pcpu | head   # 同时能看到 GUI 拉起的长命令在吃 CPU
```

### 机制
点击路径 `mousePressEvent → _show_node_menu → _poll_ext_log → _poll_train_state` 里：
- 每次调用 `subprocess.run(["pgrep", "-f", "lerobot_train"], timeout=5)`，同步等最长 5s；
- 点一次就重读一遍日志文件；
- 子进程一慢（`du` 扫大目录）整个窗口冻住 ⇒ 用户感知为“GUI 越用越慢”。

### 修法（三件缺一不可）
1. **检测类工作绝不在 UI 线程 spawn 子进程**：改纯 `/proc` 扫描取 cmdline。
   287 进程全扫实测 ≈17ms，直接放点击路径仍可感 ⇒ 必须再加 **缓存 + daemon 线程刷新**
   （TTL 5s，stale 起后台线程，busy 标记防排队），UI 侧只读缓存 = 0 等待。
2. 点击路径上的轮询加 **0.3s 节流**，不要每次点击都读文件。
3. 磁盘体积统计（`du -sm`）一律不进 UI 路径。

---

## 第二类: QTimer 里全量解析大 JSONL（最容易被忽略的一类）

### 判据
profile 叶子出现 `raw_decode (json/decoder.py:353)` 占 40%+，栈内高频是某个控件的 `reload()`：
```
41.8%  raw_decode (json/decoder.py:353)
48.8%  reload (su2_traj_ball.py:268)   ← 栈内
```
逐条看该 reload 里的来源分支，**每一路各自算账**：老的一条修好了不代表另一条也修了。
```bash
ls -lhS zmax_data/ss_live/*.jsonl | head          # 找出真正的大文件 (实测 106MB / 17.3 万行)
# 量一次“全量解析要多久”，跟定时器周期比
```

### 机制
`QTimer(1500ms)` 里 `for line in f: json.loads(line)` 读一个 10Hz 永久追加的 jsonl：
**单次解析 2.219s > 周期 1.5s** ⇒ 事件循环永远追不上，表现为「一直卡」而不是「偶尔卡」。
仅 >>周期 才致命；只比周期小一点是「越用越慢」（文件在长大）。

### 修法: 尾部读 + 按 (mtime, size) 缓存
```python
_TAIL_CACHE = {}   # path -> ((mtime, size), [dict,...])

def _read_jsonl_tail(path, tail_bytes=1 << 20, limit=400):
    st = os.stat(path); sig = (st.st_mtime, st.st_size)
    c = _TAIL_CACHE.get(path)
    if c and c[0] == sig:
        return c[1]
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END); size = f.tell(); start = max(0, size - tail_bytes)
        f.seek(start); blob = f.read().decode("utf-8", "ignore")
    lines = blob.splitlines()
    if start > 0 and lines:
        lines = lines[1:]                  # 首行可能是被切断的半行, 必须丢
    out = []
    for ln in lines[-limit:]:
        try: out.append(json.loads(ln))
        except Exception: continue
    _TAIL_CACHE[path] = (sig, out)
    return out
```
- 签名用 `(mtime, size)` 而不是只 mtime：同秒内多次追加也能命中。
- 遥测类数据只需要「最新 N 条」，不需要全历史 —— 这是能尾部读的前提。
- 实测 2.219s → 0.022~0.034s（65~100 倍），缓存命中 0.00002s，轨迹点数不变。

### 验收（不必重启用户的 GUI）
离屏实例化**真组件**再计时，比看代码猜可信：
```bash
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python - <<'PY'
import time; from PyQt5.QtWidgets import QApplication; app = QApplication([])
from su2_traj_ball import SU2TrajBall
w = SU2TrajBall()
for _ in range(3):
    t = time.time(); w.reload(); print('reload %.4fs · traj=%d' % (time.time()-t, len(w.traj)))
PY
```
改完代码也要说清：**用户当前进程跑的是旧代码，需重开控制台才生效**（别答“已修好”）。

---

## 第三类: 常驻循环里的全盘 `du`

`tools/dds/publisher.py` 每 3s 调 `hardware_view.disk()`，内部 `du -sm /home/ubuntu/zmax`：
单次 2.1s / 260GB，等于连轴转。修法 = 容量口径换 `shutil.disk_usage()`，目录体积 `du` 退到
**600s TTL + 后台线程**（首拍返回旧值，不阻塞采集）；采集侧实测 0.001s。
凡「每 N 秒采集」+「扫目录/扫进程」的组合，一律先假设它是热点。

---

## 附带：systemd 单元 crash loop 也在吃 CPU
`systemctl status` 看 `NRestarts`：端口被手工进程占着时 unit 会 `exit 1` 每 9s 重启一次
（实测 18108 次，每次 ~10s CPU / 425MB）—— 曲线像“服务正常”，其实是双重占用。
停 unit 而不是杀手工进程（保留正在服务的那个），并说明重启计数冻结在哪。

## 降真实负载（可选，别当第一招）
先证 GUI 自己不再堵，再动服务：`cam_live_stream --fps 30→15 --quality 72→64` 实测 311%→119%（省 ~1.9 核）；
同轮对照 load 14.9→12.2、idle 47%→74%、cs 186k→88k/s。

## 边界
- 只停不起：用户说「你都重启好」= 授权重启 GUI 与该流服务；但 **8797 / 8793 挂着真动授权和 AR 页面，不要顺手重启**。
- 修改常驻进程后要明确告知「重启才生效」，并等用户点头再重启。
