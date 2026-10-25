#!/bin/bash
# relay_sam3_via_ecs_orin.sh —— 非局域网环境(远程模式)下把 SAM3 送进 550C 的接力链
#
# 为什么不是直推: 550B→Intel 只有一个 ssh 通道(经 ECS 跳板), 实测推大文件 10 秒必 broken pipe,
#   3.3G 直推物理上不可能。而三段路各自的瓶颈不同:
#     ① 550B → ECS : 公网上行, 实测 ~1.15MB/s, 能稳(rsync 大文件不断)
#     ② Orin  → ECS : Orin 有公网出口(它的反向隧道就建在 ECS 上), 拉取走它自己的带宽
#     ③ Intel ← Orin: 同一产线局域网, 千兆, 与 ssh 隧道无关
#   ⇒ 用 ECS 当跳板仓, Orin 当中继, 全程绕开那条脆弱隧道。
#
# 依赖: 本机可 ssh root@ECS(id_ecs_tunnel) / ssh orin-ecs / ssh -p 18822 intel@127.0.0.1
# 产物: Intel 上 models/sam3_hf + transformers 装好 + sha256 对账
set -u
ECSH="root@47.93.88.143"
ECSK=/home/ubuntu/.ssh/id_ecs_tunnel
LOCAL_W=/home/ubuntu/zmax/zmax_data/models/sam3_hf
STAGE=/var/www/html/_sam3
WSTAGE=/var/www/html/_wheels
RELAY=/home/tashan/relay
RDIR=/home/intel/zmax_550c
LOG=/var/log/zmax-relay-sam3.log
BW=${BW:-0}

