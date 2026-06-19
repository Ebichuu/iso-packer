# ISO Packer - Docker Image
FROM python:3.11-slim

LABEL maintainer="iso-packer"
LABEL version="1.1.2"
LABEL description="Automatic Blu-ray ISO packing and CloudDrive2 transfer tool"

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    genisoimage \
    xorriso \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY iso-packer/app.py /app/
COPY iso-packer/page.py /app/
COPY iso-packer/core.py /app/

RUN pip install --no-cache-dir \
    flask==3.0.0 \
    clouddrive2-client==0.3.0

RUN mkdir -p /data /watch /output /CloudNAS

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

EXPOSE 15865

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:15865/healthz || exit 1

CMD ["python", "-u", "app.py"]
