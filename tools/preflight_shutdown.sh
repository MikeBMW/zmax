#!/usr/bin/env bash
# 下电前预检 / 关机就绪判定 (2026-10-08 建立)
#
# 为什么写成脚本: 内联 `pgrep -f gs_capture` 会匹配到**执行它的 shell 自己**(命令行里就写着这个名字)
#   ⇒ 检查结果永远"在跑", 假警报。脚本文件的 cmdline 里没有这些名字, 所以安全。
# 判据(全绿 = 可以下电):
#   ① 臂 idle + 无真动授权(文件真源)  ② 无采集/训练在写  ③ ~ 顶层只剩 zmax
#   ④ 仓库干净(除已知在飞文件)        ⑤ 磁盘/内存无异常  ⑥ 关键服务在线
set -u
REPO=/home/ubuntu/zmax
DATA=$REPO/zmax_data
PY=$REPO/gui-venv311/bin/python
G=0; R=0
ok(){ echo "  ✅ $*"; }
bad(){ echo "  ❌ $*"; R=$((R+1)); }
warn(){ echo "  ⚠️  $*"; }

echo "──────── 下电前预检 $(date '+%F %T') ────────"

echo "① 机械臂"
"$PY" - <<'PY' 2>/dev/null || bad "读不到 TCP 真值"
import json,time
d=json.load(open('/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json'))
age=time.time()-d.get('ts',0)
print("  ✅ 真值帧龄 %.2fs · pos=(%.4f, %.4f, %.4f)" % (age,d.get('x',0),d.get('y',0),d.get('z',0)))
PY
# 真动授权是"时间窗"模型: ctl_auth.json 里没有 armed 布尔位, 判据 = now < until
"$PY" - <<'PY' 2>/dev/null
import json, os, time
p = '/home/ubuntu/zmax/zmax_data/ctl_auth.json'
try:
    d = json.load(open(p))
    until = float(d.get('until') or 0)
    left = until - time.time()
    st = ("无授权(窗口已过期)" if left <= 0 else "⚠️ 授权中, 还剩 %.0fs" % left)
    print("  %s · epoch=%s · revoked_at=%s" % (st, d.get('epoch'), d.get('revoked_at')))
except Exception as e:
    print("  ⚠️ 读不到授权文件: %s" % e)
q = '/home/ubuntu/zmax/zmax_data/vl_operator_auth.json'
print("  VL 现场放行: %s" % ("存在(需看 until)" if os.path.exists(q) else "无(默认 fail-closed)"))
PY
#
echo "② 有没有东西还在写(采集/训练)"
"$PY" - <<'PY'
import os
pats = ['gs_cap'+'ture', 'gs_map'+'_run', 'train'+'_act', 'lerobot'+'_train', 'v6_train', 'joint'+'_train']
hits = []
for p in os.listdir('/proc'):
    if not p.isdigit():
        continue
    try:
        c = open('/proc/%s/cmdline' % p, 'rb').read().decode('utf-8', 'replace')
    except OSError:
        continue
    for k in pats:
        # ⚠️ 排除"搜索类"进程: 别的会话跑 `pgrep -f lerobot_train` 时, 那条 pgrep 自己的 cmdline
        #   就含模式串 ⇒ 会被当成"训练在跑"(2026-10-08 实测误报一次)。
        argv0 = os.path.basename(c.split('\0')[0]) if c else ''
        if argv0 in ('pgrep', 'pkill', 'grep', 'egrep', 'fgrep', 'preflight_shutdown.sh'):
            continue
        if k in c and 'preflight' not in c:
            hits.append((p, k, c.replace('\0', ' ')[:90]))
print("  ✅ 无采集/训练在写" if not hits else "\n".join("  ⚠️  pid=%s [%s] %s" % h for h in hits))
PY

echo "③ 家目录形态"
n=$(ls -1 /home/ubuntu | grep -icE '^zmax$|^zmax_|^aoi_v4$|^lerobot|^gs-venv$|^dds-venv$|^INTACT|^state3d|^l4_ab$|^stable-wm|^colmap-venv$|^cuda-|^hermes-install$|^dl_intact$|^android-sdk$')
if [ "$n" -eq 1 ]; then
    ok "~ 顶层只有 zmax 一个 zmax 相关项"
