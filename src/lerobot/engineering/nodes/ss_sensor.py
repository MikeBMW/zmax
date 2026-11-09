# -*- coding: utf-8 -*-
"""ss_sensor — 节点实现正文 (文件名 = 画布节点: ss_sensor)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_s1   ·   registry key: ss_sensor
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _SS_STATE,
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
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 融合定位建图真实执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_s1
