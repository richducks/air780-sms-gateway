#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$script_dir/compose.yaml" ]; then
  project_dir="$script_dir"
else
  project_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
fi
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

container_name="air780-sms-gateway"
stamp=$(date +%Y%m%d-%H%M%S)
if docker inspect "$container_name" >/dev/null 2>&1; then
  echo "升级前备份 SQLite 数据库..."
  backup_path="/data/sms_gateway.db.pre-upgrade-$stamp"
  docker exec "$container_name" sh -c "if [ -f /data/sms_gateway.db ]; then cp -p /data/sms_gateway.db '$backup_path'; fi"
  echo "备份位置: $backup_path"
fi

docker compose pull "$service"
docker compose up -d --no-build --force-recreate "$service"

for _ in $(seq 1 30); do
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)
  case "$status" in
    healthy|running)
      echo "升级完成，容器状态: $status"
      docker compose ps
      echo "当前健康状态："
      curl -fsS http://127.0.0.1:8787/health || true
      echo
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
