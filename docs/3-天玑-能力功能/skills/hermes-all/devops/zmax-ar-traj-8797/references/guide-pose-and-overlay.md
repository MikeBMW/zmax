# 3D 引导位姿绘制 · 黑底文字条 · 仿真臂姿态（/ar3d 自绘 canvas）

老倪按画面验收：先说画面哪里不对，再说代码。以下三条是每次改 /ar3d 叠加层都要守的口径。

## 1) 位姿原点 = 模块体中心，框按中心对称展开

- 位姿原点必须落在**模块体中心**（也就是真机 TCP 该去的点），**不是**金手指端。
- 框的 8 个角用 `s ∈ [-0.5, 0.5]` 三个轴展开；一旦改成从原点“单向拉出 L”（`sx ∈ [0,1]`），画面上就比模块靠前/偏上一大截（72mm 模块差 36mm），用户会直接报“位置偏上/应该跟光模块重合”。
- 金手指端保留成 `head_mm` 备查，别当绘制原点；`publish_target*` 的 `pos_mm` 与 `grasp_mm` 同源即视为“重合”。
- 预抓点（目标上方 hover 40mm）只画细虚线 + 小圆点，**默认不画**（`show_pre=false`）；那个高空圆圈会被当成第二个位姿，报“偏上”。

```js
// tcp-ar.html::_drawTP —— 框必须中心对称
for(const sx of [-0.5,0.5]) for(const sy of [-0.5,0.5]) for(const sz of [-0.5,0.5]){
  const t=[sx*D[0], sy*D[1], sz*D[2]];
  c.push([0,1,2].map(i=> o[i]+ax[0][i]*t[0]+ax[1][i]*t[1]+ax[2][i]*t[2]));
}
```

双目标（左/右臂）同屏：`fitBothTP` 只改相机（`tgt`=两点中点、`dist≈1.15`），绝不动位姿数据。
验收读 `__TP_SCREEN__` / `__TP_SCREEN___L` 和 `__TP_BOX__*`，确认 8 角点在画布内；计数分后缀写（`__TP_DRAWN__` vs `__TP_DRAWN___L`），另立 `__TP_DRAWN_ALL__`，否则后一个覆盖前一个。

## 2) 黑色文字底板一律不画

- 拦 `fillRect`：`fillStyle` 匹配 `rgba(0,0,0,.6~.9)` 或纯黑，且 `h≤26px`、`w<900px` ⇒ 直接 return；`fillText` 照画（彩色字压画面）。
- 调试开关：`window.VR_TEXT_BAR=1` 恢复黑底。
- **必须打到所有 2D canvas**（`vid / ov / loupe / vr`），并在页面起来后 1.2s、4s 各补扫一次 —— 只拦主视图时，注记换个图层又冒出来（历史上已经踩过一次）。

```js
(function(){ const patch=(P)=>{ if(!P||P.__noTextBar||typeof P.fillRect!=='function') return;
  const _fr=P.fillRect;
  P.fillRect=function(x,y,w,h){ if(!window.VR_TEXT_BAR){
      const s=String(this.fillStyle||'');
      const dark=/^rgba?\(\s*0\s*,\s*0\s*,\s*0\b/.test(s)||/^#0{3,6}$/i.test(s);
      if(dark && h<=26 && w<900) return;
    } return _fr.apply(this,arguments); };
  P.__noTextBar=1; };
  const all=()=>document.querySelectorAll('canvas').forEach(cv=>{try{patch(cv.getContext('2d'))}catch(e){}});
  all(); setTimeout(all,1200); setTimeout(all,4000); window.__noTextBarPatch=all; })();
```

验收用像素打点（同步执行，不与 rAF 抢帧）：取像素 → `fillStyle='rgba(0,0,0,.80)'` 画一条 → 再取像素，**像素没变 = 拦住了**；再用红色对照条确认没误杀。逐画布打一张表（`id / __noTextBar / suppressed`）。

## 3) 仿真指示臂要“站着”：IK 种子用真机示教关节角

- 位置 IK 只约束 xyz，多余自由度全由**种子**决定。按“工具轴朝下”在随机种子里挑最优 ⇒ 挑出大关节角，整条臂躺倒（用户原话“左臂怎么躺下了”）。
- 正确：种子取真机示教录制的**抓取帧关节角**（`zmax_data/rokae_sdk/real_traj_absj.json` 里 `rpy ≈ 2.961, −1.490, 0.205` 那帧，`q=[0.798,0.579,−2.176,1.122,0.638,0.310]`），只接受 `err≤2mm` 且 `max|Δq|≤0.5rad` 的解；超了就宁可不出并写明“该位姿需要把臂拧成大关节角，不画”。
- 自检：`urdfFK(LARM.q).tool1.t` 与目标差 ≤0.2mm，并回报 `dq_seed_rad`（正常在 0.04rad 量级）。
- **不要用页面 6-DOF 位姿 IK 判“可达”**：本页 `ikTool1Pose` 在右盘合法目标上也会偏 330mm / 姿态差 80°+，位置解（`ikTool1`）可信、姿态解不可信。
- 仿真臂只承诺“位置准 + 臂形自然”，姿态不是目标姿态 —— 标签/文案里必须写出来，不能当真机姿态用。
