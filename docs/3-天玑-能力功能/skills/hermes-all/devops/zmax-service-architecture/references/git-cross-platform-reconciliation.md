# 跨平台仓库对齐 (Windows 工作区 / Linux 索引)

## 症状

`git status` 报几千项：大量 `M`、大量 `D`、大量 `??`，看上去像"整个仓库被改过"。
多半是**平台噪音**，真实改动只占个位数。

## 判定顺序

### 1. 先关掉两个噪音源，再看还剩多少

```bash
git config core.autocrlf false
git config core.filemode false
```

- `filemode`：Linux 侧 100755，NTFS 不存执行位 ⇒ 纯噪音。量化方法：改之前后各跑一次
  `git status --porcelain | wc -l`，差值就是这一类。

### 2. `git diff -w` 与 `git diff` 数字相同 ≠ 没有换行差异

**这是最容易误判的一点。** `core.autocrlf=true` 在比较时就把 CRLF 归一化掉了，
**换行污染在 diff 里完全隐形** —— 两种 diff 都看不到它。

真正让它显形的是**逐文件 blob 哈希对比**：

```bash
git hash-object --no-filters <file>    # 工作区内容不做换行转换后的 sha
# 与索引里那一份比对
git rev-parse :<file>
```

相等 ⇒ 这个 `M` 纯换行，可以安全地就地转 LF（转换前先校验一遍，零内容风险）。

### 3. `mode 120000` 是符号链接

`git diff` 里出现 `index xxx..yyy 120000`，删除行是一条路径、新增行是大段代码 ⇒
Windows 把软链**物化成了实体文件副本**。

**这类改动绝不能提交**：会把 Linux 侧的软链变成实体文件，从此两边内容各自漂移。
处理：`git stash push -- <path>` 收起来，干完活再 `stash pop`。

**`git add -u` / `git add -A` 会连它们一起扫进去**，不是只有 `git add .` 有这个风险。
想只提交文档却顺手跑了 `git add -u`，就会把 12 个 symlink 物化悄悄带进 commit。
一律**显式列出路径** `git add <file1> <file2>`，提交前用
`git diff --cached --name-status | head` 确认没有 `M\tsrc/...` 这类不该出现的条目。

### 3b. 已经提交了怎么救

只要还没被别人拉走，用软回退重写这一条提交，不要反向提交留烂历史：

```bash
git reset --soft HEAD~1          # 改动全回暂存区, commit 消失
git restore --staged src/        # 把 symlink 物化撤出暂存区(仍在工作区, 不影响运行)
git diff --cached --name-status  # 确认只剩该提交的文件
git commit -m "..."
git push --force-with-lease origin main
```

`--force-with-lease` 而不是 `--force`：远端在此期间被别人推过就直接拒绝，不会覆盖掉别人的提交。

**推完必须验证软链没被隆级**：

```bash
git ls-tree origin/main src/lerobot/skills/muscle_memory.py
# 120000 blob ... = symlink 完好
# 100644 blob ... = 已被物化, 远端 Linux 侧已污染
```

### 4. 恢复被删的 tracked 文件

`git checkout -- <path>` 逐个恢复（可以批量），**不要 `git reset --hard`** ——
后者会连未提交的真实改动一起抹掉。

## pull / push

- `git pull --rebase` 在有未暂存改动时直接拒绝 ⇒ 先把噪音（symlink 物化）`stash` 掉。
- 未跟踪文件挡住远端新提交（`would be overwritten by checkout`）⇒ 备份后删除再 pull，
  pull 完把远端版本与本地备份比一遍，确认没丢掉本地独有的修改。
- **无人值守环境下 `git push` 会挂死**：Git Credential Manager 弹的是 GUI 对话框，
  没有桌面交互就一直等，`GIT_TERMINAL_PROMPT=0` 也拦不住它。
  要么配 SSH key / 带 token 的凭据，要么**交给共享盘另一侧去推**。
  报告时要说清"commit 已在本地、只差 push"，不要把没推上去说成已交付。

## 提交时排除什么

打包产物、运行期日志、机器相关的 `*.exe`、几十万文件的历史脚本目录
全部进 `.gitignore` —— 一次 `git add .` 会把几 GB 一起塞进去。
提交前用 `git diff --cached --name-only | wc -l` 看一眼规模是否符合预期。
