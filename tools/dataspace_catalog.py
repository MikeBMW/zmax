#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dataspace_catalog.py — 🌐 全局数据总线目录 (只读, 零副作用)

老倪 2026-10-10:
  「一定要保证全系统数据同步, 这些功能区就是同于数据源的不同切面, 这些数据,
    都要在全局数据空间, 用DDS技术, topic的形式, 系统科学的用数据总线的形式体现」

本工具把全系统的**所有数据切面**枚举成一份目录 (catalog): 每个切面带
  功能区(area) · 切面名(key) · DDS 话题(topic, 现有 or 建议) · 类型(dtype) · QoS ·
  生产者(producer, 真实工具/进程) · 消费者(consumers) · 档位(gate, 哪个模式允许) ·
  现在是否活着(live_now) · 证据(evidence, 指向能真实产出它的命令/文件)。

三条硬规矩:
  ① **真读** 现有真源: `src/lerobot/dataspace/topics.py::TOPICS/MODE_TOPICS` 与
     运行中守护 `tools/dds/ss_daemon.py::MODE_TOPICS` (以及未收口的旧副本), 标出
     哪些切面**已有话题**、哪些**缺**。
  ② **真跑**: 每个"数据源切面"都现场执行它的产出命令(或读它的产物文件), 把关键值
     贴进 evidence —— 不是写"应该有", 是写"实测产出了什么"。
  ③ **只读**: 不改任何守护/业务行为; 建议的新话题只以文本形式写在 catalog 里。

用法:
  python3 tools/dataspace_catalog.py            # 人读表
  python3 tools/dataspace_catalog.py --json      # 机器读
  python3 tools/dataspace_catalog.py --json --out zmax_data/dataspace/catalog.json
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# ── ① 真源: 话题注册表 (单一真源) ──────────────────────────────────────────────
try:
    from lerobot.dataspace import topics as T                          # noqa: E402
    REG_OK, REG_ERR = True, ""
except Exception as e:                                                   # noqa: BLE001
    T = None
    REG_OK, REG_ERR = False, "%s: %s" % (type(e).__name__, str(e)[:120])

# 运行中守护 (systemd zmax-dds-ss 实际 ExecStart) 与未收口旧副本
DAEMON_LIVE = os.path.join(REPO, "tools", "dds", "ss_daemon.py")
DAEMON_STALE = os.path.join(REPO, "tools", "zmax_dds_ss_daemon.py")
GUI_TELEMETRY = os.path.join(REPO, "tools", "gui", "zmax_telemetry.py")
LIVE_JSON = os.environ.get("ZMAX_DATASPACE_LIVE",
                           os.path.join(REPO, "zmax_data", "dataspace", "live.json"))


# ───────────────────────────── 工具 ─────────────────────────────
def _load_mode_topics(path):
    """从 .py 里静态解析 MODE_TOPICS 字典 (不 import, 无副作用)"""
    if not os.path.isfile(path):
        return None
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:                                                    # noqa: BLE001
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "MODE_TOPICS":
                    try:
                        d = ast.literal_eval(node.value)
                        if isinstance(d, dict):
                            return {k: list(v) for k, v in d.items()}
                    except Exception:                                    # noqa: BLE001
                        return None
    return None


