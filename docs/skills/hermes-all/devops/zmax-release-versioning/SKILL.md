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
   🔴 **改号前先读仓里的"实际当前版本", 不信记忆/上一份报告里的号**: 并行 session 会把号往前推
   (实测记忆里记 5.50.753 而仓里 HEAD 已是 5.50.756)。`head -30 VERSION.md` + `grep -rn '5\.50\.\d{3}' tools/gui/studio.py | head -3`
   先定基线, 再 `bump_version.py --to <用户给的目标号>`。**用户给的目标号与当前号之间的号不补、不改** ——
   `bump_version.py` 会打印 `旧号 → 新号` 两行, 对不上就是基线读错了。
2. **数据不靠 commit 保存。** `zmax_data/` 在 `.gitignore` 里 ⇒ 「保存数据」= **归档目录 + 清单 + sha256**,
   不是 `git add zmax_data`(会 fatal 或静默不入库)。
3. **commit 与 tag 是两条推送。** `git push origin HEAD` **不会**带上 tag ⇒ 必须再 `git push origin vX.Y.Z`,
   并回读**精确 ref**: `git ls-remote --tags origin 'refs/tags/vX.Y.Z*'`。
   别用 `'vX.Y.*'` 加 `| tail` 验收: ls-remote 输出按**字典序**排, `v5.50.746` 排在 `v5.50.78`/`v5.50.79` 之前,
   tail 只看得到别人的 tag ⇒ 会误判"没推上去"、白推一遍。
4. **`config/` 是软链, 不进 git。** `config -> data/database/zmax/sources/config`, 本轮改过的标定/权重 json
   (`config/calib/*.json`) 必须显式 `cp` 进归档 `data/` —— 否则"保存数据"恰好漏掉唯一的参数真源。
5. **证据只写数字。** 归档里的 evidence 放实测值(延迟/幅度/前后对照), 不写过程叙述。
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

- 🔴 **改号前先给每一处命中定性；全仓 `replace_all` 会改坏基线**。全仓 grep `5.50.7x` 实测命中四类，**只有第一类该改**:
  ① **当前版本号（改）**: `studio.py` 三处显示(QLabel / 状态栏 showMessage / 关于框 HTML) ·
     `update_checker.CURRENT_VERSION` · `version_sync.zmax_ver` · `ci/integrity_check.EXPECTED_VERSION` ·
     `src/lerobot/ops/docs_sync.py` 两键(version / zmax_version) · 归档与 savepoint 脚本里回显的号 ·
     VERSION.md **新增**一行 · `studio.py` changelog **追加**一行。
  ② **基线产品版本（绝不改）**: 评估分析页「有性能提升才准升级」对标用的那个基线版本号。改了等于把标尺一起挪走，
     之后所有「有提升/零回退」的结论都失效。
  ③ **历史 changelog 与 VERSION.md 旧行（不该改）**: 改了历史就失真，下一版读的人无法回溯根因。
  ④ **注释里的占位写法（别误判）**: 形如 `"Z-MAX v5.50.73x"` 讲的是像素宽度一类的占位符，不是版本号。
  ⇒ 一律 `grep -n` 逐条看上下文再改，改完把四类命中各举一例回读。
- **自检正则要锚够宽**: 用 `5\.50\.\d+` 自查会把 `5.50.73x` 和基线 `5.50.735` 一起抓出来报不一致（假红）⇒
  正则钉到 `5\.50\.\d{3}`，并显式排除基线与历史行；否则你会去「修」一个本来就对的地方。
- **`setWindowTitle` 没有硬编码版本**: 它走 `_console_title(<product>)` 动态拼。动手前先看目标处是不是变量拼接，
  别照着旧版本文档里的「两处」去找一个不存在的硬编码。

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

- **远端在役代码先 `scp` 到 staging 目录, 归档脚本只从 staging 拷** —— 脚本里不嵌 `ssh`（嵌了就没法重跑、
  也没法在远端掉线时看出缺件）。staging 用 `~/.hermes/cache/scratch/rel<ver>/{orin,intel}/`。
