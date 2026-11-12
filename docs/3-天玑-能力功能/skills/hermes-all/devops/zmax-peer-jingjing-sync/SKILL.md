---
name: zmax-peer-jingjing-sync
description: "Use when 要与另一台机上的静静(Hermes) 同步记忆/工程 (局域网 .6↔.7)。"
version: 1.0.0
author: Hermes Agent
license: private
metadata:
  hermes:
    tags: [sync, hermes, ssh, memory, project, lan]
    related_skills: [zmax-usb-hermes-mirror, github-repo-management]
---

# 双机静静同步 (Windows .6 ↔ Ubuntu .7)

场景: 老倪说「你和静静在同一个局域网，工程、记忆，全同步」。
本机 = Windows (WLAN 192.168.1.6, 控制台 app9 在跑 8793/8797/8802)；对端 = Ubuntu 192.168.1.7
(OpenSSH 9.6, `ubuntu` 账号, 仓库 `/home/ubuntu/zmax` 228G, `~/.hermes` 9.5G)。

## 入口 (先做这步)
- 密钥: `~/.ssh/id_ed25519` (mike@zmax-win) 已写入对端 `~/.ssh/authorized_keys`；之后一律
  `ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes ubuntu@192.168.1.7 '...'`。
- 没有密钥时的建法: 本地 `ssh-keygen -t ed25519 -N ''`，再用 paramiko(密码) 把公钥 append 到对端
  authorized_keys（本机没 sshpass）。密码只用一次，不要写进脚本。

## 脚本 (已落地, 都在 hermes/scripts/)
| 脚本 | 作用 |
|---|---|
| `sync_peer_jingjing.py --what memory [--apply]` | 记忆双向同步: 本机 `hermes/{memories,skills}` ↔ 对端 `~/.hermes/{memories,skills}`，按 (size,mtime) 较新者胜，冲突(±60s)只报不动 |
| `sync_peer_jingjing.py --what project-pull --apply` | 把对端 `src/tools/flows/config` 拉到本机镜像 `~/zmax_repo` |
| `project_hash_diff.py` / `project_diff.py` | 工程差异统计 (mtime 版 / 内容版) |

## 状态空间工程 → Windows 版本同步 (已验证 2026-11-11)
老倪说「静静的最新状态空间工程, 你来同步成 windows 版本」走这条。

**两处落地** (app9 的 data/zmax_data 是指向源码树的软链, 写一处即可):
1. `~/zmax` — 源码/配置/画布镜像 (无 .git)
2. `~/zmax_console/app9/_internal` — Windows 打包运行体 (tools/gui、src、config、flows、defaults)

**同步口径 (状态空间工程 = 这五块)**:
- 画布/工程真源: `data/database/zmax/sources/canvas/state_space_obs.json` + `ss_traj_last.json`; `zmax_space.proj`(JSON, schema `zmax.statespace.project/2`), `zmax_engineering.db`(31 表: mw_node/mw_link/mw_port/mw_topic/param_events), `config_meta.json`, `function_notes*.json`
- 引擎/节点: `src/lerobot/{engine,engineering,middleware/nodes,ops,policies/aoi,memory}`
- 配置: 本机 `config/`(实体) ↔ 对端 `data/database/zmax/sources/config`(软链) —— **对比基准要按这个映射**, 否则会把 95 个 config 文件误报成缺失
- `defaults/canvas/state_space_obs.json` (打包默认画布, 也要随真源更新)
- 版本号文件 `tools/gui/{studio,version_sync}.py` (只差 vX.Y.Z 时可安全覆盖)

**本机领先、禁止覆盖**: `tools/ar_scene_render_server.py` (含 /video 限速+私有 MjData 修复, 1543 行 vs 对端 1328)、`tools/ar_mujoco_urdf.py`。
判定法: 拉对端版本到 scratch, 用 `difflib` 统计「本机独有行 / 对端新增行」, 本机独有 > 对端新增 ⇒ 本机领先。

## 铁律与坑
1. **远端 find 要整个单引号包住**；用转义双引号套 ssh 会让远端收到被吃掉引号的 find，**静默 0 行**。
   复制整个脚本过去跑 (`ssh 'bash -s' < remote_hash.sh`) 最稳。
2. **Windows 的 ssh/tar stderr 可能是 GBK** ⇒ `subprocess.run(..., text=True)` 会 UnicodeDecodeError 崩；
   固定 `encoding='utf-8', errors='replace'`。
3. **大文件清单传输用 `tar -T listfile`**，不要拼文件名进命令行（中文/空格/引号会炸）。
   拉取时 stdin 被 tar 流占着，清单要先单独 `ssh "cat > /tmp/lst" < lst`。
