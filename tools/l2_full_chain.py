#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 全节点联通器 —— 把画布 L2 七带的 31 个节点按连线拓扑逐拍跑一遍, 结果写进 AR 场景。

真源:
  节点集合/连线   data/database/zmax/sources/canvas/state_space_obs.json (nodes + links, 221 条)
  节点实现       src/lerobot/middleware/nodes/<mod>.py::compute(ctx)  →  lerobot.engineering.registry
  工程配置点位   config/points/cell_points.json (sim_base · mm)  —— 经 points_source 读取, 与 plan 节点同源
  工艺编排       🧭 测地线规划引导 (n_geodesic) 的块输出; 不可用则如实标注, 不自造顺序
  AR 输出        zmax_data/ss_live/ar_cmd_chain.json 的 annot 分区 (ar_bridge.update)

不做的事:
  · 不下发任何真机指令 (不下发 = 不调 8793 / 不碰 l2_daemon)
  · 节点缺输入/实现异常 → 逐条记 status, 不补假值

用法:
  ./gui-venv311/bin/python tools/l2_full_chain.py --beats 1 --write-ar
  ./gui-venv311/bin/python tools/l2_full_chain.py --beats 3 --json /tmp/l2chain.json
"""
from __future__ import annotations

import argparse, importlib, json, os, re, sys, time, traceback

ROOT = '/home/ubuntu/zmax'
sys.path.insert(0, ROOT + '/src')
CANVAS = ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json'
NODEDIR = ROOT + '/src/lerobot/middleware/nodes'
L2_BANDS = ['row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4']


def canvas_l2():
    d = json.load(open(CANVAS, encoding='utf-8'))
    bands = {n['id']: n for n in d['nodes'] if n['type'] == 'row_bg'}
    idx = open(NODEDIR + '/_index.py', encoding='utf-8').read()
    nodes, order = {}, []
    for bid in L2_BANDS:
        b = bands[bid]
        for n in sorted([x for x in d['nodes'] if x['type'] != 'row_bg' and b['y'] <= x['y'] < b['y'] + b['h']],
                        key=lambda z: (z['y'], z['x'])):
            m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
            if not m:
                continue
            mod = m.group(1).split('.')[-1]
            nodes[n['id']] = dict(id=n['id'], name=n['name'], band=bid, band_name=b['name'], mod=mod)
            order.append(n['id'])
    links = [l for l in d.get('links', []) if l['f'] in nodes and l['t'] in nodes]
    return nodes, order, links


def topo(nodes, order, links):
    indeg = {k: 0 for k in order}
    adj = {k: [] for k in order}
    for l in links:
        adj[l['f']].append(l['t'])
        indeg[l['t']] += 1
    q = [k for k in order if indeg[k] == 0]
    out = []
    while q:
        k = q.pop(0)
        out.append(k)
        for t in adj[k]:
            indeg[t] -= 1
            if indeg[t] == 0:
                q.append(t)
    out += [k for k in order if k not in out]          # 环/孤立节点补在尾部, 不丢
    return out


def load_mods(nodes):
    mods = {}
    for nid, n in nodes.items():
        try:
            mods[nid] = importlib.import_module('lerobot.middleware.nodes.' + n['mod'])
        except Exception as e:                                        # noqa: BLE001
            mods[nid] = e
    return mods


def beat(nodes, seq, links, mods, bus):
    """跑一拍: 按拓扑序调每个节点的 compute(ctx), 端口值从总线上游取。"""
    rec = {}
    for nid in seq:
        n = nodes[nid]
        mod = mods[nid]
        if isinstance(mod, Exception):
            rec[nid] = dict(ok=False, ms=0.0, status='模块导入失败: %s' % mod, outs={})
            continue
        ctx = {}
        for l in links:
            if l['t'] == nid:
                up = bus.get((l['f'], l['f_port']))
                if up is not None:
                    ctx[l['t_port']] = dict(value=up[0], age_s=round(time.time() - up[1], 3), fresh=True)
        t0 = time.perf_counter()
        outs, status = {}, ''
        try:
            outs = mod.compute(ctx) or {}
            ok = True
        except Exception as e:                                        # noqa: BLE001
            status = '异常: %s: %s' % (type(e).__name__, e)
            ok = False
        ms = (time.perf_counter() - t0) * 1000
        if ok:
            status = getattr(mod, 'LAST_STATUS', '') or 'ok'
        for k, v in (outs or {}).items():
            bus[(nid, k)] = (v, time.time())
        rec[nid] = dict(ok=ok and bool(outs), ms=round(ms, 2), status=status, outs=outs)
    return rec


def points_summary():
    """工程配置点位 (与 plan 节点同源): points_source.list_points()"""
    try:
        from lerobot.engineering.nodes import points_source as PS
        sim = PS.list_points('sim_base')
        by_src = {}
        for p in sim:
            k = p['src'].split(':')[0]
            by_src[k] = by_src.get(k, 0) + 1
        return dict(ok=bool(sim), frame='sim_base', n=len(sim), by_file=by_src,
                    sample=[{'name': p['name'], 'mm': [round(v, 1) for v in p['pos_mm']]} for p in sim[:5]])
    except Exception as e:                                            # noqa: BLE001
        return dict(ok=False, err='%s: %s' % (type(e).__name__, e))


def make_annot(rec, nodes, points, process):
    ok = [k for k, v in rec.items() if v['ok']]
    return dict(
        ts=time.strftime('%H:%M:%S'), t=time.time(),
        src='l2_full_chain',
        summary=dict(nodes=len(rec), ok=len(ok), err=len(rec) - len(ok)),
        nodes=[dict(id=k, name=nodes[k]['name'], band=nodes[k]['band_name'],
                    ok=rec[k]['ok'], ms=rec[k]['ms'], status=rec[k]['status']) for k in rec],
        points=points, process=process,
    )


def process_from_geoplan(rec, nodes):
    """工艺编排: 取测地线规划节点的块输出; 不可用就如实说, 不自造顺序。"""
    for nid, n in nodes.items():
        if 'geodesic' in n['mod'] or 'geodesic' in (n['name'] or ''):
            r = rec.get(nid, {})
            o = r.get('outs') or {}
            chunk = o.get('out1') if isinstance(o, dict) else None
            return dict(node=nid, name=n['name'], ok=bool(r.get('ok')), status=r.get('status'),
                        chunk_n=(len(chunk.get('chunk') or []) if isinstance(chunk, dict) else 0))
    return dict(node=None, ok=False, status='画布中未找到测地线规划节点')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--beats', type=int, default=1)
    ap.add_argument('--json', default='')
    ap.add_argument('--write-ar', action='store_true')
    a = ap.parse_args()

    nodes, order, links = canvas_l2()
    seq = topo(nodes, order, links)
    mods = load_mods(nodes)
    bus = {}
    t0 = time.perf_counter()
    last = {}
    for i in range(a.beats):
        last = beat(nodes, seq, links, mods, bus)
        if a.beats > 1:
            print('  beat %d: ok %d/%d  %.0f ms' % (i + 1, sum(1 for v in last.values() if v['ok']),
                                                    len(last), sum(v['ms'] for v in last.values())))
    wall = (time.perf_counter() - t0) * 1000

    pts = points_summary()
    proc = process_from_geoplan(last, nodes)
    annot = make_annot(last, nodes, pts, proc)
    annot['summary']['wall_ms'] = round(wall / max(1, a.beats), 1)

    print('\nL2 全链: %d 节点 · 拓扑序 %d · %d 拍 · 每拍 %.0f ms' % (
        len(nodes), len(seq), a.beats, wall / max(1, a.beats)))
    print('%-14s %-40s %-6s %8s  %s' % ('节点', '名称(画布)', 'OK', 'ms', '状态'))
    for nid in seq:
        v = last[nid]
        print('%-14s %-40s %-6s %8.1f  %s' % (nid, nodes[nid]['name'][:40], '✓' if v['ok'] else '✗',
                                              v['ms'], v['status'][:70]))
    print('\n工程配置点位: %s' % json.dumps(pts, ensure_ascii=False))
    print('工艺编排: %s' % json.dumps(proc, ensure_ascii=False))

    if a.write_ar:
        try:
            from lerobot.engineering.exec import ar_bridge as AB
            AB.update('annot', annot, src='l2_full_chain')
            print('已写 AR annot 分区 →', AB.path())
        except Exception as e:                                        # noqa: BLE001
            print('写 AR 失败:', type(e).__name__, e)
    if a.json:
        json.dump(dict(annot=annot, rec=last), open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('报告 →', a.json)
    bad = [k for k, v in last.items() if not v['ok']]
    return 0 if not bad else 2


if __name__ == '__main__':
    sys.exit(main())
