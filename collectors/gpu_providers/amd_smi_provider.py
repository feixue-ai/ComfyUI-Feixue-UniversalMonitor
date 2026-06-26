"""
AMD amdsmi GPU Provider

使用 ROCm 官方 Python 绑定 amdsmi 读取 AMD GPU 指标。
在 Linux 上优先级高于 rocm_smi 与 sysfs。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


class AmdSmiProvider(BaseGPUProvider):
    """基于 amdsmi 的 AMD GPU 数据提供者。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-smi", priority=2, config=config)
        self._lib: Any = None
        self._handles: List[Any] = []
        # 短时移动平均：让利用率与系统监视器（如 GNOME Vitals）的采样窗口更对齐，
        # 减少 amdsmi gfx_activity 瞬时跳变带来的数值偏差。
        self._util_history: List[float] = []
        self._util_history_size: int = 3

    @property
    def priority(self) -> int:
        return 2

    def _extract_device_name(self, info: Any, handle: Any, fallback: str) -> str:
        """兼容不同 amdsmi 版本的 processor_info 返回值（对象或字符串）。

        26.0.0 的 processor_info 返回设备索引字符串，需通过 asic_info 取真实型号。
        """
        if info is not None and not isinstance(info, str):
            name = str(
                getattr(info, "market_name", None)
                or getattr(info, "device_name", None)
                or ""
            ).strip()
            if name:
                return name

        if isinstance(info, str):
            idx_str = info.strip()
            if idx_str:
                try:
                    asic_info = self._lib.amdsmi_get_gpu_asic_info(handle)
                    if isinstance(asic_info, dict):
                        name = str(asic_info.get("market_name", "")).strip()
                        if name:
                            return name
                except Exception:
                    pass

        return fallback

    @staticmethod
    def _is_gpu_type(ptype: Any, lib: Any) -> bool:
        """兼容 amdsmi_get_processor_type 返回枚举值或字典。"""
        try:
            gpu_type = getattr(lib, "AmdSmiDeviceType", None)
            if gpu_type is not None and hasattr(gpu_type, "GPU"):
                if ptype == gpu_type.GPU:
                    return True
            # 26.0.0 返回字典，如 {'processor_type': 'AMDSMI_PROCESSOR_TYPE_AMD_GPU'}
            if isinstance(ptype, dict):
                type_str = str(ptype.get("processor_type", "")).lower()
                if "gpu" in type_str:
                    return True
            type_str = str(ptype).lower()
            if "gpu" in type_str:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _safe_shutdown(lib: Any) -> None:
        """兼容不同 amdsmi 版本的 shutdown 函数名。"""
        if lib is None:
            return
        for attr in ("amdsmi_shut_down", "amdsmi_shutdown"):
            if hasattr(lib, attr):
                try:
                    getattr(lib, attr)()
                    return
                except Exception:
                    pass

    def initialize(self) -> bool:
        """初始化 amdsmi 并枚举 GPU 设备。"""
        try:
            import amdsmi
        except ImportError:
            logger.debug("amd-smi: amdsmi 库未安装")
            return False

        init_succeeded = False
        try:
            try:
                amdsmi.amdsmi_init()
            except Exception as e:
                logger.debug("amd-smi: amdsmi_init() 失败: %s", e)
                return False

            handles = amdsmi.amdsmi_get_processor_handles()
            if not handles:
                logger.debug("amd-smi: 未找到处理器设备")
                return False

            gpu_handles: List[Any] = []
            for handle in handles:
                try:
                    ptype = amdsmi.amdsmi_get_processor_type(handle)
                    if self._is_gpu_type(ptype, amdsmi) or len(handles) == 1:
                        gpu_handles.append(handle)
                    else:
                        info = amdsmi.amdsmi_get_processor_info(handle)
                        device_name = self._extract_device_name(info, handle, "").lower()
                        if any(
                            kw in device_name
                            for kw in ["radeon", "gpu", "graphics", "device"]
                        ):
                            gpu_handles.append(handle)
                except Exception:
                    if len(handles) == 1:
                        gpu_handles.append(handle)

            if not gpu_handles and handles:
                gpu_handles = [handles[0]]

            if not gpu_handles:
                return False

            self._lib = amdsmi
            self._handles = gpu_handles
            self._device_count = len(gpu_handles)
            self._device_names = []
            for i, handle in enumerate(gpu_handles):
                try:
                    info = amdsmi.amdsmi_get_processor_info(handle)
                    name = self._extract_device_name(info, handle, f"AMD Device {i}")
                    self._device_names.append(str(name))
                except Exception:
                    self._device_names.append(f"AMD Device {i}")

            self._initialized = True
            init_succeeded = True
            logger.info(
                "amd-smi provider initialized: %d device(s)", self._device_count
            )
            return True

        except Exception as e:
            logger.debug("amd-smi: 初始化异常: %s", e)
            return False
        finally:
            if not init_succeeded:
                self._safe_shutdown(amdsmi)

    def shutdown(self) -> None:
        """关闭 amdsmi 会话。"""
        if not self._initialized:
            return

        try:
            self._safe_shutdown(self._lib)
        except Exception as e:
            logger.debug("amd-smi: shutdown error: %s", e)
        finally:
            self._initialized = False
            self._lib = None
            self._handles = []
            self._device_count = 0
            self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"AMD Device {device_id}"

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """通过 amdsmi 采集单个 GPU 指标。"""
        if not self._initialized or device_id >= len(self._handles):
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
        vram_total_mb = 0
        vram_used_mb = 0
        try:
            vram_info = lib.amdsmi_get_gpu_vram_usage(handle)
            if isinstance(vram_info, dict):
                vram_total_mb = int(vram_info.get("vram_total", 0))
                vram_used_mb = int(vram_info.get("vram_used", 0))
            else:
                vram_total_mb = int(getattr(vram_info, "vram_total", 0))
                vram_used_mb = int(getattr(vram_info, "vram_used", 0))
        except Exception as e:
            logger.debug("amd-smi: 读取 VRAM 失败: %s", e)

        # GPU 利用率（取 gfx_activity 短时移动平均，与系统监视器对齐）
        gpu_util = 0.0
        try:
            activity = lib.amdsmi_get_gpu_activity(handle)
            if isinstance(activity, dict):
                raw_util = float(
                    activity.get("gfx_activity")
                    or activity.get("gpu_activity")
                    or activity.get("activity")
                    or 0
                )
            else:
                raw_util = float(
                    getattr(activity, "gfx_activity", None)
                    or getattr(activity, "gpu_activity", None)
                    or getattr(activity, "activity", None)
                    or 0
                )

            self._util_history.append(raw_util)
            if len(self._util_history) > self._util_history_size:
                self._util_history.pop(0)
            gpu_util = sum(self._util_history) / len(self._util_history)
        except Exception as e:
            logger.debug("amd-smi: 读取利用率失败: %s", e)

        # 温度 / 功耗统一来自 metrics_info
        temperature: Optional[float] = None
        power_usage: Optional[float] = None
        try:
            metrics_info: Dict[str, Any] = lib.amdsmi_get_gpu_metrics_info(handle)
            if not isinstance(metrics_info, dict):
                metrics_info = {
                    k: getattr(metrics_info, k, None)
                    for k in dir(metrics_info)
                    if not k.startswith("_")
                }

            temp_edge = metrics_info.get("temperature_edge", 0)
            if temp_edge and temp_edge > 0:
                temperature = round(float(temp_edge), 1)
            else:
                temp_hotspot = metrics_info.get("temperature_hotspot", 0)
                if temp_hotspot and temp_hotspot > 0:
                    temperature = round(float(temp_hotspot), 1)

            power_avg = metrics_info.get("average_socket_power", 0)
            if power_avg and power_avg > 0:
                power_usage = round(float(power_avg), 1)
            else:
                power_current = metrics_info.get("current_socket_power", 0)
                if power_current and power_current > 0:
                    power_usage = round(float(power_current), 1)
        except Exception as e:
            logger.debug("amd-smi: 读取 metrics_info 失败: %s", e)

        return GPUMetrics(
            gpu_utilization=gpu_util,
            vram_used=vram_used_mb,
            vram_total=vram_total_mb,
            temperature=temperature,
            power_usage=power_usage,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="",
        )
