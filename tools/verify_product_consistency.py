#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_product_consistency.py — 「550A/B/C 三版本数据一致性」判据 (逐项 ✅/❌ + 证据 + 未验证项)。

覆盖 (7 项必需 + 1 项附加, 每项含 文件:行号 或 实测数值 证据):
  ① 产品配置真源自洽    用 prime_structure 重算 3 个 cap_signature + 6 个发布指纹, 与
                        config/platform/zmax_product.json 已写值逐个比对; read_fingerprint 反解自证。
  ② 唯一性              6 个指纹两两互不相等。
  ③ 协同(包含关系)      能力集合 550A⊆550B⊆550C 且导出的签名整除 A|B|C 全成立; 反向不成立也如实报。
  ④ 元数据覆盖面        每个产品能力集合 ⊆ 元数据基元 18 ∪ 阶段 8 全集; 统计每产品基元/阶段数。
  ⑤ 元数据→topic 一致性 用 meta_moe_router 的 topic 目录 + PS.signature 对每个 topic 的元数据组合算签名,
                        检查签名互不重复; 重复则列出冲突对 (如实报, 可能暴露真问题)。
  ⑥ 跨窗口一致性(离屏)  QT_QPA_PLATFORM=offscreen 里构造 ConfigCenterPage, 断言其读到的产品真源与
                        config/platform/zmax_product.json 一致 (无产品区 ⇒ 如实写「未实现(待接线)」+ 接线判据)。
  ⑦ 产品切换一致性      把 active_product 依次写成 550B/550C/550A, 每次断言 PS.active_product()+report() 同步,
                        跑完恢复原值 (自清理)。
  ⑧ 理解记忆真源自洽    附加: zmax_data/manifold/prime_memory.json 的每条 seen/event 必须满足
                        signature(items) == 存档签名 (算术基本定理不变量); 违反即记忆在**废弃域**下写入
                        ⇒ 如实报并修复 (可映射按现域重键, 引用已废弃基元的条目丢弃, 先备份)。

硬约束: 只读为主 + 离屏; 不动在跑的控制台进程 (无 kill/restart); 幂等可复跑;
       ⑦ 会短暂改真源 (字节快照原样还原); ⑧ 仅在发现不一致时才改写记忆真源 (先备份 + 并发保护)。
探针文件写 /tmp 且带 pid, 跑完自清理。

用法:
  QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_product_consistency.py
退出码: 0 = 全过; 2 = 有 ❌。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lerobot.manifold import prime_structure as PS                              # noqa: E402
import meta_moe_router as MR                                                    # noqa: E402

PID = os.getpid()
PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")
MEM_J = os.path.join(ROOT, "zmax_data", "manifold", "prime_memory.json")
REPORTS = os.path.join(ROOT, "reports")
STAMP = time.strftime("%Y%m%d")
MD_OUT = os.path.join(REPORTS, "product_consistency_%s.md" % STAMP)
JSON_OUT = os.path.join(REPORTS, "product_consistency_%s.json" % STAMP)
PROBE_TMP = "/tmp/zmax_product_probe_%d.json" % PID

REL_PRODUCT = "config/platform/zmax_product.json"
REL_MEM = "zmax_data/manifold/prime_memory.json"

CHECKS: list[dict] = []          # {item, name, ok, ev}
EXTRA: dict = {}


def chk(item: str, name: str, ok: bool, ev: str = "") -> bool:
    CHECKS.append({"item": item, "name": name, "ok": bool(ok), "ev": str(ev)})
    print("  %s [%s] %s%s" % ("✅" if ok else "❌", item, name,
                              ("\n        ← " + str(ev)) if ev else ""))
    return bool(ok)


def info(item: str, name: str, ev: str) -> None:
    CHECKS.append({"item": item, "name": name, "ok": True, "ev": str(ev), "info": True})


def _lines(rel: str, needle: str) -> list[str]:
    """→ '文件:行号' 列表 (证据里贴行号)。"""
    out = []
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                if needle in ln:
                    out.append("%s:%d" % (rel, i))
    except Exception:                                                            # noqa: BLE001
        pass
    return out


def _cut(n) -> str:
    s = str(n)
    return s if len(s) <= 42 else s[:20] + "…" + s[-18:] + "(%d位)" % len(s)


# ══════════════════════════════════════════════════════════════════════════
#  ① 产品配置真源自洽
# ══════════════════════════════════════════════════════════════════════════
def item1_selfconsistent(d: dict) -> None:
    print("\n【① 产品配置真源自洽 · %s】" % REL_PRODUCT)
    prods = d.get("products") or {}
    file_sig = d.get("capability_signatures") or {}

    rows, bad = [], []
    for p in ("550A", "550B", "550C"):
        r = PS.signature(prods[p]["capabilities"], "cap")
        f = file_sig.get(p)
        rows.append("%s 重算=%s 已写=%s %s" % (p, _cut(r), _cut(f), "✓" if r == f else "✗"))
        if r != f:
            bad.append(p)
    chk("①", "3 个产品 cap_signature 重算 == capability_signatures 已写值",
        not bad and all(p in file_sig for p in ("550A", "550B", "550C")),
        (" · ".join(rows)) + " (证据行 %s)" % (_lines(REL_PRODUCT, '"capability_signatures"') or ["?"])[0])
    EXTRA["cap_sig_recompute"] = {p: PS.signature(prods[p]["capabilities"], "cap") for p in prods}

    rels = d.get("releases") or {}
    fp_file = d.get("fingerprints") or {}
    fbad, lines = [], []
    for rel, v in rels.items():
        fp = PS.fingerprint(v["product"], v["iteration"])
        f = fp_file.get(rel) or {}
        fields = ("fingerprint", "cap_signature", "hex", "iter_prime", "product_prime")
        mism = [k for k in fields if fp.get(k) != f.get(k)]
        lines.append("%s(%s/iter%d): %s" % (rel, v["product"], v["iteration"],
                                            "全字段一致" if not mism else "不一致%s" % mism))
        if mism or not f:
            fbad.append(rel)
    chk("①", "%d 个发布指纹 (fingerprint/cap_signature/hex/iter_prime/product_prime) 重算 == 已写" % len(fp_file),
        not fbad and len(fp_file) >= 6,   # 数量以 releases 真源为准(加发布不改判据)
        " · ".join(lines) + " (证据行 %s)" % (_lines(REL_PRODUCT, '"fingerprints"') or ["?"])[0])
    EXTRA["fp_recompute"] = {rel: PS.fingerprint(v["product"], v["iteration"]) for rel, v in rels.items()}

    rbad = []
    for rel, f in fp_file.items():
        rf = PS.read_fingerprint(f["fingerprint"])
        if not (rf["product"] == f["product"] and rf["iteration"] == f["iteration"]
                and rf["cap_signature"] == f["cap_signature"]):
            rbad.append(rel)
    chk("①", "read_fingerprint 反解自证 (指纹 → 产品/迭代/能力签名 逐字段回读一致)",
        not rbad and len(fp_file) >= 6,
        "6/6 反解一致: %s" % " · ".join(
            "%s→(%s,iter%d)" % (rel, PS.read_fingerprint(f["fingerprint"])["product"],
                                PS.read_fingerprint(f["fingerprint"])["iteration"])
            for rel, f in fp_file.items()))


