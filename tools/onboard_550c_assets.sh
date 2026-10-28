#!/bin/bash
# onboard_550c_assets.sh —— 产线网卡一到位, 自动把 550C 缺的资产补齐并自检
#
# 背景 (2026-10-25): 550C 节点级取证 52/70 在跑, 16 个没在 Intel 上跑, 全是"权重没过去":
#   SAM3(3.3G) / L5 VLM(972M) / INTACT L4(~) / transformers 包。
#   走 ECS 跳板推 3.3G 实测每次 10s 就断(broken pipe), 必然打不通 ⇒ 改成**等产线网卡**直连再推。
#   本脚本设计成幂等 + 可反复跑: 每步都先看远端是否已就绪, 好了就跳过。
#
# 触发: zmax-onboard-550c.timer (60s) 或人工 `bash tools/onboard_550c_assets.sh`
# 依赖: 192.168.23.x 直连(不依赖 ECS); 远端用户 intel 免密; 远端 /home/intel/train_venv
set -u
REPO=/home/ubuntu/zmax
STATE=$REPO/zmax_data/runtime/onboard_550c.json
LOG=/var/log/zmax-onboard-550c.log
INTEL_IP=${INTEL_IP:-192.168.23.70}
INTEL_U=${INTEL_U:-intel}
RDIR=/home/intel/zmax_550c
BW=${BW:-0}

say() { echo "$(date '+%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }
rsh="ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10"

# 已经全好了就直接退出 (timer 每 60s 跑一次, 不能有副作用)
# 2026-10-29: 原判据 test -d 只看目录存在 ⇒ 空目录也算"已齐"(实测 models/l5_vlm 是空的, 服务天天报已齐)。
#   改成按**内容**判: L5 至少一个权重文件、INTACT 至少一个 .pt。
done_marker() { $rsh ${INTEL_U}@${INTEL_IP} "test -f $RDIR/models/sam3_hf/model.safetensors && ls $RDIR/models/l5_vlm/* >/dev/null 2>&1 && ls $RDIR/models/intact/*.pt >/dev/null 2>&1 && /home/intel/train_venv/bin/python -c 'import transformers' 2>/dev/null && echo YES" 2>/dev/null | grep -q YES; }

# 0) 直连可用吗? 不可用就安静退出(等网卡), 不刷日志
if ! ping -c1 -W1 "$INTEL_IP" >/dev/null 2>&1; then
  say "直连 $INTEL_IP 不通 (产线网卡未到位), 跳过"
  exit 0
fi
if done_marker; then
  say "550C 资产已齐 (SAM3+L5+transformers), 无需动作"
  exit 0
fi

say "=== 开始补齐 550C 资产 (直连 $INTEL_IP) ==="
mkdir -p "$(dirname "$STATE")"

push() {  # $1 本地目录 $2 远端目录 $3 名字
  say "推 $3 ..."
  rsync -a --partial --inplace ${BW:+--bwlimit=$BW} -e "$rsh" "$1/" "${INTEL_U}@${INTEL_IP}:$2/" 2>&1 | tail -2 | tee -a "$LOG"
  local rc=${PIPESTATUS[0]}
  [ "$rc" = "0" ] && say "✅ $3 完成" || say "❌ $3 失败 rc=$rc"
  return "$rc"
}

$rsh ${INTEL_U}@${INTEL_IP} "mkdir -p $RDIR/models/sam3_hf $RDIR/models/l5_vlm $RDIR/models/intact $RDIR/wheels" || exit 1

# 1) transformres 离线 wheel + 安装
if ! $rsh ${INTEL_U}@${INTEL_IP} "/home/intel/train_venv/bin/python -c 'import transformers'" 2>/dev/null; then
  push /tmp/sam3_wheels "$RDIR/wheels" "transformers wheel" || true
  $rsh ${INTEL_U}@${INTEL_IP} "/home/intel/train_venv/bin/pip install -q --no-index --find-links $RDIR/wheels transformers==5.16.1 tokenizers safetensors huggingface_hub regex PyYAML requests tqdm filelock packaging && /home/intel/train_venv/bin/python -c 'from transformers import Sam3Model, Sam3Processor; import transformers; print(\"transformers\", transformers.__version__, \"sam3 OK\")'" 2>&1 | tee -a "$LOG"
fi

# 2) SAM3 权重 (3.3G)
push "$REPO/zmax_data/models/sam3_hf" "$RDIR/models/sam3_hf" "SAM3 权重" || true

# 3) L5 VLM (取最新一版 merged)
L5=$(ls -dt "$REPO"/zmax_data/models/l5_vlm_merged_* 2>/dev/null | head -1)
[ -n "${L5:-}" ] && push "$L5" "$RDIR/models/l5_vlm" "L5 VLM ($(basename "$L5"))" || say "⚠️ 没找到 l5_vlm_merged_*"

# 4) INTACT L4
INTACT="$REPO/zmax_data/stable-wm-cache/checkpoints/intact_l4_v6merged.pt"
# 2026-10-29: 原来 push "$(dirname ...)" 会把整个 checkpoints 目录(12.16GB/355 文件)推过去 ⇒ 只推这一个 .pt
if [ -f "$INTACT" ]; then
  $rsh ${INTEL_U}@${INTEL_IP} "mkdir -p $RDIR/models/intact"
  say "推 INTACT 单文件 $(basename "$INTACT") ($(du -h "$INTACT" | cut -f1)) ..."
  rsync -a --partial --inplace ${BW:+--bwlimit=$BW} -e "$rsh" "$INTACT" "${INTEL_U}@${INTEL_IP}:$RDIR/models/intact/" 2>&1 | tail -2 | tee -a "$LOG"
  [ "${PIPESTATUS[0]}" = "0" ] && say "✅ INTACT ckpt 完成" || say "❌ INTACT ckpt 失败"
else say "⚠️ 无 INTACT ckpt"; fi

# 5) 校验 SAM3 sha256
LS=$(awk '{print $1}' "$REPO/zmax_data/models/sam3_hf/model.safetensors.sha256" 2>/dev/null)
RS=$($rsh ${INTEL_U}@${INTEL_IP} "sha256sum $RDIR/models/sam3_hf/model.safetensors 2>/dev/null | awk '{print \$1}'")
if [ -n "${LS:-}" ] && [ "$LS" = "${RS:-}" ]; then say "✅ SAM3 权重 sha256 一致 $LS"; else say "⚠️ SAM3 sha 不一致 local=${LS:-无} remote=${RS:-无}"; fi

# 6) 收尾: 落状态 + 重跑节点取证
/usr/bin/python3 - "$STATE" "$LS" "$RS" <<'PY' 2>/dev/null || true
import json, sys, time
p, ls, rs = sys.argv[1], sys.argv[2], sys.argv[3]
json.dump({"t": time.time(), "t_str": time.strftime("%Y-%m-%d %H:%M:%S"),
           "sam3_sha_local": ls, "sam3_sha_remote": rs, "route": "direct"},
          open(p, "w"), ensure_ascii=False, indent=1)
PY
say "=== 完成, 建议接着跑: python3 tools/verify_550c_nodes_on_intel.py ==="
