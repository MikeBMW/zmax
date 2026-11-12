---
name: diverged-repo-push-discipline
description: "Use when git push 被拒/仓库被多台机或多个会话同时推, 或一棵工作树里混着两个任务的改动要分别提交。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [git, divergence, multi-writer, commit-scope, push]
    related_skills: [zmax-engineering-repo, github-repo-management, github-pr-workflow]
trigger: "Use when `git push` is rejected non-fast-forward, when the same repo is being pushed from several hosts or agent sessions, or when one working tree holds two unrelated tasks and each must land as its own commit."
---

# 多写者仓库的推送与提交纪律

## When to Use
- `git push` 被拒 (`non-fast-forward`), 或想确认当前能不能安全 rebase。
- 同一个仓被多台机 / 多个 agent 会话并行推 (常驻分歧: 本地未推 N 条 + 远端领先 M 条)。
- 一棵工作树里混着两个任务的改动, 要按任务分别提交 (另一个任务还在飞, 不能一起入库)。
- rebase 冲突后刚 `--abort`, 要确认提交与工作区都没丢。

同一仓库被多台机 / 多个会话并行推时, 常态是"本地未推 N 条 + 远端领先 M 条"。目标不是把它推上去,
而是**只把自己的任务干净落地**, 不把别人的半成品卷进来。

## 步骤

1. **先量分歧, 再动手**:
   ```bash
   git fetch origin
   git rev-list --left-right --count HEAD...origin/main   # 左=你未推, 右=远端领先
   git diff --name-only HEAD...origin/main                # 远端改了什么
   git log --oneline --name-only origin/main..HEAD         # 你自己未推的提交改了哪些文件
   ```
   要对**两个集合**求交集, 不是只看工作树:
   - 远端文件集 ∧ `git status --porcelain`(未提交) —— 有交集先手工处理那个文件。
   - 远端文件集 ∧ **你未推提交的文件集** —— 有交集 = rebase 时你的提交会重放到别人改过的同一文件上, **必冲突**。
   ⚠️ 只查第一个交集会误判"安全": 实测工作树里没有任何别人碰过的文件(patch-id 也对得上),
   但本地未推提交里有与远端同一域的文件, `pull --rebase` 照样在那边冲突 ⇒ 两个集合都空才叫安全。
2. 🔴 **工作树里有另一个任务的未提交改动时, 不做 `pull --rebase`** —— 带 `-c rebase.autoStash=true` 也一样:
   它会把**本地所有未推提交**一条条重放到远端头上, 一旦在无关文件上冲突, 两个任务就被卷成一团,
   而冲突文件根本不是你的。
3. **只提交本任务的文件**: `git add <域目录>/ <该节点文件>` 而不是 `git add -A`; 工作树里别的任务的改动留原处。
   提交信息用 `git commit -F <msgfile>` (中文 + 引号走 shell 内联必踩 `No such file or directory`)。
4. **提交后回读**: `git show --stat HEAD` + `git status --short` —— 确认文件数/清单正好是本任务那几个,
   未提交的那批仍在。
5. **两个交集都空 ⇒ 用 worktree + cherry-pick 只把自己的那条落到远端** (首选动作, 不是只报"未推"):
   ```bash
   git worktree add -q /tmp/push-<task> origin/main -b tmp-<task>
   cd /tmp/push-<task> && git cherry-pick <你的提交>
   python -m py_compile <改过的文件>              # 判据要在新基线上重跑一遍
   git push origin HEAD:main                        # 远端 ae65c995..5c844ad7 HEAD -> main
   ```
   收尾 (别留 worktree, 别留 ahead/behind):
   ```bash
   cd <repo> && git worktree remove /tmp/push-<task> --force && git branch -D tmp-<task>
   git fetch -q origin && git reset --hard -q origin/main
   ```
   🔴 `reset --hard` 前必须 `git diff --name-only HEAD origin/main` **只列出你那条提交的文件** —— 列出别的文件
   就说明本地还有远端没有的内容, 此时不许 reset (会丢失)。
   为什么用 worktree 而不是就地 rebase: ①**不动正在跑的常驻服务**读的那棵工作树 (现场常驻进程/引擎就从这里 import);
   ② cherry-pick 只重放一条, 不会把你其它未推提交一起卷进冲突。
   cherry-pick 冲突 ⇒ `cherry-pick --abort` + 回 6 如实报, 别手工解 (两个任务会混进一个提交)。
6. **落不了就如实报**: 「已本地提交 · 未推 · 分歧 N/M · rebase 在 <别人的文件> 冲突已 abort 复原」
   是合格交付。不要为了推上去 merge 别人的半成品, 也不要用 `--force`。

## 已 abort 的 rebase 怎么复原确认 (缺一步就可能丢工作)

```bash
git rebase --abort          # autostash 会把工作区改动恢复回来
printf 'Applied autostash'  # 出现这句才说明改动回来了
git log --oneline -2        # 自己的 commit 还在最上面
git status --short          # 未提交文件一个不少
```
然后**重跑一次能真跑的判据** (import / 单节点调用 / py_compile), 别只看 `git status` 干净就当没事 ——
rebase 期间文件被 checkout 过, 复原的是索引与工作区内容, 不是"你验过的那个状态"。

## 常见误判

| 现象 | 不是 | 而是 |
|---|---|---|
| `! [rejected] non-fast-forward` | 分支坏了 / 远端有恶意改动 | 远端有别人的新提交, 正常 |
| `pull --rebase` 冲突在你不认识的文件 | 你改错了 | 你的未推提交被重放到了别人的改动上 |
| `git status` 干净 | 可以推了 | 只说明没未提交改动, 分歧还在 |
| `ahead 5, behind 6` 且两边提交**提示文字一样** | 自己丢了两条提交 | 那几条已被别的机器/会话 rebase 过 (内容同、hash 不同) ⇒ **不要重放**, 只把真正新增的那一条 cherry-pick 上去 |
| `git diff --name-only HEAD origin/main` 只剩你改的文件 | 本地落后很多 | 恰是能安全 `reset --hard origin/main` 的证据 |
| 冲突后手工编辑解冲突 | 快 | 两个任务被混进一个提交, 下次 review 无法分离 |
