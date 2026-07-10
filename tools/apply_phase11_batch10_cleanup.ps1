$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot

$obsoleteFiles = @(
    "pc/src/bootloader_upgrade_tool/gui/styles.py",
    "pc/src/bootloader_upgrade_tool/gui/pages/placeholder_page.py"
)

foreach ($relativePath in $obsoleteFiles) {
    $path = Join-Path $repositoryRoot $relativePath
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Force
        Write-Host "Removed $relativePath"
    } else {
        Write-Host "Already absent: $relativePath"
    }
}
