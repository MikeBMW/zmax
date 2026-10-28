#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""model_runtime_map.py — 「每个模型在哪跑 / 跑的哪个权重 / 用什么转的 / 推理还是训练」的唯一依据。

老倪 2026-10-21: 「在模型引擎, 增加 每个模型在哪里运行, 运行的是哪个权重, 对应的转换工具,
是正在推理, 还是在训练, 你来设计 UI」。

为什么要单独一个文件: 这三列信息**分散在四个地方** —
  ① 哪个设备在跑: Intel `GET /pipeline/stats` + 8796 `/status/all.edge` (只有设备级)
  ② 跑的哪个权重: Intel `GET /models` 的 sha16 (IR 身份) + 本机 ckpt 的 sha256 前 16
  ③ 用什么转的: 仓库里的转换脚本 (torch→ONNX→IR fp16), 只有人记得
  ④ 推理/训练: 8796 `/status/all.models[].inferring` + `training[]` (训练进程)
⇒ 这里收成一份 `config/platform/model_runtime_map.json`, 界面只读它 (不各自猜)。

用法:
    ./gui-venv311/bin/python tools/model_runtime_map.py            # 打印人话表
    ./gui-venv311/bin/python tools/model_runtime_map.py --json     # 给界面
    ./gui-venv311/bin/python tools/model_runtime_map.py --write    # 落盘唯一依据
退出码: 0=都拿得到 / 1=有采集失败项 (绝不把"读不到"写成"没在跑")
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_J = os.path.join(ROOT, "config", "platform", "model_runtime_map.json")
STATUS_URL = os.environ.get("ZMAX_STATUS_URL", "http://127.0.0.1:8796/status/all")
EDGE_URLS = [u for u in (os.environ.get("ZMAX_EDGE_URL"),
                         "http://127.0.0.1:18800",
                         "http://192.168.23.70:8800") if u]
ACTIVE_J = os.path.join(ROOT, "models", "active_models.json")
INTACT_REPORT = os.path.join(ROOT, "zmax_data", "models", "ir", "intact_export.json")

# 转换工具的**唯一口径** (换工具改这里; 界面/文档都读这份)
CONVERTERS = {
    "yolo": {
        "tool": "tools/edge/ov_export_torch.py → tools/edge/ov_convert.py",
        "chain": "pt → ONNX(opset12,静态640) → IR fp16 (compress_to_fp16)",
        "gate": "同批真图比类别/框数/IoU (不许拿「torch 那边也差不多」代替勾兑)",
    },
    "intact": {
        "tool": "tools/edge/export_intact.py → tools/edge/ov_convert.py",
        "chain": "ckpt(严格 load) → ONNX(enc 1×3×224×224 / pred 2×[1,3,192]) → IR fp16",
        "gate": "enc/pred 各跑 parity: max|Δ| (见 items[].parity)",
    },
    "torch": {
        "tool": "无 (torch 直跑, 不进 IR)",
        "chain": "ckpt → 引擎进程内推理 (lerobot / 自研引擎)",
        "gate": "—",
    },
    "api": {
        "tool": "无 (云端 API)",
        "chain": "请求 → 云端模型 (无端侧权重)",
        "gate": "—",
    },
    "service": {
        "tool": "无 (独立服务/容器)",
        "chain": "HTTP 服务内跑自己的权重 (不在 4060/Intel 上)",
        "gate": "服务自身判据",
    },
}


