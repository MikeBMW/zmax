"""execution.py — 执行层 · 物理闭环 (状态空间模型画布)

机器人执行器 (机械臂/夹爪) → 物理世界 → 传感器反馈 z_k → 卡尔曼校正闭环。

闭环 (对应画布连线):
  🤖执行器 → 🌍物理世界 → z_k 传感器反馈 → 🧪状态校正器 → 校正后潜状态 → 📈先验预测器

状态空间闭环:
  u (物理指令) → 执行器 → 世界 → z_k (观测) → 残差 → 校正 → 预测 → (下一拍)
"""
import numpy as np


_LAST_STOP = {}        # tag → 上次真停的 monotonic 时间 (按时间间隔去重, 不是"只停一次")
_SAID_BRK = set()


def _brk(tag=""):
    """🔴 三种触发方式, 从硬到软 (2026-10-29 老倪「断点进不去」):

      ① 文件开关 (最硬, 不判断 env / 不判断 debugpy 是否连通):
           touch ~/zmax/zmax_data/ss_live/BREAK
         存在就**无条件** breakpoint() —— VSCode 调试会话里由 debugpy 接管, 停; 无调试器时进 pdb。
         若连这条都不停, 就证明 debugpy 根本没接管这个进程, 与代码无关 (换 tools/dbg_actuator.py)。
      ② ZMAX_DEBUG_BREAK=1/*/all 全停; =tag1,tag2 按 tag 停
      ③ 调试器已连接 + 未设 env ⇒ 每个 tag 只停第一次 (不把 10Hz 刷成无限暂停)
    """
    return                # 🔴 2026-10-29 老倪「不要干扰我 debug」: 本函数已停用 (纯 no-op)。
    import os as _os
    if _os.environ.get("ZMAX_BREAK_OFF") == "1":      # 日常跑不想被内置断点打扰
        return
    _HERE = _os.path.abspath(__file__)
    # state_space → left_right → policies → lerobot → src → zmax (6 层!)
    # 少一层会指到 /home/ubuntu/zmax/src 而永远不命中 —— 文件开关和到达记账都会静默失效。
    _ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(
        _os.path.dirname(_os.path.dirname(_HERE))))))
    _FLAG = _os.path.join(_ROOT, "zmax_data", "ss_live", "BREAK")
    # 🔴 2026-10-29 到达即记账 (不受调试器/env 影响): 用它回答"execute 到底有没有被调用"。
    #   改的是本函数内部, 不影响 execute 的行号。
    try:
        _tm = __import__("time")           # 不新增顶层 import (会让 execute 行号再漂)
        with open(_os.path.join(_ROOT, "zmax_data", "ss_live", "brk_calls.log"),
                  "a", encoding="utf-8") as _lf:
            _lf.write("%s pid=%s tag=%s\n"
                      % (_tm.strftime("%H:%M:%S"), _os.getpid(), tag or "-"))
    except Exception:                                                      # noqa: BLE001
        pass
    if _os.path.exists(_FLAG):
        if "flag:" + (tag or "-") not in _SAID_BRK:
            _SAID_BRK.add("flag:" + (tag or "-"))
            try:
                print("🔴 [brk:%s] 命中文件开关 %s → 停" % (tag or "-", _FLAG), flush=True)
            except Exception:                                              # noqa: BLE001
                pass
        breakpoint()
        return

    _spec = _os.environ.get("ZMAX_DEBUG_BREAK", "")
    _key = "ex:" + (tag or "-")

    def _say(msg):
        if _key in _SAID_BRK:
            return
        _SAID_BRK.add(_key)
        try:
            print("🔴 [brk:%s] %s" % (tag or "-", msg), flush=True)
        except Exception:                                                  # noqa: BLE001
            pass

    if _spec:
        if _spec in ("1", "*", "all") or (tag and tag in _spec.split(",")):
            _say("命中 ZMAX_DEBUG_BREAK=%r → 停" % _spec)
            breakpoint()
        else:
            _say("ZMAX_DEBUG_BREAK=%r 不含本 tag → 不停" % _spec)
        return
    # 未设 env: **只记录不停** (GUI 主线程一 breakpoint() 就整界面冻结, 鼠标点不动)。
    # 想停: touch zmax_data/ss_live/BREAK 或 ZMAX_DEBUG_BREAK=actuator / 1
    _say("到达 (默认不停; 想停设 ZMAX_DEBUG_BREAK=%s 或 touch zmax_data/ss_live/BREAK)" % _key)
    return



