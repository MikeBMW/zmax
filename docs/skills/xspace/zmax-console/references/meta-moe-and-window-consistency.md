# 元数据MOE门控路由 + 独立窗口数据一致性 (老倪 2026-10-13 口径)

## 需求原文 → 三层一一对应
> 「simulink 画布上面工具栏, 增加配置中心的独立打开窗口; 注意, 所有这些独立打开的窗口, 要保证与全系统的
>  数据一致性。数据源来源于全局数据空间, **元数据是整个系统的数据库根服务**; 再次检查数据一致性; 确保每个
>  元数据都是系统的基础核心组成, **类似标准原子模型的玻色子或费米子**, 而**数据空间的每个 topic 类似各种
>  原子, 分子, 有机物**; 映射关系, **全息系统**, 这些逻辑, 都在**阶段专家MOE门控路由**这个节点代码实现,
>  同时这个节点改名为 **元数据MOE门控路由**。」

实现口径 (可复核):
1. **元数据 = 系统数据库根服务** = 18 项基础核心组成: 玻色子型(场/连续量: 位置/姿态/速度/角速度/力/时间/
   置信度/健康度/主参数M/通量) + 费米子型(离散实体: 节点/话题/层级/阶段/技能/报文/场景/任务)。
   每条要有**完整定义**且**禁算法词** (conv/attention/mlp/loss/训练/梯度… 一律不写)。
2. **topic = 原子/分子/有机物** = 由元数据组合而成 (显式规则表 `COMPOSE_RULES`; 语义主源是**源/宿节点的能力名**,
   不是 topic 名 —— 画布连线的 topic 名全叫 `zmax/link_value`, 靠名字什么都分不出来)。
3. **映射关系 + 全息系统** = 0/1 映射矩阵 A(topic×基元) 行空间投影算子 Pr=pinv(A)·A。
   · 全息成立 = 任意足够大的 topic 子集算出的 Pr 与整体一致 (实测 max_op_err 0.0);
   · **必须做退化反证** (少一个 topic ⇒ Pr 不一致), 否则"全息"是白送的假话;
   · 未被任何 topic 承载的基元**不在行空间** ⇒ **不可重构**, 如实报出 (不可约残差 + 未落地基元清单),
   绝不粉饰成"全息成立";
   · 实测结论: 随机小子集**撑不起**整体 (rate 曲线 0.0), 因为 topic 组成高度同构 ⇒ 全息性取决于覆盖面,
   不是"随便拿几个就有整体"。
4. **门控** = 硬先验 7 阶段→7 专家 1:1 (单射), 学习式门控实测坦缩 ⇒ 不用。判据要含**单射性**, "每行最大值"会假阳性。

## 实现/真源
- `tools/meta_moe_router.py`: META_PRIMITIVES / COMPOSE_RULES / incidence() / holography() / route() / report()
  (`report|holography|route` 三个 CLI)。真源 `zmax_data/dataspace/busdb.json` (signals=连线记录 src/dst/topic,
  nodes=节点名)。
- 节点 `node_ss_moe` (`src/lerobot/engineering/nodes/library.py`): docstring 四段口径 + 真跑 `meta_moe_router.report()`
  打印元数据/映射/全息/门控四段真值。**函数名与画布 id 不变** (`ss_moe`/`node_ss_moe`), 只改显示名 ⇒ 不破连线。
- 改名同步**四处**: 画布真源 `data/database/zmax/sources/canvas/state_space_obs.json` 的 name/params.desc ·
  `src/lerobot/engineering/nodes/by_level.py` 显示名 · 名称归一器 `tools/gui/simulink_module.py`
  `(r"(阶段专家|元数据)\s*MOE", "元数据MOE门控路由")` · 节点 docstring。历史变更记录里的旧名不改。
- 判据 `tools/verify_meta_moe_router.py` (17 条): 基元完整定义/禁词/两类 · 映射 100% 覆盖 · 全息(复现误差+退化反证+
  残差) · 门控单射/熵 · 改名四处一致 · 零回归(89 节点/184 连线) · 节点真跑。

## 独立窗口 × 数据一致性
- 口径: 独立窗口**不存私有副本**; 页面每次 `_j()` 直读磁盘真源; 打开即 `reload_from_source()`, 之后每 3s 比对
  `source_fingerprint()` (sha256 前 16 位, 覆盖 config/ 配置 + `data/database/zmax/zmax_engineering.db`) ⇒ 变了就重读。
- 画布工具栏按钮落点 `simulink_module.py`: `mk_btn(...)` + `tl.addWidget(...)` (`tl.addWidget(self.btn_ds_win)` 后面
  接一个 `btn_cfg_win`)。`ConfigCenterPage(model_page=None)` 可离屏独立建。
- **再点复用不新开第二个** (`self._cfg_win` 可见就 raise + reload)。独立窗口里页面顶栏「← 返回主窗口」要改连 `dlg.close`
  (否则它去导航主窗口)。

## 坑 (都是实测踩过的)
1. **判据里的 0.0 会被 `or` 吃掉**: `x.get("err") or -1` 在 err=0.0 时打印 -1 (看着像失败) ⇒ 别用 `or` 给 0 兜底。
2. **禁词表要同时卡定义与名称**, 且定义措辞要让路: `度量张量…梯度怎么走` 命中禁词“梯度” ⇒ 改写为“距离与方向怎么算”。
3. **推导不能想当然**: 子集重构 `s` 需要行数 ≥ 基元数; 直接把 `pinv(A_S.T)` 当重构算子会 `matmul` 尺寸报错 ——
   正确对象是行空间投影算子 `pinv(A)·A`。
4. **改名后必须重绑真源链**, 否则 `ss_task_bind.py --check` 报“不一致 — 真源变了, 需重绑定”:
   顺序 `ss_task_bind.py` → `engineering_db.py build` → `engineering_db.py check` (全绿才算完成)。
5. `git add` 一个 pathspec 不存在/在软链外会**整条命令失败且什么都不加** (如 `config/ss_task_binding.json` 是软链后的
  路径 ⇒ `fatal: pathspec … is beyond a symbolic link`) ⇒ 逐个 add 并看退出码, 别用 `2>/dev/null` 盖住。
6. 子代理可以用 `delegate_task` 并行审计/写文档, 但**验收必须我自己跑判据**; 子代理自报“写完”前不要拿去发版。
