# Local backend setup (no Docker) — Windows PowerShell
param(
    [string]$MySqlBin = "C:\Program Files\MySQL\MySQL Server 9.7\bin\mysql.exe",
    [string]$RootUser = "root",
    [string]$RootPassword = $env:MYSQL_ROOT_PASSWORD
)

$ErrorActionPreference = "Stop"
# This file lives in <repo>/scripts, so the parent directory is the repository root.
$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root "backend"
$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
$SqlFile = Join-Path $PSScriptRoot "setup_mysql.sql"

Write-Host "=== Spy Love local setup (MySQL, no Docker) ===" -ForegroundColor Cyan

if (-not (Test-Path $MySqlBin)) {
    Write-Error "mysql.exe not found at: $MySqlBin`nInstall MySQL 8+ or pass -MySqlBin path."
}

if (-not $RootPassword) {
    $secure = Read-Host "MySQL root password" -AsSecureString
    $RootPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    )
}

Write-Host "Creating database and user..."
Get-Content $SqlFile -Raw | & $MySqlBin -u $RootUser -p"$RootPassword"
if ($LASTEXITCODE -ne 0) {
    Write-Error "MySQL setup failed. Check root password and that MySQL service is running."
}

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install -r (Join-Path $Backend "requirements\dev.txt")

Write-Host "Running migrations..."
Push-Location $Backend
& $VenvPython manage.py migrate
Pop-Location

Write-Host ""
Write-Host "Done. Start the API with:" -ForegroundColor Green
Write-Host "  cd backend"
Write-Host "  ..\venv\Scripts\python.exe manage.py runserver"
