# UPH 节拍循环节点 (把页面上的节拍功能做成状态空间节点)

适用: 用户要把「全流程 UPH / 节拍 / 良率统计」这类**已经在页面上跑着的**功能用状态空间节点重做一遍,
或要新增一个按段表推时间的节拍循环器。铁律: **两条并行, 页面一个字不改** (见 SKILL.md「已有页面上的功能要重做一遍」)。

---

## §1 段表字段语义 (先认清哪个字段是件号, 否则 UPH 全错)

唯一依据 `zmax_data/runtime/traj/sim_insert.json`(由 `tools/sim_insert_plan.py` 生成) 的字段口径:

| 字段 | 真实含义 | 用错会怎样 |
|---|---|---|
| `plan` | 段表, 每段一个动作 (move/up/side/down/grip/release/insert/pull) | — |
| `seq` | **件内段号 1..28**, 每件都从 1 重数 | 当全局段号 ⇒ "序号不单调""段数只有 28" 的假失败 |
| `seg_index` (自己累加) | 全局推进指针 | 判进度必须看它 |
| `k` | **搬运批次 1..8**, 不是件号 | 当件号 ⇒ 件数只到 8, UPH 算成 200 出头 |
| `cycles_data` | **件数唯一依据**, 一件一条 (实测 14 条) | 件数 = 14, 不是 `k` 的最大值 |
| `total_t` | 整表时长 (实测 159.43s) | `total_t / len(cycles_data)` = 单件节拍 |
| `tact_steady_s` | 稳态节拍 (实测 11.42s ⇒ 315 UPH) | 与 `total_t/n` 的 11.39s 是两个口径, 别混着报 |
| `loop` / `cum` / `states` | 循环块选择 / 每段累积时刻 / 每段取放占用态 | 循环要按 `cum` 定位, 不要自己重算时间 |
| `uph_target` | 目标 UPH (300) | 显示的"目标"取自这里, 不预先固定 |

**判据先对账**: `len(cycles_data) * tact_steady_s ≈ total_t`。两个数对不上就说明你拿错了件数口径,
此时任何 UPH 输出都不可信 —— 先去读 `cycles_data`, 不要去调公式。

---

## §2 实时 UPH 的三条口径 (不按这三条算, 启动瞬间会报 3000+)

1. **跳过预热**: 前几件含启动/冷启时间, 直接 `件数*3600/已用时间` 在头 0.5s 能算出 3547 这种假值。
   门槛用**时间与件数双条件**: `el >= max(30.0, 3*tact_s)` 且 `done >= 3` 才算实时 UPH, 否则报 `None` 让界面显示"预热中"。
2. **扣掉首件**: `uph = (done-1) / (el - 首件时刻) * 3600` —— 分母分子同时去掉第一件, 否则首件的固定开销永远摊在均值里。
3. **跨轮时钟不复位**: 循环器重开一轮时 `t_all0`(绝对起点)保持, 只复位 `t0`(本轮起点); 每件完成时刻另存 `mod_cum` 列表。
   用本轮时钟算实时 UPH, 每到一轮边界 UPH 就掉一次, 看着像性能退化。

输出里同时给 `uph_target` / `uph_capability` / `tact_s` / `speed_factor`, 让界面能回答"为什么是这个数"。

---

## §3 节点实现骨架 (`src/lerobot/middleware/nodes/n_<语义>.py`)

```python
NODE_ID   = 'ssuph'            # 与画布节点 id 一致
NAME      = '🏭 UPH 节拍循环器'
PORTS_IN  = ['in1']            # 端口 = 画布连线的两端, 声明了没接下游的端口不存在
PORTS_OUT = ['out1', 'out3']
PURE      = True               # 纯计算节点才置 True; 要动设备的一律 False

def compute(ctx):
    ...                        # 必须返回 dict, 键 ⊆ PORTS_OUT
    return {'out1': act_tok, 'out3': metrics}
```

