#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 摆盘 episode 生成器 — 状态空间六层源码**直接驱动** metaworld (2026-10-10 老倪)

老倪: 「在配置中心配摆盘任务, 通过配置改变状态空间的功能, 完成摆盘场景 —— 仿真场景里把
       三个光模块从料盘拿起, 摆放到 tray 盘。所有功能都要由状态空间自己完成。」

链路 (与画布一致, 动作全部由六层算出, 没有"脚本硬编码轨迹"):
  L5 下指令   → 任务/阶段目标由任务配置 (config/ss_task_binding.json → TASK-06-TRAY) 决定
  L4 保安全   → ss.safety.saturate (A_LIMIT=0.6m/s) + 动作调制器否决权 (残差 > veto → 减速/重试)
  L3 编流程   → 八阶段链 接近→对位→下降→抓取→抬起→转移→放入→完成 (ActionModulator mode="tray")
  L2 操作     → ss.perception(43D)/est/dyn/world/cognition + 原子技能 SK01-08 (⑦=放入 SK07Place)
  执行层      → ss.execr.execute → env.step  (仿真里 metaworld 就是执行器; 真机同口径走 L2 收口→MoveIt)

物理真实性:
  · 光模块 = MuJoCo 自由刚体; 抓起来后按**刚性手爪**钉在手上 (等效真机刚性夹爪 — 仿真摩擦夹持长
    距离必滑脱, 2026-09-10 已实锤), 释放后完全靠物理落进槽底。
  · 接触力取 MuJoCo 真实接触力 (mj_contactForce), 分 f_env(环境) / f_grasp(夹持) 两路。
  · 判据 (TASK-06-TRAY 配方): 单边 ≤1mm / 姿态 ≤1° — 逐颗报数, 不合格如实报。

用法:
  cd tools && MUJOCO_GL=egl gui-venv311/bin/python gen_tray_place_video.py [--seed 0] [--no-video]
      [--modules 3] [--params-json '{"place.angle_tol_deg":1.0}'] [--push]
