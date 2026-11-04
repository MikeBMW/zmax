#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎥 三模态同源录制器 — 逐帧真渲染 pixels + 真接触力 force + 动作 + 状态, 一批数据全带

为什么需要它 (实测):
  · collect_cog_engine_trace.py 存了 obs/action/force 但**没有 pixels** (vision=False)
  · l5_plan_and_gen.py 有 pixels 但那是**每阶段关键帧** (sim._key_frames, 同阶段内重复同一张),
    并且不存 force ⇒ 之前那批 optical_insert_v6_disturb.h5 的图在同一阶段里是静止的
  ⇒ 要"视觉+力+动作同一批数据", 必须**逐帧渲染**并同时落 force。

做法:
  · vision=True 让引擎每步走真渲染 (`_render_frame` → env.render())
  · 包一层 `_render_frame` 把每帧抓下来 (不改变引擎行为, 只是旁路复制)
  · 逐帧写 pixels(224) + force(sim.run 的 force_norm) + observation(39) + action(4) + stage_id

用法:
  PATH=/home/ubuntu/zmax/gui-venv311/bin:$PATH MUJOCO_GL=egl \\
  gui-venv311/bin/python tools/collect_multimodal_v6.py --episodes 3 --steps 700 --modes insert \\
      --out /home/ubuntu/zmax/zmax_data/stable-wm-cache/datasets/mm_v6.h5
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("STABLEWM_HOME", f"{ROOT}/zmax_data/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", f"{ROOT}/zmax_data/stable-wm-cache")
sys.path.insert(0, f"{ROOT}/tools")
sys.path.insert(0, f"{ROOT}/tools/gui")
sys.path.insert(0, f"{ROOT}/src")

