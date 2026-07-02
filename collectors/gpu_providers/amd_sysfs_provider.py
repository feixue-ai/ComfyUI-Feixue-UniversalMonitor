"""
AMD sysfs GPU Provider

零依赖回退方案：通过 /sys/class/drm/card*/device/ 读取 AMD GPU 指标。
集成 BatchSysfsReader 与 SmartTTLCache，减少高频采集时的 I/O 开销。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from collectors.base import BaseGPUProvider
from core.data_models import GPUMetrics
from fxm_utils.performance_optimizations import BatchSysfsReader, SmartTTLCache

logger = logging.getLogger(__name__)


class AmdSysfsProvider(BaseGPUProvider):
    """基于 sysfs 的 AMD GPU 数据提供者。"""

    SYSFS_DRM_BASE = Path("/sys/class/drm")
    AMD_VENDOR_ID = "0x1002"

    def __init__(self, config: Optional[dict] = None):
        super().__init__(name="amd-sysfs", priority=50, config=config)
        self._device_paths: Dict[int, Path] = {}
        self._readers: Dict[int, BatchSysfsReader] = {}
        self._hwmon_paths: Dict[int, List[Path]] = {}

        # 分层缓存：静态数据（名称）长 TTL，半静态（显存总量）中 TTL，动态（利用率/温度/功耗）短 TTL
        self._static_cache = SmartTTLCache(default_ttl=60.0, max_size=100)
        self._semi_static_cache = SmartTTLCache(default_ttl=5.0, max_size=100)
        self._dynamic_cache = SmartTTLCache(default_ttl=0.5, max_size=200)

    @property
    def priority(self) -> int:
        return 50

    def initialize(self) -> bool:
        """扫描 /sys/class/drm 下的 AMD GPU 设备。"""
        if self.SYSFS_DRM_BASE.exists() is False:
            logger.debug("amd-sysfs: /sys/class/drm 不存在")
            return False

        card_pattern = re.compile(r"^card(\d+)$")
        device_id = 0

        for card_path in sorted(self.SYSFS_DRM_BASE.glob("card*")):
            if not card_pattern.match(card_path.name):
                continue

            device_link = card_path / "device"
            if not device_link.exists():
                continue

            vendor_file = device_link / "vendor"
            if not vendor_file.exists():
                continue

            try:
                vendor = vendor_file.read_text().strip().lower()
                if self.AMD_VENDOR_ID not in vendor and "1002" not in vendor:
                    continue
            except (IOError, OSError):
                continue

            self._device_paths[device_id] = card_path
            # 缓存 TTL 从 0.5s 降到 0.1s：在高负载/显存快速变化时减少滞后，
            # 同时保留一定缓存避免 sysfs 高频 IO 拖慢监控。
            cache_ttl = self.config.get("sysfs_cache_ttl", 0.1)
            self._readers[device_id] = BatchSysfsReader(
                base_path=str(device_link),
                cache_ttl=cache_ttl,
            )
            # 预缓存 hwmon 路径，避免每次 glob
            try:
                self._hwmon_paths[device_id] = sorted(
                    (device_link / "hwmon").glob("hwmon*")
                )
            except OSError:
                self._hwmon_paths[device_id] = []

            device_id += 1

        if not self._device_paths:
            logger.debug("amd-sysfs: 未找到 AMD GPU 设备")
            return False

        self._device_count = len(self._device_paths)
        # 预加载设备名称到静态缓存
        self._device_names = [self.get_device_name(i) for i in self._device_paths]
        self._initialized = True

        logger.info(
            "amd-sysfs provider initialized: %d device(s)", self._device_count
        )
        return True

    def shutdown(self) -> None:
        """清理 sysfs 读取器与缓存。"""
        for reader in self._readers.values():
            try:
                reader.__exit__(None, None, None)
            except Exception:
                pass

        self._readers.clear()
        self._hwmon_paths.clear()
        self._device_paths.clear()
        self._static_cache.invalidate()
        self._semi_static_cache.invalidate()
        self._dynamic_cache.invalidate()
        self._initialized = False
        self._device_count = 0
        self._device_names = []

    def get_device_count(self) -> int:
        return self._device_count

    def get_device_name(self, device_id: int = 0) -> str:
        if 0 <= device_id < len(self._device_names) and self._device_names[device_id]:
            return self._device_names[device_id]

        return self._static_cache.get_or_compute(
            f"device_name_{device_id}",
            lambda: self._read_device_name(device_id),
            ttl=60.0,
        )

    def _read_device_name(self, device_id: int) -> str:
        """从 sysfs uevent/model 读取设备名称。"""
        card_path = self._device_paths.get(device_id)
        if card_path is None:
            return f"AMD GPU {device_id}"

        device_link = card_path / "device"

        # 尝试 uevent
        uevent_file = device_link / "uevent"
        if uevent_file.exists():
            try:
                content = uevent_file.read_text()
                for line in content.splitlines():
                    if line.startswith(
                        ("PRODUCT=", "MODEL=", "PCI_NAME=", "PCI_ID_NAME=")
                    ):
                        name = line.split("=", 1)[1].strip().strip('"\'')
                        if name:
                            return name
            except (IOError, OSError):
                pass

        # 尝试 model 文件
        model_file = device_link / "model"
        if model_file.exists():
            try:
                name = model_file.read_text().strip()
                if name:
                    return name
            except (IOError, OSError):
                pass

        return f"AMD GPU (sysfs) {device_id}"

    def _find_hwmon_value(self, device_id: int, sensor_name: str) -> Optional[str]:
        """在设备的 hwmon 目录下查找传感器文件。"""
        hwmon_dirs = self._hwmon_paths.get(device_id, [])
        for hwmon_dir in hwmon_dirs:
            if not hwmon_dir.is_dir():
                continue
            sensor_path = hwmon_dir / sensor_name
            if sensor_path.exists():
                try:
                    return sensor_path.read_text().strip()
                except (IOError, OSError):
                    continue
        return None

    def _read_vram_total(self, device_id: int) -> int:
        """读取显存总量（带半静态缓存）。"""
        cache_key = f"vram_total_{device_id}"
        cached = self._semi_static_cache.get(cache_key)
        if cached is not None:
            return int(cached)

        reader = self._readers.get(device_id)
        if reader is None:
            return 0

        raw = reader.read_single("mem_info_vram_total")
        if raw is None:
            return 0

        try:
            val = int(raw)
            mb = val // (1024 * 1024) if val > 1024 * 1024 else val // 1024
            self._semi_static_cache.set(cache_key, mb)
            return mb
        except ValueError:
            return 0

    def get_metrics(self, device_id: int = 0) -> GPUMetrics:
        """通过 sysfs 采集单个 GPU 指标。"""
        if not self._initialized or device_id not in self._readers:
            return GPUMetrics(
                gpu_utilization=0.0,
                vram_used=0,
                vram_total=0,
                device_id=device_id,
                device_name=self.get_device_name(device_id),
            )

        reader = self._readers[device_id]

        # 显存：总量使用半静态缓存，使用量实时读取
        vram_total_mb = self._read_vram_total(device_id)
        vram_used_mb = 0
        raw_used = reader.read_single("mem_info_vram_used")
        if raw_used is not None:
            try:
                val = int(raw_used)
                vram_used_mb = val // (1024 * 1024) if val > 1024 * 1024 else val // 1024
            except ValueError:
                pass

        # GPU 利用率：批量尝试多个可能路径
        gpu_util = 0.0
        util_paths = ["gpu_busy_percent", "gpu_busy", "busy_percent"]
        util_values = reader.read_multi(util_paths)
        for value in util_values:
            if value is not None:
                try:
                    val = float(value)
                    if 0.0 <= val <= 100.0:
                        gpu_util = val
                        break
                except ValueError:
                    continue

        # 温度：优先读取 junction (temp2_input)，与 rocm-smi 保持一致；
        # 不存在时再 fallback 到 edge (temp1_input)
        temperature: Optional[float] = None
        for temp_sensor in ("temp2_input", "temp1_input"):
            temp_raw = self._find_hwmon_value(device_id, temp_sensor)
            if temp_raw is not None:
                try:
                    temp_mc = int(temp_raw)
                    if 1000 <= temp_mc <= 120000:
                        temperature = round(temp_mc / 1000.0, 1)
                        break
                    elif 0 <= temp_mc <= 150:
                        temperature = float(temp_mc)
                        break
                except ValueError:
                    continue

        # 功耗
        power_usage: Optional[float] = None
        power_raw = self._find_hwmon_value(device_id, "power1_average")
        if power_raw is not None:
            try:
                power_uw = int(power_raw)
                power_usage = round(power_uw / 1_000_000.0, 2) if power_uw > 1000 else float(power_uw)
            except ValueError:
                pass

        return GPUMetrics(
            gpu_utilization=gpu_util,
            vram_used=max(0, vram_used_mb),
            vram_total=max(1, vram_total_mb),
            temperature=temperature,
            power_usage=power_usage,
            device_id=device_id,
            device_name=self.get_device_name(device_id),
            driver_version="sysfs",
        )
