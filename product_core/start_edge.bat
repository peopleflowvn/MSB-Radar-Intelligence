@echo off
chcp 65001 >nul
title Khoi dong MSB Radar Edge

echo ===================================================
echo       KHOI DONG MSB RADAR EDGE (CV COLLECTOR)
echo ===================================================
echo.

cd /d "%~dp0"

where python >nul 2>&1 || (
    echo [LOI] Khong tim thay Python trong PATH.
    pause
    exit /b 1
)

if not exist "edge\main.py" (
    echo [LOI] Khong tim thay thu muc edge hoac file edge\main.py.
    pause
    exit /b 1
)

echo [1/2] Kiem tra moi truong va thu vien Edge...
python -c "import webview" >nul 2>&1 || (
    echo [THONG BAO] Dang cai dat/kiem tra thu vien can thiet tu edge\requirements.txt...
    pip install -r edge\requirements.txt
)

echo [2/2] Dang khoi dong MSB Radar Edge (PyWebView Desktop App)...
start "MSB Radar Edge" cmd /k "cd /d %~dp0edge && python main.py"

echo.
echo ===================================================
echo Da gui lenh khoi dong MSB Radar Edge.
echo Cua so ung dung thu thap & quan ly CV se xuat hien.
echo ===================================================
echo.

timeout /t 3 >nul
exit /b 0
