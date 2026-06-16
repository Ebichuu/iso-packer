# 基于 Symedia 项目的 CloudDrive2 配置方案

## 🎯 关键发现

通过分析 Symedia 项目的配置，发现了问题的根源：

### Symedia 的做法
```yaml
# CloudDrive2 容器
clouddrive2:
  volumes:
    - /volume1/CloudNAS:/CloudNAS:shared  # CD2 用 shared

# Symedia 容器
symedia:
  volumes:
    - /volume1/CloudNAS:/CloudNAS:rslave  # 应用容器用 rslave
```

**关键点**：
1. 挂载的是**父目录** `/CloudNAS`，不是子目录
2. CD2 容器用 `:shared` 创建挂载点
3. 应用容器用 `:rslave` 接收传播
4. 代码中访问 `/CloudNAS/CloudDrive`

### 你当前的问题
```yaml
iso-packer:
  volumes:
    - /CloudNAS/CloudDrive:/cd2:rslave  # ❌ 错误
```

**问题**：
1. 挂载的是子目录，不是父目录
2. 如果你的 CD2 不是容器（是宿主机服务），没有上游 shared 可传播
3. `:rslave` 参数无效

## ✅ 三种修复方案对比

### 方案 1: shared 传播 (docker-compose.fix1.yml)
```yaml
volumes:
  - type: bind
    source: /CloudNAS/CloudDrive
    target: /cd2
    bind:
      propagation: shared
```
**适用**：CD2 是 FUSE 挂载点，内部有子挂载

### 方案 2: 普通挂载 (docker-compose.fix2.yml) ⭐ 最简单
```yaml
volumes:
  - /CloudNAS/CloudDrive:/cd2
```
**适用**：CD2 已完全挂载，不需要传播

### 方案 3: 模仿 Symedia (docker-compose.fix3.yml) ⭐ 推荐
```yaml
volumes:
  - /CloudNAS:/CloudNAS:rslave
```
**适用**：想完全按 Symedia 的方式配置

**需要同时修改配置**：
```json
{
  "cd2_mount_root": "/CloudNAS",
  "cd2_target_dir": "/CloudNAS/CloudDrive"
}
```

## 🚀 推荐方案：方案 3（模仿 Symedia）

### 为什么推荐方案 3？
1. ✅ 与 Symedia 项目一致，经过验证
2. ✅ 支持 CD2 的动态挂载
3. ✅ 挂载父目录，更灵活
4. ✅ 符合 CloudDrive2 的最佳实践

### 实施步骤

#### 步骤 1: 在 VPS 上应用配置
```bash
cd /root/iso-packer  # 或你的项目目录

# 备份
cp docker-compose.yml docker-compose.yml.backup

# 应用方案 3
cp docker-compose.fix3.yml docker-compose.yml

# 重启容器
docker-compose down
docker-compose up -d
```

#### 步骤 2: 修改配置文件
```bash
# 进入容器
docker exec -it iso-packer bash

# 编辑配置（或通过 Web 界面修改）
vi /data/config.json
```

修改为：
```json
{
  "watch_dir": "/root/iso-watch",
  "output_dir": "/root/iso-output",
  "cd2_transfer_enabled": true,
  "cd2_mount_root": "/CloudNAS",
  "cd2_target_dir": "/CloudNAS/CloudDrive",
  "cd2_require_mount": true
}
```

#### 步骤 3: 验证
```bash
# 检查挂载
docker exec -it iso-packer ls -la /CloudNAS/
docker exec -it iso-packer ls -la /CloudNAS/CloudDrive/

# 查看日志
docker logs iso-packer --tail 50

# 访问 Web 界面
# http://your-vps-host/
```

## 📊 方案对比表

| 特性 | 方案 2 (简单) | 方案 3 (Symedia) |
|------|--------------|------------------|
| 配置复杂度 | ⭐ 简单 | ⭐⭐ 中等 |
| 需要修改代码配置 | ❌ 否 | ✅ 是 |
| 支持动态挂载 | ❌ 否 | ✅ 是 |
| 与 Symedia 一致 | ❌ 否 | ✅ 是 |
| 稳定性 | ⭐⭐⭐ 高 | ⭐⭐⭐ 高 |
| 推荐度 | 快速修复 | 长期使用 |

## 🔍 如何选择？

### 选择方案 2（简单）如果：
- ✅ 你只想快速解决问题
- ✅ 不需要动态挂载功能
- ✅ CD2 是普通目录或已完全挂载

### 选择方案 3（Symedia）如果：
- ✅ 你想采用社区验证的方案
- ✅ 需要支持 CD2 的动态挂载
- ✅ 想保持与其他项目一致
- ✅ 不介意多改一个配置文件

## 📝 配置文件说明

使用方案 3 时，配置参数的含义：

```json
{
  // CD2 在容器内的挂载根目录
  "cd2_mount_root": "/CloudNAS",
  
  // CD2 实际存储文件的目录
  "cd2_target_dir": "/CloudNAS/CloudDrive",
  
  // 是否检查挂载点（建议保持 true）
  "cd2_require_mount": true
}
```

**重要**：`cd2_mount_root` 和 `cd2_target_dir` 的路径必须与 docker-compose.yml 中的挂载路径一致！

## ⚠️ 注意事项

1. **路径一致性**
   - docker-compose.yml 挂载 `/CloudNAS`
   - 配置文件也必须使用 `/CloudNAS` 路径
   - 不能混用 `/cd2` 和 `/CloudNAS`

2. **挂载传播模式**
   - `:rslave` 用于接收传播（只读传播）
   - `:rshared` 用于双向传播（飞牛系统）
   - 如果你用飞牛系统，改为 `rshared`

3. **配置修改**
   - 修改 docker-compose.yml 后必须重启容器
   - 修改 config.json 后刷新页面即可

## 🎉 完成后

- ✅ 容器能看到 /CloudNAS/CloudDrive 的所有文件
- ✅ Web 界面能正常访问
- ✅ CD2 转移功能正常工作
- ✅ 配置与 Symedia 项目一致

---
**基于**: Symedia Wiki (https://wiki.viplee.cc/symedia/newbie/install/)  
**更新**: 2026-06-16
