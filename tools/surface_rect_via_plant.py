#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""surface_rect_via_plant.py — 摆正后交给**工控机的 YOLO** 检测 (2026-10-20 老倪: 「用工控机的yolo不行么」)

为什么不自己加载模型: 权重是加密的 besthousing_zh0128.pt.enc, 解密器 yolo_detector 只在工控机;
本机既无模块也无权重。⇒ 正确做法是**借工控机的检测能力**, 通过 agent_hub 反向通道在工控机上跑。

为什么转**整幅图**而不送裁剪图: 工控机 YOLO 训练输入是「全幅 letterbox 1280x1280」,
   送 1282x188 的长条裁剪图 = 输入分布变了(实测那个模型对环境/尺度敏感)。
   所以绕模块中心把整幅 2448x2048 旋正, 让模块水平, 画幅不变 ⇒ 最接近它训练时的样子。
"""
from __future__ import annotations

import base64
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from aoi_surface_rect import surface_roi                        # noqa: E402
from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality  # noqa: E402

BASE = os.environ.get("ZMAX_SURFACE_AOI_URL", "http://192.168.23.23:10083").rstrip("/")
DELIVER = os.path.join(ROOT, "zmax_data/aoi_v4/deliver")       # agent_hub 的静态根
STAMP = time.strftime("%Y%m%d_%H%M%S")


def rotate_full(bgr, rect):
    """绕模块中心把整幅图旋正(长边水平), 画幅不变。返回 (rot, 实际旋转角)。"""
    cx, cy = float(rect["cx"]), float(rect["cy"])
    w, h = float(rect["w"]), float(rect["h"])
    ang = float(rect["angle"])
    if w < h:                       # minAreaRect 的 (w,h) 与 angle 约定: 让长边落到 x 轴
        w, h, ang = h, w, ang + 90.0
    M = cv2.getRotationMatrix2D((float(cx), float(cy)), float(ang), 1.0)
    rot = cv2.warpAffine(bgr, M, (bgr.shape[1], bgr.shape[0]),
                         flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    return rot, float(ang)


def set_expo(us, gain=1.8, settle=2.6):
    """切曝光并等它真生效(技能: 改完首帧可能仍是旧档 ⇒ 多等一帧)。"""
    try:
        body = urllib.request.urlopen(urllib.request.Request(
            "%s/exposure?us=%d&gain=%s" % (BASE, int(us), gain), method="POST",
            headers={"User-Agent": "zmax-probe"}), timeout=30).read()
        time.sleep(settle)
        return json.loads(body)
    except Exception as e:                                          # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}


def enqueue_ps(ps):
    r = subprocess.run([os.path.join(ROOT, "gui-venv311/bin/python"),
                        os.path.join(ROOT, "tools/agent_hub.py"), "--enqueue", ps],
                       capture_output=True, text=True, timeout=90, cwd=ROOT)
    return (r.stdout or "").strip()[:120]


def newest_out_mtime():
    outs = glob.glob(os.path.join(ROOT, "zmax_data/agent_hub/out/*.txt"))
    return max((os.path.getmtime(p) for p in outs), default=0.0)


def wait_out(marker="RESULT_JSON", tries=15, gap=12, after=0.0):
    """只看 **入队之后** 新产生的输出 —— 否则会读到上一轮的 RESULT_JSON 冒充这一次
    (2026-10-20 踩过: 拿到的是上一次 probe 的 saved_incoming=000124, 而当时已 00:02)。"""
    for _ in range(tries):
        time.sleep(gap)
        fresh = [p for p in glob.glob(os.path.join(ROOT, "zmax_data/agent_hub/out/*.txt"))
                 if os.path.getmtime(p) > after]
        if not fresh:
            continue
        for p in sorted(fresh, key=os.path.getmtime, reverse=True):
            txt = open(p, encoding="utf-8", errors="replace").read()
            if marker in txt or "Traceback" in txt:
                return p, txt
    return None, ""


def main():
    os.makedirs(DELIVER, exist_ok=True)
    sq = SurfaceOpticalQuality()
    expo = sq.exposure()

    # ── 双曝光: 48000us 下 Otsu 前景率=1.000, 模块与台面糊成一片(最大候选 1717x1269 是台面),
    #    搜不出模块; 5000us 下背景全黑, 能干净搜到 1123x188(aspect 5.97)。
    #    ⇒ ① 低曝光定几何 ② 正常曝光取像素(工控机 YOLO 认的是正常曝光分布) ③ 同角度旋转。
    # 2026-10-20 按 ROI 扫档实测(不是整帧): 死白率随曝光单调恶化 —— 5000us 19.37% / 8000 64.86% /
    #   12000 76.11% / 48000 90.74%; 降到 3000us 才有 1.72%(mean 110 仍有细节, 清晰度 44.6)。
    #   ⇒ 取像素用 3000us(不过曝的光模块, 老倪要求), 几何仍在 5000us 下搜(对比强, 搜得干净)。
    LOW_US, GOOD_US = 5000, 3000
    print("① 低曝光 %dus 定几何…" % LOW_US)
    set_expo(LOW_US)
    im_low = sq.capture(grab=True)
    rect, meta = surface_roi(im_low) if im_low is not None else (None, {"why": "低曝光取帧失败"})
    if rect is None:
        print("   低曝光也没搜到: %s ⇒ 退回用当前帧搜" % meta.get("why"))
        set_expo(GOOD_US)
        im = sq.capture(grab=True)
        if im is None:
            print("❌ 取帧失败"); return 1
        rect, meta = surface_roi(im)
        if rect is None:
            print("❌ 没搜到矩形刚体: %s" % meta.get("why")); return 1
        imB = im
    else:
        print("   低曝光搜到: w=%.0f h=%.0f 长宽比=%.2f angle=%.2f° fill=%.3f"
              % (rect["w"], rect["h"], rect.get("aspect", 0), rect["angle"], rect["fill"]))
        print("② 恢复 %dus 取检测用像素…" % GOOD_US)
        set_expo(GOOD_US)
        imB = sq.capture(grab=True)
        if imB is None:
            print("❌ 正常曝光取帧失败"); return 1
    im = imB
    print("① 搜到刚体: cx=%.1f cy=%.1f w=%.1f h=%.1f 长宽比=%.2f angle=%.2f° fill=%.3f"
          % (rect["cx"], rect["cy"], rect["w"], rect["h"], rect.get("aspect", 0),
             rect["angle"], rect["fill"]))

    rot, ang = rotate_full(im, rect)
    fname = "surface_rot_%s.png" % STAMP
    fpath = os.path.join(DELIVER, fname)
    cv2.imwrite(fpath, rot)
    print("② 整幅旋正 %.2f° → %s (%dx%d, %d KB)"
          % (ang, os.path.relpath(fpath, ROOT), rot.shape[1], rot.shape[0], os.path.getsize(fpath) // 1024))
    # 送检前确认模块本身不过曝 (老倪: 要没有曝光的光模块)
    crop_chk, _ = rotate_full(im, rect)
    gchk = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY)
    print("   用 %.0fus 取像素; 整幅 mean=%.1f 死白=%.2f%%"
          % (GOOD_US, gchk.mean(), float((gchk >= 250).mean() * 100)))

    # 旋正后复核: 模块应该变水平
    r2, m2 = surface_roi(rot)
    if r2 is not None:
        print("   旋正后复搜: w=%.1f h=%.1f angle=%.2f° (期望 |angle|→0 或 ±90, 长边水平)"
              % (r2["w"], r2["h"], r2["angle"]))

    # ── 投给工控机: 下载我这张图 → 用它的 YOLO 检测 ──
    host = os.environ.get("ZMAX_HUB_HOST", "192.168.23.50")
    url = "http://%s:8794/%s" % (host, fname)
    code = (
        "import sys, json\n"
        "sys.path.insert(0, r'D:\\xspace\\ultralytics_AOI')\n"
        "from yolo_detector import YoloDetector\n"
        "d = YoloDetector()\n"
        "r = d.detect(sys.argv[1], detect_type='housing')\n"
        "print('RESULT_JSON ' + json.dumps(r, default=str, ensure_ascii=False))\n"
    )
    b64 = base64.b64encode(code.encode("utf-8")).decode()
    ps = ("[IO.File]::WriteAllText('C:\\Windows\\TEMP\\zmax_det.py', "
          "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('%s')), "
          "(New-Object Text.UTF8Encoding($false))); "
          "Invoke-WebRequest -Uri '%s' -OutFile 'C:\\Windows\\TEMP\\zmax_rot.png' -UseBasicParsing; "
          "'downloaded ' + (Get-Item 'C:\\Windows\\TEMP\\zmax_rot.png').Length; "
          "& 'D:\\xspace\\ultralytics_AOI\\venv\\Scripts\\python.exe' "
          "'C:\\Windows\\TEMP\\zmax_det.py' 'C:\\Windows\\TEMP\\zmax_rot.png' 2>&1") % (b64, url)
    t_mark = newest_out_mtime()
    print("③ 投给工控机: %s" % url)
    print("   %s" % enqueue_ps(ps))

    out, txt = wait_out(after=t_mark)
    if not txt:
        print("⚠️ 等不到工控机输出 (agent 轮询可能停了)")
        return 1
    print("④ 工控机输出 (%s):" % os.path.basename(out))
    for ln in txt.replace("\r", "").splitlines()[-14:]:
        print("   " + ln)

    res = None
    for ln in txt.replace("\r", "").splitlines():
        if ln.startswith("RESULT_JSON "):
            try:
                res = json.loads(ln[len("RESULT_JSON "):])
            except Exception:                                  # noqa: BLE001
                pass
    if res is None:
        print("\n⇒ 没解析到检测结果")
        return 1
    dets = res.get("detections") or []
    cnt = res.get("detect_count", res.get("result"))
    print("\n⑤ 工控机 YOLO 判决 (摆正整幅图): 缺陷数=%s" % cnt)
    for i, d in enumerate(dets, 1):
        print("   缺陷%d: %s" % (i, json.dumps(d, ensure_ascii=False, default=str)[:200]))

    rec = {"ts": STAMP, "expo": expo, "rect": {k: rect.get(k) for k in ("cx", "cy", "w", "h", "angle", "fill")},
           "rot_deg": ang, "sent_png": fpath, "url": url, "plant_result": res,
           "verdict": "defect" if (isinstance(cnt, int) and cnt > 0) else "no_defect"}
    with open(os.path.join(ROOT, "data/memory/plant_yolo_rot_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("\n⇒ %s" % ("🔴 工控机 YOLO 在**摆正后**的图上检出 %s 处缺陷" % cnt
                      if isinstance(cnt, int) and cnt > 0 else "工控机 YOLO 在摆正图上仍报 0 缺陷"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
