# D:\ZMAX Git 对齐报告

- 生成时间：2026-11-26
- 仓库：`D:\ZMAX`　remote：`https://github.com/MikeBMW/zmax.git`
- 分支：`main`　本地 HEAD：`11c142e4`　`origin/main`：`1e979b68`
- 本次只做本地整理：**未 commit、未 push、未 rebase/merge、未删除任何未跟踪文件**

---

## 一、结论（先看这里）

| 指标 | 整理前 | 整理后 |
|---|---|---|
| `git status` 总条目 | **9353** | **52** |
| `M` 修改 | 3474 | **20** |
| `D` 删除 | 622 | **0** |
| `??` 未跟踪 | 5257 | **32** |

- **3474 个 M 里没有一个是"真实业务改动"**，构成是：`816` 个纯权限位(100755→100644) + `2640` 个纯 CRLF/LF 换行差异 + `10` 个 symlink 被物化成实体文件 + `9` 个真实内容改动。
- **622 个 D 全部是"Windows 侧缺文件"而非有意删除**，已全部按路径逐个 `git checkout --` 恢复成功（0 失败）。
- `??` 从 5257 骤降到 32，是因为恢复了仓库根的 `.gitignore`（8782B），之前 5000 多个构建产物全在裸奔。
- **本地落后远端 5 个提交，且没有任何本地独有提交**（可 fast-forward，但按约束未执行）。

**回答"到底有多少 M 是换行差异"：2640 个（占 3474 的 76%）是纯 CRLF/LF 差异，另有 816 个（23%）是 Windows 丢失可执行位造成的假修改。真正的代码改动只有 9 个文件。**

---

## 二、诊断：三类状态各是什么性质

### 2.1 622 个 `D`（删除）——Windows 侧文件缺失，不是有意删除

典型条目：`.gitattributes` `.gitignore` `.dockerignore` `.github/workflows/build-win-exe.yml` `.claude/` `.hermes/` `.vscode/launch.json` `AGENTS.md` `CLAUDE.md` `CONTRIBUTING.md` …

判定依据：
1. 这些文件在索引/HEAD 里都在，且工作区确实不存在；
2. 恢复后 `git status` 从 9353 掉到 52，没有产生任何冲突或内容回退错误；
3. 删除集中在"仓库根配置 + 文档 + 测试资产"，是典型的 **Linux 侧提交、Windows 侧没同步过来**（压缩包解压/拷贝丢点文件、symlink 无法创建），而不是有人在 Windows 上手工删了 622 个文件。

其中 **19 个在索引里是 symlink（mode 120000）**，Windows 无法创建符号链接，因此：
- 工作区表现为"文件缺失"(D)，或"内容变成另一个文件"(M)；
- `CLAUDE.md`(9B)、`runs` 这类恢复后是**普通文本文件，内容为链接目标路径**，这是 Windows 正常行为，不是损坏。

### 2.2 3474 个 `M`（修改）——四层叠加，只有 9 个是真的

用"索引 blob 哈希 vs 工作区实际字节"逐个比对（`git cat-file -p` + 原始读取），结果：

| 类别 | 数量 | 证据 |
|---|---:|---|
| ① 纯权限位 `100755 -> 100644` | **816** | 索引里 946 个文件带可执行位；NTFS 不存 exec 位。把 `core.filemode` 设为 false 后 M 从 3474 直接掉到 2658，差值即此类 |
| ② 纯 CRLF/LF 差异 | **2640** | 工作区是 CRLF、索引是 LF；且把工作区 CRLF→LF 后与索引 blob **逐字节完全相等**（2640/2640 校验通过）。分布：`.py 2223`、`.sh 269`、`.service 50`、`.html 23`、`.json 20`、`.java 13`、`.md 11`、`.yaml 8` … |
| ③ symlink 被物化为实体文件 | **10** | 索引 mode `120000`、blob 只有 50~54 字节（就是目标路径），工作区却是 2.8K~55K 的真代码副本 |
| ④ 真实内容改动 | **9** | 归一化后仍与索引不同，见下表 |

合计 3475 ≈ 3474（个别文件同时属于 ①和②，取并集后为 3474）。

**根因（为什么会出现"两个版本"）：**
1. `core.autocrlf=true`：检出写 CRLF、入库转 LF。它在**比较时把 CRLF 归一化掉**，所以换行差异在 `git diff` 里"看不见"——`git diff --stat` 与 `git diff -w --stat` 数字完全一致（都是 1580），这正是换行污染被掩盖的典型症状。换句话说：**不是你 diff 不出来，是 autocrlf 让它隐形了**。
2. `.gitattributes` 里**没有 `* text=auto` 之类的换行声明**，只有 LFS 和 `*.json !text` 规则，等于把换行交给各平台默认行为各玩各的。
3. `core.filemode=true` 在 NTFS 上必然产生全仓假修改。
4. Ubuntu 侧提交时带上了 symlink 与 100755 权限位，Windows 侧无法还原，于是又变成一批 D/M。

