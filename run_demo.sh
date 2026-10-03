#!/usr/bin/env bash
# ===========================================================================
#  RoboCup3D Demo 一键运行（Linux / macOS / WSL）
# ===========================================================================
#  用法：
#      chmod +x run_demo.sh
#      ./run_demo.sh            # 默认跑闭环仿真
#      ./run_demo.sh render     # ASCII 动画
#      ./run_demo.sh bench      # 基准测试
#      ./run_demo.sh check      # 环境体检
# ===========================================================================

set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo " RoboCup3D 新手 Demo"
echo "============================================================"
echo

# --- 找 Python ---
PY=""
for candidate in ".venv/bin/python" "python3" "python"; do
    if [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[错误] 找不到 Python。"
    echo
    echo "Ubuntu / Debian 安装方法："
    echo "    sudo apt update"
    echo "    sudo apt install python3 python3-venv python3-pip"
    echo
    echo "详见 docs/01-环境安装.md"
    exit 1
fi

if [ -x ".venv/bin/python" ]; then
    echo "[信息] 使用虚拟环境： .venv"
else
    echo "[提示] 没有找到 .venv 虚拟环境，将使用系统 Python。"
    echo "       建议先执行： python3 -m venv .venv && source .venv/bin/activate"
fi
echo "[信息] Python 版本： $("$PY" --version 2>&1)"
echo

CMD="${1:-demo}"

case "$CMD" in
    demo)
        echo "--- 运行闭环仿真 ---"
        "$PY" code/demo_sim.py --cycles 1500
        ;;
    render)
        echo "--- 运行闭环仿真（带 ASCII 动画）---"
        "$PY" code/demo_sim.py --cycles 400 --render
        ;;
    bench)
        echo "--- 基准测试：20 场 ---"
        "$PY" code/demo_sim.py --bench 20
        ;;
    check)
        "$PY" scripts/setup_check.py
        ;;
    viz)
        echo "正在打开 3D 可视化..."
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open tools/walkviz/index.html
        elif command -v open >/dev/null 2>&1; then
            open tools/walkviz/index.html
        else
            echo "请手动用浏览器打开： $(pwd)/tools/walkviz/index.html"
        fi
        ;;
    *)
        echo "未知参数： $CMD"
        echo "用法： $0 [demo|render|bench|check|viz]"
        exit 1
        ;;
esac

echo
echo "============================================================"
echo " 完成。"
echo "============================================================"
