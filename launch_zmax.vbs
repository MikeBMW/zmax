' Z-MAX console launcher (window-less shim)
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\ZMAX\launch_zmax.ps1""", 0, False
