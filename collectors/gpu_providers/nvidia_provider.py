"""
NVIDIA GPU Provider

使用 pynvml（NVIDIA 官方原版）或 nvidia-ml-py 读取 NVIDIA GPU 指标。
显式拒绝 pynvml-amd-windows（AMD ADLX 封装），避免在 A 卡环境被误选。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

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

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"NVIDIA GPU {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """采集单个 NVIDIA GPU 的完整指标。"""
        if not self._initialized or device_id >= len(self._handles):
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        handle = self._handles[device_id]

        # GPU 利用率
        gpu_util = 0.0
        try:
            rates = self._nvml.nvmlDeviceGetUtilizationRates(handle)
            gpu_util = float(rates.gpu)
        except Exception as e:
            logger.debug("nvidia: 读取利用率失败: %s", e)

        # 显存
        vram_used_mb = 0
        vram_total_mb = 0
        try:
            mem = self._nvml.nvmlDeviceGetMemoryInfo(handle)
            vram_used_mb = int(mem.used) // (1024 * 1024)
            vram_total_mb = int(mem.total) // (1024 * 1024)
        except Exception as e:
            logger.debug("nvidia: 读取显存失败: %s", e)

        # 温度
        temperature: Optional[float] = None
        try:
            sensor = getattr(self._nvml, "NVML_TEMPERATURE_GPU", 0)
            temperature = float(self._nvml.nvmlDeviceGetTemperature(handle, sensor))
        except Exception as e:
            logger.debug("nvidia: 读取温度失败: %s", e)

        # 功耗（单位通常为 mW）
        power_usage: Optional[float] = None
        try:
            power_mw = self._nvml.nvmlDeviceGetPowerUsage(handle)
            power_usage = float(power_mw) / 1000.0
        except Exception as e:
            logger.debug("nvidia: 读取功耗失败: %s", e)

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
