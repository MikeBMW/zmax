#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_dashboard_push.py — 把「大屏统一数据源」渲染成一张**飞书卡片**推给群。

数据源: tools/dashboard_source.py 落盘的 dashboard.json (缺省读权威副本
        <repo>/zmax_data/datapush/dashboard.json; 可 --refresh 先重采再推)。
通道  : 复用 tools/feishu_send.py 的「自换 token」通道(msg_type=interactive), 与 dataworld/静界
        报告群同源; app 凭据只从 ~/.hermes/.env 读(**绝不打印**)。
        目标群默认 = FEISHU_REPORT_CHAT_ID, 否则内置报告群; 可 --chat 覆盖。

卡片内容: 标题(版本) + 关键指标(时间/帧龄/GPU/数据/模型/场景/远程/版本同源)
          + **异常项高亮**(stale 端点 / 不可达 / 同源不一致 / 版本偏差 / 围栏非法 / GPU 采集失败)。

用法:
  python3 tools/feishu_dashboard_push.py --dry     # 只打印卡片 JSON, 不真发
  python3 tools/feishu_dashboard_push.py --send    # 真发; 失败如实报错(不假装成功)
  python3 tools/feishu_dashboard_push.py --dry --refresh   # 先重采再渲染

退出码: 0=sent 或 dry 成功; 1=失败(附 stage/code)。
红线: 不打印任何 token/密码; 发送前对整张卡片再做一次已知口令断言。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import feishu_send as fs              # noqa: E402  自换 token 通道
import remote_monitor_aggregate as rma  # noqa: E402  复用脱敏断言

ROOT = os.path.dirname(_HERE)
DASH = os.path.join(ROOT, "zmax_data", "datapush", "dashboard.json")


def load_dashboard(refresh: bool) -> dict:
    if refresh:
        import dashboard_source as dsrc
        return dsrc.build()
    with open(DASH, encoding="utf-8") as fh:
        return json.load(fh)


def _anomalies(d: dict) -> list:
    """返回高亮用的异常项字符串列表(空 = 全绿)。"""
    out = []
    g = d.get("gpu") or {}
    if g.get("error"):
        out.append("GPU 采集失败: %s" % g["error"])
    vs = d.get("version_sync") or {}
    for dv in (vs.get("deviations") or []):
        out.append("版本偏差: %s" % dv)
    if vs.get("ok") is False:
        out.append("版本同源体检: 不一致")
    sc = d.get("scene") or {}
    if sc.get("fences_valid") is False:
        out.append("场景围栏非法: %s" % ", ".join(sc.get("fence_invalid") or []))
    if sc.get("out_of_range"):
        out.append("场景坐标越界: %s" % ", ".join(sc["out_of_range"][:4]))
    rm = d.get("remote") or {}
    for n in (rm.get("unreachable") or []):
        out.append("端点不可达: %s" % n)
    for n in (rm.get("stale") or []):
        out.append("端点数据 stale: %s" % n)
    for f in (rm.get("mismatch") or []):
        out.append("同源不一致: %s" % f)
    m = d.get("models") or {}
    if m.get("training_active"):
        out.append("训练进行中: %d 个进程" % m["training_active"])
    return out


