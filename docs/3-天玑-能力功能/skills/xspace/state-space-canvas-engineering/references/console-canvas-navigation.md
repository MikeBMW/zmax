# 控制台画布页导航 + 节点源码定位 (studio.py)

## 现象: 发 `ss_canvas` 命令, 前台还是首页

`printf 'ss_canvas\n' > /tmp/zmax_nav_cmd` 后窗口标题不变、截图仍是首页。三个独立原因, 必须全修:

1. **画布页是懒创建的**: 命令处理里 `if getattr(self, "simulink", None) is not None:` 在新进程里为 `None`,
   整段直接跳过 ⇒ 命令等于没发, 且无任何日志。修: 命令到达时**先懒创建**再切, 并打印失败原因。
2. **`open_state_space()` 只刷新数据, 不切页**: 它把画布刷成该文件就返回。修: 处理完后显式
   `stack.setCurrentWidget(self.simulink)`。
3. **用索引快照切页会漂**: `modules["simulink"]` 是在建页时存的整数索引, 后来增删页就指向别的页
   (实测切到了 DDS 报文表)。修: `idx = stack.indexOf(self.simulink)` 后用控件本体切, 不要用快照索引。

**完成判据** (不是“命令发了”): 日志出现 `已切到状态空间画布 (stack[i] SimulinkModule)`,
窗口标题含 `[画布]`, 截图中心是节点画布而不是卡片首页。截图用 `xshot_win.py`, 不要截全屏。

## 节点右键「打开源代码」跳错行

`src/lerobot/engineering/nodes/library.py::_EXTERNAL_LOC["<node>"]` 存的是**行号**。
改节点实现文件 (加函数/加段) 后行号会漂, 右键会跳到错位置 ⇒ 每次改完实现都用
`grep -n "^def run" <impl>.py` 核一遍并同步 `_EXTERNAL_LOC`, 否则用户点开看到的是别人家的代码。

## 改完画布的两个真源都不能省

画布数据结构、`space-save` 后的回读校验 (节点数/连线数/文件大小)、以及 `space-open` 会用旧存档回填
这一层, 见主 SKILL.md 的“两份真源”。本文件只补两点: ① 切页要走控件本体; ② 源码行号要同步。