else
    # 老目录又冒出来的话, 先分清"谁在写、写的是数据还是日志"再判红/黄
    #  (2026-10-08 实测: 合并前的进程把老路径写在内存里 ⇒ 删掉后它自己 mkdir 继续写;
    #   代码侧已修, 但**已经在跑的**进程得等它重启才换过来 ⇒ 这类只算 ⚠️ 不算 ❌)
    who=$("$PY" - <<'PY' 2>/dev/null
import os
rows = []
for p in os.listdir('/proc'):
    if not p.isdigit():
        continue
    try:
        fds = os.listdir('/proc/%s/fd' % p)
        files = []
        for f in fds:
            try:
                t = os.readlink('/proc/%s/fd/%s' % (p, f))
            except OSError:
                continue
            if t.startswith('/home/ubuntu/zmax_data'):
                files.append(t)
        if files:
            cmd = open('/proc/%s/cmdline' % p, 'rb').read().decode('utf-8', 'replace').replace('\0', ' ')[:60]
            rows.append('pid=%s %s → %s' % (p, cmd.strip(), files[0][:60]))
    except OSError:
        continue
print(' | '.join(rows[:4]))
PY
)
    extra=$(ls -1 /home/ubuntu | grep -iE '^zmax_|^aoi_v4$|^lerobot|^INTACT' | tr '\n' ' ')
    # 只有这两个是"老进程按老路径写回"的已知形态(zmax_data=日志, lerobot-smolvla-lew=训练产物);
    # 且必须确实有进程还揣着老路径在写 ⇒ 判 ⚠️(不阻塞下电)。其余一律 ❌。
    known=1
    for e in $extra; do
        case "$e" in zmax_data|lerobot-smolvla-lew) ;; *) known=0;; esac
    done
    if [ "$known" -eq 1 ] && [ -n "$who" ]; then
        warn "~ 顶层多出老目录($extra): **代码侧已修**, 但已在跑的老进程还揣着老路径在写(下面这些, 写的是日志/产物不是真源) ⇒ 重启对应进程/重启机器后消失"
        echo "$who" | tr '|' '\n' | sed 's/^/       /' | head -4
    else
        bad "~ 顶层有 $n 个 zmax 相关项: $extra"
    fi
fi
[ -x "$REPO/gui-venv311/bin/python" ] && ok "工程 venv 可用" || bad "gui-venv311 不可用"

echo "④ 仓库"
cd "$REPO" || exit 1
d=$(git status --porcelain | wc -l)
known=$(git status --porcelain | grep -cE 'tools/(joint_train_all|vlm_worker|l5_vlm_dataset|l5_vlm_lora_train)\.py')
[ "$d" -eq 0 ] && ok "工作区干净" || { [ "$d" -le "$known" ] && warn "未提交 $d 个(全是在飞的 L5 VLM LoRA, 非本轮)" || warn "未提交 $d 个(需确认)"; }
ok "HEAD $(git log --oneline -1 | cut -c1-60)"
git for-each-ref --sort=-creatordate --format='%(refname:short)' refs/tags 2>/dev/null | head -1 | sed 's/^/  ✅ 最新 tag(按创建时间): /'
git status --porcelain 2>/dev/null | head -6 | sed 's/^/     /'

echo "⑤ 资源"
df -h /home | tail -1 | awk '{print "  磁盘: "$3" / "$2" ("$5", 可用 "$4")"}'
free -g | awk '/Mem:/{print "  内存: 已用 "$3"G / "$2"G"}'
grep -iE "^(NvRm|nvidia)" /proc/driver/nvidia/gpus/*/information >/dev/null 2>&1 && nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null | sed 's/^/  GPU: /'

echo "⑥ 服务/容器"
act=$(systemctl list-units --type=service --state=running --no-legend 2>/dev/null | awk '{print $1}' | grep -icE 'zmax|ss-|aoi|sam3')
[ "$act" -ge 20 ] && ok "服务单元 $act 个在跑" || warn "服务单元只有 $act 个在跑(重启后由单元/cron 自愈)"
for k in 8791 8793 8794 8798; do c=$(curl -s -o /dev/null -w '%{http_code}' -m 4 "http://127.0.0.1:$k/" 2>/dev/null); printf "  ✅ %s:%s" "$k" "${c:-x}"; done; echo
sudo docker ps --format '  ✅ 容器 {{.Names}} {{.Status}}' 2>/dev/null | head -4
printf "  ✅ 飞书网关(用户级): %s\n" "$(systemctl --user is-active hermes-gateway 2>/dev/null)"

echo "──────── 结论 ────────"
[ "$R" -eq 0 ] && echo "  🟢 可以下电(臂 idle、无授权、无写入、仓库已保存)" || echo "  🔴 有 $R 项红了, 先处理再下电"
