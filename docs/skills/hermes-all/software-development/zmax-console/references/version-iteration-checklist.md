# 小版本迭代清单 (Z-MAX)

## 触发
老倪: 「保存数据，小版本迭代」= **现场数据存档 + 代码提交 + 版本号 + tag**。

## 0. 先自己提交, 再跑同步 (最容易白干的一步)
每 6h 的同步 job(`sync_hermes_to_repo.sh`)会 `git add -A` 后原样提交并 push
⇒ 工作区里**任何未提交的改动都会被卷进 `sync:` 消息**(实测: 一条正经迭代的改动被它先提走、提交消息被吞,
只能事后补 follow-up 提交 + 补 tag 正名)。⇒ **迭代先自己 commit, 再让同步跑**。

## 1. 现场数据存档 (只喊"已保存"等于没保存)
`data/` 在 `.gitignore` 里 ⇒ 手教点位 / 技能配方 / 注册表都是 runtime state, **不在版本库**。
- 拷进受版本管理的 `docs/data_snapshots/<日期>_<主题>/`: 点位库 · 技能注册表 · 审计流水 · 清除前原件 · 取证日志。
- 同目录写 `README.md`: 每个文件是什么 · 当天实测数字 · 根因 · 关联台账路径。
- 判据: `git ls-files docs/data_snapshots/<目录>` 能列出来才算真入库。

## 2. 五处版本号同步 (缺一处 `integrity_check` 就报不一致)
| 位置 | 字段 |
|---|---|
| `tools/gui/studio.py` | 品牌小字 + 两个窗口标题(共 3 处) |
| `tools/gui/update_checker.py` | `CURRENT_VERSION` |
| `tools/gui/version_sync.py` | `zmax_ver` |
| `tools/gui/docs_sync.py` | `version` + `zmax_version` |
| `tools/ci/integrity_check.py` | `EXPECTED_VERSION` |

替换用**精确字符串 + 断言命中次数**(锚点写错会连带改到历史注释, 也会漏掉同一版本号的多处)。

## 3. changelog 注释置顶
`studio.py` 版本注释块加一行 `# vX.Y.Z: 变更点1+变更点2`。
🔴 **行首必须有 `#`** —— 漏了就写成一条非法 Python; `integrity_check` 里的 `ast.parse(studio.py)` 会报
「完整性检查失败 (语法错误)」当场拦住(实测拦过一次, 否则直接进库)。

## 4. `VERSION.md` 版本历史表
该表**没有 `|---|` 分隔行** ⇒ 新行插在表头 `| 版本 | 日期 | 内容 |` 正下方。

## 5. 守卫 → 提交 → tag → 推 → 核远端
```bash
python3 tools/ci/integrity_check.py      # 五处一致
python3 tools/repo_guard.py              # 无权重/交付件/超限大文件
python3 tools/secret_scan.py             # 已跟踪文件的 token/key(命中退 1)
git commit -F /tmp/commit_msg.txt        # 长中文消息写文件, 别内联
git tag -a vX.Y.Z -m "..."
git push origin main && git push origin vX.Y.Z
git ls-remote origin refs/heads/main refs/tags/vX.Y.Z   # 核远端, 别只信 push 的输出
```

## 已知既有告警(提交前先确认是不是老问题)
- `secret_scan` 命中 3 个已跟踪文件里的 agent-hub token(`tools/publish_status.py` · `tools/ss3d_live_push.py`
  · `tools/web/ss3d_push.php`) ⇒ 公开仓库里**已进历史**; 处置 = 挪 `zmax_data/secrets/zmax.env` + 轮换 + 清历史。
- `repo_guard` 干净时输出「检查 已跟踪 N 个文件, 合计 ~47MB ✅ 干净」。
- 工作区必须 `git status --porcelain | wc -l` = 0 才算迭代收尾。
