#!/bin/bash
# gs_render_loop.sh —— 550C(Intel) 侧 3DGS 渲染推流常驻壳 (v2: 按质量挑资产 + 提高渲染分辨率)
#
# 老倪 2026-10-25 / 11-13: 「4060 只是显示，而 intel 要渲染好，推流过来」「怎么模糊了」
#   ⇒ 渲染全在 550C 的 XPU 上做, 4060 只显示 /gs/live.jpg。
#
# v1 的问题(20:31 实测): 只挑"最新一轮"资产 ⇒ 挑到 400 步/13.6dB 的实时轮, 画面糊
#   (实测拉普拉斯方差 1.5, 几乎没细节), 而且 640x480 拉到 1200 宽显示 = 二次放大。
# v2 改两件事:
#   1) **按 PSNR 挑最好的完整轮次**(不按时间): 扫 gs_rt/out_* 与 8814 队列 jobs/*/out,
#      取 train_report.json 里 psnr_holdout_db 最高那份(当前 3000 步/15.07dB/109193 高斯);
#   2) 渲染分辨率提到 960 宽(可用 GSRENDER_WIDTH 覆盖), 再交给浏览器显示。
set +u

STREAM=/home/intel/zmax_map/tools/gs_render_stream_intel.py
PY=/home/intel/gsxpu-venv/bin/python
PORT=${GSRENDER_PORT:-8816}
FPS=${GSRENDER_FPS:-8}
LIFE=${GSRENDER_LIFE:-900}
# 强制渲染资产(可选): 一行就是一个 out_ 目录; 空/不存在则按 PSNR 自动挑
[ -f /home/intel/zmax_map/tools/gs_force_out.conf ] && export GS_FORCE_OUT=$(head -1 /home/intel/zmax_map/tools/gs_force_out.conf | tr -d ' \n')
WIDTH=${GSRENDER_WIDTH:-1280}

log() { echo "[$(date '+%F %T')] $*"; }

