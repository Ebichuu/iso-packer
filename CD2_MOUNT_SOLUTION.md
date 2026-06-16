# CloudDrive2 挂载问题完整解决方案

## 📋 问题描述
容器内 `/cd2` 目录读取不到宿主机 `/CloudNAS/CloudDrive` 的文件

## 🔍 根本原因
`:rslave` 挂载传播模式只在**源目录是挂载点**时有效。如果 `/CloudNAS/CloudDrive` 只是普通目录，`:rslave` 参数会被忽略，导致挂载失败或内容为空。

## 📦 已准备的文件

| 文件名 | 用途 |
|--------|------|
| `diagnose-cd2.sh` | 诊断脚本，检测挂载点状态 |
| `docker-compose.fix1.yml` | 修复方案1：使用 `shared` 传播 |
| `docker-compose.fix2.yml` | 修复方案2：普通挂载（推荐先试） |
| `CLOUDDRIVE_FIX.md` | 详细的诊断和修复指南 |
| `CD2_MOUNT_SOLUTION.md` | 本文档 |

## 🚀 快速修复步骤

### 步骤 1: 上传文件到 VPS
```bash
# 在本地执行，将文件上传到 VPS
scp diagnose-cd2.sh docker-compose.fix*.yml root@your-vps-host:/root/iso-packer/
```

### 步骤 2: 运行诊断（在 VPS 上）
```bash
cd /root/iso-packer  # 或你的项目目录
chmod +x diagnose-cd2.sh
./diagnose-cd2.sh
```

### 步骤 3: 根据诊断结果修复

**诊断结果会告诉你使用哪个方案**

#### 如果提示使用方案 2（最常见）
```bash
# 备份现有配置
cp docker-compose.yml docker-compose.yml.backup

# 应用修复
cp docker-compose.fix2.yml docker-compose.yml

# 重启容器
docker-compose down
docker-compose up -d

# 验证
docker exec -it iso-packer ls -la /cd2
```

#### 如果提示使用方案 1
```bash
cp docker-compose.yml docker-compose.yml.backup
cp docker-compose.fix1.yml docker-compose.yml
docker-compose down
docker-compose up -d
docker exec -it iso-packer ls -la /cd2
```

### 步骤 4: 测试功能
```bash
# 查看容器日志
docker logs iso-packer --tail 50

# 访问 Web 界面
# http://your-vps-host/

# 测试 CD2 转移功能是否正常
```

## 🔧 两个修复方案的区别

### 方案 1 (docker-compose.fix1.yml)
```yaml
volumes:
  - type: bind
    source: /CloudNAS/CloudDrive
    target: /cd2
    bind:
      propagation: shared
```

**适用场景**：
- CloudDrive 是 FUSE 挂载点
- 内部有动态子挂载需要传播
- 需要看到 CD2 内部的实时挂载变化

### 方案 2 (docker-compose.fix2.yml) - 推荐
```yaml
volumes:
  - /CloudNAS/CloudDrive:/cd2
```

**适用场景**：
- CloudDrive 是普通目录
- CloudDrive 已经完全挂载，无动态子挂载
- **大多数情况下这个就够了**

## 📊 诊断脚本输出示例

### 情况 1: /CloudNAS/CloudDrive 不是挂载点
```
✗ /CloudNAS/CloudDrive 不是挂载点（普通目录）
→ 建议: 使用方案 2（普通挂载）
```

### 情况 2: /CloudNAS 是挂载点
```
✓ /CloudNAS 是挂载点
✗ /CloudNAS/CloudDrive 不是挂载点
→ 建议: 使用方案 2 或挂载 /CloudNAS
```

### 情况 3: /CloudNAS/CloudDrive 是挂载点
```
✓ /CloudNAS/CloudDrive 是挂载点
→ 建议: 使用方案 1（shared 传播）
```

## ❓ 常见问题

### Q1: 为什么不能直接用 :rslave？
**A**: `:rslave` 是挂载传播模式，不是普通挂载。它需要源目录本身是挂载点才有意义。如果源目录是普通目录，这个参数会被忽略或导致挂载失败。

### Q2: 方案 2 去掉 :rslave 后会丢失功能吗？
**A**: 不会。如果 CloudDrive 已经完全挂载好，容器能看到所有文件。只有在需要看到"挂载点内部的新挂载"时才需要传播模式。

### Q3: 两个方案都试过还是不行怎么办？
**A**: 可能是权限问题，运行：
```bash
# 检查目录权限
ls -la /CloudNAS/

# 修复权限
sudo chmod -R 755 /CloudNAS/CloudDrive

# 检查 SELinux（如果启用）
getenforce
sudo setenforce 0  # 临时禁用测试
```

### Q4: 能看到目录但是空的
**A**: 可能是 CloudDrive 服务启动顺序问题：
```bash
# 确保 CloudDrive 先启动
systemctl status clouddrive

# 或者在 docker-compose.yml 添加延迟启动
command: sh -c "sleep 10 && /app/start.sh"
```

## 🎯 参考：CloudDrive2 官方最佳实践

根据类似项目的经验：

1. **CD2 作为容器运行**（推荐）
   - CD2 容器使用 `:shared` 传播
   - 其他容器普通挂载即可

2. **CD2 在宿主机运行**（你的情况）
   - 普通挂载就足够
   - 不需要复杂的传播模式

3. **关键配置**
   - CD2 需要 `/dev/fuse` 和 `SYS_ADMIN` 权限
   - 其他容器只读访问 CD2 目录即可

## 📝 下一步

修复完成后：
1. 确认 http://your-vps-host/ 能正常访问
2. 测试 CD2 转移功能
3. 如果还有问题，提供诊断脚本的完整输出
4. 继续讨论 UI 改进

## 🔗 相关资源

- CloudDrive2 官方文档: https://www.clouddrive2.com/
- Docker 挂载传播: https://docs.docker.com/storage/bind-mounts/#configure-bind-propagation
- 本项目仓库: https://github.com/Ebichuu/iso-packer

---
**最后更新**: 2026-06-16
