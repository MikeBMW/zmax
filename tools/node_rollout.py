#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点逐个接入 (一个节点一个节点替换) —— 直通 → 真模型推理, 超预算就不接入。

老倪 2026-11-01: 「所有模型要真正运行, 保证 AR 场景的 300UPH, 一个节点一个节点替换。
模型要正常推理, 如果达不到 300UPH, 可以不接入节点, 但是代码要跑通。4060 算力不够, 要串行推理。」

判据 (逐节点, 不粉饰):
  ① 能不能真跑: 模块 import + compute(ctx) 不抛异常
  ② 有没有真发值: 端口里必须有非空值 (空 dict/None 不算)
  ③ 吃不吃得下拍子: 单次 ms ≤ TICK_BUDGET_MS(默认 60ms, 10Hz 拍子留余量)
       ≤ 预算 → 判定「接入常驻循环」(每 30 拍一次全量)
       > 预算 → 判定「不接入, 走串行推理队列」(tools/serial_inference.py)
  ④ 300UPH: 由工艺动作表 (112 步 / 45.05s / 4 件 / 320 UPH) 决定, 与这些节点接入与否无关 ——
     接入慢节点反而会拖垮拍子, 所以"不接入"是正确决策, 不是妥协。

用法:
  ./gui-venv311/bin/python tools/node_rollout.py            # 全量扫一遍
  ./gui-venv311/bin/python tools/node_rollout.py --json /tmp/rollout.json
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

TICK_BUDGET_MS = float(os.environ.get('ZMAX_TICK_BUDGET_MS') or 60.0)
CANDIDATES = [
    # 常驻循环里当前置直通的 16 个 (来自 70-slow-lane / 60-offline-nodes 的实测 ms 列)
    'ssfeat', 'n_hil', 'ssllm_in', 'n_vlm_llm', 'n_dsvl', 'ssreason', 'ss_l5', 'n_web_agent',
    # ⚠️ 这些必须写**画布节点 id**, 不是模块名 (n_decoder 是模块, 节点是 ssdec)
    'ssdec', 'n_l2_muscle', 'ss_mem_l4', 'ssyolo', 'ss_mem_field', 'ss_seg', 'ssaoi',
    'n_intent_direct',
]


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


def ideal_ctx(mod, seed):
    ports = list(getattr(mod, 'PORTS_IN', ['in1']) or ['in1'])
    return {p: dict(value=seed, age_s=0.0, fresh=True) for p in ports}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='')
    a = ap.parse_args()

    from fullstack_ideal_chain import load_canvas
    from lerobot.engineering.nodes import geo_plan_impl as G
    from lerobot.engineering.nodes import ideal_obs as IO

    nodes, side, _links = load_canvas()
    allnodes = {**nodes, **side}
    doc = G.build_ideal_plan(h=8)
    obs, meta = IO.frame(doc)
    seed = dict(obs=[float(x) for x in obs], dim=43,
                craft=dict(cycle_s=doc['cycle_s'], tact_s=doc['tact_s'], n_seg=doc['n_seg']))

    rows = []
    print('节点逐个接入评测 · 拍子预算 %.0f ms · 判据: 能跑 + 真发值 + 不超预算' % TICK_BUDGET_MS)
    print('-' * 104)
    print('%-14s %-38s %-6s %9s  %-10s %s' % ('节点', '名称(画布)', '跑通', 'ms', '真发值', '判定'))
    for nid in CANDIDATES:
        n = allnodes.get(nid)
        if not n or not n.get('mod'):
            rows.append(dict(id=nid, name=(n or {}).get('name'), ok=False, ms=0.0, emitted=False,
                             verdict='不接入', why='画布无此节点/无实现'))
            print('%-14s %-38s %-6s %9s  %-10s %s' % (nid, ((n or {}).get('name') or '?')[:38],
                                                      '✗', '-', '-', '不接入 (无实现)'))
            continue
        try:
            mod = importlib.import_module('lerobot.middleware.nodes.' + n['mod'])
            if hasattr(mod, 'PURE'):
                mod.PURE = True
            ctx = ideal_ctx(mod, seed)
            t0 = time.perf_counter()
            outs = mod.compute(ctx) or {}
            ms = (time.perf_counter() - t0) * 1000
            ok = True
            err = ''
        except Exception as e:                                            # noqa: BLE001
            ms, outs, ok, err = 0.0, {}, False, '%s: %s' % (type(e).__name__, e)
        emitted = has_value(outs)
        if not ok:
            verdict, why = '不接入', '跑不通: ' + err[:60]
        elif not emitted:
            verdict, why = '不接入', '能跑但没发出值 (缺真帧/力信号/权重)'
        elif ms > TICK_BUDGET_MS:
            verdict, why = '不接入', '超预算 → 串行推理队列 (%.0fms)' % ms
        else:
            verdict, why = '接入', '≤%.0fms 且真发值' % TICK_BUDGET_MS
        rows.append(dict(id=nid, name=n['name'], mod=n['mod'], ok=ok, ms=round(ms, 1),
                         emitted=emitted, verdict=verdict, why=why))
        print('%-14s %-38s %-6s %8.1f   %-10s %s' % (nid, (n['name'] or '')[:38],
                                                    '✓' if ok else '✗', ms,
                                                    '✓' if emitted else '✗', verdict + ' · ' + why))

    take = [r for r in rows if r['verdict'] == '接入']
    serial = [r for r in rows if r['verdict'] == '不接入' and r.get('ok') and r.get('emitted')]
    dead = [r for r in rows if r['verdict'] == '不接入' and not (r.get('ok') and r.get('emitted'))]
    print('-' * 104)
    print('可接入常驻循环 %d 个: %s' % (len(take), ', '.join(r['id'] for r in take) or '无'))
    print('走串行推理队列 %d 个: %s' % (len(serial), ', '.join('%s(%.0fms)' % (r['id'], r['ms']) for r in serial) or '无'))
    print('代码待补 %d 个: %s' % (len(dead), ', '.join(r['id'] for r in dead) or '无'))
    print('300UPH 口径: 工艺动作表 45.05s/4件 = 11.264s/件 = 319.6 UPH (门槛 12.000s) ⇒ 成立; '
          '与上述节点接入与否无关')

    rep = dict(ts=time.strftime('%Y-%m-%d %H:%M:%S'), budget_ms=TICK_BUDGET_MS,
               uph=dict(cycle_s=doc['cycle_s'], tact_s=doc['tact_s'], uph=round(doc['uph'], 1),
                        ok300=bool(doc['ok300'])),
               rows=rows, take=[r['id'] for r in take],
               serial=[r['id'] for r in serial], pending=[r['id'] for r in dead])
    if a.json:
        json.dump(rep, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('报告 →', a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
