param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$Manifest = Join-Path `
    $ProjectRoot `
    "pc\src\bootloader_upgrade_tool\gui\resources\icons\icon_manifest.json"

if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    throw "Icon manifest not found: $Manifest"
}

$ManifestData = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json

if ([int]$ManifestData.schema_version -ne 1) {
    throw "Unsupported icon manifest schema_version: $($ManifestData.schema_version)"
}
if ([string]$ManifestData.library -ne "Tabler Icons") {
    throw "Unexpected icon library: $($ManifestData.library)"
}
if ([string]$ManifestData.package -ne "@tabler/icons") {
    throw "Unexpected icon package: $($ManifestData.package)"
}
if ([string]$ManifestData.style -ne "outline") {
    throw "Only Tabler Outline icons are supported."
}

$Version = [string]$ManifestData.version
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw "Icon manifest does not define a Tabler version."
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid Tabler version in icon manifest: $Version"
}

$Tag = "v$Version"
$CacheRoot = Join-Path $ProjectRoot ".cache"
$Archive = Join-Path $CacheRoot "tabler-icons-$Version.zip"
$ArchiveTemp = "$Archive.download"
$ExtractedRoot = Join-Path $CacheRoot "tabler-icons-$Version"
$Destination = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\icons\tabler\outline"
$ResolvedManifest = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\icons\resolved_manifest.json"
$LicenseDestination = Join-Path $ProjectRoot "pc\src\bootloader_upgrade_tool\gui\resources\licenses\TABLER_ICONS_LICENSE.txt"
$SyncScript = Join-Path $ProjectRoot "tools\sync_tabler_icons.py"
$DownloadUri = "https://github.com/tabler/tabler-icons/archive/refs/tags/$Tag.zip"

if (-not (Test-Path -LiteralPath $SyncScript -PathType Leaf)) {
    throw "Tabler synchronization script not found: $SyncScript"
}

New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null

if (-not (Test-Path -LiteralPath $ExtractedRoot -PathType Container)) {
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
        Write-Host "Downloading Tabler Icons $Tag..."

        if (Test-Path -LiteralPath $ArchiveTemp) {
            Remove-Item -LiteralPath $ArchiveTemp -Force
        }

        try {
            Invoke-WebRequest `
                -Uri $DownloadUri `
                -OutFile $ArchiveTemp

            Move-Item `
                -LiteralPath $ArchiveTemp `
                -Destination $Archive `
                -Force
        }
        finally {
            if (Test-Path -LiteralPath $ArchiveTemp) {
                Remove-Item -LiteralPath $ArchiveTemp -Force
            }
        }
    }

    Write-Host "Extracting $Archive..."
    Expand-Archive `
        -LiteralPath $Archive `
        -DestinationPath $CacheRoot `
        -Force
}

python $SyncScript `
    --source $ExtractedRoot `
    --source-version $Version `
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
