---
name: git-push-via-host-api
description: "Use when git push 超时或被墙, 改用托管 REST 接口落地提交。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [git, github, network, fallback, rest]
---

# git push 不通时: 用托管平台 REST 数据接口落地同一份内容

## When to Use
- `git push` 反复 `GnuTLS recv error (-110)` / 挂到超时, 重试 5 次仍然失败。
- 但 `curl -o /dev/null -w '%{http_code}' https://api.github.com` 回 200 ⇒ **只有 git 走的那条 443 断了, 仓库 API 是好的**。
- 不是环境配置问题 (凭据在、remote 对); 是链路问题, 所以重试和后台死等都不值得。

## 先分诊 (三行, 别猜)
```bash
curl -s -o /dev/null -w 'github %{http_code} %{time_total}s\n' --max-time 12 https://github.com
curl -s -o /dev/null -w 'api    %{http_code} %{time_total}s\n' --max-time 12 https://api.github.com
git remote -v
```
- github.com 超时 / 000 + api 200 ⇒ 走本文方案。
- 两个都挂 ⇒ 别动, 报告网络原因。
- 想用 SSH 绕开: 先 `ssh -T git@github.com` 看有没有 key; 没 key 就不是可选项。

## 落地步骤 (GitHub 数据接口, 一笔提交写多个文件)

Token 从 `~/.git-credentials` 里读 (`https://<user>:<token>@github.com`), **不打印、不进对话、不写进命令历史**。

1. `GET /repos/<o>/<r>/git/ref/heads/main` → `base`; `GET /git/commits/<base>` → `base_tree`。
2. 逐文件 `POST /git/blobs {content: b64, encoding: "base64"}` → 取 blob sha。
3. `POST /git/trees {base_tree, tree: [{path, mode: "100644", type: "blob", sha}]}`。
4. `POST /git/commits {message, tree, parents: [base]}` → `PATCH /git/refs/heads/main {sha, force: false}`。

坑:
- **非 ASCII 路径必须 `-c core.quotepath=false`**: 中文文件名默认被转义成 `\345\244...` 形式, `git cat-file blob HEAD:<转义名>` 直接 exit 128. 改在 subprocess 调用里写 `["git","-C",root,"-c","core.quotepath=false", …]`, 比 ``git config`` 全局改更安全.
- **别整仓上传, 只推差异**: `git diff --name-status --no-renames origin/main HEAD` 拿净变更(实测 15 笔提交只 42 个文件, 最大 418KB), 42 个 blob + 一次 `base_tree` tree 十几秒完成; 有 `D` 条目时才补 `sha: null`, 只有 A/M 时不用.
  **必须带 `--no-renames`**: 默认开启重命名检测, 条目变成 `R100\t旧路径\t新路径` 三个字段, `st, path = line.split('\t', 1)` 直接搬到新路径名上、旧路径永远删不掉. 加了之后 rename 自动拆成一条 `D` + 一条 `A`, 建 tree 时才干净 (改标题/改目录名时必碰).
- **删条目的验证**: `D` 文件推完后 `GET /repos/<o>/<r>/contents/<path>?ref=<新 sha>` 应回 404 才算删掉; 只比对 A/M 的 sha 会漏掉「旧文件还在」.
  `/contents/<path>` 里的非 ASCII 路径要 `urllib.parse.quote(path)`, 不编码会 404 —— 这与 git 侧 `core.quotepath=false` 是两件事, 少一个就出现「本地对、远端查不到」.
- **提交信息从本地取, 不重写**: `git log -1 --format=%B` 直接当 `POST /git/commits` 的 `message`, 别在脚本里另写一段 —— 两边信息不一致时以后查历史会分裂.
- **验证哈希用 `git rev-parse HEAD:<path>`**, 不是 `git hash-object HEAD:<path>`(后者 exit 128, 会让整个脚本在"上传已完成"之后崩掉, 看着像没成功). 远端 `sha`+`size` 双对齐才算过(实测 42/42).
- **删除条目只在远端真有该路径时写** (`sha: null`)。本地 `git mv` 过但从未推上去的文件远端不存在 ⇒ 再加一条删除就 **422**。
- 大文件 (1MB+ 的源文件) 一次 base64 没问题; 但**整个递归 tree 可能几 MB 而且会读不全** ⇒ 校验时逐个 `GET /contents/<path>?ref=<sha>`,
  别用 `?recursive=1` (实测会 `IncompleteRead`)。
- 🔴 **先在本地 `git commit`, 再取 `HEAD:<path>` 的 blob**。这条路推的是**提交里的内容**, 不是工作区文件;
  工作区改了没提交 ⇒ 推上去的是旧版, 而每一步都返回 200、哈希校验还"对"(对的是旧 sha) ⇒ 以为成功、实际线上没改。
  **早期识别信号: 本轮建出的 blob sha 与上一轮完全相同** ⇒ 十有八九是内容没变/没提交, 先 `git status -s` 看不是干净的再说。
  收尾必做: `git status -s` 干净 + 每个文件 `远端 contents.sha == git rev-parse HEAD:<path>` 双对。
