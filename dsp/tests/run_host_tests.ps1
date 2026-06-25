$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$CommonInclude = Join-Path $RepoRoot "dsp\bootloader_common\include"
$CommonSrc = Join-Path $RepoRoot "dsp\bootloader_common\src"
$CoreInclude = Join-Path $RepoRoot "dsp\bootloader_core\include"
$CoreSrc = Join-Path $RepoRoot "dsp\bootloader_core\src"
$ServiceInclude = Join-Path $RepoRoot "dsp\flash_service_lib\include"
$ServiceSrc = Join-Path $RepoRoot "dsp\flash_service_lib\src"
$TestSource = Join-Path $PSScriptRoot "test_boot_algorithm.c"
$Output = Join-Path ([System.IO.Path]::GetTempPath()) "bootloader_host_tests.exe"

& gcc -std=c11 -Wall -Wextra -Werror "-I$CommonInclude" "-I$CoreInclude" "-I$ServiceInclude" "-I$ServiceSrc" `
    (Join-Path $CommonSrc "boot_protocol.c") `
    (Join-Path $CommonSrc "boot_device_info.c") `
    (Join-Path $CoreSrc "boot_io.c") `
    (Join-Path $CoreSrc "boot_protocol_core.c") `
    (Join-Path $CoreSrc "boot_algorithm.c") `
    (Join-Path $ServiceSrc "boot_flash_error_map_lib.c") `
    (Join-Path $ServiceSrc "boot_flash_session_lib.c") `
    (Join-Path $ServiceSrc "boot_flash_service_lib.c") `
    $TestSource -o $Output

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $Output
exit $LASTEXITCODE
