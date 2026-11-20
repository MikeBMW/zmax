# 新增画布节点：从「JSON 里有」到「点得到、跑得起来、判据绿」

画布加节点是**六处**的事，少一处就静默失败、看不见，或让发版判据变红。

## 1. 画布 JSON 两份都要写

| 用途 | 路径 |
|---|---|
| GUI 打开工程时读 | `<repo>/flows/state_space_obs.json` |
| 写盘真源（save_space 会回写） | `data/database/zmax/sources/canvas/state_space_obs.json` |

`data/` 被 gitignore ⇒ 画布改动只留本机，只有代码（契约模块/注册/静态库条目）进 git。

```json
{"id":"ss_phase_corr","name":"🌀 相空间安全通道 …","type":"model","icon":"🌀","color":"#f5c26b",
 "x":6820,"y":1716,"w":320,"h":110,"layer":"L4",
 "params":{"desc":"…","source":"src/lerobot/manifold/phase_corridor.py","cap_level":"L4"}}
```

- `params.desc` / `params.cap_level` 缺了 → 模块库里无分组归属与提示，条目等于隐形。
- 摆位：先算目标行带空档，**跳过 `type=row_bg` 容器**（行带本来就包住节点，按容器判重叠会全红）。
- 连线：`{"id":"lkpf1","f":"<源>","t":"<目标>","f_port":"out1","t_port":"in1","label":"…"}`，且 `f` 的 x 严格小于 `t` 的 x。

## 2. 端口契约模块 `nodes/n_<slug>.py`（文件名由**节点名**推）

`spec.module_name` 用节点名里的 ASCII 片段拼文件名 —— **不是节点 id，也不是别名表**：

| 节点名 | 契约文件名 |
|---|---|
| `🔷 SE(3)×S1 记忆流形 (8815 · A位置ℝ³ …)` | `n_8815.py` |
| `🌀 相空间安全通道 (SE(3)×S1 记忆 + 速度纤维 …)` | `n_phase.py` |

写错名字不报错：loader 调 `ensure_node_modules` 生成一个**只有直通的壳**，每 tick 返回
`status="直通 (实现未注册: )"`、`out1=null`。

内容照 `n_dit.py` 裁：`NODE_ID / NAME / LAYER / TYPE / EXEC_MODE / PURE / PORTS_IN / PORTS_OUT /
IMPL_KEY / SOURCE / SOURCE_SYMBOL / PARAMS / LAST_STATUS / compute(ctx)`。

## 3. `compute()` 里自注册实现（常驻进程的关键）

```python
from lerobot.engineering import registry as _reg
if not _reg.get(IMPL_KEY):      # 画布循环进程常常没 import 过 nodes/library.py
    from lerobot.middleware.nodes.impl import <mod> as _impl
    _reg.register(IMPL_KEY, ["<匹配词>"], "<一句说明>", _impl.<fn>)
info = _reg.get(IMPL_KEY) or {}
fn = info.get("fn")
if not callable(fn):
    LAST_STATUS = "直通 (实现未注册: %s)" % IMPL_KEY
    return _passthrough(ctx)
```

不做这步：GUI 进程能跑（它 import 了 library），画布循环进程恒直通 —— 两种进程两种结果。

## 4. 读回值用「实现写的键」，不是 IMPL_KEY

实现通常写 `_SS_STATE["<短键>"]`（`se3_state` / `phase_corr`），与 IMPL_KEY（`ss_se3_state` /
`ss_phase_corr`）不是同一字符串；按 IMPL_KEY 取恒 `None`，表现为“跑成功但 out1 空”。

## 5. 工具栏按钮是另一条路（模块库左侧面板）

- 「🧮 状态空间模型 (N 节点)」组由**画布节点现场生成**；面板只在控制台启动时建一次，
  `refresh_library` 的签名也只看**内存画布** ⇒ 运行中加节点，旧进程里永远不出现。
