#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_ds_to_lerobot.py —— 把 live_ds_collect.py 采的只读数据转成 **LeRobot 数据集**,
给 SmolVLA / ACT 这类模仿学习策略 (BC) 直接吃。

输入 (live_* 目录): steps.jsonl + frames/*.jpg
输出: LeRobot 数据集 (meta/info.json + data/*.parquet + images)

特征口径 (与真机 action 一致, 单位写死):
    observation.images.top  (480,640,3)  uint8   手臂/工位相机帧
    observation.state       (13,)        float32 [j1..j6(deg), x,y,z(mm), qx,qy,qz,qw]
    action                  (7,)         float32 [x,y,z(mm), a,b,c(deg), 夹爪(0=合/70=开)]
                                         —— 位姿**逐点取 215 点真值表**(tools/web/real_traj_joints.json),
                                         与真机执行的点位完全同源(实测 act_pose 与该表 p*1000 差 ≤0.005mm)

episode 切分: 时间断档 > GAP_S(默认 1.5s) 或 派单游标回退 ⇒ 新 episode。
用法:
    python3 tools/live_ds_to_lerobot.py --src zmax_data/datasets/live_1115_150119 \
            --repo-id zmax/live_1115 --out zmax_data/datasets/lerobot
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.expanduser("~/zmax")
GAP_S = 1.5


def _rows(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:                                           # noqa: BLE001
                    pass
    return out


def _grip_num(v):
    """夹爪归一: 数字原样; close/合→0; open/开→70; hold/其它 → None(沿用上一条)。"""
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if s in ("close", "合", "closed", "夹紧"):
        return 0.0
    if s in ("open", "开", "opened", "张开"):
        return 70.0
    return None


TRAJ_JSON = os.path.join(ROOT, "tools", "web", "real_traj_joints.json")


def _load_traj215():
    """215 点真值表 → [{x,y,z(mm), a,b,c(deg)}, ...]; 取不到就返回 []（调用方回退）。"""
    try:
        import numpy as np
        from scipy.spatial.transform import Rotation as R
    except Exception:                                                       # noqa: BLE001
        return []
    try:
        fr = json.load(open(TRAJ_JSON))["frames"]
    except Exception:                                                       # noqa: BLE001
        return []
    out = []
    for f in fr:
        p = np.asarray(f["p"], dtype=float) * 1000.0        # m → mm
        e = R.from_quat(f["q"]).as_euler("xyz", degrees=True)   # 与执行器 a/b/c 同约定(实测逐位一致)
        out.append([float(p[0]), float(p[1]), float(p[2]),
                    float(e[0]), float(e[1]), float(e[2])])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--repo-id", default="")
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data/datasets/lerobot"))
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--overwrite", action="store_true", help="目标目录已存在就删掉重来")
    ap.add_argument("--task", default="光模块 215 点放料插拔", help="任务描述 (LeRobot 的 task 字段)")
    ap.add_argument("--size", type=int, default=128, help="图像边长 (默认 128, 与 policy.resize_images_to 一致; 0=保持原图)")
    a = ap.parse_args()
    src = a.src if os.path.isabs(a.src) else os.path.join(ROOT, a.src)
    rows = _rows(os.path.join(src, "steps.jsonl"))
    if a.limit:
        rows = rows[:a.limit]
    if not rows:
        print("[conv] 没有样本"); return 1
    repo = a.repo_id or ("zmax/" + os.path.basename(os.path.normpath(src)))
    TASK = a.task
    sys.path.insert(0, os.path.join(ROOT, "src"))
    # 🐛 本机 bundled FFmpeg 没有 libsvtav1 (VideoEncoderConfig 的默认 vcodec) ⇒ create() 直接抛
    #    ValueError。我们这版只写图片(use_videos=False), 把默认编码器改成实机可用的 libx264 即可。
    try:
        from lerobot.configs import video as _vcfg
        # 直接把"编码器可用性检查"打成 no-op (本版只写图片, 不走 ffmpeg)
        _vcfg.VideoEncoderConfig.validate = lambda self: None      # validate() 里是函数内 import, 只能整块打掉
        _d = _vcfg.VideoEncoderConfig.__dataclass_fields__
        _d["vcodec"].default = "libx264"
        _d["vcodec"].default_factory = None
    except Exception as _e:                                                 # noqa: BLE001
        print("[conv] 视频编码器补丁失败(不影响图片数据集): %r" % (_e,), flush=True)
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    import numpy as np
    from PIL import Image

    SZ = int(a.size) if int(a.size) > 0 else 0
    _img_shape = (SZ, SZ, 3) if SZ else (480, 640, 3)
    feats = {
        "observation.images.top": {"dtype": "image", "shape": _img_shape,
                                   "names": ["height", "width", "channels"]},
        "observation.state": {"dtype": "float32", "shape": (13,),
                              "names": ["j1", "j2", "j3", "j4", "j5", "j6",
                                        "x", "y", "z", "qx", "qy", "qz", "qw"]},
        "action": {"dtype": "float32", "shape": (7,),
                   "names": ["x", "y", "z", "a", "b", "c", "grip"]},
    }
    root = os.path.join(a.out, repo.replace("/", "_"))
    if os.path.isdir(root) and a.overwrite:
        import shutil
        shutil.rmtree(root)
        print("[conv] 清掉旧目录 %s" % root, flush=True)
    ds = LeRobotDataset.create(repo_id=repo, fps=a.fps, features=feats, root=root,
                              use_videos=False)
    print("[conv] 输出 → %s (repo=%s)" % (root, repo), flush=True)

    grip_hold = 70.0
    traj215 = _load_traj215()
    prev_abc = None
    fb = 0
    print("[conv] 215 点真值表: %d 点 (%s)" % (len(traj215), "已加载" if traj215 else "缺失 ⇒ 姿态回退"),
          flush=True)
    ep = 0
    kept = 0
    prev_ts = None
    for r in rows:
        fr = r.get("frame")
        ap_pose = r.get("act_pose")
        st = (r.get("joints") or []) + (r.get("pose") or [])
        if not fr or not ap_pose or len(st) != 13:
            continue
        p = os.path.join(src, fr)
        if not os.path.isfile(p):
            continue
        g = _grip_num(r.get("act_grip"))
        if g is None:
            g = grip_hold
        grip_hold = g
        ts = r.get("ts") or 0.0
        if prev_ts is not None and (ts - prev_ts) > GAP_S:
            ds.save_episode()
            ep += 1
            print("[conv] episode %d 完成" % ep, flush=True)
        prev_ts = ts
        img = Image.open(io.BytesIO(open(p, "rb").read())).convert("RGB")
        img = img.resize((SZ, SZ)) if SZ else img.resize((640, 480))
        img = np.array(img)
        # 🎯 action 7 维 = 215 点真值表该点的完整位姿 (x,y,z mm + a,b,c deg) + 夹爪
        #    act_i 是当时派单到 215 的第几点 ⇒ 直接取那一点的位姿, 与真机执行的点逐位同源。
        i_t = r.get("act_i")
        pose6 = None
        if traj215 and isinstance(i_t, int) and 0 <= i_t < len(traj215):
            pose6 = traj215[i_t]
        if pose6 is None:                       # 兜底: 只有 xyz 的时候沿用上一拍姿态(并记一次)
            _p = [float(ap_pose[0]), float(ap_pose[1]), float(ap_pose[2])]
            pose6 = _p + (prev_abc if prev_abc else [0.0, 0.0, 0.0])
            fb += 1
        else:
            prev_abc = pose6[3:6]
        ds.add_frame({"task": TASK,
                      "observation.images.top": img,
                      "observation.state": np.array(st, dtype="float32"),
                      "action": np.array([float(pose6[0]), float(pose6[1]), float(pose6[2]),
                                          float(pose6[3]), float(pose6[4]), float(pose6[5]),
                                          float(g)], dtype="float32")})
        kept += 1
    ds.save_episode()
    print("[conv] 完成: %d 帧 / %d episode → %s" % (kept, ep + 1, root), flush=True)
    print("[conv] 姿态来源: 215 点真值表 %d 帧, 回退 %d 帧" % (kept - fb, fb), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
