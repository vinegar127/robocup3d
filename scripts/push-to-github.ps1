# ===========================================================================
#  推送本仓库到 GitHub —— 交互式脚本（SSH 方式，国内最稳）
# ===========================================================================
#  用法：在【你自己的 PowerShell 窗口】里执行：
#        cd E:\dsh_workspace\3d\robocup3d-prep
#        powershell -ExecutionPolicy Bypass -File scripts\push-to-github.ps1
#
#  为什么需要你自己跑？
#  DSH 的运行环境有沙箱限制，无法读写 hosts、无法写全局 git 配置、
#  也无法派生 Git 的 HTTPS 辅助进程，所以推送必须在你的终端里做。
#
#  本脚本做什么：
#    1. 检查 / 生成 SSH 密钥
#    2. 打开 GitHub 添加公钥的页面，并把公钥复制到剪贴板
#    3. 等你确认后，测试 SSH 连接
#    4. 把 remote 切换成 SSH 地址并推送
#
#  安全说明：本脚本只操作你自己仓库的 .git，以及 ~/.ssh 下的密钥文件。
# ===========================================================================

$ErrorActionPreference = "Stop"

# ---- 配置：改成你的信息 ---------------------------------------------------
$GithubUser = "vinegar127"
$RepoName   = "robocup3d"
$RepoRoot   = Split-Path -Parent $PSScriptRoot     # 仓库根目录
$KeyPath    = Join-Path $env:USERPROFILE ".ssh\id_ed25519"

function Write-Step($n, $t) {
    Write-Host ""
    Write-Host ("=" * 62) -ForegroundColor DarkGray
    Write-Host " 第 $n 步：$t" -ForegroundColor Cyan
    Write-Host ("=" * 62) -ForegroundColor DarkGray
}

function Write-Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "  [提示] $m" -ForegroundColor Yellow }
function Write-Err($m)  { Write-Host "  [错误] $m" -ForegroundColor Red }

Write-Host ""
Write-Host "============================================================" -ForegroundColor White
Write-Host "  推送 robocup3d 到 GitHub（SSH 方式）" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor White
Write-Host "  仓库目录: $RepoRoot"
Write-Host "  目标仓库: git@github.com:$GithubUser/$RepoName.git"

Set-Location $RepoRoot

# ===========================================================================
Write-Step 1 "检查 SSH 密钥"
# ===========================================================================

