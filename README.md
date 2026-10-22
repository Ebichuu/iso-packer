# ISO Packer

蓝光原盘自动封装与归档工具。项目面向个人或小型 VPS 部署场景，用于把 `BDMV` / `VIDEO_TS` 原盘目录自动封装为 ISO，并配合 CloudDrive2 完成归档观察、候选拉取、转存和上传状态跟踪。

当前开发版本由 [`v2.0/iso-packer/VERSION`](v2.0/iso-packer/VERSION) 定义。`v2.0/` 是沿用的目录名，源码、Dockerfile、Compose 配置和本地启动脚本都位于该目录；旧版根目录项目已移除。

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
- 可手动暂停 CD2 全部上传、暂停到自定义时间，或配置多个每日暂停窗口，全部按北京时间执行；定时默认关闭。

## 当前发布

- 正式镜像：`ebichu/iso-packer:latest`
- 测试镜像：`ebichu/iso-packer:test`
- 每次 Actions 构建同时发布 `ebichu/iso-packer:sha-<12位提交号>`，用于固定验收版本和回滚。
- 应用端口：`15865`
- 仓库 Compose 预览端口：`15866`；本地 Python 启动端口：`15865`
- 详细说明：[v2.0/README.md](v2.0/README.md)

`latest`、Git 标签和源码开发版本可能不同。2026-10-22 已在 VPS 隔离容器通过 1 GiB 合成原盘封装、Web 响应、32 MiB 合成样本的真实 CD2 上传完成确认，以及单个自有测试上传 key 的暂停/恢复 RPC；整套调度与认领由本地回归覆盖，媒体播放和长期负载另行验收。页面版本号不能代表正式镜像已更新。当天本轮开始时，主线为 `e4d1f48`，最新 Git 标签为 `v2.0.2`；这只是发布快照。

## 快速部署

正式部署使用 Docker Hub 正式镜像；验收新改动时使用 `test`，或固定到目标 `sha-<12位提交号>` 镜像：

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
docker compose pull iso-packer
docker compose up -d --no-deps --no-build iso-packer
```

更新：

```bash
docker compose pull iso-packer
docker compose up -d --no-deps --no-build iso-packer
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
ISO_PACKER_DISABLE_WORKER=1
ISO_PACKER_BIND_HOST=127.0.0.1
```

这些开关使免登录预览仅监听本机，并关闭自动封装扫描/恢复、真实 CD2 拉取和持续读取 CD2 队列。手动文件操作仍会生效，请只使用测试数据。

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
    VERSION
    worker_runtime.py
    upload_control.py
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
- 如果 `/output` 中已有同名且校验通过的 ISO，会复用该文件并继续 CD2 转存，不会重复封装；CD2 上传完成只以 API 的明确完成状态为准，不用目标文件本地大小或校验结果推断。
- CD2 API 主要用于观察队列、候选拉取、目录刷新和封装前门禁；ISO 成品转存仍以文件系统写入挂载目录为主。
- “复制到监控目录”使用 CD2 网盘内复制能力，不是本机 `/CloudNAS -> /watch` 文件复制。

## 常用检查

```powershell
cd v2.0\iso-packer
python -B scripts\smoke_v2.py
python -B -m unittest discover -p "test_*.py" -v
python -B -m unittest discover -s scripts -p "test_*.py" -v
python -B -m py_compile app.py core.py worker_runtime.py upload_control.py release_calendar_fetcher.py scripts\smoke_v2.py scripts\update_release_calendar.py scripts\check_release.py scripts\acceptance_runtime.py
node --check static\js\shared.js
node --check static\js\index.js
node --check static\js\workspace.js
node --check static\js\files.js
node --check static\js\settings.js
node --test scripts\test_frontend_races.cjs scripts\test_upload_controls.cjs

cd ..
docker compose config --quiet
```

Linux 真实工具验收使用 [`v2.0/iso-packer/scripts/acceptance_runtime.py`](v2.0/iso-packer/scripts/acceptance_runtime.py)，在隔离容器内生成合成原盘，调用 `genisoimage`/`xorriso` 并检查独立 worker 与页面端点响应。容器用法与本轮验收数据见 [v2.0/README.md](v2.0/README.md#linux-隔离验收)。

## 安全说明

- 不要提交 `data/`、运行日志、真实 Web 密码、CD2 Token、TMDB Token 或任何 VPS 地址。
- 配置和密钥应通过运行时数据目录、环境变量或 Web 设置页保存。
- Docker Hub `latest` 用于正式发布；实验验证建议先使用 `test`。
- 镜像只通过 GitHub Actions 构建与推送。正式流程必须手动选择与 `VERSION` 一致且指向当前提交的 `v<版本号>` 标签，不能在 `main` 上沿用最近的旧标签发布新代码。
