"""
AMD SMI GPU Provider (Linux)

Uses Python ctypes to directly call the system-installed libamd_smi.so,
eliminating the Python `amdsmi` pip dependency and avoiding any C++ bridge
compilation.

Called C API subset (structurally stable across ROCm 5.x/6.x/7.x):
- amdsmi_init / amdsmi_shut_down
- amdsmi_get_socket_handles / amdsmi_get_processor_handles
- amdsmi_get_processor_type / amdsmi_get_processor_info
- amdsmi_get_gpu_vram_usage
- amdsmi_get_gpu_activity
- amdsmi_get_temp_metric
- amdsmi_get_power_info
"""

from __future__ import annotations

import ctypes
import ctypes.util
import glob
import logging
import os
import platform
import sys
from ctypes import CDLL
from pathlib import Path
from typing import List, Optional

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


# AMD SMI constants (from /opt/rocm/include/amd_smi/amdsmi.h)
AMDSMI_MAX_STRING_LENGTH = 256
AMDSMI_MAX_DEVICES = 32

AMDSMI_INIT_AMD_GPUS = 1 << 1
AMDSMI_STATUS_SUCCESS = 0

AMDSMI_PROCESSOR_TYPE_AMD_GPU = 1

AMDSMI_TEMPERATURE_TYPE_EDGE = 0
AMDSMI_TEMPERATURE_TYPE_HOTSPOT = 1
AMDSMI_TEMPERATURE_TYPE_JUNCTION = 1
AMDSMI_TEMPERATURE_TYPE_VRAM = 2

AMDSMI_TEMP_CURRENT = 0


class AmdSmiVramUsage(ctypes.Structure):
    _fields_ = [
        ("vram_total", ctypes.c_uint32),
        ("vram_used", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 2),
    ]


class AmdSmiEngineUsage(ctypes.Structure):
    _fields_ = [
        ("gfx_activity", ctypes.c_uint32),
        ("umc_activity", ctypes.c_uint32),
        ("mm_activity", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 13),
    ]


class AmdSmiPowerInfo(ctypes.Structure):
    _fields_ = [
        ("socket_power", ctypes.c_uint64),
        ("current_socket_power", ctypes.c_uint32),
        ("average_socket_power", ctypes.c_uint32),
        ("gfx_voltage", ctypes.c_uint64),
        ("soc_voltage", ctypes.c_uint64),
        ("mem_voltage", ctypes.c_uint64),
        ("power_limit", ctypes.c_uint32),
        ("reserved", ctypes.c_uint64 * 18),
    ]


class AmdSmiAsicInfo(ctypes.Structure):
    _fields_ = [
        ("market_name", ctypes.c_char * AMDSMI_MAX_STRING_LENGTH),
        ("vendor_id", ctypes.c_uint32),
        ("vendor_name", ctypes.c_char * AMDSMI_MAX_STRING_LENGTH),
        ("subvendor_id", ctypes.c_uint32),
        ("device_id", ctypes.c_uint64),
        ("rev_id", ctypes.c_uint32),
        ("asic_serial", ctypes.c_char * AMDSMI_MAX_STRING_LENGTH),
        ("oam_id", ctypes.c_uint32),
        ("num_of_compute_units", ctypes.c_uint32),
        ("target_graphics_version", ctypes.c_uint64),
        ("subsystem_id", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 21),
    ]


