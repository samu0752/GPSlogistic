#!/bin/sh
set -eu

cd "$(dirname "$0")"
python_bin=${GPS_PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
    "$python_bin" -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python -X utf8 manage.py init --generate-password
printf '%s\n' 'GPSlogistic: http://127.0.0.1:5050'
exec .venv/bin/python -X utf8 run.py "$@"
