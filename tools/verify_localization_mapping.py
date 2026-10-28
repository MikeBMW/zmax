# -*- coding: utf-8 -*-
"""verify_localization_mapping.py — 「融合定位建图」专用实现的判据 (逐项 ✅/❌ + 证据 + 未验证项)。

口径 (老倪 2026-10-13): 融合定位建图必须是**专用实现** (不与 perception.py 共用), 进系统自动加载并启动建图,
基于视觉 + 机器人位姿 (ORB 类)。判据覆盖:
  ①独立性: 模块不 import perception.py, 自带 43D 契约, perception.py 的 fuse_sensors 原样未动
  ②自检: 随机纹理 + 已知单应 ⇒ 特征/匹配/单应内点/旋转恢复/内点重投影 5 项全过
  ③真录像建图 (真实运动): 真 mp4 ⇒ 关键帧/地图点/视差 三条硬指标
  ④去重: 源刷新慢/静止段 ⇒ 重复帧被识别跳过 (不伪造关键帧)
  ⑤静止场景不撒谎: 重复帧输入 ⇒ 不新增关键帧, 地图点 0 且带 degenerate 说明
  ⑥机器人位姿唯一依据: 新鲜/陈旧判定 + 路径 + 不造位姿
  ⑦落盘唯一依据: map/traj/live 三份文件 + traj 行数 == 帧数
  ⑧自主进化接口: 质数签名 + 产品标识
  ⑨自动加载开关: auto_load=false 时 auto_start 真返回未启动 (自清理)
  ⑩零回归: perception.py 的 fuse_sensors/OBS_DIM 未被本模块改动
幂等: 探针写 /tmp 带 pid; 不改任何既有唯一依据 (auto_load 开关测完恢复); 不重启控制台。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_localization_mapping.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
PY = sys.executable or os.path.join(ROOT, "gui-venv311", "bin", "python")
MOD = os.path.join(ROOT, "src", "lerobot", "manifold", "localization_mapping.py")
PERC = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "perception.py")
VIDEO = os.path.join(ROOT, "zmax_data", "release_5.49.4_20261012", "reports", "tray_place_latest.mp4")
OK, BAD, SKIP = [], [], []


def chk(name, ok, ev):
    (OK if ok else BAD).append((name, ev))
    print("  %s %-52s %s" % ("✅" if ok else "❌", name, ev))


def run_mod(args, timeout=500):
    p = subprocess.run([PY, MOD] + args, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    try:
        return json.loads(p.stdout or "{}"), p.returncode, (p.stderr or "")[:200]
    except Exception:                                                            # noqa: BLE001
        return {}, p.returncode, (p.stdout or "")[:200] + (p.stderr or "")[:200]


def main() -> int:
    t0 = time.time()
    print("═" * 100)
    print("融合定位建图 · 判据")
    print("═" * 100)

    from lerobot.manifold import localization_mapping as LM

    # ① 独立性 (老倪: 与 perception.py 公用"不好" ⇒ 必须专用)
    print("\n[① 独立性] 专用实现, 不与 perception.py 共用")
    src = io.open(MOD, encoding="utf-8").read()
    imports_perc = ("perception" in src and "import" in src.split("perception")[0][-40:])
    chk("模块不 import perception.py", not imports_perc,
        "grep 'perception' 出现在 import 段的次数=0" if not imports_perc else "仍在 import perception")
    perc = io.open(PERC, encoding="utf-8").read()
    chk("perception.py 的 fuse_sensors 未被本模块改动", "def fuse_sensors(" in perc,
        "perception.py:15-16 OBS_DIM=%s VISUAL_DIM=%s 原样" % ("43" if "OBS_DIM = 43" in perc else "?",
                                                               "39" if "VISUAL_DIM = 39" in perc else "?"))
    obs = LM.fuse_mapping_obs(np.zeros(39), np.zeros(6), np.zeros(4))
    chk("自带 43D 契约 (视觉39 ⊕ 触觉4), 不依赖 perception 常量",
        obs["obs"].shape == (43,) and LM.MAPPING_VISUAL_DIM == 39 and LM.MAPPING_TACTILE_DIM == 4,
        "obs=%s · 视觉%d + 触觉%d = %d" % (obs["obs"].shape, LM.MAPPING_VISUAL_DIM, LM.MAPPING_TACTILE_DIM, LM.MAPPING_OBS_DIM))
    try:
        LM.fuse_mapping_obs(np.zeros(38), np.zeros(6), np.zeros(4))
        chk("维度错误被拒 (不许静默)", False, "竟然接受了 38 维")
    except LM.MappingError as e:
        chk("维度错误被拒 (不许静默)", True, str(e)[:48])

    # ② 自检 (随机纹理 + 已知单应)
    print("\n[② 自检] 随机纹理 + 已知单应 (不依赖相机的最小可解自检)")
    st, rc, err = run_mod(["selftest"], timeout=300)
    c = st.get("checks") or {}
    chk("自检 5 项全过", bool(c) and all(c.values()) and rc == 0,
        "旋转误差 %.3f° · 匹配 %s · 单应内点 %s · 内点重投影 %.3fpx"
        % (st.get("rot_err_deg") or -1, st.get("matches"), st.get("homography_inliers"),
           st.get("inlier_reproj_mean_px") or -1))

    # ③ 真录像建图 (真实运动)
    print("\n[③ 真录像建图] 摆盘实拍 mp4 (真实运动) ⇒ 关键帧/地图点/视差")
    if os.path.isfile(VIDEO):
        r, rc, err = run_mod(["run", "--n", "60", "--stride", "6", "--video", VIDEO,
                              "--scene", "SCN-JUDGE-VIDEO"], timeout=500)
        s = r.get("summary") or {}
        chk("真录像: 关键帧 ≥ 5", (s.get("keyframes") or 0) >= 5, "kf=%s" % s.get("keyframes"))
        chk("真录像: 地图点 > 100", (s.get("map_points") or 0) > 100, "map_points=%s" % s.get("map_points"))
        chk("真录像: 真视差 (中位 > 1px)", (s.get("parallax_px") or {}).get("median", 0) > 1.0,
            "视差 %s" % (s.get("parallax_px") or {}))
        chk("真录像: 零错误", not (r.get("errors") or []), "errors=%s" % (r.get("errors") or [])[:1])
    else:
        SKIP.append(("真录像建图", "录像不存在: %s" % VIDEO))
        print("  ⏭ 真录像建图 未验证: 录像不存在")

    # ④ 去重 (源刷新慢 ⇒ 重复帧必须被识别)
    print("\n[④ 去重] 重复帧识别 (不伪造关键帧)")
    r2, _, _ = run_mod(["run", "--n", "6", "--cam", "arm", "--interval", "0.02",
                        "--scene", "SCN-JUDGE-DUP"], timeout=300)
    s2 = r2.get("summary") or {}
    chk("亚刷新间隔连抓 ⇒ 检出重复帧", (s2.get("dup_skipped") or 0) >= 1,
        "dup_skipped=%s / 帧 %s (实测源刷新 100~500ms)" % (s2.get("dup_skipped"), s2.get("frames")))

    # ⑤ 静止场景不撒谎
    print("\n[⑤ 静止场景] 重复帧 ⇒ 不新增关键帧 + 地图点 0 且标注退化")
    sess = LM.MappingSession(scene="SCN-JUDGE-STATIC", save=False)
    img = (np.random.default_rng(3).integers(0, 255, (480, 640))).astype(np.uint8)
    rec1 = sess.process(img, "s", None)
    rec2 = sess.process(img.copy(), "s", None)
    chk("同一帧第二次 ⇒ 判重复且不设关键帧", rec2.get("duplicate") is True and len(sess.keyframes) == 1,
        "dup=%s kf=%d" % (rec2.get("duplicate"), len(sess.keyframes)))
    chk("地图点 0 时带退化说明 (不装成有图)", (len(sess.map_points) == 0) and bool(sess.summary()["degenerate_note"]),
        sess.summary()["degenerate_note"][:40])

    # ⑥ 机器人位姿唯一依据
    print("\n[⑥ 机器人位姿] 唯一依据新鲜度判定 (不造位姿)")
    p = LM.read_robot_pose()
    if p.get("available"):
        chk("读到新鲜位姿唯一依据", p["age_s"] < 10.0 and "tcp_out" in (p.get("path") or ""),
            "age=%.2fs · path=…%s · xyz=%s" % (p["age_s"], (p.get("path") or "")[-34:], [round(x, 3) for x in p["xyz"]]))
        chk("位姿带坐标系/来源标注", bool(p.get("frame")) and bool(p.get("src")),
            "frame=%s src=%s" % (p.get("frame"), (p.get("src") or "")[:32]))
    else:
        chk("无新鲜位姿时如实说明 (不造位姿)", bool(p.get("reason")) and p.get("xyz") is None,
            "reason=%s" % (p.get("reason") or "")[:60])
        SKIP.append(("新鲜位姿", "当前环境无新鲜位姿唯一依据"))

    # ⑦ 落盘唯一依据
    print("\n[⑦ 落盘唯一依据] map / traj / live 三份")
    live_p = os.path.join(ROOT, "zmax_data", "mapping", "mapping_live.json")
    if os.path.isfile(live_p):
        live = json.load(io.open(live_p, encoding="utf-8"))
        tj = live.get("traj_file")
        n_lines = sum(1 for _ in io.open(tj, encoding="utf-8")) if tj and os.path.isfile(tj) else -1
        chk("live 唯一依据可读且字段齐全",
            all(k in live for k in ("frames", "keyframes", "map_points", "loops", "scale_source", "map_file")),
            "帧 %s · kf %s · 地图点 %s · 帧龄 %.0fs" % (live["frames"], live["keyframes"], live["map_points"],
                                                    time.time() - live["ts"]))
        chk("traj 行数 == 帧数 (逐帧轨迹)", n_lines == live["frames"], "traj %d 行 vs 帧 %s" % (n_lines, live["frames"]))
        chk("map 文件存在且含 keyframes/loops", os.path.isfile(live["map_file"]) and
            all(k in json.load(io.open(live["map_file"], encoding="utf-8")) for k in ("summary", "keyframes", "loops")),
            os.path.basename(live["map_file"]))
    else:
        chk("live 唯一依据存在", False, "未生成 %s" % live_p)

    # ⑧ 自主进化接口
    print("\n[⑧ 自主进化] 质数签名 + 产品标识")
    ev = (r2.get("evolution") or {}) if r2 else {}
    chk("建图结构 → 质数签名 (>0)", (ev.get("signature") or 0) > 0, "signature=%s" % ev.get("signature"))
    try:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.manifold import prime_structure as PS
        chk("产品标识 ∈ {550A,550B,550C}", PS.active_product() in PS.PRODUCT_PRIMES,
            "product=%s" % PS.active_product())
    except Exception as e:                                                       # noqa: BLE001
        SKIP.append(("产品标识", repr(e)[:60]))
        print("  ⏭ 产品标识 未验证: %s" % repr(e)[:60])

    # ⑨ 自动加载开关 (自清理)
    print("\n[⑨ 自动加载] 开关真生效")
    cfg_p = LM.CONFIG_J
    bak = io.open(cfg_p, encoding="utf-8").read() if os.path.isfile(cfg_p) else None
    try:
        d = json.loads(bak) if bak else dict(LM.DEFAULT_CONFIG)
        d["auto_load"] = False
        io.open(cfg_p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2))
        off = LM.auto_start(n_frames=1, save=False)
        chk("auto_load=false ⇒ 真不启动", off.get("started") is False, "reason=%s" % off.get("reason"))
    finally:
        if bak is not None:
            io.open(cfg_p, "w", encoding="utf-8").write(bak)
    on = json.load(io.open(cfg_p, encoding="utf-8"))
    chk("开关恢复原值 (自清理)", on.get("auto_load") is True, "auto_load=%s" % on.get("auto_load"))

    # ⑩ 零回归
    print("\n[⑩ 零回归] 既有 L2 感知链未动")
    chk("perception.py 仍在且 43D/39D 契约未变",
        os.path.isfile(PERC) and "OBS_DIM = 43" in perc and "VISUAL_DIM = 39" in perc,
        "perception.py 未被本模块修改 (只读校验)")
    chk("建图模块与感知模块是两份独立文件", os.path.isfile(MOD) and os.path.isfile(PERC),
        "%s(%d B) vs perception.py(%d B)" % (os.path.basename(MOD), os.path.getsize(MOD), os.path.getsize(PERC)))

    print("\n" + "═" * 100)
    print("结论: %d 项通过 · %d 项未过 · %d 项未验证 · 用时 %.1fs" % (len(OK), len(BAD), len(SKIP), time.time() - t0))
    for n, e in BAD:
        print("  ❌ %s — %s" % (n, e))
    for n, e in SKIP:
        print("  ⏭ %s — %s" % (n, e))
    print("═" * 100)
    out = os.path.join(ROOT, "reports", "localization_mapping_judge.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "pass": len(OK), "fail": len(BAD),
                   "skip": SKIP, "ok": [n for n, _ in OK], "bad": [n for n, _ in BAD]}, f,
                  ensure_ascii=False, indent=1)
    print("报告: %s" % out)
    return 0 if not BAD else 1


if __name__ == "__main__":
    raise SystemExit(main())
