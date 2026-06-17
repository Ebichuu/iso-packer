# VPS 部署说明

这份部署文档只对应当前轻量版 `iso-packer`，默认基线是 `ebichu/iso-packer:latest`。

## 目标场景

适合下面这种固定用法：

```text
/watch -> /output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

也就是：

- 从监控目录识别原盘
- 在本地临时目录封装 ISO
- 再把 ISO 移动到 CD2 挂载目录
- 如需查看网盘上传进度，再额外读取 CD2 API

## 1. VPS 前置条件

至少确认这些：

- 已安装 Docker 与 Docker Compose
- CD2 已在宿主机正常运行
- 宿主机能看到 `/CloudNAS/CloudDrive`
- 临时输出目录有足够空间

建议：

- CPU：2 核以上
- 内存：4 GB 以上
- `/output` 所在磁盘留有足够空间

## 2. 目录规划

推荐按下面这种方式准备：

```text
宿主机
├─ ./data
├─ /mnt/115Download
├─ /mnt/iso-output
└─ /CloudNAS
   └─ CloudDrive
      └─ 00-未整理
         └─ 00-mkiso
```

说明：

- `./data`：保存 `config.json`、`state.json`、日志
- `/mnt/115Download`：监控目录
- `/mnt/iso-output`：临时 ISO 目录
- `/CloudNAS/CloudDrive/00-未整理/00-mkiso`：最终目标目录

## 3. 推荐 Compose

```yaml
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
      - ./data:/data
      - /mnt/115Download:/watch
      - /mnt/iso-output:/output
      - /CloudNAS:/CloudNAS:rslave

    network_mode: bridge

    extra_hosts:
      - "host.docker.internal:host-gateway"

    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

补充说明：

- 不强制依赖环境变量，主要配置都放在 Web 设置页和 `/data/config.json`
- `extra_hosts` 是为了让容器在 Linux bridge 模式下访问宿主机上的 CD2 API
- `rslave` 是为了接收 CD2 动态挂载传播

## 4. 启动与首配

启动：

```bash
docker compose up -d
```

检查：

```bash
docker ps | grep iso-packer
curl http://127.0.0.1:15865/healthz
```

首次访问：

```text
http://<你的 VPS IP>:15865/
```

首次打开会先要求设置 Web 登录密码。

## 5. 设置页建议

建议确认下面这些值：

```text
监控目录: /watch
输出目录: /output
启用监控: 开
启用 CD2 转移: 开
CD2 挂载根目录: /CloudNAS
CD2 目标目录: /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

如果你想在 Web 里直接看上传进度，再填写：

```text
启用 CD2 API: 开
CD2 API 地址: host.docker.internal:19798
CD2 API 用户名: 你的 CD2 用户名
CD2 API 密码: 你的 CD2 密码
轮询秒数: 10
```

这里不需要额外加环境变量，除非你自己就是想用环境变量统一管理。

## 6. 日常运维

查看日志：

```bash
docker logs -f iso-packer
```

升级镜像：

```bash
docker compose pull
docker compose up -d
```

源码改动后重建：

```bash
docker compose up -d --build
```

备份数据：

```bash
tar -czf iso-packer-data-$(date +%Y%m%d).tar.gz data/
```

## 7. 健康检查

当前健康检查接口：

```bash
curl http://127.0.0.1:15865/healthz
```

返回：

```json
{"ok": true}
```

## 8. 部署后的观察点

当前 Web 里可以直接确认这些：

- 当前任务有没有开始
- 当前任务耗时
- 转移是否完成
- CD2 上传进度有没有跑
- `watch` / `output` / `cd2` 目录里各自有什么

这意味着很多以前必须进 CD2 容器里确认的事情，现在可以先在 Web 里看。

## 9. 常见问题

### `/CloudNAS` 看不到内容

先检查宿主机和容器里是否一致：

```bash
ls -la /CloudNAS
docker exec -it iso-packer ls -la /CloudNAS
docker exec -it iso-packer ls -la /CloudNAS/CloudDrive
```

如果容器里看不到，优先检查：

- CD2 容器是不是正确做了共享挂载
- iso-packer 这边是不是用了 `:rslave`

### CD2 API 连不上

先检查：

- CD2 Web/API 本身是否可访问
- `extra_hosts` 是否已配置
- 地址是否写成了 `host.docker.internal:19798`

### 任务一直不进入封装

先看：

- 目录是不是完整原盘结构
- 文件是不是还在写入
- 监控是否已启用
- 输出目录空间是否足够

## 10. 从源码部署

如果你不是直接用 Docker Hub 镜像，而是按仓库源码构建：

```bash
git clone https://github.com/Ebichuu/iso-packer.git
cd iso-packer
docker compose up -d --build
```

这条主线以后也建议都以这个仓库为准同步。
