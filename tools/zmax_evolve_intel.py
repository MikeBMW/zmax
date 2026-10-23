#!/usr/bin/env python3
"""Z-MAX Intel 自主进化守护 —— 在 Arc GPU 上自主训练→评估→择优（带变异搜索）。

在 Intel 工位机（Arc B390 / torch XPU）常驻运行：
  每一代从当前最佳权重出发，按「变异表」挑一组超参/增广，训练若干 epoch，
  用固定验证集评估 mAP50；只有真实提升（超过 margin）才采纳为新基线，
  否则回滚并如实记录。台账记下每代的变异名与完整配置，可复核可复现。

铁律（老倪定的门槛）：
  · 交付门槛是「有提升」，不是「不回退」—— 没提升就是没提升，台账照写。
  · 缺失真源一律显「未测 / 尚未生成」，绝不假 0。
  · 每代必须留下可复核的证据：权重文件、评估数值、耗时、数据集指纹、变异配置。

为什么要有变异表：训练是确定性的（固定 seed + 固定数据顺序 + 固定超参），
不变异的话每一代都会产出**逐位相同**的权重和 mAP，进化的「搜索」根本不存在。
历史台账实证：gen8/9/10 的 mAP50 都是 0.740945867230116（15 位小数全同）。

环境变量：
  EVO_DATA      数据集 yaml（默认 ~/train_data/peg_insert/data.yaml）
  EVO_MODEL     起始权重（默认 ~/zmax_map/models/yolov8n.pt）
  EVO_WORK      工作目录（默认 ~/evolve）
  EVO_EPOCHS    每代基准 epoch 数（默认 3；平台期自动 +1）
  EVO_BATCH     批大小（默认 8）
  EVO_IMGSZ     输入尺寸（默认 640，必须与在役 OpenVINO 模型一致）
  EVO_DEVICE    xpu / cpu（默认 xpu）
  EVO_MARGIN    采纳阈值，mAP50 需超过 best + margin（默认 0.005）
  EVO_ROUNDS    最多进化代数（默认 0 = 无限）
  EVO_COOLDOWN  两代之间冷却秒数（默认 60）
  EVO_PORT      只读 HTTP 端口（默认 8810）
  EVO_MUTATE    1=启用变异（默认 1），0=每代同配置（仅调试用）

只读端点：/health /state /ledger /models
"""
import json
import os
import random
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")

# ultralytics 在 import 期会引用 matplotlib，而本机 Python 3.12 没有可用的
# cp312 版（现成的都是 3.11 编的 C 扩展）。必须先装桩再导入 ultralytics。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import mpl_stub  # noqa: F401
except Exception as _e:  # 桩缺失也要让服务起来，错误留给 /health 暴露
    print(f"[evolve] 警告: matplotlib 桩加载失败 {_e}", flush=True)

DATA = os.environ.get("EVO_DATA", f"{HOME}/train_data/peg_insert/data.yaml")
SEED = os.environ.get("EVO_MODEL", f"{HOME}/zmax_map/models/yolov8n.pt")
WORK = os.path.expanduser(os.environ.get("EVO_WORK", f"{HOME}/evolve"))
EPOCHS = int(os.environ.get("EVO_EPOCHS", "3"))
BATCH = int(os.environ.get("EVO_BATCH", "8"))
IMGSZ = int(os.environ.get("EVO_IMGSZ", "640"))
DEVICE = os.environ.get("EVO_DEVICE", "xpu")
MARGIN = float(os.environ.get("EVO_MARGIN", "0.005"))
MAX_ROUNDS = int(os.environ.get("EVO_ROUNDS", "0"))
COOLDOWN = float(os.environ.get("EVO_COOLDOWN", "60"))
PORT = int(os.environ.get("EVO_PORT", "8810"))
MUTATE = os.environ.get("EVO_MUTATE", "1") != "0"

