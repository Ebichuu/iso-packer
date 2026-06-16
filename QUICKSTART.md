# 🚀 快速启动指南

## 方式一：使用 Docker Hub 镜像（最简单）

### 步骤 1: 创建目录结构

```bash
mkdir -p ~/iso-packer/{data,watch,output}
cd ~/iso-packer
```

### 步骤 2: 下载 docker-compose.yml

```bash
wget https://raw.githubusercontent.com/Ebichuu/iso-packer/main/docker-compose.yml
```

或手动创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  iso-packer:
    image: ebichu/iso-packer:latest  # 替换为实际镜像
    container_name: iso-packer
    restart: unless-stopped
    ports:
      - "15865:15865"
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - ./data:/data
      - /CloudNAS/username/PT下载:/watch            # 修改为实际路径
      - /tmp/iso-output:/output                     # 修改为实际路径
      - /CloudNAS:/cd2:rslave                       # 修改为实际路径
```

### 步骤 3: 启动服务

```bash
docker-compose up -d
```

### 步骤 4: 访问 Web 界面

```
http://your-vps-ip:15865
```

---

## 方式二：从源码构建

### 步骤 1: 克隆仓库

```bash
git clone https://github.com/Ebichuu/iso-packer.git
cd iso-packer
```

### 步骤 2: 修改 docker-compose.yml

编辑 `docker-compose.yml`，修改 volumes 路径：

```yaml
volumes:
  - ./data:/data
  - /your/actual/watch/path:/watch      # 改成实际路径
  - /your/actual/output/path:/output    # 改成实际路径
  - /your/actual/cd2/path:/cd2:rslave   # 改成实际路径
```

### 步骤 3: 构建并启动

```bash
docker-compose up -d --build
```

---

## 方式三：一键命令（Docker Run）

```bash
docker run -d \
  --name iso-packer \
  --restart unless-stopped \
  -p 15865:15865 \
  -v $(pwd)/data:/data \
  -v /CloudNAS/username/PT下载:/watch \
  -v /tmp/iso-output:/output \
  -v /CloudNAS:/cd2:rslave \
  -e TZ=Asia/Shanghai \
  ebichu/iso-packer:latest
```

---

## 首次配置

1. 访问 `http://your-vps-ip:15865`

2. 在侧边栏填写配置：

   ```
   监控目录: /watch
   输出目录: /output
   扫描间隔: 60 秒
   稳定时间: 300 秒
   最小空间: 50 GB
   
   ☑ 启用监控
   ☑ 启用 CD2 转移
   
   CD2 挂载根目录: /cd2
   CD2 目标目录: /cd2/username/ISO备份
   ```

3. 点击 **保存设置**

4. 点击 **保存并扫描** 开始监控

---

## 常用命令

### 查看日志

```bash
docker logs -f iso-packer
```

### 重启服务

```bash
docker-compose restart
```

### 停止服务

```bash
docker-compose down
```

### 更新镜像

```bash
docker-compose pull
docker-compose up -d
```

### 进入容器

```bash
docker exec -it iso-packer bash
```

---

## 故障排查

### 问题 1: 端口被占用

```bash
# 修改 docker-compose.yml 中的端口
ports:
  - "8080:15865"  # 改为 8080 或其他可用端口
```

### 问题 2: CD2 挂载点无法访问

```bash
# 确认挂载点存在
mount | grep cd2

# 确认容器能访问
docker exec -it iso-packer ls -la /cd2
```

### 问题 3: 权限问题

```bash
# 修改目录权限
sudo chmod -R 755 /CloudNAS
sudo chown -R 1000:1000 ./data
```

---

## 最佳实践路径配置

### VPS 上的推荐配置：

```bash
# CD2 挂载点
/CloudNAS/
├── username/
│   ├── PT下载/              ← 监控目录 (只读)
│   └── VPS_Transfer/
│       └── ISO备份/         ← CD2 目标目录 (只写)

# 本地临时目录
/tmp/iso-output/            ← ISO 临时输出
```

### docker-compose.yml 对应配置：

```yaml
volumes:
  - /CloudNAS/username/PT下载:/watch
  - /tmp/iso-output:/output
  - /CloudNAS:/cd2:rslave
```

### Web 界面配置：

```
监控目录: /watch
输出目录: /output
CD2 挂载根目录: /cd2
CD2 目标目录: /cd2/username/VPS_Transfer/ISO备份
```

---

## 验证部署

1. **检查服务状态**
   ```bash
   docker ps | grep iso-packer
   ```

2. **查看日志**
   ```bash
   docker logs iso-packer | tail -20
   ```

3. **访问 Web 界面**
   - 浏览器打开 `http://your-vps-ip:15865`
   - 应该看到控制台界面

4. **测试监控**
   - 在监控目录放一个测试蓝光文件夹
   - 观察 Web 界面是否出现任务

---

## 生产环境检查清单

- [ ] CD2 已正确挂载并可访问
- [ ] VPS 有足够磁盘空间（至少 100GB）
- [ ] 防火墙已开放 15865 端口
- [ ] Docker 容器设置为自动重启
- [ ] 已配置监控和告警
- [ ] 已备份 `data/` 目录

---

搞定！现在你有一个开箱即用的蓝光 ISO 自动封装系统了 🎉
