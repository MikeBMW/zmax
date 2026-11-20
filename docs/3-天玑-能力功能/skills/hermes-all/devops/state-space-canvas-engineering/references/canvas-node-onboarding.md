# 画布加节点（让按钮/执行两处都真通）

2026-11-20 实测踩坑清单。目标：新节点既出现在左侧模块库按钮里，又在常驻循环里真执行（不是“直通”）。

## 1. 三处都要改，缺一处就只画不跑

| 位置 | 改什么 | 漏了会怎样 |
|---|---|---|
| 画布 JSON（唯一依据 `data/database/zmax/sources/canvas/state_space_obs.json`） | `nodes[]` 加节点、`links[]` 加线（字段 `f/t/f_port/t_port`） | 画布上没有 |
| `src/lerobot/middleware/nodes/n_<slug>.py` 端口契约 | `NODE_ID / NAME / PORTS_IN_OUT / IMPL_KEY / compute()` | `status="直通 (实现未注册: )"`，out1=null |
| `src/lerobot/engineering/nodes/library.py` + `impl/nodes/impl_manifest.json` | `_reg(key,[匹配词],doc,fn)` + 清单条目 | `match_node()` 认不出，`_repoint_impls` 绑不上 |

## 2. slug 不是节点 id —— 由节点名推导

`spec.module_name` 从 **name** 生成：`🔷 SE(3)×S1 记忆流形 (8815 …)` → `n_8815`；`🌀 相空间安全通道 (…)` → `n_phase`。
文件名写错（如 `n_se3_state.py`）⇒ 该节点永远落到兜底 stub，报 `实现未注册: `（key 为空）。
查法：`load_project()` 后 `p.nodes['<id>'].spec.module_name`。

## 3. compute() 里要自注册实现

常驻循环进程未必 `import library`（那是 GUI 侧才走的路）⇒ `registry.get(IMPL_KEY)` 为空。契约里加：

```python
from lerobot.engineering import registry as _reg
if not _reg.get(IMPL_KEY):
    from lerobot.middleware.nodes.impl.<mod> import <fn> as _impl
    _reg.register(IMPL_KEY, ["<中文匹配词>"], "<doc>", _impl)
```

## 4. 模块库按钮：按画布节点生成，只在启动时建

- 组名 `🧮 状态空间模型 (N节点)`，条目取自 `flows/state_space_obs.json`；老倪报“没有按钮”多半是**没重开控制台**。
- 想“一开就在、与画布状态无关”：往 `LIBRARY_STATIC` 追加一组静态条目（`("model", "组名", [{"name","type","params"}])`）。
- 节点想被分组/有提示：`params` 里必须有 `desc`、`cap_level`；只有 id/name/x/y 的节点在库里等于隐形。

## 5. 关控制台会回写画布 —— 改 JSON 前先停进程

`studio.py closeEvent` 会 `save_space()` 用内存画布覆盖文件。给旧进程加节点后如果正常关窗，新节点被冲掉。做法：先备份 JSON 到 `flows/_archive/`，再 `kill -9 <studio pid>`（该进程只有 SIGKILL 收得干净），最后改文件。

## 6. 验收口径（缺一不算通）

```python
prj = load_project()                      # 真实工程，不用假 ctx
ids = [i for i in prj.order if '<新 id>' in i]
tr = prj.step(only=ids)                   # status 必须是 ✅，不能是“直通”
```
再跑一次 `zmax-ss-canvas-loop` 落盘的 `zmax_data/ss_live/canvas_loop.json`，看 `traces[].n_ran / status`。
注意 `加载画布: N 节点` 的 N 是**可执行节点数**（总数要减掉 `row_bg` 等结构节点），别拿它判断总数。
