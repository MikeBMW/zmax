# 控制台重新打包与 exe 替换

改 `tools/gui/` 下的 py（studio.py、simulink_module.py …）后，改动要进桌面版必须重打包。
顺序固定：**打包 → 验包 → 杀孤儿 → 备份 → 替换 → 用户自己启动**。

## 1. 打包

用仓库 CI 同一套 pyinstaller 参数（`--onedir`），输出到 `tools/gui/dist_nounpack/`。
venv 里要有 PyInstaller + PyQt5 + cv2；整轮 5~8 分钟（metaworld / mujoco / cyclonedds 那几个
`--collect-all` 最慢）。成功的判据是这两行：

```
pyinstaller exit = 0
BUILD_OK exe=23.8MB total=521.7MB
```

## 2. 验包：确认新代码真进去了

不要靠"打包没报错"就认为生效，两种客观判据：

```bash
# ① 模块在 PYZ 索引里
grep -c simulink_module build_nounpack/Z-MAX_Console/PYZ-00.toc   # >=1
# ② 源文件 mtime 早于 PYZ 构建时间 ⇒ 打包读的是新版
ls -l --time-style=+%H:%M:%S simulink_module.py build_nounpack/Z-MAX_Console/PYZ-00.pyz
```

**别在 exe 里 grep 符号名**（`btn_cy_chord` 之类）来验证 —— PYZ 是 zlib 压缩的，
字符串不会明文出现，`found=0` 不代表没打进去，只会误判。

## 3. 替换前必须杀孤儿

主窗口退出**不会**带走它拉起的子服务。这些进程继续占着 8793 / 8797 / 8799 / 8802，
exe 文件也被占用 ⇒ 直接复制会半覆盖写坏。

```powershell
Get-NetTCPConnection -LocalPort 8793,8797,8799,8802 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Get-Process Z-MAX_Console -ErrorAction SilentlyContinue   # 必须为空
```

端口表空了、进程表空了，才动文件。

## 4. 备份 + 替换

```powershell
$bak = "D:\ZMAX\_bak_$(Get-Date -f yyyyMMdd_HHmmss)"
Copy-Item D:\ZMAX\Z-MAX_Console.exe $bak -Force
Move-Item D:\ZMAX\_internal "$bak\_internal_old" -Force   # 改名而不是删
Copy-Item <新包>\Z-MAX_Console.exe D:\ZMAX\ -Force
Copy-Item <新包>\_internal D:\ZMAX\_internal -Recurse -Force
```

**旧 `_internal` 用 Move 改名归档，不要先删再拷** —— 拷贝 500MB 期间出错就彻底没得退了。

## 5. 回退

```powershell
Copy-Item <bak>\Z-MAX_Console.exe D:\ZMAX\ -Force
Remove-Item D:\ZMAX\_internal -Recurse -Force
Move-Item <bak>\_internal_old D:\ZMAX\_internal
```

## 6. 启动交给用户

替换完**只报告**：新 exe 大小/时间、备份目录、要检查哪两处（工具栏新按钮、8793 是否还活着、
中央相机是否还在出图）。**不要替他去起**，见 SKILL.md「用户红线」。

## 佐证：判断"改了为什么没看到"

用户说"没看到按钮"时，先分清是**没打包**还是**代码没写对**：
源文件里 `grep -c <符号>` 有命中 + PYZ 收录 + mtime 关系成立 ⇒ 代码在包里，问题在别处
（打包没替换、他开的还是旧 exe、按钮不在当前页）；三者任一不成立 ⇒ 回到代码。
