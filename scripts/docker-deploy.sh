#!/usr/bin/env bash
set -euo pipefail

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 Docker，请先在目标 Linux 服务器安装 Docker Engine 和 Compose 插件。" >&2
  exit 1
fi

if command -v nmcli >/dev/null 2>&1 && [ ! -f /etc/udev/rules.d/99-air780.rules ]; then
  echo "尚未安装 Air780 宿主机网络保护。请先运行 ./scripts/install-host-network-guard.sh。" >&2
  exit 1
fi

if [ ! -f .env.docker ]; then
  cp .env.docker.example .env.docker
  chmod 600 .env.docker
  echo "已创建 .env.docker。请先填写随机 API Token 和 Webhook Secret，再重新运行本脚本。" >&2
  exit 1
fi

if grep -q '请替换' .env.docker; then
  echo ".env.docker 中仍有示例密钥，请替换后再部署。" >&2
  exit 1
fi

docker compose build
docker compose up -d
docker compose ps
