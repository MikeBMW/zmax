#!/usr/bin/env bash
# ============================================================================
#  Z-MAX 服务站统一管理入口   (拷到 /usr/local/bin/zmaxctl 后 chmod +x)
# ----------------------------------------------------------------------------
#  zmaxctl status          全量状态(本地 systemd + 代理 + 未就位)
#  zmaxctl health          逐端口探测, 只答活/死 + 耗时
#  zmaxctl log    <name>   跟随日志(短名自动补 zmax- 前缀)
#  zmaxctl start|stop|restart <name>
#  zmaxctl ports           端口占用总表
#  zmaxctl list            只列服务名
#
#  ⚠ 下面三个清单是唯一需要手改的地方, 新增服务时同步维护。
# ============================================================================

set -uo pipefail

# 本地 systemd 单元: 单元名:端口:说明  (端口写 0 表示没有 HTTP 端口)
SYSTEMD_UNITS="
zmax-agent-hub:8794:Agent中枢
zmax-se3-geom:8804:SE3几何
zmax-cy-slice:8805:Calabi-Yau切片
zmax-l2-watch:8807:L2过程监控
zmax-mod-overlay:8808:模块叠加
zmax-dashboard:8799:产品大屏
zmax-gs-render-stream:8816:3DGS渲染
zmax-cam-relay:8901:相机中继
zmax-aoi-bypass:0:AOI旁路
"

# 反向代理: 端口:目标主机:目标端口:说明
PROXY_ENTRIES="
10082:工控机.23:10082:AOI金手指
10083:工控机.23:10083:AOI表面
8792:Orin.66:8792:Orin相机帧
"

# 未就位: 端口:名称:原因
MISSING_ENTRIES="
8793:4060相机六路:源头 4060 的 USB 相机
8898:臂相机YOLO:源头未起
8809:ROS深度流:源头未起
8813:训练中继:源头未起
"

C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_DIM=$'\033[90m'; C_CY=$'\033[36m'; C_RST=$'\033[0m'

http_code() { curl -s -m 4 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$1/" 2>/dev/null || echo "000"; }

cmd_status() {
    echo "${C_CY}══════════════════════════════════════════════════════════${C_RST}"
    echo "${C_CY} Z-MAX 服务站状态   $(date '+%Y-%m-%d %H:%M:%S')   $(hostname)${C_RST}"
    echo "${C_CY}══════════════════════════════════════════════════════════${C_RST}"
    echo
    echo "${C_CY}【本地进程 · systemd】${C_RST}"
    printf "  %-22s %-9s %-10s %s\n" "单元" "状态" "端口/HTTP" "说明"
    echo "  ────────────────────────────────────────────────────────"
    while IFS=: read -r unit port desc; do
        [ -z "$unit" ] && continue
        act=$(systemctl is-active "$unit" 2>/dev/null)
        if [ "$act" = "active" ]; then ic="${C_OK}●${C_RST}"; else ic="${C_BAD}○${C_RST}"; fi
        hp="-"; [ "$port" != "0" ] && hp="/$(http_code "$port")"
        printf "  %s %-20s %-9s %-6s%-5s %s\n" "$ic" "${unit#zmax-}" "$act" "$port" "$hp" "$desc"
    done <<< "$SYSTEMD_UNITS"
    echo
    echo "${C_CY}【反向代理 · 硬件在别的机器】${C_RST}"
    while IFS=: read -r port host hostport desc; do
        [ -z "$port" ] && continue
        hp=$(http_code "$port")
        if [ "$hp" = "000" ]; then ic="${C_BAD}✗${C_RST}"; else ic="${C_OK}✓${C_RST}"; fi
        printf "  %s %-6s %-14s %-8s %s\n" "$ic" "$port" "$host" "$hp" "$desc"
    done <<< "$PROXY_ENTRIES"
    echo
    echo "${C_CY}【未就位】${C_RST}"
    while IFS=: read -r port name why; do
        [ -z "$port" ] && continue
        printf "  ${C_DIM}·${C_RST} %-6s %-18s ${C_DIM}%s${C_RST}\n" "$port" "$name" "$why"
    done <<< "$MISSING_ENTRIES"
    echo
}

cmd_health() {
    echo "端口   结果      耗时"
    echo "─────────────────────────"
    for port in $(echo "$SYSTEMD_UNITS" | cut -d: -f2 | grep -v '^0$') $(echo "$PROXY_ENTRIES" | cut -d: -f1); do
        t0=$(date +%s%3N); hp=$(http_code "$port"); t1=$(date +%s%3N)
        if [ "$hp" = "000" ]; then printf "%-6s ${C_BAD}死${C_RST} %7dms\n" "$port" $((t1-t0))
        else printf "%-6s ${C_OK}活${C_RST} %3s %4dms\n" "$port" "$hp" $((t1-t0)); fi
    done
}

cmd_ports() {
    # 本脚本里唯一未在目标机实测过的子命令。
    # 旧写法用 awk 的 match($0, /.../, m) 三参数形式 —— 那是 gawk 专有,
    # 目标机 awk 若是 mawk 会静默给不出进程名; 这里改用 $6 列规避。
    # 真要定端口归属, 直接 `sudo ss -ltnp | grep <端口>` 最稳。
    echo "端口   进程"
    echo "────────────────────────────"
    sudo ss -ltnp 2>/dev/null | awk 'NR>1{split($4,a,":"); p=a[length(a)]; if(p!="") print p, $6}' | sort -n -u | head -40
}

resolve_unit() { case "$1" in zmax-*) echo "$1";; *) echo "zmax-$1";; esac; }

cmd_do() {
    local action="$1" name="$2" unit
    unit=$(resolve_unit "$name")
    if ! systemctl list-unit-files 2>/dev/null | grep -q "^${unit}.service"; then
        echo "${C_BAD}没有这个单元: ${unit}${C_RST}"
        echo "可用: $(echo "$SYSTEMD_UNITS" | cut -d: -f1 | tr '\n' ' ')"
        return 1
    fi
    sudo systemctl "$action" "$unit"
    sleep 1
    printf "  %-24s %s\n" "$unit" "$(systemctl is-active "$unit" 2>/dev/null)"
}

cmd_log() { sudo journalctl -u "$(resolve_unit "$1")" -n 60 -f --no-pager; }
cmd_list() { echo "$SYSTEMD_UNITS" | cut -d: -f1 | sed 's/^zmax-//' | grep -v '^$'; }

case "${1:-status}" in
    status|st)  cmd_status ;;
    health|h)   cmd_health ;;
    ports|p)    cmd_ports ;;
    list|ls)    cmd_list ;;
    start|stop|restart|enable|disable)
        [ -z "${2:-}" ] && { echo "用法: zmaxctl $1 <name>"; exit 1; }
        cmd_do "$1" "$2" ;;
    log|logs)   [ -z "${2:-}" ] && { echo "用法: zmaxctl log <name>"; exit 1; }
        cmd_log "$2" ;;
    *)          echo "用法: zmaxctl {status|health|ports|list|start|stop|restart|log} [name]" ;;
esac
