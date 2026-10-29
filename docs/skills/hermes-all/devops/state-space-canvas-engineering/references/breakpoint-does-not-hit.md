# 断点不进 / "没反应" 的取证工具集（只读，不改被测程序）

前提：不相信“日志说成功了”“我刚改好了”，也不相信用户描述的间接结论。
四个观测面：**窗口 → 界面文字 → 进程栈 → 进程环境/产物文件**。

## 1. 哪个窗口在前台（VSCode 打开的是不是这个工作区）
```bash
wmctrl -l                       # 窗口 ID + 标题；标题常带打开的文件绝对/波浪号路径
xdotool getwindowgeometry <0xID>
```
标题是判据：`~/zmax/.../execution.py - Visual Studio Code` 说明 VSCode 确实开着那个文件；
没有 VSCode 窗口就说明用户所谓的“在 VSCode 里打断点”根本不存在。

## 2. 拽到前台截屏 + OCR（读界面自己写的状态）
```bash
echo $DISPLAY                                  # 必须是 :0 这类真实会话
xdotool windowactivate --sync <0xID>; sleep 1; scrot -o /tmp/s.png
tesseract /tmp/s.png /tmp/s -l chi_sim+eng     # 全文
tesseract /tmp/s.png /tmp/st -l chi_sim+eng tsv   # 每词 x/y/w/h
awk -F'\t' 'NR>1 && $12 ~ /运行|执行器/ {printf "%s @ %d,%d\n", $12, $7+$9/2, $8+$10/2}' /tmp/st.tsv
```
- 界面上的字样比任何推理都硬：「未运行(没点 ▶ 运行)」「帧龄 9.15s」= 引擎停着。
- 大图先裁再 OCR（PIL `crop` + `LANCZOS` 放大）比整屏识别准；4K 屏全屏 OCR 会把字糊成一行。
- `tsv` 的坐标可直接喂 `xdotool mousemove x y click 3`，用来自己点一次那个控件。

## 3. 进程真在干什么（决定性，一眼拆穿“两个进程”）
```bash
py-spy dump --pid <pid> | head -40
```
- 主线程栈只有 `paintEvent → <画图函数>` ⇒ 这个进程没在跑业务，只在重绘。
- 栈里出现 `debugpy/adapter/launcher` ⇒ 它是 VSCode 起的调试进程。
- 树里出现 `state_space_sim/engine` ⇒ 它真的在跑引擎（而不是“界面有数”就等于在跑）。

## 4. 启动环境到底有没有进进程
```bash
tr '\0' '\n' < /proc/<pid>/environ | grep -E 'ZMAX_|PYDEVD|OMP_NUM'
tr '\0' ' '  < /proc/<pid>/cmdline      # 有没有 -X frozen_modules=off
```
`launch.json` 写了不代表进了进程；**只有 /proc 是事实**。全空 ⇒ 先去查 launch 模板是否把文件重写回去了。

## 5. 谁在写活真源（区分“常驻服务在跑”与“我的进程在跑”）
```bash
ls -l --time-style=+%H:%M:%S <live_dir>/*.json      # mtime 距今多久、哪个最鲜
sudo lsof <live_dir>/<file>.json                   # 谁打开的
```
文件在更新 ≠ 你的进程在跑。常见误判：`engine_latest.json` 是常驻服务写的，GUI 不写它（GUI 只写播放态/轨迹）。
判“GUI 有没有自己跑引擎”要看 GUI 侧产物（记账文件、它自己的日志行），不是这个文件。

## 6. 记账文件：回答“这个函数被调用了吗、哪个 pid”
在函数入口（放在被测逻辑之前、且不影响关键函数的行号）追加：
```python
with open(os.path.join(ROOT, "ss_live", "<who>_calls.log"), "a", encoding="utf-8") as f:
    f.write("%s pid=%s tag=%s\n" % (time.strftime("%H:%M:%S"), os.getpid(), tag))
```
读法：
- `wc -l` → 一轮调用多少次（一轮 369 次说明引擎真的在跑）
- `awk '{print $2}' | sort -u` → 是哪个 pid（与你 `ps -o lstart= -p` 对齐就是你的进程）
- `tail -3` → 最近是什么时候