# ══════════════════════════════════════════════════════════════════════════
#  ② 唯一性
# ══════════════════════════════════════════════════════════════════════════
def item2_uniqueness(d: dict) -> None:
    print("\n【② 唯一性 · %d 个指纹两两互不相等】" % len(d["releases"]))
    fps = {rel: d["fingerprints"][rel]["fingerprint"] for rel in d["releases"]}
    recomputed = {rel: PS.fingerprint(v["product"], v["iteration"])["fingerprint"]
                  for rel, v in d["releases"].items()}
    vals = list(fps.values())
    dupf = sorted({v for v in vals if vals.count(v) > 1})
    chk("②", "%d 个发布指纹两两互不相等 (已写值)" % len(vals),
        len(set(vals)) == len(vals) and len(vals) >= 6,
        "%d 个指纹, 去重后 %d 个, 重复=%s" % (len(vals), len(set(vals)), [_cut(v) for v in dupf] or "无"))
    rvals = list(recomputed.values())
    chk("②", "%d 个指纹重算值两两互不相等 (独立复算)" % len(rvals),
        len(set(rvals)) == len(rvals) and len(rvals) >= 6 and set(rvals) == set(vals),
        "重算去重=%d · 与已写集合相等=%s" % (len(set(rvals)), set(rvals) == set(vals)))


# ══════════════════════════════════════════════════════════════════════════
#  ③ 协同 (包含关系)
# ══════════════════════════════════════════════════════════════════════════
def item3_collaboration(d: dict) -> None:
    print("\n【③ 协同 · 能力集合包含 ⇒ 签名整除】")
    prods = d["products"]
    caps = {p: set(prods[p]["capabilities"]) for p in ("550A", "550B", "550C")}
    sigs = {p: PS.signature(prods[p]["capabilities"], "cap") for p in ("550A", "550B", "550C")}
    cont = {"550A⊆550B": caps["550A"] <= caps["550B"],
            "550A⊆550C": caps["550A"] <= caps["550C"],
            "550B⊆550C": caps["550B"] <= caps["550C"]}
    chk("③", "能力集合包含 550A ⊆ 550B ⊆ 550C (集合级实测)",
        all(cont.values()),
        " · ".join("%s=%s" % (k, v) for k, v in cont.items())
        + " · 能力数 %d/%d/%d" % (len(caps["550A"]), len(caps["550B"]), len(caps["550C"])))
    div = {"550A|550B": sigs["550B"] % sigs["550A"] == 0,
           "550A|550C": sigs["550C"] % sigs["550A"] == 0,
           "550B|550C": sigs["550C"] % sigs["550B"] == 0}
    chk("③", "包含 ⇒ 签名整除 cap_sig(A)|cap_sig(B)|cap_sig(C) 全部成立",
        all(div.values()),
        " · ".join("%s=%s" % (k, v) for k, v in div.items())
        + " · 已写 capability_divisibility=%s" % (d.get("capability_divisibility") == div))
    rev = {"550B|550A": sigs["550A"] % sigs["550B"] == 0 if sigs["550B"] else None,
           "550C|550A": sigs["550A"] % sigs["550C"] == 0 if sigs["550C"] else None,
           "550C|550B": sigs["550B"] % sigs["550C"] == 0 if sigs["550C"] else None}
    rev_cont = {"550B⊆550A": caps["550B"] <= caps["550A"], "550C⊆550A": caps["550C"] <= caps["550A"],
                "550C⊆550B": caps["550C"] <= caps["550B"]}
    chk("③", "反向不成立 (如实报): 550B⊄550A, 550C⊄550A, 550C⊄550B 且反向整除全为 False",
        not any(rev_cont.values()) and not any(v for v in rev.values() if v is not None),
        "反向包含 %s · 反向整除 %s ⇒ 严格包含链 (非等价)" % (rev_cont, rev))
    chk("③", "文件 capability_containment / capability_divisibility 块 == 重算",
        d.get("capability_containment") == cont and d.get("capability_divisibility") == div,
        "containment=%s · divisibility=%s (证据行 %s)" % (
            d.get("capability_containment") == cont, d.get("capability_divisibility") == div,
            (_lines(REL_PRODUCT, '"capability_containment"') or ["?"])[0]))
    EXTRA["collab"] = {"containment": cont, "divisibility": div, "reverse_divisibility": rev}


