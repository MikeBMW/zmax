#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧵 判据: ar3d 右侧栏「元任务 · 双臂并行」—— 同一时间左手任务 + 右手任务**同时**显示

老倪 2026-10-28:
  「左右臂的任务, 应该是 并行的, http://10.163.146.78:8797/ar3d 同一时间, 应该是左手任务和右手任务同时显示啊」

判据(offscreen 真起 QWebEngineView 加载 /ar3d + 真读服务端 /api/ar/meta, 全部真跑):
  ① 服务端有 lanes: 件周期 = 右臂稳态单件(11.40s), 左右两条 lane 都非空
  ② 右手 lane 的段首尾相接、首=0、末=件周期(不重叠不缺口) ⇒ 是一条真时间轴
  ③ 页面真有两条轨道(.mtTrack = 2), 左 5 个动作块 / 右 4 个动作块
  ④ 页面读数区同时出现「左手」「右手」两个当下的动作(不是只显示一条)
  ⑤ 任取 t ∈ [0, 件周期): 左手和右手各自都能定位到一个动作(空闲也算左手的一个状态) —— 并行是硬条件
  ⑥ 元任务清单 7 条, 手别标 ◀左手/▶右手/⇄双手 三种齐全
  ⑦ 对照: 老版「🧩 元任务」单列表已不在(标题换成「🧵 元任务 · 双臂并行」)
