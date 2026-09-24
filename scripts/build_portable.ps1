$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = Join-Path $projectRoot "safe-cells.spec"
$adminSpec = Join-Path $projectRoot "safe-cells-admin.spec"
$distRoot = Join-Path $projectRoot "dist"
$portable = Join-Path $distRoot "safe-cells-portable"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment .venv was not found."
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
    & $python -m PyInstaller --noconfirm --clean $adminSpec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller admin tool failed."
    }
}
finally {
    Pop-Location
}

$builtExecutable = Join-Path $distRoot "safe-cells.exe"
if (-not (Test-Path -LiteralPath $builtExecutable -PathType Leaf)) {
    throw "Built safe-cells.exe was not found."
}

$portableFull = [System.IO.Path]::GetFullPath($portable)
if (-not $portableFull.StartsWith($projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe portable output path."
}
if (Test-Path -LiteralPath $portableFull) {
    Remove-Item -LiteralPath $portableFull -Recurse -Force
}
New-Item -ItemType Directory -Path $portableFull | Out-Null

Copy-Item -LiteralPath $builtExecutable -Destination (Join-Path $portableFull "safe-cells.exe")
Copy-Item -LiteralPath (Join-Path $distRoot "safe-cells-admin.exe") -Destination (Join-Path $portableFull "safe-cells-admin.exe")
Copy-Item -LiteralPath (Join-Path $projectRoot "config.example.json") -Destination (Join-Path $portableFull "config.example.json")
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\PORTABLE_README.txt") -Destination (Join-Path $portableFull "README.txt")
Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\OFFICE_INSTALL.txt") -Destination (Join-Path $portableFull "OFFICE_INSTALL.txt")
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\create_shortcut.ps1") -Destination (Join-Path $portableFull "create_shortcut.ps1")
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\create-shortcut.cmd") -Destination (Join-Path $portableFull "create-shortcut.cmd")
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\configure_database.ps1") -Destination (Join-Path $portableFull "configure_database.ps1")
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\configure-database.cmd") -Destination (Join-Path $portableFull "configure-database.cmd")
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\migrate_to_v12.ps1") -Destination (Join-Path $portableFull "migrate_to_v12.ps1")
Copy-Item -LiteralPath (Join-Path $projectRoot "scripts\migrate-to-v12.cmd") -Destination (Join-Path $portableFull "migrate-to-v12.cmd")

Write-Host "Ready: dist\safe-cells-portable"
