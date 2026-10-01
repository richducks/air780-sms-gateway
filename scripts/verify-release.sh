#!/usr/bin/env bash
set -euo pipefail

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

echo "[1/4] Python unit tests"
python3 -m unittest discover -v

echo "[2/4] Frontend reproducible build"
(
  cd frontend
  npm ci
  npm run build
)

echo "[3/4] Docker Compose config"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  if [ -f .env.docker ]; then
    docker compose config -q
  else
    echo "跳过完整 compose 配置解析：当前仓库没有 .env.docker（生产机应存在）。"
  fi
else
  echo "跳过 compose 配置解析：当前环境没有 docker compose。"
fi

echo "[4/4] Shell syntax"
for script in scripts/*.sh; do
  bash -n "$script"
done

echo "基础发布验收通过。下一步应在连接 Air780 的主机执行 /health、设备上线和真实短信收发验收。"
