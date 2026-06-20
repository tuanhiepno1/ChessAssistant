$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[1/4] Kiem tra Python..."
$Python = Get-Command py -ErrorAction SilentlyContinue
if ($null -eq $Python) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
}
if ($null -eq $Python) {
    throw "Khong tim thay Python. Hay cai Python 3.11 tro len va chon Add Python to PATH."
}

Write-Host "[2/4] Tao moi truong .venv..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    if ($Python.Name -eq "py.exe") {
        & $Python.Source -3 -m venv .venv
    } else {
        & $Python.Source -m venv .venv
    }
}

Write-Host "[3/4] Cai thu vien Python..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "[4/4] Kiem tra tai nguyen..."
if (-not (Test-Path "models\chess_piece_model.pt")) {
    Write-Warning "Thieu models\chess_piece_model.pt; che do DOM van chay, nhan dien anh se khong hoat dong."
}

Write-Host ""
Write-Host "Cai dat Python hoan tat." -ForegroundColor Green
Write-Host "Buoc con lai: tai Stockfish, mo Cai dat trong ung dung va chon stockfish.exe."
Write-Host "Khoi dong bang MoTroLyCoVua.bat"

