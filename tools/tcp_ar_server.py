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
import math                # 路径长度/净空计算用 (2026-10-26 直线最短路径)
import os
import re                  # 号位名 slot1..slot7 → "N号位" 解析 (2026-10-26)
import subprocess          # 🏃 Follow: 后台拉起 run_along_line.py
import sys
import threading
import time
import urllib.error
import urllib.parse
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

# 📄 2026-10-22 老倪: 「右上角增加一个 技术 按钮，可以打开技术协议；你来规划一个文件夹路径，
#   我把真正的 word 版本的技术协议放到这里，你负责打开这个 word」
#   规约: 目录只放**真源文件**(Word/PDF), 不进 git(大件不进库, 见 git 精简纪律);
#   选哪份 = ZMAX_AGREEMENT_FILE 指定 > 文件名含「技术协议」且最新的 > 目录里最新的。
AGREE_DIR = os.environ.get("ZMAX_AGREEMENT_DIR") or os.path.join(REPO, "zmax_data", "agreements")
AGREE_EXTS = (".docx", ".doc", ".pdf")
AGREE_MIME = {".pdf": "application/pdf",
              ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              ".doc": "application/msword"}


def _agreement_files():
    """目录里可当技术协议的文件(真读盘, 不缓存 —— 老倪随时可能替换)。"""
    out = []
    try:
        for n in sorted(os.listdir(AGREE_DIR)):
            if n.startswith(".") or not n.lower().endswith(AGREE_EXTS):
                continue
            p = os.path.join(AGREE_DIR, n)
            if not os.path.isfile(p):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append({"name": n, "size": st.st_size, "mtime": st.st_mtime,
                        "mtime_s": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                        "ext": os.path.splitext(n)[1].lower()})
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return out


def _agreement_pick():
    """返回 (选中文件 dict|None, 全部文件 list)。"""
    files = _agreement_files()
    if not files:
        return None, files
    want = os.environ.get("ZMAX_AGREEMENT_FILE") or ""
    if want:
        for f in files:
            if f["name"] == want:
                return f, files
    pref = [f for f in files if "技术协议" in f["name"]] or list(files)
    pref.sort(key=lambda f: f["mtime"], reverse=True)
    return pref[0], files


def _agreement_info():
    f, files = _agreement_pick()
    return {"ok": True, "dir": AGREE_DIR, "exists": bool(f), "count": len(files),
            "current": f["name"] if f else None, "size": f["size"] if f else None,
            "files": files,
            "hint": "把 Word 版技术协议放进这个目录即可（.docx/.doc/.pdf；有多份时取文件名含「技术协议」且最新的那份，"
                    "或用环境变量 ZMAX_AGREEMENT_FILE 指定文件名）"}


def _agreement_path(name=None):
    if name:
        name = os.path.basename(str(name))
        for f in _agreement_files():
            if f["name"] == name:
                return os.path.join(AGREE_DIR, name)
        return ""
    f, _ = _agreement_pick()
    return os.path.join(AGREE_DIR, f["name"]) if f else ""


# 🖼 2026-10-22 老倪: 「光纤自动检测设备1 和2 …这两张图片，也显示在 /autoLight3d#1 这个页面，
#   你来设计，如何跟工艺卡排列」—— 设备实照是**全局参考**(不随九步变), 单独从图片库读, 不塞进页面当静态资源,
#   这样老倪随时往目录里丢新照片, 页面刷新就有。
PHOTO_DIR = os.environ.get("ZMAX_PHOTO_DIR") or "/home/ubuntu/图片库/01_设备与现场照片"
# 🧩 产品/器件图(来料 MPO-8FC / MPO-16FC 的外观与结构图)单独一个目录, 与设备实照分开管理
PRODUCT_DIR = os.environ.get("ZMAX_PRODUCT_DIR") or "/home/ubuntu/图片库/05_产品与器件"
PHOTO_DIRS = [PHOTO_DIR, PRODUCT_DIR]
PHOTO_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# 🧩 来料产品的主要参数(2026-10-22 老倪: 「MPO-8FC / MPO-16FC 上网找实际的图片，主要参数，显示在 autoLight3d」)
#   数值取自厂家规格书与华为 CE 系列《光跳线外观结构与针脚定义》的公开资料, **典型/上限值**, 只作现场识别参考;
#   真值一律以甲方来料规格书与实测为准(回损测试以 RLM1412A 读数为准)。
PRODUCT_SPECS = [
    {"key": "MPO-8FC", "title": "MPO-8FC", "sub": "1× MPO 8 芯 → 8× FC 单芯",
     "rows": [["芯数", "8 芯"], ["连接器", "MPO(母/公) — 8× FC/PC"],
              ["端面", "MPO PC/APC8° · FC PC/APC"],
              ["插损", "MPO ≤0.35 · FC ≤0.30 dB"],
              ["回损", "SM ≥60 · MM ≥25~35 dB"],
              ["波长", "SM 1310/1550 · MM 850/1300"],
              ["线径", "3.0 主干 / 0.9~2.0 分支 · R≥7.5"],
              ["温度", "-40 ~ +85 ℃"], ["极性", "Type A/B/C(华为 CE 用 B)"],
              ["标准", "IEC 61754-7 · TIA-604-5(FOCIS-5) · GR-1435"]],
     "note": "本设备 FC 工站一次测 16PCS FC 端面 ⇒ 2 件 MPO-8FC 的 FC 端刚好占满一个载具",
     "picnote": "外观图可数出 8 个 FC(4 组双工 1A/1B~4A/4B); 结构图为 MPO 12 针位只用 8 芯(1~4 + 9~12); 末张为 Fluke《MPO 类型》原图裁出的 8 芯阵列 —— 该图 12 位法兰只装 8 芯(中间 4 位空), 与华为结构图 1~4 + 9~12 完全对得上"},
    {"key": "MPO-16FC", "title": "MPO-16FC", "sub": "1× MPO-16 芯 → 16× FC 单芯",
     "rows": [["芯数", "16 芯"], ["连接器", "MPO-16(母/公) — 16× FC/PC"],
              ["端面", "MPO APC8°/PC · FC PC/APC"],
              ["插损", "MPO ≤0.35 · FC ≤0.30 dB"],
              ["回损", "SM ≥60 · MM ≥25~35 dB"],
              ["波长", "SM 1310/1550 · MM 850/1300"],
              ["线径", "3.0 主干 / 0.9~2.0 分支 · R≥7.5"],
              ["温度", "-40 ~ +85 ℃"], ["极性", "Type A / B / C"],
              ["标准", "IEC 61754-7 · TIA-604-5 · GR-1435"]],
     "note": "1 件 MPO-16FC = 16 个 FC 端面 = 1 个载具(载具配 FC 夹具×16)",
     "picnote": "实物=KOCENT MPO-16 转 16×FC 白底实拍(与 HCI 同风格); 对照=HCI 的 Y 缆与华为两端 MPO 干缆; 「16 芯」以结构图+Fluke《MPO 类型》16 芯阵列为准"},
]


def _photo_files():
    out = []
    try:
        names = sorted(os.listdir(PHOTO_DIR))
    except OSError:
        return out
    for n in names:
        if n.startswith(".") or os.path.splitext(n)[1].lower() not in PHOTO_EXTS:
            continue
        p = os.path.join(PHOTO_DIR, n)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"name": n, "size": st.st_size,
                    "mtime_s": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                    "url": "/photo/" + urllib.parse.quote(n)})
    return out


def _product_photos():
    """产品图: 按文件名前缀归到 MPO-8FC / MPO-16 两组, 页面按组取外观/结构图。"""
    out = {"MPO-8FC": [], "MPO-16FC": []}
    try:
        names = sorted(os.listdir(PRODUCT_DIR))
    except OSError:
        return out
    for n in names:
        if n.startswith(".") or os.path.splitext(n)[1].lower() not in PHOTO_EXTS:
            continue
        p = os.path.join(PRODUCT_DIR, n)
        if not os.path.isfile(p):
            continue
        grp = "MPO-16FC" if "MPO-16" in n else ("MPO-8FC" if "MPO-8" in n else "")
        item = {"name": n, "url": "/photo/" + urllib.parse.quote(n),
                "kind": ("对照" if "对照" in n else
                         "结构" if "结构" in n else
                         "细节" if "细节" in n else
                         "外观" if "外观" in n else "实物"),
                "size": os.path.getsize(p)}
        if grp:
            out[grp].append(item)
    # 排序: 实物(一眼看形态) → 外观 → 细节(端面特写) → 对照(别家形态) → 结构(位定义)
    rank = {"实物": 0, "外观": 1, "细节": 2, "对照": 3, "结构": 4}
    for k in out:
        out[k].sort(key=lambda x: (rank.get(x["kind"], 9), x["name"]))
    return out


def _agreement_open():
    """在**工位机桌面**把 Word 打开(真起进程, 返回用了哪个程序)。

    为什么要服务端开: 这个按钮在工位机上点(浏览器与文档同一台机器) —— 让 LibreOffice/Word 直接出窗,
    比"下载到下载目录再自己找"快一步; 从别的设备点会开在工位机桌面上, 页面会明说, 另给 ⬇ 下载。
    """
    import shutil as _sh
    p = _agreement_path()
    if not p:
        return {"ok": False, "err": "目录里还没有技术协议文件", "dir": AGREE_DIR,
                "hint": "把 Word 放进 %s 后点这个按钮即可" % AGREE_DIR}
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    from pathlib import Path
    target = str(Path(p).resolve())
    tried = []
    for cmd in (["soffice", "--norestore", target],
                ["lowriter", "--norestore", target],
                ["xdg-open", target]):
        if _sh.which(cmd[0]) is None:
            continue
        tried.append(cmd[0])
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=env)
            return {"ok": True, "how": cmd[0], "file": os.path.basename(target), "path": target,
                    "size": os.path.getsize(target)}
        except Exception as _e:                                                # noqa: BLE001
            last = "%s: %r" % (cmd[0], _e)
            continue
    return {"ok": False, "err": "没找到能打开 Word 的程序(soffice/lowriter/xdg-open 都不可用)", "path": target}

CALIB = os.path.join(REPO, "data", "scene", "laptop_cam_calib.json")            # 旧单相机文件(兼容保留)
MCALIB = os.path.join(REPO, "data", "scene", "cam_calib.json")                   # 多相机: {"local":{...},"local2":{...}}


