param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$env:QT_QPA_PLATFORM = "offscreen"

$scales = @("1", "1.25", "1.5")
foreach ($scale in $scales) {
    Write-Host "Running Phase 11 GUI matrix at QT_SCALE_FACTOR=$scale"
    $env:QT_SCALE_FACTOR = $scale

    & $Python -m pytest `
        .\tests\unit\test_gui_phase11_final_validation.py `
        .\tests\unit\test_gui_layout_preview.py `
        .\tests\unit\test_gui_static_layout.py `
        -q

    if ($LASTEXITCODE -ne 0) {
        throw "Phase 11 GUI validation failed at QT_SCALE_FACTOR=$scale"
    }
}

Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
Write-Host "Phase 11 GUI visual matrix passed at 100%, 125%, and 150%."
