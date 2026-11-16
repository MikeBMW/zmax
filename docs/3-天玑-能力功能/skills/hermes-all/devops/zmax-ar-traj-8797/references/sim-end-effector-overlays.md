# 仿真末端叠加: 工件实体 + tool1(模块头)坐标系

给 8797 ar3d 的紫色幽灵臂(右臂_仿真)末端挂上工件实体和工具坐标系时用。

## 关键结构 (都在 `drawVR()` 内, 约 2400 行处)

- 幽灵臂: `PREV.on && PREV.M && VR.simArm!==false`
- 真机坐标系: `VR.frames && TCP.frames.tool1` —— 它**只画真机的** base/tool0/tool1, 仿真末端的 tool1 不在 `TCP.frames` 里, 所以回放时只有光秃秃一条臂。
- 工件实体: `drawFlatModule(g, pr, 世界系中心, 颜色, opt)` —— 世界轴对齐(长∥X / 宽∥Y / 厚∥Z), 不跟腕部朝向; 这是既有口径, 别改成跟 tool1 姿态。
- 轴向量: `_cols(t1.R)` 取旋转矩阵三列 = 三根轴。

## 步骤

1. 在幽灵臂那段**之后**插一段, gate 成「回放/跟随真的在跑」:
   ```js
   var _rpOn = RTRAJ.playing || RTRAJ.joints || RTRAJ_FOLLOW.on;
   if(_rpOn && PREV.on && PREV.M && PREV.M['tool1'] && VR.simArm!==false){ ... }
   ```
   用 `RTRAJ.joints` 而不只看 `playing`: 停播后它仍为真, 但 `PREV.on` 会变 false ⇒ 自动收起。
2. 工件中心 = `t1.t[0] + L/2`(与既有插入仿真逐字一致, L 取 `MODSPEC.L_mm/1000`)。
3. 夹持窗口按轨迹真值 gate: 合爪点 … 松爪点之间才画。窗口外工件已放进托盘, 还跟着手飘会被目检戳穿。
4. 三轴: 长 0.13m / 线宽 3.5 / 轴端 5px 方点 / 文字标签。真机那套是 0.13m / 2.5, 仿真略粗以便区分。
5. 三段各自受既有开关管: `🦾 右臂_仿真` 关掉则工件与三轴一起消失; `🧭 坐标系` 关掉只留工件不留轴。

## 可见性: 不改就必被打回

`drawFlatModule` 默认 `globalAlpha 0.55` + `lineWidth 1.7` —— 在整幅三维里只投影出个位数像素, 等于看不见。做法: 给函数加可选 `opt={alpha,lw}`, 叠加处传 `{alpha:0.9, lw:2.6}`, 既有调用方不传 opt 行为不变; 再加工件中心亮点 + 文字标签, 让画面自己说明白。

## 验证: 像素级, 别靠肉眼猜

画布读色有三个坑:

- 页面有多张 canvas(`vid` / `ov` / `loupe` / `vr`), 三维视图是 `vr`。读错 canvas 会得到全 0 或「全不透明」的假数据。
- 半透明叠加后颜色与背景混色, 纯色阈值(如 `r>150&&g>200&&b<110`)抓不到; 用相对判据 `g>r+25 && g>b+45 && g>110`。
- 场景里的静态元素(托盘工件)贡献固定像素数, 会造成「改前改后一样多」的假象 —— 整幅计数不可用于判定。

可靠做法是给被调函数插桩, 桩里拿到的 `pr` 就是投影函数, 可以直接算出屏幕坐标:

```js
const _o = drawFlatModule;
window.drawFlatModule = function(g,pr,p,c,opt){
  if(c===TARGET_COLOR){ window.__n++; if(pr) window.__last = pr(p); }
  return _o.apply(this, arguments);
};
```

然后做**同一屏幕坐标**的开关 A/B: 记住投影点, 切 `VR.simArm` 开/关, 各取该点周围 80×80 的轴色像素。开关两侧差存在(典型 40 → 4)才算证明; 只比整幅像素数说明不了任何事。

同理判「工件有没有画」: 比 `TARGET_COLOR` 的调用次数(开 N 次 / 关 0 次), 再看该点周围绿系像素数是否从个位数升到几十。

## 改这个大 HTML 的语法检查

`tcp-ar.html` 里除 JS 还有 `<script type="application/json">`(内嵌整条轨迹, 30KB+)。按 `<script>` 抽全部块喂 `node --check` 会报 `Unexpected token ':'` —— 那是 JSON 数据不是代码, 别去改你的 JS。按属性过滤:

```python
for m in re.finditer(r'<script([^>]*)>(.*?)</script>', html, re.S):
    if 'json' in m.group(1): continue
```

改完不必重启 8797: 服务端每次请求读盘, `curl` 一次页面比对 md5 与磁盘一致即证明线上已生效。
