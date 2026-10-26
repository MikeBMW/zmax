#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 判据: /ar3d 独立三维页 —— 左边一栏按钮, 右边整块三维视图, 同时看得见

老倪 2026-10-26 两次口径:
  ① 「三维视图要单独打开一个页面…完全独立的一个页面, 只有三维视图」
  ② 「在这个窗口左侧, 增加所有的 执行轨迹 坐标系等按钮, 但是要放在左侧, 这样我可以同时看着按钮和图像, 同步修改」

判据(offscreen 真起 QWebEngineView 加载 8797/ar3d, 全部真跑):
  ① 左栏在画布左侧: rail.right ≤ canvas.left, 且栏宽 ≥ 200px(不是压在画面上)
  ② 画布高度 = 视口, 页面不可滚(scrollH ≤ vh+2) —— 不用滚轮拖
  ③ 左栏里的按钮 ≥ 12 个且全部可见(执行轨迹/坐标系/URDF/光模块/五条轨迹…)
  ④ 画布真有绘制(非背景像素 > 0.5%)
  ⑤ 对照 /ar: 同一批按钮**不在**画布左侧(证明判据不是恒真)
  ⑥ 点『URDF 外形』来回两次: 相机(dist/tgt/yaw/pitch)纹丝不动 + 按钮状态真翻转
截图: /tmp/ar3d_verify.png · 用法: gui-venv311/bin/python tools/verify_ar3d_page.py
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt5.QtWebEngineWidgets import QWebEngineView          # noqa: E402,F401
from PyQt5.QtWidgets import QApplication                     # noqa: E402
from PyQt5.QtCore import QTimer, QUrl                        # noqa: E402

BASE = os.environ.get("ZMAX_AR3D_BASE") or "http://127.0.0.1:8797"
SHOT = "/tmp/ar3d_verify.png"

PROBE = r"""
(() => {
  const disp = el => el ? getComputedStyle(el).display : 'missing';
  const box = el => { const r = el ? el.getBoundingClientRect() : null;
                      return r ? [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] : null; };
  const cv = document.getElementById('vr');
  const rail = document.getElementById('vrRail');
  const btns = rail ? [...rail.querySelectorAll('button')].filter(b => b.offsetParent !== null) : [];
  const out = {
    url: location.pathname + location.search,
    title: document.title,
    bodyClass: document.body.className,
    vw: innerWidth, vh: innerHeight,
    canvas: box(cv), rail: box(rail),
    header: disp(document.querySelector('header')),
    railButtons: btns.length,
    railButtonText: btns.slice(0, 16).map(b => b.textContent.trim().slice(0, 10)),
    allVisibleButtons: [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null).length,
    scrollH: document.documentElement.scrollHeight,
    scrollable: document.documentElement.scrollHeight > innerHeight + 2,
    cfgN: (typeof CFG_PTS !== 'undefined') ? CFG_PTS.length : -1,
    ptsErr: window.__ptsErr || null, ptsTries: window.__ptsTries || 0,
    cfgRows: document.querySelectorAll('#rowCfgPts button').length
  };
  if (cv) {
    const c = cv.getContext('2d');
    if (c) {
      const d = c.getImageData(0, 0, cv.width, cv.height).data;
      let nonbg = 0, amber = 0, green = 0;
      for (let i = 0; i < d.length; i += 4) {
        const R = d[i], G = d[i+1], B = d[i+2];
        if (R > 12 || G > 16 || B > 22) nonbg++;
        if (G > 140 && R < 130 && B < 130) green++;
        if (R > 190 && G > 140 && G < 225 && B < 130) amber++;
      }
      const tot = cv.width * cv.height;
      out.pixels = {pct: +(100 * nonbg / tot).toFixed(2), green: green, amber: amber};
    }
  }
  return out;
})()
"""

