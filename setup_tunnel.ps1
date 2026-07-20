Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " HƯỚNG DẪN TỰ ĐỘNG THIẾT LẬP CLOUDFLARE TUNNEL" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Tải cloudflared.exe nếu chưa có
$exePath = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $exePath)) {
    Write-Host "[1/4] Đang tải cloudflared.exe từ Github (vui lòng đợi)..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $exePath
    Write-Host "✓ Tải thành công cloudflared.exe!" -ForegroundColor Green
} else {
    Write-Host "✓ Đã tìm thấy cloudflared.exe." -ForegroundColor Green
}

# 2. Hướng dẫn đăng nhập
Write-Host ""
Write-Host "[2/4] BẮT ĐẦU ĐĂNG NHẬP CLOUDFLARE:" -ForegroundColor Yellow
Write-Host "Hệ thống chuẩn bị mở trình duyệt. Bạn hãy đăng nhập tài khoản Cloudflare" -ForegroundColor Gray
Write-Host "và chọn tên miền 'fuswater.online' để liên kết nhé." -ForegroundColor Gray
Write-Host "Nhấn phím bất kỳ để tiếp tục mở trang đăng nhập..." -ForegroundColor Cyan
$null = [Console]::ReadKey($true)

# Chạy lệnh login
Start-Process -FilePath $exePath -ArgumentList "tunnel login" -Wait

# 3. Tạo Tunnel mới
Write-Host ""
Write-Host "[3/4] Đang tạo đường hầm mới tên là 'web-monitor'..." -ForegroundColor Yellow
# Chạy tạo tunnel và bắt UUID
$tunnelOut = & $exePath tunnel create web-monitor
Write-Host $tunnelOut

# Tìm UUID trong output hoặc tìm file json trong thư mục .cloudflared
$userProfile = $env:USERPROFILE
$cloudflaredDir = Join-Path $userProfile ".cloudflared"
$jsonFiles = Get-ChildItem -Path $cloudflaredDir -Filter "*.json" | Where-Object { $_.Name -ne "cert.pem" }

if ($jsonFiles.Count -gt 0) {
    $uuid = $jsonFiles[0].BaseName
    Write-Host "✓ Đã tạo thành công Tunnel với UUID: $uuid" -ForegroundColor Green
    
    # Tạo file config.yml
    $configFile = Join-Path $cloudflaredDir "config.yml"
    $configContent = @"
tunnel: $uuid
credentials-file: $userProfile\.cloudflared\$uuid.json

ingress:
  - hostname: fuswater.online
    service: http://localhost:5000
  - hostname: www.fuswater.online
    service: http://localhost:5000
  - service: http_status:404
"@
    Set-Content -Path $configFile -Value $configContent
    Write-Host "✓ Đã tạo file cấu hình config.yml tại: $configFile" -ForegroundColor Green
    
    # 4. Tạo DNS routing
    Write-Host ""
    Write-Host "[4/4] Đang trỏ tên miền fuswater.online về đường hầm..." -ForegroundColor Yellow
    & $exePath tunnel route dns web-monitor fuswater.online
    & $exePath tunnel route dns web-monitor www.fuswater.online
    Write-Host "✓ Trỏ tên miền thành công!" -ForegroundColor Green
    
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host " THIẾT LẬP THÀNH CÔNG!" -ForegroundColor Green
    Write-Host "Bây giờ bạn chỉ cần chạy ứng dụng web của bạn ở cổng 5000," -ForegroundColor White
    Write-Host "và gõ lệnh sau để khởi chạy Tunnel:" -ForegroundColor White
    Write-Host "  .\cloudflared.exe tunnel run web-monitor" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Green
} else {
    Write-Host "✕ Lỗi: Không tìm thấy file thông tin Tunnel. Vui lòng đăng nhập lại." -ForegroundColor Red
}
