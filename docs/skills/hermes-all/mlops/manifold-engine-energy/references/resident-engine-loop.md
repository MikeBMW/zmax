# 流形引擎 · 常驻周期回路 (ManifoldEngine.step 每周期真调) — 2026-10-14

触发: 用户说「流形引擎是全系统的核心, 怎么只是调用一次呢」「常驻循环在周期性调」「周期输出在哪」。

## 先查事实 (别猜)
`ManifoldEngine.step()` 全仓库的调用点:
```
grep -rn "eng.step(\(" src/lerobot/engineering/nodes/library.py     # 画布节点「🧮 流形引擎」(≈5207)
grep -n "eng.step(" src/lerobot/manifold/manifold_engine.py          # 自检 823 / hom 演示 968
grep -n "ManifoldEngine(" tools/manifold_engine_bench.py              # bench (独立进程)
```
10Hz 的 `zmax-torque-bus` (tools/tdrive_bus.py) 每周期算的是 `T = M·(−∇Φ)` (metric_field), **不经过 step**
⇒ 引擎核心没有常驻回路。量性能上限: `step` ≈ 0.5~0.7 ms/步 (理论上限 ~1400Hz) ⇒ 10Hz 周期毫无压力。

## 架构 (照抄, 与扭矩链同构)
```
状态空间工程 ▶ 运行 → simulink_module._dump_ss_traj_true_source(tr)   ← 轨迹唯一依据落盘 (新增)
                     data/database/zmax/sources/canvas/ss_traj_last.json
        ↓ 读
 tools/ss_engine_loop.py run --hz 10   (systemd: zmax-ss-engine-loop.service, 日志 /var/log/zmax-ss-engine.log)
        每周期: eng.step(obs[idx], dt) → tap /dev/shm/zmax_ss_engine/engine_<scene>.jsonl (+ engine_latest.json)
        ↓ 读 tap 最后一行
 tools/dds/ss_daemon.py::read_engine/pub_engine (专用节拍线程, 主 tick 17~26s 挂不住) → DDS zmax/ss_engine
        ↓
 tools/dds_sub_ss_engine.py   (判据用: cycle 单调递增 = 回路真在跑)
 tools/verify_ss_engine_loop.py (16 项判据)
```
唯一依据跟随: 工程名/saved_at (zmax_space.proj) · 活跃任务 (config/ss_task_binding.json) · 主参数 M
(config/calib/zmax_manifold.json) **每 5s 重读**; 状态源优先级 `--state-file` > 工程轨迹唯一依据; 都没有 ⇒ 空转并明说 (不造状态)。

## 坑 (全实测踩过)
- 🔴 **建引擎时 `goal_point` 必须在早退之前设**: `build_engine()` 里 `if loaded: return …` 在前面时, 只把
  `eng.goal_point = eng.project(obs[-1])["p"]` 写在拟合分支 ⇒ 加载标定那条路 goal=None ⇒ `gradient_flow` 的
  **Φ≡0 / ‖∇Φ‖≡0** (表面"在跑", 实际没有势场, 动作是无目标下坠)。判据要断言 Φ 非恒 0。
- 🔴 **MODE_TOPICS 有三份**: `tools/dds/ss_daemon.py`(自带一份, 守护用) · `tools/gui/zmax_telemetry.py`(控制台口径) ·
  `src/lerobot/dataspace/topics.py`(注册表)。只改后者 ⇒ 守护 `allowed("ss_engine")` 恒 False, **静默不发**
  (日志里连报错都没有)。加新话题三份都要加。
- 🔴 **`.vscode/launch.json` 只手改会被抹掉**: 唯一依据是 `tools/gui/simulink_module.py::_vscode_launch_cfg(root)`
  (「右键 → 打开 VSCode」用它重写该文件)。加调试配置**只改这个模板**, 再重新生成 json。
- **单写入器锁**: 常驻单元在跑时, 再 F5 起一个会打印「已有写入器在跑 (pid …)」。要断点调试先
  `sudo systemctl stop zmax-ss-engine-loop`, 调完 `start`。
- **守护并发坑**: 新节拍线程 `publish()` 写 `self.sent` 时, 主 tick 正 `for t,c in self.sent.items()` ⇒
  `RuntimeError: dictionary changed size during iteration`; 改成 `list(...)` 快照。
- **线程首轮竞态**: 节拍线程与 `ensure_node()` 并发 ⇒ 首轮 `ModuleNotFoundError: 'ss_types'` /
  `KeyError: 'cyclonedds'`; 修法 = 模块级把 daemon 自身目录插进 `sys.path` + 线程起手等 `self.node is not None`。
- **没有状态源时不要造**: 轨迹唯一依据不存在 ⇒ 空转并每 5s 明说; 也可以 `ss_engine_loop.py seed --episode reports/ss_episode_*.npz`
  用**已有真实 episode**(obs[43]+u_exec_vec) 先启动 (src 字段写明来源), 工程一跑会被更新的唯一依据覆盖。

## 取证口径
`gui-venv311/bin/python tools/verify_ss_engine_loop.py` → 16 项 (单元 active / cycle 递增 / 帧新鲜 / 字段齐 /
step 耗时>0 / Φ 非恒 0 / 唯一依据在位且 43 维 / 单写入器 / DDS 真收到且 cycle 递增 / project+task_id 与唯一依据一致)。
报数必给: 实测 Hz、step ms、Φ/‖∇Φ‖、帧龄、cycle 号、tap/DDS 两边一致。
