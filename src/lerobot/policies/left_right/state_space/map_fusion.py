# -*- coding: utf-8 -*-
"""map_fusion.py —— 「📡 融合定位建图」节点的**唯一**建图/训练实现。

老倪 2026-11-13/14 的要求:
  「所有训练代码，无论是实时建图还是离线建图，代码逻辑都在建图融合节点，
    550A 550B 550C 都要有相同的代码。」

所以这份文件是**唯一实现**，三条入口全部走它，没有第二份逻辑：
  ① 画布节点每一拍 → `tick(ctx)`            (融合定位建图节点入口, 见 engineering/nodes/library.py::node_ss_s1)
  ② 常驻守护进程   → `daemon_main()`        (tools/gs_realtime_map.py 现在只是 3 行转发)
  ③ 离线建图 CLI   → `offline(...)` / `--offline --session ... --steps ...`

三种模式共用同一套函数: build_ds() 建数据集 → train() 调训练 → publish() 发布资产。
实时与离线**只差参数**（窗口/步数/触发条件），不差逻辑 —— 这正是"不能有两份代码"的含义。

调试（VSCode 断点）:
  环境变量 ZMAX_DEBUG_MAPFUSION=1 时, tick() 入口会 `breakpoint()` 停住;
  常驻服务环境里没有这个变量 ⇒ 生产路径逐位不变（铁律: 共享库里裸 breakpoint() 会把常驻服务挂死）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

# ── 路径/参数（三台机同一份代码，差异全部走 env 或自动探测，不写死机器）───────────────
ROOT = os.path.expanduser(os.environ.get("MF_ROOT", "~/zmax_data/gs_rt"))
ASSETS = os.path.expanduser(os.environ.get("MF_ASSETS", "~/zmax_data/gs_assets"))
ASSET_RT = os.path.join(ASSETS, os.environ.get("MF_ASSET_RT", "rt_live"))
STATUS = os.path.expanduser(os.environ.get("MF_STATUS", "~/zmax_data/gs_map/realtime.json"))
LOG = os.path.expanduser(os.environ.get("MF_LOG", "~/zmax_data/gs_map/realtime.log"))
SESSIONS = os.path.expanduser(os.environ.get("MF_SESSIONS", "~/gs_autocap/sessions"))
CAP = os.environ.get("MF_CAP", "http://127.0.0.1:8806/health")

TRIGGER = int(os.environ.get("MF_TRIGGER", os.environ.get("RT_TRIGGER", "80")))      # 攒够多少新帧开一轮
WINDOW = int(os.environ.get("MF_WINDOW", os.environ.get("RT_WINDOW", "600")))         # 滚动窗口帧数
STEPS = int(os.environ.get("MF_STEPS", os.environ.get("RT_STEPS", "600")))            # 实时一轮步数
MIN_FRAMES = int(os.environ.get("MF_MIN_FRAMES", os.environ.get("RT_MIN_FRAMES", "40")))
POLL = float(os.environ.get("MF_POLL", os.environ.get("RT_POLL", "5")))
STALE_S = float(os.environ.get("MF_STALE_S", "25"))


def _find_train_py() -> str:
    """训练入口（gs_train.py）—— 三台机路径不同，按顺序探测，找不到就明确报错。"""
    cands = [os.environ.get("MF_TRAIN", ""),
             os.path.expanduser("~/zmax_map/tools/gs_train.py"),
             os.path.expanduser("~/zmax/zmax_map/tools/gs_train.py"),
             os.path.expanduser("~/zmax/tools/gs_train.py")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return ""


def _find_py() -> str:
    """训练用的解释器（要装 torch+gsplat）。"""
    for c in (os.environ.get("MF_PY", ""),
              "/home/intel/gsxpu-venv/bin/python",
              os.path.expanduser("~/gsxpu-venv/bin/python"),
              "/usr/bin/python3"):
        if c and os.path.isfile(c):
            return c
    return sys.executable


TRAIN_PY = _find_train_py()
PY = _find_py()

_LAST = {"check": 0.0, "st": {}}


# ── 基础工具 ─────────────────────────────────────────────────────────────────
def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def jget(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return None


def st_read() -> dict:
    try:
        return json.load(open(STATUS, encoding="utf-8"))
    except Exception:
        return {}


def st_write(d: dict) -> None:
    d["ts"] = now()
    d["ts_epoch"] = time.time()
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    tmp = STATUS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATUS)


def latest_session() -> str:
    s = sorted(glob.glob(os.path.join(SESSIONS, "*")))
    return s[-1] if s else ""


def count_imgs(sess: str) -> int:
    return len(glob.glob(os.path.join(sess, "images", "*.jpg"))) if sess else 0


def trainer_busy() -> bool:
    """有别的训练在跑就不抢 XPU。

    🔴 踩坑: `pgrep -f 'gs_train.py'` 会子串命中常驻服务 `gs_train_service_intel.py`,
      也会命中本函数自己的命令行 ⇒ 永远判"在跑"。用 [.] 断开 + 排除服务进程。
    """
    r = subprocess.run("pgrep -af 'gs_train[.]py' | grep -v gs_train_service",
                       shell=True, capture_output=True, text=True)
    return bool((r.stdout or "").strip())


# ── 建数据集 / 训练 / 发布（实时与离线共用，唯一实现）───────────────────────────
def build_ds(sess: str, out: str, window: int) -> tuple[bool, str]:
    """会话 → 数据集。两种形态都支持：
    ① 采集守护写的会话（images/ + cameras.json）= 已经是数据集 ⇒ 按窗口裁最后 N 帧（硬链接，零拷贝）；
    ② 老会话只有帧+位姿 ⇒ 退回 gs_map_from_history.build_ds。
    """
    _debug_stop("build_ds")                             # 断点: ZMAX_DEBUG_MAPFUSION>=2
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import gs_map_from_history as gh                                 # type: ignore
    except Exception:
        try:
            sys.path.insert(0, os.path.expanduser("~/zmax_map/tools"))
            import gs_map_from_history as gh                             # type: ignore
        except Exception as e:                                          # noqa: BLE001
            return False, "导入构建器失败: %r" % (e,)
    cam_p = os.path.join(sess, "cameras.json")
    if gh.has_ds(sess):
        try:
            cam = json.load(open(cam_p, encoding="utf-8"))
            frames = list(cam.get("frames") or [])
            sel = frames[-window:] if (window and len(frames) > window) else frames
            os.makedirs(os.path.join(out, "images"), exist_ok=True)
            for f in sel:
                src = os.path.join(sess, "images", f["file"])
                dst = os.path.join(out, "images", f["file"])
                if os.path.exists(dst):
                    continue
                try:
                    os.link(src, dst)
                except Exception:
                    shutil.copy2(src, dst)
            cam2 = dict(cam)
            cam2["frames"] = sel
            cam2["note"] = "map_fusion 滚动窗口 %d/%d 帧" % (len(sel), len(frames))
            json.dump(cam2, open(os.path.join(out, "cameras.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            return gh.has_ds(out), "滚动窗口 %d/%d 帧" % (len(sel), len(frames))
        except Exception as e:                                          # noqa: BLE001
            return False, "裁窗口失败: %r" % (e,)
    if not os.path.exists(os.path.join(sess, "frames.jsonl")):
        return False, "会话还在采(cameras.json 未落盘), 本轮先不建"
    ok, msg = gh.build_ds(sess, out, window)
    return bool(ok), str(msg)[:300]


def train(ds: str, out: str, steps: int, init_ply: str = "") -> tuple[bool, str, dict]:
    """唯一训练调用点。实时传 steps=600，离线传 12000/24000 —— 逻辑同一份。"""
    _debug_stop("train")                        # 门控断点: ZMAX_DEBUG_MAPFUSION=2 停在这里
    if not TRAIN_PY:
        return False, "找不到 gs_train.py(用 MF_TRAIN 指定)", {}
    os.makedirs(out, exist_ok=True)
    cmd = [PY, TRAIN_PY, "--data", ds, "--out", out, "--steps", str(int(steps))]
    if init_ply and os.path.exists(init_ply):
        cmd += ["--init-ply", init_ply]
    log = os.path.join(out, "train.log")
    t0 = time.time()
    with open(log, "w") as f:
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode
    rep = {}
    try:
        rep = json.load(open(os.path.join(out, "train_report.json"), encoding="utf-8"))
    except Exception:
        pass
    tail = ""
    try:
        tail = "".join(open(log, errors="ignore").read().splitlines(True)[-3:])[-300:]
    except Exception:
        pass
    ok = rc == 0 and bool(rep)
    msg = "rc=%d %.0fs %s" % (rc, time.time() - t0, tail) if not ok else "%.0fs" % (time.time() - t0)
    return ok, msg, rep


def publish(out: str, asset: str = "") -> str:
    """把一轮产物发布成资产目录(gs.splat/gs.ply/report + 渲染图)。"""
    _debug_stop("publish")                              # 断点: ZMAX_DEBUG_MAPFUSION>=3
    asset = asset or ASSET_RT
    os.makedirs(asset, exist_ok=True)
    src_splat = os.path.join(out, "gs.splat")
    if not os.path.exists(src_splat):
        return ""
    shutil.copy2(src_splat, os.path.join(asset, "gs.splat"))
    for f in ("gs.ply", "train_report.json"):
        p = os.path.join(out, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(asset, f))
    # 🖼 渲染图必须一起发: /gs_render.png 取的是"最新资产的 renders/holdout_00.png",
    #    只发 splat 会让工位页那格继续显示上一份的老图(2026-11-14 实测踩过)。
    rdir = os.path.join(asset, "renders")
    os.makedirs(rdir, exist_ok=True)
    for n in ("holdout_00.png", "holdout_00_gt.png"):
        p = os.path.join(out, "renders", n)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(rdir, n))
    return os.path.join(asset, "gs.splat")


# ── ① 实时：一轮检查（节点守护每 POLL 秒调一次）────────────────────────────────
def realtime_cycle(state: dict, force: bool = False) -> dict:
    """🎯 建图逻辑第一站: 一轮"攒帧 → 够阈值就建数据集 → 训练 → 发布"的决策与执行。"""
    _debug_stop("realtime_cycle")                       # 断点: ZMAX_DEBUG_MAPFUSION>=1
    h = jget(CAP) or {}
    cur = (h.get("cur") or {})
    sess = cur.get("dir") or latest_session()
    n = count_imgs(sess)
    state.update({"session": sess, "frames_now": n, "autocap_frames": h.get("frames_total"),
                  "autocap_sessions": h.get("sessions"), "trigger": TRIGGER, "window": WINDOW,
                  "steps": STEPS})
    # 换会话必须清零基线（采集每段重开新会话，帧数从 0 重数）
    if str(state.get("sess_marker") or "") != str(sess or ""):
        if state.get("sess_marker"):
            state["prev_session_frames"] = state.get("last_trained_frames")
        state["sess_marker"] = sess
        state["last_trained_frames"] = 0
    last_n = int(state.get("last_trained_frames") or 0)
    state["pending"] = max(0, n - last_n)
    trig = 1 if force else TRIGGER
    if n < MIN_FRAMES or (n - last_n) < trig:
        state["phase"] = "collect"
        return state
    if trainer_busy() and not force:
        state["phase"] = "wait_trainer"
        state.setdefault("log", []).append("[%s] 有其它训练在跑, 等它结束(%d 帧待训)" % (now(), n - last_n))
        return state

    ts = time.strftime("%Y%m%d_%H%M%S")
    ds, out = os.path.join(ROOT, "ds_%s" % ts), os.path.join(ROOT, "out_%s" % ts)
    state["phase"] = "build_ds"
    st_write(state)
    ok, msg = build_ds(sess, ds, WINDOW)
    if not ok:
        if "还在采" in msg:
            state["phase"] = "wait_ds"
            state.setdefault("log", []).append("[%s] %s" % (now(), msg))
            return state
        state["phase"], state["error"] = "error", "建数据集失败: %s" % msg
        state.setdefault("log", []).append("[%s] %s" % (now(), state["error"]))
        return state

    state["phase"], state["ds"] = "train", ds
    st_write(state)
    ok, msg, rep = train(ds, out, STEPS, os.path.join(ASSET_RT, "gs.ply"))
    if not ok:
        state["phase"], state["error"] = "error", "训练失败: %s" % msg
        state.setdefault("log", []).append("[%s] %s" % (now(), state["error"]))
        return state

    splat = publish(out)
    state.update({"phase": "done", "error": "", "out": out, "asset": splat,
                  "last_trained_frames": n, "pending": 0,
                  "psnr_holdout_db": round(float(rep.get("psnr_holdout_db") or 0), 2),
                  "psnr_train_db": round(float(rep.get("psnr_train_db") or 0), 2),
                  "n_gaussians": rep.get("n_gaussians"), "steps": rep.get("steps"),
                  "seconds": round(float(rep.get("seconds") or 0), 1),
                  "last_train_ts": now(), "n_rounds": int(state.get("n_rounds") or 0) + 1})
    state.setdefault("log", []).append("[%s] 第 %s 轮完成: %s 高斯 PSNR %.2f dB (%.0fs)" % (
        now(), state["n_rounds"], state.get("n_gaussians"), state.get("psnr_holdout_db"),
        state.get("seconds") or 0))
    return state


# ── ③ 离线：一次性建图（历史会话 / 指定数据集 / 指定步数）──────────────────────
def offline(session: str = "", steps: int = 12000, window: int = 0,
            asset: str = "", ts: str = "") -> dict:
    """离线建图 = 同一套 build_ds → train → publish，只是步数/窗口不同。

    session 可以是：会话目录(images+cameras.json) 或 已是数据集目录；空 = 最新会话。
    window=0 表示用全量帧（离线通常不裁窗口）。
    """
    sess = session or latest_session()
    if not sess or not os.path.isdir(sess):
        return {"ok": False, "err": "会话不存在: %r" % (sess,)}
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    ds = os.path.join(ROOT, "ds_off_%s" % ts)
    out = os.path.join(ROOT, "out_off_%s" % ts)
    ok, msg = build_ds(sess, ds, window)
    if not ok:
        return {"ok": False, "err": "建数据集失败: %s" % msg, "session": sess}
    ok, msg, rep = train(ds, out, steps, "")
    if not ok:
        return {"ok": False, "err": "训练失败: %s" % msg, "session": sess, "ds": ds}
    splat = publish(out, asset or os.path.join(ASSETS, "map_off_%s" % ts))
    return {"ok": True, "session": sess, "ds": ds, "out": out, "asset": splat,
            "steps": rep.get("steps"), "n_gaussians": rep.get("n_gaussians"),
            "psnr_holdout_db": rep.get("psnr_holdout_db"), "psnr_train_db": rep.get("psnr_train_db"),
            "seconds": rep.get("seconds")}


# ── ② 节点侧：状态/日志/拉起守护 ────────────────────────────────────────────
def status(fresh_s: float = 1.0) -> dict:
    t = time.time()
    if t - _LAST["check"] < fresh_s and _LAST["st"]:
        return _LAST["st"]
    st = st_read()
    _LAST["check"], _LAST["st"] = t, st
    return st


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def healthy() -> bool:
    st = status()
    if not st:
        return False
    if st.get("pid") and not _pid_alive(st["pid"]):
        return False
    return (time.time() - float(st.get("ts_epoch") or 0)) <= STALE_S


def _find_daemon() -> str:
    """守护脚本位置 —— 三台机布局不同，按顺序探测（同一份代码靠这个自适应，不写死机器）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", "..", "..", ".."))   # <repo>/src/lerobot/policies/left_right/state_space → <repo>
    cands = [os.environ.get("MF_DAEMON", ""),
             os.path.expanduser("~/zmax_map/tools/gs_realtime_map.py"),
             os.path.join(repo, "tools", "gs_realtime_map.py"),
             os.path.expanduser("~/zmax/tools/gs_realtime_map.py")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return cands[1]


DAEMON = _find_daemon()
SPAWN_LOCK = os.path.expanduser("~/zmax_data/gs_map/.rt_spawn")
RESPAWN_S = float(os.environ.get("MF_RESPAWN_S", "30"))


def ensure() -> tuple[bool, str]:
    """确保常驻守护活着（节点每拍调，节流）。守护本身也是这份模块的 daemon_main()。"""
    if healthy():
        return True, "alive"
    try:
        if os.path.exists(SPAWN_LOCK) and (time.time() - os.path.getmtime(SPAWN_LOCK)) < RESPAWN_S:
            return False, "throttled"
        os.makedirs(os.path.dirname(SPAWN_LOCK), exist_ok=True)
        open(SPAWN_LOCK, "w").write(str(time.time()))
    except Exception:
        pass
    if not os.path.exists(DAEMON):
        return False, "daemon 脚本不存在: %s" % DAEMON
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as lf:
            lf.write("\n[%s] 节点拉起守护\n" % now())
            lf.flush()
            subprocess.Popen([PY, DAEMON], stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=os.path.dirname(DAEMON))
        return False, "spawned"
    except Exception as e:                                              # noqa: BLE001
        return False, "spawn 失败: %r" % (e,)


def line() -> str:
    st = status()
    if not st:
        return "🗺 建图(3DGS): 守护未启动/无状态"
    ph, n, pend = st.get("phase") or "?", st.get("frames_now"), st.get("pending")
    if st.get("error"):
        return "🗺 建图(3DGS): ⚠️ %s · %s" % (ph, str(st["error"])[:120])
    if ph == "train":
        return "🗺 建图(3DGS): 训练中 · 数据 %s 帧(待训 %s) · %s 步" % (n, pend, st.get("steps"))
    if ph in ("collect", "wait_trainer", "done", "wait_ds"):
        return ("🗺 建图(3DGS): %s · 帧 %s(待训 %s) · 最近一轮 PSNR %s dB / %s 高斯 / %ss"
                % (ph, n, pend, st.get("psnr_holdout_db") or "-", st.get("n_gaussians") or "-",
                   st.get("seconds") or "-"))
    return "🗺 建图(3DGS): %s · 帧 %s" % (ph, n)


# ── ① 节点入口（VSCode 断点就设在这里）────────────────────────────────────────
def _debug_stop(where: str = "tick") -> None:
    """门控断点: 只在 ZMAX_DEBUG_MAPFUSION=1 时停, 且**停在 VSCode 调试器里**(不是终端 pdb)。

    用 debugpy.breakpoint() 而不是内置 breakpoint(): 后者在 VSCode 调试会话里会落到终端 Pdb,
    编辑器看不到调用栈/变量; debugpy 的版本等价于"在这里下一个断点", 会话里会停成 Paused 状态。
    没装 debugpy / 不在调试会话里 ⇒ 自动退回 breakpoint(); 生产环境没这个环境变量 ⇒ 一行都不执行。
    """
    # 层级(默认=2): 1 只停 realtime_cycle(一轮建图决策) · 2 再停 build_ds/train · 3 再停 publish
    _need = {"realtime_cycle": 1, "build_ds": 2, "train": 2, "publish": 3}.get(where, 2)
    try:
        lvl = int(os.environ.get("ZMAX_DEBUG_MAPFUSION", "0") or 0)
    except ValueError:
        return
    if lvl < _need:
        return
    try:
        import debugpy                                                  # noqa: WPS433
        debugpy.breakpoint()
        return
    except Exception:
        pass
    breakpoint()                                                        # noqa: T100


def tick(ctx: dict | None = None) -> dict:
    """融合定位建图节点的**建图入口**：本拍只做毫秒级三件事（确保守护活/读状态/写一行日志）。

    断点门控：ZMAX_DEBUG_MAPFUSION=1 时停在这里（只有调试 launch 配置会设这个变量，
    常驻服务没有 ⇒ 生产路径不变）。
    """
    # 断点不在这个壳里(这里只 ensure+日志), 在建图逻辑: realtime_cycle/build_ds/train/publish
    ctx = ctx or {}
    log = ctx.get("log")
    ok, act = ensure()
    if log:
        log(line())
        if not ok and act not in ("alive", "throttled"):
            log("   ↳ 建图守护: %s" % act)
    return {"ok": ok, "action": act, "status": status()}


# ── ② 常驻守护入口 ───────────────────────────────────────────────────────────
def daemon_main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    lock_fh = open("/tmp/gs_realtime_map.lock", "w")
    try:
        import fcntl
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print("已有实例在跑, 本进程退出")
        return 0
    ap = argparse.ArgumentParser(description="融合定位建图 · 常驻守护(实时)")
    ap.add_argument("--once", action="store_true", help="只跑一轮检查就退(自测)")
    ap.add_argument("--force", action="store_true", help="忽略触发条件与'别人在训'(自测)")
    a, _ = ap.parse_known_args(argv)
    state = st_read()
    state.update({"alive": True, "pid": os.getpid(), "started": state.get("started") or now()})
    st_write(state)
    while True:
        try:
            state = realtime_cycle(state, force=a.force)
        except Exception as e:                                          # noqa: BLE001
            state["phase"], state["error"] = "error", repr(e)[:200]
            state.setdefault("log", []).append("[%s] 异常: %s" % (now(), state["error"]))
        state["log"] = (state.get("log") or [])[-20:]
        state["alive"] = True
        st_write(state)
        if a.once:
            return 0
        time.sleep(POLL)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--offline" in argv:
        ap = argparse.ArgumentParser(description="融合定位建图 · 离线建图")
        ap.add_argument("--offline", action="store_true")
        ap.add_argument("--session", default="")
        ap.add_argument("--steps", type=int, default=12000)
        ap.add_argument("--window", type=int, default=0)
        ap.add_argument("--asset", default="")
        ap.add_argument("--ts", default="")
        a, _ = ap.parse_known_args(argv)
        r = offline(a.session, a.steps, a.window, a.asset, a.ts)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("ok") else 1
    if "--tick" in argv:
        print(json.dumps(tick({"log": lambda m: print(m, flush=True)}), ensure_ascii=False, indent=1))
        return 0
    return daemon_main(argv)


if __name__ == "__main__":
    sys.exit(main())
