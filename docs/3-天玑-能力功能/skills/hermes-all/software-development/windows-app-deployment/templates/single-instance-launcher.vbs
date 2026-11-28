' Window-less shim: the desktop shortcut targets
'   wscript.exe "D:\<APP_ROOT>\launch_app.vbs"
' so no console window ever flashes (see templates/single-instance-launcher.ps1).
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\<APP_ROOT>\launch_app.ps1""", 0, False