输出: reports/tray_place_<ts>.mp4/.npz (+ tray_place_latest.*)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("MUJOCO_EGL_DEVICE", "0")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = (os.environ.get("ZMAX_L4_ROOT")
        or getattr(sys, "_MEIPASS", "")
        or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import numpy as np  # noqa: E402
import mujoco  # noqa: E402

from train_full_pipeline import get_obs  # noqa: E402
from state_space_sim import StateSpaceSim  # noqa: E402

A_LIMIT = 0.6          # 安全限幅 (m/s)
F_REF = 25.0           # 接触力归一化 (N)
GRASP_TH = 0.60        # 夹持/吸附建立阈值 (与插拔 episode 同值)
H_APPROACH, H_ALIGN, H_GRASP_POSE, H_LIFT = 0.10, 0.055, 0.022, 0.16
PLACE_HOVER = 0.06     # 槽位上方悬停高度
H_VAC_PRESS = 0.004    # 吸嘴尖压到件顶面的距离 (真空工具的"下降/抓取"目标)
RELEASE_H = 0.0015     # 距落座 1.5mm 内才断真空 (实测 6mm 就放 → 落下时横向漂 2.2mm, 撞隔板)
# 🧲 TASK-06-TRAY 工艺 = **真空吸附取放** (配方原文: 「末端下降至吸附位, 真空建立(≤200ms)后抬起离盘」),
#    不是两指夹持 —— 真机用的是细吸嘴, 才能探进 24mm 高的盘壁.
#    仿真里 metaworld 只有两指夹爪 (指垫 30mm 高), 探进盘里必然撞壁 (实测卡在盘壁顶面 z=0.038)。
#    ⇒ 按真机语义建模**工具坐标 TCP**: 吸嘴尖端 = 手位 − 75mm; 手永远 ≥95mm (指垫底 36mm > 盘壁顶 32mm,
#      不碰壁), 吸嘴尖端可达件顶面 22mm。控制律/观测一律在 TCP 上算 (真机同口径: 控制的是工具尖端)。
TCP_OFF = np.array([0.0, 0.0, -0.075])
HAND_MIN_Z = 0.095     # 手位下限 (指垫不碰盘壁)
VAC_TOL_XY, VAC_TOL_Z = 0.004, 0.005   # 真空建立判据 (吸嘴对件顶面)
RENDER_EVERY = 4
# 🎥 视频机位: metaworld 的 env.render() 用构造时锁死的 corner2 (斜视), 摆盘件落进**深盘**后
#    在画面里只剩 ~9 像素/颗 —— 老倪"会把画面当结果", 这等于看不清。改用 MuJoCo 原生 Renderer
#    架一台**近俯视**相机对着作业区 (料盘+tray盘), 960×720: 盘内件一眼可见 (实测像素 ×20)。
# elevation 必须 ≈ -89.5°: -78° 时深盘(48mm 壁)会把盘内件挡住 (实测末帧金色像素=0); 正俯视才看得见
VIEW = {"size": (960, 720), "lookat": (0.0, 0.56, 0.02), "distance": 0.92,
        "azimuth": 90.0, "elevation": -89.5}
MAX_STEPS_MODULE = 2600
SETTLE_STEPS = 55      # 释放后退避 + 件落定
MODULES = (("peg", "", 0), ("peg2", "2", 1), ("peg3", "3", 2))
MODULE_NAMES = tuple(x[0] for x in MODULES)
TR_KEYS = ("t", "x", "peg", "peg_head", "gripper", "stage", "done", "dist", "u_ff", "u_sat",
           "residual", "contact_p", "force", "force_grasp", "target", "grasped", "obs",
           "u_ff_vec", "u_fb_vec", "u_fuse_vec", "u_limit_vec", "u_exec_vec", "latent_vec",
           "corrected_vec", "residual_vec", "z_k_vec", "v_vec", "prior_vec", "grip_lock")


def make_renderer(m):
    """近俯视原生渲染器 (不依赖 env.render 的固定机位)"""
    import mujoco
    # 模型自带离屏缓冲默认 480×480 (metaworld), 直接开 960×720 会 ValueError: 先放大缓冲
    m.vis.global_.offwidth = int(VIEW["size"][0])
    m.vis.global_.offheight = int(VIEW["size"][1])
    ren = mujoco.Renderer(m, height=VIEW["size"][1], width=VIEW["size"][0])
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.lookat[:] = VIEW["lookat"]
    cam.distance = VIEW["distance"]
    cam.azimuth = VIEW["azimuth"]
    cam.elevation = VIEW["elevation"]
    return ren, cam


def _layout_objs():
    """摆盘真源 objects 列表 (sim_scene_def._tray_layout) — 模块半高等几何从这里取"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import sim_scene_def as SSD
    return SSD._tray_layout()["objects"]


def _mw_assets():
    import metaworld as _mw
    return os.path.join(os.path.dirname(os.path.abspath(_mw.__file__)), "assets")


XML = os.path.join(_mw_assets(), "sawyer_xyz", "sawyer_tray_place.xml")


def scene_truth():
    """摆盘几何真源 (与页内 3D 视图同一份): 模块位 + 槽位落点 + 落座高度"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import sim_scene_def as SSD
    d = SSD._tray_layout()
    mods, slots = [], []
    for o in d["objects"]:
        if o["name"].startswith("光模块"):
            mods.append([float(v) for v in o["center"]])
    for m in d["markers"]:
        if "槽位" in m["name"]:
            slots.append([float(v) for v in m["pos"]])
    mods.sort(key=lambda x: x[1])
    slots.sort(key=lambda x: x[1])
    inner_top = max((float(o["center"][2]) + float(o["size"][2]) / 2.0)
                    for o in d["objects"] if "内底" in o["name"])
    half_h = max(float(o["size"][2]) for o in d["objects"] if o["name"].startswith("光模块")) / 2.0
    return mods, slots, inner_top + half_h


from metaworld.envs.sawyer_peg_insertion_side_v3 import SawyerPegInsertionSideEnvV3  # noqa: E402


class TrayEnv(SawyerPegInsertionSideEnvV3):
    @property
    def model_name(self):
        return XML

    def reset_model(self):
        """摆盘场景的复位: 没有「带孔盒」(box) —— 父类 reset_model 会 `model.body("box")` KeyError。

        摆盘语义: 3 颗光模块**固定放在料盘**(真源坐标, 不随机撒点), 目标点 = tray 槽位 1;
        臂初始位形仍走父类 `_reset_hand()` (随机化保留, 与插拔同款起手)。
        """
        self._reset_hand()
        mods, slots, rest_z = scene_truth()
        self.peg_init_pos = [np.array([m[0], m[1], rest_z], dtype=float) for m in mods]
        self.obj_init_pos = self.peg_init_pos[0].copy()
        for (body, _sfx, _s), p in zip(MODULES, self.peg_init_pos):
            pin_module(self, body, p)
        self.peg_head_pos_init = self._get_site_pos("pegHead")
        self._target_pos = np.array([slots[0][0], slots[0][1], rest_z], dtype=float)
        self.model.site("goal").pos = self._target_pos
        self.objHeight = float(rest_z)
        self.heightTarget = self.objHeight + self.liftThresh
        return self._get_obs()

    def evaluate_state(self, obs, action):
        """摆盘没有「带孔盒」—— 父类的插孔奖励要读 box 的碰撞角点 site (会 KeyError)。

        本工程不用 metaworld 奖励 (判据在 runner 侧按 TASK-06-TRAY 配方算), 这里只保持
        接口形状: `件头 → 目标槽位` 的欧氏距离当 in_place 证据。
        """
        peg = self._get_site_pos("pegGrasp")
        slot = np.array([self._target_pos[0], self._target_pos[1], self.objHeight], dtype=float)
        obj_to_target = float(np.linalg.norm(peg - slot))
        in_place = obj_to_target <= 0.02
        reward = 1.0 if in_place else 0.0
        info = {"success": float(in_place), "near_object": float(np.linalg.norm(peg - slot)),
                "grasp_success": 1.0 if (obs[3] if np.ndim(obs) else 0) < 0.5 else 0.0,
                "grasp_reward": 0.0, "in_place_reward": reward, "obj_to_target": obj_to_target,
                "unscaled_reward": reward}
        return reward, info


def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = TrayEnv(render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    env.max_path_length = 200000
    env._grip_yaw = 0.0
    return env


def _has_body(m, name):
    try:
        m.body(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def site(m, d, name):
    return np.array(d.site_xpos[m.site(name).id], dtype=float)


def body_xyz(m, d, name):
    return np.array(d.xpos[m.body(name).id], dtype=float)


def yaw_deg(v):
    return math.degrees(math.atan2(v[1], v[0]))


def body_yaw_deg(m, d, name):
    xm = d.xmat[m.body(name).id].reshape(3, 3)
    a = xm[:, 0].copy()
    a[2] = 0.0
    return yaw_deg(a)


def hand_yaw_deg(m, d):
    """手部 yaw 取局部 **Z 轴**投影 (2026-09-10 实锤: 取局部 X 轴 = 旋转轴自身 → atan2 噪声 ±180°)"""
    xm = d.xmat[m.body("hand").id].reshape(3, 3)
    a = xm[:, 2].copy()
    a[2] = 0.0
    if float(np.linalg.norm(a)) < 1e-9:
        return 0.0
    return yaw_deg(a)


def yaw_quat(deg):
    r = math.radians(deg) / 2.0
    return np.array([math.cos(r), 0.0, 0.0, math.sin(r)])


def pin_module(env, body, pos, quat=None):
    """把件钉到指定位姿 (吸附/刚性夹持的等效): 设 qpos **并清 qvel**。

    ⚠️ 只设 qpos 不清 qvel ⇒ 自由关节的速度还在累积 (每步 -9.81*ctrl_dt), 件会越掉越深 ——
    实测「钉 0.35 却读到 0.343」, 抬起目标追活件时直接飞车。清速度后位姿严格跟随。
    """
    m, d = env.model, env.data
    jid = m.body_jntadr[m.body(body).id]
    adr = m.jnt_qposadr[jid]
    vadr = m.jnt_dofadr[jid]
    d.qpos[adr:adr + 3] = pos
    if quat is not None:
        d.qpos[adr + 3:adr + 7] = quat
    d.qvel[vadr:vadr + 6] = 0.0
    mujoco.mj_forward(m, d)


def contact_forces(m, d, peg_ids, hand_ids, table_ids=frozenset()):
    f_env = f_grasp = 0.0
    f6 = np.zeros(6)
    watched = set(peg_ids) | set(hand_ids)
    for i in range(d.ncon):
        c = d.contact[i]
        b1, b2 = int(m.geom_bodyid[c.geom1]), int(m.geom_bodyid[c.geom2])
        if b1 not in watched and b2 not in watched:
            continue
        mujoco.mj_contactForce(m, d, i, f6)
        mag = float(np.linalg.norm(f6[:3]))
        pair = {b1, b2}
        if pair & set(peg_ids) and pair & set(hand_ids):
            f_grasp += mag
        elif pair <= set(hand_ids):
            continue
        elif pair & set(peg_ids) and pair & set(table_ids):
            continue
        else:
            f_env += mag
    return f_env, f_grasp


def run_module(env, ss, mod_i, cfg, log=print, record=True, frames=None, rend=None):
    """一颗光模块: 八阶段链 (mode=tray) 全由状态空间六层算动作"""
    m, d = env.model, env.data
    body, sfx, slot_i = MODULES[mod_i]
    grasp_site, head_site = "pegGrasp" + sfx, "pegHead" + sfx
    mods, slots, rest_z = scene_truth()
    slot = np.array([slots[slot_i][0], slots[slot_i][1], rest_z], dtype=float)
    hand_ids = {int(m.body(n).id) for n in
                ("hand", "rightclaw", "leftclaw", "rightpad", "leftpad",
                 "right_hand", "right_wrist") if _has_body(m, n)}
    table_ids = {int(m.body(n).id) for n in ("tablelink", "table") if _has_body(m, n)}
    peg_ids = {int(m.body(body).id)}

    ctrl_dt = float(m.opt.timestep) * int(env.frame_skip)
    a_gain = ctrl_dt / float(env.action_scale)
    sched = ss.cognition.ActionModulator(grasp_th=GRASP_TH, mode="tray")
    ss.sched = sched
    o = get_obs(env)
    hand = np.array(o[0:3], dtype=float)
    v_est = np.zeros(3)
    latent = np.concatenate([hand + TCP_OFF, [0.0]])      # 状态 = 工具尖端 (TCP)
    u_prev = np.zeros(4)
    res_ema = prev18 = None
    vac = False                # 真空吸附已建立 (等效插拔链的"夹持建立")
    top0 = None                # 吸附时刻的件顶面 (抬起/转移目标必须锚定在**吸附点**, 不能跟活件走)
    released = False
    placed = False
    half_h = float(max(float(o_["size"][2]) for o_ in _layout_objs() if o_["name"].startswith("光模块"))) / 2.0
    mod_yaw0 = 0.0
    hand_yaw_ref = 0.0
    mod_z0 = float(rest_z)
    tr = {k: [] for k in TR_KEYS}
    settle_n = 0
    t_module = 0

    for step in range(MAX_STEPS_MODULE + SETTLE_STEPS):
        st = sched.stage()
        settling = st == "完成"
        # ── 真实状态 (全部来自 env; 控制/观测一律在**工具尖端 TCP** 上算) ──
        hand_new = np.array(o[0:3], dtype=float)
        tcp = hand_new + TCP_OFF
        v_est = (tcp - (hand + TCP_OFF)) / ctrl_dt if step else np.zeros(3)
        hand = hand_new
        peg_c = body_xyz(m, d, body)
        peg_head = site(m, d, head_site)
        gripper_raw = float(np.clip(1.0 - float(o[3]), 0.0, 1.0))
        # 吸附证据: 建立后 = 0.9 (>= grasp_th 0.6) —— 与插拔链的夹持证据同口径
        grip_ev = 0.9 if (vac and not released) else gripper_raw
        f_env, f_grasp = contact_forces(m, d, peg_ids, hand_ids, table_ids)
        force_norm = float(np.clip(f_env / F_REF, 0.0, 1.0))
        grasp_norm = float(np.clip(f_grasp / F_REF, 0.0, 1.0))
        force6 = np.zeros(6)
        force6[2] = f_env

        # ── 阶段子目标 (L3 流程; TCP 语义: 吸嘴尖 → 件顶面 → 抬 → 槽位上方 → 槽底) ──
        grasp_pt = site(m, d, grasp_site)
        top_pt = peg_c + np.array([0.0, 0.0, half_h])          # 件顶面 = 吸附位
        # ⚠️ 真空工具的"下降/抓取"目标 = 吸嘴尖贴到件顶面 (H_VAC_PRESS≈4mm),
        #    不是两指抓取位 (22mm) —— 那是指垫要跨在件两侧时的悬停高度
        h = {"接近": H_APPROACH, "对位": H_ALIGN, "下降": H_VAC_PRESS,
             "抓取": H_VAC_PRESS, "抬起": H_LIFT}.get(st)
        tcp_off_z = (tcp - hand)[2]                             # = TCP_OFF[2] (常量, 显式写出便于审计)
        anchor = top0 if top0 is not None else top_pt   # ⚠️ 吸附后一律锚定吸附点 (否则目标追着件跑 = 飞车)
        if h is not None:
            target = (top_pt if h == H_VAC_PRESS else anchor) + np.array([0.0, 0.0, h])
        elif st == "转移":
            target = np.array([slot[0], slot[1], anchor[2] + PLACE_HOVER])
        else:                                                   # 放入/放下/完成 → 件顶面到槽内落座高度
            target = np.array([slot[0], slot[1], rest_z + half_h])
        # 手位下限: 指垫底 36mm 必须高于盘壁顶 32mm ⇒ 手 >=95mm (靠 TCP 偏移把吸嘴送进盘里)
        if target[2] + abs(tcp_off_z) < HAND_MIN_Z:
            target = np.array([target[0], target[1], HAND_MIN_Z - abs(tcp_off_z)])

        # ── 感知: 43D obs (39D 视觉[含当前阶段目标] + 4D 触觉) ──
        cur18 = np.concatenate([tcp, [grip_ev], v_est, peg_c, slot, np.zeros(3), np.zeros(2)])
        prev = prev18 if prev18 is not None else cur18
        visual39 = np.concatenate([cur18, prev, target])
        tactile4 = np.array([grip_ev, 1.0 if force_norm > 0.05 else 0.0, 0.0, 0.0])
        obs43 = ss.perception.fuse_sensors(visual39, force6, tactile4)
        prev18 = cur18

        # ── 六层链路 (与画布完全一致) ──
        u_ff = ss.accel.forward(obs43)
        act4 = np.concatenate([u_prev[:3], [0.0]])
        latent_pred = ss.est.predict(latent, act4)
        prior = ss.dyn.predict(latent, act4)
        z_k = np.concatenate([ss.world.observe(tcp), [force_norm]])
        corrected, residual = ss.cognition.state_correction(prior, z_k, K=0.5)
        residual = np.asarray(residual, dtype=float).copy()
        residual[3] = force_norm
        r_scalar = float(np.linalg.norm(residual))
        contact_p = float(ss.cognition.contact_probability(r_scalar, gain=8.0))
        _cw = ss.dyn.contact_of(obs43[:39], act4)
        if _cw is not None:
            contact_p = max(contact_p, _cw)
        latent = ss.est.update(latent_pred, corrected)
        res_ema = (0.85 * res_ema + 0.15 * residual) if res_ema is not None else residual.copy()
        u_fb = np.concatenate([np.clip(0.5 * res_ema[:3], -0.5, 0.5), [0.0]])
        u, stage_txt = sched.decide(u_ff, u_fb, contact_p, r_scalar)
        if np.ndim(u) == 0:
            u = np.zeros(4)
        u = np.asarray(u, dtype=float).copy()
        # 真空工具: 夹爪全程张开 (u[3]=0), "夹持"由吸附证据 grip_ev 表达 (见上)
        u[3] = 0.0
        u_sat = np.asarray(ss.safety.saturate(u, limit=A_LIMIT), dtype=float).copy()
        u_sat[3] = u[3]
        u_exec = np.asarray(ss.execr.execute(u_sat), dtype=float)
        if u_exec.ndim == 0:
            u_exec = np.zeros(4)
        u_prev = u_exec.copy()
        if settling:                                  # 完成段: 沿 z 抬离 (件留槽里)
            u_exec = np.array([0.0, 0.0, 0.12, 0.0])
        action = np.zeros(4)
        action[:3] = np.clip(u_exec[:3] * a_gain, -1.0, 1.0)
        action[3] = -1.0                               # 真空工具: 指爪恒张开 (-1=开)

        # ── 真空吸附: 建立后件顶面钉在吸嘴尖 (位置 + yaw 跟随) ──
        if vac and not released:
            pin_module(env, body, tcp - np.array([0.0, 0.0, half_h]),
                       yaw_quat(mod_yaw0 + (hand_yaw_deg(m, d) - hand_yaw_ref)))
        env.step(action)
        o = get_obs(env)

        # ── 真实证据 → 八阶段推进 ──
        peg_now = body_xyz(m, d, body)
        head_now = site(m, d, head_site)
        grasp_pt_now = site(m, d, grasp_site)
        top_now = peg_now + np.array([0.0, 0.0, half_h])
        d_tcp = float(np.linalg.norm(tcp[:2] - top_now[:2]))
        dist_h = float(np.linalg.norm(peg_now[:2] - slot[:2]))
        lifted = float(peg_now[2] - mod_z0)
        # 真空建立: 吸嘴尖到达件顶面之上 VAC_TOL_Z 内 且 xy 对准 → 吸附
        if (not vac) and (not released) and st in ("下降", "抓取") \
                and d_tcp < VAC_TOL_XY and abs(tcp[2] - top_now[2]) < VAC_TOL_Z:
            vac = True
            top0 = top_now.copy()
            mod_yaw0 = body_yaw_deg(m, d, body)
            hand_yaw_ref = hand_yaw_deg(m, d)
            log(f"    🧲 真空建立 (吸嘴尖 z={tcp[2]:.4f} ← 件顶面 z={top_now[2]:.4f}, "
                f"xy 偏差 {d_tcp*1000:.2f}mm, ≤200ms) → 吸附锁")
        placed_now = bool(released and abs(peg_now[2] - rest_z) < 0.004
                          and float(np.linalg.norm(peg_now[:2] - slot[:2])) < 0.004)
        if (not released) and vac and st in ("放入", "放下") and abs(peg_now[2] - rest_z) < RELEASE_H:
            released = True
            log(f"    🔓 断真空释放 (件心 z={peg_now[2]:.4f} → 落座 {rest_z:.4f})")
        sched.advance(contact_p=contact_p, dist_h=dist_h, gripper=grip_ev, d_xy=d_tcp,
                      lifted=lifted, at_grasp_pose=bool(
                          d_tcp < 0.006 and abs(tcp[2] - top_now[2]) < VAC_TOL_Z
                      ) or grasp_norm > 0.02,
                      # 吸附力: 真空模型 (无实体吸嘴几何) → 建立后给名义值, 否则用真实接触力
                      grasp_force=float(5.0 if (vac and not released) else f_grasp),
                      peg_z=float(head_now[2]),
                      peg_z_grasp=float(mod_z0), placed=placed_now)
        done = sched.stage() == "完成"
        placed = placed or placed_now

        if record:
            tr["t"].append(round(t_module * ctrl_dt, 4))
            tr["x"].append(hand.copy())
            tr["peg"].append(peg_now.copy())
            tr["peg_head"].append(head_now.copy())
            tr["gripper"].append(grip_ev)      # 吸附证据 (真空工具: 无指爪闭合)
            tr["stage"].append(stage_txt)
            tr["done"].append(done)
            tr["dist"].append(dist_h)
            tr["u_ff"].append(float(np.linalg.norm(u_ff[:3])))
            tr["u_sat"].append(float(np.linalg.norm(u_sat[:3])))
            tr["residual"].append(r_scalar)
            tr["contact_p"].append(contact_p)
            tr["force"].append(force_norm)
            tr["force_grasp"].append(grasp_norm)
            tr["target"].append(target.copy())
            tr["grasped"].append(bool(vac and not released))
            tr["grip_lock"].append(bool(vac and not released))   # 键名沿用 (吸附锁=插拔链的夹持锁)
            tr["obs"].append(np.asarray(obs43, dtype=float).copy())
            tr["u_ff_vec"].append(np.asarray(u_ff, dtype=float).copy())
            tr["u_fb_vec"].append(np.asarray(u_fb, dtype=float).copy())
            tr["u_fuse_vec"].append(np.asarray(u, dtype=float).copy())
            tr["u_limit_vec"].append(np.asarray(u_sat, dtype=float).copy())
            tr["u_exec_vec"].append(np.asarray(u_exec, dtype=float).copy())
            tr["latent_vec"].append(np.asarray(latent, dtype=float).copy())
            tr["corrected_vec"].append(np.asarray(corrected, dtype=float).copy())
            tr["residual_vec"].append(np.asarray(residual, dtype=float).copy())
            tr["z_k_vec"].append(np.asarray(z_k, dtype=float).copy())
            tr["v_vec"].append(np.asarray(v_est, dtype=float).copy())
            tr["prior_vec"].append(np.asarray(prior, dtype=float).copy())
        if frames is not None and step % RENDER_EVERY == 0:
            if rend[0] is None:
                rend[0], rend[1] = make_renderer(m)
            rend[0].update_scene(d, camera=rend[1])
            frames.append(rend[0].render())
        t_module += 1
        if done and released:
            settle_n += 1
            if settle_n >= SETTLE_STEPS:
                break

    # ── 判据 (TASK-06-TRAY): 单边 ≤1mm / 姿态 ≤1° ──
    peg_f = body_xyz(m, d, body)
    yaw_f = body_yaw_deg(m, d, body)
    dx, dy, dz = (float(peg_f[0] - slot[0]), float(peg_f[1] - slot[1]), float(peg_f[2] - slot[2]))
    yaw_e = abs(((yaw_f + 180.0) % 360.0) - 180.0)
    ok = bool(placed and max(abs(dx), abs(dy)) <= 0.001 and yaw_e <= 1.0 and abs(dz) <= 0.004)
    judge = dict(module=body, slot=slot_i + 1, placed=bool(placed), released=bool(released),
                 dx_mm=dx * 1000, dy_mm=dy * 1000, dz_mm=dz * 1000, yaw_err_deg=yaw_e,
                 steps=len(tr["t"]), ok=ok,
                 stages=list(dict.fromkeys(tr["stage"])),
                 history=[f"{s}: {r}" for s, r in sched.history])
    return tr, judge


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--modules", type=int, default=3)
    ap.add_argument("--params-json", default="")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(a.params_json) if a.params_json.strip() else {}
    if not os.path.isfile(XML):
        raise SystemExit("⛔ 摆盘场景 XML 不存在: %s\n   先跑 tools/gen_tray_place_scene.py" % XML)
    mods, slots, rest_z = scene_truth()
    env = make_env(a.seed)
    m, d = env.model, env.data
    ss = StateSpaceSim(log=lambda *x: None)
    log = print
    log("🎯 摆盘 episode · 状态空间六层直接驱动 metaworld (mode=tray)")
    log(f"   场景 {os.path.basename(XML)} · 料盘 {len(mods)} 颗 → tray 盘 {len(slots)} 槽 · "
        f"落座 z={rest_z:.4f}")
    log(f"   任务配置覆盖: {json.dumps(cfg, ensure_ascii=False) if cfg else '—(无)'}")
    for i, (body, _sfx, _s) in enumerate(MODULES):
        pin_module(env, body, np.array([mods[i][0], mods[i][1], rest_z]))
    mujoco.mj_forward(m, d)
    frames = None if a.no_video else []
    rend = [None, None]          # [Renderer, MjvCamera] 惰性建 (第一条 episode 首帧时)
    tr_all = {k: [] for k in TR_KEYS}
    judges = []
    t0 = time.time()
    for i in range(min(a.modules, len(MODULES))):
        log(f"  ── 第 {i+1} 颗 ({MODULE_NAMES[i]}) ──")
        tr, judge = run_module(env, ss, i, cfg, log=log, frames=frames, rend=rend)
        for k in tr_all:
            tr_all[k].extend(tr[k])
        judges.append(judge)
        log(f"    → 槽{judge['slot']}: Δxy=({judge['dx_mm']:+.2f},{judge['dy_mm']:+.2f})mm "
            f"Δz={judge['dz_mm']:+.2f}mm · 姿态 {judge['yaw_err_deg']:.2f}° · "
            f"{'✅ 合格' if judge['ok'] else '⚠️ 不合格'} ({judge['steps']} 步)")
        for h in judge["history"]:
            log(f"      {h}")
    dt = time.time() - t0
    ok_n = sum(1 for j in judges if j["ok"])
    log(f"\n📊 摆盘汇总: {ok_n}/{len(judges)} 颗合格 · 合计 {len(tr_all['t'])} 步 · {dt:.1f}s")
    meta = dict(seed=a.seed, scene=os.path.basename(XML), mode="tray", params=cfg,
                placed=ok_n, total=len(judges), steps=len(tr_all["t"]), rest_z=rest_z,
                judges=[{k: (round(v, 5) if isinstance(v, float) else v)
                         for k, v in j.items() if k != "history"} for j in judges],
                history=[h for j in judges for h in j["history"]])
    out = save(tr_all, meta, frames)
    log(f"✅ trace: {out.get('latest') or out['npz']} ({meta['steps']} 步)")
    if "mp4" in out:
        log(f"🎬 视频: {out['mp4']} ({len(frames)} 帧, 与 trace 同一条 episode)")
    if a.push:
        import subprocess
        txt = ("🧩 Z-MAX 摆盘 (状态空间自驱) " + time.strftime("%m-%d %H:%M") + "\n"
               "任务: TASK-06-TRAY · 链 接近→对位→下降→抓取→抬起→转移→放入→完成\n"
               "结果: %d/%d 颗落进 tray 槽位\n" % (ok_n, len(judges))
               + "\n".join("  · %s → 槽%d: Δxy=(%+.2f,%+.2f)mm Δz=%+.2fmm 姿态%.2f° %s"
                           % (j["module"], j["slot"], j["dx_mm"], j["dy_mm"], j["dz_mm"],
                              j["yaw_err_deg"], "✅" if j["ok"] else "⚠️") for j in judges)
               + "\n判据: 单边≤1mm / 姿态≤1° · 视频 " + os.path.basename(out.get("mp4") or out["npz"]))
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "feishu_send.py"), txt],
                       check=False)
        log("📨 已推飞书")
    return 0 if ok_n == len(judges) else 3


