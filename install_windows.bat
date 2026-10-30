@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo   PRESSFLOW 설치  -  강원사회복지신문 통합 콘텐츠 자동화 플랫폼
echo ============================================================
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo.
  echo [안내] Python 3.10 이상이 필요합니다. 지금 자동 설치를 시도합니다.
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python 설치가 끝났다면 이 창을 닫고 install_windows.bat 를 다시 실행해 주세요.
  echo 자동 설치가 안 되면 https://www.python.org/downloads/ 에서 설치하세요.
  echo (설치 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.)
  pause
  exit /b 1
)
echo.
echo [1/3] 프로그램 환경을 준비합니다...
%PY% -m venv venv
if errorlevel 1 ( echo 환경 생성에 실패했습니다. & pause & exit /b 1 )
echo [2/3] 필요한 구성요소를 설치합니다(인터넷 필요, 1~2분)...
venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ( echo 구성요소 설치에 실패했습니다. 인터넷 연결을 확인하세요. & pause & exit /b 1 )
echo [3/3] 바탕화면 아이콘과 자동 시작을 등록합니다...
venv\Scripts\python.exe pressflow.py install
echo.
echo 설치가 끝났습니다. PRESSFLOW를 시작합니다.
start "" venv\Scripts\pythonw.exe pressflow.py run --open
echo (이후에는 바탕화면의 PRESSFLOW 아이콘을 누르세요. 컴퓨터를 켜면 자동으로 백그라운드 실행됩니다.)
timeout /t 6 >nul
