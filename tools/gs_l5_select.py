#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_l5_select.py — **L5 指导选点**(3DGS 主动建图: 下一步去哪里拍)

老倪(2026-10-01): 「建图是 L5 功能运行后, deepseek 给出环境理解, 指导 3DGS 建图,
                一边移动机器人, 一边自己学环境, 一边建立场景视图」

本工具就是那条闭环里的"**选点**"环节: 拿当前采集到的画面 + 已访问视点,
让 L5 视觉大模型给出**环境理解**(看到什么/哪些区域没看全), 并给出下一步该去的位置;
软件把它的"画面方向"翻译成 base_link 目标点(经手眼链路), 并做可达性/新颖度打分。

设计要点(踩过的坑都固化了):
  · L5 只会说"画面左/右/上/下/靠近/远离"这类**图内方向**; 换到 base 系必须由软件用
    T_base_cam = T_base_tcp · T_cam2tool 做,**不让大模型猜 base 坐标**(量纲会漂)。
  · DeepSeek 是推理型: max_tokens 不足时 content 为空 ⇒ 必须给够(ZMAX_L5_VLM_MAXTOK, 默认 2000)
    且单次实测 ~120s ⇒ timeout 默认 300s。
  · L5 失败/超时/JSON 不合规 ⇒ **不假装成功**: 退回**覆盖度兜底**(确定性算法), 并在输出里如实记 err。
  · 候选点一律做可达性粗筛(已知空间点 bbox 外扩)/新颖度打分; 不可达的如实标 reachable=false。

用法:
  gs_l5_select.py --dataset ~/zmax/zmax_data/gs_assets/<scene> [--k 3] [--out sel.json]
  gs_l5_select.py --session ~/zmax/zmax_data/gs_scan/<sess>  [--k 3]
  gs_l5_select.py --dataset ... --no-llm        # 只用覆盖度兜底(不调大模型)
输出: <out 或 输入目录>/l5_select_<ts>.json + 一行摘要(stdout)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ⚠️ 2026-10-01 实测(同一批图重跑 3 次, 2000 额度下 3/3 失败): DeepSeek 是**推理型**模型 ——
#    max_tokens=2000 时 reasoning 常常把额度吃光, 表现为 content 空、或只吐半句思考
#    ("We need answer JSON only…") ⇒ L5 只能退兜底。给 4000 实测 **19.1s 稳定出真 JSON**;
#    给 6000 也成但要 162s(推理越多越慢)。这里只给**本工具**定 4000, 不动全局默认
#    (叠加标注那条链另有延迟要求), 需要时用同名 env 覆盖。
os.environ.setdefault("ZMAX_L5_VLM_MAXTOK", "4000")

import numpy as np

REPO = "/home/ubuntu/zmax"
ZMAX_DATA = os.path.expanduser("~/zmax/zmax_data")
HANDEYE_F = os.path.join(ZMAX_DATA, "handeye_state.json")
SPACE_F = os.path.join(REPO, "data/skills/l2_atomic/space_points.json")
sys.path.insert(0, os.path.join(REPO, "tools"))

# ---------------------------------------------------------------- 数据装载

def quat_to_R(q):
    x, y, z, w = q
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def T_of(pos, quat):
    T = np.eye(4)
    T[:3, :3] = quat_to_R(quat)
    T[:3, 3] = pos
    return T


def load_dataset(d):
    """数据集: cameras.json(已是 T_cam2world) → [(name, path, T_cam2world, pos)]"""
    cj = json.load(open(os.path.join(d, "cameras.json"), encoding="utf-8"))
    out = []
    for f in cj["frames"]:
        p = os.path.join(d, "images", f["file"])
        if os.path.exists(p):
            out.append({"name": f["file"], "path": p,
                        "T": np.array(f["T_cam2world"], float), "pos": np.array(f["pos"], float)})
    return out, cj


