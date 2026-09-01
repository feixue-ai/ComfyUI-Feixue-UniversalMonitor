"""
NVIDIA GPU Provider

使用 pynvml（NVIDIA 官方原版）或 nvidia-ml-py 读取 NVIDIA GPU 指标。
显式拒绝 pynvml-amd-windows（AMD ADLX 封装），避免在 A 卡环境被误选。

Blackwell (RTX 50) 兼容：
- 优先尝试 NVML v2 API（nvmlDeviceGetMemoryInfo_v2 / nvmlDeviceGetTemperatureV2）
- 若 v2 不可用或返回 0，回退到 nvidia-smi 命令行获取显存/温度
- GPU 利用率仍使用 v1 的 nvmlDeviceGetUtilizationRates（Blackwell 正常）
"""

from __future__ import annotations

import ctypes
import logging
import platform
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics
from ._pynvml_common import import_pynvml

logger = logging.getLogger(__name__)


class NvidiaProvider(BaseGPUProvider):
    """基于 NVML 的 NVIDIA GPU 数据提供者。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="nvidia", priority=1, config=config)
        self._nvml: Any = None
        self._handles: List[Any] = []
        self._variant: str = ""
        # 底层 NVML DLL/SO 引用，用于 ctypes 直接调用 v2 API
        self._nvml_dll: Optional[Any] = None
        # nvidia-smi fallback 缓存: {device_id: {"vram_used_mb": int, "vram_total_mb": int, "temperature": float, "ts": float}}
        self._smi_cache: Dict[int, Dict[str, Any]] = {}
        self._smi_cache_ttl: float = 5.0  # 秒
        self._smi_fallback_logged: bool = False  # 仅记录一次 fallback 信息
        self._zero_data_logged: bool = False  # 仅记录一次全零告警

    @property
    def priority(self) -> int:
        # NVIDIA 原生库优先级最高
        return 1

    def initialize(self) -> bool:
        """初始化 NVML 并枚举 NVIDIA GPU 设备。"""
        nvml_module, variant = import_pynvml(
            allowed_variants=("nvidia_native", "nvidia_ml_py", "unknown")
        )
        if nvml_module is None:
            logger.debug("nvidia: pynvml/nvidia-ml-py 未安装")
            return False

        # 二次确认：如果检测到 AMD Windows 封装则拒绝
        if variant == "amd_windows":
            logger.debug("nvidia: 检测到 pynvml-amd-windows，非 NVIDIA 原生实现")
            return False

        try:
            nvml_module.nvmlInit()
            count = nvml_module.nvmlDeviceGetCount()
            if count <= 0:
                logger.debug("nvidia: NVML 未检测到 GPU 设备")
                nvml_module.nvmlShutdown()
                return False

            handles = []
            for i in range(count):
                try:
                    handles.append(nvml_module.nvmlDeviceGetHandleByIndex(i))
                except Exception as e:
                    logger.debug("nvidia: 获取 handle[%d] 失败: %s", i, e)

            if not handles:
                nvml_module.nvmlShutdown()
                return False

            self._nvml = nvml_module
            self._variant = variant
            self._handles = handles
            self._device_count = len(handles)
            self._device_names = [self._fetch_name(h) for h in handles]
            self._initialized = True

            # 尝试加载底层 NVML 库，供 v2 API ctypes 调用
            self._load_nvml_dll()

            logger.info(
                "nvidia provider initialized (%s): %d device(s)",
                variant,
                self._device_count,
            )
            return True

        except Exception as e:
            logger.debug("nvidia: 初始化失败: %s", e)
            return False

    def shutdown(self) -> None:
        """关闭 NVML 会话。"""
        if not self._initialized:
            return

        try:
            if self._nvml is not None:
                self._nvml.nvmlShutdown()
        except Exception as e:
            logger.debug("nvidia: shutdown error: %s", e)
        finally:
            self._initialized = False
            self._nvml = None
            self._handles = []
            self._device_count = 0
            self._device_names = []
            self._nvml_dll = None
            self._smi_cache.clear()
            self._smi_fallback_logged = False
            self._zero_data_logged = False

    def _fetch_name(self, handle: Any) -> str:
        """读取 GPU 型号名称。"""
        try:
            raw = self._nvml.nvmlDeviceGetName(handle)
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="ignore")
            return str(raw)
        except Exception as e:
            logger.debug("nvidia: 读取设备名失败: %s", e)
            return "NVIDIA GPU"

    def _driver_version(self) -> str:
        """读取 NVML 驱动版本。"""
        try:
            return str(self._nvml.nvmlSystemGetDriverVersion())
        except Exception:
            return ""

    def _load_nvml_dll(self) -> None:
        """通过 ctypes 加载底层 NVML 库，用于直接调用 v2 API。"""
        if platform.system() == "Windows":
            lib_names = ["nvml.dll", "C:\\Windows\\System32\\nvml.dll"]
        else:
            lib_names = [
                "libnvidia-ml.so.1",
                "libnvidia-ml.so",
                "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
                "/usr/lib64/libnvidia-ml.so.1",
            ]
        for name in lib_names:
            try:
                self._nvml_dll = ctypes.CDLL(name)
                logger.debug("nvidia: 底层 NVML 库已加载: %s", name)
                return
            except OSError:
                continue
        logger.debug("nvidia: 未找到底层 NVML 库，v2 API 不可用")

    def _handle_value(self, handle: Any) -> int:
        """从 pynvml handle 中提取 c_void_p 地址值。"""
        if handle is None:
            return 0
        if isinstance(handle, int):
            return handle
        # pynvml handle 通常是 c_void_p 或封装对象
        value = getattr(handle, "value", None)
        if isinstance(value, int):
            return value
        # 某些 pynvml 版本用 _as_parameter_ 暴露地址
        try:
            return int(handle)
        except Exception:
            return 0

    def _fetch_memory_v2(self, handle: Any) -> Tuple[Optional[int], Optional[int]]:
        """使用 NVML v2 API 读取显存（Blackwell RTX 50 必需）。"""
        if self._nvml_dll is None:
            return None, None

        proc = getattr(self._nvml_dll, "nvmlDeviceGetMemoryInfo_v2", None)
        if proc is None:
            return None, None

        class NVMLMemoryV2(ctypes.Structure):
            _fields_ = [
                ("version", ctypes.c_uint),
                ("total", ctypes.c_ulonglong),
                ("reserved", ctypes.c_ulonglong),
                ("free", ctypes.c_ulonglong),
                ("used", ctypes.c_ulonglong),
            ]

        try:
            proc.argtypes = [ctypes.c_void_p, ctypes.POINTER(NVMLMemoryV2)]
            proc.restype = ctypes.c_int
        except Exception as e:
            logger.debug("nvidia: 设置 nvmlDeviceGetMemoryInfo_v2 原型失败: %s", e)
            return None, None

        mem = NVMLMemoryV2()
        # NVML_STRUCT_VERSION(2, nvmlMemory) = sizeof(struct) | (2 << 24)
        mem.version = ctypes.sizeof(NVMLMemoryV2) | (2 << 24)

        ret = proc(self._handle_value(handle), ctypes.byref(mem))
        if ret != 0:
            logger.debug("nvidia: nvmlDeviceGetMemoryInfo_v2 返回 %d", ret)
            return None, None

        if mem.total == 0 and mem.used == 0:
            return None, None

        return int(mem.total) // (1024 * 1024), int(mem.used) // (1024 * 1024)

    def _fetch_temperature_v2(self, handle: Any) -> Optional[float]:
        """使用 NVML v2 API 读取温度（Blackwell RTX 50 部分驱动需要）。"""
        if self._nvml_dll is None:
            return None

        proc = getattr(self._nvml_dll, "nvmlDeviceGetTemperatureV2", None)
        if proc is None:
            return None

        try:
            proc.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
            proc.restype = ctypes.c_int
        except Exception as e:
            logger.debug("nvidia: 设置 nvmlDeviceGetTemperatureV2 原型失败: %s", e)
            return None

        temp = ctypes.c_uint(0)
        # NVML_TEMPERATURE_GPU = 0
        ret = proc(self._handle_value(handle), 0, ctypes.byref(temp))
        if ret != 0:
            logger.debug("nvidia: nvmlDeviceGetTemperatureV2 返回 %d", ret)
            return None
        return float(temp.value)

    def _query_smi(self, device_id: int) -> Dict[str, Any]:
        """通过 nvidia-smi 命令行获取显存/温度，作为 Blackwell fallback。"""
        now = time.time()
        cached = self._smi_cache.get(device_id)
        if cached and (now - cached.get("ts", 0)) < self._smi_cache_ttl:
            return cached

        smi_path = shutil.which("nvidia-smi")
        if smi_path is None:
            return {}

        try:
            # 查询指定 GPU 的显存、温度、利用率、功耗
            cmd = [
                smi_path,
                "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu,power.draw",
                "--format=csv,noheader,nounits",
                "-i",
                str(device_id),
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3.0,
            )
            if result.returncode != 0:
                logger.debug("nvidia: nvidia-smi 错误: %s", result.stderr.strip())
                return {}

            line = result.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                return {}

            def _parse(value: str):
                try:
                    return float(value) if value else 0.0
                except ValueError:
                    return 0.0

            used_mb = int(_parse(parts[0]))  # MiB
            total_mb = int(_parse(parts[1]))  # MiB
            temp = _parse(parts[2]) if parts[2] else None
            util = _parse(parts[3])
            power = _parse(parts[4]) if parts[4] else None

            data = {
                "vram_used_mb": used_mb,
                "vram_total_mb": total_mb,
                "temperature": temp,
                "gpu_utilization": util,
                "power_usage": power,
                "ts": now,
            }
            self._smi_cache[device_id] = data
            if not self._smi_fallback_logged:
                self._smi_fallback_logged = True
                logger.info(
                    "nvidia: NVML 读取显存/温度异常，已启用 nvidia-smi 兜底 (device=%d, "
                    "vram=%d/%d MB, temp=%s°C)",
                    device_id,
                    used_mb,
                    total_mb,
                    temp if temp is not None else "--",
                )
            logger.debug("nvidia: nvidia-smi fallback 成功 device=%d: %s", device_id, data)
            return data
        except Exception as e:
            logger.debug("nvidia: nvidia-smi fallback 失败: %s", e)
            return {}

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"NVIDIA GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """采集单个 NVIDIA GPU 的完整指标（含 Blackwell RTX 50 兼容逻辑）。"""
        if not self._initialized or device_id >= len(self._handles):
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        handle = self._handles[device_id]

        # GPU 利用率：v1 API 在 Blackwell 上正常，保留
        gpu_util = 0.0
        try:
            rates = self._nvml.nvmlDeviceGetUtilizationRates(handle)
            gpu_util = float(rates.gpu)
        except Exception as e:
            logger.debug("nvidia: 读取利用率失败: %s", e)

        # 显存：优先 v2 API（Blackwell 必需），再 v1，最后 nvidia-smi
        vram_total_mb = 0
        vram_used_mb = 0
        mem_v2_total, mem_v2_used = self._fetch_memory_v2(handle)
        if mem_v2_total is not None and mem_v2_total > 0:
            vram_total_mb = mem_v2_total
            vram_used_mb = mem_v2_used or 0
        else:
            try:
                mem = self._nvml.nvmlDeviceGetMemoryInfo(handle)
                vram_total_mb = int(mem.total) // (1024 * 1024)
                vram_used_mb = int(mem.used) // (1024 * 1024)
            except Exception as e:
                logger.debug("nvidia: v1 读取显存失败: %s", e)

        # 温度：优先 v2 API，再 v1，最后 nvidia-smi
        temperature: Optional[float] = None
        temp_v2 = self._fetch_temperature_v2(handle)
        if temp_v2 is not None and temp_v2 > 0:
            temperature = temp_v2
        else:
            try:
                sensor = getattr(self._nvml, "NVML_TEMPERATURE_GPU", 0)
                temp_v1 = float(self._nvml.nvmlDeviceGetTemperature(handle, sensor))
                if temp_v1 > 0:
                    temperature = temp_v1
            except Exception as e:
                logger.debug("nvidia: v1 读取温度失败: %s", e)

        # 功耗（单位通常为 mW）
        power_usage: Optional[float] = None
        try:
            power_mw = self._nvml.nvmlDeviceGetPowerUsage(handle)
            power_usage = float(power_mw) / 1000.0
        except Exception as e:
            logger.debug("nvidia: 读取功耗失败: %s", e)

        # 若 NVML 核心字段仍为 0，使用 nvidia-smi 兜底
        need_smi = (vram_total_mb <= 0) or (temperature is None)
        smi_data: Dict[str, Any] = {}
        if need_smi:
            smi_data = self._query_smi(device_id)
            if vram_total_mb <= 0:
                smi_total = smi_data.get("vram_total_mb", 0)
                if smi_total > 0:
                    vram_total_mb = smi_total
                    vram_used_mb = smi_data.get("vram_used_mb", 0)
            if temperature is None:
                smi_temp = smi_data.get("temperature")
                if smi_temp is not None and smi_temp > 0:
                    temperature = float(smi_temp)

        if vram_total_mb <= 0 and temperature is None and not self._zero_data_logged:
            self._zero_data_logged = True
            logger.warning(
                "nvidia: GPU %d 显存/温度均无法读取。可能原因："
                "1) 旧版 NVML 不支持 Blackwell (RTX 50)；"
                "2) 驱动未正确安装；"
                "3) nvidia-smi 不在 PATH 中。",
                device_id,
            )

        return GPUMetrics(
            gpu_utilization=gpu_util,
            vram_used=vram_used_mb,
            vram_total=vram_total_mb,
            temperature=temperature,
            power_usage=power_usage,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version=self._driver_version(),
        )
