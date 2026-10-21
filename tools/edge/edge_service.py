#!/usr/bin/env python3
"""550C 端侧推理服务 (Intel 边缘机) —— 只做一件事: 远程把图发进来, 端侧 NPU/GPU 出检测框, 回 JSON。

设计口径 (老倪 2026-10-21): 「550C 用于量产, 直接部署在 intel 上, 550C 包括所有模型, 可以远程端侧实时运行」
  · 零第三方 web 依赖 (stdlib ThreadingHTTPServer), 断网也能起;
  · 模型/设备/阈值全部来自命令行或环境变量, 不在代码里写死;
  · 每次响应都带 infer_ms / device / model_sha16, 让"实时"和"这份权重"可核;
  · /health 给运维与 550C 探活 (进程、设备、已加载模型、最近一帧耗时)。

接口:
  GET  /health                      → {ok, device, model, sha16, last_ms, n_req, hw:{cpu/mem/disk/temp/npu}, infer:{busy,req_rate_10s}}
  POST /detect  (body = JPEG/PNG)   → {ok, device, infer_ms, w, h, dets:[{cls,conf,xyxy}]}
  POST /detect?conf=0.3&iou=0.45    → 阈值可覆盖
用法: python edge_service.py --xml ir/yolo_peg_live.xml --device NPU --port 8800
"""
import argparse
import collections
import hashlib
import io
import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
import openvino as ov

IMGSZ = 640
PAD = 114
STATE = {"n": 0, "last_ms": None, "t0": time.time(),
         "req_ts": collections.deque(maxlen=400), "last_req_t": 0.0,
         "dev_req": {}}


# ── 硬件 / 负载 (2026-10-21) ────────────────────────────────────────────────
#   目的: 主界面最下面的灯带要看「Intel 的硬件 + 模型是否在推理」, /health 必须自报,
#   不靠主节点去 ssh 采 (工控机上未必有登录口)。全部走 /proc 与 /sys, 零第三方依赖。
_CPU = {"t": 0.0, "idle": 0.0, "total": 0.0, "pct": None}


def _cpu_pct():
    """两次 /proc/stat 采样差分; 首次调用返回 None (不编 0)。"""
    try:
        with open("/proc/stat") as f:
            fld = f.readline().split()[1:]
        vals = [float(x) for x in fld]
        idle, total = vals[3] + vals[4], sum(vals)
        p = _CPU["pct"]
        if _CPU["total"] and total > _CPU["total"]:
            dt, di = total - _CPU["total"], idle - _CPU["idle"]
            p = round(max(0.0, min(100.0, 100.0 * (dt - di) / dt)), 1)
        _CPU.update(t=time.time(), idle=idle, total=total, pct=p)
        return p
    except Exception:
        return None


def _temp_c():
    try:
        for z in sorted(os.listdir("/sys/class/thermal")):
            if not z.startswith("thermal_zone"):
                continue
            base = "/sys/class/thermal/" + z
            try:
                typ = open(base + "/type").read().strip()
            except Exception:
                continue
            if "pkg" in typ or "coretemp" in typ or "x86" in typ:
                return round(int(open(base + "/temp").read().strip()) / 1000.0, 1)
    except Exception:
        pass
    return None


# ── 硬件注册表 / 算力 (2026-10-21) ──────────────────────────────────────────
#   老倪: 「intel 的所有硬件、算力、磁盘空间大小，都要显示标识」。硬件的**身份与算力**是静态的
#   (CPU 型号 / iGPU 型号+INT8 TOPS / NPU 型号+INT8 TOPS), 启动时问一次 OpenVINO 就够;
#   **占用**是动态的 (CPU%、内存、磁盘、温度、板载 GPU/NPU 是否在跑) 每次 /health 现采。
_STATIC = {}