def load_session(s):
    """扫描会话: frames.jsonl + frames/ → 取每张唯一图(内容 md5 变才换)首次出现的位姿"""
    import hashlib
    he = json.load(open(HANDEYE_F, encoding="utf-8"))
    Tt = np.array(he["T_cam2tool"], float).reshape(4, 4)      # cam → tool
    seen, out = set(), []
    for ln in open(os.path.join(s, "frames.jsonl"), encoding="utf-8"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if not r.get("file"):
            continue
        p = r.get("pose_after") or r.get("pose_before") or {}
        if not all(k in p for k in ("x", "y", "z", "qx", "qy", "qz", "qw")):
            continue
        fp = os.path.join(s, "frames", r["file"])
        if not os.path.exists(fp):
            continue
        h = hashlib.md5(open(fp, "rb").read()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        T_base_tcp = T_of(np.array([p["x"], p["y"], p["z"]], float),
                          [p["qx"], p["qy"], p["qz"], p["qw"]])
        out.append({"name": r["file"], "path": fp, "T": T_base_tcp @ Tt,
                    "pos": (T_base_tcp @ Tt)[:3, 3], "T_base_tcp": T_base_tcp})
    return out, {"convention": "T_cam2world (=T_base_tcp·T_cam2tool)", "n_frames": len(out)}


# ---------------------------------------------------------------- 覆盖度/几何

def visited_regions(frames, cur_pos):
    P = np.array([f["pos"] for f in frames]) if frames else np.zeros((0, 3))
    if len(P) < 2:
        return {"n": len(P), "spread_mm": [0, 0, 0], "distinct_views": len(P),
                "nearest_mm": 0.0, "covered_dirs": []}
    q = np.round(P / 0.005).astype(int)
    uniq = len({tuple(v) for v in q})
    d = np.linalg.norm(P - cur_pos, axis=1)
    # 已覆盖方向(以场景中心为球心, 8 方位)
    ctr = P.mean(0)
    dirs = set()
    for p in P:
        v = p - ctr
        n = np.linalg.norm(v)
        if n < 1e-6:
            continue
        v = v / n
        az = int(np.floor((np.degrees(np.arctan2(v[1], v[0])) + 180) / 45)) % 8
        dirs.add(az)
    return {"n": len(P), "spread_mm": [round(float(x) * 1000, 1) for x in (P.max(0) - P.min(0))],
            "distinct_views": uniq, "nearest_mm": round(float(d.min()) * 1000, 1),
            "covered_dirs": sorted(dirs)}


def space_bbox():
    """已知空间点(1..7)的包络 —— 可达性粗筛用; 缺文件 ⇒ None(不假装有)"""
    try:
        pts = json.load(open(SPACE_F, encoding="utf-8"))["points"]
    except Exception:
        return None, []
    P = np.array([[float(v) for v in d["pos"]] for d in pts.values() if isinstance(d, dict) and d.get("pos")])
    if len(P) == 0:
        return None, []
    return (P.min(0) - 0.05, P.max(0) + 0.05), list(pts.keys())


def in_reach(p, box):
    if box is None:
        return True
    lo, hi = box
    return bool(np.all(p >= lo) and np.all(p <= hi))


# ---------------------------------------------------------------- 候选生成

def coverage_candidates(frames, cur_pos, cur_T, k, box, radius_mm=(30, 50, 80)):
    """覆盖度兜底(确定性): 在相机系里绕一圈方向 × 几档距离, 打分 = 新颖度 - 不可达惩罚。
    新颖度 = 与"已访问视点"的最近距离(越远越没拍过)。"""
    P = np.array([f["pos"] for f in frames]) if frames else np.zeros((0, 3))
    R = cur_T[:3, :3]
    cands = []
    dirs = {"画面左": [-1, 0, 0], "画面右": [1, 0, 0], "画面上": [0, -1, 0], "画面下": [0, 1, 0],
            "靠近": [0, 0, 1], "远离": [0, 0, -1]}
    for nm, v in dirs.items():
        for r in radius_mm:
            off = R @ (np.array(v, float) * (r / 1000.0))
            p = cur_pos + off
            nov = float(np.min(np.linalg.norm(P - p, axis=1))) if len(P) else 1.0
            reach = in_reach(p, box)
            cands.append({"pos": [round(float(x), 4) for x in p], "dir": nm, "dist_mm": r,
                          "why": "覆盖度兜底: 该方向已访问视点最近 %.0fmm" % (nov * 1000),
                          "source": "coverage", "score": round(nov * 1000 * (1.0 if reach else 0.1), 1),
                          "reachable": reach})
    cands.sort(key=lambda c: -c["score"])
    return cands[:k]


DIR_CAM = {"画面左": [-1, 0, 0], "画面右": [1, 0, 0], "画面上": [0, -1, 0], "画面下": [0, 1, 0],
           "靠近": [0, 0, 1], "远离": [0, 0, -1], "左上": [-0.7, -0.7, 0], "右上": [0.7, -0.7, 0],
           "左下": [-0.7, 0.7, 0], "右下": [0.7, 0.7, 0]}


def l5_candidates(js, cur_pos, cur_T, box):
    """把 L5 的"画面方向"翻译成 base 系目标点(经 T_base_cam 的旋转)"""
    out = []
    for c in (js.get("next_views") or [])[:3]:
        d = str(c.get("dir") or "").strip()
        v = DIR_CAM.get(d)
        if v is None:
            continue
        try:
            mm = float(c.get("dist_mm") or 50)
        except Exception:
            mm = 50.0
        mm = max(10.0, min(200.0, mm))
        off = cur_T[:3, :3] @ (np.array(v, float) * (mm / 1000.0))
        p = cur_pos + off
        out.append({"pos": [round(float(x), 4) for x in p], "dir": d, "dist_mm": mm,
                    "why": str(c.get("why") or "")[:80], "source": "l5",
                    "reachable": in_reach(p, box), "score": None})
    return out


# ---------------------------------------------------------------- 拼图 / L5

def montage(paths, cols=2, tile=(384, 288)):
    """把若干帧拼成一张图(送 L5) —— 只依赖 PIL, 不引入新依赖"""
    from PIL import Image, ImageDraw
    if not paths:
        return None, 0, 0
    paths = paths[:4]
    rows = int(np.ceil(len(paths) / cols))
    W, H = tile[0] * cols, tile[1] * rows
    canvas = Image.new("RGB", (W, H), (16, 16, 16))
    dr = ImageDraw.Draw(canvas)
    for i, (p, label) in enumerate(paths):
        try:
            im = Image.open(p).convert("RGB").resize(tile)
        except Exception:
            continue
        x, y = (i % cols) * tile[0], (i // cols) * tile[1]
        canvas.paste(im, (x, y))
        dr.rectangle([x + 2, y + 2, x + 84, y + 20], fill=(0, 0, 0))
        dr.text((x + 6, y + 5), label, fill=(255, 255, 0))
    import io
    b = io.BytesIO()
    canvas.save(b, format="JPEG", quality=88)
    return b.getvalue(), W, H


L5_PROMPT = """你是 Z-MAX 具身智能平台的 **L5 视觉理解层**。机械臂末端相机正在**边移动边扫场**, 目标是给整个工作场景做 3D 重建(3DGS)。
图是按时间均匀抽样的**多帧拼图**(左上角写的是抽样序号), 都是臂上相机实拍; 相机可能倒置, 物体朝画面中心。

当前状态: 机械臂 TCP 在 base 系 (X={x:.3f}, Y={y:.3f}, Z={z:.3f}) m; 共已访问 {nv} 个视点, 位姿跨度 {sp} mm。

请给出**环境理解 + 下一步该去哪拍**(重点看"哪块区域还没看全"):
· scene: 一句话场景理解(你在看什么工位/什么东西)
· regions: 画面里能看到的东西 [{{name, seen:"good|partial|bad", why}}]  (最多 5 条)
· missing: 目前**看不全/可能没拍过**的区域或物体(用来决定去哪儿补拍)  (最多 4 条)
· next_views: 下一步该去的位置, 用**相对当前相机的画面方向**表示(不要给坐标!):
  [{{"dir":"画面左|画面右|画面上|画面下|靠近|远离|左上|右上|左下|右下", "dist_mm": 30-80 之间的整数, "why":"为什么去这里(15字内)"}}]
  最多 3 条; 没有把握就给 1 条。

只输出一个 JSON(不要 markdown 代码块、不要解释文字):
{{"scene":"...","regions":[{{"name":"...","seen":"good","why":"..."}}],"missing":["..."],"next_views":[{{"dir":"画面左","dist_mm":40,"why":"..."}}]}}"""


def call_l5(mont, w, h, cur_pos, nv, sp):
    import gen_overlay_from_vlm as G
    pr = L5_PROMPT.format(x=cur_pos[0], y=cur_pos[1], z=cur_pos[2], nv=nv, sp=sp)
    r = G.call_vlm(mont, w, h, timeout=300, prompt=pr)
    # ⚠️ call_vlm 返回的键是 "txt"(不是 "text"); 200 但 content 空是已知瞬态, 此时会在
    #    call_vlm 内部重试, 仍空则 txt="" —— 退一步从 reasoning 里捞 JSON, 捞不到就如实报错。
    txt = (r.get("txt") if isinstance(r, dict) else str(r)) or ""
    if not txt.strip() and isinstance(r, dict):
        txt = (r.get("reasoning") or "").strip()
    m = txt.find("{")
    n = txt.rfind("}")
    if m < 0 or n <= m:
        raise ValueError("L5 未返回 JSON: %s" % txt[:120])
    return json.loads(txt[m:n + 1]), txt


def call_l5_budgeted(mont, w, h, cur_pos, nv, sp, budget_s):
    """给 L5 一个**硬墙钟预算**: 超时就放弃(退覆盖度), 不让一次网络卡顿把整轮扫描拖住。
    ⚠️ 2026-10-01 踩到: 闸门化之后 L5 走云端(api.deepseek.com), 端点不通时 urllib 在
    socket.create_connection 里**干等**(call_vlm 内部还有 4 次退避重试) ⇒ 实测卡 5m44s
    (`timeout 300` 都没能兜住), 换成"线程 + join(budget)"才真的能按时收手。"""
    import threading
    box = {}

    def _work():
        try:
            box["ok"] = call_l5(mont, w, h, cur_pos, nv, sp)
        except Exception as e:                                   # noqa: BLE001
            box["err"] = "%s: %s" % (type(e).__name__, str(e)[:150])

    t = threading.Thread(target=_work, daemon=True)
    t0 = time.time()
    t.start()
    t.join(max(5.0, float(budget_s)))
    if t.is_alive():
        raise TimeoutError("L5 超过 %.0fs 没返回(云端不通/限流) ⇒ 退覆盖度兜底" % budget_s)
    if "err" in box:
        raise RuntimeError(box["err"])
    print("L5 用时 %.1fs" % (time.time() - t0))
    return box["ok"]


# ---------------------------------------------------------------- 主

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dataset")
    g.add_argument("--session")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--out", default="")
    ap.add_argument("--no-llm", action="store_true", help="不调大模型, 只用覆盖度兜底")
    ap.add_argument("--l5-timeout", type=float, default=180.0,
                    help="L5 硬墙钟预算(秒, 默认 180): 超时才退覆盖度兜底。"
                         "⚠️ 实测云端单次耗时会从 19s 摆到 149s(取决于端点负载), 预算给太紧会把"
                         "\"慢但会成功\"的调用砍掉; 180s 既兜住实测最慢值, 又保证坏端点不无限拖")
    ap.add_argument("--pose", default="", help="当前 TCP 位姿 x,y,z(米); 缺省用最后一帧")
    args = ap.parse_args()

    t0 = time.time()
    src = args.dataset or args.session
    if args.session and not os.path.exists(os.path.join(args.session, "frames.jsonl")):
        # 第一轮常常是"会话刚建好、还没采到帧" ⇒ 别报错崩, 如实说清并退 0
        # (调用方 gs_map_run 会据此走覆盖度兜底选点, 下一轮 L5 就有画面可看了)
        msg = "会话里还没有帧(%s 没有 frames.jsonl) ⇒ L5 无画面可看" % args.session
        print("⚠️ %s" % msg)
        if args.out:
            json.dump({"ts": time.strftime("%F %T"), "src": os.path.abspath(src), "n_frames": 0,
                       "l5_used": False, "l5_err": msg, "l5_scene": "", "l5_regions": [],
                       "l5_missing": [], "candidates": [], "note": "没有帧, 未产出候选"},
                      open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return 0
    frames, meta = (load_dataset(args.dataset) if args.dataset else load_session(args.session))
    if not frames:
        print("❌ 没有可用帧: %s" % src)
        return 2
    cur = frames[-1]
    cur_pos = np.array([float(v) for v in args.pose.split(",")], float) if args.pose else cur["pos"]
    # 当前相机姿态: 数据集只有 T_cam2world; 会话里有 T_base_tcp
    cur_T = cur["T"]
    T_base_cam = cur_T
    box, spts = space_bbox()
    reg = visited_regions(frames, cur_pos)
    print("输入 %s · 唯一帧 %d · 已访问视点 %d · 跨度 %s mm · 空间点 %d 个"
          % (src, len(frames), reg["distinct_views"], reg["spread_mm"], len(spts)))

    # ---- L5 大模型(可关) ----
    l5_js, l5_raw, err = None, "", ""
    if not args.no_llm:
        # 抽样: 时间均匀 4 帧(含最远的一帧, 让 L5 看到不同视角)
        step = max(1, len(frames) // 4)
        picks = [(frames[i], "T%d" % i) for i in range(0, len(frames), step)][:4]
        mont, W, H = montage([(f["path"], lb) for f, lb in picks])
        if not mont:
            raise ValueError("拼图失败(没有可读帧)")
        try:
            l5_js, l5_raw = call_l5_budgeted(mont, W, H, cur_pos, reg["distinct_views"],
                                             int(max(reg["spread_mm"]) if reg["spread_mm"] else 0),
                                             args.l5_timeout)
            print("L5 返回: %s" % json.dumps({k: l5_js.get(k) for k in ("scene", "next_views")},
                                             ensure_ascii=False)[:300])
        except Exception as e:                                       # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, str(e)[:150])
            print("⚠️ L5 失败, 退回覆盖度兜底: %s" % err)

    cands = l5_candidates(l5_js or {}, cur_pos, T_base_cam, box)
    if not cands:
        cands = coverage_candidates(frames, cur_pos, T_base_cam, args.k, box)
        if not cands:
            print("❌ 连覆盖度候选都生成不出来")
            return 3
    # 兜底候选补在 L5 候选后面(保证总有可执行的)
    if l5_js:
        extra = coverage_candidates(frames, cur_pos, T_base_cam, args.k, box)
        known = {tuple(c["pos"]) for c in cands}
        cands += [c for c in extra if tuple(c["pos"]) not in known]
    out = {"ts": time.strftime("%F %T"), "src": os.path.abspath(src), "n_frames": len(frames),
           "cur_pos": [round(float(v), 4) for v in cur_pos], "coverage": reg,
           "space_points": spts, "reach_box": None if box is None else
           [[round(float(v), 4) for v in box[0]], [round(float(v), 4) for v in box[1]]],
           "l5_used": bool(l5_js), "l5_scene": (l5_js or {}).get("scene", ""),
           "l5_regions": (l5_js or {}).get("regions", []), "l5_missing": (l5_js or {}).get("missing", []),
           "l5_raw": l5_raw[:3000], "l5_err": err,
           "candidates": cands[:args.k], "elapsed_s": round(time.time() - t0, 1),
           "note": "L5 gives image-frame directions; base-frame targets are computed by the software "
                   "via T_base_cam = T_base_tcp·T_cam2tool (大模型不猜 base 坐标)"}
    op = args.out or os.path.join(os.path.abspath(src), "l5_select_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    head = cands[0]
    print("✅ 选点 → %s" % op)
    print("   首选: %s %smm → base %s (source=%s reachable=%s) · 依据: %s"
          % (head["dir"], head.get("dist_mm"), head["pos"], head["source"], head["reachable"], head["why"]))
    if l5_js:
        print("   L5 场景理解: %s" % str(l5_js.get("scene"))[:110])
        if l5_js.get("missing"):
            print("   L5 认为没看全: %s" % "; ".join(str(x) for x in l5_js["missing"])[:160])
    return 0


if __name__ == "__main__":
    sys.exit(main())
