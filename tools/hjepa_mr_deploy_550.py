#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚀 hjepa_mr_deploy_550.py — H-JEPA-MR 三档部署链 (老倪 2026-10-23)

老倪原话: 「部署到 550C 自主进化, 结果返回 550B, 编码, 自动训练 550A」

三档口径 (skill zmax-product-dev-profiles):
  550C = Intel (端侧) — 跑几何分支自主进化, 适应度是几何自洽性 (无标注)
  550B = 4060 (桥梁) — 进化结果回传落盘 + 上屏
  550A = 4060 (开发) — 用回传的 HP 在**真机位姿**上训几何分支

三个子脚本各自独立文件 (不再把源码塞进字符串, 那会把引号搞乱):
  tools/hjepa_mr_evolver_intel.py   550C 进化器
  tools/hjepa_mr_train_550a.py      550A 训练器
  tools/hjepa_mr_deploy_550.py      本编排脚本

用法:
    python3 tools/hjepa_mr_deploy_550.py --all
    python3 tools/hjepa_mr_deploy_550.py --c-evolve --gens 6
    python3 tools/hjepa_mr_deploy_550.py --b-pull
    python3 tools/hjepa_mr_deploy_550.py --a-train --steps 120
"""
from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import subprocess
import sys
import time

ROOT = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"
LIVE = osp.join(ROOT, "zmax_data/ss_live")
EVOLVE_JSON = osp.join(LIVE, "hjepa_mr_550c_evolve.json")
PULL_JSON = osp.join(LIVE, "hjepa_mr_550b_result.json")
INTEL_HOME = "/home/intel/hjepa_mr"
# Intel 上系统 python3 没 torch; 有 XPU torch 2.7.1 的是 train_venv
INTEL_PY = os.environ.get("MR_INTEL_PY", "$HOME/train_venv/bin/python")
SSH_INTEL = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", "intel"]


def _run(cmd, timeout=300):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timeout %ss" % timeout
    except Exception as e:                                             # noqa: BLE001
        return 1, "", "%s: %s" % (type(e).__name__, str(e)[:200])


# ═══════════════ 550C ═══════════════
def cmd_c_evolve(gens=6, frames=80, timeout=1200):
    print("=== 550C · Intel 几何自主进化 ===")
    rc, out, err = _run(SSH_INTEL + ["echo ok; hostname; %s -c "
                                     "'import torch;print(torch.__version__)'" % INTEL_PY],
                        timeout=60)
    if rc != 0 or "ok" not in out:
        print("  ❌ Intel 不可达: %s" % (err or out)[:200])
        return {"ok": False, "why": "Intel SSH: %s" % (err or out)[:200]}
    print("  Intel: %s" % " | ".join(out.strip().splitlines()[:3]))

    print("  推代码…")
    _run(SSH_INTEL + ["mkdir -p %s" % INTEL_HOME], timeout=60)
    # tar.gz 是二进制, 必须走 bytes 管道 (text=True 会 UnicodeDecodeError: 0x8b)
    tar_p = subprocess.run(["bash", "-c",
                            "cd %s && tar czf - src/lerobot/manifold/*.py 2>/dev/null" % ROOT],
                           capture_output=True, timeout=120)
    if tar_p.returncode != 0 or not tar_p.stdout:
        print("  ❌ 打包失败")
        return {"ok": False, "why": "打包失败"}
    # --strip-components=3: src/lerobot/manifold/x.py → x.py
    p = subprocess.run(SSH_INTEL + ["tar xzf - -C %s --strip-components=3" % INTEL_HOME],
                       input=tar_p.stdout, capture_output=True, timeout=180)
    if p.returncode != 0:
        print("  ⚠ 代码解包 rc=%d: %s" % (p.returncode, (p.stderr or b"")[:200]))

    # 推进化器
    ev_local = osp.join(ROOT, "tools/hjepa_mr_evolver_intel.py")
    if not osp.exists(ev_local):
        print("  ❌ 缺 %s" % ev_local)
        return {"ok": False, "why": "缺进化器"}
    with open(ev_local, "rb") as f:
        src = f.read()
    p = subprocess.run(SSH_INTEL + ["cat > %s/evolve.py" % INTEL_HOME],
                       input=src, capture_output=True, timeout=120)
    if p.returncode != 0:
        print("  ❌ 推进化器失败: %s" % (p.stderr or b"")[:200])
        return {"ok": False, "why": "push evolver failed"}

    print("  进化 %d 代 (上限 %ds)…" % (gens, timeout))
    cmd = SSH_INTEL + [(
        "cd {h} && ZMAX_ROOT={h} MR_GENS={g} MR_FRAMES={f} "
        "PYTHONPATH={h} {py} {h}/evolve.py 2>&1 | tail -50"
    ).format(h=INTEL_HOME, g=gens, f=frames, py=INTEL_PY)]
    rc, out, err = _run(cmd, timeout=timeout)
    if out:
        print(out[-2500:])
    if err:
        print("  [stderr]", err[-400:])

    res = None
    for ln in (out or "").splitlines():
        if ln.startswith("__RESULT__"):
            try:
                res = json.loads(ln[len("__RESULT__"):])
            except Exception:                                          # noqa: BLE001
                pass
    if not res:
        return {"ok": False, "why": "没拿到 __RESULT__", "raw_tail": (out or "")[-800:]}
    os.makedirs(LIVE, exist_ok=True)
    with open(EVOLVE_JSON, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("  ✅ 550C 完成 → %s" % EVOLVE_JSON)
    print("     accepted=%s rejected=%s best_fitness=%.6f"
          % (res.get("accepted"), res.get("rejected"), res.get("best_fitness") or 0))
    return res


# ═══════════════ 550B ═══════════════
def cmd_b_pull():
    print("=== 550B · 结果回传 4060 ===")
    rc, out, err = _run(SSH_INTEL + ["cat %s/evolve_ledger.json" % INTEL_HOME], timeout=90)
    ledger = None
    if rc == 0 and (out or "").strip().startswith("{"):
        try:
            ledger = json.loads(out)
        except Exception:                                              # noqa: BLE001
            ledger = None
    evolved = {}
    if osp.exists(EVOLVE_JSON):
        try:
            evolved = json.load(open(EVOLVE_JSON))
        except Exception:                                              # noqa: BLE001
            evolved = {}
    if not ledger and not evolved:
        print("  ❌ 没有可回传的结果 (先跑 --c-evolve)")
        return {"ok": False, "why": "无结果"}

    entries = (ledger or {}).get("entries", [])
    payload = {
        "ok": True, "when": time.time(), "source": "550C (Intel Arc)",
        "evolve_summary": evolved,
        "ledger_entries": entries[-20:],
        "best_fitness": (ledger or {}).get("best_fitness", evolved.get("best_fitness")),
        "best_hp": (ledger or {}).get("best", {}).get("hp", evolved.get("best_hp")),
        "n_entries": len(entries),
        "data": evolved.get("data") or "合成轨迹",
        "fitness_semantics": evolved.get("fitness_semantics") or
                             "几何自洽性 (SE3平滑+法线平滑+NLL校准), 非真值精度",
    }
    os.makedirs(LIVE, exist_ok=True)
    tmp = PULL_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PULL_JSON)
    print("  ✅ 回传 → %s" % PULL_JSON)
    print("     best_fitness=%.6f · %d 代 · data=%s"
          % (payload["best_fitness"] or 0, payload["n_entries"], payload["data"]))
    return payload


# ═══════════════ 550A ═══════════════
def cmd_a_train(steps=120, timeout=1800, dry=False):
    print("=== 550A · 4060 训练几何分支 (真机位姿) ===")
    if not osp.exists(PULL_JSON):
        print("  ❌ 缺 550B 回传结果 (先跑 --b-pull)")
        return {"ok": False, "why": "缺回传结果"}
    payload = json.load(open(PULL_JSON))
    hp = payload.get("best_hp") or {}
    print("  HP: %s" % json.dumps(hp, ensure_ascii=False)[:200])

    ts = time.strftime("%Y%m%d_%H%M%S")
    rep_dir = osp.join(ROOT, "reports", "hjepa_mr_550a_%s" % ts)
    os.makedirs(rep_dir, exist_ok=True)
    with open(osp.join(rep_dir, "evolved_hp.json"), "w", encoding="utf-8") as f:
        json.dump({"hp": hp, "from": PULL_JSON, "when": time.time()},
                  f, ensure_ascii=False, indent=1)

    tr = osp.join(ROOT, "tools/hjepa_mr_train_550a.py")
    if not osp.exists(tr):
        print("  ❌ 缺 %s" % tr)
        return {"ok": False, "why": "缺训练器"}
    env = dict(os.environ)
    env.update({"ZMAX_ROOT": ROOT, "MR_HP": json.dumps(hp),
                "MR_A_STEPS": str(int(steps)), "MR_OUT": rep_dir})
    cmd = [osp.join(ROOT, "gui-venv311/bin/python"), tr]
    print("  命令: MR_A_STEPS=%d python %s" % (steps, tr))
    if dry:
        print("  [dry-run]")
        return {"ok": True, "dry": True, "report_dir": rep_dir}

    log_p = osp.join(rep_dir, "train.log")
    t0 = time.time()
    with open(log_p, "w") as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=ROOT)
    deadline = time.time() + timeout
    while time.time() < deadline and p.poll() is None:
        time.sleep(3)
    elapsed = time.time() - t0
    rc = p.poll()
    raw = ""
    try:
        raw = open(log_p).read()
    except Exception:                                                  # noqa: BLE001
        pass
    if raw:
        print(raw[-1800:])
    res = None
    for ln in raw.splitlines():
        if ln.startswith("__RESULT__"):
            try:
                res = json.loads(ln[len("__RESULT__"):])
            except Exception:                                          # noqa: BLE001
                pass
    out = {"ok": rc == 0 and bool(res), "rc": rc, "elapsed_s": round(elapsed, 1),
           "report_dir": rep_dir, "log": log_p, "hp": hp, "result": res,
           "still_running": p.poll() is None}
    with open(osp.join(rep_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    if res:
        print("  ✅ 550A 完成: %d 参数 · %d 帧真数据 · loss %.6f → %.6f · %.1fs"
              % (res["n_params"], res["frames"], res.get("loss_first") or 0,
                 res.get("loss_last") or 0, res["secs"]))
    else:
        print("  ❌ 550A 无结果 (rc=%s)" % rc)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--c-evolve", action="store_true")
    ap.add_argument("--b-pull", action="store_true")
    ap.add_argument("--a-train", action="store_true")
    ap.add_argument("--gens", type=int, default=6)
    ap.add_argument("--frames", type=int, default=80)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--c-timeout", type=int, default=1200)
    ap.add_argument("--a-timeout", type=int, default=1800)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if not (a.all or a.c_evolve or a.b_pull or a.a_train):
        ap.print_help()
        return 2

    results = {}
    if a.all or a.c_evolve:
        results["550C"] = cmd_c_evolve(gens=a.gens, frames=a.frames, timeout=a.c_timeout)
    if a.all or a.b_pull:
        results["550B"] = cmd_b_pull()
    if a.all or a.a_train:
        results["550A"] = cmd_a_train(steps=a.steps, timeout=a.a_timeout, dry=a.dry)

    print("\n=== 汇总 ===")
    allok = True
    for k, v in results.items():
        ok = bool((v or {}).get("ok"))
        allok = allok and ok
        print("  %s: %s" % (k, "✅" if ok else "❌ " + str((v or {}).get("why"))[:120]))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
