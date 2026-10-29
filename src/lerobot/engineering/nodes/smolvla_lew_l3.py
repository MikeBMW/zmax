# -*- coding: utf-8 -*-
"""SmolVLA+LEW · L3 层真执行 (AR 场景) — 模型前向 / 39D 观测构造 / 接口契约

老倪 2026-10-29:「SmolVLA+LEW L3 层 用上这个模型, 正式启用, 用到 AR 场景, 保证接口对齐,
                 节点真实代码」

=== 为什么另起一个模块而不是在节点里现写 ===
`src/lerobot/engine/runtime.py::RealStateSpaceSim._l3_forward` 已经是**跑通过全链**的 L3 真执行
(v10_1h/004000 接管: insert 341 步 / full 865 步 + AOI PASS), 里面每条注释都是实测换来的教训:
  · ckpt 默认 v10_1h/004000 (v8/030000 是旧模型, 跑它成绩无法归因)
  · 图像必须缩到 **128×128** LANCZOS (训练数据管线按 128 编码; 曾按 config 推断成 64 → 接管卡死 2318 帧)
  · 语言指令必须用数据集 tasks.parquet 里的**原串** (硬编码 = VLM 条件分布错)
  · 模型输出在归一化空间, **必须 post-processor 反归一化** (缺这步 → -1~1 被当 m/s, 动作全错)
  · ckpt 里 device_processor 写死 cuda → 无卡/CPU 时实例化直接抛错 ⇒ 按运行设备覆盖
  · 类级缓存 (每实例重载 625M 慢 N 倍) + 熔断 (失败不再每步重试整载)
本模块把这套口径**原样搬过来**, 只换两件事: ① 观测从 AR 场景真值构造 (不再要求 metaworld env)
② 输出成画布端口契约 (out1/out2)。基线照旧, 不重写。

=== AR 场景的可达性 (不是凑数, 是逐项对 metaworld obs 39 维) ===
metaworld sawyer_xyz_env._get_obs() 的 39 维 = hstack((curr(18), prev(18), goal(3))), 其中
  curr = pos_hand(3) + gripper_distance_apart(1) + obj1(pos3+quat4) + obj2(pos3+quat4)
AR 场景 (trace_live.json, dreamview 每拍写) 能对上的:
  pos_hand          ← 末端[3]                     ✅ 真值
  gripper           ← 夹爪 (归一化 0~1)            ✅ 真值 (metaworld 是两指间距, 语义近似)
  obj1 pos          ← 光模块[3]                    ✅ 真值
  obj2 pos          ← 光模块头[3]                  ✅ 真值
  prev(18)          ← 上一拍 curr 快照             ✅ 真值 (进程内缓存)
  goal(3)           ← 光模块头到孔的目标点          ✅ 有则用, 无则用当前光模块头 (零位移, 如实标)
  obj1/obj2 quat(4+4) ← **真机没有姿态角**, 置 0    ⚠️ 缺, 如实标 missing=8/39
⇒ 填充率 31/39 ≈ 79.5%, 缺的 8 维是四元数; 输出里带 `state_fill` 与 `missing_dims`, 不隐瞒。

=== 图像源 ===
AR 场景底图 = 8797 `/snap/<cam>.jpg`。本机在线的那路是 `local` (D435, 640×480, ~5fps);
arm/gold/surface 走 Orin/产线, 产线网卡不在位时 offline → 自动回落到 local, 并标 `img_src`。
模型训练域是 metaworld 渲染 (128×128), 真机相机域不同 ⇒ 输出带 `domain_gap` 提示, 不当训练域成绩吹。

=== 铁律 ===
只读真值 / 不造数 / 不下发动作。模型失败 → 熔断并回落到测地线块 (既有路径), 不伪装成功。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

import numpy as np

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))          # src/lerobot/engineering/nodes → repo

_CK_DEFAULT = "outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model"
_IMGSZ_DEFAULT = 128
_TASK_DEFAULT = "metaworld 光模块插拔"
_AR_API = "http://127.0.0.1:8797"
_CAM_ORDER = ("local", "arm", "gold", "surface")     # 优先本机在线那路; 其余取决于产线链路

# 类级缓存 (进程内只加载一次) / 熔断标记
_CACHE = {"pol": None, "pre": None, "post": None, "dev": None, "ck": None, "task": None,
          "load_ms": None, "failed": None, "n_infer": 0, "t_prev_curr": None}


# ─────────────────────────────────────────────────────────── 观测构造
def _live_dir(root):
    return os.path.join(root, "zmax_data", "ss_live")


def build_obs39(root, log=None):
    """从 AR 场景真值 (trace_live.json) 构造 metaworld 同构 39 维观测。

    返回 (obs39[39], meta)。取不到末端/光模块 ⇒ 返回 (None, meta) —— 不拿 0 冒充有观测。
    """
    import json as _j
    p = os.path.join(_live_dir(root), "trace_live.json")
    meta = {"src": "zmax_data/ss_live/trace_live.json", "age_s": None,
            "state_fill": 0, "missing_dims": [], "missing_note": ""}
    try:
        tr = _j.load(open(p, encoding="utf-8")) or {}
        meta["age_s"] = round(time.time() - os.path.getmtime(p), 3)
        meta["stage"] = tr.get("阶段")
    except Exception as e:                                                   # noqa: BLE001
        meta["err"] = "%s: %s" % (type(e).__name__, e)
        return None, meta

    def _v3(key):
        v = tr.get(key)
        try:
            a = np.asarray(v, dtype=np.float64).ravel()
            return a[:3] if a.size >= 3 else None
        except Exception:                                                    # noqa: BLE001
            return None

    hand = _v3("末端")
    obj1 = _v3("光模块")
    obj2 = _v3("光模块头")
    if hand is None or obj1 is None:
        meta["err"] = "缺少 末端/光模块 ⇒ 无观测"
        return None, meta
    grip = float(tr.get("夹爪") or 0.0)

    curr = np.zeros(18, dtype=np.float64)
    curr[0:3] = hand                                  # pos_hand
    curr[3] = grip                                    # gripper_distance_apart (近似)
    curr[4:7] = obj1                                  # obj1 pos
    curr[7:11] = 0.0                                  # obj1 quat  ⚠️ 缺
    if obj2 is not None:
        curr[11:14] = obj2                            # obj2 pos
    curr[14:18] = 0.0                                 # obj2 quat  ⚠️ 缺

    prev = _CACHE.get("t_prev_curr")
    if prev is None or np.asarray(prev).shape != curr.shape:
        prev = curr.copy()                            # 首拍: prev=curr (零速度, 如实)
        _CACHE["t_prev_curr"] = curr.copy()
        meta["prev_src"] = "首拍自等 (零速度)"
    else:
        meta["prev_src"] = "上一拍真值"
    _CACHE["t_prev_curr"] = curr.copy()

    goal = obj2 if obj2 is not None else obj1         # 目标点: 光模块头 = 孔位侧
    meta["goal_src"] = "光模块头 (孔位侧)" if obj2 is not None else "光模块 (兜底)"

    obs = np.hstack((curr, np.asarray(prev, dtype=np.float64), goal)).astype(np.float64)
    meta.update({
        "state_fill": 31, "missing_dims": [7, 8, 9, 10, 14, 15, 16, 17],
        "missing_note": "obj1/obj2 四元数 8 维 (真机无姿态角) 置 0 —— 不是观测值",
        "fill_ratio": round(31 / 39, 4),
        "mapping": "metaworld hstack((curr18, prev18, goal3)): hand3+grip1+obj1(pos3,quat4)+obj2(pos3,quat4)",
    })
    return obs.astype(np.float32), meta


def fetch_ar_frame(prefer=("local",), timeout=3.0):
    """取 AR 场景一帧 (8797 /snap/<cam>.jpg) → RGB ndarray(H,W,3) uint8。

    优先本机在线那路; 全 offline ⇒ 返回 (None, meta), 不拿黑图冒充。
    """
    from io import BytesIO
    meta = {"api": _AR_API, "tried": []}
    order = list(prefer) + [c for c in _CAM_ORDER if c not in prefer]
    for cam in order:
        url = "%s/snap/%s.jpg" % (_AR_API, cam)
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                raw = r.read()
            if not raw or raw[:2] != b"\xff\xd8":
                meta["tried"].append((cam, "非JPEG %dB" % len(raw)))
                continue
            from PIL import Image
            img = np.asarray(Image.open(BytesIO(raw)).convert("RGB"))
            meta.update({"cam": cam, "shape": list(img.shape), "bytes": len(raw),
                         "url": url, "tried": meta["tried"]})
            return img, meta
        except Exception as e:                                               # noqa: BLE001
            meta["tried"].append((cam, "%s" % type(e).__name__))
    meta["err"] = "所有相机取不到帧"
    return None, meta


# ─────────────────────────────────────────────────────────── 模型加载 (口径照 _l3_forward)
def _load_policy(root, log=None, dev=None):
    """懒加载 + 类级缓存 + 熔断。返回 (pol, pre, post, dev, meta)。失败返回 (None,...,meta)。"""
    if _CACHE["failed"] is not None and os.environ.get("SS_L3_FORCE_RETRY") != "1":
        return None, None, None, None, {"err": "已熔断: %s" % _CACHE["failed"],
                                        "hint": "SS_L3_FORCE_RETRY=1 重试或重启进程"}
    if _CACHE["pol"] is not None:
        return (_CACHE["pol"], _CACHE["pre"], _CACHE["post"], _CACHE["dev"],
                {"ck": _CACHE["ck"], "cached": True, "load_ms": _CACHE["load_ms"],
                 "task": _CACHE["task"], "dev": _CACHE["dev"]})
    t0 = time.monotonic()
    try:
        import torch
        from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
        from lerobot.policies.factory import make_pre_post_processors

        ck = os.environ.get("SS_L3_CK", _CK_DEFAULT)
        if not os.path.isabs(ck):
            ck = os.path.join(root, ck)
        if not os.path.isdir(ck):
            raise FileNotFoundError("ckpt 不存在: %s" % ck)
        _dev = dev or os.environ.get("SS_L3_DEV") or ("cuda" if torch.cuda.is_available() else "cpu")
        pol = SmolVLALewPolicy.from_pretrained(ck)
        pol.eval()
        pol.to(_dev)
        pre, post = make_pre_post_processors(
            pol.config, pretrained_path=ck,
            preprocessor_overrides={"device_processor": {"device": str(_dev)}},
            postprocessor_overrides={"device_processor": {"device": str(_dev)}})
        # 语言指令: 训练数据 tasks.parquet 原串 (硬编码 = 条件分布错)
        task = ""
        try:
            import pandas as _pd
            for dp in (os.path.join(root, "data", "datasets", "smolvla_peg_v8_d1", "meta", "tasks.parquet"),
                       os.path.join(root, "data", "datasets", "smolvla_peg_v8", "meta", "tasks.parquet")):
                if os.path.exists(dp):
                    task = str(_pd.read_parquet(dp)["task"].iloc[0])
                    break
        except Exception:                                                    # noqa: BLE001
            task = ""
        task = os.environ.get("SS_L3_TASK", task or _TASK_DEFAULT)
        _CACHE.update({"pol": pol, "pre": pre, "post": post, "dev": _dev, "ck": ck,
                       "task": task, "load_ms": round((time.monotonic() - t0) * 1000, 1)})
        if log:
            try:
                rel = os.path.relpath(ck, root)
            except Exception:                                                # noqa: BLE001
                rel = ck
            log("🏆 L3 SmolVLA+LEW 已加载: %s · dev=%s · %.0fms · 🗣 %r"
                % (rel, _dev, _CACHE["load_ms"], task))
        return pol, pre, post, _dev, {"ck": ck, "cached": False, "load_ms": _CACHE["load_ms"],
                                      "task": task, "dev": _dev}
    except Exception as e:                                                   # noqa: BLE001
        _CACHE["failed"] = "%s: %s" % (type(e).__name__, e)
        if log:
            log("⚠️ L3 SmolVLA 加载失败 (已熔断, 后续拍不再重试): %s" % _CACHE["failed"])
        return None, None, None, None, {"err": _CACHE["failed"]}


def infer(img, obs39, root, log=None):
    """一次真前向: AR 帧 + 39D → 反归一化 4D 动作。返回 (act|None, meta)。"""
    pol, pre, post, dev, lmeta = _load_policy(root, log)
    if pol is None:
        return None, {"stage": "load", **lmeta}
    t0 = time.monotonic()
    try:
        import torch
        from PIL import Image
        sz = int(os.environ.get("SS_L3_IMGSZ", str(_IMGSZ_DEFAULT)))
        im = np.asarray(Image.fromarray(np.asarray(img)).resize((sz, sz), Image.LANCZOS))
        it = torch.from_numpy(im).permute(2, 0, 1).float().unsqueeze(0) / 255.0
        st = torch.from_numpy(np.asarray(obs39, dtype=np.float32)).unsqueeze(0)
        batch = {"observation.image": it.to(dev), "observation.state": st.to(dev),
                 "task": _CACHE["task"]}
        batch = pre(batch)
        # 🔴 2026-10-29 老倪「predict_action 断点进不去」: select_action 只在动作队列为空时真推理
        #   (modeling_smolvla_lew.py:537 `if len(self._queues[ACTION]) == 0`), 一次推理出
        #   n_action_steps=7 个动作 ⇒ 之后 6 拍直接 popleft, 不进 predict_action。policy 又是
        #   _CACHE 单例, 队列跨调用累积 ⇒ 断点看起来"永远不进"。要每拍真推理就设 SS_L3_NO_CACHE=1。
        # 🔴 2026-10-29 老倪「我看到打了断点, 就得进入」: 调试模式下一律关掉动作缓存,
        #   让 predict_action 每拍都真跑 —— 否则 n_action_steps=7 的队列缓存会让断点
        #   连续 6 拍看起来"不进"。等价 SS_L3_NO_CACHE=1, 这里按调试模式自动生效。
        _no_cache = (os.environ.get("SS_L3_NO_CACHE") == "1"
                     or os.environ.get("ZMAX_DEBUG_MODE") == "1")
        if _no_cache:
            try:
                _q = getattr(pol, "_queues", None)
                if isinstance(_q, dict):
                    for _k in list(_q.keys()):
                        try:
                            _q[_k].clear()
                        except Exception:                                  # noqa: BLE001
                            pass
                else:
                    pol._queues = {}
            except Exception:                                              # noqa: BLE001
                pass
        with torch.no_grad():
            pred = pol.select_action(batch)
            act = post(pred) if post is not None else pred           # 🔴 反归一化, 缺则动作全错
        a = np.asarray(act.detach().cpu().float()).reshape(-1)[:4]
        _CACHE["n_infer"] = int(_CACHE.get("n_infer") or 0) + 1
        return a, {**lmeta, "infer_ms": round((time.monotonic() - t0) * 1000, 2),
                   "img_sz": sz, "n_infer": _CACHE["n_infer"], "shape": list(a.shape)}
    except Exception as e:                                                   # noqa: BLE001
        return None, {**lmeta, "err": "infer: %s: %s" % (type(e).__name__, e),
                      "infer_ms": round((time.monotonic() - t0) * 1000, 2)}


def cache_status():
    return {"loaded": _CACHE["pol"] is not None, "failed": _CACHE["failed"],
            "ck": _CACHE["ck"], "dev": _CACHE["dev"], "load_ms": _CACHE["load_ms"],
            "n_infer": _CACHE.get("n_infer", 0), "task": _CACHE["task"]}


# ─────────────────────────────────────────────────────────── 异步前向 (常驻循环不阻塞)
# 实测单次前向 0.8~1.0s (含 CUDA/预处理), 而画布常驻循环是 10Hz tick ⇒ 同步调用会把整循环拖到
# 1s/拍。这里把前向放后台线程: 节点每拍**立即**拿到最近一次真结果 (带 age/是否在算), 模型照旧真跑。
_ASYNC = {"thread": None, "act": None, "meta": None, "t_done": None, "t_start": None,
          "n_done": 0, "n_skip": 0, "err": None}


def infer_async(img, obs39, root, log=None, min_period_s=1.5):
    """非阻塞前向: 到了周期且上一轮已结束 ⇒ 起后台线程; 每拍都返回 (act|None, meta)。

    meta 里恒带 `age_s`(这次动作距今多久) 与 `busy`(是否正在算) —— 下游能看出"这拍是真新算的还是回放"。
    """
    import threading
    now = time.monotonic()
    th = _ASYNC["thread"]
    busy = bool(th is not None and th.is_alive())
    since = (now - _ASYNC["t_done"]) if _ASYNC["t_done"] else 1e9
    if (not busy) and since >= float(min_period_s):
        _ASYNC["t_start"] = now

        def _job():
            try:
                _a, _m = infer(img, obs39, root, log)
                _ASYNC["act"] = _a
                _ASYNC["meta"] = _m
                _ASYNC["t_done"] = time.monotonic()
                if _a is None:
                    _ASYNC["err"] = (_m or {}).get("err")
                else:
                    _ASYNC["err"] = None
                _ASYNC["n_done"] = int(_ASYNC["n_done"]) + 1
            except Exception as e:                                           # noqa: BLE001
                _ASYNC["err"] = "%s: %s" % (type(e).__name__, e)
                _ASYNC["t_done"] = time.monotonic()

        th = threading.Thread(target=_job, name="l3-smolvla", daemon=True)
        _ASYNC["thread"] = th
        th.start()
        busy = True
    elif not busy:
        _ASYNC["n_skip"] = int(_ASYNC["n_skip"]) + 1

    act = _ASYNC["act"]
    age = (now - _ASYNC["t_done"]) if _ASYNC["t_done"] else None
    meta = dict(_ASYNC["meta"] or {})
    meta.update({"busy": bool(_ASYNC["thread"] is not None and _ASYNC["thread"].is_alive()),
                 "age_s": (round(age, 2) if age is not None else None),
                 "n_done": _ASYNC["n_done"], "n_skip": _ASYNC["n_skip"],
                 "err": _ASYNC["err"], "min_period_s": min_period_s,
                 "mode": "async"})
    return act, meta
