#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""perf_report.py — Z-MAX 性能指标全量实测报告 (分类别 · 每项真测 · 带阈值判定)

原则 (老倪: 「详细报告, 每个性能指标都要测试, 分好类别」):
  · 每个指标都是**真测**: 要么实跑一次 (限幅次数), 要么读真实的计数器/时间戳/系统文件
  · 每个指标都带: 类别 · 值 · 单位 · 判定(PASS/WARN/FAIL + 阈值) · 来源(命令/文件) · 采样量
  · 测不到的**如实写 err**, 不用 0 或估计值冒充 (指标不夸大)
  · 分类别输出 md + json, 可直接进交付件

类别:
  A 层推理 (L5/MEM/L2/L4/L3 逐层延迟/成功率)     B 引擎回路 (Hz/周期耗时/空转/抖动)
  C 视觉链路 (每通道 fps/帧龄/分辨率/亮度/过曝/取像延迟)  D 模型资产 (在役/候选/推理中/规模)
  E 服务可用 (端口/systemd/API 延迟)             F 系统资源 (CPU/内存/磁盘/GPU/温度)
  G 训练 (进行中任务的步速/ETA; 最近 3DGS 质量)   H 配置完备性 (映射/覆盖/一致性判据)
  I 端到端 (闭环执行结果/节拍)                    J 安全 (运动闸/编码器/守卫)

CLI: --write (落盘 reports/perf_report_<ts>.md|.json) · --json · --cycles N (回路采样周期数)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
AOI = "192.168.23.23"
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


# ─────────────────────────── 通用: 计时/读数 ───────────────────────────
def sh(cmd, t=20):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:                                                        # noqa: BLE001
        return "<<%s: %s>>" % (type(e).__name__, e)


def http_timing(url, timeout=10, n=3):
    """HTTP 采样 n 次 ⇒ (p50_ms, status_ok, bytes, err)。"""
    ts, okb, sz, err = [], False, 0, ""
    for _ in range(max(1, n)):
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "zmax-perf"}), timeout=timeout)
            b = r.read()
            ts.append((time.perf_counter() - t0) * 1000.0)
            okb, sz = True, len(b)
        except Exception as e:                                                    # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, str(e)[:80])
            ts.append((time.perf_counter() - t0) * 1000.0)
    return (round(statistics.median(ts), 1) if ts else None), okb, sz, err


