"""
ComfyUI-Feixue-UniversalMonitor - Windows AMD GPU Adapter (Three-Layer Fault Tolerance)

This module implements a robust AMD GPU data provider for Windows platforms with a
three-layer fault tolerance strategy designed to handle the inherent instability of
Windows AMD GPU monitoring.

Architecture Overview:
======================

Layer 1 - WMI (Primary Source):
    - Win32_VideoController: Device name, driver version, total VRAM (AdapterRAM)
    - Win32_PerfFormattedData: GPU utilization (if available)
    - Limitations: Temperature/power usually unavailable, VRAM usage inaccurate

Layer 2 - PyTorch (Supplementary):
    - torch.cuda.memory_allocated(): Accurate VRAM usage
    - torch.cuda.utilization(): GPU utilization (if supported)
    - Limitations: DirectML backend may not support all APIs

Layer 3 - psutil (Fallback):
    - CPU/RAM metrics (complete)
    - Process list for GPU-related process identification
    - Limitations: No direct GPU metrics

Special Handling:
===============
1. Driver Crash Recovery: Monitor amdagsvc.exe health status
2. Radeon Software Conflict Detection: Detect Adrenalin overlay interference
3. Privilege Escalation Awareness: Admin rights detection for WMI queries
4. Sleep/Wakeup Reconnection: System uptime monitoring for resume detection

Performance Targets:
===================
- Single collection < 200ms (Windows API overhead is significant)
- Crash rate < 0.1%/hour
- 24h continuous operation stability > 99.9%

Known Limitations:
=================
- Temperature and power readings are generally unavailable on Windows without
  third-party tools (GPU-Z SDK, HWiNFO shared memory)
- VRAM usage via WMI is approximate; use PyTorch for accurate values
- Some WMI queries require administrator privileges
- Antivirus software may intercept WMI queries

Version: 2.0.0 (Three-Layer Fault Tolerance)
Author: Feixue (Backend Architecture Team)
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
import time
import ctypes
from typing import Any, Dict, List, Optional, Tuple

# Handle import compatibility for different execution contexts
# (ComfyUI plugin vs direct script execution)
try:
    from collectors.base import BaseGPUProvider, CollectorError
    from core.data_models import GPUMetrics, ProviderInitializationError
    from utils.platform_detect import detect_windows_gpu_info, is_admin
    from utils.thread_safe import execute_with_timeout, retry_on_failure
except ImportError:
    # Fallback for direct execution or alternative package structures
    from collectors.base import BaseGPUProvider, CollectorError
    from core.data_models import GPUMetrics, ProviderInitializationError
    from utils.platform_detect import detect_windows_gpu_info, is_admin
    from utils.thread_safe import execute_with_timeout, retry_on_failure


# Configure module-level logger
logger = logging.getLogger(__name__)


class AMDWindowsProvider(BaseGPUProvider):
    """
    Windows AMD GPU Data Provider with Three-Layer Fault Tolerance Strategy.

    This provider implements a sophisticated data collection system that automatically
    degrades gracefully when primary data sources fail, ensuring 24-hour continuous
    operation without crashes.

    Data Source Priority:
        1. **WMI** (Win32_VideoController, Win32_PerfFormattedData) - Primary method
        2. **PyTorch** (torch.cuda.* interface) - Supplementary (if available)
        3. **psutil** (process list + basic system info) - Fallback guarantee

    Design Principles:
        - Defensive programming: All external calls wrapped in try-except
        - Timeout protection: All blocking operations have timeout limits
        - Graceful degradation: Single source failure doesn't crash the system
        - Self-healing: Automatic recovery from transient failures

    Attributes:
        SOURCE_PRIORITY: Ordered list of data source names by priority
        _active_sources: List of currently operational data sources
        _wmi_available: Whether WMI data source is initialized
        _pytorch_available: Whether PyTorch data source is initialized
        _psutil_available: Whether psutil data source is initialized
        _is_admin: Whether current process has admin privileges
        _driver_process_name: Name of AMD driver service process to monitor
        _last_driver_check: Timestamp of last driver health check
        _driver_healthy: Current driver health status
        _consecutive_failures: Count of consecutive collection failures
        _max_consecutive_failures: Threshold for triggering source degradation
    """

    # Data source priority order (highest priority first)
    SOURCE_PRIORITY: List[str] = ['wmi', 'pytorch', 'psutil']

    # AMD driver service process name (External Events Service)
    DRIVER_PROCESS_NAME: str = "amdagsvc.exe"

    # Configuration constants
    DRIVER_CHECK_INTERVAL_SECONDS: float = 30.0  # Check interval for driver health
    MAX_CONSECUTIVE_FAILURES: int = 5  # Trigger degradation after N failures
    COLLECTION_TIMEOUT_SECONDS: float = 2.0  # Max time per collection attempt
    WMI_QUERY_TIMEOUT_SECONDS: float = 5.0  # Max time for WMI operations
    SLEEP_DETECTION_THRESHOLD_SECONDS: float = 60.0  # Uptime change threshold for sleep detection

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the Windows AMD GPU Provider.

        Args:
            config: Optional configuration dictionary. Supported keys:
                - wmi_timeout: WMI query timeout in seconds (default: 5.0)
                - collection_timeout: Overall collection timeout (default: 2.0)
                - max_retries: Maximum retry attempts for failed operations (default: 2)
                - enable_driver_monitoring: Enable driver health monitoring (default: True)
                - enable_radeon_detection: Enable Radeon Software conflict detection (default: True)
        """
        super().__init__(name="amd-windows", config=config)

        self._name: str = "AMD Windows Provider"
        self._vendor_name: str = "AMD"

        # Data source availability flags
        self._active_sources: List[str] = []
        self._wmi_available: bool = False
        self._pytorch_available: bool = False
        _psutil_available: bool = False

        # WMI connection object (initialized during _init_wmi)
        self._wmi_conn: Optional[Any] = None

        # Device information cache
        self._device_count: int = 0
        self._device_names: List[str] = []

        # Windows-specific state
        self._is_admin: bool = False
        self._driver_process_name: str = self.DRIVER_PROCESS_NAME
        self._last_driver_check: float = 0.0
        self._driver_healthy: bool = True
        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = self.MAX_CONSECUTIVE_FAILURES

        # Sleep/wakeup detection
        self._last_system_uptime: float = 0.0
        self._sleep_detected: bool = False

        # Performance statistics
        self._total_collections: int = 0
        self._failed_collections: int = 0
        self._last_collection_time_ms: float = 0.0

        # Configuration extraction with defaults
        self._wmi_timeout: float = config.get('wmi_timeout', self.WMI_QUERY_TIMEOUT_SECONDS) if config else self.WMI_QUERY_TIMEOUT_SECONDS
        self._collection_timeout: float = config.get('collection_timeout', self.COLLECTION_TIMEOUT_SECONDS) if config else self.COLLECTION_TIMEOUT_SECONDS
        self._max_retries: int = config.get('max_retries', 2) if config else 2
        self._enable_driver_monitoring: bool = config.get('enable_driver_monitoring', True) if config else True
        self._enable_radeon_detection: bool = config.get('enable_radeon_detection', True) if config else True

        logger.debug(
            f"AMDWindowsProvider initialized with config: "
            f"wmi_timeout={self._wmi_timeout}s, "
            f"collection_timeout={self._collection_timeout}s, "
            f"max_retries={self._max_retries}"
        )

    # =========================================================================
    # Property Implementations (BaseGPUProvider Interface)
    # =========================================================================

    @property
    def name(self) -> str:
        """Return the provider name."""
        return self._name

    @property
    def vendor_name(self) -> str:
        """Return the GPU vendor name."""
        return self._vendor_name

    @property
    def is_initialized(self) -> bool:
        """Check if the provider has been successfully initialized."""
        return self._initialized

    @property
    def is_available(self) -> bool:
        """
        Check if this provider can be used on the current platform.

        Performs a lightweight check for AMD GPU presence without full initialization.
        """
        if platform.system() != "Windows":
            return False

        # Quick check for AMD GPU presence
        try:
            gpu_info = detect_windows_gpu_info()
            if gpu_info.get("vendor") == "amd":
                return True
            if gpu_info.get("wmi_available") and "radeon" in gpu_info.get("name", "").lower():
                return True
        except Exception as e:
            logger.debug(f"Availability check failed: {e}")

        # Fallback: Check for PyTorch CUDA availability
        try:
            import torch
            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0).lower()
                if any(kw in device_name for kw in ["amd", "radeon", "ati"]):
                    return True
        except ImportError:
            pass
        except Exception:
            pass

        return False

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    def initialize(self) -> bool:
        """
        Initialize the Windows AMD GPU data collection environment.

        This method attempts to initialize all three data sources in priority order,
        enabling graceful degradation if some sources are unavailable.

        Initialization Sequence:
            1. Detect administrative privileges (affects WMI capabilities)
            2. Initialize WMI data source (primary)
            3. Initialize PyTorch data source (supplementary)
            4. Initialize psutil data source (fallback - should always succeed)
            5. Perform conflict detection (Radeon Software)
            6. Record baseline system uptime for sleep detection

        Returns:
            True if at least one data source was successfully initialized,
            False if no data sources are available.

        Raises:
            No exceptions are raised; errors are logged and handled internally.
        """
        if self._initialized:
            logger.warning("AMDWindowsProvider already initialized")
            return True

        logger.info("=" * 60)
        logger.info("Initializing Windows AMD GPU Provider (Three-Layer Fault Tolerance)")
        logger.info("=" * 60)

        start_time = time.perf_counter()

        # Step 1: Detect admin privileges
        try:
            self._is_admin = is_admin()
            logger.info(f"Administrative privileges: {'Yes' if self._is_admin else 'No'}")
            if not self._is_admin:
                logger.warning(
                    "Running without admin privileges. Some WMI queries may return limited data. "
                    "Consider running ComfyUI as Administrator for full GPU monitoring capabilities."
                )
        except Exception as e:
            logger.warning(f"Admin privilege detection failed: {e}")
            self._is_admin = False

        # Step 2: Initialize data sources in priority order
        sources_initialized: List[str] = []

        # Layer 1: WMI (Primary)
        if self._init_wmi():
            sources_initialized.append('wmi')
            logger.info("[✓] WMI data source initialized (Primary)")

        # Layer 2: PyTorch (Supplementary)
        if self._init_pytorch():
            sources_initialized.append('pytorch')
            logger.info("[✓] PyTorch data source initialized (Supplementary)")

        # Layer 3: psutil (Fallback - must succeed)
        if self._init_psutil():
            sources_initialized.append('psutil')
            logger.info("[✓] psutil data source initialized (Fallback)")
        else:
            logger.critical(
                "[✗] psutil initialization failed! This is a critical error as psutil "
                "is a required dependency. GPU monitoring will be severely limited."
            )

        # Validate that we have at least one working data source
        if len(sources_initialized) == 0:
            logger.error(
                "[✗] No data sources available on Windows! Cannot initialize AMD GPU provider."
            )
            return False

        self._active_sources = sources_initialized
        self._initialized = True

        # Step 3: Initial conflict detection
        if self._enable_radeon_detection:
            try:
                self.detect_radeon_software_conflict()
            except Exception as e:
                logger.debug(f"Radeon Software conflict detection failed: {e}")

        # Step 4: Record baseline system uptime for sleep/wakeup detection
        self._last_system_uptime = self._get_system_uptime_seconds()

        # Log initialization summary
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info("-" * 60)
        logger.info(f"Initialization completed in {elapsed_ms:.1f}ms")
        logger.info(f"Active data sources: {self._active_sources}")
        logger.info(f"Device count: {self._device_count}")
        if self._device_names:
            for idx, name in enumerate(self._device_names):
                logger.info(f"  Device {idx}: {name}")
        logger.info(f"Driver monitoring: {'Enabled' if self._enable_driver_monitoring else 'Disabled'}")
        logger.info("=" * 60)

        return True

    def shutdown(self) -> None:
        """
        Clean up resources and shut down the provider.

        Releases WMI connections, clears caches, and resets all state.
        This method is safe to call multiple times.
        """
        logger.info("Shutting down Windows AMD GPU Provider...")

        # Release WMI connection
        if hasattr(self, '_wmi_conn') and self._wmi_conn is not None:
            try:
                # WMI objects don't always have an explicit close method,
                # but we should delete the reference to allow garbage collection
                del self._wmi_conn
                self._wmi_conn = None
                logger.debug("WMI connection released")
            except Exception as e:
                logger.warning(f"Error releasing WMI connection: {e}")

        # Clear state
        self._active_sources = []
        self._wmi_available = False
        self._pytorch_available = False
        self._initialized = False
        self._device_count = 0
        self._device_names = []

        # Log final statistics
        success_rate = (
            ((self._total_collections - self._failed_collections) / max(1, self._total_collections)) * 100
            if self._total_collections > 0 else 0
        )
        logger.info(
            f"Shutdown complete. Statistics: "
            f"total_collections={self._total_collections}, "
            f"failed={self._failed_collections}, "
            f"success_rate={success_rate:.1f}%"
        )

    # =========================================================================
    # Layer 1: WMI Data Source Implementation (Primary)
    # =========================================================================

    def _init_wmi(self) -> bool:
        """
        Initialize the WMI data source for GPU information retrieval.

        Attempts to establish a WMI connection and verify that at least one
        video controller (GPU) is accessible.

        WMI Classes Used:
            - Win32_VideoController: Basic adapter info (name, RAM, driver)
            - Win32_PerfFormattedData_Counters_GPUInfo: Performance counters (if available)

        Returns:
            True if WMI was successfully initialized, False otherwise.
        """
        try:
            # Method 1: Try using the wmi Python package (preferred)
            import wmi

            self._wmi_conn = wmi.WMI()
            test_query = list(self._wmi_conn.Win32_VideoController())

            if len(test_query) == 0:
                logger.warning("WMI connected but no video controllers found")
                return False

            # Filter for AMD GPUs only
            amd_gpus = [
                gpu for gpu in test_query
                if gpu.Name and any(
                    kw in gpu.Name.lower()
                    for kw in ["amd", "radeon", "ati", "advanced micro devices"]
                )
            ]

            if len(amd_gpus) == 0:
                logger.debug(
                    f"WMI found {len(test_query)} video controller(s), but none are AMD GPUs"
                )
                # Still mark as available if there's at least one GPU (for hybrid systems)
                # but log a warning
                if len(test_query) > 0:
                    logger.info(
                        f"WMI found non-AMD GPU(s): {[g.Name for g in test_query[:3]]}"
                    )
                return False

            self._wmi_available = True
            self._device_count = len(amd_gpus)

            for gpu in amd_gpus:
                device_name = gpu.Name or "Unknown AMD GPU"
                # Handle potential encoding issues on Windows
                if isinstance(device_name, bytes):
                    device_name = device_name.decode('utf-8', errors='ignore')
                self._device_names.append(device_name)

            logger.info(
                f"WMI initialized successfully: {self._device_count} AMD GPU(s) detected"
            )
            return True

        except ImportError:
            logger.debug(
                "WMI Python package not installed. "
                "Install with: pip install wmi"
            )
            return False

        except Exception as e:
            logger.error(f"WMI initialization failed: {e}")
            logger.debug(f"WMI error details:", exc_info=True)
            return False

    @retry_on_failure(max_retries=2, delay=0.2, exceptions=(Exception,))
    def _collect_wmi(self, device_id: int = 0) -> Dict[str, Any]:
        """
        Collect GPU data via WMI interface.

        This method retrieves GPU information through Windows Management Instrumentation.
        It implements defensive programming to handle the various failure modes common
        to AMD's WMI implementation on Windows.

        Data Retrieved:
            - device_name: GPU model name (from Win32_VideoController)
            - driver_version: Installed driver version string
            - vram_total: Total VRAM in MB (from AdapterRAM, converted from bytes)
            - gpu_utilization: GPU utilization percentage (from perf counters, if available)
            - temperature: Always None (WMI cannot reliably read AMD GPU temperature)
            - power_usage: Always None (WMI cannot read AMD GPU power consumption)
            - clock_speed: Always None (not available via standard WMI classes)
            - vram_used: Estimated VRAM usage (inaccurate via WMI)

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Dictionary containing collected GPU metrics.

        Raises:
            RuntimeError: If WMI is not available or device_id is out of range.
            Exception: Various WMI query exceptions (handled by retry decorator).
        """
        if not self._wmi_available:
            raise RuntimeError("WMI data source not available")

        if self._wmi_conn is None:
            raise RuntimeError("WMI connection is None")

        data: Dict[str, Any] = {}

        try:
            # ---- Basic Information from Win32_VideoController ----
            gpus = list(self._wmi_conn.Win32_VideoController())

            if device_id >= len(gpus):
                logger.error(f"Device ID {device_id} out of range (found {len(gpus)} GPUs)")
                raise IndexError(f"Invalid device_id: {device_id}")

            gpu = gpus[device_id]

            # Device name (handle encoding issues)
            raw_name = getattr(gpu, 'Name', None)
            if raw_name:
                if isinstance(raw_name, bytes):
                    data['device_name'] = raw_name.decode('utf-8', errors='ignore')
                else:
                    data['device_name'] = str(raw_name)
            else:
                data['device_name'] = "Unknown AMD GPU"

            # Driver version
            raw_version = getattr(gpu, 'DriverVersion', None)
            data['driver_version'] = str(raw_version) if raw_version else ""

            # Total VRAM (AdapterRAM is in bytes)
            raw_ram = getattr(gpu, 'AdapterRAM', None)
            if raw_ram and int(raw_ram) > 0:
                data['vram_total'] = int(raw_ram) // (1024 * 1024)  # Convert to MB
            else:
                data['vram_total'] = 0
                logger.debug(f"AdapterRAM unavailable or zero for device {device_id}")

            # Refresh rate (can be used as a proxy for load inference)
            refresh_rate = getattr(gpu, 'CurrentRefreshRate', None)
            data['refresh_rate'] = int(refresh_rate) if refresh_rate else 0

            # PNP Device ID (useful for diagnostics)
            pnp_id = getattr(gpu, 'PNPDeviceID', None)
            data['pnp_device_id'] = str(pnp_id) if pnp_id else ""

            # ---- Performance Counters (Optional) ----
            try:
                perf_data = list(
                    self._wmi_conn.Win32_PerfFormattedData_Counters_GPUInfo()
                )

                if device_id < len(perf_data):
                    perf = perf_data[device_id]

                    # GPU Utilization Percentage
                    util_value = getattr(perf, 'UtilizationPercentage', None)
                    if util_value is not None:
                        try:
                            data['gpu_utilization'] = float(util_value)
                            # Sanity check: utilization should be 0-100
                            if not 0 <= data['gpu_utilization'] <= 100:
                                logger.warning(
                                    f"WMI returned suspicious utilization value: "
                                    f"{data['gpu_utilization']}%"
                                )
                                data['gpu_utilization'] = min(100, max(0, data['gpu_utilization']))
                        except (ValueError, TypeError):
                            data['gpu_utilization'] = None
                            logger.debug(f"Failed to parse utilization value: {util_value}")
                    else:
                        data['gpu_utilization'] = None

                    # Other potentially available metrics
                    fan_speed = getattr(perf, 'FanSpeed', None)
                    if fan_speed is not None:
                        try:
                            data['fan_speed'] = int(fan_speed)
                        except (ValueError, TypeError):
                            pass

            except Exception as perf_e:
                # Performance counters are often unavailable for AMD GPUs
                logger.debug(f"WMI performance counters unavailable: {perf_e}")
                data['gpu_utilization'] = None

            # ---- Fields Unavailable via Standard WMI ----
            data['temperature'] = None
            data['power_usage'] = None
            data['clock_speed'] = None

            # ---- VRAM Usage Estimation (Inaccurate) ----
            data['vram_used'] = self._estimate_vram_usage_wmi(device_id)

            logger.debug(
                f"WMI collection successful for device {device_id}: "
                f"name='{data.get('device_name', '')[:30]}', "
                f"vram_total={data.get('vram_total', 0)}MB, "
                f"util={data.get('gpu_utilization')}"
            )

        except IndexError:
            raise  # Re-raise index errors (invalid device_id)
        except Exception as e:
            logger.error(f"WMI collection failed for device {device_id}: {e}")
            raise

        return data

    def _estimate_vram_usage_wmi(self, device_id: int = 0) -> int:
        """
        Estimate VRAM usage through WMI (inherently inaccurate).

        WMI does not provide accurate VRAM usage for AMD GPUs on Windows.
        This method attempts several approximation strategies:

        Strategy 1: Query GPU process memory (very rough estimate)
        Strategy 2: Return 0 (indicating unavailability)

        Warning:
            The returned value should NOT be used for critical decisions.
            Always prefer PyTorch's torch.cuda.memory_allocated() for accuracy.

        Args:
            device_id: GPU device index

        Returns:
            Estimated VRAM usage in MB (likely 0 or highly inaccurate).
        """
        # Strategy 1: Try to identify GPU-associated processes
        # Note: WorkingSetSize is RAM, not VRAM, but can serve as a proxy
        estimated_usage = 0

        try:
            if self._wmi_conn is None:
                return 0

            gpu_process_keywords = ['amd', 'ati', 'radeon', 'atil', 'd3d', 'dxgi']
            process_memory_sum = 0

            for process in self._wmi_conn.Win32_Process():
                try:
                    proc_name = getattr(process, 'Name', '')
                    if proc_name and any(
                        kw in proc_name.lower()
                        for kw in gpu_process_keywords
                    ):
                        ws = getattr(process, 'WorkingSetSize', 0)
                        if ws:
                            # Convert bytes to MB, take a small fraction as VRAM proxy
                            process_memory_sum += int(ws) // (1024 * 1024)
                except Exception:
                    continue

            # Use a fraction of process memory as very rough VRAM estimate
            # This is highly inaccurate but better than nothing
            estimated_usage = min(process_memory_sum // 10, 1024)  # Cap at 1024MB estimate

        except Exception as e:
            logger.debug(f"VRAM estimation via WMI failed: {e}")

        if estimated_usage > 0:
            logger.debug(
                f"Estimated VRAM usage (WMI, inaccurate): ~{estimated_usage}MB"
            )

        return estimated_usage

    # =========================================================================
    # Layer 2: PyTorch Data Source Implementation (Supplementary)
    # =========================================================================

    def _init_pytorch(self) -> bool:
        """
        Check if PyTorch is available with GPU support.

        Verifies that:
            1. PyTorch is installed (importable)
            2. CUDA/DirectML backend is available
            3. At least one GPU device is visible to PyTorch

        Returns:
            True if PyTorch with GPU support is available, False otherwise.
        """
        try:
            import torch

            # Check CUDA availability
            if not torch.cuda.is_available():
                logger.info(
                    "PyTorch installed but no CUDA/DirectML GPU detected. "
                    "PyTorch data source will be disabled."
                )
                return False

            device_count = torch.cuda.device_count()
            if device_count == 0:
                logger.warning("PyTorch reports CUDA available but 0 devices found")
                return False

            self._pytorch_available = True

            # Update device count and names if not already set by WMI
            if self._device_count == 0:
                self._device_count = device_count

            for i in range(device_count):
                try:
                    device_name = torch.cuda.get_device_name(i)
                    if i >= len(self._device_names):
                        self._device_names.append(device_name)
                    logger.debug(f"PyTorch device {i}: {device_name}")
                except Exception as e:
                    logger.debug(f"Failed to get PyTorch device {i} name: {e}")
                    if i >= len(self._device_names):
                        self._device_names.append(f"CUDA Device {i}")

            # Detect backend type
            backend_info = ""
            if hasattr(torch.version, 'hip'):
                backend_info = "HIP/ROCm"
            elif hasattr(torch.version, 'cuda'):
                cuda_version = getattr(torch.version, 'cuda', 'unknown')
                backend_info = f"CUDA {cuda_version}"

            logger.info(
                f"PyTorch GPU backend available: {device_count} device(s) ({backend_info})"
            )
            return True

        except ImportError:
            logger.debug("PyTorch not installed")
            return False

        except Exception as e:
            logger.warning(f"PyTorch initialization check failed: {e}")
            return False

    @retry_on_failure(max_retries=1, delay=0.1, exceptions=(Exception,))
    def _collect_pytorch(self, device_id: int = 0) -> Dict[str, Any]:
        """
        Collect GPU data via PyTorch interface.

        Provides more accurate VRAM usage data than WMI, but may have limitations
        when using DirectML backend (some CUDA APIs are unsupported).

        Data Retrieved:
            - vram_used: Accurate VRAM allocated by PyTorch (MB)
            - vram_reserved: PyTorch caching allocator reserved memory (MB)
            - vram_total: Total GPU memory (MB)
            - gpu_utilization: GPU utilization % (may not work on DirectML)
            - device_name: GPU model name from PyTorch
            - temperature/Power/clock_speed: None (not available via PyTorch)

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Dictionary containing collected GPU metrics from PyTorch.

        Raises:
            Exception: Various PyTorch API exceptions (handled by retry decorator).
        """
        import torch

        data: Dict[str, Any] = {}

        # ---- Memory Information (Most Reliable Part) ----
        try:
            # Allocated memory (actual usage by tensors)
            allocated_bytes = torch.cuda.memory_allocated(device_id)
            data['vram_used'] = allocated_bytes // (1024 * 1024)  # Convert to MB

            # Reserved memory (cached by PyTorch allocator)
            reserved_bytes = torch.cuda.memory_reserved(device_id)
            data['vram_reserved'] = reserved_bytes // (1024 * 1024)

            # Total memory
            props = torch.cuda.get_device_properties(device_id)
            data['vram_total'] = props.total_mem // (1024 * 1024)

        except Exception as mem_e:
            logger.debug(f"PyTorch memory query failed: {mem_e}")
            data['vram_used'] = 0
            data['vram_reserved'] = 0
            data['vram_total'] = 0

        # ---- GPU Utilization (May Fail on DirectML) ----
        try:
            util_value = torch.cuda.utilization(device_id)
            data['gpu_utilization'] = float(util_value)

            # Sanity check
            if not 0 <= data['gpu_utilization'] <= 100:
                logger.warning(
                    f"PyTorch returned suspicious utilization: {data['gpu_utilization']}%"
                )
                data['gpu_utilization'] = min(100, max(0, data['gpu_utilization']))

        except Exception as util_e:
            logger.debug(f"PyTorch utilization query failed (normal on DirectML): {util_e}")
            data['gpu_utilization'] = None

        # ---- Device Name ----
        try:
            if device_id < torch.cuda.device_count():
                data['device_name'] = torch.cuda.get_device_name(device_id)
            else:
                data['device_name'] = f"Unknown (device {device_id})"
        except Exception:
            data['device_name'] = "Unknown (PyTorch)"

        # ---- Unavailable Metrics ----
        data['temperature'] = None
        data['power_usage'] = None
        data['clock_speed'] = None
        data['driver_version'] = ""  # Not available from PyTorch

        logger.debug(
            f"PyTorch collection for device {device_id}: "
            f"vram_used={data.get('vram_used', 0)}MB, "
            f"vram_total={data.get('vram_total', 0)}MB, "
            f"util={data.get('gpu_utilization')}"
        )

        return data

    # =========================================================================
    # Layer 3: psutil Fallback Implementation (Guaranteed)
    # =========================================================================

    def _init_psutil(self) -> bool:
        """
        Initialize psutil as fallback data source.

        psutil should always be available as it's a required dependency of this project.
        This method verifies its availability and logs appropriately.

        Returns:
            True if psutil is available (should always be True).
        """
        try:
            import psutil

            # Verify it actually works
            psutil.cpu_count()
            self._psutil_available = True

            logger.debug("psutil available (fallback source)")
            return True

        except ImportError:
            logger.critical(
                "psutil not installed! This is a required dependency. "
                "Install with: pip install psutil"
            )
            return False

        except Exception as e:
            logger.error(f"psutil initialization failed unexpectedly: {e}")
            return False

    def _collect_psutil(self, device_id: int = 0) -> Dict[str, Any]:
        """
        Collect system information via psutil (fallback data source).

        When both WMI and PyTorch are unavailable, psutil provides basic system
        metrics that can be useful for inferring system load state.

        Available Data:
            - cpu_percent: CPU utilization (%)
            - ram_total/used/percent: Physical memory information
            - gpu_processes: List of GPU-related process names (diagnostic)

        Unavailable Data (returns None/0):
            - GPU utilization, VRAM, temperature, power, clock speed

        Args:
            device_id: GPU device index (ignored by psutil, kept for interface consistency).

        Returns:
            Dictionary containing system metrics from psutil.
        """
        import psutil

        data: Dict[str, Any] = {}

        # ---- CPU Information ----
        try:
            data['cpu_percent'] = psutil.cpu_percent(interval=None)
        except Exception as e:
            logger.debug(f"CPU percent query failed: {e}")
            data['cpu_percent'] = 0.0

        # ---- Memory Information ----
        try:
            mem = psutil.virtual_memory()
            data['ram_total'] = mem.total // (1024 * 1024)  # MB
            data['ram_used'] = mem.used // (1024 * 1024)  # MB
            data['ram_percent'] = mem.percent
        except Exception as e:
            logger.debug(f"Memory info query failed: {e}")
            data['ram_total'] = 0
            data['ram_used'] = 0
            data['ram_percent'] = 0.0

        # ---- GPU Information (Limited Capability) ----
        data['gpu_utilization'] = None
        data['vram_used'] = 0
        data['vram_total'] = 0
        data['temperature'] = None
        data['power_usage'] = None
        data['clock_speed'] = None
        data['device_name'] = "AMD GPU (psutil fallback mode)"
        data['driver_version'] = ""

        # ---- GPU-Related Process Identification (Diagnostic) ----
        gpu_processes: List[str] = []
        try:
            gpu_keywords = ['amd', 'ati', 'radeon', 'atil', 'amdagsvc', 'radeonsoftware',
                           'adrenalin', 'amdkmdag', 'amdkmdap']

            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    proc_info = proc.info
                    proc_name_lower = proc_info['name'].lower()

                    if any(keyword in proc_name_lower for keyword in gpu_keywords):
                        gpu_processes.append(proc_info['name'])

                        # Limit to prevent excessive memory usage
                        if len(gpu_processes) >= 10:
                            break

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

        except Exception as proc_e:
            logger.debug(f"GPU process enumeration failed: {proc_e}")

        data['gpu_processes'] = gpu_processes

        logger.debug(
            f"psutil fallback collection: "
            f"cpu={data.get('cpu_percent')}%, "
            f"ram={data.get('ram_percent')}%, "
            f"gpu_processes={len(data.get('gpu_processes', []))}"
        )

        return data

    # =========================================================================
    # Windows-Specific Problem Handling
    # =========================================================================

    def check_driver_health(self) -> bool:
        """
        Check AMD driver service process health status.

        Monitors the AMD External Events Service (amdagsvc.exe) to detect
        driver crashes or hangs. This is critical because AMD driver crashes
        can cause WMI queries to hang indefinitely.

        Monitoring Behavior:
            - Checks every 30 seconds (configurable via DRIVER_CHECK_INTERVAL_SECONDS)
            - Verifies process existence and running status
            - Logs warnings on unhealthy states
            - Returns cached result between checks

        Returns:
            True if the driver appears healthy, False if issues detected.

        Note:
            This method is called automatically before each collection cycle
            if ``_enable_driver_monitoring`` is True.
        """
        current_time = time.time()

        # Rate-limit checks to avoid performance impact
        if current_time - self._last_driver_check < self.DRIVER_CHECK_INTERVAL_SECONDS:
            return self._driver_healthy

        self._last_driver_check = current_time

        try:
            import psutil

            found = False
            target_process = self._driver_process_name.lower()

            for proc in psutil.process_iter(['pid', 'name', 'status']):
                try:
                    proc_name = proc.info['name'].lower()

                    if proc_name == target_proc or target_proc in proc_name:
                        found = True
                        proc_status = proc.info['status']

                        if proc_status == psutil.STATUS_RUNNING:
                            self._driver_healthy = True
                        else:
                            logger.warning(
                                f"AMD driver process '{proc.info['name']}' (PID={proc.info['pid']}) "
                                f"has abnormal status: {proc_status}"
                            )
                            self._driver_healthy = False
                        break

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not found:
                logger.error(
                    f"AMD driver process '{self._driver_process_name}' not found! "
                    f"This may indicate a driver crash or installation issue."
                )
                self._driver_healthy = False

        except Exception as e:
            logger.warning(f"Driver health check failed: {e}")
            # Don't change healthy status on check failure (assume still healthy)

        return self._driver_healthy

    def detect_radeon_software_conflict(self) -> bool:
        """
        Detect Radeon Software (Adrenalin) interference with GPU monitoring.

        Problem Description:
            Radeon Software's overlay and monitoring features can:
                - Cause WMI queries to slow down significantly
                - Lock certain GPU query interfaces
                - Return fixed/incorrect values for utilization metrics
                - Cause 0% or 100% utilization readings regardless of actual load

        Detection Method:
            Scans running processes for RadeonSoftware.exe or Adrenalin-related processes.

        Mitigation Recommendations (logged to user):
            - Disable Radeon Software overlay feature
            - Close Radeon Software before intensive monitoring sessions
            - Use basic driver settings instead of Adrenalin overlay

        Returns:
            True if Radeon Software interference is detected, False otherwise.
        """
        if not self._enable_radeon_detection:
            return False

        try:
            import psutil

            radeon_indicators = [
                'radeonsoftware',
                'adrenalin',
                'radeonsettings',
                'amdvedeo',  # Sometimes misspelled in process names
            ]

            detected_processes: List[str] = []

            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    proc_name_lower = proc.info['name'].lower()

                    for indicator in radeon_indicators:
                        if indicator in proc_name_lower:
                            detected_processes.append(proc.info['name'])
                            break

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if detected_processes:
                unique_processes = list(set(detected_processes))
                logger.warning(
                    "=" * 60
                )
                logger.warning(
                    "⚠ Radeon Software (Adrenalin) DETECTED!"
                )
                logger.warning(
                    f"Processes found: {', '.join(unique_processes)}"
                )
                logger.warning(
                    "This may interfere with GPU monitoring and cause:"
                )
                logger.warning(
                    "  - Slow or hanging WMI queries"
                )
                logger.warning(
                    "  - Inaccurate GPU utilization readings"
                )
                logger.warning(
                    "  - Intermittent data collection failures"
                )
                logger.warning(
                    "-" * 60
                )
                logger.warning(
                    "RECOMMENDATIONS:"
                )
                logger.warning(
                    "  1. Disable Radeon Software overlay (RSOverlay)"
                )
                logger.warning(
                    "  2. Close Adrenalin panel during monitoring sessions"
                )
                logger.warning(
                    "  3. Or use basic 'Driver Only' installation mode"
                )
                logger.warning(
                    "=" * 60
                )
                return True

        except Exception as e:
            logger.debug(f"Radeon Software detection failed: {e}")

        return False

    def handle_sleep_wakeup(self) -> None:
        """
        Handle system sleep/wakeup reconnection.

        Windows systems can suspend/hibernate, which may invalidate
        existing handles and connections (especially WMI).

        Detection Method:
            Monitor system uptime via GetTickCount64(). If uptime suddenly
            decreases (system resumed from sleep), trigger reinitialization.

        Implementation Notes:
            - Uses ctypes for lightweight Windows API access
            - Compares against baseline recorded during initialize()
            - Triggers warning log and suggests re-initialization to caller
        """
        try:
            current_uptime = self._get_system_uptime_seconds()

            if self._last_system_uptime > 0:
                # If current uptime is significantly less than previous, system likely resumed
                uptime_diff = self._last_system_uptime - current_uptime

                if uptime_diff > self.SLEEP_DETECTION_THRESHOLD_SECONDS:
                    if not self._sleep_detected:
                        self._sleep_detected = True
                        logger.warning(
                            f"System sleep/wakeup detected! "
                            f"Uptime decreased by {uptime_diff:.0f}s "
                            f"(from {self._last_system_uptime:.0f}s to {current_uptime:.0f}s). "
                            f"Some data sources (especially WMI) may need reinitialization."
                        )

                        # Attempt automatic recovery
                        self._attempt_sleep_recovery()
            else:
                # First call, just record baseline
                pass

            self._last_system_uptime = current_uptime

        except Exception as e:
            logger.debug(f"Sleep/wakeup detection failed: {e}")

    def _get_system_uptime_seconds(self) -> float:
        """
        Get system uptime in seconds using Windows API.

        Uses GetTickCount64() for millisecond-precision uptime.

        Returns:
            System uptime in seconds, or 0.0 on failure.
        """
        if platform.system() != "Windows":
            # Non-Windows fallback
            try:
                import psutil
                return psutil.boot_time()
            except Exception:
                return 0.0

        try:
            # GetTickCount64 returns milliseconds since system boot
            uptime_ms = ctypes.windll.kernel32.GetTickCount64()
            return uptime_ms / 1000.0
        except Exception as e:
            logger.debug(f"GetTickCount64 failed: {e}")
            return 0.0

    def _attempt_sleep_recovery(self) -> None:
        """
        Attempt to recover data sources after system wakeup.

        Tries to reinitialize WMI connection which may have become stale.
        Logs success/failure for debugging purposes.
        """
        logger.info("Attempting post-sleep recovery...")

        recovery_successes = 0

        # Try to recover WMI
        if 'wmi' in self._active_sources or self._wmi_available:
            old_wmi_conn = self._wmi_conn
            self._wmi_available = False
            self._wmi_conn = None

            if self._init_wmi():
                recovery_successes += 1
                logger.info("[✓] WMI recovered after sleep")
            else:
                # Restore old connection if recovery failed
                self._wmi_conn = old_wmi_conn
                logger.warning("[✗] WMI recovery failed, keeping stale connection")

        # Try to recover PyTorch
        if 'pytorch' in self._active_sources or self._pytorch_available:
            old_pytorch_avail = self._pytorch_available
            self._pytorch_available = False

            if self._init_pytorch():
                recovery_successes += 1
                logger.info("[✓] PyTorch recovered after sleep")
            else:
                self._pytorch_available = old_pytorch_avail
                logger.warning("[✗] PyTorch recovery failed")

        if recovery_successes > 0:
            logger.info(f"Sleep recovery: {recovery_successes}/{len(self._active_sources)} sources restored")
        else:
            logger.error("All sleep recovery attempts failed. Manual re-initialization may be required.")

    # =========================================================================
    # Data Merging Logic (Multi-Source Fusion)
    # =========================================================================

    def _merge_data_from_multiple_sources(self, device_id: int = 0) -> GPUMetrics:
        """
        Merge data from all active sources into unified GPUMetrics.

        Merging Strategy (Priority-Based):
            - **Device Name**: WMI (most authoritative) > PyTorch > psutil fallback
            - **Driver Version**: WMI only (other sources don't provide this)
            - **VRAM Total**: WMI (hardware-reported) > PyTorch
            - **VRAM Used**: PyTorch (most accurate) > WMI estimation > 0
            - **GPU Utilization**: WMI > PyTorch > 0.0 default
            - **Temperature/Power/Clock**: Whoever has it, otherwise None
            - **Fallback**: If all sources fail, returns zeros/safe defaults

        Error Isolation:
            Each source is collected independently with its own try-except,
            ensuring one source's failure doesn't prevent others from contributing.

        Args:
            device_id: GPU device index (0-based)

        Returns:
            GPUMetrics object containing merged data from all available sources.
        """
        wmi_data: Dict[str, Any] = {}
        pytorch_data: Dict[str, Any] = {}
        psutil_data: Dict[str, Any] = {}

        # ---- Collect from each source independently ----

        # Layer 1: WMI (Primary)
        if self._wmi_available and 'wmi' in self._active_sources:
            try:
                # Wrap in timeout for safety
                timeout_result = execute_with_timeout(
                    func=self._collect_wmi,
                    timeout_seconds=self._wmi_timeout,
                    default={},
                    args=(device_id,),
                )

                if timeout_result.success and timeout_result.value:
                    wmi_data = timeout_result.value
                    self._consecutive_failures = 0  # Reset on success
                else:
                    logger.warning(
                        f"WMI collection failed/timed out: {timeout_result.error}"
                    )
                    self._handle_source_failure('wmi')

            except Exception as e:
                logger.warning(f"WMI collection exception: {e}")
                self._handle_source_failure('wmi')

        # Layer 2: PyTorch (Supplementary)
        if self._pytorch_available and 'pytorch' in self._active_sources:
            try:
                timeout_result = execute_with_timeout(
                    func=self._collect_pytorch,
                    timeout_seconds=self._collection_timeout,
                    default={},
                    args=(device_id,),
                )

                if timeout_result.success and timeout_result.value:
                    pytorch_data = timeout_result.value
                else:
                    logger.debug(f"PyTorch collection failed: {timeout_result.error}")
                    self._handle_source_failure('pytorch')

            except Exception as e:
                logger.debug(f"PyTorch collection exception: {e}")
                self._handle_source_failure('pytorch')

        # Layer 3: psutil (Fallback - should always work)
        try:
            psutil_data = self._collect_psutil(device_id)
        except Exception as e:
            logger.error(f"psutil collection failed (this should not happen): {e}")
            psutil_data = {}

        # ---- Merge strategy ----

        # Device name: Prefer WMI, then PyTorch, then fallback
        merged_device_name = (
            wmi_data.get('device_name', '') or
            pytorch_data.get('device_name', '') or
            psutil_data.get('device_name', 'Unknown AMD GPU')
        )

        # Driver version: Only WMI provides this
        merged_driver_version = wmi_data.get('driver_version', '')

        # VRAM total: Prefer WMI (hardware-reported), then PyTorch
        merged_vram_total = (
            wmi_data.get('vram_total', 0) or
            pytorch_data.get('vram_total', 0) or
            0
        )

        # VRAM used: Prefer PyTorch (accurate), then WMI (estimated), then 0
        merged_vram_used = (
            pytorch_data.get('vram_used', 0) or
            wmi_data.get('vram_used', 0) or
            0
        )

        # GPU utilization: Prefer WMI, then PyTorch, default to 0
        merged_utilization = 0.0
        if wmi_data.get('gpu_utilization') is not None:
            merged_utilization = float(wmi_data['gpu_utilization'])
        elif pytorch_data.get('gpu_utilization') is not None:
            merged_utilization = float(pytorch_data['gpu_utilization'])

        # Clamp to valid range
        merged_utilization = max(0.0, min(100.0, merged_utilization))

        # Temperature: Whoever has it
        merged_temperature = (
            wmi_data.get('temperature') or
            pytorch_data.get('temperature') or
            None
        )

        # Power usage: WMI only (usually None for AMD on Windows)
        merged_power = (
            wmi_data.get('power_usage') or
            pytorch_data.get('power_usage') or
            None
        )

        # Clock speed: Usually None on Windows
        merged_clock = (
            wmi_data.get('clock_speed') or
            pytorch_data.get('clock_speed') or
            None
        )

        # Construct final metrics object
        merged_metrics = GPUMetrics(
            gpu_utilization=merged_utilization,
            vram_used=int(merged_vram_used),
            vram_total=int(merged_vram_total),
            temperature=merged_temperature,
            power_usage=merged_power,
            clock_speed=merged_clock,
            device_id=device_id,
            device_name=str(merged_device_name),
            driver_version=str(merged_driver_version),
        )

        # Validate before returning (log warnings for suspicious data)
        if not merged_metrics.validate():
            logger.warning(
                f"Merged metrics validation failed for device {device_id}. "
                f"Data may be unreliable."
            )

        return merged_metrics

    def _handle_source_failure(self, source_name: str) -> None:
        """
        Handle consecutive failures from a data source.

        Implements degradation logic: if a source fails too many times
        consecutively, it's disabled to prevent continuous error spamming
        and wasted resources.

        Degradation Behavior:
            - Tracks consecutive failure count per source
            - When count exceeds MAX_CONSECUTIVE_FAILURES, source is disabled
            - Logs clear messages about source disablement
            - Resets counter on successful collection

        Args:
            source_name: Name of the failing data source ('wmi', 'pytorch', etc.)
        """
        self._consecutive_failures += 1

        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.error(
                f"[DEGRADATION] Data source '{source_name}' has failed "
                f"{self._consecutive_failures} times consecutively. "
                f"Disabling this source to prevent further resource waste."
            )

            if source_name in self._active_sources:
                self._active_sources.remove(source_name)
                logger.error(
                    f"Active sources remaining: {self._active_sources}"
                )

            # Reset counter after degradation action
            self._consecutive_failures = 0

            # Critical warning if no sources remain
            if len(self._active_sources) == 0:
                logger.critical(
                    "[CRITICAL] All data sources have been disabled! "
                    "GPU monitoring is now operating blind. "
                    "Consider restarting the application."
                )

    # =========================================================================
    # Public Interface Implementation (BaseGPUProvider Abstract Methods)
    # =========================================================================

    def get_gpu_count(self) -> int:
        """
        Get the number of AMD GPU devices detected.

        Returns:
            Number of GPU devices (int), or 0 if none detected.
        """
        if not self._initialized:
            logger.warning("get_gpu_count() called before initialization")
            return 0

        return max(self._device_count, 0)

    def get_gpu_name(self, device_id: int = 0) -> str:
        """
        Get the model name of a specific GPU device.

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Human-readable GPU model name string, or fallback message if unknown.
        """
        if not self._initialized:
            return "Not Initialized"

        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]

        return f"AMD GPU (device {device_id})"

    def get_driver_version(self) -> Optional[str]:
        """
        Get the installed AMD graphics driver version.

        Returns:
            Driver version string (e.g., "30.0.13044.4"), or None if unavailable.
        """
        if not self._initialized:
            return None

        # Collect fresh data to get driver version
        try:
            metrics = self._merge_data_from_multiple_sources(0)
            return metrics.driver_version if metrics.driver_version else None
        except Exception as e:
            logger.debug(f"Driver version query failed: {e}")
            return None

    def get_gpu_utilization(self, device_id: int = 0) -> float:
        """
        Get current GPU utilization percentage.

        This is the primary metric for monitoring GPU workload.
        On Windows AMD, this value comes from WMI performance counters
        or PyTorch utilization API.

        Args:
            device_id: GPU device index (0-based)

        Returns:
            GPU utilization as percentage (0.0 to 100.0).
            Returns 0.0 if unable to determine utilization.
        """
        if not self._initialized:
            logger.warning("get_gpu_utilization() called before initialization")
            return 0.0

        start_time = time.perf_counter()

        try:
            # Pre-flight checks
            if self._enable_driver_monitoring:
                self.check_driver_health()

            # Sleep/wakeup handling
            self.handle_sleep_wakeup()

            # Perform multi-source collection
            metrics = self._merge_data_from_multiple_sources(device_id)

            # Update statistics
            self._total_collections += 1
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._last_collection_time_ms = elapsed_ms

            if elapsed_ms > 200:  # Performance warning threshold
                logger.warning(
                    f"GPU utilization collection took {elapsed_ms:.1f}ms "
                    f">(target: <200ms)"
                )

            return metrics.gpu_utilization

        except Exception as e:
            self._failed_collections += 1
            self._total_collections += 1
            logger.error(f"get_gpu_utilization({device_id}) failed: {e}")
            return 0.0

    def get_memory_info(self, device_id: int = 0) -> Dict[str, int]:
        """
        Get GPU memory (VRAM) information.

        Returns detailed VRAM usage statistics including total capacity,
        currently used amount, and free space calculation.

        Priority Order for Accuracy:
            1. PyTorch torch.cuda.mem_get_info() (most accurate)
            2. WMI AdapterRAM (total only, usage estimated)
            3. Cached values from last collection

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Dictionary with keys:
            - 'used': Currently used VRAM in MB (int)
            - 'total': Total VRAM capacity in MB (int)
            - 'free': Free/available VRAM in MB (int)
        """
        if not self._initialized:
            return {'used': 0, 'total': 0, 'free': 0}

        try:
            metrics = self._merge_data_from_multiple_sources(device_id)

            return {
                'used': metrics.vram_used,
                'total': metrics.vram_total,
                'free': metrics.vram_free,
            }

        except Exception as e:
            logger.error(f"get_memory_info({device_id}) failed: {e}")
            return {'used': 0, 'total': 0, 'free': 0}

    def get_memory_reserved(self, device_id: int = 0) -> int:
        """
        Get PyTorch-reserved (cached) VRAM.

        PyTorch's caching allocator reserves memory beyond what's actively
        used by tensors. This represents the total memory managed by PyTorch's
        allocator, including cached free blocks ready for reuse.

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Reserved VRAM in MB (int), or 0 if unavailable.
        """
        if not self._initialized:
            return 0

        # Only available from PyTorch source
        if not (self._pytorch_available and 'pytorch' in self._active_sources):
            return 0

        try:
            import torch
            if torch.cuda.is_available():
                reserved_bytes = torch.cuda.memory_reserved(device_id)
                return reserved_bytes // (1024 * 1024)
        except Exception as e:
            logger.debug(f"Memory reserved query failed: {e}")

        return 0

    def get_temperature(self, device_id: int = 0) -> Optional[float]:
        """
        Get GPU core temperature.

        **Important Limitation on Windows:**
        AMD GPU temperature is generally NOT available through standard APIs
        on Windows. This method will typically return None unless:
            - Third-party tools (GPU-Z, HWiNFO) are providing shared memory data
            - Custom ADL (ATI Display Library) SDK integration exists
            - Future AMD drivers expose this via WMI

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Temperature in degrees Celsius (float), or None if unavailable.
        """
        if not self._initialized:
            return None

        try:
            metrics = self._merge_data_from_multiple_sources(device_id)
            return metrics.temperature
        except Exception as e:
            logger.debug(f"Temperature query failed: {e}")
            return None

    def get_power_usage(self, device_id: int = 0) -> Dict[str, float]:
        """
        Get GPU power consumption information.

        **Important Limitation on Windows:**
        Similar to temperature, power draw data is not typically available
        for AMD GPUs on Windows through standard interfaces.

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Dictionary with keys:
            - 'draw_watts': Current power consumption in watts (float)
            - 'limit_watts': Power limit/ceiling in watts (float)
            Both values are 0.0 if unavailable.
        """
        if not self._initialized:
            return {"draw_watts": 0.0, "limit_watts": 0.0}

        try:
            metrics = self._merge_data_from_multiple_sources(device_id)

            if metrics.power_usage is not None:
                return {
                    'draw_watts': float(metrics.power_usage),
                    'limit_watts': 0.0,  # Power limit usually unavailable
                }
        except Exception as e:
            logger.debug(f"Power usage query failed: {e}")

        return {"draw_watts": 0.0, "limit_watts": 0.0}

    def get_clock_speeds(self, device_id: int = 0) -> Dict[str, int]:
        """
        Get GPU clock frequencies.

        **Important Limitation on Windows:**
        Clock speed data is not readily available for AMD GPUs through
        standard Windows APIs.

        Args:
            device_id: GPU device index (0-based)

        Returns:
            Dictionary with keys:
            - 'core_mhz': Core clock frequency in MHz (int)
            - 'memory_mhz': Memory clock frequency in MHz (int)
            Both values are 0 if unavailable.
        """
        if not self._initialized:
            return {"core_mhz": 0, "memory_mhz": 0}

        try:
            metrics = self._merge_data_from_multiple_sources(device_id)

            return {
                'core_mhz': metrics.clock_speed if metrics.clock_speed else 0,
                'memory_mhz': 0,  # Memory clock not available via our data sources
            }
        except Exception as e:
            logger.debug(f"Clock speeds query failed: {e}")
            return {"core_mhz": 0, "memory_mhz": 0}

    # =========================================================================
    # Diagnostic and Utility Methods
    # =========================================================================

    def get_provider_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status information for diagnostics.

        Useful for debugging, logging, and UI display of provider state.

        Returns:
            Dictionary containing:
            - initialized: Whether provider is active
            - active_sources: List of operational data source names
            - device_count: Number of detected GPUs
            - device_names: List of GPU model names
            - driver_healthy: Current driver health status
            - is_admin: Admin privilege status
            - statistics: Collection success/failure statistics
            - known_limitations: List of known platform limitations
        """
        status = {
            'provider_name': self.name,
            'vendor': self.vendor_name,
            'platform': 'Windows',
            'initialized': self._initialized,
            'available': self.is_available,

            # Data source status
            'active_sources': list(self._active_sources),
            'wmi_available': self._wmi_available,
            'pytorch_available': self._pytorch_available,
            'psutil_available': self._psutil_available,

            # Device info
            'device_count': self._device_count,
            'device_names': list(self._device_names),

            # Health status
            'driver_healthy': self._driver_healthy,
            'is_admin': self._is_admin,
            'consecutive_failures': self._consecutive_failures,

            # Statistics
            'statistics': {
                'total_collections': self._total_collections,
                'failed_collections': self._failed_collections,
                'success_rate': (
                    ((self._total_collections - self._failed_collections) /
                     max(1, self._total_collections)) * 100
                    if self._total_collections > 0 else 0
                ),
                'last_collection_time_ms': round(self._last_collection_time_ms, 2),
            },

            # Known limitations (important for users to know)
            'known_limitations': [
                "Temperature reading unavailable (Windows AMD limitation)",
                "Power consumption reading unavailable",
                "Clock speed reading unavailable",
                "VRAM usage via WMI is approximate (use PyTorch for accuracy)",
                "Some metrics require Administrator privileges",
                "Radeon Software may interfere with monitoring",
            ],

            # Configuration
            'configuration': {
                'wmi_timeout_seconds': self._wmi_timeout,
                'collection_timeout_seconds': self._collection_timeout,
                'max_retries': self._max_retries,
                'driver_monitoring_enabled': self._enable_driver_monitoring,
                'radeon_detection_enabled': self._enable_radeon_detection,
            },
        }

        return status

    def force_source_retry(self, source_name: str) -> bool:
        """
        Manually re-enable a previously degraded/disabled data source.

        Useful when a transient issue has been resolved (e.g., user closed
        Radeon Software) and you want to retry the source.

        Args:
            source_name: Name of the source to re-enable ('wmi', 'pytorch', 'psutil')

        Returns:
            True if source was re-enabled, False if source name invalid.
        """
        valid_sources = {'wmi', 'pytorch', 'psutil'}

        if source_name not in valid_sources:
            logger.warning(f"Invalid source name: {source_name}. Valid: {valid_sources}")
            return False

        if source_name not in self._active_sources:
            self._active_sources.append(source_name)
            self._consecutive_failures = 0  # Reset failure counter
            logger.info(f"Data source '{source_name}' manually re-enabled")

            # Re-initialize if needed
            if source_name == 'wmi' and not self._wmi_available:
                if self._init_wmi():
                    logger.info("WMI re-initialized successfully")
                else:
                    logger.warning("WMI re-initialization failed")
                    return False

            elif source_name == 'pytorch' and not self._pytorch_available:
                if self._init_pytorch():
                    logger.info("PyTorch re-initialized successfully")
                else:
                    logger.warning("PyTorch re-initialization failed")
                    return False

            return True
        else:
            logger.info(f"Source '{source_name}' is already active")
            return True


# ============================================================================
# Module-Level Testing & Validation (Development Helper)
# ============================================================================

def _run_self_tests() -> Dict[str, Any]:
    """
    Run internal validation tests for the AMD Windows Provider.

    This function is intended for development and debugging purposes only.
    It exercises major code paths without requiring actual hardware.

    Returns:
        Dictionary with test results.
    """
    results = {
        'tests_run': 0,
        'tests_passed': 0,
        'tests_failed': 0,
        'details': [],
    }

    def record_test(name: str, passed: bool, detail: str = ""):
        results['tests_run'] += 1
        if passed:
            results['tests_passed'] += 1
        else:
            results['tests_failed'] += 1
        results['details'].append({'test': name, 'passed': passed, 'detail': detail})

    # Test 1: Class instantiation
    try:
        provider = AMDWindowsProvider()
        record_test(
            "Instantiation",
            provider is not None and provider.name == "AMD Windows Provider",
            "Provider created successfully"
        )
    except Exception as e:
        record_test("Instantiation", False, str(e))

    # Test 2: Platform detection (should work on any OS)
    try:
        provider = AMDWindowsProvider()
        is_avail = provider.is_available
        record_test(
            "Platform detection",
            isinstance(is_avail, property) or callable(is_avail),
            f"is_available callable: {type(is_avail)}"
        )
    except Exception as e:
        record_test("Platform detection", False, str(e))

    # Test 3: Configuration parsing
    try:
        custom_config = {
            'wmi_timeout': 3.0,
            'collection_timeout': 1.5,
            'max_retries': 3,
        }
        provider = AMDWindowsProvider(config=custom_config)
        config_correct = (
            provider._wmi_timeout == 3.0 and
            provider._collection_timeout == 1.5 and
            provider._max_retries == 3
        )
        record_test("Configuration parsing", config_correct, f"Config applied correctly")
    except Exception as e:
        record_test("Configuration parsing", False, str(e))

    # Test 4: Status report generation
    try:
        provider = AMDWindowsProvider()
        status = provider.get_provider_status()
        has_required_keys = all(
            key in status
            for key in ['provider_name', 'active_sources', 'known_limitations']
        )
        record_test("Status report", has_required_keys, f"Status keys present")
    except Exception as e:
        record_test("Status report", False, str(e))

    # Summary
    logger.info(
        f"Self-test results: {results['tests_passed']}/{results['tests_run']} passed, "
        f"{results['tests_failed']} failed"
    )

    return results


# Execute self-tests when run directly
if __name__ == "__main__":
    print("=" * 70)
    print("ComfyUI-Feixue-UniversalMonitor - Windows AMD Provider Self-Test")
    print("=" * 70)
    print()

    # Configure logging for visibility
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    test_results = _run_self_tests()

    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)
    print(f"Total Tests: {test_results['tests_run']}")
    print(f"Passed:      {test_results['tests_passed']}")
    print(f"Failed:      {test_results['tests_failed']}")
    print()

    if test_results['details']:
        for detail in test_results['details']:
            status_icon = "✓" if detail['passed'] else "✗"
            print(f"  [{status_icon}] {detail['test']}: {detail['detail']}")

    print()
    print("Note: Full integration testing requires Windows + AMD GPU environment.")
    print("=" * 70)
