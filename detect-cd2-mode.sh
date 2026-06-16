#!/bin/bash
# CloudDrive2 部署方式检测脚本

echo "=========================================="
echo "CloudDrive2 部署方式检测"
echo "=========================================="
echo ""

# 检查容器是否存在
if ! docker ps -a | grep -q clouddrive2; then
    echo "❌ 未找到 clouddrive2 容器"
    echo ""
    echo "请确认："
    echo "1. CloudDrive2 容器名称是否为 'clouddrive2'"
    echo "2. 或者使用命令查看所有容器："
    echo "   docker ps -a"
    exit 1
fi

echo "✓ 找到 clouddrive2 容器"
echo ""

# 检查挂载配置
echo "挂载配置："
echo "-------------------------------------------"
if command -v jq &> /dev/null; then
    docker inspect clouddrive2 --format '{{json .Mounts}}' | jq -r '.[] | "  \(.Source) -> \(.Destination) [\(.Mode)]"'
else
    docker inspect clouddrive2 --format '{{range .Mounts}}  {{.Source}} -> {{.Destination}} [{{.Mode}}]{{"\n"}}{{end}}'
fi
echo "-------------------------------------------"
echo ""

# 判断使用的方式
echo "判断结果："
echo ""

MOUNT_INFO=$(docker inspect clouddrive2 --format '{{json .Mounts}}')

if echo "$MOUNT_INFO" | grep -q '"Destination":"/host"'; then
    echo "✓ 使用【方式 2】（挂载根目录 /:/host）"
    echo ""
    echo "=========================================="
    echo "iso-packer 推荐配置"
    echo "=========================================="
    echo ""
    echo "docker-compose.yml:"
    echo "  volumes:"
    echo "    - /CloudNAS/CloudDrive:/cd2"
    echo ""
    echo "配置文件（保持默认）："
    echo "  cd2_mount_root: /mnt/cd2"
    echo "  cd2_target_dir: /mnt/cd2"
    echo ""
    echo "推荐使用：docker-compose.fix2.yml"

elif echo "$MOUNT_INFO" | grep -q '"Destination":"/CloudNAS"'; then
    echo "✓ 使用【方式 1】（挂载 CloudNAS 目录）"
    echo ""
    echo "=========================================="
    echo "iso-packer 推荐配置"
    echo "=========================================="
    echo ""
    echo "docker-compose.yml:"
    echo "  volumes:"
    echo "    - /CloudNAS:/CloudNAS:rslave"
    echo ""
    echo "配置文件（需要修改）："
    echo "  cd2_mount_root: /CloudNAS"
    echo "  cd2_target_dir: /CloudNAS/CloudDrive"
    echo ""
    echo "推荐使用：docker-compose.fix3.yml"

else
    echo "⚠️ 未识别的挂载配置"
    echo ""
    echo "请手动检查 CloudDrive2 的挂载配置："
    echo "  docker inspect clouddrive2"
fi

echo ""
echo "=========================================="
echo "完成"
echo "=========================================="
