param(
    [string]$Python = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Native {
    param(
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$ArgumentList
    )
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $ArgumentList"
    }
}

Push-Location $RepoRoot
try {
    if (-not $Python) {
        $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
        $Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
    }

    if (-not $SkipInstall) {
        Invoke-Native $Python @("-m", "pip", "install", "--no-build-isolation", "-e", ".[packaging]")
    }

    Invoke-Native $Python @("-m", "PyInstaller", "--clean", "--noconfirm", ".\packaging\DSP28377D_Bootloader_Upgrade_Tool.spec")

    $DistDir = Join-Path $RepoRoot "dist\DSP28377D_Bootloader_Upgrade_Tool"
    Copy-Item -LiteralPath ".\packaging\README_quick_start.md" -Destination (Join-Path $DistDir "README_quick_start.md") -Force

    Write-Host "Portable build created: $DistDir"
}
finally {
    Pop-Location
}
