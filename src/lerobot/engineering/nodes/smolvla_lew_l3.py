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
# 🧵 550B 单线程 (老倪 2026-10-31「功能逻辑只能有一个线程, 断点都要进入」):
#   L3 前向原来固定丢到 l3-smolvla 线程 ⇒ 断点跳线程。单线程模式下当场算完。
from ..thread_policy import spawn_or_inline as _spawn_or_inline

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))          # src/lerobot/engineering/nodes → repo

_CK_DEFAULT = "outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model"
_IMGSZ_DEFAULT = 128
_TASK_DEFAULT = "metaworld 光模块插拔"
_AR_API = "http://127.0.0.1:8797"
_CAM_ORDER = ("local", "arm", "gold", "surface")     # 优先本机在线那路; 其余取决于产线链路

# 类级缓存 (进程内只加载一次) / 熔断标记
_CACHE = {"pol": None, "pre": None, "post": None, "dev": None, "ck": None, "task": None,
          "load_ms": None, "failed": None, "failed_t": 0.0, "n_infer": 0, "t_prev_curr": None}


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


def build_obs13(root, log=None):
    """从真机 TCP 真值构造 **13 维真机口径**观测 (新数据集 zmax_live_215ep1 同源)。

    口径写死 (tools/live_ds_to_lerobot.py:114 `st = joints + pose`):
      [0:6]   关节角 j1..j6  (deg, 来自 latest.json joint[] rad×57.2958)
      [6:9]   TCP x,y,z      (mm, latest.json 的 m×1000)
      [9:13]  四元数 qx,qy,qz,qw
    取不到真值 ⇒ (None, meta), 不拿 0 冒充。
    """
    import json as _j
    p = os.path.join(os.path.dirname(_live_dir(root)), "rokae_sdk", "tcp_out", "latest.json")
    meta = {"src": "zmax_data/rokae_sdk/tcp_out/latest.json", "age_s": None, "dim": 13}
    try:
        d = _j.load(open(p, encoding="utf-8")) or {}
        meta["age_s"] = round(time.time() - os.path.getmtime(p), 3)
    except Exception as e:                                                   # noqa: BLE001
        meta["err"] = "%s: %s" % (type(e).__name__, e)
        return None, meta

    joint = d.get("joint") or []
    if len(joint) < 6:
        meta["err"] = "关节缺失: joint=%d 维" % len(joint)
        return None, meta
    q = [d.get(k) for k in ("qx", "qy", "qz", "qw")]
    if any(v is None for v in q):
        q = [0.0, 0.0, 0.0, 1.0]                                             # 无姿态 ⇒ 单位四元数如实标
        meta["quat_note"] = "真值无四元数 ⇒ 单位四元数(如实标)"
    st = np.zeros(13, dtype=np.float64)
    st[0:6] = np.asarray(joint[:6], dtype=np.float64) * 57.29577951308232    # rad → deg
    st[6:9] = [float(d.get("x") or 0.0) * 1000.0,
               float(d.get("y") or 0.0) * 1000.0,
               float(d.get("z") or 0.0) * 1000.0]                           # m → mm
    st[9:13] = np.asarray(q, dtype=np.float64)
    meta["state_fill"] = 13
    return st, meta


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
    # 🐛 2026-10-31 老倪「还是循环」(u 一直是 0): 原来是**永久熔断** —— 只要第一次加载赶上
    #   CUDA OOM (机器上同时跑了两个画布循环 + sam3, 8G 显存占满), 之后每拍都判"已熔断",
    #   策略永远不加载、u 恒为 0, 看着就像循环空转。改成冷却重试: 隔 SS_L3_RETRY_S 秒 (默认 60) 再试。
    if _CACHE["failed"] is not None and os.environ.get("SS_L3_FORCE_RETRY") != "1" \
            and (time.time() - float(_CACHE.get("failed_t") or 0)) < float(os.environ.get("SS_L3_RETRY_S", "60")):
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

        ck = os.environ.get("SS_L3_CK", "")
        if not ck:
            # 🎯 唯一口径: 7 维真机 action (x,y,z,a,b,c,grip) —— 位姿逐点取 215 点真值表。
            #    **绝不静默回退**到 4 维老 ckpt: 那样断点看到 (1,10,4) 会被误判成"格式不对",
            #    实际是拿错了模型。拿不到就明确报错, 让调试一眼看见。
            _pref = ["outputs/train/smolvla_live1115_7d_v1/checkpoints/last/pretrained_model",
                     "outputs/train/smolvla_live1115_7d_v1/checkpoints/000050/pretrained_model",
                     "outputs/train/smolvla_live1115_7d_v1/checkpoints/000250/pretrained_model"]
            for _c in _pref:
                _p = _c if os.path.isabs(_c) else os.path.join(root, _c)
                if os.path.isdir(_p) and os.path.isfile(os.path.join(_p, "model.safetensors")):
                    ck = _p
                    break
            if not ck:
                raise FileNotFoundError(
                    "7 维 L3 ckpt 不存在 (%s/checkpoints/{last,000050,...} 都没 model.safetensors) "
                    "⇒ 先训练, 或用 SS_L3_CK 显式指向 7 维 ckpt。不要退回 4 维口径。"
                    % _pref[0].split("/checkpoints")[0])
        if not os.path.isabs(ck):
            ck = os.path.join(root, ck)
        if not os.path.isdir(ck):
            raise FileNotFoundError("ckpt 不存在: %s" % ck)
        _dev = dev or os.environ.get("SS_L3_DEV") or ("cuda" if torch.cuda.is_available() else "cpu")
        # 🔴 本地 ckpt + 本地 VLM 缓存齐备 ⇒ 必须关掉 hub 校验。
        #    实测(2026-11-15 17:16 py-spy 栈): from_pretrained → SmolVLMWithExpert.__init__
        #    → AutoProcessor.from_pretrained → get_processor_dict → cached_file → hf_hub_download
        #    → _httpx_follow_hub_redirects_with_backoff 卡住: 本地有缓存也先联网查 etag,
        #    网络不通就 http_backoff 反复重试, 一拍几十秒 ⇒ 主循环超时重启 ⇒ predict_action 永远轮不到。
        if os.path.isdir(ck):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            try:
                import huggingface_hub.constants as _hfc
                _hfc.HF_HUB_OFFLINE = True
            except Exception:                                                # noqa: BLE001
                pass
        pol = SmolVLALewPolicy.from_pretrained(ck)
        pol.eval()
        pol.to(_dev)
        # 🔎 口径硬校验: 断点看到的维度必须等于部署口径 7 —— 否则调的是错模型的数
        _ad = int(getattr(pol.config, "action_dim", 0) or 0)
        _ch = int(getattr(pol.config, "chunk_size", 0) or 0)
        if _ad != 7 and os.environ.get("SS_L3_ALLOW_DIM", "") != str(_ad):
            raise ValueError(
                "L3 ckpt action_dim=%d (应为 7 = x,y,z,a,b,c,grip) @ %s\n"
                "  ⇒ 这个 ckpt 是旧口径, 断点会看到 (1,%d,%d) 而不是 (1,%d,7)。\n"
                "  ⇒ 换 7 维 ckpt, 或设 SS_L3_ALLOW_DIM=%d 强制接受(仅排查用)。"
                % (_ad, ck, _ch, _ad, _ch, _ad))
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
                       "task": task, "load_ms": round((time.monotonic() - t0) * 1000, 1),
                       # 🔎 接口契约 (部署前必须与训练同源; 不一致要在 infer 里当场报错, 不要崩在 normalize)
                       "contract": {"action_dim": int(pol.config.action_dim),
                                    "state_dim": int(getattr(pol.config, "state_dim", -1)),
                                    "chunk": int(pol.config.chunk_size),
                                    "n_action_steps": int(pol.config.n_action_steps),
                                    "resize": list(pol.config.resize_images_to or []),
                                    "siglip": int(pol.config.siglip_image_size),
                                    "norm_action": str((pol.config.normalization_mapping or {}).get("ACTION")),
                                    "input_features": list((pol.config.input_features or {}).keys())}})
        try:                                 # 📋 模型台账: 终端一行说清 L3 到底加载了没
            from lerobot.engineering.model_log import note as _note
            _n_par = sum(p.numel() for p in pol.parameters()) / 1e6
            _note("L3", "SmolVLA+LEW 策略", ck, True, elapsed=time.monotonic() - t0,
                  detail="参数量 %.0fM · 设备 %s · 指令 %r" % (_n_par, _dev, task[:28]))
        except Exception:                                                # noqa: BLE001
            pass
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
        _CACHE["failed_t"] = time.time()          # 冷却计时起点 (见 _load_policy 开头)
        try:                                 # 📋 台账也要如实记"没加载"
            from lerobot.engineering.model_log import note as _note
            _note("L3", "SmolVLA+LEW 策略", ck if "ck" in dir() else "", False,
                  detail="加载失败 → %s" % _CACHE["failed"][:60])
        except Exception:                                                # noqa: BLE001
            pass
        if log:
            log("⚠️ L3 SmolVLA 加载失败 (已熔断, 后续拍不再重试): %s" % _CACHE["failed"])
        return None, None, None, None, {"err": _CACHE["failed"]}


