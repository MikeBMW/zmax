#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 基础感知链路 (真机, 每帧真执行): 🎯 YOLO → 🧩 SAM3(框提示, 同帧) → 掩膜→base 3D

链路 (全部真实件, 无占位值):
  ① 取真机帧       tools/ss_yolo_on_real.pick_frame()  (产线 RealSense/臂上 D405, 带帧龄+来源标签)
  ② YOLO 定位      models/yolo_peg_live.pt (真机在役指针) → 框 + conf
  ③ 填画布缓存     _YOLO_CACHE{det2d, img_det_bgr, img_src}  ← 与画布节点**同一份缓存契约**
  ④ 🧩 节点真跑     runtime.execute_node_logic(画布节点)     ← 与 GUI 双击/▶运行**同一入口**
                  节点把 YOLO 框 + **同帧原图** POST 给常驻分割服务 8796
  ⑤ 掩膜 → 3D      mask_3d (深度 + 手眼 + 实时 TCP) → base 中心/足印/朝向
  ⑥ 取证           叠加图 PNG (YOLO 框 + SAM3 掩膜 + 状态横幅) + JSON 回执

用法:
  ./gui-venv311/bin/python tools/l2_perception_chain.py                # 真机活帧
  ./gui-venv311/bin/python tools/l2_perception_chain.py --image X.jpg  # 指定图 (自检用)
  ./gui-venv311/bin/python tools/l2_perception_chain.py --prompt-src text   # 退回文本概念提示
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DEFAULT = REPO / "reports" / "l2_perception_chain"


def _font(sz):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:                                                   # noqa: BLE001
            continue
    return ImageFont.load_default()


