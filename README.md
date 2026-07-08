# ISO Packer

当前主版本是 `v2.0`，源码、Dockerfile、Compose 配置和本地启动脚本都集中在 [`v2.0/`](v2.0/) 目录。

## 当前发布

- GitHub 主线：`main`
- Docker Hub 正式镜像：`ebichu/iso-packer:latest`
- Docker Hub 测试镜像：`ebichu/iso-packer:test`
- 本地预览端口：`15866`

## 本地运行

```powershell
cd D:\Projects\makeiso\v2.0
.\start-local.bat
```

或使用 Docker Compose：

```powershell
cd D:\Projects\makeiso\v2.0
docker compose up -d --build
```

## 目录说明

- `v2.0/iso-packer/`：Flask 应用、模板和静态资源
- `v2.0/docker-compose.yml`：v2.0 本地容器配置
- `v2.0/Dockerfile`：Docker Hub 构建入口
- `.github/workflows/`：构建并推送 Docker Hub 镜像

旧版根目录项目已移除，后续开发和发布都以 `v2.0` 为准。
