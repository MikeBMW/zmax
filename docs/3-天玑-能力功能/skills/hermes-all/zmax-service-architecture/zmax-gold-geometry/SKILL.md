---
name: zmax-gold-geometry
description: Measure gold-finger rects against QSFP constraints.
---

# 金手指几何测量与 QSFP 约束校验

现场要求（2026-11-27）：可见 19 个矩形、能算面积；把长宽规律/角度/长度变化记成**数据约束**，下次主动识别；
直线特征明显，状态空间 YOLO 或 OpenCV 要能上报边长与直角。

## 产物（三个）

| 文件 | 作用 |
|---|---|
| `config/calib/gold_geometry_constraint.json` | 约束本体：节距 0.6±0.05、宽 0.33±0.06、长 0.95~1.70、面积 0.30~0.60mm²、占空比 0.548、平行度 0.8°、直角 2°、节距离散 std≤0.02 |
| **`src/lerobot/policies/aoi/gold_geometry.py`** | **算法真身**（`probe(bgr)` 量图 / `probe_from_host()` 自己抓图再量）。由 `quality.inspect_aoi()` 调用，结果进 `gold_geometry` 字段 |
| `tools/gold_geometry_probe.py` | 同一套算法的命令行克隆，用于离线验图。**改算法只改 policies/ 那份**，工具层那份跟着抄，不要反过来 |
| 8793 `/api/aoi/detect` | 返回 `defect_check.geometry`（n/节距/宽/高/面积/合规/违规项/可疑根） |

**分层不能错**：测量与判据是算法，必须在 `policies/aoi/`；节点 `nodes/impl/ss_aoi.py` 只做壳。
只放 `server/`/`tools/` 等于把它从状态空间工程里割出去——服务可用但节点拿不到，
用户会直接问「代码是在光学质量检查节点里吗」。

**路径要算对**：`policies/aoi/` 比 `tools/` 深两层，约束文件的 `ROOT` 要**往上四层**才是工程根。
从 tools/ 搬过来时忘了改，就是静默读不到约束（`load_constraint()` 回退到只认 19 根的下限），
所有 range 校验集体失效而**不报错**。搬完立即验证一次违规检测仍能触发。

**自己抓图的入口**：`probe_from_host(host, port)` 取 `/region?grab=1` 的 quad + `/picture?kind=origin&grab=1`，
再 `warpPerspective` 成条带。单次约 0.8s ⇒ 调用方（`inspect_aoi`）必须加 **60s TTL 缓存**
（`_GEO_CACHE = {"v": None, "t": 0.0}`），节点循环预算只有 100ms/拍，每拍都跑会拖死。
`/region` 回 `w=365` 这类旧缓存值时直接判无效返回（合理性闸 `800<=w<=3000`），绝不编造几何。

## 算法（两句话）

1. **等分先验 + 格内亮度重心**：直接找峰会因触点内部亮暗分界出双峰，实测节距 std 飙到 0.11mm；
   用“19 根等距”做骨架再取重心，std 降到 0.006mm。
2. **自标定 px/mm = 节距中位数 / 0.6mm**：不依赖相机内参，换镜头/换工作距离不失效。

## 实测基准（1341×206 条带，117.7 px/mm）

```
节距 0.6001 ± 0.0061 mm   （QSFP 标准 0.6，18/18 根合格）
宽   0.329  ± 0.005  mm
高   1.309  ± 0.174  mm   （范围大 ⇒ 长度用 range 不用 tol）
面积 0.4304 ± 0.058 mm²
占空比 0.548
```

## 两个必须知道的限制

1. **几何对曝光敏感**：亮区宽度随亮度变，同一工件不同曝光下宽能从 0.33 变 0.47mm。
   判定前先确认相机在 2000us/10dB 标准档；否则 `geometry_ok` 会假报违规。
2. **单帧节距离散会尖刺**：实测出现过 std=0.0435（阈值 0.02）的劣帧。生产上应**多帧中位数**（建议 5 帧）再判，不要单帧下结论。

## 缺陷与几何的交叉证据

氧化/划伤会让该根亮区缩小 ⇒ 面积或高度比同批中位数掉 15%（`defect_coupling`）就标为可疑。
与 YOLO 的 NG 互相校验：几何说“形状不对”、YOLO 说“表面脏”，两者都否定时才真判不合格。

## 验收

```bash
# 离线验图（工具层克隆，最快）
python tools/gold_geometry_probe.py <strip.jpg>
# 期望: 19 根, 节距 mean 0.60 std <0.02, 几何合规: 是

# 验算法层本体（不要只在 tools/ 里跑通就收工）
python -c "import sys;sys.path.insert(0,r'D:\\ZMAX\\src');from lerobot.policies.aoi.gold_geometry import probe_from_host;print(probe_from_host())"
```

第二条在裸 Python 下会因 `lerobot` 包连带 `huggingface_hub` 等重依赖而导入失败——
那是环境问题，不是算法问题。要在有完整环境的机器上验（用 `D:/ZMAX/Z-MAX_Console.exe` 当解释器，
或到 550C 上跑）。判据只看 `probe()` 的返回值，不看 import 是否顺。
