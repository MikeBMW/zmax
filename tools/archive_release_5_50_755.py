#!/usr/bin/env python3
"""归档 v5.50.755 (「保存数据」= 归档目录 + MANIFEST + sha256, zmax_data 不进 git)。

本轮主题: 对称性流形引擎 —— 预测=沿对称群轨道做等距离推演, 并接入 Intel 550C 自主进化
  ① 新模块 orbit_predict.py: 轨道=大圆, 等距步=恒定弧长; 破缺四判据 (drift/accel/bend/phi)
  ② 引擎 step() 每拍产出 rec["orbit"]; 时延补偿用 p̂ 解码动作 (ZMAX_ORBIT_LOOKAHEAD)
  ③ 常驻回路平铺 orbit_* 字段; 编排门控 (事件驱动) 实测不省钱 ⇒ 默认关
  ④ 判据脚本 verify_orbit_prediction.py: 16 条 (数学/破缺/真episode/引擎闭环/三接点)
  ⑤ Intel 550C: 部署 + 15/15 判据 + 自主进化接入 (一维等改进量推演 advisor + v6 热替换)
"""
import hashlib
import io
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
VER = "5.50.755"
DST = os.path.join(REPO, "zmax_data", "release_%s_%s" % (VER, time.strftime("%Y%m%d")))

CODE = [
    "src/lerobot/manifold/orbit_predict.py",    # ① 对称轨道预测器 (新)
    "src/lerobot/manifold/manifold_engine.py",  # ② 每拍 orbit + 时延补偿解码
    "tools/ss_engine_loop.py",                  # ③ 常驻回路平铺 orbit_* / 编排门控
    "tools/verify_orbit_prediction.py",         # ④ 16 条判据
    "tools/orbit_evolve_advisor.py",            # ⑤ 进化方向裁定 (一维等改进量)
    "tools/orbit_evolve_watch.py",              # ⑤ Intel 旁路判读
    "tools/edge/apply_v6_intel.sh",             # ⑤ Intel cooldown 热替换
    "tools/gui/studio.py",                      # 版本号 (4 处显示)
    "tools/gui/update_checker.py",
    "tools/gui/version_sync.py",
    "src/lerobot/ops/docs_sync.py",
    "tools/ci/integrity_check.py",
    "tools/bump_version.py",
    "tools/archive_release_5_50_755.py",
    "VERSION.md",
]
DATA = [
    "config/platform/zmax_product.json",
    "defaults/config/platform/zmax_product.json",
    "data/database/zmax/config_meta.json",
]
UNITS = [
    "/etc/systemd/system/zmax-ss-engine-loop.service",
    "/etc/systemd/system/zmax-ss-engine-loop.service.d/orbit.conf",
    "/etc/systemd/system/zmax-x11vnc.service",
    "/etc/systemd/system/zmax-vnc-tunnel.service",
]

MANIFEST = """# Z-MAX v{ver} 归档

## 主题
**对称性流形引擎**：把"预测 = 沿对称群轨道做等距离推演"落成引擎里可跑、可判、可拒绝的机制，
并接进 Intel 550C 的自主进化（用等改进量推演决定"继续这条路"还是"换方向"）。

## 根因（为什么改）
- 原引擎只做梯度流 + 势场，没有"这条方向物理上还成不成立"的判据：外推全靠模型，破了也不知道。
- 对称性给出的是**等价轨道**：Φ 沿轨道不变 ⇒ 沿轨道等距推演精确；一旦破缺（速度/方向/残差/势变）
  ⇒ 物理已经不再给答案，必须停推、交给势场/上层。这就是"预测的边界"。

## 改动清单
### ① 轨道预测器 `orbit_predict.py`
- `U_i=log_p(p_{i+1})`、`V_host=PT(U_{i})`、`p̂=exp(V_host)` 逐步推进（等弧长）；
- 破缺四判据 `drift/accel/bend/phi_drift`，任一超阈 ⇒ `valid=False` 只报原因；`n<2` 不猜；静止标 `static`；
- 阈值实测选点（真 episode 扫描）：drift 1.0 / accel 0.6 / bend 0.5；`STATIC_EPS=1e-6`（遥测抖动地板 4e-7）。

### ② 引擎接入 `manifold_engine.py`
- `step()` 每拍 `observe(p, Φ)` → `rec["orbit"]`；`ZMAX_ORBIT_PREDICT=0` 整层关；
- 时延补偿 `ZMAX_ORBIT_LOOKAHEAD=k`：轨道成立时用 `p̂_k` 解码动作（不改 p）；关掉逐位相同。

### ③ 常驻回路 `ss_engine_loop.py`
- live/tap 平铺 `orbit_valid/orbit_speed_rad/orbit_err_rad/orbit_break/orbit_pred_1/lookahead`；
- 编排门控 `ZMAX_PIPE_SYMMETRY`（破缺触发重规划）：**实测判负**，默认关。

### ④ 判据 `verify_orbit_prediction.py`（16 条）
- A 数学 4 · B 破缺 3 · C 真 episode 3 · D 引擎闭环 2 · E 三接点 4。

### ⑤ Intel 550C 自主进化
- 部署 `manifold/{sphere,orbit_predict,manifold_engine}.py` + 判据脚本 + 权重/轨迹；
- `orbit_evolve_advisor.py`：一维退化（时间平移对称 ⇒ 等改进量）；真台账 23 代判 `escalate`；
- `zmax_evolve_intel_v6.py`：每代开头调 advisor，escalate 且 streak<3 ⇒ 强制大变异+加算力；
- `apply_v6_intel.sh`：等 `phase=cooldown` 再替换重启，不打断在跑的代。

## 目录
- `src/` `tools/` `gui/` — 本轮改动过的代码（只拷改过的）
- `data/` — 真源快照（产品档位 / 安装默认 / config_meta）
- `units/` — 流形引擎常驻 unit + orbit drop-in + 远程桌面两 unit
- `evidence/` — 实测数字
- `docs/` — VERSION.md
- `sha256sums.txt` — 全量校验
"""

