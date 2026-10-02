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

service="sms-gateway"
image="${AIR780_IMAGE:-ghcr.io/richducks/air780-sms-gateway:latest}"
export AIR780_IMAGE="$image"

echo "准备部署 Air780 短信网关"
echo "镜像: $AIR780_IMAGE"
echo "数据卷 sms-data 将用于持久化短信和配置。"

docker compose pull "$service"
docker compose up -d --no-build "$service"

container_name="air780-sms-gateway"
for _ in $(seq 1 30); do
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)
  case "$status" in
    healthy|running)
      echo "部署完成，容器状态: $status"
      docker compose ps
      curl -fsS http://127.0.0.1:8787/health || true
      echo
      exit 0
      ;;
    unhealthy|exited|dead)
      echo "部署后容器状态异常: $status" >&2
      docker compose logs --tail=100 "$service" >&2 || true
      exit 1
      ;;
  esac
  sleep 2
done

echo "容器已启动，但健康检查在等待时间内未通过。" >&2
docker compose ps >&2 || true
docker compose logs --tail=100 "$service" >&2 || true
exit 1
