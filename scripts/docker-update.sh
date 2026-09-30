#!/usr/bin/env bash
set -euo pipefail

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

service="sms-gateway"
image="${AIR780_IMAGE:-ghcr.io/richducks/air780-sms-gateway:latest}"

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 Docker。请先安装 Docker Engine 和 Docker Compose 插件。" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "未找到 docker compose 插件。" >&2
  exit 1
fi

if [ ! -f .env.docker ]; then
  echo "缺少 .env.docker。首次部署请先复制 .env.docker.example 并填写配置。" >&2
  exit 1
fi

export AIR780_IMAGE="$image"

echo "准备升级 Air780 短信网关"
echo "镜像: $AIR780_IMAGE"
echo "数据卷 sms-data 不会被删除。"

docker compose pull "$service"
docker compose up -d --no-build "$service"

container_name="air780-sms-gateway"
for _ in $(seq 1 30); do
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)
  case "$status" in
    healthy|running)
      echo "升级完成，容器状态: $status"
      docker compose ps
      exit 0
      ;;
    unhealthy|exited|dead)
      echo "升级后容器状态异常: $status" >&2
      docker compose logs --tail=100 "$service" >&2 || true
      exit 1
      ;;
  esac
  sleep 2
done

echo "镜像已经更新，但健康检查在等待时间内未通过。当前状态：" >&2
docker compose ps >&2 || true
docker compose logs --tail=100 "$service" >&2 || true
exit 1
