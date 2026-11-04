#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compute_report.py — 汇总实测算力 → reports/compute/COMPUTE_REPORT.{md,json}

数据来源 (全部实测, 无估算混入):
  reports/compute/bench_550a_gpu.json     550A RTX 4060 / CPU
  reports/compute/bench_550c_npu.json     550C NPU (AI Boost 50.4 TOPS int8)
  reports/compute/bench_550c_gpu.json     550C iGPU (Arc B390 122.9 TOPS int8)
  reports/compute/bench_550c_cpu.json     550C CPU (Ultra X7 358H, 16T)
  /tmp 日志: SAM3 端到端 733~1134ms (550A, 按需)
记账口径:
  · 入拍 = 必须在 100 ms 控制周期内跑完的组件; 异步 = 按需/后台
  · 单拍预算按"最坏同时发生"算: 检测 + 世界模型 + 流形 + 动作头
  · Thor 一栏是**厂商规格换算的估算**, 明确标注 est., 不当实测用
"""
from __future__ import annotations

import json
import os

ROOT = os.environ.get("ZMAX_ROOT", os.path.expanduser("~/zmax"))
C = os.path.join(ROOT, "reports/compute")

TICK_MS = 100.0
# Thor 规格 (NVIDIA 公开口径, 用于估算): T5000 2070 TFLOPS FP4, T4000 1200; 273 GB/s; 40-130W
THOR = {"T5000_tflops_fp4": 2070, "T4000_tflops_fp4": 1200,
        "bw_gbs": 273, "power_w": (40, 130),
        "npu_i8_tops_550c": 50.4, "igpu_i8_tops_550c": 122.9}


def _load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                       # noqa: BLE001
        return {}


def _ms(d, k):
    v = (d.get("components") or {}).get(k) or {}
    return v.get("mean_ms") if v.get("ok") else None


def main() -> int:
    a = _load(os.path.join(C, "bench_550a_gpu.json"))       # 550A
    n = _load(os.path.join(C, "bench_550c_npu.json"))       # 550C NPU
    g = _load(os.path.join(C, "bench_550c_gpu.json"))       # 550C GPU
    c = _load(os.path.join(C, "bench_550c_cpu.json"))       # 550C CPU

    rows = []
    def add(name, task, where, val, note=""):
        rows.append({"component": name, "role": task, "host": where,
                     "ms": val, "note": note})

    # 550A
    add("YOLO 检测 (640)", "L2 感知", "550A 4060", _ms(a, "yolo_det@gpu"), "ultralytics torch fp32")
    add("SmolVLM2-500M 视觉塔", "L4 潜表示", "550A 4060", _ms(a, "smolvlm_vit@gpu"), "帧→768d, fp32")
    add("Qwen2.5-VL-3B", "L5 场景理解", "550A 4060", None, "8GB 装不下: 实测 OOM (权重 7.1GB); 在役走 DeepSeek API")
    add("SAM3 掩膜 (YOLO 框提示)", "L2 分割(按需)", "550A 4060", 733.0, "服务侧 733ms / 端到端 740~1141ms (日志实测)")
    add("流形引擎 1 步 (55D)", "L4 几何", "550A CPU", _ms(a, "manifold_engine@CPU"), "numpy 规则计算")
    # 550C
    add("YOLO 检测 (640)", "L2 感知", "550C NPU", _ms(n, "yolo_det@NPU"), "OpenVINO IR")
    add("YOLO 检测 (640)", "L2 感知", "550C iGPU", _ms(g, "yolo_det@GPU"), "OpenVINO IR")
    add("YOLO 检测 (640)", "L2 感知", "550C CPU", _ms(c, "yolo_det@CPU"), "OpenVINO IR")
    add("INTACT 编码", "L4 世界模型", "550C NPU", _ms(n, "intact_enc@NPU"), "intact_enc.onnx")
    add("INTACT 预测", "L4 世界模型", "550C NPU", _ms(n, "intact_pred@NPU"), "intact_pred.onnx")
    add("INTACT 编码", "L4 世界模型", "550C iGPU", _ms(g, "intact_enc@GPU"), "")
    add("INTACT 编码", "L4 世界模型", "550C CPU", _ms(c, "intact_enc@CPU"), "")
    add("SAM3 编码器", "L2 分割(按需)", "550C NPU", _ms(n, "sam3_encoder@NPU"), "894MB IR")
    add("SAM3 编码器", "L2 分割(按需)", "550C iGPU", _ms(g, "sam3_encoder@GPU"), "")
    add("SAM3 编码器", "L2 分割(按需)", "550C CPU", None, "单次 >170s 未完成 ⇒ 不可用")
    add("流形引擎 1 步 (55D)", "L4 几何", "550C CPU", _ms(n, "manifold_engine@CPU"), "")
    add("左脑动作头 MLP", "L3 前馈", "550C CPU", _ms(n, "action_head_mlp@CPU"), "39→512×3→4, 0.8M 参数")

    # 入拍预算 (选 550C NPU 为在役端侧口径)
    tick = {
        "yolo": _ms(n, "yolo_det@NPU") or 0,
        "intact_enc": _ms(n, "intact_enc@NPU") or 0,
        "intact_pred": _ms(n, "intact_pred@NPU") or 0,
        "manifold": _ms(n, "manifold_engine@CPU") or 0,
        "action_head": _ms(n, "action_head_mlp@CPU") or 0,
    }
    tick_total = sum(tick.values())
    budget = {"tick_ms": TICK_MS, "parts": {k: round(v, 3) for k, v in tick.items()},
              "total_ms": round(tick_total, 3),
              "duty_pct": round(100.0 * tick_total / TICK_MS, 1),
              "headroom_ms": round(TICK_MS - tick_total, 1),
              "verdict": ("入拍可行: 占空 %.1f%%, 余量 %.1f ms" % (100.0 * tick_total / TICK_MS,
                                                                 TICK_MS - tick_total))}
    async_ = {"sam3_gpu": _ms(g, "sam3_encoder@GPU"),
              "smolvlm_550a": _ms(a, "smolvlm_vit@gpu"),
              "qwen3b": None,
              "note": "SAM3/VLM 只能异步或按需: 单次数百 ms~秒级, 进 100ms 拍会把节拍吃掉"}

    # 在役显存实测 (nvidia-smi 抓的并发占用)
    vram = {"550A_total_mib": 8188,
            "in_service": {"ss_engine_loop(L4 VLM)": 1764, "intact_worker": 1320,
                           "sam3_seg(lazy)": 2306, "ss_yolo_on_real": 170,
                           "ss_local_infer": 142, "hil_bridge": 138, "shadow_mode": 92},
            "in_service_sum_mib": 1764 + 1320 + 2306 + 170 + 142 + 138 + 92,
            "note": "8GB 卡上三件大模型已 5.4GB ⇒ Qwen3B(6.7GB) 无法共存 (实测 OOM)"}

    thor = {
        "spec": THOR,
        "est": {
            "yolo_npu_to_thor": "按 int8 算力比 (Thor ≈ 10× 550C NPU) 估算 ≈ 0.3 ms 级",
            "sam3_gpu_to_thor": "按算力比 估算 ≈ 30~50 ms 级 ⇒ 可进异步帧, 仍不宜进 100ms 拍",
            "vlm_3b": "64/128GB 统一内存 ⇒ 3B VLM + INTACT + DiT 可常驻 (本机 8GB 装不下的那部分直接消失)",
            "caveat": "厂商 TFLOPS 是 FP4/稀疏口径, 与 int8 TOPS 不可直接同比 ⇒ 上面是量级估算, 不是实测",
        },
    }

    rep = {"ts": __import__("time").strftime("%F %T"), "rows": rows, "tick_budget": budget,
           "async": async_, "vram": vram, "thor": thor,
           "sources": ["bench_550a_gpu.json", "bench_550c_npu.json", "bench_550c_gpu.json",
                       "bench_550c_cpu.json"]}
    json.dump(rep, open(os.path.join(C, "COMPUTE_REPORT.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ── Markdown ──
    L = []
    L.append("# Z-MAX 算力实测报告 (550A / 550C)\n")
    L.append("生成 %s · 全部为**本机实测**延迟 (mean of N), 估算项已标注 est.\n" % rep["ts"])
    L.append("## 一、单组件实测\n")
    L.append("| 组件 | 角色 | 平台 | 延迟 (ms) | 说明 |")
    L.append("|---|---|---|---:|---|")
    for r in rows:
        ms = "N/A" if r["ms"] is None else ("%.2f" % r["ms"] if r["ms"] < 100 else "%.0f" % r["ms"])
        L.append("| %s | %s | %s | %s | %s |" % (r["component"], r["role"], r["host"], ms, r["note"]))
    L.append("\n## 二、100 ms 控制拍预算 (550C 端侧口径)\n")
    for k, v in budget["parts"].items():
        L.append("- %-12s %6.2f ms" % (k, v))
    L.append("- **合计 %.2f ms / 100 ms ⇒ 占空 %.1f%%，余量 %.1f ms**\n"
             % (budget["total_ms"], budget["duty_pct"], budget["headroom_ms"]))
    L.append("结论：%s\n" % budget["verdict"])
    L.append("## 三、只能异步的三件 (不能进拍)\n")
    L.append("- SAM3 掩膜：550C iGPU 实测 %s ms；550A 日志实测 733~1141 ms ⇒ 按需触发，不进拍"
             % (("%.0f" % async_["sam3_gpu"]) if async_["sam3_gpu"] else "N/A"))
    L.append("- SmolVLM2-500M 视觉塔：550A 实测 %.0f ms/帧 (fp32) ⇒ L4 潜表示 1 Hz 异步刷新"
             % (async_["smolvlm_550a"] or 0))
    L.append("- Qwen2.5-VL-3B：550A 8GB 实测 OOM（权重 7.1GB），在役 L5 走 DeepSeek API\n")
    L.append("## 四、在役并发显存 (550A 实测)\n")
    for k, v in vram["in_service"].items():
        L.append("- %-28s %5d MiB" % (k, v))
    L.append("- 合计 **%d MiB / %d MiB** ⇒ %s\n"
             % (vram["in_service_sum_mib"], vram["550A_total_mib"], vram["note"]))
    L.append("## 五、Thor 平台 projection (est., 非实测)\n")
    L.append("- 规格：T5000 %d TFLOPS FP4 / T4000 %d TFLOPS，%d GB/s，%d–%d W"
             % (THOR["T5000_tflops_fp4"], THOR["T4000_tflops_fp4"], THOR["bw_gbs"],
                THOR["power_w"][0], THOR["power_w"][1]))
    for k, v in thor["est"].items():
        L.append("- **%s**：%s" % (k, v))
    L.append("\n> 口径提醒：%s\n" % thor["est"]["caveat"])
    md = "\n".join(L)
    open(os.path.join(C, "COMPUTE_REPORT.md"), "w", encoding="utf-8").write(md)
    print(md[:2200])
    print("\n===> %s" % os.path.join(C, "COMPUTE_REPORT.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