LEDGER = os.path.join(WORK, "ledger.json")
BEST = os.path.join(WORK, "best.pt")
STATE = {
    "phase": "starting",
    "generation": 0,
    "best_map50": None,
    "last_map50": None,
    "accepted": 0,
    "rejected": 0,
    "streak": 0,
    "mutation": None,
    "config": None,
    "last_error": None,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_round_at": None,
    "rounds": 0,
}
_LOCK = threading.Lock()

# ── 变异表 ────────────────────────────────────────────────────────────────
# 在役指标短板是 recall（~0.58）而 precision 已 ~0.99，所以变异集中在
# 「让模型见过更刁的样本」上：尺度/平移/旋转/色彩抖动。lr 与冻结层是
# 另一半自由度：从 best.pt 微调，lr 太大会把已有能力打散（实测 1 epoch
# + 默认 lr 掉了 8 个点），所以只给中小 lr。
MUTATIONS = [
    # (名字, 训练参数覆盖, 权重)
    ("base",      {},                                                     1),
    ("lr_mid",    {"lr0": 0.0040, "cos_lr": True},                        3),
    ("lr_low",    {"lr0": 0.0008, "cos_lr": True},                        2),
    ("aug_scale", {"scale": 0.80, "translate": 0.15},                     3),
    ("aug_rot",   {"degrees": 12.0, "scale": 0.50, "translate": 0.10},    3),
    ("mosaic_hi", {"mosaic": 1.0, "close_mosaic": 0},                     2),
    ("hsv_hi",    {"hsv_h": 0.02, "hsv_s": 0.70, "hsv_v": 0.50,
                   "scale": 0.60},                                        2),
    ("nofmix",    {"mosaic": 0.0, "mixup": 0.0, "scale": 0.9,
                   "translate": 0.10},                                    2),
    ("freeze10",  {"freeze": 10, "lr0": 0.0020},                          2),
]
WIDE = {"aug_scale", "aug_rot", "hsv_hi", "mosaic_hi"}


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _read_ledger():
    if not os.path.exists(LEDGER):
        return {"created_at": _utc(), "entries": []}
    try:
        with open(LEDGER, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"created_at": _utc(), "entries": []}


def _write_ledger(ledger):
    os.makedirs(WORK, exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LEDGER)


def _set(**kw):
    with _LOCK:
        STATE.update(kw)


def _param_count(model):
    try:
        return int(sum(p.numel() for p in model.model.parameters()))
    except Exception:
        return None


def _dataset_fingerprint():
    """数据集指纹 —— 帧数 + 缓存大小，用来判断数据是否换过。"""
    info = {"yaml": DATA, "train_images": None, "val_images": None, "train_cache_bytes": None}
    try:
        root = os.path.dirname(DATA)
        for key, sub in (("train_images", "images/train"), ("val_images", "images/val")):
            p = os.path.join(root, sub)
            if os.path.isdir(p):
                info[key] = len(os.listdir(p))
        cache = os.path.join(root, "labels", "train.cache")
        if os.path.exists(cache):
            info["train_cache_bytes"] = os.path.getsize(cache)
    except Exception as e:
        info["error"] = str(e)
    return info


