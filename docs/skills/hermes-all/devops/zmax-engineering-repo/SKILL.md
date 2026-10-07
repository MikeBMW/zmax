---
name: zmax-engineering-repo
description: "Use when 整合/推送 Z-MAX 工程仓库或统一代码绝对路径。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [git, repo, path-namespace, zmax, github, housekeeping]
    related_skills: [git-history-slimming, zmax-usb-hermes-mirror, disk-redline-guard, linux-host-maintenance]
---

# Z-MAX 工程仓库 (zmax) — 工程根 / 命名空间 / 入库边界

## When to Use
- 老倪说「/home/ubuntu 太多东西/整合/没用的删掉」「工程代码放哪」「开新 github 仓库」。
- 要把代码里的绝对路径改成 `/home/ubuntu/zmax` 开头, 或怀疑改了路径后哪里断了。
- 要把技能/记忆推上 GitHub, 或仓库里混进了权重/截图/交付件。

## Orin home 唯一入口 = ~/.zmax (2026-10-07 整理落地)
老倪口径: **Orin 的 home 只保留唯一 `.zmax` 隐藏目录**, 所有 zmax 相关代码/产物都在里面, 不得有其它路径(含 Desktop)。
- 现结构: `~/.zmax/{arm,uplink,rs,yolo,state_space,quarantine,logs/{sdk,desktop},rokae_log/{home,desktop},data/{orin_10s,camera_frame.png}}`
  + 原有 `act/ models/ mcap/ lerobot/ shadow_reports/` + 8月老脚本(orin_*.py/diag_*.py)。
- 搬迁清单: `~/.zmax/CONSOLIDATE_MANIFEST.jsonl`(src→dst+指纹+verified); 日志 `~/.zmax/_consolidate_<ts>.log`;
  旧物**归档而非删除**: `~/.zmax/_archive_units_<ts>/`、`_archive_junk_<ts>/`(可整目录回滚)。
- 动过的单元(只改 ExecStart 里的绝对路径, User/WorkingDirectory/argv 全不变):
  `zmax-arm-sdk-bridge.service` → `~/.zmax/arm/zmax_arm_sdk_bridge.py`;
  `zmax-orin-uplink.service` → `~/.zmax/uplink/zmax_orin_uplink.py`。改完 `daemon-reload` + `restart`。

### 坑(实战踩出来的)
1. **`sudo` 包装函数 + heredoc 会抢 stdin**: `SUDO(){ echo pw | sudo -S -p '' "$@"; }` 后接 `<<'PY'` 时,
   python 读到的是密码而不是脚本。⇒ 要 root 跑的脚本先 `scp` 成文件再 `sudo python3 /tmp/x.py`, 别用 `sudo python3 - <<EOF`。
2. **归档/删除前必须断言服务真的指向新路径**: 只看 `systemctl is-active` 会骗人——单元还指着老路径时重启照样 active,
   此时把老 .py 归档了, 服务就“跑在已不存在的文件上”(下次重启即挂)。断言 = `ps -eo cmd | grep <新路径>` 出现在 argv 里。
3. **指纹校验不能用 `find|md5sum|md5sum`**(哈希含绝对路径, 一移动就变)⇒ 假警报。
   正确: `(cd $dir && find . -type f -print0 | sort -z | xargs -0 md5sum | md5sum)`; 或直接依 `mv`(同盘 rename 数据不动)+文件数比对。
4. 搬**在跑**的脚本(如 `~/zmax/rs_fast_node.py`, ssh 会话手工起的)可以搬, 进程靠 inode 继续活,
   但之后重启必须用新路径; 手工起的进程没有单元/autostart, 动手前先 `grep -rn <名> /etc/systemd ~/.bashrc ~/.config/autostart`。
5. 不属 zmax 的别碰: `~/mes/`(MES 桥, 2 单元+2 进程, ROS 安装路径硬编码)、`0810*/`/`0810.zip`/`tashan0924/`(厂商包)、
   `Desktop/README_首次启动说明.md` + `put_points.yaml`(厂商/操作员文档)。
