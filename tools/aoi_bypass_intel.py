#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_bypass_intel.py — 550C 光学质量检测 · 旁路 AOI (Intel 侧)

老倪 2026-10-22: 「在 intel 的 550C 启动光学质量检测的旁路 AOI 检测功能」

═══ 旁路铁律 (写在代码里, 不靠自觉) ═══
① **零写入**: 只发 GET。绝不调 /capture_detect(会真拍台面)、不 POST 任何东西、
   不抢相机独占、不改产线程序。工控机上的 10082/10083 一行不动。
② **不猜数**: 没采到 ⇒ 显 null / "未测"; 绝不假 0。缺真源就写 gap 原因。
③ **旁路不是检测**: 工控机自带 YOLO 才是判据源。本服务只做
   「拉结果 → 存历史 → 算统计 → 报异常」, 不自己下判决。

═══ 被监控的两个服务 (工控机 192.168.23.23) ═══
  10082 金手指  OPT-CC1-GG50        /last_result /picture /storage
  10083 表面    OPT-CC1-C050-GG3-00 /last_result /picture /storage /exposure

═══ 本服务端点 (给 4060 / 网页看) ═══
  GET /                单页面板 (实时状态 + 缺陷趋势 + 旁路健康)
  GET /aoi/status      两路当前状态 + 旁路自身健康
  GET /aoi/recent?n=50 最近 N 次检测记录
  GET /aoi/stats       累计统计 (次数/缺陷率/耗时分位/可用率)
  GET /aoi/health      旁路自身是否真在工作 (拉取成功率/最近成功时间)

用法:
  python3 aoi_bypass_intel.py --port 8802 --interval 5
  python3 aoi_bypass_intel.py --once        # 单次拉取, 打印后退出 (自检)
