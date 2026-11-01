# 配置中心 UI 文案增删 (veh6_config_page · 北斗七星阵图条)

## 何时用
老倪说「某页这句话删掉 / 加一句 / 换个说法 / 这里不该显示」。配置中心的文案**几乎都不是字面量**，直接 grep 原句改不到渲染处。

## 三步走

### 1. 先找真渲染点，别只 grep 原句
- 页顶阵图条的「本页真源: …」= `tools/gui/veh6_config_page.py::_star_facts()` 现算字典 → `_sync_star_banner()` → `ss_seven_stars.py::StarBanner.set_tab(facts=...)` 里拼 `"本页真源: " + _fact`。
- 原句由 f-string 拼出（`"当前 %s · 真源改于 %s · 三档 %s"`）⇒ grep 整句通常只命中注释/文档/判据，改那些一律无效。
- 同一份摘要还有两个消费者：底部信息窗 `_page_out_text()`、左树 hover tooltip。改页顶时把这两个算清楚。

### 2. 在**渲染入口**过滤，不动数据源
- 加模块级名单，例：`BANNER_FACT_HIDDEN = ("prod",)`，在 `_sync_star_banner()` 传参时过滤：
  `facts={k: v for k, v in _star_facts().items() if k not in BANNER_FACT_HIDDEN}`
- **不要删 `_star_facts()` 里的键**：tooltip、底部信息窗、判据里「真源改于 = 文件 mtime」这条证据都读它；删键会连带把判据弄红、把现场证据弄丢。

### 3. 判据跟着真实现走（同一版内改完）
- `tools/verify_config_center_seven_stars.py` ⑪ 原本断言“每颗星页顶都有「本页真源」”，删了就要改成“**该页必须没有** + 其余页仍必须有”，并在 ❌ 分支打印残余文案（防它悄悄回来）。
- 隐藏名单从实现模块读，不在判据里另抄一份页名：
  `_hidden = tuple(getattr(V, "BANNER_FACT_HIDDEN", ()))`
- 判据不是“钉死某种呈现位置”，而是钉住**当前实现**：删/移/改名后不清算旧断言 = 交付一片红。

## 验收（离屏真跑，三条都要绿）
```bash
cd ~/zmax
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_center_seven_stars.py    # 期望 20/20
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_page_product_sync.py     # 期望 8/8 (⑧ 靠 tooltip 仍带「真源改于」)
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_product_ui.py                   # 期望 47/47
```
`verify_config_page_product_sync.py` ⑨ 会真写真源(550A → 写回原值)；跑完确认 `git status` 里 `config/platform/zmax_product.json` 无改动（它靠 sha 还原，mtime 会变是正常的）。

## 页缓存：改完在跑的控制台里看不到
- `studio.py` 启动时 `build_config_center()` 只建一次，`self.cfg_page` 缓存进 shell；换页签/重进配置中心都**不会重建** ⇒ 在跑的窗口仍是旧控件。
- **不要自己主动反复重启控制台**（老倪明令禁止）。报告口径：代码与判据已绿 + 「重开一次控制台才生效」，等他发话。
- 他说「你重启」就按下面**一次**重启，别让他自己动手、别多刷。

## 重启一次的标准动作（他自己发话时）
控制台是 systemd **用户**服务，别手搓 `python studio.py`：
```bash
grep -n 'ExecStart' ~/.config/systemd/user/zmax-studio.service   # → tools/gui/launch_studio.sh
pgrep -af '^[^ ]*gui-venv311/bin/python studio\.py$'            # 锚定整条 cmdline, 别人可能手动起过
kill -TERM <旧pid>; 等 10s; 仍在则 kill -9
systemctl --user start zmax-studio.service; systemctl --user is-active zmax-studio.service
```
- 🔴 **必须先 TERM 旧实例再 start**：`launch_studio.sh` 开头有「已在跑 → 只 `xdotool windowactivate` 激活旧窗口 + exit 0」守卫 ⇒ 直接 start 会「返回成功但没换进程」。（同「重启包装脚本拒绝重启却 exit 0」的坑）
- 就绪判据：`DISPLAY=:0 xdotool search --onlyvisible --name "XSpace ZMAX"` 轮询出 id（本机 ~4.5s），**不要 sleep 固定秒数**；再 `tail /tmp/studio_launch.log` + `journalctl --user -u zmax-studio.service --since -3min | grep -iE 'traceback|error|失败'` 确认无栈。
- 脚本自己会处理 `QT_QPA_PLATFORM=xcb`、DBUS 总线、信号库守护、清空 `/tmp/zmax_nav_cmd` —— 别在外层再 export offscreen 之类的变量（会继承进去把窗口弄没）。

## 改完的实机取证（不看代码，看真窗口）
离屏判据只证代码路径，**改文案必须再拿在跑窗口的 OCR 对照**，否则「这页没了」和「整块都没了」分不开：
1. 导航：`printf 'config\n' > /tmp/zmax_nav_cmd` 把窗口带到配置中心（落点通常是功能配置页，不是产品页）。
2. 截全屏：`DISPLAY=:0 scrot /tmp/cc.png`（机器上无 `import`；`scrot -u` 只截聚焦窗口，够用时更净）。
3. 定位并点左树目标行：`tesseract /tmp/cc.png out -l chi_sim --psm 6 tsv` → awk 取文本列的 `left/top/width/height`（左树在 `left<520`，行距 ~85px），`xdotool mousemove X Y click 1`。
4. 复核：再截一张，OCR 分别 grep **被删的那句**与**同族保留的句子**——本次即产品页无「本页真源」、功能配置页仍有「本页真源: 功能配置 1/3 就绪」，这才证明是「只删了这一页」。
5. 报告里给截图绝对路径（CLI 无附件通道），并如实写明：底部信息窗那句是否保留、跑判据改到的 mtime、以及日志里与本次无关的既有告警。

## 报告口径（老倪只要结果）
一句话说清：删/加了什么 · 在哪一层动的（渲染口 vs 数据源）· 数据是否仍在 · 跑了哪几条判据 + 各自数字 · 是否需要重启才可见。不要贴代码 diff。

## 当前刻意保留的缺口（别当 bug 修回去）
- 产品配置(天枢)页顶**不显示**「本页真源: 当前 550B · 真源改于 … · 三档 …」——按老倪要求删掉（产品页本身就是选三档的地方，重复）。数据仍在 `_star_facts()["prod"]`，左树 tooltip / 底部信息窗照旧显示。
