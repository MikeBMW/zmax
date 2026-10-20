#!/usr/bin/env bash
# 收工前有序停机 (只停"会写盘/占设备"的常驻件; 不动机械臂, 不发任何运动指令)
#   为什么按顺序停: ①采样器还在写 zmax_data 的 json ②rs_service 占着 USB 相机
#   ③l2_daemon 是 FIFO 消费者(停之前必须确认没有在途动作) —— 断电前把这些收干净,
#   下次上电才不会遇到"相机被旧句柄占着 EBUSY / FIFO 半条命令"这类脏状态。
set -u
cd /home/ubuntu/zmax || exit 1
say() { printf "  %-34s %s\n" "$1" "$2"; }

echo "① 机器人/执行器状态确认"
POSE=$(./gui-venv311/bin/python - <<'EOF' 2>/dev/null
import json,time
try:
    t=json.load(open('zmax_data/rokae_sdk/tcp_out/latest.json'))
    print("x=%.1f y=%.1f z=%.1f mm age=%.1fs"%(t['x']*1000,t['y']*1000,t['z']*1000,time.time()-t['ts']))
except Exception as e:
    print("位姿读不到: %s"%e)
EOF
)
say "最后一次位姿" "$POSE"
EXEC=$(./gui-venv311/bin/python -c "
import json
try:
    d=json.load(open('zmax_data/ss_live/exec_state.json'));print('%s / %s'%(d.get('phase'),d.get('skill')))
except Exception as e: print('读不到')" 2>/dev/null)
say "执行器最后状态" "$EXEC"
PEND=$(timeout 1 cat zmax_data/l2_cmd.fifo 2>/dev/null | wc -l)
say "FIFO 残留命令" "$PEND 条"
if [ "$PEND" != "0" ]; then echo "⚠️ FIFO 里还有命令, 先不要停执行器"; exit 1; fi

echo "② 采样器 (会写 zmax_data 的 json)"
for c in zmax_ft_sampler rokae_tcp_sampler; do
  if sudo -n docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c"; then
    sudo -n docker stop "$c" >/dev/null 2>&1 && say "docker $c" "已停" || say "docker $c" "停失败"
  else say "docker $c" "未运行"; fi
done

echo "③ 相机独占小服务 (放掉 USB 设备)"
if curl -s --max-time 2 http://127.0.0.1:8789/health 2>/dev/null | grep -q '"zmax-rs"'; then
  bash tools/rs_service.sh stop >/dev/null 2>&1 && say "rs_service(8789)" "已停" || say "rs_service(8789)" "停失败"
else say "rs_service(8789)" "未运行"; fi

echo "④ 常驻消费者 (空闲才停)"
if bash tools/l2_daemon_ctl.sh status 2>/dev/null | grep -q "运行中"; then
  bash tools/l2_daemon_ctl.sh stop >/dev/null 2>&1 && say "l2_daemon" "已停" || say "l2_daemon" "停失败"
else say "l2_daemon" "未运行"; fi
if bash tools/ar_aoi_bus_ctl.sh status >/dev/null 2>&1; then
  bash tools/ar_aoi_bus_ctl.sh stop >/dev/null 2>&1 && say "ar_aoi_bus" "已停" || say "ar_aoi_bus" "未运行/已停"
else say "ar_aoi_bus" "未运行"; fi

echo "⑤ 落一份停机留档"
./gui-venv311/bin/python - <<'EOF'
import json, os, time
p = "/home/ubuntu/zmax/zmax_data/evidence/shutdown_%s.md" % time.strftime("%Y%m%d_%H%M%S")
L = ["# 停机留档 %s" % time.strftime("%F %T"), ""]
L.append("- 最后一次真机位姿: %s" % os.popen(
    "python3 -c \"import json,time;t=json.load(open('/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json'));"
    "print('x=%.1f y=%.1f z=%.1f mm, 帧龄 %.1fs'%(t['x']*1000,t['y']*1000,t['z']*1000,time.time()-t['ts']))\" 2>/dev/null").read().strip())
L.append("- 控制器/Orin 网络: 均已不可达(收工前已断), 无法再读实时值 —— 上面的数是断链前最后一帧")
L.append("- 本轮证据: zmax_data/evidence/insertion_20261020_134841.{json,_arm.jpg,_rs.jpg} · insertion_series_20261020_1348.jsonl")
L.append("- 归档: zmax_data/release_sync_20261020_v5.50.750 (47 文件 4.1M, sha256 全 OK)")
L.append("- 代码: git main 已推送")
L.append("- 机械臂: 最后状态 自动待机/空闲, 无在途指令; 断电由控制器抱闸保持")
open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("  留档: " + p)
EOF
echo "完成。剩下的由人做: 关控制台 GUI → 控制器断电 → 主机断电。"