def _sample_config(gen, streak):
    """按代数确定性采样一组训练配置 —— 同代可复现，不同代必不同。

    平台期（连续 rejected ≥ 3）升级：epochs +1 且只在「大变异」里挑，
    小步微调既然已经被证明不涨点，就别再浪费一整代算力。
    """
    if not MUTATE:
        return {"mutation": "fixed", "epochs": EPOCHS, "kwargs": {}}

    rng = random.Random(7919 * (gen + 1))
    pool = MUTATIONS
    if streak >= 3:
        pool = [m for m in MUTATIONS if m[0] in WIDE] + [("lr_low", {"lr0": 0.0008, "cos_lr": True}, 1)]
    names = [m[0] for m in pool]
    weights = [m[2] for m in pool]
    pick = rng.choices(pool, weights=weights, k=1)[0]
    # 计算量阶梯：连续不涨点说明「3~4 epoch 的小步微调」这条路走到头了，
    # 那就不是再换一组增广，而是加算力。实测每 epoch 640px ≈ 20 分钟。
    #   streak 0-2  → 3 epoch （约 1 小时/代）
    #   streak 3-5  → 4 epoch + 大变异
    #   streak 6-8  → 12 epoch（约 4 小时/代，一次性把能力推上去）
    #   streak >=9  → 20 epoch（约 7 小时/代，逼近数据上限）
    if streak >= 9:
        eps = 20
    elif streak >= 6:
        eps = 12
    elif streak >= 3:
        eps = EPOCHS + 1
    else:
        eps = EPOCHS
    kwargs = dict(pick[1])
    # optimizer=auto 会「忽略 lr0 自己决定」——实测日志：
    #   "optimizer=auto found, ignoring lr0=0.01 ... determining best optimizer"
    # 那样变异表里的 lr 档位全是空转（静默降级）。必须显式钉住 AdamW。
    kwargs.setdefault("optimizer", "AdamW")
    # 默认 warmup_epochs=3.0，在 3~4 epoch 的短程里等于整程都在 warmup，
    # 学习率调度根本走不到衰减段。短程必须压到 0.5。
    kwargs.setdefault("warmup_epochs", 0.5)
    # 从 best.pt 微调，lr0 默认 0.01 会把已有能力打散（实测 1 epoch 掉 8 个点）。
    # 基准 0.002 ≈ Ultralytics auto 在 AdamW 下自己挑的 0.0014 量级。
    kwargs.setdefault("lr0", 0.002)
    kwargs["seed"] = 1000 + gen          # 每代换随机种子，保证不是同一条轨迹
    kwargs["cos_lr"] = bool(kwargs.get("cos_lr", True))
    return {"mutation": pick[0], "epochs": eps, "kwargs": kwargs,
            "escalated": streak >= 3, "pool": names}


def _eval_map50(model, tag):
    """在固定验证集上评估，返回 mAP50 等指标。未测到就返回 None，绝不填 0。"""
    out = {"map50": None, "map50_95": None, "precision": None, "recall": None}
    try:
        res = model.val(data=DATA, imgsz=IMGSZ, batch=BATCH, device=DEVICE,
                        plots=False, verbose=False, split="val")
        d = getattr(res, "results_dict", {}) or {}
        out["map50"] = d.get("metrics/mAP50(B)")
        out["map50_95"] = d.get("metrics/mAP50-95(B)")
        out["precision"] = d.get("metrics/precision(B)")
        out["recall"] = d.get("metrics/recall(B)")
    except Exception as e:
        out["error"] = f"{tag}: {type(e).__name__}: {e}"
    return out


def _train_one_generation(gen, start_weights, cfg):
    from ultralytics import YOLO

    proj = os.path.join(WORK, "runs")
    os.makedirs(proj, exist_ok=True)
    name = f"gen{gen:03d}"
    m = YOLO(start_weights)
    n_params = _param_count(m)
    t0 = time.time()
    kwargs = dict(cfg["kwargs"])
    r = m.train(
        data=DATA, epochs=cfg["epochs"], imgsz=IMGSZ, batch=BATCH, device=DEVICE,
        workers=4, plots=False, verbose=True, exist_ok=True,
        project=proj, name=name,
        **kwargs,
    )
    elapsed = time.time() - t0
    best_pt = os.path.join(proj, name, "weights", "best.pt")
    if not os.path.exists(best_pt):
        best_pt = os.path.join(proj, name, "weights", "last.pt")
    d = getattr(r, "results_dict", {}) or {}
    return {
        "weights": best_pt,
        "seconds": round(elapsed, 1),
        "params": n_params,
        "train_map50": d.get("metrics/mAP50(B)"),
    }


def _is_device_lost(err):
    s = str(err).lower()
    return "device_lost" in s or "level_zero" in s


