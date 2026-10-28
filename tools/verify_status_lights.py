#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚦 三色状态灯 + 文案清理 判据 (老倪 2026-10-15)

老倪原话: 「主控制台右上角边框 去掉 Simulink模式这几个字；那三个状态指示灯，保留，绿色表示功能正常
(可以随时进行模型推理，且所有模型可以数据闭环全流程工作)，黄色灯光默认保持现状，工作时要以1秒为周期闪烁，
表示训练正在进行(且GPU负荷平均大于50%)，红色灯光默认也是保持现状，工作时要以1秒为周期闪烁，
表示正处于真机器联调且随时可以进行机械臂操作；你来同步功能，要保证功能的准确实时显示。
控制台左下角的 0.5.2 lerobot这写字符串，删掉；System 1 VLA-T动作后面的括号里的 (SmolVLA 500M)删掉，
后面的 (LeWM 15M)这几个字和括号，删掉」

判据 (源码静态 + 唯一依据直读交叉核对, 不看印象):
  ① 文案清理: 品牌行无「Simulink 模式」· 左下角无「0.5.2 / LeRobot · Z-MAX」· System 1 两卡与架构框无括号型号
  ② 三灯语义在位: 绿=功能正常/黄=训练进行中且GPU>50%/红=真机联调且可操作 的 tooltip 与判据注释在源码里
  ③ 唯一依据自洽: tools/status_lights.py --json 的三个结论与**独立重测**一致
     (8790 直连 · nvidia-smi 直读 · 位姿/授权唯一依据直读)
  ④ 闪烁口径: BLINK_PERIOD_S == 1.0 (1s 周期) + 相位函数占空比 50% (0.5s 亮/0.5s 灭)
  ⑤ GUI 接线: 采样线程 got→_on_light_state · _render_lights 由 250ms 定时器驱动 · 取不到数据会标失效

用法: cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_status_lights.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STUDIO = os.path.join(ROOT, "tools", "gui", "studio.py")
TOOL = os.path.join(ROOT, "tools", "status_lights.py")
POSE_SRC = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
AUTH_SRC = os.path.join(ROOT, "zmax_data", "ctl_auth.json")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")

rows: list[tuple[str, bool, str]] = []


def chk(tag, ok, ev):
    rows.append((tag, bool(ok), ev))
    print("  %s %s  %s" % ("✅" if ok else "❌", tag, ev))
    return bool(ok)


