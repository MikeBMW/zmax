#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_train.py — 用 gsplat 从「已知真值位姿」数据集训练 3DGS 环境资产 (Z-MAX)

为什么不用 COLMAP: 臂上相机随臂动 = 每个视角都有 50Hz TCP 真值 + 手眼(残差 0.06mm) ⇒
外参是**算出来的**不是 SfM 解出来的; 省掉整条最脆的链。

输入: tools/gs_dataset.py 产出的 cameras.json (convention=T_cam2world, OpenCV 光学系) + images/
输出: <out>/gs.ply (真尺度) · <out>/gs.splat (网页查看器用) · <out>/renders/*.png (留出视角)
      <out>/train_report.json (步数/高斯数/PSNR/耗时/归一化参数)

用法: ~/zmax/venvs/gs-venv/bin/python tools/gs_train.py --data <数据集目录> --out <输出目录> \
        [--steps 15000] [--sh-degree 2] [--eval-every 2000] [--smoke 200]
"""
from __future__ import annotations
import argparse, json, math, os, sys, time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image


# ── 极简 SSIM (3DGS 原版口径: 11x11 高斯窗, 0.8*L1 + 0.2*(1-SSIM)) ──
def _ssim(x, y, window_size=11, size_average=True):
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ch = x.shape[1]
    coords = torch.arange(window_size, dtype=x.dtype, device=x.device) - window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * 1.5 ** 2))
    g = (g / g.sum()).unsqueeze(0)
    w = (g.t() @ g).unsqueeze(0).unsqueeze(0).repeat(ch, 1, 1, 1)
    pad = window_size // 2
    mu1 = F.conv2d(x, w, padding=pad, groups=ch)
    mu2 = F.conv2d(y, w, padding=pad, groups=ch)
    s11 = F.conv2d(x * x, w, padding=pad, groups=ch) - mu1 ** 2
    s22 = F.conv2d(y * y, w, padding=pad, groups=ch) - mu2 ** 2
    s12 = F.conv2d(x * y, w, padding=pad, groups=ch) - mu1 * mu2
    ssim = ((2 * mu1 * mu2 + c1) * (2 * s12 + c2)) / ((mu1 ** 2 + mu2 ** 2 + c1) * (s11 + s22 + c2))
    return ssim.mean()


def psnr(a, b):
    mse = float(((a - b) ** 2).mean())
    return 99.0 if mse <= 1e-12 else -10.0 * math.log10(mse)


def read_gs_ply(path):
    """读 3DGS 标准 .ply(gsplat export_splats 写的那套: x y z | f_dc_(3) | f_rest_(K*3) |
    opacity | scale_(3) | rot_(4), 全 float32 小端, 无 normal 属性)。
    返回(世界系/米, 且 scales 仍是 log 域, opacity 仍是 logit 域 —— 与文件一致, 不做激活):
      {"means":(N,3) 米, "scales_log":(N,3), "opac":(N,), "quats":(N,4), "sh0":(N,1,3), "shN":(N,K,3)}
    """
    import numpy as _np
    with open(path, "rb") as f:
        raw = f.read()
    he = raw.find(b"end_header\n")
    if he < 0:
        raise ValueError("不是标准 ply: 找不到 end_header")
    header = raw[:he].decode("ascii", "ignore")
    props = [ln.split()[-1] for ln in header.splitlines() if ln.startswith("property float")]
    n = int([ln for ln in header.splitlines() if ln.startswith("element vertex")][0].split()[-1])
    body = _np.frombuffer(raw[he + len(b"end_header\n"):], dtype=_np.float32)
    body = body[: n * len(props)].reshape(n, len(props))
    ix = {p: i for i, p in enumerate(props)}
    means = body[:, [ix["x"], ix["y"], ix["z"]]].astype(_np.float32)
    sc = body[:, [ix["scale_0"], ix["scale_1"], ix["scale_2"]]].astype(_np.float32)
    op = body[:, ix["opacity"]].astype(_np.float32)
    q = body[:, [ix["rot_0"], ix["rot_1"], ix["rot_2"], ix["rot_3"]]].astype(_np.float32)
    sh0 = body[:, [ix["f_dc_0"], ix["f_dc_1"], ix["f_dc_2"]]].astype(_np.float32)[:, None, :]
    rest = sorted([p for p in props if p.startswith("f_rest_")], key=lambda s: int(s.split("_")[-1]))
    if rest:
        v = body[:, [ix[p] for p in rest]].astype(_np.float32)
        K = len(rest) // 3
        shN = v.reshape(n, 3, K).transpose(0, 2, 1).copy()      # 还原 (N,K,3): 文件里是通道优先
    else:
        shN = _np.zeros((n, 0, 3), _np.float32)
    return {"means": means, "scales_log": sc, "opac": op, "quats": q, "sh0": sh0, "shN": shN}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="数据集目录(含 cameras.json 与 images/)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=15000)
    ap.add_argument("--sh-degree", type=int, default=2)
    ap.add_argument("--eval-every", type=int, default=2000)
    ap.add_argument("--holdout", type=int, default=20, help="留出视角数(从数据里每隔 k 取一个)")
    ap.add_argument("--init-points", type=int, default=100000)
    ap.add_argument("--init-ply", default="",
                    help="增量建图: 从已有 gs.ply 续训(用它的高斯当起点), 而不是随机初值。"
                         "归一化 center/S 会按新数据集重算, 脚本自动换算(尺度是纯缩放, 无旋转)")
    ap.add_argument("--no-refine", action="store_true",
                    help="增量续训时通常关掉致密化(新视角少, 致密化会过度膨胀)")
    ap.add_argument("--smoke", type=int, default=0, help=">0 时只跑这么多步(冒烟测试)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--refine-stop", type=int, default=0,
                    help="停止致密化的步数 (0=自动=min(steps, 15000)*0.5)。"
                         "官方配方: 30k 步训练、15k 步停致密化; 跑满全程会过度致密化")
    a = ap.parse_args()

    torch.manual_seed(a.seed); np.random.seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    import gsplat
    from gsplat.strategy import DefaultStrategy
    print("torch %s · cuda=%s (%s) · gsplat %s" % (torch.__version__, torch.cuda.is_available(),
          torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-", gsplat.__version__))

    cj = json.load(open(os.path.join(a.data, "cameras.json"), encoding="utf-8"))
    W, H = int(cj["width"]), int(cj["height"])
    K = torch.tensor(cj["K"], dtype=torch.float32, device=dev).unsqueeze(0)
    frames = cj["frames"]
    print("数据集: %d 帧 %dx%d · convention=%s" % (len(frames), W, H, cj["convention"]))

    # 位姿: viewmat = inv(T_cam2world) (world→cam); 场景归一化(3DGS 学习率按归一化尺度给)
    # ⚠️ 2026-10-01 真跑踩到: tr/te 原来直接拿 cameras.json 的原始 frame 字典, 里面**没有 R**(只有 T_cam2world),
    #    render() 里 c["R"] 直接 KeyError。⇒ 先把每个视角富化成统一结构(必须**在建 tr/te 之前**), 只用富化对象。
    cams = []
    for f in frames:
        T = np.array(f["T_cam2world"], dtype=np.float64)
        R, t = T[:3, :3], T[:3, 3]
        cams.append({"file": f["file"], "src": f.get("src"), "R": R, "t": t, "T": T})

    # 留出视角: 每 step 取一个, 不参与训练(评估泛化)
    step_h = max(2, len(frames) // max(1, a.holdout))
    hold = set(range(0, len(frames), step_h))
    tr = [c for i, c in enumerate(cams) if i not in hold]
    te = [c for i, c in enumerate(cams) if i in hold]
    print("训练 %d 视角 · 留出 %d 视角" % (len(tr), len(te)))
    centers = np.array([c["t"] for c in cams])
    center = centers.mean(0)
    spread = np.abs(centers - center).max()
    S = 1.0 / max(1e-6, spread)                      # world → 归一化系:  x' = S*(x - center)
    print("场景归一化: center=%s spread=%.4fm S=%.3f" % (np.round(center, 4), spread, S))

    def viewmat_of(c):
        Tn = np.eye(4)
        Tn[:3, :3] = c["R"]
        Tn[:3, 3] = S * (c["t"] - center)
        return torch.tensor(np.linalg.inv(Tn), dtype=torch.float32, device=dev)

    # 初值点云: 相机前向 0.28m 之外的中位视点周围, 尺寸按相机跨度(无 COLMAP 点云时的常规替代)
    fwd = np.array([c["R"] @ np.array([0, 0, 1.0]) for c in cams])   # OpenCV 光学系 z 前
    look = centers + 0.28 * fwd
    # 🔴 2026-10-01 修: 归一化系里 x' = S*(x - center) —— 初值点云中心也必须乘 S
    #   (原 `look.mean(0) - center` 漏了 S ⇒ 初值偏 0.18m, 与 line 97 相机位姿的写法自相矛盾)
    lc = S * (look.mean(0) - center)                                  # 归一化系里的场景中心
    sz = np.array([0.30, 0.30, 0.20]) * S
    sh_dim = (a.sh_degree + 1) ** 2
    C0 = 0.28209479177387814
    if a.init_ply:
        # ── 增量建图: 用已有资产当起点(边移动边建) ──────────────────────────────
        # 文件里是世界系(米): 位置真值、scales 是 log(米)、opacity 是 logit。
        # 新 run 的归一化是 x' = S*(x-center), 尺度是纯缩放(无旋转) ⇒ 直接换算是安全的。
        P = read_gs_ply(a.init_ply)
        N = int(P["means"].shape[0])
        means = torch.tensor(S * (P["means"].astype(np.float64) - center), dtype=torch.float32, device=dev)
        scales = torch.tensor(P["scales_log"].astype(np.float64) + math.log(S), dtype=torch.float32, device=dev)
        quats = torch.tensor(P["quats"], dtype=torch.float32, device=dev)
        opac = torch.tensor(P["opac"], dtype=torch.float32, device=dev)
        colors = torch.zeros((N, sh_dim, 3), device=dev)
        colors[:, :1, :] = torch.tensor(P["sh0"], dtype=torch.float32, device=dev)
        Kn = min(sh_dim - 1, int(P["shN"].shape[1]))
        if Kn > 0:
            colors[:, 1:1 + Kn, :] = torch.tensor(P["shN"][:, :Kn, :], dtype=torch.float32, device=dev)
        print("增量续训: 从 %s 载入 %d 个高斯 (SH 档 %d: sh0 + %d 个高阶系数)"
              % (os.path.basename(a.init_ply), N, a.sh_degree, Kn))
    else:
        N = a.init_points
        means = torch.tensor(np.random.uniform(-sz / 2, sz / 2, size=(N, 3)) + lc, dtype=torch.float32, device=dev)
        scales = torch.log(torch.full((N, 3), 0.01 * S, device=dev))
        quats = torch.zeros((N, 4), device=dev); quats[:, 0] = 1.0
        opac = torch.logit(torch.full((N,), 0.1, device=dev))
        colors = torch.zeros((N, sh_dim, 3), device=dev)
        colors[:, 0, :] = (torch.tensor([0.5, 0.5, 0.5], device=dev) - 0.5) / C0
        print("初值: %d 个高斯 · SH 阶 %d (dim %d)" % (N, a.sh_degree, sh_dim))

    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(means), "scales": torch.nn.Parameter(scales),
        "quats": torch.nn.Parameter(quats), "opacities": torch.nn.Parameter(opac),
        "sh0": torch.nn.Parameter(colors[:, :1, :].contiguous()),
        "shN": torch.nn.Parameter(colors[:, 1:, :].contiguous()),
    }).to(dev)
    # 🔴 2026-10-01 修: scene_scale 是"归一化系里的场景尺度" (DefaultStrategy 用它归一化
    #   grow/prune 阈值: scale/scene_scale)。本脚本的归一化是 x' = S*(x-center), S=1/spread
    #   ⇒ 相机位姿落在 ±1 内, 场景尺度 ≈ 1。原来写 S*0.5≈2.13 把 grow 阈值放宽了一倍多。
    scene_scale = 1.0
    lrs = {"means": 1.6e-4 * scene_scale, "scales": 5e-3, "quats": 1e-3,
           "opacities": 5e-2, "sh0": 2.5e-3, "shN": 2.5e-3 / 20}
    opts = {k: torch.optim.Adam([{"params": [params[k]], "lr": v}], betas=(0.9, 0.999)) for k, v in lrs.items()}
    # 🔴 2026-10-01 修: 位置学习率必须**指数衰减**(官方配方 1.6e-4 → 1.6e-6, 走完全程)。
    #   原实现是恒定 lr ⇒ 后期致密化叠加高 lr 会发散: 实测 15000 步后 loss 从 0.16 回升到 0.29、
    #   高斯涨到 140 万、留出 PSNR 反而回落到 13dB(低于"填常数"平凡基线)。
    _st_total = a.smoke or a.steps
    means_lr0 = lrs["means"]
    means_lr_min = means_lr0 * 0.01

    def means_lr_at(step):
        if step >= _st_total:
            return means_lr_min
        return float(np.exp(np.log(means_lr0) + (np.log(means_lr_min) - np.log(means_lr0)) * (step / _st_total)))
    strategy = DefaultStrategy(verbose=True,
                               refine_stop_iter=(0 if a.no_refine else
                                                 (a.refine_stop or int(min(_st_total, 15000) * 0.5))))
    strat_state = strategy.initialize_state(scene_scale=scene_scale)

    # 图像: 常驻内存(uint8), 每步搬一张上卡
    def load(f):
        im = Image.open(os.path.join(a.data, "images", f["file"])).convert("RGB")
        return torch.tensor(np.asarray(im), dtype=torch.uint8, device=dev).float().div_(255.0)

    def render(camsub, sh_flag=True):
        vm = viewmat_of(camsub).unsqueeze(0)
        col = torch.cat([params["sh0"], params["shN"]], dim=1)
        # 🔴 2026-10-01 修: gsplat.rasterization 要**线性尺度**, 而 params["scales"] 是 log 域
        #   (初值 line 107 用 torch.log, 导出 line 181 用 .exp() —— 只有这里漏了 exp)。
        #   漏 exp 的后果: 尺度被当线性读 = 0.043(而它本意是 4cm/场景 1 单位), 基元巨大 ⇒ 整帧被
        #   盖满成恒色, 梯度饱和, 参数冻死 (实测 run3: 15000 步 PSNR 12.88→12.87 全平,
        #   留出渲染唯一色=1, split/duplicate 全 0)。
        img, alpha, info = gsplat.rasterization(
            params["means"], params["quats"], torch.exp(params["scales"]),
            torch.sigmoid(params["opacities"]),
            col, viewmats=vm, Ks=K, width=W, height=H, sh_degree=(a.sh_degree if sh_flag else None),
            # 🔧 2026-10-01: 不传 backgrounds —— gsplat 要求 (B,H,W,C), 传错会
            #   "assert backgrounds.shape == image_dims + (channels,)"。不传=按 alpha 在黑底合成,
            #   是 3DGS 标准做法(训练用 L1+alpha 合成, 不受底色影响)。
            packed=True, near_plane=0.01)
        return img[0].permute(2, 0, 1).clamp(0, 1), info

    @torch.no_grad()
    def evaluate():
        ps = []
        for c in te[:min(8, len(te))]:
            im = load(c).permute(2, 0, 1)
            out, _ = render(c)
            ps.append(psnr(out, im))
        # 诊断用: 同一套权重在**训练视角**上的 PSNR —— 分开"没拟合上"与"过拟合/位姿不一致"
        trs = []
        for c in tr[:min(3, len(tr))]:
            im = load(c).permute(2, 0, 1)
            out, _ = render(c)
            trs.append(psnr(out, im))
        _last_train_psnr[0] = float(np.mean(trs)) if trs else 0.0
        return float(np.mean(ps)) if ps else 0.0

    _last_train_psnr = [0.0]

    steps = a.smoke or a.steps
    os.makedirs(os.path.join(a.out, "renders"), exist_ok=True)
    t0 = time.time(); log = []
    for step in range(1, steps + 1):
        opts["means"].param_groups[0]["lr"] = means_lr_at(step)   # 位置 lr 指数衰减(官方配方)
        c = tr[np.random.randint(len(tr))]
        gt = load(c).permute(2, 0, 1)
        out, info = render(c)
        if strategy.absgrad:
            info["means2d"].retain_grad()
        l1 = (out - gt).abs().mean()
        loss = 0.8 * l1 + 0.2 * (1.0 - _ssim(out.unsqueeze(0), gt.unsqueeze(0)))
        strategy.step_pre_backward(params, opts, strat_state, step, info)
        loss.backward()
        strategy.step_post_backward(params, opts, strat_state, step, info, packed=True)
        for o in opts.values():
            o.step(); o.zero_grad(set_to_none=True)
        if step % 200 == 0 or step == steps:
            msg = "[%5d/%d] loss %.4f (L1 %.4f) · 高斯 %d · %.1fs" % (
                step, steps, float(loss), float(l1), params["means"].shape[0], time.time() - t0)
            print(msg, flush=True); log.append(msg)
        if a.eval_every and (step % a.eval_every == 0 or step == steps):
            ev = evaluate()
            print("   ↳ 留出视角 PSNR = %.2f dB (训练视角 %.2f dB)" % (ev, _last_train_psnr[0]), flush=True)

    # 导出: 反归一化回真尺度(base_link, 米)
    # ⚠️ 2026-10-01 修(口径): .ply/.splat 的 scales 与 opacities 按**标准约定**存 **log 域 / logit 域**
    #   (与 gsplat 官方 simple_trainer 一致: 它 rasterization 用 exp/sigmoid, export 传原始参数;
    #    antimatter15 的 splat 查看器与多数 .ply 读取器都按 exp/logit 反解)。
    #   原实现传的是已激活值(exp/sigmoid 后) ⇒ 标准查看器读出来尺度/透明度全错 ⇒ 资产对外不可用。
    with torch.no_grad():
        m = (params["means"] / S) + torch.tensor(center, dtype=torch.float32, device=dev)
        sc = params["scales"] - math.log(S)                    # 真尺度 · 保持 log 域
        q = F.normalize(params["quats"], dim=-1)
        op = params["opacities"].detach()                      # 保持 logit 域
        sh0 = params["sh0"].detach(); shN = params["shN"].detach()
    ply = os.path.join(a.out, "gs.ply"); splat = os.path.join(a.out, "gs.splat")
    gsplat.export_splats(means=m, scales=sc, quats=q, opacities=op, sh0=sh0, shN=shN, format="ply", save_to=ply)
    gsplat.export_splats(means=m, scales=sc, quats=q, opacities=op, sh0=sh0, shN=shN, format="splat", save_to=splat)
    # 留出视角渲图存档
    for i, c in enumerate(te[:6]):
        with torch.no_grad():
            out, _ = render(c)
        Image.fromarray((out.permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)).save(
            os.path.join(a.out, "renders", "holdout_%02d.png" % i))
        Image.open(os.path.join(a.data, "images", c["file"])).save(
            os.path.join(a.out, "renders", "holdout_%02d_gt.png" % i))
    # 🔴 诊断(2026-10-01): 训练视角也存档, 并与训练循环**同口径**算一次 L1/PSNR。
    #   目的: 分开"没拟合上"和"渲染/存档/评估口径不一致"(实测出现过 L1=8/255 但评估 PSNR 只有 13dB 的矛盾)
    for i, c in enumerate(tr[:3]):
        with torch.no_grad():
            out, _ = render(c)
        gt_t = load(c).permute(2, 0, 1)
        l1_t = float((out - gt_t).abs().mean())
        print("   ↳ 训练视角 %d: L1 %.4f (=%.1f/255) · PSNR %.2f dB" % (i, l1_t, l1_t * 255.0, psnr(out, gt_t)))
        Image.fromarray((out.permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)).save(
            os.path.join(a.out, "renders", "train_%02d.png" % i))
        Image.open(os.path.join(a.data, "images", c["file"])).save(
            os.path.join(a.out, "renders", "train_%02d_gt.png" % i))
    _ev_final = evaluate()
    rep = {"data": a.data, "steps": steps, "sh_degree": a.sh_degree, "n_gaussians": int(params["means"].shape[0]),
           "psnr_holdout_db": _ev_final, "psnr_train_db": _last_train_psnr[0],
           "recipe": {"refine_stop_iter": int(strategy.refine_stop_iter), "refine_every": int(strategy.refine_every),
                      "reset_every": int(strategy.reset_every), "scene_scale": scene_scale, "init_points": int(N)},
           "seconds": time.time() - t0, "normalize": {"center": list(center), "S": S},
           "ply": ply, "splat": splat, "log_tail": log[-6:], "device": dev}
    json.dump(rep, open(os.path.join(a.out, "train_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 训练完成 · 高斯 %d · 留出 PSNR %.2f dB · 训练视角 %.2f dB · %.1fs"
          % (rep["n_gaussians"], rep["psnr_holdout_db"], rep["psnr_train_db"], rep["seconds"]))
    print("   ply=%s\n   splat=%s" % (ply, splat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
