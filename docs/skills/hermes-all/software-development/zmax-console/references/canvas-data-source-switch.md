# 状态空间画布的「数据源」与「场景唯一依据」切换

画布上 📦 数据源节点的拨钮 (点节点底部那条, 或右键「切换数据源」) 是**三态循环**, 点一下走一步:

    真机 → 插拔场景 → 摆盘场景 → 真机

代码全在 `tools/gui/simulink_module.py`: `SRC_CYCLE` / `SRC_SCENE_ID` / `SRC_DESC` / `_src_norm()` /
`_src_scene_dir()` / `_apply_src_scene()` / `SimulinkModule.on_toggle_src()`。

## 三态各自的含义

| 态 | 引擎数据源 | 场景唯一依据 |
|---|---|---|
| 真机 | `_data_source="bypass_real"` (Orin 远程只读真机帧: TCP 位姿/关节/六维力/夹爪/图像) | 不动 |
| 插拔场景 | `_data_source="metaworld"` (原「仿真」算路: 39D 状态 / 4D 动作) | `data/scene/scenes/SS-EPI-CORNER` |
| 摆盘场景 | `_data_source="metaworld"` (同一套算路) | `data/scene/scenes/SS-TRAY-PLACE` |

## 场景唯一依据怎么切 (关键: 它是全局的)

`ZMAX_SCENE_DIR` 是**全局场景唯一依据** —— 3D 视图 / 场景编辑窗(`dreamview_scene_edit`) / 上下料视图
(`updown_scene_view`) 都读它。切数据源时必须一起做三件事, 少一件就会「画布切了、场景窗还是旧场景」:

1. `os.environ["ZMAX_SCENE_DIR"] = <场景目录>`;
2. **已导入**的 `dreamview_scene_edit` 模块内全局 `SCENE_DIR` / `OBJECTS3D` 一起改 (否则后开的窗口拿到旧场景);
3. 已开着的场景窗调它的 `switch_to_dir(dir, label=...)` (从 `SceneEditWindow` 上取已有单例属性)。

场景窗没开就只落 env, 日志照实写「场景窗未开, 下次打开即生效」; 目录不存在就明说切不过去, 不装。

## 兼容与陷阱

* **老工程存的是 `src_state="仿真"`**: 一律先过 `_src_norm()` 归一成 `插拔场景` (与原仿真路行为一致, 不回退)。
  新增或比较状态一律走 `_src_norm()`, 不要各处直接和字符串比 —— 老工程会读成「不认识的值」而掉回真机。
* 同一份状态被多处读, 改口径要一次改全: 节点拨钮绘制 (真机=绿 / 场景=琥珀)、右键菜单文案、
  `_canvas_src_state()` (返回归一后的三态)、输入图像窗口与质量检测终端的帧源跟随 (真机→`real`, 场景→`sim`)。
* 拨钮点击热区在 `QRectF(8, self.h-26, self.w-16, 20)` —— 改节点高度/布局时要跟着核一次。

## 判据手法: 用 stub 直接跑真实处理方法 (不建整套 GUI)

节点交互逻辑 (循环 / 落盘 / 副作用) 可以在离屏判据里**真执行**, 不用拉起画布:

```python
class Stub:                      # 只提供方法真正用到的属性
    _items = {}
    _data_source = ""
    def _log(self, m): ...
    def _save_param_to_flow(self, node, k): ...

cls = next(o for o in (getattr(SM, n) for n in dir(SM))
           if isinstance(o, type) and hasattr(o, "on_toggle_src"))   # 别猜类名, 动态找
cls.on_toggle_src(stub, {"id": "n", "params": {}})                   # 未绑定方法 ⇒ 手传 self
```

方法挂在哪个类上不要猜 (`on_toggle_src` 不在 `SimCanvas` 上, 在 `SimulinkModule`) —— 遍历模块属性找
`hasattr(cls, name)`。判据要断言**副作用真的发生了**: 循环序列 (点 4 次回到起点)、`_data_source` 映射、
`ZMAX_SCENE_DIR` 真被切到目标目录、场景 `objects3d.json` 的对象数从磁盘实读 (插拔 42 / 摆盘 49),
以及「切真机时场景唯一依据不动」。

## 常见改动点

* 加一个场景态: `SRC_CYCLE` 加名字 + `SRC_SCENE_ID` 加 `data/scene/scenes/<ID>` + `SRC_DESC` 加说明;
  场景目录要真实存在 (判据会核 `objects3d.json` 对象数)。
* 只改文案: 拨钮画的是 `f"数据源: {_st}"`, `_st` 来自 `_src_norm()` ⇒ 归一表是唯一依据。
* ⚠️ 改动纪律: 只改老倪指的那一处。他要「数据源改成 A/B/C」就别顺手把三态变成四态或加个新面板 ——
  做多了会被判「你怎么把东西全给改了」并要求改回去 (见 SKILL.md「只改老倪指的那一处」)。
