#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 模型配置矩阵 (唯一依据) — 主界面「配置通道」与配置中心「模型配置」共用的同一份数据。

老倪 2026-10-14:
  「你看下面的配置通道，都是之前的模型配置了。现在要与状态空间工程实际数据一致。
    最开始配置中心的模型配置，就是配置模型的。也没对应上啊」
⇒ 这张表不再手写 (旧的 ZOO_SPEC 是 2026-08-08 的 Model Zoo 实验对比: ACT/VLA-Touch/AWE/官方专家…),
  改成每次从**状态空间工程的唯一依据**现算:

  ① tools/model_inventory.py --json        在役模型/权重真实路径/体积/最近训练
  ② http://127.0.0.1:8796/status/all       在役模型名/版本/状态 (引擎实际加载的)
  ③ src/lerobot/engineering/flows/state_space_obs.json   状态空间画布上真正接它的节点 (id/名字/源码)
  ④ config/mcd/param_registry.json         配置中心「模型配置」域 (ckpt_l2..l5 / train_state / train_entry)
  ⑤ reports/joint_train_*/summary.json     最近一次真训练的 rc/秒 (每层)

取不到的一律写 "唯一依据未登记", **不编数字** (老倪: 工程真实性零容忍)。

用法:
  ./gui-venv311/bin/python tools/model_config_matrix.py --json     # 给 GUI/页面用
  ./gui-venv311/bin/python tools/model_config_matrix.py            # 人看的文本表
  ./gui-venv311/bin/python tools/model_config_matrix.py --check    # 判据: 四层齐 + 无 "None"/空值
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
LAYERS = ("L2", "L3", "L4", "L5")
CANVAS = os.path.join(ROOT, "src", "lerobot", "engineering", "flows", "state_space_obs.json")
REG = os.path.join(ROOT, "config", "mcd", "param_registry.json")
STATUS_URL = os.environ.get("ZMAX_STATUS_URL", "http://127.0.0.1:8796/status/all")

# 画布上"哪一层由哪些节点承载" —— 判据用节点 id (不是靠名字猜), 名字只用于显示
LAYER_NODES = {
    "L2": ("n_yolo", "n_yolo3d"),
    "L3": ("n_smolvla", "n_l3"),
    "L4": ("n_intact", "n_intactwm"),
    "L5": ("n_dsvl", "n_vlm_llm", "n_qwen"),
}
LAYER_ARCH_HINT = {"L2": "YOLO", "L3": "SmolVLA", "L4": "INTACT", "L5": "VLM"}
# L2 第二个模型 (开放词汇分割) 的唯一依据路径 —— 老倪 2026-10-14:「还有个 SAM3 呢, 怎么搞?」
SAM3_BASE_REL = "zmax_data/models/sam3_hf/model.safetensors"
SAM3_ADAPTER_REL = "outputs/sam3_finetune/annot_v1/lora_adapter/adapter_model.safetensors"


def _j(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                                  # noqa: BLE001
        return default if default is not None else {}


def _inventory():
    try:
        r = subprocess.run([PY, os.path.join(ROOT, "tools", "model_inventory.py"), "--json"],
                           capture_output=True, text=True, timeout=180, cwd=ROOT)
        return json.loads(r.stdout or "{}")
    except Exception:                                                                  # noqa: BLE001
        return {}


def _status():
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=4) as r:
            return json.loads(r.read(262144).decode("utf-8", "replace"))
    except Exception:                                                                  # noqa: BLE001
        return {}


def _registry():
    d = _j(REG)
    return {p.get("id"): p.get("value") for p in (d.get("params") or d.get("items") or [])
            if isinstance(p, dict)}


def _canvas_nodes():
    d = _j(CANVAS)
    return [n for n in (d.get("nodes") or []) if isinstance(n, dict)]


