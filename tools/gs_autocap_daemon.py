#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_autocap_daemon.py — 3DGS 自动采集 + 自主训练守护进程 (跑在 Intel)

老倪 2026-10-22: 「在intel上建立守护进程，只要有图像和机械臂操作，就自动记录图像和位姿，
自主决定训练3dgs图」

═══ 它做什么 ═══
  一直跑着, 盯两件事:
    ① Orin 臂上 D405 的画面   http://192.168.23.66:8792/frame.jpg   (实测 1.9ms, 29KB)
    ② 机械臂 TCP 真值位姿      http://192.168.23.50:8804/pose       (4060 从真源文件暴露)
  **只要机械臂在动**(位姿变化超阈值) 就同时抓图 + 记位姿, 配成对落盘。
  攒够一"趟"(帧数够 + 视角覆盖够 + 图像质量合格) 就自己打包丢给 4060 训 3DGS。
  训完把 .splat 拉回 Intel, 记台账。

═══ 为什么要 Intel 采而不是 4060 采 ═══
  Intel 16 核闲在那, 而 4060 的 GPU 要留给训练和在役引擎。
  采集是纯 IO + 判定, 放 Intel 正好。位姿和图像都是 HTTP 只读拉取, 不碰任何在役链路。

═══ 自主训练的四个判据 (不满足就不训, 免得喂垃圾) ═══
  1. 帧数 >= MIN_FRAMES                    —— 太少学不出
  2. 位姿跨度 >= MIN_SPAN_M                —— 相机没动够 = 视差不足, 3DGS 必糊
  3. 图像非全黑非静止                       —— 全黑/像素纹丝不动 = 相机没出图
  4. 距上次训练 >= COOLDOWN_S              —— 别把 GPU 堵死

═══ 铁律 ═══
  · 只发 GET 去拉图/位姿, 只发 POST 去 4060 训练服务; 不下发任何机械臂指令
  · 位姿 stale (age>3s) 或机械臂静止 → 不记帧 (记了也是重复视角)
  · 全部落盘: 每趟一个 session 目录 + 台账 jsonl, 可事后核
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import os.path as osp
import shutil
import tarfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import numpy as np

# ── 手眼外参 (相机固连在臂上, TCP 位姿 + 这个 X 才是相机位姿) ──
# 来源 models/handeye_state.json 的 T_cam2tool, 标定残差 0.06mm/0.005deg。
# 可用 GS_HANDEYE 指向别的 json; 置空字符串则退回"TCP 位姿即相机位姿"(仅供对照, 不推荐)。
_HANDEYE_PATH = os.environ.get("GS_HANDEYE",
                               osp.expanduser("~/zmax_map/models/handeye_state.json"))


def _load_handeye(path):
    if not path or not osp.exists(path):
        return None
    try:
        with open(path) as f:
            d = json.load(f)
        X = np.array(d["T_cam2tool"], dtype=np.float64)
        if X.shape != (4, 4):
            print("[handeye] T_cam2tool 不是 4x4, 忽略")
            return None
        print("[handeye] 已加载 %s | t_mm=%s | resid=%.3fmm/%.4fdeg"
              % (path, d.get("t_mm"), d.get("resid_trans_mm_rms", -1),
                 d.get("resid_rot_deg_rms", -1)))
        return X
    except Exception as e:
        print("[handeye] 加载失败 %s: %s" % (path, e))
        return None


HANDEYE_X = _load_handeye(_HANDEYE_PATH)

# ── 相机内参 (真值, 不再用 1.2*max(W,H) 猜) ──
# 来源 models/real_cam_calib.json 的 fx_fy_cx_cy, 由 ROS camera_info 采集。
# 踩过: 早先 fx = 1.2*max(W,H) = 768, 而 D405 真值 394.06 —— 差近一倍,
# 所有投影系统性偏移, 重建整体扭曲 (PSNR 从 15.27 掉到 10.9)。
_CALIB_PATH = os.environ.get("GS_CALIB",
                             osp.expanduser("~/zmax_map/models/real_cam_calib.json"))


def _load_calib(path):
    """读真内参。返回 (fx, fy, cx, cy, calib_w, calib_h) 或 None。"""
    if not path or not osp.exists(path):
        print("[calib] 未找到 %s, 内参退回估算值" % path)
        return None
    try:
        with open(path) as f:
            d = json.load(f)
        fx, fy, cx, cy = [float(v) for v in d["fx_fy_cx_cy"]]
        w, h = d.get("image_size") or [640, 480]
        print("[calib] 已加载 %s | fx=%.2f fy=%.2f cx=%.2f cy=%.2f | 标定尺寸 %sx%s"
              % (path, fx, fy, cx, cy, w, h))
        return (fx, fy, cx, cy, float(w), float(h), d.get("dist"))
    except Exception as e:
        print("[calib] 解析失败 %s: %s, 内参退回估算值" % (path, e))
        return None


