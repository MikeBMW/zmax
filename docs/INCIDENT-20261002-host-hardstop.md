# INCIDENT 2026-10-02 工位机(4060)硬停 — 5 天无日志，10-07 才通电

> 规矩: 只记有证据的事实(日志/时间戳/内核输出)，不确定的写"待补充"，不编。

## 1. 结论先说

**没有任何"内核 panic"的留存证据**：全库 grep `Kernel panic|Oops|call trace|soft/hard lockup|watchdog|Out of memory|oom-kill`
零命中；`/sys/fs/pstore/` 空；`crashkernel` 未配置、kdump 未启用 ⇒ 即便真 panic 也留不下东西。

**能确证的事实链**：上一轮开机 10-01 02:29 → **10-02 21:05:01 日志戛然而止**，没有任何关机序列
(`Shutting down` / `Reached target Power-Off|Reboot` / `systemd-shutdown` 全无)，也没有电源键/ACPI/热关机事件 ⇒ **硬停**。
之后到 10-07 17:40 之间 **0 条日志**(国庆假期，机器是关着的)，17:40 是重新通电开机。

## 2. 硬停前的 12 小时：swap 写错误风暴

| 证据 | 实测 |
|---|---|
| 首次 swap 写错误 | `2026-10-02 09:12:16` `Write-error on swap-device (7:22:655368)` |
| 总量 | **8872 条** `Write-error on swap-device`，全部设备号 **(7:22) = /dev/loop22** |
| 时间分布(每小时) | 09时 443 · **10时 3213** · 11时 33 · 12时 24 · 13时 27 · **17时 1461** · **18时 2734** · 19时 494 · 20时 413 · 21时 30 |
| 最后一条内核错 | `21:04:41 I/O error, dev loop22, sector 5911816` + `Write-error on swap-device` |
| 同时段 OOM/内存告急 | **0 条**(没有 oom-kill / page allocation failure / hung_task) |

## 3. 直接根因(确证并已修)：同一个 swapfile 被两个 swap 设备同时启用

```
/proc/swaps (改前)               系统里的启用来源(两处，指向同一个文件)
/swapfile    file    8388604  -2   ← /etc/fstab:  /swapfile none swap sw 0 0
/dev/loop22  partition 8388604 -3  ← zmax-swapfile.service: losetup -f --show /swapfile && swapon $LOOP
```
- `/sys/block/loop22/loop/backing_file` = **`/swapfile`** ⇒ 同一个 8G 文件的物理块被**两个 swap 设备**同时写，
  属未定义行为；而 8872 条报错**全部只出现在 loop22 那一路**，直连文件那一路 0 条 ⇒ 强指向这条。
- 它是 **LiveUSB 时代的遗留**(LiveUSB 上不能在 overlay 上直接 `swapon` 文件，所以套了一层 loop)；
  现在系统装在 `nvme0n1p5`(ext4) 上，直接用 fstab 的文件 swap 即可。
- 机理(推断，标注为推断)：内存吃紧时(31G 内存 + 训练/画布/六格流同时跑，swap 只有 8G 还被重复映射)
  写错误→页回收失败→系统假死；这种假死现场通常只能**长按电源强制断电**，于是"看起来像内核 panic"。

## 4. 已落处置(2026-10-07)

```bash
sudo swapoff /dev/loop22 && sudo losetup -d /dev/loop22
sudo systemctl disable --now zmax-swapfile.service
```
复核: `/proc/swaps` 只剩 `/swapfile file 8388604`; 无 loop 指向 /swapfile; 单元 `disabled/inactive`;
fstab 行仍在(重启后由 systemd-fstab-generator 自动恢复)。**回滚**: `sudo systemctl enable --now zmax-swapfile.service`

