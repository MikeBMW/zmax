# -*- coding: utf-8 -*-
"""ss_sensor — 节点实现正文 (文件名 = 画布节点: ss_sensor)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_s1   ·   registry key: ss_sensor
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _SS_STATE,
    _YOLO_CACHE,
    _seg_mask3d_obs,
    _ss_ensure_obs43,
    _ss_env_obs,
    _ss_import,
    _ss_tactile_mod,
    os,
)

def node_ss_s1(ctx):
    """融合定位建图 — 📡 视觉(YOLO→2D→3D) ⊕ 触觉(4D) ⊕ 外观质量: fuse_sensors() → 统一状态空间 43D (perception.py); 兼做建图 (manifold/localization_mapping.py)
    🐛 2026-09-01 真实执行: 原 _ss_run 只打日志, perception.py 断点永不命中"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        if "状态向量" in name or "obs" in name.lower():
            obs43 = _ss_ensure_obs43(log)
            if log:
                log(f"🧩 43D obs (真实): 39D 视觉 [0:39] + 触觉4D [39:43] · "
                    f"grasp={obs43[39]:.3f} contact={obs43[40]:.3f} dir=({obs43[41]:.2f},{obs43[42]:.2f})")
            return True
        obs39, _img = _ss_env_obs(log)
        # 🆕 2026-11-10 (老倪「融合定位建图节点，接收到 2D→3D 的转换的结果了么」):
        #   原来只取 env 的 39D 真值, 2D→3D 节点写的 _YOLO_CACHE["obs39_aligned"] 全仓零消费者
        #   ⇒ 自监督解算的 3D 悬着, 统一状态空间吃的还是仿真真值。
        #   现按与 _ss_ensure_obs43 同一口径接: 新鲜度闸 SS_ALIGN_MAX_AGE_S (默认 3s) + 长度 39。
        #   **默认不覆盖数值** (ZMAX_FUSION_BOX3D=1 才真填 39D) —— 未证明提升不进默认档;
        #   闸关时也把两路偏差记进 _SS_STATE, 让「接没接、差多少」可观测, 而不是靠日志猜。
        _fus_src = "env"
        try:
            import time as _time
            _b3 = _YOLO_CACHE.get("obs39_aligned")
            _b3_t = float(_YOLO_CACHE.get("obs39_aligned_t") or 0.0)
            _b3_age = (_time.time() - _b3_t) if _b3_t else 1e9
            _b3_max = float(os.environ.get("SS_ALIGN_MAX_AGE_S", "3"))
            if (_b3 is not None and len(np.asarray(_b3).ravel()) >= 39 and _b3_age <= _b3_max):
                _b3v = np.asarray(_b3, dtype=float).ravel()
                try:      # 只可能仿真有真值: 记偏差供判据, 不改任何输出
                    _dev = float(np.linalg.norm(_b3v[4:7] - np.asarray(obs39[4:7], float))) * 1000.0
                    _SS_STATE["box3d_dev_mm"] = round(_dev, 2)
                except Exception:                                            # noqa: BLE001
                    pass
                if os.environ.get("ZMAX_FUSION_BOX3D") == "1":
                    obs39 = _b3v.copy()
                    _fus_src = "box3d"
                else:
                    _fus_src = "box3d(闸关)"
            else:
                _SS_STATE.pop("box3d_dev_mm", None)
        except Exception:                                                    # noqa: BLE001
            _fus_src = "env"
        _SS_STATE["fusion_src"] = _fus_src
        tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
        # 🧩 SAM3 掩膜 3D → 融合 (2026-10-14: 先前"只算不用", 掩膜 3D 落在缓存里零消费者 = 老倪说的"悬着")
        #   ① 掩膜可用 ⇒ 作**独立观测**入库 + 与框法**交叉校验**(偏差入状态), 参与融合质量判定;
        #   ② 真要改写 3D 数值必须显式开闸 `ZMAX_FUSION_SEG=1` —— 未证明提升不进默认档。
        seg_obs = _seg_mask3d_obs()
        seg_dev_mm = None
        if seg_obs:
            _SS_STATE["seg_mask3d"] = seg_obs
            try:
                _o0 = seg_obs[sorted(seg_obs)[0]]
                seg_dev_mm = float(np.linalg.norm(np.asarray([_o0["x"], _o0["y"]], float) -
                                                 np.asarray(obs39[4:6], float))) * 1000.0
                _SS_STATE["seg_mask3d_dev_mm"] = round(seg_dev_mm, 2)
            except Exception:                                               # noqa: BLE001
                seg_dev_mm = None
            if os.environ.get("ZMAX_FUSION_SEG") == "1":
                try:
                    _o0 = seg_obs[sorted(seg_obs)[0]]
                    obs39[4:6] = [float(_o0["x"]), float(_o0["y"])]
                    if _o0.get("z_mm") is not None:
                        obs39[6] = float(_o0["z_mm"]) / 1000.0
                    _SS_STATE["seg_mask3d_used"] = sorted(seg_obs)[0]
                except Exception:                                           # noqa: BLE001
                    pass
        else:
            _SS_STATE.pop("seg_mask3d", None)
            _SS_STATE.pop("seg_mask3d_dev_mm", None)
        obs43 = _ss_import("perception").fuse_sensors(obs39, np.zeros(6), tac)
        _SS_STATE.update({"obs43": obs43, "obs39": obs39})
        if log:
            log(f"📡 融合定位建图 (真实): 视觉39D ⊕ 触觉4D → 统一状态空间 43D · hand={np.round(obs39[0:3],3)} "
                f"光模块={np.round(obs39[4:7],3)} hole={np.round(obs39[36:39],3)} · 触觉={np.round(tac,3)}")
            if seg_obs:
                _o0 = seg_obs[sorted(seg_obs)[0]]
                _dev = ("-" if seg_dev_mm is None else "%.1fmm" % seg_dev_mm)
                log("   🧩 SAM3 掩膜 3D 观测[%s] base=(%.3f,%.3f)m z=%smm 足印=%s 帧=%s · 与框法偏差 %s%s" % (
                    sorted(seg_obs)[0], _o0["x"], _o0["y"],
                    ("-" if _o0.get("z_mm") is None else "%.0f" % float(_o0["z_mm"])),
                    (_o0.get("xy_size_mm") or "-"), (_o0.get("src") or "-"), _dev,
                    (" · 已按 ZMAX_FUSION_SEG=1 填进 39D" if os.environ.get("ZMAX_FUSION_SEG") == "1" else "")))
            else:
                log("   🧩 SAM3 掩膜 3D 观测: 本帧无 (未跑分割 / 帧非臂上相机 / 掩膜已过期) — 融合走框法")
        # 端口必须真产 (画布: sssensor.out1→ssobs.in1 融合特征 / out2→ss_mani_eng.in1 43D 状态)
        #   原来只 return True ⇒ 统一状态空间的入口读到 None (2026-11-10 实测空口)
        _f43 = [round(float(x), 6) for x in np.asarray(_ss_ensure_obs43(log), dtype=float).ravel()[:43]]
        _fus = {"kind": "fused43", "layer": "L2", "dim": len(_f43),
                "obs43": _f43, "obs39": _f43[:39], "tactile": _f43[39:43],
                "tcp": _f43[0:3], "peg": _f43[4:7], "hole": _f43[36:39],
                "fusion_src": _SS_STATE.get("fusion_src", "env"),
                "obs43_src": _SS_STATE.get("obs43_src", ""),
                "box3d_dev_mm": _SS_STATE.get("box3d_dev_mm"),
                "seg_mask3d_dev_mm": _SS_STATE.get("seg_mask3d_dev_mm"),
                "age_s": 0.0, "source": "ss_sensor 融合定位建图"}
        return {"out1": dict(_fus), "out2": dict(_fus),
                "out3": {"kind": "fusion_dev",
                         "box3d_dev_mm": _SS_STATE.get("box3d_dev_mm"),
                         "seg_mask3d_dev_mm": _SS_STATE.get("seg_mask3d_dev_mm"),
                         "fusion_src": _SS_STATE.get("fusion_src", "env")},
                "ok": True}
    except Exception as e:
        if log:
            log(f"⚠️ 融合定位建图真实执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_s1
