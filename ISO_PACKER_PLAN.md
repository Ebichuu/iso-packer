# ISO Packer 基础增强计划

## 目标

以当前 `ebichu/iso-packer:latest` 这一条轻量版本为唯一基线，继续保留现在的单 VPS 固定流程：

```text
/watch -> /output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

本次计划只补个人使用最需要的基础能力：

- 登录保护
- 任务耗时
- CD2 上传进度观察
- 目录观察

同时保持 Docker Compose 尽量简单，不强制通过环境变量配置，只做封装、转移和观察。

## 计划内容

### 1. 登录保护

- 增加简单的 Web 密码登录
- 默认保护首页、设置页、重封装接口、状态接口、目录观察接口
- 首次启动如果还没有密码，引导用户先完成首次设置
- 密码优先保存到 `/data/config.json`
- 健康检查接口 `/healthz` 单独放行

### 2. 任务耗时

- 记录每个任务的开始、结束和总耗时
- 区分封装耗时和转移耗时
- 运行中的任务显示实时耗时
- 历史任务显示固定耗时

### 3. CD2 上传进度观察

- 保留现有固定流程：`/watch -> /output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 接入 CloudDrive2 API，只用于读取上传队列和展示进度
- 不做 API 直传，也不替代文件系统移动
- API 不可用时，只提示未连接或未找到任务，不影响封装和转移

### 4. 目录观察

- 增加只读目录观察区域
- 支持三个入口：`/watch`、`/output`、`/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- 显示文件名、类型、大小、修改时间、当前路径
- 支持返回上级和刷新
- 只允许浏览配置内的根目录及其子目录

## 封装系统现状

当前封装系统整体没有大问题，核心链路是：

- 识别 `BDMV` / `VIDEO_TS` 原盘结构
- 使用 `genisoimage -iso-level 3 -udf -allow-limited-size`
- 用 `xorriso` 校验 ISO

所以：

- 双层盘、三层盘、UHD 原盘都可以按原样打包
- Dolby Vision、Atmos 等音视频内容不会被重新编码
- 只要原盘目录结构完整，就能正常封装

需要注意：

- 只处理原盘目录，不处理普通单文件视频
- `/output` 需要足够临时空间
- 封装完成后再交给 CD2 挂载目录和后台上传

## 接口与配置

- 增加登录相关页面和接口
- 扩展状态接口，返回任务耗时和 CD2 上传观察状态
- 增加目录浏览接口，只访问 `/watch`、`/output`、`/CloudNAS/CloudDrive/00-未整理/00-mkiso`
- CD2 API 地址、账号等配置放到 Web 设置页里
- Docker Compose 只保留必要挂载和最小网络说明

## 测试重点

- 未完成首次设置时访问首页会进入设置流程
- 完成登录后，首页、设置、重封装、状态刷新、目录观察都正常
- 任务运行时能看到耗时递增，完成后显示固定耗时
- 目录观察只能访问三个根目录及其子目录
- CD2 API 可用时能显示真实上传进度
- CD2 API 不可用时不影响封装和文件移动
- 大体积原盘、BDMV 结构、4 GB 以上文件都能正常封装和校验

## 默认假设

- 主流程固定为 `/watch -> /output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso`
- CD2 API 只用于看上传进度和测试连接
- SA / Symedia 继续负责观影入库、刮削和媒体库流程
- 当前项目继续以 `ebichu/iso-packer:latest` 为唯一主线

## 参考

- [CloudDrive.proto](https://raw.githubusercontent.com/ge-fei-fan/clouddrive2api/master/clouddrive/CloudDrive.proto)
- [Symedia CloudDrive2 插件文档](https://wiki.viplee.cc/symedia_config/plugin/cd2/)
