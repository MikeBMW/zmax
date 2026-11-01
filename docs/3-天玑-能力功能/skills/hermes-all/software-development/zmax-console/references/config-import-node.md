# 配置中心 → 画布节点「标定诊断测量 · 主参数 M」: 配置导入 (真加载 + 右键直达)

老倪要求 (原话): 「这个配置中心的配置数据, 要写入状态空间的 标定诊断测量 主参数M 节点, 我右键打开这个节点,
要直接定位到, 导入配置文件的位置, 而且要能够运行, 要有能加载配置文件的逻辑」

## 三条要求 → 落地
1. **配置数据写入节点**: `src/lerobot/engineering/config_import.py` 是唯一入口 ——
   `import_config_files()` 读 8 项配置真源 (总工程 .proj / 任务绑定 / 任务配置 / MCD描述 / 参数注册表 /
   模型×工程匹配 / 主参数M能量标定 / 性能指标) + 工程库 SQLite (`data/database/zmax/zmax_engineering.db`
   的 `projects` 表) + 工单 `config/orders/BS_*.json`; `write_into_node()` 把结果写进画布节点 params 的
   `cfg_entries / cfg_snapshot / cfg_loaded_at / cfg_files / cfg_source` (写前备份 + 写后回读校验)。
   CLI: `--check` 只读清单 · `--node` 加载+写回 · `--json`。
2. **右键打开节点要直达导入的位置**: 节点 `params.source` = `src/lerobot/engineering/config_import.py`,
   `params.source_symbol` = `"def import_config_files("` ⇒ 右键「打开源码」= `code -g .../config_import.py:94`
   (原先指 manifold_engine.py)。`tools/ss_node_sync.py` 写节点时同步这两个字段。
3. **要能运行**: 该节点已有逻辑 `node_ss_calib_mani` (key `n_calib_mani`) —— 把 `config_import.load_config()`
   接进它 (右键「运行节点」/双击 = 真加载 8 真源 + 真写回), 原主参数 M 两臂对比不受影响。

## 启动期预读 (让 config_import 的断点在启动时就绑得上)

`import_config_files()` 默认只在**主参数节点执行 / CLI** 时才被惰性 import ⇒ 启动期这个文件根本不在进程里,
VSCode 里 `config_import.py` 的断点是空心的 (Unbound), 按多少次 F5 都不停。
⇒ studio.py 启动流程里主动预读一次 (**只读**, 不写画布节点): 先把 `<repo>/src` 插进 `sys.path`, 再
`importlib.import_module("lerobot.engineering.config_import")` → `import_config_files(verbose=False)`;
成功打 `📚 启动期配置真源预读: 配置 N 项 (…) · 工程库 ✅ 在位 · 实际任务 <TASK> <NAME>`, 失败被 except 兜住只打一行「跳过」。

- **路径层数**: studio.py 在 `tools/gui/` 下, 到仓库根要**三层** `os.path.dirname` —— 写成两层会算出 `<repo>/tools/src`
  (不存在) ⇒ `os.path.isdir()` 判 False ⇒ 静默不插 sys.path ⇒ `import lerobot` 抛 `ModuleNotFoundError('lerobot')`。
  同文件里拼 `data/database/zmax/zmax_engineering.db` 用的就是三层, 照它抄。
- **一行「跳过」= 那段功能从来没生效过**, 不是「可选优化」: 被 except 吞掉的异常要**先算一遍路径**再放过 ——
  `python -c "import os; print(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath('<studio.py>'))),'src'))"`,
  实测算出 `…/tools/src` 而不是 `…/src` ⇒ 这是真 bug, 要定位到行、改掉、回读验证。
- **改完必须重启调试会话**才生效 (改的是 studio.py 本体, 跑着的进程是旧代码。
  生效硬证据 = 启动日志出现 `📚 启动期配置真源预读: …` 且断点在启动 3 秒内停在 `_read_db(...)` 那行)。
- 常驻服务与桌面启动走同一份代码同一算法 ⇒ 服务方式一样跳过 (unit 里**没有** `PYTHONPATH`, 别指望它兜住)。

## 坑 (踩过)
- **符号定位撞注释**: `source_symbol` 的搜索是"第一行含该子串"。docstring/注释里也写了 `def <fn>(`
  就会定位到那一行 (实测落 10 而不是 94) ⇒ 注释里别写 `def <fn>(`, 或把符号写得唯一。
- **画布有两份**: `flows/state_space_obs.json` (仓库根, 旧) 与 `src/lerobot/engineering/flows/state_space_obs.json`
  (**软链 → `data/database/zmax/sources/canvas/state_space_obs.json` = 真源**)。写节点必须写真源; 只写旧的那份
  = 界面上看不到。`config_import.canvas_path()` 按真源→旧位置依次找。
- **临时文件+rename 写盘会把软链顶成普通文件**: 目标是软链时 `os.replace` 会替换软链本身 (git 报类型变化 ` T`)
  ⇒ 复原用 `git checkout -- <软链路径>`, 写盘前先 `os.path.realpath()` 解软链。
- **真源改动按设计不进代码库**: 画布/配置/工程库都在 `data/database/zmax/` 下而 `.gitignore` 有 `data/`;
  且 `config/calib/*.json` 是**软链** ⇒ `git add config/calib/x.json` 直接报
  `fatal: pathspec ... is beyond a symbolic link` 把**整个 commit 拒掉**。提交只带代码+判据+技能,
  真源改动如实说"在盘上、不入库"。
- **判据别假定节点函数返回类型**: `node_ss_calib_mani` 成功返回 bool ⇒ 判据里 `list(r)` 直接 TypeError;
  用 `str(r)[:60]` 记录即可。
- **秒级时间戳会撞秒**: 判据里比较 `cfg_loaded_at` 前后是否不同会假 FAIL (同一秒内两次写) ⇒ 改判"近 5 分钟内"。
- 节点写盘要保结构: 写后断言 89 节点 / 184 连线不变 + 除本节点外指纹一致 (`ss_node_sync` 自带该硬约束)。

## 判据 (可重跑)
`QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_node_cfg_import.py`
 ① 注册表命中 n_calib_mani ② params.source+source_symbol 解析出导入函数行且不含 GUI 文件
 ③ 8 真源 + 工程库 + 工单在位 ④ 真跑节点无异常 ⑤ 回读 cfg_loaded_at/cfg_files/cfg_snapshot 已更新 + 画布 89/184 未变。
实测 ✅ 15/15 PASS。
