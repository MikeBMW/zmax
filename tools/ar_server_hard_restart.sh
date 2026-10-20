#!/usr/bin/env bash
# AR 服务 (8797) 彻底重启: 停 → 等所有 worker 退 → 确认没人持有 RealSense 节点 → 起 → 自证出图
#   2026-10-20: tcp_ar_server 是预派生(多 worker 共享同一个 listen fd), 单看 "端口已应答" 会以为重启成功,
#   实际老 worker 还活着并继承着 pyrealsense 的设备句柄 ⇒ 新 pipeline 一直 VIDEO S_FMT errno=16。
set -u
cd /home/ubuntu/zmax || exit 1
echo "=== ① 停 ==="
bash tools/ar_server_ctl.sh stop 2>&1 | tail -1
for i in $(seq 1 20); do
  n=$(pgrep -fc "tools/tcp_ar_server.py" 2>/dev/null || echo 0)
  [ "$n" = "0" ] && break
  sleep 0.5
done
n=$(pgrep -fc "tools/tcp_ar_server.py" 2>/dev/null || echo 0)
if [ "$n" != "0" ]; then
  echo "  还有 $n 个 worker, 强制结束"
  pgrep -f "tools/tcp_ar_server.py" | while read -r p; do kill -9 "$p" 2>/dev/null; done
  sleep 1
fi
echo "  剩余进程: $(pgrep -fc 'tools/tcp_ar_server.py' 2>/dev/null || echo 0)"

echo "=== ② 谁还持有 RealSense 视频节点 (期望: 无) ==="
HOLD=0
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  for f in /proc/$p/fd/*; do
    t=$(readlink "$f" 2>/dev/null)
    case "$t" in
      /dev/video[4-9]) echo "  ⚠ $p $(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-60) → $t"; HOLD=1;;
    esac
  done
done 2>/dev/null
[ "$HOLD" = "0" ] && echo "  ✅ 没有人持有 (D435 空闲)"

echo "=== ③ 起 ==="
bash tools/ar_server_ctl.sh start 2>&1 | tail -2
sleep 4

echo "=== ④ 自证: rs_info + 两帧新鲜度 ———"
curl -s --max-time 12 http://127.0.0.1:8797/api/rs_info; echo
curl -s --max-time 15 -o /tmp/rs_a.jpg -w "  A http=%{http_code} bytes=%{size_download}\n" http://127.0.0.1:8797/snap/rs.jpg
sleep 1.5
curl -s --max-time 15 -o /tmp/rs_b.jpg -w "  B http=%{http_code} bytes=%{size_download}\n" http://127.0.0.1:8797/snap/rs.jpg
md5sum /tmp/rs_a.jpg /tmp/rs_b.jpg 2>/dev/null | sed 's/^/  /'
