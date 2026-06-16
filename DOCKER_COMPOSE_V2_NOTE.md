# Docker Compose V2 命令更新说明

## ⚠️ 重要变更

Docker Compose V2 已经替代 V1，命令格式已更新：

### ❌ 旧命令（已过时）
```bash
docker-compose up -d
docker-compose down
docker-compose logs
docker-compose ps
```

### ✅ 新命令（推荐）
```bash
docker compose up -d
docker compose down
docker compose logs
docker compose ps
```

**关键区别**：连字符 `-` 变成了空格

## 📝 更新后的操作命令

### CloudDrive2 修复方案执行

**方案 3（推荐）：**
```bash
cd /root/iso-packer
cp docker-compose.yml docker-compose.yml.backup
cp docker-compose.fix3.yml docker-compose.yml
docker compose down
docker compose up -d
```

**方案 2（简单）：**
```bash
cd /root/iso-packer
cp docker-compose.yml docker-compose.yml.backup
cp docker-compose.fix2.yml docker-compose.yml
docker compose down
docker compose up -d
```

### 常用命令

```bash
# 启动服务
docker compose up -d

# 停止服务
docker compose down

# 查看日志
docker compose logs -f

# 查看运行状态
docker compose ps

# 重启服务
docker compose restart

# 查看配置
docker compose config

# 拉取镜像
docker compose pull
```

## 🔧 验证版本

```bash
# 检查 Docker Compose 版本
docker compose version

# 输出示例：
# Docker Compose version v2.x.x
```

## 📌 注意事项

1. **配置文件名不变**：仍然是 `docker-compose.yml`
2. **命令从连字符改为空格**：`docker-compose` → `docker compose`
3. **功能完全兼容**：V2 完全兼容 V1 的配置文件
4. **性能更好**：V2 是用 Go 重写的，比 V1 快很多

---
**更新日期**: 2026-06-16
