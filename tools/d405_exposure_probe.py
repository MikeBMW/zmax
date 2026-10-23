#!/usr/bin/env python3
"""D405 曝光扫描 —— 找出在当前光照下能出图的曝光值。

背景: d405_color_pub.py 不设曝光, 用 RealSense 自动曝光, 实测画面 mean=9.2
(几乎全黑)。本脚本独占相机, 依次设不同曝光抓帧, 统计亮度, 判断:
  · 提高曝光能明显变亮  → 自动曝光策略有问题, 改脚本固定曝光
  · 曝光拉满仍旧暗      → 环境没光, 需现场处理(开灯/移开遮挡)

用法: sudo systemctl stop d405-color-pub rs-fast-node; python3 d405_exposure_probe.py
测完: sudo systemctl start d405-color-pub rs-fast-node
"""
import sys
import time

import numpy as np

try:
    import pyrealsense2 as rs
except ImportError:
    print("缺 pyrealsense2")
    sys.exit(1)

EXPOSURES = [0, 5000, 20000, 50000, 100000, 200000, 330000]
OUT = "/tmp/d405_probe"

import os
os.makedirs(OUT, exist_ok=True)

pipe = rs.pipeline()
cfg = rs.config()
cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
profile = pipe.start(cfg)
dev = profile.get_device()
print("[probe] 相机已开 | 型号: %s" % dev.get_info(rs.camera_info.name))

# first_color_sensor() 在刚释放的相机上会返回空, 用 query_sensors 按名字找
sensor = None
for s in dev.query_sensors():
    name = s.get_info(rs.camera_info.name)
    opts = [o for o in s.get_supported_options()] if hasattr(s, "get_supported_options") else []
    if "RGB" in name.upper() or "COLOR" in name.upper() or rs.option.exposure in opts:
        sensor = s
        print("[probe] 选用 sensor: %s" % name)
        break
if sensor is None:
    print("[probe] 没找到彩色 sensor, 可用: %s"
          % [s.get_info(rs.camera_info.name) for s in dev.query_sensors()])
    pipe.stop()
    sys.exit(1)

# 关掉自动曝光, 才能设固定值
try:
    sensor.set_option(rs.option.enable_auto_exposure, 0)
    print("[probe] 自动曝光已关闭")
except Exception as e:
    print("[probe] 关自动曝光失败: %s" % e)

print("\n%-10s %8s %8s %8s %8s  %s" % ("曝光us", "mean", "std", "p95", "max", "判定"))
print("-" * 62)

results = []
for ex in EXPOSURES:
    try:
        sensor.set_option(rs.option.exposure, ex)
    except Exception as e:
        print("%-10s 设置失败: %s" % (ex, e))
        continue
    # 丢掉前几帧 (曝光切换要几帧才稳定)
    for _ in range(8):
        pipe.wait_for_frames()
    frames = pipe.wait_for_frames()
    img = np.asanyarray(frames.get_color_frame().get_data())
    gray = img.mean(axis=2)

    m, sd = gray.mean(), gray.std()
    p95, mx = np.percentile(gray, 95), gray.max()
    verdict = "可用" if m > 40 else ("偏暗" if m > 15 else "太暗")
    print("%-10s %8.1f %8.1f %8.0f %8.0f  %s" % (ex, m, sd, p95, mx, verdict))
    results.append((ex, m, sd, p95, mx))

    try:
        import cv2
        cv2.imwrite("%s/ex%06d.jpg" % (OUT, ex), img)
    except Exception:
        pass

pipe.stop()

print("\n=== 结论 ===")
if not results:
    print("  没有拿到任何有效帧")
else:
    best = max(results, key=lambda r: r[1])
    print("  最亮: 曝光 %dus → mean %.1f" % (best[0], best[1]))
    base = results[0][1]
    if best[1] > base * 3 and best[1] > 40:
        print("  提高曝光能显著变亮 ⇒ 自动曝光策略有问题, 建议固定曝光 %d" % best[0])
    elif best[1] <= 40:
        print("  曝光拉到最大仍 mean=%.1f ⇒ 环境确实没光, 需现场开灯或移开遮挡" % best[1])
    else:
        print("  提升有限, 需结合现场判断")
print("\n图已存 %s" % OUT)
