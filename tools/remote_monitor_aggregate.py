#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""remote_monitor_aggregate.py — 把"远程监控"汇总成**同源**的一层。

一句话: 清单化所有对外/远程的页与服务(ECS 大屏 / 手机页 / 本机站点服务 / Orin / 工控机 AOI),
逐个**实采**状态 → 输出**一份统一 JSON + 人读表**; 每项带 source_url / 采集时间 / 新鲜度(秒) /
ok|err / 关键字段摘要; 并对"报告同一事实的多个端点"做**同源判定**(一致/不一致)。

用法:
  python3 tools/remote_monitor_aggregate.py                 # 人读表
  python3 tools/remote_monitor_aggregate.py --list          # 只列清单(不实采)
  python3 tools/remote_monitor_aggregate.py --json          # 统一 JSON 到 stdout
  python3 tools/remote_monitor_aggregate.py --json-out p.json

红线(本脚本严格遵守):
  · 不打印/不写盘任何密码·token·口令 —— 所有输出先过 redact(); 落盘/打印前再断言一次。
  · 不修改远端(ECS)任何文件; 只做 GET 读取。
  · 不执行任何真机动作(只读端点; 绝不触碰 /ctl/* · /gen · /move 等写/动接口)。
  · 网络不通/超时/受限 ⇒ 如实标 err, 绝不编造字段。
"""

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# ─────────────────────────── 时间/常量 ───────────────────────────
STALE_S = 10.0            # >10s 记为 stale
TIMEOUT = 3.0             # 单次超时 3s
RETRIES = 1               # 失败重试 1 次

ECS_DOMAIN = os.environ.get("ZMAX_ECS_DOMAIN", "datadrive.world")
# ECS 只读闸门口令: 走 tunnel_proxy 的 ?k=<token>(与部署 unit 的 --token 同源)。
# 这是"共享口令", 不是 SSH 密码; 但仍按口令处理 —— 绝不出现在任何输出里。
OV_TOKEN = os.environ.get("ZMAX_OV_TOKEN", "zmax-live")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # …/zmax
SECRETS_FILE = os.path.join(ROOT, "zmax_data/secrets/zmax.env")
HIL_TOKEN_FILE = os.path.join(ROOT, "zmax_data/secrets/hil_term.token")
ECS_ENV_FILES = ["/etc/zmax-ecs-ov.env", "/etc/zmax-ecs-station.env"]

OWNER_ECS = "ECS 大屏 (datadrive.world)"
OWNER_LOCAL = "本机站点 (工位机 4060)"
OWNER_ORIN = "Orin (192.168.23.66)"
OWNER_IPC = "产线工控机 AOI (192.168.23.23)"
OWNER_PHONE = "手机页 (公网镜像)"


# ─────────────────────────── 凭据加载 + 脱敏 ───────────────────────────
def _load_secrets():
    """把所有"口令类"值读进内存(绝不打印)。读不到就跳过, 不报错。"""
    secs = set()
    # ① 项目 secrets (ZMAX_AGENT_TOKEN / ZMAX_SS3D_TOKEN / ZMAX_ECS_PW / WINSTATION_ADMIN_PW)
    try:
        with open(SECRETS_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                val = line.split("=", 1)[1].strip()
                for part in val.split(","):          # token 可能是逗号列表
                    if len(part) >= 3:
                        secs.add(part)
    except Exception:
        pass
    # ② HIL 终端 token
    try:
        with open(HIL_TOKEN_FILE, encoding="utf-8") as fh:
            t = fh.read().strip()
            if len(t) >= 3:
                secs.add(t)
    except Exception:
        pass
    # ③ ECS SSH env(仅在可读时才读; 本脚本 HTTP 读取并不需要它)
    for p in ECS_ENV_FILES:
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        v = line.split("=", 1)[1].strip()
                        if len(v) >= 3:
                            secs.add(v)
        except Exception:
            pass  # 无权读(root 600) 就跳过 —— 本脚本不靠它
    # ④ 共享闸门口令(功能上是口令)
    if OV_TOKEN:
        secs.add(OV_TOKEN)
    return secs


SECRETS = _load_secrets()
_QP_RE = re.compile(r"(?i)([?&](?:k|token|t|pw|pwd|password|passwd|secret)=)[^&\s\"'<>]+")
_KV_RE = re.compile(r"(?i)((?:password|passwd|pwd|secret|token|口令)\s*[:=]\s*)(\S+)")


def redact(text):
    """对任意文本做脱敏: 已知口令值 → ***; 查询串里的口令参数 → ***。"""
    s = "" if text is None else str(text)
    for sec in SECRETS:
        if sec and len(sec) >= 3:
            s = s.replace(sec, "***")
    s = _QP_RE.sub(r"\1***", s)
    s = _KV_RE.sub(r"\1***", s)
    return s


def redact_obj(obj):
    """对 JSON 结构递归脱敏。"""
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


def assert_no_secrets(text):
    """硬断言: 捕获的输出里 grep 不到任何口令。返回 (ok, 命中数, 口令总数)。"""
    hits = [s for s in SECRETS if s and len(s) >= 3 and s in text]
    return (len(hits) == 0, len(hits), len(SECRETS))


# ─────────────────────────── HTTP 采集 ───────────────────────────
_CTX = ssl.create_default_context()


def _http_get(url, timeout=TIMEOUT, retries=RETRIES):
    """GET 一次, 失败重试 retries 次。返回 (ok, status, body_text, err)。"""
    last_err = ""
    last_status = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "zmax-remote-monitor/1.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                raw = r.read()
                return True, int(getattr(r, "status", 200)), raw.decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            last_status = e.code
            last_err = "HTTP %s" % e.code
            if 400 <= e.code < 500:          # 4xx 重试也没用
                return False, e.code, body, last_err
        except Exception as e:
            last_status = None
            last_err = "%s: %s" % (type(e).__name__, e)
            time.sleep(0.4)
    return False, last_status, "", last_err or "unreachable"


def _js(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def _get_path(d, path, default=None):
    """按 'a.b.c' 取值; 任一层缺失返回 default。"""
    cur = d
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list):
            try:
                cur = cur[int(k)]
            except Exception:
                return default
        else:
            return default
    return cur


def _parse_ts_any(v):
    """把"数据时间戳"解析成 epoch 秒: 支持 epoch 数字 / 'YYYY-mm-dd HH:MM:SS'。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.match(r"^\d+(\.\d+)?$", s):
        return float(s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return time.mktime(time.strptime(s[: len(fmt) + 2].strip(), fmt))
        except Exception:
            continue
    return None


# ─────────────────────────── 各端点解析器 ───────────────────────────
# 约定: 返回 (fields:dict, vals:dict, age_s:float|None, data_ts:epoch|None)
#   · frame 型端点: age_s = 上报的帧龄(直接当数据龄)
#   · ts    型端点: data_ts = 数据自带时间戳(由 collect 算 now-ts)
def _p_ov(b):
    d = json.loads(b)
    cams = d.get("cameras") or {}
    fields = {"who": d.get("who"), "相机": cams, "fps_now": d.get("fps_now"),
              "禁止": (d.get("禁止") or "")[:40]}
    return fields, {"cameras": list(cams.keys())}, None, None


def _p_html_page(b):
    m = re.search(r"<title>(.*?)</title>", b, re.S)
    title = (m.group(1).strip() if m else "")[:60]
    return {"title": title, "bytes": len(b)}, {}, None, None


def _p_station(b):
    d = json.loads(b)
    st = d.get("stats", {})
    arm = st.get("arm", {})
    frames = {k: {"fps": (st.get(k) or {}).get("fps"), "online": (st.get(k) or {}).get("online"),
                  "age_s": (st.get(k) or {}).get("age_s"),
                  "frames": (st.get(k) or {}).get("frames_served")}
              for k in ("arm", "local", "local2") if k in st}
    fields = {"arm": _js(frames.get("arm")), "local.fps": frames.get("local", {}).get("fps"),
              "local2.fps": frames.get("local2", {}).get("fps"), "aoi_auto": _js(d.get("aoi_auto"))}
    vals = {"arm.fps": arm.get("fps"), "arm.age_s": arm.get("age_s"),
            "arm.online": arm.get("online"), "arm.label": arm.get("label"),
            "arm.frames": arm.get("frames_served")}
    age = arm.get("age_s")
    return fields, vals, (float(age) if isinstance(age, (int, float)) else None), None


def _p_zmax_status(b):
    d = json.loads(b)
    models = d.get("models") or []
    fields = {"gpu.util": _get_path(d, "hw.gpu.util"), "gpu.mem_mb": _get_path(d, "hw.gpu.mem_used_mb"),
              "cpu.load1": _get_path(d, "hw.cpu.load1"), "disk.pct": _get_path(d, "hw.disk.pct"),
              "models": len(models)}
    vals = {"gpu.util": _get_path(d, "hw.gpu.util"), "cpu.load1": _get_path(d, "hw.cpu.load1")}
    return fields, vals, None, _parse_ts_any(d.get("ts"))


def _p_ss3d(b):
    d = json.loads(b)
    cams = _get_path(d, "hw.cams", {}) or {}
    fields = {"playing": d.get("playing"), "arm.fps": _get_path(cams, "arm.fps"),
              "arm.age_s": _get_path(cams, "arm.age_s"), "infer.on": _get_path(d, "hw.infer.on")}
    vals = {"arm.fps": _get_path(cams, "arm.fps"), "arm.age_s": _get_path(cams, "arm.age_s")}
    return fields, vals, None, _parse_ts_any(d.get("beat"))


def _p_relay(b):
    d = json.loads(b)
    meta = d.get("latest_meta") or {}
    fields = {"packages": d.get("packages"), "uptime_s": d.get("uptime"), "latest": d.get("latest"),
              "source": meta.get("source"), "type": meta.get("type")}
    return fields, {}, None, _parse_ts_any(meta.get("time"))


def _p_orin_relay(b):
    d = json.loads(b)
    rk = d.get("robot_stack") or {}
    fields = {"online": d.get("online"), "host": d.get("host"), "last_seen": d.get("last_seen"),
              "cpu_temp_c": d.get("cpu_temp_c"), "uptime_s": d.get("uptime_s"),
              "robot_driver": rk.get("robot_driver"), "motion": rk.get("motion")}
    return fields, {"online": d.get("online")}, None, _parse_ts_any(d.get("ts"))


def _p_stats8791(b):
    d = json.loads(b)
    arm = d.get("arm", {})
    frames = {k: {"fps": (d.get(k) or {}).get("fps"), "online": (d.get(k) or {}).get("online"),
                  "age_s": (d.get(k) or {}).get("age_s"),
                  "frames": (d.get(k) or {}).get("frames_served")}
              for k in ("arm", "local", "local2") if k in d}
    fields = {"arm": _js(frames.get("arm")), "local.fps": frames.get("local", {}).get("fps"),
              "local2.fps": frames.get("local2", {}).get("fps")}
    vals = {"arm.fps": arm.get("fps"), "arm.age_s": arm.get("age_s"), "arm.online": arm.get("online"),
            "arm.label": arm.get("label"), "arm.frames": arm.get("frames_served")}
    age = arm.get("age_s")
    return fields, vals, (float(age) if isinstance(age, (int, float)) else None), None


def _p_hil(b):
    d = json.loads(b)
    snap = d.get("snapshot") or {}
    fields = {"ok": d.get("ok"), "pause": d.get("pause"), "stage": snap.get("stage"),
              "frame_age_s": snap.get("frame_age_s"), "canvas_nodes": _get_path(snap, "canvas.nodes"),
              "peers": len(_get_path(snap, "links.peers", []) or []),
              "instructions": len(d.get("instructions") or [])}
    return fields, {}, None, _parse_ts_any(snap.get("obs_ts"))


def _p_agentlog(b):
    lines = [ln for ln in b.splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    data_ts = None
    m = re.findall(r"\[(\d{2}):(\d{2}):(\d{2})\]", b)
    if m:
        hh, mm, ss = (int(x) for x in m[-1])
        now = datetime.now()
        data_ts = time.mktime((now.year, now.month, now.day, hh, mm, ss, 0, 0, -1))
        if data_ts > time.time() + 120:      # 未来 ⇒ 视为昨天
            data_ts -= 86400
    fields = {"last": redact(last)[:70], "lines": len(lines)}
    return fields, {}, None, data_ts


def _p_hw8796(b):
    d = json.loads(b)
    fields = {"gpu.util": _get_path(d, "hw.gpu.util"), "gpu.mem_mb": _get_path(d, "hw.gpu.mem_used_mb"),
              "cpu.load1": _get_path(d, "hw.cpu.load1"), "mem_used_gb": _get_path(d, "hw.mem.used_gb"),
              "disk.pct": _get_path(d, "hw.disk.pct")}
    vals = {"gpu.util": _get_path(d, "hw.gpu.util"), "cpu.load1": _get_path(d, "hw.cpu.load1")}
    return fields, vals, None, _parse_ts_any(d.get("ts"))


def _p_engdb(b):
    d = json.loads(b)
    return {"ok": d.get("ok"), "tag": d.get("tag"), "built_at": d.get("built_at")}, {}, None, None


def _p_orin8792(b):
    d = json.loads(b)
    age = d.get("age_s")
    fields = {"n": d.get("n"), "age_s": age, "enc": d.get("enc"), "err": d.get("err")}
    return fields, {}, (float(age) if isinstance(age, (int, float)) else None), None


def _p_aoi(b):
    d = json.loads(b)
    fields = {"code": d.get("code"), "count": d.get("count"), "type": d.get("detect_type"),
              "n": d.get("n"), "ms": d.get("ms"), "verdict": d.get("verdict")}
    return fields, {}, None, _parse_ts_any(d.get("t"))


# ─────────────────────────── 端点清单 ───────────────────────────
def _agent_token():
    """agent_hub 的 token(逗号列表取第一个); 读不到则空串(会正常 403)。"""
    try:
        for line in open(SECRETS_FILE, encoding="utf-8"):
            if line.strip().startswith("ZMAX_AGENT_TOKEN"):
                return line.split("=", 1)[1].strip().split(",")[0]
    except Exception:
        pass
    return ""


def _build_catalog():
    ecs = "https://%s" % ECS_DOMAIN
    ov = "%s/ov/live.json?k=%s" % (ecs, OV_TOKEN)
    stp = "%s/st/station?k=%s" % (ecs, OV_TOKEN)
    sts = "%s/st/station/status?k=%s" % (ecs, OV_TOKEN)
    zs = "%s/zmax_status.json?k=%s" % (ecs, OV_TOKEN)
    s3 = "%s/ss3d_live.json?k=%s" % (ecs, OV_TOKEN)
    return [
        # ── ECS 大屏 / 公网 ──
        dict(name="ECS-OV只读通道清单", url=ov, owner=OWNER_ECS, kind="json", fresh="static",
             desc="tunnel_proxy 清单(流地址/相机名)", parse=_p_ov),
        dict(name="ECS工位总览页(station)", url=stp, owner=OWNER_PHONE, kind="html", fresh="static",
             desc="手机/浏览器打开的总览页", parse=_p_html_page),
        dict(name="ECS工位状态(station/status)", url=sts, owner=OWNER_ECS, kind="json", fresh="frame",
             desc="8793 的公网镜像(经反向隧道)", parse=_p_station),
        dict(name="ECS工厂大屏页(factory-dashboard)", url="%s/factory-dashboard.html" % ecs,
             owner=OWNER_ECS, kind="html", fresh="static",
             desc="产品大屏(fetch /api/relay/status + /orin/status)", parse=_p_html_page),
        dict(name="ECS状态总线(zmax_status.json)", url=zs, owner=OWNER_ECS, kind="json", fresh="ts",
             desc="hw(models+资源) 公网快照", parse=_p_zmax_status),
        dict(name="ECS-3D实况(ss3d_live.json)", url=s3, owner=OWNER_ECS, kind="json", fresh="ts",
             desc="3D 复刻/实况心跳+各相机", parse=_p_ss3d),
        dict(name="ECS中转(relay/status)", url="%s/api/relay/status" % ecs, owner=OWNER_ECS,
             kind="json", fresh="ts", desc="ECS 中转站(packages/latest)", parse=_p_relay),
        dict(name="ECS-Orin上行(relay/orin/status)", url="%s/api/relay/orin/status" % ecs,
             owner=OWNER_ORIN, kind="json", fresh="ts", desc="Orin 遥测(经 ECS 中转)", parse=_p_orin_relay),
        # ── 本机站点服务 ──
        dict(name="本机推流stats(8791)", url="http://127.0.0.1:8791/stats", owner=OWNER_LOCAL,
             kind="json", fresh="frame", desc="相机流健康(arm/local/local2)", parse=_p_stats8791),
        dict(name="本机工位页(8793/station)", url="http://127.0.0.1:8793/station", owner=OWNER_LOCAL,
             kind="html", fresh="static", desc="本机总览页", parse=_p_html_page),
        dict(name="本机工位状态(8793/station/status)", url="http://127.0.0.1:8793/station/status",
             owner=OWNER_LOCAL, kind="json", fresh="frame", desc="stats+ctl+aoi 聚合", parse=_p_station),
        dict(name="本机HIL(8795/hil/state)", url="http://127.0.0.1:8795/hil/state", owner=OWNER_LOCAL,
             kind="json", fresh="ts", desc="HIL 大脑快照+最近指示", parse=_p_hil),
        dict(name="本机agent_hub(8794/agent/log)", url="http://127.0.0.1:8794/agent/log?t=%s" % _agent_token(),
             owner=OWNER_LOCAL, kind="text", fresh="ts", desc="远程命令通道(最近执行)", parse=_p_agentlog),
        dict(name="本机硬件状态(8796/status/all)", url="http://127.0.0.1:8796/status/all",
             owner=OWNER_LOCAL, kind="json", fresh="ts", desc="GPU/CPU/内存/磁盘", parse=_p_hw8796),
        dict(name="本机工程库(8798/)", url="http://127.0.0.1:8798/", owner=OWNER_LOCAL, kind="json",
             fresh="static", desc="工程库只读 JSON(built_at)", parse=_p_engdb),
        # ── Orin ──
        dict(name="Orin取流状态(8792/status)", url="http://192.168.23.66:8792/status", owner=OWNER_ORIN,
             kind="json", fresh="frame", desc="臂相机取流 n/age_s/enc", parse=_p_orin8792),
        # ── 产线工控机 AOI ──
        dict(name="工控机AOI金手指(10082/last_result)", url="http://192.168.23.23:10082/last_result",
             owner=OWNER_IPC, kind="json", fresh="ts", desc="金手指检测最近一次结果", parse=_p_aoi),
        dict(name="工控机AOI表面(10083/last_result)", url="http://192.168.23.23:10083/last_result",
             owner=OWNER_IPC, kind="json", fresh="ts", desc="表面(壳体)检测最近一次结果", parse=_p_aoi),
    ]


# ─────────────────────────── 同源判定 ───────────────────────────
# fact → [(endpoint_name, vals_key, tol)]。tol 数值容差; None=严格相等; 'bool'=布尔一致。
SAME_SOURCE_FACTS = [
    ("臂相机帧率 fps", [
        ("本机推流stats(8791)", "arm.fps", 4.0),
        ("本机工位状态(8793/station/status)", "arm.fps", 4.0),
        ("ECS工位状态(station/status)", "arm.fps", 4.0),
        ("ECS-3D实况(ss3d_live.json)", "arm.fps", 4.0),
    ]),
    ("臂相机帧龄 age_s", [
        ("本机推流stats(8791)", "arm.age_s", 2.0),
        ("本机工位状态(8793/station/status)", "arm.age_s", 2.0),
        ("ECS-3D实况(ss3d_live.json)", "arm.age_s", 2.0),
    ]),
    ("臂相机在线", [
        ("本机推流stats(8791)", "arm.online", "bool"),
        ("本机工位状态(8793/station/status)", "arm.online", "bool"),
    ]),
    ("臂相机设备名(同一设备?)", [
        ("本机推流stats(8791)", "arm.label", None),
        ("本机工位状态(8793/station/status)", "arm.label", None),
    ]),
    ("工位机GPU利用率", [
        ("本机硬件状态(8796/status/all)", "gpu.util", 15.0),
        ("ECS状态总线(zmax_status.json)", "gpu.util", 15.0),
    ]),
]


def compute_same_source(results):
    """results: list of {name, ok, vals}. 返回 same_source 列表。"""
    by_name = {r["name"]: r for r in results}
    out = []
    for fact, specs in SAME_SOURCE_FACTS:
        srcs = []
        for nm, key, tol in specs:
            r = by_name.get(nm)
            if r is None:
                continue
            val = (r.get("vals") or {}).get(key)
            if r.get("ok") and val is not None:
                srcs.append({"name": nm, "value": val, "data_age_s": r.get("data_age_s")})
        consistent, note = None, ""
        tol0 = specs[0][2]
        if len(srcs) >= 2:
            # 新鲜度前置: 快照类指标(如 GPU 利用率)在源过期时不可比 —— 宁可说"不可比"也不说"一致"
            stale_src = [s["name"] for s in srcs
                         if isinstance(s.get("data_age_s"), (int, float)) and s["data_age_s"] > 10]
            vals = [s["value"] for s in srcs]
            if stale_src:
                note = "不可比: 源过期(>10s) — " + ", ".join(stale_src)
            elif tol0 == "bool":
                consistent = all(bool(v) == bool(vals[0]) for v in vals)
            elif all(isinstance(v, (int, float)) for v in vals):
                consistent = (max(vals) - min(vals)) <= (tol0 or 0.0)
            else:
                consistent = all(str(v) == str(vals[0]) for v in vals)
        out.append({"fact": fact, "sources": srcs, "consistent": consistent,
                    "tol": (tol0 if not isinstance(tol0, str) else tol0), "note": note})
    return out


# ─────────────────────────── 主流程 ───────────────────────────
def collect(eps):
    results = []
    for ep in eps:
        ok, status, body, err = _http_get(ep["url"])
        now = time.time()
        fields, vals, age_s, data_ts = {}, {}, None, None
        perr = ""
        if ok:
            try:
                fields, vals, age_s, data_ts = ep["parse"](body)
            except Exception as e:
                perr = "解析失败: %s: %s" % (type(e).__name__, e)
                ok = False
        # ── 新鲜度 ──
        if ep["fresh"] == "static":
            data_age, stale = None, False
        elif age_s is not None:
            data_age = round(float(age_s), 2)
            stale = data_age > STALE_S
        elif data_ts is not None:
            data_age = round(now - data_ts, 2)
            stale = data_age > STALE_S
        else:
            data_age, stale = None, False
        if data_ts is not None:
            try:
                fields = dict(fields)
                fields["数据时间"] = datetime.fromtimestamp(data_ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        if data_age is None and ep["fresh"] != "static":
            perr = (perr + " " if perr else "") + "无数据时间戳(无法判龄)"
        results.append({
            "name": ep["name"], "url": redact(ep["url"]), "owner": ep["owner"],
            "ok": bool(ok), "status": status, "data_age_s": data_age, "stale": bool(stale),
            "fields": redact_obj(fields), "err": redact((err + " " + perr).strip()),
            "_vals": vals,
        })
    return results


def build_report(results):
    same = compute_same_source([{"name": r["name"], "ok": r["ok"], "vals": r["_vals"]} for r in results])
    out = []
    for r in results:
        r = dict(r)
        r.pop("_vals", None)
        out.append(r)
    return {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "endpoints": out, "same_source": same}


def _fld_str(e):
    f = e["fields"]
    return f if isinstance(f, str) else _js(f)


def render_table(rep):
    lines = []
    lines.append("=" * 112)
    lines.append("Z-MAX 远程监控同源汇总   采集时间 %s   端点 %d 个   stale 阈值 >%.0fs"
                 % (rep["generated_at"], len(rep["endpoints"]), STALE_S))
    lines.append("=" * 112)
    lines.append("%-30s %-4s %-5s %-9s %-6s %s" % ("名称", "ok", "http", "数据龄", "stale", "关键字段"))
    lines.append("-" * 112)
    for e in rep["endpoints"]:
        age = "  --   " if e["data_age_s"] is None else ("%7.2fs" % e["data_age_s"])
        st = "STALE" if e["stale"] else ("--" if e["data_age_s"] is None else "ok")
        fld = _fld_str(e)
        if e["err"]:
            fld = (fld + " | err: " + e["err"]).strip(" |")
        lines.append("%-30s %-4s %-5s %-9s %-6s %s"
                     % (e["name"][:30], "OK" if e["ok"] else "ERR",
                        "" if e["status"] is None else e["status"], age, st, fld[:76]))
        lines.append("   └ %s   [%s]" % (e["url"], e["owner"]))
    lines.append("")
    lines.append("── 同源判定: 报告同一事实的多个端点是否一致  " + "─" * 50)
    for s in rep["same_source"]:
        tag = "一致 ✓" if s["consistent"] is True else \
              ("不一致 ✗ MISMATCH" if s["consistent"] is False else \
               ("不可比 ⏸" if s.get("note") else "样本不足(无法比对)"))
        if s.get("tol") is not None and tag.startswith("一致"):
            tag += " (容差 ±%s)" % s["tol"]
        srcs = "  ".join("%s=%s" % (x["name"].split("(")[0][:16], x["value"]) for x in s["sources"])
        lines.append("  [%-18s] %-22s %s" % (tag, s["fact"], srcs))
    lines.append("=" * 112)
    return "\n".join(lines)


def render_list(eps):
    lines = ["远程监控端点清单 (--list, 未实采)", "-" * 112]
    lines.append("%-30s %-16s %-5s %s" % ("名称", "归属", "kind", "source_url"))
    lines.append("-" * 112)
    for ep in eps:
        lines.append("%-30s %-16s %-5s %s" % (ep["name"][:30], ep["owner"][:16], ep["kind"],
                                              redact(ep["url"])))
        lines.append("      └ 期望字段: %s" % ep["desc"])
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 远程监控同源汇总")
    ap.add_argument("--list", action="store_true", help="只列端点清单, 不实采")
    ap.add_argument("--json", action="store_true", help="输出统一 JSON 到 stdout")
    ap.add_argument("--json-out", default="", help="把统一 JSON 写到文件")
    args = ap.parse_args()

    eps = _build_catalog()

    if args.list:
        print(redact(render_list(eps)))
        return 0

    results = collect(eps)
    rep = redact_obj(build_report(results))   # 再兜一层

    text = json.dumps(rep, ensure_ascii=False)
    okr, hits, nsec = assert_no_secrets(text)
    if not okr:
        rep = redact_obj(json.loads(redact(text)))
        text = json.dumps(rep, ensure_ascii=False)
        okr, hits, nsec = assert_no_secrets(text)
    sys.stderr.write("[redaction] 断言 %s: 已知口令 %d 个, 输出命中 %d 个\n"
                     % ("PASS" if okr else "FAIL", nsec, hits))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, ensure_ascii=False, indent=2))
        sys.stderr.write("[json-out] 已写 %s\n" % args.json_out)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    elif not args.json_out:
        print(render_table(rep))
    else:
        print("已写 %s (endpoints=%d)" % (args.json_out, len(rep["endpoints"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
