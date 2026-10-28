---
name: service-migration-triage
description: "Use when 判定服务能否迁到另一台机器 (按依赖不按CPU)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [migration, triage, multi-host, systemd, dependency, zmax]
    related_skills: [system-replication-twin, intel-edge-npu-deployment, depth-cloud-map-service, status-aggregation-endpoint]
---

# 服务跨机可迁性判定 (先判，再动)

## When to Use
- 「把重计算的服务都迁到另一台机器」这类笼统要求 —— 得先逐个服务定性。
- 要回答「X 能不能迁过去」。
- 迁完之后要证明「真的活下来」（重启还能自启）。

跟 `system-replication-twin`（整套系统复制）的区别：那边是清单+打包+校验；
这边只判**哪些服务值得搬、搬家后会不会变成空转**。

---

## 🔴 律 0: 按真实依赖判，不按 CPU% 也不按名字

最容易犯的错是**拿 CPU 占用排优先级**。实测反例：占 **304%** 的那个服务是相机+机械臂常驻回路，
占 **95%** 的是 GUI 控制台 —— 这两个 CPU 最高，却是最不可迁的；搬过去只会变成
「连得上但下不了发」的空转服务，比不搬更差。

---

## 🔴 律 1: 四道红线，逐条过

| 红线 | 判据（怎么查） | 结论 |
|---|---|---|
| **硬件独占** | 相机/机械臂/DDS/串口/GPIO 物理挂在源机；源码里有独占采集、有 `capture`/`set` 写操作 | ❌ 不迁。迁 = 拔线 + 产线停 |
| **SDK 平台绑定** | `ctypes` 加载 `.dll`、Windows 盘符与反斜杠路径（`C:\Windows\TEMP`、`D:\...`） | ❌ 不迁。目标机无对应 SDK |
| **加密权重/解密器** | `.enc` 权重 + 解密器按约定留在原机 | ❌ 不迁。迁 = 破约定 |
| **纯 numpy + 标准库** | 无 CUDA、无厂商 SDK、无 GUI、路径可 env 覆盖 | ✅ **唯一真正可跨机的硬门槛** |

判定只看**依赖**，不看服务名好不好听、也不看它占多少 CPU。

判据从接口直接取：`GET /last_result` 里如果返回 `C:\Windows\TEMP\...`、`D:\...\images` 这种路径，
就已经证完「SDK 平台绑定」这条，不需要登进去看源码。

---

## 🔴 律 2: 迁之前先量源机响应 —— 毫秒级就别迁

“重计算”三个字很容易被误用。实测：被点名要迁的两个接口本来就只有 **4.4ms / 4.9ms** 响应
（局域网 + 本机回环）。这种迁过去只会**多一段网络往返**，纯变慢。

⇒ 先 `curl -w '%{http_code} %{time_total}'` 量一把；源机已是毫秒级的，正确结论是
**不迁**，并明确告诉用户「瓶颈不在算力上」，而不是默默执行。

想真实分掉负载，换方向：让目标机做**离线批处理**（图像增强 / 批量标注 / 数据集构建 / 统计报表）
—— 这些纯 CPU、无硬件依赖、可以随便搬，不动在线链路。

---

## 🔴 律 3: 目标机已有同 Python 版本的 venv ⇒ 复用大 wheel，别重下

从零 `pip install torch --index-url …/whl/xpu` 在目标机实测**七分钟无进展**（下载缓存停在 3GB、包数仍是 3）。

- 两个 venv 解释器版本相同时（都 `lib/python3.12`），直接搬包：
  ```bash
  GS=<旧>/lib/python3.X/site-packages; SP=<新>/lib/python3.X/site-packages
  cp -r $GS/torch $GS/torchvision $GS/torchgen $GS/functorch $SP/
  cp -r $GS/torch-*.dist-info $GS/torchvision-*.dist-info $SP/
  ```
  再 `pip install -r req.txt` 只装剩下的（torch 已在，会自动跳过）。1.6G 本地拷贝是秒级，下载是十几分钟。
- **只搬 wheel，不动在役环境**：目标机上那套 venv 可能正跑着渲染/训练；往里装 opencv 之类会撞
  `numpy.core.multiarray failed to import`（numpy 与 cv2 的 ABI 不匹配），把在役进程一起搞挂。
  正确做法永远是**另建隔离 venv**，只从旧 venv 复制包文件。
