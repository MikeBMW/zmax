# 在 VSCode 里把节点执行到「执行指令」那一行

用户说「节点右键打开源码, 要有断点, 我在 VSCode 里要看到你的执行指令, 你来操作」时的完整配方。
四件必须齐: **落点对 → 钩子真停 → 断点真下 → 配置别被覆盖**。

## 1. 落点 = 执行指令那一行, 不是 def run

`params.source_symbol` 放该行代码文本(`_line_of` 是 `lstrip().startswith(token)`), 行号自动跟随;
落到函数头用户会问「怎么在这里」。

## 2. 钩子: `debugpy.breakpoint()` 优先 —— 裸 `breakpoint()` 会静默失败

```python
if _os.getenv("ZMAX_BREAK_EXEC") == "1":       # 默认关 ⇒ 产线零影响
    try:
        import debugpy
        if debugpy.is_client_connected(): debugpy.breakpoint()
        else: breakpoint()
    except Exception:
        breakpoint()
u_vec = _ex.execute(np.asarray(u_sat, dtype=float))   # ← 钩子放在这条语句的上一行
```

- 无 tty / 非 debugpy 接管时, 裸 `breakpoint()` 落回 pdb 立刻抛 `BdbQuit`, 常被节点自己的
  `except Exception` 吞掉 ⇒ 程序默默跑完, 用户只看到「没停」。**参数校验失败** 空异常串就是它的指纹。
- 停住时 `u_sat` 已绑定、`u_vec` 还没有 ⇒ 验收 = **F10 后行号 +1 且 `u_vec` 有值**。

## 3. 下断点走键盘, 选配置走命令面板

```bash
code -r -g "<abs path>/node_impl.py:<行>"      # 在已开的窗口里定位
# Ctrl+G → 行号 → F9  : 断点是会话态, 手改 JSON 不会写入, 「要有断点」必须真按一次
# Ctrl+Shift+P → "Debug: Select and Start Debugging" → 输入配置名 → Enter
```

- 配置名用 **ASCII 前缀**(`DEBUG-EXEC-96 …`): 自动化输入打不了中文, 下拉框又不可靠。
- 判据 = `pgrep -af <入口>.py` 有 pid 且 F10 后行号推进; 不要只读面板上的 `Running` 字样。

## 4. 手写的 launch.json 会被 VSCode 回存覆盖

VSCode 编辑器里开着那份文件时, 它用**内存旧副本**保存 ⇒ 你刚写的多配置变回单配置。
起调试前**回读一次**; 配置至少含 `program` / `args` / `python`(绝对解释器) / `cwd` /
`console: integratedTerminal` / `justMyCode: false` / `env`(钩子开关 + 单线程 + 注入值)。

## 5. 一个容易被当成 bug 的设计

节点每拍 `new` 一个执行器实例 ⇒ 「上一拍」只能放**类级**共享字段, 这是必要的;
但忘了复位就会拿上一轮末拍做差分、误报变化率 ⇒ 加锁 + 时间间隔判新周期 + 显式 `reset()`, 并在新一次下发前调用。
