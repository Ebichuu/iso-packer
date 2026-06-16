# ISO Packer V2 更新日志

更新日期：2026-06-16

## 主要变化

### 1. 移除 115 网盘上传功能
- 删除了所有 `upload_115_*` 相关配置项
- 移除了 `sanitize_115_result()` 函数
- 移除了 `update_upload_progress()` 函数
- 移除了 `handle_115_event()` 函数
- 移除了 `upload_iso_to_115()` 函数
- 移除了 115 上传相关的状态标签（uploading、upload_done、upload_failed）

### 2. 简化默认配置
- `DEFAULT_CONFIG` 移除了所有 115 相关配置
- 为 `watch_dir` 和 `output_dir` 提供了默认路径（/root/iso-watch 和 /root/iso-output）
- `enabled` 默认改为 `True`
- `delete_source_after_success` 默认改为 `True`
- CD2 相关路径提供了默认值 `/mnt/cd2`

### 3. 新增目录浏览 API
- 新增 `/api/directories` 端点
- 支持通过 `path` 参数浏览文件系统目录
- 返回当前目录、父目录和子目录列表
- 仅返回可读的目录项

### 4. 简化 API 响应
- `/api/status` 不再需要过滤 cookie 信息（因为移除了 115 功能）
- 简化了状态响应逻辑

### 5. 前端界面优化（page.py）
- 文件行数从 1142 行增加到 1529 行
- 可能包含了更好的目录选择器 UI
- 优化了界面布局和交互

## 影响范围

### 配置文件兼容性
- 旧的 `config.json` 文件仍然兼容
- 115 相关配置项会被忽略
- 建议删除或重置配置文件以使用新的默认值

### 工作流程变化
ISO 封装完成后的流程变为：
1. 封装 ISO（packing）
2. 验证 ISO（validation）
3. 可选：转移到 CloudDrive2（如果启用）
4. 可选：删除源文件（如果启用）

不再支持上传到 115 网盘。

## 迁移建议

如果你之前使用了 115 上传功能：
1. 考虑使用 CloudDrive2 挂载 115 网盘
2. 启用 `cd2_transfer_enabled` 并配置 CD2 挂载路径
3. 这样可以间接实现上传到 115 的效果

## 技术细节

### 移除的函数
- `sanitize_115_result(raw: str) -> str`
- `update_upload_progress(target: Path, payload: Dict) -> None`
- `handle_115_event(target: Path, payload: Dict) -> Optional[Dict]`
- `upload_iso_to_115(target: Path, cfg: Dict) -> bool`

### 新增的端点
- `GET /api/directories?path=/some/path` - 浏览目录结构

### 状态变化
移除的状态：
- `uploading` - 正在上传
- `upload_done` - 115上传完成
- `upload_failed` - 115上传失败

保留的状态：
- `watching` - 监控中
- `receiving` - 接收中
- `waiting_stable` - 等待稳定
- `waiting_partial` - 等待下载完成
- `ready` - 准备打包
- `running` - 正在封装
- `done` - 已完成
- `failed` - 失败
- `verify_failed` - 验证失败
- `transferring` - 正在移动到 CD2
- `transfer_done` - 已移动到 CD2
- `transfer_failed` - 转移失败
- `removed` - 源已移除
