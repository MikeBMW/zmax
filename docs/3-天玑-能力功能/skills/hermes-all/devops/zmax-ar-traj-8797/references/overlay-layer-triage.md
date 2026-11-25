# 画布上多出来的叠加层/轨迹: 怎么定位、怎么摘掉

`/ar3d` 这类 canvas 2D 叠加页里冒出一大团不该有的线时, 按钮状态往往管不到它。
症状形态: 一大团同色密集曲线(管环/折线)压在画布中央, **点「✕ 关掉命名轨迹」「关自动环绕」「原子技能包络全部隐藏」全都不消失**。

## 定位顺序(不要逐个点按钮试)

1. **先读页面自己暴露的调试统计** —— 比点按钮快十倍, 而且能发现按钮根本管不到的 key:
   ```js
   window.__NAMED_VIS__   // {follow:{ok:25401,total:25401}}  ← 每个图层实际投影/总点数
   window.__VIS__          // {on,segs,units,pieces,phys}       ← 渲染总状态
   window.__NAMED_DBG__ / window.__TP_DRAWN__ / window.__FENCE_PTS_DRAWN__
   ```
   点数上万的那个 key 就是元凶。**`__TP_DRAWN__`/`__FENCE_PTS_DRAWN__` 是跨帧累加计数, 不是元素个数**, 别拿它判"画了多少个东西"。
2. **再按颜色反查绘制函数**:
   ```bash
   grep -oE "strokeStyle *= *[\"'][^\"']+[\"']" page.html | sed "s/.*[\"']\(.*\)[\"']/\1/" | sort | uniq -c | sort -rn
   ```
   拿到调色板后 `grep -n '<那个色值>'` 就能找到绘制点与它的调用者。
3. **最后才点按钮做对照** —— 按钮只改 UI 状态 / `NAMED_ON`, 与"哪段代码在画"是两件事。

## 已确认的一种真因形态: 外部数据源每 2s 强推一个图层

页面尾部 IIFE 定时拉 `http://HOST:8817/session.json`, 只要 `path.length>1` 就无条件执行:
```js
NAMED['follow']=pts; NAMED_ON['follow']=true;   // 强制开
NAMED_COL['follow']='#22d3ee';                   // 青蓝色
SHOW=true; drawVR();
```
⇒ 累积到 25401 点的跟随轨迹被 `drawNamedOV()` 全画成 tube, 画面中央糊成一团。

**为什么按钮关不掉**: `'follow'` 这个 key **不在**「轨迹1~5」按钮能操作的键列表里(`xiaohong/square/map/safe/real`)。
按钮只管那五个, 而 `NAMED_ON` 里多出来的 key 照样被 `drawNamedOV` 遍历绘制。

## 修法: 两道闸 + 顺手收文案

1. **绘制闸**(根治): `drawNamedOV` 的 filter 里排除该 key
   ```js
   Object.keys(NAMED_ON).filter(k=>NAMED_ON[k] && NAMED[k] && NAMED[k].length>=2 && k!=='follow')
   ```
2. **写入闸**(防再来): `pull()` 里删掉对 `NAMED` / `NAMED_ON` / `SHOW` / `drawVR()` 的写入, 只留
   `NAMED_INFO['follow']` 供别处读数 —— 否则下一轮拉取又把开关撬开。
3. **文案一起改**: HUD 里那行「跟随轨迹 N 点」要去掉。画面干净了字还在, 用户会继续问"这 2 万点是什么"。
   同理, 任何"已关闭某图层"的改动都要把对应的读数/角标一起收掉。

## 口径

- 用户说「删掉」= **画面上不要**, 不是删上游数据。`:8817` 那份会话轨迹原样保留, 要清得单独做并先告诉他。
- 该图层背后的功能(如"跟随真机"的 HUD 读数、仿真臂跟随)**要留着** —— 只摘掉叠加绘制, 别连带把功能停掉。
- 页面 HTML 是**热读**, 改完刷新即可, 不用重启服务; 验收 = 刷新后截图那团消失 + console `js_errors` 为 0
  + HUD 恢复正常读数(证明跟随本身没被改坏)。
- 排查期间为"试出来"点的那些开关会改变现场状态: 定案后**刷新页面**回到 HTML 默认态, 别留着半关半开的组合。
