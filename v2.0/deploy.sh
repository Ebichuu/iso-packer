#!/usr/bin/env bash
# 仅拉取 GitHub Actions 已发布镜像，并更新 ISO Packer 目标服务。
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
SERVICE=iso-packer-v2

if ! command -v docker >/dev/null 2>&1; then
    echo "[错误] Docker 未安装"
    exit 1
fi
if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "[错误] Docker Compose 未安装"
    exit 1
fi

echo "[信息] ISO Packer 镜像部署"
"${COMPOSE[@]}" config --quiet
mkdir -p data test-watch test-output
"${COMPOSE[@]}" pull "$SERVICE"
"${COMPOSE[@]}" up -d --no-deps --no-build "$SERVICE"

container_id=$("${COMPOSE[@]}" ps -q "$SERVICE")
if [[ -z "$container_id" ]]; then
    echo "[错误] 未找到目标服务容器"
    exit 1
fi

echo "[信息] 等待健康检查（最多 120 秒）..."
for ((attempt = 0; attempt < 24; attempt++)); do
    state=$(docker inspect --format '{{.State.Status}}' "$container_id")
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")
    if [[ "$state" == running && "$health" == healthy ]]; then
        echo "[完成] ISO Packer 健康检查通过：http://localhost:15866"
        echo "[信息] 查看日志：${COMPOSE[*]} logs -f $SERVICE"
        exit 0
    fi
    if [[ "$state" == exited || "$state" == dead || "$health" == unhealthy ]]; then
        break
    fi
    sleep 5
done

echo "[错误] 目标服务未通过健康检查，请查看日志："
"${COMPOSE[@]}" logs --tail=50 "$SERVICE"
exit 1
