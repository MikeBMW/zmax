# -*- coding: utf-8 -*-
"""quality_check.py — 🔍 外观质量检测 (AOI): 真实图像处理缺陷检测 + 取像参数/画面健康度

本文件是画布节点「🔍 外观质量检测」(`ssaoi`) 的**唯一真源**:
  双击节点 = 看这里的源码, 单步执行 = 跑这里的 `AOIQualityChecker`。

三段职责 (都在 `AOIQualityChecker` 里, 一个类管完):
  ① 取像参数   —— 曝光/增益/Gamma 与它们的**正确下发顺序**(见 EXPERIENCE 第 5 条)
  ② 画面健康度 —— 一帧就能判"现在的取像参数对不对"(过曝/偏暗/缝隙被糊白/该补多少倍)
  ③ 缺陷判据   —— DET-AOI-01~04 图像处理检测(清晰度/划痕/污染/氧化/毛刺)

=============================================================================
EXPERIENCE — 2026-10-08 在产线金手指相机 (SN D265250070) 上实测得到的经验
=============================================================================
1) **这台相机的自动曝光/自动增益出厂就是开着的**。在此状态下, 对 ExposureTime / Gain 的任何
   写入都会被判"参数值非法"返回 `rv=100100010` —— 而调用方只打印一句"设置失败"就过去了
   ⇒ **文件里写的 10000us 从来没有生效过**(现场几个月没人发现)。
2) 相机于是自己拉**超长曝光**(实测约 94ms)在亮金属上硬扛 ⇒ 恒定过曝: 条带内 20%~32% 像素 ≥250。
3) 后果链(这才是"金手指根数忽多忽少"的真根因):
   过曝 → 金手指之间的**暗缝被糊白桥接**成一条宽亮段 → 宽度归整把"两片粘成一片"的位置判错
   → 判据图上根数在 19/21/22 之间反复。**根因不在认领逻辑, 在相机取像参数。**
4) 另一条独立 bug(同一次挖出): 判据渲染里 `gate = min(bg+25, 1.35*bg)` **覆盖了同名参数 dict**
   ⇒ 暗帧必抛 `AttributeError: 'float' object has no attribute 'get'`, 判据图整个报错。
   修法: 局部变量改名 `edge_gate`。⇒ 教训: **别用参数名当局部变量**。
5) **正确下发顺序(逐条实测 rv=0)**:
        ExposureAuto→"Off" → GainAuto→"Off" → ExposureTime → Gain → Gamma
   ⚠️ 绝不能靠"停采集→写→恢复采集"绕过: 实测 `StartGrabbing` 会**卡死不返回**, 整路相机死掉
      (最后只能 kill 进程重开)。工业相机运行期拒写是常态, 正确做法是开机时序里一次写对。
6) 定值依据(同场景扫档; p50=片的亮度, p10=缝的亮度, 对比度=p50-p10):
        20000us × 增益 8.0 → p50=206 p10=49  对比度 157  ← 选它(曝光仅自动那档的 1/5 ⇒ 更锐)
        30000us × 增益 8.0 → p50=149 p10=115 对比度  34
        60000us × 增益 4.0 → p50=150 p10=115 对比度  34  (与 30000×8 等价 ⇒ 曝光×增益线性可换)
       120000us × 增益 2.0 → p50=146 p10=113 对比度  33
   范围: 曝光 1~10000000us · 增益 1.33~16.38(写 1.0 会被拒!) · Gamma 0~3.999。
7) 现场客观事实: **光源偏暗** —— 10000us 下整幅均值只有 16(最亮区 94), 要 ~9.4 倍补偿才到正常;
   相机自动曝光一直在替它扛。⇒ 现场应确认光源; 程序侧用"**高增益 + 短曝光**"换锐度
   (曝光时间越短, 振动/运动造成的糊越少, 代价是噪声)。
8) 结论一句话: **"画面糊"和"根数不稳"是同一个病 —— 取像参数从未生效。**
   修好参数比调对焦、比动机器人有用得多(该机镜头为手动定焦, 软件里根本没有对焦节点)。
=============================================================================
"""
import numpy as np

