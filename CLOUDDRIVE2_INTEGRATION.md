# CloudDrive2 集成配置指南

## 正确的配置方案（已验证）

### CloudDrive2 容器配置

```yaml
services:
  cloudnas:
    container_name: clouddrive2
    image: cloudnas/clouddrive2-unstable:latest
    
    # 网络配置
    network_mode: host  # 使用 host 网络，避免端口映射问题
    pid: host           # 共享进程命名空间，FUSE 需要
    
    # 权限配置
    privileged: true
    devices:
      - /dev/fuse:/dev/fuse
    
    # 环境变量
    environment:
      - CLOUDDRIVE_HOME=/Config
      - ENABLE_RUN_AFTER_START=true
    
    # 挂载配置
    volumes:
      # 关键：使用 shared 传播，让其他容器能看到 CD2 的子挂载
      - /CloudNAS:/CloudNAS:shared
      
      # 配置目录
      - /root/clouddrive2:/Config
      
      # 可选：挂载整个根目录（灵活但权限高）
      - /:/host:rshared
    
    restart: always
```

**关键点**：
- ✅ `network_mode: host` - 避免端口映射问题
- ✅ `/CloudNAS:/CloudNAS:shared` - 创建挂载传播源
- ✅ `pid: host` - FUSE 文件系统需要

---

### iso-packer 容器配置

```yaml
services:
  iso-packer:
    container_name: iso-packer
    image: ebichu/iso-packer:latest
    
    # 网络配置
    network_mode: bridge
    ports:
      - "15865:15865"
    
    # 环境变量
    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
    
    # 挂载配置
    volumes:
      # 数据持久化
      - ./data:/data
      
      # 监控和输出目录
      - /mnt/115Download:/watch
      - /mnt/iso-output:/output
      
      # 关键：使用 rslave 接收 CD2 的挂载传播
      - /CloudNAS:/CloudNAS:rslave
    
    # 日志配置
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    
    restart: unless-stopped
```

**关键点**：
- ✅ `/CloudNAS:/CloudNAS:rslave` - 接收来自 CD2 的挂载传播
- ✅ 挂载父目录 `/CloudNAS`，不是子目录 `/CloudNAS/CloudDrive`

---

## 配置文件设置

iso-packer 的 `config.json` 需要相应调整：

```json
{
  "watch_dir": "/mnt/115Download",
  "output_dir": "/mnt/iso-output",
  "cd2_transfer_enabled": true,
  "cd2_mount_root": "/CloudNAS",
  "cd2_target_dir": "/CloudNAS/CloudDrive",
  "cd2_require_mount": true,
  "delete_source_after_success": true
}
```

**关键点**：
- ✅ `cd2_mount_root`: `/CloudNAS` - 挂载根目录
- ✅ `cd2_target_dir`: `/CloudNAS/CloudDrive` - CD2 实际目录

---

## 挂载传播原理

```
宿主机 /CloudNAS
    ↓ (shared 传播)
CD2 容器 /CloudNAS
    ↓ (CD2 在内部创建 FUSE 挂载)
CD2 容器 /CloudNAS/CloudDrive (动态挂载)
    ↓ (rslave 传播)
iso-packer 容器 /CloudNAS/CloudDrive (能看到)
```

**工作流程**：
1. CD2 容器用 `:shared` 挂载 `/CloudNAS`
2. CD2 在容器内创建 `/CloudNAS/CloudDrive` FUSE 挂载
3. iso-packer 用 `:rslave` 接收这个子挂载
4. iso-packer 能看到 `/CloudNAS/CloudDrive` 的所有文件

---

## 常见问题

### Q1: 为什么 iso-packer 要用 rslave？
**A**: 因为 CD2 使用 FUSE 动态挂载，`:rslave` 能接收这些动态挂载的传播。

### Q2: 为什么不直接挂载 /CloudNAS/CloudDrive？
**A**: 因为 `/CloudNAS/CloudDrive` 是 CD2 容器内部动态创建的挂载点，如果直接挂载子目录，`:rslave` 参数无效。必须挂载父目录。

### Q3: CD2 为什么需要 network_mode: host？
**A**: 避免端口映射问题，让 CD2 的 Web 界面（19798 端口）直接暴露在宿主机网络。

### Q4: CD2 为什么同时挂载 /CloudNAS 和 /:/host？
**A**: 
- `/CloudNAS:shared` - 用于挂载传播
- `/:/host:rshared` - 灵活访问宿主机任意路径（可选）

---

## 验证步骤

### 1. 检查 CD2 挂载
```bash
# 查看 CD2 容器挂载
docker exec -it clouddrive2 ls -la /CloudNAS/

# 检查 CloudDrive 挂载
docker exec -it clouddrive2 ls -la /CloudNAS/CloudDrive/
```

### 2. 检查 iso-packer 能否看到
```bash
# iso-packer 应该能看到相同的内容
docker exec -it iso-packer ls -la /CloudNAS/CloudDrive/
```

### 3. 测试 CD2 转移功能
- 访问 iso-packer Web 界面：http://your-vps-host/
- 完成一个 ISO 封装任务
- 检查是否能成功转移到 CD2

---

## 部署顺序

1. **先部署 CloudDrive2**
   ```bash
   docker compose up -d cloudnas
   ```

2. **等待 CD2 完全启动**（约 10-30 秒）
   ```bash
   docker logs clouddrive2 -f
   ```

3. **再部署 iso-packer**
   ```bash
   docker compose up -d iso-packer
   ```

**原因**：iso-packer 的 `:rslave` 需要 CD2 先创建 `:shared` 挂载。

---

## 参考

- **基于 Symedia 项目的最佳实践**
- **CloudDrive2 官方文档**: https://www.clouddrive2.com/
- **Docker 挂载传播**: https://docs.docker.com/storage/bind-mounts/#configure-bind-propagation

---

**状态**：✅ 已验证正常工作  
**更新日期**：2026-06-16
