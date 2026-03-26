@echo off
REM Chay web app - He thong Giam sat Giao thong
REM Mo trinh duyet: http://127.0.0.1:8000
REM Dang nhap mac dinh: admin / admin123

cd /d "%~dp0"
echo.
echo ========================================
echo   He thong Giam sat Giao thong
echo ========================================
echo.
echo Dang khoi dong server...
echo Sau khi chay xong, mo trinh duyet: http://127.0.0.1:8000
echo Dang nhap: admin / admin123
echo.
uvicorn product_web:app --reload --host 127.0.0.1 --port 8000
pause
