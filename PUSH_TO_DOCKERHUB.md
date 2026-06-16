# 🚀 推送镜像到 Docker Hub 操作指南

## 前置条件

1. ✅ Docker Desktop 已安装并**正在运行**
2. ✅ 拥有 Docker Hub 账号：`ebichu`
3. ✅ 已生成 Access Token（从 https://hub.docker.com/settings/security 获取）

---

## 快速操作步骤

### 1️⃣ 启动 Docker Desktop

- 打开 Docker Desktop 应用
- 等待右下角状态变为 "Docker Desktop is running"
- 确认系统托盘图标显示正常

### 2️⃣ 登录 Docker Hub

打开 **PowerShell** 或 **命令提示符**，执行：

```bash
docker login
```

输入：
- **Username**: `ebichu`
- **Password**: 粘贴你的 Docker Hub Access Token

看到 `Login Succeeded` 表示登录成功。

### 3️⃣ 构建镜像

```bash
cd D:\Projects\makeiso

docker build -t ebichu/iso-packer:latest -t ebichu/iso-packer:v1.0.0 .
```

**预计耗时**：3-5 分钟（首次构建）

### 4️⃣ 推送到 Docker Hub

```bash
docker push ebichu/iso-packer:latest
docker push ebichu/iso-packer:v1.0.0
```

**预计耗时**：2-5 分钟（取决于网络速度）

### 5️⃣ 验证推送成功

访问：https://hub.docker.com/r/ebichu/iso-packer/tags

应该能看到：
- ✅ `latest` 标签
- ✅ `v1.0.0` 标签

---

## 🔧 一键执行脚本

我已经为你准备好了自动化脚本 `fix-docker-hub.bat`：

```bash
cd D:\Projects\makeiso
fix-docker-hub.bat
```

这个脚本会自动执行上述所有步骤（需要先手动启动 Docker Desktop）。

---

## ✅ 成功后的服务器操作

推送成功后，在**服务器**上执行：

```bash
cd ~/iso-packer

# 拉取最新镜像
docker compose pull

# 启动服务
docker compose up -d

# 查看日志
docker compose logs -f
```

---

## ❌ 常见问题

### Q1: 提示 "cannot connect to docker daemon"

**原因**：Docker Desktop 未启动

**解决**：
1. 打开 Docker Desktop
2. 等待完全启动（托盘图标正常）
3. 重新执行命令

### Q2: 提示 "denied: requested access to the resource is denied"

**原因**：未登录或登录凭据错误

**解决**：
```bash
# 重新登录
docker logout
docker login
# 输入正确的用户名和 Token
```

### Q3: 推送速度很慢

**原因**：网络问题

**解决**：
- 使用国内网络加速器
- 或者稍后重试
- 镜像大小约 200-300MB，根据网速需要几分钟

### Q4: 构建失败 "COPY failed"

**原因**：路径问题

**解决**：
```bash
# 确认目录结构
dir iso-packer\*.py

# 应该看到：
# iso-packer\app.py
# iso-packer\page.py
```

---

## 🎯 下一步

推送成功后，你可以：

1. **在任何服务器上一键部署**：
   ```bash
   docker run -d \
     --name iso-packer \
     -p 15865:15865 \
     -v ./data:/data \
     -v /watch:/watch \
     -v /output:/output \
     -v /CloudNAS:/cd2:rslave \
     ebichu/iso-packer:latest
   ```

2. **使用 docker-compose.yml 部署**：
   ```bash
   # docker-compose.yml 中确保使用
   image: ebichu/iso-packer:latest
   
   # 直接拉取并启动
   docker compose up -d
   ```

---

## 📊 预期结果

推送成功后：

- ✅ Docker Hub 页面显示镜像
- ✅ 服务器可以 `docker pull ebichu/iso-packer:latest`
- ✅ 其他用户也可以公开拉取（如果仓库是 public）

---

**准备好了就开始吧！** 🚀

有问题随时找我。