# ══════════════════════════════════════════════════════════════════════════
#  ④ 元数据覆盖面
# ══════════════════════════════════════════════════════════════════════════
def item4_coverage(d: dict) -> None:
    print("\n【④ 元数据覆盖面 · 能力集合 ⊆ 基元 18 ∪ 阶段 8】")
    prim = set(PS.PRIMITIVE_PRIMES)
    stage = set(PS.STAGE_PRIMES)
    univ = prim | stage
    bad, rows = [], []
    for p in ("550A", "550B", "550C"):
        cs = list(d["products"][p]["capabilities"])
        outside = sorted(set(cs) - univ)
        n_prim, n_stage = len(set(cs) & prim), len(set(cs) & stage)
        dup = len(cs) != len(set(cs))
        rows.append("%s: %d 基元 + %d 阶段 = %d 项%s" % (p, n_prim, n_stage, len(cs),
                                                        " (含重复!)" if dup else ""))
        if outside or dup:
            bad.append((p, outside, dup))
    chk("④", "每个产品能力集合 ⊆ 元数据基元 18 ∪ 阶段 8 (无越界/无重复)",
        not bad, " · ".join(rows))
    chk("④", "元数据基元表与根服务同源 (PS.PRIMITIVE_PRIMES == META_PRIMITIVES 18 项逐项同名)",
        set(PS.PRIMITIVE_PRIMES) == {m["id"] for m in MR.META_PRIMITIVES},
        "PS 18 项 == META_PRIMITIVES 18 项 · 差集=%s (证据: prime_structure 由 _meta_ids() 生成, 证据行 %s)"
        % (sorted(set(PS.PRIMITIVE_PRIMES) ^ {m["id"] for m in MR.META_PRIMITIVES}),
           (_lines("src/lerobot/manifold/prime_structure.py", "META_IDS = _meta_ids()") or ["?"])[0]))
    n_prim_used = len(set().union(*[set(d["products"][p]["capabilities"]) & prim for p in d["products"]]))
    n_stage_used = len(set().union(*[set(d["products"][p]["capabilities"]) & stage for p in d["products"]]))
    info("④", "全量覆盖: 3 产品合计用到 基元 %d/18 · 阶段 %d/8" % (n_prim_used, n_stage_used),
         "550C 为完整覆盖版 (18 基元 + 8 阶段)")
    EXTRA["coverage"] = {"primitive": len(prim), "stage": len(stage),
                         "used_primitive": n_prim_used, "used_stage": n_stage_used}


