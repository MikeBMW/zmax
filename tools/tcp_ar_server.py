#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tcp_ar_server.py — TCP 轨迹 AR/VR 可视化服务 (独立端口, 不碰在跑的推流服务)
════════════════════════════════════════════════════════════════════════════
老倪 2026-09-29: 「把可视化的管道轨迹渲染叠加到笔记本相机这个场景中(侧面固定视角)」
              +「应用 VR AR 技术把工具中心轨迹可视化出来」

职责划分(为什么不塞进 cam_live_stream.py):
  · 推流服务(8791/8793)老倪正看着 ⇒ 改它必须重启, 会打断在看的画面;
    本服务**独立端口**起, 页面另占一套 6 条连接名额, 与总览页互不饿死。

端点:
  /                   AR 页 (tools/web/tcp-ar.html, 按 mtime 热读 ⇒ 改页面不用重启)
  /local.mjpg         笔记本相机实时流 (代理 8791, 作为 AR 底图)
  /snapshot/local.jpg 单帧 (代理)
  /scene.json         叠加规格 (代理; 页面从这里取 trace/plan 的 3D 点)
  /stats              相机状态 (代理)
  /api/tcp            当前 TCP 真值(base 系, 珞石 SDK 直采) + 帧龄
  /api/traj           轨迹 3D 点: {"trace":[...], "plan":[...]} (从叠加规格里取)
  /api/stable         臂是否停稳(采 1.2s TCP, 报最大漂移 mm) —— 标定点必须停稳才准
  /api/calib GET      当前笔记本相机外参
  /api/calib POST     {"points":[{"uv":[u,v],"tcp":[x,y,z]}...]} → 解 f/R/t, 存盘, 回重投影证据
  /api/verify         独立验收: 把 TCP 投到"运动中机械臂"掩膜, 回命中率
