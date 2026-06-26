# ISO Packer v2.0

蓝光原盘自动封装与本地归档工具。当前版本是基于 `D:\Projects\makeiso` 下 v1.19 的 UI 重构版，v1.19 只作为只读功能基线，实际改动只落在本目录。

## 当前状态

- 首页已改为展示页方向，重点展示归档成果、运行摘要、蓝光发行日历和主要入口。
- 封装工作台已改为工程体检台，聚焦任务状态、CD2 候选、失败恢复和操作反馈。
- 设置页主卡片统一支持展开/收起，顺序为：
  1. 本地目录
  2. CD2 登录信息
  3. CD2 转存目录
  4. 高级同步参数
  5. 远端候选与拉取
  6. Web 登录
  7. TMDB 元数据
- 本地预览默认启用安全保护：免登录、禁止真实 CD2 拉取、禁止状态页持续读取 CD2 队列。
- 真实 CD2 拉取暂缓，后续单独开一轮验收。

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

TMDB 配置入口在“系统设置 -> TMDB 元数据”。填写 API 域名、图片域名和 API Token 后，可先点击“测试 TMDB”，再刷新外网缓存。

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
- `ISO_PACKER_DISABLE_CD2_PULL=1`：禁止创建真实 CD2 拉取/复制任务。
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
```

本地预览默认保护下，`/api/cd2/pull` 只验证保护逻辑，不会创建真实 CD2 复制任务。

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

1. 人工看一遍安全预览 UI：首页、设置页、工作台、文件页。
2. 复跑本地 smoke 和脚本检查。
3. 按 `LOCAL_CHANGE_SUMMARY.md` 整理本地提交说明。
4. 真实 CD2 拉取单独开一轮，确认 NAS/CD2 I/O 稳定后再做。

## 备注

- 当前仓库尚未补正式 `LICENSE`。
- 对外发布前需要补运维说明、API 契约和变更记录。
