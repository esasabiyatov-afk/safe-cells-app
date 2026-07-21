param(
    [string]$InstallDirectory = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$installPath = [System.IO.Path]::GetFullPath($InstallDirectory)
$executable = Join-Path $installPath "safe-cells.exe"
$configuration = Join-Path $installPath "config.json"

if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "safe-cells.exe was not found."
}
if (-not (Test-Path -LiteralPath $configuration -PathType Leaf)) {
    throw "Create config.json beside safe-cells.exe first."
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0KHQtdC50YTQvtCy0YvQtSDRj9GH0LXQudC60Lg="))
$description = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("0JvQvtC60LDQu9GM0L3QvtC1INC/0YDQuNC70L7QttC10L3QuNC1INGD0YfRkdGC0LAg0YHQtdC50YTQvtCy0YvRhSDRj9GH0LXQtdC6"))
$shortcutPath = Join-Path $desktop "$shortcutName.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $executable
$shortcut.WorkingDirectory = $installPath
$shortcut.Description = $description
$shortcut.IconLocation = "$executable,0"
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Host "Desktop shortcut created."
