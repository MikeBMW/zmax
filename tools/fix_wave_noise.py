#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_wave_noise.py — 信号页波形"看着像噪声/一块面积/跳变"的真修。

老倪 2026-10-15 目检: 「时间轴位在 5 秒左右, 八阶段信号波形范围已经到 6, 当前值显示 2, 视觉上不是一条线,
跳变到 5 6 等值, 能看到一块多出来的绿色面积; 接触概率 末端_x 也有类似的显示问题; 好像是有噪声」

两个真根因 (都在源码里):
 ① **ds.* (DDS 话题) 信号的 x 是 time.monotonic()** ⇒ 与场景信号(回放进度 0~40s)差 ~25965s 的天文数字。
    点一次 Fit/适配, X 被拉到 0~25980 ⇒ 场景曲线被压成一个点, 而 ds 曲线在原 x 处上下来回(值 0..7 跳变)
    ⇒ 视觉上就是「一块多出来的绿色面积」+「跳变到 5/6」。
 ② **3D 面板回放会绕圈 (一趟跑完从头再来)**: 每趟都从 t_s≈0 重新写 x, 而缓冲把历史趟全留着并只按 x 排序
    ⇒ 同一个 x 上叠着第 1 趟和第 2 趟的点, 连成折线就在两趟之间上下乱跳 ⇒ 「不是一条线/像噪声」。
    (接触概率 / 末端_x 是场景信号, 就是栽在②上)

修法:
 ① ds.* 映射到**同一根主钟**: 用 3D 快照那一刻的 (ts, 时间_s) 锚点把总线帧的 wall 时刻映射成回放秒,
    x = 回放秒_now + (t_帧 − ts_now); 并把该信号标成 scene=True (与场景信号同轴同画法)。
 ② 检测**新一趟** (回放秒比上一拍回跳 > 2s; 含手动拖进度条回看) ⇒ 清掉所有 scene 缓冲, 本趟从当前位置
    重新铺一条线; 状态里记 趟号 + 清空次数, 日志留一行 (不许静默)。
 ③ 顺带去重: 同一 key 连续 (x, v) 完全相同则不再入缓冲 (30Hz 重复点堆叠只会让线变粗/变花)。
