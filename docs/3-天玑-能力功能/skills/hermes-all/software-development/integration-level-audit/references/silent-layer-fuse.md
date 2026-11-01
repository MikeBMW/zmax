# 静默熔断：档位跑"通"但整层没执行

## 症状
档位/节点级自检返回 `ok: true`、跑了 N 步、有距离指标，看起来通了；实际该层**一次推理都没发生**。
例：引擎 L3（SmolVLA+LEW）3 步全绿，但 `log_counts['l3策略'] == 0`。

## 判据（必须看计数器，不看 ok）
每一层都要有一个**调用计数**，且断言 > 0：
- `log_counts` / `intact_calls` / `yolo_shots` / `mlp真身` / `l5规划`
- GPU 侧旁证：`nvidia-smi` util 与显存峰值（真推理必有非零耗时与显存）
- 计数器为 0 而 ok=true ⇒ 熔断/降级路径吃掉了该层，**判为不通**。

## 典型根因：路径少一级 dirname
`<repo>/src/lerobot/engine/runtime.py` 里 `dirname^3` = `<repo>/src`（不是仓库根）⇒
`from_pretrained` 拿到 `<repo>/src/outputs/train/...` ⇒ 抛
`Repo id must be in the form 'repo_name'` ⇒ 包在 try 里变成 "L3 推理失败(已熔断)"。
判定口径：`__file__` 在 `src/...` 下的文件，到仓库根要 **4** 级 dirname。

## 排查顺序
1. 打印该层落地路径（ckpt / 数据根）与 `os.path.exists`。
2. 只看异常类型：`Repo id must be...` / `No such file` ⇒ 先怀疑路径层级，不怀疑权重。
3. 修完复跑，**必须**再读一次计数器 + 单步耗时，不能只看 rc=0。

## 同类：结构解析不合契约导致"恒值输出"
VLM/检测器回 `bbox=[x1,y1,x2,y2]`，消费端只读 `cx/x + w/bw` ⇒ 框心恒 (0,0)、
下游力矢量恒为常数（实测 -0.566/+0.566）。
判据：输出与输入像素位置**无关**（换个目标物结果不变）就是解析错，不是模型错。
另：多目标时按面积取最大框会选中背景物（托盘/扫码枪）⇒ 必须先按目标标签过滤再取面积。
