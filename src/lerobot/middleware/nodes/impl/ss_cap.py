# -*- coding: utf-8 -*-
"""ss_cap — 节点实现正文 (文件名 = 画布节点: ss_cap)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_cap   ·   registry key: ss_cap
"""

def node_ss_cap(ctx):
    """🧭 能力档位 (数据源层) — L2 / L3 / L4 三档循环开关 (2026-09-08 老倪)

    双击节点 = 切换档位 (L2 → L3 → L4 → L2…), 档位写 module._cap_level, ▶运行 按档位
    配置任务链:
      L2 基础: 插装成功光模块 (mode=insert 8 段, 解析+MLP 小模型)
      L3 +smolvla: 插→拔→AOI 检测→放回 全链 (mode=full 13 段; VLM 真实编码在链)
      L4 +流形预测世界模型: 失败自主恢复直到最终完成任务 (cap=l4 恢复预算 ×2,
        引擎分级回退=恢复执行体; predictor 世界模型 = 流形专家预测器节点, 训练后给恢复方向)
    """
    log = ctx.get("log")
    mod = ctx.get("module")
    desc = {
        "L2": "基础: 插装成功光模块 (insert 8 段)",
        "L3": "+smolvla: 插→拔→AOI 检测→放回 全链 (full 13 段)",
        "L4": "+世界模型: 失败自主恢复直到最终完成任务 (恢复预算×2)",
    }

    # 端口 (2026-11-10): 画布 sscap.out1 → ssintact.in4 / ssvlm.in1 / ssff.in1 / swintact.in3
    # 四个下游都要「当前档位」, 原实现返回 (bool, msg) 元组 ⇒ 4 条边全空。
    def _cap_out(_cur, _msg=None):
        _d = {"kind": "cap", "layer": _cur, "ok": True,
              "cap": _cur, "cap_level": _cur, "level": _cur,
              "desc": desc.get(_cur, ""), "msg": (_msg or ""),
              "src": "src/lerobot/middleware/nodes/impl/ss_cap.py::node_ss_cap"}
        return {"out1": dict(_d), **_d}

    # 🐛 2026-09-09: 统一走 module._toggle_cap (写 node.params.cap_level + 画布重绘),
    #   与单击 radio/双击节点同一条路径 — 避免只切内存档位而画布开关视觉不更新
    if mod is not None and hasattr(mod, "_toggle_cap"):
        try:
            for _n in mod.nodes:
                if _n.get("name") == ctx.get("name"):
                    mod._toggle_cap(_n)
                    _lv = str((_n.get("params") or {}).get("cap_level")
                              or getattr(mod, "_cap_level", "L2"))
                    return _cap_out(_lv, "档位已切换 (画布已重绘)")
        except Exception:                                                  # noqa: BLE001
            pass
    cur = getattr(mod, "_cap_level", "L2") if mod is not None else "L2"
    nxt = {"L2": "L3", "L3": "L4", "L4": "L2"}.get(cur, "L2")
    if mod is not None:
        mod._cap_level = nxt
    if log:
        log(f"🧭 能力档位: {cur} → **{nxt}** [{desc[nxt]}]")
        log(f"   下次 ▶运行 生效 (L4 需 🎥真实化; 引擎分级回退=恢复执行体, predictor 待训练给恢复方向)")
    return _cap_out(nxt, f"能力档位: {nxt} ({desc[nxt]})")


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_cap
