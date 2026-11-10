# -*- coding: utf-8 -*-
"""ss_vlm — 节点实现正文 (文件名 = 画布节点: ss_vlm)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_vlm   ·   registry key: ss_vlm
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _NodeOut,
    _vlm_ask_async,
    _vlm_brief,
    _vlm_ctx,
    _vlm_encoder_ns,
    _vlm_frame,
)

def node_ss_vlm(ctx):
    """🧠 VLM 通用视觉编码器 — GUI 薄壳 (算法全在 src, 老倪 2026-09-08)

    真实算法: src/lerobot/policies/smolvla_lew/vlm_encoder.py encode_stage() —
    帧 → SmolVLM2 真实前向 → 潜空间 z ∈ R⁹⁶⁰ (首次触发后台加载 ~15s)。
    本壳职责: 取当前阶段真实帧 → 转发 encode_stage → 呈现结果。播放 demo 不跑 (铁律)。"""
    log = ctx.get("log")
    try:
        import numpy as np
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is None or not tr.get("t"):
            # 🎥 无引擎轨迹 (常驻循环 / 没点 ▶) 时,VLM 也必须真跑: 吃 AR 场景当前帧做场景理解。
            #   以前这里直接 return False → 整层 L3 在看戏, 技能编排器只能报「场景理解未就绪」。
            img, _src, _meta = _vlm_frame()
            if img is None:
                if log:
                    log("🧠 VLM: 无引擎轨迹且取不到 AR 帧 — 不假装看过现场")
                return False
            st = _vlm_ask_async("describe", img, _vlm_ctx(ctx), log)
            r = (st or {}).get("result") or {}
            ok = bool(r.get("ok"))
            if log:
                log("🧠 VLM 场景理解 (%s · %s · %sms · frame=%s tick=%s): %s" % (
                    _src, r.get("src") or "未返回", r.get("latency_ms"),
                    _meta.get("frame"), _meta.get("tick"),
                    _vlm_brief(r.get("json")) if ok else (r.get("why") or "无结果")))
            _rb2 = {
                "kind": "scene_vlm", "layer": "L3", "ok": ok, "frame_src": _src,
                "frame": _meta.get("frame"), "frame_age_s": _meta.get("frame_age_s"),
                "src": "src/lerobot/policies/left_right/state_space/scene_vlm.py::SceneVLM.describe",
                "latency_ms": r.get("latency_ms"), "scene": r.get("json"),
            }
            return {"out%d" % _i: dict(_rb2) for _i in range(1, 8)} | dict(_rb2) \
                if "_NodeOut" in globals() else {"out1": r}
        idx = min(int(getattr(mod, "_ss_round", 0) or 0), len(tr["t"]) - 1)
        stage = str(tr["stage"][idx]).replace("阶段 ", "").split("·")[0].strip()
        meta = tr.get("_meta") or {}
        x = np.asarray(tr["x"][idx], dtype=float)
        peg = np.asarray(tr["peg"][idx], dtype=float)
        tgt = np.asarray(tr["target"][idx], dtype=float)
        if log:
            log(f"🧠 VLM 通用视觉编码器 [当前阶段={stage}]: token=图像帧+触觉+检测框")
        # ① 真实编码 (算法在 src): 当前阶段真实帧 → encode_stage
        kf = tr.get("key_frames") or {}
        if kf and stage in kf:
            try:
                from PIL import Image
                _ns = _vlm_encoder_ns()
                cache = getattr(mod, "_vlm_cache", None)
                if cache is None:
                    cache = mod._vlm_cache = {}
                r = _ns["encode_stage"](Image.fromarray(np.asarray(kf[stage])),
                                        stage, cache, meta.get("seed", "?"))
                if r.get("status") == "ok":
                    if log:
                        tag = " (缓存)" if r.get("cached") else " (真实前向, 非演示)"
                        log(f"   ✅ VLM 真实编码 [阶段={stage}]{tag}: {r['model']} · "
                            f"帧 {np.asarray(kf[stage]).shape[1]}x{np.asarray(kf[stage]).shape[0]} "
                            f"→ {r['tokens']} token → z∈R{r['dim']} · "
                            f"|z|={r['z_norm']:.1f} mean={r['z_mean']:.3f} std={r['z_std']:.3f} · "
                            f"top活跃 {r['top5']} · {r['ms']}ms")
                        log(f"   语义: 真实视觉特征 (预训练 SmolVLM 通用编码, 未微调) — "
                            f"与几何潜空间关系由下游世界模型学习")
                elif log:
                    log(f"   ⏳ {r.get('msg', r.get('status'))}")
            except Exception as _e:
                if log:
                    log(f"   ⚠️ VLM 编码异常: {_e}")
        elif log:
            log("   帧源: 本轮轨迹无真实帧 (key_frames 空) — 需 🎥真实化 R1 视觉运行; 引擎快演无帧")
        # ② 几何潜空间对照 (教学注解, GUI 演示层)
        z_vis = np.concatenate([x - tgt, x - peg, [float(tr["grasped"][idx])]])
        if log:
            log(f"   几何 z∈R⁷ (对照): 手→目标 {np.round(z_vis[:3], 4)} m · 手→工件 "
                f"{np.round(z_vis[3:6], 4)} m · 夹持={z_vis[6]:.0f}")
            if meta.get("mode") == "full" or any("AOI" in str(s) for s in tr.get("stage", [])):
                af = np.asarray(meta.get("aoi_focus", [0.12, 0.62, 0.10]), dtype=float)
                log(f"   🔍 场景目标识别: 光模块/插孔 + AOI 光学检测设备 (镜头工位 "
                    f"{np.round(af, 2)}) — 插拔循环后对焦检测")
            if meta.get("aoi_report"):
                _ar = meta["aoi_report"]
                log(f"   📷 AOI 检测报告: {'PASS' if _ar.get('ok') else 'FAIL'} "
                    f"(残余深度 {_ar.get('insert_depth_min_mm')}mm · 力峰 {_ar.get('force_peak')})")
            log("   ⚙️ 真实实现: src/lerobot/policies/smolvla_lew/vlm_encoder.py (encode_stage)")
        # ── 端口 (2026-11-10): 画布 ssvlm.out1..out7 → ssskill/ssdec/ssreason 等 7 条出边,
        #    原实现只 return True ⇒ 全空。交出真算的 z_vis + 帧/阶段/AOI 状态 (无帧时如实标注)。
        _has_fr = bool(kf and stage in kf)
        _vb = {"kind": "scene_vlm", "layer": "L3", "ok": True,
               "idx": int(idx), "stage": str(stage), "has_frames": _has_fr,
               "z_vis": [round(float(v), 6) for v in z_vis],
               "hand_to_target": [round(float(v), 6) for v in z_vis[:3]],
               "hand_to_peg": [round(float(v), 6) for v in z_vis[3:6]],
               "grasped": float(z_vis[6]),
               "aoi_report": (meta.get("aoi_report") or None),
               "note": ("本轮无真实帧 (key_frames 空) ⇒ z_vis 为几何对照, 不是 VLM 编码输出"
                        if not _has_fr else "真帧编码"),
               "src": "src/lerobot/policies/smolvla_lew/vlm_encoder.py::encode_stage"}
        _vp = {"out%d" % _i: dict(_vb) for _i in range(1, 8)}
        _vp.update(_vb)
        return _vp
    except Exception as e:
        if log:
            log(f"⚠️ VLM 编码失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_vlm
