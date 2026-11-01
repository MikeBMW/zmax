#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""machine_deck_build.py — 整机工程图 PPT（不是光手臂）。

第 1 页沿用 机器人作业姿态_工位版 的封面（老倪：刚才第一页找回来），
后面接整机的 正面 / 侧面 / 轴向 三视图，标外形尺寸与 base 世界坐标系，
最后一页给整机构成与主要结构参数。

几何口径（全部来自 web 源码常量或 AR 场景实测，不自造）：
  · tcp-ar.html: TAB{x0:.35,x1:.95,cy:.25,w:1.6,t:.03,leg:.045,h:.75}
                CHS{L:.6,W:.8,H:.75,HB:.68,cy:.25,wr:.075}
                TCAM{y:.25,r:.07,tilt:35}  LARM{off:[0,.5,0]}
  · ar_station.xml: 料盘/槽位实测（槽中心 z=0.1175）
  · URDF: 机器人本体与法兰
"""
from __future__ import annotations
import os, sys, json, math
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import SPEC, load_meshes, world_tris, render, rot_cam
from render_ar_work import load_station, solve_to_point
from render_zmax_workcell import build_workcell, robot_at, web_view_rot, LARM_OFF
from robot_deck_build import annotate, read_urdf_params

DELIV = "/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables"
OUT_PPT = os.path.join(DELIV, "机器人整机三视图与技术参数_5.50.C_20261101.pptx")
FIGDIR = "/home/ubuntu/zmax/docs/6-开阳-工程落地/figs_ar_robot"


def assemble(spec, meshes):
    """整机 = 工位(箱体/轮/桌/相机) + 料盘槽位 + 右臂 + 左臂。"""
    # 对称取件，两槽关于中央相机 y=0.25 严格镜像，双臂各自背离相机
    target = [0.493, -0.218, 0.1175 + 0.120]
    q, err = solve_to_point(spec, target)
    qL, errL = solve_to_point(spec, [0.493, 0.727 - LARM_OFF[1], 0.1175 + 0.120])
    parts = build_workcell()
    st_t, st_c = load_station(skip_arms=True, skip_floor=True, skip_table=True)
    parts.append((st_t, st_c))
    parts.append(robot_at(meshes, q, spec, 0.0))
    parts.append(robot_at(meshes, qL, spec, LARM_OFF[1], color_shift=3))
    tris = np.concatenate([p[0] for p in parts], axis=0)
    cols = np.concatenate([p[1] for p in parts], axis=0)
    return tris, cols, dict(q=q, err=err, qL=qL, errL=errL)


def build_deck(imgs, mi, out):
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
        tf = box.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.TOP
        for i, ln in enumerate(str(text).split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            r = p.add_run(); r.text = ln
            r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
            r.font.name = "微软雅黑"

    # ── 第 1 页：沿用刚才那张封面 ──
    s = prs.slides.add_slide(blank)
    s.shapes.add_picture(imgs["cover"], Inches(4.30), Inches(0.72), height=Inches(6.05))
    bar = s.shapes.add_shape(1, Inches(0.85), Inches(2.05), Inches(0.055), Inches(2.3))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACC; bar.line.fill.background(); bar.shadow.inherit = False
    tb(s, 1.08, 1.90, 3.25, 2.5, "光模块上下料\n双臂工作站\nXMS5-R800 ×2", size=32, bold=True, color=D)
    tb(s, 1.10, 4.55, 3.15, 1.4,
       "作业包络（含双臂）\n%.0f × %.0f × %.0f mm\n台面 1600×600×30｜台面高 750"
       % tuple(mi["dims_mm"][:3]), size=15, color=M)

    # ── 第 2 页：正面 / 侧面 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.30, 7.0, 0.5, "整机正面图 · 侧面图", size=26, bold=True, color=D)
    s.shapes.add_picture(imgs["front"], Inches(0.35), Inches(0.95), height=Inches(4.45))
    s.shapes.add_picture(imgs["side"], Inches(6.75), Inches(0.95), height=Inches(4.45))
    tb(s, 0.50, 5.55, 6.2, 0.4, "正面（沿 −X 看）：总宽 %.0f mm · 总高 %.0f mm"
       % (mi["dims_mm"][1], mi["dims_mm"][2]), size=14, color=M)
    tb(s, 6.90, 5.55, 6.2, 0.4, "侧面（沿 −Y 看）：总长 %.0f mm · 总高 %.0f mm"
       % (mi["dims_mm"][0], mi["dims_mm"][2]), size=14, color=M)
    tb(s, 0.50, 6.00, 12.4, 1.2,
       "世界坐标系 base：原点 = 右臂底座 = 两臂安装面 = 桌面顶（z=0）｜红X / 绿Y / 蓝Z（轴长 160 mm）\n"
       "地面 z = −750 mm（箱体本体 680 + 轮 70）；左臂原心 y = +500 mm，右臂 y = 0",
       size=13, color=HD)

    # ── 第 3 页：轴向 / 立体 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.30, 8.0, 0.5, "整机轴向图（俯视）· 立体图", size=26, bold=True, color=D)
    s.shapes.add_picture(imgs["top"], Inches(0.35), Inches(0.95), height=Inches(4.45))
    s.shapes.add_picture(imgs["iso"], Inches(6.75), Inches(0.95), height=Inches(4.45))
    tb(s, 0.50, 5.55, 6.2, 0.4, "轴向（沿 −Z 俯视）：总宽 %.0f mm · 总长 %.0f mm"
       % (mi["dims_mm"][1], mi["dims_mm"][0]), size=14, color=M)
    tb(s, 6.90, 5.55, 6.2, 0.4, "立体：作业姿态，两臂各对镜像槽位、背离中央相机（误差 %0.1f / %0.1f mm）"
       % (mi["err_mm"], mi["errL_mm"]), size=13, color=M)
    tb(s, 0.50, 6.05, 12.4, 1.2,
       "两臂机位间距 500 mm｜料盘 3 组各 14 槽 + 废料盘｜中央顶视相机 r=70 mm 俯角 35°｜"
       "台面 1600 × 600 × 30 mm，4 条 45×45 铝型材腿｜箱体 600 × 800 × 750 mm，4 轮 Ø150",
       size=13, color=HD)

    # ── 第 4 页：整机构成 + 关键尺寸 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.30, 9.0, 0.5, "整机构成与关键尺寸", size=26, bold=True, color=D)
    rows = [("部件", "规格（mm）", "说明"),
            ("底盘箱体", "600 × 800 × 750", "本体 680 + 轮 70；4 轮 Ø150"),
            ("实验桌", "1600 × 600 × 30", "台面高 750；4 条 45×45 铝型材腿"),
            ("机械臂 ×2", "XMS5-R800", "右臂 y=0，左臂 y=+500；本体 13.622 kg/台"),
            ("料盘", "3 × 14 槽 + 废料盘", "槽中心 z = 117.5；槽口 36 × 42"),
            ("中央相机", "r 70，俯角 35°", "立柱高 328（= J1 高），FOV 87°×58°"),
            ("作业包络", "%.0f × %.0f × %.0f" % tuple(mi["dims_mm"][:3]), "作业姿态实测，含双臂伸展与举升")]
    tw = [Inches(2.4), Inches(3.6), Inches(6.3)]
    tbl = s.shapes.add_table(len(rows), 3, Inches(0.55), Inches(1.05), sum(tw, Inches(0)),
                             Inches(0.46) * len(rows)).table
    for i, w in enumerate(tw):
        tbl.columns[i].width = w
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = tbl.cell(ri, ci); c.text = str(val)
            for p in c.text_frame.paragraphs:
                p.alignment = PP_ALIGN.LEFT
                for r in p.runs:
                    r.font.size = Pt(13); r.font.bold = (ri == 0)
                    r.font.color.rgb = D if ri else RGBColor(0x33, 0x3A, 0x44)
                    r.font.name = "微软雅黑"
    tb(s, 0.55, 5.35, 12.4, 1.8,
       "作业姿态（由示教反解，非手摆）：右臂法兰 (%.1f, %.1f, %.1f) mm 对准 1 号槽，"
       "左臂对准左盘 1 号槽，TCP 误差 %.2f / %.2f mm\n"
       "关节角 右臂 %s｜左臂 %s"
       % (493.0, -218.0, 237.5, mi["err_mm"], mi["errL_mm"],
          [round(float(v), 3) for v in mi["q"]], [round(float(v), 3) for v in mi["qL"]]),
       size=12, color=HD)

    # ── 第 5 页：机械臂主要结构参数 ──
    s = prs.slides.add_slide(blank)
    tb(s, 0.55, 0.30, 9.0, 0.5, "机械臂主要结构参数", size=26, bold=True, color=D)
    tb(s, 0.55, 0.86, 12.2, 0.4, "来源：厂家 URDF（joint origin / axis / limit / effort）与 link 惯量质量，未手填",
       size=13, color=M)
    rows = [("轴", "关节原点 (mm)", "轴向", "行程", "额定力矩")]
    for j in mi["joints"]:
        lo_d, hi_d = math.degrees(j["lo"]), math.degrees(j["hi"])
        rng = ("±%.0f°" % hi_d) if abs(lo_d + hi_d) < 1 else ("%.0f° ~ +%.0f°" % (lo_d, hi_d))
        rows.append((j["name"].replace("joint_", "J"), "(%.1f, %.1f, %.1f)" % tuple(j["xyz"]),
                     "(%g, %g, %g)" % tuple(j["axis"]), rng, "%.0f N·m" % j["eff"]))
    tw = [Inches(1.4), Inches(3.1), Inches(2.3), Inches(2.6), Inches(2.0)]
    tbl = s.shapes.add_table(len(rows), 5, Inches(0.55), Inches(1.40), sum(tw, Inches(0)),
                             Inches(0.40) * len(rows)).table
    for i, w in enumerate(tw):
        tbl.columns[i].width = w
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = tbl.cell(ri, ci); c.text = str(val)
            for p in c.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(13); r.font.bold = (ri == 0)
                    r.font.color.rgb = D if ri else RGBColor(0x33, 0x3A, 0x44)
                    r.font.name = "微软雅黑"
    mass = mi["mass"]
    tb(s, 0.55, 4.85, 6.3, 2.2,
       "本体质量（URDF 惯量）\n" + "  ".join("%s %.3f kg" % (k.replace("link", "L"), v) for k, v in mass.items())
       + "\n合计 %.3f kg／台（双臂 %.3f kg）" % (mi["total_mass_kg"], mi["total_mass_kg"] * 2),
       size=13, color=HD)
    tb(s, 7.05, 4.85, 5.7, 2.2,
       "安装与行程\n· 安装面 = z 0，基座回转中心高 328 mm\n"
       "· 大臂 400 mm（J2→J3），小臂 400 mm（J3→J4）\n"
       "· 腕偏置 136 mm（J4→J5），法兰 103.5 mm（J5→J6）\n"
       "· 法兰→模块头 tool1（−15.9, 18.3, 258.7）mm\n· 各轴最大角速度 180 °/s",
       size=13, color=HD)

    prs.save(out)
    print("saved", out, os.path.getsize(out), "bytes", len(prs.slides._sldIdLst), "slides")


def main():
    outdir = "/tmp/machine3v"
    for i, a in enumerate(sys.argv):
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    os.makedirs(outdir, exist_ok=True)

    spec = json.load(open(SPEC))
    meshes = load_meshes()
    tris, cols, pose = assemble(spec, meshes)
    print("整机三角形 %d  右臂误差 %.1f mm  左臂误差 %.1f mm"
          % (len(tris), pose["err"] * 1000, pose["errL"] * 1000))

    verts = tris.reshape(-1, 3)
    dims = (verts.max(0) - verts.min(0)) * 1000.0
    print("整机外形 mm  X %.0f  Y %.0f  Z %.0f" % tuple(dims))

    views = {"front": (0, 0, "总宽(左右)", "总高"),
             "side": (90, 0, "总长(前后)", "总高"),
             "top": (0, 89.9, "总宽(左右)", "总长(前后)")}
    imgs = {}
    reuse = os.path.exists(os.path.join(outdir, "m_front.png")) and os.environ.get("REUSE") == "1"
    for nm, (az, el, hl, vl) in views.items():
        if reuse:
            imgs[nm] = os.path.join(outdir, f"m_{nm}.png"); continue
        R = rot_cam(az, el)
        img, meta = render(tris, R, size=(1700, 1500), ss=2, bg=1.0, colors=cols)
        a8 = (np.clip(np.asarray(img), 0, 1) ** 0.78 * 255).astype(np.uint8)
        im = annotate(a8, R, meta, verts, hl, vl,
                      note="XMS5-R800 双臂工作站整机 · 作业姿态 · 几何按 tcp-ar.html 常量与 AR 场景")
        p = os.path.join(outdir, f"m_{nm}.png")
        im.save(p); imgs[nm] = p
        print("saved", p, im.size)

    if reuse:
        imgs["iso"] = os.path.join(outdir, "m_iso.png")
    else:
        R = web_view_rot()
        img, meta = render(tris, R, size=(1700, 1500), ss=2, bg=1.0, colors=cols)
        a8 = (np.clip(np.asarray(img), 0, 1) ** 0.78 * 255).astype(np.uint8)
        im = annotate(a8, R, meta, verts, None, None, note="整机立体 · 同 AR 页机位")
        p = os.path.join(outdir, "m_iso.png"); im.save(p); imgs["iso"] = p
        print("saved", p, im.size)

    cover = "/tmp/zmax_cell/cell_high.png"
    if not os.path.exists(cover):
        cover = os.path.join(FIGDIR, "cell_high.png")
    imgs["cover"] = cover

    joints, mass = read_urdf_params()
    mi = dict(dims_mm=[round(float(v), 1) for v in dims],
              q=[round(float(v), 4) for v in pose["q"]],
              qL=[round(float(v), 4) for v in pose["qL"]],
              err_mm=round(pose["err"] * 1000, 2), errL_mm=round(pose["errL"] * 1000, 2),
              joints=joints, mass=mass, total_mass_kg=round(sum(mass.values()), 3))
    json.dump(mi, open(os.path.join(outdir, "meta.json"), "w"), ensure_ascii=False, indent=1)
    build_deck(imgs, mi, OUT_PPT)


if __name__ == "__main__":
    main()
