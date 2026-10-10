#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摆盘场景 XML 生成器 (2026-10-10 老倪: 「配置中心配摆盘任务 → 仿真把 3 个光模块从料盘拿到 tray 盘」)

真源 = `tools/sim_scene_def._tray_layout()` (与页内 3D 视图同一份几何: 料盘 / tray 盘 / 3 个光模块 / 3 个槽位)
产出 = <metaworld assets>/sawyer_xyz/sawyer_tray_place.xml

与插拔场景 `sawyer_peg_insertion_side.xml` 的差别 (其余整段 include 不动 —— 机器人/夹爪/台面/相机同源):
  · 1 个光模块 → **3 个光模块** (peg / peg2 / peg3), 初始都在「料盘」里
  · 「带孔盒」(box, 插孔座) 整个移除 → 换成「tray 盘」(外廓同料盘 + 2 块隔板 = 3 个固定槽位)
  · 新增「料盘」(黑塑料托盘: 底板 + 4 壁 + 中灰内底)
  · 落位 site: slot1/2/3 (tray 槽中心, z = 内底顶面 + 件半高)
    兼容 site: goal / hole / pegGrasp / pegHead / pegEnd (metaworld env 的 obs/reset 认这些名字)

用法:
  gui-venv311/bin/python tools/gen_tray_place_scene.py            # 生成
  gui-venv311/bin/python tools/gen_tray_place_scene.py --check     # 只校验 (body/site/几何 vs 真源)
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import sim_scene_def as SSD  # noqa: E402

MODULE_NAMES = ("peg", "peg2", "peg3")      # 3 个光模块 body 名
SLOT_SITE = ("slot1", "slot2", "slot3")


def _mw_assets_dir() -> str:
    """metaworld 包 assets 目录 (与 gen_l4_demo_scene.py 同一套多候选探测)"""
    cands = []
    try:
        import metaworld as _mw
        cands.append(os.path.join(os.path.dirname(os.path.abspath(_mw.__file__)), "assets"))
    except Exception:  # noqa: BLE001
        pass
    _mp = getattr(sys, "_MEIPASS", None)
    if _mp:
        cands.append(os.path.join(_mp, "metaworld", "assets"))
    cands.append(os.path.join(ROOT, "gui-venv311", "lib", "python3.11",
                              "site-packages", "metaworld", "assets"))
    cands.append(os.path.join(ROOT, "venvs", "lerobot-venv", "lib", "python3.12",
                              "site-packages", "metaworld", "assets"))
    for c in cands:
        if os.path.isfile(os.path.join(c, "sawyer_xyz", "sawyer_peg_insertion_side.xml")):
            return c
    return cands[0]


MW = _mw_assets_dir()
SRC = os.path.join(MW, "sawyer_xyz", "sawyer_peg_insertion_side.xml")
DST = os.path.join(MW, "sawyer_xyz", "sawyer_tray_place.xml")

TABLETOP_Z = 0.0          # 台面顶 (metaworld sawyer 工作台面)


def layout():
    """从真源取摆盘几何: 料盘/托盘实体 + 3 个模块位 + 3 个槽位 (全是米)"""
    d = SSD._tray_layout()
    src, tray, mods, slots = [], [], [], []
    for o in d["objects"]:
        n = o["name"]
        item = {"name": n, "center": [float(v) for v in o["center"]],
                "size": [float(v) for v in o["size"]], "color": o.get("color")}
        if n.startswith("料盘"):
            src.append(item)
        elif n.startswith("tray盘"):
            tray.append(item)
        elif n.startswith("光模块"):
            mods.append(item)
    for m in d["markers"]:
        if "槽位" in m["name"]:
            slots.append({"name": m["id"], "pos": [float(v) for v in m["pos"]]})
    mods.sort(key=lambda x: x["center"][1])        # 按 y 排 1/2/3
    slots.sort(key=lambda x: x["pos"][1])
    return src, tray, mods, slots


def _geom(it, tag, rgba=None):
    c, s = it["center"], it["size"]
    col = rgba or ("%g %g %g 1" % tuple(it["color"] if it.get("color") else (0.5, 0.5, 0.5)))
    return ('        <geom name="%s" type="box" pos="%.5f %.5f %.5f" size="%.5f %.5f %.5f" '
            'rgba="%s" contype="1" conaffinity="1" group="1" friction="0.6 0.05 0.001"/>\n'
            % (tag, c[0], c[1], c[2], s[0], s[1], s[2], col))