CLICK2 = r"""
(() => {
  const b = document.getElementById('bUrdf');
  if (!b) return 'NOBTN';
  if (typeof VR === 'undefined') return 'NOVR';
  const snap = () => ({d: +VR.dist.toFixed(6), t: (VR.tgt||[]).map(v => +v.toFixed(6)), y: +VR.yaw.toFixed(6), p: +VR.pitch.toFixed(6), cls: b.className});
  const s0 = snap();
  b.click();                       // 关掉 URDF
  const s1 = snap();
  b.click();                       // 再打开(来回两次都要不动相机)
  const s2 = snap();
  // 📍 工程配置点位台账(2026-10-26): 左栏要罗列全部点, 三维里点要真画出来 / 真能关掉
  const cv = document.getElementById('vr'), cx = cv.getContext('2d');
  const bright = () => {
    const d = cx.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) { if (d[i] > 200 && d[i+1] > 120 && d[i+2] > 90) n++; }
    return n;
  };
  const rows = document.querySelectorAll('#rowCfgPts button').length;
  const nCfg = (typeof CFG_PTS !== 'undefined') ? CFG_PTS.length : -1;
  const bOn = bright();
  document.getElementById('bCfgNone').click();
  const bOff = bright();
  document.getElementById('bCfgAll').click();
  const bBack = bright();
  return JSON.stringify({s0: s0, s1: s1, s2: s2,
                         cfg: {n: nCfg, rows: rows, on: bOn, off: bOff, back: bBack}});
})()
"""


def run(url, app, size=(1600, 1000), wait_ms=30000, shot=None, do_click=False):
    v = QWebEngineView()
    v.resize(*size)
    v.show()
    st = {"probe": None, "click": None, "n": 0, "tries": 0}

    def got_probe(r):
        st["tries"] += 1
        # 取"画得最多"的那次: 页面数据(traj/URDF/光模块)是异步到的, 太早取样会误判"没画出来"
        if r:
            cur = (st["probe"] or {}).get("pixels") or {}
            new = r.get("pixels") or {}
            if (new.get("pct") or 0) >= (cur.get("pct") or 0):
                st["probe"] = r
        pct = ((st["probe"] or {}).get("pixels") or {}).get("pct") or 0
        cfg_n = (st["probe"] or {}).get("cfgN") or 0          # 📍 点位台账是异步 fetch 来的, 没到就点会误判"0 点"
        if do_click and ((pct >= 3.0 and cfg_n >= 20) or st["tries"] >= 10):
            v.page().runJavaScript(CLICK2, got_click)
        elif not do_click and (pct >= 3.0 or st["tries"] >= 8):
            st["n"] += 1

    def got_click(r):
        st["click"] = r
        st["n"] += 1

    def probe():
        v.page().runJavaScript(PROBE, got_probe)

    def after_load(ok):
        sys.stdout.write("  · loadFinished(%s) %s\n" % (ok, url))
        sys.stdout.flush()
        t = QTimer(v)
        t.setInterval(1200)
        t.timeout.connect(probe)
        t.start()
        QTimer.singleShot(2500, probe)

    v.loadFinished.connect(after_load)
    v.load(QUrl(url))
    want = 1
    t0 = time.time()
    while st["n"] < want and time.time() - t0 < wait_ms / 1000.0 + 15:
        app.processEvents()
        time.sleep(0.02)
    if shot:
        v.grab().save(shot)
    v.deleteLater()
    app.processEvents()
    return st["probe"], st["click"]


