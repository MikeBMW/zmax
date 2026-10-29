# -*- coding: utf-8 -*-
"""🤖 机器人执行器  ·  节点 ssact

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssbypv, n_exec
    out out1  → ssworld

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssact.<port>

实现绑定: registry key=`ss_act` · src/lerobot/policies/left_right/state_space/execution.py:class RobotExecutor
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'ssact'
NAME = '🤖 机器人执行器'
LAYER = ''
TYPE = 'hardware'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_act'
SOURCE = 'src/lerobot/policies/left_right/state_space/execution.py'
SOURCE_SYMBOL = 'class RobotExecutor'
PARAMS = {'state_space': True, 'desc': '[基础·分段小模型] 机器人执行器 (机械臂/夹爪): 接收物理指令执行', 'source': 'src/lerobot/policies/left_right/state_space/execution.py', 'source_symbol': 'class RobotExecutor', 'ar_real_sw': True, 'ar_scene': True, 'real_auth': False, 'sw_hint': '左=AR场景(开=控左右臂/关=控真机) · 右=真机(开=授权下发/关=不发) 默认都关'}

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
PURE = False
LAST_STATUS = ""

# 🔴 2026-10-29 老倪「要让 plan 真的喂动作执行器, 现在执行器节点联通的是 AR 场景」
#   事实: 画布上 ssplan 原来**零出边**(out1 没人接), 执行器 in1 只接 n_exec/ssbypv ⇒ plan 段到不了执行器。
#   现在: ssplan.out1 → ssact.in1, 执行器在 AR 场景(exec_switches.ar_scene=1 且 real_auth=0)下把 plan 段
#   接过来、落成执行指令 zmax_data/ss_live/ar_exec.json (页面只认这一份), 并回写 out1 供总线取证。
#   真机零指令: 只要 real_auth 没开就绝不写 FIFO/l2_daemon, 只写渲染用文件。
import json as _json
import os as _os
import time as _time

_DATA = _os.environ.get("ZMAX_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "zmax", "zmax_data")
_SW_F = _os.path.join(_DATA, "ss_live", "exec_switches.json")
_EXEC_F = _os.path.join(_DATA, "ss_live", "ar_exec.json")


def _ar_scene_on():
    """AR 场景 = 执行器左开关开 且 真机开关关 (两者都从 exec_switches.json 读, 不自己造)。"""
    try:
        with open(_SW_F, encoding="utf-8") as fh:
            d = _json.load(fh)
        return bool(d.get("ar_scene")) and not bool(d.get("real_auth"))
    except Exception:                                                # noqa: BLE001
        return False


def _publish_ar_exec(seg):
    """plan 段 → AR 执行指令(落盘, 页面唯一依据)。返回 payload 或 None。"""
    try:
        a, b = seg.get("a"), seg.get("b")
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) >= 3 and len(b) >= 3):
            return None
        out = {"t": _time.time(), "t_str": _time.strftime("%H:%M:%S"), "src": "ssact",
               "from": "ssplan.out1", "mode": "ar_scene",
               "seq": seg.get("seq"), "kind": seg.get("kind"), "label": seg.get("label"),
               "a": list(a)[:3], "b": list(b)[:3],
               "u": round(min(1.0, max(0.0, float(seg.get("u") or 0.0))), 4),
               "mod": seg.get("mod"), "hole": seg.get("hole"),
               "elapsed_s": seg.get("elapsed_s"), "t_left": seg.get("t_left"),
               "mt_id": seg.get("mt_id"), "mt_name": seg.get("mt_name"),
               "mt_i": seg.get("mt_i"), "mt_n": seg.get("mt_n"),
               "batch": seg.get("batch"), "task_id": seg.get("task_id")}
        _os.makedirs(_os.path.dirname(_EXEC_F), exist_ok=True)
        tmp = _EXEC_F + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump(out, fh, ensure_ascii=False)
        _os.replace(tmp, _EXEC_F)
        return out
    except Exception:                                                # noqa: BLE001
        return None


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
    # 🔴 AR 场景: plan 段 → 执行器 (这一段在 PURE=False 之前, 否则永远只是直通, 等于没接)
    seg = (ctx.get("in1") or {}).get("value") if isinstance(ctx, dict) else None
    if isinstance(seg, dict) and seg.get("a") and seg.get("b") and _ar_scene_on():
        out = _publish_ar_exec(seg)
        if out:
            LAST_STATUS = ("实现执行 (AR场景 · plan段→ar_exec.json · seq=%s %s · u=%.2f · 真机零指令)"
                           % (out.get("seq"), out.get("kind"), out.get("u") or 0))
            return {"out1": out}
    if not PURE:
        LAST_STATUS = ("直通 (PURE=False: 只走数据面)" if not isinstance(seg, dict)
                       else "直通 (AR开关未知/真机授权, 不接 plan 段)")
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
