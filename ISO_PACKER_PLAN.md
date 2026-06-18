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

- 读取 CloudDrive2 API 上传、下载、复制任务
- 显示上传进度和 CD2 传输状态
- 显示 API 不可用 / 未连接状态
- 修改 CD2 API 设置后自动清理旧缓存和旧连接
- 显示最后成功刷新时间和最后错误
- 参考 SA/Symedia 的 CD2 接入模型，支持 API Token / 用户名密码两种认证方式
- API Token 模式按 `Authorization: Bearer <token>` 调用 CD2 gRPC 接口，不再把 token 当账号密码登录
- `/api/status` 不再返回 Web 密码哈希、Web secret 或 CD2 API 密钥
- 扫描 `/watch` 时会参考 CD2 下载 / 复制任务，未完成时不进入封装
- BDMV / VIDEO_TS 会先检查关键结构完整性，避免读取 CD2 写入中的半成品目录
- 识别 `.cifstmp`、`.clfstmp`、`.clfstmp.progress` 等 CD2/FUSE 临时文件，避免 `genisoimage` 抢跑

### CD2 按 SA/Symedia 模型继续收口

当前阶段 CD2 API 先作为观察层和封装门禁使用，不直接创建文件或取消任务。后续可以增加“受控自动化”模式，但定位不是把 iso-packer 做成另一个完整 CD2 控制器，而是让 iso-packer 编排一条固定流水线：发现网盘指定目录里的 BDMV / VIDEO_TS，调用 CD2 拉取到 `/watch`，确认完成后封装，再转移到固定 ISO 目标目录。CD2 接入按下面原则做：

- 认证方式明确区分：`API Token` / `用户名密码`
- API Token 模式下用户名可留空，界面不再误导成“用户名 + 密码”
- CD2 根目录和 ISO 目标目录分开展示：
  - CD2 根目录建议 `/CloudNAS/CloudDrive`
  - ISO 目标目录保持 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 增加“测试 CD2 连接 / 重新连接”能力
- CD2 状态展示认证模式、最后成功时间、最后错误、上传 / 下载 / 复制任务数量
- 错误文案区分地址不可达、认证失败、Token 权限不足、暂无上传任务
- 文档里明确 API Token 建议授予读取上传任务相关权限；个人部署可直接给全权限降低排错成本

### SA/Symedia 式 CD2 事件模型规划

后续 CD2 监控按 SA/Symedia 的模式收口：事件触发优先，轮询兜底，所有动作围绕固定个人流程做编排，不把 iso-packer 扩展成通用网盘管理器。

- 增加 CD2 Webhook / 事件通知入口，用于接收 CD2 或网盘目录变化事件；默认关闭
- Webhook 入口优先复用当前 Web 服务端口 `15865`，规划路径为 `/api/cd2/webhook`，避免额外开放端口
- Webhook 必须有共享密钥 / 签名 token / 反代鉴权 / IP 白名单之一，不允许裸奔公网
- 日志和状态接口不得输出完整 Webhook secret、CD2 API Token 或其它敏感凭据
- 事件来源需要单选：CD2 原生 webhook、SA/Symedia 事件转发、或禁用 webhook 仅轮询；不要同时开启多个事件来源
- 配置监听目录，例如 `/CloudNAS/CloudDrive/03-PT` 或 CD2 返回的网盘路径 `/115/03-PT`
- 明确路径映射：容器路径 `/CloudNAS/CloudDrive/...` 和 CD2 网盘路径 `/115/...` 需要建立别名关系，避免事件路径和本地路径误判
- Webhook 事件只触发复查，不作为“文件已完成”的证明
- 事件命中监听目录后，不立即封装，先进入“待确认”状态
- 增加延迟确认时间和稳定检查次数，默认按分钟级配置，避免 CD2 刚暴露文件/目录就触发封装
- 延迟结束后重新读取目录结构、文件树签名、CD2 下载 / 复制任务状态，连续稳定后才进入封装
- 保留轮询扫描作为兜底：Webhook 不可用或漏事件时，仍按现有 `/watch` 扫描逻辑发现任务
- 支持调用 CD2 刷新指定目录，用于事件后刷新挂载目录和目标目录状态；只刷新配置过的源目录和 ISO 目标目录，不做全盘递归刷新
- 目录刷新只代表“让 CD2 / 挂载层尽快反映变化”，不是上传 ISO，也不是强制转移
- CD2 API Token 权限需要随能力分级：只读观察阶段可低权限；刷新目录 / 事件监听阶段建议按 CD2/Symedia 口径授予足够权限，个人部署可使用全权限降低排错成本
- 上传进度展示继续读取 CD2 上传队列，并支持 CD2 网盘路径和本地挂载路径的别名匹配，例如 `/115/...` 对应 `/CloudNAS/CloudDrive/...`
- CD2 API 的写操作只允许用于网盘内移动 / 复制 / 刷新目录，不用于本地 ISO API 直传
- 本地生成的 ISO 仍通过文件系统交给 CD2 挂载目录；是否“直接封装到 CD2 目标目录 `.partial`”单独作为实验开关评估

推荐实现顺序：

1. 先完善只读能力：Webhook 接收、事件记录、目录刷新、上传队列路径别名匹配、Web 展示事件状态。
2. 再做稳定确认：事件触发后延迟确认，结合文件树稳定、临时文件识别、CD2 任务完成状态。
3. 再做半自动编排：Web 上显示候选原盘，允许手动确认拉取 / 封装。
4. 最后做全自动：在独立开关开启时，自动发现、自动拉取、自动封装、自动转移。

