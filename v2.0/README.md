# ISO Packer v2.x

蓝光原盘自动封装与归档工具。应用版本由 [`iso-packer/VERSION`](iso-packer/VERSION) 统一定义，页面、本地启动脚本和 Actions 镜像标签读取同一份版本；`v2.0/` 是沿用的项目目录名。v1.19 只作为历史功能参考。

## 当前状态

- 首页是展示页方向，重点展示已交付原盘资产、运行摘要、蓝光发行日历和主要入口。
- 已交付原盘资产保留海报墙展示；有 `tmdb_id` 的卡片整张可点击跳转 TMDB。
- 已交付资产海报依赖已保存的 TMDB 配置，或环境变量 `TMDB_API_KEY` / `TMDB_BEARER_TOKEN`。
- 封装入口统一命名为“封装中心”，用于快速判断当前是 CD2 拉取、生成 ISO、校验、转存、CD2 上传云端还是收尾。
- 封装中心包含“远程候选队列”和“产出与转存”：候选队列看输入端，产出面板看 ISO 生成、校验、转存、CD2 上传和文件操作。
- 文件浏览默认 `cd2` 根目录跟随设置里的网盘挂载根目录，默认 `/CloudNAS/CloudDrive`。
- 文件浏览支持多选、右键菜单、重命名、嵌入式属性面板、目录大小统计、排序、分页和目录选择弹层。
- 文件浏览“复制到监控目录”走 CD2 网盘内复制任务：从当前网盘位置复制到设置里的网盘监控目录。
- 文件浏览“复制到输出目录 / 复制到其他目录 / 移动 / 删除”仍是本机文件操作，并有路径边界和确认保护。
- 日志中心集中展示封装日志、CD2 拉取/转存/事件、文件操作和异常时间线，并支持类型筛选与搜索。
- 媒体检测页面向已经封装好的电影文件：默认扫描 CD2 成品目录，按名称、年份、分辨率、来源、发布组、大小和修改时间聚合同片不同组/不同版本，不做 BDMV 指纹。
- 设置页按“本地目录 / CD2 设置 / 系统设置”三类组织。
- Docker Hub 测试镜像使用 `ebichu/iso-packer:test`；`latest` 只在正式发布时更新。
- Web 与封装/转存 worker 使用独立进程；磁盘和 CD2 操作交由 worker，Web 请求通过有超时的进程通信读取状态和发起操作。VPS 隔离容器已通过 1 GiB 合成原盘封装及 Web 响应检查；真实 CD2 上传、媒体播放和完整异常恢复分别验收。

## 镜像部署与版本

仓库 Compose 默认拉取 `ebichu/iso-packer:test`，映射 `15866:15865`，数据目录和测试输入/输出目录均位于当前目录。部署前按实际场景配置持久化目录及 CloudDrive2 挂载。

```bash
cd v2.0
bash deploy.sh
```

脚本先拉取已发布镜像，再仅更新 `iso-packer-v2` 服务，保留其他 Compose 服务。只有目标容器通过 Docker 健康检查才报告成功；它不会在服务器上构建镜像。

验收或回滚时可固定 Actions 产出的提交镜像：

```bash
# 将示例提交号替换为 Actions 实际构建的 12 位提交号
ISO_PACKER_IMAGE=ebichu/iso-packer:sha-0123456789ab bash deploy.sh
```

`test`、`latest` 和 Git 标签不等于当前源码版本。2026-10-22 检查时，远端主线 `e4d1f48` 比最新标签 `v2.0.2` 多 26 个提交，`latest` 仍落后主线 17 个提交；本轮修复不会自动更新正式镜像。

## 关键语义

### 本机目录

- `/watch`：本机监控目录，是封装流程的临时输入目录。
- `/output`：本机输出目录，是 ISO 生成后的临时落点。
- 本机封装时允许在 `/output` 使用 `.iso.partial`，完成并校验后才改名为 `.iso`。
- 开启 CD2 转存并等待云端完成时，本机 `/output` 里的 ISO 会保留到 CD2 API 明确报告上传完成；API 明确报告失败时保留副本供重试，API 暂时不可用或任务暂时不在列表中时继续等待。
- `/output` 中已有同名 ISO 时，只有持久化的生成归属记录（provenance）与当前源树、ISO 文件身份均一致，且 ISO 校验通过，才会复用并继续转存。旧任务或重启后缺少生成归属的同名 ISO 不会自动复用或据此删除源目录，须人工核对。
- 如果开启成功后删除源目录，只有完成条件成立且源树仍与本次封装记录一致，才会清理 `/watch` 中对应的 BDMV。文件变更时间无法可靠读取时保守保留，不跳过身份检查。
- 因此“本机监控 / 本机输出”不是归档浏览入口，最终成品应到 CD2 挂载输出目录查看。

