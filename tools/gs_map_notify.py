#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_map_notify.py — 建图收尾哨兵: 一有最终资产就把结果发飞书 (只发一次)

老倪 2026-10-13 睡前指令: 「建完图, 发到飞书」。
设计 (按 unattended-pipeline-supervision 技能: 静默哨兵 + 只报一次):
  · 每 N 分钟由 cron 调一次, 平时**静默退出**(没结果不发、发过不再发)
  · 判据 = 最终资产就绪: <session>_model/quality_model.json 存在, 或 status.json 到终态
  · 发完落 marker 文件, 之后所有调用直接退出 ⇒ 不会刷屏
内容: 资产名 · 留出/训练 PSNR · 高斯数 · 数据量(取图/唯一画面/视点/视差) · 两级质检判定
      + 附渲染图(留出视角) + 页面链接 + **真话**(视点够不够/是不是走直线)
用法:
  python3 tools/gs_map_notify.py --session zmax_data/gs_assets/map_sess_20261013_2100
  python3 tools/gs_map_notify.py --session ... --dry             # 只看会发什么, 不发
  python3 tools/gs_map_notify.py --session ... --force           # 忽略 marker/marker 不判就绪
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

REPO = os.path.expanduser("~/zmax")
STATUS = os.path.join(REPO, "zmax_data/gs_map/status.json")


def rd(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="", help="会话目录(默认取 status.json 里的)")
    ap.add_argument("--dry", action="store_true", help="只打印要发的内容, 不真发")
    ap.add_argument("--force", action="store_true", help="不看就绪/已发标记, 直接发")
    a = ap.parse_args()

    st = rd(STATUS) or {}
    sess = a.session or st.get("session") or ""
    if not sess:
        print("没有会话目录, 退出", file=sys.stderr)
        return 0
    sess = os.path.abspath(os.path.expanduser(sess))
    tag = os.path.basename(sess)
    marker = os.path.join(REPO, "zmax_data/gs_map/_notify_%s.done" % tag)
    if os.path.exists(marker) and not a.force:
        return 0                                    # 已报过 ⇒ 静默

    model = sess + "_model"
    qm = os.path.join(model, "quality_model.json")
    rep = rd(qm)
    running = bool(st.get("running"))
    step = str(st.get("step") or "")
    if not rep and not a.force:
        if running and step not in ("done", "stopped", "done_data"):
            return 0                                # 还在跑 ⇒ 静默
        if step not in ("done", "stopped", "done_data"):
            return 0                                # 没到终态 ⇒ 静默
        # 到了终态但没有 model 质检 ⇒ 也报(如实说没出资产)
    if not os.path.isdir(model) and not a.force:
        return 0

    m = (rep or {}).get("model") or {}
    d = (rep or {}).get("data") or {}
    lines = []
    head = "🧊 建图完成" if rep else "🧊 建图收尾(未出资产)"
    lines.append("%s · %s" % (head, tag))
    lines.append("")
    if rep:
        lines.append("资产: %s" % os.path.basename(model))
        lines.append("留出视角 PSNR: %s dB · 训练视角: %s dB" % (m.get("psnr_holdout_db", "?"), m.get("psnr_train_db", "?")))
        lines.append("高斯: %s 个 · 步数: %s" % (m.get("n_gaussians", "?"), m.get("steps", "?")))
    else:
        lines.append("资产: 没出(model 质检缺失) — 数据集: %s" % os.path.basename(str(st.get("dataset") or "?")))
    dv = d.get("distinct_views")
    if dv is not None or d.get("unique_images") is not None:
        lines.append("数据: 唯一图 %s · 视点 %s · 视差 %s mm"
                     % (d.get("unique_images", "?"), dv, d.get("spread_mm", "?")))
    if st.get("verdict"):
        lines.append("数据集判定: %s" % str(st.get("verdict")).upper())
    # 同口径对照: 历史最好资产的留出 PSNR (老倪要"涨了还是没涨", 不只看单点数)
    try:
        cur = None
        if rep:
            cur = m.get("psnr_holdout_db")
        best, bestn = None, ""
        for pat in ("quality_model.json", "quality_report.json"):
            for p in glob.glob(os.path.join(REPO, "zmax_data/gs_assets/*", pat)):
                nm = os.path.basename(os.path.dirname(p))
                if nm == os.path.basename(model):
                    continue
                try:
                    mm = (rd(p) or {}).get("model", {}) or {}
                    v = mm.get("psnr_holdout_db")
                except Exception:                                          # noqa: BLE001
                    v = None
                if v and (best is None or v > best):
                    best, bestn = v, nm
        if best:
            if cur:
                rel = "涨" if cur > best + 0.3 else ("跌" if cur < best - 0.3 else "基本持平")
                lines.append("对照(同口径留出 PSNR): 历史最好 %.2f dB (%s) · 本次 %.2f dB ⇒ %s"
                             % (best, bestn, cur, rel))
            else:
                lines.append("对照: 历史最好 %.2f dB (%s) · 本次没出" % (best, bestn))
    except Exception:                                                      # noqa: BLE001
        pass
    lines.append("")
    lines.append("看: 手机/电脑开 http://192.168.23.23:8793/gsview (3D 可拖) · 工位页「🎥 实景查看器」")
    # 真话: 视点够不够 / 是不是走直线
    try:
        nv = int(dv or 0)
        if nv and nv < 100:
            lines.append("真话: 视点 %d 个(3DGS 建议 ≥100) ⇒ 目前是**低视点版**, 场景会偏糊; "
                         "明天绕同一件工件走一圈(15~20cm 一格)质量会明显上去" % nv)
    except Exception:
        pass
    lines.append("(老倪: 你说睡觉前定的, 建完自动发这条; 只发一次)")

    txt = "\n".join(lines)
    # 附一张渲染图(留出视角)
    img = ""
    for pat in ("renders/holdout_00.png", "renders/*.png", "*.png"):
        g = sorted(glob.glob(os.path.join(model, pat)))
        if g:
            img = g[0]
            break

    if a.dry:
        print(txt)
        print("--- 附图:", img or "(无)")
        return 0

    cmd = [sys.executable, os.path.join(REPO, "tools/feishu_send.py"), "--text", txt]
    if img:
        cmd = [sys.executable, os.path.join(REPO, "tools/feishu_send.py"), "--image", img, "--text", txt]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    ok = (p.returncode == 0) and ("\"ok\": true" in (p.stdout or "") or "ok" in (p.stdout or ""))
    print("[gs_map_notify] 发送 %s · rc=%s · %s" % ("成功" if ok else "失败", p.returncode,
                                                    (p.stdout or p.stderr or "")[-300:]), flush=True)
    if ok:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
