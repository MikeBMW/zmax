# -*- coding: utf-8 -*-
"""bridge_episode_path.py — 一整轮仿真轨迹 → **一条**多点路径, 平顺且不叠队

老倪 2026-10-18: 「你得保证平顺啊」「幅度小一些, 不要走太远」「你怎么不动了」

为什么这样才平顺 (实测):
  · 一条 move-rel = 一段直线, 走完就停 ⇒ 走一段停一段 (一顿一顿)
  · 一次性 append 多点 + **一次** moveStart ⇒ 控制器一口气走完整条 (实测 10 点 50mm/2.8s, 残差 0.0mm)

两条硬规矩 (都是实测踩出来的):
  ① 模板不许"自我衰减": 自动录到的是上一轮实际走的小路径, 越跑越小 ⇒ 用 --template 指定
     仿真真值模板 (capture_truth_template.py 生成), 并加 --no-record。
  ② 不许叠队: 上一条 path 的**回执**没回来 (agent_result 同 id) 就不发下一条。
     叠两条的实测后果是"越走越快、越走越远", 包络闸被顶穿。
  ③ 总行程硬上限 --max-path mm: 不管 scale 怎么填, 一轮走的直线距离不超过它。

用法:
  ./gui-venv311/bin/python tools/bridge_episode_path.py \\
      --template zmax_data/ss_live/episode_template_truth.json --no-record \\
      --max-path 40 --dur-scale 0.22 --npts 50 --band 60
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "tools"))
try:
    import fence_store as FS          # 🧱 3D 围栏(页面画的) —— 路径不许进
except Exception:                                                     # noqa: BLE001
    FS = None
TR = os.path.join(REPO, "zmax_data", "ss_live", "trace_live.json")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
RES = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "agent_result.json")
TPL = os.path.join(REPO, "zmax_data", "ss_live", "episode_template.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_episode_path.jsonl")
PIDF = os.path.join(REPO, "zmax_data", "ss_live", "bridge_episode.pid")
BASE = "http://127.0.0.1:8793"


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                     # noqa: BLE001
        return {}


def _get(p, timeout=3.0):
    with urllib.request.urlopen(BASE + p, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fifo(req):
    fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    os.close(fd)


def _truth():
    t = _j(VFF).get("truth_xyz")
    if isinstance(t, (list, tuple)) and len(t) >= 3:
        return [float(x) * 1000.0 for x in t]
    return None


def _len(pts):
    return sum(sum((pts[i][k] - pts[i - 1][k]) ** 2 for k in range(3)) ** 0.5
               for i in range(1, len(pts)))


def _resample(path, n):
    """把折线等弧长重采样成 n 段, 返回**相邻增量**列表 (腿按相对量走)"""
    if len(path) < 2:
        return []
    segs = [sum((path[i + 1][k] - path[i][k]) ** 2 for k in range(3)) ** 0.5
            for i in range(len(path) - 1)]
    total = sum(segs)
    if total <= 0:
        return []
    out, acc, j = [], 0.0, 0
    prev = list(path[0])
    for k in range(1, n + 1):
        want = total * k / n
        while j < len(segs) and acc + segs[j] < want:
            acc += segs[j]
            j += 1
        if j >= len(segs):
            nxt = list(path[-1])
        else:
            r = (want - acc) / segs[j] if segs[j] > 0 else 0.0
            nxt = [path[j][i] + (path[j + 1][i] - path[j][i]) * r for i in range(3)]
        out.append([nxt[i] - prev[i] for i in range(3)])
        prev = nxt
    return out


def _build_segs(tpl, scale, max_path, npts):
    # 模板是真值差, 单位 **米**; 腿的 path 点要 **毫米** ⇒ 先 ×1000
    segs = _resample([[x * 1000.0 * scale for x in q] for q in tpl], npts)
    total = sum(sum(x * x for x in q) ** 0.5 for q in segs)
    if total > max_path > 0:
        k = max_path / total
        segs = [[x * k for x in q] for q in segs]
        total = max_path
    return segs, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--npts", type=int, default=50, help="路径点数")
    ap.add_argument("--band", type=float, default=60.0, help="包络 ±mm")
    ap.add_argument("--dur-scale", type=float, default=0.25, help="时长压缩系数 (越小越快)")
    ap.add_argument("--max-path", type=float, default=40.0, help="整轮总行程硬上限 mm")
    ap.add_argument("--template", type=str, default="", help="外部模板 (episode_template_truth.json)")
    ap.add_argument("--no-record", action="store_true", help="不自动录模板 (防自我衰减)")
    ap.add_argument("--max-episodes", type=int, default=0, help="0=常驻")
    a = ap.parse_args()

    if not _get("/ctl/status").get("motion_armed"):
        print("⛔ 未授权真动 ⇒ 一行都不发。", flush=True)
        return 2
    anchor = [float(x) for x in _get("/pose")["xyz"]]
    gbox = {ax: [anchor[i] - a.band / 1000.0, anchor[i] + a.band / 1000.0]
            for i, ax in enumerate("xyz")}
    try:
        with open(PIDF, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:                                                     # noqa: BLE001
        pass

    tpl_file = a.template or TPL
    tpl = (_j(tpl_file).get("path") or None)
    tpl_dur = float(_j(tpl_file).get("dur_s") or 10.0)
    print("🎞 整轮一条路径: scale=%.2f npts=%d 包络±%.0fmm 上限%.0fmm 锚点(%.4f,%.4f,%.4f)"
          % (a.scale, a.npts, a.band, a.max_path, *anchor), flush=True)
    if tpl:
        print("   模板 %s: %d 点 · %.1fs · %.0fmm"
              % (os.path.basename(tpl_file), len(tpl), tpl_dur, _len(tpl) * 1000), flush=True)
    else:
        print("   无模板 ⇒ 先录一轮 (臂不动), 之后自动回放", flush=True)

    buf, t_start, last_frame = [], None, 0
    ep, pending, last_pose, still_since, last_send = 0, None, None, 0.0, 0.0
    while a.max_episodes == 0 or ep < a.max_episodes:
        time.sleep(0.05)
        v = _j(VFF)
        if not v.get("bridge"):
            print("⏹ 桥接开关已关 ⇒ 停", flush=True)
            break
        fr = int(v.get("frame") or 0)
        wrap = (fr < last_frame) if last_frame else False
        last_frame = fr
        t = _truth()

        # ── 一轮结束: 允许时录模板 (只接受更长的, 防衰减) ──
        if wrap:
            if (not a.no_record) and len(buf) > 20:
                rel = [[p[i] - buf[0][i] for i in range(3)] for p in buf]
                new_len, old_len = _len(rel) * 1000, (_len(tpl) * 1000 if tpl else 0.0)
                if new_len > old_len * 1.2:
                    try:
                        with open(TPL, "w", encoding="utf-8") as f:
                            json.dump({"path": rel, "dur_s": round(time.time() - (t_start or time.time()), 2),
                                       "stamp": time.strftime("%F %T")}, f, ensure_ascii=False)
                        tpl, tpl_dur = rel, time.time() - (t_start or time.time())
                        print("   ✅ 录完一轮: %d 点 · 长度 %.0fmm" % (len(rel), new_len), flush=True)
                    except Exception:                                     # noqa: BLE001
                        pass
            buf, t_start = [], time.time()
        if t is not None:
            if t_start is None:
                t_start = time.time()
            buf.append(t)

        # ── 位姿静/动 (腿的 5Hz 真值) ──
        try:
            pc = [float(x) for x in _get("/pose")["xyz"]]
            if last_pose is not None and max(abs(pc[i] - last_pose[i]) for i in range(3)) > 5e-5:
                still_since = time.time()
            last_pose = pc
        except Exception:                                                 # noqa: BLE001
            pc = None

        # ── 回执: 上一条 path 完成了才允许发下一条 ──
        if pending:
            _rj = _j(RES)
            if str(_rj.get("id") or "") == pending:
                _vd = str((_rj.get("out") or {}).get("verdict") or "")
                pending = None
                still_since = time.time()
                # 🛟 手臂被手动挪/上一轮飘出包络 ⇒ 腿上"扫掠越界"会把每条都拒掉 (实测连拒 150 轮)
                #    这时必须以**当前位置**重新锚定, 而不是拿旧锚点死磕
                # 腿前置条件不满足 (手动模式/点动中/报警) ⇒ 别死磕刷屏, 退避 1s 并说清原因
                if "前置条件" in _vd:
                    print("⏸ 腿拒绝: %s ⇒ 等 1s 再试" % _vd, flush=True)
                    time.sleep(1.0)
                if "越界" in _vd or "包络" in _vd:
                    try:
                        anchor[:] = [float(x) for x in _get("/pose")["xyz"]]
                        gbox = {ax: [anchor[i] - a.band / 1000.0, anchor[i] + a.band / 1000.0]
                                for i, ax in enumerate("xyz")}
                        print("↺ 腿回报\"%s\" ⇒ 以当前位置 (%.4f,%.4f,%.4f) ±%.0fmm 重新锚定"
                              % (_vd, *anchor, a.band), flush=True)
                    except Exception:                                     # noqa: BLE001
                        pass

        if not tpl or pending or (time.time() - still_since) < 0.35 or (time.time() - last_send) < 0.3:
            continue
        if not _get("/ctl/status").get("motion_armed"):
            print("🔒 授权已撤 ⇒ 停 (一行不发)", flush=True)
            break
        segs, total = _build_segs(tpl, a.scale, a.max_path, a.npts)
        if not segs or total < 3.0:
            continue
        # 🧱 围栏闸: 这一段路径(绝对坐标 = 当前 TCP + 逐点累加)只要有一点落进围栏就整段不发
        if FS is not None:
            try:
                cur = [float(x) for x in _get("/pose")["xyz"]]
                acc, abspts = [0.0, 0.0, 0.0], []
                for q in segs:
                    acc = [acc[i] + q[i] / 1000.0 for i in range(3)]
                    abspts.append([cur[i] + acc[i] for i in range(3)])
                now_in = FS.check_point(cur)
                rc = FS.check_points(abspts)
                if rc.get("hit"):
                    # 起点已经在围栏里时, 只放行"往外走"的段 (末点已在围栏外 = 脱困)
                    if now_in.get("hit") and not FS.check_point(abspts[-1]).get("hit"):
                        _n = (now_in.get("inside") or [{}])[0].get("name") or "?"
                        print("🆘 当前在围栏「%s」里, 这一段是往外走 ⇒ 放行脱困" % _n, flush=True)
                    else:
                        hit = (rc.get("first") or {}).get("by") or []
                        nm = hit[0].get("name") if hit else "?"
                        print("⛔ 路径会进围栏「%s」⇒ 这一段不发 (第 %s 点 / 共 %s 点)"
                              % (nm, (rc.get("first") or {}).get("i"), rc.get("n_pts")), flush=True)
                        still_since = time.time()
                        time.sleep(1.0)
                        continue
                elif now_in.get("hit"):
                    _n = (now_in.get("inside") or [{}])[0].get("name") or "?"
                    print("⚠ 当前 TCP 已在围栏「%s」里 —— 只允许往外走" % _n, flush=True)
            except Exception:                                             # noqa: BLE001
                pass
        dur_eff = max(1.0, tpl_dur * a.dur_scale)
        spd = max(2.0, min(100.0, total / dur_eff))
        _fifo({"id": "rst_%d" % int(time.time() * 1000), "cmd": "reset"})    # 清旧队列
        time.sleep(0.15)
        pid_send = "ep_%d" % int(time.time() * 1000)
        _fifo({"id": pid_send, "cmd": "path",
               "points": [[round(x, 3) for x in q] for q in segs],
               "speed": round(spd, 1), "zone": 10, "guard_box": gbox})
        pending, last_send = pid_send, time.time()
        ep += 1
        print("🎞 第 %d 轮: %d 点 · 路径 %.0fmm · %.1fs · 速度 %.1fmm/s"
              % (ep, len(segs), total, dur_eff, spd), flush=True)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": round(time.time(), 2), "ep": ep, "points": len(segs),
                                    "total_mm": round(total, 1), "dur_s": round(dur_eff, 1),
                                    "speed_mm_s": round(spd, 1), "id": pid_send},
                                   ensure_ascii=False) + "\n")
        except Exception:                                                 # noqa: BLE001
            pass
    print("✅ 结束 (回放 %d 轮)" % ep, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
