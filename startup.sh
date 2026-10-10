#!/usr/bin/env bash

set -e

exec python -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1