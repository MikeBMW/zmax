#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📈 Graphic 信号分析 (对标 Vector CANoe 的 Analysis → Graphic 窗口)

一比一复刻 CANoe Graphic 的核心能力, 数据源换成 Z-MAX 的真实链路:
  * 信号目录 (CANoe 左侧属性栏): 任意数据源的任意数值字段, 列 = 信号名/当前值/Min/Max/帧龄
  * 波形窗口: 多信号同图 (颜色区分) / 每信号独立图 / 每信号独立 Y 轴
  * 测量光标 + 差分光标 (Δt 与各信号 Δv)
  * 暂停 (只暂停打印, 继续记录) · Fit Signals · X 缩放/平移 · 网格 · 采样点 · 高亮加粗
  * 时间轴配置 (时间窗/起始) · 使用某信号作 X 轴 (X-Y 曲线)
  * Signal Logging: 记录到 CSV → 可 Import 回放 · 导出 CSV / PNG

数据源 (真链路, 无造假):
  1. 本机真值流: 轮询 zmax_data/**.json (位姿真值 latest.json @50Hz 等), 数值字段自动展开
  2. Orin ROS2 话题: ssh + tools/zmax_topic_sampler.py, rclpy 订阅任意话题任意数值字段

时间基准: 横轴统一用**本机 monotonic**秒 (跨源可对齐); 每个信号另带"源侧帧龄"
(本机源=文件 mtime 龄; ROS 源=Orin 侧最后收包龄), 界面上标出来, 不冒充新鲜。
"""

import csv
import json
import os
import re
import subprocess
import sys
import threading
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QPushButton, QSizePolicy, QSplitter,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import numpy as np
import pyqtgraph as pg

# ── 与 studio 同色系 ─────────────────────────────────────────
C_BG = "#0d1117"
C_BG2 = "#161b22"
C_BORDER = "#30363d"
C_WHITE = "#e6edf3"
C_DIM = "#8b949e"
C_GREEN = "#3fb950"
C_ORANGE = "#f0883e"
C_RED = "#f85149"
C_BLUE = "#58a6ff"
C_PURPLE = "#bc8cff"

# CANoe 式曲线配色 (12 色循环, 颜色区分信号)
TRACE_COLORS = ["#4FC3F7", "#FFB74D", "#81C784", "#F06292", "#BA68C8", "#4DD0E1",
                "#FFD54F", "#E57373", "#A1887F", "#90A4AE", "#AED581", "#7986CB"]

CAP = 200000          # 每信号环形缓冲容量 (点数)
HOST_POLL_HZ = 50     # 本机文件源轮询频率
# ▶ 3D 场景播放进度真源 (与 ss_dreamview.publish_trace_live 同一份: 帧/总帧/场景时刻 时间_s/时刻 ts)
PLAYBACK_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "zmax_data", "ss_live", "trace_live.json")
UI_FPS = 20           # 界面刷新率

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # …/zmax
if os.path.basename(ROOT) == "gui":
    ROOT = os.path.dirname(ROOT)
SAMPLER = os.path.join(ROOT, "tools", "zmax_topic_sampler.py")
SAMPLER_REMOTE = "/tmp/zmax_topic_sampler.py"
ORIN = "tashan@192.168.23.66"
LOG_DIR = os.path.join(ROOT, "zmax_data", "graphic_logs")
CATALOG_CACHE = os.path.join(LOG_DIR, "topic_catalog.json")   # 话题目录缓存 ⇒ 一进页面就有名字
# 🌐 全局数据空间 (DDS) — 与「数据空间」页同一份真源: busdb=DBC, live=话题质量, trace=总线帧
DS_DIR = os.path.join(ROOT, "zmax_data", "dataspace")
DS_TRACE = os.path.join(DS_DIR, "trace.jsonl")
DS_LIVE = os.path.join(DS_DIR, "live.json")
DS_BUSDB = os.path.join(DS_DIR, "busdb.json")

# 本机真值流默认源 (存在才启)
# 🥽 2026-10-12 老倪: 「每个场景对应不同的信号分析…信号分析主窗口的信号是有目标场景的, 你得标记出来;
#   信号分析也用 绿色 蓝色 紫色 代表对应不同的场景; 要有排序功能, 按 绿/蓝/紫/白 排列, 白=所有颜色的信号都显示,
#   没有分类的信号都是白色」 ⇒ 标签真源 = tools/sig_scene_tags.py(颜色/任务映射又来自 tools/ss_scene_switch.py, 不重写)。
SCENE_SORT_WHITE = "#ffffff"
SCENE_SORT_ITEMS = (("⚪ 全部(白)", "", SCENE_SORT_WHITE), ("🟢 插拔", "插拔场景", "#2e8b57"),
                    ("🔵 摆盘", "摆盘场景", "#1f6feb"), ("🟣 AR", "AR场景", "#8957e5"))
# 场景色 (与 tools/ss_scene_switch.py 同一份真值: 插拔绿 / 摆盘蓝 / AR 紫; 未分类=白)
SCENE_COLORS = {"插拔场景": "#2e8b57", "摆盘场景": "#1f6feb", "AR场景": "#8957e5",
                "基础场景": "#ffffff", "未分类": "#ffffff"}
# 信号目录的四个场景组 (老倪 2026-10-12: 「绿色场景标题改成 插拔场景; 摆盘应该是蓝色; 其它无法分类的
#   信号定义为基础场景, 用白色显示 topic」) —— 顺序 = 色序, 标题直接写场景名 + 数据来源, 不再叫「3D 场景实时数据」
SCENE_GROUPS = (
    ("插拔场景", "🟢 插拔场景 · 状态空间引擎轨迹 + 力控/夹持 (trace_live.json · force_torque · gripper_pos)"),
    ("摆盘场景", "🔵 摆盘场景 · 取放 / 料盘 / 真空 (pick & place)"),
    ("AR场景",   "🥽 AR 场景 · 空间点位 / AOI 话题 (ar_aoi_live.json)"),
    ("基础场景", "⚪ 基础场景 · 未分类信号 (真机位姿 / 安全 / YOLO / 空间点 / ROS / DDS 遥测)"),
)


def _scene_tags_mod():
    """加载 信号→场景 标签真源; 任何异常都返回 None(页面照常可用, 只是不标色)。"""
    try:
        import importlib.util
        p = os.path.join(ROOT, "tools", "sig_scene_tags.py")
        _spec = importlib.util.spec_from_file_location("zmax_sig_scene_tags", p)
        _m = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_m)
        return _m
    except Exception:                                                         # noqa: BLE001
        return None


SST = _scene_tags_mod()


HOST_SOURCES = [
    ("pose",    "zmax_data/rokae_sdk/tcp_out/latest.json"),
    ("state",   "zmax_data/rokae_sdk/tcp_out/state.json"),
    ("safety",  "zmax_data/vl_safety_fast.json"),
    ("yolo",    "zmax_data/ss_bypass/yolo_detections.json"),
    ("space",   "zmax_data/dataspace/live.json"),
    # 状态空间工程实况 (引擎轨迹快照 = 3D 场景面板屏幕上的同一批数字; 单一真源)
    ("sstrace", "zmax_data/ss_live/trace_live.json"),
    # 🔴 2026-10-15 老倪「信号分析, 主窗口, 没有波形信号啊」: trace_live.json 的唯一发布者是 3D 面板,
    #   3D 不播放 ⇒ 每键只有 1 个样本 ⇒ 画不出线。这一路是**常驻引擎回路**的真值帧流(10Hz, 由
    #   tools/ss_fw_trace_pub.py 从 engine_latest.json 搬运: φ/梯度/耗时/置信/内稳态/潜表示/动作调制),
    #   与 3D 是否在播无关 ⇒ 波形恒有数据。schema 同 trace_live(ts + 时间_s ⇒ 按场景时刻铺点)。
    ("sseng", "zmax_data/ss_live/engine_trace.json"),
    # 🥽 AR 场景 · 空间点位 + AOI 话题 (老倪 2026-10-11: 「信号分析对应 AR 场景下的所有空间点位置」;
    #    真源 = 机器人 TCP 真值 / 示教点位台账 / RealSense 服务 8797 / 工控机 AOI 10082 / 画布节点 🔍 光学质量检测;
    #    单一写入器 = tools/ar_aoi_bus.py, 注册表 config/topics/ar_aoi_signals.json)
    ("ar", "zmax_data/ar_live/ar_aoi_live.json"),
]

ORIN_ENV = ("source /opt/ros/humble/setup.bash; "
            "for w in /home/tashan/0810/*/install/setup.bash; do [ -f \"$w\" ] && source \"$w\" && break; done; "
            "export ROS_DOMAIN_ID=0 FASTDDS_BUILTIN_TRANSPORTS=UDPv4 ROS_LOCALHOST_ONLY=0; ")


_DS_TUPLE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_\.]*(?:\[\d+\])?)\s*=\s*\(([^)]*)\)")
_DS_SCALAR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_\.]*(?:\[\d+\])?)\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


def parse_ds_digest(d):
    """🌐 数据空间总线帧的 digest → {字段: 数值}。三种真实形态都要吃:

    ① 正常 JSON 对象 (zmax/heartbeat)
    ② **被截断的 JSON** (zmax/ss_diag: 源侧按定长截断, 缺右括号) → 补括号后解析, 只取完整的键值对
    ③ 人读文本 (zmax/ss_state: `tcp=(-1.0,-1.0,-1.0) frame_age=0.07s`) → 抠出 name=数字 / name=(数字,..)
    解析不出的部分一律不产出 (不编造)。
    """
    if isinstance(d, dict):
        return flatten_json(d, cap=48)
    if not isinstance(d, str) or not d.strip():
        return {}
    s = d.strip()
    if s.startswith("{"):
        for cand in (s, s + "}" * max(0, s.count("{") - s.count("}"))):
            try:
                o = json.loads(cand)
                if isinstance(o, dict):
                    return flatten_json(o, cap=48)
            except Exception:
                pass
    out = {}
    spans = []
    for m in _DS_TUPLE_RE.finditer(s):
        name, body = m.group(1), m.group(2)
        spans.append(m.span())
        vals = [v.strip() for v in body.split(",")]
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except Exception:
                nums = []
                break
        if nums:
            if len(nums) == 1:
                out[name] = nums[0]
            else:
                for i, v in enumerate(nums):
                    out[f"{name}.{i}"] = v
    for m in _DS_SCALAR_RE.finditer(s):
        if any(a <= m.start() < b for a, b in spans):
            continue
        try:
            out[m.group(1)] = float(m.group(2))
        except Exception:
            pass
    return out


def flatten_json(d, prefix="", out=None, depth=0, cap=64):
    """把 JSON 里的数值叶子展平成 {key: float} (索引列表用 0/1/2 下标)"""
    if out is None:
        out = {}
    if depth > 3 or len(out) >= cap:
        return out
    if isinstance(d, dict):
        for k, v in d.items():
            flatten_json(v, f"{prefix}{k}.", out, depth + 1, cap)
    elif isinstance(d, (list, tuple)):
        for i, v in enumerate(list(d)[:16]):
            flatten_json(v, f"{prefix}{i}.", out, depth + 1, cap)
    elif isinstance(d, bool):
        out[prefix.rstrip(".")] = 1.0 if d else 0.0
    elif isinstance(d, (int, float)):
        out[prefix.rstrip(".")] = float(d)
    return out


class SignalBuffer:
    """单条曲线的环形缓冲 (numpy 预分配, 供 pyqtgraph setData 直接用视图)"""

    __slots__ = ("key", "t", "v", "n", "head", "color", "bold", "x_axis_of",
                 "last_val", "vmin", "vmax", "age", "wall", "src", "scene")

    def __init__(self, key, color=None, src=""):
        self.key = key
        self.t = np.zeros(CAP, dtype=np.float64)
        self.v = np.zeros(CAP, dtype=np.float64)
        self.n = 0
        self.head = 0
        self.color = color or TRACE_COLORS[0]
        self.bold = 2
        self.x_axis_of = False
        self.last_val = None
        self.vmin = None
        self.vmax = None
        self.age = -1.0
        self.wall = 0.0
        self.src = src
        self.scene = False        # True = x 是"场景时刻"(回放进度), 不是到达时刻 ⇒ 按 x 排序画

    def push(self, t, v, age=-1.0):
        i = self.head
        self.t[i] = t
        self.v[i] = v
        self.head = (i + 1) % CAP
        if self.n < CAP:
            self.n += 1
        self.last_val = v
        self.age = age
        self.wall = time.time()
        if self.vmin is None or v < self.vmin:
            self.vmin = v
        if self.vmax is None or v > self.vmax:
            self.vmax = v

    def arrays(self):
        if self.n < CAP:
            t, v = self.t[:self.n], self.v[:self.n]
        else:
            i = self.head
            t = np.concatenate((self.t[i:], self.t[:i]))
            v = np.concatenate((self.v[i:], self.v[:i]))
        if self.scene and len(t) > 1:
            # 🎬 回放场景时刻作 x: 拖滑条往回走会写入更小的 x ⇒ 按 x 排序, 曲线才是单值函数、不成锯齿
            o = np.argsort(t, kind="stable")
            t, v = t[o], v[o]
        return t, v

    def clear(self):
        self.n = 0
        self.head = 0
        self.vmin = self.vmax = None
        self.last_val = None


class SignalStore:
    """线程安全的多源信号仓库"""

    def __init__(self):
        self.lock = threading.Lock()
        self.bufs = {}
        self.t0 = time.time()          # 🌍 统一用 epoch: 波形 x = t - t0 ⇒ 能换算回绝对时刻
        self.total_pts = 0

    def get(self, key, src=""):
        b = self.bufs.get(key)
        if b is None:
            with self.lock:
                b = self.bufs.get(key)
                if b is None:
                    b = SignalBuffer(key, TRACE_COLORS[len(self.bufs) % len(TRACE_COLORS)], src)
                    self.bufs[key] = b
        return b

    def push(self, key, t, v, age=-1.0, src=""):
        b = self.get(key, src)
        with self.lock:
            b.push(t, v, age)
            self.total_pts += 1

    def push_many(self, values, t, ages=None, src="", scene=False):
        ages = ages or {}
        with self.lock:
            for k, v in values.items():
                b = self.bufs.get(k)
                if b is None:
                    b = SignalBuffer(k, TRACE_COLORS[len(self.bufs) % len(TRACE_COLORS)], src)
                    self.bufs[k] = b
                a = ages.get(k, -1.0) if ages else -1.0
                if scene:
                    b.scene = True          # 🎬 该信号 x 轴 = 场景时刻 (回放进度)
                b.push(t, v, a)
                self.total_pts += 1

    def keys(self, src=None):
        with self.lock:
            ks = list(self.bufs.keys())
        if src:
            ks = [k for k in ks if self.bufs[k].src == src]
        return sorted(ks)

    def clear(self):
        with self.lock:
            for b in self.bufs.values():
                b.clear()
            self.total_pts = 0