4. **cron/no_agent 里 `subprocess` 一跑就 `OSError: [WinError 6] 句柄无效`** —— 定时任务是无控制台/
   无 stdin 句柄的上下文，`capture_output=True` 会去取 STD_INPUT_HANDLE。修法：显式
   `stdin=subprocess.DEVNULL, stdout=PIPE, stderr=PIPE`（本脚本的 `sh()` 已改）。
   判据：手动跑正常、cron 一触发就挂 ⇒ 就是这条，不是 ssh/网络问题。
5. **本机打包版的文件 mtime 全是打包时刻** (app9 全部 10:43) ⇒ 用 mtime 判新旧会把 1700 个文件误判成
   “本机较新”。判内容必须 md5，且 **Windows CRLF 必须归一化**：`md5(b.replace(b'\r\n', b'\n'))`
   —— 不归一化会把 1813/1815 个文件全算成“不同”。
6. **对端是唯一的演进主干** (git 提交/分层重构都在那边)，本机 app9 是裁剪过的构建产物：
   `src` 6.2M vs 57M、`tools` 20M vs 65M。所以工程同步 = **对端 → 本机镜像**，不要拿本机覆盖对端。
7. **符号链接在 Windows 建不出来** (tar rc=2): `flows/state_space_obs.json → ../src/.../flows/...`、
   `config → data/database/zmax/sources/config` 都是软链。镜像里要**实体化**: 画布真源在
   `data/database/zmax/sources/canvas/state_space_obs.json`、配置在 `.../sources/config`，单独再拉这两个目录。
8. 抓完要**逐项 md5 对账** (不是看 rc): 例如 `tools/ar_scene_render_server.py`、画布 json 两侧 md5 必须相同。
9. **`scp` 在对端常常用不了** —— 报 `subsystem request failed on channel 0` / `scp: Connection closed`
   (对端 `sshd_config` 没开 sftp subsystem)，但 `ssh` 本身是通的。改走 tar 管道，一次成型:
   `tar -cf - -C <src_dir> <file1> <file2> | ssh -i ... ubuntu@host 'tar -xf - -C <dst_dir>'`；
   传完当场两端 `md5sum` 对账，别看 tar 的 rc 就宣布成功。
10. **本机 `C:\home\ubuntu\zmax` 是软链**（→ `C:\Users\Mike\zmax`）。所以在 Windows 侧
   写「Linux 路径」`/c/home/ubuntu/zmax/...` 和写 `C:\Users\Mike\zmax\...` 是同一处；
   脚本里 `os.path.abspath()` 会解析成后者，输出打印出 `C:\Users\Mike\...` **不是写错地方** ——
   去对账时按真实路径找，别照打印路径怀疑代码。
11. **改完 skill 要立刻推，并回读确认**：`--what memory --apply` 是双向、按 (size,mtime) 较新者胜 ——
   本机刚 patch 的 SKILL.md 会在下一次 apply 里被对端更新的同一文件**静默覆盖**，patch 当时成功、
   事后内容却回到旧版（`skill_view` 一看便知）。节奏是「改 → 立刻 apply → 再 `skill_view`/`md5` 确认还在」，
   发现被盖就把本机版本重写一遍再推一次。

## 反向推送 (Ubuntu .7 → Windows .6, 已验证 2026-11-10)
老倪说「跟小静静同步」而本机是 Ubuntu 时走这条, **别照抄上面的 Windows 视角**。

- 登录: `ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes mike@192.168.1.6 '...'`。
  账号是 **mike** 不是 ubuntu；`hostname` 返回 `Space`。默认 shell = cmd.exe，先 `chcp 65001 >nul &` 再写命令，否则中文输出 GBK 乱码。
- Windows 侧 Hermes 家目录是 **`C:\home\ubuntu\.hermes`**（不是 `C:\Users\mike\.hermes`，那里没有）。
  里面只有 skills/，**memories/ 可能整个不存在** —— 那就是从没同步过。
- 备份: `xcopy /E /I /H /Y C:\home\ubuntu\.hermes C:\home\ubuntu\.hermes.bak_YYYYMMDD`。
- 推送 (44M/2126 文件, wifi 约 1 分钟):
  `cd ~/.hermes && tar -czf - memories skills | ssh -i ~/.ssh/id_ed25519 mike@192.168.1.6 'tar -xf - -C C:\home\ubuntu\.hermes'`
  memories 目录远端不存在也没关系，tar 里的 `memories/` 条目会自建。

