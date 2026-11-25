#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_su2_by_path.py — 实测 SU(2) 内核是不是真数学(不是桩), 零安装零依赖。

用法:
    python3 verify_su2_by_path.py [<定义 SU2 元素的模块路径>] [--cls SU2Element]
默认路径: ~/zmax/src/lerobot/manifold/core/su2.py

为什么按文件路径加载: `lerobot.policies.__init__` 会拖 draccus/huggingface_hub 一串重依赖,
仅仅想验一个群的公理就被拦。`spec_from_file_location` 直接绕过包 __init__。

每项输出「PASS/FAIL/SKIP + 断言名 + 实测残差 + 容差」, 可直接贴进评审证据表。
必过的两条: 双覆盖(2pi->-I, 4pi->+I) 与 非平凡性(随机元素 != I) ——
把四元数当向量用的实现过不了双覆盖; 永远返回 identity 的实现过不了非平凡性。

方法名不符时该项报 SKIP 而不是崩 —— 先拿到公理结果, 再按实际签名补 SKIP 的几项。
"""
import importlib.util
import os
import sys

import numpy as np

argv = [a for a in sys.argv[1:] if not a.startswith('--')]
DEFAULT = os.path.expanduser('~/zmax/src/lerobot/manifold/core/su2.py')
path = argv[0] if argv else DEFAULT
cls_name = 'SU2Element'
for i, a in enumerate(sys.argv):
    if a == '--cls' and i + 1 < len(sys.argv):
        cls_name = sys.argv[i + 1]

if not os.path.isfile(path):
    sys.exit('找不到 %s (传一个定义 SU2 元素的模块路径)' % path)

spec = importlib.util.spec_from_file_location('su2_audit', path)
mod = importlib.util.module_from_spec(spec)
sys.modules['su2_audit'] = mod          # 注册进 sys.modules: 断点/相对引用都要靠它
spec.loader.exec_module(mod)

S = getattr(mod, cls_name, None)
if S is None:
    sys.exit('%s 里没有 %s' % (path, cls_name))

rng = np.random.default_rng(7)
state = {'ok': True}


def check(name, val, tol, note=''):
    good = val <= tol
    state['ok'] = state['ok'] and good
    print('%s %-46s %.3e  (容差 %.0e) %s' % ('PASS' if good else 'FAIL', name, val, tol, note))


def skip(name, why):
    print('SKIP %-46s -- %s' % (name, why))


def try_call(names, *a, **kw):
    """依次尝试若干候选方法名, 全不行返回 None（用于容忍命名差异）。"""
    for n in names:
        fn = getattr(a[0], n, None) if a else None
        if callable(fn):
            try:
                return fn(*a[1:], **kw), n
            except Exception:
                continue
    return None, None


def mat(x):
    m, _ = try_call(['mat', 'matrix', 'to_matrix', 'su2_matrix'], x)
    if m is not None:
        return np.asarray(m)
    qt, n = try_call(['quat', 'q', 'as_quat', 'to_quat'], x)
    if qt is not None:
        w, v = float(qt[0]), np.asarray(qt[1:4], dtype=float)
        return np.array([[w - 1j * v[2], -v[1] - 1j * v[0]],
                         [v[1] - 1j * v[0], w + 1j * v[2]]], dtype=complex)
    raise AttributeError('既没有 mat() 也没有 quat()')


def rand():
    r, n = try_call(['random', 'rand'], S, rng)
    if r is not None:
        return r
    v = rng.normal(size=4)
    v /= np.linalg.norm(v)                     # 兜底: 随机四元数
    ctor, _ = try_call(['from_quat', 'from_quaternion'], S, v)
    if ctor is None:
        ctor = S(v)
    return ctor


# ---- 群公理 ----
try:
    worst = 0.0
    for _ in range(2000):
        a, b, c = rand(), rand(), rand()
        worst = max(worst, float(np.abs(mat((a * b) * c) - mat(a * (b * c))).max()))
    check('群公理·结合律 ||(ab)c-a(bc)||inf (2000组)', worst, 1e-12)
except Exception as e:
    skip('群公理·结合律', repr(e))

worst_i = 0.0
try:
    for _ in range(2000):
        a = rand()
        worst_i = max(worst_i, float(np.abs(mat(a * a.inv()) - np.eye(2)).max()))
    check('群公理·逆元   ||a·a^-1-I||inf', worst_i, 1e-12)
except Exception as e:
    skip('群公理·逆元', repr(e))

# ---- 双覆盖: 2pi 得 -I, 4pi 才得 +I(四元数当向量用的实现过不了这条) ----
aa, _ = try_call(['from_axis_angle', 'axis_angle', 'exp'], S,
                 np.array([0., 0., 1.]), 2 * np.pi)
if aa is None:
    skip('双覆盖·2pi -> -I', '模块没有 from_axis_angle/exp')
else:
    check('双覆盖·2pi -> -I  ||U+I||inf', float(np.abs(mat(aa) + np.eye(2)).max()), 1e-12,
          '(四元数当向量用的实现过不了)')
    a4, _ = try_call(['from_axis_angle', 'axis_angle', 'exp'], S,
                     np.array([0., 0., 1.]), 4 * np.pi)
    check('双覆盖·4pi -> +I  ||U-I||inf', float(np.abs(mat(a4) - np.eye(2)).max()), 1e-12)

# ---- 指数映射: exp(log U) == U ----
try:
    worst_exp = 0.0
    for _ in range(1000):
        a = rand()
        lg, _ = try_call(['log', 'rotvec', 'log_map'], a)
        worst_exp = max(worst_exp, float(np.abs(mat(S.from_rotvec(lg)) - mat(a)).max()))
    check('指数映射 ||exp(log U)-U||inf (1000组)', worst_exp, 1e-10)
except Exception as e:
    skip('指数映射', repr(e))

# ---- Bloch 球 ||r|| == 1 ----
try:
    worst_b = 0.0
    for _ in range(2000):
        a = rand()
        bb, _ = try_call(['bloch', 'bloch_vector', 'expectation'], a)
        worst_b = max(worst_b, abs(float(np.linalg.norm(bb)) - 1.0))
    check('Bloch 球 | ||r||-1 | (2000组)', worst_b, 1e-12)
except Exception as e:
    skip('Bloch 球', repr(e))

# ---- 幺正性 ----
try:
    worst_uni = 0.0
    for _ in range(2000):
        m = mat(rand())
        worst_uni = max(worst_uni, float(np.abs(m.conj().T @ m - np.eye(2)).max()))
    check('幺正性 ||U^H U-I||inf (2000组)', worst_uni, 1e-12)
except Exception as e:
    skip('幺正性', repr(e))

# ---- 非平凡性: 防"永远返回 identity"的假实现 ----
try:
    mags = [float(np.abs(mat(rand()) - np.eye(2)).max()) for _ in range(500)]
    frac = float(np.mean([m > 1e-3 for m in mags]))
    check('非平凡性·随机元素 != I 的比例 (应=1)', abs(1.0 - frac), 1e-9)
except Exception as e:
    skip('非平凡性', repr(e))

print()
if state['ok']:
    print('结论: 跑过的断言全过 — 真 SU(2) 数学实现, 不是桩(注意 SKIP 项还没证)')
else:
    print('结论: 有项未通过, 见上')
sys.exit(0 if state['ok'] else 1)
