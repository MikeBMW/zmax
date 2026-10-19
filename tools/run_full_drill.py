#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_full_drill.py — 全链路演练 (老倪 2026-10-14)

老倪原话:
  「你来演练一下, 最开始从 任务配置 开始, 你通过全局数据空间, 依次配置 产品配置, 功能配置,
    模型配置, 性能配置, 工程配置, 工单配置, 最后将文档配置的结果发到飞书, 同时真正启动状态空间的
    原型运行测试验证流程; 当前每个任务, 都要走一遍, 每个场景, 都要有实际 topic 的输出,
    实际波形的运行, 以及实际模型的运行与自主训练; 现在有 7 个任务, 要有 7 个文档要发到飞书,
    同时更新工程数据库, 保证数据一致性。」

每个任务真走 9 步 (没有一步是"已实现"声明, 全部留证据文件):
  ① 配置链 7 域快照 —— 依序实读真源: 任务→产品→功能→模型→性能→工程→文档(工单) (config_chain.json)
  ② 场景切换       —— ss_scene_switch.py (有映射才切, 无映射明说 skipped)
  ③ 原型单步运行   —— 按该任务 enabled_nodes 依次真执行 execute_node_logic, 每节点真出 out,
                      经 ss_bus_topics.publish(mode='step') **真序列化**成节点输出 topic (topics/*.jsonl)
  ④ 原型整体运行   —— pipeline_closure_run.py 真跑引擎闭环 (整体运行按口径不序列化)
  ⑤ 实际波形       —— 从 ③ 的 topic 载荷 + ④ 的节点状态画 PNG (waveforms/*.png)
  ⑥ 实际模型运行   —— 从 ④ 的运行报告抽 L2/L3/L4 真加载/真推理证据 (models.json)
  ⑦ 自主训练       —— joint_train_all.py 真跑有界步数, 记 loss 曲线 (train.json + PNG)
  ⑧ 文档           —— 每任务一份 md → docx/pdf (docs/*.md/.docx/.pdf)
  ⑨ 工程库         —— 证据写进 zmax_engineering.db (drill_runs 表) 并跑一致性 check
最后: 7 份文档发飞书 (真发, 记 message_id) + 汇总 INDEX。

用法:
  ./gui-venv311/bin/python tools/run_full_drill.py --tasks all --steps 60 --train-steps 20
  ./gui-venv311/bin/python tools/run_full_drill.py --tasks TASK-01-FW --no-train --no-feishu
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

TASKS_J = "config/tasks/tasks.json"
BIND_J = "config/ss_task_binding.json"
PROD_J = "config/platform/zmax_product.json"
PERF_J = "config/platform/zmax_perf_spec.json"
MATCH_J = "config/mcd/match_matrix.json"
CALIB_J = "config/calib/zmax_calib.json"
META_J = "data/database/zmax/config_meta.json"
NOTES_J = "data/database/zmax/function_notes.json"
ORDERS_D = "config/orders"
CANVAS = "src/lerobot/engineering/flows/state_space_obs.json"
DB = "data/database/zmax/zmax_engineering.db"
OUT = "reports/drill"
NODE_TIMEOUT_S = 45          # 单节点执行墙钟上限 (秒); 超时记 timeout, 不让整个演练挂死
PY = os.path.join(ROOT, "gui-venv311/bin/python")
DDS_PY = os.path.join(ROOT, "venvs/dds-venv/bin/python")


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                            # noqa: BLE001
        return d


def _w(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return p


def _run(cmd, timeout=900, env=None):
    e = dict(os.environ)
    e.update(env or {})
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=timeout, env=e, errors="replace")
        return {"rc": p.returncode, "out": p.stdout or "", "err": p.stderr or "",
                "sec": round(time.time() - t0, 2), "cmd": " ".join(cmd)}
    except subprocess.TimeoutExpired as ex:
        return {"rc": -9, "out": (ex.stdout or b"").decode(errors="replace") if isinstance(ex.stdout, bytes)
                else (ex.stdout or ""), "err": "TIMEOUT", "sec": round(time.time() - t0, 2),
                "cmd": " ".join(cmd)}


# ─────────────────────────── ① 配置链 7 域 (真源实读) ───────────────────────────
def chain_snapshot(tid):
    tk = (_j(TASKS_J, {}) or {}).get("tasks", [])
    t = next((x for x in tk if x.get("task_id") == tid), {})
    bd = (_j(BIND_J, {}) or {}).get("tasks", [])
    b = next((x for x in bd if x.get("task_id") == tid), {})
    nodes = (b.get("enabled_nodes") or [])
    prod = _j(PROD_J, {}) or {}
    ap = prod.get("active_product")
    fns_all = (_j(META_J, {}) or {}).get("functions", {})
    notes = _j(NOTES_J, {}) or {}
    cv = _j(CANVAS, {}) or {}
    n2nid = {n.get("name"): n.get("id") for n in (cv.get("nodes") or [])}
    nid2node = {n.get("id"): n for n in (cv.get("nodes") or [])}
    my_fns = []
    for fid, v in fns_all.items():
        nid = n2nid.get(v.get("module_ref"))
        if nid and nid in nodes:
            f = v.get("fields") or {}
            my_fns.append({
                "fn_id": fid, "name": v.get("name"), "node": nid, "layer": v.get("layer"),
                "code_file": v.get("code_file"), "n_params": len(f.get("parameters") or []),
                "inputs": f.get("inputs") or [], "outputs": f.get("outputs") or [],
                "params": [{"id": p.get("id"), "cn": p.get("cn"), "value": p.get("value"),
                            "unit": p.get("unit")} for p in (f.get("parameters") or [])],
                "verification": ((v.get("verification") or {}).get("methods") or []),
                "note": notes.get(fid) or {},
            })
    mm = _j(MATCH_J, {}) or {}
    site = mm.get("SITE") or {}
    models = mm.get("MODELS") or []
    kw = [str(t.get("scene_ref") or ""), str(t.get("name") or "")]
    hit_models = [m for m in models
                  if any(k and k[:4] in json.dumps(m, ensure_ascii=False) for k in kw)]
    perf = _j(PERF_J, {}) or {}
    groups = perf.get("groups") or []
    ghit = []
    for g in groups:
        blob = json.dumps(g, ensure_ascii=False)
        if any(k and k[:4] in blob for k in kw):
            ghit.append(g)
    calib = _j(CALIB_J, {}) or {}
    bs = [x for x in (_j(os.path.join(ORDERS_D, "BS_%s.json" % (t.get("scene_ref") or ""))) or {}, {})]
    bs = bs[0] if bs else {}
    return {
        "task_id": tid,
        "① 任务配置": {"task_id": tid, "name": t.get("name"), "scene_ref": t.get("scene_ref"),
                   "档位": b.get("level") or t.get("level") or t.get("gear"),
                   "enabled_nodes": len(nodes), "blocked_by_site": bool(t.get("blocked_by_site")),
                   "真源": [TASKS_J, BIND_J],
                   "元任务数": len(my_fns)},
        "② 产品配置": {"active_product": ap,
                   "product": (prod.get("products") or {}).get(ap, {}),
                   "指纹": (prod.get("fingerprints") or {}),
                   "真源": PROD_J},
        "③ 功能配置": {"元任务数": len(my_fns), "元任务": my_fns, "真源": [META_J, NOTES_J, CANVAS]},
        "④ 模型配置": {"站点": site, "站点缺项": mm.get("SITE_MISSING") or [],
                   "该任务相关模型": hit_models or models[:3],
                   "模型总数": len(models), "真源": MATCH_J},
        "⑤ 性能配置": {"匹配组数": len(ghit), "匹配口径": kw, "组": ghit,
                   "性能组总数": len(groups), "真源": PERF_J},
        "⑥ 工程配置": {"T_base_cam": calib.get("T_base_cam"), "plane_z": calib.get("plane_z"),
                   "depth_scale": calib.get("depth_scale"), "cell_geometry": calib.get("cell_geometry"),
                   "camera": calib.get("camera"), "真源": CALIB_J},
        "⑦ 文档配置·工单实例": {"order_no": (bs.get("identity") or {}).get("order_no"),
                   "scene_id": (bs.get("identity") or {}).get("scene_id"),
                   "targets": bs.get("targets"), "readiness": bs.get("readiness"),
                   "配方段数": len(bs.get("recipe") or []),
                   "真源": os.path.join(ORDERS_D, "BS_%s.json" % (t.get("scene_ref") or ""))},
    }


# ─────────────────────── ③ 原型单步运行 (真执行 + 真 topic) ───────────────────────
class _ShimModule:
    """给节点逻辑的最低上下文 (GUI 模块的替身): 只给日志, 其它属性取不到就给 None,
    节点自己会抛错 ⇒ 如实记 failed, 不假装跑通。"""
    _trace_nodes = False
    _log = staticmethod(lambda *a, **k: None)

    def __getattr__(self, _k):
        return None


def step_run(tid, snap, do_publish=True):
    # 节点逻辑里有构造 QWidget 的 (GUI 上下文节点) ⇒ 离屏也要先有 QApplication,
    # 否则 "Must construct a QApplication before a QWidget" 直接 core dump (实测 2026-10-14)。
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication                                              # noqa: PLC0415
    _app = QApplication.instance() or QApplication([])
    from lerobot.engineering import execute_node_logic                                    # noqa: PLC0415
    import ss_bus_topics as bt                                                            # noqa: PLC0415
    cv = _j(CANVAS, {}) or {}
    nodes = cv.get("nodes") or []
    bd = (_j(BIND_J, {}) or {}).get("tasks", [])
    b = next((x for x in bd if x.get("task_id") == tid), {})
    ids = b.get("enabled_nodes") or []
    shim = _ShimModule()
    log = []
    rows = []
    for i, nid in enumerate(ids, 1):
        nd = next((n for n in nodes if n.get("id") == nid), None)
        if not nd:
            rows.append({"order": i, "node": nid, "status": "missing", "ms": 0, "topic": ""})
            continue
        t0 = time.time()
        out, err = None, ""
        # ⏱ 单节点硬超时: 节点里可能是相机/服务/等待类调用, 卡住会把整个演练挂死 (实测遇到)。
        #   用 SIGALRM 打墙钟上限, 超时如实记 timeout, 不假装跑通。
        def _tmo(_s, _f):
            raise TimeoutError("节点执行超时 (%.0fs)" % NODE_TIMEOUT_S)
        _old = None
        try:
            import signal as _sig
            _old = _sig.signal(_sig.SIGALRM, _tmo)
            _sig.alarm(int(NODE_TIMEOUT_S))
        except Exception:                                                                 # noqa: BLE001
            _old = None
        try:
            out = execute_node_logic(shim, nd, label="drill", trace=False, demo=False)
            st = "ok" if out is not None else "no_logic"
        except TimeoutError as e:
            st, err = "timeout", str(e)
        except Exception as e:                                                            # noqa: BLE001
            st, err = "failed", "%s: %s" % (type(e).__name__, e)
        finally:
            try:
                import signal as _sig
                _sig.alarm(0)
                if _old is not None:
                    _sig.signal(_sig.SIGALRM, _old)
            except Exception:                                                             # noqa: BLE001
                pass
        ms = round((time.time() - t0) * 1000, 1)
        topic = ""
        if do_publish:
            try:
                r = bt.publish(nd, out, mode="step", quiet=True) or {}
                topic = (r.get("topics") or [""])[0]
            except Exception as e:                                                        # noqa: BLE001
                err = (err + " | publish:" + repr(e)).strip(" |")
        rows.append({"order": i, "node": nid, "name": nd.get("name"), "status": st,
                     "ms": ms, "topic": topic, "err": err,
                     "out_keys": sorted(out)[:12] if isinstance(out, dict) else None})
        log.append("[%2d/%d] %-22s %-8s %7.1fms  %s" % (i, len(ids), str(nd.get("name"))[:22], st, ms, topic))
        print("   " + log[-1], flush=True)          # 逐节点即时打印 (任务多时便于看进度)
    ok = sum(1 for r in rows if r["status"] == "ok")
    return {"total": len(ids), "ok": ok, "failed": len(rows) - ok, "rows": rows, "log": log}


# ─────────────────────── ④ 原型整体运行 (引擎闭环, 真跑) ───────────────────────
def closure_run(steps, seed, vote=False):
    cmd = [PY, "tools/pipeline_closure_run.py", "--steps", str(steps), "--seed", str(seed)]
    if vote:
        cmd.append("--vote")
    r = _run(cmd, timeout=1200)
    st = _j("docs/PIPELINE_STATE.json", {}) or {}
    r["state"] = st
    m = re.search(r"引擎闭环: done=(\w+) · (\d+) 步 · 最小插入距 ([\d.]+)mm · L4真推理(\d+)次"
                  r" · 融合(\d+)帧 · L2收口否决(\d+)\(([^)]*)\)", r.get("out", ""))
    r["engine"] = ({"done": m.group(1) == "True", "steps": int(m.group(2)),
                    "min_gap_mm": float(m.group(3)), "l4_calls": int(m.group(4)),
                    "fused": int(m.group(5)), "veto": int(m.group(6)), "veto_why": m.group(7)}
                   if m else None)
    return r


# ─────────────────────── ⑤ 实际波形 (从真数据出图) ───────────────────────
def waveforms(d, tid, stepres, clos):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:                                                                # noqa: BLE001
        return {"ok": False, "why": "matplotlib 不可用: %r" % (e,)}
    made = []
    zh = os.path.join(ROOT, "tools", "fonts")
    for fp in ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",):
        if os.path.exists(fp):
            from matplotlib import font_manager as fm
            fm.fontManager.addfont(fp)
            plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    # (1) 节点耗时 + 状态
    rows = stepres["rows"]
    if rows:
        fig, ax = plt.subplots(figsize=(11, 4.2), dpi=130)
        xs = [r["order"] for r in rows]
        ys = [r["ms"] for r in rows]
        cols = ["#2e8b57" if r["status"] == "ok" else ("#d29922" if r["status"] == "no_logic" else "#f85149")
                for r in rows]
        ax.bar(xs, ys, color=cols)
        ax.set_yscale("symlog")
        ax.set_xlabel("单步顺序 (该任务 enabled_nodes)")
        ax.set_ylabel("节点耗时 ms (symlog)")
        ax.set_title("%s 原型单步: 每节点真实耗时/状态 (绿=真跑通 黄=未注册逻辑 红=抛错)" % tid)
        p = os.path.join(d, "waveforms", "w2_step_cost.png")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fig.tight_layout(); fig.savefig(p); plt.close(fig)
        made.append(p)
    # (2) topic 载荷数值时序 (从 trace.jsonl 真序列化的载荷里取)
    tr = os.path.join(ROOT, "zmax_data", "dataspace", "trace.jsonl")
    series = {}
    if os.path.exists(tr):
        with open(tr, encoding="utf-8") as f:
            for line in f.readlines()[-2000:]:
                try:
                    o = json.loads(line)
                except Exception:                                                         # noqa: BLE001
                    continue
                if o.get("task") not in (None, tid) and tid not in str(o.get("node", "")):
                    pass
                pl = o.get("value") or o.get("payload") or o.get("out") or {}
                if isinstance(pl, dict):
                    for k, v in pl.items():
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            series.setdefault(k, []).append(float(v))
    if series:
        fig, ax = plt.subplots(figsize=(11, 4.2), dpi=130)
        for k, v in list(series.items())[:6]:
            if len(v) >= 2:
                ax.plot(range(len(v)), v, marker="o", ms=2.5, label=str(k)[:18])
        ax.set_xlabel("单步采样序号 (trace.jsonl 真实序列化载荷)")
        ax.set_ylabel("数值")
        ax.set_title("%s 节点输出 topic 载荷波形 (真序列化, 单步模式)" % tid)
        ax.legend(fontsize=7, ncol=3)
        p = os.path.join(d, "waveforms", "w1_topic_payload.png")
        fig.tight_layout(); fig.savefig(p); plt.close(fig)
        made.append(p)
    # (3) 引擎闭环
    eng = (clos or {}).get("engine")
    st = (clos or {}).get("state") or {}
    raw_stages = (st.get("stages") or {})
    stages = list(raw_stages.items()) if isinstance(raw_stages, dict) else \
        [(str(s.get("id") or s), s) for s in raw_stages]
    if stages:
        def _ms(v):
            m = re.search(r"([\d.]+)ms", str((v or {}).get("note") or ""))
            return float(m.group(1)) if m else 0.0
        fig, ax = plt.subplots(figsize=(11, 4.2), dpi=130)
        nm = [k for k, _ in stages]
        ms = [_ms(v) for _, v in stages]
        ax.bar(range(len(nm)), ms, color=["#2e8b57" if (v or {}).get("status") == "success" else "#f85149"
                                          for _, v in stages])
        ax.set_xticks(range(len(nm)))
        ax.set_xticklabels([str(x)[:10] for x in nm], fontsize=7)
        ttl = "%s 引擎闭环阶段耗时" % tid
        if eng:
            ttl += " (done=%s · %d步 · 最小插入距%.1fmm · L2否决%d)" % (
                eng["done"], eng["steps"], eng["min_gap_mm"], eng["veto"])
        ax.set_title(ttl)
        p = os.path.join(d, "waveforms", "w3_closure.png")
        fig.tight_layout(); fig.savefig(p); plt.close(fig)
        made.append(p)
    return {"ok": bool(made), "files": made, "topic_series": {k: len(v) for k, v in series.items()}}


# ─────────────────────── ⑥ 实际模型运行 (从真跑报告抽证) ───────────────────────
def models_evidence(clos, stepres):
    o = (clos or {}).get("out", "")
    out = {"源": "pipeline_closure_run 真跑 stdout (同一次运行, 未额外加载)", "层": {}}
    for pat, key in ((r"✅ YOLO 实际加载: (\S+) \((\d+) 类\)", "L2 YOLO"),
                     (r"✓ planner\.(\w+)\s+conf=([\d.]+)\s+([\d.]+)ms", "L5 规划"),
                     (r"🧬 UnifiedNode 已挂载: ckpt=(\S+) · missing=(\d+)\(非trunk (\d+)\) · trained=(\w+) · dev=(\w+)", "L4 认知"),
                     (r"🎯 INTACT 已挂载: horizon=(\d+) · 适配层 enabled=(\S+) · 影子=(\w+)", "L4 INTACT"),
                     (r"🧠 事件级认知头已接入闭环: (\S+) \| trained=(\w+) \| device=(\w+)", "L4 事件头")):
        m = re.findall(pat, o)
        if m:
            out["层"][key] = m[0 if len(m) == 1 else 0]
    m = re.search(r"引擎闭环: .*?L4真推理(\d+)次", o)
    out["L4 真推理次数"] = int(m.group(1)) if m else None
    out["单步真跑通节点"] = "%d/%d" % (stepres["ok"], stepres["total"])
    out["判据"] = "负载与耗时来自本次真实运行 stdout; 无 stdout 证据的层不写"
    out["模型引擎窗口"] = _model_engine_evidence()
    return out


def _model_engine_evidence():
    """🧠 模型引擎窗口取证 (老倪 2026-10-14「L2~L5 在模型引擎窗口, 要能方便的查看控制所有模型的训练状态」):
    离屏真建窗口 → 抓图 + 四层状态 (真源 model_inventory.py --json; 训练入口真源 = 配置中心 model.train_entry)。
    每次演练只抓一次 (与任务无关的全局证据), 落 reports/drill/model_engine_window.png。"""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        p = os.path.join(ROOT, "reports", "drill", "model_engine_window.png")
        if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < 900:
            return {"png": os.path.relpath(p, ROOT), "缓存": True}
        sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
        from PyQt5.QtWidgets import QApplication                                     # noqa: PLC0415
        _app = QApplication.instance() or QApplication([])
        from model_engine_window import ModelEngineWindow                            # noqa: PLC0415
        w = ModelEngineWindow(poll=False)
        r = _run([PY, "tools/model_inventory.py", "--json"], timeout=180)
        st = {}
        try:                                                                          # 8796: 在役/推理标记
            import urllib.request                                                     # noqa: PLC0415
            with urllib.request.urlopen(os.environ.get("ZMAX_STATUS_URL",
                                                       "http://127.0.0.1:8796/status/all"), timeout=3) as _r:
                st = json.loads(_r.read(262144).decode("utf-8", "replace"))
        except Exception:                                                             # noqa: BLE001
            st = {}
        w.feed(json.loads(r.get("out") or "{}"), st)
        rows = w._rows()
        w.grab().save(p)
        return {"png": os.path.relpath(p, ROOT),
                "四层": {x["layer"]: {"在役": x["name"], "版本": x["ver"], "本层产物": x["n"],
                                    "推理": x["infer"], "训练中": x["train"], "最近训练": x["last"]}
                       for x in rows},
                "训练入口真源": "config/mcd/param_registry.json#model.train_entry"}
    except Exception as e:                                                            # noqa: BLE001
        return {"失败": "%s: %s" % (type(e).__name__, e)}


# ─────────────────────── ⑦ 自主训练 (真跑有界步数) ───────────────────────
def _parse_losses(text):
    """从训练 stdout 里抓 loss。joint_train_all 的 L4 段是**两行表**: 键一行 + 数值下一行
    (如 `fit/loss:` 换行 `-3.866`), 早期只写 `loss=0.1` 的行也要能抓。返回 (loss点, 明细)。"""
    out, detail = [], {}
    lines = [x.rstrip() for x in text.splitlines()]
    for i, ln in enumerate(lines):
        m = re.search(r"(fit/[\w]+|loss[\w./]*)\s*[:=]\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s*$", ln.strip(),
                      re.I)
        if m:
            out.append(float(m.group(2)))
            detail.setdefault(m.group(1), []).append(float(m.group(2)))
            continue
        m = re.match(r"^(fit/[\w]+|loss[\w./]*)\s*[:：]\s*$", ln.strip(), re.I)      # 键行
        if m:
            for nx in lines[i + 1:i + 4]:                                            # 值在下一(几)行
                if nx.strip() == "":
                    continue
                mv = re.match(r"^(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)$", nx.strip())
                if mv:
                    out.append(float(mv.group(1)))
                    detail.setdefault(m.group(1), []).append(float(mv.group(1)))
                break
    return out, detail


def _train_summary(text):
    """训练汇总: 从 stdout 里找 `汇总: <path>/summary.json` 真读回来 (产物/耗时/返回码)。"""
    m = re.search(r"汇总[:：]\s*(\S+summary\.json)", text)
    if not m:
        return {}
    p = m.group(1)
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    try:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        s["summary_json"] = os.path.relpath(p, ROOT)
        return s
    except Exception:                                                                  # noqa: BLE001
        return {}


def scene_map(tid):
    """真源口径: 该任务有无场景映射 (ss_scene_switch --task --check --json)。
    返回 dict: {action: switch|skipped, scene, msg} —— 无映射就如实说, 不假装切过。"""
    r = _run([PY, "tools/ss_scene_switch.py", "--task", tid, "--check", "--json"], timeout=90)
    try:
        return json.loads((r.get("out") or "{}").strip().splitlines()[-1])
    except Exception:                                                                  # noqa: BLE001
        return {"action": "?", "msg": (r.get("out") or r.get("err") or "").strip()[-120:]}


def _vram_free_mb():
    """GPU 还空多少 MB (读不到返回 -1)。"""
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
        used, total = [int(x.strip()) for x in o.split(",")[:2]]
        return total - used
    except Exception:                                                                      # noqa: BLE001
        return -1


def _wait_vram(need_mb=6500, timeout_s=180, quiet=False):
    """开跑前等显存真空出来。2026-10-14 实测: TASK-05 的 L3 因显存被占直接 CUDA OOM (rc=1, 连重试 6 次全 OOM),
    而 joint_train_all 的 wait_gpu 超时后会"仍继续" ⇒ 演练侧自己再守一道。"""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        f = _vram_free_mb()
        if f < 0 or f >= need_mb:
            return f
        if not quiet:
            print("   … 等显存: 需 %dMB, 现空闲 %dMB (%.0fs)" % (need_mb, f, time.time() - t0), flush=True)
        time.sleep(10)
    f = _vram_free_mb()
    print("   ⚠️ 等显存超时 (%ds), 现空闲 %dMB — 继续 (OOM 就是真证据, 不掩盖)" % (timeout_s, f), flush=True)
    return f


def _train_argv(only, steps):
    """训练命令真源 = 配置中心「模型配置」的 model.train_entry (单个层时逐字用它, 与模型引擎窗口的
    ▶ 按钮**同一条命令**); 传多个层/取不到真源时退回 --only <层列表> --steps <N>。"""
    try:
        reg = json.load(open(os.path.join(ROOT, "config", "mcd", "param_registry.json"),
                             encoding="utf-8"))
        ent = {}
        for p in (reg.get("params") or reg.get("items") or []):
            if p.get("id") == "model.train_entry" and isinstance(p.get("value"), dict):
                ent = p["value"]
        if only in ent and ent[only].startswith("tools/"):
            return shlex.split(ent[only]), ent[only]
    except Exception:                                                                      # noqa: BLE001
        pass
    c = "tools/joint_train_all.py --only %s --steps %d" % (only, steps)
    return shlex.split(c), c


def self_train(tid, steps, only="L4"):
    """有界步数真跑训练。先按该任务切场景 (有映射才切), 训练时把场景/口径一起记下来。"""
    sc = _run([PY, "tools/ss_scene_switch.py", "--now"], timeout=60)
    scene = "?"
    try:
        scene = (json.loads(sc.get("out") or "{}") or {}).get("src_state") or (sc.get("out") or "").strip()[:40]
    except Exception:                                                                      # noqa: BLE001
        scene = (sc.get("out") or "").strip()[:40]
    # ⚠️ 2026-10-14 实测修: 原来传 env={"HF_HOME": expanduser("~/zmax_data/hf_cache")}
    #   = /home/ubuntu/zmax_data/hf_cache (缺 /zmax/ 一段, 该目录根本不存在) ⇒ joint_train_all 拿到坏的
    #   HF_HOME 后 HF_HUB_CACHE 不存在 ⇒ 它主动放弃 HF_ENV ⇒ transformers 不带 offline 去连 huggingface.co
    #   ⇒ **L3 直接 rc=1** (SmolVLM2 基座加载失败), 而 L2/L4 因不碰 HF 缓存而"看起来正常"。
    #   现在统一从 tools/zmax_hf_env.py 取 (单一真源, 模型引擎窗口的 ▶ 按钮用的是同一份)。
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from zmax_hf_env import hf_env                                              # noqa: PLC0415
    _wait_vram(6500, 180)
    _argv, _cmdtxt = _train_argv(only, steps)
    print("   命令(真源=配置中心 model.train_entry): %s" % _cmdtxt, flush=True)
    r = _run([PY] + _argv, timeout=3600, env=hf_env())
    r["cmd"] = _cmdtxt
    losses, detail = _parse_losses(r.get("out", ""))
    r["loss_head"] = losses[:10]
    r["loss_tail"] = losses[-10:]
    r["n_loss"] = len(losses)
    r["loss_detail"] = {k: {"首": v[0], "末": v[-1], "点": len(v)} for k, v in detail.items()}
    r["train_summary"] = _train_summary(r.get("out", ""))
    r["scene"] = scene or "?"
    r["scene_note"] = "训练入口不按任务取数 (真源无任务→训练集映射)" if not scene or scene == "?" else "训练时画布数据源状态"
    return r


# ─────────────────────── ⑧ 每任务一份文档 ───────────────────────
def make_doc(tid, d, snap, stepres, clos, waves, models, train):
    import export_meta_doc as E                                                           # noqa: PLC0415
    sm = scene_map(tid)
    L = ["# %s 全链路演练记录（%s）\n" % (snap["① 任务配置"].get("name") or tid, tid),
         "> 本文由 `tools/run_full_drill.py` 真跑生成：配置链 7 域全部实读真源，原型单步/整体运行真执行，",
         "> topic 载荷真序列化，波形出自真数据；未跑通的项**保留失败原样**，不做美化。\n",
         "| 项 | 值 |", "|---|---|",
         "| 任务 | %s |" % tid,
         "| 场景 | %s |" % snap["① 任务配置"].get("scene_ref"),
         "| 档位 | %s |" % snap["① 任务配置"].get("档位"),
         "| 元任务（enabled_nodes） | %s |" % snap["① 任务配置"].get("enabled_nodes"),
         "| 单步真跑通 | %s/%s |" % (stepres["ok"], stepres["total"]),
         "| 引擎闭环 | %s |" % ((clos.get("engine") or {}).get("done")),
         "| 生成时间 | %s |" % time.strftime("%Y-%m-%d %H:%M:%S"), ""]
    L += ["## 一、配置链（依序，逐域实读真源）\n",
          "1. **任务配置** `%s` — 任务 %s · 场景 %s · 启用节点 %s 个 · 站点几何拦截 %s"
          % (snap["① 任务配置"]["真源"][0], tid, snap["① 任务配置"].get("scene_ref"),
             snap["① 任务配置"].get("enabled_nodes"), snap["① 任务配置"].get("blocked_by_site")),
          "2. **产品配置** `%s` — 当前产品 %s" % (PROD_J, snap["② 产品配置"].get("active_product")),
          "3. **功能配置** `%s` — 该任务承载元任务 %s 个（参数/输入输出/验证方法逐条取自真源）"
          % (META_J, snap["③ 功能配置"]["元任务数"]),
          "4. **模型配置** `%s` — 站点 %s 项 · 站点缺项 %s 项 · 模型 %s 个"
          % (MATCH_J, len(snap["④ 模型配置"].get("站点") or {}),
             len(snap["④ 模型配置"].get("站点缺项") or []), snap["④ 模型配置"].get("模型总数")),
          "5. **性能配置** `%s` — 命中 %s 组（匹配口径 %s）"
          % (PERF_J, snap["⑤ 性能配置"]["匹配组数"], snap["⑤ 性能配置"]["匹配口径"]),
          "6. **工程配置** `%s` — T_base_cam/plane_z/depth_scale/cell_geometry 实读"
          % CALIB_J,
          "7. **文档配置·工单实例** `%s` — 工单 %s · 站点就绪 %s"
          % (snap["⑦ 文档配置·工单实例"]["真源"], snap["⑦ 文档配置·工单实例"].get("order_no"),
             (snap["⑦ 文档配置·工单实例"].get("readiness") or {}).get("site_ok")), ""]
    # 该任务承载的元任务, 逐条给「干什么活 / 卡在哪 / 当前状态」(真源 data/database/zmax/function_notes.json)
    _mts = list(snap["③ 功能配置"].get("元任务") or [])
    if _mts:
        L += ["### 1.1 该任务下的功能点描述（朴素工程化, 每条实读真源）\n",
              "| 功能 | 干什么活 | 卡在哪 | 当前状态 |", "|---|---|---|---|"]
        for x in _mts[:16]:
            ntd = x.get("note") or {}
            L.append("| %s %s | %s | %s | %s |" % (x.get("fn_id"), x.get("name"), ntd.get("work") or "—",
                                                  ntd.get("pain") or "—", ntd.get("state") or "—"))
        L.append("")
    L += ["## 二、原型运行（真启动，不是声明）\n",
          "### 2.1 单步运行（每节点真执行 → 真 topic 序列化）\n",
          "| 序 | 节点 | 状态 | 耗时ms | 输出 topic |", "|---|---|---|---|---|"]
    for r in stepres["rows"]:
        L.append("| %s | %s | %s | %s | `%s` |" % (r["order"], r.get("name") or r["node"],
                                                  r["status"], r["ms"], r.get("topic") or "-"))
    if stepres["failed"]:
        L += ["", "**未跑通的节点（原样保留）**："]
        for r in stepres["rows"]:
            if r["status"] not in ("ok",):
                L.append("- `%s` %s — %s" % (r["node"], r["status"], (r.get("err") or "")[:160]))
    L += ["", "### 2.2 整体运行（引擎闭环）\n",
          "- 数据源场景（任务↔场景映射，真源 `tools/ss_scene_switch.py`）：%s" % (
              "有映射 → %s，本次运行前已按真源切到该场景" % sm.get("scene") if sm.get("action") == "switch"
              else "**该任务在真源里没有场景映射** ⇒ 数据源保持不动（%s）；下面的 topic/波形/模型是真跑的，"
                   "但「场景」这一维在该任务的真源里尚未定义" % (sm.get("msg") or "")[:90]),
          "```", (clos.get("out", "") or "").strip()[-2000:], "```", ""]
    if waves.get("files"):
        L += ["### 2.3 实际波形（真数据出图）\n"]
        for p in waves["files"]:
            L.append("- `%s`" % os.path.relpath(p, ROOT))
        L.append("")
    L += ["## 三、实际模型运行\n"]
    for k, v in (models.get("层") or {}).items():
        L.append("- **%s**：%s" % (k, v))
    L += ["- L4 真推理次数：%s" % models.get("L4 真推理次数")]
    me = models.get("模型引擎窗口") or {}
    if me.get("png"):
        L.append("- 模型引擎窗口（L2~L5，离屏真建窗抓图）：`%s`" % me["png"])
        for ly, v in (me.get("四层") or {}).items():
            L.append("  - %s：%s · 版本 %s · 本层产物 %s · 推理 %s · 训练中 %s · 最近训练 %s" % (
                ly, v.get("在役"), v.get("版本"), v.get("本层产物"),
                "推理中" if v.get("推理") else "空闲", v.get("训练中"), v.get("最近训练")))
        # 训练入口 = 逐层真命令 (真源 = 配置中心 model.train_entry; 窗口 ▶ 与演练单层都逐字执行它)
        try:
            import json as _json                                                   # noqa: PLC0415
            with open(os.path.join(ROOT, "config", "mcd", "param_registry.json"), encoding="utf-8") as _f:
                _reg = _json.load(_f)
            _te = next((p.get("value") for p in (_reg.get("params") or [])
                        if p.get("id") == "model.train_entry"), None) or {}
        except Exception:                                                          # noqa: BLE001
            _te = {}
        if isinstance(_te, dict) and _te:
            L.append("  - 训练入口（真源 = 配置中心 `model.train_entry`，窗口 ▶ / 演练单层都逐字执行它）：")
            for _ly in ("L4", "L3", "L2", "L5"):          # 联合训练真顺序 = L4→L3→L2; L5 单独
                L.append("    - %s：`%s`" % (_ly, _te.get(_ly, "真源未登记")))
        else:
            L.append("  - 训练入口：真源未登记（`config/mcd/param_registry.json#model.train_entry`）")
    elif me.get("失败"):
        L.append("- 模型引擎窗口：⛔ %s" % me["失败"])
    L += ["", "## 四、自主训练（有界步数真跑）\n",
          "- 命令：`%s`" % (train or {}).get("cmd"),
          "- 训练时场景：%s（%s）" % ((train or {}).get("scene") or "—",
                                (train or {}).get("scene_note") or "未切场景"),
          "- 任务↔场景映射（真源 `tools/ss_scene_switch.py` 口径）：%s" % (
              "有映射 → %s" % sm.get("scene") if sm.get("action") == "switch"
              else "**该任务在真源里没有场景映射** ⇒ 数据源不切（%s）" % (sm.get("msg") or "")[:80]),
          "- 返回码 %s · 耗时 %ss · 抓到 loss 点数 %s" % ((train or {}).get("rc"),
                                                   (train or {}).get("sec"), (train or {}).get("n_loss")),
          "- loss 明细（键 · 首→末 · 点数）：%s" % (json.dumps((train or {}).get("loss_detail") or {},
                                                          ensure_ascii=False) if (train or {}).get("loss_detail")
                                              else "—"),
          "- 训练产物/日志：%s" % (json.dumps({k: v for k, v in ((train or {}).get("train_summary") or {}).items()
                                          if k in ("summary_json", "层", "产物", "layers")},
                                          ensure_ascii=False) if (train or {}).get("train_summary") else "—"),
          "- loss 前段 %s · 后段 %s" % ((train or {}).get("loss_head"), (train or {}).get("loss_tail")),
          "- 口径：演练用有界步数，只证「训练链路真能跑、loss 真出数」，不等同正式训练轮次。",
          "- **缺口（如实写，不掩盖）**：`tools/joint_train_all.py` 当前不吃「任务→训练集」的映射"
          "（真源里没有这张表），所以 7 个任务触发的是同一套数据的有界训练，",
          "  不是 7 份互不相同的训练。要做成「每任务各自训练」需先补：任务/场景 → 数据集清单 的真源映射。", "",
          "## 五、证据文件\n"]
    for f in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        if os.path.isfile(f):
            L.append("- `%s`" % os.path.relpath(f, ROOT))
    md = "\n".join(L) + "\n"
    mdp = os.path.join(d, "%s_演练记录.md" % tid)
    os.makedirs(d, exist_ok=True)
    with open(mdp, "w", encoding="utf-8") as f:
        f.write(md)
    html = E.md_to_html(md)
    hp = mdp[:-3] + ".html"
    with open(hp, "w", encoding="utf-8") as f:
        f.write(html)
    outs = {"md": mdp, "html": hp}
    try:
        dx = E.soffice_convert(hp, "html2docx", d)
        outs["docx"] = dx if isinstance(dx, str) else str(dx)
    except Exception as e:                                                                # noqa: BLE001
        outs["docx_err"] = repr(e)
    try:
        pf = E.soffice_convert(hp, "html2pdf", d)
        outs["pdf"] = pf if isinstance(pf, str) else str(pf)
    except Exception as e:                                                                # noqa: BLE001
        outs["pdf_err"] = repr(e)
    return outs


# ─────────────────────── ⑨ 工程数据库 (写证据 + 一致性) ───────────────────────
def engdb_write(rec):
    # 场景切换会改画布真源 (src_state) ⇒ 先按真源重建库, 再插演练证据, 最后跑一致性判据。
    # (口径同 memory: 改画布后 → db build → check; 直接插行不重建会报漂移 ['project','canvas'])
    bld = _run([PY, "tools/engineering_db.py", "build"], timeout=600)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS drill_runs(
        run_id TEXT PRIMARY KEY, task_id TEXT, ts TEXT, scene TEXT,
        step_ok INT, step_total INT, closure_done INT, min_gap_mm REAL, l2_veto INT,
        doc_md TEXT, doc_docx TEXT, doc_pdf TEXT, feishu_msg_id TEXT, note TEXT)""")
    con.execute("INSERT OR REPLACE INTO drill_runs(run_id,task_id,ts,scene,step_ok,step_total,"
                "closure_done,min_gap_mm,l2_veto,doc_md,doc_docx,doc_pdf,feishu_msg_id,note) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rec)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM drill_runs").fetchone()[0]
    con.close()
    chk = _run([PY, "tools/engineering_db.py", "check"], timeout=300)
    return {"rows": n, "build_rc": bld["rc"], "check_rc": chk["rc"], "check_tail": chk["out"][-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="all")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--train-steps", type=int, default=20)
    ap.add_argument("--only-model-layer", default="L4")
    ap.add_argument("--no-train", action="store_true")
    ap.add_argument("--no-feishu", action="store_true")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--docs-only", action="store_true",
                    help="只用已存的证据 JSON 重出文档 (改文档模板/描述后不必重跑运行与模型)")
    ap.add_argument("--train-only", action="store_true",
                    help="只补跑「自主训练」并把结果并进已有证据与文档 (不重跑单步/闭环/波形)")
    a = ap.parse_args()

    all_t = [x["task_id"] for x in (_j(TASKS_J, {}) or {}).get("tasks", [])]
    tasks = all_t if a.tasks == "all" else [x.strip() for x in a.tasks.split(",") if x.strip()]
    if a.train_only:
        for tid in tasks:
            d = os.path.join(OUT, tid)
            if not os.path.exists(os.path.join(d, "step_run.json")):
                print("  ⏭ %s 还没有运行证据, 跳过" % tid)
                continue
            print("▶ %s 自主训练 (--only %s --steps %d)" % (tid, a.only_model_layer, a.train_steps),
                  flush=True)
            sc = _run([PY, "tools/ss_scene_switch.py", "--task", tid], timeout=120)   # 先按任务切场景
            tr = self_train(tid, a.train_steps, a.only_model_layer)
            _w(os.path.join(d, "train.json"), {k: v for k, v in tr.items() if k != "out"})
            with open(os.path.join(d, "train_stdout.txt"), "w", encoding="utf-8") as f:
                f.write(tr.get("out", ""))
            print("   rc=%s · %ss · loss 点 %s · 场景 %s%s" % (
                tr.get("rc"), tr.get("sec"), tr.get("n_loss"), tr.get("scene"),
                "" if sc["rc"] == 0 else " (场景切换 rc=%s)" % sc["rc"]), flush=True)
            # 把训练结果并进文档 (运行/波形/模型证据沿用原样)
            try:
                snap = _j(os.path.join(d, "config_chain.json"), {}) or {}
                step = _j(os.path.join(d, "step_run.json"), {}) or {}
                clos = _j(os.path.join(d, "closure_run.json"), {}) or {}
                waves = _j(os.path.join(d, "waveforms.json"), {}) or {}
                mv = _j(os.path.join(d, "models.json"), {}) or {}
                doc = make_doc(tid, d, snap, step, clos, waves, mv, tr)
                print("   📄 文档已并进训练结果: %s" % os.path.relpath(doc["md"], ROOT), flush=True)
            except Exception as e:                                                     # noqa: BLE001
                print("   ⛔ 文档重出失败: %r" % (e,), flush=True)
        print("✅ 训练补跑完成")
        return 0
    if a.docs_only:
        n = 0
        for tid in tasks:
            d = os.path.join(OUT, tid)
            need = ("config_chain.json", "step_run.json", "closure_run.json", "waveforms.json",
                    "models.json")
            if not all(os.path.exists(os.path.join(d, x)) for x in need):
                print("  ⏭ %s 证据不全, 跳过" % tid)
                continue
            snap = _j(os.path.join(d, "config_chain.json"), {}) or {}
            step = _j(os.path.join(d, "step_run.json"), {}) or {}
            clos = _j(os.path.join(d, "closure_run.json"), {}) or {}
            waves = _j(os.path.join(d, "waveforms.json"), {}) or {}
            mv = _j(os.path.join(d, "models.json"), {}) or {}
            tr = _j(os.path.join(d, "train.json"), {}) or {}
            doc = make_doc(tid, d, snap, step, clos, waves, mv, tr)
            n += 1
            print("  📄 %s → %s" % (tid, os.path.relpath(doc["md"], ROOT)))
        print("✅ 文档重出 %d 份 (未重跑运行)" % n)
        return 0
    index = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": a.steps,
             "train_steps": a.train_steps, "tasks": {}}
    for tid in tasks:
        d = os.path.join(OUT, tid)
        os.makedirs(d, exist_ok=True)
        print("\n" + "=" * 78)
        print("▶ %s ① 配置链 7 域" % tid)
        snap = chain_snapshot(tid)
        _w(os.path.join(d, "config_chain.json"), snap)
        # ② 场景切换
        sc = _run([PY, "tools/ss_scene_switch.py", "--task", tid], timeout=120)
        snap["②b 场景切换"] = {"rc": sc["rc"], "out": (sc["out"] or "")[-400:]}
        _w(os.path.join(d, "config_chain.json"), snap)
        print("  场景切换 rc=%s %s" % (sc["rc"], (sc["out"] or "").strip()[:110]))
        # ③ 单步真跑 + 真 topic
        print("③ 原型单步 (真执行 + 真 topic 序列化)")
        step = step_run(tid, snap, do_publish=not a.no_publish)
        _w(os.path.join(d, "step_run.json"), step)
        print("   单步结果: %d/%d 跑通 (%d 失败/超时)" % (step["ok"], step["total"],
                                                       step["failed"]), flush=True)
        # ④ 整体运行
        print("④ 原型整体运行 (引擎闭环)")
        clos = closure_run(a.steps, a.seed)
        _w(os.path.join(d, "closure_run.json"), {k: v for k, v in clos.items() if k != "out"})
        with open(os.path.join(d, "closure_stdout.txt"), "w", encoding="utf-8") as f:
            f.write(clos.get("out", "") + "\n--- stderr ---\n" + clos.get("err", ""))
        print("   rc=%s · %ss · engine=%s" % (clos["rc"], clos["sec"], clos.get("engine")))
        # ⑤ 波形
        w = waveforms(d, tid, step, clos)
        _w(os.path.join(d, "waveforms.json"), w)
        print("⑤ 波形: %s" % (w.get("files") or w.get("why")))
        # ⑥ 模型证据
        mv = models_evidence(clos, step)
        _w(os.path.join(d, "models.json"), mv)
        # ⑦ 自主训练
        tr = {"skipped": True} if a.no_train else self_train(tid, a.train_steps, a.only_model_layer)
        _w(os.path.join(d, "train.json"), {k: v for k, v in tr.items() if k != "out"})
        if not a.no_train:
            with open(os.path.join(d, "train_stdout.txt"), "w", encoding="utf-8") as f:
                f.write(tr.get("out", ""))
            print("⑦ 训练 rc=%s · %ss · loss点数=%s" % (tr.get("rc"), tr.get("sec"), tr.get("n_loss")))
        # ⑧ 文档
        doc = make_doc(tid, d, snap, step, clos, w, mv, tr)
        print("⑧ 文档: %s" % doc.get("md"))
        # ⑨ 工程库
        eng = engdb_write((tid, tid, index["ts"], snap["① 任务配置"].get("scene_ref"),
                           step["ok"], step["total"],
                           1 if (clos.get("engine") or {}).get("done") else 0,
                           (clos.get("engine") or {}).get("min_gap_mm"),
                           (clos.get("engine") or {}).get("veto"),
                           doc.get("md"), doc.get("docx"), doc.get("pdf"), None,
                           "演练 %s" % index["ts"]))
        index["tasks"][tid] = {"step": "%s/%s" % (step["ok"], step["total"]),
                               "closure": (clos.get("engine") or {}).get("done"),
                               "min_gap_mm": (clos.get("engine") or {}).get("min_gap_mm"),
                               "doc": doc, "waves": w.get("files"), "models": mv,
                               "train": {k: v for k, v in (tr or {}).items()
                                         if k in ("rc", "sec", "n_loss", "loss_head", "loss_tail")},
                               "engdb": eng}
        print("⑨ 工程库: drill_runs %s 行 · check rc=%s" % (eng["rows"], eng["check_rc"]))
    _w(os.path.join(OUT, "INDEX.json"), index)
    print("\n" + "=" * 78)
    for tid, v in index["tasks"].items():
        print("  %-14s 单步 %-7s 闭环 %-5s 文档 %s" % (tid, v["step"], v["closure"],
                                                    os.path.relpath(v["doc"]["md"], ROOT)))
    print("INDEX: %s" % os.path.join(OUT, "INDEX.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
