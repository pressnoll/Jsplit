<#
    build_installer.ps1  —  produce JsplitSetup.exe from a clean checkout.

    This is the MAINTAINER's one-shot. The end user just runs the resulting
    JsplitSetup.exe. Run this from the repo root:

        powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1

    What it does:
      1. builds the VST3 with CMake  (needs Visual Studio 2022 + CMake)
      2. downloads a portable, relocatable CPython  (python-build-standalone)
      3. stages: VST3 + engine code + python (+ pre-downloaded wheels if -Offline)
      4. compiles installer\jsplit.iss with Inno Setup (iscc) -> dist\JsplitSetup.exe

    Prerequisites (install once):
      • Visual Studio 2022 (Desktop C++)          https://visualstudio.microsoft.com/
      • CMake 3.22+                               https://cmake.org/download/
      • Inno Setup 6 (provides iscc.exe)          https://jrsoftware.org/isdl.php
      • Internet access (JUCE fetch, Python, wheels)
#>

[CmdletBinding()]
param(
    [switch]$Offline = $true,          # bundle wheels so the installer needs no internet
    [string]$PyVersion = "3.11.9",
    [string]$PyTag     = "20240415",   # python-build-standalone release tag
    [string]$AppVer    = "0.1.0"
)

$ErrorActionPreference = "Stop"
$root    = Split-Path -Parent $PSScriptRoot          # repo root
$staging = Join-Path $PSScriptRoot "staging"
$dist    = Join-Path $root "dist"
$build   = Join-Path $root "plugin\build"

function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Need($exe, $hint) {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        throw "Required tool '$exe' not found on PATH. $hint"
    }
}

Step "Checking tools"
Need cmake "Install CMake and add it to PATH."
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $guess = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $guess) { $iscc = $guess } else { throw "Inno Setup (iscc.exe) not found. Install Inno Setup 6." }
}
Write-Host "iscc: $iscc"

# ── 1. build the plugin ────────────────────────────────────────────────────
# JSPLIT_COPY_AFTER_BUILD=OFF: the installer places the VST3 itself, so we don't
# want the build to also copy it into this machine's system folder (which is what
# lets the same script run unchanged on a locked-down cloud build machine).
Step "Building VST3 (CMake / Visual Studio)"
cmake -S (Join-Path $root "plugin") -B $build -G "Visual Studio 17 2022" -A x64 -D JSPLIT_COPY_AFTER_BUILD=OFF
cmake --build $build --config Release --target Jsplit_VST3

$vst3 = Get-ChildItem -Path $build -Recurse -Directory -Filter "Jsplit.vst3" |
        Select-Object -First 1 -ExpandProperty FullName
if (-not $vst3) { throw "Build finished but Jsplit.vst3 was not found under $build" }
Write-Host "VST3: $vst3"

# ── 2. reset staging ───────────────────────────────────────────────────────
Step "Staging files"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

# plugin
Copy-Item $vst3 (Join-Path $staging "Jsplit.vst3") -Recurse

# engine code (only what the engine needs at runtime)
$engineDst = Join-Path $staging "engine"
New-Item -ItemType Directory -Force -Path $engineDst | Out-Null
Copy-Item (Join-Path $root "src")     (Join-Path $engineDst "src")     -Recurse
Copy-Item (Join-Path $root "scripts") (Join-Path $engineDst "scripts") -Recurse
Copy-Item (Join-Path $root "requirements.txt") $engineDst
# don't ship caches
Get-ChildItem $engineDst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# ── 3. portable Python (relocatable) ───────────────────────────────────────
Step "Fetching portable Python $PyVersion ($PyTag)"
$pyUrl = "https://github.com/indygreg/python-build-standalone/releases/download/$PyTag/cpython-$PyVersion+$PyTag-x86_64-pc-windows-msvc-install_only.tar.gz"
$pyTar = Join-Path $env:TEMP "jsplit-python.tar.gz"
Invoke-WebRequest -Uri $pyUrl -OutFile $pyTar
# 'install_only' archives extract a top-level 'python' folder with python.exe at its root
tar -xzf $pyTar -C $staging
if (-not (Test-Path (Join-Path $staging "python\python.exe"))) {
    throw "Portable Python did not extract as expected (no python\python.exe). Check PyTag/PyVersion."
}
$py = Join-Path $staging "python\python.exe"
& $py -m pip install --upgrade pip | Out-Host

# ── 4. dependencies ────────────────────────────────────────────────────────
if ($Offline) {
    Step "Pre-downloading wheels for offline install"
    $wheels = Join-Path $staging "wheels"
    New-Item -ItemType Directory -Force -Path $wheels | Out-Null
    & $py -m pip download -r (Join-Path $engineDst "requirements.txt") -d $wheels | Out-Host
} else {
    Write-Host "Online mode: deps will be pip-installed on the user's machine at install time."
}

# ── 5. compile the installer ───────────────────────────────────────────────
Step "Compiling installer with Inno Setup"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$offFlag = if ($Offline) { "1" } else { "0" }
& $iscc `
    "/DStaging=$staging" `
    "/DAppVer=$AppVer" `
    "/DOffline=$offFlag" `
    "/O$dist" `
    (Join-Path $PSScriptRoot "jsplit.iss") | Out-Host

$out = Join-Path $dist "JsplitSetup.exe"
if (Test-Path $out) {
    Step "Done"
    Write-Host "Installer: $out" -ForegroundColor Green
    Write-Host "Share that single file. Users run it; it installs the VST3 + engine and self-configures."
} else {
    throw "Inno Setup did not produce $out"
}
