# 声明源 vs 真实实现 的漂移审计 (三件套: 体检 → 补齐 → 重指向)

**触发场景**: 配置/画布/清单里**声明了"源码在哪"或"对应哪个实现"**, 但代码搬过家、重构过、或当初就指错了 →
用户看到的是"右键打不开/跳错文件/跳文件第 1 行", 你以为是"工具坏了", 其实是**映射漂移**。
实测来源: Z-MAX 画布节点 `params.source` / `_EXTERNAL_LOC` (2026-09-14, 老倪「DiT 的右键怎么没有进入源代码呢?」)。

## 判定顺序要先读代码, 别猜

以 Z-MAX 为例 (`tools/gui/simulink_module.py::open_in_vscode`), 三条路任一断都表现为"没进源码":
```
① 节点自声明 params.source (+ params.source_symbol 按符号现搜行号)
   └ 相对路径按**仓库根** join; 可能写成描述式: "路径 · 符号" / "路径 符号" / "路径 --flag" (要拆!)
   └ 🔴 **节点自声明是最高优先, 不会"让位给 ②"** (`open_target.resolve_open_target` 里 `_impl_from_dict()`
     先跑, 且 spec 查到也仍以它为准): 实现搬了家、注册表 `_EXTERNAL_LOC` 已改对, 只要画布 JSON 的
     `params.source` 还是旧文件, 右键就**必然**落到旧文件(常是常驻进程的 `def main`)——症状是"打开的代码
     里全是 mkfifo / 探针 / 单实例"这种和节点毫无关系的启动逻辑。
   └ 判据: `grep -c '<该符号>' <落点文件>` 为 0 = 指向错; 且对比 `_EXTERNAL_LOC[key]` 与 `params.source`
     两条路径不一致 ⇒ 就是漂移, 不是工具坏。
② 注册表 match_node(名字) → _EXTERNAL_LOC[key] (真实外部实现)
   ⚠️ match_node 是**最长关键字**匹配, 不是注册顺序
③ 都没命中 → 退回壳文件自身 → 用户观感"没跳"
```

## 两个高频漂移 (都是"看起来像工具坏了")

| 症状 | 真因 | 判据 |
|---|---|---|
| 打开了源码但停在**第 1 行** | 只写文件、没写符号 → `code -g <file>:1` | 声明里没有 `source_symbol` / 符号名 |
| 打开的是**壳文件**, 不是真实现 | `source` 指向 GUI/dispatch 文件, 真实现已搬到 `src/...` | **目标文件里 grep 不到那个符号** = 指向错了 (不是"打不开") |

## 三件套 (顺序固定, 每一步都可复跑)

1. **体检** `check_node_source_map.py` 类工具: 逐条报"走哪条路 / 定位到哪个文件哪一行 / 符号是否存在",
   并把"落到壳文件"的条目单独列出 (这类最容易被误判为坏了, 其实只是映射不全)。
   导入纯逻辑模块 (`node_logic.py` 无 PyQt 依赖 → 可 headless 直接 import, 用**真** `match_node`/`get_node_location`, 别自己实现一份)。
2. **补齐** `fill_node_source_symbols.py` 类工具: 给"有真实文件但无符号"的条目补符号。
   符号**只用已经人工核对过的注册表里的**, 且必须**同一文件** + 符号在该文件里真实存在才写。
3. **重指向** `repoint_node_sources.py` 类工具: 把指向壳文件的条目改指向真实现 (内置映射表)。

**纪律 (宁缺勿错)**: 两个 apply 工具一律 **dry-run 先打印清单** → 只在"目标文件存在 + 符号真实存在"时才写 →
写入前**自动备份**原文件 (`*.bak_<ts>`) → 用**与原写入方相同的序列化格式**写回
(如 GUI 自己就是 `json.dump(..., ensure_ascii=False, indent=2)`, 别引入第二种格式) →
改完复跑体检对比数字 (体检可定位数应上升、"落到壳文件"数应下降)。

## 实现搬家后要同步的四处 (漏一处就跳错文件)

迁移节点的真实现时, 只改注册表是不够的 —— 同一个"源码在哪"有**四份声明**, 任一份留旧值都会让右键跳错:

| # | 位置 | 字段 |
|---|---|---|
| 1 | `flows/<画布>.json` 的 `nodes[].params` | `source` + `source_symbol` (**最高优先, 必改**) |
| 2 | `src/lerobot/middleware/nodes/<n_id>.py` | `SOURCE` / `SOURCE_SYMBOL` |
| 3 | 同一个文件的 `PARAMS` 字典 | 里面的 `source` / `source_symbol` (生成器从这里回填) |
| 4 | `engineering/nodes/library.py` 的 `_EXTERNAL_LOC[key]` | 实现路径 (通常最早被改对, 别以为它对了就完了) |

同时把**常驻进程**与**节点实现**分开标注 (例: 加 `params.dispatcher = tools/<x>_daemon.py`),
否则下一轮又会有人把 daemon 的 `main()` 当成节点实现。

验收一条命令 (不用开 GUI, 走的就是右键那条解析):
```bash
PYTHONPATH=src python3 -c "
import json; from lerobot.middleware import open_target as ot
d=json.load(open('flows/<画布>.json')); n=[x for x in d['nodes'] if x['id']=='<nid>'][0]
r=ot.resolve_open_target(n); print(r['path'], r['line'], '|', r['impl_path'], r['impl_line'])"
```
要看到 **节点模块 + 真实现在两个不同文件**, 且 `impl_line` 指向那个符号所在行 (第 1 行 = `source_symbol` 没生效)。
GUI 侧改了画布 JSON ⇒ 画布在启动时读进内存, **重开画布/控制台后才变**; 别拿源码 grep 当"用户已经看到新落点"。

## 报告口径 (老倪式)

给出**前后数字**而不是"修好了": `可定位 N · 不可定位 M · 落到壳文件 K` 三连 + 逐条改动
(哪条 → 哪个文件哪一行 :: 什么符号) + 明确说清"剩下 K 条落到壳文件是**正常的**"(那类条目的实现本来就在壳里,
如显示/开关类节点), 否则用户会以为还有问题。
另: 改了 GUI 侧代码 → 必须**重启**才生效; 配置文件(画布 JSON)重新载入即可。
