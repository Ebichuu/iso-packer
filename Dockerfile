# ISO Packer - Docker Image
# 蓝光原盘自动封装与转存工具

FROM python:3.11-slim

LABEL maintainer="iso-packer"
LABEL version="1.0.0"
LABEL description="Automatic Blu-ray ISO packing and CloudDrive2 transfer tool"

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    genisoimage \
    xorriso \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制应用文件
COPY iso-packer/app.py /app/
COPY iso-packer/page.py /app/

# 安装 Python 依赖
RUN pip install --no-cache-dir flask==3.0.0

# 创建必要的目录
RUN mkdir -p /data /watch /output /cd2

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 暴露端口
EXPOSE 15865

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:15865/ || exit 1

# 启动命令
CMD ["python", "-u", "app.py"]
