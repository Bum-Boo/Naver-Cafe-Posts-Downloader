$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $ProjectRoot

$pathsToRemove = @(
    "build",
    "dist"
)

foreach ($relativePath in $pathsToRemove) {
    $target = Join-Path $ProjectRoot $relativePath
    if (Test-Path $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

$releaseDir = Join-Path $ProjectRoot "release"
if (Test-Path $releaseDir) {
    Get-ChildItem -LiteralPath $releaseDir -Filter "*.zip" -File | Remove-Item -Force
}

Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $ProjectRoot -Filter "*.spec" -File |
    Where-Object { $_.Name -ne "NaverCafeArchiveManager.spec" } |
    Remove-Item -Force

Write-Host "Build outputs cleaned."
