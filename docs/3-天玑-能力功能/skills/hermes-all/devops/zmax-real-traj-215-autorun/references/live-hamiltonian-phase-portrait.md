# 跑批时看实时哈密顿量 / 相空间 (H = K + U)

用户跑 215 点时盯着「相空间」看 H，是最容易报错的一类需求：数据链有三层，任一层断了都比的是旧数或别人的数。

## 一、真相链（少一环就报错）

```
ss_engine_loop.py::emit()            每周期算一次能量场 → atomic 写 zmax_data/ss_live/hamiltonian.json
  └─ lerobot.manifold.state_space_energy.live_energy(root, cache)   ← 算式唯一依据
       ├─ 输入 zmax_data/ss_live/trace_live.json  (末端_x/y/z · 光模块_x/y/z · ts · src)
       └─ 兜底 zmax_data/ss_live/chunk_latest.json 的 u（首帧没有上一帧时）
画布节点 ss_grav_h                    只算不下盘（注释写明“本节点再写同一份会互抢”）
tools/gui/phase_space.py  (面板)      只读 hamiltonian.json
```

- 判新鲜：`hamiltonian.json` 的 mtime 与**同目录** `trace_live.json / torque_live.json / action.json` 的 mtime 比。
  同目录在动、只有 hamiltonian 冻住 ⇒ 不是采集问题，是 `ss_engine_loop` 的 emit 挂了（`live_energy` 抛异常被 try 吞掉，不会写文件）。
  对着看 `/var/log/zmax-ss-engine.log` 最后一条 `周期 N` 的时间戳，与 hamiltonian 的 mtime **逐秒吻合**就是同一刻停的。
- 时钟回拨 8h 会让这一个 loop 看起来“活着但不动”（日志里 `hz_act=10000000.00Hz`，之后不再出行）。这时别去改算式。
- 想补 H 又**不动他的服务**：起一个只读侧车（1Hz 调 `live_energy`，仅在 hamiltonian 陈旧 >5s 时写、引擎恢复即让位），
  写 `writer` 字段标明来源。`ss_engine_loop` 属“重启须点名”的服务，别自行 restart。

## 二、陷阱：`trace_live.json` 可能根本是仿真

`trace_live.json` 的 `src` 字段会明确写来源。实测踩过：

```
src = "操作视频同源 episode (metaworld seed=0, 701 步, 终态 完成)"
末端 = [0.035, 0.611, 0.125] m      真机 TCP = [0.669, 0.196, 0.264] m   ⇒ 不是一个坐标系
```

- 用它算的 H / 相点是**仿真的**，与真机无关。报“实际哈密顿量”前必须先看 `src` 与坐标量级。
- 真机口径自己算（同算式，只换真值源）：`pos = tcp_out/latest.json`、`target = real_traj_joints.json frames[cursor-1].p`（米/毫米要逐帧判）、
  `ξ_e = target − pos`、`U = ½(k_lat(Δx²+Δy²) + k_ax·Δz²)`、`ξ = d(pos)/dt`、`K = ½m|v|²`、`H = K+U`。
  `mass_kg=3.643 · k_lat=80 · k_ax=400 · alpha=0.15` 都是 `state_space_energy` 的同一组默认值。

## 三、陷阱：面板视野钉死 ⇒ 「点不见了」

- 原 `_draw_portrait` 里 `setXRange(-75,75)` / `setYRange(-0.9,0.9)`。真机跑批实测 Θ 到 **±268mm（另一轮 −354mm）**、H 到 **26J**
  ⇒ 点被裁到框外，用户只会说“点怎么不见了”，不是没数据。
- 修法：`_autoscale(xs, ys, theta_mm, p, H, k, m)` —— 只在**点或尾迹要出框**时放大（留 15% 余量，并把等能椭圆半轴
  `1000·√(2H/k)` / `√(2mH)` 计入），不做每拍重设，免得用户手动缩放被抢；尾迹 400 → 2000 点才能装下“全过程”。
- `phase_space.py` 是进程内 import ⇒ 改完**重启控制台**才生效。他不重启又急着看时：另起一个独立窗口（pyqtgraph，自动缩放 + 全过程尾迹 +
  5 个停住点标菱形 + 每次采样落 jsonl），窗口用他控制台同一个 `DISPLAY`（从 `/proc/<studio-pid>/environ` 取 `DISPLAY` / `QT_QPA_PLATFORM`）。

## 四、为什么这张相图“不规律”——口径问题，不是机器人问题

现口径 `Θ = 目标z(当前游标帧) − 实测z`，`p = m·v_z`。实测一轮 215 点、294 个样本：

```
Θ 范围 −354…+262 mm · 相邻样本 |ΔΘ| P90 = 48mm · >30mm 占 21%   ⇒ 参考点在跳，不是状态在跳
|p| 中位 0.0086 kg·m/s · 5Hz 差分分辨率 0.0018                 ⇒ 纵轴基本是噪声
K/H 中位 0%（几乎全是势能）· H 上升样本 63%                      ⇒ 不耗散：能量来自参考移动
```