- 🔴 **算法不许写进 `n_<单词>.py` 外壳里**: 画布每次 `flows.save_canvas()` 会按 `node_names.json` **重新生成**
  全部 `n_*.py`(实测一次覆盖 78 个文件, 手写的 compute 直接变回 `PURE=False` 直通空壳)。正确做法 = 三件套:
  ① `node_names.json` 登记 `"ssuph": "uph"`(生成 `n_uph.py`) ② 算法住独立文件
  `src/lerobot/engineering/nodes/uph_tact_impl.py` ③ 在 `engineering/nodes/library.py` 末尾
  `_reg("ss_uph", ["UPH 节拍循环器", …], "…", _uph_impl.run)`。外壳的 `IMPL_KEY` 由
  `registry.match_node(节点名)` 反查得到(名字要能命中关键字列表), 不用手填。
- 🔴 **`PURE` 由画布参数控制, 否则重生成即回 False**: `tools/gen_middleware_nodes.py` 原先把 `PURE = False`
  预先固定; 已改成读节点 `params.pure_verified`。要开某节点的计算面 = 画布 params 加 `pure_verified: true`
  (经 `flows.save_canvas` 写), 再跑一次生成器。判据: 生成后 `grep "^PURE =" n_*.py` —— 只有该节点是 True,
  其余恒 False(红线: 会动设备的 `EXEC_MODE=act` 不许开)。
- 🔴 **`compute` 只收 dict**: 返回 numpy 数组/标量会落成 `实现返回非 dict → 直通`, 表现为"PURE=True 也什么都不发生"。
- 画布侧仍要在 `engineering/nodes/library.py` 注册逻辑 (双击看源码/单步), 两套注册不是一回事。
- 加速跑判据时用环境变量把时间轴压缩 (如 `ZMAX_UPH_SPEED=50`), 但**输出的 UPH 必须仍按真实秒算** ——
  倍速只让测试快, 不许让 UPH 跟着变, 否则页面显示的是假产能。

---

## §4 判据清单 (`tools/verify_uph_tact_node.py` 同型)

1. 段表真加载: 条数 == `len(plan)` · 每件段数 == `len(plan)/len(cycles_data)`
2. 推进: 同一轮内 `seg_index` 单调递增且 `max > 300` (直接跑几百拍, 别只跑一拍)
3. 动作覆盖: 段表里出现的每一类动作都被分发过 (漏一类 = 某段静默不动作)
4. UPH 口径: 稳态值落在 `3600/tact_steady_s` 的 ±3% 内 · 预热期返回 `None` 或标记预热
5. 件数: `done` 最终 == `len(cycles_data)`, **不是** `max(k)`

跑完把倍速变量与画布状态复位 (判据自身不留现场)。

---

## §5 节拍实测基线 (回答"300 能不能做到"时用这四条, 别自己重算)

| 口径 | 总时长 | UPH | 说明 |
|---|---|---|---|
| 页面自报 (稳态平铺块) | 159.43s / 14 件 | ~316 | `tact_steady_s=11.42` 推的, 乐观值 |
| 空走 100mm/s | 308.31s | 163 | 保守下界 |
| 300mm/s | 209.06s | 241 | |
| 1000mm/s (安全上限) | 174.32s | 289 | 单臂串行天花板 |

结论: **单臂串行在安全速度上限内到不了 300 UPH**, 必须双臂并行 (右臂插拔 + 左臂搬运同时跑)。
回答产能问题时要带这四条, 并说明页面那 316 是几何稳态、不含真机加减速与检测等待。

---

## §6 550C 载荷约束 (端侧真正跑这条循环前必看)

- 单次下发段数 1..8 ⇒ 段表要切片: 419 段 ≈ 53 次下发。
- 每次下发往返 ~200ms ⇒ 光通信就 ~10.6s, 几乎吃掉 12s/件 的预算。
- 想看近实时必须**先合并相邻段**(同方向同速度合并成一段) 或把循环器放到下发侧本地, 别指望逐段往返。
- 段表跳变处若 `a` 写的是中转位, 要补 bridge 段, 否则执行器会自己去走一条不存在的直线 (实测 392 段补 27 段 → 419 段)。

---

