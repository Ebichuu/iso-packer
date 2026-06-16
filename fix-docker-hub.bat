@echo off
echo ========================================
echo Docker Hub 镜像手动推送脚本
echo ========================================
echo.

echo 第 1 步: 登录 Docker Hub
echo 请输入用户名: ebichu
echo 请输入 Token (从 https://hub.docker.com/settings/security 获取)
echo.
docker login

echo.
echo 第 2 步: 构建镜像
docker build -t ebichu/iso-packer:latest .
if errorlevel 1 (
    echo [错误] 镜像构建失败
    pause
    exit /b 1
)

echo.
echo 第 3 步: 推送到 Docker Hub
docker push ebichu/iso-packer:latest
if errorlevel 1 (
    echo [错误] 镜像推送失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo [成功] 镜像已推送到 Docker Hub!
echo ========================================
echo.
echo 现在可以在服务器上执行:
echo   docker compose pull
echo   docker compose up -d
echo.
pause
