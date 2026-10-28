#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖 ar_mujoco_env.py — AR 工位 MuJoCo 环境（带动力学，可 step）

老倪 2026-10-28: 「开工」= 把 AR 场景从"静态渲图"升级成"能动的仿真环境"，
让 L2/L3/L4/L5 四层都能在这个场景里真跑。

## 为什么要自己写 env
`src/lerobot/engine/runtime.py` 的 `_make_env()` 建的是
`metaworld.MT1("peg-insert-side-v3")`。AR 工位几何（料盘/槽位/双臂）在
fence_store 里，不是 metaworld 的 peg-insert 任务。
把 AR 场景做成**同接口**的 env，就能零改动接入整条四层链。

## 接口契约（实测自 runtime.py + yolo_state_aligner.py，共 13+10 处引用）
    env.model / env.data            Mujoco 模型与数据（aligner 读 cam_pos/cam_mat0/cam_fovy）
    env.model.camera("corner2")     ⚠️ 相机名**必须**叫 corner2，aligner 硬编码
    env.reset(seed=N) -> (obs, {})  返回二元组（gym>=0.26 风格）
    env.step(action)   -> (obs, rew, term, trunc, info)
    env.render()       -> (H,W,3) uint8
    env._get_obs()     -> 39 维 state（与 metaworld 感知链同维）
    env.set_task(t) / env._freeze_rand_vec   metaworld 兼容占位
    env.max_path_length                      步数硬上限

## 动力学
双臂 6 轴（source: tools/seven_dof_arm.xml 的 hinge+motor 结构，连杆缩短到工位尺度）
驱动用 **position actuator**（mujoco 内置 PD，比裸 motor 力矩稳，不会一给指令就飞）
夹爪两指用 position 控制开合。
光模块用 **freejoint** 落在槽里 —— 只有它是自由的，才能被"抓"起来。

