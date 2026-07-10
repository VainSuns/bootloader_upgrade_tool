param(
    [string]$Version = "3.44.0",
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$CacheRoot = Join-Path $ProjectRoot ".cache"
$Archive = Join-Path $CacheRoot "tabler-icons-$Version.zip"
$ExtractedRoot = Join-Path $CacheRoot "tabler-icons-$Version"
$Manifest = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\icons\icon_manifest.json"
$Destination = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\icons\tabler\outline"
$ResolvedManifest = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\icons\resolved_manifest.json"
$LicenseDestination = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\licenses\TABLER_ICONS_LICENSE.txt"
$SyncScript = Join-Path $ProjectRoot "tools\sync_tabler_icons.py"

New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null

if (-not (Test-Path $ExtractedRoot)) {
    if (-not (Test-Path $Archive)) {
        Write-Host "Downloading Tabler Icons v$Version..."
        Invoke-WebRequest `
            -Uri "https://github.com/tabler/tabler-icons/archive/refs/tags/v$Version.zip" `
            -OutFile $Archive
    }

    Write-Host "Extracting $Archive..."
    Expand-Archive -Path $Archive -DestinationPath $CacheRoot -Force
}

python $SyncScript `
    --source $ExtractedRoot `
    --manifest $Manifest `
    --destination $Destination `
    --resolved-manifest $ResolvedManifest `
    --license-destination $LicenseDestination `
    --stroke-color "#526173" `
    --stroke-width "2" `
    --clean

if ($LASTEXITCODE -ne 0) {
    throw "Tabler icon synchronization failed with exit code $LASTEXITCODE."
}
