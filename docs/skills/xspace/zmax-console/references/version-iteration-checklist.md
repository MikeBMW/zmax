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

🔴 **summary-file 不要以版本号开头**: 写 `v5.50.73 — 主题…` 会让 changelog 行变成 `# v5.50.73: v5.50.73 — 主题…`、
`VERSION.md` 单元格变成 `| **v5.50.73** | 10-15 | v5.50.73 — 主题…|` (版本号出现两次)。写法: **直接从主题写起**
(`配置中心=北斗七星阵: …  老倪:「原话」  ① …② …`)。已重复就定点删开头那一段 + 回读两处。

## 5b-1. 版本号上限与升级节奏 (老倪 2026-10-15)
**最终极限版本 = v5.50.789** (第三段封顶 789) ⇒ 这是一条**有限跑道**: 小步升、不跳号、别一次吃掉几十号。
每次迭代只前进一位 (`5.50.72 → 5.50.73 → …`), 把号留给后续真改动; 不要为了“看着整齐”合并多件事去跳号。

## 5b-2. 🔴 bump_version.py 两个实测坑 (2026-10-14 实跑 v5.50.7 → v5.50.71)

* **`--to` 传不带 v 的号**: `--to 5.50.71` ✓; 传 `v5.50.71` 会生成 `vv5.50.71` (工具只在报告里显示
  `v5.50.7 → vv5.50.71`, 不会拦住)。
* **新号把旧号当子串时会重复追位**: 5.50.7 → 5.50.71 时, `studio.py` 的品牌 QLabel + **两处窗口标题**
  变成了 `v5.50.711` (状态栏/关于框却是对的) —— 根因是多趟替换里后一趟把已改好的文本再匹配一次。
  ⇒ **不能只看工具报的「✅ 旧命中 1 → 新命中 1」**(旧号是新号的子串时, 把 `5.50.711` 数成命中 1 也是对的)。
  必须**回读** `grep -n 新号 tools/gui/studio.py` 逐位看, 并 `grep -c '新号+额外字符'` (如 `5.50.711`) 应为 0;
  修法是定点把多余的位删掉再 `py_compile` + `checks/tools/ci/integrity_check.py`。
* 提交前顺手查 `git check-ignore -v <路径>` 是否命中忽略规则, 且过了 `repo_guard`:
  数据快照目录里拷进来的 `.db`/归档件 (二进制 >300KB) 会被拦 ⇒ 只留 sha256 清单 + 重建命令进 README。

## 5g. 🔴 发布前必查: 随包唯一依据必须有「出厂骨架 + 读侧回落」(2026-10-15 实捉)

平台/实例解耦后 **实例唯一依据 `config/**` 不进仓库** (data/ 被 gitignore) ⇒ 打出来的 Windows/macOS/Linux 包里
**没有产品档唯一依据** `config/platform/zmax_product.json` ⇒ 全新安装只能走"保障=调试档全开", 三档 550A/550B/550C
**选不出来** ("产品同步发布"就成了空话)。画布早就用同一套规矩 (defaults/canvas 骨架), 产品档当时漏了。

三处都要改, 少一处发出去就是残包:
  ① **出厂骨架** `defaults/config/platform/zmax_product.json` 进仓库 (三档 dev_profile 全带, active_product=550B);
  ② **读侧回落** (实例唯一依据 → 仓库 `defaults/` → 冻结包 `sys._MEIPASS/defaults/`): `tools/zmax_profile.py::product_json()`
     与 `tools/gui/studio.py::_product_json_path()` —— 缓存键要含**实际路径**, 否则回落结果被上一次的 mtime 锁住;
  ③ **打包 job** 两个平台都 `--add-data "$GITHUB_WORKSPACE/defaults:defaults"` (Windows 用 `;`), 并在打包前
     `python -c "...assert set(('550A','550B','550C'))<=set(d['products'])"` 自检。