**容量补回(同日, 老倪确认后)**: 另建**独立**第二块 `dd` 实块文件 + fstab 常态化, 不再用 loop:
```
/swapfile2  none  swap  sw,pri=-3  0  0     # 8G, inode 17 (与 /swapfile 的 inode 16 是两个文件)
```
验证(等价开机路径): `swapoff -a` → 0 条 → `swapon -a` → `/proc/swaps` 两条(file 8G prio -2 / file 8G prio -3),
`losetup -l | grep -c swapfile` = 0, 内核 `Write-error on swap-device` = 0 条。
总量回到 **16G**, 但**两个设备映射的是两份不同的物理块** —— 这才是关键区别。
代价: `/` 从 89% 到 **91%**(剩 37G)。回滚: 删 fstab 行 + `swapoff /swapfile2` + `rm /swapfile2`。

## 5. 下次能抓到真凶了(2026-10-07 已按建议落地, 待一次重启生效)

原来 `crashkernel=` 未配置、pstore 空 ⇒ 真 panic 也留不下东西。现在:

| 装了什么 | 实测 |
|---|---|
| 包 | `linux-crashdump`(拉来 kdump-tools 1:1.10.3ubuntu2 · kexec-tools · makedumpfile · crash) |
| 预留内存 | `/etc/default/grub.d/kdump-tools.cfg`(包自带) `crashkernel=2G-4G:320M,4G-32G:512M,…` ⇒ 本机 31G 走 **512M** |
| 卡死也当 panic | 新落 `/etc/default/grub.d/99-zmax-crash.cfg`: `panic=10 softlockup_panic=1 hardlockup_panic=1`(`nmi_watchdog` 已是 1) |
| 自动回来 | `panic=10` = 崩后 10 秒自动重启(无人值守工位机要能自己起来; 起来后按既有自愈链恢复) |
| 转储落点 | `/var/crash/<时间戳>/vmcore`(makedumpfile `-c -d 31` 压缩 + 只丢内核页; `KDUMP_NUM_DUMPS=2` 限份数, 不写死磁盘) |
| 预建迷你 initrd | 手动跑了一次内核钩子 `/etc/kernel/postinst.d/kdump-tools $(uname -r)` ⇒ `/var/lib/kdump/initrd.img-6.17.0-14-generic` 252MB(解压 340MB), 免首启现建/失败 |
| 开机留痕 | `tools/boot_crashcheck.sh` + crontab `@reboot sleep 120` ⇒ 每次开井记一行 kdump 就绪状态; **发现 `/var/crash` 有转储就推飞书**(静界群), 正常开机不打扰 |

grub.cfg 已复核(default 与 advanced 两个菜单项都带上了 4 个参数)。**生效需要重启一次**; 重启后按 §7 核验。

## 6. 现场口述已确认(2026-10-07 老倪)

**10-02 晚上是卡死了, 不是下班正常关机** —— 系统假死后只能长按电源强制断电, 之后国庆 5 天没开机。
⇒ 与日志证据一致(无关机序列 + 日志 21:05:01 断在同一秒)。**假死前的先兆 = §2 的 swap 写错误风暴, 已按 §4 修掉**。

## 7. 重启后怎么核验(30 秒, 别只看"服务起没起")

```bash
sudo kdump-config show | grep -E "current state|crashkernel addr|kdump initrd"
cat /sys/kernel/kexec_crash_size                      # 要 > 0 (本机 ≈ 512×1024×1024 字节)
grep -o 'crashkernel=[^ ]*\|panic=10\|lockup_panic=1' /proc/cmdline
tail -2 /home/ubuntu/zmax_data/boot_selfcheck.log     # 开机留痕那一行(boot_crashcheck.sh 写的)
```
预期: `current state: ready to kdump` + 有 crashkernel 地址 + cmdline 四个参数齐 + selfcheck 记了一行。
仍 `Not ready` ⇒ `journalctl -u kdump-tools -b`(常见: 预留偏小 / 迷你 initrd 缺 / 内核不支持)。
**真崩过一次之后**: `/var/crash/<时间戳>/{vmcore,dmesg.txt}` 会在下次开机出现, 并且 `boot_crashcheck.sh` 自动推一条飞书(静界群)。
