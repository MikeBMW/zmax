# 平台 / 实例 解耦规范

> 2026-10-09 定版。目标：**平台代码可公开开源，你的数据可独立迁移、可自定义、可另行托管。**

## 1. 一条线划清

```
/home/ubuntu/zmax/                        ① 平台仓库  —— 可公开 (GitHub)
├── src/  tools/  tests/  examples/  docker/  dds/  scripts/  launch/   ← 代码
├── docs/                                                               ← 平台文档 (设计/参考/技能/记忆)
├── defaults/                                                           ← 出厂骨架 (结构在, 数值空)
├── pyproject.toml  Makefile  README.md  LICENSE  ...

/home/ubuntu/zmax/data/                   ② 实例数据根 —— 你的, 可迁移
├── database/zmax/                        ★ 实例数据包 (一个产品一个目录)
│   ├── zmax_engineering.db               工程库 (由真源 build)
│   ├── zmax_space.proj                   总工程 (GUI「打开总工程」)
│   ├── README.md                         产品/数据手册
│   ├── archive/                          历史工程快照
│   └── sources/                          ★★ 真源 (可编辑/可标定)
│       ├── config/                       标定 · 平台定义 · 任务 · 订单 · 机器人 · 状态机 · MCD
│       ├── feature.dbc                   能力库
│       └── canvas/state_space_obs.json   状态空间画布真源
├── datasets/  memory/  scene/  calib/  skills/   (其余实例数据桶)

/home/ubuntu/zmax/ (本机环境, 不入库)      ③ 环境与大件
├── zmax_data/   数据盘: 模型权重 · HF 缓存 · 密钥 · 备份      external/  第三方仓库 (lerobot fork)
├── venvs/       Python 环境                                  reports/   训练/评测产物
└── models/  media/  out/  toolchains/  backups/
```

**判据一句话**：平台仓库里出现的必须是「谁都一样」的东西；出现「只有你家产线才有」的数值，
就是解耦漏了 —— `tools/instance_init.py --check` 会报 ❌。

## 2. 迁移：搬一个目录 = 换一套数据

```bash
# 迁出 (打包带走)
tar czf zmax_instance_$(date +%Y%m%d).tgz -C data/database zmax

# 迁入 (在目标平台)
tar xzf zmax_instance_*.tgz -C data/database
python3 tools/instance_init.py --link data/database/zmax     # 平台指向它
python3 tools/engineering_db.py build                        # 重建工程库
python3 tools/instance_init.py --check                       # 边界体检
```

迁完后平台**零代码改动**即可运行：标定、产品定义、任务、订单、机器人参数、能力库、画布全在实例包里。

## 3. 实现机制

| 层 | 做法 |
|---|---|
| 真源落位 | `config/` `feature.dbc` `src/.../flows/state_space_obs.json` 移入 `data/database/<产品>/sources/` |
| 兼容 | 仓库内原位放**相对符号链接**，110 个文件里的 `config/xx` 字面路径零改动仍可用 |
| 原子写 | `flows.save_canvas` 写前 `realpath`，保证写的是真身、不顶掉符号链接 |
| 出厂默认 | `defaults/` 提供结构同构的空骨架；`instance_init.py --new` 一键铺开 |
| 公开边界 | `.gitignore` 排除 `/config` `/feature.dbc` `/src/.../state_space_obs.json`，`git rm --cached` 退出跟踪 |
| 切换实例 | `ZMAX_INSTANCE=<dir>` 环境变量或 `instance_init.py --link <dir>` |

## 4. 验收判据

`python3 tools/instance_init.py --check`（四段）：

1. **真源指向**：`config`/`feature.dbc`/画布 是符号链接且落在实例包内；
2. **实例包完整性**：库 + 总工程 + 手册 + `sources/{config,feature.dbc,canvas}`；
3. **公开仓库干净**：三者均未被 git 跟踪；
4. **出厂骨架在**：`defaults/` 非空。

配合全链路判据（`engineering_db check` · `verify_platform_spec` · `verify_param_center` ·
`probe_open_space` · `verify_project_archive`）全绿 = 解耦未伤功能。

## 5. 边界之外（本机环境，不属于任何一方数据）

`zmax_data/`（数据盘：模型/HF/密钥/备份）、`external/`（lerobot fork 等第三方仓库）、`venvs/`、
`reports/`（训练评测产物）、`models/`、`media/`、`out/`、`toolchains/` —— 均为本机环境与产物，
既不进平台仓库，也不属实例数据包；换机器时按 `system-replication-twin` 的清单单独处理。
