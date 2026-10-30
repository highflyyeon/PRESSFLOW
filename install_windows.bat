@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   PRESSFLOW 설치 - 강원사회복지신문 통합 콘텐츠 자동화 플랫폼
echo ============================================================
echo.
set "PY="
py -3 -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto havepy
python -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto havepy

echo [안내] 이 컴퓨터에서 Python 3.10 이상을 찾지 못했습니다.
echo.
echo   1. https://www.python.org/downloads/ 에서 Python을 내려받아 설치하세요.
echo   2. 설치 첫 화면 아래의 "Add python.exe to PATH" 를 꼭 체크하세요.
echo   3. 설치가 끝나면 이 파일을 다시 더블클릭하세요.
echo.
where winget >nul 2>nul
if errorlevel 1 goto end
set /p ANS=지금 자동으로 설치해 볼까요? 예는 Y 아니오는 N 입력 후 엔터: 
if /i not "%ANS%"=="Y" goto end
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo Python 설치가 끝났다면 이 창을 닫고 install_windows 를 다시 실행하세요.
goto end

:havepy
echo [1/3] 프로그램 환경을 준비합니다...
%PY% -m venv venv
if errorlevel 1 goto fail
echo [2/3] 필요한 구성요소를 설치합니다. 인터넷이 필요하며 1~2분 걸립니다...
venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto fail
echo [3/3] 바탕화면 아이콘과 자동 시작을 등록합니다...
venv\Scripts\python.exe pressflow.py install
echo.
echo 설치가 끝났습니다. PRESSFLOW를 시작합니다.
start "" venv\Scripts\pythonw.exe pressflow.py run --open
echo 다음부터는 바탕화면의 PRESSFLOW 아이콘을 누르세요.
echo 컴퓨터를 켜면 자동으로 백그라운드에서 실행됩니다.
timeout /t 8 >nul
exit /b 0

:fail
echo.
echo [오류] 설치에 실패했습니다. 위의 빨간 글자나 영어 메시지를 사진으로 찍어 알려 주세요.
echo 인터넷 연결과 바이러스 백신, 스마트 앱 컨트롤 차단 여부도 확인해 보세요.

:end
echo.
pause