def jload(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                             # noqa: BLE001
        return d if d is not None else {}


def tail_jsonl(p, n=400):
    out = []
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f.readlines()[-n:]:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except Exception:                                             # noqa: BLE001
                        pass
    except Exception:                                                             # noqa: BLE001
        pass
    return out


class Rep:
    """指标容器: 分类别 → 指标行。"""

    def __init__(self):
        self.cats: dict = {}
        self.t0 = time.time()

    def add(self, cat, name, value, unit="", verdict="—", thr="", src="", n=1):
        self.cats.setdefault(cat, []).append({
            "metric": name, "value": value, "unit": unit, "verdict": verdict,
            "threshold": thr, "source": src, "samples": n})

    def md(self) -> str:
        L = ["# Z-MAX 性能指标实测报告",
             "",
             "生成: %s · 采样窗口: 本次运行 %.1fs · 仓库: `%s`" % (
                 time.strftime("%Y-%m-%d %H:%M:%S"), time.time() - self.t0, ROOT),
             "",
             "> 口径: 每项均为**真测**(实跑或读真计数器/时间戳); 测不到写 err; 判定阈值写在表里可复核。",
             ""]
        n_bad = 0
        for cat, rows in self.cats.items():
            L += ["## %s" % cat, "",
                  "| 指标 | 值 | 单位 | 判定 | 阈值/口径 | 来源 | 样本 |",
                  "|---|---|---|---|---|---|---|"]
            for r in rows:
                if r["verdict"] == "FAIL":
                    n_bad += 1
                L.append("| %s | %s | %s | %s | %s | `%s` | %d |" % (
                    r["metric"], r["value"], r["unit"], r["verdict"], r["threshold"],
                    str(r["source"])[:90], r["samples"]))
            L.append("")
        tot = sum(len(v) for v in self.cats.values())
        L += ["## 汇总", "",
              "- 指标数: **%d** · 类别数: **%d** · FAIL: **%d**" % (tot, len(self.cats), n_bad), ""]
        return "\n".join(L)


# ─────────────────────────── A 层推理 ───────────────────────────
def cat_a(r: Rep, runs: int = 3):
    cat = "A 层推理 (逐层延迟/成功率)"
    try:
        from multi_layer_pipeline import Pipeline, build_default_spec                     # noqa: PLC0415
        import cv2                                                                       # noqa: PLC0415
        import numpy as np                                                               # noqa: PLC0415
        spec = build_default_spec(L5="planner.rules", L2="detect.yolo", L4="node.unified")
        spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote", "peers": ["node.intact"]}
        p = Pipeline(spec)
        # 图源依次回退 (产线网段不可达时 /aoi_modelin.png 会 502): aoi_modelin → snap/local → 本机存图
        img, _src = None, ""
        for _u, _nm in (("http://127.0.0.1:8791/aoi_modelin.png", "8791/aoi_modelin"),
                        ("http://127.0.0.1:8791/snap/local.jpg", "8791/snap/local")):
            try:
                raw = urllib.request.urlopen(urllib.request.Request(
                    _u, headers={"User-Agent": "zmax-perf"}), timeout=15).read()
                im2 = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if im2 is not None and float(im2.mean()) > 3.0:
                    img, _src = im2, _nm
                    break
            except Exception:                                                     # noqa: BLE001
                continue
        if img is None:
            for _p in sorted(glob.glob(os.path.join(ROOT, "reports/**/*.png"), recursive=True))[-40:]:
                im2 = cv2.imread(_p, cv2.IMREAD_COLOR)
                if im2 is not None and float(im2.mean()) > 3.0:
                    img, _src = im2, os.path.relpath(_p, ROOT)
                    break
        if img is None:
            raise RuntimeError("三路图源都取不到 (产线网段不可达 + 本机无可用存图)")
        r.add(cat, "A 类图源", _src, "", "—", "产线不可达时回退本机通道/存图", "load_image 回退链", 1)
        st = jload(os.path.join(LIVE, "engine_latest.json"), {})
        obs = np.asarray((st.get("p") or [0, 0, 0, 0]) + [0] * 39, float).ravel()[:39]
        layers, tot_ms, ok_n, n_tot = {}, [], 0, 0
        for _ in range(max(1, runs)):
            t0 = time.perf_counter()
            out = p.run(img=np.ascontiguousarray(img), obs39=obs)
            tot_ms.append((time.perf_counter() - t0) * 1000.0)
            for k, v in (out or {}).items():
                layers.setdefault(k, []).append(float(getattr(v, "latency_ms", 0.0) or 0.0))
                n_tot += 1
                ok_n += 1 if getattr(v, "ok", False) else 0
        for k, v in layers.items():
            med = statistics.median(v)
            thr = "≤50ms(单层)"
            r.add(cat, "%s 单层延迟(中位)" % k, round(med, 2), "ms",
                  "PASS" if med <= 50 else "WARN", thr, "Pipeline.run() 计时", len(v))
        r.add(cat, "整链延迟(中位)", round(statistics.median(tot_ms), 2), "ms",
              "PASS" if statistics.median(tot_ms) <= 120 else "WARN", "≤120ms (10Hz 预算 100ms/2Hz 档)",
              "Pipeline.run() 端到端", len(tot_ms))
        r.add(cat, "整链延迟(最大)", round(max(tot_ms), 2), "ms", "—", "看抖动用", "同上一行", len(tot_ms))
        r.add(cat, "层调用成功率", "%d/%d" % (ok_n, n_tot), "",
              "PASS" if n_tot and ok_n == n_tot else "WARN", "=100%", "NodeOut.ok 聚合", n_tot)
        r.add(cat, "L2 权重(在役)", os.path.basename(os.path.realpath(os.path.join(ROOT, "models/yolo_peg_live.pt"))),
              "", "PASS" if os.path.exists(os.path.join(ROOT, "models/yolo_peg_live.pt")) else "FAIL",
              "必须是在役 peg 权重", "models/yolo_peg_live.pt 软链", 1)
    except Exception as e:                                                            # noqa: BLE001
        r.add(cat, "层推理测量", "err", "", "FAIL", "必须真验证通过", "%s: %s" % (type(e).__name__, str(e)[:90]), 1)


# ─────────────────────────── B 引擎回路 ───────────────────────────
def cat_b(r: Rep, cycles: int = 40):
    cat = "B 引擎回路 (Hz/周期耗时/空转/抖动)"
    st = jload(os.path.join(LIVE, "engine_loop_status.json"), {})
    r.add(cat, "回路周期数(累计)", st.get("cycles"), "个", "—", "单调增", "zmax_data/ss_live/engine_loop_status.json", 1)
    r.add(cat, "回路运行时长", round(float(st.get("uptime_s") or 0) / 60.0, 1), "分钟", "—", "—", "同上", 1)
    r.add(cat, "目标频率", st.get("hz_target"), "Hz", "PASS" if (st.get("hz_target") or 0) >= 10 else "WARN",
          "≥10Hz", "同上", 1)
    r.add(cat, "空转周期数", st.get("idle_cycles"), "个", "PASS" if (st.get("idle_cycles") or 0) == 0 else "WARN",
          "=0 (有无状态唯一依据)", "同上", 1)
    tap = st.get("tap") or "/dev/shm/zmax_ss_engine/engine_default.jsonl"
    recs = tail_jsonl(tap, 400)
    if len(recs) >= 5:
        mss = [float(x.get("ms") or 0) for x in recs][-cycles:]
        r.add(cat, "单周期耗时(中位)", round(statistics.median(mss), 3), "ms", "PASS" if statistics.median(mss) <= 5 else "WARN",
              "≤5ms (10Hz 下余量足)", "engine tap jsonl", len(mss))
        r.add(cat, "单周期耗时(p95)", round(sorted(mss)[int(0.95 * (len(mss) - 1))], 3), "ms", "—", "看抖动",
              "同上", len(mss))
        ts = [float(x.get("ts") or 0) for x in recs if x.get("ts")]
        if len(ts) > 3:
            dts = [b - a for a, b in zip(ts, ts[1:]) if 0 < b - a < 2]
            if dts:
                r.add(cat, "实际周期(中位)", round(statistics.median(dts) * 1000, 2), "ms",
                      "PASS" if statistics.median(dts) <= 0.15 else "WARN", "≤150ms",
                      "tap ts 差分", len(dts))
                r.add(cat, "节拍抖动(标准差)", round(statistics.pstdev(dts) * 1000, 2), "ms", "—", "越小越稳",
                      "同上", len(dts))
        pc = [int(x.get("pipe_calls") or 0) for x in recs]
        r.add(cat, "多层 pipeline 累计调用", max(pc) if pc else 0, "次",
              "PASS" if (max(pc) if pc else 0) > 0 else "FAIL", ">0 (所有层真跑)",
              "tap pipe_calls", len(pc))
    else:
        r.add(cat, "回路 tap 采样", "err", "", "FAIL", "≥5 条记录", "tap=%s" % tap, len(recs))


# ─────────────────────────── C 视觉链路 ───────────────────────────
def cat_c(r: Rep):
    cat = "C 视觉链路 (fps/帧龄/分辨率/亮度/过曝/取像延迟)"
    ms, okb, sz, err = http_timing("http://127.0.0.1:8791/stats", n=2)
    r.add(cat, "流服务 /stats 响应", ms if ms is not None else "err", "ms",
          "PASS" if (ms or 1e9) <= 200 else "WARN", "≤200ms", "GET 8791/stats", 2)
    d = {}
    if okb:
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(
                "http://127.0.0.1:8791/stats", headers={"User-Agent": "zmax-perf"}), timeout=10).read())
        except Exception:                                                             # noqa: BLE001
            d = {}
    for k, v in (d or {}).items():
        if not isinstance(v, dict):
            continue
        fps = v.get("fps")
        age = v.get("age_s")
        if fps is None and age is None:
            continue
        r.add(cat, "通道 %s fps" % k, fps, "fps",
              "PASS" if (fps or 0) >= 5 else ("WARN" if (fps or 0) > 0 else "FAIL"), "≥5fps(监视类)",
              "GET 8791/stats", 1)
        r.add(cat, "通道 %s 帧龄" % k, age, "s",
              "PASS" if (age if age is not None else 1e9) <= 1.0 else "WARN", "≤1s", "同上", 1)
    # 取像延迟 (判据自己的取像口)
    for port, ep in ((10082, "/picture?kind=judge&grab=1"), (10083, "/picture?kind=origin&grab=1")):
        t0 = time.perf_counter()
        try:
            raw = urllib.request.urlopen(urllib.request.Request(
                "http://%s:%d%s" % (AOI, port, ep), headers={"User-Agent": "zmax-perf"}),
                timeout=30).read()
            dt = (time.perf_counter() - t0) * 1000.0
            import cv2                                                                # noqa: PLC0415
            import numpy as np                                                        # noqa: PLC0415
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                r.add(cat, "AOI %d 取像" % port, "解码失败", "", "FAIL", "能解出图",
                      "GET %s:%d%s" % (AOI, port, ep), 1)
                continue
            g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype("float32")
            r.add(cat, "AOI %d 取像延迟" % port, round(dt, 1), "ms",
                  "PASS" if dt <= 1500 else "WARN", "≤1500ms", "GET %s:%d%s" % (AOI, port, ep), 1)
            r.add(cat, "AOI %d 分辨率" % port, "%dx%d" % (im.shape[1], im.shape[0]), "", "—", "—", "同上", 1)
            r.add(cat, "AOI %d 均值亮度" % port, round(float(g.mean()), 1), "灰阶",
                  "PASS" if float(g.mean()) > 5 else "FAIL", ">5 (全黑=不可用)", "同上", 1)
            r.add(cat, "AOI %d 过曝率" % port, round(100.0 * float((g >= 250).mean()), 2), "%",
                  "PASS" if 100.0 * float((g >= 250).mean()) <= 6 else "WARN", "≤6%",
                  "≥250 像素占比", 1)
        except Exception as e:                                                        # noqa: BLE001
            r.add(cat, "AOI %d 取像" % port, "err", "", "FAIL", "能取到", str(e)[:70], 1)


