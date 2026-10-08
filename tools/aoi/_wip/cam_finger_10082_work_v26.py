"""
Z-MAX 金手指检测 AOI 程序 · 优化版 v4 (10082)
============================================
v21 change (2026-10-08; shop floor: "the gold fingers, why are the widths different?"):
  * JUDGE PICTURE REDONE = PIANO KEYS: a row of EQUAL-WIDTH vertical keys
    (one width = the median detected width, each key centred on its own detected
    centre) on pure black (0,0,0), exposure compressed by a linear gain; the mask is
    the SOLID RECTANGLE of each key (a dark inner part no longer goes black); the
    full-width bright bar only TRUNCATES the key band (no hole is punched in the
    middle); the odd wide block is dropped by width/spacing deviation > 60% (but the
    drop is skipped if fewer than 8 keys would remain, and the meta says so).
    Fixed size stays 900x332 (content scaled to width 900 with its natural aspect
    ratio and centred vertically on black; never stretched to fill).
  * UNCHANGED (byte for byte): the model input path (crop_goldfinger_regular /
    template crop / 960x960 model input), /last_result semantics and every route and
    response body.  Only the judge-render function block, the version string and this
    header note were replaced.
  * On judge-render failure -> (None, meta) and the caller falls back, exactly like v20.
v4 变更 (2026-09-20, 静静):
  ★ 核心: 金手指截取从"固定透视窗 [400,1000]-[2000,1250] 硬拉"改成【模板法规整裁剪】
    - 老问题: 固定窗与实际金手指条位置/姿态对不上(条中心 y 在 1008~1450 之间漂移, 条本身还带 ~0.6-1.0° 倾角),
      且 warp 输出尺寸被静默拉成原图尺寸 2448x2048 → 截出来的金手指"歪歪扭扭"、还被拉伸变形
    - 新做法: ① 用参考真图做"金手指条模板"(去倾斜后居中存放, 见 templates/gf_strip_template.png/.json)
              ② 运行期: 1/4 尺度多角度粗搜 → 1/1 尺度局部精修(角度+尺度)
              ③ 角度再用"裁剪图里条质心线斜率"做一次扫描精修(目标度量直接最小化, 不猜符号)
              ④ 单次仿射把条映射到规范化画布的固定位置 → 跨张一致、条水平、尺寸固定
    - 每个相机周期打印规整度自证: score / 残余倾角(px/1000) / 条质心线残差 / 金覆盖率
  ★ 旧版: 固定窗与实际金手指条位置/姿态对不上, 且 warp 输出尺寸被静默拉成原图尺寸 → 歪 + 拉伸
  ★ v4.1 (2026-09-20 现场反馈修 framing): 金手指区纵向范围改为"上含焊盘排 + 下不含塑料本体亮边沿"
      - ROI 定位: 金连通域定列段 → 列段内行密度(morph 剖面)带空隙容限扩展 → 顶到"焊盘排"顶边
      - 底部亮带切除: 行亮度中位数×1.25 以上的塑料本体反光边不裁进来(现场说"下面多一个大边沿")
      - 新增输出维度: 裁剪图里高亮(>180)像素占比 bright_frac (亮边沿若混进来这个数会明显变大)
  ★ 保留 v3 全部接口与异步方案: /capture_detect 秒回, 检测后台跑, /last_result 不变
  ★ 接口语义 (按现场要求): /picture = **原始图** (加 ?kind=crop 才给规整裁剪图); /crop_info = 裁剪结果指标
  ★ v4.2 (现场二次反馈): ①只保留"金手指"本身 —— 定位改成"最上面那片离散焊盘 run"(|gx| 高),
     下方那条实心金带与塑料本体亮边沿一律不进画布 ②金手指只占 1455x70(21:1)太扁 → 纵向拉伸到
     **960x960 方图**(与 config.yaml imgsz=960 对齐), 另存一份"原比例"版供目检
  ★ 新增 /crop_info: 最近一次裁剪的完整质量指标 (JSON), 便于外部取证
  ★ 保留旧几何开关: GF_CROP_MODE="legacy" 时退回 v3 的固定窗 warp (可一键回滚, 不用换文件)
  ★ 兜底链: 模板匹配失败/分数低 → HSV 条带兜底(仍是规整仿射) → 中心窗兜底(明确标记, 不装正常)

依赖: gf_crop.py / gf_metric.py / templates/gf_strip_template.png(.json) 与本文件同目录; yolo_detector 保持不变
"""
import os
import sys
import time
import json
import glob
import hashlib
import socket
import struct
import ctypes
import traceback
import threading
from threading import Thread
from flask import Flask, request, jsonify, Response

import cv2
import numpy as np
from SciCam_class import *
from SciCamErrorDefine_const import *
from SciCamInfo_header import *
from SciCamPayload_header import *
from yolo_detector import YoloDetector

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from gf_crop import GoldFingerCropper, annotate   # v4 核心: 模板法规整裁剪

VERSION = "v21"             # v21 = judge picture = piano keys (equal-width vertical keys + pure black + compressed exposure); model path/routes identical to v20
app = Flask(__name__)
m_Device = SciCamera()   # 相机设备全局实例 (原版保留)
detector = YoloDetector()  # 加密检测器全局实例, 启动加载一次 (原版保留)

# 图片保存根目录
SAVE_ROOT_DIR = r"./goldfinger_images"

# 端口-模型映射 (产线固定 10082; 启动时会把实际端口也注册进来, 便于换端口自测)
PRODUCTION_PORT = 10082
PORT_TO_DETECT_TYPE = {str(PRODUCTION_PORT): "gf"}

# ===== 配置: 模板法裁剪 =====
GF_CROP_MODE = os.environ.get("GF_CROP_MODE", "template")     # template | legacy
TEMPLATE_PNG = os.path.join(HERE, "templates", "gf_strip_template.png")
# —— 规范化画布: 金手指只占 1455x70(横向 21:1), 太扁, YOLO 会把它压成一条细线 →
#    现场要求"拉到符合 YOLO v8 的比例": 默认 960x960 方图(与 yolo_detector/config.yaml 的 imgsz=960 对齐,
#    推理时不做 letterbox 也不上采样), 金手指纵向拉伸填满画布。
CANONICAL_W = int(os.environ.get("GF_CANONICAL", "960"))   # 960 / 640 / 1280
CANONICAL_H = CANONICAL_W
KEEP_ASPECT = os.environ.get("GF_KEEP_ASPECT", "0") == "1"  # 1=保比例(只做对照/复核用)
MARGIN_X, MARGIN_Y = 0.02, 0.03   # 金手指条在画布内留的边距(2%/3%)
MIN_SCORE = 0.55              # 模板匹配分下限, 低于则告警(并用兜底结果)
SAVE_LEGACY_TOPVIEW = True    # 是否同时存一份 v3 几何的 topview (对照/回滚用)

# 金手指检测相机SN
TARGET_SN = "D265250070"
CAM_DESC = "金手指检测相机 OPT-CC1-GG50"

# 相机参数 (可调)
# ★ 2026-10-08 定值(实测扫出来的, 别拍脑袋改):
#   曝光 20000us × 增益 8.0 → 金手指条带 p50=206 / 暗缝 p10=49(对比度 157 最好), 曝光时间只有
#   相机原"自动曝光"那档(≈94ms)的 1/5 ⇒ 更锐(现场光源偏暗是客观事实, 用增益换曝光时间)。
EXPOSURE_US = 20000.0
GAIN_DB = 8.0          # 该相机增益下限 1.33 / 上限 16.38, 写 1.0 会被拒(rv=100100010)
GAMMA_VAL = 1.0
# 🆕 v24 (老倪 2026-10-08: 「你能按照你的经验, 调整一下曝光, 增益这样的参数么?」):
#   相机**当前实际生效**的采集参数(现场可用 GET/POST /param 实时读写, 不必重启)。
#   这里只记录真实下发成功的值, 供 /param 读回; 重启后回到上面三个常数。
_CAM_LIVE = {"exposure_us": float(EXPOSURE_US), "gain_db": float(GAIN_DB),
             "gamma_val": float(GAMMA_VAL), "sn": TARGET_SN, "model": CAM_DESC}

# ===== v3 保留: 最近一次照片 / 最近一次检测判决 =====
_LAST_PIC = {"origin": None, "topview": None, "t": 0.0}
_LAST_MODELIN = ""          # v10: 本轮送检的模型输入文件(960x960 同帧派生图, 在 %TEMP%, 检测完即删)
_LAST_SHADOW = ""           # v10: 本轮影子对照的临时图(判据图压 960x960; 空=不跑)
# 🆕 v11 (老倪: 「哪里是调用 YOLO 模型, 我看看实际输入给模型的图片, 和 YOLO 的返回值」):
#   把**喂给 detector.detect() 的同一份像素**留在内存 + 一个无损坏的 PNG 取图口, 供现场/自检核对:
#   GET /picture?kind=modelin  (= 模型实际吃的那张, 逐位相同; ?meta=1 给 md5/尺寸/来源)
_LAST_MODELIN_IMG = None
_LAST_MODELIN_META = {}
# 影子对照张数: 默认前 10 张(攒同口径对照数据), 之后自动停。设 AOI_AB_PAIRS=0 可完全关掉。
_AB_LEFT = int(os.environ.get("AOI_AB_PAIRS", "10"))
_AB_DONE = 0
TEMP_DIR = os.environ.get("TEMP") or os.environ.get("TMP") or "."


# ───────────────────── v5: 内存帧 + 按需落盘 + 保留上限 ─────────────────────
# ───────────────────── v6: 取图两路由补"重连再抓"(与 /capture_detect 同口径), 版本号统一 — 2026-09-27 ─────────────────────
# 老倪 2026-09-27: 「不检测的时候, 不用保存那么多图片」⇒
#   · 只"看一眼/取图"(GET /picture?grab=1) 一律**不落盘**, 图只留内存(编码后几百 KB);
#   · 只有真检测(POST /capture_detect, 模型要读文件)才落盘, 落完按上限清旧图;
#   · 诊断用的额外图(标注图/legacy)默认不写, 要写设 AOI_SAVE_DEBUG=1;
#   · GET /storage 看占用/张数, POST /prune 手动清。
AOI_SAVE_DEBUG = os.environ.get("AOI_SAVE_DEBUG", "0").strip().lower() in ("1", "true", "yes")
KEEP_CANON = int(os.environ.get("AOI_KEEP_CANON", "400"))
KEEP_ORIGIN = int(os.environ.get("AOI_KEEP_ORIGIN", "120"))
_PRUNE_PATTERNS = [("Finger_TopView_W*_H*_No_*.png", KEEP_CANON),   # v7: 这张现在是判据图口径
                   ("Finger_Image_W*_H*_No_*.png", KEEP_ORIGIN),
                   # v8: 老倪「Finger_ModelIn_…就不要了」⇒ keep=0, 自动清掉历史遗留文件(不再产出)
                   ("Finger_ModelIn_W*_H*_No_*.png", 0),
                   ("Finger_CropNatural_W*_No_*.png", KEEP_CANON),
                   ("Finger_CropAnno_No_*.png", KEEP_ORIGIN if AOI_SAVE_DEBUG else 0),
                   ("Legacy_TopView_No_*.png", KEEP_ORIGIN if AOI_SAVE_DEBUG else 0)]
_MEM = {"crop": None, "origin": None, "natural": None, "ts": 0.0}
_MEM_LOCK = threading.Lock()
_TL = threading.local()          # 每次抓帧的落盘开关(线程安全: /capture_detect 与 /picture?grab=1 可能并发)


def _enc_jpg(bgr, quality=90):
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else b""


def _mem_put(crop=None, origin=None, natural=None):
    """把当前这帧编码进内存 (取图走内存, 磁盘就不需要那么多文件)。"""
    with _MEM_LOCK:
        if crop is not None:
            _MEM["crop"] = _enc_jpg(crop, 92)
        if origin is not None:
            _MEM["origin"] = _enc_jpg(origin, 88)
        if natural is not None:
            _MEM["natural"] = _enc_jpg(natural, 92)
        _MEM["ts"] = time.time()


def _mem_get(kind, t0=0.0):
    """取内存帧: kind=origin/raw 要原图, 其余要规范图; 没有就退回另一张。"""
    with _MEM_LOCK:
        b = _MEM.get(kind) or _MEM.get("crop") or _MEM.get("origin")
        ts = _MEM.get("ts", 0.0)
    return b, ts


def _iw(path, img, *a, **kw):
    """落盘开关: 只有真检测(或 AOI_SAVE_DEBUG 下的诊断图)才写盘。"""
    save = getattr(_TL, "save", True)
    p = str(path)
    if save or (AOI_SAVE_DEBUG and ("Anno" in p or "Legacy" in p)):
        return cv2.imwrite(path, img, *a, **kw)
    return True


def _prune_dir(patterns=None):
    """按保留上限删最旧的图; patterns=[(glob, keep_n), ...] (keep_n=0 表示这类全清)。"""
    patterns = patterns if patterns is not None else _PRUNE_PATTERNS
    removed = 0
    for pat, keep in patterns:
        try:
            files = sorted(glob.glob(os.path.join(SAVE_ROOT_DIR, pat)), key=os.path.getmtime)
        except OSError:
            continue
        if keep >= 0 and len(files) > keep:
            for f in files[:len(files) - keep]:
                try:
                    os.remove(f)
                    removed += 1
                except OSError:
                    pass
    return removed


def _dir_stat():
    out = {"dir": os.path.abspath(SAVE_ROOT_DIR), "groups": {}}
    total = n_total = 0
    for pat, keep in _PRUNE_PATTERNS:
        files = glob.glob(os.path.join(SAVE_ROOT_DIR, pat))
        sz = 0
        for f in files:
            try:
                sz += os.path.getsize(f)
            except OSError:
                pass
        out["groups"][pat] = {"count": len(files), "mb": round(sz / 1048576.0, 1), "keep": keep}
        total += sz
        n_total += len(files)
    out["files_total"] = n_total
    out["mb_total"] = round(total / 1048576.0, 1)
    out["save_debug"] = AOI_SAVE_DEBUG
    return out
_LAST_RESULT = {}
_LAST_CROP_INFO = {}
_LAST_REGION = {}
_PIC_LOCK = threading.Lock()


def _region_payload(bgr, info):
    """金手指区域(原始图坐标系) + 对焦清晰度 —— 供状态空间 YOLO/伺服引导直接消费
    region: 定向框(中心/宽高/角度), 与模板法截取用的是同一份几何
    focus : 区域内 Laplacian 方差(对焦锐度指标, 越大越清晰), 以及该区域的灰度均值/对比度
    """
    bgr = np.asarray(bgr)
    s = (info or {}).get("strip") or {}
    if not s:
        return {"ts": time.time(), "ok": False, "reason": "无区域几何(裁剪失败)"}
    cx, cy, w, h, ang = float(s["cx"]), float(s["cy"]), float(s["w"]), float(s["h"]), float(s.get("angle", 0.0))
    R = cv2.getRotationMatrix2D((0, 0), ang, 1.0)
    pts = []
    for dx, dy in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
        pts.append([float(cx + R[0, 0] * dx + R[0, 1] * dy), float(cy + R[1, 0] * dx + R[1, 1] * dy)])
    x0 = max(0, int(min(p[0] for p in pts))); x1 = min(bgr.shape[1], int(max(p[0] for p in pts)))
    y0 = max(0, int(min(p[1] for p in pts))); y1 = min(bgr.shape[0], int(max(p[1] for p in pts)))
    roi = bgr[y0:y1, x0:x1]
    focus = sharp = None
    if roi.size:
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        focus = float(cv2.Laplacian(g, cv2.CV_64F).var())
        sharp = float(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3).__abs__().mean())
    return {"ts": time.time(), "ok": True, "image_size": [bgr.shape[1], bgr.shape[0]],
            "region": {"cx": round(cx, 2), "cy": round(cy, 2), "w": round(w, 2), "h": round(h, 2),
                       "angle": round(ang, 3), "quad": [[round(v, 1) for v in p] for p in pts],
                       "bbox": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]},
            "focus": None if focus is None else round(focus, 1),
            "sharp": None if sharp is None else round(sharp, 2),
            "score": (info or {}).get("score"), "angle": (info or {}).get("angle"),
            "quality": (info or {}).get("quality", {})}

