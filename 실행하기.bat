@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD=python"
where python >nul 2>nul
if errorlevel 1 set "PY_CMD=py"

:menu
cls
echo NAVER CAFE ARCHIVE MANAGER
echo.
echo 1. First install
echo 2. Open archive app
echo 3. Exit
echo.
set /p choice=Select number: 

if "%choice%"=="1" goto install
if "%choice%"=="2" goto open_app
if "%choice%"=="3" goto end

echo.
echo Invalid choice.
pause
goto menu

:install
cls
echo Installing Python packages...
%PY_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto command_failed
echo.
echo Installing Playwright Chromium...
%PY_CMD% -m playwright install chromium
if errorlevel 1 goto command_failed
echo.
echo Install complete.
pause
goto menu

:open_app
cls
echo Opening archive app...
echo.
%PY_CMD% app.py
pause
goto menu

:command_failed
echo.
echo Command failed.
echo Please check Python installation or internet connection.
pause
goto menu

:end
exit /b 0
