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

# 🆕 v30 层① (2026-10-09) 取像档位**持久化** —— 重启不丢档位:
#   病: 服务自启只跑 set_auto_off()+文件默认档(20000×8), **不读落盘** ⇒ 任何重启(部署/异常/保活)
#       都把现场档位(如点2 的 40000×8)打回默认, 判据图整幅变。此前只有部署器 ⑤b 会补, 覆盖不到普通重启。
#   修: 服务自己**落盘**当前生效档位 + 启动/重连时**按落盘复原**(完全不依赖部署脚本)。
#   落盘路径(工控机侧, 相对工作目录 D:\xspace\ultralytics_AOI, 可用 AOI_CAM_PARAM_PERSIST 覆盖):
#     zmax_data/aoi_v4/cam_param_persist.json  —— 与 4060 侧同名同格式 {"10082": {...}}
_CAM_PARAM_PERSIST = os.environ.get("AOI_CAM_PARAM_PERSIST") or os.path.join(
    HERE, "zmax_data", "aoi_v4", "cam_param_persist.json")
_RUN_PORT = str(PRODUCTION_PORT)      # __main__ 里按实际 --port 覆盖(与落盘键一致)

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


def _write_cam_param_persist(src="服务"):
    """把**当前实际生效**的取像档位写进本机落盘文件(供服务自启复原)。返回 bool。"""
    try:
        d = {}
        if os.path.exists(_CAM_PARAM_PERSIST):
            try:
                d = json.load(open(_CAM_PARAM_PERSIST, encoding="utf-8")) or {}
            except Exception:
                d = {}
        d[str(_RUN_PORT)] = {"exposure_us": float(_CAM_LIVE.get("exposure_us")),
                             "gain_db": float(_CAM_LIVE.get("gain_db")),
                             "profile": "", "src": str(src),
                             "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        _dir = os.path.dirname(_CAM_PARAM_PERSIST)
        if _dir and not os.path.isdir(_dir):
            os.makedirs(_dir, exist_ok=True)
        _tmp = _CAM_PARAM_PERSIST + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        os.replace(_tmp, _CAM_PARAM_PERSIST)
        _e = d[str(_RUN_PORT)]
        print("【档位落盘】%s ⇐ %gus×%gdB" % (_CAM_PARAM_PERSIST, _e["exposure_us"], _e["gain_db"]))
        return True
    except Exception as e:
        print("⚠️ 取像档位落盘失败: %r" % (e,))
        return False


def _restore_cam_param():
    """🆕 v30 层①: 服务自身启动/重连时按**本机落盘**档位复原(不靠部署脚本)。

    返回 True = 至少复原了一项; False = 无落盘/未复原。任何异常都吞掉(绝不影响启动)。"""
    try:
        if not os.path.exists(_CAM_PARAM_PERSIST):
            print("【档位复原】无落盘文件(%s) ⇒ 保持文件默认 %gus×%gdB"
                  % (_CAM_PARAM_PERSIST, EXPOSURE_US, GAIN_DB))
            return False
        d = json.load(open(_CAM_PARAM_PERSIST, encoding="utf-8")) or {}
        e = d.get(str(_RUN_PORT)) or {}
        ex, gn = e.get("exposure_us"), e.get("gain_db")
        if not ex and not gn:
            print("【档位复原】落盘无 %s 项 ⇒ 保持默认" % (_RUN_PORT,))
            return False
        ok = True
        if ex:
            ok = bool(set_exposure(float(ex))) and ok
        if gn:
            ok = bool(set_gain(float(gn))) and ok
        print("【档位复原】按落盘(%s, src=%s) exposure=%s gain=%s ⇒ ok=%s"
              % (e.get("ts"), e.get("src"), ex, gn, ok))
        return ok
    except Exception as ex:
        print("⚠️ 档位复原跳过(不影响启动): %r" % (ex,))
        return False


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
    _restore_cam_param()    # 🆕 v30 层①: 按**本机落盘**档位复原 —— 重启/重连不丢现场档位
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
# 🔴 键行带"带锁"状态: 上一次**成功**渲染用的键行带(治"判据图翻面", 见 _v21_render_core 内说明)。
#   模块级必须初始化 —— 只写 global 不初始化会在首帧抛 NameError(本轮踩过)。
_V21_BAND_PREV = None
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
_JUDGE_VER = "v36-gold19-cxwin-20261009"
   # v35: v34 + (a) 单键宽度门(死区块 1.6×中键宽..1.35×节距 不再整块拒收, 按"有/无内部凹陷"判 2 键 or 单键)
   #      (b) 救回趟(pass2, 仅 n1∈[11,16] 触发) 用更宽的重切分上限; 结果需 >n1 且 >=14 根且节距自洽才采纳。
   #      v33 的 keep-frame 抑制分支 / v34 的锚点两遍校验 / 19 根实线框全部保留。
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
_V23_KEY_HSTRETCH = 3.0        # v23 原值(参考序列逐位零回退用)
_V36_HSTRETCH = 3.0            # 🆕 v36: 新清晰画面的键高放大(只在 _V36_LIVE 时取代上值)
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


_V26_BAND_HOLD = {"band": None, "ts": 0.0, "thumb": None}   # 静止保持: 同一工件静止时按住行带(见 _v26_pick_band)
_V26_BAND_HOLD_S = 15.0                      # 保持有效期(s): 超过就按新候选重新认
_V26_BAND_TOL = 100                          # 新候选起点漂过这么多 px ⇒ 认为换件/换视角, 重新认
# 🆕 v30 层② (2026-10-09) 场景变化门: 帧内出现多个候选带时, 别一律取"最上簇"(伪结构常更靠上),
#   而是当**缩略图帧差小(同一静止工件)**时, 选**与上帧成功带重叠**的那一簇。缩略图帧差 > 该阈值才认"换件/换视角",
#   退回"最上簇"重新认。实测 16 帧静止序列缩略图帧差 0.96~1.9 ⇒ 阈值 6.0 只区分真换件(整幅重排, 差远超 6)。
_V30_SCENE_DIFF = 6.0


def _v26_pick_band(hits, met=None, prev=None, thumb=None):
    """挑出**真正的齿排那一段行带** —— 治「判据图一闪一闪/不断跳动」。

    🔴 真因(2026-10-08/09 离线冻结真帧复现, 与亮度无关: p50 恒 27 仍在跳):
      老写法 `ky0=min(y0)/ky1=max(y1)` 把**所有**命中窗并成一条带。同一批帧里有 2~3 个命中窗:
      真齿排(y≈1550-1619, 节距 70~72) **和** 它下方过曝亮面上的假周期结构(y≈1650-1699, 节距 46)。
      远窗一并进来, 行带就从 50 行涨到 130/150 行 ⇒ 判据图按带渲染 ⇒ 齿带纵向漂 **240px**、
      高度 50~150 行来回变 = 肉眼"一跳一跳"。

    ⚠️ 本地会话的"带锁并集"(_V21_BAND_PREV) 思路对(要跨帧稳定)但方向反了: **并集只会更宽**,
      一旦把假结构并进来, 就永久停在宽带上(实测当前场景行带仍在 2 种之间翻、根数 7↔15)。
      ⇒ 本版改为"**取最上簇 + 只与锚窗重叠**"(齿排是最靠上的周期结构), 再叠静止保持。

    两条规则(实测支撑):
      ① 金手指是最靠上的那条周期结构 ⇒ 取最上面那一簇, 簇内只收与锚窗重叠的窗(不让远端窗撑长带)。
      ② 同一个工件静止 ⇒ 行带不该帧间变。保持上一次的行带, 除非新候选起点漂 > _V26_BAND_TOL。
    实测(12 帧冻真帧, 当前场景): 行带 2 种 ⇒ **1 种**; 根数 7/15 ⇒ **恒 15**; 帧间像素差 6.6 ⇒ 5.1。
    """
    hs = sorted(hits, key=lambda h: int(h["y0"]))
    clusters, cur = [], [hs[0]]
    for h in hs[1:]:
        if int(h["y0"]) - int(cur[-1]["y1"]) <= _V21_WIN_H:      # 相邻/重叠 ⇒ 同一簇
            cur.append(h)
        else:
            clusters.append(cur)
            cur = [h]
    clusters.append(cur)

    def _cluster_span(cl):
        a, b = int(cl[0]["y0"]), int(cl[0]["y1"])
        for h in cl[1:]:                    # 只收与已选段重叠的窗
            if int(h["y0"]) <= b:
                b = max(b, int(h["y1"]))
        return a, b

    top = clusters[0]                       # 默认: 最上面那一簇 = 齿排
    _gate = "top"
    held = _V26_BAND_HOLD.get("band")
    held_thumb = _V26_BAND_HOLD.get("thumb")
    if len(clusters) > 1 and held is not None:
        # 🆕 v30 层②: 场景变化门 —— 缩略图帧差小(同一静止工件)时, 伪结构(更靠上)可能这一帧冒头;
        #   此时**不取最上簇**, 改选与"上帧成功带"重叠的那一簇(与上帧真键排一致的候选),
        #   避免每帧在 y≈1260-1400 与 y≈1550-1639 之间翻。帧差大 = 真换件/换视角 ⇒ 回落"最上簇"重认。
        _static = False
        if thumb is not None and held_thumb is not None:
            try:
                _static = float(np.abs(np.asarray(thumb, np.float32)
                                       - np.asarray(held_thumb, np.float32)).mean()) <= _V30_SCENE_DIFF
            except Exception:
                _static = False
        if _static:
            _ov = [(cl, _cluster_span(cl)) for cl in clusters]

            def _overlap_len(ab):
                return max(0, min(int(ab[1]), int(held[1])) - max(int(ab[0]), int(held[0])) + 1)

            _cand_ov = [(cl, ab, _overlap_len(ab)) for cl, ab in _ov if _overlap_len(ab) > 0]
            if _cand_ov:
                top = max(_cand_ov, key=lambda t: t[2])[0]
                _gate = "overlap"
    y0, y1 = _cluster_span(top)
    cand = [y0, y1]
    now = time.time()
    if (held and (now - float(_V26_BAND_HOLD.get("ts") or 0.0)) < _V26_BAND_HOLD_S
            and abs(int(held[0]) - y0) <= _V26_BAND_TOL):
        y0, y1 = int(held[0]), int(held[1])
        if met is not None:
            met["band_hold"] = {"hold": [y0, y1], "cand": cand}
    else:
        _V26_BAND_HOLD["band"] = [y0, y1]
        _V26_BAND_HOLD["ts"] = now
    if thumb is not None:
        _V26_BAND_HOLD["thumb"] = np.asarray(thumb, np.float32).copy()
    if met is not None:
        met["band_pick"] = {"clusters": len(clusters), "hits": len(hs), "cluster_hits": len(top),
                            "band": [y0, y1], "h": int(y1 - y0 + 1), "cand": cand, "gate": _gate}
    return y0, y1


# ═══ v32 (2026-10-09) 几何自适应取带: 列自相关"相位锚点" ══════════════════════════
#   病(当前位姿实测): `_v26_pick_band` 取带 **比真键排高 ~100–140px** ⇒ 只切到键排上缘,
#   数出 4~12 根(真值 19); 节距估计也因此偏成 95px。真键排(用列自相关扫出来的唯一周期带)
#   在**取带下方**, 而取带落在"连接器壳体暗面"上(该处无列周期)。
#   修: 用列自相关在**整幅**扫出唯一周期带(pitch 55..90px、跨度≈19×pitch)当**相位锚点**,
#   仅当"锚点带与当前取带**几乎不重叠**"且锚点足够强时, 才把取带钉到锚点带。
#   铁律(前视零回退): 前视取带本就落在真键排 ⇒ 锚点带与当前带重叠 ⇒ **不触发** ⇒ 逐位不变。
#   只动"取哪一行带", 不碰 crop/warp/get_cropper/_region_payload。
_V32_ON = True
_V32_WIN_H = 110          # 锚点窗口高(px, 全分辨率) —— 覆盖键排高度
_V32_STEP = 5             # 纵向扫描步长
_V32_CUT_K = 201          # 平场大窗(≈3×节距): 去掉低频亮度梯度, 只留键列周期
_V32_PITCH_LO, _V32_PITCH_HI = 55, 90
_V32_AC_MIN = 0.15        # 去低频后 ACF 峰值门槛(实测真键排 ~0.40, 其余 ≤0.23/多为负)
_V32_CUR_MAX = 0.15       # 当前取带的周期分低于此 ⇒ 判"没落在键排上" ⇒ 才允许钉带(否则一字不动)
_V32_OVERRIDE_ON = True   # 钉带总开关
_V32_TWOPASS_ON = True    # 两遍校验总开关(pass1≠19 且锚点强 ⇒ 用锚点带重渲, 恰好19才采用)
_V32_ATTEMPT_LO = 12      # pass1 键数 < 此值(或 > 19) 才认为"明显不对" ⇒ 才试重渲(保其它视角逐位不变)
_V32_AMP_MIN = 6.0        # 去低频剖面的**幅度**门槛(px·灰度): 平坦区(过曝白板/暗壳)自相关是数值假象
_V32_MIN_OVL_FRAC = 0.35  # 与当前取带重叠 < 该比例(×锚点带高) 才覆盖
_V32_SLOT_CC = 0.45       # 格心"局部平移相关"门槛(真键 ≥0.7; 边缘金属条 ≤0.2) —— 低于此判为边缘槽


# 🆕 v36 (2026-10-09 现场镜头对焦修好后) —— 新清晰画面适配
#   病: 列自相关原用**全宽**剖面; 新画面两侧大片亮/暗背景把键排周期淹没(真键排带全宽 ACF 变负,
#      中心窗 ACF 0.72@lag71) ⇒ 取带选错行窗、节距估成 254 ⇒ 根数乱。真节距实测 70~71px。
#   修: (1) 所有列自相关改在**中心 x 窗**上算(两侧背景不进剖面);
#       (2) 键行窗加**中心窗周期门**(平场去低频 ACF 峰 < 门 ⇒ 判"这条不是键排" ⇒ 不收);
#       (3) 节距候选/回退**掐死**在真键排量级, 拒绝任何 >cap 的节距(治 254/384 假节距)。
_V36_XWIN_FRAC = 0.5           # 中心 x 窗宽度 / 画幅宽(键排恒在画面中部)
_V36_ON = True                 # v36 总开关(关掉 ⇒ 逐位退回 v35 行为)
# 🔴 只在"镜头对焦修好后"的**新清晰画面**上启用 v36 逻辑。判据 = 键排区的**锐度**
#   (中心窗 Laplacian 方差): 实测 参考序列 ≤39.8(l3 3.4 / frozen 1.2 / live 12.7 / pt2 39.8)
#   vs 修好对焦后 81~86 ⇒ 门卡在 60(空档 ~2 倍)。关着的帧**逐位退回 v35**(参考零回退由结构保证)。
_V36_MIN_SHARP = 60.0
_V36_MIN_P50 = 85.0            # 且键排区要够亮: 实测新画面 p50=86~101, 全部参考组 ≤84
_V36_LIVE = False              # 由 _v21_render_core 按当帧中心窗锐度置位
_V36_LAST_BAND = None          # _v36_lattice 命中时写回所采用的行带 (y0,y1)
_V36_LATTICE_INFO = None       # 命中时的逐根相位验证数字
_V36_WIN_AC_MIN = 0.35         # 键行窗的"中心窗 ACF 峰"门(实测真键排 0.68~0.85, 伪结构 <0.25/多为负)
_V36_PITCH_HARD_CAP = 120.0    # 🔴 任何节距候选/回退超过此值 ⇒ 判为非键排结构, 一律拒绝
_V36_PITCH_LO, _V36_PITCH_HI = 62.0, 80.0   # 真键排节距带(实测 70~71)
_V36_SLOT_LO, _V36_SLOT_HI = 430.0, 1980.0  # 键排横向存在区(实测 567~1841, 两侧留余量)
_V36_GAP_MIN = 12.0            # 抗凹陷"无假框"衬度门(格内亮脊 − 格间谷; 灰度级): 正确栅格恒为正


def _v36_cxwin(w, frac=None):
    """🆕 v36: 列自相关用的**中心 x 窗** —— 真机判据画面里金手指键排总在画面中部,
    而两侧的大片亮/暗背景会把**全宽**列剖面的自相关彻底淹掉(实测新清晰画面: 真键排带
    全宽 ACF 峰值 -0.09 <0, 中心窗 ACF 0.72@lag71)。全宽剖面对新画面失效 ⇒ 取中心窗。
    返回 (x0, x1)。
    """
    w = int(w)
    f = float(_V36_XWIN_FRAC) if frac is None else float(frac)
    hw = int(w * f / 2.0)
    c = w // 2
    return max(0, c - hw), min(w, c + hw + 1)


def _v36_band_acf(ga, y0, y1, lo=55, hi=95, K=61):
    """🆕 v36: 中心 x 窗 + 去低频的列自相关峰值 → (score, lag)。无周期返回 (0.0, 0)。"""
    try:
        y0 = max(0, int(y0))
        y1 = min(int(ga.shape[0]) - 1, int(y1))
        if y1 - y0 < 12 or ga.shape[1] < 64:
            return 0.0, 0
        x0, x1 = _v36_cxwin(ga.shape[1])
        prof = ga[y0:y1 + 1, x0:x1].astype(np.float32).mean(axis=0)
        k = int(K) | 1
        bg = cv2.blur(prof.reshape(1, -1), (k, 1)).ravel()
        pd = prof - bg
        pd = pd - pd.mean()
        if float(pd.std()) < 2.0:
            return 0.0, 0
        ac = np.correlate(pd, pd, "full")[len(pd) - 1:]
        a0 = float(ac[0])
        if a0 <= 1e-6:
            return 0.0, 0
        seg = ac[int(lo):int(hi) + 1] / a0
        if seg.size == 0:
            return 0.0, 0
        kk = int(seg.argmax())
        return round(float(seg[kk]), 3), int(lo) + kk
    except Exception:                                                        # noqa: BLE001
        return 0.0, 0


def _v36_lattice(ga, ky0=0, ky1=0, merged=None, x0=520, x1=1950, want=None):
    """🆕 v36 权威键排栅格: **逐行带扫描**的组合梳拟合(节距+相位) + 径向半高宽边缘门。

    为什么要这一层: 新清晰画面下 v21 的"亮列分块"会在**每根键的暗凹陷(notch)**处分叉 ⇒ 段数/
    宽度帧间抖, 而两端整块金属边(宽)与真键(窄)又同为"亮", 老口径认不出 ⇒ 根数 15/18/20 乱跳。
    本函数不依赖任何会抖的中间量, 只依赖两个**物理自明**的事实:
      (1) 真键排是**窄**亮脊(半高全宽 6~13px)沿节距 70.75px 规则排布; 两端整块金属是**宽**亮区(半高宽 22~110px)。
      (2) 键排所在行带在 y 上是一个窄条; 而"金属焊盘"行带同样有周期但亮脊**宽得多**。
    做法: 对每个 60 行带做梳拟合 ⇒ 取"径向半高宽"定义下的**最长连续窄槽段**; 只有段长恰为 want(19)
    且该带中心窗 ACF>=0.55(确有 70px 周期)才接受; 多家命中取 ACF 最高的带。命中即返回逐槽矩形。
    实测(2048x2448 新画面): 5/5 现役帧 + 全部清晰参考帧都给出 y0=880、pitch 70.75、19 槽 567..1841。

    ⚠️ 只产出"取哪几列"(rects), 不碰 crop/warp/get_cropper/_region_payload 等模型输入函数。
    """
    try:
        g = np.asarray(ga)
        if g.ndim == 3:
            g = g[:, :, 0]
        H, W = g.shape[:2]
        _want = int(want) if want else 19
        if H < 120 or W < 600:
            return None
        # ---- 1. 逐带 ACF 预筛(中心窗, 去低频) ----
        _bands = []
        for _y0 in range(0, max(1, H - 60), 10):
            _pd = _v36_cxprof(g, _y0, _y0 + 59, 61)
            if _pd is None:
                continue
            _sc, _lag = _v36_pd_acf(_pd, _V36_PITCH_LO, _V36_PITCH_HI)
            if _sc >= 0.55:
                _bands.append((_sc, _y0, _lag))
        _bands.sort(reverse=True)
        # ---- 2. 对 ACF 最强的若干带做梳拟合, 只有"窄槽连续段长 = want"才接受 ----
        for _sc, _y0, _lag in _bands[:30]:
            for _Pst, _phst in ((0.5, 2.0), (0.05, 0.5)):
                _out = _v36_combfit(g, _y0, _y0 + 59, _Pst, _phst)
                if _out is None:
                    continue
                _P, _ph, _xs, _pd = _out
                _rn = _v36_narrow_run(_xs, _pd)
                if _rn is None or (_rn[1] - _rn[0] + 1) != _want:
                    break                      # 粗口径已否决该带 ⇒ 换带(不再细拟合)
                if _Pst == 0.05:               # 细口径确认通过
                    _slots = [int(_xs[i]) for i in range(_rn[0], _rn[1] + 1)]
                    _d = np.diff(sorted(_slots))
                    _mad = float(np.median(np.abs(_d - np.median(_d)))) if _d.size else 0.0
                    if _mad > 8.0:             # 节距不齐 ⇒ 不是真键排
                        break
                    # 🔴 相位锁定(治"框压在键缝里"): 把每个槽吸附到**该带全宽剖面的局部亮脊**
                    #   (±0.3×节距内取 argmax), 再逐根验证"脊亮度 > 两侧半格处亮度"。
                    _pf = _v36_fwprof(g, _y0, _y0 + 59)
                    if _pf is None:
                        break
                    _Pm = float(np.median(_d)) if _d.size else float(_P)
                    _sn = []
                    for _s in _slots:
                        _lo = max(0, int(_s - 0.30 * _Pm))
                        _hi = min(_pf.size - 1, int(_s + 0.30 * _Pm))
                        _sn.append(int(_lo + int(np.argmax(_pf[_lo:_hi + 1]))))
                    _ph = _v36_phase_check(_pf, _sn, _Pm)
                    if _ph is None or (not _ph["all_ok"]):
                        break                  # 相位对不上(仍有框压缝) ⇒ 否决, 换带
                    _kw = 0.66 * _Pm
                    _kw = max(18.0, min(_kw, 1.2 * _P))
                    global _V36_LAST_BAND, _V36_LATTICE_INFO
                    _V36_LAST_BAND = (int(_y0), int(_y0 + 59))
                    _V36_LATTICE_INFO = dict(_ph)
                    _V36_LATTICE_INFO.update({"band": [int(_y0), int(_y0 + 59)], "pitch": round(_Pm, 2)})
                    return [(int(round(s - _kw / 2.0)), int(round(s + _kw / 2.0))) for s in _sn]
        return None
    except Exception:                                                        # noqa: BLE001
        return None


def _v36_cxprof(g, y0, y1, K=61):
    """中心 x 窗上、去低频的列剖面(供 ACF 用)。"""
    try:
        w = g.shape[1]
        a, b = _v36_cxwin(w)
        prof = g[y0:y1 + 1, a:b].astype(np.float32).mean(axis=0)
        bg = cv2.blur(prof.reshape(1, -1), (int(K) | 1, 1)).ravel()
        pd = prof - bg
        return pd - pd.mean()
    except Exception:                                                        # noqa: BLE001
        return None


def _v36_pd_acf(pd, lo, hi):
    """归一化自相关在 [lo,hi] 的峰值 → (score, lag)。"""
    try:
        n = pd.size
        p = np.concatenate([pd, np.zeros_like(pd)])
        F = np.fft.rfft(p)
        ac = np.fft.irfft(F * np.conj(F))[:n]
        ac = ac / (float(ac[0]) + 1e-9)
        a, b = int(lo), int(hi)
        seg = ac[a:b + 1]
        if seg.size == 0:
            return 0.0, 0
        k = int(seg.argmax())
        return float(seg[k]), a + k
    except Exception:                                                        # noqa: BLE001
        return 0.0, 0


def _v36_combfit(g, y0, y1, Pstep, phstep):
    """全宽列剖面上拟合"节距+相位"(梳), 返回 (P, ph, slot_xs, pd) 或 None。"""
    try:
        prof = g[y0:y1 + 1, :].astype(np.float32).mean(axis=0)
        bg = cv2.blur(prof.reshape(1, -1), (301, 1)).ravel()
        pd = prof - bg
        pd = pd - pd.mean()
        W = pd.size
        best = None
        for P in np.arange(66.0, 75.001, Pstep):
            for ph in np.arange(0.0, P, phstep):
                xs = np.arange(ph, W, P)
                xs = xs[(xs >= _V36_SLOT_LO) & (xs <= _V36_SLOT_HI)].astype(int)
                if xs.size < 10:
                    continue
                v = pd[xs]
                sc = float(v.mean() - 0.5 * v.std())
                if best is None or sc > best[0]:
                    best = (sc, float(P), float(ph))
        if best is None:
            return None
        _, P, ph = best
        xs = [int(round(x)) for x in np.arange(ph, W, P)
              if _V36_SLOT_LO <= x <= _V36_SLOT_HI]
        if len(xs) < 10:
            return None
        return P, ph, xs, pd
    except Exception:                                                        # noqa: BLE001
        return None


def _v36_fwprof(g, y0, y1):
    """该行带的**全宽**列亮度剖面(用于相位锁定/逐根验证)。"""
    try:
        return g[y0:y1 + 1, :].astype(np.float32).mean(axis=0)
    except Exception:                                                        # noqa: BLE001
        return None


def _v36_phase_check(pf, slots, P):
    """逐根验证"框心(亮脊) > 框缝(两侧半格处)"。返回 {all_ok, boxes:[{x,bar,gap,diff}], n_bad}。

    ⚠️ 这是**唯一**能证明"框没压在键缝里"的判据: 数量对 + 节距对, 相位仍可能错半格。
    """
    try:
        rows = []
        n_bad = 0
        hw = max(3, int(0.10 * P))
        gmin = max(1, int(0.42 * P))
        gmax = max(2, int(0.58 * P))
        W = pf.size
        for x in slots:
            bar = float(pf[max(0, x - hw):min(W, x + hw + 1)].mean())
            gaps = []
            for sgn in (-1, 1):
                a = int(x + sgn * gmin)
                b = int(x + sgn * gmax)
                lo, hi = min(a, b), max(a, b)
                if lo < 0 or hi >= W:
                    continue
                w = pf[lo:hi + 1]
                gaps.append(float(w.min()))
            gap = min(gaps) if gaps else 0.0
            diff = bar - gap
            if diff <= 0.0:
                n_bad += 1
            rows.append({"x": int(x), "bar": round(bar, 1), "gap": round(gap, 1), "diff": round(diff, 1)})
        return {"all_ok": bool(rows and n_bad == 0), "n_bad": int(n_bad),
                "n": len(rows), "boxes": rows}
    except Exception:                                                        # noqa: BLE001
        return None


def _v36_narrow_run(xs, pd):
    """径向半高全宽 < max(1.6×中位, 16px) 的槽判为"真键", 返回最长连续段 (i0,i1) 或 None。

    真键: 亮脊在 ±半高宽内就落到谷 ⇒ 窄;  两端整块金属: 亮区横跨 ~20~110px ⇒ 宽被剔。
    """
    try:
        W = pd.size
        ws = []
        for x in xs:
            half = 0.5 * pd[x]
            a = x
            while a > 0 and pd[a - 1] > half:
                a -= 1
            b = x
            while b < W - 1 and pd[b + 1] > half:
                b += 1
            ws.append(b - a + 1)
        ws = np.asarray(ws, dtype=np.float64)
        med = float(np.median(ws))
        thr = max(1.6 * med, 16.0)
        ba = bb = -1
        a = last = -1
        for i, k in enumerate(ws <= thr):
            if not k:
                continue
            if a < 0:
                a = last = i
            elif i == last + 1:
                last = i
            else:
                if last - a > bb - ba:
                    ba, bb = a, last
                a = last = i
        if a >= 0 and last - a > bb - ba:
            ba, bb = a, last
        return (ba, bb) if ba >= 0 else None
    except Exception:                                                        # noqa: BLE001
        return None



def _v35_band_pitch(ga, y0, y1, lo=58, hi=96):
    """🆕 v35: **带内列自相关**峰值 → 真键排节距。

    为什么不用 uniformize 的"段间中位差"(v21 老口径): 那个量随**分块粘连程度**漂 —— 同一个
    静止场景实测在 72.5/78/83.5/88.5 之间跳。节距一漂, 栅格槽就落到键与键的**缝**上 ⇒ 框虽然
    数量对但**位置错**(实测 pitch=88 时槽心衬度出现 -54/-45 的负值 = 框压在缝里)。
    带内(只有几十行)去低频列自相关对同一场景稳定得多。

    🆕 v36: 全宽剖面在**新清晰画面**上会被两侧背景淹掉(真键排全宽 ACF 变负) ⇒ 全宽取不到
    可靠周期时, 退回**中心 x 窗**再取一次(中心窗只留键排, ACF 恢复)。全宽已够可靠(>=门)的
    帧**一字不动**(参考序列零回退由结构保证)。
    返回 (pitch, score); 无可靠周期返回 (0.0, -1.0)。
    """
    try:
        y0 = max(0, int(y0))
        y1 = min(int(ga.shape[0]) - 1, int(y1))
        if y1 - y0 < 12 or ga.shape[1] < 64:
            return 0.0, -1.0
        prof = ga[y0:y1 + 1, :].astype(np.float32).mean(axis=0)
        k = 61 | 1
        bg = cv2.blur(prof.reshape(1, -1), (k, 1)).ravel()
        pd = prof - bg
        pd = pd - pd.mean()
        if float(pd.std()) < 2.0:                # 平坦带(白板/暗壳): 自相关是数值假象
            return 0.0, -1.0
        ac = np.correlate(pd, pd, "full")[len(pd) - 1:]
        a0 = float(ac[0])
        if a0 <= 1e-6:
            return 0.0, -1.0
        seg = ac[int(lo):int(hi) + 1] / a0
        if seg.size == 0:
            return 0.0, -1.0
        kk = int(seg.argmax())
        _ph, _ps = float(int(lo) + kk), round(float(seg[kk]), 3)
        # 🆕 v36: 全宽不可靠 ⇒ 中心窗兜底(只在新清晰画面/背景淹掉键排时才会走到; 参考序列不触发)
        if _V36_LIVE and _ps < _V35_AC_MIN:
            _sc, _lag = _v36_band_acf(ga, y0, y1, lo, hi, k)
            if _sc > _ps:
                _ph, _ps = float(_lag), _sc
        return _ph, _ps
    except Exception:                                                        # noqa: BLE001
        return 0.0, -1.0


def _v32_win_score(ga, yc):
    """中心 yc 的行窗口的(去低频)列自相关峰值 score(正=有键列周期) 与 lag。"""
    h, w = ga.shape
    wh = int(_V32_WIN_H)
    y0 = int(yc) - wh // 2
    y1 = y0 + wh - 1
    if y0 < 0 or y1 >= h:
        return None, None
    K = int(_V32_CUT_K) | 1
    # 🆕 v36: 全宽剖面在新清晰画面上被两侧背景淹没 ⇒ 改在**中心 x 窗**上算(键排恒在画面中部)。
    #   非 v36 画面(参考序列) ⇒ 保持全宽, 逐位退回 v35。
    if _V36_LIVE:
        _cx0, _cx1 = _v36_cxwin(w)
    else:
        _cx0, _cx1 = 0, w
    prof = ga[y0:y1 + 1, _cx0:_cx1].astype(np.float32).mean(axis=0)
    bg = cv2.blur(prof.reshape(1, -1), (K, 1)).ravel()
    pd = prof - bg
    pd = pd - pd.mean()
    if float(pd.std()) < _V32_AMP_MIN:      # 平坦区(白板/暗壳): 自相关是数值假象 ⇒ 无周期
        return None, None
    ac = np.correlate(pd, pd, "full")[len(pd) - 1:]
    ac0 = float(ac[0])
    if ac0 <= 1e-6:
        return None, None
    seg = ac[_V32_PITCH_LO:_V32_PITCH_HI + 1] / ac0
    if seg.size == 0:
        return None, None
    k = int(seg.argmax())
    return float(seg[k]), float(_V32_PITCH_LO + k)


def _v32_acf_score(ga, yc):
    """最终取带中心的周期分 —— 判"当前带是否已落在键排周期上"。无周期返回 -1。"""
    sc, _lag = _v32_win_score(ga, yc)
    return -1.0 if sc is None else sc


def _v32_band_score_robust(ga, ky0, ky1):
    """当前取带的周期分(在带中心 ±40px 内取最大, 抗单点抖动)。

    真键排(任意姿位)该值高; 取带落到壳体/过曝白板时该值低 ⇒ 才允许 v32 修正。
    其它姿位若已取在键排上 ⇒ 值高 ⇒ v32 一字不动(降级为原始行为)。
    """
    try:
        c = (int(ky0) + int(ky1)) // 2
        h = ga.shape[0]
        best = -1.0
        for yc in range(max(0, c - 40), min(h - 1, c + 40) + 1, 5):
            best = max(best, _v32_acf_score(ga, yc))
        return best
    except Exception:                                                       # noqa: BLE001
        return -1.0


def _v32_anchor_band(ga, met=None):
    """列自相关横扫整幅 → 唯一周期带 (相位锚点)。

    对每个候选中心 yc: 取 [yc-WH/2, yc+WH/2] 行的**列亮度剖面**, 平场(减大窗均值)去低频后
    自相关; 真键排在 lag≈节距 处给出**正峰**(实测 0.40@lag71), 过曝白板/暗壳为平/负。
    ⚠️ 必须配 amplitude 门: 平坦区自相关是数值假象(实测过曝白板 normalized peak 可达 0.46 但 std≈0.5)。
    返回 (y0, y1, pitch, score) 或 None。
    """
    if not _V32_ON:
        return None
    h, w = ga.shape
    wh = int(_V32_WIN_H)
    if h < wh + 4 or w < 64:
        return None
    best = None
    for yc in range(wh // 2, h - wh // 2 + 1, int(_V32_STEP)):
        sc, lag = _v32_win_score(ga, yc)
        if sc is None or sc < _V32_AC_MIN:
            continue
        if best is None or sc > best[0]:
            best = (sc, yc - wh // 2, yc + wh // 2 - 1, lag)
    if best is None:
        return None
    sc, y0, y1, lag = best
    if met is not None:
        met["v32_autocorr"] = {"win_h": wh, "score": round(sc, 3),
                               "band": [int(y0), int(y1)], "pitch": round(lag, 1)}
    return (int(y0), int(y1), lag, sc)


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
                # 🆕 v36: 键行窗必须**在中心 x 窗上真有键列周期**(平场去低频 ACF 峰)。
                #   治"取带选错行窗": 新清晰画面里键排**上缘的竖直边缘**也凑出 >=6 组规则亮列
                #   (实测窗 [840,889] 伪间距 34.5px), 但它们**没有 70px 周期**(ACF 为负) ⇒ 被此门剔掉。
                #   非 v36 画面(参考序列) ⇒ 门关闭, 逐位退回 v35 行为。
                _ac, _acl = 0.0, 0
                if _V36_LIVE:
                    _ac, _acl = _v36_band_acf(g, y, y + _V21_WIN_H - 1, 55, 95, 61)
                if (not _V36_LIVE) or _ac >= _V36_WIN_AC_MIN:
                    hits.append({"y0": int(y), "y1": int(y + _V21_WIN_H - 1),
                                 "n_seg": int(len(segs)), "pitch_px": round(med, 1),
                                 "jitter_px": round(mad, 1), "ac": _ac, "ac_pitch": _acl})
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


# ═══ v30 层③ (2026-10-09) 列剖面**低频背景归一(平场)后裂块** ═══
#   病(f14/f15 右端): 亮度梯度把"键间暗缝"的 cf(亮列占比)抬高(实测右端基线 cf 0.72~0.80, 左端只 0.30)
#   ⇒ 2~3 根被冲糊的真键粘成一块 **w≈201~204px(≈2.8×节距)** 的过宽块 ⇒ 过宽判 TOOWIDE ⇒
#   **整块丢弃** ⇒ 认领跨度右端缩短 ⇒ 缺齿(f14 缺 3 根 / f15 缺 6 根)。
#   修: 对**过宽块**做平场 —— ff = cf / blur(cf, ~3×节距)(键亮而局部凸 ⇒ ff>1, 暗缝 ⇒ ff<1);
#   再按**已建立的节距/相位栅格**把块**裂开**: 每格槽心须亮(ff>=FF_KEY) 且相邻槽之间须有凹陷
#   (ff 谷 <= FF_NOTCH)才认领这些格。**纯增**: 只把原先"整块丢弃"里的**真键**找回来, 绝不改宽块以外的
#   任何判据 ⇒ 不引入新的假齿(不满足形状的块仍整块丢弃)。
_V30_SPLIT_ON = True
_V30_SPLIT_FF_KEY = 0.90     # 槽心平场值下限(键 ⇒ ff 明显 >1)
_V30_SPLIT_FF_NOTCH = 0.80   # 槽间中点平场值上限(暗缝 ⇒ ff 明显 <1)
_V30_SPLIT_WMAX = 4.5        # 只裂 <= 该倍数×节距 的块(更宽 = 连接器端/背景, 一律不裂)
_V30_SPLIT_MAXSLOTS = 4      # 单块最多裂成几根(防失控)

# ═══ v35 (2026-10-09) 现役位姿"分不开"救回: 单键宽度门 + 救回趟重切分 ══════════════════
#  真帧取证(工位现役 y[1130,1189]): 真键排周期性成立(pitch≈70.5, x≈610..2020 共约 20~21 格),
#  但 pass1 只给 10~12 根。逐槽局部衬度(用本帧实测节距对齐栅格)在 y≈1135~1180 全格 +40~+128 ⇒
#  **行带内可分**(不是照明/对焦的物理极限), 丢根发生在**分块资格门**:
#    · 死区块(1.6×中键宽 < w < 1.35×节距, 实测 77~99px)被整块拒收 —— 它其实是"整键"或"键+亮缝";
#    · 更宽的粘连块(271px≈4 键) 走裂块逻辑, 但默认裂块门(ff 阈值)太严 ⇒ 整块丢弃。
#  修: ① `_v21_uniformize` 的**死区块**不再一刀拒收 —— 改判: 有内部凹陷(notch) 且跨 2~3 格 ⇒ 认 2~3 格;
#        否则(跨 ≤1 格) ⇒ 按**单键**认领最近格。窄单键/宽背景块的行为**一字不变**。
#      ② 救回趟(pass2)另给一档更宽的裂块上限(ff_key/notch/wmax), 把被糊住的粘连块找回;
#        两个改动都**只在显式带(=救回趟)**启用 ⇒ pass1 与在役逐位一致。
_V35_ON = True
_V35_N_LO, _V35_N_HI = 3, 16    # pass1 键数落在该区间才试救回(≥17 视为已分离好; 采纳另有严闸兜底)
_V35_SINGLE_MAX = 1.30          # 死区块当"单键"的最大宽度(×中位节距)
_V35_SPLIT_MAXSLOTS = 8         # 救回趟: 单块最多裂成几根(末闸=衬度门, 故放宽)
_V35_SPLIT_WMAX = 9.0           # 救回趟: 裂块宽度上限(×节距; 末闸=衬度门, 故放宽)
_V35_SPLIT_FF_KEY = 0.45        # 救回趟: 槽心平场下限(放宽; 末闸=衬度门)
_V35_SPLIT_FF_NOTCH = 0.95      # 救回趟: 槽间中点平场上限(放宽)
_V35_ADOPT_MIN = 14             # 救回结果至少这么多根才采纳(宁少不假)
_V35_CTR_MIN = 8.0              # 采纳闸: 每个键心相对左右邻谷的最小衬度(灰度级) —— 防"框压在缝里"的假框
_V35_AC_MIN = 0.65              # 带内列自相关峰值可信度门: 只有"周期明确"的带才允许用自相关节距/救回
#   实测: 现役场景 0.671~0.723(键排清晰); liveF 0.623~0.624; pt2 0.504~0.522; frozen* 0.34~0.53 ⇒ 取 0.65 卡在实测空档
_V35_PITCH_LO, _V35_PITCH_HI = 63.0, 80.0   # 采纳闸: 救回结果的节距必须落在此(真键排 70~72)


def _v32_slot_filter(ctr, luma, ky0, ky1, pitch):
    """🆕 v32: 去掉"不参与节距周期"的边缘槽(连接器两端金属边条)。

    真键的列剖面在**位移一个节距**后仍与自己高度相关(邻格也是键); 而连接器两端的整块金属边条
    (宽、过曝、只出现一次) 与前一格/后一格**都不像** ⇒ 局部相关低 ⇒ 去掉。
    只按"最长 [首,末] 存活区间"截边(内部不删), 因此不会误删中间真键; 全灭则不动作(保底)。
    返回 (new_ctr, info)。
    """
    if luma is None or not ctr or len(ctr) < 4 or not pitch or pitch < 6:
        return ctr, None
    try:
        prof = np.asarray(luma, np.float32)[int(ky0):int(ky1) + 1, :].mean(axis=0)
    except Exception:
        return ctr, None
    K = max(15, int(round(3.0 * pitch))) | 1
    pd = prof - cv2.blur(prof.reshape(1, -1), (K, 1)).ravel()
    pd = pd - pd.mean()
    p = int(round(pitch))
    w = int(round(pitch * 0.6))

    def lc(c, shift):
        a = max(0, int(c) - w)
        b = min(len(pd), int(c) + w)
        x1 = pd[a:b]
        x2 = pd[a + shift:b + shift]
        if x2.size != x1.size or x1.size < 10:
            return None
        x1 = x1 - x1.mean()
        x2 = x2 - x2.mean()
        den = float(np.sqrt((x1 * x1).sum() * (x2 * x2).sum()))
        return float((x1 * x2).sum() / den) if den > 1e-6 else 0.0

    keep, scores = [], []
    for c in ctr:
        f = lc(c, p)
        b = lc(c, -p)
        m = max(f if f is not None else -9.0, b if b is not None else -9.0)
        scores.append(round(float(m), 3))
        keep.append(m >= _V32_SLOT_CC)
    kept_idx = [i for i, k in enumerate(keep) if k]
    if not kept_idx:
        return ctr, {"scores": scores, "kept": None, "note": "全灭 ⇒ 不动作"}
    lo, hi = kept_idx[0], kept_idx[-1]
    if lo == 0 and hi == len(ctr) - 1:
        return ctr, {"scores": scores, "kept": [0, len(ctr) - 1], "dropped": 0}
    return ctr[lo:hi + 1], {"scores": scores, "kept": [lo, hi],
                            "dropped_head": lo, "dropped_tail": len(ctr) - 1 - hi}


def _v21_uniformize(segs, cf=None, cx0=0, luma=None, luma_rows=None, wgate=False, pitch_hint=0.0,
                    phase_flip=False):
    """Merge split parts, pick the MEDIAN width, drop the odd blocks.

    Returns (rects, info).  Every rect is (x0, x1) with the SAME width and is centred
    on that key's own detected centre -- defect (1) and (4) fixed here.

    v29 (2026-10-09 层③): 认领多键段前先做**形状校验**(cf=列剖面, cx0=剖面起点列)——
    只在段内沿栅格"槽间中点明显比槽心暗"时才算真·两键粘连; 平顶块(如连接器左端的
    整块金属边条)没有内部凹陷 ⇒ 一律不认领, 不再靠宽度窗口的一刀切。"""
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
    # 🆕 v35: 救回趟用**带内列自相关**的节距替代"段间中位差"(后者随分块粘连程度漂,
    #   同一静止场景实测在 72.5/78/83.5/88.5 之间跳; 节距一漂栅格槽就落到缝上 ⇒ 框位置错)。
    if wgate and 0.0 < float(pitch_hint) < 200.0:
        info["v35_gap_before_px"] = round(med_gap, 1)
        med_gap = float(pitch_hint)
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
        # v29 层③: 认领多键段前先做**形状校验** —— 真·两键粘连在"槽间中点"处必有凹陷;
        #   连接器左端整块金属边条是平顶(无凹陷) ⇒ 不认领(即使其宽度恰好落进多键窗)。
        #   本闸只会**去掉**误认领, 不会新增, 故不会凭空造齿。
        def _cf_at(x):
            if cf is None:
                return 1.0
            k = int(round(x)) - int(cx0)
            return float(cf[k]) if 0 <= k < len(cf) else 0.0

        # 🆕 v30 层③: 列剖面的**低频背景归一(平场)** —— ff = cf / blur(cf, ~3×节距)。
        #   cf(亮列占比) 的空间基线随光照梯度漂(右端 0.72~0.80, 左端 0.30) ⇒ 用大窗均值当"背景"除掉它;
        #   键(亮且局部凸) ⇒ ff>1; 暗缝 ⇒ ff<1 ⇒ 粘连大块里的真缝重新露出来。
        _ff = None
        if cf is not None and len(cf) > 8 and med_gap > 2:
            try:
                _K = max(15, int(round(3.0 * med_gap))) | 1
                _bg = cv2.blur(np.asarray(cf, np.float32).reshape(1, -1), (_K, 1)).ravel()
                _ff = np.asarray(cf, np.float32) / np.maximum(_bg, 1e-6)
            except Exception:
                _ff = None

        def _ff_at(x):
            if _ff is None:
                return 0.0
            k = int(round(x)) - int(cx0)
            return float(_ff[k]) if 0 <= k < len(_ff) else 0.0

        def _spanned_slots(_a, _b):
            return list(range(int(np.floor((_a + 0.10 * med_gap - phase) / med_gap)),
                              int(np.ceil((_b - 0.10 * med_gap - phase) / med_gap)) + 1))

        def _has_notch(_slots):
            for _k in range(len(_slots) - 1):
                _cl = _cf_at(phase + _slots[_k] * med_gap)
                _cr = _cf_at(phase + _slots[_k + 1] * med_gap)
                _cm = _cf_at(phase + (_slots[_k] + 0.5) * med_gap)
                _base = min(_cl, _cr)
                if _base > 0.0 and _cm < 0.75 * _base:
                    return True
            return False

        # 🆕 v35: 救回趟(wgate)用更宽的一档裂块门; 非救回趟 = v30 原档(逐位不变)
        _V35FFK = _V35_SPLIT_FF_KEY if wgate else _V30_SPLIT_FF_KEY
        _V35FFN = _V35_SPLIT_FF_NOTCH if wgate else _V30_SPLIT_FF_NOTCH
        _V35WMAX = _V35_SPLIT_WMAX if wgate else _V30_SPLIT_WMAX
        _V35MSLOT = _V35_SPLIT_MAXSLOTS if wgate else _V30_SPLIT_MAXSLOTS

        def _ff_split_ok(_slots):
            """平场形状闸: 每个槽心须亮(ff>=FF_KEY) 且相邻槽之间须有凹陷(ff 谷<=FF_NOTCH)。"""
            if _ff is None or len(_slots) < 2:
                return False
            for _k in range(len(_slots)):
                if _ff_at(phase + _slots[_k] * med_gap) < _V35FFK:
                    return False
            for _k in range(len(_slots) - 1):
                _m = phase + (_slots[_k] + 0.5) * med_gap
                _lo = int(round(_m - 0.18 * med_gap))
                _hi = int(round(_m + 0.18 * med_gap))
                _vals = [_ff_at(_x) for _x in range(_lo, _hi + 1)]
                _vals = [v for v in _vals if v > 0.0]
                if not _vals or min(_vals) > _V35FFN:
                    return False
            return True

        _split_notes = []
        # 🆕 v35: 救回趟把"单键宽上限"从 1.6×中键宽 放宽到 _V35_SINGLE_MAX×节距 ——
        #   死区块(1.6×中键宽 .. 1.35×节距)不再一律拒收: 有内部凹陷且跨 2~3 格 ⇒ 认那些格(真·粘连);
        #   否则(跨 ≤1 格) ⇒ 按单键认领最近格。非救回趟 wgate=False ⇒ _single_hi=_pad_hi ⇒ 逐位不变。
        _single_hi = max(_pad_hi, _V35_SINGLE_MAX * med_gap) if wgate else _pad_hi
        for _a, _b in merged:
            _w = _b - _a + 1
            if _w < _pad_lo or (_single_hi < _w < _multi_lo):
                _rejected.append([int(_a), int(_b), int(_w)])   # 碎屑 / 边缘亮条 ⇒ 不认领
                continue
            if _w > _multi_hi:
                # 🆕 v30 层③: 过宽块 —— 原先一律丢弃; 现在**平场裂块**: 若它跨 2~4 个栅格槽且
                #   平场剖面在槽心亮/槽间有凹陷, 就按节距认领这些格(把被冲糊的真键找回); 否则仍整块丢弃。
                _slots = [k for k in range(int(np.ceil((_a - phase) / med_gap - 1e-9)),
                                           int(np.floor((_b - phase) / med_gap + 1e-9)) + 1)]
                if (_V30_SPLIT_ON and 2 <= len(_slots) <= _V35MSLOT
                        and _w <= _V35WMAX * med_gap and _ff_split_ok(_slots)):
                    _claims.update(_slots)
                    _split_notes.append([int(_a), int(_b), int(_w), list(_slots)])
                else:
                    _rejected.append([int(_a), int(_b), int(_w)])   # 背景/连接器端 ⇒ 仍丢弃
                continue
            if _w <= _pad_hi:                                   # 单根键(窄)
                _claims.add(int(round((0.5 * (_a + _b) - phase) / med_gap)))
            else:                                               # 多键段 / v35 死区块
                _slots = _spanned_slots(_a, _b)
                if 2 <= len(_slots) <= 3 and _has_notch(_slots):
                    _claims.update(_slots)
                elif wgate and _w <= _single_hi and len(_slots) <= 1:
                    # 🆕 v35: 死区块无内部凹陷且只跨 ≤1 格 ⇒ 真身是"一整根宽键", 按单键认领
                    _claims.add(int(round((0.5 * (_a + _b) - phase) / med_gap)))
                    _split_notes.append([int(_a), int(_b), int(_w), "v35-single"])
                else:
                    _rejected.append([int(_a), int(_b), int(_w), "flat(no-notch)"])
        if _split_notes:
            info["v30_split_blocks"] = _split_notes
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
            if wgate and phase_flip:       # 🆕 v35: 相位二选一 —— 段落中心可能整排落在"缝"上
                phase = phase + 0.5 * med_gap   #   (实测: 相位错半个节距时全部槽心衬度为负), 平移半格再验
            # 🆕 v35: **栅格延伸** —— 块分段会漏掉两端被"糊住"的真键(实测现役带: 块分段只认领
            #   中段 ~15 格, 而按真节距 70px 对齐后 20 格槽心衬度 +40~+124 全为正)。这里在
            #   "已认领跨度"的两端逐格外扩: 只要该槽的灰度剖面相对左右邻谷仍有正衬度(>= _V35_CTR_MIN),
            #   就补认这一格; 一旦碰到缝/平区(衬度不足)立刻停 —— 端点金属边块因此进不来。
            if wgate and luma is not None and luma_rows is not None:
                try:
                    _ly0, _ly1 = int(luma_rows[0]), int(luma_rows[1])
                    _prof = luma[_ly0:_ly1 + 1, :].astype(np.float32).mean(axis=0)
                    _half = max(1, int(round(0.5 * med_gap)))

                    def _slot_con(_i):
                        _c = int(round(phase + _i * med_gap))
                        if _c < 0 or _c >= _prof.size:
                            return -999.0
                        return float(_prof[_c] - min(_prof[max(0, _c - _half)],
                                                      _prof[min(_prof.size - 1, _c + _half)]))
                    _ext = 0
                    while _ext < 8 and _slot_con(_lo - 1) >= _V35_CTR_MIN:
                        _lo -= 1; _ext += 1
                    while _ext < 8 and _slot_con(_hi + 1) >= _V35_CTR_MIN:
                        _hi += 1; _ext += 1
                    if _ext:
                        _claims |= set(range(_lo, _hi + 1))
                        info["v35_extend"] = {"slots": _ext, "span": [int(_lo), int(_hi)],
                                              "con_left": round(_slot_con(_lo), 1),
                                              "con_right": round(_slot_con(_hi), 1)}
                except Exception:                                               # noqa: BLE001
                    pass
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
    # 🆕 v34 (移植 v32): 去掉"不参与节距周期"的边缘槽(连接器两端金属边条) —— 只截边, 内部不删
    if _V32_ON and luma is not None and luma_rows is not None:
        _ctr32, _f32 = _v32_slot_filter(ctr, luma, luma_rows[0], luma_rows[1], med_gap)
        if _f32 is not None:
            info["v32_slot_filter"] = _f32
            ctr = _ctr32
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
    global _V21_BAND_PREV            # 🔴 键行带"带锁"状态(见文件顶部说明: 治判据图翻面)
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
        # 🆕 v36: 按当帧**键排区锐度**(中心窗 Laplacian 方差)判定"是否对焦修好后的新清晰画面"
        #   ⇒ 决定整套 v36 逻辑开不开(参考序列是旧模糊画面 ⇒ 关着 ⇒ 逐位退回 v35)。
        global _V36_LIVE
        _sharp = 0.0
        _sherr = ""
        try:
            _h, _w = g.shape[:2]
            _cy0, _cy1 = max(0, _h // 2 - 200), min(_h, _h // 2 + 200)
            _cx0, _cx1 = max(0, _w // 2 - 700), min(_w, _w // 2 + 700)
            _crop = np.ascontiguousarray(g[_cy0:_cy1, _cx0:_cx1])
            if _crop.dtype != np.uint8:          # OpenCV 5: Laplacian(CV_64F) 只吃 uint8 输入
                _crop = np.clip(_crop, 0, 255).astype(np.uint8)
            _sharp = float(cv2.Laplacian(_crop, cv2.CV_64F).var())
            _V36_LIVE = bool(_V36_ON and _sharp >= _V36_MIN_SHARP
                             and float(np.median(g)) >= _V36_MIN_P50)
        except Exception as _e:                                              # noqa: BLE001
            _sherr = repr(_e)[:120]
            _V36_LIVE = False
        met["v36_live"] = bool(_V36_LIVE)
        met["v36_sharp"] = round(float(_sharp), 1)
        met["v36_sherr"] = _sherr
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
            # v28: 行带 = 最上簇(齿排) + 静止保持, 不用"全体 hit 的并集"
            #   (本地会话的并集版实测仍在翻: 行带 2 种/根数 7↔15; 本版 1 种/恒 15。见 _v26_pick_band)
            # v30 层②: 传入粗缩略图(48x36) 供"场景变化门" —— 帧差小=同一静止工件, 多候选时选与上帧带重叠的那簇。
            try:
                _thumb = cv2.resize(ga, (48, 36), interpolation=cv2.INTER_AREA)
            except Exception:
                _thumb = None
            ky0, ky1 = _v26_pick_band(hits, met, thumb=_thumb)
        # 🆕 v34 (移植 v32): 端点有效性过滤**只在显式指定带时启用**(= 两遍校验的 pass2);
        #    pass1(band=None) ⇒ 一字不动 ⇒ 与 v33 逐位一致(参考序列零回退由结构保证)。
        _v32_filt = bool(_V32_ON and band is not None and not gate.get("no_sfilt"))
        met["v32_filt"] = bool(_v32_filt)
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
        _wgate = bool(gate.get("wgate"))         # 🆕 v35: 救回趟开关(仅显式带 pass2 由调用方置位)
        _pflip = bool(gate.get("phase_flip"))    # 🆕 v35: 相位二选一(另一档)
        met["v35_wgate"] = bool(_wgate)
        _phint = 0.0
        if _wgate:
            # 🆕 v35: 救回趟先用**带内列自相关**量出真键排节距, 交 uniformize 覆盖"段间中位差"。
            #   仅在**周期可信**(峰值 >= _V35_AC_MIN) 时才覆盖 —— 低周期场景用老口径, 不冒险。
            _ph, _ps = _v35_band_pitch(ga, ky0, ky1)
            met["v35_pitch_hint"] = {"pitch": round(float(_ph), 1), "score": float(_ps)}
            if float(_ps) >= _V35_AC_MIN:
                _phint = float(_ph)
        if _v32_filt:
            rects, uinfo = _v21_uniformize(segs, cf=cf, cx0=cx0, luma=ga, luma_rows=(ky0, ky1),
                                           wgate=_wgate, pitch_hint=_phint, phase_flip=_pflip)
        else:
            rects, uinfo = _v21_uniformize(segs, cf=cf, cx0=cx0, wgate=_wgate, pitch_hint=_phint,
                                           phase_flip=_pflip)
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
        _V21_BAND_PREV = [int(ky0), int(ky1)]     # 本次成功 ⇒ 记成下一帧的带锁基准
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
        _vs = max(0.1, float(_V36_HSTRETCH if _V36_LIVE else _V23_KEY_HSTRETCH))  # v36: 新画面键高放大, 旧画面=v23 原值
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
    # 🆕 v34 (移植 v32 两遍校验): 只在 pass1 明显不对(数太少 <12 根, 或比 19 还多)且存在强周期锚点带时,
    #   用锚点带重渲一遍; 重渲结果**恰好 19** 才采用, 否则原样保留 ⇒ pass1 已 15~19 的视角逐位不变。
    _n1v = int(met.get("n_keys") or 0)
    if _V32_ON and _V32_TWOPASS_ON and (_n1v < _V32_ATTEMPT_LO or _n1v > _V31_N_TARGET):
        try:
            _g2 = _v25_norm_luma(_v21_luma(np.asarray(bgr)))
            _an = _v32_anchor_band(_g2)
        except Exception:                                                   # noqa: BLE001
            _an = None
        if _an is not None:
            _ay0, _ay1, _apitch, _ascore = _an
            _b0 = met.get("key_rows") or met.get("kept_rows")
            if _ascore >= _V32_AC_MIN:
                _i2, _m2 = _v21_render_core(bgr, deskew_deg=deskew_deg, hw=_hw,
                                            band=(int(_ay0), int(_ay1)))
                _m2 = dict(_m2 or {})
                if _i2 is not None and int(_m2.get("n_keys") or 0) == _V31_N_TARGET:
                    _m2["out"] = _m2.get("out_size")
                    _m2["kept_rows"] = _m2.get("key_rows")
                    _m2["kept_h"] = _m2.get("n_key_rows")
                    _m2["dropped_sat_rows"] = _m2.get("bar_rows_dropped")
                    _bh2 = max(1, int(_m2.get("band_h") or 1))
                    _m2["dropped_pct"] = round(100.0 * int(_m2.get("bar_rows_dropped") or 0) / _bh2, 1)
                    _m2["sat_after"] = _m2.get("strip_sat_frac")
                    _sx2 = _m2.get("strip_x") or [0, 0]
                    _m2["x_trim"] = {"trimmed": True, "x_span": [int(_sx2[0]), int(_sx2[1])],
                                     "dropped_cols": ([0, int(_sx2[0])] if _sx2[0] else []),
                                     "col_sat_before_max": None,
                                     "rule": "v21 strip columns (horizontal edge strength |dI/dy|)"}
                    _m2["k"] = float(k)
                    _m2["fix_hw"] = [int(_hw[0]), int(_hw[1])]
                    _m2["v32_twopass"] = {"from": _b0, "to": [int(_ay0), int(_ay1)],
                                          "score": round(float(_ascore), 3),
                                          "first_n": int(met.get("n_keys") or 0)}
                    _m2["v32_autocorr"] = {"band": [int(_ay0), int(_ay1)], "pitch": round(float(_apitch), 1),
                                           "score": round(float(_ascore), 3)}
                    _m2.setdefault("err", "")
                    img, met = _i2, _m2
    # 🆕 v35 救回趟: pass1 键数落在 [_V35_N_LO,_V35_N_HI] 时, 用**同一行带** + 单键宽度门重跑一遍,
    #   结果需 **> pass1** 且 >= _V35_ADOPT_MIN 根 且节距落在真键排量级 才采纳(**宁少不假**)。
    _n1w = int(met.get("n_keys") or 0)
    if _V35_ON and (_V35_N_LO <= _n1w <= _V35_N_HI):
        _bw = met.get("key_rows") or met.get("kept_rows") or met.get("key_row_span")
        if _bw:
            # 🔴 救回趟会再进一次 `_v21_uniformize` ⇒ 它会往 `_V25_SEEN`(跨帧投票窗)里多塞一条。
            #   为保 pass1 的投票动态不被救回趟污染(参考序列零回退的关键), 调用前后快照/恢复。
            try:
                with _V25_SEEN_LOCK:
                    _vseen_bak = {_k: list(_v) for _k, _v in _V25_SEEN.items()}
                    # 救回趟是"一次性诊断重跑", 不该被跨帧投票窗否掉它新认领的格 ⇒ 先清空窗口,
                    #   使 uniformize 在**单帧**环境下走(vote 无 ≥2 票 ⇒ 不否决), 调用后原样恢复。
                    _V25_SEEN.clear()
            except Exception:                                                   # noqa: BLE001
                _vseen_bak = None
            # 🔁 救回趟做**多假设(多带)**: pass1 带 + (若够高) 其上/下各 60 行子带 —— 同一静止场景
            #   实测"带差 10 行"就会让某些粘连块被拒/被收(如 [1120,1189] 给 11, [1120,1179] 给 15)。
            #   对每个候选带跑一遍救回趟, 取"**通过全部闸**且根数最多"者; 全不通过则不采纳。
            _cands = []
            _by0, _by1 = int(_bw[0]), int(_bw[1])
            _bh = _by1 - _by0 + 1
            _cands.append((_by0, _by1, False))
            _cands.append((_by0, _by1, True))          # 🆕 相位二选一(另一档)
            # 🔴 只在 pass1 带**附近**微调(带高变化 ≤25%): 救回趟的前提是"这条带就是一条键排",
            #    键排实测高 40~70 行。若允许换成高度差一倍的带(如 liveF 的 145 行带回落到 60 行),
            #    就等于换了另一块结构 —— 参考序列会被改写(实测 liveF 16→18) ⇒ 禁止。
            if _bh > 62:
                for (_sy0, _sy1) in ((_by0, _by0 + 59), (_by1 - 59, _by1)):
                    if _sy1 - _sy0 + 1 >= 0.75 * _bh:
                        _cands.append((_sy0, _sy1, False))
                        _cands.append((_sy0, _sy1, True))
            _tries, _pick = [], None
            for (_cy0, _cy1, _cflip) in _cands:
                if _vseen_bak is not None:      # 每个候选都从"空投票窗"起跑(救回趟=单帧重跑)
                    try:
                        with _V25_SEEN_LOCK:
                            _V25_SEEN.clear()
                            _V25_SEEN.update(_vseen_bak)
                            _V25_SEEN.clear()
                    except Exception:                                           # noqa: BLE001
                        pass
                try:
                    _i4, _m4 = _v21_render_core(bgr, deskew_deg=deskew_deg, hw=_hw,
                                                band=(int(_cy0), int(_cy1)),
                                                gate={"wgate": True, "phase_flip": _cflip})
                except Exception:                                               # noqa: BLE001
                    _i4, _m4 = None, None
                finally:
                    if _vseen_bak is not None:
                        try:
                            with _V25_SEEN_LOCK:
                                _V25_SEEN.clear()
                                _V25_SEEN.update(_vseen_bak)
                        except Exception:                                       # noqa: BLE001
                            pass
                _m4 = dict(_m4 or {})
                _n4 = int(_m4.get("n_keys") or 0)
                _p4 = float(_m4.get("lattice_pitch_px") or 0.0)
                # "**无假框**"闸: 用交付带算每个键心的局部衬度(键心 − 左右邻谷, 灰度级)。
                #   真键排每个键心都该坐在亮脊上(实测 +35~+86); 栅格错位(相位/节距漂)时会出现负值
                #   (实测漏配时 21 根里 19 根衬度为负 = 框压在缝里) ⇒ 一票否决。
                _mincon = None
                _gapcon = None
                try:
                    _pr = _v21_luma(bgr)
                    _bb2 = _m4.get("key_rows") or [_cy0, _cy1]
                    _pr = _pr[int(_bb2[0]):int(_bb2[1]) + 1, :].astype(np.float32).mean(axis=0)
                    _hh = max(1, int(round(_p4 / 2.0)))
                    _cs = []
                    for _c in (int(v) for v in (_m4.get("centers") or [])):
                        _l = _pr[max(0, _c - _hh)]
                        _r = _pr[min(_pr.size - 1, _c + _hh)]
                        _cs.append(float(_pr[_c] - min(_l, _r)))
                    if _cs:
                        _mincon = float(min(_cs))
                        _m4["v35_ctr_contrast"] = [round(v, 1) for v in _cs]
                        _m4["v35_ctr_min"] = round(_mincon, 1)
                    # 🆕 v36: 新清晰画面里**每根键心都有一道暗凹陷(notch)**, 于是"键心 vs ±节距/2"
                    #   会把正确栅格误判成负衬度 ⇒ 补一个**抗凹陷**的衬度口径: 每格只取格内**局部峰值**
                    #   (键的亮脊, 与凹陷无关), 减去该格左右**格间中点**的谷值。正确栅格恒为正。
                    _ctr = sorted(int(v) for v in (_m4.get("centers") or []))
                    if len(_ctr) >= 3:
                        _q = []
                        for _i, _c in enumerate(_ctr):
                            _lo = _ctr[_i - 1] if _i > 0 else _c - _hh
                            _hi = _ctr[_i + 1] if _i < len(_ctr) - 1 else _c + _hh
                            _gp = []
                            if _i > 0:
                                _gp.append(_pr[max(0, int((_ctr[_i - 1] + _c) / 2.0))])
                            if _i < len(_ctr) - 1:
                                _gp.append(_pr[min(_pr.size - 1, int((_c + _ctr[_i + 1]) / 2.0))])
                            if not _gp:
                                continue
                            _band_lo = max(0, _c - int(0.45 * _p4))
                            _band_hi = min(_pr.size, _c + int(0.45 * _p4) + 1)
                            _peak = float(_pr[_band_lo:_band_hi].max()) if _band_hi > _band_lo else float(_pr[_c])
                            _q.append(_peak - float(sum(_gp) / len(_gp)))
                        if _q:
                            _gapcon = float(np.median(_q))
                            _m4["v36_gap_contrast"] = [round(float(v), 1) for v in _q]
                            _m4["v36_gap_med"] = round(_gapcon, 1)
                except Exception:                                               # noqa: BLE001
                    _mincon = None
                    _gapcon = None
                _ac4 = float(((_m4.get("v35_pitch_hint") or {}).get("score")) or -1.0)
                # 🆕 v36: "无假框"闸改判据 —— 旧口径(键心 vs ±节距/2)被暗凹陷污染 ⇒ 除它外,
                #   抗凹陷口径(格内峰 vs 格间谷)达标也可采纳。
                _ctr_ok = bool((_mincon is not None and _mincon >= _V35_CTR_MIN)
                               or (_V36_LIVE and _gapcon is not None and _gapcon >= _V36_GAP_MIN))
                _ok = bool(_i4 is not None and _n4 > _n1w and _n4 >= _V35_ADOPT_MIN
                           and _V35_PITCH_LO <= _p4 <= _V35_PITCH_HI
                           and _ctr_ok
                           and _ac4 >= _V35_AC_MIN)
                _tries.append({"band": [int(_cy0), int(_cy1)], "flip": bool(_cflip),
                               "n": _n4, "pitch": round(_p4, 1),
                               "ctr_min": (None if _mincon is None else round(_mincon, 1)),
                               "ac": _ac4, "ok": _ok})
                if _ok:
                    if _V36_LIVE:                # 🆕 v36: 收集**所有**通过闸的候选, 取**最接近 19** 的那条
                        _score = (-abs(int(_n4) - 19), int(_n4))
                        if _pick is None or _score > _pick[0]:
                            _pick = (_score, _i4, _m4)
                    elif _pick is None:           # v35 原口径: 取**第一个通过全部闸**的候选
                        _pick = ((-1, 0), _i4, _m4)
            met["v35_try"] = {"n1": _n1w, "cands": _tries}
            if _pick is not None:
                _i4, _m4 = _pick[1], _pick[2]
                _n4 = int(_m4.get("n_keys") or 0)
                _p4 = float(_m4.get("lattice_pitch_px") or 0.0)
                _bw = _m4.get("key_rows") or _bw
                _m4["out"] = _m4.get("out_size")
                _m4["kept_rows"] = _m4.get("key_rows")
                _m4["kept_h"] = _m4.get("n_key_rows")
                _m4["dropped_sat_rows"] = _m4.get("bar_rows_dropped")
                _bh4 = max(1, int(_m4.get("band_h") or 1))
                _m4["dropped_pct"] = round(100.0 * int(_m4.get("bar_rows_dropped") or 0) / _bh4, 1)
                _m4["sat_after"] = _m4.get("strip_sat_frac")
                _sx4 = _m4.get("strip_x") or [0, 0]
                _m4["x_trim"] = {"trimmed": True, "x_span": [int(_sx4[0]), int(_sx4[1])],
                                 "dropped_cols": ([0, int(_sx4[0])] if _sx4[0] else []),
                                 "col_sat_before_max": None,
                                 "rule": "v21 strip columns (horizontal edge strength |dI/dy|)"}
                _m4["k"] = float(k)
                _m4["fix_hw"] = [int(_hw[0]), int(_hw[1])]
                _m4["v35_rescue"] = {"from_n": _n1w, "to_n": _n4, "pitch": round(_p4, 1),
                                     "band": [int(_bw[0]), int(_bw[1])]}
                _m4.setdefault("err", "")
                img, met = _i4, _m4
    # 🆕 v36 确定性栅格兜底: 候选栅格仍非 19(18/20) 或未采纳时, 用**组合梳拟合**的权威栅格替换
    #   端到端根数与栅格(实测帧间恒稳, 剔掉两端宽金属边块后正好 19 根)。只改"取哪几行/哪几列",
    #   不碰 crop/warp/get_cropper/_region_payload。
    if _V36_ON and _V36_LIVE:
        try:
            _nnow = int(met.get("n_keys") or 0)
            _pl = float(met.get("lattice_pitch_px") or 0.0)
            _bmow = met.get("key_rows") or met.get("kept_rows") or met.get("key_row_span")
            # 🔴 触发条件: 根数≠19 **或 节距不在真键排带**(实测现役帧会给出 n=19 但节距 121 的
            #   伪结构 ⇒ 门 geo_ok=False 被抑制)。两者任一不合法 ⇒ 用确定性栅格重算。
            # 🔴 无条件重算(治"数量对但框压在键缝里"): pass1 有时会锁到**金属焊盘行带**
            #   (同样 pitch 71 但相位与真键差半格) ⇒ rects 数量/节距都对、位置全错。
            #   只要在新清晰画面上, 一律用"逐带扫描 + 相位锁定"的权威栅格覆盖 rects。
            _need = True
            if _need:
                _ga2 = _v25_norm_luma(_v21_luma(np.asarray(bgr)))
                _lr = _v36_lattice(_ga2, want=_V31_N_TARGET)
                if _lr is not None:
                    _cens = sorted((a + b) / 2.0 for a, b in _lr)
                    _dds = np.diff(_cens) if len(_cens) > 1 else np.array([])
                    _lband = list(_V36_LAST_BAND) if _V36_LAST_BAND else None
                    met["rects"] = [[int(a), int(b)] for a, b in _lr]
                    met["centers"] = [int(round(c)) for c in _cens]
                    met["n_keys"] = int(len(_lr))
                    if _lband:
                        met["key_rows"] = _lband
                        met["kept_rows"] = _lband
                    met["width_uniform_px"] = int(round(float(np.median([b - a + 1 for a, b in _lr]))))
                    if _dds.size:
                        met["lattice_pitch_px"] = round(float(np.median(_dds)), 1)
                        met["pitch_median_px"] = met["lattice_pitch_px"]
                    met["v36_lattice"] = {"n": int(len(_lr)), "band": _lband,
                                          "from_n": _nnow, "pitch": met.get("lattice_pitch_px")}
                    if _V36_LATTICE_INFO:
                        met["v36_phase"] = dict(_V36_LATTICE_INFO)
                        _bad = int(_V36_LATTICE_INFO.get("n_bad") or 0)
                        met["v36_phase_bad"] = _bad
                    met.setdefault("err", "")
        except Exception:                                                    # noqa: BLE001
            pass
    return img, met


# ============================================================================
# 🆕 v31 【19根渲染门】+ 同姿位输出闩锁 (2026-10-09 老倪硬要求)
#   目标: 判据图上"除了 19 根金手指其它一律不要显示; 不要跳不要跳不要跳"。
#   规则:
#     ① **只有**判决落在真键排(几何自洽: 节距≈70 量级 / 高度合理 / 与已验证带一致)
#        **且 n_keys==19** 时才画金手指框;
#     ② 否则**不画任何金手指框**, 改为在画面上打醒目状态横幅(原因 + 帧龄 + 当前拍到的 y 区间);
#     ③ 绝不把 y≈[1220,1279] 这类**非键排**结构画成金手指;
#     ④ 同一位姿下**逐帧逐位一致**(不可抖动): 用缩略图帧差判定"同一姿位", 同一姿位沿用上帧输出(逐像素相同);
#        判决(画框/抑制)是**按姿位**定的, 不是按帧定的 ⇒ 避免单帧 n_keys 抖动导致闪。
#   ⚠️ 本门只作用于**人看的判据图**, 绝不动模型输入链(crop_goldfinger_regular / warp...)。
# ============================================================================
_V31_GATE_ON = True
_V31_SCENE_TOL = 6.0          # 缩略图平均绝对差 <= 该值 ⇒ 判为"同一姿位"(沿用上帧输出)
_V31_N_TARGET = 19            # 金手指真值根数
_V31_PITCH_MIN, _V31_PITCH_MAX = 60.0, 85.0   # 真键排节距量级(实测 ~70~72)
_V31_BAND_H_MAX = 160         # 键排带最大高度(超过=把别的结构并进来了)
_V31_ESCALATE_STREAK = 2      # 抑制态下, 连续这么多帧都合格 ⇒ 升为"画框"(避免误判也防抖)
_V31_ST = {"scene": None, "out": None, "ret_met": None, "ret_state": None,
           "state": None, "band": None, "ok_streak": 0, "ts": 0.0,
           "banner": "", "boxes": []}


def _v31_thumb(bgr):
    """粗缩略图(64x48 灰度) — 判"同一姿位"用。"""
    try:
        return cv2.cvtColor(cv2.resize(bgr, (64, 48), interpolation=cv2.INTER_AREA),
                            cv2.COLOR_BGR2GRAY).astype(np.float32)
    except Exception:                                                       # noqa: BLE001
        return None


def _v31_banner(hw, rows, accent):
    """状态横幅(BGR, 定尺 hw)。rows = [(中文, ascii), ...]; 有 PIL+CJK 字体走中文, 否则回退 cv2 ASCII。"""
    W, H = int(hw[0]), int(hw[1])
    img = np.zeros((H, W, 3), np.uint8)
    bar = max(28, H // 7)
    img[0:bar, :] = (int(accent[0]), int(accent[1]), int(accent[2]))
    done = False
    try:
        from PIL import Image, ImageDraw, ImageFont
        fp = None
        for cand in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                     "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                     "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
            if os.path.exists(cand):
                fp = cand
                break
        if fp:
            pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            dr = ImageDraw.Draw(pil)
            f0 = ImageFont.truetype(fp, max(15, int(bar * 0.62)))
            f1 = ImageFont.truetype(fp, max(14, int(bar * 0.46)))
            dr.text((8, max(2, int(bar * 0.16))), rows[0][0], font=f0, fill=(255, 255, 255))
            yy = bar + 10
            for r in rows[1:]:
                dr.text((8, yy), r[0], font=f1, fill=(255, 255, 255))
                yy += max(20, int(bar * 0.62))
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            done = True
    except Exception:                                                       # noqa: BLE001
        done = False
    if not done:
        cv2.putText(img, rows[0][1][:58], (8, int(bar * 0.74)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.40, bar / 40.0), (255, 255, 255), 2, cv2.LINE_AA)
        yy = bar + max(18, int(bar * 0.62))
        for r in rows[1:]:
            cv2.putText(img, r[1][:72], (8, yy), cv2.FONT_HERSHEY_SIMPLEX,
                        0.46, (255, 255, 255), 1, cv2.LINE_AA)
            yy += max(18, int(bar * 0.62))
    return img


def _v31_overlay(base, rows, accent=(0, 0, 200)):
    """v33: 在**保留画面**的前提下, 在顶部打一条状态横幅 —— 绝不整张不显示。

    rows = [(中文, ascii), ...]; 有 PIL+CJK 字体走中文, 否则回退 cv2 ASCII。
    顶部条高度取 H//3(判据图键排集中在中部 y≈127~205, 顶部 1/3 是黑边)⇒ 横幅不盖住金手指。
    """
    out = np.ascontiguousarray(base).copy()
    H, W = out.shape[:2]
    bar = max(30, min(H // 3, H - 1))
    out[0:bar, :] = (int(accent[0]), int(accent[1]), int(accent[2]))
    done = False
    try:
        from PIL import Image, ImageDraw, ImageFont
        fp = None
        for cand in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                     "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                     "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
            if os.path.exists(cand):
                fp = cand
                break
        if fp:
            pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
            dr = ImageDraw.Draw(pil)
            nrow = max(1, len(rows))
            fs0 = max(14, int(bar / max(1.55, nrow * 0.52)))
            fs1 = max(11, int(bar / max(2.3, nrow * 0.78)))
            dr.text((8, 3), rows[0][0], font=ImageFont.truetype(fp, fs0), fill=(255, 255, 255))
            yy = 3 + fs0 + 3
            for r in rows[1:]:
                if yy + fs1 > bar:
                    break
                dr.text((8, yy), r[0], font=ImageFont.truetype(fp, fs1), fill=(255, 255, 255))
                yy += fs1 + 3
            out = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            done = True
    except Exception:                                                       # noqa: BLE001
        done = False
    if not done:
        cv2.putText(out, rows[0][1][:58], (8, int(bar * 0.45)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.36, bar / 60.0), (255, 255, 255), 2, cv2.LINE_AA)
        yy = int(bar * 0.45) + max(14, int(bar * 0.28))
        for r in rows[1:]:
            if yy > bar - 2:
                break
            cv2.putText(out, r[1][:72], (8, yy), cv2.FONT_HERSHEY_SIMPLEX,
                        0.40, (255, 255, 255), 1, cv2.LINE_AA)
            yy += max(14, int(bar * 0.28))
    return out


def _v31_draw_boxes(img, met, hw, color=(0, 255, 0), thick=2):
    """🆕 把金手指列(rects)按渲染变换映射到判据图坐标, 画实线框(仅 19 根时用)。

    映射与 _v21_render_core 第 7 步一致: block=src[crop] → resize(sc, 纵向×_V23_KEY_HSTRETCH)
    → 居中贴到 out。失败则原样返回(绝不因画框而丢图)。
    """
    return img  # [no-box 2026-10-09 老倪: 不要高亮框]
    # 2026-10-09 老倪要求: 不加绿色方框 ⇒ 本函数置空(原实现仍在下方, 需要时删这行即可恢复)
    return img
    try:
        crop = met.get("crop")
        if img is None or not crop:
            return img
        px0, py0, px1, py1 = [int(v) for v in crop]
        sc = float(met.get("resize_scale") or 1.0)
        band = met.get("key_rows") or met.get("kept_rows") or met.get("key_row_span")
        rects = met.get("rects") or []
        if not band or not rects:
            return img
        W, H = int(hw[0]), int(hw[1])
        if img.shape[0] != H or img.shape[1] != W:
            img = cv2.resize(img, (W, H))
        vs = max(0.1, float(_V36_HSTRETCH if _V36_LIVE else _V23_KEY_HSTRETCH))
        bw = max(1, px1 - px0)
        bh = max(1, py1 - py0)
        ow = max(1, int(round(bw * sc)))
        oh = max(1, int(round(bh * sc * vs)))
        x0o = max(0, (W - ow) // 2)
        y0o = max(0, (H - oh) // 2)
        jy0 = int(y0o + (int(band[0]) - py0) * sc * vs)
        jy1 = int(y0o + (int(band[1]) + 1 - py0) * sc * vs)
        for a, b in rects:
            jx0 = int(x0o + (int(a) - px0) * sc)
            jx1 = int(x0o + (int(b) + 1 - px0) * sc)
            cv2.rectangle(img, (max(0, jx0), max(0, jy0)),
                          (min(W - 1, jx1), min(H - 1, jy1)), color, thick)
    except Exception:                                                       # noqa: BLE001
        pass
    return img


def render_judge_gated(bgr, deskew_deg=0.0, hw=_JUDGE_HW, k=_JR_K):
    """v31/v33: 先按 v30 出原判据图, 再套【19根渲染门】+ 同姿位闩锁。返回 (out_bgr, meta)。

    v33 修正: 抑制态下**保留判据画面**(img) 并在顶部打横幅 —— 绝不整张不显示(黑屏)。
    """
    _hw = (int(hw[0]), int(hw[1])) if hw else _JUDGE_HW
    if not _V31_GATE_ON:
        return render_judge(bgr, deskew_deg=deskew_deg, hw=_hw, k=k)
    thumb = _v31_thumb(bgr)
    scene_same = (thumb is not None and _V31_ST.get("scene") is not None
                  and float(np.abs(thumb - _V31_ST["scene"]).mean()) <= _V31_SCENE_TOL)
    if not scene_same:                       # 换姿位 ⇒ 复位判决锁
        _V31_ST["state"] = None
        _V31_ST["ok_streak"] = 0
        # 🔴 2026-10-09 修: 必须同时清掉记住的行带 —— 否则先前在**错行带**(如金属焊盘 [1000,1059])
        #   被判抑制后, 该错带会一直留在 _V31_ST["band"], 后续即使当前帧是完美 19 根 + 正确行带
        #   [890,949], band_ok 也因"与旧带不重叠"恒为 False ⇒ 永久抑制, 横幅还会自相矛盾地
        #   印出"识别 19 根 ≠ 19"。
        _V31_ST["band"] = None
    img, met = render_judge(bgr, deskew_deg=deskew_deg, hw=_hw, k=k)
    met = dict(met or {})
    n = int(met.get("n_keys") or 0)
    pitch = float(met.get("lattice_pitch_px") or 0.0)
    band = met.get("key_rows") or met.get("kept_rows") or None
    bh = (int(band[1]) - int(band[0]) + 1) if band else 0
    ov = False
    if band and _V31_ST.get("band"):
        vb = _V31_ST["band"]
        ov = (max(0, min(int(band[1]), int(vb[1])) - max(int(band[0]), int(vb[0])) + 1) > 0)
    geo_ok = (n == _V31_N_TARGET and _V31_PITCH_MIN <= pitch <= _V31_PITCH_MAX
              and 0 < bh <= _V31_BAND_H_MAX)
    band_ok = (_V31_ST.get("band") is None) or ov
    ok = bool(geo_ok and band_ok and img is not None)
    # ---- 按姿位定判决(不按帧) ----
    if _V31_ST["state"] is None:
        _V31_ST["state"] = "shown" if ok else "suppressed"
        if ok:
            _V31_ST["band"] = [int(band[0]), int(band[1])]
        _V31_ST["ok_streak"] = 0
    elif _V31_ST["state"] == "suppressed":
        _V31_ST["ok_streak"] = (_V31_ST["ok_streak"] + 1) if ok else 0
        if _V31_ST["ok_streak"] >= _V31_ESCALATE_STREAK:
            _V31_ST["state"] = "shown"
            _V31_ST["band"] = [int(band[0]), int(band[1])]
            _V31_ST["ok_streak"] = 0
    if _V31_ST["state"] != "shown" and not scene_same:
        _V31_ST["ts"] = time.time()
    state = _V31_ST["state"]
    # ---- 组装输出 ----
    if state == "shown" and img is not None:
        # 🆕 v34: 19 根 ⇒ 画面 = 真判据图 + **实线框**(框住每一根金手指); 画框失败则原样返回
        out = _v31_draw_boxes(img, met, _hw, color=(0, 255, 0), thick=2)
        boxes = [[int(a), int(b)] for a, b in (met.get("rects") or [])]
        # 🆕 v36: 人工核对用的**参考竖线** —— 只在 v36 生效帧上画(参考序列像素不受影响)。
        #   画在**第 1 根键的框心**(原图 x 坐标经渲染变换映射到判据图), 并在顶部标注原图 x。
        if False:  # [老倪 2026-10-09: 不要参考竖线/细长条] _V36_LIVE and met.get("rects") and met.get("crop"):
            try:
                _crop = [int(v) for v in met["crop"]]
                _px0, _py0, _px1, _py1 = _crop
                _sc = float(met.get("resize_scale") or 1.0)
                _W, _H = int(_hw[0]), int(_hw[1])
                _vs = max(0.1, float(_V36_HSTRETCH))
                _ow = max(1, int(round((_px1 - _px0) * _sc)))
                _ox0 = max(0, (_W - _ow) // 2)
                _cx = 0.5 * (met["rects"][0][0] + met["rects"][0][1])
                _jx = int(_ox0 + (_cx - _px0) * _sc)
                cv2.line(out, (max(0, min(_W - 1, _jx)), 0),
                         (max(0, min(_W - 1, _jx)), _H - 1), (255, 0, 255), 2)
                cv2.putText(out, "ref x=%d" % int(round(_cx)), (max(0, min(_W - 160, _jx + 4)), 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
            except Exception:                                                # noqa: BLE001
                pass
        banner = ""
    else:
        age = max(0.0, time.time() - float(_V31_ST.get("ts") or time.time()))
        ytxt = ("y=%d-%d" % (int(band[0]), int(band[1]))) if band else "y=?"
        if n == 0:
            headline = "未识别到金手指键排"
            line2 = "本帧未检出周期键排结构 · %s · 帧龄%.1fs" % (ytxt, age)
        else:
            headline = "识别 %d 根 ≠ %d，已抑制显示" % (n, _V31_N_TARGET)
            line2 = "当前拍到 y=%s · 节距%s · 帧龄%.1fs" % (
                ("%d-%d" % (int(band[0]), int(band[1]))) if band else "?",
                ("%.0fpx" % pitch) if pitch > 0 else "?", age)
        line3 = "金手指真值应为 %d 根；未达标的帧不画出框" % _V31_N_TARGET
        rows = [(headline, "NO GOLD-FINGER ROW (suppressed)"),
                (line2, "n_keys=%d need=%d band=%s pitch=%.0f age=%.1fs" % (
                    n, _V31_N_TARGET, ytxt, pitch, age)),
                (line3, "true count expected = %d" % _V31_N_TARGET)]
        # 🔴 v33: **保留画面** —— 有判据图就在它上面打横幅; 只有完全没有图时才退回黑底横幅。
        if img is not None:
            out = _v31_overlay(img, rows, (0, 0, 200))
        else:
            out = _v31_banner(_hw, rows, (0, 0, 200))
        banner = headline + " | " + line2
        boxes = []
    # ---- 同姿位 + 同判决 ⇒ 直接回放上帧输出(逐像素相同) ----
    if (scene_same and _V31_ST.get("out") is not None
            and _V31_ST.get("ret_state") == state):
        out = _V31_ST["out"]
        met = dict(_V31_ST.get("ret_met") or met)
    else:
        _V31_ST["out"] = np.ascontiguousarray(out).copy()
        _V31_ST["ret_state"] = state
        _V31_ST["banner"] = banner
        _V31_ST["boxes"] = boxes
        _V31_ST["n"] = n
    _V31_ST["scene"] = thumb
    met["ver"] = _JUDGE_VER
    met["gate"] = {"state": state, "ok": bool(ok),
                   "n_keys": int(_V31_ST.get("n") if _V31_ST.get("n") is not None else n),
                   "n_keys_raw": n,
                   "pitch": round(pitch, 1),
                   "band": ([int(band[0]), int(band[1])] if band else None), "band_h": bh,
                   "geo_ok": bool(geo_ok), "band_ok": bool(band_ok),
                   "scene_same": bool(scene_same)}
    met["gate_banner"] = _V31_ST["banner"]
    met["gate_boxes"] = _V31_ST["boxes"]
    return out, met


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
            judge, jmeta = render_judge_gated(bgr, deskew_deg=float(info.get("angle") or 0.0))
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
                _gst = ((jmeta.get("gate") or {}).get("state") or "shown")
                jmeta["state"] = "ok" if _gst == "shown" else "suppressed_19gate"
                if _gst == "shown":
                    _v22_remember_good(judge, no, _v22_view_key_from_crop(crop))   # v31: 只有"真键排(19)"的好图才记为可顶用的好图
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
                                                   "state", "ver", "why", "err", "n_keys", "attempt",
                                                   "lattice_pitch_px", "gate", "gate_banner", "gate_boxes",
                                                   "v36_live", "v36_sharp", "v36_lattice", "v36_phase",
                                                   "v36_phase_bad", "rects", "centers")},
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
      重启服务后: 先按**本机落盘** cam_param_persist.json **自动复原**(v30 层①), 无落盘才回到文件默认。
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
    if applied and not _fail:
        # 🆕 v30 层①: 现场实时改档成功后**立即落盘** ⇒ 任何重启都由服务自己复原(不靠部署脚本)
        _write_cam_param_persist("服务/param")
    _hint = ""
    if _fail:
        _hint = ("相机在采集中拒绝写 %s (实测本机型只能在不采集时写) ⇒ 请改本文件里的常数并重启服务; "
                 "切勿尝试停采集再写 —— 本机型会卡死相机" % ",".join(_fail))
    return jsonify({"code": 200, "ok": not _fail, "applied": applied, "hint": _hint, "now": dict(_CAM_LIVE),
                    "file_defaults": {"exposure_us": EXPOSURE_US, "gain_db": GAIN_DB,
                                      "gamma_val": GAMMA_VAL},
                    "note": "只改相机采集参数(曝光/增益/Gamma); 重启服务先按本机落盘 cam_param_persist.json 自动复原(v30 层①), 无落盘才回 file_defaults"})


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
    _RUN_PORT = str(_port)          # 🆕 v30: 落盘/复原档位的键 = 实际运行端口
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
