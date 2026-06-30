"""
ComfyUI-Feixue-UniversalMonitor 安装脚本
========================================

平台 + 硬件感知的按需依赖安装：

  优先使用系统原生接口（零 pip 依赖）：
    - Windows AMD: atiadlxx.dll / atiadlxy.dll (ctypes ADL)
    - Windows NVIDIA: nvml.dll (ctypes NVML)
    - Windows 兜底: pdh.dll (系统性能计数器)
    - Linux AMD: /sys/class/drm (sysfs 原生接口，零 pip / 零 ROCm), libamd_smi.so (ctypes AMD SMI 增强兜底)
    - Linux NVIDIA: libnvidia-ml.so (ctypes NVML)

  不再安装以下不准确或不必要的包：
    - pynvml-amd-windows（第三方“破解”式 N 卡方案）
    - wmi（不准确、资源占用高）
    - ADLXPybind（Windows A 卡已可通过 atiadlxx.dll 原生驱动接口获取）

安装原则：
  1. 检测环境需要不需要依赖
  2. 缺就安装，不缺就不安装
  3. 能用原生 DLL 就不用 pip 包
  4. 数据不准的方案直接弃用，不存在“降级造假”

ComfyUI Manager 会在安装节点时自动调用此脚本，
用户也可手动运行: python install.py
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from typing import Optional, Set


def _get_pip_cmd() -> list:
    """获取当前 Python 环境的 pip 命令"""
    return [sys.executable, "-m", "pip", "install"]


def _is_installed(package_name: str) -> bool:
    """检查 Python 包是否已安装"""
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False


def _pip_install(packages: list, desc: str) -> bool:
    """安装 pip 包，失败不阻塞插件运行，保留错误日志便于排障"""
    print(f"  [安装] {desc}...")
    try:
        cmd = _get_pip_cmd() + list(packages)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print(f"  [OK] {desc} 安装成功")
            return True
        else:
            # 记录错误日志（取最后 3 行，避免刷屏）
            err_lines = result.stderr.strip().splitlines()[-3:]
            for line in err_lines:
                print(f"  [错误] {line}")
            print(f"  [警告] {desc} 安装失败，将使用原生接口继续")
            return False
    except subprocess.TimeoutExpired:
        print(f"  [警告] {desc} 安装超时（120s），将使用原生接口继续")
        return False
    except subprocess.CalledProcessError as e:
        print(f"  [警告] {desc} 安装失败: {e}，将使用原生接口继续")
        return False
    except Exception as e:
        print(f"  [警告] {desc} 安装异常: {e}，将使用原生接口继续")
        return False


def _has_windows_dll(dll_name: str) -> bool:
    """检测 Windows 系统是否已存在指定 DLL（显卡驱动自带）"""
    import ctypes

    try:
        handle = ctypes.CDLL(dll_name)
        return handle is not None
    except OSError:
        return False


def _detect_windows_gpu_vendors() -> Set[str]:
    """通过原生 DLL 检测 Windows GPU 厂商，零额外依赖"""
    vendors: Set[str] = set()

    # AMD 驱动自带 ADL DLL
    if _has_windows_dll("atiadlxx.dll") or _has_windows_dll("atiadlxy.dll"):
        vendors.add("amd")

    # NVIDIA 驱动自带 NVML DLL
    if _has_windows_dll("nvml.dll"):
        vendors.add("nvidia")

    # 兜底：通过系统路径显式再检查一次
    if not vendors:
        nvml_path = r"C:\Windows\System32\nvml.dll"
        if os.path.exists(nvml_path):
            vendors.add("nvidia")

    return vendors


def _read_file(path: str) -> Optional[str]:
    """安全读取文件内容"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return None


