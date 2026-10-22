@echo off
setlocal
REM ISO Packer - 本地测试启动脚本（Windows）
set /p APP_VERSION=<"%~dp0iso-packer\VERSION"

echo ========================================
echo  ISO Packer v%APP_VERSION%
echo  本地测试模式
echo ========================================
echo.

cd /d "%~dp0iso-packer"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

echo [信息] Python 版本:
python --version
echo.

REM 检查依赖
echo [信息] 检查依赖...
python -c "import flask, clouddrive2_client" >nul 2>&1
if errorlevel 1 (
    echo [警告] 依赖不完整，正在安装 Flask 和 CloudDrive2 客户端...
    python -m pip install -r ..\requirements.txt
    if errorlevel 1 exit /b 1
)

REM 创建测试目录
if not exist "..\data" mkdir "..\data"
if not exist "..\test-watch" mkdir "..\test-watch"
if not exist "..\test-output" mkdir "..\test-output"

echo [信息] 数据目录: %CD%\..\data
echo [信息] 监控目录: %CD%\..\test-watch
echo [信息] 输出目录: %CD%\..\test-output
echo.

REM 设置环境变量
set DATA_DIR=%CD%\..\data
set PYTHONUNBUFFERED=1
set ISO_PACKER_BIND_HOST=127.0.0.1
set ISO_PACKER_DISABLE_AUTH=1
set ISO_PACKER_DISABLE_CD2_PULL=1
set ISO_PACKER_DISABLE_CD2_STATUS_POLL=1
set ISO_PACKER_DISABLE_WORKER=1

echo ========================================
echo  启动 ISO Packer v%APP_VERSION%
echo ========================================
echo.
echo [访问] http://localhost:15865
echo [认证] 本地测试已免登录
echo [CD2] 本地测试默认禁止真实拉取；需要真实拉取时请取消 ISO_PACKER_DISABLE_CD2_PULL
echo [封装] 本地预览禁用自动扫描和恢复，手动文件操作仍会生效
echo [停止] 按 Ctrl+C
echo.

REM 启动应用
python app.py

pause
