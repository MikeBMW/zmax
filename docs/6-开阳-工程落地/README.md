# 6-开阳 · 工程落地

本层管**"代码在哪、怎么跑、坑在哪"**。最大的一层（655 文件），按用途分。

## 分区

| 子目录 / 文件 | 放什么 |
|---|---|
| `ARCHITECTURE-OVERVIEW.md` · `architecture_layers_v511.md` | 全局架构（先看这两份） |
| `ops/` | 部署运维、启停脚本、常驻服务 |
| `patch/` | 现场补丁（问题 → 补丁 → 回滚方式） |
| `release/` | 发行记录（版本号、改了什么、怎么回退） |
| `web/` | 站点与前端 |
| `source/` | 源码位置索引 |
| `diagrams/` · `figs_ar_robot/` | 架构图/流程图（图与文对应，改图要改文） |
| `data_snapshots/` | ⚠️ 证据快照，按日期冻结，**只增不改** |
| `evidence_20260922/` | 当时的取证输出 |
| `*.md`（根） | 专项：MoveIt 精确控制、L2 daemon 调试、场景坐标唯一真源、配置中心、ECS 迁移、数据空间映射… |

## 找代码位置的正确方法

不要在本层翻文档找路径 —— 用**映射表**：

```bash
gui-venv311/bin/python tools/verify_doc_code_map.py --strict   # 概念 → 文件 → 符号
cat docs/0-总纲/CODE-MAP.md                                     # 人或机器都可读
```

映射表里每一行都经过校验：路径不存在或符号找不到就判 FAIL。

## 踩坑记录位置

- 通用坑 → `7-瑶光-记录追溯/notes/`
- 事故 → `7-瑶光-记录追溯/incidents/INCIDENT-INDEX.md`
- 版本相关 → 本层 `release/`

## 出口

- 为什么这么设计 → `4-天权-模型算法/`
- 这么做有没有达标 → `5-玉衡-指标验收/`
