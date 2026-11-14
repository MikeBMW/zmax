#!/usr/bin/env bash
# 归档 v5.50.775 (2026-11-14) —— 代码(仅本轮改过) + 数据快照 + 日志尾 + 实测证据 + sha256
# 用法: bash tools/archive_release_5.50.775.sh
set -uo pipefail
VER=5.50.775
DATE=$(date +%Y%m%d)
REPO=/home/ubuntu/zmax
DST=$REPO/zmax_data/release_${VER}_${DATE}
rm -rf "$DST"; mkdir -p "$DST"/{code,data,logs,evidence}

cd "$REPO" || exit 1
# ── 代码: 本轮真改过的文件(含被 gitignore 的调试配置) ─────────────────────────
FILES="
.vscode/launch.json
ZMAX.code-workspace
src/lerobot/engineering/start.py
src/lerobot/engineering/step_mode.py
src/lerobot/middleware/nodes/impl/safety_limit_impl.py
src/lerobot/policies/left_right/state_space/cognition.py
src/lerobot/policies/left_right/state_space/scheduler_fsm.py
src/lerobot/policies/left_right/state_space/real_traj_flow.py
src/lerobot/policies/left_right/state_space/ss_canvas_loop.py
tools/ss_canvas_loop.py
tools/tcp_ar_server.py
tools/ctl_auth.py
tools/cam_live_stream.py
tools/gui/simulink_module.py
tools/web/station.html
tools/web/tcp-ar.html
tools/web/real_traj_grip.json
VERSION.md
"
for f in $FILES; do
  [ -f "$f" ] || { echo "  ⚠️ 缺件: $f"; continue; }
  mkdir -p "$DST/code/$(dirname "$f")"
  cp -L "$f" "$DST/code/$f"      # -L: 解引用软链(打包红线)
done
echo "code 文件数: $(find "$DST/code" -type f | wc -l)"

# ── 数据: 参数真源(config 是软链, 必须显式拷) + 画布 + 运行时状态 ──────────────
mkdir -p "$DST/data"
cp -rL config/calib "$DST/data/calib" 2>/dev/null || true
cp -L  data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/" 2>/dev/null || true
cp -L  flows/state_space_obs.json "$DST/data/flows_state_space_obs.json" 2>/dev/null || true
for j in ss_fsm.json traj_flow.json; do
  cp -L "zmax_data/ss_live/$j" "$DST/data/$j" 2>/dev/null || echo "  ⚠️ 缺 $j"
done
cp -L zmax_data/rokae_sdk/traj_step_state.json "$DST/data/" 2>/dev/null || true
cp -L zmax_data/ctl_auth.json "$DST/data/ctl_auth.state.json" 2>/dev/null || true   # 只留状态字段
echo "data 文件数: $(find "$DST/data" -type f | wc -l) · 体积 $(du -sh "$DST/data" | cut -f1)"

# ── 日志: 只留尾部(常驻日志是 GB 级) ─────────────────────────────────────────
tail -n 3000 /tmp/ss_canvas_loop.log > "$DST/logs/ss_canvas_loop.tail.log" 2>/dev/null || true
tail -n 800  zmax_data/rokae_sdk/traj_step_out.log > "$DST/logs/traj_step_out.tail.log" 2>/dev/null || true
tail -n 300  zmax_data/rokae_sdk/grip_log.jsonl > "$DST/logs/grip_log.tail.jsonl" 2>/dev/null || true

# ── 证据: 只写实测数字 ──────────────────────────────────────────────────────
cat > "$DST/evidence/measured_20261114.md" <<'EV'
# v5.50.775 实测证据 (2026-11-14)

## 1. 动作调制器"缺前馈"误判修复 (根因: 端口载荷是业务字典, .get("value") 取到 None)
- 修前 run(ctx): out1.kind=modulator_skipped · src="cognition.ActionModulator (未调用)"
- 修后 run(ctx): out1.kind=modulator · src="cognition.ActionModulator.decide (端口 in6/in9→in8→in4)"
                u_sat=[-0.340971, -0.02119, -0.076092, 0.0] · 技能 SK01Approach.clamp 真执行
