# ISO Packer 当前计划状态

## 基线

- 主线版本：`ebichu/iso-packer:latest`
- 使用方式：单 VPS、单容器、个人自用
- 固定流程：

```text
/watch -> /output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

## 已完成

### 核心封装链路

- 识别 `BDMV` / `VIDEO_TS` 原盘目录
- 使用 `genisoimage` 打包 ISO
- 使用 `xorriso` 做封装后校验
- 成功后把 ISO 从 `/output` 转移到 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`

### Web 管理界面

- Web 登录保护
- 首次进入自动要求设置密码
- 首页状态总览
- 最近任务列表
- 历史任务列表
- 手动“重新封装”按钮
- 当前有任务运行时，重封装按钮会禁用并显示任务运行中
- 失败任务显示更明确的失败原因

### 任务状态与耗时

- 记录任务开始时间、结束时间、总耗时
- 区分封装耗时和转移耗时
- 运行中实时显示耗时
- 历史任务显示固定耗时
- 任务异常时会写入失败原因

### CD2 观察能力

- 读取 CloudDrive2 API 上传队列
- 显示上传进度
- 显示 API 不可用 / 未连接状态
- 修改 CD2 API 设置后自动清理旧缓存和旧连接
- 显示最后成功刷新时间和最后错误
- 参考 SA/Symedia 的 CD2 接入模型，支持 API Token / 用户名密码两种认证方式
- API Token 模式按 `Authorization: Bearer <token>` 调用 CD2 gRPC 接口，不再把 token 当账号密码登录
- `/api/status` 不再返回 Web 密码哈希、Web secret 或 CD2 API 密钥

### CD2 按 SA/Symedia 模型继续收口

当前项目只需要 CD2 观察层，不使用 CD2 API 直传文件。后续 CD2 接入按下面原则做：

- 认证方式明确区分：`API Token` / `用户名密码`
- API Token 模式下用户名可留空，界面不再误导成“用户名 + 密码”
- CD2 根目录和 ISO 目标目录分开展示：
  - CD2 根目录建议 `/CloudNAS/CloudDrive`
  - ISO 目标目录保持 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 增加“测试 CD2 连接 / 重新连接”能力
- CD2 状态展示认证模式、最后成功时间、最后错误和上传任务数量
- 错误文案区分地址不可达、认证失败、Token 权限不足、暂无上传任务
- 文档里明确 API Token 建议授予读取上传任务相关权限；个人部署可直接给全权限降低排错成本

### 目录观察

- 只读浏览 `watch` / `output` / `cd2`
- 显示文件名、类型、大小、修改时间
- 支持进入子目录
- 支持返回上级和刷新
- 限制在允许根目录范围内浏览

### 稳定性修复

- worker 只启动一次，避免重复起扫描线程
- `config.json` / `state.json` 使用原子写入
- 登录跳转 `next` 只允许站内路径
- 登录成功后保留原始回跳路径
- 目录选择器和目录浏览器限制越权访问
- 根目录“返回上级”不再触发 403
- 扫描逻辑统一使用当前配置，不再中途重新取 `output_dir`
- 中断恢复不再误改已终态任务
- `process_item()` 启动前先 claim `active`，避免重复起任务
- `process_item()` 增加异常兜底，避免异常后 `active` 卡死

### 结构优化

- 新增 `iso-packer/core.py`
- 已把配置默认值、状态常量、路径安全、时间格式化、文件名清理、状态文案、任务耗时等纯工具逻辑从 `app.py` 拆出
- `Dockerfile` 已同步复制 `core.py`

### 测试完善

- 新增 `tests/test_core.py`
- 新增 `tests/test_app_routes.py`
- 覆盖登录回跳安全、CD2 地址归一化、路径越权判断、目录接口越权拦截、健康检查、任务耗时计算等关键边界

## 当前仍保留为后续优化

这些不影响当前个人使用和部署，不作为本轮阻塞项：

- 继续深拆 `process_item()`、`fetch_cd2_uploads()`、`transfer_iso_to_mount()` 等长函数
- 增加真实 `genisoimage` / `xorriso` / CD2 环境下的集成测试
- 增加更细的任务失败分类，例如空间不足、挂载不可用、校验失败、删除源文件失败等独立原因码

## 本轮检查结论

- 当前核心链路仍按个人 VPS + Docker + CD2 挂载方案运行
- 没有重新引入 TMDB、qB 深度集成、Agent 或分布式能力
- 本轮计划中的基础未完成项已经落地：基础结构拆分、独立自动化测试、CD2 状态增强、失败原因展示、重封装按钮状态增强

## 验证命令

```bash
python -m py_compile iso-packer/app.py iso-packer/core.py iso-packer/page.py
python -m unittest discover -s tests -v
```