"""
from __future__ import annotations

import json
import os
import subprocess          # 🏃 Follow: 后台拉起 run_along_line.py
import sys
import threading
import time
import urllib.error
import urllib.request
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import laptop_cam_solve as LS                                                    # noqa: E402
import traj_display as TD
import fence_store as FS     # 🧱 3D 围栏(长方体/直线) 真源 + 碰撞判定
import opt_box3d as OB3      # 🔍 光模块 3D 框 (2D 检测 → 相机系立方体 → 基座系 + 像素投影)                       # noqa: E402                                                        # noqa: E402

try:                                      # 🔍 工控机 AOI 客户端 (10082 金手指 / 10083 表面)
    import aoi_link as AOI
except Exception:                                                                # noqa: BLE001
    AOI = None
AOI_STATE = os.path.join(os.path.expanduser("~/zmax/zmax_data"), "ar_aoi_state.json")

UP = "http://127.0.0.1:8791"
PORT = int(os.environ.get("AR_PORT", "8797"))
PAGE = os.path.join(REPO, "tools", "web", "tcp-ar.html")
CALIB = os.path.join(REPO, "data", "scene", "laptop_cam_calib.json")            # 旧单相机文件(兼容保留)
MCALIB = os.path.join(REPO, "data", "scene", "cam_calib.json")                   # 多相机: {"local":{...},"local2":{...}}
# 🥽 2026-10-12 老倪: 「AR 场景背景的真实图像, 应该是**状态空间工程的视频数据源**; 现在有 USB 相机(RealSense)、
#   机器人手臂的 RealSense、金手指检测相机、表面检测相机 —— 这 4 个相机都照射着同一个场景, L5 层 deepseek VL 能理解它」
#   ⇒ AR 底图来源分两类, 一律**登记真实分辨率**(标定点是像素量纲, 混用必错):
#     ① src="sstate": 状态空间工程的视频数据源 —— 单一真源 = tools/cam_live_stream.py @8791(工位总览 8793 同源),
#        这里只**订阅**, 不另起相机: 🦾 手臂 RealSense D405 / 🔍 金手指检测(10082) / 🧪 表面检测(10083) / 💻 USB 内置 / 📺 MAXHUB
#     ② src="usb": 本机 USB RealSense D435(AR 服务自持 pipeline, 有深度+出厂内参 ⇒ 可反投影/3D 叠加)
#   实测(2026-10-12 逐路拉快照): arm 640×480 · gold 900×332 · gold_raw 1400×1171 · surface 1280×1280 · local 640×480 · local2 1280×720
CAMS = {
    "arm":     {"w": 640,  "h": 480,  "label": "🦾 机器人手臂 RealSense D405 (Orin 臂上)", "mjpg": "/arm.mjpg",
                "src": "sstate", "overlay": "2d", "depth": True},
    "gold":    {"w": 900,  "h": 332,  "label": "🔍 金手指检测相机 (工控机 OPT 10082·判据图)", "mjpg": "/aoi_gold.mjpg",
                "src": "sstate", "overlay": "2d", "stats_key": "aoi_gold"},
    "gold_raw": {"w": 1400, "h": 1171, "label": "🔍 金手指检测·整板原图 (10082)", "mjpg": "/aoi_gold_raw.mjpg",
                 "src": "sstate", "overlay": "2d", "stats_key": "aoi_gold_raw"},
    "surface": {"w": 1280, "h": 1280, "label": "🧪 表面检测相机 (工控机 OPT 10083)", "mjpg": "/aoi_surface.mjpg",
                "src": "sstate", "overlay": "2d", "stats_key": "aoi_surface"},
    "local":   {"w": 640,  "h": 480,  "label": "💻 USB 内置相机 640×480", "mjpg": "/local.mjpg",
                "src": "sstate", "overlay": "2d"},
    "local2":  {"w": 1280, "h": 720,  "label": "📺 MAXHUB 顶摄 1280×720", "mjpg": "/local2.mjpg",
                "src": "sstate", "overlay": "2d"},
    "rs":      {"w": 640,  "h": 480,  "label": "🎥 USB RealSense D435 (彩色+深度·本机直连)", "mjpg": "/rs.mjpg",
                "depth": True, "intrinsics": "device", "src": "usb", "overlay": "3d"},
}
# AR 底图默认 = 状态空间工程的视频数据源(手臂相机) —— 老倪: 「背景的真实图像应该是状态空间工程的视频数据源」
DEFAULT_CAM = os.environ.get("AR_DEFAULT_CAM", "arm")
# 🥽 老倪点名的 4 台相机(同一场景 4 视角): UI 首屏就把这 4 个摆出来
FOUR_CAMS = ("arm", "gold", "surface", "rs")
SRC_NOTE = {"sstate": "状态空间工程视频源 (8791 cam_live_stream · 工位总览 8793 同源)",
            "usb": "本机 USB Intel RealSense D435 (AR 服务直连)"}
TCP_JSON = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")
IMG_W, IMG_H = 640, 480


def _get(path: str, timeout: float = 10.0):
    with urllib.request.urlopen(UP + path, timeout=timeout) as r:
        return r.read()


# 🆕 2026-10-12 老倪: 「8797 和 8793 这两个服务的 金手指检测 的整板原图 判据图, 怎么不一样呢?」
#   实测根因两条:
#   ① /api/aoi/gold.jpg 取不到本机那张时会**回退到工控机 kind=crop**(=程序画上去的那张, 没拍到金手指
#      也照样画一排) ⇒ AR 页与工位总览页显示的不是同一张 ⇒ 现场一眼就看出"不一样"。
#   ② 本机那路的取帧会偶尔慢(工控机送检帧节奏), 一旦超过超时, 页面就空/慢, 越看越像两个服务在给不同的图。
#   定式: 只用**本机裁切的实拍区域**这一个口径 + 记住**上一次成功那一张**兜底(宁可给略旧的一帧, 也不换口径)。
_SNAP_CACHE = {}          # path -> (bytes, ts); 只在成功时更新


def _cached_get(path: str, timeout: float = 6.0):
    """取上游一帧; 上游慢/失败 ⇒ 给**上一次成功的那张**(附时间), 绝不换口径、绝不挂住页面。"""
    try:
        b = _get(path, timeout=timeout)
        if b and len(b) > 1500:
            _SNAP_CACHE[path] = (b, time.time())
            return b, 0.0
    except Exception:                                                   # noqa: BLE001
        pass
    old = _SNAP_CACHE.get(path)
    if old:
        return old[0], time.time() - old[1]
    return b"", None


# ═══ 🧭 坐标系链 (2026-10-12 老倪:「世界坐标系 / tool0 = 6轴末端法兰盘中心 / tool1 = 夹爪夹住光模块,
#       Arm 相机画面最下方那个光模块头部的中心点 —— 你能看到机器人的每个坐标系么?」)
#   · base/world: 真值源的 frame 字段就是 base_link ⇒ 本服务所有坐标都在 base 系里(单位 m)。
#   · tool1: latest.json 报的位姿**就是 tool1**(珞石 endInRef, 控制器 toolset=tool1;
#             l2_daemon 的 J6 自转公式也是把上报值当 TCP ⇒ "p_tcp − R_tool·t_tool = 法兰原点" 同一口径)。
#   · tool0: 法兰中心 = tool1 ⊖ URDF tool0→tool1 的**固定**位姿(与当前姿态无关, 常数如下)。
#   ⚠️ 常数来源 = 现场 URDF; 离线自检: tools/test_j6_axis.py(与 FK 位置差 6e-14mm)。
TOOL01_RPY = (0.03702517838719945, 0.6751675651256659, 2.375248653715161)   # URDF tool0→tool1 rpy
TOOL01_XYZ = (-0.01588615307905028, 0.018348498948158043, 0.2586775713451509)  # URDF tool0→tool1 xyz


def _rpy_R(r: float, p: float, y: float):
    """rpy(URDF 口径 Rz·Ry·Rx) → 3×3"""
    import math as _m
    cr, sr, cp, sp, cy, sy = _m.cos(r), _m.sin(r), _m.cos(p), _m.sin(p), _m.cos(y), _m.sin(y)
    return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp,     cp * sr,                cp * cr]]


def _quat_R(q):
    """四元数(x,y,z,w) → 3×3"""
    x, y, z, w = [float(v) for v in q]
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
            [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)]]


def _mm(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mv(A, v):
    return [sum(A[i][k] * v[k] for k in range(3)) for i in range(3)]


def _T(A):
    return [[A[j][i] for j in range(3)] for i in range(3)]


_R_OFF = _rpy_R(*TOOL01_RPY)                       # URDF tool0→tool1 旋转
_T_TOOL = _mv(_T(_R_OFF), TOOL01_XYZ)              # 法兰→TCP 平移(工具系) = R_off^T·t_off


def _frames(d):
    """base / tool0 / tool1 三个坐标系的原点 + 三轴单位向量(都在 base 系里) —— 给 3D 视图画三色轴。"""
    q = [d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")]
    if any(v is None for v in q):
        return None
    R1 = _quat_R(q)                                # tool1 姿态(上报值)
    p1 = [float(d["x"]), float(d["y"]), float(d["z"])]
    p0 = [p1[i] - _mv(R1, _T_TOOL)[i] for i in range(3)]     # 法兰中心 = tool1 − R_tool1·t_tool
    R0 = _mm(R1, _T(_R_OFF))                                # R_tool0 = R_tool1 · R_off^T
    def tri(R, p):
        return {"origin": [round(v, 5) for v in p],
                "x": [round(v, 5) for v in [_R_col(R, 0)[i] for i in range(3)]],
                "y": [round(v, 5) for v in [_R_col(R, 1)[i] for i in range(3)]],
                "z": [round(v, 5) for v in [_R_col(R, 2)[i] for i in range(3)]]}
    return {"base": {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]},
            "tool0": tri(R0, p0), "tool1": tri(R1, p1),
            "flange_mm": round(1000.0 * sum((p1[i] - p0[i]) ** 2 for i in range(3)) ** 0.5, 1),
            "src": "tool1 = 珞石 endInRef(控制器 toolset=tool1, latest.json) · tool0 = tool1 ⊖ URDF tool0→tool1 固定位姿"}


def _R_col(R, j):
    return [R[0][j], R[1][j], R[2][j]]


_URDF_CACHE = {}


def _urdf_payload():
    """URDF 外形: 首次调用解析 URDF+STL 并缓存 (47KB 左右), 之后直接返回"""
    if _URDF_CACHE.get("ok"):
        return _URDF_CACHE["data"]
    try:
        import urdf_proxy
        d = urdf_proxy.load()
        d["ok"] = True
        _URDF_CACHE["ok"] = True
        _URDF_CACHE["data"] = d
        return d
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}


def read_tcp():
    try:
        with open(TCP_JSON) as f:
            d = json.load(f)
        out = {"ok": True, "x": d["x"], "y": d["y"], "z": d["z"],
               "t": d.get("t"), "age_s": round(time.time() - float(d["ts"]), 3),
               "frame": d.get("frame") or "base_link", "src": d.get("src"),
               "quat": [d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")],
               "tool01_const": {"rpy": list(TOOL01_RPY), "xyz": list(TOOL01_XYZ),
                                "dist_mm": round(1000 * sum(v * v for v in TOOL01_XYZ) ** 0.5, 1)}}
        jp = d.get("joint")                       # 🦾 URDF 外形要用真关节角 (前 6 个, rad)
        if isinstance(jp, list) and len(jp) >= 6:
            out["joints"] = [round(float(v), 6) for v in jp[:6]]
        fr = _frames(d)
        if fr:
            out["frames"] = fr
        return out
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": str(e)[:120]}


def snap_cam(cam: str = "local"):
    if cam == "rs":                                    # 本机 RealSense: 直接取帧(不经 8791)
        import realsense_source as RS
        return RS.snap()
    b = _get("/snapshot/%s.jpg" % cam)
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


RS_LAST_DET = {"ts": 0.0, "dets": []}       # 最近一次 AR 帧检测(pose 用来选目标)


def _rs_options():
    try:
        import realsense_source as RS
        d = RS.options()
        if d.get("ok"):
            flt = [o["name"] for s in d["sensors"] for o in s["options"]]
            d["has_ae_roi"] = [n for n in flt if "roi" in n.lower()]
            d["has_ae_priority"] = [n for n in flt if "priority" in n.lower()]
        return d
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:140])}


def _rs_exposure(auto=None, exposure_us=None, gain=None):
    try:
        import realsense_source as RS
        return RS.color_ctl(auto=auto, exposure_us=exposure_us, gain=gain)
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:140])}


def _rs_pose(use_last_detect=True, roi=None):
    """🥽 相机系 3D 位姿叠加: 有检出框就量光模块, 指定 roi 就量那块, 否则量画面中心平面 —— 都是**深度真值**。"""
    try:
        import ar_calib_module as ACM
        return ACM.pose(roi=roi, use_last_detect=use_last_detect)
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


def _rs_detect(conf=0.25, imgsz=640):
    """🥽 光模块检测(AR 相机帧): 在**本进程**跑在役 YOLO —— 相机被本服务独占, 别的进程打不开设备。

    返回 bbox/conf + 深度相机系 3D; 标注图落 zmax_data/ar_rs/rs_detect_last.png (AR 页面可直接看)。
    conf/imgsz 可调: 归因"没东西 vs 权重不认视角"时, 用低 conf / 高分辨率各跑一次对比。
    """
    try:
        import ar_calib_module as ACM
        r = ACM.detect(conf=conf, imgsz=imgsz)
        if r.get("ok"):
            RS_LAST_DET["ts"] = time.time()
            RS_LAST_DET["dets"] = r.get("dets") or []
        return r
    except SystemExit as e:
        return {"ok": False, "err": str(e)}
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


def _aoi_state_read():
    """读最近一次 AOI 结果(没有就如实说没有)。"""
    try:
        with open(AOI_STATE, encoding="utf-8") as f:
            d = json.load(f)
        d["age_s"] = round(time.time() - os.path.getmtime(AOI_STATE), 1)
        return d
    except Exception:                                                            # noqa: BLE001
        return {"ok": False, "err": "还没有 AOI 结果(点『📸 请求检测』跑一次)", "path": AOI_STATE}


def _rs_jpeg(quality: int = 82) -> bytes:
    """🥽 RealSense 单帧 JPEG —— **一律从独占小服务(8789)取**。

    ⚠ 本进程是 ForkingMixIn: 在这类子进程里 import realsense_source 只会拿到 fork 前那份空壳
      (frames=0, snap()=None) ⇒ 原来这里直接调 RS.snap() 永远回空图, 正是"USB RealSense 不好使"的表象。
      真源只有一个: tools/rs_service.py(单进程独占 D435)。取不到就回空字节, 不拿旧帧冒充。
    """
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8789/snap.jpg", timeout=8) as r:
            return r.read()
    except Exception:                                                            # noqa: BLE001
        return b""


def motion_mask(gap: float = 0.8, thr: int = 18, cam: str = "local"):
    """运动掩膜(哪台相机就量哪台): 两帧差 + 膨胀。用来做"TCP 投影是否落在运动中的臂上"的独立验收。"""
    f1 = snap_cam(cam)
    time.sleep(gap)
    f2 = snap_cam(cam)
    if f1 is None or f2 is None or f1.shape != f2.shape:
        return np.zeros((CAMS.get(cam, {}).get("h", 480), CAMS.get(cam, {}).get("w", 640)), np.uint8)
    d = np.abs(f2.astype(np.int16) - f1.astype(np.int16)).max(2)
    return cv2.dilate((d > thr).astype(np.uint8), np.ones((9, 9), np.uint8))


def load_calib(cam="local"):
    """读某台固定相机的外参: 先查多相机文件 cam_calib.json[cam], 没命中再回落到旧的单相机文件。"""
    try:
        with open(MCALIB) as f:
            d = json.load(f)
        if isinstance(d, dict):
            if cam in d and isinstance(d[cam], dict):
                return d[cam]
            if d.get("cam") == cam:                    # 旧格式(单条)
                return d
    except Exception:                                                             # noqa: BLE001
        pass
    if cam == "local":
        try:
            with open(CALIB) as f:
                return json.load(f)
        except Exception:                                                         # noqa: BLE001
            return None
    return None


def save_calib(cam, obj):
    d = {}
    try:
        with open(MCALIB) as f:
            d = json.load(f)
        if not isinstance(d, dict) or "cam" in d:      # 旧格式/坏文件 ⇒ 重开
            d = {}
    except Exception:                                                             # noqa: BLE001
        d = {}
    d[cam] = obj
    tmp = MCALIB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MCALIB)
    return MCALIB



# ───────────────────────── 🥽 AR 底图来源 / L5 理解 (2026-10-12) ─────────────────────────
def _ss_stats(timeout: float = 3.0) -> dict:
    """状态空间工程视频源的每路实况(在线/fps/帧龄/上游 label) —— 真源在 8791, 这里只转发, 不重算。"""
    try:
        with urllib.request.urlopen(UP + "/stats", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:                                                        # noqa: BLE001
        return {"_err": "%s: %s" % (type(e).__name__, e)}


def _rs_online_fast(timeout: float = 2.5):
    """USB D435 在线自证 —— **必须有硬超时**。

    2026-10-12 现场: D435 拔掉后, /api/cams 里那步直接 `_rs_jpeg()` 抓帧 ⇒ pyrealsense 永久等帧,
    整个 /api/cams 卡死(3D 场景的 AR 按钮正是拿 /api/cams 探"服务起没起" ⇒ 于是它以为服务没起,
    点 AR 既不切场景也不开页面)。⇒ 先查设备在不在, 抓帧再套一层超时。
    """
    try:
        import pyrealsense2 as _rs
        if len(_rs.context().query_devices()) == 0:
            return False, "没检测到 RealSense 设备(D435 不在位/已掉线)"
    except Exception as _e:                                                 # noqa: BLE001
        return False, "RealSense 查询失败: %s" % type(_e).__name__
    import concurrent.futures as _cf
    _ex = _cf.ThreadPoolExecutor(max_workers=1)
    try:
        return bool(_ex.submit(_rs_jpeg, 82).result(timeout=timeout)), SRC_NOTE.get("usb", "")
    except Exception:                                                       # noqa: BLE001
        return False, "抓帧超时(设备在但没帧 ⇒ 疑似掉线)"
    finally:
        _ex.shutdown(wait=False)                                            # 不等卡住的线程


def _cams_payload() -> dict:
    """底图来源清单: 每路带 来源/分辨率/是否已标定/在线/帧龄(从视频源真值读)。"""
    st = _ss_stats()
    out = {}
    for k, v in CAMS.items():
        d = dict(v)
        d["stream"] = "/cam.mjpg?c=" + k
        d["snapshot"] = "/snap/%s.jpg" % k
        d["calibrated"] = bool(load_calib(k))
        d["src_note"] = SRC_NOTE.get(d.get("src"), d.get("src") or "")
        d["four"] = (k in FOUR_CAMS)
        s = st.get(d.get("stats_key") or k) if isinstance(st, dict) else None
        if isinstance(s, dict):
            d["online"] = s.get("online")
            d["age_s"] = s.get("age_s")
            d["fps"] = s.get("fps")
            d["stalled"] = s.get("stalled")
            d["label_src"] = s.get("label")
        elif k == "rs":                       # 本机 USB D435 不在 8791 stats 里 ⇒ 自己真抓一帧自证(带超时!)
            _on, _note = _rs_online_fast()
            d["online"] = _on
            d["age_s"] = 0.0 if _on else None
            d["label_src"] = SRC_NOTE.get("usb", "") if _on else _note
        out[k] = d
    return {"ok": True, "cams": out, "default": DEFAULT_CAM, "four": list(FOUR_CAMS),
            "calibrated": [c for c in CAMS if load_calib(c)],
            "ss_stats_err": (st.get("_err") if isinstance(st, dict) else None),
            "src_note": SRC_NOTE}


def frame_bytes(cam: str):
    """取**当前底图这一路**的一帧原始 JPEG(L5 理解/证据/快照都用它, 与页面看到的是同一路)。"""
    if cam == "rs":
        return _rs_jpeg(82), "rs(本机 USB RealSense D435)"
    mj = (CAMS.get(cam) or CAMS[DEFAULT_CAM]).get("mjpg") or "/arm.mjpg"
    snap = "/snapshot/%s.jpg" % mj.rsplit("/", 1)[-1][:-5]      # /arm.mjpg -> /snapshot/arm.jpg
    _b, _old = _cached_get(snap, timeout=6.0)                  # 慢 ⇒ 上一张成功的(见 _cached_get)
    return _b, cam + ("(取帧慢·上一张)" if _old else "")


PY_EXE = os.path.join(REPO, "gui-venv311", "bin", "python")
L5_BRIDGE = os.path.join(REPO, "tools", "ar_l5_understand.py")


def l5_understand(cam: str = None, hint: str = "") -> dict:
    """L5 层 deepseek VL 理解当前底图这一帧: 抓帧 → **子进程桥** → 引擎 L5(SceneVLM) → 文字 + 框。

    为什么走子进程: 引擎要拉 torch(GB 级), AR 服务是常驻轻进程 —— 进程内 import 会顶到内存红线。
    失败一律如实回报(不编造理解结果), 并带帧字节/来源/耗时, 便于现场分清"没帧"还是"模型没起"。
    """
    cam = cam or DEFAULT_CAM
    t0 = time.time()
    try:
        jpg, src = frame_bytes(cam)
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "cam": cam, "err": "取帧失败: %s: %s" % (type(e).__name__, e)}
    if not jpg or jpg[:2] != b"\xff\xd8":       # 必须是真 JPEG: 上游报错时别把错误页当图喂给模型
        return {"ok": False, "cam": cam, "err": "该路这一帧不是有效 JPEG(相机没出图/上游报错)",
                "frame_bytes": len(jpg or b"")}
    if not os.path.isfile(L5_BRIDGE):
        return {"ok": False, "cam": cam, "err": "缺桥脚本 %s" % L5_BRIDGE, "frame_bytes": len(jpg)}
    w = int((CAMS.get(cam) or {}).get("w") or 640)
    h = int((CAMS.get(cam) or {}).get("h") or 480)
    import subprocess
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="arl5_")
    os.write(fd, jpg)
    os.close(fd)
    try:
        cmd = [PY_EXE if os.path.isfile(PY_EXE) else sys.executable,
               L5_BRIDGE, "--jpg", tmp, "--w", str(w), "--h", str(h), "--cam", cam]
        if hint:
            cmd += ["--hint", hint]
        pr = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=float(os.environ.get("AR_L5_TIMEOUT", "380")))
        lines = [ln for ln in (pr.stdout or "").splitlines() if ln.strip().startswith("{")]
        if not lines:
            return {"ok": False, "cam": cam, "frame_bytes": len(jpg),
                    "err": "桥脚本没给 JSON(rc=%s)" % pr.returncode, "stderr": (pr.stderr or "")[-300:]}
        r = json.loads(lines[-1])
        r.update({"cam": cam, "src": src, "w": w, "h": h, "frame_bytes": len(jpg),
                  "latency_s": round(time.time() - t0, 1),
                  "via": "engine:SceneVLM (L5 deepseek VL · 子进程桥)"})
        return r
    except subprocess.TimeoutExpired:
        return {"ok": False, "cam": cam, "frame_bytes": len(jpg),
                "err": "L5 超时(>%ss): 引擎在跑但没及时返回" % os.environ.get("AR_L5_TIMEOUT", "380")}
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "cam": cam, "frame_bytes": len(jpg),
                "err": "L5 调用失败: %s: %s" % (type(e).__name__, e)}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def frozen_box_center():
    """读钉住/实时的标注框中心(像素)。老倪: 坐标系就画在标注的光模块头顶中心点上。"""
    for p in ("/dev/shm/mod3_freeze.json", "/dev/shm/mod3_latest.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
            b = d.get("box2d")
            if d.get("ok") and b:
                return [(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0], b
        except Exception:                                               # noqa: BLE001
            continue
    return None, None


def frozen_box_tip(inset_px: float = None):
    """光模块**头顶中心**(像素) = 绿色边界框**下边缘中点** (老倪 2026-10-19 现场口述:
    「不对, 下多了。你自己走, 在绿色边界框的下边缘中点的位置」)。

    inset_px=None ⇒ 直接取框底 b[3] (默认口径); 给数字则按 b[1]+inset 覆盖(现场微调用 ?inset=)。

    🔴 2026-10-19 老倪现场纠正:「tool1 原点应该在光模块头顶上, 在你当前手臂相机**上边沿的下面大约 2 厘米**,
      不是图像上边沿的正中心」—— 检测框贴顶(clipped top)时 box2d[1]≈0.3, 那是被 YOLO 顶到画外的边,
      真实的模块头顶在画面里往下约 2cm ⇒ 原点必须内缩。
      · 内缩量按当前这把尺算: 60mm↔66.5px ⇒ 1px≈0.90mm ⇒ 20mm≈22.2px (可用 ?inset= 覆盖微调)。

    老倪 2026-10-19: 「原点要移动到光模块头顶中心点, 不要显示 60mm」
      · 原来对齐到框中心 ⇒ 原点画在模块**中段**(框高 59px≈54mm, 偏下约 27mm), 现场看就不是头顶;
      · 细长模块的头顶 = 框顶边中点 (box2d[0]+box2d[2])/2, box2d[1];
      · 框贴顶(clipped top)时头顶已经出画, 这里仍然给可见顶边中点, 并把 clipped 一并返回,
        由页面标注「头顶出画·原点按可见顶边」——不假装。
    返回 (tip_xy, box2d, clipped_list)
    """
    for p in ("/dev/shm/mod3_freeze.json", "/dev/shm/mod3_latest.json"):
        try:
            d = json.load(open(p, encoding="utf-8"))
            b = d.get("box2d")
            if d.get("ok") and b:
                # 默认口径: 框**下边缘中点**; 给了 inset_px 就按框顶往下量(现场微调)
                _y = float(b[3]) if inset_px is None else (b[1] + float(inset_px))
                _img = d.get("img") or [640, 480]
                _y = max(0.0, min(_y, float(_img[1]) - 2.0))
                return [(b[0] + b[2]) / 2.0, _y], b, list(d.get("clipped") or [])
        except Exception:                                               # noqa: BLE001
            continue
    return None, None, []


def toolframe_px(length_mm=80.0, align_box=True, tip_inset_px=None):
    """tool1 坐标系投影到臂相机像素。相机在腕上 ⇒ 这套像素是**固定**的(不随位姿变)。
    数据: models/handeye_state.json(相机在 tool 系的位姿; 矩阵平移单位是米) + real_cam_calib.json 的 K/dist。"""
    import json as _j
    import os as _os
    import numpy as _np
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    try:
        he = _j.load(open(_os.path.join(root, "models", "handeye_state.json"), encoding="utf-8"))
        cal = _j.load(open(_os.path.join(root, "models", "real_cam_calib.json"), encoding="utf-8"))
        T = _np.array(he["T_cam2tool"], float)
        if _np.linalg.norm(T[:3, 3]) < 2.0:
            T[:3, 3] *= 1000.0
        Ti = _np.linalg.inv(T)
        K = _np.array(cal["K"], float).reshape(3, 3)
        dist = _np.array(cal.get("dist") or [0, 0, 0, 0, 0], float).ravel()
        pts = [_np.zeros(3), _np.array([length_mm, 0, 0.0]), _np.array([0, length_mm, 0.0]),
               _np.array([0, 0, length_mm])]
        Pc = _np.array([Ti[:3, :3] @ q + Ti[:3, 3] for q in pts])
        rvec, _ = cv2.Rodrigues(_np.eye(3))
        uv, _ = cv2.projectPoints(Pc.reshape(-1, 1, 3), rvec, _np.zeros(3), K, dist)
        uv = uv.reshape(-1, 2)
        if float(Pc[0, 2]) <= 5:
            return {"ok": False, "err": "tool1 原点在相机背后", "cam_z_mm": float(Pc[0, 2])}
        org = [float(uv[0][0]), float(uv[0][1])]
        ax = {"X": [float(uv[1][0]), float(uv[1][1])], "Y": [float(uv[2][0]), float(uv[2][1])],
              "Z": [float(uv[3][0]), float(uv[3][1])]}
        delta = [0.0, 0.0]
        _clip = []
        # 🔴 老倪 2026-10-18「坐标系就在你标注的光模块头顶中心点」/ 2026-10-19「原点要移动到头顶中心点」:
        #   手眼投出来的原点和标注框**中心**有 ~12px 固定偏差; 但框中心是模块中段, 不是头顶 ⇒
        #   2026-10-19 起对齐目标改为**框顶边中点(头顶)**; 三轴整体平移(姿态不变), 偏差如实报出来。
        if align_box:
            _tip, _b, _clip = frozen_box_tip(tip_inset_px)
            if _tip:
                delta = [round(_tip[0] - org[0], 2), round(_tip[1] - org[1], 2)]
                org = [_tip[0], _tip[1]]
                for k in ax:
                    ax[k] = [ax[k][0] + delta[0], ax[k][1] + delta[1]]
        return {"ok": True, "origin": org, "align_shift_px": delta,
                "align_to": ("pegtip(框下边缘中点)" if tip_inset_px is None
                             else "pegtip(框顶+%.1fpx)" % float(tip_inset_px)),
                "tip_inset_px": tip_inset_px,
                "tip_clipped": _clip,
                "axes": ax,
                "length_mm": length_mm, "cam_z_mm": float(Pc[0, 2]), "img": [640, 480],
                "src": "handeye_state.json(残差0.06mm) + real_cam_calib K(camera_info)"}
    except Exception as e:                                               # noqa: BLE001
        return {"ok": False, "err": str(e)}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "zmax-tcp-ar/1.0"
    # 2026-10-12 现场实测(AR 按钮打不开): 客户端断链后处理线程**永久卡死**(连接堆成 CLOSE-WAIT,
    #   accept 队列满 6 ⇒ 新连接一律超时; 进程活着、老连接还能答, 换成别的端口也一样复现)。
    #   根因=处理线程没有读超时 ⇒ 这里给每条连接一个硬超时(读/写超时即收尾放行), 免得线程泄漏把服务憋死。
    timeout = 20
    # 单个响应不要无限拖: 大图走分块也要能在超时内收尾
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except Exception:                                                       # noqa: BLE001
            self.close_connection = True

    def log_message(self, fmt, *a):                                               # noqa: A003
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % a))

    def _send(self, code, ctype, body: bytes, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 🌐 CORS: 8791 上的场景叠加页/工位总览页要能直接调这里的轨迹开关
        #    (跨端口 = 跨源, 不放开的话浏览器把请求直接拦掉, 表现为"按钮点了没反应")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):                                                         # noqa: N802
        self._send(204, "text/plain", b"")

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):                                                             # noqa: N802
        p = self.path.split("?")[0]
        qs = {}
        if "?" in self.path:
            for kv in self.path.split("?", 1)[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    qs[k] = v
        cam = qs.get("cam") or qs.get("c") or "local"
        # 🔌 2026-10-20: RealSense 的**所有**端点一律转给独占小服务 (本进程是 ForkingMixIn,
        #   fork 出来的子进程里 pyrealsense 只剩空壳 ⇒ frames=0 / 0 字节 / 抢设备 EBUSY)。
        #   真源: tools/rs_service.py (单进程独占 D435)
        if p in ("/rs.mjpg", "/snap/rs.jpg", "/snapshot/rs.jpg") or p.startswith("/api/rs_"):
            self._rs_proxy()
            return
        try:
            if p in ("/", "/tcp-ar", "/tcp-ar.html", "/ar"):
                with open(PAGE, "rb") as f:                                       # 热读: 改页面不用重启
                    self._send(200, "text/html; charset=utf-8", f.read())
            elif p == "/api/cams":              # 🥽 底图来源清单(含状态空间工程视频源实况: 在线/帧龄/fps)
                self._json(_cams_payload())
            elif p == "/api/ss_stats":          # 🥽 状态空间工程视频源(8791 cam_live_stream)原始实况
                self._json({"ok": True, "stats": _ss_stats()})
            elif p == "/api/l5/understand":     # 🥽 L5 层 deepseek VL 理解当前底图(抓帧→子进程桥→引擎 L5)
                self._json(l5_understand(qs.get("c") or None, hint=(qs.get("hint") or "")))
            elif p == "/api/tcp":
                self._json(read_tcp())
            elif p == "/api/robot_state":        # 🤖 机器人状态机 (是否在插拔 ⇒ 页面顶部一眼看到)
                #   真源 = tools/robot_state.py (控制器三查 + 位姿 + 阶段文件), 本服务只做只读代发。
                try:
                    import importlib.util as _ilu
                    _sp = _ilu.spec_from_file_location(
                        "zmax_robot_state", os.path.join(REPO, "tools", "robot_state.py"))
                    _m = _ilu.module_from_spec(_sp)
                    _sp.loader.exec_module(_m)                              # type: ignore[union-attr]
                    self._json({"ok": True, "robot": _m.snapshot()})
                except Exception as e:                                      # noqa: BLE001
                    self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:200])})
            elif p in ("/toolframe.jpg", "/toolframe.png"):   # ▣ 画好 tool1 坐标系的臂相机图(直接看图, 不用等页面刷新)
                try:
                    L = float(qs.get("len", "80") or 80)
                except Exception:                                       # noqa: BLE001
                    L = 80.0
                try:
                    _ins = float(qs.get("inset"))       # 贴顶时头顶内缩(px), 现场可微调
                except Exception:                                       # noqa: BLE001
                    _ins = None
                self._toolframe_img(L, tip_inset_px=_ins)
            elif p == "/api/toolframe":                    # ▣ tool1 坐标系(臂相机像素, 固定)
                try:
                    L = float(qs.get("len", "80") or 80)
                except Exception:                                       # noqa: BLE001
                    L = 80.0
                try:
                    _ins = float(qs.get("inset"))       # 贴顶时头顶内缩(px)
                except Exception:                                       # noqa: BLE001
                    _ins = None
                self._json(toolframe_px(L, align_box=(qs.get("align", "box") != "0"), tip_inset_px=_ins))
            elif p == "/api/module3d_lock":                   # 🔒 定主状态 (只读)
                self._json(self._mod3_lock("status"))
            elif p in ("/api/module3d", "/api/opt3d"):      # 🔍 光模块 3D 框 (臂相机)
                self._json(self._module3d(qs.get("img", "0") in ("1", "true", "yes")))
            elif p == "/api/fence":            # 🧱 3D 元素列表 (页面画 + 编辑用)
                self._json(FS.listing())
            elif p == "/api/fence/follow/status":   # 🏃 跟随状态 (页面轮询)
                self._json(self._follow_status())
            elif p == "/api/fence/check":      # 🧱 某点是否在围栏里
                try:
                    q = [float(qs.get("x") or 0), float(qs.get("y") or 0), float(qs.get("z") or 0)]
                    self._json(FS.check_point(q))
                except Exception as e:                                                 # noqa: BLE001
                    self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
            elif p == "/api/urdf":             # 🦾 机器人 URDF 外形(降采样点云 + 关节链), 页面一次拉取缓存
                self._json(_urdf_payload())
            elif p == "/api/traj":
                self._json(self._traj())
            elif p == "/api/stable":
                self._json(self._stable())
            elif p == "/api/calib":
                c = load_calib(cam)
                self._json({"ok": bool(c), "calib": c, "cam": cam, "cams": CAMS})
            elif p == "/api/traj/state":
                self._json(self._traj_state())
            elif p == "/api/ar_diag":              # 🩺 AR 页面自诊断上报(页面每 3s 推一次真实运行时状态)
                # 老倪 2026-10-19「点击刷新也不好使」——服务端日志只能看到 /api/* 轮询, 看不到页面里
                # FPUMP.busy 是否卡死、document.hidden 是什么、CAMS 有没有 arm。让页面自己上报。
                # ⚠ 8797 是 ForkingMixIn(每请求一个子进程) ⇒ 不能存模块级 list, 必须落盘。
                try:
                    from urllib.parse import urlparse as _up, parse_qs as _pq
                    _f = "/dev/shm/zmax_ar_diag.jsonl"
                    _qq = _pq(_up(self.path).query)
                    if "state" in _qq:
                        try:
                            _st = json.loads(_qq["state"][0])
                        except Exception:                                        # noqa: BLE001
                            _st = {"raw": str(_qq["state"][0])[:300]}
                        _st["t"] = time.strftime("%H:%M:%S")
                        _mode = "a"
                        try:
                            if os.path.getsize(_f) > 200000:
                                _mode = "w"
                        except Exception:                                        # noqa: BLE001
                            pass
                        with open(_f, _mode, encoding="utf-8") as _fh:
                            _fh.write(json.dumps(_st, ensure_ascii=False) + "\n")
                        self._json({"ok": True})
                    else:
                        _lines = []
                        try:
                            with open(_f, encoding="utf-8") as _fh:
                                _lines = _fh.read().strip().split("\n")[-10:]
                        except Exception:                                        # noqa: BLE001
                            pass
                        self._json({"ok": True, "n": len(_lines),
                                    "diag": [json.loads(_x) for _x in _lines if _x.strip()]})
                except Exception as _e:                                          # noqa: BLE001
                    self._json({"ok": False, "err": str(_e)[:120]})
            elif p == "/api/aoi/state":            # 🔍 最近一次 AOI 结果(不拍照)
                self._json(_aoi_state_read())
            elif p == "/api/aoi/read":             # 🔍 只读体检(不拍照)
                self._json((AOI.health(10082) if AOI else {"err": "aoi_link 不可用"}))
            elif p == "/api/aoi/gold.jpg":         # 🔍 金手指判据图(唯一口径: 本机从原始帧裁切的实拍区域)
                # 🆕 2026-10-12 老倪: 「不要显示那么多高亮的条, 就显示你截取的金手指区域即可」
                #   原来直传工控机 kind=crop = **程序画上去的**判据图(没拍到金手指时也照样画一排) ⇒
                #   改成端 8793 那格"本机从原始帧裁切的实拍区域"(同一张, 页面/AR 口径一致); 取不到才回退直传。
                # 🆕 2026-10-12: 去掉"取不到就回退工控机 kind=crop"那条 —— 那正是两个页面"不一样"的来源
                #   (工控机那张是**程序画上去的**, 没拍到金手指也画一排)。取不到就给上一次成功那张,
                #   再没有就 503 + 说清原因, 让现场知道是取帧问题, 而不是悄悄换个口径。
                _loc, _old = _cached_get("/snapshot/aoi_gold.jpg", timeout=6.0)
                if _loc and len(_loc) > 2000:
                    self._send(200, "image/jpeg", _loc,
                               {"X-Zmax-Stale-S": ("%.1f" % _old) if _old else "0",
                                "X-Zmax-Source": "local-crop(8791/snapshot/aoi_gold.jpg)"})
                else:
                    self._json({"ok": False, "err": "本机裁切帧取不到(8791 /snapshot/aoi_gold.jpg), 且无缓存",
                                "hint": "看 8791 那路是否在跑: curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8791/snapshot/aoi_gold.jpg"}, 503)
            elif p == "/api/rs_stream_help":
                self._json({"mjpg": "/rs.mjpg", "snapshot": "/snapshot/rs.jpg",
                            "info": "/api/rs_info", "point": "/api/rs_point?u=&v="})
            elif p == "/api/verify":
                self._json(self._verify(cam))
            elif p in ("/scene.json", "/stats", "/station/status"):
                self._send(200, "application/json; charset=utf-8", _get(p))
            elif p == "/rs.mjpg":                  # 🥽 RealSense 彩色流 (AR 底图)
                self._rs_stream()
            elif p == "/snapshot/rs.jpg":          # 🥽 RealSense 单帧
                self._send(200, "image/jpeg", _rs_jpeg())
            elif p == "/api/rs_info":              # 🥽 出厂内参 + 深度体检 + 帧龄
                import realsense_source as RS
                self._json(RS.info())
            elif p == "/api/rs_detect":            # 🥽 在 AR 相机帧里跑在役 YOLO 找光模块(标定用)
                self._json(_rs_detect(conf=float(qs.get("conf", "0.25")),
                                      imgsz=int(qs.get("imgsz", "640"))))
            elif p == "/api/rs_options":            # 🥽 相机可调项全表(找 AE 测光区等)
                self._json(_rs_options())
            elif p == "/api/rs_exposure":          # 🥽 曝光/增益(强逆光过曝会污染叠加): 读+可调
                _a = qs.get("auto")
                _e = qs.get("exposure")
                _g = qs.get("gain")
                self._json(_rs_exposure(
                    auto=(None if _a is None else (_a not in ("0", "false", "no"))),
                    exposure_us=(float(_e) if _e else None),
                    gain=(float(_g) if _g else None)))
            elif p == "/api/rs_pose":              # 🥽 目标相机系 3D 位姿 + 虚拟坐标架叠加(深度)
                _roi = None
                if qs.get("roi"):
                    try:
                        _roi = [int(float(v)) for v in qs["roi"].split(",")][:4]
                    except Exception:                                                # noqa: BLE001
                        _roi = None
                self._json(_rs_pose(use_last_detect=(qs.get("det", "1") != "0"), roi=_roi))
            elif p == "/api/rs_point":             # 🥽 像素→相机系 3D(用深度量, 不是猜)
                import realsense_source as RS
                self._json(RS.deproject(float(qs.get("u") or 0), float(qs.get("v") or 0)))
            elif p == "/cam.mjpg":
                _mj = (CAMS.get(cam) or CAMS["local"]).get("mjpg")
                if _mj == "/rs.mjpg":              # 🥽 RealSense 是本机源, 不能走 8791 代理
                    self._rs_stream()
                else:
                    self._proxy_stream(_mj)
            elif p in ("/local.mjpg", "/local2.mjpg"):
                self._proxy_stream(p)
            elif p.startswith("/snapshot/") and p.endswith(".jpg"):
                self._send(200, "image/jpeg", _get(p))
            elif p.startswith("/snap/") and p.endswith(".jpg"):     # 🥽 按相机键取一帧(rs 走本机, 其余走状态空间视频源)
                _b, _src = frame_bytes(p[len("/snap/"):-4])
                self._send(200, "image/jpeg", _b)
            else:
                self._send(404, "text/plain", b"not found")
        except Exception as e:                                                    # noqa: BLE001
            self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)}, 500)

    def _proxy_stream(self, p):
        """MJPEG 透传: 不断开、边读边写(不要 copyfile — 它是无限的)。

        🔴 2026-10-19 实测事故 (老倪: 「怎么卡住了? 电脑怎么这么慢」):
          客户端(AR 页面/内嵌窗口刷新或关闭)断开后, 服务端这条连接停在 CLOSE-WAIT,
          而 `wfile.write` 在 socket 缓冲写满之前**不会报错** ⇒ 子进程继续 read/write 空转。
          实测两个这样的僵尸流子进程各 38% CPU、白烧 7 分钟, 又各占一个 max_children 名额,
          整机 load average 冲到 14 (8 核) ⇒ 控制台/相机全卡。
          所以这里必须: ① 单连接有硬上限时长; ② 每块 flush 让 EPIPE 尽早暴露; ③ 任何异常都收摊。
        """
        _t0 = time.time()
        try:
            req = urllib.request.Request(UP + p)
            with urllib.request.urlopen(req, timeout=20) as r:
                self.send_response(200)
                self.send_header("Content-Type", r.headers.get("Content-Type", "multipart/x-mixed-replace"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

                while True:
                    if time.time() - _t0 > 300:          # 硬上限 5 分钟: 超时收摊, 让页面自己重连
                        break
                    chunk = r.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()                   # 断链 ⇒ BrokenPipe 立刻暴露, 不拖到缓冲写满
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                                                    # noqa: BLE001
            self.log_message("stream err %s", e)
        finally:
            self.close_connection = True

    def _fence_audit(self, route, fid, body):        # 🧱 围栏写操作审计: 谁/何时/改了什么
        try:
            import json as _j
            import time as _t
            rec = {"ts": _t.strftime("%Y-%m-%d %H:%M:%S"), "route": route, "id": fid,
                   "client": self.client_address[0] if self.client_address else "-",
                   "body": body}
            os.makedirs(os.path.join(REPO, "zmax_data", "ar_rs"), exist_ok=True)
            with open(os.path.join(REPO, "zmax_data", "ar_rs", "fences_audit.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(_j.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:                                                     # noqa: BLE001
            pass

    # ── 跟随一条直线元素 (往复 N 次) ─────────────────────────
    FOLLOW_ST = os.path.join(REPO, "zmax_data", "ar_rs", "follow_status.json")
    FOLLOW_LOG = os.path.join(REPO, "zmax_data", "ar_rs", "follow_last.log")

    def _follow_status(self):
        try:
            d = json.load(open(self.FOLLOW_ST, encoding="utf-8"))
        except Exception:                                                     # noqa: BLE001
            d = {"state": "idle"}
        d["log_tail"] = ""
        try:
            with open(self.FOLLOW_LOG, encoding="utf-8") as f:
                d["log_tail"] = "".join(f.readlines()[-8:])
        except Exception:                                                     # noqa: BLE001
            pass
        return d

    def _follow_stop(self):
        import signal as _sig
        try:
            d = json.load(open(self.FOLLOW_ST, encoding="utf-8"))
            pid = int(d.get("pid") or 0)
            if pid > 0:
                os.kill(pid, _sig.SIGTERM)
                return {"ok": True, "msg": "已终止 pid=%d" % pid}
        except Exception as e:                                                # noqa: BLE001
            return {"ok": False, "err": str(e)}
        return {"ok": False, "err": "没有在跑的跟随进程"}

    def _follow_line(self, body):
        """POST /api/fence/follow {id, loops, speed} ⇒ 后台跑 run_along_line.py"""
        fid = str(body.get("id") or "")
        loops = int(body.get("loops") or 3)
        speed = float(body.get("speed") or 100.0)
        st = self._follow_status()
        if st.get("state") == "running":
            pid = int(st.get("pid") or 0)
            if pid and os.path.exists("/proc/%d" % pid):
                self._json({"ok": False, "err": "已经在跟随中 (pid=%d)" % pid})
                return
        try:
            it = next((x for x in FS.listing()["items"] if x["id"] == fid), None)
        except Exception:                                                     # noqa: BLE001
            it = None
        if not it or it.get("type") != "line":
            self._json({"ok": False, "err": "只有直线元素能 Follow"})
            return
        log = open(self.FOLLOW_LOG, "w", encoding="utf-8")
        cmd = [os.path.join(REPO, "gui-venv311", "bin", "python"),
               os.path.join(REPO, "tools", "run_along_line.py"),
               "--id", fid, "--loops", str(loops), "--speed", str(speed),
               "--zone", "5", "--npts", "1", "--chunk", "0"]
        pr = subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True)
        json.dump({"state": "running", "pid": pr.pid, "id": fid, "name": it.get("name"),
                   "loops": loops, "speed": speed,
                   "started": time.strftime("%F %T")},
                  open(self.FOLLOW_ST, "w", encoding="utf-8"), ensure_ascii=False)
        self._fence_audit("/api/fence/follow", fid, {"loops": loops, "speed": speed})
        self._json({"ok": True, "pid": pr.pid,
                    "msg": "开始跟随「%s」· 往复 %d 次 · %.0fmm/s" % (it.get("name"), loops, speed)})

    # ── 数据 ────────────────────────────────────────────────
    def _traj(self):
        d = json.loads(_get("/scene.json"))
        arm = ((d.get("cameras") or {}).get("arm") or {})
        out = {"trace": [], "plan": [], "trace_label": "", "plan_label": ""}
        for b in arm.get("boxes") or []:
            if b.get("kind") != "path3d":
                continue
            o = str(b.get("origin"))
            if o in out and b.get("pts3d"):
                out[o] = b["pts3d"]
                out[o + "_label"] = str(b.get("label") or "")
        # 🆕 真机实际走过的 TCP 轨迹 (bridge_path_recorder.py 录的实测点), 与仿真 trace/plan 分开画
        try:
            rp = os.path.join(REPO, "zmax_data", "ss_live", "bridge_real_path.json")
            rj = json.load(open(rp, encoding="utf-8"))
            out["real"] = rj.get("pts") or []
            out["real_n"] = rj.get("n")
            out["real_len_mm"] = rj.get("len_mm")
            out["real_age_s"] = round(time.time() - os.path.getmtime(rp), 1)
            out["real_stage"] = rj.get("stage")
            out["real_label"] = "真机跟随轨迹(实测 %s 点 · %smm · 阶段 %s)" % (
                rj.get("n"), rj.get("len_mm"), rj.get("stage") or "?")
        except Exception:                                                          # noqa: BLE001
            out["real"] = []
        out["ok"] = True
        out["at"] = time.strftime("%H:%M:%S")
        return out

    MOD3_STATE = "/dev/shm/mod3_latest.json"
    MOD3_FRAME = "/dev/shm/mod3_frame.jpg"
    MOD3_LOCK = os.path.join(REPO, "zmax_data", "ar_state", "module3d_lock.json")

    def _toolframe_img(self, L=80.0, tip_inset_px=None):
        """现场最直观的一张图: 当前臂相机帧 + tool1 三轴。直接 GET /toolframe.jpg 就能看。"""
        try:
            img = None
            try:
                b = urllib.request.urlopen("http://127.0.0.1:8791/snapshot/arm.jpg", timeout=6).read()
                img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
            except Exception:                                               # noqa: BLE001
                pass
            if img is None:
                self._send(503, "text/plain; charset=utf-8", "臂相机取帧失败".encode())
                return
            tf = toolframe_px(L, align_box=True, tip_inset_px=tip_inset_px)
            if not tf.get("ok"):
                self._send(200, "application/json", json.dumps(tf, ensure_ascii=False).encode())
                return
            S = 2
            big = cv2.resize(img, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)
            O = tuple(int(round(v * S)) for v in tf["origin"])
            for k, col in (("X", (60, 60, 235)), ("Y", (60, 210, 60)), ("Z", (235, 140, 40))):
                T = tuple(int(round(v * S)) for v in tf["axes"][k])
                cv2.arrowedLine(big, O, T, col, 3, cv2.LINE_AA, tipLength=0.12)
                cv2.putText(big, k, (T[0] + 6, T[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2, cv2.LINE_AA)
            cv2.circle(big, O, 7, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(big, O, 7, (30, 30, 30), 2, cv2.LINE_AA)
            cv2.putText(big, "tool1(模块头)",
                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            ok, jpg = cv2.imencode(".jpg", big, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if not ok:
                self._send(500, "text/plain; charset=utf-8", b"encode failed")
                return
            self._send(200, "image/jpeg", jpg.tobytes())
        except Exception as e:                                              # noqa: BLE001
            self._send(500, "text/plain; charset=utf-8", ("toolframe 图失败: %s" % e).encode())

    def _mod3_lock(self, action="status"):
        """🔒 绿框定主/解锁/查状态。定主 = 把当前 3D 框坐标钉死, 之后 /api/module3d 一律回这份。"""
        p = self.MOD3_LOCK
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
        except Exception:                                                   # noqa: BLE001
            pass
        if action == "unlock":
            try:
                os.remove(p)
            except FileNotFoundError:
                return {"ok": True, "locked": False, "msg": "本来就没锁"}
            return {"ok": True, "locked": False, "msg": "已解锁: 绿框回到实时检测"}
        if action == "lock":
            try:
                with open(self.MOD3_STATE, encoding="utf-8") as f:
                    r = json.load(f)
            except Exception as e:                                          # noqa: BLE001
                return {"ok": False, "err": "检测线程还没出结果, 无法定主: %s: %s"
                        % (type(e).__name__, str(e)[:80])}
            if not r.get("ok") or not r.get("corners_px"):
                return {"ok": False, "err": "当前这一帧没检出光模块 ⇒ 不能拿空框定主"}
            L = {"locked": True, "ts": time.time(),
                 "corners_px": r["corners_px"], "box2d": r.get("box2d"),
                 "dims_mm": r.get("dims_mm"), "dist_mm": r.get("dist_mm"),
                 "edges": r.get("edges"), "clipped": r.get("clipped"),
                 "frame_size": r.get("frame_size"),
                 "by": "老倪 2026-10-20: 相机与光模块相对无运动 ⇒ 绿框定主不变"}
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(L, f, ensure_ascii=False)
            os.replace(tmp, p)
            return {"ok": True, "locked": True, "lock": L,
                    "msg": "已定主: 绿框坐标从现在起不再变 (解锁用同一按钮)"}
        try:
            with open(p, encoding="utf-8") as f:
                L = json.load(f)
            L["ok"] = True
            L["age_s"] = round(time.time() - float(L.get("ts") or 0), 1)
            return L
        except FileNotFoundError:
            return {"ok": True, "locked": False}
        except Exception as e:                                              # noqa: BLE001
            return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:80])}

    def _module3d(self, want_img=False):
        """🔍 光模块 3D 框: 直接读**后台线程**算好的最新结果(请求路径上不跑推理)。

        🔴 2026-10-18 现场: 原来每个请求在 fork 出来的子进程里跑一次 YOLO, 实测 969ms
        (其中 ~900ms 是子进程重新装载权重), 而且 fork 后多子进程并发推理会卡死(实测请求 25s 不返回,
        页面就"没有绿框")。现在改成: 父进程里一个常驻线程持续算(约 6Hz), 请求只读 /dev/shm 的结果。
        """
        try:
            with open(self.MOD3_STATE, encoding="utf-8") as f:
                r = json.load(f)
        except Exception:                                                   # noqa: BLE001
            return {"ok": False, "err": "光模块检测线程还没出结果(刚启动? 看服务日志)"}
        try:
            _age = round(time.time() - float(r.get("ts") or 0), 2)
            r["result_age_s"] = _age
            # 🔴 2026-10-19 现场: 检测线程检不到目标时**保留上一帧结果**, 而页面又把旧框画在新画面上
            #   (22:05:42 的框画在 22:09 的画面里) ⇒ 用户看到的就是"绿色框向左偏了"。
            #   这里如实标 stale, 页面不得把陈旧框当实时框画成实线。
            r["stale"] = bool(_age > 2.5 or not r.get("ok"))
        except Exception:                                                   # noqa: BLE001
            pass
        # 🔒 定主: 老倪 2026-10-20「手臂相机的绿色边界框, 定主, 不要变; 相机和光模块相对无运动」
        #   相机在臂上、光模块夹在夹爪里 ⇒ 两者刚性相对 ⇒ 绿框每帧重算只会因检测抖动而"跳"。
        #   有锁文件就**一律回锁定的坐标**(stale=False), 同时把实时那路的活性放进 live 字段,
        #   让页面能分辨"框定住了"和"检测线程死了"。
        try:
            with open(self.MOD3_LOCK, encoding="utf-8") as f:
                _L = json.load(f)
            if _L.get("locked") and _L.get("corners_px"):
                r = {"ok": True, "locked": True, "stale": False,
                     "corners_px": _L["corners_px"], "box2d": _L.get("box2d"),
                     "dims_mm": _L.get("dims_mm"), "dist_mm": _L.get("dist_mm"),
                     "edges": _L.get("edges"), "clipped": _L.get("clipped"),
                     "frame_size": _L.get("frame_size"),
                     "lock_age_s": round(time.time() - float(_L.get("ts") or 0), 1),
                     "live": {"ok": bool(r.get("ok")), "age_s": r.get("result_age_s"),
                              "box2d": r.get("box2d")},
                     "note": "🔒 定主(相机↔光模块相对无运动): 坐标不随检测抖动"}
        except FileNotFoundError:
            pass
        except Exception:                                                   # noqa: BLE001
            pass
        if want_img:
            try:
                import base64
                with open(self.MOD3_FRAME, "rb") as f:
                    r["jpg_b64"] = base64.b64encode(f.read()).decode()
                r["frame_file_ts"] = os.path.getmtime(self.MOD3_FRAME)
            except Exception as e:                                          # noqa: BLE001
                r["img_err"] = str(e)
        return r

    def _traj_state(self):
        st = TD.get_state()
        rec = 0
        age = None
        try:
            _p = os.path.join(REPO, "reports", "moveit", "live_trace.json")
            rec = int(json.load(open(_p)).get("n") or 0)
            # 🆕 轨迹链的"心跳": 发布器每 1.5s 重写这个文件 ⇒ 它的 mtime 就是整条链(录制器→发布器)的
            #    活证。8 小时前停掉的链会让"已录 N 点"看着像真的(老倪现场就是这么被误导的), 页面必须能看出来。
            age = round(time.time() - os.path.getmtime(_p), 1)
        except Exception:                                                          # noqa: BLE001
            pass
        return {"ok": True, "state": st, "in_spec": TD.paths_in_spec(),
                "recorded_pts": rec, "trace_age_s": age, "plan_cached": TD.paths_cached(),
                "hint": "show=false 是默认(人工开启); clear 只影响显示, 录制历史保留"}

    def _stable(self, seconds: float = 1.2):
        pts = []
        t0 = time.time()
        while time.time() - t0 < seconds:
            d = read_tcp()
            if d.get("ok"):
                pts.append((d["x"], d["y"], d["z"]))
            time.sleep(0.1)
        if len(pts) < 3:
            return {"ok": False, "err": "读不到 TCP"}
        a = np.array(pts)
        drift = float(np.linalg.norm(a - a.mean(0), axis=1).max() * 1000.0)
        return {"ok": True, "drift_mm": round(drift, 2), "stable": drift < 3.0, "n": len(pts)}

    def _verify(self, cam="local"):
        c = load_calib(cam)
        if not c:
            return {"ok": False, "err": "还没有标定(%s)" % cam}
        m = motion_mask(cam=cam)
        n_mv = int(m.sum())
        tcp = read_tcp()
        if not tcp.get("ok"):
            return {"ok": False, "err": "读不到 TCP"}
        if n_mv == 0:
            return {"ok": False, "err": "画面没有运动像素 —— 请**移动一下机械臂**再验证",
                    "moving_px": 0}
        hits, total, detail = LS.tcp_motion_hits(c, [{"mask": m, "tcp": [tcp["x"], tcp["y"], tcp["z"]]}])
        return {"ok": True, "hits": hits, "total": total, "moving_px": n_mv, "detail": detail,
                "note": "hits=1 ⇒ 当前 TCP 投影落在正在运动的机械臂上(AR 对准)"}

    # ── 标定 ────────────────────────────────────────────────
    def do_POST(self):                                                            # noqa: N802
        p = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8", "ignore") or "{}")
        except Exception:                                                         # noqa: BLE001
            body = {}
        if p == "/api/module3d_lock":     # 🔒 绿框定主 (lock|unlock|status)
            self._json(self._mod3_lock(str(body.get("action") or "status")))
        elif p == "/api/aoi/inspect":            # 🔍 真拍 + 缺陷检测 + 矩形搜索 + 侧边修正
            self._json(self._aoi_inspect(port=int(body.get("port") or 10082)))
        elif p == "/api/calib":
            self._json(self._do_calib(body))
        elif p == "/api/fence/add":        # 🧱 加长方体/正方体/直线 (对角两点, base 系, 米)
            try:
                self._fence_audit("/api/fence/add", "-", body)
                it = FS.add(body.get("type") or "box", body.get("p1"), body.get("p2"),
                            name=body.get("name") or "", color=body.get("color") or "",
                            note=body.get("note") or "")
                self._json({"ok": True, "item": it, "n": len(FS.listing()["items"])})
            except Exception as e:                                                 # noqa: BLE001
                self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        elif p == "/api/fence/update":     # 🧱 改端点/名字/开关
            try:
                self._fence_audit("/api/fence/update", str(body.get("id") or ""), body)
                it = FS.update(str(body.get("id") or ""), p1=body.get("p1"), p2=body.get("p2"),
                               name=body.get("name"), color=body.get("color"),
                               enabled=body.get("enabled"), note=body.get("note"))
                self._json({"ok": True, "item": it})
            except Exception as e:                                                 # noqa: BLE001
                self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        elif p == "/api/fence/delete":
            try:
                self._fence_audit("/api/fence/delete", str(body.get("id") or ""), body)
                self._json(dict(ok=True, **FS.delete(str(body.get("id") or ""))))
            except Exception as e:                                                 # noqa: BLE001
                self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        elif p == "/api/fence/follow":     # 🏃 让 tool1 跟着这条直线元素往复走 (真机动作)
            self._follow_line(body)
        elif p == "/api/fence/follow/status":
            self._json(self._follow_status())
        elif p == "/api/fence/follow/stop":
            self._json(self._follow_stop())
        elif p == "/api/fence/clear":
            r = FS.clear()
            self._fence_audit("/api/fence/clear", "-", body)
            self._json(dict(ok=True, **r))
        elif p == "/api/fence/margin":
            self._json(dict(ok=True, **FS.set_margin(float(body.get("mm") or 0))))
        elif p == "/api/traj/show":
            show = bool(body.get("show"))
            r = TD.apply(show)
            pub = self._publish_once(show)
            self._json({"ok": True, "show": show, "detail": r, "publish": pub,
                        "in_spec": TD.paths_in_spec(),
                        "msg": ("✅ 已显示轨迹(实测轨迹 + 规划航路)" if show
                                else "⏸ 已隐藏轨迹(画面上的轨迹线撤掉, 录制历史保留)")})
        elif p == "/api/traj/clear":
            rec = 0
            try:
                rec = int(json.load(open(os.path.join(REPO, "reports", "moveit",
                                                      "live_trace.json"))).get("n") or 0)
            except Exception:                                                      # noqa: BLE001
                pass
            TD.set_state(baseline_n=rec)
            # 🧹 真机实测轨迹(橙色)也要清: 只清仿真 trace 的话, 橙色线还在 ⇒ 按钮看着"点了没用"
            #    ① 立刻把 JSON 清空(页面下一次轮询就看不到)
            #    ② 写控制文件通知录制器丢缓冲(不然它 1s 后又把内存里的点写回来)
            try:
                _rp = os.path.join(REPO, "zmax_data", "ss_live", "bridge_real_path.json")
                _now = time.time()
                with open(_rp + ".ctl", "w", encoding="utf-8") as _f:
                    json.dump({"clear_at": _now}, _f)
                with open(_rp, "w", encoding="utf-8") as _f:
                    json.dump({"ok": 1, "src": "已清除", "n": 0, "pts": [], "t0": None, "t1": None,
                               "len_mm": 0.0, "stage": "", "at": time.strftime("%H:%M:%S")},
                              _f, ensure_ascii=False)
            except Exception:                                                      # noqa: BLE001
                pass
            pub = self._publish_once(True) if TD.get_state()["show"] else None
            # 🔴 2026-09-29 现场「删除轨迹删不掉」的真根因: 这条路**只改了清除线**, 真正把折线从叠加规格里
            #    挪走的是发布器(live_trace_publisher); 而发布器要读录制器(容器内)落的 /tmp/live_trace.json,
            #    录制器一停它只打一行"还没有轨迹数据"就退出 ⇒ 画面上那条历史折线永远在, 按钮点了没反应。
            #    兜底: 直接改叠加规格(挪进可恢复缓存), 不依赖录制器/发布器任何一环。
            strip = None
            try:
                _tn = int(((TD.paths_in_spec() or {}).get("trace") or {}).get("n_pts") or 0)
                # 🔴 只在"发布器这一轮没拿到数据"时兜底(录制器死了) —— 不能无条件 strip:
                #    链健康时发布器会把清除线之后**新走过**的点重画上去, 那时候删它反而是错的。
                # 只要画面上还有 trace 折线, 就把它挪走 —— 老倪要的是"点了就消失", 不能再去猜
                # 发布器/录制器这一轮有没有干活(实测: 录制器死了但主机上还留着旧副本时, 发布器照样
                # 会把那条**冻结的旧轨迹**重发上去 ⇒ 只改清除线 = 画面纹丝不动)。新走过的点
                # 由发布器下一轮(1.5s)重新画上去, 不会丢。
                if TD.get_state()["show"] and _tn > 0:
                    strip = TD.strip_origins(["trace"])
            except Exception as e:                                                # noqa: BLE001
                strip = {"err": str(e)[:120]}
            _m = "🧹 已清除画面上走过的轨迹(清除线=%d); 之后新走的会重新画. 录制历史未动" % rec
            if isinstance(strip, dict) and strip.get("moved"):
                _m += " · 兜底直连: 已从叠加层挪走 %d 条折线(可恢复)" % strip["moved"]
            self._json({"ok": True, "baseline_n": rec, "publish": pub, "strip": strip, "msg": _m})
        elif p == "/api/traj/baseline":                 # 直接设"清除线": 0 = 画全部历史
            n = body.get("n")
            n = 0 if n is None else max(0, int(n))
            TD.set_state(baseline_n=n)
            pub = self._publish_once(True) if TD.get_state()["show"] else None
            # 同上的兜底(反向): 录制器不在时, "全部历史"靠缓存里的折线放回去, 不能只依赖发布器
            rest = None
            try:
                _tn = int(((TD.paths_in_spec() or {}).get("trace") or {}).get("n_pts") or 0)
                _cn = int(((TD.paths_cached() or {}).get("trace") or {}).get("n_pts") or 0)
                if n == 0 and _tn == 0 and _cn > 0:
                    rest = TD.restore_origins(["trace"])
            except Exception as e:                                                # noqa: BLE001
                rest = {"err": str(e)[:120]}
            _m = ("📜 清除线已归 0 ⇒ 画**全部已走过**的轨迹" if n == 0 else "清除线=%d" % n)
            if isinstance(rest, dict) and rest.get("restored"):
                _m += " · 兜底直连: 已放回 %d 条折线" % rest["restored"]
            self._json({"ok": True, "baseline_n": n, "publish": pub, "restore": rest, "msg": _m})
        else:
            self._json({"ok": False, "err": "no route %s" % p}, 404)

    def _publish_once(self, show: bool):
        """让发布器立刻跑一轮 ⇒ 按钮点了就见效(不然最多等 2s 的壳周期)。"""
        try:
            import subprocess
            env = dict(os.environ)
            py = os.path.join(REPO, "gui-venv311", "bin", "python")
            r = subprocess.run([py, os.path.join(HERE, "live_trace_publisher.py"), "--once"],
                               capture_output=True, text=True, timeout=90, env=env)
            return (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
        except Exception as e:                                                    # noqa: BLE001
            return ["发布器单跑失败: %s" % str(e)[:120]]

    def _aoi_inspect(self, port=10082):
        """🔍 联合工控机 AOI: 真拍一张 → 缺陷判决(/last_result) + 金手指矩形搜索(/region) + 侧边修正。

        口径照 aoi_link/zmax-aoi-service: 200 只是受理, 判决要轮询 /last_result;
        结果落 zmax_data/ar_aoi_state.json (AR 页面/其他工具读同一份)。
        """
        if AOI is None:
            return {"ok": False, "err": "aoi_link 不可用"}
        try:
            out = AOI.inspect(port)
        except Exception as e:                                                   # noqa: BLE001
            return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}
        out["ok"] = bool((out.get("detect") or {}).get("ok") or (out.get("region") or {}).get("ok"))
        try:
            tmp = AOI_STATE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            os.replace(tmp, AOI_STATE)
        except Exception:                                                        # noqa: BLE001
            pass
        return out

    def _rs_proxy(self):
        """把 /api/rs_* · /snap/rs.jpg · /rs.mjpg 原样转给 rs_service (8789)。

        流式(MJPEG)按块搬运, 其余一次性取回; 小服务不在就如实 503, 不装死、不返回空图。
        """
        import urllib.request
        import urllib.error
        _p = self.path
        _map = {"/snapshot/rs.jpg": "/snap.jpg", "/snap/rs.jpg": "/snap.jpg",
                "/api/rs_info": "/api/info", "/api/rs_options": "/api/options",
                "/api/rs_exposure": "/api/exposure", "/api/rs_pose": "/api/pose",
                "/api/rs_detect": "/api/detect", "/api/rs_point": "/api/point"}
        _base = _p.split("?")[0]
        _qs = ("?" + _p.split("?", 1)[1]) if "?" in _p else ""
        url = "http://127.0.0.1:8789" + _map.get(_base, _base) + _qs
        try:
            r = urllib.request.urlopen(url, timeout=15)
        except urllib.error.HTTPError as e:                      # 小服务自己给的 4xx/5xx 原样透出
            body = e.read() or b""
            self._send(e.code, e.headers.get("Content-Type", "application/json"), body)
            return
        except Exception as e:                                   # noqa: BLE001
            self._json({"ok": False, "err": "RealSense 小服务(8789)不可达: %s" % str(e)[:120],
                        "hint": "bash tools/rs_service.sh start  (单进程独占 D435)"}, 503)
            return
        _ct = r.headers.get("Content-Type", "")
        if "multipart/x-mixed-replace" in _ct:                   # MJPEG: 边读边写
            self.send_response(200)
            self.send_header("Content-Type", _ct)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    chunk = r.read(32768)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                try:
                    r.close()
                except Exception:                                # noqa: BLE001
                    pass
                self.close_connection = True
            return
        try:
            body = r.read()
        finally:
            r.close()
        self._send(200, _ct or "application/json; charset=utf-8", body)

    def _rs_stream(self):
        """🥽 RealSense 的 MJPEG 流: 由 realsense_source 提供(不走 8791 代理)。"""
        import realsense_source as RS
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            _t0 = time.time()
            for part in RS.mjpeg(fps=15, quality=78):
                if time.time() - _t0 > 300:      # 同 _proxy_stream: 断链不许永久占住子进程
                    break
                self.wfile.write(part)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                                                   # noqa: BLE001
            sys.stderr.write("[rs.mjpg] %s: %s\n" % (type(e).__name__, str(e)[:100]))
        finally:
            self.close_connection = True

    def _do_calib(self, body):
        cam = str(body.get("cam") or "local")
        meta = CAMS.get(cam) or CAMS["local"]
        W, H = int(meta["w"]), int(meta["h"])
        pts = body.get("points") or []
        # 🥽 相机有出厂内参(RealSense D435) ⇒ 焦距/主点不再解, 只解 R,t: 4 点就够(建议 5~8, 且高低左右都要变)
        _ci, _need, _why = None, 6, "至少 6 个点(建议 6~8, 且**高低/左右都要变**): 少于 6 个时没有线性初值(DLT), 容易解飞"
        if (CAMS.get(cam) or {}).get("intrinsics") == "device":
            try:
                import realsense_source as RS
                _ci = RS.intrinsics() or None
            except Exception:                                                    # noqa: BLE001
                _ci = None
            if _ci:
                _need = 4
                _why = "至少 4 个点(该相机有出厂内参, 只解 R,t —— 建议 5~8 个, 高低/左右都要变)"
        if len(pts) < _need:
            return {"ok": False, "err": "%s —— 现在 %d 个" % (_why, len(pts))}
        P3 = [q["tcp"] if isinstance(q.get("tcp"), list) else [q["tcp"]["x"], q["tcp"]["y"], q["tcp"]["z"]]
              for q in pts]
        P2 = [q["uv"] for q in pts]
        # 几何质量自检: 3D 点别挤成一条线/一个面
        A = np.array(P3, float)
        s = A.std(0) * 1000.0                                                     # mm
        spread_mm = float(np.linalg.norm(s))
        rng_mm = [float(v) for v in (A.max(0) - A.min(0)) * 1000.0]
        sol = (LS.solve(P3, P2, W, H, f_fixed=_ci["fx"], cx=_ci["ppx"], cy=_ci["ppy"])
               if _ci else LS.solve(P3, P2, W, H))
        if sol is None:
            return {"ok": False, "err": "解算失败(超定/退化) —— 点多散布一些再试"}
        calib = {
            "kind": "laptop_cam_calib", "cam": cam,
            "model": ("pinhole, 焦距/主点=**相机出厂内参**" if _ci else "pinhole, fx=fy=f, 主点=图像中心"),
            "intrinsics_source": ("设备出厂内参 (只解 R,t)" if _ci else "页面标定 (解 f+R+t)"),
            "device_intrinsics": (None if not _ci else {"fx": _ci["fx"], "fy": _ci["fy"],
                                                        "ppx": _ci["ppx"], "ppy": _ci["ppy"]}),
            "f": sol["f"], "cx": sol["cx"], "cy": sol["cy"], "image_size": sol["image_size"],
            "R_base_to_cam": sol["R"], "t_base_to_cam": sol["t"],
            "rms_px": round(sol["rms_px"], 2), "err_px": [round(e, 2) for e in sol["err_px"]],
            "n_points": len(P3), "spread_sigma_mm": round(spread_mm, 1), "range_mm": rng_mm,
            "solver_selftest": bool(LS.selftest(verbose=False)),
            "dlt_used": bool(sol.get("dlt_used")),
            "points": [{"uv": [float(u) for u in uvv], "tcp": [float(v) for v in p3]}
                       for uvv, p3 in zip(P2, P3)],
            "method": "页面人工标定: 停稳后点画面里的夹爪尖, 同刻记录 TCP 真值 → 解 f/rvec/t",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        warn = []
        if sol["rms_px"] > 8.0:
            warn.append("重投影 RMS %.1fpx 偏大(>8): 八成有点点位不准或臂没停稳" % sol["rms_px"])
        if spread_mm < 40:
            warn.append("点位太集中(σ=%.0fmm): 请把机械臂停到**不同高度/左右前后**再采点" % spread_mm)
        if cam not in CAMS:
            warn.append("相机名 %r 不认识(只认 %s), 按默认分辨率存了" % (cam, list(CAMS)))
        saved = save_calib(cam, calib)
        return {"ok": True, "calib": calib, "warn": warn, "cam": cam,
                "saved": os.path.relpath(saved, REPO),
                "next": "移动机械臂后点『验证对准』, 看 TCP 投影是否落在正在运动的手臂上"}


def main():
    if not os.path.exists(PAGE):
        print("✗ 页面不存在: %s" % PAGE); return 1
    # 2026-10-12 现场: 线程模型(ThreadingHTTPServer)会把整个服务憋死 ——
    #   实测 74 线程 / 16 条 CLOSE-WAIT / 主线程卡 futex(不再 accept) ⇒ 新连接一律超时(AR 按钮打不开),
    #   只有老连接还能被服务。换成**每连接一进程**(ForkingMixIn): 一个连接卡死/线程泄漏都影响不到 accept。
    #   max_children 兜住内存(父进程 ~60MB × N)。
    class _ForkingSrv(socketserver.ForkingMixIn, HTTPServer):
        allow_reuse_address = True
        daemon_threads = True
        max_children = 24
    try:                                    # 🔴 光模块检测线程: 父进程常驻, 请求只读结果(不在请求里跑推理)
        OB3.warm()
        threading.Thread(target=_mod3_worker, name="mod3", daemon=True).start()
        print("  🔍 光模块检测线程: 已启动 (结果 → /dev/shm/mod3_latest.json, 供 /api/module3d 读)")
    except Exception as _e:                                                 # noqa: BLE001
        print("  🔍 光模块检测线程启动失败: %s" % _e)
    srv = _ForkingSrv(("0.0.0.0", PORT), H)
    print("═══ TCP 轨迹 AR/VR 服务 ═══")
    print("  AR 页:      http://0.0.0.0:%d/          (手机/PC 同网可开)" % PORT)
    for k, v in CAMS.items():
        print("  底图 %-7s %s  → 代理 %s%s" % (k, v["label"], UP, v["mjpg"]))
    print("  轨迹来源:   %s/scene.json 的 cameras.arm 里 origin=trace/plan (kind=path3d)" % UP)
    print("  标定文件:   %s" % os.path.relpath(MCALIB, REPO))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n退出")
    return 0



# ═══ 光模块检测线程 (2026-10-18) ═══
# 每 ~6Hz: 取臂相机一帧 → 检测+3D → 结果写 /dev/shm/mod3_latest.json, 原帧写 /dev/shm/mod3_frame.jpg
# 请求路径只读文件 ⇒ 页面拿到的是"同一帧 + 对应的框", 不会出现框比画面滞后
MOD3_STATE = "/dev/shm/mod3_latest.json"
MOD3_FRAME = "/dev/shm/mod3_frame.jpg"


def _mod3_write(r, frame_b=None):
    """把一次检测结果落盘。**检测失败时不要用空结果覆盖** —— 老倪 2026-10-18「别丢光模块」:
    只要之前检出过, 就继续显示上一帧的框, 并用 stale/detect_lost 明确告诉页面"这是沿用的旧结果"。"""
    if r.get("ok"):
        r["detect_lost"] = 0
        if frame_b is not None:
            with open(MOD3_FRAME, "wb") as f:
                f.write(frame_b)
    else:
        # 画面必须继续走(否则整幅冻住), 只是框沿用上一次并标 stale —— 图像是新的, 框是旧的, 页面上明说
        if frame_b is not None:
            try:
                with open(MOD3_FRAME, "wb") as f:
                    f.write(frame_b)
            except Exception:                                               # noqa: BLE001
                pass
        prev = None
        try:
            with open(MOD3_STATE, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:                                                   # noqa: BLE001
            prev = None
        if not (prev and prev.get("ok")):
            r["ts"] = time.time()
            r["t"] = time.strftime("%H:%M:%S")
        else:
            prev = dict(prev)
            prev["stale"] = True
            prev["detect_lost"] = int(prev.get("detect_lost") or 0) + 1
            prev["last_ts"] = prev.get("ts")          # 保留真实采集时间, 不许用新时间冒充
            prev["err"] = r.get("err") or "本帧未检出"
            r = prev
    _tmp = MOD3_STATE + ".%d.tmp" % os.getpid()
    with open(_tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    os.replace(_tmp, MOD3_STATE)


def _mod3_worker(period=0.15):
    while True:
        try:
            _b, _src = frame_bytes("arm")
            _img = cv2.imdecode(np.frombuffer(_b, np.uint8), cv2.IMREAD_COLOR)
            if _img is not None:
                _r = OB3.build(_img, read_tcp())
                _r.update({"frame_src": _src, "frame_bytes": len(_b), "edges": OB3.EDGES,
                           "ts": time.time(), "t": time.strftime("%H:%M:%S")})
                _mod3_write(_r, _b)
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(period)


if __name__ == "__main__":
    raise SystemExit(main())
