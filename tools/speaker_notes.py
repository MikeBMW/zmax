# -*- coding: utf-8 -*-
"""为总技术手册每一页生成“可照念”的演讲备注

原则：
  1) 一页 3-5 句、70-130 字，念出来 20-30 秒；
  2) 先说这页讲什么，再给一个能被记住的硬结论；
  3) 表格不说“全部内容”，只说“比哪几列、看哪两行”；
  4) 公式页不念符号，只念结论；
  5) 面向产品/技术/市场：数字带口径，判断带理由，不堆形容词。
"""
from __future__ import annotations

import re

PART_TALK = {
    1: ("这台机器到底长什么样、怎么干活、节拍从哪来。",
        "这一篇是硬件与工位的底子，后面所有能力都长在这上面。"),
    2: ("客户买的是哪一级能力，对应哪个型号、什么价格带。",
        "这一篇销售最常翻，选型四问就在这里。"),
    3: ("五层引擎怎么分工，力控、接管、记忆、安全闸各落在哪一层。",
        "这一篇回答“凭什么能做到”。"),
    4: ("七十年里，世界模型这条路是怎么一步步走到今天的。",
        "这一篇讲来路，为下一节的横向对标铺台阶。"),
    5: ("五条主流路线摆在一张桌上，用产线约束去筛，最后落到 H-JEPA 分层。",
        "这一篇是技术判断的核心，也是客户最容易被说服的一篇。"),
    6: ("模型到底贡献了什么，用消融和 A/B 说话。",
        "这一篇是证据篇，不好看的部分我们也留着。"),
    7: ("演练怎么干跑、AR 场景怎么标、进化闭环跑了几轮。",
        "这一篇证明“不上产线也能先验证”。"),
    8: ("单件成本、回本周期、交付四件套与验收七步。",
        "这一篇是老板和采购最关心的账。"),
    9: ("12 个月怎么排、要多少人多少钱、什么条件下该停。",
        "这一篇是立项页，决策点写得很硬。"),
    10: ("公式、口径、证据索引、术语。",
         "这一篇备查，不逐页念，客户问到再翻。"),
}

