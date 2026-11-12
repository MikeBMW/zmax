# 离线改 Windows 注册表 / 账户(从 Linux 或 U盘 Live 系统)

## 何时用
Windows 没在跑(用户从 U盘/Linux 启动), 而要求"现在就改"注册表或账户: 自动登录切人、账户增删、装脚本自启。

## 铁律
- 默认仍**交给 Windows 自己**(脚本 + 计划任务)。只有用户明确要求立即生效、且这台机器上 Windows 确实没在运行时, 才走离线改。
- 先备份 hive 再动; 改完**从卷上回读**; 结束卸载并回挂 `ro`。告诉用户"下次是完整启动, 会慢一次"。
- SAM 里账户控制位(F 值)不做离线手术, 见第 5 步。

## 0) 只读先看清
```bash
sudo mkdir -p /mnt/win && sudo mount -t ntfs-3g -o ro /dev/nvme0n1p3 /mnt/win
ls /mnt/win/hiberfil.sys                              # 存在 = 快速启动/休眠残留, 决定第 1 步
sudo apt-get install -y chntpw                        # 带 chntpw / reged
chntpw -l /mnt/win/Windows/System32/config/SAM        # RID | 用户名 | 是否管理员 | 禁用/锁定
```
- **`chntpw -l` 是"本机到底有哪些账户"的唯一可信来源**。`C:\Users\<名字>` 目录 ≠ 账户:
  新建账户的 profile **首次登录才创建**(磁盘上还没有目录); 反过来几十 GB 的残留目录也可能是早已删除的账户。
  用户说"这个用户我看不到/应该有"时, 查 SAM, 别查 Users 目录。
- 系统内置必须保留: RID 500(内置 Administrator, **Windows 机制上不允许删除**)、DefaultAccount、WDAGUtilityAccount、
  WsiAccount、Guest(默认已禁用)。用户说"除了 X 全删"时, 往往真正能动的只有他自己建的号 —— 如实说明, 别硬删。
- 拿到一个 Windows 口令不代表能登另一台主机: **先看 SSH banner**(`SSH-2.0-OpenSSH_...Ubuntu` = 那是 Linux),
  Windows 口令对它无效。

## 1) 挂读写(必须撤休眠残留)
```bash
sudo umount /mnt/win
sudo mount -t ntfs-3g -o rw,remove_hiberfile /dev/nvme0n1p3 /mnt/win
```
- `remove_hiberfile` 删掉 hiberfil.sys ⇒ 下次完整启动。**不删等于白改**: Windows 恢复时用休眠里的旧注册表覆盖。

## 2) 备份(唯一回滚点)
```bash
B=/mnt/win/_zmax_setup/reg_backup/$(date +%Y%m%d_%H%M); sudo mkdir -p $B
for h in SAM SOFTWARE SYSTEM SECURITY DEFAULT; do sudo cp -p /mnt/win/Windows/System32/config/$h $B/$h; done
```

## 3) 改值: reged(chntpw 包自带)
```bash
cp /mnt/win/Windows/System32/config/SOFTWARE /tmp/wh_SOFTWARE     # 在副本上改, 好了再拷回
reged -x /tmp/wh_SOFTWARE 'HKEY_LOCAL_MACHINE\SOFTWARE' \
  'Microsoft\Windows NT\CurrentVersion\Winlogon' /tmp/cur.reg    # 先导出看现值
```
`/tmp/set.reg`(标准 Windows .reg 语法)例 —— 自动登录切人:
```
Windows Registry Editor Version 5.00

[HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon]
"AutoAdminLogon"="1"
"DefaultUserName"="<新账户>"
"DefaultPassword"="<口令>"
"DefaultDomainName"="<COMPUTERNAME>"
```
```bash
printf 'y\n' | reged -I /tmp/wh_SOFTWARE 'HKEY_LOCAL_MACHINE\SOFTWARE' /tmp/set.reg
```
三个必踩的坑:
- **前缀只能单反斜杠**: shell 单引号内就写 `'HKEY_LOCAL_MACHINE\SOFTWARE'`。写成双反斜杠 ⇒
  `import_reg: WARNING: found key <...> not matching prefix <...>` 而**什么都不写入**。
- **`reged -I` 必须喂 `y`**: 末尾问 `Commit changes to registry? (y/n) [n]`, 不喂就打印 `Not written!`——
  退出码看着正常, 极容易当成改成功了。
- **改完必回读**: 再 `reged -x` 导出同一键 grep 目标值; 拷回卷 + `sync` 后, 从卷上再 cp 一份出来验第二次。

## 4) 落回卷 + 回挂只读
```bash
sudo cp /tmp/wh_SOFTWARE /mnt/win/Windows/System32/config/SOFTWARE && sudo sync
sudo umount /mnt/win && sudo mount -t ntfs-3g -o ro /dev/nvme0n1p3 /mnt/win
sudo cp /mnt/win/Windows/System32/config/SOFTWARE /tmp/verify
reged -x /tmp/verify 'HKEY_LOCAL_MACHINE\SOFTWARE' 'Microsoft\Windows NT\CurrentVersion\Winlogon' /tmp/v.reg >/dev/null 2>&1
grep -i DefaultUserName /tmp/v.reg          # 必须是新值
```
未动的 hive 用 md5 对照证明没碰(`md5sum /tmp/wh_SAM /mnt/win/.../SAM` 同值), 交付时说出来。

## 5) 账户禁用/删除: 不能离线硬来 ⇒ 挂到新账户首次登录
- `chntpw -u <user> SAM` 菜单只有: 清空口令 / 解锁启用 / 提升管理员 / 加组 / 移组 —— **没有禁用, 没有删除**。
- **不要改 SAM 的 F 值**: `reged -x` 导出的 F 二进制实测被截断(只有 23 字节), 按它改写会破坏账户;
  F 值里还有登录计数/时间戳, 偏移一错位就废号。
- 正解 = 把动作挂到"新账户首次登录"那一刻(那一刻它一定可用):
  1. 先按第 3 步把自动登录切到新账户 —— **否则自启脚本永远不会跑**(自动登录的还是旧号)。
  2. 写全局自启: `C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\<name>.cmd`
     (所有用户登录都跑, 首次登录必跑; 末尾自删; cmd 里只调 `powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File`)。
  3. ps1 逻辑: 确保新账户在 `S-1-5-32-544` → 对 `Get-LocalUser` 中"启用且不在保留名单"的账户 `Disable-LocalUser`
     → 把最终 `名字 enabled=` 表写进 `C:\_zmax_setup\*.log` → 删掉自启 cmd。
     保留名单必须含 DefaultAccount / WDAGUtilityAccount / WsiAccount(+新账户本身)。
     脚本内只用 ASCII 输出; ps1 存 UTF-8(带 BOM)+CRLF, .cmd 纯 ASCII+CRLF。
- 这样即使新账户口令不对, 也**从没把旧号禁用** ⇒ 不会锁死; 脚本只在"新账户确实登进来了"时执行。

## 6) 交付口径
- 报三件事: 改了哪个键(**回读到的值**)、备份路径、下次启动会完整启动一次; 并明确"SAM/账户位没动"。
- 残留 profile 目录(几十 GB)不等于账户: 要清数据单独确认, 不与账户操作捆在一句话里做掉。