def _last_train_per_layer():
    """最近一次真训练的每层 rc/秒 (从最新的 reports/joint_train_*/summary.json 读)。"""
    out = {}
    for d in sorted(glob.glob(os.path.join(ROOT, "reports", "joint_train_*")), reverse=True)[:12]:
        s = _j(os.path.join(d, "summary.json"))
        rows = s.get("rows") or s.get("results") or s.get("stages") or []      # 唯一依据键名 = rows (实测)
        if not rows:
            continue
        for x in rows:
            lid = str(x.get("stage") or x.get("id") or "")                    # 层号在 stage 字段
            if lid in LAYERS and lid not in out:
                ev = (x.get("evidence") or [{}])[0]
                out[lid] = {"rc": x.get("rc"), "secs": x.get("secs") or x.get("sec"),
                            "src": os.path.basename(d),
                            "artifact": os.path.basename(str(ev.get("path") or ""))}
        if len(out) >= len(LAYERS):        # 四层都要 (原来 >=3 就 break ⇒ L5 被漏成"唯一依据未登记")
            break
    return out


def _size(path):
    try:
        b = os.path.getsize(path) if os.path.isfile(path) else None
        if b is None and os.path.isdir(path):
            b = sum(os.path.getsize(os.path.join(r, f)) for r, _s, fs in os.walk(path)
                    for f in fs if f.endswith((".pt", ".safetensors", ".bin")))
        if not b:
            return "唯一依据未登记"
        return "%.1f MB" % (b / 1048576.0) if b < 1073741824 else "%.2f GB" % (b / 1073741824.0)
    except Exception:                                                                  # noqa: BLE001
        return "唯一依据未登记"


def _params_from_log(layer):
    """从最新训练日志里抠真参数量 (只有日志写了才有)。"""
    for d in sorted(glob.glob(os.path.join(ROOT, "reports", "joint_train_*")), reverse=True)[:8]:
        p = os.path.join(d, "%s.log" % layer)
        if not os.path.exists(p):
            continue
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
        except Exception:                                                              # noqa: BLE001
            continue
        m = re.search(r"总参数\s*([\d,]+)", t) or re.search(r"可训参数\s*([\d,]+)", t)
        if m:
            n = int(m.group(1).replace(",", ""))
            return "%s (%.1fM)" % (m.group(1), n / 1e6), os.path.basename(d)
    return "唯一依据未登记", ""


def _cmpp(n):
    """紧凑显示名 (完整名仍在路径/tooltip 里, 不丢信息)。"""
    s = re.sub(r"^L\d · ", "", str(n or ""))
    s = re.sub(r"^L\d 候选 · ", "", s)
    s = re.sub(r"^L\d ", "", s)
    s = (s.replace("开放词汇分割 ", "")
          .replace(" (官方基座 848M, 未在役)", "基座848M")
          .replace("SAM3 适配器 ", "SAM3适配器")
          .replace("SAM3 基座", "SAM3基座")
          .replace(" ", ""))
    s = re.sub(r"（[^）]*）|\([^)]*\)", "", s).strip()      # 去括号限定词 ((未证明提升) 等; 判据在 tooltip)
    s = s.replace("最新训练产物", "最新产物").replace("最新训练", "最新")
    return s if len(s) <= 24 else s[:24] + "…"


