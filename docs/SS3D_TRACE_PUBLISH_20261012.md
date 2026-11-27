# 信号分析「运行不起来/不动」真根因与修复 (2026-10-12 老倪)

> 老倪原话: 「你来运行 任务1,信号分析运行啊，动起来」

## 症状

在配置中心激活 任务1(插拔) 后,让我跑 任务1 并在 **实时监控 · 信号分析** 里看波形 ——
窗口能开、信号树在、`当前值`列有数,但**波形不跟着运行走**(永远停在"停下的那一刻")。

## 真因链 (逐步实测, 不是推断)

1. 信号分析读 `zmax_data/ss_live/trace_live.json`(它把 ≤2s 视为新鲜; 超时就把竖线停在最后一次)。
2. 这份快照的**唯一写入者**是 3D 面板渲染帧时的 `ss_dreamview.publish_trace_live()`。
3. `_ss_tick`(画布播放, 30ms/tick)只对 `self._ss_3d_windows` 里的窗口调 `set_frame(idx)`。
4. `open_ss_3d` 有**三条出口**, 其中「把 Sim&Real 页里内嵌的 live DreamView 拎成独立窗口」
   是 **提前 return** 的 —— 它是**唯一没登记进 `_ss_3d_windows`** 的路径(新建分支在下方 append)。
   ⇒ 该窗口不喂帧 ⇒ 3D 不渲染播放帧 ⇒ **快照不写** ⇒ 信号分析不动。
   实测证据: 运行结束后 `trace_live.json` 帧龄 700s+ 不刷新。

## 修复 (两处)

* `tools/gui/simulink_module.py` · `open_ss_3d` 提前 return 分支: 照样登记 `_ss_3d_windows`
  + 绑 `module`(3D 上 ▶运行/⏹停止 = 同一引擎) + 把 `self._ss_tr` 推给窗口 + 留日志。
* `tools/gui/simulink_module.py` · `_real_finish`: 播放前把**本轮**轨迹 `set_trajectory(tr)`
  推给在册 3D 窗口(否则窗口 tr 还是上一轮/离线 episode, `set_frame(idx)` 画错帧)。
* `tools/gui/studio.py` · `_run_ss_cmd`: 画布为空时先 `open_state_space()` 再跑
  (实测新起进程里画布是空的 ⇒ 直接 start_sim 只打印「⚠️ 画布为空」静默失败)。

## 判据 (真跑)

`tools/verify_ss3d_trace_publish.py` — **11/11 PASS**: 发布者/读取者同一份文件 · 复用分支返回的
窗口被登记(修前 len=0) · 绑定 module · 推 `self._ss_tr` · 标题 3D场景 · 留日志 · `_real_finish`
有本轮轨迹推行 · `_ss_tick` 每 tick `set_frame(idx)` · `publish_trace_live` 在 HUD 更新路径 · 节流键名无碍。

## 真机端到端实测 (修后, 任务1 · 插拔场景)

命令通道 `echo ss_canvas > /tmp/zmax_nav_cmd` → `echo ss_run > /tmp/zmax_nav_cmd`:

```
t+14s trace帧龄=0.0s 帧=24/356  阶段=接近        场景t=2.4s
t+16s trace帧龄=0.0s 帧=90/356  阶段=下降        场景t=9.0s
t+18s trace帧龄=0.0s 帧=157/356 阶段=抬起        场景t=15.7s
t+20s trace帧龄=0.0s 帧=222/356 阶段=转移        场景t=22.2s
t+22s trace帧龄=0.0s 帧=289/356 阶段=插入·接触    场景t=28.9s
t+24s trace帧龄=0.0s 帧=356/356 阶段=完成        场景t=35.6s
估计误差 mm: 2.669 → 1.311 → 7.418 → 0.822 → 1.444 → 0.547
```

**屏幕上也在动**(不是只有文件在写): 实况期(帧龄<2s)对信号分析窗口连拍, 相邻两张平均像素差
**8.01 / 7.69 / 8.02**(帧 37→133→230); 运行一停落到 0.01(按要求停在"停下的那一刻")。
引擎日志: `════ 🧮 状态空间仿真完成 ════ / ✅ 插入完成 · 用时 35.60s · 最终距离 0.0653m`。

## 生效方式

GUI 代码改动要重启控制台才生效(本次已重启并核对窗口标题 v5.49.2 + 新日志行)。
命令通道小改(`_run_ss_cmd` 自动载画布)已入库, 下次重启生效。
