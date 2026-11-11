# -*- coding: utf-8 -*-
"""本机 AOI 镜像服务 —— 路由/语义对齐工控机 10082(金手指) / 10083(表面)。

真源与差异 (必须让调用方看得见, 不许"看着一样"就当一样):
  ✅ 判据渲染: 直接 exec 产线现役文件 (`prod/*.py`, sha256 与工控机一致) —— 判据图/几何量同源。
  ✅ 路由与回执语义: /capture_detect /picture /crop_info /last_result /storage /health /version
     (+ 工控机的 /preview.jpg · 金手指 /param · 表面 /exposure) 名字与形态一致。
  ⛔ 相机: OPT 的 Windows SDK 只装在工控机 ⇒ 本机**没有相机**。像素来自帧源 (见 sources.py):
     工控机在跑时取它的原图; 停机时用 file:/dir:/push (录制回放/推帧), 绝不生成假图。
  ⛔ 缺陷模型: 产线权重是加密件 (bestgf05088.pt.enc / besthousing_zh0128.pt.enc) 只在工控机。
     本机可选 ZMAX_AOI_LOCAL_YOLO=1 用 models/yolo_gold_v2.pt 做**观测**(源标注 local-yolo),
     不参与默认判决 (未证明同口径提升, 沿用技能里的铁律)。

启动:
    python run.py --kind gold --port 20082
    python run.py --kind surface --port 20083
"""
from __future__ import annotations

import json
import os
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

try:
    from . import prodload, sources
except ImportError:                      # 直接跑脚本
    import prodload                      # type: ignore[no-redef]
    import sources                       # type: ignore[no-redef]

_LOCK = threading.Lock()
_YOLO = {"m": None, "path": None, "err": None, "dev": None}


def _now() -> float:
    return time.time()


