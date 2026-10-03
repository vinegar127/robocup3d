# 如何把这个仓库推送到 GitHub

> **当前状态**：本地 Git 仓库**已经建好了**，代码已提交（4 个 commit）。
> 你只差「在 GitHub 上建一个空仓库」+「推上去」这两步。

---

## 前置检查

先确认本地仓库是好的：

```powershell
cd <本仓库目录>
git log --oneline
git status
```

应该看到类似输出：

```
6f8083d fix: run_demo.bat 改为纯 ASCII，修复中文导致 cmd.exe 解析失败
f3f6fa6 docs: 补充完整步态周期数据表与说明
ed63e5f docs: 增加 2D 仿真附录、术语表与常见误解；修正感知器命名
0b8b891 feat: RoboCup 3D 仿真赛项零基础备赛资料包
```

而 `git status` 应该是干净的（没有 untracked 文件）。

---

## 方案 A：网页建仓 + 命令行推送（**最推荐，最通用**）

### 第 1 步：在 GitHub 上建一个**空**仓库

1. 打开 <https://github.com/new>
2. 填写：

   | 字段 | 填什么 |
   |------|--------|
   | Repository name | `robocup3d-prep` |
   | Description | `RoboCup 3D 仿真赛项零基础备赛资料包：安装指南 + 可运行 demo + 3D 步态可视化` |
   | Public / Private | 建议 **Public**（RoboCup 鼓励开源；技术审查也好看） |
   | Add a README file | ❌ **不要勾！** |
   | Add .gitignore | ❌ **不要选！** |
   | Choose a license | ❌ **不要选！** |

   > ⚠️ **为什么不勾 README / .gitignore / license？**
   > 因为这三样**你已经有了**。
   > 如果 GitHub 帮你建了，远程仓库就会有一个你没有的 commit，
   > 你推送时会被拒绝：
   > ```
   > ! [rejected] main -> main (fetch first)
   > ```
   > 这就是新手最常遇到的第一个坑。**建纯空仓库最省事。**

3. 点 **Create repository**
4. 建完后**先别关页面** —— 上面会显示仓库地址，格式：
   `https://github.com/<你的用户名>/robocup3d-prep.git`

### 第 2 步：添加远程地址并推送

把下面的 `<你的用户名>` 换成你的 GitHub 用户名：

```powershell
cd <本仓库目录>

# ① 关联远程仓库
git remote add origin https://github.com/<你的用户名>/robocup3d-prep.git

# ② 确认关联成功
git remote -v

# ③ 推送
git push -u origin main
```

### 第 3 步：处理认证（这里 90% 的人会卡住）

推送时会要求你输入用户名和密码。**注意：GitHub 早就不能用账号密码了**，
必须用 **Personal Access Token** 代替密码。

**如果弹出浏览器让你登录** → 直接登录授权，完成。
（这是 Git Credential Manager，最省事的情况。）

**如果命令行提示输入密码** → 按下面步骤生成 Token：

1. 打开 <https://github.com/settings/tokens>
2. 推荐选 **Fine-grained tokens** → **Generate new token**
   - Name：`robocup3d`（随便起）
   - Expiration：90 天
   - Repository access：选 **All repositories**（或只选这一个仓库）
   - Permissions → Repository permissions：
     - **Contents: Read and write** ← 必须
     - **Administration: Read and write** ← 建仓库才需要
3. 点 **Generate token**，**立刻复制**（关掉页面就再也看不到了）
4. 回到命令行：
   - `Username` 输入你的 GitHub 用户名
   - `Password` **粘贴刚才的 Token**（注意：粘贴时屏幕不显示字符，这是正常的）

成功后你会看到：

```
Enumerating objects: ..., done.
...
To https://github.com/<你的用户名>/robocup3d-prep.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

**✅ 完成！去 GitHub 网页刷新，就能看到你的仓库了。**

---

## 方案 B：用 GitHub CLI（如果已装 `gh`）

```powershell
# 1. 你已经 git init 并提交过了，所以直接建远程 + 推
gh auth login

gh repo create robocup3d-prep --public --source=. --push `
  --description "RoboCup 3D 仿真赛项零基础备赛资料包"

# 验证
gh repo view --web
```

一行命令搞定建仓+推送。适合熟悉命令行的同学。

---

## 方案 C：如果推送失败

