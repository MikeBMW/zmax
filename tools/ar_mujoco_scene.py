#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎬 ar_mujoco_scene.py — AR 场景 → MuJoCo 建模 → 离屏渲染 → YOLO 感知

老倪 2026-10-28: 「要用AR场景建模, 用mujoco仿真引擎渲染, yolo感知」

## 为什么走这条路
D435 不在位、D405 固件死锁 ⇒ 真机画面这条路彻底断了, YOLO 没有输入、L4 只能吃
placeholder。改用**仿真渲染当相机**: 场景几何来自 AR 真源 (fence_store + 点位台账),
渲染出来的帧喂 YOLO ⇒ 感知链有真实输入, 且完全可复现。

## 几何真源 (不自己编坐标)
  · 工作台 / 料盘 / 孔位盒 / 夹具 ← fence_store 的箱体元素 (配置中心工程配置)
  · 关键点位 (金手指点1/2 · 安全点1 · 空间点1..8 · 准备点) ← zmax_data/ar_live/ar_aoi_live.json
  · 光模块外形 ← sim_scene_def 的 _TRAY_GOLD 常量口径 (40×16mm 长条)
  · 双臂 ← ar_cmd.json 的元任务里左臂摆盘 / 右臂插拔+AOI

## 渲染坑 (见技能 robot-sim-mujoco-rendering)
  ① **先放大离屏缓冲**再建 Renderer: m.vis.global_.offwidth/offheight = W,H
     否则 ValueError: Image width 960 > framebuffer width 480
  ② **不要用 env.render() 的机位** —— 相机在构造时锁死; 自建 MjvCamera
  ③ **elevation 要按遮挡算**: 斜视时深槽壁会把里面的件挡掉, 用近俯视 -89.5°
  ④ **可见性用消融法验**: 把目标件移出视野渲一帧, 与正常帧求差, 差值区 = 真实占位
     —— 不能只凭"我传了相机"就信拍到了

用法:
    python tools/ar_mujoco_scene.py --render              # 出 1 帧 + 存图
    python tools/ar_mujoco_scene.py --render --yolo       # 再加 YOLO 检测
    python tools/ar_mujoco_scene.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import sys

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
OUT = osp.join(ROOT, "zmax_data", "ar_mujoco")
W, H = 960, 720

# ── AR 真源读取 ─────────────────────────────────────────────
def read_fences():
    """配置中心工程配置的 3D 元素 (箱体=围栏, 直线=轨迹)。"""
    sys.path.insert(0, osp.join(ROOT, "tools"))
    try:
        import fence_store as FS
        return FS.listing().get("items") or []
    except Exception:                                                        # noqa: BLE001
        return []


def read_points():
    """点位台账 (基座系, 米)。"""
    p = osp.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
    if not osp.exists(p):
        return {}
    try:
        s = json.load(open(p, encoding="utf-8")).get("s") or {}
    except Exception:                                                        # noqa: BLE001
        return {}
    out = {}
    # 🔴 ar_aoi_live 的点位现在**只有 x 分量** (y/z 是 None), 卡"必须凑齐 xyz"会把
    #    整批点位全丢掉 (实测 0 个)。缺分量就跳过该点, 不静默丢整批, 也绝不拿 0 补。
    for name in ("金手指点1", "金手指点2", "安全点1", "准备点",
                 "空间点1", "空间点2", "空间点3", "空间点4",
                 "光模块插入点", "光模块插入口"):
        v = [s.get(name + "." + ax) for ax in "xyz"]
        if all(x is not None for x in v):
            out[name] = [float(x) for x in v]
    return out


