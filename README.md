# ISO Packer

轻量个人版蓝光原盘自动封装工具。当前主线以 `ebichu/iso-packer:latest` 为准，面向单 VPS、自用部署、固定 CD2 流程。

## 当前定位

- 单实例 Docker 部署
- 固定流程：`/watch -> /output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso`
- CloudDrive2 API 用于只读观察、测试连接和封装前门禁
- 只做封装、转移和观察

## 已有功能

- 监控 `BDMV` / `VIDEO_TS` 原盘目录
- 使用 `genisoimage` 封装 ISO
- 使用 `xorriso` 做封装后校验
- 将 ISO 从 `/output` 移动到 CD2 目标目录
- Web 密码登录保护
- 任务耗时统计
- 读取 CD2 API 上传 / 下载 / 复制任务并显示状态
- CD2 下载或复制未完成时，自动等待，不抢跑封装
- 目录观察：`watch` / `output` / `cd2`
- `GET /healthz` 健康检查

## 封装说明

当前封装链路是：

```text
识别原盘目录 -> genisoimage 打包 -> xorriso 校验 -> 移动到 CD2 目标目录
```

说明：

- 只处理原盘目录，不处理普通单视频文件
- 不做转码，不改音轨和视频轨
- 双层、三层、4K UHD 原盘都按原结构打包
- Dolby Vision、HDR10+、Atmos 等信息不会被重新编码
- 前提是原盘目录完整，且 `/output` 有足够临时空间

## 推荐部署

推荐直接使用 Docker Hub 镜像：

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

说明：

- `./data` 用于持久化配置、状态和日志
- `/mnt/115Download` 是监控目录
- `/mnt/iso-output` 是临时 ISO 输出目录
- `/CloudNAS:/CloudNAS:rslave` 用于接收 CD2 的挂载传播
- `extra_hosts` 用于在 Linux bridge 网络下访问宿主机上的 CD2 API

如果你要本地改代码再构建，把 `image:` 改成 `build: .` 即可。

## 首次使用

1. 启动容器：

   ```bash
   docker compose up -d
   ```

2. 打开：

   ```text
   http://<你的 VPS IP>:15865/
   ```

3. 首次进入会先要求设置 Web 登录密码

4. 在设置页确认或修改下面这些值：

   ```text
   监控目录: /watch
   输出目录: /output
   CD2 挂载根目录: /CloudNAS
   CD2 目标目录: /CloudNAS/CloudDrive/00-未整理/00-mkiso
   ```

5. 如果你要看 CD2 上传 / 下载 / 复制状态，并让封装前门禁参考 CD2 任务，再额外填写：

   ```text
   启用 CD2 API: 勾选
   CD2 认证方式: API Token
   CD2 API 地址: host.docker.internal:19798
   CD2 API Token: 按你的 CD2 实际配置填写
   轮询秒数: 10
   ```

   如果你不用 Token，也可以切换成用户名密码模式；个人部署建议优先用 API Token。

6. 保存设置后开始监控

## Web 界面现在能看什么

- 当前任务状态
- 封装耗时、转移耗时、总耗时
- CD2 上传 / 下载 / 复制状态
- 最近日志
- 目录观察：
  - `watch`
  - `output`
  - `cd2`

目录观察是只读的，主要为了少进 CD2 容器确认文件状态。

## 健康检查

容器健康检查走的是：

```bash
curl http://127.0.0.1:15865/healthz
```

正常返回：

```json
{"ok": true}
```

## 常用命令

查看日志：

```bash
docker logs -f iso-packer
```

更新镜像：

```bash
docker compose pull
docker compose up -d
```

源码构建：

```bash
docker compose up -d --build
```

备份数据目录：

```bash
tar -czf iso-packer-data-$(date +%Y%m%d).tar.gz data/
```

## 常见问题

### 1. 为什么 CD2 API 不是必须的

因为当前项目的实际转移逻辑仍然是文件系统移动：

```text
/output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

CD2 API 只做只读观察和封装门禁：

- 测试连接
- 读取上传 / 下载 / 复制任务并显示状态
- 判断 `/watch` 里的原盘是否仍在由 CD2 下载或复制，未完成时先等待

它不会通过 API 直传 ISO，也不会自动创建、删除、取消或接管 CD2 任务。

### 2. 为什么必须挂载 `/CloudNAS`

因为 CD2 的 FUSE 挂载点通常是在 `/CloudNAS` 下动态出现，`/CloudNAS:/CloudNAS:rslave` 才能让容器看到这些变化。

### 3. 封装完成但网盘里暂时看不到

通常是 CD2 还在后台上传。此时 Web 界面里的 CD2 状态区和目录观察区会比以前更方便。

### 4. 双层杜比原盘有没有问题

当前方案不转码，只做原盘目录打包和校验，所以双层、三层、UHD、杜比视界、Atmos 这类内容本身没有额外兼容层要处理。真正关键的是原盘结构完整和临时空间足够。

## 相关文档

- [QUICKSTART.md](QUICKSTART.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [CLOUDDRIVE2_INTEGRATION.md](CLOUDDRIVE2_INTEGRATION.md)
- [ISO_PACKER_PLAN.md](ISO_PACKER_PLAN.md)
