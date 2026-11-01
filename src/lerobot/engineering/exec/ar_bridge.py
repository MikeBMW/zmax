# -*- coding: utf-8 -*-
"""ar_bridge — 把状态空间**执行链**的产物写成 AR 渲染指令 (单文件、双分区、单写者函数)。

老倪 2026-11-01: 「画布节点是工程图纸, 是指令, 必须严格执行」「要真接入 AR 场景」
  ⇒ AR 不能再由 tools 侧的推进器自己算段 (那是另一条链), 必须由链上的节点产出:
       规划引导 → 动作调制 → 安全执行 → 技能 → 运动规划 → 动作执行器 → 机器人执行器

为什么要分两个分区而不是两个文件:
  · 段表由 运动规划(n_moveit) 产出 → {"plan": {...a/b/u/seg...}}
  · 执行指令由 机器人执行器(ssact) 产出 → {"exec": {...u_cmd/校验...}}
  两个节点都往同一个文件写, 但**各写自己的分区**, 用文件锁串行化 ⇒ 谁都不会把对方的数据盖掉。
  页面/接口优先读本文件 (新鲜时), 过期或空 ⇒ 回落 ar_cmd.json (老推进器), 不会卡死。
"""
from __future__ import annotations

import json
import os
import time

_REPO = None


def _repo():
    global _REPO
    if _REPO:
        return _REPO
    e = os.environ.get("ZMAX_REPO") or ""
    if e and os.path.isdir(e):
        _REPO = os.path.abspath(e)
        return _REPO
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".git")):
            _REPO = d
            return _REPO
        n = os.path.dirname(d)
        if n == d:
            break
        d = n
    _REPO = os.path.dirname(os.path.abspath(__file__))
    return _REPO


def path():
    data = os.environ.get("ZMAX_DATA") or os.path.join(_repo(), "zmax_data")
    return os.path.join(data, "ss_live", "ar_cmd_chain.json")


def enabled():
    return os.environ.get("ZMAX_AR_CHAIN", "1").strip() not in ("0", "false", "no", "off")


def update(section, payload, src=""):
    """读-改-写一个分区 (带 .lock 文件做进程间互斥)。返回写后的整份 dict。"""
    if not enabled():
        return None
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    lock = p + ".lock"
    for _ in range(50):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(0.002)
    else:
        return None                        # 抢不到锁就不写 (宁可少写一拍, 也不写坏)
    try:
        cur = {}
        try:
            with open(p, encoding="utf-8") as f:
                cur = json.load(f) or {}
        except Exception:                                                # noqa: BLE001
            cur = {}
        cur.setdefault("seq", 0)
        cur["seq"] = int(cur.get("seq") or 0) + 1
        cur["t"] = time.time()
        cur["ts"] = time.strftime("%H:%M:%S")
        cur["src"] = src or cur.get("src") or ""
        cur[section] = dict(payload or {})
        cur[section + "_src"] = src
        cur[section + "_t"] = cur["t"]
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
        os.replace(tmp, p)
        return cur
    finally:
        try:
            os.unlink(lock)
        except Exception:                                                # noqa: BLE001
            pass


def read():
    try:
        with open(path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return None