### 错误 1：`remote origin already exists`

说明你之前加过远程地址。先删再加：

```powershell
git remote remove origin
git remote add origin https://github.com/<你的用户名>/robocup3d-prep.git
```

### 错误 2：`! [rejected] main -> main (fetch first)`

原因：远程仓库不是空的（你建仓时勾了 README / .gitignore / license）。

**解法 A（推荐，远程内容不要了）**：

```powershell
git push -u origin main --force
```
> ⚠️ `--force` 会**覆盖远程的所有内容**。
> 只在「远程只有 GitHub 自动生成的 README」时才安全。

**解法 B（想保留远程内容）**：
```powershell
git pull origin main --allow-unrelated-histories
# 手动解决冲突后
git push -u origin main
```

### 错误 3：`OpenSSL SSL_read: Connection was reset` / 连接超时

国内网络问题。见 `docs/01-环境安装.md` 第 5.3 节的网络方案
（代理 / hosts / Gitee 中转）。

### 错误 4：`Authentication failed`

Token 没权限或过期了。重新生成一个，权限至少要有
**Contents: Read and write**。

### 错误 5：中文文件名显示成 `\344\270\255\346\226\207`

不是错误，是显示问题。执行：

```powershell
git config --global core.quotepath false
```

---

## 推送完成后的建议

### 1. 检查仓库是否完整

打开仓库网页，确认：

- [ ] README.md 正常显示（中文没乱码）
- [ ] `docs/` 里 6 个 md 文件都在
- [ ] `tools/walkviz/index.html` 能点开看源码
- [ ] 文件列表里**没有** `__pycache__`、`.venv` 这种不该提交的东西

### 2. 设置仓库描述和话题（让别人搜得到）

在仓库首页右上角 **⚙️ Settings** 附近点 **About** 的齿轮，填：

- **Description**：`RoboCup 3D 仿真赛项零基础备赛资料包：环境安装指南 + 可运行 demo + 3D 步态可视化`
- **Topics**（话题，用空格隔开）：
  ```
  robocup robocup3d simulation-league humanoid-robot mujoco python education chinese
  ```

### 3. 邀请队友

**建议建一个 Organization（组织）**，而不是放在个人账号下：

- 放在个人账号：这个人毕业了/退出队伍，仓库管理会很麻烦
- 放在组织下：仓库属于队伍，可以一直传承

创建组织：<https://github.com/account/organizations/new>

然后把队友加进来（Settings → People → Invite）。

### 4. 保护 main 分支（队伍人数多时强烈建议）

Settings → Branches → Add branch protection rule：

- Branch name pattern：`main`
- 勾选 **Require a pull request before merging**

这样谁都不能直接往 main 推代码，必须走 PR 流程 ——
可以避免「某个队员半夜把主分支搞崩了」。

---

## 日常协作流程（推上去之后）

```powershell
# ① 开工前：拉最新代码（★ 必须做，否则后面全是冲突）
git pull

# ② 开一个自己的分支（不要直接在 main 上改）
git checkout -b feature/你的名字-改进点

# ③ 改代码...

# ④ 提交前先跑基准测试，拿到数字
python code\demo_sim.py --bench 20

# ⑤ 提交
git add .
git commit -m "feat: 改进踢球对准逻辑，场均进球 2.7 -> 3.4"

# ⑥ 推送分支
git push -u origin feature/你的名字-改进点

# ⑦ 去 GitHub 上开 Pull Request
```

**提交信息的写法建议**（技术报告里会用到）：

| 前缀 | 用途 | 例子 |
|------|------|------|
| `feat:` | 新功能 | `feat: 加入球的位置记忆` |
| `fix:` | 修 bug | `fix: 修复看不见球时全员发呆` |
| `docs:` | 文档 | `docs: 补充环境安装常见报错` |
| `refactor:` | 重构（不改行为） | `refactor: 拆分 agent.py` |
| `perf:` | 性能优化 | `perf: 优化搜索路径，找球时间减半` |

> ★ **提交信息里带上数字**，第 8 周写技术报告时，
> `git log` 就是你的成果清单。

---

## 附：一句话版本

如果你已经建好了空仓库、也配好了 Token，那么**只有两行**：

```powershell
git remote add origin https://github.com/<你的用户名>/robocup3d-prep.git
git push -u origin main
```