### 对账铁律 (踩过)
- 清单太长别拼进命令行：52 个 `Get-FileHash` 就 `命令行太长`。写成 .ps1 → `scp` 过去 → `powershell -ExecutionPolicy Bypass -File` → 输出 `hashes.txt` → `scp` 拉回比对。
- **CRLF 归一化只能一端做**。本机归一化后去比远端原始 hash，会把「本机含 CRLF 的文本 + 所有二进制(pdf/tar.gz)」全判成差异（本次 21 个假差异）。
  判据：对差异项改比 **原始字节 md5**，一致即假差异。
- 本次结果: 2130 文件（skills 2126 + memories 4）**逐字节全同**，MEMORY.md/USER.md 两侧 md5 相同。
- 推完不要重启对端 Hermes（禁自重启铁律）；记忆在下次新建 session 时加载。

### 状态空间同步的专属坑 (2026-11-11)
- **Windows 发给远端 tar 的文件清单会带 `\r`** ⇒ 远端 `tar -T` 报 `Cannot stat: No such file or directory`(文件名尾部藏着 \r), 而 tar 仍返回 0。指定清单必须走远端 `tr -d '\r' > /tmp/lst`: `ssh 'tr -d "\r" > /tmp/lst'` 且本地用 `input=lst.encode()`。
- **staging 解包路径 = 远端相对路径**, 但 config 落地路径要映射成 `config/xxx` ⇒ 查找源用远端 `rel`、落地用 `local_rel`, 混用会把 10 个 config 报成「远端缺失」。
- **GUI 在跑 (Z-MAX_Console.exe ×4) 时会用内存里的旧画布覆盖你写进去的新画布** (它在「保存/配置中心重载」时写盘, 实测同步后 4 分钟被重写一次 `cfg_loaded_at`/`project_path`)。同步完立刻 md5 回读, 并告知老倪「重开一次控制台才加载新画布」—— 禁自重启, 不要替他重启。
- **`canvas_selfheal.py` 只修 junction (data/zmax_data 软链)**, 不校验画布内容; 跑它不会改画布, 可以放心跑。
- **`cc_snapshot.json` 是本地化运行时快照** (`_meta.root` = 本机路径, 由 `tools/config_center_load.py build` 生成) ⇒ 对账时必然与对端不同, 属于正确差异, 别覆盖。
- **对账时「各改各的」多半只是运行时字段**: 画布 `cfg_loaded_at/loaded_at/sha256`、config `ts/generated_at/canvas_md5` 两端值必然不同 ⇒ `difflib` 报「本机独有 N = 对端新增 N」时逐行看一眼, 确认是时间戳就判「内容已同步」, 不要覆盖。sqlite `zmax_engineering.db` 字节不同但表计数全等 + `param_events` 最新 ts 相同 = 内容等价, 不必推。
- **肌肉记忆 `src/data/muscle_memory.json` 以对端为真源**: 28 个技能键两端相同, 值不同(对端 `n_ok` 更大 = 真机练得多) ⇒ 直接覆盖。
- **不许在 `_internal` 下用系统 python**: 该目录的 `*.pyc`(PyInstaller 打包的 stdlib) 会被当标准库加载, 报 `ImportError: bad magic number in 'linecache'`。
- **验证脚本要用 app9 的 exe 跑**: `cp probe.py _internal/tools/_tmp_x.py && ./Z-MAX_Console.exe _internal/tools/_tmp_x.py`, 结果写文件再读。系统 python 3.14 无 PyQt5; `_pyenv/python.exe` 设 PYTHONPATH 后仍 `ImportError: DLL load failed while importing QtCore`(PyInstaller 的 PyQt5 是假包, 只有 bootloader 能加载)。
- **自检脚本 `check_node_logic_refs.py` 已过时**: 本机 `node_logic.py` 里 `module.xxx(` 匹配数为 0 ⇒ 它 print「未发现调用」后 exit 1, 不是坏引用。改用工程库 `mw_node.source/symbol` 直接对源码文件做真源核对。
- **`mw_node.source` 字段可能是复合描述**: `路径 · 符号`、`路径::类.方法`、`路径 --参数`。解析要按 ` · ` / `::` / ` --` 切开再判文件存在性, 否则 18 个「源文件缺」全是假报(真实 2 个: mem_nodes.py 两端都没有、HilBridge 类名不符)。

### 状态空间工程的验收口径 (本次实测数)
- 画布: 94 节点 / 222 链路, 其中 15 个 `row_bg` 是分组条不参与执行 ⇒ 功能节点 79 个, `node_logic.match_node` 命中 79/79。
- 工程库: `mw_node` 79 · `mw_link` 222 · `mw_port` 308 · `mw_topic` 308 · `param_events` 194 —— 与画布节点/链路数必须相等。
- 真源核对: `mw_node.source+symbol` 对源文件 77/79 命中。
- 总工程 `zmax_space.proj`: 版本随对端 (v5.50.772), `canvas_fingerprint.md5` 与当前画布不等 = 对端保存后又编辑过, 属正常, GUI 会提示「画布已变更」。