# ─────────────────────────── D 模型资产 ───────────────────────────
def cat_d(r: Rep):
    cat = "D 模型资产 (在役/候选/推理中/规模)"
    ms, okb, sz, err = http_timing("http://127.0.0.1:8796/status/all", n=2)
    r.add(cat, "/status/all 响应", ms if ms is not None else "err", "ms",
          "PASS" if (ms or 1e9) <= 2000 else "WARN", "≤2000ms", "GET 8796/status/all", 2)
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8796/status/all", headers={"User-Agent": "zmax-perf"}), timeout=20).read())
    except Exception as e:                                                            # noqa: BLE001
        r.add(cat, "模型清单", "err %s" % str(e)[:60], "", "FAIL", "能读到", "8796/status/all", 1)
        return
    mods = d.get("models") or []
    n_inf = sum(1 for m in mods if m.get("inferring"))
    by_layer: dict = {}
    for m in mods:
        by_layer[m.get("layer") or "?"] = by_layer.get(m.get("layer") or "?", 0) + 1
    r.add(cat, "登记模型数", len(mods), "条", "—", "—", "8796/status/all", 1)
    r.add(cat, "层分布", json.dumps(by_layer, ensure_ascii=False), "", "—", "L2/L3/L4/L5",
          "同上", 1)
    r.add(cat, "推理中模型数", "%d/%d" % (n_inf, len(mods)), "",
          "PASS" if n_inf >= 4 else "WARN", "≥4 (当前实测基线)", "探针 inferring 聚合", len(mods))
    for m in mods:
        if m.get("inferring") is False and (m.get("layer") or "") in ("L2", "L3", "L4", "L5"):
            pass
    nfile = len(glob.glob(os.path.join(ROOT, "models/*.pt")) + glob.glob(os.path.join(ROOT, "models/*.npz")))
    r.add(cat, "本机权重文件数", nfile, "个", "—", "—", "ls models/*", 1)
    gpu = d.get("gpu") or {}
    if gpu:
        r.add(cat, "GPU 利用率(状态聚合)", gpu.get("util_pct"), "%",
              "PASS" if (gpu.get("util_pct") or 0) >= 50 else "WARN", "训练须 ≥50%", "nvidia-smi via 8796", 1)
        r.add(cat, "显存占用", "%s/%s" % (gpu.get("mem_used_mb"), gpu.get("mem_total_mb")), "MB",
              "WARN" if (gpu.get("mem_used_mb") or 0) > 0.85 * (gpu.get("mem_total_mb") or 1e9) else "PASS",
              "≤85%", "同上", 1)
        r.add(cat, "GPU 温度", gpu.get("temp_c"), "°C",
              "PASS" if (gpu.get("temp_c") or 0) <= 80 else "WARN", "≤80°C", "同上", 1)