### CD2 与文件浏览

- CD2 网盘挂载根目录默认是 `/CloudNAS/CloudDrive`。
- 文件浏览“网盘挂载”入口从该根目录开始。
- “复制到监控目录”会调用 CD2 API 的网盘内复制能力，把所选源复制到设置里的网盘监控目录。
- 该操作不是本机 `/CloudNAS -> /watch` 文件复制，也不是远程候选队列的 BDMV 拉取。
- CD2 远程候选队列仍负责远端候选自动拉取，并创建 `waiting_cd2_pull` 状态。

### CD2 上传等待

- ISO Packer 将 ISO 写入 CD2 挂载输出目录后，CloudDrive2 可能还在把成品上传到云端。
- CD2 挂载目录和上传队列只允许扩展名严格为 `.iso` 的文件；`.iso.partial`、`.iso..partial` 和其他格式不会由 ISO Packer 转存或认领。
- CD2 上传只有明确进入 `UploadFileInfo.Finish=5` 或兼容的完成状态时才算已交付；`Transfer=3`、100% 进度、队列暂时为空和连接失败都不会单独触发完成或清理。
- 此时状态应显示为 `waiting_cd2_upload` / “CD2 上传云端中”。
- 如果已有 CD2 同名文件已经在上传队列中明确显示完成，会直接标记为已交付；没有明确完成记录时仍先等待队列确认。
- 如果条目已经是已交付完成态，UI 不再显示旧的上传百分比，避免出现“已交付但仍 0%/93%”的矛盾状态。
- 上传进度和任务状态直接展示 CD2 API 返回的数据；进度长时间不变或任务暂时不在 API 列表中不会被 ISO Packer 判定为卡住或失败，只有 API 明确失败才会进入失败状态。
- 即使上传完成后轮询队列迅速清空，也会保留 `PushMessage` 的明确终态证据；证据必须与上传 key、路径别名、大小和当前任务 generation 精确绑定，不能跨任务重放。
- 完成后的源目录与本机 ISO 自动清理会复核转存时记录的文件归属，避免删除后来替换的文件。旧任务缺少清理归属记录时，明确 API 完成仍可更新状态，但保留源目录和本机 ISO，并显示人工核对清理警告。
- 上传异常可以点击“重新检测”重新读取队列，也可以点击“确认已上传”。后者必须确认目标位于 CD2 成品目录、文件非空、大小符合已知目标大小且 ISO 结构校验通过。
- 源目录接收、等待下载/稳定、CD2 拉取和 CD2 确认等等待状态只计入“等待”，不计入“当前执行”；真正封装、转存和目录刷新才计入执行。
- CD2 远程候选扫描使用独立客户端和单任务 15 秒超时保护；超时不会叠加扫描线程，前端请求也会在 20 秒后结束，可稍后重新刷新。
- 名称明确包含 `BDMV` 或 `VIDEO_TS` 的远程监控根目录会一次列出全部一级候选，并按修改时间从新到旧处理；提交拉取前仍会进入选中目录复核原盘结构。通用目录继续逐层探测，任何不完整扫描都不会触发自动拉取或写入成功缓存。

### 版本感知封装

