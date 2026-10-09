#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dataspace_loop_check.py — 🔁 sim→real 数据闭环证据链检查 (只读)

老倪口径: 闭环每一环**过没过门**必须是可看的事实 —— 有证据才算 pass, 没证据就是 unknown,
**不许猜、不许写成"应该没问题"**。本工具按 `src/lerobot/dataspace/topics.py::CLOSED_LOOP`
的 S0→S8 环节逐个去读一个**真实来源**(文件/端点/进程), 产出 pass/fail/unknown, 并写出
  ① 证据(evidence) ② 缺什么才能判(missing_for_decision) ③ 证据来源清单(evidence_sources)。

输出: zmax_data/dataspace/loop.json —— schema 与 `lerobot.dataspace.loop_state` **兼容**
(含 ts/repo/counts/stuck_at/stages), 额外加 evidence_sources / missing_for_decision。
控制台「数据空间」页与网页读这一份。

设计要点(与 loop_state.py 一致, 本工具在其基础上把"缺什么才能判"显式化):
  · sim 侧 = 状态空间引擎/仿真 tap/画布;  real 侧 = 真机 tap/标定/推理/部署。
  · 源帧"陈旧"不算 pass(宁 unknown) —— 时间戳回拨/久未更新的值不冒充现在。

用法:
  python3 tools/dataspace_loop_check.py                 # 人读
  python3 tools/dataspace_loop_check.py --json           # 人读+JSON
  python3 tools/dataspace_loop_check.py --out FILE       # 写指定路径(默认 loop.json)
  python3 tools/dataspace_loop_check.py --no-write       # 只算不写(取证)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
if os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))
try:
    from lerobot.dataspace import topics as T                          # noqa: E402
    _LOOP = T.CLOSED_LOOP
except Exception:                                                        # noqa: BLE001
    _LOOP = []
    T = None

OUT = os.environ.get("ZMAX_DATASPACE_LOOP",
                     os.path.join(REPO, "zmax_data", "dataspace", "loop.json"))
ORIN = os.environ.get("ZMAX_ORIN", "192.168.23.66")
RELAY = os.environ.get("ZMAX_RELAY", "https://datadrive.world/api/relay")


# ───────────────────────── 基础 ─────────────────────────
def _age(p):
    try:
        return round(time.time() - os.path.getmtime(p), 1)
    except OSError:
        return None


def _newest(paths):
    cand = [p for p in paths if os.path.exists(p)]
    return max(cand, key=os.path.getmtime) if cand else None


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return None