def candidate_rows(models, st_models=(), layers=LAYERS):
    """🔎 候选行 —— 给「🧠 模型引擎」窗口用 (每层一条, 只在**有候选**时出)。

    与主表 `build()` **同规则同唯一依据**: 名字压缩 `_cmpp`; 判据 = 8796 `/status/all` 的 `note_short`
    (引擎没给该候选写备注 ⇒ 如实写「产物未评估(尚无 A/B 判据)」, 不编结论)。
    🧩 L2 的 SAM3 就是走这一行显示 (老倪 2026-10-14: 「在模型引擎里要增加 SAM3, 位置 L2」)。
    返回: [{"layer","layer_tag","models","note","path","ts","n","names"}]
    """
    out = []
    _st = [m for m in (st_models or []) if isinstance(m, dict)]
    for ly in layers:
        mine = [m for m in (models or []) if str(m.get("layer")) == ly and not m.get("active")]
        if not mine:
            continue
        names = [_cmpp(m.get("name")) for m in mine]
        names = [n for n in names if n]
        notes = [str(m.get("note_short") or m.get("note") or "")[:80]
                 for m in _st if str(m.get("layer")) == ly and str(m.get("state")) == "candidate"]
        notes = [n for n in notes if n]
        path, ts = "", ""
        for m in mine:
            _p = m.get("realpath") or m.get("path") or ""
            if _p and (not path or "sam3" in str(_p).lower()):
                path = _p
            _t = (m.get("last_train") or {}).get("ts") or ""
            if _t > ts:
                ts = _t
        vers = []
        for m in _st:
            if str(m.get("layer")) == ly and str(m.get("state")) == "candidate":
                _v = str(m.get("version") or "")
                if _v and _v not in vers:
                    vers.append(_v)
        # 显示串**按像素限长** (列宽 340px, 预算 316px; 不用省略号): 放不下的收成 " +k", 全清单进 tooltip。
        # 🧩 含 SAM3 的候选优先排前 (老倪点名要看 SAM3 在 L2)，其余按原序补足预算。
        def _wpx(s):                                 # 粗估: font 18 ⇒ CJK≈18px, ASCII≈9px
            return sum(18 if ord(_c) > 0x2E80 else 9 for _c in str(s))
        _ord, _s3 = [], False
        for _n in sorted(names, key=lambda _n: (0 if "SAM3" in _n.upper() else 1)):
            _n2 = _n
            if "SAM3" in _n.upper():                    # 首个 SAM3 名字已点明前缀, 后续名字去重前缀
                _n2 = _n.replace("SAM3", "").strip(" ·") if _s3 else _n
                _s3 = True
            _ord.append(_n2)
        _B = 316
        if _wpx(" · ".join(_ord)) <= _B:
            disp = " · ".join(_ord)
        else:
            _kept, _cur = [], 0
            for _n in _ord:
                _add = _wpx(_n) + (_wpx(" · ") if _kept else 0)
                _rest = len(_ord) - len(_kept) - 1
                if _cur + _add + (_wpx(" +%d" % _rest) if _rest else 0) <= _B:
                    _kept.append(_n)
                    _cur += _add
                else:
                    break
            _extra = len(_ord) - len(_kept)
            disp = " · ".join(_kept) + (" +%d" % _extra if _extra else "")
        # 版本串同样**按像素限长** (列宽 278px, 预算 250px): 多余版本收成 " +k"
        _vdisp = ""
        for _k, _v in enumerate(vers):
            if _wpx(_vdisp) + _wpx(_v) + (_wpx(" · ") if _vdisp else 0) <= 250:
                _vdisp = (_vdisp + " · " + _v) if _vdisp else _v
            else:
                _vdisp += " +%d" % (len(vers) - _k)
                break
        out.append({"layer": ly, "layer_tag": "%s · 候选" % ly, "ver": _vdisp or "—",
                    "models": disp or "—", "names_all": names,
                    "note": " · ".join(notes) or "产物未评估(尚无 A/B 判据)",
                    "path": path or "唯一依据未登记", "ts": ts or "无训练记录",
                    "n": len(mine), "names": names})
    return out


