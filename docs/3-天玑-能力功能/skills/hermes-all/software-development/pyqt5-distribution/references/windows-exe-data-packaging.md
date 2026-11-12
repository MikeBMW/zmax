# Windows exe 数据目录打包 — 画布加载失败根因链 (2026-08-26 v3.2.1)

## 症状
v3.2.0 Windows exe: 主控制台能打开, 但 Simulink 画布加载失败。
- 主窗口 OK = 代码模块打包正常 (studio.py 静态 import simulink_module → PyInstaller 自动收集)。
- 画布挂 = 运行时数据文件缺失。任何画布按钮 (Z700 / 三模型对比 / 场景 / 合作闭环) → `load_flow_file(flows/xxx.json)` → FileNotFoundError。

## 根因链
1. `.github/workflows/build-win-exe.yml` 的 pyinstaller 命令只
   `--add-data "logo.png;." "docs_sync.py;." "ppt_engine.py;." "update_checker.py;."` —
   **flows/ 目录 (画布 JSON, 1.2M) 没打包**。
2. PyInstaller 只收集 import 的 `.py`, 从不自动收集数据文件。
3. `studio._init_simulink` (延迟 400ms 创建 SimulinkModule) 有 try/except 兜底 →
   statusBar "⚠️ Simulink 初始化失败"; 模块库/场景/合作闭环的 JSON 读取虽有 try/except
   返回空, 但用户点画布按钮必然报"找不到画布/加载失败"。

## 修复 (commit 08d04b7f, v3.2.1)
1. **CI**: Windows `--add-data "flows;flows"`; macOS `--add-data "flows:flows"` (分隔符分号 vs 冒号, 写错不报错但资源丢)。
2. **simulink_module.py**: 新增模块级 `_repo_root_path()` (frozen → `sys._MEIPASS`, 源码 → `__file__` 上溯三级);
   `_repo_root()` 方法返回它; 替换全部 `__file__` 上溯点:
   - 模块级 `_load_skill_library_groups` (atomic_skill_tokens.json)
   - 场景分组 scene_skills_3scenarios.json / 合作闭环 cooperation_closed_loop.json
   - 技能 action 导出 ×5 处 (同一行字符串, patch 用 replace_all)
   - 另存为/加载工作流 QFileDialog 默认目录 ×2
3. **studio.py**: `_repo_root()` 加 frozen 分支 (import sys 已有)。
4. **training_backend.py**: `get_repo_root()` 加 frozen 分支 + **补 `import sys`** (原文件没有)。
5. 版本号四处同步 (studio 标题 / update_checker / version_sync / docs_sync)。

注: docs_sync.py 已有 frozen 处理 (exe 目录 + LOCALAPPDATA fallback), 不用改。
另注意 simulink_module.py 10427 行 `_pick_atomic_condition` 是 `dirname×2` (读 tools/flows/) —
既有的层数 bug, 有 exists 检查兜底, 本次未动。

## 验证 — 模拟 PyInstaller frozen 布局 (offscreen)
```python
import os, sys, tempfile, shutil
REPO = "/home/ubuntu/lerobot-smolvla-lew"
mei = tempfile.mkdtemp(prefix="hermes-verify-frozen-")
shutil.copytree(os.path.join(REPO, "flows"), os.path.join(mei, "flows"),
                ignore=shutil.ignore_patterns("*.py", "*.md", "*.html", "*.php"))
sys.frozen = True; sys._MEIPASS = mei
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
from PyQt5.QtWidgets import QApplication; app = QApplication([])
import simulink_module as sm
assert sm._repo_root_path() == mei          # frozen 分支生效
m = sm.SimulinkModule(); m._sync = lambda: None
m._qmsg_yes = lambda *a, **k: True          # 防确认框阻塞
assert m.load_flow_file(os.path.join(mei, "flows", "dual_brain_peg_yolo.json"))
assert len(m.nodes) >= 20                    # 实测 33 节点 34 连线
del sys.frozen
assert sm._repo_root_path() == REPO          # 非 frozen 回归
shutil.rmtree(mei, ignore_errors=True)
```
实测输出: Z700 33 节点 34 连线 / ff_pd_top 20 节点 / 非 frozen 回归 OK。
跑验证用 gui venv (`gui-venv311/bin/python`), 系统 python3 无 PyQt5。

## 排查口诀
"主窗口能开 + 某功能挂" → 先查 `--add-data` 清单 vs 该功能运行时读取的数据路径 (grep `open(`, `load_flow_file`, `abspath(__file__)`), 别先怀疑代码逻辑。

---

## 用户数据不随包走: 新机首发必须「种」一份 data

**症状**: 新机上控制台能开, 但 `文件 → 打开总工程` 弹 `❌ 没有这个文件: <路径>`。

**根因**: 打包只带 exe 与依赖; `data/database/**`(工程/主参数/功能笔记)与 `data/scene/**` 是**本机数据**,
既不该进包、也不在包里 ⇒ 全新机器上这些目录是空的。这不是「打包漏了」, 是这类文件本来就靠首次种入。

```bash
# 只打最小种子: 别把几百 MB 的历史 archive/截图一起搬
tar -czf seed.tar.gz -C ~/zmax \
  data/database/zmax/zmax_space.proj data/database/zmax/config_meta.json \
  data/database/zmax/function_notes.json $(cd ~/zmax && ls data/scene/*.json)
scp seed.tar.gz win:C:/Users/<u>/zmax_console/
ssh win 'cd C:\Users\<u>\zmax_console && tar -xzf seed.tar.gz'   # Win10+ 自带 bsdtar
```

- 🔴 **同一份种子要放遍所有候选根**: 冻结态 `repo_path` 可能是 `dirname^3(__file__)`(= `<app>` 的上级),
  也可能是 cwd ⇒ 实测这三个都放过才稳: `<install>\`、`<install>\app\`、`%USERPROFILE%\zmax\`
  (代码里大量 `os.path.expanduser("~/zmax")` 路径, 首次运行会自动建出后者的 `zmax_data/`)。
- **放完不用重启**: 打开工程用的是点击时 `os.path.exists`, 直接再点一次即可。
- **取证入口**: 打开/加载工程的每一步都写 `~/zmax/zmax_data/logs/open_project.log`
  (入口 / 文件不存在 / 读档失败 / 界面回填) —— 用户说「打不开」先读这个文件, 别让他复述弹窗内容。
- 交付口径: 「包能开」与「工程能打开」是两件事, 都要验; 新机首发清单里写明「种 data」这一步。
