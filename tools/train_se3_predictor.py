"""SE(3) 分层状态预测器训练 (L4: 相对旋转向量 + L3: 相位 s 增量)。

数据: tools/web/real_traj_joints.json 的 215 帧真机录制 (p, q, j, t) + traj_phase.json 的弧长相位 s。

🔴 同源评估纪律 (本案最容易骗自己的地方):
  1. 相邻帧几乎相同(dt 0.2s, 转角中位 2.5°), **随机划分 = 泄漏** ⇒ 必须按连续段分折(block K-fold)。
  2. 必须有平凡基线: 零动作(Δ=0)、上一拍外推(Δ_t = Δ_{t-1})。赢不过基线就等于没学到。
  3. 必须有上界参照: 固定轨迹参考(直接取录制下一帧) —— 这是"跟固定轨迹一样"的定义。
  4. 全部指标报中位/P95/max, 不报单个数。

输出:
  zmax_data/rokae_sdk/se3_predictor.pt    权重 + 归一化参数
  zmax_data/rokae_sdk/se3_predictor_metrics.json  逐折 + 汇总指标
"""
import json, math, os, sys
import numpy as np
import torch
import torch.nn as nn

# 🔴 24 核跑这种 214×19 的小张量会陷入线程同步开销(实测 1251% CPU 却 7 分钟不出第一折)
torch.set_num_threads(1)

REPO = "/home/ubuntu/zmax"
TRAJ = REPO + "/tools/web/real_traj_joints.json"
PHASE = REPO + "/zmax_data/rokae_sdk/traj_phase.json"
CKPT = REPO + "/zmax_data/rokae_sdk/se3_predictor.pt"
METR = REPO + "/zmax_data/rokae_sdk/se3_predictor_metrics.json"
N_FOLD = 5
EPOCHS = 600
SEED = 0


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1*w2-x1*x2-y1*y2-z1*z2, w1*x2+x1*w2+y1*z2-z1*y2,
                     w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2])


def qnorm(q):
    m = np.linalg.norm(q) or 1.0
    return q / m


def qlog_rel(qa, qb):
    """qb 相对 qa 的旋转向量(度): r = log(qa^-1 * qb), 小角度近似 2*vec(w>0)."""
    qa = qnorm(np.asarray(qa, float)); qb = qnorm(np.asarray(qb, float))
    qi = np.array([qa[0], -qa[1], -qa[2], -qa[3]])
    qd = qmul(qi, qb)
    if qd[0] < 0:                    # 取 ±q 中 w>0 的一支, 保证是最短旋转
        qd = -qd
    v = qd[1:]
    s = np.linalg.norm(v)
    if s < 1e-12:
        return np.zeros(3)
    ang = 2.0 * math.atan2(s, qd[0])
    return v / s * math.degrees(ang)


def load():
    fr = json.load(open(TRAJ, encoding="utf-8"))["frames"]
    ph = json.load(open(PHASE, encoding="utf-8"))["frames"]
    return fr, ph


def build(fr, ph):
    """特征 = 当前帧可观测量; 标签 = 到下一帧的相对旋转向量(3) + 相位增量(1)。"""
    X, Y, meta = [], [], []
    n = len(fr)
    prev = np.zeros(3); prev2 = np.zeros(3); prev3 = np.zeros(3)
    for i in range(n - 1):
        x, y, z, w = fr[i]["q"]                 # 存储顺序 (x,y,z,w)
        q = np.array([w, x, y, z], float)
        s = ph[i]["s"]
        j = np.degrees(np.asarray(fr[i]["j"], float))[:6]
        p = np.asarray(fr[i]["p"], float) * 1000.0
        # 试过加 prev2/prev3 历史(25 维): 留出段中位 5.23° 反而更差 ⇒ 回退到 19 维(见报告)
        x_in = np.concatenate([j / 180.0, p / 1000.0, q, [math.sin(2*math.pi*s), math.cos(2*math.pi*s)],
                               [s], prev / 10.0])
        x2, y2, z2, w2 = fr[i+1]["q"]
        q2 = np.array([w2, x2, y2, z2], float)
        r = qlog_rel(q, q2)
        ds = ((ph[i+1]["s"] - ph[i]["s"] + 0.5) % 1.0) - 0.5      # 环绕增量
        X.append(x_in); Y.append(np.concatenate([r, [ds * 1000.0]]))  # ds 放大到 mm 量级便于回归
        meta.append({"i": i, "r_true": r.tolist(), "ds_true": float(ds)})
        prev3 = prev2.copy(); prev2 = prev.copy(); prev = r
    return np.asarray(X, np.float32), np.asarray(Y, np.float32), meta


class Net(nn.Module):
    def __init__(self, d_in, d_out=4):
        super().__init__()
        self.f = nn.Sequential(nn.Linear(d_in, 64), nn.Tanh(),
                               nn.Linear(64, 64), nn.Tanh(),
                               nn.Linear(64, d_out))

    def forward(self, x):
        return self.f(x)


def fit(Xtr, Ytr, d_in, seed=SEED):
    torch.manual_seed(seed)
    net = Net(d_in)
    opt = torch.optim.Adam(net.parameters(), lr=3e-3)
    lossf = nn.MSELoss()
    xt = torch.from_numpy(Xtr); yt = torch.from_numpy(Ytr)
    for _ in range(EPOCHS):
        opt.zero_grad(); loss = lossf(net(xt), yt); loss.backward(); opt.step()
    return net


