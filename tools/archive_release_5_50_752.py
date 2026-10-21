#!/usr/bin/env python3
"""归档 v5.50.752 (「保存数据」= 归档目录 + MANIFEST + sha256, zmax_data 不进 git)。

本轮主题: 550C 端侧量产落地
  ① 三档运行位置 (550A 本地运行 / 550B 用于 VSCode / 550C 量产·部署 Intel 边缘机·全模型·远程端侧实时)
  ② 550B 选定后 文件→打开工程 自动起 VSCode 状态空间工程 (单线程 debug, 实测 3760MB→2578MB)
  ③ Intel 边缘机 (Nodka PTL X7 358H, NPU+Arc B390) 上真跑 L2 检测: NPU 2.46ms/帧, 端侧服务端到端 10.8ms
  ④ 修三条长期假红判据 + 修真 bug (drift_txt 算完没人用)
"""
import hashlib
import io
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
VER = "5.50.752"
DST = os.path.join(REPO, "zmax_data", "release_%s_%s" % (VER, time.strftime("%Y%m%d")))

CODE = [
    # ①② 配置中心 / 产品档 / 判据
    "tools/gui/veh6_config_page.py", "tools/verify_product_card_ui.py", "tools/verify_product_ui.py",
    "tools/verify_config_center_seven_stars.py", "tools/verify_config_page_product_sync.py",
    "tools/verify_ar_pts_card.py", "tools/verify_shortcuts.py",
    "tools/verify_console_title_product.py", "tools/check_debug_cfg.py",
    # ② VSCode 自动起
    "tools/gui/vscode_launch.py", "tools/gui/studio.py", "tools/gui/simulink_module.py",
    "tools/verify_vscode_autostart.py", ".vscode/launch.json", ".vscode/settings.json",
    # ③ 550C 端侧
    "tools/edge/edge_yolo_bench.py", "tools/edge/edge_yolo_infer.py",
    "tools/edge/edge_yolo_ref.py", "tools/edge/edge_service.py",
    # 版本/文档
    "tools/bump_version.py", "VERSION.md",
]
DATA = [
    # config/ 是软链 (→ data/database/zmax/sources/config), 必须显式拷
    "config/platform/zmax_product.json",
    "config/platform/zmax_data_governance.json",
    "config/robot/zmax_robot_spec.json",
    "zmax_data/models/../data/database/zmax/config_meta.json",
]
UNITS = [
    "/etc/systemd/system/zmax-dashboard.service",
    "/etc/systemd/system/zmax-tunnel-proxy.service",
    "/etc/systemd/system/zmax-ecs-station.service",
    "/etc/systemd/system/zmax-ecs-ov.service",
    "/etc/systemd/system/zmax-ecs-dash.service",
    "/etc/systemd/system/zmax-ecs-orin.service",
    "/etc/systemd/system/zmax-lan-nat.service",
    "/usr/local/sbin/zmax-lan-nat.sh",
    "/home/ubuntu/.config/systemd/user/zmax-studio.service",
    # 2026-10-21: frp 0.61 二进制目录已删 (服务一直 disabled+inactive, 33M 白占);
    # 配方 (frpc.toml/frps.toml/unit) 留档在 zmax_data/host_backup/frp/, 归档从这里取
    "/home/ubuntu/zmax/zmax_data/host_backup/frp/frpc.toml",
    "/home/ubuntu/zmax/zmax_data/host_backup/frp/zmax-frpc.service",
]