class Mirror:
    """一个视角的本机镜像状态 (进程内, 与产线一样是"最近一次"语义)。"""

    def __init__(self, kind: str):
        self.kind = kind
        self.st: dict = {
            "origin": None, "judge": None, "natural": None,
            "last_pic_t": 0.0, "last_result": {}, "crop_info": {},
            "pushed": None, "pushed_t": 0.0, "n": 0,
        }
        self.mod = prodload.load(kind) if os.environ.get("ZMAX_AOI_LOCAL_PRELOAD", "1") == "1" else None

    # ---------- 取帧 ----------
    def _frame(self, grab: bool):
        """grab=True: 向帧源要新帧; False: 用内存里最近一帧 (与产线 /picture 不带 grab 同义)。"""
        if not grab and self.st["origin"] is not None:
            return self.st["origin"], {"ok": True, "how": "memory", "kind": self.kind, "ms": 0.0}
        if self.st["pushed"] is not None and self.st["pushed_t"] > self.st["last_pic_t"]:
            bgr = self.st["pushed"]
            self.st["pushed"] = None                     # 一次性: 一帧只消费一次
            return bgr, {"ok": True, "how": "push", "kind": self.kind, "ms": 0.0}
        return sources.grab(self.kind)

    # ---------- 判据 ----------
    def judge(self, bgr):
        t0 = time.time()
        if self.kind == "gold":
            img, met = prodload.judge_gold(bgr, 0.0)
        else:
            img, met = prodload.judge_surface(bgr)
        return img, (met or {}), round((time.time() - t0) * 1000, 1)

    def _verdict(self, met: dict, img) -> tuple:
        """本机口径的判决 + 为什么。区别产线的地方明写在 basis 里。"""
        if self.kind == "gold":
            n = int(met.get("n_keys") or 0)
            st = met.get("state")
            if img is None:
                return "NO_JUDGE", 2, "判据渲染失败"
            if st == "suppressed":
                return "JUDGE_GATED", 2, f"19 根门抑制 (n_keys={n}) — 判据图仍出"
            if n <= 0:
                return "NO_TARGET", 2, "判据里没有金手指键"
            return "JUDGE_OK", 1, f"n_keys={n} · pitch={met.get('lattice_pitch_x_px') or met.get('lattice_pitch_px')}"
        ok = bool(met.get("ok"))
        if img is None or not ok:
            return "JUDGE_FAIL", 2, f"判据未通过: {met.get('why')}"
        return "JUDGE_OK", 1, "表面判据通过 (厚度/台阶几何在本机算出)"

    # ---------- 主流程 ----------
    def detect(self, grab: bool = True) -> dict:
        t0 = time.time()
        with _LOCK:
            bgr, smet = self._frame(grab)
            if bgr is None:
                r = {"code": 200, "ok": False, "msg": "无帧", "verdict": "NO_FRAME",
                     "why": smet.get("why"), "source": smet, "detect_type": self.kind,
                     "ms": round((time.time() - t0) * 1000, 1)}
                self.st["last_result"] = dict(r, t=_now())
                return r
            img, met, jms = self.judge(bgr)
            verdict, code, why = self._verdict(met, img)
            self.st["n"] += 1
            self.st["origin"] = bgr
            self.st["last_pic_t"] = _now()
            if img is not None:
                self.st["judge"] = img
            r = {
                "code": 200, "ok": True, "msg": "success", "detect_type": self.kind,
                "verdict": verdict, "vcode": code, "why": why,
                "count": None, "defects": [], "ms": jms,
                "judge_ver": met.get("ver") or met.get("judge_ver"),
                "judge_meta": met, "n": self.st["n"],
                "model": "production-encrypted(不在本机) —— verdict 来自判据几何, 不是产线 YOLO",
                "basis": "local-judge (同源判据代码)",
                "source": smet, "t": _now(), "frame": [int(bgr.shape[1]), int(bgr.shape[0])],
                "total_ms": round((time.time() - t0) * 1000, 1),
            }
            self.st["crop_info"] = {
                "code": 200, "ts": r["t"], "detect_type": self.kind, "judge_ver": r["judge_ver"],
                "judge": met, "frame": r["frame"], "source": smet, "basis": r["basis"],
                "note": "本机镜像: 判据量同源; 模板法裁剪/模型输入(960·1280)需要产线模板, 本机不派生",
            }
            self.st["last_result"] = r
            return r

    def yolo(self, log=None):
        """可选: 本机 YOLO 观测 (ZMAX_AOI_LOCAL_YOLO=1)。默认关。"""
        if self.kind != "gold" or os.environ.get("ZMAX_AOI_LOCAL_YOLO") != "1":
            return None
        if _YOLO["m"] is None:
            try:
                from ultralytics import YOLO
                p = os.environ.get("ZMAX_GOLD_YOLO_W") or os.path.join(
                    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")),
                    "models", "yolo_gold_v2.pt")
                _YOLO.update(m=YOLO(p), path=p, err=None)
            except Exception as e:                                   # noqa: BLE001
                _YOLO["err"] = f"{type(e).__name__}: {e}"
                return None
        if _YOLO["m"] is None or self.st["origin"] is None:
            return None
        kw = {"imgsz": 512, "conf": 0.25, "verbose": False}
        if os.environ.get("ZMAX_GOLD_YOLO_DEVICE"):
            kw["device"] = os.environ["ZMAX_GOLD_YOLO_DEVICE"]
        try:
            r = _YOLO["m"].predict(self.st["origin"], **kw)[0]
            return {"n": len(getattr(r, "boxes", []) or []), "src": "local-yolo", "weights": os.path.basename(_YOLO["path"] or "")}
        except Exception as e:                                       # noqa: BLE001
            return {"err": f"{type(e).__name__}: {e}", "src": "local-yolo"}


def _jpeg(bgr, q: int = 90):
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), q])
    return buf.tobytes() if ok else b""


