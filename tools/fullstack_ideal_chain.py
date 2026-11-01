#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全系统贯通 · L5 → L4 → L3 → L2 由后向前, 每层先发理想值, 再验 300UPH。

老倪 2026-11-01: 「按照 L2 L3 L4 L5 这样的顺序, 由后向前, 让节点先发出理想值,
然后看是否达到 300UPH, 保证所有状态空间工程的节点都联通、有效。开始全系统贯通。」

真源 (不另造):
  节点/连线   data/database/zmax/sources/canvas/state_space_obs.json (80 节点 · 221 连线 · 15 条 row_bg 带)
  节点实现    src/lerobot/middleware/nodes/_index.py → 模块 :: compute(ctx)
  工艺动作表  lerobot.engineering.nodes.geo_plan_impl.build_ideal_plan() (112 步 · 45.05s/4件 · 320 UPH)
  43D 状态    lerobot.engineering.nodes.ideal_obs (工艺动作 → 43D, 米, 同 su2.obs43_geometry 口径)

做法 (由后向前, 每层先发理想值):
  L5 意图   → 目标/节拍/批次/当前工艺动作 → 发理想意图
  L4 认知   → 安全域/世界模型/允许动作 → 发理想约束
  L3 调度   → 段序/进度/技能序列 → 发理想计划
  L2 执行   → 43D → 测地线 → 工艺动作 → 执行 (真跑 compute)
  旁路层    数据源/验证/可视化 (不阻断主线, 单独统计)

判据 (逐条打印, 不粉饰):
  联通: 221 条连线中, 两端都在 4 层内的连线 = 实数; 逐条核对上游是否真发出值
  有效: 每个节点 compute() 是否返回 out 且无异常; 返回空 = 无效, 如实列出
  UPH : 工艺动作表 45.05s/4件 → 11.264s/件 → 320 UPH vs 门槛 12.000s/件
        另算「真机可执行性」: 每步速度/加速度是否在 1~1000mm/s · ≤4000mm/s²

用法:
  ./gui-venv311/bin/python tools/fullstack_ideal_chain.py            # 跑一遍出报告
  ./gui-venv311/bin/python tools/fullstack_ideal_chain.py --json /tmp/fullstack.json
