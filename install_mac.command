#!/bin/bash
cd "$(dirname "$0")"
echo "=== PRESSFLOW 설치 ==="
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
  read -p "엔터를 누르면 닫힙니다."; exit 1
fi
python3 -m venv venv || { echo "환경 생성 실패"; read -p "엔터"; exit 1; }
./venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || { echo "구성요소 설치 실패(인터넷 확인)"; read -p "엔터"; exit 1; }
./venv/bin/python pressflow.py install
./venv/bin/python pressflow.py run --open &
sleep 5
echo "설치 완료. 바탕화면의 PRESSFLOW.command 로 실행할 수 있고, 로그인하면 자동으로 백그라운드 실행됩니다."
