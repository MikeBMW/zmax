# 离屏 GUI harness: 点真按钮验控制台行为(不打扰现场在跑的窗口)

用途: 改 `tools/gui/simulink_module.py` 的按钮/标题/播放态逻辑后, 要给出"真点了、真变了"的证据。
别启动第二个可见控制台, 也别让用户先重启再试 —— 用 offscreen 建一个, 逐项打印。

## 骨架

```bash
cd ~/zmax && QT_QPA_PLATFORM=offscreen timeout 280 ./gui-venv311/bin/python - <<'PY'
import sys, time, json
sys.path.insert(0, 'tools'); sys.path.insert(0, 'tools/gui')
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
app = QApplication([])
import simulink_module as sm

# ① 模块级函数要打到**模块**上: sm._canvas_src_state 是模块函数, 不是实例方法
sm._canvas_src_state = lambda *a, **k: 'AR场景'

m = sm.SimulinkModule(None) if hasattr(sm, 'SimulinkModule') else sm.Module(None)
m.nodes = [{'id': 'ssplan', 'params': {'state_space': True}}]   # 让 start_sim 走 AR 分支

# ② 别污染现场日志: harness 写的行会和真控制台混在 /tmp/simulink_log.txt
m._log = lambda *a, **k: None
...
PY
```

## 三个坑(都真的坑过)

1. **`sm._canvas_src_state` 必须改模块属性**。写成 `m._canvas_src_state = ...` 只加了个实例属性,
   `start_sim` 里调的是模块级函数 ⇒ 分支仍然不进 AR, 白跑一轮还以为代码没生效。
2. **harness 会写现场日志**。`_log` 默认往 `/tmp/simulink_log.txt` 追加, 于是日志里出现
   "用户根本没点过"的行为 ⇒ 误判成现场还在跳变。跑 harness 前把 `m._log` 换成空函数。
3. **断言时序要够长**。播放态收口是 1s 轮询 + 退避纠错, 干扰写者可能 0.5s 一次;
   短于 4~5s 的窗看不出"还会不会跳"。要做**敌意测试**: 自己每 0.5s 强行 `btn_run.setText('▶ 运行')`,
   连写 4.8s, 然后断言"期间只观察到一种文字"。

## AR 播放态一次性验收脚本(可直接抄)

```python
out = []
def snap(tag): out.append((tag, m.btn_run.text(), m.btn_run.isEnabled(), m.btn_stop.isEnabled(), m.windowTitle()))
snap('初始')
m.start_sim(); app.processEvents(); time.sleep(0.5); snap('点运行')
for _ in range(10):                       # 敌意写 4.8s
    m.btn_run.setText('▶ 运行'); app.processEvents(); time.sleep(0.5)
snap('敌意后')
m.stop_sim(); app.processEvents(); time.sleep(0.5); snap('点停止')
m.start_sim(); app.processEvents(); time.sleep(0.5); snap('再点运行')
for r in out: print(r)
```

期望: `点运行` 与 `敌意后` 的文字**完全一致**(⏸ 停止 AR 播放 (运行中)), `btn_stop.isEnabled()` 为 True;
`点停止` 后回到 `▶ 运行` 且 btn_stop 回灰; `再点运行` 又回到播放态。
任一条不符 ⇒ 别汇报"改好了"。

## 页面侧的对应验收(真浏览器)

- 布局零跳动: 分别取 `开关关 / 开 / 跟随 / 回关` 四态下, 同一个不相关按钮的
  `getBoundingClientRect().top` 和左栏 `scrollHeight`, 四态必须**完全相等**。
- 画面在动: `#vr` 画布像素哈希取两次比对, 同时读 `ARCMD.seq` 必须推进。
- 相机不漂: 跟随中隔 3s 读两次 `VR.tgt` / `VR.dist`, 必须**逐位相同**。
