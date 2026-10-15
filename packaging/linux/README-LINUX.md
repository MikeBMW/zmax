# Z-MAX Console · Ubuntu / Linux 安装说明 (@VER@)

与 Windows `.exe` / macOS `.zip` 同一版本 (v@VER@ · 2026-10-15), 同一套出厂骨架。

## 一条命令体检 (先跑这个)

```bash
tar -xzf zmax-console-@VER@-linux-x86_64.tar.gz && cd zmax-console
bash install_ubuntu.sh --check       # 只体检: python/venv/图形库/包完整性/产品三档/磁盘内存/可选项
```

体检不过会逐条标 ❌ 并给出 `apt install` 命令; 过了再装。

## 安装

```bash
bash install_ubuntu.sh               # 装到 ~/.local/share/zmax (venv + 依赖 + 桌面图标 + zmax-console 命令)
bash install_ubuntu.sh --prefix /opt/zmax
bash install_ubuntu.sh --uninstall   # 卸程序 (工程数据 data/ 不动)
```

装完:
* 启动 `zmax-console` (或点桌面图标 **Z-MAX Console**)
* 侧栏显示 `Z-MAX v@VER@`; 顶栏 = `XSpace ZMAX <550A/550B/550C>` (随配置中心「产品配置」页切)

## 产品三档 (随包)

`defaults/config/platform/zmax_product.json` 出厂就带 **550A / 550B / 550C** 三档开发分工, 全新安装即可选:

| 档 | 定位 | 关键开关 |
|---|---|---|
| 550A | 开发版 · 新技能/新算法/最新逻辑 | `new_algorithms=on` · `logic_depth=max` |
| 550B | 标定版 · 最大化 debug | `topics=all` · vscode 联调 · 信号分析/3D 开 |
| 550C | 量产版 · 稳定性优先 | 白名单算法 · `comm=shm` · 不发 topic · 关信号分析/3D · 远程旁路 |

实例真源 (接了自己的工程数据包之后) 优先于出厂骨架。

## 接真实工程数据 (真机/产线)

```bash
tar -xzf <工程数据包>.tar.gz -C ~/zmax-data
cd ~/.local/share/zmax/app
python3 tools/instance_init.py --link --data ~/zmax-data/database/zmax   # 平台↔实例对接
python3 tools/engineering_db.py build && python3 tools/engineering_db.py check
```

## 系统依赖 (体检会告诉你缺哪个)

```bash
sudo apt install -y python3 python3-venv python3-pip \
                    libgl1 libegl1 libxkbcommon0 libxcb-xinerama0 libxcb-cursor0
```

## 本版新增 (v5.50.735)

* ⚖ **原子技能物理惯性/质量变化率约束**: 9 个 L2 原子技能各带 ①速度 ②加速度 `a_max=F/m` ③加加速度
  ④动量/质量变化率 四条约束; 进入技能的动作物理上不可执行就发**偏差 error** ⇒ 小偏差进 🧪状态校正器,
  大偏差经 📡融合定位核对 → 🧮流形引擎**顶层结构补偿** (2mm/次 · 累计封顶 20mm)。
  自检: `python3 tools/audit_skill_inertia.py` / `tools/verify_physics_constraints.py`。
* 无 GPU 也能跑 (纯 CPU 仿真); 有 NVIDIA 卡时自动用系统驱动 (nvidia-smi 可见即可)。