MANIFEST = """# Z-MAX v{ver} 归档

## 主题
550C 端侧量产落地: 三档运行位置写进真源 + 550B 打开工程自动起 VSCode(单线程·省资源) +
L2 检测权重在 Intel 边缘机 NPU 上真跑 (2.46ms/帧) + 端侧推理服务 (端到端 10.8ms=93FPS)。

## 根因 (为什么改)
- 产品档原来只有"能力集", 没有"跑在哪台机器" ⇒ 550C 说是量产却没人知道它该部署到 Intel。
- 端侧没有部署链: 权重是 .pt, 边缘机没有 torch; 没有 IR、没有服务、没有 ms/帧 的数。
- 550B 每次打开工程都要人手工开 VSCode, 且每次启动吃 3.76GB 内存、306 线程, 机器明显变慢。

## 改动清单
### ① 三档运行位置 (真源 + 界面 + 判据)
- `config/platform/zmax_product.json`: `products.<id>.runtime` (location/label/host/host_ip/models/realtime);
  550A=本地运行@192.168.23.50 / 550B=VSCode 标定@192.168.23.50 / 550C=Intel 端侧@192.168.23.70 全模型。
- 配置中心「运行位置」行 + 卡片底行 = 系统总版本号 · 运行位置 (值全部真源回读)。
- 判据 `verify_product_card_ui.py` 14/14 (新增 ⑥d: 三档位置必须等于真源三处)。

### ② 550B 自动起 VSCode (省资源 / 单线程 debug)
- `tools/gui/vscode_launch.py`: 只 550B 触发; `--reuse-window --disable-gpu`; 禁 pylance/containers/remote/python-envs;
  `OMP/MKL/OPENBLAS/NumExpr/VECLIB/TORCH=1` + `MALLOC_ARENA_MAX=2` (单线程口径唯一真源);
  `systemd-run --user --scope` 隔离; `--goto tools/gui/simulink_module.py:1` (不停在 Welcome)。
- `studio.py` 两条打开路径 (打开总工程 / 加载工程文件) 末尾各接一次; 关闭非 550B 时如实报"未自动起"。
- 判据 `verify_vscode_autostart.py` 24/24 (含注入替身真跑调用链, 不真起进程)。

### ③ 550C 端侧 (Intel 边缘机)
- ONNX(640, opset12) → IR fp16 → NPU/GPU/CPU 三档 bench; 端侧服务 `edge_service.py` (`/health` `/detect`)。
- 与 torch 同口径核对: 类别一致、框数一致、IoU 0.9837~0.9855、conf 差 0.015。
- 坑记录: `INFERENCE_NUM_THREADS` 只对 CPU 合法; 8400 行 Python 后处理吃 35ms 必须向量化。

### ④ 判据与真 bug
- 修 `check_debug_cfg` / `verify_console_title_product` (把 JSONC 当 JSON 读, 长期假红)。
- 修 `verify_shortcuts` (chk 只有 2 参却传 3 参 ⇒ TypeError 被 Qt 退出盖成 "Aborted")。
- 修真 bug: `drift_txt` 算完没人用 ⇒ 漂移对照并入打开完成报告。

## 目录
- `tools/` `gui/` — 本轮改动过的代码 (只拷改过的)
- `.vscode/` — launch.json (550B 单线程配置) + settings.json (省资源项)
- `data/` — 真源快照 (产品档运行位置 / 数据治理 / 机器人规格 / config_meta)
- `units/` — 本轮落成的 systemd 单元与 frpc 配置 (重建环境靠它)
- `evidence/` — 实测数字
- `docs/` — VERSION.md
- `sha256sums.txt` — 全量校验
"""