6. `~/logs/`(global_logger_*.log)是 **xCoreSDK 按 cwd 生成的**日志, 不是代码; 单元 `WorkingDirectory=/home/tashan` 不变时它还会再生成
   ⇒ 要彻底收进 .zmax 得同时改 WorkingDirectory(本次没改, 保行为不变)。
7. 验证服务活没活: 本机 `curl https://datadrive.world/api/relay/orin/status` 看 `ts` 是否继续前进(uplink 每 5s 推一次), 比翻本地日志靠谱。

- 清理结果(2026-10-07): `~/.zmax` **1.8G → 19M**。删了老数据(act/ models/ lerobot/ shadow_reports/ orin_10s/)+15 个无引用的一次性 8月脚本,
  凭据存 `~/.zmax/_deleted_<ts>.jsonl`(逐条 path/字节/文件数/原因)。**保留** 10 个文档里仍是 Orin 管线组件的脚本
  (dds_writer / upload_data_v2 / simulink_hw_server / orin_gateway / orin_snapshot / orin_sys_status / orin_field_status /
  orin_infer_service / orin_real_infer / orin_cam15) + `state_space/ yolo/ quarantine/ rs/ arm/ uplink/ logs/ rokae_log/`。
- **mcap 采集录制(123 段/983M) 不存 Orin 了**: 整份同步到数据服务器 `/home/ubuntu/zmax_data/orin_mcap_archive_20261007/`
  (核验: 两侧文件字节 1029292993 相同 + 内容指纹 `fb81efcd3bc9acc254ed898e71ae246b` 相同) 后才从 Orin 删。
  ⇒ 要找 8月10–9月16 的 Orin 采集原始录制, 去数据服务器那个目录, 不在 Orin 上。
- 未动(范围外, 厂商包): `0810/ 0810bak/ 0810.zip tashan0924/` —— 厂商包的上一版, 回滚用。
- 迁移/删除核对的两个教训: `du -sb` 会把**目录 inode**也算进去(124 个目录 × 4096 = 507,904 字节),
  跟 rsync `Total file size`/`find -printf %s` 对不上 ⇒ 比字节用 `find -type f -printf '%s
' | awk`;
  真同步判据 = 路径无关内容指纹 `(cd dir && find . -type f -print0 | sort -z | xargs -0 md5sum | md5sum)` 两侧相同。

## 基本事实 (2026-10-07 家目录整合后 —— 路径口径已变!)
- **工程根 = `/home/ubuntu/zmax`**, 它是**独立 git 仓库**, origin = `https://github.com/MikeBMW/zmax` (public, main)。
  · **`~` 顶层只剩 `zmax` 这一个 zmax 相关项**(2026-10-07 整合): 下面所有老名(软链/实体)全部消失。
  · 代码里不该再出现 `/home/ubuntu/<老名>` 或 `~/<老名>` 或 `$HOME/<老名>` 三种写法中的任何一种。
- **数据/仓库/环境现在都在工程根里面**:
  · `zmax_data/`(180G: ss_live/ runtime/moveit_plan/ stable-wm-cache/ hf_cache/ aoi_v4/ backups/ models/weights/ secrets/600)
  · `external/lerobot-smolvla-lew`(mac-hw 分支, 独立 clone 不是 worktree) · `external/INTACT-JEPA`
  · `venvs/{gs,lerobot,dds,colmap,cuda-nvcc}-venv` · `toolchains/cuda-shim` · `hermes/install`
  · 五个 `ZMAX_*` 环境变量默认值同步改成 `$ZMAX_DATA=/home/ubuntu/zmax/zmax_data`(见下表)。
  · 软链目标也修过一轮: `zmax/models/*` → `zmax_data/models/*`, `gui-venv311/bin`(有 1121 条断链)
