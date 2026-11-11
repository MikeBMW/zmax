#!/usr/bin/env python3
"""专利正文 md → 编写稿 JSON (config/patents/drafts/part_*.json)。

用途: 手写定稿的专利正文 (docs/1-天枢-产品边界/patents/ZMP-*.md) 反向生成编写稿条目,
使 config/patents/patent_registry.json (唯一依据) 与正文同步, 不再出现
"正文写了 20 件、registry 只登记 12 件 ⇒ 专利地图现算少 8 件" 的漂移。

正文文字逐条从 md 抽取 (摘要=发明名称+核心思想段, 问题=背景技术各小节, 方案=发明内容步骤+实现模块表,
权利要求逐条, 实施例=具体实施方式前几节, 效果=有益效果条目), 不做改写; 唯一人给的是
star/layer/fn_ids 映射 (见 MAP 注释)。

用法:
  ./gui-venv311/bin/python tools/patent_drafts_import.py --write   # 写 drafts/part_c.json
  ./gui-venv311/bin/python tools/patent_center.py --build          # 合并进唯一依据 registry
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATS = os.path.join(ROOT, "docs", "1-天枢-产品边界", "patents")
DRAFT_DIR = os.path.join(ROOT, "config", "patents", "drafts")

# 手写正文 → registry 元信息。star/layer 沿用北斗七星已有分层习惯:
# 天枢=体系/可信, 天玑=数学内核, 天权=感知, 玉衡=模型, 开阳=执行, 瑶光=标定/呈现。
MAP = {
    "ZMP-2026-013": dict(codename="北斗·开阳", star="开阳", layer="动作注入层",
                         impl_hint=["src/lerobot/policies/manifold/geodesic_inject.py",
                                    "src/lerobot/policies/manifold/inject_cfg.py",
                                    "tools/verify_013_claims.py"],
                         fn_ids=["FN-SYS0-39", "FN-SYS0-49", "FN-SYS0-50", "FN-SYS0-58"],
                         fn_ids_related=["FN-SYS2-19", "FN-SYS0-62", "FN-SYS1-33"]),
    "ZMP-2026-014": dict(codename="北斗·天权", star="天权", layer="质量门层",
                         fn_ids=["FN-SYS0-40", "FN-SYS0-37", "FN-SYS0-38"],
                         fn_ids_related=["FN-PLAT-77", "FN-SYS0-51", "FN-SYS0-62"]),
    "ZMP-2026-015": dict(codename="北斗·天枢", star="天枢", layer="工程可信层",
                         fn_ids=["FN-SYS0-62", "FN-SYS0-63"],
                         fn_ids_related=["FN-PLAT-72", "FN-SYS2-08"]),
    "ZMP-2026-016": dict(codename="北斗·天枢", star="天枢", layer="工程可信层",
                         impl_hint=["src/lerobot/middleware/nodes/impl/ss_aoi.py",
                                    "tools/probe_aoi_async.py"],
                         fn_ids=["FN-SYS0-40", "FN-PLAT-77"],
                         fn_ids_related=["FN-SYS0-37", "FN-SYS0-38"]),
    "ZMP-2026-017": dict(codename="北斗·天枢", star="天枢", layer="工程可信层",
                         impl_hint=["src/lerobot/policies/manifold/inject_cfg.py",
                                    "src/lerobot/policies/manifold/geodesic_inject.py"],
                         fn_ids=["FN-SYS0-49", "FN-SYS2-30"],
                         fn_ids_related=["FN-SYS0-50", "FN-PLAT-72"]),
    "ZMP-2026-018": dict(codename="北斗·开阳", star="开阳", layer="工程可信层/动作层",
                         impl_hint=["tools/bridge_follow.py",
                                    "src/lerobot/policies/left_right/state_space/planner.py"],
                         fn_ids=["FN-SYS0-63", "FN-SYS0-60"],
                         fn_ids_related=["FN-SYS0-51", "FN-SYS2-13"]),
    "ZMP-2026-019": dict(codename="北斗·玉衡", star="玉衡", layer="世界模型跨层",
                         fn_ids=["FN-SYS2-22", "FN-SYS2-24", "FN-SYS0-49"],
                         fn_ids_related=["FN-SYS2-23", "FN-SYS2-19"]),
    "ZMP-2026-020": dict(codename="北斗·天玑", star="天玑", layer="数学内核层/动作层",
                         impl_hint=["src/lerobot/policies/manifold/metric_inject.py",
                                    "src/lerobot/policies/manifold/inject_cfg.py",
                                    "tools/verify_metric_hard_inject.py"],
                         fn_ids=["FN-SYS1-33", "FN-SYS0-49", "FN-SYS2-30"],
                         fn_ids_related=["FN-SYS1-34", "FN-SYS0-50"]),
}


def clean(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s or "")
    s = s.replace("**", "").replace("`", "").replace("\\", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def blocks(txt):
    """[(level, heading, body_lines)] — body 到下一个任意级标题为止, 级数保留以便取子节。"""
    out, cur = [], None
    for line in txt.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if cur:
                out.append(cur)
            cur = [len(m.group(1)), m.group(2).strip(), []]
        elif cur:
            cur[2].append(line)
    if cur:
        out.append(cur)
    return out


def section(bl, *keys):
    """命中标题 + 其全部子节 body (按级数收集)。"""
    for i, (lvl, h, body) in enumerate(bl):
        if all(k in h for k in keys):
            acc = list(body)
            for l2, h2, b2 in bl[i + 1:]:
                if l2 <= lvl:
                    break
                acc.append("### " + h2)
                acc.extend(b2)
            return h, acc
    return None, []


def resolve(ref):
    """md 里的裸文件名 / 老路径 → 真实存在的路径 (找不到返回 None, 不猜)。"""
    cands = [ref, os.path.join("src", "lerobot", ref), os.path.join("tools", ref)]
    for c in cands:
        if os.path.exists(os.path.join(ROOT, c)):
            return c
    base = os.path.basename(ref)
    for root in ("src/lerobot", "tools"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, root)):
            if base in files:
                return os.path.relpath(os.path.join(dirpath, base), ROOT)
    if ref.startswith(("zmax_data/", "data/")):
        return ref
    return None


def paras(lines):
    out, buf = [], []
    for ln in list(lines) + [""]:
        if not ln.strip():
            if buf:
                out.append(clean(" ".join(buf)))
                buf = []
            continue
        if ln.startswith("|") or ln.startswith("---") or ln.startswith("## ") or ln.startswith("### "):
            continue
        buf.append(ln.strip())
    return [p for p in out if p and not p.startswith("![")]


def subsections(lines):
    """按 '### ' 或 '**x.y 标题**' 切子节 → [(标题, body_lines)]。"""
    out, cur = [], None
    for ln in lines:
        m = (re.match(r"^#{3,4}\s+(.*)$", ln)
             or re.match(r"^\*\*([0-9]+(?:\.[0-9]+)?\s*[^*]*)\*\*\s*$", ln)
             or re.match(r"^\*\*(步骤\s*[0-9]+[^*]*)\*\*\s*$", ln))
        if m:
            if cur:
                out.append(cur)
            cur = [clean(m.group(1)), []]
        elif cur:
            cur[1].append(ln)
    if cur:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    pats = []
    for f in sorted(glob.glob(os.path.join(PATS, "ZMP-2026-*.md"))):
        pid = os.path.basename(f)[:12]
        if pid not in MAP:
            continue
        txt = open(f, encoding="utf-8").read()
        bl = blocks(txt)
        m = MAP[pid]
        h1 = next((h for lvl, h, _ in bl if lvl == 1), "")
        _, name_body = section(bl, "发明名称")
        title = clean(paras(name_body)[0]) if paras(name_body) else clean(h1)

        _, core = section(bl, "核心思想")
        cps = paras(core)
        abstract = clean("本发明公开" + title + "：" + (cps[0] if cps else ""))[:600]

        probs = []
        _, bbody = section(bl, "背景技术")
        subs = subsections(bbody)
        for h, body in subs:
            ps = paras(body)
            probs.append(clean((h + "：" if h else "") + (ps[0] if ps else ""))[:400])
        if not subs:                                     # 背景技术无子节: 取首 3 段
            probs = paras(bbody)[:3]
        if len(probs) < 2 and probs:                     # 仍只有 1 段: 按句切 (原文切分, 不改写)
            sents = [s.strip() + "。" for s in probs[0].split("。") if len(s.strip()) > 8]
            probs = sents[:4] or probs

        sol = []
        _, ibody = section(bl, "发明内容")
        for h, body in subsections(ibody):
            sol.append(clean(h))
        for h, body in subsections(section(bl, "示例性实现")[1]):
            pass
        for h, body in subsections(section(bl, "示例性实现")[1]):
            pass
        # 示例性实现模块表: | 步骤 N | 模块 | 职责 |
        _, mbody = section(bl, "示例性实现")
        for ln in mbody:
            if ln.startswith("| 步骤"):
                c = [clean(x) for x in ln.strip().strip("|").split("|")]
                if len(c) >= 3 and "模块" not in c[1]:
                    sol.append("%s 由%s实现：%s" % (c[0], c[1], c[2]))
        sol = sol[:22]

        claims, buf = [], ""
        _, kbody = section(bl, "权利要求")
        for ln in kbody:
            s = ln.strip()
            if not s or s.startswith("|") or s.startswith("#"):
                continue
            if re.match(r"^\d{1,2}\s*[.、]", s):
                if buf:
                    claims.append(clean(buf))
                buf = s
            elif buf:
                buf += " " + s
        if buf:
            claims.append(clean(buf))

        emb = []
        _, ebody = section(bl, "具体实施方式")
        for h, body in subsections(ebody)[:4]:
            ps = paras(body)
            if ps:
                emb.append(clean((h + "：" if h else "") + " ".join(ps[:2]))[:500])

        eff = []
        _, gbody = section(bl, "有益效果")
        if not gbody:
            _, gbody = section(bl, "技术效果")
        for ln in gbody:
            s = clean(ln)
            if s and not s.startswith("|") and not s.startswith("!") and len(s) > 6:
                eff.append(s[:300])
        eff = eff[:8]

        refs = sorted(set(re.findall(r"[\w./\-]+\.(?:py|json|sh|db)\b", txt)))
        impl, data = [], []
        for r in refs + list(m.get("impl_hint") or []):
            hit = resolve(r)
            if hit and hit.endswith(".py") and hit not in impl:
                impl.append(hit)
            elif hit and not hit.endswith(".py") and hit not in data:
                data.append(hit)

        pats.append(dict(pat_id=pid, codename=m["codename"], star=m["star"], layer=m["layer"],
                         type="发明专利", status="定稿" if pid in ("ZMP-2026-013", "ZMP-2026-019") else "撰写中",
                         title=title, abstract=abstract, problems=probs, solution=sol, effects=eff,
                         claims=claims, embodiment=emb, fn_ids=m["fn_ids"], fn_ids_related=m["fn_ids_related"],
                         impl_refs=impl, data_refs=data))
        print("%s | %s | 问题%d 方案%d 权项%d 实施%d 效果%d | impl%d data%d"
              % (pid, title[:22], len(probs), len(sol), len(claims), len(emb), len(eff), len(impl), len(data)))

    if a.write:
        out = dict(schema="zmax-patent-drafts/1",
                   note=("手写定稿专利正文 (013-020) 的编写稿: 文字逐条抽取自 docs/1-天枢-产品边界/patents/ "
                         "下的 md 定稿 (tools/patent_drafts_import.py), star/layer/fn 映射由 MAP 人工给定。"
                         "用于 --build 合并进唯一依据 registry。"),
                   patents=pats)
        os.makedirs(DRAFT_DIR, exist_ok=True)
        fp = os.path.join(DRAFT_DIR, "part_c.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("✅ 写出 %s (%d 件)" % (os.path.relpath(fp, ROOT), len(pats)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
