#!/usr/bin/env bash
# 单独起一个「3D场景」窗口 (与老倪正在看的那条 episode 同源) —— 控制台重启后把窗口还给他。
cd /home/ubuntu/zmax
export DISPLAY=:0
export MUJOCO_GL=egl MUJOCO_EGL_DEVICE=0
export PYTHONIOENCODING=utf-8
exec /home/ubuntu/zmax/gui-venv311/bin/python -c "
import sys
sys.path.insert(0, 'tools'); sys.path.insert(0, 'tools/gui')
from PyQt5.QtWidgets import QApplication
from ss_dreamview import DreamView3D, load_episode
app = QApplication(sys.argv)
tr, meta = load_episode()
if tr is None:
    print('⛔ 读不到 episode'); sys.exit(2)
tr = dict(tr); tr['_meta'] = meta
w = DreamView3D(tr)
w.setWindowTitle('3D场景')
w.show()
print('✅ 3D场景 窗口已起:', (meta or {}).get('steps'), '帧')
sys.exit(app.exec_())
"
