# 改节点语义/重新接线 + 控制台跳到画布页

## 改一个节点的语义 (例: 从「出动作块」升级为「出 3D 引导位姿」)

五处一起改, 少一处就会要嘛画布显示旧名、要嘛话题表停更:

1. **实现正文** (`src/lerobot/engineering/nodes/<xxx>_impl.py`): 新增能力不改旧返回键, 只追加
   (`guide` / `value`…), 旧消费方就不碎; 失败路径一律 `ok:false + err`, 不返回空块冒充成功。
2. **注册表描述** (`library.py` 的 `_reg(...)` 别名/描述) —— 名字变了这里也要变, 否则搜索/别名还对不上。
3. **`_EXTERNAL_LOC[<id>]` 的行号**: 一旦在 `def run` 上方插函数 (带了一个 helper), 入口行号就漂,
   右键「打开源代码」会跳到错误处。改完必须 `grep -n "^def run"` 回读并同步。
4. **`tools/gen_topic_types.py` 的 NODES 白名单**: 新增/改语义的出口都要在这里登记 (出口名 → 类型)。
   漏登不会报错, 只提示「注册表缺节点」并**整张表停更**; 改完跑一次并看行尾的「N 节点/M 出口/K 入口」。
5. **画布节点 JSON**: `name` + `outputs`/`inputs` + 连线。

## 加端口与重新接线 (先查占用, 别复用它人的口)

```python
from lerobot.engineering import flows
d,_ = flows.load_canvas()
N = {n['id']: n for n in d['nodes']}
# 查某节点已用/已占端口 —— 连线键是 f/f_port/t/t_port, 不是 src/dst
used_in  = [(l['f'], l['f_port']) for l in d['links'] if l['t'] == NID]
used_out = [(l['t'], l['t_port']) for l in d['links'] if l['f'] == NID]
```

规则:
- **先看端口占用再选口**: 实测 `sslimit.in2` 已被物理闸占、`out2` 已被力限幅占 ⇒ 只能用 `in3`/`out3`。
  共用一个出口会让两路语义混在一个端口上, 下游取到啥看谁后写。
- **穿过中间节点**: 拆掉直连边 (`n_geoplan→n_moveit`), 换成两段 (`n_geoplan→sslimit` + `sslimit→n_moveit`),
  长跨区连线变两段短线, 标签也不会跨过半个画布。
- **落盘后再回读**列一遍该节点的出入边 (f/f_port→t/t_port) 对账, 不要只看 save 的返回值。
- 两份真源: `save_canvas()` 只写画布文件, 还要 `tools/project_archive.py space-save` 同步工程存档,
  否则下一次「打开工程」用旧存档全量回填会把改动抹掉。

## 控制台「发命令但窗口不动」

`/tmp/zmax_nav_cmd` 命令通道 (如 `ss_canvas`) 实测有三层坑, 按顺序排:

1. **画布页是懒创建的**: 处理器里 `if self.simulink is not None` 直接跳过 ⇒ 新进程里永远 none ⇒ 命令等于没发。
   修法: 先 `self._init_simulink()` (本身幂等), 失败打印可见错误而不是静默 return。
2. **`open_state_space()` 只刷新画布内容, 不切页** —— 它把画布刷成该文件却不把你带过去。
   修法: 另加切页。
3. **切页不要用索引快照** `modules['simulink']`: 页面增删后会漂 (实测切到了「数据空间」页, 屏幕上是 DDS 报文表)。
   正解是按控件本体反查: `idx = stack.indexOf(self.simulink)` → `stack.setCurrentWidget(self.simulink)`,
   并把 `stack.currentWidget().__class__.__name__` 打进日志。

完成判据 (两个都看, 不要只看一个):
- 窗口标题多出后缀 `- [画布]` (`wmctrl -l | grep XSpace`)
- 日志有 `已切到状态空间画布 (stack[N] SimulinkModule)`, 且类名是画布模块而不是别的页

## 看图验证的注意

截整屏常常抓到别的前台窗口 (终端/编辑器) ⇒ 无效证据。用窗口几何裁图 (按 `wmctrl -l` 的 geom 裁),
并让看图方回答「标题原文 + 左右邻居节点名」而不是「有没有看到」—— 否则会把旧截图当真。
