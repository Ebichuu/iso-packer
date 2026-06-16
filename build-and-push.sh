#!/bin/bash
set -e

# ISO Packer - 构建并推送 Docker 镜像到 Docker Hub
# 使用方法: ./build-and-push.sh [版本号] [Docker Hub 用户名]

VERSION=${1:-"latest"}
DOCKERHUB_USER=${2:-"ebichu"}
IMAGE_NAME="iso-packer"
FULL_IMAGE="${DOCKERHUB_USER}/${IMAGE_NAME}:${VERSION}"

echo "=========================================="
echo "ISO Packer - Docker 构建脚本"
echo "=========================================="
echo "镜像名称: ${FULL_IMAGE}"
echo "=========================================="

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
    echo "❌ 错误: Docker 未运行，请先启动 Docker"
    exit 1
fi

# 构建镜像
echo ""
echo "📦 正在构建 Docker 镜像..."
docker build -t ${FULL_IMAGE} .

# 同时标记为 latest（如果不是 latest 版本）
if [ "${VERSION}" != "latest" ]; then
    echo ""
    echo "🏷️  标记为 latest..."
    docker tag ${FULL_IMAGE} ${DOCKERHUB_USER}/${IMAGE_NAME}:latest
fi

echo ""
echo "✅ 镜像构建完成！"
echo ""
echo "镜像信息:"
docker images | grep ${IMAGE_NAME}

# 询问是否推送到 Docker Hub
echo ""
read -p "是否推送到 Docker Hub? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 正在推送到 Docker Hub..."

    # 检查是否已登录
    if ! docker info | grep -q "Username"; then
        echo "请先登录 Docker Hub:"
        docker login
    fi

    # 推送镜像
    docker push ${FULL_IMAGE}

    # 推送 latest 标签
    if [ "${VERSION}" != "latest" ]; then
        docker push ${DOCKERHUB_USER}/${IMAGE_NAME}:latest
    fi

    echo ""
    echo "✅ 推送完成！"
    echo ""
    echo "现在可以通过以下命令拉取镜像:"
    echo "  docker pull ${FULL_IMAGE}"
else
    echo ""
    echo "⏭️  跳过推送"
fi

echo ""
echo "=========================================="
echo "🎉 完成！"
echo "=========================================="
echo ""
echo "本地测试运行:"
echo "  docker run -d -p 15865:15865 \\"
echo "    -v ./data:/app \\"
echo "    -v /path/to/watch:/watch \\"
echo "    -v /path/to/output:/output \\"
echo "    -v /mnt/cd2:/cd2:rslave \\"
echo "    ${FULL_IMAGE}"
echo ""