say() { echo "$(date '+%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }
r_ecs() { ssh -o BatchMode=yes -o ConnectTimeout=12 -i $ECSK $ECSH "$@"; }
r_orin() { for i in 1 2 3 4 5; do ssh -o BatchMode=yes -o ConnectTimeout=12 orin-ecs "$@" && return 0; sleep 20; done; return 1; }
r_intel() { for i in 1 2 3 4 5; do ssh -o BatchMode=yes -o ConnectTimeout=12 -p 18822 intel@127.0.0.1 "$@" && return 0; sleep 20; done; return 1; }

LOCAL_SZ=$(stat -c %s "$LOCAL_W/model.safetensors")
LOCAL_SHA=$(awk '{print $1}' "$LOCAL_W/model.safetensors.sha256" 2>/dev/null)

say "=== 接力开始 · 本地 $(numfmt --to=iec $LOCAL_SZ) · 目标 sha=${LOCAL_SHA:-无} ==="

# ── 1) 等 550B→ECS 上传完成 (背景 rsync 在跑)
for i in $(seq 1 240); do
  ECS_SZ=$(r_ecs "stat -c %s $STAGE/model.safetensors 2>/dev/null || echo 0")
  if [ "${ECS_SZ:-0}" -ge "$LOCAL_SZ" ]; then say "① 上传完成: ECS 已有 $(numfmt --to=iec ${ECS_SZ})"; break; fi
  [ $((i % 6)) = 1 ] && say "① 等待上传… ECS $(numfmt --to=iec ${ECS_SZ:-0}) / 本地 $(numfmt --to=iec $LOCAL_SZ)"
  sleep 30
done
ECS_SZ=$(r_ecs "stat -c %s $STAGE/model.safetensors 2>/dev/null || echo 0")
[ "${ECS_SZ:-0}" -ge "$LOCAL_SZ" ] || { say "❌ 上传未完成, 中止 (ECS=${ECS_SZ:-0})"; exit 1; }

# ⚠️ ECS 的站点根是 /www/wwwroot/datadrive.world (不是 /var/www/html: 实测 /_sam3/config.json 404)
#   ⇒ 传完把目录挪进真站点根, 再验一次 HTTP 200; 不做符号链接(nginx 可能 disable_symlinks)。
say "①b 把上传目录挪进站点根 /www/wwwroot/datadrive.world"
r_ecs "mkdir -p /www/wwwroot/datadrive.world && \
  [ -d /var/www/html/_sam3 ] && mv -f /var/www/html/_sam3 /www/wwwroot/datadrive.world/ 2>/dev/null; \
  [ -d /var/www/html/_wheels ] && mv -f /var/www/html/_wheels /www/wwwroot/datadrive.world/ 2>/dev/null; \
  ls -d /www/wwwroot/datadrive.world/_sam3 /www/wwwroot/datadrive.world/_wheels" 2>&1 | tail -3 | tee -a "$LOG"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://47.93.88.143/_sam3/config.json)
say "①b 静态自测 /_sam3/config.json = $CODE"
[ "$CODE" = "200" ] || { say "❌ 静态目录不可访问, 中止 (先查 nginx 根/权限)"; exit 1; }

# ── 2) Orin 从 ECS 拉 (它自己有公网出口, 不经过隧道)
say "② Orin 开始从 ECS 拉取…"
r_orin "mkdir -p $RELAY/sam3; cd $RELAY/sam3; \
  for t in 1 2 3 4 5; do curl -sS -C - -o model.safetensors http://47.93.88.143/_sam3/model.safetensors && break; echo \"retry \$t\"; sleep 15; done; \
  ls -l model.safetensors" 2>&1 | tail -3 | tee -a "$LOG"
ORIN_SZ=$(r_orin "stat -c %s $RELAY/sam3/model.safetensors 2>/dev/null || echo 0")
say "② Orin 收到 $(numfmt --to=iec ${ORIN_SZ:-0})"
[ "${ORIN_SZ:-0}" -ge "$LOCAL_SZ" ] || { say "❌ Orin 拉取不完整, 中止"; exit 1; }

# ── 3) Orin 起 http 中继 + Intel 从 Orin 拉 (产线局域网, 快)
say "③ 确保 Orin 8899 中继在跑"
r_orin "if ! ss -ltn | grep -q ':8899 '; then setsid nohup python3 -m http.server 8899 --bind 0.0.0.0 --directory $RELAY > /tmp/relay_8899.log 2>&1 < /dev/null & fi; sleep 2; ss -ltn | grep -c ':8899 '" 2>&1 | tail -1 | tee -a "$LOG"

say "③ Intel 从 Orin 拉 (局域网)…"
r_intel "mkdir -p $RDIR/models/sam3_hf; cd $RDIR/models/sam3_hf; \
  for t in 1 2 3 4 5; do curl -sS -C - -o model.safetensors http://192.168.23.66:8899/sam3/model.safetensors && break; echo \"retry \$t\"; sleep 10; done; ls -l model.safetensors" 2>&1 | tail -3 | tee -a "$LOG"

# 小文件 (config/processor/tokenizer): 直接从本机 base64 过去, 只有几百 KB
for f in config.json processor_config.json special_tokens_map.json merges.txt vocab.json tokenizer.json tokenizer_config.json README.md LICENSE model.safetensors.sha256; do
  [ -f "$LOCAL_W/$f" ] || continue
  base64 -w0 "$LOCAL_W/$f" > /tmp/_b64 2>/dev/null
  r_intel "base64 -d > $RDIR/models/sam3_hf/$f" < /tmp/_b64 2>/dev/null || true
done

# ── 4) sha256 对账
INTEL_SHA=$(r_intel "sha256sum $RDIR/models/sam3_hf/model.safetensors 2>/dev/null | awk '{print \$1}'")
say "④ sha256: 本地=${LOCAL_SHA:-无} Intel=${INTEL_SHA:-无}"
[ -n "${LOCAL_SHA:-}" ] && [ "$LOCAL_SHA" = "$INTEL_SHA" ] && say "✅ 权重逐字节一致" || say "⚠️ sha 不一致, 需人工看"

# ── 5) transformers: 也在 ECS 上了, 走同一条链
say "⑤ 传 transformers wheel 到 Intel 并安装"
#   目录列表在 nginx 上不一定开(autoindex off) ⇒ 用本机的文件名清单拼 URL, 不靠索引
WLIST=$(ls /tmp/sam3_wheels/*.whl 2>/dev/null | xargs -n1 basename | tr '\n' ' ')
say "⑤ 要传的 wheel: $(echo $WLIST | wc -w) 个"
r_orin "mkdir -p $RELAY/wheels; cd $RELAY/wheels; for f in $WLIST; do [ -s \$f ] || curl -sS -O http://47.93.88.143/_wheels/\$f; done; ls | wc -l" 2>&1 | tail -2 | tee -a "$LOG"
r_intel "mkdir -p $RDIR/wheels; cd $RDIR/wheels; for f in $WLIST; do [ -s \$f ] || curl -sS -O http://192.168.23.66:8899/wheels/\$f; done; ls | wc -l" 2>&1 | tail -2 | tee -a "$LOG"
r_intel "/home/intel/train_venv/bin/pip install -q --no-index --find-links $RDIR/wheels transformers==5.16.1 tokenizers safetensors huggingface_hub regex PyYAML requests tqdm filelock packaging 2>&1 | tail -3; /home/intel/train_venv/bin/python -c 'from transformers import Sam3Model, Sam3Processor; import transformers; print(\"transformers\", transformers.__version__, \"· sam3 可导入\")'" 2>&1 | tail -3 | tee -a "$LOG"

say "=== 接力结束 ==="
