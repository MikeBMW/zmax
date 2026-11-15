# 按文件路径消费老路径的消费方: 「打开源码」落点审计与批量修复

import 兼容只盖住一半。另有一类消费方是**按文件路径**读的: 编辑器「右键 → 打开源代码」、
画布节点的 source 字段、数据库 `source` 列、外部工具按路径 grep/打开。它们不会因为你留了别名 shim
就看到真代码 —— 会打开壳文件, 用户看到 3 行转发, 直接判定「代码不见了」。

## 优先级 (先看清楚谁赢, 再改)

以 Z-MAX 画布为例 (其它系统同理, 先读解析函数而不是猜):
`simulink_module` 右键 → `middleware/open_target.py::resolve_open_target` → `_impl_from_dict`:

1. **节点自身 `params.source` / `source_symbol` / `source_line`(最优先)**
2. `library._EXTERNAL_LOC[node_id]`
3. 注册表 / node_id 映射

所以「只改 `_EXTERNAL_LOC` 再复测」是无效动作 —— 画布里的 `params.source` 一直赢。
反过来, 只改画布不改数据库/旧字符串, 别的入口仍会打开壳。

## 四条硬判据

- 文件存在且行数 > 0;
- `source_symbol` 在文件里真存在 —— 给了符号就精确命中, **不许退化成「文件第一个 def」**
  (那正是「打开后光标在不相干函数」的根因), 不中就换下一个候选;
- `source_line` 落在该 `def` 的函数体内 (不是函数头、不是相邻函数);
- 落到的文件是算法本体, 不是转发壳 (壳 ≤40 行 / `sys.modules` 别名 / 一行 `from .x import run`)。

## 批量修

1. 候选按可信度命中即停: ① 画布原 `params.source`; ② **注册表里真正被调用的函数对象**
   (`registry.get(node_id)` → `inspect.getsourcefile/getsourcelines` 反查文件 + def 行); ③ 覆盖表
   (内联在大文件里的 `node_*` 胶水、少数走 `_EXTERNAL_LOC` 的节点);
2. 永远别信硬编码的 file:line 字符串, 注册表反查才是真源;
3. `--plan` 出变更表 (节点 / 旧 → 新 / 理由), 确认后 `--apply`; 再跑一次应输出 **0 变更**(幂等判据);
4. 体检要扫全部画布文件 (`sources/canvas/*.json` + `defaults/canvas/*.json`), 报告落盘, 报
   「好 / 坏 / 无映射」条数, 不报「都好了」。

参考实现: `tools/check_node_open_targets.py`(体检) · `tools/fix_canvas_open_targets.py`(`--plan`/`--apply`)。

## 迁移后的老路径怎么留

- 要给人「点开就能读真代码」→ **软链直指本体**(相对路径按链接所在目录算, 建完 `readlink -f` + `wc -l` 验);
- 要保模块级全局单份 (缓存/单例/`isinstance`) → 转发壳;
- 两句都对时, 看消费方: 人阅读 → 软链; 代码 `import` → 壳。

## 生效口径

- GUI 读的是**内存里的画布对象**: 改磁盘 JSON 后已在跑的 studio 仍用旧对象(靠软链兜底还能开), 重启才看新落点;
  按红线只停不起、重启要点名, 交付里写明。
- 画布会被常驻循环回写: 修完比对 md5 前后值与写入时间, 确认没把旧内存态写回磁盘。
