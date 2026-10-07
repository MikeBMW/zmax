#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifold_energy_probe.py — 流形引擎 · 能量探针 (2026-10-07)

把「一次 pipeline 训练迭代」的每一层**真测**折算成发动机物理量, 并落盘给全局数据空间。

    输入功率 P_in (W) ── nvidia-smi power.draw 全程采样 (真瓦特)
    扭矩 τ (CJ/循环) ── 该层日志里**真实损失/势能序列**的每循环下降量
    转速 ω (Hz)      ── 实测: L3 用日志里的 updt_s(步时), 其余用 步数/时长
    输出功率 P = τ·ω 能量 E = τ·ω·secs     效率 η = E / (P_in·secs)
    总能量 E_total = Σ E_layer   ← 流形引擎节点可观测量

四件事 (缺一样就如实标注, 绝不编数):
  ① 采样  ② 解析  ③ 折算  ④ 落盘 (tap JSONL = 数据空间记录; report JSON = 证据)

用法:
    # ① 跑一轮完整迭代 (全部层级) 并全程测能
    gui-venv311/bin/python tools/manifold_energy_probe.py run --only L4,L3,L2,LLM --steps 30 --yolo-epochs 2
    # ② 只折算已有的一轮 (不重跑, 零 GPU 开销)
    gui-venv311/bin/python tools/manifold_energy_probe.py ingest --run reports/joint_train_20261007_184356
    # ③ 看规格书
    gui-venv311/bin/python tools/manifold_energy_probe.py spec
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFOLD = os.path.join(ROOT, "src", "lerobot", "manifold")
SS_LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
REPORTS = os.path.join(ROOT, "reports")

sys.path.insert(0, MANIFOLD)
from energy_manifold import (EnergyManifold, LEVEL_STRUCT, energy_spec,  # noqa: E402
                             read_input_power_w)


# ══════════════════════════════════════════════════════════════════════════════
# ① 采样: GPU 电功率 (输入侧, 真瓦特)
# ══════════════════════════════════════════════════════════════════════════════
class PowerSampler:
    """后台线程按 hz 采 GPU 电功率, 记时间戳 (供按阶段窗口切片)。"""

    def __init__(self, hz: float = 2.0):
        self.hz, self.samples, self._stop, self._th = hz, [], threading.Event(), None

    def start(self):
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            w, _ = read_input_power_w()
            self.samples.append((time.time(), w))
            self._stop.wait(max(0.05, 1.0 / self.hz))

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=3)
        return self.samples


def window_power_w(samples, t0: float, t1: float) -> float:
    """阶段窗口内平均功率 (W); 窗口内无有效样本 → -1.0 (不猜)。"""
    v = [w for (t, w) in samples if t0 <= t <= t1 and w and w > 0]
    return round(sum(v) / len(v), 3) if v else -1.0


# ══════════════════════════════════════════════════════════════════════════════
# ② 解析: 各层真实日志 → 损失/势能序列 + 循环数 + 实测步时
# ══════════════════════════════════════════════════════════════════════════════
def _read(path: str, max_mb: float = 8.0) -> str:
    try:
        with open(path, "rb") as f:
            b = f.read(int(max_mb * 1e6))
        return b.decode("utf-8", "ignore")
    except Exception:                                                            # noqa: BLE001
        return ""


