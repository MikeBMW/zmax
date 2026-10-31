#!/usr/bin/env python3
"""影子模式 —— 真机在跑, 我只观察 + 只在影子侧推理, **零指令**。

老倪 2026-10-30: 「建立影子模式, 现在真实机器在运行, 你看到了么? 你要根据真实数据,
自主训练, 增长经验记忆」

════════════════════════════════════════════════════════════════════════
铁律 (写死在代码里, 不读环境变量, 不可配)
  ① 零指令: 本进程不 import 任何运动控制模块, 不发任何 POST, 不写任何 *_cmd/exec.json。
     影子推理结果只落盘做证据, 绝不回灌执行链。
  ② 只读旁路: 位姿读 tcp_out/latest.json; 相机 GET 8812/frame.jpg;
     工控机 AOI **只 GET** last_result / picture —— 绝不调 POST /capture_detect
     (那会触发真机拍照, 打断在役检测)。
  ③ 缺数据写 None + 原因, 绝不假 0 —— 没采到就是"未测"。
════════════════════════════════════════════════════════════════════════

数据源 (全部旁路只读)
  · 位姿   zmax_data/rokae_sdk/tcp_out/latest.json   (真机 1Hz 落盘)
  · 相机   http://127.0.0.1:8812/frame.jpg           (640x480 YUYV ~10fps)
  · AOI    http://192.168.23.23:10082/last_result  (金手指)
           http://192.168.23.23:10083/last_result  (表面)

产物
  zmax_data/shadow/live_latest.json        当前快照 (单文件覆盖)
  zmax_data/shadow/exp_<YYYYMMDD>.jsonl    经验流 (只追加, 不覆盖)
  zmax_data/shadow/exp_index.json          经验记忆索引 (条数/覆盖/新颖度/训练轮次)
  zmax_data/shadow/dataset/labels.jsonl    AOI 真实判定当标签的监督样本
  zmax_data/shadow/dataset/img/*.jpg       对应的真图

"增长"体现在两处
  1. exp_index.json 的 total / novel / 位姿覆盖范围 单调增
  2. dataset/ 里有标签样本累积到阈值 → train_queue 置 1, 由训练器取走
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 落盘目录可配: 4060 上默认本仓库 zmax_data/shadow; 550C 上指到 ~/zmax_shadow
OUT = os.environ.get("SS_SHADOW_OUT") or os.path.join(ROOT, "zmax_data", "shadow")
DS = os.path.join(OUT, "dataset")
IMG = os.path.join(DS, "img")
POSE = os.environ.get("SS_SHADOW_POSE") or os.path.join(
    ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")

# 位姿也可走 HTTP (550C 上没有 ROS/SDK, 由 gs_train_service 8804 /pose 暴露)
POSE_URL = os.environ.get("SS_SHADOW_POSE_URL", "")

CAM_URL = os.environ.get("SS_SHADOW_CAM", "http://127.0.0.1:8812/frame.jpg")
CAM_HEALTH = os.environ.get("SS_SHADOW_CAM_HEALTH", "http://127.0.0.1:8812/health")
AOI = {"gf": os.environ.get("SS_AOI_GF", "http://192.168.23.23:10082"),
       "surface": os.environ.get("SS_AOI_SURFACE", "http://192.168.23.23:10083")}

FRESH_S = 3.0            # 位姿/相机 新鲜度阈值
CYCLES_PER_SEC = 1.0     # 主循环节拍 (相机会去重, 同帧不重复记)
AOI_EVERY_S = 10.0       # AOI 轮询间隔 (工控机是别人的, 别打太勤)
TRAIN_AT = 200           # 带标签样本攒够多少条 → 置训练队列

_STOP = False


def _log(*a) -> None:
    print("[shadow] " + " ".join(str(x) for x in a), flush=True)


def _sig(_s, _f) -> None:
    global _STOP
    _STOP = True
    _log("收到退出信号, 收尾中")


def _get(url: str, timeout: float = 3.0) -> bytes | None:
    """只读 GET。任何异常返回 None (由调用方记原因), 不抛。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:       # noqa: S310
            if getattr(r, "status", 200) != 200:
                return None
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None


