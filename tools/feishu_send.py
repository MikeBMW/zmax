#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_send.py — 可复用的“发消息到飞书”通道 (自换 token, 不走 gateway 的 token 缓存)

背景 (2026-09-09 / feishu-gateway 技能): 长驻 gateway 进程内 lark_oapi 的
tenant_access_token(2h) 过期后不自动刷新 → 报 [99991663] Invalid access token。
本脚本**每次发送前自己换一个新 token**, 因此不受该缓存影响; 与 gateway 通道互为备份。

用法:
  # 发文字 (默认发到 dataworld/静界 报告群)
  python3 tools/feishu_send.py "要发的文本"
  python3 tools/feishu_send.py --text "要发的文本" --chat oc_xxx

  # 发图片 + 可选说明文字 (上传图片拿 image_key → 发 image, 再单独发一条说明)
  python3 tools/feishu_send.py --image /path/to.png
  python3 tools/feishu_send.py --image /path/to.png --text "这是判据图"
  python3 tools/feishu_send.py --image /path/to.png --text "说明" --chat oc_xxx

  # 自检: 换 token / 上传图片都真做, 但不发消息 (只验证链路, 不刷屏)
  python3 tools/feishu_send.py --text "hi" --dry-run
  python3 tools/feishu_send.py --image x.png --dry-run

凭据: 读 ~/.hermes/.env 的 FEISHU_APP_ID / FEISHU_APP_SECRET (不在本文件里)。
目标会话: 默认 FEISHU_REPORT_CHAT_ID (缺省=内置报告群), 可用 --chat 覆盖。
失败自带一次重试 + 错误码提示。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_CHAT = "oc_c0b4048546145c5c581ddd1a9e8f565d"   # dataworld/静界 报告群 (老倪在看)
ENV_FILE = os.path.expanduser("~/.hermes/.env")
BASE = "https://open.feishu.cn/open-apis"

# 常见错误码 → 可执行提示
HINTS = {
    99991663: "token 失效/过期。本脚本已自换 token; 若仍失败, 检查 app 凭据或重启 gateway (systemctl --user restart hermes-gateway)。",
    10003: "app_id 无效, 检查 ~/.hermes/.env 的 FEISHU_APP_ID。",
    10014: "app_secret 无效, 检查 FEISHU_APP_SECRET。",
    230002: "会话不存在/机器人不在该 chat。检查 --chat, 或把机器人拉进群。",
    230055: "文件类型不支持 (视频用 media, 文档用 file)。",
    9499:  "触发飞书频率限制, 稍后重试。",
}


def load_env() -> dict:
    env = {}
    if os.path.isfile(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _post(url, data=None, headers=None, raw=None, ctype=None, timeout=30):
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=raw if raw is not None else (json.dumps(data).encode() if data is not None else None),
        headers=hdrs, method="POST")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"http": r.status, **json.loads(r.read().decode("utf-8", "ignore"))}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:                                        # noqa: BLE001
            body = {}
        return {"http": e.code, **body}
    except Exception as e:                                       # noqa: BLE001
        return {"http": None, "error": f"{type(e).__name__}: {e}"}


def get_token() -> tuple[str, dict]:
    env = load_env()
    aid, sec = env.get("FEISHU_APP_ID", ""), env.get("FEISHU_APP_SECRET", "")
    if not aid or not sec:
        return "", {"error": "缺少 FEISHU_APP_ID/FEISHU_APP_SECRET (在 ~/.hermes/.env)"}
    r = _post(f"{BASE}/auth/v3/tenant_access_token/internal", {"app_id": aid, "app_secret": sec})
    return r.get("tenant_access_token", ""), r


def _send_text_once(tok: str, text: str, chat_id: str) -> dict:
    r = _post(f"{BASE}/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": chat_id, "msg_type": "text",
               "content": json.dumps({"text": text}, ensure_ascii=False)},
              {"Authorization": f"Bearer {tok}"})
    return {"ok": r.get("code") == 0, "code": r.get("code"), "msg": r.get("msg"),
            "message_id": (r.get("data") or {}).get("message_id"), "http": r.get("http")}