class _Shim:
    """runtime.execute_node_logic 的调用方外壳 (GUI 里是画布 widget: 提供 _log)"""
    _trace_nodes = False

    def __init__(self):
        self.lines: list[str] = []

    def _log(self, msg):
        self.lines.append(str(msg))
        print(str(msg), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="", help="指定图片 (不给就取真机活帧)")
    ap.add_argument("--conf", type=float, default=float(os.environ.get("SS_YOLO_CONF", "0.4")))
    ap.add_argument("--boxes", default="", help="上游给的框 (x1,y1,x2,y2[;x1,y1,x2,y2]) —— YOLO 检不出时用它, 不伪造 conf")
    ap.add_argument("--labels", default="upstream", help="--boxes 的标签 (逗号分隔)")
    ap.add_argument("--live-3d-s", type=float, default=3.0, help="帧龄超过这个秒数就不解 3D (深度/TCP 与旧帧对不上)")
    ap.add_argument("--seg-threshold", type=float, default=0.5, help="SAM3 实例分数阈值 (默认 0.5, 与服务同口径)")
    ap.add_argument("--prompt-src", default="auto", choices=["auto", "yolo", "text"],
                    help="auto/yolo=YOLO 框提示 (默认) · text=L5 文本概念")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    sys.path.insert(0, str(REPO / "tools"))
    sys.path.insert(0, str(REPO / "src"))
    os.chdir(REPO)

    import numpy as np
    from PIL import Image, ImageDraw
    import ss_yolo_on_real as yor                     # 真机 YOLO 入口 (同一份权重指针/取帧纪律)

    # ── ① 取帧 ────────────────────────────────────────────────────────────────
    if a.image:
        path, age, kind = a.image, None, "test"
    else:
        path, age, kind = yor.pick_frame()
    if not path:
        print("⛔ 取不到真机帧 (pick_frame 全候选不可用)")
        return 3
    im = Image.open(path).convert("RGB")
    kind = kind or "unknown"
    rgb = np.asarray(im)
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])       # ⚠️ ultralytics 吃 BGR
    frame_md5 = hashlib.md5(bgr.tobytes()).hexdigest()
    print(f"📷 帧: {os.path.basename(path)} {im.width}x{im.height} 来源={yor._SRC_LABEL.get(kind, kind)} "
          f"帧龄={'--' if age is None else '%.1fs' % age} bgr_md5={frame_md5[:12]}")

    # ── ② YOLO 定位 (真机在役权重) ─────────────────────────────────────────────
    t0 = time.time()
    res = yor._model().predict(bgr, imgsz=yor.IMGSZ, conf=a.conf, verbose=False)[0]
    t_yolo = (time.time() - t0) * 1000
    names = res.names if isinstance(res.names, dict) else {i: n for i, n in enumerate(res.names)}
    det2d = {}
    for b in res.boxes:
        cls = names.get(int(b.cls[0]), str(int(b.cls[0])))
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
        det2d[cls] = {"box": [x1, y1, x2, y2], "conf": float(b.conf[0]),
                      "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2}
    print(f"🎯 YOLO: {len(det2d)} 目标 · {t_yolo:.0f}ms · " +
          (" ".join(f"{k} conf={v['conf']:.2f} box={[round(x,1) for x in v['box']]}" for k, v in det2d.items()) or "无检出") +
          f"  (权重 {os.path.basename(yor.WEIGHTS)})")

    # 上游给的框 (YOLO 检不出时的合法来源: 示教/标定/PLC 区域框; **不伪造 conf**)
    if not det2d and a.boxes:
        labs = [s.strip() for s in a.labels.split(",") if s.strip()]
        for i, s in enumerate([x for x in a.boxes.split(";") if x.strip()]):
            bb = [float(v) for v in s.split(",")]
            nm = labs[i] if i < len(labs) else f"upstream{i}"
            det2d[nm] = {"box": bb, "conf": None, "cx": (bb[0] + bb[2]) / 2, "cy": (bb[1] + bb[3]) / 2,
                         "src": "upstream"}
        print(f"   ↳ YOLO 本帧无检出 ⇒ 用上游给的 {len(det2d)} 个框 (conf=-- , 不伪造)")

    # 3D 前置: 帧必须**实时** (旧帧 + 当前深度/当前 TCP = 对不上的假 3D)
    live = (a.image == "") and (age is not None) and (age <= a.live_3d_s)
    if a.image:
        print(f"   ⚠️ 指定图片非实时帧 ⇒ 本帧不解 3D (深度/TCP 与它不同时刻, 解出来是假数)")

    # ── ③ 填画布节点缓存 (契约: det2d / img_det_bgr / img_src) ─────────────────
    from lerobot.engineering import runtime
    from lerobot.engineering.nodes import library as L
    src_tag = "real:arm" if kind in ("real", "stale") else f"real:{kind}"   # 产线 RealSense = 臂上 D405
    L._YOLO_CACHE.update({"det2d": det2d, "img": rgb, "img_det_bgr": bgr, "img_src": src_tag})
    print(f"   缓存已填: det2d={len(det2d)} 项 · img_src={src_tag} · img_det_bgr={bgr.shape}")

    # ── ④ 🧩 画布节点真跑 (GUI 同一入口) ───────────────────────────────────────
    node = {"name": "🧩 开放词汇分割 (SAM3 分割anything)",
            "params": {"prompt_src": a.prompt_src, "cam": "arm", "three_d": bool(live),
                       "seg_threshold": a.seg_threshold}}
    shim = _Shim()
    ok = runtime.execute_node_logic(shim, node, label="L2 链 · SAM3 框提示")
    seg = dict(L._SEG_CACHE)
    inst = (seg.get("res") or {}).get("instances") or []
    mask3d = seg.get("mask3d") or {}
    print(f"🧩 SAM3: 节点返回={ok} · 提示={seg.get('prompt')} · 实例={len(inst)} · 掩膜3D={len(mask3d)} 组")

    # ── ⑤ 叠加图 + 回执 ──────────────────────────────────────────────────────
    dr = ImageDraw.Draw(im, "RGBA")
    for k, v in det2d.items():
        x1, y1, x2, y2 = v["box"]
        dr.rectangle([x1, y1, x2, y2], outline=(255, 210, 0, 255), width=2)
        _cf = "--" if v.get("conf") is None else f"{v['conf']:.2f}"
        dr.text((x1 + 3, max(0, y1 - 14)), f"YOLO {k} {_cf}", font=_font(13), fill=(255, 210, 0, 255))
    for it in inst:
        sel = it.get("selected")
        for poly in it.get("polys") or []:
            pts = [tuple(p) for p in poly]
            dr.polygon(pts, outline=((0, 255, 128, 255) if sel else (255, 92, 200, 110)))
            dr.line(pts + [pts[0]], fill=((0, 255, 128, 255) if sel else (255, 92, 200, 110)),
                    width=(3 if sel else 1))
    import urllib.request
    try:
        h = json.loads(urllib.request.urlopen("http://127.0.0.1:8796/health", timeout=6).read())
        seg_mode = ("基座+适配器" if h.get("adapter") else "官方基座(默认档)") + f" · {'已加载' if h.get('loaded') else '未加载'}"
    except Exception as e:                                                   # noqa: BLE001
        seg_mode = f"服务不可达({type(e).__name__})"
    lines = [
        f"L2 基础感知: 🎯YOLO({os.path.basename(yor.WEIGHTS)}) → 🧩SAM3框提示({seg_mode})",
        f"源={yor._SRC_LABEL.get(kind, kind)} · 帧龄={'--' if age is None else '%.1fs' % age} · "
        f"抓帧 {time.strftime('%m-%d %H:%M:%S')} · bgr_md5={frame_md5[:10]}",
        f"YOLO {len(det2d)} 目标 {t_yolo:.0f}ms → SAM3 实例 {len(inst)} · {seg.get('dt_ms', 0):.0f}ms(端到端) · 掩膜3D {len(mask3d)} 组",
    ]
    for k, v in mask3d.items():
        lines.append(f"  [{k}] base=({v['center_base'][0]:.3f},{v['center_base'][1]:.3f},{v['center_base'][2]:.3f})m "
                     f"z={v['z_mm']:.0f}mm 足印={v['xy_size_mm'][0]:.1f}×{v['xy_size_mm'][1]:.1f}mm yaw={v['yaw_deg']:.1f}° "
                     f"面积={v['area_px']}px score={v['score']:.2f}")
    bh = 20 * len(lines) + 10
    dr.rectangle([0, 0, im.width, bh], fill=(0, 0, 0, 200))
    for i, ln in enumerate(lines):
        dr.text((7, 5 + i * 20), ln, font=_font(15), fill=(255, 255, 255, 255))

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S") + (f"_{a.tag}" if a.tag else "")
    png = outdir / f"l2_chain_{ts}.png"
    im.save(png)
    receipt = {"t": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"), "prompt_src": a.prompt_src,
               "live_frame": bool(live), "boxes_source": ("yolo" if any(
                   v.get("src") != "upstream" for v in det2d.values()) else
                   ("upstream" if det2d else "none")),
               "frame": {"file": path, "source_kind": kind, "source_label": yor._SRC_LABEL.get(kind, kind),
                         "frame_age_s": age, "size": [im.width, im.height], "bgr_md5": frame_md5},
               "yolo": {"weights": yor.WEIGHTS, "imgsz": yor.IMGSZ, "conf_th": a.conf,
                        "ms": round(t_yolo, 1), "n": len(det2d),
                        "dets": {k: {"box": [round(x, 1) for x in v["box"]],
                                     "conf": (None if v.get("conf") is None else round(v["conf"], 3)),
                                     "src": v.get("src", "yolo")}
                                 for k, v in det2d.items()}},
               "sam3": {"service": "127.0.0.1:8796", "mode": seg_mode, "node_ok": ok,
                        "prompt": seg.get("prompt"), "dt_ms": seg.get("dt_ms"),
                        "n_instances": len(inst),
                        "instances": [{"label": it.get("label"), "score": it.get("score"),
                                       "area_px": it.get("area_px"), "iou_yolo": it.get("iou_yolo"),
                                       "selected": it.get("selected"),
                                       "box_xyxy": [round(float(x), 1) for x in (it.get("box_xyxy") or [])],
                                       "n_polys": len(it.get("polys") or []),
                                       "c3d": it.get("c3d")} for it in inst],
                        "mask3d": mask3d},
               "node_log": shim.lines, "png": str(png)}
    js = outdir / f"l2_chain_{ts}.json"
    js.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 叠加图: {png}\n✅ 回执:   {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