- 🔴 **`scp` 一次传多个文件会部分失败而不报错**: 必须 `ls` 回读 staging 清单, 逐个对名字。
  实测漏了一个 `traj_*.json`（清单里只剩 4 个而非 5 个）, 不核对就会把"轨迹文件"这一项静默丢出归档。
- **归档文件数上千是正常的**: `data/config` 全量拷贝（calib + platform）单项就有 700 余个文件、5 MB。
  看到 700+ 文件不要以为拷错了, 按目录 `find | wc -l` 分组报一次即可。

### ③ 提交与推送

```bash
git add VERSION.md tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py \
        src/lerobot/ops/docs_sync.py tools/ci/integrity_check.py tools/archive_release_<ver>.sh
git commit -m "vX.Y.Z: <一句话主题>"
git tag vX.Y.Z
git push origin HEAD && git push origin vX.Y.Z
git ls-remote --tags origin 'refs/tags/vX.Y.Z*'   # 回读: 新 tag 在不在这边 (别用 'vX.Y.*' + tail)
```

- **推完要等 CI 真出包再回话**: 一个 `Build Desktop` workflow 里带 Windows + macOS **两个 job** ⇒
  轮询只看那个 run 的 `status/conclusion`，不要要求"至少两个 run"（会等不到而白转）；
  两个 job 都 success 后 `GET /releases/tags/vX.Y.Z` 回读**资产名/体积/state=uploaded**，才把下载链接给他。
- **没有 `gh` 也能查 CI**: token 从 git 凭据库取, 走 REST（不要因为 `gh: command not found` 就说无法查）:
  ```bash
  TOK=$(printf "protocol=https\nhost=github.com\nusername=<user>\n\n" | git credential fill 2>/dev/null | grep '^password=' | cut -d= -f2)
  curl -s -H "Authorization: Bearer $TOK" "https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=3"
  curl -s -H "Authorization: Bearer $TOK" ".../actions/runs/<run_id>/jobs"          # 逐 job 的 status/conclusion
  curl -s -H "Authorization: Bearer $TOK" ".../releases/tags/<tag>"                 # assets[].name/size/state
  ```
- 🔴 **轮询不要用长 `sleep` 堵在前台**: 前台默认 180s 上限, `sleep 240` 会被直接杀掉报 `exit 124`
  （看着像 CI 挂了或命令出错）。写成轮询脚本用 `background=true, notify=true` 跑（每 30s 查一次、
  `conclusion` 一到就打印两个 job + release 资产），自己继续做别的。
- **界面上的版本号不会自己变**: 控制台进程是用旧源码起的 ⇒ 改完号必须清实例、单实例重起，
  然后截图 OCR 回读新号（源码 grep 只证明文件改了，不能证明他看到的变了）。
- 🔴 **tag 之后又发生新改动（服务端页面 / unit / 工具）**：另起一个普通 commit 直接 push，
  **不补 tag、不自己升版本号**（版本号只用用户给的那个）。汇报时必须把“改动的性质”点明：
  这类改动是**服务端热读/不掉进安装包**的，所以那个 tag 出的 Windows/macOS 包里没有它也不冲突；
  否则用户下一句必然是“那我下的包到底是不是最新的”。

### ④ 收工 / 关机前 (没给版本号也照样要"保存数据")

「保存数据, 准备关机」不是一句安慰话 —— 按顺序跑完这五步再回话:

1. **代码**: 只 `git add` 本轮真改过的源码 (新 tools/ 子目录、判据、gui 文件), **不 add** 一次性的
   `*_tmp.py` / probe 脚本; 然后 `git commit` + `git push origin HEAD`, 回读新 commit sha 再报。
   🔴 **先确认这段时间有没有别人在同一个仓提交**: `git log --graph --oneline -12` + `git status -sb`。
   收工时 `HEAD` 顶上常挂着**不是自己写的**提交(并行 session / cron agent 在同一仓干活, 实测几小时里插进来十来条),
   而 `git status` 干净只说明"没有未提交改动", **不代表只有我在动这个仓**。两件事必做:
   ① 本地领先远端(`## main...origin/main [ahead N]`)的提交要 push, 别让工作留在本机等关机;
   ② 报告里点名"这几条不是我提的 + 它们做了什么", 不揽功, 也不要把别人没做完的改动当已完成汇报。
