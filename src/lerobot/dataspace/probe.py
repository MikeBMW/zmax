#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 全链路 topic 可视化探针 —— 全局数据空间的"眼睛"

干什么: 按当前遥测模式订阅**全空间话题**, 实测 频率/帧龄/发布者数/字段值, 逐帧跑质量规则,
        把结果写成一个 JSON —— 控制台(数据空间页)、网页、巡检脚本都读它。
为什么这样做: cyclonedds 只装在独立 venv(~/zmax/venvs/dds-venv), 控制台/主应用不该被它污染依赖
        ⇒ 「DDS → JSON 桥」(见技能 dds-messaging)。

用法(必须 dds-venv):
    ~/zmax/venvs/dds-venv/bin/python -m lerobot.dataspace.probe --seconds 12          # 采 12 秒后打印+落盘
    ~/zmax/venvs/dds-venv/bin/python -m lerobot.dataspace.probe --watch --interval 2  # 常驻, 每 2s 更新 JSON
    ~/zmax/venvs/dds-venv/bin/python -m lerobot.dataspace.probe --once --json         # 只打 JSON

输出: /home/ubuntu/zmax/zmax_data/dataspace/live.json
"""
import argparse
import json
import os
import signal
import sys
import time

# ── 依赖路径 ────────────────────────────────────────────────────────────────
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))

# ⚠️ 待收口(老倪: 逻辑代码只能有一个 CICD 路径): DDS 类型/Node 目前在仓库外
#    /home/ubuntu/zmax/dds/{ss_types,zmax_types,zmax_node}.py —— 见 docs/design/global_data_space_mapping_*.md
DDS_DIR = os.environ.get("ZMAX_DDS_DIR", "/home/ubuntu/zmax/dds")
for _p in (DDS_DIR, os.path.join(REPO, "tools", "gui")):
    # tools/gui 也要加: link_value(画布连线)类型还住在 tools/gui/dds_link_bus.py(待收口)
    if _p not in sys.path:
        sys.path.insert(0, _p)
CFG = os.environ.get("ZMAX_DDS_CFG", "/home/ubuntu/zmax/dds/cyclonedds_unicast.xml")
OUT = os.environ.get("ZMAX_DATASPACE_LIVE", "/home/ubuntu/zmax/zmax_data/dataspace/live.json")

from lerobot.dataspace import quality, topics as T                      # noqa: E402

_STOP = {"v": False}


def _on_sig(*_a):
    _STOP["v"] = True


def np_std(xs):
    """纯 python 标准差(不引 numpy, dds-venv 保持干净)"""
    if len(xs) < 2:
        return 0.0
    mu = sum(xs) / len(xs)
    return (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _jsonable(v):
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


def _digest_for(k, f):
    """按话题给**一行可读摘要** —— 否则长数组(如 ss_plan 的 joints_path n×6)会把 digest 灌满数字"""
    try:
        if k == "ss_plan":
            return ("plan-only: n=%s (joints_path %d / tcp_path %d) plan_code=%s 时长=%ss "
                    "终点误差=%smm FK起点差=%smm 同源闸=%s[%s] age=%ss"
                    % (f.get("n_points"), len(f.get("joints_path") or []),
                       len(f.get("tcp_path") or []), f.get("plan_code"), f.get("plan_time_s"),
                       f.get("end_err_mm"), f.get("fk_start_pos_err_mm"),
                       f.get("gate_same_source"), (f.get("gate_reason") or "")[:70],
                       f.get("frame_age_s")))[:400]
        if k == "ss_state":
            return ("state: vec[%s]=%s tcp=(%s,%s,%s) layer=%s source=%s note=%s"
                    % (f.get("dim"), (f.get("vec") or [])[:6], f.get("pos_x"), f.get("pos_y"),
                       f.get("pos_z"), f.get("layer"), f.get("source"),
                       (f.get("note") or "")[:60]))[:400]
        if k == "ss_stage":
            # 🎛 八阶段状态机 (老倪 2026-10-15「没看到 topic 在信号分析里啊」): 兜底 body[:180] 会
            #    把 JSON 截断 ⇒ parse_ds_digest 解析不出数值叶子 ⇒ 信号页里"看得到话题、没有波形"。
            #    这里给一行**完整 JSON**(只留要画的叶子)。
            return json.dumps({"idx": f.get("idx"), "idx8": f.get("idx8"), "v_cap": f.get("v_cap"),
                               "done": f.get("done"), "age_s": f.get("age_s"),
                               "name": f.get("name") or ""}, ensure_ascii=False)[:400]
        if k == "ss_action_chunk":
            # 🧩 动作块 (老倪 2026-10-15「Flow Matching Action Head 的输出是个 chunk action … 应该有输出 topic,
            #   在信号分析里显示」): 载荷里 chunk/ff/u 都是长数组 ⇒ 通用兜底会把 digest 灌满原始浮点。
            #   这里给一行紧凑 JSON: 每拍**速度模长** (mm/s 由界面换算) + 权重 λ + 平滑性 + 阶段 + 技能派发。
            _ch = [float(x) for x in (f.get("chunk") or [])]
            _uu = [float(x) for x in (f.get("u") or [])]
            _lam = [float(x) for x in (f.get("lam") or [])]
            _h = int(f.get("h") or 0)

            def _nrm(arr, i):
                seg = arr[4 * i:4 * i + 3]
                return round(float(sum(x * x for x in seg) ** 0.5), 6) if seg else None

            _d = {"h": _h, "stage": str(f.get("stage") or ""), "stage_idx": f.get("stage_idx"),
                  "turn_mean_deg": f.get("turn_mean_deg"), "step_delta": f.get("step_delta"),
                  "jerk": f.get("jerk"), "u_norm0": f.get("u_norm0"), "ms": f.get("ms"),
                  "dispatch_age_s": f.get("dispatch_age_s"), "cycle": f.get("cycle")}
            # ⚠️ digest 整行有 400 字上限: 8 拍 × 3 组会把尾巴切掉 (切出非法 JSON ⇒ 正则也抠不全)。
            #   这里给 6 拍 (页面够画; 完整块在话题载荷与 chunk_latest.json 里), 名字串放最后。
            for i in range(min(_h, 8)):
                _d["c%d" % i] = _nrm(_ch, i)          # 块第 i 拍 (引擎规划)
                _d["u%d" % i] = _nrm(_uu, i)          # 加权+调制+安全后第 i 拍
                _d["lam%d" % i] = (round(_lam[i], 4) if i < len(_lam) else None)
            _d["skill_list"] = str(f.get("skill_list") or "")[:70]
            _d["ff_mode"] = str(f.get("ff_mode") or "")[:40]
            # 上限放宽到 760 (8 拍 ×3 组 + 技能串实测 ~520 字): 切在 JSON 中间会切出**非法 JSON**,
            #   下游 (页面/判据) 连前面的数都抠不全 —— 块这种"长数组型"载荷必须放宽, 别照搬 400。
            return json.dumps(_d, ensure_ascii=False, separators=(",", ":"))[:760]
        if k == "ss_meta_pred":
            # 🧾 元任务预测值 (老倪 2026-10-15「元任务预测这个节点…要加入到实时监控的信号分析」):
            #   载荷里 top_ids/top_scores 是长字符串 ⇒ 通用兜底 body[:180] 切到 top_ids 就断了,
            #   数值叶子一个都读不到 ⇒ 信号页"话题在列表、没有波形"(与 ss_stage 同款坑)。
            #   这里给一行**完整紧凑 JSON**: 数值在前、名字在后 (真被切也只丢名字, 不丢可画的数)。
            _sc = [x for x in str(f.get("top_scores") or "").replace(" ", "").split(",") if x]
            _ids = [x.strip() for x in str(f.get("top_ids") or "").split(",") if x.strip()]
            _v = []
            for _x in _sc[:5]:
                try:
                    _v.append(float(_x))
                except Exception:                                              # noqa: BLE001
                    pass
            # 🧾 文本槽: 确切元任务 (功能号 + 名字 + 得分) —— 信号页拿它上屏, 不是只画数
            _txt = " › ".join("%s %.4f" % (_ids[i], _v[i]) for i in range(min(3, len(_ids), len(_v))))
            return json.dumps({"mt1": (_v[0] if _v else None),
                               "mt2": (_v[1] if len(_v) > 1 else None),
                               "mt3": (_v[2] if len(_v) > 2 else None),
                               "mt4": (_v[3] if len(_v) > 3 else None),
                               "mt5": (_v[4] if len(_v) > 4 else None),
                               "spread": (round(_v[0] - _v[1], 6) if len(_v) > 1 else None),
                               "n_meta": f.get("n_meta"), "n_cand": f.get("n_cand"),
                               "trained": f.get("trained"), "frozen": f.get("frozen"),
                               "input_ok": f.get("input_ok"),
                               "t_pred_s": (round(float(f.get("ts") or 0) - float(f.get("ts_pred") or 0), 3)
                                            if f.get("ts_pred") else None),
                               "in_age_s": f.get("input_age_s"),
                               "top_txt": _txt, "scene": f.get("scene") or ""},
                              ensure_ascii=False)[:400]
        if k == "ss_torque":
            # 🔧 驱动扭矩 T_drive=M·(−∇Φ): 载荷是 6D 数组 + 36/9 维张量 + 长说明, 直接截断会得到
            #    **残缺 JSON** ⇒ parse_ds_digest 解析不出数值叶子 ⇒ 实时监控里"看得到话题、没有波形"
            #    (判据 ⑧b 实测 0/117 帧可解析)。这里给一行**完整 JSON**: 只留监控要画的标量叶子。
            tq = f.get("torque") or []
            return json.dumps({"torque_norm": f.get("torque_norm"), "raw_norm": f.get("torque_raw_norm"),
                               "T_x": tq[3] if len(tq) > 3 else None, "T_y": tq[4] if len(tq) > 4 else None,
                               "T_z": tq[5] if len(tq) > 5 else None,
                               "phi": f.get("phi"), "grad_norm": f.get("grad_raw_norm"),
                               "health": f.get("health"), "gain": f.get("gain"),
                               "metric_dim": f.get("metric_dim"), "t_max": f.get("t_max"),
                               "clipped": 1 if f.get("clipped") else 0,
                               "d_trough_m": f.get("dist_to_trough_m"),
                               "status": f.get("status"), "stage": f.get("stage")},
                              ensure_ascii=False)[:400]
    except Exception:                                                        # noqa: BLE001
        return None
    return None


def _fields_of(msg):
    """按 dataclass 声明白名单取字段 —— 丢掉 DDS 元数据(否则 json 会爆 SampleInfo)"""
    keys = list(getattr(type(msg), "__dataclass_fields__", {}).keys())
    return {k: _jsonable(getattr(msg, k, None)) for k in keys if not k.startswith("_")}


def _mode():
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env in T.MODE_TOPICS:
        return env
    try:
        m = open(os.path.join(os.path.expanduser("~"), ".zmax_telemetry_mode"),
                 encoding="utf-8").read().strip().lower()
        if m in T.MODE_TOPICS:
            return m
    except OSError:
        pass
    return "prod"


class Probe:
    def __init__(self, mode=None, out=OUT):
        self.mode = mode or _mode()
        self.fixed_mode = mode
        self.keys = T.topics_for_mode(self.mode)
        self.out = out
        self._tr_last = {}    # topic → 上次落 Trace 的时刻 (每话题限速 1s, 见 pump)
        self.node = None
        self.st = {}          # topic → 统计(所有曾经见过的)
        self.hist = {}        # topic → 接收时刻(最近 120s)
        self.trace = []       # 🚌 Trace 窗口(CANoe 报文追踪): 最近 N 条
        self.tr_bytes = {}    # topic → 累计载荷估算(bytes)
        self.t0 = time.time()
        if self.keys:
            from zmax_node import Node
            self.node = Node("dataspace-probe", domain=0, config_xml=CFG)
            self._ensure(self.keys)

    def _make_reader(self, k):
        """观察者读取端: BEST_EFFORT·KEEP_LAST(200) —— 深历史, 只观察不改发布端语义"""
        import zmax_node as ZN
        from cyclonedds.core import Policy, Qos
        from cyclonedds.sub import DataReader
        from cyclonedds.topic import Topic
        t = Topic(self.node.dp, "zmax/" + k, ZN.TOPICS[k])
        q = Qos(ZN._p(Policy.Reliability.BestEffort, 0), ZN._p(Policy.History.KeepLast, 200))
        return DataReader(self.node.dp, t, qos=q)

    def _ensure(self, keys):
        """给新话题建 reader + 统计槽(档位切换后补订, 不用重建进程)"""
        for k in keys:
            if k not in self.st:
                self.st[k] = {"count": 0, "last_ts": None, "last_fields": None,
                              "verdict": "-", "score": -1.0, "rules": []}
                self.hist[k] = []
                self.tr_bytes[k] = 0
                if self.node is not None:
                    try:
                        self.node._r[k] = self._make_reader(k)      # 深历史观察者(见上)
                        self.node.wait_for_match(k, 1, timeout=1.0)
                    except Exception:                                        # noqa: BLE001
                        try:
                            self.node.sub(k)
                        except Exception:                                    # noqa: BLE001
                            pass

    def follow_mode(self):
        """档位跟随: 工程上任何时候切档, 探针 2s 内跟上(不重启进程)"""
        m = self.fixed_mode or _mode()
        if m == self.mode:
            return False
        self.mode = m
        self.keys = T.topics_for_mode(m)
        if self.node is None and self.keys:
            from zmax_node import Node
            self.node = Node("dataspace-probe", domain=0, config_xml=CFG)
        self._ensure(self.keys)
        return True

    # ── 采一轮 ──────────────────────────────────────────────────────────
    def pump(self, seconds):
        t0, now = time.time(), time.time()
        while time.time() - t0 < seconds and not _STOP["v"]:
            now = time.time()
            self.follow_mode()
            for k in self.st:                       # 已订的全部收(含刚切档前订的, 便于对照)
                if k not in self.keys and self.node is not None:
                    try:
                        self.node.sub(k).take()    # 本档不允许的话题: 只抽干不统计
                    except Exception:                                        # noqa: BLE001
                        pass
                    continue
                try:
                    samples = self.node.sub(k).take()
                except Exception as e:                                       # noqa: BLE001
                    self.st[k]["rules"] = [{"rule": "take", "ok": False, "level": "warn", "msg": str(e)[:80]}]
                    continue
                for m in samples or []:
                    f = _fields_of(m)
                    s = self.st[k]
                    s["count"] += 1
                    s["last_ts"] = f.get("ts")
                    s["last_fields"] = f
                    body = json.dumps(f, ensure_ascii=False)
                    dg = _digest_for(k, f) or body[:180]
                    self.tr_bytes[k] = self.tr_bytes.get(k, 0) + len(body)
                    # Trace 采样规则 (2026-10-13 修): 原规则 `len(trace)<500 or count%20==0` 对**低频话题**
                    #   等于 40s 才落一帧 (实测 ss_torque 0.5Hz ⇒ 监控里几乎看不见) ⇒ 改为**每话题限速 1s**:
                    #   首次必落, 之后同一话题 ≥1s 才再落, 既保文件大小又让低/高频话题都看得见。
                    last_k = self._tr_last.get(k, 0.0)
                    if len(self.trace) < 500 or (now - last_k) >= 1.0:
                        self._tr_last[k] = now
                        self.trace.append({"t": round(now, 3), "topic": T.full_name(k),
                                           "type": (T.TOPICS.get(k, {}).get("type") or "").split("::")[-1],
                                           "n": s["count"], "bytes": len(body),
                                           "digest": dg})
                        if len(self.trace) > 800:
                            self.trace = self.trace[-600:]
                    self.hist[k].append(now)
                    if len(self.hist[k]) > 4000:
                        self.hist[k] = self.hist[k][-2000:]
            time.sleep(0.05)
        return now

    def snapshot(self, now=None):
        now = now or time.time()
        win = 5.0
        rows = {}
        elapsed = max(1e-6, now - self.t0)
        for k in self.st:
            s = self.st[k]
            _allowed = k in self.keys
            # 平均频率按**整个观测窗**算(低速率话题在 5s 滑窗里只有 1~2 条, 会系统性低估)
            # ★ 诊断关键: 配到了几个发布者 —— 0=发现层没通, >0 而 0 条=发布端没在发/QoS 不兼容
            matched = 0
            try:
                if self.node is not None:
                    matched = len(self.node.sub(k).get_matched_publications() or [])
            except Exception:                                                # noqa: BLE001
                matched = -1
            h = [t for t in self.hist[k] if now - t <= 120.0]     # 频率按最近 120s 算(长跑收敛, 短窗不抖)
            span = (h[-1] - h[0]) if len(h) > 1 else 0.0
            hz = round((len(h) - 1) / span, 2) if span > 0.5 else (0.0 if s["count"] else -1.0)
            want = T.TOPICS.get(k, {}).get("rate_hz")
            rules = []
            if s["last_fields"] is not None:
                rules = quality.check(k, s["last_fields"], now=now,
                                      meta={"hz": hz if hz >= 0 else None, "want_hz": want, "prev_step": None})
            vd = quality.verdict(rules) if rules else "-"
            # 🚌 Statistics 窗口口径: 抖动(相邻间隔标准差) / 丢包估算 / 载荷
            iv = [round((b - a) * 1000.0, 2) for a, b in zip(h, h[1:])]
            jit = round(float(np_std(iv)), 2) if len(iv) > 1 else None
            exp = (want or 0) * elapsed
            loss = round(max(0.0, 1.0 - s["count"] / exp) * 100.0, 1) if exp > 5 else None
            rows[k] = {
                "topic": T.full_name(k), "type": T.TOPICS.get(k, {}).get("type"),
                "qos": T.TOPICS.get(k, {}).get("qos"), "allowed": _allowed,
                "hz": hz, "hz_design": want, "count": s["count"], "matched_pubs": matched,
                "jitter_ms": jit, "loss_pct": loss, "bytes": self.tr_bytes.get(k, 0),
                "age_s": (round(now - s["last_ts"], 2) if s["last_ts"] else None),
                "verdict": vd, "score": quality.score(rules),
                "rules": rules, "fields": s["last_fields"],
            }
            # 🚦 状态灯(绿正常/红故障/黄报警/黑无信号) —— 口径在 lamps.py, UI 不许自己另判
            try:
                from lerobot.dataspace import lamps as L
                st, why = L.topic_state(k, rows[k], rows[k].get("hz_design"), _allowed, now=now)
                rows[k]["lamp"], rows[k]["lamp_reason"] = st, why
            except Exception:                                                    # noqa: BLE001
                rows[k]["lamp"], rows[k]["lamp_reason"] = "-", ""
        lamp_tally = {}
        try:
            from lerobot.dataspace import lamps as L2
            lamp_tally = L2.tally([r.get("lamp", "-") for r in rows.values() if r.get("lamp") != "-"])
        except Exception:                                                        # noqa: BLE001
            pass
        return {
            "ts": now, "mode": self.mode, "mode_desc": T.MODE_DESC.get(self.mode, ""),
            "lamp_tally": lamp_tally,
            "n_topics_allowed": len(self.keys), "n_topics_registered": len(T.TOPICS),
            "n_topic_alive": sum(1 for r in rows.values() if r["count"]),
            "rule_defs": len(T.QUALITY_RULES), "registry_version": T.VERSION,
            "topics": rows,
            "loop": [{"id": s["id"], "name": s["name"], "gate": s["gate"]} for s in T.CLOSED_LOOP],
        }

    def write(self, snap):
        os.makedirs(os.path.dirname(self.out), exist_ok=True)
        # 🚌 Trace 窗口(CANoe 报文追踪): 单独落一份, UI 只读它, 便于暂停/导出
        try:
            tp = self.out.replace("live.json", "trace.jsonl")
            with open(tp + ".tmp", "w", encoding="utf-8") as f:
                for r in self.trace[-600:]:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tp + ".tmp", tp)
        except Exception:                                                    # noqa: BLE001
            pass
        tmp = self.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.out)
        return self.out

    def print_table(self, snap):
        print("=" * 96)
        print("📡 全局数据空间 · 全链路 topic 可视化   mode=%s(%s) · 允许 %d / 注册 %d 话题 · 注册表 v%s"
              % (snap["mode"], snap["mode_desc"][:28], snap["n_topics_allowed"],
                 snap["n_topics_registered"], snap["registry_version"]))
        print("=" * 96)
        print("%-14s %-13s %8s %8s %8s %7s %6s %-6s %s" %
              ("topic", "type", "实测Hz", "设计Hz", "帧龄s", "条数", "配对", "裁决", "质量"))
        for k, r in sorted(snap["topics"].items()):
            bad = [x["rule"] for x in r["rules"] if not x["ok"]]
            print("zmax/%-9s %-13s %8s %8s %8s %7d %6s %-6s %s" %
                  (k, (r["type"] or "").split("::")[-1], r["hz"], r["hz_design"],
                   r["age_s"] if r["age_s"] is not None else "-", r["count"], r.get("matched_pubs"),
                   r["verdict"], ("%s %s" % ({"green": "🟢", "yellow": "🟡", "red": "🔴",
                                              "black": "⚫"}.get(r.get("lamp", ""), "·"),
                                             r.get("lamp_reason", "")[:34])) if not bad else ("⚠ " + ",".join(bad))))
        if not self.keys:
            print("  (mode=prod: 量产零开销, 不建参与者 —— 想看话题请切 diag/calib/test)")
        print("-" * 96)
        for s in T.CLOSED_LOOP:
            print("  %-3s %-12s 门: %s" % (s["id"], s["name"], s["gate"][:70]))


def main():
    ap = argparse.ArgumentParser(description="全局数据空间探针(全链路 topic 可视化)")
    ap.add_argument("--seconds", type=float, default=10.0, help="采集窗口秒数")
    ap.add_argument("--watch", action="store_true", help="常驻: 每 interval 秒刷新 JSON")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--mode", default=None, help="覆盖遥测模式(prod/diag/calib/test)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", action="store_true", help="只打 JSON")
    a = ap.parse_args()

    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)
    p = Probe(mode=a.mode, out=a.out)
    if a.mode and p.node is None and a.mode != "prod":
        print("⚠ 该模式不与守护口径一致或 DDS 不可用", file=sys.stderr)

    if a.watch:
        while not _STOP["v"]:
            p.pump(a.interval)
            snap = p.snapshot()
            p.write(snap)
            if not a.json:
                os.system("clear") if os.isatty(1) else None
                p.print_table(snap)
        return 0

    p.pump(a.seconds)
    snap = p.snapshot()
    p.write(snap)
    if a.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1))
    else:
        p.print_table(snap)
        print("\n落盘: %s" % p.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