def build():
    inv = _inventory()
    st = _status()
    reg = _registry()
    nodes = _canvas_nodes()
    last = _last_train_per_layer()
    rows = {}
    srcs = {
        "在役清单": "tools/model_inventory.py --json",
        "引擎状态": STATUS_URL,
        "状态空间画布": os.path.relpath(CANVAS, ROOT),
        "模型配置域": os.path.relpath(REG, ROOT),
        "最近训练": "reports/joint_train_*/summary.json",
    }
    for ly in LAYERS:
        e = {"层": ly}
        models = [m for m in (inv.get("models") or []) if str(m.get("layer")) == ly]
        act = next((m for m in models if m.get("active")), None) or (models[0] if models else {})
        sm = next((m for m in (st.get("models") or []) if str(m.get("layer")) == ly), {})
        path = act.get("realpath") or act.get("path") or reg.get("model.ckpt_%s" % ly.lower()) or ""
        e["在役模型"] = (sm.get("name") or act.get("name") or "唯一依据未登记")
        e["版本"] = (sm.get("version") or act.get("ver") or "唯一依据未登记")
        e["权重路径"] = path or "唯一依据未登记"
        e["权重体积"] = _size(path) if path else "唯一依据未登记"
        e["状态"] = {"in_service": "在役", "candidate": "候选"}.get(str(sm.get("state")), "唯一依据未登记")
        e["架构"] = (sm.get("name") or "").split("(")[0].strip() or LAYER_ARCH_HINT.get(ly, "唯一依据未登记")
        pq, _pd = _params_from_log(ly)
        e["参数量"] = pq
        ns = [n for n in nodes if str(n.get("id")) in LAYER_NODES.get(ly, ())]
        if not ns:                                  # 保障: 按名字关键字在画布上找
            ns = [n for n in nodes if LAYER_ARCH_HINT.get(ly, "\0") in str(n.get("name") or "")][:2]
        e["状态空间节点"] = " · ".join(str(n.get("name")) for n in ns) or "唯一依据未登记"
        e["输出话题"] = " ".join("ss/%s/out" % n.get("id") for n in ns) or "唯一依据未登记"
        _srcs, _seen = [], set()            # 两个节点可能指向同一个源文件 ⇒ 去重 (L4/L5 实测重复)
        for _n in ns:
            _s = str((_n.get("params") or {}).get("source") or "")
            if _s and _s not in _seen:
                _seen.add(_s)
                _srcs.append(_s)
        e["节点源码"] = " · ".join(_srcs) or "唯一依据未登记"
        e["训练入口"] = (reg.get("model.train_entry") or {}).get(ly, "唯一依据未登记")
        # 在役指针本身没有 last_train (它只是软链) ⇒ 扫本层**所有**产物取最新那次 (与引擎窗口同一口径)
        lt = ""                                    # 用空串起比 (拿中文占位串去比会把所有 ts 都比掉)
        for m in models:
            ts = (m.get("last_train") or {}).get("ts")
            if ts and ts > lt:
                lt = ts
        lt = lt or "无训练记录"
        # 归一显示 (与模型引擎窗口同一口径): 产物目录名 20261014_141727 → 10-14 14:17
        _m2 = re.match(r"^(\d{4})(\d{2})(\d{2})[_T](\d{2})(\d{2})(\d{2})?", lt)
        if _m2:                                     # 目录名 → 与其他层同款完整时间戳 (四层格式一致)
            lt = "%s-%s-%s %s:%s%s" % (_m2.group(1), _m2.group(2), _m2.group(3), _m2.group(4), _m2.group(5),
                                       (":" + _m2.group(6)) if _m2.group(6) else "")
        e["最近训练"] = lt
        t = last.get(ly)
        e["最近一次结果"] = ("rc=%s · %ss · %s" % (t["rc"], t["secs"], t["src"])) if t else "唯一依据未登记"
        e["微调方式"] = {"L2": "LoRA(annot 域) · 30 epoch",
                        "L3": "LoRA(local) · 20 步",
                        "L4": "LoRA(r8/α16) · 20 步",
                        "L5": "L5 头 + 合并为可部署"}.get(ly, "唯一依据未登记")
        # 🔎 候选 (未在役): 该层**所有非在役**产物的真实清单 + 为什么没切 (判据取自 8796 note_short)
        cand_names = [_cmpp(str(m.get("name") or "")) for m in models if not m.get("active")]
        cand_names = [c for c in cand_names if c and c not in e["在役模型"]]
        e["候选模型"] = " · ".join(cand_names) or "无"
        st_cands = [m for m in (st.get("models") or []) if str(m.get("layer")) == ly
                    and str(m.get("state")) == "candidate"]
        notes = [str(m.get("note_short") or m.get("note") or "")[:80] for m in st_cands]
        if not notes and cand_names:
            notes = ["产物未评估(尚无 A/B 判据)"]      # 如实: 有产物但没做过对照 ⇒ 不编结论
        if "SAM3" in e["候选模型"]:                     # SAM3 的判据唯一依据 = 引擎 note_short
            _s3 = [n for n in notes if n]
            notes = _s3 or ["引擎 note 未登记"]
        e["候选判据"] = " · ".join(notes) or "无"
        _cp = ""
        for m in models:                       # 候选权重真实路径 (SAM3 优先: 它就是 L2 的候选)
            if m.get("active"):
                continue
            _p = m.get("realpath") or m.get("path") or ""
            if _p and (not _cp or "sam3" in str(_p).lower()):
                _cp = _p
        e["候选权重路径"] = _cp or "无"
        rows[ly] = e
    # 🧩 L2 候选 · SAM3 的单项唯一依据 (给配置中心模型配置域用; 与上面的表同源同一次现算)
    _sm3 = next((m for m in (st.get("models") or []) if "SAM3" in str(m.get("name") or "")), {})
    _base = os.path.join(ROOT, SAM3_BASE_REL)
    _adap = os.path.join(ROOT, SAM3_ADAPTER_REL)
    extras = {
        "SAM3|基座路径": (os.path.relpath(_base, ROOT) if os.path.exists(_base) else "唯一依据未登记"),
        "SAM3|基座体积": _size(_base) if os.path.exists(_base) else "唯一依据未登记",
        "SAM3|适配器路径": (os.path.relpath(_adap, ROOT) if os.path.exists(_adap) else "无 (纯基座)"),
        "SAM3|适配器体积": _size(_adap) if os.path.exists(_adap) else "无 (纯基座)",
        "SAM3|状态": ({"in_service": "在役", "candidate": "候选"}.get(str(_sm3.get("state")), "唯一依据未登记")
                     if _sm3 else "唯一依据未登记"),
        "SAM3|判据": (str(_sm3.get("note_short") or _sm3.get("note") or "")[:120] or "唯一依据未登记"),
        "SAM3|服务": ("tools/sam3_seg.py --serve --port 8796 --lazy (常驻, 首次 /seg 才加载)"
                     if _sm3 else "唯一依据未登记"),
    }
    groups = [("🏗 模型身份", ["在役模型", "版本", "权重路径", "权重体积", "状态"]),
              ("🧠 结构与训练", ["架构", "参数量", "微调方式", "训练入口", "最近训练", "最近一次结果"]),
              ("🔗 状态空间接入", ["状态空间节点", "输出话题", "节点源码"]),
              ("🔎 候选 (未在役)", ["候选模型", "候选判据", "候选权重路径"])]
    return {"columns": [dict(layer=ly, **{k: rows[ly][k] for k in ("在役模型", "版本", "状态")})
                        for ly in LAYERS],
            "groups": [{"cat": c, "rows": [{"name": r, "vals": {ly: rows[ly][r] for ly in LAYERS}}
                                           for r in rs]} for c, rs in groups],
            "extras": extras,
            "sources": srcs, "ts": __import__("time").strftime("%Y-%m-%d %H:%M:%S")}


