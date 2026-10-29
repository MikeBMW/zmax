# 画布节点「打开源代码」: 四层解析与补齐

用户右键节点 →「打开源代码」弹 **`该节点未配置源码映射 (params.source)`** ⇒ 不是节点坏了,
而是解析链在前两层就拿不到路径。

## 解析链(按顺序, 命中即返回)

1. **现场节点自带** `node['params']['source']` (+ `source_symbol`) —— `open_target.py` 里**最优先**
2. `spec.source` — `resolve_open_target(node|id)` 内部 `spec.parse_canvas()` 建的 NodeSpec
3. **中间件模块声明** — `spec.py::_source_from_module(nid)`: 扫 `nodes/*.py` 按 `NODE_ID` 匹配, 取 `SOURCE`/`SOURCE_SYMBOL`
4. **注册表** — `registry.get(impl_key)` 的 `info['file']` + `info['line']`
5. 全落空才弹「该节点未配置源码映射」

### 🔴 为什么第 1 层必须在最前面: GUI 内存 id ≠ 磁盘画布 id
`load_flow_file` 会给每个节点**重新 `gen_id()`** ⇒ 界面上那个节点的 id (`n1793…acw`)
在磁盘画布 JSON 里根本不存在 ⇒ `parse_canvas()` 按 id 查不到 spec ⇒ 返回空 ⇒ 弹窗,
**而节点 dict 里的 `params.source` 明明是对的**。先信现场节点, 就不会被 id 重编坑到。
(症状: 修好"中间件 SOURCE + 注册表"两层之后, 用户仍报同一个弹窗 —— 只可能是拿 id 去盘上找的那一步失败。)

因此修复点在 `spec.py` / `open_target.py` 的兜底链,
不是临时往节点里塞 params:
用户在界面上改参数后随画布保存下来的 `params` **是持久的**(它们本来就住在 `flows/state_space_obs.json` 里),
而只在内存里临时塞的 params 会被 GUI 旧副本覆盖。

## 🔴 迁移实现后必须回改画布 JSON 的 `params.source` (2026-10-29 实测)

第 1 层最优先 ⇒ **画布 JSON 里那份 `params.source` 是决定右键落点的那个值**。
执行链外迁 (`library.py` → `nodes/<功能>_impl.py`) 时如果只改了 `_EXTERNAL_LOC` 与中间件 `SOURCE`,
画布节点 params 还写着旧文件, 用户右键就会跳到**那个旧文件里的某个函数**, 而它往往属于另一个程序 ——
实测症状: 动作执行器节点右键跳到 `tools/l2_daemon.py` 的 `def main()`
(`_single_instance` / `unlink+mkfifo` / ssh 链路探针 = 常驻 FIFO 下发进程的入口),
用户当场问「动作执行器的代码怎么跑到这里来了?」。

**迁移一个节点实现的完整四处**: ① `nodes/<功能>_impl.py` 正文 ② `library.py` 薄壳 ③ `_EXTERNAL_LOC[key]`
④ 中间件 `nodes/n_<单词>.py` 的 `SOURCE/SOURCE_SYMBOL` + `PARAMS`
⑤ **画布真源该节点的 `params.source` / `params.source_symbol`** (走 `save_canvas`, 或改 JSON 后回读)。
旧文件如果是另一个真实程序(常驻进程/脚本), 别删它的引用含义 —— 加一个 `params.dispatcher` 把它标成
「下发进程(不是本节点实现)」, 让后来的人一眼看出两条链的区别。

判据(改完立刻跑, 不要靠右键目检):
```bash
cd ~/zmax && PYTHONPATH=src python3 - <<'PY'
import json; from lerobot.middleware import open_target as ot
d=json.load(open('flows/state_space_obs.json'))
n=[x for x in d['nodes'] if x.get('id')=='<节点id>'][0]
print(ot.resolve_open_target(n))   # impl_path 必须是新实现, impl_line 是 def run 那一行
PY
```


## 两层兜底(都已实现)

**A. 中间件节点模块声明** — `src/lerobot/middleware/spec.py` 新增 `_source_from_module(nid)`:
扫描 `src/lerobot/middleware/nodes/*.py`, 按 `NODE_ID = '<nid>'` 匹配到模块, 再正则取
`SOURCE = '...'` / `SOURCE_SYMBOL = '...'`(结果存 `_MODSRC_CACHE`, 不重复读盘)。
`parse_canvas()` 里 `params.source` 为空时就调它。

