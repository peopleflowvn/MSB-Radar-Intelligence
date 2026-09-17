<#
.SYNOPSIS
    Đồng bộ dự án từ ổ đĩa cục bộ về thư mục Google Drive.

.DESCRIPTION
    Ổ cục bộ là nơi LÀM VIỆC. Google Drive là bản sao lưu, và là nơi duy nhất giữ
    những thứ không được lên GitHub: .env, cauhinh.json, CSDL ứng viên, file CV.

    Ba nơi lưu, ba vai trò khác nhau — đừng lẫn:

        D:\Project\MSB_Radar     làm việc; nhanh; nguồn sự thật
        GitHub                   chỉ những gì đã commit; chia sẻ, nộp bài
        G:\My Drive\...          sao lưu ĐẦY ĐỦ, gồm cả bí mật và dữ liệu thật

    Loại trừ node_modules và các thư mục cache: đó chính là thứ khiến Google Drive
    không chịu nổi (hàng chục nghìn file nhỏ trên ổ ảo). Chúng dựng lại được từ
    package-lock.json nên không đáng sao lưu.

    Thư mục .git ĐƯỢC sao lưu: nhờ vậy bản trên Drive là một repo khôi phục được
    nguyên vẹn, không phải một đống file rời.

.PARAMETER DryRun
    Chỉ liệt kê những gì sẽ thay đổi, không ghi gì.

.PARAMETER NoDelete
    Giữ lại các file chỉ có ở Drive. Mặc định là soi gương thật: xoá ở nguồn thì
    xoá luôn ở đích.

.EXAMPLE
    .\scripts\sync_to_drive.ps1 -DryRun
    .\scripts\sync_to_drive.ps1
#>
[CmdletBinding()]
param(
    [string]$Source,
    [string]$Destination = "G:\My Drive\Project\MSB_Radar",
    [switch]$DryRun,
    [switch]$NoDelete
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot rỗng khi dùng làm giá trị mặc định của param trong Windows
# PowerShell 5.1, nên phải xác định ở đây — thư mục cha của scripts\ là gốc repo.
if (-not $Source) {
    $Source = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
}

# Thư mục dựng lại được, và chính là thứ Google Drive không chịu nổi.
$excludeDirs = @(
    "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    "staticfiles", "dist", ".vite", ".venv", "venv", "build"
)
$excludeFiles = @("*.pyc", "*.pyo", "*.tmp", "*.part")

# --- Chốt chặn: /MIR xoá file ở đích, nên phải chắc chắn đúng thư mục ---
if (-not (Test-Path $Source)) { throw "Không thấy thư mục nguồn: $Source" }
foreach ($dau_hieu in @(".git", "README.md", "edge")) {
    if (-not (Test-Path (Join-Path $Source $dau_hieu))) {
        throw "'$Source' không giống thư mục MSB Radar (thiếu '$dau_hieu'). Dừng để tránh xoá nhầm."
    }
}
if ((Resolve-Path $Source).Path.TrimEnd('\') -ieq (Resolve-Path $Destination -ErrorAction SilentlyContinue).Path.TrimEnd('\')) {
    throw "Nguồn và đích trùng nhau."
}

$driveRoot = Split-Path -Qualifier $Destination
if (-not (Test-Path $driveRoot)) {
    throw "Không thấy ổ $driveRoot. Google Drive đã được gắn chưa?"
}
if (-not (Test-Path $Destination)) {
    Write-Host "Tạo thư mục đích: $Destination" -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
}

Write-Host ""
Write-Host "Nguồn : $Source"      -ForegroundColor Cyan
Write-Host "Đích  : $Destination" -ForegroundColor Cyan
if ($DryRun)   { Write-Host "Chế độ: XEM TRƯỚC, không ghi gì" -ForegroundColor Yellow }
if ($NoDelete) { Write-Host "Chế độ: giữ file thừa ở đích"    -ForegroundColor Yellow }
Write-Host ""

$robocopyArgs = @($Source, $Destination, "/E")
if (-not $NoDelete) { $robocopyArgs += "/PURGE" }   # /E + /PURGE = /MIR
if ($DryRun)        { $robocopyArgs += "/L" }
$robocopyArgs += @("/XD") + $excludeDirs
$robocopyArgs += @("/XF") + $excludeFiles
# /R:2 /W:2 — Google Drive hay giữ file trong chốc lát khi đang đồng bộ; thử lại
# vài lần là qua, nhưng đừng thử vô hạn (mặc định của robocopy là 1 triệu lần).
$robocopyArgs += @("/R:2", "/W:2", "/NP", "/NFL", "/NDL", "/TEE")

& robocopy @robocopyArgs
$code = $LASTEXITCODE

Write-Host ""
# Robocopy dùng bitmask: 0-7 là thành công, >=8 mới là lỗi thật.
if ($code -ge 8) {
    Write-Host "ĐỒNG BỘ THẤT BẠI (mã robocopy $code)" -ForegroundColor Red
    exit 1
}

if ($DryRun) {
    Write-Host "Xem trước xong. Bỏ -DryRun để thực hiện." -ForegroundColor Yellow
    exit 0
}

$mucTieu = @{
    0 = "Không có gì thay đổi"
    1 = "Đã sao chép file mới/đã sửa"
    2 = "Đã dọn file thừa ở đích"
    3 = "Đã sao chép và dọn dẹp"
}
$moTa = $mucTieu[$code]
if (-not $moTa) { $moTa = "Hoàn tất (mã $code)" }
Write-Host "ĐỒNG BỘ XONG — $moTa" -ForegroundColor Green

# Nhắc rõ điều dễ quên nhất: Drive cần thời gian đẩy lên mây sau khi ghi xong.
Write-Host "Lưu ý: Google Drive còn cần thêm ít phút để tải lên. Kiểm tra biểu tượng khay hệ thống trước khi tắt máy." -ForegroundColor DarkGray
exit 0
