#!/usr/bin/env bash
# aoi_channel_sentinel.sh — 反向通道(8794 -> 工控机)复活哨兵 (2026-09-30 建, 2026-10-13 修)
#
# 为什么需要它(实录):
#   2026-09-30 23:59 一次 `aoi_remote_deploy.py --only 10083` 卡在 **下载** 那一步超时
#   (`<<TIMEOUT download>>`), 而 `iwr -OutFile` 是**先截断目标文件**的 ⇒ 磁盘上那份
#   `cam_surface_10083_work_v*.py` **可能只有半截** ⇒ 一旦保活/人工重启 10083, 服务就起不来。
#   因此它核哈希 + 从 .bak_* 里找完好副本回滚。
#
# 2026-10-13 两处修(都真踩到了):
#   ① 【哨兵钉的版本会过期】原来钉 `..._v6.py` / 636AC7854C947943。2026-10-12 已上线 v20,
#      v6 早被删 ⇒ Get-FileHash 空输出 ⇒ 报"文件损坏且无完好副本"的**假警报**。
#      现改为: 钉 v20; 并且当"钉的那个文件名在盘上根本不存在"时, 明确报【哨兵钉的版本已过期】
#      并列出在役 v* 文件名, 而不是喊"文件损坏"。
#   ② 【取回执不能用 mtime】开机 NTP 回拨 8h 会把开机前落的回执 mtime 变成未来时间,
#      station_cmd.py 旧的 max(mtime) 逻辑永远选到那几个陈旧文件 ⇒ 每次误报"通道死了"。
#      已改成按文件名集合差找新回执(见 station_cmd.py docstring)。
#
# 本哨兵做三件事(全部只读探测 + 只在真需要时才写):
#   ① 探通道(station_cmd.py 小命令); 没醒 → 静默退出(不刷屏)
#   ② 醒了 → 核目标文件 SHA256 是否等于**已知在役版本**
#   ③ 不相等 ⇒ 从 .bak_* 里找哈希等于已知版本的那份覆盖回去 + 复核 + 报一次
#
# 报一次: 用标记文件, 修过/报过就不再重复(除非又出现不一致)。
set -uo pipefail
REPO=/home/ubuntu/zmax
PY=$REPO/gui-venv311/bin/python
WANT="763D4A565738FC5D"                    # 已知在役 v20 的 SHA256 前 16 位 (2026-10-12 部署, 2026-10-13 核过)
DIR='D:\xspace\ultralytics_AOI'
F=cam_surface_10083_work_v20.py
FAM=cam_surface_10083_work_v*.py            # PowerShell 通配
FAMRE='cam_surface_10083_work_v[0-9]+\.py'  # grep 正则(通配符 * 在正则里含义不同, 别混用)
MARK=/home/ubuntu/zmax/zmax_data/agent_hub/.sentinel_last

probe=$(cd "$REPO" && timeout 100 $PY tools/station_cmd.py "echo awake" 70 2>&1 | tail -3)
case "$probe" in
  *"没等到回执"*|*TIMEOUT*|*ENQUEUE_FAIL*) exit 0 ;;          # 通道还没醒: 静默, 不打扰
esac

# 一次取回: 目标文件+同族 .bak_* 的哈希, 再跟一行 @@NAMES@@, 再跟在役同族文件名
out=$(cd "$REPO" && timeout 180 $PY tools/station_cmd.py \
  "cd $DIR; Get-FileHash $F* -Algorithm SHA256 -ErrorAction SilentlyContinue | ForEach-Object { \$_.Hash.Substring(0,16) + '  ' + (Split-Path \$_.Path -Leaf) }; '@@NAMES@@'; Get-ChildItem $FAM -ErrorAction SilentlyContinue | ForEach-Object { \$_.Name }" 120 2>&1)

cur=$(printf '%s\n' "$out" | awk -v f="$F" 'index($2,f)==1 && $2==f {print $1}' | head -1)
good=$(printf '%s\n' "$out" | awk -v w="$WANT" '$1==w {print $2}' | head -1)
have=$(printf '%s\n' "$out" | sed -n '/@@NAMES@@/,$p' | tail -n +2 | tr -d '\r' | grep -E "$FAMRE" | tr '\n' ' ')

if [ "$cur" = "$WANT" ]; then                                  # 好: 记一笔就走
  echo "$(date '+%F %T') OK chan-alive $cur" > "$MARK"; exit 0
fi
if [ -z "$cur" ] && [ -n "$have" ]; then                       # 钉的文件名不在盘上 ⇒ 哨兵过期, 不是文件坏
  echo "⚠️ AOI 哨兵: 哨兵钉的版本已过期 —— 目标 '$F' 在工控机 $DIR 里不存在; 在役的是: $have| 请更新 tools/aoi_channel_sentinel.sh 的 F/WANT"
  echo "stale-pin" > "$MARK"; exit 0
fi
if [ -z "$good" ]; then                                        # 通道醒了但没找到好副本: 必须报
  echo "⚠️ AOI 哨兵: 通道已恢复, 但 10083 文件哈希=$cur(应为 $WANT), 且 .bak_* 里没有可用的完好副本 —— 需要人工介入"
  echo "$cur" > "$MARK"; exit 0
fi
res=$(cd "$REPO" && timeout 180 $PY tools/station_cmd.py \
  "cd $DIR; Copy-Item '$good' '$F' -Force; Start-Sleep -Milliseconds 500; (Get-FileHash '$F' -Algorithm SHA256).Hash.Substring(0,16)" 120 2>&1)
after=$(printf '%s\n' "$res" | grep -oE '[0-9A-F]{16}' | tail -1)
echo "🔧 AOI 哨兵: 通道恢复, 10083 文件曾损坏($cur) → 已用 $good 恢复 → 复核=$after (应为 $WANT)"
echo "$after" > "$MARK"
