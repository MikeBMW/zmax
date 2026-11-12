# 改画布 JSON 的安全做法 (禁止正则切文本)

画布真源是单个 ~133KB JSON(节点 + 连线 + 端口声明 + 布局都在里面)。用正则/文本替换往
`"outputs": [...]` / `"inputs": [...]` 里插行会把文件切坏(引号/逗号/缩进错一处整份不可解析),
而当时 GUI 与画布回路还在跑 ⇒ 一旦写进去就是“真源已损坏”。

## 定式
1. 先备份: `cp <canvas>.json <canvas>.json.bak_$(date +%Y%m%d_%H%M%S)`, 与真源同目录, 出事立刻 `cp` 回。
2. `json.load` → 只改内存结构 → `json.dump(ensure_ascii=False, indent=…)` 写回(格式统一比逐字节保留更安全)。
3. 写后立即 `json.load` 复验, 报三个数: 节点数、连线数、改动条数(前两个必须不变)。
4. 失败就从 `.bak_*` 还原再来, 不要在损坏文件上继续追改。

## 端口声明欠账(常见)
运行时按 link 取口, 节点 `outputs`/`inputs` 声明少了照样跑 ⇒ 属**元数据欠账**, 不是故障。
顺序: 先出清单(哪个节点缺哪个口) → 一个脚本一次批量补(只增不删) → 复验 → 再报。
不要边发现边手切: 几十处手切一轮就会切坏。

出清单用只读脚本一次跑完(不要边看边改), 判据是 0 处缺=补齐:
```python
import json
d = json.load(open('data/database/zmax/sources/canvas/state_space_obs.json'))
nodes = {n['id']: n for n in d['nodes']}
out_miss = [(l.get('f'), l.get('f_port')) for l in d['links']
            if nodes.get(l.get('f')) and l.get('f_port') not in (nodes[l['f']].get('outputs') or [])]
in_miss = [(l.get('t'), l.get('t_port')) for l in d['links']
           if nodes.get(l.get('t')) and nodes[l['t']].get('inputs') and l.get('t_port') not in nodes[l['t']]['inputs']]
print(len(out_miss), out_miss[:10]); print(len(in_miss), in_miss[:10])
```
`inputs: null` 的节点(动态口)要跳过, 否则清单里会混进一堆假欠账。

## 两份拷贝别只改一份
`flows/state_space_obs.json` 与 `data/database/zmax/sources/canvas/state_space_obs.json` 常各存一份;
只改一份就会出现“本机对、刷给别人/别的机器还是旧画布”。改完对一次 md5 两边一致再报完成。

## 生效时机
在跑的回路/控制台用的是**内存里的旧副本**: 改完要重启回路、GUI 重载工程才看得到;
只改文件不重启 = 用户看到界面没变。