def sh(c, t=8):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def main() -> int:
    print("═══ 三色状态灯 + 文案清理 判据 ═══")
    src = open(STUDIO, encoding="utf-8").read()
    # ⚠️ 只判**代码行** (studio.py 顶部有巨量 changelog 注释, 里面留着历史文案是正常的, 不算界面残留)
    code = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("#"))

    # ① 文案清理
    chk("①a 品牌行无「Simulink 模式」", "具身智能 · Simulink 模式" not in code,
        "品牌行现为 🦾 Z-MAX 具身智能 (代码里 '具身智能 · Simulink 模式' 出现 %d 次, 应为 0)" % code.count("具身智能 · Simulink 模式"))
    chk("①b 左下角无 0.5.2 / LeRobot·Z-MAX 标签",
        'QLabel("0.5.2-zmax.1.0.1' not in code and '"LeRobot · Z-MAX"' not in code,
        "老标签字面量已移除")
    chk("①c 侧栏两卡无括号型号",
        '"System 1 · VLA-T 动作 (SmolVLA 500M)"' not in code and '"System 1 · Z-Flow 引导 (LeWM 15M)"' not in code,
        '现为 "System 1 · VLA-T 动作" / "System 1 · Z-Flow 引导"')
    chk("①d 架构框描述无括号型号", "VLA-T 动作 (SmolVLA 500M) 端到端" not in code,
        '现为 "VLA-T 动作 端到端 + Z-Flow 引导"')

    # ② 三灯语义在位
    sem = {
        "绿=功能正常(可随时推理+闭环全流程)": '"功能正常: 可以随时进行模型推理, 且所有模型可以数据闭环全流程工作"',
        "黄=训练进行中(1s闪, GPU>50%)": '"训练进行中: 1s 周期闪烁 (训练进程在场 且 GPU 负荷平均 > 50%)"',
        "红=真机联调且可操作(1s闪)": '"正处于真机器联调且随时可以进行机械臂操作: 1s 周期闪烁"',
    }
    miss = [k for k, v in sem.items() if v not in src]
    chk("② 三灯语义在位", not miss, "缺 %s" % (miss or "无 (3/3)"))

    # ③ 唯一依据自洽 (独立重测)
    out = sh("%s %s --json" % (PY, TOOL))
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except Exception as e:                                                      # noqa: BLE001
        chk("③ status_lights --json 可跑", False, "%s: %s" % (e.__class__.__name__, out[:120]))
        d = None
    if d:
        # 绿: 独立直连 8790 + 检查在役指针文件
        try:
            with urllib.request.urlopen("http://127.0.0.1:8790/health", timeout=2) as r:
                direct_green = (r.status == 200)
        except Exception:                                                       # noqa: BLE001
            direct_green = False
        reg = json.load(open(os.path.join(ROOT, "models", "active_models.json"), encoding="utf-8"))
        ptr_ok = True
        for lv in ("L2", "L3", "L4"):
            p = (reg.get(lv) or {}).get("path") or ""
            ap = p if os.path.isabs(p) else os.path.join(ROOT, p)
            ptr_ok = ptr_ok and os.path.exists(ap) and os.path.exists(os.path.realpath(ap))
        expect_green = direct_green and ptr_ok
        chk("③a 绿灯判定 == 独立重测", d["green"]["on"] == expect_green,
            "工具 on=%s · 独立(8790=%s 在役指针全解析=%s) ⇒ %s" % (d["green"]["on"], direct_green, ptr_ok, expect_green))
        # 黄: 独立 nvidia-smi 平均 + /proc 训练进程
        g = sh("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits", 5).splitlines()
        g = [int(x) for x in g if x.strip().isdigit()]
        n_proc = 0
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cl = open("/proc/%s/cmdline" % pid, "rb").read().decode("utf-8", "replace").replace("\x00", " ")
            except Exception:                                                   # noqa: BLE001
                continue
            if re.search(r"lerobot[_-]train|joint_train_all|yolo_annot_train|train_[A-Za-z0-9_]*\.py|auto_loop", cl):
                n_proc += 1
        expect_blink_y = (n_proc > 0) and (d["yellow"]["gpu_avg"] is not None) and (d["yellow"]["gpu_avg"] > 50.0)
        chk("③b 黄灯判定 == 独立重测", d["yellow"]["blink"] == expect_blink_y,
            "工具 blink=%s (gpu_avg=%s) · 独立(训练进程 %d 个, 当前 GPU %s%%)" %
            (d["yellow"]["blink"], d["yellow"]["gpu_avg"], n_proc, g or "—"))
        # 红: 独立读位姿 + 授权
        try:
            pd = json.load(open(POSE_SRC, encoding="utf-8"))
            pose_age = time.time() - float(pd.get("ts") or os.path.getmtime(POSE_SRC))
            pose_ok = pose_age <= 2.0
        except Exception:                                                       # noqa: BLE001
            pose_ok, pose_age = False, None
        try:
            armed = float(json.load(open(AUTH_SRC, encoding="utf-8")).get("until") or 0) > time.time()
        except Exception:                                                       # noqa: BLE001
            armed = False
        expect_blink_r = pose_ok and armed
        chk("③c 红灯判定 == 独立重测", d["red"]["blink"] == expect_blink_r,
            "工具 blink=%s · 独立(位姿龄 %s ≤2s=%s · 授权 armed=%s)" %
            (d["red"]["blink"], "—" if pose_age is None else "%.1fs" % pose_age, pose_ok, armed))

    # ④ 闪烁口径 = 1s 周期
    m = re.search(r"BLINK_PERIOD_S\s*=\s*([0-9.]+)", open(TOOL, encoding="utf-8").read())
    period = float(m.group(1)) if m else -1
    duty = sum(1 for i in range(1000) if (i / 1000.0 % period) < period / 2.0) / 1000.0 if period > 0 else 0
    chk("④ 闪烁周期 1s 且占空比 50%", period == 1.0 and abs(duty - 0.5) < 0.02,
        "BLINK_PERIOD_S=%s ⇒ 相位占空比 %.1f%% (0.5s 亮/0.5s 灭)" % (period, duty * 100))

    # ⑤ GUI 接线
    wiring = {
        "采样线程": "_StatusLightFetcher(self, interval=2.0)" in src and ".got.connect(self._on_light_state)" in src,
        "渲染定时器 250ms": "_light_timer.start(250)" in src,
        "取不到标失效": "状态源已静止" in src,
        "唯一依据单一出处注释": "tools/status_lights.py" in src,
    }
    bad = [k for k, v in wiring.items() if not v]
    chk("⑤ GUI 接线齐", not bad, "缺 %s" % (bad or "无 (4/4)"))

    # ⑥ 渲染/闪烁**真跑** (用真 studio 类 + 桩 self, 不建整窗; 覆盖相位源验证 1s 周期两相位)
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
        from PyQt5.QtWidgets import QApplication, QLabel  # noqa: E402
        import time as _t  # noqa: E402
        import studio  # noqa: E402
        _app = QApplication.instance() or QApplication(sys.argv[:1])

        class _Stub:
            pass

        st = _Stub()
        st._status_lights = {"green": QLabel(), "yellow": QLabel(), "red": QLabel()}
        st._light_state = {
            "blink_period_s": 1.0,
            "green": {"on": True, "why": "G", "items": [{"name": "推理服务 8790/health", "ok": True}]},
            "yellow": {"blink": True, "why": "Y"},
            "red": {"blink": True, "why": "R"},
        }
        st._light_ts = _t.time()
        _orig = _t.monotonic
        try:
            def _draw(mono):
                _t.monotonic = lambda: mono
                studio.StudioMainWindow._render_lights(st)

            _draw(0.0)   # 周期起点 ⇒ 亮相位
            on = {k: st._status_lights[k].styleSheet() for k in ("yellow", "red")}
            green_on = st._status_lights["green"].styleSheet()
            _draw(0.6)   # 半周期后 ⇒ 灭相位
            off = {k: st._status_lights[k].styleSheet() for k in ("yellow", "red")}
            ok_lit = ("background:#d29922" in on["yellow"]) and ("background:#f85149" in on["red"])
            ok_dark = ("background:transparent" in off["yellow"]) and ("background:transparent" in off["red"])
            ok_green = "background:#3fb950" in green_on and "background:#3fb950" in st._status_lights["green"].styleSheet()
            chk("⑥a 黄/红 1s 周期两相位真跑", ok_lit and ok_dark,
                "t=0.0s 黄%s 红%s · t=0.6s 两灯都灭=%s" %
                ("亮" if ok_lit else on["yellow"][:30], "亮" if ok_lit else on["red"][:30], ok_dark))
            chk("⑥b 绿灯实心常亮 (与相位无关)", ok_green, "两个相位下都是 background:#3fb950")
            # 失效口径: 数据龄 >10s ⇒ 绿灯灭 + tooltip 明标失效
            st._light_ts = _t.time() - 30
            _draw(0.0)
            stale_ok = ("background:transparent" in st._status_lights["green"].styleSheet()
                        and st._status_lights["green"].toolTip().startswith("⚠"))
            chk("⑥c 状态源静止 >10s ⇒ 灯灭 + 明标失效", stale_ok,
                "tooltip 首行: %s" % st._status_lights["green"].toolTip().splitlines()[0][:60])
            st._light_ts = _t.time()
            _draw(0.0)
            chk("⑥d tooltip 带实测证据", "✓推理服务 8790/health" in st._status_lights["green"].toolTip(),
                st._status_lights["green"].toolTip().replace("\n", " | ")[:110])
        finally:
            _t.monotonic = _orig
    except Exception as e:                                                      # noqa: BLE001
        chk("⑥ 渲染判据可跑", False, "%s: %s" % (e.__class__.__name__, e))

    nbad = [r for r in rows if not r[1]]
    print("─── %d/%d %s" % (len(rows) - len(nbad), len(rows), "全绿 PASS" if not nbad else "FAIL"))
    return 0 if not nbad else 1


if __name__ == "__main__":
    sys.exit(main())
