$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Include = Join-Path $RepoRoot "dsp\bootloader_algorithm\include"
$Core = Join-Path $RepoRoot "dsp\bootloader_algorithm\core"
$ServiceInclude = Join-Path $RepoRoot "dsp\flash_service_lib\include"
$ServiceSrc = Join-Path $RepoRoot "dsp\flash_service_lib\src"
$TestSource = Join-Path $PSScriptRoot "test_boot_algorithm.c"
$Output = Join-Path ([System.IO.Path]::GetTempPath()) "bootloader_host_tests.exe"

& gcc -std=c11 -Wall -Wextra -Werror "-I$Include" "-I$ServiceInclude" "-I$ServiceSrc" `
    (Join-Path $Core "boot_io.c") `
    (Join-Path $Core "boot_protocol.c") `
    (Join-Path $Core "boot_device_info.c") `
    (Join-Path $Core "boot_algorithm.c") `
    (Join-Path $ServiceSrc "boot_flash_error_map_lib.c") `
    (Join-Path $ServiceSrc "boot_flash_session_lib.c") `
    (Join-Path $ServiceSrc "boot_flash_service_lib.c") `
    $TestSource -o $Output

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $Output
exit $LASTEXITCODE
