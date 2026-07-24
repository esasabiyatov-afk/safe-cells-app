param(
    [string]$InstallDirectory = $PSScriptRoot,
    [string]$DatabaseDirectory = ""
)

$ErrorActionPreference = "Stop"
$installPath = [System.IO.Path]::GetFullPath($InstallDirectory)
$executable = Join-Path $installPath "safe-cells.exe"
$configPath = Join-Path $installPath "config.json"
$previousConfigPath = Join-Path $installPath "config.previous.json"

if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "safe-cells.exe was not found beside the configuration tool."
}

if (-not $DatabaseDirectory) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select the shared SafeCells data folder."
    $dialog.ShowNewFolderButton = $false
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host "Configuration was not changed."
        exit 2
    }
    $DatabaseDirectory = $dialog.SelectedPath
}

$databasePath = [System.IO.Path]::GetFullPath($DatabaseDirectory)
if (-not (Test-Path -LiteralPath $databasePath -PathType Container)) {
    throw "The selected data folder is unavailable."
}

$requiredFiles = @(
    "vault_cells.sqlite3",
    "vault_archive.sqlite3"
)
foreach ($name in $requiredFiles) {
    $path = Join-Path $databasePath $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "The selected folder does not contain $name."
    }
    if ((Get-Item -LiteralPath $path).Length -le 0) {
        throw "The selected folder contains an empty $name."
    }
}

$templateDirectory = Join-Path $databasePath "templates"
if (-not (Test-Path -LiteralPath $templateDirectory -PathType Container)) {
    throw "The selected folder does not contain the templates directory."
}

$requiredTemplates = @(
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0JDQutGCINC/0YDQuNC10LzQsCDQv9C10YDQtdC00LDRhyDRgdC10LnRhC5kb2N4")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0LHQuNGA0LrQsCDQvdCwINC60L7QvdCy0LXRgNGCLmRvY3g=")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0JTQvtCz0L7QstC+0YAg0LjQvdC00LjQstC40LTRg9Cw0LvRjNC90L7Qs9C+INGB0LXQudGE0LAg0YQu0LsuZG9jeA==")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0KDQsNGB0L/QvtGA0Y/QttC10L3QuNC1INCe0YLQutGA0YvRgtC40LUg0YHQtdC50YQuZG9jeA==")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0JTQvtC/LiDRgdC+0LPQu9Cw0YjQtdC90LjQtSDRgdC10LnRhCDRhC7Quy5kb2N4")),
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0KDQsNGB0L/QvtGA0Y/QttC10L3QuNC1INCX0LDQutGA0YvRgtC40LUg0YHQtdC50YQuZG9jeA=="))
)
foreach ($name in $requiredTemplates) {
    if (-not (Test-Path -LiteralPath (Join-Path $templateDirectory $name) -PathType Leaf)) {
        throw "The selected folder does not contain all approved DOCX templates."
    }
}

$configuration = [ordered]@{
    database_directory = $databasePath
    working_database_name = "vault_cells.sqlite3"
    archive_database_name = "vault_archive.sqlite3"
}
$json = ($configuration | ConvertTo-Json) + [Environment]::NewLine
$temporaryPath = Join-Path $installPath (".config." + [Guid]::NewGuid().ToString("N") + ".tmp")
$utf8 = New-Object System.Text.UTF8Encoding($false)

try {
    [System.IO.File]::WriteAllText($temporaryPath, $json, $utf8)
    $verified = Get-Content -Raw -Encoding UTF8 -LiteralPath $temporaryPath | ConvertFrom-Json
    if (
        $verified.database_directory -ne $databasePath -or
        $verified.working_database_name -ne "vault_cells.sqlite3" -or
        $verified.archive_database_name -ne "vault_archive.sqlite3"
    ) {
        throw "The generated configuration did not pass verification."
    }
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        Copy-Item -LiteralPath $configPath -Destination $previousConfigPath -Force
    }
    Move-Item -LiteralPath $temporaryPath -Destination $configPath -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

Write-Host "Configuration saved. Start Safe Cells from the desktop shortcut."
