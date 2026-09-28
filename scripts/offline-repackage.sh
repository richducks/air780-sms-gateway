#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
if [ ! -f frontend/dist/index.html ]; then
  echo "缺少 frontend/dist；请先在可运行 Node.js 的机器上执行 npm run build。" >&2
  exit 1
fi
mkdir -p .offline-context/frontend
cp -a sms_gateway .offline-context/
cp -a frontend/dist .offline-context/frontend/
cp deploy/Dockerfile.offline-update .offline-context/Dockerfile
new_tag="air780-sms-gateway:offline-$(date +%Y%m%d%H%M%S)"
sudo docker build -t "$new_tag" .offline-context
sudo docker tag "$new_tag" air780-sms-gateway:local
sudo docker compose up -d --no-build