def infer(img, obs39, root, log=None, cond=None):
    """一次真前向: AR 帧 + state(13/39) [+ 流形引擎条件 cond] → 物理动作。
    cond: 15 维 (SE(3) ξ̂(6) + manifold6 + intent3) 或 None(None ⇒ 与改造前逐位相同)。
    返回 (act|None, meta)。"""
    pol, pre, post, dev, lmeta = _load_policy(root, log)
    if pol is None:
        return None, {"stage": "load", **lmeta}
    t0 = time.monotonic()
    try:
        import torch
        from PIL import Image
        sz = int(os.environ.get("SS_L3_IMGSZ", str(_IMGSZ_DEFAULT)))
        # 🐛 2026-10-31: np.asarray(PIL) 拿到的缓冲是**只读**的 ⇒ torch.from_numpy 报
        #   "non-writable tensor ... undefined behavior" 刷屏。np.array(copy=True) 显式复制成可写。
        im = np.array(Image.fromarray(np.asarray(img)).resize((sz, sz), Image.LANCZOS), dtype=np.uint8, copy=True)
        it = torch.from_numpy(im).permute(2, 0, 1).float().unsqueeze(0) / 255.0
        # 🔎 接口口径硬校验: 观测维度必须与 ckpt 的 state_dim 一致, 否则当场报错并给出切换命令
        _ct = _CACHE.get("contract") or {}
        _sd = int(_ct.get("state_dim", -1))
        if _sd > 0 and len(np.asarray(obs39).reshape(-1)) != _sd:
            return None, {**lmeta, "err": "口径不符: ckpt state_dim=%d, 本拍观测=%d 维 ⇒ 换 ckpt: SS_L3_CK=<新训练产物>/pretrained_model"
                          % (_sd, len(np.asarray(obs39).reshape(-1))),
                          "contract": _ct}
        st = torch.from_numpy(np.asarray(obs39, dtype=np.float32)).unsqueeze(0)
        # 🔎 图像/状态键按 ckpt 的 input_features 对齐 (老 ckpt 用 observation.image, 新数据集是 observation.images.top)
        _ikeys = _ct.get("input_features") or ["observation.image", "observation.state"]
        batch = {}
        for _k in _ikeys:
            if _k.startswith("observation.image"):
                batch[_k] = it.to(dev)
            elif _k.startswith("observation.state"):
                batch[_k] = st.to(dev)
        batch["task"] = _CACHE["task"]
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
            # 🎯 流形引擎条件约束 (SE(3) ξ̂ + manifold6 + intent3, 15 维):
            #    真送进 select_action → action_head.apply_l4_cond 拼成额外条件 token。
            #    cond=None 时一个 token 都不加 ⇒ 与改造前逐位相同 (零回退)。
            _l4t = None
            if cond is not None:
                try:
                    _cv = np.asarray(cond, dtype=np.float32).reshape(1, -1)
                    _l4t = torch.as_tensor(_cv, dtype=torch.float32, device=dev)
                    lmeta["l4_cond_dim"] = int(_cv.shape[1])
                    lmeta["l4_cond_injected"] = True
                except Exception as _ce:                                   # noqa: BLE001
                    lmeta["l4_cond_err"] = str(_ce)
                    lmeta["l4_cond_injected"] = False
            pred = pol.select_action(batch, l4_cond=_l4t)
            # 🔴 head 出口是否已是真机口径 (config.unnorm_out=True ⇒ predict_action 里已做 MIN_MAX 逆变换)
            #    是则**绝不能再 post 一次**, 否则双重反归一化 (mm 再被当 [-1,1] 拉伸, 动作全废)。
            _head_unnorm = bool(getattr(getattr(pol, "config", None), "unnorm_out", False))
            if _head_unnorm:
                act = pred
                lmeta["unnorm"] = "head(出口直出真机口径)"
            else:
                act = post(pred) if post is not None else pred           # 🔴 反归一化, 缺则动作全错
                lmeta["unnorm"] = "node(post)"
        # 🎯 出口维度按 ckpt 口径取全 (4=xyz+grip / 7=xyz+abc+grip), 不再写死 [:4]
        #    写死会把 a/b/c 切掉 —— head 出 7 维, 到这儿只剩 4 个, 姿态永远传不下去。
        a = np.asarray(act.detach().cpu().float()).reshape(-1)
        _ad = int((_CACHE.get("contract") or {}).get("action_dim") or a.size)
        a = a[:_ad]
        _CACHE["n_infer"] = int(_CACHE.get("n_infer") or 0) + 1
        return a, {**lmeta, "infer_ms": round((time.monotonic() - t0) * 1000, 2),
                   "img_sz": sz, "n_infer": _CACHE["n_infer"], "shape": list(a.shape)}
    except Exception as e:                                                   # noqa: BLE001
        return None, {**lmeta, "err": "infer: %s: %s" % (type(e).__name__, e),
                      "infer_ms": round((time.monotonic() - t0) * 1000, 2)}