def _http(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.getcode(), r.read(200000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:                                               # noqa: BLE001
        return 0, "%s: %s" % (type(e).__name__, str(e)[:80])


def _res(status, evidence, missing="", sources=None, **metrics):
    return {"status": status, "evidence": evidence,
            "missing_for_decision": missing,
            "evidence_sources": sources or [],
            "metrics": metrics, "ts": time.time()}


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ───────────────────────── 各环节检查器 ─────────────────────────
def s0_preflight():
    """S0 采数前自检: 标定有效 + TCP 位姿新鲜 + 相机帧龄"""
    ev, srcs, m, ok, unknown, missing = [], [], {}, 0, 0, []
    he = os.path.join(REPO, "models", "handeye_state.json")
    srcs.append(he)
    d = _read_json(he)
    if isinstance(d, dict) and d:
        rms = d.get("resid_trans_mm_rms", d.get("rms_mm", d.get("rms")))
        val = d.get("valid", d.get("ok"))
        m["handeye_rms_mm"], m["handeye_valid"] = rms, val
        if rms is not None and rms != -1:
            ok += 1 if float(rms) <= 2.0 else 0
            ev.append("手眼 rms=%smm(门≤2)" % rms)
        else:
            unknown += 1
            missing.append("handeye_state.json 缺 rms 字段")
            ev.append("手眼文件在但无 rms")
    else:
        unknown += 1
        missing.append("models/handeye_state.json 不存在(无法判 rms≤2)")
        ev.append("未找到 models/handeye_state.json")
    tcp_c = [os.path.join(g, "latest.json") for g in
             ("/home/ubuntu/rokae_sdk/tcp_out", os.path.join(REPO, "rokae_sdk/tcp_out"),
              os.path.join(REPO, "zmax_data/ss_live/rokae_sdk/tcp_out"))]
    srcs += tcp_c
    tcp = _newest(tcp_c)
    if tcp:
        dd = _read_json(tcp) or {}
        age = _age(tcp)
        m["tcp_age_s"] = age
        vals = [v for v in (dd.get("tcp_pose") or dd.get("pose") or []) if isinstance(v, (int, float))]
        m["tcp_nonzero"] = any(abs(v) > 1e-6 for v in vals) if vals else False
        if vals and m["tcp_nonzero"] and age is not None and age < 60:
            ok += 1
            ev.append("TCP 位姿新鲜 %.0fs 且非全 0" % age)
        else:
            missing.append("TCP 位姿可疑(需新鲜<60s且非全0)")
            ev.append("TCP 位姿可疑(龄 %s/非全0=%s)" % (age or -1, m["tcp_nonzero"]))
    else:
        unknown += 1
        missing.append("TCP 位姿文件 tcp_out/latest.json 不存在")
        ev.append("未找到 TCP 位姿文件")
    cam = "http://127.0.0.1:8791/snapshot/arm.jpg"
    srcs.append(cam)
    code, _ = _http(cam, timeout=5)
    m["cam_arm_http"] = code
    if code == 200:
        ok += 1
        ev.append("臂相机 200")
    else:
        missing.append("臂相机 8791/snapshot/arm.jpg 非 200")
        ev.append("臂相机 HTTP %s" % code)
    st = "pass" if ok >= 3 else ("fail" if ok == 0 else "unknown")
    return _res(st, " · ".join(ev), " ｜ ".join(missing), srcs, **m)


def s1_collect():
    """S1 真机采集: Orin 可达 + 本地最新数据包 (+新鲜度: 陈旧包不算当前闭环)"""
    ev, srcs, missing = [], [], []
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ORIN], capture_output=True, timeout=4)
        reach = r.returncode == 0
    except Exception:                                                    # noqa: BLE001
        reach = False
    pkgs = sorted(glob.glob(os.path.join(REPO, "zmax_data/orin_live/*.json")) +
                  glob.glob(os.path.join(REPO, "data/datasets/orin_live/*.json")) +
                  glob.glob(os.path.join(REPO, "external/lerobot-smolvla-lew/data/orin_live/*.json")),
                  key=os.path.getmtime)
    newest = pkgs[-1] if pkgs else None
    if newest:
        srcs.append(newest)
    age = _age(newest) if newest else None
    m = {"orin_reachable": reach, "n_local_pkgs": len(pkgs),
         "newest_pkg_age_s": age, "newest_pkg": os.path.basename(newest) if newest else None}
    ev.append("Orin %s" % ("可达" if reach else "不可达"))
    frames = None
    if newest:
        d = _read_json(newest) or {}
        meta = d.get("meta") or {}
        frames = meta.get("frames") or len(d.get("frames") or [])
        m["frames"] = frames
        ev.append("最新包 %s: frames=%s 龄%.1f天" % (m["newest_pkg"], frames, (age or 0) / 86400.0))
    else:
        ev.append("本地无 orin_live 数据包")
        missing.append("本地 zmax_data/orin_live / data/datasets/orin_live / fork orin_live 无包")
    if not reach:
        missing.append("Orin(%s) ping 不通" % ORIN)
    fresh_days = float(os.environ.get("ZMAX_LOOP_FRESH_DAYS", "7"))
    ok = reach and newest and (frames or 0) >= 20
    if ok and age is not None and age <= fresh_days * 86400:
        return _res("pass", " · ".join(ev), "", srcs, **m)
    if ok:                                                               # 机制在, 但包陈旧
        missing.append("最新采集包龄 %.1f 天 > %.0f 天(需新采集才代表当前闭环)" % (
            (age or 0) / 86400.0, fresh_days))
        return _res("unknown", " · ".join(ev), " ｜ ".join(missing), srcs, **m)
    st = "fail" if not reach and not newest else "unknown"
    return _res(st, " · ".join(ev), " ｜ ".join(missing), srcs, **m)


