#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据治理闸 — 把《数据平台合作与模型授权协议》的条款变成可执行的闸 (2026-10-10)

与 tools/data_sync.py 的分工:
  · data_sync.py       = 通道本身 (4060 侧从 ECS 拉数据 / 触发训练)
  · data_governance.py = 通道上的**权属与导出闸** (这份数据能不能出平台, 出了要留什么痕)

设计: 条款与工具同源。权属/可导出性/脱敏要求/SLA 只写在
      config/platform/zmax_data_governance.json; 本工具按它强制:
        · 每份数据按落点路径判定类别 (D0..D4) 与权属
        · exportable_to_supplier=false 的类别 → 物理拒发 (不是"建议不要发")
        · 每次同步写审计 data/governance/audit.jsonl, 越权尝试必留痕
        · 供应商回传模型必须登记台账 (训练数据指纹+权重哈希), 未登记不得进默认档

用法:
  python3 tools/data_governance.py manifest [--class D1] [--root PATH]
  python3 tools/data_governance.py plan supplier
  python3 tools/data_governance.py push supplier [--to DIR] [--dry-run]
  python3 tools/data_governance.py pull supplier --from DIR
  python3 tools/data_governance.py ledger | audit [-n 20]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOV = os.path.join(ROOT, "config", "platform", "zmax_data_governance.json")
GDIR = os.path.join(ROOT, "data", "governance")
AUDIT = os.path.join(GDIR, "audit.jsonl")
LEDGER = os.path.join(GDIR, "model_ledger.json")
MANIFESTS = os.path.join(GDIR, "manifests")
STAGING = os.path.join(ROOT, "outputs", "governance_staging")
HASH_CAP = 256 * 1024 * 1024          # 单文件超 256MB 只哈希前 256MB, 并显式标 partial


def gov():
    return json.load(open(GOV, encoding="utf-8"))


def _sha(p, cap=HASH_CAP):
    h = hashlib.sha256()
    n = 0
    partial = False
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            n += len(b)
            if n > cap:
                partial = True
                break
            h.update(b)
    return h.hexdigest(), partial


def classify(path, g=None):
    """按落点路径判定数据类别 (最长前缀匹配)。返回 (class_id, cls_dict)。"""
    g = g or gov()
    rel = os.path.relpath(os.path.abspath(path), ROOT)
    best = (None, None, -1)
    for c in g["data_classes"]:
        for pre in c["paths"]:
            if rel == pre or rel.startswith(pre.rstrip("/") + os.sep):
                if len(pre) > best[2]:
                    best = (c["class_id"], c, len(pre))
    return best[0], best[1]


def audit(actor, action, **kw):
    os.makedirs(GDIR, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "actor": actor, "action": action}
    rec.update(kw)
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def scan(root, cls_filter=None, do_hash=True):
    """扫描目录 → 条目清单 (带类别/权属/可导出/哈希)。"""
    g = gov()
    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules")]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            cid, c = classify(p, g)
            if cid is None:
                cid, c = "UNCLASSIFIED", {"name": "未分类", "owner": "待标注",
                                          "exportable_to_supplier": False, "retention": "-"}
            if cls_filter and cid != cls_filter:
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            sha, partial = _sha(p) if do_hash else ("", False)
            items.append({"path": os.path.relpath(p, ROOT), "bytes": st.st_size,
                          "class_id": cid, "class_name": c["name"], "owner": c["owner"],
                          "exportable": bool(c["exportable_to_supplier"]),
                          "sha256": sha, "hash_partial": partial})
    return items


def cmd_manifest(a):
    roots = [a.root] if a.root else [os.path.join(ROOT, p) for p in
                                     [x for c in gov()["data_classes"] for x in c["paths"]]]
    seen, items = set(), []
    for r in roots:
        if not os.path.isdir(r):
            continue
        for it in scan(r, a.cls):
            if it["path"] not in seen:
                seen.add(it["path"])
                items.append(it)
    if a.max_files and len(items) > a.max_files:
        items = sorted(items, key=lambda x: -x["bytes"])[:a.max_files]
    os.makedirs(MANIFESTS, exist_ok=True)
    out = os.path.join(MANIFESTS, "manifest_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "root": a.root or "全部治理落点",
               "count": len(items), "total_bytes": sum(i["bytes"] for i in items), "items": items,
               "by_class": {}}
    for it in items:
        b = payload["by_class"].setdefault(it["class_id"], {"count": 0, "bytes": 0,
                                                            "exportable": it["exportable"],
                                                            "name": it["class_name"]})
        b["count"] += 1
        b["bytes"] += it["bytes"]
    json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    audit("local", "manifest", count=len(items), bytes=payload["total_bytes"],
          file=os.path.relpath(out, ROOT))
    print("清单: %s  (%d 个文件 / %.1f MB)" % (os.path.relpath(out, ROOT), len(items),
                                              payload["total_bytes"] / 1e6))
    for cid, b in sorted(payload["by_class"].items()):
        flag = "可下发" if b["exportable"] else "🔒 禁导出"
        print("  %-4s %-24s %4d 个 %10.2f MB   %s" % (cid, b["name"], b["count"],
                                                      b["bytes"] / 1e6, flag))
    return 0


