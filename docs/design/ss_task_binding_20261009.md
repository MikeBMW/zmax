# 任务 × 状态空间工程：一个工程承载全部任务（配置清单）

> 2026-10-09 · 静静 · 老倪：「这些任务，都用一个状态空间这一个工程」「完善配置清单这个界面，要实际可运行」
> 新增：`tools/ss_task_bind.py` · `config/ss_task_binding.json` · 工程文件 `reports/projects/SS_主工程_任务配置.zmaxproj`
> 改：`tools/config_center.py`（bind/activate/project）· `tools/gui/veh6_config_page.py`（配置清单列 + 5 个真按钮）

---

## 0. 口径：一个工程，多任务

```
状态空间工程 (唯一)          任务 (工程内的一份配置)
canvas 89 节点 / 184 连线  ←  5 条任务: TASK-01-FW / 02-HANDLE / 03-BI / 04-THERMAL / 05-ATS
run_cfg 6 档位                每条任务: 适用配方段 + 参数覆盖 + 档位 + 触发/循环 + 验收判据
ui                            active_task = 当前生效的那一条 (切换只改它, 不换工程文件)
```
**不按任务分工程文件**。一个工程文件（`.zmaxproj`）里带**全部任务清单**，切换任务只是改 `active_task`。

---

## 1. 机械推导（不手写映射，可复算）

| 步 | 规则 | 依据 |
|---|---|---|
| ① 段→节点 | 每个配方段一张关键词表，在 `节点 id + name + desc` 上匹配 | 关键词取自画布真实节点文本 |
| ② 任务启用集 | `∪(applies_segments 的节点)` | 任务选了哪些段 |
| ② 任务禁用集 | 只被 `excluded_segments` 命中的节点 | 例：上下料不适用「4 插入/5 拔出」⇒ 插入类节点被禁用 |
| ③ 六档位 | 含段 4/5 ⇒ L3全链·流形yaw·L4 INTACT·L4→DiT 开；含段 1/3 ⇒ L2 兼容开；不含 4/5 ⇒ ⚡引擎快演 开 | 段语义 → 运行档位 |

实测（`python3 tools/ss_task_bind.py`）：
```
工程 状态空间工程 · 主工程  src/lerobot/engineering/flows/state_space_obs.json
     89 节点 / 184 连线 · md5 33c2729ce175
段覆盖 53/89 节点 (未覆盖 21: n_hil, n_moveit, ss_l3d_view/L5/LoRA/SAM3 … 非配方段节点)

任务ID              启用  禁用   档位(开)
TASK-01-FW           53    0   L3全链 · 流形yaw · L4 INTACT · L4→DiT · L2兼容
TASK-02-HANDLE       42   11   ⚡引擎快演 · L3全链 · L2兼容          ← 上下料
TASK-03-BI           53    0   L3全链 · 流形yaw · L4 INTACT · L4→DiT · L2兼容
TASK-04-THERMAL      53    0   L3全链 · 流形yaw · L4 INTACT · L4→DiT · L2兼容
TASK-05-ATS          53    0   L3全链 · 流形yaw · L4 INTACT · L4→DiT · L2兼容
```
上下料任务被禁用的 11 个节点 —— 正是"不插拔"该关掉的：
`n_intent_bundle, n_intent_direct, ss_mani_eng, sslat, ssmani_c, ssmani_p, sssk5, sssk6, sssk7, sssk8, ssvlm`

---

## 2. 配置清单界面（首屏，实际可运行）

`📋 任务配置` 页 = 状态空间工程的配置清单：

```
状态空间工程(主工程): 89 节点 / 184 连线 · md5 33c2729ce175 · 承载 5 个任务 · 活跃 TASK-01-FW
┌ 任务ID ──────── 类型 ─────── 适用段 粒度 启用节点 禁用节点 档位 活跃 ── 状态 ─┐
│ TASK-01-FW     插拔+固件校验   8/8   2    53      0      5   ★活跃  ⛔缺站点几何3 │
│ TASK-02-HANDLE 上下料搬运     6/8   3    42     11      3          ⛔缺站点几何3 │
│ …                                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
[🧩 刷新绑定] [📋 配置清单(选中)] [✅ 激活选中任务] [📦 导出工程文件] [🔍 全链校验] [📄 配方] [📋 导出 JSON]
── 结果面板 (每个按钮都在这里出真结果, 可复制) ──
```
- 按钮 = `tools/config_center.py` 的同一份函数（一份逻辑两处用），点【配置清单(选中)】需先在表里选一行；
- 【📦 导出工程文件】真出 `.zmaxproj` 并**回读核验**；
- 【✅ 激活选中任务】写 `config/ss_task_binding.json` 的 `active_task`（切换任务≠换工程文件）。

---

## 3. 实测（离屏真跑，全部真数据）

```
任务表列: ['任务ID','类型','适用段','粒度','启用节点','禁用节点','档位(开)','活跃','状态']
行: 5   TASK-01-FW → 启用 53 / 禁用 0 / 档位 5 / ★活跃
       TASK-02-HANDLE → 启用 42 / 禁用 11 / 档位 3
点【配置清单(选中)】→ 【TASK-01-FW】FW Loading + EEPROM 写/读校验 ← 状态空间工程里的配置清单
   工程 89 节点 / 184 连线 · md5 33c2729ce175 · 适用段 8/8 · 启用 53 · 禁用 0
点【导出工程文件】→ ✅ reports/projects/SS_主工程_任务配置.zmaxproj (117170 B)
   schema zmax.statespace.project/1 · 画布 89 节点 · 任务 5 条 · 活跃 TASK-01-FW · 回读核验 ✅ 一致
回归: ast.parse(studio.py) ✅ → 构造 ConfigModule ✅ → 6 页签 · 默认「📋 任务配置」· 5 行
```
工程文件是真的能被控制台吃的：`project_file.read_summary()` 读得出来（schema/note/run_cfg/canvas 全在），
控制台「文件 → 📂 加载工程文件」直接打开，加载走 `flows.save_canvas`（校验 + 自动备份）。

---

## 4. 命令（随时可跑，不依赖 GUI）

```
python3 tools/ss_task_bind.py                 # 绑定总览 (段覆盖/启用禁用/档位)
python3 tools/ss_task_bind.py --check         # 幂等自检
python3 tools/ss_task_bind.py --activate TASK-02-HANDLE
python3 tools/ss_task_bind.py --export reports/projects/x.zmaxproj
config_center.py bind | bind TASK-02-HANDLE | activate TASK-02-HANDLE | project
```

---

## 5. 红线

- **绝不按任务改画布**：画布是唯一工程真源，任务只引用它；要改画布只能走 `flows.save_canvas`（校验+备份）。
- 任务/绑定/工程文件都是**生成物**：改真源（tasks.json / 画布）→ 重生成；不手改。
- 画布指纹（md5 + 节点/连线数）不符 ⇒ 绑定过期，必须重绑（防止拿旧清单去配新画布）。
- 站点几何未标定 ⇒ 任务**不可下发**（拦截，非警告）。
- 工程文件写在 `reports/projects/`（`.gitignore` 排除，属交付件不属于代码库）。