def peek_state_dim(root, log=None):
    """按 ckpt 契约决定观测维度 (39=metaworld 老口径 / 13=真机口径). 加载失败按 39 兜底。"""
    try:
        _load_policy(root, log)
        return int((_CACHE.get("contract") or {}).get("state_dim") or 39)
    except Exception:                                                        # noqa: BLE001
        return 39


def cache_status():
    return {"loaded": _CACHE["pol"] is not None, "failed": _CACHE["failed"],
            "ck": _CACHE["ck"], "dev": _CACHE["dev"], "load_ms": _CACHE["load_ms"],
            "n_infer": _CACHE.get("n_infer", 0), "task": _CACHE["task"]}


# ─────────────────────────────────────────────────────────── 异步前向 (常驻循环不阻塞)
# 实测单次前向 0.8~1.0s (含 CUDA/预处理), 而画布常驻循环是 10Hz tick ⇒ 同步调用会把整循环拖到
# 1s/拍。这里把前向放后台线程: 节点每拍**立即**拿到最近一次真结果 (带 age/是否在算), 模型照旧真跑。
_ASYNC = {"thread": None, "act": None, "meta": None, "t_done": None, "t_start": None,
          "n_done": 0, "n_skip": 0, "err": None}


def infer_async(img, obs39, root, log=None, min_period_s=1.5, cond=None):
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
                _a, _m = infer(img, obs39, root, log, cond=cond)
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

        # 🧵 单线程: 当场算完 (断点停在本拍主线程); 多线程: 起 worker 并回放上一轮结果
        th = _spawn_or_inline("l3-smolvla", _job)
        _ASYNC["thread"] = th
        busy = bool(th is not None and th.is_alive())
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