- 现场日志对照: 修前 1,520 条 "缺前馈 ⇒ 直通, 调制器未生效"; 修后最近 600 行 = 0 条
- 结论: decide() 之前从未被调用 ⇒ cognition.py:573 断点永远不进

## 2. decide 自停锚点 (代码内停, 不依赖 VSCode 断点绑定)
- 位置 src/lerobot/policies/left_right/state_space/cognition.py:485-497, 停点 499
- 实测: `> /home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/cognition.py(499)decide()`
- 开关 /tmp/zmax_stop_at_decide 或 env ZMAX_STOP_AT_DECIDE=1 (默认关)

## 3. 单实例/让位 (GUI 看门狗拉起的从属引擎 vs 工程入口)
- 持锁时启动引擎: exit=3, 0.2s (拒绝并行 tick)
- 引擎在跑时 start.py 抢锁: 0.5s 内让位退出 rc=0
- 修前现象: 从属引擎占锁 ⇒ F5 的 start.py 报 "已有工程入口在运行 (pid=2804703)" 并 exit 2

## 4. 真机 215 点轨迹
- 速度档 20% → 40%; 每点实测 10.6s@20%(4060 load 18.6) ⇒ 40% 约 5s/点
- 游标可续跑: flow 启动从 8797 /api/arm/step_traj/status 读 cursor (实测 138/215 续跑)
- 末点误差 0.11~0.14°; 段内 max_jump 12.23°(< 30° 跳变闸)

## 5. 夹爪 (按轨迹几何定动作点, 非"发过算")
- 通道实测: close → /gripper_pos 回证 0.0mm; open 70mm → 回证 70.0mm
- 计划 i=9 close(hold 2000ms) / i=205 open(hold 2600ms)
- 依据: frames[].p 高度剖面 297→114.9mm(i9)→低位作业→998.6mm(i140 抬升)→118.5mm(i200 放下)

## 6. 3DGS 清晰度 (Laplacian 方差, 同一口径)
- 真值 GT 79.7 · 成品 24000步(17.22dB) 44.7 · 当前实时流(在役资产) 10.0 · 400步实时轮 1.8
- 结论: 糊的主因是渲染视角超出训练覆盖(各轮"抬头>+5°"占比 6%~49%); 400 步实时轮未收敛
- 重训: ds_cov1114 = 184658_3bb1(49%抬头/+16°) + 103533_bd5b(38%/+44°), 1149 帧, 16000 步
EV

cat > "$DST/MANIFEST.md" <<'MF'
# Z-MAX v5.50.775 归档 (2026-11-14)

## 主题
动作调制器端口读取修复(decide 真正被调用) · 入口/从属引擎单实例让位 · decide 自停锚点 ·
轨迹速度档 40% + 夹爪按轨迹几何开合 · 3DGS 换高抬头覆盖数据重训

## 目录
- `code/`     本轮改过的代码 + 两份 VSCode 调试配置(`.vscode/launch.json`、`ZMAX.code-workspace`, 均被 gitignore 或不进包)
- `data/`     参数真源 `calib/`(config 为软链, 显式拷) + 画布真源 + `ss_fsm.json`/`traj_flow.json`/`traj_step_state.json` + 授权状态
- `logs/`     日志仅保留尾部(3000/800/300 行), 原件为 GB 级不入档
- `evidence/` 实测数字汇总
- `sha256sums.txt`

## 复现要点
- 断点/自停: `touch /tmp/zmax_stop_at_decide` 后 F5 → 停 `cognition.py:499`; 用完删除
- 轨迹续跑: 停会话再 F5, flow 从 8797 游标续; 速度档在 launch.json `ZMAX_TRAJ_SPEED`
- 夹爪动作点: `tools/web/real_traj_grip.json`
MF

cd "$DST" || exit 1
find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
echo "文件数: $(wc -l < sha256sums.txt) · 体积: $(du -sh . | cut -f1)"
sha256sum -c --quiet sha256sums.txt && echo "✅ sha256 全部一致"
