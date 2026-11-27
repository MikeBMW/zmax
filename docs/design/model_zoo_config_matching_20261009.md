# Model Zoo × 工程配置：如何区分、如何匹配（三层分离 + 契约求交）

> 2026-10-09 · 设计：静静 · 配套实测：`tools/model_site_match.py` → `config/mcd/match_matrix.json`
> 前置：`docs/design/veh6_config_center_mcd_20261009.md`（VEH.6 四域 × MCD 三轴）· `docs/third_party_model_spec.md`（模型包 v1）

---

## 0. 结论先行

**区分的不是"模型名字"，是三件正交的事**：`域(domain)` × `层(layer)` × `角色(role)`。
**匹配的不是"手工记表"，是契约求交**：模型声明 `requires`（我要哪些现场事实），站点提供 `available`，
求交出 **OK / 缺项 / 不适用** 三态 —— 可执行、可复算、可报警。

```
模型包 (随模型走)          站点工程配置 (随现场走)         组配 Binding (一次运行)
manifest: 结构/权重+sha16   config/calib/*.json           逐层选型 + 档位 + 场景 + 覆盖
  输入输出契约/归一化契约      坐标系/几何/相机/工具/机器人     → run_cfg + binding_id(sha16)
  能力 CM_ / runtime           9 项现场事实                    → 可回溯: "当时到底哪套配置"
  依赖声明 requires ─┐        available ─┐
                     └──── 契约求交 ─────┘  ⇒ 兼容矩阵 (OK/缺项/不适用)
```

**关键：工程配置不写进模型包。** `T_base_cam` 同时服务 L2/L3/L4 三个模型，
复制进三个包 = 三份真相，换一次相机要改三处。模型包里只放**指针 + 期望 + 容差**，真值永远在站点配置。

---

## 1. 现状盘点（这不是从零建，是补一层）

| 已有真源 | 作用 | 什么已有 | 缺什么 |
|---|---|---|---|
| `src/lerobot/engineering/models_manifest.json` | 模型**版本**真源（`in_service/candidate/untrained` + `probe`），`status_hub` 消费成 `/status/all` | 名称/版本/状态/产物路径/来源/探针 | **契约段**（输入输出/域/依赖/归一化） |
| `models/active_models.json` | **在役指针**真源（L2/L3/L4 + `candidates` + promote） | 指针/软链/sha16/env 覆盖 | 同上（模型能力与依赖） |
| `docs/third_party_model_spec.md` | **模型包标准 v1** | `format/name/node/version/capabilities/interfaces/weights/adapter/runtime/config` | `domain` / `requires` / `normalization` / IO 语义 |
| `tools/model_autoload.py` | 加载/切换/promote | L2/L3/L4 加载器 + 显存门 | 加载前的**匹配前置校验** |
| `flows/model_zoo.json` | Model Zoo 画布 | 11 个模型家族（ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE/MLP蒸馏/官方专家…）各一行 | 每行的**配置卡 + 兼容徽章** |

⇒ 本设计的动作：给模型包 manifest **加 4 个字段**（`domain/requires/normalization/io`），
再加一个**匹配器**；不新建第二套模型体系。

---

## 2. 如何区分（三个正交维度，配置差异全来自它）

| 维度 | 取值 | 它决定什么配置 |
|---|---|---|
| **域 domain** | `metaworld`（仿真）/ `real`（真机）/ `board`（板坐标）/ `engine`（引擎内小模型）/ `cloud`（云端 VLM） | **是否需要站点几何**（`real` 必须 T_base_cam/plane_z/cell_geometry）；归一化口径；图像尺寸 |
| **层 layer** | L2 / L3 / L4 / L5（+ `—` 未挂层） | 它是哪个**在役槽位**、被谁调用、归哪一档能力（L2 只 G1+G3 / L3 +G2 / L4 +G0 / L5 只读） |
| **角色 role** | 检测 / 分段控制 / 策略 / 意图-动作 / 规划 / 肌肉记忆 | 输入输出语义与**归一化有无**（检测类与规则类无动作归一化） |