- 同一站点、同一影片且明确标注 `V1`、`V2`、`V3` 的版本，较高版本完成后才会清理较低版本；开启等待云端完成时，必须等新上传明确 `Finish`。清理还会复核本次 generation、新 ISO 与旧候选文件身份，后来被替换的旧文件会保留。
- 不同站点的发布结果始终共存；没有明确版本标记的文件也始终共存，不参与自动替换。
- 同一 CD2 远程源路径和目标目录会持久化自动/手动拉取认领，避免扫描周期重复创建相同任务；只有 API 明确失败才记录失败，API 暂时不返回任务时保持等待。
- CD2 复制或下载任务列表读取失败、不完整或客户端不支持对应查询接口时，封装流程会保持等待，不会把空队列当成没有任务。
- CD2 上传任务只按完整路径和已配置的路径别名精确匹配，不再用 basename 或路径后缀猜测不同目录的同名 ISO。
- CD2 拉取任务只依据 `GetCopyTasks` 返回的源路径、目标路径、进度和状态：活动任务继续等待，`Completed` 才完成认领，`Failed` 才记录失败；任务暂时不在列表中不会访问远端结果或本地目录来推断状态。
- 所有 CD2 网盘内复制都使用 `Rename` 冲突策略并递归处理重名，保存 API 返回的实际目标路径；不能设置安全冲突策略的客户端会被拒绝，绝不回退到覆盖模式。
- 不同远程源即使 basename 相同也会使用独立的本地拉取路径和状态记录，避免不同站点的同名作品互相覆盖。
- 文件浏览的自定义复制/移动目标只能位于本机监控、本机输出或 CD2 挂载根目录内；CD2 成品目录也必须位于配置的挂载根目录内。
- 文件操作拒绝选中的符号链接及包含链接的父路径；排队后源文件、父目录或授权根发生变化时会拒绝执行。复制采用排他创建，不覆盖已有文件；本服务的文件任务串行执行。
- `genisoimage`、`xorriso` 和 ISO 转存分别有总时长与无进展保护，异常时保留源目录并清理未完成目标，不会无限占用当前任务。
- 封装中心在本机 ISO 正在生成时提供“取消当前封装”；取消只终止 `genisoimage`、保留源目录并按异常恢复路径处理，不会删除已存在的完整 ISO。

### CD2 推送、控制与诊断

- 服务启动后会尝试订阅官方 `PushMessage`，目录和任务变化会触发防抖复查；断线、未授权或旧服务不支持时自动保留原有轮询。
- API Token 需要 `allow_push_message` 权限才能启用实时推送；缺少该权限不会阻断封装和轮询。
- 封装中心可对当前精确匹配的单个复制任务执行暂停、继续、重启、取消，对单个上传任务执行暂停、继续、取消；不提供批量取消。
- 封装中心的“运行诊断”读取 CD2 版本、CPU/内存、缓存/临时文件计数、任务计数和打开文件句柄。单项 RPC 不可用时只显示该项错误。

### CD2 上传暂停与本地上传错峰

系统设置的“上传暂停与每日窗口”和封装中心均提供手动控制。这里的范围是**当前 CD2 实例的全部上传任务**，包含其他程序创建的上传，不只限于 ISO Packer。

- “暂停 CD2 全部上传”会持续手动暂停，直到主动解除；也可选择任意未来北京时间，点击“暂停到此时间”。
- “解除手动暂停”取消手动规则。如果当前仍在每日暂停窗口内，暂停继续生效。
- “启用每日暂停窗口”默认关闭，窗口列表默认空。可按本地上传时间自定义最多 48 段 `HH:MM-HH:MM`，例如 `23:30-00:20` 表示到次日结束；不预填 00/06/12/18 等固定时刻。
- 窗口开始时间包含，结束时间不包含；重叠窗口按并集生效，开始与结束不能相同。启用计划时至少需要一个窗口。
- 所有时间均按北京时间 `Asia/Shanghai` 解释，与浏览器或 VPS 所在时区无关。每日窗口编辑后须点击“安全保存配置”；手动暂停按钮立即使用已经保存的 CD2 连接配置。
- 暂停策略也会阻止本项目开始转存。API 失联或队列不完整时，页面显示“已阻止本项目转存，CD2 暂停待确认”，不会把本机门禁等同于远端上传已暂停。
- 本项目的转存门禁立即遵守策略；其他程序新增的 CD2 上传由后台持续检查，存在短暂轮询间隔，不能视为对外部写入的即时阻断。
- 恢复时只处理本服务之前按上传 key 与路径认领的暂停任务，不调用批量恢复接口，不恢复原本已经暂停的任务。

