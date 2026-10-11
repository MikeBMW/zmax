#!/usr/bin/env bash
# 打开「实时监控 · Graphic 信号分析」独立窗口 (DISPLAY=:0)
set -u
cd /home/ubuntu/zmax
LOG=/tmp/graphic_window.log
# 已有实例就不重复开
# 只认 python 进程 (避免匹配到含同名字符串的 shell 包装)
PYPAT="python .*tools/gui/canoe_graphic[.]py"
if pgrep -f "$PYPAT" >/dev/null 2>&1; then
  echo "已在运行: $(pgrep -f "$PYPAT" | tr '\n' ' ')"
  exit 0
fi
# ⚠️ 控制台进程带 QT_QPA_PLATFORM=xcb 起时, 子进程会去 cv2/qt/plugins 找 xcb 插件然后直接退出
#    (实测 "Could not load the Qt platform plugin \"xcb\" ... failed to start") ⇒ 这里清掉平台/插件变量
unset QT_QPA_PLATFORM QT_QPA_PLATFORM_PLUGIN_PATH QT_PLUGIN_PATH
setsid nohup env DISPLAY=:0 QT_AUTO_SCREEN_SCALE_FACTOR=0 \
  /home/ubuntu/zmax/gui-venv311/bin/python /home/ubuntu/zmax/tools/gui/canoe_graphic.py \
  > "$LOG" 2>&1 < /dev/null &
sleep 8
PID=$(pgrep -f "$PYPAT" | head -1)
echo "pid=${PID:-none} 日志=$LOG"
DISPLAY=:0 xdotool search --name "Graphic 信号分析" 2>/dev/null | head -3
