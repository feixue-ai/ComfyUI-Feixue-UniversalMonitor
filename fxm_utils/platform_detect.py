"""
ComfyUI-Feixue-UniversalMonitor - Platform Detection Utilities

Cross-platform environment detection module for identifying:
- Operating system type (Linux/Windows/macOS) with WSL2 awareness
- GPU vendor (AMD/NVIDIA/Intel/Unknown)
- ROCm data source availability and priority ordering
- Windows-specific GPU information collection

Design Principles:
- Defensive programming: all external calls wrapped in try-except
- Caching: detection results cached to avoid repeated expensive queries
- Graceful degradation: safe defaults when detection fails
- Performance: full detection < 500ms, cache hit < 1ms
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from core.data_models import GPUVendor, Platform

logger = logging.getLogger(__name__)

# ============================================================================
# Type Aliases
# ============================================================================

PlatformType = Literal["linux", "windows", "macos"]
VendorType = Literal["amd", "nvidia", "intel", "unknown"]

# ============================================================================
# Module-level Cache
# ============================================================================

_cache: Dict[str, Any] = {}
_cache_timestamp: float = 0.0
_CACHE_TTL: float = 60.0  # Cache TTL in seconds

# WSL detection result (module-level, set once)
_is_wsl: bool = False


def _get_cache_key(func_name: str) -> str:
    """Generate a cache key for a function."""
    return f"platform_detect:{func_name}"


def _is_cache_valid() -> bool:
    """Check if the cache is still valid."""
    if not _cache:
        return False
    return (time.time() - _cache_timestamp) < _CACHE_TTL


def _invalidate_cache():
    """Invalidate the entire detection cache."""
    global _cache, _cache_timestamp
    _cache.clear()
    _cache_timestamp = 0.0
    logger.debug("Platform detection cache invalidated")


def _cached_result(key: str, value: Any) -> Any:
    """Store a value in cache and return it."""
    global _cache_timestamp
    _cache[key] = value
    _cache_timestamp = time.time()
    return value


# ============================================================================
# 1. Operating System Detection
# ============================================================================

def get_platform() -> PlatformType:
    """
    Detect the current operating system type.

    Returns:
        One of "linux", "windows", or "macos".

    Special handling:
        - WSL2 environment returns "linux" but sets module-level ``_is_wsl = True``
        - MSYS2/Cygwin environments return "windows"
        - Unknown systems default to "linux"

    Examples:
        >>> get_platform()
        'linux'
    """
    global _is_wsl
    cache_key = _get_cache_key("platform")

    if _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    system = platform.system().lower()

    if system == "linux":
        # Detect WSL2 environment
        _is_wsl = _check_wsl_environment()
        if _is_wsl:
            logger.info("WSL2 environment detected (reporting as Linux)")
        result = "linux"

    elif system == "windows":
        result = "windows"
        _is_wsl = False

    elif system == "darwin":
        result = "macos"
        _is_wsl = False

    else:
        # Check for MSYS2/Cygwin on Windows
        if "msys" in sys.platform.lower() or "cygwin" in sys.platform.lower():
            result = "windows"
            logger.info(f"MSYS2/Cygwin detected (reporting as Windows): {sys.platform}")
        else:
            result = "linux"  # Default assumption
            logger.warning(f"Unknown platform '{system}', defaulting to Linux")

        _is_wsl = False

    logger.debug(f"Platform detected: {result} (WSL={_is_wsl})")
    return _cached_result(cache_key, result)


def detect_platform() -> Platform:
    """
    Detect current platform and return as :class:`Platform` enum.

    This is a convenience wrapper around :func:`get_platform` that returns
    the project-native :class:`~core.data_models.Platform` enum for backward
    compatibility with existing code.

    Returns:
        :class:`Platform` enum value (LINUX, WINDOWS, or MACOS).
    """
    platform_str = get_platform()
    mapping: Dict[PlatformType, Platform] = {
        "linux": Platform.LINUX,
        "windows": Platform.WINDOWS,
        "macos": Platform.MACOS,
    }
    return mapping.get(platform_str, Platform.LINUX)


def is_wsl() -> bool:
    """
    Check if the current environment is WSL (Windows Subsystem for Linux).

    Returns:
        True if running inside WSL/WSL2, False otherwise.
    """
    # Trigger platform detection if not yet done
    if not _is_wsl and "platform" not in _cache:
        get_platform()
    return _is_wsl


def _check_wsl_environment() -> bool:
    """
    Perform WSL environment detection by reading /proc/version.

    Uses a 2-second timeout to prevent hanging on abnormal filesystems.

    Returns:
        True if WSL indicators are found in /proc/version.
    """
    proc_version = Path("/proc/version")
    if not proc_version.exists():
        return False

    try:
        # Read with timeout-like protection using small file size check
        content = proc_version.read_text(timeout=2).lower()  # type: ignore[arg-type]
        is_wsl_env = "microsoft" in content or "wsl" in content
        if is_wsl_env:
            logger.debug(f"WSL signature found in /proc/version: {content.strip()[:80]}")
        return is_wsl_env
    except FileNotFoundError:
        return False
    except PermissionError:
        logger.debug("Permission denied reading /proc/version")
        return False
    except Exception as e:
        logger.debug(f"Failed to read /proc/version: {e}")
        return False


# ============================================================================
# 2. GPU Vendor Detection
# ============================================================================

def detect_gpu_vendor() -> VendorType:
    """
    Detect the primary GPU vendor.

    Priority order for detection:
        1. **Linux sysfs**: Parse ``/sys/class/drm/cardN/device/vendor``
           - ``0x1002`` = AMD
           - ``0x10de`` = NVIDIA
           - ``0x8086`` = Intel
        2. **Windows PyTorch**: Keyword matching via ``torch.cuda.get_device_name(0)``
        3. **Environment variables**
        4. **lspci command** (Linux fallback)

    Returns:
        One of "amd", "nvidia", "intel", or "unknown".
    """
    cache_key = _get_cache_key("gpu_vendor")

    if _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    vendor = _detect_gpu_vendor_impl()
    logger.info(f"GPU vendor detected: {vendor}")
    return _cached_result(cache_key, vendor)


def _detect_gpu_vendor_impl() -> VendorType:
    """Internal implementation of GPU vendor detection with priority chain."""
    current_os = get_platform()

    # Priority 1: Sysfs-based detection (Linux)
    if current_os == "linux":
        vendor = _detect_vendor_sysfs()
        if vendor != "unknown":
            return vendor

    # Priority 2: Windows PyTorch/device name keyword matching (replaces WMI)
    # PyTorch is always present in ComfyUI; device name is authoritative.
    vendor = _detect_vendor_pytorch()
    if vendor != "unknown":
        return vendor

    # Priority 3: Environment variables
    vendor = _detect_vendor_pytorch()
    if vendor != "unknown":
        return vendor

    # Priority 3: Environment variables
    vendor = _detect_vendor_environment()
    if vendor != "unknown":
        return vendor

    # Priority 4: lspci (Linux fallback)
    if current_os == "linux":
        vendor = _detect_vendor_lspci()
        if vendor != "unknown":
            return vendor

    # Priority 6: Kernel modules (Linux)
    if current_os == "linux":
        vendor = _detect_vendor_kernel_modules()
        if vendor != "unknown":
            return vendor

    return "unknown"


def _detect_vendor_sysfs() -> VendorType:
    """
    Detect GPU vendor via Linux sysfs /sys/class/drm/cardN/device/vendor.

    PCI Vendor IDs:
        - 0x1002 → AMD
        - 0x10de → NVIDIA
        - 0x8086 → Intel

    Returns:
        Vendor string or "unknown".
    """
    drm_path = Path("/sys/class/drm")
    if not drm_path.exists():
        return "unknown"

    vendor_map: Dict[str, VendorType] = {
        "0x1002": "amd",
        "0x10de": "nvidia",
        "0x8086": "intel",
    }

    try:
        for card_path in sorted(drm_path.glob("card[0-9]*")):
            vendor_file = card_path / "device" / "vendor"
            if not vendor_file.exists():
                continue

            try:
                vendor_id = vendor_file.read_text().strip().lower()
                if vendor_id in vendor_map:
                    result = vendor_map[vendor_id]
                    logger.debug(f"sysfs vendor ID {vendor_id} → {result}")
                    return result
            except (IOError, OSError) as e:
                logger.debug(f"Failed to read {vendor_file}: {e}")
                continue
    except Exception as e:
        logger.debug(f"Sysfs vendor detection error: {e}")

    return "unknown"


def _detect_vendor_pytorch() -> VendorType:
    """
    Detect GPU vendor via PyTorch CUDA/HIP interface.

    Checks:
        - torch.version.hip / torch.version.roc → AMD (ROCm)
        - Device name keywords (AMD, NVIDIA, Intel)

    Returns:
        Vendor string or "unknown".
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return "unknown"

        # Method 1: Check HIP/ROCm build attributes (AMD-specific)
        if hasattr(torch.version, "hip"):
            logger.debug("PyTorch HIP build detected → AMD")
            return "amd"
        if hasattr(torch.version, "roc"):
            logger.debug("PyTorch ROCm build detected → AMD")
            return "amd"

        # Method 2: Device name keyword matching
        device_name = torch.cuda.get_device_name(0).lower()

        amd_keywords = ["amd", "radeon", "instinct"]
        nvidia_keywords = ["nvidia", "geforce", "rtx", "gtx", "tesla", "quadro"]
        intel_keywords = ["intel"]

        for kw in amd_keywords:
            if kw in device_name:
                logger.debug(f"PyTorch device name contains '{kw}' → AMD")
                return "amd"

        for kw in nvidia_keywords:
            if kw in device_name:
                logger.debug(f"PyTorch device name contains '{kw}' → NVIDIA")
                return "nvidia"

        for kw in intel_keywords:
            if kw in device_name:
                logger.debug(f"PyTorch device name contains '{kw}' → Intel")
                return "intel"

        # Method 3: Standard CUDA version format implies NVIDIA
        cuda_version = getattr(torch.version, "cuda", None)
        if cuda_version and len(cuda_version.split(".")) >= 2:
            logger.debug(f"CUDA version {cuda_version} detected → NVIDIA")
            return "nvidia"

        logger.debug(f"PyTorch available but vendor unclear: {device_name}")
        return "unknown"

    except ImportError:
        logger.debug("PyTorch not available for vendor detection")
        return "unknown"
    except Exception as e:
        logger.debug(f"PyTorch vendor detection failed: {e}")
        return "unknown"


