#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_edit.py 单元测试 —— 在**沙箱副本**上真跑 (env 重定向, 绝不碰在役文件)。

    python3 tools/tests/test_scene_edit.py       # 或  python3 -m unittest ...

覆盖: 四类实体增删改 + 显隐 + 围栏校验(含非法拒绝) + 轨迹点名引用 + set 命令 +
      不破坏不认识的其他键 + 回滚/原子写契约。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
REAL_SCENE = REPO / "data" / "scene"
REAL_SP = REPO / "data" / "skills" / "l2_atomic" / "space_points.json"

SANDBOX = Path(tempfile.mkdtemp(prefix="scene_edit_sbx_"))
SB_SCENE = SANDBOX / "data" / "scene"
SB_SP = SANDBOX / "data" / "skills" / "l2_atomic" / "space_points.json"
SB_SCENE.mkdir(parents=True)
SB_SP.parent.mkdir(parents=True)
for f in ("objects3d.json", "overlay_spec.json", "traj_display.json"):
    shutil.copy2(REAL_SCENE / f, SB_SCENE / f)
shutil.copy2(REAL_SP, SB_SP)

os.environ["ZMAX_REPO"] = str(SANDBOX)
os.environ["ZMAX_SCENE_DIR"] = str(SB_SCENE)
os.environ["ZMAX_SPACE_POINTS"] = str(SB_SP)
sys.path.insert(0, str(REPO / "tools"))
import scene_edit as SE   # noqa: E402


