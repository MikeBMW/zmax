# 给冻结 app (PyInstaller onedir) 补 Python 依赖，不重打包

## 适用判据
节点"真函数被调用了"但算不出：stdout 出现 `No module named ...` / `PackageNotFoundError ...`，
而 `node_breakpoint_audit.py` 的状态仍写「实现执行」。**先看 stdout，不要只看 status 文案。**

## 平台前提
冻结 app 的 sys.path 只认 `<app>/_internal/`。打包时的解释器版本要先用
`Z-MAX_Console.exe -c "import sys;print(sys.version)"`（或等价一行脚本）拿到，Windows 打包版实测 **3.12.10**。
wheel 必须按这个版本/A​BI 下载，否则解包后 import 失败。

## 下载（不需要目标机上有对应 Python）
```bash
python -m pip download <pkg> \
  --python-version 3.12 --only-binary=:all: --platform win_amd64 \
  --implementation cp --abi cp312 --no-deps -d wheels
unzip -q -o wheels/<pkg>-*.whl -d <app>/_internal/
```
- torch 走 CPU 索引：`--index-url https://download.pytorch.org/whl/cpu`（实测 torch 2.15.0+cpu，解包 ~490MB）。
- **一个包一次，装完立刻验**：
  ```python
  # t.py —— 用冻结 exe 跑，验证真的能 import
  import torch; print(torch.__version__); x=torch.randn(3,3); print(float((x@x).sum()))
  ```
  先验 torch，再验目标包。错误会**点名下一个缺的模块**。

## 依赖链是按报错一层层展开的
| 验的东西 | 第一个报错 | 真实缺口 |
|---|---|---|
| torch | `No module named 'graphlib'`(stdlib 未打包) | 补 3.12 stdlib pyc |
| ultralytics | `PackageNotFoundError: No package metadata was found for torchvision` | **torchvision**（不是 ultralytics） |
| torchvision 之后 | matplotlib/pandas/scipy/pillow… 逐个报 | 视觉依赖全家桶 |
实测一整套（与 torch 同源）：torchvision · scipy · pandas · matplotlib · pillow · pyyaml · requests · tqdm ·
psutil · py-cpuinfo · ultralytics-thop · contourpy · cycler · fonttools · kiwisolver · packaging ·
python-dateutil · pytz · six · charset_normalizer · idna · urllib3 · certifi。

## stdlib 缺口只补报错的那几个
`python-3.12.10-embed-amd64.zip` 里的 `python312.zip` 是 **.pyc**（sourceless import 可用）。
⚠️ 不要整包拷进 `_internal/`：会遮蔽同名模块，且其它版本的 python 在该 cwd 下直接
`ImportError: bad magic number in 'json'`（实测：拷了 599 个 pyc 后，Hermes 自带的 3.14 在 `_internal`
目录里 import json 就崩）。逐个补、补一个验一个。

## 进度判断（别把慢当死）
`pip download` 串行下大包（scipy 36.7MB）在 ~0.4MB/s 上是几分钟，且 **pip 下完才落盘** ⇒ 目录里长时间只有
0~1 个 whl。不要 `| tail` 吞掉输出（等于自盲），也不要只看目录文件数判卡死：连续两次量 `ls -la` 的大小
/ `du -sh` 都不变才算卡，单包跑最直观。

## 验完的预期结果：失败点会前移，不会消失
补包只把 "缺包" 换成 "缺数据/权重"，交付时必须分两栏报（逻辑级通过 / 计算级还缺哪个文件，带绝对路径）。
打包版经常缺少这些非代码件：
- `runs/detect/outputs/<模型>/weights/best.pt`（YOLO 系节点）
- `models/*.npz`（左/右脑、前馈 MLP 权重）
- `src/lerobot/policies/intact`、`src/lerobot/cognition`（整包不存在 ⇒ ModuleNotFoundError）
- `data/skills/l2_atomic/*`（肌肉记忆库查询恒 0 条）
这些只能从源码仓库/产线机拷；本机够不到产线网时如实说明，不要用通用预训练权重冒充。
