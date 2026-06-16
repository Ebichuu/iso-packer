# 🐳 Docker Compose 部署指南

iso-packer 提供两种 Docker Compose 部署方式，根据您的需求选择：

---

## 方式 1: 使用 Docker Hub 镜像（推荐）⭐

**适合场景**：快速部署，无需构建，开箱即用

### 步骤 1: 创建 docker-compose.yml

在您的 VPS 上创建一个目录并创建配置文件：

```bash
mkdir ~/iso-packer && cd ~/iso-packer
nano docker-compose.yml
```

粘贴以下内容：

```yaml
version: '3.8'

services:
  iso-packer:
    image: ebichu/iso-packer:latest  # 直接使用 Docker Hub 镜像
    container_name: iso-packer
    restart: unless-stopped
    
    ports:
      - "15865:15865"
    
    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
    
    volumes:
      # 数据持久化（配置、状态、日志）
      - ./data:/app
      
      # 【必改】监控目录 - CD2 挂载的 115 网盘下载目录
      - /CloudNAS/username/PT下载:/watch
      
      # 【必改】临时输出目录 - ISO 封装临时存放
      - /tmp/iso-output:/output
      
      # 【必改】CD2 挂载根目录 - 用于转移文件
      # 重要：必须使用 :rslave 参数
      - /CloudNAS:/cd2:rslave
    
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 步骤 2: 修改路径配置

编辑上面的 `volumes` 部分，改为您的实际路径：

```yaml
volumes:
  - ./data:/app                          # 保持不变
  - /your/cd2/mount/path:/watch         # 改成您的 CD2 监控路径
  - /your/tmp/output:/output            # 改成您的临时输出路径
  - /your/cd2/root:/cd2:rslave          # 改成您的 CD2 根目录
```

### 步骤 3: 启动服务

```bash
docker-compose up -d
```

### 步骤 4: 查看日志

```bash
docker-compose logs -f
```

### 步骤 5: 访问 Web 界面

```
http://your-vps-ip:15865
```

---

## 方式 2: 从源码构建

**适合场景**：需要修改代码或离线部署

### 步骤 1: 克隆仓库

```bash
git clone https://github.com/Ebichuu/iso-packer.git
cd iso-packer
```

### 步骤 2: 修改 docker-compose.yml

打开 `docker-compose.yml`，确保使用 `build` 而不是 `image`：

```yaml
services:
  iso-packer:
    build: .                            # 从源码构建
    # image: ebichu/iso-packer:latest  # 注释掉这行
    container_name: iso-packer
    # ... 其他配置
```

修改 `volumes` 路径为您的实际路径。

### 步骤 3: 构建并启动

```bash
docker-compose up -d --build
```

### 步骤 4: 查看构建进度

```bash
docker-compose logs -f
```

---

## 📋 路径配置示例

### 示例 1: 标准配置

```yaml
volumes:
  - ./data:/app
  - /CloudNAS/username/PT下载:/watch
  - /tmp/iso-output:/output
  - /CloudNAS:/cd2:rslave
```

### 示例 2: 自定义路径

```yaml
volumes:
  - ./data:/app
  - /data/clouddrive/downloads:/watch
  - /data/iso-temp:/output
  - /data/clouddrive:/cd2:rslave
```

### 示例 3: 多个监控目录（不推荐，使用单个目录更好）

如果确实需要监控多个目录，需要修改代码或在 Web 界面配置时使用符号链接。

---

## 🔧 常用命令

### 启动服务
```bash
docker-compose up -d
```

### 停止服务
```bash
docker-compose down
```

### 重启服务
```bash
docker-compose restart
```

### 查看日志
```bash
docker-compose logs -f
```

### 查看状态
```bash
docker-compose ps
```

### 更新镜像（方式 1）
```bash
docker-compose pull
docker-compose up -d
```

### 重新构建（方式 2）
```bash
docker-compose up -d --build
```

### 进入容器
```bash
docker-compose exec iso-packer bash
```

### 查看容器资源使用
```bash
docker stats iso-packer
```

---

## ⚙️ 高级配置

### 修改端口

如果 15865 端口被占用，修改 `docker-compose.yml`：

```yaml
ports:
  - "8080:15865"  # 主机端口:容器端口
```

访问地址变为：`http://your-vps-ip:8080`

### 启用特权模式

某些 FUSE 挂载可能需要特权模式：

```yaml
services:
  iso-packer:
    privileged: true
    # ... 其他配置
```

### 自定义网络

```yaml
services:
  iso-packer:
    networks:
      - iso-packer-net

networks:
  iso-packer-net:
    driver: bridge
```

### 资源限制

```yaml
services:
  iso-packer:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

### 环境变量配置

```yaml
environment:
  - TZ=Asia/Shanghai
  - PYTHONUNBUFFERED=1
  - LOG_LEVEL=DEBUG  # 调试模式
```

---

## 🐛 故障排查

### 问题 1: 端口冲突

**错误信息**：`Bind for 0.0.0.0:15865 failed: port is already allocated`

**解决方法**：
```bash
# 查看占用端口的进程
sudo lsof -i :15865

# 修改 docker-compose.yml 使用其他端口
ports:
  - "8080:15865"
```

### 问题 2: 挂载点无法访问

**错误信息**：容器日志显示 `/watch` 或 `/cd2` 无法访问

**解决方法**：
```bash
# 检查挂载点是否存在
ls -la /CloudNAS

# 检查 CD2 是否正常挂载
mount | grep CloudNAS

# 确保目录权限正确
sudo chmod -R 755 /CloudNAS
```

### 问题 3: 容器无法启动

**解决方法**：
```bash
# 查看详细错误信息
docker-compose logs iso-packer

# 检查配置文件语法
docker-compose config

# 重新构建
docker-compose down
docker-compose up -d --build
```

### 问题 4: CD2 挂载传播问题

**错误信息**：容器内看不到 CD2 挂载的文件

**解决方法**：
确保使用 `:rslave` 参数：
```yaml
volumes:
  - /CloudNAS:/cd2:rslave  # :rslave 是必须的
```

---

## 📝 完整示例配置文件

### docker-compose.yml（生产环境）

```yaml
version: '3.8'

services:
  iso-packer:
    image: ebichu/iso-packer:latest
    container_name: iso-packer
    restart: unless-stopped
    
    ports:
      - "15865:15865"
    
    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
    
    volumes:
      - ./data:/app
      - /CloudNAS/username/PT下载:/watch
      - /tmp/iso-output:/output
      - /CloudNAS:/cd2:rslave
    
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:15865"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

---

## 🎯 最佳实践

### 1. 使用独立目录

```bash
mkdir -p ~/iso-packer
cd ~/iso-packer
# 将 docker-compose.yml 放在这里
```

### 2. 备份配置

```bash
# 定期备份数据目录
tar -czf iso-packer-backup-$(date +%Y%m%d).tar.gz data/
```

### 3. 监控日志大小

```bash
# 查看日志大小
docker inspect iso-packer --format='{{.LogPath}}' | xargs du -h
```

### 4. 设置开机自启

Docker Compose 的 `restart: unless-stopped` 已经实现了开机自启。

---

## 🎉 完成

现在您可以通过 Docker Compose 轻松部署 iso-packer 了！

- **使用镜像**：快速部署，开箱即用
- **从源码构建**：可自定义，适合开发

有任何问题查看日志：
```bash
docker-compose logs -f iso-packer
```
