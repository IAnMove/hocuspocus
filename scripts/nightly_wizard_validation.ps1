$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
if (-not $env:RUN_EXTERNAL_PROVIDER_TESTS) { $env:RUN_EXTERNAL_PROVIDER_TESTS = "0" }
if (-not $env:RUN_GPU_TESTS) { $env:RUN_GPU_TESTS = "0" }
Set-Location $Root
node (Join-Path $Root "scripts/nightly_wizard_report.mjs") @args
exit $LASTEXITCODE