# ── MuJoCo 场景 (XML 由真源拼出来) ──────────────────────────
def build_xml():
    """按 AR 真源生成 MuJoCo XML。

    几何**全部**来自 fence_store 的箱体元素 (配置中心工程配置里实测出来的工位):
      料盘 / 槽位 / 相机 / 横梁 / 检测设备 —— 51 个 box, 不是自己编的坐标。
    坐标: 直接 base 系 (米), 世界原点 = 机器人底座。
    """
    fences = read_fences()
    pts = read_points()
    all_boxes = [f for f in fences if f.get("type") == "box" and f.get("p1") and f.get("p2")]
    if not all_boxes:
        all_boxes = [{"name": "table", "p1": [0.30, -0.45, 0.0], "p2": [0.95, 0.35, 0.10]}]

    # 🔴 结构件不参与渲染: 「长方体-上横梁」实测 200×1600×18mm(1.6m 长), 是框架参照不是实体,
    #    按包围盒画成实心板 ⇒ 正俯视时把整张台面盖死(实测金色模块 0 像素、消融差 0)。
    #    结构件只用来定台面范围, 不进 worldbody。
    SKIP = ("横梁", "相机", "检测设备")
    boxes = [b for b in all_boxes if not any(k in str(b.get("name")) for k in SKIP)]
    if not boxes:
        boxes = all_boxes

    # 台面范围 = 所有 box(含结构件) 的 XY 包络 (再外扩 6cm), 台面顶 = 最低 box 底面
    xs = [v for b in all_boxes for v in (b["p1"][0], b["p2"][0])]
    ys = [v for b in all_boxes for v in (b["p1"][1], b["p2"][1])]
    zs = [v for b in all_boxes for v in (b["p1"][2], b["p2"][2])]
    tx0, tx1 = min(xs) - 0.06, max(xs) + 0.06
    ty0, ty1 = min(ys) - 0.06, max(ys) + 0.06
    tz = min(zs)

    def _rgba(nm):
        """按语义给颜色 —— 料盘黑、槽更暗、设备金属灰。"""
        n = str(nm)
        if "槽" in n:
            return "0.055 0.055 0.065 1"      # 槽内: 近黑 (深凹)
        if "料盘" in n or "盘" in n:
            return "0.10 0.10 0.11 1"        # 料盘本体: 黑塑料
        if "相机" in n or "横梁" in n or "设备" in n:
            return "0.30 0.32 0.36 1"        # 金属结构件
        return "0.20 0.21 0.24 1"

    geos = []
    cx, cy = (tx0 + tx1) / 2, (ty0 + ty1) / 2
    hx, hy = (tx1 - tx0) / 2, (ty1 - ty0) / 2
    geos.append('<geom name="table" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f 0.020" '
                'rgba="0.32 0.32 0.35 1"/>' % (cx, cy, tz - 0.008, hx, hy))

    # 51 个真实箱体逐个画出来
    slot_center = None
    for k, b in enumerate(boxes):
        p1, p2 = list(b["p1"]), list(b["p2"])
        bx = abs(p2[0] - p1[0]) / 2
        by = abs(p2[1] - p1[1]) / 2
        zlo, zhi = min(p1[2], p2[2]), max(p1[2], p2[2])
        bz = max(abs(zhi - zlo) / 2, 0.002)         # 纯平面 box 给 4mm 厚, 否则退化
        mcx, mcy, mcz = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (zlo + zhi) / 2
        if bx < 1e-4 or by < 1e-4:
            continue
        nm = str(b.get("name") or "box%d" % k)
        gname = "b%02d_%s" % (k, nm.replace(" ", "_").replace("(", "").replace(")", "")
                              .replace("🧰", ""))
        is_pan = ("料盘" in nm) or ("废料盘" in nm) or ("盘" in nm and "槽" not in nm)
        if is_pan and (zhi - zlo) > 0.02:
            # 🔴 料盘画成「薄底 + 四壁」, 不能画实心盒。
            #    实测: 🧰黑色料盘 z=100~140mm 的实心盒把槽(110~125)和坐在 130mm 的
            #    光模块整个包住 ⇒ 全场景金色像素 0、消融差 0 (拍了等于没拍)。
            wall = 0.006
            geos.append('<geom name="%s_bot" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f %.4f" '
                        'rgba="%s"/>' % (gname, mcx, mcy, zlo + wall / 2, bx, by, wall / 2, _rgba(nm)))
            for suf, px, py, sx, sy in (
                    ("w0", mcx, min(p1[1], p2[1]) + wall / 2, bx, wall / 2),
                    ("w1", mcx, max(p1[1], p2[1]) - wall / 2, bx, wall / 2),
                    ("w2", min(p1[0], p2[0]) + wall / 2, mcy, wall / 2, by),
                    ("w3", max(p1[0], p2[0]) - wall / 2, mcy, wall / 2, by)):
                geos.append('<geom name="%s_%s" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f %.4f" '
                            'rgba="%s"/>' % (gname, suf, px, py, (zlo + zhi) / 2, sx, sy,
                                             (zhi - zlo) / 2, _rgba(nm)))
        else:
            geos.append('<geom name="%s" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f %.4f" '
                        'rgba="%s"/>' % (gname, mcx, mcy, mcz, bx, by, bz, _rgba(nm)))
        if slot_center is None and nm.startswith("槽"):
            # 坐在**槽顶面之上** (半高 4mm + 1mm 余量)
            slot_center = [mcx, mcy, zhi + 0.005]

    # 光模块 (金色 40×16mm 长条) —— 放进真实槽1; 没有槽就放料盘中心
    if slot_center:
        gx, gy, gz = slot_center
    elif pts.get("光模块插入口"):
        gx, gy, gz = pts["光模块插入口"]
    else:
        gx, gy, gz = cx, cy, tz + 0.02
    geos.append('<geom name="gold_module" type="box" pos="%.4f %.4f %.4f" size="0.020 0.008 0.004" '
                'rgba="0.94 0.76 0.22 1"/>' % (gx, gy, gz))

    # 双臂 (简化: 底座+上臂+前臂, 从台面后方立柱位置伸出)
    for side, ox in (("L", -0.13), ("R", +0.13)):
        bx0 = cx + ox
        geos.append('<geom name="arm%s_base" type="cylinder" pos="%.4f %.4f %.4f" '
                    'size="0.038 0.10" rgba="0.35 0.37 0.42 1"/>'
                    % (side, bx0, ty0 - 0.09, tz + 0.10))
        geos.append('<geom name="arm%s_up" type="capsule" fromto="%.4f %.4f %.4f %.4f %.4f %.4f" '
                    'size="0.026" rgba="0.42 0.45 0.50 1"/>'
                    % (side, bx0, ty0 - 0.09, tz + 0.20, bx0 + (0.05 if side == "L" else -0.05),
                       ty0 + 0.14, tz + 0.36))
        geos.append('<geom name="arm%s_fore" type="capsule" fromto="%.4f %.4f %.4f %.4f %.4f %.4f" '
                    'size="0.020" rgba="0.50 0.53 0.58 1"/>'
                    % (side, bx0 + (0.05 if side == "L" else -0.05), ty0 + 0.14, tz + 0.36,
                       cx + (ox * 0.5), cy, tz + 0.17))

    return ("""<mujoco model="zmax_ar_station">
  <option gravity="0 0 -9.81" integrator="Euler" timestep="0.002"/>
  <visual>
    <global offwidth="%d" offheight="%d"/>
    <quality shadowsize="4096"/>
  </visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.24 0.25 0.28" rgb2="0.17 0.18 0.21"
             width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="10 10"/>
  </asset>
  <worldbody>
    <light pos="%.4f %.4f %.4f" dir="0 0 -1" diffuse="0.9 0.9 0.95" specular="0.25 0.25 0.25"/>
    <light pos="%.4f %.4f %.4f" dir="0.3 0.7 -1" diffuse="0.4 0.4 0.45"/>
    <geom name="floor" type="plane" pos="0 0 0" size="3 3 0.05" material="grid"/>
%s
  </worldbody>
</mujoco>
""" % (W, H, cx, cy, tz + 1.4, cx - 0.5, cy - 0.6, tz + 1.1, "\n    ".join(geos)))


