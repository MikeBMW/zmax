# -*- coding: utf-8 -*-
"""n_hil — 节点实现正文 (文件名 = 画布节点: n_hil)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_hil   ·   registry key: n_hil
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _HIL_CACHE,
    _SS_DIR,
    os,
    time,
)

def node_hil(ctx):
    """🙋 HIL 人机在环 · 状态↔指示 — 状态空间状态发 ECS web, 并取回人的指示 (2026-09-26)

    真源: src/lerobot/policies/left_right/state_space/hil_bridge.py
    通道: /api/relay/hil/state (上行) + /agent/{prompt,reply} (下行, from=hil_web/hil_bridge)
    红线: 动作类指示一律拒答并记为待授权; 本节点不下发任何真机动作
    网页: https://datadrive.world/hil.html (hermes 形式聊天界面)
    """
    log = ctx.get("log")
    try:
        import json as _j
        import sys as _s
        import urllib.request as _u
        for _x in (_SS_DIR, os.path.abspath(os.path.join(_SS_DIR, "..", "..", "..", ".."))):
            if _x not in _s.path:
                _s.path.insert(0, _x)
        # 🚦 2026-11-01: 本节点原每拍都往 datadrive.world 打 HTTPS (timeout=15s) + 拉一次指示 (12s),
        #   实测 py-spy 十次采样有九次卡在 urlopen 的 connect 里 ⇒ 整圈被它吃掉, 链产物 >3s 就被
        #   AR 接口判过期 (AR_CMD_FRESH_S=3.0), 页面回落老推进器。改成**按节拍上报**: 常驻循环里
        #   最少间隔 ZMAX_HIL_EVERY_S (默认 15s) 才真发一次, 单次超时压到 1.5s; GUI 手动档不受限。
        _now = time.time()
        _in_loop = bool(os.environ.get("ZMAX_CANVAS_HZ"))
        _every = float(os.environ.get("ZMAX_HIL_EVERY_S") or (15.0 if _in_loop else 0.0))
        if _now - _HIL_CACHE["t"] < _every:
            return True
        _HIL_CACHE["t"] = _now
        from lerobot.policies.left_right.state_space.hil_bridge import build_snapshot, poll_instructions
        snap = build_snapshot()
        req = _u.Request("https://datadrive.world/api/relay/hil/state", data=_j.dumps(snap).encode(),
                         headers={"Content-Type": "application/json"}, method="POST")
        with _u.urlopen(req, timeout=float(os.environ.get("ZMAX_HIL_TIMEOUT_S") or 1.5)) as r:
            pub = _j.loads(r.read().decode() or "{}")
        inst = {} if _in_loop else poll_instructions()      # 指示轮询由 8795 HIL API 常驻负责
        if log:
            s2 = snap["snapshot"]
            log("🙋 HIL 人机在环: 状态已上报(ok=%s) · 阶段=%s 帧龄=%ss · 事件头 %s"
                % (pub.get("ok"), s2.get("stage"), s2.get("frame_age_s"),
                   {k: v for k, v in (s2.get("events") or {}).items() if not k.startswith("_")}))
            log("   ← 人的指示: 处理 %d 条 %s" % (inst.get("handled", 0), inst.get("items") or ""))
            log("   网页 https://datadrive.world/hil.html (只读状态+软先验指示; 动作类拒答)")
            # 📱 2026-09-27 老倪: 「从这个点, 我要通过 APP 跟状态空间交互」—— 手机入口挂在本节点上
            log("   📱 手机 APP 现场页 http://10.163.146.78:8791/room (全看 6 路相机 + 远程操作 + 本节点交互)")
            log("   本地 HIL API http://10.163.146.78:8795 (与本节点同一个大脑: build_snapshot/handle_instruction)")
            log("   装包下载 http://10.163.146.78:8791/dl/ZMAX-Site.apk (App 长按屏幕可改地址)")
        return True
    except Exception as e:
        if log:
            log("❌ HIL 桥执行失败: %s: %s" % (type(e).__name__, str(e)[:120]))
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_hil