def parse_l3(log: str) -> dict:
    """lerobot 训练行: `step:10 smpl:20 ep:0 epch:0.00 loss:0.242 grdn:0.610 lr:… updt_s:1.469`"""
    raw, steps, updts = [], [], []
    for m in re.finditer(r"step:(\d+)[^\n]*?loss:([0-9.eE+-]+)[^\n]*?(?:updt_s:([0-9.eE+-]+))?", log):
        steps.append(int(m.group(1)))
        try:
            raw.append(float(m.group(2)))
        except ValueError:
            continue
        if m.group(3):
            try:
                updts.append(float(m.group(3)))
            except ValueError:
                pass
    out = {"potential": list(raw), "raw": list(raw), "metric": "loss (lerobot 逐步)",
           "cycles": float(max(steps) if steps else len(raw)), "omega_hz_measured": -1.0,
           "src": f"L3 日志 lerobot 训练行 ({len(raw)} 行, 势能=loss)", "note": ""}
    if updts:
        mu = sum(updts) / len(updts)
        out["omega_hz_measured"] = round(1.0 / mu, 4) if mu > 0 else -1.0
        out["note"] = f"ω 实测自 updt_s 均值 {mu:.3f}s/步 ⇒ {out['omega_hz_measured']}Hz"
    if not raw:
        out["note"] = (out["note"] + " | 未解析到 loss 行 ⇒ τ=0 (如实)").strip(" |")
    return out


def parse_l4(log: str) -> dict:
    """INTACT (lightning): 进度条给 it/s 与迭代数; epoch 汇总行给 validate/loss (负值, 越负越好)。"""
    log_n = re.sub(r"\x1b\[[0-9;]*m", "", log)                       # 去 ANSI, 表行才能正则
    its, rate = 0, -1.0
    m = re.search(r"(\d+)/(\d+)\s+[\d:]+[^\n]*?([\d.]+)it/s", log_n) or \
        re.search(r"(\d+)/(\d+)[^\n]*?([\d.]+)(?:it|s)/s", log_n)
    if m:
        its, rate = int(m.group(2)), float(m.group(3))               # 总迭代数, 实测 it/s
    raw = []
    # ⚠️ 2026-10-07 实测: INTACT 的 validate/loss **两种格式都会出现** ——
    #   rich 表格行 `validate/loss       |  -3.8152334690093994  |`
    #   lightning 汇总 `validate/loss: -3.815 | validate/pred_loss: …`
    #   原来只认进度条 `[Epoch x/y] … | validate/loss:` ⇒ 一次训练只抓到 1 个点 ⇒ τ 只能记 0。
    #   现在统一收 (| 或 : 后面跟数值), 并按出现顺序去重 (相邻重复只留一个)。
    for x in re.findall(r"validate/loss\s*[|:]\s*(-?[\d.eE+-]+)", log_n):
        try:
            v = float(x)
        except ValueError:
            continue
        if not raw or abs(v - raw[-1]) > 1e-12:
            raw.append(v)
    if not raw:                                                      # 备选: 进度条式
        raw = [float(x) for x in re.findall(r"\[Epoch \d+/\d+\][^\n|]*\|\s*validate/loss:\s*(-?[\d.eE+-]+)", log_n)]
    pot = [-x if x < 0 else x for x in raw]                          # 口径: 该指标越负越好 ⇒ 势能 = −loss
    out = {"potential": pot, "raw": raw, "metric": "validate/loss (INTACT; 势能=−loss)",
           "cycles": float(its or max(len(pot), 1)), "omega_hz_measured": rate,
           "src": f"L4 日志 lightning 汇总 ({len(raw)} 点) + 进度条 ({its} 迭代 × {rate} it/s)",
           "note": ("ω 实测自进度条 it/s" if rate > 0 else "进度条未解析到 it/s ⇒ ω 用 迭代数/时长") +
                   ("" if len(pot) >= 2 else " | 只有 1 个损失点 ⇒ 无下降区间可测, τ=0 (如实; 跑 ≥2 epoch 才有 τ)")}
    return out


