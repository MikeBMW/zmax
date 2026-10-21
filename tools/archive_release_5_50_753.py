#!/usr/bin/env python3
"""归档 v5.50.753 (「保存数据」= 归档目录 + MANIFEST + sha256, zmax_data 不进 git)。

本轮主题: 底部硬件状态带放大 + 三处"看着像坏了"的假象排掉
  ① 状态带整体放大 1.42x (1080x40 → 1533x56, 字 10/11px → 14/15.6px), 单一 SCALE 不改版式比例
  ② 缩放后 fillRect 传 float 走 int 重载抛错 ⇒ 整帧静默不画 (透白底) —— 改 QRectF/QPointF
  ③ availableGeometry() 自身越界把状态带顶到屏外 ⇒ 按 屏幕物理几何 ∩ 可用区 夹回屏内
  ④ NPU/GPU 槽画"—" 根因 = orin 隧道单请求 2.9~3.6s 而取数只等 1.5s ⇒ 改后台线程刷 + 缓存
  ⑤ 550 ABC 三处真源同步 (本机 / intel: product.json · zmax_profile.py · edge_service.py)
"""
import hashlib
import io
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
VER = "5.50.753"
DST = os.path.join(REPO, "zmax_data", "release_%s_%s" % (VER, time.strftime("%Y%m%d")))

# 只拷本轮真改过的代码 (git diff --name-only v5.50.752..HEAD)
CODE = [
    "tools/gui/status_panel.py",            # ① 放大 / ③ float→QRectF
    "tools/gui/studio.py",                  # ③ 窗口夹回屏内 + geo 取证 / 状态栏 _QuietStatusBar
    "tools/gui/simulink_module.py",          # 画布工具栏左对齐 + 日志区可拖高
    "tools/gui/model_engine_window.py",      # 模型引擎 11 列 (运行位置/权重/转换工具/推理或训练)
    "tools/gui/hw_widgets.py",
    "src/lerobot/engineering/status_hub.py", # ④ Intel 端侧后台刷 + 缓存
    "tools/model_runtime_map.py",
    "tools/zmax_compute_mode.py",
    "tools/zmax_profile.py",                 # ⑤ 与 intel 侧逐字节一致
    "tools/verify_product_dev_profiles.py",
    "tools/edge/edge_service.py",             # ⑤ 从 intel 拉回 (/models sha16/bin_mb/mtime)
    "tools/edge/edge_pipeline_guard.py",
    "tools/edge/bench_edge_models.py",
    "tools/edge/bench_npu_streams.py",
    "tools/edge/export_intact.py",
    "tools/edge/ov_convert.py",
    "tools/edge/ov_export_torch.py",
    "tools/edge/export_sam3_enc.py",
    "tools/edge/sam3_onnx_to_ir.py",
    "tools/tcp_ar_server.py",                 # AR 位姿改读 Orin 珞石桥 (latest.json 冻在 3.5h 前)
    "tools/archive_release_5_50_752.py",
    "tools/bump_version.py",
    "VERSION.md",
]
DATA = [
    # config/ 是软链 (→ data/database/zmax/sources/config), 必须显式拷
    "config/platform/zmax_product.json",
    "defaults/config/platform/zmax_product.json",
    "data/database/zmax/config_meta.json",
]
UNITS = [
    "tools/edge/zmax-edge-pipeline.service",                    # intel 并行调度 (NPU 2 流 / GPU 1 流)
    "/home/ubuntu/.config/systemd/user/zmax-studio.service",
    "/home/ubuntu/zmax/zmax_data/host_backup/frp/frpc.toml",
]

MANIFEST = """# Z-MAX v{ver} 归档

## 主题
底部硬件状态带放大 1.42 倍 (老倪: 「最下面的硬件指示的字体太小了」), 并排掉三处"看着像坏了"的假象:
状态带整帧静默不画 / 状态带被顶到屏外 / 槽位画"—"。同时把 550 ABC 三处真源与本机·intel 两端对齐。

## 根因 (为什么改)
- 状态带 paint 全是写死像素 (chip 88、槽宽、灯半径), 逐处改字号必然错位 ⇒ 引入单一 SCALE + `painter.scale`,
  逻辑坐标与版式比例都不动, 字体同比放大到 14/15.6px。
- 缩放后 `w/h` 变 float, `QPainter.fillRect/drawLine` 的 int 重载抛错、异常被 paintEvent 吞掉 ⇒ **整帧什么都不画**,
  透出父控件白底 —— 截图看着像"状态带没了", selftest 却可能仍绿 (必须数像素)。
- 这套 GNOME/Mutter 上 `availableGeometry()` 自己越界 (3068x1862@132,212, 底边 2074 > 主屏 2000),
  "按可用区夹回屏内"等于夹到屏外, 最底下那条带整条看不见。
- 状态带 NPU/GPU 读 `/status/all.edge.pipeline.devices.*.duty_pct`; 经 orin 隧道单请求实测 2.9~3.6s,
  而 `collect_edge` 只等 1.5s ⇒ 必然 TimeoutError ⇒ online=False ⇒ 界面只能画横杠 (intel 上其实 96% 满载)。

## 改动清单
### ① 放大 (单一系数)
- `status_panel.py`: `W,H=1080,40` 为逻辑画布, 新增 `SCALE=1.42` ⇒ 物理 1533x56; `_paint` 先 `p.scale(SCALE,SCALE)`,
  `w,h = width()/SCALE, height()/SCALE`。字号 10/11px → 14.2/15.6px, 版式同比 ⇒ 不重叠不截断。
- selftest 判据跟着改成相对阈值 (`_Hp*0.35 ~ _Hp*0.98`), 不再写死 40px。

### ② 缩放后整帧不画 (float 走 int 重载)
- `fillRect(0,0,w,h)` → `fillRect(QRectF(...))`; `drawLine(0,0,w,0)` → `QPointF` 两端。
- 离屏 grab 判据: 深色带 mean ≈ [27,33,40]; 出现 [239,239,239] 就是"没画"。

### ③ 窗口夹回屏内
- `studio.py`: 夹紧用 **屏幕物理几何 ∩ availableGeometry**, 底部留 48px; 起窗后 4s 打印
  `[status_panel] geo=1533x56@0,1750 vis=True | win=3068x1936@132,64 | in_screen=True` 作取证。

### ④ Intel 端侧取数不再超时
- `status_hub.py`: `_edge_fetch()` + `_EDGE_CACHE`, 后台线程刷 (timeout 8s / ttl 8s), 请求路径永不阻塞;
  返回带 `cache_age_s` / `stale`, 读不到就继续给上一份并标年龄, 不冒充在线。

### ⑤ 550 ABC 同步
- 本机与 intel 两端 `zmax_product.json` / `zmax_profile.py` / `edge_service.py` 三方 sha256 逐字节一致;
  `verify_product_dev_profiles.py` 全过 (550A=4060 / 550B=4060 / 550C=intel, 读取口与四处接线一致)。

## 目录
- `gui/` `tools/` `tools/edge/` — 本轮改动过的代码 (只拷改过的)
- `data/` — 真源快照 (三档硬件绑定 / 安装默认 / config_meta)
- `units/` — intel 并行调度 unit + 本机 GUI unit + frp 配方
- `evidence/` — 实测数字
- `docs/` — VERSION.md
- `sha256sums.txt` — 全量校验
"""