def save(tr, meta, frames, tag=None):
    rep = os.path.join(ROOT, "reports")
    os.makedirs(rep, exist_ok=True)
    tag = tag or time.strftime("%Y%m%d_%H%M%S")
    arrs = {k: np.asarray(v, dtype=object if k == "stage" else float) for k, v in tr.items()}
    meta = dict(meta)
    meta["episode_tag"] = tag
    npz = os.path.join(rep, f"tray_place_{tag}.npz")
    np.savez_compressed(npz, meta=np.array([meta], dtype=object), **arrs)
    out = {"npz": npz}
    if frames:
        import shutil
        import subprocess
        import tempfile
        import cv2
        tmp = tempfile.mkdtemp(prefix="tray_")
        for i, fr in enumerate(frames):
            cv2.imwrite(os.path.join(tmp, f"f{i:05d}.png"),
                        cv2.cvtColor(np.asarray(fr), cv2.COLOR_RGB2BGR))
        mp4 = os.path.join(rep, f"tray_place_{tag}.mp4")
        subprocess.run(["ffmpeg", "-y", "-framerate", "25", "-i", os.path.join(tmp, "f%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                        "-loglevel", "error", mp4], check=True)
        shutil.copyfile(mp4, os.path.join(rep, "tray_place_latest.mp4"))
        shutil.copyfile(npz, os.path.join(rep, "tray_place_latest.npz"))
        shutil.rmtree(tmp, ignore_errors=True)
        out["mp4"] = mp4
        out["latest"] = os.path.join(rep, "tray_place_latest.mp4")
    return out


if __name__ == "__main__":
    sys.exit(main())