import os

import json
import math
import threading

import time


# ── 215 点轨迹真值(回退用) ──────────────────────────────────────────────
def _root_() -> str:
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if (os.path.isdir(os.path.join(d, "zmax_data"))
                and os.path.isdir(os.path.join(d, "src", "lerobot"))):
            return d
        d = os.path.dirname(d)
    return "/home/ubuntu/zmax"


_ROOT_ = _root_()
_TRAJ_JSON = os.path.join(_ROOT_, "tools", "web", "real_traj_joints.json")
_TRAJ_STATE = os.path.join(_ROOT_, "zmax_data", "rokae_sdk", "traj_step_state.json")


def _abc_deg(quat):
    """四元数 → 姿态 a b c (deg)。唯一口径走 tools/pt_pose.py:abc_deg; 读不到返回 None(绝不编)。"""
    try:
        import importlib.util as _ilu
        _p = os.path.join(_ROOT_, "tools", "pt_pose.py")
        _spec = _ilu.spec_from_file_location("_pt_pose", _p)
        _m = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        return _m.abc_deg(quat)
    except Exception:                                          # noqa: BLE001
        return None


def tcp_pose_now():
    """机器人当前位姿, 与机器人读数同格式: x y z (mm) + a b c (deg)。取不到 ⇒ None。"""
    try:
        p = os.path.join(_ROOT_, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
        if time.time() - os.path.getmtime(p) > 2.0:
            return None
        d = json.load(open(p, encoding="utf-8"))
        xyz = [float(d["x"]) * 1000.0, float(d["y"]) * 1000.0, float(d["z"]) * 1000.0]
        if xyz == [0.0, 0.0, 0.0]:
            return None
        abc = _abc_deg([d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")])
        return {"x": round(xyz[0], 2), "y": round(xyz[1], 2), "z": round(xyz[2], 2),
                "a": (None if abc is None else abc[0]),
                "b": (None if abc is None else abc[1]),
                "c": (None if abc is None else abc[2]),
                # 四元数(与 a b c 同一姿态的另一种表示): 旋转插值/传给策略时用这个, 别用欧拉角
                "qx": round(float(d.get("qx") or 0.0), 6),
                "qy": round(float(d.get("qy") or 0.0), 6),
                "qz": round(float(d.get("qz") or 0.0), 6),
                "qw": round(float(d.get("qw") or 0.0), 6),
                "age_s": round(time.time() - os.path.getmtime(p), 3),
                "src": "tcp_out/latest.json"}
    except Exception:                                          # noqa: BLE001
        return None


_TRAJ_FRAMES = {"mt": -1.0, "frames": []}


def _traj_frames():
    """215 点 frames —— 按 mtime 缓存(单线程每拍都要取, 不能每拍 parse 1MB)。"""
    try:
        mt = os.path.getmtime(_TRAJ_JSON)
    except Exception:                                          # noqa: BLE001
        return []
    if _TRAJ_FRAMES["mt"] == mt and _TRAJ_FRAMES["frames"]:
        return _TRAJ_FRAMES["frames"]
    try:
        d = json.load(open(_TRAJ_JSON, encoding="utf-8"))
        fr = d.get("frames") or []
    except Exception:                                          # noqa: BLE001
        return []
    _TRAJ_FRAMES["mt"], _TRAJ_FRAMES["frames"] = mt, fr
    return fr


def traj215_target(cursor=None):
    """取 215 点轨迹"当前点"的真值关节指令 (deg)。取不到 ⇒ None。

    老倪 2026-11-14: 「如果 a 算错了, 就直接输出 215 点的真正轨迹」
      cursor 优先级: 显式参数 > traj_step_state.json(8797 每点写) > 0
      真源文件: tools/web/real_traj_joints.json  frames[i].j (rad)  215 帧
    """
    try:
        if cursor is None:
            i = 0
            if os.path.exists(_TRAJ_STATE):
                i = int(json.load(open(_TRAJ_STATE, encoding="utf-8")).get("cursor") or 0)
            # 2026-11-14 老倪「action 怎么跟机器人上看到的不一样」:
            #   cursor 是**派单游标**(每轮结束才推进), 一轮 n 点时臂在走 cursor+1~+n。
            #   ⇒ 运行中按真机位姿取最近点, 让 action 跟"实际执行"对齐(取不到才用 cursor)。
            try:
                from . import action_bus as _ab2
                _e = _ab2.exec_index()
                if _e is not None:
                    i = int(_e)
            except Exception:                                              # noqa: BLE001
                pass
        else:
            i = int(cursor)
        fr = _traj_frames()
        if not fr:
            return None
        i = max(0, min(i, len(fr) - 1))
        j = fr[i].get("j") or []
        if len(j) != 6:
            return None
        _p = fr[i].get("p") or []
        _abc = _abc_deg(fr[i].get("q") or [])
        return {"cursor": i, "cursor_plan": int(json.load(open(_TRAJ_STATE, encoding="utf-8")).get("cursor") or 0) if os.path.exists(_TRAJ_STATE) else i, "total": len(fr),
                "joint_deg": [round(math.degrees(float(x)), 4) for x in j],
                "p_mm": [round(float(x) * 1000, 2) for x in _p],
                "abc_deg": _abc,
                "quat": [round(float(x), 6) for x in (fr[i].get("q") or [])][:4],
                "pose": ({"x": round(float(_p[0]) * 1000, 2), "y": round(float(_p[1]) * 1000, 2),
                          "z": round(float(_p[2]) * 1000, 2),
                          "a": (None if _abc is None else _abc[0]),
                          "b": (None if _abc is None else _abc[1]),
                          "c": (None if _abc is None else _abc[2]),
                          "qx": round(float((fr[i].get("q") or [0, 0, 0, 0])[0]), 6),
                          "qy": round(float((fr[i].get("q") or [0, 0, 0, 0])[1]), 6),
                          "qz": round(float((fr[i].get("q") or [0, 0, 0, 0])[2]), 6),
                          "qw": round(float((fr[i].get("q") or [0, 0, 0, 0])[3]), 6),
                          "src": "215点轨迹 frames[%d]" % i} if len(_p) == 3 else None)}
    except Exception:                                          # noqa: BLE001
        return None


def _eff_out(act):
    """这一拍真正下发的口径: 直驱(ss) 还是 215 点回放。

    为什么要打: 执行器 src=ss 时, 节点里的直驱护栏可能没放行 ⇒ 实际落盘/下发的是 215 点。
    终端只看 src 会以为下发的是直驱位姿, 于是又对不上。这里给出护栏的判决。
    """
    try:
        from lerobot.policies.left_right.state_space import direct_drive_guard as _g
        v = _g.last() or {}
        if not v:
            return "215点(护栏未跑 · 直驱闸默认关)"
        if str(act.get("src")) == "ss" and not v.get("allow"):
            return "215点(护栏 mode=%s ok=%s/%s)" % (v.get("mode"), v.get("ok_ticks"), v.get("need"))
        return "直驱/ss"
    except Exception:                                       # noqa: BLE001
        return "?"


class Action(dict):
    """工程唯一输出 —— **位姿口径**(老倪 2026-11-14)。

    返回 dict 而不是裸数组, 因为机器人执行的是**位姿/关节**, 不是那个 4 维速度:
      action["pose"]       {x,y,z mm · a,b,c deg · qx..qw}  ← 与机器人读数逐字同格式
      action["joints_deg"] [6] 关节角(deg) + action["joints_src"]
      action["grip_*"]     夹爪开合(mm/动作/状态/来源)
      action["src"]        "traj215"(回放真值) | "ss"(状态空间算出)
      action["u"]          4 维速度+夹爪通道(仅 ss 档; 留作溯源, 不再当"指令"看)
      action["check"]      NaN/范围/变化率三项校验 + fallback
    同时向后兼容老消费方(verification_layer / sim.py): np.asarray(action) 仍拿到数值指令
    (ss 档 = 4 维速度; 回退档 = 6 维关节 deg), action[:3] / action.size 也照旧可用。
    """

    def __array__(self, dtype=None, copy=None):                      # noqa: D105
        a = np.asarray(self.get("cmd") if self.get("cmd") is not None else [], dtype=float)
        return a if dtype is None else a.astype(dtype)

    @property
    def size(self):
        return int(np.asarray(self).size)

    def ravel(self):
        return np.asarray(self).ravel()

    def __getitem__(self, k):
        if isinstance(k, str):
            return dict.__getitem__(self, k)
        return np.asarray(self)[k]                                   # 兼容 u_vec[:3]


class RobotExecutor:
    """🤖 机器人执行器 — 接收物理指令执行

    🔴 2026-10-29 老倪:「def execute 原样返回? 没用就删掉啊」 —— 原来 execute() 就是
    `return np.asarray(u, dtype=float)`, 一个纯恒等函数: 执行器这一环在链路上什么都不做,
    却撑着画布 params.source_symbol / _EXTERNAL_LOC 源码锚点 / verification t_act_dim·t_act_pass
    两条判据 —— 典型的"占着位置不干活"。判定: 不删 (删了链路少一环, 锚点与判据全要连带改),
    改成真执行器该做的三件事, 且**输出数值一字不改** (零回归):
      ① NaN/Inf 拦截: 出现即整条指令归零 (执行器不敢把脏数往外送), 标 valid=False
      ② 通道范围: |u| > _LIMIT 记 clip_hint —— 真裁剪仍归 🛡 安全执行边界 sslimit (不越权)
      ③ 变化率: |u − u_prev| > max_rate 记 over_rate (物理上臂跟不上, 是异常信号不是误差)
    校验结果落在 `last_check`, 节点把它带进 out1.exec_check —— 看得见, 不是口号。
    """

    _LIMIT = 1.0          # 归一化通道范围 (再往外归 sslimit 的 safety_limit=0.6 裁)
    # 上一拍指令必须**跨实例**共享: 节点每拍都会 new 一个 RobotExecutor, 放实例上等于每拍清零。
    # 🔴 2026-11-01 老倪「修」—— 但共享不能无脑共享:
    #   ① 跨线程: 画布线程 + GUI/调试线程会同时进来 ⇒ 加锁, 否则两个线程各写一半
    #   ② 跨轮次: 上一轮最后拍留在这里, 下一轮第一拍拿它差分 ⇒ 必误报"变化率超限"
    #      ⇒ 记 rstamp, 间隔 > _RATE_STALE_S(默认 2s) 视为新周期, **不判变化率**并在 why 说明
    _LAST = None
    _LAST_T = 0.0
    _RATE_STALE_S = float(os.environ.get("ZMAX_RATE_STALE_S", "2.0"))
    _LOCK = threading.Lock()

    @classmethod
    def reset(cls, why=""):
        """显式清账: 新一轮/换臂/调试重跑时调一次, 避免拿上一轮末拍做差分。"""
        with cls._LOCK:
            cls._LAST = None
            cls._LAST_T = 0.0
            cls._LAST_WHY = why or "reset()"
        return True

    def __init__(self, n_joints=6, max_rate=0.35):
        # 🔧 2026-10-14 修 (真源一致性): 原写 `n_joints=7` + 注释"7 轴冗余臂 (Sawyer)";
        #   本平台真机是珞石 Z700 = **6 轴** (config/calib/zmax_calib.json 的 robot.dof=6),
        #   Sawyer 注释是早期遗留。全仓检索确认: 该属性除了这里赋值**没有任何消费点**
        #   (execute() 只做 np.asarray(u)), 所以改成与真机一致的 6 —— 不影响行为, 只去掉误导。
        self.n_joints = n_joints  # 珞石 Z700 · 6 轴 (未被消费的登记属性)
        self.max_rate = float(max_rate)   # 每拍最大指令变化 (归一化单位/拍)
        self.last_check = {"valid": True, "clip_hint": [], "over_rate": [], "why": []}

    def execute(self, u, allow_traj_fallback=False):
        """状态空间工程的最终输出 = **action**(位姿/指令), 校验后原样返回; 结论在 self.last_check。

        老倪 2026-11-14:「return a? 你的代码怎么还是 a? 应该是 action, 改」
          ⇒ 变量名统一叫 action —— 与 out1.action / action.json 同名, 看代码不用翻译。
        """
        action = np.asarray(u, dtype=float).ravel()
        chk = {"valid": True, "clip_hint": [], "over_rate": [], "why": [], "n": int(action.size)}
        # ① NaN/Inf: 脏数不往外送
        if not np.isfinite(action).all():
            chk.update(valid=False, why=chk["why"] + ["指令含 NaN/Inf → 整条归零"])
            action = np.zeros_like(action)
        # ② 通道范围 (只记不裁, 裁剪权在 sslimit)
        for _i, _v in enumerate(action):
            if abs(float(_v)) > self._LIMIT:
                chk["clip_hint"].append([int(_i), round(float(_v), 4)])
        # ③ 变化率: 物理上臂跟不上 (NaN 归零后不再算 —— 否则"归零"本身会被误报成轴跳变)
        _now = time.time()
        chk["cycle"] = "seq"
        with RobotExecutor._LOCK:
            prev, prev_t = RobotExecutor._LAST, RobotExecutor._LAST_T
            _gap = (_now - prev_t) if prev_t else 0.0
            if not chk["valid"]:
                pass                                     # 已归零, 不参与差分
            elif prev is None:
                chk["cycle"] = "首个指令"
            elif prev.shape != action.shape:
                chk["cycle"] = "维度变化(%d→%d) ⇒ 不判变化率" % (prev.size, action.size)
            elif _gap > RobotExecutor._RATE_STALE_S:
                # 上一拍是别的轮次/上次运行留下的 ⇒ 拿它差分没有物理意义
                chk["cycle"] = "新周期(间隔 %.2fs>%.1fs) ⇒ 不判变化率" % (_gap, RobotExecutor._RATE_STALE_S)
            else:
                d = np.abs(action - prev)
                over = np.where(d > self.max_rate)[0]
                if over.size:
                    chk["over_rate"] = [[int(_i), round(float(d[_i]), 4)] for _i in over]
                    chk["why"] = chk["why"] + ["变化率超 %.2f/拍: 轴 %s"
                                               % (self.max_rate, [int(_i) for _i in over])]
            RobotExecutor._LAST = action.copy()
            RobotExecutor._LAST_T = _now
        # ── ④ 🚦 输出仲裁(老倪 2026-11-14): 算错的判据三条(任一命中) ⇒ 直接输出 215 点真轨迹
        #    allow_traj_fallback 默认 False ⇒ 与改造前逐位一致(零回归)
        chk["fallback"] = None
        _need_fb = (not chk["valid"]) or bool(chk["clip_hint"]) or bool(chk["over_rate"])
        if _need_fb and allow_traj_fallback:
            _t = traj215_target()
            if _t is not None:
                chk["fallback"] = "traj215:第 %d/%d 点" % (_t["cursor"], _t["total"])
                chk["traj_joint_deg"] = _t["joint_deg"]
                chk["traj_p_mm"] = _t["p_mm"]
                chk["traj_pose"] = _t.get("pose")
                chk["out_dim"] = 6
                self.last_check = chk
                _a = self._act_traj215(_t, chk)
                self._print_action(_a, chk, tag="回退")
                return _a
            chk["fallback"] = "hold(不直驱 · 轨迹通道照常)"
        elif _need_fb:
            chk["fallback"] = "hold(不直驱 · 轨迹通道照常)"
        self.last_check = chk
        # ⑤ 正常档: 输出**位姿**(当前位姿 + u·dt), 不是那个速度数组 —— 老倪 2026-11-14
        #    变量名仍叫 action: 在 VSCode 里对 `return action` 打红点, 看到的就是位姿口径的 action
        action = self._act_ss(action, chk)
        # 🎯 2026-11-14 老倪「这里断也没有对上」：直驱闸没放行时，节点层会把直驱换成 215 点。
        #    换口径前移到执行器 ⇒ 断点里看到的 action 就是**真正下发**的那份，不会再看错。
        action = self._effective(action, chk)
        self._print_action(action, chk)
        return action

    @staticmethod
    def _effective(act, chk):
        """把「本拍真正下发的 action」算出来(与节点层同一判断, 只此一处口径)。

        · 直驱闸放行(guard.allow) ⇒ 保持 src=ss 的直驱位姿
        · 没放行 ⇒ 换成 215 点当前点(关节+位姿+夹爪计划), 并把直驱速度留在 u 里溯源
        关掉: ZMAX_EXEC_EFFECTIVE=0(退回"执行器只出直驱, 由节点层换口径"的旧行为)
        """
        if str(os.environ.get("ZMAX_EXEC_EFFECTIVE", "1")).strip() in ("0", "false", "False"):
            return act
        if str(act.get("src")) != "ss":
            return act
        try:
            from . import direct_drive_guard as _g
            v = _g.last() or {}
        except Exception:                                          # noqa: BLE001
            v = {}
        if v.get("allow"):
            return act
        _t = traj215_target()
        if _t is None:
            return act
        _a = RobotExecutor._act_traj215(_t, chk)
        _why = "215 点回放 · 直驱闸未放行(mode=%s ok=%s/%s)" % (
            v.get("mode"), v.get("ok_ticks"), v.get("need"))
        _a["why"] = _why
        _a["fallback"] = _a.get("fallback") or "直驱闸未放行 ⇒ 215 点"
        _a["dd_u"] = [float(x) for x in (act.get("u") or [])]      # 保留直驱速度, 便于溯源
        _a["dd_pose"] = act.get("pose")
        _a["total"] = _t.get("total")
        return _a

    # ─────────────────────── 🖨 终端可见的实时位姿(return action 之前) ───────────────────────
    @staticmethod
    def _print_action(act, chk=None, tag=""):
        """一行打印这一拍的位姿: **目标 vs 实测 vs 差额** —— 让终端和机器人屏幕能直接对账。

        老倪 2026-11-14: 「return action 这之前, 增加一个 print 打印实时位姿, 终端也能看到
        实际的位姿」。所以打在 return 之前: 断点/单步(F10)时, 终端这一行就是这一拍的结论。
        关掉: ZMAX_ACTION_PRINT=0
        """
        try:
            if str(os.environ.get("ZMAX_ACTION_PRINT", "1")).strip() in ("0", "false", "False"):
                return
            if not isinstance(act, dict):
                return
            now = tcp_pose_now() or {}
            _p = act.get("pose") or {}
            tx = act.get("x", _p.get("x"))
            ty = act.get("y", _p.get("y"))
            tz = act.get("z", _p.get("z"))
            ta = act.get("a", _p.get("a"))
            tb = act.get("b", _p.get("b"))
            tc = act.get("c", _p.get("c"))
            d_mm = None
            if None not in (tx, ty, tz) and now.get("x") is not None:
                d_mm = math.dist([tx, ty, tz], [now["x"], now["y"], now["z"]])
            g = act.get("grip_mm")
            gs = act.get("grip_state") or ""
            print("[action]%s i=%s/%s src=%s 目标 %.2f/%.2f/%.2f · %.2f/%.2f/%.2f | "
                  "实测 %s/%.2f/%.2f · %.2f/%.2f/%.2f (age %ss) | Δ=%s mm | 夹爪 %s mm %s" % (
                      (" " + tag) if tag else "",
                      act.get("i") if act.get("i") is not None else "-",
                      act.get("total") or 215, act.get("src"),
                      tx if tx is not None else float("nan"), ty if ty is not None else float("nan"),
                      tz if tz is not None else float("nan"),
                      ta if ta is not None else float("nan"), tb if tb is not None else float("nan"),
                      tc if tc is not None else float("nan"),
                      ("%.2f" % now["x"]) if now.get("x") is not None else "读不到",
                      now.get("y") or float("nan"), now.get("z") or float("nan"),
                      now.get("a"), now.get("b"), now.get("c"), now.get("age_s"),
                      ("%.2f" % d_mm) if d_mm is not None else "?",
                      g if g is not None else "?", gs)
                  + (" | 下发=%s" % _eff_out(act)))
        except Exception:                                       # noqa: BLE001
            pass

    # ────────────────────────── 位姿口径的 action 构造 ──────────────────────────
    _DT0 = 0.0                      # 上一拍时间戳(跨实例共享, 与 _LAST 同一理由)
    _DT_MIN, _DT_MAX = 0.01, 0.5    # 单拍积分步长夹紧(10ms~500ms), 不让长间隔放大位移

    def _dt(self):
        _now = time.time()
        _t0 = RobotExecutor._DT0
        dt = 0.1 if not _t0 else min(max(_now - float(_t0), self._DT_MIN), self._DT_MAX)
        RobotExecutor._DT0 = _now
        return float(dt)

    @staticmethod
    def _joints_now():
        """实测关节角(deg)。读不到/过期 ⇒ None(绝不编)。"""
        try:
            p = os.path.join(_ROOT_, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
            if time.time() - os.path.getmtime(p) > 2.0:
                return None
            _j = json.load(open(p, encoding="utf-8")).get("joint") or []
            _d = [round(math.degrees(float(v)), 4) for v in _j][:6]
            return _d if len(_d) == 6 else None
        except Exception:                                                  # noqa: BLE001
            return None

    @staticmethod
    def _grip_ss():
        try:
            from . import action_bus as _ab
            _m, _age = _ab.grip_meas()
        except Exception:                                                  # noqa: BLE001
            _m, _age = None, None
        return {"grip_mm": _m, "grip_act": "hold",
                "grip_state": (None if _m is None else ("开" if _m > 1.0 else "合")),
                "grip_src": "保持实测(ss 档暂无夹爪通道)",
                "grip_meas_mm": _m,
                "grip_meas_age_s": (None if _age is None else round(_age, 1))}

    def _act_ss(self, u_arr, chk):
        """src=ss: action.pose = 实测位姿 + u·dt(mm), 关节=实测(未做 IK, 明确标注)。"""
        dt = self._dt()
        u4 = [round(float(x), 6) for x in np.asarray(u_arr, dtype=float).ravel()[:4]]
        pose_now = tcp_pose_now()
        pose = None
        if pose_now is not None:
            pose = dict(pose_now)
            _v = np.asarray(u_arr, dtype=float).ravel()[:3]
            if _v.size == 3 and bool(np.isfinite(_v).all()):
                pose.update(x=round(float(pose_now["x"]) + float(_v[0]) * 1000.0 * dt, 2),
                            y=round(float(pose_now["y"]) + float(_v[1]) * 1000.0 * dt, 2),
                            z=round(float(pose_now["z"]) + float(_v[2]) * 1000.0 * dt, 2),
                            src="pos+u*dt(直驱)", dt_s=round(dt, 4))
        _j = self._joints_now()
        act = Action(kind="action", src="ss", i=None, pose=pose,
                     joints_deg=_j, joints_src=("实测(未做IK)" if _j else "缺"),
                     u=u4, cmd=np.asarray(u4, dtype=float),
                     check=chk, fallback=chk.get("fallback"),
                     why="位姿 = 当前位姿 + u*dt(%.3fs)" % dt,
                     ts=time.time(), dt_s=round(dt, 4))
        act.update(self._grip_ss())
        return act

    @staticmethod
    def _act_traj215(t, chk):
        """src=traj215: action = 215 点真值(位姿 + 6 维关节 + 夹爪计划)。"""
        try:
            from . import action_bus as _ab
            _g = _ab.grip_at(t["cursor"], t["total"])
        except Exception:                                                  # noqa: BLE001
            _g = {"grip_mm": None, "grip_act": "hold", "grip_state": None,
                  "grip_src": "缺", "grip_meas_mm": None, "grip_meas_age_s": None}
        act = Action(kind="action", src="traj215", i=int(t["cursor"]),
                     pose=t.get("pose"), joints_deg=list(t["joint_deg"]),
                     joints_src="215点轨迹",
                     u=[], cmd=np.asarray(t["joint_deg"], dtype=float),
                     check=chk, fallback=chk.get("fallback"),
                     why="215 点真轨迹(算错 ⇒ 回放真值, 不是速度)", ts=time.time())
        act.update(_g)
        return act


class PhysicalWorld:
    """🌍 物理世界 — 执行结果 → 传感器反馈 z_k"""

    # 🧮 2026-08-18 老倪: 硬件属性 (Z700 光模块工厂机械臂 — 画布节点展示用)
    #   质量/惯量/自由度 = 真机规格 (VLA 触觉 58D 工程对应 Z700F); 仿真参数 = 引擎常量
    HARDWARE_SPEC = {
        "自由度": "7 (6×旋转关节 J1–J6 + 夹爪开合)",
        "关节配置": "J1–J6 旋转关节 (±170°~±360°) + 末端电动两指夹爪",
        "整机质量": "24.5 kg (Z700 臂), 末端执行器 1.2 kg",
        "额定负载": "3 kg (抓取光模块 0.15 kg ≪ 额定)",
        "末端惯量": "0.08 kg·m² (负载 0.15kg @ 0.3m 臂展)",
        "重复定位精度": "±0.02 mm (光模块插拔需求 ≤0.1mm)",
        "工作半径": "0.8 m",
        "夹爪行程": "0–35 mm, 最大夹持力 12 N",
        "力觉": "6D 力/力矩传感器 (z 向推力 0.03–12 N 分辨率 0.01N)",
        "触觉": "4D 触觉 (夹爪开度/接触 0-1 开关量)",
        "视觉": "RGB-D (Orin 侧 39D 观测: 位置/夹爪/速度/peg/孔位/姿态)",
        "接触刚度": "6.0 N/m (仿真参数)",
        "接触半径": "0.02 m (peg 半径, 仿真参数)",
        "插入深度阈值": "0.004 m (仿真参数, 插入完成判定)",
        "传感器噪声 σ": "0.005 (仿真参数, 卡尔曼校正残差来源)",
    }

    def __init__(self, noise=0.005, seed=42):
        self.noise = noise          # 传感器噪声 σ (卡尔曼校正的残差来源)
        self._rng = np.random.default_rng(seed)

    # 🧮 2026-08-18 老倪: 每轴电机参数 (Z700 6 旋转关节 + 夹爪直驱, 协作臂级规格)
    AXIS_MOTORS = [
        # (轴, 额定扭矩 N·m, 峰值扭矩 N·m, 额定转速 rpm, 减速比, 转子惯量 kg·m², 功率 W)
        ("J1 肩部", 12.0, 30.0, 1200, 101.0, 0.00032, 1500),
        ("J2 肩部", 12.0, 30.0, 1200, 101.0, 0.00032, 1500),
        ("J3 肘部", 6.0, 15.0, 1500, 81.0, 0.00024, 940),
        ("J4 肘部", 6.0, 15.0, 1500, 81.0, 0.00024, 940),
        ("J5 腕部", 3.0, 8.0, 1800, 51.0, 0.00018, 560),
        ("J6 腕部", 3.0, 8.0, 1800, 51.0, 0.00018, 560),
        ("夹爪直驱", 0.15, 0.40, 3000, 1.0, 0.00002, 45),
    ]

    # 🧮 2026-08-18 老倪: 各臂段质量 (kg) + 质心位置 (m, 沿该段轴线) — 总和 = 整机 24.5 kg
    ARM_SEGMENTS = [
        # (段, 质量 kg, 质心 m, 长度 m)
        ("底座", 5.0, 0.05, 0.12),
        ("J1 段 (肩)", 4.6, 0.18, 0.35),
        ("J2 段 (大臂)", 4.2, 0.28, 0.55),
        ("J3 段 (肘)", 3.4, 0.15, 0.30),
        ("J4 段 (小臂)", 2.8, 0.21, 0.42),
        ("J5 段 (腕)", 2.0, 0.12, 0.24),
        ("J6 段 (末端)", 1.3, 0.08, 0.16),
        ("末端夹爪", 1.2, 0.06, 0.12),
    ]

    @property
    def total_mass(self):
        """整机总质量 = 各臂段质量之和 (kg)"""
        return round(sum(s[1] for s in self.ARM_SEGMENTS), 2)

    def generalized_mass(self, q=None):
        """广义质量矩阵 M(q) (7×7) — 典型位形下每轴等效惯量 (kg·m²)
        对角线 = 电机转子惯量×减速比² + 臂段负载贡献; 非对角 = 简化耦合项
        q=None → 竖直零位 (J2 大臂垂直向下) 的典型值"""
        n = len(self.AXIS_MOTORS)
        M = np.zeros((n, n))
        for i, (_, _, _, _, ratio, rotor_i, _) in enumerate(self.AXIS_MOTORS):
            M[i, i] = round(rotor_i * ratio * ratio + 0.32, 3)   # 转子贡献 + 臂段负载等效
        # 相邻轴耦合 (简化: 相邻关节运动耦合 5%)
        for i in range(n - 1):
            M[i, i + 1] = M[i + 1, i] = round(0.05 * min(M[i, i], M[i + 1, i + 1]), 3)
        return M

    @property
    def hardware(self):
        """硬件属性 dict (质量/惯量/自由度等) — 画布节点展示"""
        return dict(self.HARDWARE_SPEC)

    def observe(self, state):
        """返回传感器观测 z_k (带高斯噪声, 供卡尔曼校正)"""
        s = np.asarray(state, dtype=float)
        return s + self._rng.normal(0.0, self.noise, size=s.shape)