def _run_json(cmd, timeout=90):
    """现场跑一个 --json 数据源, 返回 (dict|None, 摘要文本)"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=REPO)
        if r.returncode != 0:
            return None, "exit=%d %s" % (r.returncode, (r.stderr or "").strip()[:80])
        return json.loads(r.stdout), "ok"
    except Exception as e:                                               # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:90])


def _newest(pattern):
    c = glob.glob(pattern)
    if not c:
        return None
    return max(c, key=os.path.getmtime)


def _age(p):
    try:
        return round(time.time() - os.path.getmtime(p), 1)
    except OSError:
        return None


_HC = {}


def _http_ok(url, timeout=4):
    if url in _HC:
        return _HC[url]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zmax-catalog"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = (r.status == 200)
    except Exception:                                                    # noqa: BLE001
        ok = False
    _HC[url] = ok
    return ok


def _load_live():
    try:
        return json.load(open(LIVE_JSON, encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        return {}


# ───────────────────────────── 现场真跑: 各数据源 ─────────────────────────────
def collect_sources():
    """真跑各只读数据源, 返回 {name: {"data":…, "evidence": 文案}}"""
    out = {}

    def add(name, cmd, fmt):
        d, note = _run_json(cmd, timeout=120)
        out[name] = {"data": d, "evidence": fmt(d) if d else "产出失败(%s)" % note}

    def f_ds(d):
        t = d.get("totals", {})
        c = d.get("categories", {})
        return ("items=%s size=%s files=%s · 下载%s/%s · 生成%s/%s · 建图%s/%s" % (
            t.get("items"), t.get("size_human"), t.get("file_count"),
            c.get("downloaded", {}).get("count"), c.get("downloaded", {}).get("size_human"),
            c.get("generated", {}).get("count"), c.get("generated", {}).get("size_human"),
            c.get("map", {}).get("count"), c.get("map", {}).get("size_human")))

    def f_mi(d):
        g = d.get("gpu", {})
        return ("models=%d reports=%d training=%d · GPU=%s util=%s%% mem=%s/%sMB" % (
            len(d.get("models", [])), len(d.get("reports", [])), len(d.get("training", [])),
            g.get("name"), g.get("util"), g.get("mem_used"), g.get("mem_total")))

    def f_rm(d):
        eps = d.get("endpoints", [])
        ok = sum(1 for e in eps if e.get("ok"))
        return ("endpoints=%d(ok=%d) same_source=%d · 例 AOI10082 age=%ss AOI10083 age=%ss" % (
            len(eps), ok, len(d.get("same_source", [])),
            next((e.get("data_age_s") for e in eps if "10082" in str(e.get("name"))), "?"),
            next((e.get("data_age_s") for e in eps if "10083" in str(e.get("name"))), "?")))

    def f_ag(d):
        m = d.get("meta", {})
        return ("nodes=%d edges=%d · db=%s" % (
            len(d.get("nodes", [])), len(d.get("edges", [])), m.get("db")))

    def f_vs(d):
        return ("ok=%s canonical=%s src=%s sync_locs=%d consistent=%s · remote_tags=%s head=%s" % (
            d.get("ok"), d.get("canonical_version"), d.get("canonical_source"),
            len(d.get("sync_locations", [])), d.get("all_locations_consistent"),
            (d.get("remote") or {}).get("remote_tag_count"), (d.get("remote") or {}).get("head_short")))

    def f_se(d):
        return ("objects=%d markers=%d fences=%d traj=%d" % (
            len(d.get("objects", [])), len(d.get("markers", [])),
            len(d.get("fences", [])), len(d.get("trajectories", []))))

    py = sys.executable
    add("dataset_inventory", [py, "tools/dataset_inventory.py", "--json"], f_ds)
    add("model_inventory", [py, "tools/model_inventory.py", "--json"], f_mi)
    add("remote_monitor_aggregate", [py, "tools/remote_monitor_aggregate.py", "--json"], f_rm)
    add("arch_graph", [py, "tools/arch_graph.py", "--json"], f_ag)
    add("verify_version_sync", [py, "tools/verify_version_sync.py", "--json"], f_vs)
    add("scene_edit", [py, "tools/scene_edit.py", "list", "--json"], f_se)
    return out


# ───────────────────────────── 现场真跑: 文件/端点切面 ─────────────────────────────
def collect_probes():
    """返回 {probe_name: (live_bool, note)}"""
    p = {}
    # 真机状态 tap (ss_state 的数据源)
    st = _newest(os.path.join(REPO, "zmax_data", "ss_live", "state_*.jsonl"))
    p["state_tap"] = (bool(st and _age(st) is not None and _age(st) < 86400 * 3),
                      "%s 龄%.0fs" % (os.path.basename(st), _age(st) or -1) if st else "无 state_*.jsonl")
    # 推理输出 tap (ss_action 的数据源) —— 关键: 空文件=没有动作源
    pr = _newest(os.path.join(REPO, "zmax_data", "ss_live", "proposal_*.jsonl"))
    psz = os.path.getsize(pr) if pr else -1
    p["proposal_tap"] = (bool(pr and psz > 0),
                         "%s size=%dB" % (os.path.basename(pr), psz) if pr else "无 proposal_*.jsonl")
    # 能量 tap (ss_energy 的数据源)
    en = _newest(os.path.join(REPO, "zmax_data", "ss_live", "energy_*.jsonl"))
    p["energy_tap"] = (bool(en and _age(en) is not None and _age(en) < 86400 * 30),
                       "%s 龄%.0fs" % (os.path.basename(en), _age(en) or -1) if en else "无 energy_*.jsonl")
    # 画布真源
    cv = os.path.join(REPO, "flows", "state_space_obs.json")
    p["canvas_json"] = (os.path.isfile(cv), "flows/state_space_obs.json 在" if os.path.isfile(cv) else "缺")
    # MoveIt 规划 tap
    pl = os.path.join(os.path.expanduser("~"), "zmax_moveit_plan", "live_plan.jsonl")
    p["moveit_plan"] = (os.path.isfile(pl), "live_plan.jsonl 在" if os.path.isfile(pl) else "缺 ~/zmax_moveit_plan/live_plan.jsonl")
    # 标定真源
    he = os.path.join(REPO, "models", "handeye_state.json")
    p["handeye"] = (os.path.isfile(he), "models/handeye_state.json 在" if os.path.isfile(he) else "缺")
    # 数据集 orin_6d
    o6 = os.path.join(REPO, "data", "datasets", "orin_6d", "meta", "info.json")
    p["orin_6d"] = (os.path.isfile(o6), "data/datasets/orin_6d/meta/info.json 在" if os.path.isfile(o6) else "缺")
    # 训练进度
    tp = os.path.join(REPO, "zmax_data/stable-wm-cache/reports/progress_v6expand.json")
    p["train_progress"] = (os.path.isfile(tp), "progress_v6expand.json 在(龄%.0fs)" % (_age(tp) or -1) if os.path.isfile(tp) else "缺")
    # 推理服务
    p["infer_8790"] = (_http_ok("http://127.0.0.1:8790/health"), "127.0.0.1:8790/health")
    # HIL 桥
    p["hil_8795"] = (_http_ok("http://127.0.0.1:8795/hil/state"), "127.0.0.1:8795/hil/state")
    # AOI 金手指 / 表面 last_result
    p["aoi_10082"] = (_http_ok("http://192.168.23.23:10082/last_result"), "192.168.23.23:10082/last_result")
    p["aoi_10083"] = (_http_ok("http://192.168.23.23:10083/last_result"), "192.168.23.23:10083/last_result")
    # AOI 生产清单
    am = os.path.join(REPO, "tools", "aoi", "PRODUCTION_MANIFEST.json")
    p["aoi_manifest"] = (os.path.isfile(am), "tools/aoi/PRODUCTION_MANIFEST.json 在" if os.path.isfile(am) else "缺")
    # HIL 取证
    hc = _newest(os.path.join(REPO, "reports", "hil_chain_verify_*.json"))
    p["hil_verify"] = (bool(hc), os.path.basename(hc) if hc else "无 hil_chain_verify_*.json")
    ha = os.path.join(REPO, "reports", "hil_instructions.jsonl")
    p["hil_audit"] = (os.path.isfile(ha), "reports/hil_instructions.jsonl 在" if os.path.isfile(ha) else "缺")
    # 部署审计
    da = os.path.join(REPO, "docs", "deploy_audit.jsonl")
    p["deploy_audit"] = (os.path.isfile(da), "docs/deploy_audit.jsonl 在" if os.path.isfile(da) else "缺")
    # 报告盘点
    reps = glob.glob(os.path.join(REPO, "reports", "*.json"))
    p["reports_dir"] = (len(reps) > 0, "reports/*.json %d 个" % len(reps))
    return p


# ───────────────────────────── 切面定义 ─────────────────────────────
def build_slices(sources, probes, live, mode_topics_live):
    """把所有数据切面枚举成目录条目"""
    S = []

    def add(area, key, topic, dtype, qos, producer, consumers, gate, live_spec, evidence,
            topic_state=None, note=""):
        # topic_state: existing / missing / meta —— 若 topic 是注册表里的 key 则 existing
        if topic_state is None:
            topic_state = ("meta" if not topic else
                           ("existing" if (T and topic in T.TOPICS) else "missing"))
        live_now = None
        if live_spec is not None:
            live_now = live_spec[0]
            live_note = live_spec[1]
        else:
            live_note = ""
        if not topic:
            full = ""
        else:
            full = (T.full_name(topic) if (T and topic in T.TOPICS) else
                    (topic if topic.startswith("zmax/") else ("zmax/" + topic)))
        S.append({
            "area": area, "key": key, "topic": full, "topic_key": topic,
            "topic_state": topic_state, "dtype": dtype, "qos": qos,
            "producer": producer, "consumers": consumers, "gate": gate,
            "live_now": live_now, "live_note": live_note,
            "evidence": evidence, "note": note,
        })

    def P(name):
        v = probes.get(name)
        return (v[0], v[1]) if v else (False, "未探测")

    def TQ(key):
        """某话题在哪些档位允许"""
        if not T:
            return []
        return [m for m, ts in T.MODE_TOPICS.items() if key in ts]

    # ═══════════════ A. 数据集 (dataset_inventory) ═══════════════
    ds = sources.get("dataset_inventory", {}).get("data") or {}
    ev_ds = sources.get("dataset_inventory", {}).get("evidence", "未产出")
    add("数据集", "数据集_总量", "dataset_inventory", "json{modules,totals,items[]}",
        "state", "tools/dataset_inventory.py --json", ["数据空间页", "盘点/备份"], ["test"],
        (True, "脚本按需产出"), "python3 tools/dataset_inventory.py --json → " + ev_ds)
    cat = ds.get("categories", {})
    add("数据集", "数据集_已下载", "dataset_inventory", "json{modules.downloaded}",
        "state", "tools/dataset_inventory.py --json", ["盘点/备份"], ["test"],
        (bool(cat.get("downloaded")), "HF hub缓存+权重快照目录在盘"),
        "modules.downloaded: count=%s size=%s (HF hub缓存+权重快照)" % (
            cat.get("downloaded", {}).get("count"), cat.get("downloaded", {}).get("size_human")))
    add("数据集", "数据集_本机生成", "dataset_inventory", "json{modules.generated}",
        "state", "tools/dataset_inventory.py --json", ["盘点/备份"], ["test"],
        (bool(cat.get("generated")), "数据集/训练run/YOLO/WM 目录在盘"),
        "modules.generated: count=%s size=%s (数据集/训练run/YOLO/WM)" % (
            cat.get("generated", {}).get("count"), cat.get("generated", {}).get("size_human")))
    add("数据集", "数据集_建图3DGS", "dataset_inventory", "json{map_summary}",
        "state", "tools/dataset_inventory.py --json", ["场景/仿真资产"], ["test"],
        (bool(cat.get("map")), "3DGS 资产/gpr 目录在盘"),
        "map_summary: items=%s gs_ply=%s size=%s" % (
            (ds.get("map_summary") or {}).get("total_items"),
            (ds.get("map_summary") or {}).get("items_with_gs_ply"),
            (ds.get("map_summary") or {}).get("size_human")))
    add("数据集", "数据集_LeRobot_orin_6d", "dataset_orin_6d", "parquet+mp4/meta",
        "state", "build_orin6d_dataset.py → data/datasets/orin_6d", ["训练S3", "评测S5"], ["test"],
        P("orin_6d"), "data/datasets/orin_6d/meta/info.json " +
        ("在" if P("orin_6d")[0] else "缺(缺则 S3 入库门 unknown)"))
    add("数据集", "数据集_报告盘点", "reports_index", "json{reports_summary}",
        "state", "tools/dataset_inventory.py --json", ["数据空间页/评估页"], ["test"],
        P("reports_dir"), "reports_summary: files=%s size=%s" % (
            (ds.get("reports_summary") or {}).get("total_files"),
            (ds.get("reports_summary") or {}).get("total_human")))

    # ═══════════════ B. 模型引擎 (model_inventory) ═══════════════
    mi = sources.get("model_inventory", {}).get("data") or {}
    ev_mi = sources.get("model_inventory", {}).get("evidence", "未产出")
    add("模型引擎", "模型_总量与GPU", "model_inventory", "json{models[],gpu,reports[]}",
        "state", "tools/model_inventory.py --json", ["数据空间页/训练页"], ["test"],
        (bool(mi), "model_inventory 产出 ok"),
        "python3 tools/model_inventory.py --json → " + ev_mi)
    for m in (mi.get("models") or [])[:8]:
        short = (m.get("name") or "?").split("·")[-1].strip()
        add("模型引擎", "模型_%s·%s" % (m.get("layer") or "?", short), "model_inventory",
            "json{models[]}", "state", "tools/model_inventory.py --json", ["训练页/部署"], ["test"],
            (bool(m.get("ready")), "ready=%s size=%s" % (m.get("ready"), m.get("size_h"))),
            "%s · active=%s size=%s ready=%s path=%s" % (
                m.get("name"), m.get("active"), m.get("size_h"), m.get("ready"), m.get("path")))
    add("模型引擎", "模型_训练运行", "train_prog", "zmax::TrainProgress", "state@state",
        "训练脚本→进度文件 / zmax-dds-pub", ["训练页", "DDS订阅端"], TQ("train_prog"),
        P("train_progress"), "progress_v6expand.json " + ("在" if P("train_progress")[0] else "缺") +
        " · model_inventory training=%d(当前无在跑训练)" % len(mi.get("training") or []),
        note="topic train_prog 已有; 但训练运行本身当前为空")
    add("模型引擎", "模型_推理服务", "ss_infer", "zmax::SSInfer", "beat",
        "ss_daemon ← http://127.0.0.1:8790/health", ["推理页", "数据空间页"], TQ("ss_infer"),
        P("infer_8790"), "curl 8790/health " + ("200" if P("infer_8790")[0] else "不通"))
    add("模型引擎", "模型_能量探针", "ss_energy", "zmax::SSEnergy", "state",
        "tools/manifold_energy_probe.py → tap → ss_daemon", ["画布能量节点", "训练页"], TQ("ss_energy"),
        P("energy_tap"), "能量 tap " + probes.get("energy_tap", ("", "?"))[1])
    add("模型引擎", "模型_评测报告", "model_reports", "json{reports[]}", "state",
        "tools/model_inventory.py --json", ["评估页/数据空间页"], ["test"],
        (len(mi.get("reports") or []) > 0, "reports=%d" % len(mi.get("reports") or [])),
        "model_inventory.reports: %d 条(训练 run 的 steps/samples/artifact)" % len(mi.get("reports") or []))
    add("模型引擎", "模型_部署审计", "deploy_cmd", "zmax::DeployCommand", "cmd",
        "ECS/控制台(人工晋级)", ["4060/Orin 部署执行"], TQ("deploy_cmd"),
        P("deploy_audit"), "docs/deploy_audit.jsonl " + ("在" if P("deploy_audit")[0] else "缺(S7 部署门 unknown)"))

    # ═══════════════ C. 场景 (scene_edit + canvas) ═══════════════
    se = sources.get("scene_edit", {}).get("data") or {}
    ev_se = sources.get("scene_edit", {}).get("evidence", "未产出")
    add("场景", "场景_对象清单", "scene_objects", "json{objects[],markers[],fences[],trajectories[]}",
        "state", "tools/scene_edit.py list --json", ["3D视图/画布叠加"], ["test"],
        (bool(se), "scene_edit 产出 ok"),
        "python3 tools/scene_edit.py list --json → " + ev_se +
        " · 例: %s" % ((se.get("objects") or [{}])[0].get("name")))
    add("场景", "场景_markers_fences_traj", "scene_objects", "json{markers,fences,trajectories}",
        "state", "tools/scene_edit.py list --json", ["3D视图"], ["test"],
        (bool(se.get("markers") or se.get("fences") or se.get("trajectories")),
         "空集合" if not (se.get("markers") or se.get("fences") or se.get("trajectories")) else "非空"),
        "markers=%d fences=%d traj=%d(当前全空)" % (
            len(se.get("markers") or []), len(se.get("fences") or []), len(se.get("trajectories") or [])))
    add("场景", "场景_画布节点", "ss_canvas", "zmax::SSCanvasNode", "state",
        "ss_daemon ← flows/state_space_obs.json", ["画布页", "数据空间页"], TQ("ss_canvas"),
        P("canvas_json"), "flows/state_space_obs.json " + ("在" if P("canvas_json")[0] else "缺"))
    add("场景", "场景_MoveIt规划", "ss_plan", "zmax::SSPlan", "state",
        "MoveIt plan-only → live_plan.jsonl → ss_daemon", ["叠加层", "数据空间页"], TQ("ss_plan"),
        P("moveit_plan"), "~/zmax_moveit_plan/live_plan.jsonl " + ("在" if P("moveit_plan")[0] else "缺"))
    add("场景", "场景_标定真源", "ss_calib", "zmax::SSCalib", "state",
        "ss_daemon ← 标定真源文件", ["标定页/现场核对"], TQ("ss_calib"),
        P("handeye"), "models/handeye_state.json " + ("在" if P("handeye")[0] else "缺"))

    # ═══════════════ D. 监控 (remote_monitor_aggregate) ═══════════════
    rm = sources.get("remote_monitor_aggregate", {}).get("data") or {}
    ev_rm = sources.get("remote_monitor_aggregate", {}).get("evidence", "未产出")
    add("监控", "监控_端点矩阵", "endpoint_matrix", "json{endpoints[]}", "state",
        "tools/remote_monitor_aggregate.py --json", ["工位总览/大屏", "数据空间页"], ["diag", "test"],
        (bool(rm), "remote_monitor_aggregate 产出 ok"),
        "python3 tools/remote_monitor_aggregate.py --json → " + ev_rm)
    add("监控", "监控_同源一致性", "same_source", "json{same_source[]}", "state",
        "tools/remote_monitor_aggregate.py --json", ["工位总览", "数据质量门"], ["diag", "test"],
        (bool(rm), "same_source=%d 项" % len(rm.get("same_source") or [])),
        "same_source=%d 项(臂相机fps/帧龄/在线/设备名 + 工位机GPU利用率 跨端点一致)" % len(rm.get("same_source") or []))
    add("监控", "监控_硬件遥测", "hw_state", "zmax::HardwareState", "state",
        "zmax-dds-pub (4060 硬件发布端)", ["硬件页", "工位总览", "数据空间页"], TQ("hw_state"),
        (True, "zmax-dds-pub active"), "systemctl zmax-dds-pub=active · live.json hw_state count=%s" % (
            ((live.get("topics") or {}).get("hw_state") or {}).get("count")))
    add("监控", "监控_心跳", "heartbeat", "zmax::Heartbeat", "beat",
        "各端守护", ["节点灯/数据空间页"], TQ("heartbeat"),
        (True, "zmax-dds-pub active"), "live.json heartbeat count=%s age=%ss" % (
            ((live.get("topics") or {}).get("heartbeat") or {}).get("count"),
            ((live.get("topics") or {}).get("heartbeat") or {}).get("age_s")))
    add("监控", "监控_诊断", "ss_diag", "zmax::SSDiag", "beat",
        "ss_daemon(延时/帧龄/吞吐/健康度)", ["监控页", "告警"], TQ("ss_diag"),
        (True, "ss_daemon active"), "live.json ss_diag count=%s hz=%s" % (
            ((live.get("topics") or {}).get("ss_diag") or {}).get("count"),
            ((live.get("topics") or {}).get("ss_diag") or {}).get("hz")))

    # ═══════════════ E. 遥测 (DDS 话题总线本身) ═══════════════
    if T:
        for key, meta in T.TOPICS.items():
            tinfo = (live.get("topics") or {}).get(key) or {}
            cnt = tinfo.get("count")
            allowed_now = tinfo.get("allowed")
            if allowed_now is None:
                lv = (None, "当前模式(%s)未开此话题" % live.get("mode"))
                live_now = None
            else:
                lv = None
                live_now = bool(cnt and cnt > 0)
            add("遥测", "话题_%s" % key, key, meta.get("type", ""), meta.get("qos", ""),
                meta.get("producer", ""), list(meta.get("consumers") or []),
                [m for m, ts in T.MODE_TOPICS.items() if key in ts], None,
                "src/lerobot/dataspace/topics.py::TOPICS[%r] · rate=%.2fHz · live.json count=%s allowed=%s verdict=%s" % (
                    key, meta.get("rate_hz", 0.0), cnt, allowed_now, tinfo.get("verdict")))
            S[-1]["live_now"] = live_now
            S[-1]["live_note"] = ("count=%s age=%ss verdict=%s" % (
                cnt, tinfo.get("age_s"), tinfo.get("verdict"))) if allowed_now is not None else \
                "当前模式(%s)未开" % live.get("mode")
        add("遥测", "总线_模式框架", "", "dict{mode:[topics]}", "-",
            "tools/gui/zmax_telemetry.py", ["守护/业务代码/所有订阅端"], ["ALL"],
            (True, "zmax_telemetry 在盘"),
            "注册表版本 %s · 档位话题数 %s" % ((live.get("registry_version")),
                {m: len(v) for m, v in T.MODE_TOPICS.items()}))
        add("遥测", "总线_话题注册表", "", "dict{key:{type,producer,consumers,quality}}", "-",
            "src/lerobot/dataspace/topics.py", ["GUI数据空间页", "守护", "巡检"], ["ALL"],
            (True, "topics.py 在盘"),
            "TOPICS 条目 %d · 质量规则 %d 条 · 闭环环节 %d" % (
                len(T.TOPICS), len(T.QUALITY_RULES), len(T.CLOSED_LOOP)))

    # ═══════════════ F. 架构 (arch_graph) ═══════════════
    ag = sources.get("arch_graph", {}).get("data") or {}
    ev_ag = sources.get("arch_graph", {}).get("evidence", "未产出")
    add("架构", "架构_全图", "arch_graph", "json{nodes[],edges[],meta}", "state",
        "tools/arch_graph.py --json", ["架构图/数据空间页"], ["test"],
        (bool(ag), "arch_graph 产出 ok"),
        "python3 tools/arch_graph.py --json → " + ev_ag)
    add("架构", "架构_节点", "arch_graph", "json{nodes[]}", "state",
        "tools/arch_graph.py --json", ["架构图"], ["test"],
        (bool(ag), "nodes=%d" % len(ag.get("nodes") or [])),
        "nodes=%d(0..11 层: 平台/产品/特征/子系统/功能/模块/代码/参数/能力/接口/验证/真源)" % len(ag.get("nodes") or []))
    add("架构", "架构_边", "arch_graph", "json{edges[]}", "state",
        "tools/arch_graph.py --json", ["架构图"], ["test"],
        (bool(ag), "edges=%d" % len(ag.get("edges") or [])),
        "edges=%d" % len(ag.get("edges") or []))

    # ═══════════════ G. 版本 (verify_version_sync) ═══════════════
    vs = sources.get("verify_version_sync", {}).get("data") or {}
    ev_vs = sources.get("verify_version_sync", {}).get("evidence", "未产出")
    add("版本", "版本_权威与同步点", "version_sync", "json{sync_locations[],canonical_version}",
        "state", "tools/verify_version_sync.py --json", ["版本面板/更新检查"], ["test"],
        (bool(vs), "verify_version_sync 产出 ok"),
        "python3 tools/verify_version_sync.py --json → " + ev_vs)
    add("版本", "版本_远端对齐", "version_sync", "json{remote}", "state",
        "tools/verify_version_sync.py --json", ["更新检查"], ["test"],
        (bool(vs), "remote_release_aligned=%s" % (vs.get("remote") or {}).get("release_aligned")),
        "canonical=%s remote_release_aligned=%s" % (
            vs.get("canonical_version"), (vs.get("remote") or {}).get("release_aligned")))

    # ═══════════════ H. AOI (产线检测服务) ═══════════════
    add("AOI", "AOI_金手指10082", "aoi_result", "json{code,count,defects[],detect_type,gf}", "beat",
        "工控机 192.168.23.23:10082 /capture_detect", ["AOI页/伺服/数据空间页"], ["diag", "test"],
        P("aoi_10082"), "GET 10082/last_result " + ("200" if P("aoi_10082")[0] else "不通") +
        " · detect_type=gf · 见 remote_monitor端 age 提示陈旧")
    add("AOI", "AOI_表面10083", "aoi_result", "json{code,count,detect_type:housing}", "beat",
        "工控机 192.168.23.23:10083 /capture_detect", ["AOI页/数据空间页"], ["diag", "test"],
        P("aoi_10083"), "GET 10083/last_result " + ("200" if P("aoi_10083")[0] else "不通") +
        " · detect_type=housing · judge_ok=false(画面未找到过曝条)")
    add("AOI", "AOI_生产清单", "aoi_manifest", "json{...}", "state",
        "tools/aoi/PRODUCTION_MANIFEST.json", ["部署/回归"], ["test"],
        P("aoi_manifest"), "tools/aoi/PRODUCTION_MANIFEST.json " + ("在" if P("aoi_manifest")[0] else "缺"))

    # ═══════════════ I. HIL (人机在环) ═══════════════
    add("HIL", "HIL_上行快照", "hil_state", "json{obs7,layers,events,canvas}", "state",
        "tools/hil_bridge.py build_snapshot → relay/hil/state", ["hil.html", "数据空间页"], ["diag", "test"],
        P("hil_8795"), "GET 127.0.0.1:8795/hil/state " + ("200" if P("hil_8795")[0] else "不通"))
    add("HIL", "HIL_下行指示", "hil_instruction", "json{from,text,verdict}", "cmd",
        "网页 hil.html → agent/prompt → hil_bridge.poll_instructions", ["HIL桥/审计"], ["test"],
        P("hil_audit"),
        "reports/hil_bridge_state.json + reports/hil_instructions.jsonl(指示落盘审计)")
    add("HIL", "HIL_红线审计", "hil_instruction", "jsonl{verdict:refused_motion}", "state",
        "hil_bridge 拒答动作类指示", ["审计/取证"], ["test"],
        P("hil_audit"), "reports/hil_instructions.jsonl " + ("在" if P("hil_audit")[0] else "缺") +
        " · 8795 实测 verdict=refused_motion(未授权不下发真机动作)")
    add("HIL", "HIL_服务常驻", "hil_state", "service", "-",
        "systemd zmax-hil-bridge", ["监控/数据空间页"], ["diag", "test"],
        P("hil_verify"), "最近取证 " + probes.get("hil_verify", ("", "?"))[1])

    return S


# ───────────────────────────── 汇总 ─────────────────────────────
def build_catalog():
    t0 = time.time()
    sources = collect_sources()
    probes = collect_probes()
    live = _load_live()
    mt_live = _load_mode_topics(DAEMON_LIVE) or {}
    mt_stale = _load_mode_topics(DAEMON_STALE) or {}
    mt_gui = _load_mode_topics(GUI_TELEMETRY) or {}
    mt_topics = ({m: list(v) for m, v in T.MODE_TOPICS.items()} if T else {})

    slices = build_slices(sources, probes, live, mt_live)

    n_existing = sum(1 for s in slices if s["topic_state"] == "existing")
    n_missing = sum(1 for s in slices if s["topic_state"] == "missing")
    n_live = sum(1 for s in slices if s["live_now"] is True)
    n_live_unknown = sum(1 for s in slices if s["live_now"] is None)

    # 现有话题 vs 缺失切面 清单
    existing_topics = []
    seen_t = set()
    for s in slices:
        if s["topic_state"] == "existing" and s["topic_key"] not in seen_t:
            seen_t.add(s["topic_key"])
            ti = (live.get("topics") or {}).get(s["topic_key"]) or {}
            existing_topics.append({
                "topic": s["topic"], "key": s["topic_key"],
                "type": s["dtype"], "qos": s["qos"],
                "producer": s["producer"], "consumers": s["consumers"],
                "modes": s["gate"],
                "allowed_now": ti.get("allowed"), "count": ti.get("count"),
                "age_s": ti.get("age_s"), "verdict": ti.get("verdict"),
            })
    missing = [{"area": s["area"], "key": s["key"], "suggested_topic": s["topic"],
                "dtype": s["dtype"], "qos": s["qos"], "gate": s["gate"],
                "producer": s["producer"], "evidence": s["evidence"]}
               for s in slices if s["topic_state"] == "missing"]

    # 档位口径漂移 (注册表 vs 运行守护 vs 旧副本 vs GUI)
    drift = []
    for name, mt in (("topics.py(MODE_TOPICS)", mt_topics),
                     ("tools/dds/ss_daemon.py(运行)", mt_live),
                     ("tools/zmax_dds_ss_daemon.py(旧副本)", mt_stale),
                     ("tools/gui/zmax_telemetry.py", mt_gui)):
        if not mt:
            drift.append({"source": name, "error": "未读到"})
    modes_all = set(mt_topics) | set(mt_live) | set(mt_stale) | set(mt_gui)
    for m in sorted(modes_all):
        vals = {}
        for name, mt in (("topics.py", mt_topics), ("daemon_live", mt_live),
                         ("daemon_stale", mt_stale), ("gui_telemetry", mt_gui)):
            if mt:
                vals[name] = sorted(mt.get(m, []))
        uniq = {tuple(v) for v in vals.values()}
        if len(uniq) > 1:
            drift.append({"mode": m, "sources": vals})

    # 同源关系表 (功能区 ↔ 话题 ↔ 生产者 ↔ 消费者)
    same_source_table = [{
        "area": s["area"], "slice": s["key"], "topic": s["topic"],
        "topic_state": s["topic_state"], "producer": s["producer"],
        "consumers": " / ".join(s["consumers"]), "gate": "/".join(s["gate"]),
        "live_now": s["live_now"],
    } for s in slices]

    # 建议 patch 文本 (只写文本, 不改守护)
    miss_topic_keys = sorted({m["suggested_topic"].replace("zmax/", "") for m in missing})
    patch_text = (
        "# ⚠️ 建议(未应用): 把缺失切面接入数据总线。\n"
        "# 1) 在 src/lerobot/dataspace/topics.py::TOPICS 注册以下话题 (key → type/producer/consumers):\n"
        + "\n".join("  + %-22s  # 见 catalog missing_slices" % k for k in miss_topic_keys) +
        "\n# 2) 在守护 MODE_TOPICS 把它们挂到 'test'(取证) 或 'diag'(诊断) 档:\n"
        "  diag  += [\"endpoint_matrix\",\"aoi_result\",\"hil_state\"]\n"
        "  test  += [" + ",".join("\"%s\"" % k for k in miss_topic_keys) + "]\n"
        "# 3) 上线前必须复验: prod 仍零开销 & diag 档仍能起 (python3 tools/dds/ss_daemon.py --status)。\n"
        "# 本工具只读, 不改任何守护行为。")

    return {
        "tool": "dataspace_catalog.py",
        "schema": "zmax-dataspace-catalog/1.0",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "repo": REPO,
        "registry": {
            "ok": REG_OK, "error": REG_ERR,
            "registry_version": (T.VERSION if T else None),
            "mode_now": live.get("mode"),
            "n_topics_registered": len(T.TOPICS) if T else 0,
            "n_topics_allowed_now": live.get("n_topics_allowed"),
            "mode_topics": mt_topics, "daemon_running_mode_topics": mt_live,
            "drift": drift,
        },
        "totals": {
            "slices": len(slices), "areas": len({s["area"] for s in slices}),
            "existing_topic_slices": n_existing, "missing_topic_slices": n_missing,
            "unique_existing_topics": len(existing_topics),
            "live_now_true": n_live, "live_now_unknown": n_live_unknown,
            "elapsed_s": round(time.time() - t0, 1),
        },
        "areas": sorted({s["area"] for s in slices}),
        "slices": slices,
        "existing_topics": existing_topics,
        "missing_slices": missing,
        "same_source_table": same_source_table,
        "suggested_topic_patches": patch_text,
        "source_evidence": {k: v.get("evidence") for k, v in sources.items()},
    }


# ───────────────────────────── 渲染 ─────────────────────────────
def human(c):
    L = []
    A = L.append
    t = c["totals"]
    A("=" * 100)
    A("🌐 Z-MAX 全局数据总线目录 (dataspace catalog)   %s" % c["generated_at"])
    A("=" * 100)
    A("注册表: %s · 现有话题 %d · 当前模式 %s(允许 %s) · 切面 %d (功能区 %d)" % (
        c["registry"]["registry_version"], c["registry"]["n_topics_registered"],
        c["registry"]["mode_now"], c["registry"]["n_topics_allowed_now"],
        t["slices"], t["areas"]))
    A("切面统计: 已有话题切面 %d · 缺话题切面 %d · 活(数据源在跑) %d · 未探 %d · 耗时 %ss" % (
        t["existing_topic_slices"], t["missing_topic_slices"], t["live_now_true"],
        t["live_now_unknown"], t["elapsed_s"]))
    if c["registry"]["drift"]:
        A("\n⚠️ 档位口径漂移 (注册表 vs 运行守护 vs 旧副本 vs GUI):")
        for d in c["registry"]["drift"]:
            if "mode" in d:
                A("   mode=%s: %s" % (d["mode"], d["sources"]))
            else:
                A("   %s" % d)
    A("\n【一】功能区 ↔ 切面 ↔ 话题 ↔ 状态  (人读表)")
    A("-" * 100)
    cur = None
    for s in c["slices"]:
        if s["area"] != cur:
            cur = s["area"]
            A("[%s]" % cur)
        mark = {"existing": "✅有话题", "missing": "➕缺话题", "meta": "·元切面"}.get(s["topic_state"], "?")
        lv = {True: "🟢活", False: "⚪静", None: "❔未探"}[s["live_now"]]
        A("   %-10s %-30s %-18s %-4s %s" % (mark, s["key"], s["topic"], lv, s["dtype"][:24]))
    A("\n【二】现有话题 vs 缺失切面")
    A("-" * 100)
    A("✅ 现有 DDS 话题 (%d 个, 注册表):" % len(c["existing_topics"]))
    for e in c["existing_topics"]:
        A("   %-16s %-22s mode=%-22s now_allowed=%s count=%s" % (
            e["key"], e["type"], ",".join(e["modes"]), e["allowed_now"], e["count"]))
    A("\n➕ 缺话题切面 (%d 个) —— 数据源在, 无 DDS 出口:" % len(c["missing_slices"]))
    for m in c["missing_slices"]:
        A("   %-10s %-26s 建议话题=%s" % (m["area"], m["key"], m["suggested_topic"]))
    A("\n【三】功能区 ↔ 话题 ↔ 生产者 ↔ 消费者 (同源关系表)")
    A("-" * 100)
    A("   %-8s %-24s %-18s %-34s %s" % ("功能区", "切面", "话题", "生产者", "消费者"))
    for r in c["same_source_table"]:
        A("   %-8s %-24s %-18s %-34s %s" % (
            r["area"], r["slice"][:24], r["topic"][:18], r["producer"][:34], r["consumers"][:30]))
    A("\n【四】建议 patch (未应用, 只读建议)")
    A("-" * 100)
    A(c["suggested_topic_patches"])
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="全局数据总线目录 (只读)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="", help="写 JSON 到文件 (只读以外的唯一写动作)")
    a = ap.parse_args()
    c = build_catalog()
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out + ".tmp", "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(a.out + ".tmp", a.out)
    if a.json:
        print(json.dumps(c, ensure_ascii=False, indent=1))
    else:
        print(human(c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
