#!/usr/bin/env python3
"""现场盯着走: 每隔几秒拉一次采集守护 + 图像桥, 打出「帧数/跨度/转角/清晰度/中心距离」表并在跑偏时喊。

为什么需要: 操作员边走边问「够了么 / 我这样走对不对」时, 只回一句"继续"毫无信息量;
**中心深度**、**清晰度**、**累计转角** 三项能当场分开「相机没对着工件」「走太快」「只平移没换视角」。
实测: 中心深度 1215mm = 对着空处(应 250~350mm); 清晰度(拉普拉斯方差) 198 = 行走过快/低纹理面(正常 400~500);
转角只涨十几度而位移涨了几十厘米 = 一路平移, 重建天花板不会动。

用法:
  python3 live_capture_monitor.py --secs 90 --interval 6
  python3 live_capture_monitor.py --secs 300 --rot-target 180
  # 守护(gs_autocap)与桥(gs_ros_bridge)不在默认端口时用 env 改
  GS_HEALTH_URL=http://127.0.0.1:8806/health GS_BRIDGE=http://127.0.0.1:8811 \
    python3 live_capture_monitor.py --secs 300

输出一列 `+N` 是两次采样之间的新增帧数(≈实际采集 Hz × 间隔)。
🔴 停超 20s 守护会立刻 finalize + 送训(占 GPU 3~10 分钟) ⇒ 看到 `帧数 +0` 且 `静态跳` 涨就提醒他别停。
🔴 `转角` 列来自守护 /health 的 `cur.rot_deg`(采集端按相邻帧 rpy 变化累加); 老版本守护没这个字段时显示 `-`, 不报错。
"""
import argparse
import json
import os
import time
import urllib.request

HEALTH = os.environ.get("GS_HEALTH_URL", "http://127.0.0.1:8806/health")
BRIDGE = os.environ.get("GS_BRIDGE", "http://127.0.0.1:8811")
DIST_OK = (250, 350)      # mm, 画面中心 80x60 区域深度中位数应落在这个区间
SHARP_MIN = 250.0         # 拉普拉斯方差低于此认为糊/走得快


def get(url, timeout=4.0):
    return urllib.request.urlopen(url, timeout=timeout).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=6.0)
    ap.add_argument("--rot-target", type=float, default=180.0,
                    help="累计转角目标(度): 低于它说明只在平移, 没换视角")
    args = ap.parse_args()

    import cv2
    import numpy as np

    print("%-8s %7s %6s %7s %8s %7s %8s %8s  %s" % (
        "时刻", "帧数", "新增", "跨度m", "静态跳", "转角°", "清晰度", "中心mm", "提示"), flush=True)
    last_f = None
    rot_seen = None
    t0 = time.time()
    while time.time() - t0 < args.secs:
        hint = ""
        try:
            h = json.loads(get(HEALTH))
            cur = h.get("cur") or {}
            f = int(cur.get("frames", 0))
            span = float(cur.get("duration_s", 0.0))
            skip = int(cur.get("skipped_static", 0))
            rot = cur.get("rot_deg")
            rot_seen = rot if rot is not None else rot_seen
            sharp, dm = -1.0, -1.0
            try:
                jpg = get(BRIDGE + "/frame.jpg")
                png = get(BRIDGE + "/depth.png")
                im = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                dep = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED).astype(np.float32) * 0.0001
                sharp = float(cv2.Laplacian(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
                hh, ww = dep.shape
                c = dep[hh // 2 - 30:hh // 2 + 30, ww // 2 - 40:ww // 2 + 40]
                v = c[c > 0]
                dm = float(np.median(v)) * 1000 if len(v) else -1.0
            except Exception:
                pass
            if last_f is not None and f == last_f:
                hint += "← 没新帧(停了? 超 20s 会收尾送训)"
            if dm > 0 and not (DIST_OK[0] <= dm <= DIST_OK[1]):
                hint += (" 中心 %dmm %s" % (dm, "太远, 靠近到 25~35cm" if dm > DIST_OK[1] else "太近, D405 最近 ~7cm"))
            if 0 <= sharp < SHARP_MIN:
                hint += " 模糊/走快了, 慢到 30~50mm/s"
            if rot is not None and f >= 40 and float(rot) < args.rot_target:
                hint += " 转角仅 %.0f°/目标 %.0f°(只在平移, 绕弧或转腕)" % (float(rot), args.rot_target)
            d = "" if last_f is None else ("+%d" % (f - last_f))
            last_f = f
            print("%-8s %7d %6s %7.2f %8d %7s %8.0f %8.0f  %s" % (
                time.strftime("%H:%M:%S"), f, d or "-", span, skip,
                ("%.0f" % float(rot)) if rot is not None else "-", sharp, dm, hint.strip()), flush=True)
        except Exception as e:
            print("采样失败: %s" % str(e)[:80], flush=True)
        time.sleep(args.interval)

    if rot_seen is not None:
        verdict = "够" if float(rot_seen) >= args.rot_target else "不够(只平移, 补绕弧/转腕)"
        print("收工判定: 累计转角 %.0f° / 目标 %.0f° ⇒ %s" % (float(rot_seen), args.rot_target, verdict), flush=True)


if __name__ == "__main__":
    main()
