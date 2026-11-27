#!/usr/bin/env bash
# stop_writers_safe.sh — 关机/交接前安全批量停「常驻写入者」
#
# 为什么需要它:
#   ① `pkill -f <模式>` 会命中**调用它的这条 shell**(命令里就含模式串) ⇒ 自己把自己杀了, 后续步骤全不执行;
#   ② 只停被守护的进程、不停它的 keepalive, 一分钟内就被拉回来 ⇒ 报"已停"是假的;
#   ③ TERM 后仍存活的个别守护要单独列出来(不能只说"已全部停止")。
#
# 用法:
#   bash stop_writers_safe.sh --dry                 # 只列待停清单(先看清单再动手)
#   bash stop_writers_safe.sh                       # 默认正则停一轮
#   bash stop_writers_safe.sh --pat 'a\.py|b\.py'    # 换匹配(扩展正则, 匹配整条命令行)
#
# 判据: 末尾逐条复核, 输出 ✅ 全部已退出 / ⚠ 仍未退出 <pid>。
# 汇报口径: 「停掉的」+「会被 cron/systemd 看护拉回的」+「有意不动的(对外/隧道)」三类都写。
set -u

DRY=0
PAT='vl_safety_keepalive\.sh|vl_safety_monitor\.py|vl_safety_fast\.py|auto_loop\.py|l2_daemon\.py|ss_local_infer|ss_bypass_run|ss_yolo_on_real|sam3_seg\.py|hil_local_api\.py|aoi_feishu_push\.py|motion_beep\.py|tunnel_proxy\.py|tcp_ar_server\.py|cam_live_stream\.py'
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) DRY=1 ;;
    --pat) shift; PAT="${1:-$PAT}" ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

SELF=$$
SELF_PPID=$(ps -o ppid= -p $$ 2>/dev/null | tr -d ' ')

# 排除自身 + 父 shell(以及它们的子进程), 免得把自己停掉
PIDS=$(ps -eo pid,ppid,args --no-headers \
  | awk -v sp="$SELF" -v spp="$SELF_PPID" '($1==sp || $1==spp || $2==sp || $2==spp) {next} {print}' \
  | grep -E "$PAT" | grep -v grep | awk '{print $1}' | sort -un)

[ -z "$PIDS" ] && { echo "无匹配进程"; exit 0; }
echo "待停 ($(echo $PIDS | wc -w)): $(echo $PIDS)"

if [ "$DRY" = "1" ]; then
  for p in $PIDS; do ps -o pid,etime,pcpu,args --no-headers -p "$p" 2>/dev/null | cut -c1-118; done
  exit 0
fi

# 先停 keepalive/包装 shell: 否则它们会在几秒内把被守护的进程拉回来
KEEP=""
for p in $PIDS; do
  a=$(ps -o args= -p "$p" 2>/dev/null)
  case "$a" in *keepalive.sh*|*guard.sh*|*"sleep 20 && cd"*) KEEP="$KEEP $p" ;; esac
done
if [ -n "$KEEP" ]; then echo "先停 keepalive/包装:$KEEP"; kill -TERM $KEEP 2>/dev/null; sleep 3; fi

kill -TERM $PIDS 2>/dev/null; sleep 5

LEFT=""
for p in $PIDS; do ps -p "$p" >/dev/null 2>&1 && LEFT="$LEFT $p"; done
if [ -n "$LEFT" ]; then
  echo "⚠ 仍未退出:$LEFT"          # 单独列出: 汇报里『停不掉的』和『停掉的』都要写
  for p in $LEFT; do ps -o pid,stat,etime,pcpu,args --no-headers -p "$p" 2>/dev/null | cut -c1-118; done
  exit 1
fi
echo "✅ 全部已退出"
