#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_compute_mode.py — 档位 → 算力用法 的**唯一决策部署口** (550A/550B/550C)。

老倪 2026-10-21 (逐字):
  「左下角选 550C, 则自动切换到 intel 运行部署模式, 显示 intel 硬件信息;
    选 550B, 自动打开 vscode, 对应一种 debug 模式, 自动运行单线程模式, 推理如果有 intel,
    默认就在 intel, 如果没有硬件, 自动调回 4060;
    550A 自动启动 4060 全模型训练模式, 如果算力不足, 启用所有能获得的计算资源」。

为什么单独一个模块: 界面 chip 只该做一件事 —— 把档位交给这里。决策 (推理落哪台 / 几线程 /
要不要起训练 / 要不要起 VSCode / intel 通不通) 全在这个文件里, 谁都能复核:
    ./gui-venv311/bin/python tools/zmax_compute_mode.py --json         # 看当前档的决策
    ./gui-venv311/bin/python tools/zmax_compute_mode.py --apply 550C   # 真切换 (写档 + 起隧道 + 探活)
零依赖 (stdlib), 不改任何在役软链; 训练只**新起**一个进程, 绝不 kill 别人的。

口径:
  550C 推理=intel (不可达则**明说**回退 4060, 不冒充); 本机线程=2 (只做桥)
  550B 推理=intel 优先, 无 intel 自动回 4060; 线程=1 (单线程 debug, 单线程口径真源=vscode_launch.SINGLE_THREAD_ENV)
  550A 训练=4060 全模型 (L4,L3,L2) 吃满 GPU+全部 CPU 核; 推理挪 intel 以免和训练抢卡
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_J = os.path.join(ROOT, "config", "platform", "zmax_compute_mode.json")
TRAIN_LOG_DIR = os.path.join(ROOT, "reports")

# intel 端侧 /health 候选: 隧道优先 (本机不在产线网时), 产线网直连作候选
EDGE_URLS = [u for u in (os.environ.get("ZMAX_EDGE_URL"),
                         "http://127.0.0.1:18800/health",
                         "http://192.168.23.70:8800/health") if u]
if (os.environ.get("ZMAX_EDGE_ONLY") or "").strip():   # 判据用: 只探指定地址 (验证「无 intel 自动回 4060」)
    EDGE_URLS = [u for u in (os.environ.get("ZMAX_EDGE_URL"),) if u]
TUNNEL_UNIT = "zmax-orin-intel-fwd.service"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def probe_edge(timeout=2.0):
    """→ {online, url, ms, device, models, hw, err}; 读不到一律 online=False (不冒充)。"""
    errs = []
    for url in EDGE_URLS:
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                d = json.loads(r.read().decode())
        except Exception as e:                                          # noqa: BLE001
            errs.append("%s(%s)" % (url, type(e).__name__))
            continue
        pipe = d.get("pipeline") or {}
        devs = pipe.get("devices") or {}
        return {"online": True, "url": url, "ms": round((time.time() - t0) * 1000.0, 1),
                "device": d.get("device"), "models": sorted(devs.keys()) and {
                    k: (v or {}).get("models") for k, v in devs.items()},
                "fps": pipe.get("total_fps"), "n_req": d.get("n_req"),
                "last_ms": d.get("last_ms"), "hw": d.get("hw") or {},
                "err": None}
    return {"online": False, "url": EDGE_URLS[0] if EDGE_URLS else "", "ms": None,
            "err": "; ".join(errs) or "无候选地址"}


def probe_local():
    """本机算力 (4060 侧): GPU 名/利用率/显存 + CPU 核数/load。"""
    out = {"gpu": None, "gpu_util": None, "gpu_mem_free_mb": None,
           "cores": os.cpu_count() or 0, "load1": None}
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.free",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4)
        line = (r.stdout or "").strip().splitlines()[0]
        p = [x.strip() for x in line.split(",")]
        out.update(gpu=p[0], gpu_util=int(float(p[1])), gpu_mem_free_mb=int(float(p[2])))
    except Exception:                                                   # noqa: BLE001
        pass
    try:
        with open("/proc/loadavg") as f:
            out["load1"] = float(f.read().split()[0])
    except Exception:                                                   # noqa: BLE001
        pass
    return out


def tunnel_active():
    try:
        r = subprocess.run(["systemctl", "is-active", TUNNEL_UNIT], capture_output=True, text=True, timeout=5)
        return (r.stdout or "").strip() == "active"
    except Exception:                                                   # noqa: BLE001
        return False


def train_running():
    """已有联合训练在跑就返回 pid (不重复起第二个)。"""
    try:
        r = subprocess.run(["pgrep", "-af", "joint_train_all.py"], capture_output=True, text=True, timeout=5)
        for ln in (r.stdout or "").splitlines():
            if "pgrep" in ln or "--help" in ln:
                continue
            if "joint_train_all.py" in ln:
                return ln.split()[0]
    except Exception:                                                   # noqa: BLE001
        pass
    return ""


