#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""n_moveit 固定轨迹 → **理想**运动规划指令 + 300UPH 时间账。

两条口径, 分开写清:
  A) 保真档 = 现役段表原时间 (GET /api/sim_insert, 392 段逐段 t)      → 313.9 UPH
  B) 理想档 = 同一批段表几何, 逐段按理想剖面重计时:
        t = d/v + v/a  (长段, 梯形)   或   t = 2·sqrt(d/a)  (短段, 三角)
        抬升/横移 v=1000 mm/s a=2000 mm/s²; 下落/插入 v=300 mm/s a=1000 mm/s²
        流程时间 (AOI 每点 0.84×5 / 夹 0.30 / 放 0.30 / 插入 2.70) 一分不压
     理想档 = "指令没问题、机器人按极限执行" 的上界; 真机做不到这个上界, 所以两档都报。

几何真源: 段表 a/b (mm, sim_base) 来自 n_moveit 侧产出 sim_insert.plan[]
点位真源: config/points/cell_points.json (数值与段表 a/b 一致, 可核)
停留下限: 9.85 s (config) —— 4 孔轮转下 dwell = (下一轮拔该孔) − (本轮插完该孔)

用法:
  ./gui-venv311/bin/python tools/l2_moveit_fixed_cycle.py
  ./gui-venv311/bin/python tools/l2_moveit_fixed_cycle.py --json /tmp/ideal.json