def _detect_linux_gpu_vendors() -> Set[str]:
    """通过 sysfs / lspci 检测 Linux GPU 厂商，零额外依赖"""
    vendors: Set[str] = set()

    # 1. sysfs DRM vendor
    drm_base = "/sys/class/drm"
    if os.path.isdir(drm_base):
        for entry in os.listdir(drm_base):
            vendor_path = os.path.join(drm_base, entry, "device", "vendor")
            vid = _read_file(vendor_path)
            if vid:
                vid_lower = vid.lower()
                if vid_lower == "0x1002":
                    vendors.add("amd")
                elif vid_lower == "0x10de":
                    vendors.add("nvidia")

    # 2. lspci 兜底
    if not vendors:
        try:
            result = subprocess.run(
                ["lspci", "-nn"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.lower()
            if any(k in output for k in ("amd", "ati", "radeon")):
                vendors.add("amd")
            if "nvidia" in output:
                vendors.add("nvidia")
        except Exception:
            pass

    return vendors


def _linux_has_amd_smi_lib() -> bool:
    """检测系统级 AMD SMI C 库是否存在"""
    try:
        output = subprocess.check_output(
            ["ldconfig", "-p"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return "libamd_smi.so" in output
    except Exception:
        # ldconfig 不可用时尝试直接找库文件
        for path in (
            "/opt/rocm/lib/libamd_smi.so",
            "/opt/rocm/lib/libamd_smi.so.1",
            "/usr/lib/x86_64-linux-gnu/libamd_smi.so",
            "/usr/lib64/libamd_smi.so",
        ):
            if os.path.exists(path):
                return True
        return False


def _linux_has_rocm_smi() -> bool:
    """检测 rocm-smi 系统工具是否存在"""
    try:
        subprocess.check_call(
            ["rocm-smi", "--showid"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _linux_has_nvidia_driver() -> bool:
    """检测 NVIDIA 驱动/库是否存在"""
    for path in (
        "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
        "/usr/lib64/libnvidia-ml.so.1",
        "/usr/lib/libnvidia-ml.so.1",
    ):
        if os.path.exists(path):
            return True
    try:
        subprocess.run(
            ["nvidia-smi", "-L"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except Exception:
        return False


def install_windows():
    """Windows 平台：原生 DLL 优先，不装不准确包"""
    print("[飞雪监测器] Windows 平台")

    vendors = _detect_windows_gpu_vendors()
    if not vendors:
        print("  [信息] 未检测到 AMD/NVIDIA 显卡驱动 DLL，跳过 GPU 依赖安装")
        print("         安装对应显卡驱动后将自动使用原生接口监控")
        return

    print(f"  [信息] 检测到 GPU 厂商: {', '.join(sorted(vendors)).upper()}")

    if "amd" in vendors:
        print("  [跳过] AMD ADL 原生驱动接口可用（atiadlxx.dll），无需 pip 依赖")

    if "nvidia" in vendors:
        print("  [跳过] NVIDIA NVML 原生驱动接口可用（nvml.dll），无需 pip 依赖")

    print("  [信息] Windows GPU 监控使用系统原生接口，零 pip 依赖")


def install_linux():
    """Linux 平台：原生接口优先，无额外 pip 依赖"""
    print("[飞雪监测器] Linux 平台")

    vendors = _detect_linux_gpu_vendors()
    if not vendors:
        print("  [信息] 未检测到 AMD/NVIDIA GPU，跳过 GPU 依赖安装")
        return

    print(f"  [信息] 检测到 GPU 厂商: {', '.join(sorted(vendors)).upper()}")

    if "amd" in vendors:
        has_amd_smi_lib = _linux_has_amd_smi_lib()
        has_rocm_smi = _linux_has_rocm_smi()

        if has_amd_smi_lib:
            print("  [信息] 检测到系统级 AMD SMI 库（libamd_smi.so）")
            print("         插件将直接通过 ctypes 调用，无需 pip 包或 C++ 编译")
        else:
            print("  [信息] 未检测到系统级 AMD SMI 库，不安装 amdsmi pip 包")
            print("         将使用 /sys/class/drm (sysfs) 原生接口监控 AMD GPU")

        if has_rocm_smi:
            print("  [跳过] rocm-smi 系统工具可用")
        else:
            print("  [信息] rocm-smi 系统工具未安装（非必需，有 sysfs 兜底）")

    if "nvidia" in vendors:
        if _linux_has_nvidia_driver():
            print("  [跳过] NVIDIA 驱动/NVML 已安装，无需 pip 依赖")
        else:
            print("  [警告] 未检测到 NVIDIA 驱动，NVIDIA GPU 监控可能不可用")


def install_darwin():
    """macOS 平台：无 GPU 监控依赖需求"""
    print("[飞雪监测器] macOS 平台")
    print("  [信息] macOS 无原生 GPU 监控依赖需求")


def main():
    print("=" * 60)
    print("  飞雪监测器 (Feixue Universal Monitor)")
    print("  平台 + 硬件感知按需依赖安装")
    print("=" * 60)

    system = platform.system()
    print(f"  系统: {system} ({platform.machine()})")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    # 安装基础依赖（仅 psutil 等真正跨平台通用包）
    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if os.path.exists(req_file):
        _pip_install(["-r", req_file], "基础依赖 (requirements.txt)")

    if system == "Windows":
        install_windows()
    elif system == "Linux":
        install_linux()
    elif system == "Darwin":
        install_darwin()
    else:
        print(f"  [警告] 未知系统: {system}，跳过依赖安装")

    print()
    print("=" * 60)
    print("  安装完成。重启 ComfyUI 即可使用。")
    print("=" * 60)


if __name__ == "__main__":
    main()
