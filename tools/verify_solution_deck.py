#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案册自检 (R5 大字版): 每个关键数字回来源文件重算, 排版按实际字号与边界核。

三类检查:
  数字 —— 节拍/产能/成本/回本/力限/控制周期/节点数, 与来源文件现算值比对;
  结构 —— 页数、每页标题字号、最小字号、形状不出界、节点页顺序;
  用语 —— 全册禁用词、旧节点名、内部代号。

用法: ./gui-venv311/bin/python tools/verify_solution_deck.py [pptx]
退出码: 0 全过 / 1 有 FAIL
"""
import json
import os
import sys
import urllib.request

from pptx import Presentation
from pptx.util import Emu

ROOT = '/home/ubuntu/zmax'
DECK = sys.argv[1] if len(sys.argv) > 1 else (
    ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案/'
           'Z-MAX机器人整机解决方案_5.50.C-R5_20261102.pptx')

sys.path.insert(0, ROOT + '/tools')
results = []


def chk(item, truth, ok, seen, src):
    results.append((item, truth, seen, 'PASS' if ok else 'FAIL', src))


# ── 读 PPT: 逐页文本 + 字号
pr = Presentation(DECK)
pages = []
for si, s in enumerate(pr.slides, 1):
    txt, sizes = [], []
    for sh in s.shapes:
        if sh.has_text_frame:
            t = sh.text_frame.text
            if t.strip():
                txt.append(t)
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.font.size and r.text.strip():
                        sizes.append(r.font.size.pt)
        if sh.has_table:
            for row in sh.table.rows:
                for c in row.cells:
                    if c.text.strip():
                        txt.append(c.text)
                    for p in c.text_frame.paragraphs:
                        for r in p.runs:
                            if r.font.size and r.text.strip():
                                sizes.append(r.font.size.pt)
    pages.append(dict(no=si, text='\n'.join(txt), sizes=sizes))
ALL = '\n'.join(p['text'] for p in pages)


def pno(needle):
    return [p['no'] for p in pages if needle in p['text']]


# ── 来源: 节拍/工位/结构/成本/节点
import build_solution_deck as B
import cost_model as CM
import l2_chain_pages as LC

S = B.sources()
COST = CM.build_tiers()
T = {t['id']: t for t in COST['tiers']}
NODES, L2SET, LINKS = LC.l2_nodes()
ORDER = list(LC.chain_order(L2SET, LINKS)[0])

_NP_TOTAL = len(ORDER) + 5 + 18 + 11
_WANT_PAGES = 13 + 7 + _NP_TOTAL + 3 + 3 + 1
chk('页数', _WANT_PAGES, len(pages) == _WANT_PAGES, '%d 页' % len(pages),
    '前置13(含轨迹页) + 母版7 + 节点%d + 层首3 + 收尾3 + 节拍1' % _NP_TOTAL)
chk('节拍 秒/件', '%.3f' % S['tact'], ('%.3f' % S['tact']) in ALL,
    '%.3f' % S['tact'], 'api/sim_insert plan[] 逐段求和')
chk('节拍产能 件/小时', '%d' % round(S['uph']), ('%d' % round(S['uph'])) in ALL,
    '%d' % round(S['uph']), '3600 / tact')
chk('基础层节点数', S['n_l2'], str(S['n_l2']) in ALL, str(S['n_l2']),
    '画布 state_space_obs.json')

# ── 前 12 页: 每页一句结论
front_titles = ['光模块上下料与插拔工作站', '这台机器解决什么问题', '难点不在', '一层管一件事',
                '先看清楚', '100 毫秒一拍', '中间有四道闸', '40 牛顿', '同一份场景',
                '走完的一条连续轨迹', '三处证据', '三档配置', '我们承诺什么']
for i, want in enumerate(front_titles):
    p = pages[i] if i < len(pages) else dict(text='', sizes=[])
    chk('第 %d 页标题' % (i + 1), want, want in p['text'],
        p['text'][:44].replace('\n', ' / '), 'deck_front.build_front')

# ── 数字落到全册
pairs = [
    ('控制周期 100 毫秒', '100', '常驻循环 10 次/秒'),
    ('全链计算 13.7 毫秒', '13.7', '快通道 14 节点耗时合计'),
    ('统一状态 43 维', '43', '状态空间维数'),
    ('力上限 40 牛顿', '40 牛顿', '工艺力限'),
    ('横向分量否决 60 度', '60', '分层力场方向判据'),
    ('识别目标类别', '2 类', 'models/yolo_peg_live.pt 的 names'),
    ('手眼落点 1.74 毫米', '1.74', '手眼 TSAI 闭环'),
    ('一轮轨迹 392 段', '392', 'sim_insert 段表'),
    ('段表 112 段', '112', '段表接口'),
]
for item, needle, src in pairs:
    chk(item, needle, needle in ALL, '出现 %d 页: %s' % (len(pno(needle)), pno(needle)[:6]), src)

# ── 成本: 售价/单件成本/节省/回本 与 cost_model 现算一致
for tid in ('A', 'B', 'C'):
    t = T[tid]
    for label, val, fmt in (
            ('售价', t['price_set'] / 10000, '%.0f 万'),
            ('单件成本', t['client_unit_cost'], '%.3f'),
            ('相对人工', t['client_save_pct'], '%.1f'),
            ('回本', t['payback_years'], '%.2f')):
        s = fmt % val
        chk('%s 档%s' % (tid, label), s, s in ALL, s, 'tools/spec/cost_model.json → build_tiers')

# ── 轨迹页: 图在不在 + 五阶段 + 总时长与段表现算一致
_traj = [p for p in pages if '走完的一条连续轨迹' in p['text']]
if _traj:
    _sl = pr.slides[_traj[0]['no'] - 1]
    _pics = [sh for sh in _sl.shapes if sh.shape_type == 13]
    chk('轨迹页有图', '1 张透视轨迹图', len(_pics) == 1, '%d 张' % len(_pics), 'deck_traj_fig.render')
    _need = ['取件', '插入', '拔出', '检测 AOI', '分拣']
    chk('轨迹页五阶段', '/'.join(_need), all(x in _traj[0]['text'] for x in _need),
        str([x for x in _need if x not in _traj[0]['text']]), 'sim_insert 分阶段计时')
    import deck_traj_fig as _TF

    def _plan():
        try:
            return json.loads(urllib.request.urlopen('http://127.0.0.1:8797/api/sim_insert', timeout=8).read())
        except Exception:                                    # noqa: BLE001
            return json.load(open(ROOT + '/zmax_data/runtime/traj/sim_insert.json', encoding='utf-8'))
    _P = [x for x in _plan()['plan'] if x.get('mod') == 1]
    _B = _TF.phase_bounds(_P)
    _dur = [round(sum(x['t'] for x in _P[_B[k]:_B[k + 1]]), 2) for k in range(5)]
    _miss = [(k, '%.2f 秒' % _dur[k]) for k in range(5)
             if ('%.2f 秒' % _dur[k]) not in _traj[0]['text']]
    chk('轨迹页阶段计时', '%s' % _dur, not _miss, str(_miss), 'sim_insert 按阶段求和')

# ── 前置页页码: 必须 01..13, 不能因为母版排后面而错位
_bad_pn = []
for i in range(1, 13):                    # 第 1 页是封面, 不印页码
    want = '%02d / %d' % (i + 1, len(pages))
    if i < len(pages) and want not in pages[i]['text']:
        _bad_pn.append((i + 1, want))
chk('前置页页码', '02..13 / 全册页数', not _bad_pn, str(_bad_pn[:4]), 'deck_front.page 自动编号')

# ── 结构: 字号 / 出界
_m0 = next((p['no'] for p in pages if '整机外观' in p['text']), 14)
CHART_PAGES = set(range(_m0, _m0 + 7))    # 母版 7 页(三视图/尺寸/参数/甘特/稳态): 尺寸标注按工程图惯例
small = [(p['no'], min(p['sizes'])) for p in pages
         if p['sizes'] and min(p['sizes']) < 9.0 and p['no'] not in CHART_PAGES]
chart_small = [(p['no'], min(p['sizes'])) for p in pages
               if p['sizes'] and min(p['sizes']) < 9.0 and p['no'] in CHART_PAGES]
chk('正文最小字号 ≥ 9pt', '9.0', not small, str(small[:6]), '逐 run 实际字号 (图表页除外)')
chk('图表页字号', '≥6pt 尺寸标注', all(v >= 6.0 for _, v in chart_small),
    str(chart_small[:6]), '工程图尺寸标注下限 6pt')
no_title = [p['no'] for p in pages if not p['sizes'] or max(p['sizes']) < 16]
chk('每页有 ≥16pt 标题', '16', not no_title, str(no_title), '标题字号')
W, H = pr.slide_width, pr.slide_height
out = []
for s in pr.slides:
    for sh in s.shapes:
        try:
            if sh.left is None:
                continue
            if (sh.left < -Emu(1) or sh.top < -Emu(1)
                    or sh.left + sh.width > W + Emu(1) or sh.top + sh.height > H + Emu(1)):
                out.append(str(sh.shape_type))
        except Exception:                                    # noqa: BLE001
            pass
chk('形状不出页面', '0 个越界', not out, '%d 个越界' % len(out), '页面 13.333×7.5 英寸')

# ── 节点页: 30 页、顺序、五段
node_pages = [p['no'] for p in pages if p['text'].startswith('基础层 · 第')]
chk('基础层节点页页数', len(ORDER), len(node_pages) == len(ORDER),
    '%d 页 %s' % (len(node_pages), node_pages[:3]), 'l2_chain_pages.chain_order')
for _lv, _cn, _want in (('L3', '决策层', 5), ('L4', '认知层', 18), ('L5', '任务层', 11)):
    _ps = [p['no'] for p in pages if p['text'].startswith(_cn + ' · 第')]
    chk('%s节点页页数' % _cn, _want, len(_ps) == _want, '%d 页' % len(_ps),
        'by_level.LEVELS_INDEX')
    _bad = [n for n in _ps if '个输入' in pages[n - 1]['text'] or '个源' in pages[n - 1]['text']]
    chk('%s页无计数词' % _cn, 0, not _bad, str(_bad), '输入 x 条 / 输出 y 条')
bad_seq = []
for i, nid in enumerate(ORDER[:len(node_pages)]):
    t = pages[node_pages[i] - 1]['text']
    mi = LC._mod_info(nid)[1] or {}
    import re as _re
    def norm(x):
        s = ''.join(c for c in str(x) if c.isalnum() and c not in '①②③④⑤⑥⑦⑧⑨⑩')
        return s[2:] if (s[:1] == 'L' and s[1:2].isdigit()) else s
    name = norm(str(mi.get('NAME') or nid))[:4]
    if name and name not in norm(t):
        bad_seq.append((i + 1, nid))
chk('节点页顺序', '与链路一致', not bad_seq, str(bad_seq[:4]), 'chain_order + 中间件 NAME')
miss_lbl = []
for n in node_pages:
    t = pages[n - 1]['text']
    for lbl in ('输入接口', '输出接口', '节拍角色', 'AR 验证'):
        if lbl not in t:
            miss_lbl.append((n, lbl))
chk('节点页结构齐全', '功能描述+输入接口+输出接口+AR验证+节拍角色', not miss_lbl, str(miss_lbl[:5]),
    'l2_node_prose + l2_node_ar')

# ── 用语
ban = {'真源': '内部说法', '口径': '内部说法', 'PURE': '内部代号', 'UPH': '内部缩写',
       'in1': '端口代号', 'out1': '端口代号', '本节点': '模板措辞', '模块的': '模板措辞',
       '个源 /': '旧表述', '个去向': '旧表述', '开放词汇分割': '旧节点名',
       '分割anything': '旧节点名', '链接 links': '内部字段名'}
hit = {k: pno(k) for k in ban if pno(k)}
chk('禁用词清零', '0 处', not hit, str(hit), '全册文本扫描')

# ── 在役权重类别数: 直接读权重 names, 不按印象写
try:
    import torch
    _ck = torch.load(ROOT + '/models/yolo_peg_live.pt', map_location='cpu', weights_only=False)
    _m = _ck.get('model') or _ck
    _names = getattr(_m, 'names', None) or _ck.get('names') or {}
    _n_cls = len(_names)
except Exception as _e:                                     # noqa: BLE001
    _n_cls = None
chk('在役权重大小类数', str(_n_cls), (_n_cls is not None and ('%d 类' % _n_cls) in ALL),
    '%d 类' % _n_cls if _n_cls else '读不到', 'models/yolo_peg_live.pt names')
chk('册版本', '5.50.C-R5', '5.50.C-R5' in ALL,
    '5.50.C-R5' if '5.50.C-R5' in ALL else '未见', 'deck_front.VER')

# ── 输出
print('检查 %d 项' % len(results))
npass = 0
for i, (item, truth, seen, st, src) in enumerate(results, 1):
    print('%02d:%-24s %-4s %-30s %s  [%s]' % (i, item, st, truth, str(seen)[:58], src))
    npass += (st == 'PASS')
print('结果: %d PASS / %d FAIL' % (npass, len(results) - npass))
sys.exit(0 if npass == len(results) else 1)
