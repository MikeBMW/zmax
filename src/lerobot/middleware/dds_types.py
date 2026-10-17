# -*- coding: utf-8 -*-
"""DDS 通用载荷类型 (只在 550B / DDS 后端时被 import —— 其它档不碰 cyclonedds)。

一条话题 = 一个端口信号; 载荷用 JSON 字符串承载 (值域不受 IDL 字段限制),
外层只保留 话题名/时间戳/JSON 三个字段 ⇒ 加信号不用改 IDL、不用重建类型。
"""
from dataclasses import dataclass

from cyclonedds.idl import IdlStruct


@dataclass
class SSNodePort(IdlStruct, typename="zmax::SSNodePort"):
    topic: str = ""      # ss.node.<node_id>.<port>
    ts: float = 0.0      # 发布时刻 (墙钟)
    json: str = "null"   # 值 (JSON 文本)
