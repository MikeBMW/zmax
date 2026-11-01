# 关机存档 · 代 v5.50.735 收尾 (2026-10-15 傍晚)

## 本次已落库 (远端 main == tag v5.50.735 == 39bca62)
* 21773b3 ⚖ 原子技能物理惯性/质量变化率约束 + 偏差 error 分流 (9 技能四条约束 · ⚖物理闸节点 · 偏差→状态校正器/融合定位→流形引擎顶层补偿)
* 39bca62 产品三档 550A/550B/550C 随包发布 (出厂骨架 + 读侧回落 + 打包带上)
* 判据: verify_physics_constraints 34 条 · audit_skill_inertia 9/9 · verify_product_release_factory 20 条 · verify_function_notes 9 项 (75/75) · engineering_db check 全绿 · integrity/repo_guard/secret_scan 全绿

## 关机前状态 (开机后照这个恢复)
常驻服务 (5 个, 关机即停, 开机后要手动拉起):
```bash
sudo -S -p '' systemctl start zmax-ss-engine-loop zmax-dds-ss zmax-ss-skill-dispatch zmax-dataspaces-probe zmax-ss-trace-pub
systemctl is-active zmax-ss-engine-loop zmax-dds-ss zmax-ss-skill-dispatch zmax-dataspaces-probe zmax-ss-trace-pub
```
控制台与信号页:
```bash
bash tools/studio_ctl.sh restart --force        # 控制台 (标题 XSpace ZMAX 550B · 侧栏 Z-MAX v5.50.735)
bash tools/gui/restart_graphic_window.sh        # 实时监控 · Graphic 信号分析
```
本机现场 (关机前实测): GPU 3212 MiB/8188 MiB · 磁盘余 ~39-42 GB (90%) · 相机不在位 ⇒ 视觉源只有渲染帧 ·
融合定位真值 tcp_out/latest.json ~10h 陈旧 ⇒ 顶层补偿按设计被拒 (机器人在线才生效)。

## 未完成 (开机后按序收)
1. `packaging/linux/install_ubuntu.sh` 的库检测: ldconfig -p 匹配误报 ⇒ 改 ctypes 载入 (已实测 libGL/libEGL/libxkbcommon.so.0 全可载)
   → `bash tools/build_linux_installer.sh` 重打 → 上传 Release 附件 (+ sha256)。
2. Windows .exe 出包结论 (CI 自 v5.50.72 起因版本连挂, 非本版引入); macOS zip 已出 135,051,842 字节。
3. Release 正文补写「三平台 + 550A/550B/550C 同步发布」。
4. 若老倪要冻结的 Linux 二进制 ⇒ 加一个 linux CI job (现 Ubuntu 交付物 = 安装脚本 + 源码包 + 出厂骨架)。