def send_text(text: str, chat_id: str = DEFAULT_CHAT) -> dict:
    tok, tr = get_token()
    if not tok:
        return {"ok": False, "stage": "token", **tr}
    out = _send_text_once(tok, text, chat_id)
    out["attempts"] = 1
    if not out["ok"]:                       # 换新 token 重试一次
        tok2, _ = get_token()
        if tok2:
            out = _send_text_once(tok2, text, chat_id)
            out["attempts"] = 2
    if not out["ok"] and out.get("code") in HINTS:
        out["hint"] = HINTS[out["code"]]
    return out


def _upload_image_once(tok: str, path: str) -> dict:
    b = "----zmaximg" + os.urandom(8).hex()
    fn = os.path.basename(path)
    with open(path, "rb") as f:
        body = f.read()
    raw = ((f"--{b}\r\nContent-Disposition: form-data; name=\"image_type\"\r\n\r\nmessage\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{fn}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + body + f"\r\n--{b}--\r\n".encode())
    up = _post(f"{BASE}/im/v1/images", None,
               {"Authorization": f"Bearer {tok}", "Content-Type": f"multipart/form-data; boundary={b}"},
               raw=raw, timeout=60)
    return {"ok": up.get("code") == 0, "code": up.get("code"),
            "image_key": (up.get("data") or {}).get("image_key"), "raw": up if up.get("code") != 0 else None}


def send_image(path: str, chat_id: str = DEFAULT_CHAT, caption: str = "", dry_run: bool = False) -> dict:
    if not os.path.isfile(path):
        return {"ok": False, "err": f"图片不存在: {path}"}
    tok, tr = get_token()
    if not tok:
        return {"ok": False, "stage": "token", **tr}
    up = _upload_image_once(tok, path)
    if not up["ok"]:                        # 换新 token 重试一次
        tok2, _ = get_token()
        if tok2:
            tok = tok2
            up = _upload_image_once(tok, path)
    if not up["ok"]:
        return {"ok": False, "stage": "upload", "image_upload": up}
    ik = up["image_key"]
    if dry_run:
        return {"ok": True, "dry_run": True, "image_key": ik, "note": "dry-run: 已上传, 未发送消息"}
    r = _post(f"{BASE}/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": chat_id, "msg_type": "image", "content": json.dumps({"image_key": ik})},
              {"Authorization": f"Bearer {tok}"})
    out = {"ok": r.get("code") == 0, "code": r.get("code"), "msg": r.get("msg"), "http": r.get("http"),
           "image_key": ik, "message_id": (r.get("data") or {}).get("message_id")}
    if caption:
        rc = _send_text_once(tok, caption, chat_id)
        out.update({"caption_ok": rc["ok"], "caption_id": rc["message_id"], "caption_code": rc["code"]})
    if not out["ok"] and out.get("code") in HINTS:
        out["hint"] = HINTS[out["code"]]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="发消息到飞书 (自换 token, 含一次重试)")
    ap.add_argument("pos_text", nargs="?", default="", help="位置参数: 文本内容")
    ap.add_argument("--text", default="", help="文本内容 (发图时为说明文字)")
    ap.add_argument("--image", default="", help="图片路径 (给了则发图片)")
    ap.add_argument("--chat", default=os.environ.get("FEISHU_REPORT_CHAT_ID", DEFAULT_CHAT),
                    help="目标 chat_id (默认报告群 / 环境变量 FEISHU_REPORT_CHAT_ID)")
    ap.add_argument("--dry-run", action="store_true", help="换 token/上传都真做, 但不发消息")
    a = ap.parse_args()
    text = a.text or a.pos_text

    if not a.image and not text:
        ap.error("至少给 --text/位置文本 或 --image")
    if a.image:
        r = send_image(a.image, a.chat, caption="" if a.dry_run else text, dry_run=a.dry_run)
    else:
        if a.dry_run:
            tok, tr = get_token()
            r = {"ok": bool(tok), "dry_run": True, "token_http": tr.get("http"),
                 "token_code": tr.get("code"), "note": "dry-run: token 已取, 未发送"}
        else:
            r = send_text(text, a.chat)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
