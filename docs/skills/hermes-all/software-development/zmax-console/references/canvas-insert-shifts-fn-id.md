# 往画布插节点 → `fn_id` 位置号整体错位 (描述唯一依据静默错挂)

## 现象与根因

功能描述唯一依据 `data/database/zmax/function_notes.json`、配置元数据 `config_meta.json` 都按 **`fn_id` = `FN-<系统>-<序号>`**
存放, 而 fn_id 是**行内位置号**。往某一行里插一个画布节点 ⇒ 该行**后面所有节点的号前移一位** ⇒ 每个描述被挂到
"下一个节点"上。

实测 (2026-10-15 插 ⚖物理约束闸 → FN-SYS0-60 · 📦metaworld 数据源 → FN-PLAT-63 · 🧾元任务预测 → FN-SYS2-24):
16 条搬号 + 2 条空缺, 而 `engineering_db check` 的 ⑦b **只看得见"空描述"2 条** ——
`🤖 机器人执行器` 挂着 `PhysicalWorld(...)` 的描述这种**错挂是判据看不出来的** (它只数"有几个空的")。

## 判据 (唯一能逐条查出错挂的口径)

描述条目自带 `name` 字段 ⇒ **逐 id 比对 `notes[id].name` vs 工程库 `functions.name`**:

```bash
./gui-venv311/bin/python - <<'PY'
import json,sqlite3
N=json.load(open('data/database/zmax/function_notes.json'))['notes']
c=sqlite3.connect('data/database/zmax/zmax_engineering.db')
for fid,nm in c.execute('SELECT fn_id,name FROM functions ORDER BY fn_id'):
    if (N.get(fid) or {}).get('name')!=nm: print('错位', fid, nm, '<-', (N.get(fid) or {}).get('name'))
PY
```

`0` 条错位才算对; `verify_function_notes.py` 的「描述里的功能名与 config_meta 一致」也就是这条。

## 修法 (按节点名重挂, 不要按号硬搬)

```bash
./gui-venv311/bin/python tools/fix_function_notes_align.py          # 干跑看计划 (搬号/改名/新写/孤儿)
# 新节点的描述写到 data/database/zmax/function_notes_new.json (键=节点名, 值={name,work,pain,state})
./gui-venv311/bin/python tools/fix_function_notes_align.py --apply  # 落盘 (自动 .bak)
./gui-venv311/bin/python tools/config_meta.py build                  # 配置元数据从库重建 (同样按号错位)
./gui-venv311/bin/python tools/engineering_db.py build
./gui-venv311/bin/python tools/verify_function_notes.py              # 9 项全过 = 75/75 逐条一致
./gui-venv311/bin/python tools/engineering_db.py check               # ⑦b 应显示 75/75
```

写新描述的口径 (判据会逐条卡): 三条 (work/pain/state) **每条 ≥12 字** · work/pain 至少含一个具体事实
(参数 ID/数字/文件名/类名) · state 必须用工程口径词 (在役/未接入/待标定/缺口/回流…) · 禁宣传话术词表见
`tools/verify_function_notes.py::BAN`。

## 别踩的坑

* **别只补空描述就收工**: 错挂(名字对不上)的条目比空的更坏 —— 界面上会理直气壮显示错的描述。
* `config_meta.json` 是**生成物** (`tools/config_meta.py build` 从库+param_registry 派生, 只保留 `author=human` 的 notes),
  重跑 build 即可对齐; 不要手改它的 fn_id 键。
* 一次插入多个节点 ⇒ 先把所有新节点的描述一次写进 `function_notes_new.json`, 再一跑到底 (多次 apply 会让孤儿判定变乱)。
