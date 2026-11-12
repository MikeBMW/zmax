#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""site_snapshot.py — 现场快照器 (2026-11-12): 在断网/离场前把「现场真值」抄成离线可复算的一份。

为什么要它: 自主进化不能只吃仿真自造数据 —— 现场断掉以后, 真机视觉分布、位姿序列、相机、工控机
接口、Orin 驱动契约全都没了, 进化就退化成"自己跟自己玩"。本工具把现场**只读抄一份**,
进化在离线态照样能跑, 而且用的还是现场那套口径。

抄什么 (每项都记 字节数/来源/时间/帧龄, 缺就写"未采集 + 原因", **绝不补 0 或造数**):
  pose     机器人实际位姿时序 (8791 /pose, SDK 原生 p6 + quat, 与产线 /robot/tcp_pose 同口径)
  cam      各相机真帧 (8791 /snapshot/*.jpg) + 同帧检测框 (8791 /boxes ⇒ 弱标签)
  ar       AR 场景渲染帧 (8802 /frame.png) —— 进化的"看什么"就是它
  scene    scene/stats 等结构化现场描述
  aoi      工控机 AOI 接口探活 (10082/10083) + 配置
  cfg      标定/产品/画布/DDS 契约 (config/calib, config/products, canvas, topics)
  code     代码指纹 (git HEAD + 核心文件 md5) —— 离线复算要能对上"哪一版代码"
  orin     Orin 机器人驱动契约 (只读: ros2 topic list + /robot/tcp_pose 采样), 不可达就记原因

用法:
  gui-venv311/bin/python tools/site_snapshot.py --seconds 120 --frames 8
  gui-venv311/bin/python tools/site_snapshot.py --selftest      # 只验采集器, 不落大目录

产物: zmax_data/site_snapshot/<ts>/ + manifest.json (每项一条证据)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMS = (("arm", "http://127.0.0.1:8791/snapshot/arm.jpg"),
        ("local", "http://127.0.0.1:8791/snapshot/local.jpg"),
        ("overlay_arm", "http://127.0.0.1:8791/snapshot/overlay_arm.jpg"),
        ("overlay_local", "http://127.0.0.1:8791/snapshot/overlay_local.jpg"))
POSE = "http://127.0.0.1:8791/pose"
BOXES = "http://127.0.0.1:8791/boxes"
STATS = "http://127.0.0.1:8791/stats"
SCENE = "http://127.0.0.1:8791/scene.json"
AR = "http://127.0.0.1:8802/frame.png"

CFG_GLOBS = ("config/calib/*.json", "config/products/*.json", "config/topics/*.json",
             "data/database/zmax/sources/canvas/state_space_obs.json",
             "config/platform/dds_topic_types.json", "config/skills/*.json")
CODE_FILES = ("src/lerobot/middleware/nodes/impl/ss_obs.py",
              "src/lerobot/policies/left_right/state_space/su2.py",
              "src/lerobot/policies/left_right/state_space/quat_truth.py",
              "src/lerobot/engineering/exec/daemon.py",
              "tools/evolve_ar_world.py", "tools/ar_mujoco_clutter.py",
              "tools/ar_yolo_train_eval.py")


def _get(url, timeout=5.0):
    """返回 (bytes|None, 说明)。绝不抛, 让调用方按 ok=False 记账。"""
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            b = r.read()
            return b, "HTTP %d · %dB · %.0fms" % (r.status, len(b), (time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return None, "HTTP %d %s" % (e.code, e.reason)
    except Exception as e:                                                       # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:120])


def _md5(path):
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for ch in iter(lambda: f.read(1 << 20), b""):
                h.update(ch)
        return h.hexdigest()
    except Exception:                                                            # noqa: BLE001
        return None


def _git_head():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:                                                            # noqa: BLE001
        return None


class Snap:
    def __init__(self, out):
        self.out = out
        self.items = []
        os.makedirs(out, exist_ok=True)

    def save(self, name, kind, data, ext, note_ok=""):
        rel = os.path.join(kind, name + ext)
        p = os.path.join(self.out, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        self.items.append({"name": name, "kind": kind, "path": rel, "bytes": len(data),
                           "ts": time.time(), "ok": True, "note": note_ok})
        return p

    def miss(self, name, kind, why):
        self.items.append({"name": name, "kind": kind, "path": None, "bytes": 0,
                           "ts": time.time(), "ok": False, "note": "未采集: " + why})
        print("  ✗ %-22s %s" % (name, why))
        return None

    def fetch(self, name, kind, url, ext=".bin", timeout=5.0):
        b, why = _get(url, timeout)
        if b is None:
            return self.miss(name, kind, "%s (%s)" % (why, url))
        print("  ✓ %-22s %s" % (name, why))
        return self.save(name, kind, b, ext, why)


def capture_pose_series(sn: Snap, seconds: float, hz: float = 10.0):
    """位姿时序: 机器人实际位姿是离线复算的第一真值 (位置+姿态都在, 不是从速度反推的)。"""
    rows, t_end = [], time.time() + seconds
    n_fail = 0
    while time.time() < t_end:
        b, why = _get(POSE, timeout=2.0)
        if b is None:
            n_fail += 1
        else:
            try:
                d = json.loads(b.decode("utf-8"))
                d["_t"] = time.time()
                rows.append(d)
            except Exception:                                                    # noqa: BLE001
                n_fail += 1
        time.sleep(max(0.0, 1.0 / hz - 0.001))
    if not rows:
        return sn.miss("pose_timeseries", "pose", "整段拿不到位姿 (失败 %d 次)" % n_fail)
    p = sn.save("pose_timeseries", "pose",
                ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode(),
                ".jsonl", "%d 拍 · 失败 %d" % (len(rows), n_fail))
    xs = [r.get("xyz") for r in rows if isinstance(r.get("xyz"), list) and len(r["xyz"]) == 3]
    sm = {"n": len(rows), "fail": n_fail, "seconds": round(seconds, 2),
          "span_s": round(rows[-1]["_t"] - rows[0]["_t"], 2) if len(rows) > 1 else 0.0,
          "src": rows[-1].get("abc_src"), "units": "m / rad",
          "xyz_min": [round(min(c[i] for c in xs), 4) for i in range(3)] if xs else None,
          "xyz_max": [round(max(c[i] for c in xs), 4) for i in range(3)] if xs else None,
          "has_quat": sum(1 for r in rows if r.get("quat")) }
    sn.save("pose_summary", "pose", json.dumps(sm, ensure_ascii=False, indent=1).encode(), ".json")
    print("  ✓ pose_timeseries        %d 拍 / %.1fs / 有quat %d" % (sm["n"], sm["span_s"], sm["has_quat"]))
    return p


def capture_frames(sn: Snap, n_frames: int, gap: float):
    """相机真帧 + 同帧检测框 (弱标签: 框是现场在役模型给的, 标注来源必须写清, 不冒充人工标注)。"""
    got = 0
    for i in range(n_frames):
        stamp = time.strftime("%H%M%S")
        bx = _get(BOXES, timeout=3.0)[0]
        bxs = None
        if bx:
            try:
                bxs = json.loads(bx.decode("utf-8"))
            except Exception:                                                    # noqa: BLE001
                bxs = None
        for cam, url in CAMS:
            b, why = _get(url, timeout=4.0)
            if b is None:
                continue
            nm = "%02d_%s_%s" % (i, stamp, cam)
            sn.save(nm, "frames", b, ".jpg", why + " · 同帧框=" + ("有" if bxs else "无"))
            got += 1
            if bxs:
                weak = dict(bxs)
                weak["_weak_label"] = True
                weak["_label_src"] = "现场在役检测器 8791/boxes (弱标签, 非人工标注)"
                weak["_frame"] = nm + ".jpg"
                sn.save(nm, "labels", json.dumps(weak, ensure_ascii=False).encode(), ".json")
        if i < n_frames - 1:
            time.sleep(gap)
    print("  ✓ frames                  %d 张 (含 overlay)" % got)
    return got


def capture_orin(sn: Snap):
    """Orin 机器人驱动契约 (只读): 话题清单 + 一次 tcp_pose 采样。禁装包/禁下发。"""
    # 🔴 入口顺序: 产线 USB 网卡在位 ⇒ orin-lan(192.168.23.66); 拔了才走 orin-wifi(热点 DHCP)。
    #    实测 `Host orin` 指向热点 IP, 产线在场时它反而连不上 (2026-11-12 踩到, ssh 超时)。
    HOSTS = ("orin-lan", "orin-wifi", "orin")

    def sh(cmd, t=12):
        last = None
        for h in HOSTS:
            try:
                r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                                    h, cmd], capture_output=True, text=True, timeout=t)
                if r.returncode == 0 or (r.stdout or "").strip():
                    return (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr.strip() else ""), r.returncode
                last = (r.stderr or "").strip() or ("rc=%d" % r.returncode)
            except Exception as e:                                               # noqa: BLE001
                last = "%s: %s" % (type(e).__name__, e)
        return "所有入口都失败: %s" % last, -1
    out, rc = sh("source /opt/ros/humble/setup.bash 2>/dev/null; timeout 8 ros2 topic list 2>&1 | head -40")
    if rc != 0 or "ros2" not in out.lower() and not out.strip():
        return sn.miss("orin_topics", "orin", "ssh/ros2 不可达: %s" % out.strip()[:120])
    sn.save("orin_topics", "orin", out.encode(), ".txt", "只读 ros2 topic list")
    print("  ✓ orin_topics             %d 行" % len(out.splitlines()))
    out2, rc2 = sh("source /opt/ros/humble/setup.bash 2>/dev/null; timeout 8 ros2 topic echo /robot/tcp_pose --once 2>&1 | head -30")
    if out2.strip():
        sn.save("orin_tcp_pose_once", "orin", out2.encode(), ".txt",
                "只读一次采样 (与 8791 /pose 同口径可对账)")
        print("  ✓ orin_tcp_pose_once      %d 行" % len(out2.splitlines()))
    else:
        sn.miss("orin_tcp_pose_once", "orin", "echo 无输出")
    return None


def capture_aoi(sn: Snap):
    """工控机 AOI 探活 (禁 84/85, 只认 10082/10083)。只记录可达性与返回码, 不写假结论。"""
    # 🔴 实测 (2026-11-12): 10082/10083 是**本机 127.0.0.1** 在听 (ss -ltn 可核), 不是 192.168.23.23;
    #    .23.23 上这些端口 全部 Connection refused。先探本机, 再把工控机那侧如实记为不可达。
    for port in (10082, 10083):
        for host in ("127.0.0.1", "192.168.23.23"):
            b, why = _get("http://%s:%d/" % (host, port), timeout=3.0)
            tag = "aoi_%d%s" % (port, "" if host == "127.0.0.1" else "_plant")
            if b is None:
                sn.miss(tag, "aoi", "%s (%s:%d)" % (why, host, port))
            else:
                sn.save(tag, "aoi", b, ".txt", "%s via %s" % (why, host))
                break
    return None


def capture_config(sn: Snap):
    import glob
    n = 0
    for g in CFG_GLOBS:
        for p in sorted(glob.glob(os.path.join(ROOT, g))):
            rel = os.path.relpath(p, ROOT)
            try:
                b = open(p, "rb").read()
            except Exception:                                                    # noqa: BLE001
                continue
            sn.save(rel.replace("/", "_"), "cfg", b, ".json", "原路径 " + rel)
            n += 1
    print("  ✓ cfg                     %d 个配置文件" % n)
    return n


def capture_code(sn: Snap):
    head = _git_head()
    rows = {"git_head": head, "files": {}, "at": time.strftime("%F %T")}
    for f in CODE_FILES:
        rows["files"][f] = _md5(os.path.join(ROOT, f))
    sn.save("code_fingerprint", "code", json.dumps(rows, ensure_ascii=False, indent=1).encode(), ".json")
    print("  ✓ code_fingerprint        git=%s · %d 文件" % ((head or "?")[:8], len(rows["files"])))
    return head


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120.0, help="位姿时序时长")
    ap.add_argument("--frames", type=int, default=8, help="相机采样次数 (每次 4 路 + 同帧框)")
    ap.add_argument("--gap", type=float, default=3.0, help="采样间隔秒")
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true", help="只跑 3s/1 帧, 验采集链路")
    ap.add_argument("--only", default="", help="补采: 逗号分隔 pose,frames,http,aoi,orin,cfg,code (输出目录必须已存在)")
    a = ap.parse_args()
    if a.selftest:
        a.seconds, a.frames, a.gap = 3.0, 1, 0.5

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(ROOT, "zmax_data/site_snapshot", ts)
    sn = Snap(out)
    print("[snapshot] → %s" % out)
    t0 = time.time()

    only = {x.strip() for x in a.only.split(",") if x.strip()}
    want = (lambda k: (not only) or k in only)
    if want("pose"):
        capture_pose_series(sn, a.seconds)
    if want("frames"):
        capture_frames(sn, a.frames, a.gap)
    if want("http"):
        for name, url, ext in (("ar_frame", AR, ".png"), ("stats", STATS, ".json"),
                               ("scene", SCENE, ".json")):
            sn.fetch(name, "ar" if name == "ar_frame" else "scene", url, ext)
    if want("aoi"):
        capture_aoi(sn)
    if want("orin"):
        capture_orin(sn)
    if want("cfg"):
        capture_config(sn)
    if want("code"):
        capture_code(sn)

    # 补采 (--only) 时把新条目并进已有 manifest, 不覆盖历史
    mpath = os.path.join(out, "manifest.json")
    if only and os.path.exists(mpath):
        try:
            prev = json.load(open(mpath, encoding="utf-8"))
            keep = [x for x in prev.get("items", [])
                    if x.get("name") not in {y["name"] for y in sn.items if y.get("ok")}]
            sn.items = keep + sn.items
        except Exception:                                                        # noqa: BLE001
            pass

    ok = [x for x in sn.items if x["ok"]]
    bad = [x for x in sn.items if not x["ok"]]
    man = {"created_at": time.strftime("%F %T"), "epoch": time.time(),
           "seconds": round(time.time() - t0, 1), "dir": out,
           "n_items": len(sn.items), "n_ok": len(ok), "n_missing": len(bad),
           "kinds": sorted({x["kind"] for x in sn.items}),
           "missing": [{"name": x["name"], "why": x["note"]} for x in bad],
           "items": sn.items,
           "restore_hint": "离线复算: 位姿取 pose/pose_timeseries.jsonl · 视觉取 frames/ · "
                           "弱标签取 labels/ (注明非人工标注) · 代码版本对 code/code_fingerprint.json"}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print("\n[snapshot] 完成 %.1fs · %d 项 (OK %d / 未采集 %d) · 清单 manifest.json"
          % (man["seconds"], man["n_items"], len(ok), len(bad)))
    if bad:
        print("[snapshot] 未采集项 (如实记账, 不补数):")
        for x in bad[:8]:
            print("   - %-22s %s" % (x["name"], x["note"]))
    return 0 if len(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
