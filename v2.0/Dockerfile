# ISO Packer v2.0 - Docker Image
FROM python:3.11-slim

LABEL maintainer="iso-packer"
LABEL version="2.0.0"
LABEL description="Automatic Blu-ray ISO packing with UI refactor and CloudDrive2 transfer"

WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    genisoimage \
    xorriso \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# 复制 v2.0 应用代码。docker-compose 的 build context 是项目根目录，
# 所以路径必须显式带 v2.0，避免误拷贝旧版 iso-packer。
COPY v2.0/requirements.txt /app/requirements.txt
COPY v2.0/iso-packer/app.py /app/
COPY v2.0/iso-packer/core.py /app/
COPY v2.0/iso-packer/templates /app/templates/
COPY v2.0/iso-packer/static /app/static/
COPY v2.0/iso-packer/scripts /app/scripts/

# 安装 Python 依赖
RUN pip install --no-cache-dir -r /app/requirements.txt

# 创建数据目录
RUN mkdir -p /data /watch /output /CloudNAS

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai
ENV DATA_DIR=/data

# 暴露端口
EXPOSE 15865

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:15865/healthz || exit 1

# 启动
ENTRYPOINT ["tini", "-g", "--"]
CMD ["python", "-u", "app.py"]
