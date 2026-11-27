# 模型引擎「所有模型: 显示/管理/可训练」(2026-11-25)

老倪原话：「模型引擎 所有模型, 都要显示, 管理, 可训练」。旧状：`model_inventory` 每层只取
`_newest` 一个 ⇒ 磁盘 319 个权重只露 8 条；管理只有层级「训练本层」。

## 三层结构

| 位置 | 职责 |
|---|---|
| `tools/model_inventory.py` → `all_models` | 只读枚举：磁盘上**每一个**权重（319 条） |
| `tools/model_engine_ctl.py` | 动作：`--set-active` / `--train` / `--stop` / `--status`（回执 JSON） |
| `model_engine_window.py` `tb_all` | 界面：逐条列表 + 筛选 + 选中行动作按钮 |

## 坑（都是实测踩过的）

1. **必须加 TTL 缓存（120s）**：面板 `_Fetcher` 5s 一拉，319 次 stat + 91 个目录 `_dir_size`
   不解缓存会把 GUI 拖慢。
2. **`glob('yolo_annot*/**/weights/best.pt')` 会对同一文件匹配多次** ⇒ 按 `(层, 相对路径)` 去重，
   否则 150 条 L2 里有重复。
3. **名字不能用 basename**：147 个 YOLO run 目录很多都叫 `yolo_annot`，要用相对 `outputs/` 的路径
   （`yolo_annot/annot_0911_1814`）才分得清。
4. **319 行不要每行放按钮**：`setCellWidget` ×2×319 会卡。用「选中行 + 底部按钮」。
   重建前比签名 `(条数, 在役数, mtime 和)`，不变就跳过填充。
5. **在役判定用 realpath**：L3 的 `checkpoints/last` 和 `004000` 是同一目标 ⇒ 两条都会判在役（正常）。
6. **set-active 必须备份+回读+回滚**：`models/active_models.json` 是重启加载的真源；L2 是**软链**
   （`models/yolo_peg_live.pt`，原子 symlink+rename），其它层改指针。绝不覆盖权重文件。
7. **训练同层已有进程就拒绝**（`8G 显存双开必 OOM`），要并行显式 `--force`。
8. **selftest 判回归要用基线比 FAIL 条数**：HEAD 基线已有 9 项历史 FAIL（selftest 假数据与真实字段
   不匹配，如「表格列名齐 (8 列)」while 实际 11 列）。**别用 `tail` 截断输出下结论** —— 前面几条 ✓
   会被截掉，看起来像新 FAIL。

## 实测（2026-11-25）

- 319 条全列出、0 重名、0.2s；按层 L2 150 / L4 91 / L3 42 / L5 36；在役 15 条标记正确。
- `--set-active L3 last → 回读 verified → 切回 004000`：最终态与初态一致，备份 1 个。
- `--train L4 --dry-run` 输出 `gui-venv311/bin/python tools/joint_train_all.py --only L4`。
- 真机窗口截图确认：顶表 12 行 + 全量表 319 条（883px 高窗口里可见 5~7 行，靠筛选/滚动）。
