# 「窗口到底出没出来」判据 —— 别只认页面标题里的某几个字

## 症状
点「打开浏览器页面」按钮, 页面其实已经弹出来, 界面却回一条「浏览器没开新窗口 ⇒ 窗口可能被挡/开了标签页」,
连点几次日志重复同一条。spawn 日志(`zmax_data/logs/ar_browser.log`)里 fast / iso / fresh 三级都跑过,
除了 snap cgroup 警告没有任何报错。

## 根因
判据用固定字符串匹配 `wmctrl` 顶层标题(只认「TCP 轨迹」「AR/VR」)。页面 `<title>` 改过之后
(现为「Z-MAX AR3D r95 · SIM自动 · 位置细胞 · 8802直播」)一个标记都不命中 ⇒ **窗口在, 判据说不在**。
出窗失败又会触发下一级 spawn, 三级跑完后给用户一条完全误导的「可能被挡」警告。

## 定式
1. 一个模块级标记集合 + 单一判定函数, 所有窗口标题判断只走它:
```python
_AR_TITLE_MARKS = ("TCP 轨迹", "AR/VR", "AR3D", "Z-MAX AR", "位置细胞", "8802直播")

def ar_title_hit(title: str) -> bool:
    return any(_m in (title or "") for _m in _AR_TITLE_MARKS)
```
2. 三个调用点一起换: `ar_window_seen`(点击前看已开)、`ar_wait_new_window`(spawn 后等新窗口)、
   以及任何「标题 == 页面」的旁路判断。只改一处 ⇒ 另一处继续误判, 表现为时好时坏。
3. 标记取**页面稳定语义词**(产品名 + 页面主题), 不要取版本号/档位/时间这类易变串; 标题再改只加词。
4. 二级判据兜底: 标题不命中时看「到该端口的 ESTAB 连接数有没有变多」(页面加载必开 `/api/cams` + 流),
   比「认任何新窗口」准 —— 在已有窗口里开新标签页时, 顶层标题根本不含页面标题。

## 验收(必须自己起一次真浏览器, 不许只看日志下结论)
```bash
(DISPLAY=:0 setsid /snap/bin/chromium --user-data-dir=$PWD/zmax_data/ar_browser \
   --no-first-run --no-default-browser-check --window-size=1500,950 URL >/tmp/ar.log 2>&1 &)
sleep 6; DISPLAY=:0 wmctrl -l | grep -iE 'AR3D|AR/VR|轨迹'
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python -c "
import importlib.util as u,sys; sys.path.insert(0,'.')
s=u.spec_from_file_location('dv','tools/gui/ss_dreamview.py'); m=u.module_from_spec(s); s.loader.exec_module(m)
print(repr(m.ar_window_seen(3.0)))"
```
修前返回空串, 修后返回窗口 id(形如 `0x04000003`)才算过; 再单独断言标记函数: 新标题 True / 老标题 True /
无关窗口(如 `Visual Studio Code`)False。

## 常见坑
- snap chromium 配全新 `--user-data-dir` ⇒ 首个窗口是「Chromium Additional Terms of Service」, 页面根本没加载,
  任何标题判据都命不中。判定测试要用在役 profile, 或先手工接受一次 ToS。
- `webbrowser.open()` 的返回值不可信(实测返回 True 什么窗口都没起), 判据只认 `wmctrl -l` 真窗口表。
- 改完判据 ≠ 生效: 控制台进程里是旧代码, 不重开控制台按钮还会照旧误报(只可停不可自行重启)。
