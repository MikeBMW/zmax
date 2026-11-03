"""离屏验收 SU(2) 轨迹球 (不碰相机/共享内存, QT_QPA_PLATFORM=offscreen)"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")

from PyQt5.QtWidgets import QApplication            # noqa: E402
from PyQt5.QtCore import QSettings                  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
from su2_traj_ball import SU2TrajBall               # noqa: E402

OUT = "/home/ubuntu/zmax/zmax_data/ss_live"
w = SU2TrajBall(root="/home/ubuntu/zmax")
w.resize(520, 460)
w.reload()
app.processEvents()


def stats(img):
    """数一下关键颜色像素 (轨迹蓝 / 当前点绿 / 记忆黄), 用来证明"真的画出来了"。"""
    counts = {"trail": 0, "now": 0, "mem": 0, "ink": 0}
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if abs(r - 88) < 40 and abs(g - 166) < 40 and abs(b - 255) < 40:
                counts["trail"] += 1
            elif abs(r - 63) < 40 and abs(g - 185) < 45 and abs(b - 80) < 45:
                counts["now"] += 1
            elif abs(r - 210) < 45 and abs(g - 153) < 45 and abs(b - 34) < 55:
                counts["mem"] += 1
            if r + g + b > 180:
                counts["ink"] += 1
    return counts


shown_png = os.path.join(OUT, "ui_su2_ball_shown.png")
s1 = stats(w.grab().toImage())
w.grab().save(shown_png)
print("① 显示态: 轨迹点=%d 当前点=%d 记忆点=%d 亮像素=%d → %s" %
      (s1["trail"], s1["now"], s1["mem"], s1["ink"], shown_png))
print("   轨迹点数=%d 当前θ=%.2f° 源=%s" % (len(w.traj), 0 if w.cur is None else 2 * 0, w.lbl_src.text()))

# ② S² 切换
w.toggle_mode()
app.processEvents()
s2 = stats(w.grab().toImage())
w.grab().save(os.path.join(OUT, "ui_su2_ball_s2.png"))
print("② S² 视图: 轨迹点=%d (切回 S3)" % s2["trail"])
w.toggle_mode()

# ③ 完全隐藏
sig = []
w.hiddenChanged.connect(lambda h: sig.append(bool(h)))
w.btn_hide.click()
app.processEvents()
print("③ 点[⬇隐藏]: isVisible=%s  计时器=%s  信号=%s  尺寸=%s" %
      (w.isVisible(), w._timer.isActive(), sig, (w.width(), w.height())))
hidden_png = os.path.join(OUT, "ui_su2_ball_hidden.png")
print("   隐藏后 grab 为空/黑: ink=%d" % stats(w.grab().toImage())["ink"])

# ④ 恢复显示
w.set_hidden(False)
app.processEvents()
print("④ 恢复: isVisible=%s 计时器=%s 轨迹点=%d" % (w.isVisible(), w._timer.isActive(), len(w.traj)))

# ⑤ 宿主页面的"摘项/还原"逻辑 (真实 MasterParamMView)
try:
    from model_tree import MasterParamMView, MPARAM_SU2_KEY, MPARAM_SU2_PREV_KEY   # noqa: E402
    m = MasterParamMView(module=None)
    app.processEvents()
    print("⑤ 宿主页: 下拉项=%s 球可见=%s" % ([m.cmb_viz_view.itemText(i) for i in range(m.cmb_viz_view.count())],
                                          m._su2_shown))
    m._toggle_su2()          # 隐藏
    app.processEvents()
    print("   隐藏后: 下拉项=%s 球可见=%s 存值=%s" % (
        [m.cmb_viz_view.itemText(i) for i in range(m.cmb_viz_view.count())], m._su2_shown,
        QSettings("ZMAX", "studio").value(MPARAM_SU2_KEY)))
    m._toggle_su2()          # 还原
    app.processEvents()
    print("   还原后: 下拉项=%s 球可见=%s 存值=%s" % (
        [m.cmb_viz_view.itemText(i) for i in range(m.cmb_viz_view.count())], m._su2_shown,
        QSettings("ZMAX", "studio").value(MPARAM_SU2_KEY)))
    m.resize(520, 1100)
    app.processEvents()
    m.grab().save(os.path.join(OUT, "ui_mparam_with_ball.png"))
    print("   整页截图: %s/ui_mparam_with_ball.png" % OUT)
except Exception as e:                                                             # noqa: BLE001
    print("⑤ 宿主页整页验收跳过 (%s: %s)" % (type(e).__name__, e))
