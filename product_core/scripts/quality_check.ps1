# Kiểm tra chất lượng cấp monorepo cho MSB Radar.
# Chạy từ thư mục gốc repo:  .\scripts\quality_check.ps1
# Mỗi subsystem chỉ được kiểm tra khi nó đã tồn tại, nên script này chạy được
# xuyên suốt từ Phase 1 (chỉ có edge/) tới Phase 3+ (có thêm server/ và web/).

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot
$failed = @()

function Invoke-Step {
    param([string]$Label, [scriptblock]$Body)
    Write-Host "`n--- $Label ---" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        $script:failed += $Label
        Write-Host "FAIL: $Label" -ForegroundColor Red
    }
}

# ---------------- EDGE (Python / PyWebView) ----------------
$edge = Join-Path $ROOT "edge"
if (Test-Path (Join-Path $edge "main.py")) {
    Push-Location $edge
    Invoke-Step "edge: compileall"  { python -m compileall -q app tests }
    Invoke-Step "edge: pytest"      { python -m pytest -q }
    Invoke-Step "edge: ruff"        { python -m ruff check app tests }
    Pop-Location
} else {
    Write-Host "Bo qua edge/ (chua co main.py)" -ForegroundColor DarkGray
}

# ---------------- SERVER (Django Hub) ----------------
$server = Join-Path $ROOT "server"
if (Test-Path (Join-Path $server "manage.py")) {
    Push-Location $server
    Invoke-Step "server: django check" { python manage.py check }
    Invoke-Step "server: migrations"   { python manage.py makemigrations --check --dry-run }
    Invoke-Step "server: django tests" { python manage.py test }
    Invoke-Step "server: ruff"         { python -m ruff check . }
    Pop-Location
} else {
    Write-Host "Bo qua server/ (chua co manage.py - Phase 3)" -ForegroundColor DarkGray
}

# ---------------- WEB (React / Vite) ----------------
$web = Join-Path $ROOT "web"
if (Test-Path (Join-Path $web "package.json")) {
    Push-Location $web
    Invoke-Step "web: tests"     { npm test }
    Invoke-Step "web: typecheck" { npm run typecheck }
    Invoke-Step "web: lint"      { npm run lint }
    Invoke-Step "web: build"     { npm run build }
    Pop-Location
} else {
    Write-Host "Bo qua web/ (chua co package.json - Phase 3)" -ForegroundColor DarkGray
}

# ---------------- AGENT (Prospect Agent / AgentBase) ----------------
$agent = Join-Path $ROOT "agent"
if (Test-Path (Join-Path $agent "app.py")) {
    Push-Location $agent
    Invoke-Step "agent: pytest" { python -m pytest tests -q }
    Invoke-Step "agent: ruff"   { python -m ruff check app.py tests }
    Pop-Location
} else {
    Write-Host "Bo qua agent/ (chua co app.py)" -ForegroundColor DarkGray
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "=== THAT BAI: $($failed -join ', ') ===" -ForegroundColor Red
    exit 1
}
Write-Host "=== TAT CA KIEM TRA DA QUA ===" -ForegroundColor Green
exit 0
