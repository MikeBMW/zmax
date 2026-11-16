# 仿真幽灵臂上的附加几何 + 时间构成游标

两件事都在 `tools/web/tcp-ar.html`(8797 服务每请求从磁盘读, 改完不用重启服务, 浏览器硬刷新即可)。

## 三条硬规则

- **真机坐标系 ≠ 仿真幽灵臂**: `TCP.frames`(来自 `/api/tcp`)只覆盖**真机**臂; 回放/预览动的是 `PREV.M`(`rtrajPlayJoints` 每帧 `PREV.q`+`PREV.M=urdfFK`)。要在仿真末端显示模块/坐标系/任何标记, 必须自己 gated 在 `RTRAJ.playing||RTRAJ.joints` 并从 `PREV.M['tool1']` 取 —— 指望 `TCP.frames` 带出来, 回放时就只有一条光秃秃的臂。
- **任何进度/时间可视化的游标, 取值优先级必须是「本页播放中 > 跟随真机 > 真机游标」**: 反过来写时, 真机停在末点会让真机游标恒为末值, 游标永久钉在 100%, 用户看到的就是「没有游标 / 不动」。
- **改 canvas 绘制后, 只有像素判据能结案, 「函数被调用过」不算**: 插桩只证明代码跑了; 半透明填充落到画布上是混色, 纯色阈值抓不到; 整幅色块计数又会被静态元素(托盘模块/图例/UI)污染。

## 1. 在仿真末端挂几何体

`rtrajPlayJoints()` 每帧只做 `PREV.on=true; PREV.q=qq; PREV.M=urdfFK(qq)`, 不产出任何坐标系。自己写一段:

```js
var _rpOn = (typeof RTRAJ!=='undefined' && (RTRAJ.playing || RTRAJ.joints))
         || (typeof RTRAJ_FOLLOW!=='undefined' && RTRAJ_FOLLOW.on);
if(_rpOn && PREV.on && PREV.M && PREV.M['tool1'] && VR.simArm!==false){
  const t1 = PREV.M['tool1'];          // 单位米
  ...
}
```

- 位置: `drawFlatModule(g, pr, [t1.t[0]+L/2, t1.t[1], t1.t[2]], col, opt)` —— 长轴∥世界 X、与料盘同姿态, **不跟 tool1 的腕部朝向**; 这个偏移与 `INSIM.carry` 是同一口径, 别另起一套。
- 姿态: `_cols(t1.R)` 取三列当 X/Y/Z 轴向量。
- 夹持窗口按**真实夹爪事件**取(`#9` 合爪 → `#205` 松爪, 见 `real_traj_grip` 口径), 区间外模块已经放下, 不该再跟手飘。`RTRAJ.fi` 就是当前帧号。
- ⚠️ `rtrajStop()` 之后 `PREV.on` 变 `false`, 幽灵臂本身不再画 —— 附加物随之消失是对的语义, 别为「停下来还能看见」改成无条件绘制。

## 2. 半透明 = 看不见

`drawFlatModule` 默认 `globalAlpha 0.55` + `lineWidth 1.7`。一个 56.5mm 的盒子在整幅三维里只投影几十像素, 55% 透明铺在深底上, 人眼基本抓不到。

- 加可选第 5 参 `opt={alpha,lw}`, 既有调用方不传则行为不变 —— **别改全局默认值**, 托盘里几十个模块会糊成一片。
- 回放末端用 `{alpha:0.9, lw:2.6}`, 再加**中心亮点 + 文字标签**让它在整幅里能被认出来。
- 坐标轴同理: 0.10m/2.5px 太细, 0.13m/3.5px + 轴端小方点才看得清。

## 3. 时间构成甘特的游标

位置与时间**同源累加**, 一次循环出两个量:

```js
for (各段) {
  if (curI >= sg.i0 && curI <= sg.i1) {
    const frac = (curI - sg.i0) / Math.max(1, sg.i1 - sg.i0 + 1);
    pos  = accP + frac * sg.pct;      // 左偏移 %
    tNow = accS + frac * sg.dur_s;    // 当前时间点(秒)
    break;
  }
  accP += sg.pct; accS += sg.dur_s;
}
```

- **不能 `curI/215*100`**: 条宽是**时间**占比, 各段时间/点数比不同, 线性映射会跑偏。
- 动画: `#rpGanttCur` 加 `transition:left .16s linear`, 与 160ms 的 `mtTick` 同拍, 平滑不跳格。
- **气泡要溢出到条外** ⇒ 条(`overflow:hidden`)外再包一层 `position:relative`, 游标放条外那层; 气泡放条里会被裁掉。
- 甘特在 `mtRender` 里重建, 而 `mtRender` 有 `cur|i|n|meta数|cycle_s` 的 key 节流 —— 纯回放(非元任务流)时 key 不变, 游标元素不会销毁重建, transition 才能连续。

## 4. 无头自验: 证明「真的画出来了」

1. **插桩**: 全局函数声明可重新赋值, 包一层计数并偷 projector ——
   ```js
   const _o = drawFlatModule;
   window.drawFlatModule = function(g, pr, p, c, opt){
     if (c === '#a3e635') { cnt++; last = pr(p); }   // pr 是 drawVR 传进来的投影器
     return _o.apply(this, arguments);
   };
   ```
2. **开关 A/B**: `VR.simArm=false` 关掉幽灵臂, 计数必须归 0; 同一屏幕坐标再取一次色轴像素(实测 40 → 4)。
3. **判色要放宽**: 透明填充落盘是混色(柠檬绿 55% 铺深底 ≈ `100,171,78`), 纯色阈值一律抓空 ⇒ 用 `g > r+25 && g > b+45` 这类方向性判据。
4. **别整幅数颜色**: 托盘模块/图例色块/UI 同色系, 整幅计数在几种完全不同的状态下会给出**一模一样**的数字 —— 那就是信号: 你数的是静态元素。
5. **采样中心用插桩拿到的实时投影坐标**, 别用上一拍存下的固定像素点 —— 回放一直在动。
6. 页面状态变量(如 `MT`)可能锁在 IIFE 闭包里, 控制台取不到, 只能读 DOM。这是正常的, 不是页面没加载。

### 语法校验两个坑

- `node --check` 前只抽**非 json** 的 `<script>` 块: 页面内嵌 `application/json` 的数据块(轨迹 32KB)会让 `--check` 报假 `SyntaxError`, 看着像自己改坏了。
- 括号配平 + `node --check` 都过再上浏览器; 改完要**回读服务端返回的字节数/md5** 确认读到的是新文件。

## 5. 改 `s += '...' + '...'` 拼接串时别插分号

拼接链中间插一个 `;`, 后面的 `+ '...'` 会变成**独立的 unary-plus 表达式**, 求值后丢弃 —— 不报错、不告警, 整段内容静默消失(实测把 14 段图例整块吞掉)。改完必须回读 DOM 里「本该还在」的元素数量与文本, 别只看自己新加的那部分。
