#!/bin/sh
# Abre el programa directamente en el tutorial guiado (usa una base de datos de práctica: no toca la suya).
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
exec "$PY" main.py --tutorial