- **数据全在 `/home/ubuntu/zmax_data/`**: `ss_live/`(Orin 状态流+深度源, 旧名 zmax_ss_remote)、
  `runtime/moveit_plan/`(旧名 zmax_moveit_plan)、`stable-wm-cache/`(训练缓存, 含政策保护的 95G 官方数据集)、
  `hf_cache/`(HF 缓存默认根, `~/.cache/huggingface` 是它的软链)、`aoi_v4/`(AOI 工具链 + agent-hub 静态目录)、
  `backups/`(hermes 备份 + 整套复制件)、`models/weights/`、`secrets/`(600)。**根上只留软链**。
- 根目录目标形态(2026-09-30 收尾后, 81 条) = `zmax/`(工程) + `zmax_data/`(数据) + 几个软链
  (`zmax_rel` `zmax_dds` `stable-wm-cache` `zmax_ss_remote` `zmax_moveit_plan` `aoi_v4` `.cache/huggingface`)
  + 第三方仓库(`INTACT-JEPA` `lerobot-smolvla-lew`) + venv(`lerobot-venv` `dds-venv`) + 点文件/个人目录。
  说明书: `docs/notes/home_top_level_map.md`(每个条目是什么/谁在用/能不能删)。

## 入库边界 (老倪: 只放源代码 + 技能 + 记忆)
| 进 | 不进(留本机) |
|---|---|
| `src/` `tools/` `configs/` `flows/` `scripts/` `docker/` `dds/` `ros_*_ws/` 等代码与配置 | `reports/` 运行产物(截图/状态快照, 数百 MB) |
| `docs/**` 文本(.md/.csv/小图) | 权重 `*.pt/*.h5/*.safetensors`、交付件 `pdf/pptx/zip`、视频 |
| `docs/skills/hermes-all/` 技能全量镜像 | `outputs/` `runs/` `models/` `gui-venv311/`(venv) |
| `docs/memory/` 记忆快照(MEMORY.md + USER.md, 每日 + latest) | `.github/`(fork 的上游 CI) |

- 守卫: `python3 tools/repo_guard.py` (加 `--staged` 可做 pre-commit)。判据: 权重/交付件类 >200KB 报; 二进制 >300KB 报
  (白名单 `config/moveit_*/urdf/meshes/`); 文本/代码不设上限(studio.py 1MB、uv.lock 1.1MB 正常)。
- `.gitignore` 已封 `reports/ media/ outputs/ models/ backups/ *.pt *.h5 *.pdf *.pptx *.zip ...`。

## yaml/配置收编口径 (2026-10-08 实测)

仓库根散落的 `config_smolvla_lew_lora_*.yaml`(= 每轮联合训练生成的配置)会越积越多。收编判据与做法:

1. **先分三类再动手**(别删完才发现被引用):
   - **生成物** — 只在 `reports/joint_train_*/{summary.json,L3_mkcfg.log}` 里被提到(留痕), **无任何 .py/.sh 引用**, 且已被 `.gitignore` 的
     `config_smolvla_lew_lora_*.yaml` 覆盖 ⇒ **收进 `configs/generated_train_configs/`, 不要删**: 删了文件名还在报告里, "那轮用什么配置跑的"就回溯不了。
   - **手写配置** — `git ls-files` 里**被跟踪**的 ⇒ 源文件, 收进 `configs/`(如 `configs/policies/{act,smolvla,smolvla_lew,hybrid}/`), 并改引用点。
   - **不能动的** — `.github/workflows`(GitHub 要求路径) · `config/`(ROS 包布局: `config/moveit_xms5/launch/*.py`、`arm_control.py` 按包内相对路径读, 动就断) · `reports/`(生成区)。