根因四条，报现场时按这个说：
1. 参考点按块跳（flow 档 12 点/块）⇒ 臂没动，Θ 已经跳到几百毫米；
2. 速度靠 5Hz relay 差分，真实 |v| 只有几十 mm/s ⇒ p 在 0.0x 量级；
3. `k_ax=400 N/m` 配 350mm 偏差 ⇒ U 到 26J，量级失衡；
4. 停住点（夹爪/AOI dwell）v=0 且参考不变 ⇒ 一堆重合点。

要画成真正的阻尼振子螺旋（ζ=0.786，Ḣ≤0），必须同时改三处：①固定参考（孔轴/目标点，不用“当前块目标”）
②高频或回归速度（Orin 50Hz tcp_pose，或 ≥0.4s 窗口差分）③跨块不连线 + 无量纲化（Θ/tol、p/p_ref、V=½‖z‖²）。
只改屏幕不动口径只会让图更好看，不会让 H 有物理意义。

## 五、速度源三级：0.5Hz relay → 20Hz 桥 → 关节速度×雅可比

| 源 | 速率 | 怎么读 | 何时用 |
|---|---|---|---|
| `tcp_out/latest.json`（官方 relay） | **0.50Hz**（相邻样本差 2.000s） | 读文件 | 只要“当前在哪”。`tools/orin_pose_relay.py` 的 `PERIOD = ZMAX_POSE_RELAY_HZ or 2.0`，别改它（下游唯一依据） |
| `http://127.0.0.1:39071/status`（relay 的上游本机桥） | 实测 **10~20Hz**，每次都是新样本 | `d["status"]` → `endInRef`(m/rad) · `jointPos` · `jointVel` · `flangeInBase` | 相图/速度/能量的标准做法：自己读、自己写独立 jsonl |
| 关节速度 + URDF 雅可比 | 与端点位姿**同帧** | `v_tcp = J(q)·q̇` | 要“瞬时速度”时首选；比位置差分干净，且不需要历史窗口 |

雅可比口径（`gui-venv311` 里没有 pinocchio，自写 4×4 链即可）：
- URDF `data/database/zmax/sources/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf`：6 个 revolute + `joint_tool0`(在 link6) + `joint_tool1`(偏移 `-0.0159/0.0183/0.2587` m)。
- 链校验（不是看代码，是比数）：`FK(q).tool0` 与桥 `flangeInBase` 差 ≤1.8mm、`FK(q).tool1` 与 `endInRef` 差 ≤2.9mm ⇒ 链对，余量是标定零点。
- 速度校验：运动中 `J·q̇` 的 z 分量 −18.7 mm/s vs 位置差分 −17.9 mm/s（差 5~10%）⇒ 可用。
- 🔴 **`jointVel` 会整帧为 0**（桥缓存帧，不是真静止）：解出的 `v=0` 必须判定并**退回位置差分**；不能“有 jointVel 就用、出错/为零就写 0”，否则整轮相点全压在 v=0 上（实测踩过：URDF 常量取错 → 雅可比抛异常被 try 吞成 0 → 8000 个样本全是 0）。
- 纵轴用 `p = m·v_z`（kg·m/s）比 `v_z` 规范：哈密顿力学的共轭对是 (z, p_z)，`H = p²/2m + m·g·z`；两者只差常数 m=3.643，换算 `p = 3.643·v_z(m/s)`（实测 p ∈ −0.133…+0.118、|p| P90 0.0715）。给现场报数时说清“同一张图，只是单位”。
- ✅ 以上链校验与速度对账已固化成脚本 `scripts/tcp_velocity_probe.py`（无 pinocchio 依赖）：
  `./gui-venv311/bin/python scripts/tcp_velocity_probe.py --watch 5` 一次打印两处位置差 + `J·q̇` vs 位置差分，
  开跑前用它确认“速度这一路是通的”，别到相图里才发现全是 0。

## 六、断点续走 / 中途停 —— 判活与停稳的实测定式

- 🔴 **8797 的 `/status` 读的是日志，会陈旧到“骗人”**：实测 `running=false · done=0 · 未跑过` 的同刻，执行器容器还在走（臂在轨迹中段）。
  判“真在跑”只能三件一起看：`pgrep -af 'arm_step_[t]raj'`、`sudo docker ps` 里有没有 humble 执行容器、桥的 `endInRef` 是否在变。
- **从停顿点续走**（不重跑全程、也不先 align）：读 `frames[i].j` 与真机 `jointPos` 逐帧算 `max|Δq|`，取最小者 =
  该点（实测停在 #81，差 0.11°），再 `POST {"n": 215-idx, "start": idx, "speed":100, "speed_mode":"flow"}`。
  轨迹有多处**姿态自交**（5° 内常出现 3~6 个候选），所以最近点只用来定 start；`{"align":true}` 会按它自己的 `_nearest` 选，可能选到自交的另一帧 ⇒ **能直接给 start 就别 align**。