def qexp(r_deg):
    """旋转向量(度) → 四元数 (w,x,y,z)"""
    r = np.asarray(r_deg, float); a = float(np.linalg.norm(r))
    if a < 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    ax = r / a
    h = math.radians(a) / 2.0
    return np.concatenate([[math.cos(h)], ax * math.sin(h)])


def angs(pred, true):
    """🔴 正确的误差口径: 两个旋转(由旋转向量给出)之间的物理夹角。

    旧版用'两个旋转向量的方向夹角'是错的: 真实 Δ 只有 2°、符号一翻就 180°,
    把小角度噪声放大成天文数字(实测 model 中位 62° 纯属口径病)。
    这里取 exp(r_pred)^T·exp(r_true) 的转角, 小角度时≈‖r_pred−r_true‖, 恒 ≤180°。
    """
    a = np.asarray(pred, float); b = np.asarray(true, float)
    if np.linalg.norm(a) < 1e-9 and np.linalg.norm(b) < 1e-9:
        return 0.0
    qa, qb = qexp(a), qexp(b)
    qd = qmul(np.array([qa[0], -qa[1], -qa[2], -qa[3]]), qb)
    s = float(np.linalg.norm(qd[1:]))
    return math.degrees(2.0 * math.atan2(s, abs(float(qd[0]))))


def stat(v):
    v = np.asarray(v, float)
    return {"median": round(float(np.median(v)), 3), "p95": round(float(np.percentile(v, 95)), 3),
            "max": round(float(v.max()), 3), "mean": round(float(v.mean()), 3)}


def main():
    fr, ph = load()
    X, Y, meta = build(fr, ph)
    n = len(X)
    print("样本 %d (= 帧数-1) · 特征 %d 维 · 标签 3(相对旋转向量) + 1(Δs)" % (n, X.shape[1]))
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Xn = (X - mu) / sd

    # ── block K-fold: 连续段分折, 杜绝相邻帧泄漏
    idx = np.arange(n)
    folds = np.array_split(idx, N_FOLD)

    global _MU_DELTA
    _MU_DELTA = Y[:, :3].mean(0)          # 平凡基线: 永远predict平均增量
    rows = {"model": [], "zero": [], "persist": [], "mean_base": [], "ref": []}
    ds_err = {"model": [], "zero": [], "persist": []}
    per_fold = []
    for k in range(N_FOLD):
        te = folds[k]
        tr = np.concatenate([folds[j] for j in range(N_FOLD) if j != k])
        net = fit(Xn[tr], Y[tr], X.shape[1], seed=SEED + k)
        with torch.no_grad():
            pr = net(torch.from_numpy(Xn[te])).numpy()
        for t, i in enumerate(te):
            r_true = Y[i][:3]
            ds_true = Y[i][3] / 1000.0
            r_pred = pr[t][:3]
            r_prev = X[i][-3:] * 10.0                     # 上一拍真值增量(persist 基线)
            rows["model"].append(angs(r_pred, r_true))
            rows["zero"].append(angs(np.zeros(3), r_true))
            rows["persist"].append(angs(r_prev, r_true))
            rows.setdefault("mean_base", []).append(angs(_MU_DELTA, r_true))
            rows["ref"].append(0.0)                       # 固定轨迹参考: 直接取录制下一帧
            ds_err["model"].append(abs(pr[t][3] / 1000.0 - ds_true))
            ds_err["zero"].append(abs(ds_true))
            ds_err["persist"].append(abs(X[i][10] / 1000.0 * 10 - X[i][10]))  # 占位, 见下
        per_fold.append({"fold": k, "n_test": int(len(te)),
                         "model_p95_deg": stat([angs(pr[t][:3], Y[i][:3]) for t, i in enumerate(te)])["p95"]})
        print("  fold %d/%d  测试 %3d 帧  模型 P95 %.2f°  零动作 P95 %.2f°" % (
            k + 1, N_FOLD, len(te),
            stat([angs(pr[t][:3], Y[i][:3]) for t, i in enumerate(te)])["p95"],
            stat([angs(np.zeros(3), Y[i][:3]) for t, i in enumerate(te)])["p95"]))

    out = {"n_samples": n, "n_features": int(X.shape[1]), "folds": N_FOLD, "epochs": EPOCHS,
           "ang_err_deg": {k: stat(v) for k, v in rows.items() if v},
           "ds_err_frac": {k: stat(v) for k, v in ds_err.items() if v and k != "persist"},
           "per_fold": per_fold,
           "note": "ang_err 是'预测的相对旋转向量'与'真实相对旋转向量'的夹角误差; "
                   "zero=什么都不动的基线; persist=照上一拍外推; ref=直接取录制下一帧(上界)"}
    # 全量重训一版存盘(给人用)
    net = fit(Xn, Y, X.shape[1], seed=SEED)
    torch.save({"state": net.state_dict(), "mu": mu, "sd": sd, "d_in": int(X.shape[1])}, CKPT)
    json.dump(out, open(METR, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out["ang_err_deg"], ensure_ascii=False, indent=1))
    print("权重 →", CKPT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