例（真实身份）：
```
L3.smolvla_lew  = 域 metaworld × 层 L3 × 角色 策略   ⇒ 只需 cam.K, 不需要 plane_z/T_base_cam
L4.intact       = 域 real      × 层 L4 × 角色 意图-动作 ⇒ 必须 cam.K+T_base_cam+plane_z+cell_geometry
L2.yolo_peg     = 域 real      × 层 L2 × 角色 检测     ⇒ 只需 cam.K/cam.dist (无动作归一化)
```
**同一层可以并挂多个候选**（在役/候选），配置差异靠 `domain + requires` 自动区分，不靠人记。

---

## 3. 匹配 = 五类契约求交

| # | 契约 | 谁声明 | 谁提供 | 不匹配的后果 |
|---|---|---|---|---|
| 1 | **输入契约** | 模型 `io.in`（obs 维度/通道/图像尺寸/触觉） | 感知链（`n_enc_obs` 43D / 39D / 640×480 RGB / 触觉 4D） | 维度不符 → 加载即崩；UI 给"少一路触觉"的明确提示 |
| 2 | **输出契约** | 模型 `io.out`（动作 4D `dx,dy,dz,grip` / 6D 关节 / chunk 长度） | L2 收口闸（期望 4D） | 动作语义错 → **零动作伪装**（必须显式拒绝，不能静默） |
| 3 | **域契约** | 模型 `domain` | 站点（`real` 需 geometry 齐） | `real` 模型缺几何 → **能跑但不对**（最危险）⇒ 判 `MCD-E02` 拦下 |
| 4 | **归一化契约** | 模型 `normalization`（per-dim stats 的 sha16 / "训练集同源"） | ckpt 自带 stats | 不同源 → 静默退化（铁律：必须同源，**不匹配 = 拒绝加载**，不是警告） |
| 5 | **载荷/工具契约** | 模型 `requires` 含 `tool_payload/TCP` | 站点（`tool_payload.mass_kg` / `control_tcp.offset_xyz_m`） | 力控/插入类偏 → 3D 分解误差 |

**三态判定规则（写死，避免"全绿"假象）**
- `OK` = 模型**声明需要** 且 站点**有真值**（值非 null）
- `缺项` = 模型声明需要 而 站点为 null ⇒ 红格 + 原因 + 补法（现场量/示教/标定）
- `不适用` = 模型**没声明**（不是"缺"） ⇒ 灰格，不报错 —— 这条最重要：没有它，矩阵会一片红，看不出真问题。

---

## 4. 冲突消解（谁说了算，写死）

| 参数级 | 谁赢 | 规则 |
|---|---|---|
| G1 安全红线 / G3 现场几何 | **站点永远赢** | 模型只能"要求"，**不能改**；现场值不符 = 拒用（模型适应现场，不是现场迁就模型） |
| G2 性能参数 | **组配覆盖赢** | 模型给默认值，binding 可覆盖；覆盖必须落盘可回溯 |
| 归一化 stats | **谁都不能覆盖** | 只能与 ckpt 训练集同源；不符 = 拒绝加载（不降级、不警告） |
| 能力 ID | 能力库赢 | manifest 里 `capabilities` 必须存在于 `feature.dbc`（`BO_` 31 条），越界 = 拒绝导入 |

---

## 5. 命名与版本（出问题能还原"当时哪套"）

```
模型 ID    <层>.<家族>.<版本>#<sha16>    L3.smolvla_lew.v10#64ae35b5 · L4.intact.intact_l4_current
站点 ID    <站点>.<工位>.<版本>          SITE-A.ST11.v3
组配 ID    binding_id = sha16(逐层模型 ID + 站点 ID + 档位 + 覆盖参数)
```
报告/评估/产线记录都引 **binding_id** —— 事后能精确还原"这条数据是哪套模型 + 哪套工程配置跑出来的"。

---

## 6. 实测：兼容矩阵（`tools/model_site_match.py`，真跑）

站点工程配置就位 **6/9**（缺 `T_base_cam` · `plane_z` · `cell_geometry.points`）；能力库 `BO_` **31** 条。

