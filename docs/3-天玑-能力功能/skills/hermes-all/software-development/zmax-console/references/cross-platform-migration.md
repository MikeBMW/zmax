# 跨平台迁移：控制台 → Windows D:\ZMAX（2026-11-25 落地）

老倪要求：控制台（业务容器）+ 配置中心 + 数据库 全量搬到 Windows D:\ZMAX，直接双击能跑，
CI/CD 标准流程、不许安装失败。架构定位：**控制台=业务容器（标定/诊断/服务），Simulink 画布=AI 模型层（全部代码）**。

## 1. 最关键的一条：exe 读不到同级 config（已修）

原实现 `_ROOT_P = dirname³(__file__)`。冻结包里：
- onefile: `__file__ = %TEMP%\_MEIxxxx\studio.py` → dirname³ = `AppData\Local`
- onedir : `__file__ = <exe>\_internal\studio.py` → dirname³ = `<exe 的上级>` = `D:\`

⇒ 读 `config/` 全部落空，静默退到 `defaults/`。表现为「配置中心明明拷了，界面里读不到」。

修法：`_zmax_root_dir()`，优先级
1. `ZMAX_ROOT` 环境变量（启动 bat 里 `set ZMAX_ROOT=%~dp0`）
2. frozen: exe 同级（**要求该目录真有 `config/` 才算**）→ `_MEIPASS` → `<exe>\_internal`
3. 源码: `tools/gui/` 上三级

并 `os.environ.setdefault("ZMAX_ROOT", _ROOT_P)`，让 `local_services.py` 等按 env 找根的模块同源
（Windows 上 `~/zmax` 不存在，不设这条它们自己拼 home 路径）。

自验（不必有 Windows）：同一函数换 `__file__` 跑两遍
```python
ns={'os':os,'sys':sys,'__file__':'/home/ubuntu/zmax/tools/gui/studio.py'}  # → /home/ubuntu/zmax
sys.frozen=True; sys.executable='/mnt/d/ZMAX/Z-MAX_Console.exe'; sys._MEIPASS='/mnt/d/ZMAX/_internal'
ns['__file__']='/mnt/d/ZMAX/_internal/studio.py'                              # → /mnt/d/ZMAX
```

## 2. 从 Linux 直接写 Windows D 盘（不必等 Windows 机）

分区表：`nvme0n1p3` = C 盘（350G，有 `$WINRE`/`Program Files`），`nvme0n1p4` = D 盘（200G，
有 `00_状态空间`/`03_代码工程`）。`/mnt/winp3`、`/mnt/winp4` 可能是**空目录假挂载**（df 显示根分区）
—— 要用 `mount -o ro /dev/nvme0n1p4 /mnt/wD` 自己挂，先 ro 探内容，确认是 D 盘再 `-o rw`。

写之前必须测一笔：`echo test | tee /mnt/wD/ZMAX/_wtest.txt`。ntfs-3g 对休眠/快速启动的卷会拒写。

软链必须 `rsync -aL`（解引用）—— `config` 本身就是软链（`config -> data/database/zmax/sources/config`，
1223 文件/18M）。用 `-a` 不加 `-L` 拷过去就是一堆断链，Windows 上直接空白。

## 3. 拷贝清单与校验

```bash
sudo rsync -aL --delete config/ /mnt/wD/ZMAX/config/
sudo rsync -aL data/ models/ src/ docs/ flows/ defaults/ dds/ reports/ /mnt/wD/ZMAX/...
```

逐目录核文件数（**不要只看 du**）：
```bash
for d in config data models src docs flows defaults dds reports; do
  a=$(find -L $d -type f|wc -l); b=$(find /mnt/wD/ZMAX/$d -type f|wc -l)
  printf '%-10s %8s %8s %s\n' $d $a $b $([ "$a" = "$b" ] && echo OK || echo DIFF)$(done
```
实测结果：config 1223=1223 ✅、data 94478 ✅、models 49 ✅、src 2205 ✅、docs 4484 ✅、
flows/defaults/dds ✅；reports 会一直差几个 —— 那是 `intact_sw/frames/` 有进程在实时写，不是拷贝失败。

`zmax_data` 有 214G（stable-wm-cache 49G / ar_evolve 31G / gs_assets 24G / hf_cache 17G），
**不做全量**：只拷 `eval`(20M) + `logs`(134M)。全量拷贝既装不下也没意义（训练缓存不是「信息文档」）。

## 4. Windows 启动脚本

`.bat` 必须 **CRLF**（`content.replace("\n", "\r\n").encode("utf-8")`）+ `chcp 65001`，
第一件事 `cd /d "%~dp0"` 并 `set ZMAX_ROOT=%~dp0` —— 后者是 `_zmax_root_dir()` 的第一优先级。

## 5. 包的选择

用 **onedir 免解包版**（`Z-MAX_Console-win64-nounpack.zip`）部署到 D 盘：
文件夹形式、启动快、不用每次跑都解压到 %TEMP%、出问题能直接看 `_internal` 里的文件。
onefile 版适合「发一个 exe 给对方」。

## 6. tag 重打（改完代码发现包已开始构建）

```bash
git tag -f v5.50.785 HEAD && git push -f origin v5.50.785
```
push tag 会自动触发新的 workflow run，旧 run 先 `POST /actions/runs/<id>/cancel` 干掉，
否则会产出一个「不含修复」的包并建 Release。**确认新 run 的 head_sha 就是当前 HEAD** 再等。
