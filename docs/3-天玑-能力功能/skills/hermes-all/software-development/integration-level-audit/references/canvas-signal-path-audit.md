# 画布"连线 ≠ 数据通路"审计法（节点级取证）

用于回答“某节点到底在不在链上 / 它的信号进没进下一个环节 / 那个开关是不是真切换”。
每一步都要落到 `文件:行` 或一次可复现的实测，不接受“图上有线所以通了”。

## 1. 先分清三层接入

| 层 | 怎么查 | 假接入长什么样 |
|---|---|---|
| 画布连线 | 工程 JSON 的 `links`（f/f_port → t/t_port） | 线在图上，但下游实现从不读那个 `ctx[port]` |
| 节点执行 | `zmax_data/ss_live/canvas_loop.json` 的 traces（status/ms/out） | 报“实现执行”但 `out1=None`，或名字分支走错 |
| 真实副作用 | 下游消费点 + 落盘文件 mtime / HTTP 返回值 | 文件停在几天前，接口 `fresh:false` |

三层都过才算“接上了”；只过前两层 = 图纸上的接入。

## 2. 同一个 t_port 挂多条上游 ⇒ last-write-wins，先算谁赢

- 总线 `bus.py` 的 `publish` 是 `self._d[tp] = (value, now)`，后写的覆盖先写的；
  同一 `t_port` 上挂 N 条线时，最终值 = **执行序里最后一个写的那个上游**。
- 实际执行序看 `canvas_loop.json` 的 `traces` 数组顺序（不是画布坐标、也不是连线顺序）。
- 取证话术：报出“第 2 位 ssplan 写 in1 → 第 11 位 n_exec 覆盖 → 第 13 位 ssact 读到的是 n_exec”。
- 结论若为“执行器没吃到某分支”，先怀疑端口复用，改成独立端口（in3…）或让该分支直连目标服务。

## 3. 别信 `PURE`（文件里写的不是运行时）

- 节点文件里 `PURE=False` 只描述“本文件是否直通”；常驻加载默认把 PURE 覆写为 True
  （`src/lerobot/middleware/node.py` 的 `ZMAX_NODE_PURE_ALL`，默认 1）。
- 判据只能用 traces 的 status/ms/out，不要用源码里的 PURE 推断“它没在算”。

## 4. 名字分派会把不相干的节点送进同一支

实现里常见 `if "物理" in name` 这类中文子串分派；节点改名后静默换分支。
新节点接入时，实测它的 out 结构是否等于预期分支（例如 `kind=physical_world` vs `kind=actuator`）。

## 5. 序列化静默丢数据

`[float(x) for x in (gd if isinstance(gd, (list,)) else [])]` 遇到 numpy 数组 ⇒ 输出空列表且不报错。
验收时读真实 out（不是打印值），空数组/`None` 当成失败处理。

## 6. 探针 ≠ 后端

“有 xxx 后端”先看它的 `plan()/run()` 正文：只 `docker images | grep` 或 return `{available:…}` 的都是探针。
汇报必须写：`探针` / `真后端` / `旁路产物（不进执行链）` 三者之一，并给出镜像/容器状态作依据。

## 7. fail-open 闸门：新鲜度看文件 mtime，不看 payload 时间戳

```python
if time.time() - os.path.getmtime(f) > FRESH_S:   # 判活口径
    return None                                   # 不拦 (fail-open)
```

- 造“过期”测试时必须 `os.utime(f, (t, t))` 把 mtime 调旧；只把 JSON 里的 `t` 字段写成旧值**不算过期**
  （写文件那一刻 mtime 就是新的），会得出“闸没生效”的假结论。
- 反过来也要说清：真正的过期意味着“发布者停了”，此时闸松开是设计选择，不是 bug。

## 8. 开关类改动的验收三件套

临时目录 + 环境变量覆盖（`ZMAX_DATA` / 自定 `*_PATH`），跑三态：

1. 开  → 写/放行，产物文件被创建
2. 关  → 不写/拒绝，且**已有产物 mtime 不变**（不是“被空文件覆盖”）
3. 缺失/过期 → 走 fail-open 分支，行为与开一致

真机安全闸另外加一条：急停名必须在闸前面放行（逐个别名实测，别只看白名单常量）。