2. **状态快照** (这才是数据): 进 `data/database/zmax/archive/state_<date>_preoff/` 拷 `sources/config` 全量、
   `zmax_engineering.db`、`zmax_space.proj`、`config_meta.json`, 再拷一份 `/etc/systemd/system/zmax-*.service`
   + `~/.config/systemd/user/zmax-*.service` (下次重建环境靠它); 最后 `tar czf archive/zmax_state_<ts>.tar.gz`,
   报出 tar 体积与文件数。
   - **场景/画布数据别手搓打包**: 有现成 `./gui-venv311/bin/python tools/scene_data_snapshot.py` ——
     一步出 `zmax_data/snapshots/scene_<ts>.tar.gz` + 同目录 `MANIFEST_<ts>.json`(逐文件 sha256 前 16 位),
     末尾自带 `--verify` 自校验; 收尾再跑一次 `--verify` 把 sha 报给用户(实测 49 文件 / sha[:16])。
   - **权重与模型产物清单按 `zmax_data/models/` 找, 不是 `outputs/`**: 训练产物落在 `zmax_data/models/<name>_<ts>/`
     (如 `l5_vlm_lora_<ts>/adapter_model.safetensors`), `find outputs` 会得 0 条然后误报"今天没产出权重"。
     清单写 `路径 | 字节 | mtime`, 大件不拷。
   - **归档里要引用的远端产物先探活**: 另一台机器(如 intel)上的质量 json / 地图 png 先 `ping`+`ssh` 一次再 `scp`;
     对端已掉线就把该项标成"在远端磁盘, 未取回", **绝不静默略过** —— 否则清单看起来齐全, 实际少件。
3. **工程库重建并核对**: `./gui-venv311/bin/python tools/engineering_db.py build` 然后 `... check`,
   必须看到"判据全绿"。改了 config/产品真源不重建 = 下次 check 报漂移。
4. **开机自启清单**: 逐个 `systemctl is-active/is-enabled` (含 `systemctl --user` 的 GUI 服务),
   把 enabled 的服务列给他 —— 并且要真的 **enabled**, 本次手工 `setsid nohup` 起的服务要补 unit
   (否则重启就没了, 而他会以为还在)。
   🔴 **`is-enabled` 不是二值: `static` / `indirect` / `disabled` 都等于“开机不会起”** —— 那份清单里
   `active` 但 `static` 的 (无 `[Install]` 段) 当时在跑只是被人/`systemctl start` 拉起来的, 必须归到
   "开机后手动跑" 那一类; 权威名单用 `systemctl list-unit-files --state=enabled --no-legend '<前缀>*'`。
   **`oneshot` 单元完成后 `is-active` 回 `inactive` 是正常态**, 不是挂了 —— 报之前先看 `Type=`;
   把它当异常会让用户开机后看到 inactive 又白查一轮。
5. **关机影响面必须先讲**: 哪些公网/远程链路跑在这台机器上 (隧道、反代、docker 里的 ROS 节点),
   一关机就死; 哪些在别的机器上, 不受影响。让他出门前就知道了, 不要等他到了现场才发现 502。
   顺带报**本机哪些服务一关就没人顶**: 消息通道/网关、各 87xx 页面与推流、FIFO 执行器 daemon ——
   这几项列清楚比一句“服务会停”有用得多。