pick() {
  # 输出 "<out>|<ds>"; 选择理由写 stderr
  /usr/bin/python3 - <<'PY'
import glob, json, os, sys
cands = []
for p in glob.glob('/home/intel/zmax_data/gs_rt/out_*') + glob.glob('/home/intel/gs_train_service_intel/jobs/*/out'):
    p = p.rstrip('/')
    if not (os.path.isfile(p + '/gs.ply') and os.path.isfile(p + '/train_report.json')):
        continue
    base = os.path.basename(p)
    if base.startswith('out_'):
        ds = '/home/intel/zmax_data/gs_rt/ds_' + base[4:]
    else:
        ds = os.path.dirname(p) + '/ds'
    # (cameras.json 的存在性放到读完 report 之后判 —— ds 可能要从 report.data 兜底, 见下)
    try:
        r = json.load(open(p + '/train_report.json'))
    except Exception:
        continue
    # 🔴 2026-11-14 老倪「图像还是非常模糊」的根因, 两处:
    #   ① 大训练产物(out_big2_081214: 24000 步/44.5万高斯/17.22dB)的 ds 不在 gs_rt/ds_* 下, 而是
    #      当初 --data 指到的会话目录 ⇒ 老逻辑 continue 直接跳过它, 永远只剩实时那份 400 步/10 万高斯;
    #   ② 于是画面一直糊。这里用 report 里的 data 字段兜底, 谁 psnr 高就用谁(实时轮只要练得更准也能赢)。
    _ds2 = ds
    if not os.path.isfile(os.path.join(_ds2, 'cameras.json')):
        _d = (r.get('data') or '').rstrip('/')
        if _d and os.path.isfile(os.path.join(_d, 'cameras.json')):
            _ds2 = _d
    if not os.path.isfile(os.path.join(_ds2, 'cameras.json')):
        continue
    ds = _ds2
    mt = os.path.getmtime(p + '/gs.ply')
    # 🔴 只认同一天的产物: 老 job 是别的场景/别的标定, PSNR 再高也不是这个工位
    import datetime
    # 2026-11-25 修: 原来只认「今天」, 凌晨 0 点后昨天训的资产全部被过滤 ⇒ pick 返回空 / 回落到次优。
    #   改成最近 48 小时(含跨零点), 既不跨场景也不丢昨晚刚训的资产。
    import datetime as _dt
    if (_dt.datetime.now() - _dt.datetime.fromtimestamp(mt)).total_seconds() > 172800:
        continue
    cands.append((float(r.get('psnr_holdout_db') or 0), mt,
                  p, ds, r.get('steps'), r.get('n_gaussians')))
# 🔴 2026-11-25 老倪「切」: 强制指定渲染资产。
#   默认按 psnr_holdout 选最高, 但跨数据集的 PSNR 不可比 ——
#   在役 out_20261124_141621 是 22.93dB(金属块特写小场景), 新的 out_merged_3k 是 20.88dB(整个料盘),
#   数值低的反而看得清更多东西。所以允许 GS_FORCE_OUT=<out目录> 覆盖排序。
_force = os.environ.get('GS_FORCE_OUT', '').rstrip('/')
if _force and os.path.isfile(_force + '/gs.ply'):
    _r = {}
    try:
        _r = json.load(open(_force + '/train_report.json'))
    except Exception:
        pass
    _ds = '/home/intel/zmax_data/gs_rt/ds_' + os.path.basename(_force)[4:]
    if not os.path.isfile(os.path.join(_ds, 'cameras.json')):
        _d = (_r.get('data') or '').rstrip('/')
        if _d and os.path.isfile(os.path.join(_d, 'cameras.json')):
            _ds = _d
    if os.path.isfile(os.path.join(_ds, 'cameras.json')):
        print('# 强制指定 %s  PSNR留出 %s  步 %s' % (_force, _r.get('psnr_holdout_db'), _r.get('steps')),
              file=sys.stderr)
        print('%s|%s' % (_force, _ds))
        sys.exit(0)
    else:
        print('# GS_FORCE_OUT 指定目录缺 cameras.json, 回退自动挑选', file=sys.stderr)

if not cands:
    sys.exit(1)
cands.sort(key=lambda x: (x[0], x[1]))
psnr, mt, p, ds, steps, ng = cands[-1]
print('# 选中 %s  PSNR留出 %.2f dB  步 %s  高斯 %s' % (p, psnr, steps, ng), file=sys.stderr)
print('%s|%s' % (p, ds))
PY
}

while true; do
  # 内存闸: 不够就先不渲(2026-11-13 20:38 曾把 550C 压到 30G 全满 / load 50 / sshd 登不上)
  AVAIL=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
  if [ "$AVAIL" -lt "${GSRENDER_MIN_AVAIL_GB:-6}" ]; then
    log "可用内存 ${AVAIL}G < ${GSRENDER_MIN_AVAIL_GB:-6}G, 先不渲, 等 30s"
    sleep 30
    continue
  fi
  if ! P=$(pick); then
    log "还没有完整的轮次(gs.ply + train_report.json + cameras.json), 等 30s"
    sleep 30
    continue
  fi
  OUT="${P%%|*}"; DS="${P##*|}"
  log "起渲染: out=$OUT ds=$DS port=$PORT fps=$FPS width=$WIDTH life=${LIFE}s"
  timeout -s TERM "$LIFE" "$PY" "$STREAM" \
      --ply "$OUT/gs.ply" --cameras "$DS/cameras.json" --report "$OUT/train_report.json" \
      --port "$PORT" --fps "$FPS" --width "$WIDTH" --quality 92 --sync ${GSRENDER_SYNC:-on} 2>&1 | sed -u 's/^/[stream] /'
  log "渲染进程退出(或到 ${LIFE}s 轮换), 5s 后重挑最好资产重起"
  sleep 5
done