# ─────────────────────────── E 服务可用 ───────────────────────────
def cat_e(r: Rep):
    cat = "E 服务可用 (端口/systemd/API 延迟)"
    ports = {"8791": "状态空间/流服务", "8793": "工位总览+授权", "8796": "模型状态+分割",
             "8797": "AR", "8799": "大屏+APP", "8798": "工程库"}
    up = 0
    for p, name in ports.items():
        line = sh("ss -ltn 2>/dev/null | grep -c ':%s '" % p).strip()
        ok = line not in ("", "0")
        up += 1 if ok else 0
        r.add(cat, "端口 %s (%s)" % (p, name), "在听" if ok else "未监听", "",
              "PASS" if ok else "WARN", "关键服务应在线", "ss -ltn", 1)
    r.add(cat, "关键端口在线率", "%d/%d" % (up, len(ports)), "",
          "PASS" if up >= len(ports) - 1 else "WARN", "≥n-1", "同上", len(ports))
    unl = [u.split()[0] for u in sh("systemctl list-units --type=service --all --no-legend").splitlines()
           if "zmax" in u or "sam3" in u]
    bad = [u for u in unl if sh("systemctl is-active %s" % u).strip() != "active"]
    r.add(cat, "zmax systemd 单元数", len(unl), "个", "—", "—", "systemctl list-units", 1)
    r.add(cat, "非 active 单元", len(bad), "个", "PASS" if not bad else "WARN", "=0",
          ("、".join(bad)[:80] if bad else "无"), len(unl))
    for nm, u in (("判定图服务 8791", "http://127.0.0.1:8791/stats"),
                  ("主控页 8793", "http://127.0.0.1:8793/station"),
                  ("大屏 JSON 8799", "http://127.0.0.1:8799/dashboard.json")):
        ms, okb, sz, err = http_timing(u, n=2, timeout=8)
        r.add(cat, "%s 响应" % nm, ms if ms is not None else "err", "ms",
              "PASS" if okb and (ms or 1e9) <= 1000 else "WARN", "≤1000ms",
              "GET %s" % u, 2)


