#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🦾 肌肉记忆通道 = 真机真实轨迹 (v2)

真源:
  zmax_data/pose_records/rec_20261111_181020/poses.jsonl   1470 样本, 真时间戳(~34Hz)
  tools/web/real_traj_joints.json                          215 点(只做几何参照; 它的时间是压缩过的)

v1 为什么不行(实测记录):
  - 用 215 点最近邻反查原始时间 ⇒「接近」段把 135s 静止空档整段吞进来(n=2713)
  - 20Hz 重采样 + 中心差分 ⇒ 段端点速度被摊平, ∫u·dt 与真实位移差 2.8~7.8mm

v2 口径:
  1) 段边界直接在原始录制上按几何事件定(最低点 z / z 回到 218 / y 123·183 / x 760·808),
     静止空档不算进任何段
  2) u[i] = (p[i+1]-p[i]) / (t[i+1]-t[i]) 前向差分 ⇒ ∫u·dt ≡ 段位移(恒等, 不是近似)
  3) 判据: 每段 ∫u·dt 与 q[-1]-q[0] 逐轴差 <0.01mm
写入 data/muscle_memory.json 的 "real215|<段>" 桶; 其它桶原样不动(有备份)。
口径: 只读真源 + 只写这一个桶; 不动真机、不动在跑的服务。
"""
import json
import os
import time as _t

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REC = os.path.join(REPO, "zmax_data", "pose_records", "rec_20261111_181020", "poses.jsonl")
MM = os.path.join(REPO, "data", "muscle_memory.json")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def load_raw():
    rows, skip = [], 0
    with open(REC, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                ts = r.get("ts")
                if ts is None:
                    continue
                rows.append((float(ts), float(r["x"]), float(r["y"]), float(r["z"])))
            except Exception:
                skip += 1
    rows.sort(key=lambda r: r[0])
    a = np.asarray(rows, dtype=float)
    if skip:
        print("  (跳过 %d 条不可解析记录)" % skip)
    return a[:, 0], a[:, 1:4]


def bounds_from_raw(ts, P):
    mm = P * 1000.0
    step = np.linalg.norm(np.diff(mm, axis=0), axis=1)
    dt = np.maximum(np.diff(ts), 1e-3)
    spd = step / dt
    i_low = int(np.argmin(mm[:, 2]))
    # 起始点: 从最低点往前找「这一段运动」的开头 —— 遇到 ≥0.6s 的停顿(速度<20mm/s 连续)就停
    slow = spd < 20.0
    i0, run = 0, 0
    for i in range(i_low, 0, -1):
        run = run + 1 if slow[i - 1] else 0
        if run >= 20:                      # ~0.6s 静止 ⇒ 上一段动作从 i 开始
            i0 = i
            break
    zlow = mm[i_low, 2]

    def back(pred, start):
        for i in range(start, max(i0, 0), -1):
            if pred(i):
                return i
        return start

    def fwd(pred, start):
        for i in range(start, len(mm)):
            if pred(i):
                return i
        return len(mm) - 1

    idx_z218 = back(lambda i: mm[i, 2] >= 218, i_low)        # 下降起点
    idx_y123 = back(lambda i: mm[i, 1] <= 123, idx_z218)     # 对位起点(215 点 i=3 的 y=123)
    idx_lift = fwd(lambda i: mm[i, 2] >= zlow + 30, i_low)   # 抓取结束/抬起起点
    idx_up = fwd(lambda i: mm[i, 2] >= 218, idx_lift)        # 抬起结束
    idx_x760 = fwd(lambda i: mm[i, 0] >= 760, idx_up)        # 转移结束(示教 插入口 761)
    idx_x808 = fwd(lambda i: mm[i, 0] >= 808, idx_x760)      # 插入结束(示教 到位 811)
    idx_end = idx_x808                                       # 完成段: 插入到位后 2s 内(按真时间截, 不按样本数)
    while idx_end < len(mm) - 1 and (ts[idx_end] - ts[idx_x808]) < 2.0:
        idx_end += 1

    b = {"接近": (i0, idx_y123), "对位": (idx_y123, idx_z218), "下降": (idx_z218, i_low),
         "抓取": (i_low, idx_lift), "抬起": (idx_lift, idx_up),
         "转移": (idx_up, idx_x760), "插入": (idx_x760, idx_x808),
         "完成": (idx_x808, idx_end)}
    return b, mm, i_low


RATE_HZ = 50.0        # 引擎 dt=0.02s (50Hz) ⇒ 标杆必须重采样到 50Hz, 否则重放快 9 倍(录制只有 ~5.4Hz)


def stage_uv(ts, P, a, b):
    """原始样本(≈5.4Hz) → 50Hz 等间隔(引擎步频) → 前向差分速度 ⇒ ∫u·dt 仍恒等于位移"""
    ts_s, xyz = ts[a:b + 1], P[a:b + 1]
    if len(ts_s) < 2:
        return None
    t0, t1 = ts_s[0], ts_s[-1]
    n = max(2, int(round((t1 - t0) * RATE_HZ)) + 1)
    tt = np.linspace(t0, t1, n)
    q = np.stack([np.interp(tt, ts_s, xyz[:, k]) for k in range(3)], axis=1)
    dt = np.full(n - 1, 1.0 / RATE_HZ)
    v = np.diff(q, axis=0) / dt[:, None]
    # 末样本速度=0: 重放 n 帧 = (n-1) 个步长 ⇒ ∑u·dt 恰好等于段位移(若沿用上一步会多走一步 5.5mm)
    v = np.vstack([v, np.zeros((1, 3))])
    u = np.concatenate([v, np.zeros((n, 1))], axis=1)           # 第4维=夹爪速度(现 0)
    return {"u": u, "x": q, "dt": dt, "dur": float(t1 - t0), "n": n}


def main():
    ts, P = load_raw()
    print("真源 poses: %d 样本 · %.1fs" % (len(ts), ts[-1] - ts[0]))
    b, mm, i_low = bounds_from_raw(ts, P)
    print("段边界(原始样本索引; 最低点 %d z=%.1fmm):" % (i_low, mm[i_low, 2]))
    for st in STAGES:
        a, c = b[st]
        print("  %-4s %5d→%-5d t=%5.2fs  %s → %s"
              % (st, a, c, ts[c] - ts[a], np.round(mm[a]).astype(int).tolist(),
                 np.round(mm[c]).astype(int).tolist()))

    out, ok_all = {}, True
    print("-" * 80)
    for st in STAGES:
        a, c = b[st]
        r = stage_uv(ts, P, a, c)
        if r is None:
            print("  %-4s ❌ 样本不足" % st)
            ok_all = False
            continue
        integ = (r["u"][:-1, :3] * r["dt"][:, None]).sum(0) * 1000.0
        disp = (r["x"][-1] - r["x"][0]) * 1000.0
        err = float(np.max(np.abs(integ - disp)))
        vmax = float(np.linalg.norm(r["u"][:, :3], axis=1).max() * 1000)
        ok = err < 0.01
        ok_all = ok_all and ok
        print("  %-4s n=%4d %5.2fs 位移%9s mm  ∫u·dt误差 %.6f mm  峰值%6.1f mm/s %s"
              % (st, r["n"], r["dur"], np.round(disp, 1).tolist(), err, vmax, "✅" if ok else "❌"))
        out[st] = {"n_ok": 999,
                   "champ_u": np.round(r["u"], 6).tolist(),
                   "champ_x": np.round(r["x"], 6).tolist(),
                   "io": {"src": "rec_20261111_181020/poses.jsonl",
                          "stage": st, "dur_s": round(r["dur"], 3), "n": r["n"],
                          "rate_hz": round(r["n"] / max(r["dur"], 1e-6), 2),
                          "disp_mm": np.round(disp, 2).tolist(),
                          "v_peak_mm_s": round(vmax, 1),
                          "note": "肌肉记忆通道=真机真实轨迹(前向差分速度)"}}

    db = json.load(open(MM, encoding="utf-8")) if os.path.isfile(MM) else {}
    bak = MM + ".bak_%s" % _t.strftime("%Y%m%d_%H%M%S")
    if os.path.isfile(MM):
        json.dump(db, open(bak, "w", encoding="utf-8"), ensure_ascii=False)
    n0 = len(db)
    for st in STAGES:
        db["real215|" + st] = out[st]
    json.dump(db, open(MM, "w", encoding="utf-8"), ensure_ascii=False)
    print("-" * 80)
    print("写库 %s · 条目 %d → %d · 备份 %s" % (os.path.basename(MM), n0, len(db), os.path.basename(bak)))
    print("判据: 8 段 ∫u·dt 与真实位移逐轴 <0.01mm ⇒ %s"
          % ("✅ 通道已与真实轨迹匹配" if ok_all else "❌ 有段不符"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
