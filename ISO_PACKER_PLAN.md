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
- 最近任务和历史任务列表显示封装 / 转移 / CD2 上传进度
- 手动“重新封装”按钮
- 当前有任务运行时，重封装按钮会禁用并显示任务运行中
- 失败任务显示更明确的失败原因

### 任务状态与耗时

- 记录任务开始时间、结束时间、总耗时
- 区分封装耗时和转移耗时
- 运行中实时显示耗时
- 运行中实时显示封装进度和转移到 CD2 挂载目录的进度
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
- 已增加 `/api/cd2/webhook` 事件入口：默认关闭，启用后必须带共享密钥；事件只记录、去重、防抖并触发复查，不直接判定文件完成
- Webhook 事件命中本地候选目录后，会先进入 `waiting_cd2_confirm`，等待确认延迟 / 确认次数满足后，再继续走完整性、临时文件、CD2 下载 / 复制任务和稳定时间门禁
- 已支持 CD2 目录刷新：启用后 Webhook 事件可刷新源目录，ISO 转移完成后可刷新目标目录；刷新通过 `get_sub_files(..., force_refresh=True)` 触发，并记录成功 / 失败状态

这里的 SA/Symedia 仅指可参考的 CD2 接入 / 事件模型；当前 iso-packer 不依赖 SA/Symedia 部署，也不会默认接收 SA/Symedia 事件。

### 已落地的 CD2 基础

- 认证方式明确区分：`API Token` / `用户名密码`
- API Token 模式下用户名可留空，界面不再误导成“用户名 + 密码”
- CD2 根目录和 ISO 目标目录分开展示：
  - CD2 根目录建议 `/CloudNAS/CloudDrive`
  - ISO 目标目录保持 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 增加“测试 CD2 连接 / 重新连接”能力
- CD2 状态展示认证模式、最后成功时间、最后错误、上传 / 下载 / 复制任务数量
- 错误文案区分地址不可达、认证失败、Token 权限不足、暂无上传任务
- `cd2_path_aliases` 已支持在 Web 配置本地挂载路径与 CD2 网盘路径的映射，默认 `/CloudNAS/CloudDrive=/115`
- 上传队列匹配和下载 / 复制门禁优先使用路径别名，再保留后缀兜底兼容旧行为
- `cd2_wait_upload_complete` 已支持等待匹配到的 CD2 上传任务完成，避免把“本地已转移”误显示成“云端已上传”
- 文档里明确 API Token 建议授予读取上传任务相关权限；个人部署可直接给全权限降低排错成本

## 后续计划

### CD2 按 SA/Symedia 模型继续收口

当前已实现的 CD2 API 能力包含观察、测试连接、封装前门禁、路径别名匹配、上传完成门禁、Webhook 基础事件入口、`waiting_cd2_confirm` 延迟确认、目录刷新、远程目录扫描、手动拉取和自动拉取基础能力。

### SA/Symedia 式 CD2 监控与门禁

后续按 SA/Symedia 的思路收口：事件触发优先，轮询兜底，CD2 API 用来读取队列、刷新目录、判断下载 / 复制 / 上传状态，并在开启自动化后创建 iso-packer 自己的拉取任务。它可以控制 CD2，但控制范围只服务固定个人流水线，不做通用网盘管理。

SA 式判定核心不是“看到目录就开工”，而是多路确认：

1. 事件或轮询发现候选目录。
2. 查询 CD2 下载 / 复制任务，确认源目录没有正在写入。
3. 刷新指定目录，让挂载层尽快反映最新状态。
4. 检查本地挂载里的 `BDMV` / `VIDEO_TS` 结构是否完整。
5. 检查 `.cifstmp`、`.clfstmp`、`.partial` 等临时文件是否消失。
6. 对文件树签名连续确认 N 次稳定。
7. 进入封装，完成后把 ISO 交给 CD2 目标挂载目录。
8. 如果开启上传完成门禁，再读取 CD2 上传队列；只有匹配到目标 ISO 的上传任务并确认完成或队列清理后，才把任务显示为最终完成。

事件入口与安全：

- 已增加 CD2 Webhook / 事件通知入口，用于接收 CD2 或目录变化事件；默认关闭
- Webhook 入口复用当前 Web 服务端口 `15865`，路径为 `/api/cd2/webhook`
- Webhook 必须有共享密钥，不允许裸奔公网
- 日志和状态接口不得输出完整 Webhook secret、CD2 API Token 或其它敏感凭据
- 事件来源单选：CD2 原生 webhook、SA/Symedia 事件转发、或禁用 webhook 仅轮询；不要同时开启多个事件来源处理同一目录
- Webhook 事件只触发复查，不作为“文件已完成”的证明
- 已实现：事件命中监听目录后，任务进入 `waiting_cd2_confirm`，不立即封装

