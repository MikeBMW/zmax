#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 550C 探针原始 JSON + 复核修正值 → 正式性能报告 (md + json)。
每个修正都写明依据(复核命令), 保证 md 里每个数都能在 json 里查到。
"""
import json
import os
import time

RAW = "/home/ubuntu/.hermes/cache/scratch/perf_550c.json"
OUTDIR = "/home/ubuntu/zmax/zmax_data/reports"
os.makedirs(OUTDIR, exist_ok=True)
d = json.load(open(RAW, encoding="utf-8"))
M = {m["metric"]: m for m in d["m"]}


def fix(metric, value=None, unit=None, verdict=None, threshold=None, source=None, samples=None):
    m = M.get(metric)
    if not m:
        return
    if value is not None:
        m["value"] = value
    if unit is not None:
        m["unit"] = unit
    if verdict is not None:
        m["verdict"] = verdict
    if threshold is not None:
        m["threshold"] = threshold
    if source is not None:
        m["source"] = source
    if samples is not None:
        m["samples"] = samples


def drop(metric):
    d["m"] = [m for m in d["m"] if m["metric"] != metric]


def add(cat, metric, value, unit="", verdict="—", threshold="", source="", samples=1):
    d["m"].append({"cat": cat, "metric": metric, "value": value, "unit": unit, "verdict": verdict,
                   "threshold": threshold, "source": source, "samples": samples})


# ---- 复核修正 (每条都有独立命令支撑) ----
fix("臂相机桥 8811 实测帧率", value=17.97, verdict="PASS", threshold="≥10fps(桥限 15…实测超)",
    source="8811/health.fps 字段(原探针错读 n 字段→0, 已复核两次均 17.97)")
fix("cam relay :8901", value="up", verdict="PASS", source="curl -o /dev/null -w %{http_code} http://127.0.0.1:8901/ → 200; ss -ltnp 有监听")
drop("渲染/推流 :8816")   # 550C 上不存在这个端口(是 4060 的), 不属本机指标
fix("最高温度", value=98.0, verdict="FAIL", threshold="<85°C", source="/sys/class/thermal/thermal_zone*: x86_pkg_temp 98000m°C; acpitz 27.8°C")
add("F系统资源", "GPU(Arc B390) 频率 gt0 当前/上限", "2500/2500", "MHz", "PASS", "训练中应接近上限",
    "/sys/class/drm/card0/device/tile0/gt0/freq0/{cur,max}_freq")
add("F系统资源", "GPU 第二 tile 频率", "600", "MHz", "—", "空闲时低", "/sys/class/drm/card0/device/tile1/gt1/freq0/cur_freq")
add("F系统资源", "GPU 利用率", "err(无 xpu-smi)", "%", "—", "",
    "xpu-smi 未安装(intel_gpu_top 亦无); 只有 sysfs 频率可用 → 记为不可测，不用估计值顶替", 0)
add("F系统资源", "内存 TOP1 进程", "zmax_evolve_intel.py 5.6GB", "", "—", "<8GB", "ps -eo rss,args --sort=-pcpu")
add("G训练", "训练吞吐", "1.93", "步/s", "—", "", "train_report: 3000 步 / 1557s")
add("G训练", "本轮数据→首份资产 端到端", "约 33", "分钟", "—", "MIN_SPAN 0.10m / ≥160 帧触发",
    "18:29 采集起 → 19:02 train_report 落盘")

fix("当前会话帧数", value="会话已收口(cur=null)", verdict="—", source="8806/health cur=null, cooldown 已过期")

# ---- H 配置完备性 ----
add("H配置完备", "两套代码树 tools/*.py 不一致文件数", 4, "个", "WARN", "应为 0(同类工具不同版本=埋坑)",
    "md5 逐个比对 zmax_map/tools 与 zmax_550c/tools: gs_autocap_daemon / gs_dataset / gs_ros_bridge / tcp_ar_server")
add("H配置完备", "tools 文件数 zmax_map / zmax_550c", "1262 / 1479", "个", "—", "",
    "ls /home/intel/{zmax_map,zmax_550c}/tools/*.py | wc -l")
add("H配置完备", "systemd drop-in 覆盖", 6, "个", "—", "", "ls /etc/systemd/system/zmax*.service.d/*.conf | wc -l")
add("H配置完备", "建图空间点 space_points.json", "缺", "", "WARN", "自动走点建图需要",
    "查 /home/intel/zmax_data/gs_map/space_points.json 与 config/gs_map.json 均不存在")
add("H配置完备", "相机内参/手眼状态", "齐", "", "PASS", "缺一不可",
    "real_cam_calib_undist.json + handeye_state.json 均在 ~/zmax_map/models")

# 分类汇总重算
by = {}
for m in d["m"]:
    by.setdefault(m["cat"], []).append(m)
d["summary"] = {c: {"n": len(v), "PASS": sum(1 for x in v if x["verdict"] == "PASS"),
                    "WARN": sum(1 for x in v if x["verdict"] == "WARN"),
                    "FAIL": sum(1 for x in v if x["verdict"] == "FAIL"),
                    "err": sum(1 for x in v if x["value"] == "err")} for c, v in by.items()}
tot = {"n": len(d["m"]), "PASS": sum(1 for x in d["m"] if x["verdict"] == "PASS"),
       "WARN": sum(1 for x in d["m"] if x["verdict"] == "WARN"),
       "FAIL": sum(1 for x in d["m"] if x["verdict"] == "FAIL"),
       "err": sum(1 for x in d["m"] if x["value"] == "err")}
d["summary"]["_total"] = tot
d["meta"]["probe"] = "perf_550c.py (十类探针) + 人工复核修正 6 处"
d["meta"]["raw_probe_json"] = "/home/intel/tmp/perf_550c.json (550C 本机)"

ORDER = ["A层推理/进化", "B常驻回路", "C视觉链路", "D模型资产", "E服务可用", "F系统资源",
         "G训练", "H配置完备", "I端到端", "J安全/真源"]

ts = d["meta"]["ts"].replace(":", "").replace("-", "").replace(" ", "_")
jsonp = os.path.join(OUTDIR, "550C_perf_%s.json" % ts)
mdp = os.path.join(OUTDIR, "550C_perf_%s.md" % ts)
json.dump(d, open(jsonp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

L = []
A = L.append
A("# 550C 性能实测报告")
A("")
A("- 主机：%s（192.168.23.70，Intel Core Ultra / Arc B390，16 线程，30.9GB）" % d["meta"]["host"])
A("- 采集时间：%s" % d["meta"]["ts"])
A("- 工装：`%s`（十类探针，每项真测；测不到的写 err，不用估计值）" % d["meta"]["probe"])
A("- 机读版：`%s`" % jsonp)
A("")
A("## 总览")
A("")
A("| 类别 | 指标数 | PASS | WARN | FAIL | err |")
A("|---|---|---|---|---|---|")
for c in ORDER:
    s = d["summary"].get(c)
    if s:
        A("| %s | %d | %d | %d | %d | %d |" % (c, s["n"], s["PASS"], s["WARN"], s["FAIL"], s["err"]))
A("| **合计** | **%d** | **%d** | **%d** | **%d** | **%d** |" % (tot["n"], tot["PASS"], tot["WARN"], tot["FAIL"], tot["err"]))
A("")
A("口径：PASS/WARN/FAIL 只在有预算处判定，无预算的标 `—`；每行带来源命令或文件，可复跑。")
A("")
for c in ORDER:
    ms = by.get(c)
    if not ms:
        continue
    A("## %s（%d 项）" % (c, len(ms)))
    A("")
    A("| 指标 | 值 | 判定 | 阈值 | 来源 |")
    A("|---|---|---|---|---|")
    for m in ms:
        A("| %s | %s%s | %s | %s | %s |" % (
            m["metric"], m["value"], (" " + m["unit"]) if m["unit"] else "",
            m["verdict"], m["threshold"] or "—", m["source"] or "—"))
    A("")

A("## 结论（按根因归并）")
A("")
fails = [m for m in d["m"] if m["verdict"] == "FAIL"]
warns = [m for m in d["m"] if m["verdict"] == "WARN"]
A("**① CPU 被四件重活超订 1.75×，同时封装温度 98°C、主频从 2600 掉到 2195MHz** —— 这是本轮最硬的瓶颈。")
A("证据：`load1 28.03 / 16 线程`；TOP 进程 `zmax_shadow_mode.py 173%`、`ss_skill_dispatch.py(60Hz) 127%`、")
A("`zmax_evolve_intel.py 98.9%（RSS 5.6GB）`、`gs_train.py 94.7%`；`x86_pkg_temp 98°C`（acpitz 27.8°C 是壳温，不代表核心）。")
A("")
A("**② GPU 其实一点不闲、也没算力缺口** —— `gt0 2500/2500MHz` 满频在跑训练，`gt1 600MHz` 闲着。")
A("所以“加算力”不是解法，**把进化/影子/技能派发从 CPU 挪到 GPU 或限频**才是（同一颗 OpenVINO 模型在")
A("Arc iGPU 1.62ms vs CPU 79.8ms，量级差）。利用率口径因机器没装 `xpu-smi` 只能记 err，不给估计值。")
A("")
A("**③ 视觉链路本身是好的** —— 臂相机桥 17.97fps、帧龄 0.01~0.05s、位姿龄 0.04s、亮度 77；USB 相机 10fps、帧龄 0.067s；")
A("上游 Orin 8794 中继 `n=701690` 在出帧。唯一 WARN 是 8814 训练服务健康检查 2.6s（训练占满时 HTTP 被拖慢，非服务挂）。")
A("")
A("**④ 建图闭环真实跑通，但产出质量只到 15.07dB** —— 1352 帧 → 2 会话 → 2 作业；最近一份 3000 步 / 109193 高斯 /")
A("PSNR 留出 15.07、训练 15.96 / 1557s。历史 66 份作业最佳 17.48dB。低于“可用重建”18dB 门槛，是数据覆盖问题，不是训练链路问题。")
A("")
A("**⑤ 真源与闸门齐备** —— 内参 `real_cam_calib_undist.json`、手眼 `handeye_state.json` 都在；")
A("本机无 `ctl_auth.json`（运动授权在 4060 侧，550C 不持授权，这是设计而非缺失）。")
A("")
A("**⑥ 配置面有两处坑** —— 两套代码树（`zmax_map/tools` 与 `zmax_550c/tools`）有 4 个同名工具内容不一致")
A("（`gs_autocap_daemon` / `gs_dataset` / `gs_ros_bridge` / `tcp_ar_server`），今天为修采集死锁和白平衡只改了其中一套；")
A("另外 550C 上**没有** `space_points.json`，所以它现在只能“边动边采”，不能自己按空间点走位。")
A("")
A("## 待办（可验收）")
A("")
A("1. 装 `xpu-smi`（或给 `intel_gpu_top` 加 cap）把 GPU 利用率纳入常测 —— 现在这块只能给频率，不给利用率。")
A("2. 给 `zmax_evolve_intel` / `zmax_shadow_mode` / `ss_skill_dispatch` 设 CPU 亲和或降频，把 load1 压回 ≤16/16；")
A("   验收：训练同跑时 `x86_pkg_temp < 90°C`、`load1 ≤ 16`、`gs_train 吞吐 ≥1.9 步/s` 不掉。")
A("3. 建图质量要过 18dB：下一轮走点把平移跨度拉大到 ≥0.5m、帧间位移 ≤5cm（`GS_MAX_STEP_M` 已限 5cm）。")
A("")
open(mdp, "w", encoding="utf-8").write("\n".join(L) + "\n")
print(mdp)
print(jsonp)
print(tot)
