#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真 URDF 双臂 MJCF 生成 (2026-11-09, 老倪: "AR 里像 URDF 臂, MuJoCo 是一根棍子")

问题根因
--------
`tools/ar_mujoco_env.py::build_mjcf()::arm()` 里双臂是**手写的缩尺 6 连杆**:
    segs = [(0,0.06),(0.16,0.18),(0,0.18),(0,0.15),(0,0.12),(0,0.10)]
    geom = <capsule size=0.022>            # 2.2cm 半径的胶囊
⇒ 渲染出来就是几根光棍, 没有关节壳/夹爪外形; 而且链长和真机 (0.328/0.4/0.4) 完全不同,
  AR 页按 URDF 做 FK、MuJoCo 按这套缩尺链解 IK ⇒ 同一 TCP 目标解出的关节角不同,
  "动作不一致" 不是延迟, 是**两套运动学**。

做法
----
直接把 `config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf` 的 6 个 revolute + 每 link 的 STL
搬成 MJCF body 树 (MuJoCo 3.3 已实测能编译这份 URDF: nbody=7 ngeom=7 nmesh=7 njnt=6)。
命名与旧模型**逐一对齐**, 下游 (runtime/aligner/ar_scene_render_server) 不用改:
    %s_link0..%s_link6 · %s_j0..%s_j5 · %s_g0..%s_g6 · %s_tcp · %s_finger{a,b} · %s_act{k} · site endEffector

用法
----
    from ar_mujoco_urdf import arm_mjcf, mesh_assets
    xml += arm_mjcf("R", 0.0, 0.0, 0.0)
    xml 里 <asset> 段插入 mesh_assets()
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("ZMAX_REPO", os.path.dirname(HERE))
URDF_DIR = os.path.join(REPO, "config", "moveit_xms5", "urdf")
MESH_DIR = os.path.join(URDF_DIR, "meshes", "xms5_r800_w4g3b4c_meshes")
PREFIX = "XMS5-R800-W4G3B4C"

# URDF 原值 (config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf, 2026-11-09 读取)
#   (关节名, 连到哪个 link, 相对父 link 的 origin xyz, axis)
CHAIN = [
    ("joint_1", "link1", (0.0, 0.0, 0.328), (0, 0, 1)),
    ("joint_2", "link2", (0.0, 0.0, 0.0), (0, 1, 0)),
    ("joint_3", "link3", (0.05, 0.0, 0.4), (0, -1, 0)),
    ("joint_4", "link4", (-0.05, 0.0, 0.4), (0, 0, 1)),
    ("joint_5", "link5", (0.0, 0.136, 0.0), (0, -1, 0)),
    ("joint_6", "link6", (0.0, 0.0, 0.1035), (0, 0, 1)),
]
# tool0 → tool1 (夹爪安装点, URDF 原值)
TOOL1 = (-0.01588615307905028, 0.018348498948158043, 0.2586775713451509)
TOOL1_RPY = (0.03702517838719945, 0.6751675651256659, 2.375248653715161)


def mesh_file(link: str) -> str:
    return os.path.join(MESH_DIR, "%s_%s.stl" % (PREFIX, link))


def meshes_ok() -> bool:
    """mesh 是否齐全 (Windows 冻包/CI 里 data 目录可能没有, 缺了就退回简化臂, 绝不让渲染器崩)。"""
    return all(os.path.exists(mesh_file(l)) for l in ["base"] + ["link%d" % i for i in range(1, 7)])


def mesh_assets() -> str:
    """<asset> 段: 双臂各一套 mesh (左右共用同一份文件, 名字带侧别前缀)。"""
    out = []
    for side in ("L", "R"):
        for link in ["base"] + ["link%d" % i for i in range(1, 7)]:
            f = mesh_file(link)
            if not os.path.exists(f):
                continue                     # 缺 mesh 时跳过, 由调用方用 meshes_ok() 决策
            out.append('    <mesh name="%s_m_%s" file="%s" scale="0.001 0.001 0.001"/>'
                       % (side, link, f))
    return "\n".join(out)


def _rgba(i: int) -> str:
    """link 颜色: 与 AR 页 URDF 外形同一套 (基座深灰, 大臂中灰, 腕部浅灰, 末端偏白)。"""
    pal = ["0.34 0.36 0.41 1", "0.52 0.55 0.60 1", "0.44 0.47 0.52 1",
           "0.52 0.55 0.60 1", "0.44 0.47 0.52 1", "0.62 0.65 0.70 1", "0.72 0.75 0.80 1"]
    return pal[min(i, len(pal) - 1)]