def build(xml_src: str):
    """插拔场景 XML → 摆盘场景 XML (文本外科: 只换 peg body 与 box body, 其余原样)"""
    src, tray, mods, slots = layout()
    if len(mods) != 3 or len(slots) != 3:
        raise SystemExit("⛔ 真源几何不对: 模块 %d 个 / 槽位 %d 个 (要 3/3)" % (len(mods), len(slots)))
    half = [s / 2.0 for s in mods[0]["size"]]                 # 模块半尺寸
    inner_top = max((o["center"][2] + o["size"][2] / 2.0) for o in src if "内底" in o["name"])
    rest_z = inner_top + half[2]                              # 模块在盘里的落座高度 (底面贴内底)

    # ① 3 个模块 (替换原单个 peg body)
    peg = []
    for i, (body, m) in enumerate(zip(MODULE_NAMES, mods)):
        c = [m["center"][0], m["center"][1], rest_z if "料盘里" in m["name"] else m["center"][2]]
        sfx = "" if i == 0 else str(i + 1)
        peg.append(
            '        <body name="%s" pos="%.5f %.5f %.5f">\n'
            '          <inertial pos="0 0 0" mass="0.06" diaginertia="100000 100000 100000"/>\n'
            '          <geom name="%s_geom" size="%.5f %.5f %.5f" type="box" mass="0.06" '
            'rgba="0.92 0.74 0.24 1" conaffinity="1" contype="1" group="1" '
            'friction="1.2 0.06 0.002"/>\n'
            '          <joint type="free" limited="false" damping="0.005"/>\n'
            '          <site name="pegHead%s" pos="%.5f 0 0" size="0.004" rgba="0.8 0 0 1"/>\n'
            '          <site name="pegEnd%s" pos="%.5f 0 0" size="0.004" rgba="0.8 0 0 1"/>\n'
            '          <site name="pegGrasp%s" pos="%.5f 0 %.5f" size="0.004" rgba="0.8 0 0 1"/>\n'
            '          <site name="%s_grip" pos="0 0 0" size="0.004" rgba="0.9 0.9 0.2 1"/>\n'
            '        </body>\n'
            % (body, c[0], c[1], c[2], body, half[0], half[1], half[2], sfx, -half[0], sfx,
               half[0], sfx, half[0] * 0.55, half[2] * 1.1, body))
    peg_block = "".join(peg)

    # ② 料盘 + tray 盘 (静态几何, 直接从真源坐标落地) + 3 个槽位 site
    static = ['        <body name="src_tray" pos="0 0 0">\n']
    for i, it in enumerate(src):
        static.append(_geom(it, "src_%d" % i))
    static.append("        </body>\n")
    static.append('        <body name="dst_tray" pos="0 0 0">\n')
    for i, it in enumerate(tray):
        static.append(_geom(it, "dst_%d" % i))
    static.append("        </body>\n")
    slots_xml = ""
    for i, s in enumerate(slots):
        slots_xml += ('        <site name="%s" pos="%.5f %.5f %.5f" size="0.008" '
                      'rgba="1 0.25 0.25 1"/>\n'
                      % (SLOT_SITE[i], s["pos"][0], s["pos"][1], rest_z))
    # 兼容 site (metaworld env 的 obs/reset 认 goal/hole)
    slots_xml += ('        <site name="goal" pos="%.5f %.5f %.5f" size="0.01" rgba="0.8 0 0 1"/>\n'
                  '        <site name="hole" pos="%.5f %.5f %.5f" size="0.005" rgba="0 0.8 0 1"/>\n'
                  % (slots[0]["pos"][0], slots[0]["pos"][1], rest_z,
                     slots[0]["pos"][0], slots[0]["pos"][1], rest_z))

    # ③ 文本外科: peg body 块 → 3 模块;  box body 块 → 料盘 + tray 盘
    out, n_peg, n_box = [], 0, 0
    i = 0
    lines = xml_src.splitlines(keepends=True)
    while i < len(lines):
        ln = lines[i]
        if re.search(r'<body name="peg"', ln):
            depth = 0
            while i < len(lines):
                depth += lines[i].count("<body") - lines[i].count("</body>")
                i += 1
                if depth <= 0:
                    break
            out.append(peg_block)
            n_peg += 1
            continue
        if re.search(r'<body name="box"', ln):
            depth = 0
            while i < len(lines):
                depth += lines[i].count("<body") - lines[i].count("</body>")
                i += 1
                if depth <= 0:
                    break
            out.append("".join(static))
            n_box += 1
            continue
        if re.search(r'<site name="goal"', ln):
            out.append(slots_xml)
            i += 1
            continue
        out.append(ln)
        i += 1
    if n_peg != 1 or n_box != 1:
        raise SystemExit("⛔ 文本外科失败: peg body %d 处 / box body %d 处 (各要 1)" % (n_peg, n_box))
    return "".join(out), dict(rest_z=rest_z, inner_top=inner_top, half=half,
                              mods=mods, slots=slots, src=src, tray=tray)


