#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""se3_pose_provider.py — 把训练好的 SE(3) 7 维位姿预测头接进流形引擎 (实时)

链路 (每一步都是真数据):
    live obs(39) ──PCA(训练时同一 mu/W)──> z16 ──头──> ξ6 = [ρ;φ]
                                                   └─ 指数映射 / 群乘法 ─> T_next
    live 真值位姿 (rokae_sdk/tcp_out/latest.json, base_link)
                                                   └─ 下一拍真值到位后算 **1 步前向测地线残差**

纪律
  · 网络只出 6 数; 7 数由 `se3_pose_head.step_pose` 的群乘法给出 (四元数复合, ‖q‖≡1)。
  · 位姿陈旧 (>max_age_s) 直接 ok=False 并写明 age —— 不拿旧位姿冒充当前。
  · 训练域是**仿真** (AR 工位 obs→PCA): 落地时必须带 `domain` 字段, 不许说成真机标定过。
  · 残差是"上一拍预测 vs 本拍真值", 不是"本拍预测 vs 本拍真值"(那是作弊)。

用法
    python tools/se3_pose_provider.py --selftest
    python tools/se3_pose_provider.py --once           # 打一帧 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))
CKPT = os.path.join(ROOT, "zmax_data/se3_pose_head/head.pt")
POSE = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
PRED_OUT = os.path.join(ROOT, "zmax_data/ss_live/se3_pose_pred.json")


def read_pose7(path: str = POSE) -> dict:
    """读真机 TCP 位姿真值 → {pose7, age_s, src}。位姿真源 = 珞石 SDK endInRef。"""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "why": "位姿真值读不到: %s" % (type(e).__name__,)}
    age = time.time() - os.path.getmtime(path)
    q = np.array([d.get("qw"), d.get("qx"), d.get("qy"), d.get("qz")], float)
    n = float(np.linalg.norm(q))
    if n < 1e-9:
        return {"ok": False, "why": "位姿四元数为 0 (真值未刷新)"}
    p7 = np.concatenate([[d.get("x", 0.0), d.get("y", 0.0), d.get("z", 0.0)], q / n])
    return {"ok": True, "pose7": p7, "age_s": round(float(age), 3),
            "src": d.get("src", ""), "frame": d.get("frame", ""),
            "raw_q_norm": round(n, 9), "ts": d.get("t", "")}


