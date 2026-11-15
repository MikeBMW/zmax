#!/usr/bin/env python3
"""grasp_seg_watch.py — 盯回放抓取段, 连抓帧看工件到底在不在视野 (2026-11-15)

背景: 全圈 60 帧 VLM 判读结果全是「看不清/空」, YOLO 的检出框全贴画面边缘(噪声)。
疑问: 是「相机视野看不到工件」还是「工件根本不在台上」?
办法: 只在抓取段(cursor 区间)高频抓帧 + 深度 + VLM, 每帧都存图, 事后可逐帧回看。

用法:
  ./gui-venv311/bin/python tools/grasp_seg_watch.py --lo 85 --hi 120 --every 1.0
输出: zmax_data/reports/grasp_seg/<ts>/{frame_cXXX.jpg, meta.jsonl, summary.json}
"""
from __future__ import annotations
import argparse, json, os, sys, time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
CAM = "http://127.0.0.1:8791/snapshot/arm.jpg"
DEPTH = "http://192.168.23.66:8795/depth.png"
AR = "http://127.0.0.1:8797/api/arm/step_traj/status"

PROMPT = """机械臂末端相机画面。只输出 JSON:
{"工件可见": "有/没有/看不清", "工件是什么": "简短", "在画面哪个区域": "左上/中央/右下/无",
 "画面主体": "一句话", "依据": "简短"}
看不清就写看不清, 不要猜。"""


def _get(u, t=6):
    with urllib.request.urlopen(u, timeout=t) as r:
        return r.read()


def _getj(u, t=6):
    return json.loads(_get(u, t).decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo", type=int, default=85)
    ap.add_argument("--hi", type=int, default=120)
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--vlm-every", type=float, default=4.0)
    a = ap.parse_args()

    import cv2
    import numpy as np
    from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM, _json_from

    od = os.path.join(REPO, "zmax_data", "reports", "grasp_seg", time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(od, exist_ok=True)
    print("[watch] 区间 %d~%d · 输出 %s" % (a.lo, a.hi, od), flush=True)
    vlm = SceneVLM.get()
    meta = open(os.path.join(od, "meta.jsonl"), "w")
    t_end = time.time() + a.seconds
    n_in = 0
    t_vlm = 0.0
    depth_stats = []
    vlm_rows = []

    while time.time() < t_end:
        try:
            cur = _getj(AR).get("cursor")
        except Exception:                                               # noqa: BLE001
            time.sleep(a.every); continue
        if cur is None or not (a.lo <= int(cur) <= a.hi):
            time.sleep(0.5); continue

        n_in += 1
        rec = {"ts": time.time(), "cursor": int(cur)}
        try:
            raw = _get(CAM)
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:                                          # noqa: BLE001
            rec["cam_err"] = str(e)[:60]; im = None
        if im is not None:
            fn = os.path.join(od, "frame_c%03d_n%d.jpg" % (int(cur), n_in))
            open(fn, "wb").write(raw)
            rec["img"] = fn
            rec["mean"] = round(float(im.mean()), 1)
            # 深度: 整幅统计 + 最近处
            try:
                dr = _get(DEPTH, 8)
                d = cv2.imdecode(np.frombuffer(dr, np.uint8), cv2.IMREAD_UNCHANGED)
                if d is not None and d.ndim == 2:
                    v = d[d > 0]
                    if v.size:
                        rec["depth"] = {"valid_pct": round(v.size / d.size * 100, 1),
                                        "min_mm": round(float(v.min()) / 10, 1),
                                        "med_mm": round(float(np.median(v)) / 10, 1),
                                        "max_mm": round(float(v.max()) / 10, 1)}
                        depth_stats.append(rec["depth"])
                    fn2 = os.path.join(od, "depth_c%03d_n%d.png" % (int(cur), n_in))
                    open(fn2, "wb").write(dr)
                    rec["depth_img"] = fn2
            except Exception as e:                                      # noqa: BLE001
                rec["depth_err"] = str(e)[:50]
            # VLM 限频
            if time.time() - t_vlm >= a.vlm_every:
                t_vlm = time.time()
                try:
                    r = vlm.ask(im, PROMPT, max_tokens=300)
                    j = _json_from(r.get("text")) or {}
                    rec["vlm"] = j
                    rec["vlm_ok"] = bool(r.get("ok"))
                    vlm_rows.append({"cursor": int(cur), **j})
                except Exception as e:                                  # noqa: BLE001
                    rec["vlm_err"] = "%s: %s" % (type(e).__name__, str(e)[:60])
        meta.write(json.dumps(rec, ensure_ascii=False) + "\n")
        meta.flush()
        print("  c%-4d %s %s %s" % (cur,
                                    ("mean=%.0f" % rec["mean"]) if "mean" in rec else "no-frame",
                                    ("depth med=%.0fmm" % rec["depth"]["med_mm"]) if rec.get("depth") else "",
                                    str((rec.get("vlm") or {}).get("工件可见") or "")[:20]), flush=True)
        time.sleep(a.every)

    meta.close()
    vis = {}
    for r in vlm_rows:
        k = str(r.get("工件可见") or "?")
        vis[k] = vis.get(k, 0) + 1
    summary = {"lo": a.lo, "hi": a.hi, "frames_in_seg": n_in, "vlm_calls": len(vlm_rows),
               "vlm_visible_dist": vis,
               "depth_frames": len(depth_stats),
               "depth_min_overall_mm": min([d["min_mm"] for d in depth_stats]) if depth_stats else None,
               "out": od}
    json.dump(summary, open(os.path.join(od, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print("\n[watch] 汇总:", json.dumps(summary, ensure_ascii=False)[:400], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
