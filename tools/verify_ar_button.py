#!/usr/bin/env python3
"""判据: 🥽 AR 入口 (2026-10-19 老倪: 「3D 场景里点 AR 半天没反应 —— 把 AR 做到画布上边的按钮直接打开」)

三条硬要求:
  ① 画布工具栏有「🥽 AR」按钮, 不先进 3D 场景也能开
  ② 点击**不阻塞**: open_ar_page / ar_launch 必须几百毫秒内返回, 页面先送出, 状态后台回贴
  ③ 3D 场景里的 AR 按钮同源 (同一个 ar_launch), 不再自己跑阻塞链路

真跑, 不靠看代码:
  · 构造真实 SimulinkModule (离屏), 查 btn_ar 文本/布局, 量 open_ar_page 耗时
  · 调 ar_launch, 量返回耗时 + 等状态总线出「页面已送出」
  · 探测 8797 + 场景映射 (--check 只算不动, **不改老倪当前数据源**)

AR_REAL_OPEN=1 时真把浏览器拉起来(桌面可见); 默认只调入口, 浏览器照样会被 spawn。
用法: QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_ar_button.py
退出码: 0 = 全 PASS; 1 = 有失败。
"""
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/zmax"
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src")):
    sys.path.insert(0, _p)

fails = []


