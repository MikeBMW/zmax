# Qt 界面取证: 样式表告警 / 控件可见性 / 终端噪声

什么时候看这个文件: 终端被 Qt 消息刷屏、控件拖不动/看不见、页内日志跑到终端。

## 1. "Could not parse stylesheet of object QPushButton(0x…)" 定位法

症状: 终端反复刷同一批地址 (几秒十几条), 界面看不出任何异常, 用户只说"这是什么? 不要显示"。

1. `qInstallMessageHandler` 里用正则从消息抠地址:
   `re.search(r"QPushButton\((0x[0-9a-f]+)\)", msg)`。
2. 枚举控件做**地址反查**: `int(sip.unwrapinstance(w))` 与消息里的 C++ 指针同值 ⇒ 直接点名是哪个按钮
   (实测定位到 3 个筛选按钮, 5s 内 18 条 / 6 个唯一地址)。
3. 真根因类别 (不是 Qt 抽风): 基础样式写成**裸声明**
   `background:...;border-radius:4px;padding:5px 12px;` (没有 `QPushButton{}` 包起来),
   后面又用 `b.styleSheet() + "QPushButton:checked{...}"` 拼接 ⇒ 裸声明直接跟选择器, 解析失败,
   每次 repolish 刷一条。修法: 把 base 包成 `QPushButton{...}` 规则块, 拼接就合法。
4. 保障: 主程序 `QApplication(...)` 之后装一层 handler, 只吞
   `Could not parse stylesheet` 与 `propagateSizeHints`, 其他 Qt 消息照打 (不要整类静音)。

🔴 handler 里打印中文必须走字节口:
```python
sys.stderr.buffer.write((msg + "\n").encode("utf-8", "replace")); sys.stderr.flush()
```
直接 `print(msg, file=sys.stderr)` 在 GUI 环境 (stderr 编码 ascii) 抛 `UnicodeEncodeError`,
消息会被静默丢掉, 看起来像"过滤器把它吃了"。

## 2. 页内日志不要刷终端

- 回放趟号 / 清空条数 / 重连这类"波形为什么变了"的说明: 进页内 `notes` + 状态行, **终端默认静默**。
- 要排障时给环境变量开关: `ZMAX_SIG_DEBUG=1` 才 `print`, 默认 `ZMAX_SIG_DEBUG` 未设不打印。
- 判据: 跑 8s 抓 stdout, 该前缀 0 条; 页内 notes 仍在累积 (信息没丢, 只是不上终端)。

## 3. 控件可见性取证 (删一行/并按钮之后)

```python
btns = [b for b in w.findChildren(QPushButton) if b.isVisible()]
rows = {}
for b in btns: rows.setdefault(b.mapTo(w, b.rect().topLeft()).y() // 10 * 10, []).append(b.text())
QApplication.topLevelWidgets()            # 多余顶层窗 = 有控件没 setParent 就 hide 了
max(b.mapTo(w, b.rect().topRight()).x())  # 与 w.width() 比, 判溢出/折行
```

- 隐藏控件必须 `setParent(self) + hide()`; 只 `hide()` 不 `setParent` 的在某些布局重排后会重新冒出来。
- 表格类列宽/表头规矩见 `references/dataspace-message-signal.md` §7; 面板瘦身口径见 §12。
- 列宽持久化读取回来是 `0:150,1:333,...` 这种串 (QSettings), 复位一定要给显式按钮, 别在刷新心跳里悄悄还原。

## 4. 改完必跑的取证顺序

1. `./gui-venv311/bin/python -m py_compile <改过的文件>`
2. 离屏/真屏探针: 读表头 `headerItem().text(i)` / `columnCount()` / 可见控件列表
3. 真控制台构造 `StudioMainWindow()` 一次, 逐页 `setCurrentIndex(i)` 走一遍 (样式表告警只在这时出现)
4. `tools/ci/integrity_check.py` (版本五处一致) 与对应 `verify_*.py` 判据
