# 版本迭代与发布 (bump → 判据 → tag/Release)

一次迭代的标准链路。**顺序不能换** —— 最后一步（技能+记忆同步）自带 commit+push，
技能/记忆的改动必须在它**之前**做完，否则会把旧版技能推上去。

## 1. 先写迭代摘要，再改版本号
摘要一行、项目体例：主题 + ① ② ③ …；每条带**实测数字 / 判据 / 回退开关**。
回退开关写成 `env` 变量名或 `--flag` 名字，别写“需要时改代码”。

## 2. bump
```bash
./gui-venv311/bin/python tools/bump_version.py --to <X.Y.Z> --summary-file <摘要文件>
```
同步 8 处（studio.py 三处显示位 · changelog 行 · update_checker · docs_sync · version_sync · integrity_check）
+ 往 `VERSION.md` 表首插一行，并打印逐项命中清单。**它只改盘，不 commit，也不保证改干净（见第 3 步）。**

## 3. 🔴 紧接着跑判据（这一步不能省）
```bash
./gui-venv311/bin/python tools/verify_version_sync.py
```
bump 工具的“其它显示位”扫不到**硬写字面量**：实测残留两处 —— 状态栏
`sb.showMessage("Z-MAX vX …")` 与「关于」框里的 `<b>Z-MAX vX</b>`，字面量可能比当前版号**还老几代**。
判据会点名：`❌ GUI 显示陈旧: studio.py:<行号> 字面量 vX (≠ vY)` ⇒ patch 那一行，再复跑。
版本号对用户只在**状态栏**与**关于框**两处可见，它们必须与 `VERSION.md` 表首一致，否则现场看到的永远是旧版号。

## 4. 判据对照表
| 判据行 | 含义 | 处置 |
|---|---|---|
| studio.py 各处命中数 / VERSION.md 新行 | bump 到位 | 命中为 0 ⇒ 匹配串与现场不一致，手工定位 |
| `GUI 显示陈旧: studio.py:<行> 字面量 vX` | 硬写字面量漏改 | patch 该行 → 复跑 |
| `远端缺少 tag vX` | 忘推 tag | `git push origin main --tags` |
| `最新 Release tag vX-1 ≠ vX` | CI 还没跑完 | 查 actions runs；在跑就等，**别手动建 Release** |

## 5. commit → tag → push（带 tags）
Release 不用手动建：tag 推上去后 CI（`.github/workflows/release.yml`，run 名 `Build Desktop (Windows .exe)`）
构建 Windows/macOS 包并发布 Release。核实用只读 API，不要凭猜：
```bash
curl -s "https://api.github.com/repos/MikeBMW/zmax/actions/runs?per_page=4"   # in_progress ⇒ 正常
curl -s https://api.github.com/repos/MikeBMW/zmax/releases/latest              # tag_name
```

## 6. 技能 + 记忆同步
`bash tools/sync_hermes_to_repo.sh`：技能全量镜像到 `docs/skills/hermes-all/`（另挑一份到 `docs/skills/xspace/`）、
记忆备份成 `docs/memory/hermes-jingjing-{memory,user}-<日期>.md` + `-latest.md`、更新 manifest，自带 commit + push。
> 若该脚本的 SKILL.md 侧记不在本技能，就只当作工作流参考；技能/记忆的改动务必在跑它之前完成。
