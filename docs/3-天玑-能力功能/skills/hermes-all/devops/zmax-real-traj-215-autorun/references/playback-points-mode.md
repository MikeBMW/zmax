# 215 点「回放模式」: 逐点勾停 + 只读记录示教

老倪要的「回到原来的 215 点回放」= 控制器自己做关节插补的 MoveAbsJ 逐点/分块, 不是 RT 指令流。
他要的是**每个点都能看、能勾选是否停 1 秒**, 不是只给几个具名停点。

## 1. 数据与接口

| 用途 | 位置 |
|---|---|
| 点位真源(关节/TCP/名称) | API `GET /api/pts` → `{ok,n,n_stop,pts:[{i,j[6deg],tcp[3mm],t,stop,name}]}` |
| 勾选结果(唯一可写) | `zmax_data/rokae_sdk/point_stops.json` → `{"<i>":{"stop":true,"name":"…"}}` |
| 写入接口 | `POST /api/pts {i, stop:true/false, name?}`; `name:""` = 清名; 回 `{ok,i,stop,n_stop}` |
| 页面 | `tools/web/points.html`, 由 `se3_geom_server.py` 在 `/points` 出 |

- 帧号 `i` 一律 0 基, 与 `frames[i]` 同口径; 页面第一列就写 `#i`, 报数也写 `#i`。
- `j` 输出用**度**(两位), `tcp` 用**毫米**(一位), `t` 用秒 —— 现场是拿着这一列数字核对示教器的。

## 2. 页面定式(老倪验收口径)

- 表头 sticky, 215 行一次全出(别虚拟化: 他要用浏览器 Ctrl-F 找点)。
- 每行: `#i | J1..J6 | X Y Z | t | [☐停] | 名称`; 勾选即时 POST, 不等保存按钮。
- 顶部常驻: 共 N 点 · **已标记停止 M 点** · 当前 `#i`; 右侧两个按钮「滚到当前点」「清空标记」。
- 当前行高亮跟 `/api/se3` 的 `nearest.i`, 1s 轮询; 高亮只许一处, 且**只在行值变化时才改 DOM**,
  否则正在输入的框会被重绘打断。
- 行内输入框与复选框回写后要 readback 校验(尤其名字), 别假设 POST 成功。

## 3. 执行脚本 `tools/rokae/play_points.py`

```bash
ZMAX_PP_I0=0 ZMAX_PP_I1=215 ZMAX_PP_SPEED=100 ZMAX_PP_DWELL=1000 \
ZMAX_PP_CHUNK=24 ZMAX_PP_SLOW="21-35:15,93-108:15" \
  bash tools/rokae_sdk_run.sh --script play_points.py
```

- **分块**: 默认 8 点/块(实测 24 点/块 ≈3.1 s/点最省), 遇勾选停点必以它收块 ⇒ 保证停在点上。
- **接触段低速区 `ZMAX_PP_SLOW="a-b:speed,..."`**: 区内**一次只走 1 点**且降速; 这是纯位置回放唯一能减伤的手段。
- **到位判据**: `max|cmd−meas| ≤ TOL_DEG(0.6°)` 且 `op=idle`; 块超时按 `n_pts` 放大; 失败即停不重发。
- 每块打一行 JSON(`i0/i1/n/ok/err_deg/secs/speed/stop/name`) + `dwell` 行, 跑完 `done` 行带末态关节。
- 🔴 **`ZMAX_PP_*` 不加进 `tools/rokae_sdk_run.sh` 的 `-e` 白名单就永远到不了容器** —— 命令行看着设了
  `I1=12`, 日志 `pre` 行却回 `i1:215`。新加 env 一律先 `grep -c ZMAX_PP_ tools/rokae_sdk_run.sh` 再信它。
- 🔴 `moveAppend` 的 tag 写成 `"pp%d" % (int(t0*1000) % 100000)` —— 少了外层括号会先拼字符串再取模,
  抛 `TypeError: not all arguments converted during string formatting`, 整块零下发。

## 4. 「我重新走一遍, 你看着, 记录」= 只读录制

```bash
ZMAX_REC_RATE=30 ZMAX_REC_SECS=0 bash tools/rokae_sdk_run.sh --script record_manual.py
# 收尾: sudo docker kill --signal=TERM <容器名>  ← 脚本 SIGTERM handler 会把 jsonl 转成同构 json
```

- 纯读 `jointPos` + `cartPosture`, 30Hz, **不发任何运动指令**; 每 10s 打一行 tick(帧数/关节/TCP) 让他确认在录。
- 落 `zmax_data/rokae_sdk/rec/rec_manual_<ts>.jsonl`(逐帧 `t/j/p/rpy`), 收尾转 `n_frames/dur_s/frames[]` 同构 json,
  `p` 用**米**(与 `real_traj_joints.json` 一致)。
- 🔴 **`cartPosture` 返回的就是米**: 转换时再除 1000 会把 2493mm 的行程算成 2.5mm(实测踩过)。
  统一 `if max(|p|) > 20: p /= 1000`。
