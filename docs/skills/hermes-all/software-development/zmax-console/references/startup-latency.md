# 控制台启动时延 (studio.py)

## 什么时候看这个
- 用户说「点快捷方式好长时间才看到主界面」/「第一次点了没反应」/「得等半天」
- 刚把页面改成延迟构建，判据/探针突然全红（页面「0 控件」）
- 要给启动做提速，需要改前/改后的同口径数字

先分清是不是**桌面这一侧**的问题: 启动脚本(pgrep/notify-send/exec) 全链实测 ≈0.2s,
基本可以排除; 真瓶颈在 python 侧。

## 测量: 用 Xvfb 冷启, 别在用户桌面上重启他的控制台
```bash
setsid Xvfb :99 -screen 0 2400x1500x24 >/tmp/xvfb.log 2>&1 </dev/null &
DISPLAY=:99 xdpyinfo | grep -m1 dimensions     # 先确认 X 起来
```
冷启测量**写成脚本文件**再执行(内联 & 会被工具拒; `pkill -f "DISPLAY=:99"` 会杀掉自己的 shell):
```bash
T0=$(date +%s.%N)
DISPLAY=:99 ZMAX_BOOT_PAGE=config ZMAX_BUILD_TRACE=1 setsid <venv>/bin/python studio.py >/tmp/cold.log 2>&1 </dev/null &
for i in $(seq 1 900); do
  W=$(DISPLAY=:99 xdotool search --onlyvisible --name "XSpace ZMAX" | head -1); [ -n "$W" ] && break; sleep 0.05
done
python3 -c "print('窗口 map: %.2fs' % ($(date +%s.%N)-$T0))"
```
- **先确认 0 个残留窗口**, 否则量到 0.0s 假数据。清理写脚本: 扫 `/proc/*/cmdline` 含 `studio.py`
  且 `/proc/*/environ` 里 `DISPLAY=:99` 的 pid, `kill -9`。
- `ZMAX_BUILD_TRACE=1` 会额外打「分段」每页构建时刻 + 「按需 key (ms)」+ 「全部页面真建完成」。
- `xdotool search --name` 一个窗口可能报两个(第一个是 `mutter-x11-frames` 的框) ⇒ 按 pid 去重再算。

## 实测分解 (3200x2000 本机, Xvfb 冷启, 与真机日志误差 <0.3s)

| 段 | 改前 | 改后 |
|---|---|---|
| 解释器 + import + QApplication | 0.20s | 0.20s |
| YOLO 依赖链预热 import (主线程, 挡在 splash 前) | 1.20s | 0 (挪到窗口后) |
| 建全部页面 | 4.30s | 只建首页+配置中心 1.30s |
| `win.show()` 首次 polish/布局整棵控件树 | 2.80s | ≈1.0s |
| **合计到主界面可见** | **8.66~8.96s** | **3.12~3.36s** |

单页成本(占位前实测): 配置中心 1.17 · 插拔场景 1.09 · 数据集 0.54 · 评估 0.54 · 硬件 0.25 · 监控 0.17 · 参数中心 0.12.
`win.show()` 的 2.8s 与控件总数强相关(全局 QSS 逐控件 polish) ⇒ 少建页 = 少 polish, 两项一起降。

## 改法(已落地, 照这个顺序做)
1. **splash 最早出现**: 主线程 import 链预热(YOLO/metaworld)一律挪到 `win.show()` 之后, 用 `_oneshot(win, 900, fn)`。
   铁律不变: import 链必须主线程且 `QApplication` 之后(放后台线程会 QObject::moveToThread + debugpy abort)。
2. **占位 + 后台泵(空闲驱动, 不是固定节拍)**: 除「开局就要的两页」(`home` 首页 + `config` 配置中心 —— 首页是开机第一眼,
   配置中心是下一步必点) 外, 每个页先 `QWidget()` 占位登记
   `self._lazy_pages[idx] = (key, builder, placeholder)`。
   真建走 `StudioMainWindow.start_idle_build(app, yolo_warm)`, 五条缺一不可:
   ① 挂 `QAbstractEventDispatcher.instance().aboutToBlock` 判「队列真空了」;
   ② **最近 2s 内有滚轮/鼠标/键盘输入 ⇒ 一个页都不建** (装一个 app 级 eventFilter 记 last_input 时间);
   ③ 两次建页间隔 ≥0.8s;
   ④ 按 `zmax_data/page_build_ms.json` 里上次实测耗时**轻的先生、重的最后**(inference 18ms … plugging 2.3s);
   ⑤ YOLO 依赖链预热排在所有页建完之后。
   真建时 `insertWidget(idx, real)` → `removeWidget(placeholder)` → `placeholder.deleteLater()`, **索引净位移 0**。