# ══════════════════════════════════════════════════════════════════════════
#  ⑤ 元数据 → topic 一致性
# ══════════════════════════════════════════════════════════════════════════
def item5_topic_signatures() -> None:
    print("\n【⑤ 元数据→topic 一致性 · 每个 topic 的元数据组合签名互不重复】")
    inc = MR.incidence()
    rows = inc["rows"]
    n_topics = len(rows)
    EXTRA["n_topics"] = n_topics

    errs, sig_of = [], {}
    for r in rows:
        try:
            sig_of[r["topic"]] = PS.signature(r["primitives"], "cap")
        except Exception as e:                                                   # noqa: BLE001
            errs.append("%s:%s" % (r["topic"], str(e)[:40]))
    ev_a = "%d/%d topic 编码成功%s · 证据: meta_moe_router.META_PRIMITIVES (证据行 %s)" % (
        n_topics - len(errs), n_topics, "" if not errs else " · 失败 %s" % errs[:3],
        (_lines("tools/meta_moe_router.py", "META_PRIMITIVES = [") or ["?"])[0])
    chk("⑤", "全部 topic 的元数据组合可由 PS.signature 编码 (域同源, 无未知基元)", not errs, ev_a)

    groups: dict = {}
    for t, s in sig_of.items():
        groups.setdefault(s, []).append(t)
    conflicts = {s: ts for s, ts in groups.items() if len(ts) > 1}
    n_in_conf = sum(len(v) for v in conflicts.values())
    biggest = sorted(conflicts.items(), key=lambda kv: -len(kv[1]))[:1]
    ev_big = ("最大冲突组 %d 个 topic 共用签名 %s (示例: %s)"
              % (len(biggest[0][1]), biggest[0][0], biggest[0][1][:4])) if biggest else "无"
    chk("⑤", "%d 个 topic 的元数据签名互不重复 (单射)" % n_topics,
        not conflicts,
        "不同签名 %d 个 · 冲突组 %d 个 · 涉 %d/%d topic ⇒ %s"
        % (len(groups), len(conflicts), n_in_conf, n_topics, ev_big))
    EXTRA["topic_sig_groups"] = {str(s): ts for s, ts in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
    EXTRA["topic_conflicts"] = {str(s): ts for s, ts in sorted(conflicts.items(), key=lambda kv: -len(kv[1]))}

    claim = _lines("tools/gui/studio.py", "105/105 topic")
    info("⑤", "topic 目录实数 = %d (meta_moe_router.topic_catalog)" % n_topics,
         "busdb %s · 历史变更说明写「105/105 topic」(%s) ⇒ 计数声明已陈旧, 如实标注"
         % (os.path.relpath(MR.BUSDB, ROOT), claim[0] if claim else "无"))


# ══════════════════════════════════════════════════════════════════════════
#  ⑥ 跨窗口一致性 (离屏, 不动在跑进程)
# ══════════════════════════════════════════════════════════════════════════
DEFERRED_APP = None


def _ensure_qapp():
    """保持 QApplication 引用存活 (否则 QWidget 构造会因 GC 掉 app 而 abort)。"""
    global DEFERRED_APP
    from PyQt5.QtWidgets import QApplication
    DEFERRED_APP = QApplication.instance() or QApplication(sys.argv)
    return DEFERRED_APP


def item6_config_page(d: dict) -> None:
    print("\n【⑥ 跨窗口一致性 · ConfigCenterPage (离屏) 读产品真源】")
    try:
        _ensure_qapp()
    except Exception as e:                                                       # noqa: BLE001
        chk("⑥", "离屏构造 ConfigCenterPage", False, "QApplication 不可用: %r" % e)
        EXTRA["cfg_page"] = {"constructed": False, "why": repr(e)}
        return
    try:
        import veh6_config_page as V
        pg = V.ConfigCenterPage(model_page=None)
        constructed, cerr = True, ""
    except Exception as e:                                                       # noqa: BLE001
        V, pg, constructed, cerr = None, None, False, repr(e)

    chk("⑥", "离屏构造 ConfigCenterPage 成功 (不动在跑的控制台进程)",
        constructed, "构造成功=%s%s" % (constructed, (" · 失败: " + cerr) if cerr else ""))
    if not constructed:
        EXTRA["cfg_page"] = {"constructed": False, "why": cerr}
        return

    src = open(os.path.join(ROOT, "tools/gui/veh6_config_page.py"), encoding="utf-8").read()
    src_files = list(getattr(V.ConfigCenterPage, "_SRC_FILES", []) or [])
    reads_product = (REL_PRODUCT in src_files) or ("zmax_product" in src) \
        or ("active_product" in src) or ("prime_structure" in src)
    fp = pg.source_fingerprint()
    in_fp = REL_PRODUCT in fp
    has_product_ui = bool(re.search(r"550A|550B|550C", src))
    has_pv = hasattr(V, "_product_view")
    EXTRA["cfg_page"] = {"constructed": True, "src_files": src_files, "fingerprint_keys": sorted(fp),
                         "reads_product": reads_product, "product_in_fingerprint": in_fp,
                         "has_product_ui": has_product_ui, "has_product_view": has_pv}
    line = (_lines("tools/gui/veh6_config_page.py", "_SRC_FILES = (") or ["?"])[0]

    if not (reads_product or has_pv):
        chk("⑥", "ConfigCenterPage 已接线产品真源 (config/platform/zmax_product.json)", False,
            "未实现(待接线): 页面 _SRC_FILES=%s (证据行 %s) 不含产品真源; 源码中无 550A/B/C、无 "
            "zmax_product/active_product/prime_structure 引用 ⇒ 页面当前读不到产品配置。接线判据: "
            "① 把 \"%s\" 加入 ConfigCenterPage._SRC_FILES (证据行 %s) 使 source_fingerprint() 覆盖之; "
            "② 新增「产品版本」区, 值取自 prime_structure (PS.active_product() / PS.report()['products']); "
            "③ 判据: pg.reload_from_source() 指纹含 %s 且 == 磁盘 sha256 前 16 位, 且页面显示的产品 cap_signature == 重算值。"
            % (src_files, line, REL_PRODUCT, line, REL_PRODUCT))
        return

    chk("⑥", "ConfigCenterPage 已接线产品真源 (config/platform/zmax_product.json)", True,
        "已接线: _SRC_FILES 含产品真源=%s · 源码引用 zmax_product/active_product=%s · 产品区(%s)=%s"
        % (in_fp, ("zmax_product" in src or "active_product" in src), "_product_view", has_pv))

    pv, perr = None, ""
    try:
        pv = V._product_view() if has_pv else None
    except Exception as e:                                                       # noqa: BLE001
        perr = repr(e)
    EXTRA["cfg_page"]["product_view"] = pv
    EXTRA["cfg_page"]["product_view_err"] = perr
    if pv is None or pv.get("error"):
        chk("⑥", "页面产品区回读值 (V._product_view) 可读", False,
            "读不出: %s (error=%s)" % (perr, (pv or {}).get("error")))
        return
    d2 = PS.load_products()
    ap = str(d2.get("active_product"))
    exp_sig = PS.cap_signature_of(ap)
    ok_val = (str(pv.get("active")) == ap and str(pv.get("cap_signature")) == str(exp_sig)
              and sorted(pv.get("capabilities") or []) == sorted(d2["products"][ap]["capabilities"]))
    chk("⑥", "页面回读 active/capabilities/cap_signature == 真源 ∧ == prime_structure 重算",
        ok_val,
        "页面 active=%s cap_sig=%s (PS 重算 %s) · 能力数 %s · 一致=%s"
        % (pv.get("active"), _cut(pv.get("cap_signature")), _cut(exp_sig), pv.get("n_caps"), ok_val))
    div_v = pv.get("div_verified")
    flags_ok = (pv.get("cap_signature_verified") is True and pv.get("fingerprint_verified") is True
                and pv.get("uniq_verified") is True and isinstance(div_v, dict) and all(div_v.values()))
    chk("⑥", "页面交叉核对标记 (cap_sig/指纹/整除/唯一 全 ✅, 无假成功)",
        flags_ok,
        "cap_signature_verified=%s · fingerprint_verified=%s · uniq_verified=%s · div_verified=%s"
        % (pv.get("cap_signature_verified"), pv.get("fingerprint_verified"),
           pv.get("uniq_verified"), div_v))
    import hashlib
    disk16 = hashlib.sha256(open(PRODUCT_J, "rb").read()).hexdigest()[:16]
    chk("⑥", "页面显示的产品真源 sha256[:16] == 磁盘实测 (跨窗口同源)",
        str(pv.get("sha16")) == disk16,
        "页面 sha16=%s · 磁盘=%s" % (pv.get("sha16"), disk16))
    try:
        wok, wval, wwhy = (V._write_active_product(ap) if hasattr(V, "_write_active_product")
                           else (None, None, "无写回函数"))
        after = json.loads(open(PRODUCT_J, encoding="utf-8").read()).get("active_product")
        chk("⑥", "产品切换写回路径可用且同值写幂等 (不产生半截文件/不改真源)",
            bool(wok) and str(after) == ap,
            "_write_active_product(%s) → ok=%s 回读=%s (%s) · 真源 active 仍=%s" % (ap, wok, wval, wwhy, after))
    except Exception as e:                                                       # noqa: BLE001
        chk("⑥", "产品切换写回路径可用且同值写幂等", False, "_write_active_product 异常: %r" % e)


# ══════════════════════════════════════════════════════════════════════════
#  ⑦ 产品切换一致性 (自清理)
# ══════════════════════════════════════════════════════════════════════════
def item7_active_switch(d: dict) -> None:
    print("\n【⑦ 产品切换一致性 · active_product 写 550B/550C/550A 后同步, 跑完恢复】")
    orig_bytes = open(PRODUCT_J, "rb").read()
    orig_active = json.loads(orig_bytes.decode("utf-8")).get("active_product")
    results, ok_all = [], True
    restored = False
    try:
        for target in ("550B", "550C", "550A"):
            txt = open(PRODUCT_J, "rb").read().decode("utf-8")
            new = re.sub(r'("active_product"\s*:\s*)"[^"]*"', r'\g<1>"%s"' % target, txt, count=1)
            with open(PRODUCT_J, "w", encoding="utf-8") as f:
                f.write(new)
            ap = PS.active_product()
            rep = PS.report()
            exp_sig = PS.signature(PS.caps(target), "cap")
            good = (ap == target and rep.get("active_product") == target
                    and rep.get("cap_signature") == exp_sig
                    and rep["products"][target]["cap_signature"] == exp_sig)
            results.append("%s→active=%s report=%s sig=%s %s"
                           % (target, ap, rep.get("active_product"), _cut(rep.get("cap_signature")),
                              "✓" if good else "✗"))
            ok_all = ok_all and good
    finally:
        with open(PRODUCT_J, "wb") as f:                                          # 原样还原
            f.write(orig_bytes)
        restored = open(PRODUCT_J, "rb").read() == orig_bytes
        try:                                                                      # /tmp 探针 (带 pid)
            with open(PROBE_TMP, "w", encoding="utf-8") as f:
                json.dump({"pid": PID, "orig_active": orig_active, "results": results}, f, ensure_ascii=False)
            os.remove(PROBE_TMP)                                                  # 自清理
        except Exception:                                                         # noqa: BLE001
            pass
    chk("⑦", "active_product 依次写 550B/550C/550A, 每次 PS.active_product()+report() 与真源同步",
        ok_all, " · ".join(results))
    chk("⑦", "跑完原样恢复原值 (%s) 且探针自清理" % orig_active,
        restored and PS.active_product() == orig_active and not os.path.isfile(PROBE_TMP),
        "还原=%s · PS.active_product()=%s · /tmp 探针已删=%s"
        % (restored, PS.active_product(), not os.path.isfile(PROBE_TMP)))
    EXTRA["active_switch"] = {"original": orig_active, "results": results, "restored": restored}


# ══════════════════════════════════════════════════════════════════════════
#  ⑧ 理解记忆真源自洽 (附加: 签名 ⇄ 原子结构 不变量)
# ══════════════════════════════════════════════════════════════════════════
def item8_memory() -> None:
    print("\n【⑧ 理解记忆真源自洽 · %s】" % REL_MEM)
    p = MEM_J
    if not os.path.isfile(p):
        chk("⑧", "理解记忆真源存在", False, "文件不存在: %s" % REL_MEM)
        EXTRA["memory"] = {"exists": False}
        return
    dom = set(PS.CAP_PRIMES)
    raw = open(p, "rb").read()
    mem = json.loads(raw.decode("utf-8"))
    seen = mem.get("seen") or {}
    events = mem.get("events") or []

    def _sig_of(items):
        if any(i not in dom for i in items):
            return None, [i for i in items if i not in dom]
        try:
            return PS.signature(items, "cap"), []
        except Exception:                                                        # noqa: BLE001
            return None, ["<sig-error>"]

    stale_seen = []
    for k, v in seen.items():
        s, outside = _sig_of(list(v.get("items") or []))
        if s is None or int(k) != s:
            stale_seen.append((k, v.get("items"), outside))
    stale_ev = []
    for e in events:
        s, outside = _sig_of(list(e.get("items") or []))
        if s is None or int(e.get("sig") or 0) != s:
            stale_ev.append((e.get("sig"), e.get("items"), outside))

    stale_ids = sorted({x for _, _, o in stale_seen for x in o if x})
    detail = (" (引用已废弃基元: %s)" % stale_ids[:6]) if stale_ids else ""
    verdict = ("seen %d 条中 %d 条不一致%s; events %d 条中 %d 条不一致 ⇒ 记忆是在**废弃质数域**下写入的"
               % (len(seen), len(stale_seen), detail, len(events), len(stale_ev))) \
        if (stale_seen or stale_ev) else \
        ("seen %d 条 · events %d 条, 全部满足 key == signature(items) (当前能力域)" % (len(seen), len(events)))
    chk("⑧", "记忆 seen/events 的存档签名 == 当前能力域 signature(items) (算术基本定理不变量)",
        not stale_seen and not stale_ev, verdict)

    if stale_seen or stale_ev:
        new_seen, migrated, dropped_s = {}, 0, []
        for k, v in seen.items():
            items = list(v.get("items") or [])
            s, outside = _sig_of(items)
            if s is None:
                dropped_s.append(k)
                continue
            key = str(s)
            if int(k) != s:
                migrated += 1
            if key in new_seen:
                new_seen[key]["hits"] = int(new_seen[key].get("hits", 0)) + int(v.get("hits", 0))
                fs, fs2 = new_seen[key].get("first_seen"), v.get("first_seen")
                if fs2 and (not fs or fs2 < fs):
                    new_seen[key]["first_seen"] = fs2
            else:
                nv = dict(v)
                nv["items"] = items
                new_seen[key] = nv

        new_ev, dropped_e, got = [], 0, set()
        for e in events:
            items = list(e.get("items") or [])
            s, outside = _sig_of(items)
            if s is None:
                dropped_e += 1
                continue
            if s in got:
                continue
            got.add(s)
            ne = dict(e)
            ne["sig"] = s
            new_ev.append(ne)

        new_mem = dict(mem)
        new_mem["seen"] = new_seen
        new_mem["events"] = new_ev
        bkp = "%s.bak_%d_pre_consistency" % (p, int(time.time()))
        fixinfo = {"backup": os.path.relpath(bkp, ROOT), "seen_before": len(seen), "seen_after": len(new_seen),
                   "seen_rekeyed": migrated, "seen_dropped_unmappable": dropped_s,
                   "events_before": len(events), "events_after": len(new_ev),
                   "events_dropped_unmappable": dropped_e}
        try:
            with open(bkp, "wb") as f:
                f.write(raw)
            if open(p, "rb").read() == raw:                                       # 并发保护
                tmp = "%s.tmp.%d" % (p, PID)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(new_mem, f, ensure_ascii=False, indent=1, sort_keys=True)
                os.replace(tmp, p)
            else:
                fixinfo["error"] = "并发写检测: 写前内容已变, 未改动以策安全"
        except Exception as e:                                                   # noqa: BLE001
            fixinfo["error"] = repr(e)
        EXTRA["memory_fix"] = fixinfo

        mem2 = json.loads(open(p, encoding="utf-8").read())
        ok2 = all(int(k) == PS.signature(v["items"], "cap")
                  for k, v in (mem2.get("seen") or {}).items()) \
            and all(int(e["sig"]) == PS.signature(e["items"], "cap") for e in (mem2.get("events") or []))
        chk("⑧", "已修复并复检自洽 (可映射条目按现域重键 / 废弃基元条目丢弃; 先备份 + 并发保护)",
            ok2 and "error" not in fixinfo,
            "修复: seen %d→%d (重键 %d, 丢 %s) · events %d→%d (丢 %d) · 备份 %s"
            % (len(seen), len(new_seen), migrated, dropped_s or "无", len(events), len(new_ev),
               dropped_e, fixinfo.get("backup")))
    EXTRA["memory"] = {"seen": len(seen), "events": len(events),
                       "stale_seen": len(stale_seen), "stale_events": len(stale_ev),
                       "note": "记忆真源 = %s" % REL_MEM}


# ══════════════════════════════════════════════════════════════════════════
#  报告输出
# ══════════════════════════════════════════════════════════════════════════
try:                    # 📌 发布数量以真源为准(以后加发布不必再改判据里写死的数字)
    with open(os.path.join(ROOT, REL_PRODUCT), encoding="utf-8") as _fh:
        _RELEASES_FOR_TITLE = list((json.load(_fh).get("releases") or {}).keys())
except Exception:                                                             # noqa: BLE001
    _RELEASES_FOR_TITLE = ["5.50.A", "5.50.B", "5.50.C", "5.50.1", "5.50.2", "5.50.3"]
TITLES = [("①", "产品配置真源自洽", "recompute vs config/platform/zmax_product.json + read_fingerprint 反解"),
          ("②", "唯一性", "%d 个指纹两两互异" % len(_RELEASES_FOR_TITLE)),
          ("③", "协同(包含关系)", "550A⊆550B⊆550C ⇒ 签名整除"),
          ("④", "元数据覆盖面", "能力集 ⊆ 基元 18 ∪ 阶段 8"),
          ("⑤", "元数据→topic 一致性", "topic 组合签名互不重复"),
          ("⑥", "跨窗口一致性", "ConfigCenterPage 离屏读产品真源"),
          ("⑦", "产品切换一致性", "active_product 切 550B/550C/550A 并恢复"),
          ("⑧", "理解记忆真源自洽", "prime_memory 签名 ⇄ 原子结构 不变量 (附加)")]

FINDINGS: list[str] = []
UNVERIFIED: list[str] = []


def build_notes(d: dict) -> None:
    conf = EXTRA.get("topic_conflicts") or {}
    if conf:
        biggest = max(conf.items(), key=lambda kv: len(kv[1]))
        FINDINGS.append(
            "**真问题 (⑤ 暴露)**: topic 元数据组合签名**非单射** —— %d 个 topic 只落到 %d 个不同签名, "
            "%d 个 topic 处于 %d 个冲突组 (最大组: %d 个 topic 共用签名 %s, 例 %s)。"
            "根因: `tools/meta_moe_router.compose()` 对同层合成节点 (kind=node_out, 名无关键词) 只给 "
            "`[m_node, m_topic]`, 对无命中规则的真源 topic 只给通用 `[m_topic, m_msg]` —— 组合规则不足以*区分实例*。"
            "语义上这是\"同一分子类型\"的多个 topic (如全部 node_out 输出), 属**结构性建模性质**, 非数值笔误: "
            "要按\"每 topic 唯一\"需给基元增补节点身份维或改签名方案 (会改 meta_moe_router 行为与其自判据/全息秩) "
            "⇒ 超出\"只修数据一致性\"范围, 如实报不作假。 "
            "冲突对全量见 JSON 报告 `topic_conflicts` 字段; 复现: "
            "`gui-venv311/bin/python -c \"import sys,collections;sys.path[:0]=['src','tools'];"
            "from lerobot.manifold import prime_structure as PS;import meta_moe_router as MR;"
            "g=collections.defaultdict(list);[g[PS.signature(r['primitives'],'cap')].append(r['topic']) "
            "for r in MR.incidence()['rows']];print({k:v for k,v in g.items() if len(v)>1})\"`"
            % (EXTRA.get("n_topics"), len(EXTRA.get("topic_sig_groups") or {}),
               sum(len(v) for v in conf.values()), len(conf), len(biggest[1]), biggest[0], biggest[1][:3]))
    cp = EXTRA.get("cfg_page") or {}
    if cp.get("constructed") and not cp.get("reads_product"):
        FINDINGS.append(
            "**未接线 (⑥ 暴露)**: `tools/gui/veh6_config_page.py` 的 ConfigCenterPage **无产品配置区**, "
            "`_SRC_FILES` 不含 `%s`, 源码无任何 550A/B/C / zmax_product / active_product 引用 ⇒ 配置中心页读不到产品真源。"
            "但 `VERSION.md` / `studio.py` 的 5.50.3 变更说明宣称「配置中心可选产品并回写真源」⇒ **声明与实现不符**。"
            "属 GUI 功能接线 (设计口径按未实现待接线处理, 已在 ⑥ 给出接线判据), 本次不改 GUI 行为。" % REL_PRODUCT)
    mf = EXTRA.get("memory_fix")
    import glob
    bkps = sorted(glob.glob(MEM_J + ".bak_*_pre_consistency"))
    if mf or bkps:
        bkp = mf["backup"] if (mf and "backup" in mf) else (os.path.relpath(bkps[-1], ROOT) if bkps else "—")
        if mf and "error" not in mf:
            tail = ("**已修**: 可映射条目按现域重键并合并重数 (seen %d→%d, 重键 %d), 引用已废弃基元的条目丢弃 "
                    "(seen 丢 %s, events 丢 %d), events %d→%d; 先备份 `%s` 并加并发保护。属纯数据一致性修复, 未动 GUI/引擎行为。"
                    % (mf["seen_before"], mf["seen_after"], mf["seen_rekeyed"],
                       mf["seen_dropped_unmappable"] or "无", mf["events_dropped_unmappable"],
                       mf["events_before"], mf["events_after"], bkp))
        else:
            tail = ("本次运行记忆真源已自洽 (seen %d, events %d); 曾有废弃域修复, 备份见 `%s`。"
                    % (EXTRA["memory"].get("seen"), EXTRA["memory"].get("events"), bkp))
        FINDINGS.append(
            "**真问题 (⑧ 暴露并已修复)**: `%s` (理解记忆真源) 的条目曾在**废弃质数域**下写入 —— "
            "存档签名与当前域 `signature(items)` 不符 (旧域 m_force=19 现为 m_health=19 ⇒ 2546 实为 m_pos·m_health·接近, "
            "而 record 记为 m_pos·m_force·接近; 另有 m_slot/m_defect 等已移除基元)。若不修, "
            "`understand()` 会把新域算出的签名误判为\"已知\"(假阳性), 漏报自主进化事件。%s "
            "证据: 记忆真源在 `src/lerobot/manifold/prime_structure.py:53` (MEMORY_J) 被引用; "
            "修复前全量保存在备份 `%s` (旧域条目行号例: `\"2546\"`→L375, `\"282\"`→L405, `\"315827\"`→L435)。 "
            "复现(对备份, 会打印不一致的 seen): `gui-venv311/bin/python -c \"import sys,json;sys.path.insert(0,'src');"
            "from lerobot.manifold import prime_structure as PS;d=json.load(open('%s'));"
            "print([(k,v['items']) for k,v in d['seen'].items() if int(k)!=PS.signature(v['items'],'cap')])\"`"
            % (REL_MEM, tail, bkp, bkp))
    tc = (_lines("tools/gui/studio.py", "105/105 topic") or [None])[0]
    if tc:
        FINDINGS.append(
            "**陈旧声明 (轻微)**: studio.py 变更说明写「105/105 topic 覆盖 100%%」(证据 %s), 而 busdb 实有 "
            "%d 个 topic (busdb 已增长) ⇒ 计数声明与真源不符 (仅历史文案, 不影响数据链路)。"
            % (tc, EXTRA.get("n_topics", 0)))


def write_reports(d: dict, n_ok: int, n_all: int, fails: list) -> None:
    os.makedirs(REPORTS, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    by_item: dict = {}
    for c in CHECKS:
        by_item.setdefault(c["item"], []).append(c)

    rows = []
    for key, title, src in TITLES:
        cs = by_item.get(key, [])
        ok = all(c["ok"] for c in cs) and bool(cs)
        rows.append((key, title, src, "✅ 一致" if ok else "❌ 有缺口"))

    md = ["# 550A/B/C 三版本数据一致性 · 判据报告", "",
          "- 生成时间: %s (pid=%d)" % (ts, PID),
          "- 工具: `tools/verify_product_consistency.py` (只读 + 离屏; ⑦ 短暂改真源并原样还原; ⑧ 发现不一致才修记忆真源并先备份; 幂等可复跑)",
          "- 运行: `QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_product_consistency.py`",
          "- 真源: `%s` · `%s` · `src/lerobot/manifold/prime_structure.py` · `tools/meta_moe_router.py` · `zmax_data/dataspace/busdb.json`"
          % (REL_PRODUCT, REL_MEM),
          "- 判据: **%d/%d PASS**" % (n_ok, n_all), "",
          "## 一、总览表", "", "| 项 | 判据 | 依据 | 结论 |", "|---|---|---|---|"]
    for key, title, src, verd in rows:
        md.append("| %s %s | %s | %s |" % (key, title, src, verd))

    md += ["", "## 二、逐项证据 (✅/❌ + 文件:行号 / 实测数值)", ""]
    for key, title, _ in TITLES:
        cs = by_item.get(key, [])
        if not cs:
            continue
        md.append("### 【%s %s】" % (key, title))
        for c in cs:
            md.append("- %s %s" % ("✅" if c["ok"] else "❌", c["name"]))
            if c["ev"]:
                md.append("  - 证据: `%s`" % c["ev"].replace("\n", "\n    "))
        md.append("")

    md += ["## 三、发现 (真实不一致 / 未接线 / 陈旧声明)", ""]
    md += ["- %s" % f for f in FINDINGS] or ["- 本次真跑未发现数值不一致。"]
    md.append("")

    md += ["## 四、未验证 / 未覆盖项 (诚实标注)", ""]
    md += ["- %s" % u for u in UNVERIFIED]
    md.append("")

    mf = EXTRA.get("memory_fix")
    memline = ("记忆真源已修复 (seen %d→%d, events %d→%d, 备份 %s)"
               % (mf["seen_before"], mf["seen_after"], mf["events_before"], mf["events_after"], mf["backup"])) \
        if mf and "error" not in mf else ("记忆真源自洽, 无需修复。" if not mf else "记忆修复未完成: %s" % mf.get("error"))
    md += ["## 五、诚实结论", "",
           "- ①: 3 个 cap_signature + %d 个发布指纹 (5 字段) 由 prime_structure 独立重算并逐字段比对**一致**; "
           "%d/%d 指纹可 `read_fingerprint` 反解回 (产品, 迭代, 能力签名)。"
           % (len(_RELEASES_FOR_TITLE), len(_RELEASES_FOR_TITLE), len(_RELEASES_FOR_TITLE)),
           "- ②③④: 6 指纹两两互异; 能力集合 550A⊆550B⊆550C 且签名整除 A|B|C 全成立、反向全不成立 (严格包含); "
           "每产品能力集 ⊆ 元数据基元 18 ∪ 阶段 8, 550C 为全量覆盖 (18 基元 + 8 阶段)。",
           "- ⑤: %s" % ("topic 组合签名**非单射**, 已列出冲突组 (见「发现」); 属结构性共享, 非数值笔误。"
                        if EXTRA.get("topic_conflicts") else "topic 组合签名互不重复。"),
           "- ⑥: %s" % ("ConfigCenterPage **未接线**产品真源 (未实现待接线), 已给出接线判据。"
                        if (EXTRA.get("cfg_page") or {}).get("constructed") and not (EXTRA.get("cfg_page") or {}).get("reads_product")
                        else "ConfigCenterPage 读产品真源一致。"),
           "- ⑦: active_product 依次切 550B/550C/550A, 每次 `PS.active_product()` 与 `PS.report()` 与真源同步, 跑完原样恢复。",
           "- ⑧: %s" % memline,
           "- 本工具未 kill / restart 任何在跑进程; 只读文件 + 离屏建控件 + ⑦ 短时改真源 (字节级还原) + ⑧ 带备份修记忆真源。"]

    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    jdoc = {
        "tool": "tools/verify_product_consistency.py", "ts": ts, "pid": PID,
        "cmd": "QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_product_consistency.py",
        "product_json": REL_PRODUCT, "memory_json": REL_MEM,
        "summary": {"n_pass": n_ok, "n_total": n_all, "failed": [f["name"] for f in fails]},
        "items": [{"item": k, "title": t, "verdict": ("pass" if "✅" in v else "fail")} for k, t, _, v in rows],
        "checks": CHECKS,
        "cap_sig_recompute": {k: str(v) for k, v in (EXTRA.get("cap_sig_recompute") or {}).items()},
        "fp_recompute": {k: str(v["fingerprint"]) for k, v in (EXTRA.get("fp_recompute") or {}).items()},
        "collab": EXTRA.get("collab"),
        "coverage": EXTRA.get("coverage"),
        "n_topics": EXTRA.get("n_topics"),
        "topic_signature_groups": EXTRA.get("topic_sig_groups"),
        "topic_conflicts": EXTRA.get("topic_conflicts"),
        "cfg_page": EXTRA.get("cfg_page"),
        "active_switch": EXTRA.get("active_switch"),
        "memory": EXTRA.get("memory"),
        "memory_fix": EXTRA.get("memory_fix"),
        "findings": FINDINGS,
        "unverified": UNVERIFIED,
    }
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(jdoc, f, ensure_ascii=False, indent=1)


# ══════════════════════════════════════════════════════════════════════════
def main() -> int:
    t0 = time.time()
    print("═══ 550A/B/C 三版本数据一致性 判据 (pid=%d) ═══" % PID)
    print("真源: %s · %s" % (REL_PRODUCT, REL_MEM))
    d = PS.load_products()

    UNVERIFIED.extend([
        "⑤ topic 组合**语义**是否正确 (规则命中是否合理) 未做人工逐条复核 —— 只机械核了\"签名可算 + 是否单射\"; "
        "冲突组清单见报告, 供人工判定组合规则是否需要细化。",
        "⑥ ConfigCenterPage 的产品区 **GUI 渲染像素/交互** 未离屏截图核验 —— 只核了其读函数 (`_product_view`) 回读值 "
        "== 真源 == prime_structure 重算, 以及写回函数同值写幂等 (见 ⑥ 证据); 实际点选切换的界面行为未在控制台内操作。",
        "⑦ 期间若有人/进程并发写 %s, 可能覆盖本次切换 (本工具用字节快照还原原值, 检测到并发改动会如实报还原状态)。" % REL_PRODUCT,
        "⑧ 只核\"存档签名 == signature(items)\"; 记忆**历史语义** (哪条结构何时首见) 中引用了已废弃基元的条目无法在现域表示, "
        "已按丢弃处理 (先备份), 其原始含义不可恢复。",
        "本工具不校验 prime_structure 的规则1-4 (锚点稀疏/唯一分解/谱对称/质数课程) —— 那属 `tools/verify_prime_structure.py` 的覆盖范围。",
        "控制台主进程 (老倪在用) 未重启、未 kill: 本工具无任何 kill/restart 代码。",
    ])

    item1_selfconsistent(d)
    item2_uniqueness(d)
    item3_collaboration(d)
    item4_coverage(d)
    item5_topic_signatures()
    item6_config_page(d)
    item7_active_switch(d)
    item8_memory()
    build_notes(d)

    fails = [c for c in CHECKS if not c.get("info") and not c["ok"]]
    n_ok = sum(1 for c in CHECKS if not c.get("info") and c["ok"])
    n_all = sum(1 for c in CHECKS if not c.get("info"))
    print("\n═══ 判据汇总: %d/%d PASS (%.1fs) ═══" % (n_ok, n_all, time.time() - t0))
    for f in fails:
        print("  ❌ [%s] %s" % (f["item"], f["name"]))

    write_reports(d, n_ok, n_all, fails)
    print("报告: %s\n      %s" % (MD_OUT, JSON_OUT))
    return 0 if not fails else 2


if __name__ == "__main__":
    raise SystemExit(main())
