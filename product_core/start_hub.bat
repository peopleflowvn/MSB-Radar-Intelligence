@echo off
chcp 65001 >nul
title Khoi dong Radar System Hub

echo ===================================================
echo       KHOI DONG HE THONG RADAR (LOCAL HUB)
echo ===================================================
echo.

cd /d "%~dp0"

where python >nul 2>&1 || (echo [LOI] Khong tim thay Python trong PATH. & exit /b 1)
where npm >nul 2>&1 || (echo [LOI] Khong tim thay npm trong PATH. & exit /b 1)
if not exist "web\node_modules" (echo [LOI] Chua cai frontend. Chay: cd web ^&^& npm install & exit /b 1)

echo [0/3] Kiem tra va cap nhat CSDL...
pushd server
python manage.py check || (popd & echo [LOI] Django check that bai. & exit /b 1)
python manage.py migrate --no-input || (popd & echo [LOI] Migration that bai. & exit /b 1)
popd

echo [1/3] Dang khoi dong Backend Server (Django API :8000)...
start "Radar Backend Server" cmd /k "cd /d %~dp0server && python manage.py runserver 127.0.0.1:8000"

timeout /t 2 >nul

echo [2/3] Dang khoi dong Frontend Hub (Vite UI :5173)...
start "Radar Frontend Web" cmd /k "cd /d %~dp0web && npm run dev"

timeout /t 3 >nul

echo.
echo ===================================================
echo [3/3] Da gui lenh khoi dong. Neu cua so Backend/Frontend bao loi, khong su dung he thong.
echo -> Frontend UI:   http://localhost:5173
echo -> Backend API:  http://127.0.0.1:8000/api/
echo -> Admin Portal: http://127.0.0.1:8000/admin/
echo ===================================================
echo.
echo Dang mo trinh duyet...
start http://localhost:5173

exit /b 0