STAGES8 = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def stage_id(s):
    t = str(s).strip()
    for pre in ("阶段 ", "阶段"):
        if t.startswith(pre):
            t = t[len(pre):].strip()
    t = t.split("·")[0].strip() if "·" in t else t
    if t not in STAGES8:
        for s8 in STAGES8:
            if t.startswith(s8):
                return STAGES8.index(s8)
        return -1
    return STAGES8.index(t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--steps", type=int, default=700)
    ap.add_argument("--modes", default="insert")
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--upres", type=int, default=960, help="离屏渲染分辨率 (放大后裁 ROI 才有细节)")
    ap.add_argument("--roi", default="0.30,0.18,0.98,0.88",
                    help="裁剪框 x0,y0,x1,y1 (归一化, 由时间维 std 实测: 运动 bbox x[102,192] y[97,144]/224)")
    ap.add_argument("--no-roi", action="store_true", help="关了裁, 存全画幅 (对照用)")
    ap.add_argument("--out", default=f"{ROOT}/zmax_data/stable-wm-cache/datasets/mm_v6.h5")
    a = ap.parse_args()

    import h5py
    from state_space_sim_real import RealStateSpaceSim                # noqa: PLC0415

    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    obs_l, act_l, px_l, f_l, st_l, ep_l = [], [], [], [], [], []
    t0 = time.time()
    for i in range(a.episodes):
        mode = modes[i % len(modes)]
        sim = RealStateSpaceSim(seed=a.seed + i, vision=True, mode=mode, log=lambda *x: None)
        # 放大离屏缓冲: 480² 里运动只占 ~1% 像素, 先渲大再裁 ROI, 细节才留得住
        try:
            m = getattr(sim.env, "model", None)
            if m is not None:
                m.vis.global_.offwidth = int(a.upres)
                m.vis.global_.offheight = int(a.upres)
            mr = getattr(sim.env, "mujoco_renderer", None)
            if mr is not None:
                mr.width = int(a.upres); mr.height = int(a.upres)
        except Exception as e:
            print("  ⚠️ 放大离屏缓冲失败:", str(e)[:60])
        rx0, ry0, rx1, ry1 = [float(v) for v in a.roi.split(",")]
        frames = []
        _orig_render = sim._render_frame

        def _hooked(h=480, w=480, _o=_orig_render, _b=frames):
            fr = np.asarray(_o(h, w))          # 引擎自己拿到的永远是原图 (行为不变)
            store = fr
            if not a.no_roi and fr.ndim == 3:
                H, W = fr.shape[:2]
                crop = fr[int(ry0 * H):int(ry1 * H), int(rx0 * W):int(rx1 * W)]
                if crop.size:
                    import cv2
                    store = cv2.resize(crop, (a.size, a.size), interpolation=cv2.INTER_AREA)
            _b.append(store)
            return fr                          # ★ 返回原帧: 只旁路记录, 不改引擎感知

        sim._render_frame = _hooked
        tr = sim.run(max_steps=a.steps)
        sim._render_frame = _orig_render
        n = len(tr.get("t", []) or tr.get("obs", []))
        if n == 0:
            print(f"  段{i} 空轨迹, 跳过")
            continue
        obs = np.asarray(tr["obs"], np.float32)[:n, :39]
        act = np.asarray(tr.get("u_sat_vec") or tr.get("u_exec_vec"), np.float32)[:n, :4]
        fors = np.asarray(tr.get("force", np.zeros(n)), np.float32).reshape(-1)[:n]
        stages = np.asarray([stage_id(s) for s in tr.get("stage", [])[:n]], np.int32)
        # 帧对齐: 渲染帧数 nf 与步数 n 对齐 (取后 nf 帧或用尾帧补齐)
        nf = len(frames)
        n = min(n, len(obs), len(act), len(fors), len(stages))
        if nf >= n:
            fr_idx = np.linspace(0, nf - 1, n).round().astype(int)
            pxs = [frames[j] for j in fr_idx]
        else:
            pxs = list(frames) + [frames[-1] if frames else np.zeros((a.size, a.size, 3), np.uint8)] * (n - nf)
        # 统一尺寸
        px_arr = np.zeros((n, a.size, a.size, 3), np.uint8)
        for j, fr in enumerate(pxs[:n]):
            fr = np.asarray(fr)
            if fr.ndim == 2:
                fr = np.stack([fr] * 3, -1)
            if fr.shape[-1] != 3:
                fr = fr[..., :3]
            if fr.shape[:2] != (a.size, a.size):
                import cv2
                fr = cv2.resize(fr, (a.size, a.size))
            px_arr[j] = fr.astype(np.uint8, copy=False)
        diff = float(np.abs(np.diff(px_arr.astype(np.int16), axis=0)).mean()) if n > 1 else 0.0
        print(f"  段{i} mode={mode:6s} 步={n:4d} 渲染帧={nf:4d} 力非零={int((fors > 0).sum()):4d} "
              f"力max={fors.max():.3f} 帧间差={diff:.2f} 阶段={dict(zip(*[x.tolist() for x in np.unique(stages, return_counts=True)]))}")
        obs_l.append(obs[:n]); act_l.append(act[:n]); px_l.append(px_arr)
        f_l.append(fors[:n]); st_l.append(stages[:n]); ep_l.append(np.full(n, i, np.int32))

    if not obs_l:
        print("❌ 没采到数据")
        return 1
    obs_all, act_all = np.concatenate(obs_l), np.concatenate(act_l)
    px_all, f_all = np.concatenate(px_l), np.concatenate(f_l)
    st_all, ep_all = np.concatenate(st_l), np.concatenate(ep_l)
    # 段边界
    offs, lens = [], []
    for e in np.unique(ep_all):
        idx = np.where(ep_all == e)[0]
        offs.append(idx[0]); lens.append(len(idx))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with h5py.File(a.out, "w") as h:
        h.create_dataset("observation", data=obs_all)
        h.create_dataset("action", data=act_all)
        h.create_dataset("force", data=f_all.astype(np.float32))
        h.create_dataset("pixels", data=px_all, compression="gzip", compression_opts=4)
        h.create_dataset("stage_id", data=st_all)
        h.create_dataset("ep_idx", data=ep_all)
        h.create_dataset("ep_offset", data=np.asarray(offs, np.int64))
        h.create_dataset("ep_len", data=np.asarray(lens, np.int64))
        h.attrs["source"] = "multimodal v6 recorder (vision=True 逐帧渲染 + force_norm)"
        h.attrs["ts"] = time.strftime("%F %T")
    print(f"\n✅ 三模态同源数据集: {a.out}")
    print(f"   帧 {len(obs_all)} · 段 {len(offs)} · 力非零 {int((f_all > 0).sum())} · 用时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