class Se3PoseProvider:
    """引擎每周期调用一次: `provider(z=<潜表示>, state=<obs>)`。"""

    def __init__(self, ckpt: str = CKPT, pose_path: str | None = None, max_age_s: float = 2.0,
                 state_dim: int | None = None, xi_scale: float = 1.0) -> None:
        self.ckpt_path = ckpt
        # 夹具优先级: 显式参数 > 环境变量 SE3_POSE_FIXTURE > 真机真值文件
        self.pose_path = pose_path or os.environ.get("SE3_POSE_FIXTURE") or POSE
        self.xi_scale = float(xi_scale)
        self.max_age_s = float(max_age_s)
        self.ok_load = False
        self.why = ""
        self.mu = self.W = None
        self.head = None
        self.meta: dict = {}
        self._prev_pred = None
        self._prev_true = None
        self.residuals: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            import torch
            from lerobot.manifold.se3_pose_head import build_head
            d = torch.load(self.ckpt_path, map_location="cpu", weights_only=False)
            self.mu = np.asarray(d["pca_mu"], float)
            self.W = np.asarray(d["pca_W"], float)
            head = build_head(latent_dim=int(d["latent_dim"]), hidden=int(d.get("hidden", 128)),
                              max_trans=float(d.get("max_trans", 0.02)),
                              max_rot=float(d.get("max_rot", 0.20)), torch=torch)
            head.load_state_dict(d["state_dict"])
            head.eval()
            self.head = head
            self.meta = d.get("meta", {}) or {}
            self.ok_load = True
        except Exception as e:                                               # noqa: BLE001
            self.why = "权重/头加载失败: %s: %s" % (type(e).__name__, str(e)[:160])

    def latent(self, z=None, state=None) -> np.ndarray | None:
        """优先用 state 过训练时的 PCA (与训练同空间); 没有 state 才退回引擎潜表示。"""
        if state is not None and self.mu is not None:
            s = np.asarray(state, float).ravel()
            if s.size == self.mu.size:
                return (s - self.mu) @ self.W
        if z is not None:
            zz = np.asarray(z, float).ravel()
            if self.W is not None and zz.size == self.W.shape[0]:
                return zz
            if self.W is not None and zz.size == self.W.shape[1]:
                # 引擎已给潜表示: 直接用 (维度与训练潜维一致)
                return zz
        return None

    def __call__(self, z=None, state=None) -> dict:
        t0 = time.perf_counter()
        if not self.ok_load:
            return {"ok": False, "why": self.why, "trained": False}
        import torch
        from lerobot.manifold import se3_pose_head as H
        pr = read_pose7(self.pose_path)
        if not pr.get("ok"):
            return {"ok": False, "why": pr.get("why"), "trained": True}
        # 🔴 陈旧守卫: 位姿超过 max_age_s 就**拒绝预测** —— 拿旧位姿推出的 7 维预测等于编数据
        age = float(pr.get("age_s") or 0.0)
        if age > self.max_age_s:
            return {"ok": False, "trained": True,
                    "why": "位姿真值陈旧 %.1fs > %.1fs ⇒ 拒绝预测 (等真值刷新)"
                           % (age, self.max_age_s),
                    "pose_age_s": age, "pose_src": pr.get("src", ""),
                    "pose_path": os.path.relpath(self.pose_path, ROOT)}
        pose7 = pr["pose7"]
        zz = self.latent(z=z, state=state)
        if zz is None:
            return {"ok": False, "why": "没有可用潜表示 (state 维度与训练不符, z 也不匹配)",
                    "trained": True, "pose_src": pr.get("src")}
        with torch.no_grad():
            xi = self.head(torch.tensor(zz[None], dtype=torch.float32)).numpy()[0]
            if self.xi_scale != 1.0:
                xi = xi * self.xi_scale
            pred = H.step_pose(pose7, xi, mode="group")       # 6 维 → 7 维 (群乘法)
        # 1 步前向残差: 上一次预测 vs 这一次真值
        res = None
        if self._prev_pred is not None:
            d = H.pose_distance(self._prev_pred, pose7)
            res = {"rot_deg": round(d["rot_deg"], 4), "trans_mm": round(d["trans_m"] * 1e3, 4),
                   "se3": round(d["se3"], 6)}
            self.residuals.append(res)
            self.residuals = self.residuals[-200:]
        self._prev_pred, self._prev_true = pred.copy(), pose7.copy()
        out = {"ok": True, "pose7_pred": [round(float(v), 7) for v in pred],
               "xi": [round(float(v), 7) for v in xi], "mode": "group",
               "trained": True, "weights": os.path.relpath(self.ckpt_path, ROOT),
               "domain": "sim(AR 工位 obs→PCA) · 真机未标定",
               "dt_note": "训练步长 20ms (仿真 10 sub-step) / 实机周期≈100ms ⇒ ξ 幅值需按 dt 折算后再用于下发; 本轮只做预测, 不下发",
               "xi_scale": self.xi_scale,
               "pose_src": "%s · 帧龄 %.2fs · %s" % (pr.get("src", ""), pr.get("age_s", -1), pr.get("frame", "")),
               "pose_age_s": pr.get("age_s"),
               "quat_norm": round(float(np.linalg.norm(pred[3:7])), 9),
               "pose7_prev_true": [round(float(v), 7) for v in pose7],
               "t_head_ms": round((time.perf_counter() - t0) * 1e3, 2)}
        if res is not None:
            out["residual_1step"] = res
            out["residual_mean_20"] = {
                "rot_deg": round(float(np.mean([r["rot_deg"] for r in self.residuals[-20:]])), 4),
                "trans_mm": round(float(np.mean([r["trans_mm"] for r in self.residuals[-20:]])), 4)}
        try:
            os.makedirs(os.path.dirname(PRED_OUT), exist_ok=True)
            tmp = PRED_OUT + ".tmp"
            json.dump({"ts": time.time(), "t": time.strftime("%F %T"), **out},
                      open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, PRED_OUT)
        except Exception:                                                    # noqa: BLE001
            pass
        return out


def build_provider(**kw) -> Se3PoseProvider:
    return Se3PoseProvider(**kw)


def selftest() -> int:
    from lerobot.manifold import se3_pose_head as H
    r = H.self_test(verbose=False)
    ok1 = bool(r.get("ok"))
    p = Se3PoseProvider()
    pr = read_pose7()
    out = p(state=np.zeros(int(p.mu.size)) if p.mu is not None else None) if p.ok_load else {"ok": False, "why": p.why}
    ok2 = bool(p.ok_load) and bool(pr.get("ok"))
    # ④ 两种都算通过: 位姿新鲜 ⇒ 必须真出 7 数; 位姿陈旧 ⇒ 必须**拒绝**(守卫生效), 不许编数据
    fresh = bool(pr.get("ok")) and float(pr.get("age_s") or 1e9) <= p.max_age_s
    refused = (not out.get("ok")) and ("陈旧" in str(out.get("why", "")))
    ok3 = (bool(out.get("ok")) and abs(float(np.linalg.norm(out["pose7_pred"][3:7])) - 1) < 1e-6) if fresh else refused
    print("① 内核数学: %s" % ("OK" if ok1 else "FAIL"))
    print("② 权重加载: %s (%s) · PCA %s" % ("OK" if p.ok_load else "FAIL", p.why or "head.pt",
                                          None if p.mu is None else p.mu.size))
    print("③ 真值位姿: %s · age=%ss · q_norm=%.6f" % ("OK" if pr.get("ok") else "FAIL",
                                                     pr.get("age_s"), pr.get("raw_q_norm", 0)))
    print("④ %s: %s" % ("实时前向" if fresh else "陈旧守卫(正确行为)",
                        ("‖q‖=%.9f · xi=%s" % (float(np.linalg.norm(out["pose7_pred"][3:7])), out.get("xi")))
                        if out.get("ok") else out.get("why")))
    good = ok1 and ok2 and ok3
    print("✅ 自检通过" if good else "❌ 自检失败: %s" % (out.get("why") or p.why))
    return 0 if good else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.once:
        p = Se3PoseProvider()
        print(json.dumps(p(state=None), ensure_ascii=False, indent=1))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
