# SPDX-License-Identifier: GPL-3.0-only
"""Generate an ASCII launcher and a Unicode-safe per-user installer."""
from pathlib import Path

INSTALL = r'''param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$dest = Join-Path $env:LOCALAPPDATA 'Programs\BoothNest'
$running = Get-CimInstance Win32_Process -Filter "Name='BoothNest.exe'" |
    Where-Object { $_.ExecutablePath -eq (Join-Path $dest 'BoothNest.exe') }
if ($running) { throw '请先关闭正在运行的 BoothNest 再安装。' }
New-Item -ItemType Directory -Path $dest -Force | Out-Null
if ([IO.Path]::GetFullPath($source).TrimEnd('\') -ne [IO.Path]::GetFullPath($dest).TrimEnd('\')) {
    & robocopy $source $dest /E /NFL /NDL /NJH /NJS /NC /NS /XF '*.log' | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制失败，robocopy 返回 $LASTEXITCODE" }
}
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'BoothNest.lnk'))
$link.TargetPath = Join-Path $dest 'BoothNest.exe'
$link.WorkingDirectory = $dest
$link.Save()
Write-Host "安装完成：$dest"
Write-Host '更新会保留个人扫描数据。卸载方法见 README.md。'
if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $dest 'BoothNest.exe') }
'''


def generate(target: Path):
    target.mkdir(parents=True, exist_ok=True)
    launcher = ('@echo off\r\n'
                '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
                '-NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*\r\n'
                'if errorlevel 1 pause\r\n')
    (target / "install.cmd").write_bytes(launcher.encode("ascii"))
    (target / "install.ps1").write_bytes(INSTALL.replace("\n", "\r\n").encode("utf-8-sig"))


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "dist" / "BoothNest")
