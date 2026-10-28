#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 X11 窗口 id 抓指定窗口的像素 (不需要 import/scrot/xwd)。

用法:
    W=$(wmctrl -l | awk '/XSpace ZMAX/{print $1; exit}')
    DISPLAY=:0 QT_QPA_PLATFORM=xcb <venv>/bin/python grab_window_by_winid.py "$W" /tmp/win.png

为什么不用别的: ImageMagick `import` 常没装; `xwd -id` 输出 PIL 打不开, 且窗口被遮挡时
截到的是压在上面的那个窗口 (实测截到自己的终端)。QScreen.grabWindow 直接取该窗口的后备缓冲,
被遮挡、在别的 workspace 都能拿到正确像素。

注意: 必须用 Qt 的 xcb 平台 (DISPLAY=:0 QT_QPA_PLATFORM=xcb); offscreen 下 grabWindow 拿不到屏幕内容。
"""
import os
import sys

from PyQt5.QtGui import QGuiApplication


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    win_id = int(sys.argv[1], 0)  # wmctrl 给的是十进制字符串; 也允许 0x 前缀
    out = sys.argv[2]

    app = QGuiApplication.instance() or QGuiApplication([])
    screen = app.primaryScreen()
    pix = screen.grabWindow(win_id)
    if pix.isNull() or pix.width() == 0 or pix.height() == 0:
        print("FAIL: grabWindow 拿到空图 (win_id=%s). 先核窗口还在: wmctrl -l" % win_id)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    ok = pix.save(out)
    print("saved=%s %dx%d bytes=%d" % (out, pix.width(), pix.height(), os.path.getsize(out) if os.path.exists(out) else -1))
    # Qt teardown 在离屏/带线程时可能 abort, 别让它盖掉上面的结果
    sys.stdout.flush()
    os._exit(0 if (ok and os.path.getsize(out) > 1024) else 1)


if __name__ == "__main__":
    raise SystemExit(main())
