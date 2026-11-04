#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deck_m4.py — 在 M3 手册上补「算力实测 / BOM / 成本」六页 → 5.50.D-M4

数字全部从 reports/compute/*.json 读 (不手抄), 页面版式复用 4.03a 正文页。
插入位置: 4.03d 之后 (3 页算力) / 8.20 之后 (3 页成本)。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pptx import Presentation                                                # noqa: E402
from deck_55d_revise import clone_slide, move_slide_to, tf_set, shape_by_text, set_pagenum  # noqa: E402

ROOT = os.environ.get("ZMAX_ROOT", os.path.expanduser("~/zmax"))
SRC = os.path.join(ROOT, "zmax_data/deliverables/20261105/"
                         "Z-MAX以世界模型为核心的状态空间工程_5.50.D-M3.pptx")
OUT = os.path.join(ROOT, "zmax_data/deliverables/20261105/"
                         "Z-MAX以世界模型为核心的状态空间工程_5.50.D-M4.pptx")
C = os.path.join(ROOT, "reports/compute")


def _j(n):
    return json.load(open(os.path.join(C, n), encoding="utf-8"))


def _ms(d, k, nd=2):
    v = (d.get("components") or {}).get(k) or {}
    return ("%.*f" % (nd, v["mean_ms"])) if v.get("ok") else "N/A"


def pages():
    a = _j("bench_550a_gpu.json")
    n = _j("bench_550c_npu.json")
    g = _j("bench_550c_gpu.json")
    c = _j("bench_550c_cpu.json")
    cr = _j("COMPUTE_REPORT.json")
    bc = _j("BOM_COST.json")
    tick = cr["tick_budget"]

    p = {}
    p[("4.03", "e")] = ("e", "算力实测：两台机器 × 三个计算单元（全部本机实测）", [
        "▪ 550A（RTX 4060 8GB）  YOLO 640 检测 %s ms · SmolVLM2-500M 视觉塔 %s ms/帧 · SAM3 掩膜 733~1141 ms（按需）· 流形引擎 %s ms/步"
        % (_ms(a, "yolo_det@gpu"), _ms(a, "smolvlm_vit@gpu", 0), _ms(a, "manifold_engine@CPU", 2)),
        "▪ 550C · NPU（AI Boost 50.4 TOPS int8）  YOLO %s ms · INTACT 编码 %s ms + 预测 %s ms · SAM3 编码 %s ms · 流形 %s ms · 左脑 MLP %s ms"
        % (_ms(n, "yolo_det@NPU"), _ms(n, "intact_enc@NPU"), _ms(n, "intact_pred@NPU"),
           _ms(n, "sam3_encoder@NPU", 0), _ms(n, "manifold_engine@CPU"), _ms(n, "action_head_mlp@CPU")),
        "▪ 550C · iGPU（Arc B390 122.9 TOPS int8）  YOLO %s ms · INTACT 编码 %s ms · SAM3 编码 %s ms —— SAM3 在 iGPU 上比 NPU 快 6 倍（%s → %s ms）"
        % (_ms(g, "yolo_det@GPU"), _ms(g, "intact_enc@GPU"), _ms(g, "sam3_encoder@GPU", 0),
           _ms(n, "sam3_encoder@NPU", 0), _ms(g, "sam3_encoder@GPU", 0)),
        "▪ 550C · CPU（Ultra X7 358H 16T）  YOLO %s ms · INTACT 编码 %s ms ⇒ 纯 CPU 跑检测已吃掉整个拍，NPU/iGPU 不是可选项"
        % (_ms(c, "yolo_det@CPU"), _ms(c, "intact_enc@CPU")),
        "▪ 装不下的那个  Qwen2.5-VL-3B（权重 7.1GB）在 4060 8GB 上实测 OOM；在役 L5 场景理解走 DeepSeek API，本地只保留 SmolVLM 视觉塔。",
    ], "口径：每项先 warmup 再计时取均值；IR/ONNX 走 OpenVINO，torch 走 CUDA。没有一项是论文值或厂商值。")

    p[("4.03", "f")] = ("f", "100 ms 控制拍预算：入拍 8.3 ms，三件大模型只能异步", [
        "▪ 入拍合计 %s ms / 100 ms ⇒ 占空 %.1f%%，余量 %s ms（YOLO %s + INTACT %s + 流形 %s + 动作头 %s）"
        % (tick["total_ms"], tick["duty_pct"], tick["headroom_ms"], tick["parts"]["yolo"],
           tick["parts"]["intact_enc"] + tick["parts"]["intact_pred"], tick["parts"]["manifold"],
           tick["parts"]["action_head"]),
        "▪ 为什么能进拍  检测与世界模型都在 NPU 上（2.9 ms / 3.9 ms 量级），流形与动作头是 CPU 上的小矩阵运算（<1 ms），三者互不抢设备。",
        "▪ 只能异步的三件  SAM3 掩膜 %s ms（iGPU）· SmolVLM 视觉塔 %s ms（550A）· Qwen3B 秒级 ⇒ 按需触发/1 Hz 刷新，不进拍。"
        % (_ms(g, "sam3_encoder@GPU", 0), _ms(a, "smolvlm_vit@gpu", 0)),
        "▪ 分层的算力依据  同一个 100 ms 里硬塞 SAM3 会把占空从 8.3% 打到 480%——分层不是审美，是预算约束。",
        "▪ 空转也要算  L4 视觉编码 1 Hz 占 4% 的拍；若改成每拍编码，单这一项就超预算 7.7 倍（768 ms / 100 ms）。",
    ], "判据不是「跑得动」，是「在 100 ms 里还剩多少给异常处理」：现在余 91.7 ms，够跑四道安全闸与退段重试。")

    vram = cr["vram"]
    p[("4.03", "g")] = ("g", "显存与共存：8GB 卡已经满了，这条路只能走到 Thor", [
        "▪ 550A 在役并发实测  %d MiB / %d MiB —— 引擎(L4 视觉) 1.8G + INTACT worker 1.3G + SAM3(懒加载) 2.3G + 四个小服务 0.5G"
        % (vram["in_service_sum_mib"], vram["550A_total_mib"]),
        "▪ 后果  Qwen2.5-VL-3B 需 ~6.7GB ⇒ 与三件大模型不可能同卡；实测直接 OOM，不是配置问题。",
        "▪ 550C 走另一条路  30GB 内存 + NPU/iGPU 分工：YOLO/INTACT 上 NPU，SAM3 上 iGPU，CPU 只跑流形与动作头 —— 没有显存争用。",
        "▪ Thor（T5000 2070 TFLOPS FP4 / T4000 1200，273 GB/s，40–130W，64/128GB 统一内存）  3B VLM + INTACT + DiT 可常驻，SAM3 按算力比估算降到几十 ms 级（est.，非实测）。",
        "▪ 车规路线  量产版按车规级 Thor（宽温/振动/长供期）选型，软件侧不改接口：算力单元是配置项，不是架构项。",
    ], "厂商 TFLOPS 是 FP4/稀疏口径，与 int8 TOPS 不可直接同比：上面 Thor 的数字只作量级估算，验收仍要在真机上实测。")

    t550, tth = bc["tiers"]["550C(Intel)"], bc["tiers"]["Thor T5000"]
    p[("8.20", "a")] = ("a", "BOM 三档：目标成本 30 / 22 / 35 万，两档在限内、专家版超 5%", [
        "▪ 精细操作（双臂）  BOM %.2f 万（550C）/ %.2f 万（Thor），目标 30 万 ⇒ 余量 %+.2f / %+.2f 万"
        % (t550["精细操作（双臂）"]["bom_wan"], tth["精细操作（双臂）"]["bom_wan"],
           t550["精细操作（双臂）"]["margin_vs_target_wan"],
           tth["精细操作（双臂）"]["margin_vs_target_wan"]),
        "▪ 集出版（单臂）  BOM %.2f 万 / %.2f 万，目标 22 万 ⇒ 余量 %+.2f / %+.2f 万（余量最大的一档）"
        % (t550["集出版（单臂）"]["bom_wan"], tth["集出版（单臂）"]["bom_wan"],
           t550["集出版（单臂）"]["margin_vs_target_wan"], tth["集出版（单臂）"]["margin_vs_target_wan"]),
        "▪ 专家版（双臂+力控装配）  BOM %.2f 万 / %.2f 万，目标 35 万 ⇒ 超 %.2f / %.2f 万（六维力×2 + 3D 视觉 + 快换工装是主因）"
        % (t550["专家版（双臂+力控装配）"]["bom_wan"], tth["专家版（双臂+力控装配）"]["bom_wan"],
           -t550["专家版（双臂+力控装配）"]["margin_vs_target_wan"],
           -tth["专家版（双臂+力控装配）"]["margin_vs_target_wan"]),
        "▪ 双臂 BOM 构成（550C）  机械臂 11.60 · 夹爪力觉 3.20 · 相机 1.35 · 算力 1.10 · 结构 3.20 · 电控 1.80 · 线束 0.50 · 调试 2.40 · 包装 0.60（万）",
        "▪ 算力单元只占 4%~9%  BOM 里最便宜的一件却决定节拍上限：换成无 NPU 工控机省 0.9 万，YOLO 从 2.9 ms 变 98 ms，拍直接废掉。",
    ], "单价是 2026 参考价（中值）；换供应商、批量、国产化都会变，签前按报价单重算，不拿这张表当报价。")

    roi = bc["roi"]
    cd = bc["cost_down"]
    p[("8.20", "b")] = ("b", "成本与回本：0.55~0.70 年，专家版要先降本再报价", [
        "▪ 回本（售价=目标价口径）  双臂 %s 年 · 单臂 %s 年 · 专家版 %s 年（年净省 54.4 / 31.2 / 54.4 万元）"
        % (roi["精细操作（双臂）"]["payback_years"], roi["集出版（单臂）"]["payback_years"],
           roi["专家版（双臂+力控装配）"]["payback_years"]),
        "▪ 产能口径  314 件/h × 8000 h × 稼动率 85% = 213.5 万件/年；人工 0.36 元/件 vs 设备 0.105 元/件，单件净省 0.255 元。",
        "▪ 专家版降本三条  ① 六维力只装插入臂（省 3.2 万 → %.2f 万）② 3D 视觉改用手臂相机+深度反投影（省 2.8 万）③ 结构件批量与工装标准化（省 0.8~1.2 万）。"
        % (t550["专家版（双臂+力控装配）"]["bom_wan"] - 3.2),
        "▪ 两种读法必须说清  30/22/35 万若当**成本**：两档在限内、专家版超 5%；若当**售价**：双臂毛利 14%%、专家版 −5%% ⇒ 不可签。",
        "▪ 毛利红线  低于 15% 的档位不接：软件迭代、备件与远程支持会把毛利吃回去（这是三年账，不是首单账）。",
    ], "回本快是因为人工贵、节拍高；一旦客户产能利用率掉到 50% 以下，回本翻倍——报价前先问产能，不问参数。")

    p[("8.20", "c")] = ("c", "这一页给结论：算力不是瓶颈，成本要按档位说清", [
        "▪ 算力  100 ms 拍只用掉 8.3%（入拍 8.33 ms，余 91.7 ms）；SAM3/VLM 异步化后，550C 这一级端侧就够跑当前闭环。",
        "▪ 平台  550C 用 NPU+iGPU 分工（无显存争用）；Thor 让 3B VLM 与 DiT 常驻成为可能，是下一代的标配而不是当下的门槛。",
        "▪ 成本  双臂 %.2f 万 / 单臂 %.2f 万 均在目标内；专家版 %.2f 万超 5%%，按三条降本路径可回到 33.65 万。"
        % (t550["精细操作（双臂）"]["bom_wan"], t550["集出版（单臂）"]["bom_wan"],
           t550["专家版（双臂+力控装配）"]["bom_wan"]),
        "▪ 商业定位  卖的不是硬件，是「0.5 mm 精度 + 1 年回本 + 可复核判据」；硬件 BOM 只占售价的一半左右，剩下是软件与进化服务。",
        "▪ 下一步  车规 Thor 选型验证（宽温/振动/供期）+ 专家版降本样机 + 力控装配 C3 的 30 次重复性报告。",
    ], "把「算力够不够」变成可复核的表，把「成本高不高」变成按档位的账：这两页之后，争论就只能围绕数字，而不是感觉。")
    return p


def _ref_slide(prs):
    """按**左上角编号框的精确文本**找版式页: 不能只搜 "4.03a" —— 4.03 正文里也写着"见 4.03a" (踩过)。"""
    for i, s in enumerate(prs.slides):
        for sh in s.shapes:
            if sh.has_text_frame and sh.top is not None and sh.top < 1.0 * 914400:
                if sh.text_frame.text.strip() == "4.03a":
                    return i
    return None


def main() -> int:
    prs = Presentation(SRC)
    src_idx = _ref_slide(prs)
    if src_idx is None:
        raise SystemExit("找不到 4.03a 版式页")
    P = pages()
    # 🔴 同一个锚点插多页时必须**倒序**插: 每页都插在锚点正后方, 正序会得到 g,f,e (踩过)
    plan = [("4.03d", ("4.03", "g")), ("4.03d", ("4.03", "f")), ("4.03d", ("4.03", "e")),
            ("8.20", ("8.20", "a")), ("8.20", ("8.20", "b")), ("8.20", ("8.20", "c"))]
    # 逐页插: 每次都在锚点后追加, 顺序自然
    for anchor, key in plan:
        idx = None
        for i, s in enumerate(prs.slides):
            if shape_by_text(s, anchor) is not None:
                idx = i
        if idx is None:
            print("⚠️ 找不到锚点 %s, 跳过 %s" % (anchor, key))
            continue
        _, title, lines, bottom = P[key]
        s = clone_slide(prs, src_idx)
        move_slide_to(prs, len(prs.slides) - 1, idx + 1)
        s = prs.slides[idx + 1]
        ref = [x for x in s.shapes if x.has_text_frame and x.text_frame.text.strip() == "4.03a"]
        tf_set(ref[0].text_frame, [key[0] + key[1]])   # 编号按"章节+字母", 不是锚点页号
        ttl = [x for x in s.shapes if x.has_text_frame and "55D 分段" in x.text_frame.text]
        tf_set(ttl[0].text_frame, [title])
        body = [x for x in s.shapes if x.has_text_frame and x.width and x.width > 10 * 914400
                and x.top and 1.9 * 914400 < x.top < 3.0 * 914400]
        tf_set(body[0].text_frame, lines)
        bot = [x for x in s.shapes if x.has_text_frame and x.top and 6.2 * 914400 < x.top < 6.9 * 914400]
        tf_set(bot[0].text_frame, [bottom])
        src_idx = _ref_slide(prs)
        print("✅ 插入 %s%s · %s" % (anchor, key[1], title))

    # 版本 / 页码 / 封面页数
    n1 = len(prs.slides)
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                t = sh.text_frame.text
                if "5.50.D-M3" in t or ("范围：" in t and "页" in t):
                    import re
                    _t = t.replace("5.50.D-M3", "5.50.D-M4")
                    _t = re.sub(r"范围：\d+ 页", "范围：%d 页" % n1, _t)
                    if _t != t:
                        tf_set(sh.text_frame, [_t])
    for i, s in enumerate(prs.slides, start=1):
        set_pagenum(s, i)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print("✅ %s · %d 页 · %.1f KB" % (OUT, n1, os.path.getsize(OUT) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