try:
    import cv2
except ImportError:  # 无 cv2 环境 → check() 返回 error, 不静默假装
    cv2 = None

# 默认阈值 (工程标定起点; 产线实测后可调参, 画布传 thresholds 覆盖)
_DEF_TH = {
    "focus_min": 60.0,      # 拉普拉斯方差下限 (低于=对焦不良/端面破损)
    "scratch_max": 6,       # 长直线条数上限 (超过=划痕缺陷)
    "scratch_len_min": 40,  # 直线最短像素 (滤噪)
    "blob_max": 8,          # 污染斑点数上限
    "blob_area_min": 24,    # 斑点最小面积 px
    "gray_dev_max": 18.0,   # 灰度中值偏移上限 (氧化/镀层缺损)
    "edge_frac_max": 0.35,  # 边缘像素占比上限 (毛刺/变形)
}


class AOIQualityChecker:
    """AOI 外观质量检测器 —— 取像参数 + 画面健康度 + 缺陷判据, 一个类管完。

    参数(曝光/增益/Gamma)是**类常量**: 它们属于"这台相机该怎么取像"这条技能, 不属于某次调用。
    """

    # ─────────────────────────── ① 取像参数 (真机实测定值) ───────────────────────────
    CAMERA = {
        "sn": "D265250070",              # 金手指相机 (表面检测那路是 D265250099, 互不影响)
        "model": "OPT-LCRT1500 / CC1-GG50",
        "sdk": "奥普特 SciCamera (SciCam_class.py)",
        "nodes": ["ExposureTime", "Gain", "Gamma"],   # 只有这三个可调; **没有对焦节点**(手动定焦镜头)
        # ★ 定值: 2026-10-08 扫档实测选出 (见文件头 EXPERIENCE 第 6 条)
        "exposure_us": 20000.0,
        "gain_db": 8.0,
        "gamma": 1.0,
        # 实测范围 (越界会被相机拒: rv=100100010)
        "exposure_range": (1.0, 10000000.0),
        "gain_range": (1.33, 16.38),
        "gamma_range": (0.0, 3.999),
        # ★ 必须先关自动模式, 否则上面三个参数的写入**静默失败**(EXPERIENCE 第 1 条)
        "must_disable_auto_first": ["ExposureAuto", "GainAuto"],
        # 正确下发顺序 (逐条 rv=0 实测)
        "init_order": ["ExposureAuto=Off", "GainAuto=Off", "ExposureTime", "Gain", "Gamma"],
        "forbidden_workaround": "停采集→写→恢复采集 (实测 StartGrabbing 卡死, 整路相机死掉)",
    }

    # 扫档证据表 (曝光us, 增益, 片亮度p50, 缝亮度p10, 对比度) —— 留着, 下次谁质疑口径就能复算
    SWEEP_EVIDENCE = [
        (20000.0, 8.0, 206.0, 49.0, 157.0),
        (30000.0, 8.0, 149.0, 115.0, 34.0),
        (60000.0, 4.0, 150.0, 115.0, 34.0),
        (120000.0, 2.0, 146.0, 113.0, 33.0),
    ]

    # 画面健康度判据 (看一帧就能判取像参数对不对)
    FRAME_Q = {
        "blown_max": 0.08,      # 全图 ≥250 像素占比上限 (超=过曝, 暗缝会被糊白桥接)
        "band_p50_min": 150.0,  # 金手指带亮度中位下限 (低=偏暗, 判据会检不到键)
        "contrast_min": 80.0,   # 片亮度p50 - 缝亮度p10 下限 (低=缝被抬灰, 键边界糊掉)
        "target_band": 180.0,   # 期望的条带亮度 (用来算"还差几倍")
    }

    # ─────────────────── 产线 ↔ 调试 的旁路关系 (2026-10-08 老倪定的架构) ───────────────────
    #   产线程序 = 跑在**工控机**上的那份(改它必须走部署器: 哈希核对 + 失败自动回滚)
    #   调试程序 = 本仓库 `tools/aoi/` 的副本 + 本类(先在副本上改/试, 再下发)
    #   ⇒ 调参与判据的迭代都发生在调试侧, 产线侧只接受"验证过的整包"
    PRODUCTION = {
        "host": "192.168.23.23",
        "finger": {
            "port": 10082, "title": "金手指检测",
            "remote_file": "D:\\xspace\\ultralytics_AOI\\cam_finger_10082_work_v20.py",
            "repo_copy": "tools/aoi/cam_finger_10082_work_v24.py",
            "endpoints": {"region": "/region?grab=1", "capture_detect": "/capture_detect",
                          "picture": "/picture?kind=crop|natural|origin", "crop_info": "/crop_info",
                          "param": "/param", "last_result": "/last_result", "storage": "/storage"},
        },
        "surface": {
            "port": 10083, "title": "表面/端面检测",
            "remote_file": "D:\\xspace\\ultralytics_AOI\\cam_surface_10083_work_v20.py",
            "repo_copy": "tools/aoi/cam_surface_10083_work_v20.py",
            "endpoints": {"region": "/region?grab=1", "capture_detect": "/capture_detect",
                          "picture": "/picture?kind=crop|natural|origin", "crop_info": "/crop_info",
                          "last_result": "/last_result", "storage": "/storage"},
        },
        "sync_tool": "tools/aoi/production_sync.py",     # status/verify/diff/pull (旁路对齐)
        "deploy_tool": "tools/aoi_remote_deploy.py",     # --finger/--only, 哈希核对+失败回滚
        "manifest": "tools/aoi/PRODUCTION_MANIFEST.json",
        "runtime_tool": "tools/aoi_remote_run.py",       # 只在工控机上跑一次性 PowerShell
    }

    def __init__(self, thresholds=None):
        self.th = {**_DEF_TH, **(thresholds or {})}

    # ─────────────────────────── ② 取像参数下发 (技能逻辑) ───────────────────────────
    @classmethod
    def apply_camera(cls, cam, log=None):
        """把本类的取像参数下发到相机 —— **顺序不可换**。

        返回 {"auto_off": {node: rv}, "applied": {node: rv}, "ok": bool, "note": str}
        任何一步失败都如实回报(不再静默): 调用方必须打印 rv, 否则下次又会"以为设上了"。
        """
        say = log or (lambda *_a, **_k: None)
        out = {"auto_off": {}, "applied": {}, "readback": {}, "ok": True, "note": ""}
        # ① 先关自动曝光/自动增益 (不关 → 下面全白写)
        for node in cls.CAMERA["must_disable_auto_first"]:
            rv = None
            try:
                rv = cam.SciCam_SetEnumValueByString(node, "Off")
                if rv != 0:
                    rv2 = cam.SciCam_SetEnumValue(node, 0) if hasattr(cam, "SciCam_SetEnumValue") else None
                    say(f"⚠️ {node}->Off 字符串方式返回 {rv}, 枚举方式返回 {rv2}")
                    rv = rv2 if rv2 == 0 else rv
            except Exception as e:            # pragma: no cover (真机才走)
                say(f"⚠️ {node} 关自动异常: {e!r}")
            out["auto_off"][node] = rv
            if rv != 0:
                out["ok"] = False
        # ② 写曝光 / 增益 / Gamma (各自带范围校验, 越界就钳一下并说明)
        lo, hi = cls.CAMERA["exposure_range"]
        g_lo, g_hi = cls.CAMERA["gain_range"]
        want = {
            "ExposureTime": float(min(max(cls.CAMERA["exposure_us"], lo), hi)),
            "Gain": float(min(max(cls.CAMERA["gain_db"], g_lo), g_hi)),
            "Gamma": float(cls.CAMERA["gamma"]),
        }
        for node, val in want.items():
            try:
                rv = cam.SciCam_SetFloatValue(node, val)
            except Exception as e:            # pragma: no cover
                rv, say = -1, (lambda *a, **k: None) or say
                say(f"⚠️ {node}={val} 异常: {e!r}")
            out["applied"][node] = {"value": val, "rv": rv}
            if rv != 0:
                out["ok"] = False
                say(f"⚠️ {node}={val} 写入失败 rv={rv} (自动模式没关掉? 见 EXPERIENCE 第 1 条)")
            else:
                say(f"✅ {node}={val} 写入成功")
        if not out["ok"]:
            out["note"] = "有参数没写进去 ⇒ **绝不能**改成'停采集再写'(会把相机写死), 查自动模式/范围"
        return out

    # ─────────────────────────── ② 画面健康度 (一帧判参数) ───────────────────────────
    def assess_frame(self, frame):
        """一帧 → 取像质量体检 dict (不需要相机, 只看像素)。

        把"相机参数对不对"变成可判读的数字, 并给出**还差几倍补偿**:
          blown/black      全图过曝/全黑占比
          band_p50/p10     金手指带的片亮度中位 / 缝亮度(第10百分位)
          contrast         p50-p10 (越小=缝被抬灰=键边界糊)
          pads             带的列剖面里"片状亮段"(宽 20~130px) 的个数 (对照真理: 19 根)
          need_x           要把带亮度拉到 target_band 还差几倍 (1.0=刚好)
          verdict          ok / too_dark / overexposed / gaps_washed
        """
        res = {"ok": False, "why": "", "blown": 0.0, "black": 0.0, "band": None,
               "band_p50": 0.0, "band_p10": 0.0, "contrast": 0.0, "pads": 0, "need_x": 1.0,
               "verdict": "unknown"}
        if cv2 is None:
            res["why"] = "cv2 不可用"
            return res
        img = np.asarray(frame)
        if img.dtype != np.uint8:
            img = np.clip(img * 255.0, 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
        h, w = gray.shape
        res["blown"] = float((gray >= 250).mean())
        res["black"] = float((gray <= 8).mean())
        # 金手指带 = **行均值的连续亮段**(从最亮行向两侧扩, 直到行均值掉下阈值)。
        # ⚠️ 别用"最亮行 ±75": 那会把带外的背景算进来, 带均值被稀释(实测同一帧 137 vs 235 的差别),
        #    判读就会把本来健康的帧误判成 too_dark。
        rs = gray.mean(axis=1)
        yc = int(np.argmax(rs))
        thr_row = max(float(rs[yc]) * 0.55, float(np.percentile(rs, 80)))
        y0, y1 = yc, yc
        while y0 > 0 and rs[y0 - 1] >= thr_row:
            y0 -= 1
        while y1 < h - 1 and rs[y1 + 1] >= thr_row:
            y1 += 1
        band = gray[y0:y1 + 1]
        prof = band.mean(axis=0)
        p10 = float(np.percentile(prof, 10))
        p50 = float(np.percentile(prof, 50))
        res.update({"band": [int(y0), int(y1)], "band_p50": round(p50, 1),
                    "band_p10": round(p10, 1), "contrast": round(p50 - p10, 1)})
        # 片状亮段计数 (只做粗筛; 真根数由判据渲染的 lattice 归整决定)
        thr = max(100.0, p50)
        mask = prof >= thr
        runs, s = [], None
        for i, m in enumerate(mask):
            if m and s is None:
                s = i
            elif not m and s is not None:
                runs.append(i - s)
                s = None
        if s is not None:
            runs.append(len(mask) - s)
        res["pads"] = int(sum(1 for wd in runs if 20 <= wd <= 130))
        target = float(self.FRAME_Q["target_band"])
        res["need_x"] = round(target / max(1.0, float(band.mean())), 2)
        # ── 判读 ──
        q = self.FRAME_Q
        if res["blown"] > q["blown_max"]:
            res["verdict"] = "overexposed"
            res["why"] = (f"过曝 {res['blown']:.3f} > {q['blown_max']} ⇒ 暗缝会被糊白桥接, "
                          f"金手指根数会不稳 (2026-10-08 实测根因)")
        elif p50 < q["band_p50_min"]:
            res["verdict"] = "too_dark"
            res["why"] = (f"带亮度 {p50:.0f} < {q['band_p50_min']:.0f} ⇒ 偏暗, 判据会检不到键; "
                          f"约需再补 {res['need_x']}× (先查光源, 再用增益补)")
        elif (p50 - p10) < q["contrast_min"]:
            res["verdict"] = "gaps_washed"
            res["why"] = f"缝亮度 {p10:.0f} 被抬灰(对比度 {p50 - p10:.0f}) ⇒ 片/缝边界糊, 降曝光或增益"
        else:
            res["verdict"] = "ok"
            res["ok"] = True
            res["why"] = f"取像健康: 片 {p50:.0f} / 缝 {p10:.0f} / 过曝 {res['blown']:.3f}"
        return res

    # ─────────────────────────── ③ 缺陷判据 (原有能力, 保持口径不变) ───────────────────────────
    def check(self, frame):
        """帧 → 检测结果 dict

        {
          "pass": bool,                     # 全目标通过?
          "focus": float, "scratch": int, "blob": int,
          "gray_dev": float, "edge_frac": float,
          "items": [{target_id, target, defect, value, threshold, pass, conf}],
          "quality": {...}                  # 取像健康度 (assess_frame 的结果, 供画布显性提示)
        }
        """
        if cv2 is None:
            return {"pass": False, "error": "cv2 不可用 (gui-venv311 缺 opencv)", "items": [],
                    "focus": 0.0, "scratch": 0, "blob": 0, "gray_dev": 0.0, "edge_frac": 0.0,
                    "quality": {"verdict": "unknown", "why": "cv2 不可用"}}
        img = np.asarray(frame)
        if img.dtype != np.uint8:
            img = np.clip(img * 255.0, 0, 255).astype(np.uint8)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img

        # ── ① 清晰度 (对焦/端面破损混淆) ──
        focus = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # ── ② 划痕: Canny + 概率霍夫直线 ──
        edges = cv2.Canny(gray, 50, 150)
        scratches = 0
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40,
                                minLineLength=self.th["scratch_len_min"], maxLineGap=6)
        if lines is not None:
            segs = lines[:, 0] if lines.ndim == 3 else lines   # 🐛 OpenCV 版本差异: (N,1,4) vs (N,4)
            lens = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
            scratches = int(np.sum(lens >= self.th["scratch_len_min"]))

        # ── ③ 污染: 高斯模糊差分 + 连通域斑点 ──
        blur = cv2.GaussianBlur(gray, (21, 21), 0)
        diff = cv2.absdiff(gray, blur)
        _, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        blobs = 0
        if n > 1:
            for i in range(1, n):
                if int(stats[i, cv2.CC_STAT_AREA]) >= self.th["blob_area_min"]:
                    blobs += 1

        # ── ④ 氧化/镀层缺损: 灰度中值偏移 ──
        med = float(np.median(gray))
        gray_dev = float(np.mean(np.abs(gray.astype(np.float32) - med)))

        # ── ⑤ 毛刺/变形: 边缘密度 ──
        edge_frac = float(edges.mean() / 255.0)

        # ── ⑥ 取像健康度 (新增: 让"参数对不对"上屏, 而不是只看缺陷) ──
        quality = self.assess_frame(img)

        # ── 对照 DET-AOI-01~04 组装判定 ──
        th = self.th
        items = [
            {"target_id": "DET-AOI-01", "target": "金手指表面缺陷", "defect": "划痕",
             "value": scratches, "threshold": f"≤{th['scratch_max']}条",
             "pass": scratches <= th["scratch_max"], "conf": 0.92},
            {"target_id": "DET-AOI-01", "target": "金手指表面缺陷", "defect": "污染",
             "value": blobs, "threshold": f"≤{th['blob_max']}点",
             "pass": blobs <= th["blob_max"], "conf": 0.90},
            {"target_id": "DET-AOI-01", "target": "金手指表面缺陷", "defect": "氧化/镀层缺损",
             "value": round(gray_dev, 2), "threshold": f"≤{th['gray_dev_max']}",
             "pass": gray_dev <= th["gray_dev_max"], "conf": 0.88},
            {"target_id": "DET-AOI-02", "target": "光口端面清洁度", "defect": "对焦不良/端面破损",
             "value": round(focus, 1), "threshold": f"≥{th['focus_min']}",
             "pass": focus >= th["focus_min"], "conf": 0.90},
            {"target_id": "DET-AOI-04", "target": "外观/尺寸检测", "defect": "毛刺/边缘密度",
             "value": round(edge_frac, 3), "threshold": f"≤{th['edge_frac_max']}",
             "pass": edge_frac <= th["edge_frac_max"], "conf": 0.85},
        ]
        # DET-AOI-03 金线/焊点显微检测: 需显微镜头图像 (本帧非显微), 标注 not-applicable 不误判
        items.append({"target_id": "DET-AOI-03", "target": "金线/焊点显微检测", "defect": "显微复检",
                      "value": None, "threshold": "需显微镜头帧", "pass": True, "conf": 1.0,
                      "note": "非显微帧, 跳过"})
        # ⚠️ 取像参数不健康时不报"PASS" —— 参数错的帧上谈缺陷判定没有意义 (2026-10-08 教训)
        overall = all(it["pass"] for it in items) and quality.get("verdict") in ("ok", "unknown")
        return {"pass": overall, "focus": focus, "scratch": scratches, "blob": blobs,
                "gray_dev": gray_dev, "edge_frac": edge_frac, "items": items, "quality": quality}

    # ─────────────────────────── 辅助: 给人看的一行 ───────────────────────────
    @classmethod
    def camera_profile_line(cls):
        """取像参数一行 (画布日志/提示用) —— 参数错了先看这行。"""
        c = cls.CAMERA
        return ("📷 取像参数 %s (SN %s): 曝光 %.0fus · 增益 %.2f · Gamma %.2f | 须先关 %s"
                % (c["model"], c["sn"], c["exposure_us"], c["gain_db"], c["gamma"],
                   "+".join(c["must_disable_auto_first"])))

    @classmethod
    def production_profile_line(cls):
        """产线↔调试 关系一行 (画布日志/汇报用)。"""
        p = cls.PRODUCTION
        return ("🔀 产线在 %s (10082 金手指 %s · 10083 表面 %s; 改它走 %s) | "
                "调试在本仓库 tools/aoi/ 同名副本 + 本类; 对齐用 %s"
                % (p["host"], p["finger"]["remote_file"].split("\\")[-1],
                   p["surface"]["remote_file"].split("\\")[-1], p["deploy_tool"], p["sync_tool"]))

    @classmethod
    def repo_copy_status(cls):
        """离线核对: 仓库里的调试副本是否还等于清单里登记的那版(产线当时的那版)。"""
        import hashlib
        import json
        import os
        out = {"manifest": None, "items": [], "ok": True}
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # → 仓库根
        mf = os.path.join(root, cls.PRODUCTION["manifest"])
        if not os.path.exists(mf):
            out["ok"] = False
            out["manifest"] = "缺清单 %s" % mf
            return out
        man = json.load(open(mf, encoding="utf-8"))
        out["manifest"] = mf
        for it in man.get("items", []):
            p = os.path.join(root, it["repo_copy"])
            if not os.path.exists(p):
                out["items"].append({"file": it["repo_copy"], "ok": False, "why": "缺文件"})
                out["ok"] = False
                continue
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            same = (h == it["sha256"])
            out["items"].append({"file": it["repo_copy"], "ok": same, "sha256": h[:16],
                                 "登记": it["sha256"][:16], "port": it["port"]})
            out["ok"] = out["ok"] and same
        return out

    @classmethod
    def experience_brief(cls):
        """经验一句话 (节点描述/汇报用): 病根 + 处方 + 定值依据。"""
        return ("经验(2026-10-08 实测): 相机**自动曝光/自动增益出厂是开的** ⇒ 曝光/增益写入全部"
                "静默失败(rv=100100010), 文件里的 10000us 从未生效; 相机改拉 ~94ms 超长曝光硬扛 ⇒ "
                "恒定过曝 ⇒ 金手指暗缝被糊白桥接 ⇒ 判据根数 19/21/22 反复、画面发糊。"
                "处方: 先 ExposureAuto/GainAuto→Off 再写参数(顺序不可换), 定值 曝光20000us·增益8.0 "
                "(扫档对比度 157 vs 其它档 33~34, 曝光仅自动档 1/5 ⇒ 更锐); 禁用\"停采集再写\"(会卡死相机)。")


