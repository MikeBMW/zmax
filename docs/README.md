# docs 目录说明

一句话：**15 个目录，6 类**。按「干什么用」找，不按时间找。

## 一、分类

| 类 | 目录 | 放什么 | 现状 |
|---|---|---|---|
| **① 方案与架构** | `design/` | 技术方案、架构、算法说明、接线方案、配置规范（含 `design/diagrams/` 图） | 143 件 |
| **② 验收与评测** | `eval/` · `test-reports/` | 评测结论、对比数据、正式测试报告（F02/F03/F04、MASTER-TEST-REPORT） | 21 + 11 件 |
| **③ 对外交付** | `deliverables/` · `patents/` | 给客户/集成商/供应商的成稿（含 `deliverables/outreach/` 立项资料）、专利文件 | 80 + 25 件 |
| **④ 运行与运维** | `ops/` · `patch/` · `web/` | 部署/运维手册、现场补丁片段、页面与状态 JSON | 20 + 7 + 8 件 |
| **⑤ 记录与复盘** | `notes/` · `incidents/` · `memory/` | 交接/收工记录、事故台账、工程记忆 | 66 + 31 + 136 件 |
| **⑥ 参考与快照** | `source/` · `data_snapshots/` · `skills/` · `release/` | 上游框架文档、数据快照、技能导出、版本 changelog | 93 + 50M + 29M + 18 件 |

根目录只留三个入口文件：`INCIDENT-INDEX.md`（→ `incidents/` 的软链）· `PIPELINE_STATE.json`（CI/CD 状态）· `deploy_audit.jsonl`（部署审计）。

## 二、新文档放哪

| 你写的是 | 放 |
|---|---|
| 某个功能/接线的技术方案 | `design/` |
| 一次评测/对比/压测的结论 | `eval/` |
| 正式测试报告 | `test-reports/` |
| 给客户看的成稿（手册/清单/报告） | `deliverables/` |
| 部署步骤、运维命令、现场补丁 | `ops/` 或 `patch/` |
| 今天的收工/交接/复盘 | `notes/` |
| 事故、险情、被拦下的动作 | `incidents/`（并更新 `INCIDENT-INDEX.md`） |

## 三、命名

```
方案    <主题>_<YYYYMMDD>.md          例: PLAN_NODE_PORT_ALIGN_20261101.md
记录    <YYYY-MM-DD>_<主题>.md        例: 2026-10-23_handoff.md
事故    INCIDENT-<YYYYMMDD>-NN-<主题>.md
交付    带版本号或客户名，不加日期后缀（日期用 mtime）
快照    data_snapshots/<YYYYMMDD>_<版本>_<主题>/
```

## 四、三条只读规矩

1. `memory/` 被 `src/lerobot/memory/eng_memory.py` 真读 —— **别改名、别挪目录**，加文件可以。
2. `data_snapshots/` 只增不改（历史证据），要删先确认无脚本引用。
3. `test-reports/` 的 `MASTER-TEST-REPORT.md`、`F03-orin-inference-test.md` 被 `verification_layer.py` 按路径校验，**缺文件即判 FAIL**。

## 五、找不到东西时

```bash
cd /home/ubuntu/zmax
ls docs/*/ -d                                  # 15 个目录
find docs -name '*<关键词>*' -type f           # 按名找
grep -rl '<关键词>' docs --include=*.md        # 按内容找
find docs -mtime -7 -name '*.md' | sort        # 最近一周动过的
```

已知：部分**历史交付件与数据快照**里写的 `docs/AOI_*.md`、`docs/AR_*.md` 等路径，已归位到 `design/` 或 `notes/`；
那些文件按日期冻结不再改，按文件名 `find docs -name` 即可定位。
