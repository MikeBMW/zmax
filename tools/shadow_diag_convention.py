#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断: 手眼残差大到底是 (a)标定失效 (b)欧拉角约定不符 (c)相机不在臂上。
在**已录关键帧**上扫 4 种 rpy 约定 × 2 个位姿口径 (tcp/flange), 谁的残差最小谁就是真口径。
只读本地数据。
"""
import json, math, os, sys
import numpy as np, cv2

SESS = sys.argv[1]
K = np.array([[394.0623474121094, 0, 318.443603515625],
              [0, 393.472412109375, 238.658447265625], [0, 0, 1.0]])
XR = np.array(json.load(open("/home/ubuntu/zmax/models/handeye_state.json"))["T_cam2tool"], float)[:3, :3]


def R_zyx(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]) @ \
           np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ \
           np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])


def R_xyz(rx, ry, rz):        # 固定轴 X→Y→Z
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ \
           np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ \
           np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])


def R_xyz_intr(rx, ry, rz):   # 内旋 X→Y→Z = Rz·Ry·Rx  (与 ZYX 相同!)
    return R_zyx(rx, ry, rz)


def R_zyx_intr(rx, ry, rz):   # 内旋 Z→Y→X = Rx·Ry·Rz
    return np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]]) @ \
           np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]]) @ \
           np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])


CONV = {"ZYX(RzRyRx)": R_zyx, "XYZ_fixed(RxRyRz)": R_xyz, "ZYX_intr(RxRyRz)反序": R_zyx_intr}


def ang(R):
    return math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(R)) - 1) / 2))))


def main():
    kfs = [json.loads(l) for l in open(os.path.join(SESS, "keyframes.jsonl"), encoding="utf-8")]
    kfs = [k for k in kfs if k.get("tcp")]
    print("keyframes:", len(kfs))
    orb = cv2.ORB_create(3000)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    feats = {}
    def ft(f):
        p = os.path.join(SESS, "frames", f)
        if p in feats: return feats[p]
        im = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        r = orb.detectAndCompute(im, None) if im is not None else (None, None)
        feats[p] = (r[0], r[1], im)
        return feats[p]

    pairs = []
    for i in range(len(kfs) - 1):
        a, b = kfs[i], kfs[i + 1]
        fa, fb = ft(a["file"]), ft(b["file"])
        if fa[1] is None or fb[1] is None: continue
        if fa[2] is not None and fb[2] is not None:
            chg = float((np.abs(fa[2].astype(np.int16) - fb[2].astype(np.int16)) > 20).mean())
        else:
            chg = 0
        if chg < 0.08: continue
        m = sorted(bf.match(fa[1], fb[1]), key=lambda x: x.distance)[:600]
        if len(m) < 80: continue
        p1 = np.float32([fa[0][x.queryIdx].pt for x in m]); p2 = np.float32([fb[0][x.trainIdx].pt for x in m])
        E, inl = cv2.findEssentialMat(p1, p2, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
        if E is None or E.shape != (3, 3): continue
        if int((inl > 0).sum()) < 100: continue
        _, Rc, _, _ = cv2.recoverPose(E, p1, p2, K)
        if ang(Rc) < 2: continue
        pairs.append((a, b, Rc, chg))
    print("usable image pairs:", len(pairs))
    for kind in ("tcp", "flange"):
        for name, fn in CONV.items():
            res = []
            for a, b, Rc, _ in pairs:
                pa, pb_ = a.get(kind), b.get(kind)
                if not pa or not pb_: continue
                dR = fn(*pa[3:]).T @ fn(*pb_[3:])
                if ang(dR) < 5: continue
                pred = XR.T @ dR @ XR
                res.append(ang(pred.T @ Rc))
            if res:
                print("%-8s %-22s n=%3d  median=%5.1f°  p25=%5.1f°  p75=%5.1f°"
                      % (kind, name, len(res), np.median(res), np.percentile(res, 25), np.percentile(res, 75)))


if __name__ == "__main__":
    sys.exit(main())