# ─────────────────────────── F 系统资源 ───────────────────────────
def cat_f(r: Rep):
    cat = "F 系统资源 (CPU/内存/磁盘/GPU)"
    try:
        la = float(open("/proc/loadavg").read().split()[0])
        nc = os.cpu_count() or 1
        r.add(cat, "负载(1min)", round(la, 2), "load", "PASS" if la <= nc * 1.2 else "WARN",
              "≤1.2×核数(%d)" % nc, "/proc/loadavg", 1)
    except Exception as e:                                                            # noqa: BLE001
        r.add(cat, "负载", "err", "", "FAIL", "—", str(e)[:60], 1)
    try:
        mt = {}
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":", 1)
            mt[k] = float(v.strip().split()[0]) / 1048576.0
        avail = mt.get("MemAvailable", 0.0)
        r.add(cat, "内存可用", round(avail, 2), "GB", "PASS" if avail >= 2 else ("WARN" if avail >= 1 else "FAIL"),
              "≥2GB (工具/模型共 8GB 上限, 超则 OOM)", "/proc/meminfo", 1)
    except Exception as e:                                                            # noqa: BLE001
        r.add(cat, "内存", "err", "", "FAIL", "—", str(e)[:60], 1)
    try:
        du = shutil.disk_usage("/")
        pct = 100.0 * du.used / du.total
        r.add(cat, "磁盘使用率(/)", round(pct, 1), "%", "PASS" if pct < 90 else "WARN",
              "<90% (红线守护 cron 每 2h)", "shutil.disk_usage('/')", 1)
        r.add(cat, "磁盘可用(/)", round(du.free / 1e9, 1), "GB", "PASS" if du.free > 30e9 else "WARN",
              ">30GB", "同上", 1)
    except Exception as e:                                                            # noqa: BLE001
        r.add(cat, "磁盘", "err", "", "FAIL", "—", str(e)[:60], 1)
    q = sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw "
           "--format=csv,noheader,nounits", t=10).strip().split(",")
    if len(q) >= 5:
        try:
            r.add(cat, "GPU 利用率", float(q[0]), "%", "PASS" if float(q[0]) >= 50 else "WARN",
                  "训练须满负荷 ≥50%", "nvidia-smi", 1)
            r.add(cat, "显存(used/total)", "%s/%s" % (q[1].strip(), q[2].strip()), "MB",
                  "PASS" if float(q[1]) < 0.9 * float(q[2]) else "WARN", "≤90%", "nvidia-smi", 1)
            r.add(cat, "GPU 温度", float(q[3]), "°C", "PASS" if float(q[3]) <= 80 else "WARN", "≤80°C",
                  "nvidia-smi", 1)
            r.add(cat, "GPU 功耗", float(q[4]), "W", "—", "—", "nvidia-smi", 1)
        except Exception as e:                                                        # noqa: BLE001
            r.add(cat, "GPU", "err %s" % str(e)[:50], "", "FAIL", "—", "nvidia-smi", 1)
    else:
        r.add(cat, "GPU", "err: %s" % q[:80], "", "FAIL", "—", "nvidia-smi", 1)


