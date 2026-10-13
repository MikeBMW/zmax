# -*- coding: utf-8 -*-
"""verify_feishu_zip.py — 飞书端逐字节核验 (不信自述: 从服务端把文件拉回来比 sha256)。

用法: python3 tools/verify_feishu_zip.py <message_id> <本地文件>
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_send_file import BASE, load_env, token                             # noqa: E402


def get(url: str, tok: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer %s" % tok})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    mid, local = sys.argv[1], sys.argv[2]
    tok = token()
    d = get("%s/im/v1/messages/%s" % (BASE, mid), tok)
    if d.get("code") != 0:
        print("读消息失败: %s" % json.dumps(d, ensure_ascii=False)[:300])
        return 1
    item = (d.get("data", {}).get("items") or [{}])[0]
    body = json.loads(item.get("body", {}).get("content") or "{}")
    fk, fn, fs = body.get("file_key"), body.get("file_name"), body.get("file_size")
    print("服务端: 文件 %s · %s B · file_key=%s" % (fn, fs, fk))
    url = "%s/im/v1/messages/%s/resources/%s?type=file" % (BASE, mid, fk)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer %s" % tok})
    out = "/tmp/_feishu_dl_%s.zip" % os.getpid()
    with urllib.request.urlopen(req, timeout=180) as r, open(out, "wb") as f:
        f.write(r.read())
    n = os.path.getsize(out)
    h_remote, h_local = sha(out), sha(local)
    print("拉回: %d B · sha256 %s" % (n, h_remote[:32]))
    print("本地: %d B · sha256 %s" % (os.path.getsize(local), h_local[:32]))
    same = (n == os.path.getsize(local)) and (h_remote == h_local)
    print("逐字节核验: %s" % ("✅ 一致 (飞书端就是本地这一份)" if same else "❌ 不一致"))
    os.unlink(out)
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