# ─────────────────────────────────────────────────────────────
# 数据源线程
# ─────────────────────────────────────────────────────────────
class HostJsonSource(threading.Thread):
    """本机真值流: 轮询 JSON 文件, mtime 变了才解析 (50Hz)"""

    def __init__(self, store, sources):
        super().__init__(daemon=True)
        self.store = store
        self.sources = [(p, os.path.join(ROOT, rel)) for p, rel in sources]
        self._stop = threading.Event()
        self.rate = 0.0
        self._cnt = 0

    def stop(self):
        self._stop.set()

    def run(self):
        last_mtime = {}
        while not self._stop.is_set():
            t_start = time.monotonic()
            for prefix, path in self.sources:
                if self._stop.is_set():
                    break
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if last_mtime.get(path) == st.st_mtime:
                    continue
                last_mtime[path] = st.st_mtime
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                except Exception:
                    continue
                # 🥽 AR/AOI 源(ar_aoi_live.json): 它的信号表就在 `s` 里(86 条), 而且 groups 的组名就是信号名
                #   ⇒ 直接取 s 的键, 不走 flatten。**踩过的坑**: flatten_json 有 48 键上限, 原来 AR 的 86 条
                #   只进来 48 条(老倪: 「AR场景的信号呢?」), 且键名前缀会多出 "s."(组名对不上, 全掉进"其它信号")。
                if prefix == "ar" and isinstance(raw.get("s"), dict):
                    _meta = ("ts", "t", "age", "meta", "groups", "schema")     # 元数据不是信号, 别混进目录
                    vals = {str(k): v for k, v in raw["s"].items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)
                            and str(k).split(".")[0] not in _meta}
                else:
                    vals = flatten_json(raw, "", {}, 0, 48)
                age = max(0.0, time.time() - st.st_mtime)      # 源侧帧龄 = 文件写龄
                # 🕒 时间戳口径: 源侧自带的 ts 优先 (trace_live.json = 3D 面板那一帧的时刻),
                # 这样波形标记线上的时刻 == 3D 场景 HUD 上的时刻, 才能一一对应核对。
                _ts = raw.get("ts") if isinstance(raw, dict) else None
                # 🎬 3D 场景快照: x 用"场景时刻" (时间_s) ⇒ 波形横轴 = 回放进度, 拖进度条游标能左右走
                _st = raw.get("时间_s") if isinstance(raw, dict) else None
                _scene = isinstance(_st, (int, float)) and isinstance(_ts, (int, float))
                now = float(_st) if _scene else (float(_ts) if isinstance(_ts, (int, float)) else time.time())
                keys = {f"{prefix}.{k}": v for k, v in vals.items()}
                self.store.push_many(keys, now, {k: age for k in keys}, src=prefix, scene=_scene)
                self._scene_epoch = (float(_ts) - float(_st)) if _scene else None   # 场景时刻→epoch 偏移
                self._cnt += 1
            dt = time.monotonic() - t_start
            if dt < 1.0 / HOST_POLL_HZ:
                time.sleep(1.0 / HOST_POLL_HZ - dt)


class RosTopicSource(threading.Thread):
    """Orin ROS2 话题: ssh 常驻采样器 (rclpy, 任意话题任意数值字段)"""

    def __init__(self, store, topics):
        super().__init__(daemon=True)
        self.store = store
        self.topics = list(topics)          # ["/topic:type", ...]
        self._stop = threading.Event()
        self.proc = None
        self.state = "未启动"
        self.rate = 0.0
        self._cnt = 0
        self._lines = 0

    def stop(self):
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def run(self):
        if not self.topics:
            self.state = "未选话题"
            return
        self._deploy()
        args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                "-o", "ServerAliveInterval=10", ORIN]
        inner = ORIN_ENV + " python3 -u " + SAMPLER_REMOTE + " watch --rate 20 "
        inner += " ".join(f"--topic {t}" for t in self.topics)
        cmd = args + [inner]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         text=True, bufsize=1)
        except Exception as e:
            self.state = f"启动失败: {e}"
            return
        try:
            for line in self.proc.stdout:
                if self._stop.is_set():
                    break
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                raw = d.get("s") or {}
                ages = d.get("age") or {}
                if not raw:
                    self.state = "已连 Orin · 话题无发布者"
                    continue
                # key 必须和信号栏一致: "ros." + 话题(去前导斜杠) + "." + 字段
                vals = {("ros." + k.lstrip("/")): v for k, v in raw.items()}
                per_age = {}
                for k in vals:
                    rest = k[len("ros."):]
                    for topic, a in ages.items():
                        if rest.startswith(topic.lstrip("/") + "."):
                            per_age[k] = a
                            break
                self._lines += 1
                self.store.push_many(vals, time.time(), per_age, src="ros")
                if self._lines == 1:
                    self.state = "采样中"
        finally:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            if not self._stop.is_set():
                self.state = "连接断开"

    def _deploy(self):
        """把采样器推到 Orin (内容一致就跳过)"""
        try:
            local = open(SAMPLER, "rb").read()
        except OSError:
            return
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ORIN,
                            f"md5sum {SAMPLER_REMOTE} 2>/dev/null | cut -d' ' -f1"],
                           capture_output=True, text=True, timeout=15)
        import hashlib
        if r.stdout.strip() == hashlib.md5(local).hexdigest():
            return
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", SAMPLER, f"{ORIN}:{SAMPLER_REMOTE}"],
                       timeout=30)


class CatalogWorker(threading.Thread):
    """刷新 Orin 话题目录 (话题 → 数值字段)"""

    def __init__(self, on_done):
        super().__init__(daemon=True)
        self.on_done = on_done

    def run(self):
        try:
            cmd = ["timeout", "40", "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", ORIN,
                   ORIN_ENV + f" python3 -u {SAMPLER_REMOTE} discover"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=70)
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    self.on_done(json.loads(line), None)
                    return
            self.on_done(None, "目录为空")
        except Exception as e:
            self.on_done(None, str(e))


def clock_str(epoch, ms=True):
    """epoch → 本地时刻字符串。⚠️ ss_dreamview.clock_str 必须与本函数一字不差 (老倪要两边对时刻)。"""
    try:
        e = float(epoch)
    except Exception:
        return "—"
    s = time.strftime("%H:%M:%S", time.localtime(e))
    if not ms:
        return s
    return "%s.%03d" % (s, int((e - int(e)) * 1000) % 1000)


class ClockAxis(pg.AxisItem):
    """底部时间轴: 可在"相对秒"与"绝对时刻"之间切换 (对着 3D 场景 HUD 的时刻看)"""

    def __init__(self, *a, **kw):
        self.store = None                # 由 WaveArea 建图时注入 (pyqtgraph 要 instance 且要 orientation)
        super().__init__(*a, **kw)
        self.abs_on = False
        self.epoch_base = None           # 场景时刻轴用: epoch = epoch_base + x (否则用 store.t0 + x)

    def tickStrings(self, values, scale, spacing):
        if not self.abs_on:
            return [("%.3g" % v) for v in values]
        base = self.epoch_base if self.epoch_base is not None else self.store.t0
        out = []
        for v in values:
            sec = base + float(v)
            lt = time.localtime(sec)
            if spacing < 1.0:
                out.append("%s.%03d" % (time.strftime("%H:%M:%S", lt),
                                        int((sec - int(sec)) * 1000) % 1000))
            else:
                out.append(time.strftime("%H:%M:%S", lt))
        return out


