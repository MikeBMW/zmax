---
name: cross-host-asset-transfer
description: Use when 把大权重/依赖/数据推到另一台主机 (选链路·按目标 Python 抓轮子·三证验收)。
version: 1.0.0
author: Hermes Agent
license: Apache-2.0
metadata:
  hermes:
    tags: [transfer, rsync, wheels, offline, edge, network]
---

# 把大文件与依赖送到另一台主机

## When to Use
- 要把权重/数据集/轮子包推到另一台机器(边缘机、工控机、无外网主机), 而目标机 Python 版本与本机不同。
- 跨机传输很慢/反复断, 要判断该走局域网直连还是公网中转。
- 目标机 `pip install` 报 `from versions: none` 或依赖区间冲突, 要一次把依赖树搬全。

适用: 权重/数据集/轮子包要从本机到一台**边缘机或工控机**(可能无外网、Python 版本与本机不同、没有 GPU)。
目标不是"拷过去了", 而是**那台机器上真能 import / 真能前向**。

## 1. 先选链路, 再传

按实测速率选, 不要按"哪条现成"选:

| 链路 | 实测 | 判据 |
|---|---|---|
| 同网段直连(产线网卡/同交换机) | 3.4GB / 30s ≈ **106MB/s** | 首选, 一到位就把中转任务停掉 |
| 经云主机中转(ssh 隧道 / 公网回传) | ≈ **1.1MB/s**, 3.4GB 约 50min | 只在没有局域网时用 |

- 直连判定: 三个对端全 ping 通 **且** 原上网链路地址未变(别把默认路由抢走)。
- 中转链路普遍有对端周期性 `Connection closed by remote host`, 大文件会被拦半途; 一旦直连可用立即切换,
  否则白等一小时。
- 传之前先确认大小与目标盘剩余空间(`df -h`), 权重 3GB 级别不算小。

## 2. 依赖必须按"目标机的 Python 版本"抓

在有外网的那台机器上把**整棵依赖树**抓成轮子, 目标机只做 `--no-index` 安装:

```bash
pip download --only-binary :all: --python-version 3.12 --implementation cp --abi cp312 \
    <pkg>==<ver> -d /tmp/wheels312          # 不带 --no-deps
rsync -a /tmp/wheels312/ host:/home/x/wheels312/
ssh host 'pip install --no-index --find-links /home/x/wheels312 <pkg>'
```

三个反复咬人的错法:
- **`--no-deps`**: 只抓直接依赖, 到目标机上一轮报一个缺(pyyaml → typer → …), 每轮都要重传。
- **abi/python-version 与目标机不一致**: 轮子文件名里的 `cp311` 对不上目标机 3.12 ⇒
  `Could not find a version that satisfies X (from versions: none)`。看到 "from versions: none" 先查轮子文件名, 不是查镜像源。
- **包本身的依赖区间与源侧缓存冲突**(如 `huggingface-hub<2.0,>=1.5` vs 缓存里 2.3.0): 让同一条 `pip download`
  的 resolver 自己选, 不要手改版本号, 也不要把不兼容的那个旧轮子跟着推过去(会先被选中再报冲突)。

### 目标机可能已经有 wheel 库 —— 先找, 再决定要不要下载
- 边缘机上常留有预先铺好的轮子目录(实测 `/home/intel/sam3_wheels`(cp310-abi3 + py3-none) ·
  `sam3_wheels312`(cp312) · `whl550c`(draccus/mergedeep 等)) ⇒ 先
  `find /home/<user> -maxdepth 2 -type d -iname '*wheel*'` + `ls <dir> | grep -i <pkg>`,
  命中就直接 `pip install --no-index --find-links=<dir> --no-deps <pkg>==<ver>`, 不用回本机 `pip download` 再传。
  **`--no-index` 必须显式给**: 不给自己会去连源/DNS, 在无外网的机器上白等到超时。
  cp310-abi3 的轮子在 3.12 上可以直接用, abi 号不同也照用, 不必重下。
- **只缺一两个包时, `--no-deps` 定向补比推整棵树安全**: 目标 venv 如果是**训练环境**,
  按整棵树装会顺手把 torch/transformers 升级 ⇒ 复现性毁了。口径: 装前 `pip freeze` 存快照,
  只装缺的(`--no-deps`), 装后逐字核 `torch`/`transformers` 版本未变。
- 依赖链会**一串一串**冒(实测 `draccus` → `mergedeep` → `typing_inspect` → `mypy_extensions`):
  逐个补、逐个 `import` 验证, 别一次只报一个就停, 也别因为链长就改回抓全树。
- 端侧 torch 跑大视觉模型的性价比要**实测再下结论**: SAM3 1008px 在 Intel Arc B390 首次 **92.9s**
  (含权重搬 XPU) vs 本机 4060 热推理 **742ms**, 同图同结果(都 13 个实例) ⇒ 这类模型端侧该走
  ONNX→IR(OpenVINO); 补 venv 只用于"能启动同口径比对一次", 不是上线方案。

## 3. 验收三证 (少一条不算完成)

1. **字节数/校验**: 目标机 `stat -c %s` 与源侧一致(或 sha256 对账), 不看 rsync 退出码就完事。
2. **import**: 目标机跑 `python -c 'import <pkg>; from <pkg> import <关键类>; print(<pkg>.__version__)'`。
3. **真跑**: 喂一份真数据跑一次, 记录耗时与输出数值(例: 参数规模 / 加载秒数 / 单次推理秒数)。
   只说"验证通过了"不算证据; 目标是给出能让别人复核的数。

在验收报告里把这三条都写出来, 并明写**性能结论**: 目标机若无 GPU, 同一模型可能是秒级→十秒级,
"能用"和"能实时"是两件事, 必须分开说。实测锚点: 840M 参数视觉模型在 CPU(8 线程, 640×480)上
**单次 43~64s**, 同模型在 4060 上是 0.4s 级 —— 无 GPU 目标机的结论只能是"静态/离线可用",
要实时必须换量化/NPU 后端, 别把"验证通过了"说成"能上线"。

## 4. 收尾

- 旧链路上的传输任务(中转脚本/后台 rsync)按 **PID** 停: `pgrep -af` 看清父子再 `kill -TERM <pid>`。
  `pkill -f <脚本名>` 会匹配到执行它的那条 shell 命令行(名字就在里面), 把自己一起 SIGTERM 掉
  (表现为 exit -15 且后续命令全未执行)。
- 大文件不入 git: 权重/压缩包留数据盘或目标机, 仓库里只放清单与校验和。