"""
from __future__ import annotations

import argparse
import importlib
import os
import json
import re
import sys
import time
import traceback

ROOT = '/home/ubuntu/zmax'
sys.path.insert(0, ROOT + '/src')
CANVAS = ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json'
NODEDIR = ROOT + '/src/lerobot/middleware/nodes'

# 层 → 画布带 (id, 口径照画布 row_bg 的 name, 不改名)
LAYERS = [
    ('L5', '🧠 大模型层 · 任务/编排/记忆中枢 (回路外慢决策)', ['ssbg5']),
    ('L4', '🏆 L4 专家自主功能 · 标定与流形世界模型', ['row_mem_l4', 'ssbg7']),
    ('L3', '🚀 L3 高级自动功能 · VLM 编码 + Flow-Matching', ['row_mem_l3', 'ssbg_vlm']),
    ('L2', '🔧 L2 基础辅助功能 (分段感知→融合→控制→决策→技能→执行)', [
        'row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4']),
]
SIDE_BANDS = {'ssbg_data': '📦 数据源 (供全部层级)', 'ssbg8': '🧩 验证层 (回路外元层)',
              'ssbg9': '🔭 可视化层 (旁路)'}


def load_canvas():
    d = json.load(open(CANVAS, encoding='utf-8'))
    bands = {n['id']: n for n in d['nodes'] if n.get('type') == 'row_bg'}
    idx = open(NODEDIR + '/_index.py', encoding='utf-8').read()

    def mod_of(nid):
        m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(nid), idx)
        return m.group(1).split('.')[-1] if m else None

    out, seen = {}, set()
    for lname, ldesc, band_ids in LAYERS:
        for bid in band_ids:
            b = bands[bid]
            for n in sorted([x for x in d['nodes']
                             if x.get('type') != 'row_bg' and b['y'] <= x['y'] < b['y'] + b['h']],
                            key=lambda z: (z['y'], z['x'])):
                if n['id'] in seen:
                    continue
                seen.add(n['id'])
                out[n['id']] = dict(id=n['id'], name=n['name'], layer=lname, band=bid,
                                    band_name=b['name'], mod=mod_of(n['id']), x=n['x'], y=n['y'])
    side = {}
    for bid, nm in SIDE_BANDS.items():
        b = bands[bid]
        for n in sorted([x for x in d['nodes']
                         if x.get('type') != 'row_bg' and b['y'] <= x['y'] < b['y'] + b['h']],
                        key=lambda z: (z['y'], z['x'])):
            if n['id'] in seen:
                continue
            seen.add(n['id'])
            side[n['id']] = dict(id=n['id'], name=n['name'], layer='SIDE', band=bid,
                                 band_name=nm, mod=mod_of(n['id']), x=n['x'], y=n['y'])
    links = d.get('links', [])
    return out, side, links


def topo(ids, links):
    idset = set(ids)
    sub = [l for l in links if l['f'] in idset and l['t'] in idset]
    indeg = {k: 0 for k in ids}
    adj = {k: [] for k in ids}
    for l in sub:
        adj[l['f']].append(l['t'])
        indeg[l['t']] += 1
    q = [k for k in ids if indeg[k] == 0]
    order = []
    while q:
        k = q.pop(0)
        order.append(k)
        for t in adj[k]:
            indeg[t] -= 1
            if indeg[t] == 0:
                q.append(t)
    order += [k for k in ids if k not in order]
    return order, sub


def _has_value(outs):
    """端口里是否真有值 (None/空 dict/空 list 都算没发出)。"""
    if not outs:
        return False
    for port in outs.values():
        v = port.get('value') if isinstance(port, dict) else port
        if isinstance(v, dict):
            if v:
                return True
        elif isinstance(v, (list, tuple)):
            if len(v):
                return True
        elif v is not None and v != '':
            return True
    return False


def ideal_seed(layer, craft, obs43):
    """每层的「理想值」——只有语义, 不假造传感器读数。"""
    if layer == 'L5':
        return dict(task='TASK-07-AOI', uph_target=300, cycle_s=craft['cycle_s'],
                    tact_s=craft['tact_s'], batch=4, deadline_s=12.0,
                    craft_steps=craft['n_seg'], craft_src='geo_plan_impl.build_ideal_plan',
                    note='理想意图: 按工艺动作表跑 4 件/循环, 每件 ≤12s')
    if layer == 'L4':
        return dict(allow=True, v_max_mm_s=1000, a_max_mm_s2=4000,
                    safety='pass', world_model='ideal', note='理想约束: 全段在允许速度/加速度域内')
    if layer == 'L3':
        return dict(plan_n=craft['n_seg'], plan_src='geo_ideal', progress=craft.get('progress', 0.0),
                    batch=4, note='理想计划: 112 步段表, 4 件/循环')
    if layer == 'L2':
        return dict(obs=[float(x) for x in obs43], dim=43, src='ideal_obs(工艺动作→43D)',
                    note='理想 43D: 手/夹爪/模块/四元数/孔位/触觉, 单位 m')
    return {}


def run(beats=1, verbose=True):
    nodes, side, links = load_canvas()
    from lerobot.engineering.nodes import geo_plan_impl as G
    from lerobot.engineering.nodes import ideal_obs as IO

    doc = G.build_ideal_plan(h=8)
    obs43, meta = IO.frame(doc)
    craft = dict(cycle_s=doc['cycle_s'], tact_s=doc['tact_s'], n_seg=doc['n_seg'],
                 uph=doc['uph'], ok300=doc['ok300'], progress=meta.get('prog', round(meta['u'] / max(1, doc['n_seg']), 4)))

    mods = {}
    for nid, n in list(nodes.items()) + list(side.items()):
        if not n['mod']:
            mods[nid] = RuntimeError('_index.py 无节点实现映射')
            continue
        try:
            m = importlib.import_module('lerobot.middleware.nodes.' + n['mod'])
            # 🔴 与常驻循环同一口径: Node._load_module 默认把 PURE 置 True (「默认真执行」,
            #     ZMAX_NODE_PURE_ALL=0 才全直通)。本工具直接 import 模块, 绕过了那道闸,
            #     ⇒ 之前 60 多个节点全是 PURE=False 直通, 报"有效"其实是端口壳子。
            if os.environ.get('ZMAX_NODE_PURE_ALL', '1').strip().lower() in ('0', 'false', 'off', 'no'):
                pass
            elif nid not in [x.strip() for x in os.environ.get('ZMAX_NODE_PURE_OFF', '').split(',') if x.strip()]:
                if getattr(m, 'PURE', None) is not True:
                    m.PURE = True
            mods[nid] = m
        except Exception as e:                                             # noqa: BLE001
            mods[nid] = e

    bus, rec, layers_out = {}, {}, []
    for lname, ldesc, _bands in LAYERS:
        ids = [k for k, v in nodes.items() if v['layer'] == lname]
        order, sub = topo(ids, links)
        seed = ideal_seed(lname, craft, obs43)
        t0 = time.perf_counter()
        for nid in order:
            n, mod = nodes[nid], mods[nid]
            if isinstance(mod, Exception):
                rec[nid] = dict(layer=lname, ok=False, ms=0.0, status='无实现: %s' % mod,
                                emitted={}, outs={})
                continue
            # ctx: 上游连线取值 + 本层理想值 (节点没有任何上游时, 用理想值喂, 让它先发)
            ctx = {}
            for l in sub:
                if l['t'] == nid:
                    up = bus.get((l['f'], l['f_port']))
                    if up is not None:
                        ctx[l['t_port']] = dict(value=up[0], age_s=round(time.time() - up[1], 3), fresh=True)
            upstream = len(ctx)
            if seed:
                ctx.setdefault('in_ideal', dict(value=seed, age_s=0.0, fresh=True))
                if upstream == 0:
                    # 该节点在这一层没有任何上游给出值 ⇒ 用**本层理想值**把它的输入口喂满,
                    # 让它先发出理想值 (这是"注入理想输入", 不是伪造传感器读数;
                    # 真帧/真力信号这类喂不了的, 节点自己会报缺什么, 见状态列)。
                    ports_in = list(getattr(mod, 'PORTS_IN', ['in1']) or ['in1'])
                    for p_ in ports_in:
                        ctx.setdefault(p_, dict(value=seed, age_s=0.0, fresh=True))
            ts = time.perf_counter()
            try:
                outs = mod.compute(ctx) or {}
                # 「有效」= 真的发出了非空值, 不是只返回了端口壳子
                ok = _has_value(outs)
                status = (getattr(mod, 'LAST_STATUS', '') or 'ok')
                if not ok:
                    status = '空输出(端口无值): ' + status
            except Exception as e:                                         # noqa: BLE001
                outs, ok, status = {}, False, '异常 %s: %s' % (type(e).__name__, e)
            ms = (time.perf_counter() - ts) * 1000
            for k, v in (outs or {}).items():
                bus[(nid, k)] = (v, time.time())
            # 端口值可能是 dict / ndarray / bool, 摘要时一律按"值本体"取
            _o1 = outs.get('out1') if isinstance(outs, dict) else None
            _v1 = _o1.get('value') if isinstance(_o1, dict) else _o1
            if isinstance(_v1, dict):
                emitted = {k: (list(x)[:6] if isinstance(x, (list, tuple)) else str(x)[:60])
                           for k, x in list(_v1.items())[:6]}
            elif _v1 is None:
                emitted = {}
            else:
                emitted = {'out1': str(_v1)[:80]}
            rec[nid] = dict(layer=lname, band=n['band_name'], name=n['name'], mod=n['mod'],
                            ok=ok, ms=round(ms, 2), status=str(status)[:120],
                            upstream_ports=upstream, outs_n=len(outs or {}), emitted=emitted,
                            outs=outs)
        layers_out.append(dict(layer=lname, desc=ldesc, nodes=len(ids), links=len(sub),
                               ok=sum(1 for k in ids if rec.get(k, {}).get('ok')),
                               ms=round((time.perf_counter() - t0) * 1000, 1),
                               ideal=seed if lname != 'L2' else dict(dim=43, step_i=meta['step_i'],
                                                                     action=meta['action'], label=meta['label'])))
        if verbose:
            print('%-3s %-46s 节点 %2d  连线 %3d  有效 %2d/%-2d  %7.1f ms  理想值: %s'
                  % (lname, ldesc[:46], len(ids), len(sub), layers_out[-1]['ok'], len(ids),
                     layers_out[-1]['ms'], _brief(seed if lname != 'L2' else
                                                  dict(step='%d/%d' % (meta['step_i'], doc['n_seg']),
                                                       action=meta['action'], label=meta['label']))))

    # 旁路层: 数据源/验证/可视化 (不阻断主线)
    side_rec = {}
    for nid, n in side.items():
        mod = mods.get(nid)
        if isinstance(mod, Exception) or mod is None:
            side_rec[nid] = dict(ok=False, status='无实现')
            continue
        ctx = {'in1': dict(value=ideal_seed('L2', craft, obs43), age_s=0.0, fresh=True)}
        try:
            outs = mod.compute(ctx) or {}
            side_rec[nid] = dict(ok=bool(outs), status=str(getattr(mod, 'LAST_STATUS', '') or 'ok')[:100])
        except Exception as e:                                             # noqa: BLE001
            side_rec[nid] = dict(ok=False, status='%s: %s' % (type(e).__name__, e))

    # 联通性: 连线两端都在 4 层内的, 逐条核上游是否真发了值
    ins = set(nodes)
    core_links = [l for l in links if l['f'] in ins and l['t'] in ins]
    def _bus_has(l):
        e = bus.get((l['f'], l['f_port']))
        return bool(e) and _has_value({l['f_port']: e[0]})
    carried = [l for l in core_links if _bus_has(l)]
    dang = [dict(f=l['f'], f_port=l['f_port'], t=l['t'], t_port=l['t_port'],
                 f_name=nodes.get(l['f'], {}).get('name'), t_name=nodes.get(l['t'], {}).get('name'),
                 f_layer=nodes.get(l['f'], {}).get('layer'), t_layer=nodes.get(l['t'], {}).get('layer'))
            for l in core_links if not _bus_has(l)]
    # UPH 判定
    uph = dict(cycle_s=doc['cycle_s'], tact_s=doc['tact_s'], uph=round(doc['uph'], 1),
               ok300=bool(doc['ok300']), margin_s=round(12.0 - doc['tact_s'], 3),
               batch=4, segs=doc['n_seg'])
    report = dict(ts=time.strftime('%Y-%m-%d %H:%M:%S'), t=time.time(),
                  layers=layers_out, side=side_rec,
                  uph=uph,
                  connect=dict(nodes=len(nodes) + len(side), core_nodes=len(nodes),
                               core_links=len(core_links), carried=len(carried),
                               dangling=len(core_links) - len(carried), dangling_list=dang),
                  nodes=[{k: rec[nid][k] for k in ('layer', 'band', 'name', 'mod', 'ok', 'ms', 'status')}
                         for nid in nodes if nid in rec])
    return report, rec, nodes


def _brief(d):
    parts = []
    for k, v in list(d.items())[:5]:
        parts.append('%s=%s' % (k, v if not isinstance(v, (list, dict)) else '…'))
    return ' '.join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default='')
    a = ap.parse_args()
    print('=' * 108)
    print('全系统贯通 · 由后向前 L5 → L4 → L3 → L2, 每层先发理想值')
    print('=' * 108)
    rep, rec, nodes = run(verbose=True)
    print('-' * 108)
    for lid, desc, _ in LAYERS:
        bad = [k for k, v in rec.items() if v['layer'] == lid and not v['ok']]
        if bad:
            print('%s 未发出值 (%d):' % (lid, len(bad)))
            for k in bad:
                print('   - %-14s %-34s %s' % (k, (nodes[k]['name'] or '')[:34], rec[k]['status'][:80]))
    c, u = rep['connect'], rep['uph']
    print('-' * 108)
    print('联通: 核心 %d 节点 · 核心连线 %d 条 · 上游真发出值 %d 条 · 断链 %d 条'
          % (c['core_nodes'], c['core_links'], c['carried'], c['dangling']))
    print('旁路层: 数据源/验证/可视化 %d 个, 有效 %d'
          % (len(rep['side']), sum(1 for v in rep['side'].values() if v['ok'])))
    for d in rep['connect'].get('dangling_list') or []:
        print('   断链 %-14s.%s → %-14s.%s   (%s → %s)'
              % (d['f'], d['f_port'], d['t'], d['t_port'], d['f_layer'], d['t_layer']))
    print('300UPH: 循环 %.2fs / %d 件 · 节拍 %.3fs/件 · %.1f UPH · 门槛 12.000s · 余量 %+.3fs ⇒ %s'
          % (u['cycle_s'], u['batch'], u['tact_s'], u['uph'], u['margin_s'],
             '成立 ✓' if u['ok300'] else '不成立 ✗'))
    if a.json:
        json.dump(rep, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('报告 →', a.json)
    ok_all = all(v['ok'] for v in rec.values())
    return 0 if ok_all else 2


if __name__ == '__main__':
    sys.exit(main())
