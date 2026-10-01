#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_map_run.py (v2) — **自动建图完整闭环**: L5 指导选点 → 移动 → 采集 → 建数据集 → 训练 → 质检

老倪(2026-10-01): 「机械臂自动运行空间的每个点, 顺序 1 到 7 点, 同时自主建图 3DGS」
               + 「建图是 L5 功能运行后, deepseek 给出环境理解, 指导 3DGS 建图,
                  一边移动机器人, 一边自己学环境, 一边建立场景视图」

链路(每一环都是既有真链路, 不新开通道):
  选点  tools/gs_l5_select.py   —— L5(DeepSeek 视觉)看当前画面 → 环境理解 + 下一步方向
                                  ⇒ 软件把"画面方向"翻成 base 系方向, 在**已示教可达点**里
                                    挑最贴合该方向、且最没拍过的点(理由与打分写进日志/状态)
  移动  POST 127.0.0.1:8793/ctl/move {skill:"L2.goto_spaceN"} —— 与页面按钮**同一条**
        授权+收口+执行器+安全裁决链; 到位判据 = TCP 真值 <3mm 且连续 1s 稳定(不靠超时猜)
  采集  tools/gs_capture.py     —— 臂上 D405 原始 JPEG + TCP 真值位姿逐帧配对(只读)
  建库  tools/gs_dataset.py     —— 按**图像内容 md5 去重** + 位姿取该图首现时刻(关键, 见下)
  训练  tools/run_gs_train.sh   —— 带 CUDA shim 环境(不然 gsplat 扩展载不到)
  质检  tools/gs_quality.py     —— 数据集健康 + 与"平凡基线"比; 不过门就停, 不把废资产当成果

⚠️ 实测教训(2026-10-01, 必须写进调用方认知):
  · 采集端按 8Hz 取图, 而相机有效出帧率低得多 ⇒ 同一张图会被连取十几次, 每次记一个**不同**
    TCP 位姿。不去重就是"同图配多位姿"的矛盾监督: 训练视角都拟合不上(实测训练视角 PSNR 16dB、
    留出 11~13dB, **低于"填常数"平凡基线**), 但日志 loss 看着还在降。⇒ 建库必须去重, 且用
    gs_quality 判定"是否真的建出东西"再来当真。
  · 机械臂大部分时间可能是**静止**的(实测中位速度 0mm/s) ⇒ 扫场若蹲点不动, 视点/视差都不够,
    3DGS 出不来。⇒ 本闭环按"多点移动 + 每点采集"跑, 并在质检里看"真正不同视点"数。

模式:
  --rounds N --targets l5      L5 指导选点(每轮重新看画面, 边移动边学)
  --rounds N --targets spaces  固定顺序 space1..N(兼容旧行为, 也是 L5 不可用时的兜底)
  --order fixed|novelty        spaces 模式下的顺序: 固定序 / 按"最没拍过"优先
  --dry-run                    不移动: 用当前位姿当"到位", 走完 采集→建库→质检(验证链路)
  --from-recording <会话目录>   用已有录像重跑 建库→质检(→训练), 完全不动臂
状态文件 ~/zmax_data/gs_map/status.json(页面 /ctl/gs_map 轮询), 结束附 质量门 结果与资产路径。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = "/home/ubuntu/zmax"
PY = "/home/ubuntu/gs-venv/bin/python"
GS = os.path.expanduser("~/zmax_data/gs_assets")
ROOT = os.path.expanduser("~/zmax_data/gs_map")
STATUS = os.path.join(ROOT, "status.json")
POSE = os.path.expanduser("~/zmax_data/rokae_sdk/tcp_out/latest.json")
SP = os.path.join(REPO, "data/skills/l2_atomic/space_points.json")
SKILLS = os.path.join(REPO, "data/skills/l2_atomic/ctl_abs_skills.json")
MIN_TRAIN_VIEWS = 30      # 真正不同视点少于这个数就别训(浪费 GPU 且出不来资产)


def now():
    return time.strftime("%H:%M:%S")


def w(st, line=""):
    os.makedirs(ROOT, exist_ok=True)
    st["ts"] = time.strftime("%F %T")
    if line:
        st.setdefault("log", []).append("[%s] %s" % (now(), line))
        st["log"] = st["log"][-60:]
        print("[%s] %s" % (now(), line), flush=True)
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATUS)


