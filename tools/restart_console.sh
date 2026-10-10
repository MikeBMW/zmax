#!/usr/bin/env bash
# 重启 Z-MAX 控制台 —— 杀进程一律走脚本 (内联 pgrep -f "studio.py" 会命中自己的命令行, 把本 shell 杀了)
set -u
ME=$$
PARENT=$PPID
TARGETS=()
for d in /proc/[0-9]*; do
  p=${d#/proc/}
  [ "$p" = "$ME" ] && continue
  [ "$p" = "$PARENT" ] && continue
  cl=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
  case "$cl" in
    *tools/gui/studio.py*) ;;
    *) continue ;;
  esac
  exe=$(readlink -f "$d/exe" 2>/dev/null)
  case "$exe" in
    */gui-venv311/bin/python*) ;;
    *) continue ;;
  esac
  TARGETS+=("$p")
done
echo "控制台进程: ${TARGETS[*]:-无}"
for p in "${TARGETS[@]:-}"; do
  [ -z "$p" ] && continue
  kill "$p" 2>/dev/null && echo "  TERM $p"
done
sleep 4
for p in "${TARGETS[@]:-}"; do
  [ -z "$p" ] && continue
  [ -d "/proc/$p" ] || continue
  kill -9 "$p" 2>/dev/null && echo "  KILL $p"
done
sleep 2
ALIVE=0
for d in /proc/[0-9]*; do
  cl=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
  case "$cl" in *tools/gui/studio.py*) ALIVE=$((ALIVE+1));; esac
done
if [ "$ALIVE" -gt 0 ]; then
  echo "⚠️ 仍有 $ALIVE 个 studio.py 相关进程"
else
  echo "✅ 控制台已全部退出"
fi