此功能用于协调两地上传时间；是否已暂停以页面的 CD2 确认状态为准。2026-10-22 已在禁用真实 CD2 调用的本地隔离预览中通过 Edge 集成验收，覆盖自定义/跨午夜窗口保存、暂停状态刷新持久化、解除手动暂停保留计划、北京时间截止值、封装中心控制及 390 px 窄屏布局，页面 JavaScript 错误为 0。另以独立 32 MiB 合成样本的单个上传 key 验证真实 CD2 暂停/恢复 RPC，队列明确进入 `Pause=4` 并保持 1 秒，恢复后收到同 key 的 `Finish=5`；整套调度、任务认领及不误恢复其他任务由本地回归覆盖，未进行全局生产队列暂停验收。

## TMDB 配置

TMDB 配置入口在“系统设置 -> TMDB 元数据”。

需要填写并保存：

- API 域名
- 图片域名
- API Token
- 启用 TMDB 元数据补全

注意：

- “测试 TMDB”只验证连通性，不保存配置。
- 必须点击“安全保存配置”后，发行日历和首页已交付资产海报才会使用该配置。
- 也可以通过环境变量 `TMDB_API_KEY` 或 `TMDB_BEARER_TOKEN` 注入。

## 蓝光发行日历

- `Blu-ray.com` 作为基础发行源。
- `TMDB` 用于补中文名、TMDB ID 和海报。
- 碟影、贴吧、豆瓣只作为人工校对参考，不在首页卡片露出。
- 展示窗口从今天起算，优先显示今天及之后的待发售条目；缓存里没有未来条目时，再回退显示最近已发售。
- 发行卡片点击新开窗口跳转 Blu-ray.com。
- `TMDB #id` 徽标点击新开窗口跳转对应 TMDB 影片页。

数据缓存文件：

```text
iso-packer/data/release_calendar.json
```

手动刷新外网缓存：

```powershell
cd D:\Projects\makeiso\v2.0\iso-packer
python scripts\update_release_calendar.py --limit 12
```

也可以在首页点击“刷新外网”。该操作只访问 Blu-ray.com / TMDB，不触发 CD2 拉取或封装任务。

## 本地安全预览

Windows 本地预览建议使用：

```powershell
cd D:\Projects\makeiso\v2.0
.\start-local.bat
```

脚本默认设置：

```text
ISO_PACKER_DISABLE_AUTH=1
ISO_PACKER_DISABLE_CD2_PULL=1
ISO_PACKER_DISABLE_CD2_STATUS_POLL=1
ISO_PACKER_DISABLE_WORKER=1
ISO_PACKER_BIND_HOST=127.0.0.1
```

含义：

- `ISO_PACKER_DISABLE_AUTH=1`：本地预览免登录。
- `ISO_PACKER_DISABLE_CD2_PULL=1`：禁止创建真实 CD2 拉取任务。
- `ISO_PACKER_DISABLE_CD2_STATUS_POLL=1`：状态页不持续读取 CD2 队列。
- `ISO_PACKER_DISABLE_WORKER=1`：禁用自动封装扫描和启动恢复；手动文件与配置操作仍由独立 worker 执行。
- `ISO_PACKER_BIND_HOST=127.0.0.1`：免登录预览只监听本机回环地址。容器部署默认仍监听 `0.0.0.0`。

预览使用独立测试目录；手动文件操作仍会修改所选文件。正式部署或真实拉取验收时，再按需移除对应保护开关。

## 本地验收

核心 smoke：

```powershell
cd D:\Projects\makeiso\v2.0\iso-packer
python -B scripts\smoke_v2.py
```

正式版前建议检查：

```powershell
cd D:\Projects\makeiso\v2.0\iso-packer
python -B scripts\smoke_v2.py
python -B -m unittest discover -p "test_*.py" -v
python -B -m unittest discover -s scripts -p "test_*.py" -v
python -B scripts\check_release.py
python -B -m py_compile app.py core.py worker_runtime.py upload_control.py release_calendar_fetcher.py scripts\smoke_v2.py scripts\update_release_calendar.py scripts\check_release.py scripts\acceptance_runtime.py
node --check static\js\shared.js
node --check static\js\index.js
node --check static\js\workspace.js
node --check static\js\files.js
node --check static\js\settings.js
node --check static\js\logs.js
node --check static\js\compare.js
node --test scripts/test_*.cjs

cd D:\Projects\makeiso\v2.0
docker compose config --quiet
```

