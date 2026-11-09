# -*- coding: utf-8 -*-
"""data — 节点实现正文 (文件名 = 画布节点: data)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_metaworld_data   ·   registry key: data
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _REPO_ROOT,
    os,
)

def node_metaworld_data(ctx):
    """📦 metaworld 数据 — 训练数据源选择"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
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
        return module._toggle_source_ctx(ctx["name"])
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
    return module._toggle_source_ctx(ctx["name"])


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_metaworld_data
