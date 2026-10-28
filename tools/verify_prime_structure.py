# -*- coding: utf-8 -*-
"""verify_prime_structure.py — 「空间质数结构化理解能力」判据 (逐项 ✅/❌ + 证据 + 未验证项)。

覆盖: 规则1 锚点稀疏 / 规则2 唯一分解(可逆) / 规则3 谱对称正则(**只读性**——不许改写度量张量) /
      规则4 质数计数课程 / 版本唯一性(质数指纹互异+反解) / 产品协同(包含⇒整除) /
      唯一依据自洽(config/platform/zmax_product.json 回读比对) / 与元数据根服务同源(18 基元逐项相等) /
      引擎集成(ManifoldEngineLoop.step 真出 product_id+签名, 干跑不写记忆库) / 零回归(engine_loop 自检)。
幂等: 只读 + /tmp 探针带 pid 自清理; 不碰在跑的控制台进程。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_prime_structure.py
"""
from __future__ import annotations

import io
import json
import os
import random
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from lerobot.manifold import prime_structure as PS                              # noqa: E402
from lerobot.manifold.engine_loop import ManifoldEngineLoop                     # noqa: E402

OK, BAD, SKIP = [], [], []
PY = sys.executable or os.path.join(ROOT, "gui-venv311", "bin", "python")


def chk(name: str, ok: bool, ev: str) -> None:
    (OK if ok else BAD).append((name, ev))
    print("  %s %-46s %s" % ("✅" if ok else "❌", name, ev))


