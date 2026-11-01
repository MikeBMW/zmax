# 点位/配置值的覆盖识别与还原

## 1. 常见形态: 两套同名数据

| 库 | 谁写 |
|---|---|
| 传授/示教点库(`…/taught_points.json` 类) | 教点工具、脚本 |
| 页面「空间点」库(`…/space_points.json` 类) | 界面「记录/清除」按钮 |

解析时**同名以某一套为准**(常见: 传授库优先); **另一套缺失不报错** ⇒ 静默回落到
"演示学习轨迹点"(逐次运动自动攒的点) ⇒ 落点变成"某个历史时刻恰好在那里的位姿"。
两条都要看, 别只 grep 一个文件就下结论。

## 2. 症状 → 判据

- 现场说"这个点不是我写的点" ⇒ 查该条目的 `recorded_at` 与值:
  - `recorded_at` 很近, 且值与**当时**的真值文件逐位相同 ⇒ **被覆盖式写入**过(写的是当时状态, 不是人设的值)。
  - 名字在库里但落点等于"当时设备在哪" ⇒ 首选库被清空, 走了回落路径。
- 别用"看着差不多"当判据; **数字对不上就是被换过**, 拿数字说话。

## 3. 审计与备份(还原靠它们)

- `…/<store>_removed.jsonl` 类审计流水 —— 每次清除追加一行:
  `{ts, ts_str, name, removed:{pos/quat/值, desc, recorded_at, source, n_samples, spread_*}, by, backup}`
- `/tmp/<store>.cleared_<name>_<mmdd_HHMMSS>.json` —— 清除前的整库快照。
- 库自身的历史 `*.bak*`(可能更早, 用来交叉验证)。

## 4. 每个名字取"覆盖前最后一次"的原件(可跑)

```python
import json, os
AUD = os.path.expanduser("~/<store>_removed.jsonl")
rows = [json.loads(l) for l in open(AUD, encoding="utf-8") if l.strip()]
best = {}
for r in rows:
    nm, rm = r.get("name"), (r.get("removed") or {})
    if not nm or not rm.get("pos"):
        continue
    if nm not in best or str(rm.get("recorded_at") or "") > str(best[nm].get("recorded_at") or ""):
        best[nm] = rm
for k, v in sorted(best.items()):
    print("%-8s 值=%s 原件记录于 %s" % (k, [round(float(x), 4) for x in v["pos"]], v.get("recorded_at")))
```

写回流程: **先把将要写回的值列给现场确认**(不要自己挑一套他没要的) → 备份现库 → 写回 → 回读校验
→ 发一次 **dry(不下发)** 指令, 核对目标值与写回值逐位一致。

## 5. 纪律

- **现场正在手改这份数据(清+重记)时不要插手** —— 只报证据 + 给"可一键还原"选项, 由他选。
- 新增"记录/清除"入口时照抄**审计 + 备份两件套**, 否则覆盖不可追溯。
- 回报格式: 原值 / 现值 / 覆盖时间 / 原件在哪个文件 / 能否一键还原 —— 一行一条。
