#!/usr/bin/env bash
set -euo pipefail

# Corrected HTTP Keep-Alive benchmark server.
# Run from the directory containing http_echo.py.
cd "$(dirname "$0")"

exec waitress-serve \
  --host=0.0.0.0 \
  --port=8080 \
  http_echo:app
