# 信号分析页: 场景色标 / 目录树 / 「没看到某个信号」的收口

适用: 老倪说「插拔是绿色信号 / 没看到 / 加在 topic / 怎么这么多蓝色信号」这类关于「📈 实时监控 · Graphic 信号分析」页面的问题。页面实现 = `tools/gui/canoe_graphic.py`（`CanoeGraphicWidget`，控制台内嵌 tab 与独立窗口**同一个类**）。

## 真源与文件
- 打标真源 = `tools/sig_scene_tags.py` → `config/topics/scene_tags.json`（键 `signals`(信号名→场景) / `overrides`(人工·学习补充, 优先级最高) / `source_scenes`(来源族兜底)）；颜色/任务映射再来自 `tools/ss_scene_switch.py`（不重写）。
- 页面里的信号名 = `<源前缀>.<键名>`，前缀表在 `canoe_graphic.HOST_SOURCES`：`sstrace`(trace_live.json) / `pose` / `state` / `safety` / `yolo` / `space` / `ar`(ar_aoi_live.json)。**页面只列「源文件里当前出现的键」** ⇒ 想加一个信号, 先确认它真在某个源文件里落盘。
- `config/topics/` 是**符号链接**（真身在仓库外）⇒ 改完标签 `git status` 看不到该文件, 别以为没写进去（用 `git check-ignore -v` / 直接读文件核）。

## 给某场景加信号（顺序）
1. 确认信号真在源文件里（`python -c` 读源 JSON 看键）。
2. 写 `overrides`（**人工补充优先级最高**, 已有一例 `ins_depth_m → 插拔场景`；`--tag` 只回读不写）: 载入 JSON → 更新 `overrides` → `tempfile`+`os.replace` 原子写 → 回读比对。
3. `./gui-venv311/bin/python tools/sig_scene_tags.py --build --from-runs` 重建（会保留 overrides, 并扫 `zmax_data/task_runs/` 的运行证据）。
4. `--tag "<名>"` 逐个回读核色（如 `#2e8b57` 插拔 / `#1f6feb` 摆盘 / `#8957e5` AR / 白=未分类）。
5. 出判据 + 重启窗口（见下）。

## 一条源被多个场景共写 ⇒ 不能按标签二选一（本节是老倪纠正过的口径）
- `sstrace` 源（`zmax_data/ss_live/trace_live.json`）是**插拔(SS-EPI-CORNER) 与 摆盘(SS-TRAY-PLACE) 两个 3D 面板共写的唯一快照**（见 `ss_dreamview.publish_trace_live` 的防串台注释）。同一批键（`光模块_x`/`末端_x`/`接触概率`/`时间_s`/`帧`…）两个场景都要用。
- 旧口径「每个键按标签只归一个组」⇒ 这些键被标给摆盘后, 插拔区**看着缺一半**, 另外半个跑到蓝组去 = 老倪说的「为什么还有很多蓝色场景的信号也加在了」。
- 正确口径: **同一份共写源的键, 在每个场景区域各自重新加载一份, 行色 = 它所在区域的场景色**；非共写源仍按打标单一归组。实现: `canoe_graphic._fill_tree()` 对 `sstrace.` 前缀的键向 `("插拔场景","摆盘场景")` 各加一份, `_make_item(..., scene=<区域场景>)` 用区域色上色并注明「本场景区域加载」。
- 推论: 一个信号能不能/该不该染某场景色, 取决于**写它的源是不是该场景专用**, 不取决于键名好不好听。

## 改完标签/改完页面代码 → 必须重启窗口 + 出判据
- 信号目录树在**建窗时铺一次** ⇒ 加标签后不重启就永远看不到。重启专用脚本 `tools/gui/restart_graphic_window.sh`：
  · 匹配模式写成 `[p]ython .*tools/gui/canoe_graphic[.]py`（直接 `pkill -f "原文"` 会把含同串的自身 shell 也算上 → 自杀）；
  · 起窗前 `unset QT_QPA_PLATFORM QT_QPA_PLATFORM_PLUGIN_PATH QT_PLUGIN_PATH`（控制台带 `QT_QPA_PLATFORM=xcb` 时子进程去找 cv2 的 xcb 插件 → 直接退出，观感「点了没反应」）。
- 控制台内嵌 tab 是同一个类, 切走再切回会 `reload(force_tree=True)`；没同步就重启控制台。
- 判据 `tools/verify_scene_signal_green.py`（离屏真建 `CanoeGraphicWidget` → 逐行走树打印 组/行/前景色 → 断言）：
  ① 目标场景组内**零异色行** ② 共写源的键在两组各有一份且各自本区色 ③ 关键信号在组内。
  现场取证同理: `wmctrl -lG | grep 信号分析` 拿**真实几何**再裁图（窗口可能开在第二块屏 x≈2085, 用主屏坐标裁会得到空图 + 绿色像素 0），再用像素计数（绿/蓝 px）佐证, 截图给老倪。

## 页内信号名口径（插拔场景 · 状态空间源 = trace_live.json）
- `sstrace.前馈速度_mps` = u_ff（前馈加速器输出）→ **`sstrace.动作调制_mps` = ‖u_fuse_vec[:3]‖（动作调制器的输出）** → `sstrace.安全边界_mps` = u_limit（安全执行边界饱和限幅后）；导出这一帧数值的是 `tools/gui/ss_dreamview.py`（3D 面板同帧同值）；画布节点 = 「🧭 动作调制器」(`sssched`, 源码 `src/lerobot/policies/left_right/state_space/cognition.py::def decide`)。
- 这一路只在 **3D 播放/回放**时才刷新 ⇒ 帧龄列可能显示几千秒；常驻引擎回路那一路的动作出口是 `zmax/ss_engine` 的 `action`/`action_norm`（`engine_latest.json`, 帧龄 0.1s）。老倪问「哪个 topic」时把这两路分开说, 别混。
- OCR 认这类名字会丢下划线（`动作调制_mps` → `动作调制mps`）, 不是页面缺字。
