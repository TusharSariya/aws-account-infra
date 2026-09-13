#!/bin/sh
set -eu
mkdir -p /workspace/data /workspace/logs /workspace/cache /workspace/local /workspace/ssh
# setup is idempotent; bootstrap credentials are supplied only through Secrets.
python /app/setup.py
exec uvicorn app:app --host 0.0.0.0 --port 7000
