# ISO Packer v2.1.0

蓝光原盘自动封装与归档工具。v2.x 是基于 `D:\Projects\makeiso` 旧版 v1.19 的重构版本；v1.19 只作为只读验收基线，实际改动只落在 `D:\Projects\makeiso\v2.0`。

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

## 关键语义

### 本机目录

- `/watch`：本机监控目录，是封装流程的临时输入目录。
- `/output`：本机输出目录，是 ISO 生成后的临时落点。
- 本机封装时允许在 `/output` 使用 `.iso.partial`，完成并校验后才改名为 `.iso`。
- 开启 CD2 转存并等待云端完成时，本机 `/output` 里的 ISO 会保留到 CD2 API 明确报告上传完成；API 明确报告失败时保留副本供重试，API 暂时不可用或任务暂时不在列表中时继续等待。
- 如果 `/output` 中已有同名且校验通过的 ISO，会复用该文件并继续 CD2 转存，不会重复封装；CD2 上传完成只以 API 的明确完成状态为准，不用目标文件本地大小或校验结果推断。
- 如果开启成功后删除源目录，`/watch` 里的源 BDMV 也会被清理。
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
- 上传异常可以点击“重新检测”重新读取队列，也可以点击“确认已上传”。后者必须确认目标位于 CD2 成品目录、文件非空、大小符合已知目标大小且 ISO 结构校验通过。
- 源目录接收、等待下载/稳定、CD2 拉取和 CD2 确认等等待状态只计入“等待”，不计入“当前执行”；真正封装、转存和目录刷新才计入执行。
- CD2 远程候选扫描使用独立客户端和单任务 15 秒超时保护；超时不会叠加扫描线程，前端请求也会在 20 秒后结束，可稍后重新刷新。
- 名称明确包含 `BDMV` 或 `VIDEO_TS` 的远程监控根目录会一次列出全部一级候选，并按修改时间从新到旧处理；提交拉取前仍会进入选中目录复核原盘结构。通用目录继续逐层探测，任何不完整扫描都不会触发自动拉取或写入成功缓存。

### 版本感知封装

- 同一站点、同一影片且明确标注 `V1`、`V2`、`V3` 的版本，较高版本在新 ISO 校验并成功转存后会清理较低版本。
- 不同站点的发布结果始终共存；没有明确版本标记的文件也始终共存，不参与自动替换。
- 同一 CD2 远程源路径和目标目录会持久化自动/手动拉取认领，避免扫描周期重复创建相同任务；只有 API 明确失败才记录失败，API 暂时不返回任务时保持等待。
- CD2 复制或下载任务列表读取失败、不完整或客户端不支持对应查询接口时，封装流程会保持等待，不会把空队列当成没有任务。
- CD2 上传任务只按完整路径和已配置的路径别名精确匹配，不再用 basename 或路径后缀猜测不同目录的同名 ISO。
- CD2 拉取任务只依据 `GetCopyTasks` 返回的源路径、目标路径、进度和状态：活动任务继续等待，`Completed` 才完成认领，`Failed` 才记录失败；任务暂时不在列表中不会访问远端结果或本地目录来推断状态。
- 所有 CD2 网盘内复制都使用 `Rename` 冲突策略并递归处理重名，保存 API 返回的实际目标路径；不能设置安全冲突策略的客户端会被拒绝，绝不回退到覆盖模式。
- 不同远程源即使 basename 相同也会使用独立的本地拉取路径和状态记录，避免不同站点的同名作品互相覆盖。
- 文件浏览的自定义复制/移动目标只能位于本机监控、本机输出或 CD2 挂载根目录内；CD2 成品目录也必须位于配置的挂载根目录内。
- `genisoimage`、`xorriso` 和 ISO 转存分别有总时长与无进展保护，异常时保留源目录并清理未完成目标，不会无限占用当前任务。
- 封装中心在本机 ISO 正在生成时提供“取消当前封装”；取消只终止 `genisoimage`、保留源目录并按异常恢复路径处理，不会删除已存在的完整 ISO。

### CD2 推送、控制与诊断

- 服务启动后会尝试订阅官方 `PushMessage`，目录和任务变化会触发防抖复查；断线、未授权或旧服务不支持时自动保留原有轮询。
- API Token 需要 `allow_push_message` 权限才能启用实时推送；缺少该权限不会阻断封装和轮询。
- 封装中心可对当前精确匹配的单个复制任务执行暂停、继续、重启、取消，对单个上传任务执行暂停、继续、取消；不提供批量取消。
- 封装中心的“运行诊断”读取 CD2 版本、CPU/内存、缓存/临时文件计数、任务计数和打开文件句柄。单项 RPC 不可用时只显示该项错误。

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
```

含义：

- `ISO_PACKER_DISABLE_AUTH=1`：本地预览免登录。
- `ISO_PACKER_DISABLE_CD2_PULL=1`：禁止创建真实 CD2 拉取任务。
- `ISO_PACKER_DISABLE_CD2_STATUS_POLL=1`：状态页不持续读取 CD2 队列。

正式部署或真实拉取验收时，再按需移除对应保护开关。

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
python -B -m py_compile app.py core.py release_calendar_fetcher.py scripts\smoke_v2.py scripts\update_release_calendar.py
node --check static\js\shared.js
node --check static\js\index.js
node --check static\js\workspace.js
node --check static\js\files.js
node --check static\js\settings.js
node --check static\js\logs.js
node --check static\js\compare.js

cd D:\Projects\makeiso\v2.0
docker-compose config --quiet
```

GitHub Actions 在构建 Docker 镜像前会执行同一组后端单元测试、smoke、Python 编译检查和前端 JavaScript 语法检查；镜像仍只由 Actions 构建和推送。

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
- `/api/file-actions` 承载文件浏览里的复制、移动、删除和重命名。
- 文件浏览“复制到监控目录”由 `/api/file-actions` 发起 CD2 网盘内复制任务。

## VPS 实机观察

- VPS 测试入口：`http://your-vps-host/`
- 部署镜像：`ebichu/iso-packer:test`
- 端口 `15865` 报错通常是容器重建时端口释放/绑定时序问题，不代表镜像拉取失败。
- 容器曾因大文件转存到 CloudDrive2 挂载目录而进入 `unhealthy`。
- 根因是封装/转存 I/O 堵住了 Web 服务线程，导致 `/healthz` 和页面无响应。
- `/output` 中的 `.iso.partial` 持续增长时不要强停；它是本机封装临时文件。CD2 挂载目标目录不会再创建 `.partial` 文件。

## 正式版前计划

1. 拉取并运行最新 `ebichu/iso-packer:test`，完成一轮 VPS 实机验收。
2. 在线保存 TMDB Token，确认首页已交付资产海报能自动补全并缓存。
3. 验证文件浏览“复制到监控目录”确实进入 CD2 网盘内复制任务。
4. 验证封装中心能正确显示：生成 ISO、校验、转存、CD2 上传云端、已交付。
5. 修复封装/转存 worker 与 Web 服务耦合问题，避免 CloudDrive2 大文件 I/O 堵住页面和 `/healthz`。
6. 实机验证 v2.1.0 的日志中心与媒体检测页，确认大目录下的扫描范围和页面响应符合预期。
7. 正式发布前再更新 Docker Hub `latest`；测试阶段继续只更新 `test`。

## 不应提交

- `D:\Projects\makeiso\tests\key.txt`
- `D:\Projects\makeiso\PROJECT_STAGE_SUMMARY.md`
- `D:\Projects\makeiso\v2.0-HTML\`
- 临时截图、缓存、日志和本地测试输出
