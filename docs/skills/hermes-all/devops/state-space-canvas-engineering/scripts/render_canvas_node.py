# -*- coding: utf-8 -*-
"""离屏渲染画布上的任意一个节点 → PNG (验证节点上画的东西/开关/徽标真的画出来了)。

用法 (仓根执行):
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python scripts/render_canvas_node.py \\
      --id n_moveit --set bridge_vff=true --out /tmp/node.png [--set key=value ...]

为什么要这个脚本:
  · 节点开关/徽标这类改动用鼠标验不了(也不该去点用户正在看的窗口) ⇒ 用真控件离屏画一张,
    再 tesseract 认字, 就是"画出来了"的硬证据。
  🔴 stub scene_ref 必须提供 links/nodes/_items/_flow_path: `_paint_core` 会遍历
    `self.scene_ref.links`, 返回 None ⇒ TypeError: 'NoneType' object is not iterable
    (看着像"节点根本画不出来", 实际只是 stub 缺属性)。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QRectF                                # noqa: E402
from PyQt5.QtGui import QImage, QPainter                       # noqa: E402
from PyQt5.QtWidgets import QApplication, QStyleOptionGraphicsItem  # noqa: E402

app = QApplication([])
import simulink_module as SM                                    # noqa: E402

CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")


class StubMod:
    """paint 会回问 module 的画布状态; 这些属性必须是真的空容器, 不能是 None。"""

    _mw_state = {}
    _cap_level = "L2"
    _data_source = "metaworld"
    _items = {}
    _flow_path = None
    links: list = []
    nodes: dict = {}

    def __getattr__(self, k):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="画布节点 id (如 n_moveit); 给 --name 关键字也行")
    ap.add_argument("--name", default="", help="按名字子串找 (节点 id 在 GUI 里会被重编, 推荐带上)")
    ap.add_argument("--set", action="append", default=[], metavar="K=V", help="覆盖节点 params, 值 true/false 会转 bool")
    ap.add_argument("--out", default="/tmp/canvas_node.png")
    ap.add_argument("--scale", type=float, default=2.0)
    a = ap.parse_args()

    node = None
    with open(CANVAS, encoding="utf-8") as f:
        for n in (json.load(f).get("nodes") or []):
            if n.get("id") == a.id or (a.name and a.name in str(n.get("name") or "")):
                node = dict(n)
                break
    if node is None:
        sys.exit("没找到节点: id=%s name~%s" % (a.id, a.name))

    node.setdefault("params", {})
    for kv in a.set:
        k, _, v = kv.partition("=")
        node["params"][k] = (v.lower() in ("1", "true", "yes", "on")) if v.lower() in (
            "true", "false", "yes", "no", "on", "off", "1", "0") else v
    for k in ("x", "y"):
        node[k] = 0
    node.setdefault("w", 280)
    node.setdefault("h", 110)

    it = SM.SimNodeItem(node, StubMod())
    w = int((node["w"] + 20) * a.scale)
    h = int((node["h"] + 20) * a.scale)
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0xFF0D1117)
    qp = QPainter(img)
    qp.scale(a.scale, a.scale)
    qp.translate(10, 10)
    it.paint(qp, QStyleOptionGraphicsItem(), None)
    qp.end()
    img.save(a.out)
    print("节点 %s (%s) → %s   params=%s" % (node.get("id"), node.get("name"), a.out,
                                            {k: node["params"].get(k) for k in a.set and
                                             [kv.partition("=")[0] for kv in a.set]}))
    print("复核: tesseract %s - -l chi_sim+eng --psm 7" % a.out)


if __name__ == "__main__":
    main()
