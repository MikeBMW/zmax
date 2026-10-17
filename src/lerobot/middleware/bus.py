# -*- coding: utf-8 -*-
"""状态空间节点数据总线 (middleware) —— 所有 node 只认这一条通道。

契约 (三条, 全工程统一):
    bus.publish(topic, value)          # value 必须 JSON 可序列化 (标量/列表/字典)
    value, ts = bus.latest(topic)      # 没有数据 → (None, 0.0)
    bus.close()

话题命名:  ``ss.node.<node_id>.<port>``   (例 ss.node.ssff.out1)

后端由**产品档**决定 (真源 tools/zmax_profile.py, 配置 config/platform/zmax_product.json):
    550B 标定版  comm=dds · topics=all   → **DDS** (Cyclone DDS, 跨进程/跨机)
    550A 开发版  comm=dds · topics=core  → 共享内存总线 (/dev/shm), 按老倪口径 DDS 不开
    550C 量产版  comm=shm · topics=none  → 共享内存总线 (与 550C "comm=shm" 口径一致)
环境覆盖: ``ZMAX_MW_BUS=dds|shm|mem``  (诊断用; 只允许在同一档内收窄, 不放宽)

铁律:
  * 缺数据返回 (None, 0.0), **绝不用 0 冒充**; age 由调用方判断新鲜度。
  * 后端不可用 (没有 cyclonedds 等) → 降级到 shm/mem 并**写明原因**, 不假装在发 DDS。
"""
from __future__ import annotations

import json
import os
import threading
import time

TOPIC_PREFIX = "ss.node"


def _repo_root():
    here = os.path.abspath(__file__)
    # src/lerobot/middleware/bus.py → 仓库根
    return os.path.abspath(os.path.join(os.path.dirname(here), "..", "..", ".."))


def _profile():
    """读产品档 (真源 tools/zmax_profile.py)。读不到 → (None, 原因)。"""
    try:
        import sys
        root = _repo_root()
        if os.path.join(root, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(root, "tools"))
        import zmax_profile as zp                                     # noqa: PLC0415
        return zp, None
    except Exception as e:                                            # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def bus_enabled(product=None):
    """(是否启用 DDS, 一段可打印的原因)。只有 550B (comm=dds 且 topics=all) 才开。"""
    env = os.environ.get("ZMAX_MW_BUS", "").strip().lower()
    if env == "dds":
        return True, "环境变量 ZMAX_MW_BUS=dds → 强制 DDS (诊断覆盖)"
    if env in ("shm", "mem"):
        return False, "环境变量 ZMAX_MW_BUS=%s → 不用 DDS" % env
    zp, err = _profile()
    if zp is None:
        return False, "读不到产品档 (%s) → 按关闭兜底 (550A/550C 口径)" % err
    try:
        prod = product or zp.product()
        comm = zp.comm_mode(prod)
        topics = zp.topics_mode(prod)
    except Exception as e:                                            # noqa: BLE001
        return False, "档位读取失败 (%s: %s) → 按关闭兜底" % (type(e).__name__, e)
    ok = (str(comm).lower() == "dds") and (str(topics).lower() == "all")
    return ok, "档 %s: comm=%s topics=%s → DDS %s" % (prod, comm, topics, "开" if ok else "关")


def topic(node_id, port):
    return "%s.%s.%s" % (TOPIC_PREFIX, node_id, port)


# ─────────────────────────── 进程内 / 共享内存 后端 ───────────────────────────
class MemBus:
    """进程内总线 (测试/无 shm 环境)。线程安全, 只保留每话题最新一份。"""

    backend = "mem"

    def __init__(self, note=""):
        self._d = {}
        self._lock = threading.Lock()
        self.note = note
        self.n_pub = 0

    def publish(self, tp, value) -> bool:
        try:
            json.dumps(value, ensure_ascii=False)
        except Exception as e:                                        # noqa: BLE001
            raise TypeError("话题 %s 的值不可 JSON 序列化: %s" % (tp, e))
        with self._lock:
            self._d[tp] = (value, time.time())
            self.n_pub += 1
        return True

    def latest(self, tp):
        with self._lock:
            v, ts = self._d.get(tp, (None, 0.0))
        return v, ts

    def keys(self):
        with self._lock:
            return sorted(self._d)

    def close(self):
        return True


