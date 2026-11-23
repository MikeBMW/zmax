# ar3d 目标位姿层（TP1/TP2）：发布、双位姿绘制与「真的看得见」的取证

页面：`tools/web/tcp-ar.html`（`:8797/ar3d`，systemd 托管，改文件不需重启，刷新即生效）。

## 数据链路

```
plan_guide.target_pose(slot_id, tray="R"|"L")    几何 → 6D 目标（pos=金手指端中点 / grasp=体中心 / pre=+hover）
plan_guide.target_pose_pair(lslot, rslot)        成对，atomic=True：一侧取不到几何则整对失效
plan_guide.publish_target(slot_id, tray=)        写 fences.json：TP1=右臂 / TP2=左臂
                                                 pose{pos_m,quat,dims_mm,pre_pos_mm,valid,label,arm}
/api/fence → tpTick() → TP(TP1)/TPL(TP2) → drawTargetPose → _drawTP(g,pr,T,COL,suf)
```

- 只写文件、不下发运动。颜色约定：右臂 `#ffd23f`、左臂 `#4da3ff`；`valid=false` 走虚线 + 文字尾巴 `⚠未观测(先验)`。
- 标签只写彩色文字，**不加黑底文字条**。
- 左盘（左臂前面那块）没有 `tray_slots` 配置，几何真源是围栏盒子 `左槽N`；体中心 z = 盒底 z + 模块厚/2
  （用盒中心会高出约 3mm）。
- 左盘朝向按右盘镜像，属**先验**：现场若反向摆放，用 `ZMAX_SLOT_XDIR_L` 覆盖，别把镜像当实测写进交付。

## 坑：「画了」不等于「看得见」

两块料盘相距 ~0.53m，默认机位只框住右盘 ⇒ 左目标被投影到 canvas 外（实测 `u=-89`）。
`__TP_DRAWN__` 递增只能证明函数跑了，不能证明用户看得见。

取证判据（缺一不可）：

```javascript
const c=document.querySelector('canvas');
const inBox = b => (b||[]).filter(p=>p[0]>4&&p[1]>4&&p[0]<c.width-4&&p[1]<c.height-4).length;
inBox(window.__TP_BOX__)===8 && inBox(window.__TP_BOX___L)===8   // 两个位姿的 8 角点都在画面内
window.__TP_DRAWN__===window.__TP_DRAWN___L                      // 每帧两侧都画（计数相等）
window.TP.label / window.TPL.label / window.TP.pos_m             // 标签与位姿对得上、js_errors 为空
```

## 坑：suf='' 与总计数器同键 ⇒ 总数被翻倍

`window['__TP_DRAWN__'+suf]` 在 `suf===''` 时就是 `__TP_DRAWN__` 本身，再叠一行总计数 ⇒ 总数 = 右×2 + 左，
看起来像「一侧丢帧」，其实两侧都画了。正确写法：`suf` 非空才进分计数器，总数另立 `__TP_DRAWN_ALL__`。

## 两个位姿同时进画面：只改相机，不动数据

```javascript
VR.tgt   = 两目标中点;
VR.yaw   = Math.atan2(b[1]-a[1], b[0]-a[0]) + Math.PI/2;  // 视线垂直于两点连线 ⇒ 左右并排
VR.pitch = 0.62;                                         // 略俯视
VR.dist  = Math.max(1.15, d*1.55);                       // d = 两点距离(m)
window.__FIT_TP__ = {d, yaw, dist, tgt};                 // 取景参数留证
```

- 一对目标都到位后自动取景**一次**（`__TP_FIT_DONE__` 防重复），别每帧重设，也别改别的场景的默认机位。
- 投影约定：`fwd=[cos p·cos y, cos p·sin y, −sin p]`、`eye = tgt − fwd·dist`；改 yaw 前先核对约定，
  否则「并排」会变成「前后」。

## 成对发布的红线

两个目标各自都合法，但规划器一次只吃一个 ⇒ 一侧缺失时**整对不发**（`atomic`），并在 `why` 里写清哪一侧、为什么。
让一侧单飞的结果就是一臂按新目标、一臂按旧目标，等于半路掉头。
