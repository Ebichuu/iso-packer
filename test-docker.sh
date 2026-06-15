#!/bin/bash

# ISO Packer - Docker 镜像测试脚本
# 用于验证镜像是否正常构建和运行

set -e

echo "=========================================="
echo "ISO Packer - Docker 测试脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试函数
test_passed() {
    echo -e "${GREEN}✅ $1${NC}"
}

test_failed() {
    echo -e "${RED}❌ $1${NC}"
    exit 1
}

test_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 1. 检查 Docker 是否安装
echo ""
echo "1️⃣  检查 Docker 环境..."
if command -v docker &> /dev/null; then
    test_passed "Docker 已安装: $(docker --version)"
else
    test_failed "Docker 未安装，请先安装 Docker"
fi

# 2. 检查 Docker 是否运行
if docker info &> /dev/null; then
    test_passed "Docker 服务正在运行"
else
    test_failed "Docker 服务未运行，请启动 Docker"
fi

# 3. 检查必要文件
echo ""
echo "2️⃣  检查项目文件..."
required_files=(
    "Dockerfile"
    "docker-compose.yml"
    "iso-packer/app.py"
    "iso-packer/page.py"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        test_passed "文件存在: $file"
    else
        test_failed "文件缺失: $file"
    fi
done

# 4. 构建 Docker 镜像
echo ""
echo "3️⃣  构建 Docker 镜像..."
if docker build -t iso-packer:test . > /tmp/docker-build.log 2>&1; then
    test_passed "Docker 镜像构建成功"
else
    test_failed "Docker 镜像构建失败，详见: /tmp/docker-build.log"
fi

# 5. 检查镜像大小
echo ""
echo "4️⃣  检查镜像信息..."
IMAGE_SIZE=$(docker images iso-packer:test --format "{{.Size}}")
test_passed "镜像大小: $IMAGE_SIZE"

# 6. 创建测试目录
echo ""
echo "5️⃣  准备测试环境..."
TEST_DIR="/tmp/iso-packer-test"
rm -rf $TEST_DIR
mkdir -p $TEST_DIR/{data,watch,output,cd2}
test_passed "测试目录创建成功: $TEST_DIR"

# 7. 启动容器
echo ""
echo "6️⃣  启动测试容器..."
docker run -d \
    --name iso-packer-test \
    -p 15866:15865 \
    -v $TEST_DIR/data:/app \
    -v $TEST_DIR/watch:/watch \
    -v $TEST_DIR/output:/output \
    -v $TEST_DIR/cd2:/cd2 \
    -e TZ=Asia/Shanghai \
    iso-packer:test > /dev/null 2>&1

if [ $? -eq 0 ]; then
    test_passed "容器启动成功"
else
    test_failed "容器启动失败"
fi

# 8. 等待服务启动
echo ""
echo "7️⃣  等待服务就绪..."
sleep 5

# 9. 检查容器状态
if docker ps | grep -q iso-packer-test; then
    test_passed "容器正在运行"
else
    test_failed "容器未运行"
fi

# 10. 检查 Web 服务
echo ""
echo "8️⃣  测试 Web 服务..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:15866/ || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    test_passed "Web 服务响应正常 (HTTP $HTTP_CODE)"
else
    test_warning "Web 服务响应异常 (HTTP $HTTP_CODE)"
    echo "正在获取容器日志..."
    docker logs iso-packer-test | tail -20
fi

# 11. 检查日志
echo ""
echo "9️⃣  检查容器日志..."
if docker logs iso-packer-test 2>&1 | grep -q "Running on"; then
    test_passed "Flask 应用启动成功"
else
    test_warning "未检测到 Flask 启动日志"
fi

# 12. 检查文件创建
echo ""
echo "🔟 检查配置文件生成..."
sleep 2
if [ -f "$TEST_DIR/data/config.json" ]; then
    test_passed "配置文件已生成: config.json"
else
    test_warning "配置文件未生成"
fi

if [ -f "$TEST_DIR/data/state.json" ]; then
    test_passed "状态文件已生成: state.json"
else
    test_warning "状态文件未生成"
fi

# 13. 显示容器信息
echo ""
echo "=========================================="
echo "📊 容器信息"
echo "=========================================="
docker ps --filter "name=iso-packer-test" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 14. 显示日志摘要
echo ""
echo "=========================================="
echo "📝 最近日志 (最后 10 行)"
echo "=========================================="
docker logs iso-packer-test 2>&1 | tail -10

# 15. 提供访问信息
echo ""
echo "=========================================="
echo "🎉 测试完成！"
echo "=========================================="
echo ""
echo "访问测试环境:"
echo "  URL: http://localhost:15866"
echo ""
echo "测试目录:"
echo "  数据: $TEST_DIR/data"
echo "  监控: $TEST_DIR/watch"
echo "  输出: $TEST_DIR/output"
echo ""
echo "查看日志:"
echo "  docker logs -f iso-packer-test"
echo ""
echo "清理测试环境:"
echo "  docker stop iso-packer-test"
echo "  docker rm iso-packer-test"
echo "  docker rmi iso-packer:test"
echo "  rm -rf $TEST_DIR"
echo ""

# 16. 询问是否清理
read -p "是否立即清理测试环境? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "正在清理..."
    docker stop iso-packer-test > /dev/null 2>&1
    docker rm iso-packer-test > /dev/null 2>&1
    docker rmi iso-packer:test > /dev/null 2>&1
    rm -rf $TEST_DIR
    test_passed "清理完成"
else
    echo ""
    test_warning "测试容器保留，请手动清理"
fi

echo ""
