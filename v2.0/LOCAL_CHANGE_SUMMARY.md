# ISO Packer v2.0 本地变更摘要

更新时间：2026-06-26

## 边界

- 只改 `D:\Projects\makeiso\v2.0`。
- `D:\Projects\makeiso` 下的 v1.19 只作为只读功能基线。
- 当前未提交、未推送。
- 真实 CD2 拉取暂停，后续单独验收。

## 当前运行状态

- 安全预览端口：`http://127.0.0.1:15866/`
- 默认保护：
  - `ISO_PACKER_DISABLE_AUTH=1`
  - `ISO_PACKER_DISABLE_CD2_PULL=1`
  - `ISO_PACKER_DISABLE_CD2_STATUS_POLL=1`
- 手动真实拉取：关闭
- 自动真实拉取：关闭
- 拉取目标目录：空

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

### 封装工作台

- 工作台改为工程体检台方向。
- 增强任务状态、CD2 候选、失败恢复和页面内反馈。
- 真实拉取未启用或被本地保护禁止时，按钮会显示明确状态。
- 清除记录能力已接回 `/api/cd2/pull-record`。

### 设置页

当前设置卡片顺序：

1. 本地目录
2. CD2 登录信息
3. CD2 转存目录
4. 高级同步参数
5. 远端候选与拉取
6. Web 登录
7. TMDB 元数据

已完成：

- 主卡片统一为展开/收起结构。
- 展开态改为中性色，不使用绿色底。
- `本地目录` 默认展开。
- `TMDB 元数据` 移到最底部。
- `路径别名 / 上传匹配模式` 不再显示给普通用户。
- `上传目录` 保持 Windows 本地路径选择语义。
- `网盘监控目录` 支持 CD2 API 远端目录浏览。
- `下载目录` 按用户要求保留该名称。
- `封装后转存到 CD2 目录` 默认开启。
- `监控 CloudDrive 上传队列` 默认开启。

### CD2 安全保护

- 本地预览默认禁止真实 CD2 拉取。
- 本地预览默认禁止状态页持续读取 CD2 队列。
- `/api/status` 已瘦身，只返回摘要，不返回 CD2 大列表。
- CD2 gRPC 客户端禁用 HTTP 代理，避免局域网地址被代理劫持。

### 发行日历和 TMDB

- 新增发行日历抓取模块：`iso-packer/release_calendar_fetcher.py`
- 新增刷新脚本：`iso-packer/scripts/update_release_calendar.py`
- 发行缓存：`iso-packer/data/release_calendar.json`
- 首页刷新接口：`POST /api/release-calendar/refresh`
- TMDB 测试接口：`POST /api/tmdb/test`
- 设置页可维护 TMDB API 域名、图片域名和 API Token。

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

## 建议提交拆分

1. `feat(ui): refine iso packer v2 dashboard and settings`
2. `feat(calendar): add blu-ray release calendar with tmdb enrichment`
3. `feat(cd2): guard real cd2 operations in local preview`
4. `test: add v2 smoke coverage for ui and cd2 safety`
5. `docs: update v2 local run and verification workflow`

## 后续计划

1. 人工预览 `http://127.0.0.1:15866/`。
2. 重点检查首页发行日历、设置页展开顺序、工作台保护状态、文件页浏览。
3. 复跑 smoke。
4. 决定是否整理本地提交。
5. 真实 CD2 拉取单独开一轮，等 NAS/CD2 I/O 稳定后再做。
