# -*- coding: utf-8 -*-
"""🧩 开放词汇分割 (SAM3 分割anything)  ·  节点 ss_seg

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    in  in2   ← ss_l5
    in  in3   ← ssyolo
    out out1  → ss2d3d
    out out2  → ssvlm, n_dsvl

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_seg.<port>

实现绑定: registry key=`ss_seg` · tools/sam3_seg.py:def segment(img_bgr
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ss_seg'
NAME = '🧩 开放词汇分割 (SAM3 分割anything)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {}

IMPL_KEY = 'ss_seg'
SOURCE = 'tools/sam3_seg.py'
SOURCE_SYMBOL = 'def segment(img_bgr'
PARAMS = {'state_space': True, 'segmentation': True, 'open_vocabulary': True, 'kind': 'real', 'layer': 'L2', 'role': 'L2 感知原语 — 一帧 + 概念提示词(文本/框/点) → 该概念的**所有实例掩膜**(像素级); 与 L2-A01 YOLO 同级(框→轮廓, 固定类→开放词汇)', 'intent_from': 'L5 (VLM/人/工单给概念; 本节点不自造概念)', 'model': 'facebook/sam3 (848M: 共享视觉编码 + DETR 检测器 + SAM2 式跟踪器)', 'engine': 'transformers Sam3Model / Sam3Processor (本机 transformers 5.16.1) + 权重=HF 逐文件镜像(官方 gated, 用镜像)', 'weights_dir': '/home/ubuntu/zmax/zmax_data/models/sam3_hf (model.safetensors 3.44GB fp32 → bf16 载入)', 'api': 'POST http://127.0.0.1:8796/seg {cam|image_path|image_b64, texts[], three_d, write_spec} · GET /health', 'source': 'tools/sam3_seg.py', 'source_symbol': 'def segment(img_bgr', 'run': 'python tools/sam3_seg.py --serve --port 8796   (显存独占 ≈2GB, 按需调用, 不逐帧常开)', 'overlay': "写 data/scene/overlay_spec.json 的 origin='seg' / kind='mask' (品红轮廓 + 半透明填充; 与 sim/vlm/det 按 origin 合并)", 'license': 'SAM License (允许商用; 禁军事/ITAR 用途; 再分发须带许可)', 'modes': 'PCS 图像(文本→所有实例掩膜) · PCS 视频(文本→跨帧跟踪) · PVS(点/框/mask → 单实例精修, SAM2 兼容接口)', 'caveat': '1008px 输入 + 848M 参数 ⇒ 4060(8GB) 上不能与别的模型同刻常驻; 定位=关键帧/触发式(按钮/画布节点/标注批次), 不是 30fps 逐帧', 'desc': 'L2 基础感知(与 🎯YOLO 内链): 吃 YOLO 的框 + **同帧原图** → 每个目标出像素级掩膜(轮廓/面积/质心/越界), 再掩膜→base 3D(中心/足印/朝向); 也支持 L5 给的文本概念。', 'prompt_src': 'yolo', 'prompt_from': '🎯 YOLO 目标检测 (框, 同帧原图) / L5 (文本概念, prompt_src=text)', 'chain': 'L2 基础感知: 🎯 YOLO 定位 → 🧩 SAM3 掩膜细化 → 📐 2D→3D'}

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
    if not PURE:
        LAST_STATUS = "直通 (PURE=False: 只走数据面)"
        return _passthrough(ctx)
    try:
        from lerobot.engineering import registry as _reg
        info = _reg.get(IMPL_KEY) or {}
        fn = info.get("fn")
        if not callable(fn):
            LAST_STATUS = "直通 (实现未注册: %s)" % IMPL_KEY
            return _passthrough(ctx)
        # 🔴 2026-10-29: 实现层需要知道"自己是哪个节点" —— 同一实现服务多个节点时靠这个分派
        #   (如 node_ss_mani 同时服务 ssmani_c 接触流形 / ssmani_p 性能流形, 只看 ctx["name"])。
        #   原来 ctx 里只有端口 (in1→{"value":…}), 常驻循环里实现拿到 name="" ⇒ 直接 return False。
        #   这里补元信息: 键名不与端口冲突 (端口是 inN/outN), 且不参与 _passthrough 取数。
        _mctx = dict(ctx)
        _mctx.setdefault("name", NAME)
        _mctx.setdefault("params", dict(PARAMS))
        _mctx.setdefault("id", NODE_ID)
        _mctx.setdefault("_node", {"id": NODE_ID, "name": NAME, "params": dict(PARAMS),
                                   "ports_in": list(PORTS_IN), "ports_out": list(PORTS_OUT)})
        try:
            res = fn(_mctx)                     # 约定: 接 ctx 的实现
        except TypeError:
            res = fn()                          # 老实现: 无参
        if isinstance(res, dict):
            LAST_STATUS = "实现执行"
            _out = {k: v for k, v in res.items() if k in PORTS_OUT}
            if not _out and PORTS_OUT:
                # 实现返回的是**业务结果字典**(键是 M/ok/progress 这类, 不是端口名)
                # ⇒ 整块当首端口的值发出去, 不能过滤成空 dict 把数据丢掉
                # (2026-10-29: 流形引擎族就是这样, 原来 out 恒为空, 下游永远拿不到)
                _out = {PORTS_OUT[0]: res}
            return _out
        LAST_STATUS = "实现返回非 dict → 直通"
        return _passthrough(ctx)
    except Exception as e:                                          # noqa: BLE001
        LAST_STATUS = "实现异常(%s: %s) → 直通" % (type(e).__name__, e)
        return _passthrough(ctx)
