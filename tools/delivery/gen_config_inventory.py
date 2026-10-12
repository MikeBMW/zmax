#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_config_inventory.py — 生成「全系统总配置清单」(交付件)。

为什么用生成而不是手写: 交付件里的端口/服务/模型/节点数必须可复核 —— 手写会过期、
且老倪会逐条追问"这个数怎么来的"。本脚本逐项从**在役系统**读取, 每项都带来源。

输出:
  docs/deliverables/全系统配置清单_<ver>.md
  docs/deliverables/全系统配置清单_<ver>.json

用法: python tools/delivery/gen_config_inventory.py [--ver 5.50.A] [--repo /home/ubuntu/zmax]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import time


def sh(cmd: str, t: int = 12) -> str:
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:                                                       # noqa: BLE001
        return "<<%s: %s>>" % (type(e).__name__, e)


def sha8(p: str) -> str:
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()[:12]
    except Exception:                                                            # noqa: BLE001
        return "-"


def size_mb(p: str) -> str:
    try:
        return "%.1f MB" % (os.path.getsize(p) / 1048576)
    except Exception:                                                            # noqa: BLE001
        return "-"


def jload(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        return default if default is not None else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", default="5.50.A")
    ap.add_argument("--repo", default=os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax"))
    a = ap.parse_args()
    R = a.repo
    os.chdir(R)
    inv: dict = {"schema": "zmax-config-inventory/1.0", "version": a.ver,
                 "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "repo": R, "sections": {}}

    # ① 版本与分支
    studio = open(os.path.join(R, "tools/gui/studio.py"), encoding="utf-8", errors="ignore").read()
    m = re.findall(r'QLabel\("Z-MAX v{1,2}(\d+\.\d+\.\d+)"\)', studio)
    _vm = ""
    try:
        for _ln in open(os.path.join(R, "VERSION.md"), encoding="utf-8", errors="ignore").read().splitlines():
            _mm = re.search(r"(\d+\.\d+\.\d+)", _ln)
            if _mm and not _ln.lstrip().startswith("#"):
                _vm = _mm.group(1)
                break
    except Exception:                                                            # noqa: BLE001
        pass
    _tags = [t for t in sh("git tag --sort=-creatordate").split() if re.match(r"^v\d+\.\d+\.\d+$", t)]
    inv["sections"]["版本"] = {
        "界面品牌版本": (max(set(m), key=m.count) if m else "-"),
        "VERSION.md 记载": _vm or "-",
        "git HEAD": sh("git log --oneline -1").strip(),
        "git describe": sh("git describe --tags").strip(),
        "最新 tag(按创建时间, 只认 vX.Y.Z)": (_tags[0] if _tags else "-"),
        "tag 总数": len(_tags),
    }

    # ② 在役服务与端口 (真源 = ss -ltn + systemd)
    ports = {}
    for ln in sh("ss -ltnp").splitlines()[1:]:
        mm = re.search(r":(\d+)\s", ln)
        if mm and mm.group(1) in {"8791", "8793", "8796", "8797", "8799", "8795", "5000", "8888", "4000", "9090"}:
            ports[mm.group(1)] = ln.strip()[:120]
    units = [u.split()[0] for u in sh("systemctl list-units --type=service --all --no-legend").splitlines()
             if "zmax" in u or "sam3" in u or "cam_" in u or "station" in u]
    inv["sections"]["在役服务"] = {
        "监听端口": ports,
        "systemd 单元": {u: sh("systemctl is-active %s" % u).strip() for u in units[:20]},
        "crontab": sh("crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$'").strip().split("\n")[:12],
    }

    # ③ 配置真源文件 (逐个 sha256 ⇒ 交付可校验)
    cfgs = []
    for pat in ("config/ss_task_binding.json", "config/topics/*.json", "config/mcd/*.json",
                "config/version.json", "config/aoi/*.json", "config/*.json"):
        for p in sorted(glob.glob(os.path.join(R, pat))):
            if p.endswith(".json") and os.path.getsize(p) < 4 << 20:
                cfgs.append({"file": os.path.relpath(p, R), "size": os.path.getsize(p), "sha256_12": sha8(p)})
    seen, uniq = set(), []
    for c in cfgs:
        if c["file"] not in seen:
            seen.add(c["file"])
            uniq.append(c)
    inv["sections"]["配置真源"] = {"files": uniq, "count": len(uniq)}

    # ④ 任务/场景绑定
    b = jload(os.path.join(R, "config/ss_task_binding.json"))
    tasks = b.get("tasks") or []
    inv["sections"]["任务与场景"] = {
        "active_task": b.get("active_task"),
        "project": b.get("project"),
        "tasks": [{"task_id": t.get("task_id"), "name": t.get("name"), "recipe_type": t.get("recipe_type"),
                   "scene": t.get("scene_ref"), "site": t.get("site"), "ss_mode": t.get("ss_mode"),
                   "steps": len(t.get("steps") or []),
                   "enabled_nodes": len(t.get("enabled_nodes") or []),
                   "disabled_nodes": len(t.get("disabled_nodes") or [])} for t in tasks],
        "count": len(tasks),
        "segment_node_map": len(b.get("segment_node_map") or {}),
        "coverage": b.get("coverage"),
    }

    # ⑤ 模型与数据集 (交付需知道依赖哪些权重/数据)
    models = []
    for pat in ("models/*.pt", "models/*.npz", "zmax_data/models/*"):
        for p in sorted(glob.glob(os.path.join(R, pat))):
            if os.path.isfile(p) and not p.endswith(".json"):
                models.append({"file": os.path.relpath(p, R), "size": size_mb(p), "sha256_12": sha8(p)})
    inv["sections"]["模型权重"] = {"files": models, "count": len(models)}

    # ⑥ 相机与 AOI (从在役流服务读真值)
    stats = sh("curl -s --max-time 6 http://127.0.0.1:8791/stats")
    chans = {}
    try:
        for k, v in json.loads(stats).items():
            chans[k] = {"label": (v.get("label") or "")[:40], "fps": v.get("fps"),
                        "age_s": v.get("age_s"), "stalled": v.get("stalled")}
    except Exception:                                                            # noqa: BLE001
        pass
    aoi = {}
    for port in (10082, 10083):
        r = sh('curl -s -A zmax-probe --max-time 8 "http://192.168.23.23:%d/exposure"' % port)
        if not r.strip().startswith("{"):
            r = sh('curl -s -A zmax-probe --max-time 8 "http://192.168.23.23:%d/param"' % port)
        aoi[str(port)] = r.strip()[:260]
    inv["sections"]["相机与AOI"] = {"流服务通道": chans, "AOI端口(工控机 192.168.23.23)": aoi}

    # ⑦ 数据空间 (DDS) 话题注册表
    top = open(os.path.join(R, "src/lerobot/dataspace/topics.py"), encoding="utf-8", errors="ignore").read()
    inv["sections"]["数据空间"] = {
        "topic 常量数": len(re.findall(r'^\s*[A-Z_]+\s*=\s*"zmax/', top, re.M)),
        "registry": "src/lerobot/dataspace/topics.py",
        "live": "zmax_data/dataspace/live.json" if os.path.exists(os.path.join(R, "zmax_data/dataspace/live.json")) else "-",
        "AR/AOI 信号": (len((jload(os.path.join(R, "config/topics/ar_aoi_signals.json")).get("groups") or {})) or 0),
    }

    # ⑧ 状态空间画布规模 (真源 = flows/state_space_obs.json + 工程库)
    nodes = edges = 0
    canvas_files = sorted(glob.glob(os.path.join(R, "flows/*.json")))
    for p in canvas_files:
        d = jload(p)
        if isinstance(d, dict) and ("nodes" in d or "links" in d):
            nodes = max(nodes, len(d.get("nodes") or []))
            edges = max(edges, len(d.get("links") or d.get("edges") or []))
    _db = os.path.join(R, "data/database/zmax/zmax_engineering.db")
    inv["sections"]["状态空间工程"] = {
        "画布真源": "flows/state_space_obs.json",
        "节点数": nodes, "连线数": edges, "flows 源件数": len(canvas_files),
        "工程库": (os.path.relpath(_db, R) + " (%s)" % size_mb(_db)) if os.path.exists(_db) else "-",
        "其余画布源件": [os.path.relpath(p, R) for p in canvas_files][:12],
    }

    # ⑨ 技能与文档
    inv["sections"]["技能与文档"] = {
        "技能数": len(glob.glob(os.path.expanduser("~/.hermes/skills/**/SKILL.md"), recursive=True)),
        "docs 目录": {
            "data_snapshots": len(glob.glob(os.path.join(R, "docs/data_snapshots/*"))),
            "deliverables": [os.path.basename(p) for p in sorted(glob.glob(os.path.join(R, "docs/deliverables/*")))],
            "design": [os.path.basename(p) for p in sorted(glob.glob(os.path.join(R, "docs/design/*")))],
        },
    }

    # ⑩ 运行环境
    inv["sections"]["运行环境"] = {
        "主机": sh("hostname").strip(), "内核": sh("uname -r").strip(),
        "CPU": sh("nproc").strip() + " 核",
        "内存": sh("free -g | awk 'NR==2{print $2\" GB (可用 \"$7\" GB)\"}'").strip(),
        "磁盘": sh("df -h / | awk 'NR==2{print $2\" 总 / \"$4\" 可用 (\"$5\" 已用)\"}'").strip(),
        "GPU": sh("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader").strip(),
        "Python": sh("%s/gui-venv311/bin/python -V" % R).strip(),
    }

    os.makedirs(os.path.join(R, "docs/deliverables"), exist_ok=True)
    md = os.path.join(R, "docs/deliverables/全系统配置清单_%s.md" % a.ver)
    js = os.path.join(R, "docs/deliverables/全系统配置清单_%s.json" % a.ver)
    with open(js, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)

    L = []
    L.append("# Z-MAX 全系统总配置清单（交付件 %s）" % a.ver)
    L.append("")
    L.append("生成时间: %s · 来源: 在役系统扫描（每个数都可回读复核）· 仓库: `%s`" % (inv["generated_at"], R))
    L.append("")
    for sec, val in inv["sections"].items():
        L.append("## %s" % sec)
        L.append("")
        if isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, dict):
                    L.append("**%s**" % k)
                    L.append("")
                    L.append("| 项 | 值 |")
                    L.append("|---|---|")
                    for k2, v2 in v.items():
                        if isinstance(v2, dict):
                            v2 = json.dumps(v2, ensure_ascii=False)
                        L.append("| %s | %s |" % (k2, str(v2)[:400]))
                    L.append("")
                elif isinstance(v, list):
                    L.append("**%s**（%d 项）" % (k, len(v)))
                    L.append("")
                    if v and isinstance(v[0], dict):
                        ks = list(v[0].keys())
                        L.append("| " + " | ".join(ks) + " |")
                        L.append("|" + "---|" * len(ks))
                        for it in v[:60]:
                            L.append("| " + " | ".join(str(it.get(x, ""))[:120] for x in ks) + " |")
                    else:
                        for it in v[:60]:
                            L.append("- %s" % str(it)[:300])
                    L.append("")
                else:
                    L.append("- **%s**: %s" % (k, str(v)[:600]))
            L.append("")
    open(md, "w", encoding="utf-8").write("\n".join(L))
    print("✅ %s (%d B)" % (md, os.path.getsize(md)))
    print("✅ %s (%d B)" % (js, os.path.getsize(js)))
    for sec in inv["sections"]:
        print("   · %s" % sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