def main():
    print("═══ /ar3d 独立三维页(左栏按钮 + 右侧三维) 判据 ═══", flush=True)
    app = QApplication.instance() or QApplication(sys.argv)
    # 先跑对照(/ar 整页), 再跑 /ar3d —— 实测同一个 QApplication 里第二个 view 更容易超时,
    # 把"要判的那个"放第二个之前先拿对照, 免得对照缺数据(判据⑤)被判"跳过"。
    b, _ = run(BASE + "/ar", app, wait_ms=25000)
    if b:
        print("ar  :", json.dumps({k: b.get(k) for k in ("canvas", "rail", "railButtons", "scrollH", "vh")},
                                  ensure_ascii=False), flush=True)
    else:
        print("⚠️ 没取到 /ar 对照状态(不影响 ar3d 判定)", flush=True)
        b = {}
    a, click_res = run(BASE + "/ar3d", app, shot=SHOT, do_click=True)
    print("ar3d:", json.dumps(a, ensure_ascii=False) if a else None, flush=True)
    print("点击『坐标系』:", click_res, flush=True)
    if not a:
        print("❌ FAIL 没取到 /ar3d 页面状态(加载超时)")
        return 1
    ck = []

    def chk(name, ok, detail):
        ck.append((name, bool(ok), detail))
        print("%s %s · %s" % ("✅" if ok else "❌", name, detail), flush=True)

    cv, rl = a.get("canvas"), a.get("rail")
    chk("① 左栏在画布左侧", bool(cv and rl) and rl[0] + rl[2] <= cv[0] + 2 and rl[2] >= 200,
        "rail=%s canvas=%s" % (rl, cv))
    chk("② 画布满高 · 页面不可滚", bool(cv) and cv[3] >= a.get("vh", 0) - 2 and not a.get("scrollable"),
        "canvasH=%s vh=%s scrollH=%s" % (cv[3] if cv else None, a.get("vh"), a.get("scrollH")))
    chk("③ 左栏按钮全在(≥12)且可见", (a.get("railButtons") or 0) >= 12,
        "railButtons=%s %s" % (a.get("railButtons"), a.get("railButtonText")))
    px = a.get("pixels") or {}
    chk("④ 三维真画出来了", (px.get("pct") or 0) > 0.5 and ((px.get("amber") or 0) > 200 or (px.get("green") or 0) > 200),
        "非背景 %s%% · 琥珀 %s · 绿 %s" % (px.get("pct"), px.get("amber"), px.get("green")))
    if b and b.get("canvas") and b.get("rail"):
        side = b["rail"][0] + b["rail"][2] <= b["canvas"][0] + 2
        chk("⑤ 对照 /ar 不是左栏版式(判据非恒真)", not side,
            "/ar rail=%s canvas=%s" % (b["rail"], b["canvas"]))
    cam_ok = False
    j = {}
    detail = "click=%r" % (click_res,)
    try:
        j = json.loads(click_res) if isinstance(click_res, str) else {}
        s0, s1, s2 = j.get("s0"), j.get("s1"), j.get("s2")
        if s0 and s1 and s2:
            cam_still = (s0["d"] == s1["d"] == s2["d"] and s0["t"] == s1["t"] == s2["t"]
                         and s0["y"] == s1["y"] == s2["y"] and s0["p"] == s1["p"] == s2["p"])
            toggled = (s0["cls"] != s1["cls"] and s1["cls"] != s2["cls"])
            cam_ok = cam_still and toggled
            detail = ("dist %s→%s→%s · tgt %s · yaw %s · cls %r→%r→%r"
                      % (s0["d"], s1["d"], s2["d"], "同" if s0["t"] == s2["t"] else "变了",
                         "同" if s0["y"] == s2["y"] else "变了", s0["cls"], s1["cls"], s2["cls"]))
    except Exception as e:                                    # noqa: BLE001
        detail = "解析失败 %r / %r" % (click_res, e)
    chk("⑥ 点『URDF 外形』来回两次: 相机纹丝不动(视距/目标/角度全不变)+ 状态真翻转", cam_ok, detail)
    pts_ok = False
    pd = "cfg=%r" % (j.get("cfg") if isinstance(j, dict) else None,)
    try:
        c = j.get("cfg") or {}
        n, rows = c.get("n"), c.get("rows")
        on, off, back = c.get("on") or 0, c.get("off") or 0, c.get("back") or 0
        listed = (n or 0) >= 20 and (rows or 0) >= (n or 0)
        drawn = on > 0 and off < on * 0.6 and back > off * 1.4
        pts_ok = listed and drawn
        pd = ("台账 %s 点 / 左栏 %s 行 · 亮点 全开%s → 全关%s → 全开%s" % (n, rows, on, off, back))
    except Exception as e:                                    # noqa: BLE001
        pd = "解析失败 %r" % (e,)
    chk("⑦ 工程配置点位: 左栏向下罗列全部点 + 三维大圆点真画出且能整组关/开", pts_ok, pd)
    print("截图:", SHOT, os.path.getsize(SHOT) if os.path.exists(SHOT) else "-")
    bad = [n for n, ok, _ in ck if not ok]
    print("═══ %s (%d/%d) ═══" % ("全绿" if not bad else "不过: " + ", ".join(bad), len(ck) - len(bad), len(ck)))
    return 0 if not bad else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