- 要“一开就在”，往 `tools/gui/simulink_module.py` 的 `LIBRARY_STATIC` 追静态组：

```python
("model", "🌀 流形 · 相空间 (L4)", [
    {"name": "🔷 SE(3)×S1 记忆流形", "type": "model",
     "params": {"state_space": True, "cap_level": "L4", "source": "src/…/ss_se3_state.py",
                "desc": "…"}},
]),
```

静态条目不依赖画布状态，也不会被 `config/library_curation.json` 的删除名单影响。

## 6. 功能点描述（不加就让 `engineering_db.py check` 变红）

新节点一进画布，`functions` 表就多一条没描述的记录，发版前的工程库判据立刻红：

```
❌ ⑦b 功能点描述 79/81 条 (做什么/阻塞点/状态) · 禁词命中 0
❌ 判据失败: ['fn_notes 79/81 ban=[]']
```

这不是历史漂移，是**本轮新节点欠的账**。真源是 `data/database/zmax/function_notes.json`（被 gitignore，只能靠归档留档），
三处要同时改：`notes_by_name[<节点全名>]`、`notes[<fn_id>]`（以 `SELECT fn_id,name FROM functions WHERE note_work=''` 现查）、`count`。

- **键必须是节点全名（逐字符一致，含 emoji 与括号里的说明）**：`_keying=by_name` 就是为画布插节点会把 `FN-*-NN` 整体平移而设的，按编号写会张冠李戴。
- 每条写 `work`（读什么、算什么、实现落在哪个文件）/ `pain`（现场什么现象暴露了它）/ `state`（在役到什么程度 + 没验的部分），车间口径。
- 禁词表（赋能/生态/抓手/全面提升/显著提升/智能化升级/助力/打造/一站式/无缝/深度融合/颠覆/行业领先）命中即红，写完自查一遍。
- 顺序固定：补 notes → `engineering_db.py build` → `check` 到 `✅ 判据全绿`。

## 验收（不是“JSON 里有”）

```python
from lerobot.middleware import load_project
p = load_project()
tr = p.step(only=["<new_id>"])
print(tr[0]["status"], tr[0].get("ms"), tr[0]["out"])
```

| 现象 | 结论 / 下一步 |
|---|---|
| `✅ …` + `out` 有值 | 真跑通 |
| `直通 (实现未注册: <key>)` | 键进 registry 但 `fn` 空 → 补第 3 点 |
| `直通 (实现未注册: )`（键为空） | 模块没绑上 → 查第 2 点 slug |
| `✅` 但 `out1=null` | 读错键 → 第 4 点 |

再对 `zmax_data/ss_live/canvas_loop.json` 的 `traces` 抽查：没有你的 id 就是没进执行序。

最后跑工程库判据，`✅ 判据全绿` 才算交付（新节点没描述时 ⑦b 会红，见第 6 点）：

```bash
./gui-venv311/bin/python tools/engineering_db.py build && ./gui-venv311/bin/python tools/engineering_db.py check | tail -12
```

## 编辑前先停控制台（否则白改）

- 打开工程时它把旧文件备份成 `_archive/…_before_open_*`；**关闭时把内存画布写回** ⇒ 运行期改 JSON
  会被旧版本覆盖，且备份名字看起来“已经备份过了”，很容易误判成功。
- 该进程只吃 `SIGKILL`（见 `closeEvent` 注释）。停 = 允许；起 = 等用户点名。
- 自己再留一份：`cp … flows/_archive/state_space_obs_$(date +%m%d_%H%M)_pre_edit.json`。

## 改法：脚本化 + 幂等

照 `tools/canvas_add_*` 的形状写 adder：`--dry` 先断言（id 不重复、与执行节点不重叠、连线 x 递增）
→ `--apply` 备份 + 写盘 + 回读（`json.load`、节点/连线计数、悬空连线检查）。复跑按 id 去重，
改坏了能直接重跑。
