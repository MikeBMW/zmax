#!/usr/bin/env python3
"""真机连杆正解 + 长方体侵入检查。

为什么需要它: tools/precheck_move.py 用的是**固定连杆模型**(不看当前关节角),
实测在 [594.5,141.8,298.6] 报 PASS 145.6mm, 但现场三维视图显示撞上「上横梁」。
本脚本用 URDF + latest.json 的真实 joint 角做正解, 给出每级 link 的实际位置。

用法:
  gui-venv311/bin/python tools/fk_link_check.py                 # 当前姿态
  gui-venv311/bin/python tools/fk_link_check.py --joints 0.4,0.08,-1.8,-0.74,-0.96,1.47
"""
import argparse
import json
import math
import os
import xml.etree.ElementTree as ET

import numpy as np

URDF = os.path.join(os.path.dirname(__file__), '..', 'zmax_data', 'rokae_sdk', 'urdf',
                    'xms5_r800_w4g3b4c.urdf')
LATEST = os.path.join(os.path.dirname(__file__), '..', 'zmax_data', 'rokae_sdk', 'tcp_out',
                      'latest.json')
FENCE = 'http://127.0.0.1:8797/api/fence'


def rpy2R(r, p, y):
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]], float)
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], float)
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], float)
    return Rz @ Ry @ Rx


def axis_rot(axis, ang):
    a = np.array(axis, float)
    n = np.linalg.norm(a)
    if n < 1e-12:
        return np.eye(3)
    a = a / n
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]], float)
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)


def T(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def load_chain(path):
    root = ET.parse(path).getroot()
    joints = []
    for j in root.findall('joint'):
        o = j.find('origin')
        xyz = [float(v) for v in (o.get('xyz', '0 0 0').split() if o is not None else [0, 0, 0])]
        rpy = [float(v) for v in (o.get('rpy', '0 0 0').split() if o is not None else [0, 0, 0])]
        ax = j.find('axis')
        axis = [float(v) for v in (ax.get('xyz', '1 0 0').split() if ax is not None else [1, 0, 0])]
        joints.append({'name': j.get('name'), 'type': j.get('type'),
                       'parent': j.find('parent').get('link'),
                       'child': j.find('child').get('link'),
                       'xyz': xyz, 'rpy': rpy, 'axis': axis})
    return joints


def solve(path, q):
    joints = load_chain(path)
    moving = [j for j in joints if j['type'] == 'revolute']
    cur = np.eye(4)
    chain = [('base', cur.copy())]
    qi = 0
    for j in moving:
        cur = cur @ T(rpy2R(*j['rpy']), j['xyz'])
        if qi < len(q):
            cur = cur @ T(axis_rot(j['axis'], q[qi]), [0, 0, 0])
        qi += 1
        chain.append((j['child'], cur.copy()))
    return chain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--joints', default='')
    ap.add_argument('--urdf', default=URDF)
    a = ap.parse_args()

    if a.joints:
        q = [float(v) for v in a.joints.split(',')]
    else:
        d = json.load(open(LATEST, encoding='utf-8'))
        q = [float(v) for v in (d.get('joint') or [])[:6]]

    chain = solve(a.urdf, q)
    print('joint 角(rad): %s' % [round(v, 4) for v in q])
    print('\n每级 link 原点(base_link 坐标, mm):')
    for name, M in chain:
        p = M[:3, 3] * 1000
        print('  %-28s [%8.1f, %8.1f, %8.1f]' % (name, p[0], p[1], p[2]))

    # 围栏 AABB
    try:
        import urllib.request
        fd = json.load(urllib.request.urlopen(FENCE, timeout=6))
    except Exception as e:
        print('\n(取围栏失败: %s)' % e)
        return
    boxes = {}
    stack = [fd]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get('type') == 'box' or ('p1' in o and 'p2' in o):
                p1 = np.array(o['p1'], float) * 1000
                p2 = np.array(o['p2'], float) * 1000
                boxes[o.get('name', '?')] = (np.minimum(p1, p2), np.maximum(p1, p2))
            for v in o.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(o, list):
            stack.extend(o)

    print('\nlink 原点到长方体距离 (mm)  [括号内=扣除本体半径后的间隙]:')
    RAD = {'link3': 70.0, 'link4': 78.0, 'link5': 62.0, 'link6': 58.0}
    hdr = '  %-8s %-6s' % ('link', 'r')
    for b in boxes:
        hdr += '%-22s' % b[:20]
    print(hdr)
    for name, M in chain[2:]:
        p = M[:3, 3] * 1000
        short = name.split('_')[-1] if '_' in name else name
        short = short.replace('XMS5-R800-W4G3B4C_', '').replace('XMS5-R800-W4', '')
        r = 0.0
        for k, v in RAD.items():
            if k in name:
                r = v
        print('  %-8s %-6.0f' % (short[-8:], r), end='')
        for b, (A, B) in boxes.items():
            dd = float(np.linalg.norm(p - np.clip(p, A, B)))
            gap = dd - r
            mark = ' ⛔侵入' if gap < 0 else (' ⚠' if gap < 20 else '')
            print('%-22s' % ('%.1f→%+.0f%s' % (dd, gap, mark)), end='')
        print()


if __name__ == '__main__':
    main()
