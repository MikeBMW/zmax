param(
    [Parameter(Mandatory = $true)][string]$Exe,          # full path to the console exe to launch
    [string]$Name = 'Hermes Agent',                      # shortcut name on the Desktop
    [string]$Title = 'Hermes Agent',                     # Windows Terminal tab title
    [string]$WorkDir = $env:USERPROFILE,
    [switch]$NewWindow = $true,                          # wt -w -1 = separate window (what users expect)
    [switch]$UseTerminal                                # force wt.exe even if detection is unsure
)
# Creates a Desktop launcher for a console app and READS IT BACK.
# Why: on Win11 the default terminal is Windows Terminal, so a shortcut pointing at the raw
# console exe opens a background TAB inside an already-running terminal window -> the user
# sees nothing and reports "the icon does not open".  `wt -w -1` forces a new window.
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Exe)) { throw "exe not found: $Exe" }

$desk = [Environment]::GetFolderPath('Desktop')
$lnk = Join-Path $desk ($Name + '.lnk')
$wt = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\wt.exe'

if (Test-Path $lnk) {
    $bak = "$lnk.bak_" + (Get-Date -Format 'yyyyMMdd_HHmmss')
    Copy-Item $lnk $bak -Force
    "backup=" + $bak
}

$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
if ((Test-Path $wt) -and ((-not $UseTerminal) -or $UseTerminal)) {
    $windowArg = if ($NewWindow) { '-w -1 ' } else { '' }
    $sc.TargetPath = $wt
    $sc.Arguments = $windowArg + 'new-tab --title "' + $Title + '" -d "' + $WorkDir + '" "' + $Exe + '"'
} else {
    $sc.TargetPath = $Exe
    $sc.Arguments = ''
}
$sc.WorkingDirectory = $WorkDir
$sc.IconLocation = "$Exe,0"
$sc.Description = $Name
$sc.WindowStyle = 1
$sc.Save()
Start-Sleep -Milliseconds 300

$r = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
"=== READBACK ==="
"lnk=" + $lnk + "  exists=" + (Test-Path $lnk)
"target=" + $r.TargetPath + "  target_ok=" + (Test-Path $r.TargetPath)
"args=[" + $r.Arguments + "]"
"workdir=" + $r.WorkingDirectory + "  workdir_ok=" + (Test-Path $r.WorkingDirectory)
"icon=" + $r.IconLocation
"next: launch it from the LOGGED-IN session (scheduled task, -LogonType Interactive) and enumerate visible
windows BEFORE/AFTER - a launch from an SSH (session 0) shell proves nothing about what the user sees."
