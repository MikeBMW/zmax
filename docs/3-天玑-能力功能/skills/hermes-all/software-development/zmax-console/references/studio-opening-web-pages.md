# 从 studio 里打开一个网页/新窗口 (含 snap 版 chromium 的坑)

适用: GUI 里加"点节点/按钮 → 打开某个本地页面"(三维可视化页、看板、报告页)。

## 结论先行

**用 PyQt5 QtWebEngine 在应用内开 windowless 的 `QDialog`,不要 spawn 外部浏览器。**

```python
def _open_page(self, url):
    w = getattr(self, "_win", None)
    if w is not None and w.isVisible():        # 复用同窗, 不叠一堆窗口
        w.raise_(); w.activateWindow(); w.view.reload(); return
    from PyQt5.QtCore import Qt, QUrl
    from PyQt5.QtWidgets import QDialog, QVBoxLayout
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    dlg = QDialog(self); dlg.setWindowModality(Qt.NonModal); dlg.resize(1180, 780)
    lay = QVBoxLayout(dlg); lay.setContentsMargins(0, 0, 0, 0)
    view = QWebEngineView(dlg); view.load(QUrl(url)); lay.addWidget(view)
    dlg.view = view; self._win = dlg; dlg.show()
```

- gui-venv 里已装 `PyQt5.QtWebEngineWidgets`; WebGL 正常(实测五瓣曲面/深度缓冲正常渲染)。
- 开窗前先探 `url + "health"` (2s 超时); 不通就 log 启动命令, 别让人对着空白页猜。
- 句柄必须存到 `self`, 否则 `QDialog` 被 GC 掉, 窗口一闪就没。

## 为什么不能 spawn 外部浏览器 (四条, 全部实测过)

| 路径 | 现象 |
|---|---|
| `xdg-open <url>` | 只往**已开着**的 Chromium 塞一个标签页 ⇒ 用户眼前没变化, 口径就是"双击没反应" |
| `Popen(["chromium", "--app=…"])` | snap 版从 studio 的 cgroup(终端派生)拉起被 snapd 拒: `… is not a snap cgroup for tag snap.chromium.chromium`, 进程立刻退; **Popen 仍返回成功** ⇒ 只看返回值会误判已打开 |
| `systemd-run --user --scope chromium …` | 同一个 cgroup 拒绝, 不开窗 |
| `--user-data-dir=$HOME/.hidden` | snap 的 home 接口**禁 $HOME 下的点目录** ⇒ `Failed to create …/SingletonLock: Permission denied` 后静默退出; 换非点开头目录(`~/xxx_profile`)才行 |

判断"到底开没开": `wmctrl -l | grep <页面标题>` 数窗口, 别信 exit code / Popen 返回值。

## 取证通道: `ss_node <关键字>`

命令通道(`echo "ss_node 十维流形引擎" > /tmp/zmax_nav_cmd`)按节点名**子串**找节点, 直接调
`scene.on_node_activated(node)` —— 与真双击走同一条代码路径, 不必去屏幕上找像素/算画布坐标。

- 未命中先 `_open_ss_canvas_cmd()` 再 `_oneshot(self, 2500, retry)`, 别在画布还没加载时判"没有这个节点"。
- 命中/未命中都 **print 节点总数**(`共 N 节点`) —— 这是"画布到底加载了几个节点"最直接的口径, 日志里有它就能区分
  "节点不存在" 与 "画布没加载" 两种完全不同的原因。