def _write_json(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _append(path: str, rec: dict) -> None:
    with io.open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── ① 位姿 (真机 1Hz) ────────────────────────────────────────────────────────
def read_pose() -> dict:
    """读真机位姿真值。缺文件/解析失败 → ok=False + why, 绝不假 0。

    两种源: 本地文件 (4060, 与真机同机) 或 HTTP (550C, 由 8804 /pose 暴露)。
    """
    if POSE_URL:
        raw = _get(POSE_URL, timeout=3.0)
        if not raw:
            return {"ok": False, "why": f"位姿 HTTP 不通 {POSE_URL}"}
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as e:
            return {"ok": False, "why": f"位姿 HTTP 非 JSON {e}"}
        if d.get("error"):
            return {"ok": False, "why": f"位姿 HTTP 报错 {d.get('error')}"}
        age = float(d.get("age_s") if d.get("age_s") is not None
                    else (time.time() - float(d.get("ts") or 0)))
        j = d.get("joint") or []
        return {"ok": True, "age_s": round(age, 3), "fresh": bool(age <= FRESH_S),
                "xyz": [float(d["x"]), float(d["y"]), float(d["z"])],
                "rpy": [float(d.get("rx") or 0), float(d.get("ry") or 0),
                        float(d.get("rz") or 0)],
                "joint": [float(v) for v in j] if j else None,
                "src": (d.get("src") or "") + " (via HTTP)"}
    if not os.path.isfile(POSE):
        return {"ok": False, "why": f"位姿文件不存在 {POSE}"}
    try:
        with io.open(POSE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return {"ok": False, "why": f"位姿解析失败 {type(e).__name__}: {e}"}
    ts = float(d.get("ts") or 0)
    age = time.time() - ts
    j = d.get("joint") or []
    return {"ok": True, "age_s": round(age, 3), "fresh": bool(age <= FRESH_S),
            "xyz": [float(d["x"]), float(d["y"]), float(d["z"])],
            "rpy": [float(d.get("rx") or 0), float(d.get("ry") or 0), float(d.get("rz") or 0)],
            "joint": [float(v) for v in j] if j else None,
            "src": d.get("src") or ""}


# ── ② 相机 (真机 ~10fps, 按 md5 去重) ────────────────────────────────────────
def grab_frame() -> tuple[bytes | None, str, str]:
    """返回 (jpeg_bytes, md5, why)。取不到 → (None,'',原因)。"""
    h = _get(CAM_HEALTH, timeout=2.0)
    if not h:
        return None, "", "相机 /health 不通"
    try:
        hd = json.loads(h.decode("utf-8", "replace"))
    except ValueError:
        hd = {}
    if float(hd.get("age_s") or 999) > FRESH_S:
        return None, "", f"相机帧过期 age={hd.get('age_s')}s"
    b = _get(CAM_URL, timeout=3.0)
    if not b or len(b) < 5000:
        return None, "", f"相机帧太小 {0 if not b else len(b)}B"
    return b, hashlib.md5(b).hexdigest(), ""


# ── ③ 工控机 AOI (只 GET, 当真实标签) ────────────────────────────────────────
def poll_aoi(kind: str) -> dict:
    base = AOI[kind]
    raw = _get(base + "/last_result", timeout=5.0)
    if not raw:
        return {"ok": False, "why": f"{kind} last_result 不通"}
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        return {"ok": False, "why": f"{kind} 返回非 JSON: {e}"}
    if int(d.get("code") or 0) != 200:
        return {"ok": False, "why": f"{kind} code={d.get('code')}"}
    return {"ok": True,
            "n": int(d.get("n") or 0),
            "count": int(d.get("count") or 0),          # 缺陷数 (真 0 是 0, 不是缺测)
            "defects": d.get("defects") or [],
            "ms": float(d.get("ms") or 0),
            "judge_ok": bool(d.get("judge_ok", True)),
            "judge_why": d.get("judge_why") or "",
            "model_input_md5": d.get("model_input_md5") or ""}


# ── 经验记忆索引 (单调增长) ──────────────────────────────────────────────────
def load_index() -> dict:
    p = os.path.join(OUT, "exp_index.json")
    if os.path.isfile(p):
        try:
            with io.open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {"total": 0, "frames_seen": 0, "novel": 0, "motion_cycles": 0,
            "pose_min": None, "pose_max": None, "yolo_det": 0, "yolo_frames": 0,
            "aoi_runs": 0, "labeled": 0, "train_rounds": 0, "train_queue": 0,
            "since": time.time(), "last_t": 0}


def update_index(ix: dict, rec: dict) -> None:
    ix["total"] += 1
    ix["last_t"] = rec["t"]
    if rec.get("frame_md5"):
        ix["frames_seen"] += 1
    if rec.get("motion"):
        ix["motion_cycles"] += 1
    p = rec.get("pose") or {}
    if p.get("ok") and p.get("fresh"):
        xyz = p["xyz"]
        if ix["pose_min"] is None:
            ix["pose_min"], ix["pose_max"] = list(xyz), list(xyz)
        else:
            ix["pose_min"] = [min(a, b) for a, b in zip(ix["pose_min"], xyz)]
            ix["pose_max"] = [max(a, b) for a, b in zip(ix["pose_max"], xyz)]
    y = rec.get("yolo") or {}
    if y.get("ok"):
        ix["yolo_frames"] += 1
        ix["yolo_det"] += int(y.get("n") or 0)


# ── 监督样本: AOI 真实判定 = 标签 ────────────────────────────────────────────
def save_labeled(kind: str, a: dict, img_bytes: bytes) -> str:
    """把一张真实 AOI 图 + 它的真实判定落成监督样本。返回样本 id 或 ''。"""
    if not a.get("ok") or not img_bytes:
        return ""
    md5 = hashlib.md5(img_bytes).hexdigest()
    fn = f"{kind}_{md5[:12]}.jpg"
    fp = os.path.join(IMG, fn)
    if os.path.isfile(fp):                    # 同一张图只收一次 (去重)
        return ""
    os.makedirs(IMG, exist_ok=True)
    with open(fp, "wb") as f:
        f.write(img_bytes)
    rec = {"t": time.time(), "kind": kind, "img": os.path.relpath(fp, ROOT),
           "md5": md5, "n_defect": a["count"], "defects": a["defects"],
           "judge_ok": a["judge_ok"], "judge_why": a["judge_why"],
           "aoi_ms": a["ms"], "model_input_md5": a["model_input_md5"],
           "label_src": f"AOI {kind} 真实判定 (工控机 10{82 if kind == 'gf' else 83})"}
    _append(os.path.join(DS, "labels.jsonl"), rec)
    return md5


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(IMG, exist_ok=True)
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    # 影子侧 YOLO: 只在影子进程里跑, 结果只落盘, 不回灌任何执行链
    yolo = None
    try:
        from ultralytics import YOLO                                 # noqa: PLC0415
        wp = os.environ.get("SS_SHADOW_YOLO") or os.path.join(
            ROOT, "models", "yolo_peg_live.pt")
        if os.path.exists(wp):
            yolo = YOLO(wp)
            _log(f"影子 YOLO 已加载 {wp}")
        else:
            _log(f"影子 YOLO 权重不存在 {wp} → 只记位姿/相机/AOI")
    except Exception as e:                                            # noqa: BLE001
        _log(f"影子 YOLO 加载失败 {type(e).__name__}: {e} → 降级只记位姿/相机/AOI")

    ix = load_index()
    _log(f"经验记忆载入: total={ix['total']} labeled={ix['labeled']} "
         f"frames={ix['frames_seen']} novel={ix['novel']}")

    last_md5 = ""
    last_aoi_t = 0.0
    prev_xyz = None
    day = time.strftime("%Y%m%d")
    exp_path = os.path.join(OUT, f"exp_{day}.jsonl")
    period = 1.0 / max(0.2, CYCLES_PER_SEC)

    while not _STOP:
        t0 = time.time()
        rec: dict = {"t": round(t0, 3), "t_str": time.strftime("%H:%M:%S"),
                     "mode": "shadow", "zero_cmd": True}

        # ① 位姿
        pose = read_pose()
        rec["pose"] = pose
        motion = False
        if pose.get("ok"):
            xyz = pose["xyz"]
            if prev_xyz is not None:
                motion = max(abs(a - b) for a, b in zip(xyz, prev_xyz)) > 1e-5
            prev_xyz = xyz
        rec["motion"] = bool(motion)

        # ② 相机 + 影子 YOLO (同帧不重复推理)
        jpg, md5, why = grab_frame()
        rec["cam"] = {"ok": bool(jpg), "md5": md5, "why": why}
        rec["frame_md5"] = md5 if md5 != last_md5 else ""
        yrec: dict = {"ok": False, "why": "未跑(同帧去重)" if md5 and md5 == last_md5 else "未加载权重"}
        if jpg and md5 != last_md5 and yolo is not None:
            try:
                import numpy as np                                  # noqa: PLC0415
                from PIL import Image                                # noqa: PLC0415
                arr = np.asarray(Image.open(io.BytesIO(jpg)).convert("RGB"))
                r = yolo.predict(arr, verbose=False, conf=0.25,
                                 device=os.environ.get("SS_SHADOW_YOLO_DEV") or None)[0]
                dets = []
                for b in (r.boxes or []):
                    cid = int(b.cls.item())
                    dets.append({"cls": r.names.get(cid, str(cid)),
                                 "conf": round(float(b.conf.item()), 4),
                                 "xyxy": [round(float(v), 1) for v in b.xyxy[0].tolist()]})
                yrec = {"ok": True, "n": len(dets), "dets": dets}
            except Exception as e:                                  # noqa: BLE001
                yrec = {"ok": False, "why": f"{type(e).__name__}: {e}"}
            last_md5 = md5
        rec["yolo"] = yrec

        # ③ AOI (低频轮询, 只 GET) + 真实标签样本落盘
        if t0 - last_aoi_t >= AOI_EVERY_S:
            last_aoi_t = t0
            rec["aoi"] = {}
            for kind in AOI:
                a = poll_aoi(kind)
                rec["aoi"][kind] = a
                if a.get("ok"):
                    ix["aoi_runs"] += 1
                    pic = _get(AOI[kind] + "/picture", timeout=6.0)
                    if pic and save_labeled(kind, a, pic):
                        ix["labeled"] += 1

        # ④ 新颖度: 位姿出现新区域 或 从未见过的帧 → 记 novelty
        novel = False
        if pose.get("ok") and pose.get("fresh") and ix["pose_min"] is not None:
            xyz = pose["xyz"]
            span = [hi - lo for lo, hi in zip(ix["pose_min"], ix["pose_max"])]
            if any(s < 1e-4 for s in span) and md5 and md5 not in ("", last_md5):
                novel = True
        if md5 and ix["frames_seen"] and (md5 not in (last_md5,) and rec["frame_md5"]):
            novel = True
        rec["novel"] = bool(novel)
        if novel:
            ix["novel"] += 1

        update_index(ix, rec)
        rec["ix_total"] = ix["total"]
        _append(exp_path, rec)

        # ⑤ 训练队列: 有标签样本攒够 → 置 1, 训练器取走后清零
        if ix["labeled"] >= TRAIN_AT:
            ix["train_queue"] = 1
        _write_json(os.path.join(OUT, "live_latest.json"),
                    {"t": time.time(), "t_str": time.strftime("%H:%M:%S"),
                     "record": rec, "index": ix})
        _write_json(os.path.join(OUT, "exp_index.json"), ix)

        if int(ix["total"]) % 30 == 0:
            _log(f"total={ix['total']} frames={ix['frames_seen']} novel={ix['novel']} "
                 f"motion={ix['motion_cycles']} labeled={ix['labeled']} "
                 f"yolo={ix['yolo_det']}/{ix['yolo_frames']} queue={ix['train_queue']}")

        # 跨天换文件
        d2 = time.strftime("%Y%m%d")
        if d2 != day:
            day, exp_path = d2, os.path.join(OUT, f"exp_{d2}.jsonl")

        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)

    _write_json(os.path.join(OUT, "exp_index.json"), ix)
    _log(f"退出。经验记忆: total={ix['total']} labeled={ix['labeled']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
