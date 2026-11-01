#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""robot_deck_build.py — 机器人工程图 PPT：正面/侧面/轴向三视图 + 外形尺寸 + 坐标系 + 结构参数。

为什么自己用 PIL 画尺寸线：render_robot_views.draw_dims 走 matplotlib 重画一遍，
坐标系叠加层的投影就对不上了。这里统一用 render() 返回的 meta 做投影，
尺寸线、比例尺、坐标系全部画在同一张图上。

口径（都与工程一致）：
  · 外形 = 真机 URDF 厂家 STL，作业姿态（法兰反解到 1 号槽上方，误差 0）
  · 坐标系 = tcp-ar.html:2444，原点右臂底座，红X/绿Y/蓝Z，base 轴长 160mm（图上放大到 240mm 好读）
  · 结构参数 = 直接读 URDF 的 joint origin/axis/limit/effort 与 link mass
"""
from __future__ import annotations
import os, sys, json, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import SPEC, LINK_ORDER, fk, load_meshes, world_tris, render, rot_cam

URDF = "/home/ubuntu/zmax/zmax_data/rokae_sdk/urdf/xms5_r800_w4g3b4c.urdf"
AX_C = {"x": (255, 93, 93), "y": (93, 255, 143), "z": (93, 184, 255)}
INK = (32, 38, 48)
DIMC = (200, 60, 60)
GREY = (120, 130, 145)


def _font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                pass
    return ImageFont.load_default()


def annotate(img_u8, R, meta, verts_world, h_lab=None, v_lab=None,
             axes_origin=(0, 0, 0), axes_len=0.24, note=None):
    """在渲染图上画：外形尺寸线 + 100mm 比例尺 + base 世界坐标系。"""
    lo = np.asarray(meta["lo"], float); scale = float(meta["scale"])
    off = np.asarray(meta["off"], float)

    def proj(p):
        v = np.asarray(p, float) @ R.T
        return (v[:2] - lo) * scale + off

    im = Image.fromarray(img_u8).convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    f_t = _font(30); f_s = _font(24)

    px = np.array([proj(p) for p in verts_world])
    x0, x1 = px[:, 0].min(), px[:, 0].max()
    y0, y1 = px[:, 1].min(), px[:, 1].max()
    span_mm_x = (x1 - x0) / scale * 1000.0
    span_mm_y = (y1 - y0) / scale * 1000.0

    # ── 横向尺寸线（顶部） ──
    if h_lab:
        yy = max(46.0, y0 - 58)
        d.line([(x0, yy), (x1, yy)], fill=DIMC, width=3)
        for xx in (x0, x1):
            d.line([(xx, yy - 13), (xx, yy + 13)], fill=DIMC, width=3)
            d.line([(xx, yy), (xx, y0 - 6)], fill=(*DIMC, 90), width=1)
        txt = "%s %.0f mm" % (h_lab, span_mm_x)
        tw = d.textlength(txt, font=f_t)
        d.rectangle([(x0 + x1) / 2 - tw / 2 - 10, yy - 40, (x0 + x1) / 2 + tw / 2 + 10, yy - 4],
                    fill=(255, 255, 255))
        d.text(((x0 + x1) / 2 - tw / 2, yy - 38), txt, font=f_t, fill=DIMC)

    # ── 纵向尺寸线（右侧） ──
    if v_lab:
        xx = min(W - 40.0, x1 + 62)
        d.line([(xx, y0), (xx, y1)], fill=DIMC, width=3)
        for yy in (y0, y1):
            d.line([(xx - 13, yy), (xx + 13, yy)], fill=DIMC, width=3)
            d.line([(x1 + 6, yy), (xx, yy)], fill=(*DIMC, 90), width=1)
        txt = "%s %.0f mm" % (v_lab, span_mm_y)
        tw = d.textlength(txt, font=f_t)
        d.text((max(8, xx - tw - 14), (y0 + y1) / 2 - 16), txt, font=f_t, fill=DIMC)

    # ── 100mm 比例尺 ──
    bar = 0.1 * scale
    bx, by = 34, H - 44
    d.line([(bx, by), (bx + bar, by)], fill=(180, 140, 40), width=8)
    d.text((bx, by - 34), "100 mm", font=f_s, fill=(180, 140, 40))

    # ── base 世界坐标系（叠最上层，口径同 AR 场景） ──
    o = proj(axes_origin)
    for k, dv in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        t = proj(np.asarray(axes_origin, float) + np.array(dv, float) * axes_len)
        d.line([tuple(o), tuple(t)], fill=AX_C[k], width=7)
        d.rectangle([t[0] - 8, t[1] - 8, t[0] + 8, t[1] + 8], fill=AX_C[k])
        d.text((t[0] + 13, t[1] - 13), k.upper(), font=f_t, fill=AX_C[k])
    d.ellipse([o[0] - 9, o[1] - 9, o[0] + 9, o[1] + 9], fill=(230, 237, 243), outline=(17, 22, 28), width=2)
    d.text((o[0] + 14, o[1] + 8), "base（右臂底座）", font=f_s, fill=(40, 50, 62))

    if note:
        d.text((26, 18), note, font=f_s, fill=GREY)
    return im


def read_urdf_params(path=URDF):
    import xml.etree.ElementTree as ET
    r = ET.parse(path).getroot()
    joints, mass = [], {}
    for j in r.iter("joint"):
        if j.get("type") != "revolute":
            continue
        o = j.find("origin"); a = j.find("axis"); l = j.find("limit")
        xyz = [float(v) for v in (o.get("xyz", "0 0 0").split() if o is not None else [0, 0, 0])]
        ax = [float(v) for v in (a.get("xyz", "0 0 1").split() if a is not None else [0, 0, 1])]
        joints.append(dict(name=j.get("name").replace("XMS5-R800-W4G3B4C_", ""), xyz=xyz, axis=ax,
                           lo=float(l.get("lower")), hi=float(l.get("upper")),
                           vel=float(l.get("velocity")), eff=float(l.get("effort"))))
    for lk in r.iter("link"):
        i = lk.find("inertial")
        if i is not None:
            mass[lk.get("name").replace("XMS5-R800-W4G3B4C_", "")] = float(i.find("mass").get("value"))
    return joints, mass


def build_ppt(imgs, meta_all, out):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

    D = RGBColor(0x22, 0x26, 0x2E); M = RGBColor(0x6B, 0x72, 0x80)
    ACC = RGBColor(0x1E, 0x6F, 0xD9); HD = RGBColor(0x2B, 0x34, 0x40)
    prs = Presentation()
    prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    def tb(s, x, y, w, h, text, size=18, bold=False, color=D, align=PP_ALIGN.LEFT):
        box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame; tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.TOP
        for i, ln in enumerate(text.split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            r = p.add_run(); r.text = ln
            r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
            r.font.name = "微软雅黑"
        return box

    # ── 第 1 页 封面 ──
    s = prs.slides.add_slide(blank)
    s.shapes.add_picture(imgs["iso"], Inches(4.30), Inches(0.72), height=Inches(6.05))
    bar = s.shapes.add_shape(1, Inches(0.85), Inches(2.35), Inches(0.055), Inches(1.95))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACC; bar.line.fill.background(); bar.shadow.inherit = False
    tb(s, 1.08, 2.20, 3.20, 2.30,
       "六轴工业机械臂\nXMS5-R800\n作业姿态", size=34, bold=True, color=D)
    tb(s, 1.10, 4.60, 3.10, 1.2,
       "模型：厂家 URDF + STL\n外形：%.0f × %.0f × %.0f mm" % tuple(meta_all["dims_mm"][:3]),
       size=15, color=M)

    # ── 第 2 页 正面 / 侧面 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.34, 6.0, 0.5, "正面图 · 侧面图", size=26, bold=True, color=D)
    s.shapes.add_picture(imgs["front"], Inches(0.45), Inches(1.00), height=Inches(4.55))
    s.shapes.add_picture(imgs["side"], Inches(6.85), Inches(1.00), height=Inches(4.55))
    tb(s, 0.55, 5.75, 6.1, 0.5, "正面（沿 −X 看）：总宽 %.0f mm · 总高 %.0f mm"
       % (meta_all["dims_mm"][1], meta_all["dims_mm"][2]), size=14, color=M)
    tb(s, 6.95, 5.75, 6.1, 0.5, "侧面（沿 −Y 看）：总长 %.0f mm · 总高 %.0f mm"
       % (meta_all["dims_mm"][0], meta_all["dims_mm"][2]), size=14, color=M)
    tb(s, 0.55, 6.35, 12.2, 0.8,
       "坐标系：原点 = 右臂底座 = 两臂安装面 = 桌面顶（z=0）· 红X / 绿Y / 蓝Z · "
       "地面 z = −750mm（箱体本体 680 + 轮 70）", size=13, color=HD)

    # ── 第 3 页 轴向 / 立体 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.34, 8.0, 0.5, "轴向图（俯视）· 立体图", size=26, bold=True, color=D)
    s.shapes.add_picture(imgs["top"], Inches(0.45), Inches(1.00), height=Inches(4.55))
    s.shapes.add_picture(imgs["iso2"], Inches(6.85), Inches(1.00), height=Inches(4.55))
    tb(s, 0.55, 5.75, 6.1, 0.5, "轴向（沿 −Z 俯视）：总宽 %.0f mm · 总长 %.0f mm"
       % (meta_all["dims_mm"][1], meta_all["dims_mm"][0]), size=14, color=M)
    tb(s, 6.95, 5.75, 6.1, 0.5, "立体：作业姿态，法兰正对 1 号槽（反解误差 %.1f mm）"
       % meta_all["err_mm"], size=14, color=M)
    tb(s, 0.55, 6.35, 12.2, 0.8,
       "外形包络以作业姿态实测：轴向投影 %d × %d mm。轴长 base 系 160mm（图上放大到 240mm 便于识读）"
       % (round(meta_all["dims_mm"][1]), round(meta_all["dims_mm"][0])), size=13, color=HD)

    # ── 第 4 页 主要结构参数 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.34, 9.0, 0.5, "主要结构参数", size=26, bold=True, color=D)
    tb(s, 0.55, 0.90, 12.2, 0.4,
       "来源：厂家 URDF（joint origin / axis / limit / effort）与 link 惯量质量，未手填",
       size=13, color=M)

    rows = [("轴", "关节原点 (mm)", "轴向", "关节范围", "额定力矩")]
    for j in meta_all["joints"]:
        nm = j["name"].replace("joint_", "J")
        lo_d, hi_d = math.degrees(j["lo"]), math.degrees(j["hi"])
        rng = ("±%.0f°" % hi_d) if abs(lo_d + hi_d) < 1 else ("%.0f° ~ %.0f°" % (lo_d, hi_d))
        rows.append((nm, "(%.1f, %.1f, %.1f)" % tuple(j["xyz"]),
                     "(%g, %g, %g)" % tuple(j["axis"]), rng, "%.0f N·m" % j["eff"]))
    tw = [Inches(1.5), Inches(3.1), Inches(2.4), Inches(2.5), Inches(2.0)]
    tbl = s.shapes.add_table(len(rows), 5, Inches(0.55), Inches(1.45), sum(tw, Inches(0)),
                             Inches(0.42) * len(rows)).table
    for i, w in enumerate(tw):
        tbl.columns[i].width = w
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = tbl.cell(ri, ci); c.text = str(val)
            for p in c.text_frame.paragraphs:
                p.alignment = PP_ALIGN.LEFT
                for r in p.runs:
                    r.font.size = Pt(13 if ri else 13)
                    r.font.bold = (ri == 0)
                    r.font.color.rgb = D if ri else RGBColor(0x33, 0x3A, 0x44)
                    r.font.name = "微软雅黑"

    mass = meta_all["mass"]
    tb(s, 0.55, 5.05, 6.3, 2.1,
       "本体质量（URDF 惯量）\n" +
       "  ".join("%s %.3f kg" % (k.replace("link", "L"), v) for k, v in mass.items()) +
       "\n合计 %.3f kg" % meta_all["total_mass_kg"], size=13, color=HD)
    tb(s, 7.05, 5.05, 5.7, 2.1,
       "安装与行程\n· 安装面 = z 0，基座回转中心高 328 mm\n"
       "· 大臂 400 mm（J2→J3），小臂 400 mm（J3→J4）\n"
       "· 腕偏置 136 mm（J4→J5），法兰 103.5 mm（J5→J6）\n"
       "· 法兰→模块头 tool1（−15.9, 18.3, 258.7）mm\n"
       "· 各轴最大角速度 180 °/s", size=13, color=HD)

    prs.save(out)
    print("saved", out, os.path.getsize(out), "bytes", len(prs.slides.__iter__.__self__._sldIdLst), "slides")


def main():
    outdir = "/tmp/robot3v"
    for i, a in enumerate(sys.argv):
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    os.makedirs(outdir, exist_ok=True)

    spec = json.load(open(SPEC))
    meshes = load_meshes()
    from render_ar_work import solve_to_point
    q, err = solve_to_point(spec, [0.4898, 0.4987, 0.1175 + 0.120])
    print("作业姿态 q =", [round(float(v), 3) for v in q], "TCP 误差 %.1f mm" % (err * 1000))

    T = fk(spec, q)
    tris = world_tris(T, meshes)
    verts = tris.reshape(-1, 3)
    dims = (verts.max(0) - verts.min(0)) * 1000.0
    print("外形包围盒 mm X %.0f Y %.0f Z %.0f" % tuple(dims))

    views = {"front": (0, 0, "总宽(左右)", "总高"),
             "side": (90, 0, "总长(前后)", "总高"),
             "top": (0, 89.9, "总宽(左右)", "总长(前后)"),
             "iso": (38, 22, None, None),
             "iso2": (146, 26, None, None)}
    imgs = {}
    for nm, (az, el, hl, vl) in views.items():
        R = rot_cam(az, el)
        img, meta = render(tris, R, size=(1700, 1400), ss=2)
        a8 = (np.clip(np.asarray(img), 0, 1) ** 0.85 * 255).astype(np.uint8)
        note = "真机 XMS5-R800-W4G3B4C · 厂家 URDF/STL · 作业姿态"
        im = annotate(a8, R, meta, verts, hl, vl, note=note)
        p = os.path.join(outdir, f"deck_{nm}.png")
        im.save(p)
        imgs[nm] = p
        print("saved", p, im.size)

    joints, mass = read_urdf_params()
    meta_all = dict(q=[round(float(v), 3) for v in q], err_mm=round(float(err) * 1000, 2),
                    dims_mm=[round(float(v), 1) for v in dims],
                    joints=joints, mass=mass, total_mass_kg=round(sum(mass.values()), 3))
    json.dump(meta_all, open(os.path.join(outdir, "meta_deck.json"), "w"), ensure_ascii=False, indent=1)

    out = "/home/ubuntu/zmax/zmax_data/tmp/legacy_decks/机器人三视图与技术参数.pptx"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    build_ppt(imgs, meta_all, out)


if __name__ == "__main__":
    main()