def parse_l2(log: str) -> dict:
    """YOLO (ultralytics): 每 epoch 一行 `all  N  M  0.989  1  0.995  0.726` → 势能 = 1 − mAP50。"""
    log_n = re.sub(r"\x1b\[[0-9;]*m", "", log).replace("\x1b[K", "")
    maps = [float(x) for x in re.findall(r"^\s*all\s+\d+\s+\d+\s+[\d.]+\s+[\d.]+\s+([\d.]+)", log_n, re.M)]
    pot = [round(1.0 - x, 6) for x in maps]                           # mAP 升 ⇒ 势能降
    out = {"potential": pot, "raw": maps, "metric": "mAP50 (势能 = 1 − mAP50)",
           "cycles": float(max(len(pot), 1)), "omega_hz_measured": -1.0,
           "src": f"L2 日志 ultralytics 每 epoch 验证行 ({len(pot)} 点)",
           "note": (f"mAP50 首 {maps[0]:.4f} → 末 {maps[-1]:.4f}" if len(maps) >= 2 else
                    (f"mAP50 {maps[0]:.4f} (单点 ⇒ τ=0, 如实)" if maps else "未解析到验证行 ⇒ τ=0 (如实)")) +
                   "; 循环数=epoch 数"}
    return out


PARSERS = {"L4": parse_l4, "L3": parse_l3, "L2": parse_l2}


def parse_stage_log(path: str, stage: str) -> dict:
    if not path or not os.path.exists(path):
        return {"potential": [], "raw": [], "metric": "", "cycles": 0.0, "omega_hz_measured": -1.0,
                "src": "", "note": "日志不存在 ⇒ τ=0 (如实)"}
    fn = PARSERS.get(stage)
    return fn(_read(path)) if fn else {"potential": [], "raw": [], "metric": "", "cycles": 0.0,
                                      "omega_hz_measured": -1.0, "src": "",
                                      "note": f"{stage} 无解析器 (仅体检类) ⇒ τ=0"}


# ══════════════════════════════════════════════════════════════════════════════
# ③ 折算 + ④ 落盘
# ══════════════════════════════════════════════════════════════════════════════
LORA_STAGE = {"L4": True, "L3": True, "L2": False, "L5": False}


def level_from_parse(pr: dict) -> float:
    """能力水平 c ∈[0,1] (真实指标归一) —— 用于**存量能量**(基座在场就有)。

    · L2: c = mAP50 末值 (检测能力的绝对水平)
    · L3/L4: c = 1 − 末势能/首势能 (本轮把误差压到多低; 单点或势能≤0 ⇒ -1 如实)
    """
    pot, raw = pr.get("potential") or [], pr.get("raw") or []
    if not pot:
        return -1.0
    if pr.get("metric", "").startswith("mAP50"):
        return round(max(0.0, min(1.0, raw[-1])), 6)
    if len(pot) >= 2 and abs(pot[0]) > 1e-12:
        return round(max(0.0, min(1.0, 1.0 - abs(pot[-1]) / abs(pot[0]))), 6)
    return -1.0