EVIDENCE = """# v5.50.753 实测数字 (全部来自本机/真机运行, 不是估算)

## ① 状态带尺寸与字高
| 项 | 改前 | 改后 |
|---|---|---|
| 面板 | 1080 x 40 | 1533 x 56 |
| 字号 (chip/标签/数值) | 10 / 11 px | 14.2 / 15.6 px |
| 屏上墨迹行高 | 约 27 px | 39 px |
| 屏上实际位置 | 被顶到屏外 (底边 2074 > 2000) | y=1945..1999, 完整在屏内 |

OCR (真实窗口截图 reports/status_strip_bigfont_evidence.png):
`550C·Intel | NPU 97% | GPU 96% | CPU 8% | 内存 7% | 盘 926G | L2 YOLO annot | L3 SmolVLA 004000 | L4 INTACT current | 3DGS x5`

- `status_panel.py --selftest`: PASS (含 6 例畸形载荷 / 灰灯 / 像素带判据)
- 离屏 grab: 尺寸 1533x56, mean [27.1, 33.3, 40.3], 暗像素 95% (改前 float 崩溃时 mean [239,239,239])

## ② 取数链路
- 修复前 `/status/all.edge`: `{online:false, tried:["127.0.0.1:18800(TimeoutError)", "192.168.23.70:8800(URLError)"]}`
- 隧道单请求实测: 3.61s / 2.88s / 3.44s (curl 三次)
- 修复后连续 6 次采样: `online=True, cache_age 0.2~7.3s, NPU 96.6%, GPU 96.3%`

## ③ Intel 端侧并行 (在跑)
- NPU 2 流: yolo_peg_live + intact_enc + intact_pred → 895.9 fps · duty 96.6% · avg 2.16 ms · busy_ratio 1.93
- GPU 1 流: intact_pred + intact_enc → 约 1201 fps · duty 96.3%
- 合计 2087~2107 fps, err=null, pkg 72°C, CPU 9~10%, 内存 7.2%, edge_service RSS 596MB
- 30fps 生产节拍折算: NPU 25.5% / GPU 15.1% (现在 96% 是静态图跑分模式, 真实产线余量 70%+)

## ④ 550 ABC 三处真源 (sha256 前 16 位)
| 文件 | 本机 | intel |
|---|---|---|
| config/platform/zmax_product.json | 5276456ed3142efc | 5276456ed3142efc |
| tools/zmax_profile.py | 6773fa4b110522c9 | 6773fa4b110522c9 |
| tools/edge/edge_service.py | 7888bfe3980d9897 | 7888bfe3980d9897 |

- `verify_product_dev_profiles.py`: 全过 (550A=4060 / 550B=4060 / 550C=intel; 不符判定与"550C 在本机不算缺口"均自检通过)
- 版本五处一致: studio.py(4 处显示) / update_checker.CURRENT_VERSION / version_sync.zmax_ver /
  docs_sync 两键 / integrity_check.EXPECTED_VERSION = 5.50.753
- 已知遗留: `tools/ci/integrity_check.py` 的 "stack addWidget 顺序" 一项长期假红 (页面改懒加载后
  AST 取不到 `self.stack.addWidget(<PageClass>)`, 实测 v5.50.752 也是 0 命中), 与版本号无关。
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
    for d in ("tools", "gui", "units", "data", "evidence", "docs"):
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
        else:
            print("  跳过(不存在): %s" % rel)
    for u in UNITS:
        if os.path.isfile(u):
            shutil.copy2(u, os.path.join(DST, "units", os.path.basename(u)))
            n += 1
        else:
            print("  跳过(不存在): %s" % u)
    with io.open(os.path.join(DST, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write(MANIFEST.format(ver=VER))
    with io.open(os.path.join(DST, "evidence", "measured_%s.md" % time.strftime("%Y%m%d")), "w", encoding="utf-8") as f:
        f.write(EVIDENCE)
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
