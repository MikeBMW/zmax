#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_send_file.py — 往飞书发**文件**(文档交付用; feishu_send.py 只支持文字/图片)。

链路 (全部真做, 每步回读):
  1. 自换 tenant_access_token (与 feishu_send.py 同源, 不走 gateway 缓存 ⇒ 不踩 99991663)
  2. POST /open-apis/im/v1/files  (multipart/form-data: file_type=stream, file_name, file) → file_key
  3. POST /open-apis/im/v1/messages?receive_id_type=chat_id  msg_type=file, content={"file_key":...}
  4. 打印 message_id (供回读核验)

用法:
  python3 tools/feishu_send_file.py docs/deliverables/a.md [b.md ...]
  python3 tools/feishu_send_file.py --zip            # 把 docs/deliverables/*.md 打包成一个 zip 再发
  python3 tools/feishu_send_file.py --text "文件说明" a.md
  python3 tools/feishu_send_file.py --dry-run a.md   # 只换 token / 只打包, 不发
凭据: ~/.hermes/.env 的 FEISHU_APP_ID / FEISHU_APP_SECRET; 默认会话 FEISHU_REPORT_CHAT_ID。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

DEFAULT_CHAT = "oc_c0b4048546145c5c581ddd1a9e8f565d"          # dataworld/静界 报告群 (老倪在看)
ENV_FILE = os.path.expanduser("~/.hermes/.env")
BASE = "https://open.feishu.cn/open-apis"


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
    aid, asec = env.get("FEISHU_APP_ID", ""), env.get("FEISHU_APP_SECRET", "")
    if not (aid and asec):
        raise SystemExit("缺 FEISHU_APP_ID / FEISHU_APP_SECRET (~/.hermes/.env)")
    body = json.dumps({"app_id": aid, "app_secret": asec}).encode()
    req = urllib.request.Request(BASE + "/auth/v3/tenant_access_token/internal", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise SystemExit("换 token 失败: %s" % d)
    return d["tenant_access_token"]


def upload(tok: str, path: str) -> dict:
    """multipart/form-data 上传 → file_key (非图片走 im/v1/files)。"""
    bd = "----Hermes%s" % uuid.uuid4().hex
    name = os.path.basename(path)
    parts = []
    for k, v in (("file_type", "stream"), ("file_name", name)):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (bd, name)).encode())
    parts.append(open(path, "rb").read())
    parts.append(("\r\n--%s--\r\n" % bd).encode())
    body = b"".join(parts)
    req = urllib.request.Request(BASE + "/im/v1/files", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "multipart/form-data; boundary=" + bd})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": e.read().decode()[:400]}


def send_file(tok: str, file_key: str, chat: str) -> dict:
    body = json.dumps({"receive_id": chat, "msg_type": "file",
                       "content": json.dumps({"file_key": file_key})}).encode()
    req = urllib.request.Request(BASE + "/im/v1/messages?receive_id_type=chat_id", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": e.read().decode()[:400]}


def send_text(tok: str, text: str, chat: str) -> dict:
    body = json.dumps({"receive_id": chat, "msg_type": "text",
                       "content": json.dumps({"text": text})}).encode()
    req = urllib.request.Request(BASE + "/im/v1/messages?receive_id_type=chat_id", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"code": e.code, "msg": e.read().decode()[:400]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--chat", default=os.path.expanduser(load_env().get("FEISHU_REPORT_CHAT_ID", DEFAULT_CHAT)))
    ap.add_argument("--text", default="")
    ap.add_argument("--text-file", default="", help="文字结论从文件读 (多行说明避免 shell 转义出错)")
    ap.add_argument("--zip", action="store_true", help="打包 docs/deliverables/*.md 为一个 zip 再发")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.text_file:
        a.text = open(os.path.expanduser(a.text_file), encoding="utf-8").read().strip()
    files = list(a.files)
    if a.zip:
        out = "docs/deliverables/Z-MAX_交付文档包_%s.zip" % __import__("time").strftime("%Y%m%d")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(glob.glob("docs/deliverables/*.md")):
                z.write(p, os.path.basename(p))
        print(json.dumps({"zipped": out, "n": len(zipfile.ZipFile(out).namelist())}, ensure_ascii=False))
        files.append(out)
    if not files:
        raise SystemExit("没有要发的文件 (给文件名或 --zip)")
    tok = token()
    print(json.dumps({"token": "ok", "len": len(tok)}, ensure_ascii=False))
    if a.dry_run:
        print(json.dumps({"ok": True, "dry_run": True}, ensure_ascii=False))
        return 0
    if a.text:
        print(json.dumps({"text": send_text(tok, a.text, a.chat)}, ensure_ascii=False))
    rc = 0
    for p in files:
        if not os.path.isfile(p):
            print(json.dumps({"file": p, "ok": False, "err": "不存在"}, ensure_ascii=False))
            rc = 1
            continue
        up = upload(tok, p)
        fk = (up.get("data") or {}).get("file_key", "")
        if not fk:
            print(json.dumps({"file": p, "stage": "upload", "resp": up}, ensure_ascii=False))
            rc = 1
            continue
        msg = send_file(tok, fk, a.chat)
        ok = bool(msg.get("code") == 0)
        print(json.dumps({"file": os.path.basename(p), "bytes": os.path.getsize(p), "file_key": fk[:24] + "…",
                          "ok": ok, "message_id": (msg.get("data") or {}).get("message_id"),
                          "msg": msg.get("msg")}, ensure_ascii=False))
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
