$ErrorActionPreference = 'Stop'
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $desktopRoot '..')).Path
$pythonExe = Join-Path $repoRoot '.venv-gui/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Crear .venv-gui e instalar desktop[dev] antes de compilar. Ver desktop/README.md.'
}
Push-Location $desktopRoot
try {
    & $pythonExe -m PyInstaller --noconfirm --distpath . PPS-Desktop.spec
    if ($LASTEXITCODE -ne 0) { throw 'Falló la compilación con PyInstaller.' }
    Write-Output "Ejecutable: $desktopRoot/dist/PPS-Desktop.exe"
} finally {
    Pop-Location
}