def _collect(cls_filter=None, do_hash=True):
    """按类别收集 (允许下发, 被拦) 两组条目。"""
    g = gov()
    ok, bad = [], []
    for c in g["data_classes"]:
        if cls_filter and c["class_id"] != cls_filter:
            continue
        for p in c["paths"]:
            full = os.path.join(ROOT, p)
            if not os.path.isdir(full):
                continue
            (ok if c["exportable_to_supplier"] else bad).extend(
                scan(full, c["class_id"], do_hash=do_hash))
    return g, ok, bad


def cmd_plan(a):
    g, ok, bad = _collect(a.cls, do_hash=False)
    print("下发计划 → 供应商 (通道 C2 训练下行)")
    print("  ✅ 允许: %d 个文件 / %.1f MB" % (len(ok), sum(i["bytes"] for i in ok) / 1e6))
    for cid in sorted({i["class_id"] for i in ok}):
        s = [i for i in ok if i["class_id"] == cid]
        cls = next((c for c in g["data_classes"] if c["class_id"] == cid), {})
        print("     %-4s %-24s %4d 个   脱敏: %s" % (cid, s[0]["class_name"], len(s),
                                                    "、".join(cls.get("desensitize") or []) or "无"))
    print("  🔒 拦截: %d 个文件 / %.1f MB (协议禁导出)" % (len(bad), sum(i["bytes"] for i in bad) / 1e6))
    for cid in sorted({i["class_id"] for i in bad}):
        s = [i for i in bad if i["class_id"] == cid]
        print("     %-4s %-24s %4d 个   权属: %s" % (cid, s[0]["class_name"], len(s),
                                                    s[0]["owner"][:36]))
    return 0


