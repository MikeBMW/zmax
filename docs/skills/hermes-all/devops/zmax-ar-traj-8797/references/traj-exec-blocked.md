# 执行轨迹被拦/中途停住: 分诊表与配方

用于 8797 页面『▶ 执行轨迹』点了之后: 一步没动 · 走一半停住 · 停在目标上方不下来。
一律先取证据再改代码, 现场描述("没执行"/"不下降"/"停住了")本身不区分故障类型。

## 0. 三样取证 (一次跑完)

```bash
cd /home/ubuntu/zmax
date +%H:%M:%S
curl -s http://127.0.0.1:8797/api/traj/exec/state          # phase / blocked_by / seg_i / plan_age
python3 -c "import json,time;d=json.load(open('zmax_data/rokae_sdk/tcp_out/latest.json'));\
print('age %.1fs'%(time.time()-d['ts']), [round(d['x']*1000,1),round(d['y']*1000,1),round(d['z']*1000,1)])"
stat -c '%y %n' zmax_data/runtime/traj/planned_traj.json   # 30 分钟过期, 过期直接重规划
curl -s --max-time 8 http://127.0.0.1:39071/status | head -c 200   # 空 = 隧道僵尸
ssh orin 'curl -s --max-time 5 http://127.0.0.1:39061/status'       # endInRef / jointVel 真值
```

`latest.json` 的 `x/y/z` 是**米**; 距上次更新超过 120s 基本可判中继停更。

## 1. 分诊表

| 现象 | state | 大概率原因 | 处置 |
|---|---|---|---|
| 一步没动 | `idle` / 无记录 | 按钮没发请求(confirm 被拦)、规划过期、起点闸、授权窗过期 | 看页面横幅原文; `plan_age<30min`; 起点闸报差值; 重新授权 |
| 一步没动 | 有 `拒绝:` 日志 | `位姿读不到(直读失败且常驻缓存过期)` | 先修位姿链(下节), 别动轨迹 |
| 走一半停住 | `blocked` · `起点已变 Nmm` | 起点复核拿**整条轨迹起点**比当前位姿 | 重规划剩余段(起点=当前真值) |
| 走完没停/过冲 | `running` 不收敛 | 段长 >90mm 被控制器静默丢弃后再补 | 拆短段, 单段 ≤90mm |
| 页面说成功但臂不动 | `delegated` | `exec_by.json` 指向执行链外的机器 | 改回 `{"by":"local"}` |

## 2. 「起点已变」机制 (实测)

- 段表一次性写 N 行 FIFO; 臂按段表走到终点上方后, 执行器复核 `当前 TCP vs plan 起点` → 差值 = 它自己走过的距离。
- 实测: 起点 (347,353,260) → 当前位置 (647,206,300), 三维距离 336.4mm, `blocked_by` 恰好 `起点已变 336.4mm`;
  后两段(下降到 230 / 172)从未下发, `jointVel` 全 0。
- 判据: 拿 `planned_traj.json` 的 `start_mm` 与当前真值算距离, 与 `blocked_by` 数字吻合 ⇒ 复核口径问题,
  **不是**碰撞、不是控制器拒、也不是轨迹算错。

## 3. 止血: 只规划剩余位移(起点 = 当前真值)

```python
import sys, json, time, shutil
sys.path.insert(0, "tools"); import traj_from_named as T
T.LIMIT = 70.0                                  # < 剩余距离, 避免单段过长
rec = T.build_from_points([[0.647,0.206,0.300], [0.647,0.206,0.172]],
                          "visual", 5.0, "下降 · 目标上方(z172)", "手工")
assert rec["precheck"]["ok"] and 1 <= rec["n_seg"] <= 24
p = "zmax_data/runtime/traj/planned_traj.json"
shutil.copy(p, "/home/ubuntu/.zmax/planned_traj.json.bak-%s" % time.strftime("%H%M%S"))
json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
```

- 起点闸天然过(起点就是当前位姿); 预检仍要过 20mm 净空 —— 实测 172mm 处最差净空 21.9mm,
  而 168mm 处只有 17.9mm 会被判 FAIL, 所以"上方 5cm"落到 172 才可执行。
- 改完提醒用户**重新授权**(`zmax_data/ctl_auth.json` 的 `until` 过期后一切执行都拒, 而拒绝理由只在小字里)。
- 治本方向: 起点复核改成按"当前段起点"比, 或在预发后按段增量更新复核基准; 改完必须回归一条多段轨迹
  (至少 3 段) 从起点走到末段仍继续下发。

## 4. 位姿链是执行的前置闸

```
Orin 39061 (SDK 桥) → 本机 39071 (ssh -L 隧道) → zmax-pose-relay → zmax_data/rokae_sdk/tcp_out/latest.json
```

- `l2_daemon` 只认 `latest.json` 龄 <10s; 龄大 → 直读 ROS → 失败即 `拒绝: 位姿读不到`。
- 隧道僵尸: `ss -ltnp` 有监听, `curl 39071/status` 回空。判活只认响应体。
- `zmax-orin-legs` 用老跳板 `orin-ecs` 时主进程 exit 255 并卡在 `start-pre`(等端口释放), 重启它会把 39071 与
  18792 一起弄掉 —— 换网络模式后要先把 ExecStart 的 Host 改对。
- 修完的判据: 执行器日志里自己打出的 TCP 真值 + 龄 `0.0s`(不是只看 relay 的 age)。
