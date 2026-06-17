# 快速开始

这份文档按当前主线写，只针对轻量个人版 `iso-packer`。

## 1. 准备目录

```bash
mkdir -p ~/iso-packer/data
cd ~/iso-packer
```

你需要准备好这几个宿主机目录：

- `./data`：持久化配置、状态、日志
- `/mnt/115Download`：监控目录
- `/mnt/iso-output`：临时 ISO 输出目录
- `/CloudNAS`：CD2 挂载父目录

## 2. 创建 `docker-compose.yml`

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

如果你要本地改代码构建，把 `image:` 改成：

```yaml
build: .
```

## 3. 启动

```bash
docker compose up -d
```

检查服务：

```bash
docker ps | grep iso-packer
curl http://127.0.0.1:15865/healthz
```

## 4. 首次登录

打开：

```text
http://<你的 VPS IP>:15865/
```

首次进入会先要求设置一个 Web 密码。设置完成后再进入主界面。

## 5. 建议的设置值

设置页建议至少确认下面这些值：

```text
监控目录: /watch
输出目录: /output
扫描间隔: 20
稳定时间: 180
最小剩余空间: 按你的磁盘情况调整

启用监控: 开
启用 CD2 转移: 开

CD2 挂载根目录: /CloudNAS
CD2 目标目录: /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

如果需要显示 CD2 上传进度，再打开 CD2 API：

```text
启用 CD2 API: 开
CD2 API 地址: host.docker.internal:19798
CD2 API 用户名: 你的 CD2 用户名
CD2 API 密码: 你的 CD2 密码
轮询秒数: 10
```

注意：CD2 API 只用来读上传进度，不负责真正上传文件。

## 6. 现在可以看到什么

启动后，Web 界面可以直接看：

- 当前任务状态
- 任务总耗时、封装耗时、转移耗时
- CD2 上传进度
- 目录观察：
  - `watch`
  - `output`
  - `cd2`

## 7. 快速验证

1. 在监控目录放入一个完整原盘目录
2. 等待扫描和稳定时间
3. 观察任务是否进入封装
4. 查看 `/output` 是否出现 ISO
5. 查看 `cd2` 目录观察里是否进入目标目录
6. 如果启用了 CD2 API，查看上传进度是否变化

## 8. 常用命令

查看日志：

```bash
docker logs -f iso-packer
```

重启：

```bash
docker compose restart
```

停止：

```bash
docker compose down
```

更新镜像：

```bash
docker compose pull
docker compose up -d
```

源码重建：

```bash
docker compose up -d --build
```

## 9. 常见排查

### CD2 目录看不到内容

先确认：

```bash
docker exec -it iso-packer ls -la /CloudNAS
docker exec -it iso-packer ls -la /CloudNAS/CloudDrive
```

如果这里都看不到，优先检查挂载传播是不是用了 `:rslave`。

### CD2 上传进度显示不了

先确认：

- CD2 API 已启用
- 地址、用户名、密码正确
- compose 里加了 `host.docker.internal:host-gateway`

### 任务不启动

优先检查：

- 监控目录里是否是完整 `BDMV` / `VIDEO_TS`
- 文件是否还在持续写入
- `/output` 空间是否足够

## 10. 这版主线

当前项目只聚焦轻量封装、转移和观察。
