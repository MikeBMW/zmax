#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_check_messages.py — 飞书端回读核验 (发的到底有没有到, 文件是不是同一份)。

老倪 2026-10-12: 「检查飞书端, 同步飞书结果」—— 不信发送返回值, 直接读回飞书服务端。

能力:
  1. 拉取指定会话最近消息 (GET /open-apis/im/v1/messages, container_id_type=chat)
  2. 过滤本机器人 (cli_...) 发出的消息, 打印 时间/类型/message_id/正文摘要
  3. --download <file_key> <本地文件>: 把飞书端的文件拉回来, 与本地文件比对 sha256 + 字节数
     (证明"发上去的那份"与本地是同一份, 不是只看到 file_key 就宣布成功)

用法:
  python3 tools/feishu_check_messages.py                      # 列最近 20 条 + 标出我发的
  python3 tools/feishu_check_messages.py --n 40
  python3 tools/feishu_check_messages.py --download file_v3_xxx /tmp/back.zip --compare docs/deliverables/X.zip
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

ENV_FILE = os.path.expanduser("~/.hermes/.env")
BASE = "https://open.feishu.cn/open-apis"
DEFAULT_CHAT = "oc_c0b4048546145c5c581ddd1a9e8f565d"
BOT = "cli_a87851ffe46b500d"


def load_env() -> dict:
    env = {}
    if os.path.isfile(ENV_FILE):
        for ln in open(ENV_FILE, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, _, v = ln.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def token() -> str:
    env = load_env()
    body = json.dumps({"app_id": env.get("FEISHU_APP_ID", ""), "app_secret": env.get("FEISHU_APP_SECRET", "")}).encode()
    req = urllib.request.Request(BASE + "/auth/v3/tenant_access_token/internal", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise SystemExit("换 token 失败: %s" % d)
    return d["tenant_access_token"]


def get(tok: str, url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": e.read().decode()[:400]}


def list_msgs(tok: str, chat: str, n: int, page_token: str = "") -> dict:
    u = ("%s/im/v1/messages?container_id_type=chat&container_id=%s&sort_type=ByCreateTimeDesc&page_size=%d"
         % (BASE, chat, max(1, min(n, 50))))
    if page_token:
        u += "&page_token=" + page_token
    return get(tok, u)


def paged(tok: str, chat: str, pages: int) -> list:
    """翻页取更早的消息 (每页 50), 返回 [msg...] 新→旧。"""
    out, pt = [], ""
    for _ in range(max(1, pages)):
        d = list_msgs(tok, chat, 50, pt)
        if d.get("code") != 0:
            break
        data = d.get("data") or {}
        out += data.get("items") or []
        pt = data.get("page_token") or ""
        if not data.get("has_more") or not pt:
            break
    return out


def brief(m: dict) -> str:
    mt = m.get("msg_type")
    try:
        c = json.loads(m.get("body", {}).get("content") or "{}")
    except Exception:                                                              # noqa: BLE001
        c = {}
    if mt == "text":
        return (c.get("text") or "").replace("\n", " ⏎ ")[:150]
    if mt == "file":
        return "file: %s (%s B)" % (c.get("file_name", "?"), c.get("file_size", "?"))
    if mt == "image":
        return "image: %s" % (c.get("image_key", "")[:20] + "…")
    if mt == "post":
        return "post(富文本)"
    if mt == "system":
        return "system"
    return str(c)[:120]


def download(tok: str, file_key: str, out: str) -> dict:
    req = urllib.request.Request("%s/im/v1/files/%s" % (BASE, file_key), headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        return {"ok": False, "code": e.code, "msg": e.read().decode()[:300]}
    with open(out, "wb") as f:
        f.write(data)
    return {"ok": True, "out": out, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", default="")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--pages", type=int, default=1, help="翻页数 (每页 50, 用于找更早的消息)")
    ap.add_argument("--find", default="", help="只打印正文/message_id 含该串的消息")
    ap.add_argument("--download", nargs=2, metavar=("FILE_KEY", "OUT"))
    ap.add_argument("--compare", default="", help="与这个本地文件比 sha256")
    a = ap.parse_args()
    chat = a.chat or load_env().get("FEISHU_REPORT_CHAT_ID", DEFAULT_CHAT)
    tok = token()
    if a.download:
        r = download(tok, a.download[0], a.download[1])
        if a.compare and r.get("ok"):
            r["local"] = os.path.basename(a.compare)
            r["local_sha256"] = sha256_file(a.compare)
            r["identical"] = (r["sha256"] == r["local_sha256"])
            r["local_bytes"] = os.path.getsize(a.compare)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get("ok") else 1
    if a.pages > 1:
        items = paged(tok, chat, a.pages)
        if not items:
            print(json.dumps({"ok": False, "chat": chat, "err": "翻页无结果"}, ensure_ascii=False))
            return 1
    else:
        d = list_msgs(tok, chat, a.n)
        if d.get("code") != 0:
            print(json.dumps({"ok": False, "chat": chat, "resp": d}, ensure_ascii=False))
            return 1
        items = (d.get("data") or {}).get("items") or []
    if a.find:
        items = [m for m in items if a.find in (brief(m) + " " + str(m.get("message_id", "")))]
    mine = []
    print("会话 %s · 最近 %d 条 (服务端返回 %d 条)" % (chat, a.n, len(items)))
    for m in items:
        sid = (m.get("sender") or {}).get("id", "")
        ts = m.get("create_time", "")
        try:
            t = dt.datetime.fromtimestamp(int(ts) / 1000).strftime("%m-%d %H:%M:%S")
        except Exception:                                                          # noqa: BLE001
            t = str(ts)
        tag = "★我" if sid == BOT else "  "
        dele = " [已撤回]" if m.get("deleted") else ""
        print("%s %s  %-6s %s  %s%s" % (tag, t, m.get("msg_type"), m.get("message_id", "")[:30], brief(m), dele))
        if sid == BOT:
            mine.append({"t": t, "msg_type": m.get("msg_type"), "message_id": m.get("message_id"),
                         "deleted": bool(m.get("deleted")), "brief": brief(m)})
    print(json.dumps({"ok": True, "n_total": len(items), "mine": len(mine), "mine_list": mine}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
