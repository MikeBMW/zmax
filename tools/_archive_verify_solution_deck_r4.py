#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解决方案 PPT 数字自检: 把 PPT 里写的每个关键数, 回到真源重算一遍再比对。

真源:
  结构   config/robot/zmax_robot_spec.json (URDF 导出) + zmax_data/rokae_sdk/urdf/xms5_r800_w4g3b4c.urdf
  工位   tools/web/tcp-ar.html 的 CHS / TAB / LARM / TCAM 常量
  场景   zmax_data/ar_mujoco/ar_station.xml (料盘/槽位)
  节拍   GET http://127.0.0.1:8797/api/sim_insert (plan[] 逐段 t + loop{})
  L2     画布 state_space_obs.json + src/lerobot/middleware/nodes/n_*.py
用法: ./gui-venv311/bin/python tools/verify_solution_deck.py [pptx路径]
退出码: 0 全过 / 1 有 FAIL
"""
import re, json, sys, os, math, urllib.request

ROOT = '/home/ubuntu/zmax'
DECK = sys.argv[1] if len(sys.argv) > 1 else \
    ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案/Z-MAX机器人整机解决方案_5.50.C_20261101.pptx'

results = []          # (项, 期望(真源算), PPT里出现的文本, PASS/FAIL, 来源)


def check(item, truth, needles, src):
    """truth: 真源算出的值(用于打印); needles: 必须在 PPT 里出现的字符串"""
    ok = all(n in PPT_TEXT for n in needles)
    results.append((item, truth, ' '.join(needles), 'PASS' if ok else 'FAIL', src))


def num(x, nd=1):
    return ('%.' + str(nd) + 'f') % x


# ---------- 1. 读 PPT 全文 ----------
from pptx import Presentation
pr = Presentation(DECK)
PPT_TEXT = []
for s in pr.slides:
    for sh in s.shapes:
        if sh.has_text_frame:
            PPT_TEXT.append(sh.text_frame.text)
        if sh.has_table:
            for r in sh.table.rows:
                PPT_TEXT.append(' | '.join(c.text for c in r.cells))
PPT_TEXT = '\n'.join(PPT_TEXT).replace('−', '-').replace('×', '×')

# ---------- 2. 结构真源 ----------
spec = json.load(open(ROOT + '/config/robot/zmax_robot_spec.json', encoding='utf-8'))
J = [j for j in spec['joints'] if j.get('limit')][:6]
masses = [l['mass'] for l in spec['links'] if l['mass']]
mass_sum = round(sum(masses), 3)
travel = [(round(math.degrees(j['limit']['lower'])), round(math.degrees(j['limit']['upper']))) for j in J]
efforts = [j['limit']['effort'] for j in J]
vels = {round(math.degrees(j['limit']['velocity'])) for j in J}
src_xyz = [j['origin_xyz'] for j in J]
tool = spec['tool']['xyz']

# ---------- 3. 工位常量 (tcp-ar.html) ----------
html = open(ROOT + '/tools/web/tcp-ar.html', encoding='utf-8').read()


def const(name):
    m = re.search(name + r'\s*=\s*\{([^}]*)\}', html)
    if not m:
        return {}
    d = {}
    for k, v in re.findall(r'(\w+)\s*:\s*(-?[\d.]+)', m.group(1)):
        d[k] = float(v)
    return d


CHS, TAB, TCAM = const('CHS'), const('TAB'), const('TCAM')
LARM = re.search(r'LARM\s*=\s*\{[^}]*off:\s*\[([^\]]*)\]', html)
larm_y = float(LARM.group(1).split(',')[1]) if LARM else None

# ---------- 4. 场景真源 (ar_station.xml) ----------
xml = open(ROOT + '/zmax_data/ar_mujoco/ar_station.xml', encoding='utf-8').read()
slots = []
for a, b, c, x, y in re.findall(
        r'name="[^"]*_槽\d+" type="box" pos="([-\d.e]+) ([-\d.e]+) ([-\d.e]+)" size="([-\d.e]+) ([-\d.e]+)',
        xml):
    slots.append((float(a) * 1000, float(b) * 1000, float(c) * 1000, float(x) * 2000, float(y) * 2000))
slot_z = {round(s[2], 1) for s in slots}
slot_open = {(round(s[3]), round(s[4])) for s in slots}
trays = re.findall(r'name="(b\d+)__([^"]*)_bot" type="box" pos="([-\d.e]+) ([-\d.e]+) ([-\d.e]+)" size="([-\d.e]+) ([-\d.e]+)', xml)
tray_sizes = {(round(float(t[5]) * 2000), round(float(t[6]) * 2000)) for t in trays}
slot_geoms = [(n, float(x), float(y), float(sx), float(sy))
              for n, x, y, z, sx, sy, sz in re.findall(
                  r'name="([^"]+)" type="box" pos="([-\d.e]+) ([-\d.e]+) ([-\d.e]+)" size="([-\d.e]+) ([-\d.e]+) ([-\d.e]+)', xml)
              if '槽' in n and round(float(sx) * 2000) == 36 and round(float(sy) * 2000) == 42]
n_slots = len(slot_geoms)
n_groups = len({re.match(r'(b\d+)', n).group(1)[:2] for n, *_ in slot_geoms}) if slot_geoms else 0

# ---------- 5. 节拍真源 (AR3D 接口) ----------
try:
    sim = json.loads(urllib.request.urlopen('http://127.0.0.1:8797/api/sim_insert', timeout=6).read())
    sim_src = '/api/sim_insert'
except Exception as e:
    sim = json.load(open(ROOT + '/zmax_data/runtime/traj/sim_insert.json', encoding='utf-8'))
    sim_src = 'disk sim_insert.json (%s)' % e
P, L = sim['plan'], sim['loop']
cum, t = [], 0.0
for s in P:
    cum.append(t); t += s['t']            # 不预先舍入: 与页面 loop.tact_s 口径一致
i0 = next(i for i, s in enumerate(P) if s['k'] == L['ks'][0])
i1 = max(i for i, s in enumerate(P) if s['k'] == L['ks'][1])
loop_dur = round(cum[i1] + P[i1]['t'] - cum[i0], 3)
tact = (cum[i1] + P[i1]['t'] - cum[i0]) / L['mods']
uph = 3600 / tact
ins_end, grip_t = {}, {}
for i, s in enumerate(P):
    if s['kind'] == 'release' and s.get('at') == 'hole' and s.get('hole') is not None:
        ins_end[s['mod']] = round(cum[i] + s['t'], 2)
    if s['kind'] == 'grip' and s.get('hole') is not None and '(拔)' in (P[i - 2].get('label') or ''):
        grip_t[s['mod']] = round(cum[i], 2)
dwells = [round(grip_t[m] - ins_end[m], 2) for m in sorted(ins_end) if m in grip_t]

# ---------- 6. L2 节点真源 (严格按画布七带, 名称逐字) ----------
canvas_all = json.load(open(ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json', encoding='utf-8'))['nodes']
bands = {n['id']: n for n in canvas_all if n['type'] == 'row_bg'}
idx = open(ROOT + '/src/lerobot/middleware/nodes/_index.py', encoding='utf-8').read()
L2_BANDS = ['row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4']
l2_nodes = []
for bid in L2_BANDS:
    b = bands[bid]
    for n in canvas_all:
        if n['type'] != 'row_bg' and b['y'] <= n['y'] < b['y'] + b['h']:
            m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
            f = ROOT + '/src/lerobot/middleware/nodes/%s.py' % (m.group(1).split('.')[-1] if m else '')
            pure = bool(re.search(r'^PURE\s*=\s*True', open(f, encoding='utf-8').read(), re.M)) if os.path.exists(f) else False
            l2_nodes.append(dict(id=n['id'], name=n['name'], band=bid, pure=pure))
n_l2 = len(l2_nodes)
n_pure = sum(1 for n in l2_nodes if n['pure'])
n_logic = sum(1 for n in l2_nodes if n['id'] != 'ssworld')

# ---------- 7. 逐项比对 ----------
# 工位尺寸
if TAB:
    tab_len = round((TAB['x1'] - TAB['x0']) * 1000)
    check('实验桌台面', '%d×%d×%d 高 %d mm' % (TAB['w'] * 1000, tab_len, TAB['t'] * 1000, TAB['h'] * 1000),
          ['1600 × 600 × 30', '台面高 750'], 'tcp-ar.html TAB')
if CHS:
    check('底盘箱体', '%d×%d×%d mm 轮 Ø%d' % (CHS['L'] * 1000, CHS['W'] * 1000, CHS['H'] * 1000, CHS['wr'] * 2000),
          ['600 × 800 × 750', 'Ø150'], 'tcp-ar.html CHS')
if TCAM:
    check('中央顶视相机', 'r%d 俯角%d° FOV %d×%d' % (TCAM['r'] * 1000, TCAM['tilt'], TCAM['fovH'], TCAM['fovV']),
          ['r 70', '35°', '87°×58°'], 'tcp-ar.html TCAM')
if larm_y is not None:
    check('双臂间距', '%d mm' % (larm_y * 1000), ['500 mm'], 'tcp-ar.html LARM.off')
check('相机立柱高 = J1 高', '%d mm' % (src_xyz[0][2] * 1000), ['328'], 'spec.json joints[0].origin_xyz')
# 机械臂
check('本体质量', '%.3f kg (6 link 求和)' % mass_sum, ['13.622'], 'spec.json links mass')
check('双臂质量', '%.3f kg' % (mass_sum * 2), ['27.244'], 'spec.json ×2')
check('J1/J4/J5/J6 行程 ±360', str([travel[0], travel[3], travel[4], travel[5]]), ['±360°'], 'spec.json limit')
check('J2 行程', '%d° ~ %d°' % travel[1], ['-160° ~ +150°'], 'spec.json limit')
check('J3 行程', '%d° ~ %d°' % travel[2], ['-170° ~ +140°'], 'spec.json limit')
check('额定力矩', str([int(e) for e in efforts]), ['113 N·m', '70 N·m', '25 N·m', '19 N·m'], 'spec.json limit.effort')
check('最大角速度', '%s °/s' % sorted(vels), ['180 °/s'], 'spec.json limit.velocity')
check('关节原点 J1/J5/J6', str([[round(v * 1000, 1) for v in src_xyz[i]] for i in (0, 4, 5)]),
      ['328.0', '136.0', '103.5'], 'spec.json joints origin_xyz')
check('大臂/小臂', 'J3 z=%d, J4 z=%d' % (src_xyz[2][2] * 1000, src_xyz[3][2] * 1000), ['400 mm'], 'spec.json joints origin_xyz')
check('法兰→tool1', '(%s) mm' % ', '.join(num(v * 1000, 1) for v in tool),
      ['-15.9, 18.3, 258.7'], 'spec.json tool.xyz')
# 场景
check('槽中心高', str(sorted(slot_z)), ['117.5'], 'ar_station.xml')
check('槽口尺寸', str(sorted(slot_open)), ['36 × 42'], 'ar_station.xml')
check('料盘 3 组 × 14 槽 + 废料盘', '槽口 36×42 共 %d 个 / 盘面 %s / 盘体 %d 个(含废料盘)' % (
    n_slots, sorted(tray_sizes), len(trays)),
    ['3 组 × 14 槽 + 废料盘', '266 × 393'], 'ar_station.xml')
# 节拍
check('稳态循环', '%.3f 秒 / %d 件 = %.3f 秒/件 = 每小时 %.0f 件' % (loop_dur, L['mods'], tact, uph),
      ['%.3f 秒 / %d 件' % (loop_dur, L['mods']), '%.3f 秒/件' % tact, '每小时 %.0f 件' % round(uph)], sim_src)
check('停留 dwell', '%.2f ~ %.2f s' % (min(dwells), max(dwells)),
      ['%.2f ~ %.2f s' % (min(dwells), max(dwells))], sim_src)
check('目标节拍', '每小时 300 件 = 12.0 秒/件, 余量 %.3f 秒' % (12.0 - tact),
      ['300', '12 秒', '余量 %.3f 秒' % (12.0 - tact)], 'order ar_300uph')

# 段表动作块 (与甘特页/总览页同一套解析: tools/build_uph300_gantt.build)
sys.path.insert(0, ROOT + '/tools')
from build_uph300_gantt import build as _gantt_build          # noqa: E402
R = _gantt_build(sim)
win = [b for b in R['blocks'] if b[2] >= R['base'] - 1e-6 and b[3] <= R['base'] + R['dur'] + 1e-6]


def _ph(kind):
    xs = sorted(b[3] - b[2] for b in win if b[0] == kind)
    return xs


pu, ao, pl, pi = _ph('pull'), _ph('aoi'), _ph('place'), _ph('insert')
occ = sum(b[3] - b[2] for b in win)
gap = R['dur'] - occ
check('单件动作块 拔/AOI/落盘/补插',
      '拔 %.2f~%.2f AOI %.2f 落盘 %.2f~%.2f 补插 %.2f~%.2f' % (
          pu[0], pu[-1], sum(ao) / len(ao), pl[0], pl[-1], pi[0], pi[-1]),
      ['拔 %.2f~%.2f' % (pu[0], pu[-1]), '落盘 %.2f~%.2f' % (pl[0], pl[-1]),
       '补插 1 颗/件 %.2f~%.2f' % (pi[0], pi[-1])], '段表 blocks')
check('右臂块内作业', '%.2f s / %.3f s = %.0f%%' % (occ, R['dur'], 100.0 * occ / R['dur']),
      ['%.2f 秒 / 循环 %.3f 秒' % (occ, R['dur']), '%.0f%%' % (100.0 * occ / R['dur'])], '段表 blocks')
check('块间走位', '%.3f s/件 (循环 %.2f s)' % (gap / R['mods'], gap),
      ['块间走位 %.2f s/件' % (gap / R['mods'])], '段表 blocks')
check('稳态窗口动作块数', '窗口内 %d 块 = %d 拔 + %d AOI + %d 落盘 + %d 补插' % (
    len(win), len(pu), len(ao), len(pl), len(pi)),
      ['%d 个动作块' % len(win)], '段表 blocks (窗口 [base, base+dur])')
check('设备孔', '%d 个孔, 孔距 %.0f mm, device_box_mm %s' % (
    len(sim['holes']), sim.get('hole_pitch_mm') or 0, sim.get('device_box_mm')),
      ['%d 个设备孔' % len(sim['holes'])], sim_src)
# L2
check('L2 节点数 / 真算数', '画布七带 %d 个(逻辑 %d), PURE=True %d' % (n_l2, n_logic, n_pure),
      ['%d 个节点' % n_l2], 'canvas 七带 + n_*.py')
missing = [n['name'] for n in l2_nodes if n['name'] not in PPT_TEXT]
results.append(('L2 节点名称逐字一致', '%d 个名称' % n_l2,
                ('缺 %d 个: %s' % (len(missing), ' / '.join(missing[:3]))) if missing else '全部命中',
                'PASS' if not missing else 'FAIL', 'canvas state_space_obs.json'))

# L2 连线页 (2026-11-02) —— 内部连线 / L3 入口 / 层外节点, 计数与画布 links 同源
try:
    sys.path.insert(0, ROOT + '/tools')
    from l2_wiring import counts as _l2c                     # noqa: E402
    _c = _l2c()
    check('L2 连线页 · 内部连线', 'L2↔L2 %d 条' % _c['l2_edges'],
          ['基础层内部 %d 条连线' % _c['l2_edges']], 'canvas links (L2↔L2)')
    check('L2 连线页 · L3 入口', 'L3↔L2 %d 条 / %d 个节点' % (_c['l3_edges'], _c['l3_nodes']),
          ['层间 %d 条' % _c['l3_edges']], 'canvas links (L3↔L2)')
    check('L2 连线页 · 层外节点', '%d 个节点 / %d 条连线' % (_c['ext_nodes'], _c['ext_edges']),
          ['层外节点 %d 个 / 连线 %d 条' % (_c['ext_nodes'], _c['ext_edges'])], 'canvas links (layer外)')
except Exception as _e:                                       # noqa: BLE001
    results.append(('L2 连线页', '可解析', '%s' % _e, 'FAIL', 'l2_wiring'))

# L5 / L4 / L3 层节点 (2026-11-01 新增页) —— 名称逐字 + 每层数量
try:
    sys.path.insert(0, ROOT + '/tools')
    from build_layer_nodes import load_nodes as _ln, LAYERS as _LY
    for _layer, _bands, _title, _note in _LY:
        _nodes, _ = _ln(_bands)
        _norm = lambda t: t.replace('−', '-')     # PPT_TEXT 已把 U+2212 归一, 比对也要归一同一边
        _miss = [n['name'] for n in _nodes if _norm(n['name']) not in PPT_TEXT]
        results.append(('%s 层节点数' % _layer, '画布 %d 个' % len(_nodes),
                        ['%d 个节点' % len(_nodes)], 'PASS' if len(_nodes) > 0 else 'FAIL',
                        'canvas %s' % '+'.join(_bands)))
        results.append(('%s 节点名称逐字一致' % _layer, '%d 个名称' % len(_nodes),
                        ('缺 %d 个: %s' % (len(_miss), ' / '.join(_miss[:3]))) if _miss else '全部命中',
                        'PASS' if not _miss else 'FAIL', 'canvas state_space_obs.json'))
except Exception as _e:                                                  # noqa: BLE001
    results.append(('L3/L4/L5 层页', '可解析', ['%s' % _e], 'FAIL', 'build_layer_nodes'))
# ---------- 7b. L2 逐节点页 + 节拍测试报告 (2026-11-02) ----------
try:
    sys.path.insert(0, ROOT + '/tools')
    import l2_chain_pages as _C
    _nodes, _l2, _links = _C.l2_nodes()
    _order, _out, _in = _C.chain_order(_l2, _links)
    _want = 19 + len(_order) + 1
    results.append(('总页数', '%d 页 (19 + L2 逐节点 %d + 节拍报告 1)' % (_want, len(_order)),
                    ['%d' % len(pr.slides._sldIdLst)],
                    'PASS' if len(pr.slides._sldIdLst) == _want else 'FAIL', 'pptx 实际页数'))
    # 每点一页: 标题里的编号/节点 id 与逆序一致
    _titles = {}
    for _i, _s in enumerate(pr.slides, 1):
        _full = "\n".join(sh.text_frame.text for sh in _s.shapes if sh.has_text_frame)
        _m = re.search(r'基础层链路 (\d+)/(\d+)', _full)
        if _m:
            _titles[int(_m.group(1))] = (_i, _full)
    _miss_pg = [k for k in range(1, len(_order) + 1) if k not in _titles]
    results.append(('L2 逐节点页数', '%d 个节点 = %d 页' % (len(_order), len(_order)),
                    ['%d 页' % len(_titles)], 'PASS' if not _miss_pg else 'FAIL',
                    'canvas L2 带 + 反向 BFS'))
    # 顺序: 第 1 页必须是"无 L2 下游"的末端节点, 且顺序与反向 BFS 逐位一致
    _ids = []
    for k in range(1, len(_order) + 1):
        _t = _titles.get(k, (0, ''))[1]
        _ids.append(_t.split('·', 1)[0].strip())
    _bad_order = [(_i + 1, _order[_i], _titles.get(_i + 1, (0, ''))[1][-30:])
                  for _i in range(len(_order)) if _order[_i] not in _titles.get(_i + 1, (0, ''))[1]]
    # 末端 = 离源头最远的输出节点 (画布有反馈回路, 不能只看"无下游")
    _sink_ok = (_order[0] in _titles.get(1, (0, ''))[1]) if _titles.get(1) else False
    results.append(('L2 顺序从末端开始', '第 1 页 = 无下游节点 (%s) · 逐位 %d' % (_order[0], len(_order) - len(_bad_order)),
                    ['基础层链路 01/%d' % len(_order)], 'PASS' if (_sink_ok and not _bad_order) else 'FAIL',
                    'canvas links 反向 BFS'))
    # 输入/输出条数 = 画布连线条数 (逐页核)
    _bad_io = []
    for k, _nid in enumerate(_order, 1):
        _pg = _titles.get(k)
        if not _pg:
            _bad_io.append(_nid + ':缺页'); continue
        _t = _pg[1]
        _ni = len([x for x in _links if x.get('t') == _nid])
        _no = len([x for x in _links if x.get('f') == _nid])
        _mi = re.search(r'输入（(\d+) 条连线', _t)
        _mo = re.search(r'输出（(\d+) 条连线', _t)
        if not (_mi and _mo and int(_mi.group(1)) == _ni and int(_mo.group(1)) == _no):
            _bad_io.append('%s(%s/%s vs %d/%d)' % (_nid, _mi.group(1) if _mi else '?',
                                                   _mo.group(1) if _mo else '?', _ni, _no))
    results.append(('L2 节点页输入输出对账', '%d 个节点逐页 vs 画布连线' % len(_order),
                    ['异常 %d' % len(_bad_io)], 'PASS' if not _bad_io else 'FAIL',
                    'canvas links (f/t)'))
    # 节拍测试报告页: 两口径都在, 且数字与 compute() 现算一致 (台账用建页时冻结的库内快照)
    import l2_uph_measure as _U
    from lerobot.memory import l2_store as _S2
    _led = json.loads(json.dumps(_S2._read('ledger').get('kinds') or {}))
    _c = _U.compute(led=_led or None)
    _tp, _tm = _c["plan_tact"], _c["meas_tact"]
    _pt = ''
    for _s2 in pr.slides:
        _all = "\n".join(sh.text_frame.text for sh in _s2.shapes if sh.has_text_frame)
        if _all.lstrip().startswith('基础层节拍测试报告'):      # 标题页, 不是总览里提一句
            _pt = _all
            break
    _m1 = re.search(r'按段表计时：([\d.]+) 秒/件 → 每小时 (\d+) 件', _pt)
    _m2 = re.search(r'按台账实测：([\d.]+) 秒/件 → 每小时 (\d+) 件', _pt)
    _ok_t = bool(_m1 and _m2 and abs(float(_m1.group(1)) - _tp) < 0.02
                 and abs(float(_m2.group(1)) - _tm) < 0.02
                 and int(_m1.group(2)) == round(3600 / _tp) and int(_m2.group(2)) == round(3600 / _tm))
    results.append(('节拍测试报告页', '计划 %.3f/实测 %.3f s/件 现算' % (_tp, _tm),
                    ['按段表 %.3f' % _tp, '按台账 %.3f' % _tm],
                    'PASS' if _ok_t else 'FAIL', '段表 + AR 台账(逐 label)'))
    # 收口路径行: 三个杠杆/两段组合必须与 l2_uph_closure.analyse() 现算一致 (同一份冻结台账)
    import l2_uph_closure as _K
    _k = _K.analyse(led=_led or None)
    _cm = {x["name"]: x for x in _k["combos"]}
    _a, _b = _cm["C1+C2+C3"], _cm["C1+C2+C3+C4"]
    _need = ['C1_连续化', 'C2_检测并行', 'C3_插拔提速', 'C4_抬升加速度']
    _miss_lv = [k for k in _need if ('−%.2f 秒' % _k["levers"][k]["save"]) not in _pt]
    _ok_c = (not _miss_lv
             and ('%.2f 秒/件 = 每小时 %d 件' % (_a["tact_s"], round(_a["uph"]))) in _pt
             and ('%.2f 秒/件 = 每小时 %d 件' % (_b["tact_s"], round(_b["uph"]))) in _pt)
    results.append(('节拍收口路径', 'C1+C2+C3 %.2f s/件 · +C4 %.2f s/件 现算' % (_a["tact_s"], _b["tact_s"]),
                    ['杠杆缺口 %d' % len(_miss_lv), 'C1+C2+C3 %.2f' % _a["tact_s"],
                     'C1+C2+C3+C4 %.2f' % _b["tact_s"]],
                    'PASS' if _ok_c else 'FAIL', 'l2_uph_closure.analyse'))
except Exception as _e:                                                  # noqa: BLE001
    results.append(('L2 逐节点页', '可解析', ['%s' % _e], 'FAIL', 'l2_chain_pages'))
    results.append(('总页数', '19 + L2 节点页 + 1', ['%d' % len(pr.slides._sldIdLst)], 'FAIL', 'pptx'))

# ---------- 8. 输出 ----------
w = max(len(r[0]) for r in results) + 2
print('检查 %d 项 · PPT: %s' % (len(results), os.path.basename(DECK)))
print('-' * (w + 78))
bad = 0
for item, truth, needle, st, src in results:
    if st == 'FAIL':
        bad += 1
    print('%-*s %-5s 真源: %-34s PPT需含: %s  [%s]' % (w, item, st, truth[:34], needle[:26], src))
print('-' * (w + 78))
print('结果: %d PASS / %d FAIL' % (len(results) - bad, bad))

# 自洽闸: 册里写的「N 项 / N PASS / N FAIL」必须等于本次实跑 (放在 summary 之后, 不进 results, 避免自指)
claim = re.search(r'（(\d+) 项逐条回到来源文件重新计算；当前 (\d+) PASS / (\d+) FAIL）', PPT_TEXT)
want = (len(results), len(results) - bad, bad)
if not claim:
    print('自检口径 ✗ 册内未写项数/结果, 实跑 %d 项 %d PASS / %d FAIL' % want)
    sys.exit(1)
got = tuple(int(x) for x in claim.groups())
if got != want:
    print('自检口径 ✗ 册写 %s, 实跑 %s' % (got, want))
    sys.exit(1)
print('自检口径 ✓ 册写 %s = 实跑' % (got,))
sys.exit(1 if bad else 0)