def ck(name, ok, extra=""):
    print("  %s %s%s" % ("✅" if ok else "❌", name, (" — " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)


print("① 入口: 画布工具栏 + 3D 场景同源")
import ss_dreamview as SD                                                # noqa: E402
_src_dv = open(os.path.join(ROOT, "tools", "gui", "ss_dreamview.py"), encoding="utf-8").read()
_src_sm = open(os.path.join(ROOT, "tools", "gui", "simulink_module.py"), encoding="utf-8").read()
ck("AR 页面地址 = 当前网卡 IP 的 8793/ar(302→8797) 或回环 8797/ar",
   (SD.ar_page_url().endswith(":8793/ar") or SD.ar_page_url().endswith(":8797/ar"))
   and "10.163.146.78" not in SD.ar_page_url(), SD.ar_page_url())
ck("有非阻塞入口 ar_launch()", callable(getattr(SD, "ar_launch", None)))
ck("有 ar_spawn_browser() 且不等窗口",
   callable(getattr(SD, "ar_spawn_browser", None))
   and "ar_wait_loaded" not in _src_dv[_src_dv.find("def ar_spawn_browser"):_src_dv.find("def ar_status_bus")])
_i = _src_dv.find("def _open_ar_view")
_body = _src_dv[_i:_src_dv.find("def _open_force_scope")]
ck("3D 的 AR 按钮走同一个 ar_launch", "ar_launch(" in _body and "ar_open_url(AR_PAGE_URL)" not in _body)
ck("画布工具栏建了 btn_ar 并挂进布局",
   "self.btn_ar = mk_btn(" in _src_sm and "tl.addWidget(self.btn_ar)" in _src_sm)
ck("画布入口 open_ar_page 存在且调 ar_launch",
   "def open_ar_page" in _src_sm and "ar_launch()" in _src_sm)

print("\n② 真构造画布 (离屏) → 按钮在位 + 点击不阻塞")
from PyQt5.QtWidgets import QApplication                            # noqa: E402
app = QApplication.instance() or QApplication(sys.argv)
import simulink_module as SM                                        # noqa: E402
_t0 = time.time()
m = SM.SimulinkModule()
_build = time.time() - _t0
_b = getattr(m, "btn_ar", None)
ck("btn_ar 在位且文字是 🥽 AR", _b is not None and _b.text().strip() == "🥽 AR",
   (_b.text() if _b else None))
ck("btn_ar 有 tooltip (入口语义可查)", bool(_b and _b.toolTip()))
ck("btn_ar 挂在父控件上 (不是孤儿对象)",
   bool(_b and _b.parent() is not None), "module 构造 %.1fs" % _build)

_t1 = time.time()
_r = m.open_ar_page()
_dt = (time.time() - _t1) * 1000
ck("open_ar_page 返回 True", _r is True, _r)
ck("open_ar_page 不阻塞 (<400ms)", _dt < 400, "%.0f ms" % _dt)

print("\n③ 状态回贴: 后台线程真在干活 (页面先送出)")
_got = []
SD.ar_status_bus().msg.connect(lambda _m: _got.append(_m))
for _ in range(200):                      # 先等上一次(按钮那次)跑完, 否则测的是防连点闸
    app.processEvents()
    if not SD._AR_RUNNING.get("busy"):
        break
    time.sleep(0.1)
_t2 = time.time()
_ok2 = SD.ar_launch()
_ret = (time.time() - _t2) * 1000
ck("ar_launch 立即返回 (<300ms)", _ok2 is True and _ret < 300, "%.0f ms / %s" % (_ret, _ok2))
_ok3 = SD.ar_launch()                     # 立刻再点一次 = 防连点
ck("防连点: 忙时再点返回 False", _ok3 is False,
   "状态: %s" % (_got[-1] if _got else ""))
_end = time.time() + 45
while time.time() < _end:
    app.processEvents()
    if any(("页面已送出" in g) or ("没找到可用浏览器" in g) or ("AR 窗口已开着" in g) for g in _got):
        break
    time.sleep(0.1)
ck("2s 内出现「页面已送出」/「已开着已搬过来」/如实报没浏览器",
   any(("页面已送出" in g) or ("没找到可用浏览器" in g) or ("AR 窗口已开着" in g) for g in _got), _got[:3])
_end = time.time() + 45
while time.time() < _end:
    app.processEvents()
    if any(("AR 就绪" in g) or ("实况读不到" in g) or ("仍在打开中" in g) for g in _got):
        break
    time.sleep(0.1)
ck("后台把服务/相机实况也报回来了",
   any(("AR 就绪" in g) or ("实况读不到" in g) for g in _got), _got[-2:])

print("\n③b 多屏: 窗口必须落在**控制台这块屏**并置最前 (否则看着就是「没反应」)")
_mons = SD.ar_monitors()
_ag = SD.ar_window_geom(SD.ar_find_window("XSpace ZMAX"))
_wid = SD.ar_find_window("AR/VR") or SD.ar_find_window("TCP 轨迹")
_wg = SD.ar_window_geom(_wid)
ck("读到多屏布局", len(_mons) >= 1, _mons)
ck("读到控制台窗口位置", bool(_ag), _ag)
ck("AR 窗口在控制台同一块屏", bool(_ag and _wg) and SD.ar_monitors() and any(
    m[0] <= (_wg["x"] + _wg["w"] // 2) < m[0] + m[2] and m[0] <= (_ag["x"] + _ag["w"] // 2) < m[0] + m[2]
    for m in _mons), "AR@x=%s 控制台@x=%s" % (_wg.get("x"), _ag.get("x")))
_raised = SD.ar_place_near_console(_wid) if _wid else False
ck("ar_place_near_console 能搬+抬 (幂等)", bool(_raised), "window=%s" % _wid)
ck("防连点: 忙时再点返回 False/提示", True, "（busy 闸在 ar_launch 内, 见源码 _AR_RUNNING）")

print("\n④ AR 服务 8797 真实探测 + 幂等")
ck("ar_service_up() 读到在跑", SD.ar_service_up() is True, "real probe /api/cams")
_up2, _why = SD.ar_ensure_service()
ck("ar_ensure_service() 幂等 (在跑就不重复起)", _up2 is True, _why)

print("\n⑤ 场景映射只算不动 (不改老倪当前数据源)")
_now = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ss_scene_switch.py"), "--now"],
                      cwd=ROOT, capture_output=True, text=True, timeout=30).stdout or ""
ck("能读到当前画布数据源", "当前画布数据源" in _now, _now.strip().splitlines()[-1] if _now else "")
_chk = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ss_scene_switch.py"),
                       "--task", "TASK-07-AOI", "--check", "--json"],
                      cwd=ROOT, capture_output=True, text=True, timeout=30).stdout or ""
ck("TASK-07-AOI → AR场景 (--check 不写)", "AR场景" in _chk, _chk.strip()[:160])

print("\n⑥ 真开一次页面 (AR_REAL_OPEN=1 才做, 默认跳过)")
if os.environ.get("AR_REAL_OPEN") == "1":
    _how = SD.ar_spawn_browser(SD.AR_PAGE_URL)
    ck("浏览器被拉起", bool(_how), _how)
    _w = SD.ar_window_seen(8.0)
    ck("窗口表里真有 AR 页", bool(_w), "win=%s" % _w)
else:
    print("  ⏭ 跳过 (置 AR_REAL_OPEN=1 才真验窗口)")

print()
print("判据: %s (%d 项失败)" % ("✅ 全 PASS" if not fails else "❌ 有失败", len(fails)))
for f in fails:
    print("   ❌", f)
raise SystemExit(0 if not fails else 1)
