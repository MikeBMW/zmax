# 画布层节点数 ↔ 册子页数 对账

老倪的验收口径：**画布某层有几个节点，册子该层就出几页**，1:1，不许册子多出没人认识的页，也不许画布留着册子上没有的节点。改完必须报这两个数字并证明相等。

## 一次对账要跑的四件事

```bash
cd ~/zmax
rm -f tools/__pycache__/*.pyc src/lerobot/engineering/nodes/__pycache__/*.pyc
./gui-venv311/bin/python -c "
import sys; sys.path.insert(0,'tools'); sys.path.insert(0,'src')
import l2_chain_pages as LC, l345_pages as L
nodes,_,links=LC.l2_nodes()
for lv in ('L3','L4','L5'):
    ids=L._level_ids(lv); order=L._ordered(lv,set(ids),links)
    print(lv,'画布',len(ids),'册子',len(order),'一致',len(ids)==len(order))
"
./gui-venv311/bin/python tools/build_solution_deck.py 2>&1 | grep -E "结果:|个节点页 \+|❌"
```

`画布` 与 `册子` 不等，就是还有该删的节点或该补的条目，别急着出册子。

## 校验器里的写死数字是头号假 FAIL 源

`tools/verify_solution_deck.py` 曾经写死：`_NP_TOTAL = len(ORDER) + 5 + 18 + 11`，以及
`(('L3','决策层',5),('L4','认知层',18),('L5','任务层',11))`。任何一次增删节点都会让总页数和分层页数同时 FAIL —— 而页面本身是对的。

规则：三层页数一律动态算，且要扣掉页级屏蔽集合：

```python
import l345_pages as L345
_N_L3 = len([x for x in L345._level_ids('L3') if x not in L345.NO_PAGE])
_N_L4 = len([x for x in L345._level_ids('L4') if x not in L345.NO_PAGE])
_N_L5 = len([x for x in L345._level_ids('L5') if x not in L345.NO_PAGE])
_NP_TOTAL = len(ORDER) + _N_L3 + _N_L4 + _N_L5
_WANT_PAGES = 13 + 7 + _NP_TOTAL + 3 + 3 + 1
```

改完必须仍收到 `58 PASS / 0 FAIL`；FAIL 里有页数项，先怀疑这里又写死了。

## 导入顺序决定基础层受不受控

`NO_PAGE` 的屏蔽是靠 `l345_pages` 模块顶层执行 `LC.SKIP_IDS = set(NO_PAGE)` 注入的。
`tools/build_solution_deck.py` 里 `import l345_pages as _C345` **必须排在 `_C2.add_block(pr)` 之前**：

```python
import l2_chain_pages as _C2
import l345_pages as _C345      # 先导入: 注入 LC.SKIP_IDS
_C2.add_block(pr)               # 基础层节点页
_C345.add_layers(pr)            # 决策层 + 认知层 + 任务层
```

排在后面，基础层 30 页照旧带着被屏蔽的节点出页，而认知层/任务层已经干净——看起来「屏蔽只生效了一半」。

基础层页序在 `l2_chain_pages.add_block()` 里也要自己过滤一遍：

```python
if SKIP_IDS:
    order = [x for x in order if x not in SKIP_IDS]
```

## NO_PAGE 只管「出不出页」，绝不去动连线

试过把被屏蔽节点从上下游框里一并抹掉，结果下游页立刻变成「输入 0 条 / 输出 12 条」的孤页——页面干净了，事实失真了。

规则：`node_page(..., skip=...)` 不得过滤 `ins`/`outs`；屏蔽只作用在「这个节点要不要单独占一页」。链路图里它作为上下游出现是**链路事实**，不是重复页。用户说「怎么重复了」时，先数独立页（带 `认知层 · 第 N/M 位` 角标的那一页），再解释其余是引用。

## 功能删不掉就合并（A → B）

用户的判断顺序是：能删就删，功能真存在就合并，不许留空壳节点。合并的语义固定：

- A 的**入边**改挂 B（B 从此接收 A 的输入 = 承担 A 的职责）
- A 的**出边**改从 B 出发（B 继续向下游供数）
- 去掉 B→B 自环、连线去重、删掉 A

```bash
./gui-venv311/bin/python tools/merge_canvas_nodes.py --pairs "A1:B1,A2:B2"          # dry-run
./gui-venv311/bin/python tools/merge_canvas_nodes.py --pairs "A1:B1,A2:B2" --apply
```

选 B 的判据是语义承接，不是就近：档位 `sscap → ssmode`（档位即模式应用）、L4 记忆 `ss_mem_l4 → ss_mem_field`（势场联络本就吃 L4 势场）、汇总中枢 `ss_mem_share → n_mem_links`（图谱即中枢结构）。合并后 `by_level.py` 删 A 的条目、`NO_PAGE` 里去掉 A（画布已无，页级屏蔽失去意义）。

## 「这个节点实现了么」—— 三证缺一不能答「已实现」

用户问「有节点么？实现了么？没有就删掉」时，节点在画布上只证明第一层。固定三证：

1. **源码文件存在**：`_mod_info(id)[1]['SOURCE']` 指向的文件 `os.path.exists`
2. **符号真在里面**：对该文件 `re.search(r'def\s+<SOURCE_SYMBOL>\b', 全文)`；`SOURCE_SYMBOL` 常写成 `def run_once(` 这种带括号形式，比对前先剥掉括号
3. **数据源真有内容**：它读的那个 json / 共享内存字段非空（例：`ss_mem_l4` 读 `data/memory/ar_safety.json` 与 `shared_memory.l4`，实测 `l4.predict` 有 40 条）

三条全过才能说“有实现，不该删”，报的时候每条各给一行证据（路径 + 命中 + 字段值）。只有节点在画布上、或只看到个函数壳子，都按“没实现”处理并主动给合并/删除建议——不要拿“节点存在”冒充“已实现”。

## 合并后必须复核环没断

记忆族天生是双向环（三层记忆 ↔ 中枢）。合并后逐条确认：

```bash
./gui-venv311/bin/python -c "
import sys; sys.path.insert(0,'tools'); sys.path.insert(0,'src')
import l2_chain_pages as LC
nodes,_,links=LC.l2_nodes()
for n in ('n_mem_links','ss_mem_field'):
    print(n,'入',[k['f'] for k in links if k.get('t')==n],'出',[k['t'] for k in links if k.get('f')==n])
"
```

合并工具自己会打印 `悬空 0` 和 B 的改前/改后出入边——悬空非 0 或 B 的出入边凭空少一条，就是重定向搞错了，回滚到 `zmax_data/backup_state_space_obs_*.json`。
