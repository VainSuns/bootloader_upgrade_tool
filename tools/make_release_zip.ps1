param(
    [string]$Version = "v0.1.0"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PortableName = "DSP28377D_Bootloader_Upgrade_Tool"
$PortableDir = Join-Path $RepoRoot "dist\$PortableName"
$ZipPath = Join-Path $RepoRoot "dist\DSP28377D_Bootloader_Upgrade_Tool_${Version}_win64.zip"
$DocsOut = Join-Path $PortableDir "docs"

if (-not (Test-Path -LiteralPath $PortableDir)) {
    throw "Portable output not found: $PortableDir"
}

New-Item -ItemType Directory -Path $DocsOut -Force | Out-Null
foreach ($doc in @(
    "docs\guides\windows_portable_build.md",
    "docs\releases\v0.1.0.md"
)) {
    $source = Join-Path $RepoRoot $doc
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Required release document not found: $source"
    }

    Copy-Item -LiteralPath $source -Destination $DocsOut -Force
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -LiteralPath $PortableDir -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "Release zip created: $ZipPath"