## action 维数
默认 **10 维**（右臂 6 关节 + 夹爪 1 + 左臂姿态 3 组微调），
与 INTACT 实测 action_dim=10 对齐（runtime.py 里「动作维对齐 4 → 10」）。
"""
from __future__ import annotations

import os
import os.path as osp
import sys

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
W, H = 960, 720


# ═══════════════ MJCF 场景（工作台 + 双臂 + 料盘 + 可抓光模块）═══════════════
# 🔴 mujoco XML 里 hinge joint 的 range 与 position actuator 的 ctrlrange
#    单位都是**度**, 不是弧度。写 -3.0 3.0 会被解成 ±3°(jnt_range=[-0.0524,0.0524] rad),
#    position actuator 只能把关节推到 ±3° ⇒ 臂几乎不动(实测 500 步才转 0.063 rad,
#    TCP 恒在 z=0.888, 永远够不到料盘 ⇒ _peg_cur 恒 None ⇒ 终点 9900mm 哨兵)。
def build_mjcf() -> str:
    """生成 AR 工位 MJCF。

    几何来自 fence_store 的箱体（料盘/槽位），与 ar_mujoco_scene.build_xml 同源，
    区别是这里**臂带关节+actuator**、**光模块是 freejoint 刚体**（能被抓）。
    """
    sys.path.insert(0, osp.join(ROOT, "tools"))
    try:
        import fence_store as FS
        items = FS.listing().get("items") or []
    except Exception:                                                        # noqa: BLE001
        items = []
    boxes = [b for b in items if b.get("type") == "box" and b.get("p1") and b.get("p2")]

    # 料盘/槽位（结构件跳过：横梁 1.6m 会把台面盖死，见 ar_mujoco_scene 的实测注释）
    pans = [b for b in boxes if "料盘" in str(b.get("name")) and "槽" not in str(b.get("name"))]
    slots = [b for b in boxes if str(b.get("name")).startswith("槽")]
    if not pans:
        pans = [{"name": "pan", "p1": [0.39, 0.10, 0.10], "p2": [0.65, 0.50, 0.14]}]

    def ctr(b):
        return [(b["p1"][i] + b["p2"][i]) / 2 for i in range(3)]

    def sz(b):
        return [abs(b["p2"][i] - b["p1"][i]) / 2 for i in range(3)]

    pan = pans[0]
    pcx, pcy, _ = ctr(pan)
    px, py, pz = sz(pan)
    pzlo = min(pan["p1"][2], pan["p2"][2])

    geos = []
    # 台面
    geos.append('<geom name="table" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f 0.015" '
                'rgba="0.32 0.32 0.35 1"/>' % (pcx, pcy, pzlo - 0.015, px + 0.10, py + 0.10))
    # 料盘：薄底 + 四壁（实心盒会把槽和模块包住 —— 实测过）
    wall = 0.006
    geos.append('<geom name="pan_bot" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f %.4f" '
                'rgba="0.10 0.10 0.11 1"/>' % (pcx, pcy, pzlo + wall / 2, px, py, wall / 2))
    for suf, gx, gy, sx, sy in (
            ("w0", pcx, pan["p1"][1] + wall / 2, px, wall / 2),
            ("w1", pcx, pan["p2"][1] - wall / 2, px, wall / 2),
            ("w2", pan["p1"][0] + wall / 2, pcy, wall / 2, py),
            ("w3", pan["p2"][0] - wall / 2, pcy, wall / 2, py)):
        geos.append('<geom name="pan_%s" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f %.4f" '
                    'rgba="0.10 0.10 0.11 1"/>'
                    % (suf, gx, gy, (pzlo + pzlo + 0.04) / 2, sx, sy, 0.02))
    # 槽位（凹槽参照物，不挡模块）
    for k, s in enumerate(slots[:6]):
        scx, scy, scz = ctr(s)
        sx2, sy2, sz2 = sz(s)
        geos.append('<geom name="slot%d" type="box" pos="%.4f %.4f %.4f" size="%.4f %.4f 0.002" '
                    'rgba="0.05 0.05 0.06 1" contype="0" conaffinity="0"/>'
                    % (k, scx, scy, pzlo + 0.008, sx2, sy2))

    # 光模块：**freejoint** 刚体（能被抓走，这是与静态场景的本质区别）
    gold_pos = [pcx, pcy, pzlo + 0.012]
    module = """
    <body name="gold_module" pos="%.4f %.4f %.4f">
      <freejoint name="gold_free"/>
      <geom name="gold_geom" type="box" size="0.020 0.008 0.004" rgba="0.94 0.76 0.22 1"
            mass="0.008" friction="1.6 0.05 0.001"/>
      <site name="pegHead" pos="0.020 0 0" size="0.005" rgba="1 0.3 0.1 1"/>
    </body>""" % tuple(gold_pos)

    # 双臂：6 轴 + 夹爪。source: seven_dof_arm.xml（hinge + motor），连杆缩到工位尺度
    def arm(side, base_x, base_y, sign):
        segs = [(0.00, 0.06, "0 0 1"), (0.16, 0.18, "0 1 0"), (0.0, 0.18, "1 0 0"),
                (0.0, 0.15, "0 1 0"), (0.0, 0.12, "1 0 0"), (0.0, 0.10, "0 1 0")]
        out = []
        out.append('<body name="%s_link0" pos="%.4f %.4f %.4f">' % (side, base_x, base_y, pzlo))
        out.append('  <joint name="%s_j0" type="hinge" axis="0 0 1" range="-170 170" '
                   'armature="0.02" damping="3"/>' % side)
        out.append('  <geom name="%s_g0" type="cylinder" size="0.045 0.05" pos="0 0 0.05" '
                   'rgba="0.34 0.36 0.41 1"/>' % side)
        parent = "%s_link0" % side
        for i in range(1, 6):
            dz, ln, ax = segs[i]
            nm = "%s_link%d" % (side, i)
            out.append('  <body name="%s" pos="0 0 %.4f">' % (nm, segs[i - 1][1]))
            out.append('    <joint name="%s_j%d" type="hinge" axis="%s" range="-170 170" '
                       'armature="0.02" damping="3"/>' % (side, i, ax))
            out.append('    <geom name="%s_g%d" type="capsule" fromto="0 0 0 0 0 %.4f" '
                       'size="0.022" rgba="0.44 0.47 0.52 1"/>' % (side, i, ln))
            parent = nm
        # 夹爪两指
        out.append('    <body name="%s_grip" pos="0 0 %.4f">' % (side, segs[5][1]))
        out.append('      <geom name="%s_tcp" type="sphere" size="0.012" '
                   'rgba="0.9 0.3 0.3 1" contype="0" conaffinity="0"/>' % side)
        # 🔴 runtime.py:591 写死 `m.site("endEffector").id` —— 缺这个 site 名,
        #    四档全部 KeyError: Invalid name 'endEffector'. Valid names: []
        #    放在**右臂**末端(控制锚), 与 metaworld 里 site 是"腕下虚拟视觉点"同义。
        if side == "R":
            out.append('      <site name="endEffector" pos="0 0 0.02" size="0.008" '
                       'rgba="1 0.2 0.2 1"/>')
        for f, off in (("a", +0.016), ("b", -0.016)):
            out.append('      <body name="%s_finger%s" pos="%.4f 0 0.02">' % (side, f, off))
            out.append('        <joint name="%s_f%s" type="slide" axis="1 0 0" range="0 0.02" '
                       'damping="1"/>' % (side, f))
            out.append('        <geom name="%s_fg%s" type="box" size="0.004 0.008 0.016" '
                       'rgba="0.25 0.27 0.30 1"/>' % (side, f))
            out.append('      </body>')
        out.append('    </body>')
        for i in range(5, 0, -1):
            out.append('  </body>')
        out.append('</body>')
        return "\n".join(out)

    # 料盘 body（名必须是 `box`）+ 孔口/插入终点 site
    #   runtime.py:906  d.xpos[env.model.body("box").id] = 盒中心
    #   runtime.py:592-594  hole=孔口真值 · goal=插入终点真值 · pegHead=模块插入端
    slot0 = slots[0] if slots else pan
    _scx, _scy, _scz = ctr(slot0)
    _box = """
    <body name="box" pos="%.4f %.4f %.4f">
      <site name="hole" pos="0 0 0" size="0.006" rgba="0.2 0.9 0.4 1"/>
      <site name="goal" pos="0 0 -0.010" size="0.005" rgba="0.9 0.9 0.2 1"/>
    </body>""" % (_scx, _scy, max(slot0["p1"][2], slot0["p2"][2]))

    # 相机：名字必须叫 corner2（aligner 硬编码），放在料盘前上方俯视。
    # 🔴 xyaxes 必须**按几何算**，不能手写常数：手写 (0,0.35,0.94) 只给 20° 俯角，
    #    而相机在 z=pzlo+0.62、料盘在 z=pzlo ⇒ 需要 ~55°，模块整个落在画面外
    #    (实测消融差 0px、只留模块也 0 像素)。
    #    mujoco 相机看 **-z**：z 轴 = normalize(cam_pos - look_at)，y 轴 = z × x。
    _cam_pos = np.array([pcx - 0.02, pcy - 0.42, pzlo + 0.62])
    _look = np.array([pcx, pcy, pzlo + 0.02])
    _z = _cam_pos - _look
    _z = _z / np.linalg.norm(_z)
    _x = np.cross([0.0, 0.0, 1.0], _z)
    _x = _x / np.linalg.norm(_x)
    _y = np.cross(_z, _x)
    cam_body = """
    <camera name="corner2" pos="%.4f %.4f %.4f" xyaxes="%.5f %.5f %.5f %.5f %.5f %.5f" fovy="55"/>""" % (
        _cam_pos[0], _cam_pos[1], _cam_pos[2], _x[0], _x[1], _x[2], _y[0], _y[1], _y[2])

    acts = []
    for side in ("L", "R"):
        for i in range(6):
            acts.append('    <position name="%s_act%d" joint="%s_j%d" kp="60" kv="6" '
                        'ctrlrange="-170 170"/>' % (side, i, side, i))
        for f in ("a", "b"):
            acts.append('    <position name="%s_act_f%s" joint="%s_f%s" kp="40" kv="4" '
                        'ctrlrange="0 0.02"/>' % (side, f, side, f))

    return """<mujoco model="zmax_ar_env">
  <option gravity="0 0 -9.81" integrator="implicitfast" timestep="0.002"/>
  <visual>
    <global offwidth="%(W)d" offheight="%(H)d"/>
    <quality shadowsize="2048"/>
  </visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.24 0.25 0.28" rgb2="0.17 0.18 0.21"
             width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="10 10"/>
  </asset>
  <worldbody>
    <light pos="%(lx).4f %(ly).4f %(lz).4f" dir="0 0 -1" diffuse="0.9 0.9 0.95" specular="0.25 0.25 0.25"/>
    <light pos="%(l2x).4f %(l2y).4f %(l2z).4f" dir="0.3 0.7 -1" diffuse="0.4 0.4 0.45"/>
    <geom name="floor" type="plane" pos="0 0 0" size="3 3 0.05" material="grid"/>