if (Test-Path "$KeyPath.pub") {
    Write-Ok "已存在 SSH 密钥：$KeyPath"
} else {
    Write-Warn2 "还没有 SSH 密钥，现在生成（连续回车 3 次即可）"
    Write-Host ""
    # -N "" 表示不设密码短语，省去每次输入
    ssh-keygen -t ed25519 -C "zwyzwyjis@163.com" -f $KeyPath -N '""'
    if (-not (Test-Path "$KeyPath.pub")) {
        Write-Err "密钥生成失败，请手动执行：ssh-keygen -t ed25519 -C `"你的邮箱`""
        exit 1
    }
    Write-Ok "密钥已生成"
}

Write-Host ""
Write-Host "  公钥内容（这就是要贴给 GitHub 的东西）：" -ForegroundColor DarkGray
Get-Content "$KeyPath.pub" | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

# 顺手复制到剪贴板
try {
    Get-Content "$KeyPath.pub" -Raw | Set-Clipboard
    Write-Ok "公钥已复制到剪贴板"
} catch {
    Write-Warn2 "复制到剪贴板失败，请手动复制上面那一行"
}

# ===========================================================================
Write-Step 2 "把公钥添加到 GitHub"
# ===========================================================================

Write-Host @"

  接下来需要你做两件事：

    1) 浏览器会自动打开 GitHub 的 SSH 密钥设置页
    2) 按这个填：
         Title      : 随便起，比如「我的笔记本」
         Key type   : Authentication Key（保持默认）
         Key        : 直接 Ctrl+V 粘贴（已在剪贴板里）
       然后点 Add SSH key

  重要：必须是 .pub 结尾的【公钥】。
        没有 .pub 的那个文件是【私钥】，绝对不能外传。

"@ -ForegroundColor Yellow

Start-Process "https://github.com/settings/keys"
Read-Host "  添加完成后，按回车继续"

# ===========================================================================
Write-Step 3 "测试 SSH 连接"
# ===========================================================================

Write-Host "  执行: ssh -T git@github.com" -ForegroundColor DarkGray
Write-Host "  （第一次会问 yes/no，输入 yes 回车）" -ForegroundColor DarkGray
Write-Host ""

$test = ssh -T git@github.com 2>&1 | Out-String
Write-Host "  $($test.Trim())"

if ($test -match "successfully authenticated") {
    Write-Ok "SSH 认证成功！"
} elseif ($test -match "Permission denied") {
    Write-Err "认证失败。常见原因："
    Write-Host "         - 公钥没添加成功，去 https://github.com/settings/keys 确认"
    Write-Host "         - 粘贴时漏字符了，重新复制公钥再加一次"
    Write-Host ""
    $cont = Read-Host "  仍要继续尝试推送吗？(y/N)"
    if ($cont -ne "y") { exit 1 }
} elseif ($test -match "timed out|Connection") {
    Write-Warn2 "连接超时。22 端口可能被封，脚本会自动配置 443 端口兜底。"
    $sshDir = Join-Path $env:USERPROFILE ".ssh"
    $cfgFile = Join-Path $sshDir "config"
    $cfgBody = @"
Host github.com
    HostName ssh.github.com
    Port 443
    User git
"@
    if (Test-Path $cfgFile) {
        $existing = Get-Content $cfgFile -Raw
        if ($existing -notmatch "ssh\.github\.com") {
            Add-Content -Path $cfgFile -Value "`n$cfgBody"
            Write-Ok "已追加配置到 $cfgFile"
        } else {
            Write-Ok "配置文件里已有 443 兜底配置"
        }
    } else {
        Set-Content -Path $cfgFile -Value $cfgBody -Encoding ASCII
        Write-Ok "已创建 $cfgFile"
    }
    Write-Host ""
    Write-Warn2 "请重新运行本脚本（这次会走 443 端口）"
    exit 0
}

# ===========================================================================
Write-Step 4 "切换 remote 到 SSH 并推送"
# ===========================================================================

$sshUrl = "git@github.com:$GithubUser/$RepoName.git"
Write-Host "  执行: git remote set-url origin $sshUrl" -ForegroundColor DarkGray
git remote set-url origin $sshUrl

Write-Host ""
Write-Host "  当前 remote:" -ForegroundColor DarkGray
git remote -v | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "  待推送的提交:" -ForegroundColor DarkGray
git log --oneline | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "  开始推送..." -ForegroundColor Cyan
Write-Host ""

git push -u origin main 2>&1 | ForEach-Object { Write-Host "    $_" }

Write-Host ""
if ($LASTEXITCODE -eq 0) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  推送成功！" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  仓库地址: https://github.com/$GithubUser/$RepoName"
    Write-Host ""
    Write-Host "  建议接下来做：" -ForegroundColor Yellow
    Write-Host "    1. 打开仓库网页，确认 README 和 docs/ 都正常显示（中文没乱码）"
    Write-Host "    2. 在仓库首页 About 里加描述和 Topics（robocup robocup3d mujoco）"
    Write-Host "    3. 邀请队友，或把仓库转到 Organization 下"
    Write-Host ""
    Start-Process "https://github.com/$GithubUser/$RepoName"
} else {
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  推送失败" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  常见原因：" -ForegroundColor Yellow
    Write-Host "    rejected / fetch first  -> GitHub 上那个仓库不是空的"
    Write-Host "        解法: git push -u origin main --force   (确认远程没内容再用)"
    Write-Host "    仓库不存在               -> 先去 https://github.com/new 建一个空仓库"
    Write-Host "    连接超时                 -> 重新运行本脚本（会走 443 端口）"
    Write-Host ""
    Write-Host "  详细排查见: docs\07-推送到GitHub.md"
}