GitHub Actions 在构建镜像前执行后端/进程隔离测试、发布校验回归测试、smoke、Python 编译、前端 JavaScript 语法和部署配置检查。`test` 与 `sha-<12位提交号>` 同时推送；镜像版本和完整提交号写入 OCI 标签。镜像只由 Actions 构建和推送。

正式发布顺序：

1. 将修复合入主线，通过测试镜像完成下面的 VPS 实机验收。
2. 确认 `VERSION` 后，为验收通过的同一提交创建 `v<版本号>` Git 标签。
3. 手动运行 `Build and Push Docker Image`，选择该标签。
4. 流程校验标签名等于 `VERSION`，且标签精确指向构建提交；通过后才更新版本镜像及 `latest`。

从 `main` 或旧版本标签发起正式流程会直接失败，不再用 `git describe` 把新代码发布到旧版本名下。

## Linux 隔离验收

[`scripts/acceptance_runtime.py`](iso-packer/scripts/acceptance_runtime.py) 使用临时数据目录生成合成 BDMV，经过独立 worker 运行真实 `genisoimage`，再用 `xorriso -toc` 检查 ISO 结构。执行过程中反复请求 `/healthz`、`/api/status` 和 `/workspace`；任何端点失败或单次响应超过 1 秒均判定失败。脚本还检查源目录保留及完成后没有 `.partial` 遗留。

在已有测试镜像的 Linux 主机，从 `v2.0/` 目录运行离线验收：

```bash
docker run --rm --pull never --network none \
  --mount "type=bind,src=$PWD/iso-packer,dst=/app,readonly" \
  --workdir /app --entrypoint python \
  ebichu/iso-packer:test -B scripts/acceptance_runtime.py \
  --size-mib 1024 --timeout 180
```

该命令复用主机已有镜像并只读挂载当前源码，不构建镜像，不挂生产数据、CloudDrive2 目录或宿主机端口。合成文件写入验收容器临时目录；成功时输出 JSON 报告并清理，失败时报告 `retained_data_dir`，需要保留失败现场时去掉 `--rm`。

参数：`--size-mib` 为 1–4096 MiB，默认 256；`--timeout` 为 10–1800 秒，默认 180。合成样本只用于结构和进程通信验证，不是可播放的蓝光内容。

2026-10-22 上一轮收尾在 VPS 的独立、无网络验收容器运行上述 1 GiB 样本，生产服务保持运行，结果如下（本轮逻辑复审重跑见下文）：

| 项目 | 结果 |
| --- | --- |
| 生成 ISO | 1,074,630,656 字节，`genisoimage` 成功、`xorriso` 结构检查通过 |
| 上一轮离线重跑耗时 | 1.50 秒 |
| 请求数量 | Flask 测试客户端共 36 次端点请求 |
| 最长响应 | `/healthz` 0.58 ms；`/api/status` 4.95 ms；`/workspace` 14.92 ms |
| 验证范围 | 真实 ISO 工具、独立 worker、源文件保留、临时文件收尾、上述端点响应 |

这些响应时间来自容器内测试客户端，不能替代公网访问和长期负载测试。此轮离线结果不包含 CD2 上传或媒体播放验收。

脚本可显式增加 `--cloud-config /run/acceptance-config.json` 做 CD2 验收。操作者需另行提供可用网络、CD2 挂载以及只读配置文件；不要在离线命令上直接追加该参数。云端模式复制配置到独立临时目录，并仅在配置的 CD2 输出目录下创建唯一 `.iso-packer-acceptance-<随机值>` 子目录，关闭自动拉取、自动扫描及源删除。只有 API 明确确认上传完成才报告成功并清理本次云端样本；超时或失败保留样本，不加载或改写生产状态。

2026-10-22 上一轮修复 PushMessage 终态证据后，新的 32 MiB 随机合成 BDMV 完成真实 CD2 验收：生成 34,443,264 字节 ISO，PushMessage 依次收到同一上传 key 的 `0 (Wait)` 与 `5 (Finish)`，精确绑定路径别名、大小与任务 generation，最终进入 `transfer_done`，`cloud_api_confirmed=true`。全程 48.72 秒、993 次容器内端点请求；最长响应为 `/healthz` 2.08 ms、`/api/status` 19.72 ms、`/workspace` 19.81 ms。`xorriso` 结构检查、源目录保留和无 `.partial` 遗留均通过，仅在明确 Finish 后清理本次唯一云端目录与隔离数据。