6. **把"开机后必须手动跑一次"的东西单独列出来**, 别混进 enabled 服务清单里：
   本仓 `tools/boot_restore.sh` **没有开机自启**(不在 systemd unit、也不在 crontab) —— 它才是补起
   l5_live_mark / vl_safety_monitor / 深度源 / 实时标注器的入口 ⇒ 台账上写一句「重启后手动
   `bash tools/boot_restore.sh local`」, 否则用户开机看到图不刷新、标注不动。
   验收口径: `systemctl is-enabled` 的那批会自己起, `boot_restore` 那批不会 —— 两类分开写。
7. **已知在崩的东西先定性, 并说清它重启后依旧会崩**（实测两容器 `RuntimeError: network: network connection`
   = 本机没接产线网、连不上机器人控制器）⇒ 否则开机后他一眼看到 `Restarting` 就当成新故障又查一轮。
   同时点名**另一台机器上没在跑的节点**(如 Orin 的取流节点)不会因本机重启而回来。

### ⑤ 「同步 550 ABC」= 两端逐字节对齐，方向靠 sha + diff 判

“同步”不是无脑把仓库推到机器上：**两边的副本可能各自更新**，推错方向就把对方的新功能盖掉。
实测一对反向的：仓库的 `tools/edge/edge_service.py` 比 intel 旧（intel 有 `/models` 的 `sha16/bin_mb/mtime`）⇒ 该**拉回仓库**；
而仓库的 `tools/zmax_profile.py` 比 intel 新（`hardware_ok` + 550C 判据）⇒ 该**推到 intel**。

固定流程（每个共享文件都跑）:
1. 两侧 `sha256sum` 前 16 位对齐 → 相等就结束，不要动。
2. 不等就**抓回远端那一份，双向 diff**（`diff <(git show HEAD:path) /tmp/remote_copy`），
   看清哪边是哪边的超集再决定 `cp` 方向 —— 别凭“仓库一定是最新”直接覆盖。
3. 同步后回读两侧 sha 作证据，再跑档位门：本机 `tools/verify_product_dev_profiles.py`；
   intel 侧 `zmax_profile.product()/hardware()/host_hardware()/hardware_ok()` 应得 `550C / intel / intel / True`。
4. 产品真源三份都要在：`config/platform/zmax_product.json`（软链真源）、`defaults/config/platform/...`、
   `/home/intel/zmax/config/platform/...`；只改一处就会出现“界面报 550C、机器按旧档跑”。

隧道不稳时不要下结论“机器挂了”: `sshpass ... -J <jump> ssh -o ConnectTimeout=25` 报
`Connection timed out during banner exchange` 就加重试（2~3 次、间隔 3 s）—— 实测第二次同一条命令就通了。

### ⑥ 同步飞书 (成果外发) · 发之前先看有没有发过

```bash
cd ~/zmax && ./gui-venv311/bin/python tools/feishu_send.py --text "【标题】日期 …"
./gui-venv311/bin/python tools/feishu_check_messages.py --n 3      # 回读
```
- 通道自带换 token (不走 gateway 缓存), 凭据读 `~/.hermes/.env` 的 `FEISHU_APP_ID/SECRET`; 默认会话 = `DEFAULT_CHAT` (dataworld/静界 报告群)。
  仓里只有**这一个** `oc_` id ⇒ 要发别处必须用户给 `oc_`, 不要猜。
- 🔴 **200 + message_id 不是送达证据**: 必须 `feishu_check_messages.py --n 3` 回读到正文开头 + `deleted: false` + 时间,
  报告里报 message_id 与回读时间两件。
- 🔴 **同一份成果只发一次**: 用户再说一句「同步飞书」时, **先回读** —— 看到同标题已在 X 时间送达, 就回答已在,
  不要盲发第二遍(群里会出现两条一样的, 他天天在看)。只有他明确说"重发"才再发, 并在回复里点名"现在两条了, 要不要撤回早的"。
- 消息结构固定四段: **已保存(commit sha + 产物/证据路径) → 本轮成果(实测数字, 一条一个数) → 就绪判定 → 提醒**, 末尾加一句边界
  (如「全程零真机指令」)。不写排查过程, 不复述对话。
