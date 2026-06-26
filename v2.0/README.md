# ISO Packer v2.0

蓝光原盘自动封装与本地归档工具。当前版本是基于 `D:\Projects\makeiso` 下 v1.19 的 UI 重构版，v1.19 只作为只读功能基线，实际改动只落在本目录。

## 当前状态

- 首页已改为展示页方向，重点展示已交付原盘资产、运行摘要、蓝光发行日历和主要入口；已交付资产海报依赖已保存的 TMDB 配置或环境变量。
- 封装入口统一命名为“封装中心”，主任务是快速判断当前处于 CD2 拉取、封装、校验、转存还是收尾阶段。
- 封装中心包含“远程候选队列”和“产出与转存”两侧：候选队列看输入端，产出面板看 ISO 生成、校验、转存和本地文件操作。
- 文件浏览支持多选、属性面板、右键菜单和目录选择器；“拉取到监控目录”走 CD2 API 远程拉取队列，复制到输出目录/其他目录仍是本机文件操作。
- 设置页按三类归纳：本地目录、CD2 设置、系统设置；TMDB 元数据放在系统设置内。
- 本地预览默认启用安全保护：免登录、禁止真实 CD2 拉取、禁止状态页持续读取 CD2 队列。

## 蓝光发行日历

首页发行日历已接入第三版数据结构：

- `Blu-ray.com` 作为基础发行源。
- `TMDB` 用于补中文名、TMDB ID 和海报。
- 碟影、贴吧、豆瓣只作为数据层人工校对参考，不在首页卡片露出。
- 展示窗口按今天日期起算，优先显示今天及之后的待发售条目；如果缓存里没有未来条目，才回退显示最近已发售。
- 发行卡片点击会新开窗口跳转 Blu-ray.com 影片页。
- `TMDB #id` 徽标点击会新开窗口跳转对应 TMDB 影片页。

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

TMDB 配置入口在“系统设置 -> TMDB 元数据”。填写 API 域名、图片域名和 API Token 后，可先点击“测试 TMDB”验证连通性；测试不会保存配置，必须点击“安全保存配置”后，发行日历和首页已交付资产海报才会使用该配置。

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

当前安全预览端口：

```text
http://127.0.0.1:15866/
```

正式部署或真实拉取验收时，再按需移除对应保护开关。

## 本地验收

核心 smoke：

```powershell
cd D:\Projects\makeiso\v2.0\iso-packer
python -B scripts\smoke_v2.py
```

该脚本使用临时 `DATA_DIR` 和模拟 CD2 客户端，覆盖：

- 首页、工作台、文件页、设置页渲染
- 模板挂载点
- 按钮类型
- 重复 ID
- 基础可访问性
- 设置字段契约
- 目录选择接口
- CD2 测试、候选扫描、mock 拉取契约
- 发行日历、TMDB、点击链接和日期窗口
- 本地真实拉取保护

完整提交前检查建议：

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

## 运行方式

### Docker

```bash
cd v2.0
./deploy.sh
```

访问：

```text
http://localhost:15866
```

### 本地 Python

```powershell
cd D:\Projects\makeiso\v2.0
pip install -r requirements.txt
cd iso-packer
python app.py
```

默认端口：

```text
http://localhost:15865
```

## 关键接口

```text
GET  /api/status
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

本地预览默认保护下，`/api/cd2/pull` 只验证保护逻辑，不会创建真实 CD2 拉取任务。文件浏览的“拉取到监控目录”复用 CD2 拉取队列；复制到输出目录/其他目录仍由 `/api/file-actions` 作为本地文件操作处理。

## 不应提交

`.gitignore` 已排除：

- `iso-packer/test-output/preview-data/`
- `iso-packer/test-output/*.log`
- `__pycache__/`
- 临时截图和本地测试文件

## 本地变更摘要

当前本地变更摘要见：

```text
LOCAL_CHANGE_SUMMARY.md
```

建议先人工预览 UI，再按摘要决定是否整理本地提交。默认不执行 `git push`。

## 后续计划

1. 部署 `ebichu/iso-packer:test` 到 VPS 后，实机确认“拉取到监控目录”会进入 CD2 远程拉取队列。
2. 在设置页保存 TMDB Token 后，确认首页已交付资产能自动补海报并写入本地缓存。
3. 继续优化“封装中心”的状态可读性，保持主页面只回答当前阶段、进度和产物位置。
4. 新增独立“日志中心”入口，用于查看封装日志、CD2 拉取记录和后台任务事件，不再把详细日志塞进封装中心。
5. 保持 Docker Hub `test` 镜像用于实机测试；`latest` 只在正式发布时更新。

## 备注

- 当前仓库尚未补正式 `LICENSE`。
- 对外发布前需要补运维说明、API 契约和变更记录。
