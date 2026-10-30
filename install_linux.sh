#!/bin/bash
cd "$(dirname "$0")"
python3 -m venv venv && ./venv/bin/python -m pip install -q -r requirements.txt && ./venv/bin/python pressflow.py install && ./venv/bin/python pressflow.py run --open