- **停臂**（用户说“先停下/快停下”）：
  - 执行器是 `sudo docker run … python3 /repo/arm_step_traj.py`，属 root ⇒ 普通 `kill` 无效，必须 `sudo`；
  - 🔴 `pkill -f "arm_step_traj"` 会匹配到**你自己这条 shell**，把自己 SIGKILL 掉、后面的步骤全没跑 ⇒ 用区间写法 `pkill -9 -f "arm_step_[t]raj"`，或先 `pgrep` 拿 pid 再 kill；
  - `kill -TERM` 对容器内 python 常无效，用 `-9`；停完 `sudo docker ps` 应为 0，再 `endInRef` 连采 2~3s **位移 0.00mm** 才算停稳；
  - 报现场要带“停在哪”：TCP mm + 关节角 + `powerState/operateMode`。
- **采样侧车只许单写**：两个窗口同时 append 同一 jsonl 会把两条 JSON 拼成一行（实测 336 行里 1 行坏）；启动前先 `pgrep` 确认单实例，解析端遇到坏行要能拆 `}{` 修复并去重。

## 七、采样器定式（自己写一个也别踩）

- 定时器 5Hz 读 `latest.json` 会把**同一 ts 重复读到**：必须 `if ts <= prev_ts: return`，否则会把速度算成 0（p 恒 0，相点全挤在 p=0 轴上）。
- 速度用 **≥0.4s 窗口差分**（块内 goto 是冲刺式，单帧差分被采样抖动打成 0）。
- 每条样本记 `{ts, i, th_mm, p, H, K, U, tcp}` 落 jsonl —— 只有留档才能事后导 PNG / 复盘 / 换口径重算。
- 侧车本身要轻：5Hz 采样 + 2000 点重绘会抢 CPU，实测同一档位整轮从 2.26 s/点 变 2.74 s/点（485.9s → 589.1s）。
- 🔴 **从探针脚本拷函数进窗口脚本时，块引用的模块级常量不在块内**：只截 `def …` 那一段会把上面的 `URDF = …` 漏掉，
  `NameError` 被宽 `except` 吞掉后速度**静默恒 0**（当时 `qd_live=True` 而 `vz_jac=0.0`，看着像“关节没动”）。
  定式：拷完把该块用到的全局名逐个确认目标文件里有（`grep -n '<NAME> =' 目标文件`），再跑第一帧看速度是否非零。
- 🔴 **测量路径不许 `except: zeros`**：解算失败要退回备选估计量（雅可比失败 → 位置差分）并在样本里记来源，
  否则“0”会被当成真实静止写进结论，事后从数据里根本分不出是没动还是算挂了。

## 八、相图三件套：z-p / 末端三轴 / 六关节（问“为什么只画垂直速度”就照这套答）

- 只画 `(z, p_z)` 的理由只有一条：重力势 `U = m·g·z` 只依赖 z，哈密顿量的共轭对就是 `(z, p_z)`；x/y 在等高搬运时不改变 U。
- 代价要主动报，别等人问（一轮 520s / 4965 样本 / 9.5Hz 实测）：
  ```
  水平占 v² 的 67% · 垂直 33%      |v_xy| P90 25.7 · |v_z| P90 17.9 mm/s
  6% 样本 |v_z|<1 而水平 >16mm/s    ⇒ 在 z 相图上正好落在横线上，会被误读成“静止”
  行程 x 210…819 · y −512…411 · z 120…1001 mm
  ```
- **六关节 `(q_i, q̇_i)` 才是控制器口径**（MoveAbsJ 是逐关节走），出六联图 + 每关节四列：角度范围 / 峰值角速度 / P90 / 换向次数。
  换向次数直接回答“动作落在哪几个关节”：实测 J3 11 次、J4 10 次、J1 仅 5 次 ⇒ 取放集中在一个方位角内，瓶颈在 J3/J4/J6 的速度上限。
- 🔴 **关节角跨 180° 先验再当真**：实测 J4 −8…+247°，逐帧 `max|Δq|` >30° 的出现 **0 次** ⇒ 是真回转不是数据断裂。
  不先验就 unwrap，会把真实行程抹平；反过来把真断裂当行程，相图会出现一条不存在的长线。
- **不重跑也能出三轴/六关节图**：遥测 `zmax_data/ss_live/state_<YYYYMMDD>.jsonl`（`ss_remote_tap` 10Hz，字段
  `t / tcp / tcp_quat / jpos / jvel / ft`）按该轮跑批的 `ts` 窗口过滤，速度用 0.35s 最小二乘重算即可（实测 520s 窗口抽 4965 条）。
  它同时是“本轮到底动了几秒”的旁证 —— 比 recorder 的样本条数可靠。
- 被质疑口径时**不要重新论证**，直接给同一份数据的三种投影 + 每张一句话物理含义：
  z-p = 竖直机械能账本（H≈m·g·z，K 占比 <1%）· 三轴 = 行程使用谱与换向次数 · 六关节 = 控制器真状态与瓶颈关节。
