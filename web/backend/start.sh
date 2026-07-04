#!/bin/bash
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
"../../.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 --reload --log-level info