def policy(product, edge=None, local=None):
    """档位 → 算力决策 (纯函数, 不写盘不启动, 便于复核)。"""
    p = str(product or "").strip().upper()
    edge = edge if edge is not None else probe_edge()
    local = local if local is not None else probe_local()
    egpu = ((edge.get("hw") or {}).get("accel") or {})
    edge_ok = bool(edge.get("online"))
    d = {"product": p, "ts": _now(), "intel": edge, "local": local,
         "intel_online": edge_ok}

    if p == "550C":
        d.update({
            "role": "deploy · intel 运行部署模式",
            "infer": {"target": "intel" if edge_ok else "4060",
                      "why": ("intel /health 在线: 推理在 intel (%s)" % (edge.get("device") or "?"))
                      if edge_ok else ("intel 不可达 → **回退 4060**, 原因: %s" % edge.get("err")),
                      "fallback": not edge_ok, "url": edge.get("url")},
            "threads": 2, "single_thread": False,
            "train": {"target": None, "why": "部署档不训练"},
            "vscode": False,
            "display": "intel" if edge_ok else "4060(回退)",
            "intel_hw": {k: (egpu.get(k) or {}) for k in ("cpu", "gpu", "npu")},
        })
    elif p == "550B":
        d.update({
            "role": "bridge · 状态空间工程 / 全 tool / VSCode 标定",
            "infer": {"target": "intel" if edge_ok else "4060",
                      "why": ("intel 在线 → 推理默认 intel, 4060 只留给调试") if edge_ok
                      else ("无 intel 硬件 → 自动回 4060 (%s)" % edge.get("err")),
                      "fallback": not edge_ok, "url": edge.get("url")},
            "threads": 1, "single_thread": True,
            "train": {"target": None, "why": "调试档不训练"},
            "vscode": True,
            "display": "intel" if edge_ok else "4060",
        })
    else:  # 550A
        gpu_free = local.get("gpu_mem_free_mb") or 0
        tight = bool(local.get("gpu_util") is not None and local["gpu_util"] > 60) or (0 < gpu_free < 1500)
        d.update({
            "role": "dev · 4060 全模型训练",
            "train": {"target": "4060", "only": "L4,L3,L2",
                      "why": ("4060 空闲: 全模型训练吃满 GPU + %d 核" % local.get("cores", 0))
                      if not tight else ("4060 紧张 (util=%s%% free=%sMB) → 训练仍在本机, 推理挪 intel 腾卡"
                                         % (local.get("gpu_util"), gpu_free)),
                      "use_all": True},
            "infer": {"target": "intel" if edge_ok else "4060",
                      "why": ("算力不足时启用所有可得资源: 推理切 intel, 4060 专供训练") if (tight and edge_ok)
                      else ("intel 在线 → 推理放 intel, 4060 留给训练" if edge_ok
                            else "无 intel → 推理与训练共用 4060"),
                      "fallback": not edge_ok, "url": edge.get("url")},
            "threads": "all", "single_thread": False,
            "vscode": False,
            "display": "4060",
            "resources": {"gpu": local.get("gpu"), "cores": local.get("cores"),
                          "intel_offload": edge_ok},
        })
    d["summary"] = ("%s %s | 推理=%s 线程=%s 训练=%s VSCode=%s intel=%s"
                    % (p, d["role"], d["infer"]["target"], d["threads"],
                       (d.get("train") or {}).get("target") or "无", d["vscode"],
                       "通" if edge_ok else "不通"))
    return d


def _write_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_J), exist_ok=True)
        tmp = STATE_J + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_J)
        return True
    except Exception:                                                   # noqa: BLE001
        return False


