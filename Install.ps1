param(
    [string]$LyXDir = 'C:\Program Files\LyX 2.5',
    [string]$LyXUserDir = (Join-Path $env:APPDATA 'LyX2.5'),
    [ValidateSet('auto','zh','en','both')][string]$MenuLanguage = 'auto',
    [switch]$OpenSettings
)
$ErrorActionPreference = 'Stop'
$releasePath = Join-Path $PSScriptRoot 'dist\LyXAI'
$portablePath = Join-Path $PSScriptRoot 'LyXAI'
if (Test-Path -LiteralPath (Join-Path $portablePath 'LyXAI.exe')) { $releasePath = $portablePath }
$destination = Join-Path $env:LOCALAPPDATA 'LyXAI'
if (-not (Test-Path -LiteralPath (Join-Path $releasePath 'LyXAI.exe'))) {
    throw 'Packaged app not found. Follow docs/INSTALL.zh-CN.md for source installation or build the package first.'
}
if (Get-Process -Name LyXAI -ErrorAction SilentlyContinue) { throw 'Close LyX AI before installing/updating.' }
if (Get-Process -Name LyX -ErrorAction SilentlyContinue) { throw 'Close LyX before installing/updating so its menus can reload.' }
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -Path (Join-Path $releasePath '*') -Destination $destination -Recurse -Force
$appPath = Join-Path $destination 'LyXAI.exe'
$argsText = '--install --lyx-dir "{0}" --lyx-user-dir "{1}" --menu-language {2}' -f $LyXDir, $LyXUserDir, $MenuLanguage
$result = Start-Process -FilePath $appPath -ArgumentList $argsText -Wait -PassThru -WindowStyle Hidden
if ($result.ExitCode -ne 0) { throw 'Menu installation failed. See the error dialog; existing menu backup is retained.' }
Write-Host 'Installed to:' $destination
$launcher = Join-Path $destination 'Start-LyX.ps1'
@"
`$env:LYX_LOCALEDIR = '$($LyXUserDir.Replace("'", "''"))\lyxai-locale'
Start-Process -FilePath '$($LyXDir.Replace("'", "''"))\bin\LyX.exe' -WindowStyle Normal
"@ | Set-Content -LiteralPath $launcher -Encoding UTF8
if ($MenuLanguage -eq 'auto') {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LyX AI - Start LyX.lnk'))
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
    $shortcut.IconLocation = (Join-Path $LyXDir 'bin\LyX.exe') + ',0'
    $shortcut.Save()
}
Write-Host 'Start LyX with the Start Menu entry: LyX AI - Start LyX. For other launchers, sign out/in once to refresh the language environment.'
if ($OpenSettings) { Start-Process -FilePath $appPath -ArgumentList '--configure' -WindowStyle Hidden }