# 重点页手写备注（按标题前缀匹配，覆盖模板）
OVERRIDES = {
    "世界模型：流派对标":
        "这一篇是整本手册的技术判断核心。前面几篇讲的是我们能干什么，这一篇讲我们为什么这么选。"
        "我会把 NVIDIA、Google、OpenAI、李飞飞、Meta 五条路线放在同一张桌子上，用产线的三条硬约束——延迟、精度、可判定——去筛。"
        "结论先给：我们走 latent 预测加分层，也就是 H-JEPA 这条路。后面每一页都在回答“为什么不是另外四条”。",

    "OpenAI Sora：视频生成":
        "Sora 2024 年初发布，技术上是把视频切成时空 patch，用扩散 Transformer 生成，作者自述目标是“世界模拟器”。"
        "它确实证明了一件事：大规模视频里有可迁移的物理直觉，比如物体恒存、遮挡关系。"
        "但它给不了三样东西：没有动作条件，你没法问“我这样做会怎样”；没有度量一致性，像素对不代表毫米对；生成延迟在秒到分钟级。"
        "所以我们把它放在训练侧造难例，不放控制环。",

    "Sora / 视频生成 vs 产线控制":
        "这张表只有五行，但它就是我们不选生成式的全部理由。"
        "最要命的是第一行：单次前向，生成式是秒到分钟，我们要二十毫秒以内，差十的二次方到十的四次方。"
        "第二行输出形态也不一样，它给视频，我们要的是动作增量加置信度加判据。"
        "所以不是它不好，是它不在我们的时间尺度上。",

    "八维横向对比":
        "这张表是这一篇的核心，横着是六列：Sora、Cosmos、Genie 和 Dreamer、World Labs、JEPA，最后一列是我们。"
        "竖着八个维度，我建议只盯两行：第四行实时性，和最后一行能不能进控制环。"
        "看最后一行：只有 JEPA 那一列写“可”，我们的写“是”，其余四条都是“否”或者“研究级”。"
        "这不是说它们没价值，是说它们的价值在训练侧和场景侧，不在控制环。",

    "为什么选 JEPA":
        "为什么选 JEPA，四条硬理由。"
        "第一，延迟：单次前向四点四毫秒，能塞进二十毫秒的控制拍；生成式要几百毫秒起，物理上进不去。"
        "第二，可判定：latent 预测能挂毫米级判据，还能拿几何真值来对拍。"
        "第三，数据效率：自监督不需要逐帧标注，产线真机数据直接用。"
        "第四，天生可分层：H-JEPA 本来就是层级结构，正好对上我们的五层。最后一条软理由：它不承诺通用智能，只承诺在你这个场景里预测得准。",

    "算一笔延迟账":
        "这一页把账算死。控制拍二十毫秒，一千件每小时对应单件三点六秒，一件里面一百八十拍。"
        "扩散生成一般要二十到五十步去噪，单步在 4060 上二三十毫秒，乘起来四百毫秒起步，等于机械臂已经走完二十拍。"
        "我们的 latent 预测四点四毫秒，每一拍都能算。"
        "所以结论不是生成模型不好，是它的时间尺度比控制环大两个数量级，只能放在环外。",

    "UPH>1000 的账":
        "这一页回答“凭什么敢说一千件每小时”。"
        "一千件每小时就是三点六秒一件，现在是十一点四六八秒，要提三点一九倍。"
        "钱花在哪也写了：对位从五点五秒压到零点八秒，插拔从二点四秒到一点二秒，检测从一点六到零点六，搬运从一点九到一点零。"
        "注意口径：三点六秒是目标值，现在在役还是十一点四六八秒，这一页是规划不是现状。",

    "单一大模型路线为什么到不了":
        "有人会问，为什么不干脆训一个大的。这一页给四个理由。"
        "第一，延迟不可压缩：十亿参数级模型在边缘卡上单次前向三十到两百毫秒，一拍只有二十毫秒。"
        "第二，容量和频率冲突：能做长时规划的一定慢，能进拍的一定小，同一组权重满足不了两个时间尺度。"
        "第三，错误不可定位：单模型出错你不知道是感知、预测还是决策错。"
        "第四，没法局部升级：加个力传感器就要重训。这就是必须分层的工程理由。",

    "五条路线各自的定位":
        "最后收一下：我们不是选了一个阵营，是按时间尺度把五家的能力各取一段。"
        "Sora 取它的难例合成和复盘可视化，Cosmos 取它的仿真造数据，Genie 和 Dreamer 取动作条件和 latent 训练，"
        "World Labs 取 3D 场景底座，JEPA 取架构骨架。"
        "舍掉的是：它们各自进不了控制环的那部分。这叫工程，不叫站队。",

    "V6：把视觉、力、动作":
        "这一页是实证篇的开头，也是最容易被问“模型到底有没有用”的地方。"
        "V6 做的事情是把视觉、力、动作、记忆压进同一张 autograd 图，一个优化器、一次反传。"
        "为什么要一张图？因为分开训会出现“各自指标都还行、合起来不会用”的情况。",

    "干跑：把“要发的信号”":
        "演练的定义很硬：把要发的信号全部算出来、落盘，但一条都不发出去。"
        "这样做的好处是可以在不碰产线的前提下，把整条链路的时序、判据、报文格式全暴露出来。"
        "这一篇后面会看到，正是干跑暴露了对位吃掉一半时间这个真问题。",
}


def _clean(t: str) -> str:
    t = (t or "").replace("\n", " ")
    t = re.sub(r"[①②③④⑤⑥⑦⑧]\s*", "", t)
    t = re.sub(r"[｜|]", "，", t)
    return re.sub(r"\s+", " ", t).strip()


def _clip(t: str, n: int = 40) -> str:
    t = re.sub(r"^[①②③④⑤⑥⑦⑧]\s*", "", _clean(t))
    return t if len(t) <= n else t[:n] + "…"


def _first(t: str, n: int = 56) -> str:
    t = _clean(t)
    m = re.search(r"[。；;]", t)
    if m:
        t = t[:m.start()]
    if len(t) <= n:
        return t.rstrip("与、和，, ")
    cut = t[:n]
    idx = max(cut.rfind(x) for x in "，、：")
    body = cut[:idx] if idx > n * 0.45 else cut
    return body.rstrip("与、和，, ") + "等"


def _lead_name(it) -> str:
    """条目名：取元组首项，截短，去掉尾巴标点"""
    s = _clean(str(it[0])) if isinstance(it, (tuple, list)) else _clean(str(it))
    s = re.sub(r"[，,、：:]$", "", s)
    s = re.sub(r"^[①②③④⑤⑥⑦⑧]\s*", "", s)
    return s if len(s) <= 14 else s[:14]


def _join(names) -> str:
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return "、".join(names[:-1]) + "和" + names[-1]


