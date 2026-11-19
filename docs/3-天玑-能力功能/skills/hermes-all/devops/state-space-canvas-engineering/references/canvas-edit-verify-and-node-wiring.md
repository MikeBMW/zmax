# 画布改动的「自证没改坏」+ 给节点接一路真源

两件事连着用: 先把改动的**校验口径**定对(否则基线就 FAIL, 改对了也看不出), 再把新能力**挂到节点上**(否则算法在跑、画布上没人知道)。

## 一 · 校验口径: 与备份逐条对比, 不做全量否决

- 这份画布本身就有 ~110 条「端口未声明」(连线的 `f_port` 不在源节点 `outputs` 里, 或 `t_port` 不在目标 `inputs` 里),
  而 GUI **容忍隐式端口**(按连线动态生成) ⇒ 写一个"每条连线端口都必须声明"的校验器, **基线就 FAIL**, 你会误判自己改坏了。
- 定式: 改前 `cp` 一份 `<flow>.bak_<标签>_<ts>`; 校验器同时算「当前」与「最近备份」的错误集, **只报新增**
  (`new = cur − base`); 退出码只认「新增 0 条 + 硬断言全过」。
- 另三条便宜断言: 节点 id 唯一 · 坐标/宽高是 int(画布渲染依赖) · link id 重复要**排除 `None`**(很多老连线没有 id)。
- 改画布的脚本必须**幂等**: 端口已存在不重复 append、连线 id 已存在不重复加 ⇒ 重跑一次就是自我校验。
- 改完先确认 GUI 到底读哪份: 非打包态读 `_repo_root()/flows/<name>`(环境变量 `ZMAX_FLOWS_DIR` 优先),
  冻结态读 `src/…/engineering/flows/<name>`; 仓库里另有 `data/database/.../sources/canvas/` 这类导出副本,
  **节点数/连线数可能不是同一版** —— 别改错文件后宣布"已接线"。

最小校验器骨架:

```python
def collect(path):
    d = json.load(open(path, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    errs, ids = set(), set()
    for l in d["links"]:
        lid = l.get("id")
        if lid is not None:
            if lid in ids: errs.add(("dup_link", lid))
            ids.add(lid)
        f, t = nodes.get(l["f"]), nodes.get(l["t"])
        if f and l.get("f_port") not in (f.get("outputs") or []): errs.add(("f_port", l["f"], l.get("f_port")))
        if t and l.get("t_port") not in (t.get("inputs") or []): errs.add(("t_port", l["t"], l.get("t_port")))
    return nodes, errs
```

## 二 · 给节点接「真源可见」的一路输出

症状: 画布上写着「融合定位建图」, 但真正在跑的重建/训练链路全在 `tools/` 里各跑各的
⇒ 画布上看不到、状态空间里查不到、现场只能问人。

定式四件套(每件都要能被别人只读复核):

1. **单一真源 JSON**: `zmax_data/<域>/<x>_live.json`, 含 `stage / ts / 关键数字 / 帧龄 / 子步骤状态`
   (每个子步骤写 `running|idle|unknown`, 不许留空、不许用默认值冒充实测)。
2. **systemd 常驻**每 30s 刷它, 顺带 append 一份 `*_history.jsonl` 供追溯。
3. **页服务加只读端点** `/api/<域>/<x>` 转发该文件(带 `_served_at`, **不重算**任何数字 —— 两处算法迟早不一致)。
4. **画布**: 节点 `outputs` 追加一个端口 + 一条到状态节点的连线; `params` 写清
   `*_source` / `*_tool` / `*_service` / `*_api` 四个锚点(下次谁都找得到)。

### 四条教训(都是踩出来的)

- 🔴 **先不要把新量塞进固定维度向量**(如 43D obs): 那是下游模型头与 ckpt 的契约, 加维要同步改所有模型。
  走"旁带 out 口"先让状态可见可查、可 curl; 升维单独一件事、单独验。
- 真源里每个数字都要**可复算**: 训练态读**最新**的日志(`ls -t <pattern> | head -1`, 日志名会变, 不写死),
  资产态读产物里的 `train_report.json`, 而不是自己下发的参数。
- 远端不可达时**不许**把状态翻成"空闲": 沿用上一轮结论并标 `stale`。SSH 抖一次就报"训练结束", 比不报更坏。
- **systemd 用 root 起时 `~/.ssh` 是 /root 的** ⇒ 所有远端 ssh 静默失败, 表现为"读不到远端状态"。
  单元里必须 `User=<实际用户>` + `Environment=HOME=/home/<用户>`; 验收看它写出的文件 **mtime 在动**, 不看 `is-active`。

### 时间戳对账

跨机比较 mtime 前先核时钟(`date +%s` 两边各跑一次)。差几百秒无妨, 差几小时会让 `age` 变负数、
把"正在训练"判成"空闲" —— 判活阈值宁可用「连续两轮都在推进」(step 数变大)而不是只看 `age < N`。