额外真实 RPC 验收仅作用于另一个独立 32 MiB 合成样本的上传 key：34,443,264 字节 ISO 的上传经 `PauseUploadFiles` 后，队列明确为 `Pause=4` 且持续 1 秒；`ResumeUploadFiles` 后收到同 key 的明确 `Finish=5`，测试目录清理完成，全程 45.08 秒。范围为 `one_synthetic_upload_key`，未全局暂停生产上传，也未改生产配置或状态。

修复前的两个样本虽在云端可见，却未获得明确 API 完成终态，仍按待确认处理，不追认为成功。两个唯一云端测试目录已按撤销验收删除，记录 `completion_inferred=false`；对应已退出的自有验收容器已移除，本地预览进程树已停止，生产 `iso-packer` 服务保持运行且健康。

上一轮代码快照回归：Linux 后端 134 项全部通过（9.314 秒），Windows 后端 133 项通过、1 项 POSIX 专属测试跳过（7.902 秒）；发布/部署 scripts 在 Windows 9 项全部通过（0.723 秒），Linux 验收镜像中 8 项通过、1 项因缺 Git 跳过；两端 smoke 通过，Node 前端 16 项通过，Edge 本地隔离集成 8 项通过。该轮真实 CD2 结果对应源码包 SHA-256 `4e8a50d921ee8596ecace3621cba39f23b6454fe0b5be520af29f4c1706a1412`。

## 本轮逻辑复审（2026-10-22）

以本地提交 `e70d59f` 为基线，多 agent 复审并修复了以下流程：

- 旧版本清理延后到新任务满足完成条件；云端等待模式要求明确 Finish，并绑定 generation 与新旧文件身份。
- 源树逐项计算 metadata digest，ISO 保存生成归属记录；Windows 使用真实 `ChangeTime`，避免把创建时间当成变更时间。读不到可靠变更时间时保守保留；旧任务或重启后未知归属的 ISO 不自动复用、也不据此删源，交由人工核对。
- 手动确认上传完成时重新核对任务 generation；并发启动只允许一个当前封装，取消与最终收尾使用明确边界，避免接受取消后仍完成或删源。
- CD2 拉取区分完整原盘任务与子任务，按 Rename 返回的实际路径匹配，失败优先；“重新检测”清除旧失败终态后仍等待新的明确完成证据。
- 手动暂停接管上传任务时保留正确 ownership，自动恢复不会抢回用户暂停；控制前复核最新配置，RPC 串行化，Web 快照按单调 revision 接收，防止旧响应回滚配置。
- Web 父进程意外退出时清理 worker、工具子进程并释放数据目录租约。
- 文件操作拦截链接越界、排队期间路径替换和目标覆盖；设置页目录选择器丢弃过时请求，加载期间禁止确认。

最终回归与当前源码的隔离运行结果：

| 检查 | Windows | Linux |
| --- | --- | --- |
| 后端/进程/逻辑回归 178 项 | 177 通过，1 项 POSIX 专测跳过；8.769 秒 | 175 通过，3 项 Windows 专测跳过；10.708 秒 |
| scripts 9 项 | 9 项通过；0.739 秒 | 8 项通过，1 项因镜像缺 Git 跳过；0.053 秒 |
| smoke | 通过 | 通过 |

Node 前端 19 项全部通过；Compose 配置与 `git diff --check` 通过。两份 Actions 均用 `scripts/test_*.cjs` 自动覆盖全部前端回归。

当前 50 文件验收源码包 SHA-256 为 `5b7055f9f0a974bab29cc28c59f5377efa2fdd112a6bceaf11712561ad632c7e`。Linux 再次复用已有镜像、只读挂载该源码，在无网络且不挂生产数据的独立容器中完成真实工具的 1 GiB 合成 BDMV 封装：ISO 1,074,630,656 字节，`genisoimage` / `xorriso` 通过，耗时 1.57 秒，36 次容器内端点请求；最长 `/healthz` 1.35 ms、`/api/status` 5.13 ms、`/workspace` 16.01 ms。

