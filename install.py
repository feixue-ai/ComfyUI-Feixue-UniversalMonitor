"""
ComfyUI-Feixue-UniversalMonitor 安装脚本
========================================

Cross-platform 自动依赖安装：
  - Windows: pynvml-amd-windows (ADLX GPU监控), wmi (系统信息)
  - Linux:   amdsmi (AMD GPU监控), 无需额外依赖

ComfyUI Manager 会在安装节点时自动调用此脚本，
用户也可手动运行: python install.py
"""

import subprocess
import sys
import platform
import os


def _get_pip_cmd() -> list:
    """获取当前 Python 环境的 pip 命令"""
    return [sys.executable, "-m", "pip", "install"]


def _is_installed(package_name: str) -> bool:
    """检查包是否已安装"""
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False


def _pip_install(packages: list, desc: str) -> bool:
    """安装 pip 包，返回是否成功"""
    print(f"  [安装] {desc}...")
    try:
        cmd = _get_pip_cmd() + list(packages)
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  [OK] {desc} 安装成功")
        return True
    except subprocess.CalledProcessError:
        print(f"  [警告] {desc} 安装失败，插件将以降级模式运行")
        return False


def install_windows():
    """Windows 平台依赖安装"""
    print("[飞雪监测器] 检测到 Windows 系统")

    deps = {
        "pynvml-amd-windows": "pynvml-amd-windows (ADLX GPU 温度/利用率)",
        "wmi": "wmi (Windows 系统信息)",
    }

    for pkg, desc in deps.items():
        if _is_installed(pkg):
            print(f"  [跳过] {desc} 已安装")
        else:
            _pip_install([pkg], desc)


def install_linux():
    """Linux 平台依赖安装"""
    print("[飞雪监测器] 检测到 Linux 系统")

    # amdsmi 是 pip 包，但底层需要系统包 amd-smi-lib
    if _is_installed("amdsmi"):
        print("  [跳过] amdsmi (AMD GPU 监控) 已安装")
    else:
        _pip_install(["amdsmi"], "amdsmi (AMD GPU 监控)")

    # 检查底层 C 库
    try:
        subprocess.check_output(
            ["ldconfig", "-p"], stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


def install_darwin():
    """macOS 平台依赖安装"""
    print("[飞雪监测器] 检测到 macOS 系统")
    print("  [信息] macOS 无需额外依赖 (使用 sysfs 基础模式)")


def main():
    print("=" * 55)
    print("  飞雪监测器 (Feixue Universal Monitor) v3.0")
    print("  依赖安装脚本")
    print("=" * 55)

    system = platform.system()
    print(f"  系统: {system} ({platform.machine()})")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    if system == "Windows":
        install_windows()
    elif system == "Linux":
        install_linux()
    elif system == "Darwin":
        install_darwin()
    else:
        print(f"  [警告] 未知系统: {system}，跳过依赖安装")

    print()
    print("=" * 55)
    print("  安装完成！重启 ComfyUI 即可使用。")
    print("=" * 55)


if __name__ == "__main__":
    main()