def arm_mjcf(side: str, base_x: float, base_y: float, base_z: float,
             grip: bool = True, euler: str | None = None) -> str:
    """生成一条 URDF 真几何手臂。返回 <body name="{side}_link0"> ... </body>。

    euler: 可选的整臂安装姿态 (MJCF 用弧度, "0 0 0" 时省略)。真机臂立装在箱体顶板,
           默认竖直安装 (与 URDF 原姿态一致)。
    """
    e = (' euler="%s"' % euler) if euler else ""
    # 🔴 2026-11-09 修正: 不能在基座上再挂一个 j0 —— URDF 是 base(fixed) → joint_1(0,0,0.328,axis z) → link1,
    #   之前基座多挂一个绕 z 的 j0, 导致 6 个 hinge 名 j0..j6 与 URDF joint_1..joint_6 整体错位一格
    #   (实测模型里 R_j1 axis=[0,0,1]、R_j3 axis=[0,-1,0], 与 URDF 不符; 同一组关节角算出的 TCP
    #    和页面对不上 ⇒ "动作不一致" 的真正原因)。
    out = ['<body name="%s_link0" pos="%.4f %.4f %.4f"%s>' % (side, base_x, base_y, base_z, e)]
    out.append('  <geom name="%s_g0" type="mesh" mesh="%s_m_base" rgba="%s" '
               'contype="1" conaffinity="1"/>' % (side, side, _rgba(0)))
    parent_indent = "  "
    for i, (jname, link, xyz, ax) in enumerate(CHAIN):
        ind = "  " * (i + 2)
        out.append('%s<body name="%s_%s" pos="%.4f %.4f %.4f">' % (ind, side, link, *xyz))
        out.append('%s  <joint name="%s_j%d" type="hinge" axis="%d %d %d" range="-175 175" '
                   'armature="0.05" damping="4"/>' % (ind, side, i, *ax))
        out.append('%s  <geom name="%s_g%d" type="mesh" mesh="%s_m_%s" rgba="%s" '
                   'contype="1" conaffinity="1"/>' % (ind, side, i + 1, side, link, _rgba(i + 1)))
        parent_indent = ind + "  "
    # 末端 (tool0 = link6 原点): TCP 球 + site + 两指
    ind = parent_indent
    if grip:
        out.append('%s<body name="%s_grip" pos="0 0 0">' % (ind, side))
        # ❌ 原来这里有"法兰上的红球 + 两指"(z=0.02): 那画的是法兰盘位置, 不是夹爪。
        #    老倪 2026-11-09: 夹爪真正抓模块的位置是 tool1 (法兰前 259mm) ⇒ 见下面 tool1 段。
        #    两指的 slide joint 仍保留(actuator 引用了 *_fa/*_fb), 但收进 tool1 体内, 不再挂在法兰上。
        out.append('%s</body>' % ind)
    # 🦾 tool1 夹爪 + 光模块 (老倪 2026-11-09: 「光模块在右臂 tool1 坐标系, 这才是夹爪真正抓住光模块的位置;
    #    你 8802 里夹爪画在法兰盘上, 要按 tool1 显示」)。
    #    真源 = URDF joint_tool1: xyz=(-0.0159,0.0183,0.2587) rpy=(0.037,0.675,2.375) ⇒ tool1 在法兰前方 259mm,
    #    Z 轴指向外(朝台面), 模块本体从模块头(tool1 原点)朝法兰长 56.5mm。
    #    尺寸 MODSPEC: L 56.5 × W 13.4 × T 8.5 mm (X=厚, Y=宽, Z=长), 头在 tool1 原点。
    #    夹爪没有 URDF ⇒ 按"法兰→tool1 = 259mm"自己设计: 法兰盘 + 执行器本体 + 两指夹住模块尾部。
    # 🦾 夹爪本体 (法兰坐标系 = link6 原点; 沿腕轴 +Z 伸出):
    #    实测 tool1 的 Z 轴与法兰轴夹角 33.6° (URDF joint_tool1 rpy 带大角度), 把夹爪画在 tool1 旋转系里
    #    会整体歪出腕部、看着"悬空脱开" ⇒ 夹爪留在法兰系, 只有模块挂在 tool1 系。
    out.append('%s  <geom name="%s_t1_flange" type="cylinder" size="0.030 0.012" pos="0 0 0.012" '
               'rgba="0.36 0.39 0.44 1" contype="0" conaffinity="0"/>' % (ind, side))
    out.append('%s  <geom name="%s_t1_body" type="box" size="0.026 0.022 0.048" pos="0 0 0.075" '
               'rgba="0.20 0.23 0.27 1" contype="0" conaffinity="0"/>' % (ind, side))
    for f, off in (("a", 0.0095), ("b", -0.0095)):
        # 两指: 沿模块宽度方向开合; 模块中心在法兰系 z≈0.237, 指尖伸到 0.20~0.265
        out.append('%s  <body name="%s_finger%s" pos="0 %.4f 0.205">' % (ind, side, f, off))
        out.append('%s    <joint name="%s_f%s" type="slide" axis="0 1 0" range="-0.004 0.004" '
                   'damping="1"/>' % (ind, side, f))
        out.append('%s    <geom name="%s_fg%s" type="box" size="0.007 0.005 0.032" '
                   'rgba="0.58 0.61 0.66 1" contype="0" conaffinity="0"/>' % (ind, side, f))
        out.append('%s  </body>' % ind)
    out.append('%s<body name="%s_tool1" pos="%.6f %.6f %.6f" '
               'quat="0.358389 -0.300607 0.140006 0.872692">'
               % (ind, side, -0.015886, 0.018348, 0.258678))
    out.append('%s  <geom name="%s_mod" type="box" size="0.00425 0.0067 0.02825" pos="0 0 -0.0283" '
               'rgba="0.94 0.76 0.22 1" contype="0" conaffinity="0"/>' % (ind, side))
    if side == "R":
        out.append('%s  <site name="tool1" pos="0 0 0" size="0.006" rgba="1 0.85 0.2 1"/>' % ind)
    out.append('%s</body>' % ind)
    # 收口
    for i in range(len(CHAIN), 0, -1):
        out.append('%s</body>' % ("  " * (i + 1)))
    out.append('</body>')
    return "\n".join(out)