3. **`_on_nav(target)` 第一步**: 目标是占位就先 `_realize_page(idx)` —— 否则点过去是空白页(这是最容易漏的一环)。
4. **后插入的页会推后所有索引**: 画布 `_init_simulink` 用 `insertWidget(self._simulink_index, sim)` 插回原位,
   它后面的页整体 +1 ⇒ 插完必须遍历 `stack.indexOf(obj)` 重算 `self.modules`。
   不要信任构建时算的 index(spec/params 曾长期 off-by-one, 只因导航分支里临时重算过才没暴露)。
5. **判据/探针必须显式收口**: 任何 `StudioMainWindow()` 之后紧跟 `win.materialize_all()`
   (一把把占位全真建 + 建画布)。线上才走 120ms 泵; 判据里跑泵会拿到半成品。
   受影响的是所有建主窗口的 probe/verify(pages_sweep / param_center / platform_spec / library_sync /
   project_archive / cfg_table_fit / canvas_menu / open_space / overlay_start_debug)。

## 量「窗口能不能拖/能不能滚」—— 进程内探针, 别靠肉眼
新建一个 `QTimer(50ms)` 记相邻 tick 的时间差, 同时每 100ms 用 `QApplication.postEvent` 往首页滚动区投一个
`QWheelEvent`, 跑 6s 后打印: 最大停顿 / 平均间隔 / 滚轮命中次数 / 期间建了几个页。
口径: **最大停顿 = 用户感知的卡顿**; 滚轮「命中」= 滚动条值变了或已在底部(到底后无位移是正常的, 别当成没响应)。
探针必须调**与线上同一个函数**(`start_idle_build`), 不要在手搭的窗口里复制一份泵 —— 两份代码一定漂。

## 坑
- **离屏建主窗口会崩**: `QT_QPA_PLATFORM=offscreen` 建 `StudioMainWindow()` 会 core dump / Aborted(未 show 的 GL 控件+常驻线程)。
  验证一律 `QT_QPA_PLATFORM=xcb` + Xvfb `:99`, 不要在 offscreen 下断言「我的改动崩了」。
- **后台泵会阻塞主线程**: 单页 0.02~2.5s(插拔场景最重) —— 固定节拍(每 120/500ms 建一个)**一定**会被用户感知成
  「窗口出来了, 但滚轮十几秒没反应 / 卡一下动一下」。实测同一份代码: 固定节拍下 12 个页连拍, 事件循环最大停顿 2938ms;
  改成空闲+2s 静默门槛后, 连续滚 6s 期间**建页 0 个**、最大停顿 953ms(剩下的是画布初始化, 老代码本来就有)。
  判据: 泵的间隔/门槛可以调, 「有人操作时不许建页」这条不能省。
- **测试实例关闭会写工程档**: `closeEvent` 有「退出自动更新默认工程」⇒ 判据随后报
  `engineering_db check` 的「漂移 ['canvas']」是测试副作用, 重跑一次 check 即恢复, 不要当回归。
- **重启后先证「活着」再报时延**: 杀旧实例 → 脚本启动 → 必须同时看到 ①`pgrep -f studio.py` 有新 pid
  ②`wmctrl -l` 有 `XSpace ZMAX` 窗口 ③日志里 `🚀 首个界面: …` 三样齐了才念启动数字。
  只看到「点击→可见 0.01s」通常不是快, 而是旧窗口还在或新进程已被 SIGTERM (日志尾行
  `收到信号 15 → 正常关闭界面后退出`) ⇒ 这时屏幕上其实一个控制台都没有。
- **别只看总量**: 一定要拿到分段(每页/每段时刻), 否则「慢」只能猜; 用户问的是「为什么慢」, 答案必须是分解。
- **改默认落点/默认值时, 同批 grep 判据里的硬编码字符串**: `grep -rn 'or "config"' tools/verify_*.py` ——
  判据常把默认值当字面量写死, 默认一变就假红(或假绿)。改默认值时一并把判据断言改成新口径,
  并在判据注释里写清"为什么口径变", 而不是把判据删掉。
- **落点页变了要同步把"首个界面"印进启动日志**(`🚀 首个界面: <类名> (stack[i])`): 用户问"第一眼是什么",
  要能用一行日志复现, 不靠自述或截图。
