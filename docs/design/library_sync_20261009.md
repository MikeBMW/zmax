# 📚 模块库 ↔ 画布 同步 / 拖入 / 删除 / 存为新工程 (2026-10-09 老倪)

> 老倪原话: 「全面检查 simulink 画布左侧的模块库, 现在状态空间的节点, 所有节点, 都要与模块库同步;
> 模块库的每个模块节点, 可以交互式拖进画布, 或者删除, 可以保存为新的工程文件;
> 你来全局检查同步功能; 没有联系的模块, 或者没有关联的, 都删掉」

## 一、体检结果 (改前)

| 项 | 数 |
|---|---|
| 模块库条目 | **495 条** (35 组) |
| 状态空间画布节点 | **89 个** (74 功能 + 15 行背景) → **库里缺 0 个** |
| 库里「无联系/无关联」条目 | **33 条** |
| 同组重名 | 0 |

状态空间那一组 `🧮 状态空间模型 (89节点)` **本来就是从画布 JSON 自动生成的**, 所以「所有节点都与
模块库同步」这条原来就成立 (89/89)。真正的问题是**另外 33 条没人要的旧条目**和**库里不能拖/不能删**。

删掉的 33 条 (见 `config/library_curation.json`):

| 分组 | 条数 | 例 |
|---|---|---|
| 动作 (11) | 8 | `A00 Action输出` `A01 取料·100G` … `A08 定位` |
| 系统 (8) | 7 | `S00 任务调度` `S01 工作流` … `S06 Switch 数据源` |
| 硬件 (8) | 7 | `H00 Orin Nano` `H03 机械臂` `H05 相机` … |
| 🌐 LeWorldModel·子模块 | 5 | `🎛 Action Embedder` `🧠 CrossAttn 块 ×N` … |
| 条件 (11) | 4 | `C00 信号触发` `C02 扫码OK` `C03 力控达标` `C05 温控阈值` |
| 模型 (9) | 2 | `M00 SmolVLA` `M04 LEW` |

这批是 **2026-08 的老 C/A/S/H/M 编号体系** (现在画布用 VEH.5.xxx), 老倪说「没有联系的都删掉」。
判定「有关联」= 命中任一条: ① 同名节点在任一画布 flow ② REFERENCE_APPS 模板 ③ 原子技能注册表
④ `match_node()` 命中引擎逻辑真源 ⑤ 条目自带 flow/模板/场景/原子闸。只有全不命中的才删。

## 二、改完的形态

```
模块库 = LIBRARY_STATIC(手写组) + 原子技能组(注册表 flows/atomic_skill_tokens.json)
                        + 状态空间组(画布节点: 内存优先, JSON 兜底)
                        − curation 删除名单(config/library_curation.json)
```

* **同步是活的**: `SimulinkModule.refresh_library(force=False)`
  * 重算 `LIBRARY` + `LIBRARY_SEQ`, 再重建左侧栏;
  * 状态空间组**优先吃画布内存里的节点** ⇒ 刚拖进来还没存盘的节点, 也立刻出现在库里;
  * 用「画布节点名集合 + curation 文件 mtime」做签名, 没变化就跳过重建 (495 个按钮全建要几百毫秒);
  * `load_flow_file()` 收尾自动调一次 ⇒ 换画布 = 库跟着换。
* **拖进画布**: `LibButton` (模块库按钮子类) 拖动 ≥8px 起 `QDrag`, MIME `application/x-zmax-lib-item`
  (载荷 `{type,name,params,group}`); 画布 `SimCanvas.setAcceptDrops(True)` +
  `dragEnter/dragMove/dropEvent` → `module.add_node_from_lib(payload, mapToScene(落点))`。
  * 拖 = 落在**鼠标处** (节点左上角 = 落点 −(120,42)); 单击 = 老行为 (落在画布中心)。
  * 非模块库的拖拽 (纯文本等) 一律不建节点。
* **删除**: 库条目右键 → 「⛔ 从模块库移除」 → 写 `config/library_curation.json` 名单 → 立刻重建面板。
  * **删条目不动画布节点**; 名单是生成物式的外挂数据, `lib_sync.py restore` 一句整表还原。
  * 右键菜单里还有「➕ 加入画布 (画布中心)」和「🖱 拖到画布 = 落在鼠标处」的提示。
* **存为新工程文件**: 模块库面板新增按钮「💾 存为新工程」(= 菜单 画布(C) → 💾 另存为 JSON… Ctrl+Shift+S),
  走的是同一个 `export_flow()` ⇒ 节点/连线/位置全落盘。

## 三、工具与判据

* `tools/lib_sync.py` — `check` (体检) / `dead` (只列无关联) / `prune` (写删除名单) / `restore` (整表还原) /
  `list` / `verify` (同步判定: 状态空间画布节点必须全在库里 + 0 死条目 + 同组 0 重名)
  * 口径注意: `verify` 的①只认**状态空间画布** (库不是所有 flow 的并集), 其它 528 个 side-canvas 节点
    只报覆盖率, 不作判据。
* `tools/verify_library_sync.py` — 7 条判据 (已在 `run_gui_verifiers.sh` 判据集里):
  ① 同步 (子进程 rc=0) ② 拖拽通道齐备 ③ **真拖一次** (造 `QDropEvent` 打真 `dropEvent`, 校验落点=位置、
  换落点位置跟着变、非库拖拽不建节点) ④ 同步是活的 (画布加节点 → 刷新后库里就有, 且落在状态空间组)
  ⑤ 删除 (curation +1 / 库条目 −1 / 画布不变) ⑥ **真落盘** (替掉文件框 → `export_flow()` → 新 JSON 节点数一致)
  ⑦ 删除名单在册。
* 实测: `lib_sync.py verify` → 89/89 缺 0 · 462 条 · 0 死 · 0 重名 (**rc=0**);
  `verify_library_sync.py` → **全绿 0 失败** (库 453 个按钮, 其中 445 个可拖)。

## 四、踩过的坑

1. **`QDropEvent` 不接管 `QMimeData` 所有权** — 用 `QDropEvent(pos, act, btn.drag_mime(), ...)` 内联造 mime,
   Python 侧没有引用 ⇒ GC 掉 → **段错误** (判据跑一半崩)。必须 `mime = btn.drag_mime()` 先接住再传。
2. **`export_flow()` 里的 `QFileDialog(...).exec_()` 在离屏环境会卡死** — 判据不能替 `getSaveFileName`
   (代码根本没用它), 要替 `QFileDialog.exec_` → 返回 `Accepted` + `QFileDialog.selectedFiles` → 临时路径。
   替身只换「对话框这一层」, 保存逻辑一字不改地真跑。
3. **状态空间组的数据源**: 原来只读画布 JSON ⇒ 刚拖进来的节点「库不认」。改成**内存优先**,
   否则「同步」在没存盘时是假的。
4. 旧的 `_msg_ask` 确认框回归 (`_remove_entry` 原来直接调 `_rebuild_library_globals()`),
   一律改走 `module.refresh_library(force=True)`, 保证「删条目」也不会把没存盘的画布节点从库里弄丢。
