# CloudDrive2 集成说明

当前项目和 CloudDrive2 的关系很明确：

- 真正的文件转移依旧走文件系统
- CD2 API 只用于观察上传进度和测试连接
- 默认目标目录是 `/CloudNAS/CloudDrive/00-未整理/00-mkiso`

也就是说，当前主线不是“通过 API 直传到网盘”，而是：

```text
/output -> /CloudNAS/CloudDrive/00-未整理/00-mkiso -> CD2 后台继续上传
```

## 1. 为什么还需要 `/CloudNAS:/CloudNAS:rslave`

因为 CD2 的挂载点通常是动态出现在 `/CloudNAS` 下的。`iso-packer` 想在容器里看到这些目录，就要接收挂载传播。

推荐挂载：

```yaml
volumes:
  - /CloudNAS:/CloudNAS:rslave
```

不要只挂载子目录来赌运气，父目录更稳。

## 2. iso-packer 侧推荐配置

```yaml
services:
  iso-packer:
    image: ebichu/iso-packer:latest
    container_name: iso-packer
    restart: unless-stopped

    ports:
      - "15865:15865"

    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1

    volumes:
      - ./data:/data
      - /mnt/115Download:/watch
      - /mnt/iso-output:/output
      - /CloudNAS:/CloudNAS:rslave

    network_mode: bridge

    extra_hosts:
      - "host.docker.internal:host-gateway"
```

这里的 `extra_hosts` 是为了访问宿主机上的 CD2 API。

## 3. 如果你自己也管 CD2 容器

CD2 那边通常需要确保宿主机上的 `/CloudNAS` 是共享传播来源。常见做法是：

```yaml
volumes:
  - /CloudNAS:/CloudNAS:shared
```

`iso-packer` 再通过 `:rslave` 接收这层传播。

如果你的 CD2 已经正常工作，并且宿主机能看到 `/CloudNAS/CloudDrive`，那 `iso-packer` 这边通常只需要按当前文档挂载就行，不一定要重做整套 CD2 部署。

## 4. Web 设置页怎么填

基础设置建议：

```text
CD2 挂载根目录: /CloudNAS
CD2 目标目录: /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

如果要显示上传进度，再额外填写：

```text
启用 CD2 API: 开
CD2 API 地址: host.docker.internal:19798
CD2 API 用户名: 你的 CD2 用户名
CD2 API 密码: 你的 CD2 密码
轮询秒数: 10
```

再强调一次：这里不是 API 直传，只是读取上传队列。

## 5. 现在能看到哪些 CD2 信息

启用 CD2 API 后，Web 界面会展示：

- 当前上传任务数
- 每个任务的目标路径
- 已上传大小 / 总大小
- 上传百分比
- 上传状态

同时，你还可以直接在“目录观察”里看：

- `watch`
- `output`
- `cd2`

这样比反复进 CD2 容器里看更方便。

## 6. 验证方法

先看健康检查：

```bash
curl http://127.0.0.1:15865/healthz
```

再确认容器里能看到目标路径：

```bash
docker exec -it iso-packer ls -la /CloudNAS
docker exec -it iso-packer ls -la /CloudNAS/CloudDrive
docker exec -it iso-packer ls -la /CloudNAS/CloudDrive/00-未整理/00-mkiso
```

如果启用了 CD2 API，再去 Web 看上传进度区是否有返回。

## 7. 常见问题

### 为什么不用 CD2 API 直接创建文件上传

因为你现在的实际使用方式已经固定，文件路径也固定，走文件系统移动更直接，项目也更轻。CD2 API 只拿来做观察层正好够用。

### 为什么 API 地址建议写 `host.docker.internal`

因为当前 `iso-packer` 通常跑在 bridge 网络里，而 CD2 往往跑在宿主机或 host 网络里。这个地址配合：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

在 Linux 环境里比较省事。

### 为什么目录观察和 API 都保留

因为两者解决的问题不一样：

- 目录观察：看文件有没有真的落到目标路径
- CD2 API：看后台上传队列有没有在跑

两者一起用，排查会顺手很多。

## 8. 参考

- [Symedia CloudDrive2 插件文档](https://wiki.viplee.cc/symedia_config/plugin/cd2/)
- [CloudDrive2 官方站点](https://www.clouddrive2.com/)