CALIB = _load_calib(_CALIB_PATH)

# ── 配置 (环境变量可覆盖) ──
FRAME_URL = os.environ.get("GS_FRAME_URL", "http://192.168.23.66:8792/frame.jpg")
POSE_URL = os.environ.get("GS_POSE_URL", "http://192.168.23.50:8804/pose")
TRAIN_URL = os.environ.get("GS_TRAIN_URL", "http://192.168.23.50:8804")
WORK = os.environ.get("GS_WORK", osp.expanduser("~/gs_autocap"))
SESS = osp.join(WORK, "sessions")
os.makedirs(SESS, exist_ok=True)

MIN_FRAMES = int(os.environ.get("GS_MIN_FRAMES", "120"))
MIN_SPAN_M = float(os.environ.get("GS_MIN_SPAN_M", "0.05"))     # 位姿跨度 >= 5cm
MOVE_EPS_M = float(os.environ.get("GS_MOVE_EPS_M", "0.002"))    # 2mm 算"在动"
MOVE_EPS_RAD = float(os.environ.get("GS_MOVE_EPS_RAD", "0.008"))
COOLDOWN_S = float(os.environ.get("GS_COOLDOWN_S", "180"))
MAX_FRAMES = int(os.environ.get("GS_MAX_FRAMES", "400"))
POLL_HZ = float(os.environ.get("GS_POLL_HZ", "4"))
TRAIN_STEPS = int(os.environ.get("GS_TRAIN_STEPS", "1000"))
MIN_BRIGHT = float(os.environ.get("GS_MIN_BRIGHT", "12"))       # 全黑闸
AUTOTRAIN = os.environ.get("GS_AUTOTRAIN", "1") == "1"

_LAST_MD5 = [None]          # 上一张真正落盘画面的 md5

STATE = {
    "started": time.time(),
    "frames_total": 0, "frames_skipped_static": 0, "frames_skipped_stale": 0,
    "frames_skipped_dark": 0, "frames_skipped_dup": 0, "sessions": 0, "trains_submitted": 0,
    "last_error": "", "cooldown_until": 0.0,
    "cur": None,          # 当前这趟
    "last_train": None,   # 最近一次训练结果
}
LOCK = threading.Lock()


def _get(url, timeout=6.0):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-autocap/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _get_json(url, timeout=6.0):
    return json.loads(_get(url, timeout).decode("utf-8", "ignore"))


def _brightness(jpeg_bytes):
    """均值亮度, 只用来看"是不是全黑/没出图". 没有 numpy 依赖时退化为抽样字节均值。"""
    try:
        import numpy as np
        import cv2
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        im = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if im is None:
            return -1.0
        return float(im.mean())
    except Exception:
        # 退化: JPEG 压缩数据本身的字节均值, 全黑图这个值也会显著偏低
        return float(sum(jpeg_bytes[:4096]) / max(1, len(jpeg_bytes[:4096])))


def _pose_vec(p):
    return [float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("z", 0)),
            float(p.get("rx", 0)), float(p.get("ry", 0)), float(p.get("rz", 0))]


def _moved(a, b):
    if a is None or b is None:
        # 首次没有基准 ⇒ 必须当作"动了", 否则永远采不到第一帧 (踩过: 一直 skipping)
        return True
    d = sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5
    r = sum((a[i] - b[i]) ** 2 for i in range(3, 6)) ** 0.5
    return d > MOVE_EPS_M or r > MOVE_EPS_RAD


def _new_session():
    sid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    d = osp.join(SESS, sid)
    os.makedirs(osp.join(d, "images"), exist_ok=True)
    return {"id": sid, "dir": d, "frames": [], "t0": time.time(), "last_pose": None,
            "skipped_static": 0, "state": "capturing"}


