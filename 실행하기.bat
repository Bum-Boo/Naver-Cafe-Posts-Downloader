@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD=python"
where python >nul 2>nul
if errorlevel 1 set "PY_CMD=py"

:menu
cls
echo NAVER CAFE POST SAVER
echo.
echo 1. First install
echo 2. Save cafe post
echo 3. Manual HTML save
echo 4. Exit
echo.
set /p choice=Select number: 

if "%choice%"=="1" goto install
if "%choice%"=="2" goto save
if "%choice%"=="3" goto manual_html_save
if "%choice%"=="4" goto end

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

:save
cls
echo Paste URL only. The tool will use Naver cookies from your normal browser.
echo.
%PY_CMD% save_naver_cafe_post.py
pause
goto menu

:manual_html_save
cls
echo This backup mode opens the URL in your normal browser.
echo After the page opens, save it with Ctrl+S, then paste the saved HTML path.
echo.
%PY_CMD% save_naver_cafe_post.py --manual-html
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