def read_json(p, timeout=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def pose():
    d = read_json(POSE)
    if not d:
        return None
    try:
        return [float(d["x"]), float(d["y"]), float(d["z"])]
    except Exception:
        return None


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def api_get(path, timeout=8):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8793" + path, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "err": str(e)[:120]}


def api_post(path, body, timeout=30):
    req = urllib.request.Request("http://127.0.0.1:8793" + path, method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "msg": str(e)[:150]}


def armed():
    """真动授权真源(8793 /ctl/status)。读不到 ⇒ 如实当"未授权", 不猜。"""
    s = api_get("/ctl/status")
    if isinstance(s, dict):
        for k in ("motion_armed", "armed"):
            if k in s:
                return bool(s[k]), s
        for k in ("auth", "ctl"):
            if isinstance(s.get(k), dict) and "armed" in s[k]:
                return bool(s[k]["armed"]), s
    return None, s


# ----------------------------------------------------------------- 目标点目录

def catalog():
    """可执行目标点目录: {skill: {pos, quat, desc}} —— 来自空间点真源 + 绝对运动白名单"""
    pts = read_json(SP) or {}
    out = {}
    for nm, v in (pts.get("points") or {}).items():
        if isinstance(v, dict) and v.get("pos"):
            out["L2.goto_" + nm] = {"pos": [float(x) for x in v["pos"]],
                                    "quat": v.get("quat"), "desc": v.get("desc", "")}
    sk = (read_json(SKILLS) or {}).get("skills") or {}
    for nm in sk:
        if nm in out or not nm.startswith("L2."):
            continue
        out.setdefault(nm, {"pos": None, "quat": None, "desc": sk[nm]})
    return out


def pick_by_direction(cat, cur, visited, dirs, min_align=0.30):
    """L5 给方向 → 在可达点里挑最贴合方向 + 最没拍过的点。
    dirs: L5 的方向向量列表(base 系, 已按优先级排序)。返回 (skill, info) 或 (None, 理由)。"""
    best, best_s, best_info = None, -1e9, {}
    for skill, meta in cat.items():
        p = meta.get("pos")
        if not p or skill in visited:
            continue
        v = [p[i] - cur[i] for i in range(3)]
        n = sum(x * x for x in v) ** 0.5
        if n < 1e-6:
            continue
        v = [x / n for x in v]
        align = max(float(sum(v[i] * d[i] for i in range(3))) for d in dirs) if dirs else 0.0
        if align < min_align:
            continue
        nov = min([dist(p, q) for q in visited.values()], default=9.9)
        s = 1.5 * align + 0.5 * min(nov, 1.0)
        if s > best_s:
            best, best_s = skill, s
            best_info = {"align": round(align, 3), "novelty_m": round(nov, 3), "score": round(s, 3),
                         "pos": [round(x, 4) for x in p]}
    return (best, best_info) if best else (None, {"reason": "没有可达点与该方向对齐(align<%.2f)" % min_align})


def pick_novelty(cat, visited):
    """覆盖度兜底: 挑离已访问视点最远的可达点"""
    best, bd = None, -1
    for skill, meta in cat.items():
        p = meta.get("pos")
        if not p or skill in visited:
            continue
        d = min([dist(p, q) for q in visited.values()], default=9.9)
        if d > bd:
            best, bd = skill, d
    return best, {"novelty_m": round(bd, 3), "reason": "覆盖度兜底: 该点离已访问视点最远"}


# ----------------------------------------------------------------- 各阶段

def run(cmd, timeout=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)


def l5_select(sess_or_ds, st, k=3):
    op = os.path.join(sess_or_ds, "l5_select.json")
    p = run([PY, os.path.join(REPO, "tools/gs_l5_select.py"), "--session", sess_or_ds,
             "--k", str(k), "--out", op], timeout=420)
    d = read_json(op)
    if not d:
        w(st, "⚠️ L5 选点没出结果: %s" % ((p.stderr or p.stdout or "")[-140:]))
    return d or {}, op


def move_and_wait(skill, tgt, timeout=240):
    j = api_post("/ctl/move", {"skill": skill, "arm": 1, "speed": 8, "by": "自动建图(L5选点)"})
    if not j.get("ok"):
        return False, 0.0, "下发被拒: %s" % str(j.get("msg") or j.get("err") or j)[:130]
    t0 = time.time()
    stable = None
    while time.time() - t0 < timeout:
        p = pose()
        if p and tgt and dist(p, tgt) < 0.003:
            stable = stable or time.time()
            if time.time() - stable >= 1.0:
                return True, dist(p, tgt), ""
        else:
            stable = None
        time.sleep(0.2)
    p = pose()
    return False, (dist(p, tgt) if p else -1.0), "未到位(超时 %ds)" % timeout


def capture(sess, secs):
    return run([PY, os.path.join(REPO, "tools/gs_capture.py"), "--out", sess, "--secs", str(secs)],
               timeout=secs + 180)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=7)
    ap.add_argument("--targets", choices=["l5", "spaces"], default="l5")
    ap.add_argument("--order", choices=["fixed", "novelty"], default="fixed")
    ap.add_argument("--dwell", type=float, default=float(os.environ.get("GS_DWELL_S", "8")))
    ap.add_argument("--steps", type=int, default=int(os.environ.get("GS_STEPS", "30000")))
    ap.add_argument("--train", action="store_true", default=True)
    ap.add_argument("--no-train", dest="train", action="store_false")
    ap.add_argument("--dry-run", action="store_true", help="不移动(用当前位姿当到位), 验证链路")
    ap.add_argument("--from-recording", default="", help="用已有会话重跑 建库→质检(不动臂)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    tag = args.tag or time.strftime("%Y%m%d_%H%M%S")
    st = {"running": True, "step": "start", "session": "", "mode":
          ("recording" if args.from_recording else ("dry-run" if args.dry_run else "live")),
          "targets": args.targets, "rounds": args.rounds, "log": []}

    # ---------- 录制重跑模式: 只建库→质检(→训练) ----------
    if args.from_recording:
        sess = os.path.abspath(os.path.expanduser(args.from_recording))
        st["session"] = sess
        w(st, "录制重跑: %s" % sess)
        return finish(sess, sess + "_ds", st, args, train_only_ds=True)

    ds = os.path.join(GS, "map_%s" % tag)
    sess = os.path.join(GS, "map_sess_%s" % tag)
    st["session"] = sess
    os.makedirs(sess, exist_ok=True)

    # ---------- 真动前置: 授权真源 ----------
    if not args.dry_run:
        a, raw = armed()
        if a is None:
            st.update(running=False, status_line="读不到真动授权(8793 /ctl/status) ⇒ 不动作, 如实停")
            w(st, "⛔ " + st["status_line"])
            return 1
        if not a:
            st.update(running=False, status_line="当前**未授权**真动(motion_armed=false) ⇒ 不发任何动作")
            w(st, "⛔ " + st["status_line"])
            return 1
        w(st, "真动授权已确认(motion_armed=true)")

    cat = catalog()
    w(st, "可达目标点 %d 个(空间点真源 + 绝对运动白名单) · 模式=%s · %d 轮 × 采集 %.0fs"
      % (len(cat), args.targets, args.rounds, args.dwell))

    visited = {}
    for i in range(1, args.rounds + 1):
        st.update(step="select", status_line="(%d/%d) 选点…" % (i, args.rounds))
        w(st)
        skill = None
        why = ""
        if args.targets == "l5":
            sel, sp = l5_select(sess, st, 3)
            dirs = []
            # L5 的"画面方向"在 gs_l5_select 里已翻成 base 系候选点 ⇒ 用候选点方向当方向
            for c in (sel.get("candidates") or []):
                p = c.get("pos")
                if not p:
                    continue
                v = [p[k] - (pose() or p)[k] for k in range(3)]
                n = sum(x * x for x in v) ** 0.5
                if n > 1e-6:
                    dirs.append([x / n for x in v])
            if dirs:
                skill, info = pick_by_direction(cat, pose() or [0, 0, 0], visited, dirs)
                why = "L5 方向匹配 %s" % json.dumps(info, ensure_ascii=False)
            else:
                skill, info = pick_novelty(cat, visited)
                why = "L5 无有效方向 ⇒ %s" % json.dumps(info, ensure_ascii=False)
            w(st, "选点: %s (%s)" % (skill or "无", why))
        if not skill and args.targets == "spaces":
            order = sorted([k for k in cat if k.startswith("L2.goto_space")])
            if args.order == "novelty":
                skill, info = pick_novelty({k: cat[k] for k in order}, visited)
                why = json.dumps(info, ensure_ascii=False)
            else:
                for k in sorted([k for k in cat if k.startswith("L2.goto_space")]):
                    if k not in visited and cat[k].get("pos"):
                        skill, why = k, "固定序"
                        break
                if not skill:
                    why = "固定序里没有「有已知位姿且未访问」的点"
        if not skill:
            skill, info = pick_novelty(cat, visited)
            why = "兜底: %s" % json.dumps(info, ensure_ascii=False)
        if not skill:
            st.update(running=False, status_line="没有可去的目标点(都访问过了?)")
            w(st, "⛔ " + st["status_line"])
            break
        tgt = cat[skill].get("pos")

        st.update(step="move", status_line="(%d/%d) 去 %s" % (i, args.rounds, skill))
        if args.dry_run:
            p = pose()
            ok, dd, err = (p is not None), 0.0, ("dry-run: 不移动" if p else "读不到 TCP 位姿")
            w(st, "  (dry-run) 不移动, 用当前位姿 %s" % (p,))
        else:
            ok, dd, err = move_and_wait(skill, tgt)
        if not ok:
            st.update(running=False, status_line="%s 未成功: %s" % (skill, err))
            w(st, "⛔ " + st["status_line"])
            return 1
        w(st, "  ✓ %s 到位(偏差 %.1fmm)" % (skill, dd * 1000))
        visited[skill] = pose() or tgt or [0, 0, 0]

        st.update(step="capture", status_line="(%d/%d) 采集 %.0fs…" % (i, args.rounds, args.dwell))
        p = capture(sess, args.dwell)
        if p.returncode != 0:
            st.update(running=False, status_line="采集失败: %s" % ((p.stderr or p.stdout or "")[-120:]))
            w(st, "⛔ " + st["status_line"])
            return 1
        w(st, "  采集中…")

    return finish(sess, ds, st, args)


def finish(sess, ds, st, args, train_only_ds=False):
    """建数据集(去重) → 质检门 → (过门才)训练 → 质检门 → 状态"""
    st.update(step="dataset", status_line="建数据集(按图像内容去重)…")
    w(st)
    p = run([PY, os.path.join(REPO, "tools/gs_dataset.py"), "--session", sess, "--out", ds,
             "--max-frames", "400"], timeout=1800)
    if p.returncode != 0:
        st.update(running=False, status_line="建数据集失败: %s" % ((p.stderr or p.stdout or "")[-160:]))
        w(st, "⛔ " + st["status_line"])
        return 1
    w(st, "  数据集 → %s" % ds)

    st.update(step="quality_data", status_line="数据集质检(门)…")
    w(st)
    q1 = os.path.join(ds, "quality_data.json")
    p = run([PY, os.path.join(REPO, "tools/gs_quality.py"), "--dataset", ds, "--session", sess,
             "--json", q1], timeout=1800)
    rep = read_json(q1) or {}
    v = rep.get("verdict", "?")
    nv = int((rep.get("data") or {}).get("distinct_views") or 0)
    w(st, "  数据集判定: %s · 真正不同视点 %d" % (v.upper(), nv))
    if v == "fail":
        st.update(running=False, step="stopped", status_line="数据集没过门 ⇒ 不训练(避免白烧 GPU)",
                  verdict=v, dataset=ds, quality=q1)
        w(st, "⛔ 数据集没过门, 停")
        return 1
    if nv < MIN_TRAIN_VIEWS:
        st.update(running=False, step="stopped", verdict=v, dataset=ds, quality=q1,
                  status_line="真正不同视点只有 %d 个(<%d) ⇒ 训也出不来, 不烧 GPU"
                              "(要资产: 增加移动/采集轮数, 让相机真的换位置)" % (nv, MIN_TRAIN_VIEWS))
        w(st, "⛔ " + st["status_line"])
        return 1

    if not args.train:
        st.update(running=False, step="done_data", status_line="数据集就绪(未训练): %s" % os.path.basename(ds),
                  verdict=v, dataset=ds, quality=q1)
        w(st, "完成(未训练)")
        return 0

    model = sess + "_model"
    st.update(step="train", status_line="训练 3DGS %d 步(日志 train.log)…" % args.steps)
    w(st)
    tl = os.path.join(model, "train.log")
    os.makedirs(model, exist_ok=True)
    with open(tl, "w", encoding="utf-8") as lf:
        p = subprocess.run(["bash", os.path.join(REPO, "tools/run_gs_train.sh"), "--data", ds,
                            "--out", model, "--steps", str(args.steps), "--eval-every",
                            str(max(1500, args.steps // 10)), "--holdout", "20",
                            "--refine-stop", str(int(min(args.steps, 30000) * 0.4))],
                           stdout=lf, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        st.update(running=False, status_line="训练失败, 见 %s" % tl)
        w(st, "⛔ " + st["status_line"])
        return 1

    st.update(step="quality_model", status_line="训练产物质检(门)…")
    w(st)
    q2 = os.path.join(model, "quality_model.json")
    run([PY, os.path.join(REPO, "tools/gs_quality.py"), "--dataset", ds, "--session", sess,
         "--model", model, "--json", q2], timeout=1800)
    rep2 = read_json(q2) or {}
    v2 = rep2.get("verdict", "?")
    m = rep2.get("model", {})
    good = (v2 != "fail")
    st.update(running=False, step="done", verdict=v2,
              status_line=("✅ 建图完成(过门): %s" % os.path.basename(model)) if good else
                           ("⚠️ 训练完成但**没过门**(不作成果): 留出 PSNR %s dB vs 平凡基线 %s dB"
                            % (m.get("psnr_holdout_db"), m.get("trivial_baseline_db"))),
              model=model, dataset=ds, quality=q2,
              gs={"ply": os.path.join(model, "gs.ply"), "splat": os.path.join(model, "gs.splat")},
              metrics={"psnr_holdout_db": m.get("psnr_holdout_db"), "psnr_train_db": m.get("psnr_train_db"),
                       "trivial_baseline_db": m.get("trivial_baseline_db"),
                       "n_gaussians": m.get("n_gaussians")})
    w(st)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
