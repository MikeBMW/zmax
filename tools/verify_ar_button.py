#!/usr/bin/env python3
"""判据: 3D 场景「🥽 AR」按钮 —— ①切 AR 数据源 ②确保 8797 在跑 ③真打开 http://127.0.0.1:8797/ar
(老倪 2026-10-12: 「点击 AR按钮, 直接打开这个页面」/「怎么没有打开服务呢? 场景也没有切换啊」)
真跑, 不靠看代码。AR_REAL_OPEN=1 时最后一步真把浏览器拉起来(桌面可见)。
"""
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
sys.path.insert(0, "/home/ubuntu/zmax/src")

import ss_dreamview as SD

fails = []


def ck(name, ok, extra=""):
    print("  %s %s%s" % ("✅" if ok else "❌", name, (" — " + str(extra)) if extra else ""))
    if not ok:
        fails.append(name)


print("① 目标地址")
ck("AR 页面地址 = http://127.0.0.1:8797/ar", SD.AR_PAGE_URL == "http://127.0.0.1:8797/ar", SD.AR_PAGE_URL)
_src = open("/home/ubuntu/zmax/tools/gui/ss_dreamview.py", encoding="utf-8").read()
_i = _src.find("def _open_ar_view")
_body = _src[_i:_i + 6000]
ck("按钮回调里调的就是 ar_open_url(AR_PAGE_URL)",
   "ar_open_url(AR_PAGE_URL)" in _body and "?cam=" not in _body.split("def ")[0])
ck("按钮回调里会切场景 (ar_switch_scene)", "ar_switch_scene(" in _body)
ck("按钮回调里会确保服务在跑 (ar_ensure_service)", "ar_ensure_service(" in _body)
_from = _i
_i2 = _src.find("def _open_ar_view", 0)
ck("该窗口的 AR 按钮 sid=None 走 _open_ar_view", "self._open_ar_view() if sid is None" in _src)

print("② AR 服务(8797) 真实探测")
_up = SD.ar_service_up()
ck("ar_service_up() 读到服务在跑", _up is True, "real probe /api/cams")
_up2, _why = SD.ar_ensure_service()
ck("ar_ensure_service() 幂等(在跑就不重复起)", _up2 is True, _why)

print("③ 切场景/数据源 → AR (真源 ss_scene_switch.py, 回读画布)")
_j = SD.ar_switch_scene("TASK-07-AOI")
ck("切到 AR场景 成功", bool(_j.get("ok")), _j.get("msg"))
ck("回读 src_state == AR场景", _j.get("src_state") == "AR场景", _j.get("src_state"))
_j2 = SD.ar_switch_scene("TASK-06-TRAY")      # 还原老倪原来的状态: 摆盘 + 任务6
ck("还原到摆盘场景(交还原状态)", bool(_j2.get("ok")) and _j2.get("src_state") == "摆盘场景", _j2.get("msg"))

print("④ 打开页面: 逐条候选 + **验窗口真出现**(不认 webbrowser 的返回值)")
_how_dry = SD.ar_open_url(dry=True)
ck("探路能定出至少一条可用路", bool(_how_dry), _how_dry)
ck("有窗口表检查 ar_window_seen", callable(getattr(SD, "ar_window_seen", None)))
ck("有置顶 ar_raise_window", callable(getattr(SD, "ar_raise_window", None)))
if os.environ.get("AR_REAL_OPEN") == "1":
    import subprocess as _sp
    _sp.run(["pkill", "-f", "127.0.0.1:8797"], capture_output=True)   # 先把已开的 AR 窗口关掉, 好真测一次拉起
    import time as _t
    _t.sleep(2)
    _w0 = SD.ar_window_seen(1.0)
    ck("关掉后窗口表里确实没有 AR 页(检查不是摆设)", _w0 == "", "win=%r" % _w0)
    _how = SD.ar_open_url(timeout=12.0)
    _w1 = SD.ar_window_seen(1.0)
    ck("真打开: 返回「窗口已出现」", "窗口已出现" in _how, _how)
    ck("真打开: 窗口表里确有该页(可被老倪看到)", bool(_w1), "win=%s" % _w1)
else:
    print("  ⏭ 跳过真打开 (置 AR_REAL_OPEN=1 才真开)")

print()
print("判据: %s (%d 项失败)" % ("✅ 全 PASS" if not fails else "❌ 有失败", len(fails)))
raise SystemExit(0 if not fails else 1)
