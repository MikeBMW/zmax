# AR 页面 (8797/ar3d) 的启动与「窗口到底开没开」判据

控制台 AR 按钮走 `tools/gui/ss_dreamview.py::ar_launch()`: **先看窗口 → 没有才 spawn**,
spawn 三级(共享实例 → 独立 profile → 全新 profile), 每级都要等到"新窗口出现"才算成功。
所以**判据错一次的代价是三重 spawn 全跑一遍 + 一条假警告**, 用户看到的就是"按钮没反应"。

## 铁律
- **标题判据必须是多标记集合**, 不能写死一个页面标题。页面标题会改(例如改成
  「Z-MAX AR3D r95 · SIM自动 · 位置细胞 · 8802直播」这类), 单标记实现立刻永远判负。
  统一走 `_AR_TITLE_MARKS` + `ar_title_hit(title)`(内置 `TCP 轨迹 / AR/VR / AR3D / Z-MAX AR / 位置细胞 / 8802直播`);
  页面再换标题就往元组里加词, **不要**在各处复制判断式。
- **第二判据: 到 8797 的 ESTABLISHED 连接数**。页面一加载就会开 `/api/cams` 和各路流;
  chromium 在已有窗口里开**新标签页**时顶层标题不含页面名 ⇒ 只看标题会误判。
- **判"没窗口"前先看浏览器进程在不在**: 进程在、窗口表里没有 ⇒ 是窗口/判据问题;
  连进程都没有 ⇒ 才是 spawn/依赖问题。两类根因修法完全不同。
- snap chromium **新 profile 首启会弹 "Chromium Additional Terms of Service"** 对话框,
  那窗标题不带页面标记 ⇒ 照样被判负。复用既有 profile + `--no-first-run --no-default-browser-check`
  `--disable-session-crashed-bubble --noerrdialogs` 可避开。
- 改完判据**必须重开控制台**才生效(面板/模块在 `sys.modules` 里缓存)。

## 验证 (改判据后必做, 别只看代码)
```bash
# ① 真起一个 AR 窗口 (独立 profile, 后台)
cd ~/zmax && (DISPLAY=:0 setsid /snap/bin/chromium --user-data-dir=$PWD/zmax_data/ar_browser \
  --no-first-run --no-default-browser-check --window-size=1500,950 \
  "http://127.0.0.1:8797/ar3d" >/tmp/ar_open.log 2>&1 &)
# ② 窗口表里认不认得出
DISPLAY=:0 wmctrl -l | grep -E 'AR3D|位置细胞|TCP 轨迹'
# ③ 判据函数本身返回非空 id (空串 = 判负)
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python -c "
import importlib.util as u; s=u.spec_from_file_location('dv','tools/gui/ss_dreamview.py')
m=u.module_from_spec(s); s.loader.exec_module(m)
print('ar_window_seen ->', repr(m.ar_window_seen(3.0)))
print('hit 新/老/无关:', m.ar_title_hit('Z-MAX AR3D r95 · SIM自动'), m.ar_title_hit('TCP 轨迹 · AR/VR'), m.ar_title_hit('Visual Studio Code'))"
# ④ 页面与连接数
curl -s -o /dev/null -w 'ar3d=%{http_code}\n' http://127.0.0.1:8797/ar3d
ss -tn | grep -c ':8797.*ESTAB'
```
判据: ③ 返回 `0x...` 窗口 id; `hit` 新/老标题 True、无关窗口 False; ④ `/ar3d` 200(与 `/` 同一份页面, SPA 回退, 不带尾斜杠)。
