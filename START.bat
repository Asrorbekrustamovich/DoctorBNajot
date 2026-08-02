@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Doctor B Najot - ishga tushirilmoqda...
echo ============================================

REM 0) Mos Python versiyasini topish (3.10+ kerak)
set PYCMD=
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYCMD (
        py -%%V -c "print()" >nul 2>&1 && set PYCMD=py -%%V
    )
)
REM Python Install Manager (msix) o'rnatgan buyruqlar
for %%C in (python3.14 python3.13 python3.12 python3.11 python3.10) do (
    if not defined PYCMD (
        %%C -c "print()" >nul 2>&1 && set PYCMD=%%C
    )
)
if not defined PYCMD (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set PYCMD=python
)
if not defined PYCMD (
    py -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set PYCMD=py
)
REM Python Install Manager papkasidan to'g'ridan-to'g'ri qidirish (PATH shart emas)
if not defined PYCMD (
    for /d %%D in ("%LocalAppData%\Python\pythoncore-3.1*") do (
        if not defined PYCMD (
            if exist "%%D\python.exe" set "PYCMD=%%D\python.exe"
        )
    )
)
if not defined PYCMD (
    for %%C in (python3.14.exe python3.13.exe python3.12.exe) do (
        if not defined PYCMD (
            if exist "%LocalAppData%\Python\bin\%%C" set "PYCMD=%LocalAppData%\Python\bin\%%C"
        )
    )
)
REM Klassik o'rnatuvchi papkalari
if not defined PYCMD (
    for %%V in (314 313 312 311 310) do (
        if not defined PYCMD (
            if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" set "PYCMD=%LocalAppData%\Programs\Python\Python%%V\python.exe"
        )
    )
)
if not defined PYCMD (
    echo.
    echo XATO: Python 3.10+ topilmadi.
    echo Yechim 1: Python Install Manager o'rnatgan bo'lsangiz, terminalda:
    echo           python install 3.13
    echo Yechim 2: https://www.python.org/downloads/ dan Python 3.13 ni o'rnating
    echo           ^(o'rnatishda "Add python.exe to PATH" ni belgilang^)
    pause & exit /b 1
)
echo Python topildi: %PYCMD%

REM 1) Virtual muhit (eski/buzilgani bo'lsa qayta yaratiladi)
if exist .venv (
    .venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [1/5] Eski virtual muhit o'chirilmoqda...
        rmdir /s /q .venv
    )
)
if not exist .venv (
    echo [1/5] Virtual muhit yaratilmoqda...
    %PYCMD% -m venv .venv
    if errorlevel 1 ( echo XATO: venv yaratilmadi. & pause & exit /b 1 )
) else (
    echo [1/5] Virtual muhit mavjud.
)
set VPY=.venv\Scripts\python.exe

REM 2) Kutubxonalar
echo [2/5] pip yangilanmoqda va kutubxonalar o'rnatilmoqda...
%VPY% -m pip install --upgrade pip --quiet
%VPY% -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo XATO: kutubxonalar o'rnatilmadi. Internetni tekshiring.
    pause & exit /b 1
)

REM 3) Migratsiya
echo [3/5] Ma'lumotlar bazasi yangilanmoqda...
REM Model o'zgarishlari uchun migratsiya yaratish (fayl yetib kelmagan bo'lsa ham)
%VPY% manage.py makemigrations --noinput
%VPY% manage.py migrate --noinput
if errorlevel 1 ( pause & exit /b 1 )

REM 4) Rollar va admin
echo [4/5] Rollar va admin tayyorlanmoqda...
%VPY% manage.py seed_roles
%VPY% manage.py seed_admin
%VPY% manage.py seed_demo_users
%VPY% manage.py seed_operation_data
%VPY% manage.py seed_services

REM 4.5) Har ishga tushirishda avtomatik zaxira (xavfsizlik uchun)
echo [4/5] Zaxira nusxa olinmoqda...
%VPY% manage.py backup_db --keep 30

REM 5) Server
echo [5/5] Server ishga tushmoqda: http://127.0.0.1:8000
echo     Login: admin    Parol: Admin2026!
echo     To'xtatish: Ctrl+C
start "" http://127.0.0.1:8000
%VPY% manage.py runserver 127.0.0.1:8000
pause
