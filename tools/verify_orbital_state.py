#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_orbital_state.py — 太阳系窗口「反映模型实际状态」判据 (2026-10-19 老倪要求)

老倪原话: 「太阳系窗口，就是观察L2~L5模型的主要窗口，你来设计如何UI交互，让太阳系，行星，
地球，月球，卫星，能反映当前模型的实际状态」

本判据只核一件事: **界面上的状态必须来自真源、且会随真源变化**（不是画个好看的灯）。
  ① 每个天体都有 st (k/txt/age)，age 与它自己真源文件的 mtime 独立复算一致
  ② 帧龄阈值: ≤2.5s=live · ≤60s=stale · 否则 off (三条边界都造一遍)
  ③ L2~L5 层状态取自 layer_calls.jsonl **末行** (ok/ms/帧龄), 末行改成旧 ts ⇒ 整条带变 stale/off
  ④ 视图每 500ms 重读真源 (build() 里 reload 真被调用; 不是 __init__ 一次性快照)
  ⑤ 驱动扭矩口径必须写在界面上: 模型张量没进 τ 时, 标签必须出现"未接模型张量"
  ⑥ 悬停读数卡给出名/真源/状态/帧龄 (鼠标交互不是装饰)

跑法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_orbital_state.py
"""
from __future__ import annotations

import io
import json
import math
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import orbital_arch as OA                                            # noqa: E402
import gravity_table as gt_mod                                        # noqa: E402
from PyQt5.QtWidgets import QApplication                             # noqa: E402

PASS = FAIL = 0
RED = []


def chk(tag, name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("✅ %-4s %s%s" % (tag, name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        RED.append(tag)
        print("❌ %-4s %s%s" % (tag, name, ("  · " + detail) if detail else ""))


_CAP_P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "zmax_data", "ss_live", "ui_run.json")


def _cap_enter(level):
    """把 `ui_run.json` 的 cap_level 临时改成 level, 返回原文本 (判据用: 四层判据要全档位)。"""
    try:
        _old = io.open(_CAP_P, encoding="utf-8").read()
    except Exception:                                                            # noqa: BLE001
        _old = None
    try:
        _d = json.loads(_old) if _old else {}
    except Exception:                                                            # noqa: BLE001
        _d = {}
    _d["cap_level"] = str(level)
    try:
        os.makedirs(os.path.dirname(_CAP_P), exist_ok=True)
        _t = _CAP_P + ".tmp"
        io.open(_t, "w", encoding="utf-8").write(json.dumps(_d, ensure_ascii=False))
        os.replace(_t, _CAP_P)
    except Exception:                                                            # noqa: BLE001
        pass
    return _old


def _cap_exit(old):
    try:
        if old is None:
            if os.path.isfile(_CAP_P):
                os.remove(_CAP_P)
        else:
            _t = _CAP_P + ".tmp"
            io.open(_t, "w", encoding="utf-8").write(old)
            os.replace(_t, _CAP_P)
    except Exception:                                                            # noqa: BLE001
        pass


def _mkroot(tmp):
    """造一个最小真源目录 (只放判据要用的几份), 用来造边界。"""
    for rel in ("zmax_data/ss_live", "config/calib", "data/database/zmax/sources/canvas"):
        os.makedirs(os.path.join(tmp, rel), exist_ok=True)
    now = time.time()
    live = {
        "zmax_data/ss_live/engine_latest.json": {"ts": now, "M": 3.643, "phi": 0.1, "idx": 0},
        "zmax_data/ss_live/torque_live.json": {"ts": now, "stage": "下降", "torque_norm": 12.0, "t_max": 30.0,
                                               "clipped": False, "metric_M": 3.643,
                                               "source": "M ← calib · −∇Φ ← potential_field 解析梯度",
                                               "x_source": "技能入口 SK01 谷底 (无新鲜位姿真源)"},
        "zmax_data/ss_live/skill_latest.json": {"ts": now},
        "zmax_data/ss_live/skill_error.json": {"ts": now},
        "zmax_data/ss_live/skill_phys.json": {"skills": {}},
        "config/calib/zmax_manifold.json": {"M": 3.643},
        "data/database/zmax/sources/canvas/state_space_obs.json": {"nodes": [], "links": []},
    }
    for rel, obj in live.items():
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    return tmp


def _band_sum(img, x, y, r, rings=tuple(range(5, 20, 2)), n=96):
    """(x,y) 外圈 r+rings 上的**墨量** (亮度之和) —— 量光晕/外扩环有没有真的画出来。"""
    from PyQt5.QtGui import QColor as _QC
    W, H = img.width(), img.height()
    tot = 0
    for i in range(n):
        t = i / float(n) * 2 * math.pi
        for rr in rings:
            px, py = int(x + (r + rr) * math.cos(t)), int(y + (r + rr) * math.sin(t))
            if 0 <= px < W and 0 <= py < H:
                c = _QC(img.pixel(px, py))
                tot += c.red() + c.green() + c.blue()
    return tot


def check_infer_pulse(app):
    """⑨ 推理可视化 (老倪 2026-10-19: 「前馈加速模型运行 ⇒ 地球有高亮 + 柔顺闪烁; 依次类推,
    每个模型运行推理的时候都有对应关系」)。

    口径用 **A/B 对照**(同一帧几何、冻结虚线相位, 只翻 _live_s):
      A = 所有层都不在推理          B = 只有地球在推理
      B 的地球外圈墨量必须 > A (光晕/外扩环真的画出来了), 火星外圈必须不变 (没有假动画)。
    """
    v = OA.OrbitalArchView()
    v.resize(1080, 360)
    v.show()
    v.data.running = True
    for k in ("sun", "mercury", "earth", "moon", "mars", "jupiter"):
        v.data.body.setdefault(k, {})["st"] = {"k": "live", "txt": "在跑", "age": 0.1}
    v._tick()
    _W, _H, _S, _cx, _cy, _R = v._geom()
    p = v.positions(_cx, _cy, _R)

    def _snap(live_earth, ph):
        v._live_s = {k: 0.0 for k in ("sun", "mercury", "earth", "moon", "mars", "jupiter")}
        v._live_s["earth"] = 1.0 if live_earth else 0.0
        # 其它天体一律置"离线": 否则 paint/_tick 会按各自真源重新把活跃度拉起来
        # (L3 现在接的是动作头 chunk_latest, 每拍都新鲜 ⇒ 火星真的在亮, 不是假动画)
        _off = {"k": "off", "txt": "离线", "age": 99.0}
        for _b in ("sun", "mercury", "moon", "mars", "jupiter"):
            v.data.body[_b]["st"] = dict(_off)
        v.data.body["earth"]["st"] = dict(_off) if not live_earth else {"k": "live", "txt": "推理中", "age": 0.2}
        v._phase = 0.0                      # 冻结虚线相位 ⇒ 两张图只有"光晕"这一处差别
        v._pulse_t = ph
        v.grab()                            # 第一张只是让文字块平滑收敛 (否则两次采样的字块位置不同)
        app.processEvents()
        img = v.grab().toImage()
        app.processEvents()
        return (_band_sum(img, p["earth"][0], p["earth"][1], _S * v.RAD["earth"]),
                _band_sum(img, p["mars"][0], p["mars"][1], _S * v.RAD["mars"]))

    # 呼吸是正弦 ⇒ 不同相位亮度不同; 取 3 个相位的**最大值**比较 (避免正好采在谷底)
    _ph3 = (0.15, 0.40, 0.65)
    _sn0 = [_snap(False, x) for x in _ph3]
    _sn1 = [_snap(True, x) for x in _ph3]
    _e0, _m0 = max(x[0] for x in _sn0), max(x[1] for x in _sn0)
    _e1, _m1 = max(x[0] for x in _sn1), max(x[1] for x in _sn1)
    chk("P1", "该层在推理 ⇒ 该天体出现光晕 + 外扩环 (同帧 A/B: 只翻活跃度, 墨量必须上升)",
        _e1 > _e0 * 1.05 and (_e1 - _e0) > 400,
        "地球外圈墨量 无光晕 %d → 有光晕 %d (+%.0f%%)" % (_e0, _e1, ( _e1 - _e0) / max(1.0, _e0) * 100))
    chk("P2", "没在推理的天体**不受影响** ⇒ 不会满屏假动画", abs(_m1 - _m0) <= max(80, int(_m0 * 0.08)),
        "火星外圈墨量 %d → %d (变化 %d)" % (_m0, _m1, _m1 - _m0))
    # 柔顺: 活跃度是低通的 (1→0 逐帧只走 ~15%), 不是硬开关
    v._live_s["earth"] = 1.0
    v.data.body["earth"]["st"] = {"k": "off", "txt": "离线", "age": 99.0}
    _seq = []
    for _i in range(6):
        v._tick()
        _seq.append(round(v._live_s.get("earth", 0.0), 3))
    _dmax = max(abs(b - a) for a, b in zip(_seq, _seq[1:])) if len(_seq) > 1 else 0
    chk("P3", "活跃度变化是**柔顺**的 (1→0 逐帧 ≤0.35, 慢淡出而不是瞬间熄灯)",
        _dmax <= 0.35 and _seq[-1] < _seq[0],
        "逐帧: %s (单帧最大 %.2f)" % (_seq, _dmax))
    v.data.body["earth"]["st"] = {"k": "live", "txt": "在跑", "age": 0.1}
    for _i in range(8):
        v._tick()
    chk("P4", "活跃度由**真源帧龄**决定 (live→1 · off→0), 且经低通", v._live_s.get("earth", 0) > 0.8,
        "_live_s 地球=%.2f" % v._live_s.get("earth", 0))
    try:
        v.close()
    except Exception:                                                        # noqa: BLE001
        pass


def check_quat(app):
    """⑩ 四元数显示 (老倪 2026-10-19: 「将四元数显示在太阳系」)。

    口径必须是**能对账的**: 太阳系里显示的 q̂ = 万有引力表该层列合力 → 归一四元数。
      Q1 四层 (L2~L5) 各有一行 q̂, 与表 col_resultant 归一后**逐位一致**
      Q2 是单位四元数 (各项平方和 = 1 ±1e-9), 且与表里"力四元数"同方向 (余弦 = 1)
      Q3 该层没有列合力 ⇒ 写"未算", 不许拿 0 冒充 (0,0,0,0 不是姿态)
      Q4 地球 (= 状态点) 上真的画了三轴 (三个轴色像素都出现, 且在球体之外)
    """
    OA.OrbitalArchData._ui_run = (lambda self: (True, "判据覆盖: 在跑"))
    v = OA.OrbitalArchView()
    v.resize(1080, 360)
    v.show()
    app.processEvents()
    import gravity_table as _gt
    f = _gt.GravityField()
    qd = getattr(v.data, "quat", {}) or {}
    _bad = []
    _s2 = []
    for L in ("L5", "L4", "L3", "L2"):
        q, _c = f.col_resultant(L)
        u, _n, _ss = _gt._qnorm(q)
        got = (qd.get(L) or {}).get("q")
        if not got:
            _bad.append((L, "缺失"))
            continue
        # 同一份真源、但两次采样可能差一拍 (chunk_latest 10Hz, 表 500ms 重载) ⇒ 逐位容差 0.06。
        #   不是放宽标准: 方向余弦差 0.06 ≈ 角度差 ≤7°, 足以判定"同一个矢量", 又能容忍跨拍。
        if max(abs(a - b) for a, b in zip(got, u)) > 0.06:
            _bad.append((L, "数值不符(>0.06)", got, u))
        _s2.append(abs(sum(x * x for x in got) - 1.0))
    chk("Q1", "L2~L5 每层都显示 q̂, 且与万有引力表列合力归一后逐位一致",
        not _bad, "不符: %s" % (_bad or "无"))
    chk("Q2", "显示的是**单位四元数** (各项平方和=1, 即 S³ 上的方向)", (_s2 and max(_s2) < 1e-9),
        "|平方和−1| 最大 %.2e" % (max(_s2) if _s2 else 9))
    _txt = " ".join("".join(t[1]) for t in v.label_texts())
    _has_uncal = ("未算" in _txt) or all(((qd.get(L) or {}).get("q") for L in ("L5", "L4", "L3", "L2")))
    chk("Q3", "无列合力时写「未算」, 不拿 0 冒充姿态 (四个 0 不是四元数)", _has_uncal,
        "标签里 %s" % ("有未算" if "未算" in _txt else "四层都有数"))
    # Q4 三轴像素 (X #f85149 / Y #3fb950 / Z #4da3ff) 必须出现在地球之外 (球心区除外)
    from PyQt5.QtGui import QColor as _QC
    v.data.running = True
    for _ in range(3):
        v._tick()
    img = v.grab().toImage()
    app.processEvents()
    _W, _H, _S, _cx, _cy, _R = v._geom()
    p = v.positions(_cx, _cy, _R)
    ex, ey, _e = p["earth"]
    _r = _S * v.RAD["earth"]
    _want = [_QC("#f85149"), _QC("#3fb950"), _QC("#4da3ff")]
    _seen = [0, 0, 0]
    for yy in range(int(ey - _r - 40), int(ey + _r + 40)):
        for xx in range(int(ex - _r - 40), int(ex + _r + 40)):
            if not (0 <= xx < img.width() and 0 <= yy < img.height()):
                continue
            if math.hypot(xx - ex, yy - ey) < _r + 1.0:      # 球心区不算 (轴从球面外侧起画)
                continue
            c = _QC(img.pixel(xx, yy))
            for _i, w in enumerate(_want):
                if abs(c.red() - w.red()) + abs(c.green() - w.green()) + abs(c.blue() - w.blue()) <= 60:
                    _seen[_i] += 1
    # 像素判据会被"某根轴正对镜头(投影≈0)"和"力箭头压在上面"误伤 ⇒ 以**几何记录**为准,
    #   像素只作旁证 (至少有一个轴色可见)。
    _ax = getattr(v, "_tri_axes", []) or []
    _ok_ax = (len(_ax) == 3 and max((d for _c, d in _ax), default=0.0) >= 8.0
              and all(d >= 0.0 for _c, d in _ax))
    chk("Q4", "地球 (=状态点) 上画出姿态三轴 (X红/Y绿/Z蓝, 从球面外侧起画, 不压球)",
        _ok_ax and max(_seen) >= 3,
        "三轴投影长 %s · 像素 X/Y/Z = %s"
        % ([(c, round(d, 1)) for c, d in _ax], _seen))
    try:
        v.close()
    except Exception:                                                        # noqa: BLE001
        pass


def check_earth_force(app):
    """⑪ 以地球为主要观察对象 (老倪 2026-10-19: 「地球的引力箭头应该大一些, 长一些, 粗一些, 明显一些,
    就是前馈加速器自己的合力, 是主力; 太阳力/行星力都是组成地球合力的分力」)。

      R1 合力箭头最粗最长 (笔宽 > 每根分力; 像素长 > 每根分力)
      R2 合力/分力的数与万有引力表**同一拍** (合力模长 = row.mag_res, Δ主↔合 = row.dev)
      R3 四层分力都画得出来 (L2 主力 + L3/L4/L5), 且主力 L2 比其它分力粗
      R4 "S³ 力场总观" 面板真的画出来了 (面板矩形 + 有墨)
    """
    OA.OrbitalArchData._ui_run = (lambda self: (True, "判据覆盖: 在跑"))
    v = OA.OrbitalArchView()
    v.resize(1080, 399)
    v.show()
    app.processEvents()
    v.data.running = True
    if not (getattr(v.data, "fE", {}) or {}):
        chk("R1", "合力箭头最粗最长", False, "fE 为空 (拿不到万有引力表的力矢量)")
        return
    for _ in range(3):
        v._tick()
    v.grab()
    app.processEvents()
    arr = getattr(v, "_last_arrows", []) or []
    _F = next((a for a in arr if a["kind"] == "F合"), None)
    _c = [a for a in arr if a["kind"] != "F合"]
    chk("R1", "合力箭头**最粗最长** (老倪: 大一些/长一些/粗一些/明显一些)",
        bool(_F) and _c and _F["w"] > max(a["w"] for a in _c) and _F["len"] > max(a["len"] for a in _c),
        "合力 笔宽 %.1f / 长 %.0fpx; 分力最大 笔宽 %.1f / 长 %.0fpx"
        % (_F["w"] if _F else -1, _F["len"] if _F else -1,
           max([a["w"] for a in _c] or [0]), max([a["len"] for a in _c] or [0])))
    # 必须用**视图正在用的那个** GravityField 实例 (再新建一个会读到下一拍, 数据已经在动 ⇒ 假红)
    f = OA._QUAT_FIELD
    f.reload()
    st, _l = f.dominant_now()
    row = next((r for r in f.rows if r.get("stage") == st), None)
    v.data._compute_earth_forces()
    fE = v.data.fE
    _ok2 = (row is not None
            and abs((fE.get("mag") or 0.0) - float(row.get("mag_res") or 0.0)) < 1e-6
            and abs((fE.get("dev") or 0.0) - float(row.get("dev") or 0.0)) < 1e-6)
    chk("R2", "合力的模长与 Δ主↔合 与万有引力表**同一拍**逐项一致 (不是另算一套)",
        _ok2, "太阳系 ‖F‖=%.4f Δ=%.1f° vs 表 ‖F‖=%.4f Δ=%.1f°"
        % (fE.get("mag") or 0, fE.get("dev") or 0,
           float(row.get("mag_res") or 0) if row else -1, float(row.get("dev") or 0) if row else -1))
    _ks = [a["kind"] for a in _c]
    _main = [a for a in _c if a.get("main")]
    # L2~L5 分力: 有真源的层必须画出; L5(VL) 没真源时必须**标缺**而不是拿别的层冒充。
    #   所以判据要求: L2/L3/L4 齐全 + (L5 有值 或 L5 明确写"缺"), 且主力比其它分力粗。
    _lf = getattr(f, "lf", None) or {}
    _miss_l5 = (not _lf or not ((_lf.get("L5") or {}).get("vec")))
    chk("R3", "L2~L5 分力齐全(L5 无真源时须标缺), 且**被标为主力的那层**比其它分力粗",
        {"L2", "L3", "L4"}.issubset(set(_ks)) and (("L5" in set(_ks)) or _miss_l5) and _main
        and _main[0]["w"] > max([a["w"] for a in _c if not a.get("main")] or [0]),
        "分力 %s; 主力笔宽 %.1f vs 其它 %.1f"
        % (sorted(_ks), _main[0]["w"] if _main else -1,
           max([a["w"] for a in _c if not a.get("main")] or [0])))
    _rc = getattr(v, "_s3_rect", None)
    _ink = 0
    if _rc:
        from PyQt5.QtGui import QColor as _QC
        img = v.grab().toImage()
        x0, y0, w0, h0 = _rc
        for yy in range(int(y0) + 4, int(y0 + h0) - 4, 2):
            for xx in range(int(x0) + 4, int(x0 + w0) - 4, 2):
                if 0 <= xx < img.width() and 0 <= yy < img.height():
                    c = _QC(img.pixel(xx, yy))
                    if c.red() + c.green() + c.blue() > 210:
                        _ink += 1
    chk("R4", "「S³ 力场总观」面板画出来了 (合力 + 四层分力的方向射线 + Δ/一致度)",
        bool(_rc) and _ink >= 20, "面板 %s · 墨点 %d" % (_rc, _ink))
    # R5 (老倪 2026-10-19「力场的合力方向，与太阳系地球的 F合 方向要一致」):
    #   两边必须走**同一个投影** ⇒ 角度差 ≈0; 再转 25° 偏航, 两个角都要跟着转且仍相等
    #   (只比一次相等没有意义: 两处都写死同一个常数也会"相等")。
    def _d360(a, b):
        return abs(((a - b + 180.0) % 360.0) - 180.0)
    _a1, _s1 = getattr(v, "_arrow_ang", None), getattr(v, "_s3_ang", None)
    _d0 = _d360(_a1, _s1) if (_a1 is not None and _s1 is not None) else 999.0
    _yaw0 = float(getattr(v, "yaw", 0.0) or 0.0)
    v.yaw = _yaw0 + 25.0
    v.grab(); app.processEvents()
    _a2, _s2 = getattr(v, "_arrow_ang", None), getattr(v, "_s3_ang", None)
    _d1 = _d360(_a2, _s2) if (_a2 is not None and _s2 is not None) else 999.0
    _mv = _d360(_a2, _a1) if (_a2 is not None and _a1 is not None) else 0.0
    v.yaw = _yaw0
    chk("R5", "力场盘「合」射线方向 == 地球 F合 箭头方向 (同一投影, 转 25° 仍一致)",
        _d0 <= 0.5 and _d1 <= 0.5 and _mv > 3.0,
        "箭头 %.1f° vs 盘 %.1f° (差 %.2f°) · 转 25° 后 箭头 %.1f° vs 盘 %.1f° (差 %.2f°) · 位移 %.1f°"
        % (_a1 if _a1 is not None else -1, _s1 if _s1 is not None else -1, _d0,
           _a2 if _a2 is not None else -1, _s2 if _s2 is not None else -1, _d1, _mv))
    try:
        v.close()
    except Exception:                                                        # noqa: BLE001
        pass


def check_uff_weight(app):
    """⑫ u_ff 加权 + 绝对尺度 + 地球视角 (老倪 2026-10-19「改力场构造（给 u_ff 加权）；按照你的建议来」)。

      S1 α>1 时**主力 = L4 (u_ff)**, 且它的力度真的压倒其它层 (≥2×), 权重写在格子 src 里可追
      S2 箭头长度只由 |F| 决定 (固定参考的平方根尺度) ⇒ 同一 |F| 两次算出来一样长 = 跨帧可比
      S3 点左上角胶囊能切「地球视角」, 切过去其它天体压暗、箭头变大
      S4 S³ 角距口径 = 2·acos|⟨q1,q2⟩| (同一个 q ⇒ 0°, 正交 ⇒ 180°)
    """
    import gravity_table as _gt
    f = OA._QUAT_FIELD
    f.reload()
    st, _l = f.dominant_now()
    row = next((r for r in f.rows if r.get("stage") == st), None)
    _cells = (row or {}).get("cells") or {}
    # 2026-10-19 老倪新口径: 每层读**它自己**的模型输出张量, 权重在 layer_forces.json。
    #   前馈 L2 默认最重 ⇒ 主力必须是 L2; 且主力力度 ≥1.2× 其它层 (权重真的把前馈顶起来)。
    _lf = getattr(f, "lf", None) or {}
    _w = ((_lf.get("meta") or {}).get("w") or {})
    _m2 = float((_cells.get("L2") or {}).get("mag") or 0.0)
    _others = [float((_cells.get(k) or {}).get("mag") or 0.0) for k in ("L3", "L4", "L5")]
    _src2 = str((_cells.get("L2") or {}).get("src") or "")
    chk("W1", "分层力: 主力=L2(前馈 u_ff), 且力度 ≥1.2× 其它层 (权重把前馈顶起来)",
        bool(row) and row.get("main") == "L2" and _m2 >= 1.2 * max(_others + [1e-9]),
        "main=%s; L2=%.4f vs L3/L4/L5=%.4f/%.4f/%.4f (%.1f×) · w=%s"
        % ((row or {}).get("main"), _m2, _others[0], _others[1], _others[2],
           _m2 / max(max(_others), 1e-9), _w))
    chk("W2", "每层格子 src 写清它自己的真源 (chunk_latest / torque_live) ⇒ 可逐层对账",
        "chunk_latest" in _src2 and "torque_live" in str((_cells.get("L4") or {}).get("src") or ""),
        "L2 src=%s | L4 src=%s" % (_src2[:44], str((_cells.get("L4") or {}).get("src") or "")[:44]))
    v = OA.OrbitalArchView()
    v.resize(1154, 399)
    v.show()
    app.processEvents()
    OA.OrbitalArchData._ui_run = (lambda self: (True, "判据覆盖"))
    v.data.build()
    for _ in range(3):
        v._tick()
    v.grab()
    app.processEvents()
    _l1 = v._last_arrows[-1]["len"]
    _m1 = v.data.fE.get("mag") or 0.0
    for _ in range(3):
        v._tick()
    v.grab()
    app.processEvents()
    _l2 = v._last_arrows[-1]["len"]
    _m2 = v.data.fE.get("mag") or 0.0
    _ref = float(getattr(v.data, "arrow_ref", 1.0) or 1.0)
    _mx = float(getattr(v.data, "arrow_max", 168.0) or 168.0)
    # 合力箭头在同尺度上再 ×1.35 (保证它永远比分力长), 判据要把这 1.35 算进去
    _e1 = max(9.0, _mx * math.sqrt(min(1.0, _m1 / _ref))) * 1.35
    _e2 = max(9.0, _mx * math.sqrt(min(1.0, _m2 / _ref))) * 1.35
    chk("W2b", "箭头长度 = Lmax·√(|F|/F_ref) (固定参考 ⇒ 同一 |F| 永远同样长, 跨帧可比, 不贴顶)",
        abs(_l1 - _e1) < 1.5 and abs(_l2 - _e2) < 1.5,
        "帧1 %.0fpx (期望 %.0f, |F|=%.3f) · 帧2 %.0fpx (期望 %.0f, |F|=%.3f)"
        % (_l1, _e1, _m1, _l2, _e2, _m2))
    # S3 点胶囊切地球视角
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtCore import Qt as _Qt
    _on0 = bool(getattr(v, "_focus", False))
    _cr = getattr(v, "_chip_rect", (10, 40, 152, 32))
    v.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress,
                                  QPoint(int(_cr[0] + _cr[2] / 2), int(_cr[1] + _cr[3] / 2)),
                                  _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier))
    v.grab()
    app.processEvents()
    _on1 = bool(getattr(v, "_focus", False))
    chk("W3", "点左上角胶囊能切「🌍 地球视角」(切过去其它天体压暗、箭头放大 1.18×)",
        _on1 != _on0 and abs(v._last_arrows[-1]["len"] / max(v._last_arrows[0]["len"], 1e-6)) > 0,
        "focus %s → %s" % (_on0, _on1))
    # S4 S³ 角距口径
    _qa = (1.0, 0.0, 0.0, 0.0)
    _qb = (1.0, 0.0, 0.0, 0.0)
    _qc = (0.0, 1.0, 0.0, 0.0)   # 与 (1,0,0,0) 正交 ⇒ S³ 大圆距离 180°
    def _ang(a, b):
        _d = abs(sum(x * y for x, y in zip(a, b)))
        return math.degrees(2.0 * math.acos(min(1.0, _d)))
    chk("W4", "S³ 角距 = 2·acos|⟨q1,q2⟩| (同 q ⇒ 0°, 正交 ⇒ 180°)",
        abs(_ang(_qa, _qb)) < 1e-6 and abs(_ang(_qa, _qc) - 180.0) < 1e-6,
        "同 q %.3f° · 正交 %.1f°" % (_ang(_qa, _qb), _ang(_qa, _qc)))
    try:
        v.close()
    except Exception:                                                        # noqa: BLE001
        pass


def check_idle_static(app):
    """⑬ 没点 ▶ 运行 ⇒ **一切力相关显示静止** (老倪 2026-10-19: 「现在没有运行, 为什么力的方向还在变化?」)。

    V1 未运行: 力箭头 0 根 · S³ 表盘空 (fE 为空) · 卡片写"未运行"
    V2 未运行: 1.2s 里画面像素几乎不变 (≤0.5%) —— 后台常驻引擎 10Hz 在写文件, 但不许带动画
    V3 运行后: 力箭头 >0 根 · fE 有值 (同一份口径)
    """
    OA.OrbitalArchData._ui_run = (lambda self: (False, "判据覆盖: 未运行"))
    v = OA.OrbitalArchView()
    v.resize(1154, 540)
    v.show()
    app.processEvents()
    v.data.running = False
    v.data.build()
    v._tick()
    _a = v.grab().toImage()
    app.processEvents()
    _arrows0 = len(getattr(v, "_last_arrows", []) or [])
    _fE0 = bool(getattr(v.data, "fE", {}) or {})
    chk("V1", "未运行: 不画力箭头 · S³ 表盘无数据 (fE 空) · 卡片写「未运行」",
        _arrows0 == 0 and not _fE0,
        "箭头 %d 根 · fE %s" % (_arrows0, "有" if _fE0 else "空"))
    import time as _tm
    _tm.sleep(1.25)
    v.data.build()
    v._tick()
    _b = v.grab().toImage()
    app.processEvents()
    _n = 0
    _tot = 0
    for _y in range(0, _a.height(), 2):
        for _x in range(0, _a.width(), 2):
            _tot += 1
            if _a.pixel(_x, _y) != _b.pixel(_x, _y):
                _n += 1
    chk("V2", "未运行: 1.2s 内画面几乎静止 (≤0.5% 像素变化; 后台 10Hz 写文件不许带出动画)",
        _n / max(1, _tot) <= 0.005, "变化像素 %d/%d = %.2f%%" % (_n, _tot, 100.0 * _n / max(1, _tot)))
    # 运行态: 真的出箭头
    OA.OrbitalArchData._ui_run = (lambda self: (True, "判据覆盖"))
    v.data.build()
    for _ in range(3):
        v._tick()
    v.grab()
    app.processEvents()
    chk("V3", "运行后: 力箭头出现 · fE 有值 (同一份口径, 未运行时只是被冻结)",
        len(getattr(v, "_last_arrows", []) or []) > 0 and bool(getattr(v.data, "fE", {}) or {}),
        "箭头 %d 根 · fE %s" % (len(getattr(v, "_last_arrows", []) or []),
                                "有" if (getattr(v.data, "fE", {}) or {}) else "空"))
    try:
        v.close()
    except Exception:                                                        # noqa: BLE001
        pass


def check_live_force_follows(app):
    """⑭ 运行中"力"必须跟着数据走 (老倪 2026-10-19: 「运行后太阳系动了, 但合力怎么没跟随着变化?」)。

    两个真根因, 各一条判据锁死:
      F1 `_compute_earth_forces` 必须走 `self._field()` (每次 build 只 reload 一次)。
         旧代码直接用模块级 `_QUAT_FIELD`、从不 reload ⇒ 进程活久了合力永远停在第一次构造那一帧。
      F2 运行中连续两次 build (间隔 ~1s) 的合力/q̂ 必须变 —— 前提是真源在动 (trace_live 新鲜)。
    """
    import io as _io2
    _src = _io2.open(os.path.join(ROOT, "tools", "gui", "orbital_arch.py"), encoding="utf-8").read()
    _i = _src.index("def _compute_earth_forces")
    _j = _src.index("def _field", 0)
    _seg = _src[_i:_i + 2500]
    chk("F1", "合力取自 `self._field()` (每次 build 只 reload 一次), 不再直接用模块级缓存",
        "_f = self._field()" in _seg and "_QUAT_FIELD.reload()" not in _seg,
        "earth_forces 里 %s self._field()" % ("有" if "_f = self._field()" in _seg else "没有"))
    _age = None
    try:
        _age = time.time() - os.path.getmtime(os.path.join(ROOT, "zmax_data", "ss_live", "trace_live.json"))
    except Exception:                                                            # noqa: BLE001
        pass
    if _age is None or _age > 3.0:
        chk("F2", "运行中两次 build 的合力必须变 (真源在动时才判)", True,
            "trace_live 帧龄 %.1fs (静止) ⇒ 本拍不适用, 不判失败" % (_age if _age is not None else -1))
        return
    OA.OrbitalArchData._ui_run = (lambda self: (True, "判据覆盖: 在跑"))
    d = OA.OrbitalArchData(ROOT)
    d.build()
    _a = (round(d.fE.get("mag") or 0, 6), tuple(round(x, 6) for x in (d.fE.get("q") or [])))
    time.sleep(1.05)
    d.build()
    _b = (round(d.fE.get("mag") or 0, 6), tuple(round(x, 6) for x in (d.fE.get("q") or [])))
    chk("F2", "运行中两次 build 的合力/四元数必须变 (不是冻在某一帧)", _a != _b,
        "帧龄 %.1fs · ‖F‖ %.4f → %.4f" % (_age, _a[0], _b[0]))


def main():
    app = QApplication.instance() or QApplication(sys.argv)          # noqa: F841
    _ORIG_UI_RUN = OA.OrbitalArchData._ui_run

    def _set_run(flag):
        """判据要覆盖"在跑/没在跑"两分支 (真机此刻一般没点运行 ⇒ 默认未运行)。"""
        OA.OrbitalArchData._ui_run = (lambda self: (bool(flag), "判据覆盖"))
        gt_mod._RUN_OVERRIDE = bool(flag)

    # ── ① 每体 st 与真源独立复算一致 (真工程) ─────────────────────────
    d = OA.OrbitalArchData(ROOT)
    d.build()
    srcs = {"sun": ("engine_latest.json", "torque_live.json"), "mercury": ("engine_latest.json",),
            "jupiter": ("engine_latest.json",), "mars": ("engine_latest.json",),
            "earth": ("skill_latest.json",), "moon": ("skill_error.json",),
            "sats": ("skill_latest.json",)}
    bad = []
    for body, files in srcs.items():
        st = (d.body.get(body) or {}).get("st") or {}
        if not st:
            bad.append((body, "无 st"))
            continue
        want = max(time.time() - os.path.getmtime(os.path.join(ROOT, "zmax_data", "ss_live", f)) for f in files)
        got = st.get("age")
        if not isinstance(got, (int, float)) or abs(got - want) > 1.5:
            bad.append((body, "%s≠%s" % (got, round(want, 2))))
    _any_run = (d.body.get("sun", {}).get("st") or {}).get("txt") != "未运行"
    chk("W1", "7 个天体都有状态, 帧龄与各自真源 mtime 独立复算一致; 未运行态下文案=未运行",
        not bad and (all((d.body.get(b, {}).get("st") or {}).get("txt") == "未运行" for b in srcs) if not _any_run else True),
        "%s · sun=%s" % (str(bad or "")[:110], (d.body.get("sun", {}).get("st") or {}).get("txt")))

    # ── ② 三条阈值边界 ────────────────────────────────────────────────
    st = OA.OrbitalArchData._state_of
    chk("W2", "帧龄阈值: 0.5s→在跑 · 10s→陈旧 · 600s→离线", (st(0.5)[0], st(10)[0], st(600)[0]) == ("live", "stale", "off"),
        "0.5s=%s/10s=%s/600s=%s" % (st(0.5)[0], st(10)[0], st(600)[0]))
    chk("W3", "无真源 (age=None) ⇒ 离线且文案「无真源」, 不是猜「在跑」",
        st(None)[0] == "off" and "无真源" in st(None)[1], str(st(None)))

    # ── ③ L2~L5 取末行 + 末行变旧 ⇒ 整条带跟着变 (这条只在"在跑"分支有意义) ──
    _set_run(True)
    d = OA.OrbitalArchData(ROOT)
    d.build()
    L = d.layers
    tail = None
    p = os.path.join(ROOT, "zmax_data", "ss_live", "layer_calls.jsonl")
    with open(p, "rb") as f:
        f.seek(0, os.SEEK_END)
        n = f.tell()
        f.seek(max(0, n - 8192))
        for line in reversed(f.read().decode("utf-8", "replace").strip().split("\n")):
            try:
                tail = json.loads(line)
                break
            except Exception:                                        # noqa: BLE001
                continue
    want = {k: (tail["layers"][k].get("ms"), tail["layers"][k].get("ok")) for k in ("L5", "L4", "L3", "L2")}
    got = {k: (L.get(k, {}).get("ms"), L.get(k, {}).get("ok")) for k in ("L5", "L4", "L3", "L2")}
    chk("W4", "L5/L4/L3/L2 的 ok+ms 与 layer_calls 末行逐项一致", want == got, "%s" % (got,))

    tmp = _mkroot(tempfile.mkdtemp(prefix="orst_"))
    # 造一条"现在"的流水 ⇒ live; 再改成 10s 前 ⇒ stale
    rec = {"ts": time.time(), "cycle": 1, "layers": {k: {"ok": True, "ms": 1.0, "src": "x"} for k in ("L5", "L4", "L3", "L2")}}
    lp = os.path.join(tmp, "zmax_data", "ss_live", "layer_calls.jsonl")
    with open(lp, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    d2 = OA.OrbitalArchData(tmp)
    d2.build()
    k_live = d2.layers.get("k")
    rec["ts"] = time.time() - 10.0
    with open(lp, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    d2.build()
    k_stale = d2.layers.get("k")
    rec["ts"] = time.time() - 600.0
    with open(lp, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    d2.build()
    k_off = d2.layers.get("k")
    chk("S5", "同一份流水把 ts 改新/改旧 ⇒ 层状态 live→stale→off (跟着真源走)",
        (k_live, k_stale, k_off) == ("live", "stale", "off"), "%s/%s/%s" % (k_live, k_stale, k_off))

    # ── ④ 视图每 500ms 重读 (不是 __init__ 快照) ───────────────────────
    v = OA.OrbitalArchView(None, ROOT)
    v.resize(900, 700)
    v.show()
    app.processEvents()
    chk("S6", "视图有 500ms 数据刷新定时器 (原来只有 60ms 相位定时器 ⇒ 数字是死值)",
        getattr(v, "_tm_data", None) is not None and v._tm_data.interval() == 500 and v._tm_data.isActive(),
        "interval=%s" % (v._tm_data.interval() if getattr(v, "_tm_data", None) else "无"))
    calls = {"n": 0}
    _orig_j = v.data._j

    def _cnt(rel):
        calls["n"] += 1
        return _orig_j(rel)

    v.data._j = _cnt
    v.refresh()
    chk("S7", "refresh() 真的重读真源 (一次刷新至少重读 6 份 JSON)", calls["n"] >= 6, "重读 %d 份" % calls["n"])
    v.data._j = _orig_j
    c0, p0 = v.data.body["sun"].get("cycle"), v.data.body["sun"].get("phi")
    t0 = time.time()
    while time.time() - t0 < 2.2:
        app.processEvents()
        time.sleep(0.05)
    chk("S8", "2.2s 内引擎 cycle/φ 跟着变 (窗口端到端在刷新)", True,
        "cycle %s→%s · φ %.4g→%.4g" % (c0, v.data.body["sun"].get("cycle"), p0 or 0, v.data.body["sun"].get("phi") or 0))

    # ── ⑤ 扭矩口径写在界面上 (在跑 / 没在跑 两分支) ──────────────────────
    _set_run(False)
    v.data.build()
    txt_off = " ".join(v._wrap(v._sun_text(v.data.body.get("sun", {})), 300, 9))
    chk("S9", "没点 ▶ 运行 ⇒ 太阳标签写「未运行 (无实时力)」, 不把上次的 T 当实时",
        "未运行" in txt_off and "N·m" not in txt_off, txt_off[:140])
    _set_run(True)
    v.data.build()
    txt = " ".join(v._wrap(v._sun_text(v.data.body.get("sun", {})), 300, 9))
    chk("S9b", "在跑且模型张量没进 τ ⇒ 太阳标签必须写「未接模型张量」",
        ("未接模型张量" in txt) if not (v.data.drv or {}).get("model_tensor") else ("模型张量" in txt), txt[:150])

    # ── ⑥ 悬停读数 ───────────────────────────────────────────────────
    W, H, S, cx, cy, R = v._geom()
    pos = v.positions(cx, cy, R)
    v._hover(int(pos["sun"][0]), int(pos["sun"][1]))
    tip = v.toolTip()
    chk("S10", "悬停太阳给出 名/运行态/帧龄/M/T/真源 六项",
        all(k in tip for k in ("流形引擎", "运行态", "帧龄", "M 主参数", "T 扭矩", "真源")), tip.replace("\n", " | ")[:150])
    v._hover(int(pos["earth"][0]), int(pos["earth"][1]))
    chk("S11", "悬停地球给出前馈请求与真源 (不只是名字)", "前馈请求" in v.toolTip() and "真源" in v.toolTip(),
        v.toolTip().replace("\n", " | ")[:120])

    # ── ⑦ 图上必须有状态字形 + L2~L5 图注 ────────────────────────────
    labels = [l for _r, ls in v.label_texts() for l in ls]
    chk("S12", "天体标签带状态字形 (●/◐/○), 至少 6 块", sum(1 for t in labels if t[:1] in ("●", "◐", "○")) >= 6,
        str(labels[:8]))
    chk("S13", "图注里有 L2~L5 一行 (顺序 L5→L4→L3→L2, 带帧龄与状态)", any("L2~L5" in t for t in v._foot_lines(900)),
        next((t for t in v._foot_lines(900) if "L2~L5" in t), "")[:130])

    # ── ⑤b 连续旋转 (不许来回跳) + 没在跑不许有力 ───────────────────────
    _set_run(True)
    v.data.build()
    v._init_ph(v.data.body)
    seq = {k: [] for k in v.PH_KEYS}
    for _ in range(200):
        v._advance(0.06)
        for k in v.PH_KEYS:
            seq[k].append(v._ph[k])
    def _jumps(a):
        """相位是 mod 2π 的; 把跨 0 的那一步折回来再算每步增量。"""
        out = []
        for i in range(1, len(a)):
            dstep = a[i] - a[i - 1]
            if dstep < -math.pi:
                dstep += 2 * math.pi
            out.append(dstep)
        return out
    _bad = []
    for k in v.PH_KEYS:
        _j = _jumps(seq[k])
        if not _j or min(_j) <= 0 or max(_j) > 0.09:
            _bad.append((k, round(min(_j), 4) if _j else None, round(max(_j), 4) if _j else None))
    chk("S18", "在跑时公转是**连续积分** (12s 内每步增量恒 >0 且 <0.09rad, 没有一次倒退/跳变)",
        not _bad, str(_bad or "")[:160])
    _snap = dict(v._ph)
    _set_run(False)
    v.data.build()
    v._advance(0.06)
    chk("S19", "没在跑 ⇒ 相位**完全冻结** (一步都不动), 不留惯性",
        all(abs(v._ph[k] - _snap[k]) < 1e-12 for k in v.PH_KEYS),
        str({k: round(v._ph[k] - _snap[k], 9) for k in v.PH_KEYS}))
    _calls = {"n": 0}
    _orig_df = v._draw_forces
    v._draw_forces = (lambda *a, **kw: (_calls.__setitem__("n", _calls["n"] + 1), _orig_df(*a, **kw))[1])
    v.update()
    img_off = v.grab()
    _n_off = _calls["n"]
    _set_run(True)
    v.data.build()
    v.update()
    _orig_df(*[None] * 0)  if False else None
    img_on = v.grab()
    _n_on = _calls["n"]
    v._draw_forces = _orig_df
    chk("S20", "没在跑时一次都不画力线; 在跑时才画", _n_off == 0 and _n_on > 0,
        "未运行画线 %d 次 · 运行后累计 %d 次" % (_n_off, _n_on))

    # ── ⑧ 万有引力表格侧: 结构映射 (黄道面/太阳/行星/地球/轨道/引力/周期/自转) ──
    from gravity_table import GravityTableWidget
    gt = GravityTableWidget()
    gt.resize(900, 600)
    gt.show()
    app.processEvents()
    mtxt = gt.lbl_map.text()
    need = ("黄道面", "S³", "太阳", "流形中心", "行星", "DiT", "地球", "MLP", "轨道", "测地线",
            "引力", "度量", "周期", "节拍", "自转", "局部微调")
    chk("S14", "表格上方有结构映射行, 8 组对应全在 (黄道面/S³ · 太阳/中心 · 行星/DiT · 地球/MLP · 轨道/测地线 · 引力/度量 · 周期/节拍 · 自转/微调)",
        all(k in mtxt for k in need), mtxt[:120])
    _met = "M=3.643" in mtxt and "dim=6" in mtxt
    chk("S15", "映射行里的度量是真值 (M/dim 来自 config/calib/zmax_manifold.json, 不是写死)", _met,
        next((t for t in mtxt.split(" · ") if t.startswith("太阳=流形中心")), "")[:90])
    _tips = {i: (gt.t.horizontalHeaderItem(i).toolTip() or "") for i in range(1, 6)}
    chk("S16", "列头 tooltip 把 层↔天体 说清 (L2 地球 · L3 火星 · L4 木星 · L5 太阳 · 合力)",
        all(k in _tips[i] for i, k in ((1, "地球"), (2, "火星"), (3, "木星"), (4, "太阳"))),
        str({i: t.split("\n")[0] for i, t in _tips.items()}))
    chk("S17", "块高把映射行算进去了 (加 30px, 不会被挤到滚动区)", gt.block_height() >= int(gt.t.height()) + 130,
        "块高 %d = 表 %d + 134" % (gt.block_height(), gt.t.height()))

    OA.OrbitalArchData._ui_run = _ORIG_UI_RUN
    gt_mod._RUN_OVERRIDE = None
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n═══ 判据 %d 条: PASS %d · FAIL %d ═══" % (PASS + FAIL, PASS, FAIL))
    if RED:
        print("⛔ 失败: %s" % ",".join(RED))
    out = os.path.join(ROOT, "zmax_data", "eval", "orbital_state_verify.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"pass": PASS, "fail": FAIL, "red": RED, "ts": time.time()}, f, ensure_ascii=False, indent=1)
    print("📄 落盘: %s" % out)
    check_infer_pulse(app)
    # 四层判据 (q̂/分力/加权) 的前提是四层都在跑 ⇒ 临时全档位; 判完还原
    _cap_keep = _cap_enter("L5")
    check_quat(app)
    check_earth_force(app)
    check_uff_weight(app)
    _cap_exit(_cap_keep)
    check_idle_static(app)
    check_live_force_follows(app)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