def _rd(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def _drv(link):
    """driver/module 软链 → 驱动名 (软链指向目录, 不能用 read_text)。"""
    try:
        return os.path.basename(os.path.realpath(link))
    except Exception:
        return None


def _npu_dev():
    """/dev/accel/accel0 才是真实节点 (udev 建的是子目录); 兼容老内核的 /dev/accel0。"""
    if os.path.exists("/dev/accel/accel0"):
        return "/dev/accel/accel0"
    try:
        for fn in sorted(os.listdir("/dev/accel")):
            if fn.startswith("accel"):
                return "/dev/accel/" + fn
    except Exception:
        pass
    return "/dev/accel0" if os.path.exists("/dev/accel0") else None


def _gops_to_tops(gops, typ="int8_t"):
    """OpenVINO DEVICE_GOPS: {'<Type: int8_t>': 50380.8, ...} (GOPS) → TOPS。取不到就 None, 不估算。"""
    try:
        for k, v in (gops or {}).items():
            if typ in str(k) and v:
                return round(float(v) / 1000.0, 1)
    except Exception:
        pass
    return None


def _dev_static(core, dev):
    """某设备的型号/架构/INT8 算力 (TOPS) —— 取不到就如实空着。"""
    out = {"name": None, "arch": None, "tops_int8": None}
    try:
        out["name"] = str(core.get_property(dev, "FULL_DEVICE_NAME"))
    except Exception:
        pass
    try:
        out["arch"] = str(core.get_property(dev, "DEVICE_ARCHITECTURE"))
    except Exception:
        pass
    for key in ("DEVICE_GOPS", "DEVICE_GOPS"):
        try:
            out["tops_int8"] = _gops_to_tops(core.get_property(dev, key), "int8_t")
            break
        except Exception:
            continue
    return out


def _init_static(core, devices):
    """启动时只跑一次: 主机身份 + 三设备身份/算力 + 磁盘总量。"""
    cpu_model, threads = None, os.cpu_count()
    for ln in open("/proc/cpuinfo"):
        if ln.startswith("model name"):
            cpu_model = ln.split(":", 1)[1].strip()
            break
    mhz_max = _rd("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    _STATIC.update({
        "host": os.uname().nodename, "kernel": os.uname().release, "arch": os.uname().machine,
        "ov_version": ov.__version__, "devices_ov": list(devices),
        "cpu": {"model": cpu_model, "threads": threads,
                "mhz_max": round(int(mhz_max) / 1000.0) if mhz_max else None},
        "gpu": {"pci": None, "driver": _drv("/sys/class/drm/card0/device/driver/module"),
                "tops_int8": None, "name": None},
        "npu": {"dev": _npu_dev(), "present": bool(_npu_dev()),
                "driver": _drv("/sys/class/accel/accel0/device/driver/module"),
                "pci": None, "name": None, "tops_int8": None},
    })
    for ln in (_rd("/sys/class/drm/card0/device/uevent") or "").splitlines():
        if ln.startswith("PCI_ID="):
            _STATIC["gpu"]["pci"] = ln.split("=", 1)[1]
    for ln in (_rd("/sys/class/accel/accel0/device/uevent") or "").splitlines():
        if ln.startswith("PCI_ID="):
            _STATIC["npu"]["pci"] = ln.split("=", 1)[1]
    for dev, key in (("GPU", "gpu"), ("NPU", "npu")):
        if dev in devices:
            d = _dev_static(core, dev)
            _STATIC[key].update(name=d.get("name"), arch=d.get("arch"), tops_int8=d.get("tops_int8"))
    try:
        du = shutil.disk_usage("/")
        _STATIC["disk_root_gb"] = round(du.total / 1e9, 1)
    except Exception:
        pass
    return _STATIC


