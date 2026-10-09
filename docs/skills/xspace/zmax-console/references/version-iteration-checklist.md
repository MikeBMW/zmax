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

## 5b. 一条龙工具 `tools/bump_version.py` (2026-10-09 实跑 v5.34.2 → v5.35.0)

```bash
python3 tools/bump_version.py --to 5.35.0 --summary-file /tmp/v53500_summary.md --dry   # 先看命中
python3 tools/bump_version.py --to 5.35.0 --summary-file /tmp/v53500_summary.md         # 真写
```
它把第 2 节五处 + `VERSION.md` 表首行一起改, 逐处报「旧命中/新命中」, 末尾 `py_compile` 校验。

🔴 **summary-file 必须是「台账单行」体, 不要写 markdown**: `# 标题` / `## 小节` / 换行会被原样塞进
`VERSION.md` 表格单元与 studio.py changelog 行 ⇒ 出现 `# v5.35.0: # v5.35.0 — … ## 一句话` 双前缀 +
裸井号。写法: `vX.Y.Z — 主题 (日期 老倪)  老倪: 「原话」  ① …② …③ …  实测: …`, 单行、无 `#`、无 `|`。
已插错就整行替换: 正则 `^\s*# v5\.X\.Y: .*$` → 干净行, 再 `py_compile` 复验。

## 5c. push zmax 的 ghproxy 变体 (skill 自带脚本写死了另一个仓库)
`scripts/push_via_ghproxy.sh` 里 `REPO`/`URL` 是 lerobot-smolvla-lew ⇒ 推 zmax 要改
`REPO=/home/ubuntu/zmax` + `URL=…/MikeBMW/zmax.git`, 且**推两样**: `HEAD:refs/heads/main` 与
`refs/tags/<tag>`(tag 才触发 `.github/workflows/build-win-exe.yml` → Windows exe + macOS zip → Release)。
成功判据只有 `ls-remote` 远端 SHA == 本地 HEAD。实测 ghproxy.net 一次过 (main+tag, 14 提交 ~20MB pack)。

**查发布状态 (gh CLI 未装)**: 用 `~/.git-credentials` 里的 token 直接打 API (token 不打印) ——
`api.github.com/repos/MikeBMW/zmax/actions/runs?per_page=6` 看 run status/conclusion,
`/releases/tags/vX.Y.Z` 看 assets 名与字节数。实测 api.github.com 直连可用, 只有 git push 需要 ghproxy。

## 5d. 🔴 解耦后的出包硬坑 (v5.35.0 首轮 CI 挂, 两轮才过 —— 实测)

**坑一: 真源不在仓库里 ⇒ 打出来的包没有画布**。解耦后 `src/lerobot/engineering/flows/state_space_obs.json`
是**软链→实例包**(data/ 被 gitignore); CI 上变成「文件不存在」⇒ `--add-data src/lerobot/engineering`
里没画布, 资产核验 `画布真源: 0` → `::error::` exit 1 (run 2 分钟就挂, 比正常构建快很多 = 早期步骤挂)。
修法（双管齐下, 两处都要）:
  ① `paths.canvas_json()` 加**出厂骨架回落**: 包内 → 根 `flows/` → `defaults/canvas/<name>` → 包内路径;
     且 `defaults/canvas/state_space_obs.json` 必须真实存在于仓库 (空骨架, 0 节点) ⇒ 全新安装/无实例也能起。
  ② 两个打包 job (Windows .exe / macOS .app) 在 PyInstaller **之前**加一步
     `mkdir -p src/lerobot/engineering/flows && cp -f defaults/canvas/state_space_obs.json src/lerobot/engineering/flows/`
     (让 --add-data 有真实文件可收)。

**坑二: Windows runner 的 stdout 是 cp1252 —— `python -c` 里打中文直接 `UnicodeEncodeError` 挂步骤**
(`codecs.charmap_encode ... can't encode characters in position 0-4`)。打包/校验步骤里的 python 打印
一律写成**纯 ASCII**(哪怕注释是中文, 注释不进 stdout); bash `echo` 打中文没问题 (Git bash 是 UTF-8)。

**验完再算完**: `api.github.com/repos/MikeBMW/zmax/releases/tags/vX.Y.Z` 看 assets, 再对每个 asset 发
**HEAD 请求**比 Content-Length 与声明字节数 (实测 170.7MB exe / 134.4MB zip, HTTP 200 且字节一致)。

## 5e. tag 已被推过但构建失败怎么重发
无产物 (Release 未生成) 时可以把 tag 重指到修复提交后重推: `ghproxy push :refs/tags/<tag>` 先删远端
→ `git tag -f <tag> HEAD` → `push --force refs/tags/<tag>` ⇒ **必须再 ls-remote 核 tag SHA == 本地 HEAD**
(踩过: 只 `push <url> HEAD:main refs/tags/t:refs/tags/t` 不带 `-f` 时 tag 会停在旧提交, 主分支却已前进)。

## 已知既有告警(提交前先确认是不是老问题)
- `secret_scan` 命中 3 个已跟踪文件里的 agent-hub token(`tools/publish_status.py` · `tools/ss3d_live_push.py`
  · `tools/web/ss3d_push.php`) ⇒ 公开仓库里**已进历史**; 处置 = 挪 `zmax_data/secrets/zmax.env` + 轮换 + 清历史。
- `repo_guard` 干净时输出「检查 已跟踪 N 个文件, 合计 ~47MB ✅ 干净」。
- 工作区必须 `git status --porcelain | wc -l` = 0 才算迭代收尾。
