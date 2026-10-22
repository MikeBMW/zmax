#!/usr/bin/env python3
"""Z-MAX Intel 自主进化守护 —— 在 Arc GPU 上自主训练→评估→择优。

在 Intel 工位机（Arc B390 / torch XPU）常驻运行：
  每一代从当前最佳权重出发，训练若干 epoch，用固定验证集评估 mAP50；
  只有真实提升（超过 margin）才采纳为新基线，否则回滚并如实记录。

铁律（老倪定的门槛）：
  · 交付门槛是「有提升」，不是「不回退」—— 没提升就是没提升，台账照写。
  · 缺失真源一律显「未测 / 尚未生成」，绝不假 0。
  · 每代必须留下可复核的证据：权重文件、评估数值、耗时、数据集指纹。

环境变量：
  EVO_DATA      数据集 yaml（默认 ~/train_data/peg_insert/data.yaml）
  EVO_MODEL     起始权重（默认 ~/zmax_map/models/yolov8n.pt）
  EVO_WORK      工作目录（默认 ~/evolve）
  EVO_EPOCHS    每代 epoch 数（默认 3）
  EVO_BATCH     批大小（默认 8）
  EVO_IMGSZ     输入尺寸（默认 320）
  EVO_DEVICE    xpu / cpu（默认 xpu）
  EVO_MARGIN    采纳阈值，mAP50 需超过 best + margin（默认 0.005）
  EVO_ROUNDS    最多进化代数（默认 0 = 无限）
  EVO_COOLDOWN  两代之间冷却秒数（默认 60）
  EVO_VAL_EVERY 每代内的循环内验证次数（默认 1）
  EVO_PORT      只读 HTTP 端口（默认 8810）

只读端点：/health /state /ledger /models
"""
import json
import os
import shutil
import sys
import threading
import time
import traceback
import urllib.request
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
IMGSZ = int(os.environ.get("EVO_IMGSZ", "320"))
DEVICE = os.environ.get("EVO_DEVICE", "xpu")
MARGIN = float(os.environ.get("EVO_MARGIN", "0.005"))
MAX_ROUNDS = int(os.environ.get("EVO_ROUNDS", "0"))
COOLDOWN = float(os.environ.get("EVO_COOLDOWN", "60"))
PORT = int(os.environ.get("EVO_PORT", "8810"))

LEDGER = os.path.join(WORK, "ledger.json")
BEST = os.path.join(WORK, "best.pt")
STATE = {
    "phase": "starting",
    "generation": 0,
    "best_map50": None,
    "last_map50": None,
    "accepted": 0,
    "rejected": 0,
    "last_error": None,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_round_at": None,
    "rounds": 0,
}
_LOCK = threading.Lock()


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


def _train_one_generation(gen, start_weights):
    from ultralytics import YOLO

    proj = os.path.join(WORK, "runs")
    os.makedirs(proj, exist_ok=True)
    name = f"gen{gen:03d}"
    m = YOLO(start_weights)
    n_params = _param_count(m)
    t0 = time.time()
    r = m.train(
        data=DATA, epochs=EPOCHS, imgsz=IMGSZ, batch=BATCH, device=DEVICE,
        workers=4, plots=False, verbose=True, exist_ok=True,
        project=proj, name=name,
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


def _run_round():
    """跑一代进化。返回台账条目。"""
    with _LOCK:
        gen = STATE["generation"] + 1
    _set(phase=f"training gen{gen}", generation=gen)

    start = BEST if os.path.exists(BEST) else SEED
    trained = _train_one_generation(gen, start)

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
        "epochs": EPOCHS,
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
            _set(best_map50=restored, generation=max_gen,
                 accepted=len(accepted),
                 rejected=len(entries) - len(accepted),
                 rounds=len(entries))
            print(f"[evolve] 从台账恢复: 最优 mAP50={restored:.4f} "
                  f"(已采纳 {len(accepted)}/{len(entries)} 代, 下一代 gen{max_gen + 1})",
                  flush=True)

    print(f"[evolve] data={DATA} seed={SEED} work={WORK}", flush=True)
    print(f"[evolve] epochs={EPOCHS} batch={BATCH} imgsz={IMGSZ} device={DEVICE} "
          f"margin={MARGIN} cooldown={COOLDOWN}s", flush=True)

    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[evolve] 只读端点 :{PORT} /health /state /ledger /models", flush=True)

    _loop()


if __name__ == "__main__":
    main()
