#!/bin/bash
# gs_render_loop.sh —— 边缘机(Intel XPU)侧 3DGS 渲染推流的常驻壳。
#
# 为什么需要这层壳(实测):
#   1) gs_render_stream_intel.py 必须显式给 --ply/--cameras/--report 三个路径,
#      而实时建图每轮产出新目录(out_<ts> / ds_<ts>, 以及训练队列 jobs/<id>/out) ⇒ 需要"挑资产"的逻辑;
#   2) 每轮训练完要换成新资产 ⇒ 外圈定时重起一次(LIFE 秒);
#   3) 端口被旧实例占 / 权重读坏 ⇒ 死了就退到下一圈重起, 不静默退出;
#   4) 只装脚本不装 unit = 永远没人拉它 ⇒ station 那格取帧报 503/Connection reset。
#      (判据见 SKILL.md「在线渲染推流 / 运维坑」)
#
# 两条实测铁律(都踩过):
#   · **按质量挑资产, 不按时间**: 实时建图每轮的 400~600 步只有 12~13.6dB, 跑满 3000 步那份 15dB+ ⇒
#     "取最新一轮"就把最糊的推上墙(实测拉普拉斯方差 1.5, 用户第一句就是"怎么模糊了")。
#   · **候选必须限同一天**: 训练队列里留着别的场景/别的标定的老 job(PSNR 更高), 一选就渲成另一个工位 ⇒
#     加 date.fromtimestamp(mtime)==today 过滤, 再取 PSNR 最高。
#   · **渲染前先看可用内存**: 960x720@8fps 与训练同跑会把边缘机压到 30G 全满 / load 50 / sshd banner timeout
#     (页面那格跟着黑)。低于 GSRENDER_MIN_AVAIL_GB 就先不渲 —— 宁可整格退回浏览器端查看器。
#
# 用法: 放进 systemd 单元 ExecStart(见本技能 SKILL.md 的在线渲染推流一节),
#       env GSRENDER_PORT/GSRENDER_FPS/GSRENDER_LIFE/GSRENDER_WIDTH/GSRENDER_MIN_AVAIL_GB 可覆盖默认。
set +u

RT=${GS_RT_DIR:-$HOME/zmax_data/gs_rt}
JOBS=${GS_JOBS_DIR:-$HOME/gs_train_service_intel/jobs}
TOOLS=${GS_TOOLS_DIR:-$HOME/zmax_map/tools}
STREAM=$TOOLS/gs_render_stream_intel.py
PY=${GS_PY:-$HOME/gsxpu-venv/bin/python}
PORT=${GSRENDER_PORT:-8816}
FPS=${GSRENDER_FPS:-6}
LIFE=${GSRENDER_LIFE:-900}
WIDTH=${GSRENDER_WIDTH:-640}
MIN_AVAIL=${GSRENDER_MIN_AVAIL_GB:-6}

log() { echo "[$(date '+%F %T')] $*"; }

pick() {
  # 输出 "<out>|<ds>"; 选择理由写 stderr。取"今天 · 完整 · PSNR 最高"那一版。
  GS_RT_DIR="$RT" GS_JOBS_DIR="$JOBS" /usr/bin/python3 - <<'PY'
import datetime, glob, json, os, sys
rt = os.environ.get('GS_RT_DIR', '')
jobs = os.environ.get('GS_JOBS_DIR', '')
today = datetime.date.today()
cands = []
for p in glob.glob(os.path.join(rt, 'out_*')) + glob.glob(os.path.join(jobs, '*', 'out')):
    p = p.rstrip('/')
    if not (os.path.isfile(p + '/gs.ply') and os.path.isfile(p + '/train_report.json')):
        continue
    base = os.path.basename(p)
    ds = os.path.join(rt, 'ds_' + base[4:]) if base.startswith('out_') else os.path.join(os.path.dirname(p), 'ds')
    if not os.path.isfile(os.path.join(ds, 'cameras.json')):
        continue
    mt = os.path.getmtime(p + '/gs.ply')
    if datetime.date.fromtimestamp(mt) != today:      # 老 job = 别的场景/标定, PSNR 再高也不是这个工位
        continue
    try:
        r = json.load(open(p + '/train_report.json'))
    except Exception:
        continue
    cands.append((float(r.get('psnr_holdout_db') or 0), mt, p, ds, r.get('steps'), r.get('n_gaussians')))
if not cands:
    sys.exit(1)
cands.sort(key=lambda x: (x[0], x[1]))
psnr, mt, p, ds, steps, ng = cands[-1]
print('# 选中 %s  PSNR留出 %.2f dB  步 %s  高斯 %s' % (p, psnr, steps, ng), file=sys.stderr)
print('%s|%s' % (p, ds))
PY
}

while true; do
  # 内存闸: 不够就先不渲(曾把边缘机压到 30G 全满 / load 50 / sshd 都登不上)
  AVAIL=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
  if [ "$AVAIL" -lt "$MIN_AVAIL" ]; then
    log "可用内存 ${AVAIL}G < ${MIN_AVAIL}G, 先不渲, 等 30s"
    sleep 30
    continue
  fi
  if ! P=$(pick); then
    log "今天还没有完整轮次(gs.ply + train_report.json + cameras.json), 等 30s"
    sleep 30
    continue
  fi
  OUT="${P%%|*}"; DS="${P##*|}"
  log "起渲染: out=$OUT ds=$DS port=$PORT fps=$FPS width=$WIDTH life=${LIFE}s avail=${AVAIL}G"
  timeout -s TERM "$LIFE" "$PY" "$STREAM" \
      --ply "$OUT/gs.ply" --cameras "$DS/cameras.json" --report "$OUT/train_report.json" \
      --port "$PORT" --fps "$FPS" --width "$WIDTH" 2>&1 | sed -u 's/^/[stream] /'
  log "渲染进程退出或到 ${LIFE}s 轮换, 5s 后重挑"今天 PSNR 最高"那版重起"
  sleep 5
done
