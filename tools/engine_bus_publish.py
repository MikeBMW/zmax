#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""engine_bus_publish.py — 流形引擎 → AR/AOI 集成信号总线 (老倪 2026-10-12)。

老倪口径:
> 用我的插拔场景和摆盘场景, 作为软件在环测试环境; 用 AOI AR 场景, 作为集成信号的实际接口。

本工具把**流形引擎的实测几何量**并进 `tools/ar_aoi_bus.py` 的同一 live 总线文件 (AR 8797 / AOI
10082·10083 信号都走这条路), 使 AR/AOI 场景看到的不只是相机/AOI 信号, 还有引擎的度量与健康度。

信号口径 (全部来自真源, 不造数):
  · 引擎.健康度_H         H = (1/κ)·λ_min        (无量纲; 分级 >0.5 优秀 / 0.1~0.5 良好 / 0.01~0.1 警告 / ≤0.01 危险)
  · 引擎.条件数_κ         κ = λ_max/λ_min
  · 引擎.最小特征值_λmin / 引擎.最大特征值_λmax  (度量张量 g 的特征值)
  · 引擎.各向异性          std(λ)/mean(λ)
  · 引擎.扭矩_τ           ‖g⁻¹F‖  (m/s², 引擎输出的"动力"预算; 力由工序真源给定, 缺省 1N 基准载荷)
  · 引擎.度量尺度_M       标量 M (等效惯量尺度)
  · 引擎.度量分量数       n(n+1)/2
  · 引擎.分级             0=危险 1=警告 2=良好 3=优秀 (数值化, 便于大屏判色)

用法:
  python3 tools/engine_bus_publish.py                 # 用真源配置 (config/calib/zmax_manifold.json) 发一次
  python3 tools/engine_bus_publish.py --task TASK-06-TRAY   # 先用配置单映射出 M 再发
  python3 tools/engine_bus_publish.py --dry-run       # 只算不发
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

GRADE_NUM = {"critical": 0, "warning": 1, "good": 2, "excellent": 3}


def _engine_state(task: str | None = None, force_n: float = 1.0) -> dict:
    """从真源算出引擎的几何/健康量 (与流形引擎节点同一套口径)。"""
    from lerobot.manifold.metric_field import MetricField
    from lerobot.manifold.health import health_from_metric                          # noqa: PLC0415

    cfg_path = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
    mapping = None
    if task:
        import importlib.util as ilu
        sp = ilu.spec_from_file_location("config_to_M", os.path.join(ROOT, "tools", "config_to_M.py"))
        cm = ilu.module_from_spec(sp)
        sp.loader.exec_module(cm)
        mapping = cm.compute_M(task)
        m = mapping.get("metric") or {}
        f = MetricField(dim=int(m.get("dim", 3)), scale=float(mapping.get("scale", 1.0)),
                        mode=str(m.get("mode", "isotropic")), diag=m.get("diag"), comps=m.get("components"))
    else:
        f = MetricField.from_config(path=cfg_path)

    spec = f.spec()
    n = int(spec["dim"])
    rep = health_from_metric(f.g(np.zeros(n)))          # 健康度口径的唯一实现 = health.py
    lam_min, lam_max = float(rep.lambda_min), float(rep.lambda_max)
    kappa, H, aniso = float(rep.kappa), float(rep.H), float(rep.anisotropy)
    # ⚠️ 尺度发现 (2026-10-12): g = M·G ⇒ λ = M·λ̃, 而 κ/anisotropy 对尺度不变 ⇒
    #    H = (1/κ)·λmin = M · H̃, 其中 H̃ = (1/κ)·λ̃min 才是**尺度不变**的几何健康度。
    #    分级/阈值必须落在 H̃ (否则 M 一变分级就跟着变, 把"物理尺度"误读成"几何变好")。
    g_tilde = f.shape(np.zeros(n))                       # det G = 1 的形状部分
    rep_t = health_from_metric(g_tilde)
    H_t = float(rep_t.H)
    grade = str(rep_t.status)
    force = np.zeros(n)
    force[0] = float(force_n)
    tau = float(np.linalg.norm(f.ginv_mul(np.zeros(n), force)))                # ‖g⁻¹F‖
    return {"H": H, "H_tilde": H_t, "kappa": kappa, "lam_min": lam_min, "lam_max": lam_max, "aniso": aniso,
            "tau": tau, "M": float(spec["尺度 M"]), "ncomp": int(spec["独立分量数"]), "grade": grade,
            "dim": n, "mode": spec["mode"], "task": task or "-", "cfg": os.path.relpath(cfg_path, ROOT)}


def signals(st: dict) -> dict:
    return {"引擎.健康度_H": round(st["H"], 6), "引擎.健康度_H̃_尺度不变": round(st["H_tilde"], 6),
            "引擎.条件数_κ": round(st["kappa"], 6),
            "引擎.最小特征值_λmin": round(st["lam_min"], 9), "引擎.最大特征值_λmax": round(st["lam_max"], 9),
            "引擎.各向异性": round(st["aniso"], 6), "引擎.扭矩_τ": round(st["tau"], 9),
            "引擎.度量尺度_M": round(st["M"], 6), "引擎.度量分量数": float(st["ncomp"]),
            "引擎.分级": float(GRADE_NUM.get(st["grade"], 0))}


def main() -> int:
    ap = argparse.ArgumentParser(description="流形引擎 → AR/AOI 集成信号总线")
    ap.add_argument("--task", default="", help="先用配置单映射 M (如 TASK-06-TRAY), 缺省用真源配置")
    ap.add_argument("--force", type=float, default=1.0, help="计算 τ 用的基准力 (N, 缺省 1)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    st = _engine_state(a.task or None, a.force)
    sig = signals(st)
    prov = {"src": "src/lerobot/manifold/metric_field.py + health.py", "by": "engine_bus_publish.py",
            "cfg": st["cfg"], "metric": "g_ij(x)=M·G_ij(x) (det G=1)", "dim": st["dim"], "mode": st["mode"],
            "task": st["task"], "grade": st["grade"]}
    print(json.dumps({"state": st, "signals": sig}, ensure_ascii=False, indent=1))
    if a.dry_run:
        print(json.dumps({"ok": True, "dry_run": True}, ensure_ascii=False))
        return 0
    import importlib.util as ilu
    sp = ilu.spec_from_file_location("ar_aoi_bus", os.path.join(ROOT, "tools", "ar_aoi_bus.py"))
    bus = ilu.module_from_spec(sp)
    sp.loader.exec_module(bus)
    # 先拉一次现场信号 (AR/AOI), 再把引擎信号并进去 ⇒ 同一份 live 总线文件
    try:
        pulled = bus.pull(publish_it=False, quiet=True) or {}
    except Exception as e:                                                     # noqa: BLE001
        pulled = {"err": repr(e)}
    out = bus.publish(sig, meta={"engine": st}, prov=prov, quiet=True)
    back = bus._j(bus.LIVE, {}) or {}                                           # noqa: SLF001
    got = {k: back.get("s", {}).get(k) for k in sig}
    miss = [k for k, v in got.items() if v is None]
    ok = bool(out.get("ok")) and not miss
    print(json.dumps({"ok": ok, "live": os.path.relpath(bus.LIVE, ROOT), "n_total": out.get("n"),
                      "signals_written": len(sig), "missing": miss,
                      "readback": got, "ar_pull_keys": len((pulled.get("signals") or {}))},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
