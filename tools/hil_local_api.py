#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hil_local_api.py — 🙋 HIL 人机在环 · **局域网本地 API** (手机 APP / 工位现场页用)

为什么要有它 (2026-09-27 老倪: 「veh.5.010 状态空间的 HIL 人机在环节点, 接入我的手机 APP,
从这个点我要通过 APP 跟状态空间交互, 人机在环」):
  原来的 HIL 链路是绕公网的: 桥每 N 秒 POST https://datadrive.world/api/relay/hil/state,
  网页 hil.html 读它、写回的指示再由桥取回。手机在现场连的是**局域网**, 再绕一圈公网没有意义;
  现场页(8791/room)需要本地就能读到状态、本地就能把人的指示交给**同一个大脑**。

**同一个大脑(关键)**: 本服务直接 import state_space/hil_bridge 的 build_snapshot / handle_instruction
  ⇒ 画布 n_hil 节点、datadrive 的 hil.html、手机 APP 三处看到的是**同一份状态**、**同一套指示处理**,
    红线也一并在同一个地方生效: 动作类指示一律拒答(只记为待授权), 真动只走 /ctl/* 那套两步授权+限时。

接口(只有 GET/POST, 只产出判读/建议/记录, 不产生任何机械臂动作):
  GET  /hil/state  → {"ok":1, "snapshot":{…}, "pause":bool, "instructions":[最近N条]}
  POST /hil/say    {"text":"…"} → {"ok":1, "reply":"…", "verdict":"…"}
  GET  /health     → {"ok":1, "hil":…}

终端接口 (静静/Hermes; 头 X-Zmax-Term: <token>, 仅回环/192.168.23.*/10.163.146.*;
  token 存 zmax_data/secrets/hil_term.token, 首启自动生成 0600):
  GET  /hil/term/state          → 一行现状(hint)+分层+画布+peers+最近指示+可用动词
  POST /hil/term/say   {"text","from","seq"} → 原样走 HB.handle_instruction; 动作类 refused_motion
  GET  /hil/term/log?n=20       → 最近 N 条指示 (读 reports/hil_instructions.jsonl)
  POST /hil/term/peer  {"name","kind","pid","note"}  ·  GET /hil/term/peers → 在线 peer(TTL 30s)
  GET  /hil/term/pose          → 实时位姿真值 + 距「金手指点1」mm + 控制器拖动态 (帧龄>2s/全0 ⇒ stale, 不编造)
  POST /hil/term/record_point  {"name","note"} → 复用 record_point_sdk 三道闸真采样 6 帧 → 过闸写示教点库
  (动词扩展: 「位置/在哪里/当前位姿」「记住安全点/记下来/标记这里」「拖动状态」; 动作类仍 refused_motion)