- **依赖清单要按源机的每一套 venv 分别出**：同一个项目常有多套环境（GUI 一套、推理/训练一套），
  少出一套 = 有一类服务永远起不来，而且报错各不相同。
- 清单里先剔掉算力绑定包再给目标机：`grep -viE '^(torch|torchvision|torchaudio|nvidia-|triton)'`，
  torch 由目标机按自己的算力（XPU/CUDA/CPU）单独解决。
- 🔴 **清单里的 `-e` editable 行会让整条 `pip download -r` 全盘失败**：报
  `... is not a valid editable requirement`，现象是只零星下到几个包，之后就开始「补一个缺一个」地打补丁，
  而根本不在按清单装。先 `grep -v '^-e ' req.txt > req_clean.txt`。
- 🔴 **`pip download` 一律带 `--no-deps`**：不带的话 pip 会顺着 `transformers`/`accelerate` 的依赖去解析
  `torch`，把 CUDA 版 torch + `nvidia-*`（nccl 216MB、cublas 423MB…）整批拖下来 —— XPU/CPU 目标机上全白下，
  一次卡几十分钟。缺哪个再单独补。
- **`--python-version` 与 sdist 互斥**：带了 `--python-version 312` 就必须同时给 `--only-binary=:all:`，
  否则 pip 直接拒绝执行。
- **下载与安装都串行**：两个 `pip download` 同时往同一个 `-d` 目录写会互相抢，
  报 `FileNotFoundError: /tmp/pip-unpack-*/xxx.whl`（文件被另一个进程清掉）。
- 🔴 **目标机无外网时走离线 wheel 通道**，但**看要装的是哪类包, 两种打法别混用**:
  - **大栈 / 带算力绑定的清单**（torch·torchvision·nvidia-*）: 源机
    `pip download --no-deps --python-version 312 --only-binary=:all: --platform manylinux2014_x86_64 -d whl/ <pkg>`
    → `scp -r whl/ target:~/whl/` → 目标机 `pip install --no-index --find-links ~/whl <pkg>`。
    这种场景下别把百来条清单一次装全（链条深、编译型包会挂），按「起服务 → 看 `ModuleNotFoundError` → 只补那一个」迭代。
  - **单个有依赖树的主包**（`transformers` 这类）: **去掉 `--no-deps`，让 pip 把整棵闭包一次算完**:
    ```bash
    pip download --only-binary :all: --python-version 3.12 --implementation cp --abi cp312 \
        transformers==5.16.1 -d /tmp/wheels312          # 实测 27 个轮子, 含 typer/hub/tokenizers
    ```
    逐次补在这里**更慢**: 目标机每轮只会报一个缺包（`pyyaml → typer → …`），每轮都要重新撞网络、重新搬文件。
- 🔴 **轮子的 Python/ABI 必须先对齐目标解释器, 否则整个方案从第一秒就错了**: 拿 cp311 的 `pyyaml`/`regex` 去装 py3.12
  会直接 “no matching distribution”, 而你很容易把它误读成“源机上有包、镜像没同步”。先 `python -V` 确认目标版本,
  再给 `--python-version / --implementation cp / --abi cp312`。同理版本约束先读主包 METADATA：
  `transformers 5.16.1` 要 `huggingface-hub>=1.5,<2.0`, 给 2.3.0 会卡在解析。
- **装完必跑一次 `import`，不要看 pip 输出猜**：
  `python -c "import torch, cv2, numpy; print(torch.__version__, torch.xpu.is_available())"` ——
  `pip install` 成功不等于能 import（缺 XPU 运行时库时要到 import 期才炸 `libpti_view.so.0`）。
  包文件级复制（上条）拿不到运行时库时，改用一台**已知完整**的 venv 作底座，
  只往里补缺的那个包（如 `--no-deps` 装新版 cv2），不要在新 venv 里从零重建整个栈。

---

## 🔴 律 4: 目标机路径不一致时，软链收口 > 逐处改代码

源码里预先固定 `/home/<源用户>/<项目>` 的地方可能有几百处，逐处改成目标机路径既慢又会漏。
最快的收敛方式是在目标机上把名字补出来：

