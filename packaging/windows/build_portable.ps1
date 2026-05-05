$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $ProjectRoot

$python = "python"
try {
    & $python --version | Out-Null
} catch {
    $python = "py"
}

Write-Host "Cleaning previous build outputs..."
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "clean_build.ps1")

Write-Host "Installing Python dependencies..."
& $python -m pip install -r requirements.txt

$version = (& $python -c "from app import APP_VERSION; print(APP_VERSION)").Trim()
$appName = "NaverCafeArchiveManager"
$distAppDir = Join-Path $ProjectRoot "dist\$appName"
$releaseDir = Join-Path $ProjectRoot "release"
$releaseZip = Join-Path $releaseDir "$appName-v$version-win64.zip"
$browserCache = Join-Path $ProjectRoot ".playwright-browsers"

Write-Host "Installing Playwright Chromium for portable package..."
$env:PLAYWRIGHT_BROWSERS_PATH = $browserCache
& $python -m playwright install chromium

Write-Host "Building PyInstaller onedir app..."
& $python -m PyInstaller --noconfirm --clean (Join-Path $ProjectRoot "NaverCafeArchiveManager.spec")

if (-not (Test-Path $distAppDir)) {
    throw "PyInstaller output folder was not created: $distAppDir"
}

$portableBrowserDir = Join-Path $distAppDir "ms-playwright"
if (Test-Path $portableBrowserDir) {
    Remove-Item -LiteralPath $portableBrowserDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $portableBrowserDir | Out-Null
Copy-Item -Path (Join-Path $browserCache "*") -Destination $portableBrowserDir -Recurse -Force

Copy-Item -LiteralPath (Join-Path $ProjectRoot "README_QUICKSTART.txt") -Destination $distAppDir -Force

$runtimeDataDir = Join-Path $distAppDir "data"
$runtimeSavedPostsDir = Join-Path $distAppDir "saved_posts"
New-Item -ItemType Directory -Force -Path $runtimeDataDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeSavedPostsDir | Out-Null

$forbiddenPaths = @(
    "data\browser_profile",
    "data\auth",
    "data\archive_index.json",
    "data\batches",
    "saved_posts\_debug"
)

foreach ($relativePath in $forbiddenPaths) {
    $target = Join-Path $distAppDir $relativePath
    if (Test-Path $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
if (Test-Path $releaseZip) {
    Remove-Item -LiteralPath $releaseZip -Force
}

Write-Host "Creating release ZIP..."
Compress-Archive -LiteralPath $distAppDir -DestinationPath $releaseZip -Force

Write-Host ""
Write-Host "Portable package created:"
Write-Host $releaseZip