**B. 注册表登记的实现位置** — `open_target.py` 再兜一层:
`registry.get(spec.impl_key)` 拿 `info['file']` + `info['line']`(注册时 `_reg()` 自动记的)。

## 节点实现正文不许留在 `library.py` (注册表大文件)

`registry.get(key)['file']` 记的是**函数定义处** ⇒ 实现写在 `nodes/library.py` 里,
右键就永远停在 `library.py:<行>`, 用户会直接说「怎么能是 library.py 呢？应该是 <真实功能> 的代码」。

规矩:
- 节点实现正文放**自己的模块** (`src/lerobot/engineering/nodes/<功能>_impl.py`), `library.py` 里只留薄壳
  (`def node_xxx(ctx): from .<功能>_impl import run as _run; return _run(ctx)`) —— 保持老 import/注册 key 不变。
- 同步两处映射: `_EXTERNAL_LOC["<key>"] = (<impl.py 绝对路径>, <`def run` 行号>, "def run")`,
  中间件 `nodes/n_<单词>.py` 的 `SOURCE` / `SOURCE_SYMBOL` 也指过去。
- 改实现后**重算行号**(`grep -n '^def run('`); 映射行号漂了不会报错, 只会把用户送到错误的一行。
- 挪完顺带确认壳没变行为: 注册 key、`match_node(画布节点名)`、`PURE`、返回值形状都不变。
  ⚠️ `PURE=False` 的壳在画布常驻循环里**只直通不执行实现** —— 实现挪走了但节点「看着有、跑起来不动」时先查这一条,
  别去怀疑规划逻辑。

## 批量外迁执行链的落地套路 (2026-10-28 实测 6 个节点)

用户说「把执行链上那几个节点按顺序迁出来」时, 一次迁一整批, 别一节点一提交:

顺序按数据流: 运动规划 `n_moveit` → 安全边界/动作调制 `ss_limit` → 万有引力/SE3 `ss_grav_h`
→ 动作执行器 `n_exec` → 机器人执行器/物理世界 `ss_act` → 状态校正器/先验动力学 `ss_correct` → 触觉 `yolo_tactile`。

**做法(正文逐字搬, 不手抄)**:
1. `ast.parse(library.py)` 取目标函数的 `lineno~end_lineno`, 原样切行进新文件 (跑手脚写必引入差异)。
2. 算**自由名**: 函数里 `Load` 但本地没绑定的名字 ∩ 模块级名字 (函数/类/常量/import) ⇒ 生成
   `from .library import _SS_STATE, _ss_import` 这类显式 import。
   🔴 漏 `os` 这种**模块级 import** 只有真调用才炸 (`NameError: name 'os' is not defined`) —— 静态看代码全对。
3. `library.py` 原函数换成薄壳 `from .<impl> import run as _run; return _run(ctx)`; 老 key/返回值形状不变。
4. `_EXTERNAL_LOC[key] = (impl 绝对路径, def run 行号, "def run")`; 已有同名条目要**先删旧再加新**
   (本次 `n_exec` 旧条目指向 `l2_daemon.py:2143`, 与新的并存 ⇒ 后者覆盖, 右键仍落旧文件且行号是错的)。
5. 中间件壳 `SOURCE/SOURCE_SYMBOL` 若已经指向**算法模块**(`safety.py`/`execution.py`/`cognition.py`/`gen_tactile.py`), **别覆盖** ——
   那是比节点包装更真的源码; 只有 `SOURCE = ''` 的壳才补 impl 路径。

**行为对拍 (硬判据, 必须做)**: 迁移前后各跑同一份脚本, 调 `library.node_xxx(ctx)` 全部用例, 比 `ret` + 日志条数:
- 纯函数节点 (安全边界/执行器/校正器/触觉) 应 **逐字相同**。
- **读实时文件的节点 (万有引力) 前后必不同** (stage/U 随 live 快照变) ⇒ 用「旧模块 vs 新模块同一秒各跑一次」比
  (把迁移前备份 `cp` 进包目录当 `_library_old_tmp.py` import, 比完 `rm`) —— 实测同快照完全一致。

**收尾别漏**: registry 说明里标「节点实现 nodes/<impl>.py」时别把已有 `(源码 xxx.py)` 顶掉, 现写法是追加 `; 节点实现 …`;
`registry.get(key)['fn']` 仍是那个薄壳名字 (`node_xxx`) 属正常 —— 源码落点看 `resolve_open_target` 的 `impl_path`。

## 把 tools 脚本的「生成本体」迁成节点实现 (build + 薄壳 CLI)

