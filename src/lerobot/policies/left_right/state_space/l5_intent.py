# -*- coding: utf-8 -*-
"""l5_intent.py — L5 大模型层 → SU(2) 的 L5 槽 (3 维意图方向)

为什么需要它
------------
su2.py 的 L5 层读 `frame["L5_intent"]` (3 个数, 意图向量); 没有人写这个字段时
`encode_layer("L5")` 返回**单位元**并在文档里明写「未接入 LLM」。本模块就是那个写入方:
用 DeepSeek (本机已配 key, 无需申请) 把「当前阶段 + 几何误差 + 夹持/接触 + 检测置信度」
换成一句结构化意图 `{"intent":[x,y,z], "conf":.., "why":".."}`。

口径 (不许含糊)
--------------
· intent 是 **机器人基座系下的期望运动方向**, 3 维 ∈ [-1,1]; 不是绝对位置、不是速度幅值。
· 只输出方向语义 —— 真正的限幅/势函数兜底由 L2 收口 (老倪架构原则: 上层只给意图/条件)。
· 失败 = 没有结果 (返回 None, L5 落单位元 + 日志说明)。**不猜、不填 0 冒充、不用规则假装成大模型。**
· 每进程只一个推理线程 (单飞), 带 TTL 缓存 —— 绝不占住 10Hz 节拍。

对外
----
    intent(obs43=None, frame=None) -> dict | None
        {"vec":[x,y,z], "conf":0..1, "why":"..", "src":"deepseek:<model>",
         "latency_ms":int, "ts":float, "age_s":float, "cos_vs_to_hole":float|None, "suspicious":bool}
    status() -> dict     # 路径/模型/key 有没有/最近一次错误 (面板与排查用)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import numpy as np

API = os.environ.get("SS_L5_BASE", os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
MODEL = os.environ.get("SS_L5_MODEL", "deepseek-flash")
TIMEOUT = float(os.environ.get("SS_L5_TIMEOUT", "60"))
TTL = float(os.environ.get("SS_L5_TTL_S", "60"))   # DeepSeek 实测 60~130s/次 ⇒ 默认 60s 缓存
CALLS_LOG = os.path.join(os.environ.get("ZMAX_DATA", "/home/ubuntu/zmax/zmax_data"),
                         "l5_intent_calls.jsonl")

SYS_PROMPT = ("你是工业装配机器人 (光模块插孔) 的 L5 意图层。"
              "只输出 JSON, 不要解释, 不要 markdown。")

_ST = {"res": None, "t": 0.0, "th": None, "err": None, "n": 0}


def _key():
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    try:
        from .scene_vlm import _key_from_hermes_env
        return _key_from_hermes_env("DEEPSEEK_API_KEY")
    except Exception:                                                      # noqa: BLE001
        pass
    try:
        with open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except Exception:                                                      # noqa: BLE001
        pass
    return None


def _prompt(obs43, frame):
    """短提示 + 小 JSON (L5 实测: 长提示更慢也更爱跑题)。缺项就写「未知」, 不编。"""
    f = frame or {}
    e_mm = None
    if obs43 is not None:
        try:
            o = np.asarray(obs43, float).ravel()
            peg = o[4:7].copy()
            peg[2] += 0.030
            e_mm = np.round((peg - o[36:39]) * 1000.0, 1).tolist()
        except Exception:                                                  # noqa: BLE001
            e_mm = None
    stage = f.get("stage") or f.get("动作") or "未知"
    grasp = f.get("grasp")
    contact = f.get("contact_p")
    conf = f.get("conf")
    parts = [
        "场景: 光模块插入孔位 (peg-in-hole)。",
        "阶段: %s。" % stage,
        "光模块头−孔位误差 e_mm: %s (基座系, +z 向上)。" % (e_mm if e_mm is not None else "未知"),
        "夹持力: %s · 接触概率: %s · 检测置信度: %s。"
        % ("未知" if grasp is None else round(float(grasp), 3),
           "未知" if contact is None else round(float(contact), 3),
           "未知" if conf is None else round(float(conf), 3)),
        "任务: 给出此刻应让末端加速的方向 (基座系单位方向, 目的=减小误差、完成插入), 以及把握度。",
        '只输出: {"intent":[x,y,z],"conf":0~1,"why":"不超过20字"}',
    ]
    return "".join(parts)


def _parse(text):
    """从模型回复里抠出 JSON 并做硬校验 (范围/有限值/非零), 不合格就报错不猜。"""
    s = str(text or "")
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("回复里没有 JSON")
    d = json.loads(s[i:j + 1])
    v = np.asarray(d.get("intent"), dtype=float).reshape(-1)
    if v.size != 3:
        raise ValueError("intent 不是 3 维 (%d)" % v.size)
    if not np.all(np.isfinite(v)):
        raise ValueError("intent 含 NaN/Inf")
    if float(np.linalg.norm(v)) < 1e-3:
        raise ValueError("intent 是零向量")
    v = np.clip(v, -1.0, 1.0)
    conf = d.get("conf")
    try:
        conf = float(np.clip(float(conf), 0.0, 1.0))
    except Exception:                                                      # noqa: BLE001
        conf = None
    return {"vec": [round(float(x), 4) for x in v], "conf": conf,
            "why": str(d.get("why") or "")[:60]}


def _call(obs43, frame):
    key = _key()
    if not key:
        raise RuntimeError("无 DEEPSEEK_API_KEY (env / ~/.hermes/.env 都没有)")
    body = {"model": MODEL, "temperature": 0,
            "max_tokens": int(os.environ.get("SS_L5_MAX_TOKENS", "160")),
            # 关思考 (与 scene_vlm 同口径): 实测开思考 61.7s, 关掉 ~1-3s
            "thinking": {"type": "enabled" if os.environ.get("SS_L5_THINKING") == "1" else "disabled"},
            "messages": [{"role": "system", "content": SYS_PROMPT},
                         {"role": "user", "content": _prompt(obs43, frame)}]}
    req = urllib.request.Request(API.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode())
    text = d["choices"][0]["message"]["content"]
    out = _parse(text)
    out.update({"src": "deepseek:%s" % MODEL, "latency_ms": int((time.time() - t0) * 1000),
                "ts": time.time(), "raw": text[:400]})
    # 语义自检 (只标疑, 不否决): e = 光模块头 − 孔位 (从孔指向模块), 要减小误差就该往 **−e** 走
    #   ⇒ cos_vs_to_hole = cos(intent, −e) 应 ≈ +1; < +0.2 (横着走/反向走) 才标疑, 交上层复核。
    try:
        if obs43 is not None:
            o = np.asarray(obs43, float).ravel()
            peg = o[4:7].copy(); peg[2] += 0.030
            e = peg - o[36:39]
            ne = float(np.linalg.norm(e))
            if ne > 1e-6:
                c = float(np.dot(np.asarray(out["vec"], float) / np.linalg.norm(out["vec"]), -e / ne))
                out["cos_vs_to_hole"] = round(c, 3)
                out["suspicious"] = bool(c < 0.2)
    except Exception:                                                      # noqa: BLE001
        pass
    try:
        os.makedirs(os.path.dirname(CALLS_LOG), exist_ok=True)
        with open(CALLS_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({k: out.get(k) for k in
                                 ("ts", "src", "latency_ms", "vec", "conf", "why",
                                  "cos_vs_to_hole", "suspicious", "raw")},
                                ensure_ascii=False) + "\n")
    except Exception:                                                      # noqa: BLE001
        pass
    return out


def _work(obs43, frame):
    try:
        r = _call(obs43, frame)
        _ST.update({"res": r, "t": time.time(), "err": None})
    except Exception as e:                                                 # noqa: BLE001
        _ST["err"] = "%s: %s" % (type(e).__name__, e)


def intent(obs43=None, frame=None):
    """拿一个**新鲜**的 L5 意图 (非阻塞); 没有就返回 None (调用方落单位元, 如实标注)。

    · TTL 内直接返回缓存; 过期就后台算一次 (单飞), 本拍先用上一份并带 age_s。
    · SS_L5_SYNC=1 = 当场同步算 (调试/单步; 会占 1~3s)。
    · 冷启第一拍: 多线程档后台起线程返回 None; 同步档当场出结果 (保证链路能验证)。
    """
    # 🔴 断点把整拍卡死的第 3 个来源(2026-11-14 实测): 单线程档 spawn_or_inline 把 L5 联网
    #    改成当场同步执行 ⇒ 每拍 urlopen 到 DeepSeek, 60s 超时 ⇒ 主循环回不到 ss_canvas_loop:286,
    #    decide() 一次不跑, 587 永不命中。调试/单线程档一律不联网, 只回缓存。
    _off = str(os.environ.get("ZMAX_LLM_OFF", "")).strip().lower() in ("1", "true", "yes", "on")
    _single = str(os.environ.get("ZMAX_SINGLE_THREAD", "")).strip().lower() in ("1", "true", "yes", "on")
    _online = str(os.environ.get("ZMAX_LLM_ONLINE", "")).strip().lower() in ("1", "true", "yes", "on")
    if (_off or _single) and not _online:
        _r = _ST.get("res")
        if not _r:
            return None
        _o = dict(_r)
        _o["age_s"] = round(time.time() - float(_r.get("ts") or 0.0), 2)
        return _o
    now = time.time()
    res, t = _ST.get("res"), float(_ST.get("t") or 0.0)
    age = (now - t) if t else 1e9
    sync = str(os.environ.get("SS_L5_SYNC", "0")).strip().lower() in ("1", "true", "yes", "on")
    th = _ST.get("th")
    need = (res is None) or (age > TTL)
    if need and sync:
        _work(obs43, frame)                    # 仅显式调试档 (SS_L5_SYNC=1) 才当场算: 会占 60~130s
    elif need and not (th is not None and th.is_alive()):
        # 常态: 后台单飞, 本拍先用上一份 (冷启第一拍 = None ⇒ L5 落单位元 + 日志说明, 绝不卡节拍)
        from lerobot.engineering.thread_policy import spawn_or_inline
        _ST["th"] = spawn_or_inline("ss_l5_intent", lambda: _work(obs43, frame))
    r = _ST.get("res")
    if not r:
        return None
    out = dict(r)
    out["age_s"] = round(time.time() - float(r.get("ts") or 0.0), 2)
    return out


def status():
    key = _key()
    return {"api": API, "model": MODEL, "has_key": bool(key), "ttl_s": TTL,
            "timeout_s": TIMEOUT, "calls": _ST.get("n", 0),
            "last_err": _ST.get("err"),
            "last": {k: (_ST["res"] or {}).get(k) for k in ("ts", "vec", "conf", "why",
                                                            "src", "latency_ms")}
            if _ST.get("res") else None}