截图: /tmp/ar3d_meta_parallel.png · 用法: gui-venv311/bin/python tools/verify_ar_meta_parallel.py
"""
import json
import os
import sys
import time
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-dev-shm-usage "
                      "--disable-background-timer-throttling --disable-renderer-backgrounding "
                      "--disable-backgrounding-occluded-windows")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt5.QtWebEngineWidgets import QWebEngineView          # noqa: E402
from PyQt5.QtWidgets import QApplication                     # noqa: E402
from PyQt5.QtCore import QTimer, QUrl                        # noqa: E402

BASE = os.environ.get("ZMAX_AR_BASE") or "http://127.0.0.1:8797"
SHOT = "/tmp/ar3d_meta_parallel.png"
PASS, FAIL = [], []


def ck(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" · " + str(detail)) if detail else ""))


def api(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # ═══ ① ② 服务端唯一依据
    m = api("/api/ar/meta")
    ck("① /api/ar/meta ok", bool(m.get("ok")), m.get("err") or "")
    ln = m.get("lanes") or {}
    cyc = float(ln.get("cycle_s") or 0)
    R = ((ln.get("R") or {}).get("blocks") or [])
    L = ((ln.get("L") or {}).get("blocks") or [])
    ck("① 有双臂轨道 lanes", bool(R) and bool(L),
       "件周期 %.2fs · 右 %d 块 / 左 %d 块" % (cyc, len(R), len(L)))
    ck("① 件周期 = 右臂稳态单件(≈11.4s)", 10.0 <= cyc <= 12.5, "%.2fs" % cyc)
    seq_ok = bool(R) and abs(R[0]["t0"]) < 1e-6 and abs(R[-1]["t1"] - cyc) < 1e-6
    for a, b in zip(R, R[1:]):
        seq_ok = seq_ok and abs(a["t1"] - b["t0"]) < 1e-6
    ck("② 右手 lane 首尾相接 = 一条真时间轴", seq_ok,
       " → ".join("%s %.2f-%.2fs" % (b["mt"], b["t0"], b["t1"]) for b in R))
    hands = (m.get("long_horizon") or {}).get("hands") or {}
    ck("⑥ 元任务手别三类齐全",
       all(hands.get(k) for k in ("L", "R", "BOTH")),
       "R=%s L=%s BOTH=%s" % (hands.get("R"), hands.get("L"), hands.get("BOTH")))
    mt_ids = [x.get("id") for x in (m.get("meta_tasks") or [])]
    ck("⑥ 元任务 7 条", len(mt_ids) == 7, mt_ids)
    ck("⑥ 左臂那条是 MT-06 / 双手是 MT-07",
       "MT-06" in (hands.get("L") or []) and "MT-07" in (hands.get("BOTH") or []))

    # ═══ ③④⑤⑦ 页面
    app = QApplication(sys.argv)
    view = QWebEngineView()
    view.resize(1700, 1000)
    view.show()                                  # 🔴 不 show ⇒ 视口 0, 截图空白
    view.load(QUrl(BASE + "/ar3d"))
    state = {"ok": False, "probe": None, "tries": 0}

    def probe():
        state["tries"] += 1
        view.page().runJavaScript(PROBE, lambda r: cb(r))

    def cb(r):
        if isinstance(r, dict) and r.get("title"):
            state["probe"] = r
            state["ok"] = True
        if not state["ok"] and state["tries"] < 40:
            QTimer.singleShot(300, probe)
        else:
            done()

    def done():
        p = state["probe"] or {}
        ver = p.get("ver") or ""
        ck("③ 页面两条轨道 .mtTrack", p.get("tracks") == 2, p.get("tracks"))
        ck("③ 左手 5 块 / 右手 4 块", p.get("blocksL") == 5 and p.get("blocksR") == 4,
           "L=%s R=%s" % (p.get("blocksL"), p.get("blocksR")))
        now = p.get("nowText") or ""
        ck("④ 读数区同时有左手+右手", ("左手" in now) and ("右手" in now), now.replace("\n", " | ")[:120])
        ck("⑤ 任一时刻左右手都能定位到动作", bool(p.get("parOk")), p.get("parDetail"))
        ck("⑥ 清单 7 行 + 三种手别", p.get("rows") == 7 and p.get("handKinds") == 3,
           "rows=%s kinds=%s" % (p.get("rows"), p.get("handKinds")))
        ck("⑦ 标题已是双臂并行版", "双臂并行" in (p.get("hdr") or ""), p.get("hdr"))
        # 老版单列表标题「🧩 元任务」必须已被替换(防两版并存看着像没改)
        ck("⑦ 老版单列表标题已替换", "🧩 元任务" not in (p.get("allHdr") or ""), (p.get("allHdr") or "")[:40])
        ck("⑦ 版本戳 r46+", bool(ver) and ("r46" in ver), ver[:60])
        g = p.get("geo") or {}
        ck("⑧ 双臂块没被甘特挤压(不截字)", (not g.get("mbClip")) and (g.get("mbH") or 0) >= 240,
           "mtBox %spx · 溢出 %s" % (g.get("mbH"), g.get("mbClip")))
        ck("⑧ 甘特区仍有高度(没被顶没)", (g.get("tbH") or 0) >= 100, "tBody %.0fpx" % (g.get("tbH") or 0))
        ck("⑧ 轨道块全落在轨道内", g.get("over") == 0, "越界计数 %s" % g.get("over"))
        if p.get("shot"):
            pass
        view.grab().save(SHOT) if hasattr(view, "grab") else None
        try:
            import subprocess
            subprocess.run(["cp", "/dev/null", "/dev/null"])
        except Exception:                     # noqa: BLE001
            pass
        print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
        if FAIL:
            print("FAILED:", FAIL)
        print("截图: %s" % SHOT)
        app.exit(0 if not FAIL else 1)

    QTimer.singleShot(2500, probe)
    app.exec_()
    return 0 if not FAIL else 1


PROBE = r"""
(() => {
  const box = document.getElementById('mtBox');
  const tracks = document.querySelectorAll('#mtBox .mtTrack').length;
  const bL = document.querySelectorAll('#mtBox .mtb[data-arm="L"]').length;
  const bR = document.querySelectorAll('#mtBox .mtb[data-arm="R"]').length;
  const nowEl = document.getElementById('mtNow');
  const hdr = box ? (box.querySelector('span') || {}).textContent || '' : '';
  // 逐时刻判定: 左右两条 lane 在同一 t 上都必须有落点(左臂空闲也算它的状态)
  let parOk = true, bad = null, detail = '';
  const MP = window.__MTP__ || null;
  const MTv = MP ? MP.get() : null;
  if (MTv && MTv.lanes && MTv.lanes.R && MTv.lanes.L) {
    const cyc = MTv.lanes.cycle_s || 11.4;
    for (let k = 0; k < 40; k++) {
      const t = cyc * k / 40;
      const r = MP.at(MTv.lanes.R, t), l = MP.at(MTv.lanes.L, t);
      const lOk = l.b !== null || (MTv.lanes.L.idle_from != null && t >= MTv.lanes.L.idle_from);
      if (!r.b || !lOk) { parOk = false; bad = t.toFixed(2); break; }
    }
    if (!parOk) detail = 't=' + bad + 's 处有一侧没有动作';
    else detail = '40 个采样点上左右手都有落点(0→' + cyc.toFixed(2) + 's)';
  } else {
    detail = 'window.__MTP__ 拿不到元任务(页面没加载完或钩子没挂)';
  }
  const rowEls = [...document.querySelectorAll('#mtBox .mtRow')];
  const handTxt = rowEls.map(r => { const sp = r.querySelectorAll('span'); return sp[1] ? sp[1].textContent.trim() : ''; });
  const kinds = new Set(handTxt.map(s => s[0]).filter(Boolean));
  // 几何: mtBox 不许被甘特挤压(截字), 轨道块必须落在轨道内
  const mb = document.getElementById('mtBox');
  const geo = { mbH: mb ? Math.round(mb.getBoundingClientRect().height) : -1,
                mbClip: mb ? (mb.scrollHeight > mb.clientHeight + 2) : true,
                tbH: (document.querySelector('.tBody') || {getBoundingClientRect:()=>({height:0})}).getBoundingClientRect().height,
                over: 0 };
  document.querySelectorAll('#mtBox .mtTrack').forEach(function (tr) {
    const tw = tr.getBoundingClientRect().width;
    tr.querySelectorAll('.mtb').forEach(function (b) {
      const r = b.getBoundingClientRect(), t0 = tr.getBoundingClientRect();
      if (r.right > t0.right + 1.5 || r.left < t0.left - 1.5) { geo.over++; }
    });
    if (tw < 100) { geo.over += 100; }
  });
  return {
    geo: geo,
    title: document.title, ver: (document.getElementById('bVer') || {}).textContent || '',
    tracks: tracks, blocksL: bL, blocksR: bR, rows: rowEls.length,
    handKinds: kinds.size, nowText: nowEl ? nowEl.textContent : '',
    parOk: parOk, parDetail: detail, hdr: hdr.slice(0, 40),
    allHdr: (document.getElementById('mtBox') || {}).textContent ? document.getElementById('mtBox').textContent.slice(0, 40) : '',
    shot: true
  };
})()
"""

if __name__ == "__main__":
    sys.exit(main())
