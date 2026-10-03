#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RoboCup3D 备赛环境体检脚本
===========================

零基础同学的第一道关卡：**先确认电脑环境是对的，再开始写代码。**

直接运行：
    python scripts/setup_check.py

它会逐项检查，并用 [OK] / [WARN] / [FAIL] 标注结果，
最后给出「你现在能不能开始备赛」的结论。

设计原则：
    - 只用 Python 标准库，因为「还没装依赖」正是最需要被诊断的时期
    - 每个 FAIL 都附带可复制的修复命令
    - 绝不因为一个可选组件缺失就报失败（比如 VS Code）

退出码：
    0 = 可以开始备赛
    1 = 有阻塞性问题需要修复
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

# Windows 控制台默认可能是 GBK，中文会乱码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 输出helpers（带颜色，但在不支持的终端上自动降级）
# ---------------------------------------------------------------------------

_COLOR = sys.platform != "win32" or os.environ.get("WT_SESSION") or os.environ.get("TERM")


def _c(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


OK = _c("32", "[OK]  ")
WARN = _c("33", "[WARN]")
FAIL = _c("31", "[FAIL]")
INFO = _c("36", "[INFO]")


class Report:
    """收集检查结果，最后统一汇报。"""

    def __init__(self):
        self.ok = 0
        self.warn = 0
        self.fail = 0
        self.fixes: List[str] = []

    def good(self, name: str, detail: str = ""):
        self.ok += 1
        print(f" {OK} {name:<22} {detail}")

    def warning(self, name: str, detail: str = "", fix: str = ""):
        self.warn += 1
        print(f" {WARN} {name:<22} {detail}")
        if fix:
            self.fixes.append(f"  [可选] {name}\n         {fix}")

    def bad(self, name: str, detail: str = "", fix: str = ""):
        self.fail += 1
        print(f" {FAIL} {name:<22} {detail}")
        if fix:
            self.fixes.append(f"  [必须] {name}\n         {fix}")

    def info(self, text: str):
        print(f" {INFO} {text}")


def run_cmd(cmd: List[str], timeout: int = 12) -> Tuple[bool, str]:
    """
    安全执行外部命令，返回 (成功?, 输出)。

    注意这里显式设置了 PYTHONIOENCODING=utf-8：
    中文 Windows 的控制台默认编码是 GBK(cp936)，一旦子进程的输出被
    管道捕获（而不是直接打到控制台），Python 会因为无法用 GBK 编码
    中文字符而抛 UnicodeEncodeError 直接崩溃。
    这不是理论问题 —— 它就是「终端里能跑、脚本里调就报错」的元凶。
    """
    exe = shutil.which(cmd[0])
    if not exe:
        return False, "未找到可执行文件"

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "命令超时"
    except Exception as e:  # pragma: no cover
        return False, f"执行失败: {e}"


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------

def check_python(rep: Report):
    """① Python 版本 —— 这是最关键的检查。"""
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"

    if v < (3, 8):
        rep.bad(
            "Python 版本",
            f"{ver_str}  （太旧）",
            "本仓库需要 Python 3.8+，推荐 3.12。\n"
            "         下载: https://www.python.org/downloads/windows/",
        )
        return

    if v >= (3, 13):
        rep.warning(
            "Python 版本",
            f"{ver_str}  （偏新）",
            "部分机器人/AI 库的预编译包可能还没支持 3.13+，\n"
            "         可能被迫从源码编译（报 Microsoft Visual C++ 14.0 required）。\n"
            "         如果后面装 MuJoCo / PyTorch 失败，建议换成 Python 3.12。",
        )
    else:
        rep.good("Python 版本", ver_str)

    # 是不是 64 位（32 位 Python 装不了 MuJoCo 等库）
    bits = platform.architecture()[0]
    if "64" in bits:
        rep.good("Python 位数", bits)
    else:
        rep.bad(
            "Python 位数",
            f"{bits}  （必须是 64 位）",
            "32 位 Python 无法安装 MuJoCo / PyTorch。\n"
            "         请卸载后重新安装 64 位版本。",
        )

    # 解释器位置（帮同学确认自己用的是哪个 Python）
    rep.info(f"解释器路径: {sys.executable}")

    # 是不是虚拟环境 —— 新手最常踩的坑
    in_venv = sys.prefix != sys.base_prefix or "VIRTUAL_ENV" in os.environ
    if in_venv:
        rep.good("虚拟环境", "已激活")
    else:
        rep.warning(
            "虚拟环境",
            "未激活（用的是全局 Python）",
            "强烈建议用虚拟环境，避免污染系统 Python：\n"
            "         python -m venv .venv\n"
            "         .\\.venv\\Scripts\\Activate.ps1     # PowerShell\n"
            "         source .venv/bin/activate          # Linux / macOS / WSL\n"
            "         若 PowerShell 报「禁止运行脚本」：\n"
            "         Set-ExecutionPolicy -Scope CurrentUser RemoteSigned",
        )


def check_pip(rep: Report):
    """② pip 是否可用、有没有配国内源。"""
    ok, out = run_cmd([sys.executable, "-m", "pip", "--version"])
    if ok:
        # 输出形如 "pip 24.2 from D:\py\Lib\site-packages\pip (python 3.12)"
        m = re.search(r"pip\s+([\d.]+)", out)
        rep.good("pip", m.group(1) if m else "可用")
    else:
        rep.bad(
            "pip",
            "不可用",
            f"{sys.executable} -m ensurepip --upgrade",
        )
        return

    # 检查 pip 源配置（国内同学没配源会非常痛苦）
    ok, out = run_cmd([sys.executable, "-m", "pip", "config", "list"])
    if ok and "index-url" in out:
        m = re.search(r"index-url\s*=\s*'?([^'\n]+)'?", out)
        url = m.group(1) if m else "已配置"
        if "pypi.org" in url:
            rep.warning(
                "pip 镜像源",
                "使用官方源（国内会慢）",
                "建议换成清华源：\n"
                "         python -m pip config set global.index-url "
                "https://pypi.tuna.tsinghua.edu.cn/simple\n"
                "         python -m pip config set global.trusted-host "
                "pypi.tuna.tsinghua.edu.cn",
            )
        else:
            rep.good("pip 镜像源", url[:46])
    else:
        rep.warning(
            "pip 镜像源",
            "未配置（国内下载会很慢）",
            "python -m pip config set global.index-url "
            "https://pypi.tuna.tsinghua.edu.cn/simple",
        )


def check_git(rep: Report):
    """③ Git 是否装了、身份配了没、中文设置对不对。"""
    ok, out = run_cmd(["git", "--version"])
    if not ok:
        rep.bad(
            "Git",
            "未安装",
            "下载 https://git-scm.com/download/win 并安装。\n"
            "         安装时 Default editor 请选 Visual Studio Code，不要选 Vim。",
        )
        return
    rep.good("Git", out.replace("git version ", ""))

    # 用户身份
    ok_name, name = run_cmd(["git", "config", "--global", "user.name"])
    ok_mail, mail = run_cmd(["git", "config", "--global", "user.email"])
    if ok_name and name and ok_mail and mail:
        rep.good("Git 用户身份", f"{name} <{mail}>")
    else:
        rep.bad(
            "Git 用户身份",
            "未配置",
            'git config --global user.name "你的名字"\n'
            '         git config --global user.email "你的邮箱@example.com"',
        )

    # 中文文件名显示（Windows 必配）
    ok, qp = run_cmd(["git", "config", "--global", "core.quotepath"])
    if ok and qp.strip().lower() == "false":
        rep.good("core.quotepath", "false（中文文件名显示正常）")
    else:
        rep.warning(
            "core.quotepath",
            f"{qp.strip() or '未设置'}（中文文件名会乱码）",
            "git config --global core.quotepath false",
        )

    # 换行符
    ok, ac = run_cmd(["git", "config", "--global", "core.autocrlf"])
    val = ac.strip().lower() if ok else ""
    if val == "true":
        rep.good("core.autocrlf", "true（Windows 正确设置）")
    elif val == "input":
        rep.good("core.autocrlf", "input（Linux/macOS 正确设置）")
    else:
        rep.warning(
            "core.autocrlf",
            f"{val or '未设置'}",
            "Windows 用户请执行： git config --global core.autocrlf true",
        )

    # SSH 是否配好（不实际联网，只看文件在不在）
    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    has_key = any(
        os.path.exists(os.path.join(ssh_dir, f))
        for f in ("id_ed25519", "id_rsa", "id_ecdsa")
    )
    if has_key:
        rep.good("SSH 密钥", "已生成（可用 git@github.com 克隆）")
    else:
        rep.warning(
            "SSH 密钥",
            "未生成",
            "ssh-keygen -t ed25519 -C \"你的邮箱@example.com\"\n"
            "         然后把 ~/.ssh/id_ed25519.pub 的内容贴到 https://github.com/settings/keys",
        )


def check_vscode(rep: Report):
    """④ VS Code（可选，但强烈建议）。"""
    ok, out = run_cmd(["code", "--version"])
    if ok:
        rep.good("VS Code", out.split("\n")[0])
    else:
        rep.warning(
            "VS Code",
            "未在 PATH 中找到（非必须，但强烈建议装）",
            "下载 https://code.visualstudio.com/Download\n"
            "         安装时勾选「添加到 PATH」。本仓库文档有完整插件清单。",
        )


def check_repo(rep: Report):
    """⑤ 仓库文件是否完整。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)

    required = [
        ("README.md", "主文档"),
        (os.path.join("code", "demo_sim.py"), "闭环仿真 demo"),
        (os.path.join("code", "agent", "core.py"), "数据结构"),
        (os.path.join("code", "agent", "agent.py"), "行为状态机"),
        (os.path.join("tools", "walkviz", "walk.py"), "步态引擎"),
        (os.path.join("tools", "walkviz", "index.html"), "3D 可视化"),
        (os.path.join("docs", "01-环境安装.md"), "安装指南"),
    ]
    missing = [d for p, d in required if not os.path.exists(os.path.join(root, p))]
    if not missing:
        rep.good("仓库文件完整性", f"{len(required)}/{len(required)} 齐全")
    else:
        rep.bad(
            "仓库文件完整性",
            f"缺失: {', '.join(missing)}",
            "可能是 clone 不完整，或文件被误删。\n"
            "         重新克隆： git clone <仓库地址>",
        )


def check_demo(rep: Report):
    """⑥ 真的跑一遍 walk.py —— 光检查文件存在是不够的。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    walk = os.path.join(root, "tools", "walkviz", "walk.py")

    if not os.path.exists(walk):
        rep.bad("demo 可运行", "找不到 walk.py", "重新 clone 仓库")
        return

    # 判定标准是「输出里有没有预期的成功标志」，而不是退出码 ——
    # 因为有些 Python 发行版/包装脚本会额外打印内容并返回非零退出码，
    # 用退出码判断会产生假失败。
    ok, out = run_cmd([sys.executable, walk], timeout=30)
    if "OK: 步态生成器工作正常" in out:
        rep.good("demo 可运行", "步态引擎输出正常")
    else:
        rep.bad(
            "demo 可运行",
            "执行失败" + ("" if ok else "（进程返回非零）"),
            f"手动执行看看报什么错：\n"
            f"         {sys.executable} {walk}\n"
            f"         （常见原因见 docs/01-环境安装.md 第 9 章）",
        )

    # 再跑一下闭环仿真（这才是主 demo）
    demo = os.path.join(root, "code", "demo_sim.py")
    if os.path.exists(demo):
        ok2, out2 = run_cmd([sys.executable, demo, "--cycles", "200"], timeout=90)
        if "比赛结束" in out2 and "最终比分" in out2:
            m = re.search(r"最终比分\s*:\s*(\d+)\s*:\s*(\d+)", out2)
            score = f"{m.group(1)}:{m.group(2)}" if m else "?"
            rep.good("闭环仿真", f"跑通，比分 {score}")
        else:
            rep.bad(
                "闭环仿真",
                "执行失败",
                f"手动执行： python {demo} --cycles 200",
            )
    else:
        rep.bad("闭环仿真", "找不到 demo_sim.py", "重新 clone 仓库")


def check_optional_libs(rep: Report):
    """
    ⑦ 可选的进阶库。
    注意：这些【没装完全正常】—— 本仓库的 demo 零依赖。
    真实仿真器（MuJoCo）是第 3 周才需要的东西。
    """
    optional = [
        ("numpy", "数值计算（读论文复现时用）"),
        ("mujoco", "物理仿真引擎（第 3 周才需要）"),
    ]
    found = []
    for mod, desc in optional:
        try:
            __import__(mod)
            found.append(mod)
        except ImportError:
            pass

    if found:
        rep.good("已装的进阶库", ", ".join(found))
    else:
        rep.info(
            "进阶库（numpy / mujoco）均未安装 —— "
            "这是正常的，本仓库 demo 不需要它们。"
        )


def check_path_hygiene(rep: Report):
    """⑧ 路径卫生：中文路径和空格是新手噩梦。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)

    problems = []
    if re.search(r"[\u4e00-\u9fff]", root):
        problems.append("路径含中文")
    if " " in root:
        problems.append("路径含空格")

    if problems:
        rep.warning(
            "项目路径",
            f"{'、'.join(problems)}  ->  {root}",
            "部分编译工具（CMake / make / 老版 MSVC）无法处理\n"
            "         中文或含空格的路径，会在你完全想不到的地方报错。\n"
            "         建议移到 D:\\projects\\robocup3d\\ 这类纯英文无空格路径。",
        )
    else:
        rep.good("项目路径", root)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    print()
    print("=" * 66)
    print(" RoboCup3D 备赛环境体检")
    print("=" * 66)
    print(f" 平台: {platform.system()} {platform.release()}  |  "
          f"Python: {platform.python_version()}")
    print("=" * 66)
    print()

    rep = Report()

    print(" 【基础环境】")
    check_python(rep)
    check_pip(rep)
    print()

    print(" 【版本控制】")
    check_git(rep)
    print()

    print(" 【编辑器】")
    check_vscode(rep)
    print()

    print(" 【仓库与 demo】")
    check_repo(rep)
    check_demo(rep)
    check_path_hygiene(rep)
    print()

    print(" 【进阶组件（可选）】")
    check_optional_libs(rep)
    print()

    # ------------------------------------------------------------------
    print("=" * 66)
    print(" 结论")
    print("=" * 66)
    print(f" 通过 {rep.ok} 项  |  警告 {rep.warn} 项  |  失败 {rep.fail} 项")
    print()

    if rep.fixes:
        print(" 需要处理的问题：")
        for f in rep.fixes:
            print(f)
        print()

    if rep.fail == 0:
        print(" " + _c("32", "✅ 环境可用，可以开始备赛！"))
        print()
        print(" 下一步：")
        print("   cd code")
        print("   python demo_sim.py --cycles 1500      # 跑闭环仿真")
        print("   python demo_sim.py --cycles 400 --render   # 看 ASCII 动画")
        print("   然后双击打开 tools/walkviz/index.html       # 看 3D 可视化")
        print()
        print(" 学习路线见 docs/05-八周训练计划.md")
        return 0

    print(" " + _c("31", f"❌ 有 {rep.fail} 个阻塞性问题，请先按上面的提示修复。"))
    print()
    print(" 报错速查表： docs/01-环境安装.md 第 9 章（25 条常见报错）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