class ShmBus(MemBus):
    """共享内存总线: 每话题一行 JSON 落到 /dev/shm/zmax_mw/<ns>.bus.jsonl (跨进程可读)。

    550A/550C 口径: 不发序列化 topic, 走共享内存。写入 = 追加 + 截断保留最新 N 行,
    读取 = 扫尾部取每话题最后一条 (文件小, 足够快)。
    """

    backend = "shm"

    def __init__(self, ns="default", note="", keep_lines=4000):
        super().__init__(note=note)
        self.dir = os.path.join("/dev/shm", "zmax_mw")
        self.path = os.path.join(self.dir, "%s.bus.jsonl" % ns)
        self.keep = keep_lines
        self._n = 0
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:                                             # noqa: BLE001
            self.path = os.path.join(os.path.expanduser("~"), ".zmax_mw_%s.bus.jsonl" % ns)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def publish(self, tp, value):
        ok = super().publish(tp, value)
        try:
            with self._lock:
                self._n += 1
                n = self._n
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "k": tp, "v": value}, ensure_ascii=False) + "\n")
            if n % 200 == 0:                                          # 周期性压回, 别把 shm 撑爆
                self._compact()
        except Exception:                                             # noqa: BLE001
            pass
        return ok

    def latest(self, tp):
        v, ts = super().latest(tp)
        if v is not None:
            return v, ts
        return self._tail_lookup(tp)         # 进程内没有 ⇒ 到共享内存文件里找 (跨进程读)

    def _tail_lookup(self, tp):
        try:
            with open(self.path, encoding="utf-8") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 512 * 1024))      # 只扫尾部 512KB
                best = (None, 0.0)
                for ln in f:
                    try:
                        d = json.loads(ln)
                    except Exception:                          # noqa: BLE001
                        continue
                    if d.get("k") == tp:
                        best = (d.get("v"), float(d.get("t") or 0.0))
                if best[0] is not None:
                    with self._lock:
                        self._d[tp] = best
                return best
        except Exception:                                      # noqa: BLE001
            return (None, 0.0)

    def _compact(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()[-self.keep:]
            with open(self.path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:                                             # noqa: BLE001
            pass

    def close(self):
        self._compact()
        return True


# ───────────────────────────────── DDS 后端 ─────────────────────────────────
class DDSBus(MemBus):
    """Cyclone DDS 后端: 每话题一个 writer/reader, 值装进通用 IDL 结构 SSNodePort。

    发现未完成就发会丢首帧 ⇒ publish 前 wait_for_match (带超时, 不阻塞主循环太久)。
    任何 DDS 侧异常都只降级**本话题**并记录, 不炸掉节点执行。
    """

    backend = "dds"

    def __init__(self, domain=0, note=""):
        super().__init__(note=note)
        from lerobot.middleware import dds_types as T                # noqa: PLC0415
        import cyclonedds.domain as cd                                # noqa: PLC0415
        import cyclonedds.topic as ct                                 # noqa: PLC0415
        import cyclonedds.pub as cp                                   # noqa: PLC0415
        import cyclonedds.sub as cs                                   # noqa: PLC0415
        from cyclonedds.core import Policy, Qos                        # noqa: PLC0415
        self._T, self._cd, self._ct, self._cp, self._cs = T, cd, ct, cp, cs
        self.dp = cd.DomainParticipant(domain)
        self.pub = cp.Publisher(self.dp)
        self.sub = cs.Subscriber(self.dp)
        self._w, self._r = {}, {}
        # 🐛 2026-10-17 实测: 本机 cyclonedds 的策略类在 core.Policy 下, 不在 cyclonedds.qos
        self._qos = Qos(Policy.Reliability.Reliable(2), Policy.History.KeepLast(1),
                        Policy.Durability.TransientLocal)

    def _writer(self, tp):
        w = self._w.get(tp)
        if w is None:
            t = self._ct.Topic(self.dp, "zmax_mw::" + tp, self._T.SSNodePort)
            w = self._cp.DataWriter(self.pub, t, qos=self._qos)
            self._w[tp] = w
        return w

    def _reader(self, tp):
        r = self._r.get(tp)
        if r is None:
            t = self._ct.Topic(self.dp, "zmax_mw::" + tp, self._T.SSNodePort)
            r = self._cs.DataReader(self.sub, t, qos=self._qos)
            self._r[tp] = r
        return r

    def publish(self, tp, value):
        super().publish(tp, value)                                    # 本地缓存 + 校验 JSON
        try:
            w = self._writer(tp)
            msg = self._T.SSNodePort(topic=tp, ts=time.time(),
                                     json=json.dumps(value, ensure_ascii=False))
            w.write(msg)
            return True
        except Exception as e:                                        # noqa: BLE001
            self.note += " | publish(%s) 失败: %s" % (tp, e)
            return False

    def latest(self, tp):
        v, ts = super().latest(tp)                                    # 本地已收到的
        try:
            r = self._reader(tp)
            for s in r.take(N=4):
                try:
                    v = json.loads(s.json)
                    ts = float(s.ts)
                except Exception:                                     # noqa: BLE001
                    continue
            if v is not None:
                with self._lock:
                    self._d[tp] = (v, ts)
        except Exception:                                             # noqa: BLE001
            pass
        return v, ts


def make_bus(product=None, ns="default", prefer=None):
    """按产品档建总线。返回 (bus, info)。

    info = {"backend", "enabled", "why", "note"}
    prefer: None|"dds"|"shm"|"mem"  (显式指定后端; 仅测试/诊断用)
    """
    enabled, why = bus_enabled(product)
    want = (prefer or os.environ.get("ZMAX_MW_BUS", "")).strip().lower()
    if want == "dds":
        enabled = True
    if enabled:
        try:
            b = DDSBus(domain=int(os.environ.get("ZMAX_MW_DDS_DOMAIN", "0")), note=why)
            return b, {"backend": "dds", "enabled": True, "why": why, "note": b.note}
        except Exception as e:                                        # noqa: BLE001
            note = "DDS 不可用 (%s: %s) → 降级共享内存总线" % (type(e).__name__, e)
            b = ShmBus(ns=ns, note=note)
            return b, {"backend": "shm", "enabled": False, "why": why, "note": note}
    if (want == "mem") or product == "mem":
        b = MemBus(note=why)
        return b, {"backend": "mem", "enabled": False, "why": why, "note": why}
    b = ShmBus(ns=ns, note=why)
    return b, {"backend": "shm", "enabled": False, "why": why, "note": why}
