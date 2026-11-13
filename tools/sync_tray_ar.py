# -*- coding: utf-8 -*-
"""把 AR 场景(ar_station.xml)里的上料盘几何投到**手臂相机**当前帧, 并与画面实测料盘对齐。

用途: 回答"手臂相机能看到上料盘吗 / AR 场景的上料盘能不能和实际同步" —— 给像素级证据,
而不是只看渲染图。

跑法:
  ./gui-venv311/bin/python tools/sync_tray_ar.py                  # 抓 8791 臂相机一帧
  ./gui-venv311/bin/python tools/sync_tray_ar.py --frame x.jpg    # 用本地图
  ./gui-venv311/bin/python tools/sync_tray_ar.py --write-scene    # 用实测位姿回写场景(默认只报不改)

判据:
  1) 投影角点落在画面内的比例(要看得到才谈同步)
  2) 投影料盘外包 vs 画面实测暗区(黑色料盘) bbox 的 IoU / 中心差 px
  3) 每个槽中心投影是否落在料盘暗区掩膜内(槽真的在盘上, 而不是飘在旁边)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import scene_overlay as so   # noqa: E402

XML = REPO / "zmax_data/ar_mujoco/ar_station.xml"
OUT_DIR = Path("/tmp/ar_sync")
OUT_DIR.mkdir(parents=True, exist_ok=True)

GEOM_RE = re.compile(
    r'<geom\s+name="([^"]+)"\s+type="box"\s+pos="([-\d.eE]+) ([-\d.eE]+) ([-\d.eE]+)"'
    r'\s+size="([-\d.eE]+) ([-\d.eE]+) ([-\d.eE]+)"')


GEOM_TAG_RE = re.compile(r'<geom\s+name="([^"]+)"[^>]*?/>', re.S)


def _attr(tag, key, default=None, n=3):
    m = re.search(r'%s="([^"]+)"' % key, tag)
    if not m:
        return default
    v = [float(x) for x in m.group(1).split()]
    return np.array(v) if n and len(v) == n else v


def parse_tray_geoms(path=XML):
    """按名字归类: 上料盘底板/侧壁 + 槽位。同时读出 quat (w x y z) —— 回写后场景会带 yaw。"""
    txt = path.read_text(encoding="utf-8")
    tray, slots = [], []
    for m in GEOM_TAG_RE.finditer(txt):
        name, tag = m.group(1), m.group(0)
        if 'type="box"' not in tag:
            continue
        pos, size = _attr(tag, "pos"), _attr(tag, "size")
        if pos is None or size is None:
            continue
        quat = _attr(tag, "quat", np.array([1.0, 0.0, 0.0, 0.0]))
        item = {"name": name, "pos": pos, "size": size, "quat": quat}
        if name.startswith("b00_"):
            tray.append(item)
        elif re.match(r"^b(0[1-9]|1[0-4])_槽", name):
            slots.append(item)
    return tray, slots


def quat_to_R(q):
    w, x, y, z = [float(v) for v in q]
    n = np.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def fetch_arm_frame() -> np.ndarray:
    import urllib.request
    url = "http://127.0.0.1:8791/snapshot/arm.jpg"
    with urllib.request.urlopen(url, timeout=8) as r:
        buf = np.frombuffer(r.read(), np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("臂相机帧解码失败")
    return img


def project(pts_base, K, X, tcp7):
    """base 点 → 像素; 返回 uv, 相机系 z, 有效掩膜(z>0.05)。"""
    P = so.base_to_cam(np.asarray(pts_base, float), X, tcp7)
    z = P[:, 2]
    ok = z > 0.05
    uv = np.full((len(P), 2), np.nan)
    if ok.any():
        uv[ok, 0] = K["fx"] * P[ok, 0] / z[ok] + K["cx"]
        uv[ok, 1] = K["fy"] * P[ok, 1] / z[ok] + K["cy"]
    return uv, z, ok


def box_corners(pos, size):
    """MuJoCo box: pos=中心, size=半边长 ⇒ 8 角点。"""
    s = np.asarray(size, float)
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                out.append(np.asarray(pos, float) + np.array([sx * s[0], sy * s[1], sz * s[2]]))
    return np.array(out)


def face_quad(pos, size, top=True, quat=None):
    """某个面(顶/底)的 4 角**有序** (x-,y- → x+,y- → x+,y+ → x-,y+), 支持 box 自带 yaw。

    画框必须用有序四角: 直接 polyline 8 个角点会连成自交的"蝴蝶结",
    看起来像骑在隔墙上(实测被目检打回)。
    """
    s = np.asarray(size, float)
    p = np.asarray(pos, float)
    z = s[2] if top else -s[2]
    local = np.array([[-s[0], -s[1], z], [s[0], -s[1], z], [s[0], s[1], z], [-s[0], s[1], z]])
    if quat is not None:
        local = (quat_to_R(quat) @ local.T).T
    return local + p


def detect_tray_mask(img, seed_mask=None):
    """实测料盘: 黑色料盘 ⇒ 低亮度 + 低饱和的大块区域。

    有多块黑区域时(上料盘/左臂料盘/下料盘/阴影), **按与投影区的重叠量选**(不是按面积最大) ——
    否则会挑到旁边那块满高阴影, 得出"投影偏 217px"的假结论。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.int16)
    s = hsv[:, :, 1].astype(np.int16)
    m = ((v < 95) & (s < 110)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = [c for c in cnts if cv2.contourArea(c) >= 1200]
    if not cnts:
        return None, m
    best, best_ov = None, -1.0
    for c in cnts:
        one = np.zeros_like(m)
        cv2.drawContours(one, [c], -1, 255, -1)
        if seed_mask is not None:
            ov = float((one & seed_mask).sum())
        else:
            ov = float(cv2.contourArea(c))
        if ov > best_ov:
            best, best_ov = c, ov
    keep = np.zeros_like(m)
    cv2.drawContours(keep, [best], -1, 255, -1)
    return best, keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default="")
    ap.add_argument("--xml", default="", help="用指定场景 XML (A/B 对比用), 默认 zmax_data/ar_mujoco/ar_station.xml")
    ap.add_argument("--write-scene", action="store_true", help="用实测料盘中心回写场景(默认只报)")
    args = ap.parse_args()
    global XML
    if args.xml:
        XML = Path(args.xml)

    tcp7 = so.read_tcp()
    if tcp7 is None:
        print("✗ 读不到 TCP 真值 (rokae_sdk/tcp_out/latest.json 过期?)")
        return 2
    hc = so.load_handeye()
    if not hc.get("ok"):
        print("✗ 手眼不可用:", hc.get("why"))
        return 2
    X = hc["X"]

    img = cv2.imread(args.frame) if args.frame else fetch_arm_frame()
    H, W = img.shape[:2]
    K = so.load_intrinsics(W, H)

    tray, slots = parse_tray_geoms()
    print("AR 场景上料盘: %d 个本体 geom + %d 个槽位" % (len(tray), len(slots)))
    print("臂相机帧 %dx%d · TCP=(%.3f,%.3f,%.3f) · 手眼 %s std=%.2fmm"
          % (W, H, tcp7[0], tcp7[1], tcp7[2], hc.get("method"), float(hc.get("closed_loop_std_mm") or -1)))

    vis = img.copy()
    tray_uv_all, slot_uv = [], []
    tray_top_uv = None
    for g in tray:
        for top in (True, False):
            quad = face_quad(g["pos"], g["size"], top=top, quat=g.get("quat"))
            uv, z, ok = project(quad, K, X, tcp7)
            if ok.sum() == 4:
                tray_uv_all.append(uv)
                cv2.polylines(vis, [np.round(uv).astype(np.int32)], True, (255, 200, 0), 1)
                if top and g["name"].endswith("_bot"):
                    tray_top_uv = uv          # 底板顶面 = 料盘口沿, 用于和实测比 yaw/尺寸
    for g in slots:
        uv, z, ok = project(face_quad(g["pos"], g["size"], top=True, quat=g.get("quat")), K, X, tcp7)
        if ok.sum() == 4:
            slot_uv.append((g["name"], uv.mean(0), uv))
            cv2.polylines(vis, [np.round(uv).astype(np.int32)], True, (0, 220, 255), 1)

    all_uv = np.vstack([u for u in tray_uv_all if len(u)] + [p for _, _, p in slot_uv]) if (tray_uv_all or slot_uv) else np.zeros((0, 2))
    if len(all_uv) == 0:
        print("✗ 投影全部落在相机背后 (z<=0) —— 当前臂位姿看不到上料盘")
        cv2.imwrite(str(OUT_DIR / "arm_tray_sync.jpg"), vis)
        return 3
    inside = ((all_uv[:, 0] >= 0) & (all_uv[:, 0] < W) & (all_uv[:, 1] >= 0) & (all_uv[:, 1] < H)).mean()
    print("投影点: %d 个, 画面内 %.1f%%" % (len(all_uv), 100 * inside))

    # 投影区掩膜 (先用它当种子, 再拿去和实测暗区比)
    m_ok = np.isfinite(all_uv).all(1)
    m_in = np.zeros((H, W), np.uint8)
    if m_ok.sum() >= 4:
        poly = np.round(all_uv[m_ok]).astype(np.int32)
        cv2.fillConvexPoly(m_in, cv2.convexHull(poly), 255)

    # 实测料盘(暗区) 与 投影外包 对比
    cnt, mask = detect_tray_mask(img, m_in if m_ok.sum() >= 4 else None)
    # 只用投影附近(膨胀 15px)的暗像素量外框: 否则盘外的黑色夹具/阴影会把 minAreaRect 拉长
    # (实测长边虚高 +14.7% ⇒ yaw/尺寸都跟着歪)
    if m_ok.sum() >= 4:
        roi = cv2.dilate(m_in, np.ones((31, 31), np.uint8))
        m_roi = (mask & roi)
        cnts2, _ = cv2.findContours(m_roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts2:
            c2 = max(cnts2, key=cv2.contourArea)
            if cv2.contourArea(c2) >= 1200:
                cnt, mask = c2, cv2.drawContours(np.zeros_like(mask), [c2], -1, 255, -1)
    res = {"inside_ratio": float(inside), "n_slots_proj": len(slot_uv)}

    # 与"暗区检测"无关的独立判据: 投影区本身的亮度 vs 周围环带
    # 料盘是黑色 ⇒ 若投影落在料盘上, 区内应显著更暗 (ΔV>15)。
    if m_ok.sum() >= 4:
        m_ring = cv2.dilate(m_in, np.ones((25, 25), np.uint8)) & ~m_in
        v = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]
        v_in = float(np.median(v[m_in > 0])) if (m_in > 0).any() else float("nan")
        v_ring = float(np.median(v[m_ring > 0])) if (m_ring > 0).any() else float("nan")
        res.update({"V_in_proj": round(v_in, 1), "V_ring": round(v_ring, 1),
                    "delta_V": round(v_in - v_ring, 1)})
        print("投影区亮度 V=%.1f vs 周围 %.1f (Δ=%+.1f, 料盘为黑应显著更暗)"
              % (v_in, v_ring, v_in - v_ring))

    if cnt is not None:
        rx, ry, rw, rh = cv2.boundingRect(cnt)
        cv2.rectangle(vis, (rx, ry), (rx + rw, ry + rh), (80, 255, 80), 2)
        m = np.isfinite(all_uv).all(1)
        px0, py0 = np.floor(all_uv[m].min(0)).astype(int)
        px1, py1 = np.ceil(all_uv[m].max(0)).astype(int)
        inter = max(0, min(px1, rx + rw) - max(px0, rx)) * max(0, min(py1, ry + rh) - max(py0, ry))
        union = (px1 - px0) * (py1 - py0) + rw * rh - inter
        iou = inter / union if union > 0 else 0.0
        dcx = (px0 + px1) / 2 - (rx + rw / 2)
        dcy = (py0 + py1) / 2 - (ry + rh / 2)
        area = cv2.contourArea(cnt)
        # 槽中心落在暗区内 = 槽真的贴在盘上
        in_mask = sum(1 for _, c, _ in slot_uv
                      if 0 <= int(c[1]) < H and 0 <= int(c[0]) < W and mask[int(c[1]), int(c[0])] > 0)
        res.update({"tray_bbox_px": [int(rx), int(ry), int(rw), int(rh)],
                    "proj_bbox_px": [int(px0), int(py0), int(px1), int(py1)],
                    "iou": round(float(iou), 4),
                    "center_dx_px": round(float(dcx), 1), "center_dy_px": round(float(dcy), 1),
                    "tray_area_px": float(area),
                    "slots_center_in_tray": int(in_mask), "slots_total": len(slot_uv)})
        print("实测料盘 bbox=%s 面积=%.0fpx²" % ([int(rx), int(ry), int(rw), int(rh)], area))
        print("投影外包     =%s" % ([int(px0), int(py0), int(px1), int(py1)]))
        print("IoU=%.3f · 中心差 dx=%.1f dy=%.1f px" % (iou, dcx, dcy))
        print("槽中心落在料盘暗区内: %d/%d" % (in_mask, len(slot_uv)))
        # mask 级 IoU: 投影料盘多边形 vs 实测暗区(bbox IoU 会被旋转后的轴对齐包围盒放大而失真)
        inter = int(((m_in > 0) & (mask > 0)).sum()); union = int(((m_in > 0) | (mask > 0)).sum())
        res["mask_iou"] = round(inter / union, 4) if union else 0.0
        print("mask IoU(投影∩实测/并) = %.4f" % res["mask_iou"])

        # ── 场景料盘 vs 实测料盘: 反投到料盘口沿平面, 给 mm / 度 ──────────────
        # 料盘口沿 z = 壁顶 (XML: 壁 pos z=0.1201 + 半高 0.02)
        try:
            wall_z = max(g["pos"][2] + g["size"][2] for g in tray if g["name"].endswith(("_w0", "_w1", "_w2", "_w3")))
            rect = cv2.minAreaRect(cnt)
            box = cv2.boxPoints(rect)
            base_pts = []
            for u, v in box:
                p = so.px_to_base_ray(float(u), float(v), K, X, tcp7, wall_z)
                base_pts.append(p)
            base_pts = np.asarray(base_pts, float)
            if np.isfinite(base_pts).all():
                # 实测外框 (base, mm)
                mm = base_pts * 1000.0
                cen_meas = mm.mean(0)
                # 长边方向 = 边长较大的那条
                e0 = mm[1] - mm[0]; e1 = mm[2] - mm[1]
                if np.linalg.norm(e0) >= np.linalg.norm(e1):
                    yaw_meas = np.degrees(np.arctan2(e0[1], e0[0])); Lmaj, Lmin = np.linalg.norm(e0), np.linalg.norm(e1)
                else:
                    yaw_meas = np.degrees(np.arctan2(e1[1], e1[0])); Lmaj, Lmin = np.linalg.norm(e1), np.linalg.norm(e0)
                # 矩形 90° 等价: 归一到 (-45,45], 长宽随之对调(否则会报出"yaw 差 93°"的假结论)
                while yaw_meas > 45.0:
                    yaw_meas -= 90.0; Lmaj, Lmin = Lmin, Lmaj
                while yaw_meas <= -45.0:
                    yaw_meas += 90.0; Lmaj, Lmin = Lmin, Lmaj
                if Lmaj < Lmin:                 # 归一后保证 Lmaj ≥ Lmin (名字必须与数值一致)
                    Lmaj, Lmin = Lmin, Lmaj
                # 场景外框 (base, mm)
                bot = next(g for g in tray if g["name"].endswith("_bot"))
                ws = [g for g in tray if g["name"].endswith(("_w0", "_w1", "_w2", "_w3"))]
                qs = np.vstack([face_quad(g["pos"], g["size"], top=True, quat=g.get("quat")) for g in ws])
                x0, x1 = float(qs[:, 0].min()), float(qs[:, 0].max())
                y0, y1 = float(qs[:, 1].min()), float(qs[:, 1].max())
                cen_scene = np.array([(x0 + x1) / 2, (y0 + y1) / 2, wall_z]) * 1000.0
                d = cen_meas - cen_scene
                res.update({
                    "scene_tray_mm": {"center": [round(v, 1) for v in cen_scene], "size": [round(x1 - x0, 1), round(y1 - y0, 1)], "yaw_deg": 0.0},
                    "meas_tray_mm": {"center": [round(v, 1) for v in cen_meas], "size": [round(Lmaj, 1), round(Lmin, 1)], "yaw_deg": round(float(yaw_meas), 2), "plane_z": round(wall_z, 4)},
                    "d_center_mm": [round(float(v), 1) for v in d], "d_center_norm_mm": round(float(np.linalg.norm(d[:2])), 1),
                    "size_delta_pct": [round(100 * (Lmin - (x1 - x0) * 1000) / ((x1 - x0) * 1000), 1),
                                       round(100 * (Lmaj - (y1 - y0) * 1000) / ((y1 - y0) * 1000), 1)],
                })
                print("实测料盘(base,mm): 中心(%.1f,%.1f) 尺寸 %.1f×%.1f yaw %.2f°"
                      % (cen_meas[0], cen_meas[1], Lmaj, Lmin, yaw_meas))
                print("场景料盘(base,mm): 中心(%.1f,%.1f) 尺寸 %.1f×%.1f yaw 0.00°"
                      % (cen_scene[0], cen_scene[1], (x1 - x0) * 1000, (y1 - y0) * 1000))
                print("→ 中心差 Δ=(%.1f, %.1f) mm (|Δ|=%.1f) · 尺寸差 %.1f%%/%.1f%% · yaw 差 %.2f°"
                      % (d[0], d[1], np.linalg.norm(d[:2]), res["size_delta_pct"][0], res["size_delta_pct"][1], yaw_meas))
        except Exception as e:      # 反投/拟合失败要如实报, 不许静默
            res["base_compare_error"] = str(e)[:160]
            print("⚠️ 反投对比失败: %s" % str(e)[:120])
    else:
        print("未检出实测料盘暗区 (曝光/工件不在位?)")

    hdr = "AR上料盘→臂相机 | TCP(%.3f,%.3f,%.3f) | 帧内%.0f%% | %s" % (
        tcp7[0], tcp7[1], tcp7[2], 100 * inside,
        ("IoU %.2f 中心差(%.0f,%.0f)px" % (res.get("iou", 0), res.get("center_dx_px", 0), res.get("center_dy_px", 0)))
        if "iou" in res else "无实测对照")
    cv2.rectangle(vis, (0, 0), (W, 20), (25, 25, 25), -1)
    cv2.putText(vis, hdr, (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    outp = OUT_DIR / "arm_tray_sync.jpg"
    cv2.imwrite(str(outp), vis)
    (OUT_DIR / "arm_tray_sync.json").write_text(json.dumps(
        {"ts": time.strftime("%F %T"), "tcp": tcp7.tolist(), "handeye": {k: hc.get(k) for k in ("method", "closed_loop_std_mm", "n_poses")},
         "result": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("图: %s\nJSON: %s" % (outp, OUT_DIR / "arm_tray_sync.json"))

    if args.write_scene:
        if "meas_tray_mm" not in res:
            print("✗ 没有可用的实测位姿, 拒绝写场景")
            return 4
        mm, yaw = res["meas_tray_mm"], res["meas_tray_mm"]["yaw_deg"]
        c_meas = np.array(mm["center"], float) / 1000.0
        # 场景料盘中心 (按 4 壁外沿算, 与测量同口径)
        ws = [g for g in tray if g["name"].endswith(("_w0", "_w1", "_w2", "_w3"))]
        qs = np.vstack([face_quad(g["pos"], g["size"], top=True, quat=g.get("quat")) for g in ws])
        c0 = np.array([(qs[:, 0].min() + qs[:, 0].max()) / 2, (qs[:, 1].min() + qs[:, 1].max()) / 2])
        th = np.radians(float(yaw))
        R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        bak = XML.with_suffix(".xml.bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
        bak.write_bytes(XML.read_bytes())
        txt = XML.read_text(encoding="utf-8")
        moved = 0
        qw, qz = np.cos(th / 2.0), np.sin(th / 2.0)     # MuJoCo quat = (w x y z), 绕 z 转 yaw
        qstr = "%.6f 0.000000 0.000000 %.6f" % (qw, qz)
        for g in tray + slots:                      # 本体 + 槽族一起做刚体变换(保持内部关系)
            p2 = R @ (np.asarray(g["pos"][:2], float) - c0) + c_meas[:2]
            new_pos = "%.6f %.6f %.6f" % (p2[0], p2[1], g["pos"][2])
            tag_re = re.compile(r'<geom\s+name="%s"[^>]*?/>' % re.escape(g["name"]), re.S)
            m = tag_re.search(txt)
            if not m:
                continue
            tag = m.group(0)
            tag = re.sub(r'pos="[^"]+"', 'pos="%s"' % new_pos, tag, count=1)
            if 'quat="' in tag:
                tag = re.sub(r'quat="[^"]+"', 'quat="%s"' % qstr, tag, count=1)
            else:
                tag = tag.replace("/>", ' quat="%s"/>' % qstr)
            txt = txt[:m.start()] + tag + txt[m.end():]
            moved += 1
        XML.write_text(txt, encoding="utf-8")
        side = {"ts": time.strftime("%F %T"), "src": "sync_tray_ar --write-scene (臂相机实测反投)",
                "center_m": [round(float(v), 6) for v in c_meas[:2]], "yaw_deg": round(float(yaw), 3),
                "scene_center_before_m": [round(float(v), 6) for v in c0],
                "applied_geoms": moved, "backup": str(bak),
                "note": "尺寸未改: 短边吻合(+0.7%), 长边掩膜不可靠(+13%) ⇒ 只同步位姿"}
        (XML.parent / "tray_pose_measured.json").write_text(json.dumps(side, ensure_ascii=False, indent=1), encoding="utf-8")
        print("✅ 已同步场景料盘位姿: 中心 %.1f,%.1f mm · yaw %.2f° · 改动 %d 个 geom"
              % (c_meas[0] * 1000, c_meas[1] * 1000, yaw, moved))
        print("   备份 %s · 台账 %s" % (bak.name, "tray_pose_measured.json"))
        print("--- 回读校验(用新 XML 重投同一帧) ---")
        subprocess.run([sys.executable, __file__] + (["--frame", args.frame] if args.frame else []),
                       cwd=str(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
