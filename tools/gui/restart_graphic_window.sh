#!/usr/bin/env bash
# 重启「实时监控 · Graphic 信号分析」独立窗口 (老倪: 「你给我重启 信号分析的窗口」)
# 为什么必须重启: 该窗口的信号目录树在**建窗时**按当时的场景标签铺一次; 标签真源
# (config/topics/scene_tags.json) 之后再加的信号要重开窗口才进树。
set -u
cd /home/ubuntu/zmax
LOG=/tmp/graphic_window.log
# 模式用 [c] 断开自匹配 (否则 pkill -f 会把本脚本自己的 shell 也算上)
PAT="[p]ython .*tools/gui/canoe_graphic[.]py"
pids=$(pgrep -f "$PAT" 2>/dev/null | tr '\n' ' ')
if [ -n "${pids:-}" ]; then
  echo "关闭旧窗口: $pids"
  kill $pids 2>/dev/null
  for i in 1 2 3 4 5 6; do
    sleep 1
    [ -z "$(pgrep -f "$PAT" 2>/dev/null)" ] && break
  done
  pids=$(pgrep -f "$PAT" 2>/dev/null | tr '\n' ' ')
  [ -n "${pids:-}" ] && { echo "强杀: $pids"; kill -9 $pids 2>/dev/null; sleep 1; }
else
  echo "没有旧窗口在跑"
fi
# 与 tools/gui/open_graphic_window.sh 同一套环境修法 (控制台带 QT_QPA_PLATFORM=xcb 起时子进程会去找 xcb 插件直接退出)
unset QT_QPA_PLATFORM QT_QPA_PLATFORM_PLUGIN_PATH QT_PLUGIN_PATH
setsid nohup env DISPLAY=:0 QT_AUTO_SCREEN_SCALE_FACTOR=0 \
  /home/ubuntu/zmax/gui-venv311/bin/python /home/ubuntu/zmax/tools/gui/canoe_graphic.py \
  > "$LOG" 2>&1 < /dev/null &
sleep 10
NEW=$(pgrep -f "$PAT" | head -1)
echo "新窗口 pid=${NEW:-none}  日志=$LOG"
DISPLAY=:0 wmctrl -lG 2>/dev/null | grep -i "信号分析" | head -3
