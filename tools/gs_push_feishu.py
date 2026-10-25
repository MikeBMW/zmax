#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_push_feishu.py — 在笔记本上跑: 从 intel 取「已训好的 3DGS 资产」→ 发飞书。

链路: 笔记本 → 公网跳板 39.102.211.79:22022 → intel 192.168.23.70 (paramiko 两跳, 只读+置标记)
判据: 只推 <asset>/status.json 里 ready=true 且 sent=false 的目录; 推完把 sent 置 true(幂等, 不重发)
用法: python3 gs_push_feishu.py [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import paramiko

def _secret(key: str, default: str = "") -> str:
    """口令只从环境变量或 zmax_data/secrets/zmax.env(600, 不入库) 取 —— 不许再写明文进仓库。"""
    v = os.environ.get(key)
    if v:
        return v
    p = os.path.expanduser("~/zmax/zmax_data/secrets/zmax.env")
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return default


JUMP = dict(hostname=os.environ.get("ZMAX_JUMP_HOST", "47.93.88.143"),
            port=int(os.environ.get("ZMAX_JUMP_PORT", "22022")),
            username=os.environ.get("ZMAX_JUMP_USER", "tashan"),
            password=_secret("ZMAX_ORIN_PW"))
INTEL = dict(hostname=os.environ.get("ZMAX_INTEL_HOST", "192.168.23.70"),
             username="intel", password=_secret("ZMAX_INTEL_PW"))
ASSETS = '/home/intel/zmax_map/gs_assets'
LOCAL = os.path.expanduser('~/zmax_data/deliverables/gs_assets')
PY = os.path.expanduser('~/zmax/gui-venv311/bin/python')
SENDER = os.path.expanduser('~/zmax/tools/feishu_send_file.py')


def intel_client():
    j = paramiko.SSHClient()
    j.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    j.connect(JUMP['hostname'], port=JUMP['port'], username=JUMP['username'],
              password=JUMP['password'], timeout=15)
    tr = j.get_transport()
    ch = tr.open_channel('direct-tcpip', (INTEL['hostname'], 22), ('127.0.0.1', 0))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(INTEL['hostname'], username=INTEL['username'], password=INTEL['password'],
              sock=ch, timeout=20)
    return j, c


def sh(c, cmd, t=30):
    i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode(errors='ignore').strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    os.makedirs(LOCAL, exist_ok=True)
    try:
        j, c = intel_client()
    except Exception as ex:
        print('连不上 intel(跳板/内网?): %s %s' % (type(ex).__name__, str(ex)[:90]))
        return 2
    st = sh(c, 'cat %s/state.json 2>/dev/null' % ASSETS)
    print('编排器状态:', st.replace('\n', ' ')[:300] if st else '(无)')
    dirs = [d for d in sh(c, 'ls -1 %s 2>/dev/null' % ASSETS).split('\n')
            if d and d[0].isdigit()]
    todo = []
    for d in sorted(dirs):
        raw = sh(c, 'cat %s/%s/status.json 2>/dev/null' % (ASSETS, d))
        if not raw:
            continue
        try:
            m = json.loads(raw)
        except Exception:
            continue
        if m.get('ready') and not m.get('sent'):
            todo.append((d, m))
    if not todo:
        print('无待推送资产(未训好/已推送过)')
        j.close()
        return 0
    sf = paramiko.SFTPClient.from_transport(c.get_transport())
    for d, m in todo:
        ld = os.path.join(LOCAL, d)
        os.makedirs(ld, exist_ok=True)
        remote = ['gs.splat', 'gs.ply']
        rd = sh(c, 'ls -1 %s/%s/renders 2>/dev/null' % (ASSETS, d)).split('\n')
        remote += ['renders/' + n for n in rd[:3] if n.endswith('.png')]
        got = []
        for rel in remote:
            try:
                os.makedirs(os.path.dirname(os.path.join(ld, rel)) or ld, exist_ok=True)
                sf.get('%s/%s/%s' % (ASSETS, d, rel), os.path.join(ld, rel))
                got.append(rel)
            except Exception as ex:
                print('  拉取失败', rel, type(ex).__name__)
        if not got:
            print('  目录 %s 无可用产物, 跳过' % d)
            continue
        txt = ('3DGS 地图资产 %s｜视点 %s · 帧 %s · 位姿跨度 %smm · %s 步\n'
               'intel Arc B390 (SYCL/XPU) 训练\n附: %s'
               % (d, m.get('views'), m.get('frames'), m.get('pose_span_mm'),
                  m.get('steps'), ', '.join(got)))
        if a.dry:
            print('[dry] 将发送:', txt.replace('\n', ' | ')[:200])
            continue
        paths = [os.path.join(ld, g) for g in got]
        r = subprocess.run([PY, SENDER, '--text', txt, '--file'] + paths,
                           capture_output=True, text=True)
        ok = r.returncode == 0 and 'success' in (r.stdout + r.stderr).lower()
        print('  发送 %s → %s' % (d, 'OK' if ok else 'FAIL'))
        print('   ', (r.stdout or r.stderr).strip().replace('\n', ' ')[:300])
        if ok:
            m['sent'] = True
            m['sent_at'] = time.strftime('%F %T')
            sf.putfo(__import__('io').BytesIO(json.dumps(m, ensure_ascii=False, indent=1).encode()),
                     '%s/%s/status.json' % (ASSETS, d))
    sf.close()
    j.close()
    c.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