"""
from __future__ import annotations

import io
import os
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "canoe_graphic.py")
s = io.open(P, encoding="utf-8").read()
orig = s
n = 0


def rep(old, new, cnt=1):
    global s, n
    assert old in s, "锚点没找到: %r" % old[:70]
    s = s.replace(old, new, cnt)
    n += 1


# ── ① 缓冲去重 (同 x 同 v 不再入) ────────────────────────────────────────────
rep('''    def push(self, t, v, age=-1.0):
        i = self.head''',
    '''    def push(self, t, v, age=-1.0):
        # 🔁 去重: 同一个 key 连续两次 (x, v) 完全相同 ⇒ 不再入缓冲。
        #   30Hz 轮询同一份快照会重复写同一点, 画出来只是把线加粗、视觉上更像"噪点团"。
        if self.n and self.last_val is not None and v == self.last_val:
            _j = (self.head - 1) % CAP
            if self.t[_j] == t:
                self.age = age
                self.wall = time.time()
                return
        i = self.head''')

# ── ② SignalStore: 主钟锚点 + 清场景缓冲 ─────────────────────────────────────
rep('''    def __init__(self):
        self.lock = threading.Lock()
        self.bufs = {}
        self.t0 = time.time()          # 🌍 统一用 epoch: 波形 x = t - t0 ⇒ 能换算回绝对时刻
        self.total_pts = 0''',
    '''    def __init__(self):
        self.lock = threading.Lock()
        self.bufs = {}
        self.t0 = time.time()          # 🌍 统一用 epoch: 波形 x = t - t0 ⇒ 能换算回绝对时刻
        self.total_pts = 0
        # 🎬 主钟锚点 (墙钟 ts, 回放秒 时间_s) —— 3D 面板快照那一刻的对应关系。
        #   所有"自带别的钟"的源 (尤其是 ds.* DDS 话题) 都用它映射到同一根钟, 否则 x 差 2 万秒。
        self.pb_anchor = None
        self.lap = 1                   # 回放趟号 (3D 面板绕圈一次 +1)
        self.lap_clears = 0            # 新一趟清过几次 (取证用)

    def clear_scene(self, why=""):
        """新一趟回放 (或拖进度条回看) 时清掉**场景钟**的缓冲: 避免两趟点叠在同一 x 上画成"噪声"。

        只清 scene=True 的键 (场景/话题信号); 墙钟到达类信号不动。返回清掉的键数。
        """
        hit = 0
        with self.lock:
            for b in self.bufs.values():
                if getattr(b, "scene", False) and b.n:
                    b.clear()
                    hit += 1
            self.lap_clears += 1
        return hit''')

# ── ③ HostJsonSource: 写锚点 + 检测新一趟 ───────────────────────────────────
rep('''                if _st is not None and _ts is not None and prefix == "sstrace":
                    now, _scene = float(_st), True                  # 3D 面板快照: 回放进度 = 主钟
                    self._pb_sync = (float(_ts), float(_st))
                    self._scene_epoch = float(_ts) - float(_st)     # x → 绝对时刻 的偏移 (轴标签用)''',
    '''                if _st is not None and _ts is not None and prefix == "sstrace":
                    now, _scene = float(_st), True                  # 3D 面板快照: 回放进度 = 主钟
                    self._pb_sync = (float(_ts), float(_st))
                    self._scene_epoch = float(_ts) - float(_st)     # x → 绝对时刻 的偏移 (轴标签用)
                    # 🌍 锚点给全页共用 (ds.* 等自带别的钟的源靠它对齐; 见 SignalStore.pb_anchor)
                    self.store.pb_anchor = (float(_ts), float(_st))
                    # 🔄 新一趟回放检测: 回放秒比上一拍**回跳 > 2s** ⇒ 3D 面板绕回起点 (或老倪拖进度条回看)。
                    #   不清的话: 第 1 趟和第 2 趟的点叠在同一个 x 上, 连成折线在两趟之间上下跳 ⇒
                    #   目检就像"噪声/一块面积/跳变到 5 6"(老倪 2026-10-15 报的就是这个)。
                    _prev = getattr(self, "_pb_t_prev", None)
                    if _prev is not None and float(_st) < _prev - 2.0:
                        _hit = self.store.clear_scene("新一趟回放/拖回看")
                        self.store.lap += 1
                        try:
                            self.store.note("▶ 第 %d 趟回放 (回放秒 %.1f→%.1f): 清掉上一趟的 %d 条波形, "
                                            "本趟从当前位置重新铺 (两趟叠画会看着像噪声)"
                                            % (self.store.lap, _prev, float(_st), _hit))
                        except Exception:
                            pass
                    self._pb_t_prev = float(_st)''')

# ── ④ DataSpaceTraceSource: x 用主钟映射 (不再是 monotonic) ─────────────────
rep('''        vals = parse_ds_digest(rec.get("digest"))
        pref = "ds." + topic.lstrip("/") + "."
        # 帧龄 = 本机收到该帧的年龄 (总线帧本身就是落盘时刻)
        self.store.push_many({pref + k: v for k, v in vals.items()},
                             time.monotonic(), src="ds")''',
    '''        vals = parse_ds_digest(rec.get("digest"))
        if not vals:
            return
        pref = "ds." + topic.lstrip("/") + "."
        # 🕒 **x 必须是主钟 (3D 回放进度秒), 不能是 time.monotonic()**。
        #   踩过的坑 (老倪 2026-10-15「一块多出来的绿色面积/跳变到 5 6/好像有噪声」): ds.* 原用
        #   time.monotonic() 当 x (~25965), 与场景信号的回放秒 (0~40) 差 2 万秒 ⇒ 一按 Fit, X 被拉到
        #   0~25980, 场景曲线压成一个点, ds 曲线在自己那格上下乱跳, 看着就是"一块绿色面积"。
        #   锚点 = 3D 快照那一刻的 (墙钟 ts, 回放秒 时间_s) ⇒ x = 回放秒_now + (帧时刻 − ts_now)。
        _anc = getattr(self.store, "pb_anchor", None)
        _tw = rec.get("t")
        if _anc is not None:
            x = float(_anc[1]) + ((float(_tw) - float(_anc[0])) if isinstance(_tw, (int, float)) else 0.0)
            _scene = True
        else:
            # 还没有锚点 (3D 面板还没出过快照): 先按到达时刻铺, 标 scene=False —— 一旦有锚点就自动归到主钟。
            #   **不静默**: 目录里该信号会带"等 3D 快照对齐"的注记。
            x, _scene = time.time(), False
        self.store.push_many({pref + k: v for k, v in vals.items()},
                             x, src="ds", scene=_scene)''')

assert s != orig
io.open(P, "w", encoding="utf-8").write(s)
print("已改 %d 处 → %s" % (n, P))