def ingest_run(run_dir: str, power_samples: list[tuple[float, float]] | None = None,
               publish: bool = True, tag: str = "") -> dict:
    """把一轮真实 pipeline 迭代 (stages.jsonl + 各层日志 + 功率采样) 折算成引擎能量。"""
    sj = os.path.join(run_dir, "stages.jsonl")
    if not os.path.exists(sj):
        return {"ok": False, "why": f"缺 {sj}"}
    rows = [json.loads(l) for l in open(sj, encoding="utf-8") if l.strip()]
    em = EnergyManifold()
    stages_detail = []
    for r in rows:
        layer = r.get("stage")
        secs = float(r.get("secs") or 0.0)
        log = r.get("log") or ""
        pr = parse_stage_log(log, layer)
        # 输入功率: 优先用窗口内实测; 无采样 → 退回整轮均值; 再没有 → -1 (不猜)
        t1 = time.time() if not rows else None
        w = -1.0
        if power_samples:
            t0 = float(r.get("t_start") or 0.0)
            if t0:
                w = window_power_w(power_samples, t0, t0 + secs)
            else:
                w = (sum(x[1] for x in power_samples if x[1] > 0) /
                     max(1, len([1 for x in power_samples if x[1] > 0])))
        if w > 0:
            em.note_power([w], f"阶段窗口实测 ({run_dir.split('/')[-1]})")
        # LoRA: 真适配器文件存在 → 记 rank/参数量 (结构量; A/B 实测优先, 无则如实标注)
        lora = None
        for f in (glob.glob(os.path.join(run_dir, "lora_*.pt")) if LORA_STAGE.get(layer) else []):
            try:
                sz = os.path.getsize(f) / 1e6
            except OSError:
                continue
            lora = {"r": int(os.environ.get("ZMAX_LORA_R", 8)), "params_m": round(sz / 4.0 / 1e6, 4),
                    "targets": os.environ.get("ZMAX_LORA_TARGETS", ""), "file": os.path.basename(f)}
            break
        le = em.absorb_stage(layer, secs=secs or 1.0, cycles=pr.get("cycles") or None,
                            loss_series=pr.get("potential") or None,
                            level_c=(level_from_parse(pr) if level_from_parse(pr) >= 0 else None),
                            lora=lora, src=pr.get("src", ""),
                            note=(f"指标 {pr.get('metric') or '—'}" if pr.get("metric") else "") +
                                 (" · " + pr["note"] if pr.get("note") else "") +
                                 ("" if r.get("rc") == 0 else f" · 阶段 rc={r.get('rc')} (未跑完, 能量按已有段计)"),
                            )
        if pr.get("omega_hz_measured") and pr["omega_hz_measured"] > 0:
            # ⚠️ 只换"转速读数"与输出功率; **能量保持 τ·循环数**(累计功), 不能改成 τ·ω_实测·秒
            #    —— 实测步率与 循环数/时长 不是同一个量, 混用会把能量算错 (实测踩过)。
            le.omega_hz = pr["omega_hz_measured"]
            le.p_out_cjs = round(le.tau_cj * le.omega_hz, 9) if le.tau_cj > 0 else -1.0
            le.note = (le.note + f" · ω 读数用实测 {le.omega_hz}Hz (能量仍按 τ×循环数={le.cycles:.0f})").strip(" ·")
        if le.w_in_j > 0:
            le.eta_cjj = round(le.energy_cj / le.w_in_j, 9)
        stages_detail.append({"stage": layer, "rc": r.get("rc"), "secs": secs,
                              "log": os.path.relpath(log, ROOT) if log else "",
                              "parsed": {k: v for k, v in pr.items() if k != "loss_series"},
                              "energy": le.as_dict(), "p_in_window_w": w})
    # L5: pipeline 里只有 LLM 体检 (无训练) → 若没进场就补一条 0 并标注
    if "L5" not in em.layers:
        from energy_manifold import LayerEnergy
        em.layers["L5"] = LayerEnergy(layer="L5", shell_n=4,
                                      feasible_r=LEVEL_STRUCT["L5"]["feasible_r"],
                                      src="pipeline LLM 体检档", note="L5 本轮无训练/未接入 ⇒ 能量 0 (如实)")
    em.t0 = time.time()
    t = em.total()
    payload = em.topic_payload(node="流形引擎", state="train", run=os.path.basename(run_dir),
                               stages=[[d["stage"], d["rc"], round(d["secs"], 1)] for d in stages_detail])
    report = {"ok": True, "version": energy_spec()["version"], "run": run_dir,
              "generated_at": time.strftime("%F %T"), "spec": energy_spec()["physical"],
              "shells": em.shells(), "total": t, "payload": payload, "stages": stages_detail,
              "power_samples_n": len(power_samples or []),
              "power_src": em.power_src or "无采样 (η=-1 如实)"}

    # 落盘 (记录 = 可被观测/被测量)
    ts = time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(SS_LIVE, exist_ok=True)
    os.makedirs(REPORTS, exist_ok=True)
    tap = os.path.join(SS_LIVE, f"energy_{ts}{('_' + tag) if tag else ''}.jsonl")
    with open(tap, "a", encoding="utf-8") as f:
        # ⚠️ 顺序铁律: 先分层行、**最后一行才是 payload** —— 守护用 _last_line() 读最后一行,
        #    倒过来写会让守护读到"某一层"而不是总量 (实测踩过: n_levels=0)。
        for d in stages_detail:
            f.write(json.dumps({"kind": "layer", "run": os.path.basename(run_dir),
                                "ts": payload["ts"], **d["energy"]}, ensure_ascii=False) + "\n")
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    rp = os.path.join(REPORTS, f"manifold_energy_{ts}{('_' + tag) if tag else ''}.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    report["tap"] = tap
    report["report"] = rp
    return report


# ══════════════════════════════════════════════════════════════════════════════
# run: 跑一轮完整迭代 (全部层级) 并全程测能
# ══════════════════════════════════════════════════════════════════════════════
def run_iteration(steps: int, yolo_epochs: int, only: str, extra: list[str]) -> dict:
    ts = time.strftime("%Y%m%d_%H%M%S")
    tag = "iter"
    py = os.path.join(ROOT, "gui-venv311", "bin", "python")
    py = py if os.path.exists(py) else sys.executable
    cmd = [py, os.path.join(ROOT, "tools", "joint_train_all.py"),
           "--steps", str(steps), "--yolo-epochs", str(yolo_epochs)]
    if only:
        cmd += ["--only", only]
    cmd += extra
    print("▶ 跑一轮 pipeline 迭代 (全程采 GPU 电功率):")
    print("   " + " ".join(cmd))
    ps = PowerSampler(hz=2.0).start()
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         bufsize=1, text=True)
    mroot = None
    for line in iter(p.stdout.readline, ""):
        sys.stdout.write(line)
        sys.stdout.flush()
        m = re.search(r"证据目录 (\S+)", line)
        if m and mroot is None:
            mroot = os.path.join(ROOT, m.group(1))
    p.wait()
    time.sleep(0.5)
    samples = ps.stop()
    # 💾 存下功率采样 (jsonl: [t, W]) —— 让同一次迭代可**离线复算**(ingest --power-file),
    #    也是"被测量/被记录"的证据链 (2026-10-07 加)。
    pw_path = os.path.join(REPORTS, f"power_{ts}{('_' + tag) if tag else ''}.jsonl")
    try:
        with open(pw_path, "w", encoding="utf-8") as f:
            for _t, _w in ps.samples:
                f.write(json.dumps([_t, _w]) + "\n")
    except Exception:                                                              # noqa: BLE001
        pw_path = ""
    print(f"⏹ 迭代结束 rc={p.returncode} 用时 {time.time()-t0:.0f}s · 功率采样 {len(samples)} 点")
    # 给每个阶段打上 t_start (由 stages.jsonl 的顺序 + 耗时倒推: 用日志 mtime 作锚)
    if mroot and os.path.exists(os.path.join(mroot, "stages.jsonl")):
        rows = [json.loads(l) for l in open(os.path.join(mroot, "stages.jsonl"), encoding="utf-8") if l.strip()]
        t = t0
        for r in rows:
            r["t_start"] = t
            t += float(r.get("secs") or 0.0)
        with open(os.path.join(mroot, "stages.jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return ingest_run(mroot, samples, tag="iter")
    return {"ok": False, "why": "未找到证据目录/stages.jsonl"}


# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="流形引擎 · 能量探针")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("run", help="跑一轮完整 pipeline 迭代并测能")
    p1.add_argument("--steps", type=int, default=30)
    p1.add_argument("--yolo-epochs", type=int, default=2)
    p1.add_argument("--only", default="L4,L3,L2,LLM")
    p1.add_argument("rest", nargs="*")
    p2 = sub.add_parser("ingest", help="只折算已有的一轮 (不重跑)")
    p2.add_argument("--run", required=True)
    p2.add_argument("--power-file", default="")
    sub.add_parser("spec", help="打印规格书")
    a, _extra = ap.parse_known_args()
    # ⚠️ 透传口径 (2026-10-07 实测): 想给 joint_train_all 传额外参数必须放在 **`--` 之后**:
    #      probe.py run --steps 30 -- --l4-epochs 2      ← rest=["--l4-epochs","2"] 顺序正确
    #    不能直接写 `--l4-epochs 2`: argparse 会把"选项"丢进未知集合、"值 2"留在 rest,
    #    拼出来变成 `--l4-epochs 2 --l4-epochs` ⇒ joint_train_all 报 expected one argument。
    if _extra:
        print("⚠️ 未知参数 %r 已忽略 —— 要透传给 joint_train_all 请放在 `--` 之后 "
              "(例: run --steps 30 -- --l4-epochs 2)" % (_extra,))
        return 2

    if a.cmd == "spec":
        print(json.dumps(energy_spec(), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "run":
        rep = run_iteration(a.steps, a.yolo_epochs, a.only, a.rest)
    elif a.cmd == "ingest":
        rd = a.run if os.path.isabs(a.run) else os.path.join(ROOT, a.run)
        samples = []
        if a.power_file and os.path.exists(a.power_file):
            samples = [tuple(json.loads(l)) for l in open(a.power_file) if l.strip()]
        rep = ingest_run(rd, samples, tag="ingest")
    else:
        ap.print_help()
        return 0

    if not rep.get("ok"):
        print("❌ " + str(rep.get("why")))
        return 1
    em_tbl = rep["total"]
    print("\n" + "═" * 78)
    print(f"⚡ 流形引擎能量 (轮次 {os.path.basename(rep['run'])})")
    print("═" * 78)
    print(f"{'壳':<3}{'层':<5}{'存量CJ':>11}{'增量CJ':>11}{'层能量CJ':>11}{'累积CJ':>11}"
          f"{'τ(CJ/循环)':>13}{'ω(Hz)':>8}{'可行域':>7}{'占比':>7}{'η(CJ/J)':>11}")
    for s in rep["shells"]:
        le = rep["total"]["layers"].get(s["layer"], {})
        print(f"{s['shell_n']:<3}{s['layer']:<5}{s['e_standing_cj']:>11.4f}{s['e_work_cj']:>11.4f}"
              f"{s['e_layer_cj']:>11.4f}{s['e_cum_cj']:>11.4f}"
              f"{le.get('tau_cj', 0):>13.8f}{le.get('omega_hz', -1):>8.3f}{s['feasible_r']:>7.2f}"
              f"{(le.get('share', -1) if le.get('share', -1) >= 0 else -1):>7.3f}"
              f"{(le.get('eta_cjj', -1) if le.get('eta_cjj', -1) >= 0 else -1):>11.6f}")
    print("─" * 78)
    print(f"总能量 E_total = {em_tbl['e_total_cj']:.6f} CJ  = 存量 {em_tbl['e_standsum_cj']:.6f} + "
          f"做功 {em_tbl['e_worksum_cj']:.6f}")
    print(f"  其中基础 L2 能量 {em_tbl['e_base_cj']:.6f} CJ · LoRA 增压 {em_tbl['e_boost_cj']:.6f} CJ")
    print(f"输入功率 {em_tbl['p_in_w']} W · 电功 {em_tbl['w_in_j']} J · 整机效率 η={em_tbl['eta_total_cjj']} CJ/J"
          f" ({rep['power_src']})")
    print(f"自检: Σ分层==总量 {em_tbl['sum_ok']} · 壳层单调 {rep['shells'][0]['shell_monotonic_ok']}"
          f" · 可行域收窄 {rep['shells'][0]['feasible_narrowing_ok']} · 活跃能级 {em_tbl['n_levels_active']}/4")
    print(f"📼 记录: {os.path.relpath(rep['tap'], ROOT)}")
    print(f"📄 报告: {os.path.relpath(rep['report'], ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
