# -*- coding: utf-8 -*-
"""prime_structure.py — 空间质数结构化理解能力 (流形引擎 · 理解层)

口径 (与老倪给定文档《流形引擎·用质数约束泛化性》) 对应关系, 逐条如实:

  规则1 质数间隙约束状态空间  -> 本模块 anchor_ok / anchor_sparsity:
      状态空间里**可固化的锚点**(记忆点/示教点)只允许落在质数索引位, 非质数位只允许插值。
      诚实说明: 这条约束的是"离散化/固化"的稀疏性(质数密度 ~ 1/ln N), 从而限制系统"在任何位置都记住";
      它不改变连续状态空间本身的度量。

  规则2 唯一分解约束技能库    -> signature / decompose (原子技能与元数据基元都编码为质数):
      复杂结构 = 原子结构质数的乘积; 由**算术基本定理**, 该乘积与"用了哪些原子、各几次"一一对应,
      因此可逆分解、无冗余、无黑箱。这是本模块唯一"数学上完全严格"的一条。

  规则3 黎曼猜想约束度量张量  -> spectral_symmetry (**按诚实版落实**):
      文档给的写法 (把特征值部部置到 0.5 + 1j*间隙, 再 np.diag 重建) 在数学上是错的:
        (a) 实对称正定度量张量的特征值必为实数, 强行置成复数会得到**非 Hermite 矩阵**,
            直接破坏本工程在用的正定闸门与 det G = 1 归一;
        (b) 黎曼猜想本身**未被证明**, 任何实现都不能声称"用了它"。
      故本条按**谱对称正则**落实: 取归一化谱 λ̃ = λ/tr(g) (和为 1, 落在 (0,1)), 量它的
      关于 1/2 的对称度 sym = 1 - mean|λ̃_i - (1 - λ̃_{n-1-i})|; sym=1 表示谱完美对称。
      本模块**只用它作正则度量**(惩罚谱不对称), 绝不改写 g ⇒ 与既有 23/23(主参数M)、20/20(闭环) 判据零冲突。
      诚实注记: 归一化后谱的对称中心恰是 1/2 —— 与临界线是同一个数, 但这是"和为1"归一化的必然结果,
      **不构成与黎曼猜想的任何关系**; 本工程不声称证明 RH。

  规则4 质数计数约束课程      -> sample_rate / curriculum:
      采样率 = π(step)/step (质数计数函数/步数); 质数步发生跳变(强制跳跃式学习, 抑制局部记忆)。

版本唯一性 (老倪: "每次系统更新，都要有个质数结构，表示唯一性"):
  fingerprint(product, caps, iteration) = p_prod · p_iter · Π p_cap
  三个质数域**互不相交**(产品域 / 迭代域 / 能力域) ⇒ 由算术基本定理, 该整数与
  (产品, 能力集合含重数, 迭代序号) 一一对应 ⇒ 可逆、唯一、可比对 (能力集合的包含关系 ⇒ 整除关系)。

数据结构真源: config/platform/zmax_product.json (产品配置: 550A 原创版 / 550B 标定版 / 550C 量产版)
理解记忆真源: zmax_data/manifold/prime_memory.json (未见结构事件 = 自主进化的输入)

CLI: report | sign <domain> <id,...> | decompose <n> [domain] | fingerprint <产品> <迭代> |
     understand <id,...> | sparsity <N> | symmetry
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")
MEMORY_J = os.path.join(ROOT, "zmax_data", "manifold", "prime_memory.json")

# ── 质数域 (互不相交, 这是唯一性的前提) ────────────────────────────────────────────
class PrimeError(ValueError):
    pass


def _sieve(n: int) -> list[int]:
    ok = [True] * (n + 1)
    ok[0] = ok[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if ok[i]:
            for j in range(i * i, n + 1, i):
                ok[j] = False
    return [i for i in range(n + 1) if ok[i]]


def _meta_ids() -> list:
    """元数据基元真源 = 元数据根服务实现 (tools/meta_moe_router.py 的 META_PRIMITIVES)。

    本表**从真源生成, 绝不手写**: 第一版手写的 18 项与真源不符 (m_grasp/m_slot/m_gold 等根本不存在),
    被 tools/verify_prime_structure.py 的"逐项同名"判据当场抓到 ⇒ 改为硬依赖真源, 读不到直接报错。
    """
    tools_dir = os.path.join(ROOT, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import meta_moe_router as _M
    except Exception as e:                                                       # noqa: BLE001
        raise PrimeError("读不到元数据根服务真源 tools/meta_moe_router.py: %r" % e)
    ids = [p["id"] for p in _M.META_PRIMITIVES]
    if len(ids) < 2:
        raise PrimeError("元数据根服务真源异常: 只有 %d 项基元" % len(ids))
    return ids


_PRIMES = _sieve(12000)
META_IDS = _meta_ids()
# 域1 能力域: 元数据基元 (真源顺序) → 前 N 个质数
PRIMITIVE_PRIMES = {k: _PRIMES[i] for i, k in enumerate(META_IDS)}
# 域1b 能力域(续): 阶段/原子技能 8 项 → 紧随其后的 8 个质数 (与元数据基元同域但不同质数 ⇒ 同域组合仍唯一)
STAGE_IDS = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
STAGE_PRIMES = {k: _PRIMES[len(META_IDS) + i] for i, k in enumerate(STAGE_IDS)}

# 域2 产品域: 550A/B/C → 三个质数 (≥1000, 与能力域不相交)
PRODUCT_PRIMES = {"550A": 1009, "550B": 1013, "550C": 1019}
# 域3 迭代域: 第 N 次系统更新 → 质数 (≥1031)
ITER_PRIMES = [p for p in _PRIMES if p >= 1031]

CAP_PRIMES = dict(PRIMITIVE_PRIMES)
CAP_PRIMES.update(STAGE_PRIMES)


# ── 规则2: 唯一分解 (质数编码 / 可逆分解) ─────────────────────────────────────────
def signature(items, domain: str = "cap") -> int:
    """把一组原子结构编码成一个整数。重复出现即计入指数 (算术基本定理同样覆盖指数)。"""
    table = CAP_PRIMES if domain == "cap" else (PRODUCT_PRIMES if domain == "prod" else None)
    if table is None:
        raise PrimeError("未知域: %s (只支持 cap|prod)" % domain)
    n = 1
    for it in items:
        if it not in table:
            raise PrimeError("未知原子结构 %r (域=%s)" % (it, domain))
        n *= table[it]
    return n


def decompose(n: int, domain: str = "cap") -> list[str]:
    """唯一分解: 还原出原子结构列表 (含重数)。分解不干净 ⇒ 报错, 绝不猜。"""
    table = CAP_PRIMES if domain == "cap" else (PRODUCT_PRIMES if domain == "prod" else None)
    if table is None:
        raise PrimeError("未知域: %s" % domain)
    out, rest = [], int(n)
    for name, p in sorted(table.items(), key=lambda kv: kv[1]):
        while rest % p == 0:
            out.append(name)
            rest //= p
    if rest != 1:
        raise PrimeError("整数 %d 在域 %s 内分解不干净 (残 %d) ⇒ 它不是该域的合法编码" % (n, domain, rest))
    return out


def cap_signature_of(product: str) -> int:
    return signature(caps(product), "cap")


def caps(product: str) -> list[str]:
    d = load_products()
    p = d["products"].get(product)
    if not p:
        raise PrimeError("未知产品 %s" % product)
    return list(p["capabilities"])


# ── 版本唯一性: 质数指纹 ──────────────────────────────────────────────────────────
def fingerprint(product: str, iteration: int, caps_override=None) -> dict:
    """指纹 = p_prod · p_iter · Π p_cap ⇒ 唯一、可逆 (三个质数域互不相交)。"""
    if product not in PRODUCT_PRIMES:
        raise PrimeError("未知产品 %s (只支持 %s)" % (product, "/".join(sorted(PRODUCT_PRIMES))))
    if not 1 <= int(iteration) <= len(ITER_PRIMES):
        raise PrimeError("迭代序号 %s 超出范围 1..%d" % (iteration, len(ITER_PRIMES)))
    cs = list(caps_override if caps_override is not None else caps(product))
    csig = signature(cs, "cap")
    prod_p, it_p = PRODUCT_PRIMES[product], ITER_PRIMES[int(iteration) - 1]
    f = prod_p * it_p * csig
    return {"fingerprint": f, "product": product, "iteration": int(iteration),
            "iter_prime": it_p, "product_prime": prod_p, "cap_signature": csig,
            "capabilities": cs, "hex": "%x" % f}


def read_fingerprint(n: int) -> dict:
    """反解: 从指纹还原 (产品, 迭代, 能力集合) —— 唯一性/可逆性的实测入口。"""
    rest = int(n)
    prod = None
    for k, p in PRODUCT_PRIMES.items():
        if rest % p == 0:
            prod, rest = k, rest // p
            break
    if prod is None:
        raise PrimeError("指纹 %d 不含任何产品质数" % n)
    it_p = None
    for i, p in enumerate(ITER_PRIMES, 1):
        if rest % p == 0:
            it_p, rest = i, rest // p
            break
    if it_p is None:
        raise PrimeError("指纹 %d 不含迭代质数" % n)
    return {"product": prod, "iteration": it_p, "capabilities": decompose(rest, "cap"),
            "cap_signature": rest}


# ── 产品配置真源 ─────────────────────────────────────────────────────────────────
def load_products() -> dict:
    with io.open(PRODUCT_J, encoding="utf-8") as f:
        return json.load(f)


def active_product() -> str:
    """当前产品号 (真源 config/platform/zmax_product.json 的 active_product)。

    2026-10-15 (老倪「保证全局数据同步」): 原来 `d.get("active_product") or "550A"` —— 真源读不出该键时
    **静默退回 550A**, 于是 550B 的工程里可能带着 550A 的产品号继续跑, 谁也不知道。现在缺键会**喊一声**,
    仍返回 550A 兜住调用方 (引擎常驻回路不能因为一个键就被打断), 但不再是静默的。
    """
    d = load_products()
    _v = d.get("active_product")
    if not _v:
        try:
            import sys as _s
            _s.stderr.write("⚠️ 产品真源 %s 里没有 active_product ⇒ 本次退回 550A (不是真源的值, 请核对)\n"
                            % PRODUCT_J)
        except Exception:                                                       # noqa: BLE001
            pass
        return "550A"
    return str(_v)


# ── 规则3: 谱对称正则 (诚实版 —— 不改写 g, 不声称 RH) ─────────────────────────────
def spectral_symmetry(g) -> dict:
    """谱的对称性度量 (只读, 绝不改写 g)。诚实版 —— 见 note/reachable 说明。

    两个口径都给:
      (a) 补对称缺口 symmetry_gap: 1 - mean_i|λ̃_i + λ̃_{n-1-i} - 1| (λ̃ = λ/tr(g), 和为 1)。
          取 1 表示谱在 λ̃→1-λ̃ 下不变 (即"关于 1/2 对称")。
      (b) 质心偏离 centroid_asymmetry: |centroid(λ̂) - 0.5|, λ̂ = (λ-λmin)/(λmax-λmin) 落在 [0,1]。
          取 0 表示谱质量关于区间中点 1/2 平衡 (双峰对称);
          单主方向/单峰谱会偏离 0.5 (这是我方在役度量的真实状态)。

    数学事实 (必须诚实说): 在 "和为 1" 的归一化下, 谱关于 1/2 精确对称要求特征值成对 (a, 1-a),
    每对和为 1 ⇒ 总和 = n/2 ≠ 1 (n>2 时不可能)。故 (a) 只有在 n==2 时才可能取 1;
    n>2 时它只能作为**偏离量正则项**使用 —— 这正是文档《用质数约束泛化性》规则3 在 n>2 时不可达的地方
    (原文档"把特征值实部置 1/2 再重建"还会把实对称正定度量变成非 Hermite 复数矩阵, 破坏正定与 det G=1,
     本实现不采用)。黎曼猜想本身未被证明, 本工程不声称与它有证明关系。
    """
    a = np.asarray(g, dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise PrimeError("g 必须是方阵, 收到 %s" % (a.shape,))
    sym_part = (a + a.T) / 2.0
    lam = np.sort(np.linalg.eigvalsh(sym_part))
    tr = float(np.trace(sym_part))
    if tr <= 0:
        raise PrimeError("度量张量迹非正 (%.3g) ⇒ 非正定, 谈不上谱对称" % tr)
    n = len(lam)
    lam_t = lam / tr
    gap = float(np.mean([abs(lam_t[i] + lam_t[n - 1 - i] - 1.0) for i in range(n)]))
    if lam[-1] > lam[0]:
        lam_hat = (lam - lam[0]) / (lam[-1] - lam[0])
        centroid = float(np.mean(lam_hat))
    else:                                                                        # 各向同性: 区间退化
        lam_hat, centroid = np.full(n, 0.5), 0.5
    return {"trace": tr, "lambda_min": float(lam[0]), "lambda_max": float(lam[-1]),
            "normalized_spectrum": [round(float(x), 6) for x in lam_t],
            "symmetry_gap": round(1.0 - gap, 9), "gap_penalty": round(gap, 9),
            "centroid": round(centroid, 9), "centroid_asymmetry": round(abs(centroid - 0.5), 9),
            "symmetry_centered": round(1.0 - 2.0 * abs(centroid - 0.5), 9),
            "positive_definite": bool(lam[0] > 0), "dim": n,
            "exact_1_2_symmetry_reachable": bool(n == 2),
            "note": "只读正则项, 不改写 g (保正定与 det G=1); n>2 时'谱对称于1/2'在归一化下不可达, "
                    "只作偏离量正则; 与黎曼猜想无证明关系"}


# ── 规则1: 状态空间锚点稀疏化 (质数位才允许固化) ───────────────────────────────────
def anchor_ok(index: int) -> bool:
    return int(index) in set(_PRIMES)


def anchor_sparsity(n: int) -> dict:
    """前 n 个索引位里允许固化的位 (质数位) 与稀疏度。"""
    n = int(n)
    allowed = [i for i in _PRIMES if i <= n]
    want = n / max(1e-9, np.log(max(n, 3)))
    return {"n": n, "allowed_anchor_count": len(allowed), "allowed_anchors": allowed,
            "density": round(len(allowed) / max(n, 1), 6), "pn_ln_n_expected": round(want, 3),
            "note": "非质数位只允许插值, 不允许固化 ⇒ 限制'在任何位置都记住'"}


# ── 规则4: 质数计数采样课程 ──────────────────────────────────────────────────────
def sample_rate(step: int) -> float:
    s = int(step)
    if s < 2:
        return 1.0
    cnt = sum(1 for p in _PRIMES if p <= s)
    return cnt / s


def curriculum(total_steps: int) -> list:
    out = []
    for s in range(1, int(total_steps) + 1):
        out.append({"step": s, "sample_rate": round(sample_rate(s), 6),
                    "is_prime_step": anchor_ok(s)})
    return out


# ── 空间质数结构化理解能力 (L5 运行时用; 自助进化输入) ────────────────────────────
def understand(items, product: str = "", memory_path: str = MEMORY_J, domain: str = "cap",
               record: bool = True) -> dict:
    """给一组"当前出现"的原子结构, 算出质数签名, 与记忆库比对 ⇒ 已知/未见。

    未见结构 = 自主进化的输入: 记事件 (含时间/签名/来源/产品), 供流形引擎节点展示与后续固化决策。
    record=False 时只读不落盘 (干跑/自检用, 不污染记忆库)。
    """
    sig = signature(items, domain)
    prod = product or active_product()
    mem = {"seen": {}, "events": []}
    if os.path.isfile(memory_path):
        try:
            with io.open(memory_path, encoding="utf-8") as f:
                mem = json.load(f)
            mem.setdefault("seen", {})
            mem.setdefault("events", [])
        except Exception:                                                        # noqa: BLE001
            pass
    key = str(sig)
    known = key in mem["seen"]
    if not known:
        mem["seen"][key] = {"first_seen": time.strftime("%Y-%m-%d %H:%M:%S"), "product": prod,
                            "items": list(items), "hits": 0}
        mem["events"].append({"ts": time.time(), "sig": sig, "product": prod, "items": list(items)})
    mem["seen"][key]["hits"] = int(mem["seen"][key].get("hits", 0)) + 1
    if record:
        os.makedirs(os.path.dirname(memory_path), exist_ok=True)
        tmp = "%s.tmp.%d" % (memory_path, os.getpid())
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, memory_path)
    return {"signature": sig, "items": list(items), "product": prod, "known": known,
            "hits": mem["seen"][key]["hits"], "seen_structures": len(mem["seen"]),
            "novel_events": len(mem["events"]), "recorded": bool(record),
            "evolution_input": bool(not known)}


def sha256_short(path: str, k: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:k]


def report(product: str = "", iteration: int = 0) -> dict:
    prod = product or active_product()
    d = load_products()
    caps_l = caps(prod)
    out = {"active_product": prod, "product_name": (d["products"][prod].get("name")),
           "capabilities": caps_l, "cap_signature": signature(caps_l, "cap"),
           "domains": {"primitive": dict(PRIMITIVE_PRIMES), "stage": STAGE_PRIMES,
                       "product": PRODUCT_PRIMES, "iter_first": ITER_PRIMES[0]},
           "products": {k: {"name": v.get("name"), "cap_signature": signature(v["capabilities"], "cap"),
                            "iter_fingerprint": fingerprint(k, iteration or 1)["fingerprint"]}
                        for k, v in d["products"].items()}}
    # 协同关系: 能力集合包含 ⇒ 签名整除 (可测不变量)
    rel = {}
    for a in sorted(d["products"]):
        for b in sorted(d["products"]):
            if a >= b:
                continue
            sa, sb = out["products"][a]["cap_signature"], out["products"][b]["cap_signature"]
            rel["%s|%s" % (a, b)] = {"%s⊆%s" % (a, b): sb % sa == 0, "%s⊆%s" % (b, a): sa % sb == 0}
    out["capability_relation"] = rel
    return out


def _main(argv) -> int:
    cmd = argv[1] if len(argv) > 1 else "report"
    if cmd == "report":
        r = report(argv[2] if len(argv) > 2 else "", int(argv[3]) if len(argv) > 3 else 0)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    if cmd == "sign":
        print(signature(argv[3].split(","), argv[2]))
        return 0
    if cmd == "decompose":
        print(",".join(decompose(int(argv[2]), argv[3] if len(argv) > 3 else "cap")))
        return 0
    if cmd == "fingerprint":
        print(json.dumps(fingerprint(argv[2], int(argv[3]) if len(argv) > 3 else 1),
                         ensure_ascii=False, indent=1))
        return 0
    if cmd == "understand":
        print(json.dumps(understand(argv[2].split(",")), ensure_ascii=False, indent=1))
        return 0
    if cmd == "sparsity":
        print(json.dumps(anchor_sparsity(int(argv[2]) if len(argv) > 2 else 64), ensure_ascii=False))
        return 0
    if cmd == "symmetry":
        g = np.array(json.loads(argv[2])) if len(argv) > 2 else np.diag([10.0, 10.0, 50.0, 10.0, 10.0, 10.0])
        print(json.dumps(spectral_symmetry(g), ensure_ascii=False, indent=1))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
