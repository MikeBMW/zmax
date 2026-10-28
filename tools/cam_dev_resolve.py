#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 **设备名 + 能力** 解析出该用哪个 /dev/videoN —— 别再预先固定索引。

现场根因 (2026-09-28): `tools/boot_restore.sh` 里预先固定 `--local-dev 2 --local2-dev 0`,
而本机 video2 是笔记本相机的 **GREY 640x360 (IR/灰度) 那一路** —— 没有红外照明时整幅近黑
(实测 mean=6.0 / median=0 / 96% 像素 <20); 而 VL 安全闸把 "local" 当**笔记本相机(全局视角)**:
快反射层判『遮挡/糊化』⇒ 所有运动类原子技能一律拒发 (老倪: 「原子技能又不好使了」)。
video0 才是同一台相机的 MJPG 彩色那一路 (实测 mean=112 / Laplacian=260), video4 是 MAXHUB 顶视。

用法:
    python3 tools/cam_dev_resolve.py          # 打印 LOCAL=<n> / LOCAL2=<n> (找不到给 -1)
    python3 tools/cam_dev_resolve.py --json   # 机器可读 + 每个候选设备的实测理由

判据(全部实测, 不猜):
  ① local  = 卡名含 "Integrated RGB" **且** 支持 MJPG (彩色)   ← 排除同名的 GREY(IR) 节点
  ② local2 = 卡名含 "MAXHUB"                                   ← 顶视
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

VID = "/sys/class/video4linux"


def _name(dev: str) -> str:
    try:
        with open(os.path.join(VID, dev, "name"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _formats(dev: str):
    """该设备支持的像素格式集合 (v4l2-ctl; 设备被占用也能查, 不需要独占)。"""
    try:
        r = subprocess.run(["v4l2-ctl", "-d", "/dev/" + dev, "--list-formats"],
                           capture_output=True, text=True, timeout=6)
        return set(re.findall(r"'([A-Z0-9 ]{3,8})'", r.stdout or ""))
    except Exception:                                                       # noqa: BLE001
        return set()


def _idx(path: str) -> int:
    m = re.search(r"(\d+)$", path)
    return int(m.group(1)) if m else -1


def _alive(dev: str):
    """实测"能不能出图"(不是只看格式表): 打开一次、连读 3 帧、判 mean/std。

    2026-10-22 现场: 笔记本内置相机被物理隐私开关关掉(camera_power=0 / privacy=1) —— 能 open、
    能读帧, 但**整幅全黑**(mean≈5)。只按卡名+MJPG 匹配会把它选成 local ⇒ 页面一格里永远是黑屏。
    所以判据必须落到像素上: 全黑/无对比 ⇒ 判不可用, 让位给外接 USB 相机。
    """
    try:
        import cv2
        cap = cv2.VideoCapture(int(str(dev).replace("video", "")), cv2.CAP_V4L2)
        if not cap.isOpened():
            return False, "无法打开(被占用/无权限)"
        ok, f = False, None
        for _ in range(3):
            ok, f = cap.read()
            if ok and f is not None:
                break
        cap.release()
        if not ok or f is None:
            return False, "读不到帧"
        m, s = float(f.mean()), float(f.std())
        if m < 12 or s < 8:
            return False, "全黑/无对比 mean=%.0f std=%.1f" % (m, s)
        return True, "mean=%.0f std=%.0f %dx%d" % (m, s, f.shape[1], f.shape[0])
    except Exception as e:                                                 # noqa: BLE001
        return False, "探测异常 %s" % type(e).__name__


def pick(prefer_rgb_name: str, prefer_top_name: str):
    devs = sorted(glob.glob(os.path.join(VID, "video*")), key=_idx)
    rows = []
    for p in devs:
        d = os.path.basename(p)
        fmts = _formats(d)
        ok, why = _alive(d) if fmts else (False, "无像素格式(纯 metadata 节点)")
        rows.append({"dev": d, "name": _name(d), "formats": sorted(fmts),
                     "alive": ok, "why": why})

    def _has_mjpg(r):
        return "MJPG" in r["formats"]

    def _ok(r):
        # 只要实测出图就算可用: 外接 USB 相机常只有 YUYV(没有 MJPG), 卡 MJPG 会把它判成"不在位"
        return bool(r["alive"])

    # ① 点名优先, 但必须**实测出图** (内置相机被隐私开关关掉时会在这里被跳过)
    local = next((r["dev"] for r in rows
                  if prefer_rgb_name.lower() in r["name"].lower() and _ok(r)), None)
    # ①.5 外接 USB 相机优先占 local 位 —— 老倪 2026-10-22「笔记本我也接了USB摄像头」:
    #     内置相机遇隐私开关/亮度不稳, 而 USB 是现场唯一稳定的一路; 内置仍可点 [内置] 换回。
    usb_alive = next((r["dev"] for r in rows
                      if any(k in r["name"].lower() for k in ("usb2.0 camera", "realsense"))
                      and _ok(r)), None)
    if usb_alive:
        local = usb_alive
    if local is None:                                          # ② 退一步: 任意彩色且实测出图
        local = next((r["dev"] for r in rows if _ok(r)), None)
    top = next((r["dev"] for r in rows
                if prefer_top_name.lower() in r["name"].lower() and _ok(r)
                and r["dev"] != local), None)
    return local, top, rows


def pick_usb(rows, prefer_usb_name: str, exclude: str = ""):
    """🎛 USB 摄像头 (2026-10-07 老倪外接): 卡名匹配 **且有像素格式**。

    坑: 很多 UVC 相机在同一物理设备上多暴露一个只有 metadata/无像素格式的节点 (实测 USB2.0 Camera
    的 video3 列不出任何格式, `VIDIOC_G_FMT` 直接 Invalid argument) —— 认卡名不认格式就会挑到它,
    打开后一帧都不出。所以这里必须要求 formats 里出现 MJPG/JPEG/YUYV。
    """
    def _cap(r):
        return any(f in ("MJPG", "JPEG", "YUYV") for f in r["formats"])
    keys = [k.strip().lower() for k in str(prefer_usb_name).split(",") if k.strip()]
    return next((r["dev"] for r in rows
                 if any(k in r["name"].lower() for k in keys) and _cap(r)
                 and r["dev"] != exclude), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rgb-name", default="Integrated RGB", help="笔记本彩色相机的卡名关键字")
    ap.add_argument("--top-name", default="MAXHUB", help="顶视相机的卡名关键字")
    ap.add_argument("--usb-name", default="USB2.0 Camera,RealSense",
                    help="外接 USB 摄像头的卡名关键字(逗号分隔多个, 任一命中即可; "
                         "实测本机外接 Intel RealSense D435 的卡名是 Intel(R) RealSense(TM) Depth Camera, "
                         "只认 'USB2.0 Camera' 会把它判成不在位)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    local, top, rows = pick(a.rgb_name, a.top_name)
    usb = pick_usb(rows, a.usb_name, exclude=local)
    n = lambda d: int(re.sub(r"\D", "", d)) if d else -1                          # noqa: E731
    if a.json:
        print(json.dumps({"local": n(local), "local2": n(top), "usb": n(usb), "cands": rows},
                         ensure_ascii=False, indent=1))
    else:
        print("LOCAL=%d" % n(local))
        print("LOCAL2=%d" % n(top))
        print("USB=%d" % n(usb))
    return 0 if local else 1


if __name__ == "__main__":
    sys.exit(main())
