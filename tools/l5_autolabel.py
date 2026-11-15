#!/usr/bin/env python3
"""l5_autolabel.py — L5 场景理解 → 自动标注 → 喂 L2 (2026-11-15 老倪要求)

链路: 8791 抓帧 → SceneVLM 理解(阶段/工件/能否抓) → 结构化标注 → YOLO 格式落盘

为什么这样: L2 的 yolo_peg_live.pt 在真机画面 conf≤0.66 且框贴边(可疑误检)。
老倪的判断是「L5 先理解, 把自动标注的场景给到 L2」—— 用 VLM 的语义去标真机帧,
比人工标快, 也比纯 2D 检测器自举可靠。

输出:
  zmax_data/ss_live/l5_autolabel/<ts>/
    frame_XXXX.jpg          原始帧
    labels/frame_XXXX.txt   YOLO 格式 "cls cx cy w h" (归一化)
    meta.jsonl              {frame, stage, objects[{cls,bbox,conf,note}], vlm, ok}
  zmax_data/ss_live/l5_understand_latest.json   ← 也给 ss_mani_eng 的 L5Guide 用

用法:
  ./gui-venv311/bin/python tools/l5_autolabel.py --n 12 --every 4
  ./gui-venv311/bin/python tools/l5_autolabel.py --n 30 --every 2   # 跟回放跑一圈
"""
from __future__ import annotations
import argparse, json, os, sys, time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
CAM = "http://127.0.0.1:8791/snapshot/arm.jpg"
AR = "http://127.0.0.1:8797/api/arm/step_traj/status"
UND = os.path.join(REPO, "zmax_data", "ss_live", "l5_understand_latest.json")

PROMPT = """你是产线视觉工程师。看这张机械臂末端相机(HAND CAMERA)的实时画面，只输出 JSON：

{
  "stage": "接近|抓取|插入|对位|完成|空|看不清",
  "objects": [
    {"name": "peg|opt_gold|hole|fixture|other", "bbox_px": [x1,y1,x2,y2], "conf": 0.0~1.0, "note": "简短描述"}
  ],
  "can_grasp": true|false,
  "note": "一句话总体判断"
}

要求：
- bbox_px 用**画面像素坐标**(左上原点)，不要归一化。
- 只标**真实可见**的目标；看不清就不标、stage 写"看不清"，**不要猜**。
- peg=光模块(小长方体金属件)，opt_gold=金手指端面，hole=插孔。
- 画面里只有夹具/桌面就写 objects: [] 且 stage:"空"。"""


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _getj(url, timeout=6):
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--every", type=float, default=4.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-conf", type=float, default=0.5)
    a = ap.parse_args()

    import cv2
    import numpy as np
    from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM

    ts = time.strftime("%Y%m%d_%H%M%S")
    od = a.out or os.path.join(REPO, "zmax_data", "ss_live", "l5_autolabel", ts)
    ld = os.path.join(od, "labels")
    os.makedirs(ld, exist_ok=True)
    print("[l5_autolabel] 输出 %s" % od, flush=True)

    vlm = SceneVLM.get()
    print("[l5_autolabel] VLM 通道: %s" % ("本地Qwen" if getattr(vlm, "local", False)
                                          else ("HTTP %s" % vlm.url if vlm.url else "deepseek")), flush=True)

    n_ok = n_obj = 0
    meta = open(os.path.join(od, "meta.jsonl"), "w")
    for i in range(a.n):
        try:
            cursor = _getj(AR).get("cursor")
        except Exception:                                               # noqa: BLE001
            cursor = None
        try:
            raw = _get(CAM)
        except Exception as e:                                          # noqa: BLE001
            print("  [%d] 抓帧失败: %s" % (i, str(e)[:60]), flush=True)
            time.sleep(a.every)
            continue
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            print("  [%d] 解帧失败" % i, flush=True)
            time.sleep(a.every)
            continue
        h, w = im.shape[:2]

        t0 = time.time()
        try:
            r = vlm.ask(im, PROMPT, max_tokens=400)
        except Exception as e:                                          # noqa: BLE001
            print("  [%d] VLM 失败: %s: %s" % (i, type(e).__name__, str(e)[:90]), flush=True)
            time.sleep(a.every)
            continue
        dt = time.time() - t0
        # ask() 只回 text, json 要自己解 (describe() 内部才做 json 化)
        j = (r or {}).get("json") or {}
        if not j:
            try:
                from lerobot.policies.left_right.state_space.scene_vlm import _json_from
                j = _json_from((r or {}).get("text")) or {}
            except Exception:                                           # noqa: BLE001
                j = {}
        stage = str(j.get("stage") or "").strip()
        objs = j.get("objects") or []

        fn = "frame_%04d" % i
        open(os.path.join(od, fn + ".jpg"), "wb").write(raw)
        lines = []
        for o in objs:
            try:
                bb = [float(v) for v in (o.get("bbox_px") or [])]
                if len(bb) != 4:
                    continue
                cf = float(o.get("conf") or 0)
                if cf < a.min_conf:
                    continue
                x1, y1, x2, y2 = bb
                x1, x2 = max(0, min(w, x1)), max(0, min(w, x2))
                y1, y2 = max(0, min(h, y1)), max(0, min(h, y2))
                if x2 <= x1 or y2 <= y1:
                    continue
                cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
                bw, bh = (x2 - x1) / w, (y2 - y1) / h
                cls = 0 if str(o.get("name", "")).lower().startswith("peg") else 1
                lines.append("%d %.6f %.6f %.6f %.6f" % (cls, cx, cy, bw, bh))
                n_obj += 1
            except Exception:                                           # noqa: BLE001
                continue
        open(os.path.join(ld, fn + ".txt"), "w").write("\n".join(lines) + ("\n" if lines else ""))
        rec = {"frame": fn, "cursor": cursor, "tcp": None, "stage": stage,
               "objects": objs, "can_grasp": j.get("can_grasp"), "note": j.get("note"),
               "vlm_ok": bool((r or {}).get("ok")), "vlm_secs": round(dt, 2),
               "n_labels": len(lines), "why": (r or {}).get("why")}
        meta.write(json.dumps(rec, ensure_ascii=False) + "\n")
        meta.flush()
        if lines:
            n_ok += 1
        print("  [%d] cursor=%s stage=%s objects=%d → 标 %d 框 (%.1fs) %s"
              % (i, cursor, stage or "?", len(objs), len(lines), dt, str(j.get("note") or "")[:40]), flush=True)

        # 最新一帧的语义也写给 L5Guide (ss_mani_eng 会读)
        try:
            json.dump({"ts": time.time(), "stage": stage, "conf": 0.6 if stage else 0.0,
                       "label": str(j.get("note") or ""), "vec": None,
                       "src": "l5_autolabel:%s" % fn, "cursor": cursor,
                       "objects": objs, "can_grasp": j.get("can_grasp")},
                      open(UND + ".tmp", "w"), ensure_ascii=False)
            os.replace(UND + ".tmp", UND)
        except Exception:                                               # noqa: BLE001
            pass
        time.sleep(a.every)

    meta.close()
    print("\n[l5_autolabel] 完成: %d 帧, %d 帧有标注, 共 %d 个框" % (a.n, n_ok, n_obj), flush=True)
    print("[l5_autolabel] 目录 %s" % od, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
