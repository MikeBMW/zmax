# 「改完用户看不到」/ 数据空间缺 Tx / mm/s 口径 / v_ff 能不能算位姿

## 1. 用户连说两次「还是没有」→ 先查是不是两个控制台并存（血泪，代价 = 3 轮无效改动）

- 症状：你每次重启都起了新 pid、代码确实改了，用户仍说看不到；`wmctrl -l -p` 里他的窗口属于**另一个 pid**。
- 根因：实例识别只匹配 `gui/studio.py`，漏掉**以 cwd=tools/gui 用裸 `studio.py` 启动**的实例
  （VSCode F5 / 手工启动 / 守护拉起）⇒ 清理永远留一个旧进程，用户盯的是旧代码。
- 识别（别只信 `pgrep -f studio.py`）：
  ```bash
  wmctrl -l -p | grep -i zmax          # 窗口 → pid（用户眼睛落点就是这里的 pid）
  readlink /proc/<pid>/cwd             # 确认它是控制台而不是别的进程
  ```
- 修法：识别条件 = cmdline 含 `studio.py` **且** comm=python* **且** cwd ∈ {工程根, 工程根/tools/gui}；改完 `bash -n` 验。
- 副作用：两个控制台各 1.3~1.8GB 且都在渲染 ⇒ 同时是「机器变慢」的元凶（用户会把两件事一起报）。

## 2. 数据空间 Trace 里「没有某个 Tx 节点」= 三道门，任一不过就静默丢行（无日志）

按顺序核，每道都能一条命令看出来：

1. **层**：`src/lerobot/engineering/nodes/by_level.py` 的 `LEVELS_INDEX` 缺该 `node_id` ⇒ 工程库把它算成 `meta`
   ⇒ `attribution.layer_of()` 返回 `SYS` ⇒ Trace 不收（SYS 不入表）。补进对应层（执行收口类归 L2）。
2. **Rx**：`attribution.rx_of()` 里 `sstrace.*` 曾硬 `return "—"`（当时画布确实没连线），而
   `show_in_l2_link()` 要求 **Tx、Rx 都是 L2** ⇒ Rx 为 "—" 整行丢。画布已有真连线后应按 `_rule(key)` 的 node
   取 `db.node_rows()` 的 `outs` 下游名字。
3. **白名单**：`src/lerobot/middleware/signal_policy.py` 的 `NODE_ALLOW` 没登记的节点，`decide()` 返回 None 再丢一次；
   另有 `MAX_PER_NODE=10` / `MAX_TOTAL=100` 两道量限（超了按行序砍）。

**取证不要靠推理**：离屏构造真控件再读表格，两种 Trace 模式都试。
```python
os.environ["QT_QPA_PLATFORM"]="offscreen"
w = dds_canoe.build_view(None); w._fill_trace_fixed(force=True)
tb = w.tb                      # 列: 0 Time 1 Layer 2 Signal 3 Value 4 Unit 5 Phys 6 Type 7 Tx 8 Rx 9 QoS 10 Hz
print([(i, tb.item(i,7).text()) for i in range(tb.rowCount())])
```
判据：`tools/verify_signal_policy.py` 7 项全绿；给用户的证据用离屏 `tb.grab()` 存 PNG（**不是**他的屏幕，要说清楚）。

## 3. 速度信号统一 mm/s，键后缀 `_mms`（字面禁止 `mps`）

- 生产端 **只转一次**（`ss_dreamview.publish_trace_live` / `ss_fw_trace_pub`：值 ×1000 + 键 `_mps`→`_mms`）。
- 显示层 `canoe_graphic` 的旧逻辑是「键名以 `_mps` 结尾就 ×1000」⇒ **必须同步改**，否则二次放大 1000 倍。
- 消费端（`ss_daemon` 的 v_cap、`gravity_table`）显式 `/1000` 回到 m/s，DDS 契约不跟着改。
- 同步处：`signal_en.py` 映射、`config/topics/scene_tags.json`（软链到 `data/database/zmax/sources/config`，不在 git 里）、`signals.db` 旧行。

## 4. 「由 v_ff 算位姿」的口径（实测，785 帧 / 80Hz / dt=12.5ms）

- 动作向量只有 4 维 = vx,vy,vz + 夹爪 ⇒ **位置可积分，姿态算不出来**（没有角速度）。
- 积分误差：直接用 `u_ff` 平均 23.4mm / 最大 36.8mm；用执行后的 `u_limit` 平均 5.0mm / 最大 12.9mm
- 最优缩放 k≈0.986 ⇒ 单位就是 m/s、dt 就是帧间隔，没有隐藏系数；误差小是因为真值=执行结果，u_limit 才是执行量。
- 姿态必须另取：真机 `tcp_out/latest.json`（50Hz，含 rx/ry/rz）或规划器给；`SSPlan` 只镜像 MoveIt 结果，**不由速度反推位姿**。
- 插拔 episode 里光模块姿态 = 单位四元数（`meta.qpos[12:16]`），3D 只实现绕 Z 的 yaw（`_box_mesh_yaw`），
  且 `tr["peg_yaw"]` 引擎不产 ⇒ 画面恒不转不俯仰，这与真值一致（不是渲染漏了）。要姿态需：落盘 rpy/quat + 完整 4×4 变换 + 动作扩到含角速度。

## 5. 四层速度里哪层是模型

`v_ff`（前馈加速器：非插入段 `accel.forward` 蒸馏 MLP / 插入段 `analytic_forward` 解析）是唯一模型层；
`u_fb = clip(0.5·残差EMA)`、`u = u_ff + k_fb·u_fb`+阶段限速、`u_limit = saturate(u, ±0.6)` 全是确定性公式。
INTACT 只在常驻 `ss_engine_loop` 里跑（`SS_INTACT=1` 是那个进程的环境变量），**不自动进控制台的场景回放**。
