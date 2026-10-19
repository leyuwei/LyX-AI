param([string]$LyXUserDir = (Join-Path $env:APPDATA 'LyX2.5'))
$ErrorActionPreference = 'Stop'
$appPath = Join-Path $env:LOCALAPPDATA 'LyXAI\LyXAI.exe'
if (-not (Test-Path -LiteralPath $appPath)) { throw 'Installed app not found.' }
$argsText = '--uninstall --lyx-user-dir "{0}"' -f $LyXUserDir
$result = Start-Process -FilePath $appPath -ArgumentList $argsText -Wait -PassThru -WindowStyle Hidden
if ($result.ExitCode -ne 0) { throw 'Menu removal failed; inspect the error dialog.' }
$shortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LyX AI - Start LyX.lnk'
if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut }
Write-Host 'Menu removed. Restart LyX. Model settings and app files are retained.'
