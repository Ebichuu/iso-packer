# ISO Packer - Docker Image (built and published by GitHub Actions)
FROM python:3.11-slim

ARG APP_VERSION
ARG VCS_REF
LABEL maintainer="iso-packer"
LABEL version="${APP_VERSION}"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.source="https://github.com/Ebichuu/iso-packer"
LABEL description="Automatic Blu-ray ISO packing with logs center, lightweight media compare, and CloudDrive2 transfer"

WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    genisoimage \
    xorriso \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Actions 的构建上下文为项目根目录。版本来自同一份 VERSION 文件。
COPY v2.0/requirements.txt /app/requirements.txt
COPY v2.0/iso-packer/VERSION /app/VERSION
COPY v2.0/iso-packer/scripts/check_release.py /app/scripts/check_release.py
RUN python /app/scripts/check_release.py --expect-version "$APP_VERSION"
COPY v2.0/iso-packer/app.py /app/
COPY v2.0/iso-packer/core.py /app/
COPY v2.0/iso-packer/worker_runtime.py /app/
COPY v2.0/iso-packer/upload_control.py /app/
COPY v2.0/iso-packer/release_calendar_fetcher.py /app/
COPY v2.0/iso-packer/data /app/data/
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
