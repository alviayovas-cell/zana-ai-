# Create/update the "Zana" Desktop shortcut for a built folder (default: dist_next\Zana\Zana.exe).
# Never touches the exe itself. Refuses to replace an existing shortcut unless -Force is given.
param([switch]$Force, [string]$Folder = "dist_next")
$exe = (Resolve-Path "$PSScriptRoot\..\$Folder\Zana\Zana.exe").Path
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "Zana.lnk"
if ((Test-Path $lnk) -and -not $Force) { Write-Host "Shortcut already exists: $lnk (use -Force to replace)"; exit 1 }
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $exe
$s.WorkingDirectory = Split-Path $exe
$s.IconLocation = "$exe,0"
$s.Description = "Zana - local voice assistant"
$s.Save()
Write-Host "Shortcut: $lnk -> $exe"
