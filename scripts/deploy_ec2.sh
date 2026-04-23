#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/home/ubuntu/ReactAct}"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_SERVICE="${BACKEND_SERVICE:-reactact}"

cd "$ROOT_DIR"

DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"

# Deployment should mirror the remote branch exactly, even if the server
# checkout has local merge commits or other divergence from origin.
git fetch origin "$DEPLOY_BRANCH"
git checkout "$DEPLOY_BRANCH" >/dev/null 2>&1 || git checkout -B "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
git reset --hard "origin/$DEPLOY_BRANCH"

if [ -f ".env" ]; then
  set -a
  # Prefer a single project-level .env shared across services.
  . ./.env
  set +a
fi

NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # Ensure the frontend build runs on a Vite-compatible Node version.
  . "$NVM_DIR/nvm.sh"
  nvm install 20 >/dev/null
  nvm use 20 >/dev/null
fi

cd "$BACKEND_DIR"
if [ -f ".env" ]; then
  set -a
  # Fallback for older deployments still storing env in backend/.env.
  . ./.env
  set +a
fi

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
