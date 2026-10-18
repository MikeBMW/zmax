---
name: zmax-release-versioning
description: Use when 老倪说「小版本迭代到 X.Y.Z / 保存数据」— 版本号多处同步、产物归档、tag 推送一条龙。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [release, versioning, archive, git, tag, zmax]
    related_skills: [zmax-engineering-repo, git-history-slimming, live-service-change-discipline]
---

# Z-MAX 小版本迭代 = 改号 · 归档 · 推 tag

## When to Use
- 「小版本迭代到 5.50.741」「保存数据」「打个 tag 推上去」「发个 Release」。
- 要确认"这版到底改了哪些文件/产物在哪"。

## 铁律

1. **版本号只用用户给的数字。** 没给数字时只改内容、不改号; 自选版本号是明确被禁止的。
2. **数据不靠 commit 保存。** `zmax_data/` 在 `.gitignore` 里 ⇒ 「保存数据」= **归档目录 + 清单 + sha256**,
   不是 `git add zmax_data`(会 fatal 或静默不入库)。
3. **commit 与 tag 是两条推送。** `git push origin HEAD` **不会**带上 tag ⇒ 必须再 `git push origin vX.Y.Z`,
   并 `git ls-remote --tags origin 'vX.Y.*'` 回读确认。
4. **证据只写数字。** 归档里的 evidence 放实测值(延迟/幅度/前后对照), 不写过程叙述。

## 步骤

### ① 改号 (一条命令同步全部位置)

```bash
cd ~/zmax && ./gui-venv311/bin/python tools/bump_version.py --to 5.50.741 --summary-file /tmp/v.txt
```

- summary **一行写完**: 做了什么 + 根因。它会被同时写进 studio.py 的 changelog 与 VERSION.md 表首。
- 该工具覆盖的口径(漏一处就会出现"界面还显示旧号"): studio.py 三处显示(QLabel/状态栏/关于框) ·
  `update_checker.CURRENT_VERSION` · `version_sync.zmax_ver` · `src/lerobot/ops/docs_sync.py` 两键 ·
  `tools/ci/integrity_check.EXPECTED_VERSION` · changelog 行 · VERSION.md 新行。
- 看完它打印的"旧号残留": **只允许留在历史行**(VERSION.md 旧行、旧 changelog); 其它任何命中都要改。
  复核: `grep -rn '5.50.740' --include=*.py --include=*.md . | grep -v 'v5.50.740 |'`。

### ② 归档 (这才是「保存数据」)

照 `tools/archive_release_<ver>.sh` 复制改写(仓库里已有 5.13/5.14/5.15/5.21/5.34/5.41/5.50 的同类脚本), 产物:

```
zmax_data/release_<ver>_<YYYYMMDD>/
  tools/ gui/ src/ docs/      ← 本轮改动过的代码(只拷改过的, 不是整仓)
  data/                       ← 数据快照: 模板/轨迹/状态 json/jsonl
  logs/                       ← 运行日志(证明跑过)
  evidence/measured_<date>.md ← 实测数字汇总
  MANIFEST.md                 ← 主题 + 改动清单 + 目录说明
  sha256sums.txt              ← find . -type f ! -name sha256sums.txt | sort | xargs sha256sum
```

验收(缺这条等于没验): 在归档目录里 `sha256sum -c sha256sums.txt` **全 OK** + 报文件数与体积。

### ③ 提交与推送

```bash
git add VERSION.md tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py \
        src/lerobot/ops/docs_sync.py tools/ci/integrity_check.py tools/archive_release_<ver>.sh
git commit -m "vX.Y.Z: <一句话主题>"
git tag vX.Y.Z
git push origin HEAD && git push origin vX.Y.Z
git ls-remote --tags origin 'vX.Y.*'        # 回读: 新 tag 在不在这边
```

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 只 push HEAD | 本地有 tag, 远端没有 ⇒ CI/发布看着"没触发" | 单独 `git push origin vX.Y.Z` + `ls-remote` 回读 |
| 想用 commit 保存数据 | `zmax_data` 被 .gitignore, add 不进或直接 fatal | 走归档目录 + sha256; 真要入库的是文档/说明, 放 `docs/data_snapshots/` |
| 归档脚本照抄上一版没改路径/版本 | 产物堆到旧版本目录, MANIFEST 写错号 | 复制后只改 `DST` 前缀 + MANIFEST 主题, 跑完用 `search_files(target='files')` 核对目录名 |
| changelog 写成过程叙述 | 下一版读的人不知道改了什么、根因在哪 | 一行: "做了什么 + 为什么(根因)", 不写排查过程 |
| 版本号自选 | 与用户口径冲突 | 只按用户给的数字; 没给就只改内容 |

## 相关
- 仓库口径/入库边界/密钥红线: `zmax-engineering-repo`(user-owned)。
- 长跑服务改完的生效纪律: `live-service-change-discipline`。
