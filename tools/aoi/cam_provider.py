#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX AOI frame provider -- camera shutter only, no detection (2026-11-11).

Purpose
-------
The OPT cameras are wired to the plant PC (Windows) and their driver (SciCam SDK)
exists only there. The 4060 host does the judging / detection. So the plant PC
only has to hand out frames:

    plant PC (this file):  open camera -> grab -> JPEG -> HTTP
    4060 host:             GET /picture?kind=origin&grab=1 -> judge locally

Why not just run the full AOI program?  Because it loads YOLO, renders judge
pictures and writes images on every request; this provider does none of that:
one grab + one JPEG encode, no disk writes, no model, no judge.

Routes (drop-in compatible with the AOI program for frame consumers)
--------------------------------------------------------------------
    GET  /health                       JSON: camera state, sn, fps, last grab ms
    GET  /status                       JSON: same as /health (alias)
    GET  /preview.jpg[?scale=0.5&q=90]  one JPEG
    GET  /picture?kind=origin[&grab=1]  one JPEG (alias, same bytes)
    GET  /picture?meta=1                JSON only, no image
    GET  /param                         JSON: exposure/gain/gamma read back
    POST /param?exposure=<us>&gain=<dB> write to the running camera (honest reply)
    POST /param?auto=off                switch ExposureAuto/GainAuto off

Rules
-----
* ASCII only (PS 5.1 / GBK consoles corrupt non-ASCII scripts on that machine).
* Never fake a frame: if the camera cannot be opened or grabbed, reply
  HTTP 503 with ok=false and a reason. No cached old picture is served.
* Camera is exclusive: stop the AOI program first (same SN), otherwise the
  open call fails and /health says so.

Usage (plant PC)
----------------
    python cam_provider.py --port 10083 --sn D265250099 --exposure 80000 --gain 1.8
    python cam_provider.py --port 10082 --sn D265250070 --exposure 24000 --gain 8
