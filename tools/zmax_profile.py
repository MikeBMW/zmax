#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_profile.py — 三产品 (550A/550B/550C) **开发分工**的单一读取口。

真源: `config/platform/zmax_product.json` → `products[<档>].dev_profile`
      (老倪 2026-10-15: 「以后同步开发 550A 550B 550C 产品，A产品负责新技能、新算法，逻辑最多；
        B产品开通所有 TOPIC 最大化 debug，允许 vscode 联调；C产品稳定性优先，未经验证的算法都关闭，
        通讯以效率优先，不用发出序列化 topic，只要在共享内存中快速传递信号，不用开启信号分析，
        不用开启 3D 场景，只需要远程旁路功能，能够远程运行和真机部署」)

为什么要有它: 三档的差异 (话题开合/通讯方式/界面开合/能否 VSCode/算法准入) 原来散在各处硬编码,
改一处漏一处就会互相矛盾 (实测过同类问题: 标题/能力两处各写各的)。这里收成一处, 谁要判档都调这里。

用法:
    from zmax_profile import dev_profile, topics_mode, comm_mode, gui_on, vscode_ok, remote_bypass_ok, algo_policy
    topics_mode()            # 'all' | 'core' | 'none'
    comm_mode()              # 'dds' | 'shm'
    gui_on('signal_analysis')  # True/False  (C 档=False: 不用开信号分析)
    gui_on('scene_3d')         # True/False  (C 档=False: 不用开 3D 场景)
    vscode_ok()              # True/False  (只有调试档允许 VSCode 联调)
    algo_policy()            # 'on' | 'debug' | 'off'  (C 档 off = 未验证算法全关)
    algo_allowed('新算法名')  # C 档只放 verified_algorithms 里的

产品档从 `active_product` 取; 也可用环境变量 `ZMAX_PRODUCT` 覆盖 (做 A/B/C 差异验证时不必改真源)。
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")
# 🏭 出厂骨架回落 (老倪 2026-10-15「产品 550A 550B 550C 同步发布」):
#   平台/实例解耦后, 实例真源 config/platform/ 不在仓库里 ⇒ 全新安装 (含 Windows/macOS 安装包) 读不到产品档
#   ⇒ 三档 550A/550B/550C 就选不出来。这里按 canvas 同一套规矩回落: 实例真源 → 仓库 defaults/ → 冻结包 _MEIPASS。
def _product_candidates():
    _c = [PRODUCT_J, os.path.join(ROOT, "defaults", "config", "platform", "zmax_product.json")]
    _mp = getattr(__import__("sys"), "_MEIPASS", None)
    if _mp:
        _c.append(os.path.join(_mp, "defaults", "config", "platform", "zmax_product.json"))
        _c.append(os.path.join(_mp, "config", "platform", "zmax_product.json"))
    return _c


def product_json():
    """返回第一个存在且可读的产品真源路径 (找不到返回实例路径, 便于报错时指出该放哪)。"""
    for _p in _product_candidates():
        if os.path.isfile(_p):
            return _p
    return PRODUCT_J

# 读不到 dev_profile 时的兜底 (按"调试档"= 全开, 宁可看得到也别把现场功能悄悄关掉)
_DEFAULT = {
    "role": "未配置 (兜底=调试档全开)",
    "new_algorithms": "debug",
    "topics": "all",
    "comm": "dds",
    "gui": {"signal_analysis": True, "scene_3d": True},
    "vscode_debug": True,
    "remote_bypass": True,
    "verified_algorithms": [],
}

_CACHE = {"key": None, "v": None}


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return -1.0


def product():
    """当前产品档 (550A/550B/550C); 环境变量 ZMAX_PRODUCT 可覆盖, 便于做档位差异验证。"""
    env = (os.environ.get("ZMAX_PRODUCT") or "").strip()
    if env:
        return env
    try:
        with open(product_json(), encoding="utf-8") as f:
            return str(json.load(f).get("active_product") or "550B")
    except Exception:                                                       # noqa: BLE001
        return "550B"