def _run_round():
    """跑一代进化。返回台账条目。"""
    with _LOCK:
        gen = STATE["generation"] + 1
        streak = STATE.get("streak") or 0
    cfg = _sample_config(gen, streak)
    _set(phase=f"training gen{gen}", generation=gen,
         mutation=cfg["mutation"], config=cfg)

    start = BEST if os.path.exists(BEST) else SEED
    print(f"[evolve] gen{gen} 变异={cfg['mutation']} epochs={cfg['epochs']} "
          f"kwargs={cfg['kwargs']} 起点={start}", flush=True)

    # XPU 上 level_zero 会偶发 device lost（xe GT0 job timeout）。这不是配置
    # 问题，重试同一代即可；连续 3 次失败才记为失败代，别把整条进化链拖死。
    last_err = None
    trained = None
    for attempt in range(1, 4):
        try:
            trained = _train_one_generation(gen, start, cfg)
            break
        except Exception as e:
            last_err = e
            if not _is_device_lost(e):
                raise
            print(f"[evolve] gen{gen} 第{attempt}次训练 XPU device lost: {e}；"
                  f"90s 后重试", flush=True)
            _set(last_error=f"device lost, retry {attempt}/3")
            time.sleep(90)
    if trained is None:
        reason = f"训练连续 3 次 XPU device lost，跳过本代（{type(last_err).__name__}: {last_err}）"
        entry = {
            "generation": gen, "at": _utc(), "started_from": start,
            "epochs": cfg["epochs"], "mutation": cfg["mutation"],
            "mutation_kwargs": cfg["kwargs"], "accepted": False, "reason": reason,
            "val": {"map50": None, "map50_95": None, "precision": None, "recall": None},
            "weights_kept": None, "dataset": _dataset_fingerprint(),
        }
        ledger = _read_ledger()
        ledger["entries"].append(entry)
        ledger["updated_at"] = _utc()
        _write_ledger(ledger)
        with _LOCK:
            STATE["rejected"] += 1
            STATE["rounds"] += 1
            STATE["last_round_at"] = _utc()
            STATE["last_reason"] = reason
            STATE["streak"] = (STATE.get("streak") or 0) + 1
        return entry

    _set(phase=f"evaluating gen{gen}")
    from ultralytics import YOLO
    cand = YOLO(trained["weights"])
    metrics = _eval_map50(cand, f"gen{gen}")

    best_map = STATE.get("best_map50")
    cand_map = metrics.get("map50")

    # 采纳判据：必须有真实提升；mAP 未测到一律不采纳
    if cand_map is None:
        accepted = False
        reason = f"评估未产出 mAP50（{metrics.get('error', '未知原因')}）→ 不采纳"
    elif best_map is None:
        accepted = True
        reason = f"首个可用基线：mAP50={cand_map:.4f}"
    elif cand_map > best_map + MARGIN:
        accepted = True
        reason = f"提升 {cand_map - best_map:+.4f} > margin {MARGIN} → 采纳"
    else:
        accepted = False
        reason = (f"无实质提升（{cand_map:.4f} vs best {best_map:.4f}，"
                  f"差 {cand_map - best_map:+.4f} ≤ {MARGIN}）→ 回滚")

    stored = None
    if accepted:
        os.makedirs(WORK, exist_ok=True)
        shutil.copy2(trained["weights"], BEST)
        gen_dir = os.path.join(WORK, "models")
        os.makedirs(gen_dir, exist_ok=True)
        stored = os.path.join(gen_dir, f"gen{gen:03d}.pt")
        shutil.copy2(trained["weights"], stored)

    entry = {
        "generation": gen,
        "at": _utc(),
        "started_from": start,
        "params": trained.get("params"),
        "epochs": cfg["epochs"],
        "mutation": cfg["mutation"],
        "mutation_kwargs": cfg["kwargs"],
        "escalated": cfg.get("escalated", False),
        "seconds": trained.get("seconds"),
        "train_map50": trained.get("train_map50"),
        "val": metrics,
        "best_map50_before": best_map,
        "accepted": accepted,
        "reason": reason,
        "weights_kept": stored,
        "dataset": _dataset_fingerprint(),
    }

    ledger = _read_ledger()
    ledger["entries"].append(entry)
    ledger["updated_at"] = _utc()
    _write_ledger(ledger)

    with _LOCK:
        if accepted and cand_map is not None:
            STATE["best_map50"] = cand_map
        STATE["last_map50"] = cand_map
        STATE["accepted"] = STATE["accepted"] + (1 if accepted else 0)
        STATE["rejected"] = STATE["rejected"] + (0 if accepted else 1)
        STATE["rounds"] = STATE["rounds"] + 1
        STATE["last_round_at"] = _utc()
        STATE["last_reason"] = reason
        STATE["streak"] = 0 if accepted else (STATE.get("streak") or 0) + 1
        if accepted:
            STATE["last_error"] = None
    print(f"[evolve] gen{gen} mAP50={cand_map} accepted={accepted} {reason}", flush=True)
    return entry


