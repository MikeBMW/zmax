#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 话题采样器 (Orin 侧常驻, 只读)

用途: 给控制台「📈 实时监控 · CANoe-Graphic 式信号分析」供数 —— 把任意 ROS2 话题的
      **任意数值字段** 展开成可画曲线的信号, 按固定节拍输出一行 JSON。

用法:
  python3 -u zmax_topic_sampler.py discover
      → 输出 {"topics":[{"name":..., "type":..., "fields":["pose.position.x", ...]}]}
  python3 -u zmax_topic_sampler.py watch --rate 20 --topic /robot/tcp_pose --topic /gripper_pos
      → 每行一行 JSON: {"t": <orin_monotonic_sec>, "s": {"<topic>.<field>": v, ...},
                        "age": {"<topic>": 秒}}   age = 最后一次收到该话题消息到现在的秒数

设计要点 (实测踩过的坑):
  * QoS 用 BEST_EFFORT: 最宽松, 能同时收到 RELIABLE 与 BEST_EFFORT 的发布者。
  * 订阅只存"最新值", 打印节拍与话题发布频率解耦 (高频话题不会打爆 ssh 管道)。
  * 展开时跳过图像/点云/字符串等非数值, 固定数组只展开前 N 个元素, 深度限制 3。
  * 需要先 source 工作区 (含自定义 interfaces) 才有正确的消息类型。