- 🔴 容器内写出的文件是 **root 所有** ⇒ 宿主要改写先 `sudo chown -R ubuntu:ubuntu <dir>`。
- 收尾报告要给的数: 帧数/时长/采样率 · TCP 总行程 · 包络 X/Y/Z · **运动段切分**(相邻位移 >0.5mm 视为在动,
  段端点就是他的停点) · 每段行程与**峰值关节速度**。峰值超过旧轨迹名义速度时要提前说明(做点位表按实测反算时间轴)。
- 与旧轨迹比对时给「差在哪」而不是「不一样」: 例如插入后下压量 13mm vs 旧 38mm —— 这一句就能解释上一次为什么撞。

## 5. 把一次示教重走变成可回放点位表

- 段端点(停顿处)自动标 `stop:true`, 其余按行程等间隔重采样(目标 0.2~0.3s/点), 写 `point_stops.json` 让他在页面上勾。
- 若重采样后相邻点关节跳变 >30°, 保持原样并在页面上标出来 —— 控制器在 `MAX_JUMP_DEG` 处会拆段执行,
  不要为了让数据「好看」去插中间姿态。
- 表建好后先只跑空走段验证, 再谈接触段。

## 6. 多套点表共存 (`?set=`)

- 一套表 = 三个文件 + 一个非参数: `real_traj_joints_<set>.json` · `point_stops_<set>.json` ·
  `traj_phase_<set>.json`/`traj_hopf_<set>.json`/`sectors_<set>.json`; `se3_geom_server.py` 里 `PTS_SETS` 登记,
  默认 `ZMAX_SE3_SET=v2`, `?set=215` 回旧表。**旧表原样保留** —— 现场会拿它对比"上次为什么撞"。
- 页面两份都留着: `/points`(旧) 与 `/points?set=v2`(新); 只报一个会被问"那另一份呢"。
- 新表生成口径: 段端点标 `stop:true`, 中间**等弧长**重采样(实测 8mm/点 ⇒ 2500mm 行程 239 点), 不要等时间采样
  —— 匀速假设不成立(实测某段峰值 99.2°/s)。

## 7. 🔴 状态列表与回放停点是**同一份** `point_stops_*.json`

`se3_geom_server.py` 的 `PHASES` 由该文件的停点顺序生成 ⇒ **改状态名/合并状态 = 改停点数量 = 改回放节拍**。
现场只说"状态不对"时, 一句话要同时交代两件事: 状态行从 N 变 M, 回放就少/多 M-N 次 1s 停顿。改前先备份
`point_stops_v2.json` 成 `.bak-<N>states.json`, 报错能一键退回。

归类按**几何**判, 不按文字推断:
- 判"到底"= 该段 z 的最小值那一帧(实测 #128 z=188 是全程孔内最低), "第一次到达"就是它 ⇒ 用户口述
  "插入之后第一次到底就是工作点"落到这一帧上。
- 插入过程中间的"抽出→再插→下压→原位微调"是**同一次插装动作的子动作**, 不单独成状态;
  单列会让状态表出现 `插入 → 退出 → 再进 → 工作点` 这种在孔里来回的假行程。
- 合并后 15 状态 → 11 状态(实测): 抓取点 → 抬升 → 扫码点 → 对位点 → 对位微进 → 插入 → **工作点** →
  离开 → 废料点 → 回程 → 初始点。
- 改完必做帧抽样核对(不是看第一行): `#100→插入` `#120/#129→工作点` `#150→离开`, 且全页只有一个 `.cur` 框。

## 8. 跑之前把"跟显"确认了, 跑的时候只报进度

- 三维臂跟真机**默认就在跟**: `MIRROR.on=true` 每 100ms 拉 `/api/tcp` 写 `PREV.q`。判据 = 控制台比
  `PREV.q` 与 `/api/tcp` 的 `joints` **逐位相等**(或差 ≤0.02 rad = 正常滞后); `RTRAJ_FOLLOW.on` 只是 UI 标志,
  它 false **不代表**没在跟 —— 别据此报"没跟随"、也别为了它去反复点按钮。
- 起跑前臂未必站在 `I0` 那一帧(上一轮可能停在半路/被闸停): 报一句"当前 TCP → 表首点还有多少 mm",
  控制器会先做一次关节空间直跳到首点, 那段不在录制路径上。
- 全程基线(239 点·speed=100·24 点/块·接触段 `91-133:15`·每停点 1s): **288.57s / 56 块 / 每点 0.106~0.130°**,
  末态 TCP `664.9,-29.1,295.7` 与表首点差 0.23°。11 停点的版本约 **284s**。
- 起跑命令照抄(env 全走 `ZMAX_PP_*`, 缺一不可):
```bash
ZMAX_PP_TRAJ=/sdk/real_traj_joints_v2.json ZMAX_PP_STOPS=/sdk/point_stops_v2.json \
ZMAX_PP_I0=0 ZMAX_PP_I1=239 ZMAX_PP_SPEED=100 ZMAX_PP_DWELL=1000 ZMAX_PP_CHUNK=24 \
ZMAX_PP_SLOW="91-133:15" timeout 1800 bash tools/rokae_sdk_run.sh --script play_points.py
```
- 汇报进度只给两个数: 当前 TCP 与**表上最近第几点**(逐点算欧氏距离取最小, 一行 `nearest #N …mm`),
  比"跑了百分之几"可核; 停止/异常一律先报"哪一个停点、误差多少、有没有 abort"。
