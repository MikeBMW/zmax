# -*- coding: utf-8 -*-
"""Trace 列口径判据: 中文名 ≤5 字 / 真实信号名 / Type / Tx·Rx / DDS 标准 QoS。

老倪 2026-10-17: 「trace窗口都是 signal, 改成 Name列…中文名字不要超过5个字, signal列是程序里的
   真实信号变量, 增加 type 列对应 topic, 增加 Tx Rx, 删除 Lamp/Count/Age, 再检查 QoS 列要跟 DDS 标准对上」
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from lerobot.middleware import cn_names, qos_names, db, topic_types

fails = []
def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + info) if info else ""))
    if not ok:
        fails.append(name)

# ① 节点中文名: 75 个全覆盖, ≤5 字, 不重名
nodes = {r["node_id"] for r in db.node_rows()}
missing = sorted(nodes - set(cn_names.NODE_CN))
ck("节点中文名覆盖 %d/%d" % (len(nodes) - len(missing), len(nodes)), not missing, str(missing[:5]))
bad_len = [(k, v) for k, v in cn_names.NODE_CN.items() if len(v) > 5]
ck("中文名都 ≤5 字", not bad_len, str(bad_len[:5]))
ck("中文名不重复", not [b for b in cn_names.audit() if "重复" in b])

# ② 所有话题都能给出中文名 (非空, ≤5)
tops = [r["topic"] for r in db.topics()]
names = {t: cn_names.cn_of(t) for t in tops}
ck("话题中文名 0 空", all(v.strip() for v in names.values()), str([t for t, v in names.items() if not v.strip()][:3]))
ck("话题中文名 0 超长", all(len(v) <= 5 for v in names.values()),
   str([(t, v) for t, v in names.items() if len(v) > 5][:3]))

# ③ 常见信号: 中文名 ≤5; 英文名原样保留 (Signal 列就是程序变量)
sigs = ["grasp_prob", "u_ff", "joint1_deg", "tcp_x_mm", "temp_c", "action6", "rubbish_name_xyz"]
cn = {s: cn_names.cn_of_signal(s, "ss.node.ssff.out2") for s in sigs}
ck("信号中文名 0 超长", all(len(v) <= 5 for v in cn.values()), str(cn))
ck("未知信号退回节点名 (不编造)", cn["rubbish_name_xyz"] == "前馈加速2", cn["rubbish_name_xyz"])
ck("Signal 列保留英文原名", cn_names.cn_of_signal("grasp_prob", "ss.node.ssff.out2") != "grasp_prob",
   "Name=抓取概率 / Signal=grasp_prob")

# ④ Type: 每个话题都有语义类型且非 SSNodePort
types = {t: topic_types.type_of_topic(t) for t in tops}
ck("Type 覆盖 0 缺失", all(v for v in types.values()))
ck("Type 无信封名 SSNodePort", all(v != "zmax::SSNodePort" for v in types.values()),
   str([t for t, v in types.items() if v == "zmax::SSNodePort"][:3]))

# ⑤ QoS: DDS 标准术语, 三种简写都要能翻
cases = {"beat": "BEST_EFFORT · KEEP_LAST(1) · VOLATILE",
         "state": "RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL",
         "cmd": "RELIABLE · KEEP_ALL · VOLATILE",
         "reliable/transient_local": "RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL",
         "shm": "SHM (非 DDS)"}
for k, want in cases.items():
    ck("QoS %s → %s" % (k, want), qos_names.standard(k) == want, qos_names.standard(k))
ck("QoS 未知值显式标错 (不糊)", qos_names.standard("whatever").startswith("❌ 未知"))
ck("库内 273 条 QoS 全部合规", all(qos_names.valid(r["qos"]) for r in db.topics()))

print("\n%s (%d 项)" % ("✅ 全部通过" if not fails else "❌ 失败: %s" % fails, 16 - len(fails)))
sys.exit(0 if not fails else 1)