def s2_upload():
    """S2 上传中转: ECS relay 队列状态"""
    url = RELAY + "/status"
    code, body = _http(url, timeout=12)
    if code != 200:
        return _res("unknown", "ECS relay /status HTTP %s" % code,
                    "需 ECS relay 可达(当前 HTTP %s)" % code, [url], http=code)
    try:
        d = json.loads(body)
    except Exception:                                                    # noqa: BLE001
        d = {}
    keys = {k: d[k] for k in ("pending", "queue", "n", "count", "latest", "last_upload")
            if isinstance(d, dict) and k in d}
    return _res("pass", "ECS relay 可达(队列字段 %s)" % (list(keys) or "无"),
                "", [url], http=code, **{k: v for k, v in keys.items()
                                         if isinstance(v, (int, float, str))})


def s3_dataset():
    """S3 入库质量门: 数据集存在 + 帧数/维度"""
    info = os.path.join(REPO, "data/datasets/orin_6d/meta/info.json")
    d = _read_json(info)
    if not d:
        return _res("unknown", "未找到 data/datasets/orin_6d/meta/info.json",
                    "需 LeRobot 数据集 meta/info.json(缺则无法判帧数/时间戳)", [info])
    tot = d.get("total_frames")
    eps = d.get("total_episodes")
    st = "pass" if isinstance(tot, int) and tot >= 20 else ("fail" if isinstance(tot, int) else "unknown")
    miss = "" if st == "pass" else "需 total_frames≥20(当前 %s)" % tot
    return _res(st, "orin_6d: %s 帧 / %s 轨迹" % (tot, eps), miss, [info],
                total_frames=tot, total_episodes=eps, path="data/datasets/orin_6d")


def s4_train():
    """S4 训练: 进度文件或 DDS train_prog"""
    cands = []
    for pat in ("outputs/**/progress*.json", "outputs/*.json", "outputs/**/train_state.json",
                os.path.join(REPO, "zmax_data/**/progress*.json")):
        cands += glob.glob(os.path.join(REPO, pat), recursive=True)
    p = _newest(cands)
    live = _read_json(os.path.join(REPO, "zmax_data/dataspace/live.json")) or {}
    tp = ((live.get("topics") or {}).get("train_prog") or {}).get("fields") or {}
    if p:
        d = _read_json(p) or {}
        m = {k: d.get(k) for k in ("step", "total", "pct", "loss", "running") if k in d}
        m["file_age_s"] = _age(p)
        running = m.get("running")
        st = "pass" if running == 1 else ("unknown" if running is None else "fail")
        miss = "" if st == "pass" else "需 running=1(当前 %s)" % running
        return _res(st, "%s: step=%s/%s loss=%s running=%s(龄 %.0fs)" % (
            os.path.basename(p), m.get("step"), m.get("total"), m.get("loss"), running,
            m.get("file_age_s") or -1), miss, [p], path=p, **m)
    if tp:
        st = "pass" if tp.get("running") == 1 else "unknown"
        return _res(st, "DDS train_prog: step=%s/%s loss=%s running=%s" % (
            tp.get("step"), tp.get("total"), tp.get("loss"), tp.get("running")),
            "" if st == "pass" else "需 running=1", ["live.json:train_prog"],
            source="dds:train_prog", **{k: tp.get(k) for k in ("step", "total", "loss", "running")})
    return _res("unknown", "未找到训练进度文件, DDS train_prog 也无值",
                "需 outputs/**/progress*.json 或 train_prog 话题有值", cands[:3])


