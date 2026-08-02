@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Doctor B Najot - Zaxiradan TIKLASH
echo ============================================
echo.
echo DIQQAT: tiklash joriy ma'lumotlarni almashtiradi!
echo (Tiklashdan oldin avtomatik xavfsizlik zaxirasi olinadi)
echo.

if not exist .venv (
    echo XATO: avval START.bat ni ishga tushiring.
    pause & exit /b 1
)
set VPY=.venv\Scripts\python.exe

echo Mavjud zaxiralar:
echo --------------------------------------------
%VPY% manage.py restore_db --list
echo --------------------------------------------
echo.
set /p FNAME="Tiklanadigan zaxira fayl nomini kiriting (yoki bo'sh qoldiring - eng oxirgisi): "

if "%FNAME%"=="" (
    %VPY% manage.py restore_db --latest
) else (
    %VPY% manage.py restore_db --file "%FNAME%"
)

echo.
pause