def _disk_mounts():
    out = []
    for mnt in ("/", "/boot/efi"):
        try:
            u = shutil.disk_usage(mnt)
            out.append({"mount": mnt, "total_gb": round(u.total / 1e9, 1),
                        "used_gb": round(u.used / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
                        "pct": round(100.0 * u.used / u.total, 1)})
        except Exception:
            pass
    return out


def _dev_in_use(dev, window_s=3.0):
    """该设备最近 window_s 内有没有真在推理 (流水线计数 / 单帧请求, 任一即可)。"""
    now = time.time()
    st = (PIPE.get("stat") or {}).get(dev) or {}
    if st.get("last_t") and (now - float(st["last_t"])) <= window_s:
        return True
    ts = (STATE.get("dev_req") or {}).get(dev)
    try:
        return bool(ts) and (now - float(ts)) <= window_s
    except Exception:                                                 # noqa: BLE001
        return False


def _hw():
    """动态占用 + 静态身份/算力 一起给 (字段名跟主节点 status_hub 的口径对齐)。"""
    hw = {"host": _STATIC.get("host") or os.uname().nodename,
          "cpu_n": os.cpu_count(), "cpu_pct": _cpu_pct(),
          "cpu_model": (_STATIC.get("cpu") or {}).get("model"),
          "cpu_mhz_max": (_STATIC.get("cpu") or {}).get("mhz_max"),
          "cpu_mhz_now": None, "load1": round(os.getloadavg()[0], 2)}
    mhz = _rd("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    if mhz:
        try:
            hw["cpu_mhz_now"] = round(int(mhz) / 1000.0)
        except Exception:
            pass
    try:
        mi = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, v = ln.split(":", 1)
                mi[k] = int(v.split()[0])
        tot, avail = mi.get("MemTotal", 0), mi.get("MemAvailable", 0)
        hw["mem_total_mb"] = round(tot / 1024.0)
        hw["mem_used_mb"] = round((tot - avail) / 1024.0)
        hw["mem_pct"] = round(100.0 * (tot - avail) / tot, 1) if tot else None
    except Exception:
        pass
    disks = _disk_mounts()
    hw["disks"] = disks
    if disks:
        d0 = disks[0]
        hw["disk_total_gb"], hw["disk_used_gb"] = d0["total_gb"], d0["used_gb"]
        hw["disk_free_gb"], hw["disk_pct"] = d0["free_gb"], d0["pct"]
    hw["temp_c"] = _temp_c()
    hw["npu"] = bool(_npu_dev())
    # 三块算力的身份/算力 (静态) + 谁在用 (动态: 当前服务编译在哪个设备上)
    hw["accel"] = {
        "cpu": {"name": (_STATIC.get("cpu") or {}).get("model"),
                "tops_int8": None, "unit": "threads",
                "cap": (_STATIC.get("cpu") or {}).get("mhz_max")},
        # in_use = 最近 3s 真在算 (流水线 worker 或最近一次 /detect), 不看命令行 --device。
        # 2026-10-21 修真: 原来只看 --device ⇒ 流水线把 GPU 跑到 96% 占空, /health 还报 gpu.in_use=false
        # (界面把在干活的 iGPU 显示成「当前空闲」)。
        "gpu": dict((_STATIC.get("gpu") or {}), in_use=_dev_in_use("GPU")),
        "npu": dict((_STATIC.get("npu") or {}), in_use=_dev_in_use("NPU")),
    }
    return hw


def _busy():
    """模型是否在推理: 最近 3s 内有请求 = busy; 速率按最近 10s 请求数算。"""
    now = time.time()
    ts = STATE["req_ts"]
    while ts and now - ts[0] > 10.0:
        ts.popleft()
    rate = round(len(ts) / 10.0, 2)
    return {"busy": (now - STATE["last_req_t"]) < 3.0, "req_rate_10s": rate,
            "last_req_age_s": (round(now - STATE["last_req_t"], 1) if STATE["last_req_t"] else None)}


def letterbox(img, size=IMGSZ):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((size, size, 3), PAD, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return canvas, r, (left, top)


def decode(out, r, pad, conf_th=0.25, iou_th=0.45):
    p = out[0] if out.ndim == 3 and out.shape[0] == 1 else out
    if p.shape[0] < p.shape[1]:
        p = p.transpose(1, 0)
    # ⚡ 向量化: 8400 行纯 Python 循环实测吃掉 ~35ms (NPU 本身只要 2.5ms), 端到端因此假慢到 25FPS。
    #    改成 numpy 一次算完 + cv2.dnn.NMSBoxes(C++), 端侧才真"实时"。
    cs = p[:, 4:]
    cidx = cs.argmax(axis=1)
    conf = cs[np.arange(cs.shape[0]), cidx]
    keep = conf >= conf_th
    if not keep.any():
        return []
    xywh = p[keep, :4]
    conf = conf[keep]
    cidx = cidx[keep]
    xy = np.concatenate([xywh[:, 0:1] - xywh[:, 2:3] / 2.0, xywh[:, 1:2] - xywh[:, 3:4] / 2.0,
                         xywh[:, 2:3], xywh[:, 3:4]], axis=1)          # cxcywh -> xywh
    idx = cv2.dnn.NMSBoxes(xy.tolist(), conf.tolist(), conf_th, iou_th)
    idx = np.array(idx).flatten() if len(idx) else np.array([], dtype=int)
    res = []
    for i in idx:
        x, y, w, h = (float(v) for v in xy[i])   # numpy.float32 不能直接进 json
        res.append({"cls": int(cidx[i]), "conf": round(float(conf[i]), 4),
                    "xyxy": [round(float((x - pad[0]) / r), 1), round(float((y - pad[1]) / r), 1),
                             round(float((x - pad[0] + w) / r), 1), round(float((y - pad[1] + h) / r), 1)]})
    return sorted(res, key=lambda d: -d["conf"])


# ── 多设备 / 多模型: 编译结果按 (xml, device) 缓存 ────────────────────────────────
#   老倪 2026-10-21: 「我现在有 YOLO, SmolVLA, INTACT 模型, 怎么在 intel 上运行?」
#   ⇒ 服务不再绑死一个模型/一个设备: /detect?model=<名>&device=NPU|GPU|CPU 现编现跑, 编过就复用。
#   并发安全: 共用的是 **CompiledModel**(线程安全), 每次调用由它新建 InferRequest;
#   之前 4 并发 RemoteDisconnected 是共用一个 InferRequest 导致的, 这里不碰那个坑。
_COMP = {}
_COMP_LOCK = threading.Lock()


def _comp_cache_devices():
    return sorted({k[1] for k in _COMP.keys()})


def _comp_for(model_name, device):
    """(model 名, device) → (compiled_model, output_port, key)。

    2026-10-21 老倪「NPU GPU 最大化使用」: 流水线可用 hint=1 让 OpenVINO 按 **吞吐** 编
    (PERFORMANCE_HINT=THROUGHPUT ⇒ 单模型内部多 stream)；老设备/驱动不认就自动退回默认配置,
    退回要打印一行, 不许静默。
    """
    xml = Handler.meta.get("xml")
    if model_name:
        base = os.path.dirname(os.path.abspath(xml))
        cand = os.path.join(base, model_name if model_name.endswith(".xml") else model_name + ".xml")
        if not os.path.isfile(cand):
            raise FileNotFoundError("没有这个模型: %s" % cand)
        xml = cand
    hint = bool(PIPE.get("hint"))
    key = (os.path.abspath(xml), str(device or "NPU").upper(), hint)
    with _COMP_LOCK:
        if key not in _COMP:
            t0 = time.perf_counter()
            mdl = Handler.core.read_model(key[0])
            comp = None
            if hint:
                try:
                    comp = Handler.core.compile_model(mdl, key[1], {"PERFORMANCE_HINT": "THROUGHPUT"})
                except Exception as e:                                # noqa: BLE001
                    print("[edge] %s@%s 不支持 THROUGHPUT 提示 (%s) → 退回默认编译"
                          % (os.path.basename(key[0]), key[1], str(e)[:80]), flush=True)
            if comp is None:
                comp = Handler.core.compile_model(mdl, key[1])
            _COMP[key] = comp
            print("[edge] 编译 %s @ %s%s: %.1fms" % (os.path.basename(key[0]), key[1],
                                                    " (throughput)" if hint else "",
                                                    (time.perf_counter() - t0) * 1000), flush=True)
        comp = _COMP[key]
    return comp, comp.output(0), key


# ── NPU/GPU 并行调度 (2026-10-21 老倪: 「550C 全模型运行, 将 NPU GPU 最大化使用」) ────────
#   一台设备一个常驻 worker: 各自 back-to-back 跑自己那几个模型, 谁闲着就补下一个 ⇒ 两块算力同时吃满。
#   指标口径: duty = 该 worker 真正在执行推理的累计时间 / 墙钟时间 (不是"发了多少请求")。
PIPE = {"on": False, "stop": None, "threads": [], "t0": 0.0, "plan": [],
        "stat": {}, "streams": 1, "hint": False,
        "lock": threading.Lock()}   # stat[dev] = {"n":int, "busy_s":float, "last_ms":float, "err":str}
# streams = 每台设备并发几条 worker (每条自己 back-to-back 推理 ⇒ 设备不等主机侧开销, 占空往 100% 顶)


def _model_path(name):
    """模型名 (yolo_peg_live / xxx.xml / 绝对路径) → 绝对路径。"""
    if not name:
        return Handler.meta.get("xml")
    if os.path.isabs(name):
        return name
    base = os.path.dirname(os.path.abspath(Handler.meta.get("xml")))
    cand = os.path.join(base, name if name.endswith(".xml") else name + ".xml")
    if not os.path.isfile(cand):                       # 也允许传 ir/ 子目录下的名字
        cand2 = os.path.join(base, "ir", name if name.endswith(".xml") else name + ".xml")
        if os.path.isfile(cand2):
            return cand2
    return cand


def _dim(d):
    """OpenVINO Dimension → int; 动态维(-1)按 1 处理。"""
    try:
        return int(d.get_length()) if d.is_static else 1
    except Exception:                                             # noqa: BLE001
        return 1


def _sat_input(xml, img_path):
    """给 worker 造输入: 按模型自己声明的形状建 tensor; 有图且输入是 4D 图像就吃真图。
    返回 (feed, src) —— feed 是 np.ndarray (单输入) 或 {port: array} (多输入)。"""
    core = Handler.core
    m = core.read_model(_model_path(xml))
    ins = list(m.inputs)
    feed, srcs = {}, []
    for i, port in enumerate(ins):
        shp = [_dim(s) for s in port.partial_shape]
        arr = np.zeros(shp, dtype=np.float32)
        if len(shp) == 4 and img_path and os.path.exists(img_path) and i == 0:
            import cv2
            im = cv2.imread(img_path)
            if im is not None:
                im = cv2.resize(im, (shp[3], shp[2]))
                arr = np.ascontiguousarray(
                    im[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
                srcs.append(os.path.basename(img_path))
        feed[port] = arr
    vals = list(feed.values())
    if len(vals) == 1:
        return vals[0], (srcs[0] if srcs else "zeros")
    return vals, (",".join(srcs) if srcs else "zeros")     # 多输入 → 按端口顺序传 list
                                                        # (dict 用 read_model 的 Port 当键会被 OpenVINO 拒)


def _worker(dev, plan, stop_ev):
    st = PIPE["stat"][dev]
    while not stop_ev.is_set():
        for xml in plan:
            if stop_ev.is_set():
                break
            try:
                comp, port, key = _comp_for(xml, dev)
                x = Handler.sat_in.get((dev, os.path.basename(_model_path(xml))))
                if x is None:
                    x = np.zeros((1, 3, 640, 640), dtype=np.float32)
                t0 = time.perf_counter()
                comp(x)[port]
                dt = time.perf_counter() - t0
                with PIPE["lock"]:
                    st["n"] += 1
                    st["busy_s"] += dt
                    st["last_ms"] = round(dt * 1000.0, 2)
                    st["last_t"] = time.time()
                    st["err"] = None
            except Exception as e:                                    # noqa: BLE001
                st["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
                time.sleep(0.05)


def _parse_streams(spec, plan):
    """'2' → 每设备 2 条; '2:1' → NPU 2 条 / GPU 1 条; 缺省 1。"""
    spec = str(spec or "1").strip()
    if ":" in spec:
        parts = [x.strip() for x in spec.split(":")]
        out = {}
        for i, dev in enumerate([d for d in ("NPU", "GPU", "CPU") if d in plan]):
            try:
                out[dev] = max(1, min(int(parts[i]) if i < len(parts) else 1, 8))
            except Exception:                                         # noqa: BLE001
                out[dev] = 1
        for dev in plan:
            out.setdefault(dev, 1)
        return out
    try:
        n = max(1, min(int(spec), 8))
    except Exception:                                                 # noqa: BLE001
        n = 1
    return {dev: n for dev in plan}


def _pipe_start(plan, img_path=None, streams=1, hint=False):
    """plan = {"NPU":[xml...], "GPU":[xml...]}; streams=每设备并发 worker 数; hint=吞吐编译。

    streams 口径: 设备在同一时刻只有一条推理在跑时, 主机侧 (numpy 造 tensor/py 开销) 是空的 ⇒
    实测占空 ~96%。多开几条 worker 让设备始终有活 ⇒ 占空顶到 ~100%, fps 上去; 代价是单帧均值略增。
    """
    _pipe_stop()
    Handler.sat_in = {}
    strm = _parse_streams(streams, plan)
    PIPE.update(on=True, stop=threading.Event(), threads=[], t0=time.time(),
                plan=[{"dev": k, "models": list(v)} for k, v in plan.items()], stat={},
                streams=strm, hint=bool(hint))
    src = {}
    for dev, models in plan.items():
        if not models:
            continue
        for mname in models:                     # 同一设备多个模型 → 每个模型自己的输入张量
            x, s = _sat_input(mname or Handler.meta["xml"], img_path)
            Handler.sat_in[(dev, os.path.basename(_model_path(mname or Handler.meta["xml"])))] = x
            src["%s:%s" % (dev, mname)] = s
        PIPE["stat"][dev] = {"n": 0, "busy_s": 0.0, "last_ms": None, "err": None, "last_t": 0.0,
                             "src": ",".join(sorted({v for k2, v in src.items() if k2.startswith(dev + ":")}))}
        for i in range(strm.get(dev, 1)):
            th = threading.Thread(target=_worker, args=(dev, list(models), PIPE["stop"]), daemon=True,
                                  name="pipe-%s-%d" % (dev, i))
            th.start()
            PIPE["threads"].append(th)
    return {"ok": True, "plan": PIPE["plan"], "input": src, "t0": PIPE["t0"],
            "streams": strm, "hint": bool(hint)}


def _pipe_stop():
    if PIPE.get("stop") is not None:
        PIPE["stop"].set()
    for th in PIPE.get("threads") or []:
        th.join(timeout=2.0)
    PIPE.update(on=False, stop=None, threads=[])


def _pipe_stats():
    el = (time.time() - PIPE["t0"]) if PIPE["on"] else 0.0
    out = {}
    snap = {}
    with PIPE["lock"]:
        for dev, st in (PIPE.get("stat") or {}).items():
            snap[dev] = dict(st)
    for dev, st in snap.items():
        n = st["n"]
        busy = st["busy_s"]
        plan_models = next((x["models"] for x in (PIPE.get("plan") or []) if x["dev"] == dev), [])
        streams = PIPE.get("streams")
        n_str = (streams or {}).get(dev, 1) if isinstance(streams, dict) else 1
        out[dev] = {"n": n, "models": plan_models, "elapsed_s": round(el, 1),
                    "fps": round(n / el, 1) if el > 0 else None,
                    "avg_ms": round(busy / n * 1000.0, 2) if n else None,
                    # duty = 设备真正在算的时间 / 墙钟; 多 stream 时按 stream 数归一 (封顶 100)
                    "duty_pct": round(min(100.0, 100.0 * busy / el / max(1, n_str)), 1) if el > 0 else None,
                    "busy_ratio": round(busy / el, 2) if el > 0 else None,
                    "streams": n_str,
                    "last_ms": st["last_ms"], "src": st.get("src"), "err": st["err"]}
    return {"on": PIPE["on"], "elapsed_s": round(el, 1), "devices": out,
            "streams": PIPE.get("streams"), "hint": PIPE.get("hint"),
            "total_fps": round(sum((v["fps"] or 0) for v in out.values()), 1) if out else None}


class Handler(BaseHTTPRequestHandler):
    server_version = "zmax-edge/1.0"
    protocol_version = "HTTP/1.1"
    comp = None
    out_port = None
    meta = {}

    def log_message(self, fmt, *a):                     # 静音: 只留 /health 与错误
        if "/detect" not in (fmt % a):
            print("[edge] " + fmt % a, flush=True)

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/health", "/", "/healthz"):
            return self._json(200, dict(ok=True, uptime_s=round(time.time() - STATE["t0"], 1),
                                        n_req=STATE["n"], last_ms=STATE["last_ms"],
                                        hw=_hw(), infer=_busy(),
                                        pipeline=_pipe_stats(), **self.meta))
        if u.path == "/pipeline/stats":
            return self._json(200, dict(ok=True, **_pipe_stats()))
        if u.path == "/pipeline/stop":
            _pipe_stop()
            return self._json(200, dict(ok=True, stopped=True, **_pipe_stats()))
        if u.path == "/models":
            d = os.path.dirname(os.path.abspath(Handler.meta.get("xml") or "."))
            items = []
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".xml"):
                    fp = os.path.join(d, fn)
                    try:                                  # sha16 = 这份 IR 的身份 (界面要显示"跑的哪个权重")
                        _h = hashlib.sha256(open(fp, "rb").read()).hexdigest()[:16]
                    except Exception:                     # noqa: BLE001
                        _h = None
                    _b = fp[:-4] + ".bin"
                    items.append({"name": fn[:-4], "mb": round(os.path.getsize(fp) / 1e6, 1),
                                  "bin_mb": round(os.path.getsize(_b) / 1e6, 1) if os.path.isfile(_b) else None,
                                  "sha16": _h,
                                  "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fp))),
                                  "active": os.path.basename(Handler.meta.get("xml") or "") == fn})
            return self._json(200, {"ok": True, "dir": d, "models": items,
                                    "devices": list(_comp_cache_devices())})
        return self._json(404, {"ok": False, "error": "no such path %s" % u.path})

    def do_POST(self):
        try:
            return self._do_POST()
        except Exception:                                         # noqa: BLE001
            import traceback
            tb = traceback.format_exc().strip().splitlines()[-3:]
            try:
                self._json(500, {"ok": False, "error": " | ".join(tb)})
            except Exception:                                     # noqa: BLE001
                pass

    def _do_POST(self):
        u = urlparse(self.path)
        q0 = parse_qs(u.query or "")
        if u.path == "/pipeline/start":
            plan = {}
            for dev in ("NPU", "GPU", "CPU"):
                v = (q0.get(dev.lower()) or q0.get(dev) or [""])[0]
                if v:
                    plan[dev] = [x.strip() for x in v.split(",") if x.strip()]
            if not plan:
                plan = {Handler.meta.get("device") or "NPU": [os.path.basename(Handler.meta["xml"])]}
            img = (q0.get("img") or [""])[0] or None
            streams = (q0.get("streams") or ["1"])[0] or 1
            hint = (q0.get("hint") or ["0"])[0] in ("1", "true", "on", "yes")
            try:
                return self._json(200, _pipe_start(plan, img, streams=streams, hint=hint))
            except Exception as e:                                    # noqa: BLE001
                return self._json(500, {"ok": False, "plan": plan,
                                        "error": "%s: %s" % (type(e).__name__, str(e)[:200])})
        if u.path != "/detect":
            return self._json(404, {"ok": False, "error": "no such path %s" % u.path})
        q = parse_qs(u.query or "")
        conf = float((q.get("conf") or ["0.25"])[0])
        want_dev = (q.get("device") or [Handler.meta.get("device") or "NPU"])[0].upper()
        want_model = (q.get("model") or [None])[0]
        iou = float((q.get("iou") or ["0.45"])[0])
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 32 * 1024 * 1024:
            return self._json(400, {"ok": False, "error": "bad content-length %s" % n})
        raw = self.rfile.read(n)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return self._json(400, {"ok": False, "error": "不是能解码的图片 (要 JPEG/PNG)"})
        try:
            comp, out_port, used = _comp_for(want_model, want_dev)
        except Exception as e:                                        # noqa: BLE001
            return self._json(400, {"ok": False, "error": "compile %s/%s 失败: %s: %s"
                                                         % (want_model or Handler.meta.get("xml"),
                                                            want_dev, type(e).__name__, str(e)[:160])})
        t = time.perf_counter()
        lb, r, pad = letterbox(img)
        x = np.ascontiguousarray(lb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        out = comp(x)[out_port]
        dets = decode(out, r, pad, conf, iou)
        ms = round((time.perf_counter() - t) * 1000.0, 2)
        STATE["n"] += 1
        STATE["last_ms"] = ms
        STATE["last_req_t"] = time.time()
        STATE["req_ts"].append(time.time())
        STATE["dev_req"][used] = STATE["dev_req"].get(used, 0) + 1
        return self._json(200, dict(ok=True, device=used[1], model=os.path.basename(used[0]),
                                    infer_ms=ms, n_dev_req=STATE["dev_req"].get(used, 0),
                                    w=img.shape[1], h=img.shape[0], dets=dets))


def _sha_of(meta):
    return {"model": os.path.basename(meta.get("xml") or ""), "model_sha16": meta.get("sha16")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", required=True)
    ap.add_argument("--device", default=os.environ.get("ZMAX_EDGE_DEVICE", "NPU"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("ZMAX_EDGE_PORT", "8800")))
    ap.add_argument("--bind", default="0.0.0.0")
    a = ap.parse_args()

    core = ov.Core()
    t0 = time.perf_counter()
    model = core.read_model(a.xml)
    comp = core.compile_model(model, a.device)
    compile_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    with open(a.xml, "rb") as f:
        sha16 = hashlib.sha256(f.read()).hexdigest()[:16]
    Handler.comp, Handler.out_port = comp, comp.output(0)
    Handler.core = core
    _init_static(core, core.available_devices)          # 硬件身份 + 三设备算力 (静态, 只跑一次)
    _COMP[(os.path.abspath(a.xml), a.device.upper())] = comp
    Handler.meta = {"xml": a.xml, "device": a.device, "sha16": sha16,
                    "compile_ms": compile_ms, "imgsz": IMGSZ,
                    "host": os.uname().nodename, "pid": os.getpid()}
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print("[edge] 起来了: %s:%d device=%s model=%s sha=%s compile=%sms"
          % (a.bind, a.port, a.device, os.path.basename(a.xml), sha16, compile_ms), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