2. **查引用只查代码**: `grep -rl --include=*.py --include=*.sh <basename> .` 并排除 `reports/ docs/` —— 否则报告里的留痕会被当成"被引用"。
3. **挪配置前必须确认相对路径基准**: lerobot 的 `dataset.root` 是 **CWD 相对**(`Path(cfg.dataset.root)` 直通, 不按配置文件目录拼)。
   所以**必须仍在仓库根启动训练**, 配置文件放子目录不改语义; 但要顺手把生成器改成写新目录, 否则下轮又散落:
   `os.makedirs(cfg_dir, exist_ok=True)` + 路径常量; 改完 `python -m py_compile` 验证。
4. **收编留清单**: `from → to` + "被哪些训练目录引用"写 JSONL 进 `zmax_data/backups/`, 并同目录放 `README.md` 说明它们是生成物不是手写配置。

## 家目录整合/改路径: 第 4 种写法与"老进程还在写老路径"的取证 (2026-10-08 实测)

**改引用只覆盖 绝对 `/home/ubuntu/x` · `~/x` · `$HOME/x` 三种写法是不够的 —— 第 4 种是分开拼:**
```python
os.path.join(os.path.expanduser("~"), "zmax_data", "model_autoload")   # ❌ 三种写法都扫不到
```
实测后果: 家目录 `~/zmax_data` 被反复建回来(里面是 `ctl_auth.json` 真动授权、`cam_local_src.json`、日志),
一度盖过"~ 顶层只剩 zmax"的验收。扫法: `grep -rn 'expanduser("~")\|expanduser(\x27~\x27)'` 看它**后面跟的字符串字面量**, 别只搜拼接后的路径。
同类还有 `Path.home() / "zmax_data"`、`os.path.join(os.environ["HOME"], "zmax_data")` —— 一并扫。

**"代码已改干净 ≠ 老路径没人写": 老进程的内存里揣着改之前的字符串。**
- 取证(只读, 一眼看出谁在写): 扫 `/proc/*/fd` 里 readlink 指向老目录的进程 ⇒ pid + cmdline + 具体文件:
  ```bash
  for p in $(ls /proc | grep -E '^[0-9]+$'); do ls -l /proc/$p/fd 2>/dev/null | grep -q '/home/ubuntu/zmax_data' && \
    printf 'pid=%s %s\n' $p "$(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-90)"; done
  ```
  实测定式: 长跑服务(站台 `cam_live_stream` / L2 / GUI 子进程)在**整合前**启动的, 会一直往老路径写。
- **挨个分清写的是"数据"还是"日志"**再决定动不动: 实测那几笔全是 log(启动日志/GUI 重定向日志) ⇒ 无数据丢失风险, 不杀进程(里面可能有在飞训练),
  写清楚"重启后消失"即可; 若是数据集/真值/授权状态 ⇒ 必须立刻处理(见下)。
- **安全相关的必须当场修**: 8793 页的"真动授权"由站台写 `ctl_auth.json` —— 若站台是旧进程(写老路径)、L2 执行器是新进程(读新路径),
  就在页上显示"已授权"而执行器看不见 ⇒ **授权形同虚设**(方向是 fail-closed 不会乱动, 但"点了没反应")。
  处置: 按 **PID** 杀旧实例(**别用 `pkill -f`**, 会匹配执行它的 shell 自杀) → 跑官方守卫 `cam_stream_guard.sh` 让它
  **按自己的参数**拉起(手搓命令行会换参数/串线) → 复核新实例命令行与旧实例**逐字节一致** + `/station/status` 的 `ctl.tcp`/`exec.online`/`auth.armed`。
- 页面报错文字本身带路径 ⇒ **能直接区分新旧进程**: 报 `/home/ubuntu/zmax_data/...` = 旧进程还在当班; 报 `/home/ubuntu/zmax/zmax_data/...` = 已是新进程(那就只是浏览器缓存, 让用户刷新)。

