# -*- coding: utf-8 -*-
"""从状态空间画布 JSON 解析出**节点规格** (NodeSpec)。

真源: ``flows/state_space_obs.json`` (= 工程文件里 canvas 段那一段)
  * 节点: {id, name, type, x, y, w, h, params{...}}
  * 连线: {id, f, t, f_port, t_port, label}

端口规则 (画布里没有显式 ports, 历史遗留):
  * 输入端口 = 所有连向该节点的 ``t_port`` 集合
  * 输出端口 = 所有从该节点出发的 ``f_port`` 集合
  * 没有任何连线 → 按类型给默认 (纯输出节点 out1 / 纯输入节点 in1 / 孤立节点 in1,out1)
这样"输入输出"完全由**工程 JSON 的连线**决定 —— 换工程 = 换端口, 不用改代码。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# 会真的动设备/需要授权的节点 —— 数据面照跑, 但 **不自动执行实现** (红线)
_ACT_HINTS = ("执行器", "下发", "MoveIt", "夹爪", "机械臂", "运动", "动作块", "安全执行边界", "授权")
_VIEW_HINTS = ("视图", "视频", "可视化", "监视", "大屏", "历史", "曲线", "3D")


def find_canvas(explicit=None):
    """找画布真源 (软链按 realpath 走, 与 engineering.flows 同源)。"""
    if explicit:
        return os.path.abspath(explicit)
    try:
        from lerobot.engineering import flows                       # noqa: PLC0415
        return os.path.realpath(flows.canvas_path())
    except Exception:                                               # noqa: BLE001
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        return os.path.realpath(os.path.join(root, "flows", "state_space_obs.json"))


_EN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_names.json")
_EN_CACHE = {"mtime": None, "map": {}}


def en_names():
    """节点 id → 英文单词 (真源 node_names.json, 手改后不需要改代码)。"""
    try:
        _m = os.path.getmtime(_EN_PATH)
        if _EN_CACHE["mtime"] != _m:
            with open(_EN_PATH, encoding="utf-8") as _f:
                _d = json.load(_f)
            _EN_CACHE["map"] = {k: v for k, v in _d.items()
                                if not k.startswith("_") and isinstance(v, str) and v}
            _EN_CACHE["mtime"] = _m
    except Exception:                                                           # noqa: BLE001
        pass
    return _EN_CACHE["map"]


@dataclass
class NodeSpec:
    id: str
    name: str
    type: str
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    port_labels: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    impl_key: str = ""
    source: str = ""
    source_symbol: str = ""
    exec_mode: str = "pure"          # pure=纯计算 | act=会动设备 | view=展示
    x: int = 0
    y: int = 0

    @property
    def layer(self):
        m = re.search(r"\bL([2-5])\b", self.name or "")
        if m:
            return "L" + m.group(1)
        return (self.params or {}).get("cap_level") or ""

    @property
    def module_name(self):
        """生成物模块名 = **一个英文单词**, 真源 node_names.json。

        🎯 2026-10-17 老倪: 「n_n1792213069066aaw.py 怎么能出现这个文件? 用英文的文件名, 改」
          ⇒ 永远不许出现 id 当文件名。解析顺序:
             ① node_names.json 里登记的 id → 单词
             ② 同名节点已登记过 → 用那个单词 (草稿里重复拖进来的同名节点)
             ③ 名字里的英文字母 (MoveIt / VLM / YOLO …)
             ④ 名字里的中文关键词 → 英文单词 (node_names.json 的 _词汇 表)
             ⑤ 兜底 node_<4位哈希> (仍是英文, 且稳定)
        """
        w = resolve_word(self.id, self.name)
        return "n_" + w

    @property
    def module_name_by_id(self):
        """老命名 (按 id) —— 只用于清理/兼容旧文件。"""
        s = re.sub(r"[^0-9a-zA-Z_]", "_", self.id or "node").lower().lstrip("_")
        return s if s.startswith("n_") else "n_" + s

    def manifest(self):
        return {
            "id": self.id, "name": self.name, "type": self.type, "layer": self.layer,
            "inputs": list(self.inputs), "outputs": list(self.outputs),
            "port_labels": dict(self.port_labels), "impl_key": self.impl_key,
            "source": self.source, "source_symbol": self.source_symbol,
            "exec_mode": self.exec_mode, "module": self.module_name,
        }


def _exec_mode(name, params):
    txt = (name or "") + " " + json.dumps(params or {}, ensure_ascii=False)[:400]
    if any(k in txt for k in _ACT_HINTS):
        return "act"
    if any(k in txt for k in _VIEW_HINTS):
        return "view"
    return "pure"


def _port_sort_key(p):
    m = re.search(r"(\d+)$", p or "")
    return (m.group(1).zfill(3) if m else (p or "zz"))


def parse_canvas(canvas_path=None):
    """→ (specs:list[NodeSpec], links:list[dict], meta:dict)

    canvas_path 既可以是工程 JSON 的路径, 也可以直接给**已加载的 flow dict**
    (GUI 打开工程时手上就是 dict, 不必再落盘读一遍)。
    """
    if isinstance(canvas_path, dict):
        d = canvas_path
        path = "<in-memory flow>"
    else:
        path = find_canvas(canvas_path)
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    raw_nodes = [n for n in (d.get("nodes") or [])
                 if n.get("type") not in ("bg", "row_bg")]
    ids = {n.get("id") for n in raw_nodes}
    links = []
    for l in d.get("links") or []:
        f_id, t_id = l.get("f"), l.get("t")
        if f_id in ids and t_id in ids:
            links.append({"id": l.get("id"), "f": f_id, "t": t_id,
                          "f_port": l.get("f_port") or "out1",
                          "t_port": l.get("t_port") or "in1",
                          "label": l.get("label") or ""})
    ins, outs = {}, {}
    for l in links:
        ins.setdefault(l["t"], set()).add(l["t_port"])
        outs.setdefault(l["f"], set()).add(l["f_port"])

    try:                                   # 实现绑定: 注册表 (最长关键字匹配)
        from lerobot.engineering import registry                     # noqa: PLC0415
        match = registry.match_node
    except Exception:                                               # noqa: BLE001
        registry, match = None, (lambda _n: None)

    specs = []
    for n in raw_nodes:
        nid, name = n.get("id"), n.get("name") or n.get("id")
        p = dict(n.get("params") or {})
        i_ports = sorted(ins.get(nid, set()), key=_port_sort_key)
        o_ports = sorted(outs.get(nid, set()), key=_port_sort_key)
        if not i_ports and not o_ports:
            i_ports, o_ports = ["in1"], ["out1"]
        elif not i_ports:
            i_ports = ["in1"]          # 只有出线的源节点也留一个输入口 (可接远端注入)
        elif not o_ports:
            o_ports = ["out1"]         # 只为"端口一致"兜底, 下游不会读它
        key = ""
        try:
            key = match(name) or ""
        except Exception:                                            # noqa: BLE001
            key = ""
        specs.append(NodeSpec(
            id=nid, name=name, type=n.get("type") or "model",
            inputs=i_ports, outputs=o_ports,
            port_labels=dict(p.get("_port_labels") or {}),
            params=p, impl_key=key,
            source=str(p.get("source") or ""),
            source_symbol=str(p.get("source_symbol") or ""),
            exec_mode=_exec_mode(name, p),
            x=int(n.get("x") or 0), y=int(n.get("y") or 0),
        ))
    meta = {
        "canvas": path,
        "nodes": len(specs), "links": len(links),
        "impl_bound": sum(1 for s in specs if s.impl_key),
        "impl_registry_keys": (len(registry.keys()) if registry is not None else 0),
    }
    return specs, links, meta


def spec_by_name_or_id(specs, name_or_id):
    for s in specs:
        if name_or_id in (s.id, s.name):
            return s
    for s in specs:
        if name_or_id and name_or_id in (s.name or ""):
            return s
    return None


def en_glossary():
    """中文关键词 → 英文单词 (node_names.json 的 _词汇 表, 可手改)。"""
    try:
        with open(_EN_PATH, encoding="utf-8") as _f:
            _d = json.load(_f)
        return {k: v for k, v in (_d.get("_词汇") or {}).items() if isinstance(v, str) and v}
    except Exception:                                                           # noqa: BLE001
        return {}


def en_names_by_name():
    """节点名 → 单词 (由工程里已登记的 id→word 反推, 让同名新节点复用同一个单词)。"""
    try:
        canvas = find_canvas()
        specs = parse_canvas(canvas)[0] if canvas else []
        m = en_names()
        out = {}
        for sp in specs:
            w = m.get(sp.id)
            if w and sp.name:
                out.setdefault(sp.name.strip(), w)
        return out
    except Exception:                                                          # noqa: BLE001
        return {}


def resolve_word(node_id, node_name):
    """节点 → 一个英文单词 (绝不返回 id / 中文)。"""
    m = en_names()
    w = m.get(node_id or "")
    if w:
        return w.strip().lower()
    w = en_names_by_name().get((node_name or "").strip())
    if w:
        return w.strip().lower()
    _toks = [t for t in re.split(r"[^0-9a-zA-Z]+", node_name or "") if t]
    if _toks:
        _toks.sort(key=len, reverse=True)          # 取最有信息量的那个英文词, 不拼接
        return _toks[0].lower()
    for k, v in en_glossary().items():
        if k in (node_name or ""):
            return str(v).lower()
    import hashlib
    h = hashlib.md5((node_id or node_name or "node").encode()).hexdigest()[:4]
    return "node%s" % h