```
model          cam.K  cam.dist T_base plane_z depth_s cell_geo robot.dof tool_pay tcp_off   判定
L2.yolo_peg     ✅      ✅       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
L2.skill_mlp    ·       ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
L3.smolvla_lew  ✅      ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
L4.intact       ✅      ·       ⛔     ⛔      ·       ⛔       ·         ·        ·      ⛔ 缺 3 项
L5.deepseek_vl  ·       ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
MZ.act          ✅      ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
MZ.vla_touch    ✅      ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
MZ.awe          ✅      ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
MZ.expert       ·       ·       ·      ·       ·       ·        ·         ·        ·      ✅ 可用
MZ.l2_muscle    ·       ·       ·      ·       ·       ·        ·         ·        ✅      ✅ 可用
可用 9/10 · 受阻 1 · 按层 {L2:3, L3:1, L4:1, L5:1, —:4}
```

**读法（这是这份矩阵最大的一次信息量）**：唯一受阻的正是**唯一真机域的在役模型 `L4.intact`** ——
其它 9 个都是仿真域（`metaworld`/`engine`/`cloud`），本来就不需要站点几何。
⇒ **"域"就是第一判据**：仿真模型对工程配置几乎无依赖，真机模型一缺几何立刻红。
这也解释了为什么"模型很多但只有真机那层总出问题"。

---

## 7. UI 落点（VEH.6 + Model Zoo 画布）

1. **Model Zoo 每行加「配置卡」**：manifest 摘要（域/层/角色/版本/sha16/IO/归一化）+ **兼容徽章**
   （对当前站点：✅ 可用 / ⛔ 缺 N 项 / · 不适用），点徽章弹出缺项与补法。
2. **VEH.6 新增「组配 Binding」页签**：左 = 站点工程配置真值（读 `calib`）；中 = **逐层选型下拉**
   （L2/L3/L4/L5 各选在役或候选）；右 = 匹配矩阵 + 冲突提示 + `[试配]`（dry，不落盘）`[应用]` `[存为工程文件]`。
3. **一键"为什么不可用"**：点红格直接给「缺 `plane_z` → 现场量台面高度 → `ss_geom_calib.py --record`」。
4. **反查**：从 `binding_id` 反查当时逐层模型 + 工程配置 + 覆盖项（报告/评估页共用）。

---

## 8. 落地批次

| 批 | 内容 | 判据 | 碰 GUI |
|---|---|---|---|
| **B1 ✅已落** | `tools/model_site_match.py` + `config/mcd/match_matrix.json` | 矩阵可复算；真机域模型正确受阻；`不适用` 不误报 | 否 |
| **B2** | 模型包 manifest 加 4 字段（`domain/requires/normalization/io`）+ `validate` 扩校验；`models_manifest.json` 逐条补契约 | 每个在役模型都有完整契约；缺字段被拒 | 否 |
| **B3** | `tools/zmax_bind.py`：binding 生成/校验/落盘（run_cfg + binding_id）+ 覆盖规则（G1/G3 拒绝覆盖） | G1/G3 覆盖被拒；`binding_id` 可复算；反查一致 | 否 |
| **B4** | VEH.6「组配 Binding」页签（选型 + 矩阵 + 试配/应用） | 三层验证；矩阵与 `match_matrix.json` 逐格一致 | GUI |
| **B5** | Model Zoo 画布每行配置卡 + 兼容徽章 | 徽章状态 = 匹配器输出；既有连线不动 | 画布 |

---

## 9. 红线

- 工程配置不进模型包（一份真相）；模型包只放 `requires`+容差。
- 归一化不同源 = **拒绝加载**，不降级、不警告。
- `real` 域模型缺站点几何 ⇒ 判 `MCD-E02` 拦下，**不允许"先跑起来再说"**。
- 本匹配器**只读**（不改 calib、不改在役指针、不切权重）。
- 矩阵里的契约目前部分为**设计推定**（`declared_by` 字段标明证据来源：`active_models.json` / 画布 / 推定），
  B2 起逐条换成模型包自带 manifest —— 未换成的不许当"已证明"用。
