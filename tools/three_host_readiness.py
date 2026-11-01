#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三机就绪核对 —— 550B 代码通 / 550A 训练通 / 550C 部署通(打 MAC)。

老倪 2026-11-01: 「550B 代码要通, 550A 训练要通, 550C 部署要通打 MAC, 我只要结果。」

每一项都**真跑**, 不写"应该没问题":
  550B 代码通   py_compile 全仓 .py → 失败数; 核心模块 import; 跑 verify_ar_chain.py 取 PASS/FAIL
  550A 训练通   训练入口 --help 退出码; 数据/配置存在性; torch CUDA 设备; (可选)1 步真训
  550C 部署通   git sha + 版本号 + 交付件 sha256 + 本机 MAC ⇒ 部署清单 (可直接贴给现场)

用法:
  ./gui-venv311/bin/python tools/three_host_readiness.py
  ./gui-venv311/bin/python tools/three_host_readiness.py --train-smoke   # 真跑 1 步训练
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = '/home/ubuntu/zmax'
PY = ROOT + '/gui-venv311/bin/python'
OUT = ROOT + '/zmax_data/ss_live/three_host_readiness.json'


def run(cmd, timeout=180, cwd=ROOT):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, timeout=timeout,
                           capture_output=True, text=True)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except subprocess.TimeoutExpired:
        return 124, 'timeout %ss' % timeout


def code_gate():
    files = glob.glob(ROOT + '/src/**/*.py', recursive=True) + glob.glob(ROOT + '/tools/**/*.py', recursive=True)
    bad = []
    for f in files:
        rc, out = run([PY, '-m', 'py_compile', f], timeout=60)
        if rc != 0:
            bad.append(dict(file=f.replace(ROOT + '/', ''), err=out.strip().splitlines()[-1][:120] if out.strip() else ''))
    imp_rc, imp_out = run([PY, '-c',
                           'import sys; sys.path.insert(0,"src"); '
                           'import lerobot.middleware.node, lerobot.middleware.project, '
                           'lerobot.engineering.nodes.library, lerobot.engineering.nodes.geo_plan_impl, '
                           'lerobot.policies.left_right.state_space.su2; print("IMPORT_OK")'], timeout=180)
    arc_rc, arc_out = run([PY, 'tools/verify_ar_chain.py'], timeout=180)
    import re as _re
    m = _re.search(r'判据\s*(\d+)\s*PASS\s*/\s*(\d+)\s*FAIL', arc_out)
    n_pass, n_fail = (int(m.group(1)), int(m.group(2))) if m else (0, -1)   # -1 = 没解析到, 别当 0
    return dict(files=len(files), compile_fail=len(bad), bad=bad[:8],
                imports=('IMPORT_OK' in imp_out), import_rc=imp_rc,
                ar_chain_rc=arc_rc, ar_chain_pass=n_pass, ar_chain_fail=n_fail,
                ok=(len(bad) == 0 and 'IMPORT_OK' in imp_out and arc_rc == 0 and n_fail == 0))


def train_gate(smoke=False):
    entry = ROOT + '/tools/joint_train_all.py'
    exists = os.path.exists(entry)
    help_rc, help_out = run([PY, entry, '--help'], timeout=240) if exists else (1, 'no entry')
    data = {k: os.path.exists(os.path.join(ROOT, k)) for k in
            ('data', 'config/tasks/tasks.json', 'config/calib/zmax_manifold.json')}
    gpu = {}
    rc, out = run([PY, '-c',
                   'import torch,json;print(json.dumps({"cuda":torch.cuda.is_available(),'
                   '"n":torch.cuda.device_count(),'
                   '"name":(torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""),'
                   '"torch":torch.__version__}))'], timeout=180)
    if rc == 0 and out.strip():
        try:
            gpu = json.loads(out.strip().splitlines()[-1])
        except Exception:                                                  # noqa: BLE001
            gpu = dict(raw=out.strip()[:120])
    smoke_rc, smoke_out = (None, '')
    if smoke:
        smoke_rc, smoke_out = run([PY, entry, '--only', 'L2', '--steps', '1'], timeout=900)
    return dict(entry=entry.replace(ROOT + '/', ''), entry_exists=exists,
                help_rc=help_rc, help_ok=(help_rc == 0),
                data=data, gpu=gpu, smoke_rc=smoke_rc,
                smoke_tail=smoke_out.strip().splitlines()[-3:] if smoke_out else [],
                ok=(exists and help_rc == 0 and all(data.values())))


