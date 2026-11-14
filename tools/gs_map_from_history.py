#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_map_from_history.py — 550C 用历史数据建图 (零运动 · 不需要真动授权)

老倪 2026-11-13: 「建图必须能够开始」「你也可以利用历史数据建图」「先把功能开发完整, 我先不授权」

为什么要这条:
  gs_map_run.py 的自动走点要真机运动 = 要 8793 授权窗口; 现场没授权时"建图"就只能空转。
  而 550C 上已经躺着大量历史采集会话 (gs_autocap/sessions/*, 每个都带 images/ + cameras.json,
  位姿是采集当时的 TCP 真值 + 手眼外参) ⇒ 这些数据**本身就够建一张图**, 不需要臂动。

做的事 (每一环都有落盘证据, 不假装):
  ① 选数据: --session <gs_autocap 会话> 或 --ds <已是数据集> 或 --latest (取最新有帧的会话)
  ② 建数据集: 会话只有帧+位姿时先用 gs_dataset.py 做去畸变+最远点选帧(去重), 已有 cameras.json 的直接用
  ③ 排队训练: 打包 dataset.tar.gz POST 到本机 gs_train_service (127.0.0.1:8814/train) —— 走服务队列, 不抢 XPU
  ④ 收尾: 轮询 /job?id 直到出结果, 把资产(gs.ply/splat) 和 PSNR 记进 <out>/map_asset.json,
     并写一份与 4060 同 schema 的 status.json, 页面/网关都能读

用法:
  python3 gs_map_from_history.py --latest --steps 3000
  python3 gs_map_from_history.py --session /home/intel/gs_autocap/sessions/20261113_153619_ed7d --steps 3000
  python3 gs_map_from_history.py --ds /home/intel/gs_train_service_intel/jobs/xxx/ds --dry  # 只体检不打训练
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

TRAIN = os.environ.get("GS_TRAIN_URL", "http://127.0.0.1:8814")
TOOLS = os.path.dirname(os.path.abspath(__file__))
PY = os.environ.get("GS_PY", "/home/intel/gsxpu-venv/bin/python")
WORK = os.path.expanduser("~/zmax_map/gs_sess")
STATUS = os.path.expanduser("~/zmax_data/gs_map/status.json")


def now() -> str:
    return time.strftime("%H:%M:%S")


def jget(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def post_tar(url: str, tar_path: str, timeout: float = 120.0):
    """multipart/form-data 上传 dataset.tar.gz —— 与 gs_train_service_intel.py 的 /train 契约一致。"""
    boundary = "----zmax550c%d" % int(time.time() * 1000)
    fn = os.path.basename(tar_path)
    head = ("--%s\r\nContent-Disposition: form-data; name=\"dataset\"; filename=\"%s\"\r\n"
            "Content-Type: application/gzip\r\n\r\n" % (boundary, fn)).encode()
    tail = ("\r\n--%s--\r\n" % boundary).encode()
    body_head = head
    size = os.path.getsize(tar_path)
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    req.add_header("Content-Length", str(len(body_head) + size + len(tail)))
    import http.client
    from urllib.parse import urlparse
    u = urlparse(url)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    conn.putrequest("POST", u.path or "/")
    conn.putheader("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    conn.putheader("Content-Length", str(len(body_head) + size + len(tail)))
    conn.endheaders()
    conn.send(body_head)
    with open(tar_path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            conn.send(chunk)
    conn.send(tail)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return json.loads(raw)
    except Exception:
        return {"ok": False, "err": "train 服务返回非 JSON: %s" % raw[:200]}


def write_status(d: dict):
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    d = dict(d)
    d["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATUS)


def pick_latest() -> str:
    """挑最新一个**真有帧**的采集会话(空会话不算)。"""
    for s in sorted(glob.glob(os.path.expanduser("~/gs_autocap/sessions/*")), reverse=True):
        img = os.path.join(s, "images")
        if os.path.isdir(img) and any(f.endswith(".jpg") for f in os.listdir(img)[:50]):
            return s
    return ""


def has_ds(d: str) -> bool:
    return os.path.exists(os.path.join(d, "cameras.json")) and \
        os.path.isdir(os.path.join(d, "images")) and \
        any(f.endswith(".jpg") for f in os.listdir(os.path.join(d, "images"))[:50])


def build_ds(session: str, out_ds: str, max_frames: int) -> tuple[bool, str]:
    """会话 → 数据集: 用 gs_dataset.py (去畸变 + 位姿最远点选帧); 失败就如实返回原因。"""
    ds_py = os.path.join(TOOLS, "gs_dataset.py")
    if not os.path.exists(ds_py):
        return False, "找不到 gs_dataset.py"
    cmd = [PY, ds_py, "--session", session, "--out", out_ds, "--max-frames", str(max_frames)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return False, ((p.stderr or p.stdout or "")[-300:]).strip()
    return has_ds(out_ds), "gs_dataset %.0fs" % (time.time() - t0)


def make_tar(ds: str, tar_path: str) -> int:
    n = 0
    with tarfile.open(tar_path, "w:gz") as tf:
        for name in ("cameras.json", "transforms.json", "meta.json", "depth"):
            p = os.path.join(ds, name)
            if os.path.exists(p):
                tf.add(p, arcname=name)
        img_dir = os.path.join(ds, "images")
        for f in sorted(os.listdir(img_dir)):
            if not f.endswith(".jpg"):
                continue
            tf.add(os.path.join(img_dir, f), arcname="images/" + f)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="", help="gs_autocap 采集会话目录")
    ap.add_argument("--ds", default="", help="已经是数据集(含 cameras.json + images/)的目录")
    ap.add_argument("--latest", action="store_true", help="自动取最新一个有帧的采集会话")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--max-frames", type=int, default=400, help="建数据集时最多选多少帧(最远点贪心)")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry", action="store_true", help="只做数据体检+打包, 不提交训练(不占 XPU)")
    ap.add_argument("--wait", type=float, default=0, help="训练提交后最多等多少秒(0=不等, 只看排队)")
    a = ap.parse_args()

    tag = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.abspath(a.out or os.path.join(WORK, "history_%s" % tag))
    os.makedirs(out, exist_ok=True)
    st = {"running": True, "step": "select", "mode": "history", "session": "", "ds": "",
          "out": out, "steps": a.steps, "log": [], "source": ""}

    def log(msg: str):
        st["log"].append("[%s] %s" % (now(), msg))
        st["log"] = st["log"][-40:]
        write_status(dict(st, status_line=msg))
        print("[%s] %s" % (now(), msg), flush=True)

    # ① 选数据
    src = a.ds or a.session or (pick_latest() if a.latest else "")
    if not src:
        st.update(running=False, step="done", status_line="没有可用的历史数据(既没 --ds/--session, 也没找到有帧的会话)")
        write_status(st)
        log("⛔ " + st["status_line"])
        return 2
    src = os.path.abspath(os.path.expanduser(src))
    st["source"] = src
    log("数据源: %s" % src)

    # ② 数据集
    if has_ds(src):
        ds = src
        n_img = len([f for f in os.listdir(os.path.join(ds, "images")) if f.endswith(".jpg")])
        log("已是数据集: %d 帧 (直接用, 不再去重)" % n_img)
    else:
        st["step"] = "dataset"
        ds = os.path.join(out, "ds")
        ok, why = build_ds(src, ds, a.max_frames)
        if not ok:
            st.update(running=False, step="done", status_line="建数据集失败: %s" % why[:160])
            write_status(st)
            log("⛔ " + st["status_line"])
            return 3
        n_img = len([f for f in os.listdir(os.path.join(ds, "images")) if f.endswith(".jpg")])
        log("建数据集 OK: %d 帧 (%s)" % (n_img, why))
    st["ds"] = ds
    cam = os.path.join(ds, "cameras.json")
    try:
        cj = json.load(open(cam, encoding="utf-8"))
        st["cameras"] = len(cj.get("frames") or cj or [])
    except Exception as e:                                   # noqa: BLE001
        log("⚠️ cameras.json 读不出: %r" % (e,))

    # ③ 打包 + 提交
    st["step"] = "pack"
    tar_path = os.path.join(out, "dataset.tar.gz")
    n_tar = make_tar(ds, tar_path)
    st["tar_mb"] = round(os.path.getsize(tar_path) / 1e6, 1)
    log("打包 %d 帧 → %s (%.1f MB)" % (n_tar, os.path.basename(tar_path), st["tar_mb"]))
    if n_tar < 30:
        st.update(running=False, step="done", status_line="帧数 %d < 30 ⇒ 3DGS 建不出结构, 如实停" % n_tar)
        write_status(st)
        log("⛔ " + st["status_line"])
        return 4
    if a.dry:
        st.update(running=False, step="done", status_line="[dry] 数据+打包就绪, 未提交训练")
        write_status(st)
        log("✅ " + st["status_line"])
        return 0

    st["step"] = "submit"
    try:
        r = post_tar(TRAIN + "/train", tar_path)
    except Exception as e:                                   # noqa: BLE001
        st.update(running=False, step="done", status_line="提交训练失败: %r" % (e,))
        write_status(st)
        log("⛔ " + st["status_line"])
        return 5
    jid = (r or {}).get("id") or (r or {}).get("job") or ""
    st["job_id"] = jid
    log("已提交训练: %s (steps=%d)" % (jid or r, a.steps))

    # ④ 等结果
    if a.wait > 0 and jid:
        st["step"] = "train"
        t_end = time.time() + a.wait
        last = ""
        while time.time() < t_end and st["running"]:
            try:
                j = jget("%s/job?id=%s" % (TRAIN, jid))
            except Exception as e:                           # noqa: BLE001
                log("⚠️ 轮询失败: %r" % (e,))
                time.sleep(5)
                continue
            line = "%s %s" % (j.get("state"), j.get("msg") or "")
            if line != last:
                last = line
                log("训练: " + line)
            if str(j.get("state")) in ("done", "error", "failed"):
                st["train"] = j
                st["step"] = "wrap"
                break
            time.sleep(8)

    # 收尾: 资产记录
    asset = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": src, "ds": ds,
             "job_id": jid, "steps": a.steps, "out": out}
    tr = st.get("train") or {}
    for k in ("psnr", "psnr_holdout_db", "n_gaussians", "splat_bytes", "secs"):
        if k in tr:
            asset[k] = tr[k]
    with open(os.path.join(out, "map_asset.json"), "w", encoding="utf-8") as f:
        json.dump(asset, f, ensure_ascii=False, indent=1)
    st["asset"] = os.path.join(out, "map_asset.json")
    st.update(running=False, step="done",
              status_line=("训练完成 · PSNR %s dB" % tr.get("psnr") if tr else
                           "已提交训练(job %s) —— 完成与否看 8814 /job, 这里不假装" % (jid or "?")))
    write_status(st)
    log("✅ " + st["status_line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