def _detect_vendor_environment() -> VendorType:
    """
    Detect GPU vendor via environment variables.

    AMD variables: ROCM_PATH, HSA_PATH, AMDGPU_TARGET_TRIPLE, HIP_PLATFORM
    NVIDIA variables: CUDA_PATH, CUDA_HOME, NVIDIA_VISIBLE_DEVICES

    Returns:
        Vendor string or "unknown".
    """
    amd_vars = ["ROCM_PATH", "HSA_PATH", "AMDGPU_TARGET_TRIPLE", "HIP_PLATFORM"]
    nvidia_vars = ["CUDA_PATH", "CUDA_HOME", "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES"]

    for var in amd_vars:
        value = os.environ.get(var, "")
        if value:
            logger.debug(f"Environment variable '{var}={value}' → AMD")
            return "amd"

    for var in nvidia_vars:
        value = os.environ.get(var, "")
        if value:
            logger.debug(f"Environment variable '{var}={value}' → NVIDIA")
            return "nvidia"

    return "unknown"


def _detect_vendor_lspci() -> VendorType:
    """
    Detect GPU vendor via lspci command (Linux fallback).

    Queries VGA-compatible controllers only.

    Returns:
        Vendor string or "unknown".
    """
    try:
        result = subprocess.run(
            ["lspci", "-nn", "-d", "::0300"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.lower()

        if any(kw in output for kw in ["amd", "radeon", "advanced micro devices"]):
            logger.debug("lspci shows AMD GPU")
            return "amd"
        if "nvidia" in output:
            logger.debug("lspci shows NVIDIA GPU")
            return "nvidia"
        if any(kw in output for kw in ["intel corporation", "intel"]):
            logger.debug("lspci shows Intel GPU")
            return "intel"

    except FileNotFoundError:
        logger.debug("lspci command not found")
    except subprocess.TimeoutExpired:
        logger.warning("lspci command timed out after 5 seconds")
    except Exception as e:
        logger.debug(f"lspci vendor detection failed: {e}")

    return "unknown"


def _detect_vendor_kernel_modules() -> VendorType:
    """
    Detect GPU vendor via loaded kernel modules (Linux fallback).

    Checks for amdgpu/nvidia/i915 module presence in /sys/module/.

    Returns:
        Vendor string or "unknown".
    """
    module_checks: List[Tuple[str, str, VendorType]] = [
        ("amdgpu", "AMD", "amd"),
        ("nvidia", "NVIDIA", "nvidia"),
        ("i915", "Intel i915", "intel"),
    ]

    for module_name, label, vendor in module_checks:
        module_path = Path(f"/sys/module/{module_name}")
        if module_path.exists():
            logger.debug(f"Kernel module '{module_name}' loaded → {label}")
            return vendor

    # Also check nvidia driver directory
    if Path("/proc/driver/nvidia").exists():
        logger.debug("nvidia driver present at /proc/driver/nvidia → NVIDIA")
        return "nvidia"

    return "unknown"


def get_gpu_device_name() -> str:
    """
    Get the GPU device model name string.

    Tries multiple sources in priority order:
        1. PyTorch ``torch.cuda.get_device_name(0)``
        2. Linux sysfs uevent/model files
        3. Fallback: "Unknown GPU"

    Returns:
        Human-readable GPU model name string.
    """
    cache_key = _get_cache_key("gpu_device_name")

    if _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    name = _get_gpu_device_name_impl()
    logger.debug(f"GPU device name: {name}")
    return _cached_result(cache_key, name)


def _get_gpu_device_name_impl() -> str:
    """Internal implementation for GPU device name retrieval."""
    # Try PyTorch first
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            if name:
                return str(name)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"PyTorch device name failed: {e}")

    # Try Linux sysfs
    current_os = get_platform()
    if current_os == "linux":
        name = _get_gpu_name_from_sysfs()
        if name:
            return name

    return "Unknown GPU"


def _get_gpu_name_from_sysfs() -> Optional[str]:
    """
    Extract GPU name from Linux sysfs uevent/model files.

    Returns:
        Device name string or None if unavailable.
    """
    drm_path = Path("/sys/class/drm")
    if not drm_path.exists():
        return None

    for card_path in sorted(drm_path.glob("card[0-9]*")):
        # Try uevent file first (contains PRODUCT= info)
        uevent_path = card_path / "device" / "uevent"
        if uevent_path.exists():
            try:
                content = uevent_path.read_text()
                for line in content.splitlines():
                    if line.startswith("PRODUCT=") or line.startswith("MODEL=") or line.startswith("PCI_NAME="):
                        name = line.split("=", 1)[1].strip().strip("'\"")
                        if name:
                            return name
            except (IOError, OSError):
                continue

        # Try model file
        model_path = card_path / "device" / "model"
        if model_path.exists():
            try:
                name = model_path.read_text().strip()
                if name:
                    return name
            except (IOError, OSError):
                continue

    return None


# ============================================================================
# 3. ROCm Availability and Data Source Detection
# ============================================================================

def detect_rocm_availability() -> Dict[str, Any]:
    """
    Detect ROCm-related library availability and determine optimal data sources.

    Returns:
        Dictionary with the following keys:

        .. code-block:: python

            {
                "amdsmi_available": bool,       # ROCm 6.0+ recommended
                "rocm_smi_lib_available": bool,  # ROCm 5.x compatible
                "sysfs_available": bool,         # Zero-dependency fallback
                "rocm_version": Optional[str],   # ROCm version string if obtainable
                "recommended_source": str,       # Top-priority available source name
                "priority_list": List[str],      # Full priority-ordered list of available sources
            }

    The priority list follows: ``["amdsmi", "rocm_smi_lib", "sysfs"]`` on Linux,
    and ``["directml", "pytorch", "psutil"]`` on Windows.
    """
    cache_key = _get_cache_key("rocm_availability")

    if _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    result = _detect_rocm_availability_impl()
    logger.info(
        f"ROCm availability: amdsmi={result['amdsmi_available']}, "
        f"rocm_smi_lib={result['rocm_smi_lib_available']}, "
        f"sysfs={result['sysfs_available']}, "
        f"recommended={result['recommended_source']}"
    )
    return _cached_result(cache_key, result)


def _detect_rocm_availability_impl() -> Dict[str, Any]:
    """Internal implementation for ROCm availability detection."""
    current_os = get_platform()

    amdsmi_avail = check_amdsmi()
    rocm_smi_avail = check_rocm_smi_lib()

    if current_os == "linux":
        sysfs_avail = _check_sysfs_amd_available()
        rocm_version = _query_rocm_version()
        priority_list: List[str] = []
        if amdsmi_avail:
            priority_list.append("amdsmi")
        if rocm_smi_avail:
            priority_list.append("rocm_smi_lib")
        if sysfs_avail:
            priority_list.append("sysfs")
        recommended = priority_list[0] if priority_list else "generic"

        return {
            "amdsmi_available": amdsmi_avail,
            "rocm_smi_lib_available": rocm_smi_avail,
            "sysfs_available": sysfs_avail,
            "rocm_version": rocm_version,
            "recommended_source": recommended,
            "priority_list": priority_list,
        }

    elif current_os == "windows":
        directml_avail = _check_directml_available()
        pytorch_avail = _check_pytorch_cuda_available()
        psutil_avail = _check_psutil_available()

        win_priority: List[str] = []
        if directml_avail:
            win_priority.append("directml")
        if pytorch_avail:
            win_priority.append("pytorch")
        if psutil_avail:
            win_priority.append("psutil")
        win_recommended = win_priority[0] if win_priority else "generic"

        return {
            "amdsmi_available": False,
            "rocm_smi_lib_available": False,
            "sysfs_available": False,
            "rocm_version": None,
            "recommended_source": win_recommended,
            "priority_list": win_priority,
        }

    else:
        # macOS or other
        return {
            "amdsmi_available": False,
            "rocm_smi_lib_available": False,
            "sysfs_available": False,
            "rocm_version": None,
            "recommended_source": "generic",
            "priority_list": [],
        }


def check_amdsmi() -> bool:
    """
    Check if the amdsmi library (ROCm 6.0+) is available and functional.

    Attempts to initialize amdsmi to verify it works, not just that it imports.

    Returns:
        True if amdsmi can be imported and initialized successfully.
    """
    try:
        import amdsmi

        amdsmi.amdsmi_init()
        logger.debug("amdsmi library imported and initialized successfully")
        return True
    except ImportError:
        logger.debug("amdsmi library not installed (ImportError)")
        return False
    except AttributeError:
        # Library exists but amdsmi_init may not be available
        logger.debug("amdsmi imported but amdsmi_init not found (possibly incompatible version)")
        return False
    except Exception as e:
        logger.debug(f"amdsmi initialization failed: {e}")
        return False


def check_rocm_smi_lib() -> bool:
    """
    Check if the rocm_smi_lib library (ROCm 5.x compatible) is available.

    Note:
        The Python package is typically importable as ``rocm_smi`` (not ``rocm_smi_lib``).
        This function checks both possible import names.

    Returns:
        True if rocm_smi_lib can be imported.
    """
    # Try both possible package names
    for import_name in ("rocm_smi", "rocm_smi_lib"):
        try:
            __import__(import_name)
            logger.debug(f"{import_name} library is available")
            return True
        except ImportError:
            continue

    logger.debug("rocm_smi_lib library not installed")
    return False


def _check_sysfs_amd_available() -> bool:
    """
    Check if sysfs AMD GPU interface is available (Linux only).

    Verifies that /sys/class/drm/ exists and contains AMD GPU devices
    (vendor ID 0x1002).

    Returns:
        True if AMD GPU devices are accessible via sysfs.
    """
    drm_base = Path("/sys/class/drm")
    if not drm_base.exists():
        return False

    try:
        for card in drm_base.glob("card[0-9]*"):
            vendor_file = card / "device" / "vendor"
            if vendor_file.exists():
                try:
                    if vendor_file.read_text().strip() == "0x1002":
                        logger.debug("sysfs AMD GPU interface available")
                        return True
                except (IOError, OSError):
                    continue
    except Exception as e:
        logger.debug(f"sysfs AMD check failed: {e}")

    return False


def _query_rocm_version() -> Optional[str]:
    """
    Attempt to retrieve the installed ROCm version string.

    Methods tried (in order):
        1. ``rocm-smi --version`` command output parsing
        2. ``/opt/rocm/.info/version`` file
        3. ``dpkg -l rocm-dev`` package version

    Returns:
        Version string like "6.0.2" or None if undetectable.
    """
    # Method 1: rocm-smi --version
    try:
        result = subprocess.run(
            ["rocm-smi", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr
        # Common formats: "ROCm Version: 6.0.2", "rocm-smi version 5.7.x"
        import re
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", output)
        if match:
            version = match.group(1)
            logger.debug(f"ROCm version from rocm-smi: {version}")
            return version
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        logger.debug(f"rocm-smi version query failed: {e}")

    # Method 2: /opt/rocm/.info/version
    version_file = Path("/opt/rocm/.info/version")
    if version_file.exists():
        try:
            version = version_file.read_text().strip()
            if version:
                logger.debug(f"ROCm version from file: {version}")
                return version
        except (IOError, OSError) as e:
            logger.debug(f"Failed to read ROCm version file: {e}")

    # Method 3: dpkg query
    try:
        result = subprocess.run(
            ["dpkg", "-l", "rocm-dev"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        import re
        match = re.search(r"\S+\s+(\S+)\s+", result.stdout)
        if match:
            version = match.group(1).rstrip(":").split("-")[0]
            if version and version != "<none>":
                logger.debug(f"ROCm version from dpkg: {version}")
                return version
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"dpkg ROCm version query failed: {e}")

    return None


def _check_directml_available() -> bool:
    """Check if DirectML backend is available."""
    try:
        import torch
        # Check for DirectML device
        # DirectML devices appear as 'privateuseone' backend
        return hasattr(torch, "directml") or "directml" in str(torch.__dict__.keys()).lower()
    except ImportError:
        return False
    except Exception:
        return False


def _check_pytorch_cuda_available() -> bool:
    """Check if PyTorch with CUDA support is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False
    except Exception:
        return False


def _check_psutil_available() -> bool:
    """Check if psutil is available."""
    try:
        import psutil
        return True
    except ImportError:
        return False


def check_amd_smi_availability() -> Dict[str, bool]:
    """
    Check availability of various AMD SMI libraries.

    This is a legacy compatibility wrapper that returns a simple dictionary.
    New code should use :func:`detect_rocm_availability` instead.

    Returns:
        Dictionary with keys ``"amdsmi"``, ``"rocm_smi_lib"``, ``"sysfs"``.
    """
    rocm_info = detect_rocm_availability()
    return {
        "amdsmi": rocm_info["amdsmi_available"],
        "rocm_smi_lib": rocm_info["rocm_smi_lib_available"],
        "sysfs": rocm_info["sysfs_available"],
    }


# ============================================================================
# 4. Windows-Specific Detection
# ============================================================================

def detect_windows_gpu_info() -> Dict[str, Any]:
    """
    Collect comprehensive GPU information on Windows platforms.

    Gathers data from multiple sources:
        - PyTorch ``torch.cuda.get_device_name(0)`` (adapter name, vendor)
        - DirectML availability
        - Administrative privilege status

    Returns:
        Dictionary with keys:

        .. code-block:: python

            {
                "vendor": str,               # Detected vendor
                "name": str,                 # Adapter/product name
                "driver_version": str,       # Driver version string (empty)
                "directml_available": bool,  # Whether DirectML is usable
                "admin_privileges": bool,    # Current process has admin rights
            }

    On non-Windows platforms, returns a dict with default/empty values.
    """
    cache_key = _get_cache_key("windows_gpu_info")

    if _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    result = _detect_windows_gpu_info_impl()
    logger.debug(f"Windows GPU info: vendor={result['vendor']}, name={result['name'][:40] if result['name'] else 'N/A'}")
    return _cached_result(cache_key, result)


def _detect_windows_gpu_info_impl() -> Dict[str, Any]:
    """Internal implementation for Windows GPU info collection."""
    current_os = get_platform()

    default_result: Dict[str, Any] = {
        "vendor": "unknown",
        "name": "",
        "driver_version": "",
        "directml_available": False,
        "admin_privileges": False,
    }

    if current_os != "windows":
        return default_result

    result = default_result.copy()
    result["admin_privileges"] = is_admin()

    # Use PyTorch device name for vendor/name info; no WMI dependency.
    try:
        import torch
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            name = str(torch.cuda.get_device_name(0))
            name_lower = name.lower()
            if any(kw in name_lower for kw in ("amd", "radeon", "ati")):
                result["vendor"] = "amd"
            elif any(kw in name_lower for kw in ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla")):
                result["vendor"] = "nvidia"
            elif any(kw in name_lower for kw in ("intel", "uhd", "iris", "arc", "xe")):
                result["vendor"] = "intel"
            result["name"] = name
    except Exception:
        pass

    # Check DirectML
    result["directml_available"] = _check_directml_available()

    return result


def is_admin() -> bool:
    """
    Check if the current process has administrative privileges (Windows only).

    On non-Windows platforms, always returns False.

    Returns:
        True if running with admin/elevated rights, False otherwise.
    """
    if platform.system() != "Windows":
        return False

    try:
        import ctypes
        import ctypes.wintypes

        # Attempt to open the process token with admin-level access
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except (AttributeError, OSError):
            pass

        # Fallback: check via ctypes token elevation
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            token = ctypes.wintypes.HANDLE()
            if ctypes.windll.advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
                elevation = ctypes.c_long()
                size = ctypes.wintypes.DWORD(4)
                result = ctypes.windll.advapi32.GetTokenInformation(
                    token, 20,  # TokenElevation
                    ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(size),
                )
                ctypes.windll.kernel32.CloseHandle(token)
                return result != 0 and elevation.value != 0
        except (AttributeError, OSError):
            pass

    except Exception as e:
        logger.debug(f"Admin privilege check failed: {e}")

    return False


# ============================================================================
# 5. System Information Summary
# ============================================================================

def get_system_info() -> Dict[str, Any]:
    """
    Collect a comprehensive system information summary.

    Aggregates all detection results into a single convenient dictionary
    suitable for logging, diagnostics, or UI display.

    Returns:
        Dictionary with the following structure:

        .. code-block:: python

            {
                "platform": str,              # "linux" | "windows" | "macos"
                "platform_version": str,       # OS version string (e.g., "22.04")
                "architecture": str,           # CPU architecture (e.g., "x86_64")
                "hostname": str,               # Machine hostname
                "python_version": str,         # Python version (e.g., "3.11.5")
                "gpu_vendor": str,             # "amd" | "nvidia" | "intel" | "unknown"
                "gpu_name": str,               # GPU model name
                "is_wsl": bool,                # WSL environment flag
                "rocm_info": dict,             # ROCm availability details
                "total_memory_gb": float,      # Total system RAM in GB
                "cpu_cores": int,              # Logical CPU core count
            }
    """
    cache_key = _get_cache_key("system_info")

    if _is_cache_valid() and cache_key in _cache:
        return _cache[cache_key]

    result = _build_system_info()

    logger.info(
        f"System Info: {result['platform']} / {result['architecture']} / "
        f"Python {result['python_version']} / GPU: {result['gpu_vendor']} {result['gpu_name']} / "
        f"RAM: {result['total_memory_gb']:.1f}GB / Cores: {result['cpu_cores']} / WSL: {result['is_wsl']}"
    )
    return _cached_result(cache_key, result)


def _build_system_info() -> Dict[str, Any]:
    """Build the complete system information dictionary."""
    # Platform basics
    plat = get_platform()
    plat_ver = _get_platform_version()
    arch = platform.machine().lower()
    hostname = platform.node()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    # GPU information
    gpu_vendor = detect_gpu_vendor()
    gpu_name = get_gpu_device_name()

    # ROCm information
    rocm_info = detect_rocm_availability()

    # Hardware resources (via psutil)
    total_memory_gb = _get_total_memory_gb()
    cpu_cores = _get_cpu_core_count()

    return {
        "platform": plat,
        "platform_version": plat_ver,
        "architecture": arch,
        "hostname": hostname,
        "python_version": py_ver,
        "gpu_vendor": gpu_vendor,
        "gpu_name": gpu_name,
        "is_wsl": is_wsl(),
        "rocm_info": rocm_info,
        "total_memory_gb": total_memory_gb,
        "cpu_cores": cpu_cores,
    }


def _get_platform_version() -> str:
    """
    Get the operating system version string.

    Handles platform-specific version extraction:
        - Linux: Distro info from /etc/os-release
        - Windows: Version from platform.release()/version()
        - macOS: Version from platform.mac_ver()

    Returns:
        Version string or empty string on failure.
    """
    try:
        if get_platform() == "linux":
            # Try /etc/os-release for distro version
            os_release = Path("/etc/os-release")
            if os_release.exists():
                try:
                    content = os_release.read_text()
                    for line in content.splitlines():
                        if line.startswith("VERSION_ID="):
                            return line.split("=", 1)[1].strip().strip("'\"")
                        if line.startswith("PRETTY_NAME="):
                            pretty = line.split("=", 1)[1].strip().strip("'\"")
                            # Extract version from pretty name (e.g., "Ubuntu 22.04.3 LTS")
                            import re
                            match = re.search(r"(\d+\.?\d*)", pretty)
                            if match:
                                return match.group(1)
                except (IOError, OSError):
                    pass
            return platform.release()

        elif get_platform() == "windows":
            return platform.release()  # e.g., "10", "11"

        elif get_platform() == "macos":
            ver = platform.mac_ver()[0]
            return ver if ver else platform.release()

    except Exception as e:
        logger.debug(f"Platform version detection failed: {e}")

    return platform.release()


def _get_total_memory_gb() -> float:
    """
    Get total system physical memory in gigabytes.

    Uses psutil if available, falls back to crude estimation.

    Returns:
        Total RAM in GB (float), 0.0 on failure.
    """
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 2)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"psutil memory query failed: {e}")

    # Fallback: try reading from /proc/meminfo (Linux)
    if get_platform() == "linux":
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            try:
                content = meminfo.read_text()
                for line in content.splitlines():
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 2)
            except (ValueError, IOError, OSError):
                pass

    return 0.0


def _get_cpu_core_count() -> int:
    """
    Get the number of logical CPU cores.

    Uses psutil.cpu_count() if available, falls back to os.cpu_count().

    Returns:
        Number of logical cores (int), 0 on failure.
    """
    try:
        import psutil
        count = psutil.cpu_count(logical=True)
        return count if count else 0
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"psutil CPU count failed: {e}")

    try:
        count = os.cpu_count()
        return count if count else 0
    except Exception:
        return 0


# ============================================================================
# Public API Summary & Cache Management
# ============================================================================

def invalidate_cache() -> None:
    """
    Manually invalidate the platform detection cache.

    Call this when hardware configuration changes (e.g., GPU hotplug)
    or when fresh detection results are needed.
    """
    _invalidate_cache()
    logger.info("Platform detection cache manually invalidated")


def get_cache_status() -> Dict[str, Any]:
    """
    Get the current status of the detection cache.

    Returns:
        Dictionary with cache metadata:

        .. code-block:: python

            {
                "is_valid": bool,          # Whether cache is still within TTL
                "age_seconds": float,      # Age of cache in seconds (0 if invalid)
                "entry_count": int,        # Number of cached entries
                "ttl_seconds": float,      # Configured TTL
                "cached_keys": List[str],  # Names of cached detection results
        }
    """
    if not _cache:
        return {
            "is_valid": False,
            "age_seconds": 0.0,
            "entry_count": 0,
            "ttl_seconds": _CACHE_TTL,
            "cached_keys": [],
        }

    age = time.time() - _cache_timestamp
    return {
        "is_valid": _is_cache_valid(),
        "age_seconds": round(age, 2),
        "entry_count": len(_cache),
        "ttl_seconds": _CACHE_TTL,
        "cached_keys": list(_cache.keys()),
    }