"""

import argparse
import json
import sys
import time

SKIP_TYPE_KEYWORDS = ("image", "compressed", "pointcloud", "pointcloud2", "log",
                      "parameterevent", "markerarray", "laserscan", "camera_info_t")
NUMERIC = {"bool": True, "byte": True, "octet": True, "char": True, "wchar": True,
           "short": True, "long": True, "long long": True,
           "unsigned short": True, "unsigned long": True, "unsigned long long": True,
           "int": True, "int8": True, "int16": True, "int32": True, "int64": True,
           "uint": True, "uint8": True, "uint16": True, "uint32": True, "uint64": True,
           "float": True, "float32": True, "float64": True, "double": True,
           "long double": True}
MAX_ARRAY = 16          # 定长数组最多展开多少个元素
MAX_FIELDS_PER_TOPIC = 96
MAX_DEPTH = 3


def _strip_ns(t):
    return t.replace("/msg/", "/").replace("/srv/", "/")


def _resolve_type(t, base_ns=""):
    """把字段类型串解析成 prim / ('array', prim, n) / ('msg', 类)"""
    from rosidl_runtime_py.utilities import get_message
    t = t.strip().replace("\\", "")
    n = None
    if t.endswith("]") and "[" in t:
        t, _, arr = t.rpartition("[")
        try:
            n = int(arr[:-1])
        except ValueError:
            n = None
    if t.startswith("sequence<") and t.endswith(">"):
        inner = t[len("sequence<"):-1].strip()
        ik, ip, _in = _resolve_type(inner, base_ns)
        return ("seq", (ik, ip), n)
    if t in NUMERIC:
        return ("prim", t, n)
    if t == "string" or t == "wstring":
        return ("str", None, n)
    cands = [t]
    if "/" not in t:
        if base_ns:
            cands.insert(0, f"{base_ns}/{t}")
        for pre in ("std_msgs/msg/", "geometry_msgs/msg/", "sensor_msgs/msg/",
                    "builtin_interfaces/msg/", "interfaces/msg/"):
            cands.append(pre + t)
    for c in cands:
        try:
            return ("msg", get_message(c), n)
        except Exception:
            continue
    return ("unknown", None, n)


def expand_fields(type_str, max_depth=MAX_DEPTH):
    """展开一个消息类型的所有数值叶子字段 → [(path, prim_type)]"""
    out = []

    def walk(cls, prefix, depth, base_ns):
        if depth > max_depth or len(out) >= MAX_FIELDS_PER_TOPIC:
            return
        try:
            fields = cls.get_fields_and_field_types()
        except Exception:
            return
        for name, tstr in fields.items():
            if len(out) >= MAX_FIELDS_PER_TOPIC:
                return
            kind, payload, n = _resolve_type(tstr, base_ns)
            path = f"{prefix}{name}"
            if kind == "prim":
                if n is None:
                    out.append((path, payload))
                else:
                    for i in range(min(n, MAX_ARRAY)):
                        out.append((f"{path}[{i}]", payload))
            elif kind == "msg":
                walk(payload, path + ".", depth + 1, base_ns)
            elif kind == "seq":
                ik, ip = payload if isinstance(payload, tuple) else (None, None)
                if ik == "prim":                      # 数值序列: 运行时按实际长度展开
                    out.append((path + "[*]", ip or "float64"))
                elif ik == "msg":
                    pass                             # 消息序列这一版不展开
    walk(type_str, "", 1, "")
    return out


def discover():
    import subprocess
    r = subprocess.run(["ros2", "topic", "list", "-t"], capture_output=True, text=True, timeout=20)
    topics = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or "[" not in line:
            continue
        name, _, rest = line.partition("[")
        name = name.strip()
        typ = rest.rstrip("]").split(",")[0].strip()
        low = (name + typ).lower()
        if any(k in low for k in SKIP_TYPE_KEYWORDS):
            continue
        try:
            from rosidl_runtime_py.utilities import get_message
            cls = get_message(typ)
        except Exception:
            continue
        fields = expand_fields(cls)
        if not fields:
            continue
        topics.append({"name": name, "type": typ,
                       "fields": [f for f, _ in fields],
                       "types": [t for _, t in fields]})
    print(json.dumps({"topics": topics, "ts": time.time()}, ensure_ascii=False), flush=True)


def flatten(cls, msg, prefix, out, depth=0):
    if depth > MAX_DEPTH or len(out) >= MAX_FIELDS_PER_TOPIC:
        return
    for name, tstr in cls.get_fields_and_field_types().items():
        try:
            val = getattr(msg, name)
        except Exception:
            continue
        kind, payload, n = _resolve_type(tstr)
        path = f"{prefix}{name}"
        if kind == "prim":
            if n is None:
                out[path] = val
            else:
                for i in range(min(n, MAX_ARRAY)):
                    try:
                        out[f"{path}[{i}]"] = val[i]
                    except Exception:
                        break
        elif kind == "msg":
            flatten(payload, val, path + ".", out, depth + 1)
        elif kind == "seq":
            ik, ip = payload if isinstance(payload, tuple) else (None, None)
            if ik == "prim":
                for i in range(min(len(val), MAX_ARRAY)):
                    try:
                        out[f"{path}[{i}]"] = val[i]
                    except Exception:
                        break


def watch(args):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
    from rosidl_runtime_py.utilities import get_message

    rclpy.init()
    node = Node("zmax_topic_sampler")
    qos = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                     reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE)
    state = {}     # topic -> (cls, {leaf: val}, last_stamp_mono)

    for spec in args.topic:
        name, _, typ = spec.partition(":")
        name = name.strip()
        try:
            cls = get_message(typ.strip()) if typ.strip() else None
            if cls is None:
                raise RuntimeError("no type")
        except Exception:
            # 未带类型: 从 topic list -t 里找
            import subprocess
            r = subprocess.run(["ros2", "topic", "list", "-t"], capture_output=True, text=True, timeout=15)
            cls = None
            for line in r.stdout.splitlines():
                if line.strip().startswith(name + " ["):
                    t = line.split("[", 1)[1].rstrip("]").split(",")[0].strip()
                    try:
                        cls = get_message(t)
                    except Exception:
                        cls = None
                    break
            if cls is None:
                sys.stderr.write(f"skip {name}: 类型未知\n")
                continue
        state[name] = [cls, {}, 0.0]

        def make_cb(topic_name, cls_):
            def cb(msg):
                d = {}
                try:
                    flatten(cls_, msg, "", d)
                except Exception:
                    return
                st = state.get(topic_name)
                if st is not None:
                    st[1] = d
                    st[2] = time.monotonic()
            return cb
        node.create_subscription(cls, name, make_cb(name, cls), qos)

    period = 1.0 / max(1.0, float(args.rate))
    wall_delay = float(args.delay)
    time.sleep(wall_delay)   # 给订阅一点发现时间

    while True:
        t0 = time.monotonic()
        try:
            rclpy.spin_once(node, timeout_sec=period * 0.5)
        except Exception:
            pass
        now = time.monotonic()
        sig, age = {}, {}
        for topic, (cls, vals, stamp) in state.items():
            age[topic] = round(max(0.0, now - stamp), 3) if stamp else -1.0
            for k, v in vals.items():
                key = f"{topic}.{k}" if not k.startswith(topic) else k
                if isinstance(v, bool):
                    sig[key] = 1.0 if v else 0.0
                elif isinstance(v, (int, float)):
                    sig[key] = float(v)
        sys.stdout.write(json.dumps({"t": round(now, 4), "s": sig, "age": age},
                                    ensure_ascii=False) + "\n")
        sys.stdout.flush()
        rest = period - (time.monotonic() - t0)
        if rest > 0:
            time.sleep(rest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["discover", "watch"])
    ap.add_argument("--topic", action="append", default=[])
    ap.add_argument("--rate", default=20)
    ap.add_argument("--delay", default=1.5, help="启动后先等几秒做发现(避免首包全空)")
    args = ap.parse_args()
    if args.mode == "discover":
        discover()
    else:
        if not args.topic:
            sys.stderr.write("watch 需要至少一个 --topic\n")
            sys.exit(2)
        watch(args)


if __name__ == "__main__":
    main()