def _loop():
    while True:
        try:
            if MAX_ROUNDS and STATE["rounds"] >= MAX_ROUNDS:
                _set(phase=f"finished {MAX_ROUNDS} rounds")
                return
            _run_round()
            _set(phase="cooldown")
            time.sleep(COOLDOWN)
        except Exception as e:
            _set(phase="error", last_error=f"{type(e).__name__}: {e}",
                 traceback=traceback.format_exc()[-2000:])
            time.sleep(max(COOLDOWN, 60))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health":
            with _LOCK:
                st = dict(STATE)
            st["alive"] = True
            st["data_exists"] = os.path.exists(DATA)
            st["best_exists"] = os.path.exists(BEST)
            st["imgsz"] = IMGSZ
            st["batch"] = BATCH
            self._send(st)
        elif p == "/state":
            with _LOCK:
                self._send(dict(STATE))
        elif p == "/ledger":
            self._send(_read_ledger())
        elif p == "/models":
            d = os.path.join(WORK, "models")
            items = []
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    fp = os.path.join(d, f)
                    items.append({"file": f, "bytes": os.path.getsize(fp)})
            self._send({"best": BEST if os.path.exists(BEST) else None,
                        "best_bytes": os.path.getsize(BEST) if os.path.exists(BEST) else None,
                        "generations": items})
        else:
            self._send({"error": "not found",
                        "endpoints": ["/health", "/state", "/ledger", "/models"]}, 404)


def main():
    os.makedirs(WORK, exist_ok=True)
    for p in (DATA, SEED):
        if not os.path.exists(p):
            _set(phase="blocked", last_error=f"缺少真源: {p}")

    # 从台账恢复最优值：否则守护重启后 best_map50=None，
    # 第一代会被当成「首个可用基线」无条件采纳，哪怕比历史最优更差。
    ledger = _read_ledger()
    entries = ledger.get("entries", [])
    accepted = [e for e in entries if e.get("accepted")]
    if accepted:
        restored = accepted[-1]["val"].get("map50")
        if restored is not None:
            # 用台账里最大的代号恢复，别用条数——基线 gen0 不占进化代号，
            # 用 len() 会让重启后跳过一代。
            max_gen = max(e.get("generation", 0) for e in entries)
            streak = 0
            for e in reversed(entries):
                if e.get("accepted"):
                    break
                streak += 1
            _set(best_map50=restored, generation=max_gen,
                 accepted=len(accepted),
                 rejected=len(entries) - len(accepted),
                 rounds=len(entries), streak=streak)
            print(f"[evolve] 从台账恢复: 最优 mAP50={restored:.4f} "
                  f"(已采纳 {len(accepted)}/{len(entries)} 代, 连续未采纳 {streak}, "
                  f"下一代 gen{max_gen + 1})", flush=True)

    print(f"[evolve] data={DATA} seed={SEED} work={WORK}", flush=True)
    print(f"[evolve] epochs={EPOCHS} batch={BATCH} imgsz={IMGSZ} device={DEVICE} "
          f"margin={MARGIN} cooldown={COOLDOWN}s mutate={MUTATE}", flush=True)

    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[evolve] 只读端点 :{PORT} /health /state /ledger /models", flush=True)

    _loop()


if __name__ == "__main__":
    main()