判据 `tools/verify_product_release_factory.py` (20 条): 真回落验证 = **隔离目录只放 defaults、故意不建 config/**, 起子进程
读三档 (550A=on/core/dds · 550B=debug/all/dds · 550C=off/none/shm); 并核现场仍读实例唯一依据 (不被骨架顶掉)。

### 修完要重指 tag 时的顺序 (顺序错 = 旧产物覆盖新产物)

`upload-release-action` 是 `overwrite=true` ⇒ 旧 run 后跑完会**盖掉**新 run 的产物。
```bash
# ① 先取消在跑的 run (否则等它跑完再重指, 产物又变旧)
#    cancel: POST /repos/<org>/<repo>/actions/runs/<id>/cancel   (token 取 ~/.git-credentials 的冒号后段)
# ② 提交修复 → 推 main → 删远端 tag → git tag -f → 强推 tag (脚本 push_zmax_via_ghproxy.sh <tag> 就是这套)
# ③ ls-remote 核 tag SHA == 本地 HEAD, 再等新 run
```

## 5c. push zmax 的 ghproxy 变体 (skill 自带脚本预先固定了另一个仓库)
`scripts/push_via_ghproxy.sh` 里 `REPO`/`URL` 是 lerobot-smolvla-lew ⇒ 推 zmax 要改
`REPO=/home/ubuntu/zmax` + `URL=…/MikeBMW/zmax.git`, 且**推两样**: `HEAD:refs/heads/main` 与
`refs/tags/<tag>`(tag 才触发 `.github/workflows/build-win-exe.yml` → Windows exe + macOS zip → Release)。
成功判据只有 `ls-remote` 远端 SHA == 本地 HEAD。实测 ghproxy.net 一次过 (main+tag, 14 提交 ~20MB pack)。

**查发布状态 (gh CLI 未装)**: 用 `~/.git-credentials` 里的 token 直接打 API (token 不打印) ——
`api.github.com/repos/MikeBMW/zmax/actions/runs?per_page=6` 看 run status/conclusion,
`/releases/tags/vX.Y.Z` 看 assets 名与字节数。实测 api.github.com 直连可用, 只有 git push 需要 ghproxy。

## 5d. 🔴 解耦后的出包硬坑 (v5.35.0 首轮 CI 挂, 两轮才过 —— 实测)

**坑一: 唯一依据不在仓库里 ⇒ 打出来的包没有画布**。解耦后 `src/lerobot/engineering/flows/state_space_obs.json`
是**软链→实例包**(data/ 被 gitignore); CI 上变成「文件不存在」⇒ `--add-data src/lerobot/engineering`
里没画布, 资产核验 `画布唯一依据: 0` → `::error::` exit 1 (run 2 分钟就挂, 比正常构建快很多 = 早期步骤挂)。
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

## 5f. 快照图/大文件: 不入库, 只留可重生成的清单 (2026-10-15)
`docs/data_snapshots/**/*.png` 已在 `.gitignore` (以前只挡 `**/evidence/*.png`, 漏得很多 ⇒ 13 张 1MB 图进过库)。
往快照目录拷图**不要用 `git add -f`**: 图留在原地 (本机路径可直接看/发给老倪), 入库只入清单 ——
`./gui-venv311/bin/python tools/snapshot_media_index.py --write` 重生 `docs/data_snapshots/MEDIA-INDEX.md`
(名字 + 字节 + sha256前16, 从**工作区**扫 —— 不是 `git ls-files`, 因为那些文件已不入库)。
工程库快照 `zmax_engineering.db` 同理: 不入库, 清单里记 sha256 + 重建命令 (`tools/zmax_engineering_db.py build`)。

## 已知既有告警(提交前先确认是不是老问题)
- 🔴 **`repo_guard` 曾对中文文件名静默跳过 (2026-10-15 实捉)**: `tracked()` 原来用 `git ls-files` + `splitlines()`,
  git 默认 `core.quotepath=true` 把中文名转义成 `"…/real_1_\345\244\251…"` ⇒ `os.path.getsize()` 抛 OSError 被 `continue`
  ⇒ **中文名的大文件一个都查不到** (当时实际躺着 13 张 1MB 图 + 7 个工程库 .db, 它只报了 3 个 ASCII 名的)。
  已修: `git -c core.quotepath=false ls-files -z` + 按 NUL 切。**判据: 修后计数应当变多**(实测 3 → 13+7);
  若某次又只报几个 ASCII 名, 先查这条是不是被改回去了。看大文件别用 `for f in $(git ls-files)`, 中文名会断词。
- `secret_scan` 命中 3 个已跟踪文件里的 agent-hub token(`tools/publish_status.py` · `tools/ss3d_live_push.py`
  · `tools/web/ss3d_push.php`) ⇒ 公开仓库里**已进历史**; 处置 = 挪 `zmax_data/secrets/zmax.env` + 轮换 + 清历史。
- `repo_guard` 干净时输出「检查 已跟踪 N 个文件, 合计 ~47MB ✅ 干净」。
- 工作区必须 `git status --porcelain | wc -l` = 0 才算迭代收尾。
