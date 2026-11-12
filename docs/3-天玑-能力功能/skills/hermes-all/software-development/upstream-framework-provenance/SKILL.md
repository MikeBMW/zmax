---
name: upstream-framework-provenance
description: "Use when 用户问「跟开源项目你改了什么/源码在哪/解释这个文件夹」— 分层定位、只读引用、按层回答。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [code-provenance, third-party, site-packages, vscode, explanation]
    related_skills: [codebase-inspection, integration-level-audit]
---

# 第三方框架溯源：我们改了什么、源码在哪

## When to Use
- 「这个类跟开源项目比，你改什么了？」「源码在哪里？」「解释一下这个文件夹」
- 需要判断某能力是**框架自带**、**训练脚本传参**、还是**我们包装层加的**
- 要回答「能不能改框架」，或排查「升级 pip 后行为变了」

## 铁律一：先定位包，再回答，别凭记忆说"我们没改框架"

```bash
python -c "import <pkg>,os;print(<pkg>.__version__, os.path.dirname(<pkg>.__file__))"
```
装在哪决定了改没改：`site-packages/` 里的是安装产物（一行未改），仓库里另有一份才是 fork。
🔴 项目 venv 常是软链（`~/zmax/gui-venv311 -> external/lerobot-smolvla-lew/gui-venv311`），
回答路径时给**解析后的真实路径**，并顺带说一句软链关系 —— 否则用户在自己目录里找不到。

## 铁律二：答案按三层给，不要按「改了 8 处」平铺

| 层 | 判据 |
|---|---|
| 框架本体 | 在 `site-packages` 里；升级即覆盖 ⇒ 改它等于白改 |
| 训练/评测脚本 | `model.train(...)` / `.predict()` 的直接调用方；只传参、不改库 |
| 包装层 | 仓库里的自有文件：帧源适配、类名映射、几何反投影、证据字段、状态拼装 |

回答句式：**「开源负责 X；我们加的是 Y」**，每处改动配一句它解决了什么实际问题（比列 API 有用得多）。
先给行号定位，再给摘要；用户要的是能点开核对的坐标，不是散文。

## 铁律三：别把框架内部机制说成「我们的改造」

写答案前把每条改动归位：`model.names` 覆写、rot90、RGB→BGR、射线反投影、`meta.gaps` 取证、39D 拼装 —— 这些在包装层；
NMS、letterbox、AMP、数据增强 —— 是框架自带，不算我们的功劳。
要判断某行为是不是我们加的：在仓库里 `search_files` 该符号，只命中 `site-packages` ⇒ 框架自带。

## 铁律四：类别数、版本号这类事实现查权重与包，不抄旧文案

画布/PPT 上的节点描述常是旧文案（实测写着「22 个目标」，权重 `names` 实际只有 2 类）。
回答前跑一遍：`python -c "from ultralytics import YOLO;print(YOLO('w.pt').names)"`，或读 ckpt 的 `names`。
口径不一致时**明说哪个是旧的**，并给出改或不改的后果，别默默按旧的讲。

## 铁律五：要改框架，先拿源码再 `-e`，不动 site-packages

```bash
pip download <pkg>==<ver> --no-deps --no-binary :all:
# 解包后：pip install -e <源码目录>
```
只改一两个函数、又要随包升级跟进时，宁可**在包装层 monkey-patch**，把补丁与动机写在同一文件里。

## 把代码摆到用户眼前：真开编辑器，不要只在回复里贴

用户说「打开 / 你用 vscode 开」时，执行的是**开窗口**这个动作，不是再贴一遍代码：

```bash
code --reuse-window --goto "<绝对路径>:<行号>"      # 定位到类/函数
code --reuse-window --add  "<目录>"                 # 目录加进当前工作区
wmctrl -l | grep -i "visual studio"                 # 回读窗口标题核对该文件真开了
```
- 用 `--reuse-window` 复用用户在用的窗口，别每问一次弹一个新窗口。
- 开完在回复里给**下一步该点哪**（文件树里哪个目录、按什么顺序读哪几行），窗口标题变了才算真开。
- site-packages 的文件是只读产物：告诉用户「可以看、可以临时改来验证，但升级会覆盖」，改法见铁律五。

## 框架解剖怎么写（用户说「解释这个文件夹」）

按「运行层 / 网络层 / 工具层 / 配置层 / 附录」讲，每个目录一句职责 + 体量（py 文件数、行数），
最后收一句**我们实际经过哪几个文件**，并点明哪些目录在推理链上完全不参与（solutions / trackers / export）。
体量用现算的，不估：`for d in */; do echo $d $(find $d -name '*.py' | wc -l); done`。
具体到 ultralytics 8.x 的逐目录地图与关键行号见 `references/ultralytics-package-map.md`。

## 坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 拿 `len(pr.slides)` 式的「当前对象数」当事实 | 报告里的页码/序号全偏（构建顺序影响） | 事实一律取「本册起点 + 偏移」或直接读实例属性，别用容器长度代替语义序号 |
| 只列 diff 不讲机制 | 用户追问「为什么改」时答不上 | 每处改动写「原实现的错法 → 现象 → 现做法」，一行 |
| 说「框架一行没改」却没核实 | 仓库里藏着一份 fork 或本地 patch 文件 | `search_files` 包名 + 看 import 路径是否指向本地目录 |

## 支持文件
- `references/ultralytics-package-map.md` —— ultralytics 8.x 安装包的目录职责、推理链关键行号、`pip download` 取源码的口径。
