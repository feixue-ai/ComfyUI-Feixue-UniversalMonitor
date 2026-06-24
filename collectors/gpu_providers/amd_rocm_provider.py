"""
AMD ROCm SMI GPU Provider

兼容 rocm_smi / rocm_smi_lib 两个导入名，作为 amdsmi 不可用时的降级方案。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics

logger = logging.getLogger(__name__)


class AmdRocmProvider(BaseGPUProvider):
    """基于 rocm_smi_lib 的 AMD GPU 数据提供者。"""

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-rocm", priority=10, config=config)
        self._rsmi: Any = None

    @property
    def priority(self) -> int:
        return 10

    def initialize(self) -> bool:
        """导入并初始化 rocm_smi / rocm_smi_lib。"""
        rsmi_module = None
        for name in ("rocm_smi", "rocm_smi_lib"):
            try:
                rsmi_module = __import__(name)
                break
            except ImportError:
                continue

        if rsmi_module is None:
            logger.debug("amd-rocm: rocm_smi/rocm_smi_lib 未安装")
            return False

        init_succeeded = False
        try:
            if hasattr(rsmi_module, "rocm_smi_init"):
                rsmi_module.rocm_smi_init()

            if hasattr(rsmi_module, "getDevices"):
                devices = rsmi_module.getDevices()
            elif hasattr(rsmi_module, "get_device_count"):
                devices = list(range(rsmi_module.get_device_count()))
            else:
                return False

            device_count = len(devices) if isinstance(devices, list) else devices
            if device_count == 0:
                return False

            self._rsmi = rsmi_module
            self._device_count = device_count
            self._device_names = []
            for i in range(device_count):
                try:
                    if hasattr(rsmi_module, "getDeviceName"):
                        name = str(rsmi_module.getDeviceName(i))
                    else:
                        name = f"AMD Device {i}"
                    self._device_names.append(name)
                except Exception:
                    self._device_names.append(f"AMD Device {i}")

            self._initialized = True
            init_succeeded = True
            logger.info(
                "amd-rocm provider initialized: %d device(s)", device_count
            )
            return True

        except Exception as e:
            logger.debug("amd-rocm: 初始化失败: %s", e)
            return False
        finally:
            if not init_succeeded:
                try:
                    if hasattr(rsmi_module, "rocm_smi_shutdown"):
                        rsmi_module.rocm_smi_shutdown()
                except Exception:
                    pass

    def shutdown(self) -> None:
        """关闭 rocm_smi 会话。"""
        if not self._initialized:
            return

        try:
            if self._rsmi is not None and hasattr(self._rsmi, "rocm_smi_shutdown"):
                self._rsmi.rocm_smi_shutdown()
        except Exception as e:
            logger.debug("amd-rocm: shutdown error: %s", e)
        finally:
            self._initialized = False
            self._rsmi = None
            self._device_count = 0
            self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"AMD Device {device_id}"

    @staticmethod
    def _call_rsmi_method(rsmi_obj, method_names: List[str], device_id: int) -> Any:
        """尝试多个可能的 rocm_smi 方法名。"""
        for method_name in method_names:
            if hasattr(rsmi_obj, method_name):
                method = getattr(rsmi_obj, method_name)
                try:
                    return method(device_id, silent=True)
                except TypeError:
                    try:
                        return method(device_id)
                    except Exception:
                        continue
                except Exception:
                    continue
        return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """将 rocm_smi 返回值转为 float。"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            import re

            match = re.search(r"(\d+(?:\.\d+)?)", value.strip())
            if match:
                return float(match.group(1))
        return None

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """通过 rocm_smi 采集单个 GPU 指标。"""
        if not self._initialized or self._rsmi is None:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        rsmi = self._rsmi

        # 利用率
        gpu_util = 0.0
        try:
            util_result = self._call_rsmi_method(rsmi, ["getGpuUse", "get_gpu_use"], device_id)
            parsed = self._to_float(util_result)
            if parsed is not None:
                gpu_util = parsed
        except Exception as e:
            logger.debug("amd-rocm: 读取利用率失败: %s", e)

        # 显存
        vram_total_mb = 0
        vram_used_mb = 0
        try:
            mem_result = self._call_rsmi_method(rsmi, ["getMemInfo", "get_mem_info"], device_id)
            if isinstance(mem_result, dict):
                total_raw = int(mem_result.get("vram_total", 0) or mem_result.get("total", 0) or 0)
                used_raw = int(mem_result.get("vram_used", 0) or mem_result.get("used", 0) or 0)
            elif isinstance(mem_result, (list, tuple)) and len(mem_result) >= 2:
                total_raw = int(mem_result[0]) if mem_result[0] else 0
                used_raw = int(mem_result[1]) if mem_result[1] else 0
            else:
                total_raw = used_raw = 0

            if total_raw > 1024 * 1024:
                vram_total_mb = total_raw // (1024 * 1024)
                vram_used_mb = used_raw // (1024 * 1024)
            else:
                vram_total_mb = total_raw // 1024
                vram_used_mb = used_raw // 1024
        except Exception as e:
            logger.debug("amd-rocm: 读取显存失败: %s", e)

        # 温度
        temperature: Optional[float] = None
        try:
            temp_result = self._call_rsmi_method(rsmi, ["getTemp", "get_temp"], device_id)
            parsed = self._to_float(temp_result)
            if parsed is not None:
                temperature = round(parsed, 1)
        except Exception as e:
            logger.debug("amd-rocm: 读取温度失败: %s", e)

        # 功耗
        power_usage: Optional[float] = None
        try:
            power_result = self._call_rsmi_method(rsmi, ["getPower", "get_power"], device_id)
            parsed = self._to_float(power_result)
            if parsed is not None:
                power_usage = round(parsed, 2)
        except Exception as e:
            logger.debug("amd-rocm: 读取功耗失败: %s", e)

        return GPUMetrics(
            gpu_utilization=max(0.0, min(100.0, gpu_util)),
            vram_used=max(0, vram_used_mb),
            vram_total=max(1, vram_total_mb),
            temperature=temperature,
            power_usage=power_usage,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="rocm_smi_lib",
        )
