#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topics_list_skill.py — 【只读·生成器】原子技能 topic 清单 (所有场景) → 文档。

老倪 2026-10-15: 「你来给出所有场景的原子技能 topic」。

唯一依据 = src/lerobot/dataspace/topics.py (话题登记) + 技能库 atomic_skills.py (技能号↔阶段);
本工具只**读**这两处渲染成人能看的清单, 不另存一份数 (两份必然打架)。

用法:
  ./gui-venv311/bin/python tools/topics_list_skill.py            # 打到屏幕
  ./gui-venv311/bin/python tools/topics_list_skill.py --md       # 写 docs/design/atomic_skill_topics_20261015.md
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

DOC = os.path.join(ROOT, "docs", "design", "atomic_skill_topics_20261015.md")
# 场景归属: 技能号 → 场景 (与 tools/ss_scene_switch.py 的颜色口径一致; SK07 两条链同号)
SCENE = {
    "SK01": "插拔场景(绿)", "SK02": "插拔场景(绿)", "SK03": "插拔场景(绿)", "SK04": "插拔场景(绿)",
    "SK05": "插拔场景(绿)", "SK06": "插拔场景(绿)",
    "SK07": "插拔场景(绿) / 摆盘场景(蓝) 同号两支 (插入 ↔ 放入)", "SK08": "插拔场景(绿) / 摆盘场景(蓝)",
}
SIG = [
    ("实测", "x / y / z", "mm", "末端位置 (真机 tap; 位姿停更 ⇒ -1)"),
    ("实测", "v", "mm/s", "速度 = ‖实际下发动作‖"),
    ("实测", "a", "mm/s²", "加速度 = 块间速度变化率 (保留到下一块, 不做 16ms 尖峰)"),
    ("实测", "s", "mm", "本段累计行程 (物理闸 InertiaLimiter.travel)"),
    ("实测", "angle", "deg", "末端姿态角 (真机 tap 四元数 2·acos|w|)"),
    ("实测", "err", "mm/s", "被物理闸削出来的偏差 ‖u_req − u‖"),
    ("包络", "v_cap", "m/s", "限速 (标定唯一依据)"),
    ("包络", "a_max", "m/s²", "加速度上限 = F/m"),
    ("包络", "jerk_max", "m/s³", "加加速度上限"),
    ("包络", "s_step", "m", "单拍位移上限"),
    ("包络", "s_max", "m", "段行程上限"),
    ("包络", "m_kg", "kg", "运动质量"),
    ("包络", "f_max", "N", "力上限"),
    ("元", "in_service / step / frame_age_s / why", "—", "在职 / 块内拍号 / 源帧龄 / 本拍被哪条约束削"),
]
CODE = [
    ("话题登记 (唯一依据)", "src/lerobot/dataspace/topics.py"),
    ("DDS 消息类型", "dds/ss_types.py → class SSSkillPhys"),
    ("类型/QoS 注册", "dds/zmax_node.py → _SS_TOPICS / QOS_CLASS"),
    ("实测值生产 (每拍过物理闸)", "tools/ss_skill_dispatch.py → cycle() → zmax_data/ss_live/skill_phys.json"),
    ("真发布 (DDS)", "tools/dds/ss_daemon.py → pub_skills()"),
    ("信号分析窗口取信号", "tools/gui/canoe_graphic.py → HOST_SOURCES + HostJsonSource.run"),
    ("场景色标", "tools/sig_scene_tags.py → tag()"),
    ("物理包络唯一依据 (改数用 CLI)", "config/calib/zmax_skill_physics.json ← tools/skill_physics_calib.py"),
    ("判据 (26 条全链)", "tools/verify_skill_topics.py"),
]


