#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""光模块尺寸实测 (臂相机 + 手眼 + 内参)。

链: Orin ROS /robot/tcp_pose (pos+quat) → T_base_tool1
    ⊗ T_tool2cam (= inv(handeye 里的 T_cam2tool)) → T_base_cam
    → tool1 原点投到臂相机像素 → 围绕该点分割模块 → 尺度 = Z/f。

输出: /tmp/mod_measure.json (像素框/尺度/长宽高) + /tmp/mod_crop.png (标注图)
"""
import json, os, re, subprocess, sys
import numpy as np

REPO = os.path.expanduser("~/zmax")
NM = re.compile(r"-?\d+\.?\d*(?:e-?\d+)?")

def orin_pose(timeout=30):
    pre = ('source /opt/ros/humble/setup.bash 2>/dev/null; '
           'for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done; '
           'export ROS_DOMAIN_ID=0; ')
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "orin", "bash", "-lc",
                        pre + "timeout 8 ros2 topic echo --once /robot/tcp_pose"],
                       capture_output=True, text=True, timeout=timeout)
    txt = r.stdout
    def blk(name, keys):
        # yaml 风格: "position:" 之后缩进的 x/y/z(或 x/y/z/w) 各一行
        m = re.search(r"^\s*" + name + r":\s*$", txt, re.M)
        if not m: return None
        rest = txt[m.end():]
        vals = []
        for k in keys:
            mm = re.search(r"^\s+" + k + r":\s*(-?\d+\.?\d*(?:e-?\d+)?)", rest, re.M)
            if not mm: return None
            vals.append(float(mm.group(1)))
        return vals
    pos = blk("position", ["x", "y", "z"])
    ori = blk("orientation", ["x", "y", "z", "w"])
    return pos, ori

def q2R(x, y, z, w):
    n = w*w + x*x + y*y + z*z
    s = 2.0/n if n > 1e-12 else 0.0
    return np.array([
        [1-s*(y*y+z*z), s*(x*y-w*z),   s*(x*z+w*y)],
        [s*(x*y+w*z),   1-s*(x*x+z*z), s*(y*z-w*x)],
        [s*(x*z-w*y),   s*(y*z+w*x),   1-s*(x*x+y*y)]])

def main():
    pos, ori = orin_pose()
    if not pos or not ori:
        raise SystemExit("⛔ 读不到 /robot/tcp_pose 的 position/orientation")
    P_tool1 = np.array(pos, float) * 1000.0            # m → mm
    R_b2t = q2R(*ori)                                   # ROS xyzw
    print("TCP(mm) =", np.round(P_tool1, 2), " quat(xyzw) =", np.round(ori, 4))

    he = json.load(open(os.path.join(REPO, "models", "handeye_state.json")))
    Tc2t = np.array(he["T_cam2tool"], float)
    if np.abs(Tc2t[:3, 3]).max() < 10:                 # 米 → 毫米
        Tc2t[:3, 3] *= 1000.0
    T_t2c = np.linalg.inv(Tc2t)                        # 相机在 tool 系 → tool 在相机系
    print("手眼 |t| %.1fmm 残差 %.3fmm  用的是 inv(T_cam2tool)" %
          (np.linalg.norm(Tc2t[:3, 3]), he.get("resid_trans_mm_rms") or -1))

    cal = json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))
    K = np.array(cal["K"], float).reshape(3, 3)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    print("K: fx=%.2f fy=%.2f cx=%.2f cy=%.2f 图像=%s" % (fx, fy, cx, cy, cal.get("image_size")))

    # 口径(见 skill fixed-camera-ar-overlay): T_cam2tool 存的是"相机在 tool 系下的位姿"
    #   ⇒ p_tool = Tc2t · p_cam ; 相机原点(tool 系) = Tc2t[:3,3] ; 投 tool 点要用逆矩阵
    p_cam = T_t2c[:3, 3]                                   # tool1 原点在相机系
    cam_origin = P_tool1 + R_b2t @ Tc2t[:3, 3]             # 相机原点在 base 系
    R_c2b = R_b2t @ T_t2c[:3, :3]
    u = fx*p_cam[0]/p_cam[2] + cx
    v = fy*p_cam[1]/p_cam[2] + cy
    Z = float(np.linalg.norm(P_tool1 - cam_origin))
    print("tool1 投影像素 = (%.1f, %.1f)  相机↔tool1 = %.1fmm  尺度 %.3f mm/px" % (u, v, Z, Z/fx))

    out = {"tcp_mm": P_tool1.tolist(), "quat_xyzw": ori, "uv": [u, v], "Z_mm": Z,
           "mm_per_px": Z/fx, "K": [fx, fy, cx, cy],
           "tool1_axes_base": (R_b2t).T.tolist()}
    json.dump(out, open("/tmp/mod_measure.json", "w"), ensure_ascii=False, indent=1)
    print("落 /tmp/mod_measure.json")

if __name__ == "__main__":
    main()