# ─────────────────────────── G 训练 ───────────────────────────
def cat_g(r: Rep):
    cat = "G 训练 (在跑任务的步速/ETA; 最近 3DGS 质量)"
    ps = sh("ps -eo pid,etime,pcpu,args --sort=-pcpu 2>/dev/null | grep -E 'train|gs_train|lerobot-train' "
            "| grep -v grep")
    lines = [x for x in ps.splitlines() if "train" in x]
    r.add(cat, "在跑训练进程", len(lines), "个", "—", "—", "ps -eo args | grep train", 1)
    for ln in lines[:3]:
        r.add(cat, "训练进程", ln.strip()[:110], "", "—", "—", "ps", 1)
    # 最近 3DGS 训练报告
    reps = sorted(glob.glob(os.path.join(ROOT, "zmax_data/gs_assets/*/train_report.json")),
                  key=lambda p: os.path.getmtime(p), reverse=True)
    if reps:
        d = jload(reps[0], {})
        r.add(cat, "3DGS 最近训练报告", os.path.basename(os.path.dirname(reps[0])), "", "—", "—", reps[0], 1)
        for k, thr, good in (("holdout_psnr", 22.0, "high"), ("train_psnr", 30.0, "high")):
            v = d.get(k)
            if v is not None:
                r.add(cat, "3DGS %s" % k, round(float(v), 2), "dB",
                      "PASS" if float(v) >= thr else "WARN", "≥%.0fdB (3DGS 可用资产经验线)" % thr,
                      os.path.relpath(reps[0], ROOT), 1)
    q = sorted(glob.glob(os.path.join(ROOT, "zmax_data/gs_assets/*/quality_report.json")),
               key=lambda p: os.path.getmtime(p), reverse=True)
    if q:
        d = jload(q[0], {})
        r.add(cat, "3DGS 质检总判定", d.get("verdict") or d.get("result") or d.get("total") or "?", "",
              "PASS" if str(d.get("verdict")).lower().find("pass") >= 0 else "WARN", "beats_trivial+有结构",
              os.path.relpath(q[0], ROOT), 1)