def deploy_gate():
    rc, sha = run(['git', 'rev-parse', '--short', 'HEAD'])
    rc2, ver = run([PY, '-c',
                    'import json,sys;d=json.load(open("config/platform/zmax_perf_spec.json"));'
                    'print(next((str(d[k]) for k in ("version","ver","app_version") if k in d),"?"))'])
    macs = []
    for nic in sorted(os.listdir('/sys/class/net')):
        if nic == 'lo':
            continue
        try:
            macs.append(dict(nic=nic, mac=open('/sys/class/net/%s/address' % nic).read().strip()))
        except Exception:                                                  # noqa: BLE001
            pass
    arts = []
    for pat in ('docs/1-天枢-产品边界/deliverables/2-机器人方案/*.pptx',
                'docs/1-天枢-产品边界/deliverables/2-机器人方案/*.pdf'):
        for f in glob.glob(os.path.join(ROOT, pat)):
            h = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:16]
            arts.append(dict(file=os.path.basename(f), mb=round(os.path.getsize(f) / 1048576, 2), sha256_16=h))
    return dict(git=sha.strip(), version=ver.strip(), macs=macs, artifacts=arts,
                ok=bool(macs) and sha.strip() != '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train-smoke', action='store_true')
    ap.add_argument('--json', default='')
    a = ap.parse_args()

    print('三机就绪核对 (550B 代码 / 550A 训练 / 550C 部署+MAC)')
    print('=' * 96)
    t0 = time.perf_counter()
    b = code_gate()
    print('550B 代码通 : %s · .py %d 个 · 编译失败 %d · import %s · AR 链 %d PASS / %d FAIL'
          % ('✓ 通' if b['ok'] else '✗ 不通', b['files'], b['compile_fail'],
             '✓' if b['imports'] else '✗', b['ar_chain_pass'], b['ar_chain_fail']))
    for x in b['bad']:
        print('     ✗ %s  %s' % (x['file'], x['err']))
    tr = train_gate(a.train_smoke)
    print('550A 训练通 : %s · 入口 %s(存在=%s, --help rc=%s) · 数据 %s · GPU %s'
          % ('✓ 通' if tr['ok'] else '✗ 不通', tr['entry'], tr['entry_exists'], tr['help_rc'],
             '✓' if all(tr['data'].values()) else '✗', tr['gpu']))
    if tr['smoke_rc'] is not None:
        print('     1 步真训 rc=%s · %s' % (tr['smoke_rc'], tr['smoke_tail']))
    d = deploy_gate()
    print('550C 部署通+MAC: %s · git %s · 版本 %s · 网卡 %s · 交付件 %d'
          % ('✓ 通' if d['ok'] else '✗ 不通', d['git'], d['version'],
             ', '.join('%s=%s' % (m['nic'], m['mac']) for m in d['macs']),
             len(d['artifacts'])))
    for x in d['artifacts']:
        print('     %-52s %5.2f MB  sha256 %s' % (x['file'], x['mb'], x['sha256_16']))
    rep = dict(ts=time.strftime('%Y-%m-%d %H:%M:%S'), wall_s=round(time.perf_counter() - t0, 1),
               code_550b=b, train_550a=tr, deploy_550c=d,
               all_ok=bool(b['ok'] and tr['ok'] and d['ok']))
    print('=' * 96)
    print('结论: %s (%.1fs)' % ('三机全通' if rep['all_ok'] else '有缺口, 见上', rep['wall_s']))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rep, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.json:
        json.dump(rep, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('清单 →', OUT)
    return 0 if rep['all_ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