def _finalize_and_train(sess):
    """收尾: 判据 → 打包 → 提交训练"""
    with LOCK:
        STATE["cur"] = None
        STATE["sessions"] += 1

    frames = sess["frames"]
    n = len(frames)
    poses = [f["pose"] for f in frames]
    span = 0.0
    if poses:
        for i in range(3):
            vs = [p[i] for p in poses]
            span = max(span, max(vs) - min(vs))

    meta = {
        "session": sess["id"], "frames": n, "span_m": round(span, 5),
        "duration_s": round(time.time() - sess["t0"], 1),
        "skipped_static": sess["skipped_static"],
        "min_frames": MIN_FRAMES, "min_span_m": MIN_SPAN_M,
    }

    reason = ""
    if n < MIN_FRAMES:
        reason = "帧数不足 %d<%d" % (n, MIN_FRAMES)
    elif span < MIN_SPAN_M:
        reason = "位姿跨度不足 %.4fm<%.4fm (视差不够, 训了也糊)" % (span, MIN_SPAN_M)
    if reason:
        meta["trained"] = False
        meta["skip_reason"] = reason
        json.dump(meta, open(osp.join(sess["dir"], "session_meta.json"), "w"),
                  ensure_ascii=False, indent=1)
        _log(meta)
        return meta

    if not AUTOTRAIN:
        meta["trained"] = False
        meta["skip_reason"] = "GS_AUTOTRAIN=0 (只采集不训练)"
        json.dump(meta, open(osp.join(sess["dir"], "session_meta.json"), "w"),
                  ensure_ascii=False, indent=1)
        _log(meta)
        return meta

    # 打包数据集 (cameras.json + images/) → 4060
    cj = osp.join(sess["dir"], "cameras.json")
    if not osp.exists(cj):
        meta["trained"] = False
        meta["skip_reason"] = "没有 cameras.json"
        json.dump(meta, open(osp.join(sess["dir"], "session_meta.json"), "w"),
                  ensure_ascii=False, indent=1)
        _log(meta)
        return meta

    try:
        meta["train"] = _submit_train(sess["dir"], TRAIN_STEPS)
        meta["trained"] = True
        with LOCK:
            STATE["trains_submitted"] += 1
            STATE["cooldown_until"] = time.time() + COOLDOWN_S
            STATE["last_train"] = meta["train"]
    except Exception as e:
        meta["trained"] = False
        meta["skip_reason"] = "提交训练失败: %s" % e
        with LOCK:
            STATE["last_error"] = str(e)
    json.dump(meta, open(osp.join(sess["dir"], "session_meta.json"), "w"),
              ensure_ascii=False, indent=1)
    _log(meta)
    return meta


