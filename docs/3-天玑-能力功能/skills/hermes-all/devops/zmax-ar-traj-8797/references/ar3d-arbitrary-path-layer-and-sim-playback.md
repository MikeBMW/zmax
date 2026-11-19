# 在 /ar3d 上显示任意航路 + 只用仿真右臂回放(真机不动)

用户诉求形态：「把这条轨迹画出来」「让我看到仿真右臂走一遍」。页面天生只有三样东西：命名轨迹(轨迹1~5)、实测轨迹、真机实测层 —— **没有"随便给一条航路"的入口**。所以要么走下面这套最小改造，要么事先跟用户讲清只能在别的页看。

## 1. 把任意航路画成一条线(青色层)

数据源：`zmax_data/runtime/traj/planned_traj.json`，字段 `pts_mm`(≥4 个 [x,y,z] 毫米) + `total_mm` + `src`/`note`。

`tools/tcp_ar_server.py` 的 `_traj()` 末尾加一个 flag 闸（只影响画面，不碰 8791、不碰执行链）：

```python
_ofl = os.path.join(REPO, "zmax_data", "runtime", "traj", "orbit_show.flag")
if os.path.exists(_ofl):
    _od = json.load(open(planned_traj.json))
    out["plan"] = [[v / 1000.0 for v in p] for p in _od["pts_mm"]]
    out["plan_label"] = "插口补采 · %d点/%.0fmm" % (len(_pts), total_mm)
```

页面侧（`tools/web/tcp-ar.html`）`plan` 层的绘制闸原来是 `NAMED_ON[planOwner()]` —— 认的是"某条命名轨迹按钮亮着"，自定义航路 label 不在那五个名字里 ⇒ **永远不会画**。加一个按 label 认的旁路：

```js
function orbitOn(){ return /插口特写|插口补采/.test((TRAJ&&TRAJ.planLabel)||''); }
function planVisible(){ return !!(NAMED_ON[planOwner()] || orbitOn()); }
```
然后把三处 `NAMED_ON[planOwner()]` 全换成 `planVisible()`（3D 管、2D 粗线、标签块），并给自定义层换色（青 `rgba(0,229,255,…)`，与洋红=命名轨迹、橙=真机实测区分）。

## 2. 只用仿真右臂回放(不下发真机)

页面里 `rtrajPlayJoints(d)` 就是"按关节角帧驱动仿真右臂、真机不动"的那条路（`d.frames[i] = {p:[3]m, q:[4]quat, j:[6]rad, t:s}`，另有 `n_frames`/`path_mm`/`rot_total_deg`/`src_rec`）。

- 服务端加只读端点 `GET /api/orbit_frames`，返回 `zmax_data/capture_plan/*_joints.json`（**多个候选按 mtime 取最新**，这样换航路不用改页面）。
- 页面加载后 `fetch('/api/orbit_frames')` → `ensureTrajJoints()`(先读 215 点那份，左臂冻结/FK 依赖它) → `setTimeout(()=>rtrajPlayJoints(d), 400)`。
- 入口要**看得见**：在「轨迹:」那一行加个青色按钮（`id=bOrbit`，`DOMContentLoaded` 里绑 onclick），别只靠 `#orbit` 这种 URL 约定——用户不会去记锚点。

## 3. 标签黑条（必然踩）

长 label 会被这段代码画成横贯画面的黑底条，用户会说「黑条挡视线」：

```js
g.fillStyle='rgba(0,0,0,.78)'; g.fillRect(lx-4, ly-15, tw+12, 21);   // tw = measureText(lbl).width
```

规则：① 服务端标签只给短串（`插口补采 · 22点/1048mm`），别把 `note` 拼进去；② 页面加硬上限 `if(lbl.length>30) lbl=lbl.slice(0,29)+'…'`。改完可量：`bold 13px monospace` 下 30 字内约 230px，画布 980px 宽，不是黑条。

## 4. 验证口径（别用"我看着画上了"）

- 接口：`GET /api/traj` 的 `plan` 点数/`plan_label`；`GET /api/orbit_frames` 的 `n_frames`。
- 页面：`RTRAJ.playing / RTRAJ.fi / (RTRAJ.frames||[]).length`，以及 HUD `#tRTraj.textContent` 里是否出现新航路名。
- 真的画上去：把 canvas `drawImage` 到离屏再 `getImageData`，数青色像素（>1000 才算有线）。
- 按钮是否真生效：`document.getElementById('bOrbit').click()` 后再读 `RTRAJ`；无障碍层的 `browser_click` 可能打在别的元素上，别据此判定按钮坏。