def main() -> int:
    t0 = time.time()
    print("═" * 100)
    print("空间质数结构化理解能力 · 判据")
    print("═" * 100)

    # ── 规则2: 唯一分解 (本设计唯一数学严格的一条) ────────────────────────────────
    print("\n[规则2] 唯一分解 — 原子结构 ⇄ 质数签名 (算术基本定理)")
    ids = sorted(PS.CAP_PRIMES)
    rnd = random.Random(20261013)
    bad = []
    for _ in range(30):
        items = [rnd.choice(ids) for _ in range(rnd.randint(1, 6))]      # 允许重复(带指数)
        s = PS.signature(items)
        back = PS.decompose(s)
        if sorted(back) != sorted(items):
            bad.append((items, s, back))
    chk("签名→分解 往返一致 (30 组随机含重数)", not bad, "30/30 一致" if not bad else "例: %s" % (bad[:1],))
    try:
        PS.signature(["不存在的基元"])
        chk("未知原子结构被拒 (不许静默)", False, "竟然接受了非法输入")
    except PS.PrimeError as e:
        chk("未知原子结构被拒 (不许静默)", True, "PrimeError: %s" % str(e)[:56])
    try:
        PS.decompose(PS.PRODUCT_PRIMES["550A"])
        chk("跨域不混叠 (产品质数在能力域分解必须失败)", False, "竟分解成功 ⇒ 域有重叠")
    except PS.PrimeError:
        chk("跨域不混叠 (产品质数在能力域分解必须失败)", True,
            "cap 域无法分解 %d ⇒ 三域互不相交" % PS.PRODUCT_PRIMES["550A"])
    prime_sets = set(PS.PRIMITIVE_PRIMES.values()) | set(PS.STAGE_PRIMES.values())
    disj = (not (prime_sets & set(PS.PRODUCT_PRIMES.values()))
            and not (prime_sets & set(PS.ITER_PRIMES))
            and not (set(PS.PRODUCT_PRIMES.values()) & set(PS.ITER_PRIMES)))
    chk("三质数域两两不相交 (唯一性的前提)", disj,
        "能力 2..101 · 产品 %s · 迭代 ≥%d" % (sorted(PS.PRODUCT_PRIMES.values()), PS.ITER_PRIMES[0]))

    # ── 规则1: 状态空间锚点稀疏化 ────────────────────────────────────────────────
    print("\n[规则1] 质数间隙约束状态空间 — 可固化锚点只在质数位")
    sp = PS.anchor_sparsity(128)
    non_prime = [i for i in range(2, 128) if i not in sp["allowed_anchors"]]
    chk("锚点集合全为质数", all(PS.anchor_ok(i) for i in sp["allowed_anchors"]),
        "n=128 → %d 个可固化位, 密度 %.4f" % (sp["allowed_anchor_count"], sp["density"]))
    chk("非质数位不可固化 (负例)", (not PS.anchor_ok(4)) and (not PS.anchor_ok(64)),
        "4/64 均 False; 非质数位 %d 个只允许插值" % len(non_prime))
    chk("密度符合 π(n)~n/ln n (量级一致)", 0.5 <= sp["allowed_anchor_count"] / sp["pn_ln_n_expected"] <= 2.0,
        "实测 %d vs n/ln n=%.2f" % (sp["allowed_anchor_count"], sp["pn_ln_n_expected"]))

    # ── 规则3: 谱条款 —— 只读性 + 数学可达性 (诚实版) ─────────────────────────────
    print("\n[规则3] 黎曼猜想条款 — 按诚实版落实: 只读谱偏离量正则, 绝不改写度量张量")
    g = np.diag([10.0, 10.0, 50.0, 10.0, 10.0, 10.0])                  # 在役唯一依据形状
    g0 = g.copy()
    r = PS.spectral_symmetry(g)
    chk("调用后度量张量逐位不变 (只读)", np.array_equal(g, g0),
        "max|Δg|=%.1e (正定 %s, det G 归一未被碰)" % (float(np.max(np.abs(g - g0))), r["positive_definite"]))
    chk("保留正定性判定", bool(r["positive_definite"]), "λmin=%.4f > 0" % r["lambda_min"])
    two = PS.spectral_symmetry(np.diag([3.0, 7.0]))
    chk("n=2 时'谱关于 1/2 对称'可达 (λ̃=[0.3,0.7] ⇒ 缺口 1.0)",
        abs(two["symmetry_gap"] - 1.0) < 1e-12 and two["exact_1_2_symmetry_reachable"],
        "symmetry_gap=%.4f · reachable=True" % two["symmetry_gap"])
    chk("n>2 时精确对称**数学上不可达** (成对补和为 1 ⇒ 总和 n/2 ≠ 1)",
        (not r["exact_1_2_symmetry_reachable"]) and r["symmetry_gap"] < 1.0,
        "n=6: reachable=False · symmetry_gap=%.4f (只能作偏离量正则)" % r["symmetry_gap"])
    both = PS.spectral_symmetry(np.diag([1.0, 1.0, 1.0, 100.0, 100.0, 100.0]))
    chk("质心偏离量可区分 (双峰对称 0  vs 单主方向 >0)",
        both["centroid_asymmetry"] < 1e-9 <= r["centroid_asymmetry"],
        "双峰 %.4f vs 在役单主方向 %.4f" % (both["centroid_asymmetry"], r["centroid_asymmetry"]))
    iso = PS.spectral_symmetry(np.diag([5.0] * 6))
    chk("各向同性 (区间退化) 按约定质心 0.5", abs(iso["centroid"] - 0.5) < 1e-12,
        "各向同性 centroid=%.4f ⇒ 偏离 %.4f" % (iso["centroid"], iso["centroid_asymmetry"]))
    chk("诚实标注: 在役唯一依据度量谱向单方向偏 (正则项的用武之地)", r["centroid_asymmetry"] > 0,
        "在役 centroid=%.4f · 偏离 %.4f" % (r["centroid"], r["centroid_asymmetry"]))

    # ── 规则4: 质数计数采样课程 ──────────────────────────────────────────────────
    print("\n[规则4] 质数计数约束课程 — 采样率 = π(step)/step")
    chk("step<2 采样率 = 1.0", PS.sample_rate(1) == 1.0, "sample_rate(1)=%.3f" % PS.sample_rate(1))
    chk("π(50)=15 ⇒ 采样率 0.30", abs(PS.sample_rate(50) - 0.3) < 1e-9, "sample_rate(50)=%.4f" % PS.sample_rate(50))
    cur = PS.curriculum(60)
    chk("课程标注质数步 (跳变点)", [c["step"] for c in cur if c["is_prime_step"]][:6] == [2, 3, 5, 7, 11, 13],
        "质数步 %s …" % [c["step"] for c in cur if c["is_prime_step"]][:8])

    # ── 版本唯一性 + 产品协同 (老倪: 每次系统更新都要有个质数结构表示唯一性) ─────
    print("\n[唯一性/协同] 版本质数指纹 + 550A/B/C 能力包含⇒签名整除")
    d = PS.load_products()
    fps = {rel: PS.fingerprint(m["product"], m["iteration"]) for rel, m in d["releases"].items()}
    vals = [v["fingerprint"] for v in fps.values()]
    chk("6 个发布指纹两两互异", len(set(vals)) == len(vals), "%d 个指纹全不同" % len(vals))
    rt = all(PS.read_fingerprint(v["fingerprint"])["product"] == v["product"]
             and PS.read_fingerprint(v["fingerprint"])["iteration"] == v["iteration"] for v in fps.values())
    chk("指纹可反解回 (产品, 迭代, 能力集)", rt, "6/6 反解自证")
    chk("5.50.3 指纹 = 唯一依据注册值", d["fingerprints"]["5.50.3"]["fingerprint"] == fps["5.50.3"]["fingerprint"],
        "5.50.3 = %d (hex %s)" % (fps["5.50.3"]["fingerprint"], fps["5.50.3"]["hex"][:12]))
    sigs = {k: PS.cap_signature_of(k) for k in ("550A", "550B", "550C")}
    chk("能力包含 550A⊆550B⊆550C", set(PS.caps("550A")) <= set(PS.caps("550B")) <= set(PS.caps("550C")),
        "能力数 %d/%d/%d" % tuple(len(PS.caps(k)) for k in ("550A", "550B", "550C")))
    chk("包含 ⇒ 签名整除 (协同不变量)", sigs["550B"] % sigs["550A"] == 0 and sigs["550C"] % sigs["550B"] == 0,
        "A|B: %s · B|C: %s" % (sigs["550B"] % sigs["550A"] == 0, sigs["550C"] % sigs["550B"] == 0))
    chk("唯一依据回读: capability_signatures 与我重算一致",
        all(d["capability_signatures"][k] == sigs[k] for k in sigs), "3/3 一致")

    # ── 与元数据根服务同源 (全系统数据一致性的地基) ──────────────────────────────
    print("\n[同源] 质数域 vs 元数据根服务 (元数据=系统数据库根服务)")
    try:
        import meta_moe_router as M
        m_ids = [m["id"] for m in M.META_PRIMITIVES]
        same = set(m_ids) == set(PS.PRIMITIVE_PRIMES)
        chk("18 个元数据基元与 META_PRIMITIVES 逐项同名", same,
            "%d 项, 差集 %s" % (len(m_ids), sorted(set(m_ids) ^ set(PS.PRIMITIVE_PRIMES))))
        chk("8 阶段与引擎 STAGES 逐项同名",
            set(PS.STAGE_PRIMES) == {"接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"},
            "阶段质数 %s" % list(PS.STAGE_PRIMES.values()))
    except Exception as e:                                                       # noqa: BLE001
        SKIP.append(("元数据同源", repr(e)[:80]))
        print("  ⏭ 元数据同源 未验证: %s" % repr(e)[:80])

    # ── 引擎集成 (L5 运行时自主进化的输入) ───────────────────────────────────────
    print("\n[集成] ManifoldEngineLoop.step 真出产品标识 + 结构签名 (干跑不写记忆库)")
    mem = os.path.join(ROOT, "zmax_data", "manifold", "prime_memory.json")
    before = os.path.getmtime(mem) if os.path.isfile(mem) else None
    eng = ManifoldEngineLoop(apply_updates=False)
    recs = [eng.step({"x": [0.0, 0.0, 0.0], "stage": "接近", "force": 0.0}),
            eng.step({"x": [0.01, 0.0, 0.002], "stage": "下降", "force": 3.0, "vel": [0.0, 0.0, -0.01]}),
            eng.step({"x": [0.01, 0.0, 0.004], "stage": "插入", "force": 5.0})]
    u0 = recs[0]["understand"]
    chk("每 tick 有结构化理解输出", all("understand" in r and r["understand"].get("signature", 0) > 0 for r in recs),
        "3 tick 签名 %s" % [r["understand"]["signature"] for r in recs])
    chk("产品标识随唯一依据 (550A/B/C 之一)", u0.get("product_id") in PS.PRODUCT_PRIMES,
        "product_id=%s" % u0.get("product_id"))
    chk("结构随真实载荷变化 (力/速度非零才计入)",
        recs[0]["understand"]["caps"] != recs[1]["understand"]["caps"],
        "tick0 %s vs tick1 %s" % (recs[0]["understand"]["caps"], recs[1]["understand"]["caps"]))
    after = os.path.getmtime(mem) if os.path.isfile(mem) else None
    chk("干跑 (apply_updates=False) 不写记忆库", before == after, "mtime %s → %s" % (before, after))
    chk("无 stage 时也能理解 (不崩)", eng.step({"x": [0, 0, 0]})["understand"]["signature"] > 0, "空 stage 仍出签名")

    # ── 零回归: 引擎自检 (20/20) ────────────────────────────────────────────────
    print("\n[零回归] engine_loop 自检")
    p = subprocess.run([PY, os.path.join(ROOT, "src", "lerobot", "manifold", "engine_loop.py")],
                       capture_output=True, text=True, timeout=300)
    tail = (p.stdout or "").strip().splitlines()[-1] if p.stdout else ""
    chk("engine_loop 自检全通过", "全部通过" in (p.stdout or ""), tail[:80] or (p.stderr or "")[:80])

    dt = time.time() - t0
    print("\n" + "═" * 100)
    print("结论: %d 项通过 · %d 项未过 · %d 项未验证 · 用时 %.1fs" % (len(OK), len(BAD), len(SKIP), dt))
    if BAD:
        print("未过:")
        for n, e in BAD:
            print("  ❌ %s — %s" % (n, e))
    print("═" * 100)
    out = os.path.join(ROOT, "reports", "prime_structure_judge.json")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with io.open(out, "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "pass": len(OK), "fail": len(BAD),
                       "skip": SKIP, "ok": [n for n, _ in OK], "bad": [n for n, _ in BAD]}, f,
                      ensure_ascii=False, indent=1)
        print("报告: %s" % out)
    except Exception:                                                            # noqa: BLE001
        pass
    return 0 if not BAD else 1


if __name__ == "__main__":
    raise SystemExit(main())
