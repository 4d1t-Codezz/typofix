# Creates Start menu and desktop shortcuts for Typofix.
# "Install on Windows.bat" runs this. To run it by hand:
#   powershell -ExecutionPolicy Bypass -File scripts\make-windows-shortcuts.ps1

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    Write-Error "Couldn't find pythonw. Install Python 3.10+ from python.org (tick 'Add python.exe to PATH')."
    exit 1
}

$targets = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Typofix.lnk",
    "$([Environment]::GetFolderPath('Desktop'))\Typofix.lnk"
)

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "-m typofix"
    $lnk.WorkingDirectory = $repo
    $lnk.IconLocation = "$repo\assets\Typofix.ico,0"
    $lnk.Description = "Typofix: fixes typos as you type"
    $lnk.Save()
    Write-Output "Wrote $path"
}
