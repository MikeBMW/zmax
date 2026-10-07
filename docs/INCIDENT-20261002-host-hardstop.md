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
代价: 可用 swap **16G → 8G**(磁盘 / 剩 45G，需要的话另建一个**独立**文件补回去，**绝不再对同一个文件启两次**)。

## 5. 下次要抓到真凶(需重启，待老倪点头)

现在 `efi_pstore` 已加载但目录为空、内核命令行无 `crashkernel=` ⇒ 真 panic 也不会留证据。二选一/都做：
1. `crashkernel=512M` + `kdump-tools`：panic 后落 `/var/crash/*/vmcore`(全量，最能定因，占内存)。
2. `ramoops`/`pstore`：至少留最后一屏内核回溯(轻量)。

## 6. 待补充

- 10-02 当晚是"下班关机"还是"假死后强制断电"，需老倪口述确认(日志到 21:05:01 就断了，无法自证)。
