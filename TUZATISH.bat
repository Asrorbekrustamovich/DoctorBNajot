@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Doctor B Najot - Bazani tuzatish
echo ============================================
echo.
echo Bu fayl bazadagi yetishmayotgan ustunlarni qo'shadi.
echo ("no such column" xatosini tuzatadi)
echo.

if not exist .venv (
    echo XATO: avval START.bat ni ishga tushiring.
    pause & exit /b 1
)
set VPY=.venv\Scripts\python.exe

echo [1/4] Zaxira nusxa olinmoqda (xavfsizlik uchun)...
%VPY% manage.py backup_db --keep 30

echo.
echo [2/4] Qo'llanmagan migratsiyalar tekshirilmoqda...
%VPY% manage.py showmigrations --plan | findstr /C:"[ ]"
if errorlevel 1 echo    (hammasi qo'llangan)

echo.
echo [3/4] Model o'zgarishlari uchun migratsiya yaratilmoqda...
%VPY% manage.py makemigrations --noinput

echo.
echo [4/4] Bazaga qo'llanmoqda...
%VPY% manage.py migrate --noinput
if errorlevel 1 (
    echo.
    echo XATO: migratsiya bajarilmadi.
    echo Sabab: server ishlab turgan bo'lishi mumkin.
    echo Yechim: server oynasini yoping ^(Ctrl+C^) va bu faylni qayta bosing.
    pause & exit /b 1
)

echo.
echo ============================================
echo   TAYYOR! Baza yangilandi.
echo   Endi START.bat ni ishga tushiring
echo   yoki brauzerda sahifani yangilang.
echo ============================================
pause
