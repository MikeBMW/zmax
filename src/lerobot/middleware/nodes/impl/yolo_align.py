# -*- coding: utf-8 -*-
"""yolo_align — 节点实现正文 (文件名 = 画布节点: yolo_align)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_yolo_align   ·   registry key: yolo_align
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _BOX3D,
    _YOLO_ALIGNER,
    _YOLO_CACHE,
    _box3d_ensure,
    _box3d_pose,
    _box3d_state_path,
)

def node_yolo_align(ctx):
    """📐 2D→3D 解算 — 真实执行 (**2026-09-18 改造: 不作弊版**)

    输入: ① 感知给的 YOLO **2D 框** (_YOLO_CACHE['det2d'], 真检测结果)
          ② 机器人**自身**位姿 (真机=编码器落盘 / 仿真=末端状态)
    算法: Box3DSolver (自监督: 模块刚性夹持 ⇒ 中心=TCP+R·off; 未知 P 与 off 一起从数据里解)
    输出: 光模块 3D → 39D 的 [4:7] 与 [22:25]
    🚫 不读: env 的模块真值 (obs[7:10] / _pc) · aligner.detect_3d 的仿真内参/外参/深度
    """
    log = ctx["log"]
    try:
        det2d = _YOLO_CACHE.get("det2d") or {}
        box = None
        for k in ("光模块", "peg"):
            if isinstance(det2d.get(k), dict) and det2d[k].get("box"):
                box = [float(v) for v in det2d[k]["box"]]
                break
        if box is None:
            if log:
                log("📐 2D→3D: 本帧没有可用的 YOLO 2D 框 (先跑 🎯 YOLO 目标检测) — 不产出 3D")
            return False
        aligner = None
        try:
            aligner = _YOLO_ALIGNER
        except Exception:                                                  # noqa: BLE001
            pass
        tcp, quat, psrc = _box3d_pose(ctx.get("module"), aligner)
        if tcp is None:
            if log:
                log("📐 2D→3D: 拿不到机器人位姿 (真机旁路无数据 / 仿真无末端状态) — 不产出 3D")
            return False
        if quat is None:
            if log:
                log("📐 2D→3D: 有位置没姿态 → 现在用不了 (需要有姿态才能解 offset) — 攒数据跳过本帧")
            return False
        slv = _box3d_ensure(log)
        r = slv.add(box, tcp, quat, meta={"img_wh": _YOLO_CACHE.get("img_shape")})
        _BOX3D["n_seen"] += 1
        if not slv.fitted and (len(slv.obs) >= 10) and (_BOX3D["n_seen"] % 5 == 0):
            # 未知量按 2026-09-18 可辨识性实验: **R_rel 与 off 必须联合估** (不估 R_rel → off 被
            # 歪斜吸收, 中心实测偏 76mm); **尺寸不联合解** (尺寸自由会退化, 实测中心偏 65mm)。
            fit = slv.fit(use_rrel=True, use_scale=(getattr(slv, "K", None) is None))
            if log:
                log("📐 2D→3D: 自拟合 " + ("成功 " + str({k: fit[k] for k in ('n_fit', 'rms_px',
                    'holdout_rms_px', 'off_mm', 'rrel_deg') if k in fit}) if fit.get("ok")
                    else f"暂不拟合 ({fit.get('why')})"))
            if fit.get("ok") and not fit.get("degenerate"):
                slv.save(_box3d_state_path(), extra={"src": "node_logic.📐 2D→3D 解算 (自监督)",
                                                     "handeye": getattr(slv, "T_cam_from_base", None)})
        # ── 3D **边界框** (中心 + 姿态 + 尺寸 + 8 角点 + 反投影自检), 不只是中心点 ──
        try:
            b3 = slv.predict_box3d(box, tcp=tcp, quat=quat) if slv.fitted else None
        except Exception as _e:                                            # noqa: BLE001
            b3 = None
            if log:
                log(f"⚠️ 3D 边界框解算失败: {type(_e).__name__}: {_e}")
        p3 = (b3.get("center") if (b3 and b3.get("ok")) else
              (slv.predict_held(tcp, quat) if slv.fitted else None))
        _BOX3D["box3d"] = b3 or {}
        _BOX3D["last"] = {"box": box, "tcp": tcp, "quat": quat, "pose_src": psrc,
                          "p3": p3, "fitted": bool(slv.fitted), "n_obs": len(slv.obs),
                          "rms_px": slv.rms_px, "off_mm": (None if slv.off is None else
                                                            [round(float(v) * 1000, 1) for v in slv.off]),
                          "used_env_module_truth": False, "used_sim_geometry": False}
        if p3 is None:
            if log:
                d = slv.diversity()
                log(f"📐 2D→3D: 攒数据中 {len(slv.obs)} 帧 · 框={[round(v,1) for v in box]} · "
                    f"位姿源={psrc} · {d['why']} — 还没标定, 本帧不产出假 3D")
            return False
        # 写 39D (光模块段): 与 align() 同段位约定
        obs39 = _YOLO_CACHE.get("obs39")
        out = None
        if obs39 is not None:
            import numpy as np
            out = np.asarray(obs39, dtype=float).copy()
            out[4:7] = p3
            out[22:25] = p3
            _YOLO_CACHE["obs39_aligned"] = out
        _YOLO_CACHE["box3d"] = dict(_BOX3D["last"])
        if log:
            log(f"📐 2D→3D 解算(不作弊): 框{[round(v,1) for v in box]} + 位姿[{psrc}] "
                f"→ 光模块 3D=[{p3[0]:.4f} {p3[1]:.4f} {p3[2]:.4f}]m "
                f"(自监督标定 · {len(slv.obs)} 帧 · 拟合 {slv.rms_px:.2f}px · "
                f"off={[round(float(v)*1000,1) for v in slv.off]}mm)")
            if b3 and b3.get("ok"):
                import numpy as np      # 局部导入 (本文件模块级不引 numpy)
                _cs = np.asarray(b3["corners8"], float)
                _sig = (b3.get("sigma_mm") or {}).get("total")
                log(f"📐 **3D 边界框** ({b3['mode']}): 中心=[{p3[0]:.4f} {p3[1]:.4f} {p3[2]:.4f}]m · "
                    f"尺寸={b3['size_mm']}mm({b3['size_src']}) · 8 角点范围 "
                    f"x[{_cs[:,0].min():.3f},{_cs[:,0].max():.3f}] y[{_cs[:,1].min():.3f},{_cs[:,1].max():.3f}] "
                    f"z[{_cs[:,2].min():.3f},{_cs[:,2].max():.3f}] · 反投影框 {b3.get('box2d_reproj')} "
                    f"vs 检测 {b3.get('box2d_obs')} (IoU {b3.get('iou')}) · σ ±{_sig}mm")
                for _g in (b3.get("gaps") or [])[:2]:
                    log(f"   gap: {_g}")
        # 仿真下允许**事后打分** (只记日志, 不进任何输出): 与 env 真值比一下
        try:
            env = getattr(aligner, "env", None)
            if env is not None:
                import numpy as np
                truth = np.asarray(env._get_obs(), float).ravel()[4:7]
                err = float(np.linalg.norm(np.asarray(p3) - truth)) * 1000
                if log:
                    log(f"📐 (只打分, 不入链路) 与仿真真值差 {err:.1f}mm")
                _BOX3D["last"]["score_mm_vs_sim_truth"] = round(err, 2)
        except Exception:                                                  # noqa: BLE001
            pass
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 2D→3D 解算(不作弊) 失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_yolo_align