def make_renderer(model):
    """近俯视渲染器。

    🔴 必须**先放大离屏缓冲**再建 Renderer —— metaworld/mujoco 默认 offwidth=480,
       直接开 960×720 会 ValueError: Image width 960 > framebuffer width 480。
    🔴 elevation 用 -89.5° 近正俯视: 斜视时深槽壁会把里面的件挡掉(实测件像素差 20 倍)。
    """
    import mujoco
    model.vis.global_.offwidth = W
    model.vis.global_.offheight = H
    ren = mujoco.Renderer(model, height=H, width=W)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    # 机位对准料盘/槽位区: 从 fence_store 的箱体包络中心取, 不依赖点位台账
    # 机位对准**料盘**中心 (不是全工位包络): 结构件横梁 1.6m 长会把画面拉散
    pans = [f for f in read_fences()
            if f.get("type") == "box" and f.get("p1")
            and ("料盘" in str(f.get("name")) or "盘" in str(f.get("name")))]
    use = pans if pans else [f for f in read_fences() if f.get("type") == "box" and f.get("p1")]
    if use:
        xs = [v for b in use for v in (b["p1"][0], b["p2"][0])]
        ys = [v for b in use for v in (b["p1"][1], b["p2"][1])]
        zs = [v for b in use for v in (b["p1"][2], b["p2"][2])]
        ctr = np.array([(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                        max(zs) + 0.02])
    else:
        ctr = np.array([0.52, 0.30, 0.16])
    cam.lookat[:] = ctr
    cam.distance = 0.95
    cam.azimuth = 90.0
    cam.elevation = -78.0          # 斜俯视: 既看得见台面布局, 也不至于被臂全挡
    return ren, cam


def render_frame(with_yolo=False, tag="scene"):
    """渲一帧 → (jpg_path, meta)。可选跑 YOLO。"""
    import mujoco
    os.makedirs(OUT, exist_ok=True)
    xml = build_xml()
    xmlp = osp.join(OUT, "ar_station.xml")
    with open(xmlp, "w", encoding="utf-8") as f:
        f.write(xml)
    model = mujoco.MjModel.from_xml_path(xmlp)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    ren, cam = make_renderer(model)
    ren.update_scene(data, camera=cam)
    img = ren.render()

    from PIL import Image
    jpg = osp.join(OUT, "render_%s.jpg" % tag)
    Image.fromarray(img).save(jpg, quality=92)

    meta = {"ok": True, "jpg": jpg, "w": int(img.shape[1]), "h": int(img.shape[0]),
            "n_geoms": int(model.ngeom), "xml": xmlp,
            "camera": {"lookat": [float(v) for v in cam.lookat], "distance": float(cam.distance),
                       "azimuth": float(cam.azimuth), "elevation": float(cam.elevation)},
            "src": "fence_store + ar_aoi_live 点位台账",
            "nonblack_px": int((img.reshape(-1, 3).max(axis=1) > 12).sum())}

    if with_yolo:
        meta["yolo"] = run_yolo(img, tag)
    with open(osp.join(OUT, "render_%s.json" % tag), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


def run_yolo(img, tag="scene"):
    """在渲染帧上跑在役 YOLO。

    ⚠️ 诚实口径: models/yolo_peg_live.pt 是在**腕相机 D405 视角**上训的,
       在别的视角/尺度的渲染图上很可能检不出 —— 检不出就如实报 0 框 + 原因,
       绝不拿"0 框"冒充"场景里没有件"。
    """
    out = {"ok": False, "boxes": [], "n": 0, "weights": "", "note": ""}
    wp = osp.join(ROOT, "models", "yolo_peg_live.pt")
    if not osp.exists(wp):
        out["note"] = "权重不存在: %s" % wp
        return out
    out["weights"] = osp.realpath(wp)
    try:
        from ultralytics import YOLO
        m = YOLO(wp)
        r = m.predict(img, conf=0.20, imgsz=640, verbose=False)
        names = getattr(r[0], "names", {}) if r else {}
        boxes = []
        if r and r[0].boxes is not None:
            for b in r[0].boxes:
                xyxy = [float(v) for v in b.xyxy[0].tolist()]
                boxes.append({"cls": str(names.get(int(b.cls[0]), int(b.cls[0]))),
                              "conf": round(float(b.conf[0]), 4), "xyxy": [round(v, 1) for v in xyxy]})
        out.update(ok=True, boxes=boxes, n=len(boxes))
        if not boxes:
            out["note"] = ("0 框 —— 在役权重是腕相机 D405 视角训的, 本渲染机位与之不同视角/尺度, "
                           "检不出属预期; 要在这条仿真链上检出需按本机位重训小头")
    except Exception as e:                                                   # noqa: BLE001
        out["note"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return out


# ═══════════ 自检 ═══════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("① 真源读取")
    fences = read_fences()
    pts = read_points()
    chk("fence_store 有元素", len(fences) > 0, "%d 个" % len(fences))
    # 台账当前 y/z 分量是 None (ar_aoi_bus 只发了 x) ⇒ 凑不齐 xyz 的点一律不采用才是对的,
    # 所以这里只验"文件可读 + 确实有信号", 完整点位数单独打印, 不当失败。
    _ap = osp.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
    _ok = osp.exists(_ap)
    _nsig = 0
    if _ok:
        try:
            _nsig = len((json.load(open(_ap, encoding="utf-8")).get("s") or {}))
        except Exception:                                                    # noqa: BLE001
            _ok = False
    chk("点位台账可读", _ok, "%d 个信号" % _nsig)
    print("     (凑齐 xyz 的点位 %d 个 —— 台账 y/z 为 None 时按规则不采用)" % len(pts))

    print("② XML 生成")
    xml = build_xml()
    chk("XML 可解析", "<mujoco" in xml and "</mujoco>" in xml)
    chk("含 offwidth=%d" % W, 'offwidth="%d"' % W in xml)
    chk("含台面 geom", 'name="table"' in xml)
    chk("含光模块", 'name="gold_module"' in xml)
    chk("含双臂", 'name="armL_base"' in xml and 'name="armR_base"' in xml)

    print("③ 真渲染")
    m = render_frame(with_yolo=False, tag="selftest")
    chk("渲出图", m["ok"] and osp.exists(m["jpg"]), m["jpg"])
    chk("分辨率 %dx%d" % (W, H), (m["w"], m["h"]) == (W, H), "%dx%d" % (m["w"], m["h"]))
    nb = m["nonblack_px"]
    tot = m["w"] * m["h"]
    chk("画面非黑 (非黑像素 > 40%%)", nb > tot * 0.40,
        "%.1f%% (%d/%d)" % (100.0 * nb / tot, nb, tot))
    chk("geom 数合理", m["n_geoms"] >= 8, "%d" % m["n_geoms"])

    print("④ 消融法验可见性 (不能凭'我传了相机'就信)")
    import mujoco
    model = mujoco.MjModel.from_xml_path(m["xml"])
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    ren, cam = make_renderer(model)
    ren.update_scene(data, camera=cam)
    a = ren.render().astype(int)
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "gold_module")
    chk("找得到 gold_module geom", gid >= 0, "id=%d" % gid)
    if gid >= 0:
        model.geom_pos[gid] = [0, 0, -5.0]     # 移到视野外
        mujoco.mj_forward(model, data)
        ren.update_scene(data, camera=cam)
        b = ren.render().astype(int)
        diff = np.abs(a - b).sum(axis=2) > 24
        chk("光模块在画面里占足够像素 (消融差)", int(diff.sum()) >= 150,
            "%d px 变化" % int(diff.sum()))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (AR 场景 → MuJoCo 建模 → 渲染)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--yolo", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.render or a.yolo:
        m = render_frame(with_yolo=a.yolo)
        print("渲染 → %s (%dx%d, %d geoms, 非黑 %.1f%%)"
              % (m["jpg"], m["w"], m["h"], m["n_geoms"],
                 100.0 * m["nonblack_px"] / (m["w"] * m["h"])))
        print("机位: lookat=%s dist=%.2f az=%.1f° el=%.1f°"
              % ([round(v, 3) for v in m["camera"]["lookat"]], m["camera"]["distance"],
                 m["camera"]["azimuth"], m["camera"]["elevation"]))
        if "yolo" in m:
            y = m["yolo"]
            print("YOLO: %s · %d 框 · %s" % ("ok" if y["ok"] else "fail", y["n"],
                                            y.get("note", "")[:90]))
            for b in y["boxes"][:6]:
                print("   %-8s conf=%.3f %s" % (b["cls"], b["conf"], b["xyxy"]))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
