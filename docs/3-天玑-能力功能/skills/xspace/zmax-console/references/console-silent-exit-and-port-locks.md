# 控制台"起了但没窗口" —— 先查单实例锁的端口冲突

## 症状
`studio.py` 启动后**立刻 exit 0、日志 0 行、没有窗口**, 没有任何堆栈。(不是缺 PyQt5、不是 DISPLAY、不是依赖)

## 机制
`tools/gui/studio.py::_single_instance_guard()` 用 **bind 一个固定端口** 当单实例锁。
历史上锁端口 = **8795**, 而 `tools/hil_local_api.py` 恰好就在 `0.0.0.0:8795` 起 HTTP(手机 HIL 面板)
⇒ 两者互斥: 谁先起谁占口。

- HIL API 先起 ⇒ 控制台 bind 失败 ⇒ 判定"已经有一个在运行" ⇒ 直接退出。
- 控制台先起 ⇒ HIL API bind 失败 ⇒ 手机 HIL 面板 8795 打不开。
- 更坑: 退出路径是 `os._exit(...)` 跳过解释器 finalize(**故意的**, 为了不触发 QThread abort),
  但它也**跳过了 stdout flush** ⇒ 那句"已经有一个控制台在运行"根本落不了盘 ⇒ 看不出来。

## 诊断三步(顺序别换)
```bash
ss -ltn | grep -E ':(8795|8793|8797|8802|8895)\b'        # ① 谁在这个端口上听
ss -ltnp | grep 8795                                     #    持有着是 hil_local_api 还是 studio
grep -n '_single_instance_guard' -A12 tools/gui/studio.py  # ② 锁绑的是哪个端口
```
③ 结论: **锁端口必须与任何对外服务分开** (现锁在 8895, HIL API 继续用 8795)。

## 启动与验收
```bash
# 启动(禁自行 restart 的纪律照旧: 用户点名才起) —— 用工具后台, 不要 nohup/&(会被拦)
terminal(background=true, persist_on_release=true,
         command="cd ~/zmax && DISPLAY=:0 ./gui-venv311/bin/python tools/gui/studio.py > /tmp/studio_boot.log 2>&1")
```
**三条同时成立才算起来**(任一条缺都不算, 单看进程/端口会被旧实例或别的服务骗):
1. `wmctrl -l` 里出现 `XSpace ZMAX` 窗口  2. 锁端口(`8895`)在听  3. 对外服务 `8795 /health = 200`

## 推论(同类坑)
- 任何"静默 exit 0 + 无日志"的 GUI/常驻启动, 第一嫌疑是**资源锁被占**(端口/文件锁), 不是代码坏。
- 用 `os._exit` 收尾的程序, **崩溃前的 print 都会丢** ⇒ 排查时先把它那几条判断打印改成写文件,
  或临时用 `python -u` / 重定向并在 exit 前手动 `flush`。
- 改端口这类修复**要重启 GUI 才生效**; 用户正在看的时候不得自行重启。

## 姊妹坑: 外部窗口「出没出来」也别只认页面标题
同一个毛病换个方向再犯一次: 控制台点「打开 AR 页面」→ 窗口真的弹出去了, 但判据拿固定字符串匹配 `wmctrl`
标题(只认「TCP 轨迹」「AR/VR」), 页面 `<title>` 改成「Z-MAX AR3D r95 · …」后一个标记都不命中
⇒ 报「浏览器没开新窗口」并再 spawn 两遍。定式(标记集合 + 连接数二级判据 + 真浏览器验收):
`references/ar-window-presence-check.md`。一句话规则: **判据要找“稳定语义标记 + 第二路证据”, 不绑单一字符串。**