def make_app(kind: str, port: int) -> Flask:
    app = Flask(f"aoi_local_{kind}")
    M = Mirror(kind)

    @app.get("/health")
    def health():
        sp = sources.kind_src(kind)
        return jsonify({"ok": True, "kind": kind, "port": port, "version": "local-mirror-v1",
                        "prod_version": getattr(M.mod, "VERSION", None) if M.mod else None,
                        "src": sp, "camera": "absent (OPT Windows SDK 只在工控机)",
                        "prod": prodload.info()["kinds"].get(kind),
                        "have_frame": M.st["origin"] is not None})

    @app.get("/version")
    def version():
        return jsonify({"code": 200, "version": "local-mirror-v1",
                        "prod_version": getattr(M.mod, "VERSION", None) if M.mod else None,
                        "kind": kind, "port": port})

    @app.post("/frame")
    def push_frame():
        """推一帧进来 (raw body 或 multipart 'file') —— 工控机停机时的正规用法。"""
        # 🔴 顺序有讲究: 碰 request.files 会**先解析表单并吃掉请求体**, 之后 get_data() 只剩空串
        #    ⇒ 推帧会"200 但 frame=None"(实测踩到)。所以按 Content-Type 分流, raw 体绝不在解析之后取。
        raw = None
        _ct = (request.content_type or "").lower()
        if "multipart/form-data" in _ct:
            _f = request.files.get("file")
            raw = _f.read() if _f is not None else None
        if not raw:
            raw = request.get_data(cache=False) or None
        if not raw:
            _f = request.files.get("file")
            raw = _f.read() if _f is not None else None
        bgr = sources._decode(raw) if raw else None
        if bgr is None:
            return jsonify({"code": 200, "ok": False, "why": "空/无法解码 (raw body 或 multipart file)"})
        M.st["pushed"] = bgr
        M.st["pushed_t"] = _now()
        return jsonify({"code": 200, "ok": True, "frame": [int(bgr.shape[1]), int(bgr.shape[0])],
                        "bytes": len(raw or b"")})

    @app.post("/capture_detect")
    def capture_detect():
        grab = request.args.get("grab", "1") not in ("0", "false", "no")
        r = M.detect(grab=grab)
        return jsonify(r), 200

    @app.get("/picture")
    @app.post("/picture")
    def picture():
        k = (request.args.get("kind") or "origin").lower()
        want_grab = request.args.get("grab") in ("1", "true", "yes")
        if k in ("origin", "raw"):
            if want_grab or M.st["origin"] is None:
                bgr, smet = M._frame(grab=True)
                if bgr is not None:
                    M.st["origin"], M.st["last_pic_t"] = bgr, _now()
            else:
                bgr = M.st["origin"]
            if bgr is None:
                return jsonify({"code": 404, "msg": "尚无照片", "source": M.st.get("last_source")}), 404
            return Response(_jpeg(bgr), mimetype="image/jpeg")
        if k in ("judge", "crop", "topview"):
            if M.st["judge"] is None:
                r = M.detect(grab=want_grab)
                if r.get("verdict") == "NO_FRAME":
                    return jsonify({"code": 404, "msg": "尚无判据图", "why": r.get("why")}), 404
            if M.st["judge"] is None:
                return jsonify({"code": 404, "msg": "判据渲染失败"}), 404
            return Response(_jpeg(M.st["judge"]), mimetype="image/jpeg")
        if k == "natural":
            if M.st["origin"] is None:
                return jsonify({"code": 404, "msg": "尚无照片"}), 404
            return Response(_jpeg(M.st["origin"]), mimetype="image/jpeg")
        return jsonify({"code": 400, "msg": f"未知 kind={k} (origin|judge|crop|natural)"}), 400

    @app.get("/preview.jpg")
    def preview():
        if request.args.get("meta") in ("1", "true"):
            bgr, smet = sources.grab(kind)
            return jsonify({"code": 200 if bgr is not None else 404, "source": smet,
                            "frame": None if bgr is None else [int(bgr.shape[1]), int(bgr.shape[0])]})
        bgr, smet = M._frame(grab=True)
        if bgr is None:
            return jsonify({"code": 404, "msg": "无帧", "why": smet.get("why")}), 404
        M.st["origin"], M.st["last_pic_t"] = bgr, _now()
        M.st["last_source"] = smet
        return Response(_jpeg(bgr), mimetype="image/jpeg")

    @app.get("/last_result")
    def last_result():
        if not M.st["last_result"]:
            return jsonify({"code": 404, "msg": "尚无检测结果"}), 404
        r = dict(M.st["last_result"])
        r["age_s"] = round(_now() - (r.get("t") or _now()), 2)
        y = M.yolo()
        if y:
            r["local_yolo"] = y
        return jsonify(r)

    @app.get("/crop_info")
    def crop_info():
        if not M.st["crop_info"]:
            return jsonify({"code": 404, "msg": "尚无裁剪记录"}), 404
        return jsonify(M.st["crop_info"])

    @app.get("/storage")
    def storage():
        d = prodload.workdir(kind)
        files = [f for f in os.listdir(d) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        return jsonify({"code": 200, "dir": d, "files_total": len(files),
                        "n": M.st["n"], "memory_frame": M.st["origin"] is not None,
                        "note": "本机镜像只存最近的判据/原图 (内存优先), 不落产线那种批量图"})

    @app.route("/param", methods=["GET", "POST"])
    @app.route("/exposure", methods=["GET", "POST"])
    def camera_param():
        return jsonify({"code": 200, "ok": False, "why": "camera_absent",
                        "note": "本机没有 OPT 相机 (Windows SDK 只在工控机) —— 曝光/增益请对工控机 10082/10083 下发",
                        "kind": kind, "method": request.method})

    @app.get("/source")
    def source():
        return jsonify({"code": 200, "kind": kind, "src": sources.kind_src(kind),
                        "spec_help": "remote:<host> | cam:<url> | file:<path> | dir:<path> | push"})

    return app


def run(kind: str, port: int, host: str = "0.0.0.0"):
    app = make_app(kind, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