"""
from __future__ import annotations

import argparse
import ctypes
import io
import json
import os
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

from SciCam_class import *            # noqa: F401,F403  (SciCamera, SciCamTLType, ...)
from SciCamErrorDefine_const import *  # noqa: F401,F403
from SciCamInfo_header import *       # noqa: F401,F403
from SciCamPayload_header import *    # noqa: F401,F403

APP = Flask(__name__)
CAM = {
    "dev": None, "open": False, "sn": None,
    "exposure": None, "gain": None, "gamma": 1.0,
    "w": 0, "h": 0, "n": 0, "fails": 0,
    "last_ms": None, "last_t": None, "err": None,
}
LOCK = threading.Lock()


# ------------------------------------------------------------------ camera ----
def find_dev_by_sn(target_sn):
    devInfos = SCI_DEVICE_INFO_LIST()
    reVal = SciCamera.SciCam_DiscoveryDevices(
        devInfos, SciCamTLType.SciCam_TLType_Gige | SciCamTLType.SciCam_TLType_Usb3)
    if reVal != SCI_CAMERA_OK or devInfos.count == 0:
        CAM["err"] = "discovery failed or no device"
        return None
    for i in range(devInfos.count):
        cam_obj = devInfos.pDevInfo[i]
        if cam_obj.tlType != SciCamTLType.SciCam_TLType_Gige:
            continue
        sn = bytes(cam_obj.info.gigeInfo.serialNumber).strip(b"\x00").decode("utf-8", "replace")
        if sn == target_sn:
            return cam_obj
    CAM["err"] = "sn %s not found" % target_sn
    return None


def _set_float(name, val, alts=()):
    ret = CAM.get("_dev_handle").SciCam_SetFloatValue(name, float(val))
    if ret == SCI_CAMERA_OK:
        return True
    for alt in alts:
        if abs(float(alt) - float(val)) < 1e-9:
            continue
        if CAM["_dev_handle"].SciCam_SetFloatValue(name, float(alt)) == SCI_CAMERA_OK:
            return True
    return False


def open_camera(sn):
    with LOCK:
        if CAM["open"]:
            return True, "already open"
        dev = find_dev_by_sn(sn)
        if dev is None:
            return False, CAM.get("err") or "no device"
        h = SciCamera()
        CAM["_dev_handle"] = h
        if h.SciCam_CreateDevice(dev) != SCI_CAMERA_OK:
            return False, "CreateDevice failed (camera busy?)"
        if h.SciCam_OpenDevice() != SCI_CAMERA_OK:
            return False, "OpenDevice failed (another program owns the camera?)"
        h.SciCam_SetGrabStrategy(2)
        _apply(exposure=CAM["exposure"], gain=CAM["gain"], gamma=CAM["gamma"])
        if h.SciCam_StartGrabbing() != SCI_CAMERA_OK:
            try:
                h.SciCam_CloseDevice()
                h.SciCam_DeleteDevice()
            except Exception:                                        # noqa: BLE001
                pass
            return False, "StartGrabbing failed"
        time.sleep(0.8)
        CAM.update(open=True, dev=dev, sn=sn, err=None)
        return True, "opened"


def close_camera():
    with LOCK:
        h = CAM.get("_dev_handle")
        if h is not None:
            for fn in ("SciCam_StopGrabbing", "SciCam_CloseDevice", "SciCam_DeleteDevice"):
                try:
                    getattr(h, fn)()
                except Exception:                                    # noqa: BLE001
                    pass
        CAM.update(open=False, dev=None)


def _auto_off():
    h = CAM.get("_dev_handle")
    if h is None:
        return {"auto": "no camera handle"}
    out = {}
    for name in ("ExposureAuto", "GainAuto"):
        try:
            out[name] = (h.SciCam_SetEnumValueByString(name, "Off") == SCI_CAMERA_OK)
        except Exception as e:                                       # noqa: BLE001
            out[name] = "err %s" % type(e).__name__
    return out


def _apply(exposure=None, gain=None, gamma=None):
    res = {}
    if exposure is not None:
        CAM["exposure"] = float(exposure)
        res["exposure"] = _set_float("ExposureTime", exposure)
    if gain is not None and float(gain) > 0:
        CAM["gain"] = float(gain)
        res["gain"] = _set_float("Gain", gain, alts=(float(gain) * 2, int(float(gain)), 8.0))
    if gamma is not None:
        CAM["gamma"] = float(gamma)
        res["gamma"] = _set_float("Gamma", gamma)
    return res


def grab_bgr():
    """One grab -> BGR ndarray, or (None, reason). Retries with reconnect."""
    t0 = time.time()
    for attempt in range(3):
        ok, why = open_camera(CAM["sn"]) if not CAM["open"] else (True, "")
        if not ok:
            if attempt == 2:
                CAM["fails"] += 1
                return None, why
            time.sleep(0.4)
            continue
        h = CAM["_dev_handle"]
        ppayload = ctypes.c_void_p()
        if h.SciCam_Grab(ppayload) != SCI_CAMERA_OK:
            CAM["fails"] += 1
            close_camera()
            time.sleep(0.3)
            continue
        attr = SCI_CAM_PAYLOAD_ATTRIBUTE()
        if SciCam_Payload_GetAttribute(ppayload, attr) != SCI_CAMERA_OK:
            h.SciCam_FreePayload(ppayload)
            continue
        if not bool(attr.isComplete) or attr.payloadMode != SciCamPayloadMode.SciCam_PayloadMode_2D:
            h.SciCam_FreePayload(ppayload)
            continue
        iw, ih = attr.imgAttr.width, attr.imgAttr.height
        ptype = attr.imgAttr.pixelType
        mono_set = {SciCamPixelType.Mono8, SciCamPixelType.Mono10, SciCamPixelType.Mono12}
        is_mono = ptype in mono_set
        ttype = SciCamPixelType.Mono8 if is_mono else SciCamPixelType.RGB8
        nch = 1 if is_mono else 3
        imgData = ctypes.c_void_p()
        if SciCam_Payload_GetImage(ppayload, imgData) != SCI_CAMERA_OK:
            h.SciCam_FreePayload(ppayload)
            continue
        size = ctypes.c_int()
        if SciCam_Payload_ConvertImage(attr.imgAttr, imgData, ttype, None, size, True) != SCI_CAMERA_OK:
            h.SciCam_FreePayload(ppayload)
            continue
        buf = (ctypes.c_ubyte * size.value)()
        if SciCam_Payload_ConvertImage(attr.imgAttr, imgData, ttype, buf, size, True) != SCI_CAMERA_OK:
            h.SciCam_FreePayload(ppayload)
            continue
        arr = np.frombuffer(buf, dtype=np.uint8).reshape(ih, iw, nch)
        h.SciCam_FreePayload(ppayload)
        bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR) if nch == 1 else cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        CAM.update(w=iw, h=ih, n=CAM["n"] + 1, err=None,
                   last_ms=round((time.time() - t0) * 1000, 1), last_t=time.time())
        return bgr, None
    return None, CAM.get("err") or "grab failed 3x"


def jpeg(bgr, scale=1.0, q=90):
    if scale and abs(scale - 1.0) > 1e-6:
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(q)])
    return enc.tobytes() if ok else b""


# ------------------------------------------------------------------- routes ---
@APP.get("/health")
@APP.get("/status")
def health():
    age = None if CAM["last_t"] is None else round(time.time() - CAM["last_t"], 2)
    return jsonify({"ok": True, "role": "frame-provider (no detection)",
                    "cam_open": CAM["open"], "sn": CAM["sn"], "w": CAM["w"], "h": CAM["h"],
                    "exposure_us": CAM["exposure"], "gain_db": CAM["gain"], "gamma": CAM["gamma"],
                    "grabs": CAM["n"], "fails": CAM["fails"], "last_grab_ms": CAM["last_ms"],
                    "last_frame_age_s": age, "err": CAM["err"], "port": PORT})


@APP.get("/preview.jpg")
def preview():
    scale = float(request.args.get("scale", "1.0"))
    q = int(request.args.get("q", "90"))
    if request.args.get("meta") in ("1", "true"):
        bgr, why = grab_bgr()
        if bgr is None:
            return jsonify({"code": 503, "ok": False, "why": why}), 503
        return jsonify({"code": 200, "ok": True, "grab_ms": CAM["last_ms"],
                        "frame": [int(bgr.shape[1]), int(bgr.shape[0])]})
    bgr, why = grab_bgr()
    if bgr is None:
        return jsonify({"code": 503, "ok": False, "why": why, "stage": "grab"}), 503
    return Response(jpeg(bgr, scale, q), mimetype="image/jpeg",
                    headers={"X-Grab-Ms": str(CAM["last_ms"]), "X-Sn": str(CAM["sn"])})


@APP.get("/picture")
@APP.post("/picture")
def picture():
    if request.args.get("meta") in ("1", "true"):
        return jsonify({"code": 200, "ok": CAM["open"], "sn": CAM["sn"],
                        "frame": [CAM["w"], CAM["h"]], "exposure_us": CAM["exposure"]})
    bgr, why = grab_bgr()
    if bgr is None:
        return jsonify({"code": 503, "ok": False, "why": why, "stage": "grab"}), 503
    return Response(jpeg(bgr, float(request.args.get("scale", "1.0")), int(request.args.get("q", "92"))),
                    mimetype="image/jpeg", headers={"X-Grab-Ms": str(CAM["last_ms"])})


@APP.route("/param", methods=["GET", "POST"])
def param():
    if request.method == "GET":
        return jsonify({"code": 200, "exposure_us": CAM["exposure"], "gain_db": CAM["gain"],
                        "gamma": CAM["gamma"], "cam_open": CAM["open"]})
    out = {"code": 200}
    if request.args.get("auto") == "off":
        out["auto"] = _auto_off()
    exp = request.args.get("exposure") or request.args.get("us")
    g = request.args.get("gain")
    gm = request.args.get("gamma")
    if exp is not None or g is not None or gm is not None:
        res = _apply(exposure=exp, gain=g, gamma=gm) if CAM["open"] else {"note": "camera not open"}
        out["applied"] = res
        out["exposure_us"] = CAM["exposure"]
        out["gain_db"] = CAM["gain"]
        # settle: throw the next frame away (exposure change needs one frame to take effect)
        bgr, _ = grab_bgr()
        out["settled"] = bgr is not None
    return jsonify(out)


def main():
    global PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=10083)
    ap.add_argument("--sn", default=os.environ.get("AOI_SN", "D265250099"))
    ap.add_argument("--exposure", type=float, default=float(os.environ.get("AOI_EXPOSURE", "80000")))
    ap.add_argument("--gain", type=float, default=float(os.environ.get("AOI_GAIN", "1.8")))
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--no-auto-off", action="store_true")
    a = ap.parse_args()
    PORT = a.port
    CAM.update(sn=a.sn, exposure=a.exposure, gain=a.gain, gamma=a.gamma)
    print("[provider] port=%s sn=%s exposure=%s gain=%s" % (a.port, a.sn, a.exposure, a.gain))
    ok, why = open_camera(a.sn)
    print("[provider] camera: %s (%s)" % (ok, why))
    if ok and not a.no_auto_off:
        print("[provider] auto off:", _auto_off())
        _apply(exposure=a.exposure, gain=a.gain, gamma=a.gamma)
    APP.run(host="0.0.0.0", port=a.port, threaded=True, use_reloader=False)


PORT = 10083

if __name__ == "__main__":
    main()