### 第 5 种写法(2026-10-08 补): `Path.home()` / `os.environ["HOME"]` 分开拼
```python
Path.home() / "zmax_data" / "l5_corners"          # ❌ 第5种
Path.home() / "lerobot-smolvla-lew" / "runs"      # ❌ 第5种(老 fork)
os.path.join(os.environ["HOME"], "zmax_data")    # ❌ 第5种
HOME = os.path.expanduser("~"); OUT = HOME / "lerobot-smolvla-lew" / ...   # ❌ 改名也扫不到(变量再拼)
```
**实际后果(都是实测, 不是理论)**:
- `tools/rokae/l2_transport_sdk.py` + `tools/sdk_motion_service.py` 这样写 ⇒ SDK 执行腿永远判"代理未就绪",
  页面报「已下发(真动)」但**机器人不动**(每条在最后一跳被拦)。
- `tools/auto_iterate.py`/`auto_loop.py`/`cicd_deploy.py`/`data_closed_loop.py`/`relay_train.py`/`disk_guard.py` 等 ~20 个 CICD/训练文件
  ⇒ 产物写回家目录 ⇒ `~/lerobot-smolvla-lew` 反复被建回来(实测 YOLO 标注训练 06:41/06:56 各建一次)。
- `src/lerobot/engineering/paths.py` 的 DATA_DIR 是全局数据根, 漏改影响面最大。

**扫法(两种, 都要跑)**:
```bash
python3 tools/scan_oldpaths.py     # 只扫可执行代码区, 列 file:line + 类别(带 SUBS 映射建议)
python3 tools/audit_paths.py       # 全仓扫(含 docs, 用于区分"历史留档"与"真代码")
```
命中分两类: **代码区必须改**(统一改成 `os.environ.get("ZMAX_DATA"|"ZMAX_FORK", "<工程根>/...")` +
`tools/fix_oldpaths_code.py --apply` 可批量带清单); **docs/历史留档不能改**(那是当时的取证快照)。
注意: 探测/判据脚本自身(preflight/audit/scan/fix)里的老路径字符串**是判据, 不能一起改** —— 要放进 SKIP 名单。

### 改完代码不等于修好: 必查"老进程揣老路径"
**已经在跑的进程, 内存里是改之前的字符串** ⇒ 代码全绿语法通过, 功能照样整体失效。判据:
- 进程启动时间 **< ** 它依赖的代码文件 mtime ⇒ 可疑, 必须重启该进程(实测 L2/SDK 服务/站台全中过)。
- 一键看全部: `bash tools/verify_functions.sh`(含该项探测 + 端口/FIFO/真值/容器/网关/家目录形态)。
- 单服务重启工具: `tools/restart_sdk_motion_service.sh`(8798 会因"端口已在听"跳过重启, 必须强制)、
  `restart_vl_l2_homecons.sh`(L2+VL)、`cam_stream_guard.sh`(站台, 按它自己的参数拉起, 别手搓命令行)。

### 守卫误判要当故障修(2026-10-08 实测)
站台加了「笔记本内置 ↔ USB」换源功能并落盘 `cam_local_src.json` 后, `cam_stream_guard.py` 仍只认
`"Integrated RGB"` ⇒ 用户选了 USB 之后守卫**每 5 分钟重启一次站台**(页面反复掉线)。
口径: **守卫的期望值必须来自用户的运行时选择, 不能写死** ⇒ `judge(..., local_key=local_expected())`。

## 路径命名空间统一 (老倪: 左右脑源码打开后都以 /home/ubuntu/zmax 开头)
```bash
python3 tools/ns_unify_paths.py --dry   # 先看要改哪些、多少处
python3 tools/ns_unify_paths.py         # 真改 (改前 tar 备份: zmax_data/backups/ns_unify_pre_<日期>.tar.gz)
```
规则(写在脚本里, 别手改):
1. `/home/ubuntu/zmax_rel/...` → `/home/ubuntu/zmax/...` **恒安全**(前者本就是软链)。
2. `/home/ubuntu/zmax_dds/...` → `/home/ubuntu/zmax/dds/...`。
3. `/home/ubuntu/lerobot-smolvla-lew/...` → `/home/ubuntu/zmax/...` **仅当 zmax 下存在同一相对路径**;
   两棵工作树分支不同、内容有差异 ⇒ 缺路径的一律保留并打印出来人工看。
