#!/usr/bin/env python3
"""快反射层「只提示不拦」开关(现场一次性/长期授权) —— 带审计。

老倪 2026-10-12: 「别拦我，有提示就行了。」
  ⇒ 快反射层(遮挡/糊化 · 裁决过期 · 裁决缺失)不再拦住下发, 但照算照写日志, 页面照显示。

用法:
  python tools/vl_fast_warn_ctl.py status
  python tools/vl_fast_warn_ctl.py on  --by "老倪(现场)" --note "别拦我, 有提示就行了" [--minutes 720]
  python tools/vl_fast_warn_ctl.py off --by "..." --note "恢复拒发"

落盘: ~/zmax/zmax_data/vl_fast_warn_only.json (原子写, 0600)
审计: ~/zmax/zmax_data/vl_fast_warn_only.jsonl (每次开/关/查询各一行, 追加)
执行器每次下发**实时读**该文件 ⇒ 不需要重启执行器。
"""
import argparse, json, os, sys, time

P = os.path.expanduser("~/zmax/zmax_data/vl_fast_warn_only.json")
AUD = P + "l"


def _audit(rec):
    rec["ts"] = time.time()
    rec["ts_str"] = time.strftime("%F %T")
    try:
        with open(AUD, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:                                              # noqa: BLE001
        print("  (审计写失败: %s)" % e)


def read():
    try:
        return json.load(open(P, encoding="utf-8"))
    except Exception:                                                   # noqa: BLE001
        return {}


def state():
    d = read()
    on = bool(d.get("enabled"))
    left = None
    if on and d.get("until"):
        try:
            left = max(0.0, float(d["until"]) - time.time()) / 60.0
        except Exception:                                               # noqa: BLE001
            left = None
    if on and left is not None and left <= 0:
        return False, d, 0.0
    return on, d, left


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["on", "off", "status"])
    ap.add_argument("--by", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--minutes", type=float, default=0.0, help="0 = 不自动到期")
    a = ap.parse_args()
    on, d, left = state()

    if a.cmd == "status":
        print("快反射层: %s" % ("⚠️ 只提示不拦(开)" if on else "🛡 拒发(fail-closed)"))
        if d:
            print("  文件: %s" % P)
            print("  开启: %s · by=%s · note=%s" % (d.get("ts_str"), d.get("by"), d.get("note")))
            print("  到期: %s" % (d.get("until_str") or "不自动到期"))
            if left is not None:
                print("  剩余: %.1f 分钟" % left)
        _audit({"cmd": "status", "on": on})
        return 0

    if a.cmd == "off":
        if os.path.exists(P):
            bak = P + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
            os.replace(P, bak)
            print("  旧文件已备份: %s" % bak)
        else:
            print("  (原本就没有开关文件)")
        _audit({"cmd": "off", "by": a.by, "note": a.note})
        print("✅ 已恢复「拒发(fail-closed)」 —— 执行器下次下发即生效(不用重启)")
        return 0

    # on
    rec = {"enabled": True, "ts": time.time(), "ts_str": time.strftime("%F %T"),
           "by": a.by or "现场", "note": a.note or "别拦我, 有提示就行了",
           "scope": "快反射层(遮挡/糊化 · 裁决过期 · 裁决缺失) · 只提示不拦", "until": None, "until_str": None}
    if a.minutes > 0:
        u = time.time() + a.minutes * 60.0
        rec["until"] = u
        rec["until_str"] = time.strftime("%F %T", time.localtime(u))
    tmp = P + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, P)
    _audit({"cmd": "on", "by": rec["by"], "note": rec["note"], "until_str": rec["until_str"]})
    print("✅ 快反射层 = 只提示不拦")
    print("   范围: 遮挡/糊化 · 裁决过期 · 裁决缺失(判据照算 · 日志照写 · 页面照显示)")
    print("   到期: %s" % (rec["until_str"] or "不自动到期"))
    print("   恢复: python tools/vl_fast_warn_ctl.py off  (执行器不用重启, 下次下发即生效)")
    print("   还剩的保护: 真动授权窗 · 包络/爬升/下压/限速/防连点/30s超时 · 控制器限位 · 现场急停")
    return 0


if __name__ == "__main__":
    sys.exit(main())