**本轮没有重做真实 CD2 写入，也没有部署生产或发布镜像。** 生产容器仅通过只读 `docker inspect` 核对，仍为 `running` / `healthy`。上一轮的真实 CD2 上传和单 key 暂停/恢复结果仅代表上面注明的旧源码快照。本轮新增逻辑通过离线回归验证，合成 ISO 不代表媒体播放验收。

## 关键接口

```text
GET  /api/status
GET  /api/logs
GET  /api/compare
GET  /api/cd2/remote-candidates
POST /api/cd2/directories
POST /api/cd2/test
POST /api/cd2/pull
GET  /api/cd2/diagnostics
GET  /api/cd2/upload-control
POST /api/cd2/upload-control
POST /api/tasks/action
POST /api/release-calendar/refresh
POST /api/tmdb/test
GET  /api/browse?root=watch
GET  /api/file-properties
POST /api/file-actions
```

接口语义：

- `/api/status` 返回当前封装、CD2 拉取、CD2 上传、产出和文件操作摘要。
- `/api/logs` 聚合 `iso-packer.log`、内存事件、任务状态、CD2 最近事件和文件操作，供日志中心筛选展示。
- `/api/compare` 在指定成品目录内做最多两层轻量扫描，只读取 ISO/视频成品文件并返回同片分组，不触发封装、拉取或删除。
- `/api/cd2/pull` 只用于 CD2 远程候选拉取。
- `/api/tasks/action` 用于等待任务重新检测、CD2 上传完成确认，以及单任务复制/上传控制；服务端会重新读取当前队列并精确匹配任务，不接受前端直接指定成品路径。
- `/api/tasks/action` 的 `cancel_pack` 只允许取消当前正在生成 ISO 的任务，校验/转存阶段不接受该操作。
- `/api/cd2/diagnostics` 只读返回 CD2 运行信息，可用 `path` 查询参数筛选打开句柄并读取该路径的详情统计。
- `/api/cd2/upload-control` 读取已保存的全部上传暂停策略及 CD2 确认状态；POST JSON 使用 `action: pause` 或 `action: resume`，可给 `pause` 增加带时区的未来 `until`，例如 `2026-10-23T12:30:00+08:00`。
- `/api/file-actions` 承载文件浏览里的复制、移动、删除和重命名。
- 文件浏览“复制到监控目录”由 `/api/file-actions` 发起 CD2 网盘内复制任务。

## VPS 历史观察与待验收项

- 部署镜像：`ebichu/iso-packer:test`
- 端口 `15865` 报错通常是容器重建时端口释放/绑定时序问题，不代表镜像拉取失败。
- 容器曾因大文件转存到 CloudDrive2 挂载目录而进入 `unhealthy`。
- 历史排查怀疑封装/转存与 Web 同进程导致大文件 I/O 影响页面和 `/healthz`。本轮改用进程隔离后，仍需用同类实机负载复核。
- `/output` 中的 `.iso.partial` 持续增长时不要强停；它是本机封装临时文件。CD2 挂载目标目录不会再创建 `.partial` 文件。

## 正式版前计划

1. 用新构建的 `sha-<12位提交号>` 镜像完成 VPS 实机验收，并记录实际镜像 digest、提交号和时间。
2. 在线保存 TMDB Token，确认首页已交付资产海报能自动补全并缓存。
3. 验证文件浏览“复制到监控目录”确实进入 CD2 网盘内复制任务。
4. 验证封装中心能正确显示：生成 ISO、校验、转存、CD2 上传云端、已交付。
5. 大文件生成、校验、写入 CloudDrive2 时持续检查页面和 `/healthz` 响应；强制 worker 异常退出后验证状态提示、重启恢复和源文件保留。
6. 实机验证日志中心与媒体检测页，确认大目录下的扫描范围和页面响应符合预期。
7. 正式发布前再更新 Docker Hub `latest`；测试阶段继续只更新 `test`。

本地测试、模拟卡顿或接口 smoke 只证明对应验证范围，不能替代真实 CloudDrive2 上传完成和 VPS 大文件验收。本轮不创建正式 Git 标签，也不触发 `latest` 发布。

## 不应提交

- `D:\Projects\makeiso\tests\key.txt`
- `D:\Projects\makeiso\PROJECT_STAGE_SUMMARY.md`
- `D:\Projects\makeiso\v2.0-HTML\`
- 临时截图、缓存、日志和本地测试输出