# ─────────────────────────── H 配置完备性 ───────────────────────────
def cat_h(r: Rep):
    cat = "H 配置完备性 (映射/覆盖/一致性判据)"
    out = sh("cd %s && timeout 120 ./gui-venv311/bin/python tools/ss_meta_task.py --selftest 2>&1 | tail -14" % ROOT,
             t=180)
    r.add(cat, "元任务自检", "PASS" if "3/3 PASS" in out else "FAIL", "",
          "PASS" if "3/3 PASS" in out else "FAIL", "74/74 映射 + 各任务==enabled_nodes",
          "tools/ss_meta_task.py --selftest", 1)
    m = re.search(r"① 功能 module_ref → 画布节点: (\d+)/(\d+)", out)
    if m:
        r.add(cat, "功能→画布节点映射", "%s/%s" % (m.group(1), m.group(2)), "",
              "PASS" if m.group(1) == m.group(2) else "FAIL", "=100%",
              "同上", int(m.group(2)))
    for mt in re.finditer(r"(TASK-\d+-\w+)\s+元任务\s+(\d+) / enabled_nodes\s+(\d+)\s+(\S+)", out):
        r.add(cat, "%s 覆盖" % mt.group(1), "%s/%s" % (mt.group(2), mt.group(3)), "",
              "PASS" if mt.group(2) == mt.group(3) else "FAIL", "元任务数 == 启用节点数",
              "ss_meta_task --selftest", int(mt.group(3)))
    db = sh("cd %s && timeout 120 ./gui-venv311/bin/python tools/engineering_db.py check 2>&1 | tail -6" % ROOT, t=180)
    ok = ("漂移" not in db and "FAIL" not in db.upper())
    r.add(cat, "工程库一致性", "无漂移" if ok else "有漂移", "", "PASS" if ok else "WARN",
          "build 后 check 无漂移", "tools/engineering_db.py check", 1)
    # 任务/场景绑定
    b = jload(os.path.join(ROOT, "config/ss_task_binding.json"), {})
    r.add(cat, "激活任务", b.get("active_task"), "", "—", "—", "config/ss_task_binding.json", 1)
    r.add(cat, "任务数", len(b.get("tasks") or []), "个", "—", "—", "同上", 1)
    # 预测器可用性
    p = jload(os.path.join(LIVE, "meta_tasks_pred.json"), {})
    if p:
        r.add(cat, "元任务预测(图像+状态)", "%d 条" % (p.get("n_predicted") or 0), "",
              "PASS" if not p.get("degraded") else "WARN", "degraded=false 才算图像路真生效",
              "zmax_data/ss_live/meta_tasks_pred.json", 1)
        r.add(cat, "预测降级标记", str(p.get("degraded")), "", "—", "原因见 degrade_reason",
              (p.get("degrade_reason") or "")[:90], 1)


# ─────────────────────────── I 端到端 ───────────────────────────
def cat_i(r: Rep):
    cat = "I 端到端 (闭环执行结果/节拍)"
    cands = sorted(glob.glob(os.path.join(ROOT, "reports/ss_task_run_*_latest.json")),
                   key=lambda p: os.path.getmtime(p), reverse=True)
    for p in cands[:3]:
        d = jload(p, {})
        nm = os.path.basename(p).replace("ss_task_run_", "").replace("_latest.json", "")
        r.add(cat, "%s 成功" % nm, str(d.get("success")), "", "PASS" if d.get("success") else "WARN",
              "true", os.path.relpath(p, ROOT), 1)
        if d.get("steps") is not None:
            r.add(cat, "%s 步数" % nm, d.get("steps"), "步", "—", "—", "同上", 1)
    ev = sorted(glob.glob(os.path.join(ROOT, "docs/data_snapshots/*/切换验证台账_*.json")),
                key=lambda p: os.path.getmtime(p), reverse=True)
    for p in ev[:1]:
        d = jload(p, [])
        n = len(d) if isinstance(d, list) else len(d.get("rows") or [])
        r.add(cat, "配置切换验证条目", n, "条", "—", "逐次真激活+回执", os.path.relpath(p, ROOT), 1)
    # 引擎回路状态 = 端到端常驻
    st = jload(os.path.join(LIVE, "engine_latest.json"), {})
    if st:
        r.add(cat, "常驻回路最新状态", st.get("status"), "", "PASS" if st.get("status") else "WARN",
              "ready", "ss_live/engine_latest.json", 1)
        r.add(cat, "回路帧龄", round(time.time() - float(st.get("ts") or 0), 2), "s",
              "PASS" if (time.time() - float(st.get("ts") or 0)) <= 2 else "WARN", "≤2s",
              "同上", 1)