- 🔴 **被 .gitignore 命中的文件要 `git add -f`**: 工作流的 `.github/workflows/*.yml` 常被仓库 ignore ⇒ `git add <path>`
  静默跳过、`git commit` 也不报错, 你以为改了推上去了其实一行没变. 收尾用 `git show --stat HEAD` 确认**那个文件在提交里**;
  推送后 `GET /git/ref/heads/<branch>` 核对 sha 真的动了.
- 🔴 **本地分支落后远端时, 父提交用远端 sha, 但只把"内容真由本次改动决定"的文件写进 tree**: 每个要推的文件先比
  `git rev-parse HEAD:<path>` 与远端该路径的 blob sha, 两者不等(远端已被别处推过)就别拿本地那份覆盖 ——
  `base_tree` 只保证"没列出的文件保持原样", 保不住"列出来的文件被旧内容盖掉"。
  典型场景: 本机不是唯一写者(另一台机器/另一个会话刚推过 sync 提交), 本地 HEAD 落后一两笔而你要发一个版本。
- 🔴 **每一轮 API 推送都要重新 `GET /git/ref/heads/<branch>` 取 base, 绝不拿本地 `origin/main` 当 base**:
  push 不通时本地 remote-tracking ref 永远停在旧 sha, 第二次推送时它已落后于远端 ⇒ 拿它当 `base_tree`
  会把上一轮刚推的内容**静默回退**, 而每一步都返 200。多笔本地提交一次补齐时, 差异取 `HEAD~N..HEAD`,
  message 取 `git log -N --format=%B`(拼接), 不要只取最后一笔。
- 推完要触发 CI 时: `POST /actions/workflows/<w>.yml/dispatches` 带上 `{"ref":"main","inputs":{...}}`(**不能只传 ref**,
  否则输入走默认值, 典型后果是版本串变成非语义版本、构建在前几步就死), 再读该次 run 的 **`head_sha` 与刚推的 sha 对齐**
  —— 只看“有 run 在跑”可能跑的是上一笔提交.
- **发版走 tag 时, 建 tag ref 本身就是一次 push**: `POST /git/refs {"ref":"refs/tags/vX.Y.Z","sha":"<commit>"}`
  会触发 `on: push: tags: v*` 的发布流水线(要 annotated tag 就先 `POST /git/tags` 再拿它的 sha 建 ref)。
  回读新 run 的 `head_sha` 必须等于这个 commit —— tag ref 建错对象, 打出来的是旧代码的包而版本号是新的。
- **构建失败且 Release 还没产生资产时, 重打同一个 tag 是干净的**: `DELETE /git/refs/tags/vX.Y.Z` → 修完代码
  (例如 workflow 自身的 bug)后对新提交再 `POST` 同一个 ref ⇒ 等价 `git push -f` 该 tag, 会再触发一次构建。
  **一旦该 tag 已有 Release 资产就绝不重指**(下载链接会失去意义), 改递增新号。
- **推了新提交就先把上一笔的构建取消掉**: 上一笔 run 还在 queued/in_progress 时直接 dispatch, 两个构建并行,
  先完成的那份产物是**旧代码**, 而你会拿它的产物去交付。定式: `GET /actions/runs?per_page=3` 取 status ∈
  (queued,in_progress) 的 run → `POST /actions/runs/<id>/cancel` → 再 dispatch → 回读新 run 的 `head_sha` 等于刚推的 sha。
- 请求要带 `Authorization: token <t>`、`Accept: application/vnd.github+json`、`User-Agent`, 并对 5xx/断链做 3~4 次重试.

## 验收 (必须逐文件对哈希)
```bash
# 逐个比对: 远端 contents 的 sha == 本地 git hash-object
```
字节数也要对一遍。只看 `HTTP 200` / `PATCH 成功` 不算 —— 那只能证明接口接受了请求。

## 必须告诉用户的副作用
- 远端得到的是一笔**新 sha 的提交**; 本地那几笔 commit 内容相同但历史不同 ⇒ 链路恢复后第一次 `git push` 会
  **non-fast-forward**, 需 `git fetch && git rebase origin/main` (内容已存在, 空改动会自动丢弃)。恢复前 fetch 也走
  github.com, 所以当场做不了。
- 🔴 **推完后本地 `git status` 会一直显示 `ahead N`, 到链路恢复并 fetch 为止** —— 那不是"没推上去":
  API 造出的提交是**另一个 sha**, 本地 remote-tracking ref 无从更新。收工/关机清单要写成
  "本地 `<sha>` / 远端 `<sha>`, 逐文件哈希 N/N 对齐 (origin ref 因 443 断未更新, 故 status 显示 ahead N)",
  并且**不要为了消掉 ahead 去 `git reset` 或 `git push -f`** —— 那会把远端那笔提交连同别人后来的提交一起冲掉。
- `git ls-remote` **不能用来判网络**: 超时后管道里 `cut`/`tail` 的退出码仍是 0, 看起来像成功。
  判网络一律 `curl -o /dev/null -w '%{http_code}'`; 判推送成功一律看回读哈希。