EVIDENCE = """# v5.50.752 实测数字 (全部来自本机/真机运行, 不是估算)

## ① Intel 边缘机 (Nodka PTL-Demo, Core Ultra X7 358H, 30GB, NPU + Arc B390)
模型: 现役 yolo_peg_live (yolov8n, 3.01M 参数, 640x640, 类别 peg/OPT_Gold), IR fp16 (284KB xml + 5920KB bin)

| 设备 | 单帧中位 | p95 | 并发4 ms/帧 | 编译 |
|---|---|---|---|---|
| NPU | 2.46 ms (407 FPS) | 3.17 ms | 1.38 ms (727 FPS) | 1288 ms |
| GPU Arc B390 | 1.50 ms (668 FPS) | 2.22 ms | 1.12 ms (894 FPS) | 1775 ms |
| CPU 8线程 | 56.27 ms (17.8 FPS) | 67.22 ms | 56.61 ms | 272 ms |

端侧服务 (JPEG 解码 + letterbox + NPU + NMS, 远程 HTTP 调用): 20 次中位 **10.80 ms/帧 = 93 FPS**

正确性 (3 张真图, 与 torch 同口径):
- 20260917_124517_611.jpg torch 0.8134 / NPU 0.8291 IoU 0.9837
- 20260917_124803_915.jpg torch 0.8040 / NPU 0.8193 IoU 0.9855
- 20260917_124808_267.jpg torch 0.8040 / NPU 0.8193 IoU 0.9855
(类别一致, 框数一致, conf 差 <= 0.0157)

## ② VSCode (550B 自动起)
- 放开全部扩展: 15 进程 / 3760 MB / 306 线程
- 关 pylance+containers+remote+python-envs + --disable-gpu: 14 进程 / 2578~2813 MB / 282 线程 (省 ~1.2 GB)
- 落地位置: 打开后标题 = `simulink_module.py - Visual Studio Code` (不停在 Welcome)

## ③ 三档运行位置
- 550A 本地运行 @192.168.23.50 / 550B VSCode 标定 @192.168.23.50 / 550C Intel 端侧 @192.168.23.70 (全部模型, 远程端侧实时)

## ④ 判据
- verify_product_card_ui 14/14 · verify_product_ui 47/47 · verify_config_center_seven_stars 21/21
- verify_config_page_product_sync 8/8 · verify_ar_pts_card 19/19 · verify_vscode_autostart 24/24
- check_debug_cfg PASS · verify_console_title_product 7/7 · verify_shortcuts 15/15
"""


def sha256sum(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main():
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    for d in ("tools", "gui", "units", "data", "evidence", "docs", "vscode"):
        os.makedirs(os.path.join(DST, d), exist_ok=True)
    os.makedirs(os.path.join(DST, "tools", "edge"), exist_ok=True)
    n = 0
    for rel in CODE:
        src = os.path.join(REPO, rel)
        if not os.path.isfile(src):
            print("  跳过(不存在): %s" % rel)
            continue
        if rel.startswith("tools/edge/"):
            dst = os.path.join(DST, "tools", "edge", os.path.basename(rel))
        elif rel.startswith("tools/gui/"):
            dst = os.path.join(DST, "gui", os.path.basename(rel))
        elif rel.startswith(".vscode/"):
            dst = os.path.join(DST, "vscode", os.path.basename(rel))
        elif rel.startswith("tools/"):
            dst = os.path.join(DST, "tools", os.path.basename(rel))
        else:
            dst = os.path.join(DST, "docs", os.path.basename(rel))
        shutil.copy2(src, dst)
        n += 1
    for rel in DATA:
        src = os.path.join(REPO, rel)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(DST, "data", os.path.basename(rel)))
            n += 1
    for u in UNITS:
        if os.path.isfile(u):
            shutil.copy2(u, os.path.join(DST, "units", os.path.basename(u)))
            n += 1
    with io.open(os.path.join(DST, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write(MANIFEST.format(ver=VER))
    with io.open(os.path.join(DST, "evidence", "measured_%s.md" % time.strftime("%Y%m%d")), "w", encoding="utf-8") as f:
        f.write(EVIDENCE)
    # sha256
    lines = []
    for root, _dirs, files in os.walk(DST):
        for fn in sorted(files):
            if fn == "sha256sums.txt":
                continue
            p = os.path.join(root, fn)
            lines.append("%s  %s" % (sha256sum(p), os.path.relpath(p, DST)))
    with io.open(os.path.join(DST, "sha256sums.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(lines)) + "\n")
    total = sum(os.path.getsize(os.path.join(r, fn)) for r, _d, fs in os.walk(DST) for fn in fs)
    print("归档: %s" % DST)
    print("拷贝 %d 个文件 + MANIFEST/evidence/sha256 ⇒ 共 %d 个文件, %.1f KB"
          % (n, len(lines) + 1, total / 1024.0))


if __name__ == "__main__":
    main()
