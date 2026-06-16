# ISO Packer

[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

蓝光原盘自动封装与 CloudDrive2 转存工具 - 轻量级单机版

## 🎯 核心功能

- 🔍 **自动监控**：实时监控指定目录，自动识别蓝光原盘结构（BDMV/VIDEO_TS）
- 📦 **ISO 封装**：使用 genisoimage 进行 UDF + ISO Level 3 封装，完美支持 4K UHD 双层蓝光
- ✅ **ISO 验证**：封装完成后自动使用 xorriso 验证完整性
- ☁️ **CD2 转移**：自动转移 ISO 到 CloudDrive2 挂载点，带进度监控和大小校验
- 📊 **Web 管理**：实时刷新的 Web 控制台，可视化进度和日志
- 🗑️ **智能清理**：可选的源文件自动删除功能
- 📝 **日志管理**：7 天自动清理的日志系统

## 🎬 适用场景

**完美适配以下工作流**：

```
本地 qBittorrent (PT RSS)
         ↓ 下载完成
    115 网盘
         ↓ CD2 拉取到 VPS
    VPS 监控目录
         ↓ iso-packer 自动封装
    临时 ISO 目录
         ↓ CD2 自动转移
    115 网盘备份目录
```

## 🚀 快速部署

### 方式一：Docker Compose + Docker Hub 镜像（最简单）⭐

1. **下载 docker-compose.yml**

```bash
mkdir ~/iso-packer && cd ~/iso-packer
wget https://raw.githubusercontent.com/Ebichuu/iso-packer/main/docker-compose.yml
```

或手动创建 `docker-compose.yml`：

```yaml
version: '3.8'
services:
  iso-packer:
    image: ebichu/iso-packer:latest  # 使用 Docker Hub 镜像
    container_name: iso-packer
    restart: unless-stopped
    ports:
      - "15865:15865"
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - ./data:/app
      - /CloudNAS/username/PT下载:/watch           # 修改为实际路径
      - /tmp/iso-output:/output                    # 修改为实际路径
      - /CloudNAS:/cd2:rslave                      # 修改为实际路径
```

2. **启动服务**

```bash
docker-compose up -d
```

3. **访问 Web 界面**

```
http://your-vps-ip:15865
```

### 方式二：Docker Compose + 源码构建

1. **克隆仓库**

```bash
git clone https://github.com/Ebichuu/iso-packer.git
cd iso-packer
```

2. **编辑 docker-compose.yml**

将 `image: ebichu/iso-packer:latest` 改为 `build: .`

3. **构建并启动**

```bash
docker-compose up -d --build
```

### 方式三：Docker Run

```bash
docker run -d \
  --name iso-packer \
  --restart unless-stopped \
  -p 15865:15865 \
  -v ./data:/app \
  -v /CloudNAS/username/PT下载:/watch \
  -v /tmp/iso-output:/output \
  -v /CloudNAS:/cd2:rslave \
  -e TZ=Asia/Shanghai \
  ebichu/iso-packer:latest
```

### 方式四：本地运行

```bash
# 安装系统依赖
sudo apt update
sudo apt install -y genisoimage xorriso python3 python3-pip

# 安装 Python 依赖
pip3 install flask

# 运行
cd iso-packer
python3 app.py
```

## ⚙️ 配置说明

首次启动后，访问 Web 界面进行配置：

### 基础配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| 监控目录 | CD2 挂载的源目录 | `/watch` 或 `/CloudNAS/username/PT下载` |
| 输出目录 | ISO 临时存放目录 | `/output` 或 `/tmp/iso-output` |
| 扫描间隔 | 扫描频率（秒） | `60`（建议 30-120） |
| 稳定时间 | 文件稳定后才封装（秒） | `300`（建议 180-600） |
| 最小空间 | 预留磁盘空间（GB） | `50`（建议 50-100） |

### CD2 转移配置

| 配置项 | 说明 | 示例 |
|--------|------|------|
| 启用 CD2 转移 | 封装后自动转移到 CD2 | ✅ 勾选 |
| CD2 挂载根目录 | CloudDrive2 FUSE 挂载点 | `/cd2` 或 `/CloudNAS` |
| CD2 目标目录 | 最终存储路径 | `/cd2/username/ISO备份` |

### 高级配置

- **成功后删除源**：封装并转移成功后，是否删除监控目录中的源文件
  - ⚠️ 慎用：网盘上的文件会被删除
  - 建议：关闭此选项，手动清理

## 📁 目录结构

```
iso-packer/
├── app.py                # 主程序
├── page.py               # Web 界面模板
├── config.json           # 配置文件（自动生成）
├── state.json            # 任务状态（自动生成）
├── iso-packer.log        # 日志文件（自动生成）
├── Dockerfile            # Docker 镜像构建
├── docker-compose.yml    # Docker Compose 配置
└── README.md             # 本文档
```

## 🎯 工作原理

### 1. 蓝光原盘识别

自动识别以下结构：

```
蓝光电影/
├── BDMV/                    ✅ 识别为蓝光原盘
│   ├── BACKUP/
│   ├── BDJO/
│   ├── CLIPINF/
│   ├── JAR/
│   ├── META/
│   ├── PLAYLIST/
│   └── STREAM/
└── CERTIFICATE/
```

或：

```
DVD电影/
├── VIDEO_TS/                ✅ 识别为 DVD 原盘
│   ├── VIDEO_TS.IFO
│   ├── VTS_01_0.IFO
│   └── *.VOB
```

### 2. 封装流程

```
监控扫描 → 文件稳定检测 → 空间检查 → ISO 封装 → ISO 验证 → CD2 转移
```

- **文件稳定检测**：确保文件大小不再变化（避免封装未完成的下载）
- **空间检查**：确保有足够空间存放 ISO
- **ISO 封装**：使用 `genisoimage -udf -iso-level 3` 支持大文件
- **ISO 验证**：使用 `xorriso` 验证 ISO 完整性
- **CD2 转移**：分块读写，实时进度，完成后校验文件大小

### 3. 跳过封装的情况

以下情况会跳过 ISO 封装：

- ❌ 单个视频文件（.mkv, .mp4 等）
- ❌ 普通文件夹（无蓝光/DVD 结构）
- ❌ 部分下载文件（.part, .tmp 等）

## 🔧 常见问题

### Q1: CD2 挂载点无法识别？

**A:** 确保 Docker 容器能访问 FUSE 挂载点：

```yaml
volumes:
  - /CloudNAS:/cd2:rslave  # 必须添加 :rslave 参数
```

### Q2: 封装后网盘没有文件？

**A:** 这是正常现象。文件已移入 CD2 的本地缓存，CD2 会在后台慢慢上传到网盘。

检查 CD2 上传进度：
```bash
# 查看 CD2 日志
docker logs clouddrive

# 或查看 CD2 Web 管理界面的上传队列
```

### Q3: VPS 磁盘空间不足？

**A:** 建议配置：

1. **临时目录使用大容量磁盘**：
   ```bash
   df -h  # 查看磁盘空间
   # 将 /output 映射到空间充足的分区
   ```

2. **启用 CD2 转移**：封装完成后立即转移到网盘，释放本地空间

3. **定期清理**：转移成功后，临时 ISO 会自动删除

### Q4: 如何查看详细日志？

```bash
# Docker 日志
docker logs -f iso-packer

# 或登录容器查看
docker exec -it iso-packer tail -f /app/iso-packer.log
```

### Q5: 支持哪些蓝光规格？

✅ 支持所有蓝光规格：

- BD-25 (单层 25GB)
- BD-50 (双层 50GB)
- BD-66 (双层 66GB)
- BD-100 (三层 100GB)
- 4K UHD 蓝光
- 杜比视界 / HDR10+ / Dolby Atmos

⚠️ 文件系统限制：
- FAT32：❌ 不支持超过 4GB 的文件
- NTFS/exFAT/ext4：✅ 支持大文件
- CloudDrive2 网盘：✅ 通常支持大文件

## 📊 Web 界面预览

### 主控制台

- 📈 实时任务进度
- 📝 系统日志（最近 120 条）
- 📊 统计信息（任务数量、最后扫描时间）

### 侧边栏配置

- ⚙️ 监控配置
- ☁️ CD2 转移配置
- 🚀 保存并扫描按钮

## 🛡️ 生产部署建议

### 1. 网盘空间规划

避免触发网盘风控：

```
115网盘/
├── PT下载/              # CD2 拉取源（VPS 只读）
└── VPS_Transfer/        # VPS 专用中转目录
    └── ISO备份/         # 最终存储（VPS 只写）
```

**重要**：不要将 VPS 的 CD2 挂载到海量文件目录，使用专门的空目录作为接收站。

### 2. VPS 配置建议

- **CPU**：2 核及以上
- **内存**：4GB 及以上
- **磁盘**：至少 100GB 可用空间（用于临时 ISO）
- **网络**：带宽越大越好（影响上传速度）

### 3. 监控告警

```bash
# 添加到 crontab，监控服务状态
*/5 * * * * docker ps | grep iso-packer || docker-compose restart
```

### 4. 备份重要数据

定期备份：
```bash
# 备份配置和状态
tar -czf iso-packer-backup-$(date +%Y%m%d).tar.gz data/
```

## 🔄 更新升级

```bash
# 拉取最新代码
git pull

# 重新构建镜像
docker-compose build

# 重启服务
docker-compose up -d
```

## 📝 开发状态

| 功能模块 | 状态 | 说明 |
|---------|------|------|
| 自动监控与扫描 | ✅ 完成 | 稳定运行 |
| ISO 封装引擎 | ✅ 完成 | 支持 4K UHD |
| ISO 验证 | ✅ 完成 | xorriso 验证 |
| CD2 转移 | ✅ 完成 | 带进度监控 |
| Web 管理界面 | ✅ 完成 | 实时刷新 |
| 状态持久化 | ✅ 完成 | JSON 存储 |
| 日志系统 | ✅ 完成 | 7 天自动清理 |
| 115 上传 | ⚠️ 部分 | 需额外脚本 |

**生产就绪度**：✅ 可用（核心功能完善）

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 🔗 相关项目

- [AutoISO](https://github.com/xeiderx/AutoISO) - 分布式企业级版本
- [CloudDrive2](https://www.clouddrive2.com/) - 网盘挂载工具
