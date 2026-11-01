# 采集 schema / 位姿数学 / 导出约定

## frames.jsonl 每行(采集器 `tools/gs_capture.py` 落)
```json
{"seq":0,"t_wall":1790808058.7,"t_mono_fetch0":12345.6,"t_mono_fetch1":12345.603,
 "fetch_ms":2.4,"pose_before":{…},"pose_after":{…},"pose_t_gap_ms":2.4,
 "file":"frame_000000.jpg","bytes":27096}
```
- 配对: 取 `pose_after`(失败则 `pose_before`), 认为它代表 `[t_mono_fetch0, t_mono_fetch1]` 这一瞬的 TCP; 两者差大(运动中)= 取图中点位姿更准, 可线性插值。
- `t_wall` 只留档; **一切排序/配对用 `t_mono_*`**。
- 图**原样存**(Orin 已压好 JPEG), 不要解码再压 —— 3DGS 输入别叠加一层重压损失。

## 位姿字段(rokae `tcp_out/latest.json`)
`x,y,z`(m) + `rx,ry,rz`(**弧度**) + `qx,qy,qz,qw` + `frame:"base_link"` + `joint[12]` + `ts`/`t`。
- 四元数与 rx/ry/rz 同源(差 ≤1e-6 rad, ZYX), 用**四元数**建旋转矩阵(避免欧拉奇异)。
- 位姿源静止时仍按 50Hz 写同一值 ⇒ 别拿“值在变”当“臂在动”; 判动看 `capture_summary.json` 的 `pose_*_range_mm`。

## 相机外参(重建的输入)
```
T_base_tcp = [R(qx,qy,qz,qw) | (x,y,z)]     # 来自 latest.json
T_tcp_cam  = inv(T_cam2tool)                 # handeye_state.json 给的是 cam→tool
T_base_cam = T_base_tcp @ T_tcp_cam          # 相机外参
```
- 手眼残差(本机 0.06mm / 0.0046°)远小于 D405 在 7cm~1m 的像素级误差 ⇒ 不是瓶颈; 瓶颈通常是**内参 K、时间配对、过曝**。

## 判「位姿有没有真下手眼」—— 看模长恒定, 不看 note 字段
`cameras.json` 的 `note` 写什么都不作数(可能是旧文案没更新)。硬判据:
手眼生效时, `T_base_cam` 与 `T_base_tcp` 的平移之差, 模长对**每一帧**恒等于手眼模长(本机 244.1mm);
没下手眼时(把 TCP 位姿直接当相机位姿), `T_cam2world` 的平移模长是**随机分布**(实测 124 帧 0.537~1.002m, 均值 0.740m)。
- 恒定 ⇒ 变换已生效; 随机 ⇒ 那趟采的是原始 TCP 位姿, 该数据集不可用于交付重建。
- ⚠️ **模长恒定只能证明「乘过某个手眼矩阵」, 不能证明方向对**: 平移模长在 `@ X` 与 `@ inv(X)` 下相等,
  两种写法都能让这一检查通过。方向必须另验(反投影一个已知点 / 看渲染是否整体镜像),
  别拿模长恒等就下「公式正确」的结论。

## 内参: 一律读标定文件, 禁用 `1.2*max(W,H)` 这类估算
自动采集守护里最容易长出「猜内参」: `fx = 1.2*max(W,H)` 在 640 宽正好给 **768**,
而 D405 真值 **394.06** —— 差 95%, 所有投影系统性偏移, 重建整体扭曲。
同批 124 帧实测: 内参 768 时留出 PSNR **10.9dB**, 换成 394.06 才是正常量级。
- 定式: 读 `models/real_cam_calib.json` 的 `fx_fy_cx_cy`, 并按**实际帧尺寸 / 标定尺寸**等比缩放
  (采到 320x240 缩略图时 fx/fy/cx/cy 一起乘 0.5; 只缩 fx 不缩 cx 等于又错位一次)。
- 无标定文件才退回估算, 但必须写进 `K_src`: `估算 1.2*max(W,H)=768 (无标定, 不可信)`。

## cameras.json 必须自证来源(猜的 vs 标定的)
至少三个元数据字段, 否则事后无法审计到底是数据错还是训练错:
- `K_src` —— 内参出处(标定文件名 + 缩放比, 或「估算…不可信」)
- `handeye_applied` —— 布尔, 位姿是否真的乘过 `T_cam2tool`
- `note` —— 人读一句话, 按实际生效情况生成, **不要硬编码**

## 没下手眼的数据集可以救, 不用重采
守护若把 `T_cam2world` 存成了 TCP 位姿的逆(即「TCP 位姿直接当相机位姿」), 原始位姿信息其实还在文件里:
反推 `T_base_tcp = inv(T_cam2world)`, 再按本文开头的公式重算外参即可 —— **别急着让人重扫一遍**。
- 现成工具 `tools/gs_fix_dataset.py --src <旧数据集> --out <新目录> [--handeye <json>] [--calib <json>]`:
  一次重算外参 + 内参, 并打印「手眼修正位移量」分布(全帧同值才说明与标定一致)。
- `--no-handeye` 只修内参 —— 消融对照用, 可把「内参错」和「位姿错」的贡献分开量。
- ⚠️ 重训必须用**同口径**(同步数 / 同 holdout)与出问题那版比, 否则「修好了」只是换了个数。

## 先核产物版本, 别假设「我改过就一定生效」
同一批数据可能是新代码采的, 也可能是旧代码采的 —— 看产物自证字段(`note` / `K_src` / `handeye_applied`),
不要凭「我记得部署过手眼版」下判断。
反例值得记住: 部署过的修复没有落到在役进程上, 后续采集的帧 `note` 仍写着「未经手眼变换」,
于是低 PSNR 被一路归因到训练参数上 —— 症状与「训练没调好」完全同名, 先查数据自证字段再调参。

## 导出给训练器
- **COLMAP 文本**(通用): `cameras.txt` = `CAMERA_ID PINHOLE W H fx fy cx cy`; `images.txt` = `IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME`。
  COLMAP 的 `(q,t)` 是 **world→camera**: `R_cw = T_base_cam[:3,:3].T`, `t_cw = -R_cw @ T_base_cam[:3,3]`。写反 = 场景镜像/直接崩。
- **nerfstudio transforms.json**(gsplat/nerfstudio 的 loader 也吃): `frames[]` 给 `file_path` + `transform_matrix`(是 **camera→world**, 即 `T_base_cam`) + `fl_x/fl_y/cx/cy/w/h`; 顶层 `applied_transform`/`scale` 保持单位阵/1。
- 训练前必查: 挑 3~5 个已知位姿, 把“单位矩阵代入”反投影一遍(把场景里一个已知点投到图上看着对不对), 比训完再猜便宜得多。

## 什么算“够用的一次扫描”
- 覆盖: 目标区域每个面至少 2~3 个不同方向看到(相邻帧重叠大); 单基线平移会“薄”。
- 帧量: 640x480 下 200~600 帧能干一个小工作区; 帧多不是好事——重复视角只增时间不加信息, 用位姿去重(位置+朝向阈值)筛。
- 质量筛选(可与 VLM 联合): 拉普拉斯/梯度能量判糊, 直方图全 255 判过曝, 帧间位姿跳变过大(运动中拖影)直接丢。