4. **不动** `reports/`(历史取证, 改写=篡改证据) 与 `docs/skills|docs/memory`(是 `~/.hermes` 的镜像, 要改改源)。
5. **绝不能碰** `./.git` 指针文件(worktree 时它存着 gitdir 路径)与脚本自身。

仓库外一起改(否则口径不一致): `/etc/systemd/system/*.service` + `~/.hermes/scripts/*`(改前 `.bak`),
改完 `systemctl daemon-reload`, 再逐个核 `systemctl is-active`(reload 不会重启服务)。

## 基线自检 / 首次 clone 初始化 (老倪: 首 clone 就要识别出已下载的模型和数据)
- 入口: `bash tools/zmax_bootstrap.sh [--apply|--download|--smoke|--secrets|--systemd]`

## 家目录整合 playbook (2026-10-07 落地, 下次搬路径照这个走)
工具: `tools/consolidate_home.py --dry|--apply --stage A|B|C|R|all` + `tools/fix_symlinks_homecons.py`
+ `tools/restart_vl_l2_homecons.sh`。清单 `zmax_data/backups/HOME_CONSOLIDATE_MANIFEST.jsonl`。

阶段划分(每阶段自带核验段):
- **A** 搬不涉及在跑服务的(第三方仓库/venv/toolchains) + 老路径留软链过渡。
- **B** 搬 `zmax_data`(在跑服务在用) + 改 systemd/Hermes 脚本 + 重启活单元。
- **C** 删老路径软链(引用改完才做)。
- **R** 改**仓库内**老路径字面量(改前 `tar` 整树备份)。

### 六个真坑(全是 2026-10-07 实测踩出来的, 每条都静默)
1. **三种写法, 只改绝对路径必漏**: `os.path.expanduser("~/zmax_data")` 这类家目录相对写法照样能跑(家目录没变),
   但老目录一删它**静默** mkdir 出新空目录继续往里写, 不报错。⇒ 绝对 / `~/` / `$HOME/` 三套一起换。
2. **软链的目标字符串不在任何文件内容里** ⇒ 内容改写器扫不到。实测一次 `find ~ -xtype l` 报 **1121 条断链**
   (`zmax/models/*` 全指老 zmax_data, `gui-venv311/bin` 指老 lerobot-venv —— 仓库自己的 venv 会一起断)。
   ⇒ 搬完必跑 `find <根> -xtype l` + 按 `readlink` 重写目标, 不看内容。
3. **改写器会改写它自己**: 替换表里写着 `old→new`, 第一遍就把自己那张表改成恒等映射, 第二遍开始静默失效。
   ⇒ 改写器必须显式跳过自身文件(`"homecons" not in basename`)。
4. **docker 绑定挂载靠 inode, 容器配置里的源路径字符串会过期**: 目录 rename 后容器照跑(同一 inode),
   但容器**下次重启**时 docker 重新解析源路径 ⇒ 老路径没了就起不来。⇒ 用新路径重建容器(`docker run` 照原参数), 别只 `restart`。
5. **长跑进程内存里揣着旧字面量**: 改完源码不算完, 必须重启那些进程(否则它们继续往老路径写, 表现为"老目录又冒出来")。
   重启顺序无关; 但**只信落盘位置**——改完看新旧两侧的 mtime, 老侧停住、新侧每秒在动才算好。
