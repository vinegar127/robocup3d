# 如何把这个仓库推送到 GitHub

> **当前状态**：本地 Git 仓库**已经建好了**，代码已提交（7 个 commit）。
> remote 已指向正确地址，你只差「推送 + 认证」这一步。

---

## ⚠️ 先记住这两个名字不一样

| | 名字 |
|---|------|
| **本地文件夹** | `robocup3d-prep` |
| **GitHub 仓库** | `robocup3d-` ← **末尾有一个横杠！** |

**这个横杠是真实存在的，不要漏掉。** 漏掉就会得到：

```
fatal: repository 'https://github.com/用户名/robocup3d.git/' not found
```

> 💡 **为什么容易搞错**：GitHub 仓库名末尾带 `-` 是很罕见的写法，
> 肉眼几乎注意不到。如果推送时提示仓库不存在，
> **第一件事就是去网页上把仓库名复制下来对照一遍**，
> 而不是怀疑网络或权限。

---

## 前置检查

```powershell
cd E:\dsh_workspace\3d\robocup3d-prep
git remote -v
git log --oneline
git status
```

应该看到：

```
origin  https://github.com/vinegar127/robocup3d-.git (fetch)
origin  https://github.com/vinegar127/robocup3d-.git (push)
```

而 `git status` 应该是干净的。

---

## 🚀 最快路径：直接跑脚本

本仓库提供了一个交互式脚本，**自动处理 SSH 密钥 + 连接测试 + 推送**：

```powershell
cd E:\dsh_workspace\3d\robocup3d-prep
powershell -ExecutionPolicy Bypass -File scripts\push-to-github.ps1
```

脚本会：

1. 检查/生成 SSH 密钥，并把公钥复制到剪贴板
2. 自动打开 GitHub 添加公钥的页面
3. 测试 SSH 连接（22 端口被封时**自动改走 443**）
4. 切换 remote 为 SSH 地址并推送
5. 失败时给出针对性排错提示

**不想用脚本**就继续看下面的手动流程。

---

## 方案 A：HTTPS + Token

### 第 1 步：确认仓库是空的

打开 <https://github.com/vinegar127/robocup3d->

**如果里面已经有 README**（建仓时勾了），推送会被拒绝：

```
! [rejected] main -> main (fetch first)
```

两种解法：
- 那个 README 不要了 → `git push -u origin main --force`
- 想保留 → `git pull origin main --allow-unrelated-histories` 后再推

### 第 2 步：推送

```powershell
cd E:\dsh_workspace\3d\robocup3d-prep
git push -u origin main
```

### 第 3 步：认证

**GitHub 早已禁用账号密码**，必须用 Token 或 SSH。

**如果弹出浏览器** → 登录授权即可，最省事。

**如果提示输入密码** → 生成 Token：

1. 打开 <https://github.com/settings/tokens>
2. **Fine-grained tokens** → **Generate new token**
   - Name：随便起
   - Expiration：90 天
   - Repository access：**Only select repositories** → 选 `robocup3d-`
   - Permissions → Repository permissions：
     - **Contents: Read and write** ← 必须
3. **立刻复制**（关掉页面就再也看不到了）
4. 回到命令行：`Username` 填 `vinegar127`，
   `Password` **粘贴 Token**（粘贴时屏幕不显示字符，这是正常的）

成功后：

```
To https://github.com/vinegar127/robocup3d-.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

**✅ 去网页刷新就能看到仓库了。**

---

## 方案 B：SSH（推荐长期使用）

配好之后**再也不用输任何东西**。

```powershell
# ① 生成密钥（连续回车即可）
ssh-keygen -t ed25519 -C "zwyzwyjis@163.com"

# ② 复制【公钥】（认准 .pub 后缀！）
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard

# ③ 去 https://github.com/settings/keys 点 New SSH key 粘贴

# ④ 测试（第一次问 yes/no 输 yes）
ssh -T git@github.com
#    期望: Hi vinegar127! You've successfully authenticated...

# ⑤ 切换为 SSH 地址（注意是冒号，不是斜杠）
git remote set-url origin git@github.com:vinegar127/robocup3d-.git
git push -u origin main
```

### SSH 连不上时（22 端口被封）

新建 `C:\Users\zwyzw\.ssh\config`：

```
Host github.com
    HostName ssh.github.com
    Port 443
    User git