```bash
sudo ln -sfn /home/<目标用户> /home/<源用户>                                # 源 HOME 整体重定向
sudo ln -sfn /home/<目标用户>/<实际迁移目录> /home/<目标用户>/<代码里固定不变的目录名>
readlink /home/<目标用户>/<代码里固定不变的目录名>                              # 回读确认
```

- ⚠️ **`ln -sfn src dir` 在 `dir` 已是真实目录时不替换，而是「在 dir 里面建同名链接」**。
  先 `ls -ld` 看清：是目录就 `mv` 备份（`mv /home/u/zmax /home/u/zmax_old_<日期>`）再建链，
  否则得到 `dir/src` 这种永远命中不了的嵌套链接，`readlink` 返回空、代码继续报 PermissionError。
- 迁移目录名与代码里固定不变的目录名**常常不一致**（拷到 `zmax_550c`，代码写 `/home/u/zmax`）——
  这条软链不做，前面所有 unit 都白装。

## 🔴 律 5: unit 里的 `User=` / `Group=` 必须换成目标机账户

照搬源机 unit，`User=ubuntu` 落到只有 `intel` 账户的机器上 ⇒ `status=217/USER`：
服务反复 restart、`is-active` 永远 `activating`，而 **`journalctl` 一条日志都没有**（进程根本没被拉起）。
「日志为空」就是这条坑的指纹，别去查代码。

```bash
sed -i -e 's/^User=.*/User=<目标用户>/' -e 's/^Group=.*/Group=<目标组>/' *.service
```

## 流程

1. **先盘清源机有哪几个常驻服务**：按端口/pid 找（`ss -ltnp`），顺手拿 CPU/内存占用。
   ⚠️ 不要 `ps | grep <名字>` —— 会匹配到自己这条命令行，把自查变成自杀。
2. **逐个过四道红线**（律 1），能拿接口证据就拿接口证据，别靠猜。
3. **对判定可迁的，先量源机响应**（律 2），确认迁过去不是变慢。
4. **只同步代码 + 必要的输入数据**，不要搬整个项目树（实测项目 206G，代码只有 93M；
   `rsync --exclude` 掉数据/外部仓库/venv/报告/归档/.git 后约 300~400M，局域网几十秒）。
5. **服务清单用 `ExecStart` 批量导出，别逐个读文件**：
   `systemctl list-unit-files '<前缀>*' --plain | awk '$1 ~ /\.service$/ {print $1}'` 拿到全集（实测 53 个），
   再逐个 `systemctl show -p ExecStart --value <u> | grep -oE '/[a-z0-9_]+/[a-z0-9_]+\.(py|sh)'`
   ⇒ 一张“unit → 脚本”映射表，直接据此分类：业务服务（可迁）/ 隧道转发（迁了没意义）/ 桌面·守护·网络（留源机）。
6. **路径环境变量化后再迁**：预先固定 `ROOT/zmax_data/...` 的脚本拷到布局不同的机器上一启动就 `FileNotFoundError`。
   入口处一次性收口成可覆盖常量（`ZMAX_MAP_OUT` / `ZMAX_MAP_DEPTH_DIR` 这类）。
   批量改 unit 时 **长前缀先替换**：`sed -e 's|<源根>|<目标根>|g' -e 's|<源 HOME>|<目标 HOME>|g'` ——
   反过来先换 HOME，`/home/a/zmax` 那条子路径映射就永远匹配不到了。
7. **先探 `sudo -n true` 再排自动化**：目标机 sudo 免密才能全自动 `cp unit → daemon-reload → enable --now`；
   要密码就把需要人工的那一步提前讲清楚，别做到一半阻塞。
8. **起 systemd**：`Restart=always` + `RestartSec` + `Nice`/`CPUQuota`/`MemoryMax`，并 `enable`。
9. **验收两件事**：① 两端各跑一次，**输出逐项对照**（点数/bbox/耗时）；
   ② `stop → start` 实测一次自恢复，确认换了新 PID 且端口重新监听。
   只验证「现在跑着」不算 —— 机器一重启就什么都不剩。
10. **验收要看接口，不看 `is-active`**：逐个端口 `curl -s -o /dev/null -w '%{http_code}'`，200 才算活。
    实测一批 `is-active` 的服务接口是 500 / 读不到真值（跨机后缺相机/SDK 通道），`systemctl` 眼里完全正常。
    补依赖后**重数一遍 active 数**（实测 12 → 26，那批「activating」的实际一直卡在缺包）。