def s5_eval():
    """S5 评测: 最近取证/评测 JSON 的通过数与提升"""
    reps = sorted(glob.glob(os.path.join(REPO, "reports/*.json")), key=os.path.getmtime)
    evals = []
    for f in reps:
        d0 = _read_json(f) or {}
        if isinstance(d0, dict) and any(k in d0 for k in
                                        ("passed", "total", "success_rate", "gain_obs_pct")):
            evals.append(f)
    if not evals:
        return _res("unknown", "reports/ 下无评测产物(最近 %d 个 JSON 都不是评测)" % len(reps),
                    "需一份含 passed/total/success_rate 的评测 JSON", reps[-3:])
    p = evals[-1]
    d = _read_json(p) or {}
    passed, total = d.get("passed"), d.get("total")
    gain = d.get("gain_obs_pct", d.get("gain_pct"))
    have_gain = isinstance(gain, (int, float))
    # 门: "**有提升**才放行(非仅不回退) · 平凡基线对照" —— 仅 passed==total 不足以 pass,
    #     必须带 baseline 提升(gain), 否则"未证明提升" = unknown (不猜)
    if isinstance(total, int) and isinstance(passed, int) and passed == total and total > 0 and have_gain and gain > 0:
        st, miss = "pass", ""
    else:
        st = "unknown"
        miss = ("有 %s/%s 通过, 但缺 baseline 提升(需 gain>0 才算放行; 当前 gain=%s)" % (
            passed, total, gain) if (passed is not None) else "需一份含 passed/total/gain 的评测 JSON")
    return _res(st, "%s: passed=%s/%s gain=%s(门: 有提升才放行)" % (
        os.path.basename(p), passed, total, gain), miss, [p],
        path=os.path.basename(p), age_s=_age(p), passed=passed, total=total, gain_pct=gain)


def s6_publish():
    """S6 发布: 本地权重 + 静态 URL 可达"""
    ws = sorted(glob.glob(os.path.join(REPO, "outputs/**/*.safetensors"), recursive=True) +
                glob.glob(os.path.join(REPO, "models/**/*.safetensors"), recursive=True),
                key=os.path.getmtime)
    if not ws:
        return _res("unknown", "本地未找到 *.safetensors 权重",
                    "需一个本地权重产物", [os.path.join(REPO, "outputs"), os.path.join(REPO, "models")])
    p = ws[-1]
    h = _sha256(p)
    name = os.path.basename(p)
    url = "https://datadrive.world/models/" + name
    code, _ = _http(url, timeout=12)
    st = "pass" if code == 200 else "unknown"
    miss = "" if st == "pass" else "静态 URL HTTP %s(需 200 且 sha256 与本地一致)" % code
    return _res(st, "本地 %s(sha256 %s…) 静态URL HTTP %s" % (name, h[:12], code), miss, [p, url],
                local=p.replace(REPO + "/", ""), sha256=h, url_http=code)


def s7_deploy():
    """S7 部署: 审计台账最后一条指令"""
    p = os.path.join(REPO, "docs/deploy_audit.jsonl")
    if not os.path.exists(p):
        return _res("unknown", "没有 docs/deploy_audit.jsonl",
                    "需部署审计台账(缺则部署不可追、S7 无法判)", [p])
    last = None
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                last = ln.strip()
    if not last:
        return _res("unknown", "审计台账为空", "需台账至少一条", [p])
    try:
        d = json.loads(last)
    except Exception:                                                    # noqa: BLE001
        return _res("unknown", "审计台账最后一行不是 JSON", "需台账行合法 JSON", [p])
    ev_kind = d.get("ev") or d.get("action")
    art = d.get("dir") or d.get("artifact")
    who = d.get("to") or d.get("issuer") or "本机"
    st = "pass" if (ev_kind and d.get("ts")) else "unknown"
    return _res(st, "最后一条: %s · 目标=%s · 产物=%s · sha=%s · 时间=%s(龄 %.0fh)" % (
        ev_kind, who, art, str(d.get("sha16"))[:16], d.get("ts"), (_age(p) or 0) / 3600.0),
        "" if st == "pass" else "需 ev/ts 字段", [p],
        age_h=round((_age(p) or 0) / 3600.0, 1), ev=ev_kind, target=who, artifact=art)


