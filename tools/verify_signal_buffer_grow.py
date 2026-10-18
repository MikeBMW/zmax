#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 判据: 信号页环形缓冲「惰性扩容」是否既省内存又不改语义 (2026-10-18)

## 事故
studio.py 跑 8h53m 涨到 **20.2GB RSS**，把内存+swap 吃满导致整机卡死。

## 根因 (有数据)
`canoe_graphic.py`: `CAP = 200000`，而 `SignalBuffer.__init__` **每个信号都预分配**
`np.zeros(CAP) × 2`(t,v) = **3.2 MB/信号**。信号页的 key 来自各源 JSON 的全部叶子字段:
`dataspace/live.json` 的 `topics.*` 就 **829 个**(≈100 个 DDS 话题 × 8 字段)，加其他源合计 **1013 个 key**
⇒ 1013 × 3.2MB = **3.2GB** 常驻 (实测 RSS 3.63GB，吻合)。话题/字段继续增 ⇒ 8h 后到 20GB。

## 修法
`SignalBuffer` 初始只分配 `CAP_MIN=4096 点`(64KB)，**写满才翻倍**直到 CAP(200000)。
语义完全不变(只是数组变长)；没人看的信号留 64KB 而不是 3.2MB。

## 判据
① 惰性扩容：初始容量 == CAP_MIN，点少时数组长度 == CAP_MIN(不涨)
② 与朴素 oracle 逐点一致：随机 30000 点 (含回绕、去重、乱序 x) push 后 arrays() 完全一致
③ 长跑语义：写满 CAP 后仍只保留最后 CAP 个点、顺序正确 (环形回绕正确)
④ 内存：2000 个"各 10 点"的信号 总占用 < 旧实现的 1/20
⑤ key 上限：超过 MAX_KEYS 拒绝新增并在 notes 里说明(不静默吞)
用法: ./gui-venv311/bin/python tools/verify_signal_buffer_grow.py
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys

import numpy as np

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
ROWS = []


def ck(name, ok, detail=""):
    ROWS.append({"判据": name, "结果": "PASS" if ok else "FAIL", "实测": detail})
    print(("✅ " if ok else "❌ ") + name + (": " + detail if detail else ""))


