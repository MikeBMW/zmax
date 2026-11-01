# -*- coding: utf-8 -*-
"""🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)  ·  节点 n_dsvl · L5

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    in  in2   ← ssllm_in
    in  in3   ← n_web_agent
    in  in4   ← ss_seg
    out out1  → n_vlm_llm, n_board_frame, n_hil

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_dsvl.<port>

实现绑定: registry key=`n_dsvl` · src/lerobot/policies/left_right/state_space/scene_vlm.py:class SceneVLM (provider=deepseek)
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'n_dsvl'
NAME = '🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)'
LAYER = 'L5'
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'n_dsvl'
SOURCE = 'src/lerobot/policies/left_right/state_space/scene_vlm.py'
SOURCE_SYMBOL = 'class SceneVLM (provider=deepseek)'
PARAMS = {'state_space': True, 'vlm_llm': True, 'model': 'deepseek-flash (DeepSeek-V4.1-Flash, Vision ✓, 本机 key 已配)', 'desc': '[L5 大模型主路] DeepSeek-V4-Flash (API · 支持 Vision): 场景判读/工序纠错 → 结构化落 data/scene/scene_state.json, 喂 L3 规划/技能编排与 L4 意图解码; 本地保障 = smolvlm2-500m (HuggingFaceTB/SmolVLM2-500M, 权重在 ~/.cache/huggingface, GPU 单帧编码); 双路优先级 SS_VLM_PROVIDER > DeepSeek(flash) > 本地 worker', 'source': 'src/lerobot/policies/left_right/state_space/scene_vlm.py', 'source_symbol': 'class SceneVLM (provider=deepseek)', 'provider': 'deepseek-v4-flash', 'fallback': 'smolvlm2-500m (本地)'}

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
