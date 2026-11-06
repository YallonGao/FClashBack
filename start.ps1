# 本地启动 FClashBack。默认监听 127.0.0.1:8780，数据在 ./data。
# 需要 Python 3.11+，首次运行会自建 .venv 并安装依赖。
param(
    [int]$Port = 8780,
    [switch]$Reload,
    # Bind every interface so phones on the same network can reach the API.
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "creating .venv" -ForegroundColor Cyan
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
if (Test-Path "requirements-dev.txt") {
    & .\.venv\Scripts\python.exe -m pip install --quiet -r requirements-dev.txt
}

$dataDir = Join-Path $PSScriptRoot "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

# The secret decides every token. A new one per start would sign every device
# out on restart, so a local one is generated once and reused.
$secretFile = Join-Path $dataDir "dev-secret.txt"
if (-not $env:FCLASH_JWT_SECRET) {
    if (-not (Test-Path $secretFile)) {
        $bytes = New-Object byte[] 48
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        [Convert]::ToBase64String($bytes) | Set-Content -NoNewline $secretFile
    }
    $env:FCLASH_JWT_SECRET = Get-Content -Raw $secretFile
}

if (-not $env:FCLASH_DATA_DIR) { $env:FCLASH_DATA_DIR = $dataDir }

# Serve the built console from the sibling repo when it exists.
$frontend = Join-Path (Split-Path $PSScriptRoot) "FClashFront\dist"
if ((-not $env:FCLASH_FRONTEND_DIR) -and (Test-Path (Join-Path $frontend "index.html"))) {
    $env:FCLASH_FRONTEND_DIR = $frontend
}

Write-Host ""
Write-Host "  API      http://127.0.0.1:$Port/docs" -ForegroundColor Green
Write-Host "  Console  $(if ($env:FCLASH_FRONTEND_DIR) { "http://127.0.0.1:$Port/" } else { "not built; run FClashFront/start.ps1" })" -ForegroundColor Green
Write-Host "  Data     $env:FCLASH_DATA_DIR" -ForegroundColor DarkGray
Write-Host ""

$bindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
if ($Lan) {
    $address = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1).IPAddress
    if ($address) {
        Write-Host "  LAN      http://$address`:$Port/  (phone uses this)" -ForegroundColor Yellow
        Write-Host "           Windows 防火墙需要放行该端口" -ForegroundColor DarkGray
    }
}

$arguments = @("-m", "uvicorn", "app.main:app", "--host", $bindHost, "--port", "$Port")
if ($Reload) { $arguments += "--reload" }
& .\.venv\Scripts\python.exe @arguments