路径和目录：

- 配置 CD2 云端源目录，例如 `/115/03-PT`，用于发现远程原盘候选
- 配置本地拉取目录，保持 `/watch`
- 配置 CD2 拉取目标目录，建议指向 `/watch` 对应的网盘路径；如果留空，则通过路径别名把本地拉取目录转换为 CD2 网盘路径
- 配置 ISO 目标目录，保持 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 明确路径映射：容器路径 `/CloudNAS/CloudDrive/...` 和 CD2 网盘路径 `/115/...` 建立别名关系
- 上传进度展示继续读取 CD2 上传队列，并优先用路径别名匹配，例如 `/115/...` 对应 `/CloudNAS/CloudDrive/...`
- 已支持配置上传队列匹配策略：默认兼容旧逻辑，优先路径别名匹配并允许同名后缀兜底；严格模式只允许路径别名 / 完整路径匹配，避免同名文件误匹配

CD2 控制边界：

- 已允许调用 CD2 刷新指定目录，用于事件后刷新源目录和 ISO 目标目录状态
- 允许在手动 / 自动拉取开启后创建下载 / 复制任务，把指定网盘原盘拉取到 `/watch`
- 只跟踪 iso-packer 自己创建的 CD2 任务，外部手动任务保持只读观察
- 未来如启用受控自动化，CD2 API 写操作只允许服务于 iso-packer 自己发起的固定流水线，例如创建自己的下载 / 复制任务、刷新配置过的目录
- 不提供通用网盘文件管理，不接管用户手动任务，也不用于本地 ISO API 直传
- 不通过 CD2 API 直传本地 ISO，本地生成的 ISO 仍通过文件系统交给 CD2 挂载目录
- 不自动删除网盘源文件，不自动取消用户在 CD2 里手动创建的任务
- 是否“直接封装到 CD2 目标目录 `.partial`”单独作为实验开关评估，默认不启用

推荐实现顺序：

1. 已完成：路径别名配置化，`/CloudNAS/CloudDrive` 和 `/115` 可在 Web 配置，并统一用于上传队列匹配、下载 / 复制门禁。
2. 已完成：增加 CD2 事件入口，Webhook 鉴权、事件记录、去重、防抖，只触发复查，不直接改 ready。
3. 已完成：增加 `waiting_cd2_confirm`：事件触发后延迟确认，结合文件树稳定、临时文件识别、原盘结构检查、CD2 下载 / 复制任务状态。
4. 已完成：上传完成门禁，`cd2_wait_upload_complete` 开启时，`transfer_done` 之前进入 `waiting_cd2_upload`，等待匹配到的 CD2 上传任务完成；未匹配到队列时保持等待并提示检查路径别名或 CD2 上传状态。
5. 已完成：CD2 目录刷新基础能力，Webhook 后刷新源目录，转移后刷新目标目录，并记录刷新结果。
6. 已完成：增加远程目录扫描，Web 里能看到指定 CD2 云端源目录下的 BDMV / VIDEO_TS 候选；默认只读展示。
7. 已完成：增加手动拉取，用户点选候选后，由 iso-packer 调用 CD2 `copy_file` 创建复制任务；任务进入 `waiting_cd2_pull`，继续由现有 `/watch` 扫描、完整性门禁和稳定性门禁接管。
8. 已完成：增加自动拉取基础能力。独立开关开启时，扫描周期自动发现候选并每轮最多创建 1 个 CD2 `copy_file` 任务；拉取完成后仍由现有 `/watch` 扫描、完整性门禁、稳定性门禁、封装和转移流程接管。

计划新增配置：

- 已新增：`cd2_webhook_enabled`、`cd2_webhook_secret`、`cd2_event_source`
- 已新增：`cd2_event_debounce_seconds`、`cd2_event_dedupe_ttl_seconds`
- 已新增：`cd2_confirm_delay_seconds`、`cd2_confirm_stable_checks`
- 已新增：`cd2_refresh_enabled`、`cd2_refresh_after_transfer`、`cd2_refresh_after_source_event`
- 已新增：`cd2_path_aliases`，例如 `{ "local": "/CloudNAS/CloudDrive", "remote": "/115" }`
- 已新增：`cd2_upload_match_mode`，优先别名匹配，再决定是否允许后缀兜底
- 已新增：`cd2_wait_upload_complete`，用于区分“本地已转移”和“云端已上传”
- 已新增：`cd2_remote_source_dirs`，用于配置网盘原盘来源目录；默认只读扫描远程 BDMV / VIDEO_TS 候选，手动 / 自动拉取由独立开关控制
- 已新增：`cd2_manual_pull_enabled`
- 已新增：`cd2_auto_pull_enabled`
- 已新增：`cd2_local_pull_dir`，默认 `/watch`
- 已新增：`cd2_remote_pull_dest_dir`，用于指定 CD2 拉取目标目录；留空时走路径别名转换

