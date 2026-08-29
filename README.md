# ISO Packer

蓝光原盘自动封装与归档工具。项目面向个人或小型 VPS 部署场景，用于把 `BDMV` / `VIDEO_TS` 原盘目录自动封装为 ISO，并配合 CloudDrive2 完成归档观察、候选拉取、转存和上传状态跟踪。

当前主版本是 **v2.0**，源码、Dockerfile、Compose 配置和本地启动脚本都集中在 [`v2.0/`](v2.0/) 目录。旧版根目录项目已移除，后续开发和发布都以 v2.0 为准。

## 功能概览

- 自动识别 `/watch` 里的 `BDMV` / `VIDEO_TS` 原盘目录。
- 使用 `genisoimage` 生成 ISO，并使用 `xorriso` 做封装后校验。
- 支持将成品 ISO 转存到 CloudDrive2 挂载目录。
- 封装中心集中展示当前封装、校验、转存、CD2 上传、后台文件操作和 CD2 远程候选队列。
- 文件浏览支持监控目录、输出目录和网盘挂载目录查看，并提供多选、属性、重命名、复制、移动、删除等受控操作。
- CD2 远程候选队列支持从配置的远程目录发现原盘，并通过 CD2 网盘内复制任务拉取到监控目录。
- 首页展示运行摘要、已交付原盘资产、发行日历和主要入口。
- 支持 TMDB 元数据补全，用于海报、中文名和发行信息展示。
- 提供 Web 登录保护、健康检查和 Docker Hub 镜像发布流程。

## 当前发布

- 正式镜像：`ebichu/iso-packer:latest`
- 测试镜像：`ebichu/iso-packer:test`
- 应用端口：`15865`
- 本地预览端口：`15866`
- 详细说明：[v2.0/README.md](v2.0/README.md)

## 快速部署

推荐直接使用 Docker Hub 正式镜像：

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
      - /path/to/watch:/watch
      - /path/to/output:/output
      - /CloudNAS:/CloudNAS:rslave

    network_mode: bridge

    extra_hosts:
      - "host.docker.internal:host-gateway"
```

启动：

```bash
docker compose up -d
```

更新：

```bash
docker compose pull
docker compose up -d
```

健康检查：

```bash
curl http://127.0.0.1:15865/healthz
```

首次访问 Web 页面时会要求设置登录密码。

## 本地开发预览

Windows 本地预览建议使用：

```powershell
cd v2.0
.\start-local.bat
```

脚本默认启用本地安全预览开关：

```text
ISO_PACKER_DISABLE_AUTH=1
ISO_PACKER_DISABLE_CD2_PULL=1
ISO_PACKER_DISABLE_CD2_STATUS_POLL=1
```

这些开关用于避免本地预览时误触发真实登录、真实 CD2 拉取或持续读取 CD2 队列。

## 目录结构

```text
v2.0/
  Dockerfile
  docker-compose.yml
  requirements.txt
  start-local.bat
  iso-packer/
    app.py
    core.py
    templates/
    static/
    scripts/
    data/
```

关键入口：

- [`v2.0/iso-packer/app.py`](v2.0/iso-packer/app.py)：Flask Web 应用和 API。
- [`v2.0/iso-packer/core.py`](v2.0/iso-packer/core.py)：配置、状态和核心工具函数。
- [`v2.0/iso-packer/templates/`](v2.0/iso-packer/templates/)：Flask 页面模板。
- [`v2.0/iso-packer/static/js/`](v2.0/iso-packer/static/js/)：原生 JS 页面逻辑。
- [`.github/workflows/`](.github/workflows/)：Docker Hub 镜像构建与发布。

## 关键语义

- `/watch` 是临时输入目录，用于接收待封装原盘。
- `/output` 是本机临时输出目录，用于承接生成后的 ISO。
- 开启 CD2 转存后，最终成品应到 CD2 挂载输出目录查看。
- 如果 `/output` 中已有同名且校验通过的 ISO，会复用该文件并继续 CD2 转存，不会重复封装；CD2 目标目录中的同名文件只有在同大小且校验通过时才会视为已完成。
- CD2 API 主要用于观察队列、候选拉取、目录刷新和封装前门禁；ISO 成品转存仍以文件系统写入挂载目录为主。
- “复制到监控目录”使用 CD2 网盘内复制能力，不是本机 `/CloudNAS -> /watch` 文件复制。

## 常用检查

```powershell
cd v2.0\iso-packer
python -B scripts\smoke_v2.py
python -B -m py_compile app.py core.py release_calendar_fetcher.py scripts\smoke_v2.py scripts\update_release_calendar.py
node --check static\js\shared.js
node --check static\js\index.js
node --check static\js\workspace.js
node --check static\js\files.js
node --check static\js\settings.js

cd ..
docker compose config --quiet
```

## 安全说明

- 不要提交 `data/`、运行日志、真实 Web 密码、CD2 Token、TMDB Token 或任何 VPS 地址。
- 配置和密钥应通过运行时数据目录、环境变量或 Web 设置页保存。
- Docker Hub `latest` 用于正式发布；实验验证建议先使用 `test`。