"""
import importlib.util
import hmac
import json
import math
import os
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/home/ubuntu/zmax"

# ⚠️ 必须按**文件路径**加载核心模块: 若直接 `import hil_bridge`, 从 tools/ 起进程时会先命中
#   tools/hil_bridge.py(只是 CLI 壳, 没有 build_snapshot/handle_instruction) ⇒ 运行时 AttributeError。
#   核心模块是纯 stdlib ⇒ 按路径加载最稳最快, 不用把 torch/lerobot 那条包 import 链拉起来。
_CORE = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/hil_bridge.py")
_spec = importlib.util.spec_from_file_location("zmax_hil_core", _CORE)
HB = importlib.util.module_from_spec(_spec)
sys.modules["zmax_hil_core"] = HB
_spec.loader.exec_module(HB)

PORT = int(os.environ.get("ZMAX_HIL_LOCAL_PORT", "8795"))
REPORTS = HB.REPORTS
INSTR_LOG = os.path.join(REPORTS, "hil_instructions.jsonl")
PAUSE_FLAG = os.path.join(REPORTS, "hil_pause.flag")
_LOCK = threading.Lock()
_LAST = {"ts": 0.0, "snap": None}

# ───────────────────── /hil/term/* 终端接口 (静静/Hermes) 门控 ─────────────────────
# 老倪要求(2026-10-09): 终端代理要能便宜读·带裁决写·可审计; 只在**同一个大脑**上加一层,
# 不另造一套 HIL。token 门控 + 网段限制; token 只在 zmax_data/secrets 下 (绝不入代码/日志)。
SECRETS_DIR = os.path.join(ROOT, "zmax_data", "secrets")
TERM_TOKEN_FILE = os.path.join(SECRETS_DIR, "hil_term.token")
TERM_TTL = 30.0                                       # peer 在线 TTL(秒)
ALLOWED_NET_PREFIX = ("192.168.23.", "10.163.146.")   # 回环另判
VERBS = ["状态", "停", "继续", "看画面", "标注", "去<点>", "计划<点>"]
_TOKEN_CACHE = {"v": None}


def _term_token():
    """读终端 token (只读, 绝不打印)。不存在 → ""。"""
    if _TOKEN_CACHE["v"]:
        return _TOKEN_CACHE["v"]
    try:
        with open(TERM_TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            _TOKEN_CACHE["v"] = t
            return t
    except Exception:                                                    # noqa: BLE001
        pass
    return ""


def _term_token_ensure():
    """启动时调用一次: token 不存在则生成 32B hex 写 0600。返回是否就绪。

    刻意与鉴权分离 ⇒ 未带/错 token 的请求**绝不**触发任何写(连 token 都不生成)。
    """
    if _term_token():
        return True
    try:
        os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True)
        t = secrets.token_hex(32)                                        # 32 bytes → 64 hex
        fd = os.open(TERM_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(t)
        _TOKEN_CACHE["v"] = t
        return True
    except Exception:                                                    # noqa: BLE001
        return False


def _ip_allowed(ip):
    """回环 + 指定局域网网段放行; 其它一律不放行"""
    if not ip:
        return False
    if ip in ("::1", "::ffff:127.0.0.1") or ip.startswith("127."):
        return True
    if ip.startswith("::ffff:"):
        ip = ip[len("::ffff:"):]
    return any(ip.startswith(p) for p in ALLOWED_NET_PREFIX)


def _instr_size():
    try:
        return os.path.getsize(INSTR_LOG)
    except OSError:
        return -1


def _term_hint(snap, paused, peers):
    """一行中文现状 (给终端直接念给用户)"""
    st = snap.get("stage") or "未上报"
    age = snap.get("frame_age_s")
    try:
        agetxt = ("%.0fs 前" % float(age)) if float(age) >= 0 else "无真机帧"
    except Exception:                                                    # noqa: BLE001
        agetxt = "无真机帧"
    ly = snap.get("layers") or {}
    off = [k for k, v in ly.items()
           if str((v or {}).get("status") if isinstance(v, dict) else v) != "active"]
    pn = ", ".join(str(p.get("name")) for p in peers) or "无"
    return ("阶段=%s · 真机帧 %s · 分层%s · 在线 peer: %s · %s"
            % (st, agetxt, ("全绿" if not off else ("离线:" + "/".join(off))), pn,
               ("已暂停" if paused else "运行中")))


def _term_layers(snap):
    """把 snapshot.layers 的 dict 压成 {L2:"active", ...} (终端要一眼看懂的形态)"""
    out = {}
    for k, v in (snap.get("layers") or {}).items():
        out[k] = (v.get("status") if isinstance(v, dict) else v)
    return out


def _snapshot(force=False):
    """带 2s 缓存的快照 (手机上页面 2~3 秒刷一次, 不必每次重算)"""
    with _LOCK:
        if not force and _LAST["snap"] and (time.time() - _LAST["ts"]) < 2.0:
            return _LAST["snap"]
    try:
        snap = HB.build_snapshot()["snapshot"]
    except Exception as e:                                          # noqa: BLE001
        snap = {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}
    with _LOCK:
        _LAST["snap"] = snap
        _LAST["ts"] = time.time()
    return snap


def _recent_instructions(n=20):
    out = []
    try:
        with open(INSTR_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:                                       # noqa: BLE001
                pass
    except Exception:                                               # noqa: BLE001
        pass
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 🤲 拖动示教捕捉 (只读位姿 + 记点)                     2026-10-09 老倪
#   老倪: 「从状态空间人机交互接口, 从金手指点1, 去到一个安全点, 手动拖拽」—
#   本段只做 看+记点, **绝不下发任何运动** (不 enableDrag/disableDrag/不改控制器模式)。
#   位姿真值同 pages 同源: rokae_tcp_sampler → zmax_data/rokae_sdk/tcp_out/latest.json。
#   记点复用 record_point_sdk 的**同一份三道闸** (帧龄 / 全 0 / 还在动), 不另造判据。
# ══════════════════════════════════════════════════════════════════════════════
TCP_SRC = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
TAUGHT_STORE = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
BASE_PT_NAME = "金手指点1"
POSE_MAX_AGE_S = 2.0        # 帧龄上限: 超过 ⇒ stale (与 record_point_sdk 同口径)
POSE_MIN_NORM_M = 1e-3     # 位置范数下限: 低于 ⇒ 典型"会话陈旧全 0"
CTL_STATUS_URL = "http://127.0.0.1:8793/ctl/status"

# 复用 record_point_sdk 的采样/判据 (按路径加载, 不复制一份判据出来)
_RPS_PATH = os.path.join(ROOT, "tools", "record_point_sdk.py")
_rps_spec = importlib.util.spec_from_file_location("zmax_record_point_sdk", _RPS_PATH)
RPS = importlib.util.module_from_spec(_rps_spec)
sys.modules["zmax_record_point_sdk"] = RPS
_rps_spec.loader.exec_module(RPS)


def _read_pose():
    """读位姿真值 → dict; 读不到/帧龄>2s/全 0 ⇒ stale=True + stale_why, pos/quat=None (**不编造**)。"""
    out = {"ok": False, "ts": None, "frame_age_s": None, "pos": None, "quat": None,
           "stale": True, "stale_why": "", "src": TCP_SRC}
    try:
        with open(TCP_SRC, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                                              # noqa: BLE001
        out["stale_why"] = "读位姿真值失败: %s: %s (%s)" % (type(e).__name__, e, TCP_SRC)
        return out
    try:
        ts = float(d.get("ts") or 0.0)
        pos = [float(d["x"]), float(d["y"]), float(d["z"])]
        quat = [float(d["qx"]), float(d["qy"]), float(d["qz"]), float(d["qw"])]
    except Exception as e:                                             # noqa: BLE001
        out["stale_why"] = "位姿字段解析失败: %s: %s" % (type(e).__name__, e)
        return out
    age = (time.time() - ts) if ts else 999.0
    norm = math.sqrt(sum(v * v for v in pos))
    out["ts"] = ts
    out["frame_age_s"] = round(age, 3)
    why = []
    if age > POSE_MAX_AGE_S:
        why.append("帧龄 %.2fs > %.1fs (采样器没在更新/陈旧)" % (age, POSE_MAX_AGE_S))
    if norm < POSE_MIN_NORM_M:
        why.append("位置范数 %.2e m ≈ 0 (会话陈旧全 0 坏值)" % norm)
    if why:
        out["stale_why"] = " · ".join(why)
        return out
    out.update({"ok": True, "pos": pos, "quat": quat, "stale": False, "stale_why": ""})
    return out


def _base_point(name=BASE_PT_NAME):
    """读示教点库里某个点位的 pos (只读) → {"name","pos"(或 None)}。"""
    try:
        with open(TAUGHT_STORE, encoding="utf-8") as f:
            d = json.load(f)
        p = (d.get("points") or {}).get(name) or {}
        pos = p.get("pos")
        if pos and len(pos) >= 3:
            return {"name": name, "pos": [float(v) for v in pos[:3]]}
    except Exception:                                                   # noqa: BLE001
        pass
    return {"name": name, "pos": None}


def _dist_mm(a, b):
    """两点欧氏距离 (mm); 任一缺 ⇒ None (不编)。"""
    if not a or not b or len(a) < 3 or len(b) < 3:
        return None
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a[:3], b[:3]))) * 1000.0


def _ctl_drag(timeout=2.5):
    """从 8793/ctl/status 读控制器 operation/mode/power; 拿不到 ⇒ 字段 None (不编)。"""
    out = {"operation": None, "mode": None, "power": None, "src": CTL_STATUS_URL}
    try:
        req = urllib.request.Request(CTL_STATUS_URL, headers={"User-Agent": "zmax-hil-local/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        rb = d.get("robot") or {}
        out["operation"] = rb.get("operation")
        out["mode"] = rb.get("mode")
        out["power"] = rb.get("power")
    except Exception as e:                                              # noqa: BLE001
        out["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return out


def _which_gate(rows, mean, spread_pos):
    """指出不过的是哪道闸 (与 record_point_sdk.vet 同判据)。"""
    age = (time.time() - (rows[-1].get("ts") or 0)) if rows else 999.0
    norm = math.sqrt(sum(v * v for v in mean[:3]))
    if age > RPS.MAX_AGE_S:
        return "帧龄(>2s)"
    if norm < RPS.MIN_NORM_M:
        return "全0坏值(范数≈0)"
    if spread_pos > RPS.MAX_SPREAD_M:
        return "还在动(pos极差>1e-4)"
    return "unknown"


def _do_record_point(name, note=""):
    """复用 record_point_sdk 三道闸真采样 6 帧; 过闸写示范教点库 (带 prev + 写前备份)。只读+写库, 零运动。"""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "name": name, "reason": "no_name", "why": "缺 name"}
    if not os.path.exists(RPS.SRC):
        return {"ok": False, "name": name, "reason": "no_src",
                "why": "读不到位姿真值源: %s (rokae_tcp_sampler 在跑吗?)" % RPS.SRC}
    try:
        rows = RPS.sample(6)                        # ← 真采样 6 帧 (record_point_sdk 本体)
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "name": name, "reason": "sample_exc",
                "why": "%s: %s" % (type(e).__name__, e)}
    mean, sp, sq = RPS.analyse(rows)
    ok, why = RPS.vet(rows, mean, sp, sq)           # ← record_point_sdk 的三道闸
    if not ok:
        return {"ok": False, "name": name, "reason": "gate", "gate": _which_gate(rows, mean, sp),
                "why": why,
                "measured": {"pos": [round(v, 7) for v in mean[:3]],
                             "spread_pos_m": sp, "spread_quat": sq,
                             "frame_age_s": round(time.time() - (rows[-1].get("ts") or 0), 2)}}
    try:
        with open(RPS.STORE, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:                                                   # noqa: BLE001
        store = {"version": "v1", "note": "L2 示教绝对点位", "frame": "base_link", "points": {}}
    store.setdefault("points", {})
    old = store["points"].get(name)
    backed_up_to = None
    if old:                                        # 写前备份 (回滚 = 反向 cp)
        try:
            os.makedirs(os.path.dirname(RPS.STORE), exist_ok=True)
            bak = "%s.bak_hilrec_%s_%s" % (RPS.STORE, name, time.strftime("%Y%m%d_%H%M%S"))
            shutil.copy2(RPS.STORE, bak)
            backed_up_to = bak
        except Exception:                                               # noqa: BLE001
            backed_up_to = None
    rec = {
        "pos": [round(v, 7) for v in mean[:3]],
        "quat": [round(v, 7) for v in mean[3:7]],
        "desc": str(note or ""),
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "HIL 拖动示教捕捉 (record_point_sdk 三道闸 → ROKAE SDK 直读 endInRef, 页面同源)",
        "frame": rows[-1].get("frame") or "base_link",
        "n_samples": len(rows),
        "spread_pos_m": round(sp, 8),
        "spread_quat": round(sq, 8),
        "via": "hil/term/record_point",
    }
    if old:
        rec["prev"] = old                          # 保旧值
    store["points"][name] = rec
    try:                                           # 原子写: 临时文件 + os.replace (半截 JSON 不会被读到)
        tmp = "%s.tmp.%d" % (RPS.STORE, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=1)
        os.replace(tmp, RPS.STORE)
        with open(RPS.STORE, encoding="utf-8") as f:      # 回读断言 (写没落地就报错)
            back = json.load(f)
        assert name in (back.get("points") or {}), "回读缺少点位 %s" % name
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "name": name, "reason": "write_failed",
                "why": "%s: %s" % (type(e).__name__, e)}
    return {"ok": True, "name": name, "pos": rec["pos"], "quat": rec["quat"],
            "n_samples": len(rows), "spread_pos_m": rec["spread_pos_m"],
            "recorded_at": rec["recorded_at"], "backed_up_to": backed_up_to}


def _next_safe_point_name(prefix="安全点"):
    """下一个安全点编号 (N 自增, 绝不覆盖已有)。"""
    try:
        with open(TAUGHT_STORE, encoding="utf-8") as f:
            pts = (json.load(f).get("points") or {})
    except Exception:                                                   # noqa: BLE001
        pts = {}
    n = 0
    for k in pts:
        m = re.match(r"^%s(\d+)$" % re.escape(prefix), str(k))
        if m:
            n = max(n, int(m.group(1)))
    return "%s%d" % (prefix, n + 1)


# ── 终端动词 (只读/记点; 动作类仍由 HB.handle_instruction 判 refused_motion) ──
_VERB_DRAG = ("拖动状态", "拖动态")
_VERB_RECORD = ("记住安全点", "记下来", "标记这里")
_VERB_POSE = ("位置", "在哪里", "当前位姿")


def _verb_pose_reply():
    pose, bp, drag = _read_pose(), _base_point(), _ctl_drag()
    if pose["stale"]:
        return ("⚠️ 位姿不可用 (陈旧/坏值): %s · 控制器 operation=%s mode=%s (未编造位姿)"
                % (pose["stale_why"] or "—", drag.get("operation"), drag.get("mode")), {})
    d = _dist_mm(pose["pos"], bp["pos"])
    p = pose["pos"]
    is_drag = (str(drag.get("operation")) == "drag")
    txt = ("📍 当前位姿 x=%.3f y=%.3f z=%.3f m · 距起点「%s」%s · 拖动模式: %s (operation=%s mode=%s) · 帧龄 %.2fs"
           % (p[0], p[1], p[2], bp["name"], ("%.1f mm" % d if d is not None else "—"),
              ("是" if is_drag else "否"), drag.get("operation"), drag.get("mode"),
              pose["frame_age_s"]))
    return txt, {"pos": pose["pos"], "d_mm": (round(d, 1) if d is not None else None)}


def _verb_record_reply():
    name = _next_safe_point_name()
    res = _do_record_point(name, "HIL 终端动词「记住安全点」")
    if res.get("ok"):
        bp = _base_point()
        d = _dist_mm(res["pos"], bp["pos"])
        txt = ("✅ 已记住 %s pos=(%.4f, %.4f, %.4f) · 距起点%s · 采样 %d 帧 (spread %.1e m)"
               % (name, res["pos"][0], res["pos"][1], res["pos"][2],
                  ("%.1f mm" % d if d is not None else "—"), res["n_samples"], res["spread_pos_m"]))
        return txt, {"name": name, "pos": res["pos"], "n_samples": res["n_samples"]}
    return ("❌ 未记住 %s: %s (闸=%s · 实测 %s)"
            % (name, res.get("why"), res.get("gate"),
               res.get("measured") or res.get("reason"))), {"name": name, "ok": False}


def _verb_drag_reply():
    pose, drag = _read_pose(), _ctl_drag()
    op = str(drag.get("operation"))
    state = "🖐 拖动中" if op == "drag" else ("⏸ 静止/非拖动" if drag.get("operation") else "未知")
    return ("🤲 拖动状态: %s · operation=%s mode=%s power=%s · 帧龄 %s s"
            % (state, drag.get("operation"), drag.get("mode"), drag.get("power"),
               pose["frame_age_s"])), {}


def _term_verb(text):
    """把只读/记点动词在本地答掉 (不下发任何动作)。返回 (handled, reply, verdict, extra)。"""
    t = (text or "").strip()
    if any(k in t for k in _VERB_DRAG):
        rep, extra = _verb_drag_reply()
        return True, rep, "drag_status", extra
    if any(k in t for k in _VERB_RECORD):
        rep, extra = _verb_record_reply()
        return True, rep, "record_point", extra
    if any(k in t for k in _VERB_POSE):
        rep, extra = _verb_pose_reply()
        return True, rep, "pose_read", extra
    return False, "", "", {}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "zmax-hil-local/1.0"

    def log_message(self, format, *args):  # noqa: A002                                  # 静音
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Zmax-Term")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _q(self):
        try:
            return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        except Exception:                                            # noqa: BLE001
            return {}

    def _term_guard(self):
        """终端接口门控: 网段 + token。放行返回 True; 否则已回 403(且**未改任何状态**)。

        顺序: 先判来源网段, 再判 token。任一不过 → 403, 不做任何写/计算副作用。
        """
        ip = (self.client_address[0] if self.client_address else "") or ""
        if not _ip_allowed(ip):
            self._send({"ok": 0, "err": "forbidden: source %s not allowed" % ip}, 403)
            return False
        tok = self.headers.get("X-Zmax-Term") or ""
        want = _term_token()
        if not want or not tok or not hmac.compare_digest(tok, want):
            self._send({"ok": 0, "err": "forbidden: bad or missing X-Zmax-Term"}, 403)
            return False
        return True

    def do_OPTIONS(self):                                            # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):                                                # noqa: N802
        p = self.path.split("?")[0].rstrip("/") or "/"
        if p == "/health":
            return self._send({"ok": 1, "hil": "local", "port": PORT, "reports": REPORTS})
        if p in ("/", "/hil/state", "/hil"):
            s = _snapshot()
            return self._send({"ok": 1, "ts": time.strftime("%F %T"),
                               "pause": os.path.isfile(PAUSE_FLAG),
                               "instructions": _recent_instructions(),
                               "snapshot": s})
        # ───────── 终端接口 (需要 token + 网段) ─────────
        if p == "/hil/term/state":
            if not self._term_guard():
                return
            s = _snapshot()
            paused = os.path.isfile(PAUSE_FLAG)
            peers = HB.peers_alive(TERM_TTL)
            return self._send({
                "ok": True, "ts": time.strftime("%F %T"),
                "stage": s.get("stage"), "frame_age_s": s.get("frame_age_s"),
                "layers": _term_layers(s), "canvas": s.get("canvas") or {},
                "paused": paused, "peers": peers,
                "last_instructions": _recent_instructions(5),
                "verbs": VERBS,
                "hint": _term_hint(s, paused, peers),
            })
        if p == "/hil/term/log":
            if not self._term_guard():
                return
            try:
                n = int((self._q().get("n") or ["20"])[0])
            except Exception:                                        # noqa: BLE001
                n = 20
            n = max(1, min(n, 200))
            items = _recent_instructions(n)
            return self._send({"ok": True, "n": len(items), "items": items,
                               "source": "reports/hil_instructions.jsonl"})
        if p == "/hil/term/peers":
            if not self._term_guard():
                return
            return self._send({"ok": True, "ttl": TERM_TTL, "peers": HB.peers_alive(TERM_TTL)})
        if p == "/hil/term/pose":
            if not self._term_guard():
                return
            pose = _read_pose()
            bp = _base_point()
            drag = _ctl_drag()
            d = _dist_mm(pose["pos"], bp["pos"])
            return self._send({
                "ok": True, "ts": time.strftime("%F %T"),
                "frame_age_s": pose["frame_age_s"], "pos": pose["pos"], "quat": pose["quat"],
                "stale": pose["stale"], "stale_why": pose["stale_why"],
                "base_pt": {"name": bp["name"], "pos": bp["pos"],
                            "d_mm": (round(d, 1) if d is not None else None),
                            "d_str": ("%.1f mm" % d if d is not None else "—")},
                "drag": {"operation": drag.get("operation"), "mode": drag.get("mode"),
                         "power": drag.get("power")},
                "src": {"pose": TCP_SRC, "base_pt": BASE_PT_NAME, "ctl": CTL_STATUS_URL},
            })
        return self._send({"ok": 0, "err": "no route %s" % p}, 404)

    def do_POST(self):                                               # noqa: N802
        p = self.path.split("?")[0].rstrip("/") or "/"
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:                                           # noqa: BLE001
            body = {}
        if p in ("/hil/say", "/say"):
            text = (body.get("text") or "").strip()
            if not text:
                return self._send({"ok": 0, "err": "空指示"}, 400)
            snap = _snapshot()
            try:
                reply, verdict = HB.handle_instruction(text, snap)
            except Exception as e:                                  # noqa: BLE001
                return self._send({"ok": 0, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}, 500)
            return self._send({"ok": 1, "ts": time.strftime("%F %T"), "text": text,
                               "reply": reply, "verdict": verdict})
        # ───────── 终端接口 (需要 token + 网段) ─────────
        if p == "/hil/term/say":
            if not self._term_guard():
                return
            text = (body.get("text") or "").strip()
            if not text:
                return self._send({"ok": 0, "err": "空指示"}, 400)
            seq = body.get("seq", 0)
            frm = str(body.get("from") or "hermes")
            # ① 只读/记点动词: 本地答掉 (绝不下发任何动作; 记点只用 record_point_sdk 三道闸)
            handled, vreply, vverdict, vextra = _term_verb(text)
            if handled:
                app = getattr(HB, "_append_instruction", None)
                if callable(app):
                    app({"ts": time.strftime("%F %T"), "text": text, "verdict": vverdict,
                         "from": frm, "seq": seq, "via": "term"})
                out = {"ok": True, "verdict": vverdict, "reply": vreply, "seq": seq,
                       "wrote_to": os.path.relpath(INSTR_LOG, ROOT)}
                if vextra:
                    out.update(vextra)
                return self._send(out)
            snap = _snapshot()
            before = _instr_size()
            try:
                reply, verdict = HB.handle_instruction(text, snap)     # 原样调用(红线在服务端)
            except Exception as e:                                  # noqa: BLE001
                return self._send({"ok": 0, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}, 500)
            # 动作类: handle_instruction 已返回 refused_motion 并记账; 其它裁决(如 status)大脑不落盘
            # ⇒ 此处补一条终端台账, 保证"每次终端 say 都留流水"。仅补, 不覆盖大脑记录。
            if _instr_size() <= before:
                app = getattr(HB, "_append_instruction", None)
                if callable(app):
                    app({"ts": time.strftime("%F %T"), "text": text, "verdict": verdict,
                         "from": frm, "seq": seq, "via": "term"})
            return self._send({"ok": True, "verdict": verdict, "reply": reply, "seq": seq,
                               "wrote_to": os.path.relpath(INSTR_LOG, ROOT)})
        if p == "/hil/term/peer":
            if not self._term_guard():
                return
            name = (body.get("name") or "").strip()
            if not name:
                return self._send({"ok": 0, "err": "缺 name"}, 400)
            rec = HB.register_peer(name, body.get("kind") or "", pid=body.get("pid"),
                                   note=body.get("note") or "", ttl=TERM_TTL)
            return self._send({"ok": True, "peer": rec, "peers": HB.peers_alive(TERM_TTL)})
        if p == "/hil/term/record_point":
            if not self._term_guard():
                return
            nm = (body.get("name") or "").strip()
            if not nm:
                return self._send({"ok": False, "err": "缺 name"}, 400)
            res = _do_record_point(nm, str(body.get("note") or ""))     # 只读+写库, 零运动
            return self._send(res)
        return self._send({"ok": 0, "err": "no route %s" % p}, 404)


def main():
    _ready = _term_token_ensure()                       # 启动即确保 token 就绪(鉴权请求永不触发写)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("🙋 HIL 本地 API 在听 0.0.0.0:%d (同一个大脑: %s)" % (PORT, HB.__file__), flush=True)
    print("🔑 终端门控 token: %s (%s; 取值: cat 该文件 · 绝不入日志)"
          % (os.path.relpath(TERM_TOKEN_FILE, ROOT),
             "0600 已就绪" if _ready else "⚠️ 生成失败"), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
