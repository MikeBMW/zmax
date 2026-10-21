#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slam_map_service.py — 建图服务 (Intel 上跑建图, 4060 上显示)

老倪 2026-10-22: 「在 intel 上完成 slam 建图, 建好的图变成服务, 在 4060 显示,
                  先做程序, 再将已经有的点先运行建图」

═══ 口径澄清 (写进代码, 避免自欺) ═══
本项目**没有 LiDAR、没有移动底盘**。臂上 D405 的位姿来自机械臂 TCP 真值(50Hz),
不是靠 SLAM 估出来的 ⇒ 这里是「**已知位姿的建图**」, 比传统 SLAM 少了位姿估计这一环,
精度上限由手眼标定决定(实测 TSAI 闭环 1.74mm)。不要对外宣称"SLAM 定位精度 X"。

═══ 数据源 (都是既有的, 不新造) ═══
  ① 深度点云  zmax_data/ss_live/depth_map/depth_raw.npy (480x640 uint16, 0.1mm/unit)
                + stats.json (内参 fx/fy/cx/cy + handeye + tcp) ⇒ 反投影到 base 系
  ② 采集数据集 zmax_data/gs_assets/<blk>/ (COLMAP cameras.json + images/)

═══ 服务端点 (给 4060 显示) ═══
  GET /map/status        建图状态 (就绪/进度/时间戳/点数/bbox)
  GET /map/meta          地图元数据 (坐标系/单位/内参/手眼/来源)
  GET /map/points.bin    点云二进制 (float32 xyz 平铺, 供 WebGL 直接灌 buffer)
  GET /map/points.json   点云 JSON (小图/调试; 超过 20 万点自动降采样)
  GET /map/topdown.png   俯视图 (XY 栅格, 深色背景 + 高度着色)
  GET /map/side.png      侧视图 (XZ 栅格)
  GET /                   单页查看器 (4060 打开即看)

用法:
  # 用已有深度点云建图并起服务 (默认)
  python3 slam_map_service.py --port 8801 --source depth
  # 从已有 COLMAP 数据集合成点云
  python3 slam_map_service.py --port 8801 --source colmap --blk blkA
  # 只建图不出服务 (落盘后退出)
  python3 slam_map_service.py --once
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 路径全部可用环境变量覆盖 —— 部署到别的机器(如 Intel 192.168.23.70)时
# 目录结构不一样, 硬编码会直接崩 (2026-10-22 部署时踩到)
MAP_DIR = os.environ.get("ZMAX_MAP_OUT", os.path.join(ROOT, "zmax_data", "slam_map"))
DEPTH_DIR = os.environ.get("ZMAX_MAP_DEPTH_DIR", os.path.join(ROOT, "zmax_data", "ss_live", "depth_map"))
GS_ASSETS = os.environ.get("ZMAX_MAP_GS_ASSETS", os.path.join(ROOT, "zmax_data", "gs_assets"))
os.makedirs(MAP_DIR, exist_ok=True)
# 与 tools/ros_scene_depth_build.py 同源: DEPTH_SCALE=0.0001 m/unit, 有效阈值 0.05m
MIN_DEPTH_MM = float(os.environ.get('ZMAX_MAP_MIN_DEPTH_MM', '50'))

# 全局地图状态 (单写者: 建图线程; 多读者: HTTP 线程)
MAP = {
    "ready": False,
    "state": "init",
    "msg": "",
    "points": None,        # (N,3) float32, base 系 mm
    "colors": None,        # (N,3) uint8 或 None
    "meta": {},
    "topdown": None,       # (H,W,3) uint8 RGB
    "side": None,
    "updated": 0.0,
}
LOCK = threading.Lock()


