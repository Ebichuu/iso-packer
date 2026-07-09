#!/bin/bash
# ISO Packer v2.1.0 - Docker 部署脚本

set -e

echo "ISO Packer v2.1.0 - Docker 部署"
echo "================================================"
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "[错误] Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 Docker Compose
if command -v docker-compose &> /dev/null; then
    COMPOSE="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE="docker compose"
else
    echo "[错误] Docker Compose 未安装，请先安装 docker-compose 或 Docker Compose 插件"
    exit 1
fi

# 进入当前 v2.x 工作目录
cd "$(dirname "$0")"

echo "[信息] 当前目录: $(pwd)"
echo ""

# 创建必要目录
echo "[信息] 创建数据目录..."
mkdir -p data test-watch test-output
echo "[完成] 目录创建完成"
echo ""

# 停止旧容器
echo "[信息] 停止旧容器（如果存在）..."
$COMPOSE down 2>/dev/null || true
echo ""

# 构建镜像
echo "[信息] 构建 Docker 镜像..."
$COMPOSE build --no-cache
echo "[完成] 镜像构建完成"
echo ""

# 启动容器
echo "[信息] 启动容器..."
$COMPOSE up -d
echo "[完成] 容器已启动"
echo ""

# 等待服务启动
echo "[信息] 等待服务启动..."
sleep 5

# 检查容器状态
if $COMPOSE ps | grep -q "Up"; then
    echo "[完成] 服务运行正常"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "部署成功"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "访问地址: http://localhost:15866"
    echo "容器状态: $COMPOSE ps"
    echo "查看日志: $COMPOSE logs -f"
    echo "停止服务: $COMPOSE down"
    echo ""
else
    echo "[错误] 服务启动失败，请查看日志："
    $COMPOSE logs --tail=50
    exit 1
fi
