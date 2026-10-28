# 画布节点「打开源代码」与「运行/停止」按钮的配套做法

## 一、右键「打开源代码」弹「该节点未配置源码映射 (params.source)」

三条真因（按出现频率排序）：

1. 画布节点 params 里没写 source —— 但中间件节点模块 `src/lerobot/middleware/nodes/n_*.py` 已声明 `SOURCE` / `SOURCE_SYMBOL`。
2. **GUI 现场节点的 id 与磁盘画布文件里的 id 不一致**：GUI 会给现场节点生成 `n<时间戳><随机>` 的 id，而解析函数是拿这个 id 去读磁盘画布查 spec ⇒ 查不到 ⇒ 直接弹窗，即使该节点自己 params 里就写着 source。这条最容易漏，因为「明明配了却打不开」。
3. 少数纯组合节点两处都没声明，只剩注册表登记的 `file` / `line`。

解析顺序（`src/lerobot/middleware/open_target.py` + `spec.py`，三层兜底）：

```
节点自带 params.source  →  中间件模块 SOURCE/SOURCE_SYMBOL（按 NODE_ID 匹配 nodes/*.py）
                        →  注册表 registry.get(impl_key)['file'/'line']
```

实现要点：

- 节点自带 params **必须最高优先**。它是 GUI 现场真值，不要先按 id 查盘再回落——id 一失配就永远回落不到。
- spec 层回落用**文本正则**读模块（`^SOURCE\s*=\s*['\"]([^'\"]+)`），不要 import 节点模块（有副作用、慢），结果按 nid 缓存。
- 取证判据（不猜，直接跑）：遍历 `parse_canvas()[0]` 每个 spec 调 `resolve_open_target(spec)`，要求 `impl_path` 非空。全画布 79/79 可解析即通过（改前 66）。
- `open_in_vscode` 受产品档控制（`zmax_profile.vscode_ok()`），非调试档不会开 VSCode ⇒ 必须在调试档验证「命令真的发起」：monkeypatch `subprocess.Popen` 记录 argv，期望 `code ZMAX.code-workspace -g <file>:<line>`，行号落在 `def run` 那一行。
- 改 `src/lerobot/middleware/*.py` 后**必须重启控制台**：模块已在进程内缓存，不重启用户会复述「还是打不开」。重启前先比对改动 mtime 与进程 lstart，别让用户在旧进程上验证。

## 二、画布「▶ 运行 / ■ 停止」按钮的配套

- 播放态按钮文字的唯一写者 = `_ar_play_ui()`；在 `btn_run.setText` 写入点拦截（play 期间强制播放态文字），不要用轮询去纠写者——互抢就是用户看到的「运行/停止跳变」。
- 每个收尾分支都要守卫：`_flow_next` / worker finished / `_recover_run_btn` / `_on_real_poll` / `_ss_finish` / `stop_sim` 里写 `▶ 运行` 前加 `if not self._ar_playing():`。
- **`btn_stop` 必须显式点亮**：AR 类分支如果不碰 btn_stop，它会停在上一次运行结束时的灰色。进入播放 `setEnabled(True)`，`_ar_play_ui` 再兜一层。用户会立刻发现「停止按钮应该亮了」。
- `stop_sim()` 开头先写 `ar_play action=stop` 并解播放态，再走原有逻辑——否则播放期的只读锁会把按钮永久卡在「停止 AR 播放」。
- 离屏验证模板：`QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python` 起真模块，点一次运行 → 断言按钮文字/标题/`btn_stop.isEnabled()`；再模拟外部每 0.5s 强写 `▶ 运行` 持续数秒，断言期间文字只有一种取值。