def _ar_points():
    """📍 工程配置的全部点位台账 —— 配置中心推的 ar_aoi_live.json。

    老倪 2026-10-26: 「也要显示 工程配置的所有点, 向下罗列显示出来」。
    结构: {"ts":..., "s":{"金手指点1.x":0.36, "金手指点1.y":..., ...}, "groups":{"金手指点1.x":"AR·空间点位 (基座系)"}}
    ⇒ 按 "<点名>.x/.y/.z" 三件齐全才认(米), 同时给 mm 和分组, 页面按分组向下罗列。
    """
    ap = os.path.join(REPO, "zmax_data", "ar_live", "ar_aoi_live.json")
    try:
        with open(ap, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                                                    # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, e), "points": [], "n": 0,
                "hint": "台账由 ar_aoi_bus 推送(工程配置→%s)" % os.path.relpath(ap, REPO)}
    s = d.get("s") or {}
    groups = d.get("groups") or {}
    out = []
    for k in sorted(s.keys()):
        if not k.endswith(".x"):
            continue
        nm = k[:-2]
        try:
            v = [float(s[nm + "." + ax]) for ax in "xyz"]
        except Exception:                                                     # noqa: BLE001
            continue
        out.append({"name": nm, "x": v[0], "y": v[1], "z": v[2],
                    "mm": [round(x * 1000) for x in v],
                    "group": groups.get(nm + ".x") or "未分组"})
    out.sort(key=lambda r: (r["group"], r["name"]))
    # 🔴 2026-10-26 老倪「我已经更新 空间点7 了，刚在 station 的标记模式改的，你看到了么？数据要保持一致」
    #   实测: 标记模式(8793) → tools/record_l2_point.py 写 **data/skills/l2_atomic/space_points.json**
    #   (space1..space8, 含 pos/quat/abc, mtime 就是刚改的时刻);
    #   而本接口原来**只读** ar_aoi_live.json(工程配置台账, 停在 10-20) ⇒ 页面上还是旧点位,
    #   station 改了、AR 页面不变 —— 两边各说各话。
    #   口径: **标记模式是示教点真源**, 它写到的 spaceN 覆盖台账里同义的「空间点N」;
    #   台账里有、示教里没有的点照旧保留(它们来自工程配置, 不是示教出来的)。
    sp = os.path.join(REPO, "data", "skills", "l2_atomic", "space_points.json")
    _ov = {}
    try:
        with open(sp, encoding="utf-8") as f:
            _spd = json.load(f)
        for _k, _v in (_spd.get("points") or {}).items():
            _p = _v.get("pos") or []
            if len(_p) >= 3:
                _ov["空间点" + str(_k).replace("space", "").strip()] = [float(_p[0]), float(_p[1]), float(_p[2])]
    except Exception:                                                         # noqa: BLE001
        _ov = {}
    if _ov:
        _seen = set()
        for row in out:
            _v = _ov.get(row["name"])
            if _v:
                row.update({"x": _v[0], "y": _v[1], "z": _v[2],
                            "mm": [round(x * 1000) for x in _v], "src": "space_points"})
                _seen.add(row["name"])
        for _n, _v in _ov.items():                       # 示教里有、台账里没有的, 补出来
            if _n in _seen:
                continue
            out.append({"name": _n, "x": _v[0], "y": _v[1], "z": _v[2],
                        "mm": [round(x * 1000) for x in _v],
                        "group": "AR·空间点位 (基座系)", "src": "space_points"})
        out.sort(key=lambda r: (r["group"], r["name"]))
    # 📍 号位 1~7 (2026-10-26 老倪「号位 1～7 号示教点，也要在 ar3d 显示，怎么没有呢？工程配置没有么？」)
    #   实测: 号位坐标一直在 data/skills/l2_atomic/taught_points.json 的 slot1..slot7
    #   (8793 工位总览 /ctl/points 读的就是这个文件, 7/7 全绿有坐标), 但 ar3d 这个接口
    #   从来只读 ar_aoi_live 台账 + space_points ⇒ 3D 里根本没有号位,
    #   所以看着像"工程配置里没配"。口径: 号位与空间点并列, 单独分组, src=taught_points。
    _tpp = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
    try:
        with open(_tpp, encoding="utf-8") as f:
            _tp = (json.load(f) or {}).get("points") or {}
        _nslot = 0
        for _i in range(1, 8):
            _v = _tp.get("slot%d" % _i) or {}
            _p = _v.get("pos") or []
            if len(_p) < 3:
                continue
            out.append({"name": "%d号位" % _i,
                        "x": float(_p[0]), "y": float(_p[1]), "z": float(_p[2]),
                        "mm": [round(float(x) * 1000) for x in _p[:3]],
                        "group": "AR·号位 (基座系)", "src": "taught_points"})
            _nslot += 1
        if _nslot:
            out.sort(key=lambda r: (r["group"], r["name"]))
    except Exception:                                                         # noqa: BLE001
        pass
    ts = d.get("ts")
    return {"ok": True, "n": len(out), "points": out, "ts": ts,
            "age_s": (round(time.time() - float(ts), 1) if ts else None),
            "src": os.path.relpath(ap, REPO)}
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


def _box_covers_xy(it, p, margin=0.02):
    """盒子在 x/y 平面是否真的盖住这个点(含 margin)。

    🔴 2026-10-26 老倪「去7号位，要先到7号位的正上方」实测踩坑: 接近高度 z=307.7 被判成
      "落进 检测设备(x 711~844 / y -91~302 / z 0~340) 的 z 区间" ⇒ 压到盒底 -20mm,
      可 7号位在 x=647, x 根本不在盒子里 —— 只判 z 不判 x/y 就会把高度压到地下。
      避让必须三维真重叠才算重叠。
    """
    try:
        x0, x1 = sorted((float(it["p1"][0]), float(it["p2"][0])))
        y0, y1 = sorted((float(it["p1"][1]), float(it["p2"][1])))
        return (x0 - margin) <= float(p[0]) <= (x1 + margin) and (y0 - margin) <= float(p[1]) <= (y1 + margin)
    except Exception:                                                        # noqa: BLE001
        return True                     # 判不了就按"可能重叠"处理, 保守


def _min_clear_mm(path_pts):
    """一条路径到所有启用围栏(长方体/直线)的最小净空 mm; 负值=穿进围栏内部。

    2026-10-26 老倪:「走直线是最近的」⇒ 直线要能自证安全, 不能只说"应该没问题"。
    只读 FS 真源(_load), 轨迹点(type=points)不参与判定(否则自己的路把自己堵死)。
    """
    d = FS._load()
    best_d, best_nm = 9e9, ""
    for p in path_pts:
        for it in d.get("items", []):
            if not it.get("enabled", True) or it.get("type") == "points":
                continue
            if it["type"] == "box":
                lo = [min(it["p1"][k], it["p2"][k]) for k in range(3)]
                hi = [max(it["p1"][k], it["p2"][k]) for k in range(3)]
                if all(lo[k] <= p[k] <= hi[k] for k in range(3)):
                    dd = -min(min(p[k] - lo[k], hi[k] - p[k]) for k in range(3))
                else:
                    dd = math.dist(p, [min(max(p[k], lo[k]), hi[k]) for k in range(3)])
            else:
                dd = FS._pt_seg_dist(p, it["p1"], it["p2"])
            if dd < best_d:
                best_d, best_nm = dd, (it.get("name") or "")
    return best_d * 1000.0, best_nm


def _smooth_fillet(pts, radius=0.045, step=0.005):
    """折线骨架 → 圆弧圆角过渡 + 等步长采样 ⇒ 切线连续(C1)的平滑路径。

    2026-10-26 老倪: 「你应该规划一个平滑的, 从当前点到准备点的轨迹」
      (原实现是 4 点直角折线: 原地升 → 平移 → 垂直落, 三段 90° 硬拐角, 画出来就是折线。)

    口径:
      · 首点/末点**原样保留** —— 起点闸按首点判 20mm, 末端必须精确落在目标点
      · 每个内部拐角用半径 radius 的圆弧过渡; 段长不足时按 45% 段长自动缩半径
      · ⚠ 圆角会在拐角处**向内切 radius**, 所以安全高的余量必须 > radius,
        否则平滑后实际抬升余量被吃掉(调用方负责: zs = max(两端z) + 余量 + radius)
      · 纯 math 实现, 不引 numpy
    返回 [[x,y,z]m, ...]
    """
    import math as _m

    def _sub(a, b): return [a[i] - b[i] for i in range(3)]
    def _add(a, b): return [a[i] + b[i] for i in range(3)]
    def _mul(a, s): return [a[i] * s for i in range(3)]
    def _dot(a, b): return sum(a[i] * b[i] for i in range(3))
    def _norm(a): return _m.sqrt(max(0.0, _dot(a, a)))

    def _unit(a):
        n = _norm(a)
        return [x / n for x in a] if n > 1e-12 else [0.0, 0.0, 0.0]

    def _spin(v, axis, th):
        """Rodrigues: 把 v 绕单位轴 axis 转 th 弧度。"""
        c, s = _m.cos(th), _m.sin(th)
        cr = [axis[1] * v[2] - axis[2] * v[1],
              axis[2] * v[0] - axis[0] * v[2],
              axis[0] * v[1] - axis[1] * v[0]]
        dd = _dot(axis, v)
        return _add(_add(_mul(v, c), _mul(cr, s)), _mul(axis, dd * (1.0 - c)))

    P = [[float(x) for x in p[:3]] for p in pts if p]
    if len(P) < 2:
        return P
    if len(P) == 2:
        n = max(2, int(_norm(_sub(P[1], P[0])) / step) + 1)
        return [_add(P[0], _mul(_sub(P[1], P[0]), i / (n - 1))) for i in range(n)]

    out = [P[0][:]]
    tail = P[0][:]
    for i in range(1, len(P) - 1):
        A, B, C = P[i - 1], P[i], P[i + 1]
        u1, u2 = _unit(_sub(B, A)), _unit(_sub(C, B))
        l1, l2 = _norm(_sub(B, A)), _norm(_sub(C, B))
        cosphi = max(-1.0, min(1.0, _dot(u1, u2)))
        phi = _m.acos(cosphi)
        if phi < 1e-3 or l1 < 1e-9 or l2 < 1e-9:          # 直行, 无拐角
            n = max(2, int(_norm(_sub(B, tail)) / step) + 1)
            out += [_add(tail, _mul(_sub(B, tail), k / (n - 1))) for k in range(1, n)]
            tail = B[:]
            continue
        half_tan = _m.tan(phi / 2.0)
        d = min(radius * half_tan, 0.45 * l1, 0.45 * l2)
        r = d / half_tan if half_tan > 1e-9 else radius
        T_in = _sub(B, _mul(u1, d))
        T_out = _add(B, _mul(u2, d))
        n = max(2, int(_norm(_sub(T_in, tail)) / step) + 1)
        out += [_add(tail, _mul(_sub(T_in, tail), k / (n - 1))) for k in range(1, n)]
        nvec = _unit(_sub(u2, _mul(u1, cosphi)))          # 垂直 u1, 指向转向内侧
        Cc = _add(T_in, _mul(nvec, r))
        v1, v2 = _sub(T_in, Cc), _sub(T_out, Cc)
        a1 = _unit(v1)
        ang = _m.acos(max(-1.0, min(1.0, _dot(_unit(v1), _unit(v2)))))
        axis = [v1[1] * v2[2] - v1[2] * v2[1],
                v1[2] * v2[0] - v1[0] * v2[2],
                v1[0] * v2[1] - v1[1] * v2[0]]
        ax = _unit(axis)
        msteps = max(3, int(r * ang / step) + 1)
        for j in range(1, msteps):
            th = ang * j / (msteps - 1)
            p = _add(Cc, _mul(_spin(a1, ax, th) if _norm(axis) > 1e-12 else a1, r))
            out.append(p)
        tail = T_out[:]
    n = max(2, int(_norm(_sub(P[-1], tail)) / step) + 1)
    out += [_add(tail, _mul(_sub(P[-1], tail), k / (n - 1))) for k in range(1, n)]
    out[0] = P[0][:]
    out[-1] = P[-1][:]                                     # 末端精确落在目标点
    return out


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


def _euler_quat(rx, ry, rz):
    """与 tcp_direct_sampler.euler_to_quaternion 逐行相同 (Euler ZYX → qx,qy,qz,qw)。
    本机没有产线网卡时, 真值从 Orin 的珞石桥来, 口径必须与采样器一致, 否则姿态会整体歪掉。"""
    import math
    cr, sr = math.cos(rx * 0.5), math.sin(rx * 0.5)
    cp, sp = math.cos(ry * 0.5), math.sin(ry * 0.5)
    cy, sy = math.cos(rz * 0.5), math.sin(rz * 0.5)
    return (cy * cp * sr - sy * sp * cr,      # qx
            sy * cp * sr + cy * sp * cr,      # qy
            sy * cp * cr - cy * sp * sr,      # qz
            cy * cp * cr + sy * sp * sr)      # qw


