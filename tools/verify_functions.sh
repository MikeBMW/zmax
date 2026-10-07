#!/usr/bin/env bash
# verify_functions.sh — Z-MAX 全功能链回归 (2026-10-08 家目录整合后)
#
# 为什么要有它:
#   整合/清理后最阴的坑不是语法错, 而是**已经在跑的老进程把老路径字面量揣在内存里** ——
#   代码看着是新的、语法全绿, 功能却整体失效(2026-10-08 实测: SDK 腿就是这样, 页面报
#   「已下发(真动)」但机器人不动)。所以本脚本对每条关键服务同时验三件事:
#     ① 进程在不在 / 端口通不通(功能面)
#     ② FIFO/状态文件/真值是否新鲜(数据面)
#     ③ 进程启动时间 vs 它依赖的代码文件 mtime(内存面: 老进程 = 老路径)
# 用法: bash tools/verify_functions.sh    (只读, 不改任何东西)
set -u
REPO=/home/ubuntu/zmax
PY="$REPO/gui-venv311/bin/python"
PASS=0; FAIL=0
ok()  { echo "  ✅ $*"; PASS=$((PASS+1)); }
bad() { echo "  ❌ $*"; FAIL=$((FAIL+1)); }
warn(){ echo "  ⚠️  $*"; }
hdr() { echo; echo "── $* ──"; }

# 进程启动时间(epoch) 与 代码 mtime 比较: 进程比代码老 => 内存里可能是老代码(老路径)
stale_check() { # $1=服务名 $2=pgrep 模式 $3...=依赖的代码文件
    local name="$1"; shift
    local pat="$1"; shift
    local pid st code_new=0 f m
    pid=$(pgrep -f "$pat" 2>/dev/null | head -1)
    [ -z "$pid" ] && { bad "$name: 进程不在 (pgrep -f '$pat')"; return; }
    st=$(date -d "$(ps -o lstart= -p "$pid" 2>/dev/null)" +%s 2>/dev/null || echo 0)
    for f in "$@"; do
        [ -f "$REPO/$f" ] || continue
        m=$(stat -c %Y "$REPO/$f" 2>/dev/null || echo 0)
        [ "$m" -gt "$code_new" ] && code_new="$m"
    done
    if [ "$st" -gt 0 ] && [ "$code_new" -gt 0 ] && [ "$st" -lt "$code_new" ]; then
        warn "$name: pid=$pid 起于 $(date -d @$st '+%m-%d %H:%M') **早于**代码改动 $(date -d @$code_new '+%m-%d %H:%M') ⇒ 内存里可能是老路径, 需重启"
    else
        ok "$name: pid=$pid 起于 $(date -d @$st '+%m-%d %H:%M') ≥ 代码改动 ⇒ 加载的是新代码"
    fi
}

echo "════════ Z-MAX 功能链回归 $(date '+%F %T') ════════"

hdr "① 网络服务面(端口/HTTP)"
for pp in 8790 8791 8793 8794 8795 8796 8797 8798 8891 8893; do
    if ss -ltn 2>/dev/null | grep -q ":$pp "; then
        code=$(curl -s -m 4 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$pp/" 2>/dev/null)
        case "$code" in
            200|301|302|403|404) ok "端口 $pp 在听 (HTTP $code)";;
            000) ok "端口 $pp 在听 (HTTP 无响应: 非 HTTP 服务)";;
            *) warn "端口 $pp 在听 但 HTTP $code";;
        esac
    else
        warn "端口 $pp 没在听"
    fi
done

hdr "② 站台 8793 /station/status(数据面)"
curl -s -m 6 http://127.0.0.1:8793/station/status 2>/dev/null > /tmp/vf_st.json
if [ -s /tmp/vf_st.json ]; then
    "$PY" - <<'PY'
import json
d = json.load(open('/tmp/vf_st.json'))
c = (d.get('ctl') or {})
tcp = c.get('tcp') or {}
age = float(tcp.get('age_s') or 999)
print("  %s 真值位姿 xyz=%s 帧龄=%.2fs stale=%s" % ("✅" if (age < 3 and not tcp.get('stale')) else "❌",
      [round(v,4) for v in (tcp.get('xyz') or [])], age, tcp.get('stale')))
e = c.get('exec') or {}
print("  %s L2 执行器 online=%s pid=%s skills=%s log_age=%.0fs" % ("✅" if e.get('online') else "❌",
      e.get('online'), e.get('pid'), e.get('skills'), float(e.get('log_age_s') or -1)))
a = c.get('auth') or {}
print("  %s 授权 armed=%s epoch=%s" % ("✅" if a.get('armed') else "⚠️", a.get('armed'), a.get('epoch')))
print("  ✅ 执行腿 transport=%s" % c.get('move_transport'))
st = d.get('stats') or {}
off = [k for k, v in st.items() if isinstance(v, dict) and v.get('online') is False]
print("  %s 相机格: 在线 %d, 离线 %s" % ("✅" if not off else "⚠️",
      sum(1 for v in st.values() if isinstance(v, dict) and v.get('online')), off or '无'))
