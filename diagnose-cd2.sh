#!/bin/bash
# CloudDrive2 挂载诊断脚本
# 用法: ./diagnose-cd2.sh

echo "=========================================="
echo "CloudDrive 挂载诊断"
echo "=========================================="
echo ""

echo "1. 检查 /CloudNAS 是否是挂载点："
if mountpoint -q /CloudNAS 2>/dev/null; then
    echo "   ✓ /CloudNAS 是挂载点"
    CLOUDNAS_IS_MOUNT=true
else
    echo "   ✗ /CloudNAS 不是挂载点"
    CLOUDNAS_IS_MOUNT=false
fi

echo ""
echo "2. 检查 /CloudNAS/CloudDrive 是否是挂载点："
if mountpoint -q /CloudNAS/CloudDrive 2>/dev/null; then
    echo "   ✓ /CloudNAS/CloudDrive 是挂载点"
    CLOUDDRIVE_IS_MOUNT=true
else
    echo "   ✗ /CloudNAS/CloudDrive 不是挂载点（普通目录）"
    CLOUDDRIVE_IS_MOUNT=false
fi

echo ""
echo "3. 查看挂载详情："
if command -v findmnt &> /dev/null; then
    findmnt /CloudNAS 2>/dev/null || echo "   未找到 /CloudNAS 的挂载信息"
else
    mount | grep CloudNAS || echo "   未找到 /CloudNAS 的挂载信息"
fi

echo ""
echo "4. 查看目录内容："
if [ -d /CloudNAS/CloudDrive ]; then
    ls -la /CloudNAS/CloudDrive/ 2>/dev/null | head -10
else
    echo "   ✗ 目录 /CloudNAS/CloudDrive 不存在"
fi

echo ""
echo "5. 测试 Docker 直接挂载："
docker run --rm -v /CloudNAS/CloudDrive:/test alpine sh -c "echo '   容器内目录列表:' && ls -la /test 2>/dev/null | head -10 || echo '   ✗ 无法访问'" 2>/dev/null

echo ""
echo "6. 测试 Docker rslave 挂载："
docker run --rm -v /CloudNAS/CloudDrive:/test:rslave alpine sh -c "echo '   容器内目录列表:' && ls -la /test 2>/dev/null | head -10 || echo '   ✗ 无法访问'" 2>/dev/null

echo ""
echo "=========================================="
echo "诊断结果总结"
echo "=========================================="
echo ""

# 分析结果并给出建议
if [ "$CLOUDDRIVE_IS_MOUNT" = false ]; then
    echo "【结论】"
    echo "  /CloudNAS/CloudDrive 不是挂载点，只是普通目录"
    echo ""
    echo "【建议】"
    echo "  使用普通挂载，移除 :rslave 参数"
    echo ""
    echo "【修复方法】"
    echo "  1. 备份配置："
    echo "     cp docker-compose.yml docker-compose.yml.backup"
    echo ""
    echo "  2. 使用修复配置："
    echo "     cp docker-compose.fix2.yml docker-compose.yml"
    echo ""
    echo "  3. 重启容器："
    echo "     docker-compose down && docker-compose up -d"
    echo ""
    echo "  4. 验证："
    echo "     docker exec -it iso-packer ls -la /cd2"

elif [ "$CLOUDNAS_IS_MOUNT" = true ] && [ "$CLOUDDRIVE_IS_MOUNT" = false ]; then
    echo "【结论】"
    echo "  /CloudNAS 是挂载点，但 /CloudNAS/CloudDrive 只是其中的子目录"
    echo ""
    echo "【建议】"
    echo "  方案 1: 直接挂载 /CloudNAS/CloudDrive（推荐）"
    echo "  方案 2: 挂载 /CloudNAS 并修改代码路径"
    echo ""
    echo "【修复方法 - 方案 1】"
    echo "  使用 docker-compose.fix2.yml（移除 rslave）"
    echo ""
    echo "【修复方法 - 方案 2】"
    echo "  修改 docker-compose.yml："
    echo "    - /CloudNAS:/CloudNAS:rslave"
    echo "  修改代码配置："
    echo "    cd2_mount_root: '/CloudNAS'"
    echo "    cd2_target_dir: '/CloudNAS/CloudDrive'"

else
    echo "【结论】"
    echo "  /CloudNAS/CloudDrive 是独立挂载点"
    echo ""
    echo "【建议】"
    echo "  使用 shared 传播模式"
    echo ""
    echo "【修复方法】"
    echo "  使用 docker-compose.fix1.yml"
fi

echo ""
echo "=========================================="
echo "完成"
echo "=========================================="