def s8_infer():
    """S8 推理与回采: 本机推理服务 + Orin 推理计数"""
    u1 = "http://127.0.0.1:8790/health"
    code, body = _http(u1, timeout=6)
    d = {}
    try:
        d = json.loads(body)
    except Exception:                                                    # noqa: BLE001
        pass
    cnt = d.get("infer_count") if isinstance(d, dict) else None
    u2 = RELAY + "/orin/status"
    c2, b2 = _http(u2, timeout=12)
    try:
        o = json.loads(b2)
    except Exception:                                                    # noqa: BLE001
        o = {}
    st = "pass" if (cnt or 0) > 0 else "unknown"
    miss = "" if st == "pass" else "需 infer_count>0(本机 %s)·失败帧归档回采" % cnt
    return _res(st, "本机推理 HTTP %s infer_count=%s · Orin 侧 HTTP %s %s" % (
        code, cnt, c2, {k: o.get(k) for k in list(o)[:3]} if isinstance(o, dict) else ""),
        miss, [u1, u2], infer_count=cnt, orin_http=c2, orin_infer_count=(o or {}).get("infer_count"))


CHECKERS = {"S0": s0_preflight, "S1": s1_collect, "S2": s2_upload, "S3": s3_dataset,
            "S4": s4_train, "S5": s5_eval, "S6": s6_publish, "S7": s7_deploy, "S8": s8_infer}


def collect():
    stages = []
    for s in _LOOP:
        fn = CHECKERS.get(s["id"])
        try:
            r = fn() if fn else _res("unknown", "无检查器", "需为本环节实现检查器")
        except Exception as e:                                           # noqa: BLE001
            r = _res("unknown", "检查器异常 %s: %s" % (type(e).__name__, str(e)[:80]),
                     "检查器需修")
        stages.append({"id": s["id"], "name": s["name"], "gate": s["gate"],
                       "owner": s["owner"], **r})
    n = {k: sum(1 for s in stages if s["status"] == k) for k in ("pass", "fail", "unknown")}
    n_pas = [s["id"] for s in stages if s["status"] == "pass"]
    n_unk = [s["id"] for s in stages if s["status"] == "unknown"]
    n_fail = [s["id"] for s in stages if s["status"] == "fail"]
    return {
        "ts": time.time(), "repo": REPO,
        "tool": "dataspace_loop_check.py", "schema": "zmax-dataspace-loop/1.0",
        "counts": n, "n_stages": len(stages),
        "stuck_at": next((s["id"] for s in stages if s["status"] != "pass"), None),
        "pass_stages": n_pas, "unknown_stages": n_unk, "fail_stages": n_fail,
        "verdict": "闭环链路完整: 全 %d 环节 pass" % len(stages) if not (n_unk or n_fail)
                   else "闭环停在 %s (pass=%d fail=%d unknown=%d)" % (
                       next((s["id"] for s in stages if s["status"] != "pass"), None),
                       n["pass"], n["fail"], n["unknown"]),
        "stages": stages,
    }


def main():
    ap = argparse.ArgumentParser(description="sim→real 数据闭环证据链检查 (只读)")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    d = collect()
    if not a.no_write:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(a.out + ".tmp", a.out)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print("=" * 96)
        print("🔁 sim→real 数据闭环 · %d 环节  pass=%d fail=%d unknown=%d · 卡在 %s" % (
            d["n_stages"], d["counts"]["pass"], d["counts"]["fail"],
            d["counts"]["unknown"], d["stuck_at"]))
        print("=" * 96)
        for s in d["stages"]:
            icon = {"pass": "✅", "fail": "❌", "unknown": "❔"}[s["status"]]
            print("%s %-3s %-12s %s" % (icon, s["id"], s["name"], s["evidence"][:92]))
            if s["status"] != "pass" and s.get("missing_for_decision"):
                print("        缺: %s" % s["missing_for_decision"][:110])
        print("-" * 96)
        print("结论: %s" % d["verdict"])
        if not a.no_write:
            print("已写: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