```

再测一次 `ssh -T git@github.com`。

> ⚠️ 公钥是 `.pub` 后缀那个，可以公开；
> **没有 `.pub` 的是私钥，绝对不能外传或提交到 Git**。

---

## 方案 C：GitHub CLI

```powershell
gh auth login
# 仓库已存在，直接推送：
git push -u origin main
```

---

## 推送失败的排查

| 报错 | 原因 | 解法 |
|------|------|------|
| `repository not found` | **仓库名写错**（最常见：漏了末尾的 `-`） | `git remote -v` 对照网页地址 |
| `repository not found` | 仓库私有且未登录 | 先认证，或把仓库设为 public |
| `rejected / fetch first` | 远程不空 | 见第 1 步 |
| `Authentication failed` | Token 无权限/过期 | 重新生成，勾 Contents: Read and write |
| `schannel: SEC_E_NO_CREDENTIALS` | Windows 证书后端异常 | 见下 |
| `OpenSSL SSL_read: Connection was reset` | 网络 | 走代理或重试 |
| `Permission denied (publickey)` | 公钥没加上 | 去 settings/keys 确认 |
| `Connection timed out` | 22 端口被封 | 用上面的 443 兜底配置 |
| `remote origin already exists` | 加过 remote 了 | `git remote set-url origin <地址>` |

### `schannel: SEC_E_NO_CREDENTIALS`

Windows 的 TLS 后端拿不到凭据。两种解法：

```powershell
# 解法 1：换 Git 自带的 OpenSSL 后端
git config --global http.sslBackend openssl
git config --global http.sslCAInfo "D:/Git/mingw64/etc/ssl/certs/ca-bundle.crt"

# 解法 2：让 Git 走你的代理
git config --global http.https://github.com.proxy http://127.0.0.1:7890
# 端口换成你自己代理软件的（Clash 常见 7890 / 7897，从软件界面看）
```

取消代理：

```powershell
git config --global --unset http.https://github.com.proxy
```

> ⚠️ 如果你**不在**代理环境里却留着代理配置，会**反而连不上**。
> 换网络（宿舍↔实验室）后记得检查。

---

## 日常协作流程

```powershell
# ① 开工前先拉（★ 必须，否则后面全是冲突）
git pull

# ② 开分支（不要直接在 main 上改）
git checkout -b feature/你的名字-改进点

# ③ 改代码...

# ④ 提交前跑基准测试，拿到数字
python code\demo_sim.py --bench 20

# ⑤ 提交
git add .
git commit -m "feat: 改进踢球对准逻辑，场均进球 2.7 -> 3.4"

# ⑥ 推送分支
git push -u origin feature/你的名字-改进点

# ⑦ 去 GitHub 开 Pull Request
```

**提交信息前缀**（写技术报告时，`git log` 就是你的成果清单）：

| 前缀 | 用途 |
|------|------|
| `feat:` | 新功能 |
| `fix:` | 修 bug |
| `docs:` | 文档 |
| `refactor:` | 重构 |
| `perf:` | 性能优化 |

> ★ **提交信息里带上数字**（比如「场均进球 2.7 → 3.4」），
> 第 8 周写技术报告时你会感谢自己。

---

## 推送完成后的建议

1. **检查网页**：README 和 `docs/` 中文没乱码、没有 `__pycache__` 之类的垃圾
2. **加描述和 Topics**：仓库首页 About → 填
   `robocup robocup3d simulation-league humanoid-robot mujoco python education chinese`
3. **建 Organization**：放在个人账号下，人毕业了仓库会很难处理；
   放在组织下可以一直传承（<https://github.com/account/organizations/new>）
4. **保护 main 分支**：Settings → Branches → 勾
   *Require a pull request before merging*，
   防止有人直接把主分支搞崩
5. **考虑改个仓库名**：`robocup3d-` 末尾的横杠很容易让人打错，
   建议在 Settings → General → Repository name 改成 `robocup3d`
   或 `robocup3d-prep`；改名后 GitHub 会自动重定向旧地址，
   然后本地执行：
   ```powershell
   git remote set-url origin https://github.com/vinegar127/新名字.git
   ```

---

## 附：本机环境的两个已知问题

推送时如果在这台机器上遇到下面情况，属于**正常**，按提示处理：

| 现象 | 原因 |
|------|------|
| `schannel: SEC_E_NO_CREDENTIALS` | 这台机器的 Windows 证书后端有问题，用上面的解法 1 或 2 |
| `sh.exe: couldn't create signal pipe, Win32 error 5` | 在受限沙箱里跑 Git 会这样；**在普通终端里不会有这个问题** |
| 有时连不上 github.com 但过一会又好了 | 该域名解析到的 IP 时通时断，重试或走代理即可 |
