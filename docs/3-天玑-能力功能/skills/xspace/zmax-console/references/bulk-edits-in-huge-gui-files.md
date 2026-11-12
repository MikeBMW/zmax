# 在几万行的 GUI 文件里成批改代码 (studio.py / simulink_module.py)

`tools/gui/studio.py` ~18.7k 行, `tools/gui/simulink_module.py` ~18.7k 行、1.1MB。改这类文件只有一条安全路径:
**锚点整块替换 + 每批改完跑四道验证**。

## 铁律
- **`patch` 只用来真改, 绝不能当探针。** 想确认一段文本是否存在, 用 `search_files`/`grep -n`;
  `patch(old, new)` 一旦命中就**已经写盘**了。曾把 `new_string="X"` 当"试探能否匹配", 结果那一行代码
  真的变成了裸 `X`(语法能过、运行 NameError), 而工具返回的是 success —— 不报错不等于没改坏。
- **绝不 `write_file` 整文件重写**(会静默丢内容, 且工具会因"未完整读过"拒写一半)。一律 `patch`。
- **删块时把整块(含初始化)一起替换**, 不要逐行删: 删 handler 却留下 `dlg = QDialog(self)` / `from PyQt5.QtWidgets import …`
  之类的前置行, 会引入 undefined name 而 py_compile **照样通过**(只在运行时炸)。

## 每批改完的四道验证 (缺一不可)
```bash
cd ~/zmax
./gui-venv311/bin/python -m py_compile tools/gui/studio.py tools/gui/simulink_module.py   # ① 语法
./gui-venv311/bin/python - <<'PY'                                                        # ② 裸 name 语句
import ast
for f in ('tools/gui/studio.py','tools/gui/simulink_module.py'):
    t=ast.parse(open(f,encoding='utf-8').read())
    print(f, [n.lineno for n in ast.walk(t) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Name)])
PY
QT_QPA_PLATFORM=offscreen timeout 120 ./gui-venv311/bin/python -c \
  "import importlib.util as u;s=u.spec_from_file_location('m','tools/gui/simulink_module.py');m=u.module_from_spec(s);s.loader.exec_module(m);print('IMPORT_OK',flush=True)"
# ④ 目标字符串计数 (删云端入口/删旧地址时用: 改前改后各数一次, 差值要对上你改的处数)
grep -c '<被删的域名或标记>' tools/gui/simulink_module.py
```
- ② 专治①的盲区: 替换成裸变量名 / 删掉初始化后, 语法仍是合法 Python。
- ③ 的结论行用 `flush=True` 写: 模块顶层会打自己的日志, 用 `| tail -3` 会把结论挤掉, 看着像没跑。
- Pyright/LSP 在这种文件上会报大量 `Import "PyQt5" could not be resolved` —— **那是它看不到 venv 的既有噪音**,
  只盯 `reportUndefinedVariable` 这类新引入的错。

## 删一个"打开外部页面/上传到外部"的功能 (常见整类改动)
1. 先 `search_files` 把该功能的**所有落点**列出来: 按钮创建行、`clicked.connect`、handler、`_xxx_url` 常量、
   打开 URL 的方法、节点 `desc`/副标题文案、日志里打印链接的行。少改一处就留下死链。
2. 按"给本机替代动作 或 给明确说法"二选一改: 能本地生成的换成「复制到剪贴板 / 存本地文件 + 打印绝对路径」;
   只能打开外部页面的, 改指本机在役页并**先探活再打开**(`urlopen(..., timeout=2)` 200 才开), 没起就如实说。
3. 删完用 ④ 数一次残留, 逐个判定: 注释/文档里的留; 活代码里的要么删要么明确报告"出站已封, 失败极快并回退"。
4. 界面改动**要重开控制台才生效**; 用户正在看的时候不得自行重启(运行纪律照旧, 只可停)。