PY
else
    bad "站台 /station/status 无响应"
fi

hdr "③ L2 执行器 + 命令 FIFO + 日志新鲜度"
L2F="$REPO/zmax_data/l2_cmd.fifo"
[ -p "$L2F" ] && ok "命令 FIFO 存在 $L2F" || bad "命令 FIFO 缺失 $L2F"
if pgrep -f "tools/l2_daemon.py" >/dev/null 2>&1; then
    LP=$(pgrep -f "tools/l2_daemon.py" | head -1)
    LA=$(( $(date +%s) - $(stat -c %Y "$REPO/zmax_data/l2_daemon.log" 2>/dev/null || echo 0) ))
    [ "$LA" -lt 86400 ] && ok "L2 在跑 pid=$LP, 日志龄 ${LA}s" || warn "L2 在跑 pid=$LP 但日志已 ${LA}s 未更新"
else
    bad "L2 执行器没在跑"
fi

hdr "④ SDK 执行腿(8798 + 代理 FIFO + 心跳)"
SDKF="$REPO/zmax_data/rokae_sdk/cmd_arm.fifo"
[ -p "$SDKF" ] && ok "代理 FIFO 存在" || bad "代理 FIFO 缺失 $SDKF"
HB="$REPO/zmax_data/rokae_sdk/tcp_out/agent_heartbeat.json"
if [ -s "$HB" ]; then
    "$PY" - "$HB" <<'PY'
import json, sys, time
d = json.load(open(sys.argv[1]))
t = d.get('t') or 0
try: age = time.time() - float(t)
except Exception: age = -1
print("  %s 代理心跳: agent=%s state=%s 龄=%.1fs" % ("✅" if 0 <= age < 30 else "⚠️",
      d.get('agent'), str(d.get('state'))[:40], age))
print("  %s 容器内已登录控制器: pose=%s alarms=%s" % ("✅" if d.get('pose') else "⚠️",
      str(d.get('pose'))[:60], str(d.get('alarms'))[:40]))
PY
else
    bad "代理心跳文件缺失"
fi
"$PY" - <<'PY'
import sys, os
sys.path.insert(0, '/home/ubuntu/zmax/tools/rokae')
try:
    import l2_transport_sdk as t
    print("  %s SDK 腿路径解析: FIFO=%s exists=%s" % ("✅" if os.path.exists(t.FIFO) else "❌",
          t.FIFO, os.path.exists(t.FIFO)))
except Exception as e:
    print("  ❌ SDK 腿模块导入失败: %s" % e)
PY

hdr "⑤ 老进程揣老路径探测(进程启动时间 vs 代码 mtime)"
stale_check "站台 cam_live_stream" "tools/cam_live_stream.py" "tools/cam_live_stream.py"
stale_check "L2 执行器" "tools/l2_daemon.py" "tools/l2_daemon.py" "tools/rokae/l2_transport_sdk.py"
stale_check "SDK 动作服务" "tools/sdk_motion_service.py" "tools/sdk_motion_service.py"
stale_check "VL 快层" "tools/vl_safety_fast.py" "tools/vl_safety_fast.py"

hdr "⑥ 容器 / 服务单元 / 网关 / 磁盘"
for c in zmax-arm-raw rokae_tcp_sampler zmax-sdk-arm-agent ss-remote-tap; do
    sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c" && ok "容器 $c up" || bad "容器 $c 不在"
done
NF=$(systemctl --user list-units --state=failed --no-legend 2>/dev/null | wc -l)
[ "$NF" -eq 0 ] && ok "用户级服务无 failed 单元" || warn "用户级 failed 单元 $NF 个"
systemctl --user is-active hermes-gateway >/dev/null 2>&1 && ok "飞书网关 active" || bad "飞书网关未 active"
DISK=$(df / | awk 'NR==2{print $3}')
ok "磁盘根已用 $DISK"

hdr "⑦ 家目录形态(整合验收)"
EXTRA=$(ls -1 /home/ubuntu | grep -iE '^zmax_|^lerobot|^INTACT|^gs-venv$|^dds-venv$' | grep -v '^zmax$' | tr '\n' ' ')
[ -z "$EXTRA" ] && ok "~ 顶层只有 zmax" || warn "~ 顶层多出: $EXTRA (老进程写回)"

echo
echo "════════ 结论: ✅ $PASS 项通过 · ❌ $FAIL 项失败 ════════"
[ "$FAIL" -eq 0 ] && echo "  🟢 功能链无阻断项" || echo "  🔴 有 $FAIL 项需处理"