def _read_orin_tcp():
    """Orin 珞石桥 (经 ECS 隧道 19061) → 与 latest.json **同口径**的一条真值。
    老倪 2026-10-21: 「http://10.163.146.78:8797/ar 现在不是实际的位姿啊」
    ⇒ 根因: 本机 tcp_direct_sampler 容器连不上控制器 192.168.23.160 (本机只有 WiFi),
      容器 restarts 循环, latest.json 冻在 00:46(3.5 小时前), 而页面照旧读它。
    返回 (rec, err)"""
    url = os.environ.get("ZMAX_ORIN_SDK_URL", "http://127.0.0.1:19061/status")
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            d = json.loads(r.read().decode())
        st = d.get("status") or d
        p6 = st.get("endInRef")
        if not p6 or len(p6) < 6:
            return None, "桥里没有 endInRef"
        ts = time.time()
        qx, qy, qz, qw = _euler_quat(float(p6[3]), float(p6[4]), float(p6[5]))
        rec = {"ts": round(ts, 4),
               "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + (".%03d" % int(ts * 1000 % 1000)),
               "x": round(float(p6[0]), 6), "y": round(float(p6[1]), 6), "z": round(float(p6[2]), 6),
               "rx": round(float(p6[3]), 6), "ry": round(float(p6[4]), 6), "rz": round(float(p6[5]), 6),
               "qx": round(qx, 6), "qy": round(qy, 6), "qz": round(qz, 6), "qw": round(qw, 6),
               "frame": "base_link",
               "src": "orin_bridge/珞石 endInRef (本机无产线网卡 → ECS 隧道 19061, 5Hz)",
               "joint": st.get("jointPos")}
        return rec, None
    except Exception as e:                                                    # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:100])


def read_tcp():
    """真值优先级: latest.json 新鲜(≤8s) → 用文件; 否则 → Orin 桥直连; 都不行 → 如实报 stale。"""
    d, src_used, fb_err = None, "latest.json", None
    try:
        with open(TCP_JSON) as f:
            d = json.load(f)
    except Exception as e:                                                    # noqa: BLE001
        fb_err = "文件读不到: %s" % str(e)[:60]
    max_age = float(os.environ.get("ZMAX_TCP_MAX_AGE_S", "8"))
    if d is not None and (time.time() - float(d.get("ts") or 0)) > max_age:
        rec, err = _read_orin_tcp()
        if rec is not None:
            d, src_used = rec, "orin_bridge"
            fb_err = None
        else:
            fb_err = "文件 %.0fs 没更新 · 桥也读不到(%s)" % (time.time() - float(d.get("ts") or 0), err)
    elif d is None:
        rec, err = _read_orin_tcp()
        if rec is not None:
            d, src_used = rec, "orin_bridge"
            fb_err = None
    if d is None:
        return {"ok": False, "err": "真值读不到(文件+桥都失败)", "fallback_err": fb_err}
    try:
        out = {"ok": True, "x": d["x"], "y": d["y"], "z": d["z"],
               "t": d.get("t"), "age_s": round(time.time() - float(d["ts"]), 3),
               "stale": bool(time.time() - float(d["ts"]) > max_age),
               "source": src_used, "fallback_err": fb_err,
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
        return {"ok": False, "err": str(e)[:120], "fallback_err": fb_err}


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


AR_SW_FRESH_S = 1800.0          # 开关状态有效期: 控制台只在"点开关"那一刻写盘, 120s 太短(2min后页面自己退出 AR 模式)
AR_CMD_FRESH_S = 3.0            # 🥽 状态空间→AR 指令新鲜度: 超时页面回落到自己的播放逻辑(不卡死)

# 元任务 → 手臂归属 (真源 = 元任务里的 hand 字段; 这个表只是老 schema(无 hand) 的兜底)
_MT_ARM = {"MT-01": "right", "MT-02": "right", "MT-03": "right", "MT-04": "right",
           "MT-05": "right", "MT-06": "left", "MT-07": "both"}
_HAND_ARM = {"L": "left", "R": "right", "BOTH": "both"}


def _ar_meta_payload() -> dict:
    """🧩 AR 场景元任务组合 (真源: 配置中心 TASK-07-AOI 的 ar_meta_tasks.json)

    给 /ar3d 右侧边栏「🧩 元任务」区用: 5 个元任务 + 长程节拍 + 当前执行到哪一个。
    只读, 不下发 (真机零指令)。
    """
    import json as _j
    import os as _o
    P = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                     "data/database/zmax/sources/config/tasks/ar_meta_tasks.json")
    try:
        d = _j.load(open(P, encoding="utf-8"))
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}
    mts = []
    for m in (d.get("meta_tasks") or []):
        mid = m.get("id")
        mts.append({"id": mid, "name": m.get("name"), "segments": m.get("segments"),
                    "occurrences": m.get("occurrences"), "t_s": m.get("t_s"),
                    "prompt": m.get("prompt"), "actions": m.get("actions"),
                    "hand": m.get("hand"), "hand_cn": m.get("hand_cn"),
                    "t_win": m.get("t_win"), "dur": m.get("dur"),
                    "targets": m.get("targets"),
                    "arm": _HAND_ARM.get(m.get("hand") or "") or _MT_ARM.get(mid)})
    lh = d.get("long_horizon") or {}
    cur = {}
    try:
        c = _j.load(open(_o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))),
                                      "zmax_data/ss_live/ar_cmd.json"), encoding="utf-8"))
        cur = {k: c.get(k) for k in ("mt_id", "mt_name", "mt_i", "mt_n", "batch",
                                     "seq", "kind", "label", "mod", "elapsed_s")}
        cur["age_s"] = round(max(0.0, time.time() - float(c.get("t") or 0)), 2)
    except Exception:                                               # noqa: BLE001
        pass
    return {"ok": True, "task_id": d.get("task_id") or "TASK-07-AOI",
            "scene": "AR 仿真双臂 · 左臂摆盘 / 右臂插拔+AOI",
            "meta_tasks": mts,
            # 🧵 双臂并行轨道 (老倪 2026-10-28): 一条件周期时间轴 + 左手/右手两条 lane + 交接点
            "lanes": d.get("lanes") or {},
            "long_horizon": {k: lh.get(k) for k in ("uph_target", "tact_s", "segments_total",
                                                    "round_total_s", "meta_count", "verified",
                                                    "hands")},
            "current": cur}


def _ar_cmd_payload() -> dict:
    """🥽 状态空间 → AR 场景 的机器人驱动指令 (只用于**渲染虚拟臂**, 永不产生真机下发)

    真源: zmax_data/ss_live/ar_cmd.json (状态空间侧 plan/执行器节点按拍写)
    口径: 页面只在 AR 开关=开 且本条新鲜(<=AR_CMD_FRESH_S)时才用它驱动虚拟臂;
          过期或没有 ⇒ 页面回落到原来的播放逻辑。真机通路与本文件无关(真机由 ctl_auth+l2_daemon 管)。
    """
    import json as _j
    import os as _o
    import time as _t
    f = _o.path.expanduser("~/zmax/zmax_data/ss_live/ar_cmd.json")
    try:
        age = _t.time() - _o.path.getmtime(f)
        with open(f, encoding="utf-8") as fh:
            d = _j.load(fh)
        out = {"ok": True, "age_s": round(age, 2), "fresh": age <= AR_CMD_FRESH_S,
               "src": d.get("src"), "seq": d.get("seq"), "mod": d.get("mod"),
               "kind": d.get("kind"), "label": d.get("label"),
               "a": d.get("a"), "b": d.get("b"), "u": d.get("u"),
               "q": d.get("q"), "q_l": d.get("q_l"), "t_str": d.get("t_str"),
               "t_seg": d.get("t_seg"), "t_left": d.get("t_left"),
               "elapsed_s": d.get("elapsed_s"),
               # 🧩 2026-10-28: 长程元任务归属 (Plan 节点 ss_plan_long 写) —— 让页面/取证能看到
               #   "当前属于哪个元任务、第几个、第几批", 而不是只有段号
               "task_id": d.get("task_id"), "mt_id": d.get("mt_id"), "mt_name": d.get("mt_name"),
               "mt_i": d.get("mt_i"), "mt_n": d.get("mt_n"), "batch": d.get("batch")}
        if not out["fresh"]:
            out["note"] = "指令过期(%.1fs > %.1fs) ⇒ 页面回落自身播放" % (age, AR_CMD_FRESH_S)
        return out
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "fresh": False, "age_s": None,
                "err": "%s: %s" % (type(e).__name__, e),
                "note": "无指令文件 ⇒ 页面回落自身播放"}


