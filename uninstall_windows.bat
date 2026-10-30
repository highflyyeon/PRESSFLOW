@echo off
chcp 65001 >nul
cd /d "%~dp0"
venv\Scripts\python.exe pressflow.py uninstall
echo.
echo 수집한 자료는 %USERPROFILE%\PRESSFLOW 폴더에 그대로 남아 있습니다.
pause
