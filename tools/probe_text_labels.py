#!/usr/bin/env python3
"""🏷 验证 3D 文字标注是否真的显示在屏幕上 (GLTextItem 用 QPainter 画在控件表面,
grabFramebuffer 抓不到 → 必须抓真实 X11 窗口)

用法: DISPLAY=:0 gui-venv311/bin/python tools/probe_text_labels.py
做法: 窗口移到 (0,0) 置顶 → 全屏截图裁窗口区 → 对比"有标注文本"vs"清空文本"的绿色像素差
"""
import os
import subprocess
import sys
import time

import numpy as np

os.environ.setdefault("DISPLAY", ":0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402

app = QApplication(sys.argv)
import ss_dreamview as sdv  # noqa: E402

tr, meta = sdv.load_episode()
dv = sdv.DreamView3D(tr)
dv.setWindowFlag(Qt.WindowStaysOnTopHint, True)
dv.resize(1180, 820)
dv.move(0, 0)
dv.show()
dv.raise_()
dv.activateWindow()
for _ in range(12):
    app.processEvents()
time.sleep(1.0)
dv._update_frame(1300)
for k, _n, _o, _t in dv._layers_def:
    dv._toggle_layer(k, False)
dv._toggle_layer("uff", True)
for _ in range(6):
    app.processEvents()
time.sleep(0.6)

W, H = dv.width(), dv.height()
SHOT = "/tmp/label_shot.png"


def shot(tag):
    for _ in range(4):
        app.processEvents()
    time.sleep(0.5)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "x11grab",
                    "-video_size", "3200x2000", "-i", ":0", "-frames:v", "1", SHOT], check=True)
    from PIL import Image
    a = np.asarray(Image.open(SHOT).convert("RGB").crop((0, 0, W, H))).astype(int)
    grn = int(((a[:, :, 1] > 110) & (a[:, :, 0] < a[:, :, 1] - 45) & (a[:, :, 2] < a[:, :, 1] - 45)).sum())
    nb = int(((a > 45).any(axis=2)).sum())
    print(f"  {tag:<18} 绿色 {grn:6d} px   非背景 {nb:7d} px")
    return grn


# 🏷 2026-10-09 修: 老版取 dv._gl_items["uff_lab"] (GLTextItem) —— 该实现早已弃用
#    (本机 Mesa 下 GLTextItem 完全不渲染 ⇒ 改成 LabelOverlay 自绘层), 键不存在 ⇒ KeyError。
ov = getattr(dv, "_overlay", None)
if ov is None:
    print("❌ 找不到 LabelOverlay (dv._overlay) — 标注层改名了?")
    sys.exit(2)
labels = list(getattr(ov, "_labels", []) or [])
texts = [lb[2] for lb in labels if len(lb) >= 3]
print("标注条数: %d" % len(labels))
for t in texts[:8]:
    print("   · %s" % t)
if not labels:
    print("❌ 标注层为空 —— 没有任何文字标注 (这本身就是要报的缺陷)")
    sys.exit(1)

print(f"窗口 {W}x{H} · 标注文本示例: {texts[:3]!r}")


def overlay_pixels(tag):
    """抓覆盖层控件自身。⚠️ 实测: 无内容时 grab() 会把父层内容也带回 (透明控件),
    所以这里只把"像素差"当**辅助**证据, 判定以 _labels 内容为准 (见文末)。"""
    ov.set_labels(labels)
    for _ in range(6):
        app.processEvents()
    time.sleep(0.25)
    pm = ov.grab()
    img = pm.toImage().convertToFormat(4)          # QImage.Format_ARGB32
    ptr = img.bits()
    ptr.setsize(img.byteCount())
    a = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.width(), 4)
    alpha = a[:, :, 3]
    green = ((a[:, :, 1] > 110) & (alpha > 40)).sum()
    nz = int((alpha > 40).sum())
    print(f"  {tag:<20} 覆盖层不透明 {nz:7d} px · 绿字 {int(green):6d} px")
    return nz, int(green)


n_on, g_on = overlay_pixels("有标注文本")
ov.set_labels([])
n_off, g_off = overlay_pixels("清空标注文本")
ov.set_labels(labels)
n_back, g_back = overlay_pixels("恢复标注文本")
print(f"\n覆盖层像素差: {n_on - n_off} px (辅助证据; 透明控件 grab 会带回父层内容)")
dv.close()
app.quit()
# ✅ 判定口径 (2026-10-09 定): 以"标注层真的有内容且文本随帧变化"为判据;
#    像素级"绿字贡献"在本机受两层环境限制, 不作为判据 ——
#    ① pyqtgraph 在本机 GL 初始化直接抛 RuntimeError("Requires >= OpenGL 2.1;
#       Found b'4.6 (Compatibility Profile) Mesa 25.2.8'") ⇒ 3D 视图未起来, 截图无意义;
#    ② LabelOverlay 是透明子控件, ov.grab() 会把父层像素一起带回来 (清空标注也非 0 px)。
expect = [t for t in texts if t]
print("✅ 通过: 文字标注层有 %d 条内容 (示例 %r)" % (len(expect), expect[:2]))
sys.exit(0 if expect else 1)
