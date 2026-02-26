# Start Fabio Bot API server - finds Python and runs uvicorn
# Optional: set $env:FABIO_PYTHON = "C:\path\to\python.exe" if the script can't find Python
$host.UI.RawUI.WindowTitle = "Fabio Bot Server"
Set-Location $PSScriptRoot

$python = $null
if ($env:FABIO_PYTHON -and (Test-Path $env:FABIO_PYTHON)) { $python = $env:FABIO_PYTHON }
if (-not $python) {
foreach ($name in @('python', 'python3', 'py')) {
    $p = Get-Command $name -ErrorAction SilentlyContinue
    if ($p) { $python = $p.Source; break }
}
if (-not $python) {
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\python3.12.exe",
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\Python312\python.exe"
    )
    foreach ($path in $paths) {
        if (Test-Path $path) { $python = $path; break }
    }
}
# Microsoft Store Python (in Packages)
if (-not $python) {
    $pkgDir = "$env:LOCALAPPDATA\Packages"
    if (Test-Path $pkgDir) {
        $storePython = Get-ChildItem -Path $pkgDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "PythonSoftwareFoundation.Python*" } | ForEach-Object {
            $exe = Join-Path $_.FullName "LocalCache\local-packages\Python312\python.exe"
            if (Test-Path $exe) { $exe; break }
            $exe = Join-Path $_.FullName "LocalCache\local-packages\Python311\python.exe"
            if (Test-Path $exe) { $exe; break }
        } | Select-Object -First 1
        if ($storePython) { $python = $storePython }
    }
}
# Search PATH directories
if (-not $python) {
    foreach ($dir in ($env:Path -split ';')) {
        if ([string]::IsNullOrWhiteSpace($dir)) { continue }
        $exe = Join-Path $dir "python.exe"
        if (Test-Path $exe) { $python = $exe; break }
    }
}
# where.exe (finds python on PATH)
if (-not $python) {
    $where = (where.exe python 2>$null) | Select-Object -First 1
    if ($where -and (Test-Path $where)) { $python = $where }
}
}

if (-not $python) {
    Write-Host "Python not found. Install Python from https://www.python.org/downloads/ and check 'Add Python to PATH'."
    Write-Host "Or install from Microsoft Store: search 'Python 3.12'."
    Write-Host ""
    Write-Host "If Python IS installed, find it with:  where.exe python"
    Write-Host "Then run:  & 'C:\path\to\python.exe' -m uvicorn api_server:app --host 0.0.0.0 --port 8000"
    exit 1
}

Write-Host "Using: $python"
& $python -m uvicorn api_server:app --host 0.0.0.0 --port 8000
if ($LASTEXITCODE -ne 0) {
    Write-Host "If uvicorn failed: run   $python -m pip install uvicorn fastapi   then try again."
}
