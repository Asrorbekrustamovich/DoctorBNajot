@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Doctor B Najot - Zaxira nusxa olish
echo ============================================

if not exist .venv (
    echo XATO: avval START.bat ni ishga tushiring.
    pause & exit /b 1
)
set VPY=.venv\Scripts\python.exe

%VPY% manage.py backup_db --keep 60
if errorlevel 1 (
    echo.
    echo XATO: zaxira olinmadi.
    pause & exit /b 1
)

echo.
echo Zaxiralar "backups" papkasida saqlanadi.
echo Tiklash uchun: RESTORE.bat
echo.
echo MASLAHAT: "backups" papkasini vaqti-vaqti bilan
echo tashqi diskka yoki bulutga nusxalab qo'ying!
pause