def build() -> str:
    from lerobot.dataspace import topics as T
    stages = {}
    for c in ("SK01", "SK02", "SK03", "SK04", "SK05", "SK06", "SK07", "SK08"):
        stages[c] = "—"
    try:
        import importlib.util as iu
        p = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "skills", "atomic_skills.py")
        spec = iu.spec_from_file_location("zmax_atomic_skills_doc", p)
        m = iu.module_from_spec(spec)
        spec.loader.exec_module(m)
        # 插拔链先写, 摆盘链不覆盖 (SK07 两条链同号: 插入 ↔ 放入) ⇒ 主名取插拔链, 摆盘支单列说明
        for c in m.SKILLS:
            stages[c.code] = c.stage
        for c in m.SKILLS_TRAY:
            stages.setdefault(c.code, c.stage)
        if "SK07" in stages and any(c.stage == "放入" for c in m.SKILLS_TRAY):
            stages["SK07"] = "插入 (摆盘链同号 = 放入)"
    except Exception:                                                      # noqa: BLE001
        pass                                                               # 技能库读不到就留 "—" (不猜)

    L = []
    A = L.append
    A("# 原子技能 topic 清单 (所有场景)")
    A("")
    A("老倪 2026-10-15: 「所有的原子技能, 例如 接近, 对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有对应的信号;")
    A("你来给出所有场景的原子技能 topic, 我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、角度等物理值;")
    A("要实际发出来; 所有原子技能, 而且 vscode 要有对应代码。」")
    A("")
    A("**本文件是生成物**: `./gui-venv311/bin/python tools/topics_list_skill.py --md` 从唯一依据")
    A("`src/lerobot/dataspace/topics.py`(话题) + `.../skills/atomic_skills.py`(技能号↔阶段) 渲染 —— 别手改, 改了会被覆盖。")
    A("")
    A("## 一、已上线: 真发布 + 有实测值 + 信号分析可见 (8 个原子技能)")
    A("")
    A("| topic | 技能 | 阶段 | 场景 | 类型 | 频率 | 遥测档 |")
    A("|---|---|---|---|---|---|---|")
    for i in range(1, 9):
        k = "skill_sk%02d" % i
        e = T.TOPICS.get(k) or {}
        code = "SK%02d" % i
        A("| `zmax/%s` | %s | %s | %s | `%s` | %.0f Hz | %s |" % (
            k, code, stages.get(code, "—"), SCENE.get(code, "—"), e.get("type", ""),
            float(e.get("rate_hz") or 0), "/".join(e.get("modes") or [])))
    A("")
    A("## 二、每个 topic 携带的信号 (信号分析窗口里一行一条; 每技能 18 条)")
    A("")
    A("| 分类 | 信号 | 单位 | 说明 |")
    A("|---|---|---|---|")
    for r in SIG:
        A("| %s | %s | %s | %s |" % r)
    A("")
    A("> 信号分析窗口里的行名 = `<topic>.<SK号> <阶段> · <信号> <单位>`, 例如")
    A("> `skillphys.SK07 插入 · v 速度 mm/s`; 实测曲线与 v_cap/a_max 包络线**同图叠**即\"看到物理模型\"。")
    A("")
    A("## 三、场景 ↔ 技能号")
    A("")
    A("| 场景 | 颜色 | 技能号 | 阶段 | topic |")
    A("|---|---|---|---|---|")
    A("| 插拔场景 TASK-01-FW | 绿 `#2e8b57` | SK01..SK08 | 接近/对位/下降/抓取/抬起/转移/插入/完成 | `zmax/skill_sk01` … `sk08` |")
    A("| 摆盘场景 TASK-06-TRAY | 蓝 `#1f6feb` | SK01..SK08 | 接近/对位/下降/抓取/抬起/转移/**放入**/完成 | 同上 (同号两支: SK07=放入) |")
    A("| AR场景 TASK-07-AOI | 紫 `#8957e5` | — 无技能类 | AOI转移/AOI检测/回程 | 待建 (见第四节) |")
    A("")
    A("## 四、已登记但**没有生产者**的 5 段 (诚实标注, 不假装有数)")
    A("")
    A("引擎 13 段 (cognition.STAGES) 里这 5 段在技能库里**没有类** ⇒ 目前没有实测产出;")
    A("v/a/s 包络在标定唯一依据里是齐的, 补生产者的做法 = 与 SK01..08 同一条链接进派发服务。")
    A("")
    A("| topic | 段 | 场景 | 状态 |")
    A("|---|---|---|---|")
    NAMEOF = {"stage_pullout": "拔出", "stage_aoi_move": "AOI转移", "stage_aoi_inspect": "AOI检测",
              "stage_return": "回程", "stage_place": "放下"}
    SC = {"stage_pullout": "插拔场景(绿)", "stage_aoi_move": "AR场景(紫)", "stage_aoi_inspect": "AR场景(紫)",
          "stage_return": "AR场景(紫)", "stage_place": "摆盘场景(蓝)"}
    for k, nm in NAMEOF.items():
        e = T.TOPICS.get(k) or {}
        A("| `zmax/%s` | %s | %s | %s |" % (k, nm, SC[k], e.get("status", "")))
    A("")
    A("## 五、代码位置 (VSCode 直接打开; 绝对路径见下)")
    A("")
    A("| 作用 | 仓库相对路径 |")
    A("|---|---|")
    for a, b in CODE:
        A("| %s | `%s` |" % (a, b))
    A("")
    A("仓库根 = `/home/ubuntu/zmax` (e.g. `/home/ubuntu/zmax/tools/dds/ss_daemon.py`)。")
    A("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true", help="写入 docs/design/atomic_skill_topics_20261015.md")
    a = ap.parse_args()
    txt = build()
    if a.md:
        os.makedirs(os.path.dirname(DOC), exist_ok=True)
        with open(DOC, "w", encoding="utf-8") as fh:
            fh.write(txt)
        print("写出 %s (%d 行)" % (DOC, txt.count("\n")))
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
