# ISO Packer v2.0 本地变更摘要

更新时间：2026-06-26

## 边界

- 只改 `D:\Projects\makeiso\v2.0`。
- `D:\Projects\makeiso` 下的 v1.19 只作为只读功能基线。
- 代码改动已按阶段提交并推送到 `origin/main`；本文件用于同步当前测试阶段摘要。
- VPS 实机测试使用 Docker Hub `ebichu/iso-packer:test`；本地预览仍默认禁止真实 CD2 拉取。

## 当前运行状态

- 本地安全预览端口：`http://127.0.0.1:15866/`
- VPS 实机测试入口：`http://your-vps-host/`
- 默认保护：
  - `ISO_PACKER_DISABLE_AUTH=1`
  - `ISO_PACKER_DISABLE_CD2_PULL=1`
  - `ISO_PACKER_DISABLE_CD2_STATUS_POLL=1`
- 本地手动真实拉取：关闭
- 本地自动真实拉取：关闭
- VPS 真实拉取：按线上配置执行

## 已完成改动

### 首页展示页

- 首页改为展示页方向，不再是纯工具入口。
- 主内容宽度放宽，减少宽屏左右留白。
- 顶部改为紧凑展示台工具栏，不再使用占空间的大口号。
- 蓝光发行日历第三版已落地：
  - Blu-ray.com 外网缓存
  - TMDB 中文名、TMDB ID、海报补全
  - 按今天日期优先显示待发售条目
  - 没有未来条目时回退最近已发售
  - 整张发行卡片新窗口打开 Blu-ray.com
  - `TMDB #id` 新窗口打开 TMDB
- 首页不展示中文校对状态、碟影/贴吧/豆瓣等维护信息。

### 封装中心

- 原“工程体检台 / 封装工作台”命名已收敛为“封装中心”。
- 主状态卡直接显示当前处于 CD2 拉取、封装、校验、转存还是收尾阶段。
- “远程候选队列”显示输入端的 CD2 可拉取原盘。
- “产出与转存”显示 ISO 生成、校验、转存结果，以及仍保留的本地文件操作。
- 后续详细日志不放在主工作台，单独规划“日志中心”。

### 文件浏览

- 文件浏览默认 `cd2` 根目录跟随设置里的网盘挂载根目录，默认 `/CloudNAS/CloudDrive`。
- 目录行可点击进入，不再需要单独“进入”按钮。
- 支持多选、右键菜单、属性面板、目录大小统计和目录选择弹层。
- “拉取到监控目录”已改为走 CD2 API 远程拉取队列，会创建 `waiting_cd2_pull` 状态。
- “复制到输出目录 / 复制到其他目录 / 移动 / 删除”保留本机文件操作语义，并受路径边界与二次确认保护。

### 设置页

当前设置页归类：

1. 本地目录
2. CD2 设置
3. 系统设置

已完成：

- 主卡片统一为展开/收起结构。
- 展开态改为中性色，不使用绿色底。
- `本地目录` 默认展开。
- `TMDB 元数据` 放入系统设置，并说明它同时服务发行日历和首页已交付资产海报。
- 上传队列匹配策略改为程序内部默认处理，不在设置页暴露给普通用户。
- `上传目录` 保持 Windows 本地路径选择语义。
- `网盘监控目录` 支持 CD2 API 远端目录浏览。
- `下载目录` 按用户要求保留该名称。
- `封装后转存到 CD2 目录` 默认开启。
- `监控 CloudDrive 上传队列` 默认开启。

### CD2 安全保护与拉取语义

- 本地预览默认禁止真实 CD2 拉取。
- 本地预览默认禁止状态页持续读取 CD2 队列。
- `/api/status` 已瘦身，只返回摘要，不返回 CD2 大列表。
- CD2 gRPC 客户端禁用 HTTP 代理，避免局域网地址被代理劫持。
- 文件浏览进入监控目录的动作统一走 CD2 API 远程拉取队列，不再做 `/CloudNAS/CloudDrive -> /watch` 本地复制。

### 发行日历和 TMDB

- 新增发行日历抓取模块：`iso-packer/release_calendar_fetcher.py`
- 新增刷新脚本：`iso-packer/scripts/update_release_calendar.py`
- 发行缓存：`iso-packer/data/release_calendar.json`
- 首页刷新接口：`POST /api/release-calendar/refresh`
- TMDB 测试接口：`POST /api/tmdb/test`
- 设置页可维护 TMDB API 域名、图片域名和 API Token。
- “测试 TMDB”只验证连通性，不保存配置；首页已交付资产海报需要保存配置或注入 `TMDB_API_KEY` / `TMDB_BEARER_TOKEN`。

### 验收脚本

- `iso-packer/scripts/smoke_v2.py` 已固化为本地门槛。
- 覆盖模板挂载、按钮类型、重复 ID、基础可访问性、设置字段、发行日历、TMDB、CD2 mock 链路和安全保护。

### 文档和启动

- 新增 `requirements.txt` 作为本地和 Docker 的统一依赖入口。
- `start-local.bat` 默认安全启动。
- `deploy.sh` 兼容 `docker-compose` 和 `docker compose`。
- `README.md` 已恢复为干净中文，并同步当前状态。
- `.gitignore` 排除预览数据、日志、缓存和临时截图。

## 验证状态

已通过：

```powershell
cd D:\Projects\makeiso\v2.0\iso-packer
python -B scripts\smoke_v2.py
python -B -m py_compile app.py core.py release_calendar_fetcher.py scripts\smoke_v2.py scripts\update_release_calendar.py
node --check static\js\shared.js
node --check static\js\index.js
node --check static\js\workspace.js
node --check static\js\files.js
node --check static\js\settings.js

cd D:\Projects\makeiso\v2.0
docker-compose config --quiet
```

运行态已确认：

- 首页、工作台、文件页、设置页返回 200。
- `/api/status` 是摘要响应。
- `/api/cd2/pull` 在本地安全预览下返回 400，不创建真实复制任务。

## 不应提交

- `iso-packer/test-output/preview-data/`
- `iso-packer/test-output/*.log`
- `__pycache__/`
- 临时截图或本地测试文件

## 最近主线提交

- `ae562b3 fix(status): show local file operations`
- `5c3e367 fix(files): route monitor pulls through cd2`

## 后续计划

1. VPS 拉取最新 `ebichu/iso-packer:test` 并重启后，确认文件浏览“拉取到监控目录”进入 CD2 远程拉取队列。
2. 在线上设置页保存 TMDB Token，确认首页已交付资产能自动补海报并缓存。
3. 继续观察封装中心在两个并发任务下的显示：一个 CD2 远程候选拉取、一个文件浏览提交的 CD2 拉取。
4. 新增独立“日志中心”，承载封装日志、CD2 拉取事件、后台文件操作事件和下载/复制失败原因。
5. 继续只更新 Docker Hub `test` 镜像；`latest` 等正式发布时再动。
