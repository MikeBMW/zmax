# 首页「功能模块」整块消失 / 右上角三灯不亮 —— 取证与修法 (2026-10-23 现场)

## 1. 现象与根因

现象: 主控制台首页只看到 `功能模块  Modules` 这一行标题, 下面整块空白; 滚轮/End 都滚不动(内容没溢出),
窗口任何位置都找不到模块卡。

根因 (在 `tools/gui/studio.py::ReflowCardRow`, 自适应卡片行的自定义容器):
- 卡片只在 `reflow_for(width)` 里真正 `addWidget` 进内部 `QGridLayout`;
- 而 `reflow_for` 在 `width<=1` 时直接 return, **showEvent 那刻父级还没布完尺寸** ⇒ 网格一直是空的;
- 网格空 ⇒ `minimumSizeHint()==0` ⇒ 外层 QVBoxLayout 按"可以压到 0"处理, 于是整块被压成 0 高,
  卡片就算后来建出来也永远看不见 (观感 = "功能模块没有了")。

修法 (两处, 已落地):
1. `reflow_for()` 末尾按网格实际高度**给出最小高**: `self.setMinimumHeight(self._grid.sizeHint().height())` + `updateGeometry()`
   —— 外层布局再也压不掉它 (列数变了会重算)。
2. `showEvent` 改成 `QTimer.singleShot(0, lambda: self.reflow_for(self.width()))` 延后一拍再排;
   `resizeEvent` 里照旧 reflow (窗口拉宽/拉窄 3→2→1 列)。

验收口径(必须真看到卡): 窗口 xwd 截图 → 滚轮向下 → OCR 出现 `数据集管理 / 模型引擎 / 硬件工具箱 / 系统架构 / Simulink模式 / 配置中心`;
修前滚到最底也只有一行 `系统 · 平台底座…` 组标题。

## 2. 右上角三色状态灯 (550C / GPU 训练)

口径 (老倪 2026-10-23 覆盖旧口径, 唯一依据 `tools/status_lights.py`):
- **绿 实心常亮 = 已连上 550C** (Intel 端侧 `/health` 真拿到 JSON; 隧道端口在听**不算**连上)
- **红 实心常亮 = 没连上 550C** (与绿互斥, 任一时刻恰好一个亮)
- **黄 1s 周期闪 = 本机 GPU 在训练** (训练进程在场 且 GPU 20s 滑窗平均 >50%)
- 旧口径(绿=功能正常/红=真机联调+授权)那套证据不删, 降级进 tooltip: `green.func` / `red.detail`。

接线: `studio.py::_build_menubar` 里 `mb.setCornerWidget(status_widget, TopRightCorner)` (品牌标签 + 三颗 14x14 QLabel),
`_render_lights()` 每 250ms 按真状态上色 (绿/红实心, 黄按相位闪)。采样子线程 `_StatusLightFetcher` 每 2s 跑一次源脚本。

### 取证方法 (窗口被别的窗口挡住也能取)
```bash
WID=$(xwininfo -root -tree | grep '"studio.py"' | awk '{print $1}' | head -1)
xwd -id $WID -out /tmp/w.xwd       # 拿窗口自身像素(不走屏幕合成, 被遮挡也有效)
```
再用 python 解 XWD 头 (25 个大端 int; `bpl=idx12`, `ncolors=idx19`, 掩码 idx14/15/16) 转成 BGR,
按 `#3fb950/#d29922/#f85149` 找 14x14 连通块: 实心亮 = 130~150 px, 空心 = ~50 px(只有 2px 边框)。
实测位姿: 窗口坐标 (1802,18) 绿实心 · (1820,18) 黄空心 · (1838,18) 红空心 ⇒ 与"550C 已连、GPU 无训练"一致。

## 3. 坑
- **控制台有重复实例**: `systemctl --user restart zmax-studio` 后 `is-active` 可能是 `inactive` (启动器检测到
  "already running" 直接 exit 0), 而真正在跑的是更早的孤儿进程 ⇒ 改了 `studio.py` 看着"没生效"。
  定式: 先 `pgrep -f '^[^ ]*gui-venv311/bin/python studio\.py$'` 精确清干净, 再 `systemctl --user start zmax-studio`,
  复核 `pgrep` 只有一个新 pid + `is-active=active`。
- 状态灯线程只在非调试态启动 (`_dbg_attached()` 为真时不采), 所以"灯不动"先确认不是 debugpy 挂着。
