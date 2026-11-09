# -*- coding: utf-8 -*-
"""data — 节点实现正文 (文件名 = 画布节点: data)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_metaworld_data   ·   registry key: data
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
import time  # noqa: F401  (端口输出打 tick 用)

from .shared_runtime import (  # noqa: F401
    _REPO_ROOT,
    os,
)

def node_metaworld_data(ctx):
    """📦 metaworld 数据 — 训练数据源选择"""
    # 总线路径 (n_metaworld.compute) 只给端口, 没有 module/log —— 不许因此直通
    module = ctx.get("module")
    log = ctx.get("log") or (lambda *a, **k: None)
    p = ctx.get("params") or {}
    # === ✏️ 可修改区 START ===
    # 🎬 AR 场景数据源 (老倪 2026-11-10: 「当然要符合画布的选择了, 真正实现 AR 场景」)
    #   画布的「数据源」节点 src_state=AR场景 ⇒ 这里必须真去取 8802 渲染帧, 不是只改个标签。
    _state = str(p.get("src_state") or "").strip()
    if _state.upper().startswith("AR") or str(p.get("source") or "").lower() == "ar":
        import time as _t
        import lerobot.middleware.nodes.impl.shared_runtime as _SR
        _cam = p.get("cam") or "ar3d"
        _arr, _path, _meta = _SR._ar_frame(_cam, ttl=0.35)
        if _arr is None:
            if log:
                log("📦 数据源: AR 场景取帧失败 — %s" % ((_meta.get("gaps") or ["未知"])[0]))
            try:
                if module is not None:
                    module._toggle_source_ctx(ctx.get("name") or "")
            except Exception:                                                # noqa: BLE001
                pass
            return {"out1": {"kind": "ar_frame", "src": "ar", "ok": False,
                             "gaps": (_meta.get("gaps") or ["AR 帧不可用"])},
                    "out2": {"kind": "scene_state", "src": "ar", "ok": False},
                    "out3": {"kind": "image", "src": "ar", "ok": False}}
        else:
            _h, _w = _arr.shape[:2]
            _cp = _meta.get("cam_params") or {}
            _SR._SS_STATE["data_source"] = {
                "src": "ar", "cam": _cam, "w": _w, "h": _h,
                "bytes": _meta.get("bytes"), "frame": _meta.get("frame"),
                "ts": _meta.get("t") or _t.time(), "cam_params": _cp,
                "tick": int(_t.time() * 1000),
            }
            if log:
                log("📦 数据源: AR 场景 (8802 MuJoCo 渲染 · %d×%d · %s B · cam=%s · "
                    "az=%.1f° el=%.1f° dist=%.2fm · 帧 %s)"
                    % (_w, _h, _meta.get("bytes"), _cam,
                       float(_cp.get("az") or 0), float(_cp.get("el") or 0),
                       float(_cp.get("dist") or 0), _meta.get("frame")))
            # 📤 画布端口的真输出 (老倪 2026-11-10: 「哪里是 AR 场景的输出?」)
            #   out1 = 场景帧 (下游 ssvlm/ssyolo/ssintact/n_dsvl 吃的就是它)
            #   out2 = 场景状态 (关节/夹爪/相机参数 —— sssensor/ssuph/ssplan 用)
            #   out3 = 图像句柄 (ss_seg 分割输入, 给路径不搬像素)
            _tick = _SR._SS_STATE["data_source"]["tick"]
            _joints, _grip = None, {}
            try:
                import urllib.request as _ur
                import json as _json
                _base = os.environ.get("ZMAX_AR_RENDER", "http://127.0.0.1:8802")
                with _ur.urlopen(_base + "/joints.json", timeout=2.0) as _r:
                    _j = _json.loads(_r.read().decode("utf-8"))
                _joints = {"R": _j.get("R"), "L": _j.get("L")}
                _grip = {"R": _j.get("gripR"), "L": _j.get("gripL")}
                _jfresh = {"age_s": _j.get("age_s"), "fresh": _j.get("fresh"), "src": _j.get("src")}
            except Exception:                                                # noqa: BLE001
                _jfresh = None
            try:
                if module is not None:
                    module._toggle_source_ctx(ctx.get("name") or "")
            except Exception:                                                # noqa: BLE001
                pass
            return {
                "out1": {"kind": "ar_frame", "src": "ar", "ok": True, "cam": _cam,
                         "frame": _meta.get("frame"), "path": _path,
                         "w": _w, "h": _h, "bytes": _meta.get("bytes"),
                         "ts": _meta.get("t"), "tick": _tick,
                         "cam_params": _cp, "frame_src": "AR 场景 (8802 MuJoCo 渲染)"},
                "out2": {"kind": "scene_state", "src": "ar", "ok": True, "tick": _tick,
                         "scene": "AR 场景 (MuJoCo 8802)", "cam": _cam,
                         "joints": _joints, "grippers": _grip, "joints_meta": _jfresh,
                         "cam_params": _cp},
                "out3": {"kind": "image", "src": "ar", "ok": True, "tick": _tick,
                         "path": _path, "frame": _meta.get("frame"), "w": _w, "h": _h},
            }
    source = p.get("source", "metaworld")   # metaworld(占位集) | orin(真实产线)
    # 非 AR 也要把画布选择落到同一个状态里, 否则下游 10s 内还按上一次的 AR 走 (数据同步)
    try:
        import time as _t2
        import lerobot.middleware.nodes.impl.shared_runtime as _SR2
        _sel = (str(p.get("src_state") or source or "")).strip().lower()
        _norm = "real" if ("真机" in _sel or "orin" in _sel) else ("sim" if ("仿真" in _sel or "metaworld" in _sel) else "sim")
        _SR2._SS_STATE["data_source"] = {"src": _norm, "cam": None, "ts": _t2.time()}
    except Exception:                                                        # noqa: BLE001
        pass
    frames = p.get("frames", 696)           # 期望帧数 (展示用)
    # 📂 真实数据层 (2026-09-02 老倪: 数据源必须接 lerobot 框架 src/lerobot/datasets/,
    #   不是控制台模板 — 与传感器融合/前馈节点同构: 右键打开 + VSCode 断点都进 datasets 真实实现)
    # 🐛 2026-09-02: 改用 exec(compile(src, 真实路径, "exec")) 加载 — spec_from_file_location
    #   动态加载的模块 debugpy 不感知 (断点设置时文件未加载 → 绑定不生效, 实测 probe 执行了
    #   但 62 行断点不命中); compile 带真实 filename → 函数 co_filename 指向真实文件,
    #   debugpy 按路径查表必定命中 (同引擎 perception/cognition 断点行为)
    try:
        _p = os.path.join(_REPO_ROOT, "src", "lerobot", "datasets", "metaworld_data_source.py")
        _ns = {"__file__": _p, "__name__": "lerobot.datasets.metaworld_data_source"}
        with open(_p, encoding="utf-8") as _f:
            _src = _f.read()
        exec(compile(_src, _p, "exec"), _ns)
        _probe = _ns.get("probe_data_source")
        if _probe is None:
            raise RuntimeError("数据层缺少 probe_data_source")
        _info = _probe()
        if log:
            if _info:
                log(f"📦 数据源: {source} · 真实仓库 {_info['path']} · "
                    f"{_info['frames']}帧/{_info['episodes']}集 · {_info['label']} · "
                    f"特征[{','.join(_info['features'])}]")
            else:
                log(f"📦 数据源: {source} · 本机无训练仓库 (仅画布占位) · 期望 {frames}帧")
    except Exception as _e:
        if log:
            log(f"📦 数据源: {source} · 数据层探测失败: {_e}")
    # 数据源策略: 想强制某来源训练, 在「训练」节点的 data_source 里改
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 激活数据源 (勿改)
    try:
        if module is not None:
            module._toggle_source_ctx(ctx.get("name") or "")
    except Exception:                                                # noqa: BLE001
        pass
    # 非 AR 也给出端口真输出 (仿真/真机), 端口口径与 AR 一致 —— 切换前后下游只认 out1.src
    _tsim = int(time.time() * 1000)
    return {
        "out1": {"kind": "env_frame", "src": str(source), "ok": True, "tick": _tsim,
                 "frames": frames, "declared_domain": str(source),
                 "note": "仿真/真机源: 帧由引擎(ss_engine_loop)/真机旁路提供"},
        "out2": {"kind": "scene_state", "src": str(source), "ok": True, "tick": _tsim,
                 "task": p.get("task"), "state_dim": p.get("state_dim"),
                 "action_dim": p.get("action_dim")},
        "out3": {"kind": "image", "src": str(source), "ok": True, "tick": _tsim, "path": None},
    }


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_metaworld_data