"""
from __future__ import annotations

import argparse
import json
import os
import time
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── 被监控目标 (工控机, 只读) ──
TARGETS = {
    "gold": {"name": "金手指", "base": "http://192.168.23.23:10082",
             "cam": "OPT-CC1-GG50", "detect_type": "gf"},
    "surface": {"name": "表面", "base": "http://192.168.23.23:10083",
                "cam": "OPT-CC1-C050-GG3-00", "detect_type": "housing"},
}
OUT_DIR = os.environ.get("ZMAX_AOI_BYPASS_DIR", os.path.expanduser("~/aoi_bypass"))
os.makedirs(OUT_DIR, exist_ok=True)

STATE = {
    "started": time.time(),
    "interval": 5.0,
    "running": False,
    "last_tick": 0.0,
    "ticks": 0,
    "cur": {},          # 每路最新快照
    "hist": {k: deque(maxlen=500) for k in TARGETS},
    "health": {k: {"ok": 0, "fail": 0, "last_ok": 0.0, "last_err": ""} for k in TARGETS},
}
LOCK = threading.Lock()


def _get(url, timeout=6.0):
    """只读 GET —— 全网关唯一出口。绝不允许 POST/PUT/DELETE 从这里漏出去。"""
    req = Request(url, method="GET", headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8", "ignore"))


def pull_one(key):
    """拉一路的 /last_result, 归一成统一记录。失败要如实记, 不填假值。"""
    t = TARGETS[key]
    base = t["base"]
    rec = {
        "ts": time.time(),
        "at": time.strftime("%F %T"),
        "key": key,
        "name": t["name"],
        "cam": t["cam"],
        "reachable": False,
        # 下面这些拿不到就是 None, 绝不写成 0
        "count": None, "verdict": None, "ms": None,
        "judge": None, "origin": None, "defects": None,
        "detect_type": None, "t_dev": None, "gap": "",
    }
    try:
        j = _get(base + "/last_result")
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        rec["gap"] = "拉取失败: %s" % type(e).__name__
        return rec
    rec["reachable"] = True
    rec["count"] = j.get("count")
    rec["verdict"] = j.get("verdict") or j.get("verdict_topview")
    rec["ms"] = j.get("ms")
    rec["judge"] = j.get("judge")
    rec["origin"] = j.get("origin")
    rec["defects"] = j.get("defects")
    rec["detect_type"] = j.get("detect_type")
    # 设备侧时间戳 vs 本机时间 → 帧龄 (老倪要求: 实时数据必须标拍照时间/帧龄)
    td = j.get("t")
    if isinstance(td, (int, float)) and td > 0:
        rec["t_dev"] = td
        rec["frame_age_s"] = round(time.time() - td, 1)
    else:
        rec["frame_age_s"] = None
        rec["gap"] = "设备未返回时间戳, 帧龄不可得"
    # 10083 特有的判据闸信息
    if j.get("judge_ok") is False:
        rec["gap"] = (rec["gap"] + " | " if rec["gap"] else "") + "判据图不合格: %s" % j.get("judge_why", "")
    return rec


def tick():
    """一轮: 并发拉两路 → 存历史 → 更新健康"""
    out = {}
    errs = {}
    threads = []

    def work(k):
        try:
            out[k] = pull_one(k)
        except Exception as e:      # 任何异常都要落成记录, 不让线程静默死
            errs[k] = "%s: %s" % (type(e).__name__, e)

    for k in TARGETS:
        th = threading.Thread(target=work, args=(k,), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(timeout=12)

    with LOCK:
        for k in TARGETS:
            rec = out.get(k)
            if rec is None:
                rec = {"ts": time.time(), "at": time.strftime("%F %T"), "key": k,
                       "name": TARGETS[k]["name"], "cam": TARGETS[k]["cam"],
                       "reachable": False, "count": None, "verdict": None, "ms": None,
                       "gap": "本轮异常: %s" % errs.get(k, "超时")}
            STATE["cur"][k] = rec
            STATE["hist"][k].append(rec)
            h = STATE["health"][k]
            if rec["reachable"]:
                h["ok"] += 1
                h["last_ok"] = time.time()
                h["last_err"] = ""
            else:
                h["fail"] += 1
                h["last_err"] = rec.get("gap", "")
        STATE["ticks"] += 1
        STATE["last_tick"] = time.time()
    return STATE["cur"]


def stats():
    """累计统计。缺陷率只在有 count 的样本上算 (没采到的不进分母)。"""
    with LOCK:
        res = {"since": time.strftime("%F %T", time.localtime(STATE["started"])),
               "uptime_s": round(time.time() - STATE["started"], 1),
               "ticks": STATE["ticks"], "interval": STATE["interval"], "channels": {}}
        for k in TARGETS:
            recs = [r for r in STATE["hist"][k] if r.get("reachable")]
            n = len(recs)
            counts = [r["count"] for r in recs if isinstance(r.get("count"), int)]
            mss = [r["ms"] for r in recs if isinstance(r.get("ms"), (int, float))]
            verdicts = [r["verdict"] for r in recs if r.get("verdict")]
            h = STATE["health"][k]
            tot = h["ok"] + h["fail"]
            d = {
                "name": TARGETS[k]["name"], "cam": TARGETS[k]["cam"],
                "samples": n,
                "samples_with_count": len(counts),
                "defect_frames": sum(1 for c in counts if c > 0),
                "defect_rate": (round(sum(1 for c in counts if c > 0) / len(counts), 4)
                                if counts else None),
                "count_sum": sum(counts) if counts else None,
                "ms_p50": (round(sorted(mss)[len(mss) // 2], 1) if mss else None),
                "ms_max": (round(max(mss), 1) if mss else None),
                "verdict_ok": sum(1 for v in verdicts if str(v).upper() == "OK"),
                "verdict_ng": sum(1 for v in verdicts if str(v).upper() != "OK"),
                "reach_rate": round(h["ok"] / tot, 4) if tot else None,
                "last_ok": time.strftime("%F %T", time.localtime(h["last_ok"])) if h["last_ok"] else None,
                "last_err": h["last_err"],
            }
            res["channels"][k] = d
        return res


PANEL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>550C 旁路 AOI</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0c10;color:#dfe3ea;font:13px/1.6 -apple-system,"Segoe UI","Noto Sans CJK SC",sans-serif}
header{padding:14px 18px;border-bottom:1px solid #1b2028;display:flex;gap:20px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;font-weight:600}
.tag{padding:2px 9px;border-radius:10px;font-size:11px;background:#16202c;color:#63b3ed}
.warn{background:#2d1b1e;color:#f87171}
.wrap{padding:16px 18px;display:grid;gap:14px}
.card{border:1px solid #1b2028;border-radius:8px;padding:14px 16px;background:#0d1117}
.card h2{font-size:13px;font-weight:600;color:#9aa4b2;margin-bottom:10px;letter-spacing:.04em}
.row{display:flex;gap:26px;flex-wrap:wrap;font-size:12px}
.kv{color:#6b7683}.kv b{color:#dfe3ea;font-weight:600;font-variant-numeric:tabular-nums}
.gap{color:#f0a050;font-size:11px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #161b22}
th{color:#5a6270;font-weight:500;font-size:11px}
td{font-variant-numeric:tabular-nums}
</style></head><body>
<header>
  <h1>550C 光学质量检测 · 旁路 AOI</h1>
  <span class="tag" id="mode">Intel 侧 · 只读</span>
  <span class="kv" id="up"></span>
  <span class="kv" id="tick"></span>
</header>
<div class="wrap">
  <div id="cards"></div>
  <div class="card"><h2>最近检测</h2><div id="recent"></div></div>
</div>
<script>
function ms(v){return v==null?'未测':v}
async function refresh(){
  try{
    const s = await (await fetch('/aoi/status',{cache:'no-store'})).json();
    const st = await (await fetch('/aoi/stats',{cache:'no-store'})).json();
    document.getElementById('up').textContent = '运行 ' + Math.round(st.uptime_s) + 's · ' + st.ticks + ' 轮';
    document.getElementById('tick').textContent = '间隔 ' + st.interval + 's';
    let h = '';
    for(const [k,v] of Object.entries(s.channels)){
      const c = st.channels[k] || {};
      const live = v.reachable;
      h += '<div class="card"><h2>' + v.name + ' · ' + v.cam +
           ' <span class="tag' + (live?'':' warn') + '">' + (live?'在线':'不可达') + '</span></h2>' +
           '<div class="row">' +
           '<span class="kv">缺陷数 <b>' + ms(v.count) + '</b></span>' +
           '<span class="kv">判决 <b>' + (v.verdict||'未测') + '</b></span>' +
           '<span class="kv">耗时 <b>' + ms(v.ms) + 'ms</b></span>' +
           '<span class="kv">帧龄 <b>' + ms(v.frame_age_s) + 's</b></span>' +
           '<span class="kv">累计 <b>' + ms(c.count_sum) + '</b></span>' +
           '<span class="kv">缺陷率 <b>' + (c.defect_rate==null?'—':(c.defect_rate*100).toFixed(1)+'%') + '</b></span>' +
           '<span class="kv">拉取成功 <b>' + (c.reach_rate==null?'—':(c.reach_rate*100).toFixed(1)+'%') + '</b></span>' +
           '</div>' +
           (v.gap ? '<div class="gap">⚠ ' + v.gap + '</div>' : '') + '</div>';
    }
    document.getElementById('cards').innerHTML = h;
    const r = await (await fetch('/aoi/recent?n=12',{cache:'no-store'})).json();
    let t = '<table><tr><th>时间</th><th>通道</th><th>缺陷</th><th>判决</th><th>耗时</th></tr>';
    for(const x of r.records){
      t += '<tr><td>' + x.at + '</td><td>' + (x.name||'') + '</td><td>' + ms(x.count) +
           '</td><td>' + (x.verdict||'—') + '</td><td>' + ms(x.ms) + 'ms</td></tr>';
    }
    document.getElementById('recent').innerHTML = t + '</table>';
  }catch(e){
    document.getElementById('mode').className = 'tag warn';
    document.getElementById('mode').textContent = '服务无响应';
  }
}
refresh(); setInterval(refresh, 3000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _s(self, code, body, ct="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p in ("/", "/index.html"):
            return self._s(200, PANEL, "text/html; charset=utf-8")
        if p == "/aoi/status":
            with LOCK:
                cur = dict(STATE["cur"])
                running = STATE["running"]
                last = STATE["last_tick"]
            return self._s(200, json.dumps({
                "mode": "550C 旁路 AOI (Intel 侧, 只读)",
                "running": running,
                "last_tick": last,
                "tick_age_s": round(time.time() - last, 1) if last else None,
                "channels": cur,
                "targets": {k: v["base"] for k, v in TARGETS.items()},
            }, ensure_ascii=False))
        if p == "/aoi/stats":
            return self._s(200, json.dumps(stats(), ensure_ascii=False))
        if p == "/aoi/recent":
            n = int((q.get("n") or ["50"])[0])
            with LOCK:
                recs = []
                for k in TARGETS:
                    recs.extend(list(STATE["hist"][k]))
            recs.sort(key=lambda r: r.get("ts", 0), reverse=True)
            return self._s(200, json.dumps({"n": len(recs[:n]), "records": recs[:n]},
                                           ensure_ascii=False))
        if p == "/aoi/health":
            with LOCK:
                hh = {k: dict(v) for k, v in STATE["health"].items()}
                alive = (time.time() - STATE["last_tick"]) < max(STATE["interval"] * 3, 20) if STATE["last_tick"] else False
            return self._s(200, json.dumps({
                "bypass_alive": alive,
                "ticks": STATE["ticks"],
                "interval": STATE["interval"],
                "channels": hh,
            }, ensure_ascii=False))
        return self._s(404, json.dumps({"error": "no route", "path": p}))


def loop(interval):
    STATE["interval"] = float(interval)
    STATE["running"] = True
    while True:
        t0 = time.time()
        try:
            tick()
        except Exception as e:
            with LOCK:
                STATE["last_tick"] = time.time()
                for k in TARGETS:
                    STATE["health"][k]["fail"] += 1
                    STATE["health"][k]["last_err"] = "loop 异常: %s" % e
        time.sleep(max(0.2, STATE["interval"] - (time.time() - t0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8802)
    ap.add_argument("--interval", type=float, default=5.0, help="拉取间隔秒")
    ap.add_argument("--once", action="store_true", help="单次拉取打印后退出")
    a = ap.parse_args()

    if a.once:
        cur = tick()
        print(json.dumps(cur, ensure_ascii=False, indent=1))
        return

    threading.Thread(target=loop, args=(a.interval,), daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    print("550C 旁路 AOI: http://0.0.0.0:%d/  (只读监控 %s)" %
          (a.port, ", ".join(v["base"] for v in TARGETS.values())))
    srv.serve_forever()


if __name__ == "__main__":
    main()