11. **跨机后「读不到真值」不是迁移失败**：机械臂/相机留在源机时，目标机上服务会 fail-closed 拒答
    （`{"ok": false, "err": "真值读不到(文件+桥都失败)"}`）。这是正确行为，别当 bug 修 ——
    要单独配一条通道（SDK 桥 / ROS domain / 推流），并在交付话术里写明「哪几个服务在等通道」。

---

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 按 CPU% 挑迁移对象 | 搬完发现绑硬件，白花一天 | 先过四道红线（律 1） |
| 按名字想当然（“建图应该很重”） | 迁过去没变快反而慢 | 先量源机响应（律 2） |
| 看到 Windows 路径还继续排方案 | 到 Linux 上根本跑不起来 | 路径/盘符/反斜杠出现即封死（律 1） |
| 端口被手动进程占着就装 systemd | 重启循环，起不来 | 先按 pid 停掉手动进程，再让 systemd 接管 |
| 只验证「当前 active」 | 重启后全没 | `stop → start` 实测新 PID（流程 7） |
| 路径预先固定 | 目标机启动即 `FileNotFoundError` | env 覆盖（流程 5） |
| 两种口径的产物比数字 | “你的数和官方差一倍”来回扯 | 先问是不是两个口径（全体 vs 子集），两者都对 |
| 从零在目标机重下大 wheel | 十几分钟无进展 / 直接超时 | 同版本 venv 直接 `cp -r` 包 + `dist-info`（律 3） |
| 照搬源机 `pip freeze` 全量装 | 目标机的 XPU/CPU 版 torch 被 CUDA 版覆盖 | 清单先剔 torch 家族，由目标机单独解决 |
| 在在役 venv 里补装依赖 | `numpy.core.multiarray failed to import`，在役渲染/推理进程跟着挂 | 另建隔离 venv，只复制包文件（律 3） |
| 只出一套依赖清单 | 有一类服务永远起不来，且报错各不相同 | 按源机每个 venv 各出一份 |
| 逐个读 unit 文件猜服务 | 几十个 unit 要看一天，还容易漏 | `systemctl show -p ExecStart` 批量导出映射表（流程 5） |
| 批量 sed 先换 HOME 后换子路径 | 有一批路径根本没改到、启动即报文件不存在 | 长前缀先替换（流程 6） |
| unit 照搬 `User=<源用户>` | 永远 `activating`、**journalctl 一条日志都没有** | 目标机账户名不同即 `217/USER`；批量 sed 换 `User=`（律 5） |
| 迁移目录名 ≠ 代码预先固定目录名 | 代码报 PermissionError/FileNotFoundError，路径看着没错 | 补一条软链（律 4） |
| `ln -sfn src dir` 目标是真实目录 | 链接被建到 `dir/src` 里，`readlink` 空 | 先 `mv` 备份目录再建链（律 4） |
| `pip download` 不带 `--no-deps` | 被 transformers/accelerate 拖着下几个 G 的 CUDA 包，卡几十分钟 | 见律 3 |
| 依赖清单含 `-e` 行 | 整条下载失败、只零星下到几个包，之后靠猜补依赖 | 先 `grep -v '^-e '`（律 3） |
| 轮子 ABI/Python 版本不对（cp311 装到 py3.12） | 每轮报**另一个**包 no matching distribution，像依赖永远补不完 | 先 `python -V`，下载时给 `--python-version/--abi`，一次算全闭包 |
| 并发跑两个 `pip download` | `FileNotFoundError: /tmp/pip-unpack-*/xxx.whl` | 串行（律 3） |
| 只按 `is-active` 验收 | 「起来了」但接口 500 / 读不到真值 | 逐端口 `curl` 拿 200；补依赖后重数 active（流程 10） |

---

## 交付话术

给用户结论时要带**真实证据**，不要只报“已迁移”：
- 哪些**不能迁**，各自阻塞点道红线（带一条接口或路径证据）。
- 哪些**已迁**，两端输出逐项一致的数字。
- 迁移**没有收益**的，直说「不迁才是对的」并给替代方案。