6. **看护脚本只会 `restart` 不等于能自愈**: `cam_stream_guard.start_tcp_sampler()` 原来只有 `docker restart`,
   容器一旦被 `docker rm` 过就永远救不回来(TCP 真值停刷 ⇒ 整条臂链路看着"死了", 而守护每 5 分钟报一次"已处理")。
   ⇒ 兜底补 `docker run`(照原参数重建)。检查任何守护时都问一句: 目标**不存在**时它会怎么办?
  (实现在 `tools/zmax_bootstrap.py`; 清单 `tools/zmax_assets.json`, 机器可读, 加资产只加一条)。
- **识别顺序**(已下载的绝不重下): 默认路径 → `alt_paths`(老位置) → `alt_globs`(精确文件) → HF 老缓存 `~/.cache/huggingface`。
  命中即"可用/可采纳"; `--apply` 只建软链/建目录/写 `$ZMAX_DATA/zmax_paths.env`, **只增不改不删**。
- `--smoke` = 状态空间功能自检(10 个核心模块 import + 关键文件 + 端口), 全绿 = 代码面恢复完成。
- 退出码: 必需资产齐 0 / 缺 1(可进 CI)。裸机上跑一次应当**打印出确切的下载命令**, 而不是偷偷下 100G。
- 文档口径: `docs/notes/model-paths.md`(默认路径+下载命令) / `docs/notes/restore_matrix.md`(功能→代码→资产, 四类资产)。

## 默认落盘路径约定 (模型下载默认落哪)
| 变量 | 默认 | 放什么 |
|---|---|---|
| `ZMAX_DATA` | `/home/ubuntu/zmax/zmax_data` | 所有重东西的根 |
| `ZMAX_MODELS` | `$ZMAX_DATA/models` | **模型默认下载根** |
| `ZMAX_HF_HOME` | `$ZMAX_DATA/hf_cache` | **HF 缓存默认根**(布局同 `~/.cache/huggingface`: `hub/models--…`) |
| `STABLEWM_HOME` | `$ZMAX_DATA/stable-wm-cache` | 数据集 + 训练产物 |
| `ZMAX_SECRETS` | `$ZMAX_DATA/secrets` | `zmax.env`(600, 永不入库) |

环境变量优先; `--apply` 生成 `$ZMAX_DATA/zmax_paths.env`, `source` 后全部脚本/服务同一套路径。

## 密钥出库 (公开仓库的硬红线)
- 真值只放 `$ZMAX_DATA/secrets/zmax.env`(600, 即 `/home/ubuntu/zmax/zmax_data/secrets/zmax.env`); 代码/单元只留 `${VAR}` 占位;
  systemd 用 `EnvironmentFile=-/home/ubuntu/zmax/zmax_data/secrets/zmax.env`。
- `python3 tools/secret_scan.py [--staged]` 扫已跟踪/暂存区(值打码输出, 命中退 1); 与 `repo_guard.py` 一起当提交前双闸。
- 已泄露的值: 上游 vendored 文档里的示例 key 不算(路径白名单 `docs/source/` `src/lerobot/`);
  **历史里的密钥清不掉**(force-push 后旧对象仍可按 SHA 取) ⇒ 要么删库重建(破坏性, 需老倪点头), 要么轮换密钥。

## 技能 + 记忆同步
- 脚本: `tools/sync_hermes_to_repo.sh` (`--no-push` 只提交)。三件事: ① zmax-console 全家 → `docs/skills/xspace/`
  ② **技能全量镜像** `~/.hermes/skills` → `docs/skills/hermes-all/`(rsync --delete + 删 >300KB 大图)
  ③ 记忆 → `docs/memory/hermes-jingjing-{memory,user}-<日期>.md` + `-latest.md`; 然后 commit + push。
- cron: Hermes job `hermes-skill-memory-sync`(每 6h) → 包装脚本 `~/.hermes/scripts/sync_hermes_to_repo.sh`
  → **必须指向工程根那份**(2026-09-30 前指向 fork 副本, 会把技能推到错仓库)。

