# Instalación por usuario, sin elevación. Ejecutar después de Build-Windows.ps1.
$ErrorActionPreference = 'Stop'
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$distribution = Join-Path $desktopRoot 'dist'
if (-not (Test-Path -LiteralPath (Join-Path $distribution 'PPS-Desktop.exe'))) {
    throw 'No existe la distribución. Ejecutar Build-Windows.ps1 primero.'
}
$installRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs/PPS-Desktop/0.1.0'
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
Get-ChildItem -LiteralPath $distribution | Copy-Item -Destination $installRoot -Recurse -Force
$startMenu = [Environment]::GetFolderPath('Programs')
$shortcutPath = Join-Path $startMenu 'PPS Desktop.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $installRoot 'PPS-Desktop.exe'
$shortcut.WorkingDirectory = $installRoot
$shortcut.Description = 'PPS - Auditoría de seguridad FortiGate'
$shortcut.Save()
Write-Output "PPS Desktop instalado en $installRoot"
Write-Output "Acceso directo: $shortcutPath"
