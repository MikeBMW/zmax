#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 DDS 节点封装（Cyclone DDS）—— 三端统一用这一套

话题与 QoS:
  zmax/hw_state    HardwareState  RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL(新加入者能立刻拿到最新值)
  zmax/train_prog  TrainProgress  RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL
  zmax/deploy_cmd  DeployCommand  RELIABLE · KEEP_ALL           (指令不许丢)
  zmax/heartbeat   Heartbeat      BEST_EFFORT · KEEP_LAST(1)    (心跳丢了无所谓)

跨网（ECS 在公网）: 由 CYCLONEDDS_URI 指向 XML 配置, 用**单播 Peers + 固定端口**,
不用多播（公网/跨网段多播不通）。见 dds/cyclonedds_unicast.xml。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cyclonedds.core import Qos, Policy                                   # noqa: E402
from cyclonedds.domain import DomainParticipant                           # noqa: E402
from cyclonedds.pub import DataWriter                                     # noqa: E402
from cyclonedds.sub import DataReader                                     # noqa: E402
from cyclonedds.topic import Topic                                        # noqa: E402

from zmax_types import DeployCommand, HardwareState, Heartbeat, TrainProgress   # noqa: E402

# ── 状态空间全局数据空间（老倪 2026-09-25: 状态空间工程用 DDS）──
try:
    from ss_types import (SSState, SSAction, SSInfer, SSCanvasNode, SSMacro, SSNodes,
                          SSCalib, SSDiag, SSTest, SSPlan, SSEnergy, SSEnergyLayer,
                          SSDrivingTorque, SSConfigNames, SSManifoldStep, SSMetaTask, SSMetaPred)
    _SS_TOPICS = {
        "ss_state": SSState, "ss_action": SSAction, "ss_infer": SSInfer,
        "ss_canvas": SSCanvasNode, "ss_macro": SSMacro, "ss_nodes": SSNodes,
        "ss_calib": SSCalib, "ss_diag": SSDiag, "ss_test": SSTest,
        "ss_plan": SSPlan,          # 🧭 MoveIt plan-only 轨迹镜像 (老倪 2026-09-29)
        "ss_energy": SSEnergy,      # ⚡ 流形引擎能量层 (发动机类比: 功率/转速/扭矩/能量/效率)
        "ss_torque": SSDrivingTorque,  # 🔧 驱动扭矩 T_drive = M·(−∇Φ) (老倪 2026-10-13)
        "ss_cfg_names": SSConfigNames,  # 🧮 主参数节点已加载的配置名称 (老倪 2026-10-14, 5s, 字符串)
        "ss_engine": SSManifoldStep,   # 🧮 流形引擎每周期输出 (常驻回路, 老倪 2026-10-14)
        "ss_meta_task": SSMetaTask,    # 🧾 根据任务输出的元任务清单 (主参数节点出口, 5s, 老倪 2026-10-14)
        "ss_meta_pred": SSMetaPred,    # 🧾 元任务预测值 (输入=流形引擎驱动扭矩; 信号分析可见, 老倪 2026-10-14)
    }
except Exception:                                                               # noqa: BLE001
    _SS_TOPICS = {}
    # 连线数据总线（DDS 连线 topic）
try:
    from dds_link_bus import LinkValue as _LV
    _LINK_TOPIC = {"link_value": _LV}
except Exception:                                                               # noqa: BLE001
    _LINK_TOPIC = {}

TOPICS = {
    "hw_state": HardwareState,
    "train_prog": TrainProgress,
    "deploy_cmd": DeployCommand,
    "heartbeat": Heartbeat,
    **(_SS_TOPICS if _SS_TOPICS else {}),
    **(_LINK_TOPIC if _LINK_TOPIC else {}),
}
QOS_CLASS = {
    "hw_state": "state", "train_prog": "state", "deploy_cmd": "cmd", "heartbeat": "beat",
    # 状态空间: 高频感知/动作/连线 → best（低延迟, 丢帧无妨）; 状态/画布/训练 → state（latch）
    "link_value": "beat", "ss_action": "beat", "ss_infer": "beat", "ss_state": "beat",
    "ss_canvas": "state", "ss_macro": "state", "ss_nodes": "state",
    "ss_calib": "state", "ss_diag": "beat", "ss_test": "state",
    "ss_energy": "state",   # ⚡ 每轮聚合量 → state(latch, 新订阅者立刻拿到最新一轮)
    # 🔧 驱动扭矩 T_drive=M·(−∇Φ): 高频逐帧驱动力 (10Hz 实测数据通道) → beat (低延迟, 丢帧无妨)
    "ss_torque": "beat",
    # 🧮 配置名称清单是"一段时间内有效"的状态型产物 → state(latch): 新开的窗口立刻拿到最新一份
    "ss_cfg_names": "state",
    # 🧮 流形引擎常驻回路每周期输出 (高频逐帧) → beat (低延迟, 丢帧无妨; 帧龄由载荷 ts 判)
    "ss_engine": "beat",
    "ss_meta_task": "state",
    "ss_meta_pred": "state",   # 预测是"一段时间内有效"的状态型产物 → latch
    # 规划是"状态型"产物(一段时间内有效) → latch: 新开的独立窗口立刻拿到最新一条轨迹
    "ss_plan": "state",
}


def _p(cls, *a):
    """CycloneDDS 11 的 Policy 有的可调用(Reliable(n)/KeepLast(n)) 有的不可(BestEffort/TransientLocal)
    → 统一兜底: 能调就调, 不能就原样用"""
    try:
        return cls(*a)
    except TypeError:
        return cls