# 【优化1】全局常驻: 相机设备缓存 + 打开状态
_dev_cache = None
_cam_open = False
_cam_lock = threading.Lock()

_CROPPER = None
_CROPPER_LOCK = threading.Lock()
_LAST_NATURAL = None       # 原比例版裁剪图 (1:1 像素)


def get_cropper():
    """惰性建裁剪器 (模板只读一次; 进程内复用, 角度热启动)"""
    global _CROPPER
    with _CROPPER_LOCK:
        if _CROPPER is None:
            if not os.path.exists(TEMPLATE_PNG):
                print(f"⚠️ 模板不存在: {TEMPLATE_PNG} → 只能用 legacy 几何")
                return None
            _CROPPER = GoldFingerCropper(
                TEMPLATE_PNG, canonical_w=CANONICAL_W, canonical_h=CANONICAL_H,
                margin_x=MARGIN_X, margin_y=MARGIN_Y, preserve_aspect=KEEP_ASPECT,
                min_score=MIN_SCORE)
            print(f"模板裁剪器就绪: {os.path.basename(TEMPLATE_PNG)} "
                  f"条={_CROPPER.meta['strip_w']:.0f}x{_CROPPER.meta['strip_h']:.0f} "
                  f"规范化={CANONICAL_W}x{'auto' if KEEP_ASPECT else CANONICAL_H}")
        return _CROPPER


def uint32_to_ipv4(ip_uint32):
    network_order_ip = socket.htonl(ip_uint32)
    packed_ip = struct.pack("!I", network_order_ip)
    return socket.inet_ntoa(packed_ip)


def _resolve_detect_type_by_channel() -> tuple:
    port = str(request.environ.get("SERVER_PORT", "")).strip()
    detect_type = PORT_TO_DETECT_TYPE.get(port)
    return detect_type, port


def find_dev_by_sn(target_sn: str, use_cache=True):
    """【优化4】设备枚举缓存: 找到后缓存, 不重复枚举"""
    global _dev_cache
    if use_cache and _dev_cache is not None:
        return _dev_cache
    devInfos = SCI_DEVICE_INFO_LIST()
    reVal = SciCamera.SciCam_DiscoveryDevices(
        devInfos, SciCamTLType.SciCam_TLType_Gige | SciCamTLType.SciCam_TLType_Usb3)
    if reVal != SCI_CAMERA_OK or devInfos.count == 0:
        print("枚举相机失败或无设备")
        return None
    for i in range(devInfos.count):
        cam_obj = devInfos.pDevInfo[i]
        if cam_obj.tlType != SciCamTLType.SciCam_TLType_Gige:
            continue
        gige_info = cam_obj.info.gigeInfo
        sn_buf = bytes(gige_info.serialNumber).strip(b"\x00")
        sn_str = sn_buf.decode("utf-8")
        if sn_str == target_sn:
            _dev_cache = cam_obj
            return cam_obj
    print(f"未找到序列号 {target_sn} 的相机")
    return None


def set_exposure(exposure_us: float):
    ret = m_Device.SciCam_SetFloatValue("ExposureTime", exposure_us)
    if ret != SCI_CAMERA_OK:
        print(f"【参数设置失败】曝光 {exposure_us}us，错误码:{ret}")
        return False
    print(f"曝光设置成功 {exposure_us}us")
    _CAM_LIVE["exposure_us"] = float(exposure_us)
    return True


def set_gain(gain_db: float):
    """【优化2】增益容错: 失败自动尝试替代值, 都不行降级跳过"""
    ret = m_Device.SciCam_SetFloatValue("Gain", gain_db)
    if ret == SCI_CAMERA_OK:
        print(f"增益设置成功 {gain_db}")
        _CAM_LIVE["gain_db"] = float(gain_db)
        return True
    for alt in [gain_db * 2, int(gain_db), 0.0, 2.0, 8.0]:
        if alt == gain_db:
            continue
        ret = m_Device.SciCam_SetFloatValue("Gain", alt)
        if ret == SCI_CAMERA_OK:
            print(f"增益设置成功(替代值) {alt} (原{gain_db}失败码{ret})")
            _CAM_LIVE["gain_db"] = float(alt)
            return True
    print(f"【参数设置失败】增益 {gain_db}，错误码:{ret}，跳过(不影响采集)")
    return False


def set_gamma(gamma_val: float):
    ret = m_Device.SciCam_SetFloatValue("Gamma", gamma_val)
    if ret != SCI_CAMERA_OK:
        print(f"【参数设置失败】Gamma {gamma_val}，错误码:{ret}")
        return False
    print(f"Gamma设置成功 {gamma_val}")
    _CAM_LIVE["gamma_val"] = float(gamma_val)
    return True


def set_auto_off():
    """★ 关掉相机自带的自动曝光/自动增益 —— 这是 2026-10-08 挖出来的**真根因**:

    这台 OPT-CC1-GG50 出厂把 ExposureAuto / GainAuto 开着, 此时对 ExposureTime / Gain 的任何
    写入都会被判"参数值非法"(rv=100100010) 而**静默失败**。相机于是自己在亮金属上长期拉超长曝光
    (实测约 94ms)硬扛 → 恒定过曝、暗缝被糊白糊连、画面发糊、金手指根数不稳。
    先关自动(枚举接口)再写, 实测 rv=0 写入成功。
    """
    for node in ("ExposureAuto", "GainAuto"):
        try:
            ret = m_Device.SciCam_SetEnumValueByString(node, "Off")
            if ret != SCI_CAMERA_OK:
                ret2 = m_Device.SciCam_SetEnumValue(node, 0)     # 0 = Off
                print(f"{node} 关自动: 字符串方式码 {ret}, 枚举方式码 {ret2}")
            else:
                print(f"{node} 关自动成功")
        except Exception as e:
            print(f"{node} 关自动异常: {e!r}")


def Open_Device(target_dev):
    global _cam_open
    reVal = m_Device.SciCam_CreateDevice(target_dev)
    if reVal != SCI_CAMERA_OK:
        print("创建设备句柄失败，错误码：", reVal)
        return False
    reVal = m_Device.SciCam_OpenDevice()
    if reVal != SCI_CAMERA_OK:
        print("打开相机失败，错误码：", reVal)
        return False
    m_Device.SciCam_SetGrabStrategy(2)
    set_auto_off()          # ★ 必须最先: 不关自动曝光/自动增益, 下面三行是"静默失败"
    set_exposure(EXPOSURE_US)
    set_gain(GAIN_DB)
    set_gamma(GAMMA_VAL)
    _cam_open = True
    print("相机打开成功")
    return True


def StartGrabbing():
    ret = m_Device.SciCam_StartGrabbing()
    if ret != SCI_CAMERA_OK:
        print("开启采集失败")
        return False
    print("采集流已启动")
    return True


def StopGrabbing():
    m_Device.SciCam_StopGrabbing()
    print("采集流已停止")


def Close_Device():
    global _cam_open
    try:
        m_Device.SciCam_CloseDevice()
        m_Device.SciCam_DeleteDevice()
    except Exception:
        pass
    _cam_open = False
    print("相机已关闭释放")


def ensure_camera():
    """【优化1】相机常驻: 已打开直接返回True, 未打开才初始化"""
    global _cam_open
    with _cam_lock:
        if _cam_open:
            return True
        target_dev = find_dev_by_sn(TARGET_SN)
        if target_dev is None:
            return False
        if not Open_Device(target_dev):
            return False
        if not StartGrabbing():
            StopGrabbing()
            Close_Device()
            return False
        time.sleep(0.8)
        return True


# ===== v3 保留: 旧的固定窗 warp (legacy 模式 / 对照用) =====
def warp_goldfinger_topview(pDstData, img_w, img_h, out_w=None, out_h=None):
    if out_w is None:
        out_w = img_w
    if out_h is None:
        out_h = img_h
    img_mat = np.frombuffer(pDstData, dtype=np.uint8).reshape(img_h, img_w, 3)
    src_points = np.array([[400, 1000], [2000, 1000], [2000, 1250], [400, 1250]], dtype=np.float32)
    dst_points = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    trans_matrix = cv2.getPerspectiveTransform(src_points, dst_points)
    return cv2.warpPerspective(img_mat, trans_matrix, (out_w, out_h))


# ============ v21: judge picture = a row of EQUAL-WIDTH piano keys on pure black ============
# v21 change (2026-10-08; shop floor: "the gold fingers, why are the widths different?
#   some wide, some thin.  Real gold fingers are very uniform in width"):
#   The old recipe drew every key at the width IT was detected with -> uneven widths; it
#   also counted the ~70 px metal block on the left as one very wide "key"; its mask took
#   bright pixels per pixel -> the dim core of a key went black (the key broke in two);
#   and it removed the full-width bright rows with keyrows & ~bar, i.e. it punched a hole
#   in the MIDDLE of the key band -> the row of keys was cut into an upper and lower half.
#   v21 recipe (all of it inlined in THIS file; no import of any other machine's module):
#     (1) EQUAL widths: one key width = the MEDIAN detected width; every key is centred on
#         its OWN detected centre -> every key in the delivered picture has the same width.
#     (2) mask = the SOLID RECTANGLE of each key (key-row range x key-column range), not a
#         per-pixel brightness test.  The whole key block is kept, dark parts included.
#     (3) the horizontal bar never punches a hole: find the CONTINUOUS run of full-width
#         bright rows (bright fraction >= 0.85) and TRUNCATE the key band at its START
#         (keep only the rows before the bar); the bar rows are excluded as a block.
#     (4) drop the odd block: width off the median by > 60% OR spacing to the neighbouring
#         keys off the median pitch by > 60%; BUT if that would leave fewer than 8 keys the
#         drop is SKIPPED and the meta says so (outlier_skipped).
#   Everything else is pure black (0,0,0).  Fixed size stays **900x332** (the content is
#   scaled to width 900 with its NATURAL aspect ratio and centred vertically on black; it is
#   never stretched to fill); exposure is compressed with a linear gain.
#   On failure -> (None, meta with why/err) and the caller falls back to the regular crop;
#   a wrong judge picture is never handed out.
#   Everything ADDED/CHANGED in v21 is pure ASCII (the shop-floor Windows hosts choke on
#   non-ASCII sources).
_JUDGE_HW = (900, 332)           # judge picture fixed size (= the /last_result contract)
_SAT_LEVEL = 250                 # grey level that counts as a saturated pixel
_JR_K = 1.0                      # v21 does not stretch the short side (signature compat)

# --- v21 parameters (every one of them is reported in the returned meta) ---
_V21_WIN_H = 50                  # key-row search window height (px)
_V21_WIN_STEP = 10               # ... and step
_V21_CF_BRIGHT_COL = 0.45        # a column is bright inside a window at this fraction
_V21_COL_MERGE_GAP = 3           # merge bright columns closer than this (px)
_V21_MIN_SEG_W = 4               # drop bright groups narrower than this (px)
_V21_MIN_KEYS = 6                # a key row window needs at least this many groups
_V21_PITCH_MIN = 25.0            # ... with a median pitch in this range
_V21_PITCH_MAX = 140.0
_V21_PITCH_JITTER_K = 0.25       # ... and a jitter below this fraction of the pitch
_V21_EDGE_CUT = 2.5              # horizontal edge strength of the strip columns
_V21_EDGE_BAND_H = 40            # rows used for the column profile
_V21_CUT_RUN = 20                # a cut segment must last this many columns
_V21_BORDER_IGNORE = 6           # ignore this many frame-edge columns
_V21_COL_PAD = 4                 # keep a few px past the detected end
_V21_MIN_KEEP_W = 120            # refuse if fewer columns survive
_V21_VCLOSE_K = 31               # vertical close kernel: bridges a dark notch inside a key
_V21_CF_KEY_COL = 0.50           # a column is a key at this closed-mask fraction
_V21_KEY_MERGE_GAP = 6           # merge key columns closer than this (px)
_V21_MIN_KEY_W = 8               # drop key groups narrower than this (px)
_V21_COL_LEVEL_FRAC = 0.85       # the column profile runs a bit lower than the row level,
                                 # so a dimmer key still shows up
_V21_MERGE_SPLIT_FRAC = 0.70     # two groups closer than this * pitch are ONE key
_V21_OUTLIER_W = 0.60            # width deviation from the median that means "outlier"
_V21_OUTLIER_P = 0.60            # pitch deviation from the median that means "outlier"
_V21_MIN_KEYS_KEEP = 8           # never drop below this many keys
_V21_BAR_BRIGHT = 0.85           # inside the band: this bright fraction -> the solid bar
_V21_CROP_PAD = 20               # margin around the kept content (px)
_V21_AUTO_PEAK = 205.0           # auto gain puts the brightest kept pixel here
_V21_BRIGHT_LEVEL = 200.0        # upper clamp of the adaptive brightness level
_V21_BRIGHT_MIN = 60.0           # lower clamp
_V21_BRIGHT_FRAC = 0.72          # a pixel is "bright" above this much of the local p96


# --- v22 (2026-10-08 晚, 老倪「右侧有方块区域, 不是金手指」) --------------------------
#   v21 在役, 但**每 ~20 帧有 1 帧**判据渲染失败(键列塌成 1 根, 需 >=3) ⇒ 老代码把
#   topview 静默回退成 **旧的 960x960 拉伸图**(右侧灰块没切) = 现场看到的"方块区域"。
#   v22 三件事: ① 失败时**保留上一张好判据图 + 红条标注**(绝不端旧口径);
#              ② 失败时**逐窗 + 放宽门限**重试(正常帧仍走第 1 遍, 像素与 v21 逐位一致);
#              ③ 失败时把**输入帧 + 完整 meta** 覆盖式落两个固定文件(有界取证)。
# 🆕 v25 (老倪 2026-10-08 「改, 验证, 部署」): 判据几何对**画面亮度免疫**。
#   实测病灶: 判据图的根数在 19/18/16 之间跳, 而同一帧姿态一帧没变(区域横向偏移 0.5px)。
#   离线复放(_v24 逐帧)证明: 同一帧仅做 λ∈[0.75,1.18] 的亮度缩放, 根数就 19/21/16/16/19/19 ——
#   因为判据几何里混着**绝对阈值**(裁剪 _V21_EDGE_CUT=2.5, 亮列门限 = frac×lvl), 画面一亮一暗
#   这些阈值就相对变松/变紧 ⇒ 左端那块 ~78px 金属边块在"单键窗/拒收窗/双键窗"之间漂 ⇒ 认领跨度漂。
#   修法: 几何分析(键行窗/裁剪/亮列/键掩膜)**统一走逐帧对比度归一化副本 ga**, 阈值由此变成相对量;
#   渲染像素仍取原图 src(1111 行 block=src[...]) ⇒ 判据图观感不变; sat_before/曝光增益仍用原图 g。
_JUDGE_VER = "v25-gold-judge-20261008"
_V22_GATES = (                       # 第 1 组 = v21 原口径(保证成功帧像素不变)
    {},
    {"col_level_frac": 0.80, "cf_key_col": 0.40, "min_key_w": 4},
    {"col_level_frac": 0.72, "cf_key_col": 0.32, "min_key_w": 3},
)
_V22_ACCEPT = {"max_sat_before": 0.55, "min_keys": 5, "min_black_frac": 0.45}
# 🆕 v23 (2026-10-08 老倪「金手指细条小片之间的间隙, 也不用全黑, 暗一些即可, 也要保留原来的底色,
#   要不然感觉很怪」): 键**之间/周围**的像素不再一律压成纯黑(0), 改成**保留原像素 × 这个系数**
#   (0 = 纯黑= v21 老口径; 1 = 原样; 0.38 = 暗一些但看得出底色)。键本身不受影响(照旧原像素+增益)。
_V23_GAP_DIM = 0.38
# 🆕 v23 (2026-10-08 老倪「金手指的高度, 可以再搞一些, 变成原来的 1.2 倍吧」):
#   判据图里**键的高度**放大到 1.2 倍(宽度不变) —— 只在宽度受限时生效(本就按宽度定尺),
#   实现 = 纵向按 sc*1.2 重采样(纯显示放大, 不改检测/不改键宽/不改口径参数)。
_V23_KEY_HSTRETCH = 1.2
_V22_DBG_PNG = "debug_judge_fail_last.png"
_V22_DBG_JSON = "debug_judge_fail_last.json"
# 🔴 2026-10-08 现场(老倪: 「判据图怎么总变呢? 不稳定」): 原先是一张**全局**好图 —— 切到点2 后判据屡屡失败,
#   `_v22_judge_fail_view` 就把**前视(点1)的那张好图**端出来顶着 ⇒ 画面在"当前帧"和"别的视角的旧图"之间来回切。
#   修: 按**视角签名**(裁剪块形状的粗桶)隔离 ⇒ 同视角才许顶着用; 没有就退回 960 并如实标注。
_LAST_GOOD_JUDGE = {}            # {视角签名: {"img":..., "ts":..., "no":...}}
_V22_GOOD_KEEP = 4               # 最多保留几个视角的好图


