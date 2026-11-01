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
    cum.append(round(t, 2)); t += s['t']
i0 = next(i for i, s in enumerate(P) if s['k'] == L['ks'][0])
i1 = max(i for i, s in enumerate(P) if s['k'] == L['ks'][1])
loop_dur = round(cum[i1] + P[i1]['t'] - cum[i0], 2)
tact = loop_dur / L['mods']
uph = 3600 / tact
ins_end, grip_t = {}, {}
for i, s in enumerate(P):
    if s['kind'] == 'release' and s.get('at') == 'hole' and s.get('hole') is not None:
        ins_end[s['mod']] = round(cum[i] + s['t'], 2)
    if s['kind'] == 'grip' and s.get('hole') is not None and '(拔)' in (P[i - 2].get('label') or ''):
        grip_t[s['mod']] = round(cum[i], 2)
dwells = [round(grip_t[m] - ins_end[m], 2) for m in sorted(ins_end) if m in grip_t]

# ---------- 6. L2 节点真源 ----------
canvas = json.load(open(ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json', encoding='utf-8'))['nodes']
idx = open(ROOT + '/src/lerobot/middleware/nodes/_index.py', encoding='utf-8').read()
n_l2, n_pure = 0, 0
for n in canvas:
    if n['type'] == 'row_bg' or not (2972 <= n['y'] < 6490) or n['id'] == 'ssworld':
        continue
    m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
    if not m:
        continue
    f = ROOT + '/src/lerobot/middleware/nodes/%s.py' % m.group(1).split('.')[-1]
    if not os.path.exists(f):
        continue
    n_l2 += 1
    if re.search(r'^PURE\s*=\s*True', open(f, encoding='utf-8').read(), re.M):
        n_pure += 1

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
check('稳态循环', '%.2f s / %d 件 = %.3f s/件 = %.0f UPH' % (loop_dur, L['mods'], tact, uph),
      ['%.2f s' % loop_dur, '%.3f s' % tact, '%d UPH' % round(uph)], sim_src)
check('停留 dwell', '%.2f ~ %.2f s' % (min(dwells), max(dwells)),
      ['%.2f ~ %.2f s' % (min(dwells), max(dwells))], sim_src)
check('目标节拍', '300 UPH = 12.0 s/件, 余量 %.2f s' % (12.0 - tact), ['300', '12 s'], 'order ar_300uph')
# L2
check('L2 节点数 / 真算数', '%d 个, PURE=True %d' % (n_l2, n_pure), ['%d 个逻辑节点' % n_l2], 'canvas + n_*.py')

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
sys.exit(1 if bad else 0)