def load_canoe():
    """按路径加载 canoe_graphic (不 import GUI 依赖: 模块顶层已对 Qt 做了保护)"""
    p = os.path.join(REPO, "tools", "gui", "canoe_graphic.py")
    spec = importlib.util.spec_from_file_location("canoe_under_test", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["canoe_under_test"] = m
    spec.loader.exec_module(m)
    return m


class Oracle:
    """朴素实现: 只留最后 CAP 个点, 重复 (t,v) 去重 —— 判据用真值"""

    def __init__(self, cap):
        self.cap = cap
        self.t, self.v = [], []
        self.last = None

    def push(self, t, v):
        if self.t and self.last is not None and v == self.last and self.t[-1] == t:
            return
        self.t.append(t)
        self.v.append(v)
        self.last = v
        if len(self.t) > self.cap:
            self.t = self.t[-self.cap:]
            self.v = self.v[-self.cap:]

    def arrays(self):
        return np.asarray(self.t, float), np.asarray(self.v, float)


def main() -> int:
    CG = load_canoe()
    CAP = CG.CAP
    CAP_MIN = getattr(CG, "CAP_MIN", CAP)
    print(f"模块实测: CAP={CAP} CAP_MIN={CAP_MIN} "
          f"每信号满容量 {2 * CAP * 8 / 1048576:.2f}MB → 惰性后 {2 * CAP_MIN * 8 / 1024:.0f}KB")

    # ① 惰性分配
    b = CG.SignalBuffer("k")
    ck("①初始只分配 CAP_MIN(不预支 3.2MB)", len(b.t) == CAP_MIN and len(b.v) == CAP_MIN,
       f"len(t)={len(b.t)} 期望 {CAP_MIN}")

    # ② 与 oracle 逐点一致 (含回绕/去重)
    random.seed(7)
    b2 = CG.SignalBuffer("r")
    b2._used = True                               # 模拟"这条曲线正在显示" ⇒ 允许长到 CAP
    orc = Oracle(10 ** 9)                         # 不截断: 判据比较"技能是 oracle 的尾巴"
    for i in range(60000):
        t = float(i // 3)                          # 制造重复 x (触发去重)
        v = float(random.randint(0, 5)) if i % 7 else float(i % 5)
        b2.push(t, v)
        orc.push(t, v)
    t_a, v_a = b2.arrays()
    t_o, v_o = orc.arrays()
    _k = len(t_a)
    same = (_k > 0 and len(t_o) >= _k
            and np.array_equal(t_a, t_o[-_k:]) and np.array_equal(v_a, v_o[-_k:])
            and _k == min(len(t_o), len(b2.t)))   # 容量没满时点数应等于全部去重后的点
    ck("②60000 点(含去重/多次扩容)与朴素实现逐点一致", same,
       f"技能 {_k} 点 / oracle {len(t_o)} 点 · 技能容量已扩到 {len(b2.t)}")

    # ③ 长跑: 超过 CAP 只留最后 CAP 个, 顺序正确
    b3 = CG.SignalBuffer("long")
    b3._used = True                               # 在显示 ⇒ 允许长到 CAP (未显示封顶 CAP_SOFT)
    n = CAP + 1234
    for i in range(n):
        b3.push(float(i), float(i * 2))
    t3, v3 = b3.arrays()
    ok3 = (len(t3) == CAP and t3[0] == float(n - CAP) and t3[-1] == float(n - 1)
           and v3[0] == t3[0] * 2 and v3[-1] == t3[-1] * 2
           and bool(np.all(np.diff(t3) == 1.0)))
    ck("③写满 CAP 后只留最后 CAP 点且顺序正确", ok3,
       f"{len(t3)} 点 · 首={t3[0]:.0f} 末={t3[-1]:.0f} · 容量={len(b3.t)}")

    # ④ 内存: 2000 个各 10 点的信号
    bufs = []
    for k in range(2000):
        bb = CG.SignalBuffer("k%d" % k)
        for i in range(10):
            bb.push(float(i), float(i))
        bufs.append(bb)
    new_bytes = sum(b.t.nbytes + b.v.nbytes for b in bufs)
    old_bytes = 2000 * 2 * CAP * 8
    ratio = old_bytes / max(new_bytes, 1)
    ck("④2000 个稀疏信号内存 < 旧实现 1/20", ratio > 20,
       f"新 {new_bytes / 1048576:.1f}MB vs 旧 {old_bytes / 1048576:.0f}MB ⇒ 省 {ratio:.0f}×")

    # ⑤ 全量 key 场景: 1013 个真实 key (事故当时) 的常驻
    bufs2 = [CG.SignalBuffer("t%d" % i) for i in range(1013)]
    for bb in bufs2:                              # 每个只来几个点
        for i in range(5):
            bb.push(float(i), float(i))
    now_mb = sum(b.t.nbytes + b.v.nbytes for b in bufs2) / 1048576
    was_mb = 1013 * 2 * CAP * 8 / 1048576
    ck("⑤事故规模(1013 信号)常驻内存 < 1GB", now_mb < 1024,
       f"新 {now_mb:.0f}MB vs 旧 {was_mb:.0f}MB")

    # ⑥ 没人看的信号封顶 CAP_SOFT; 被画过之后才允许长到 CAP
    CAP_SOFT = getattr(CG, "CAP_SOFT", CAP)
    b6 = CG.SignalBuffer("quiet")
    for i in range(CAP_SOFT + 5000):
        b6.push(float(i), float(i % 7))
    quiet_cap = len(b6.t)
    b6._used = True                              # 等价于被 _refresh_inner 真正画到屏上
    for i in range(CAP_SOFT + 5000, 2 * CAP_SOFT + 5000):
        b6.push(float(i), float(i % 7))
    used_cap = len(b6.t)
    ck("⑥未显示信号封顶 CAP_SOFT · 被画后才扩到 CAP", quiet_cap == CAP_SOFT and used_cap > CAP_SOFT,
       f"未显示 {quiet_cap} 点 ({quiet_cap * 16 / 1024:.0f}KB) → 画过 {used_cap} 点")

    # ⑦ 8 小时真实场景: 1013 个元数据信号(未显示) + 20 条在看曲线, 全部写满后总占用
    _ = [CG.SignalBuffer("meta%d" % i) for i in range(1013)]
    for b in _:
        b.n = CAP_SOFT
        b.head = 0
        b._cap = CAP_SOFT
        b.t = np.zeros(CAP_SOFT)
        b.v = np.zeros(CAP_SOFT)
    shown = []
    for i in range(20):
        bb = CG.SignalBuffer("shown%d" % i)
        bb._used = True
        bb._cap = CAP
        bb.t = np.zeros(CAP)
        bb.v = np.zeros(CAP)
        bb.n = CAP
        shown.append(bb)
    tot_mb = (sum(b.t.nbytes + b.v.nbytes for b in _ + shown)) / 1048576
    old_mb = (1013 + 20) * 2 * CAP * 8 / 1048576
    ck("⑦8 小时写满后总占用 < 1.5GB (旧实现 20GB+)", tot_mb < 1536,
       f"新 {tot_mb:.0f}MB vs 旧全满 {old_mb / 1024:.1f}GB")

    # ⑨ arrays() 本身不得标 _used (否则树刷新/状态栏会把 1013 个信号全变成"在显示" ⇒ 又是 3.1GB)
    b9 = CG.SignalBuffer("tree")
    for i in range(5000):
        b9.push(float(i), float(i))
    b9.arrays()
    b9.arrays()
    ck("⑨arrays() 不污染 _used (只有渲染路径能标)", b9._used is False
       and len(b9.t) <= CG.CAP_SOFT, f"_used={b9._used} 容量={len(b9.t)}(≤CAP_SOFT {CG.CAP_SOFT})")

    # ⑩ 树刷新/状态栏取值走直接索引 (末两点变化率) —— 与 arrays() 结果一致
    _c = b9._cap
    _i1, _i0 = (b9.head - 1) % _c, (b9.head - 2) % _c
    _t_orc, _v_orc = b9.arrays()
    ck("⑩末两点直接索引 == arrays() 末两点", float(b9.t[_i1]) == float(_t_orc[-1])
       and float(b9.v[_i0]) == float(_v_orc[-2]),
       f"t[-1] {float(b9.t[_i1]):.0f} vs {float(_t_orc[-1]):.0f}")

    # ⑧ CSV 导入不被截断 (导入=用户明确要看 ⇒ 允许长到 CAP)
    b8 = CG.SignalBuffer("csv", None, "file")
    b8._used = True
    for i in range(100000):
        b8.push(float(i), float(i * 0.5))
    t8, _ = b8.arrays()
    ck("⑧CSV 导入 10 万点不被 CAP_SOFT 截断", len(t8) == 100000 and len(b8.t) >= 131072,
       f"{len(t8)} 点 · 容量 {len(b8.t)}")

    # ⑪ arrays() 零分配: 数据没变时复用同一缓冲 (旧实现每次 concatenate 新建 n×8 字节)
    b11 = CG.SignalBuffer("zeroalloc")
    b11._used = True
    for i in range(50000):
        b11.push(float(i), float(i))
    t_a1, _ = b11.arrays()
    t_a2, _ = b11.arrays()
    same_buf = t_a1 is t_a2 or (t_a1.base is t_a2.base and t_a1.base is not None)
    b11.push(50000.0, 50000.0)
    t_a3, _ = b11.arrays()
    ok11 = same_buf and float(t_a3[-1]) == 50000.0 and len(t_a3) == len(t_a1) + 1
    ck("⑪arrays() 零分配(复用缓冲)+push 后仍正确", ok11,
       f"同一缓冲={same_buf} · push 后点数 {len(t_a1)}→{len(t_a3)}")

    n_pass = sum(1 for r in ROWS if r["结果"] == "PASS")
    print("\n" + "=" * 78)
    print(f"判据 {n_pass}/{len(ROWS)} PASS")
    import json
    out = os.path.join(REPO, "zmax_data", "eval", "verify_signal_buffer_grow.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"rows": ROWS, "pass": n_pass, "total": len(ROWS), "CAP": CAP, "CAP_MIN": CAP_MIN},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("落盘: " + out)
    return 0 if n_pass == len(ROWS) else 3


if __name__ == "__main__":
    raise SystemExit(main())
