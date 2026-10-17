#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 全局数据空间 · 控制台视图 (对标 Apollo DreamView / CANoe 的 channel·message·signal)

🎯 2026-10-17 老倪三条口径 (本版按它重写):
  ① 「删除 数据闭环 页面」            → 只留 频道 / 状态空间工程 / 报文·信号 / 质量告警 / 字段真值
  ② 「数据空间的显示, 要根据配置中心的参数中心的数据库的数据进行实际配置」
                                    → 话题/端口/信号**全部从工程库读** (mw_node/mw_port/mw_topic/mw_signal),
                                      单位/量程向参数中心 (params 表) 取; 注册表只作为"另一来源"并列显示
  ③ 「状态空间工程的所有连接关系…保存到状态空间的工程数据库」
                                    → 画布写盘 (engineering/flows.save_canvas) 同一口同步 mw_* 表;
                                      本页只读库 ⇒ 画布改了、库没同步 = 显式标「⚠ 库过期」
  · 数据源全部是**已落盘的事实**, 本页不自己采数据(免得又一处口径):
      data/database/zmax/zmax_engineering.db  ← 工程库(节点/端口/连线/话题/信号) + 参数中心(params)
      zmax_data/dataspace/live.json           ← DDS 全链路探针(频率/帧龄/配对/字段真值/质量裁决)
      src/lerobot/dataspace/topics.py         ← DDS 注册表(话题/类型/QoS/生产者/消费者/门)
  · 老倪要求: 内容可复制可导出(JSON/CSV)、字少不挤不截断、指标不夸大
  · prod 档是"静默正确"(不发=预期) ⇒ 页面必须显式标出当前档位与"本档不发"的原因
