# ===========================================================================
#  推送本仓库到 GitHub —— 交互式脚本（SSH 方式，国内最稳）
# ===========================================================================
#  用法：在【你自己的 PowerShell 窗口】里执行：
#        cd E:\dsh_workspace\3d\robocup3d-prep
#        powershell -ExecutionPolicy Bypass -File scripts\push-to-github.ps1
#
#  为什么需要你自己跑？
#  DSH 的运行环境有沙箱限制，无法写全局 git 配置，也无法派生 Git 的
#  HTTPS 辅助进程，所以推送必须在你的终端里做。
#
#  本脚本做什么：
#    1. 检查 / 生成 SSH 密钥，并把公钥复制到剪贴板
#    2. 打开 GitHub 添加公钥的页面，等你确认
#    3. 测试 SSH 连接；22 端口被封时自动改走 443 端口
#    4. 把 remote 切换成 SSH 地址并推送，附带针对性排错提示
#
#  安全说明：本脚本只操作你自己仓库的 .git，以及 ~/.ssh 下的密钥文件。
# ===========================================================================

$ErrorActionPreference = "Stop"

# ---- 配置：改成你的信息 ---------------------------------------------------
$GithubUser = "vinegar127"
$RepoName   = "robocup3d-"
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$KeyPath    = Join-Path $env:USERPROFILE ".ssh\id_ed25519"