### 2.3 5257 个 `??`（未跟踪）——绝大多数是构建产物

- 恢复 `.gitignore`（8782B，覆盖 `build/ dist/ node_modules/ .venv/ *.egg-info/` 等）后，`??` 从 5257 → **32**。
- 剩下 32 个是**真正的未跟踪产物**，全部原样保留、未删除、未 add：`launch_zmax.ps1`、`launch_zmax.vbs`、`Z-MAX_Console.exe`、`_internal/`、`_stubs/`、`_patches/`、`pkgtools/`、`server/`、`tools/gui/dist_nounpack/`、`tools/gui/build_nounpack/`、`*.bat` 启动器、若干探针脚本与 `.txt/.md` 日志。
- 其中 `launch_zmax.ps1`、`_internal/tools/cam_live_stream.py`、`_internal/tools/tcp_ar_server.py` **本来就没有被 git 跟踪**（从未提交过），所以任何 checkout/reset 都不会碰到它们。

---

## 三、实际执行的动作（可复核）

1. **备份（先备份后动手）**
   - `C:\Users\Admin\AppData\Local\hermes\cache\scratch\git_backup_list.txt`：622 个待恢复路径 + 9 个真实改动路径清单。
   - `...\scratch\git_keep\`：7 个已知有改动文件的 `cp -p` 原件（`launch_zmax.ps1`、`tools/tcp_ar_server.py`、`tools/cam_live_stream.py`、`tools/web/station.html`、`_internal/tools/cam_live_stream.py`、`_internal/tools/tcp_ar_server.py`、`tools/arm_pose_relay_intel.py`）。

2. **恢复 622 个 D**：对每个路径单独 `git checkout -- <path>`（**没有用 `git reset --hard`，也没有用 `git checkout -- .`**，避免冲掉 9 处真实改动）。结果：622/622 成功，0 失败。
   - 其中 50 个是 LFS 文件（`.safetensors/.png/.bag`），smudge 会卡在网络上，改用 `GIT_LFS_SKIP_SMUDGE=1` 恢复为指针文件（详见"遗留问题"）。

3. **配置修正（仅本地 `.git/config`，不影响 Ubuntu 的 clone）**
   ```
   git config core.filemode false     # NTFS 不存 exec 位，关掉权限位比较
   git config core.autocrlf false     # 不再做隐式 CRLF 转换, 换行交给 .gitattributes
   ```

4. **`.gitattributes` 增补换行策略**（保留原有 LFS 与 `*.json !text` 行，新段插在其**前面**，保证 LFS/`!text` 仍然优先）：
   ```
   * text=auto eol=lf
   *.py *.sh *.md *.html *.js *.ts *.css *.java *.yaml *.yml *.toml *.cfg
   *.ini *.service *.desktop *.timer   text eol=lf
   *.bat *.cmd *.ps1 *.vbs             text eol=crlf   # Windows 专属脚本保留 CRLF
   *.exe *.ico *.png *.jpg *.jpeg *.zip *.zst   binary
   ```

5. **把 2640 个 CRLF 文件就地转成 LF**：每个文件转换前的判据是"把 CRLF 换成 LF 后必须与索引 blob **逐字节相等**"，转换后再读回校验。2640/2640 通过、0 失败、0 跳过——**内容零风险**（转换后的字节就是仓库里已提交的那份字节）。
   > 没有用 `git add --renormalize .`：索引里本来就是 LF，renormalize 改不动索引，反而会把 9 处真实改动和 622 个恢复一起 stage 进暂存区，违背"不提交"的约束。

6. **`git update-index --refresh`** 刷新 stat 缓存（8-9 月遗留的假 mtime 差异一并清掉）。

7. **验证**：`HEAD` 仍是 `11c142e4`，`git diff --cached` 为空（暂存区干净，什么都没提交）。

---

## 四、整理后剩下的 20 个 M（都是"该留"的）

| 文件 | 行数 | 性质 |
|---|---|---|
| `src/lerobot/engineering/nodes/exec_dispatch_impl.py` | +57/-1 | symlink→实体副本 |
| `src/lerobot/engineering/nodes/geo_plan_impl.py` | +1000/-1 | symlink→实体副本 |
| `src/lerobot/engineering/nodes/plan_impl.py` | +801/-1 | symlink→实体副本 |
| `src/lerobot/middleware/nodes/impl/geo_plan_impl.py` | +1000/-1 | symlink→实体副本 |
| `src/lerobot/perception/yolo.py` | +238/-1 | symlink→实体副本 |
| `src/lerobot/policies/aoi/quality.py` | +228/-1 | symlink→实体副本 |
| `src/lerobot/policies/yolo_3d/frame_source.py` | +452/-1 | symlink→实体副本 |
| `src/lerobot/policies/yolo_3d/gen_tactile.py` | +92/-1 | symlink→实体副本 |
| `src/lerobot/policies/yolo_3d/yolo_state_aligner.py` | +440/-1 | symlink→实体副本 |
| `src/lerobot/skills/muscle_memory.py` | +223/-1 | symlink→实体副本 |
| `.gitattributes` | +37/-0 | **本次人为修改**（换行策略） |
| `src/lerobot/middleware/dds_hw.py` | +29/-0 | **真实改动**：给子进程统一加 `CREATE_NO_WINDOW`，修 Windows 闪黑窗 |
| `src/lerobot/ops/startup_probe.py` | +7/-0 | **真实改动**：Windows 下不再逐档写内存探测（启动 45s→） |
| `tools/cam_live_stream.py` | +90/-9 | **真实改动** |
| `tools/gui/studio.py` | +139/-2 | **真实改动** |
| `tools/tcp_ar_server.py` | +2/-1 | **真实改动** |
| `tools/web/station.html` | +2/-2 | **真实改动** |
| `tools/dashboard_server.py` | +422/-1 | **真实改动** |
| `tools/web/unified_app.html` | +137/-0 | **真实改动** |
| `defaults/config/eval/iteration_roadmap.json` | +680/-680 | **真实改动**：整文件重排/重格式化，需人工确认是否有意 |

`tools/cam_live_stream.py` / `tools/tcp_ar_server.py` / `tools/web/station.html` 已用 sha256 与 `scratch/git_keep/` 备份比对，**逐字节一致**，说明恢复过程没碰到它们。

---

## 五、与远端的关系

```
git fetch origin  ->  da21dc88..1e979b68  main -> origin/main
本地 HEAD         :  11c142e4
origin/main       :  1e979b68
origin/main..HEAD :  (空)      -> 本地没有任何未推送提交
HEAD..origin/main :  5 个提交  -> 本地落后 5 个
```

落后的 5 个提交（全部与本次改动无交集，只动 memory 文档 + 一个新脚本）：
- `1e979b68` sync: Hermes user 记忆同步 2026-11-26
- `e26210ef` sync: Hermes memory 记忆同步 2026-11-26
- `72480936` sync: Hermes memory 记忆同步 2026-11-25 (latest)
- `911d3404` sync: Hermes memory 记忆同步 2026-11-25 (daily)
- `da21dc88` feat(sync): Windows↔Ubuntu 双向同步渠道

`git merge-base --is-ancestor HEAD origin/main` 成立 → **纯粹落后，可直接 fast-forward，无冲突风险**（按约束未执行）。

---

## 六、遗留问题与建议

1. **LFS 对象在远端是 404，仓库本身就是坏的**
   `git lfs pull --include="tests/artifacts/**"` 返回大量 `Object does not exist on the server [404]`。即这 45 个 `.safetensors/.png/.bag` 的 LFS 实体**从来没被成功上传过**（或已被清理）。本地只能得到 131 字节的指针文件，这是**远端缺陷，本地无法修复**（修它必须 push LFS 对象，本次禁止）。→ 建议后续单独确认历史里这些对象是否还存在于任何地方，否则依赖 `tests/artifacts` 的测试在全新 clone 上必然失败。

2. **symlink 在 Windows 上永远是"差异"**
   索引里有 19 个 `120000` 条目，Windows 只能落成普通文件，因此这 10 个 M 会长期存在。三种处理方式（需你决定）：① 接受现状；② 开 Windows 开发者模式 + `git config core.symlinks true` 后重新 checkout；③ 把这些 symlink 改回实体文件并提交（会动到 Ubuntu 侧）。
   `CLAUDE.md`(9B)、`runs` 恢复成了内容为链接目标的普通文件，同理。

3. **9 处真实改动还在工作区、未提交**：其中 `defaults/config/eval/iteration_roadmap.json` 是整文件 +680/-680 重排，建议先人工确认是不是格式化工具误写，再决定是否提交。

4. **建议的下一步（均未执行）**
   - `git merge --ff-only origin/main` 追平远端（本地无独有提交，安全）；
   - 决定 9 处改动的去留后，再按主题分批提交；
   - 团队约定：**所有 clone 都设 `core.autocrlf=false` + `core.filemode=false`**，换行只由 `.gitattributes` 的 `eol=lf` 决定，这样 Ubuntu 和 Windows 工作区字节一致，"两个版本"问题从根上消失。
   - `core.autocrlf` 建议值：**`false`**（不是 `input`，也不是 `true`）。理由：本仓 `.gitattributes` 已显式声明 `eol=lf`，交给它统管即可；autocrlf 再插一手只会制造隐形差异。

---

## 七、回滚方式

- 恢复的文件：`git rm --cached` 不行，直接 `git checkout -- <path>` 可再次取回，或重新删除即可。
- 换行转换：2640 个文件转换后的字节 == 索引 blob，取回原始 CRLF 版本无意义；若确需回滚，`git checkout -- <path>` 得到的就是 LF 版本（即仓库版本）。
- 配置回滚：`git config core.autocrlf true`、`git config core.filemode true`。
- `.gitattributes`：`git checkout -- .gitattributes`。
- 备份原件仍在：`C:\Users\Admin\AppData\Local\hermes\cache\scratch\git_keep\`。
