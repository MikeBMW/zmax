# -*- coding: utf-8 -*-
"""🎯 YOLO 目标检测  ·  节点 ssyolo

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata, ss_l5
    out out1  → ssvlm, ss2d3d, ssaoi, swds, n_board_frame, ss_seg

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssyolo.<port>

实现绑定: registry key=`ss_yolo` · src/lerobot/policies/yolo_3d/yolo_state_aligner.py:class YoloStateAligner
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssyolo'
NAME = '🎯 YOLO 目标检测'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_yolo'
SOURCE = 'src/lerobot/policies/yolo_3d/yolo_state_aligner.py'
SOURCE_SYMBOL = 'class YoloStateAligner'
PARAMS = {'model': 'yolov8s', 'classes': 'peg/hole/hand', 'state_space': True, 'source': 'src/lerobot/policies/yolo_3d/yolo_state_aligner.py', 'desc': '[基础·分段小模型] 感知层·B1 目标识别定位: YOLO 检测光模块/插座/料盘/缺陷等 22 个目标 (类别/位姿/方向, 指标含 mAP/推理时间); 双击=目标清单, 右下角导出=Excel', 'detection_targets': True, 'source_symbol': 'class YoloStateAligner'}

import os   # noqa: E402  (ZMAX_YOLO_SHARE 复用开关需要)

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
PURE = False
LAST_STATUS = ""


def manifest():
    """给画布/面板: 这个节点的输入输出与实现位置。"""
    return {
        "id": NODE_ID, "name": NAME, "layer": LAYER, "exec_mode": EXEC_MODE,
        "ports_in": list(PORTS_IN), "ports_out": list(PORTS_OUT),
        "impl_key": IMPL_KEY, "source": SOURCE, "source_symbol": SOURCE_SYMBOL,
        "pure": PURE,
    }


def _passthrough(ctx):
    """默认数据面: out1←in1, out2←in2 … (端口序号对齐); 缺输入 → None。"""
    outs = {}
    for i, op in enumerate(PORTS_OUT):
        ip = PORTS_IN[i] if i < len(PORTS_IN) else None
        outs[op] = (ctx.get(ip) or {}).get("value") if ip else None
    return outs


def compute(ctx):
    """一个周期: ctx 来自总线 → 返回要发回总线的输出。

    PURE=False 时只做直通 (数据面), 不调用真实现 —— 避免未验证/未授权的节点被自动执行。
    """
    global LAST_STATUS
    # 🔴 2026-10-29 老倪「用 AR 场景渲染视频当数据源, 再有 L2 感知节点检测」:
    #   引擎常驻回路的 L2 (detect.yolo, 权重 models/yolo_ar_peg.pt) 已经在 8802 的 AR 渲染帧上
    #   每拍真推理, 结果外发 /dev/shm/l2_det.json。本节点**复用这次推理**(不再开第二份模型:
    #   8GB 显存里两份 YOLO 会互挤), 但输出的确是这一帧的检测结果, 不是抄来的常量。
    #   ZMAX_YOLO_SHARE=0 可关掉复用 (改回自己跑 YoloStateAligner 的老路, 需 PURE=True)。
    if (os.environ.get("ZMAX_YOLO_SHARE", "1") or "1").strip().lower() not in ("0", "false", "no"):
        try:
            import json as _j
            import time as _t
            _f = "/dev/shm/l2_det.json"
            _age = _t.time() - os.path.getmtime(_f)
            if _age <= 5.0:
                with open(_f, encoding="utf-8") as _fh:
                    _d = _j.load(_fh)
                LAST_STATUS = ("复用L2检测 (n=%d · %s · 帧龄%.1fs · %s)"
                               % (int(_d.get("n") or 0), _d.get("src"),
                                  _age, os.path.basename(str(_d.get("img") or ""))))
                return {"out1": {"det": _d.get("det") or {}, "n": int(_d.get("n") or 0),
                                 "src": "L2:detect.yolo(复用)", "age_s": round(_age, 2),
                                 "img": _d.get("img"), "t_str": _d.get("t_str")}}
            LAST_STATUS = "复用L2检测失败 (l2_det.json 过期 %.1fs)" % _age
        except Exception as _e:                                              # noqa: BLE001
            LAST_STATUS = "复用L2检测失败 (%s) → 直通" % type(_e).__name__
    if not PURE:
        LAST_STATUS = LAST_STATUS if LAST_STATUS.startswith("复用L2检测失败") else \
            "直通 (PURE=False: 只走数据面)"
        return _passthrough(ctx)
    try:
        from lerobot.engineering import registry as _reg
        info = _reg.get(IMPL_KEY) or {}
        fn = info.get("fn")
        if not callable(fn):
            LAST_STATUS = "直通 (实现未注册: %s)" % IMPL_KEY
            return _passthrough(ctx)
        try:
            res = fn(ctx)                       # 约定: 接 ctx 的实现
        except TypeError:
            res = fn()                          # 老实现: 无参
        if isinstance(res, dict):
            LAST_STATUS = "实现执行"
            return {k: v for k, v in res.items() if k in PORTS_OUT}
        LAST_STATUS = "实现返回非 dict → 直通"
        return _passthrough(ctx)
    except Exception as e:                                          # noqa: BLE001
        LAST_STATUS = "实现异常(%s: %s) → 直通" % (type(e).__name__, e)
        return _passthrough(ctx)