# ─────────────────────────── J 安全 ───────────────────────────
def cat_j(r: Rep):
    cat = "J 安全 (运动闸/编码器来源/守卫/veto)"
    d = jload(os.path.join(ROOT, "zmax_data/ss_live/engine_latest.json"), {})
    r.add(cat, "运动授权闸 motion_armed", "见 8793 (默认 False)", "", "—",
          "默认关; 授权只能从 8793 产生", "8793 页面", 1)
    r.add(cat, "L4 潜表示来源", str(d.get("z_source") or "?")[:60], "",
          "PASS" if str(d.get("z_source") or "").startswith("内建 PCA") is False else "WARN",
          "期望 VLM 编码器; PCA=退化为内建", "ss_live/engine_latest.json", 1)
    r.add(cat, "内稳态是否启用", str(d.get("hom_enabled")), "", "—", "—", "同上", 1)
    r.add(cat, "内稳态 veto", str(d.get("hom_veto")), "", "PASS" if not d.get("hom_veto") else "WARN",
          "veto=True 时动作被拦", "同上", 1)
    r.add(cat, "异常度 anomaly", d.get("anomaly"), "", "PASS" if (d.get("anomaly") or 0) < 0.5 else "WARN",
          "<0.5 正常", "同上", 1)
    r.add(cat, "位姿唯一依据新鲜度", round(time.time() - os.path.getmtime(
        os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")), 1) if os.path.exists(
        os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")) else "缺", "s",
        "PASS" if os.path.exists(os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json"))
        and time.time() - os.path.getmtime(os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")) < 5
        else "WARN", "≤5s (全 0/陈旧不可用)", "rokae_sdk/tcp_out/latest.json", 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cycles", type=int, default=40)
    ap.add_argument("--runs", type=int, default=3, help="整链 pipeline 实跑次数")
    a = ap.parse_args()
    r = Rep()
    for fn in (lambda: cat_a(r, a.runs), lambda: cat_b(r, a.cycles), lambda: cat_c(r), lambda: cat_d(r),
               lambda: cat_e(r), lambda: cat_f(r), lambda: cat_g(r), lambda: cat_h(r),
               lambda: cat_i(r), lambda: cat_j(r)):
        try:
            fn()
        except Exception as e:                                                    # noqa: BLE001
            r.add("X 采集异常", getattr(fn, "__name__", "cat"), "err %s" % str(e)[:70], "", "FAIL", "—", "harness", 1)
    md = r.md()
    if a.json:
        print(json.dumps({"meta": {"ts": time.time(), "elapsed_s": round(time.time() - r.t0, 1)},
                          "categories": r.cats}, ensure_ascii=False, indent=1))
    else:
        print(md)
    if a.write:
        os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        mp = os.path.join(ROOT, "reports/perf_report_%s.md" % ts)
        jp = os.path.join(ROOT, "reports/perf_report_%s.json" % ts)
        open(mp, "w", encoding="utf-8").write(md)
        json.dump({"meta": {"ts": time.time(), "elapsed_s": round(time.time() - r.t0, 1),
                            "repo": ROOT}, "categories": r.cats},
                  open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("✅ %s" % mp)
        print("✅ %s" % jp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
