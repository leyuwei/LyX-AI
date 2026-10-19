$ErrorActionPreference = 'Stop'
$taskBuildPath = $env:PATH
$taskPython = (Get-Command python -ErrorAction Stop).Source
# Do not let unrelated apps' DLLs in PATH replace Windows' ICU or Qt dependencies.
$env:PATH = @((Split-Path -Parent $taskPython), (Join-Path $env:WINDIR 'System32'), $env:WINDIR) -join ';'
Push-Location $PSScriptRoot
try {
    & $taskPython -m PyInstaller --noconfirm --clean --windowed --onedir --name LyXAI `
        --icon lyxai/assets/logo.ico --add-data 'lyxai/assets;lyxai/assets' `
        --exclude-module tkinter --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
        main.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    $packagePath = Join-Path $PSScriptRoot 'dist\LyXAI-Windows'
    New-Item -ItemType Directory -Path $packagePath -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dist\LyXAI') -Destination $packagePath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'docs') -Destination $packagePath -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'examples') -Destination $packagePath -Recurse -Force
    foreach ($name in @('Install.ps1','Install.cmd','Uninstall.ps1','README.md')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $packagePath -Force
    }
    Compress-Archive -Path (Join-Path $packagePath '*') -DestinationPath (Join-Path $PSScriptRoot 'dist\LyXAI-Windows.zip') -Force
    Write-Host 'Package:' (Join-Path $PSScriptRoot 'dist\LyXAI-Windows.zip')
} finally { Pop-Location; $env:PATH = $taskBuildPath }