### 中文路径/文件名必须英文中转 (2026-11-10)

`tar -czf - | ssh 'tar -xf - -C ...'` 传中文路径会坏：Windows bsdtar 报
`Invalid empty pathname`，且会留下乱码目录。做法：

1. 本地把文件改成**英文名**拷到 `/tmp/inbox/`（pptxxx/pdf 都改名）
2. `tar -czf - -C /tmp inbox | ssh ... 'if not exist <dst> mkdir <dst> & tar -xf - -C <dst>'`
   —— 注意 `/path/inbox` 解到 `<dst>` 下得到 `<dst>\inbox`，不是 `<dst>` 本身
3. Windows 侧用 **PowerShell `-EncodedCommand`**（脚本 UTF-16LE + base64）建中文目录并重命名：
   ```python
   ps = "Copy-Item ... -Destination ..."
   b64 = base64.b64encode(ps.encode('utf-16-le')).decode()
   subprocess.run(["ssh", ..., "powershell -NoProfile -EncodedCommand " + b64])
   ```
   直接 ssh 传中文命令会被 cmd 的 GBK 吃掉。
4. 验证：让 PowerShell 回 `($name -eq '期望中文名')` —— **不要看 ssh 回显**，
   回显是 GBK 按 UTF-8 解码，名字正确也会显示为乱码；`md5` + `name_match=True` 才算完。
5. `subprocess.run(capture_output=True, text=True)` 读 Windows 输出要加
   `encoding='utf-8', errors='replace'`，否则 `UnicodeDecodeError: 0xd5`。

## 已验证口径 (2026-11-10)

### 第二轮: 状态空间同步 (Ubuntu .7 → Windows .6, 同日)
老倪「跟小静静同步记忆, 让她的 windows 版本, 也跟你当前的状态空间一样」。

- **Windows 侧 `C:\home\ubuntu\zmax` 只有 `config / data / flows / zmax_data` —— 没有 src, 没有 tools**。
  `zmax_data/staging_zmax_repo` 也只有 `data`。⇒ Windows 是**数据+画布+记忆镜像**, 不是代码副本;
  想让它跑节点还得推 src + Python 依赖, 那不属于「同步记忆」范围, 要单独问。
- 备份: `xcopy /E /I /H /Y .hermes .hermes.bak_20261110b` + 两个画布 json 各 `copy` 成 `.bak_sync`。
- 画布真源两个位置都要推 (Windows 侧是实体文件, 没有软链):
  `flows/state_space_obs.json` 与 `data/database/zmax/sources/canvas/state_space_obs.json`。
  推之前先比 md5 —— 本次 Windows 是 `51488fa4…` / 本机 `1fdf3fd9…`, 确认是旧的才推。
- **tar 落地要建同构临时目录**, 不要拼两条 tar 路径:
  ```
  mkdir -p /tmp/ss_push/flows /tmp/ss_push/data/database/zmax/sources/canvas
  cp 两个 json 到对应位置
  tar -czf - -C /tmp/ss_push flows data | ssh ... 'tar -xf - -C C:\home\ubuntu\zmax'
  ```
- 对账 (certutil 输出行尾带 `\r`, `grep -oE '[0-9a-f]{32}'` 才取得到):
  `MEMORY.md` b980535c… / `USER.md` 1088ba91… / 两个画布 json 1fdf3fd9… **四项两侧全同**;
  skills 文件数 2136 = 2136。
- **顺序很重要**: 先把本轮新认知写进 skill (`l2-node-signal-linkage`), 再推 —— 否则只是搬文件,
  对端认知还是旧的。

### 第一轮: 记忆 + 工程镜像
- 记忆: 拉 5 推 64 → 再跑一遍 0/0 幂等；`MEMORY.md`/`USER.md` 两侧 md5 相同。
- 工程: 镜像 `~/zmax_repo` = 123M(src/tools/flows) + 63M(data/sources/{canvas,config})，抽查 4 个文件 md5 与对端逐位相同。
- 归一化内容对账: 两侧同在 1815 个文件里**只有 97 个真不同** (其余是 CRLF)，差异集中在
  `src/lerobot/middleware/nodes/*` 与 `engineering/*` (对端做了分层重构, 本机包是旧结构)。
- 对端 8802 的实现比本机新 (1439 行, 自带 `/cam.json` + `/depth.png`) ⇒ 直接取对端文件覆盖本机
  `app9/_internal/tools/ar_scene_render_server.py` (先备份 .mine_HHMM)，再重启计划任务 `ZMAX_8802_RENDER`，
  端点/画面逐项复测。
