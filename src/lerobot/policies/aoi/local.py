# -*- coding: utf-8 -*-
"""本机 AOI 镜像服务的客户端 (节点侧「旁路」入口)。

链路:
    node_ss_aoi → policies/aoi/quality.inspect_aoi
                 → **local_bypass()**  ← 本文件: 打本机镜像服务 (20082/20083)
                 → 失败才回落 gold.gold_bypass / surface.surface_bypass (工控机 10082/10083)

为什么需要这一层:
  工控机的产线程序一旦停机, 10082/10083 就没有任何响应 —— 节点那三路旁路全部降级成
  "unavailable"。本机镜像是把产线**同一份判据代码**搬过来跑 (service/prod/*.py, sha256 一致),
  像素由帧源提供 (remote/cam/file/dir/push) ⇒ 停机也能出判据图 + 判据量。

开关:
    ZMAX_AOI_LOCAL=auto (默认, 能连上就用) | 1 (强制) | 0 (关掉, 只走工控机)
    ZMAX_AOI_LOCAL_HOST=127.0.0.1
    ZMAX_AOI_LOCAL_GOLD_PORT=20082  ZMAX_AOI_LOCAL_SURFACE_PORT=20083
"""
from __future__ import annotations

import json
import os
import socket
import time as _t
import urllib.request as _urq

_DOWN: dict = {}          # kind -> 冷却到期时刻 (服务没起来时不要每拍都等它)
_COOLDOWN = float(os.environ.get("ZMAX_AOI_LOCAL_COOLDOWN_S", "30"))
_UA = {"User-Agent": "zmax-aoi-local-client"}

PORTS = {"gold": int(os.environ.get("ZMAX_AOI_LOCAL_GOLD_PORT", "20082")),
         "surface": int(os.environ.get("ZMAX_AOI_LOCAL_SURFACE_PORT", "20083"))}


def mode() -> str:
    return (os.environ.get("ZMAX_AOI_LOCAL") or "auto").strip().lower()


def host() -> str:
    return os.environ.get("ZMAX_AOI_LOCAL_HOST") or "127.0.0.1"


def _url(kind: str, path: str) -> str:
    return f"http://{host()}:{PORTS[kind]}{path}"


def available(kind: str, timeout: float = 0.3) -> bool:
    """只探端口 (不取图): 服务没起时 0.3s 内返回 False, 不拖节拍。"""
    if mode() == "0":
        return False
    if _t.time() < _DOWN.get(kind, 0.0):
        return False
    try:
        socket.create_connection((host(), PORTS[kind]), timeout=timeout).close()
        return True
    except OSError:
        _DOWN[kind] = _t.time() + _COOLDOWN
        return False


def _get_json(kind: str, path: str, timeout: float = 30.0):
    req = _urq.Request(_url(kind, path), headers=_UA)
    try:
        with _urq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except _urq.HTTPError as he:
        try:
            return json.loads(he.read().decode("utf-8", "replace"))
        except Exception:                                              # noqa: BLE001
            return {"code": he.code, "msg": f"HTTP {he.code}"}


def _post_json(kind: str, path: str, timeout: float = 30.0):
    """🔴 /capture_detect 只收 POST —— 用 GET 会拿 405, 却看着像"服务没反应"(实测踩过)。"""
    req = _urq.Request(_url(kind, path), data=b"", headers=_UA, method="POST")
    try:
        with _urq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except _urq.HTTPError as he:
        try:
            return json.loads(he.read().decode("utf-8", "replace"))
        except Exception:                                              # noqa: BLE001
            return {"code": he.code, "msg": f"HTTP {he.code}"}


def local_detect(kind: str, grab: bool = True, timeout: float = 60.0, log=None) -> dict | None:
    """让本机镜像真检测一次 → /last_result 形状的 dict。服务不可用返回 None。"""
    if not available(kind):
        return None
    try:
        r = _post_json(kind, f"/capture_detect?grab={1 if grab else 0}", timeout=timeout)
    except Exception as e:                                             # noqa: BLE001
        _DOWN[kind] = _t.time() + _COOLDOWN
        if log:
            log(f"⚠️ 本机 AOI 镜像({kind}) 检测失败: {type(e).__name__}: {e}")
        return None
    if not isinstance(r, dict) or r.get("code") != 200:
        return None
    r["src"] = f"local-mirror:{PORTS[kind]}"
    return r


def local_status(kind: str) -> dict:
    """体检用: 服务在不在 + 它的 prod 版本/帧源。"""
    ok = available(kind)
    out = {"kind": kind, "port": PORTS[kind], "up": ok, "mode": mode()}
    if ok:
        try:
            out["health"] = _get_json(kind, "/health", timeout=3.0)
        except Exception as e:                                         # noqa: BLE001
            out["health_err"] = f"{type(e).__name__}: {e}"
    return out


def local_bypass(kind: str, log=None, cache=None, publish=None) -> dict | None:
    """节点旁路: 本机镜像优先。返回 {"verdict","why","judge_ver","ms","src"} 或 None。

    不发布话题 —— 话题由调用方按自己的口径发 (本机镜像的判决 basis 与产线不同,
    混进「工控机真值」话题会让人误以为是产线判决)。
    """
    if cache is None:
        cache = {}
    r = local_detect(kind, grab=True, log=log)
    if r is None:
        cache[f"{kind}_local"] = {"ok": False, "why": "本机镜像未运行"}
        return None
    met = r.get("judge_meta") or {}
    out = {"ok": bool(r.get("ok")), "verdict": r.get("verdict"),
           "why": r.get("why"), "code": r.get("vcode"),
           "ms": r.get("ms"), "total_ms": r.get("total_ms"),
           "judge_ver": r.get("judge_ver"), "n_keys": met.get("n_keys"),
           "pitch_px": met.get("lattice_pitch_px"),
           "frame": r.get("frame"), "src": r.get("src"),
           "basis": r.get("basis"), "source": r.get("source"),
           "ts": r.get("t")}
    cache[f"{kind}_local"] = out
    if log:
        _m = {"JUDGE_OK": "✅", "JUDGE_FAIL": "❌", "JUDGE_GATED": "⛔",
              "NO_FRAME": "🌑", "NO_JUDGE": "❔", "NO_TARGET": "❔"}.get(out["verdict"], "❔")
        log(f"{_m} 本机镜像({kind}) {out['verdict']}: {out['why']} "
            f"· {out['judge_ver']} · {out['ms']}ms · 帧 {out['frame']} · 源 {(out['source'] or {}).get('how')}")
    return out


__all__ = ["mode", "available", "local_detect", "local_status", "local_bypass", "PORTS", "host"]