计划新增配置：

- `cd2_webhook_enabled`、`cd2_webhook_secret`、`cd2_webhook_event_source`
- `cd2_event_debounce_seconds`、`cd2_event_dedupe_ttl_seconds`
- `cd2_confirm_delay_seconds`、`cd2_confirm_stable_checks`
- `cd2_refresh_enabled`、`cd2_refresh_after_transfer`、`cd2_refresh_after_source_event`
- `cd2_path_aliases`，例如 `{ "local": "/CloudNAS/CloudDrive", "remote": "/115" }`
- `cd2_upload_match_mode`，优先别名匹配，再按策略决定是否允许后缀兜底
- `cd2_wait_upload_complete`，用于区分“本地已转移”和“云端已上传”

计划新增状态：

- 全局 CD2 状态：最近 webhook 事件、重复事件数量、最近刷新结果、缓存失效时间
- 单任务状态：事件来源、确认时间、确认次数、刷新结果、上传队列匹配路径
- 新增中间状态：`waiting_cd2_confirm`、`refreshing_cd2_dir`、`waiting_cd2_upload`

测试重点：

- Webhook secret 校验、重复事件去重、事件只触发复查
- 确认延迟结束后仍需经过文件树稳定和临时文件检查
- CD2 刷新目录成功 / 失败状态记录
- 本地路径和 CD2 网盘路径别名匹配，避免同名文件误匹配
- `sanitize_config` 不泄露 webhook secret 或 CD2 API Token

边界：

- 不接管用户在 CD2 里手动创建的通用任务
- 不把 webhook 事件当成文件已完成的证明，事件只能触发重新检查
- 不同时启用多个 webhook / 事件来源来处理同一目录
- 不自动删除网盘源文件
- 不改变当前状态语义前先拆清楚“本地已转移”和“云端已上传”
- 不把 TMDB、qB 深度集成、Agent / 分布式重新带回主线
- 不默认把 `genisoimage` 直接输出到 CD2 FUSE 目录，除非用户明确开启实验模式

### CD2 受控自动化规划

后续目标是把 iso-packer 从“监控本地 `/watch`”扩展为“自动拉取网盘原盘再封装”。这条能力可以控制 CD2，但只控制自己发起的下载 / 复制任务，不接管 CD2 的通用文件管理、删除、取消、移动等能力。

- 增加独立开关，默认关闭，只有明确启用后才主动调用 CD2
- 配置一个 CD2 云端源目录，例如 `115/03-PT/BDMV`
- 定期读取该目录，只挑选 BDMV / VIDEO_TS 原盘目录
- 为每个候选目录生成唯一任务指纹，避免同一个原盘被重复拉取或重复封装
- 调用 CD2 把原盘下载 / 复制到 `/watch/<片名或目录名>`
- 只跟踪 iso-packer 自己创建的 CD2 任务，外部手动任务只读观察
- 等 CD2 任务状态完成，并且本地 `/watch` 目录结构与文件树稳定后，才进入封装
- 成功封装后仍按现有流程转移到 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 首期不自动删除网盘源文件，也不自动取消用户在 CD2 里手动创建的任务

建议分三步实现：

1. 先做“远程目录只读扫描”：能在 Web 里看到指定网盘目录下有哪些 BDMV / VIDEO_TS 候选项。
2. 再做“手动拉取”：用户在 Web 点一下，让 iso-packer 调用 CD2 创建下载 / 复制任务。
3. 最后做“全自动拉取”：打开开关后自动发现、自动拉取、自动封装、自动转移。

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
- `process_item()` 启动前二次检查源目录完整性和 CD2 任务状态，发现仍在下载 / 复制则退回等待
- 手动“重新封装”同样遵守未完成下载保护

### 结构优化

- 新增 `iso-packer/core.py`
- 已把配置默认值、状态常量、路径安全、时间格式化、文件名清理、状态文案、任务耗时等纯工具逻辑从 `app.py` 拆出
- `Dockerfile` 已同步复制 `core.py`

### 测试完善

- 新增 `tests/test_core.py`
- 新增 `tests/test_app_routes.py`
- 覆盖登录回跳安全、CD2 地址归一化、路径越权判断、目录接口越权拦截、健康检查、任务耗时计算等关键边界
- 新增覆盖 CD2 临时文件、不完整 BDMV、完整 BDMV 稳定后 ready、CD2 copy/download 未完成时禁止封装

## 当前仍保留为后续优化

这些不影响当前个人使用和部署，不作为本轮阻塞项：

- 继续深拆 `process_item()`、`fetch_cd2_uploads()`、`transfer_iso_to_mount()` 等长函数
- 增加真实 `genisoimage` / `xorriso` / CD2 环境下的集成测试
- 增加更细的任务失败分类，例如空间不足、挂载不可用、校验失败、删除源文件失败等独立原因码
- 后续实现 CD2 受控自动化时，需要新增独立设置、任务状态和“只创建自己发起的任务”的边界保护

## 本轮检查结论

- 当前核心链路仍按个人 VPS + Docker + CD2 挂载方案运行
- 没有重新引入 TMDB、qB 深度集成、Agent 或分布式能力
- 本轮计划中的基础未完成项已经落地：基础结构拆分、独立自动化测试、CD2 状态增强、失败原因展示、重封装按钮状态增强

## 验证命令

```bash
python -m py_compile iso-packer/app.py iso-packer/core.py iso-packer/page.py
python -m unittest discover -s tests -v
```
