# 整机方案册（PPT）页序与重出

## 真源与副本（两份会分叉）
- 构建入口：`tools/build_solution_deck.py`
  - 母版：`zmax_data/deliveries/母版/机器人整机内容源_5.50.C.pptx`
  - 输出：`docs/1-天枢-产品边界/deliverables/2-机器人方案/Z-MAX机器人整机解决方案_<ver>_<date>.pptx`
- `zmax_data/deliverables/<date>/` 下那份是**副本**。重出后必须 `cp` 过去并比对 md5，否则用户打开的还是旧页序（实测两份 md5 已分叉：1307102 vs 1333168 字节）。

## 层内页序 = 一个函数，两处调用
- `tools/l345_pages.py` 的 `_ordered(lv, ids, links)`：先 `LC.chain_order()` 出链路拓扑序，再按 `PIN_HEAD[lv]` 把指定节点钉到前几位（每行注释标「第几位」）。
- **层首页表格与逐节点页必须共用它**。曾经两处各排一遍，改完逐节点页已经是新序、层首页表格还是旧序。
- `PIN_HEAD` 增删节点后要重跑一遍，用页名回读验证：
  ```bash
  python -c "from pptx import Presentation; ..."   # 打印 第 k/18 位 + 节点名，确认位次 1..N 连续
  ```

## 重出前先清 pyc
源码改了但 `tools/__pycache__/l345_pages*.pyc` 是旧的 ⇒ 重出**静默用旧版面**（实测：源码 `NH=1.30`、成品仍是 `1.16`、connector 数 13 而应为 39）。
```bash
rm -f tools/__pycache__/l345_pages*.pyc tools/__pycache__/l2_chain_pages*.pyc
./gui-venv311/bin/python tools/build_solution_deck.py     # 末尾自带 58 PASS/0 FAIL 自检
```

## 框图清爽的三条改法（`l2_chain_pages.node_page`）
1. 连线改**三段正交**：框右缘水平出 → 阶梯竖直（每根错开 0.055 in）→ 水平入中心节点；原来是 N 根斜线扎成一把扇子。
2. 节点框高 0.28→0.34 in、字号 9.0→9.2~10.0、名字截断 13→18 字符。
3. 中心节点框 1.16→1.30 in，左右沿锚点间隔 0.105→0.175 in；每根线落独立锚点。
验证：单页 connector 数应等于 `3 × (输入条数 + 输出条数)`；同列框两两不重叠。