def check():
    """判据: XML 能载入 + 3 模块/2 盘/3 槽位 site 都在 + 槽位 site 与真源一致"""
    import mujoco
    m = mujoco.MjModel.from_xml_path(DST)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    src, tray, mods, slots = layout()
    have_bodies = {m.body(i).name for i in range(m.nbody)}
    have_sites = {m.site(i).name for i in range(m.nsite)}
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + msg)
        ok = ok and bool(cond)

    chk(os.path.isfile(DST), "XML 存在: %s" % os.path.relpath(DST, ROOT))
    chk(all(b in have_bodies for b in MODULE_NAMES), "3 个光模块 body 在: %s" % ", ".join(MODULE_NAMES))
    chk("src_tray" in have_bodies and "dst_tray" in have_bodies, "料盘 + tray 盘 body 在")
    chk("box" not in have_bodies, "插拔用「带孔盒」已移除 (摆盘无插孔)")
    chk(all(s in have_sites for s in SLOT_SITE), "3 个槽位 site 在: %s" % ", ".join(SLOT_SITE))
    _rz = max((o["center"][2] + o["size"][2] / 2.0) for o in src if "内底" in o["name"])
    half = mods[0]["size"][2] / 2.0
    for i, s in enumerate(slots):
        sid = m.site(SLOT_SITE[i]).id
        p = d.site_xpos[sid]
        err = abs(p[0] - s["pos"][0]) + abs(p[1] - s["pos"][1])
        chk(err < 1e-6, "%s 位置 == 真源 (%.4f,%.4f,%.4f) err=%.2e"
            % (SLOT_SITE[i], s["pos"][0], s["pos"][1], _rz + half, err))
    for i, b in enumerate(MODULE_NAMES):
        bid = m.body(b).id
        p = d.xpos[bid]
        exp = mods[i]["center"]
        chk(abs(p[1] - exp[1]) < 1e-6, "%s 初始在料盘 (y=%.4f, 期望 %.4f)" % (b, p[1], exp[1]))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不生成")
    a = ap.parse_args()
    if a.check:
        print("🧪 摆盘场景判据 (--check)"); sys.exit(check())
    xml_src = open(SRC, encoding="utf-8").read()
    xml, meta = build(xml_src)
    open(DST, "w", encoding="utf-8").write(xml)
    print("✅ 摆盘场景已生成: %s" % os.path.relpath(DST, ROOT))
    print("   3 个光模块 (peg/peg2/peg3) 落在料盘 · 落座 z=%.4f (内底顶面 %.4f + 半高 %.4f)"
          % (meta["rest_z"], meta["inner_top"], meta["half"][2]))
    print("   tray 盘 3 个槽位 site: " + ", ".join(
        "%s(%.4f,%.4f)" % (SLOT_SITE[i], s["pos"][0], s["pos"][1]) for i, s in enumerate(meta["slots"])))
    print("   料盘 %d 块几何 · tray 盘 %d 块几何 (真源 tools/sim_scene_def._tray_layout)"
          % (len(meta["src"]), len(meta["tray"])))
    sys.exit(check())


if __name__ == "__main__":
    main()
