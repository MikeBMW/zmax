# 事故台账 INCIDENT-INDEX

按时间倒序。每条：编号 · 一句话标题 · 影响 · 是否闭环

| 编号 | 标题 | 影响 | 闭环 |
|---|---|---|---|
| INC-20261020-01 | 抬升去金手指点1 途中肘部(link4)撞上横梁 | 3 次急停；precheck 报 PASS 而实际侵入 23mm | 部分（工具已修；连杆半径/手臂相机尺寸待标定） |

---

## INC-20261020-01 抬升去金手指点1 途中肘部撞上横梁

详见 [incidents/INC-20261020-01-aoi-upper-beam.md](incidents/INC-20261020-01-aoi-upper-beam.md)

- 根因：`precheck_move.py` 把连杆当无粗细线段 ⇒ 肘部距横梁 55.5mm > 20mm 门槛判绿，扣本体半径 78mm 后实际 −22.5mm
- 加重因素：手臂相机不在围栏表；我用欧拉角手推法兰位置 y 差 251mm
- 修复：precheck 扣半径 + <20mm 判 FAIL；新增 `tools/fk_link_check.py`（URDF 正解）；tool0 改读 `heartbeat.pose.flange`
- 遗留：连杆半径需实测标定；手臂相机需偏移+包络尺寸才能入模型