"""
from __future__ import annotations

import argparse, json, math, sys, urllib.request

ROOT = '/home/ubuntu/zmax'
API = 'http://127.0.0.1:8797/api/sim_insert'
PROC = {'insert': 2.70, 'grip': 0.30, 'release': 0.30}       # 流程时间, 不随速度变
AOI_PT = 0.84                                                # 每点 AOI
DWELL_MIN = 9.85
AA = 4000.0            # 理想档加速度 mm/s² (300UPH 的临界约 3.5; 见扫档)


def fetch():
    try:
        d = json.loads(urllib.request.urlopen(API, timeout=6).read())
        return d, API
    except Exception as e:                                    # noqa: BLE001
        p = ROOT + '/zmax_data/runtime/traj/sim_insert.json'
        return json.load(open(p, encoding='utf-8')), 'disk (%s)' % e


def ideal_t(d, kind, v_fast=1000.0, a_fast=2000.0, v_slow=300.0, a_slow=1000.0):
    """理想剖面时间: 长段梯形 / 短段三角。down·insert 走慢档。"""
    slow = kind in ('down', 'insert', 'pull')   # 拔模块不能 1000mm/s, 与 AR 页面同口径
    v = v_slow if slow else v_fast
    a = a_slow if slow else a_fast
    if d <= 1e-9:
        return 0.0
    if d > v * v / a:
        return d / v + v / a
    return 2.0 * math.sqrt(d / a)


def analyse(d, mode='ideal'):
    P, L = d['plan'], d['loop']
    cum, t = [], 0.0
    for s in P:
        cum.append(t); t += s['t']
    i0 = next(i for i, s in enumerate(P) if s['k'] == L['ks'][0])
    i1 = max(i for i, s in enumerate(P) if s['k'] == L['ks'][1])
    W = P[i0:i1 + 1]
    base = cum[i0]

    rows, tt, clock = [], 0.0, base
    ins_end, pull_t = {}, {}
    for wi, s in enumerate(W):
        a, b = s.get('a'), s.get('b')
        dist = math.dist(a, b) if (a and b) else 0.0
        # 流程段(插入/夹/放) 与 零位移段(检测/停驻: a==b) 一律用段表自己的 t —— 那不是运动时间, 不重计时
        proc = PROC.get(s['kind'])
        if proc is not None or mode == 'now' or dist <= 1e-9:
            dt = s['t']
        else:
            dt = ideal_t(dist, s['kind'], a_fast=AA, a_slow=AA / 2.0)
        rows.append(dict(kind=s['kind'], label=s.get('label'), a=a, b=b, len_mm=round(dist, 1),
                         t_old=round(s['t'], 3), t=round(dt, 3), t0=round(clock, 2)))
        # 插入完成: 松开且模块留在孔里 (at=hole)
        if s['kind'] == 'release' and s.get('at') == 'hole' and s.get('hole') is not None:
            ins_end[int(s['hole'])] = clock + dt
        # 拔起开始: 夹住(在孔内)
        if s['kind'] == 'grip' and s.get('hole') is not None and '在孔内' in str(s.get('label') or ''):
            pull_t[int(s['hole'])] = clock
        clock += dt
        tt += dt
    cycle = tt
    tact = cycle / L['mods']
    dwells = sorted(round(pull_t[h] + cycle - ins_end[h], 2) for h in ins_end if h in pull_t)
    return dict(cycle=round(cycle, 2), tact=round(tact, 3), uph=round(3600.0 / tact, 1),
                n=len(W), rows=rows, dwells=dwells, mods=L['mods'])


def report(tag, R, detail=False):
    pr = [r for r in R['rows'] if r['kind'] in PROC]
    mv = [r for r in R['rows'] if r['kind'] not in PROC]
    print('\n【%s】%d 段 (运动 %d / 流程 %d)' % (tag, R['n'], len(mv), len(pr)))
    print('  运动 %.2f s + 流程 %.2f s = 循环 %.2f s / %d 件' % (
        sum(r['t'] for r in mv), sum(r['t'] for r in pr), R['cycle'], R['mods']))
    print('  节拍 %.3f s/件 → %.0f UPH   (300UPH 需 ≤ 12.000 s/件, 余量 %.2f s)' % (
        R['tact'], R['uph'], 12.0 - R['tact']))
    print('  停留 %s ~ %s s (下限 %.2f) %s' % (
        R['dwells'][0] if R['dwells'] else '-', R['dwells'][-1] if R['dwells'] else '-',
        DWELL_MIN, '✓' if R['dwells'] and R['dwells'][0] >= DWELL_MIN else '✗'))
    if detail:
        top = sorted([r for r in R['rows'] if r['kind'] not in PROC], key=lambda x: -x['t'])[:6]
        print('  最吃时间的 6 个运动段 (原→理想):')
        for r in top:
            print('    %-24s %6.1f mm   %.2f → %.3f s' % ((r['label'] or r['kind'])[:24],
                                                         r['len_mm'], r['t_old'], r['t']))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='')
    ap.add_argument('--emit', action='store_true', help='把理想档固定轨迹写成 ss_live/fixed_cycle.json')
    ap.add_argument('--a', type=float, default=0.0, help='理想档加速度 mm/s² (默认 4000)')
    a = ap.parse_args()
    d, src = fetch()
    global AA
    if a.a > 0:
        AA = a.a
    A = analyse(d, 'now')
    B = analyse(d, 'ideal')
    print('段表源: %s' % src)
    report('A 保真档 · 现役段表原时间', A)
    report('B 理想档 · 同几何, 极限剖面重计时 (a=%.0f)' % AA, B, detail=True)
    print('\n结论: 同一批几何, 每段按 1000/300 mm/s + 加减速理想剖面跑, 循环 %.2f → %.2f s, '
          '节拍 %.3f → %.3f s/件, UPH %.0f → %.0f。' % (
              A['cycle'], B['cycle'], A['tact'], B['tact'], A['uph'], B['uph']))
    print('  300UPH: %s —— 理想档=指令上界(含加减速), 真机还要再打折。'
          % ('成立' if B['uph'] >= 300 else '不成立'))
    print('\n加速度扫档 (v 不变, 只提 a):')
    for _a in (2000.0, 3000.0, 4000.0, 6000.0, 12000.0):
        AA = _a
        R = analyse(d, 'ideal')
        print('  a=%5.0f mm/s² → 循环 %6.2f s · 节拍 %6.3f s/件 · %4.0f UPH %s' % (
            _a, R['cycle'], R['tact'], R['uph'], '✓' if R['uph'] >= 300 else '✗'))
    AA = a.a if a.a > 0 else 4000.0
    if a.emit:
        out = ROOT + '/zmax_data/ss_live/fixed_cycle.json'
        json.dump(dict(ok=True, src=a_src if (a_src := src) else src,
                       model=dict(v_fast=1000, a_fast=AA, v_slow=300, a_slow=AA / 2.0),
                       cycle_s=B['cycle'], tact_s=B['tact'], uph=B['uph'],
                       mods=B['mods'], dwell_s=B['dwells'], n_seg=B['n'],
                       note='固定轨迹理想档: 几何=段表 a/b(sim_base, mm), 时序=理想剖面重计时; 流程时间用段表值',
                       rows=B['rows']), open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('固定轨迹指令 →', out)
    if a.json:
        json.dump(dict(source=src, now=A, ideal=B,
                       model=dict(v_fast=1000, a_fast=2000, v_slow=300, a_slow=1000,
                                  proc=PROC, aoi_pt=AOI_PT, dwell_min=DWELL_MIN)),
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('时间账 →', a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
