# 话题注册表 + 库优先加载 (工程化口径)

## 1. 为什么要落库

话题名 = `"<prefix>.<node_id>.<port>"`, 端口由工程连线推出 (指向节点的 `t_port` = inputs,
从节点出发的 `f_port` = outputs)。**只拼不存**的后果:

- 监控/CI/抓包工具问“这套工程有哪些话题” → 只能把工程跑起来才拿得到;
- 改命名规则/改前缀 → 不知道哪些订阅端会断;
- 排查“订阅端 0 条”时, 双方各拼一次字符串, 拼错了没地方对照。

## 2. 表结构 (SQLite 单文件 = 一套工程)

```
mw_project(project, canvas_sha, canvas_path, built_at, node_n, link_n, topic_n)
mw_node   (project,node_id,name,type,module,layer,exec_mode,impl_key,source,symbol,x,y,params_json)
mw_port   (project,node_id,port,dir,label,dtype)
mw_link   (project,link_id,f,f_port,t,t_port,label)
mw_topic  (project,node_id,port,dir,topic,qos,enabled)   -- 话题真源, 加 topic 索引
```
`project` = 工程文件名去扩展名。qos 字段写档位口径 (如 `reliable/transient_local` 或 `shm`) + 一个
`enabled` 位, 让“同一套节点在低档位不开 DDS”也留痕, 而不是运行时才算。

## 3. 加载路径

```
load_project(source="auto")             # 默认
  ensure_synced(源文件):
    sha256(源文件) == mw_project.canvas_sha ?
      是 → load()            节点/端口/连线全从库读 (meta.source="db")
      否 → parse(源文件) → sync() 回写 → 用源文件结果 (meta.source="json→db")
source="json"   强制按源文件 (对照/调试)
source="db"     只认库, 没有就抛错 (CI 就是要它抛)
```
加载末尾把 `topic_map` 挂到总线上: `{(node,port): topic}`; 发布/订阅查它, 查不到才回落派生式。

## 4. Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 位置参数混用 | `topic_map(path)` 落到 `project` 形参 → 返回空表 (topic_n=None) | 一律关键字 `topic_map(canvas_path=...)` |
| 复用别人的工程库画布表 | 行数对但 `src/dst` 全 NULL, 端口信息不存在 | 自己建 `mw_*` 表, 端口**显式存**一行一口 |
| 只在 sync 时算话题, 运行时还拼 | 改库不生效, 注册表变缓存 | `Node.topic(port)` 必须先查 `topic_map` |
| 没有 sha 守卫 | 改完工程忘了同步 → 用旧图跑新节点 | 每次加载比 sha, 不一致就重解析+回写 |

## 5. CLI 与判据

```bash
python tools/mw_db.py status            # 几套工程 + 是否过期
python tools/mw_db.py sync              # 源文件 → 库 (幂等)
python tools/mw_db.py topics [过滤]
python tools/mw_db.py node <id>
python tools/mw_db.py sql "select dir,count(*) from mw_topic group by dir"
PYTHONPATH=src python tools/verify_mw_db.py     # 7 项
```

判据七项: ①表行数 ②库读回 == 源解析 (逐节点) ③每条话题 == 派生值 ④`source="db"` 能跑一拍
⑤改过的副本 → 判 stale 并回写, 再 load 认库 ⑥`source="json"` 与库节点集合一致
⑦**改库里一行话题名 → 重新 load → 立刻生效**。

⑦ 与 ⑤ 是“库是真源”和“不会跑过期图”的铁证; 其余只证明拷贝没丢字段。
