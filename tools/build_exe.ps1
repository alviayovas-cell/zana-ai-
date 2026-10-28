# Build the one-folder Windows app into dist\Zana\.  Run from the project root.
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"
& $py -m PyInstaller zana.spec --noconfirm --clean
Write-Host "Built: $((Resolve-Path .\dist\Zana\Zana.exe))"