def note_for(idx: int, part: int, e: dict) -> str:
    k = e.get("k")
    title = _clean(e.get("t") or e.get("title") or "")

    for key, txt in OVERRIDES.items():
        if title.startswith(key):
            return txt

    if k == "cover":
        return ("各位好，今天用大概一个半小时，把这台精细操作机器人讲透。"
                "这本手册是整机方案、技术白皮书、能力分级产品册三本合一的版本，顺序就是决策顺序："
                "先看它能干什么，再看凭什么能干，最后看要花多少钱、怎么验收。"
                "中间任何一页想细看，随时打断我。")

    if k == "section":
        talk, why = PART_TALK.get(part, ("", ""))
        return f"第 {part} 篇，{title}。{talk}{why}这一篇我会讲快一点，重点页停下来多说两句。"

    if k == "quote":
        return ("最后一句话：把能干什么说清楚，再把凭什么说能干举证清楚。"
                "这也是我们做产品、做交付的两个基本动作。谢谢，接下来看大家有什么问题。")

    body = []

    if k == "bigstat":
        stats = e.get("stats") or []
        items = []
        for v, lab in stats[:3]:
            lab = re.sub(r"[（(].*$", "", _clean(str(lab))).strip()
            lab = _first(lab, 12)
            items.append(f"{_clean(str(v))}，{lab}")
        if items:
            body.append("先给三个数：" + "；".join(items) + "。")
        if e.get("note"):
            body.append(_first(e["note"], 60) + "。")

    elif k == "table":
        headers = [str(h) for h in (e.get("headers") or [])]
        rows = e.get("rows") or []
        if headers:
            axis = _join([_clip(h, 13) for h in headers[1:4]])
            body.append(f"这张表横着是{axis}，竖着是几组对照。")
        if len(rows) >= 2:
            body.append(f"建议只盯两行：{_lead_name(rows[0])}，和{_lead_name(rows[-1])}。")
        if e.get("note"):
            body.append(_first(e["note"], 62) + "。")

    elif k in ("bullets", "cards"):
        items = e.get("items") or []
        names = [_lead_name(x) for x in items[:3]]
        if names:
            body.append(f"这页讲{len(names)}件事：{_join(names)}。")
        if items and isinstance(items[0], (tuple, list)):
            body.append(_first(str(items[0][1]), 54) + "。")
        if e.get("note"):
            body.append(_first(e["note"], 52) + "。")

    elif k == "layers":
        rows = e.get("rows") or []
        if rows:
            body.append("从上到下是" + "、".join(_clip(str(r[0]), 10) for r in rows[:4]) + "。")
            body.append(f"最上面一层是{_clip(str(rows[0][0]), 10)}，{_first(str(rows[0][1]), 38).replace('：', '，')}。")
        if e.get("note"):
            body.append(_first(e["note"], 52) + "。")

    elif k == "timeline":
        ev = e.get("events") or []
        if ev:
            body.append(f"时间线上 {len(ev)} 个节点，从{_clean(str(ev[0][0]))}到{_clean(str(ev[-1][0]))}。")
            mid = ev[1] if len(ev) > 1 else ev[0]
            body.append(f"中间这一步是{_clip(str(mid[1]), 14)}，{_first(str(mid[2]), 34).replace('：', '，')}。")
        if e.get("note"):
            body.append(_first(e["note"], 52) + "。")

    elif k == "formula":
        body.append("这一页是推导，符号不用念，只听结论。" if part == 10
                    else "这一页给的是量化关系，会上只念结论。")
        note = e.get("note")
        if note:
            body.append(_first(note, 66) + "。")
        else:
            lines = e.get("lines") or []
            if lines:
                body.append(_first(str(lines[-1]), 56) + "。")

    elif k == "nodeblock":
        body.append(f"方框图：左边 {len(e.get('ins') or [])} 条输入，右边 {len(e.get('outs') or [])} 条输出，中间是这个功能本体。")
        tick = _clean(e.get("tick", ""))
        if tick:
            body.append(_first(tick.replace("节拍角色：", "它在节拍里的位置是，"), 46)
                        .replace("：", "，").rstrip("与、，") + "。")

    elif k == "funcmap":
        rows = e.get("rows") or []
        body.append("功能总图：左边进，中间分层处理，右边出。")
        if rows:
            body.append(f"中间{len(rows)}层，最上面是{_clip(str(rows[0][0]), 12)}。")
        if e.get("note"):
            body.append(_first(e["note"], 48) + "。")

    elif k == "figures":
        caps = [_clip(str(c), 16) for _, c in (e.get("items") or [])][:2]
        body.append("看图，" + ("、".join(caps) if caps else "图上是关键尺寸与姿态") + "。")
        if e.get("note"):
            body.append(_first(e["note"], 48) + "。")

    else:
        body.append("这一页我们先过一遍，细节在后面对应的章节展开。")

    lead = f"这一页讲{_clip(title, 24)}。" if title else ""
    text = lead + "".join(x if x.endswith(("。", "！", "？")) else x + "。" for x in body if x)
    text = re.sub(r"。{2,}", "。", text)

    # 过渡句：每 4 页加一次，避免每页都重复
    if part in (1, 2, 3, 5) and idx % 4 == 0:
        text += "这一条后面还会用到，先记住。"
    return text
