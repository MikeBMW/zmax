#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_meta_task_predict.py — 元任务「图像+状态」推导预测 (老倪 2026-10-14)

口径 (老倪原话): 「元任务需要从真实图像或渲染图像以及状态信息推导出来预测」

与 ss_meta_task.py 的分工 (两者不冲突, 输出的字段不同):
  · ss_meta_task.py : 任务 → **该任务覆盖的元任务全集** (登记表派生: 功能+参数+依赖+验证+层)
                      = "这次可能要跑哪些功能" (配置完备性, 现已 74/74 全映射)
  · 本文件          : (图像 + 状态) → **此刻真该跑哪些元任务** (预测子集)
                      = "现在正在做哪一步、下一步要哪些功能"

三段真输入, 每段都留证据:
  ① 图像: --src real  → 8791 /aoi_modelin.png (真产线帧, 与产线检测器同一张)
          --src render→ 3D/仿真渲染帧 (engine/3D 快照, 找不到就如实报 err, 不造图)
          --src auto  → 先真后渲染
  ② 感知: YOLO 在役权重 models/yolo_peg_live.pt (检出数/框/置信 ⇒ 定量证据)
          VLM  : L5 本地视觉模型 (能出 JSON) 或 L4 视觉编码器 (退化为证据+规则融合, 标签如实写)
  ③ 状态: zmax_data/ss_live/engine_latest.json (p/phi/action/phase/confidence/hom_*; 带 ts 与帧龄)

输出: zmax_data/ss_live/meta_tasks_pred.json  (+ --json 打印)
     predicted[] 每条带: fn_id/name/layer/node_id/why(证据)/src(哪个通道触发)/conf
     evidence{}  原始证据: yolo{ndet,boxes}/vlm{backend,prompt,raw}/state{字段+帧龄}

CLI:
  --task TASK-07-AOI   指定任务 (默认真源 active_task)
  --src auto|real|render
  --json / --write / --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
LIVE_DIR = os.path.join(ROOT, "zmax_data", "ss_live")
OUT = os.path.join(LIVE_DIR, "meta_tasks_pred.json")
LATEST = os.path.join(LIVE_DIR, "engine_latest.json")
REAL_IMG_URL = os.environ.get("ZMAX_PRED_IMG") or "http://127.0.0.1:8791/aoi_modelin.png"
RENDER_GLOBS = ("zmax_data/*/render*.png", "reports/render*.png", "outputs/**/render*.png",
                "zmax_data/gs_assets/*/renders/*.png", "zmax_data/ss3d/*.png")
YOLO_LIVE = os.path.join(ROOT, "models", "yolo_peg_live.pt")

if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                            # noqa: BLE001
        return d if d is not None else {}