def summarize(result):
    """检测结果 → 一行可读摘要 (画布日志用)"""
    if "error" in result:
        return f"❌ {result['error']}"
    parts = [f"清晰度={result['focus']:.0f}", f"划痕={result['scratch']}条",
             f"污染={result['blob']}点", f"灰度偏移={result['gray_dev']:.1f}",
             f"边缘密度={result['edge_frac']:.3f}"]
    q = result.get("quality") or {}
    if q:
        parts.append(f"取像={q.get('verdict')}({q.get('why', '')[:40]})")
    verdict = "✅ PASS" if result["pass"] else "❌ FAIL"
    return " · ".join(parts) + f" → {verdict} (场景级基线; 金手指/端面 ROI 特写检测需真机显微帧)"


# ─────────────────────────── 自检 (不需要相机): python quality_check.py ───────────────────────────
def _self_test():
    """合成三帧(正常/过曝/偏暗) 跑一遍判读 —— 交付前必须真跑, 数字对得上才算过。"""
    import numpy as np
    ok = True
    W, H = 600, 300
    def mk(pad, gap, base, blown=False, h=150):
        """合成一帧: h 行键带(19 片宽20/节距28) + 上下背景 —— 键带越矮, 带均值越被背景拉低。"""
        img = np.full((H, W, 3), base, np.uint8)
        y0, y1 = (H - h) // 2, (H + h) // 2
        img[y0:y1, :] = gap
        for i in range(19):
            x = 40 + i * 28
            img[y0:y1, x:x + 20] = 255 if blown else pad
        return img
    cases = [
        ("正常", mk(235, 30, 40), "ok"),                 # 片 235 / 缝 30 / 背景 40
        ("过曝", mk(255, 255, 220, blown=True), "overexposed"),
        ("偏暗", mk(60, 8, 10), "too_dark"),
    ]
    ck = AOIQualityChecker()
    print(AOIQualityChecker.camera_profile_line())
    for name, img, want in cases:
        q = ck.assess_frame(img)
        flag = "✅" if q["verdict"] == want else "❌"
        if q["verdict"] != want:
            ok = False
        print(f"  {flag} {name}: verdict={q['verdict']} (期望 {want}) 片={q['band_p50']} 缝={q['band_p10']} "
              f"对比度={q['contrast']} 片数={q['pads']} 过曝={q['blown']:.3f} 需补={q['need_x']}x")
    r = ck.check(cases[0][1])
    print(f"  check(): pass={r['pass']} items={len(r['items'])} quality={r['quality']['verdict']}")
    print(summarize(r))
    print("自检:", "✅ 全过" if ok else "❌ 有不对")
    return ok


if __name__ == "__main__":
    _self_test()