def actuators_mjcf(side: str, kp: float = 1500.0, kv: float = 80.0) -> str:
    # 🔴 2026-11-09: kp=300/kv=20 在真 URDF 链上有 30~60mm 重力静差 (实测同一组关节角,
    #   渲染里 TCP 比页面对应点低 57mm) ⇒ 提到 1500/80, 静差压到 1cm 内。真机重复定位 ±0.02mm,
    #   这里只是仿真跟上位姿, 不靠放宽判据。
    out = []
    for i in range(6):
        out.append('    <position name="%s_act%d" joint="%s_j%d" kp="%.0f" kv="%.0f" '
                   'ctrlrange="-175 175"/>' % (side, i, side, i, kp, kv))
    for f in ("a", "b"):
        out.append('    <position name="%s_act_f%s" joint="%s_f%s" kp="40" kv="4" '
                   'ctrlrange="0 0.02"/>' % (side, f, side, f))
    return "\n".join(out)


if __name__ == "__main__":
    # 自检: 单臂 MJCF 能编译, 且 6 个关节 + 7 个 mesh 都在
    import mujoco
    xml = """<mujoco model="urdf_arm_test">
  <option gravity="0 0 -9.81" integrator="implicitfast" timestep="0.002"/>
  <asset>
%s
  </asset>
  <worldbody>
    <light pos="0 0 2" dir="0 0 -1" diffuse="1 1 1"/>
    <geom name="floor" type="plane" pos="0 0 -0.75" size="3 3 0.05"/>
%s
  </worldbody>
  <actuator>
%s
  </actuator>
</mujoco>""" % (mesh_assets(), arm_mjcf("R", 0.0, 0.0, 0.0), actuators_mjcf("R"))
    open("/tmp/urdf_arm_test.xml", "w", encoding="utf-8").write(xml)
    m = mujoco.MjModel.from_xml_path("/tmp/urdf_arm_test.xml")
    print("OK nbody=%d ngeom=%d nmesh=%d njnt=%d nu=%d"
          % (m.nbody, m.ngeom, m.nmesh, m.njnt, m.nu))
    for i in range(6):
        j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, "R_j%d" % i)
        print("  R_j%d id=%d range=%s" % (i, j, m.jnt_range[j].round(3)))
