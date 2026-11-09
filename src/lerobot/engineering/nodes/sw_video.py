# -*- coding: utf-8 -*-
"""sw_video — 节点实现正文 (文件名 = 画布节点: sw_video)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_sw_video   ·   registry key: sw_video
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _sw_paths,
    _sw_status,
    _sw_task,
    os,
)

def node_sw_video(ctx):
    """🎬 L4 可视化 — 从 stable world 取出的渲染视频 (实况窗 + 视频路径)"""
    log = ctx["log"]
    root = str(ctx.get("root") or os.getcwd())
    _, fr, st, vd = _sw_paths(root)
    d = _sw_status(st)
    newest = None
    try:
        js = sorted([x for x in os.listdir(fr) if x.endswith(".jpg")])
        newest = os.path.join(fr, js[-1]) if js else None
    except Exception:
        pass
    vids = []
    try:
        vids = sorted([os.path.join(vd, x) for x in os.listdir(vd) if x.endswith(".mp4")])
    except Exception:
        pass
    tsk = "光模块插拔" if _sw_task(root) == "optical_insert" else "cube"
    log(f"🎬 渲染视频 [L4·{tsk}]: 逐帧实况 {newest} · 最新一帧 {d.get('frame_std')} std "
        f"(>5 真图) · 阶段 {d.get('stage_label')} · 插入深度 {d.get('insert_mm')}mm")
    log(f"   视频文件 ({len(vids)}): " + (" · ".join(os.path.basename(v) for v in vids[-4:])
                                          or "尚未产出"))
    if d.get("honest_note"):
        log(f"   ⚠️ {d.get('honest_note')}")
    try:                                                        # 实况窗 (lazy Qt, CLI 下跳过)
        # 🔴 2026-11-01: 常驻循环 (ss_canvas_loop) 在**工作线程**里真跑节点, 这里建 QWidget 会让
        #   Qt 直接 ABRT ("QWidget: Must construct a QApplication before a QWidget"),
        #   整个 canvas loop 被 systemd 判 core-dump 重启 (实测 19:17:40 abrt, NRestarts=1),
        #   链随之断拍 ⇒ AR 侧看到的就是"指令停了"。窗口只许在主线程开。
        import threading as _th
        if _th.current_thread() is not _th.main_thread():
            return True
        if os.environ.get("ZMAX_NO_GUI", "").strip() in ("1", "true", "on", "yes"):
            return True
        import importlib.util as _ilu
        if _ilu.find_spec("PyQt5") is None:
            return True
        from PyQt5 import QtWidgets, QtGui, QtCore
        app = QtWidgets.QApplication.instance()
        if app is None:
            return True
        # 🎛 2026-09-13 老倪: 要能像 L2/L3 dreamview 一样互动看任意帧 → 优先开互动查看器
        try:
            import intact_signal_viewer as _iv
            _vw = _iv.open_signal_viewer(os.path.dirname(fr))
            if _vw is not None:
                _vw.rescan(os.path.dirname(fr))
                log("🎛 互动查看器已打开 — 拖时间轴/◀▶ 单帧, 任意帧的 画面+模型动作[0..3]+std+done+推理次数 同步显示")
                return True
        except Exception as _e:                     # 回落到简易实况窗 (不静默)
            log(f"   (互动查看器不可用, 回落实况窗: {type(_e).__name__}: {_e})")
        w = QtWidgets.QDialog()
        w.setWindowTitle("🎬 SW 渲染视频 (stable-world) · L4")
        lay = QtWidgets.QVBoxLayout(w)
        lb = QtWidgets.QLabel("等待渲染帧 …")
        lb.setMinimumSize(456, 456)
        lb.setAlignment(QtCore.Qt.AlignCenter)
        info = QtWidgets.QLabel("")
        lay.addWidget(lb)
        lay.addWidget(info)
        timer = QtCore.QTimer(w)

        def _tick():
            js2 = []
            try:
                js2 = sorted([x for x in os.listdir(fr) if x.endswith(".jpg")])
            except Exception:
                pass
            if js2:
                pm = QtGui.QPixmap(os.path.join(fr, js2[-1]))
                if not pm.isNull():
                    lb.setPixmap(pm.scaled(lb.size(), QtCore.Qt.KeepAspectRatio,
                                           QtCore.Qt.SmoothTransformation))
                d2 = _sw_status(st)
                info.setText(f"帧 {js2[-1]} · std={d2.get('frame_std')} · step={d2.get('step')} · "
                             f"阶段={d2.get('stage')} · 成功 {d2.get('succ')}/{d2.get('ep_done')}")
        timer.timeout.connect(_tick)
        _tick()
        timer.start(120)
        w.resize(520, 560)
        w.show()
    except Exception as e:                                      # noqa: BLE001
        log(f"   (实况窗跳过: {type(e).__name__}: {e})")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_sw_video
