# 配置中心「导出文档」按钮 —— 注册表式接入 + 离屏真点判据

适用：用户说「这个功能要**由配置中心**在某个页里可以**导出 Word/PDF/Excel**」。
落点：`tools/gui/veh6_config_page.py`（VEH.6 配置中心，首屏 = 「📋 任务配置」）。

## 一、接入 = 往注册表加一项，不要另写执行体

页面已经有一套导出器注册表，**新增一个导出功能只改两处**：

```python
# ① tools/gui/veh6_config_page.py 顶部
DOC_SCRIPTS = {
    ...
    "<key>": ("<按钮长标题 (Word + PDF)>", "<tools/下的导出脚本名>.py", [<额外参数>]),
}
DOC_DIRS = [..., "<产物目录相对路径>"]        # 产物清单扫描用

# ② 要放按钮的那个页的按钮行
_b = _btn("📄 <按钮短名>", th)
_b.setToolTip("<产物绝对路径>\n<数据源>")
_b.clicked.connect(lambda: self._run_doc("<key>"))   # _run_doc 读 DOC_SCRIPTS[key] → _run_script(script, args)
```

- `_run_script(script, args)` 真跑 `tools/<script>` 并**把 stdout 摆到底部结果面板** —— 所以导出脚本的
  stdout 必须**自带产物绝对路径 + 结论行**（「点了必出结果」的口径）。
- `DOCS` 那个 dict 是「文档预览」页用的（`name` / `script` / `rel`），要在预览页内嵌看 docx 才加它；
  只导出不预览则 `DOC_SCRIPTS` 一项就够。
- 导出脚本本身要**能独立跑**（`--out` / `--check` 只校验 / `--json` 给 GUI 解析），GUI 与命令行**同一个执行体**。
- 任务配置页那排按钮里有的是走 `self._run_selected(<config_center 子命令>)` 的 —— 那是配置中心 CLI 命令，
  **不是**文档导出；加导出按钮别往那个元组列表里塞，单独一个 `_btn` 更清楚。

## 二、离屏判据（不重启用户在用的控制台）

`tools/verify_meta_doc_export.py` 是这个模板（实测 13/13 PASS）。要点：

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 离屏，不抢用户的控制台
sys.path.insert(0, "tools"); sys.path.insert(0, "tools/gui")
from PyQt5.QtWidgets import QApplication, QPushButton
app = QApplication.instance() or QApplication([])
import veh6_config_page as V
page = V.ConfigCenterPage()          # 无参构造即可
```

判据逐条（别只核「源码里有这个字符串」）：
1. `page.tabs` 里目标页存在，**且在 index 0**（首屏）。
2. 该页 `tabs.widget(i).findChildren(QPushButton)` 里有目标按钮（把全部按钮名打出来，便于看有没有挤掉/改名）。
3. 按钮 tooltip 写明产物路径。
4. `DOC_SCRIPTS[key]` 存在 + 指向的 `tools/<script>.py` **文件真存在**。
5. **真点一次**：先记三个产物的 `mtime`，`btn.click()` 后循环 `app.processEvents()` + `sleep(2)`，
   直到三者 `mtime` 都变新（导出含两趟 soffice 转换，实测 ~5s，给到 200s 上限）。
6. 底部结果面板（`page.out.toPlainText()`）里有产物绝对路径与结论行。

离屏跑的解释器：`gui-venv311/bin/python`（项目 venv 在仓库根，PyQt5 只装在那里）。

## 三、导出器的常见坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 从 HTML 直接 `--convert-to docx` | `no export filter for <x>.docx found` | HTML 被当 **Writer/Web** 文档 ⇒ 先 `.odt` 再 `.odt`→docx |
| 并发调 soffice 不带私有 profile | 第二次调用静默失败/挂住 | 每次都带 `-env:UserInstallation=file://<临时目录>` |
| 导出脚本只 print 结果、不 print 路径 | 用户点了看不到产物在哪 | stdout 固定三段：结论行 + `md/docx/pdf` 各一路绝对路径 |
| 一致性校验放在文档生成之后 | 真源漂了还照出文档 | 生成前先跑校验，`--check` 只校验；不一致就 exit 非 0 |
| 产物落在 `outputs/`（软链目录） | `git add` 报 `beyond a symbolic link` | 交付件按稳定名落 `docs/deliverables/` |