EVIDENCE = """# v5.50.755 实测数字（全部来自本机/Intel 真跑）

## ① 数学（理想群轨道，p∈S³ 大圆）
| 项 | 实测 | 说明 |
|---|---|---|
| 等距性 CV | 2.5e-14 | 步长 0.0629 rad 恒定 |
| 一步外推误差 | 2.0e-8 rad（相对步长 3.2e-7） | = exp∘log 数值地板（实测 2.1e-8），公式本身精确 |
| 平行搬移保内积 | 1.1e-14 相对误差 | 往返 300 组 |

## ② 破缺（判据必须抓住）
- 速度翻倍 → **同拍**判无效（第 8 拍，`symmetry_broken(speed_step_change)`）
- 只扭方向 → 第 3 拍起无效（稳态残差/步长 0.59）
- 静止 → `static=True` 且 valid（不把"保持"冒充预测成功）

## ③ 真 episode（400 帧真机 obs43 → 引擎 project，步长 median 1.1e-3 rad）
- 一步误差：轨道 1.159e-3 · 保持 2.113e-3 · 弦线 1.159e-3（n=398）
- 轨道 vs 保持：逐帧胜率 82.9%，平均改进 **+45.1%**
- 门控：valid 拍 5.8e-4 vs invalid 拍 2.6e-3（4.4x），覆盖 71.1%

## ④ 引擎闭环（真 episode 起点跑 240 拍，Φ 0.0266→0）
- 多视界误差：k=1 5.0e-5 · k=2 1.5e-4 · k=5 7.0e-4 · k=10 2.4e-3 rad
- 末拍 speed 5e-8 ⇒ static

## ⑤ 三个"指导运行"接点
| 接点 | 实测 | 结论 |
|---|---|---|
| 时延补偿（p̂ 解码） | 动作误差 0.002129→0.000759（**+64.4%**, n=283） | ✅ 进常驻 lookahead=1 |
| 编排门控（破缺才重规划） | 节拍5 省 3%；节拍20 多跑 190%（破缺率 29%） | ❌ 默认关 |
| L4 影子 | \\|Δz\\| valid/break = 0.36（live 3024 拍） | 🟡 未改行为 |
| 直接改动作（向轨道增量靠拢） | jerk 0.26e-3→0.34/0.43/0.70e-3，Φ 无改善 | ❌ 判负默认关 |

## ⑥ 常驻 live（700 拍真实流）
- 轨道 vs 保持（误差中位数）：2.72e-4 vs 1.275e-3 ⇒ **+78.7%**
- valid 拍（477）：1.13e-4 vs 1.33e-3 ⇒ **+91.5%**；invalid 拍仅 +9.7%（10.0x 分离）

## ⑦ 零回归
- 同一 60 拍序列 `ZMAX_ORBIT_PREDICT=1/0`：动作 max|Δ|=0、p max|Δ|=0、`array_equal=True`
- 引擎 `--selftest` 全部通过

## ⑧ Intel 550C
- 判据在 `/home/intel/train_venv/bin/python` 上真跑：selftest 3/3、verify **15/15**（E4 需 live tap 跳过）
- 进化台账（23 代，best 0.7381）：advisor 判 `escalate` · `推演破缺(step_length_dispersion)` ·
  pred_next 0.7113 · drift 1.95 · accel 5.29
- 版本五处一致 = 5.50.755（studio 4 处显示 / update_checker / version_sync / docs_sync 两键 / integrity_check）
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
    for d in ("tools", "gui", "units", "data", "evidence", "docs", "src"):
        os.makedirs(os.path.join(DST, d), exist_ok=True)
    os.makedirs(os.path.join(DST, "tools", "edge"), exist_ok=True)
    os.makedirs(os.path.join(DST, "src", "manifold"), exist_ok=True)
    n = 0
    for rel in CODE:
        src = os.path.join(REPO, rel)
        if not os.path.isfile(src):
            print("  跳过(不存在): %s" % rel)
            continue
        if rel.startswith("src/lerobot/manifold/"):
            dst = os.path.join(DST, "src", "manifold", os.path.basename(rel))
        elif rel.startswith("tools/edge/"):
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
        f.write(MANIFEST.replace("{ver}", VER))
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
