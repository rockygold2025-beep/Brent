#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install -r requirements.txt -q
if [ ! -f .env ]; then
  cp .env.example .env
fi
echo ""
echo "Starting app..."
python app.py
