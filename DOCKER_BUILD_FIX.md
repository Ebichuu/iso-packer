# 🔧 Docker Hub 认证失败修复指南

## 问题症状

```
Error: Error response from daemon: Get "https://registry-1.docker.io/v2/": 
unauthorized: incorrect username or password
```

---

## 🎯 解决步骤

### 步骤 1: 验证 Docker Hub Token

1. **访问 Docker Hub**：https://hub.docker.com/settings/security

2. **检查 Token 状态**：
   - 找到您创建的 Token
   - 确认状态为 **Active**（未过期）
   - 确认权限包含 **Read, Write, Delete**

3. **如果 Token 无效，重新生成**：
   - 点击 "New Access Token"
   - Name: `github-actions-iso-packer`
   - Permissions: **Read, Write, Delete**
   - 点击 "Generate"
   - **立即复制 Token**（只显示一次）

---

### 步骤 2: 更新 GitHub Secrets

访问：https://github.com/Ebichuu/iso-packer/settings/secrets/actions

#### 更新 DOCKERHUB_USERNAME

1. 找到 `DOCKERHUB_USERNAME`
2. 点击右侧的 "Update" 按钮
3. 在 "Value" 框中输入：`ebichu`（必须全小写）
4. 点击 "Update secret"

#### 更新 DOCKERHUB_TOKEN

1. 找到 `DOCKERHUB_TOKEN`
2. 点击右侧的 "Update" 按钮
3. 在 "Value" 框中粘贴新的 Token
4. 点击 "Update secret"

**⚠️ 重要提示**：
- 用户名必须是 `ebichu`（全小写）
- Token 前后不能有空格
- 确保复制完整的 Token

---

### 步骤 3: 重新触发构建

更新 Secrets 后，重新触发构建：

#### 方法 1: 手动触发

1. 访问：https://github.com/Ebichuu/iso-packer/actions
2. 点击左侧 "Build and Push Docker Image"
3. 点击右上角 "Run workflow"
4. 选择 "main" 分支
5. 点击 "Run workflow"

#### 方法 2: 推送触发

```bash
cd D:\Projects\makeiso
git commit --allow-empty -m "Trigger build after fixing secrets"
git push
```

---

## 🔍 验证 Secrets 配置

### 正确的配置应该是：

| Secret Name | Value | 说明 |
|------------|-------|------|
| DOCKERHUB_USERNAME | `ebichu` | 必须全小写 |
| DOCKERHUB_TOKEN | `dckr_pat_...` | 完整的 Token |

### 常见错误：

❌ 用户名使用了 `Ebichuu`（大写）  
✅ 应该使用 `ebichu`（全小写）

❌ Token 前后有空格  
✅ Token 应该无空格

❌ Token 已过期  
✅ Token 状态为 Active

---

## 🧪 本地测试（可选）

如果想在本地验证凭据是否正确：

```bash
# 测试登录
echo "YOUR_TOKEN" | docker login -u ebichu --password-stdin

# 如果成功会显示
# Login Succeeded

# 测试推送（可选）
docker pull hello-world
docker tag hello-world ebichu/test:latest
docker push ebichu/test:latest
docker image rm ebichu/test:latest
```

---

## 💡 替代方案：本地构建推送

如果 GitHub Actions 持续有问题，可以本地构建：

```bash
cd D:\Projects\makeiso

# 1. 登录 Docker Hub
docker login
# Username: ebichu
# Password: [粘贴您的 Token]

# 2. 构建镜像
docker build -t ebichu/iso-packer:latest .
docker tag ebichu/iso-packer:latest ebichu/iso-packer:v1.0.0

# 3. 推送到 Docker Hub
docker push ebichu/iso-packer:latest
docker push ebichu/iso-packer:v1.0.0

# 4. 验证
docker pull ebichu/iso-packer:latest
```

---

## 📊 构建成功的标志

构建成功后，您会看到：

1. **GitHub Actions**：
   - ✅ 绿色对勾
   - "Build and Push Docker Image" 成功

2. **Docker Hub**：
   - 访问：https://hub.docker.com/r/ebichu/iso-packer
   - 看到镜像标签：latest, v1.0.0, main

3. **用户可以拉取**：
   ```bash
   docker pull ebichu/iso-packer:latest
   # 应该成功下载
   ```

---

## ❓ 仍然失败？

如果按照上述步骤操作后仍然失败，请提供：

1. **GitHub Actions 完整日志**
   - 访问失败的 workflow run
   - 展开所有步骤
   - 复制完整日志

2. **Secrets 配置截图**
   - 显示 Secret 名称（不显示值）

3. **Docker Hub Token 截图**
   - 显示 Token 状态和权限

---

## 📝 快速检查清单

- [ ] Docker Hub Token 状态为 Active
- [ ] Token 权限包含 Read & Write
- [ ] GitHub Secret DOCKERHUB_USERNAME = `ebichu`（小写）
- [ ] GitHub Secret DOCKERHUB_TOKEN 已正确粘贴
- [ ] Secret 值前后无空格
- [ ] 已重新触发构建

---

**完成上述步骤后，构建应该能成功！** 🚀
