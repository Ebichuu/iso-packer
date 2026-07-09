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
- 媒体检测页提供同片不同组的轻量候选分组：只按名称、年份、分辨率、来源、发布组、大小和修改时间比对，不做 BDMV 指纹。
- 设置页按“本地目录 / CD2 设置 / 系统设置”三类组织。
- Docker Hub 测试镜像使用 `ebichu/iso-packer:test`；`latest` 只在正式发布时更新。

## 关键语义

### 本机目录

- `/watch`：本机监控目录，是封装流程的临时输入目录。
- `/output`：本机输出目录，是 ISO 生成后的临时落点。
- 开启 CD2 转存后，ISO 成功写入 CD2 挂载目标目录后，本机 `/output` 里的临时 ISO 会被清理。
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
- 此时状态应显示为 `waiting_cd2_upload` / “CD2 上传云端中”。
- 如果条目已经是已交付完成态，UI 不再显示旧的上传百分比，避免出现“已交付但仍 0%/93%”的矛盾状态。

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

## 关键接口

```text
GET  /api/status
GET  /api/logs
GET  /api/compare
GET  /api/cd2/remote-candidates
POST /api/cd2/directories
POST /api/cd2/test
POST /api/cd2/pull
POST /api/release-calendar/refresh
POST /api/tmdb/test
GET  /api/browse?root=watch
GET  /api/file-properties
POST /api/file-actions
```

接口语义：

- `/api/status` 返回当前封装、CD2 拉取、CD2 上传、产出和文件操作摘要。
- `/api/logs` 聚合 `iso-packer.log`、内存事件、任务状态、CD2 最近事件和文件操作，供日志中心筛选展示。
- `/api/compare` 在指定文件浏览根目录内做最多两层轻量扫描，返回同片候选分组，不触发封装、拉取或删除。
- `/api/cd2/pull` 只用于 CD2 远程候选拉取。
- `/api/file-actions` 承载文件浏览里的复制、移动、删除和重命名。
- 文件浏览“复制到监控目录”由 `/api/file-actions` 发起 CD2 网盘内复制任务。

## VPS 实机观察

- VPS 测试入口：`http://your-vps-host/`
- 部署镜像：`ebichu/iso-packer:test`
- 端口 `15865` 报错通常是容器重建时端口释放/绑定时序问题，不代表镜像拉取失败。
- 容器曾因大文件转存到 CloudDrive2 挂载目录而进入 `unhealthy`。
- 根因是封装/转存 I/O 堵住了 Web 服务线程，导致 `/healthz` 和页面无响应。
- `.partial` 文件持续增长时不要强停；强停会清理 partial 并重新转存。

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
