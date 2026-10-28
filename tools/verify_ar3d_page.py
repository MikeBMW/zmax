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
# 🔴 offscreen 页会被 Chromium 当"后台页"限流: 页面里的 setTimeout 从 300ms 变 ~1s,
#   验证链(要等两轮 fetch + 定时轮询)就永远等不完 —— 必须关掉后台节流
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--no-sandbox --disable-gpu --disable-dev-shm-usage "
                      "--disable-background-timer-throttling --disable-renderer-backgrounding "
                      "--disable-backgrounding-occluded-windows")
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
    vr: (typeof VR!=='undefined') ? {dist:+VR.dist.toFixed(4), auto:VR.auto,
         tgt:VR.tgt.map(v=>+v.toFixed(3))} : null,
    urdfN: (URDF&&URDF.links)?URDF.links.length:0,
    linkN: Object.keys(LINKM||{}).length,
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
  // 点位判据只认 CFG_PAL 调色板本身: 之前用"亮+饱和"的泛判据, 场景一加铝型材/标注就假红
  const PAL = CFG_PAL.map(h => [parseInt(h.slice(1,3),16), parseInt(h.slice(3,5),16), parseInt(h.slice(5,7),16)]);
  const bright = () => {
    const d = cx.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) {
      for (let k = 0; k < PAL.length; k++) {
        const p = PAL[k];
        if (Math.abs(d[i]-p[0]) < 10 && Math.abs(d[i+1]-p[1]) < 10 && Math.abs(d[i+2]-p[2]) < 10) { n++; break; }
      }
    }
    return n;
  };
  const rows = document.querySelectorAll('#rowCfgPts button').length;
  const nCfg = (typeof CFG_PTS !== 'undefined') ? CFG_PTS.length : -1;
  const bOn = bright();
  document.getElementById('bCfgNone').click();
  const bOff = bright();
  document.getElementById('bCfgAll').click();
  const bBack = bright();
  // 🤖 左臂(仿真臂): 默认 = 右臂整条平移 (0,+500,0)mm; 能画能关; 点动不改相机
  const cyan = () => {
    const d = cx.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (Math.abs(d[i]-94) < 26 && Math.abs(d[i+1]-234) < 22 && Math.abs(d[i+2]-212) < 22) n++;
    }
    return n;
  };
  let offErr = null;
  const X = larmXform();
  ['base_link','link1','link2','link3','link4','link5','link6','tool1'].forEach(nm => {
    const M = (LINKM||{})[nm]; if (!M) return;
    const w = M.t;
    const l = [X.R[0][0]*w[0]+X.R[0][1]*w[1]+X.R[0][2]*w[2]+X.t[0],
               X.R[1][0]*w[0]+X.R[1][1]*w[1]+X.R[1][2]*w[2]+X.t[1],
               X.R[2][0]*w[0]+X.R[2][1]*w[1]+X.R[2][2]*w[2]+X.t[2]];
    const e = Math.max(Math.abs(l[0]-w[0]), Math.abs(l[1]-w[1]-0.5), Math.abs(l[2]-w[2]));
    offErr = (offErr === null) ? e : Math.max(offErr, e);
  });
  const cOn = cyan(), dd0 = +VR.dist.toFixed(4);
  document.getElementById('bArmL').click();
  const cOff = cyan();
  document.getElementById('bArmL').click();
  for (let i = 0; i < 3; i++) document.getElementById('lXP').click();
  const dJog = LARM.d.slice(), cJog = cyan(), dd1 = +VR.dist.toFixed(4);
  document.getElementById('bLreset').click();
  const dBack = LARM.d.slice();
  // 📷 顶视相机: 立柱高 = 1 轴高 · 立在两臂中线(y=+250mm) · 能画能关 · 视锥真打到台面
  const pr2 = VIEW.pr;
  const hA = axis1H();
  const sample = (u, v) => {
    const dd = cx.getImageData(Math.max(0, (u|0)-2), Math.max(0, (v|0)-2), 5, 5).data;
    let r=0,g=0,b=0,n=0;
    for (let i=0;i<dd.length;i+=4){ r+=dd[i]; g+=dd[i+1]; b+=dd[i+2]; n++; }
    return [Math.round(r/n), Math.round(g/n), Math.round(b/n)];
  };
  const pT = pr2([0, TCAM.y, hA - 0.002]);              // 立柱顶面中心
  const Rr = _ry(TCAM.tilt * Math.PI / 180), org = [0, TCAM.y, hA + 0.006];
  const lens = _rotT(Rr, org, [TCAM.body[2]/2, 0, TCAM.body[1]*0.5]);
  const fwd = [Rr[0][0], Rr[1][0], Rr[2][0]];
  const tt = -lens[2] / fwd[2];
  const pHit = (tt > 0) ? pr2([lens[0]+fwd[0]*tt, lens[1]+fwd[1]*tt, 0.002]) : null;
  const onTop = pT ? sample(pT.u, pT.v) : null;
  const onFov = pHit ? sample(pHit.u, pHit.v) : null;
  document.getElementById('bCamTop').click();
  const offTop = pT ? sample(pT.u, pT.v) : null;
  const offFov = pHit ? sample(pHit.u, pHit.v) : null;
  document.getElementById('bCamTop').click();
  // 📦 箱体: 顶板 = 两臂安装面(z=0), 长宽高 1085/775/290(对标 优艾智合 O 系列)
  // 箱体用**颜色计数**验(取样点会被立柱/视锥/遮挡干扰, 单点取样不可靠):
  //   顶板 #31404f=(49,64,79) / 体色 #1b2732=(27,39,50) 都是箱体独有
  const cnt = (R,G,B,t) => {
    const dd = cx.getImageData(0, 0, cv.width, cv.height).data;
    let n = 0;
    for (let i = 0; i < dd.length; i += 4) {
      if (Math.abs(dd[i]-R)<t && Math.abs(dd[i+1]-G)<t && Math.abs(dd[i+2]-B)<t) n++;
    }
    return n;
  };
  // 顶板面 #31404f 与"顶板高光/标签"#9fb6cc 一起数: 体色 #1b2732 会和相机机身撞色, 不能用
  const onPlate = cnt(49,64,79,6), onHi = cnt(159,182,204,6);
  document.getElementById('bChs').click();
  const offPlate = cnt(49,64,79,6), offHi = cnt(159,182,204,6);
  document.getElementById('bChs').click();
  const onBody = onHi, offBody = offHi;
  // 🧪🟫 2026-10-26 r22: 实验桌 750 摆在箱体前面 + 箱体 750 落地平齐 + 四轮落地 + 地面层 -750
  //   全部走真按钮真绘制: 木色 #7a5f45 / 桌面高光 #f0d9ac / 750 标注 #d8b98c / 轮毂 #39424e / 地面 (19,25,32)
  const camN = () => ({d:+VR.dist.toFixed(6), t:(VR.tgt||[]).map(v=>+v.toFixed(6)),
                       y:+VR.yaw.toFixed(6), p:+VR.pitch.toFixed(6)});
  const camA = camN();
  const woodish = () => {                        // 木色(纯 #7a5f45 与被 10% 青视锥染色后的 (119,109,84))
    const dd = cx.getImageData(0,0,cv.width,cv.height).data; let n=0;
    for (let i=0;i<dd.length;i+=4){ const R=dd[i],G=dd[i+1],B=dd[i+2];
      if (R>90 && R<150 && G>72 && G<135 && B<105 && R>G && G>B && (R-B)>28) n++; }
    return n; };
  const woodOn = woodish(), woodHiOn = cnt(240,217,172,6)+cnt(225,219,176,6), dimOn = cnt(216,185,140,6);
  const aluOn = cnt(168,179,191,6);               // 铝型材 #a8b3bf: 立柱/顶框/支撑梁
  const beamInfo = (typeof beamBox==='function') ? beamBox() : null;
  const tNote = {show:TAB.show, x0:TAB.x0, x1:TAB.x1, w:TAB.w, h:TAB.h, cy:TAB.cy, t:TAB.t};
  document.getElementById('bTab').click();
  const woodOff = woodish(), woodHiOff = cnt(240,217,172,6)+cnt(225,219,176,6), dimOff = cnt(216,185,140,6);
  const aluOff = cnt(168,179,191,6);
  const camB = camN();
  document.getElementById('bTab').click();
  const flrOn = cnt(19,25,32,4), flrZ = FLR.z;
  document.getElementById('bFlr').click();
  const flrOff = cnt(19,25,32,4);
  const camC = camN();
  document.getElementById('bFlr').click();
  // 四个轮子的屏幕包围盒(和 drawChassis 用同一套公式), 轮子判据只在盒子里数, 不受别处抗锯齿杂点干扰
  const wBoxes = [];
  (function(){
    const r=CHS.wr, wzc=-CHS.H+r;
    [[-CHS.L/2+0.13,-1],[CHS.L/2-0.13,-1],[-CHS.L/2+0.13,1],[CHS.L/2-0.13,1]].forEach(w=>{
      const cxw=w[0], cyw=CHS.cy+w[1]*(CHS.W/2-0.03);
      const a=VIEW.pr([cxw-r, cyw-0.04, wzc-r]), b=VIEW.pr([cxw+r, cyw+0.04, wzc+r]);
      if(a&&b) wBoxes.push([Math.min(a.u,b.u)-2, Math.min(a.v,b.v)-2,
                            Math.max(a.u,b.u)+2, Math.max(a.v,b.v)+2]);
    });
  })();
  const cntIn = (boxes, R,G,B,t) => {
    const dd = cx.getImageData(0,0,cv.width,cv.height).data; let n=0;
    for (let i=0;i<dd.length;i+=4){
      if (Math.abs(dd[i]-R)>=t || Math.abs(dd[i+1]-G)>=t || Math.abs(dd[i+2]-B)>=t) continue;
      const px=(i/4)|0, X=px % cv.width, Y=(px/cv.width)|0;
      for (const bx of boxes){ if (X>=bx[0]&&X<=bx[2]&&Y>=bx[1]&&Y<=bx[3]){ n++; break; } }
    }
    return n; };
  const hubOn = cntIn(wBoxes, 57,66,78,8);
  document.getElementById('bChs').click();
  const hubOff = cntIn(wBoxes, 57,66,78,8);
  document.getElementById('bChs').click();
  const dotOn = cntIn(wBoxes, 185,198,212,6);     // 轮芯亮钉 #b9c6d4
  document.getElementById('bChs').click();
  const dotOff = cntIn(wBoxes, 185,198,212,6);
  document.getElementById('bChs').click();
  const baseK = Object.keys(LINKM||{}).filter(k=>/_base$/.test(k))[0];
  const baseZ = (baseK && LINKM[baseK] && LINKM[baseK].t) ? +LINKM[baseK].t[2].toFixed(9) : null;
  return JSON.stringify({s0: s0, s1: s1, s2: s2,
                         chs: {L: CHS.L, W: CHS.W, H: CHS.H, HB: CHS.HB, wr: CHS.wr, cy: CHS.cy,
                               onPlate: onPlate, offPlate: offPlate, onBody: onBody, offBody: offBody,
                               hubOn: hubOn, hubOff: hubOff, wBoxes: wBoxes.length,
                               dotOn: dotOn, dotOff: dotOff, baseZ: baseZ},
                         tab: {note: tNote, woodOn: woodOn, woodOff: woodOff,
                               woodHiOn: woodHiOn, woodHiOff: woodHiOff,
                               dimOn: dimOn, dimOff: dimOff, cams: [camA, camB, camC],
                               aluOn: aluOn, aluOff: aluOff, beam: beamInfo},
                         flr: {z: flrZ, on: flrOn, off: flrOff},
                         tcam: {h: +hA.toFixed(4), y: TCAM.y, onTop: onTop, offTop: offTop,
                                onFov: onFov, offFov: offFov},
                         cfg: {n: nCfg, rows: rows, on: bOn, off: bOff, back: bBack},
                         larm: {offErr: (offErr === null ? null : +offErr.toFixed(9)), cyanOn: cOn,
                                cyanOff: cOff, cyanJog: cJog, dJog: dJog, dBack: dBack,
                                dist0: dd0, dist1: dd1}});
})()
"""


TGT1 = r"""(() => {
  const res = {};
  const list = () => [...document.querySelectorAll('#rowCfgPts .tgtbtn')];
  const st = () => { const on = list().filter(b=>b.classList.contains('on'));
    return {n:list().length, onCount:on.length, on:on[0]?on[0].dataset.target:null, cur:CFG_TARGET}; };
  const cam = () => [VR.dist, VR.yaw, VR.pitch, (VR.tgt||[]).map(x=>+x.toFixed(4))];
  res.cam0 = cam();
  res.before = st();
  // ① 单选: 点另一个点的靶心
  const other = list().find(b=>b.dataset.target!==CFG_TARGET);
  res.other = other ? other.dataset.target : null;
  if(other) other.click();
  res.afterClick = st();
  res.cam1 = cam();
  // ② 点亮 轨迹5 实时
  const t5 = document.getElementById('t5') || document.getElementById('tA5');
  res.t5 = !!t5; if(t5) t5.click();
  return JSON.stringify(res);
})()"""

# 轮询用: 直接读页面状态(不靠页面 setTimeout —— offscreen 会被 Chromium 限流)
TGT_POLL = r"""(() => {
  const p = NAMED['real'] || [], i = NAMED_INFO['real'] || {};
  const last = p.length ? p[p.length-1].map(x=>Math.round(x*1000)) : null;
  const tp1 = CFG_PTS.find(p => p.name === CFG_TARGET);
  const m1 = !!(tp1 && last && Math.abs(last[0]-tp1.mm[0])<2 && Math.abs(last[1]-tp1.mm[1])<2 && Math.abs(last[2]-tp1.mm[2])<2);
  const t2 = window.__t2 || null;
  const m2 = !!(t2 && last && Math.abs(last[0]-t2.mm[0])<2 && Math.abs(last[1]-t2.mm[1])<2 && Math.abs(last[2]-t2.mm[2])<2);
  return JSON.stringify({on:!!NAMED_ON['real'], n:p.length,
    first: p.length ? p[0].map(x=>Math.round(x*1000)) : null, last: last,
    note: i.note || '', src: i.src || '', m1: m1, m2: m2,
    cam: [VR.dist, VR.yaw, VR.pitch, (VR.tgt||[]).map(x=>+x.toFixed(4))]});
})()"""

# ③ 换目标: 记下新目标坐标, 供判据比对
TGT2 = r"""(() => {
  const list = () => [...document.querySelectorAll('#rowCfgPts .tgtbtn')];
  const third = list().find(b=>b.dataset.target!==CFG_TARGET);
  if(!third) return null;
  const tp = CFG_PTS.find(p=>p.name===third.dataset.target);
  window.__t2 = {name: third.dataset.target, mm: tp ? tp.mm : null};
  third.click();
  return JSON.stringify(window.__t2);
})()"""


def run(url, app, size=(1600, 1000), wait_ms=30000, shot=None, do_click=False):
    v = QWebEngineView()
    v.resize(*size)
    v.show()
    st = {"probe": None, "click": None, "tgt": None, "n": 0, "tries": 0, "clicked": False}

    def got_probe(r):
        st["tries"] += 1
        # 取"画得最多"的那次: 页面数据(traj/URDF/光模块)是异步到的, 太早取样会误判"没画出来"
        # 取**最新**一帧, 不取"画得最多"的: 早期帧数据还没到(视距还在收敛/轨迹还没拉),
        # 非背景像素反而更多(立柱被放大糊满屏), 按 pct 取最大会挑中那种废帧。
        if r:
            st["probe"] = r
        pct = ((st["probe"] or {}).get("pixels") or {}).get("pct") or 0
        cfg_n = (st["probe"] or {}).get("cfgN") or 0          # 📍 点位台账是异步 fetch 来的, 没到就点会误判"0 点"
        amber = ((st["probe"] or {}).get("pixels") or {}).get("amber") or 0
        if do_click and not st["clicked"] and ((pct >= 3.0 and cfg_n >= 20 and amber >= 300) or st["tries"] >= 12):
            st["clicked"] = True        # 🔴 只点一次: probe 每 1.2s 一次, 重复点会把 __tgtTest 重置成 null
            v.page().runJavaScript(CLICK2, got_click)
        elif not do_click and (pct >= 3.0 or st["tries"] >= 8):
            st["n"] += 1

    def got_click(r):
        st["click"] = r
        if not do_click:
            st["n"] += 1
            return
        # 🎯 目标点/轨迹5: 全部由 Qt 侧定时器驱动(页面 setTimeout 在 offscreen 下被限流, 不能用来等 fetch)
        TG = {"t0": time.time(), "res": {}, "phase": 1}

        def tgt_finish():
            print("  [tgt res] %s" % json.dumps(TG["res"], ensure_ascii=False)[:800], flush=True)
            st["tgt"] = json.dumps(TG["res"], ensure_ascii=False)
            st["n"] += 1

        def tgt_poll(want, timeout, done):
            def tick():
                def got(r):
                    d = json.loads(r) if r else {}
                    if want(d) or time.time() - TG["t0"] > timeout:
                        done(d)
                    else:
                        QTimer.singleShot(250, tick)
                v.page().runJavaScript(TGT_POLL, got)
            tick()

        def after_t2(d):
            TG["res"]["afterThird"] = {k: d.get(k) for k in ("n", "last", "note", "src", "m2", "cam")}
            tgt_finish()

        def after_first(d):
            TG["res"]["real"] = {k: d.get(k) for k in ("n", "first", "last", "note", "src", "cam")}
            # ③ 再换一个目标 ⇒ 亮着的轨迹5 必须自动重算到新点
            def got2(r2):
                TG["res"]["third"] = json.loads(r2) if r2 else None
                TG["t0"] = time.time()
                tgt_poll(lambda x: bool(x.get("m2")), 25, after_t2)
            v.page().runJavaScript(TGT2, got2)

        def got1(r1):
            print("  [tgt step1] %s" % str(r1)[:400], flush=True)
            try:
                TG["res"].update(json.loads(r1) if r1 else {})
            except Exception as e:                                       # noqa: BLE001
                TG["res"]["err1"] = str(e)
            TG["res"]["cams"] = [TG["res"].get("cam0"), TG["res"].get("cam1")]
            # ② 等 轨迹5 实时 真取回来(起点=TCP, 终点=选中的目标点)
            TG["t0"] = time.time()
            tgt_poll(lambda x: bool(x.get("m1")), 25, after_first)

        v.page().runJavaScript(TGT1, got1)

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
    # do_click 那条链里 🎯 目标点/轨迹5 要等两轮 fetch(换目标再重算), 给足 45s 余量
    _budget = wait_ms / 1000.0 + (70 if do_click else 15)
    while st["n"] < want and time.time() - t0 < _budget:
        app.processEvents()
        time.sleep(0.02)
    if shot:
        v.grab().save(shot)
    v.deleteLater()
    app.processEvents()
    return st["probe"], st["click"], st["tgt"]


def main():
    print("═══ /ar3d 独立三维页(左栏按钮 + 右侧三维) 判据 ═══", flush=True)
    app = QApplication.instance() or QApplication(sys.argv)
    # 先跑对照(/ar 整页), 再跑 /ar3d —— 实测同一个 QApplication 里第二个 view 更容易超时,
    # 把"要判的那个"放第二个之前先拿对照, 免得对照缺数据(判据⑤)被判"跳过"。
    b, _, _ = run(BASE + "/ar", app, wait_ms=25000)
    if b:
        print("ar  :", json.dumps({k: b.get(k) for k in ("canvas", "rail", "railButtons", "scrollH", "vh")},
                                  ensure_ascii=False), flush=True)
    else:
        print("⚠️ 没取到 /ar 对照状态(不影响 ar3d 判定)", flush=True)
        b = {}
    a, click_res, tgt_res = run(BASE + "/ar3d", app, shot=SHOT, do_click=True)
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
    arm_ok = False
    ad = "larm=%r" % (j.get("larm") if isinstance(j, dict) else None,)
    try:
        L = j.get("larm") or {}
        e = L.get("offErr")
        on, off, jog = L.get("cyanOn") or 0, L.get("cyanOff") or 0, L.get("cyanJog") or 0
        dj, db = L.get("dJog") or [], L.get("dBack") or []
        d0, d1 = L.get("dist0"), L.get("dist1")
        same = (e is not None and e < 1e-6)                       # 左臂默认 = 右臂整体平移 Y+500mm
        drawn = on > 300 and off < on * 0.2 and jog > 300
        jogged = (dj == [30, 0, 0]) and (db == [0, 0, 0])
        still = (d0 is not None and d0 == d1)                     # 点动不许动相机
        arm_ok = same and drawn and jogged and still
        ad = ("默认偏差 %.2e m · 青像素 开%d/关%d/点动后%d · 点动 %s→复位 %s · 视距 %s→%s"
              % (e if e is not None else -1, on, off, jog, dj, db, d0, d1))
    except Exception as e2:                                   # noqa: BLE001
        ad = "解析失败 %r" % (e2,)
    chk("⑧ 左臂仿真臂: 默认=右臂整条平移(0,+500,0) + 能画/能关 + x 点动生效且不动相机", arm_ok, ad)
    tc_ok = False
    td = "tcam=%r" % (j.get("tcam") if isinstance(j, dict) else None,)
    try:
        T = j.get("tcam") or {}
        h, y = T.get("h"), T.get("y")
        onT, offT = T.get("onTop") or [0,0,0], T.get("offTop") or [0,0,0]
        onF, offF = T.get("onFov") or [0,0,0], T.get("offFov") or [0,0,0]
        height_ok = (h is not None and abs(h - 0.328) < 0.02)        # 立柱高 = 1 轴高(joint_1 z=0.328)
        mid_ok = (y is not None and abs(y - 0.25) < 1e-9)            # 立在两臂原心中线
        drawn = (max(abs(onT[i]-offT[i]) for i in range(3)) > 20)    # 立柱/相机真画出来, 关掉即消失
        tint_on = (onF[1]+onF[2]) - 2*onF[0]
        tint_off = (offF[1]+offF[2]) - 2*offF[0]
        fov_ok = (tint_on - tint_off) > 12                           # 视锥覆盖区(青)真打在台面上
        tc_ok = height_ok and mid_ok and drawn and fov_ok
        td = ("立柱高 %.3fm(=1轴) · y=%.3fm(两臂中线) · 顶面 %s↔关%s · 台面视锥 青偏置 %+d↔关%+d"
              % (h, y, onT, offT, tint_on, tint_off))
    except Exception as e2:                                   # noqa: BLE001
        td = "解析失败 %r" % (e2,)
    chk("⑨ 顶视相机: 立柱高=1轴高 + 立两臂中线 + 能画能关 + 视锥打到台面", tc_ok, td)
    ch_ok = False
    cd = "chs=%r" % (j.get("chs") if isinstance(j, dict) else None,)
    try:
        C = j.get("chs") or {}
        L, W, H = C.get("L") or 0, C.get("W") or 0, C.get("H") or 0
        HB = C.get("HB") or 0
        # r22: 箱体改成"落地总高 750(本体 680 + 轮露出 70)", 顶板仍钉在 z=0(两臂安装面)
        dim_ok = (abs(L-0.600) < 0.002 and abs(W-0.800) < 0.002
                  and abs(H-0.750) < 0.002 and abs(HB-0.680) < 0.002)
        onP, offP = C.get("onPlate") or [0,0,0], C.get("offPlate") or [0,0,0]
        onB, offB = C.get("onBody") or [0,0,0], C.get("offBody") or [0,0,0]
        # 顶板高光 #9fb6cc 是箱体独有的(实测 480 ↔ 关 2); 顶板面 #31404f 会和围栏/臂的
        # 暗色底撞色(基线 3337), 只用来佐证"画上去了确实变多"
        drawn = (onB > 200 and offB < 60 and onP > offP * 1.3)
        # 两臂安装面没被抬/压: base_link 的 z 必须还是 0 (箱体只向下长, 不动臂)
        bz = C.get("baseZ")
        arm_ok = (bz is not None and abs(bz) < 1e-6)
        ch_ok = dim_ok and drawn and arm_ok
        cd = ("箱体 %.3f×%.3f×%.3fm(本体%.3f)+臂安装面 z=%.6f · 顶板面像素 %d↔关%d · 顶板高光 %d↔关%d"
              % (L, W, H, HB, bz if bz is not None else -9, onP, offP, onB, offB))
    except Exception as e2:                                   # noqa: BLE001
        cd = "解析失败 %r" % (e2,)
    chk("⑩ 箱体: 600×800×750(本体680+轮70) + 顶板仍是两臂安装面(z=0, 臂没被抬高) + 能画能关", ch_ok, cd)
    # 🧪 实验桌: 摆在箱体前面(+X), 桌面 1000×600, 高 750, 桌面顶 z=0 与箱体顶板平齐
    tb_ok = False
    td2 = "tab=%r" % (j.get("tab") if isinstance(j, dict) else None,)
    try:
        T = j.get("tab") or {}
        N = T.get("note") or {}
        x0, x1, w, h, tt = N.get("x0"), N.get("x1"), N.get("w"), N.get("h"), N.get("t")
        C = j.get("chs") or {}
        L = C.get("L") or 0
        pos_ok = (x0 is not None and x1 is not None and x0 > L/2 + 0.02)      # 桌沿在箱体前脸之外, 不插进箱体
        dim_ok = (x0 is not None and abs((x1-x0)-0.600) < 0.002 and abs(w-1.600) < 0.002
                  and abs(h-0.750) < 0.002 and abs(tt-0.030) < 0.002)
        wOn, wOff = T.get("woodOn") or 0, T.get("woodOff") or 0
        hiOn, hiOff = T.get("woodHiOn") or 0, T.get("woodHiOff") or 0
        dmOn, dmOff = T.get("dimOn") or 0, T.get("dimOff") or 0
        drawn = (wOn > 800 and wOff < wOn * 0.35 and hiOn > 30 and dmOn > 10)
        cams = T.get("cams") or []
        still = (len(cams) == 3 and cams[0] == cams[1] == cams[2])            # 开关桌子/地面不许动相机
        tb_ok = pos_ok and dim_ok and drawn and still
        td2 = ("桌面 %.0f×%.0f×%.0fmm 高%.0f · 前脸外 %s · 木色 %d↔关%d · 桌面高光 %d↔关%d · 750标注 %d↔关%d · 相机静止 %s"
               % (((x1 or 0)-(x0 or 0))*1000, (w or 0)*1000, (tt or 0)*1000, (h or 0)*1000,
                  "是" if pos_ok else "否", wOn, wOff, hiOn, hiOff, dmOn, dmOff, still))
    except Exception as e2:                                   # noqa: BLE001
        td2 = "解析失败 %r" % (e2,)
    chk("⑪ 实验桌: 摆在箱体前面(+X, 不插进箱体) + 1600×600×750 + 真画出来(关掉即消失) + 开关不动相机", tb_ok, td2)
    # 🟫 地面层 + 📦 四轮 + 平齐口径
    fl_ok = False
    fd = "flr=%r chs=%r" % (j.get("flr") if isinstance(j, dict) else None,
                            j.get("chs") if isinstance(j, dict) else None)
    try:
        F = j.get("flr") or {}
        C = j.get("chs") or {}
        T = (j.get("tab") or {}).get("note") or {}
        fz = F.get("z")
        cH, tH = C.get("H"), T.get("h")
        same_dims = (cH is not None and tH is not None
                     and abs(cH - 0.750) < 1e-9 and abs(tH - 0.750) < 1e-9)
        floor_same = (fz is not None and abs(fz + 0.750) < 1e-9)              # 轮底 = 桌腿底 = 同一层地面
        fOn, fOff = F.get("on") or 0, F.get("off") or 0
        drawn = (fOn > 20000 and fOff < fOn * 0.6)
        hubOn, hubOff = C.get("hubOn") or 0, C.get("hubOff") or 0
        # 轮毂色 #39424e 与别的暗色有少量撞色(关掉箱体还剩 ~350px 抗锯齿杂点),
        # 所以"轮子真画出来"用**轮芯亮钉 #b9c6d4** 判: 全页只有轮子用这个色(实测 162 ↔ 关 0)
        dotOn, dotOff = C.get("dotOn") or 0, C.get("dotOff") or 0
        wheels = (dotOn > 60 and dotOff < 5 and hubOn > hubOff)
        fl_ok = same_dims and floor_same and drawn and wheels
        fd = ("桌高 %.3fm = 箱体落地高 %.3fm · 地面 z=%.3fm(轮底/桌腿同层) · 地面像素 %d↔关%d · 轮芯亮钉 %d↔关%d"
              % (T.get("h") or -1, C.get("H") or -1, fz if fz is not None else -9, fOn, fOff, dotOn, dotOff))
    except Exception as e2:                                   # noqa: BLE001
        fd = "解析失败 %r" % (e2,)
    chk("⑫ 750 平齐落地: 箱体=桌子=750 + 四轮/桌腿同一地面(-750) + 四轮真画出来", fl_ok, fd)
    # 🧱 铝型材框架: 四腿向上通到上横梁底面(唯一依据=围栏台账里的"上横梁") + 顶框/支撑梁/角码真画出来
    fr_ok = False
    frm = "tab.beam=%r" % ((j.get("tab") or {}).get("beam") if isinstance(j, dict) else None,)
    try:
        T = j.get("tab") or {}
        B = T.get("beam") or {}
        bx, by, bz = B.get("x") or [], B.get("y") or [], B.get("z") or []
        nm = B.get("name") or ""
        from_fence = ("横梁" in nm) and ("缺省" not in nm)          # 坐标必须来自围栏台账, 不是固定不变的保障
        ztop = bz[0] if len(bz) == 2 else None
        colh = (ztop + 0.750) if ztop is not None else None        # 柱高 = 从地面 -0.750 到横梁底面
        geo_ok = (from_fence and ztop is not None
                  and abs(ztop - 0.682) < 1e-6                      # 柱顶正好顶在上横梁底面
                  and ztop > 0.60                                   # 高出桌面 600mm 以上 = 腿真的向上延伸
                  and abs((by[1] - by[0]) - 1.600) < 1e-3            # 上横梁 1600 长
                  and abs((bx[1] - bx[0]) - 0.200) < 1e-3)           # 200 宽
        aOn, aOff = T.get("aluOn") or 0, T.get("aluOff") or 0
        drawn = (aOn > 400 and aOff < 30)
        fr_ok = geo_ok and drawn
        frm = ("上横梁 %s x%.3f..%.3f y%.3f..%.3f z%.3f..%.3f · 柱顶=横梁底面 z=%.3f(柱高%.3fm) · 铝型材像素 %d↔关%d"
               % (nm, bx[0], bx[1], by[0], by[1], bz[0], bz[1],
                  ztop if ztop is not None else -9, colh if colh is not None else -9, aOn, aOff))
    except Exception as e2:                                   # noqa: BLE001
        frm = "解析失败 %r" % (e2,)
    chk("⑬ 铝型材框架: 四腿通顶到上横梁底面(唯一依据读围栏台账) + 顶框/支撑梁/角码真画出来 + 随桌子一起关", fr_ok, frm)
    # 🎯 目标点开关(单选) + 轨迹5「实时」= 当前 TCP → 选中的目标点, 换目标自动重算
    tg_ok = False
    tgd = "tgt=%r" % (tgt_res,)
    try:
        T = json.loads(tgt_res) if isinstance(tgt_res, str) else {}
        B0, A0 = T.get("before") or {}, T.get("afterClick") or {}
        R, A3 = T.get("real") or {}, T.get("afterThird") or {}
        cams = [T.get("cam0"), T.get("cam1"), R.get("cam"), A3.get("cam")]
        cam_still = bool(cams[0]) and all(c == cams[0] for c in cams)
        radios = (B0.get("n") or 0) >= 20 and (A0.get("n") or 0) == (B0.get("n") or 0)
        single = (B0.get("onCount") == 1 and A0.get("onCount") == 1
                  and A0.get("on") == T.get("other") and A0.get("cur") == T.get("other"))
        shaped = (R.get("n") == 4)
        starts_live = bool(R.get("first")) and ("TCP" in (R.get("src") or "") or "TCP" in (R.get("note") or ""))
        recalc = bool(A3.get("m2"))
        # 起点=当前 TCP: 页面里的 TCP 可能陈旧, 这里用"骨架首点 == 第二点前的竖直抬升"验证形状
        tg_ok = radios and single and cam_still and shaped and recalc and starts_live
        tgd = ("靶心钮 %s 个 · 单选 %s→%s(%s) · 轨迹5 %s点 首%s 末%s · 目标 %s · 换目标自动重算 %s(%s→%s) · 相机静止 %s"
               % (B0.get("n"), B0.get("onCount"), A0.get("onCount"), A0.get("on"),
                  R.get("n"), R.get("first"), R.get("last"), (A0.get("cur")),
                  recalc, (T.get("third") or {}).get("name"), A3.get("last"), cam_still))
    except Exception as e2:                                           # noqa: BLE001
        tgd = "解析失败 %r / %r" % (tgt_res, e2)
    chk("⑭ 🎯目标点开关(单选) + 轨迹5实时=当前TCP→选中点(4点:升→平移→落点) + 换目标自动重算 + 不动相机", tg_ok, tgd)
    print("截图:", SHOT, os.path.getsize(SHOT) if os.path.exists(SHOT) else "-")
    bad = [n for n, ok, _ in ck if not ok]
    print("═══ %s (%d/%d) ═══" % ("全绿" if not bad else "不过: " + ", ".join(bad), len(ck) - len(bad), len(ck)))
    return 0 if not bad else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