def cmd_push(a):
    g, items, blocked = _collect(a.cls)
    dest = a.to or os.path.join(STAGING, time.strftime("%Y%m%d_%H%M%S"))
    if a.dry_run:
        print("DRY-RUN: 允许 %d 个 / %.1f MB · 拦截 %d 个 / %.1f MB"
              % (len(items), sum(i["bytes"] for i in items) / 1e6,
                 len(blocked), sum(i["bytes"] for i in blocked) / 1e6))
        audit("local", "push_dryrun", allowed=len(items), blocked=len(blocked),
              dest=os.path.relpath(dest, ROOT))
        return 0
    os.makedirs(dest, exist_ok=True)
    sent = []
    for it in items:
        src = os.path.join(ROOT, it["path"])
        dst = os.path.join(dest, it["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        sha, _ = _sha(dst)
        assert sha == it["sha256"], "校验失败: %s" % it["path"]
        sent.append(it)
    man = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "governance_version": g["version"],
           "channel": "C2 训练下行",
           "allowed_classes": [c["class_id"] for c in g["data_classes"] if c["exportable_to_supplier"]],
           "blocked_classes": sorted({b["class_id"] for b in blocked}),
           "count": len(sent), "total_bytes": sum(i["bytes"] for i in sent), "items": sent}
    json.dump(man, open(os.path.join(dest, "transfer_manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    audit("local", "push", channel="C2", allowed=len(sent), blocked=len(blocked),
          bytes=man["total_bytes"], dest=os.path.relpath(dest, ROOT),
          blocked_classes=man["blocked_classes"])
    print("已下发 → %s" % os.path.relpath(dest, ROOT))
    print("  %d 个文件 / %.1f MB · 逐文件 sha256 校验通过" % (len(sent), man["total_bytes"] / 1e6))
    print("  🔒 拦截未下发: %d 个文件 (类别 %s) — 已留审计" % (len(blocked), man["blocked_classes"]))
    print("  传输清单: %s" % os.path.relpath(os.path.join(dest, "transfer_manifest.json"), ROOT))
    return 0


def _ledger_read():
    if os.path.isfile(LEDGER):
        return json.load(open(LEDGER, encoding="utf-8"))
    return {"format": "zmax-model-ledger", "version": "1.0", "models": []}


def cmd_pull(a):
    src = a.src
    if not src or not os.path.isdir(src):
        print("用法: pull supplier --from <回传目录> (目录内需含 model_manifest.json)")
        return 2
    mp = os.path.join(src, "model_manifest.json")
    if not os.path.isfile(mp):
        print("❌ 回传缺 model_manifest.json — 未登记不得部署 (协议 C3)")
        audit("supplier", "pull_rejected", reason="缺 model_manifest.json", src=src)
        return 3
    m = json.load(open(mp, encoding="utf-8"))
    g = gov()
    missing = [k for k in ("model_id", "weight_sha256", "trained_on") if not m.get(k)]
    if missing:
        print("❌ 回传缺字段 %s (协议要求 %s)" % (missing, g["model_terms"]["fingerprint_required"]))
        audit("supplier", "pull_rejected", reason="缺字段 %s" % missing, model=m.get("model_id"))
        return 3
    wp = os.path.join(src, m.get("weight_file", ""))
    if os.path.isfile(wp):
        sha, _ = _sha(wp)
        if sha != m["weight_sha256"]:
            print("❌ 权重哈希不符: 清单 %s… 实测 %s… — 拒收" % (m["weight_sha256"][:16], sha[:16]))
            audit("supplier", "pull_rejected", reason="权重哈希不符", model=m["model_id"])
            return 3
    lg = _ledger_read()
    rec = {"model_id": m["model_id"], "name": m.get("name", ""), "owner": m.get("owner", "供应商"),
           "base_weights": m.get("base_weights", "平台方基础权重"),
           "trained_on": m["trained_on"], "weight_sha256": m["weight_sha256"],
           "authorized_scope": m.get("authorized_scope", g["platform_scope"]["scenarios"]),
           "resale": g["model_terms"]["resale"], "expiry": m.get("expiry", ""),
           "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"), "deployed": False}
    lg["models"] = [x for x in lg["models"] if x["model_id"] != rec["model_id"]] + [rec]
    json.dump(lg, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    audit("supplier", "pull_registered", model=rec["model_id"],
          weight_sha256=rec["weight_sha256"][:16], trained_on=rec["trained_on"])
    print("✅ 已登记台账: %s (权重 %s…) — 未登记不得进默认档" % (rec["model_id"],
                                                              rec["weight_sha256"][:16]))
    return 0


def cmd_ledger(a):
    lg = _ledger_read()
    g = gov()
    r = g["model_terms"]["resale"]
    print("模型台账 (data/governance/model_ledger.json) — %d 条" % len(lg["models"]))
    print("  转售规则: 允许=%s · 需书面同意=%s · 二次授权=%s" % (
        r["allowed"], r["requires_written_consent"], r["sub_license"]))
    if not lg["models"]:
        print("  (空) 供应商尚无回传模型")
    for m in lg["models"]:
        print("  %-24s 权属=%-8s 训练数据=%s 部署=%s 到期=%s"
              % (m["model_id"], m["owner"], m["trained_on"], m["deployed"], m["expiry"] or "-"))
    return 0


def cmd_audit(a):
    if not os.path.isfile(AUDIT):
        print("(无审计记录)")
        return 0
    lines = open(AUDIT, encoding="utf-8").read().strip().splitlines()[-a.n:]
    print("审计日志 (最近 %d 条, %s)" % (len(lines), os.path.relpath(AUDIT, ROOT)))
    for ln in lines:
        d = json.loads(ln)
        k = " ".join("%s=%s" % (x, y) for x, y in d.items() if x not in ("ts", "action", "actor"))
        print("  %s %-8s %-16s %s" % (d["ts"], d["actor"], d["action"], k[:96]))
    return 0


CMDS = {"manifest": cmd_manifest, "plan": cmd_plan, "push": cmd_push,
        "pull": cmd_pull, "ledger": cmd_ledger, "audit": cmd_audit}


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?", default="plan")
    ap.add_argument("target", nargs="?")
    ap.add_argument("--class", dest="cls", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--to", default=None)
    ap.add_argument("--from", dest="src", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-files", type=int, default=2000)
    ap.add_argument("-n", type=int, default=20)
    a, _ = ap.parse_known_args()
    if not a.src and "--from" in sys.argv:
        i = sys.argv.index("--from")
        a.src = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    fn = CMDS.get(a.cmd)
    if not fn:
        print(__doc__)
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
