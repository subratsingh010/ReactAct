#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/ubuntu/ReactAct}"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_SERVICE="${BACKEND_SERVICE:-reactact}"

cd "$ROOT_DIR"

git pull origin "${DEPLOY_BRANCH:-main}"

cd "$BACKEND_DIR"
if [ -d "venv" ]; then
  source venv/bin/activate
else
  python3 -m venv venv
  source venv/bin/activate
fi

pip install --upgrade pip
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput

cd "$FRONTEND_DIR"
npm install
npm run build

sudo systemctl restart "$BACKEND_SERVICE"
sudo systemctl restart nginx
