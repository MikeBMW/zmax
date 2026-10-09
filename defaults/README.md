# 出厂骨架 (Platform Defaults)

本目录是 **Z-MAX 平台仓库的出厂数据骨架**：结构在、数值空。

安装一套全新环境时，用本目录生成一个实例数据包：

```bash
python3 tools/instance_init.py --new /path/to/instance      # 用骨架新建实例包
python3 tools/instance_init.py --link /path/to/instance     # 平台指向该实例包
python3 tools/engineering_db.py build                       # 由真源构建工程库
python3 tools/instance_init.py --check                      # 边界体检
```

## 与实例数据的关系

| | 平台仓库（本仓库，可公开/开源） | 实例数据包 `data/database/<产品>/` |
|---|---|---|
| 内容 | 代码 · 平台文档 · **本目录出厂骨架** | 真源（标定/平台定义/任务/订单/机器人/状态机/能力库/画布）· 工程库 · 总工程 · 归档 |
| 归属 | 平台研发方 | 使用方自有，可自定义、可迁移、可另行托管 |
| 生成方式 | `tools/instance_init.py --new` 复制本目录 | 由使用方在平台上配置/标定产生 |

## 骨架生成规则

- **JSON 文件**：与真源同构，键保留、列表清空、数值置 `0`、字符串置 `""`。
- **`feature.dbc`**：保留 `VERSION` / 模型节点(`BU_`) / 数据流形态(`FLOW_`) 等平台结构行，去除全部能力行（`BO_` / `SG_`）。
- **画布 `canvas/state_space_obs.json`**：空画布（节点、连线为空）。

## 未包含的内容（需在实例内生成）

| 内容 | 说明 | 生成方式 |
|---|---|---|
| `config/moveit_xms5/` | 机器人 MoveIt 运动学/关节限位/规划器配置，与具体机型绑定 | `tools/gen_moveit_config.py` |
| `config/state_machines/*.yaml` | 工序状态机，与具体产线工艺绑定 | 控制台配置 |
| `config/ib_robot_config.yaml` | 机器人现场参数 | 现场配置 |

> 平台/实例 边界规范见 `docs/notes/platform_vs_instance.md`。
