# 相机与真机链路 (Z-MAX 诊断手册)

## 相机源对照

| 格 | 数据来源 | 额外生效条件 |
|---|---|---|
| `arm` 臂相机 | Orin `8792/frame.jpg`（fallback 链：本机 18792 → Orin） | — |
| `local` 内置 | 本机 `/dev/video0` | `ZMAX_CAM_LOCAL=1` |
| `local2` 中央相机 | Intel 550C 的 `usb_cam_http.py --dev 0 --port 8812 --bind 0.0.0.0` → `http://192.168.23.70:8812/frame.jpg` | `ZMAX_CAM_LOCAL=1` + `--local2-url` |
| `aoi_gold` / `aoi_surface` | 工控机 `10082` / `10083` | — |

## local / local2 的静默开关

`cam_live_stream.py`:

```python
ap.add_argument("--local2-url", default="")
ap.add_argument("--no-local2", action="store_true",
                default=not os.environ.get("ZMAX_CAM_LOCAL"))
...
if not args.no_local2 and (args.local2_url or args.local2_dev >= 0):
```

环境变量未设 ⇒ `not None` = `True` ⇒ `no_local2=True` ⇒ 整段 `if` 被跳过。
不报错、不打日志，`/station/status` 里只有 `online=False, fps=0.0, age=-1.0`。

判据与验证:

```bash
curl -s http://127.0.0.1:8793/station/status   # 看 stats.local2
curl -s -o /tmp/l2.jpg -w '%{http_code} %{size_download}\n' \
     http://127.0.0.1:8793/snapshot/local2.jpg
# 503 = 没接源；200 + 几十 KB JPEG = 通了
```

## 中央相机 (Intel 顶摄)

Intel 侧常驻命令形态:

```
usb_cam_http.py --dev 0 --port 8812 --bind 0.0.0.0 --w 640 --h 480 --fps 10 --quality 80
```

端点：`/frame.jpg`（约 37KB，640x480）、`/health`。

`--bind 0.0.0.0` 是能被本机取到的前提。反例：Intel 的 `cam_relay.py`（8901）只 bind `127.0.0.1`，
**外部访问不到**（探活拿到 `http=000`）—— 不要拿它当中央相机源，也别据此判断"Intel 没有相机"。

## 真机轨迹三层闸

页面 `bRTraj`（▶ 右臂跑真实轨迹）→ `POST /api/arm/step_traj` → `tools/rokae/arm_step_traj.py`。

1. **授权**：`ctl_auth` 模块 / `zmax_data/ctl_auth.json`；
   状态看 `/station/status` 的 `ctl.motion_armed`。撤销走 `POST /ctl/arm {"on": false}`。
2. **控制器 TCP 可达**：`192.168.23.160`。

   ```bash
   for p in 30001 30002 30003; do
     timeout 2 bash -c "</dev/tcp/192.168.23.160/$p" 2>/dev/null && echo "open $p" || echo "closed $p"
   done
   ```

   **ping/ARP 通 ≠ 服务在听**。全 closed ⇒ 控制器侧（示教器）没开远程控制/SDK 服务，
   软件侧无法绕过。从同网段另一台机器复测，排除本机防火墙。
3. **执行环境**：`rokae_sdk_run.sh` 默认只在 Linux 上跑得了，但 Windows 侧可以配通（已实测）。

   ```
   SDK_DIR="${ZMAX_SDK_DIR:-/home/ubuntu/zmax/zmax_data/rokae_sdk}"
   exec sudo docker run --rm --network host ... "$IMAGE" python3 "/repo/$SCRIPT"
   ```

   SDK 是 `xcoresdk_python.cpython-310-x86_64-linux-gnu.so`，所以**必须跑在 Linux 容器里**；
   但这不等于必须在 Linux 主机上 —— Docker Desktop 的 WSL2 后端就够，`--network host`
   实测容器能直连 `192.168.23.160`。缺 SDK 时脚本 `exit 2` 打印「⛔ 找不到 SDK」。

   Windows 侧要打通需三处适配：

   ```bash
   # ① SDK 副本（对端有现成的，24MB，tar 压完 6.4MB）
   #    对端: cd <工程>/zmax_data && tar -czf /tmp/rokae_sdk.tgz rokae_sdk
   #    本机: sftp get 后 tar -xzf 到 D:/ZMAX/zmax_data/
   docker pull ros:humble-ros-base          # ② 镜像，约 1.16GB，脚本里硬编码这个 tag
   ```

   ```bash
   # ③ 脚本适配：SDK 路径 + sudo 实测
   if [ -d /d/ZMAX/zmax_data/rokae_sdk/xcoresdk_python ]; then
     SDK_DIR="${ZMAX_SDK_DIR:-/d/ZMAX/zmax_data/rokae_sdk}"
   else
     SDK_DIR="${ZMAX_SDK_DIR:-/home/ubuntu/zmax/zmax_data/rokae_sdk}"
   fi
   SUDO=""
   command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null && SUDO="sudo"
   exec $SUDO docker run --rm --network host ...
   ```

   **`command -v sudo` 在 Windows 11 上会命中系统自带的 `sudo.exe`（默认禁用）**，
   只看有没有等于白看；不实测就报「已在此计算机上禁用 Sudo」，整个脚本一行没跑。

   验证阶梯（前两步都不动机器人，别跳）：

   ```bash
   bash tools/rokae_sdk_run.sh state                          # 位姿/关节/ec=success
   bash tools/rokae_sdk_run.sh move-rel --dx 0 --dy 0 --dz 0   # 零位移，回 PASS
   ```

   `move-rel` 零位移时日志应出现：起始 TCP 与 `8793/pose` 的 `endInRef` **逐位一致**、
  回读误差 0、`moveReset`/`moveAppend`/`moveStart` 三个 ec 全 0、结论 `PASS · Δ=0mm · 报警无新增`。
   三条齐了才让用户在页面上点真移动。

## 从 Windows 服务里调 bash（三道坎）

服务进程（`tcp_ar_server.py` 之类）用 `subprocess` 调 `bash tools/xxx.sh` 时，
「同一句命令，交互 shell 里能跑、服务里跑不动」基本都是这三件事之一，
而且每一条都伪装成不同症状，容易各自误判成"脚本坏了""孤儿进程没救""代码有问题"。

### ① PATH 命中的是 WSL 的 bash，不是 git-bash

`C:\Windows\System32\bash.exe` 与 `WindowsApps\bash.exe` 都是 WSL 入口。WSL 里没有 `/d/ZMAX`；
发行版 vhdx 丢失时返回的是 UTF-16 编码的
`Wsl/Service/CreateInstance/MountDisk/HCS/ERROR_PATH_NOT_FOUND`，直接看是一屏乱码。
在 Hermes 的 shell 里测能过，是因为 git-bash 排在 PATH 前面 —— 换成服务或
`Start-Process` 启动，顺序就变了。

```python
def _find_bash():
    """显式挑 git-bash: ZMAX_BASH > 独立安装路径 > PATH 里非 system32/WindowsApps 的。"""
    cands = [os.environ.get("ZMAX_BASH") or "",
             r"C:\Program Files\Git\bin\bash.exe",
             r"C:\Program Files\Git\usr\bin\bash.exe"]
    for d in (os.environ.get("PATH") or "").split(os.pathsep):
        low = (d or "").lower()
        if d and "system32" not in low and "windowsapps" not in low:
            cands.append(os.path.join(d, "bash.exe"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return "bash"
```

**别把 git-bash 的 `usr/bin` 复制到工程目录当"自带 bash"。** 试过：bash 起得来，
但它按安装根推导 MSYS 挂载表，`/d` 不再是 D 盘，脚本一律 `No such file or directory`，
还多一句 `warning: could not find /tmp`。要长期稳定就装独立 Git for Windows 到
`C:\Program Files\Git`（`_find_bash` 已优先找那里）；靠 Hermes 自带那份迟早因升级失效。

### ② Windows 路径喂给 bash，`set -e` 会静默退出

`os.path.join(REPO, "tools", "x.sh")` 得到 `D:\ZMAX\tools\x.sh`。bash 里
`dirname "$0"` → `D:\ZMAX\tools`，`cd` 失败，`set -euo pipefail` 直接退出，
**stdout/stderr 全空**，上层只看到 `rc=2`（看起来和"找不到 SDK"一模一样，其实一行都没跑）。

```python
def _msys_path(p):
    p = (p or "").replace("\\", "/")
    if len(p) > 2 and p[1] == ":" and p[2] == "/":
        return "/" + p[0].lower() + "/" + p[3:]
    return p
```

拼的是「`/` + 盘符 + `/` + 余下」，少那个斜杠会得到 `/dZMAX/...`，同样是找不到文件。

### ③ `text=True` 用 GBK 解码，把返回值吃掉

中文 Windows 上 `subprocess.run(..., capture_output=True, text=True)` 按系统 ANSI(GBK) 解码，
脚本输出是 UTF-8（含中文日志）⇒ 读取线程抛
`UnicodeDecodeError: 'gbk' codec can't decode byte ...`。`rc` 仍会正常返回，
但 `stdout` 丢了，上层 `json.loads` 解析不到 ⇒ 返回里 `script: null`、页面只显示 `ok:false`，
而脚本其实已经成功执行完（移动指令可能已经下发）。一律补：

```python
subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=120,
               encoding="utf-8", errors="replace")
```

### 验证顺序

1. `bash -n tools/x.sh` —— 纯语法，不碰环境
2. 命令行直跑脚本的只读子命令（`state`）—— 证明 SDK/容器本身没问题
3. **通过 HTTP 端点发 `{"dx": 0.0001}`** —— 只有这步能证明服务进程用的是对的 bash、
   路径和编码。`dry:true` 不算数（在 handler 里就 return 了）。

## 僵尸状态堵队

`zmax_data/rokae_sdk/traj_step_state.json` 里 `running: true` 而对应 pid 已死时，
`/api/arm/step_traj` 会一直判「上一轮真机逐点还在跑」并拒绝下发。
判活看 pid 是否真在（`kill -0` 之外还要排 `Z` 僵尸态），不要只信 `running` 字段。
清僵尸：把状态文件改成 `running: false, pid: 0`。

## 排障顺序

先 `/health` 或 `/station/status` 定性（真实数据，不猜），再按上面的闸一层层往下查。
每层都有独立的可观测判据，跳过任何一层都会把"硬件没开"误判成"软件有 bug"。