计划新增状态：

- 已新增全局 CD2 Webhook 状态：最近 webhook 事件、重复事件数量、防抖数量、最近触发复查时间
- 已新增全局 CD2 刷新状态：最近刷新结果、最近 20 次刷新结果
- 仍待新增全局 CD2 缓存状态：缓存失效时间
- 已新增单任务 CD2 确认状态：事件指纹、事件路径、确认开始 / 完成时间、确认次数
- 已新增单任务拉取状态：远程源路径、本地目标路径、CD2 创建时间、最近结果、是否已看到 CD2 copy 队列、完成时间
- 已新增全局自动拉取状态：最近一次自动扫描结果、候选数量、已创建任务或跳过原因
- 已新增远程候选拉取状态：新候选、拉取中、已处理、失败、最近失败，并在 Web 远程候选表格展示
- 已新增中间状态：`waiting_cd2_confirm`
- 已新增中间状态：`waiting_cd2_pull`
- 已新增中间状态：`refreshing_cd2_dir`

测试重点：

- 已覆盖：Webhook secret 校验、重复事件去重、事件只触发复查
- 已覆盖：确认延迟结束后仍需经过文件树稳定、临时文件检查和 CD2 任务状态门禁
- 已覆盖：CD2 刷新目录成功 / 失败状态记录、路径别名转换、Webhook 后刷新源目录、转移后刷新目标目录
- 已覆盖：手动拉取开关、源目录越权拦截、CD2 copy 任务创建、拉取进度优先显示为 `waiting_cd2_pull`
- 已覆盖：自动拉取默认关闭、缺目标目录时不扫描、每轮只创建 1 个任务、已有同源记录时不重复创建
- 已覆盖：远程候选列表展示拉取状态，避免只能从自动拉取跳过文案推断原因
- 已覆盖：本地路径和 CD2 网盘路径别名匹配，以及严格上传匹配模式下避免同名文件误匹配
- 上传完成门禁不会把“本地已转移”或“未匹配到上传队列”误显示成“云端已上传”
- 自动拉取只跟踪自己创建的 CD2 任务，不接管外部手动任务；默认关闭，开启后每轮最多创建 1 个任务
- `sanitize_config` 不泄露 webhook secret 或 CD2 API Token

边界：

- CD2 可以被 iso-packer 控制，但只控制配置目录和自己创建的任务
- 不把 webhook 事件当成文件已完成的证明，事件只能触发重新检查
- 不同时启用多个 webhook / 事件来源处理同一目录
- 不自动删除网盘源文件
- 不把 TMDB、qB 深度集成、Agent / 分布式重新带回主线
- 不默认把 `genisoimage` 直接输出到 CD2 FUSE 目录，除非用户明确开启实验模式

### CD2 受控自动化目标

最终目标是把 iso-packer 从“只监控本地 `/watch`”扩展为“观察网盘源目录，自动拉取原盘，确认完成后封装，再交给 CD2 上传”。这条自动化按阶段开放，每一步都可以单独关闭：

1. 远程目录观察：只读展示 CD2 云端源目录里的原盘候选。
2. 手动拉取：用户点选候选，iso-packer 创建自己的 CD2 下载 / 复制任务。
3. 自动拉取：打开独立开关后自动发现候选并创建任务。
4. 自动封装：拉取完成并稳定后进入现有封装流程。
5. 上传观察：ISO 写入目标目录后，继续显示并可等待 CD2 上传完成。

### 目录观察

- 只读浏览 `watch` / `output` / `cd2`
- 显示文件名、类型、大小、修改时间
- 支持进入子目录
- 支持返回上级和刷新
- 限制在允许根目录范围内浏览

## 已完成的稳定性与结构改造

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
- 继续细化 CD2 自动拉取，例如手动清除同源记录后重拉、远程候选跳过原因分组过滤

## 本轮检查结论

- 当前核心链路仍按个人 VPS + Docker + CD2 挂载方案运行
- 没有重新引入 TMDB、qB 深度集成、Agent 或分布式能力
- 本轮计划中的基础项已经落地：基础结构拆分、独立自动化测试、CD2 状态增强、失败原因展示、重封装按钮状态增强、任务列表行内进度展示、CD2 Webhook 基础事件入口、`waiting_cd2_confirm` 延迟确认门禁、CD2 目录刷新、远程候选扫描、CD2 手动拉取、CD2 自动拉取基础能力、远程候选拉取状态展示

## 验证命令

```bash
python -m py_compile iso-packer/app.py iso-packer/core.py iso-packer/page.py
python -m unittest discover -s tests -v
```