def _sha16(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()[:16]
    except Exception:                                                   # noqa: BLE001
        return None


def _get(url, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _status():
    try:
        return _get(STATUS_URL, 4.0)
    except Exception:                                                   # noqa: BLE001
        return {}


def _edge(idx="/health"):
    """→ (base, payload) ; 第一个能通的候选。"""
    errs = []
    for base in EDGE_URLS:
        try:
            return base, _get(base + idx, 3.0)
        except Exception as e:                                          # noqa: BLE001
            errs.append("%s(%s)" % (base, type(e).__name__))
    return "", {"_err": "; ".join(errs) or "无候选地址"}


def _active():
    try:
        with open(ACTIVE_J, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                   # noqa: BLE001
        return {}


def _intact_report():
    try:
        with open(INTACT_REPORT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                   # noqa: BLE001
        return {}


def _layers_from_status(st):
    """8796 的 models[] → per-layer 名单 (与模型引擎列表同源)。"""
    out = {}
    for m in (st.get("models") or []):
        if not isinstance(m, dict):
            continue
        ly = str(m.get("layer") or "")
        out.setdefault(ly, []).append(m)
    return out


def build(inv=None):
    st = _status()
    inv = inv if isinstance(inv, dict) else {}
    base, eh = _edge("/health")
    _, emodels = _edge("/models") if base else ("", {})
    act = _active()
    rep = _intact_report()
    pipe = (eh.get("pipeline") or {}) if isinstance(eh, dict) else {}
    pdevs = (pipe.get("devices") or {}) if isinstance(pipe, dict) else {}
    streams = pipe.get("streams") if isinstance(pipe, dict) else None

    items = []

    def add(**kw):
        it = {"status": "idle", "runs": []}
        it.update(kw)
        items.append(it)
        return it

    # ① Intel 端侧 IR 三件 (唯一依据 = edge /models 的 sha16 + pipeline 的 device 归属)
    ir_by_name = {m.get("name"): m for m in (emodels.get("models") or []) if isinstance(m, dict)}
    dev_of = {}
    for dev, d in pdevs.items():
        for nm in ((d or {}).get("models") or []):
            dev_of.setdefault(nm, []).append({"dev": dev, "fps": (d or {}).get("fps"),
                                              "duty_pct": (d or {}).get("duty_pct"),
                                              "streams": (streams or {}).get(dev) if isinstance(streams, dict) else None,
                                              "avg_ms": (d or {}).get("avg_ms")})
    conv = CONVERTERS["intact"]
    src = (rep.get("ckpt") or "")
    parity = {k: (v or {}).get("parity") for k, v in (rep.get("parts") or {}).items()}
    # 端侧 IR 的来源 ckpt 与"在役指针"是否同一份 (口径检查, 不修数据只报出来)
    live_ptr = os.path.join(ROOT, "zmax_data", "stable-wm-cache", "checkpoints", "intact_l4_current", "weights.pt")
    live_src = os.path.realpath(live_ptr) if os.path.exists(live_ptr) else ""
    same_src = bool(src) and bool(live_src) and os.path.realpath(src) == live_src
    add(key="intel:intact", layer="L4", model="INTACT (enc + pred)", role="意图-动作 / 世界模型",
        fmt="IR fp16", kind="intact",
        runs=dev_of.get("intact_enc", []) + [r for r in dev_of.get("intact_pred", []) if r not in dev_of.get("intact_enc", [])],
        ir=[ir_by_name.get(n) for n in ("intact_enc", "intact_pred") if ir_by_name.get(n)],
        source=src, source_sha16=_sha16(src) if src else None,
        source_live=live_src, source_live_sha16=_sha16(live_src) if live_src else None,
        source_same=same_src,
        converter=conv["tool"], chain=conv["chain"], gate=conv["gate"], parity=parity,
        status="inferring" if any(r.get("fps") for r in dev_of.get("intact_enc", [])) else "idle")

    cy = CONVERTERS["yolo"]
    ysrc = os.path.join(ROOT, "models", "yolo_peg_live.pt")
    ysrc_r = os.path.realpath(ysrc) if os.path.exists(ysrc) else ""
    add(key="intel:yolo", layer="L2", model="YOLO 光模块检测", role="检测 (2D→3D 输入)",
        fmt="IR fp16", kind="yolo",
        runs=dev_of.get("yolo_peg_live", []),
        ir=[ir_by_name["yolo_peg_live"]] if ir_by_name.get("yolo_peg_live") else [],
        source=ysrc_r, source_sha16=_sha16(ysrc_r) if ysrc_r else None,
        converter=cy["tool"], chain=cy["chain"], gate=cy["gate"], parity=None,
        status="inferring" if any(r.get("fps") for r in dev_of.get("yolo_peg_live", [])) else "idle")

    # ② 本机 4060 上 torch 直跑的 (L3 SmolVLA / L2 SAM3 原语 / 本机引擎)
    def inv_path(layer):
        """inventory (tools/model_inventory.py --json) 里该层在役行的真实路径 —— 比猜 glob 可靠。"""
        for m in (inv.get("models") or []):
            if isinstance(m, dict) and str(m.get("layer")) == layer and m.get("active"):
                p = str(m.get("realpath") or m.get("path") or "")
                if p and not os.path.isabs(p):
                    p = os.path.join(ROOT, p)
                return os.path.realpath(p) if p and os.path.exists(p) else p
        return ""

    def local_ckpt(pat_list):
        for pat in pat_list:
            for p in sorted(glob.glob(os.path.join(ROOT, pat)), reverse=True):
                if os.path.exists(p):
                    return os.path.realpath(p)
        return ""

    tf = CONVERTERS["torch"]
    l3 = inv_path("L3") or local_ckpt(["zmax_data/outputs/smolvla_lew*/checkpoints/*/pretrained_model",
                                       "zmax_data/outputs/**/pretrained_model", "outputs/**/pretrained_model"])
    for m in (_layers_from_status(st).get("L3") or []):
        if str(m.get("state")) == "candidate":
            continue
        p = str(m.get("path") or "")
        if p and not os.path.isabs(p):
            p = os.path.join(ROOT, p)
        p = os.path.realpath(p) if p and os.path.exists(p) else p
        if not p or not os.path.exists(p):
            p = l3
        add(key="local:L3", layer="L3", model=str(m.get("name") or "SmolVLA + LEW"),
            role="长程规划 / 动作序列", fmt="torch ckpt", kind="torch",
            runs=[{"dev": "4060", "fps": None, "duty_pct": None, "streams": 1, "avg_ms": None}],
            ir=[], source=p, source_sha16=_sha16(p) if p and os.path.isfile(p) else None,
            converter=tf["tool"], chain=tf["chain"], gate=tf["gate"], parity=None,
            status="inferring" if m.get("inferring") else "idle")
        break

    for m in (_layers_from_status(st).get("L5") or []):
        if str(m.get("state")) == "candidate":
            continue
        ap = CONVERTERS["api"]
        add(key="cloud:L5", layer="L5", model=str(m.get("name") or "DeepSeek 视觉规划"),
            note="主路 = api.deepseek.com (scene_vlm.py); 本机 smolvlm 备用权重未转 IR",
            role="场景理解 / 规划 (大模型主路)", fmt="API (无端侧权重)", kind="api",
            runs=[{"dev": "云端", "fps": None, "duty_pct": None, "streams": None, "avg_ms": None}],
            ir=[], source="", source_sha16=None,
            converter=ap["tool"], chain=ap["chain"], gate=ap["gate"], parity=None,
            status="inferring" if m.get("inferring") else "idle")
        break

    # ③ 训练状态 (8796 training[] / 训练进程) —— 逐层标"正在训练"
    tr_layers = set()
    for t in (st.get("training") or []):
        if isinstance(t, dict) and t.get("active"):
            tr_layers.add(str(t.get("layer") or ""))
    for it in items:
        if it["layer"] in tr_layers:
            it["status"] = "training"

    # ④ 转换工具/权重口径自检
    warns = []
    for it in items:
        if it.get("source_same") is False:
            warns.append("%s: 端侧 IR 来源 %s ≠ 在役指针 %s (同一 run 不同 epoch)"
                         % (it["layer"], os.path.basename(str(it.get("source"))),
                            os.path.basename(str(it.get("source_live")))))
        if it["kind"] in ("intact", "yolo") and not it["ir"]:
            warns.append("%s: Intel /models 没报到这份 IR (采集断?)" % it["layer"])
    ok = bool(st) and bool(eh.get("ok"))

    return {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": ok,
            "status_url": STATUS_URL,
            "edge": {"online": bool(eh.get("ok")), "url": base,
                     "streams": streams, "total_fps": pipe.get("total_fps"),
                     "err": eh.get("_err")},
            "items": items, "warns": warns,
            "conv_tools": CONVERTERS}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="模型在哪跑/跑的哪份权重/用什么转的/推理还是训练")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    d = build()
    if a.check:
        bad = []
        for it in d["items"]:
            if it["kind"] in ("intact", "yolo"):
                if not it["ir"]:
                    bad.append("%s: Intel 没报到 IR (采集断?)" % it["key"])
                for x in it["ir"]:
                    if not x.get("sha16"):
                        bad.append("%s/%s: 无 sha16 (无法证明跑的是哪份权重)" % (it["key"], x.get("name")))
                if it.get("runs") and not any(r.get("duty_pct") is not None for r in it["runs"]):
                    bad.append("%s: 有运行设备但没有占空 (推理状态不可判)" % it["key"])
            if not it.get("converter"):
                bad.append("%s: 缺转换工具口径" % it["key"])
        for x in bad:
            print("✗ " + x)
        print("%s 运行信息自检: %d 项, %d 处不合规" % ("✓" if not bad else "✗", len(d["items"]), len(bad)))
        return 0 if (d["ok"] and not bad) else 1
    if a.write:
        os.makedirs(os.path.dirname(OUT_J), exist_ok=True)
        tmp = OUT_J + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, OUT_J)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0 if d["ok"] else 1
    for it in d["items"]:
        runs = " + ".join("%s%s%s" % (r["dev"],
                                      ("×%s" % r["streams"]) if r.get("streams") else "",
                                      (" %.0f%%" % r["duty_pct"]) if isinstance(r.get("duty_pct"), (int, float)) else "")
                          for r in it["runs"]) or "未加载"
        shas = " / ".join("%s:%s" % (x.get("name"), x.get("sha16")) for x in it["ir"]) or "—"
        print("%-3s %-22s %-9s 跑到 %-24s 权重 %-42s 工具 %s"
              % (it["layer"], it["model"][:22], it["status"], runs, shas, (it.get("converter") or "")[:64]))
        if it.get("source"):
            print("      源 %s (sha %s)%s" % (str(it["source"])[-72:], it.get("source_sha16"),
                                             "" if it.get("source_same") in (True, None)
                                             else "  ⚠ 与在役指针不是同一份"))
    for w in d["warns"]:
        print("⚠ " + w)
    print("采集: status=%s edge=%s (%s) → %s" % ("ok" if d["ok"] else "FAIL",
                                                "ok" if d["edge"]["online"] else "FAIL",
                                                d["edge"].get("url") or d["edge"].get("err"), OUT_J))
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