def build_card(d: dict) -> dict:
    g = d.get("gpu") or {}
    ds = d.get("datasets") or {}
    m = d.get("models") or {}
    sc = d.get("scene") or {}
    rm = d.get("remote") or {}
    vs = d.get("version_sync") or {}
    anom = _anomalies(d)

    gpu_line = ("采集失败: %s" % g["error"]) if g.get("error") else (
        "%s · util **%s%%** · mem %s/%s MiB · %sC · 进程 %s"
        % (g.get("name"), g.get("util"), g.get("mem_used"), g.get("mem_total"),
           g.get("temp"), g.get("procs")))

    active_layers = "  ".join("%s✓" % l["layer"] for l in (m.get("layers") or []) if l.get("active"))
    remote_line = ("离线未采" if rm.get("error") else
                   "OK **%s/%s** · stale %s · 帧龄 **%ss**"
                   % (rm.get("endpoints_ok"), rm.get("endpoints_total"),
                      rm.get("stale_count"), rm.get("frame_age_s")))

    facts = "  ".join(
        ("%s%s" % (f["fact"], "✓" if f.get("consistent") is True else
                   ("✗" if f.get("consistent") is False else "⏸")))
        for f in (rm.get("same_source") or []))

    lines = [
        "**⏱ 数据时间** %s   帧龄 %ss" % (d.get("generated_at"), rm.get("frame_age_s")),
        "**🖥 GPU** %s" % gpu_line,
        "**🗂 数据资产** %s · %s 条 · %s 文件 · 报告 %s 个"
        % (ds.get("size_human"), ds.get("items"), ds.get("file_count"), ds.get("reports_files")),
        "**🧠 模型** 在役就绪 %s/%s  %s  · 训练中 %s"
        % (m.get("active_ready"), m.get("count"), active_layers, m.get("training_active")),
        "**🗺 场景** objects %s · fences %s · traj %s · 隐藏 %s · 轨迹显示 %s"
        % (sc.get("objects"), sc.get("fences"), sc.get("trajectories"),
           sc.get("deleted"), sc.get("traj_show")),
        "**📡 远程端点** %s" % remote_line,
        "**🔗 同源判定** %s" % (facts or "-"),
        "**🏷 版本同源** ok=%s · 权威 %s · Release %s"
        % (vs.get("ok"), vs.get("canonical"), vs.get("release_tag")),
    ]

    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    if anom:
        warn = "**⚠️ 异常 %d 项**\n" % len(anom) + "\n".join("· %s" % a for a in anom)
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": warn}})
    else:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "✅ 无异常项"}})

    title = "Z-MAX 大屏 · v%s" % (d.get("version") or "?")
    header_tpl = "orange" if anom else "green"
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": header_tpl,
                   "title": {"tag": "plain_text", "content": title}},
        "elements": elements,
    }