def _ar_mode_payload() -> dict:
    """🥽 AR 开关状态 —— 画布 🤖 机器人执行器(ssact) 的 AR / 真机 两个开关, 经控制台发布到这里。

    真源: zmax_data/ss_live/exec_switches.json (控制台 on_toggle_ar/on_toggle_real 写)
    口径: AR=开 ⇒ 本页进 AR 场景(右臂用仿真臂, 真机右臂不参与), 且 l2_daemon 对该帧之后的一律拒发;
          文件过期(>120s, 控制台没在发布) ⇒ 视为 AR=关, 不能让控制台失联把页面锁在 AR 模式。
    """
    import json as _j
    import os as _o
    import time as _t
    f = _o.path.expanduser("~/zmax/zmax_data/ss_live/exec_switches.json")
    try:
        age = _t.time() - _o.path.getmtime(f)
        with open(f, encoding="utf-8") as fh:
            d = _j.load(fh)
        fresh = age <= AR_SW_FRESH_S
        # ▶ 播放开关 (老倪 2026-10-28): 只有人点了画布「▶ 运行」才写 ar_play.json,
        #   页面据此 plantStart(); 人不点 ⇒ play 为空 ⇒ 页面绝不自播
        play = {}
        try:
            _pf = _o.path.expanduser("~/zmax/zmax_data/ss_live/ar_play.json")
            if _o.path.exists(_pf):
                with open(_pf, encoding="utf-8") as _ph:
                    play = _j.load(_ph)
                play["age_s"] = round(_t.time() - float(play.get("ts") or 0), 1)
                play["fresh"] = play["age_s"] <= 3600       # 1 小时内的启动命令才算
        except Exception:                                          # noqa: BLE001
            play = {}
        return {"ok": True, "ar_scene": bool(d.get("ar_scene")) if fresh else False,
                "raw_ar_scene": bool(d.get("ar_scene")), "real_auth": bool(d.get("real_auth")),
                "age_s": round(age, 1), "fresh": fresh, "play": play,
                "t_str": d.get("t_str"), "src": d.get("src")}
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "ar_scene": False, "real_auth": False, "age_s": None,
                "err": "%s: %s" % (type(e).__name__, e)}


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
            if p in ("/", "/tcp-ar", "/tcp-ar.html", "/ar",
                     "/ar3d", "/ar3d.html", "/arvr"):
                # 🧭 /ar3d = 独立三维页(同一份页面, 前端按 path 进 vrfull 模式: 一屏只有三维视图)
                with open(PAGE, "rb") as f:                                       # 热读: 改页面不用重启
                    self._send(200, "text/html; charset=utf-8", f.read())
            elif p in ("/autoLight", "/autolight", "/autoLight.html"):
                # 光纤端面检测及清理设备 · 三维工艺视图 (2026-10-21)
                #   与 /ar 同一 base 世界系 (Z 上, m); 页面本身独立, 同样**热读**——改 HTML 不用重启
                _alp = os.path.join(REPO, "tools", "web", "autoLight.html")
                try:
                    with open(_alp, "rb") as f:
                        self._send(200, "text/html; charset=utf-8", f.read())
                except Exception as _ae:
                    self._send(404, "text/plain; charset=utf-8",
                               ("autoLight 页面缺失: %s: %s" % (type(_ae).__name__, _ae)).encode())
            elif p in ("/autoLight3d", "/autolight3d", "/autoLight3d.html"):
                # 🧊 2026-10-22 老倪: 「/ar 的三维视角，需要重新开一个新页面，在光纤的场景」
                #   = 光纤设备九步场景的**独立大窗口三维视角**(一页一个大 3D + 九步切换);
                #   与 /autoLight 同一份引擎/场景(1:1 布置), 同样**热读** —— 改 HTML 不用重启服务
                _al3 = os.path.join(REPO, "tools", "web", "autoLight3d.html")
                try:
                    with open(_al3, "rb") as f:
                        self._send(200, "text/html; charset=utf-8", f.read())
                except Exception as _ae:
                    self._send(404, "text/plain; charset=utf-8",
                               ("autoLight3d 页面缺失: %s: %s" % (type(_ae).__name__, _ae)).encode())
            elif p == "/api/photos":            # 🖼 设备实照清单(从图片库现场读盘)
                self._json({"ok": True, "dir": PHOTO_DIR, "photos": _photo_files()})
            elif p == "/api/products":          # 🧩 来料产品(MPO-8FC / MPO-16FC) 图 + 主要参数
                self._json({"ok": True, "dir": PRODUCT_DIR,
                            "specs": PRODUCT_SPECS, "photos": _product_photos()})
            elif p.startswith("/photo/"):
                # 🖼 单张设备实照: 只认白名单扩展名 + 目录内文件(防目录穿越)
                from urllib.parse import unquote as _uq2
                _nm = os.path.basename(_uq2(p[len("/photo/"):]))
                # 设备实照与产品图分两个目录, 同名以设备实照优先
                _pp = ""
                for _d in PHOTO_DIRS:
                    _c = os.path.join(_d, _nm)
                    if os.path.isfile(_c):
                        _pp = _c
                        break
                if not _nm or not _pp or \
                        os.path.splitext(_nm)[1].lower() not in PHOTO_EXTS:
                    self._send(404, "text/plain; charset=utf-8", b"no such photo")
                else:
                    with open(_pp, "rb") as f:
                        _b = f.read()
                    _mime = ("image/png" if _nm.lower().endswith(".png")
                             else "image/webp" if _nm.lower().endswith(".webp")
                             else "image/jpeg")
                    self._send(200, _mime, _b, {"Cache-Control": "max-age=30"})
            elif p == "/api/agreement":         # 📄 技术协议清单(目录/当前选中/候选列表)
                self._json(_agreement_info())
            elif p in ("/agreement", "/agreement/file") or p.startswith("/agreement/"):
                # 📄 取文件本身: /agreement = 当前选中那份; /agreement/<文件名> = 指定那份
                _nm = p[len("/agreement/"):] if p.startswith("/agreement/") else ""
                if _nm in ("", "file"):
                    _ap = _agreement_path()
                else:
                    from urllib.parse import unquote as _uq
                    _ap = _agreement_path(_uq(_nm))
                if not _ap:
                    self._send(404, "text/plain; charset=utf-8",
                               ("没有技术协议文件; 请放到: %s" % AGREE_DIR).encode())
                else:
                    _ext = os.path.splitext(_ap)[1].lower()
                    _fn = os.path.basename(_ap)
                    try:
                        with open(_ap, "rb") as f:
                            _b = f.read()
                        # inline: 手机上能直接看 PDF; Word 由浏览器交系统打开/下载
                        _disp = "inline" if _ext == ".pdf" else "attachment"
                        self._send(200, AGREE_MIME.get(_ext, "application/octet-stream"), _b,
                                   {"Content-Disposition":
                                    '%s; filename="agreement%s"; filename*=UTF-8\'\'%s'
                                    % (_disp, _ext, urllib.parse.quote(_fn))})
                    except Exception as _ae:                                # noqa: BLE001
                        self._send(500, "text/plain; charset=utf-8",
                                   ("读取技术协议失败: %s: %s" % (type(_ae).__name__, _ae)).encode())
            elif p == "/api/ar/mode":           # 🥽 AR 开关(画布 🤖 机器人执行器) → 本页 AR 模式/真机不下发
                self._json(_ar_mode_payload())
            elif p == "/api/ar/cmd":            # 🥽 状态空间 → AR 虚拟臂驱动指令(只渲染, 不下发真机)
                self._json(_ar_cmd_payload())
            elif p == "/api/ar/meta":            # 🧩 AR 元任务组合(配置中心 TASK-07-AOI) + 当前执行到哪
                self._json(_ar_meta_payload())
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
            elif p == "/api/mod2d_usb":        # 🆕 USB 固定相机(local)上的光模块 2D 框
                # 老倪 2026-10-22「usb 相机, 光模块, 你给画出边界框」
                # 在役 YOLO 在这一路实测 0 框 ⇒ 走"绿拉环锚点 + 一次性标定偏移"(tools/mod2d_usb.py),
                # 只给 2D 框, 不冒充 3D; 找不到拉环就 ok=False, 不拿旧框顶上。
                try:
                    import mod2d_usb as M2U
                    _f = snap_cam(qs.get("cam") or "local")
                    if _f is None:
                        self._json({"ok": False, "boxes": [], "err": "local 取帧失败(8791 未出图)"})
                    else:
                        _r = M2U.detect(_f)
                        _r["age_s"] = 0.0
                        _r["cam"] = qs.get("cam") or "local"
                        self._json(_r)
                except Exception as e:                                             # noqa: BLE001
                    self._json({"ok": False, "boxes": [], "err": "%s: %s" % (type(e).__name__, str(e)[:120])})
            elif p == "/api/fence":            # 🧱 3D 元素列表 (页面画 + 编辑用)
                _lst = FS.listing()
                try:                # ↩ 可回退步数 + 最近几步做了什么 (老倪 2026-10-27)
                    _lst["undo_n"] = len(FS.history(60))
                    _lst["undo_last"] = (FS.history(3) or [{}])[0]
                except Exception:                                                 # noqa: BLE001
                    _lst["undo_n"] = 0
                self._json(_lst)
            elif p == "/api/points":           # 📍 工程配置的全部点位台账 (配置中心 → ar_aoi_live.json)
                # 老倪 2026-10-26: 「也要显示 工程配置的所有点, 向下罗列显示出来」
                # 真源: zmax_data/ar_live/ar_aoi_live.json 的 s{} + groups{} (ar_aoi_bus 推的台账)。
                # 只认 <点名>.x/.y/.z 三件齐全的组 —— AOI/相机/机器人这种非坐标组不列。
                self._json(_ar_points())
            elif p == "/api/sim_transport":    # 🚚 左臂仿真搬运路径 (老倪 2026-10-27)
                # 只读 zmax_data/runtime/traj/sim_transport.json, 不动真机一个字节
                try:
                    _f = os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_transport.json")
                    with open(_f, encoding="utf-8") as _fh:
                        _d = json.load(_fh)
                    _d["ok"] = True
                    self._json(_d)
                except Exception as e:                                             # noqa: BLE001
                    self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
            elif p == "/api/sim_insert":       # 🔁 右臂插拔全流程 (抓取→插孔→拔出→良品下料盘/NG废料盘)
                # 只读 zmax_data/runtime/traj/sim_insert.json, 纯仿真, 不碰真机
                try:
                    _f = os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_insert.json")
                    with open(_f, encoding="utf-8") as _fh:
                        _d = json.load(_fh)
                    _d["ok"] = True
                    self._json(_d)
                except Exception as e:                                             # noqa: BLE001
                    self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
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
            elif p == "/api/traj/named":        # 🧭 命名轨迹 (轨迹1小红/2正方/3建图/4安全/5实时)
                # 老倪 2026-10-25: 「三维视图窗口下面操作按钮区加五个按钮」
                # 轨迹点全从配置中心工程配置读真源, 空数据返回 ok=False + 原因, 不假造点。
                # ⚠️ 本服务的 query 是手工 split 出来的, **不做 percent 解码** —— 点名是中文
                #   ("金手指点1"), 页面 encodeURIComponent 过来必须在这里 unquote 一次,
                #   否则台账里永远找不到这个点(实测: target=%e9%87%91... 查不到)。
                _kq = urllib.parse.unquote(str(qs.get("k") or ""))
                _tq = urllib.parse.unquote(str(qs.get("target") or ""))
                self._json(self._traj_named(_kq, _tq))
            elif p == "/api/stable":
                self._json(self._stable())
            elif p == "/api/calib":
                c = load_calib(cam)
                self._json({"ok": bool(c), "calib": c, "cam": cam, "cams": CAMS})
            elif p.startswith("/box/") and p.endswith(".jpg"):
                cam = p[5:-4]
                if cam == "arm":
                    b, err = self._box_arm_jpeg()
                    if b is None:
                        self.send_response(503); self.end_headers(); return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store, max-age=0")
                    self.send_header("X-Box-Err", (err or "")[:120].encode("ascii", "ignore").decode())
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers(); self.wfile.write(b)
                else:
                    self._json({"ok": False, "err": "%s 这台相机还没外参 ⇒ 画不了 3D 框(需要在 AR 页做 6~8 点标定)" % cam})
            elif p == "/api/module_spec":
                self._json(self._module_spec())
            elif p == "/api/traj/plan":
                self._json(self._traj_plan())
            elif p == "/api/traj/exec/state":
                self._json(self._traj_exec_state())
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
                _cam = p[len("/snap/"):-4]
                _b, _src = frame_bytes(_cam)
                if not _b:
                    # 🔴 2026-10-20 老倪「USB 相机还是没有图像」: 原来这里对**空帧**照样回 200 + 0 字节,
                    #   页面的 onload 拿到 0×0 的图什么也不画 ⇒ 屏幕停在上一帧, 看着像"没变/卡住"。
                    #   空帧必须如实 503 + 说清是哪一路、源在哪、怎么查。
                    self._json({"ok": False, "cam": _cam, "src": _src,
                                "err": "这一路相机此刻取不到帧(源返回 0 字节): " + str(_src),
                                "hint": ("①设备在不在 USB 总线: lsusb | grep -i camera  "
                                         "②节点还在不在: v4l2-ctl --list-devices  "
                                         "③源服务是否活着: curl -s -o /dev/null -w '%{http_code}' "
                                         + str(_src))},
                               503)
                    return
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

    # ═══ 命名轨迹 (老倪 2026-10-25: 「三维视图窗口下面操作按钮区加五个按钮:
    #     轨迹1 小红 / 轨迹2 正方 / 轨迹3 建图 / 轨迹4 安全 / 轨迹5 实时」) ═══
    #
    # 轨迹点一律从**配置中心的工程配置**读真源, 前端不写死坐标:
    #   小红  → fence_store 的直线元素 (工程配置「3D 元素」里那条叫"小红"的线)
    #   正方  → 工程配置里没有正方形元素, 由小红的两个端点推出边长**构造**,
    #           响应里 note 明确标 "构造", 不冒充已有元素
    #   建图  → zmax_data/ss_live/explore_traj.json (tools/explore_path_planner.py 的产物)
    #   安全  → ar_aoi_live.json 的金手指点1 → 安全点1 (工程配置点位台账, 实时刷新)
    #   实时  → zmax_data/ss_live/bridge_real_path.json (bridge_path_recorder 录的真机实测)
    #
    # 统一返回 {"ok","k","label","pts":[[x,y,z]m...],"src","n","note","at"};
    # 空数据一律 ok=False + note 说明**为什么空**, 绝不返回假 0 点。
    NAMED_TRAJ = {
        "xiaohong": "轨迹1 · 小红 (工程配置直线)",
        "square":   "轨迹2 · 矩形 (规划航路·洋红闭环)",
        "map":      "轨迹3 · 建图 (自主探索)",
        "safe":     "轨迹4 · 安全 (金手指点1→安全点1)",
        "real":     "轨迹5 · 实时 (当前位姿 → 目标点)",
    }

    def _traj_named(self, k, target=None):
        k = (k or "").strip()
        out = {"ok": False, "k": k, "label": self.NAMED_TRAJ.get(k, k),
               "pts": [], "n": 0, "src": "", "note": "", "at": time.strftime("%H:%M:%S")}
        if k not in self.NAMED_TRAJ:
            out["note"] = "未知轨迹名 (可用: %s)" % ", ".join(self.NAMED_TRAJ)
            return out

        def _lerp(a, b, n):
            return [[a[i] + (b[i] - a[i]) * (t / float(n)) for i in range(3)]
                    for t in range(n + 1)]

        try:
            if k == "xiaohong":
                it = next((x for x in FS.listing()["items"]
                           if x.get("type") == "line" and x.get("name") == "小红"), None)
                if not it:
                    out["note"] = "工程配置里没有叫「小红」的直线元素 (fence_store 为空或已改名)"
                    return out
                A, B = list(it["p1"]), list(it["p2"])
                out.update(ok=True, pts=_lerp(A, B, 40), src="fence_store/小红",
                           note="直线 %s → %s mm" % ([round(v * 1000) for v in A],
                                                     [round(v * 1000) for v in B]))

            elif k == "square":
                # 🔴 2026-10-26 老倪两次纠正:
                #   ① 「正方形不对，不是新的」⇒ 不许我自己构造;
                #   ② 「你怎么还画到前面的检测器上面了？那不碰撞了？矩形就是你旁边的粉色矩形轨迹」
                #      ⇒ 我上一版读的是「检测设备」盒子顶面(z=340, 正好贴/压设备) —— 方向整个错了。
                #   粉色矩形 = 三维视图里那条**洋红色的规划航路**(planned_traj.json, 4 段闭环:
                #   抬60→后80→降60→前80, 起点就是当前 TCP), 也就是模块头刚实际走过的那一圈。
                #   所以这里读 planned_traj.json 的真点列, 按边加密到 ~20mm 一个点。
                # 🔴 2026-10-26 现场第三轮: 「点击执行，没反应」——
                #   真因: 之前这里读的是**上一次**的 planned_traj.json, 而臂已经不在那个起点了
                #   (走完抬60+后80之后停在 [455,306,222]) ⇒ 段表起点 [535,306,162] 与当前差 100mm,
                #   550C 起点闸拒: "起点已变 100.0mm"。页面只在小字里闪一下, 看着就是"点了没反应"。
                #   语义修正: 轨迹2 就是「臂旁边那个矩形」, 必须**以当前 TCP 为基准**画, 否则永远过期。
                #   现在: 用当前真值当场生成 抬60 → 后(x-)80 → 降60 → 前(x+)80 的闭环;
                #   真值取不到时才退回 planned_traj.json 的历史点列(并注明是历史)。
                _t = read_tcp()
                if _t.get("ok"):
                    # read_tcp 给的是米, 这里换算成毫米再构图, 末了整组 /1000 回米
                    x0 = float(_t["x"]) * 1000.0
                    y0 = float(_t["y"]) * 1000.0
                    z0 = float(_t["z"]) * 1000.0
                    a_mm = [[x0, y0, z0], [x0, y0, z0 + 60.0], [x0 - 80.0, y0, z0 + 60.0],
                            [x0 - 80.0, y0, z0], [x0, y0, z0]]
                    _anchors = [[v / 1000.0 for v in p] for p in a_mm]
                    pts = []
                    for c in range(len(_anchors) - 1):
                        A, B = _anchors[c], _anchors[c + 1]
                        edge = sum((B[q] - A[q]) ** 2 for q in range(3)) ** 0.5
                        nn = max(2, int(round(edge / 0.02)))
                        pts.extend(_lerp(A, B, nn)[:-1])
                    pts.append(list(_anchors[-1]))
                    mn = [min(p[q] for p in _anchors) for q in range(3)]
                    mx = [max(p[q] for p in _anchors) for q in range(3)]
                    out.update(ok=True, pts=pts, n=len(pts),
                               src="以当前 TCP 为基准的矩形 (实时)",
                               note="矩形: 起点=当前 TCP [%.1f,%.1f,%.1f]mm · "
                                    "抬60 → 后(x-)80 → 降60 → 前(x+)80 · 280mm · %d 点 · 闭环 · "
                                    "x %.1f~%.1f / z %.1f~%.1fmm"
                                    % (x0, y0, z0, len(pts),
                                       mn[0] * 1000, mx[0] * 1000, mn[2] * 1000, mx[2] * 1000))
                    return out

                pp = os.path.join(REPO, "zmax_data", "runtime", "traj", "planned_traj.json")
                _pl = None
                if os.path.exists(pp):
                    _pl = json.load(open(pp, encoding="utf-8"))
                if not _pl or len(_pl.get("pts_mm") or []) < 4:
                    # 550C 上没有 planned_traj.json(规划在 550B 做的) ⇒ 退回它自己收到的那份段表
                    #   plan_latest.json(段表真源, 每段带 abs_mm), 拼成同样的闭环点列。
                    lp = os.path.join(REPO, "zmax_data", "runtime", "plan", "plan_latest.json")
                    if os.path.exists(lp):
                        _lb = json.load(open(lp, encoding="utf-8"))
                        _st = [float(v) / 1000.0 for v in (_lb.get("start_mm") or [])]
                        _pts = [_st] if _st else []
                        for _sg in (_lb.get("segs") or []):
                            _a = _sg.get("abs_mm") or [(float(_sg["pos"][i]) * 1000.0) for i in range(3)]
                            _pts.append([float(v) / 1000.0 for v in _a])
                        if len(_pts) >= 4:
                            _pl = {"pts_mm": [[round(v * 1000.0, 1) for v in p] for p in _pts],
                                   "total_mm": _lb.get("lin_total_mm"),
                                   "src": "plan_latest.json(550C 收到的段表)"}
                if not _pl:
                    out["note"] = ("没有规划航路: planned_traj.json / plan_latest.json 都没有 ⇒ "
                                   "先在 550B 规划, 或让规划桥把段表推过来")
                    return out
                _anchors = [[float(v) / 1000.0 for v in p] for p in (_pl.get("pts_mm") or [])]
                if len(_anchors) < 4:
                    out["note"] = ("规划航路只有 %d 个点, 不成矩形 (要 ≥4) ⇒ 重新规划一条 4 段闭环"
                                   % len(_anchors))
                    return out
                pts = []
                for c in range(len(_anchors) - 1):
                    a, b = _anchors[c], _anchors[c + 1]
                    edge = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
                    n = max(2, int(round(edge / 0.02)))
                    seg = _lerp(a, b, n)
                    pts.extend(seg[:-1])
                pts.append(list(_anchors[-1]))               # 收尾回到闭环点
                mn = [min(p[i] for p in _anchors) for i in range(3)]
                mx = [max(p[i] for p in _anchors) for i in range(3)]
                out.update(ok=True, pts=pts, src="planned_traj.json (规划航路矩形)",
                           note="规划航路矩形(三维视图里那条洋红线): 起点 [%.0f,%.0f,%.0f]mm · "
                                "x %.0f~%.0f / y %.0f~%.0f / z %.0f~%.0fmm · %d 段 / %.0fmm · %d 点 · 闭环"
                                % (_anchors[0][0] * 1000, _anchors[0][1] * 1000, _anchors[0][2] * 1000,
                                   mn[0] * 1000, mx[0] * 1000, mn[1] * 1000, mx[1] * 1000,
                                   mn[2] * 1000, mx[2] * 1000, len(_anchors) - 1,
                                   float(_pl.get("total_mm") or 0), len(pts)))

            elif k == "map":
                # 🔴 2026-10-26 老倪: 「建图轨迹太长了，都碰到检测设备了，你前面的围栏，你看到了么？重新规划」
                #    原来读的是 2D 栅格平移的**示意坐标**, 一路铺到 x=+720mm, 正好压进
                #    「检测设备」围栏(712~844mm / z 0~340mm)。现在优先读
                #    tools/explore_traj_fenced.py 按围栏重规划出来的 base 系真坐标点列;
                #    那份不存在时才退回旧栅格映射, 并在 note 里明说"没避让围栏"。
                fp = os.path.join(REPO, "zmax_data", "ss_live", "explore_traj_fenced.json")
                if os.path.exists(fp):
                    _f = json.load(open(fp, encoding="utf-8"))
                    _p = [[float(v) for v in q] for q in (_f.get("pts") or [])]
                    if len(_p) >= 2:
                        # n / label 必须一起给: 早退分支漏了 n ⇒ 页面显示「✓ 0 点」(实测踩过)
                        out.update(ok=True, pts=_p, n=len(_p), src="explore_traj_fenced.json",
                                   note="按工程配置围栏重规划 · %s" % (_f.get("note") or ""))
                        out["label"] = self.NAMED_TRAJ["map"] + " · 避让围栏重规划"
                        return out
                mp = os.path.join(REPO, "zmax_data", "ss_live", "explore_traj.json")
                if not os.path.exists(mp):
                    out["note"] = "还没有探索轨迹 (先跑 tools/explore_path_planner.py)"
                    return out
                d = json.load(open(mp, encoding="utf-8"))
                cell = float(d.get("cell") or 0.02)
                nx = int(d.get("nx") or 0)
                ny = int(d.get("ny") or 0)
                # 栅格坐标系在工作台左下角原点; 平移到 base 系 (台面高度 z, 机器人在其左后)
                # ⚠ 这是**示意映射** —— 探索轨迹是 2D 栅格, 没有真实 base 系坐标
                # 栅格 (0~0.64, 0~0.60) 平移到 base 系工作台区。
                # 🔴 初版用 oy=-0.45 ⇒ 整条轨迹跑到机器人身后, VR 视图里 54 个点
                #    只投出 15 个像素(其余在视锥外), 看着就是"没画"。
                #    对齐小红/安全点的实际 y 区间 (-0.20~+0.20) 后就能看见。
                ox, oy, oz = 0.28, -0.30, 0.28
                # 优先用**完整 path** (54 步连续轨迹), 不是 7 个航点跳着连 ——
                # 实测只连航点时画出 7 段稀疏短线, VR 视图里只剩 15 个像素看不见。
                pts = [[ox + i * cell, oy + j * cell, oz] for (i, j) in (d.get("path") or [])]
                if len(pts) < 2:
                    pts = [[ox + w["x"], oy + w["y"], oz] for w in (d.get("waypoints") or [])]
                out.update(ok=len(pts) >= 2, pts=pts, src="explore_traj.json",
                           note="⚠ 示意坐标: 2D 栅格(%dx%d @ %dcm)平移到 base 系台面 z=%.0fmm; "
                                "覆盖 %.1f%%, 航点 %d"
                                % (nx, ny, int(cell * 1000), oz * 1000,
                                   float(d.get("coverage_final") or 0) * 100,
                                   len(d.get("waypoints") or [])))
                if not out["ok"]:
                    out["note"] += " (航点不足 2 个)"

            elif k == "safe":
                ap = os.path.join(REPO, "zmax_data", "ar_live", "ar_aoi_live.json")
                if not os.path.exists(ap):
                    out["note"] = "点位台账 ar_aoi_live.json 不存在 (ar_aoi_bus 没在跑)"
                    return out
                s = json.load(open(ap, encoding="utf-8")).get("s") or {}

                def _p(nm):
                    v = [s.get(nm + "." + ax) for ax in "xyz"]
                    return None if any(x is None for x in v) else [float(x) for x in v]

                a, b = _p("金手指点1"), _p("安全点1")
                if a is None or b is None:
                    out["note"] = "点位台账缺金手指点1 或 安全点1 (工程配置里没标这俩点)"
                    return out
                out.update(ok=True, pts=_lerp(a, b, 20), src="ar_aoi_live/金手指点1→安全点1",
                           note="金手指点1 %s → 安全点1 %s mm"
                                % ([round(v * 1000) for v in a], [round(v * 1000) for v in b]))

            elif k == "real":
                # 🧭 2026-10-26 老倪:「当我选择 轨迹5 实时的时候, 你要规划一个从当前点 → 目标点的轨迹;
                #   左栏每个空间点位左侧加一个小开关标目标点(只能一个), 选好之后规划到这个点并显示」
                #   ⇒ 轨迹5 = 当前实时 TCP → **页面上选中的目标点**(?target=点名, 缺省 安全点1);
                #     路径形状 = 原地升到安全高 → 在安全高平移 → 垂直落点 (不做低空横移, 也不凭空造起点)。
                aq = os.path.join(REPO, "zmax_data", "ar_live", "ar_aoi_live.json")
                cur = None
                try:
                    cp = os.path.join(REPO, "zmax_data", "rokae_sdk/tcp_out/latest.json")
                    cj = json.load(open(cp, encoding="utf-8"))
                    if all(abs(float(cj.get(ax) or 0)) < 1e-9 for ax in "xyz"):
                        cur = None                                   # 全 0 = 陈旧, 不能当起点
                    else:
                        cur = [float(cj["x"]), float(cj["y"]), float(cj["z"])]
                except Exception:                                                  # noqa: BLE001
                    cur = None
                tname = (str(target or "").strip() or "安全点1")
                tgt_p, names = None, []
                # 🔴 2026-10-26 老倪「我已经更新 空间点7 了，刚在 station 的标记模式改的…数据要保持一致」
                #   实测: 标记模式写 data/skills/l2_atomic/space_points.json(space1..8) 是**示教真源**,
                #   而这段原来只查工程配置台账 ar_aoi_live.json(停在 10-20) ⇒
                #   station 明明改了空间点7(522,-116,274), 这里规划还用旧值(679,-38,360), 差 195mm。
                #   ⇒ 先按「空间点N ↔ spaceN」查 space_points, 命中就用它压过台账; 未命中才回落台账。
                _spm = {}
                try:
                    _spf = os.path.join(REPO, "data", "skills", "l2_atomic", "space_points.json")
                    with open(_spf, encoding="utf-8") as _f:
                        for _k, _v in (json.load(_f).get("points") or {}).items():
                            _pv = _v.get("pos") or []
                            if len(_pv) >= 3:
                                _spm["空间点" + str(_k).replace("space", "").strip()] = \
                                    [float(_pv[0]), float(_pv[1]), float(_pv[2])]
                except Exception:                                                  # noqa: BLE001
                    _spm = {}
                # 📍 号位 1~7 (2026-10-26 老倪「号位1～7 也要在 ar3d 显示」+「现在目标是7号位, 怎么不规划了」)
                #   号位坐标在 data/skills/l2_atomic/taught_points.json 的 slot1..slot7 —— 8793 号位按钮
                #   读的就是它, 但这段目标点解析原来只认台账 + space_points ⇒ 选「7号位」直接报
                #   "点位台账里没有目标点", 页面上就是"不规划了"。这里同样按示教真源优先。
                _slm = {}
                try:
                    _tpf = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
                    with open(_tpf, encoding="utf-8") as _f:
                        for _k, _v in ((json.load(_f) or {}).get("points") or {}).items():
                            _mm = re.match(r"slot(\d+)$", str(_k))
                            if not _mm:
                                continue
                            _pv = _v.get("pos") or []
                            if len(_pv) >= 3:
                                _slm[_mm.group(1) + "号位"] = [float(_pv[0]), float(_pv[1]), float(_pv[2])]
                except Exception:                                                  # noqa: BLE001
                    _slm = {}
                try:
                    s = json.load(open(aq, encoding="utf-8")).get("s") or {}
                    names = sorted({str(n)[:-2] for n in s if str(n).endswith(".x")})
                    v = [s.get(tname + "." + ax) for ax in "xyz"]
                    if all(x is not None for x in v):
                        tgt_p = [float(x) for x in v]
                except Exception:                                                  # noqa: BLE001
                    tgt_p = None
                if tname in _spm:                                                  # 示教真源优先
                    tgt_p = list(_spm[tname])
                    if tname not in names:
                        names = sorted(set(names) | set(_spm.keys()))
                if tname in _slm:                                                  # 号位: 示教真源优先
                    tgt_p = list(_slm[tname])
                    if tname not in names:
                        names = sorted(set(names) | set(_slm.keys()))
                out["target"] = tname
                if cur is None:
                    out["note"] = ("实时路径缺起点: 读不到当前 TCP (tcp_out/latest.json 全 0 或不存在)"
                                   " —— 不会凭空编一个起点")
                    return out
                if tgt_p is None:
                    out["note"] = ("点位台账里没有目标点「%s」或坐标不全 · 可选: %s"
                                   % (tname, ", ".join(names[:8]) or "(台账为空)"))
                    return out
                # 🥽 2026-10-26 老倪:「从当前点去准备点, 走直线是最近的, 你却升高后又绕远; 改成直线」
                #   ① 默认 **直线**: 两点连线, 最短(当前→准备点 260.8mm, 原来抬升绕行 448.7mm)
                #   ② 直线仍要过 20mm 净空门槛 —— 用 _min_clear_mm 逐点算, 不达标才回退
                #      「原地升→安全高平移→垂直落」, 并在 note 里写明绕行原因(不偷偷绕)
                #   ③ 两种形状统一按 5mm 等步长采样, 首末点原样(起点闸/末端精度靠它)
                _straight = _lerp(cur, tgt_p, 80)
                _cmin, _cby = _min_clear_mm(_straight)
                _Ldist = math.dist(cur, tgt_p) * 1000.0
                # 📍 2026-10-26 老倪「去7号位，要先到7号位的正上方，再下降抓光模块」
                #   号位 1~7 = 光模块插拔/抓取位, 目标 z≈108mm 就贴在台面上。
                #   直接一路斜插过去 = 贴着台面/工件横切(净空 64mm 也照样是斜的落低处),
                #   抓取位必须**先到正上方、再竖直下降** —— 这是现场工艺, 不是最短路径问题。
                _grasp = bool(re.match(r"^\d+号位$", tname or ""))
                if _grasp:
                    # 🎯 2026-10-26 老倪「先到 7号位的正上方 5厘米的位置」
                    #   接近高度 = 点位 z + **50mm**（不是 200mm），而且**终点就停在正上方 50mm**,
                    #   最后一刀"下降 50mm 到抓取位"不编进这条 —— 现场自己走。
                    #   路径仍是: 先在本高度横移到正上方 → 再竖直下降 (不在低位横切)。
                    _app_h = 0.050
                    _zt = float(tgt_p[2])
                    _zap = _zt + _app_h
                    _end = [float(tgt_p[0]), float(tgt_p[1]), _zap]
                    _p1 = [float(tgt_p[0]), float(tgt_p[1]), max(_zap, float(cur[2]))]
                    # 接近高度同样要避开头顶围栏盒(横梁/相机), 与绕行同一套 z 区间判据(三维真重叠)
                    _cap2 = []
                    for _it in (FS._load().get("items") or []):
                        if not _it.get("enabled", True) or _it.get("type") != "box":
                            continue
                        _z0 = min(_it["p1"][2], _it["p2"][2])
                        _z1 = max(_it["p1"][2], _it["p2"][2])
                        if (_z0 - 0.02 <= _p1[2] <= _z1 + 0.02) and _box_covers_xy(_it, _p1):
                            _p1[2] = _z0 - 0.02
                            _cap2.append(str(_it.get("name") or "?"))
                    if _p1[2] > _zap + 0.002:
                        skel = [list(cur), _p1, _end]       # 高位横移 → 竖直降到正上方 50mm
                        shape = ("两阶段(高位 z=%.0f 横移到正上方 → 竖直降到 z=%.0f)"
                                 % (_p1[2] * 1000, _zap * 1000))
                    else:
                        skel = [list(cur), _end]            # 当前已在接近高度或更低 ⇒ 直接到正上方
                        shape = "两阶段(到正上方 z=%.0f)" % (_zap * 1000)
                    extra = " · 正上方 +%.0fmm · 停在抓取位上方, 未落到 z=%.0f" % (_app_h * 1000, _zt * 1000)
                    if _cap2:
                        extra += " · 受%s压到 %.0fmm" % ("、".join(_cap2), _p1[2] * 1000)
                    _cmin, _cby = _min_clear_mm(_smooth_fillet(skel, radius=0.03, step=0.01))
                elif _cmin >= 20.0:
                    skel = [list(cur), list(tgt_p)]
                    shape = "直线(最短)"
                    extra = ""
                else:
                    _R = 0.045
                    zs = max(cur[2], tgt_p[2]) + 0.05 + _R
                    # 🔴 2026-10-26 老倪「你看你现在规划的轨迹，是先上升，穿过上横梁，又横向后退，又下降，不对」
                    #   绕行的"安全高度"原来只算 最高点+95mm, **完全没看头顶的横梁(682~700)** ——
                    #   目标点一高(例如末端 z=654)就得出 zs=749, 正好从横梁胸中间穿过去, 而且是
                    #   「升→横移→降」三段, 现场一眼就是瞎绕。
                    #   口径: 绕行高度必须避开每个围栏盒的 z 区间; 要穿进去就压到盒底下方 20mm,
                    #   并在 note 里写明"受 <盒名> 限制压到 Xmm"(不偷偷压, 也不偷偷穿)。
                    _cap = []
                    _fd = FS._load()
                    for _it in _fd.get("items", []):
                        if not _it.get("enabled", True) or _it.get("type") != "box":
                            continue
                        _z0 = min(_it["p1"][2], _it["p2"][2])
                        _z1 = max(_it["p1"][2], _it["p2"][2])
                        if (_z0 - 0.02 <= zs <= _z1 + 0.02) and _box_covers_xy(_it, [tgt_p[0], tgt_p[1], zs]):
                            zs = _z0 - 0.02
                            _cap.append(str(_it.get("name") or "?"))
                    # 压下来之后仍要高于两端点, 否则绕行没意义 ⇒ 如实说走不了, 不硬编
                    if zs <= max(cur[2], tgt_p[2]) + 0.005:
                        out["note"] = ("绕行高度被头顶围栏(%s)压到 %.0fmm, 已不高于两端点(%.0f/%.0f) "
                                       "⇒ 这条不要绕, 请改目标点或先手动退开"
                                       % ("、".join(_cap) or "?", zs * 1000, cur[2] * 1000, tgt_p[2] * 1000))
                        return out
                    skel = [list(cur),
                            [cur[0], cur[1], zs],               # ① 原地升到安全高
                            [tgt_p[0], tgt_p[1], zs],           # ② 在安全高平移
                            list(tgt_p)]                        # ③ 垂直落点
                    shape = "抬升绕行(直线净空仅 %.1fmm < 20mm)" % _cmin
                    extra = " · 圆弧过渡 R=45mm · 抬升余量 50mm"
                    _cmin, _cby = _min_clear_mm(_smooth_fillet(skel, radius=_R, step=0.01))
                pts = _smooth_fillet(skel, radius=0.045, step=0.005)
                _plen = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * 1000.0
                out.update(ok=True, pts=pts,
                           src="实时: 当前TCP→%s (%s)" % (tname, shape),
                           note=("当前 TCP %s → 🎯目标点「%s」%s · 直线距离 %.1fmm · 路径长 %.1fmm · "
                                 "%d 点 @5mm · 最小净空 %.1fmm(%s)%s · 执行时按弧长拆段 ≤100mm")
                                % ([round(x * 1000) for x in cur], tname,
                                   [round(x * 1000) for x in tgt_p], _Ldist, _plen,
                                   len(pts), _cmin, _cby or "—", extra))
                out["skeleton"] = [[round(c, 6) for c in p] for p in skel]

            elif k == "real_gone":
                rp = os.path.join(REPO, "zmax_data", "ss_live", "bridge_real_path.json")
                if not os.path.exists(rp):
                    out["note"] = "还没有真机实测轨迹 (bridge_path_recorder 未录到)"
                    return out
                rj = json.load(open(rp, encoding="utf-8"))
                pts = rj.get("pts") or []
                if len(pts) < 2:
                    out["note"] = ("真机还没走过路 (实测 0 点) —— 这**不是故障**, "
                                   "是机器人这段时间没执行动作; 走一次就会自动出现")
                    return out
                out.update(ok=True, pts=pts, src="bridge_real_path.json",
                           note="真机实测 %s 点 · %smm · 阶段 %s · 帧龄 %.0fs"
                                % (rj.get("n"), rj.get("len_mm"), rj.get("stage") or "?",
                                   time.time() - os.path.getmtime(rp)))
        except Exception as e:                                                  # noqa: BLE001
            out["ok"] = False
            out["note"] = "读真源失败 %s: %s" % (type(e).__name__, e)
        out["n"] = len(out["pts"])
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

    TRAJ_DIR = os.path.join(REPO, "zmax_data", "runtime", "traj")
    TRAJ_MAX_AGE = 1800.0

    # ── 光模块外形(长方体) 规格: 真源一个文件, 页面只读 ───────────────────────
    MODSPEC = os.path.join(REPO, "zmax_data", "ar_state", "module_spec.json")
    MOD_DEFAULT = {"L_mm": 56.5, "W_mm": 13.4, "T_mm": 8.5,
                   "src": "SFP 类标称(长 56.5 / 宽 13.4 / 厚 8.5), 与臂相机实测宽高比 27/122px 吻合"}

    def _module_corners_mm(self):
        """光模块长方体的 8 角点 (base 系, mm)。口径由老倪定, 见 _module_spec()。

        手眼口径(2026-10-25 定死, 有判据): cam 原点 = O + R_b2t·t ; R_c2b = R_b2t·M_R
          ⇒ tool1 投到 (333.0, 39.7), 与项目文档常量 (332.9, 41.8) 吻合。
          (另一种"用 inv(M) 的旋转 + 同样的位置"会投到 (-83,1266), 已证伪。)
        """
        import numpy as _np
        t = read_tcp()
        if not t.get("ok"):
            return None, "TCP 读不到: %s" % str(t.get("err"))[:60]
        sp = self._module_spec()
        F1 = (t.get("frames") or {}).get("tool1")
        F0 = (t.get("frames") or {}).get("tool0") or {}
        if not F1:
            return None, "TCP 没有 frames(tool1)"
        O = _np.array(F1["origin"], float) * 1000.0
        AX = [_np.array(F1[k], float) for k in ("x", "y", "z")]
        L, W, T = float(sp["L_mm"]), float(sp["W_mm"]), float(sp["T_mm"])
        sgn = 1
        if F0.get("origin"):
            d = _np.array(F0["origin"], float) * 1000.0 - O
            sgn = 1 if float(_np.dot(d, AX[2])) >= 0 else -1
        # 固定偏移(老倪目视标定, 不跑检测 ⇒ 框不跳动): 相机系里平移, 再转到 base
        off = _np.zeros(3)
        try:
            rf = json.load(open(os.path.join(REPO, "zmax_data", "ar_state", "tool1_refine.json"), encoding="utf-8"))
            o_cam = _np.array(rf.get("cam_offset_mm") or [0, 0, 0], float)
            M = _np.array(json.load(open(os.path.join(REPO, "models", "handeye_state.json")))["T_cam2tool"], float)
            if _np.abs(M[:3, 3]).max() < 10: M[:3, 3] *= 1000.0
            R_c2b = R_b2t @ M[:3, :3]
            off = R_c2b @ o_cam
        except Exception:                                                        # noqa: BLE001
            pass
        O = O + off
        C = O + AX[2] * (L / 2.0 * sgn)
        cs = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    cs.append(C + AX[0] * (T / 2) * sx + AX[1] * (W / 2) * sy + AX[2] * (L / 2) * sz)
        return cs, None

    def _box_arm_jpeg(self):
        """在**手臂相机**帧上画光模块 3D 框(手眼实时投影)。腕上相机没有固定外参 ⇒ 每帧算。"""
        import numpy as _np
        cs, err = self._module_corners_mm()
        img = snap_cam("arm")
        if img is None:
            return None, "取不到臂相机帧"
        if cs is None:
            b = cv2.imencode(".jpg", img)[1].tobytes()
            return b, err
        t = read_tcp()
        F1 = (t.get("frames") or {})["tool1"]
        R_b2t = _np.column_stack([_np.array(F1[k], float) for k in ("x", "y", "z")])
        M = _np.array(json.load(open(os.path.join(REPO, "models", "handeye_state.json")))["T_cam2tool"], float)
        if _np.abs(M[:3, 3]).max() < 10:
            M[:3, 3] *= 1000.0
        cam = _np.array(F1["origin"], float) * 1000.0 + R_b2t @ M[:3, 3]
        R_c2b = R_b2t @ M[:3, :3]
        K = _np.array(json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))["K"], float).reshape(3, 3)
        sp = self._module_spec()

        def pr(p):
            q = R_c2b.T @ (_np.asarray(p, float) - cam)
            if q[2] <= 1: return None
            return (int(round(K[0, 0] * q[0] / q[2] + K[0, 2])), int(round(K[1, 1] * q[1] / q[2] + K[1, 2])))
        P = [pr(c) for c in cs]
        ix = lambda a, b, c: ((a + 1) // 2) * 4 + ((b + 1) // 2) * 2 + ((c + 1) // 2)
        edges = []
        for a in (-1, 1):
            for b in (-1, 1): edges.append((ix(a, b, -1), ix(a, b, 1)))
        for a in (-1, 1):
            for c in (-1, 1): edges.append((ix(a, -1, c), ix(a, 1, c)))
        for b in (-1, 1):
            for c in (-1, 1): edges.append((ix(-1, b, c), ix(1, b, c)))
        n_draw = 0
        for i, j in edges:
            if P[i] and P[j]:
                cv2.line(img, P[i], P[j], (0, 255, 0), 2, cv2.LINE_AA); n_draw += 1
        if P[0]:
            cv2.circle(img, P[0], 4, (0, 0, 255), -1)
        cv2.putText(img, "MOD %.1fx%.1fx%.1fmm  edges %d/12  FIXED(+2mm up)" % (float(sp["L_mm"]), float(sp["W_mm"]), float(sp["T_mm"]), n_draw),
                    (6, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
        return cv2.imencode(".jpg", img)[1].tobytes(), None

    def _module_spec(self):
        """光模块长方体规格 + 与 tool1 的轴向约定(老倪 2026-10-25 定的口径)。

        tool1 原点 = **模块头中心**(长方体沿 Z 的一端); X = 上表面法向(厚度);
        Y = 侧面法向(宽度); Z = 上表面中轴线(长度)。
        """
        d = dict(self.MOD_DEFAULT)
        try:
            d.update(json.load(open(self.MODSPEC, encoding="utf-8")))
            d["ok"] = True
        except Exception:                                                        # noqa: BLE001
            d["ok"] = True
            d["src"] = d.get("src") or self.MOD_DEFAULT["src"]
            d["note"] = "还没落 module_spec.json, 用默认标称值"
        d["axes"] = "tool1: X=上表面法向(厚度) · Y=侧面法向(宽度) · Z=上表面中轴线(长度) · 原点=模块头中心"
        return d

    def _traj_plan(self):
        """当前规划轨迹（老倪要"先画出来、我看到再执行" ⇒ 页面读的就是执行器读的同一份）。"""
        p = os.path.join(self.TRAJ_DIR, "planned_traj.json")
        try:
            d = json.load(open(p, encoding="utf-8"))
            d["age_s"] = round(time.time() - float(d.get("ts") or 0), 1)
            d["stale"] = d["age_s"] > self.TRAJ_MAX_AGE
            d["ok"] = True
            return d
        except Exception as e:                                                   # noqa: BLE001
            return {"ok": False, "err": "还没有规划轨迹 (%s)" % str(e)[:80]}

    def _traj_exec_state(self):
        p = os.path.join(self.TRAJ_DIR, "traj_state.json")
        try:
            d = json.load(open(p, encoding="utf-8"))
            d["age_s"] = round(time.time() - float(d.get("t") or 0), 1)
            d["ok"] = True
            return d
        except Exception:                                                        # noqa: BLE001
            return {"ok": False, "phase": "none"}

    def _traj_plan_from_named(self, k, target=None):
        """把页面高亮的命名轨迹转成执行段表 (tools/traj_from_named.py)。

        全流程真源仍是那个脚本: 起点闸/预检/写 planned_traj.json + plan_latest.json 都在它里面,
        这里只负责跑它并把**失败原因原样带回页面** (不能笼统报"失败", 人要知道是起点不一致还是净空不够)。
        """
        exe = [sys.executable, os.path.join(HERE, "traj_from_named.py"), "--k", str(k)]
        # 🎯 轨迹5 的目标点是页面上选的(单选) —— 必须**原样**传下去, 否则页面显示到 A 点、
        #    执行却去了安全点1 (看着A执行B, 事故级)
        if str(k) == "real" and target:
            exe += ["--target", str(target)]
        # 建图轨迹(覆盖扫描)起点不在当前 TCP: 允许把「TCP→首点」也拆成段写进同一份段表,
        # 否则点执行永远被起点闸拒(实测差 520mm)。其余轨迹保持严格起点闸, 不许偷偷飞过去。
        if str(k) in ("map",):
            exe.append("--lead-in")
        try:
            pr = subprocess.run(exe, cwd=REPO, capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            return {"ok": False, "msg": "命名轨迹转段表超时(240s)"}
        out = (pr.stdout or "") + (pr.stderr or "")
        if pr.returncode != 0:
            bad = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("⛔")]
            return {"ok": False, "msg": bad[0] if bad else "命名轨迹转段表失败(见 exec_stdout.log)"}
        tot = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("总长")]
        return {"ok": True, "msg": tot[-1] if tot else "段表已生成", "k": k}

    def _traj_exec_start(self, speed_mm_s=None):
        """『▶ 执行轨迹』按钮的后端: 复核(规划新鲜/预检过/授权窗) → 后台起 traj_exec.py。

        命令**只进** l2_daemon 的 FIFO（唯一执行收口），本服务不直连 SDK、不自己下发。

        🎚 2026-10-26 老倪「在 执行轨迹 按钮上边，给出速度 5mm/s 10mm/s 50mm/s 三个档位」:
          speed_mm_s(真实 mm/s) 一路透传: 本接口 → traj_exec.py --speed-mm-s → 每条 FIFO 行
          → l2_daemon._bridge_send 优先采用(压过 env ZMAX_L2_MM_S)。缺省 None ⇒ 用 env(10mm/s)。
        """
        plan = self._traj_plan()
        if not plan.get("ok"):
            return {"ok": False, "msg": plan.get("err") or "没有规划轨迹"}
        if plan.get("stale"):
            return {"ok": False, "msg": "规划已 %.0f 分钟, 位姿早变了 ⇒ 请重新规划" % (plan["age_s"] / 60.0)}
        if not ((plan.get("precheck") or {}).get("ok")):
            return {"ok": False, "msg": "规划预检未通过(净空 %.1fmm) ⇒ 不发" % (
                (plan.get("precheck") or {}).get("worst_mm") or -1)}
        # 🔒 授权闸先判: 过期就直接告诉人, 不要"已下发"然后执行器静默拒发(用户会以为机器该动了却没动)
        try:
            _au = json.load(open(os.path.join(REPO, "zmax_data", "ctl_auth.json"), encoding="utf-8"))
            _until = float(_au.get("until") or 0)
            _left = _until - time.time()
            if float(_au.get("revoked_at") or 0) > 0:
                return {"ok": False, "msg": "授权已被撤销 ⇒ 先在 8793 页面重新做现场授权"}
            if _left <= 0:
                return {"ok": False, "msg": "授权窗已过期 %.0f 分钟 ⇒ 先在 8793 页面点现场授权, 再点执行轨迹" % (-_left / 60.0)}
        except Exception as e:                                                   # noqa: BLE001
            return {"ok": False, "msg": "读不到授权真源(ctl_auth.json): %s" % str(e)[:60]}
        st = self._traj_exec_state()
        if st.get("phase") == "running" and float(st.get("age_s") or 99) < 3:
            return {"ok": False, "msg": "轨迹正在执行中(第 %s 段)" % st.get("seg")}
        log = os.path.join(self.TRAJ_DIR, "exec_stdout.log")
        os.makedirs(self.TRAJ_DIR, exist_ok=True)
        f = open(log, "ab")
        _argv = [sys.executable, os.path.join(HERE, "traj_exec.py")]
        try:
            _sms = float(speed_mm_s) if speed_mm_s else 0.0
        except (TypeError, ValueError):
            _sms = 0.0
        if _sms > 0:
            _argv += ["--speed-mm-s", ("%.1f" % _sms)]
        pr = subprocess.Popen(_argv, cwd=REPO,
                              stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        _sp_txt = ("%.0fmm/s(档位)" % _sms) if _sms > 0 else "env(默认10mm/s)"
        return {"ok": True, "pid": pr.pid, "n_seg": plan.get("n_seg"), "speed_mm_s": (_sms or None),
                "msg": "已下发: %d 段 / %.0fmm · 速度 %s (执行器 l2_daemon · FIFO 收口)" % (
                    plan.get("n_seg") or 0, plan.get("total_mm") or 0, _sp_txt)}

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
        if p == "/api/autolight/docx":          # 📄 工艺卡 → Word(.docx) 一键导出
            # 真源是页面 CARDS（tools/web/autoLight.html）：前端把卡片文字 + canvas 截图传上来,
            # 这里只排版（python-docx）。不要在服务端复制一份工艺文字, 否则改页面会与导出不一致。
            try:
                from autolight_docx import build_docx
                _d = build_docx(body)
                _fn = "autolight_process_cards_%s.docx" % time.strftime("%Y%m%d_%H%M%S")
                self._send(200,
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           _d, {"Content-Disposition": 'attachment; filename="%s"' % _fn})
            except Exception as _e:                                            # noqa: BLE001
                self.log_message("autolight docx FAIL: %s: %s", type(_e).__name__, _e)
                self._json({"ok": False, "err": "%s: %s" % (type(_e).__name__, _e)})
        elif p == "/api/module3d_lock":     # 🔒 绿框定主 (lock|unlock|status)
            self._json(self._mod3_lock(str(body.get("action") or "status")))
        elif p == "/agreement/open":        # 📄 技术协议: 在工位机桌面打开 Word(真起进程)
            self._json(_agreement_open())
        elif p == "/api/aoi/inspect":            # 🔍 真拍 + 缺陷检测 + 矩形搜索 + 侧边修正
            self._json(self._aoi_inspect(port=int(body.get("port") or 10082)))
        elif p == "/api/calib":
            self._json(self._do_calib(body))
        elif p == "/api/fence/add":        # 🧱 加长方体/正方体/直线 (对角两点, base 系, 米)
            try:
                self._fence_audit("/api/fence/add", "-", body)
                it = FS.add(body.get("type") or "box", body.get("p1"), body.get("p2"),
                            name=body.get("name") or "", color=body.get("color") or "",
                            note=body.get("note") or "", pts=body.get("pts"))
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
        elif p == "/api/fence/undo":        # ↩ 回到上一步 (老倪 2026-10-27 误拖料盘后要的)
            # 每次写操作(加/改/删)之前都会存一份快照, 这里用最近一份覆盖回去。
            # steps 默认 1 = 退一步, 可以一次退多步; 回退本身也留快照(可再撤回)。
            try:
                _steps = int(body.get("steps") or 1)
                self._fence_audit("/api/fence/undo", "-", body)
                _res = FS.undo(_steps)
                if _res.get("ok"):
                    _res["undo_n"] = len(FS.history(60))
                self._json(_res)
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
        elif p == "/api/auth":
            # 🔴 2026-10-26 老倪「轨迹2执行，你怎么不动？」——
            #    真因是授权窗过期(10.5 小时前), 服务端在发段表之前就拒了, 一行小字他没看见。
            #    这里只读授权真源, 给页面做**顶部横幅**: 过期=红条, 有授权=绿条, 不让人猜。
            try:
                _d = json.load(open(os.path.join(REPO, "zmax_data", "ctl_auth.json"), encoding="utf-8"))
            except Exception as e:                                               # noqa: BLE001
                self._json({"ok": False, "err": "读不到 ctl_auth.json: %s" % str(e)[:60]})
                return
            _u = float(_d.get("until") or 0)
            _left = _u - time.time()
            _rev = float(_d.get("revoked_at") or 0) > 0
            self._json({"ok": True, "armed": (not _rev) and _left > 0, "epoch": _d.get("epoch"),
                        "left_s": round(max(0.0, _left)), "left_min": round(max(0.0, _left) / 60.0, 1),
                        "revoked": _rev, "until": _u,
                        "where": "8793 工位总览 → 授权真动(两步确认)"})
        elif p == "/api/traj/exec":
            # 🧭 2026-10-26 老倪: 「点轨迹按钮→高亮→三维里看着→点执行就发指令」
            #   带 k 就先把它转成段表(planned_traj.json), 再走原来的执行闸;
            #   不带 k 保持老行为(执行当前规划航路)。
            _k = str((body or {}).get("k") or "").strip()
            _tg = str((body or {}).get("target") or "").strip()
            # 🎚 2026-10-26 老倪「在 执行轨迹 按钮上边，给出速度 5mm/s 10mm/s 50mm/s 三个档位」
            #   页面把选中的档位以真实 mm/s 传上来, 一路透传到执行器; 缺省 ⇒ 用 env(10mm/s)。
            try:
                _sms = float((body or {}).get("speed_mm_s") or 0) or None
            except (TypeError, ValueError):
                _sms = None
            if _k:
                _pr = self._traj_plan_from_named(_k, _tg)
                if not _pr.get("ok"):
                    self._json(_pr)
                    return
            r = self._traj_exec_start(speed_mm_s=_sms)
            self._json(r)
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
                "/api/rs_detect": "/api/detect", "/api/rs_point": "/api/point",
                # 🆕 2026-10-20 老倪选 B: D435 专用 1 类小头(只给 2D 框)
                #   ⚠ 本进程在 do_GET 开头就把 **所有 /api/rs_** 交给这里代理(见 665 行), 所以这条必须
                #   做成**路径映射**; 在 elif 链里加 p=="/api/rs_detect_d435" 是够不到的(死代码)。
                "/api/rs_detect_d435": "/api/detect_d435"}
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
    # 🧵 2026-10-26 (老倪: 「按照你的建议来」) —— 进程模型: fork-per-connection → **单进程多线程**
    #   旧模型现场实测的代价(ForkingMixIn, max_children=24): 多开几个 AR 页后 24 个子进程、
    #     RSS 合计 12.3GB、LISTEN backlog=5 且 Recv-Q 已满 6 ⇒ 新连接排队,
    #     `curl -L 8793/ar` 走那条 302 要 **175.8s** 才通(直连也 30s 超时) ⇒ AR 按钮"打不开"(窗口空白)。
    #   为什么以前线程模型会憋死(74 线程 / 16 CLOSE-WAIT / 主线程卡 futex): 那时**没有读超时、
    #     也没有线程上限**, 断链的连接把线程永久挂住。现在两个都补齐:
    #       · H.timeout = 20 秒(读/写超时即收尾) · 线程数上限 + 信号量(满了直接关连接, 不排长队)
    #       · backlog 128(原来 5) —— 页面一次开 10Hz 轮询 + 4 路流是正常行为, 不许排队。
    class _ThreadingSrv(socketserver.ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        block_on_close = False
        request_queue_size = 128
        max_workers = 96
        def __init__(self, *a, **kw):
            self._sem = threading.BoundedSemaphore(self.max_workers)
            super().__init__(*a, **kw)
        def process_request_thread(self, request, client_address):
            if not self._sem.acquire(blocking=False):
                try:                                                # 满载: 关掉这条, 页面自己会重试
                    request.close()
                except Exception:                                   # noqa: BLE001
                    pass
                return
            try:
                super().process_request_thread(request, client_address)
            finally:
                self._sem.release()
    try:                                    # 🔴 光模块检测线程: 父进程常驻, 请求只读结果(不在请求里跑推理)
        OB3.warm()
        threading.Thread(target=_mod3_worker, name="mod3", daemon=True).start()
        print("  🔍 光模块检测线程: 已启动 (结果 → /dev/shm/mod3_latest.json, 供 /api/module3d 读)")
    except Exception as _e:                                                 # noqa: BLE001
        print("  🔍 光模块检测线程启动失败: %s" % _e)
    srv = _ThreadingSrv(("0.0.0.0", PORT), H)
    print("  🧵 进程模型: 单进程多线程 (backlog=%d · 线程上限=%d · 读超时=%ss)"
          % (srv.request_queue_size, srv.max_workers, H.timeout))
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
        elif (time.time() - float(prev.get("last_ts") or prev.get("ts") or 0)) > float(
                os.environ.get("ZMAX_MOD_STALE_MAX_S", "3.0")):
            # 🆕 2026-10-22 现场(老倪: 「手臂相机现在没有光模块, 不需要显示绿色边界框」):
            #   沿用旧框**必须有上限**。老逻辑是"只要以前检出过就一直沿用" ⇒ 明明画面上没有模块,
            #   那个(橙虚线)框会无限期挂在页面上。⇒ 超过 ZMAX_MOD_STALE_MAX_S(默认 3s)仍没检出,
            #   就写一份干净的"未检出"(ok=False), 页面自然不画框; 3s 内的短暂漏检仍按旧框+stale 明示。
            r["ts"] = time.time()
            r["t"] = time.strftime("%H:%M:%S")
            r["stale"] = False
            r["box_expired"] = True
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
