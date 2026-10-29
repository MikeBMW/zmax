#!/usr/bin/env bash
# set_det_src.sh — 一键切换「检测输入帧源」: 真机帧(550C看真机) ⇄ AR 渲染帧(550A仿真)
#
# 老倪 2026-10-29: 「在 550A 上运行的时候, 需要接到渲染后的图像给 yolo; 550C 可以看到真机器人,
# 550A 是在仿真的 AR 上运行的。能切换么?」
#
# 两条消费者, 一次切完 (口径唯一真源 = tools/det_src.py):
#   ① AR 页 8797 光模块 3D 框  : 读 zmax_data/runtime/det_src.json, **每拍重读, 不用重启**
#   ② 状态空间 L2 感知节点      : 输入帧/权重在 unit 的 env+args 里 ⇒ 本脚本改 drop-in 并重启该服务
#
# 用法:
#   bash tools/set_det_src.sh              # 只看现状 (只读)
#   sudo bash tools/set_det_src.sh render  # 550A: AR 工位渲染帧 + yolo_ar_peg.pt
#   sudo bash tools/set_det_src.sh real    # 550C: 真机臂相机帧 + yolo_peg_live.pt
#   sudo bash tools/set_det_src.sh auto    # 按真机帧是否可取自动选 (engine 侧=启动时判定)
set -u
ROOT="/home/ubuntu/zmax"
DROP="/etc/systemd/system/zmax-ss-engine-loop.service.d/zzz-det-src.conf"
UNIT="zmax-ss-engine-loop"
PY="$ROOT/gui-venv311/bin/python"
WANT="${1:-status}"

status() {
  echo "── 真源文件 ──"
  cat "$ROOT/zmax_data/runtime/det_src.json" 2>/dev/null || echo "(无, 默认 auto)"
  echo "── 解析 (含在线探测) ──"
  ( cd "$ROOT/tools" && "$PY" det_src.py | sed -n '1,20p' )
  echo "── ① AR页 8797 ──"
  curl -s -m 6 "http://127.0.0.1:8797/api/det_src" 2>/dev/null \
    | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(' want=%s running=%s weights=%s n=%s ok=%s age=%ss'%(d.get('want'),d.get('running'),d.get('weights'),d.get('n'),d.get('ok_det'),d.get('result_age_s')))" 2>/dev/null \
    || echo " (8797 无响应)"
  echo "── ② 状态空间 L2 (engine) ──"
  "$PY" - <<'PYEOF'
import json, os, time
p = "/dev/shm/l2_det.json"
try:
    d = json.load(open(p, encoding="utf-8"))
    print(" img=%s n=%s ms=%s age=%.1fs" % (d.get("img"), d.get("n"), d.get("ms"), time.time() - float(d.get("t") or 0)))
except Exception as e:
    print(" (无 l2_det.json: %s)" % e)
PYEOF
  systemctl is-active "$UNIT" >/dev/null 2>&1 && echo " unit=$UNIT active" || echo " unit=$UNIT NOT active"
}

if [ "$WANT" = "status" ] || [ "$WANT" = "" ]; then status; exit 0; fi

case "$WANT" in real|render|auto) ;; *) echo "用法: $0 [status|real|render|auto]"; exit 2;; esac
[ "$(id -u)" = "0" ] || { echo "写 engine drop-in 需要 root: sudo bash $0 $WANT"; exit 3; }

# ① 写真源 (8797 每拍重读, 立即生效)
( cd "$ROOT/tools" && "$PY" det_src.py "$WANT" >/dev/null )
RES=$( cd "$ROOT/tools" && "$PY" -c "import json,det_src;print(json.dumps(det_src.resolve()))" )
URL=$(echo "$RES" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['frame_url'])")
W=$(echo "$RES"   | "$PY" -c "import sys,json;print(json.load(sys.stdin)['weights_abs'])")
SRC=$(echo "$RES" | "$PY" -c "import sys,json;d=json.load(sys.stdin);print(d['src'])")
echo "▶ 切到 src=$SRC · frame=$URL · weights=$(basename "$W")"

# ② engine: 改 drop-in (env + ExecStart 的 --pipe-img 都要, argparse 优先于 env)
mkdir -p "$(dirname "$DROP")"
cat > "$DROP" <<EOF
[Service]
# 由 tools/set_det_src.sh 生成 (2026-10-29 帧源切换) — 手改请同步 tools/det_src.py
Environment=ZMAX_SS_PIPE_IMG=$URL
Environment=ZMAX_L2_WEIGHTS=$W
ExecStart=
ExecStart=$PY $ROOT/tools/ss_engine_loop.py run --hz 10 --encoder l4 --l4-hz 1 --l4-frame-url http://127.0.0.1:8801/frame.png --pipeline --pipe-every 10 --pipe-img $URL
EOF
systemctl daemon-reload
_T0=$(stat -c %Y /dev/shm/l2_det.json 2>/dev/null || echo 0)
_OLD_PID=$(systemctl show -p MainPID --value "$UNIT")
systemctl restart "$UNIT"
echo "▶ engine 重启中 (等新帧源的首拍)…"
OK=0
for i in $(seq 1 90); do
  sleep 2
  # 🔴 只判 mtime 不够: 旧进程在停的过程中仍在写 (实测切源后 status 误报成旧源)
  #   必须同时满足: 主进程换了 + l2_det.json 里的 img 已是目标帧源
  _R=$("$PY" -c "
import json,os,subprocess,time
p='/dev/shm/l2_det.json'
try:
    d=json.load(open(p,encoding='utf-8'))
except Exception:
    print('none'); raise SystemExit
pid=subprocess.run(['systemctl','show','-p','MainPID','--value','$UNIT'],
                   capture_output=True,text=True).stdout.strip()
same_img = str(d.get('img') or '') == '''$URL'''
print(('ok' if (pid != '$_OLD_PID' and same_img) else 'waiting')
      + ' pid=%s img=%s age=%.1f' % (pid, d.get('img'), time.time()-float(d.get('t') or 0)))" 2>/dev/null)
  case "$_R" in ok*) OK=1; echo "   $_R"; break;; esac
done
[ "$OK" = "1" ] || echo "⚠ 180s 内没等到新源首拍 (看 journalctl -u $UNIT)"
echo "════ 复核 ════"
status
