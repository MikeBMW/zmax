# 新 DDS 话题要进「实时监控 · 信号分析」——五处登记清单 (少一处就静默收不到)

实测代价: 加 `zmax/ss_action_chunk` 时, 只改守护的 MODE_TOPICS ⇒ 订阅端 `KeyError` / 收到 0 帧 / 探针 trace.jsonl 0 行,
而且**不报错** (只在服务日志里一句 `⚠️ 发 X 失败`, 常被别的刷屏淹没)。必须**五处**一致:

1. `dds/ss_types.py` —— 新 `@dataclass ...(IdlStruct, typename="zmax::X")`; 数组字段用 `field(default_factory=list)`。
2. `dds/zmax_node.py` —— ① `_SS_TOPICS` 映射 `"ss_x": SSX`; ② qos 表 `"ss_x": "state"`(latch, 一段时间内有效) 或 `"beat"`(逐帧高频)。
   漏这处 ⇒ `Node.take("ss_x")` 报 `KeyError: 'ss_x'`。
3. `src/lerobot/dataspace/topics.py` —— ① `TOPICS` 登记 (type/producer/consumers/modes/key_fields/quality/provenance); ② `MODE_TOPICS` 三档 (diag/calib/test; prod 恒 `[]`)。
4. `tools/gui/zmax_telemetry.py::MODE_TOPICS` —— 控制台侧同口径副本 (探针的 `topics_for_mode` 读的是 `src/lerobot/dataspace/topics.py`, 别只改一处)。
5. `tools/dds/ss_daemon.py` —— ① `MODE_TOPICS` 三档; ② `pub_xxx()`; ③ 挂到发布线程并 `if allowed("ss_x")`; ④ `_STALE_S` 陈旧阈值。

改完 `sudo systemctl restart zmax-dds-ss.service zmax-dataspaces-probe.service` (两端都重启), 再核:

```bash
# 用项目自己的 Node, **别用裸 cyclonedds DomainParticipant(0)** (域名不同 ⇒ 永远 0 帧, 会误判成没发)
cd ~/zmax && ./gui-venv311/bin/python -c "
import sys; sys.path.insert(0,'dds')
from zmax_node import Node
n=Node('probe'); print(len(n.take('ss_x', timeout=2.0)))"
tail -c 300000 zmax_data/dataspace/trace.jsonl | grep -c ss_x
```

## 载荷 digest 的 400 字上限 (长数组型话题)

`src/lerobot/dataspace/probe.py::_digest_for` 每话题给一行摘要; 通用兜底 `body[:180]`, 自定义分支常写 `[:400]`。
长数组话题 (动作块/姿态序列) 会正好被**切在 JSON 中间 ⇒ 非法 JSON ⇒ 下游连前面的数都抠不全** (页面靠正则逐对抠数才勉强有值)。
对策: 这类话题放宽上限 (块用 760), 且**数值在前、名字串放最后**。

## 数值字段别用 `or -1.0` 兜底

`x = float(d.get(k) or -1.0)` —— `0.0` 是**合法值** (块退化时转角=0), 会被 falsy 吃掉变成 "没值 -1.0", 界面上像坏了。
改 `(-1.0 if d.get(k) is None else float(d[k]))`。

## 宿主源选择 (界面要极简)

- 嵌套数组型真源直接当 `HOST_SOURCES` ⇒ 被展开成一大片生数 (`chunk.chunk.0.0/0.1/…` 48 行)。
  改吃"平铺语义键": 让上游 (`ss_fw_trace_pub.py`) 把语义键搬进 `engine_trace.json` ⇒ 页面得到 `sseng.chunk.块步0_mps` 这种可读行。
- 平铺快照 (如 `skill_latest.json`) 适合当宿主源: 一行一技能 (`skill.下降_mps` / `skill.下降_拍`)。
- 文字行 (QLabel) 直接读真源文件, 每次刷新**比对文本再 setText** (老倪要看确切的名字/状态, 不是只有数字)。
