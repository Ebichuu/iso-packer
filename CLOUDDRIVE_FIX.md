# CloudDrive 挂载问题修复指南

## 问题描述
容器内 `/cd2` 目录读取不到宿主机 `/CloudNAS/CloudDrive` 的文件

## 诊断步骤

### 1. 在 VPS 上测试基础访问
```bash
# 检查目录是否存在且有内容
ls -la /CloudNAS/CloudDrive/

# 检查是否是挂载点
mount | grep CloudDrive
findmnt /CloudNAS/CloudDrive

# 测试 Docker 能否访问
docker run --rm -v /CloudNAS/CloudDrive:/test:ro alpine ls -la /test
```

如果上面的 Docker 测试命令能看到文件，说明基础挂载没问题，只是 `rslave` 参数的问题。

### 2. 检查容器内情况
```bash
# 进入容器
docker exec -it iso-packer bash

# 查看挂载点
ls -la /cd2
mount | grep cd2

# 检查权限
id
```

## 修复方案

### 方案 1：使用 shared 传播（推荐） - docker-compose.fix1.yml
```yaml
volumes:
  - type: bind
    source: /CloudNAS/CloudDrive
    target: /cd2
    bind:
      propagation: shared
```

**优点**：
- 支持动态子挂载
- 容器能看到 CloudDrive 内部的新挂载

**适用场景**：CloudDrive 是一个 FUSE 挂载点，内部有多个子目录挂载

### 方案 2：简化为普通挂载（最简单） - docker-compose.fix2.yml
```yaml
volumes:
  - /CloudNAS/CloudDrive:/cd2
```

**优点**：
- 最简单，兼容性最好
- 没有复杂的传播模式

**缺点**：
- 容器启动后 CloudDrive 内的新挂载点不可见

**适用场景**：CloudDrive 是普通目录或已经完全挂载好

### 方案 3：直接挂载真实存储
如果 CloudDrive 是个符号链接或二次挂载，找到真实位置：

```bash
# 查找真实路径
df -h /CloudNAS/CloudDrive
readlink -f /CloudNAS/CloudDrive

# 假设真实路径是 /mnt/clouddrive-data
```

然后修改 docker-compose.yml：
```yaml
volumes:
  - /mnt/clouddrive-data:/cd2
```

## 测试步骤

### 1. 备份当前配置
```bash
cp docker-compose.yml docker-compose.yml.backup
```

### 2. 尝试修复方案 2（最简单）
```bash
cp docker-compose.fix2.yml docker-compose.yml
docker-compose down
docker-compose up -d
```

### 3. 验证
```bash
# 进入容器检查
docker exec -it iso-packer ls -la /cd2

# 查看日志
docker logs iso-packer

# 访问 Web 界面
# http://your-vps-host/
```

### 4. 如果方案 2 不行，尝试方案 1
```bash
cp docker-compose.fix1.yml docker-compose.yml
docker-compose down
docker-compose up -d
```

## 常见问题

### Q1: 容器内 /cd2 是空的
**原因**：权限问题或路径不存在
**解决**：
```bash
# 检查宿主机目录权限
ls -la /CloudNAS/
sudo chmod 755 /CloudNAS/CloudDrive

# 确保目录存在
ls -la /CloudNAS/CloudDrive/
```

### Q2: Permission denied
**原因**：SELinux 或 AppArmor 限制
**解决**：
```bash
# 临时禁用 SELinux
sudo setenforce 0

# 或添加 :z 标志
- /CloudNAS/CloudDrive:/cd2:z
```

### Q3: 能看到目录但是空的
**原因**：CloudDrive 尚未挂载或异步挂载
**解决**：
```bash
# 确保 CloudDrive 服务先启动
# 检查 CloudDrive 状态
systemctl status clouddrive  # 或对应服务名

# 在 docker-compose.yml 添加依赖（如果 CloudDrive 也是容器）
depends_on:
  - clouddrive
```

## 推荐操作流程

1. 先用测试命令确认宿主机目录可访问
2. 使用方案 2（最简单的普通挂载）
3. 如果需要动态挂载传播，再升级到方案 1
4. 在 VPS 上执行上述步骤并观察日志

## 联系支持
如果以上方案都不行，提供以下信息：
```bash
# 收集诊断信息
echo "=== 宿主机信息 ===" > diagnosis.txt
uname -a >> diagnosis.txt
docker version >> diagnosis.txt
echo -e "\n=== CloudDrive 挂载 ===" >> diagnosis.txt
mount | grep CloudDrive >> diagnosis.txt
echo -e "\n=== 目录内容 ===" >> diagnosis.txt
ls -la /CloudNAS/CloudDrive/ >> diagnosis.txt
echo -e "\n=== Docker 测试 ===" >> diagnosis.txt
docker run --rm -v /CloudNAS/CloudDrive:/test:ro alpine ls -la /test >> diagnosis.txt
cat diagnosis.txt
```