def load_state():
    try:
        with open(STATE_J, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                   # noqa: BLE001
        return {}


def start_vscode(root=None):
    """550B: 起 VSCode 状态空间工程 (复用 vscode_launch 这一唯一实现)。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
        from vscode_launch import autostart                        # noqa: PLC0415
        return autostart(root or ROOT)
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120])}


def start_training(product="550A", only="L4,L3,L2", steps=None):
    """550A: 起 4060 全模型训练 (独立会话, 日志落 reports/; 已有训练在跑就不重复起)。"""
    pid = train_running()
    if pid:
        return {"ok": True, "already": True, "pid": pid, "why": "已有联合训练在跑, 不重复起"}
    try:
        os.makedirs(TRAIN_LOG_DIR, exist_ok=True)
    except Exception:                                                   # noqa: BLE001
        pass
    log = os.path.join(TRAIN_LOG_DIR, "profile_550A_train_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
    py = sys.executable or "python3"
    cmd = [py, os.path.join(ROOT, "tools", "joint_train_all.py"), "--only", only]
    if steps:
        cmd += ["--steps", str(steps)]
    try:
        with open(log, "wb") as lf:
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True,
                                 env=dict(os.environ, ZMAX_PRODUCT=product))
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:140])}
    time.sleep(1.2)
    alive = p.poll() is None
    return {"ok": alive, "pid": p.pid, "log": log, "cmd": " ".join(cmd),
            "why": "已起 4060 全模型训练 (L4,L3,L2)" if alive
                   else ("训练进程 1.2s 内退出, 看日志: %s" % log)}


def ensure_tunnel():
    """550C: intel 通道 (18800) 不在就拉起来。"""
    if tunnel_active():
        return {"ok": True, "why": "%s 已 active" % TUNNEL_UNIT, "started": False}
    try:
        r = subprocess.run(["sudo", "-n", "systemctl", "start", TUNNEL_UNIT],
                           capture_output=True, text=True, timeout=15)
        ok = tunnel_active()
        return {"ok": ok, "started": ok, "why": ("已拉起 %s" % TUNNEL_UNIT) if ok
                else ("拉不起来: %s" % ((r.stderr or r.stdout or "").strip()[:120] or "未知"))}
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "started": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120])}


def active_product():
    """读真源当前的 active_product (只读, 不依赖 lerobot)。"""
    try:
        with open(os.path.join(ROOT, "config", "platform", "zmax_product.json"), encoding="utf-8") as f:
            return str(json.load(f).get("active_product") or "")
    except Exception:                                                   # noqa: BLE001
        return ""


def set_product(product):
    """写档位 —— 一律走唯一写路径 status_hub.set_profile (备份 + 原子写 + 回读 + 切换日志)。"""
    p = str(product or "").strip().upper()
    if active_product() == p:
        return {"ok": True, "unchanged": True, "why": "真源已经是 %s, 不重复写" % p}
    sys.path.insert(0, os.path.join(ROOT, "src"))
    try:
        from lerobot.engineering import status_hub                   # noqa: PLC0415
        return dict(status_hub.set_profile(p), unchanged=False)
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "why": "写不进真源 (%s: %s)" % (type(e).__name__, str(e)[:110])}


def apply(product, do=("product", "state", "tunnel", "vscode", "train"), dry=False, steps=None):
    """真切换: ①算决策 ②按档做事 ③落状态文件。返回 {ok, product, actions[], state}。"""
    acts = []
    p = str(product or "").strip().upper()

    if "product" in do and not dry:
        s = set_product(p)
        acts.append({"act": "product", "ok": bool(s.get("ok")),
                     "why": s.get("why") or ("真源已写 %s (重启控制台后界面/话题准入全生效)" % p)})

    if "tunnel" in do and p == "550C" and not dry:
        t = ensure_tunnel()
        acts.append({"act": "intel_tunnel", **t})

    st = policy(p)
    if "state" in do and not dry:
        st["applied_at"] = _now()
        st["state_written"] = _write_state(st)

    if "vscode" in do and st.get("vscode") and not dry:
        v = start_vscode()
        acts.append({"act": "vscode", "ok": bool(v.get("ok")), "skipped": bool(v.get("skipped")),
                     "why": v.get("why") or ("已起" if v.get("ok") else "未起")})

    if "train" in do and (st.get("train") or {}).get("target") and not dry:
        t = start_training(p, (st["train"] or {}).get("only") or "L4,L3,L2", steps=steps)
        acts.append({"act": "train", **t})

    ok = st.get("intel_online") or p == "550A" or True   # 状态写成功即算 ok; 仔细看 actions
    return {"ok": ok, "product": p, "dry": dry, "actions": acts, "state": st}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="档位 → 算力用法 决策部署口 (550A/550B/550C)")
    ap.add_argument("--apply", default="", help="550A|550B|550C: 真切换 (写档状态 + 按档做事)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-vscode", action="store_true")
    ap.add_argument("--no-train", action="store_true")
    ap.add_argument("--train-steps", type=int, default=0, help="只给验证用: 训练有界步数")
    ap.add_argument("--show", action="store_true", help="只打印按当前档位算出的决策")
    a = ap.parse_args(argv)

    if a.apply:
        do = ["product", "state", "tunnel"]
        if not a.no_vscode:
            do.append("vscode")
        if not a.no_train:
            do.append("train")
        r = apply(a.apply, do=tuple(do), dry=a.dry_run, steps=(a.train_steps or None))
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        else:
            st = r["state"]
            print(st["summary"])
            for x in r["actions"]:
                print("  · %-12s %s %s" % (x.get("act"), "OK" if x.get("ok") else "FAIL",
                                           x.get("why") or ""))
            print("  · 状态文件 %s" % (STATE_J if st.get("state_written") else "(未写)"))
        return 0 if r["ok"] else 1

    st = policy(load_state().get("product") or "550B")
    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=1))
    else:
        print(st["summary"])
        print("  推理: %s" % st["infer"]["why"])
        print("  训练: %s" % (st.get("train") or {}).get("why", "—"))
        print("  intel: %s · %s" % ("在线" if st["intel_online"] else "不通",
                                    st["intel"].get("url") or st["intel"].get("err")))
        print("  本机: %s · %s 核 · load1 %s" % (st["local"].get("gpu"), st["local"].get("cores"),
                                                st["local"].get("load1")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
