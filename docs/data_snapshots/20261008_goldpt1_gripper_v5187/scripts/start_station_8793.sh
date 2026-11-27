#!/bin/bash
# 📌 8793 工位总览 + 8791 看板 的标准启动命令 (唯一真源)
#
# 🔴 2026-10-08 教训: 助手用 `python tools/cam_live_stream.py` **裸启动**过一次 ——
#    丢了下面这些参数, 后果是: ① 叠加三路全 503(缺 --overlay) ② MAXHUB 顶摄无帧
#    (它必须 --local2-dev 6, 裸启动会去开别的设备) ③ 手动控制退化成"仅演练"(缺 --ctl-motion)
#    ⇒ **重启本服务必须用本脚本, 不要敲裸命令**。
#
# 参数逐项含义:
#   --port 8791              看板端口(手机/PC 同网)
#   --quality 72 --fps 30    JPEG 质量/推流上限
#   --arm-http ...:8792/...  手臂相机源(Orin 的 HTTP 帧)
#   --arm-fps 30             手臂源抓取上限
#   --local-dev 0            笔记本相机 = /dev/video0
#   --local2-dev 6           MAXHUB 顶摄 = /dev/video6 (WT15: MAXHUB-Camera)
#   --depth-fps 4            D405 深度图
#   --aoi-fps 0.25           工控机 AOI 取图
#   --ctl-motion             服务侧允许真动(页面仍需显式授权, 5 分钟失效)
#   --station-port 8793      工位总览端口
#   --overlay --overlay-src all --overlay-fps 10   场景叠加(手眼 + overlay_spec.json)
set -u
cd /home/ubuntu/zmax
PY=/home/ubuntu/zmax/gui-venv311/bin/python
LOG=/home/ubuntu/zmax/zmax_data/cam_live_stdout.log

# 停旧实例(按端口占用者取 pid, 比模糊匹配可靠)
for pid in $(ss -ltnp 2>/dev/null | grep ':8793' | grep -oP 'pid=\K[0-9]+' | sort -u); do kill "$pid" 2>/dev/null; done
for pid in $(ps -eo pid,cmd | grep 'tools/cam_live_stream\.py' | grep -v grep | awk '{print $1}'); do kill "$pid" 2>/dev/null; done
for i in $(seq 1 15); do ss -ltn 2>/dev/null | grep -q ':8793' || break; sleep 1; done

setsid nohup "$PY" tools/cam_live_stream.py \
  --port 8791 --quality 72 --fps 30 \
  --arm-http http://192.168.23.66:8792/frame.jpg --arm-fps 30 \
  --local-dev 0 --local2-dev 6 --depth-fps 4 --aoi-fps 0.25 \
  --ctl-motion --station-port 8793 \
  --overlay --overlay-src all --overlay-fps 10 \
  >> "$LOG" 2>&1 < /dev/null &
sleep 10
echo "pid: $(ss -ltnp 2>/dev/null | grep ':8793' | grep -oP 'pid=\K[0-9]+' | sort -u | head -1)"
echo "验收(预热 40s 后应全部 200):"
sleep 40
for u in /snapshot/overlay_arm.jpg /snapshot/overlay_local.jpg /snapshot/overlay_local2.jpg /snapshot/local2.jpg /snapshot/arm.jpg /snapshot/depth.jpg; do
  printf "  %-32s " "$u"; curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 8 "http://127.0.0.1:8793$u"
done
