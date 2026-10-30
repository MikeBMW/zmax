#!/bin/bash
# 550C 一键部署 48Hz 只读记录器 + 实测验收 (链路恢复后跑)
# 用法: bash deploy_rec48.sh          (在 550A 上跑, 走 ssh intel)
set -u
SRC=/home/ubuntu/zmax/_bak_memwire
H=intel

echo "== 0. 连通性 =="
ssh -o ConnectTimeout=6 $H 'echo ok' || { echo "!! 550C 不通, 先插回 USB 网卡"; exit 1; }

echo "== 1. 拷脚本 + unit =="
scp -q $SRC/zmax_rec48.py $H:/home/intel/zmax_550c/tools/zmax_rec48.py || exit 1
scp -q $SRC/zmax-rec48.service $H:/tmp/zmax-rec48.service || exit 1
ssh $H 'chmod +x /home/intel/zmax_550c/tools/zmax_rec48.py
        sudo install -m 644 /tmp/zmax-rec48.service /etc/systemd/system/zmax-rec48.service
        sudo mkdir -p /dev/shm/zmax_rec48 && sudo chown intel:intel /dev/shm/zmax_rec48
        sudo systemctl daemon-reload && sudo systemctl enable --now zmax-rec48 >/dev/null 2>&1
        systemctl is-active zmax-rec48'

echo "== 2. 跑 70s 后实测频率 =="
sleep 70
ssh $H 'cat /dev/shm/zmax_rec48/status.json 2>/dev/null; echo; d=$(ls -dt /home/intel/zmax_map/rec48/*/ep_* 2>/dev/null | head -1); echo "集: $d"; wc -l $d/stream.jsonl $d/frames.jsonl $d/plan.jsonl 2>/dev/null | head -4; echo "关节字段:"; head -1 $d/stream.jsonl | python3 -c "import json,sys;r=json.load(sys.stdin);print(\" joints\",len(r[\"j\"][\"name\"]) if r.get(\"j\") else None,\"个:\",(r[\"j\"][\"name\"][:8] if r.get(\"j\") else None));print(\" gripper\",r.get(\"g\"));print(\" 位姿\",{k:round(v,4) for k,v in r[\"pose\"].items() if k in \"xyz\"})"'

echo "== 3. 判据 =="
ssh $H 'python3 -c "
import json
s=json.load(open(\"/dev/shm/zmax_rec48/status.json\"))
ok = s[\"pose_hz\"]>=40 and s[\"joints_hz\"]>=40 and s[\"frames\"]>0 and s[\"skew_p50_ms\"]<25
print(\" pose %.1fHz  joints %.1fHz  帧 %d  skew_p50 %.1fms  plan %d  ->  %s\" % (s[\"pose_hz\"],s[\"joints_hz\"],s[\"frames\"],s[\"skew_p50_ms\"],s[\"plan_updates\"],\"PASS\" if ok else \"FAIL\"))
"'
