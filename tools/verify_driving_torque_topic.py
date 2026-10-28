# -*- coding: utf-8 -*-
"""verify_driving_torque_topic.py — 「驱动扭矩 T_drive = M·(−∇Φ) 全局数据空间 topic」判据。

老倪 2026-10-13: 「T drive = M·(−∇Φ) 用 topic 在全局数据空间输出，我要看到，并在实时监控里，有这个信号」。

判据口径 (逐项 ✅/❌ + 证据字符串 + 未验证项), 覆盖 12 组:
  ① 定义式一致: 从 tap 最后一行 payload 自带字段独立复算 clip(M·(−∇Φ),±t_max)·gain / M·(−∇Φ) / M⁻¹·(−∇Φ)
  ② 唯一依据同源: payload.metric_tensor ↔ MetricField.from_config(cfg).g(x); payload.potential_gradient[3:5] ↔ grad_raw(x) 现场重算
  ③ 正定性/健康度: 度量对称正定 (特征值>0); gain 与 status 一致
  ④ 限幅: 逐分量 |torque_i| ≤ t_max; clipped 标志与 raw 是否超限一致
  ⑤ 注册三处: topics.py TOPICS / MODE_TOPICS 三档 / PRODUCERS / QUALITY_RULES 三条新规则
  ⑥ 守护链路: ss_daemon read_torque/pub_torque/tick allowed 分支; zmax_node _SS_TOPICS+QOS_CLASS; ss_types SSDrivingTorque
  ⑦ 注册表登记: live.json ss_torque 记录 (type / matched_pubs / count / 帧龄<10s)
  ⑧ 总线追踪: trace.jsonl zmax/ss_torque 帧≥5; digest 经 canoe_graphic.parse_ds_digest 出数值叶子
  ⑨ DDS 端到端: dds-venv python + zmax_node.py 真订阅 ≥1 条, torque/phi 与 tap 最后一行逐位一致
  ⑩ 时效性: 发布器 pid 锁存在且活 · tap 最后一行 ts 帧龄<3s · 守护 STALE_TORQUE_S=3.0
  ⑪ 单位/口径自证: unit=N·m + unit_note 非空含「未做扭矩计量学标定」; spec 未接通道(1000Hz/100Hz)如实说明
  ⑫ 零回归: 其余 9 个总线话题仍在 · 画布 89 节点/184 连线 · ss_task_bind --check · verify_localization_mapping 23/23

幂等: 只读唯一依据 + 只订阅 DDS (不写 tap/不改运行中的发布器/守护); 唯一写入是本报告。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_driving_torque_topic.py
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# tap 流不再落盘 (老倪 2026-10-13): 与 tools/tdrive_bus.py 同源解析 —— 默认内存盘 /dev/shm
TAP_DIR = os.environ.get("ZMAX_TORQUE_TAP_DIR") or "/dev/shm/zmax_torque"
sys.path.insert(0, os.path.join(ROOT, "src"))
PY = sys.executable or os.path.join(ROOT, "gui-venv311", "bin", "python")
DDS_PY = os.path.join(ROOT, "venvs", "dds-venv", "bin", "python")


def _resolve_tap() -> str:
    """驱动的 tap 唯一依据 = **当前活跃场景**那份 (与 tools/tdrive_bus.py 同一口径)。

    🔴 2026-10-13: 原先这里预先固定 `torque_SCN-07-AOI.jsonl` —— 服务改成"场景跟随 ss_scene_switch"
    之后, 活跃场景是摆盘(SCN-06-TRAY)时, 判据去读**没人再写的旧 AOI 文件**, 于是 ⑩b 假红
    (实测 tap 帧龄 4318s ⇒ 判据在量一个陈旧文件, 不是在量现场)。
    规则: 跟活跃场景取 torque_<SCN>.jsonl; 取不到就取最新在写的那份, 并把选中的文件打出来。
    """
    import glob
    import json as _json
    scn = ""
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import ss_scene_switch as _sw
        nm = (_sw.now() or {}).get("src_state") or ""
        for s in (_json.load(open(os.path.join(ROOT, "config", "topics", "scene_tags.json"),
                                  encoding="utf-8")).get("scenes") or []):
            if s.get("scene") == nm:
                scn = s.get("scn") or ""
                break
    except Exception:                                                              # noqa: BLE001
        pass
    if scn:
        p = os.path.join(TAP_DIR, "torque_%s.jsonl" % scn)
        if os.path.isfile(p):
            return p
    g = sorted(glob.glob(os.path.join(TAP_DIR, "torque_SCN-*.jsonl")),
               key=os.path.getmtime, reverse=True)
    return g[0] if g else os.path.join(ROOT, "zmax_data", "ss_live", "torque_live.json")


TAP = _resolve_tap()
print("驱动扭矩判据 · tap 唯一依据: %s" % os.path.relpath(TAP, ROOT))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live", "torque_live.json")
PIDF = os.path.join(ROOT, "zmax_data", "ss_live", "torque.pid")
DS_LIVE = os.path.join(ROOT, "zmax_data", "dataspace", "live.json")
DS_TRACE = os.path.join(ROOT, "zmax_data", "dataspace", "trace.jsonl")
TOPICS_PY = os.path.join(ROOT, "src", "lerobot", "dataspace", "topics.py")
DAEMON = os.path.join(ROOT, "tools", "dds", "ss_daemon.py")
ZNODE = os.path.join(ROOT, "dds", "zmax_node.py")
STYPS = os.path.join(ROOT, "dds", "ss_types.py")
CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")
SCENE = "SCN-07-AOI"
T_MAX_SPEC = 30.0
OK, BAD, SKIP = [], [], []


def chk(name, ok, ev):
    (OK if ok else BAD).append((name, ev))
    print("  %s %-56s %s" % ("✅" if ok else "❌", name, ev))


def skip(name, why):
    SKIP.append((name, why))
    print("  ⏭ %-56s %s" % (name, why))


def read_tap_last(path):
    """tap 的**最后一行**才是 payload (与能量层同口径)。"""
    last = None
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    return json.loads(last) if last else None


def read_src(path):
    return io.open(path, encoding="utf-8", errors="ignore").read()


def run(cmd, timeout=120, env=None):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, **(env or {})})
    return p.returncode, (p.stdout or ""), (p.stderr or "")


DDS_PROBE = r'''
import sys, time, json
sys.path.insert(0, "/home/ubuntu/zmax/dds")
from zmax_node import Node
n = Node("torque_judge", domain=0)
n.sub("ss_torque")
got = []
t0 = time.time()
while time.time() - t0 < 14:
    s = n.take("ss_torque", timeout=1.5)
    if s:
        got.extend(s)
        if len(got) >= 3:
            break
out = [{"ts": float(m.ts), "torque": [float(v) for v in m.torque], "phi": float(m.phi),
        "unit": str(m.unit), "scene": str(m.scene), "gain": float(m.gain),
        "status": str(m.status), "metric_dim": int(m.metric_dim),
        "torque_inv": [float(v) for v in m.torque_inv],
        # 🏷 标识信息 (老倪 2026-10-14): 话题上必须看得到"在为哪个任务/哪个产品干活"
        "task_id": str(m.task_id), "task_name": str(m.task_name), "product": str(m.product),
        "product_prime": int(m.product_prime), "m_scale": float(m.m_scale),
        "identity_json": str(m.identity_json)} for m in got[:3]]
print(json.dumps({"n": len(got), "samples": out}, ensure_ascii=False))
'''


def dds_subscribe(tries=2):
    """真 DDS 订阅 (dds-venv + dds/zmax_node.py)。失败如实返回 (ok=False, [])。"""
    errs = []
    for _ in range(tries):
        try:
            rc, out, err = run([DDS_PY, "-c", DDS_PROBE], timeout=90)
            j = json.loads((out or "").strip().splitlines()[-1] if out.strip() else "{}")
            if j.get("n"):
                return True, j.get("samples") or [], ""
            errs.append((err or out or "no sample")[:160])
        except Exception as e:                                                    # noqa: BLE001
            errs.append(repr(e)[:160])
    return False, [], " | ".join(errs)[:300]


def main() -> int:
    t0 = time.time()
    print("═" * 104)
    print("驱动扭矩 T_drive = M·(−∇Φ) · 全局数据空间 topic 判据")
    print("═" * 104)

    if not os.path.isfile(TAP):
        print("❌ tap 不存在: %s" % TAP)
        return 2
    d = read_tap_last(TAP)
    M = np.asarray(d["metric_tensor"], float).reshape(int(d["metric_dim"]), int(d["metric_dim"]))
    neg6 = np.asarray(d["neg_gradient"], float)
    tau = np.asarray(d["torque"], float)
    raw = np.asarray(d["torque_raw"], float)
    tinv = np.asarray(d["torque_inv"], float)
    t_max = float(d["t_max"])
    gain = float(d["gain"])
    print("payload: ts=%.3f scene=%s ‖T‖=%.4f raw_norm=%.1f gain=%.2f status=%s t_max=%.0f"
          % (d["ts"], d["scene"], np.linalg.norm(tau), d["torque_raw_norm"], gain, d["status"], t_max))

    # ───────────────────────── ① 定义式一致 ─────────────────────────
    print("\n[① 定义式一致] 用 payload 自带字段独立复算 (不信任发布器结论)")
    ROT = 3
    # 主参数维数唯一依据: dim=3 (位置) / dim=6 (位姿, 插拔任务含腕部翻转 ⇒ config_to_M R1 判 6)。
    # 向量必须与 M 同维 —— 与 tools/tdrive_bus.py 同一条口径 (dim=6 用 6D 向量 [旋转 0,0,0 | 平移 …])。
    _d6 = (M.shape[0] == 6)
    raw_exp = (M @ neg6) if _d6 else np.concatenate([np.zeros(ROT), M @ neg6[ROT:]])
    exp_clip = np.clip(raw_exp, -t_max, t_max) * gain
    e1 = float(np.max(np.abs(tau - exp_clip))) if tau.size else 9e9
    chk("①a torque == clip(M·(−∇Φ), ±%.0f)·gain" % t_max, e1 <= 1e-9,
        "逐位最大偏差 %.3e (≤1e-9)" % e1)
    e1b = float(np.max(np.abs(raw - raw_exp)))
    chk("①b torque_raw == M·(−∇Φ) (未限幅)", e1b <= 1e-9, "逐位最大偏差 %.3e (≤1e-9)" % e1b)
    try:
        Minv = np.linalg.inv(M)
        inv_exp = gain * (Minv @ (neg6 if _d6 else neg6[ROT:]))
        e2 = float(np.max(np.abs((tinv if _d6 else tinv[ROT:]) - inv_exp)))
    except Exception as ex:                                                       # noqa: BLE001
        e2 = 9e9
        _ = ex
    chk("①c torque_inv == M⁻¹·(−∇Φ)", e2 <= 1e-6, "逐位最大偏差 %.3e (≤1e-6)" % e2)

    # ───────────────────────── ② 唯一依据同源 ─────────────────────────
    print("\n[② 唯一依据同源] M ← 主参数唯一依据; −∇Φ ← potential_field 现场重算")
    x = np.asarray(d["x"], float)
    try:
        from lerobot.manifold.metric_field import MetricField, _load_manifold_cfg
        cfg = _load_manifold_cfg()
        mf = MetricField.from_config(cfg)
        _xm = np.concatenate([np.zeros(ROT), x]) if int(getattr(mf, "dim", 3)) == 6 else x
        g_true = np.asarray(mf.g(_xm), float).ravel()
        g_pay = np.asarray(d["metric_tensor"], float).ravel()
        em = float(np.max(np.abs(g_true - g_pay)))
        chk("②a metric_tensor == MetricField.from_config(cfg).g(x)", em <= 1e-9,
            "逐位最大偏差 %.3e · dim=%d · M=%.4f · mode=%s (x 从 payload 取)"
            % (em, mf.dim, mf.scale, mf.mode))
    except Exception as ex:                                                       # noqa: BLE001
        em = 9e9
        chk("②a metric_tensor ↔ 唯一依据度量", False, "复算失败: %s" % repr(ex)[:120])
    try:
        from lerobot.memory.potential_field import MemoryLayerBridge
        br = MemoryLayerBridge.from_real_data(ROOT)
        gr = np.asarray(br.grad_raw(x, None), float)[:3]
        pg = np.asarray(d["potential_gradient"], float)[ROT:]
        eg = float(np.max(np.abs(gr - pg)))
        chk("②b potential_gradient[3:5] == grad_raw(x) (现场重算)", eg <= 1e-9,
            "逐位最大偏差 %.3e · grad_raw=%s · gates=%s" % (eg, np.round(gr, 3).tolist(), d.get("gates")))
    except Exception as ex:                                                       # noqa: BLE001
        chk("②b potential_gradient ↔ grad_raw 唯一依据", False, "复算失败: %s" % repr(ex)[:120])

    # ───────────────────────── ③ 正定性 / 健康度 ─────────────────────────
    print("\n[③ 正定性/健康度] 度量对称正定 + 增益与状态一致")
    sym = float(np.max(np.abs(M - M.T)))
    eig = np.linalg.eigvalsh(M)
    chk("③a 度量对称正定 (λ_min>0)", sym <= 1e-12 and float(np.min(eig)) > 0.0,
        "对称偏差 %.2e · λ = %s" % (sym, np.round(eig, 4).tolist()))
    want = {"normal": 1.0, "warning": 0.5, "critical": 0.0}.get(d["status"], 1.0)
    chk("③b gain 与 status 一致", abs(gain - want) <= 1e-12,
        "status=%s gain=%.2f 期望 %.2f" % (d["status"], gain, want))

    # ───────────────────────── ④ 限幅 ─────────────────────────
    print("\n[④ 限幅] 逐分量 |T_i| ≤ t_max + clipped 标志与 raw 一致")
    inb = float(np.max(np.abs(tau))) <= t_max + 1e-9
    chk("④a 逐分量 |torque_i| ≤ t_max", inb,
        "max|T_i|=%.3f ≤ %.0f (‖T‖=%.3f ≤ √3·T_MAX=%.3f)"
        % (float(np.max(np.abs(tau))), t_max, float(np.linalg.norm(tau)), t_max * np.sqrt(3)))
    clip_want = bool(np.any(np.abs(raw) > t_max + 1e-12))
    chk("④b clipped 标志与 raw 超限一致", bool(d["clipped"]) == clip_want,
        "clipped=%s · raw max|x|=%.1f (>%.0f ?)" % (d["clipped"], float(np.max(np.abs(raw))), t_max))

    # ───────────────────────── ⑤ 注册三处齐全 ─────────────────────────
    print("\n[⑤ 注册齐全] topics.py TOPICS / MODE_TOPICS / PRODUCERS / QUALITY_RULES")
    try:
        from lerobot.dataspace import topics as T
        t = T.TOPICS.get("ss_torque") or {}
        chk("⑤a TOPICS['ss_torque'] 含 rate_hz/ros_alias/type", bool(t) and
            isinstance(t.get("rate_hz"), (int, float)) and bool(t.get("ros_alias")) and
            t.get("type") == "zmax::SSDrivingTorque",
            "rate_hz=%s ros_alias=%s type=%s" % (t.get("rate_hz"), t.get("ros_alias"), t.get("type")))
        tiers = {m: ("ss_torque" in (T.MODE_TOPICS.get(m) or [])) for m in ("diag", "calib", "test")}
        chk("⑤b MODE_TOPICS 三档都含 ss_torque", all(tiers.values()),
            "diag=%s calib=%s test=%s" % (tiers["diag"], tiers["calib"], tiers["test"]))
        prods = [k for k, v in T.PRODUCERS.items() if "ss_torque" in (v.get("publishes") or [])]
        chk("⑤c PRODUCERS 有 ss_torque 发布器", bool(prods),
            "producer=%s → %s" % (prods, (T.PRODUCERS[prods[0]].get("path") if prods else None)))
        need = ["metric_definite", "torque_matches_definition", "health_gain_consistent"]
        have = [r for r in need if r in T.QUALITY_RULES]
        chk("⑤d QUALITY_RULES 含三条新规则", len(have) == 3, "命中 %s (共 %d 条规则)" % (have, len(T.QUALITY_RULES)))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑤ topics.py 注册读取", False, "import 失败: %s" % repr(ex)[:120])

    # ───────────────────────── ⑥ 守护链路 ─────────────────────────
    print("\n[⑥ 守护链路] ss_daemon → zmax_node → ss_types")
    dsrc = read_src(DAEMON)
    tick_branch = bool(re.search(r'allowed\(["\']ss_torque["\']\)\s*:[\s\S]{0,80}?pub_torque\(\)', dsrc))
    chk("⑥a ss_daemon 有 read_torque/pub_torque + tick allowed 分支",
        "def read_torque(" in dsrc and "def pub_torque(" in dsrc and tick_branch,
        "read_torque=%s pub_torque=%s tick[allowed('ss_torque')→pub_torque]=%s"
        % ("def read_torque(" in dsrc, "def pub_torque(" in dsrc, tick_branch))
    zsrc = read_src(ZNODE)
    ss_reg = bool(re.search(r'["\']ss_torque["\']\s*:\s*SSDrivingTorque', zsrc))
    qos_reg = bool(re.search(r'["\']ss_torque["\']\s*:\s*["\']beat["\']', zsrc))
    chk("⑥b zmax_node _SS_TOPICS + QOS_CLASS 含 ss_torque", ss_reg and qos_reg,
        "_SS_TOPICS ss_torque=%s · QOS_CLASS ss_torque=%s" % (ss_reg, qos_reg))
    styp = read_src(STYPS)
    chk("⑥c ss_types 有 SSDrivingTorque (zmax::SSDrivingTorque)", 'class SSDrivingTorque' in styp and
        'typename="zmax::SSDrivingTorque"' in styp, "class + typename 均在 dds/ss_types.py")

    # ───────────────────────── ⑦ 注册表登记 ─────────────────────────
    print("\n[⑦ 注册表登记] live.json ss_torque 记录")
    try:
        lv = json.load(io.open(DS_LIVE, encoding="utf-8"))
        rec = (lv.get("topics") or {}).get("ss_torque")
        if not rec:
            chk("⑦ live.json 登记 ss_torque", False, "未登记 (topics keys=%s)" % list((lv.get("topics") or {}))[:12])
        else:
            age = float(rec.get("age_s", 1e9))
            ok7 = (rec.get("type") == "zmax::SSDrivingTorque" and int(rec.get("matched_pubs") or 0) >= 1
                   and int(rec.get("count") or 0) > 0 and age < 10.0)
            chk("⑦ live.json 登记 ss_torque (type/pub/count/帧龄)", ok7,
                "type=%s matched_pubs=%s count=%s age=%.2fs hz=%s verdict=%s"
                % (rec.get("type"), rec.get("matched_pubs"), rec.get("count"), age,
                   rec.get("hz"), rec.get("verdict")))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑦ live.json 登记 ss_torque", False, "读取失败: %s" % repr(ex)[:120])

    # ───────────────────────── ⑧ 总线追踪可见 ─────────────────────────
    print("\n[⑧ 总线追踪] trace.jsonl zmax/ss_torque 帧 + digest 可解析")
    frames, parsed, last_dg, nleaf_last = 0, 0, None, 0
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
        import canoe_graphic as CG
        with io.open(DS_TRACE, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:                                                 # noqa: BLE001
                    continue
                if o.get("topic") != "zmax/ss_torque":
                    continue
                frames += 1
                last_dg = o.get("digest")
                v = CG.parse_ds_digest(last_dg)
                if v:
                    parsed += 1
                    nleaf_last = len(v)
        chk("⑧a trace.jsonl 帧数 ≥ 5", frames >= 5, "topic=zmax/ss_torque 帧 %d 条" % frames)
        chk("⑧b digest 经 parse_ds_digest 解析出数值叶子", parsed > 0,
            "可解析帧 %d/%d · 末帧叶子 %d 个 (digest 前 180 字符: %s)"
            % (parsed, frames, nleaf_last, (last_dg or "")[:90]))
    except Exception as ex:                                                       # noqa: BLE001
        skip("⑧ 总线追踪 digest 解析", "canoe_graphic 导入/解析失败: %s" % repr(ex)[:120])

    # ───────────────────────── ⑨ DDS 端到端 ─────────────────────────
    print("\n[⑨ DDS 端到端] dds-venv python + dds/zmax_node.py 真订阅 zmax/ss_torque")
    ok9, samples, err9 = dds_subscribe(tries=2)
    if not ok9:
        chk("⑨a DDS 真收 ≥1 条", False, "订阅失败/超时: %s" % err9)
        skip("⑨b DDS torque/phi 与 tap 最后一行逐位一致", "⑨a 未收到样本")
    else:
        s0 = samples[0]
        chk("⑨a DDS 真收 ≥1 条", True,
            "收到 %d 条 · 首帧 ts=%.3f scene=%s ‖T‖=%.3f" % (len(samples), s0["ts"], s0["scene"],
                                                             float(np.linalg.norm(s0["torque"]))))
        # 订阅后立刻再读 tap 最后一行 (发布器 ~10Hz 实时刷新)
        d2 = read_tap_last(TAP)
        t_dds = np.asarray(s0["torque"], float)
        t_tap = np.asarray(d2["torque"], float)
        e_t = float(np.max(np.abs(t_dds - t_tap)))
        e_p = abs(float(s0["phi"]) - float(d2["phi"]))
        found_ts = any(abs(float(s["ts"]) - float(d2["ts"])) < 1e-9 for s in samples)
        chk("⑨b DDS torque/phi 与 tap 最后一行逐位一致", e_t <= 1e-9 and e_p <= 1e-9,
            "torque 最大偏差 %.3e · phi 偏差 %.3e (ts 命中=%s · tap ts=%.3f)"
            % (e_t, e_p, found_ts, d2["ts"]))

    # ───────────────────────── ⑩ 时效性 ─────────────────────────
    print("\n[⑩ 时效性] 发布器活体 + tap 新鲜 + 守护过期阈值 (mtime 反造假)")
    pid_ok, pid_ev = False, "pid 锁不存在"
    if os.path.isfile(PIDF):
        try:
            pid = int(io.open(PIDF, encoding="utf-8").read().strip())
            os.kill(pid, 0)
            cl = read_src("/proc/%d/cmdline" % pid).replace("\x00", " ").strip()
            pid_ok = "tdrive_bus.py" in cl
            pid_ev = "pid=%d 活 · cmd=%s" % (pid, cl[:70])
        except Exception as ex:                                                   # noqa: BLE001
            pid_ev = "pid 锁存在但进程不可用: %s" % repr(ex)[:80]
    chk("⑩a 发布器 pid 锁存在且进程活", pid_ok, pid_ev)
    # 帧龄必须对**当前** tap 测 (脚本启动时的快照会被 ②/⑨ 的耗时拖旧 ⇒ 那样测的是脚本耗时, 不是发布器活性)
    d_now = read_tap_last(TAP)
    ts_age = time.time() - float(d_now["ts"])
    mtime_age = time.time() - os.path.getmtime(TAP)
    chk("⑩b tap 最后一行 ts 帧龄 < 3s", ts_age < 3.0,
        "现场重读: ts 帧龄 %.3fs · 文件 mtime 帧龄 %.3fs (启动快照帧龄 %.1fs 仅作对照)"
        % (ts_age, mtime_age, time.time() - float(d["ts"])))
    stale_const = "STALE_TORQUE_S" in dsrc and "3.0" in dsrc and "age > STALE_TORQUE_S" in dsrc
    m = re.search(r'STALE_TORQUE_S\s*=\s*float\(os\.environ\.get\([^)]*\)\)', dsrc)
    chk("⑩c 守护 STALE_TORQUE_S=3.0 生效 (读源码字串)", stale_const and bool(m),
        "%s · 过期分支 'age > STALE_TORQUE_S'" % (m.group(0) if m else "未找到常量定义"))

    # ───────────────────────── ⑪ 单位/口径自证 ─────────────────────────
    print("\n[⑪ 单位/口径] unit + unit_note + 未接通道如实说明")
    un = str(d.get("unit_note") or "")
    chk("⑪a payload unit=N·m 且 unit_note 含「未做扭矩计量学标定」",
        d.get("unit") == "N·m" and bool(un) and "未做扭矩计量学标定" in un,
        "unit=%s · unit_note %d 字, 含标定声明=%s" % (d.get("unit"), len(un), "未做扭矩计量学标定" in un))
    tor_src = read_src(TOPICS_PY)
    tprov = ""
    try:
        from lerobot.dataspace import topics as T2
        tprov = str((T2.TOPICS.get("ss_torque") or {}).get("provenance") or "")
    except Exception:                                                             # noqa: BLE001
        pass
    payload_has = any(s in json.dumps(d, ensure_ascii=False) for s in ("1000", "100Hz", "监控通道", "电机通道"))
    prov_has = any(s in tprov for s in ("1000", "100Hz", "监控通道", "电机通道"))
    chk("⑪b spec 未接通道(1000Hz/100Hz) 在 payload 或 topics.py provenance 如实说明",
        payload_has or prov_has,
        "payload 提及=%s · topics.py provenance 提及=%s (仅生产者 CLI 帮助 tools/tdrive_bus.py:--hz 有 1000Hz 说明)"
        % (payload_has, prov_has))

    # ───────────────────────── ⑫ 零回归 ─────────────────────────
    print("\n[⑫ 零回归] 其余话题 / 画布 / 任务绑定 / 融合定位判据")
    try:
        lv2 = json.load(io.open(DS_LIVE, encoding="utf-8"))
        bus = [k for k in (lv2.get("topics") or {}) if k != "ss_torque"]
        from lerobot.dataspace import topics as T3
        missing = [k for k in bus if k not in T3.TOPICS]
        chk("⑫a 其余总线话题仍在 (TOPICS)", len(bus) >= 9 and not missing,
            "其余 %d 个: %s · 缺失=%s" % (len(bus), bus, missing or "无"))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑫a 其余总线话题仍在", False, "读取失败: %s" % repr(ex)[:120])
    try:
        cnv = json.load(io.open(CANVAS, encoding="utf-8"))
        nn, nl = len(cnv.get("nodes") or []), len(cnv.get("links") or [])
        chk("⑫b 画布 89 节点 / 184 连线未变", nn == 89 and nl == 184,
            "nodes=%d links=%d (%s)" % (nn, nl, os.path.relpath(CANVAS, ROOT)))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑫b 画布节点/连线计数", False, "读取失败: %s" % repr(ex)[:120])
    try:
        rc, out, err = run([PY, os.path.join(ROOT, "tools", "ss_task_bind.py"), "--check"], timeout=120)
        chk("⑫c ss_task_bind.py --check 通过", rc == 0 and "✅" in out,
            "exit=%d · %s" % (rc, (out.strip().splitlines()[-1] if out.strip() else err[:80])[:90]))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑫c ss_task_bind --check", False, "运行失败: %s" % repr(ex)[:120])
    try:
        rc, out, err = run([PY, os.path.join(ROOT, "tools", "verify_localization_mapping.py")],
                           timeout=560, env={"QT_QPA_PLATFORM": "offscreen"})
        mcon = re.search(r"结论:\s*(\d+)\s*项通过\s*·\s*(\d+)\s*项未过\s*·\s*(\d+)\s*项未验证", out)
        if mcon:
            p, f, s = int(mcon.group(1)), int(mcon.group(2)), int(mcon.group(3))
            chk("⑫d verify_localization_mapping.py 仍 23/23", p == 23 and f == 0,
                "结论: %d 通过 / %d 未过 / %d 未验证 (exit=%d)" % (p, f, s, rc))
        else:
            chk("⑫d verify_localization_mapping.py 仍 23/23", False,
                "未解析到结论行 (exit=%d, tail=%s)" % (rc, (out or err)[-90:]))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑫d verify_localization_mapping 23/23", False, "运行失败: %s" % repr(ex)[:120])

    # ───────────────────────── ⑬ 标识信息 (老倪 2026-10-14) ─────────────────────────
    #  「流形引擎的输出 topic 看到: 正在执行的任务 / 产品质数 / 主参数 等标识信息」
    #  判据口径: 载荷里的标识必须与**各自唯一依据**逐字段一致 (不从载荷反推载荷), 且必须真在 DDS 话题上。
    print("\n[⑬ 标识信息] 任务 / 场景 / 产品质数 / 主参数 —— 与各自唯一依据逐字段核对")
    idb = d.get("identity") or {}
    try:
        bind = json.load(io.open(os.path.join(ROOT, "config", "ss_task_binding.json"), encoding="utf-8"))
        tasks = json.load(io.open(os.path.join(ROOT, "config", "tasks", "tasks.json"), encoding="utf-8"))
        tsk = next((t for t in (tasks.get("tasks") or [])
                    if str(t.get("task_id")) == str(bind.get("active_task"))), {})
        bad = []
        if str(idb.get("task_id")) != str(bind.get("active_task")):
            bad.append("task_id %r ≠ 绑定 %r" % (idb.get("task_id"), bind.get("active_task")))
        if str(idb.get("task_name")) != str(tsk.get("name")):
            bad.append("task_name %r ≠ tasks.json %r" % (idb.get("task_name"), tsk.get("name")))
        if str(idb.get("site")) != str(tsk.get("site")):
            bad.append("site %r ≠ %r" % (idb.get("site"), tsk.get("site")))
        chk("⑬a 标识-任务: task_id/task_name/site 与 config/ss_task_binding.json + tasks.json 一致",
            bool(idb) and not bad,
            ("%s · %s · %s" % (idb.get("task_id"), idb.get("task_name"), idb.get("site"))) if not bad
            else "; ".join(bad)[:150])
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑬a 标识-任务 ↔ 唯一依据", False, "核对失败: %s" % repr(ex)[:120])
    try:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.manifold import prime_structure as _PS
        pd = _PS.load_products() or {}
        pid = str(pd.get("active_product"))
        pr = (pd.get("products") or {}).get(pid) or {}
        b2 = []
        if str(idb.get("product_id")) != pid:
            b2.append("product_id %r ≠ %r" % (idb.get("product_id"), pid))
        if int(idb.get("product_prime") or -1) != int(pr.get("prime") or -2):
            b2.append("product_prime %r ≠ 唯一依据 %r" % (idb.get("product_prime"), pr.get("prime")))
        if str(idb.get("version_segment")) != str(pr.get("version_segment")):
            b2.append("version_segment %r ≠ %r" % (idb.get("version_segment"), pr.get("version_segment")))
        chk("⑬b 标识-产品: 产品 id / **产品质数** / 版本段 与 config/platform/zmax_product.json 一致",
            bool(idb) and not b2,
            ("%s · 产品质数 %s · 版本段 %s · 能力 %s 项" % (idb.get("product_id"), idb.get("product_prime"),
                                                     idb.get("version_segment"), idb.get("n_capabilities")))
            if not b2 else "; ".join(b2)[:150])
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑬b 标识-产品 ↔ 唯一依据", False, "核对失败: %s" % repr(ex)[:120])
    try:
        mcfg = json.load(io.open(os.path.join(ROOT, "config", "calib", "zmax_manifold.json"), encoding="utf-8"))
        mp = idb.get("main_params") or {}
        b3 = []
        if abs(float(mp.get("metric_M") or -1) - float(mcfg.get("M") or -2)) > 1e-12:
            b3.append("metric_M %r ≠ 唯一依据 M %r" % (mp.get("metric_M"), mcfg.get("M")))
        if int(mp.get("metric_dim") or -1) != int((mcfg.get("metric") or {}).get("dim") or -2):
            b3.append("metric_dim %r ≠ %r" % (mp.get("metric_dim"), (mcfg.get("metric") or {}).get("dim")))
        if str(mp.get("metric_mode")) != str((mcfg.get("metric") or {}).get("mode")):
            b3.append("metric_mode %r ≠ %r" % (mp.get("metric_mode"), (mcfg.get("metric") or {}).get("mode")))
        if int(d.get("metric_dim") or -1) != int(mp.get("metric_dim") or -2):
            b3.append("载荷 metric_dim %r ≠ 标识 metric_dim %r" % (d.get("metric_dim"), mp.get("metric_dim")))
        chk("⑬c 标识-主参数: M / dim / mode 与 config/calib/zmax_manifold.json 一致, 且与载荷度量同维",
            not b3,
            ("M=%s · dim=%s · mode=%s · 形状 diag=%s · 任务工艺参数 %d 项" % (
                mp.get("metric_M"), mp.get("metric_dim"), mp.get("metric_mode"),
                mp.get("metric_diag"), len(mp.get("task_params") or {}))) if not b3 else "; ".join(b3)[:170])
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑬c 标识-主参数 ↔ 唯一依据", False, "核对失败: %s" % repr(ex)[:120])
    # ⑬d 必须**真在 DDS 话题上** (不是只在 tap 文件里)
    try:
        ok9, samp9, err9 = dds_subscribe()
    except Exception as ex:                                                       # noqa: BLE001
        ok9, samp9, err9 = False, [], repr(ex)
    if ok9 and samp9:
        s0 = samp9[0]
        same = (str(s0.get("task_id")) == str(idb.get("task_id"))
                and int(s0.get("product_prime") or -1) == int(idb.get("product_prime") or -2)
                and abs(float(s0.get("m_scale") or -1) - float(mp.get("metric_M") or -2)) < 1e-12)
        chk("⑬d DDS 话题 zmax/ss_torque 上真带标识 (task_id/产品质数/主参数 M 与 tap 逐字段同值)", same,
            "话题样本: task=%s · 产品质数=%s · M=%s · task_name=%s" % (
                s0.get("task_id"), s0.get("product_prime"), s0.get("m_scale"), s0.get("task_name")))
        chk("⑬e identity_json 在话题上是完整块 (含 唯一依据 出处, 可回读复核)",
            len(str(s0.get("identity_json") or "")) > 80 and "src" in str(s0.get("identity_json")),
            "identity_json %d 字符 · 首 60: %s" % (len(str(s0.get("identity_json"))),
                                                   str(s0.get("identity_json"))[:60]))
    else:
        skip("⑬d/⑬e 标识真在 DDS 话题上", "DDS 未收到样本: %s" % err9)
    try:
        tp = io.open(os.path.join(ROOT, "src", "lerobot", "dataspace", "topics.py"), encoding="utf-8").read()
        blk = tp.split('"ss_torque": {', 1)[-1].split('"ds_dataset"', 1)[0]
        need = ["task_id", "product_prime", "m_scale", "identity_json"]
        miss = [k for k in need if k not in blk]
        dm = io.open(os.path.join(ROOT, "tools", "dds", "ss_daemon.py"), encoding="utf-8").read()
        dmiss = [k for k in ("task_id", "product_prime", "identity_json") if k not in dm]
        chk("⑬f 标识字段已登记 (topics.py key_fields + 守护 pub_torque 转发)", not miss and not dmiss,
            "key_fields 缺=%s · 守护缺=%s" % (miss or "无", dmiss or "无"))
    except Exception as ex:                                                       # noqa: BLE001
        chk("⑬f 标识字段登记", False, "读取失败: %s" % repr(ex)[:120])

    # ───────────────────────── 结论 ─────────────────────────
    print("\n" + "═" * 104)
    print("结论: %d 项通过 · %d 项未过 · %d 项未验证 · 用时 %.1fs" % (len(OK), len(BAD), len(SKIP), time.time() - t0))
    for n, e in BAD:
        print("  ❌ %s — %s" % (n, e))
    for n, e in SKIP:
        print("  ⏭ %s — %s" % (n, e))
    print("═" * 104)
    out = os.path.join(ROOT, "reports", "driving_torque_judge.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    verdicts = ([{"item": n, "ok": True, "evidence": e} for n, e in OK]
                + [{"item": n, "ok": False, "evidence": e} for n, e in BAD])
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "subject": "T_drive = M·(−∇Φ) → zmax/ss_torque",
                   "pass": len(OK), "fail": len(BAD), "skip": [n for n, _ in SKIP],
                   "unverified": [{"item": n, "reason": e} for n, e in SKIP],
                   "ok": [n for n, _ in OK], "bad": [n for n, _ in BAD], "verdicts": verdicts}, f,
                  ensure_ascii=False, indent=1)
    print("报告: %s" % out)
    return 0 if not BAD else 1


if __name__ == "__main__":
    raise SystemExit(main())
