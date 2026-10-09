#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_bypass_view.py — 📈 旁路实时可视化窗 (状态空间可视化层观察器)

老倪 2026-09-16: 「旁路接到控制台做实时可视化 (当前阶段/残差/接触概率曲线)」

数据源: 旁路运行器心跳 + 逐帧记录 (tools/ss_bypass_run.py → ~/zmax/zmax_data/ss_bypass/)
        与 真机感知最新帧 (ss_remote_tap → ~/zmax/zmax_data/ss_live/)
显示:   ① 数值面板: 当前阶段(13 段状态机) · 残差 · 接触概率 · 旁路步数/采样 · 六层调用数
                    · 零下行自证 (rclpy/publishers/sockets/writes_to_orin) · 缺口计数 · 数据源新鲜度
        ② 两条实时曲线: 残差 (米) 与 接触概率 (0~1), 取最近 N 帧逐帧记录
刷新:   500 ms (QTimer), 数据不新鲜 → 明确显示 "数据流过期 xx s" (不用旧帧冒充实时)
"""
import json
import os
import re
import subprocess
import sys
import time

from PyQt5 import QtCore, QtGui, QtWidgets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_src():
    """旁路数据源模块 (框架层 src/lerobot/datasets/bypass_sensor_source.py)"""
    import importlib.util
    root = os.environ.get("ZMAX_REPO_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    path = os.path.join(root, "src", "lerobot", "datasets", "bypass_sensor_source.py")
    if not os.path.exists(path):
        for up in range(6):
            cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * up),
                                "src", "lerobot", "datasets", "bypass_sensor_source.py")
            cand = os.path.normpath(cand)
            if os.path.exists(cand):
                path = cand
                break
    spec = importlib.util.spec_from_file_location("bypass_sensor_source", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BG = "#0d1117"
PANEL = "#161b22"
FG = "#e6edf3"
DIM = "#8b949e"
C_RES = "#ffa657"      # 残差 = 橙
C_CON = "#58a6ff"      # 接触概率 = 蓝
C_OK = "#3fb950"
C_BAD = "#f85149"

# ── 波形通道定义 (每通道一条独立泳道; min_span = 静止时的最小量程, 防噪声被放大成假波动) ──
BANDS_SS = [
    {"key": "residual", "title": "残差", "unit": "m", "color": C_RES,
     "fmt": (lambda v: f"{v:.4f}"), "min_span": 0.002},
    {"key": "contact_p", "title": "接触概率", "unit": "", "color": C_CON,
     "fmt": (lambda v: f"{v:.3f}"), "fixed": "01"},
    {"key": "dx_real", "title": "真机位移速率", "unit": "m/s", "color": C_OK,
     "fmt": (lambda v: f"{v:.4f}"), "min_span": 0.01},
]
BANDS_REAL = [
    {"key": "tcp_x", "title": "TCP X", "unit": "m", "color": "#ffa657",
     "fmt": (lambda v: f"{v:+.4f}"), "min_span": 1e-4},
    {"key": "tcp_y", "title": "TCP Y", "unit": "m", "color": "#3fb950",
     "fmt": (lambda v: f"{v:+.4f}"), "min_span": 1e-4},
    {"key": "tcp_z", "title": "TCP Z", "unit": "m", "color": "#58a6ff",
     "fmt": (lambda v: f"{v:+.4f}"), "min_span": 1e-4},
    {"key": "force_mag", "title": "插入力 |F|", "unit": "N", "color": "#f778ba",
     "fmt": (lambda v: f"{v:.2f}"), "min_span": 0.1},
    {"key": "force_fz", "title": "轴向力 Fz", "unit": "N", "color": "#d29922",
     "fmt": (lambda v: f"{v:+.2f}"), "min_span": 0.1},
]
SS = (f"QWidget {{ background:{BG}; color:{FG}; font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif; }}"
      f"QLabel {{ color:{FG}; font-size:15px; }}"
      f"QGroupBox {{ border:1px solid #30363d; border-radius:6px; margin-top:14px; padding:10px; }}"
      f"QGroupBox {{ color:{DIM}; font-size:14px; }}"
      f"QGroupBox::title {{ subcontrol-origin: margin; left:12px; padding:0 4px; color:{DIM}; font-size:14px; }}")


class CurveWidget(QtWidgets.QWidget):
    """多泳道实时波形 — 纯 QPainter, 无 GL/第三方依赖

    排版铁律 (老倪 2026-09-18「波形名称和描述的字体有重叠 / 字太小」):
      · 每个通道一条**独立泳道**: 左侧栏放「通道名 + 当前值」, 右侧栏放该泳道量程上下限,
        绘图区只画曲线 —— 文字三处物理分离, 结构上不可能重叠 (旧版名与量程都挤在同一 x 位置)。
      · 字号显式指定 (通道名 13px 粗 / 当前值 17px / 刻度 12px), 不受系统默认小字影响。
    """

    FAM = "Noto Sans CJK SC"

    def __init__(self, bands, title="", parent=None):
        super().__init__(parent)
        self.bands = bands            # [{"key","title","unit","color","fmt","min_span","fixed"}]
        self.title = title
        self.data = {b["key"]: [] for b in bands}
        self.setMinimumHeight(30 + 112 * max(1, len(bands)))
        f = self.font()
        f.setFamily(self.FAM)
        f.setPointSizeF(11.0)
        self.setFont(f)

    def set_series(self, key, pts):
        if key in self.data:
            self.data[key] = list(pts or [])
            self.update()

    def _fonts(self):
        fam = self.font().family() or self.FAM
        return (QtGui.QFont(fam, 12, QtGui.QFont.Bold),      # 通道名
                QtGui.QFont(fam, 16, QtGui.QFont.DemiBold),  # 当前值
                QtGui.QFont(fam, 11),                        # 量程刻度 / 脚注
                QtGui.QFont(fam, 14, QtGui.QFont.DemiBold))  # 组件标题

    def layout(self):
        """绘制几何 — paintEvent 与自检**共用同一套矩形** (自检断言的就是真实绘制位置)"""
        f_t, f_v, f_a, _fh = self._fonts()
        fm_t, fm_v, fm_a = QtGui.QFontMetrics(f_t), QtGui.QFontMetrics(f_v), QtGui.QFontMetrics(f_a)
        W, H = self.width(), self.height()
        n = max(1, len(self.bands))
        head = 30 if self.title else 6
        foot, gap = 24, 10
        band_h = max(fm_t.height() + fm_v.height() + 16, (H - head - foot - gap * (n - 1)) // n)
        gutter = max(fm_t.horizontalAdvance(b["title"]) for b in self.bands) + 20
        right_w = max(fm_a.horizontalAdvance("-0.0000"), fm_a.horizontalAdvance("-100.0")) + 16
        x0, x1 = gutter, max(gutter + 60, W - right_w - 8)
        info = {"x0": x0, "x1": x1, "band_h": band_h, "head": head, "gap": gap, "gutter": gutter,
                "right_w": right_w, "fm_t": fm_t, "fm_v": fm_v, "fm_a": fm_a, "bands": []}
        for i, b in enumerate(self.bands):
            y0 = head + i * (band_h + gap)
            tb = y0 + fm_t.ascent() + 4                        # 通道名基线
            vb = tb + fm_t.descent() + 6 + fm_v.ascent()       # 当前值基线 (在通道名下方)
            info["bands"].append({
                "y0": y0, "title_baseline": tb, "value_baseline": vb,
                "title_rect": QtCore.QRect(6, tb - fm_t.ascent(),
                                           fm_t.horizontalAdvance(b["title"]), fm_t.height()),
                "value_rect": QtCore.QRect(6, vb - fm_v.ascent(), 0, fm_v.height()),
                "hi_rect": QtCore.QRect(x1 + 5, y0 + 2, right_w - 8, fm_a.height()),
                "lo_rect": QtCore.QRect(x1 + 5, y0 + band_h - fm_a.height() - 2,
                                        right_w - 8, fm_a.height()),
            })
        return info

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QtGui.QColor(PANEL))
        f_t, f_v, f_a, f_h = self._fonts()
        g = self.layout()
        x0, x1, band_h = g["x0"], g["x1"], g["band_h"]
        W, H = self.width(), self.height()

        if self.title:
            p.setFont(f_h)
            p.setPen(QtGui.QPen(QtGui.QColor(FG), 1))
            p.drawText(8, 21, self.title)

        npts_max = 0
        for i, b in enumerate(self.bands):
            gi = g["bands"][i]
            y0 = gi["y0"]
            series = self.data.get(b["key"]) or []
            npts_max = max(npts_max, len(series))
            vals = [v for _, v in series]
            fmt = b.get("fmt") or (lambda v: f"{v:.4f}")
            if b.get("fixed") == "01":
                lo, hi = 0.0, 1.0
            elif vals:
                vmin, vmax = min(vals), max(vals)
                span = max(vmax - vmin, float(b.get("min_span", 0.0)) or 1e-9)
                pad = span * 0.15
                lo, hi = vmin - pad, vmax + pad
            else:
                lo, hi = 0.0, 1.0

            # 网格 + 边框 (绘图区)
            p.setPen(QtGui.QPen(QtGui.QColor("#21262d"), 1))
            for k in range(3):
                p.drawLine(x0, y0 + int(band_h * k / 2), x1, y0 + int(band_h * k / 2))
            p.setPen(QtGui.QPen(QtGui.QColor("#30363d"), 1))
            p.drawRect(x0, y0, x1 - x0, band_h)

            # 左栏: 通道名 (上) + 当前值 (下) — 两行分层, 基线由 layout() 保证不叠
            p.setFont(f_t)
            p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
            p.drawText(6, gi["title_baseline"], b["title"])
            p.setFont(f_v)
            p.setPen(QtGui.QPen(QtGui.QColor(b["color"]), 1))
            p.drawText(6, gi["value_baseline"], (fmt(vals[-1]) if vals else "—")
                       + ((" " + b["unit"]) if b.get("unit") else ""))

            # 右栏: 量程上限 (顶) / 下限 (底) — 与左栏 x 区间完全分离
            p.setFont(f_a)
            p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
            p.drawText(gi["hi_rect"], QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, fmt(hi))
            p.drawText(gi["lo_rect"], QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, fmt(lo))

            if len(series) < 2:
                p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
                p.drawText(x0 + 14, y0 + band_h // 2 + 5, b.get("empty") or "等待数据…")
                continue
            m = len(series)
            span_v = max(1e-12, hi - lo)
            pts = []
            for j, (_, v) in enumerate(series):
                xx = x0 + 2 + int((x1 - x0 - 4) * j / (m - 1))
                yy = y0 + band_h - 3 - int((band_h - 6) * (max(lo, min(hi, v)) - lo) / span_v)
                pts.append(QtCore.QPoint(xx, yy))
            p.setPen(QtGui.QPen(QtGui.QColor(b["color"]), 2))
            p.drawPolyline(QtGui.QPolygon(pts))
            p.setBrush(QtGui.QBrush(QtGui.QColor(b["color"])))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(pts[-1], 3, 3)

        p.setFont(f_a)
        p.setPen(QtGui.QPen(QtGui.QColor(DIM), 1))
        p.drawText(8, H - 7, f"横轴 = 最近 {npts_max} 帧 (等距 · 10Hz 采集 ≈ {npts_max / 10.0:.0f}s) ·"
                             f" 纵轴各自自适应量程 · 缺通道显示等待, 不填假值")


# ══════════════════════════════════════════════════════════════════════════════
# 旁路调试 · 上网通道 (4060 借道 · 工控机 wifi 代理)            2026-10-09 老倪
#   本机 4060 跑 tinyproxy 监听 192.168.23.50:8889 (白名单只放 192.168.23.23/.50),
#   工控机(192.168.23.23) 只在【测试连通】这一条命令上加 -Proxy 借道出网。
#   铁律: 工控机系统级代理 (WinHTTP) / 用户代理 (WinINET) / 默认路由 一字不动。
#   外部动作全部非阻塞 (后台 QThread) 且 站侧等待 ≤15s; 失败把原始报错打到界面 + 落盘日志。
#   最近一次结果写实例属性 self._net_last + 模块级 _NET_LAST, 由 net_channel_status_line()
#   供执行层取用 (口径与画布其它节点一致: 用下面终端日志汇报成一行)。
# ══════════════════════════════════════════════════════════════════════════════
PROXY_HOST = "192.168.23.50"
PROXY_PORT = 8889
STATION_HOST = "192.168.23.23"
NET_TINYPROXY_CONF = "/etc/tinyproxy/zmax.conf"
NET_CHANNEL_LOG = os.path.join(os.path.expanduser("~/zmax/zmax_data/ss_bypass"), "net_channel_status.json")


def _net_repo_root():
    r = os.environ.get("ZMAX_REPO_ROOT")
    if r and os.path.isdir(r):
        return r
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "src", "lerobot")) and os.path.isdir(os.path.join(d, "tools")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(d))


def _net_station_cmd_path():
    return os.path.join(_net_repo_root(), "tools", "station_cmd.py")


def _net_py():
    p = os.path.join(_net_repo_root(), "gui-venv311", "bin", "python")
    return p if os.path.exists(p) else sys.executable


_NET_LAST = {"ts": None, "action": None, "text": "尚未执行"}


def net_channel_status_line():
    """模块级: 最近一次上网通道结果的一行状态 (供执行层取用 → 下面终端日志汇报)。"""
    t = str(_NET_LAST.get("text") or "无").replace("\n", " ").strip()
    return "[上网通道] %s · %s" % (_NET_LAST.get("action") or "-", t[:200])


def _net_proxy_listening(host=PROXY_HOST, port=PROXY_PORT):
    """本机 tinyproxy 是否在听 host:port —— /proc/net/tcp LISTEN 命中 或 socket 探测连通。"""
    try:
        want_port = "%04X" % port
        with open("/proc/net/tcp", encoding="utf-8") as f:
            for ln in f:
                p = ln.split()
                if len(p) >= 4 and p[3] == "0A" and p[1].split(":")[-1] == want_port:
                    return True, "LISTEN(/proc/net/tcp)"
    except Exception:
        pass
    try:
        import socket as _s
        c = _s.socket()
        c.settimeout(1.0)
        rc = c.connect_ex((host, port))
        c.close()
        if rc == 0:
            return True, "socket 连通"
    except Exception:
        pass
    return False, "未监听"


def _net_run_station(ps_cmd, wait=15):
    """经反向通道 (tools/station_cmd.py) 让工控机跑一条 PowerShell 取回回显。阻塞, 调用方放线程里。"""
    sc = _net_station_cmd_path()
    if not os.path.exists(sc):
        return "❌ 找不到反向通道脚本: %s" % sc
    try:
        r = subprocess.run([_net_py(), sc, ps_cmd, str(int(wait))],
                           capture_output=True, text=True, timeout=int(wait) + 8)
    except subprocess.TimeoutExpired:
        return "❌ 反向通道超时 (>%ds)" % (int(wait) + 8)
    except Exception as e:
        return "❌ 反向通道异常: %s: %s" % (type(e).__name__, e)
    out = (r.stdout or "").strip()
    if out:
        return out
    return "❌ 无回执 (rc=%s): %s" % (r.returncode, ((r.stderr or "").strip() or "空")[:400])


def _net_ps_probe():
    """工控机只读回显: WinHTTP 系统代理 / WinINET 用户代理 / 10082·10083 监听 (单次往返)。"""
    return ("$p=Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings';"
            " $w=((netsh winhttp show proxy | Out-String) -replace '\\s+',' ').Trim();"
            " 'WinHTTP=' + $w + ' || WinINET ProxyEnable=' + $p.ProxyEnable + ' ProxyServer=[' + $p.ProxyServer + ']'"
            " + ' || Port10082=' + (Test-NetConnection -ComputerName 127.0.0.1 -Port 10082 -InformationLevel Quiet)"
            " + ' || Port10083=' + (Test-NetConnection -ComputerName 127.0.0.1 -Port 10083 -InformationLevel Quiet)")


def _net_ps_test():
    """工控机用 -Proxy 借道访问一次外网 (仅本条命令带 -Proxy, 不改任何系统设置)。"""
    return ("try { $r=Invoke-WebRequest -Uri 'http://example.com' -Proxy 'http://%s:%d' "
            "-UseBasicParsing -TimeoutSec 10; 'OK HTTP ' + $r.StatusCode } "
            "catch { 'FAIL ' + $_.Exception.Message }") % (PROXY_HOST, PROXY_PORT)


def _net_do_action(action):
    """同步执行一个上网通道动作, 返回回显文本 (原始报错已捕获, 不静默)。"""
    if action == "probe":
        ok, how = _net_proxy_listening()
        local = "本机 tinyproxy %s:%d → %s (%s)" % (PROXY_HOST, PROXY_PORT,
                                                    "✅ 在听" if ok else "❌ 未听", how)
        return local + "\n工控机(经反向通道): " + _net_run_station(_net_ps_probe(), wait=15)
    if action == "test":
        return "测试连通 → " + _net_run_station(_net_ps_test(), wait=15)
    if action == "open":
        ok, _ = _net_proxy_listening()
        if ok:
            return "开代理: ✅ 已在监听 %s:%d (未重复启动)" % (PROXY_HOST, PROXY_PORT)
        try:
            r = subprocess.run(["sudo", "-n", "/usr/bin/tinyproxy", "-c", NET_TINYPROXY_CONF],
                               capture_output=True, text=True, timeout=15)
        except Exception as e:
            return "开代理: ❌ %s: %s" % (type(e).__name__, e)
        time.sleep(1.0)
        ok2, how = _net_proxy_listening()
        msg = "开代理: %s (%s)" % ("✅ 已起 %s:%d" % (PROXY_HOST, PROXY_PORT) if ok2 else "❌ 未起", how)
        if r.returncode != 0:
            msg += " · rc=%s %s" % (r.returncode, ((r.stderr or r.stdout or "").strip())[:200])
        return msg
    if action == "close":
        try:
            r = subprocess.run(["sudo", "-n", "pkill", "-f", "tinyproxy -c " + NET_TINYPROXY_CONF],
                               capture_output=True, text=True, timeout=15)
        except Exception as e:
            return "关代理: ❌ %s: %s" % (type(e).__name__, e)
        time.sleep(0.6)
        ok2, how = _net_proxy_listening()
        msg = "关代理: %s (%s)" % ("❌ 仍在听" if ok2 else "✅ 已停", how)
        if r.returncode not in (0, 1):
            msg += " · rc=%s %s" % (r.returncode, ((r.stderr or r.stdout or "").strip())[:200])
        return msg
    return "❌ 未知动作: %r" % (action,)


class _NetChannelWorker(QtCore.QThread):
    """后台跑一个上网通道动作 (非阻塞 GUI), 完成后把回显文本发给主线程。"""
    done = QtCore.pyqtSignal(str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            txt = _net_do_action(self.action)
        except Exception as e:                        # 任何异常都要见到 (不静默)
            import traceback as _tb
            txt = "❌ %s: %s\n%s" % (type(e).__name__, e, _tb.format_exc()[-300:])
        self.done.emit(txt)


# ══════════════════════════════════════════════════════════════════════════════
# 旁路实时可视化 · 🛰 工位总览 station 带                       2026-10-09 老倪
#   地址来自配置文件 (不硬编码): ~/zmax/zmax_data/ss_bypass/station_url.json
#   只读轮询 station /station/status (1.5s), 与 8793 同源, 不做第二份真相。
#   不把 6 路 MJPEG 嵌进画布 (会拖死页面) —— 只给可点链接 (外部浏览器, 文本可复制)。
#   station 不可达 ⇒ 红色"离线" + 原始错误码 (不静默)。
# ══════════════════════════════════════════════════════════════════════════════
STATION_CFG_PATH = os.path.join(os.path.expanduser("~/zmax/zmax_data/ss_bypass"), "station_url.json")
STATION_CFG_DEFAULT = {
    "url": "http://10.163.146.78:8793/station",
    "status": "http://10.163.146.78:8793/station/status",
    "hil": "http://127.0.0.1:8795",
}
STATION_HIL_PEERS_PATH = os.path.join(os.path.expanduser("~/zmax/zmax_data/ss_bypass"), "hil_peers.json")
STATION_LEDGER_PATH = os.path.join(_net_repo_root(), "reports", "station_plan_ledger.jsonl")
# 6 路同屏键名 (与 tools/cam_live_stream.py 页面 CAMS['arm','local','local2'] + depth/aoi_gold/aoi_surface 同口径)
STATION_CAMS = [("arm", "臂上D405"), ("local", "笔记本"), ("local2", "MAXHUB顶摄"),
                ("depth", "D405深度"), ("aoi_gold", "金手指"), ("aoi_surface", "表面检测")]
STATION_PEER_TTL_S = 30.0


def load_station_cfg():
    """读 station 地址配置 → (cfg, created)。不存在则写默认并置 created=True (调用方 log)。"""
    created = False
    try:
        if os.path.exists(STATION_CFG_PATH):
            with open(STATION_CFG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            out = dict(STATION_CFG_DEFAULT)
            if isinstance(cfg, dict):
                out.update({k: v for k, v in cfg.items() if isinstance(v, str) and v})
            return out, created
        os.makedirs(os.path.dirname(STATION_CFG_PATH), exist_ok=True)
        with open(STATION_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(STATION_CFG_DEFAULT, f, ensure_ascii=False, indent=2)
        created = True
    except Exception:
        return dict(STATION_CFG_DEFAULT), created
    return dict(STATION_CFG_DEFAULT), created


def _station_http_get(url, timeout=2.5):
    """只读 GET → (ok, obj_or_err_text)。错误文本带原始类型/HTTP 码, 不静默。"""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zmax-ss-bypass/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.getcode(), r.read()
        try:
            return True, json.loads(raw.decode("utf-8", "replace"))
        except Exception as e:
            return False, "HTTP %s 但 JSON 解析失败: %s: %s" % (code, type(e).__name__, e)
    except urllib.error.HTTPError as e:
        return False, "HTTPError %s %s" % (e.code, e.reason)
    except urllib.error.URLError as e:
        return False, "URLError %s" % (e.reason,)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def read_hil_peers():
    """读 hil_peers.json (谁连着人机在环节点) → (ok, list_or_err_text)。"""
    try:
        if not os.path.exists(STATION_HIL_PEERS_PATH):
            return False, "文件不存在: %s" % STATION_HIL_PEERS_PATH
        with open(STATION_HIL_PEERS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        peers = d.get("peers") if isinstance(d, dict) else d
        if isinstance(peers, dict):
            peers = [dict(v, name=k) for k, v in peers.items()]
        return True, (peers if isinstance(peers, list) else [])
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def read_last_station_ledger():
    """读 reports/station_plan_ledger.jsonl 末行 → (ok, dict_or_err_text); 无则 ok=False。"""
    try:
        p = STATION_LEDGER_PATH
        if not os.path.exists(p):
            return False, "无台账文件: %s" % p
        last = None
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    last = ln
        if not last:
            return False, "台账为空: %s" % p
        return True, json.loads(last)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


class _StationPollWorker(QtCore.QThread):
    """后台只读拉一次 station/status + hil 可达性探测 (非阻塞 GUI)。

    done(status_dict_or_None, status_err, hil_ok, hil_err)
    """
    done = QtCore.pyqtSignal(object, str, bool, str)

    def __init__(self, status_url, hil_url, parent=None):
        super().__init__(parent)
        self.status_url = status_url
        self.hil_url = hil_url

    def run(self):
        try:
            ok, obj = _station_http_get(self.status_url)
        except Exception as e:                      # 任何异常都要见到 (不静默)
            ok, obj = False, "%s: %s" % (type(e).__name__, e)
        status = obj if ok else None
        serr = "" if ok else str(obj)
        hil_ok, hil_err = False, ""
        if self.hil_url:
            try:
                hok, hobj = _station_http_get(self.hil_url, timeout=2.0)
                hil_ok = bool(hok)
                hil_err = "" if hok else str(hobj)
            except Exception as e:
                hil_ok, hil_err = False, "%s: %s" % (type(e).__name__, e)
        self.done.emit(status, serr, hil_ok, hil_err)


# ══════════════════════════════════════════════════════════════════════════════
# 🤲 拖动示教捕捉带 (实时位姿 + 起点距离 + 拖动态 + 录点命令)     2026-10-09 老倪
#   老倪: 「从状态空间人机交互接口, 从金手指点1, 去到一个安全点, 手动拖拽」。
#   只读位姿真值 (rokae_tcp_sampler → latest.json) + 读控制器 operation/mode (8793) +
#   读示教点库里的起点 (金手指点1)。**绝不下发任何动作** (不 enableDrag/disableDrag)。
#   不可达/陈旧 ⇒ 红字 + 原始错误/帧龄 (不静默, 也不拿旧值冒充实时)。
# ══════════════════════════════════════════════════════════════════════════════
DRAG_TCP_SRC = os.path.join(os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out"), "latest.json")
DRAG_TAUGHT_STORE = os.path.join(os.path.expanduser("~/zmax"), "data/skills/l2_atomic/taught_points.json")
DRAG_BASE_PT_NAME = "金手指点1"
DRAG_MAX_AGE_S = 2.0
DRAG_CTL_URL = "http://127.0.0.1:8793/ctl/status"
DRAG_RECORD_CMD = ('curl -s -H "X-Zmax-Term: $(cat zmax_data/secrets/hil_term.token)" '
                   '-X POST http://127.0.0.1:8795/hil/term/record_point '
                   '-d \'{"name":"安全点1","note":"拖动示教捕捉"}\'')


def drag_read_pose():
    """读位姿真值 → dict; 陈旧/全 0/读不到 ⇒ stale=True + stale_why (pos=None, 不编造)。"""
    out = {"ok": False, "pos": None, "quat": None, "frame_age_s": None, "stale": True, "stale_why": ""}
    try:
        with open(DRAG_TCP_SRC, encoding="utf-8") as f:
            d = json.load(f)
        pos = [float(d["x"]), float(d["y"]), float(d["z"])]
        quat = [float(d["qx"]), float(d["qy"]), float(d["qz"]), float(d["qw"])]
        ts = float(d.get("ts") or 0.0)
    except Exception as e:
        out["stale_why"] = "读位姿真值失败: %s: %s (%s)" % (type(e).__name__, e, DRAG_TCP_SRC)
        return out
    age = (time.time() - ts) if ts else 999.0
    norm = sum(v * v for v in pos) ** 0.5
    out["frame_age_s"] = round(age, 3)
    why = []
    if age > DRAG_MAX_AGE_S:
        why.append("帧龄 %.2fs > %.1fs" % (age, DRAG_MAX_AGE_S))
    if norm < 1e-3:
        why.append("位置范数 %.2e m ≈ 0 (会话陈旧全 0)" % norm)
    if why:
        out["stale_why"] = " · ".join(why)
        return out
    out.update({"ok": True, "pos": pos, "quat": quat, "stale": False, "stale_why": ""})
    return out


def drag_read_base_point(name=DRAG_BASE_PT_NAME):
    """读示教点库里起点位姿 → {"name","pos"(或 None)}; 读不到 ⇒ pos=None。"""
    try:
        with open(DRAG_TAUGHT_STORE, encoding="utf-8") as f:
            p = ((json.load(f).get("points") or {}).get(name) or {}).get("pos")
        if p and len(p) >= 3:
            return {"name": name, "pos": [float(v) for v in p[:3]]}
    except Exception:
        pass
    return {"name": name, "pos": None}


def drag_read_ctl(timeout=2.5):
    """读 8793 控制器 operation/mode/power; 拿不到 ⇒ 字段 None + err (不编)。"""
    out = {"operation": None, "mode": None, "power": None, "err": ""}
    try:
        import urllib.request
        req = urllib.request.Request(DRAG_CTL_URL, headers={"User-Agent": "zmax-ss-bypass/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rb = (json.loads(r.read().decode("utf-8", "replace")) or {}).get("robot") or {}
        out.update({"operation": rb.get("operation"), "mode": rb.get("mode"), "power": rb.get("power")})
    except Exception as e:
        out["err"] = "%s: %s" % (type(e).__name__, e)
    return out


def drag_dist_mm(a, b):
    """两点欧氏距离 (mm); 任一缺 ⇒ None。"""
    if not a or not b or len(a) < 3 or len(b) < 3:
        return None
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a[:3], b[:3])) ** 0.5 * 1000.0


class _DragPollWorker(QtCore.QThread):
    """后台只读拉一次 位姿真值 + 起点 + 控制器状态 (非阻塞 GUI)。"""
    done = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            payload = {"pose": drag_read_pose(), "base": drag_read_base_point(), "ctl": drag_read_ctl()}
        except Exception as e:                      # 任何异常都要见到 (不静默)
            payload = {"err": "%s: %s" % (type(e).__name__, e)}
        self.done.emit(payload)


class SSBypassView(QtWidgets.QWidget):
    """旁路实时可视化窗口 (非模态, 可常开)"""

    def __init__(self, module=None):
        super().__init__(None, QtCore.Qt.Window)
        self.module = module
        self.setWindowTitle("📈 旁路实时可视化 — 状态空间 (当前阶段 / 残差 / 接触概率 / 真机位姿 XYZ / 插入力)")
        self.resize(1660, 1060)
        self.setStyleSheet(SS)
        self.src = _load_src()
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()
        # 🛰 工位总览 station 带: 1.5s 轮询 (后台线程, 不阻塞 GUI)
        self._station_worker = None
        self._station_last_status = None
        self._station_last_err = None
        self._station_hil_ok = None
        self._station_hil_err = ""
        self.station_timer = QtCore.QTimer(self)
        self.station_timer.timeout.connect(self._station_tick)
        self.station_timer.start(1500)
        QtCore.QTimer.singleShot(800, self._station_tick)
        # 🤲 拖动示教带: 1.5s 后台线程轮询 (只读; 不阻塞 GUI)
        self._drag_worker = None
        self._drag_last = None
        self.drag_timer = QtCore.QTimer(self)
        self.drag_timer.timeout.connect(self._drag_tick)
        self.drag_timer.start(1500)
        QtCore.QTimer.singleShot(1100, self._drag_tick)

    def _row(self, k):
        lab = QtWidgets.QLabel("-")
        lab.setStyleSheet(f"color:{FG};font-size:19px;")
        kk = QtWidgets.QLabel(k)
        kk.setStyleSheet(f"color:{DIM};font-size:14px;")
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)
        v.addWidget(kk)
        v.addWidget(lab)
        return w, lab

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel("🔭 可视化层 · 旁路观察器 (回路外, 不参与控制) — 数据源: 旁路真机传感器 (Orin 远程只读)")
        head.setStyleSheet(f"color:{DIM};font-size:15px;")
        root.addWidget(head)

        gb = QtWidgets.QGroupBox("旁路运行状态 (六层真源码逐帧)")
        g = QtWidgets.QGridLayout(gb)
        self.lab_stage, self.lab_res, self.lab_con = None, None, None
        keys = [("当前阶段 (13 段)", "stage"), ("残差 (m)", "residual"), ("接触概率", "contact_p"),
                ("旁路步 / 采样", "steps"), ("六层调用", "layers"), ("零下行自证", "zero"),
                ("缺口 (逐帧计数)", "gaps"), ("数据源新鲜度", "fresh")]
        self.labs = {}
        for i, (title, key) in enumerate(keys):
            w, lab = self._row(title)
            self.labs[key] = lab
            g.addWidget(w, i // 4, i % 4)
        root.addWidget(gb)

        gb2 = QtWidgets.QGroupBox("真机感知最新帧 (旁路数据源)")
        g2 = QtWidgets.QGridLayout(gb2)
        for i, (title, key) in enumerate([("TCP 位置 (m)", "tcp"), ("关节速度范数", "vnorm"),
                                          ("夹爪开度", "grip"), ("六维力", "ft"),
                                          ("场景几何 z7", "z7"), ("产线阶段", "prod")]):
            w, lab = self._row(title)
            self.labs["src_" + key] = lab
            g2.addWidget(w, i // 3, i % 3)
        root.addWidget(gb2)

        gbp = QtWidgets.QGroupBox("真机位姿 (实时 · 远程只读 Orin)")
        gp = QtWidgets.QGridLayout(gbp)
        for i, (t_, k, h_) in enumerate([("TCP X / Y / Z", "pose_xyz", "m · base_link 末端位置"),
                                         ("姿态四元数", "pose_quat", "x,y,z,w · 末端朝向"),
                                         ("六关节位置", "pose_q", "rad · q1..q6"),
                                         ("六关节速度", "pose_dq", "rad/s · 全 0 = 机器静止"),
                                         ("位置变化率", "pose_dx", "m/s · 由真实帧差分 (产线在动)"),
                                         ("机器人状态", "pose_rs", "电源 / 运行 / 报警 / 急停 / 碰撞"),
                                         ("插入力 |F|", "pose_fmag", "N · 合力 = √(Fx²+Fy²+Fz²) · 真实力信号"),
                                         ("轴向插入力 Fz", "pose_fz", "N · 工具轴接触反馈力 (插装判据)"),
                                         ("六维力 Fx,Fy,Fz", "pose_f3", "N · 腕部力觉三分量 · 50Hz")]):
            w, lab = self._row(t_)
            self.labs["p_" + k] = lab
            gp.addWidget(w, i // 5, i % 5)          # 5 列 → 9 格只占 2 行 (窗口别太高)
        root.addWidget(gbp)

        gbimg = QtWidgets.QGroupBox("实时图像 (RealSense 彩色优先 / FoundationPose 调试帧兜底)")
        gi = QtWidgets.QHBoxLayout(gbimg)
        self.img_view = QtWidgets.QLabel("(无图像)")
        self.img_view.setFixedSize(260, 195)
        self.img_view.setStyleSheet("background:#161b22; color:#8b949e; border:1px solid #30363d;")
        self.img_view.setAlignment(QtCore.Qt.AlignCenter)
        self.img_meta = QtWidgets.QLabel("-")
        self.img_meta.setStyleSheet(f"color:{FG};font-size:12px;")
        self.img_meta.setWordWrap(True)
        gi.addWidget(self.img_view)
        gi.addWidget(self.img_meta, 1)
        root.addWidget(gbimg)

        self.curve = CurveWidget(BANDS_SS, title="状态空间通道 (旁路六层真源码逐帧)")
        self.curve_real = CurveWidget(BANDS_REAL, title="真机通道 (Orin 远程只读 · 位姿 50Hz/落盘 10Hz · 力 49.5Hz)")
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(12)
        box.addWidget(self.curve, 1)
        box.addWidget(self.curve_real, 1)
        root.addLayout(box, 1)
        self.lab_foot = QtWidgets.QLabel("")
        self.lab_foot.setStyleSheet(f"color:{DIM};font-size:14px;")
        self.lab_foot.setWordWrap(True)
        root.addWidget(self.lab_foot)

        self._build_net_channel(root)          # 旁路调试 · 上网通道 区块 (新增, 不动上面现有功能)
        self._build_station_band(root)         # 🛰 工位总览 station 带 (新增, 不动上面现有功能)
        self._build_drag_teach_band(root)      # 🤲 拖动示教捕捉带 (新增, 不动上面现有功能)

    # ── 🛰 工位总览 station 带 (2026-10-09) ───────────────────────────────────
    def _station_row(self, title):
        lab = QtWidgets.QLabel("—")
        lab.setStyleSheet(f"color:{FG};font-size:15px;")
        lab.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)      # 可复制
        lab.setWordWrap(True)
        kk = QtWidgets.QLabel(title)
        kk.setStyleSheet(f"color:{DIM};font-size:14px;")
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)
        v.addWidget(kk)
        v.addWidget(lab)
        return w, lab

    def _build_station_band(self, root):
        """只读工位总览: 可点链接 + 六路相机/TCP/授权/机器人 + HIL peers + 台账。"""
        gb = QtWidgets.QGroupBox("🛰 工位总览 station (旁路只读 · 与 8793 同源 · 不嵌 6 路 MJPEG)")
        g = QtWidgets.QGridLayout(gb)
        self.station_cfg, _created = load_station_cfg()
        tip = QtWidgets.QLabel(
            "读 station /station/status (1.5s 轮询) · 只读不动臂 · 地址来自 "
            "zmax_data/ss_bypass/station_url.json" + ("  [本次新建默认]" if _created else ""))
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{DIM};font-size:12px;")
        g.addWidget(tip, 0, 0, 1, 2)
        if _created:
            print("[SSBypassView] station_url.json 不存在 → 已写默认: %s" % STATION_CFG_PATH, flush=True)

        self.station_labs = {}
        # 1) 可点链接 (外部浏览器) —— 文本可复制, 不内嵌 MJPEG
        url = self.station_cfg["url"]
        link = QtWidgets.QLabel(f'<a href="{url}" style="color:#7ee787;">{url}</a>')
        link.setTextFormat(QtCore.Qt.RichText)
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse |
                                     QtCore.Qt.LinksAccessibleByMouse)
        link.setStyleSheet("font-size:15px;")
        wl = QtWidgets.QWidget()
        vl = QtWidgets.QVBoxLayout(wl)
        vl.setContentsMargins(2, 2, 2, 2)
        vl.setSpacing(2)
        kl = QtWidgets.QLabel("工位总览页 (点击用外部浏览器打开 · 文本可复制)")
        kl.setStyleSheet(f"color:{DIM};font-size:14px;")
        vl.addWidget(kl)
        vl.addWidget(link)
        g.addWidget(wl, 1, 0, 1, 2)

        for i, (t_, k) in enumerate([("六路相机 在线/最大帧龄", "cam"),
                                     ("TCP 位姿 x/y/z", "tcp"),
                                     ("授权剩余", "auth"),
                                     ("机器人 operation/mode", "robot"),
                                     ("HIL peers (人机在环)", "peers"),
                                     ("最近 station→规划→L2 台账", "ledger")]):
            w, lab = self._station_row(t_)
            self.station_labs[k] = lab
            g.addWidget(w, 2 + i // 2, i % 2)
        root.addWidget(gb)

    # ── 🤲 拖动示教捕捉带 (2026-10-09) ───────────────────────────────────────
    def _build_drag_teach_band(self, root):
        """只读: 实时 x/y/z + 帧龄 + 采样时刻 · 起点「金手指点1」+ 距起点 mm · 拖动中/静止 · 可复制录点命令。"""
        gb = QtWidgets.QGroupBox("🤲 拖动示教捕捉 (只读位姿 + 起点距离 + 录点命令 · 1.5s 后台轮询 · 零下发)")
        g = QtWidgets.QGridLayout(gb)
        tip = QtWidgets.QLabel(
            "位姿真值 rokae_tcp_out/latest.json (页面同源) · 起点 = taught_points.json 的「%s」· "
            "operation/mode 来自 8793/ctl/status · 绝不 enableDrag/disableDrag/不改控制器模式 · "
            "不可达/陈旧 ⇒ 红字报原始错误/帧龄 (不静默)" % DRAG_BASE_PT_NAME)
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{DIM};font-size:12px;")
        g.addWidget(tip, 0, 0, 1, 2)

        self.drag_labs = {}
        for i, (t_, k) in enumerate([("① 实时末端位姿 x/y/z + 帧龄 + 采样时刻", "pos"),
                                     ("② 拖动状态 operation/mode", "state")]):
            w, lab = self._station_row(t_)                 # 复用同一字体/泳道写法
            self.drag_labs[k] = lab
            g.addWidget(w, 1, i)
        for i, (t_, k) in enumerate([("③ 起点「%s」(base_link)" % DRAG_BASE_PT_NAME, "base"),
                                     ("④ 录点命令 (可复制)", "cmd")]):
            w, lab = self._station_row(t_)
            if k == "cmd":
                lab.setStyleSheet("color:#7ee787;font-size:14px;font-family:monospace;")
            self.drag_labs[k] = lab
            g.addWidget(w, 2 + i, 0, 1, 2)                 # ③④ 各占整行 (命令一行放得下)
        self.drag_err = QtWidgets.QLabel("")
        self.drag_err.setWordWrap(True)
        self.drag_err.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.drag_err.setStyleSheet(f"color:{C_BAD};font-size:13px;")
        g.addWidget(self.drag_err, 4, 0, 1, 2)
        root.addWidget(gb)

    def _drag_tick(self):
        """每 1.5s: 后台线程只读拉一次 (位姿/起点/控制器); 上一轮没跑完就跳过。"""
        if self._drag_worker is not None and self._drag_worker.isRunning():
            return
        w = _DragPollWorker(self)
        w.done.connect(self._drag_on_done)
        self._drag_worker = w
        w.start()

    def _drag_on_done(self, payload):
        self._drag_last = payload
        self._render_drag(payload)

    def _drag_refresh_blocking(self):
        """同步拉一轮并渲染 (供离屏自测/冒烟调用, 不依赖事件循环)。"""
        try:
            payload = {"pose": drag_read_pose(), "base": drag_read_base_point(), "ctl": drag_read_ctl()}
        except Exception as e:
            payload = {"err": "%s: %s" % (type(e).__name__, e)}
        self._drag_last = payload
        self._render_drag(payload)
        return payload

    def _render_drag(self, payload):
        now = time.time()
        errs = []
        if payload.get("err"):
            errs.append("轮询异常: " + str(payload["err"]))
        pose = payload.get("pose") or {}
        base = payload.get("base") or {}
        ctl = payload.get("ctl") or {}
        if ctl.get("err"):
            errs.append("控制器读取失败: " + str(ctl["err"]))

        pos = pose.get("pos")
        if pos:
            st = self._stamp(now - (pose.get("frame_age_s") or 0))
            self.drag_labs["pos"].setText("x=%.3f y=%.3f z=%.3f m · 帧龄 %.2fs · 采样 %s"
                                          % (pos[0], pos[1], pos[2], pose.get("frame_age_s") or -1, st))
            self.drag_labs["pos"].setStyleSheet(f"color:{FG};font-size:15px;")
        else:
            self.drag_labs["pos"].setText("🔴 位姿不可用 · " + (pose.get("stale_why") or "读不到"))
            self.drag_labs["pos"].setStyleSheet(f"color:{C_BAD};font-size:15px;")
            if pose.get("stale_why"):
                errs.append(str(pose["stale_why"]))

        bp = base.get("pos")
        if bp and pos:
            d = drag_dist_mm(pos, bp)
            self.drag_labs["base"].setText("起点 %s (%.4f, %.4f, %.4f) · 距起点 %.1f mm"
                                           % (base.get("name"), bp[0], bp[1], bp[2], d))
            self.drag_labs["base"].setStyleSheet(f"color:{C_OK};font-size:15px;")
        else:
            self.drag_labs["base"].setText("起点 %s · 距离不可用 (位姿缺 或 起点缺)" % base.get("name"))
            self.drag_labs["base"].setStyleSheet(f"color:{C_BAD};font-size:15px;")
            if not bp:
                errs.append("起点「%s」读不到: %s" % (base.get("name"), DRAG_TAUGHT_STORE))

        op = ctl.get("operation")
        if op is None:
            self.drag_labs["state"].setText("⏸ 状态未知 · operation=None mode=None (8793 不可达)")
            self.drag_labs["state"].setStyleSheet(f"color:{C_BAD};font-size:15px;")
        else:
            moving = (str(op) == "drag")
            self.drag_labs["state"].setText("%s · operation=%s mode=%s power=%s"
                                            % ("🖐 拖动中" if moving else "⏸ 静止/非拖动",
                                               op, ctl.get("mode"), ctl.get("power")))
            self.drag_labs["state"].setStyleSheet(
                f"color:{C_OK if moving else FG};font-size:15px;")

        self.drag_labs["cmd"].setText(DRAG_RECORD_CMD)
        self.drag_err.setText(("🔴 " + " | ".join(errs)) if errs else "")

    @staticmethod
    def _stamp(t):
        try:
            return time.strftime("%H:%M:%S", time.localtime(t))
        except Exception:
            return "—"

    def _station_tick(self):
        """每 1.5s: 本地文件项 (peers/台账) 立即刷新; 远程 status+hil 丢后台线程。"""
        self._station_render_peers()
        self._station_render_ledger()
        if self._station_worker is not None and self._station_worker.isRunning():
            return
        w = _StationPollWorker(self.station_cfg["status"], self.station_cfg.get("hil"), self)
        w.done.connect(self._station_on_done)
        self._station_worker = w
        w.start()

    def _station_on_done(self, status, err, hil_ok, hil_err):
        self._station_last_status, self._station_last_err = status, err
        self._station_hil_ok, self._station_hil_err = hil_ok, hil_err
        self._station_render_status(status, err)
        self._station_render_peers()

    def _station_render_status(self, status, err):
        """写 station 状态标签; status=None ⇒ 红色离线 + 原始错误码 (不静默)。"""
        now = time.time()
        if not status:
            emsg = err or "无错误信息"
            for k in ("cam", "tcp", "auth", "robot"):
                self.station_labs[k].setText("🔴 离线 · " + emsg)
                self.station_labs[k].setStyleSheet(f"color:{C_BAD};font-size:15px;")
                self.station_labs[k].setToolTip(emsg)
            return
        st = status.get("stats") or {}
        ctl = status.get("ctl") or {}

        # 六路相机: 在线数 + 最大帧龄 (带秒) + 取样时间
        on, age_max, worst = 0, -1.0, "—"
        for key, nm in STATION_CAMS:
            c = st.get(key) or {}
            if c.get("online"):
                on += 1
            a = c.get("age_s")
            if isinstance(a, (int, float)) and a > age_max:
                age_max, worst = a, nm
        samp = self._stamp(now - age_max) if age_max >= 0 else "—"
        self.station_labs["cam"].setText(
            "在线 %d/%d · 最大帧龄 %.0fs (%s) · 取样 %s" % (on, len(STATION_CAMS), age_max, worst, samp))
        self.station_labs["cam"].setStyleSheet(
            f"color:{C_OK if on == len(STATION_CAMS) else C_BAD};font-size:15px;")

        # TCP 位姿 (x/y/z 三位小数) + 采样时间
        tcp = ctl.get("tcp") or {}
        xyz = tcp.get("xyz") or []
        if len(xyz) >= 3:
            txt = "x=%.3f y=%.3f z=%.3f m" % (xyz[0], xyz[1], xyz[2])
            a = tcp.get("age_s")
            txt += (" · 采样 %s (age %.2fs)" % (self._stamp(now - a), a)
                    if isinstance(a, (int, float)) else " · 采样时间缺")
        else:
            txt = "缺 (无 TCP 真值)"
        self.station_labs["tcp"].setText(txt)

        # 授权剩余秒 + 读取时间
        auth = ctl.get("auth") or {}
        armed = bool(auth.get("armed"))
        left = auth.get("left_s")
        self.station_labs["auth"].setText(
            ("✅ 已授权 剩余 %.0fs" % (left or 0.0) if armed else "⛔ 未授权 (剩余 %.0fs)" % (left or 0.0))
            + " · 读取 %s" % self._stamp(now))
        self.station_labs["auth"].setStyleSheet(f"color:{C_OK if armed else C_BAD};font-size:15px;")

        # 机器人 operation / mode + 读取时间
        rob = ctl.get("robot") or {}
        self.station_labs["robot"].setText(
            "%s / %s · 读取 %s" % (rob.get("operation", "缺"), rob.get("mode", "缺"), self._stamp(now)))
        self.station_labs["robot"].setStyleSheet(f"color:{FG};font-size:15px;")

    def _station_render_peers(self):
        ok, peers = read_hil_peers()
        now = time.time()
        parts = []
        if not ok:
            self.station_labs["peers"].setToolTip(str(peers))     # 原始原因 (文件缺失/解析失败)
        else:
            for p in peers:
                if not isinstance(p, dict):
                    continue
                nm = p.get("name") or p.get("kind") or "?"
                a = p.get("age_s")
                if a is None:
                    t = p.get("ts") or p.get("t")
                    if isinstance(t, (int, float)):
                        a = now - t
                if isinstance(a, (int, float)) and a > STATION_PEER_TTL_S:
                    parts.append("🔴 %s 离线(%.0fs>%.0fs)" % (nm, a, STATION_PEER_TTL_S))
                else:
                    parts.append("🟢 %s%s" % (nm, ("(%.0fs)" % a) if isinstance(a, (int, float)) else ""))
        ptxt = " · ".join(parts) if parts else "无 peers 登记"
        # hil 端点可达性 (不可达 ⇒ 红色 + 原始错误)
        hok = getattr(self, "_station_hil_ok", None)
        if hok is None:
            htxt, hbad = "hil …", False
        elif hok:
            htxt, hbad = "hil ✅ 在线", False
        else:
            htxt, hbad = "🔴 hil 离线 · " + (getattr(self, "_station_hil_err", "") or "—"), True
        self.station_labs["peers"].setText(ptxt + "  |  " + htxt)
        self.station_labs["peers"].setStyleSheet(
            f"color:{C_BAD if hbad else FG};font-size:15px;")

    def _station_render_ledger(self):
        ok, d = read_last_station_ledger()
        if not ok:
            self.station_labs["ledger"].setText("—")
            self.station_labs["ledger"].setStyleSheet(f"color:{DIM};font-size:15px;")
            self.station_labs["ledger"].setToolTip(str(d))
            return
        try:
            if isinstance(d, dict):
                bits = []
                for k in ("ts", "t", "kind", "stage", "status", "target", "plan_id", "segments", "ok"):
                    if k in d:
                        bits.append("%s=%s" % (k, d[k]))
                txt = " · ".join(bits) or json.dumps(d, ensure_ascii=False)
            else:
                txt = str(d)
        except Exception:
            txt = str(d)
        self.station_labs["ledger"].setText(txt[:220])
        self.station_labs["ledger"].setStyleSheet(f"color:{FG};font-size:15px;")


    def _build_net_channel(self, root):
        """只读回显 (tinyproxy/WinHTTP/WinINET/端口) + 【测试连通】【开代理】【关代理】。"""
        gb = QtWidgets.QGroupBox("旁路调试 · 上网通道 (4060 借道 · 工控机 wifi 代理)")
        v = QtWidgets.QVBoxLayout(gb)
        tip = QtWidgets.QLabel(
            "🔒 工控机系统设置一字不动 — 仅在【测试连通】这一条命令上加 -Proxy http://%s:%d 借道出网, "
            "WinHTTP / WinINET 用户代理 / 默认路由一律不改。本机 tinyproxy 白名单仅放工控机 %s。"
            % (PROXY_HOST, PROXY_PORT, STATION_HOST))
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C_OK};font-size:13px;")
        v.addWidget(tip)

        self.net_labs = {}
        grid = QtWidgets.QGridLayout()
        for i, (t_, k) in enumerate([("本机 tinyproxy (%s:%d)" % (PROXY_HOST, PROXY_PORT), "proxy"),
                                     ("工控机 WinHTTP 系统代理", "winhttp"),
                                     ("工控机 WinINET 用户代理", "wininet"),
                                     ("工控机 10082 / 10083 监听", "ports")]):
            w, lab = self._row(t_)
            lab.setStyleSheet(f"color:{FG};font-size:14px;")
            self.net_labs[k] = lab
            grid.addWidget(w, i // 2, i % 2)
        v.addLayout(grid)

        btns = QtWidgets.QHBoxLayout()
        self.btn_net_probe = QtWidgets.QPushButton("🔄 刷新状态")
        self.btn_net_test = QtWidgets.QPushButton("🌐 测试连通")
        self.btn_net_open = QtWidgets.QPushButton("▶ 开代理")
        self.btn_net_close = QtWidgets.QPushButton("■ 关代理")
        for b in (self.btn_net_probe, self.btn_net_test, self.btn_net_open, self.btn_net_close):
            b.setStyleSheet(f"color:{FG};font-size:14px;padding:4px 10px;")
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)

        self.net_out = QtWidgets.QPlainTextEdit()
        self.net_out.setReadOnly(True)
        self.net_out.setMaximumHeight(120)
        self.net_out.setStyleSheet(f"background:{PANEL};color:{FG};font-size:13px;border:1px solid #30363d;")
        self.net_out.setPlainText("尚未执行")
        v.addWidget(self.net_out)
        root.addWidget(gb)

        self._net_worker = None
        self._net_last = "尚未执行"                      # 实例属性 (供后续节点读取)
        self.btn_net_probe.clicked.connect(lambda: self._net_action("probe"))
        self.btn_net_test.clicked.connect(lambda: self._net_action("test"))
        self.btn_net_open.clicked.connect(lambda: self._net_action("open"))
        self.btn_net_close.clicked.connect(lambda: self._net_action("close"))
        # 打开即自动取一次只读回显 (非阻塞 · 后台线程)
        QtCore.QTimer.singleShot(1500, lambda: self._net_action("probe"))

    _NET_BTN_BASE = {"probe": "🔄 刷新状态", "test": "🌐 测试连通",
                     "open": "▶ 开代理", "close": "■ 关代理"}

    def _net_append(self, txt):
        try:
            self.net_out.appendPlainText("[%s] %s" % (time.strftime("%H:%M:%S"), txt))
        except Exception:
            pass

    def _net_setbtn(self, action, busy):
        b = getattr(self, {"probe": "btn_net_probe", "test": "btn_net_test",
                           "open": "btn_net_open", "close": "btn_net_close"}.get(action, ""), None)
        if b is None:
            return
        base = self._NET_BTN_BASE[action]
        try:
            b.setText(("⏳ " + base[2:]) if busy else base)
            b.setEnabled(not busy)
        except Exception:
            pass

    def _net_update_labels(self, action, txt):
        try:
            ok, how = _net_proxy_listening()
            if "proxy" in self.net_labs:
                self.net_labs["proxy"].setText(("✅ 在听 " if ok else "❌ 未听 ") + "%s:%d" % (PROXY_HOST, PROXY_PORT))
                self.net_labs["proxy"].setStyleSheet(f"color:{C_OK if ok else C_BAD};font-size:14px;")
            t = txt or ""
            m = re.search(r"WinHTTP=([^|]*)", t)
            if m and "winhttp" in self.net_labs:
                self.net_labs["winhttp"].setText(m.group(1).strip()[:60] or "-")
            m = re.search(r"WinINET\s+([^|]*)", t)
            if m and "wininet" in self.net_labs:
                self.net_labs["wininet"].setText(m.group(1).strip()[:60] or "-")
            if "ports" in self.net_labs and "Port10082" in t:
                self.net_labs["ports"].setText("10082 %s · 10083 %s"
                                               % ("✅" if "10082=True" in t else "❌",
                                                  "✅" if "10083=True" in t else "❌"))
        except Exception as e:
            self._net_append("⚠️ 回显解析异常: %s: %s" % (type(e).__name__, e))

    def _net_action(self, action, blocking=False):
        """执行一个上网通道动作。blocking=True 同步返回文本 (供自检/执行层调用); 否则后台线程非阻塞。"""
        if self._net_worker is not None and self._net_worker.isRunning():
            self._net_append("⏳ 上一个动作仍在进行, 请稍候…")
            return None
        self._net_append("⏳ 执行: %s …" % action)
        if blocking:
            txt = _net_do_action(action)
            self._net_done(action, txt)
            return txt
        self._net_setbtn(action, True)
        w = _NetChannelWorker(action, self)
        w.done.connect(lambda t, a=action: self._net_done(a, t))
        self._net_worker = w
        w.start()
        return None

    def _net_done(self, action, txt):
        txt = txt if txt is not None else "❌ 空结果"
        self._net_last = txt                             # 实例属性 (供后续节点读取)
        self._net_append(txt)
        try:
            _NET_LAST.update({"ts": time.time(), "action": action, "text": txt})
            os.makedirs(os.path.dirname(NET_CHANNEL_LOG), exist_ok=True)
            with open(NET_CHANNEL_LOG, "w", encoding="utf-8") as f:
                json.dump(_NET_LAST, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._net_append("⚠️ 状态落盘失败: %s: %s" % (type(e).__name__, e))
        self._net_update_labels(action, txt)
        self._net_setbtn(action, False)

    def _feed_curves(self):
        """把最近一段真实逐帧记录喂给两条波形 (旁路通道 + 真机位姿/插入力); 缺的通道留空, 不填假值"""
        rows = self.src.tail_bypass(240)
        self.curve.set_series("residual", [(float(r.get("t", 0)), float(r.get("residual", 0) or 0))
                                           for r in rows])
        self.curve.set_series("contact_p", [(float(r.get("t", 0)), float(r.get("contact_p", 0) or 0))
                                            for r in rows])
        self.curve.set_series("dx_real", [(float(r.get("t", 0)), float(r.get("dx_real", 0) or 0))
                                          for r in rows])
        xs, ys, zs, mag, fz = [], [], [], [], []
        for r in (self.src.tail_state(240) or []):
            t = float(r.get("t", 0) or 0)
            q = r.get("tcp") or []
            if len(q) >= 3:
                xs.append((t, float(q[0])))
                ys.append((t, float(q[1])))
                zs.append((t, float(q[2])))
            w = r.get("ft") or []
            if len(w) >= 3:
                fx, fy, fzz = float(w[0]), float(w[1]), float(w[2])
                mag.append((t, (fx * fx + fy * fy + fzz * fzz) ** 0.5))
                fz.append((t, fzz))
        self.curve_real.set_series("tcp_x", xs)
        self.curve_real.set_series("tcp_y", ys)
        self.curve_real.set_series("tcp_z", zs)
        self.curve_real.set_series("force_mag", mag)
        self.curve_real.set_series("force_fz", fz)

    def refresh(self):
        try:
            s = self.src.read_bypass_status()
            last = (s.get("last") or {}) if s.get("ok") else {}
            self.labs["stage"].setText(str(last.get("stage", "-")))
            self.labs["residual"].setText(f"{last.get('residual', '-')}")
            self.labs["contact_p"].setText(f"{last.get('contact_p', '-')}")
            self.labs["steps"].setText(f"{s.get('steps', '-')} / {s.get('samples', '-')}")
            lc = s.get("layer_calls") or {}
            self.labs["layers"].setText(" · ".join(f"{k[:4]}={v}" for k, v in lc.items()) or "-")
            zd = s.get("zero_downlink") or {}
            zt = ("✅ 无 rclpy/无 socket/零写回" if zd and not zd.get("rclpy_imported")
                  else f"⚠️ {zd}")
            self.labs["zero"].setText(zt)
            self.labs["zero"].setStyleSheet(f"color:{C_OK if '✅' in zt else C_BAD};font-size:14px;")
            gaps = s.get("gap") or {}
            self.labs["gaps"].setText(" · ".join(f"{k.split('(')[0]}×{v}" for k, v in gaps.items()) or "无")
            age = s.get("age_s")
            fresh = s.get("fresh")
            self.labs["fresh"].setText(("✅ " if fresh else "⚠️ 过期 ") + f"{age}s" if age is not None else "-")
            self.labs["fresh"].setStyleSheet(f"color:{C_OK if fresh else C_BAD};font-size:14px;")

            p = self.src.read_latest()
            self.labs["src_tcp"].setText(str([round(x, 4) for x in p["tcp"]]) if p.get("tcp") else "-")
            jv = p.get("jvel")
            self.labs["src_vnorm"].setText(f"{sum(v * v for v in jv) ** 0.5:.4f}" if jv else "缺")
            self.labs["src_grip"].setText(str(p.get("gripper")) if p.get("gripper") is not None else "缺(无发布者)")
            self.labs["src_ft"].setText(str(p.get("ft")) if p.get("ft") is not None else "缺(无发布者)")
            ft6 = p.get("ft") or []
            _fm = (sum(v * v for v in ft6[:3]) ** 0.5) if len(ft6) >= 3 else None
            self.labs["p_pose_fmag"].setText(f"{_fm:.2f} N" if _fm is not None else "缺")
            self.labs["p_pose_fmag"].setStyleSheet(
                f"color:{'#f778ba' if _fm is not None else C_BAD};font-size:19px;")
            self.labs["p_pose_fz"].setText(f"{ft6[2]:+.2f} N" if len(ft6) >= 3 else "缺")
            self.labs["p_pose_f3"].setText(", ".join(f"{v:+.2f}" for v in ft6[:3]) if len(ft6) >= 3 else "缺")
            self.labs["src_z7"].setText("未示教 (拒算)" if p.get("z7") is None else str(p["z7"]))
            self.labs["src_prod"].setText(p.get("stage_prod") or "空闲")

            # 真机位姿 (TCP + 四元数 + 六关节 + 机器人状态)
            tcp = p.get("tcp") or []
            self.labs["p_pose_xyz"].setText(", ".join(f"{v:+.4f}" for v in tcp) + f"  ({p.get('tcp_frame')})" if tcp else "-")
            q = p.get("tcp_quat") or []
            self.labs["p_pose_quat"].setText(", ".join(f"{v:+.3f}" for v in q) if q else "缺")
            jp = p.get("jpos") or []
            jv = p.get("jvel") or []
            self.labs["p_pose_q"].setText(" ".join(f"{v:+.3f}" for v in jp) if jp else "缺")
            self.labs["p_pose_dq"].setText(" ".join(f"{v:+.3f}" for v in jv) if jv else "缺")
            moving = bool(jv) and max(abs(v) for v in jv) > 1e-4
            self.labs["p_pose_dq"].setStyleSheet(f"color:{C_OK if moving else DIM};font-size:19px;")
            dxr = (last.get("dx_real") if last else None)
            self.labs["p_pose_dx"].setText(f"{dxr:.4f}" if isinstance(dxr, (int, float)) else "-")
            self.labs["p_pose_dx"].setStyleSheet(
                f"color:{C_OK if isinstance(dxr, (int, float)) and dxr > 0.002 else DIM};font-size:19px;")
            import json as _json
            import re as _re
            _rsraw = p.get("robot_status") or ""
            try:
                rs = _json.loads(_rsraw)
            except Exception:                      # 截断/非完整 JSON → 正则兜底 (如实取值, 不猜)
                rs = {}
                for _k in ("power_state", "operation_state", "error_reason"):
                    _m = _re.search(r'"%s"\s*:\s*"([^"]*)"' % _k, _rsraw)
                    if _m:
                        rs[_k] = _m.group(1)
                for _k in ("has_error", "estop_detected", "collision_detected"):
                    rs[_k] = ('"%s": true' % _k) in _rsraw.replace(" ", "")
            if rs:
                st_txt = (f"{rs.get('power_state', '?')} / {rs.get('operation_state', '?')} / "
                          + ("报警 " + str(rs.get("error_reason", "")) if rs.get("has_error")
                             else ("急停" if rs.get("estop_detected") else
                                   ("碰撞" if rs.get("collision_detected") else "正常"))))
            else:
                st_txt = "缺 (无 /robot_status)"
            self.labs["p_pose_rs"].setText(st_txt)

            # 实时图像 (多话题状态如实显示) —— L2 YOLO 标注图优先 (旁路可视化唯一出口)
            import json as _json2
            _ydp = os.path.join(os.path.expanduser("~/zmax/zmax_data/ss_bypass"), "yolo_detections.json")
            _yimg = os.path.join(os.path.expanduser("~/zmax/zmax_data/ss_bypass"), "yolo_annotated.png")
            try:
                _yd = _json2.load(open(_ydp)) if os.path.exists(_ydp) else None
            except Exception:
                _yd = None
            if _yd and os.path.exists(_yimg) and (time.time() - os.path.getmtime(_yimg)) <= 6.0:
                _pm = QtGui.QPixmap(_yimg)
                if not _pm.isNull():
                    self.img_view.setPixmap(_pm.scaled(self.img_view.size(), QtCore.Qt.KeepAspectRatio,
                                                       QtCore.Qt.SmoothTransformation))
                _peg = _yd.get("peg_optical_module")
                _dt = " · ".join(f"{d['cls']}={d['conf']}" for d in (_yd.get("detections") or [])[:4]) or "无检出"
                self.img_meta.setText(
                    f"🎯 L2 YOLO 旁路检测 (输出=可视化, 零下行)\n源图: {_yd.get('image')} "
                    f"[{_yd.get('source_kind')}] {_yd.get('size')} · age={_yd.get('frame_age_s')}s\n"
                    f"检出: {_dt}\n" +
                    (f"✅ 光模块(peg) conf={_peg['conf']} box={_peg['xyxy']}" if _peg else "⚠️ 未检出光模块(peg)"))
                self._feed_curves()
                self.lab_foot.setText(f"旁路可视化: 真机位姿 + L2 YOLO 标注图 (唯一输出, 无任何下行) · "
                                      f"权重 {os.path.basename(str(_yd.get('weights', '')))} · imgsz={_yd.get('imgsz')} "
                                      f"conf_th={_yd.get('conf_th')}")
                return
            byt = p.get("images_by_topic") or {}
            pick, pick_t = None, None
            for t, v in byt.items():                     # RealSense 优先 (只认新鲜帧 ≤5s)
                if v.get("png") and "realsense" in t and (v.get("age") or 99) <= 5.0:
                    pick, pick_t = v, t
            if pick is None:
                for t, v in byt.items():
                    if v.get("png") and (v.get("age") or 99) <= 5.0:
                        pick, pick_t = v, t
            if pick and os.path.exists(pick["png"]):
                pm = QtGui.QPixmap(pick["png"])
                if not pm.isNull():
                    self.img_view.setPixmap(pm.scaled(self.img_view.size(), QtCore.Qt.KeepAspectRatio,
                                                      QtCore.Qt.SmoothTransformation))
                self.img_meta.setText(
                    f"显示: {pick_t}\n{('RealSense 彩色' if 'realsense' in str(pick_t) else 'FoundationPose 调试帧')} "
                    f"{pick.get('w')}×{pick.get('h')} {pick.get('encoding')} · 对比度 std={pick.get('std')} "
                    f"(>5 判真图)\n新鲜度: {pick.get('age')}s\n各话题: " +
                    " / ".join(f"{t.split('/')[-1]}={'有帧' if v.get('png') else '无帧'}" for t, v in byt.items()))
            else:
                _pubs = (p.get("pubs") or {})
                _rs = _pubs.get("/realsense/color/image_raw")
                _fp = _pubs.get("/foundationpose/tray_reference/debug_image")
                if _rs and _rs > 0:
                    self.img_view.setText("(RealSense 在线, 等待帧)")
                elif _fp:
                    self.img_view.setText("(FoundationPose 在线, 当前无帧)")
                else:
                    self.img_view.setText("(无图像发布者)")
                self.img_meta.setText(
                    f"当前无图像帧 — 发布者计数: RealSense 彩色={_rs} (D405 已接, Orin 未装 realsense2_camera), "
                    f"FoundationPose 调试帧={_fp} (vision_tag, 产线视觉空闲时不发帧)\n"
                    f"触觉 interfaces/msg/TactileSensor = 自定义消息, 容器无类型定义 → 暂不可订\n"
                    f"💡 现场一旦有帧 (驱动起来/产线跑) 这里会立即显示真图, 不会用旧帧或占位图冒充")

            self._feed_curves()
            self.lab_foot.setText(f"数据源: {p.get('file')} · 旁路记录 {os.path.basename(str(s.get('bypass_file', self.src.probe().get('bypass_file'))))}"
                                  f" · 刷新 500ms · 缺口/未示教项按缺报缺 (不填假值)")
        except Exception as e:
            self.lab_foot.setText(f"⚠️ 刷新异常: {type(e).__name__}: {e}")


class Z700SignalsView(QtWidgets.QWidget):
    """🖥 Z700 真机信号面板 (可视化层观察器, 输入=物理世界输出)

    显示**全部真机信号** (Orin 生产机器人 XMS5-R800 · 4060 远程只读):
      TCP 位姿(位置+四元数+坐标系) · 六关节位置/速度 · 六维力/力矩 · 夹爪开度 · 触觉 4D
      · 机器人状态(电源/运行/错误/急停/碰撞) · 产线阶段 · 采样率与新鲜度 · 缺通道清单
    另附状态空间旁路当前值 (阶段/残差/接触概率) — 物理世界输出 → 状态校正闭环的即时观测量。
    数据不新鲜 → 显示过期秒数; 通道缺失 → 显式"缺(无发布者)", 不用 0 冒充。
    """

    def __init__(self, module=None):
        super().__init__(None, QtCore.Qt.Window)
        self.module = module
        self.setWindowTitle("🖥 Z700 真机信号 — 全信号观测 (物理世界输出)")
        self.resize(1040, 620)
        self.setStyleSheet(SS)
        self.src = _load_src()
        self._build()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def _cell(self, title, hint=""):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(4, 3, 4, 3)
        v.setSpacing(1)
        t = QtWidgets.QLabel(title)
        t.setStyleSheet(f"color:{DIM};font-size:11px;")
        val = QtWidgets.QLabel("-")
        val.setStyleSheet(f"color:{FG};font-size:14px;")
        v.addWidget(t)
        v.addWidget(val)
        if hint:
            h = QtWidgets.QLabel(hint)
            h.setStyleSheet(f"color:{DIM};font-size:10px;")
            v.addWidget(h)
        return w, val

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel("🖥 Z700 真机信号 — 来源: 🌍 物理世界 输出 / 旁路真机传感器 (Orin 192.168.23.66 远程只读, 不接管)")
        head.setStyleSheet(f"color:{DIM};font-size:12px;")
        root.addWidget(head)
        self.labs = {}

        gb1 = QtWidgets.QGroupBox("真机 TCP 位姿 (base_link)")
        g1 = QtWidgets.QGridLayout(gb1)
        for i, (t_, k, h) in enumerate([("TCP X", "x", "m · 末端横向"), ("TCP Y", "y", "m · 末端纵向"),
                                        ("TCP Z", "z", "m · 末端高度"), ("姿态四元数", "quat", "x,y,z,w · 末端朝向"),
                                        ("位置变化率", "dx", "m/s · 由连续帧差分 (真机运动)"),
                                        ("坐标系", "frame", "TCP 位姿参考系")]):
            w, lab = self._cell(t_, h)
            self.labs["tcp_" + k] = lab
            g1.addWidget(w, i // 3, i % 3)
        root.addWidget(gb1)

        gb2 = QtWidgets.QGroupBox("六关节 (珞石 XMS5-R800 · /real_joint_states)")
        g2 = QtWidgets.QGridLayout(gb2)
        for i in range(6):
            w, lab = self._cell(f"关节 {i+1} 位置", "rad · 位置反馈")
            self.labs[f"q{i}"] = lab
            g2.addWidget(w, 0, i)
            w2, lab2 = self._cell(f"关节 {i+1} 速度", "rad/s · 速度反馈")
            self.labs[f"dq{i}"] = lab2
            g2.addWidget(w2, 1, i)
        root.addWidget(gb2)

        gb3 = QtWidgets.QGroupBox("力觉 / 夹爪 / 触觉 / 机器人状态")
        g3 = QtWidgets.QGridLayout(gb3)
        for i, (t_, k, h) in enumerate([("六维力 Fx,Fy,Fz", "force", "N · 腕部力觉"),
                                        ("力矩 Tx,Ty,Tz", "torque", "N·m · 腕部力矩"),
                                        ("夹爪开度", "grip", "0~1000 · 传感器反馈"),
                                        ("触觉 4D", "tactile", "grasp/contact/dirx/diry"),
                                        ("电源状态", "power", "真机 /robot_status"),
                                        ("运行状态", "op", "idle/moving · 产线是否在动"),
                                        ("报警 / 急停 / 碰撞", "err", "has_error / estop / collision"),
                                        ("侧频 / 新鲜度", "rate", "Hz · 我方采集 10Hz 落盘")]):
            w, lab = self._cell(t_, h)
            self.labs["s_" + k] = lab
            g3.addWidget(w, i // 4, i % 4)
        root.addWidget(gb3)

        gbi = QtWidgets.QGroupBox("真机图像 (现场唯一有发布者的图像话题)")
        gi = QtWidgets.QHBoxLayout(gbi)
        self.img_view = QtWidgets.QLabel("(无图像)")
        self.img_view.setFixedSize(240, 180)
        self.img_view.setStyleSheet("background:#161b22; color:#8b949e; border:1px solid #30363d;")
        self.img_view.setAlignment(QtCore.Qt.AlignCenter)
        self.img_meta = QtWidgets.QLabel("-")
        self.img_meta.setStyleSheet(f"color:{FG};font-size:12px;")
        self.img_meta.setWordWrap(True)
        gi.addWidget(self.img_view)
        gi.addWidget(self.img_meta, 1)
        root.addWidget(gbi)

        gb4 = QtWidgets.QGroupBox("状态空间旁路 (物理世界输出 → 状态校正闭环)")
        g4 = QtWidgets.QGridLayout(gb4)
        for i, (t_, k, h) in enumerate([("当前阶段", "stage", "13 段状态机 · 旁路判定"),
                                        ("残差", "res", "m · 测量 vs 先验 (状态校正器)"),
                                        ("接触概率", "con", "σ(残差) · 接触判据"),
                                        ("旁路步 / 采样", "steps", "逐帧六层真源码"),
                                        ("零下行自证", "zero", "无 rclpy/socket/写回"),
                                        ("缺口", "gaps2", "缺通道与未示教项")]):
            w, lab = self._cell(t_, h)
            self.labs["b_" + k] = lab
            g4.addWidget(w, i // 3, i % 3)
        root.addWidget(gb4)
        self.lab_foot = QtWidgets.QLabel("")
        self.lab_foot.setStyleSheet(f"color:{DIM};font-size:11px;")
        root.addWidget(self.lab_foot)

    def refresh(self):
        try:
            p = self.src.read_latest()
            tcp = p.get("tcp")
            for k, i in (("x", 0), ("y", 1), ("z", 2)):
                self.labs["tcp_" + k].setText(f"{tcp[i]:+.4f}" if tcp else "-")
            q = p.get("tcp_quat")
            self.labs["tcp_quat"].setText(", ".join(f"{v:+.3f}" for v in q) if q else "缺")
            self.labs["tcp_frame"].setText(p.get("tcp_frame") or "-")
            # 位置变化率 (本窗口内相邻两次刷新差分, 真实运动指示)
            now = time.time()
            if tcp and getattr(self, "_last_tcp", None) is not None and now > getattr(self, "_last_t", 0):
                dt = now - self._last_t
                dx = sum((a - b) ** 2 for a, b in zip(tcp, self._last_tcp)) ** 0.5 / dt
                self.labs["tcp_dx"].setText(f"{dx:.4f}")
                self.labs["tcp_dx"].setStyleSheet(
                    f"color:{C_OK if dx > 0.002 else DIM};font-size:14px;")
            if tcp:
                self._last_tcp, self._last_t = tcp, now
            jp, jv = p.get("jpos") or [], p.get("jvel") or []
            for i in range(6):
                self.labs[f"q{i}"].setText(f"{jp[i]:+.4f}" if len(jp) > i else "-")
                self.labs[f"dq{i}"].setText(f"{jv[i]:+.4f}" if len(jv) > i else "缺")
            ft = p.get("ft")
            self.labs["s_force"].setText(", ".join(f"{v:+.3f}" for v in ft[:3]) if ft else "缺(无发布者)")
            self.labs["s_torque"].setText(", ".join(f"{v:+.3f}" for v in ft[3:6]) if ft else "缺(无发布者)")
            self.labs["s_grip"].setText(str(p.get("gripper")) if p.get("gripper") is not None else "缺(无发布者)")
            self.labs["s_tactile"].setText("缺(触觉话题未接)" if not p.get("tactile") else str(p["tactile"]))
            rs = {}
            try:
                import json as _j
                rs = _j.loads(p.get("robot_status") or "{}")
            except Exception:
                rs = {}
            self.labs["s_power"].setText(str(rs.get("power_state", "缺")))
            op = str(rs.get("operation_state", "缺"))
            self.labs["s_op"].setText(op)
            self.labs["s_op"].setStyleSheet(f"color:{C_OK if op == 'moving' else FG};font-size:14px;")
            self.labs["s_err"].setText(("有报警 " + str(rs.get("error_reason", ""))) if rs.get("has_error")
                                       else ("急停" if rs.get("estop_detected") else
                                             ("碰撞" if rs.get("collision_detected") else "正常")))
            st = self.src.probe()
            recv = st.get("recv") or {}
            self.labs["s_rate"].setText(("✅ " if p.get("fresh") else "⚠️过期 ") + f"{p.get('age_s')}s"
                                        + f" · tcp×{recv.get('tcp', 0)} joint×{recv.get('joint', 0)}")
            im = p.get("image") or {}
            png = im.get("png")
            if png and os.path.exists(png):
                pm = QtGui.QPixmap(png)
                if not pm.isNull():
                    self.img_view.setPixmap(pm.scaled(self.img_view.size(), QtCore.Qt.KeepAspectRatio,
                                                      QtCore.Qt.SmoothTransformation))
                self.img_meta.setText(f"话题: {im.get('topic')}\n尺寸: {im.get('w')}×{im.get('h')} "
                                      f"编码: {im.get('encoding')}\n对比度 std: {im.get('std')} "
                                      f"(>5 判真图)\n新鲜度: {im.get('age')}s\n文件: {os.path.basename(png)}")
            else:
                _pubs = (p.get("pubs") or {})
                _n = _pubs.get("/foundationpose/tray_reference/debug_image")
                _rs = _pubs.get("/realsense/color/image_raw")
                if _n:
                    self.img_view.setText("(话题在线, 当前无帧)")
                    self.img_meta.setText(f"话题: /foundationpose/tray_reference/debug_image\n发布者: {_n} (vision_tag) "
                                          f"— 在线但产线视觉空闲 → 无帧\nRealSense 彩色话题发布者: {_rs} "
                                          f"(D405 已接, Orin 未装 realsense2_camera)\n触觉: interfaces/msg/TactileSensor "
                                          f"(自定义消息, 容器无类型定义 → 暂不可订)")
                else:
                    self.img_view.setText("(无图像发布者)")
                    self.img_meta.setText("真机图像话题当前无发布者 (现场视觉节点未起)")
            b = self.src.read_bypass_status()
            last = b.get("last") or {}
            self.labs["b_stage"].setText(str(last.get("stage", "-")))
            self.labs["b_res"].setText(str(last.get("residual", "-")))
            self.labs["b_con"].setText(str(last.get("contact_p", "-")))
            self.labs["b_steps"].setText(f"{b.get('steps', '-')} / {b.get('samples', '-')}")
            zd = b.get("zero_downlink") or {}
            okz = bool(zd) and not zd.get("rclpy_imported")
            self.labs["b_zero"].setText("✅ 零下行" if okz else str(zd or "无心跳"))
            self.labs["b_zero"].setStyleSheet(f"color:{C_OK if okz else C_BAD};font-size:14px;")
            gaps = (b.get("gap") or {})
            gtxt = " · ".join(f"{k.split('(')[0]}×{v}" for k, v in gaps.items()) or "无"
            self.labs["b_gaps2"].setText(gtxt[:70])
            self.lab_foot.setText(f"数据源 {p.get('file')} · 关节名 {', '.join((p.get('jnames') or ['-'])[:2])}…"
                                  f" · 刷新 500ms · 缺通道按缺报缺 (不填假值)")
        except Exception as e:
            self.lab_foot.setText(f"⚠️ 刷新异常: {type(e).__name__}: {e}")


def open_z700_signals(module=None):
    """打开 Z700 真机信号面板 (单例由调用方持有)"""
    w = Z700SignalsView(module)
    w.show()
    return w


def open_bypass_view(module=None):
    """打开/复用窗口 (单例由调用方持有引用)"""
    w = SSBypassView(module)
    w.show()
    return w


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = SSBypassView()
    win.show()
    sys.exit(app.exec_())
