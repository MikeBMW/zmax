#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 层真实运行回路 (老倪 2026-10-14: 「让L2 L3都运行，我看着」)

跑的是 **L3 层的真节点** (走 GUI 双击同一条路: runtime.execute_node_logic), 每个周期:
  ① 抓一帧**真相机画面**    http://127.0.0.1:8791/snapshot/local2.jpg  (带帧龄/字节/HTTP)
  ② 取一帧**真轨迹**        reports/ss_episode_latest.npz (876 帧真机录制: x/peg/target/stage/grasped/v_vec)
  ③ 跑 L3 真节点:
       🧠 ss_vlm    → SmolVLM2 视觉塔**真前向** (帧 → z ∈ R^960, 首次加载 ~15s)
       🛠 ss_skill  → SkillComposer 真编排 (规格 → 技能序列 + 力阈值/节拍)
       🚀 ss_mem_l3 → L3 长程序列规划 (海马体记忆)
     (🎯 action_head / 🎛 ss_lora_l3 是**结构/产物节点**, 只登记配置与产物, 不算推理 ⇒ 如实标注不充数)
  ④ 落状态 zmax_data/ss_live/l3_live_status.json + 追加 zmax_data/ss_live/l3_live.jsonl

为什么要这条回路: 模型引擎那一列的「推理中」= 该层最近窗口内**有没有真跑节点**
(唯一依据 = runtime.execute_node_logic → layer_calls.touch → zmax_data/ss_live/layer_calls.json,
manifest 里 L3 探针 = json_counter#L3.count, 窗口 60s)。所以「让 L3 显示运行」的正确做法是**真跑 L3**,
不是改显示。L2 另有在役回路 (ss_yolo_on_real.py --auto --loop, 它写 ss_bypass/yolo_detections.json,
L2 探针 = 该文件 10s 新鲜度) —— 本回路不重复起 L2 推理。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.engineering import runtime, layer_calls                          # noqa: E402
from lerobot.engineering.registry import NODE_LOGIC                           # noqa: E402

STATE = os.path.join(ROOT, "zmax_data/ss_live")
PID = os.path.join(STATE, "l3_live.pid")
STATUS = os.path.join(STATE, "l3_live_status.json")
JSONL = os.path.join(STATE, "l3_live.jsonl")
EPISODE = os.path.join(ROOT, "reports/ss_episode_latest.npz")
NODES = (("ss_vlm", "🧠 VLM 通用视觉编码器 (SmolVLA) 真前向"),
         ("ss_skill", "🛠 L3 技能序列编排"),
         ("ss_mem_l3", "🚀 L3 长程序列规划 (海马体)"))
STRUCT_ONLY = (("action_head", "🎯 Flow-Matching Action Head (DiT)"), ("ss_lora_l3", "🎛 L3 SmolVLA LoRA"))
_STOP = False


class _Ctx:
    """节点执行上下文 (与 GUI 侧 module 同形: _ss_tr/_ss_round/_log/_dw)。"""

    def __init__(self):
        self._ss_tr: dict | None = None
        self._ss_round = 0
        self._dw = None
        self._trace_nodes = False
        self.lines: list = []

    def _log(self, *a):
        s = " ".join(str(x) for x in a)
        self.lines.append(s)
        print("      " + s[:180], flush=True)


def _load_tr() -> dict:
    import numpy as np
    if os.path.exists(EPISODE):
        z = np.load(EPISODE, allow_pickle=True)
        return {k: np.asarray(z[k]).tolist() for k in z.files if k != "meta"}
    p = os.path.join(ROOT, "data/database/zmax/sources/canvas/ss_traj_last.json")
    return json.load(open(p, encoding="utf-8"))


def _grab_frame(url: str) -> dict:
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            b = r.read()
            lm = r.headers.get("Last-Modified")
        return {"ok": True, "url": url, "bytes": len(b), "http": getattr(r, "status", 200),
                "ms": round((time.time() - t0) * 1000, 1), "last_modified": lm, "data": b}
    except Exception as e:                                                    # noqa: BLE001
        return {"ok": False, "url": url, "err": "%s: %s" % (type(e).__name__, str(e)[:100]),
                "ms": round((time.time() - t0) * 1000, 1), "data": None}


def _frame_array(fr: dict):
    """真帧 → ndarray (H,W,3)。用 PIL 解 JPEG (与节点内 encode_stage 同源头)。"""
    if not fr.get("data"):
        return None
    try:
        import io
        import numpy as np
        from PIL import Image
        return np.asarray(Image.open(io.BytesIO(fr["data"])).convert("RGB"))
    except Exception:                                                        # noqa: BLE001
        return None


def cycle(ctx: _Ctx, tr: dict, idx: int, cam_url: str) -> dict:
    import numpy as np
    n = len(tr.get("t") or [])
    idx = (idx % n) if n else 0
    fr = _grab_frame(cam_url)
    arr = _frame_array(fr)
    stage = "未知"
    try:
        stage = str(tr["stage"][idx]).replace("阶段 ", "").split("·")[0].strip()
    except Exception:                                                        # noqa: BLE001
        pass
    ctx._ss_round = idx
    ctx._vlm_cache = {}          # 每周期清缓存 ⇒ 每周期都是**真前向** (不清则同 stage 命中缓存, 只第一次真算)
    trr = dict(tr)
    if arr is not None:                                                      # 真帧提供给需要图像 token 的节点
        trr["key_frames"] = {stage: arr, "局部": arr, "local": arr}
    ctx._ss_tr = trr
    out = {"ts": time.strftime("%H:%M:%S"), "idx": idx, "stage": stage,
           "cam": {k: v for k, v in fr.items() if k != "data"},
           "nodes": {}, "struct_only": [n2 for n2, _ in STRUCT_ONLY]}
    for key, nm in NODES:
        info = NODE_LOGIC.get(key) or {}
        fn = info.get("fn")
        if fn is None:
            out["nodes"][key] = {"ok": False, "msg": "未注册"}
            continue
        ctx.lines = []
        t0 = time.time()
        err = ""
        try:
            runtime.execute_node_logic(ctx, {"name": nm}, label="L3 回路")
        except Exception as e:                                               # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, str(e)[:120])
        ms = round((time.time() - t0) * 1000, 1)
        tail = ([x for x in ctx.lines if x.strip()][-1:] or [""])[0]
        out["nodes"][key] = {"ok": not err, "ms": ms, "err": err, "last_log": tail[:170]}
    out["layer_calls"] = {k: (v or {}).get("count") for k, v in layer_calls.read().items()
                          if k in ("L2", "L3", "L4", "L5")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="L3 层真实运行回路")
    ap.add_argument("--interval", type=float, default=1.0, help="每个周期间隔秒 (默认 1.0)")
    ap.add_argument("--seconds", type=float, default=0.0, help="跑多少秒后停 (0=一直跑)")
    ap.add_argument("--cam-url", default="http://127.0.0.1:8791/snapshot/local2.jpg")
    ap.add_argument("--instance", default="l3")
    a = ap.parse_args()

    def _on_term(_s, _f):
        global _STOP
        _STOP = True
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    os.makedirs(STATE, exist_ok=True)
    if os.path.exists(PID):
        try:
            old = int(open(PID, encoding="utf-8").read().strip())
            os.kill(old, 0)
            print("⚠️ 已有 L3 回路在跑 (pid %d) ⇒ 退出 (单实例)" % old)
            return 3
        except Exception:                                                    # noqa: BLE001
            pass
    with open(PID, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    print("══ L3 真实运行回路 ══ 间隔 %.1fs · 相机 %s · 轨迹 %s" % (a.interval, a.cam_url, os.path.basename(EPISODE)))
    print("   节点: %s" % " · ".join("%s(%s)" % (k, n) for k, n in NODES))
    print("   纯结构/产物节点 (只登记, 不算推理): %s" % " · ".join(k for k, _ in STRUCT_ONLY))
    tr = _load_tr()
    print("   轨迹: %d 帧 · 键 %s" % (len(tr.get("t") or []), ",".join(sorted(tr)[:9])))
    # 预加载 L3 视觉塔 (离线本地缓存实测 1.0s) —— 不预加载则前几轮只打印"加载中", 看着在跑实际没 encode
    try:
        from lerobot.policies.smolvla_lew.vlm_encoder import get_encoder
        _e = get_encoder()
        _e.ensure_loaded_async()
        _t0 = time.time()
        _ok = _e.wait_loaded(180)
        print("   🧠 视觉塔预加载: %s · %.1fs · 状态=%s · load_ms=%s%s"
              % ("就绪" if _ok else "未就绪", time.time() - _t0, _e.status, round(_e.load_ms or 0),
                 (" · err=" + str(_e.error)[:80]) if _e.error else ""), flush=True)
    except Exception as _exc:                                                # noqa: BLE001
        print("   ⚠️ 视觉塔预加载失败: %s" % _exc, flush=True)
    ctx = _Ctx()
    t_start, cyc, fails = time.time(), 0, 0
    while not _STOP:
        cyc += 1
        rec = cycle(ctx, tr, cyc - 1, a.cam_url)
        rec["cycle"] = cyc
        ok_n = sum(1 for v in rec["nodes"].values() if v.get("ok"))
        if not rec["cam"].get("ok") or ok_n == 0:
            fails += 1
        print("[%s] #%d 帧 idx=%d 阶段=%s 相机 %s/%s %.0fms · 节点 ok %d/%d · %s"
              % (rec["ts"], cyc, rec["idx"], rec["stage"],
                 "OK" if rec["cam"].get("ok") else "失败", rec["cam"].get("bytes"), rec["cam"].get("ms"),
                 ok_n, len(rec["nodes"]),
                 " · ".join("%s %.0fms" % (k, v.get("ms") or 0) for k, v in rec["nodes"].items())), flush=True)
        rec["pid"] = os.getpid()
        rec["started"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start))
        rec["uptime_s"] = round(time.time() - t_start, 1)
        rec["fails"] = fails
        tmp = STATUS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, STATUS)
        with open(JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        if a.seconds and (time.time() - t_start) >= a.seconds:
            break
        time.sleep(max(0.0, a.interval - (time.time() - t_start - (cyc - 1) * a.interval)))
    print("══ 停: 共 %d 周期 · 失败 %d · 运行 %.0fs ══" % (cyc, fails, time.time() - t_start))
    try:
        os.remove(PID)
    except Exception:                                                        # noqa: BLE001
        pass
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