def _submit_train(ds_dir, steps):
    """打包 + multipart POST 到 4060"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(osp.join(ds_dir, "cameras.json"), arcname="cameras.json")
        img = osp.join(ds_dir, "images")
        if osp.isdir(img):
            tf.add(img, arcname="images")
    data = buf.getvalue()
    boundary = "----zmaxautocap%d" % int(time.time())
    body = io.BytesIO()
    body.write(("--%s\r\n" % boundary).encode())
    body.write(b'Content-Disposition: form-data; name="steps"\r\n\r\n')
    body.write(str(steps).encode())
    body.write(("\r\n--%s\r\n" % boundary).encode())
    body.write(b'Content-Disposition: form-data; name="dataset"; filename="ds.tar.gz"\r\n')
    body.write(b"Content-Type: application/gzip\r\n\r\n")
    body.write(data)
    body.write(("\r\n--%s--\r\n" % boundary).encode())
    payload = body.getvalue()
    req = urllib.request.Request(TRAIN_URL.rstrip("/") + "/train", data=payload, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    req.add_header("Content-Length", str(len(payload)))
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


def _log(meta):
    try:
        with open(osp.join(WORK, "sessions.jsonl"), "a") as f:
            f.write(json.dumps({"ts": time.time(), **meta}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _write_cameras(sess):
    """把本趟帧+位姿写成 cameras.json (T_cam2world, OpenCV 光学系)
    位姿约定: 机械臂 TCP 真值 = base←flange, 相机装在臂上, 手眼标定给出 cam←flange。
    T_base2cam = T_base2tcp @ T_cam2tool, T_cam2world = inv(T_base2cam)。
    内参优先用 real_cam_calib.json 真值, 按实际帧尺寸等比缩放。
    """
    frames = sess["frames"]
    if not frames:
        return
    W, H = frames[0].get("w"), frames[0].get("h")
    W = int(W or 640)
    H = int(H or 480)
    if CALIB is not None:
        fx, fy, cx, cy, cw, ch, _dist = CALIB
        # 实际帧尺寸和标定尺寸不一致时按比例缩放 (例如采到 320x240 的缩略图)
        sx, sy = W / cw, H / ch
        fx, cx = fx * sx, cx * sx
        fy, cy = fy * sy, cy * sy
        K = [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]
        k_src = "real_cam_calib.json(真机内参) 缩放 %.3fx%.3f" % (sx, sy)
    else:
        # 兜底估算, 显式标注, 免得又被当成真值
        fx = 1.2 * max(W, H)
        K = [[fx, 0.0, W / 2.0], [0.0, fx, H / 2.0], [0.0, 0.0, 1.0]]
        k_src = "估算 1.2*max(W,H)=%.1f (无标定文件, 不可信)" % fx
    pose_note = ("位姿=T_base2tcp @ T_cam2tool 手眼变换" if HANDEYE_X is not None
                 else "位姿=机械臂TCP真值(未经手眼变换)")
    out = {"width": W, "height": H, "K": K,
           "convention": "T_cam2world",
           "note": "gs_autocap_daemon 自动采集; %s; K=%s" % (pose_note, k_src),
           "K_src": k_src,
           "handeye_applied": HANDEYE_X is not None,
           "frames": frames}
    json.dump(out, open(osp.join(sess["dir"], "cameras.json"), "w"),
              ensure_ascii=False, indent=1)


def _rpy_to_R(rx, ry, rz):
    import math
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [[cy * cz, cz * sx * sy - cx * sz, cx * cz * sy + sx * sz],
            [cy * sz, cx * cz + sx * sy * sz, -cz * sx + cx * sy * sz],
            [-sy, cy * sx, cx * cy]]


def capture_loop():
    """主循环: 轮询位姿与画面, 机械臂在动就配对落盘"""
    while True:
        try:
            dur = 1.0 / max(0.5, POLL_HZ)
            # ① 位姿
            try:
                p = _get_json(POSE_URL, timeout=4)
            except Exception as e:
                with LOCK:
                    STATE["last_error"] = "位姿拉取失败: %s" % e
                time.sleep(dur)
                continue
            if p.get("stale"):
                with LOCK:
                    STATE["frames_skipped_stale"] += 1
                    STATE["last_error"] = "位姿陈旧 age=%.2fs" % float(p.get("age_s") or -1)
                time.sleep(dur)
                continue
            # 位姿拉到了 ⇒ 清掉历史错误, 否则界面上的 err 会一直挂着旧故障
            with LOCK:
                if STATE.get("last_error", "").startswith("位姿拉取失败"):
                    STATE["last_error"] = ""
            pv = _pose_vec(p)

            # ② 机械臂在动? 静止就不抓 (抓到的是重复视角, 白占盘)
            # 🔴 基准必须是"上一次**采到帧**的位姿", 不是"上一次轮询的位姿"。
            #    踩过: 用轮询位姿当基准 + 4Hz 采样, 慢速扫场每次只动 0.4mm
            #    永远够不到 2mm 阈值 ⇒ frames_total 一直是 0, 全被判静止。
            cur = STATE.get("cur")
            ref = cur["last_pose"] if cur else STATE.get("_last_cap_pose")
            if not _moved(ref, pv):
                if cur:
                    cur["skipped_static"] += 1
                with LOCK:
                    STATE["frames_skipped_static"] += 1
                time.sleep(dur)
                continue

            # ③ 冷却中不采集
            with LOCK:
                cooling = time.time() < STATE["cooldown_until"]
            if cooling:
                time.sleep(dur)
                continue

            # ④ 抓图
            try:
                jpg = _get(FRAME_URL, timeout=6)
            except Exception as e:
                with LOCK:
                    STATE["last_error"] = "抓图失败: %s" % e
                time.sleep(dur)
                continue
            if len(jpg) < 1000:
                time.sleep(dur)
                continue
            bright = _brightness(jpg)
            if bright >= 0 and bright < MIN_BRIGHT:
                with LOCK:
                    STATE["frames_skipped_dark"] += 1
                    STATE["last_error"] = "画面过暗 bright=%.1f" % bright
                time.sleep(dur)
                continue

            # ⑥-b 内容去重(实测必须): 相机 ~1.2fps, 臂快速移动时同一张图会被配上多个位姿
            #      ⇒ 唯一图 47/124(重复 62%), 留出 PSNR 10.9dB 低于平凡基线 = 废资产。
            #      内容没变就不落盘, 也不推进"上一次采到帧"的基准。
            md5 = hashlib.md5(jpg).hexdigest()
            if md5 == _LAST_MD5[0]:
                with LOCK:
                    STATE["frames_skipped_dup"] = STATE.get("frames_skipped_dup", 0) + 1
                time.sleep(dur)
                continue

            # ⑤ 起新趟
            if cur is None:
                cur = _new_session()
                with LOCK:
                    STATE["cur"] = cur
                # 图像尺寸
                try:
                    import numpy as np
                    import cv2
                    arr = np.frombuffer(jpg, dtype=np.uint8)
                    im = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
                    W, H = (im.shape[1], im.shape[0]) if im is not None else (640, 480)
                except Exception:
                    W, H = 640, 480
                cur["w"], cur["h"] = W, H

            # ⑥ 落盘: 图 + 位姿
            fn = "f_%04d.jpg" % len(cur["frames"])
            with open(osp.join(cur["dir"], "images", fn), "wb") as f:
                f.write(jpg)
            R = _rpy_to_R(pv[3], pv[4], pv[5])
            T_base2tcp = np.array([
                [R[0][0], R[0][1], R[0][2], pv[0]],
                [R[1][0], R[1][1], R[1][2], pv[1]],
                [R[2][0], R[2][1], R[2][2], pv[2]],
                [0.0, 0.0, 0.0, 1.0],
            ], dtype=np.float64)
            # 🔴 2026-10-22 修: 原来直接把 TCP 位姿当相机位姿 (T_cam2world = T_base2tcp),
            #   少了手眼变换, 实测 338 帧数据集 PSNR 只有 15dB(train 也才 18)。
            #   相机固连在臂上, 差一个固定外参 X = T_cam2tool:
            #     p_base = T_base2tcp @ X @ p_cam  ⇒  T_base2cam = T_base2tcp @ X
            #     ⇒ T_cam2world = inv(T_base2cam)
            #   验证口径: |T_base2cam[:3,3] - T_base2tcp[:3,3]| 必须恒等于手眼模长,
            #   否则说明 X 的方向或约定用错了(踩过: 用错方向得 735mm/1064mm, 对的是 244.1mm)。
            if HANDEYE_X is not None:
                T_base2cam = T_base2tcp @ HANDEYE_X
                T_cam2world = np.linalg.inv(T_base2cam)
            else:
                T_cam2world = T_base2tcp
            T = T_cam2world.tolist()
            cur["frames"].append({"file": fn, "T_cam2world": T,
                                  "pose": pv, "bright": round(bright, 1),
                                  "ts": time.time()})
            _LAST_MD5[0] = md5
            cur["last_pose"] = pv
            with LOCK:
                STATE["frames_total"] += 1
                STATE["_last_cap_pose"] = pv

            # ⑦ 够了就收尾训练
            if len(cur["frames"]) >= MAX_FRAMES:
                _write_cameras(cur)
                _finalize_and_train(cur)

        except Exception as e:
            with LOCK:
                STATE["last_error"] = "主循环异常: %s" % e
            time.sleep(1.0)


def idle_flush_loop():
    """机械臂停了但这一趟已经够了 → 主动收尾, 不用等攒满"""
    while True:
        time.sleep(5)
        cur = STATE.get("cur")
        if not cur:
            continue
        n = len(cur["frames"])
        idle = time.time() - (cur["frames"][-1]["ts"] if cur["frames"] else cur["t0"])
        if n >= MIN_FRAMES and idle > 20:
            _write_cameras(cur)
            _finalize_and_train(cur)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _j(self, o, c=200):
        b = json.dumps(o, ensure_ascii=False).encode()
        self.send_response(c)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            with LOCK:
                s = dict(STATE)
            s.pop("_last_cap_pose", None)
            s["uptime_s"] = round(time.time() - s["started"], 1)
            if s.get("cur"):
                c = s["cur"]
                s["cur"] = {"id": c["id"], "frames": len(c["frames"]),
                            "duration_s": round(time.time() - c["t0"], 1),
                            "skipped_static": c["skipped_static"]}
            s["config"] = {"min_frames": MIN_FRAMES, "min_span_m": MIN_SPAN_M,
                           "max_frames": MAX_FRAMES, "cooldown_s": COOLDOWN_S,
                           "autotrain": AUTOTRAIN, "train_steps": TRAIN_STEPS}
            return self._j(s)
        if u.path == "/sessions":
            p = osp.join(WORK, "sessions.jsonl")
            rows = []
            if osp.exists(p):
                for ln in open(p):
                    try:
                        rows.append(json.loads(ln))
                    except Exception:
                        pass
            return self._j({"sessions": rows[-50:]})
        return self._j({"error": "no route"}, 404)


def main():
    threading.Thread(target=capture_loop, daemon=True).start()
    threading.Thread(target=idle_flush_loop, daemon=True).start()
    port = int(os.environ.get("GS_PORT", "8806"))
    print("3DGS 自动采集守护: http://0.0.0.0:%d/  frames=%s pose=%s train=%s"
          % (port, FRAME_URL, POSE_URL, TRAIN_URL))
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    main()
