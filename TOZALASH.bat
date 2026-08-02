@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Doctor B Najot - Bemor malumotlarini
echo   BAZADAN TOZALASH
echo ============================================
echo.
echo O'CHIRILADI:
echo   - Bemorlar, tashriflar, navbat
echo   - Shifokor xulosalari, tayinlangan xizmatlar
echo   - Statsionar yotishlar, muolajalar, imzolar
echo   - Operatsiyalar, bayonnomalar, protokollar
echo   - Berilgan dorilar
echo   - Cheklar, to'lovlar, pul qaytarishlar
echo.
echo SAQLANADI:
echo   - Xodimlar va rollar
echo   - Xizmatlar katalogi va barcha narxlar
echo   - Palatalar, o'rinlar, operatsion xonalar
echo   - Operatsiya turlari, jarrohlik anjomlari
echo   - Dori katalogi va ombor qoldiqlari
echo   - Shifokor shablonlari
echo.
echo DIQQAT: qaytarib bo'lmaydi! (faqat zaxiradan tiklash mumkin)
echo Avtomatik zaxira olinadi.
echo.

if not exist .venv (
    echo XATO: avval START.bat ni ishga tushiring.
    pause & exit /b 1
)
set VPY=.venv\Scripts\python.exe

set /p JAVOB="Davom etilsinmi? (ha / yo'q): "
if /I not "%JAVOB%"=="ha" (
    echo Bekor qilindi.
    pause & exit /b 0
)

echo.
set /p STOCK="Berilgan dorilar ombor qoldig'iga qaytarilsinmi? (ha / yo'q): "
if /I "%STOCK%"=="ha" (
    %VPY% manage.py clear_patient_data --yes --restore-stock
) else (
    %VPY% manage.py clear_patient_data --yes
)

if errorlevel 1 (
    echo.
    echo XATO: tozalash bajarilmadi.
    echo Server ishlab turgan bo'lsa, oynasini yoping va qayta urinib ko'ring.
    pause & exit /b 1
)

echo.
echo ============================================
echo   TAYYOR. Baza bemorlardan tozalandi.
echo   Xato bo'lsa: RESTORE.bat orqali tiklang.
echo ============================================
pause
