#!/usr/bin/env bash
# 保存数据 (无版本号轮次): 归档 + 清单 + sha256
# 口径: zmax_data/ 与 data/ 都在 .gitignore ⇒ 「保存数据」= 归档目录, 不是 git add
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
TS=$(date +%Y%m%d_%H%M)
DST="$ROOT/zmax_data/release_multimachine_$TS"
mkdir -p "$DST"/{code,data,reports,evidence,logs}

# ① 代码: 由上一版 tag 现场算, 滤掉技能/记忆同步噪声
BASE=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
[ -n "$BASE" ] && git diff --name-only "$BASE"..HEAD > /tmp/_rel_files.txt || true
git status --porcelain | grep -v '^??' | awk '{print $2}' >> /tmp/_rel_files.txt
git status --porcelain | grep '^??' | awk '{print $2}' >> /tmp/_rel_files.txt
sort -u /tmp/_rel_files.txt | while read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    docs/*skills/hermes-all/*|docs/*memory/*|*.code-workspace|zmax_data/*|reports/*) continue;;
    *.pptx|*.pdf|*.zip|*.tar.gz|*.pt|*.safetensors|*.mp4|*.log) continue;;
  esac
  mkdir -p "$DST/code/$(dirname "$f")"; cp -p "$f" "$DST/code/$f"
done

# ② 数据快照: config 全量(软链真源) + 画布 + 本轮成对引导/能量参数
mkdir -p "$DST/data/config" "$DST/data/canvas" "$DST/data/ss_live"
cp -a config/. "$DST/data/config/" 2>/dev/null || true
cp -a data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/canvas/" 2>/dev/null || true
cp -a flows/state_space_obs.json "$DST/data/canvas/state_space_obs.flows.json" 2>/dev/null || true
for j in target_pose_pair.json target_pose_pair_evidence.json target_pose.json; do
  [ -f "zmax_data/ss_live/$j" ] && cp -a "zmax_data/ss_live/$j" "$DST/data/ss_live/" || true
done

# ③ 报告: 本轮 PPT(小文件, 交付件) + 训练/评估 json
for f in zmax_data/reports/*多机动作协同*.pptx zmax_data/reports/*双臂协同*.pptx zmax_data/reports/*SK13*.pptx; do
  [ -f "$f" ] && cp -a "$f" "$DST/reports/" || true
done

# ④ 证据: 现算一遍关键数字 (与 PPT 同源)
PYTHONPATH="$ROOT/src" "$ROOT/gui-venv311/bin/python" - > "$DST/evidence/measured_$(date +%Y%m%d).md" <<'PY'
import numpy as np
from lerobot.manifold.multi_machine_energy import machine_energy, assist_share, dual_layer_forces
from lerobot.manifold.state_space_energy import StateSpaceHamiltonian, layer_shares
from lerobot.manifold.se3_gravity_provider import _rpy_to_T
from lerobot.manifold.se3_impedance import pose_error
ham = StateSpaceHamiltonian()
g = _rpy_to_T([0.649, 0.404, 0.114, 2.961, -1.490, 0.205, 0.0]); gd = g.copy()
gd[:3, 3] = g[:3, 3] + g[:3, 2] * 0.005
M = machine_energy(g, gd, np.array([0, 0, 0.05, 0, 0, 0]), ham)
a = assist_share(240.0, 319.0, 120.0); b = assist_share(240.0, 319.0, 40.0)
_, xie = pose_error(g, gd)
dl = dual_layer_forces(ham, {"M": a["alpha_master"], "S": a["alpha_slave"]}, xie)
print("# 多机动作协同 — 现算实测 (无真机指令)")
print()
print("| 项 | 值 |")
print("|---|---|")
print("| 主机 U/K/H | %.6f / %.6f / %.6f J |" % (M["U"], M["K"], M["H"]))
print("| 主机 |F| | %.3f N |" % float(np.linalg.norm(M["F"])))
print("| 计划/实测/缺口 | 319 / 240 / %.0f 件·时 |" % a["gap"])
print("| 从机能力120 ⇒ 份额 | α_s=%.4f α_m=%.4f Σα=%.6f |" % (a["alpha_slave"], a["alpha_master"], a["sum_alpha"]))
print("| 从机能力40 ⇒ 饱和 | saturated=True shortfall=%.0f |" % b["shortfall"])
print("| 双层分力恒等残差 | %.1e |" % dl["resid_sumF"])
print("| 层份额 | %s |" % " · ".join("%s %.2f" % kv for kv in layer_shares().items()))
PY

# ⑤ 日志尾部
for lg in reports/joint_train_*/train.log; do [ -f "$lg" ] && tail -n 400 "$lg" > "$DST/logs/$(basename $(dirname $lg))_tail.log"; done

cat > "$DST/MANIFEST.md" <<EOF
# 归档 MANIFEST — 多机动作协同 / 双臂协同 / SK13 (无版本号轮次)

- 生成: $(date '+%Y-%m-%d %H:%M:%S %Z')
- 仓库基线: $(git describe --tags --always 2>/dev/null) · HEAD $(git rev-parse --short HEAD)
- 主题: 多机动作协同(机间调度 n_mfac + 力场分力 ss_grav_h) · 双臂协同(机内 dual_arm_guide) · SK13 自动翻转节点
- 目录: code/=本轮改动源码(滤掉技能/记忆同步噪声与大二进制) · data/=config全量+画布+成对引导真源 · reports/=交付 PPT · evidence/=现算实测数字 · logs/=训练日志尾部400行
- 口径: 只算不下发; 无真机指令
EOF

cd "$DST" && find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
cd "$DST" && sha256sum -c --quiet sha256sums.txt && echo "sha256 全 OK"
echo "归档: $DST"
find "$DST" -type f | wc -l; du -sh "$DST"