def _v22_view_key_from_crop(crop):
    """视角签名 = 裁剪块形状的粗桶(宽 64px / 高 16px 一档)。

    为什么用裁剪块形状: **判据失败的路径也能算**(失败路径手里只有 crop) ⇒ 成功/失败两侧的签名可比,
    且前视(条带 ~1455x70)与点2(裁剪 ~1153x100)天然不同桶 ⇒ 一个视角的失败绝不会端出另一个视角的图。
    """
    try:
        h, w = crop.shape[:2]
        return (int(round(float(w) / 64.0)), int(round(float(h) / 16.0)))
    except Exception:                                                               # noqa: BLE001
        return (0, 0)


def _v22_band_candidates(hits, h):
    """候选键行带: 第 0 条 = v21 原口径(所有命中窗 min~max 合并); 其后 = 单个命中窗(命中段多的优先)。"""
    if not hits:
        return []
    out = [(int(min(z["y0"] for z in hits)), int(max(z["y1"] for z in hits)))]
    for z in sorted(hits, key=lambda q: (-int(q.get("n_seg") or 0), float(q.get("jitter_px") or 0.0))):
        c = (int(z["y0"]), int(z["y1"]))
        if c not in out and 0 <= c[0] <= c[1] < int(h):
            out.append(c)
    return out


def _v22_remember_good(img, no, key):
    """记下**本视角**最后一张成功判据图(同视角失败时用它顶着, 并标出帧龄)。"""
    try:
        _LAST_GOOD_JUDGE[key] = {"img": np.ascontiguousarray(img).copy(),
                                 "ts": time.time(), "no": no}
        if len(_LAST_GOOD_JUDGE) > _V22_GOOD_KEEP:      # 只留最近几个视角
            for _k in list(_LAST_GOOD_JUDGE)[:len(_LAST_GOOD_JUDGE) - _V22_GOOD_KEEP]:
                _LAST_GOOD_JUDGE.pop(_k, None)
    except Exception:
        pass


