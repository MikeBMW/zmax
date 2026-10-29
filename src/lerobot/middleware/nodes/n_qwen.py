# -*- coding: utf-8 -*-
"""👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)  ·  节点 n_vlm_llm

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in4   ← n_dsvl
    out out1  → ss_mani_eng, ssintact_dec, ss_mem_share, ssllm, ssreason, ssskill

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_vlm_llm.<port>

实现绑定: registry key=`n_dsvl` · src/lerobot/policies/left_right/state_space/scene_vlm.py:class SceneVLM
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'n_vlm_llm'
NAME = '👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in4']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'n_dsvl'
SOURCE = 'src/lerobot/policies/left_right/state_space/scene_vlm.py'
SOURCE_SYMBOL = 'class SceneVLM'
PARAMS = {'state_space': True, 'vlm_llm': True, 'model': 'DeepSeek-V4.1-Flash Vision (本机已配 key, 零申请) / Qwen2.5-VL-3B 本地 / Qwen3-VL / qwen-vl-max (API)', 'desc': '大模型层**视觉通路** (2026-09-19 实测可用): 环境帧/引擎真图/真机帧 → 场景理解 JSON (目标/在不在夹爪/画面质量/光照/背景/标定建议) → 任务规划器·异常推理器·技能编排器·意图解码器·总装记忆。 默认走 **DeepSeek Vision (deepseek-flash / V4.1-Flash, 本机 ~/.hermes/.env 已配 key, 关思考后真机帧实测 1.36s)**; 可换 Qwen: SS_VLM_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 + SS_VLM_KEY + SS_VLM_MODEL=qwen-vl-max; 或本地开源 Qwen2.5-VL-3B (无需 key) / Qwen3-VL。无模型时只给规则回退摘要并如实标注。源码 scene_vlm.py + tools/vlm_worker.py', 'source': 'src/lerobot/policies/left_right/state_space/scene_vlm.py', 'source_symbol': 'class SceneVLM'}

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