"""
import csv
import io
import json
import os
import sys
import time

LIVE = os.environ.get("ZMAX_DATASPACE_LIVE", "/home/ubuntu/zmax/zmax_data/dataspace/live.json")
MODE_FILE = os.path.join(os.path.expanduser("~"), ".zmax_telemetry_mode")
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")

MODE_ORDER = ["prod", "diag", "calib", "test"]


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return {}


def registry():
    """DDS 注册表(话题/规则/模式) —— 从包里读, 不复制一份"""
    try:
        if os.path.join(REPO, "src") not in sys.path:
            sys.path.insert(0, os.path.join(REPO, "src"))
        from lerobot.dataspace import topics as T
        return T
    except Exception:                                                        # noqa: BLE001
        return None


def mwdb():
    """工程库接口 (lerobot.middleware.db) —— 不在包路径上时返回 None, 页面显式标"库不可用"。"""
    try:
        if os.path.join(REPO, "src") not in sys.path:
            sys.path.insert(0, os.path.join(REPO, "src"))
        from lerobot.middleware import db as _db
        return _db
    except Exception:                                                        # noqa: BLE001
        return None


def current_mode():
    """档位读取口径与守护一致: env > 运行时(文件) > prod"""
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env:
        return env, "env ZMAX_TELEMETRY(锁定)"
    try:
        with open(MODE_FILE, encoding="utf-8") as f:
            m = f.read().strip().lower()
        if m:
            return m, "运行时文件 ~/.zmax_telemetry_mode"
    except OSError:
        pass
    return "prod", "默认(未设置)"


def set_mode(mode):
    """切换档位(写运行时文件; env 锁定时由调用方拒绝)"""
    if mode not in MODE_ORDER:
        return False, "非法档位 %s" % mode
    if (os.environ.get("ZMAX_TELEMETRY") or "").strip():
        return False, "env ZMAX_TELEMETRY 已锁定, 页面不能改(改 env 或重启服务)"
    tmp = MODE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(mode + "\n")
    os.replace(tmp, MODE_FILE)
    return True, "已切到 %s (守护 2s 内跟随)" % mode


# ─────────────────────────── 工程库 (画布实际配置) ───────────────────────────
def project_status():
    """工程库状态: 哪套工程 / 行数 / 与画布是否同源 (过期=画布改过没落库)。"""
    db = mwdb()
    if db is None:
        return {"ok": False, "why": "工程库接口不可用 (lerobot.middleware.db 导入失败)"}
    try:
        st = db.status()
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, e)}
    if not st:
        return {"ok": False, "why": "库里还没有工程 (先保存一次画布)"}
    s = st[0]
    return {"ok": True, "project": s["project"], "canvas_path": s.get("canvas_path"),
            "sha": s.get("canvas_sha"), "built_at": s.get("built_at"),
            "nodes": s.get("node_n"), "links": s.get("link_n"), "topics": s.get("topic_n"),
            "stale": bool(s.get("stale")),
            "signals": len(db.signals(s["project"]) or [])}


def node_rows():
    """节点 → 输入/输出话题 (画布实际连线) —— 数据空间跟画布对齐的那张表。"""
    db = mwdb()
    if db is None:
        return []
    try:
        return db.node_rows()
    except Exception:                                                        # noqa: BLE001
        return []


def message_rows():
    """报文 (输出话题) + 它承载的信号。

    信号两层来源 (合并显示, 不互相覆盖):
      ① 声明/占位: mw_signal (来自节点模块或画布 params 的 _signals; 单位/量程由参数中心补齐)
      ② 实测: live.json 里该话题的 fields —— 实测字段优先展示 (真在线上跑的就是它), 标 src=实测
    """
    db = mwdb()
    if db is None:
        return []
    try:
        rows = db.message_rows()
    except Exception:                                                        # noqa: BLE001
        return []
    lt = (_load(LIVE).get("topics") or {})
    # 🧹 2026-10-17 老倪: 「Tx Rx 只显示节点名字, 不要 L5/L4/箭头, 全局规范名称」
    try:
        from lerobot.middleware import naming as _naming
    except Exception:                                                        # noqa: BLE001
        _naming = None
    try:
        _rows = db.node_rows() or []
        _nm = (_naming.unique_map([(n["node_id"], n["name"]) for n in _rows]) if _naming
               else {n["node_id"]: n["name"] for n in _rows})
    except Exception:                                                        # noqa: BLE001
        _nm = {}
    for r in rows:
        r["_names"] = _nm
        lv = {}
        for k, v in lt.items():                       # live 键可能是短名, 也可能是全路径
            if k == r["topic"] or (v or {}).get("topic") == r["topic"] or k == r["node_id"]:
                lv = v or {}
                break
        f = lv.get("fields") or {}
        if isinstance(f, dict) and f:
            r["signals"] = [{"signal": k,
                             "unit": (v.get("unit") if isinstance(v, dict) else "") or "",
                             "vmin": (v.get("min") if isinstance(v, dict) else None),
                             "vmax": (v.get("max") if isinstance(v, dict) else None),
                             "src": "实测", "param_id": ""}
                            for k, v in f.items()]
            r["n_signal"] = len(f)
        _nm = r.get("_names") or {}
        r["tx"] = (_naming.clean(r.get("node") or "", fallback=r["node_id"]) if _naming
                   else (r.get("node") or r["node_id"]))
        r["rx"] = ", ".join(_nm.get(x, x) for x in (r.get("consumers") or [])) or "—"
        r.pop("_names", None)
        r["hz"] = lv.get("hz", -1.0)
        r["age_s"] = lv.get("age_s")
    rows.sort(key=lambda r: (_lrank(r.get("layer")), str(r["topic"])))   # L5→L1→系统
    return rows


# ─────────────────────────── 频道 (工程库 ∪ DDS 注册表) ───────────────────────────
LAYER_SEQ = {"L5": 0, "L4": 1, "L3": 2, "L2": 3, "L1": 4, "meta": 5}


def _lrank(ly):
    return LAYER_SEQ.get(ly or "meta", 9)


def _live_match(topic, node_id, lt):
    """实测条目匹配: live.json 的键是注册表名(如 ss_state), 工程库是 ss.node.<id>.<port>。"""
    for k, v in (lt or {}).items():
        if k == topic or (v or {}).get("topic") == topic:
            return k, v or {}
        if node_id and k == node_id:
            return k, v or {}
        if node_id and isinstance(k, str) and topic.endswith("." + k):
            return k, v or {}
    return None, {}


def _sem_type_topic(topic, default="zmax::SSNodePort"):
    """topic → 语义类型 (注册表: config/platform/dds_topic_types.json)。"""
    try:
        from lerobot.middleware import topic_types as _tt
        return _tt.type_of_topic(topic) or default
    except Exception:                                                    # noqa: BLE001
        return default


def channel_rows():
    """频道清单: **工程库为主体** (画布实际配置) + DDS 注册表并列。"""
    T = registry()
    live = _load(LIVE)
    lt = live.get("topics") or {}
    mode = live.get("mode") or current_mode()[0]
    rows, seen = [], set()

    db = mwdb()
    if db is not None:
        try:
            tps = db.topics()
            sig_n = {}
            for s_ in (db.signals() or []):
                sig_n[(s_["node_id"], s_["port"])] = sig_n.get((s_["node_id"], s_["port"]), 0) + 1
        except Exception:                                                    # noqa: BLE001
            tps, sig_n = [], {}
        _ly = {}
        try:
            _ly = {n["node_id"]: n["layer"] for n in (db.node_rows() or [])}
        except Exception:                                                    # noqa: BLE001
            _ly = {}
        for t in tps:
            live_key, lv = _live_match(t["topic"], t["node_id"], lt)
            rules = lv.get("rules") or []
            bad = [r for r in rules if not r.get("ok")]
            rows.append({
                "topic": t["topic"], "src": "工程库",
                "layer": _ly.get(t["node_id"], "meta"),
                "node": t["node_id"], "port": t["port"], "dir": t["dir"],
                "type": t.get("type") or _sem_type_topic(t["topic"]), "qos": t["qos"],
                "hz": lv.get("hz", -1.0), "hz_design": lv.get("hz_design"),
                "age_s": lv.get("age_s"), "count": lv.get("count", 0),
                "matched": lv.get("matched_pubs"),
                "verdict": lv.get("verdict", "-"), "score": lv.get("score", -1.0),
                "bad": "; ".join("%s(%s)" % (r.get("rule"), r.get("msg")) for r in bad),
                "producer": t["node_id"], "consumers": "",
                "fields": lv.get("fields") or {}, "signals_n": sig_n.get((t["node_id"], t["port"]), 0),
                "allowed": (live_key in T.topics_for_mode(mode)) if (T and live_key) else None,
            })
            seen.add(t["topic"])

    # DDS 注册表里另有、工程库没覆盖到的 (板级/真机遥测等) —— 也列出, 标来源
    for k, reg in (list(T.TOPICS.items()) if T else []):
        name = "zmax/" + k
        if name in seen or k in seen:
            continue
        lv = lt.get(k) or {}
        rules = lv.get("rules") or []
        bad = [r for r in rules if not r.get("ok")]
        rows.append({
            "topic": name, "src": "注册表", "layer": "meta", "node": "-", "port": "-", "dir": "-",
            "type": (reg.get("type") or "").split("::")[-1], "qos": reg.get("qos"),
            "hz": lv.get("hz", -1.0), "hz_design": reg.get("rate_hz") or lv.get("hz_design"),
            "age_s": lv.get("age_s"), "count": lv.get("count", 0),
            "matched": lv.get("matched_pubs"),
            "verdict": lv.get("verdict", "-"), "score": lv.get("score", -1.0),
            "bad": "; ".join("%s(%s)" % (r.get("rule"), r.get("msg")) for r in bad),
            "producer": (reg.get("producer") or "")[:60],
            "consumers": ", ".join(reg.get("consumers") or [])[:60],
            "fields": lv.get("fields") or {}, "signals_n": 0,
            "allowed": (k in T.topics_for_mode(mode)) if T else None,
        })
    return rows


def alerts():
    """质量告警流: 频道规则不过 (闭环页已按老倪要求删除, 不再混入)。"""
    out = []
    for r in channel_rows():
        if r["bad"]:
            out.append((r["verdict"], r["topic"], r["bad"], r["age_s"]))
    return sorted(out, key=lambda x: {"fail": 0, "veto": 0, "warn": 1}.get(x[0], 2))


def summary_line():
    T = registry()
    live = _load(LIVE)
    mode, src = current_mode()
    age = (time.time() - live["ts"]) if live.get("ts") else None
    ps = project_status()
    return {
        "mode": mode, "mode_src": src, "mode_desc": (T.MODE_DESC.get(mode, "") if T else ""),
        "n_allowed": live.get("n_topics_allowed"), "n_reg": live.get("n_topics_registered"),
        "alive": live.get("n_topic_alive"),
        "live_age_s": round(age, 1) if age is not None else None,
        "project": ps, "n_alerts": len(alerts()),
        "registry_v": live.get("registry_version") or (T.VERSION if T else None),
    }


def export_csv(rows=None):
    rows = rows or channel_rows()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["topic", "层", "来源", "节点", "端口", "方向", "类型", "QoS", "实测Hz", "设计Hz",
                "帧龄s", "条数", "配对", "裁决", "本档允许", "信号数", "问题"])
    for r in rows:
        w.writerow([r["topic"], r.get("layer") or "meta", r["src"], r["node"], r["port"], r["dir"],
                    r["type"], r["qos"],
                    r["hz"], r["hz_design"], r["age_s"], r["count"], r["matched"], r["verdict"],
                    r["allowed"], r["signals_n"], r["bad"]])
    return buf.getvalue()


def export_json():
    """可复制/可导出: 频道 + 节点 in/out + 报文/信号 一把给全 (供脚本/CI 直接吃)。"""
    return json.dumps({"ts": time.time(), "summary": summary_line(),
                       "channels": channel_rows(),
                       "nodes": node_rows(), "messages": message_rows(),
                       "alerts": alerts()}, ensure_ascii=False, indent=1)


# ─────────────────────────── Qt 视图(被 studio 嵌入) ───────────────────────────
def build_widget(parent=None, into_tabs=None):
    """返回本页的头部条(档位/刷新/导出)。

    into_tabs=None  → 自己带一个 QTabWidget(独立查看用)
    into_tabs=<QTabWidget> → 把 5 个 Tab 塞进调用方那一个 Tab 栏里
                            (老倪: 一个功能一个入口, 不做第 13 个模块卡, 也不做嵌套 Tab)
    """
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QColor, QFont
    from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                                 QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                                 QTextEdit, QVBoxLayout, QWidget)

    DARK = "background:#0d1117; color:#c9d1d9;"
    OK, WARN, BAD, DIM, BLUE = "#3fb950", "#d29922", "#f85149", "#8b949e", "#58a6ff"
    MONO = QFont("DejaVu Sans Mono", 9)

    class DataSpaceView(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setStyleSheet(DARK)
            self.setAttribute(Qt.WA_StyledBackground, True)   # 否则整条工具条漏出调色板亮底
            self.setAutoFillBackground(False)
            v = QVBoxLayout(self)
            v.setContentsMargins(8, 6, 8, 6)
            v.setSpacing(6)

            head = QHBoxLayout()
            self.lbl = QLabel("加载中…")
            self.lbl.setStyleSheet("font-size:12px; color:#e6edf3;")
            head.addWidget(self.lbl, 1)
            head.addWidget(QLabel("档位:"))
            self.cmb = QComboBox()
            self.cmb.addItems(MODE_ORDER)
            head.addWidget(self.cmb)
            self.btn_mode = QPushButton("切换档位")
            self.btn_ref = QPushButton("刷新")
            self.btn_csv = QPushButton("导出 CSV")
            self.btn_json = QPushButton("复制 JSON")
            for b in (self.btn_mode, self.btn_ref, self.btn_csv, self.btn_json):
                head.addWidget(b)
            v.addLayout(head)

            self.tabs = into_tabs if into_tabs is not None else QTabWidget()
            _own = into_tabs is None

            # ① 频道 (工程库 ∪ 注册表)
            self.t_ch = QTableWidget(0, 11)
            self.t_ch.setHorizontalHeaderLabels(["话题", "层", "来源", "方向", "类型/QoS", "实测Hz/设计",
                                                 "帧龄s", "条数", "信号", "裁决", "问题"])
            self.t_ch.setFont(MONO)
            self.t_ch.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.t_ch.horizontalHeader().setSectionResizeMode(10, QHeaderView.Stretch)
            self.t_ch.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.t_ch.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.t_ch.itemSelectionChanged.connect(self._show_fields)
            self.tabs.addTab(self.t_ch, "📡 频道 (topic)")

            # ② 状态空间工程: 节点 × 输入/输出话题 (画布实际连线)
            self.t_pj = QTableWidget(0, 5)
            self.t_pj.setHorizontalHeaderLabels(["节点", "类型 / 层", "输入 topic (端口 ← 上游)",
                                                 "输出 topic (端口 → 下游)", "信号"])
            self.t_pj.setFont(MONO)
            self.t_pj.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.t_pj.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.t_pj.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.t_pj.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.t_pj.itemSelectionChanged.connect(self._show_node)
            self.tabs.addTab(self.t_pj, "🧩 状态空间工程")

            # ③ 报文 / 信号 (message ↔ signal)
            # 🧭 2026-10-17 老倪「信号表增加 Tx Rx 两列」—— 这张表同样给出 发送节点/接收节点
            self.t_ms = QTableWidget(0, 7)
            self.t_ms.setHorizontalHeaderLabels(["层", "报文 (topic)", "端口", "QoS",
                                                 "Tx 发送节点", "Rx 接收节点",
                                                 "信号 (名 · 单位 · 量程)"])
            self.t_ms.setFont(MONO)
            # 🎯 2026-10-17 老倪: 「这些列要对齐, 字显示不全」+「Tx Rx 都看不全, 不要截断省略」
            #   ⇒ 列宽按**内容**铺 (ResizeToContents), 不省略; 表比面板宽就横向滚动
            _mh = self.t_ms.horizontalHeader()
            for _i in range(6):
                _mh.setSectionResizeMode(_i, QHeaderView.ResizeToContents)
            _mh.setSectionResizeMode(6, QHeaderView.Stretch)
            self.t_ms.setTextElideMode(Qt.ElideNone)
            self.t_ms.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.t_ms.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.t_ms.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.t_ms.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.tabs.addTab(self.t_ms, "📨 报文 / 信号")

            # ④ 告警
            self.t_al = QTableWidget(0, 3)
            self.t_al.setHorizontalHeaderLabels(["级别", "对象", "问题"])
            self.t_al.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.t_al.setFont(MONO)
            self.t_al.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.tabs.addTab(self.t_al, "⚠ 质量告警")

            # ⑤ 字段真值
            self.txt = QTextEdit()
            self.txt.setReadOnly(True)
            self.txt.setFont(MONO)
            self.tabs.addTab(self.txt, "🔎 字段真值")
            if _own:
                v.addWidget(self.tabs, 1)

            self.btn_ref.clicked.connect(self.refresh)
            self.btn_mode.clicked.connect(self._do_mode)
            self.btn_csv.clicked.connect(self._csv)
            self.btn_json.clicked.connect(self._json)
            self.refresh()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh)      # 只读本地库/JSON ⇒ 主线程直接刷(无网络)
            self.timer.start(2000)

        # ── 渲染 ──────────────────────────────────────────────
        def refresh(self):
            s = summary_line()
            color = {"prod": DIM, "diag": OK, "calib": WARN, "test": BLUE}.get(s["mode"], DIM)
            ps = s.get("project") or {}
            if ps.get("ok"):
                pj = ("工程库 <b>%s</b> · 节点 %s / 连线 %s / 话题 %s / 信号 %s · 建于 %s%s"
                      % (ps["project"], ps["nodes"], ps["links"], ps["topics"], ps["signals"],
                         ps["built_at"], " <span style='color:%s'>⚠ 库过期(画布改过没落库)</span>" % WARN
                         if ps.get("stale") else " · 与画布同源"))
            else:
                pj = "<span style='color:%s'>工程库不可用: %s</span>" % (BAD, ps.get("why"))
            self.lbl.setText(
                "档位 <b style='color:%s'>%s</b>(%s) · 本档允许 <b>%s</b>/注册 %s · 活着 %s · "
                "live 龄 %ss · 告警 %s 条<br>%s"
                % (color, s["mode"], s["mode_src"], s["n_allowed"], s["n_reg"], s["alive"],
                   s["live_age_s"], s["n_alerts"], pj))
            self.lbl.setTextFormat(Qt.RichText)
            self.cmb.setCurrentText(s["mode"] if s["mode"] in MODE_ORDER else "prod")

            rows = sorted(channel_rows(), key=lambda r: (_lrank(r.get("layer")), str(r["topic"])))
            self.t_ch.setRowCount(len(rows))
            for i, r in enumerate(rows):
                vcol = {"ok": OK, "warn": WARN, "veto": BAD, "-": DIM}.get(r["verdict"], DIM)
                cells = [r["topic"], r.get("layer") or "meta", r["src"], r["dir"],
                         "%s / %s" % (r["type"], r["qos"]),
                         "%.2f / %s" % (r["hz"], r["hz_design"] if r["hz_design"] is not None else "—"),
                         "%.1f" % r["age_s"] if r["age_s"] is not None else "—",
                         str(r["count"]), str(r["signals_n"]), r["verdict"], r["bad"]]
                for c, t in enumerate(cells):
                    it = QTableWidgetItem(t)
                    if c == 9:
                        it.setForeground(QColor(vcol))
                    elif c == 1:
                        it.setForeground(QColor("#d2a8ff" if (r.get("layer") or "meta") != "meta" else DIM))
                    elif c == 2:
                        it.setForeground(QColor(BLUE if r["src"] == "工程库" else DIM))
                    elif c == 6 and r["age_s"] is not None and r["age_s"] > 5:
                        it.setForeground(QColor(WARN))
                    self.t_ch.setItem(i, c, it)

            nr = sorted(node_rows(), key=lambda n: (_lrank(n.get("layer")), str(n["node_id"])))
            ms = message_rows()
            _sig_by_node = {}
            for m in ms:
                _sig_by_node[m["node_id"]] = _sig_by_node.get(m["node_id"], 0) + m["n_signal"]
            self.t_pj.setRowCount(len(nr))
            for i, n in enumerate(nr):
                ins = "  ".join("%s ← %s" % (x["port"], ",".join(x["from"]) or "-") for x in n["ins"]) or "—"
                outs = "  ".join("%s → %s" % (x["port"], ",".join(x["to"]) or "-") for x in n["outs"]) or "—"
                n_sig = _sig_by_node.get(n["node_id"], 0)
                cells = ["%s (%s)" % ((_naming.clean(n["name"], fallback=n["node_id"]) if _naming else n["name"]),
                                      n["module"]),
                         "%s · %s" % (n.get("layer") or "meta", n["type"]), ins, outs, str(n_sig)]
                for c, t in enumerate(cells):
                    it = QTableWidgetItem(t)
                    if c == 4:
                        it.setForeground(QColor(DIM))
                    self.t_pj.setItem(i, c, it)

            self.t_ms.setRowCount(len(ms))
            for i, m in enumerate(ms):
                sigs = "; ".join(
                    "%s%s%s" % (x["signal"],
                                (" · " + x["unit"]) if x.get("unit") else "",
                                (" [%s~%s]" % (x["vmin"], x["vmax"]))
                                if x.get("vmin") is not None and x.get("vmax") is not None else "")
                    for x in m["signals"]) or "—"
                cells = [m.get("layer") or "meta", m["topic"], m["port"],
                         str(m["qos"]), m.get("tx") or "—", m.get("rx") or "—", sigs]
                for c, t in enumerate(cells):
                    it = QTableWidgetItem(t)
                    it.setToolTip(t)                       # 列宽只影响显示, 全文永远看得到
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    if c == 0:
                        it.setForeground(QColor("#d2a8ff" if (m.get("layer") or "meta") != "meta" else DIM))
                    self.t_ms.setItem(i, c, it)

            al = alerts()
            self.t_al.setRowCount(len(al))
            for i, (lv, obj, msg, _a) in enumerate(al):
                for c, t in enumerate([lv, obj, msg]):
                    self.t_al.setItem(i, c, QTableWidgetItem(t))

        def _show_fields(self):
            r = self.t_ch.currentRow()
            rows = channel_rows()
            if r < 0 or r >= len(rows):
                return
            x = rows[r]
            self.txt.setPlainText(json.dumps({
                "话题": x["topic"], "层": x.get("layer") or "meta", "来源": x["src"],
                "节点": x["node"], "端口": x["port"],
                "方向": x["dir"], "类型": x["type"], "QoS": x["qos"],
                "实测Hz": x["hz"], "设计Hz": x["hz_design"], "帧龄s": x["age_s"],
                "发布者": x["producer"], "消费者": x["consumers"],
                "信号数": x["signals_n"], "最新字段真值": x["fields"],
                "质量问题": x["bad"] or "无",
            }, ensure_ascii=False, indent=1))

        def _show_node(self):
            """点节点 → 在真值页给出该节点的完整 in/out 报文 (可复制)。"""
            r = self.t_pj.currentRow()
            nr = node_rows()
            if r < 0 or r >= len(nr):
                return
            n = nr[r]
            ms = [m for m in message_rows() if m["node_id"] == n["node_id"]]
            self.txt.setPlainText(json.dumps({
                "节点": (_naming.clean(n["name"], fallback=n["node_id"]) if _naming else n["name"]),
                "节点全名": n["name"], "id": n["node_id"], "模块": n["module"],
                "类型": n["type"], "层": n["layer"], "执行口径": n["exec_mode"],
                "实现绑定": n["impl_key"], "实现源码": n["source"],
                "输入报文": n["ins"], "输出报文": n["outs"], "报文明细": ms,
            }, ensure_ascii=False, indent=1))

        def _do_mode(self):
            ok, msg = set_mode(self.cmb.currentText())
            self.lbl.setToolTip(msg)
            self.refresh()

        def _csv(self):
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(export_csv())
            self.lbl.setToolTip("CSV 已复制到剪贴板(%d 行)" % len(channel_rows()))

        def _json(self):
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(export_json())
            self.lbl.setToolTip("JSON 已复制到剪贴板")

    w = DataSpaceView(parent)
    return w


if __name__ == "__main__":          # 自检/独立查看: QT_QPA_PLATFORM=offscreen python dds_space.py --dump
    if "--dump" in sys.argv:
        print(json.dumps({"summary": summary_line(), "nodes": len(node_rows()),
                          "messages": len(message_rows()), "channels": len(channel_rows())},
                         ensure_ascii=False, indent=1)[:2000])
    else:
        from PyQt5.QtWidgets import QApplication
        app = QApplication(sys.argv)
        w = build_widget()
        w.resize(1180, 620)
        w.show()
        sys.exit(app.exec_())
