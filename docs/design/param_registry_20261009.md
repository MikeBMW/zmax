# 🎛 数据一体化工程: 全局可改数字 → 链路 → 代码 (2026-10-09 老倪)

> 老倪: 「全局梳理所有可以更改的数字…改变任意数值均可链动 功能·性能·代码逻辑; 状态空间工程是一个整体,
> 修改不同层的数据即表现出不同功能特性; 从顶层产品性能的数据改变, 直接调整代码; 中间的代码要完整映射
> 这个全局架构; UI 用颜色区分不同用途。」

## 一、三层架构 (数据一体化)

```
真源 (人可编 · 进 git)              数据面 (扫描+注册+校验)         交互面 (GUI/服务)
┌──────────────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ config/platform/*.json   │   │                        │   │ 🎛 参数中心 (改数字)      │
│ config/calib/*.json      │──▶│ tools/param_registry.py│──▶│ 📋 功能清单 (产品/子系统) │
│ flows/state_space_obs.json│  │  162 个数字 + 影响链    │   │ 🖥 状态空间画布 (执行)     │
│ 源码 (常量/默认参数)      │   │                        │   │ 📡 :8798 只读 JSON 服务   │
│ feature.dbc / FEATURES   │   └───────────┬────────────┘   └──────────────────────────┘
│ reports/projects/*.proj  │               │ 装载
└──────────────────────────┘               ▼
                        data/database/zmax_engineering.db  (单一文件 = 一套工程; 0.87 MB)
```

**一句话**: 数字只有一份真源, 库与界面都是它的投影; 界面不认识工程文件, 只认那一个库。

## 二、五类数字 (颜色即用途)

| 颜色 | 类 | 数量 | 真源 | 写口 |
|---|---|---|---|---|
| 🟡 | 标定/真源参数 | 45 | `config/calib/zmax_calib.json`(+manifold) | JSON 路径写 (支持 `camera.K[0][0]` 这类下标) |
| 🔵 | 画布节点数据 | 78 | `flows/state_space_obs.json` 节点 params | 节点 params 写 (画布重载生效) |
| 🟣 | 代码常量/默认参数 | 25 | 源码 (`safety.py` / `planner.py` / `cognition.py` / `dynamics.py` …) | 定点改行 + **语法校验，坏则回滚** |
| 🟢 | 顶层产品性能 | 8 | `config/platform/zmax_platform.json` 的 KPI 文本 | 原地替换那个数, 保留比较符/单位 |
| 🟠 | 运行开关/调试档位 | 6 | `config/platform/param_spec.json` | 档位枚举校验后落地 |

每个数字的元数据: 中文名 · 当前值 · 默认值 · min · max · 单位 · 档位 · 真源文件与位置 · 归属子系统 ·
影响说明 · **口径**。

**口径三态 (不许含糊)**:
- `已定义(人工)` — 人工在 `param_spec.json` 里确认过的范围;
- `范围自动推断(未确认)` — 由当前值推的粗略界 (仅用于拦截明显越界, 界面显式标注);
- `未标定(缺口)` / `未定义` — 值就是 null (T_base_cam / plane_z / cell_geometry.points) 或档位未定。

## 三、改数 → 链动 (一条数字一条链)

```
用户改数 (GUI 双击 / set_param)
  ① 校验: 类型 · 范围(min/max) · 档位枚举 · 只读
  ② 预览影响链 (dry-run): 子系统 → 功能 → 模块 → 代码文件:行 → 产品 KPI
  ③ 落真源: 备份(.<file>.bak_<ts>) → 写 → 回读核对 (代码类再跑 ast 语法校验, 坏则回滚)
  ④ 留痕: 唯一工程库 `data/database/zmax_engineering.db` 的 `param_events` 表 (时间/参数/旧值/新值/真源/结果)
     —— 2026-10-09 收口: 不再写 param_events.jsonl (老倪「所有数据都要整合进统一的数据库」), build 不清空该表
```

实测链路样例:
- `calib:manifold_engine.M` → 子系统 sys2 · 24 条功能 · 模块 1 · KPI (L4 专家自主/流形世界模型)
- `code:...cognition.py#__init__:insert_depth` (0.0005) → 文件:行 86 · L2 收口插入深度
- `platform:PF-Z700-01#1` (4mm) → 产品特征 KPI 文本原地改 → 回读一致 → 还原

## 四、装配关系 (代码完整映射架构)

```
特征(feature.dbc BO_) ← 产品特征(PF-Z700-xx) → 子系统(sys2/sys1/sys0/plat)
                                                  ↓ 行带归属
                                          功能(74) == 画布节点(74)
                                                  ↓ 模块名
                                          模块(74) → 代码符号+行号 (nodes/library.py)
                                                  ↑ 数字
                                          参数(162): 每个数字都挂到 功能/模块/系统 (375 条链接)
```

## 五、踩坑 (写进技能)

1. **列表下标路径**: `camera.K[0][0]` 必须解析下标, 否则内参改不了 → 加 `_path_tokens/_get_path/_set_path`。
2. **null 不是"读不到"**: `plane_z.value = null` 是现场缺口, 判据必须区分「路径不存在」与「值就是空」。
3. **负值范围**: 畸变系数是负的, 范围推断不能写死 `0..n`。
4. **自动推断不许冒充人工定义**: 范围来源要带 code=curated/auto, UI 与判据都按它显示。
5. **画布 params 大多是元数据**: `state_space/row_bg/bg/status` 不是旋钮, 过滤后 149 → 78。
6. **代码数字不只在模块级**: `insert_depth=0.0005` 在函数默认参数里 → 扫描要覆盖签名默认值 (3 → 25)。
7. **顶层 KPI 的数字也在真源里**: 用正则从 KPI 文本抽量化目标, 写回时原地替换, 保留比较符与单位。

## 六、命令行

```bash
python3 tools/param_registry.py list|stats|show <id>|chain <id>|verify|seed
python3 tools/param_registry.py set <id> <value>          # 预览 (dry-run)
python3 tools/param_registry.py set <id> <value> --write  # 落真源 (备份+回读)
python3 tools/engineering_db.py build|check|query "product Z700"
python3 tools/verify_param_center.py                      # 8 项判据
```
