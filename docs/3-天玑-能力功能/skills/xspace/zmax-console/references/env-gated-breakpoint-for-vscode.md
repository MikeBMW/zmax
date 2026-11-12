# 给用户一个 VSCode 断点, 停在某个函数的 return (且不挂死常驻服务)

用户说「用 VSCode 定义一个断点, 停在 X 的输出 return, 我看看实际的输出」时, 交付物是:
**能按的断点 + 驱动脚本 + launch 配置 + 已跑出来的真实数值** —— 不是"你去那一行点一下"。

## 步骤
1. **断点用环境变量门控**(关键): 在目标 `return` 前插
   ```python
   import os as _os_dbg
   if _os_dbg.environ.get("ZMAX_DEBUG_<X>") == "1":
       breakpoint()          # ← 局部变量在此可看
   ```
   常驻服务/回路不设该变量 ⇒ **完全不受影响**。裸 `breakpoint()` 会在无人值守进程里掉进 pdb 挂死;
   只有在 debugpy/`python -m pdb` 接管时它才是个断点。
2. **驱动脚本**(`tools/debug_<topic>_output.py`): 从**真实数据源**构造输入(在役 jsonl 最后一行 /
   现场几何常数 / 满通道), 每次调用都进断点; 同时支持 `--no-break` 只打印数值, 让结论可入汇报。
3. **launch 配置**: `type: python` · `request: launch` · `program` 驱动脚本绝对路径 · `python` 解释器绝对路径 ·
   `cwd` 仓库根 · `console: integratedTerminal` · `justMyCode: false` · `env` 带门控开关。
   仓库用了多根工作区(`*.code-workspace`)时**两处都加**: `.vscode/launch.json` 与 workspace 的 `"launch"` 块,
   否则用户从工作区打开时看不到配置。
4. **自己先证断点真能停**, 并把停住时的数值一并报出:
   ```bash
   cd ~/zmax && printf 'c\np x.shape\np x[:3]\nq\n' | ZMAX_DEBUG_X=1 ./gui-venv311/bin/python -m pdb tools/debug_topic_output.py
   ```
   要看到 `> /abs/path.py(NN)func() -> return x` + 变量值。

## 坑
- **大文件只读尾行**: 80MB+ 的 jsonl 用 `seek(0, SEEK_END)` 读尾 8KB, 再倒着找最后一个 `{`, 别整文件读。
- **落盘字段与预期不符是常态**: 字段可能是"JSON 套 JSON"的字符串(真值在顶层别的键)、某段可能全 0
  (现场缺几何/触觉源)。驱动脚本要 `isinstance` 守卫, 并在输出里**标明哪几段有真值、哪几段是 0 及原因**;
  把 0 说成"误差为零"是谎报。
- 行号会随后续改动漂移: 交付时给"绝对路径 + 行号 + 函数名 + launch 配置名"四件, 源码注释里写用法。
- 门控断点可长期留着(下次同问一条命令复现); 要清理就整段删, 别留裸 `breakpoint()`。
