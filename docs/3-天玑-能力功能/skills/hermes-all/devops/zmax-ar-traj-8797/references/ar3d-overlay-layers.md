# 8797 /ar3d 画布「多了东西」怎么定位与删掉

针对「XXX 太多了, 删掉」这类请求(用户指着画布说某个颜色的一堆线/点不要了)。

## 定位顺序(不要逐个点按钮试)

1. **先读运行时状态, 不要靠点击探测**。页面把很多层的绘制结果挂在 `window.__*` 上:
   ```js
   window.__NAMED_VIS__   // {key: {ok: 实际画出的点数, total: 数组长度}}  ← 最有用
   window.__NAMED_DBG__   // {key, total, projected, ...}
   window.__VIS__         // {on, phys, pieces, segs, units} 总开关/文案
   window.__TP_DRAWN__ / __TP_DRAWN_ALL__ / __FENCE_PTS_DRAWN__   // 跨帧累加计数器, 不是元素个数
   ```
   `__NAMED_VIS__` 一读就知道哪条命名轨迹在画、画了多少点 —— 比一轮轮关按钮快一个量级。
   ⚠️ `__TP_DRAWN__` 这类**每帧 +1** 的计数器不代表元素数(实测 2502 只是帧数), 别拿它下结论。

2. **按颜色反查源码**。`grep -noE '0x[0-9a-fA-F]{6}|#[0-9a-fA-F]{6}' page.html | sort | uniq -c | sort -rn`
   能把「浅蓝/青」落到具体常量上; 再 `grep -n '<该色值>'` 看它被赋给哪个 key。
   颜色与 key 的映射集中在 `NAMED_COL`(实测 `map:'#22d3ee'` 就是那条青蓝)。

3. **分清「按钮管得住的层」与「按钮管不住的层」**。界面上的「轨迹1~5 / ✕ 关掉命名轨迹」只遍历
   它自己那几个 key; 而代码里**直接写 `NAMED_ON['<别的key>'] = true`** 的层(定时拉取、自动接续)
   根本不在按钮的管辖里 —— 现场表现就是"点了关不掉"。判据: `Object.keys(NAMED_ON)` 里出现了
   按钮列表之外的名字。

4. 排查阶段点过的开关(自动环绕 / SIM骨骼 / MuJoCo 同视角 / 位置细胞)会互相干扰判读 ——
   **先刷新页面取一次基线截图**, 别在"已经点乱"的状态上下结论; 刷新也会把按钮 class 恢复到 HTML 默认值。

## 典型真因: 8817 跟随轨迹自动叠加

页面尾部一个 IIFE 每 2s 拉 `http://<host>:8817/session.json`, `pts.length>1` 就无条件:
```js
NAMED['follow']=pts; NAMED_ON['follow']=true;
NAMED_COL['follow']='#22d3ee';   // 青/浅蓝
SHOW=true; if(typeof drawVR==='function') drawVR();
```
累积到两万多点时, 画面中央就是一坨密集的青色管环(`drawTube` 按点逐段画环, 点越多越糊)。

## 删掉的做法(两道闸, 只做一道下次还会回来)

- **绘制闸**: `drawNamedOV()` 的 filter 加 `k!=='follow'` —— 挡住所有从这个 key 来的绘制。
- **数据闸**: 删掉 `pull()` 里对 `NAMED` / `NAMED_ON` / `SHOW` / `drawVR()` 的写入, 只保留
  `NAMED_INFO['follow']`(HUD 读数用)。**只把 `NAMED_ON` 设 false 不够** —— 下一次 `pull()` 又写成 true。
- **读数要一起改**: HUD 那行「跟随轨迹 N 点」留着会让用户以为还在画(画面干净了字还在), 一并去掉。
- **验证**: 刷新(页面热读, 改 HTML 不用重启服务) → `browser_console` 看 `js_errors` 为空 →
  截图确认那团没了 → 再读 `window.__NAMED_VIS__` 确认 follow 已不在绘制集合里。

## 边界

- **只删显示, 不删数据**: 8817 的会话轨迹数据仍在服务端。用户要连数据一起清时再单独处理(清数据不可逆)。
- **别顺手改功能**: "跟随真机"本身(仿真臂跟随、`/api/tcp` 的 HUD 读数)靠 `PREV.on` 与那段 `setInterval` 活着,
  只关轨迹叠加不影响它 —— 删完回读一次 HUD 的 TCP / 真值帧龄有没有在刷, 确认没连带打断。
