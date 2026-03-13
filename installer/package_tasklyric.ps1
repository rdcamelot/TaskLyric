param(
    [string]$BuildDir = "build",
    [string]$OutputDir = "dist\TaskLyric"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$buildPath = Join-Path $root $BuildDir
$outputPath = Join-Path $root $OutputDir

$hostBuildDir = Join-Path $buildPath "host"
$dllPath = Join-Path $hostBuildDir "tasklyric_host.dll"
$runtimeDir = Join-Path $root "runtime"

if (-not (Test-Path $dllPath)) {
    $fallback = Get-ChildItem -Path $hostBuildDir -Filter "*tasklyric_host.dll" -File | Select-Object -First 1
    if ($null -eq $fallback) {
        throw "Missing build artifact: $dllPath"
    }
    $dllPath = $fallback.FullName
}

New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $outputPath "runtime") -Force | Out-Null

Copy-Item $dllPath (Join-Path $outputPath "tasklyric_host.dll") -Force
Copy-Item (Join-Path $runtimeDir "tasklyric.runtime.js") (Join-Path $outputPath "runtime\tasklyric.runtime.js") -Force
Copy-Item (Join-Path $root "README.md") (Join-Path $outputPath "README.md") -Force

$toolchain = Get-Command g++ -ErrorAction Stop
$toolchainDir = Split-Path -Parent $toolchain.Source
foreach ($name in @("libstdc++-6.dll", "libgcc_s_seh-1.dll", "libwinpthread-1.dll")) {
    $candidate = Join-Path $toolchainDir $name
    if (Test-Path $candidate) {
        Copy-Item $candidate (Join-Path $outputPath $name) -Force
    }
}

Write-Host "Packaged TaskLyric to $outputPath"