def qos_for(name):
    kind = QOS_CLASS.get(name, "state")
    if kind == "cmd":
        return Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepAll, 0))
    if kind == "beat":
        return Qos(_p(Policy.Reliability.BestEffort, 0), _p(Policy.History.KeepLast, 1))
    # state: 可靠 + 只留最新 + 新订阅者立刻拿到（DDS 的 latch 语义）
    return Qos(_p(Policy.Reliability.Reliable, 0), _p(Policy.History.KeepLast, 1),
               _p(Policy.Durability.TransientLocal))


class Node:
    """一个 DDS 参与者 + 按需创建的 writer/reader（同一进程可同时收发）"""

    def __init__(self, name, domain=0, config_xml=None):
        # 🔴 2026-10-13 口径(单一配置): **全系统只有一张 DDS 配置**, 任何参与者都不许默认走多播 ——
        #   实测后果: 发布端已改单播(AllowMulticast=false), 而验证器/脚本的订阅端没给配置 ⇒ 仍走多播
        #   ⇒ 双方发现不到对方 ⇒ "DDS 真收 0 条"(torque 判据 ⑨a 连挂), 现场表现为"话题发了但谁都看不见"。
        #   所以: 没显式给配置、也没环境变量时, 自动用工程根这张 (存在且非空才用)。
        if not config_xml and not os.environ.get("CYCLONEDDS_URI"):
            _d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cyclonedds_unicast.xml")
            if os.path.isfile(_d) and os.path.getsize(_d) > 0:
                config_xml = _d
        # 🛡 防呆 (2026-10-13 现场黑灯根因): 「空/缺配置」绝不许静默当"未配置"用 ——
        #   实测: 脚本默认指 dds/cyclonedds_unicast.xml 而该文件当时不存在 ⇒ 这里判假 ⇒ 静默退回
        #   默认多播 ⇒ 多网卡挑错网卡 + 常驻进程 IP 变化不恢复 ⇒ 本机自己都收不到, 数据空间全黑灯。
        #   口径: 要么真读到非空配置, 要么**大声告警**(让人当场看得见), 不许默默降级。
        if config_xml:
            if not os.path.isfile(config_xml):
                print("⚠️ DDS 配置不存在: %s ⇒ 将退回默认多播发现(多网卡下可能收不到)。"
                      "生成: python3 tools/dds/gen_unicast_cfg.py" % config_xml, flush=True)
            elif os.path.getsize(config_xml) == 0:
                print("⚠️ DDS 配置是 0 字节: %s ⇒ 参与者会掉出发现网。"
                      "重生成: python3 tools/dds/gen_unicast_cfg.py" % config_xml, flush=True)
            else:
                os.environ["CYCLONEDDS_URI"] = "file://" + os.path.abspath(config_xml)
        self.name = name
        self.dp = DomainParticipant(domain)
        self._w, self._r = {}, {}

    def pub(self, topic):
        if topic not in self._w:
            t = Topic(self.dp, "zmax/" + topic, TOPICS[topic])
            self._w[topic] = DataWriter(self.dp, t, qos=qos_for(topic))
        return self._w[topic]

    def sub(self, topic):
        if topic not in self._r:
            t = Topic(self.dp, "zmax/" + topic, TOPICS[topic])
            self._r[topic] = DataReader(self.dp, t, qos=qos_for(topic))
        return self._r[topic]

    def send(self, topic, msg):
        self.pub(topic).write(msg)
        return True

    def take(self, topic, timeout=5.0):
        """返回新到的样本列表（非阻塞窗口内轮询）"""
        r = self.sub(topic)
        out, t0 = [], time.time()
        while time.time() - t0 < timeout:
            s = r.take()
            if s:
                out.extend(s)
            else:
                time.sleep(0.1)
        return out

    def wait_for_match(self, topic, n=1, timeout=15.0):
        """等配对（DDS 发现是异步的, 必须等匹配再发, 否则消息会丢给"还没发现"的读者）"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                st = (self._w[topic].get_matched_subscriptions() if topic in self._w
                      else self._r[topic].get_matched_publications())
            except Exception:                                                   # noqa: BLE001
                st = []
            if len(st) >= n:
                return True
            time.sleep(0.2)
        return False


if __name__ == "__main__":
    # 自检: 同一进程内 pub → sub 往返（证明 DDS 栈真通）
    print("=" * 74)
    print("📡 DDS 自检: 本机 pub → sub 往返")
    print("=" * 74)
    n = Node("selftest")
    n.pub("hw_state")
    ok = n.wait_for_match("hw_state", 1, 15)
    print("  ① 发现配对: %s" % ("✅" if ok else "⚠️ 超时"))
    n.send("hw_state", HardwareState(node="4060", role="工作端", backend="cuda",
                                     device_name="RTX 4060 Laptop", ts=time.time(),
                                     util_pct=100.0, mem_used_mb=1629.0, mem_total_mb=8188.0,
                                     temp_c=68.0, power_w=55.0, cpu_cores=32))
    got = n.take("hw_state", 6.0)
    print("  ② 收到 %d 条:" % len(got))
    for m in got:
        print("     %s/%s [%s] %s util=%.0f%% temp=%.0f°C mem=%.0f/%.0fMB" %
              (m.node, m.role, m.backend, m.device_name, m.util_pct, m.temp_c, m.mem_used_mb, m.mem_total_mb))
    print("  🎯 %s" % ("DDS 通信成立 ✅" if got else "未收到 → 需排查 ❌"))
    sys.exit(0 if got else 2)