# ─────────────────────────────────────────────────────────────
# 波形区
# ─────────────────────────────────────────────────────────────
class WaveArea(QWidget):
    """CANoe 波形窗口: 3 种 Y 轴显示模式"""

    MODE_SHARED, MODE_MULTI, MODE_SINGLE = 0, 1, 2

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.mode = self.MODE_SHARED
        self.items = {}          # key -> PlotDataItem
        self.extra_vbs = {}      # key -> ViewBox (多轴模式)
        self.curves = []         # 当前要画的 key
        self.show_points = False
        self.grid = True
        pg.setConfigOptions(antialias=False)
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(C_BG2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.glw)
        self.main_plot = None
        self.plots = []          # 当前所有子图 (每信号独立图时不止一张)
        self.c1 = self.c2 = None
        self.cursor_on = False
        self.diff_on = True
        self.cursor_cb = None
        self.pin_cb = None       # 点波形打标记时回调(上报时刻)
        self.abs_on = False      # 时间轴: 相对秒 / 绝对时刻
        self.pb = None           # ▶ 3D 场景播放状态 {帧,总帧,时间_s,ts,age} — 驱动播放游标
        self._pb_last = None     # ▶ 3D **停在**的那一帧 (播放中持续记) ⇒ 停止后竖线留在这一刻, 不消失
        self.marks = []          # 🕒 最新时刻标记线 (每张子图一根)
        self.mark_lb = None
        self.pins = []           # 📌 手动标记线
        self.pin_lb = None
        self._rebuild(force=True)

    def _clock_axes(self):
        ax = ClockAxis(orientation="bottom")
        ax.store = self.store
        return {"bottom": ax}

    def _label_y(self):
        """标记文字的 y: 贴在本图可见区顶部 (anchor=(0,1) ⇒ 文字往下挂, 不会被裁)"""
        p = self.plots[0] if self.plots else None
        try:
            _y0, _y1 = p.getViewBox().viewRange()[1]
            return float(_y0) + (float(_y1) - float(_y0)) * 0.99
        except Exception:                                                      # noqa: BLE001
            return 0.0

    def _make_markers(self):
        """🕒 时间戳标记线(最新) + 📌 手动标记(点一下打在波形上)。
        老倪 2026-10-11: 要和 3D 场景一一对应 ⇒ 两边显示的必须是同一个时刻。"""
        self.marks, self.pins = [], []
        self.mark_lb = self.pin_lb = None
        for i, p in enumerate(self.plots):
            try:
                mk = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen("#ffb86c", width=1.4, style=Qt.DashLine))
                mk.setZValue(60)
                p.addItem(mk, ignoreBounds=True)
                self.marks.append(mk)
                if i == 0:
                    self.mark_lb = pg.TextItem(anchor=(0, 1), color="#ffb86c")
                    self.mark_lb.setZValue(62)
                    p.addItem(self.mark_lb, ignoreBounds=True)
                pn = pg.InfiniteLine(angle=90, movable=True,
                                     pen=pg.mkPen("#4dd0e1", width=1.3))
                pn.setZValue(58)
                pn.setVisible(False)
                p.addItem(pn, ignoreBounds=True)
                self.pins.append(pn)
                if i == 0:
                    self.pin_lb = pg.TextItem(anchor=(0, 1), color="#4dd0e1")
                    self.pin_lb.setZValue(59)
                    self.pin_lb.setVisible(False)
                    p.addItem(self.pin_lb, ignoreBounds=True)
            except Exception:                                                  # noqa: BLE001
                pass
        if self.main_plot is not None:
            try:
                self.main_plot.scene().sigMouseClicked.connect(self._on_plot_click)
            except Exception:                                                  # noqa: BLE001
                pass

    def _epoch_of(self, x):
        """x(轴坐标) → 绝对时刻: 场景时刻轴用快照的 (ts - 时间_s) 偏移反算, 其它源用 store.t0。"""
        pb = self.pb or {}
        _scene = any((self.store.bufs.get(k) is not None and self.store.bufs[k].scene)
                     for k in self.curves)
        if _scene and pb.get("ts") is not None and pb.get("t_s") is not None:
            return float(pb["ts"]) - float(pb["t_s"]) + float(x)
        return self.store.t0 + float(x)

    def pin_at(self, x, notify=True):
        """在波形 x 处打一个时刻标记 (试: 老倪点一下就要看到那一点的绝对时刻)"""
        if not self.pins:
            return None
        for pn in self.pins:
            pn.setPos(float(x))
            pn.setVisible(True)
        clock = clock_str(self._epoch_of(float(x)))
        if self.pin_lb is not None:
            self.pin_lb.setText("📌 %s" % clock)
            self.pin_lb.setPos(float(x), self._label_y())
            self.pin_lb.setVisible(True)
        if notify and self.pin_cb:
            try:
                self.pin_cb(float(x), clock)
            except Exception:                                                  # noqa: BLE001
                pass
        return clock

    def clear_pins(self):
        for pn in self.pins:
            pn.setVisible(False)
        if self.pin_lb is not None:
            self.pin_lb.setVisible(False)

    def _on_plot_click(self, ev):
        try:
            if ev.button() != Qt.LeftButton or ev.double():
                return
            for p in self.plots:
                if p.sceneBoundingRect().contains(ev.scenePos()):
                    x = p.getViewBox().mapSceneToView(ev.scenePos()).x()
                    self.pin_at(x)
                    return
        except Exception:                                                      # noqa: BLE001
            pass

    def set_abs_axis(self, on):
        """时间轴切绝对时刻 (对着 3D HUD 时刻看是否一一对应)"""
        self.abs_on = bool(on)
        for p in self.plots:
            for name in ("bottom",):
                ax = p.getAxis(name)
                if isinstance(ax, ClockAxis):
                    ax.abs_on = self.abs_on
                    ax.picture = None                      # 强制重算刻度文字
            p.setLabel("bottom", "时间 (绝对时刻)" if self.abs_on else "时间 (s)", color=C_DIM)
        self._refresh_marks()

    def set_playback(self, pb):
        """▶ 3D 场景的播放进度 (拖 3D 进度条 → 这里的竖线跟着左右移动)"""
        self.pb = pb
        self._refresh_marks()

    def _refresh_marks(self):
        """🕒 播放游标/最新标记线定位 + 写上那一刻 (场景时刻 & 绝对时刻)。"""
        if not self.marks:
            return
        pb = self.pb or {}
        scene_x = pb.get("t_s") if (pb.get("fresh") and pb.get("t_s") is not None) else None
        # 轴向标签/时刻换算: 场景时刻轴要能反算绝对时刻 (epoch = ts - 场景时刻 + x)
        try:
            _off = (float(pb["ts"]) - float(pb["t_s"])
                    if (pb.get("ts") is not None and pb.get("t_s") is not None) else None)
            _scene_view = any((self.store.bufs.get(k) is not None and self.store.bufs[k].scene)
                              for k in self.curves)
            _lab = ("场景时刻" if _scene_view else "时间") + \
                   (" (绝对时刻)" if self.abs_on else " (s)")
            for p in self.plots:
                ax = p.getAxis("bottom")
                if isinstance(ax, ClockAxis) and ax.epoch_base != _off:
                    ax.epoch_base = _off
                    ax.picture = None
                if p.getAxis("bottom").labelText != _lab:
                    p.setLabel("bottom", _lab, color=C_DIM)
                    p.getAxis("bottom").setTextPen(C_DIM)
        except Exception:                                                      # noqa: BLE001
            pass
        if scene_x is not None:                     # ▶ 跟 3D 播放进度 (可左右移动)
            # 🔖 记住"3D 停下的那一刻" (拖动/播放时持续更新) — 停止后竖线靠它留在原地, 不消失
            self._pb_last = {"t_s": float(scene_x), "ts": pb.get("ts"),
                             "frame": pb.get("frame"), "total": pb.get("total")}
            for mk in self.marks:
                mk.setPos(float(scene_x))
                mk.setPen(pg.mkPen("#ffb86c", width=1.6))
                mk.setVisible(True)
            if self.mark_lb is not None:
                _clk = (" · 🕒 %s" % clock_str(pb["ts"])) if pb.get("ts") else ""
                _fr = (" · 帧 %s/%s" % (pb.get("frame"), pb.get("total"))
                       if pb.get("frame") is not None else "")
                self.mark_lb.setText("▶ 场景 t=%.3fs%s%s" % (float(scene_x), _fr, _clk))
                self.mark_lb.setPos(float(scene_x), self._label_y())
                self.mark_lb.setVisible(True)
            return
        # 🚫 2026-10-11 老倪: 「同步时间轴不要消失 —— 我移动 3D 场景的播放按钮, 刚停止, 你的时间轴就不见了」
        #   根因: 3D 停下后 trace_live.json 不再刷新 (st_mtime > 2s ⇒ fresh=False), 旧代码就落到"最新样本"分支,
        #   把竖线从**他停下的那一刻**跳回最新样本处 (看着就是"时间轴不见了")。
        #   修法: 3D 停下 ⇒ **竖线留在它停下的那一刻**, 标签继续写那一刻的场景时刻/帧号/🕒绝对时刻; 永不隐藏。
        _scene_view2 = any((self.store.bufs.get(k) is not None and self.store.bufs[k].scene)
                           for k in self.curves)
        if self._pb_last is not None and _scene_view2:
            _x = float(self._pb_last["t_s"])
            # 🔒 再兜一层: 若这一刻被"跟随/缩放"挤到可视范围外, 把 x 范围撑到含它 ⇒ 竖线不会"看着消失"
            try:
                vb = self.main_plot.getViewBox() if self.main_plot is not None else None
                if vb is not None:
                    x0, x1 = vb.viewRange()[0]
                    if _x < x0 or _x > x1:
                        m = max(0.5, (x1 - x0) * 0.05)
                        self.refresh(x_range=(min(x0, _x - m), max(x1, _x + m)))
            except Exception:                                                    # noqa: BLE001
                pass
            for mk in self.marks:
                mk.setPos(_x)
                mk.setPen(pg.mkPen("#ffb86c", width=1.4, style=Qt.DashLine))
                mk.setVisible(True)
            if self.mark_lb is not None:
                _ts = self._pb_last.get("ts")
                _clk = (" · 🕒 %s" % clock_str(_ts)) if _ts is not None else ""
                _fr = (" · 帧 %s/%s" % (self._pb_last.get("frame"), self._pb_last.get("total"))
                       if self._pb_last.get("frame") is not None else "")
                self.mark_lb.setText("▶ 场景 t=%.3fs%s (3D 已停在这一帧)%s" % (_x, _fr, _clk))
                self.mark_lb.setPos(_x, self._label_y())
                self.mark_lb.setVisible(True)
            return
        x_new, x_scene = None, False
        for k, item in self.items.items():
            b = self.store.bufs.get(k)
            if b is None or b.n == 0:
                continue
            t, _ = b.arrays()
            if len(t):
                # 场景时刻源不能减 t0 (t 本身就是秒) —— 否则竖线会飞到 -1.79e9 屏幕外
                x = float(t[-1]) if b.scene else float(t[-1]) - self.store.t0
                if x_new is None or x > x_new:
                    x_new, x_scene = x, bool(b.scene)
        if x_new is None:
            return
        for mk in self.marks:
            mk.setPos(x_new)
            mk.setPen(pg.mkPen("#ffb86c", width=1.4, style=Qt.DashLine))
            mk.setVisible(True)                 # 🚫 任何路径都不隐藏竖线 (老倪: 不要消失)
        if self.mark_lb is not None:
            self.mark_lb.setVisible(True)
            if x_scene:
                _c = (" · 🕒 %s" % clock_str(pb["ts"])) if pb.get("ts") is not None else ""
                self.mark_lb.setText("🕒 最新 场景 t=%.3fs (3D 进度条已停)%s" % (x_new, _c))
            else:
                self.mark_lb.setText("🕒 最新 %s" % clock_str(self.store.t0 + x_new))
            self.mark_lb.setPos(x_new, self._label_y())

    def _make_cursors(self):
        """测量光标: 每次重建图形后重建光标 (旧对象的 C++ 实例已随 clear() 销毁)"""
        self.c1 = self.c2 = None
        if self.main_plot is None:
            return
        self.c1 = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(C_BLUE, width=1.2),
                                  label="A", labelOpts={"color": C_BLUE, "position": 0.04})
        self.c2 = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(C_ORANGE, width=1.2),
                                  label="B", labelOpts={"color": C_ORANGE, "position": 0.12})
        for c in (self.c1, self.c2):
            c.setZValue(50)
            if self.cursor_cb:
                c.sigPositionChanged.connect(lambda *_: self.cursor_cb())
            self.main_plot.addItem(c, ignoreBounds=True)
        self.c1.setVisible(self.cursor_on)
        self.c2.setVisible(self.cursor_on and self.diff_on)

    def set_cursors(self, on, diff, cb=None):
        self.cursor_on, self.diff_on = on, diff
        if cb is not None:
            self.cursor_cb = cb
        if on and self.c1 is None:
            self._make_cursors()
        if self.c1 is not None:
            self.c1.setVisible(on)
            self.c2.setVisible(on and diff)

    # ---- 模式 ----
    def set_mode(self, mode):
        self.mode = mode
        self._rebuild(force=True)

    def _rebuild(self, force=False):
        self._clear_extra_axes()
        self.glw.clear()
        self.items.clear()
        ax_pen = pg.mkPen(C_DIM)
        self.main_plot = self.glw.addPlot(row=0, col=0)
        p = self.main_plot
        p.setLabel("bottom", "时间 (s)", color=C_DIM)
        p.showGrid(x=self.grid, y=self.grid, alpha=0.25)
        p.getAxis("left").setPen(ax_pen)
        p.getAxis("bottom").setPen(ax_pen)
        p.getAxis("left").setTextPen(C_DIM)
        p.getAxis("bottom").setTextPen(C_DIM)
        p.setClipToView(True)
        p.setDownsampling(auto=True, mode="peak")
        self._build_items()

    def _clear_extra_axes(self):
        """摘掉多轴模式往 scene 里塞的 ViewBox / AxisItem。

        ⚠️ glw.clear() 只清 layout 里的 PlotItem, 这些直接 scene().addItem 进去的
        ViewBox 会留下来继续画 ⇒ 切到"每信号独立图"时曲线会跨子图溢出。
        """
        for k, (vb, axis) in list(self.extra_vbs.items()):
            try:
                if vb.scene() is not None:
                    vb.scene().removeItem(vb)
            except Exception:
                pass
            try:
                if axis is not None and axis.scene() is not None:
                    axis.scene().removeItem(axis)
            except Exception:
                pass
            try:
                if self.main_plot is not None and axis is not None:
                    self.main_plot.layout.removeItem(axis)
            except Exception:
                pass
        self.extra_vbs.clear()

    def _build_items(self):
        """按当前 mode 与 curves 建曲线对象"""
        self._clear_extra_axes()
        self.glw.clear()
        self.items.clear()
        self.plots = []
        keys = self.curves
        if self.mode == self.MODE_SINGLE:
            self.main_plot = None            # 🔧 原来指向被 clear() 删掉的那张图 ⇒ 光标/缩放打空对象
            for i, k in enumerate(keys):
                p = self.glw.addPlot(row=i, col=0, axisItems=self._clock_axes())
                self.plots.append(p)
                p.getAxis("bottom").abs_on = self.abs_on
                p.showGrid(x=self.grid, y=self.grid, alpha=0.25)
                p.setLabel("left", k.split(".")[-1], color=self.store.get(k).color)
                p.setLabel("bottom", "时间 (s)", color=C_DIM)
                p.getAxis("left").setTextPen(C_DIM)
                p.getAxis("bottom").setTextPen(C_DIM)
                p.setClipToView(True)
                p.setDownsampling(auto=True, mode="peak")
                if self.main_plot is None:
                    self.main_plot = p
                else:
                    p.setXLink(self.main_plot)
                pen = pg.mkPen(self.store.get(k).color, width=self.store.get(k).bold)
                item = p.plot(pen=pen, symbol=None)
                item.setClipToView(True)      # 数据裁到本子图内, 不越界
                self.items[k] = item
        else:
            self.glw.clear()
            self.main_plot = self.glw.addPlot(row=0, col=0, axisItems=self._clock_axes())
            self.plots = [self.main_plot]
            self.main_plot.getAxis("bottom").abs_on = self.abs_on
            p = self.main_plot
            p.setLabel("bottom", "时间 (绝对时刻)" if self.abs_on else "时间 (s)", color=C_DIM)
            p.showGrid(x=self.grid, y=self.grid, alpha=0.25)
            p.getAxis("left").setTextPen(C_DIM)
            p.getAxis("bottom").setTextPen(C_DIM)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            for i, k in enumerate(keys):
                b = self.store.get(k)
                pen = pg.mkPen(b.color, width=b.bold)
                item = p.plot(pen=pen)
                item.setClipToView(True)
                self.items[k] = item
            if self.mode == self.MODE_MULTI:
                self._build_multi_axes(keys)
        self._make_cursors()
        self._make_markers()

    def _build_multi_axes(self, keys):
        """每信号一套独立 Y 轴 (CANoe: Show signals in separate Y axes)

        注意: pyqtgraph 内置只有 left/right 两根轴。第 1 根用内置 right, 第 3 根起必须
        自建 AxisItem 并插进 PlotItem.layout (官方 MultiplePlotAxes 例子的做法)。
        """
        p = self.main_plot
        vb0 = p.getViewBox()
        for i, k in enumerate(keys):
            b = self.store.get(k)
            if i == 0:
                # 第 1 条信号直接用左轴 (改色便于识别)
                p.getAxis("left").setPen(pg.mkPen(b.color))
                p.getAxis("left").setTextPen(b.color)
                p.getAxis("left").setLabel(b.key.split(".")[-1])
                self.items[k] = p.plot(pen=pg.mkPen(b.color, width=b.bold))
                continue
            vb = pg.ViewBox()
            p.scene().addItem(vb)
            vb.setXLink(vb0)
            if i == 1:
                axis = p.getAxis("right")
                p.showAxis("right")
            else:
                axis = pg.AxisItem("right")
                # (2, 3) = 右侧列; 每多一根轴把已有轴往外挪一列
                p.layout.addItem(axis, 2, 3 + (i - 2))
            axis.setPen(pg.mkPen(b.color))
            axis.setTextPen(b.color)
            axis.setLabel(b.key.split(".")[-1])
            axis.linkToView(vb)
            item = pg.PlotDataItem(pen=pg.mkPen(b.color, width=b.bold))
            item.setClipToView(True)
            vb.addItem(item)
            self.items[k] = item
            self.extra_vbs[k] = (vb, axis)
        vb0.sigResized.connect(lambda: self._sync_vb_geometry())
        self._sync_vb_geometry()

    def _sync_vb_geometry(self):
        if not self.extra_vbs or self.main_plot is None:
            return
        rect = self.main_plot.getViewBox().sceneBoundingRect()
        for vb, _ in self.extra_vbs.values():
            vb.setGeometry(rect)
            try:
                vb.linkedViewChanged(self.main_plot.getViewBox(), vb.XAxis)
            except Exception:
                pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_vb_geometry()

    # ---- 数据 ----
    def set_curves(self, keys):
        changed = list(keys) != list(self.curves)
        self.curves = list(keys)
        if changed:
            self._build_items()
            if self.mode == self.MODE_MULTI:
                self._sync_vb_geometry()

    def refresh(self, x_range=None, fit_y=False):
        store = self.store
        for k, item in list(self.items.items()):
            b = store.bufs.get(k)
            if b is None or b.n == 0:
                continue
            t, v = b.arrays()
            if not b.scene:
                t = t - store.t0      # ⏱ 到达时刻源: x = 相对秒 (t - t0); 场景源 x 就是场景时刻
            if self.mode == self.MODE_MULTI and k in self.extra_vbs:
                item.setData(t, v)
                vb, _ = self.extra_vbs[k]
                # 每条曲线按自己的 Y 量程自动缩放 (CANoe: 每信号独立 Y 轴), 常量值给个最小跨度
                lo, hi = float(np.min(v)), float(np.max(v))
                if hi - lo < 1e-12:
                    lo, hi = lo - 1.0, hi + 1.0
                pad = (hi - lo) * 0.08
                vb.setYRange(lo - pad, hi + pad, padding=0)
            else:
                item.setData(t, v, symbol=None)
        if self.mode == self.MODE_MULTI:
            self._sync_vb_geometry()      # 尺寸/布局每帧对齐, 否则副轴曲线会画到框外
        self._refresh_marks()             # 🕒 最新时刻标记线跟着最新样本走
        if x_range is not None and self.main_plot is not None and self.mode != self.MODE_SINGLE:
            try:
                self.main_plot.setXRange(*x_range, padding=0)
            except Exception:
                pass
        if self.mode == self.MODE_SINGLE:
            for k, item in self.items.items():
                b = store.bufs.get(k)
                if b is None or b.n == 0:
                    continue
                plot = item.getViewBox().parentItem()
                if x_range is not None:
                    plot.setXRange(*x_range, padding=0)
                if fit_y:
                    t, v = b.arrays()
                    plot.setYRange(float(np.min(v)), float(np.max(v)), padding=0.1)

    def fit_y(self):
        if self.mode == self.MODE_SINGLE:
            self.glw.ci.layout.invalidate()
            for k, item in self.items.items():
                b = self.store.bufs.get(k)
                if b is not None and b.n:
                    t, v = b.arrays()
                    item.getViewBox().parentItem().setYRange(float(np.min(v)), float(np.max(v)), padding=0.1)
        else:
            lo = hi = None
            for k in self.items:
                b = self.store.bufs.get(k)
                if b is None or b.n == 0:
                    continue
                t, v = b.arrays()
                a, c = float(np.min(v)), float(np.max(v))
                lo = a if lo is None else min(lo, a)
                hi = c if hi is None else max(hi, c)
            if lo is not None and self.main_plot is not None:
                self.main_plot.setYRange(lo, hi, padding=0.1)

    def set_grid(self, on):
        self.grid = on
        for p in self._all_plots():
            p.showGrid(x=on, y=on, alpha=0.25)

    def set_points(self, on):
        self.show_points = on
        for k, item in self.items.items():
            try:
                item.setData(item.xData, item.yData, symbol="o" if on else None, symbolSize=4)
            except Exception:
                pass

    def _all_plots(self):
        out = []
        for i in range(self.glw.ci.layout.count()):
            it = self.glw.ci.layout.itemAt(i)
            if isinstance(it, pg.PlotItem):
                out.append(it)
        return out

    def apply_style(self):
        """把颜色/加粗同步到曲线"""
        for k, item in self.items.items():
            b = self.store.get(k)
            item.setPen(pg.mkPen(b.color, width=b.bold))


# ─────────────────────────────────────────────────────────────
# 主页面
# ─────────────────────────────────────────────────────────────
class DataSpaceTraceSource(threading.Thread):
    """🌐 全局数据空间 (DDS) 信号源 — 尾读 zmax_data/dataspace/trace.jsonl

    每行一帧总线报文 {t, topic, type, n, bytes, digest:"<payload json>"}; digest 里的数值叶子
    就是该话题此刻的实时信号值 ⇒ 波形键 = ds.<真实话题名>.<字段> (话题名即数据空间登记名)。
    首次只回看末尾 200KB, 不重放全历史。
    """

    def __init__(self, store, path=DS_TRACE, registry=DS_LIVE, poll=0.2):
        super().__init__(daemon=True)
        self.store = store
        self.path = path
        self.registry = registry
        self.poll = poll
        self.stop_ev = threading.Event()
        self.seen = {}          # topic → {"type","wall","n"}
        self.declared = {}      # registry 登记话题 → {"type","hz","pubs","allowed"}
        self._off = None
        self.load_registry()

    def load_registry(self):
        try:
            with open(self.registry, encoding="utf-8") as f:
                d = json.load(f)
            for key, rec in (d.get("topics") or {}).items():
                nm = rec.get("topic") or key
                self.declared[nm] = {"type": rec.get("type", ""), "hz": rec.get("hz"),
                                     "pubs": rec.get("matched_pubs"), "allowed": rec.get("allowed")}
        except Exception:
            pass

    def run(self):
        while not self.stop_ev.is_set():
            try:
                if os.path.isfile(self.path):
                    sz = os.path.getsize(self.path)
                    if self._off is None:
                        self._off = max(0, sz - 200000)
                    elif sz < self._off:
                        self._off = 0
                    if sz > self._off:
                        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
                            f.seek(self._off)
                            for line in f:
                                self._feed(line)
                            self._off = f.tell()
            except Exception:
                pass
            self.stop_ev.wait(self.poll)

    def _feed(self, line):
        line = line.strip()
        if not line:
            return
        try:
            rec = json.loads(line)
        except Exception:
            return
        topic = str(rec.get("topic") or "").strip()
        if not topic:
            return
        # digest 有两种真实形态 (JSON / 人读文本 / 被截断的 JSON) → 交给 parse_ds_digest 判
        vals = parse_ds_digest(rec.get("digest"))
        pref = "ds." + topic.lstrip("/") + "."
        # 帧龄 = 本机收到该帧的年龄 (总线帧本身就是落盘时刻)
        self.store.push_many({pref + k: v for k, v in vals.items()},
                             time.monotonic(), src="ds")
        self.seen[topic] = {"type": str(rec.get("type") or ""), "wall": time.time(),
                            "n": int(rec.get("n") or 0)}

    def stop(self):
        self.stop_ev.set()