## 验证口径 (交付前必做)
```bash
cd /home/ubuntu/zmax && git status --porcelain | wc -l      # 0
python3 tools/repo_guard.py                                  # ✅ 干净
python3 -m compileall -q tools src/lerobot/policies/left_right
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8793/station   # 200
rm -rf /tmp/c && git clone --depth 1 https://github.com/MikeBMW/zmax.git /tmp/c && ls /tmp/c   # 全新克隆核验
```

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 把 fork 路径当同义词批量替换 | 指向 mac-hw 树里不存在的文件 / 改错内容 | 先 `os.path.exists(zmax+tail)` 判存在, 不存在保留 |
| 改写 `./.git` 指针 | git 直接坏掉(找不到 gitdir) | 脚本 SKIP_FILES 显式排除 |
| 用 `du` 统计仓库体积 | 报出来的数跟 `git ls-tree HEAD` 差几倍(块取整 + 输出被截断) | 入库体积一律 `git ls-tree -r -l HEAD` 求和 |
| 只改仓库内、忘了 systemd/Hermes 脚本 | 单元里还是旧路径, 下次改口径又漂 | 仓库外一起 sed + daemon-reload + 核验 |
| 技能镜像与仓库不一致 | `git status` 一堆 D 与 ??(docs/skills 下) | `rsync -a --delete` 重新镜像, 别只 cp |
| 大图/PDF 混进技能镜像 | 仓库体积暴涨 | 镜像后 `find -size +300k -delete` + `repo_guard.py` 兜底 |
| 把 venv 当老位置资产"采纳" | 软链过去的 venv 跑不了(内部路径写死) | bootstrap 里 venv/env 类只报"复用原处"并给重建命令, **不建软链** |
| `alt_paths` 里写了目录 | 把整个目录当资产采纳(如 lora_l3 → reports/) | 精确文件用 `alt_globs` 且 **glob 先于 alt_paths**; 取文件要 `os.path.isfile` 过滤 |
| 从 fork 收源码时连生成物一起收 | `tools/ros2_interfaces/install/**` 上千个 rosidl 生成文件入库 | 排除 `/install/`、`docs/`、`reports/`、`media/`、`.github/`; 根级脚本归 `tools/fork_experiments/` |
| 用 `du -sh` 判目录空不空 | 明明有文件却报 0 | 用 `ls -A`/`os.listdir` 判非空; du 受挂载/稀疏影响 |
| 用 `ln -s 相对路径` 在**别的目录**里建软链 | 链指向 `<那个目录>/相对路径`, 直接断(如 `.cache/huggingface → zmax_data/hf_cache` 变成 `.cache/zmax_data/hf_cache`) | 跨目录一律用**绝对路径**; 建完立即 `python3 -c "import os;print(os.path.isdir(p))"` 验一次 |
| 搬数据目录后没验活链路 | 服务/训练在报错, 半天后才发现 | 搬完立刻验: 软链目标存在 + `bash tools/zmax_bootstrap.sh` 仍 15/15 + 8793/8794 返回 200 |
| 只改内容不看软链 | 服务全绿但 1121 条 `zmax/models/*` 断链, 检测器加载不到在役权重 | 搬完 `find <根> -xtype l` 修目标(见 playbook 坑 2) |
| 改完源码不重启长跑进程 | 老路径目录被静默重建, 新路径文件不刷新 | 重启 VL 链/L2/站台, 再比对新旧两侧 mtime(见 playbook 坑 5) |
| `pgrep -f <模式>` 里出现自己命令行里的名字 | 执行它的 shell 被自己杀掉(实测一晚 5 次; 用 `kee[p]alive` 括号技巧**不够**, 因为命令行别处还会原样出现这个名字) | 一律写脚本文件执行(脚本 cmdline 里没有这个名字), 或先取 pid 再 kill |
| systemd 单元 exit 75 无限重启 | 网关"看着没起来", 其实野进程在服务, restart counter 涨到 2110 | `systemctl --user status` 看真身; 系统级重复单元 stop+disable(用户级 Linger=yes 已保证开机自启) |
