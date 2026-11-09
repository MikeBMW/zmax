#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串行推理队列 —— 4060 算力不够, 重模型一个接一个跑, 不许并发挤爆显存/拍子。

老倪 2026-11-01: 「4060 算力不够, 要串行推理。」

范围: tools/node_rollout.py 判定为「超预算 → 串行推理队列」的节点 (单次 0.2~4.1s),
      常驻循环里这些节点置直通, 由本脚本按**严格串行**方式逐个真推理, 结果落盘缓存。

铁律:
  · 一次只有一个模型在算 (串行), 跑完释放; 记录每个模型 ms/是否真发值/错误
  · 不碰下发链路 (不调 8793 / 不碰 l2_daemon), 只算不发
  · AR 场景 300UPH 的节拍由核心链 (每拍 15ms) 保证, 本队列在旁路跑, 不占拍子

用法:
  ./gui-venv311/bin/python tools/serial_inference.py            # 跑一轮, 打印逐模型结果
  ./gui-venv311/bin/python tools/serial_inference.py --loop 5   # 每 5s 一轮 (常驻串行队列)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time

ROOT = '/home/ubuntu/zmax'
sys.path.insert(0, ROOT + '/src')
sys.path.insert(0, ROOT + '/tools')
OUT = ROOT + '/zmax_data/ss_live/serial_inference.json'

SERIAL_NODES = ['n_l2_muscle', 'ss_mem_field', 'n_web_agent', 'n_hil', 'ss_seg',
                'n_intent_direct', 'ssfeat']
PENDING_NODES = ['ssdec', 'ss_mem_l4', 'ssyolo', 'ssaoi']


def has_value(outs):
    if not outs:
        return False
    for port in outs.values():
        v = port.get('value') if isinstance(port, dict) else port
        if isinstance(v, dict) and v:
            return True
        if isinstance(v, (list, tuple)) and len(v):
            return True
        if v is not None and not isinstance(v, (dict, list, tuple)) and v != '':
            return True
    return False


def one_round(nodes_all, seed, ids):
    recs = []
    for nid in ids:
        n = nodes_all.get(nid)
        if not n or not n.get('mod'):
            recs.append(dict(id=nid, ok=False, ms=0.0, emitted=False, why='画布无此节点'))
            continue
        try:
            mod = importlib.import_module('lerobot.middleware.nodes.' + n['mod'])
            if hasattr(mod, 'PURE'):
                mod.PURE = True
            ports = list(getattr(mod, 'PORTS_IN', ['in1']) or ['in1'])
            ctx = {p: dict(value=seed, age_s=0.0, fresh=True) for p in ports}
            t0 = time.perf_counter()
            outs = mod.compute(ctx) or {}          # ← 严格串行: 上一行返回后才进下一个
            ms = (time.perf_counter() - t0) * 1000
            recs.append(dict(id=nid, name=n['name'], mod=n['mod'], ok=True, ms=round(ms, 1),
                             emitted=has_value(outs), why=str(getattr(mod, 'LAST_STATUS', ''))[:110]))
        except Exception as e:                                            # noqa: BLE001
            recs.append(dict(id=nid, name=n['name'], ok=False, ms=0.0, emitted=False,
                             why='%s: %s' % (type(e).__name__, str(e)[:90])))
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--loop', type=float, default=0.0, help='每 N 秒跑一轮 (0=只跑一次)')
    ap.add_argument('--json', default='')
    a = ap.parse_args()

    from fullstack_ideal_chain import load_canvas
    from lerobot.middleware.nodes.impl import geo_plan_impl as G
    from lerobot.middleware.nodes.impl import ideal_obs as IO
    nodes, side, _ = load_canvas()
    allnodes = {**nodes, **side}

    n_round = 0
    while True:
        doc = G.build_ideal_plan(h=8)
        obs, meta = IO.frame(doc)
        seed = dict(obs=[float(x) for x in obs], dim=43,
                    craft=dict(cycle_s=doc['cycle_s'], tact_s=doc['tact_s'], n_seg=doc['n_seg']))
        t0 = time.perf_counter()
        recs = one_round(allnodes, seed, SERIAL_NODES)
        pend = one_round(allnodes, seed, PENDING_NODES)
        wall = (time.perf_counter() - t0) * 1000
        n_round += 1
        ok_n = sum(1 for r in recs if r['ok'] and r['emitted'])
        rep = dict(ts=time.strftime('%Y-%m-%d %H:%M:%S'), round=n_round,
                   mode='串行 (一个模型算完再下一个)',
                   serial=recs, pending=pend,
                   summary=dict(models=len(recs), emitted=ok_n,
                                serial_total_ms=round(sum(r['ms'] for r in recs), 1),
                                wall_ms=round(wall, 1), step=meta['step_i'],
                                uph=round(doc['uph'], 1), ok300=bool(doc['ok300'])))
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT + '.tmp', 'w', encoding='utf-8') as fh:
            json.dump(rep, fh, ensure_ascii=False)
        os.replace(OUT + '.tmp', OUT)

        if a.loop <= 0 or n_round == 1:
            print('串行推理 · 一轮 %d 个模型 · 合计 %.0f ms · 拍子 %.0f ms (不吃节拍)' % (
                len(recs), rep['summary']['serial_total_ms'], wall))
            print('%-14s %-34s %-4s %9s %-4s %s' % ('节点', '名称', '跑通', 'ms', '发值', '状态'))
            for r in recs + pend:
                print('%-14s %-34s %-4s %8.1f %-4s %s' % (r['id'], (r.get('name') or '')[:34],
                                                          '✓' if r['ok'] else '✗', r['ms'],
                                                          '✓' if r['emitted'] else '✗', r['why'][:70]))
            print('产物 →', OUT)
        if a.json:
            json.dump(rep, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        if a.loop <= 0:
            return 0
        time.sleep(a.loop)


if __name__ == '__main__':
    sys.exit(main())