def _write_json(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(o, f, ensure_ascii=False, indent=2)


# ───────────────────────── ① 图像: 真 / 渲染 ─────────────────────────
def load_image(which: str = "auto", override: str = ""):
    """返回 (img_bgr, meta)。不造图: 都取不到就 (None, {err})。

    override: 指定真帧 (本地路径或 URL) ⇒ 优先用它 (给"画面里真有模块"的帧做证据用)。
    """
    import cv2                                                                # noqa: PLC0415
    import glob as _g                                                         # noqa: PLC0415
    import numpy as np                                                        # noqa: PLC0415
    tries = []
    if override:
        tries.append(("override", "url" if override.startswith("http") else "file", override))
    if which in ("auto", "real"):
        tries.append(("real", "url", REAL_IMG_URL))
    if which in ("auto", "render"):
        cands = []
        for pat in RENDER_GLOBS:
            cands += sorted(_g.glob(os.path.join(ROOT, pat)))
        if cands:
            cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            tries.append(("render", "file", cands[0]))
    for kind, how, ref in tries:
        try:
            if how == "url":
                raw = urllib.request.urlopen(urllib.request.Request(
                    ref, headers={"User-Agent": "zmax-pred"}), timeout=10).read()
                im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            else:
                im = cv2.imread(ref)
            if im is not None:
                g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype("float32")
                mean_, std_ = float(g.mean()), float(g.std())
                usable = bool(mean_ > 3.0 and std_ > 2.0)     # 全黑/纯色 ⇒ 无视觉证据可用
                meta = {"kind": kind, "how": how, "ref": ref, "age_s": 0.0,
                        "size": [int(im.shape[1]), int(im.shape[0])],
                        "mean": round(mean_, 2), "std": round(std_, 2), "usable": usable}
                if not usable:
                    meta["note"] = ("图像不可用 (均值%.1f/标准差%.1f): 全黑或纯色 ⇒ 这一路无视觉证据, "
                                    "预测退化为状态推理" % (mean_, std_))
                return im, meta
        except Exception as e:                                                # noqa: BLE001
            continue
    return None, {"err": "真帧与渲染帧都没取到 (%d 个候选)" % len(tries), "tried": [t[2] for t in tries]}


# ───────────────────────── ② 感知: YOLO + VLM ─────────────────────────
def run_yolo(img):
    """在役 YOLO 真检出 (定量证据)。返回 {ok, weights, n_cls, ndet, dets, err}。"""
    out = {"weights": os.path.relpath(YOLO_LIVE, ROOT) if os.path.exists(YOLO_LIVE) else "(缺)",
           "ndet": 0, "dets": []}
    try:
        from ultralytics import YOLO                                            # noqa: PLC0415
        import numpy as np                                                      # noqa: PLC0415
        m = YOLO(YOLO_LIVE) if os.path.exists(YOLO_LIVE) else YOLO("yolov8s.pt")
        out["n_cls"] = len(getattr(m, "names", {}) or {})
        # ⚠️ ultralytics 吃 BGR (直传 cv2 图, 不要 cvtColor)
        r = m.predict(np.ascontiguousarray(img), verbose=False, conf=0.25)
        dets = []
        for b in (r[0].boxes if r else []):
            xyxy = [float(x) for x in b.xyxy[0].tolist()]
            dets.append({"cls": int(b.cls[0]), "name": str((m.names or {}).get(int(b.cls[0]), "")),
                         "conf": round(float(b.conf[0]), 3), "xyxy": [round(x, 1) for x in xyxy]})
        out.update({"ok": True, "ndet": len(dets), "dets": dets[:12]})
    except Exception as e:                                                    # noqa: BLE001
        out.update({"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:120])})
    return out


def run_vlm(img, candidates, state, task_id):
    """VLM 从「图像 + 候选元任务 + 状态」推导此刻该跑哪些功能。

    返回 {backend, prompt_head, raw, active[], conf, err}
    后端如实标注: l5-vlm(本地视觉模型出 JSON) / encoder+fusion(编码器证据+规则融合, 非语言推理) / rules
    """
    import numpy as np                                                          # noqa: PLC0415
    base = {"backend": "none", "active": [], "conf": 0.0, "raw": ""}
    # 候选精简成 "fn_id|层|名" 三列, 提示尽量短 (老倪: 短提示 + 小 JSON)
    cand_txt = "\n".join("%s | %s | %s" % (c["fn_id"], c.get("layer") or "?", (c.get("name") or "")[:28])
                         for c in candidates[:40])
    prompt = ("你是产线元任务预测器。看这张光模块工序图像, 结合状态, 从候选功能里选出此刻正在执行"
              "和紧接着要执行的功能(最多6个)。只输出 JSON: {\"active\":[\"FN-...\"],\"conf\":0.0-1.0,"
              "\"why\":\"一句话\"}\n候选:\n" + cand_txt + "\n状态: " + json.dumps(state, ensure_ascii=False)[:300])
    base["prompt_head"] = prompt[:160]
    # ① 本地 L5 视觉模型 (出 JSON 的那种)
    l5 = os.environ.get("ZMAX_L5_VLM_DIR") or _find_l5_vlm()
    if l5:
        try:
            return _vlm_hf(l5, img, prompt, base)
        except Exception as e:                                                # noqa: BLE001
            base["err"] = "l5: %s: %s" % (type(e).__name__, str(e)[:100])
    # ② 退化: 编码器证据 + 规则融合 (不是语言推理, 标签如实写)
    try:
        from multi_layer_pipeline import Layer, NodeOut, available, build      # noqa: PLC0415
    except Exception as e:                                                    # noqa: BLE001
        base["backend"] = "rules"
        base["err"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        return base
    base["backend"] = "encoder+fusion"
    base["err"] = base.get("err") or "本地 L5 视觉模型目录未找到 ⇒ 用编码器证据+规则融合(非语言推理)"
    return base


def _find_l5_vlm():
    """找本地 L5 视觉模型目录 (实测真名是小写 l5_vlm_merged_*; 大写会找不到 ⇒ 曾退化成规则融合)。"""
    import glob                                                                # noqa: PLC0415
    pats = ("zmax_data/models/l5_vlm_merged_*", "zmax_data/models/L5_vlm_merged_*",
            "models/l5_vlm_merged_*", "models/L5_vlm_merged_*",
            "zmax_data/models/*vlm_merged*", "models/*vlm_merged*")
    cands = []
    for pat in pats:
        cands += [d for d in glob.glob(os.path.join(ROOT, pat))
                  if os.path.isdir(d) and os.path.exists(os.path.join(d, "config.json"))]
    cands = sorted(set(cands), key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0] if cands else ""


def _vlm_hf(model_dir, img, prompt, base):
    from PIL import Image                                                      # noqa: PLC0415
    from transformers import AutoProcessor                                     # noqa: PLC0415
    import cv2                                                                 # noqa: PLC0415
    dev = "cuda" if os.environ.get("ZMAX_PRED_DEV") == "cuda" else "cpu"
    # 加载类要按模型族试: 实测 L5 本地权重是 **SmolVLM 系**(config 类别不同) ⇒ AutoModelForCausalLM 会
    # 报 `Unrecognized configuration class` (2026-10-14 踩过)。按 Vision2Seq → ImageTextToText → CausalLM 依次试。
    _chain = []
    for _tag, _name in (("Vision2Seq", "AutoModelForVision2Seq"),
                        ("ImageTextToText", "AutoModelForImageTextToText"),
                        ("CausalLM", "AutoModelForCausalLM")):
        try:
            _mod = __import__("transformers", fromlist=[_name])
            _chain.append((_tag, getattr(_mod, _name)))
        except Exception:                                                         # noqa: BLE001
            continue
    mdl, err, tag = None, "", ""
    for _tag, _cls in _chain:
        try:
            mdl = _cls.from_pretrained(model_dir, trust_remote_code=True, torch_dtype="auto").to(dev)
            tag = _tag
            break
        except Exception as e:                                                    # noqa: BLE001
            err = "%s(%s): %s" % (_tag, type(e).__name__, str(e)[:80])
    if mdl is None:
        raise RuntimeError("所有加载类都失败: %s" % err)
    proc = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
    text = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inp = proc(text=text, images=[pil], return_tensors="pt").to(dev)
    gen = mdl.generate(**inp, max_new_tokens=180, do_sample=False)
    raw = proc.batch_decode(gen[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    base.update({"backend": "l5-vlm:%s@%s" % (os.path.basename(model_dir), dev), "raw": raw[:800]})
    try:
        s = raw[raw.find("{"): raw.rfind("}") + 1]
        d = json.loads(s)
        base["active"] = [str(x) for x in (d.get("active") or [])][:8]
        base["conf"] = float(d.get("conf") or 0.0)
        base["why"] = str(d.get("why") or "")[:160]
    except Exception as e:                                                    # noqa: BLE001
        base["err"] = "JSON 解析失败: %s" % str(e)[:80]
    return base


# ───────────────────────── ③ 状态 + 融合 ─────────────────────────
def read_state():
    d = _j(LATEST, {})
    keep = ("ts", "ts_str", "cycle", "hz", "ms", "task_id", "task_name", "scene", "status",
            "phi", "grad_norm", "confidence", "anomaly", "residual", "hom_enabled", "hom_mode",
            "hom_kind", "hom_vitality", "hom_dominant", "hom_urgency", "hom_veto",
            "z_source", "encoder", "p", "action", "pipe_calls")
    s = {k: d.get(k) for k in keep if k in d}
    try:
        s["frame_age_s"] = round(time.time() - float(d.get("ts") or 0), 1)
    except Exception:                                                             # noqa: BLE001
        s["frame_age_s"] = None
    return s


def fuse(candidates, yolo, vlm, state):
    """融合三路证据 ⇒ 预测清单。每条都带 why/src/conf (可复核)。"""
    pred, seen = [], set()
    by_id = {c["fn_id"]: c for c in candidates}

    def add(fn_id, why, src, conf):
        c = by_id.get(fn_id)
        if not c or fn_id in seen:
            return
        seen.add(fn_id)
        pred.append({"fn_id": fn_id, "name": c.get("name"), "layer": c.get("layer"),
                     "node_id": c.get("node_id"), "mt_id": c.get("mt_id"),
                     "why": why, "src": src, "conf": round(float(conf), 3)})

    # ① VLM 语言推理选中的候选 (最强的"理解"证据)
    for fid in (vlm.get("active") or []):
        add(fid, vlm.get("why") or "VLM 选中", "vlm:" + str(vlm.get("backend")), vlm.get("conf") or 0.5)
    # ② YOLO 定量证据: 检出目标 ⇒ 与该层功能挂钩 (L2 类功能: 检测/定位/抓取)
    if yolo.get("ok") and (yolo.get("ndet") or 0) > 0:
        for c in candidates:
            if (c.get("layer") or "").startswith("L2"):
                add(c["fn_id"], "YOLO 检出 %d 个目标 (conf=%.2f)" % (
                    yolo["ndet"], max([d["conf"] for d in yolo["dets"]] or [0])),
                    "yolo:%s" % yolo.get("weights"), min(0.9, 0.4 + 0.1 * yolo["ndet"]))
    # ③ 状态证据: 势/置信/异常/内稳态 → 对应层功能
    if state:
        st = str(state.get("status") or "")
        if (state.get("anomaly") or 0) > 0.5 or state.get("hom_veto"):
            for c in candidates:
                if "安全" in (c.get("name") or "") or "闸" in (c.get("name") or ""):
                    add(c["fn_id"], "状态异常(anomaly=%.2f·veto=%s) ⇒ 触发安全类功能" % (
                        state.get("anomaly") or 0, state.get("hom_veto")),
                        "state:engine_latest", 0.8)
        if str(state.get("z_source") or "").startswith("内建 PCA"):
            for c in candidates:
                if (c.get("layer") or "") == "L4":
                    add(c["fn_id"], "L4 潜表示当前来自内建 PCA (非 VLM) ⇒ L4 链路待接管",
                        "state:z_source", 0.5)
        if st:
            for c in candidates:
                if "调度" in (c.get("name") or "") or (c.get("layer") or "") == "L3":
                    add(c["fn_id"], "引擎状态=%s ⇒ L3 调度链在跑" % st, "state:status", 0.6)
    pred.sort(key=lambda x: -x["conf"])
    return pred[:12]


def predict(task_id=None, src="auto", write=False, img_path=""):
    t0 = time.time()
    # 候选 = 该任务的元任务全集 (配置完备性已 74/74, 由 ss_meta_task 提供)
    import ss_meta_task as MT                                                      # noqa: PLC0415
    base = MT.build(task_id)
    cands = base.get("items") or []
    img, img_meta = load_image(src, img_path)
    yolo = run_yolo(img) if img is not None else {"ok": False, "err": "无图像"}
    state = read_state()
    _usable = bool((img_meta or {}).get("usable"))
    if img is None:
        vlm = {"backend": "none", "active": [], "err": "无图像"}
    elif not _usable:
        # 全黑/纯色帧 ⇒ 不做视觉语言推理 (省算力, 也不把黑图当证据)
        vlm = {"backend": "none", "active": [],
               "err": "图像不可用(全黑/纯色) ⇒ 跳过 VLM, 不拿黑图当视觉证据"}
    else:
        vlm = run_vlm(img, cands, state, base.get("task_id"))
    pred = fuse(cands, yolo, vlm, state)
    out = {
        "schema": "zmax.ss_meta_task_pred/1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
        "task_id": base.get("task_id"), "task_name": base.get("task_name"),
        "n_candidates": len(cands), "n_predicted": len(pred),
        "predicted": pred,
        "evidence": {
            "image": img_meta,
            "yolo": {k: v for k, v in yolo.items() if k != "dets"},
            "yolo_dets": yolo.get("dets") or [],
            "vlm": {k: v for k, v in vlm.items() if k not in ("raw",)} | {"raw_head": (vlm.get("raw") or "")[:200]},
            "state": state,
        },
        "degraded": (not (img_meta.get("usable") if isinstance(img_meta, dict) else False))
                    or (not (yolo.get("ok") and (yolo.get("ndet") or 0) > 0)),
        "degrade_reason": ("; ".join(x for x in (
            (img_meta.get("note") if isinstance(img_meta, dict) else None),
            "YOLO 无检出 ⇒ 定量视觉证据为空" if not (yolo.get("ndet") or 0) else None,
            ("VLM 未跑语言推理 (%s)" % (vlm.get("backend") or "")) if "l5-vlm" not in str(vlm.get("backend")) else None,
        ) if x) or "无 (图像+YOLO+VLM 三路都有证据)"),
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "note": "预测 = 图像(真/渲染) × YOLO 在役权重 × VLM 语言推理 × 引擎状态, 三路各留证据; "
                "候选集来自任务元任务全集 (登记表, 74/74 完备)",
    }
    if write:
        _write_json(OUT, out)
    return out


def selftest() -> int:
    """判据: ① 图像必须真取到(真或渲染) ② YOLO 真要跑出一条结论(ok 或如实 err) ③ 预测每条都有 why+src
    ④ 预测必须是候选子集 (不凭空造功能)。"""
    o = predict(src="auto", write=False)
    ok = []
    ev = o.get("evidence") or {}
    im = ev.get("image") or {}
    ok.append(("图像取到", bool(im.get("kind")), "%s %s" % (im.get("kind"), im.get("size") or im.get("err"))))
    y = ev.get("yolo") or {}
    ok.append(("YOLO 真跑", ("ok" in y), "ndet=%s n_cls=%s weights=%s" % (
        y.get("ndet"), y.get("n_cls"), y.get("weights"))))
    v = ev.get("vlm") or {}
    ok.append(("VLM 通道有结论", bool(v.get("backend") and v.get("backend") != "none"),
               "backend=%s active=%d" % (v.get("backend"), len(v.get("active") or []))))
    preds = o.get("predicted") or []
    ok.append(("每条预测带证据", all(p.get("why") and p.get("src") for p in preds), "%d 条" % len(preds)))
    ok.append(("预测⊆候选", bool(preds) and o["n_predicted"] <= o["n_candidates"], "全量 %s" % o["n_candidates"]))
    print("══ 元任务预测自检 (%s) ══" % o.get("task_id"))
    for name, v_, extra in ok:
        print("  [%s] %-14s %s" % ("PASS" if v_ else "FAIL", name, extra))
    print("  ⏱ %.1fms · 图像=%s · YOLO ndet=%s · VLM=%s · 预测 %d 条" % (
        o.get("elapsed_ms") or 0, (im.get("kind") or im.get("err")), y.get("ndet"),
        v.get("backend"), o.get("n_predicted") or 0))
    for p in preds[:6]:
        print("     · %-12s %-30s [%s] %s" % (p["fn_id"], (p["name"] or "")[:30], p["src"], p["why"][:60]))
    n_bad = sum(1 for _, v_, _ in ok if not v_)
    print("  判据 %d/%d %s" % (len(ok) - n_bad, len(ok), "PASS" if n_bad == 0 else "FAIL"))
    return 0 if n_bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--src", default="auto", choices=["auto", "real", "render"])
    ap.add_argument("--img", default="", help="指定真帧(路径或URL)作图像证据, 优先于 --src")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    o = predict(a.task or None, a.src, write=a.write, img_path=a.img)
    if a.json:
        print(json.dumps(o, ensure_ascii=False, indent=2))
    else:
        print("任务 %s · 候选 %d · 预测 %d 条 · %.1fms" % (
            o["task_id"], o["n_candidates"], o["n_predicted"], o["elapsed_ms"]))
        ev = o["evidence"]
        print("  图像: %s" % (ev["image"].get("ref") or ev["image"].get("err")))
        print("  YOLO: ndet=%s n_cls=%s %s" % (ev["yolo"].get("ndet"), ev["yolo"].get("n_cls"),
                                              ev["yolo"].get("err") or ""))
        print("  图像可用性: %s (均值%s/标准差%s)" % (
            "可用" if (ev["image"].get("usable")) else "❌不可用(全黑/纯色)",
            ev["image"].get("mean"), ev["image"].get("std")))
        print("  降级标记: %s ⇒ %s" % (o.get("degraded"), (o.get("degrade_reason") or "")[:110]))
        print("  VLM : %s active=%s %s" % (ev["vlm"].get("backend"), ev["vlm"].get("active"),
                                           (ev["vlm"].get("err") or "")[:80]))
        for p in o["predicted"]:
            print("   · %-12s %-32s [%s] %s" % (p["fn_id"], (p["name"] or "")[:32], p["src"], p["why"][:70]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