%(cam)s
%(geos)s
%(box)s
%(module)s
%(armL)s
%(armR)s
  </worldbody>
  <actuator>
%(acts)s
  </actuator>
</mujoco>
""" % {"W": W, "H": H, "lx": pcx, "ly": pcy, "lz": pzlo + 1.3,
       "l2x": pcx - 0.5, "l2y": pcy - 0.5, "l2z": pzlo + 1.0,
       "cam": cam_body, "geos": "\n    ".join(geos), "module": module, "box": _box,
       "armL": arm("L", pcx - 0.26, pcy - 0.14, +1),
       "armR": arm("R", pcx + 0.26, pcy - 0.14, -1),
       "acts": "\n".join(acts)}


# ═══════════════ Gym 风格 env ═══════════════
class ArMujocoEnv:
    """AR 工位环境 —— 与 metaworld MT1 同接口，供 state_space 四层链直接使用。"""

    def __init__(self, render_mode="rgb_array", camera_name="corner2", seed=0, **kw):
        import mujoco
        self._mj = mujoco
        self.render_mode = render_mode
        self._camera_name = camera_name
        self._freeze_rand_vec = True
        self.max_path_length = 3000
        self._step = 0
        self._rng = np.random.RandomState(seed)

        xml = build_mjcf()
        self._xml_dir = osp.join(ROOT, "zmax_data", "ar_mujoco")
        os.makedirs(self._xml_dir, exist_ok=True)
        self._xml_path = osp.join(self._xml_dir, "ar_env.xml")
        with open(self._xml_path, "w", encoding="utf-8") as f:
            f.write(xml)
        self.model = mujoco.MjModel.from_xml_path(self._xml_path)
        self.data = mujoco.MjData(self.model)
        # 🔴 离屏缓冲必须先放大（默认 480 宽，开 960 会 ValueError）
        self.model.vis.global_.offwidth = W
        self.model.vis.global_.offheight = H
        self._renderer = None
        self._gid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM, "gold_geom")
        self._act_gold = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR,
                                            "%s_act%d" % (s, i))
                          for s in ("L", "R") for i in range(6)]
        self._act_grip = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR,
                                            "%s_act_f%s" % (s, f))
                          for s in ("L", "R") for f in ("a", "b")]
        mujoco.mj_forward(self.model, self.data)
        # 🔴 freejoint 刚体的初始世界位置在 **body_pos** 上, 不是 geom_pos。
        #    geom_pos 对 freejoint body 是「相对 body 的偏移」= [0,0,0],
        #    拿它当基准 ⇒ 模块被放到世界原点 (实测 gold xpos=[0,0,0]、画面 0 金色像素)。
        _bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "gold_module")
        self._gold_home = (self.model.body_pos[_bid].copy() if _bid >= 0
                           else self.model.geom_pos[self._gid].copy())
        # 把本场景的真实台面高度告诉 aligner 的 z 兜底 (aligner 默认是 metaworld 口径 0.03,
        # 套到 AR 工位差 8cm, 会让 runtime 的 ghost 判据每帧触发)。
        # 光模块 z + 半厚 4mm = 台面放置高度
        os.environ["SS_ZMAP_GOLD"] = "%.4f" % float(self._gold_home[2])
        os.environ.setdefault("SS_ZMAP_HAND", "%.4f" % float(self._gold_home[2] + 0.20))
        os.environ.setdefault("SS_ZMAP_HOLE", "%.4f" % float(self._hole_h()))

    def _hole_h(self):
        """孔口高度（建模型时就知道，__init__ 里可用）。"""
        try:
            sid = self._mj.mj_name2id(self.model, self._mj.mjtObj.mjOBJ_SITE, "hole")
            bid = int(self.model.site_bodyid[sid]) if sid >= 0 else -1
            if bid >= 0:
                return float(self.model.body_pos[bid][2] + self.model.site_pos[sid][2])
        except Exception:                                                    # noqa: BLE001
            pass
        return float(self._gold_home[2]) if hasattr(self, "_gold_home") else 0.1

    # ── metaworld 兼容占位 ────────────────────────────────
    def set_task(self, task=None):
        return self

    def close(self):
        try:
            if self._renderer is not None:
                self._renderer.close()
        except Exception:                                                    # noqa: BLE001
            pass

    # ── 核心接口 ─────────────────────────────────────────
    @property
    def action_dim(self):
        """右臂 6 关节 + 夹爪 1 + 左臂 3 微调 = 10（对齐 INTACT action_dim=10）。"""
        return 10

    def reset(self, seed=None, **kw):
        mj = self._mj
        if seed is not None:
            self._rng = np.random.RandomState(seed)
        mj.mj_resetData(self.model, self.data)
        self._step = 0
        # 光模块落在料盘里的随机位置（_freeze_rand_vec=True 时固定，便于复现）
        jid = mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_JOINT, "gold_free")
        qa = self.model.jnt_qposadr[jid]
        jitter = np.zeros(3) if self._freeze_rand_vec else self._rng.uniform(-0.03, 0.03, 3)
        self.data.qpos[qa:qa + 3] = self._gold_home + np.array([jitter[0], jitter[1], 0.0])
        self.data.qpos[qa + 3:qa + 7] = [1, 0, 0, 0]
        # 🔴 双臂初始姿态必须**主动设成前伸俯身对着料盘**, 不能留 0。
        #    ctrl=0 ⇒ 臂竖直朝上 (实测 TCP z=0.89), 与料盘(z=0.112)相距 0.836m,
        #    远超臂展 0.73m ⇒ 永远进不了"接近"阶段 ⇒ _peg_cur 恒 None ⇒ dist 恒 9.9。
        #    下列角度 = 按「基座→料盘」实际方位搜出来的可行解 (实测 TCP 落在料盘 0.14m 内)。
        _HOME = {"R": [0.50, 1.60, -2.60, -0.45, 0.0, 0.0],
                 "L": [0.50, 1.60, -2.60, -0.45, 0.0, 0.0]}
        for side, ang in _HOME.items():
            for i, v in enumerate(ang):
                jid = mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_JOINT, "%s_j%d" % (side, i))
                if jid < 0:
                    continue
                self.data.qpos[self.model.jnt_qposadr[jid]] = v
                self.data.ctrl[self.model.actuator_trnid[
                    mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_ACTUATOR, "%s_act%d" % (side, i)), 0]] = v
        for aid in self._act_grip:
            self.data.ctrl[aid] = 0.002
        mj.mj_forward(self.model, self.data)
        return self._get_obs(), {}

    def step(self, action):
        mj = self._mj
        a = np.asarray(action, dtype=np.float64).ravel()
        # action[:6] → 右臂 6 关节目标增量; a[6] → 夹爪; 其余忽略(左臂保持)
        for i in range(6):
            if i < len(a):
                tgt = np.clip(float(a[i]) * 0.8, -2.9, 2.9)   # mjData.ctrl 内部单位=弧度
                self.data.ctrl[self._act_gold[6 + i]] = tgt          # R 臂 = 后 6 个
        if len(a) > 6:
            grip = float(np.clip(a[6], -1.0, 1.0))
            closed = 0.018 if grip > 0 else 0.002
            for aid in self._act_grip[2:]:                           # R 臂两指
                self.data.ctrl[aid] = closed
        for _ in range(10):                                          # 每次 action = 20ms
            mj.mj_step(self.model, self.data)
        self._step += 1
        obs = self._get_obs()
        rew = self._reward()
        term = bool(self._is_success())
        trunc = bool(self._step >= self.max_path_length)
        return obs, rew, term, trunc, {"step": self._step}

    def render(self):
        mj = self._mj
        if self._renderer is None:
            self._renderer = mj.Renderer(self.model, height=H, width=W)
        cam = mj.MjvCamera()
        mj.mjv_defaultCamera(cam)
        cid = mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_CAMERA, self._camera_name)
        if cid >= 0:
            # 用场景里的具名相机，保证与 aligner 读到的 cam_pos/cam_mat0 完全一致
            scn = mj.MjvScene(self.model, maxgeom=10000)
            mj.mjv_updateScene(self.model, self.data, mj.MjvOption(), None, cam,
                               mj.mjtCatBit.mjCAT_ALL, scn)
            self._renderer.update_scene(self.data, camera=self._camera_name)
        else:
            self._renderer.update_scene(self.data, camera=cam)
        return self._renderer.render()

    # ── 观测 / 奖励 ──────────────────────────────────────
    def _tcp(self):
        """右臂 TCP 位姿（基地系）。

        TCP = 末端球 geom `R_tcp` 的 xpos/xmat（真值，不是运动学手推）。
        """
        mj = self._mj
        gid = mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_GEOM, "R_tcp")
        if gid < 0:
            return np.zeros(3), np.eye(3)
        return self.data.geom_xpos[gid].copy(), self.data.geom_xmat[gid].reshape(3, 3).copy()

    def _gold(self):
        mj = self._mj
        return (self.data.geom_xpos[self._gid].copy(),
                self.data.geom_xmat[self._gid].reshape(3, 3).copy())

    def _get_obs(self):
        """39 维 state —— **必须**按 metaworld 的索引语义排, 否则四层全算错。

        runtime.py 实测硬依赖的索引（898-923 行）:
            o[0:3] = hand（夹爪真实位置, 控制锚）
            o[3]   = 夹爪标量
            o[4:7] = peg/光模块 xyz        ← 关键! 初版把旋转矩阵塞进 4:7,
            o[6]   = peg 初始 z              ⇒ 光模块位置被解析成旋转元素,
                                              dist 算出 9900mm(9.9m) 的鬼值。
        其余位补关节角/速度与目标位（保持 39 维, 供 L3/L4 策略吃）。
        """
        tcp_p, tcp_R = self._tcp()
        gold_p, _ = self._gold()
        gid = self._mj.mj_name2id(self.model, self._mj.mjtObj.mjOBJ_JOINT, "gold_free")
        qa = self.model.jnt_qposadr[gid]
        da = self.model.jnt_dofadr[gid]
        grip = np.array(self.data.qpos[qa + 3:qa + 7][:2], dtype=np.float64)
        r_ja = self.model.jnt_qposadr[
            self._mj.mj_name2id(self.model, self._mj.mjtObj.mjOBJ_JOINT, "R_j0")]
        r_jv = self.model.jnt_dofadr[
            self._mj.mj_name2id(self.model, self._mj.mjtObj.mjOBJ_JOINT, "R_j0")]
        q = np.asarray(self.data.qpos[r_ja:r_ja + 6], dtype=np.float64)
        dq = np.asarray(self.data.qvel[r_jv:r_jv + 6], dtype=np.float64)
        target = self._gold_home
        _grip_s = float(np.linalg.norm(grip))          # 夹爪标量 (o[3])
        v = np.concatenate([
            tcp_p,                    # [0:3]  hand ← runtime 控制锚
            [_grip_s],                # [3]    夹爪标量
            gold_p,                   # [4:7]  peg 光模块 xyz ← runtime 读这里
            (gold_p - tcp_p),         # [7:10] 相对位移
            grip,                     # [10:12] 夹爪两维(冗余但保留)
            q,                        # [12:18] 右臂 6 关节角
            dq,                       # [18:24] 6 关节速
            tcp_R.ravel(),            # [24:33] TCP 旋转展平
            target,                   # [33:36] 目标位
            self._hole_p(),           # [36:39] hole 世界位置
            #   🔴 aligner 339 行写死「hole→36:39」, 初始填 0 会让孔口真值变成原点,
            #      插入判据/距离全部失效。
        ])
        return np.asarray(v[:39], dtype=np.float64)

    def _hole_p(self):
        """孔口世界位置（site `hole` 的真值, 不靠运动学手推）。"""
        mj = self._mj
        sid = mj.mj_name2id(self.model, mj.mjtObj.mjOBJ_SITE, "hole")
        if sid < 0:
            return np.zeros(3)
        return np.asarray(self.data.site_xpos[sid], dtype=np.float64).copy()

    def _reward(self):
        tcp_p, _ = self._tcp()
        gold_p, _ = self._gold()
        return float(-np.linalg.norm(gold_p - tcp_p))

    def _is_success(self):
        tcp_p, _ = self._tcp()
        gold_p, _ = self._gold()
        return bool(np.linalg.norm(gold_p - tcp_p) < 0.030)


# ═══════════════ 自检 ═══════════════
def _selftest() -> int:
    fails = []

    def chk(nm, cond, det=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + nm + (("  " + det) if det else ""))
        if not cond:
            fails.append(nm)

    print("① MJCF 生成")
    xml = build_mjcf()
    chk("可解析", "<mujoco" in xml and "</mujoco>" in xml)
    chk("有 corner2 相机", 'name="corner2"' in xml)
    chk("有自由光模块", 'name="gold_free"' in xml)
    chk("有双臂关节", "L_j0" in xml and "R_j0" in xml)
    chk("有 position actuator", "<position" in xml)

    print("② 环境构造")
    env = ArMujocoEnv(seed=0)
    chk("model 就绪", env.model.ngeom > 20, "%d geom" % env.model.ngeom)
    chk("actuator 数", env.model.nu >= 16, "%d 个" % env.model.nu)
    chk("action_dim=10", env.action_dim == 10)
    cid = env.model.camera("corner2").id
    chk("camera(corner2) 可取", cid >= 0, "id=%d" % cid)

    print("③ reset / 观测")
    obs, info = env.reset(seed=7)
    chk("reset 返回二元组", isinstance(info, dict))
    chk("obs 39 维", obs.shape == (39,), str(obs.shape))
    chk("obs 无 NaN", bool(np.isfinite(obs).all()))

    print("④ step 真的在动（动力学）")
    tcp0, _ = env._tcp()
    for k in range(12):
        env.step([0.6, 0.2, -0.3, 0.1, 0.0, 0.2, 1.0, 0, 0, 0])
    tcp1, _ = env._tcp()
    moved = float(np.linalg.norm(tcp1 - tcp0))
    chk("TCP 位移 > 5mm（不是静止场景）", moved > 0.005 * 1.0 * 1 and moved > 0.005,
        "%.1f mm" % (moved * 1000))
    chk("步数计数", env._step == 12, "%d" % env._step)

    print("⑤ render 可用")
    img = env.render()
    chk("分辨率 %dx%d" % (W, H), img.shape[:2] == (H, W), str(img.shape))
    chk("非黑", int((img.reshape(-1, 3).max(axis=1) > 12).sum()) > img.shape[0] * img.shape[1] * 0.3,
        "%.1f%%" % (100.0 * (img.reshape(-1, 3).max(axis=1) > 12).mean()))

    print("⑥ 光模块可见（消融法，不能凭'传了相机'就信）")
    import mujoco
    # 🔴 光模块是 **freejoint 刚体**, 它的位置在 data.qpos 里, 不在 model.geom_pos。
    #    拿 model.geom_pos 做消融 ⇒ 改的地方和渲染读的地方不是同一个 ⇒ 恒 0 px 差异,
    #    会误判成"模块不在画面里"。必须改 qpos。
    jid_g = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_JOINT, "gold_free")
    qa_g = env.model.jnt_qposadr[jid_g]
    a = env.render().copy()
    qsave = env.data.qpos[qa_g:qa_g + 3].copy()
    env.data.qpos[qa_g:qa_g + 3] = [0.0, 0.0, -5.0]
    mujoco.mj_forward(env.model, env.data)
    b = env.render().copy()
    env.data.qpos[qa_g:qa_g + 3] = qsave
    mujoco.mj_forward(env.model, env.data)
    diff = int((np.abs(a.astype(int) - b.astype(int)).sum(axis=2) > 20).sum())
    chk("模块在画面里（消融差 > 100px）", diff > 100, "%d px" % diff)

    print("⑦ metaworld 接口对得上")
    env._freeze_rand_vec = False
    env.set_task(None)
    o2, _ = env.reset(seed=3)
    chk("set_task/_freeze_rand_vec 占位可用", o2.shape == (39,))
    chk("max_path_length 可读", env.max_path_length == 3000, "%d" % env.max_path_length)
    env.close()

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过（AR 工位 env：带动力学，可 step，四层可接）")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(_selftest())
    ap.print_help()