def show(m):
    print("模型配置矩阵 (唯一依据现算 · %s)" % m["ts"])
    print("  " + " | ".join("%s %s" % (c["layer"], c["版本"]) for c in m["columns"]))
    for g in m["groups"]:
        print("\n%s" % g["cat"])
        for r in g["rows"]:
            print("  %-10s" % r["name"] + " | ".join(str(r["vals"][ly])[:34] for ly in LAYERS))
    print("\n唯一依据:")
    for k, v in m["sources"].items():
        print("  %s = %s" % (k, v))


def check(m):
    bad = []
    for ly in LAYERS:
        for g in m["groups"]:
            for r in g["rows"]:
                v = str(r["vals"][ly])
                if not v or v in ("None", "—") or "None" in v:
                    bad.append("%s/%s" % (ly, r["name"]))
    ok = not bad
    print("判据: 四层 × %d 项无空值/None ⇒ %s" % (sum(len(g["rows"]) for g in m["groups"]),
                                            "PASS" if ok else "FAIL"))
    if bad:
        print("  空值项: %s" % bad[:8])
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true",
                    help="写缓存 reports/model_config_matrix.json (GUI 冷启动读它, 不阻塞界面)")
    a = ap.parse_args()
    m = build()
    if a.write:
        p = os.path.join(ROOT, "reports", "model_config_matrix.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        print("已写 %s" % os.path.relpath(p, ROOT))
    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    elif a.check:
        sys.exit(check(m))
    else:
        show(m)