🔴 `ROOT` 一定要按文件**真实目录层级**上溯并回读验证；少一层就写到不存在的目录，被 `except: pass` 吞掉，
得到“代码在、日志永远空”的假象——排查代价极高。写完先造一次真实调用证明文件真的产出。

## 7. 两个进程 vs 一个进程的典型形态
| 现象 | 真因 |
|---|---|
| 界面有数据、帧龄几秒，但断点永不进 | 常驻服务在跑业务；GUI 只显示 |
| 界面写“未运行”，但有数 | 数是别人写的（服务/上一个进程），不是它 |
| 启动时停一次，之后再运行不停 | 兜底断点用“只停一次”去重，或整轮跑完落在时间窗内 |
| 右键运行节点什么都没发生 | 轨迹取不到就中止 / 节点执行的 except 静默吞 |

## 8. 「取消断点后再添加就不进」= 模块没有 loader

这是与"代码没执行"完全不同的故障: **第一次能停、取消再添加就不进**。机制不是行为, 是绑定:

| 加载方式 | `__spec__` / `__loader__` | 首次绑定 | 取消后重新添加 |
|---|---|---|---|
| `exec(compile(src, path, "exec"))` | 都 None | 按 `co_filename` 能命中 | **没有 loader 可重新定位 ⇒ 静默不绑** |
| `spec_from_file_location` + `sys.modules[name] = m` | SourceFileLoader | 命中 | 命中 |

所以「为了断点能绑上而改成 exec」是反向操作 —— 它买到了首次绑定, 弄丢了重新绑定。

正确写法（三处加载器统一: 引擎 `runtime._load` / `sim._load` / 注册表 `_ss_import`）:
```python
spec = importlib.util.spec_from_file_location(mod_name, path)
m = importlib.util.module_from_spec(spec)
sys.modules[mod_name] = m      # pydevd 按模块名解析文件; dataclass 也查这里
spec.loader.exec_module(m)
```
`exec(compile())` 只保留为降级分支, 且**必须打印告警**（"无 __spec__, 断点取消/重加会失效"）。

验收（一条命令跑完四项）:
```python
m = _ss_import('execution')
print(m.__spec__ is not None, type(m.__spec__.loader).__name__, 'state_space.execution' in sys.modules)
print(m.RobotExecutor.execute.__code__.co_filename)   # 必须与文件绝对路径逐字相同
```
只要 `__spec__` 为 None, 就别再浪费轮次重启 —— 先把加载方式改对。

## 9. 让 GUI 自己跑一轮（否则断点无处可停）+ 什么算"停对了"

调试进程若只在重绘, 代码永远跑不到断点。调试档（`ZMAX_DEBUG_MODE=1`, 由 launch env 带入）下让 GUI
启动后**自动跑一轮引擎**, 是让"有代码在跑"不依赖用户记不记得点 ▶ 运行的可重复做法:
- 主窗口是**异步建好的** ⇒ 用 1s 轮询找"带运行入口的窗口实例"再调, 不要一次性 `singleShot` 就假定窗口已存在
  (`topLevelWidgets` 常在 `app.exec_()` 之前还拿不到; 换成遍历 `app.allWidgets()` + 重试上限)。
- 留逃生口 `ZMAX_AUTO_RUN=0`; 自动跑只属调试档, 不能推广成"打开就自动播放"。

"停对了"的三条硬指标（缺一条就別说改好了）:
1. 记账文件多出一批行, pid == 调试进程 (`tail` + `awk '{print $2}' | sort -u`);
2. 一轮的调用次数是**几百量级**（引擎逐步调用）而不是 1 次;
3. 停住时 VSCode 高亮的是"下一条语句" —— 因此 `_brk()` 在 `a = np.asarray(...)` 上一行停住, 界面看起来
   像停在普通赋值行。用户会问"我没在这行打断点怎么停了", 先把这条讲清楚。
