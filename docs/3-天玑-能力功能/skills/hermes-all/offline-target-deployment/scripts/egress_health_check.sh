#!/bin/bash
# egress_health_check.sh —— 内网机出口体检，在**收端**（借出口那台）上跑。
# 用法: bash egress_health_check.sh <业务域名> [期望的出口机IP]
#   例: bash egress_health_check.sh open.feishu.cn 192.168.23.66
# 逐项 PASS/FAIL，末行给结论。ICMP 只作 WARN：不少出口只放行 TCP。
set -u
D="${1:-open.feishu.cn}"
EXPECT="${2:-}"
fail=0
ok(){ echo "PASS  $1"; }
no(){ echo "FAIL  $1"; fail=1; }
warn(){ echo "WARN  $1"; }

GW=$(ip route | awk '/^default/{print $3; exit}')
echo "默认网关: ${GW:-无}   期望: ${EXPECT:-任意}"
[ -n "$GW" ] && ok "有默认路由" || no "没有默认路由（出口彻底断了）"
if [ -n "$EXPECT" ] && [ "$GW" != "$EXPECT" ]; then
  no "网关不是期望的出口机 —— 很可能被 NetworkManager 回滚（见 SKILL 铁律五）"
fi
echo "--- 本机网口"; ip -br a | grep -v '^lo' | sed 's/^/      /'

echo "--- 出口机回包"
ping -c1 -W2 223.5.5.5 >/dev/null 2>&1 && ok "ICMP 出网" || warn "ICMP 不通（部分出口只放行 TCP，不阻塞判定）"

echo "--- 解析层"
if getent hosts "$D" >/dev/null 2>&1; then ok "DNS 解析 $D"; else no "DNS 解析失败 $D（先证出口通不通，再谈 resolved.conf）"; fi

echo "--- 传输层"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://$D/" 2>/dev/null)
if [ "$code" != "000" ]; then ok "HTTPS 握手 $D (http=$code)"; else no "HTTPS 不通 $D"; fi

echo
echo "注: 以上全 PASS 也只是「链路通」，交付还要业务接口真跑一次（code=0 + 返回 id）。"
if [ $fail -eq 0 ]; then echo "结论: 出口可用"; else echo "结论: 出口不可用, 先修上面 FAIL 的那层"; fi
exit $fail
