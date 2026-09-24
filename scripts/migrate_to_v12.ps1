param([string]$InstallDirectory = $PSScriptRoot)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$installPath = [System.IO.Path]::GetFullPath($InstallDirectory)
$adminExecutable = Join-Path $installPath "safe-cells-admin.exe"
$configPath = Join-Path $installPath "config.json"

if (-not (Test-Path -LiteralPath $adminExecutable -PathType Leaf)) {
    throw "Не найден safe-cells-admin.exe."
}
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "Сначала настройте путь к общей базе через configure-database.cmd."
}

Write-Host "Закройте приложение на всех компьютерах перед миграцией."
$confirmation = Read-Host "Для продолжения введите MIGRATE-TO-12"
if ($confirmation -ne "MIGRATE-TO-12") {
    Write-Host "Миграция отменена."
    exit 2
}

& $adminExecutable migrate-v12 --config $configPath --confirm MIGRATE-TO-12
if ($LASTEXITCODE -ne 0) {
    throw "Миграция не выполнена."
}
Write-Host "Готово. Базы обновлены до версии 12. Старые данные сохранены."
Read-Host "Нажмите Enter, чтобы закрыть окно"
