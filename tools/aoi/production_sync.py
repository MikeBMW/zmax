#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""production_sync.py — 🔍 AOI 产线程序 ↔ 状态空间工程 的旁路对齐工具

架构(2026-10-08 老倪定):
    产线程序 = 跑在**工控机 192.168.23.23** 上的 `D:\\xspace\\ultralytics_AOI\\cam_finger_10082_work_v20.py`
               (10082 金手指) / `cam_surface_10083_work_v20.py` (10083 表面)
    调试程序 = 本仓库 `tools/aoi/` 里的同名副本 + 画布节点「🔍 外观质量检测」的
               `src/lerobot/policies/yolo_3d/quality_check.py::AOIQualityChecker`

    ⇒ 调参/改判据**先在仓库副本上做**, 用本工具对齐/下发, 而不是直接改工控机上那份。

用法:
    # 看现状(离线, 只读清单 + 算仓库副本哈希)
    python3 tools/aoi/production_sync.py status

    # 把产线那份**拉回来**(经反向通道 agent_hub), 与仓库副本对比出差异
    python3 tools/aoi/production_sync.py diff   --port 10082
    python3 tools/aoi/production_sync.py pull   --port 10082            # 覆盖仓库副本
    python3 tools/aoi/production_sync.py pull   --port 10082 --dry-run  # 只看差异不改文件

    # 校验清单里的哈希与仓库副本是否一致(离线)
    python3 tools/aoi/production_sync.py verify

下发(部署)仍走既有部署器(带哈希核对 + 失败回滚):
    python3 tools/aoi_remote_deploy.py --finger tools/aoi/cam_finger_10082_work_v24.py --only 10082
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MANIFEST = os.path.join(_ROOT, "tools", "aoi", "PRODUCTION_MANIFEST.json")


def manifest():
    with open(_MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def item_for(port):
    for it in manifest()["items"]:
        if int(it["port"]) == int(port):
            return it
    raise SystemExit("清单里没有端口 %s (有: %s)" % (port, [i["port"] for i in manifest()["items"]]))


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cmd_status(_a):
    m = manifest()
    print("清单: %s (%s)" % (_MANIFEST, m["generated_at"]))
    print("说明: %s" % m["note"])
    for it in m["items"]:
        p = os.path.join(_ROOT, it["repo_copy"])
        live = sha256_file(p) if os.path.exists(p) else "缺文件"
        same = "✅一致" if live == it["sha256"] else "⚠️与清单不符(副本被改过)"
        print("  · %s 端口=%s %s" % (it["title"], it["port"], it["repo_copy"]))
        print("      仓库副本 sha=%s (%s B) %s" % (live[:16], it["bytes"], same))
        print("      产线文件   %s" % it["remote_file"])
    return 0


def cmd_verify(_a):
    bad = 0
    for it in manifest()["items"]:
        p = os.path.join(_ROOT, it["repo_copy"])
        if not os.path.exists(p):
            print("❌ 缺文件 %s" % it["repo_copy"])
            bad += 1
            continue
        live = sha256_file(p)
        ok = (live == it["sha256"])
        print("%s %s sha=%s" % ("✅" if ok else "⚠️", it["repo_copy"], live[:16]))
        bad += 0 if ok else 1
    print("清单校验:", "✅ 全过" if bad == 0 else "⚠️ %d 项与清单不符(改过就更新清单)" % bad)
    return 0


def _pull_remote(remote_file, timeout_s=180):
    """经反向通道把产线那份文件的字节取回来 (base64 走 agent_hub 回执)。"""
    sys.path.insert(0, os.path.join(_ROOT, "tools"))
    from aoi_remote_deploy import remote                      # 复用同一条通道
    win = remote_file.replace("/", "\\")
    ps = ("$b=[IO.File]::ReadAllBytes('%s'); "
          "[Convert]::ToBase64String($b)" % win)
    out = remote(ps, wait=timeout_s, label="aoi_pull")
    if "TIMEOUT" in out or "ENQUEUE_FAIL" in out:
        raise SystemExit("✗ 反向通道没回: %s" % out.strip()[:200])
    # 回执里混着命令回显/空行 → 取最长的纯 base64 片段
    cands = re.findall(r"[A-Za-z0-9+/=]{1000,}", out.replace("\n", "").replace("\r", ""))
    if not cands:
        raise SystemExit("✗ 回执里没有 base64 内容:\n%s" % out[:400])
    try:
        return base64.b64decode(max(cands, key=len))
    except Exception as e:
        raise SystemExit("✗ base64 解码失败: %r" % (e,))


def cmd_pull(a):
    it = item_for(a.port)
    dst = os.path.join(_ROOT, it["repo_copy"])
    cur = open(dst, "rb").read() if os.path.exists(dst) else b""
    print("拉取 %s …" % it["remote_file"])
    data = _pull_remote(it["remote_file"], a.timeout)
    rsha = hashlib.sha256(data).hexdigest()
    csha = hashlib.sha256(cur).hexdigest() if cur else "(无副本)"
    print("产线那份: %d B sha=%s" % (len(data), rsha[:16]))
    print("仓库副本: %d B sha=%s" % (len(cur), csha[:16]))
    if rsha == csha:
        print("✅ 两边一致, 无需动作")
        return 0
    print("⚠️ 两边不一致 —— 产线那份与仓库副本有差异")
    if a.dry_run:
        print("(dry-run: 未写文件)")
        return 2
    with open(dst, "wb") as f:
        f.write(data)
    print("已写入 %s (备份: %s.bak_%s)" % (it["repo_copy"], it["repo_copy"],
                                        time.strftime("%Y%m%d_%H%M%S")))
    return 2


def cmd_diff(a):
    b = dict(vars(a))
    b["dry_run"] = True
    return cmd_pull(argparse.Namespace(**b))


def main():
    ap = argparse.ArgumentParser(description="AOI 产线程序 ↔ 状态空间工程 旁路对齐")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("verify").set_defaults(fn=cmd_verify)
    p = sub.add_parser("pull"); p.add_argument("--port", default=10082)
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--timeout", type=float, default=180)
    p.set_defaults(fn=cmd_pull)
    d = sub.add_parser("diff"); d.add_argument("--port", default=10082)
    d.add_argument("--dry-run", action="store_true", default=True)
    d.add_argument("--timeout", type=float, default=180)
    d.set_defaults(fn=cmd_diff)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
