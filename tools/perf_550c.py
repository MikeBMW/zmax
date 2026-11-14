#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""550C 性能实测探针: 十类指标, 每项真测, 测不到写 err。输出纯 JSON。
在 550C 本机跑: python3 /tmp/perf_550c.py > /tmp/perf_550c.json
"""
import json
import os
import shutil
import socket
import statistics
import subprocess
import time
import urllib.request

OUT = {"meta": {"host": socket.gethostname(), "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "ts_epoch": time.time(), "nproc": os.cpu_count()}, "m": []}


def add(cat, metric, value, unit="", verdict="—", threshold="", source="", samples=1):
    OUT["m"].append({"cat": cat, "metric": metric, "value": value, "unit": unit,
                     "verdict": verdict, "threshold": threshold, "source": source, "samples": samples})


def sh(cmd, t=8):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (r.stdout or "").strip()
    except Exception as e:
        return "err:" + repr(e)[:60]


def http_json(url, t=4):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=t) as r:
            body = r.read().decode("utf-8", "ignore")
        return json.loads(body), (time.time() - t0) * 1000.0, None
    except Exception as e:
        return None, (time.time() - t0) * 1000.0, repr(e)[:80]


# ---------- F 系统资源 ----------
la1, la5, la15 = os.getloadavg()
add("F系统资源", "load1", round(la1, 2), "", "FAIL" if la1 > os.cpu_count() else ("WARN" if la1 > os.cpu_count() * 0.7 else "PASS"),
    "load1 ≤ nproc", "/proc/loadavg")
add("F系统资源", "load5/load15", "%.2f/%.2f" % (la5, la15), "", "—", "", "/proc/loadavg")
add("F系统资源", "CPU超订系数 load1÷nproc", round(la1 / os.cpu_count(), 2), "", "PASS" if la1 / os.cpu_count() <= 1 else "FAIL",
    "≤1.0", "/proc/loadavg + os.cpu_count")

mi = {}
for line in open("/proc/meminfo"):
    k, v = line.split(":", 1)
    mi[k] = int(v.split()[0])
total_gb = mi["MemTotal"] / 1048576
used_gb = (mi["MemTotal"] - mi["MemAvailable"]) / 1048576
add("F系统资源", "内存占用", "%.1f/%.1f" % (used_gb, total_gb), "GB",
    "FAIL" if used_gb / total_gb > 0.9 else ("WARN" if used_gb / total_gb > 0.75 else "PASS"),
    "<75%", "/proc/meminfo", )
add("F系统资源", "内存占用率", round(used_gb / total_gb * 100, 1), "%", "—", "", "/proc/meminfo")
du = shutil.disk_usage("/")
add("F系统资源", "根盘可用", "%.0f/%.0f" % (du.free / 2**30, du.total / 2**30), "GB",
    "FAIL" if du.free / 2**30 < 30 else ("WARN" if du.free / 2**30 < 80 else "PASS"), "≥80GB 余量", "shutil.disk_usage('/')")
add("F系统资源", "根盘使用率", round(du.used / du.total * 100, 1), "%", "—", "", "shutil.disk_usage('/')")

temps = []
for i in range(8):
    p = "/sys/class/thermal/thermal_zone%d/temp" % i
    if os.path.exists(p):
        try:
            temps.append(int(open(p).read().strip()) / 1000.0)
        except Exception:
            pass
add("F系统资源", "最高温度", round(max(temps), 1) if temps else "err", "°C",
    ("WARN" if temps and max(temps) > 85 else "PASS") if temps else "—", "<85°C", "/sys/class/thermal/thermal_zone*/temp", len(temps))

mhz = []
for line in open("/proc/cpuinfo"):
    if line.startswith("cpu MHz"):
        try:
            mhz.append(float(line.split(":")[1]))
        except Exception:
            pass
if mhz:
    add("F系统资源", "CPU 当前主频(均值)", round(statistics.mean(mhz)), "MHz", "—", "", "/proc/cpuinfo", len(mhz))
    add("F系统资源", "CPU 主频 min/max", "%d/%d" % (min(mhz), max(mhz)), "MHz", "—", "", "/proc/cpuinfo", len(mhz))

# GPU (Intel Arc B390)
gpu = sh("timeout 6 xpu-smi stats -d 0 -j 2>/dev/null | head -c 600")
if gpu and not gpu.startswith("err") and "{" in gpu:
    add("F系统资源", "xpU stats(原始)", gpu[:300], "", "—", "", "xpu-smi stats -d 0 -j")
else:
    top = sh("timeout 5 sudo -n intel_gpu_top -J -s 500 2>/dev/null | head -c 400")
    if top and not top.startswith("err") and "{" in top:
        add("F系统资源", "intel_gpu_top(原始)", top[:300], "", "—", "", "intel_gpu_top -J -s 500")
    else:
        add("F系统资源", "GPU 利用率", "err", "%", "—", "", "xpu-smi / intel_gpu_top 均不可用(无权限或未装)", 0)

# ---------- E 服务可用 ----------
SVC = [(8811, "gs_ros_bridge(帧/位姿)"), (8812, "USB 相机"), (8814, "gs 训练服务"),
       (8806, "autocap 采集守护"), (8810, "自主进化"), (8816, "渲染/推流"), (8901, "cam relay")]
listen = sh("ss -ltnp 2>/dev/null")
for port, name in SVC:
    up = (":%d " % port) in listen or (":%d\t" % port) in listen
    j, ms, err = http_json("http://127.0.0.1:%d/health" % port) if up else (None, 0.0, "not listening")
    if j is not None:
        add("E服务可用", "%s :%d" % (name, port), "up", "", "PASS", "端口监听 + /health 200",
            "curl :%d/health, %.0fms" % (port, ms))
        add("E服务可用", "%s 健康响应延迟" % name, round(ms, 1), "ms",
            "PASS" if ms < 200 else "WARN", "<200ms", "curl -w 计时")
    else:
        add("E服务可用", "%s :%d" % (name, port), "down" if up else "not listening", "",
            "WARN" if not up else "FAIL", "端口应在监听", "ss -ltnp / curl :%d/health → %s" % (port, err))

units = sh("systemctl list-units 'zmax*' --state=running --no-legend --plain 2>/dev/null | awk '{print $1}'")
ul = [u for u in units.splitlines() if u.strip()]
add("E服务可用", "zmax systemd 运行单元数", len(ul), "个", "—", "", "systemctl list-units 'zmax*'", len(ul))
failu = sh("systemctl list-units 'zmax*' --state=failed --no-legend --plain 2>/dev/null | awk '{print $1}'")
fl = [u for u in failu.splitlines() if u.strip()]
add("E服务可用", "zmax 失败单元", len(fl), "个", "PASS" if not fl else "FAIL", "=0", "systemctl --state=failed", len(fl) or 1)

# ---------- C 视觉链路 ----------
def sample_fps(url, secs=4.0):
    j1, _, _ = http_json(url)
    if not j1:
        return None
    n1 = j1.get("frames") or j1.get("n") or 0
    t1 = time.time()
    time.sleep(secs)
    j2, _, _ = http_json(url)
    if not j2:
        return None
    n2 = j2.get("frames") or j2.get("n") or 0
    return {"fps": round((n2 - n1) / (time.time() - t1), 2), "h": j2}

sp = sample_fps("http://127.0.0.1:8811/health")
if sp:
    add("C视觉链路", "臂相机桥 8811 实测帧率", sp["fps"], "fps", "PASS" if sp["fps"] >= 10 else "WARN", "≥10fps(桥限 15)",
        "8811/health frames 差分 / 4s")
    h = sp["h"]
    add("C视觉链路", "臂相机帧龄", h.get("img_age_s"), "s", "PASS" if (h.get("img_age_s") or 99) < 1 else "FAIL", "<1s", "8811/health img_age_s")
    add("C视觉链路", "臂相机位姿龄", h.get("pose_age_s"), "s", "PASS" if (h.get("pose_age_s") or 99) < 0.5 else "WARN", "<0.5s", "8811/health pose_age_s")
    add("C视觉链路", "臂相机分辨率", "%sx%s" % (h.get("wh", [0, 0])[0], h.get("wh", [0, 0])[1]), "px", "—", "", "8811/health wh")
    add("C视觉链路", "臂相机亮度", h.get("brightness"), "", "PASS" if 40 <= (h.get("brightness") or 0) <= 200 else "WARN", "40~200",
        "8811/health brightness")
else:
    add("C视觉链路", "臂相机桥 8811", "err", "", "FAIL", "应可达", "8811/health 取不到", 0)

sp2 = sample_fps("http://127.0.0.1:8812/health")
if sp2:
    add("C视觉链路", "USB 相机 8812 实测帧率", sp2["fps"], "fps", "PASS" if sp2["fps"] >= 5 else "WARN", "≥5fps",
        "8812/health frames 差分 / 4s")
    add("C视觉链路", "USB 相机帧龄", sp2["h"].get("age_s"), "s", "PASS" if (sp2["h"].get("age_s") or 99) < 1 else "FAIL",
        "<1s", "8812/health age_s")
else:
    add("C视觉链路", "USB 相机 8812", "err", "", "WARN", "应可达", "8812/health 取不到", 0)

up = sh("curl -s -m3 http://192.168.23.66:8794/health 2>/dev/null")
add("C视觉链路", "上游 Orin 8794 中继", up[:120] if up else "err", "", "PASS" if '"n"' in up else "FAIL",
    "应返回 n/age_s", "curl 192.168.23.66:8794/health")

# ---------- B 常驻回路 / 采集吞吐 ----------
hc, _, _ = http_json("http://127.0.0.1:8806/health")
if hc:
    f1 = hc.get("frames_total", 0)
    time.sleep(4)
    hc2, _, _ = http_json("http://127.0.0.1:8806/health")
    f2 = hc2.get("frames_total", 0)
    add("B常驻回路", "autocap 采集速率(4s 窗口)", round((f2 - f1) / 4.0, 2), "帧/s", "—", "静置时应接近 0",
        "8806/health frames_total 差分", 2)
    add("B常驻回路", "autocap 累计收帧", f2, "帧", "—", "", "8806/health frames_total")
    add("B常驻回路", "autocap 会话数/已交训练", "%s/%s" % (hc2.get("sessions"), hc2.get("trains_submitted")), "个", "—", "",
        "8806/health sessions, trains_submitted")
    add("B常驻回路", "autocap 跳变跳过(累计)", hc2.get("frames_skipped_jump"), "帧", "—", "", "8806/health frames_skipped_jump")
    cur = hc2.get("cur") or {}
    add("B常驻回路", "当前会话帧数", cur.get("frames"), "帧", "—", "≥160 才自动交训练", "8806/health cur.frames")

# ---------- G 训练 ----------
ps = sh("pgrep -af 'gs_train.py' | grep -v bash")
if ps and not ps.startswith("err"):
    parts = ps.splitlines()[0].split()
    pid = parts[0]
    et = sh("ps -o etimes= -p %s" % pid).strip()
    pc = sh("ps -o pcpu=,rss= -p %s" % pid).strip().split()
    add("G训练", "在跑训练作业", parts[parts.index("--data") + 1].split("/")[-1] if "--data" in parts else "?", "",
        "PASS", "应有作业在跑", "pgrep -af gs_train.py")
    add("G训练", "训练已运行", int(et) if et.isdigit() else "err", "s", "—", "", "ps -o etimes")
    if len(pc) >= 2:
        add("G训练", "训练进程 CPU", float(pc[0]), "%", "PASS" if float(pc[0]) > 60 else "WARN", ">60%(单核占比)",
            "ps -o pcpu")
        add("G训练", "训练进程 RSS", round(float(pc[1]) / 1024), "MB", "—", "", "ps -o rss")
else:
    add("G训练", "在跑训练作业", "无", "", "WARN", "空闲", "pgrep -af gs_train.py", 0)

jb = "/home/intel/gs_train_service_intel/jobs"
reports = []
if os.path.isdir(jb):
    for n in sorted(os.listdir(jb)):
        p = os.path.join(jb, n, "out", "train_report.json")
        if os.path.exists(p):
            try:
                reports.append((os.path.getmtime(p), n, json.load(open(p))))
            except Exception:
                pass
reports.sort(reverse=True)
if reports:
    mt, name, r = reports[0]
    add("G训练", "最近完成作业", name, "", "PASS", "", jb + "/<job>/out/train_report.json")
    add("G训练", "最近作业 PSNR(留出)", round(r.get("psnr_holdout_db", 0), 2), "dB", "—", "越高越好", "train_report.json psnr_holdout_db")
    add("G训练", "最近作业 PSNR(训练集)", round(r.get("psnr_train_db", 0), 2), "dB", "—", "", "train_report.json")
    add("G训练", "最近作业高斯数", r.get("n_gaussians"), "个", "—", "", "train_report.json n_gaussians")
    add("G训练", "最近作业步数/耗时", "%s步/%.0fs" % (r.get("steps"), r.get("seconds") or 0), "", "—", "",
        "train_report.json steps, seconds")
    add("G训练", "已完成作业总数", len(reports), "个", "—", "", jb + "/*/out/train_report.json", len(reports))
    add("G训练", "历史最佳 PSNR(留出)", round(max(x[2].get("psnr_holdout_db", 0) for x in reports), 2), "dB", "—", "",
        "全部 train_report.json 取 max", len(reports))

# ---------- A 推理/进化 ----------
evo, ms, _ = http_json("http://127.0.0.1:8810/health")
if evo is None:
    evo, ms, _ = http_json("http://127.0.0.1:8810/status")
if evo:
    add("A层推理/进化", "自主进化服务延迟", round(ms, 1), "ms", "PASS" if ms < 300 else "WARN", "<300ms",
        "curl :8810/health 计时")
    for k, lab in (("gen", "进化代数"), ("best_map50", "最佳 mAP50"), ("best_map5095", "最佳 mAP50-95"),
                   ("accepted", "接受代数"), ("rejected", "拒绝代数")):
        if k in evo:
            v = evo[k]
            add("A层推理/进化", lab, round(v, 4) if isinstance(v, float) else v, "", "—", "", "8810 响应字段 " + k)
else:
    add("A层推理/进化", "自主进化 8810", "err", "", "WARN", "", "取不到 /health /status", 0)

# ---------- D 模型资产 ----------
for d, lab in (("/home/intel/zmax_map/models", "模型目录"), ("/home/intel/gs_autocap/sessions", "采集会话目录")):
    if os.path.isdir(d):
        sz = sh("du -sm %s 2>/dev/null | cut -f1" % d)
        cnt = len([x for x in os.listdir(d) if not x.startswith(".")])
        add("D模型资产", lab, "%sMB / %d 项" % (sz, cnt), "", "—", "", "du -sm, ls")

# ---------- I 端到端 ----------
if reports and hc:
    add("I端到端", "采集→训练→资产 闭环", "通", "", "PASS", "frames>0 且 有 train_report",
        "8806 frames_total=%s + %d 份 train_report" % (hc.get("frames_total"), len(reports)))
    add("I端到端", "闭环产出质量(最近)", round(reports[0][2].get("psnr_holdout_db", 0), 2), "dB",
        "WARN" if reports[0][2].get("psnr_holdout_db", 0) < 18 else "PASS", "≥18dB 才算可用重建",
        "最近 train_report.json")

# ---------- J 安全 ----------
for p, lab in (("/home/intel/zmax_data/ctl_auth.json", "本机授权闸文件"),
               ("/home/intel/zmax_map/models/real_cam_calib_undist.json", "相机内参"),
               ("/home/intel/zmax_map/models/handeye_state.json", "手眼标定")):
    add("J安全/真源", lab, "有" if os.path.exists(p) else "缺", "", "PASS" if os.path.exists(p) else "WARN",
        "应存在", p)

# 输出
by = {}
for m in OUT["m"]:
    by.setdefault(m["cat"], []).append(m)
OUT["summary"] = {c: {"n": len(v),
                      "PASS": sum(1 for x in v if x["verdict"] == "PASS"),
                      "WARN": sum(1 for x in v if x["verdict"] == "WARN"),
                      "FAIL": sum(1 for x in v if x["verdict"] == "FAIL"),
                      "err": sum(1 for x in v if x["value"] == "err")} for c, v in by.items()}
OUT["summary"]["_total"] = {"n": len(OUT["m"]),
                            "PASS": sum(1 for x in OUT["m"] if x["verdict"] == "PASS"),
                            "WARN": sum(1 for x in OUT["m"] if x["verdict"] == "WARN"),
                            "FAIL": sum(1 for x in OUT["m"] if x["verdict"] == "FAIL"),
                            "err": sum(1 for x in OUT["m"] if x["value"] == "err")}
print(json.dumps(OUT, ensure_ascii=False, indent=1))