class CanoeGraphicWidget(QWidget):
    """Graphic 信号分析页 (对标 CANoe Analysis → Graphic)"""

    log = pyqtSignal(str)
    catalog_ready = pyqtSignal(object, object)     # (catalog, err) —— 从工作线程安全回主线程

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C_BG}; color:{C_WHITE};")
        self.store = SignalStore()
        self.host_src = None
        self.ros_src = None
        self.ds_src = None             # 🌐 全局数据空间 (DDS 总线帧)
        self.scope = "3d"              # 数据范围: "3d"=只看 3D 场景数据 (默认) | "all"=全部来源
        self._default_done = False     # 3D 场景默认曲线是否已自动勾上
        self._watch_prefixes = set()   # 「增加信号话题」点名但暂无帧的话题: 出帧即自动画
        self.catalog = None            # {topic: {type, fields}}
        self.selected = []             # 画在波形里的信号 key (有序, 决定颜色)
        self.running = False
        self.paused = False
        self.follow = True
        self.cursor_on = False
        self.diff_cursor = True
        self.window_s = 10.0
        self.x_signal = None           # 用作 X 轴的信号
        self.logger = None             # 记录文件句柄
        self.log_rows = 0
        self._last_tree_update = 0.0
        self._tree_sig = None          # 上次建树时的 (目录, 信号集合) 指纹
        self._last_fill = 0.0
        self._expanded = set()         # 重建时保留展开的话题
        self._collapsed = set()        # 用户手动折叠的组/话题 (重建时不许被顶开 —— 老倪 10-12「点了没反应」)
        self._build_ui()
        self.catalog_ready.connect(self._on_catalog)
        self._load_catalog_cache()
        self._fill_tree()              # 🔧 一进页面就有名字 (不再等 ssh 回来)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / UI_FPS))
        self._autostart()

    # ─────────── UI ───────────
    def _btn(self, text, tip="", color=C_BLUE, checkable=False):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"""
            QPushButton{{background:{C_BG2}; color:{C_WHITE}; border:1px solid {C_BORDER};
                        border-radius:5px; padding:4px 9px; font-size:13px;}}
            QPushButton:hover{{border-color:{color}; color:{color};}}
            QPushButton:checked{{background:{color}22; border-color:{color}; color:{color};}}
        """)
        b.setFixedHeight(28)
        return b

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(6)

        # ── 工具栏 (对应 CANoe Graphic 工具栏) ──
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.b_start = self._btn("▶ 开始", "开始采样 (CANoe: Start measurement)", C_GREEN)
        self.b_pause = self._btn("⏸ 暂停", "暂停打印(仍继续记录) — CANoe Pause", C_ORANGE, True)
        self.b_stop = self._btn("■ 停止", "停止采样", C_RED)
        self.b_clear = self._btn("🧹 清空", "清空已采数据", C_DIM)
        self.b_cursor = self._btn("┃ 测量光标", "单光标: 读某点值/时刻 — CANoe Measurement cursor", C_BLUE, True)
        self.b_diff = self._btn("┃┃ 差分光标", "双光标: Δt 与各信号 Δv — CANoe Difference cursor", C_BLUE, True)
        self.b_fit = self._btn("⤢ Fit", "自适应 (CANoe: Fit signals)", C_PURPLE)
        self.b_zin = self._btn("X−", "沿时间轴缩小 (CANoe: Zoom out)", C_DIM)
        self.b_zout = self._btn("X+", "沿时间轴放大 (CANoe: Zoom in)", C_DIM)
        self.b_bold = self._btn("B 加粗", "选中信号加粗高亮 (CANoe: Highlight)", C_ORANGE, True)
        self.b_grid = self._btn("# 网格", "网格线 (CANoe: Grid)", C_DIM, True)
        self.b_pts = self._btn("• 采样点", "显示采样点 (CANoe: Sample points)", C_DIM, True)
        self.b_bold.setChecked(True)
        self.b_grid.setChecked(True)
        self.b_diff.setChecked(True)

        self.win_combo = QComboBox()
        for label, val in [("时间窗 5s", 5.0), ("时间窗 10s", 10.0), ("时间窗 30s", 30.0),
                           ("时间窗 60s", 60.0), ("时间窗 120s", 120.0), ("全部时间", 0.0)]:
            self.win_combo.addItem(label, val)
        self.win_combo.setCurrentIndex(1)
        self.win_combo.setStyleSheet(f"QComboBox{{background:{C_BG2};color:{C_WHITE};border:1px solid {C_BORDER};"
                                     f"border-radius:5px;padding:4px 6px;font-size:13px;}}")
        self.win_combo.currentIndexChanged.connect(self._on_window_changed)

        self.ymode = QComboBox()
        for label, m in [("Y轴: 共用一根", WaveArea.MODE_SHARED),
                         ("Y轴: 每信号独立", WaveArea.MODE_MULTI),
                         ("视图: 每信号独立图", WaveArea.MODE_SINGLE)]:
            self.ymode.addItem(label, m)
        self.ymode.setStyleSheet(self.win_combo.styleSheet())
        self.ymode.currentIndexChanged.connect(self._on_ymode)

        self.b_pan_l = self._btn("◀", "向左平移 (CANoe: Pan left)", C_DIM)
        self.b_pan_r = self._btn("▶", "向右平移 (CANoe: Pan right)", C_DIM)
        self.b_pan_u = self._btn("▲", "向上平移 (CANoe: Pan up)", C_DIM)
        self.b_pan_d = self._btn("▼", "向下平移 (CANoe: Pan down)", C_DIM)
        self.b_list = self._btn("☰ 信号栏", "显示/隐藏信号目录 (CANoe: 工具栏 1/17)", C_BLUE, True)
        self.b_list.setChecked(True)
        self.b_yrange = self._btn("↕ Y范围", "手动设 Y 轴范围 (CANoe: Graphic Configuration → Signals/Axes)", C_DIM)
        self.b_follow = self._btn("⇥ 跟随最新", "自动跟随最新数据 (CANoe: 滚动)", C_GREEN, True)
        self.b_follow.setChecked(True)
        self.b_add = self._btn("➕ 增加信号话题", "把别的话题/数据源加进来一起看 (全局数据空间 DDS / Orin ROS2 / 本机真值流)",
                               C_GREEN)
        self.scope_combo = QComboBox()
        for label, val in [("🎬 数据范围: 3D 场景数据", "3d"), ("🌐 数据范围: 全部来源", "all")]:
            self.scope_combo.addItem(label, val)
        self.scope_combo.setStyleSheet(f"QComboBox{{background:{C_BG2};color:{C_WHITE};"
                                       f"border:1px solid {C_BORDER};padding:2px 6px;}}")
        self.scope_combo.currentIndexChanged.connect(self._on_scope)
        self.b_log = self._btn("⏺ 记录", "Signal Logging: 落 CSV", C_RED, True)
        self.b_imp = self._btn("⤓ 导入", "导入记录 CSV 回放 (CANoe: Import)", C_DIM)
        self.b_abs = self._btn("🕒 绝对时刻轴", "时间轴改成绝对时刻显示 —— 直接和 3D 场景 HUD 上的时刻对 (老倪核对用)",
                               C_ORANGE, True)      # 可勾选: 勾=绝对时刻, 不勾=相对秒
        self.b_pin = self._btn("📌 打标记", "在最新时刻打一根标记线(或直接在波形上点一下)", C_BLUE)
        self.b_pinclear = self._btn("📌 清标记", "清掉手动标记线", C_DIM)
        self.b_csv = self._btn("⤒ 导出CSV", "导出当前数据", C_DIM)
        self.b_png = self._btn("⤒ 导出PNG", "截图", C_DIM)
        # 🕒 时刻标记: 波形页与 3D 场景对时刻 (老倪: 看是否一一对应)
        self.b_abs.clicked.connect(self._on_abs_axis)
        self.b_pin.clicked.connect(self._on_pin_latest)
        self.b_pinclear.clicked.connect(lambda: (self.wave.clear_pins(),
                                                self._log("📌 已清掉手动标记线")))
        # (pin_cb 挂在 wave 建好之后)

        # 第一行: 运行控制 + 时间/光标/缩放
        for w in (self.b_start, self.b_pause, self.b_stop, self.b_clear):
            bar.addWidget(w)
        bar.addSpacing(8)
        bar.addWidget(self.win_combo)
        bar.addWidget(self.b_follow)
        bar.addSpacing(8)
        for w in (self.b_cursor, self.b_diff, self.b_fit, self.b_zin, self.b_zout):
            bar.addWidget(w)
        bar.addSpacing(6)
        for w in (self.b_pan_l, self.b_pan_r, self.b_pan_u, self.b_pan_d):
            bar.addWidget(w)
        bar.addWidget(self.b_bold)
        bar.addStretch()
        root.addLayout(bar)

        # 第二行: 显示选项 + Signal Logging / 导出
        bar2 = QHBoxLayout()
        bar2.setSpacing(6)
        bar2.addWidget(self.ymode)
        bar2.addWidget(self.scope_combo)
        bar2.addWidget(self.b_add)
        bar2.addSpacing(8)
        for w in (self.b_grid, self.b_pts, self.b_list, self.b_yrange):
            bar2.addWidget(w)
        bar2.addSpacing(8)
        for w in (self.b_abs, self.b_pin, self.b_pinclear):
            bar2.addWidget(w)
        bar2.addSpacing(8)
        for w in (self.b_log, self.b_imp, self.b_csv, self.b_png):
            bar2.addWidget(w)
        bar2.addStretch()
        root.addLayout(bar2)

        for b, fn in ((self.b_start, self.start), (self.b_stop, self.stop),
                      (self.b_clear, self.clear), (self.b_fit, self._fit),
                      (self.b_zin, lambda: self._zoom(2.0)), (self.b_zout, lambda: self._zoom(0.5)),
                      (self.b_csv, self.export_csv), (self.b_png, self.export_png),
                      (self.b_imp, self.import_csv)):
            b.clicked.connect(fn)
        self.b_pause.toggled.connect(self._on_pause)
        self.b_cursor.toggled.connect(self._on_cursor)
        self.b_diff.toggled.connect(self._on_diff)
        self.b_follow.toggled.connect(lambda v: setattr(self, "follow", v))
        self.b_grid.toggled.connect(lambda v: self.wave.set_grid(v))
        self.b_pts.toggled.connect(lambda v: self.wave.set_points(v))
        self.b_bold.toggled.connect(self._on_bold)
        self.b_log.toggled.connect(self._on_log)
        self.b_list.toggled.connect(lambda v: self.tree.setVisible(v))
        self.b_yrange.clicked.connect(self._set_yrange)
        self.b_add.clicked.connect(self._add_topic_dialog)
        self.b_pan_l.clicked.connect(lambda: self._pan(-0.25, 0))
        self.b_pan_r.clicked.connect(lambda: self._pan(0.25, 0))
        self.b_pan_u.clicked.connect(lambda: self._pan(0, 0.25))
        self.b_pan_d.clicked.connect(lambda: self._pan(0, -0.25))

        # ── 状态行 ──
        st = QHBoxLayout()
        st.setSpacing(14)
        self.lb_state = QLabel("● 未启动")
        self.lb_state.setStyleSheet(f"color:{C_ORANGE}; font-size:13px;")
        self.lb_info = QLabel("")
        self.lb_info.setStyleSheet(f"color:{C_DIM}; font-size:13px;")
        st.addWidget(self.lb_state)
        st.addWidget(self.lb_info)
        st.addStretch()
        self.lb_legend = QLabel("")
        self.lb_legend.setTextFormat(Qt.RichText)
        self.lb_legend.setStyleSheet(f"font-size:13px;")
        st.addWidget(self.lb_legend)
        root.addLayout(st)

        # ── 主体: 左信号栏 + 右波形 ──
        split = QSplitter(Qt.Horizontal)
        split.setStyleSheet(f"QSplitter::handle{{background:{C_BORDER};}}")

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("过滤信号…")
        self.filter.setStyleSheet(f"QLineEdit{{background:{C_BG2};color:{C_WHITE};border:1px solid {C_BORDER};"
                                  f"border-radius:5px;padding:4px 6px;font-size:13px;}}")
        self.filter.textChanged.connect(lambda _: self._fill_tree())
        b_refresh = self._btn("⟳ 话题目录", "从 Orin 刷新话题字段 (任意话题)", C_BLUE)
        b_refresh.clicked.connect(self.refresh_catalog)
        top.addWidget(self.filter, 1)
        top.addWidget(b_refresh)
        lv.addLayout(top)
        # 🥽 2026-10-12 老倪: 「信号分析要有个排序的功能, 即按照 绿色/蓝色/紫色/白色 来排列;
        #   白色就是所有颜色的信号都显示」⇒ 四个按钮 = 四色; 选色后该色**置顶**(其余压暗但仍显示), 白=全部不排序。
        self._scene_sort = ""
        sc_row = QHBoxLayout()
        self._scene_btns = {}
        for _lab, _val, _col in SCENE_SORT_ITEMS:
            _b = self._btn(_lab, ("全部显示(不按场景排序)" if not _val else "按场景排序: %s 置顶(色 %s)" % (_val, _col)), _col)
            _b.clicked.connect(lambda _=False, v=_val: self._set_scene_sort(v))
            self._scene_btns[_val] = _b
            sc_row.addWidget(_b)
        sc_row.addStretch(1)
        self._scene_lab = QLabel("")
        self._scene_lab.setStyleSheet(f"color:{C_DIM}; font-size:12px")
        sc_row.addWidget(self._scene_lab)
        lv.addLayout(sc_row)
        self._scene_sync_lab()

        # ⚙️ 2026-10-12 老倪: 「现在的实时监控, 要能看出配置」——顶部常显一行"当前配置"
        #   (任务/场景+色/配方/工艺步数/启用节点/档位/覆盖参数/配置单文件与时间);
        #   真源 = tools/config_sheet.py 导出的配置单 (outputs/config_sheets/配置单_*_latest.json), 5s 自刷新。
        self._cfg_mtime = None
        self._cfg_lab = QLabel("")
        self._cfg_lab.setTextFormat(Qt.RichText)
        self._cfg_lab.setWordWrap(True)
        self._cfg_lab.setStyleSheet(f"color:{C_DIM}; font-size:12px; padding:2px 3px;")
        lv.addWidget(self._cfg_lab)
        self._fill_cfg()
        self._cfg_timer = QTimer(self)
        self._cfg_timer.setInterval(5000)
        self._cfg_timer.timeout.connect(self._fill_cfg)
        self._cfg_timer.start()

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["信号名称", "当前值", "帧龄", "来源话题"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setStyleSheet(f"""
            QTreeWidget{{background:{C_BG2}; color:#c9d1d9; border:1px solid {C_BORDER};
                         border-radius:6px; font-size:13px;
                         alternate-background-color:#11161d;}}
            QTreeWidget::item:selected{{background:{C_BLUE}44; color:#ffffff;}}
            QHeaderView::section{{background:{C_BG}; color:{C_DIM}; border:none; padding:4px; font-size:12px;}}
        """)
        # 名字列必须真看得见: 数值列用固定窄宽 (原来 ResizeToContents 会被 1791721088.4008 这种长数字
        # 撑到 110px+, 5 列一起把"信号"列挤成 0 宽 ⇒ 名字画不出来), 余下全给名字列。
        self.tree.setIndentation(16)                     # 默认 40px 缩进把名字列吃掉了
        self.tree.setTextElideMode(Qt.ElideMiddle)       # 长名字: 头尾都留着 (sstrace.…孔_mm)
        self.tree.setMinimumWidth(460)
        self._apply_col_widths()
        QTimer.singleShot(0, self._apply_col_widths)     # 显示后再来一次 (样式表 polish 会重置)
        QTimer.singleShot(1200, self._apply_col_widths)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemDoubleClicked.connect(lambda *_: self._toggle_checked())
        lv.addWidget(self.tree, 1)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        self.wave = WaveArea(self.store)
        self.wave.pin_cb = self._on_pinned        # 📌 打标记 → 记一行带时刻的日志
        rv.addWidget(self.wave, 1)
        self.cursor_lb = QLabel("")
        self.cursor_lb.setTextFormat(Qt.RichText)
        self.cursor_lb.setStyleSheet(f"background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px;"
                                     f"padding:4px 8px; font-size:13px; font-family:monospace;")
        self.cursor_lb.setVisible(False)
        rv.addWidget(self.cursor_lb)
        self.log_line = QLabel("")
        self.log_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.log_line.setStyleSheet(f"color:{C_DIM}; font-size:12px; font-family:monospace;")
        rv.addWidget(self.log_line)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([540, 1180])
        left.setMinimumWidth(470)
        root.addWidget(split, 1)

        # 光标 (CANoe 测量光标 + 差分光标) — 归 WaveArea 持有, 图形重建后自动重建
        self.wave.set_cursors(False, True, self._update_cursor_text)

        self._log("就绪 · 勾选左侧信号即出波形 · 数据源: 本机真值流 + Orin ROS2 话题")

    # ─────────── 起停 ───────────
    def _autostart(self):
        self.refresh_catalog(quiet=True)
        self.start()

    def start(self):
        if self.running:
            return
        if self.host_src is None:
            self.host_src = HostJsonSource(self.store, HOST_SOURCES)
            self.host_src.start()
        if self.ros_src is not None:
            self.ros_src.stop()
        topics = self._ros_topics()
        self.ros_src = RosTopicSource(self.store, topics)
        self.ros_src.start()
        if self.ds_src is None:
            self.ds_src = DataSpaceTraceSource(self.store)
            self.ds_src.start()
        self.running = True
        self._log(f"▶ 采样开始 · 本机源 {len(HOST_SOURCES)} 个文件 · Orin 话题 {len(topics)} 个"
                  f" · 数据空间总线帧 1 路 (zmax_data/dataspace/trace.jsonl)")

    def stop(self):
        for s in (self.host_src, self.ros_src, self.ds_src):
            if s is not None:
                s.stop()
        self.host_src = self.ros_src = self.ds_src = None
        self.running = False
        self._log("■ 采样停止")

    def clear(self):
        self.store.clear()
        for b in self.store.bufs.values():
            b.clear()
        self.wave.set_curves(self.selected)
        self._log("🧹 已清空数据")

    def _on_bold(self, on):
        """选中信号加粗 (CANoe: Highlight)"""
        for k in self.wave.curves:
            b = self.store.get(k)
            b.bold = 5 if on else 2
        self.wave.apply_style()

    def _on_pause(self, on):
        self.paused = on
        self._log("⏸ 暂停打印 (后台继续记录)" if on else "▶ 继续打印")

    def _on_window_changed(self):
        self.window_s = self.win_combo.currentData()
        # 选时间窗不再强行打开「跟随最新」: 原行为会把用户手动平移的位置顶掉,
        # 且按钮状态与实际行为对不上 (老倪口径: 界面显示要等于真实行为)
        self.b_follow.setChecked(self.follow)

    def _on_abs_axis(self):
        on = self.b_abs.isChecked()
        self.wave.set_abs_axis(on)
        self._log("🕒 时间轴 → 绝对时刻 (和 3D 场景 HUD 上的时刻直接对)" if on
                  else "🕒 时间轴 → 相对秒")

    def _on_pin_latest(self):
        """按最新样本打一根标记线 (和 3D 场景正在显示的那一帧同一时刻)"""
        x_new = None
        for k in self.selected:
            b = self.store.bufs.get(k)
            if b is None or b.n == 0:
                continue
            t, _ = b.arrays()
            if len(t):
                x = float(t[-1]) - self.store.t0
                x_new = x if x_new is None else max(x_new, x)
        if x_new is None:
            self._log("📌 还没数据, 打不了标记")
            return
        self.wave.pin_at(x_new)

    def _on_pinned(self, x, clock):
        self._log(f"📌 标记 @ {clock}  (t={x:.3f}s) — 拿它和 3D 场景上的时刻对一下")

    def _on_ymode(self):
        self.wave.set_mode(self.ymode.currentData())
        self.wave.set_curves(self.selected)
        self._log(f"Y 轴模式 → {self.ymode.currentText()}")

    def _on_scope(self):
        self.scope = self.scope_combo.currentData() or "3d"
        self._fill_tree()
        self._update_tree_values()
        self._log("🎬 数据范围: 3D 场景数据 (只看引擎轨迹快照)" if self.scope == "3d"
                  else "🌐 数据范围: 全部来源 (3D 场景 + 本机真值流 + Orin ROS2 + 全局数据空间)")

    # 首屏默认曲线: 3D 场景里最说明问题的几条 (量纲差大 ⇒ 配「每信号独立图」)
    # 🔤 两套按场景给 (2026-10-13): 摆盘 = 真空吸持 / 吸嘴到槽位_mm; 插拔 = 夹爪 / 光模块头到孔_mm。
    #   命名真源 = tools/scene_signal_names.py; 实际哪套在跑由快照里的键决定 (下面用 store.bufs 过滤)。
    DEFAULT_3D = ("sstrace.末端_x", "sstrace.末端_y", "sstrace.末端_z",
                  "sstrace.光模块头到孔_mm", "sstrace.吸嘴到槽位_mm",
                  "sstrace.接触概率", "sstrace.安全边界_mps",
                  # ⚡ 2026-10-15 老倪「信号分析, 主窗口, 没有波形信号啊」: 上面 7 条来自 3D 面板快照
                  #   (trace_live.json), 3D 不播放 ⇒ 每键 1 个样本 ⇒ 画不出线。下面 3 条来自**常驻
                  #   引擎回路**的 10Hz 真值帧流 (sseng.*), 打开页面就有连续波形(每周期真值都在动)。
                  "sseng.势能_phi", "sseng.梯度范数", "sseng.循环耗时_ms")

    def _apply_watch(self):
        """被「➕ 增加信号话题」点名但当时还没出帧的话题: 一有字段出现就自动勾上"""
        for pref in list(self._watch_prefixes):
            hit = False
            for k in self.store.keys():
                if k.startswith(pref) and k not in self.selected:
                    self.selected.append(k)
                    hit = True
            if hit:
                self.wave.set_curves(self.selected)

    def _apply_default_selection(self):
        """首屏默认: 只显示 3D 场景数据, 并自动勾上代表曲线 (打开就有波形看)"""
        self._apply_watch()
        if self._default_done or self.scope != "3d":
            return
        keys = [k for k in self.DEFAULT_3D if k in self.store.bufs]
        if len(keys) < 3:
            return              # 3D 场景还没跑过 (快照未落) → 下次建树再试
        self._default_done = True
        for it in self._all_items():
            if not (it.flags() & Qt.ItemIsUserCheckable):
                continue        # 非当前场景区域的重名行不可勾选(老倪: 蓝区不该跟着打勾)
            if it.data(0, Qt.UserRole) in keys and it.checkState(0) != Qt.Checked:
                it.setCheckState(0, Qt.Checked)
        self.ymode.setCurrentIndex(2)       # 每信号独立图
        self._log(f"🎬 首屏: 只显示 3D 场景数据, 已勾 {len(keys)} 条 (末端 xyz · 光模块头到孔 · 接触概率 · 安全边界) "
                  f"· 要加别的话题点「➕ 增加信号话题」")

    def _add_topic_dialog(self):
        """➕ 增加信号话题: 从 全局数据空间(DDS) / Orin ROS2 / 本机真值流 里挑话题加进波形"""
        dlg = QDialog(self)
        dlg.setWindowTitle("➕ 增加信号话题 — 挑选要看的 topic")
        dlg.resize(980, 620)
        dlg.setStyleSheet(f"QDialog{{background:{C_BG};}} QLabel{{color:{C_WHITE};}}")
        box = QVBoxLayout(dlg)
        head = QLabel("选话题 → 「加入波形」后, 该话题的每个数值字段都会出现在左侧信号栏并开始画。"
                      "\n· 全局数据空间(DDS): 数据空间页登记的真实话题 (zmax/ss_state 等), 值来自总线帧 trace.jsonl"
                      "\n· Orin ROS2: 机械臂/相机侧话题 (勾上后自动向 Orin 重新订阅)"
                      "\n· 本机真值流: 位姿/安全/YOLO 等本机 JSON 文件")
        head.setStyleSheet(f"color:{C_GRAY}; font-size:12px;")
        box.addWidget(head)

        lw = QListWidget()
        lw.setSelectionMode(QAbstractItemView.ExtendedSelection)
        lw.setStyleSheet(f"QListWidget{{background:{C_BG2};color:{C_WHITE};font-family:monospace;"
                         f"font-size:13px;border:1px solid {C_BORDER};}}")
        # (1) 全局数据空间
        ds_items = {}
        if self.ds_src is not None:
            for t, meta in self.ds_src.seen.items():
                ds_items[t] = dict(meta)
            for t, meta in self.ds_src.declared.items():
                ds_items.setdefault(t, {"type": meta.get("type", ""), "hz": meta.get("hz"),
                                        "pubs": meta.get("pubs")})
        for t, meta in sorted(ds_items.items()):
            n = len([k for k in self.store.keys() if k.startswith("ds." + t.lstrip("/") + ".")])
            info = f"[数据空间] {t:<28s} ({(str(meta.get('type') or '?')).split('::')[-1]})"
            if meta.get("hz") not in (None, -1.0):
                info += f" · {float(meta['hz']):.2f}Hz"
            if meta.get("pubs") is not None:
                info += f" · 发布者{meta['pubs']}"
            info += f" · {n} 个信号" + ("" if n else " · 此刻无帧")
            it = QListWidgetItem(info)
            it.setData(Qt.UserRole, ("ds", t))
            lw.addItem(it)
        # (2) Orin ROS2
        for t, meta in sorted((self.catalog or {}).items()):
            it = QListWidgetItem(f"[Orin ROS2] {t:<28s} ({meta['type'].split('/')[-1]}) · "
                                 f"{len(meta['fields'])} 个数值字段")
            it.setData(Qt.UserRole, ("ros", t))
            lw.addItem(it)
        # (3) 本机真值流
        for pref, rel in HOST_SOURCES:
            it = QListWidgetItem(f"[本机文件] {pref:<28s} ({rel}) · 数值叶子自动展开")
            it.setData(Qt.UserRole, ("host", pref))
            lw.addItem(it)
        box.addWidget(lw, 1)

        row = QHBoxLayout()
        info_lb = QLabel("")
        info_lb.setStyleSheet(f"color:{C_DIM}; font-size:12px;")
        row.addWidget(info_lb, 1)
        b_add = QPushButton("➕ 加入波形")
        b_del = QPushButton("➖ 从波形移除")
        b_cancel = QPushButton("取消")
        for b in (b_add, b_del, b_cancel):
            b.setStyleSheet(f"QPushButton{{background:{C_BG2};color:{C_WHITE};border:1px solid "
                            f"{C_BORDER};padding:5px 12px;}}")
            row.addWidget(b)
        box.addLayout(row)

        def do_add(remove=False):
            picked = [i.data(Qt.UserRole) for i in lw.selectedItems()]
            if not picked:
                info_lb.setText("先在上面选一个或多个话题")
                return
            r = self._apply_topic_pick(picked, remove=remove)
            if r["added"] or r["removed"] or r["watch"]:
                dlg.accept()

        b_add.clicked.connect(lambda: do_add(False))
        b_del.clicked.connect(lambda: do_add(True))
        b_cancel.clicked.connect(dlg.reject)
        dlg.exec_()

    def _apply_topic_pick(self, picked, remove=False):
        """把选中的话题加进/移出波形 (抽出来便于回归测试: 不弹对话框也能走同一条路)

        picked: [("ds"|"ros"|"host", 话题名/来源前缀), ...]
        """
        added = removed = 0
        watch, ros_dirty = [], False
        for kind, name in picked:
            if kind == "ds":
                pref = "ds." + name.lstrip("/") + "."
                keys = [k for k in self.store.keys() if k.startswith(pref)]
                if remove:
                    for k in keys:
                        if k in self.selected:
                            self.selected.remove(k); removed += 1
                elif keys:
                    for k in keys:
                        if k not in self.selected:
                            self.selected.append(k); added += 1
                else:
                    watch.append(pref)          # 此刻无帧 → 挂监视, 出帧即画
            elif kind == "ros":
                meta = (self.catalog or {}).get(name)
                if not meta:
                    continue
                for f in meta["fields"]:
                    if f.endswith("[*]"):
                        keys_f = ["ros." + f"{name}.{f[:-3]}[{i}]".lstrip("/") for i in range(16)]
                    else:
                        keys_f = ["ros." + f"{name}.{f}".lstrip("/")]
                    for key in keys_f:
                        if remove:
                            if key in self.selected:
                                self.selected.remove(key); removed += 1
                        elif key not in self.selected:
                            self.selected.append(key); added += 1
                ros_dirty = True
            else:                                   # 本机文件源
                for k in list(self.store.keys()):
                    if k.startswith(name + "."):
                        if remove:
                            if k in self.selected:
                                self.selected.remove(k); removed += 1
                        elif k not in self.selected:
                            self.selected.append(k); added += 1
        if watch:
            self._watch_prefixes.update(watch)
        if self.scope == "3d" and (added or removed):
            self.scope_combo.setCurrentIndex(1)     # 加了别的话题 → 自动切到「全部来源」
        if ros_dirty:
            was = self.running
            self.running = False
            if self.ros_src is not None:
                self.ros_src.stop()
            self.running = was
            self.start()                            # 重新订阅 (带上新话题)
        self.wave.set_curves(self.selected)
        self._fill_tree()
        self._update_tree_values()
        self._log(f"{'➕' if not remove else '➖'} {'加入' if not remove else '移除'} "
                  f"{added if not remove else removed} 个信号 (话题 {len(picked)} 个)"
                  + (" · 已切到「全部来源」" if self.scope == "all" else "")
                  + (" · 已重新向 Orin 订阅" if ros_dirty else "")
                  + (f" · {len(watch)} 个话题此刻无帧, 出帧即画" if watch else ""))
        return {"added": added, "removed": removed, "watch": len(watch), "ros": ros_dirty}

    # ─────────── 信号目录 ───────────
    def refresh_catalog(self, quiet=False):
        if not quiet:
            self._log("⟳ 读取 Orin 话题目录…")

        def done(cat, err):
            # ⚠️ 这里跑在工作线程: 必须用信号回主线程 (QTimer.singleShot 在无事件循环的线程里不会触发)
            self.catalog_ready.emit(cat, err)

        CatalogWorker(done).start()

    def _on_catalog(self, cat, err):
        if err:
            self._log(f"⚠️ 话题目录获取失败: {err} (只有本机真值流; 点「⟳ 话题目录」重试)")
        else:
            self.catalog = {t["name"]: {"type": t["type"], "fields": t["fields"]}
                            for t in cat.get("topics", [])}
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                with open(CATALOG_CACHE, "w", encoding="utf-8") as f:
                    json.dump(cat, f, ensure_ascii=False)
            except Exception:
                pass
            self._log(f"✅ 话题目录: {len(self.catalog)} 个话题 / "
                      f"{sum(len(v['fields']) for v in self.catalog.values())} 个数值字段")
        self._fill_tree()

    def _load_catalog_cache(self):
        """读上次的话题目录缓存 ⇒ 一进页面左侧就能看到话题名, 不用等 ssh"""
        try:
            with open(CATALOG_CACHE, encoding="utf-8") as f:
                cat = json.load(f)
            self.catalog = {t["name"]: {"type": t["type"], "fields": t["fields"]}
                            for t in cat.get("topics", [])}
        except Exception:
            pass

    def _ros_topics(self):
        """当前勾选的 ROS 信号所涉及的话题 (含类型)"""
        if not self.catalog:
            return []
        topics = set()
        for k in self.selected:
            if not k.startswith("ros."):
                continue
            rest = k[len("ros."):]
            topic = None
            for t in self.catalog:                      # 话题名本身带斜杠, 用目录反查(最长匹配)
                if rest.startswith(t.lstrip("/") + "."):
                    if topic is None or len(t) > len(topic):
                        topic = t
            if topic:
                topics.add(f"{topic}:{self.catalog[topic]['type']}")
        return sorted(topics)

    def _fill_tree(self):
        """建信号目录 —— **按场景分组** (老倪 2026-10-12: 「绿色场景的标题应该叫插拔场景; AR 下面是白的?;
        摆盘呢, 摆盘应该是蓝色信号; 其它无法分类的信号, 定义为基础场景, 用白色显示 topic」)。

        四组(顺序 = 色序): 🟢 插拔场景 / 🔵 摆盘场景 / 🥽 AR 场景 / ⚪ 基础场景(白)。
        一个信号归哪组 = 打标真源 `tools/sig_scene_tags.py` → `config/topics/scene_tags.json`;
        没打标的一律进「基础场景」(白 ○)。可反复调用: 记指纹 + 保留展开/折叠状态
        (老倪点的折叠不再被下一次重建顶开 —— 之前是硬编码 setExpanded(True) 顶开的)。
        """
        filt = self.filter.text().strip().lower()
        for it in self._all_items():        # 记住展开/折叠, 重建后原样恢复
            _k = it.data(0, Qt.UserRole + 1) or it.data(0, Qt.UserRole) or it.text(0)
            if not _k:
                continue
            if it.isExpanded():
                self._expanded.add(_k)
                self._collapsed.discard(_k)
            else:
                self._collapsed.add(_k)
        self._tree_sig = (len(self.catalog or {}), tuple(sorted(self.store.keys())))
        self._last_fill = time.monotonic()
        self.tree.blockSignals(True)
        self.tree.clear()

        def _scene_of(_key):
            try:
                return ((SST.tag(_key) if SST is not None else "") or "基础场景")
            except Exception:                                                  # noqa: BLE001
                return "基础场景"

        def _mkroot(_sc, _title):
            _r = QTreeWidgetItem([_title, "", "", ""])
            _r.setForeground(0, QColor(SCENE_COLORS.get(_sc, C_WHITE)))
            _r.setData(0, Qt.UserRole + 1, "scene:" + _sc)
            self.tree.addTopLevelItem(_r)
            return _r

        only3d = (self.scope == "3d")
        roots = {_sc: _mkroot(_sc, _ti) for _sc, _ti in SCENE_GROUPS}
        # 🔴 2026-10-15 老倪: 「为什么还有很多蓝色场景的信号也加在了? 插拔是绿色信号, 如果需要重名信号,
        #   就要在绿色区域重新加载」—— sstrace 源(trace_live.json)是**插拔(SS-EPI-CORNER)与
        #   摆盘(SS-TRAY-PLACE)两个 3D 面板共写的唯一快照**(见 publish_trace_live 的防串台注释):
        #   同一批键名两个场景都要用。规则: 这些键在**每个场景区域内各自加载一份**, 行色 = 该区域场景色;
        #   否则按旧口径"按标签二选一"会把光模块_x/末端_x/接触概率 等打给摆盘 ⇒ 插拔区里看着缺一半、
        #   另一半跑到蓝组去(老倪现场看到的就是这个)。
        _TRACE_SCENES = ("插拔场景", "摆盘场景")
        _act = self._active_scene()          # 当前场景: 决定重名行可勾选性 + 组默认展开/折叠
        # 1) 本机真值流: 按打标落到 插拔 / 摆盘 / 基础 三组 (AR 有二级分组, 见下)
        host_bufs = [b for b in self.store.bufs.values() if b.src not in ("ros", "ds", "file")]
        _n_host = 0
        for b in sorted(host_bufs, key=lambda x: (self._scene_rank(x.key), x.key)):
            if filt and filt not in b.key.lower():
                continue
            if b.key.startswith("ar."):
                continue                        # AR 单独成组(二级), 见 1b
            if b.key.startswith("sstrace."):
                for _sc in _TRACE_SCENES:       # 重名信号: 每个场景区域重新加载一份
                    roots[_sc].addChild(self._make_item(b, scene=_sc,
                                                        interactive=((not _act) or _act == _sc)))
                _n_host += 1
                continue
            _sc = _scene_of(b.key)
            roots[_sc if _sc in roots else "基础场景"].addChild(self._make_item(b))
            _n_host += 1
        if not _n_host:
            _it = QTreeWidgetItem(["（暂无本机真值流数据 — 在画布点 ▶运行 跑一轮；真机位姿/安全等未分类信号会进「基础场景」组）",
                                   "-", "-", "-", "-"])
            _it.setForeground(0, QColor(C_DIM))
            roots["插拔场景"].addChild(_it)
        # 1b) 🥽 AR 场景 · 空间点位 / AOI 话题
        #   🔴 2026-10-12 老倪: 「实时监控信号的窗口, AOI 相关的信号, 也没有啊」——
        #     根因: 这一段原来套在 `if not only3d:` 里, 而打开窗口默认的「数据范围」= 3D 场景实时数据,
        #     于是 AOI/AR 话题(176 条)整组被挡在外面, 一眼看不到。⇒ 与数据范围无关, **一律列出**。
        ar_items = sorted([b for b in self.store.bufs.values() if b.key.startswith("ar.")],
                          key=lambda x: (self._scene_rank(x.key), x.key))
        _ar_root = roots["AR场景"]
        if ar_items:
            grp = self._ar_groups()
            by_g = {}
            for b in ar_items:
                if filt and filt not in b.key.lower():
                    continue
                by_g.setdefault(grp.get(b.key[3:], "AR 场景 · 其它信号"), []).append(b)
            for g in sorted(by_g):
                _sid = "ar:" + g
                gnode = QTreeWidgetItem([g, "", "", ""])
                gnode.setForeground(0, QColor(SCENE_COLORS["AR场景"]))   # 二级标题也用场景色(老倪: AR 下面别是白的)
                gnode.setData(0, Qt.UserRole + 1, _sid)
                for b in by_g[g]:
                    gnode.addChild(self._make_item(b, checked=b.key in self.selected))
                _inuse = any(k.startswith("ar.") and (grp.get(k[3:]) == g) for k in self.selected)
                gnode.setExpanded(False if _sid in self._collapsed
                                  else bool(filt) or _inuse or _sid in self._expanded)
                _ar_root.addChild(gnode)
        else:
            _it = QTreeWidgetItem(["（AR/AOI 总线此刻没有数据帧 — ar_aoi_live.json 未在写; 紫组信号由 tools/ar_aoi_bus.py 发布）",
                                   "-", "-", "-", "-"])
            _it.setForeground(0, QColor(C_DIM))
            _ar_root.addChild(_it)
        # 2) Orin ROS2 话题 (未分类 ⇒ 挂「⚪ 基础场景」组下)
        ros_root = QTreeWidgetItem(["Orin ROS2 话题 (未分类 → 基础场景)", "", ""])
        ros_root.setForeground(0, QColor(C_DIM))
        ros_root.setData(0, Qt.UserRole + 1, "base:ros")
        roots["基础场景"].addChild(ros_root)
        if self.catalog and not only3d:
            for topic, meta in sorted(self.catalog.items()):
                tnode = QTreeWidgetItem([f"{topic}  ({meta['type'].split('/')[-1]})", "", ""])
                tnode.setForeground(0, QColor(C_DIM))
                rows = [f for f in meta["fields"] if not filt or filt in (topic + "." + f).lower()]
                if filt and not rows:
                    continue
                for f in rows:
                    if f.endswith("[*]"):
                        # 数值序列: 运行时按实际长度展开 (采样器上限 16) ⇒ 列成可勾选的下标
                        fnode = QTreeWidgetItem([f[:-3], "", "", "", ""])
                        fnode.setForeground(0, QColor(C_DIM))
                        for i in range(16):
                            key = "ros." + (f"{topic}.{f[:-3]}[{i}]").lstrip("/")
                            b = self.store.get(key, "ros")
                            fnode.addChild(self._make_item(b, checked=key in self.selected,
                                                           label=f"[{i}]"))
                        tnode.addChild(fnode)
                    else:
                        key = "ros." + (topic + "." + f).lstrip("/")
                        b = self.store.get(key, "ros")
                        tnode.addChild(self._make_item(b, checked=key in self.selected))
                _inuse = any(k.startswith("ros." + topic.lstrip("/") + ".") for k in self.selected)
                tnode.setExpanded(bool(filt) or _inuse or tnode.text(0) in self._expanded)
                ros_root.addChild(tnode)
        else:
            ros_root.addChild(QTreeWidgetItem(["（点「⟳ 话题目录」从 Orin 拉取）", "", ""]))
        # 3) 🌐 全局数据空间 (DDS 总线帧) — 与「数据空间」页同一份真源 (未分类 ⇒ 挂基础场景组下)
        ds_root = QTreeWidgetItem(["🌐 全局数据空间 (DDS 总线)", "", ""])
        ds_root.setForeground(0, QColor("#bc8cff"))
        ds_root.setData(0, Qt.UserRole + 1, "base:ds")
        roots["基础场景"].addChild(ds_root)
        if not only3d:
            ds_topics = {}
            if self.ds_src is not None:
                for t, meta in self.ds_src.seen.items():
                    ds_topics[t] = dict(meta)
                for t, meta in self.ds_src.declared.items():
                    ds_topics.setdefault(t, {"type": meta.get("type", ""), "hz": meta.get("hz"),
                                             "pubs": meta.get("pubs"), "wall": 0.0})
            try:
                all_keys = self.store.keys()
            except Exception:
                all_keys = []
            for topic, meta in sorted(ds_topics.items()):
                pref = "ds." + topic.lstrip("/") + "."
                keys = [k for k in all_keys if k.startswith(pref)]
                if filt and filt not in topic.lower() and not any(filt in k.lower() for k in keys):
                    continue
                _t = str(meta.get("type") or "")
                typ = _t.split("::")[-1].split("/")[-1] or "?"
                extra = ""
                if meta.get("hz") not in (None, -1.0):
                    extra += f" · {float(meta['hz']):.2f}Hz"
                if meta.get("pubs") is not None:
                    extra += f" · 发布者{meta['pubs']}"
                if not keys:
                    extra += " · 采集窗内无帧"
                tnode = QTreeWidgetItem([f"{topic}  ({typ}){extra}", "", ""])
                tnode.setForeground(0, QColor(C_DIM))
                for k in sorted(keys):
                    tnode.addChild(self._make_item(self.store.get(k, "ds"), checked=k in self.selected))
                if not keys:
                    tnode.addChild(QTreeWidgetItem(["（该话题此刻没有数据帧）", "", ""]))
                _inuse = any(k.startswith(pref) for k in self.selected)
                tnode.setExpanded(bool(filt) or _inuse or tnode.text(0) in self._expanded)
                ds_root.addChild(tnode)
        # 4) 组展开/折叠: 用户点过的优先; 其余 **当前场景展开, 非当前场景默认折叠隐藏**
        #    (老倪 2026-10-15: 「蓝色区域你得折叠隐藏啊」—— 摆盘蓝那一大片不该占着屏幕)
        for _sc, _r in roots.items():
            _sid = "scene:" + _sc
            if _sid in self._collapsed:
                _r.setExpanded(False)
            elif _sid in self._expanded or bool(filt):
                _r.setExpanded(True)                       # 用户手动展开过 / 正在过滤 → 尊重
            elif _sc == "基础场景" or not _act:
                _r.setExpanded(True)                       # 基础场景保持可见(未分类信号要看)
            else:
                _r.setExpanded(_sc == _act)                # 当前场景展开, 其它场景组折叠
        for _sc, _ph in (("摆盘场景", "（摆盘场景链路此刻无数据帧: 真空/吸盘/料盘/槽位话题未接 — 真机网络通 + 摆盘场景激活后, 蓝色信号出现在这里）"),
                         ("基础场景", "（本机真值流/ROS/DDS 此刻没有数据帧）")):
            _r = roots[_sc]
            if _r.childCount() == 0:
                _it = QTreeWidgetItem([_ph, "-", "-", "-", "-"])
                _it.setForeground(0, QColor(C_DIM))
                _r.addChild(_it)
        self.tree.blockSignals(False)
        # 🔴 2026-10-15 老倪: 「你重启信号分析」后要**一眼看到插拔(绿)**。原来建完树视图停在别处
        #   (树很长, 默认落点/旧滚动位置不在首组) ⇒ 看着像"绿色信号不在"。规则: 首次建树 + 切场景排序后,
        #   都把视图滚到目标场景组 (没切排序时滚第一个场景组 = 插拔绿), 组本身仍按 绿/蓝/紫/白 恒定顺序。
        try:
            _tgt = roots.get(self._scene_sort) if self._scene_sort else None
            if _tgt is None:
                _tgt = roots.get("插拔场景")
            if _tgt is not None:
                self.tree.scrollToItem(_tgt, QAbstractItemView.PositionAtTop)
        except Exception:                                                       # noqa: BLE001
            pass
        self._apply_default_selection()
        self._update_tree_values()

    def _ar_groups(self):
        """🥽 AR/AOI 信号总线 live 文件里的 信号→组 映射 (按 mtime 缓存; 读不到就空 —— 静默降级)。"""
        p = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
        try:
            mt = os.path.getmtime(p)
        except OSError:
            return {}
        if getattr(self, "_ar_grp", None) is not None and getattr(self, "_ar_grp_mt", None) == mt:
            return self._ar_grp
        out = {}
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            for k in (d.get("s") or {}):
                st = (d.get("groups") or {}).get(k)
                if st:
                    out[k] = st
        except Exception:                                                         # noqa: BLE001
            out = {}
        self._ar_grp, self._ar_grp_mt = out, mt
        return out

    def _fill_cfg(self):
        """顶部「当前配置」横幅 —— 让实时监控一眼看出"正在看的是哪套配置"。

        真源 = tools/config_sheet.py 导出的配置单 (outputs/config_sheets/配置单_<TASK>_latest.json);
        没有配置单就退回 config/ss_task_binding.json + config/tasks/tasks.json 现算一行(不编数字)。
        """
        import glob as _g
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cands = sorted(_g.glob(os.path.join(root, "outputs", "config_sheets", "配置单_*_latest.json")),
                       key=os.path.getmtime, reverse=True)
        mt = os.path.getmtime(cands[0]) if cands else None
        if mt is not None and mt == self._cfg_mtime:
            return
        self._cfg_mtime = mt
        txt = ""
        if cands:
            try:
                d = json.load(open(cands[0], encoding="utf-8"))
                t, meta = (d.get("任务") or {}), (d.get("_meta") or {})
                col = t.get("场景色") or "#c9d1d9"
                txt = ("⚙️ <b>当前配置</b> <b>%s</b> %s · 场景 <span style='color:%s'><b>%s</b></span>"
                       " · 配方 %s · 工艺 %d 步 · 启用节点 %d · 档位 %d · 参数覆盖 %d"
                       " <span style='color:#8b949e'>[配置单 %s · 导出 %s · 真源 任务/绑定/画布/参数注册表]</span>") % (
                    t.get("task_id") or "—", t.get("name") or "", col, t.get("场景") or "—",
                    t.get("recipe_type") or "—", len(t.get("工艺步骤") or []),
                    (d.get("画布") or {}).get("启用节点数") or 0, len(t.get("档位") or {}),
                    len(t.get("参数覆盖") or {}), os.path.basename(cands[0]), meta.get("generated_at") or "—")
            except Exception:                                                  # noqa: BLE001
                txt = ""
        if not txt:
            try:
                sys.path.insert(0, os.path.join(root, "tools"))
                import ss_task_bind as _sb
                b = _sb.build()
                tid = b.get("active_task") or "—"
                tk = next((x for x in (b.get("tasks") or []) if x["task_id"] == tid), {})
                txt = ("⚙️ <b>当前配置</b> <b>%s</b> %s · 工艺 %d 步 · 启用节点 %d · "
                       "<span style='color:#8b949e'>配置单未导出 (跑 python3 tools/config_sheet.py)</span>") % (
                    tid, tk.get("name") or "", len(tk.get("steps") or []), len(tk.get("enabled_nodes") or []))
            except Exception:                                                  # noqa: BLE001
                txt = "⚙️ <b>当前配置</b> <span style='color:#8b949e'>未读到任务配置 (config/ss_task_binding.json)</span>"
        try:
            self._cfg_lab.setText(txt)
        except Exception:                                                      # noqa: BLE001
            pass

    def _disp_name(self, key):
        """列表显示的短名: 去掉来源前缀 (来源已由上层分组写清), 名字列才容得下。
        全路径 + Min/Max + 点数 都放 tooltip。"""
        if key.startswith("ros."):
            return "/" + key[4:]                     # ROS 保留话题全路径 (老倪要看 topic)
        for pre in ("sstrace.", "ds.", "ar."):
            if key.startswith(pre):
                return key[len(pre):]
        return key

    # 3D 场景那批信号的"血缘": 哪些是真机话题, 哪些是 L2 引擎算的 (老倪要能一眼看到)
    SS_TRACE_SRC = (                                  # 顺序要紧: 长前缀必须排在短前缀前面
        ("光模块头到孔", "L2 引擎 (孔口 objects3d.json)"),
        ("吸嘴到槽位", "L2 引擎 (槽位 objects3d.json) · 摆盘"),
        ("末端", "/robot/tcp_pose (Orin 50Hz)"),
        ("光模块头", "YOLO 3D 检测 (旁路 JSON)"),
        ("光模块", "YOLO 3D 检测 (旁路 JSON)"),
        ("真空吸持", "/gripper_pos (Orin) · 摆盘=吸附建立(0.9)"),
        ("夹爪", "/gripper_pos (Orin)"),
        ("环境接触", "/robot/force_torque (Orin)"),
        ("吸附力", "/robot/force_torque (Orin) · 摆盘=吸持力"),
        ("夹持", "/robot/force_torque (Orin)"),
    )

    def _src_hint(self, key):
        if key.startswith("ar."):
            return "🥽 AR/AOI 信号总线 · " + self._ar_groups().get(key[3:], "AR 场景")
        if key.startswith("sstrace."):
            n = key[8:]
            for pre, s in self.SS_TRACE_SRC:
                if n.startswith(pre):
                    return s
            return "L2 状态空间引擎 (无话题)"
        if key.startswith("ros."):
            return "Orin ROS2" + (" · " + key[4:].split(".")[0] if "/" in key[:24] else "")
        if key.startswith("ds."):
            return "DDS · " + key[3:].split(".")[0]
        return "本机真值流 (JSON)"

    def _scene_rank(self, key):
        """排序秩: 当前选中色 = 0(置顶), 其余 = 1(仍显示, 不隐藏)。白(未选) ⇒ 全部同级(不排序)。"""
        if not getattr(self, "_scene_sort", ""):
            return 0
        if SST is None:
            return 0
        try:
            return 0 if SST.tag(key) == self._scene_sort else 1
        except Exception:                                                     # noqa: BLE001
            return 1

    def _active_scene(self):
        """当前正在看哪个场景: 排序里选中的场景优先; 否则取画布数据源场景真源 (ss_scene_switch src_state)。

        用途(老倪 2026-10-15): ① 非当前场景的重名信号行不可勾选 ② 非当前场景的场景组默认**折叠隐藏**
        (「摆盘的蓝色信号, 怎么也有 tick 小对号?」「蓝色区域你得折叠隐藏啊」)。
        """
        if getattr(self, "_scene_sort", ""):
            return self._scene_sort
        try:
            import ss_scene_switch as _ssw
            return str(_ssw.now().get("src_state") or "")
        except Exception:                                                       # noqa: BLE001
            return ""

    def _scene_sync_lab(self):
        """标题行实况: 当前画布数据源/场景 + 各色信号计数(照实报, 不编)。"""
        try:
            import ss_scene_switch as _ssw
            _cur = _ssw.now().get("src_state") or "?"
        except Exception:                                                     # noqa: BLE001
            _cur = "?"
        _n = {}
        if SST is not None:
            try:
                for _k in list(self.store.bufs.keys()):     # 快照键: 实时源线程同时在加键, 直接迭代会 RuntimeError
                    _s = SST.tag(_k) or "未分类"
                    _n[_s] = _n.get(_s, 0) + 1
            except Exception:                                                 # noqa: BLE001
                _n = {}
        _sel = self._scene_sort or "全部(白)"
        self._scene_lab.setText("场景排序: %s · 当前数据源场景: %s · 计数 %s"
                                % (_sel, _cur, " ".join("%s=%d" % (k, v) for k, v in sorted(_n.items())) or "—"))

    def _set_scene_sort(self, val):
        self._scene_sort = val or ""
        for _v, _b in getattr(self, "_scene_btns", {}).items():
            _on = (_v == self._scene_sort)
            _b.setStyleSheet("font-weight:%s" % ("700" if _on else "400"))
        self._log("🎨 信号排序: %s" % (self._scene_sort or "全部(白) — 所有颜色的信号都显示"))
        self._scene_sync_lab()
        self._fill_tree()

    def _make_item(self, b, checked=False, label=None, scene=None, interactive=True):
        name = label or self._disp_name(b.key)
        it = QTreeWidgetItem([name, "-", "-", self._src_hint(b.key)])
        it.setToolTip(0, f"{b.key}\n来源 {b.src} · 点数 {b.n}")
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Checked if (checked or b.key in self.selected) else Qt.Unchecked)
        it.setData(0, Qt.UserRole, b.key)
        it.setForeground(0, QColor(b.color))
        # 🔴 2026-10-15 老倪: 「为什么还有很多蓝色场景的信号也加在了? 插拔是绿色信号, 如果需要重名信号,
        #   就要在绿色区域重新加载」⇒ 多场景共写的源(trace_live.json)里, 每个场景区域各自加载一份,
        #   行色 = **该区域场景色**(不再按"这个键被打了哪个标签"二选一 —— 那会让插拔区里冒出摆盘蓝)。
        # 老倪 2026-10-15 后续: 「摆盘的蓝色信号, 怎么也有 tick 小对号?」—— 同一份重名键在两区都有,
        #   勾选状态原来按 key 走 ⇒ 绿区勾上"末端_x/接触概率"时, 蓝区同名行也被打勾(看着像摆盘也在监视)。
        #   规则: **非当前场景区域的那一份不可勾选、不带勾**(灰掉), 勾选只在当前场景区域生效。
        if scene:
            it.setText(0, "● " + it.text(0))
            _c = SCENE_COLORS.get(scene, C_WHITE)
            it.setForeground(0, QColor(_c))
            if not interactive:
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setForeground(0, QColor(C_DIM))
            it.setToolTip(0, it.toolTip(0) + "\n场景: %s (%s) ← 本场景区域加载 (该数据源为多场景共写)%s"
                          % (scene, _c, "" if interactive else "\n（非当前场景 ⇒ 不可勾选，不在本区画波形）"))
            return it
        # 🥽 场景标记(老倪 2026-10-12: 「插拔信号绿色; 摆盘信号蓝色; AOI信号紫色; 没有分类的信号都是白色」):
        #   有目标场景 → ● + **场景色**; 没分类 → ○ + **白**(不再沿用曲线色, 否则看着像"乱七八糟的颜色")
        _tagged = False
        if SST is not None:
            try:
                _sc = SST.tag(b.key)
                if _sc:
                    _tagged = True
                    it.setText(0, "● " + it.text(0))
                    it.setForeground(0, QColor(SST.color(b.key)))
                    it.setToolTip(0, it.toolTip(0) + "\n场景: %s (%s) ← 由 tools/sig_scene_tags.py 打标"
                                  % (_sc, SST.color(b.key)))
                else:
                    it.setText(0, "○ " + it.text(0))
                    it.setForeground(0, QColor(C_WHITE))
                    it.setToolTip(0, it.toolTip(0) + "\n场景: 未分类 (白)")
            except Exception:                                                 # noqa: BLE001
                pass
        return it

    def _apply_col_widths(self):
        """名字列必须真看得见。Qt 加样式表后, header 的列宽/模式会在 polish 时被重置
        (离屏平台不重置、真机 xcb 上 5 列全变 viewport/5=80px ⇒ 名字被挤没), 所以显示后要再设一遍。"""
        try:
            h = self.tree.header()
            h.setStretchLastSection(False)               # 否则最后一列把名字列空间又吃掉
            h.setMinimumSectionSize(28)                  # 样式表会把最小列宽抬到 80 ⇒ 设的 54/68 全被夹成 80, 5 列均分
            h.setSectionResizeMode(0, QHeaderView.Stretch)
            for i, w in ((1, 78), (2, 54), (3, 168)):   # 值 / 帧龄 / 来源话题 (Min·Max 移进 tooltip)
                h.setSectionResizeMode(i, QHeaderView.Interactive)
                self.tree.setColumnWidth(i, w)
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_col_widths()

    def _all_items(self, parent=None):
        parent = parent or self.tree.invisibleRootItem()
        for i in range(parent.childCount()):
            ch = parent.child(i)
            yield ch
            yield from self._all_items(ch)

    def _on_item_changed(self, item, col):
        if col != 0:
            return
        # 🔴 2026-10-15 老倪「信号分析, 主窗口, 没有波形信号啊」——真根因(实测): 上一步让重名信号在
        #   插拔/摆盘两个区域各加载一份后, **两份行的 key 相同**; 非当前场景那一份在建树时被强制
        #   setCheckState(Unchecked) (必做, 否则蓝区跟着打勾), 这个 Unchecked 会走 itemChanged ⇒ 把
        #   同名 key 从 self.selected 里**摘掉** ⇒ 连带当前场景(绿区)那条曲线也没了 ⇒ 主窗口空图。
        #   规则: 勾选状态只由**当前场景区域那一份**(可勾选的 interactive 行)说了算。
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        checked = item.checkState(0) == Qt.Checked
        if checked and key not in self.selected:
            self.selected.append(key)
        elif not checked and key in self.selected:
            self.selected.remove(key)
        self.wave.set_curves(list(self.selected))
        if self.catalog and any(k.startswith("ros.") for k in self.selected) and self.running:
            topics_now = self._ros_topics()
            if self.ros_src is None or sorted(self.ros_src.topics) != topics_now:
                if self.ros_src:
                    self.ros_src.stop()
                self.ros_src = RosTopicSource(self.store, topics_now)
                self.ros_src.start()
                self._log(f"↻ ROS 订阅更新: {len(topics_now)} 个话题")

    def _toggle_checked(self):
        for it in self.tree.selectedItems():
            if it.data(0, Qt.UserRole):
                it.setCheckState(0, Qt.Unchecked if it.checkState(0) == Qt.Checked else Qt.Checked)

    def _tree_menu(self, pos):
        items = [i for i in self.tree.selectedItems() if i.data(0, Qt.UserRole)]
        if not items:
            return
        m = QMenu(self)
        m.setStyleSheet(f"QMenu{{background:{C_BG2};color:{C_WHITE};border:1px solid {C_BORDER};}}")
        a_add = m.addAction("加入波形" if True else "")
        a_del = m.addAction("移除选中")
        a_hl = m.addAction("高亮加粗 (Highlight)")
        a_x = m.addAction("用作 X 轴 (Use as X-Axis)")
        a_col = m.addAction("换颜色")
        m.addSeparator()
        a_clr = m.addAction("清空所有已选信号")
        act = m.exec_(self.tree.viewport().mapToGlobal(pos))
        keys = [i.data(0, Qt.UserRole) for i in items]
        if act == a_add:
            for it in items:
                it.setCheckState(0, Qt.Checked)
        elif act == a_del:
            for it in items:
                it.setCheckState(0, Qt.Unchecked)
        elif act == a_hl:
            for k in keys:
                b = self.store.get(k)
                b.bold = 5 if b.bold < 5 else 2
            self.wave.apply_style()
            self._log(f"B 加粗 {len(keys)} 条")
        elif act == a_x:
            self.x_signal = keys[0]
            self._log(f"X 轴 ← {self.x_signal}")
        elif act == a_col:
            for k in keys:
                b = self.store.get(k)
                idx = (TRACE_COLORS.index(b.color) + 1) % len(TRACE_COLORS) if b.color in TRACE_COLORS else 0
                b.color = TRACE_COLORS[idx]
            self.wave.set_curves(list(self.selected))
            self._log("换颜色")
        elif act == a_clr:
            for k in list(self.selected):
                self.selected.remove(k)
            self._fill_tree()
            self.wave.set_curves([])

    # ─────────── 光标 ───────────
    def _on_diff(self, on):
        self.diff_cursor = on
        self.wave.set_cursors(self.cursor_on, on, self._update_cursor_text)
        self._update_cursor_text()

    def _on_cursor(self, on):
        self.cursor_on = on
        self.wave.set_cursors(on, self.diff_cursor, self._update_cursor_text)
        self.cursor_lb.setVisible(on)
        if on and self.wave.c1 is not None:
            for k in self.wave.curves[:1]:
                b = self.store.get(k)
                if b.n:
                    t, v = b.arrays()
                    self.wave.c1.setValue(float(t[-1] - self.store.t0) - 1.0)
                    self.wave.c2.setValue(float(t[-1] - self.store.t0))
        self._update_cursor_text()

    def _update_cursor_text(self):
        if not self.cursor_on or self.wave.c1 is None:
            self.cursor_lb.setText("")
            return
        a, b_ = float(self.wave.c1.value()), float(self.wave.c2.value())
        t0 = self.store.t0
        # 🕒 A/B 也标绝对时刻 (老倪拿它和 3D 场景 HUD 上的时刻对)
        rows = [f"<span style='color:{C_BLUE}'>A</span>={a:.3f}s"
                f"({clock_str(t0 + a, ms=False)}) "
                f"<span style='color:{C_ORANGE}'>B</span>={b_:.3f}s"
                f"({clock_str(t0 + b_, ms=False)}) "
                f"<b>Δt={abs(b_ - a):.3f}s</b>"
                + (f"  <span style='color:{C_ORANGE}'>B@</span>{clock_str(t0 + b_)}"
                   if self.wave.abs_on else "")]
        for k in self.wave.curves[:8]:
            buf = self.store.bufs.get(k)
            if buf is None or buf.n < 2:
                continue
            t, v = buf.arrays()
            t = t - t0                      # 曲线 x 是相对秒 ⇒ 插值必须同口径
            va = float(np.interp(a, t, v))
            vb = float(np.interp(b_, t, v))
            rows.append(f"<span style='color:{buf.color}'>{k}</span>: {va:.4f} → {vb:.4f} "
                        f"<b>Δ={vb - va:+.4f}</b>")
        self.cursor_lb.setText("  |  ".join(rows))

    # ─────────── 记录 / 导出 / 导入 ───────────
    def _on_log(self, on):
        if on:
            os.makedirs(LOG_DIR, exist_ok=True)
            self.log_path = os.path.join(LOG_DIR, time.strftime("graphic_%Y%m%d_%H%M%S.csv"))
            self.logger = open(self.log_path, "w", newline="", encoding="utf-8")
            w = csv.writer(self.logger)
            w.writerow(["signal", "t_rel_s", "wall", "value", "age_s", "latency_ms"])
            self.log_rows = 0
            self._log(f"⏺ 开始记录 → {self.log_path}")
        else:
            if self.logger:
                self.logger.close()
                self.logger = None
                self._log(f"⏹ 记录结束 ({self.log_rows} 行) → {self.log_path}")

    def export_csv(self):
        keys = list(self.selected) or self.store.keys()
        if not keys:
            self._log("⚠️ 无数据可导出")
            return
        os.makedirs(LOG_DIR, exist_ok=True)
        p = os.path.join(LOG_DIR, time.strftime("export_%Y%m%d_%H%M%S.csv"))
        n = 0
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["signal", "t_rel_s", "value", "age_s"])
            t0 = self.store.t0
            for k in keys:
                b = self.store.bufs.get(k)
                if b is None or b.n == 0:
                    continue
                t, v = b.arrays()
                for i in range(b.n):
                    w.writerow([k, round(float(t[i] - t0), 4), float(v[i]), b.age])
                    n += 1
        self._log(f"⤒ 已导出 CSV: {p} ({n} 行)")

    def export_png(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        p = os.path.join(LOG_DIR, time.strftime("graphic_%Y%m%d_%H%M%S.png"))
        self.wave.glw.grab().save(p)
        self._log(f"⤒ 已导出 PNG: {p}")

    def import_csv(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入记录 CSV (CANoe: Import)", LOG_DIR, "CSV (*.csv)")
        if not p:
            return
        self.stop()
        data = {}
        t0 = None
        try:
            with open(p, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    k = row["signal"]
                    tt = float(row["t_rel_s"])
                    t0 = tt if t0 is None else min(t0, tt)
                    data.setdefault(k, []).append((tt, float(row["value"]), float(row.get("age_s") or -1)))
        except Exception as e:
            self._log(f"⚠️ 导入失败: {e}")
            return
        base = time.monotonic()
        with self.store.lock:
            for k, rows in data.items():
                b = SignalBuffer(k, TRACE_COLORS[len(self.store.bufs) % len(TRACE_COLORS)], "file")
                for tt, vv, ag in rows:
                    b.push(base + (tt - t0), vv, ag)
                self.store.bufs[k] = b
        self.selected = list(data.keys())
        self._fill_tree()
        self.wave.set_curves(list(self.selected))
        self.wave.fit_y()
        self._log(f"⤓ 已导入 {p} · {sum(len(v) for v in data.values())} 点 / {len(data)} 信号")

    # ─────────── 刷新 ───────────
    def _fit(self):
        """Fit signals: Y 自适应 + X 拉到全数据 (CANoe: Fit)"""
        self.wave.fit_y()
        ends = [float(b.arrays()[0][-1]) for b in self.store.bufs.values() if b.n]
        starts = [float(b.arrays()[0][0]) for b in self.store.bufs.values() if b.n]
        if ends and starts and self.wave.main_plot is not None:
            self.follow = False
            self.b_follow.setChecked(False)
            self.wave.main_plot.setXRange(min(starts), max(ends), padding=0.02)
        self._log("⤢ Fit: 波形自适应")

    def _pan(self, fx, fy):
        """平移 (CANoe: Pan up/down/left/right); 时间轴平移即取消跟随"""
        p = self.wave.main_plot
        if p is None:
            return
        if fx:
            self.follow = False
            self.b_follow.setChecked(False)
            x0, x1 = p.viewRange()[0]
            d = (x1 - x0) * fx
            p.setXRange(x0 + d, x1 + d, padding=0)
        if fy:
            y0, y1 = p.viewRange()[1]
            d = (y1 - y0) * fy
            p.setYRange(y0 + d, y1 + d, padding=0)

    def _set_yrange(self):
        """手动 Y 轴范围 (CANoe: Graphic Configuration → Signals/Axes)"""
        from PyQt5.QtWidgets import QInputDialog
        p = self.wave.main_plot
        if p is None:
            return
        y0, y1 = p.viewRange()[1]
        txt, okk = QInputDialog.getText(self, "Y 轴范围", "最小,最大 (逗号分隔):",
                                        text=f"{y0:.4f},{y1:.4f}")
        if not okk or not txt:
            return
        try:
            lo, hi = [float(x) for x in txt.replace("，", ",").split(",")[:2]]
            p.setYRange(lo, hi, padding=0)
            self._log(f"↕ Y 轴范围 = [{lo}, {hi}]")
        except Exception as e:
            self._log(f"⚠️ Y 轴范围解析失败: {e}")

    def _zoom(self, factor):
        p = self.wave.main_plot
        if p is None:
            return
        x0, x1 = p.viewRange()[0]
        c = (x0 + x1) / 2.0
        half = (x1 - x0) / 2.0 * factor
        self.follow = False
        self.b_follow.setChecked(False)
        p.setXRange(c - half, c + half, padding=0)

    def _poll_playback(self):
        """▶ 每帧读 3D 场景快照 (= 它的播放进度真源) ⇒ 波形页竖线跟着 3D 进度条走。"""
        try:
            st = os.stat(PLAYBACK_FILE)
            with open(PLAYBACK_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            age = max(0.0, time.time() - st.st_mtime)
            pb = {"frame": raw.get("帧"), "total": raw.get("总帧"),
                  "t_s": raw.get("时间_s"), "ts": raw.get("ts"),
                  "age": age, "fresh": age < 2.0}
        except Exception:                                                      # noqa: BLE001
            pb = {"fresh": False, "age": -1.0}
        self.pb = pb
        if getattr(self, "wave", None) is not None:
            self.wave.set_playback(pb)

    def _wave_dirty(self, xr):
        """这一帧要不要重画波形?

        老倪 2026-10-12「感觉就是反映慢 / 窗口拖不动 / 三角点了没反应」—— 真因之一是 **20Hz 无条件重画**
        (250 条曲线 × UI_FPS=20 ⇒ GUI 线程一直忙, 输入事件排在后面)。判据: 有新样本 / 播放游标动了 /
        跟随滚动 / 暂停切换 ⇒ 重画; 否则这一帧什么都不做。
        """
        _pb = getattr(self, "pb", None) or {}
        sig = (self.store.total_pts, _pb.get("frame"), _pb.get("fresh"), self.paused, self.follow,
               len(self.wave.curves))
        if xr is not None or sig != getattr(self, "_wave_sig", None):
            self._wave_sig = sig
            return True
        return False

    def _tick(self):
        # 0) ▶ 3D 场景播放进度 (老倪: 拖 3D 进度条 ⇒ 这里的竖线要同步左右移动)
        self._poll_playback()
        # 1) 出波形
        keys = list(self.wave.curves)
        xr = None
        if not self.paused and keys and self.follow and self.window_s > 0:
            end = None
            for k in keys:
                b = self.store.bufs.get(k)
                if b is not None and b.n:
                    t, _ = b.arrays()
                    e = float(t[-1]) if b.scene else float(t[-1]) - self.store.t0   # 与曲线 x 同口径
                    end = e if end is None else max(end, e)
            if end is not None:
                xr = (end - self.window_s, end)
        if self._wave_dirty(xr):
            self.wave.refresh(x_range=xr)

        # 2) 记录
        if self.logger is not None:
            w = csv.writer(self.logger)
            now = time.monotonic()
            for k in keys:
                b = self.store.bufs.get(k)
                if b is not None and b.n:
                    w.writerow([k, round(now - self.store.t0, 4),
                                time.strftime("%Y-%m-%dT%H:%M:%S"), b.last_val, b.age, 0])
                    self.log_rows += 1
            self.logger.flush()

        # 3) 状态 + 图例 + 信号栏 (4 次/秒)
        if time.monotonic() - self._last_tree_update > 0.25:
            self._last_tree_update = time.monotonic()
            # 信号集合/目录变了就重建左侧目录 (主线程里做, 不依赖工作线程回调)
            sig = (len(self.catalog or {}), tuple(sorted(self.store.keys())))
            if sig != self._tree_sig and (time.monotonic() - self._last_fill) > 1.5:
                self._fill_tree()
            self._update_tree_values()
            self._update_status(keys)

    def _update_status(self, keys):
        src_state = []
        if self.ros_src is not None:
            src_state.append(f"Orin: {self.ros_src.state}")
        if self.host_src is not None:
            src_state.append("本机: 采集中")
        state = "● 采样中" if self.running else "● 已停止"
        if self.paused:
            state = "⏸ 已暂停(仍记录)"
        ages = []
        for k in keys:
            b = self.store.bufs.get(k)
            if b is not None and b.age >= 0:
                ages.append(b.age)
        agestr = f" · 帧龄 {min(ages):.2f}s" if ages else " · 帧龄 —"
        self.lb_state.setText(state)
        self.lb_state.setStyleSheet(
            f"color:{C_ORANGE if self.paused else (C_GREEN if self.running else C_RED)}; font-size:13px;")
        # 🕒 数据时刻 = 最新样本自己的时刻 (3D 场景 HUD 上写的是同一个) ⇒ 一眼对得上
        newest = None
        for k in keys:
            _b = self.store.bufs.get(k)
            if _b is not None and _b.n:
                _t, _ = _b.arrays()
                if len(_t):
                    newest = float(_t[-1]) if newest is None else max(newest, float(_t[-1]))
        clk = f" · 🕒 数据时刻 {clock_str(newest)}" if newest is not None else ""
        pb = getattr(self, "pb", None) or {}
        if pb.get("fresh") and pb.get("t_s") is not None:
            clk += (" · ▶ 3D 播放 %s/%s @ 场景 %.3fs" % (pb.get("frame"), pb.get("total"),
                                                        float(pb["t_s"])))
        elif pb:
            clk += " · ▶ 3D 播放已停 (进度条不动/播放完)"
        self.lb_info.setText(f"{' / '.join(src_state)} · 信号 {len(self.selected)} · 点 {self.store.total_pts}"
                             f"{agestr}{clk} · 本机时刻 {time.strftime('%H:%M:%S')}")
        parts = []
        for k in keys[:8]:
            b = self.store.bufs.get(k)
            if b is None or b.last_val is None:
                continue
            parts.append(f"<span style='color:{b.color}'>■</span> {k} <b>{b.last_val:.4f}</b>")
        self.lb_legend.setText("   ".join(parts))

    def _update_tree_values(self):
        if self.tree.topLevelItemCount() == 0:
            return
        for it in self._all_items():
            key = it.data(0, Qt.UserRole)
            if not key:
                continue
            b = self.store.bufs.get(key)
            if b is None or b.last_val is None:
                continue
            v = b.last_val
            it.setText(1, f"{v:.4g}" if abs(v) < 1e5 else f"{v:.3g}")   # 紧凑: 1.79e+09 不再撑列
            it.setText(2, "-" if b.age < 0 else f"{b.age:.2f}s")
            try:                                    # Min/Max 收进 tooltip, 不再占列宽
                it.setToolTip(0, f"{key}\n来源 {b.src} · 点数 {b.n}"
                                 f" · Min {b.vmin:.4g} · Max {b.vmax:.4g}"
                                 if b.vmin is not None else f"{key}\n来源 {b.src} · 点数 {b.n}")
            except Exception:
                pass

    def _log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        try:
            self.log_line.setText(line)      # 页内一行, 可选中复制 (导出路径等)
        except Exception:
            pass
        self.log.emit(line)

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)


# ────────────────────────────────────────────────────────────
# 独立窗口自测: DISPLAY=:0 gui-venv311/bin/python tools/gui/canoe_graphic.py
#   (实时监控页里是同一个控件; 这里单独开一个窗口便于现场看波形)
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QMainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("📈 实时监控 · Graphic 信号分析")
    w = CanoeGraphicWidget()
    w.log.connect(lambda s: print(s, flush=True))
    win.setCentralWidget(w)
    # 🪟 2026-10-12 老倪: 「窗口无法拖放调整窗口大小」—— 真因 = 开窗尺寸超过屏幕
    #   (实测 2017x1131 @ (1934,118), 桌面 3840x1200 ⇒ 右边 111px / 下边 49px 在屏幕外, 抓不到边框)。
    #   ⇒ 开窗按**当前屏幕可用区**收口, 留 40px 余量; 尺寸也可用 GRAPHIC_WIN_GEOM=x,y,w,h 覆盖。
    _g = os.environ.get("GRAPHIC_WIN_GEOM", "")
    _scr = app.primaryScreen()
    _av = _scr.availableGeometry() if _scr is not None else None
    if _g:
        try:
            _x, _y, _ww, _hh = (int(v) for v in _g.replace("x", ",").split(",")[:4])
            win.move(_x, _y)
            win.resize(max(900, _ww), max(600, _hh))
        except Exception:                                                      # noqa: BLE001
            pass
    elif _av is not None:
        _ww = min(1720, max(900, _av.width() - 40))
        _hh = min(1010, max(600, _av.height() - 40))
        win.resize(_ww, _hh)
        win.move(_av.x() + max(0, (_av.width() - _ww) // 2), _av.y() + max(0, (_av.height() - _hh) // 2))
    else:
        win.resize(1720, 1010)
    win.setMinimumSize(900, 600)      # 允许缩小: 不设最小尺寸时布局最小宽会顶死(拖不动)
    win.show()
    if os.environ.get("GRAPHIC_SELFCHECK"):     # 取证钩子: 打印左栏全局坐标 + 把左栏单独存图
        from PyQt5.QtCore import QTimer
        def _shot():
            g = w.tree.mapToGlobal(w.tree.rect().topLeft())
            print(f"SELFCHECK tree_global=({g.x()},{g.y()}) size={w.tree.width()}x{w.tree.height()}",
                  flush=True)
            print("SELFCHECK cols=%s viewport=%d indent=%d elide=%d last_stretch=%s" % (
                [w.tree.columnWidth(i) for i in range(5)], w.tree.viewport().width(),
                w.tree.indentation(), w.tree.textElideMode(),
                w.tree.header().stretchLastSection()), flush=True)
            for it in list(w._all_items())[:8]:
                r0 = w.tree.visualItemRect(it)
                print("SELFCHECK row key=%r name=%r val=%r fg=%s rect=(%d,%d,%dx%d) col0=%d" % (
                    it.data(0, Qt.UserRole), it.text(0), it.text(1),
                    it.foreground(0).color().name(), r0.x(), r0.y(), r0.width(), r0.height(),
                    w.tree.columnWidth(0)), flush=True)
            p = os.environ.get("GRAPHIC_SELFCHECK")
            w.tree.grab().save(p)
            print(f"SELFCHECK saved={p}", flush=True)
        QTimer.singleShot(6000, _shot)

        def _watch():                                  # 每 2s 打一行: 播放状态 vs 竖线位置 (拖动进度条时看它变)
            _pb = getattr(w, "pb", None) or {}
            _mk = w.wave.marks[0].value() if w.wave.marks else None
            _lb = w.wave.mark_lb.toPlainText() if w.wave.mark_lb is not None else ""
            _ax = w.wave.main_plot.getAxis("bottom") if w.wave.main_plot is not None else None
            print("SELFCHECK t=%s pb帧=%s/%s 场景t=%s age=%.2f fresh=%s | 竖线x=%s | %s | 轴=%s" % (
                time.strftime("%H:%M:%S"), _pb.get("frame"), _pb.get("total"), _pb.get("t_s"),
                float(_pb.get("age") or -1), _pb.get("fresh"),
                ("%.3f" % _mk) if isinstance(_mk, float) else _mk, _lb,
                getattr(_ax, "labelText", "")), flush=True)
        _wt = QTimer(); _wt.timeout.connect(_watch); _wt.start(2000)
    sys.exit(app.exec_())