function Write-Step($n, $t) {
    Write-Host ""
    Write-Host ("=" * 62) -ForegroundColor DarkGray
    Write-Host " 第 $n 步：$t" -ForegroundColor Cyan
    Write-Host ("=" * 62) -ForegroundColor DarkGray
}
function Write-Ok($m)    { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Note($m)  { Write-Host "  [提示] $m" -ForegroundColor Yellow }
function Write-Err($m)   { Write-Host "  [错误] $m" -ForegroundColor Red }
function Write-Dim($m)   { Write-Host "  $m" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "============================================================"
Write-Host "  推送 robocup3d 到 GitHub（SSH 方式）"
Write-Host "============================================================"
Write-Host "  仓库目录: $RepoRoot"
Write-Host "  目标仓库: git@github.com:$GithubUser/$RepoName.git"

Set-Location $RepoRoot

# ===========================================================================
Write-Step 1 "检查 SSH 密钥"
# ===========================================================================

if (Test-Path "$KeyPath.pub") {
    Write-Ok "已存在 SSH 密钥：$KeyPath"
} else {
    Write-Note "还没有 SSH 密钥，现在生成（不需要再输入任何东西）"
    Write-Host ""
    # -N '' 表示不设密码短语，省去每次输入
    ssh-keygen -t ed25519 -C "zwyzwyjis@163.com" -f $KeyPath -N '""'
    if (-not (Test-Path "$KeyPath.pub")) {
        Write-Err "密钥生成失败。请手动执行："
        Write-Host '         ssh-keygen -t ed25519 -C "你的邮箱@example.com"'
        exit 1
    }
    Write-Ok "密钥已生成"
}

Write-Host ""
Write-Dim "公钥内容（就是要贴给 GitHub 的那一行）："
Get-Content "$KeyPath.pub" | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

try {
    Get-Content "$KeyPath.pub" -Raw | Set-Clipboard
    Write-Ok "公钥已复制到剪贴板"
} catch {
    Write-Note "复制到剪贴板失败，请手动选中上面那一行复制"
}

# ===========================================================================
Write-Step 2 "把公钥添加到 GitHub"
# ===========================================================================

Write-Host ""
Write-Host "  接下来做两件事：" -ForegroundColor Yellow
Write-Host "    1) 浏览器会自动打开 GitHub 的 SSH 密钥设置页"
Write-Host "    2) 按这样填："
Write-Host "         Title    : 随便起，比如 我的笔记本"
Write-Host "         Key type : Authentication Key（保持默认）"
Write-Host "         Key      : 直接 Ctrl+V 粘贴（已经在剪贴板里了）"
Write-Host "       然后点 Add SSH key"
Write-Host ""
Write-Host "  注意：必须是 .pub 结尾的【公钥】。" -ForegroundColor Red
Write-Host "        没有 .pub 的那个文件是【私钥】，绝对不能外传。" -ForegroundColor Red
Write-Host ""

Start-Process "https://github.com/settings/keys"
Read-Host "  添加完成后按回车继续"

# ===========================================================================
Write-Step 3 "测试 SSH 连接"
# ===========================================================================

Write-Dim "执行: ssh -T git@github.com"
Write-Dim "（第一次会问 yes/no，输入 yes 回车）"
Write-Host ""

$test = ssh -T git@github.com 2>&1 | Out-String
Write-Host "  $($test.Trim())"
Write-Host ""

if ($test -match "successfully authenticated") {
    Write-Ok "SSH 认证成功"
}
elseif ($test -match "Permission denied") {
    Write-Err "认证失败。常见原因："
    Write-Host "         - 公钥没添加成功，去 https://github.com/settings/keys 确认"
    Write-Host "         - 粘贴时漏字符了，重新复制公钥再加一次"
    Write-Host ""
    $cont = Read-Host "  仍要继续尝试推送吗？(y/N)"
    if ($cont -ne "y") { exit 1 }
}
elseif ($test -match "timed out|Connection|refused") {
    Write-Note "连接超时。22 端口可能被网络封锁，正在配置 443 端口兜底..."
    $sshDir  = Join-Path $env:USERPROFILE ".ssh"
    $cfgFile = Join-Path $sshDir "config"
    $cfgBody = "Host github.com`n    HostName ssh.github.com`n    Port 443`n    User git`n"

    if (Test-Path $cfgFile) {
        $existing = Get-Content $cfgFile -Raw
        if ($existing -notmatch "ssh\.github\.com") {
            Add-Content -Path $cfgFile -Value "`n$cfgBody"
            Write-Ok "已追加配置到 $cfgFile"
        } else {
            Write-Ok "配置文件里已有 443 兜底配置"
        }
    } else {
        New-Item -ItemType Directory -Force -Path $sshDir | Out-Null
        Set-Content -Path $cfgFile -Value $cfgBody -Encoding ASCII
        Write-Ok "已创建 $cfgFile"
    }

    Write-Host ""
    Write-Note "请重新运行本脚本，这次会走 443 端口"
    Write-Host "        powershell -ExecutionPolicy Bypass -File scripts\push-to-github.ps1"
    exit 0
}

# ===========================================================================
Write-Step 4 "切换 remote 到 SSH 并推送"
# ===========================================================================

$sshUrl = "git@github.com:$GithubUser/$RepoName.git"
Write-Dim "执行: git remote set-url origin $sshUrl"
git remote set-url origin $sshUrl

Write-Host ""
Write-Dim "当前 remote:"
git remote -v | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

Write-Host ""
Write-Dim "待推送的提交:"
git log --oneline | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "  开始推送..." -ForegroundColor Cyan
Write-Host ""

git push -u origin main 2>&1 | ForEach-Object { Write-Host "    $_" }

Write-Host ""
if ($LASTEXITCODE -eq 0) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  推送成功" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  仓库地址: https://github.com/$GithubUser/$RepoName"
    Write-Host ""
    Write-Host "  建议接下来做：" -ForegroundColor Yellow
    Write-Host "    1. 打开仓库网页，确认 README 和 docs 都正常显示（中文没乱码）"
    Write-Host "    2. 在仓库首页 About 里加描述和 Topics: robocup robocup3d mujoco python"
    Write-Host "    3. 邀请队友，或把仓库转到 Organization 下"
    Write-Host ""
    Start-Process "https://github.com/$GithubUser/$RepoName"
} else {
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "  推送失败" -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  常见原因：" -ForegroundColor Yellow
    Write-Host "    rejected / fetch first -> GitHub 上那个仓库不是空的"
    Write-Host "         解法: git push -u origin main --force   （确认远程没内容再用）"
    Write-Host "    仓库不存在              -> 先去 https://github.com/new 建一个空仓库"
    Write-Host "    连接超时                -> 重新运行本脚本（会自动走 443 端口）"
    Write-Host ""
    Write-Host "  详细排查见: docs\07-推送到GitHub.md"
}

Write-Host ""
Read-Host "  按回车关闭"