# ────────────────────────── 深度图 → base 系点云 ──────────────────────────
def backproject_depth(depth_u16, stats):
    """按 stats.json 的内参 + 手眼, 把深度图反投影到 base 系 (mm)。

    路径严格照 stats.json 的链路 (不自己发明):
      像素(u,v) + 深度 z ⇒ 相机系点 (Xc,Yc,Zc)
      ⇒ 手眼 X (相机→末端) ⇒ 末端系
      ⇒ TCP 位姿 (x,y,z + rpy 四元数口径看 stats['tcp'] 7 维) ⇒ base 系
    depth_scale 由 stats 给 (实测 0.1 mm/unit, 与 memory 一致)。
    """
    K = stats.get("intrinsics", {})
    fx, fy = float(K.get("fx", 0)), float(K.get("fy", 0))
    cx, cy = float(K.get("cx", 0)), float(K.get("cy", 0))
    scale = float(stats.get("depth_scale_mm_per_unit", 0.1))
    if fx <= 0 or fy <= 0:
        raise RuntimeError("内参缺失 (fx/fy), 无法反投影")

    h, w = depth_u16.shape
    z = depth_u16.astype(np.float32) * scale          # mm
    # 有效判据必须与真源 tools/ros_scene_depth_build.py 一致: z_m > 0.05 (50mm)。
    # 只判 z>0 会把近距噪声点也反投影出去, 实测直接把 bbox 撑到 Z[-3322,1158]mm
    # (真源 bbox 是 Z[-1224,337]mm) —— 2026-10-22 踩过。
    valid = z > MIN_DEPTH_MM
    vv, uu = np.nonzero(valid)
    zc = z[vv, uu]
    xc = (uu.astype(np.float32) - cx) * zc / fx
    yc = (vv.astype(np.float32) - cy) * zc / fy
    Pc = np.stack([xc, yc, zc], axis=1)               # 相机系 mm

    # 手眼: X_t_mm 是平移; 旋转在 stats['handeye'] 里若无则按单位阵处理并标注
    he = stats.get("handeye", {})
    X_t = np.array(he.get("X_t_mm", [0, 0, 0]), float)
    X_R = np.array(he.get("X_R", np.eye(3).tolist()), float)
    Pe = (Pc @ X_R.T) + X_t                            # 相机 → 末端

    # TCP 7 维: [x,y,z, qx,qy,qz,qw] 或 [x,y,z, rx,ry,rz,_]
    tcp = np.array(stats.get("tcp", [0] * 7), float)
    t = tcp[:3]
    if len(tcp) >= 7:
        q = tcp[3:7]
        nq = float(np.linalg.norm(q))
        if nq > 1e-6 and abs(nq - 1.0) < 0.2:          # 像四元数
            R = quat_to_R(q / nq)
        else:                                           # 当欧拉角处理
            R = euler_to_R(q)
    else:
        R = np.eye(3)
    Pb = Pe @ R.T + t                                  # 末端 → base (mm)
    return Pb.astype(np.float32), (valid.sum())


def quat_to_R(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], float)