def dev_profile(prod=None):
    """返回该档的 dev_profile dict (含兜底键; 真源改了自动重读)。"""
    p = prod or product()
    key = (_mtime(product_json()), p)
    if _CACHE["key"] == key and _CACHE["v"] is not None:
        return _CACHE["v"]
    prof = dict(_DEFAULT)
    try:
        with open(product_json(), encoding="utf-8") as f:
            d = json.load(f)
        prof.update((d.get("products", {}).get(p) or {}).get("dev_profile") or {})
        prof.setdefault("product", p)
        prof.setdefault("name", (d.get("products", {}).get(p) or {}).get("name", p))
    except Exception:                                                       # noqa: BLE001
        prof.setdefault("product", p)
    _CACHE["key"], _CACHE["v"] = key, prof
    return prof


def topics_mode(prod=None):
    return str(dev_profile(prod).get("topics") or "all")


def comm_mode(prod=None):
    return str(dev_profile(prod).get("comm") or "dds")


def shm_dir(prod=None):
    return str(dev_profile(prod).get("shm_dir") or "/dev/shm/zmax_ss_engine")


def gui_on(feature, prod=None):
    """界面功能开合: 'signal_analysis' 信号分析 / 'scene_3d' 3D 场景 (C 档都 False)。"""
    return bool((dev_profile(prod).get("gui") or {}).get(feature, True))


def vscode_ok(prod=None):
    """允许 VSCode 联调 (断点/launch.json 模板生效) —— 只有调试档开。"""
    return bool(dev_profile(prod).get("vscode_debug", True))


def remote_bypass_ok(prod=None):
    """远程旁路 (远程运行 + 真机部署) —— C 档保留的唯一入口。"""
    return bool(dev_profile(prod).get("remote_bypass", True))


def algo_policy(prod=None):
    """'on'(开发: 新算法全开) | 'debug'(调试: 逐条开关) | 'off'(量产: 只放已验证)。"""
    return str(dev_profile(prod).get("new_algorithms") or "debug")


def algo_allowed(name, prod=None):
    """该档能否跑这个算法。C 档: 只放 verified_algorithms 名单里的 (其余硬关, 不是"默认关")。"""
    pol = algo_policy(prod)
    if pol == "on":
        return True
    if pol == "debug":
        return True                      # 调试档: 由逐条开关显式控制, 这里不额外拦
    return str(name) in set(dev_profile(prod).get("verified_algorithms") or [])


def dds_topics_allowed(topics, prod=None):
    """按档位过滤序列化话题: all=全放 (只受运行时 mode 另有约束) · core=核心集 · none=一个都不发。"""
    mode = topics_mode(prod)
    if mode == "none":
        return []
    if mode == "all":
        return list(topics)
    core = ("ss_stage", "ss_torque", "ss_engine", "ss_energy", "ss_meta_task", "ss_meta_pred",
            "hw_state", "heartbeat", "ss_cfg_names",
            *["skill_%s" % c for c in ("sk01", "sk02", "sk03", "sk04", "sk05", "sk06", "sk07", "sk08")])
    return [t for t in topics if t in core]


def summary(prod=None):
    """一行摘要 (可打印/可复制; 判据与界面共用同一句)。"""
    p = dev_profile(prod)
    return ("%s %s | topics=%s comm=%s 信号分析=%s 3D场景=%s VSCode=%s 远程旁路=%s 算法=%s"
            % (p.get("product"), p.get("role"), topics_mode(prod), comm_mode(prod),
               gui_on("signal_analysis", prod), gui_on("scene_3d", prod),
               vscode_ok(prod), remote_bypass_ok(prod), algo_policy(prod)))


if __name__ == "__main__":
    import sys
    for _p in ([sys.argv[1]] if len(sys.argv) > 1 else ["550A", "550B", "550C"]):
        print(summary(_p))