def run(args):
    """跑一条命令, 返回 (exit, stdout 文本, 若 --json 则解析出的 dict)。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = SE.main(args)
    out = buf.getvalue()
    obj = None
    if "--json" in args:
        try:
            obj = json.loads(out.strip().splitlines()[-1])
        except Exception:
            try:
                obj = json.loads(out)
            except Exception:
                obj = None
    return rc, out, obj


class TestSceneEdit(unittest.TestCase):
    def test_00_files_exist(self):
        rc, out, j = run(["path", "--json"])
        self.assertEqual(rc, 0)
        for k in ("objects3d.json", "overlay_spec.json", "traj_display.json"):
            self.assertIn(k, j)
        self.assertTrue(Path(j["objects3d.json"]).exists())

    def test_01_list_json_shape(self):
        rc, out, j = run(["list", "--json"])
        self.assertEqual(rc, 0)
        for k in ("ok", "generated_at", "objects", "markers", "fences", "trajectories", "visibility"):
            self.assertIn(k, j)
        self.assertIn("deleted", j["visibility"])
        self.assertIn("traj_show", j["visibility"])
        self.assertGreaterEqual(len(j["objects"]), 1)

    def test_02_add_marker_and_unknown_keys_preserved(self):
        before = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        before_keys = set(before.keys())
        rc, out, j = run(["add", "--kind", "markers", "--json", "--data",
                          json.dumps({"name": "工位A", "type": "工位", "pos": [0.5, 0.2, 0.1],
                                      "desc": "测试"}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["ok"])
        self.assertTrue(j["readback_ok"])
        self.assertIn("overlay_spec.json:markers", j["changed_keys"])
        self.assertTrue(j["backup"] and Path(j["backup"]).exists())
        mid = j["entity"]["id"]
        after = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        # 不认识的其他键一个都不能少、内容不能变
        for k in before_keys:
            self.assertIn(k, after, "原键丢失: %s" % k)
            if k not in ("markers", "fences", "trajectories", "deleted", "ts", "updated_at"):
                self.assertEqual(before[k], after[k], "原键内容被改: %s" % k)
        self.assertIn("mode", after)
        self.assertIn("cameras", after)
        self.assertIn("l5live", after)
        return mid

    def test_03_update_and_rm_marker(self):
        rc, out, j = run(["add", "--kind", "markers", "--json", "--data",
                          json.dumps({"id": "mk_test3", "name": "临时", "type": "检查点",
                                      "pos": [0.1, 0.1, 0.1]}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        rc, out, j = run(["update", "--kind", "markers", "--id", "mk_test3", "--json",
                          "--data", json.dumps({"name": "临时改名", "pos": [0.2, 0.2, 0.2]}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["readback_ok"])
        rc, out, j = run(["list", "--json"])
        m = [x for x in j["markers"] if x.get("id") == "mk_test3"][0]
        self.assertEqual(m["name"], "临时改名")
        self.assertEqual(m["pos"], [0.2, 0.2, 0.2])
        rc, out, j = run(["rm", "--kind", "markers", "--id", "mk_test3", "--json"])
        self.assertEqual(rc, 0, out)
        rc, out, j = run(["list", "--json"])
        self.assertEqual([x for x in j["markers"] if x.get("id") == "mk_test3"], [])

    def test_04_hide_show_object(self):
        obj = run(["list", "--json"])[2]["objects"][0]["name"]
        rc, out, j = run(["hide", "--kind", "objects", "--name", obj, "--json"])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["readback_ok"])
        self.assertIn("sim|%s" % obj, j["visibility"]["deleted"])
        ov = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        self.assertIn("sim|%s" % obj, ov["deleted"].get("arm", []))
        rc, out, j = run(["show", "--kind", "objects", "--name", obj, "--json"])
        self.assertEqual(rc, 0, out)
        ov = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        self.assertNotIn("sim|%s" % obj, ov["deleted"].get("arm", []))
        # 原有 deleted 条目不能被刷掉
        self.assertIn("arm", ov["deleted"])

    def test_05_box_fence(self):
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"id": "fn_box", "name": "安全箱", "kind": "box",
                                      "shape": {"center": [0.5, 0.3, 0.15], "size": [0.4, 0.4, 0.3]},
                                      "desc": "测试"}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["readback_ok"])

    def test_06_polygon_fence_ok(self):
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"id": "fn_poly", "name": "多边形", "kind": "polygon",
                                      "shape": {"points": [[0.4, 0.2], [0.7, 0.2], [0.7, 0.4], [0.4, 0.4]],
                                                "z_min": 0.0, "z_max": 0.5}}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["readback_ok"])

    def test_07_illegal_fences_rejected(self):
        # a) 多边形只有 2 点
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"name": "坏2点", "kind": "polygon",
                                      "shape": {"points": [[0.1, 0.1], [0.2, 0.2]], "z_min": 0, "z_max": 1}},
                                     ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"]); self.assertIn("至少 3", j["msg"])
        # b) z_min >= z_max
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"name": "坏z", "kind": "polygon",
                                      "shape": {"points": [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3]], "z_min": 0.5, "z_max": 0.2}},
                                     ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"]); self.assertIn("z_min", j["msg"])
        # c) 坐标越界 (点超 ±3m)
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"name": "越界", "kind": "polygon",
                                      "shape": {"points": [[5.0, 0.1], [0.3, 0.1], [0.3, 0.3]], "z_min": 0, "z_max": 0.5}},
                                     ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"]); self.assertIn("超出", j["msg"])
        # d) 退化多边形 (共线, 面积 0)
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"name": "退化", "kind": "polygon",
                                      "shape": {"points": [[0, 0], [1, 1], [2, 2]], "z_min": 0, "z_max": 0.5}},
                                     ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"]); self.assertIn("面积", j["msg"])
        # e) box 越界
        rc, out, j = run(["add", "--kind", "fences", "--json", "--data",
                          json.dumps({"name": "坏box", "kind": "box",
                                      "shape": {"center": [2.9, 0, 0], "size": [1, 1, 1]}}, ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"])
        # 非法项一个都没落盘
        ov = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        names = [f["name"] for f in ov.get("fences", [])]
        for bad in ("坏2点", "坏z", "越界", "退化", "坏box"):
            self.assertNotIn(bad, names)

    def test_08_trajectory_with_refs(self):
        rc, out, j = run(["add", "--kind", "trajectories", "--json", "--data",
                          json.dumps({"id": "tj_test", "name": "回字", "kind": "自定义",
                                      "waypoints": ["space1", [0.5, 0.2, 0.3], "space2"],
                                      "speed_hint": 0.1, "desc": "引用空间点"}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["readback_ok"])
        wp = j["entity"]["waypoints"]
        self.assertEqual(len(wp), 3)
        for p in wp:
            self.assertEqual(len(p), 3)
            self.assertTrue(all(isinstance(x, (int, float)) for x in p))
        # 引用被解析成坐标, 且与 space_points 里 space1 的 pos 一致
        sp = json.loads(SB_SP.read_text(encoding="utf-8"))
        self.assertEqual([round(x, 6) for x in wp[0]], [round(x, 6) for x in sp["points"]["space1"]["pos"]])
        self.assertEqual(j["entity"]["waypoint_refs"], ["space1", None, "space2"])
        # 少于 2 点被拒
        rc, out, j = run(["add", "--kind", "trajectories", "--json", "--data",
                          json.dumps({"name": "单点", "waypoints": [[0.1, 0.1, 0.1]]}, ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"])
        # 未知点名被拒
        rc, out, j = run(["add", "--kind", "trajectories", "--json", "--data",
                          json.dumps({"name": "坏引用", "waypoints": ["spaceX", [0.1, 0.1, 0.1]]}, ensure_ascii=False)])
        self.assertEqual(rc, 1); self.assertFalse(j["ok"])

    def test_09_set_traj_show(self):
        rc, out, j = run(["set", "--traj-show", "off", "--json"])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j["readback_ok"])
        td = json.loads((SB_SCENE / "traj_display.json").read_text(encoding="utf-8"))
        self.assertFalse(td["show"])
        self.assertEqual(td["baseline_n"], 0)          # 其他键没动
        rc, out, j = run(["set", "--traj-show", "on", "--json"])
        self.assertEqual(rc, 0, out)
        self.assertTrue(json.loads((SB_SCENE / "traj_display.json").read_text())["show"])

    def test_10_set_json_delete(self):
        p = SANDBOX / "del.json"
        p.write_text(json.dumps({"arm": ["sim|示教·槽位1"], "local": ["guide|y=108"]}, ensure_ascii=False), encoding="utf-8")
        rc, out, j = run(["set", "--json-delete", str(p), "--json"])
        self.assertEqual(rc, 0, out)
        ov = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        self.assertEqual(ov["deleted"]["arm"], ["sim|示教·槽位1"])
        self.assertIn("cameras", ov)

    def test_11_dry_does_not_write(self):
        h0 = json.dumps(json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8")), sort_keys=True)
        rc, out, j = run(["add", "--kind", "markers", "--dry", "--json", "--data",
                          json.dumps({"name": "空跑", "pos": [0.1, 0.2, 0.3]}, ensure_ascii=False)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(j.get("dry"))
        h1 = json.dumps(json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8")), sort_keys=True)
        self.assertEqual(h0, h1, "--dry 不该改文件")

    def test_12_check(self):
        rc, out, j = run(["check", "--json"])
        self.assertEqual(rc, 0, out)
        self.assertIn("counts", j)
        self.assertIn("fence_invalid", j)
        self.assertEqual(j["fence_invalid"], {})
        self.assertTrue(j["files"]["objects3d.json"]["exists"])


    def test_13_rm_to_empty_drops_key(self):
        # 回归: 清空最后一类条目后应移除该键 (原文件本无此键 ⇒ 回到原键集), 且不能 KeyError
        for _ in range(20):
            mids = [m.get("id") for m in run(["list", "--json"])[2]["markers"]]
            if not mids:
                break
            rc, out, j = run(["rm", "--kind", "markers", "--id", mids[0], "--json"])
            self.assertEqual(rc, 0, out)
            self.assertTrue(j["readback_ok"], out)
        ov = json.loads((SB_SCENE / "overlay_spec.json").read_text(encoding="utf-8"))
        self.assertNotIn("markers", ov)
        self.assertIn("mode", ov) and self.assertIn("cameras", ov) and self.assertIn("l5live", ov)


if __name__ == "__main__":
    print("沙箱: %s" % SANDBOX)
    result = unittest.main(exit=False, verbosity=2).result
    ok = result.wasSuccessful()
    print("\n沙箱保留: %s" % SANDBOX)
    sys.exit(0 if ok else 1)