class AmdSmiProvider(BaseGPUProvider):
    """基于 AMD SMI C 库的 AMD GPU 数据提供者（ctypes 直接调用）。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-smi", priority=0, config=config)
        self._lib: Optional[ctypes.CDLL] = None
        self._handles: List[int] = []
        self._device_names: List[str] = []
        self._initialized = False
        self._available_functions: set[str] = set()

    @property
    def priority(self) -> int:
        return 0

    def _discover_rocm_paths(self) -> List[str]:
        """发现系统中可能的 ROCm 安装路径。"""
        paths: List[str] = []

        # 1. 环境变量显式指定（最高优先级）
        env_path = os.environ.get("FEIXUE_AMD_SMI_PATH")
        if env_path:
            paths.append(env_path)

        # 2. /opt/rocm 符号链接（当前默认激活版本）
        if os.path.islink("/opt/rocm"):
            paths.append("/opt/rocm")
        if os.path.isdir("/opt/rocm"):
            paths.append("/opt/rocm")

        # 3. /opt/rocm-<version> 多版本目录（按版本号降序，优先新版本）
        rocm_version_dirs = sorted(
            glob.glob("/opt/rocm-[0-9]*"),
            key=lambda p: [int(x) for x in os.path.basename(p).replace("rocm-", "").split(".")],
            reverse=True,
        )
        paths.extend(rocm_version_dirs)

        # 4. 从 LD_LIBRARY_PATH 解析
        ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
        for part in ld_library_path.split(os.pathsep):
            part = part.strip()
            if part and os.path.isdir(part):
                paths.append(part)

        # 5. 从 amd-smi / rocminfo 等可执行文件定位（如果存在）
        for exe_dir in os.environ.get("PATH", "").split(os.pathsep):
            exe_dir = exe_dir.strip()
            if not exe_dir:
                continue
            # 如果 bin 在 /opt/rocm-X.Y/bin，则其 ../lib 或 ../lib64 可能包含库
            parent = os.path.dirname(exe_dir)
            if parent.startswith("/opt/rocm"):
                if os.path.isdir(parent):
                    paths.append(parent)

        # 6. 常见系统路径
        paths.extend([
            "/usr/local/lib",
            "/usr/local/lib64",
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib64",
            "/usr/lib",
        ])

        # 去重并保持顺序
        seen = set()
        unique_paths: List[str] = []
        for p in paths:
            resolved = os.path.realpath(p)
            if resolved not in seen:
                seen.add(resolved)
                unique_paths.append(p)
        return unique_paths

    def _load_library(self) -> Optional[ctypes.CDLL]:
        """尝试加载 libamd_smi.so，支持多种常见路径和 ROCm 多版本。"""
        candidates: List[str] = []

        # ctypes.util.find_library 会搜索系统库路径和 LD_LIBRARY_PATH
        found = ctypes.util.find_library("amd_smi")
        if found:
            candidates.append(found)

        # 在发现的 ROCm 路径中查找库文件
        for base in self._discover_rocm_paths():
            candidates.extend([
                os.path.join(base, "libamd_smi.so"),
                os.path.join(base, "lib", "libamd_smi.so"),
                os.path.join(base, "lib64", "libamd_smi.so"),
                # 带版本号的 so 文件（处理不同 ROCm 版本命名）
                *sorted(glob.glob(os.path.join(base, "libamd_smi.so*")), reverse=True),
                *sorted(glob.glob(os.path.join(base, "lib", "libamd_smi.so*")), reverse=True),
                *sorted(glob.glob(os.path.join(base, "lib64", "libamd_smi.so*")), reverse=True),
            ])

        # 兜底：裸库名，依赖系统动态链接器
        candidates.append("libamd_smi.so")

        # 去重
        seen = set()
        unique_candidates: List[str] = []
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            unique_candidates.append(path)

        last_error = ""
        for path in unique_candidates:
            try:
                lib = ctypes.CDLL(path)
                logger.debug("amd-smi: loaded library from %s", path)
                return lib
            except OSError as e:
                last_error = str(e)
                continue

        logger.debug("amd-smi: failed to load libamd_smi.so: %s", last_error)
        return None

    def _bind_functions(self, lib: ctypes.CDLL) -> None:
        """绑定我们需要的 C 函数签名，并记录哪些函数可用。"""
        self._available_functions.clear()

        signatures = {
            "amdsmi_init": ([ctypes.c_uint64], ctypes.c_int),
            "amdsmi_shut_down": ([], ctypes.c_int),
            "amdsmi_get_socket_handles": (
                [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p)],
                ctypes.c_int,
            ),
            "amdsmi_get_processor_handles": (
                [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p)],
                ctypes.c_int,
            ),
            "amdsmi_get_processor_type": (
                [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)],
                ctypes.c_int,
            ),
            "amdsmi_get_processor_info": (
                [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_char_p],
                ctypes.c_int,
            ),
            "amdsmi_get_gpu_asic_info": (
                [ctypes.c_void_p, ctypes.POINTER(AmdSmiAsicInfo)],
                ctypes.c_int,
            ),
            "amdsmi_get_gpu_vram_usage": (
                [ctypes.c_void_p, ctypes.POINTER(AmdSmiVramUsage)],
                ctypes.c_int,
            ),
            "amdsmi_get_gpu_activity": (
                [ctypes.c_void_p, ctypes.POINTER(AmdSmiEngineUsage)],
                ctypes.c_int,
            ),
            "amdsmi_get_temp_metric": (
                [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int64)],
                ctypes.c_int,
            ),
            "amdsmi_get_power_info": (
                [ctypes.c_void_p, ctypes.POINTER(AmdSmiPowerInfo)],
                ctypes.c_int,
            ),
        }

        for name, (argtypes, restype) in signatures.items():
            try:
                func = getattr(lib, name)
                func.argtypes = argtypes
                func.restype = restype
                self._available_functions.add(name)
            except AttributeError:
                logger.debug("amd-smi: function %s not available in this library version", name)

        # 核心函数缺失则无法使用
        required = {"amdsmi_init", "amdsmi_shut_down", "amdsmi_get_processor_handles"}
        missing = required - self._available_functions
        if missing:
            raise RuntimeError(f"Missing required AMD SMI functions: {missing}")

    def _enum_gpu_handles(self, lib: ctypes.CDLL) -> List[int]:
        """枚举系统中的 AMD GPU 句柄。"""
        gpu_handles: List[int] = []

        socket_count = ctypes.c_uint32(0)
        rc = lib.amdsmi_get_socket_handles(ctypes.byref(socket_count), None)
        if rc != AMDSMI_STATUS_SUCCESS or socket_count.value == 0:
            return gpu_handles

        sockets = (ctypes.c_void_p * socket_count.value)()
        rc = lib.amdsmi_get_socket_handles(ctypes.byref(socket_count), sockets)
        if rc != AMDSMI_STATUS_SUCCESS:
            return gpu_handles

        for i in range(socket_count.value):
            proc_count = ctypes.c_uint32(0)
            rc = lib.amdsmi_get_processor_handles(sockets[i], ctypes.byref(proc_count), None)
            if rc != AMDSMI_STATUS_SUCCESS or proc_count.value == 0:
                continue

            procs = (ctypes.c_void_p * proc_count.value)()
            rc = lib.amdsmi_get_processor_handles(sockets[i], ctypes.byref(proc_count), procs)
            if rc != AMDSMI_STATUS_SUCCESS:
                continue

            for j in range(proc_count.value):
                # 如果当前库版本没有 amdsmi_get_processor_type，
                # 保守地只把 processor 当作 GPU 加入（后续若指标读不出再过滤）
                if "amdsmi_get_processor_type" not in self._available_functions:
                    gpu_handles.append(int(procs[j]))
                    continue

                ptype = ctypes.c_int(0)
                rc = lib.amdsmi_get_processor_type(procs[j], ctypes.byref(ptype))
                if rc == AMDSMI_STATUS_SUCCESS and ptype.value == AMDSMI_PROCESSOR_TYPE_AMD_GPU:
                    gpu_handles.append(int(procs[j]))

        return gpu_handles

    def _fetch_device_names(self, lib: ctypes.CDLL, handles: List[int]) -> List[str]:
        names = []
        for h in handles:
            name = None

            # 优先用 amdsmi_get_gpu_asic_info 获取 market_name（真实 GPU 型号）
            if "amdsmi_get_gpu_asic_info" in self._available_functions:
                try:
                    asic_info = AmdSmiAsicInfo()
                    if lib.amdsmi_get_gpu_asic_info(h, ctypes.byref(asic_info)) == AMDSMI_STATUS_SUCCESS:
                        market_name = asic_info.market_name.decode("utf-8", errors="replace").strip()
                        if market_name:
                            name = market_name
                except Exception as e:
                    logger.debug("amd-smi: get_gpu_asic_info error: %s", e)

            # 回退到 processor_info（通常返回处理器 ID，非型号名）
            if name is None and "amdsmi_get_processor_info" in self._available_functions:
                try:
                    buf = ctypes.create_string_buffer(AMDSMI_MAX_STRING_LENGTH)
                    rc = lib.amdsmi_get_processor_info(h, AMDSMI_MAX_STRING_LENGTH, buf)
                    if rc == AMDSMI_STATUS_SUCCESS:
                        info = buf.value.decode("utf-8", errors="replace").strip()
                        if info:
                            name = info
                except Exception as e:
                    logger.debug("amd-smi: get_processor_info error: %s", e)

            names.append(name or f"AMD GPU {len(names)}")
        return names

    def initialize(self) -> bool:
        """加载 libamd_smi.so 并枚举 AMD GPU 设备。"""
        if platform.system() != "Linux":
            logger.debug("amd-smi: Linux only")
            return False

        lib = self._load_library()
        if lib is None:
            logger.debug("amd-smi: libamd_smi.so not found")
            return False

        try:
            self._bind_functions(lib)
        except Exception as e:
            logger.debug("amd-smi: failed to bind functions: %s", e)
            return False

        rc = lib.amdsmi_init(AMDSMI_INIT_AMD_GPUS)
        if rc != AMDSMI_STATUS_SUCCESS:
            logger.debug("amd-smi: amdsmi_init failed, rc=%s", rc)
            return False

        try:
            handles = self._enum_gpu_handles(lib)
            if not handles:
                logger.debug("amd-smi: no AMD GPU found")
                lib.amdsmi_shut_down()
                return False

            self._lib = lib
            self._handles = handles
            self._device_count = len(handles)
            self._device_names = self._fetch_device_names(lib, handles)
            self._initialized = True

            logger.info(
                "amd-smi provider initialized: %d device(s) via ctypes",
                self._device_count,
            )
            return True
        except Exception as e:
            logger.debug("amd-smi: initialization error: %s", e)
            try:
                lib.amdsmi_shut_down()
            except Exception:
                pass
            return False

    def shutdown(self) -> None:
        if not self._initialized or self._lib is None:
            return

        try:
            self._lib.amdsmi_shut_down()
        except Exception as e:
            logger.debug("amd-smi: shutdown error: %s", e)
        finally:
            self._initialized = False
            self._lib = None
            self._handles = []
            self._device_names = []
            self._device_count = 0

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"AMD GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """通过 libamd_smi.so 采集单个 GPU 指标。"""
        if not self._initialized or self._lib is None or device_id >= self._device_count:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        handle = self._handles[device_id]
        lib = self._lib

        # VRAM
        vram_used = 0
        vram_total = 0
        if "amdsmi_get_gpu_vram_usage" in self._available_functions:
            try:
                vram = AmdSmiVramUsage()
                if lib.amdsmi_get_gpu_vram_usage(handle, ctypes.byref(vram)) == AMDSMI_STATUS_SUCCESS:
                    vram_used = int(vram.vram_used)
                    vram_total = int(vram.vram_total)
            except Exception as e:
                logger.debug("amd-smi: vram usage error: %s", e)

        # GPU utilization
        gpu_util = 0.0
        if "amdsmi_get_gpu_activity" in self._available_functions:
            try:
                activity = AmdSmiEngineUsage()
                if lib.amdsmi_get_gpu_activity(handle, ctypes.byref(activity)) == AMDSMI_STATUS_SUCCESS:
                    gpu_util = float(activity.gfx_activity)
            except Exception as e:
                logger.debug("amd-smi: gpu activity error: %s", e)

        # Temperature: edge first, fallback to hotspot/junction
        temperature: Optional[float] = None
        if "amdsmi_get_temp_metric" in self._available_functions:
            for sensor_type in (AMDSMI_TEMPERATURE_TYPE_EDGE, AMDSMI_TEMPERATURE_TYPE_HOTSPOT):
                try:
                    temp = ctypes.c_int64(0)
                    rc = lib.amdsmi_get_temp_metric(
                        handle, sensor_type, AMDSMI_TEMP_CURRENT, ctypes.byref(temp)
                    )
                    if rc == AMDSMI_STATUS_SUCCESS and temp.value > 0:
                        temperature = float(temp.value)
                        break
                except Exception as e:
                    logger.debug("amd-smi: temp metric error: %s", e)

        # Power
        power_usage: Optional[float] = None
        if "amdsmi_get_power_info" in self._available_functions:
            try:
                power = AmdSmiPowerInfo()
                if lib.amdsmi_get_power_info(handle, ctypes.byref(power)) == AMDSMI_STATUS_SUCCESS:
                    if power.average_socket_power > 0:
                        power_usage = float(power.average_socket_power)
                    elif power.current_socket_power > 0:
                        power_usage = float(power.current_socket_power)
                    elif power.socket_power > 0:
                        power_usage = float(power.socket_power)
            except Exception as e:
                logger.debug("amd-smi: power info error: %s", e)

        return GPUMetrics(
            gpu_utilization=round(gpu_util, 1),
            vram_used=vram_used,
            vram_total=vram_total,
            temperature=temperature,
            power_usage=power_usage,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )
