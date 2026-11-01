# 规划跨机链路 (MoveIt → DDS ss_plan → 550C 执行) 的断点清单

链路全景:
```
MoveIt(容器 zmax-moveit, plan-only) → live_plan.jsonl → zmax-dds-ss(ss_daemon.pub_plan)
  → DDS zmax/ss_plan → ws_bridge --role hub --up ss_plan → wss bus
  → ws_bridge --role edge --down ss_plan(550C) → 550C 本地 DDS
  → zmax-plan-exec-550c(订阅 ss_plan) → Orin SDK 桥 192.168.23.66:39061 → 控制器
```
每一段都有自己的闸, **每段都要单独取证**, 不能因为后一段通就假设前一段通。

## 五个实测断点(按排查顺序)

### ① 容器根本没跑
`sudo docker ps -a | grep moveit` → `Exited (137) 8 days ago`。
**137 默认会被当成 OOM, 但先看 `OOMKilled` 字段**: `sudo docker inspect <ct> --format '{{.State.OOMKilled}}'`
实测 OOMKilled=false ⇒ 是被人/脚本 stop 的, 不是内存打爆。别先去调内存。
恢复: `bash tools/moveit_live_up.sh up`(自带 move_group 就绪等待 + 容器内规划器 + 宿主机请求器 + 重启 dds 守护)。
验收: 容器日志出现 `✓ N 关节路点 / N TCP 路点 · 终点误差 x mm`, n_points 应为几十到上百(平滑轨迹), 不是 1~4。

### ② PLAN_DIR 默认路径与实际写入路径不一致(最隐蔽)
`tools/dds/ss_daemon.py`:
```python
PLAN_DIR = os.environ.get("SS_PLAN_DIR", os.path.join(HOME, "zmax_moveit_plan"))
```
而 `moveit_live_up.sh` 把规划写到 `$REPO/zmax_data/runtime/moveit_plan/`。
⇒ `read_plan()` 恒返回 None ⇒ `pub_plan()` 走 `_pub_plan_vff()` 分支, **发的是仿真 v_ff 位姿, 却在页面上看着像"有规划"**。
取证(一条命令定性):
```python
import sys; sys.path.insert(0,'tools/dds'); import ss_daemon as S, os
print(S.PLAN_FILE, os.path.isfile(S.PLAN_FILE), S.read_plan()[0] is not None)
```
修: drop-in 写 `Environment=SS_PLAN_DIR=<实际目录>`, 不改代码。

### ③ 产品档位 topics=none 把整条 DDS 关掉
`config/platform/zmax_product.json` 的 `dev_profile.topics`: 550A=core · 550B=all · **550C=none(comm=shm)**。
`allowed(topic)` 里 `if _zp.topics_mode()=="none": return False` ⇒ 550C 档下**一个序列化 topic 都不发**。
但规划**必须跨机**(本机 MoveIt → 550C 执行), 共享内存只在本机有效 ⇒ 这是"收窄原则"唯一必须破例的地方。
落地方式(只开一个 topic, 默认行为不变):
```python
if topic == "ss_plan" and os.environ.get("ZMAX_SS_PLAN_ALWAYS") == "1":
    return True
if _zp.topics_mode() == "none":
    return False
```
+ drop-in `Environment=ZMAX_SS_PLAN_ALWAYS=1`。
验收: `zmax_data/dataspace/live.json` 的 `topics.ss_plan`: count 从 0 变成持续增长, matched_pubs≥1, lamp=green, age≈0.1s。

### ④ edge 方向缺 --down, 只 up 不拉
550C `zmax-ws-bridge.service` 的 ExecStart 只有 `--role edge --src 550C --max-hz 10`, **没有 --down**。
`--up` = 把本地 DDS 推到 bus; `--down <topic>` = 从 bus 拉下来写进本地 DDS。规划要看的是后者。
症状: edge 日志 `↓ss_plan:0(写0,缺0)` 一直不动, 而 hub 侧 `↑ss_plan:8000+` 在涨。
临时验证(不动 systemd): `setsid nohup env ZMAX_WS_BUS_URL=... ZMAX_WS_BUS_TOKEN=... python tools/dds/ws_bridge.py --role edge --down ss_plan --up - --src 550C-plan --max-hz 10 > log 2>&1 &`
日志应出现 `✅ 下行配对 ss_plan`。

### ⑤ 两端 bus 入口不是同一个后端
今天实测: 本机 hub → `wss://datadrive.world/ws/bus/`(443) · 550C edge → `ws://192.168.23.66:39064/`(Orin 转发 → ECS:39064)。
可达性: 本机→ECS:39064 公网 **Timeout**(ufw 只开 22/80/443/22022) · 550C→datadrive.world **000**(产线无外网)。
⇒ 只能在 ECS 侧把 443 的 `/ws/bus/` 与 39064 对齐(nginx 反代到 39064, 或 39064 面向公网)。
**判断两端是否同一后端的最快办法**: 一端推(`↑topic:N` 在涨)、另一端 `↓topic:0` 不动 ⇒ 不同后端, 不是网络问题。

## 执行侧的独立坑(与本链路无关, 但会混在一起报"不执行")

### 起点闸 "起点已变 X mm" = 多段轨迹中途必触发
`l2_daemon` 的起点复核拿**整条轨迹起点(plan.tcp0_mm)**比当前 TCP。
一次性预发 N 段时, 臂被段表正常带到几百 mm 之外 ⇒ 复核判"有人搬了机器人" ⇒ 中止余段。
实测: 9 段轨迹走到第 7 段(647,206,300)后停, blocked_by="起点已变 336.4mm", 而 336.4 正好等于 起点→当前位置 的距离。
⇒ 现场表现是"走到一半停了", 不是轨迹错。绕法: 从**当前位置**重新规划余下段(起点=当前真值), 或把起点复核改成按段起点判。

### moveStart 被拒 → 先查机器人状态, 别查轨迹
`curl http://127.0.0.1:39071/status` 的 `operateMode` / `powerState`:
- `OperateMode.manual` / `PowerState.off` ⇒ moveStart 一定被拒(实测日志: `🚚 bridge 腿拒发: moveStart 报错`)。
- 必须先上电(servo on) + 切 automatic, 才谈执行。
用 `dry:true` 调 `/move_pose` 可**只算不下发**验证目标点参数是否被接受(delta_mm 合理即轨迹没问题), 安全且能区分"轨迹错"与"状态错"。

## 取证口径
- 规划真伪: `live_plan.jsonl` 末行的 `n_points` / `plan_code` / `gate_same_source`(FK 与真机 TCP 差 ≤5mm 算同源)
- 发布真伪: `zmax_data/dataspace/live.json` 的 ss_plan count/hz/matched_pubs/lamp
- 远端接收: 550C `zmax_data/runtime/plan/plan_exec_seen.json`(收到过哪些 plan_id) + `plan_exec_550c.jsonl`(逐段残差)
- 执行真伪: 桥 `/status` 的 `endInRef`(50Hz 真值) + `jointVel` 全 0 才算停稳
