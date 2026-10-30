"""判据：symmetry 搜索的热点该不该搬 GPU。

热点形态 = 每个点调一次极小流形算子（3 维 log/exp 映射），串行 60 步 × 若干段 × 每个候选。
测两种形态：
  ① 串行小算子（每次 1 个点）—— 看 GPU 的 kernel 启动开销是否吃掉全部收益
  ② 批量算子（一次 N 个点）—— 看批量化之后 GPU 是否真的快
判据：只有当 ② 显著快于 ① 的 numpy 时，才值得改；只把 ① 搬过去是负收益。
"""
import time

import numpy as np

try:
    import torch
    HAS_TORCH = True
except Exception:                                                        # noqa: BLE001
    HAS_TORCH = False


def np_log_map_norm(p, q):
    """球面 log_map 的范数（3 维，最小可用算子）。"""
    p = np.asarray(p, float).ravel()
    q = np.asarray(q, float).ravel()
    c = float(np.clip(np.dot(p, q), -1.0, 1.0))
    th = np.arccos(c)
    return float(th)


def np_serial(pts, reps):
    s = 0.0
    n = len(pts) - 1
    for _ in range(reps):
        for i in range(n):
            s += np_log_map_norm(pts[i], pts[i + 1])
    return s


def torch_serial(pts, reps, dev):
    p = torch.tensor(pts[:-1], dtype=torch.float32, device=dev)
    q = torch.tensor(pts[1:], dtype=torch.float32, device=dev)
    s = torch.zeros((), device=dev)
    n = p.shape[0]
    for _ in range(reps):
        for i in range(n):
            c = torch.clamp((p[i] * q[i]).sum(), -1.0, 1.0)
            s = s + torch.arccos(c)
    if str(dev) == "xpu":
        torch.xpu.synchronize()
    return float(s.cpu())


def torch_batched(pts, reps, dev):
    p = torch.tensor(pts[:-1], dtype=torch.float32, device=dev)
    q = torch.tensor(pts[1:], dtype=torch.float32, device=dev)
    s = torch.zeros((), device=dev)
    for _ in range(reps):
        c = torch.clamp((p * q).sum(dim=1), -1.0, 1.0)
        s = s + torch.arccos(c).sum()
    if str(dev) == "xpu":
        torch.xpu.synchronize()
    return float(s.cpu())


def timeit(fn, *a, **kw):
    fn(*a, **kw)                                     # warmup
    t0 = time.perf_counter()
    fn(*a, **kw)
    return time.perf_counter() - t0


rng = np.random.default_rng(0)
SEQ = rng.normal(size=(60, 3))
SEQ /= np.linalg.norm(SEQ, axis=1, keepdims=True)
REPS = 200

print("=== ① 串行小算子: 60 点 x %d 轮 (模拟一次窗口扫描) ===" % REPS)
t_np = timeit(np_serial, SEQ, REPS)
print("  numpy (CPU)          %.4f s" % t_np)
if HAS_TORCH:
    for dev in ("cpu", "xpu"):
        if dev == "xpu" and not torch.xpu.is_available():
            continue
        t = timeit(torch_serial, SEQ, REPS, dev)
        print("  torch %-4s (串行)   %.4f s   %.2fx vs numpy" % (dev, t, t_np / t))

print()
print("=== ② 批量算子: 同一批点一次性算 ===")
BIG = rng.normal(size=(200000, 3))
BIG /= np.linalg.norm(BIG, axis=1, keepdims=True)


def np_bulk(a):
    b = np.roll(a, -1, axis=0)
    return float(np.arccos(np.clip((a * b).sum(1), -1, 1)).sum())


def torch_bulk(a, dev):
    x = torch.tensor(a, dtype=torch.float32, device=dev)
    y = torch.roll(x, -1, 0)
    s = torch.arccos(torch.clamp((x * y).sum(1), -1, 1)).sum()
    if str(dev) == "xpu":
        torch.xpu.synchronize()
    return float(s.cpu())


t_nb = timeit(np_bulk, BIG)
print("  numpy (CPU)           %.4f s" % t_nb)
if HAS_TORCH:
    for dev in ("cpu", "xpu"):
        if dev == "xpu" and not torch.xpu.is_available():
            continue
        t = timeit(torch_bulk, BIG, dev)
        print("  torch %-4s (批量)    %.4f s   %.2fx vs numpy" % (dev, t, t_nb / t))

print()
print("判据: 若 ① 里 GPU 不快、② 里 GPU 明显快 ⇒ 正确改法是**批量化**, 不是把逐点算子搬过去。")