## §7 前端那套现有的 300UPH 按钮 (只读地图, 别改)

`tools/web/tcp-ar.html`: `#bPlant`(🏭 全流程 UPH) → `plantToggle()` → `GET /api/sim_insert` → `inspPrepare()`
→ `plantStart()` → `requestAnimationFrame(plantStep)` → `plantAt(simT)` 插值关节角驱动**仿真臂** → `plantHud()` 出数。
节拍/UPH 由 `plantCtx()` 取相邻两块稳态轮次拼成无缝平铺块算出。全程纯前端, **零真机指令**。
用户问"这个按钮现在怎么实现的"时按这条链答, 并在末尾说明: 这是几何推算, 不含加减速/等待; 状态空间节点是并行的第二条实现。

---

## §8 本机(550B)没有常驻的画布节点执行器 —— 要跑节点必须先补一个

`zmax-ss-engine-loop` 跑的是 `ManifoldEngine.step`(数学流形), **不是**画布节点;
能跑画布节点的只有 `tools/mw_project.py step`(一拍就退) 和控制台 GUI 内的 tick(窗口关着就不跑)。
⇒ "由状态空间的节点实现"在本机落不了地, 除非补一个常驻循环。`tools/ss_canvas_loop.py` 就是它:

- `load_project()` 读画布唯一依据 → `prj.step(only=WHITELIST)` → 落 `zmax_data/ss_live/canvas_loop.json`(帧龄/节点状态)。
- 🔴 **必须白名单** `ZMAX_CANVAS_ONLY=ssuph`: 默认跑全部 78 节点会真调模型/硬件。
- 画布 mtime 变了自动重载(加节点不用重启服务)。
- unit `zmax-ss-canvas-loop.service`(Restart=always), 环境里带 `ZMAX_CANVAS_ONLY` / `ZMAX_UPH_AR_PUB`。
- 判活看 `canvas_loop.json` 的 `traces[].status` 是否为「实现执行」—— 若是「直通 (PURE=False…)」说明
  该节点还没开计算面; 若是「实现未注册」说明 registry 关键字没命中。

---

## §9 画布节点驱动 AR 场景虚拟臂 (真机零指令的那条通道)

要让「plan 出来的动作」在 AR 页面看得见, 加一条**只渲染**的通道, 三处:

1. 节点每拍写 `zmax_data/ss_live/ar_cmd.json`(`{a,b,u,seq,mod,kind,t_seg,src}`) —— 由环境变量
   `ZMAX_UPH_AR_PUB=1` 打开; 只写渲染量, 不碰 `ctl_auth`/`l2_daemon`。
2. 8797 加只读端点 `GET /api/ar/cmd`: 读该文件返回 `{ok,fresh,age_s,a,b,u,…}`, 超过 `AR_CMD_FRESH_S=3.0` 报
   `fresh=false` 并给 `note` —— 页面据此回落到自身播放, 不会卡死。
3. 页面只在 **AR 开关=开 且 cmd fresh** 时接管(`plantAtAR()` 用 `a/b/u` 插值 TCP → 页面既有 `ikTool1` 解关节 →
   驱动虚拟臂), 其余一律走原来的 `plantAt(simT)` ⇒ **普通模式行为零变化**。轮询 100ms(一段≈0.4s, 每段约 4 次更新)。

判据: 字段齐全 · `u∈[0,1]` · `seq` 递增 · `/api/ar/cmd` fresh · 停写 4s 后 `fresh=false`(回落) ·
`real_auth=false` 且 `ctl_auth armed=false`(真机零指令)。脚本 `tools/verify_ar_cmd_chain.py`。
浏览器级取证: `browser_console` 读 `ARCMD.on/fresh/seq` 与 `PREV.ssOn/ssSeq`、点 `#bPlant` 后看 `ssSeq` 真推进
(实测 14→16→18→20, `q` 关节角在变, 指令帧龄 0.05s) —— **API 通 ≠ 页面进了那个模式**。

⚠️ 改服务端 `.py` 要重启 8797(`systemctl restart zmax-traj-ar`); 同服务的 html 热读不用重启。
