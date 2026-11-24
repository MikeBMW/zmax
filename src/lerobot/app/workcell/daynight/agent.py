#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自主工作 (agent) —— 训练好的模型在 550C 上自己看、自己算、自己判好坏。

不是"再训一个模型", 而是把**已过闸上线**的动力学头投入值班:
  ① 取最近的真实状态(白天日志尾巴)
  ② 用上线模型做秒级前瞻(horizon 由模型元数据决定)
  ③ 与真实到达值比, 算在线误差 → 记 agent_log.jsonl
  ④ 误差超阈值 ⇒ status.degraded=True 并把原因写回 state.json(供上层降级/回滚)
  ⑤ 同时输出一份可被页面/其他服务读的 agent/status.json

设计纪律:
- 只读日志, 不碰机器人、不碰安全闸; 判据失败只"标记降级", 绝不自作主张改参数
- 没有上线模型就老实报 "no_model", 不许拿先验冒充模型
"""
from __future__ import annotations

import json
import os
import time

from . import daylog
from .phase import DN_DIR, read_state, write_state

AG_DIR = os.path.join(DN_DIR, "agent")
STATUS = os.path.join(AG_DIR, "status.json")
LOG = os.path.join(AG_DIR, "agent_log.jsonl")
PRIOR = os.path.join(DN_DIR, "current.json")

# 误差阈值: 关节预测(度)。超过就认为模型对这工况失效(不调参, 只标记)
ERR_DEG_WARN = 3.0
ERR_DEG_BAD = 8.0


def _ensure() -> None:
    os.makedirs(AG_DIR, exist_ok=True)


def _load_dyn() -> dict | None:
    try:
        with open(PRIOR, encoding="utf-8") as f:
            dyn = json.load(f).get("dyn") or {}
    except Exception:                                              # noqa: BLE001
        return None
    if not dyn.get("ckpt") or not os.path.isfile(dyn["ckpt"]):
        return None
    meta_path = dyn["ckpt"].replace(".pt", ".json")
    meta = {}
    if os.path.isfile(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            meta = {}
    return {"dyn": dyn, "meta": meta}


def _latest_records(n: int) -> list[dict]:
    d = daylog.latest_with_data()
    if not d:
        return []
    rs = [r for r in daylog.read(d) if all(isinstance(r.get(k), (int, float))
                                           for k in ("ts", "th_mm", "p", "H"))]
    rs.sort(key=lambda r: r["ts"])
    return rs[-n:]


def tick(day_id: str = "") -> dict:
    """一次自我值班: 用上线模型前瞻 + 在线误差自检。"""
    _ensure()
    out = {"ts": time.time(), "ok": True}
    model = _load_dyn()
    st = read_state()
    if not model:
        out.update({"ok": False, "why": "no_model", "model_ver": st.get("model_ver")})
        _write_status(out)
        return out

    dyn, meta = model["dyn"], model["meta"]
    kind = meta.get("kind", "state")
    horizon = int(meta.get("horizon") or 1)
    out["model_ver"] = dyn.get("ver")

    # 口径纪律: joints 模型是**路径时间**(示教 5Hz/4s), telemetry 模型才是**墙钟**。
    # 拿路径时间模型去对 98Hz 遥测判好坏, 差的是口径不是模型 ⇒ 不许报 degraded。
    if kind == "joints" and not meta.get("hz_wall"):
        out.update({"ok": True, "kind": "joints", "model_ver": dyn.get("ver"), "level": "n/a",
                    "degraded": False,
                    "why": "该模型是路径时间口径(示教 5Hz), 不用于墙钟遥测自检; 需 telemetry 口径模型才判"})
        _write_status(out)
        return out

    if kind in ("joints", "telemetry"):
        # 关节口径: 需要真机关节序列 —— 用最近一次 RT 回放的 meas 日志(只读)
        import glob
        files = sorted(glob.glob(os.path.join(os.path.dirname(DN_DIR), "rokae_sdk", "logs", "meas_*.jsonl")))
        if not files:
            out.update({"ok": False, "why": "no_meas_log"})
            _write_status(out)
            return out
        rows = []
        with open(files[-1], encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:                                  # noqa: BLE001
                    continue
                q = d.get("q") or d.get("j")
                if isinstance(q, list) and len(q) >= 6 and isinstance(d.get("t"), (int, float)):
                    # meas 落的是**弧度**, 模型是用真实示教轨迹的**度**训的 ⇒ 必须换算
                    import math as _m
                    rows.append((float(d["t"]), [_m.degrees(float(x)) for x in q[:6]]))
        if len(rows) < horizon + 5:
            out.update({"ok": False, "why": "meas_too_short", "n": len(rows)})
            _write_status(out)
            return out
        import math
        rows.sort(key=lambda r: r[0])
        # 🔴 关键: 模型是在它自己的采样率上训的(示教轨迹 5Hz, 20 帧=4s),
        #    而实测序列是 98Hz ⇒ 必须按**时间**取起点, 不能按行号取, 否则 20 行只有 0.2s
        hz = float(meta.get("hz") or 5.0)
        dt = horizon / hz
        t1, q1 = rows[-1]
        cand = [r for r in rows if r[0] <= t1 - dt]
        if not cand:
            out.update({"ok": False, "why": "meas_shorter_than_horizon", "need_s": round(dt, 2)})
            _write_status(out)
            return out
        t0, q0 = cand[-1]
        span_move = max(abs(q1[k] - q0[k]) for k in range(6))
        if span_move < 0.3:
            out.update({"ok": True, "kind": "joints", "static_span_deg": round(span_move, 3),
                        "why": "该跨度内臂几乎没动, 不具备判据价值", "level": "idle",
                        "degraded": False, "model_ver": dyn.get("ver")})
            _write_status(out)
            return out
        err = None
        try:
            import torch
            net_state = torch.load(dyn["ckpt"], map_location="cpu")
            import torch.nn as nn
            W = meta.get("width", 16)
            lag = int(meta.get("lag") or 0)
            net = nn.Sequential(nn.Linear(12 if lag else 6, W), nn.SiLU(), nn.Linear(W, 6))
            net.load_state_dict(net_state["state_dict"])
            net.eval()
            v = [0.0] * 6
            if lag:
                t_lag = t0 - lag / hz
                prev = [r for r in rows if r[0] <= t_lag]
                if not prev:
                    out.update({"ok": False, "why": "meas_shorter_than_lag", "need_s": round(lag / hz, 1)})
                    _write_status(out)
                    return out
                v = [q0[k] - prev[-1][1][k] for k in range(6)]
            with torch.no_grad():
                x = torch.tensor([q0 + v], dtype=torch.float32)
                pred = (torch.tensor([q0], dtype=torch.float32) + net(x))[0].tolist()
            err = max(abs(pred[k] - q1[k]) for k in range(6))
            pred_deg = [round(v, 3) for v in pred]
        except Exception as e:                                     # noqa: BLE001
            out.update({"ok": False, "why": "infer_failed: %s" % e})
            _write_status(out)
            return out
        out.update({"kind": "joints", "horizon_frames": horizon, "hz": hz,
                    "span_s": round(t1 - t0, 3), "span_move_deg": round(span_move, 3),
                    "err_deg": round(err, 3),
                    "pred_deg": pred_deg, "actual_deg": [round(v, 3) for v in q1]})
    else:
        recs = _latest_records(horizon + 2)
        if len(recs) < horizon + 2:
            out.update({"ok": False, "why": "day_log_too_short"})
            _write_status(out)
            return out
        try:
            import torch
            import torch.nn as nn
            sd = torch.load(dyn["ckpt"], map_location="cpu")
            net = nn.Sequential(nn.Linear(3, 64), nn.SiLU(), nn.Linear(64, 64), nn.SiLU(), nn.Linear(64, 3))
            net.load_state_dict(sd["state_dict"])
            net.eval()
            a, b = recs[-(horizon + 1)], recs[-1]
            x = torch.tensor([[a["th_mm"] / 100.0, a["p"] / 0.05, a["H"] / 0.1]], dtype=torch.float32)
            with torch.no_grad():
                pred = (x + net(x))[0].tolist()
            act = [b["th_mm"] / 100.0, b["p"] / 0.05, b["H"] / 0.1]
            err = max(abs(pred[i] - act[i]) for i in range(3))
            out.update({"kind": "state", "horizon_frames": horizon,
                        "err_norm": round(err, 4), "pred": [round(v, 4) for v in pred],
                        "actual": [round(v, 4) for v in act]})
        except Exception as e:                                     # noqa: BLE001
            out.update({"ok": False, "why": "infer_failed: %s" % e})
            _write_status(out)
            return out

    e = out.get("err_deg") if out.get("kind") == "joints" else None
    if e is None:
        e = float(out.get("err_norm") or 0.0) * 100.0        # 归一化误差换算成"度当量"仅用于分级
    out["level"] = "ok" if e < ERR_DEG_WARN else ("warn" if e < ERR_DEG_BAD else "bad")
    out["degraded"] = out["level"] == "bad"

    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")
    _write_status(out)
    if out["degraded"]:
        st["degraded"] = True
        write_state(st, "agent: 在线误差 %.2f° 超阈值 → 标记降级(模型 %s)" % (e, dyn.get("ver")))
    return out


def _write_status(out: dict) -> None:
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATUS)
