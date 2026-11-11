# -*- coding: utf-8 -*-
"""本机 AOI 服务的「Windows SDK 桩」——让产线程序**原样**在 Linux 上被 import。

产线文件 (`prod/gold_10082_prod.py` / `prod/surface_10083_prod.py`) 与工控机现役
**逐字节一致** (sha256 见 PROD_SHA256), 它们 import 的是工控机上的 Windows 专有件:

    SciCam_class / SciCamErrorDefine_const / SciCamInfo_header / SciCamPayload_header
    yolo_detector / gf_crop

本机没有这些件, 也不该有(相机是 OPT 的 Windows SDK)。这里的桩让模块能加载,
**判据/渲染/几何那些纯 numpy+cv2 的代码一行不改地跑起来**; 取图与 YOLO 由
本服务自己的「帧源」和「本机模型」提供 —— 谁提供了什么, 回执里都写明。

🔴 桩只提供「能加载」, 绝不伪造相机成功: 任何走过取图的路由在本机一律回
   `ok=false, why=camera_absent`, 不许编一张假图。
"""
from __future__ import annotations

import sys
import types


class _AnyCallable:
    """任何名字都当常量 0 / 可调用对象 —— 覆盖产线文件里用到的全部 SDK 符号。"""

    def __init__(self, name: str):
        self._name = name

    def __call__(self, *a, **k):
        return 0

    def __getattr__(self, item):
        return _AnyCallable(f"{self._name}.{item}")

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __bool__(self):
        return False

    def __repr__(self):
        return f"<stub {self._name}>"


# 产线文件 `from SciCam_class import *` ⇒ 桩模块必须给出**确定的导出名**,
# 否则 importlib 会去迭代模块的 __getattr__ 返回值 (TypeError: not iterable)。
_SCI_NAMES = """
SciCam_CloseDevice SciCam_CreateDevice SciCam_DeleteDevice SciCam_DiscoveryDevices
SciCam_FreePayload SciCam_Grab SciCam_OpenDevice SciCam_Payload_ConvertImage
SciCam_Payload_GetAttribute SciCam_Payload_GetImage SciCam_Payload_SaveImage
SciCam_SetEnumValue SciCam_SetEnumValueByString SciCam_SetFloatValue
SciCam_SetGrabStrategy SciCam_StartGrabbing SciCam_StopGrabbing
SciCam_TLType_Gige SciCam_TLType_Usb SciCam_PayloadMode_MultiFrame SciCam_PayloadMode_Single
""".split()


def _mod(name: str, extra: dict | None = None) -> types.ModuleType:
    m = types.ModuleType(name)
    for _n in _SCI_NAMES:
        setattr(m, _n, _AnyCallable(f"{name}.{_n}"))
    for k, v in (extra or {}).items():
        setattr(m, k, v)
    m.__all__ = [k for k in m.__dict__ if not k.startswith("_")]
    return m


class SciCamera:                                    # noqa: D101 - 产线就是这么用的
    def __init__(self, *a, **k):
        self.opened = False

    def __getattr__(self, item):
        return lambda *a, **k: 0


class YoloDetector:                                 # noqa: D101
    """产线用它做缺陷判决; 本机服务**不用它**(用 models/yolo_gold_v2.pt 或只出判据)。"""

    def __init__(self, *a, **k):
        self.ready = False

    def detect(self, *a, **k):
        raise RuntimeError("本机服务不提供产线加密权重 (bestgf/besthousing .pt.enc)")

    def __getattr__(self, item):
        return lambda *a, **k: 0


class GoldFingerCropper:                            # noqa: D101
    """产线模板法裁剪器 (Windows 侧带模板). 本机不做模型输入派生 ⇒ 调用即报错, 不假造。"""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, item):
        def _no(*a, **k):
            raise RuntimeError("本机无产线模板/裁剪器 (tz_gf_crop); 判据渲染不依赖它")
        return _no


def annotate(img, *a, **k):                          # noqa: D103
    return img


def install() -> None:
    """把桩装进 sys.modules (幂等)。必须在 import 产线文件之前调用。"""
    if getattr(install, "_done", False):
        return
    consts = {
        "SCI_CAMERA_OK": 0,
        "SCI_CAM_PAYLOAD_ATTRIBUTE": "attribute",
        "SCI_DEVICE_INFO_LIST": list,
        "SCI_NODE_VAL_FLOAT": dict,
        "SCI_PAYLOAD_MODE_NONE": 0,
    }
    sys.modules.setdefault("SciCam_class", _mod("SciCam_class", {"SciCamera": SciCamera}))
    sys.modules.setdefault("SciCamErrorDefine_const", _mod("SciCamErrorDefine_const", consts))
    sys.modules.setdefault("SciCamInfo_header", _mod("SciCamInfo_header"))
    sys.modules.setdefault("SciCamPayload_header", _mod("SciCamPayload_header"))
    sys.modules.setdefault("yolo_detector", _mod("yolo_detector", {"YoloDetector": YoloDetector}))
    sys.modules.setdefault("gf_crop", _mod("gf_crop", {"GoldFingerCropper": GoldFingerCropper,
                                                      "annotate": annotate}))
    install._done = True