def euler_to_R(rpy):
    rx, ry, rz = rpy
    Rx = np.array([[1, 0, 0], [0, np.cos(rx), -np.sin(rx)], [0, np.sin(rx), np.cos(rx)]])
    Ry = np.array([[np.cos(ry), 0, np.sin(ry)], [0, 1, 0], [-np.sin(ry), 0, np.cos(ry)]])
    Rz = np.array([[np.cos(rz), -np.sin(rz), 0], [np.sin(rz), np.cos(rz), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


# ────────────────────────── 离群点剔除 ──────────────────────────
def remove_outliers(P, k=12, std_ratio=2.0, chunk=20000):
    """统计离群点剔除 (SOR): 每点到 k 近邻的平均距离 > 全局均值+std_ratio*std 则剔。

    为什么必须做: 深度图里的飞点(反光/边缘/无效插值)反投影后会把 bbox 撑得离谱。
    实测 depth_raw.npy 全部有效像素 257,172 点 ⇒ bbox Z[-3322,1158]mm;
    官方 stats.json 给的 bbox 是 Z[-1224,337]mm (7,163 点, 已剔离群)。
    不剔离群就把"环境多大"报错, 后面所有几何判断都跟着错。
    """
    n = len(P)
    if n == 0:
        return P, {"in": 0, "out": 0, "removed_frac": 0.0}
    if n > 300000:
        # 太大时分块算, 避免 (n,n) 距离矩阵爆内存
        keep = np.ones(n, bool)
    else:
        keep = None
    # 用 KD-tree (scipy 有就用, 没有退化到随机抽样参照)
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(P)
        d, _ = tree.query(P, k=min(k + 1, n), workers=-1)
        d = d[:, 1:]                                   # 去掉自身
        mean_d = d.mean(axis=1)
        thr = mean_d.mean() + std_ratio * mean_d.std()
        keep = mean_d <= thr
    except ImportError:
        # 无 scipy: 用体素占用法, 剔除孤立体素
        vox = np.floor(P / 5.0).astype(np.int64)        # 5mm 体素
        key = vox[:, 0] * 73856093 ^ vox[:, 1] * 19349663 ^ vox[:, 2] * 83492791
        uniq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        keep = cnt[inv] >= 3                            # 邻居<3 的孤立点剔除
    out = P[keep]
    return out.astype(np.float32), {"in": int(n), "out": int(len(out)),
                                    "removed_frac": round(float(1 - len(out) / max(n, 1)), 4)}


# ────────────────────────── 栅格化渲染 ──────────────────────────
def rasterize(P, axis_a=0, axis_b=1, res=0.0, px=900, flip_b=True, dense_px=400000):
    """把点云投影成 (H,W,3) 俯视/侧视栅格图。高度用第三轴着色。

    返回 (rgb, extent) —— extent=[min_a,max_a,min_b,max_b] 供查看器换回世界坐标。
    """
    if P is None or len(P) == 0:
        return np.zeros((px, px, 3), np.uint8), [0, 1, 0, 1]
    a = P[:, axis_a]
    b = P[:, axis_b]
    c = P[:, 3 - axis_a - axis_b] if P.shape[1] > 2 else np.zeros(len(P))
    amin, amax = float(a.min()), float(a.max())
    bmin, bmax = float(b.min()), float(b.max())
    span = max(amax - amin, bmax - bmin, 1e-6)
    W = px
    H = px
    ia = ((a - amin) / span * (W - 1)).astype(np.int32)
    ib = ((b - bmin) / span * (H - 1)).astype(np.int32)
    if flip_b:
        ib = (H - 1) - ib
    ia = np.clip(ia, 0, W - 1)
    ib = np.clip(ib, 0, H - 1)
    img = np.zeros((H, W, 3), np.float32)
    cnt = np.zeros((H, W), np.float32)
    # 高度 → 伪彩 (低=蓝, 中=绿, 高=红)
    cmin, cmax = float(np.percentile(c, 2)), float(np.percentile(c, 98))
    t = np.clip((c - cmin) / max(cmax - cmin, 1e-6), 0, 1)
    col = np.stack([t, 1 - np.abs(t - 0.5) * 2, 1 - t], axis=1)
    np.add.at(img, (ib, ia), col)
    np.add.at(cnt, (ib, ia), 1)
    # ⚠ 必须先存 empty 标记再除: 早先把 cnt==0 直接改成 1, 导致后面 empty 判断永远 False,
    #   背景成了纯黑(看着像"没读到"), 实测整图亮度只有 3.1 —— 2026-10-22 踩过
    empty = (cnt <= 0)
    safe = np.where(cnt == 0, 1.0, cnt)
    img = img / safe[:, :, None]
    rgb = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    # 点只有 1 像素会看不清 ⇒ 3x3 膨胀, 让稀疏点云可见
    if dense_px and len(P) < dense_px:
        pad = np.pad(rgb, ((1, 1), (1, 1), (0, 0)), mode="edge")
        acc = np.zeros_like(rgb[..., 0], dtype=np.uint8)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                acc = np.maximum(acc, pad[dy:dy + H, dx:dx + W].max(axis=2))
        grown = acc > 0
        for ch in range(3):
            ch_max = np.zeros_like(rgb[..., ch])
            for dy in (0, 1, 2):
                for dx in (0, 1, 2):
                    ch_max = np.maximum(ch_max, pad[dy:dy + H, dx:dx + W, ch])
            rgb[..., ch] = np.where(grown & (rgb[..., ch] == 0), ch_max, rgb[..., ch])
    # 空处给深灰底(不是纯黑), 一眼能分清"没数据"和"数据黑"
    rgb[empty] = (18, 21, 26)
    return rgb, [round(amin, 2), round(amax, 2), round(bmin, 2), round(bmax, 2)]


# ────────────────────────── 建图任务 ──────────────────────────
def build_from_depth(downsample=0):
    """用已有深度点云建图 (默认路径: 用户「将已经有的点先运行建图」)"""
    dpath = os.path.join(DEPTH_DIR, "depth_raw.npy")
    spath = os.path.join(DEPTH_DIR, "stats.json")
    if not os.path.exists(dpath):
        raise RuntimeError("缺少深度图: %s" % dpath)
    if not os.path.exists(spath):
        raise RuntimeError("缺少 stats.json: %s" % spath)
    stats = json.load(open(spath))
    d = np.load(dpath)
    P, n_valid = backproject_depth(d, stats)
    P_raw = P.copy()
    P, sor = remove_outliers(P, k=12, std_ratio=2.0)
    if downsample and len(P) > downsample:
        idx = np.random.default_rng(0).choice(len(P), downsample, replace=False)
        P = P[idx]
    return P, {
        "source": "depth_map/depth_raw.npy",
        "depth_shape": list(d.shape),
        "depth_scale_mm_per_unit": stats.get("depth_scale_mm_per_unit"),
        "valid_pixels": int(n_valid),
        "outlier_removal": sor,
        "raw_points": int(len(P_raw)),
        "handeye": stats.get("handeye", {}).get("method", ""),
        "handeye_closed_loop_std_mm": stats.get("handeye", {}).get("closed_loop_std_mm"),
        "tcp_at_capture": stats.get("tcp"),
        "captured_at": stats.get("at"),
        "intrinsics": stats.get("intrinsics"),
        "frame": "base (mm) · 手眼 TSAI · 位姿来自 TCP 真值",
    }


def build_from_colmap(blk, downsample=0):
    """用已有 COLMAP 数据集 (gs_assets/<blk>) 合成点云 —— 需要稀疏重建的 points3D。
    没有 points3D 时明确报错, 绝不拿图像瞎造点。"""
    d = os.path.join(GS_ASSETS, blk)
    if not os.path.isdir(d):
        raise RuntimeError("没有该 blk: %s" % d)
    p3d = None
    for cand in ("points3D.bin", "points3D.txt", "sparse/0/points3D.bin"):
        p = os.path.join(d, cand)
        if os.path.exists(p):
            p3d = p
            break
    if p3d is None:
        n_img = 0
        imgd = os.path.join(d, "images")
        if os.path.isdir(imgd):
            n_img = len([x for x in os.listdir(imgd) if x.lower().endswith(('.jpg', '.png'))])
        raise RuntimeError("%s 只有 %d 张图, 无 sparse/points3D ⇒ 不能当点云建图。"
                           "要走 3DGS 请用 tools/gs_map_run.py (训练会产出高斯点)。" % (blk, n_img))
    raise RuntimeError("points3D 解析未实现 (当前 blk=%s); 请走 depth 源或先跑 gs 训练" % blk)


def build(source="depth", blk=None, downsample=0):
    with LOCK:
        MAP["state"] = "building"
        MAP["ready"] = False
        MAP["msg"] = "建图中 (%s)" % source
    t0 = time.time()
    try:
        if source == "depth":
            P, meta = build_from_depth(downsample)
        elif source == "colmap":
            P, meta = build_from_colmap(blk or "blkA", downsample)
        else:
            raise RuntimeError("未知 source: %s" % source)
        td, ext_xy = rasterize(P, axis_a=0, axis_b=1, px=900)
        sd, ext_xz = rasterize(P, axis_a=0, axis_b=2, px=900)
        meta.update({
            "n_points": int(len(P)),
            "bbox_mm": {"x": [float(P[:, 0].min()), float(P[:, 0].max())],
                        "y": [float(P[:, 1].min()), float(P[:, 1].max())],
                        "z": [float(P[:, 2].min()), float(P[:, 2].max())]},
            "extent_xy": ext_xy, "extent_xz": ext_xz,
            "build_secs": round(time.time() - t0, 2),
            "built_at": time.strftime("%F %T"),
        })
        with LOCK:
            MAP.update({"ready": True, "state": "ready", "msg": "建图完成",
                        "points": P, "meta": meta, "topdown": td, "side": sd,
                        "updated": time.time()})
        # 落盘 (地图成为可复用的资产)
        np.save(os.path.join(MAP_DIR, "points_base_mm.npy"), P)
        json.dump(meta, open(os.path.join(MAP_DIR, "meta.json"), "w"),
                  ensure_ascii=False, indent=1)
        try:
            from PIL import Image
            Image.fromarray(td).save(os.path.join(MAP_DIR, "topdown.png"))
            Image.fromarray(sd).save(os.path.join(MAP_DIR, "side.png"))
        except Exception:
            pass
        return True
    except Exception as e:
        with LOCK:
            MAP.update({"ready": False, "state": "failed", "msg": str(e),
                        "updated": time.time()})
        return False


# ────────────────────────── HTTP 服务 ──────────────────────────
VIEWER_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Z-MAX 地图服务</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0c10;color:#dfe3ea;font:13px/1.5 -apple-system,"Segoe UI",sans-serif}
header{padding:14px 18px;border-bottom:1px solid #1b2028;display:flex;gap:22px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;font-weight:600;letter-spacing:.02em}
.kv{color:#7d8794;font-size:12px}.kv b{color:#cfd6e0;font-weight:500}
.tag{padding:2px 8px;border-radius:10px;font-size:11px;background:#16202c;color:#63b3ed}
main{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:#1b2028;height:calc(100vh - 58px)}
.pane{background:#0a0c10;position:relative;overflow:hidden}
.pane img{width:100%;height:100%;object-fit:contain;display:block}
.lbl{position:absolute;top:10px;left:12px;font-size:11px;color:#5a6270;letter-spacing:.06em}
.err{color:#f87171}
</style></head><body>
<header>
  <h1>Z-MAX 地图服务</h1>
  <span class="tag" id="st">加载中</span>
  <span class="kv" id="meta"></span>
</header>
<main>
  <div class="pane"><span class="lbl">俯视 XY</span><img id="td" alt="topdown"></div>
  <div class="pane"><span class="lbl">侧视 XZ</span><img id="sd" alt="side"></div>
</main>
<script>
async function tick(){
  try{
    const r = await fetch('/map/status',{cache:'no-store'});
    const s = await r.json();
    document.getElementById('st').textContent = s.state + ' · ' + s.msg;
    document.getElementById('st').className = 'tag' + (s.state==='failed'?' err':'');
    if(s.meta && s.meta.n_points){
      const m = s.meta;
      document.getElementById('meta').innerHTML =
        '<b>'+m.n_points.toLocaleString()+'</b> 点 · 来源 <b>'+m.source+'</b>'+
        ' · bbox X['+m.bbox_mm.x.map(v=>v.toFixed(0)).join(',')+']'+
        ' Y['+m.bbox_mm.y.map(v=>v.toFixed(0)).join(',')+']'+
        ' Z['+m.bbox_mm.z.map(v=>v.toFixed(0)).join(',')+'] mm'+
        ' · 建图 <b>'+m.build_secs+'s</b> @ '+m.built_at;
    }
    const t = Date.now();
    document.getElementById('td').src = '/map/topdown.png?t='+t;
    document.getElementById('sd').src = '/map/side.png?t='+t;
  }catch(e){
    document.getElementById('st').textContent = '服务无响应';
    document.getElementById('st').className = 'tag err';
  }
}
tick(); setInterval(tick, 3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        with LOCK:
            ready = MAP["ready"]
            state = MAP["state"]
            msg = MAP["msg"]
            meta = MAP["meta"]
            P = MAP["points"]
            td = MAP["topdown"]
            sd = MAP["side"]
            updated = MAP["updated"]

        if path in ("/", "/index.html"):
            return self._send(200, VIEWER_HTML, "text/html; charset=utf-8")

        if path == "/map/status":
            return self._send(200, json.dumps({
                "ready": ready, "state": state, "msg": msg,
                "meta": meta, "updated": updated,
                "age_secs": round(time.time() - updated, 1) if updated else None,
            }, ensure_ascii=False))

        if path == "/map/meta":
            return self._send(200, json.dumps(meta, ensure_ascii=False, indent=1))

        if path == "/map/points.bin":
            if P is None:
                return self._send(503, json.dumps({"error": "地图未就绪", "state": state}))
            # 头部 16 字节: n(4B) + 保留, 后面 float32 xyz
            n = len(P)
            head = struct.pack("<II", n, 0)
            return self._send(200, head + P.astype("<f4").tobytes(),
                              "application/octet-stream")

        if path == "/map/points.json":
            if P is None:
                return self._send(503, json.dumps({"error": "地图未就绪", "state": state}))
            Pj = P
            if len(Pj) > 200000:
                idx = np.random.default_rng(0).choice(len(Pj), 200000, replace=False)
                Pj = Pj[idx]
            return self._send(200, json.dumps({
                "n": int(len(Pj)), "downsampled": bool(len(Pj) < len(P)),
                "xyz_mm": np.round(Pj, 1).tolist()}, ensure_ascii=False))

        if path in ("/map/topdown.png", "/map/side.png"):
            img = td if "topdown" in path else sd
            if img is None:
                return self._send(503, json.dumps({"error": "地图未就绪"}))
            try:
                import io
                from PIL import Image
                buf = io.BytesIO()
                Image.fromarray(img).save(buf, format="PNG")
                return self._send(200, buf.getvalue(), "image/png")
            except Exception as e:
                return self._send(500, json.dumps({"error": "PNG 编码失败: %s" % e}))

        return self._send(404, json.dumps({"error": "no route", "path": path}))


def serve(port=8801):
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("地图服务: http://0.0.0.0:%d/  (端点: /map/status /map/meta /map/points.bin /map/topdown.png)" % port)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8801)
    ap.add_argument("--source", default="depth", choices=["depth", "colmap"])
    ap.add_argument("--blk", default=None)
    ap.add_argument("--downsample", type=int, default=0, help="0=不降采样")
    ap.add_argument("--once", action="store_true", help="只建图落盘, 不起服务")
    a = ap.parse_args()

    ok = build(source=a.source, blk=a.blk, downsample=a.downsample)
    with LOCK:
        m = dict(MAP["meta"])
        st = MAP["state"]
        msg = MAP["msg"]
    if not ok:
        print("建图失败: %s" % msg)
        if a.once:
            sys.exit(1)
    else:
        print("建图完成: %d 点 · bbox X[%.1f,%.1f] Y[%.1f,%.1f] Z[%.1f,%.1f] mm · %.2fs"
              % (m["n_points"], m["bbox_mm"]["x"][0], m["bbox_mm"]["x"][1],
                 m["bbox_mm"]["y"][0], m["bbox_mm"]["y"][1],
                 m["bbox_mm"]["z"][0], m["bbox_mm"]["z"][1], m["build_secs"]))
        print("落盘: %s/points_base_mm.npy + meta.json + topdown.png + side.png" % MAP_DIR)
    if a.once:
        return
    serve(a.port)


if __name__ == "__main__":
    main()
