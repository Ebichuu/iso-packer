# ISO Packer 本地集成验证

这份说明用于验证真实 ISO 工具链。默认不会操作 VPS 上正在运行的 `iso-packer` 容器，也不会读写生产 `/data`、`/watch`、`/output` 或 CD2 挂载目录。

## 验证目标

- 创建一个最小 BDMV 样本目录。
- 使用和主程序一致的 `genisoimage` 关键参数生成 `.iso.partial`。
- 将 `.iso.partial` 改名为正式 ISO。
- 使用 `xorriso -toc` 校验生成的 ISO。
- 可选模拟本地转移：分块写入 `.partial`、`fsync`、大小校验、原子改名。

它不验证 CD2 API、真实上传队列、真实网盘上传速度，也不会创建 CD2 复制任务。

## 本机或 VPS 直接运行

前提是机器上已有 `genisoimage` 和 `xorriso`：

```bash
python scripts/integration_smoke.py
```

保留测试现场：

```bash
python scripts/integration_smoke.py --keep
```

模拟转移到一个安全的本地目录：

```bash
python scripts/integration_smoke.py --transfer-target /tmp/iso-packer-transfer-smoke
```

Windows PowerShell 下可以先看帮助或验证缺依赖提示：

```powershell
python .\scripts\integration_smoke.py --help
python .\scripts\integration_smoke.py
```

Windows 本机通常没有 `genisoimage` / `xorriso`，返回缺命令是正常结果。要验证完整链路，建议用 Docker 或在 Linux/VPS 临时目录里运行。

## 在 Docker 镜像里运行

如果宿主机没有 `genisoimage` / `xorriso`，可以用镜像里的依赖跑。下面命令只挂载当前项目目录，不会使用生产 `/data`：

```bash
docker run --rm \
  -v "$PWD":/workspace \
  -w /workspace \
  ebichu/iso-packer:latest \
  python /workspace/scripts/integration_smoke.py
```

如果要同时验证转移模拟，可以挂载一个临时目录：

```bash
mkdir -p /tmp/iso-packer-transfer-smoke
docker run --rm \
  -v "$PWD":/workspace \
  -v /tmp/iso-packer-transfer-smoke:/transfer-smoke \
  -w /workspace \
  ebichu/iso-packer:latest \
  python /workspace/scripts/integration_smoke.py --transfer-target /transfer-smoke
```

如需验证当前本地源码，而不是 Docker Hub 已发布镜像，可先本地构建一个临时镜像再跑：

```bash
docker build -t iso-packer:smoke .
docker run --rm \
  -v "$PWD":/workspace \
  -w /workspace \
  iso-packer:smoke \
  python /app/scripts/integration_smoke.py
```

## VPS 上建议的安全顺序

1. 不停止现有容器。
2. 不挂载生产 `/data`。
3. 不挂载生产 `/watch`、`/output`、`/CloudNAS`。
4. 只使用临时目录或 `--transfer-target /tmp/...`。
5. 测试通过后，再考虑是否用新镜像替换生产容器。

推荐 VPS 命令：

```bash
mkdir -p /tmp/iso-packer-transfer-smoke
docker run --rm \
  -v /tmp/iso-packer-transfer-smoke:/transfer-smoke \
  ebichu/iso-packer:latest \
  python /app/scripts/integration_smoke.py --transfer-target /transfer-smoke
```

如果镜像内没有 `/app/scripts/integration_smoke.py`，说明正在测试的是旧镜像。此时用源码目录挂载方式运行，或等新镜像发布后再跑。

## 通过标准

脚本最后输出：

```text
OK: local ISO toolchain smoke test passed
```

如果缺少命令，会返回 `2` 并提示缺少 `genisoimage` 或 `xorriso`。如果封装、校验、转移模拟失败，会返回 `1`。

## 和生产链路的关系

这个 smoke test 对应生产链路里的基础段：

```text
BDMV 目录 -> genisoimage 写入 .iso.partial -> 改名为 .iso -> xorriso 校验
```

开启 `--transfer-target` 后，还会对应本地转移段：

```text
ISO -> 目标目录 .partial -> 大小校验 -> 改名为正式 ISO
```

真实生产里的 CD2 上传进度、CD2 下载完成门禁、远程候选自动拉取，需要另外用 CD2 API 集成测试验证。

## CD2 API 只读探针

`scripts/cd2_readonly_probe.py` 用于验证 CD2 API 的真实读取能力。它只调用上传队列、下载队列、复制队列读取逻辑，不会创建 CD2 复制任务，不会移动文件，也不会写入 iso-packer 的生产状态。

直接传 API Token：

```bash
python scripts/cd2_readonly_probe.py \
  --addr 127.0.0.1:19798 \
  --token "你的-CD2-API-Token"
```

如果要验证某个 ISO 目标路径是否能匹配上传队列，可以加 `--path` 和路径别名：

```bash
python scripts/cd2_readonly_probe.py \
  --addr 127.0.0.1:19798 \
  --token "你的-CD2-API-Token" \
  --alias /CloudNAS/CloudDrive=/115 \
  --path /CloudNAS/CloudDrive/00-未整理/00-mkiso/Movie.iso
```

在 Docker 镜像里跑，并只读挂载当前源码：

```bash
docker run --rm \
  -v "$PWD":/workspace \
  -w /workspace \
  ebichu/iso-packer:latest \
  python /workspace/scripts/cd2_readonly_probe.py \
    --addr host.docker.internal:19798 \
    --token "你的-CD2-API-Token"
```

如果要读取现有 `config.json`，建议只读挂载，不要把生产 `/data` 整个可写挂进去：

```bash
docker run --rm \
  -v "$PWD":/workspace \
  -v /path/to/config.json:/tmp/iso-packer-config.json:ro \
  -w /workspace \
  ebichu/iso-packer:latest \
  python /workspace/scripts/cd2_readonly_probe.py \
    --config /tmp/iso-packer-config.json
```

返回码含义：

- `0`：CD2 连接成功，上传 / 下载 / 复制队列读取没有错误。
- `1`：连接到了 CD2，但认证失败、权限不足、队列读取失败或返回错误。
- `2`：本地参数缺失、配置不可读，或镜像里缺少 `clouddrive2-client`。