场景: 节点的输入是某个 tools 脚本预烤的成品 (段表/索引/配置投影) ⇒ 节点只是"播放器", 用户会说
「这是 tool 在算, 不是节点在算」。改法是把生成本体搬进节点侧模块, 工具降为薄壳 CLI。

1. 新模块 `nodes/<功能>_plan.py` 放本体, 暴露两个入口:
   - `build()` 纯计算, **不写盘、不下发**, 返回 dict (含 `cfg_sha = sha1(真源内容)[:12]`);
   - `write(out, path)` 才落盘 (工具/对拍用), 写时带上 `cfg_sha`。
2. 机械搬: 按行切片保留原脚本的模块级常量 + helper, 把 `def main():` 改名 `def build():`, 末尾 `return out`
   替掉原来的 `json.dump` + `print` 块。别手抄 400 行 —— 手抄必引入差异, 且差异会在"改了配置但段表没变"时才暴露。
3. 根目录常量要重算: 原脚本 `REPO = dirname(dirname(__file__))`, 挪到 `src/lerobot/engineering/nodes/` 后是**上溯四层**。
4. 节点侧 `_self_plan()`: 先 `build()`; 与磁盘成品**同 cfg_sha** 时逐段对拍 (段数/kind/t/端点), 不一致或异常 ⇒
   回退磁盘成品并在状态里写 `src=self | self(配置已变) | disk(原因)`。对拍闸的细节见
   `derived-store-staleness-gating` 的「真源从预烤成品换成运行时现算」。
5. 缓存 key 带上真源 mtime 或指纹, 否则改配置不重算。
6. 工具变薄壳: `from ...nodes.<功能>_plan import build, write` + 打印人看得懂的编排。

验收 = ①自算 vs 原成品逐段差量 (端点 ≤0.01mm、kind/时长 0 处差) ②现场节拍不掉 (例如 300UPH) ③改配置后自算跟着变且不被回退。

⚠️ 整文件重写会被工具拒掉 (`stale write`: 该文件本会话只 patch 过/只读过部分) ⇒ 先把旧文件 `cp` 到 scratch 当备份、
`rm` 掉原路径, 再 `write_file` 写新内容 —— 既留住旧实现可回退, 又避免"拿记忆里的旧版覆盖磁盘上的真实内容"。

## 自检(改完必跑, 不要只看一个节点)

```bash
cd ~/zmax && PYTHONPATH=src ./gui-venv311/bin/python - <<'PY'
from lerobot.middleware import resolve_open_target as rot
from lerobot.middleware import spec as S
specs,_,_=S.parse_canvas()
ok=bad=0
for s in specs:
    t=rot(s.id); hit = bool(t.get('impl_path'))
    ok += hit; bad += (not hit)
    if not hit: print('缺:', s.id, s.name[:20])
print('可打开真实现 %d / %d' % (ok, len(specs)))
PY
```

验收口径: **全部节点都能落到 impl_path** (不是"plan 节点能开了就行")。

## 自检二: 走 GUI 真路径 (只调 resolve_* 不够)

`resolve_*` 通过 ≠ 右键能用 (GUI 传的是**内存节点 dict**, id 是重编过的)。离屏起真控制台加载真画布,
拦 `subprocess.Popen` 看它到底发了什么命令:

```python
# QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python, sys.path.insert(0,'tools/gui')
v = SimulinkModule(); v.load_flow_file(<画布真源>)
node = [n for n in v.nodes.values() if '运动规划' in (n.get('name') or '')][0]   # 名字找, 别按 id
real = subprocess.Popen
subprocess.Popen = lambda cmd, *a, **k: (print('CMD', cmd), type('P',(),{'pid':0}))[1]
v.open_node_source(node)
subprocess.Popen = real
```

判据 = 打印里出现 `code … ZMAX.code-workspace -g <impl.py>:<行>` 且**没有弹窗**(弹窗会把 `_qmsg_info` 调到)。

## 交付前必知

- 改 `spec.py` / `open_target.py` 后**必须重启控制台**才生效: 该模块在启动时已 import,
  `from lerobot.middleware import resolve_open_target` 拿的是缓存模块, 旧代码继续跑。
- 本机档位决定能否真的拉起 VSCode: `zmax_profile.vscode_ok()` 只在调试档为 True;
  其余档位点是"无反应" —— 要么给出路径+行号让用户自己跳, 要么先查档位再承诺。
- 本类问题形状固定: **能力已存在但解析链断在某层**。先按链逐层打印(拿到哪一层为空),
  再去补那一层, 不要新建一套映射表。