def _default_base_url(port: int = 8799) -> str:
    """给 web / 手机端用的基址: 取本机默认路由网卡的 IPv4 (现场局域网), 取不到退回 127.0.0.1。"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:                                                         # noqa: BLE001
        ip = "127.0.0.1"
    return "http://%s:%d" % (ip, port)


def build_web_task_card(d: dict, base_url: str) -> dict:
    """🖥 产品大屏 → web 任务单 (老倪: 「将功能页的产品大屏完全同步工位总览的服务, 完善数据流服务,
    然后让 web 将这个数据推流, 做到手机远程操作, APP发布; 把这个发给飞书, 通知 web」)。"""
    s = d.get("screen") or {}
    ch = s.get("channels") or []
    rb = s.get("robot") or {}
    rows = []
    for c in ch[:6]:
        rows.append("· %s %s %s fps · 帧龄 %ss%s"
                    % (c.get("label") or c.get("key"), "在线" if c.get("online") else "离线",
                       c.get("fps"), c.get("age_s"), "  ⚠️卡死" if c.get("stalled") else ""))
    lines = [
        "**① 同源** 产品大屏 与 工位总览 = **同一台服务 (:8793) 的同一份在役状态**: 通道 **%s/%s 在线** · "
        "最大帧龄 **%ss** · 手动闸 motion_armed=**%s** · 机械臂 %s/%s"
        % (s.get("channels_online"), s.get("channels_total"), s.get("frame_age_max_s"),
           s.get("motion_armed"), rb.get("power"), rb.get("operation")),
        "**② 单一数据源(推流用)** %s/dashboard.json  ·  数据时间 %s" % (base_url, d.get("generated_at")),
        "**③ 手机远程页** %s/  (手机优先视口/CSS 已适配; 远程动作受现场授权闸约束)" % base_url,
        "**④ 交付 APP** %s/dl/ZMAX-Dash.apk" % base_url,
        "**⑤ 工位通道实况**\n" + ("\n".join(rows) if rows else "· 服务未连通(如实为空)"),
        "**请 web 接续**: 拉 ② 的 JSON 做推流 → ③ 手机端远程操作页 → ④ 出/发布 APP",
    ]
    return {"config": {"wide_screen_mode": True},
            "header": {"template": "blue" if s.get("ok") else "orange",
                       "title": {"tag": "plain_text", "content": "🖥 Z-MAX 产品大屏 → web 交付任务单"}},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]}


def _send_card(card: dict, chat_id: str) -> dict:
    tok, tr = fs.get_token()
    if not tok:
        return {"ok": False, "stage": "token", **tr}
    r = fs._post("%s/im/v1/messages?receive_id_type=chat_id" % fs.BASE,
                 {"receive_id": chat_id, "msg_type": "interactive",
                  "content": json.dumps(card, ensure_ascii=False)},
                 {"Authorization": "Bearer %s" % tok})
    out = {"ok": r.get("code") == 0, "code": r.get("code"), "msg": r.get("msg"),
           "http": r.get("http"), "message_id": (r.get("data") or {}).get("message_id")}
    if not out["ok"] and out.get("code") in fs.HINTS:
        out["hint"] = fs.HINTS[out["code"]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把大屏数据渲染成飞书卡片并推送")
    ap.add_argument("--dry", action="store_true", help="只打印卡片 JSON, 不真发")
    ap.add_argument("--send", action="store_true", help="真发到群")
    ap.add_argument("--refresh", action="store_true", help="先重采大屏数据源再渲染")
    ap.add_argument("--notify-web", dest="notify_web", action="store_true",
                    help="推送「产品大屏 → web 任务单」(数据源/手机页/APP 链接 + 同源实测)")
    ap.add_argument("--base-url", default=os.environ.get("ZMAX_SCREEN_BASE", ""),
                    help="卡片里给 web 的基址 (默认按本机局域网 IP 拼 :8799)")
    ap.add_argument("--chat", default=os.environ.get("FEISHU_REPORT_CHAT_ID", fs.DEFAULT_CHAT),
                    help="目标 chat_id (默认报告群)")
    a = ap.parse_args(argv)
    if not (a.dry or a.send):
        a.dry = True   # 缺省 dry, 避免误发

    try:
        d = load_dashboard(a.refresh)
    except FileNotFoundError:
        print(json.dumps({"ok": False, "stage": "load",
                          "error": "无 dashboard.json; 先跑 `python3 tools/dashboard_source.py` 或加 --refresh"},
                         ensure_ascii=False))
        return 1
    except Exception as e:                                            # noqa: BLE001
        print(json.dumps({"ok": False, "stage": "load", "error": "%s: %s" % (type(e).__name__, e)},
                         ensure_ascii=False))
        return 1

    if a.notify_web:
        base = a.base_url or _default_base_url()
        card = build_web_task_card(d, base)
        _ok, _hits, _n = rma.assert_no_secrets(json.dumps(card, ensure_ascii=False))
        if not _ok:
            print(json.dumps({"ok": False, "stage": "redact",
                              "error": "卡片命中 %d 个已知口令, 已中止" % _hits}, ensure_ascii=False))
            return 1
        if a.dry:
            print(json.dumps({"ok": True, "dry": True, "base_url": base, "card": card},
                             ensure_ascii=False, indent=2))
            return 0
        res = _send_card(card, a.chat)
        res["dry"] = False
        res["base_url"] = base
        res["kind"] = "product_screen_web_task"
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("ok") else 1

    card = build_card(d)
    # 发送前脱敏断言: 整张卡片 JSON 里不应出现任何已知口令
    okr, hits, nsec = rma.assert_no_secrets(json.dumps(card, ensure_ascii=False)
                                            + json.dumps(d, ensure_ascii=False))
    if not okr:
        print(json.dumps({"ok": False, "stage": "redact",
                          "error": "卡片内容命中 %d 个已知口令, 已中止" % hits}, ensure_ascii=False))
        return 1

    if a.dry:
        print(json.dumps({"ok": True, "dry": True, "anomalies": _anomalies(d),
                          "card": card}, ensure_ascii=False, indent=2))
        return 0

    res = _send_card(card, a.chat)
    res["dry"] = False
    res["anomalies"] = _anomalies(d)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