def _v22_judge_fail_view(crop, jmeta, no, key):
    """失败时**绝不端错图**: **同视角**有上一张好判据图就用它 + 红条 + 帧龄; 没有才退回 960 并如实标注。

    🔴 2026-10-08: 按视角隔离 —— 宁可退回 960(如实标注)也**绝不**端出别的视角的图(那正是"判据图总变")。
    """
    why = str(jmeta.get("err") or jmeta.get("why") or "judge render failed")[:90]
    _g = _LAST_GOOD_JUDGE.get(key) or {}
    base = _g.get("img")
    if base is not None and getattr(base, "size", 0):
        state = "stale_lastgood"
        img = base.copy()
        age = max(0.0, time.time() - float(_g.get("ts") or 0.0))
        note = "JUDGE FAIL - LAST GOOD (%.1fs old, frame %s)" % (age, _g.get("no"))
    else:
        state = "fallback_960"
        img = np.ascontiguousarray(crop).copy()
        note = "JUDGE FAIL - 960x960 FALLBACK (NO GOOD FRAME YET FOR THIS VIEW)"
    try:
        h, w = img.shape[:2]
        bar = max(24, h // 12)
        img[0:bar, :] = (0, 0, 200)
        cv2.putText(img, note[:64], (6, int(bar * 0.70)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.42, bar / 40.0), (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, ("REASON: " + why)[:80], (6, min(h - 6, bar + int(bar * 0.85))),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.34, bar / 52.0), (0, 0, 255), 1, cv2.LINE_AA)
    except Exception:
        pass
    return img, state


def _v22_dump_fail(bgr, jmeta, no):
    """有界取证: 失败时把输入帧 + 完整 meta(含命中的键行窗) 覆盖式落两个固定文件, 永不增长。"""
    try:
        cv2.imwrite(os.path.join(SAVE_ROOT_DIR, _V22_DBG_PNG), np.ascontiguousarray(bgr))
        rec = {"ts": time.time(), "t_local": time.strftime("%F %T"), "frame_no": no,
               "ver": _JUDGE_VER, "why": jmeta.get("why"), "err": jmeta.get("err"),
               "hits": (jmeta or {}).get("_hits"),
               "meta": {k: v for k, v in (jmeta or {}).items() if not k.startswith("_")}}
        with open(os.path.join(SAVE_ROOT_DIR, _V22_DBG_JSON), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1, default=str)
        return True
    except Exception as e:                                               # noqa: BLE001
        print("  ⚠️ 失败取证落盘失败: %s" % e)
        return False


def _v21_luma(bgr):
    """BT.601 luma as float32 (BGR in, matches the shop-floor gray() helper)."""
    b = bgr.astype(np.float32)
    return 0.114 * b[:, :, 0] + 0.587 * b[:, :, 1] + 0.299 * b[:, :, 2]


def _v21_segments(on, merge_gap, min_w):
    """Group the True runs of a boolean array; merge runs closer than merge_gap."""
    idx = np.where(np.asarray(on, bool))[0]
    if idx.size == 0:
        return []
    segs = [[int(idx[0]), int(idx[0])]]
    for v in idx[1:]:
        if int(v) - segs[-1][1] <= int(merge_gap) + 1:
            segs[-1][1] = int(v)
        else:
            segs.append([int(v), int(v)])
    return [(a, b) for a, b in segs if (b - a + 1) >= int(min_w)]


def _v21_pitch_stats(segs):
    """Median pitch and its median absolute deviation, from the segment centres."""
    if len(segs) < 2:
        return None, None
    c = np.array([(a + b) / 2.0 for a, b in segs], np.float32)
    d = np.diff(c)
    med = float(np.median(d))
    return med, float(np.median(np.abs(d - med)))


def _v21_robust_line(xs, ys, iters=3):
    """Least squares fit with a couple of hard-outlier rejections."""
    if len(xs) < 8:
        return None
    xs = np.asarray(xs, np.float64)
    ys = np.asarray(ys, np.float64)
    keep = np.ones(xs.size, bool)
    for _ in range(iters):
        if keep.sum() < 8:
            return None
        k, c = np.polyfit(xs[keep], ys[keep], 1)
        r = np.abs(ys - (k * xs + c))
        thr = max(2.0, 2.5 * float(np.median(r[keep])))
        new = r <= thr
        if new.sum() < 8 or np.array_equal(new, keep):
            break
        keep = new
    k, c = np.polyfit(xs[keep], ys[keep], 1)
    return float(k), float(np.abs(ys[keep] - (k * xs[keep] + c)).max()), int(keep.sum())


def _v21_pivot_slope(xs, ys):
    """Robust slope: median of (y - y_med) / (x - x_med).  A handful of odd columns
    (a short or dim key) cannot drag it the way a least-squares fit would."""
    if len(xs) < 8:
        return None
    x = np.asarray(xs, np.float64)
    y = np.asarray(ys, np.float64)
    px = float(np.median(x))
    py = float(np.median(y))
    d = x - px
    ok = np.abs(d) >= 4.0
    if ok.sum() < 8:
        return None
    return float(np.median((y[ok] - py) / d[ok]))


def _v21_smooth1d(a, k=7):
    a = np.asarray(a, np.float32)
    n = a.size
    if n <= k:
        return a.copy()
    out = np.empty(n, np.float32)
    half = k // 2
    for i in range(n):
        out[i] = np.median(a[max(0, i - half):min(n, i + half + 1)])
    return out


def _v21_adaptive_bright(win):
    """Brightness level that means "lit metal" for THIS window (darker archives)."""
    return float(np.clip(_V21_BRIGHT_FRAC * float(np.percentile(win, 96)),
                         _V21_BRIGHT_MIN, _V21_BRIGHT_LEVEL))


def _v21_key_windows(g, lvl):
    """Slide a window down the frame and keep the ones that look like a ROW OF KEYS.

    A full-width horizontal bar is ONE bright group, so it can never pass the
    '>= MIN_KEYS groups at a regular pitch' test -- that is what finds the keys and
    not the bar."""
    h, w = g.shape
    mrows = g.mean(axis=1)
    bg = float(np.percentile(mrows, 20))
    gate = min(bg + 25.0, 1.35 * bg)
    hits = []
    y = 0
    while y + _V21_WIN_H <= h:
        if float(mrows[y:y + _V21_WIN_H].mean()) >= gate:
            cf = (g[y:y + _V21_WIN_H, :] >= lvl).mean(axis=0)
            segs = _v21_segments(cf >= _V21_CF_BRIGHT_COL, _V21_COL_MERGE_GAP, _V21_MIN_SEG_W)
            med, mad = _v21_pitch_stats(segs)
            if (len(segs) >= _V21_MIN_KEYS and med is not None
                    and _V21_PITCH_MIN <= med <= _V21_PITCH_MAX
                    and mad < _V21_PITCH_JITTER_K * med):
                hits.append({"y0": int(y), "y1": int(y + _V21_WIN_H - 1),
                             "n_seg": int(len(segs)), "pitch_px": round(med, 1),
                             "jitter_px": round(mad, 1)})
        y += _V21_WIN_STEP
    return hits


# 现场正常状态(判据 19 根)实测: 中位灰度 63/255 —— 选它当"工作点", 因为它**随光照精确等比**
# (实测同一帧 ×0.75~×1.18 时 p50 = 47.2/53.6/58.0/63.0/68.0/74.3, 正好等于 63×λ);
# 而 p90/p97/p99 在正常状态就已饱和(255) ⇒ 亮区无法当参照。
_V25_REF_P50 = 63.0
_V25_GAIN_LIM = (0.70, 1.50)     # 增益夹紧: 只修现场实测那点光照漂移(±25% 量级), 不重映射陌生场景
_V25_GAIN_DEAD = 0.03            # 死区: 正常状态增益=1 ⇒ 与 v24 逐位一致(观感零变化)

# 🆕 v25b (2026-10-08 现场实测第二层病灶): 端部认领是"一刀切", 对帧间 ±1px 噪声敏感 ——
#   左端那块 ~78px 金属边块的宽度在"单键窗(<=1.60×中键宽)"与"拒收窗(<1.35×节距)"之间摇摆,
#   于是同一姿态下根数在 16(少认 3 格)/19/22(多认 2 格)之间跳(8 张真帧实测: 裁剪端点恒 497、
#   姿态恒定 p50 恒 63, 只有这一刀在跳)。
#   物理事实: **同一个工件的金手指阵列是静止的** ⇒ 端部不该由单帧一刀决定, 改用**短窗逐格投票**:
#   最近 _V25_VOTE_WIN 帧里被认领 >= _V25_VOTE_MIN 次的格子才认领。
#   实测(50% 概率漏认领的 3 格 → 得票 3~4/7 ⇒ 补回; 8% 概率过认领的 2 格 → 得票 0~1/7 ⇒ 否掉)。
_V25_VOTE_WIN = 7                # 投票窗(帧)
_V25_VOTE_MIN = 2                # 得票门槛: 窗口内至少这么多帧认领过这一格
# 🔴 2026-10-08 第3轮修正: 投票窗**必须按视角分桶** —— 原先是模块级一个列表, 而格子索引 (_i) 是
#   以**本视角自己的相位 phase** 为基准的 ⇒ 前视(front)与点2(背面)的 _i 完全不是一回事, 混在同一窗里
#   必然互相污染: 同一帧给 16 还是 19, 取决于"之前看过哪个视角"。现场点1/点2 切换 ⇒ 判据数必然跳。
#   分桶键 = (节距桶, 行带桶): 同一视角内恒定(⇒ 同视角逐位不变), 跨视角不同(⇒ 不再互相污染)。
_V25_SEEN = {}                   # {视角签名: [最近各帧的认领格集合]}
_V25_SEEN_LOCK = threading.Lock()
_V25_SEEN_KEEP = 4               # 最多保留几个视角桶(防无限增长)


def _v25_view_key(med_gap):
    """视角签名 = 节距桶(8px)。

    为什么用节距: 前视节距 ~47(桶3), 点2 节距 72~74(桶5) ⇒ 同视角恒定、跨视角必不同。
    ⚠️ 桶宽必须**大于节距的帧间抖动**: 初版取 8px, 而前视热身期节距会抖到 47~52 ⇒ 跨桶 ⇒ 投票被拆成两窗,
    预热形态与 v25 不同(实测头 3 帧像素差 49%, 第 4 帧起才全等) ⇒ 改成 16px 一档。
    取不到就退化成单桶(0) ⇒ 行为等同旧版, 安全。
    """
    try:
        # 🔴 2026-10-08 第3轮实测: **分桶键同样不可用** —— 点2 节距 72.0~73.2, 除以 16 后落在 4.5 的取整边界,
        #   相邻帧分别落进桶 4 / 桶 5 ⇒ 投票窗被拆散 ⇒ 点2 序列从"稳定16"变成 19/11/16 乱跳(实测)。
        #   任何"按标量分桶"的键都有边界风险 ⇒ 暂退化成单桶(= 与 v25 逐位一致), 等有**稳定信号**
        #   (如裁剪块形状/外部视角标识)再接。**宁可不隔离, 也不许制造新抖动。**
        return 0
    except Exception:                                                               # noqa: BLE001
        return 0


def _v25_norm_luma(g):
    """逐帧对比度归一化(仅供几何分析): 2%/99% 分位拉到 0~255。

    目的不是"看得更清", 而是让下游那些**写死的绝对阈值**(裁剪边缘门 2.5、亮度下限、
    亮列门限)变成相对量 —— 现场画面亮度在几个档之间漂时, 判据几何(尤其两端认领跨度)不再跟着漂。
    渲染不走这条路: 出图仍用原像素, 观感与 v24 一致。
    """
    a = g.astype(np.float32)
    p50 = float(np.median(a))
    if p50 < 8.0:                    # 全黑/极暗帧(工件不在位等): 不动它, 宁可不修也不制造
        return g.copy()
    gain = float(np.clip(_V25_REF_P50 / p50, _V25_GAIN_LIM[0], _V25_GAIN_LIM[1]))
    if abs(gain - 1.0) < _V25_GAIN_DEAD:
        return g.copy()              # 正常状态: 逐位等同 v24(出图/几何都不变)
    return np.clip(a * gain, 0, 255).astype(np.uint8)


def _v21_strip_cols(g, ky0, ky1):
    """Left/right end of the metal body, from the horizontal edge strength |dI/dy|.

    The flat grey block on the right carries almost no edge strength, so it is cut."""
    h, w = g.shape
    y0 = max(0, int(ky0))
    y1 = min(h, int(ky1) + 1)
    mid = (y0 + y1) // 2
    b0 = max(0, mid - _V21_EDGE_BAND_H // 2)
    b1 = min(h, b0 + _V21_EDGE_BAND_H)
    gb = g[b0:b1, :]
    e = np.zeros(gb.shape[1], np.float32)
    if gb.shape[0] >= 2:
        e[:] = np.abs(np.diff(gb, axis=0)).mean(axis=0)
    e = _v21_smooth1d(e, 7)
    e[:_V21_BORDER_IGNORE] = 0.0
    e[w - _V21_BORDER_IGNORE:] = 0.0
    hi = np.where(e >= _V21_EDGE_CUT)[0]
    right = None
    rsrc = ""
    if hi.size:
        xr = int(hi.max())
        tail = e[xr + 1:]
        if len(tail) >= _V21_CUT_RUN and tail.mean() < _V21_EDGE_CUT:
            right = xr
            rsrc = ("last column with |dI/dy| >= %.1f is x=%d; the %d columns beyond "
                    "carry edge %.2f -> grey block cut"
                    % (_V21_EDGE_CUT, xr, len(tail), float(tail.mean())))
        else:
            rsrc = ("trailing segment too short (%d columns) -> right end kept at x=%d"
                    % (len(tail), xr))
    else:
        rsrc = "no column reaches the edge gate %.1f" % _V21_EDGE_CUT
    left = 0
    lsrc = ""
    if hi.size:
        xl = int(hi.min())
        head = e[:xl]
        if len(head) >= _V21_CUT_RUN and head.mean() < _V21_EDGE_CUT:
            left = xl
            lsrc = ("leading %d columns: edge %.2f (< %.1f) -> background cut at x=%d"
                    % (len(head), float(head.mean()), _V21_EDGE_CUT, xl))
        else:
            lsrc = "left end kept (leading gate not met)"
    return left, right, rsrc, lsrc, (b0, b1)


def _v21_key_cols(g, rows, x0, x1, lvl, cf_key_col=None, min_key_w=None):
    """Averaged bright-column profile over the band -> the key column segments.

    The mask is closed VERTICALLY first: a key whose middle is a dark notch shows up
    as two bright groups otherwise and would be counted twice.
    v22: cf_key_col/min_key_w 可覆盖(None = 用 v21 常量, 保证正常帧逐位不变)。"""
    m = (g[rows, x0:x1] >= lvl).astype(np.uint8)
    ker = np.ones((max(3, _V21_VCLOSE_K), 1), np.uint8)
    cl = cv2.morphologyEx(m, cv2.MORPH_CLOSE, ker)
    cf = cl.mean(axis=0)
    _cfk = _V21_CF_KEY_COL if cf_key_col is None else float(cf_key_col)
    _mkw = _V21_MIN_KEY_W if min_key_w is None else int(min_key_w)
    segs = _v21_segments(cf >= _cfk, _V21_KEY_MERGE_GAP, _mkw)
    segs = [(a + x0, b + x0) for a, b in segs]
    return segs, cf, cl


# ═══ v26: 格点补齐 (2026-10-08 点2 实测; 老倪"金手指判据图总变"的根修) ═══
#   病: 判据的列掩膜只到 x1607, 而齿排延续到 x≈1922 —— 右段 3~4 根的"黑帽+耳"被高光吃掉, 过不了特征门,
#   于是**从没进入计算**; 内部还有 w=188(2.6×节距) 的粘连块被判 too_wide **整块丢弃** ⇒ 判据自报 16,
#   而目检(3 帧一致)+几何+前视同源 三路都给出真值 **19**。
#   修: 用已认到的槽中心拟合节距/相位 ⇒ ① 内部缺口按栅格补回 ② 两端按"槽亮度+局部对比度"延伸(不是靠黑帽特征)。
#   铁律: 前视必须**逐位不变** —— 前视的齿列两端是暗背景/平坦填充(无局部对比度) ⇒ 判据天然不触发。
_V26_ON = False
# 🔴 2026-10-08 第3轮实测结论: 补格**暂关** —— 前视预热期(投票未治愈, rects 只 16)时它也会触发(16->17),
#   连带改掉 tilt_deg(2.048->0.0) ⇒ 前视头 3 帧像素差 49%(第 4 帧起才全等)。相关阈值 0.65 挡不住前视边缘周期结构。
#   要在点2 真正可用, 必须先做**列剖面低频背景归一(平场)**再判形状(见 docs/AOI-PT2-ROUND3-STATUS);
#   在那之前开启 = 凭空造齿, 比漏数更危险。代码保留, 开关置 False。
_V26_EXT_FRAC = 0.65      # 槽内亮度 >= 这个倍数 × 中位槽亮度, 才认这一格
_V26_CTR_FRAC = 0.35      # 槽内局部对比度 >= 这个倍数 × 中位槽对比度, 才认这一格
_V26_MAX_ADD = 6          # 单侧最多延伸几格(防失控)
_V26_CORR_MIN = 0.65      # 候选槽剖面与已认齿均值的相关下限(第3轮: 0.55 会收下"壳体倒角高光弧"=假齿, 实测 0.596)
_V26_TPL_N = 64           # 模板/候选剖面统一重采样长度(否则长短不一, np.dot 直接抛 shapes not aligned)


def _v26_fill_lattice(rects, ga, x0, x1, y0, y1):
    """在"节距栅格"上补齐缺失槽。返回 (rects, info)。"""
    info = {"v26_on": bool(_V26_ON)}
    if not _V26_ON or not rects or len(rects) < 4:
        return rects, info
    cs = sorted(((a + b) / 2.0, float(b - a + 1)) for a, b in rects)
    cen = [c for c, _ in cs]
    wid = float(np.median([w for _, w in cs])) or 26.0
    dd = np.diff(cen)
    dd = dd[dd > 0]
    if dd.size < 3:
        return rects, info
    pitch = float(np.median(dd[dd <= 1.6 * np.median(dd)])) if (dd <= 1.6 * np.median(dd)).size >= 3 else float(np.median(dd))
    if pitch <= 0:
        return rects, info
    prof = ga[int(y0):int(y1) + 1, :].astype(np.float32).mean(axis=0)
    half = pitch * 0.30

    def lvl(c):
        a = max(0, int(round(c - half)))
        b = min(len(prof), int(round(c + half + 1)))
        return float(prof[a:b].mean()) if b > a else None

    def ctr(c):
        a = max(0, int(round(c - pitch * 0.5)))
        b = min(len(prof), int(round(c + pitch * 0.5 + 1)))
        if b - a < 3:
            return 0.0
        seg = prof[a:b]
        return float(seg.max() - np.percentile(seg, 10))

    ref_l = float(np.median([lvl(c) for c in cen if lvl(c) is not None]))
    ref_c = float(np.median([ctr(c) for c in cen]))
    if ref_l <= 0:
        return rects, info

    # ── 第2轮修正: 判据改用"与已认齿平均剖面的**相关性**" ──────────────────────
    #   第1轮用"槽亮度≥0.65×中位" ⇒ 过曝白区(240~255, 又亮又平)天然通过 ⇒ 一路延伸过头(前视 16→22 ✗)。
    #   齿的特征是**形状**(峰-谷周期), 白区是平坦的 ⇒ 相关性天然低。
    def shape(c):
        a = int(round(c - pitch * 0.5))
        b = int(round(c + pitch * 0.5))
        if a < 0 or b > len(prof) or b - a < 6:
            return None
        v = prof[a:b].astype(np.float32)
        if v.size != _V26_TPL_N:      # 端部槽会被画面/裁切截短 ⇒ 统一重采样, 否则 dot 形状不对
            v = np.interp(np.linspace(0, v.size - 1, _V26_TPL_N),
                          np.arange(v.size), v).astype(np.float32)
        v = v - float(v.mean())
        n = float(np.linalg.norm(v))
        return (v, n) if n > 1e-6 else None

    _refs = [s for s in (shape(c) for c in cen) if s is not None]
    if not _refs:
        return rects, info
    _tmpl = np.mean([v / n for v, n in _refs], axis=0)
    _tn = float(np.linalg.norm(_tmpl))
    _tmpl = _tmpl / _tn if _tn > 1e-6 else _tmpl

    def corr(c):
        s = shape(c)
        if s is None:
            return -1.0
        v, n = s
        return float(np.dot(_tmpl, v) / n)

    def ok(c):
        if not (0 <= c < ga.shape[1]):
            return False
        l = lvl(c)
        return l is not None and l >= _V26_EXT_FRAC * ref_l and corr(c) >= _V26_CORR_MIN

    newc = list(cen)
    ph = cen[0] % pitch
    k0 = int(np.floor((cen[0] - ph) / pitch))
    k1 = int(np.round((cen[-1] - ph) / pitch))
    for k in range(k0, k1 + 1):
        c = ph + k * pitch
        if all(abs(c - x) > 0.45 * pitch for x in newc) and ok(c):
            newc.append(c)
    added_in = len(newc) - len(cen)
    added_out = 0
    for sgn in (+1, -1):
        step = 0
        c = (max(newc) if sgn > 0 else min(newc)) + sgn * pitch
        while step < _V26_MAX_ADD and ok(c):
            newc.append(c)
            added_out += 1
            step += 1
            c += sgn * pitch
    newc = sorted({round(c, 1) for c in newc})
    info.update({"v26_pitch": round(pitch, 1), "v26_ref_lvl": round(ref_l, 1), "v26_ref_ctr": round(ref_c, 1),
                 "v26_added_in": int(added_in), "v26_added_out": int(added_out), "v26_n": len(newc)})
    if len(newc) == len(cen):
        return rects, info
    out = [(int(round(c - wid / 2.0)), int(round(c + wid / 2.0 - 1))) for c in newc]
    return out, info


def _v21_uniformize(segs):
    """Merge split parts, pick the MEDIAN width, drop the odd blocks.

    Returns (rects, info).  Every rect is (x0, x1) with the SAME width and is centred
    on that key's own detected centre -- defect (1) and (4) fixed here."""
    info = {"raw_segs": [[int(a), int(b)] for a, b in segs]}
    if not segs:
        return [], info
    ws0 = np.array([b - a + 1 for a, b in segs], np.float32)
    med_w0 = float(np.median(ws0))
    strong = [(a, b) for a, b in segs if 0.6 * med_w0 <= (b - a + 1) <= 1.6 * med_w0]
    if len(strong) >= 2:
        cc = np.array([(a + b) / 2.0 for a, b in strong])
        dd = np.diff(cc)
        dd = dd[dd > 0]
        med_p = float(np.median(dd)) if dd.size else med_w0
    else:
        med_p = med_w0
    if not med_p or med_p <= 0:
        med_p = med_w0
    info["pitch_px"] = round(med_p, 1)
    # two groups closer than MERGE_SPLIT_FRAC * pitch are ONE key (dark notch)
    merged = []
    for a, b in sorted(segs, key=lambda s: (s[0] + s[1])):
        if merged and ((a + b) / 2.0 - (merged[-1][0] + merged[-1][1]) / 2.0) < _V21_MERGE_SPLIT_FRAC * med_p:
            merged[-1] = (min(merged[-1][0], a), max(merged[-1][1], b))
        else:
            merged.append((a, b))
    info["merged_segs"] = [[int(a), int(b)] for a, b in merged]
    info["n_merged"] = len(merged)
    ws = np.array([b - a + 1 for a, b in merged], np.float32)
    med_w0 = float(np.median(ws))
    strong2 = ws[(ws >= 0.6 * med_w0) & (ws <= 1.6 * med_w0)]
    med_w = float(np.median(strong2)) if strong2.size else med_w0
    info["width_median_detected_px"] = round(med_w, 1)
    info["widths_detected"] = [int(x) for x in ws]
    # ---- outlier removal (defect 4): the odd wide block on the left -----------
    centers = [(a + b) / 2.0 for a, b in merged]
    gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    med_gap = float(np.median(gaps)) if gaps else 0.0
    info["pitch_median_px"] = round(med_gap, 1)
    keep, flags = [], []
    for i, (a, b) in enumerate(merged):
        w = b - a + 1
        nb = []
        if i > 0:
            nb.append(centers[i] - centers[i - 1])
        if i < len(merged) - 1:
            nb.append(centers[i + 1] - centers[i])
        off_lat = bool(nb) and med_gap > 0 and all(
            abs(d - med_gap) > _V21_OUTLIER_P * med_gap for d in nb)
        too_wide = (w - med_w) > _V21_OUTLIER_W * med_w
        too_thin_off = (_V21_OUTLIER_W * med_w < (med_w - w)) and off_lat
        bad = bool(too_wide or off_lat or too_thin_off)
        keep.append(not bad)
        if bad:
            flags.append({"seg": [int(a), int(b)], "w": int(w),
                          "too_wide": bool(too_wide), "off_lattice": bool(off_lat),
                          "too_thin_off": bool(too_thin_off)})
    info["outlier_flags"] = flags
    n_keep = int(sum(keep))
    if n_keep < _V21_MIN_KEYS_KEEP:
        info["outlier_skipped"] = True
        info["outlier_note"] = ("only %d keys would remain (< %d) -> the outlier drop "
                                "is SKIPPED" % (n_keep, _V21_MIN_KEYS_KEEP))
        info["outlier_dropped"] = 0
        kept = merged
    else:
        info["outlier_skipped"] = False
        info["outlier_note"] = "odd blocks removed"
        info["outlier_dropped"] = int(len(merged) - n_keep)
        kept = [m for m, k in zip(merged, keep) if k]
    info["kept_segs"] = [[int(a), int(b)] for a, b in kept]
    # v21b (2026-10-08, shop floor: "real gold fingers are very uniform in width"):
    #   The detected centres of the *reliable* keys define ONE pitch and ONE phase.
    #   Every lattice slot inside the span of the *merged* (pre-outlier) segments that
    #   still has some detected structure gets its own key -> the dim keys that the
    #   outlier rule dropped come back, at a uniform width and a uniform pitch.
    half = med_w / 2.0
    mctr = [(a + b) / 2.0 for a, b in merged]
    kctr = [(a + b) / 2.0 for a, b in kept]
    if len(kctr) >= 2 and med_gap > 0:
        c_ref = kctr[0]
        resid = [c - round((c - c_ref) / med_gap) * med_gap for c in kctr]
        phase = float(np.median(resid))
        i0 = int(np.floor((mctr[0] - phase) / med_gap))
        i1 = int(np.ceil((mctr[-1] - phase) / med_gap))
        tol = 0.35 * med_gap
        # 🆕 v24 (2026-10-08 老倪「总共有19个金手指小金属条, 你怎么显示那么多呢? 最边上的不是金手指」):
        #   v21/v22 是"格子里有点东西就补一根", 于是**连接器两端的边缘亮条**也被补成金手指
        #   (实测: 左端一根 81px 宽的边条 + 一根 8~12px 的碎屑 ⇒ 凭空多画 2 根, 21 根而不是 19 根)。
        #   改成**按资格认领**:
        #     · 键宽结构(0.40~1.60×中位宽)  ⇒ 只认领它中心最近的那一格(正常的单根键);
        #     · 多键段(宽 ≥ 1.35×节距)      ⇒ 认领它跨度内的每一格(相邻两键被亮边粘成一段, 真身是 2 根);
        #     · 其余(过细碎屑 / 又宽又不合键宽的边缘亮条) ⇒ **一格都不认领**;
        #   然后 [最小格 .. 最大格] 之间的每一格都补上 —— 细金手指是连续的, 中间不该出现空格
        #   (这条同时修掉"偶尔少 1~2 根": 某一格没被检出时由 lattice 补齐)。
        _pad_lo, _pad_hi = 0.40 * med_w, 1.60 * med_w
        # 多键段(≥2 根键被亮边粘成一段)的宽度窗口: 下限 1.35×节距(一根键绝不可能这么宽),
        # 上限 1.66×节距(实测真·两根粘一起 = 86~108px; 而连接器两端的边缘整块金属 = 82~127px,
        # 其中 127px 这一档必须挡住 —— 它不是金手指, 现场:「最边上的不是金手指」)。
        _multi_lo = 1.35 * med_gap
        _multi_hi = 1.66 * med_gap
        _claims, _rejected = set(), []
        _lo = _hi = None
        for _a, _b in merged:
            _w = _b - _a + 1
            if _w < _pad_lo or (_pad_hi < _w < _multi_lo) or _w > _multi_hi:
                _rejected.append([int(_a), int(_b), int(_w)])   # 碎屑 / 边缘亮条 ⇒ 不认领
                continue
            if _w <= _pad_hi:                                   # 单根键
                _claims.add(int(round((0.5 * (_a + _b) - phase) / med_gap)))
            else:                                               # 多键段: 跨度内每格都认领
                for _i in range(int(np.floor((_a - 0.25 * med_gap - phase) / med_gap)),
                                int(np.ceil((_b + 0.25 * med_gap - phase) / med_gap)) + 1):
                    _c = phase + _i * med_gap
                    if _a - 0.25 * med_gap <= _c <= _b + 0.25 * med_gap:
                        _claims.add(int(_i))
        # v25b: 短窗逐格投票(见 _V25_VOTE_WIN 注释) —— 只动"哪些格被认领", 不动单帧的宽度规则
        _vote_note = None
        if _claims:
            _vk = _v25_view_key(med_gap)
            with _V25_SEEN_LOCK:
                _seen = _V25_SEEN.setdefault(_vk, [])
                _seen.append(frozenset(_claims))
                if len(_seen) > _V25_VOTE_WIN:
                    del _seen[0:len(_seen) - _V25_VOTE_WIN]
                if len(_V25_SEEN) > _V25_SEEN_KEEP:          # 只留最近几个视角桶
                    for _k in list(_V25_SEEN)[:len(_V25_SEEN) - _V25_SEEN_KEEP]:
                        _V25_SEEN.pop(_k, None)
                _tally = {}
                for _s in _seen:
                    for _i in _s:
                        _tally[_i] = _tally.get(_i, 0) + 1
                _raw = set(_claims)
                _kept = {_i for _i, _c in _tally.items() if _c >= _V25_VOTE_MIN}
            _vote_note = {"frames": len(_seen), "min": _V25_VOTE_MIN, "view_pitch_bucket": _vk,
                          "raw_span": [min(_raw), max(_raw)] if _raw else None,
                          "voted_span": [min(_kept), max(_kept)] if _kept else None,
                          "healed": sorted(set(range(min(_kept), max(_kept) + 1)) - _raw) if _kept else [],
                          "vetoed": sorted(_raw - _kept)}
            if _kept:
                _claims = _kept
        info["v25_vote"] = _vote_note
        if _claims:
            _lo, _hi = min(_claims), max(_claims)
            ctr = [int(round(phase + i * med_gap)) for i in range(_lo, _hi + 1)]
        else:
            ctr = [int(round(c)) for c in mctr]
            info["lattice_note"] = "no claimable structure; fallback to merged centres"
        if len(ctr) > 64:
            ctr = ctr[:64]
        info["lattice_pitch_px"] = round(float(med_gap), 1)
        info["lattice_phase_px"] = round(phase, 1)
        info["lattice_added_vs_kept"] = int(len(ctr) - len(kept))
        info["v24_pad_lo_px"] = round(float(_pad_lo), 1)
        info["v24_pad_hi_px"] = round(float(_pad_hi), 1)
        info["v24_multi_lo_px"] = round(float(_multi_lo), 1)
        info["v24_multi_hi_px"] = round(float(_multi_hi), 1)
        info["v24_claims_span"] = [_lo, _hi] if _claims else None
        info["v24_rejected_edge_segs"] = _rejected
        info["v24_note"] = ("按资格认领: 单键宽 %.0f~%.0fpx, 多键段宽 %.0f~%.0fpx; "
                            "被拒(碎屑/边缘整块金属) %d 段"
                            % (_pad_lo, _pad_hi, _multi_lo, _multi_hi, len(_rejected)))
    else:
        ctr = [int(round(c)) for c in mctr]
        info["lattice_note"] = "no regular pitch (fewer than 2 reliable keys)"
    rects = [(int(round(c - half)), int(round(c + half - 1))) for c in ctr]
    info["centers"] = ctr
    info["rects"] = [[int(a), int(b)] for a, b in rects]
    info["width_uniform_px"] = int(rects[0][1] - rects[0][0] + 1) if rects else 0
    info["n_keys"] = len(rects)
    return rects, info


def _v21_render_core(bgr, gain=None, gamma=None, deskew_deg=0.0, hw=_JUDGE_HW,
                     band=None, gate=None):
    """Core v21 renderer.  Returns (img | None, meta); see render_judge().

    v22: band=(ky0,ky1) 指定键行带, gate={col_level_frac,cf_key_col,min_key_w} 放宽门限 ——
    两者都为 None 时**与 v21 逐位一致**(所以成功帧的输出像素没有变化)。
    """
    gate = gate or {}
    met = {"ok": False, "why": "", "err": "", "deskew_deg": 0.0,
           "deskew_requested_deg": round(float(deskew_deg), 3),
           "deskew_note": ("v21 draws every key as an axis-aligned rectangle, so the "
                           "whole row is already upright; the caller's strip angle is "
                           "reported but NO extra rotation is applied (rotating would "
                           "tilt the delivered keys)")}
    out_w, out_h = int(hw[0]), int(hw[1])
    try:
        src = np.asarray(bgr).astype(np.uint8)
        if src.ndim == 2:
            src = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
        elif src.ndim == 3 and src.shape[2] == 4:
            src = cv2.cvtColor(src, cv2.COLOR_BGRA2BGR)
        if src.size == 0:
            met["why"] = "empty image"
            met["err"] = met["why"]
            return None, met
        h, w = src.shape[:2]
        met["src_size"] = [int(w), int(h)]
        g = _v21_luma(src)
        met["src_mean"] = round(float(g.mean()), 1)
        # 🆕 v25: 几何分析专用副本(逐帧对比度归一化) —— 阈值变相对量, 亮度漂移不影响判据几何。
        #   渲染不经过它(src 原样), sat_before / 曝光增益统计也仍用原图 g。
        ga = _v25_norm_luma(g)
        met["norm_luma"] = {"lo2": round(float(np.percentile(g, 2.0)), 1),
                            "hi99": round(float(np.percentile(g, 99.0)), 1),
                            "mean_before": round(float(g.mean()), 1),
                            "mean_after": round(float(ga.mean()), 1)}
        # ---- 1. key-row windows ------------------------------------------
        lvl = _V21_BRIGHT_LEVEL
        hits = _v21_key_windows(ga, lvl)
        if not hits:
            mrows = ga.mean(axis=1)
            bg = float(np.percentile(mrows, 20))
            # ⚠️ 别叫 gate: 它是函数参数 gate(dict) 的名字, 复用它会让下面 gate.get() 崩
            #    (2026-10-08 实测: 暗帧走到这条 fallback 分支 → AttributeError → 判据图整个报错)
            edge_gate = min(bg + 25.0, 1.35 * bg)
            cand = [y for y in range(0, h - _V21_WIN_H + 1, _V21_WIN_STEP)
                    if float(mrows[y:y + _V21_WIN_H].mean()) >= edge_gate]
            if cand:
                lvl = float(np.median([_v21_adaptive_bright(ga[y:y + _V21_WIN_H, :])
                                       for y in cand]))
                met["bright_level_fallback"] = True
                hits = _v21_key_windows(ga, lvl)
        met["bright_level_used"] = round(lvl, 1)
        met["_hits"] = list(hits)        # v22: 私有, 供失败重试挑候选键行带(不进 HTTP)
        met["_lvl"] = float(lvl)
        if not hits:
            met["why"] = ("no key-row window found (needs >= %d bright groups with a "
                          "median pitch of %.0f..%.0f px)"
                          % (_V21_MIN_KEYS, _V21_PITCH_MIN, _V21_PITCH_MAX))
            met["err"] = met["why"]
            return None, met
        if band is not None:                     # v22 重试: 指定单窗键行带
            ky0, ky1 = int(band[0]), int(band[1])
            met["band_overridden"] = [int(ky0), int(ky1)]
        else:
            ky0 = min(hh["y0"] for hh in hits)
            ky1 = max(hh["y1"] for hh in hits)
        # ---- 2. strip columns (kills the flat grey block on the right) ----
        left, right, rsrc, lsrc, band = _v21_strip_cols(ga, ky0, ky1)   # v25: 归一化域 ⇒ 裁窗不随亮度漂
        if right is None:
            right = w - 1
        cx0 = int(max(0, left - _V21_COL_PAD))
        cx1 = int(min(w, right + 1 + _V21_COL_PAD))
        met.update({"key_row_span": [int(ky0), int(ky1)],
                    "strip_cols": [int(left), int(right)],
                    "strip_x": [int(cx0), int(cx1)], "band_h": int(ky1 - ky0 + 1),
                    "right_edge_x": int(cx1), "right_edge_src": rsrc,
                    "left_edge_src": lsrc})
        met["sat_before"] = round(
            float((g[ky0:ky1 + 1, cx0:cx1] >= _SAT_LEVEL).mean()), 4)
        if right - left + 1 < _V21_MIN_KEEP_W:
            met["why"] = ("strip column run too narrow after the cut (%d px < %d)"
                          % (right - left + 1, _V21_MIN_KEEP_W))
            met["err"] = met["why"]
            return None, met
        # ---- 3. keys (columns), then the UNIFORM width --------------------
        band_rows = np.arange(ky0, ky1 + 1)
        lvl_col = max(_V21_BRIGHT_MIN, float(gate.get("col_level_frac", _V21_COL_LEVEL_FRAC)) * lvl)
        met["col_bright_level"] = round(lvl_col, 1)
        if gate:
            met["gate_used"] = {k: gate.get(k) for k in ("col_level_frac", "cf_key_col", "min_key_w")
                                if gate.get(k) is not None}
        segs, cf, cl = _v21_key_cols(ga, band_rows, cx0, cx1, lvl_col,
                                     cf_key_col=gate.get("cf_key_col"),
                                     min_key_w=gate.get("min_key_w"))
        if not segs:
            met["why"] = "no key columns survived the bright-column gate"
            met["err"] = met["why"]
            return None, met
        rects, uinfo = _v21_uniformize(segs)
        met.update(uinfo)
        # 🆕 v26: 格点补齐(内部缺口 + 两端延伸) —— 点2 右段黑帽被高光吃掉导致掩膜跨度截断
        _r26, _i26 = _v26_fill_lattice(rects, ga, cx0, cx1, ky0, ky1)
        met.update(_i26)
        if _i26.get("v26_on") and len(_r26) != len(rects):
            rects = _r26
            met["n_keys"] = len(rects)
            met["v26_note"] = ("格点补齐 %d -> %d (内补 %s · 外延 %s)"
                               % (int(uinfo.get("n_keys") or 0), len(rects),
                                  _i26.get("v26_added_in"), _i26.get("v26_added_out")))
        if int(uinfo.get("n_keys") or 0) < 3:
            met["why"] = "too few keys after detection (%s)" % uinfo.get("n_keys")
            met["err"] = met["why"]
            return None, met
        # ---- 4. the solid bar: truncate the band, never punch a hole ------
        bf = (ga[:, cx0:cx1] >= lvl).mean(axis=1)      # v25: 同上
        inband = np.zeros(h, bool)
        inband[ky0:ky1 + 1] = True
        bar = inband & (bf >= _V21_BAR_BRIGHT)
        bar_rows = np.where(bar)[0]
        bar_run = None
        if bar_rows.size:
            runs = []
            s = bar_rows[0]
            p = bar_rows[0]
            for v in bar_rows[1:]:
                if v == p + 1:
                    p = v
                else:
                    runs.append((int(s), int(p)))
                    s = v
                    p = v
            runs.append((int(s), int(p)))
            bar_run = max(runs, key=lambda r: r[1] - r[0])
        keyrows = np.zeros(h, bool)
        if bar_run is not None:
            keyrows[ky0:bar_run[0]] = True        # keep only the rows BEFORE the bar
            met["bar_rows_dropped"] = int(bar_run[1] - bar_run[0] + 1)
            met["bar_rows_range"] = [int(bar_run[0]), int(bar_run[1])]
            met["bar_rule"] = ("full-width bright rows (bf >= %.2f): the longest run "
                               "truncates the key band at its START; no hole is cut "
                               "inside the band" % _V21_BAR_BRIGHT)
        else:
            keyrows[ky0:ky1 + 1] = True
            met["bar_rows_dropped"] = 0
            met["bar_rows_range"] = None
            met["bar_rule"] = "no full-width bright run inside the band"
        krr = np.where(keyrows)[0]
        met["key_rows"] = [int(krr.min()), int(krr.max())]
        met["n_key_rows"] = int(keyrows.sum())
        if keyrows.sum() < 30:
            met["why"] = ("only %d key rows survive the bar truncation (need >= 30)"
                          % int(keyrows.sum()))
            met["err"] = met["why"]
            return None, met
        # ---- 5. mask = SOLID RECTANGLES (key rows x uniform key columns) ---
        colmask = np.zeros(w, bool)
        for a, b in rects:
            colmask[max(0, a):min(w, b + 1)] = True
        mask = keyrows[:, None] & colmask[None, :]
        ys, xs = np.where(mask)
        if ys.size < 200:
            met["why"] = "the key mask is essentially empty (%d px)" % int(ys.size)
            met["err"] = met["why"]
            return None, met
        bx0, bx1 = int(xs.min()), int(xs.max()) + 1
        by0, by1 = int(ys.min()), int(ys.max()) + 1
        met["mask_bbox"] = [bx0, by0, bx1, by1]
        # tilt from the key-band TOP edge measured on the closed mask
        tx, ty = [], []
        for a, b in rects:
            for x in range(max(a, cx0), min(b + 1, cx1)):
                col = np.where(cl[:, x - cx0])[0]
                if col.size:
                    tx.append(x)
                    ty.append(float(ky0 + col[0]))
        fit = _v21_robust_line(tx, ty)
        slope = _v21_pivot_slope(tx, ty)
        if slope is None:
            slope = fit[0] if fit else 0.0
        tilt = float(np.degrees(np.arctan(slope)))
        met["tilt_deg"] = round(tilt, 3)
        met["tilt_resid_px"] = round(fit[1], 2) if fit else None
        met["tilt_src"] = "median-pivot slope of the key-band top edge (closed mask)"
        # ---- 6. crop, deskew (black border), exposure ----------------------
        px0 = max(0, bx0 - _V21_CROP_PAD)
        py0 = max(0, by0 - _V21_CROP_PAD)
        px1 = min(w, bx1 + _V21_CROP_PAD)
        py1 = min(h, by1 + _V21_CROP_PAD)
        block = src[py0:py1, px0:px1].copy()
        mk = mask[py0:py1, px0:px1]
        # v23: 这里**不再**把键外像素清零 —— 保留原像素走完增益, 最后统一按 _V23_GAP_DIM 压暗,
        #      这样键之间的间隙保留原底色(老倪: 全黑"感觉很怪")。增益统计只看键内像素[mk], 不受影响。
        met["gap_dim"] = float(_V23_GAP_DIM)
        met["crop"] = [int(px0), int(py0), int(px1), int(py1)]
        met["crop_wh"] = [int(px1 - px0), int(py1 - py0)]
        # NOTE: no deskew rotation is applied.  Every key is an axis-aligned rectangle
        # in native coordinates, so the delivered row is upright by construction; the
        # caller's strip angle (deskew_deg) is only recorded (see met["deskew_note"]).
        if gain is None:
            kept = _v21_luma(block)[mk]
            p99 = float(np.percentile(kept, 99)) if kept.size else 255.0
            gain = float(np.clip(_V21_AUTO_PEAK / max(p99, 1.0), 0.15, 1.0))
            met["exposure_auto"] = True
        else:
            met["exposure_auto"] = False
        if gamma is None:
            gamma = 1.0
        xf = block.astype(np.float32) / 255.0
        xf = np.clip(xf * float(gain), 0.0, 1.0)
        xf = np.power(xf, 1.0 / max(float(gamma), 1e-3))
        block = np.clip(xf * 255.0, 0.0, 255.0).astype(np.uint8)
        if _V23_GAP_DIM >= 1.0:
            pass                                        # 1.0 = 完全保留原像素
        elif _V23_GAP_DIM <= 0.0:
            block[~mk] = 0                              # 0.0 = 纯黑(v21 老口径)
        else:
            block[~mk] = (block[~mk].astype(np.float32) * float(_V23_GAP_DIM)).astype(np.uint8)
        met["gain"] = round(float(gain), 4)
        met["gamma"] = round(float(gamma), 4)
        # ---- 7. scale to width out_w (natural aspect × 键高系数), centre on black -----
        _vs = max(0.1, float(_V23_KEY_HSTRETCH))       # v23: 键高 1.2×(宽度不变, 纯显示放大)
        scw = out_w / float(block.shape[1])
        sch = out_h / float(block.shape[0] * _vs)      # 高度预算按"拉伸后"算 ⇒ 一定装得下
        sc = min(scw, sch)
        ow = max(1, int(round(block.shape[1] * sc)))
        oh = max(1, int(round(block.shape[0] * sc * _vs)))
        interp = cv2.INTER_AREA if sc < 1.0 else cv2.INTER_NEAREST
        rs = cv2.resize(block, (ow, oh), interpolation=interp)   # 纵向 = sc*_vs ⇒ 键高 ×1.2
        out = np.zeros((out_h, out_w, 3), np.uint8)
        x0o = max(0, (out_w - ow) // 2)
        y0o = max(0, (out_h - oh) // 2)
        out[y0o:y0o + min(oh, out_h - y0o), x0o:x0o + min(ow, out_w - x0o)] = \
            rs[:min(oh, out_h - y0o), :min(ow, out_w - x0o)]
        met["resize_scale"] = round(float(sc), 4)
        met["scale_width_limited"] = bool(scw <= sch)
        met["out_size"] = [out_w, out_h]
        if min(out.shape[:2]) < 3:
            met["why"] = "degenerate output size %r" % (out.shape,)
            met["err"] = met["why"]
            return None, met
        # ---- 8. metrics ---------------------------------------------------
        go = _v21_luma(out)
        nz = (out > 0).any(axis=2)
        met["black_frac"] = round(float((out == 0).all(axis=2).mean()), 4)
        met["strip_mean"] = round(float(go.mean()), 1)
        met["strip_mean_content"] = round(float(go[nz].mean()), 1) if nz.any() else 0.0
        met["strip_sat_frac"] = round(float((go >= _SAT_LEVEL).mean()), 4)
        met["nonblack_frac"] = round(float(nz.mean()), 4)
        met["ok"] = True
        met["err"] = ""
        return out, met
    except Exception as exc:                                             # noqa: BLE001
        met["why"] = "judge render failed: %s" % exc
        met["err"] = met["why"]
        traceback.print_exc()
        return None, met


def _v21_render(bgr, gain=None, gamma=None, deskew_deg=0.0, hw=_JUDGE_HW):
    """v22 外壳: 第 1 遍严格按 v21 口径(成功帧像素与 v21 逐位一致);

    只有当第 1 遍失败时才**逐窗 + 放宽门限**重试 —— 救回那 ~5% 的失败帧,
    并且重试结果要过 _V22_ACCEPT(饱和/键数/黑底)才被采纳, 避免"救回一张错的"。
    """
    img, met = _v21_render_core(bgr, gain=gain, gamma=gamma, deskew_deg=deskew_deg, hw=hw)
    met = dict(met or {})
    if img is not None:
        met["ver"] = _JUDGE_VER
        met["attempt"] = 1
        met["attempts_note"] = "v21 band+gate (1st attempt) OK"
        met.pop("_hits", None)
        met.pop("_lvl", None)
        return img, met
    hits = met.get("_hits") or []
    first_why = met.get("why") or met.get("err") or "judge render failed"
    h = int((met.get("src_size") or [0, 0])[1] or 0)
    cands = _v22_band_candidates(hits, h)
    n = 0
    last_why = first_why
    for ci, band in enumerate(cands):
        for gi, gate in enumerate(_V22_GATES):
            if ci == 0 and not gate:
                continue                      # 合并带 + 默认门限 = 刚刚失败的那一组
            n += 1
            try:
                img2, met2 = _v21_render_core(bgr, gain=gain, gamma=gamma, deskew_deg=deskew_deg,
                                              hw=hw, band=band, gate=gate)
            except Exception as exc:                                          # noqa: BLE001
                last_why = "retry raised: %s" % exc
                continue
            if img2 is None:
                last_why = met2.get("why") or last_why
                continue
            _sat = float(met2.get("sat_before") or 0.0)
            _nk = int(met2.get("n_keys") or 0)
            _bf = float(met2.get("black_frac") or 0.0)
            if (_sat > _V22_ACCEPT["max_sat_before"] or _nk < _V22_ACCEPT["min_keys"]
                    or _bf < _V22_ACCEPT["min_black_frac"]):
                last_why = ("retry produced a doubtful picture (sat=%.2f keys=%d black=%.2f) -> rejected"
                            % (_sat, _nk, _bf))
                continue
            met2["ver"] = _JUDGE_VER
            met2["attempt"] = n + 1
            met2["band_used"] = [int(band[0]), int(band[1])]
            met2["gate_used"] = int(gi)
            met2["first_why"] = first_why
            met2["attempts_note"] = ("v21 band+gate FAILED (%s) -> RECOVERED by v22 retry #%d "
                                     "(band=%s gate=%d)" % (first_why, n + 1, band, gi))
            met2.pop("_hits", None)
            met2.pop("_lvl", None)
            return img2, met2
    met["ver"] = _JUDGE_VER
    met["attempt"] = n + 1
    met["candidates"] = len(cands)
    met["first_why"] = first_why
    met["last_why"] = last_why
    met["why"] = first_why
    met["err"] = first_why
    met.pop("_hits", None)
    met.pop("_lvl", None)
    return None, met


def render_judge(bgr, deskew_deg=0.0, hw=_JUDGE_HW, k=_JR_K):
    """Machine frame (BGR) -> **v21 judge picture** (BGR, fixed size hw=(900,332)).

    v21: a row of EQUAL-WIDTH vertical keys (piano keys) on pure black, exposure
    compressed; the short side is not stretched.  Returns (judge_bgr | None, meta).
    On failure img is None and meta carries both 'why' and 'err' (the v20 caller reads
    'err'), so the caller falls back to the regular crop -- a wrong judge picture is
    never handed out.  For the v20 prints and /last_result the meta also carries the
    v20 names (out/kept_rows/kept_h/dropped_sat_rows/dropped_pct/sat_before/sat_after/
    x_trim/k/fix_hw/deskew_deg).
    """
    _hw = (int(hw[0]), int(hw[1])) if hw else _JUDGE_HW
    img, met = _v21_render(bgr, deskew_deg=deskew_deg, hw=_hw)
    met = dict(met or {})
    if img is None:
        met.setdefault("err", met.get("why") or "judge render failed")
        return None, met
    # ---- v20-compatible meta aliases (the caller and /last_result read these) ----
    met["out"] = met.get("out_size")
    met["kept_rows"] = met.get("key_rows")
    met["kept_h"] = met.get("n_key_rows")
    met["dropped_sat_rows"] = met.get("bar_rows_dropped")
    _bh = max(1, int(met.get("band_h") or 1))
    met["dropped_pct"] = round(100.0 * int(met.get("bar_rows_dropped") or 0) / _bh, 1)
    met["sat_after"] = met.get("strip_sat_frac")
    _sx = met.get("strip_x") or [0, 0]
    met["x_trim"] = {"trimmed": True, "x_span": [int(_sx[0]), int(_sx[1])],
                     "dropped_cols": ([0, int(_sx[0])] if _sx[0] else []),
                     "col_sat_before_max": None,
                     "rule": "v21 strip columns (horizontal edge strength |dI/dy|)"}
    met["k"] = float(k)
    met["fix_hw"] = [int(_hw[0]), int(_hw[1])]
    return img, met


def crop_goldfinger_regular(bgr):
    """v4 核心: 模板法把金手指条裁成规整图。返回 (crop, info)
    同时把"原比例版"(1:1 像素, 不拉伸) 放到 info 外的全局缓存, 供落盘/目检"""
    global _LAST_NATURAL
    cr = get_cropper()
    if cr is None:
        h, w = bgr.shape[:2]
        return warp_goldfinger_topview(bgr.tobytes(), w, h, CANONICAL_W, CANONICAL_H), {"method": "legacy_no_template"}
    crop, info = cr.crop(bgr)
    _LAST_NATURAL = getattr(cr, "_last_natural", None)
    return crop, info


def GrabAndSaveImage(save: bool = True):
    """抓一帧 → 原图 → 模板法规整裁剪 → 裁剪图(+标注图取证)。

    v5: 图**总是**进内存(取图走内存); `save=True`(真检测)才落盘, `save=False`(只看一眼)不落盘。
    """
    global global_img_count
    _TL.save = bool(save)
    ppayload = ctypes.c_void_p()
    reVal = m_Device.SciCam_Grab(ppayload)
    if reVal != SCI_CAMERA_OK:
        print('Grab抓取帧失败，错误码：%d' % reVal)
        return None, None
    payloadAttribute = SCI_CAM_PAYLOAD_ATTRIBUTE()
    reVal = SciCam_Payload_GetAttribute(ppayload, payloadAttribute)
    if reVal != SCI_CAMERA_OK:
        print('Get payload attribute failed: %d' % reVal)
        m_Device.SciCam_FreePayload(ppayload)
        return None, None
    imgIsComplete = bool(payloadAttribute.isComplete)
    payloadMode = payloadAttribute.payloadMode
    imgPixelType = payloadAttribute.imgAttr.pixelType
    imgWidth = payloadAttribute.imgAttr.width
    imgHeight = payloadAttribute.imgAttr.height

    if not os.path.exists(SAVE_ROOT_DIR):
        os.makedirs(SAVE_ROOT_DIR, exist_ok=True)
    no = global_img_count
    origin_name = "Finger_Image_W{}_H{}_No_{}.png".format(imgWidth, imgHeight, no)
    save_file_param = os.path.join(SAVE_ROOT_DIR, origin_name)
    global_img_count += 1

    if not imgIsComplete or payloadMode != SciCamPayloadMode.SciCam_PayloadMode_2D:
        print("Image data is not complete or payload type error,")
        m_Device.SciCam_FreePayload(ppayload)
        return None, None

    imgData = ctypes.c_void_p()
    reVal = SciCam_Payload_GetImage(ppayload, imgData)
    if reVal != SCI_CAMERA_OK:
        print('Get image data failed: %d' % reVal)
        m_Device.SciCam_FreePayload(ppayload)
        return None, None

    dstImgSize = ctypes.c_int()
    mono_types = [
        SciCamPixelType.Mono1p, SciCamPixelType.Mono2p, SciCamPixelType.Mono4p,
        SciCamPixelType.Mono8s, SciCamPixelType.Mono8,
        SciCamPixelType.Mono10, SciCamPixelType.Mono10p,
        SciCamPixelType.Mono12, SciCamPixelType.Mono12p,
        SciCamPixelType.Mono14, SciCamPixelType.Mono16,
        SciCamPixelType.Mono10Packed, SciCamPixelType.Mono12Packed, SciCamPixelType.Mono14p
    ]
    is_mono = imgPixelType in mono_types
    target_type = SciCamPixelType.Mono8 if is_mono else SciCamPixelType.RGB8
    nch = 1 if is_mono else 3

    reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, target_type, None, dstImgSize, True)
    top_path = None
    if reVal == SCI_CAMERA_OK:
        pDstData = (ctypes.c_ubyte * dstImgSize.value)()
        reVal = SciCam_Payload_ConvertImage(payloadAttribute.imgAttr, imgData, target_type, pDstData, dstImgSize, True)
        if reVal == SCI_CAMERA_OK:
            arr = np.frombuffer(pDstData, dtype=np.uint8).reshape(imgHeight, imgWidth, nch)
            bgr = arr if nch == 3 else cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

            # ---- v4: 模板法规整裁剪 ----
            t_crop = time.time()
            crop, info = crop_goldfinger_regular(bgr)
            dt_crop = (time.time() - t_crop) * 1000
            q = info.get("quality", {}) or {}
            # 🆕 v7 (2026-09-29 老倪「在工控机保存的 topview 图片…改成判据图的样子」):
            #   · 落盘/对外展示的 **topview = 判据图口径**(过曝切除+只留金手指条+列裁+短边×2+反倾角+定尺900x332)
            # 🆕 v8 (2026-09-30 老倪「Finger_ModelIn_…就不要了; 模型用的是这个图片; 确认模型使用的是不是 topview」):
            #   · **只落一张图** = Finger_TopView_*(判据图); Finger_ModelIn_* 不再写盘(老文件按上限自动清掉)
            #   · 影子对照: 同帧老口径 960 方图也跑一遍, 临时图 %TEMP% 跑完即删, 结果进 /last_result
            # 🆕 v9 (2026-09-30 现场实测修正): v8 让模型**直接吃 900x332 判据图** ——
            #      在工控机 app 里**卡死**(同一张图: app 进程 CPU 空转 3 分钟不返回、incoming 不再落图、
            #      %TEMP% 里堆了 ~90 张没删的临时图; 换 venv 解释器单独跑同一张只要 0.7s)
            #      ⇒ 该口径在工控机运行环境里**不可用**(检测通道会死)。
            #      改回: 模型吃**同帧派生的 960x960 方图**(与 v6/v7 逐位同口径, 保证召回), 但**不落盘**:
            #      临时图写 %TEMP%, 检测完即删 ⇒ goldfinger_images 里只剩判据图一张。
            #      影子对照改成: 用**判据图压成 960x960** 再喂一次(方形, 不走那条会卡死的路),
            #      两个口径同帧对照(自然条带 ×13.7  vs  判据图含上下内容 ⇒ 谁更准用数据说话)。
            t_j = time.time()
            judge, jmeta = render_judge(bgr, deskew_deg=float(info.get("angle") or 0.0))
            dt_j = (time.time() - t_j) * 1000
            model_in = crop                    # 主口径 960x960(金手指条带拉伸, 与 v6/v7 逐位同口径)
            if judge is None:
                # 🆕 v22 (2026-10-08 晚): 老代码把 topview 静默回退成旧的 960x960 拉伸图 ⇒
                #   现场看到"右侧有方块区域, 不是金手指"(其实是**旧口径**那张, 不是判据图)。
                #   现在: 保留**上一张好判据图** + 红条标注(帧龄/原因); 一张好图都没有才退回 960 并如实标注。
                print("  ⚠️ 判据图渲染失败(%s) ⇒ 保留上一张好判据图 + 红条标注(不再端旧 960x960 口径)"
                      % jmeta.get("err"))
                _v22_dump_fail(bgr, jmeta, no)          # 有界取证: 输入帧 + 完整 meta(覆盖式, 不增长)
                judge, _jst = _v22_judge_fail_view(crop, jmeta, no, _v22_view_key_from_crop(crop))
                jmeta["state"] = _jst
                jmeta["fail_ver"] = _JUDGE_VER
            else:
                jmeta["state"] = "ok"
                _v22_remember_good(judge, no, _v22_view_key_from_crop(crop))   # 记好图(**按视角**), 供同视角失败顶着用
            _mem_put(crop=judge, origin=bgr, natural=_LAST_NATURAL)   # v5: 内存帧(kind=crop 给的就是判据图)
            top_name = "Finger_TopView_W{}_H{}_No_{}.png".format(judge.shape[1], judge.shape[0], no)
            top_path = os.path.join(SAVE_ROOT_DIR, top_name)
            _iw(top_path, judge)               # ✅ 唯一落盘的一张 = 判据图(不再写 Finger_ModelIn_*)
            # 主口径输入(960x960): 临时图, 检测完即删 ⇒ 目录里不留第二张
            # ⚠️ 2026-09-30 踩坑(v9⇒v10): 这两段临时图代码在 GrabAndSaveImage 里, 而"只看一眼"的
            #    grab(页面 0.5s 一次)也走这个函数 ⇒ 每次 grab 写 2 张临时图却没人删 ⇒ 实测 9 分钟
            #    在 %TEMP% 堆了 2180 张。现在**只有 save=True(真检测, 会入队)才写**, 并且每次真检测
            #    先做一次 _sweep_temp() 清残留(只碰我们自己的三个前缀, 只删 60s 以上的)。
            if save:
                _sweep_temp()
            mi_path = None
            if save and model_in is not None:
                try:
                    mi_path = os.path.join(TEMP_DIR, "zmax_main_960_No_%s.png" % no)
                    cv2.imwrite(mi_path, model_in)
                except Exception as e:                                     # noqa: BLE001
                    mi_path = None
                    print("  ⚠️ 主口径临时图写失败: %s" % e)
            # 影子对照: 判据图压成 960x960(方形, 避开那条会卡死的路) ⇒ 同帧两口径对照
            sh_path = None                     # 影子对照的临时图(在 %TEMP%, 检测完删)
            shadow_left = max(0, _AB_LEFT - _AB_DONE)
            if save and judge is not None and shadow_left > 0:
                try:
                    sh_path = os.path.join(TEMP_DIR, "zmax_ab_judge960_No_%s.png" % no)
                    cv2.imwrite(sh_path, cv2.resize(judge, (960, 960), interpolation=cv2.INTER_LINEAR))
                except Exception as e:                                     # noqa: BLE001
                    sh_path = None
                    print("  ⚠️ 影子对照临时图写失败: %s" % e)
            global _LAST_MODELIN, _LAST_SHADOW, _LAST_MODELIN_IMG, _LAST_MODELIN_META
            _LAST_MODELIN = mi_path or top_path
            _LAST_SHADOW = sh_path or ""
            if save and model_in is not None:      # 🆕 v11: 留一份"模型实际吃的那份像素"在内存
                _LAST_MODELIN_IMG = model_in
                _LAST_MODELIN_META = {"n": no, "t": time.time(),
                                      "hw": [int(model_in.shape[1]), int(model_in.shape[0])],
                                      "md5": hashlib.md5(np.ascontiguousarray(model_in).tobytes()).hexdigest(),
                                      "src": "crop_goldfinger_regular(模板法规整裁剪) → 960x960",
                                      "fed_to": "detector.detect(path=<该临时文件>, detect_type=<本端口类型: gf>)",
                                      "note": "detector 读的是 %TEMP% 下的同名临时文件, 检测完即删; 这里留的是同一份像素"}
            nat = _LAST_NATURAL
            if nat is not None:
                _iw(os.path.join(SAVE_ROOT_DIR, "Finger_CropNatural_W{}_H{}_No_{}.png".format(
                    nat.shape[1], nat.shape[0], no)), nat)
            anno_path = os.path.join(SAVE_ROOT_DIR, "Finger_CropAnno_No_{}.png".format(no))
            _iw(anno_path, annotate(bgr, info))
            _note = str(jmeta.get("attempts_note") or "")
            print(f"  【判据图】v22 状态={jmeta.get('state') or '?'} 第{jmeta.get('attempt')}遍"
                  f"{' | ' + _note if int(jmeta.get('attempt') or 1) > 1 else ''} | "
                  f"保留行={jmeta.get('kept_rows')} ({jmeta.get('kept_h')}行) "
                  f"切过曝行={jmeta.get('dropped_sat_rows')}({jmeta.get('dropped_pct')}%) "
                  f"列裁={(jmeta.get('x_trim') or {}).get('x_span')} 倾角={jmeta.get('deskew_deg')}° "
                  f"定尺={jmeta.get('fix_hw')} 饱和={jmeta.get('sat_after')} 耗时={dt_j:.0f}ms")
            # ⚠️ 这里不能直接用 detect_type(那是路由/worker 的局部变量) —— 用与本函数同一真源解析
            _dt, _ = _resolve_detect_type_by_channel()
            print("  【送检】模型吃 %s (%sx%s, 存在=%s) —— detector.detect(这张, detect_type=%s)" % (
                os.path.basename(mi_path or "(未写盘!)"),
                model_in.shape[1] if model_in is not None else "?",
                model_in.shape[0] if model_in is not None else "?",
                bool(mi_path and os.path.exists(mi_path)), _dt))
            print("  【落盘】只留判据图 -> %s (%dx%d)" % (top_name, judge.shape[1], judge.shape[0]))
            if sh_path:
                print("  【影子对照】判据图压 960 也跑一遍(临时图, 跑完删) 剩余 %d 张" % (shadow_left - 1))
            print(f"  【金手指截取】{info.get('method')} 模式={GF_CROP_MODE} 尺寸={crop.shape[1]}x{crop.shape[0]} "
                  f"score={info.get('score')} 角度={info.get('angle')}° "
                  f"残余倾角={q.get('stripe_slope_px_per_1000')}px/1000 线残差={q.get('stripe_line_resid_px')}px "
                  f"金覆盖={q.get('gold_cover')} 高亮占比={q.get('bright_frac')} "
                  f"原比例={info.get('natural')} 耗时={dt_crop:.0f}ms"
                  + (f" ⚠️{info['warn']}" if info.get("warn") else ""))
            if SAVE_LEGACY_TOPVIEW:
                try:
                    leg = warp_goldfinger_topview(bgr.tobytes(), imgWidth, imgHeight, 1600, 220)
                    _iw(os.path.join(SAVE_ROOT_DIR, "Legacy_TopView_No_{}.png".format(no)), leg)
                except Exception:
                    pass
            # 🆕 v12: 只有真检测(save=True, 写了模型输入临时图)才更新"模型吃哪张"; grab 保持上次真值
            _mi_fields = ({"model_input_file": os.path.basename(mi_path),
                           "model_input_kind": "960x960 方图(同帧派生, 检测完即删)",
                           "model_input_full": mi_path,
                           "model_input_frame_n": no,
                           "judge_file": os.path.basename(top_path)} if mi_path else {})
            with _PIC_LOCK:
                # 先留住"模型吃哪张"那几项: grab(save=False)不重算, 必须沿用上一次真检测的值
                _prev_mi = {_k: _LAST_CROP_INFO[_k] for _k in
                            ("model_input_file", "model_input_kind", "model_input_full",
                             "model_input_frame_n", "judge_file", "crop_file", "anno_file") if _k in _LAST_CROP_INFO}
                _LAST_CROP_INFO.clear()
                _LAST_CROP_INFO.update(_prev_mi)      # 先铺上次真检测的值, 再被下面的真值覆盖
                _LAST_CROP_INFO.update({"n": no, "t": time.time(), "crop_ms": round(dt_crop, 1),
                                        # grab(save=False)不落盘 ⇒ crop_file/anno_file 沿用上次真检测的文件名,
                                        # 否则这里会写出一个**根本不存在**的文件名(自欺)
                                        "grab": (not bool(mi_path)),
                                        "crop_file": os.path.basename(top_path) if mi_path else _prev_mi.get("crop_file", ""),
                                        # 🆕 v12: 模型吃的是**同帧派生的 960 方图**(临时文件), 不是判据图。
                                        #   v8 那会儿模型确实吃判据图, 这个字段就写成了 top_path; v9 改回 960 后忘了同步 ⇒
                                        #   与 /last_result.model_input 不一致(老倪一眼就会看出) —— 这里改成真实值 + 类型说明。
                                        **_mi_fields,
                                        "judge_ms": round(dt_j, 1),
                                        # 🆕 v22: 原来只暴露 11 个 v20 别名, **渲染失败时它们全是 null**
                                        #    ⇒ 故障隐形(看不出"这一帧根本没出判据图")。补上 状态/版本/原因。
                                        "judge_ver": _JUDGE_VER,
                                        "judge": {k: jmeta.get(k) for k in
                                                  ("out", "kept_rows", "kept_h", "dropped_sat_rows", "dropped_pct",
                                                   "sat_before", "sat_after", "x_trim", "k", "fix_hw", "deskew_deg",
                                                   "state", "ver", "why", "err", "n_keys", "attempt")},
                                        "anno_file": os.path.basename(anno_path), **info})
            # v4.2: 金手指"区域"信息(原始图坐标系) + 对焦清晰度 —— 供状态空间/机械臂伺服使用
            try:
                reg = _region_payload(bgr, info)
                with _PIC_LOCK:
                    _LAST_REGION.clear()
                    _LAST_REGION.update(reg)
            except Exception as _e:
                print(f"  ⚠️ 区域信息计算失败: {_e}")
            # 原图落盘 (与 v3 一致; v5: save=False 时不写盘 —— 老倪「不检测时不用存那么多图」)
            if getattr(_TL, "save", True):
                reVal = SciCam_Payload_SaveImage(save_file_param, target_type, pDstData, imgWidth, imgHeight)
                if reVal == SCI_CAMERA_OK:
                    print('原图保存成功.', save_file_param)
            else:
                print('  (v5 未落盘: 只是取图/看一眼, 图留在内存)')

    m_Device.SciCam_FreePayload(ppayload)
    return save_file_param, top_path


global_img_count = 1

# 【异步】检测队列: 单worker串行处理, 模型只加载一次, API秒回
_detect_lock = threading.Lock()
_detect_count = 0
_detect_queue = []
_detect_thread = None


def _detect_worker_loop():
    global _detect_count
    while True:
        item = None
        with _detect_lock:
            if _detect_queue:
                item = _detect_queue.pop(0)
        if item is None:
            time.sleep(0.2)
            continue
        # v8: (判据图=模型输入, 原图, 类型, 台账用判据图, 影子对照临时图)
        topview_path, origin_path, detect_type, judge_path, shadow_path = (list(item) + [None] * 5)[:5]
        try:
            if not topview_path or not os.path.exists(topview_path):
                print("  ⚠️ 跳过一项: 模型输入图已不在(%s) —— 不把不存在的路径喂给检测器" % topview_path)
                continue
            t0 = time.time()
            result = detector.detect(topview_path, detect_type=detect_type)
            dt_ms = (time.time() - t0) * 1000
            dets = result.get("detections", [])
            with _detect_lock:
                _detect_count += 1
                n = _detect_count
            print("\n" + "=" * 60)
            print(f"【检测结果 #{n}】{CAM_DESC} 推理耗时 {dt_ms:.0f}ms")
            print(f"  原图:   {origin_path}")
            print(f"  模型输入(送检)=960x960 同帧派生(不落盘): {topview_path}")
            print(f"  判据图(唯一落盘/展示): {judge_path or ''}")
            print(f"  缺陷数(topview 口径): {len(dets)}  {'❌ NG' if dets else '✅ OK'}")
            for i, d in enumerate(dets):
                cls = d.get("class_name", d.get("name", "?"))
                conf = d.get("confidence", d.get("conf", 0))
                bbox = d.get("bbox", d.get("box", "?"))
                print(f"    [{i+1}] {cls} conf={conf:.2f} bbox={bbox}")
            if result.get("saved_incoming"):
                print(f"  存档: {result['saved_incoming']}")
            # ── v8 影子对照: 同帧再跑一遍老口径 960 方图(临时图, 跑完删) ──
            sh = None
            global _AB_DONE
            if shadow_path and os.path.exists(shadow_path):
                try:
                    t1 = time.time()
                    r2 = detector.detect(shadow_path, detect_type=detect_type)
                    d2 = r2.get("detections", []) or []
                    sh = {"input": "判据图压 960x960", "input_file": os.path.basename(shadow_path),
                          "count": len(d2), "verdict": ("NG" if d2 else "OK"), "ms": round((time.time() - t1) * 1000, 1),
                          "defects": d2}
                    print("  影子对照(判据图压 960 口径): 缺陷数 %d %s  %sms  %s" %
                          (len(d2), "❌ NG" if d2 else "✅ OK", sh["ms"],
                           "与主口径一致" if (len(d2) > 0) == (len(dets) > 0) else "⚠️ 两口径判决不同(需人工看)"))
                    _AB_DONE += 1
                except Exception as e:                                     # noqa: BLE001
                    print("  ⚠️ 影子对照失败: %s" % e)
                finally:
                    try:
                        os.remove(shadow_path)          # 临时图不留(老倪: 只留判据图)
                    except OSError:
                        pass
            # 主口径临时图同样删掉(只删我们自己写的临时图, 绝不碰落盘的判据图)
            if os.path.basename(topview_path or "").startswith("zmax_main_960"):
                try:
                    os.remove(topview_path)
                except OSError:
                    pass
            v_primary = "NG" if dets else "OK"
            v_shadow = (sh or {}).get("verdict")
            v_union = "NG" if (v_primary == "NG" or v_shadow == "NG") else "OK"
            with _PIC_LOCK:
                _LAST_RESULT.clear()
                _LAST_RESULT.update({
                    "n": n, "t": time.time(), "detect_type": detect_type,
                    "origin": origin_path,
                    "topview": judge_path or topview_path,      # v7: topview = 判据图(老倪看的那张)
                    "model_input": topview_path,                # v9: 模型真正吃的那张(960x960, 同帧派生)
                    "model_input_kind": "960x960 方图(同帧派生, 检测完即删; 与 v6/v7 同口径)",
                    "model_input_md5": (dict(_LAST_MODELIN_META).get("md5") or ""),   # 🆕 v11: 与 /picture?kind=modelin 逐位同源
                    "judge": judge_path or "",
                    "defects": dets, "count": len(dets),
                    # v8: verdict = 并集(topview 口径 ‖ 影子口径 任一 NG 即 NG ⇒ 不漏判);
                    #     单口径结果也分别报, 便于攒同口径对照数据。
                    "verdict": v_union, "verdict_topview": v_primary, "verdict_shadow": v_shadow,
                    "shadow": sh,
                    "ms": round(dt_ms, 1),
                    "saved_incoming": result.get("saved_incoming", ""),
                })
            print("=" * 60 + "\n", flush=True)
        except Exception as e:
            print(f"【检测异常】{e}")
            traceback.print_exc()


def _ensure_detect_worker():
    global _detect_thread
    with _detect_lock:
        if _detect_thread is None or not _detect_thread.is_alive():
            _detect_thread = threading.Thread(target=_detect_worker_loop, daemon=True)
            _detect_thread.start()


def _sweep_temp(max_age_s=60):
    """清掉我们自己在 %TEMP% 里的残留临时图。

    只碰三个前缀(zmax_main_960_* / zmax_ab_judge960_* / zmax_ab_960_*), 且只删 60s 之前的
    —— 免得把"正在被检测器读的那一张"删掉(Windows 下删被占用的文件会失败, 也就自然跳过了)。
    """
    try:
        now = time.time()
        with _detect_lock:                      # 🆕 v12: 还在队列里等检测的那几张不能清
            _keep = {os.path.abspath(x) for it in _detect_queue for x in (it[0], it[4]) if x}
        for pat in ("zmax_main_960_*.png", "zmax_ab_judge960_*.png", "zmax_ab_960_*.png"):
            for p in glob.glob(os.path.join(TEMP_DIR, pat)):
                if os.path.abspath(p) in _keep:
                    continue
                try:
                    if now - os.path.getmtime(p) > max_age_s:
                        os.remove(p)
                except OSError:
                    pass
    except Exception:                                                          # noqa: BLE001
        pass


_DETECT_Q_MAX = int(os.environ.get("AOI_DETECT_Q_MAX", "3"))   # 🆕 v12: 队列上限(挤压时丢最旧的)


def _enqueue_detect(model_path, origin_path, detect_type, judge_path=None, shadow_path=None):
    """入队: (模型实际吃的那张, 原图, 类型, 判据图, 影子临时图)。

    🆕 v12: 挤压时**丢最旧的**。为什么要: 页面会高频触发拍照, 而一次推理 ~1.6s ⇒ 队伍会越排越长,
    队伍里的临时图会被 _sweep_temp/下一轮覆盖清掉 ⇒ 检测器拿到的可能是个**已不存在的路径**。
    实测出现过"拍了没结果、/last_result 一直 404"的现场, 就是这么来的。丢最旧的 + 跳过失效项都能治。
    """
    # 🆕 v12: /crop_info 的"模型实际吃哪张"以**入队那一刻的真值**为准(唯一收口, 不会和 /last_result 打架)
    try:
        with _PIC_LOCK:
            _LAST_CROP_INFO["model_input_file"] = os.path.basename(model_path or "")
            _LAST_CROP_INFO["model_input_kind"] = "960x960 方图(同帧派生, 检测完即删)"
            _LAST_CROP_INFO["model_input_full"] = model_path or ""
    except Exception:                                                          # noqa: BLE001
        pass
    with _detect_lock:
        _detect_queue.append((model_path, origin_path, detect_type, judge_path, shadow_path))
        while len(_detect_queue) > _DETECT_Q_MAX:
            old = _detect_queue.pop(0)
            for _p in (old[0], old[4]):
                if _p and "zmax_" in os.path.basename(_p):
                    try:
                        os.remove(_p)
                    except OSError:
                        pass
            print("  ⚠️ 检测队列积压 ⇒ 丢掉最旧的一项(只保留最新 %d 个)" % _DETECT_Q_MAX)
    _ensure_detect_worker()


@app.route("/capture_detect", methods=["POST"])
def capture_detect_api():
    try:
        detect_type, channel_port = _resolve_detect_type_by_channel()
        if not detect_type:
            return jsonify({
                "code": 400,
                "msg": f"当前通道端口 {channel_port or '未知'} 未配置检测模型，可选端口: {sorted(PORT_TO_DETECT_TYPE.keys())}"
            }), 400

        print(f"\n===== 检测通道 {channel_port} · {CAM_DESC} =====")
        if not ensure_camera():
            return jsonify({"code": 500, "msg": "相机初始化失败"}), 500

        img_origin_path, img_topview_path = GrabAndSaveImage(save=True)   # 真检测: 落盘(模型要读文件)
        if img_origin_path is None or img_topview_path is None:
            print("⚠️ 抓帧失败, 尝试重连相机...")
            Close_Device()
            if ensure_camera():
                img_origin_path, img_topview_path = GrabAndSaveImage(save=True)
            if img_origin_path is None or img_topview_path is None:
                return jsonify({"code": 500, "msg": "图像抓取失败"}), 500

        print(f"   📸 已拍照 + 已规整裁剪, 投递检测队列 (不阻塞动作)")
        with _PIC_LOCK:
            _LAST_PIC.update({"origin": img_origin_path, "topview": img_topview_path, "t": time.time()})
        _prune_dir()                                # v5: 按保留上限清旧图(不检测时不再堆图)
        _enqueue_detect(_LAST_MODELIN or img_topview_path, img_origin_path, detect_type,
                        judge_path=img_topview_path, shadow_path=(_LAST_SHADOW or None))
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:
        print("==========接口异常完整堆栈==========")
        traceback.print_exc()
        try:
            StopGrabbing()
            Close_Device()
        except Exception:
            pass
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/picture", methods=["GET", "POST"])
def picture_api():
    """?kind=origin(默认,原始图)|crop(金手指拉长960方图)|natural(金手指原比例) · ?meta=1 返回JSON · ?grab=1 先抓一帧"""
    try:
        kind = (request.args.get("kind") or "origin").lower()   # origin|crop(判据图/内存帧)|natural|modelin(模型实际吃的那张)
        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            # v5: 取图默认**不落盘**(加 &save=1 才写盘) —— 不检测时不再堆图
            _sv = str(request.args.get("save", "")).lower() in ("1", "true", "yes")
            o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:      # v5.1: 与 /capture_detect 同口径 —— 冷启/空闲后首抓会失败, 重连再抓一次
                print("⚠️ grab 抓帧失败, 重连相机后重试…")
                Close_Device()
                if ensure_camera():
                    o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv, "t": time.time()})
        if kind == "modelin":                     # 🆕 v11: 模型实际吃的那张(= 喂 YOLO 的同一份像素)
            with _PIC_LOCK:
                _img = _LAST_MODELIN_IMG
                _meta = dict(_LAST_MODELIN_META)
            if _img is None:
                return jsonify({"code": 404, "msg": "尚无模型输入图: 先 POST /capture_detect"}), 404
            if str(request.args.get("meta", "")).lower() in ("1", "true", "yes"):
                return jsonify(_meta)
            ok_enc, buf = cv2.imencode(".png", _img)   # PNG 无损: 取回来解码后与喂进去的逐位相同
            if not ok_enc:
                return jsonify({"code": 500, "msg": "PNG 编码失败"}), 500
            resp = Response(buf.tobytes(), mimetype="image/png")
            resp.headers["X-Zmax-Modelin-Md5"] = str(_meta.get("md5", ""))
            resp.headers["X-Zmax-Modelin-HW"] = "%sx%s" % tuple(_meta.get("hw", ["?", "?"]))
            resp.headers["X-Zmax-Modelin-N"] = str(_meta.get("n", ""))
            return resp
        with _PIC_LOCK:
            snap = dict(_LAST_PIC)
        mem, mts = _mem_get(kind)
        if mem and not request.args.get("file"):
            return Response(mem, mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store",
                                     "X-Frame-Source": "memory", "X-Frame-Age-S": "%.3f" % (time.time() - mts)})
        if kind in ("origin", "raw"):
            path = snap.get("origin")
        elif kind in ("natural", "natural_crop"):
            nats = sorted(glob.glob(os.path.join(SAVE_ROOT_DIR, "Finger_CropNatural_W*_No_*.png")),
                          key=os.path.getmtime)
            path = nats[-1] if nats else None
        else:
            path = snap.get("topview")
        if not path:
            path = snap.get("origin") or snap.get("topview")
        if not path or not os.path.exists(path):
            return jsonify({"code": 404, "msg": "尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}), 404
        if request.args.get("meta") in ("1", "true", "yes"):
            return jsonify({"code": 200, "kind": kind, "file": os.path.basename(path),
                            "t": snap.get("t", 0), "size": os.path.getsize(path),
                            "origin": os.path.basename(snap.get("origin") or ""),
                            "topview": os.path.basename(snap.get("topview") or ""),
                            "crop_info": _LAST_CROP_INFO, "last_result": _LAST_RESULT})
        with open(path, "rb") as fp:
            data = fp.read()
        mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        return Response(data, mimetype=mt, headers={"Cache-Control": "no-store"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/last_result", methods=["GET"])
def last_result_api():
    with _PIC_LOCK:
        snap = dict(_LAST_RESULT)
    if not snap:
        return jsonify({"code": 404, "msg": "尚无检测结果"}), 404
    snap["code"] = 200
    return jsonify(snap)


@app.route("/param", methods=["GET", "POST"])
def cam_param():
    """🆕 v24 相机采集参数实时读写 (老倪 2026-10-08: 「你能按照你的经验, 调整一下曝光, 增益这样的参数么?」)

    GET  /param                           -> 当前生效值(曝光us/增益dB/Gamma/相机SN/型号)
    GET|POST /param?exposure=5000&gain=1  -> 现场实时下发, **不必重启服务**
      只调用相机 SDK 的 ExposureTime / Gain / Gamma 三个节点, 不动任何裁剪/判据/模型口径。
      重启服务后回到文件里的 EXPOSURE_US / GAIN_DB / GAMMA_VAL。
    """
    from flask import request
    want, bad = {}, []
    for k, node in (("exposure", "exposure_us"), ("gain", "gain_db"), ("gamma", "gamma_val")):
        v = request.args.get(k)
        if v not in (None, ""):
            try:
                want[node] = float(v)
            except (TypeError, ValueError):
                bad.append(k)
    if bad:
        return jsonify({"code": 400, "ok": False, "error": "参数不是数字: %s" % ",".join(bad)}), 400
    applied = {}
    # 🔴 2026-10-08 实测教训(务必读):
    #   ① 这台 OPT 相机在**采集过程中**写 ExposureTime/Gain **必失败**(SDK 返回非 0) —— 所以"改了曝光"
    #      其实一个字都没写进去(扫 10000/8000/6000 三档, 图逐位相同, 就是这么来的)。
    #   ② 想绕过 ① 去"StopGrabbing → 写 → StartGrabbing" **会把相机卡死**: 实测 StartGrabbing 不返回,
    #      此后所有抓图 40s 超时, 整路 10082 只能停服务重开相机(现场就发生过一次)。
    #   ⇒ 本路由**永不**停采集。只尝试直接写: 写不进就如实回报 ok=false, 并指向唯一可靠路径 ——
    #     改本文件里的 EXPOSURE_US / GAIN_DB / GAMMA_VAL 后重启服务(开机时序 = 未采集时写, 实测成功)。
    if "exposure_us" in want:
        applied["exposure_us"] = {"ok": bool(set_exposure(want["exposure_us"])), "want": want["exposure_us"]}
    if "gain_db" in want:
        applied["gain_db"] = {"ok": bool(set_gain(want["gain_db"])), "want": want["gain_db"]}
    if "gamma_val" in want:
        applied["gamma_val"] = {"ok": bool(set_gamma(want["gamma_val"])), "want": want["gamma_val"]}
    _fail = [k for k, v in applied.items() if not v.get("ok")]
    _hint = ""
    if _fail:
        _hint = ("相机在采集中拒绝写 %s (实测本机型只能在不采集时写) ⇒ 请改本文件里的常数并重启服务; "
                 "切勿尝试停采集再写 —— 本机型会卡死相机" % ",".join(_fail))
    return jsonify({"code": 200, "ok": not _fail, "applied": applied, "hint": _hint, "now": dict(_CAM_LIVE),
                    "file_defaults": {"exposure_us": EXPOSURE_US, "gain_db": GAIN_DB,
                                      "gamma_val": GAMMA_VAL},
                    "note": "只改相机采集参数(曝光/增益/Gamma); 重启服务回到 file_defaults"})


@app.route("/crop_info", methods=["GET"])
def crop_info_api():
    """最近一次金手指裁剪的规整度指标 (score/残余倾角/线残差/金覆盖率/角度扫描曲线)"""
    with _PIC_LOCK:
        snap = dict(_LAST_CROP_INFO)
    if not snap:
        return jsonify({"code": 404, "msg": "尚无裁剪记录"}), 404
    snap["code"] = 200
    snap["mode"] = GF_CROP_MODE
    snap["template"] = os.path.basename(TEMPLATE_PNG)
    return jsonify(snap)


@app.route("/region", methods=["GET"])
def region_api():
    """金手指【区域】信息(原始图坐标系): 定向框/四边形/外接框 + 对焦清晰度 focus + 裁剪质量
    —— 状态空间 YOLO 目标检测模块 / 机械臂伺服引导 直接消费这个接口
    ?grab=1 先抓一帧再返回 (不传则返回最近一次拍照的结果)"""
    try:
        if request.args.get("grab") in ("1", "true", "yes"):
            if not ensure_camera():
                return jsonify({"code": 500, "msg": "相机初始化失败"}), 500
            # v5: 取图默认**不落盘**(加 &save=1 才写盘)
            _sv = str(request.args.get("save", "")).lower() in ("1", "true", "yes")
            o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:      # v5.1: 与 /capture_detect 同口径 —— 冷启/空闲后首抓会失败, 重连再抓一次
                print("⚠️ grab 抓帧失败, 重连相机后重试…")
                Close_Device()
                if ensure_camera():
                    o, tv = GrabAndSaveImage(save=_sv)
            if o is None and tv is None:
                return jsonify({"code": 500, "msg": "抓帧失败"}), 500
            with _PIC_LOCK:
                _LAST_PIC.update({"origin": o, "topview": tv, "t": time.time()})
        with _PIC_LOCK:
            snap = dict(_LAST_REGION)
        if not snap:
            return jsonify({"code": 404, "msg": "尚无区域信息: 先 POST /capture_detect 或 GET /region?grab=1"}), 404
        snap["code"] = 200
        snap["mode"] = GF_CROP_MODE
        snap["template"] = os.path.basename(TEMPLATE_PNG)
        snap["target_note"] = "与示教基准的偏差由 tools/aoi_gold_servo.py 计算并下发 L2 运动"
        return jsonify(snap)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/storage", methods=["GET"])
def storage_api():
    """看存了多少图 / 占多少磁盘, 以及保留上限 (老倪: 不检测时别存那么多)。"""
    try:
        d = _dir_stat()
        d["code"] = 200
        d["keep_canon"] = KEEP_CANON
        d["keep_origin"] = KEEP_ORIGIN
        d["mem"] = {"crop_kb": round(len(_MEM.get("crop") or b"") / 1024.0, 1),
                    "origin_kb": round(len(_MEM.get("origin") or b"") / 1024.0, 1),
                    "age_s": round(time.time() - (_MEM.get("ts") or 0), 1)}
        return jsonify(d)
    except Exception as e:                                                    # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500


@app.route("/prune", methods=["POST", "GET"])
def prune_api():
    """清旧图: POST 真删(按保留上限), GET 只报告(不删)。"""
    try:
        before = _dir_stat()
        if request.method == "GET":
            return jsonify({"code": 200, "dry": True, "before": before})
        n = _prune_dir()
        after = _dir_stat()
        print("  【清理】删除 %d 张旧图; 现在 %d 张 / %.1fMB" % (n, after["files_total"], after["mb_total"]))
        return jsonify({"code": 200, "removed": n, "before": before, "after": after})
    except Exception as e:                                                    # noqa: BLE001
        return jsonify({"code": 500, "msg": str(e)}), 500


def run_flask(port=10082):
    app.run(host="0.0.0.0", port=int(port), debug=False)


def _already_serving(port, timeout=3.0):
    """v6.1: 该端口上是否已有 AOI 服务在应答(看 /storage 面, 只有 v5+ 才有)。
            用于启动自检 —— Windows 的 SO_REUSEADDR 会让第二个 socket 也 bind 成功,
            于是手动起的第二份会"看起来起来了", 然后被每分钟守护清掉(像自己退出)。"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/storage" % int(port), timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def _port_available(port):
    """启动前自检: 端口是否被占(通常是旧程序还在跑)。带 SO_REUSEADDR, 不会把 TIME_WAIT 误判成占用"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", int(port)))
        return True
    except OSError as e:
        print(f"❌ 端口 {port} 无法绑定: {e}")
        print(f"   → 通常是旧程序(如 v3)还占着 {PRODUCTION_PORT}; 先停掉它再启动本程序。")
        print(f"   → Windows 查占用: netstat -ano | findstr :{port}    再 taskkill /PID <pid> /F")
        return False
    finally:
        s.close()


if __name__ == "__main__":
    _port = int(os.environ.get("AOI_PORT") or PRODUCTION_PORT)
    if "--port" in sys.argv:
        _port = int(sys.argv[sys.argv.index("--port") + 1])
    # 通道→模型 映射按"实际运行的端口"注册 (产线固定 10082; 换端口自测时通道也不会报 400)
    PORT_TO_DETECT_TYPE[str(_port)] = "gf"
    print(f"金手指检测相机程序启动({VERSION})，端口{_port}，gf金手指模型，相机常驻模式；"
          f"裁剪={GF_CROP_MODE} 模板={os.path.basename(TEMPLATE_PNG)} "
          f"规范化={CANONICAL_W}x{'auto(保比例)' if KEEP_ASPECT else CANONICAL_H}")
    print(f"   通道映射: {PORT_TO_DETECT_TYPE}  (产线调用端口 = {PRODUCTION_PORT})")
    if _port != PRODUCTION_PORT:
        print(f"   ⚠️ 当前不是产线端口 {PRODUCTION_PORT}(仅在换端口自测时这样用); 产线请用 {PRODUCTION_PORT}")
    if _already_serving(_port):
        print(f"❌ 端口 {_port} 上已经有 AOI 服务在应答(/storage 200) —— 正式实例正在跑。")
        print("   → 本程序由计划任务托管(开机自启 + 每分钟自愈), **不要手动再起第二份**。")
        print(f"   → 要验证: curl -X POST http://127.0.0.1:{_port}/capture_detect   (GET 不触发动作)")
        sys.exit(3)
    if not _port_available(_port):
        sys.exit(1)
    get_cropper()      # 启动即加载模板 (缺模板只报警不影响启动)
    try:
        t_pre = threading.Thread(target=ensure_camera, daemon=True)
        t_pre.start()
    except Exception:
        pass
    _ensure_detect_worker()
    t = Thread(target=run_flask, args=(_port,))
    t.start()
    t.join()