- 发之前先自查每个数字的出处: 报告里的 commit sha/文件体积/目录是否存在, 用 `git log --oneline -3`、`ls -l` 校一遍再发 ——
  并行 session 会把 HEAD 往前推, 拿记忆里的号写进群就是假汇报。

## 改完号的判据：只认「五处一致」，不认 integrity_check 全绿

`tools/ci/integrity_check.py` 里那条 **"stack addWidget 顺序不一致"** 是长期假红：
页面改成懒加载后，AST 在 `__init__` 里取不到 `self.stack.addWidget(<PageClass>)`
（实参是 `_ph` 占位 widget），实测 **v5.50.752 / HEAD 都是"实际前11个 []"，命中 0**。
⇒ 发版前不要因为它整份脚本 ❌ 就以为版本号没改对；版本可用性看这六个数全部等于新号：
`studio.py`(QLabel/状态栏/关于框/changelog 共 4 处) · `update_checker.CURRENT_VERSION` · `version_sync.zmax_ver` ·
`docs_sync` 两键 · `integrity_check.EXPECTED_VERSION` · `VERSION.md` 新增行。
要真修就改检查器（按 `self.modules` 字典 + `_lazy()` 闭包里的 `addWidget(_ph)` 重建顺序），别去"修"源码。

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 只 push HEAD | 本地有 tag, 远端没有 ⇒ CI/发布看着"没触发" | 单独 `git push origin vX.Y.Z` + `ls-remote` 回读 |
| 想用 commit 保存数据 | `zmax_data` 被 .gitignore, add 不进或直接 fatal | 走归档目录 + sha256; 真要入库的是文档/说明, 放 `docs/data_snapshots/` |
| 归档漏掉参数真源 | 归档里没有 `layer_forces.json`/`force_field.json` 之类 | `config/` 是软链且不在 git, 逐份 `cp config/calib/<本轮改过的>.json` 进 `data/`, MANIFEST 里点名 |
| 归档脚本照抄上一版没改路径/版本 | 产物堆到旧版本目录, MANIFEST 写错号 | 复制后只改 `DST` 前缀 + MANIFEST 主题, 跑完用 `search_files(target='files')` 核对目录名 |
| changelog 写成过程叙述 | 下一版读的人不知道改了什么、根因在哪 | 一行: "做了什么 + 为什么(根因)", 不写排查过程 |
| 版本号自选 | 与用户口径冲突 | 只按用户给的数字; 没给就只改内容 |
| 同步多端时默认“仓库最新” | 把远端较新的修复盖掉（反向同理） | 先两侧 sha256，不等就抓回远端 diff 看超集，只拷较新那个方向 |
| 归档清单把自己也算进去 | `sha256sum -c` 必 FAIL(清单写入时自己已被截断) | `find . -type f ! -name MANIFEST.sha256 -exec sha256sum {} \; > MANIFEST.sha256`, 再 `-c --quiet` 复核 |
| 归档清单靠手写 | 改了文件忘了加进 CODE 表，归档里少东西 | 用 `git diff --name-only v<上一版>..HEAD` 生成 CODE 列表，再人工剔除一次性的 `*_tmp.py` |
| 信记忆里的"当前版本" | `bump_version.py` 打印的旧号与预期不符，或跳号改错 | 先 `head VERSION.md` + grep studio.py 定基线；只落用户给的目标号 |
| 前台长 `sleep` 等 CI | `exit 124`，误判 CI 挂 | 轮询写成脚本用 `background=true, notify=true` |
| `scp` 多文件只到一部分 | 归档里少一个关键 json 而 sha256 仍「全 OK」 | staging 后 `ls` 逐名核对，再让脚本拷 |
| tag 后又有改动 | 用户问“我下的包里包含这个吗” | 不补 tag/不自升号，另起 commit；汇报里说明该改动是服务端热读/不进包 |

## 相关
- 仓库口径/入库边界/密钥红线: `zmax-engineering-repo`(user-owned)。
- 长跑服务改完的生效纪律: `live-service-change-discipline`。
