# -*- coding: utf-8 -*-
"""ss_seg — 节点实现正文 (文件名 = 画布节点: ss_seg)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_seg   ·   registry key: ss_seg
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _SEG_CACHE,
    _SEG_DEFAULT_TEXTS,
    _SEG_URL,
    _YOLO_CACHE,
    _seg_match_labels,
    _seg_pick_per_box,
    _seg_yolo_prompt,
    os,
    time,
)

def node_ss_seg(ctx):
    """🧩 开放词汇分割 (SAM3 分割anything) — 真实执行: 一帧 + 提示 → 所有实例掩膜(像素级)

    提示有两种来源 (**L2 内链两条, 都不自造数据**):
      ① **YOLO 框提示 (默认, `prompt_src=yolo|auto`)**: 取 🎯 YOLO 目标检测缓存的框 + **同帧原图** →
         每个目标出**像素级掩膜**(框只给"在哪", 掩膜才给"轮廓/边界/面积/质心") + 掩膜→base 3D。
         ⇒ L2 基础感知: **YOLO 定位(快/固定类) → SAM3 分割细化(轮廓/开放词汇)**。
      ② **文本概念提示 (`prompt_src=text`)**: 概念词由 L5 给 (本节点不自造概念); 实测真机域中文=0 实例、
         英文只有部分词命中 ⇒ 兜底用。
    真执行: POST 常驻分割服务 /seg (算法内核 src/lerobot/policies/sam3_seg/, 调用方 tools/sam3_seg.py)
    返回: 每实例 掩膜多边形/面积/分数, 写进叠加规格 origin='seg' (kind=mask) → 叠加页/画布可见
    ⚠️ 掩膜→3D 只对**臂上相机**成立: 仿真渲染帧 ⇒ 如实拒答(不拿真机手眼套仿真); 服务没起 → 如实报"""
    log = ctx.get("log")
    try:
        import json as _json
        import urllib.request as _ur
        params = ctx.get("params") or {}
        src = str(params.get("prompt_src") or os.environ.get("ZMAX_SEG_PROMPT_SRC", "auto")).lower()
        cam = params.get("cam") or os.environ.get("ZMAX_SEG_CAM", "arm")
        boxes = labels = frame_b64 = ysrc = None
        if src in ("auto", "yolo"):
            boxes, labels, frame_b64, ysrc = _seg_yolo_prompt()
        if boxes:
            # ① YOLO 框提示: 一次前向喂多个框 (框 = 视觉提示; 文本用中性词 "object" 当占位标签,
            #    实例再按 IoU 贴回 YOLO 类名)。3D 只看帧来源: 只对**臂上相机**解 (仿真帧如实拒答)。
            #    ⚠️ 实测: 同一组框会返回**多个候选掩膜** (阈值 0.5 下也可能 >1 个), 逐框取分数最高者为目标。
            real_arm = (ysrc == "real:arm")
            payload_obj = {"image_b64": frame_b64, "boxes": boxes, "texts": ["object"],
                           "threshold": float(params.get("seg_threshold", 0.5)),
                           "three_d": bool(params.get("three_d", True)) and real_arm,
                           "write_spec": True, "cam": (cam if real_arm else "local"),
                           "cam_name": (cam if real_arm else "local"),
                           "note": "L2 内链: 🎯YOLO框 → 🧩SAM3掩膜 (%s)" % (ysrc or "?")}
        else:
            texts = params.get("texts") or params.get("prompt") or _SEG_DEFAULT_TEXTS
            if isinstance(texts, str):
                texts = [t.strip() for t in texts.split(",") if t.strip()]
            payload_obj = {"cam": cam, "texts": texts, "three_d": bool(params.get("three_d", True)),
                           "write_spec": True, "cam_name": cam,
                           "note": "画布节点 node_ss_seg (L2 开放词汇分割 · 文本概念)"}
        payload = _json.dumps(payload_obj).encode()
        req = _ur.Request(_SEG_URL + "/seg", data=payload, headers={"Content-Type": "application/json"})
        t0 = time.time()
        with _ur.urlopen(req, timeout=float(params.get("timeout", 120))) as r:
            res = _json.loads(r.read())
        dt = (time.time() - t0) * 1000
        if not res.get("ok"):
            if log:
                log(f"⚠️ 开放词汇分割: 服务返回失败 — {res.get('err') or res}")
            return False
        if boxes:
            # 贴回 YOLO 类名 (几何配对, 不假设返回顺序) + 逐框选目标掩膜 + 掩膜级 3D 落缓存供下游用
            insts = res.get("instances") or []
            pairs = _seg_match_labels(insts, boxes, labels)
            picked = _seg_pick_per_box(insts, pairs)
            for i, (it, pr) in enumerate(zip(insts, pairs)):
                it["label"] = pr["box_src"]
                it["iou_yolo"] = pr["iou_yolo"]
                it["selected"] = any(i == pi for pi, _ in picked.values())
            mask3d = {}
            for j, (i, pr) in picked.items():
                it = insts[i]
                c3 = it.get("c3d") or {}
                if c3.get("ok"):
                    mask3d[pr["box_src"]] = {"center_base": c3["center_base"], "z_mm": c3["z_mm"],
                                             "xy_size_mm": c3["xy_size_mm"], "yaw_deg": c3["yaw_deg"],
                                             "area_px": it.get("area_px"), "score": it.get("score"),
                                             "iou_yolo": pr["iou_yolo"], "src": ysrc, "at": time.time()}
            _SEG_CACHE.update({"res": res, "at": time.time(), "prompt": "yolo", "boxes": boxes,
                               "labels": labels, "src": ysrc, "mask3d": mask3d, "dt_ms": dt,
                               "n_candidates": len(insts), "n_selected": len(picked),
                               "picked": {labels[j]: i for j, (i, _) in picked.items()}})
            _YOLO_CACHE["seg_masks"] = {"instances": insts, "at": time.time(),
                                        "n_yolo_boxes": len(boxes), "n_selected": len(picked), "src": ysrc}
            _YOLO_CACHE["mask3d"] = mask3d
        else:
            _SEG_CACHE.update({"res": res, "at": time.time(), "prompt": "text",
                               "texts": payload_obj.get("texts"), "cam": cam, "dt_ms": dt})
        if log:
            _n = res.get("count")
            if boxes:
                log(f"🧩 L2 内链 🎯YOLO框→🧩SAM3掩膜 (真实推理): 帧={res.get('src')} · "
                    f"{res.get('ms')}ms(服务) / {dt:.0f}ms(端到端) · YOLO 框 {len(boxes)} 个 → "
                    f"候选掩膜 {_n} 个 → 选中目标 {_SEG_CACHE.get('n_selected')} 个 · 帧来源={ysrc}")
                for it in (res.get("instances") or [])[:8]:
                    c3 = it.get("c3d") or {}
                    extra = (f" · base中心=({c3['center_base'][0]:.3f},{c3['center_base'][1]:.3f},{c3['center_base'][2]:.3f})，"
                             f"z={c3['z_mm']:.0f}mm 足印={c3['xy_size_mm'][0]:.1f}×{c3['xy_size_mm'][1]:.1f}mm "
                             f"yaw={c3['yaw_deg']:.1f}°"
                             if c3.get("ok") else (f" · 3D拒答: {c3.get('reason')}" if c3 else ""))
                    log(f"   {'★' if it.get('selected') else '·'} [{it.get('label')}] (贴回YOLO IoU={it.get('iou_yolo')}) "
                        f"score={it.get('score'):.3f} 面积={it.get('area_px')}px 轮廓={len(it.get('polys') or [])} 圈{extra}")
            else:
                log(f"🧩 开放词汇分割 (SAM3 真实推理 · 文本概念): 概念={payload_obj.get('texts')} · 帧={res.get('src')} · "
                    f"{res.get('ms')}ms(服务) / {dt:.0f}ms(端到端) · 实例 {_n} 个")
                for it in (res.get("instances") or [])[:8]:
                    c3 = it.get("c3d") or {}
                    extra = (f" · base中心=({c3['center_base'][0]:.3f},{c3['center_base'][1]:.3f},{c3['center_base'][2]:.3f})，"
                             f"z={c3['z_mm']:.0f}mm 尺寸={c3['xy_size_mm'][0]:.1f}×{c3['xy_size_mm'][1]:.1f}mm"
                             if c3.get("ok") else (f" · 3D拒答: {c3.get('reason')}" if c3 else ""))
                    log(f"   {it.get('label')}: score={it.get('score'):.3f} 面积={it.get('area_px')}px "
                        f"轮廓={len(it.get('polys') or [])} 圈{extra}")
            if _n:
                log("   → 已写入叠加规格 origin='seg' (kind=mask), 叠加页/工位总览刷新即见(品红轮廓+半透明填充)")
            else:
                log("   ℹ️ 这一帧没找到目标(不是执行失败) — 文本概念要现场试(英文); 已把该相机的 seg 掩膜清空")
        # 口径: 链跑通(服务返回 ok) 就算成功 —— 0 个实例是**合法结果**, 不能当失败报(GUI 播放会误判)
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 开放词汇分割真实执行失败: {type(e).__name__}: {e}")
            if isinstance(e, OSError) or "refused" in str(e).lower() or "timed out" in str(e).lower():
                log("   服务未在跑? 先起: python tools/sam3_seg.py --serve --port 8796 "
                    "(SAM3 权重 ~1.7GB, 显存独占)")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_seg
