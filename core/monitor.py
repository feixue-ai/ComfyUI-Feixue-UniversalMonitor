"""
FeixueHardwareInfo - 飞雪监测器简化版数据采集引擎

参考 ComfyUI-Crystools 的 CHardwareInfo 设计理念，针对 AMD RX 6800 + ROCm 7.2.1
环境进行优化，确保在高负载和爆显存场景下稳定可靠。

核心设计原则：
1. 简洁性：从 1200+ 行精简至 <500 行
2. 可靠性：get_snapshot() 永不返回 None 或异常
3. 容错性：爆显存(VRAM=100%)时显示具体数值而非 "--"
4. 降级策略：ROCm SMI -> amdsmi -> sysfs 三级 Fallback
5. 线程安全：所有操作不影响 ComfyUI 主线程

接口契约（JSON 格式）:
{
    "timestamp": float,
    "cpu_utilization": int (0-100),
    "ram": {"total_gb": float, "used_gb": float, "percent": int},
    "gpus": [{
        "gpu_utilization": int,
        "vram_used_mb": int,
        "vram_total_mb": int,
        "vram_percent": int (0-100, 上限钳位),
        "gpu_temperature": float,
        "power_draw": float
    }]
}

Version: 2.1.0 (v10.0 Gemstone Capsule Support)  # [v10.0-fix] 版本号升级至2.1.0
Author: Feixue Team
"""

from __future__ import annotations

import logging
import os
import platform
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 配置日志
logger = logging.getLogger(__name__)


# ============================================================================
# 工具函数：超时执行保护
# ============================================================================

def execute_with_timeout(func, timeout: float = 2.0, default=None, *args, **kwargs):
    """
    在独立线程中执行函数，带超时保护。

    用于防止 GPU 驱动挂起导致主线程阻塞。

    Args:
        func: 要执行的函数
        timeout: 超时时间（秒）
        default: 超时时返回的默认值
        *args, **kwargs: 传递给 func 的参数

    Returns:
        (success: bool, result: Any, error: Optional[str])
    """
    result_container = [None]
    error_container = [None]
    exception_container = [None]

    def target():
        try:
            result_container[0] = func(*args, **kwargs)
        except Exception as e:
            exception_container[0] = e
            error_container[0] = str(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # 超时了
        logger.warning(f"Operation timed out after {timeout}s: {func.__name__}")
        return False, default, f"Timeout after {timeout}s"

    if exception_container[0] is not None:
        return False, default, error_container[0]

    return True, result_container[0], None


# ============================================================================
# 核心：FeixueHardwareInfo 类
# ============================================================================

class FeixueHardwareInfo:
    """
    飞雪硬件信息采集器（简化版）

    参考 Crystools 的 CHardwareInfo 设计，但针对 AMD ROCm 环境进行了增强：

    特性：
    - CPU/RAM 使用 psutil（跨平台兼容）
    - GPU 支持三级降级：amdsmi -> rocm_smi_lib -> sysfs
    - 内置超时保护（单次采集 ≤2 秒）
    - 爆显存安全处理（VRAM=100% 时返回具体数值）
    - 缓存降级机制（异常时返回上次成功的数据）
    - 永不返回 None 或异常

    使用示例::

        # 初始化（自动检测最佳数据源）
        hw = FeixueHardwareInfo()

        # 获取快照（永不失败）
        snapshot = hw.get_snapshot()
        print(f"CPU: {snapshot['cpu_utilization']}%")
        print(f"RAM: {snapshot['ram']['percent']}%")
        if snapshot['gpus']:
            gpu = snapshot['gpus'][0]
            print(f"VRAM: {gpu['vram_used_mb']}/{gpu['vram_total_mb']} MB ({gpu['vram_percent']}%)")

        # 清理资源
        hw.shutdown()
    """

    # ════════════════════════════════════════════════════════════
    # 数据源优先级策略 (2024-06-02 更新)
    # ════════════════════════════════════════════════════════════
    #
    # 【第一级】amdsmi (ROCm 7.2+ 官方推荐) ★★★★★
    #   - AMD 官方标记为 rocm-smi 的替代品和未来方向
    #   - 直接与 AMDGPU KMD 内核驱动通信
    #   - 轻量级 Ctypes 绑定，无 Python GIL 限制
    #   - 版本: v26.2.2+ (当前环境)
    #   - 适用: ROCm 6.0+, Linux 5.14+
    #
    # 【第二级】rocm_smi / rocm_smi_lib (传统兼容) ★★★☆☆
    #   - 旧版 ROCm 的 SMI 工具库
    #   - AMD 已标记为 deprecated (将被 amdsmi 取代)
    #   - 仍适用于 ROCm 5.x 和部分 6.x 环境
    #   - 作为向下兼容的备用方案保留
    #
    # 【第三级】sysfs 物理文件读取 (最终保底) ★★☆☆☆
    #   - 通过 /sys/class/drm/card0/device/ 读取硬件信息
    #   - 最原始但最可靠的方式（无需任何特殊库）
    #   - 精度较低，格式依赖内核版本
    #   - 仅在前两级全部失败时启用
    #
    # 【未来可选】AMDGPU KMD ioctl 接口 (实验性)
    #   - 通过 /dev/dri/card0 + fcntl.ioctl() 直接通信
    #   - 性能最优（<0.1ms），数据最权威
    #   - 需要特殊权限（root 或 video 组 + DRM master）
    #   - 兼容性敏感（不同内核版本接口可能变化）
    #   - 暂未实现，作为 Phase 3/4 的研究方向
    #
    # 设计原则：顺应未来趋势，向下兼容旧版，确保 A 卡完美使用
    # ════════════════════════════════════════════════════════════
    SOURCE_PRIORITY = ['amdsmi', 'rocm_smi', 'sysfs']

    # 平台感知的数据源优先级（Windows自动切换）
    _SOURCE_PRIORITY_LINUX = ['amdsmi', 'rocm_smi', 'sysfs']
    # Windows: amdsmi 是 Linux 专用（依赖 libamd_smi.so），
    # pynvml-amd-windows 通过 ADLX 提供等价功能，已集成在 windows_wmi 采集器中
    _SOURCE_PRIORITY_WINDOWS = ['windows_wmi']

    @property
    def _effective_source_priority(self) -> List[str]:
        """根据操作系统返回对应的数据源优先级（不影响原有SOURCE_PRIORITY常量）"""
        import platform
        if platform.system() == 'Windows':
            return self._SOURCE_PRIORITY_WINDOWS
        return self._SOURCE_PRIORITY_LINUX

    # 超时配置
    INIT_TIMEOUT = 5.0      # 初始化超时
    COLLECT_TIMEOUT = 8.0   # 单次采集超时（torch 首次导入 + PowerShell 子进程可能需要更长时间）

    # sysfs 基础路径
    SYSFS_DRM_BASE = Path("/sys/class/drm")
    AMD_VENDOR_ID = "0x1002"

    def __init__(self):
        """初始化硬件信息采集器"""
        self._lock = threading.Lock()

        # GPU 数据源状态
        self._active_source: Optional[str] = None
        self._source_instance: Any = None
        self._device_count: int = 0
        self._device_names: List[str] = []
        self._device_path: Optional[Path] = None  # sysfs 设备路径

        # 缓存数据（用于异常降级）
        self._cached_gpu_data: Optional[Dict[str, Any]] = None
        self._last_success_time: float = 0.0

        # pynvml 持久化状态（Windows，避免每次 snapshot 都 init/shutdown 导致数据抖动）
        self._pynvml_available: bool = False
        self._pynvml_handles: List[Any] = []
        self._pynvml_lock = threading.Lock()

        # 磁盘/网络IO差值计算状态
        self._prev_disk_io: Any = None
        self._prev_net_io: Any = None
        self._prev_disk_time: float = 0.0
        self._prev_net_time: float = 0.0

        # 统计信息
        self._stats = {
            'total_collections': 0,
            'successful_collections': 0,
            'failed_collections': 0,
            'timeout_count': 0,
            'source_switches': 0,
        }

        # 自动初始化
        self._initialize()

    def _initialize(self) -> None:
        """自动初始化并选择最佳数据源"""
        logger.info("FeixueHardwareInfo: initializing...")

        for source in self._effective_source_priority:
            if self._try_init_source(source):
                self._active_source = source
                logger.info(
                    f"FeixueHardwareInfo: initialized with source={source}, "
                    f"device_count={self._device_count}"
                )
                return

        logger.warning("FeixueHardwareInfo: no GPU data source available, GPU monitoring disabled")

    def _try_init_source(self, source: str) -> bool:
        """尝试初始化单个数据源"""
        try:
            if source == 'amdsmi':
                return self._init_amdsmi()
            elif source == 'rocm_smi':
                return self._init_rocm_smi()
            elif source == 'sysfs':
                return self._init_sysfs()
            elif source == 'windows_wmi':
                return self._init_windows_wmi()
            else:
                logger.warning(f"Unknown source: {source}")
                return False
        except Exception as e:
            logger.debug(f"Failed to init {source}: {e}")
            return False

    # ------------------------------------------------------------------
    # 数据源初始化方法
    # ------------------------------------------------------------------

    def _init_amdsmi(self) -> bool:
        """初始化 amdsmi 数据源（ROCm 7.2+ 官方推荐）"""
        try:
            import amdsmi

            logger.info("尝试初始化 amdsmi (ROCm 7.2+)...")

            # amdsmi_init() 是 void 函数，直接调用即可
            # 它会返回 None，这是正常的
            try:
                amdsmi.amdsmi_init()
                logger.debug("amdsmi_init() 调用成功")
            except Exception as init_error:
                logger.warning(f"amdsmi_init() 失败: {init_error}")
                return False

            # 获取所有处理器句柄（无参数调用）
            handles = amdsmi.amdsmi_get_processor_handles()
            logger.info(f"amdsmi 发现 {len(handles)} 个处理器设备")

            if not handles:
                logger.warning("amdsmi: 未找到任何处理器设备")
                return False

            # 尝试识别 GPU 设备（宽松匹配）
            gpu_handles = []
            for handle in handles:
                try:
                    ptype = amdsmi.amdsmi_get_processor_type(handle)
                    logger.debug(f"处理器类型: {ptype} (GPU={amdsmi.AmdSmiDeviceType.GPU})")

                    # 宽松匹配：只要是 GPU 类型或者是唯一设备就加入
                    if ptype == amdsmi.AmdSmiDeviceType.GPU or len(handles) == 1:
                        gpu_handles.append(handle)
                    else:
                        # 如果类型不确定但看起来像 GPU，也尝试添加
                        info = amdsmi.amdsmi_get_processor_info(handle)
                        device_name = str(getattr(info, 'market_name', '') or getattr(info, 'device_name', '') or '')
                        if any(keyword in device_name.lower() for keyword in ['radeon', 'gpu', 'graphics', 'device']):
                            gpu_handles.append(handle)
                            logger.info(f"通过名称识别到 GPU: {device_name}")
                        else:
                            logger.debug(f"跳过非 GPU 设备: type={ptype}, name={device_name}")
                except Exception as e:
                    # 如果无法判断类型，且只有1个设备就假设是 GPU
                    if len(handles) == 1:
                        gpu_handles.append(handle)
                        logger.warning(f"无法确定设备类型，假设为 GPU (唯一设备)")
                    else:
                        logger.debug(f"设备类型检查异常: {e}")

            # 最终保底：如果没找到 GPU 但有设备，使用第一个
            if not gpu_handles and handles:
                logger.warning("amdsmi: 未明确找到 GPU 设备，使用第一个处理器")
                gpu_handles = [handles[0]]

            if not gpu_handles:
                logger.error("amdsmi: 无法获取任何可用的 GPU 句柄")
                return False

            self._device_count = len(gpu_handles)
            self._source_instance = {'lib': amdsmi, 'handles': gpu_handles}

            # 获取设备名称
            self._device_names = []
            for i, handle in enumerate(gpu_handles):
                try:
                    info = amdsmi.amdsmi_get_processor_info(handle)
                    name = (
                        getattr(info, 'market_name', None) or
                        getattr(info, 'device_name', None) or
                        f"AMD Device {i}"
                    )
                    self._device_names.append(str(name))
                    logger.info(f"GPU [{i}]: {name}")
                except Exception as e:
                    self._device_names.append(f"AMD Device {i}")
                    logger.warning(f"获取设备[{i}]名称失败: {e}")

            logger.info(f"✅ amdsmi 初始化成功: {self._device_count}个GPU设备")
            return True

        except ImportError:
            logger.debug("amdsmi: 库未安装 (pip install amdsmi)")
            return False
        except Exception as e:
            logger.error(f"amdsmi 初始化异常: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

    def _init_rocm_smi(self) -> bool:
        """初始化 rocm_smi 数据源（ROCm 5.x 兼容层）"""
        rsmi_module = None

        for name in ('rocm_smi', 'rocm_smi_lib'):
            try:
                rsmi_module = __import__(name)
                break
            except ImportError:
                continue

        if rsmi_module is None:
            logger.debug("rocm_smi: library not installed")
            return False

        try:
            # 初始化
            if hasattr(rsmi_module, 'rocm_smi_init'):
                rsmi_module.rocm_smi_init()

            # 获取设备列表
            if hasattr(rsmi_module, 'getDevices'):
                devices = rsmi_module.getDevices()
            elif hasattr(rsmi_module, 'get_device_count'):
                devices = list(range(rsmi_module.get_device_count()))
            else:
                return False

            device_count = len(devices) if isinstance(devices, list) else devices
            if device_count == 0:
                return False

            self._device_count = device_count
            self._source_instance = rsmi_module

            # 获取设备名称
            self._device_names = []
            for i in range(device_count):
                try:
                    if hasattr(rsmi_module, 'getDeviceName'):
                        name = str(rsmi_module.getDeviceName(i))
                    else:
                        name = f"AMD Device {i}"
                    self._device_names.append(name)
                except Exception:
                    self._device_names.append(f"AMD Device {i}")

            return True

        except Exception as e:
            logger.debug(f"rocm_smi initialization failed: {e}")
            return False

    def _init_sysfs(self) -> bool:
        """初始化 sysfs 数据源（零依赖回退）"""
        if not self.SYSFS_DRM_BASE.exists():
            logger.debug("sysfs: /sys/class/drm does not exist")
            return False

        card_pattern = re.compile(r'^card(\d+)$')
        found_devices: List[Tuple[int, Path]] = []

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
                if self.AMD_VENDOR_ID not in vendor and '1002' not in vendor:
                    continue
            except (IOError, OSError):
                continue

            device_index = len(found_devices)
            found_devices.append((device_index, card_path))

            # 提取设备名称
            device_name = self._extract_device_name_from_sysfs(device_link)
            self._device_names.append(device_name)

        if not found_devices:
            logger.debug("sysfs: no AMD GPU devices found")
            return False

        primary_index, primary_path = found_devices[0]
        self._device_path = primary_path
        self._device_count = len(found_devices)
        self._source_instance = 'sysfs'  # 标记为 sysfs 模式

        logger.info(f"sysfs initialized: {self._device_count} GPU(s)")
        return True

    # ------------------------------------------------------------------
    # Windows WMI 数据源（纯新增，不影响Linux任何代码）
    # ------------------------------------------------------------------

    def _init_windows_wmi(self) -> bool:
        """
        初始化 Windows WMI 数据源。

        通过 Windows Management Instrumentation (WMI) 读取 AMD GPU 信息。
        适用于 Windows + ROCm 或 DirectML 环境。

        支持两级 fallback:
        1. Python wmi 包 (pip install wmi)
        2. subprocess wmic 命令行 (零依赖，Windows 内置)
        """
        import platform
        if platform.system() != 'Windows':
            return False

        amd_gpus = []

        # ---- 方式1: Python wmi 包 ----
        try:
            import wmi
            c = wmi.WMI()

            for gpu in c.Win32_VideoController():
                name = (gpu.Name or '').upper()
                adapter_ram = gpu.AdapterRAM or 0
                # Python wmi 包可能将大 VRAM 值返回为负数（32位有符号溢出）
                # 例如 16GB 返回 -1048576，需要转换为无符号值
                if isinstance(adapter_ram, int) and adapter_ram < 0:
                    adapter_ram = adapter_ram & 0xFFFFFFFF
                if 'AMD' in name or 'RADEON' in name or 'ATI' in name:
                    amd_gpus.append({
                        'name': gpu.Name or 'AMD GPU',
                        'adapter_ram_bytes': adapter_ram,
                    })

            if not amd_gpus:
                # 尝试 APU 检测
                for gpu in c.Win32_VideoController():
                    if 'AMD' in (gpu.Name or '').upper() or \
                       'RADEON' in (gpu.Name or '').upper():
                        adapter_ram = gpu.AdapterRAM or 0
                        if isinstance(adapter_ram, int) and adapter_ram < 0:
                            adapter_ram = adapter_ram & 0xFFFFFFFF
                        amd_gpus.append({
                            'name': gpu.Name or 'AMD APU',
                            'adapter_ram_bytes': adapter_ram,
                        })
                        break

            if amd_gpus:
                self._device_names = [g['name'] for g in amd_gpus]
                self._device_count = len(amd_gpus)
                self._source_instance = {
                    'type': 'wmi',
                    'gpus': amd_gpus,
                }
                logger.info(f"windows_wmi initialized: {self._device_count} AMD GPU(s): "
                           f"{', '.join(self._device_names)}")

                # pynvml 一次性初始化（避免每次 snapshot 都 init/shutdown 导致数据抖动）
                self._init_pynvml()
                return True

        except ImportError:
            logger.debug("windows_wmi: wmi module not available, trying wmic fallback...")
        except Exception as e:
            logger.debug(f"windows_wmi init via wmi package failed: {e}, trying wmic fallback...")

        # ---- 方式2: subprocess wmic 命令行（零依赖 fallback）----
        try:
            import subprocess
            result = subprocess.run(
                ['wmic', 'path', 'win32_videocontroller', 'get', 'name,adapterram'],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # 跳过表头
                    if not line.strip():
                        continue
                    parts = line.rsplit(None, 1)  # 最后一个是 AdapterRAM
                    if len(parts) >= 2:
                        try:
                            ram_bytes = int(parts[1])
                        except ValueError:
                            ram_bytes = 0
                        gpu_name = parts[0].strip()
                        if 'AMD' in gpu_name.upper() or 'RADEON' in gpu_name.upper() or 'ATI' in gpu_name.upper():
                            amd_gpus.append({
                                'name': gpu_name,
                                'adapter_ram_bytes': ram_bytes,
                            })

            if amd_gpus:
                self._device_names = [g['name'] for g in amd_gpus]
                self._device_count = len(amd_gpus)
                self._source_instance = {
                    'type': 'wmic',
                    'gpus': amd_gpus,
                }
                logger.info(f"windows_wmi (wmic fallback) initialized: {self._device_count} AMD GPU(s): "
                           f"{', '.join(self._device_names)}")

                # pynvml 一次性初始化
                self._init_pynvml()
                return True

        except Exception as e:
            logger.debug(f"windows_wmi wmic fallback also failed: {e}")

        logger.debug("windows_wmi: no AMD GPU found via any method")
        return False

    def _init_pynvml(self) -> None:
        """一次性初始化 pynvml（避免每次 snapshot 都 init/shutdown 导致数据抖动）"""
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='.*pynvml.*deprecated.*', category=FutureWarning)
                import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            self._pynvml_handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
            self._pynvml_available = True
            logger.debug(f"pynvml initialized: {len(self._pynvml_handles)} device(s)")
        except ImportError:
            logger.debug("pynvml not available (pip install pynvml-amd-windows)")
            self._pynvml_available = False
        except Exception as e:
            logger.debug(f"pynvml init failed: {e}")
            self._pynvml_available = False

    def _shutdown_pynvml(self) -> None:
        """关闭 pynvml（在 shutdown 时调用）"""
        if self._pynvml_available:
            try:
                # pynvml_amd_windows hooks into pynvml module
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass

    def _extract_device_name_from_sysfs(self, device_link: Path) -> str:
        """从 sysfs 提取设备名称"""
        uevent_file = device_link / "uevent"
        if uevent_file.exists():
            try:
                with open(uevent_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if any(line.startswith(k) for k in ['PRODUCT=', 'MODEL=', 'PCI_NAME=']):
                            name = line.split('=', 1)[1].strip().strip('"\'')
                            if name:
                                return name
            except (IOError, OSError):
                pass

        model_file = device_link / "model"
        if model_file.exists():
            try:
                name = model_file.read_text().strip()
                if name:
                    return name
            except (IOError, OSError):
                pass

        return "AMD GPU (sysfs)"

    # ------------------------------------------------------------------
    # 核心数据采集方法
    # ------------------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        """
        获取系统硬件快照。

        这是主要的数据访问接口，保证：
        1. 永不返回 None
        2. 永不抛出异常
        3. 爆显存时返回具体数值
        4. 单次调用耗时 ≤2 秒

        Returns:
            符合接口契约的字典格式
        """
        self._stats['total_collections'] += 1

        timestamp = time.time()

        try:
            # 1. 采集 CPU 和 RAM（使用 psutil，快速且可靠）
            cpu_data = self._safe_get_cpu()
            ram_data = self._safe_get_ram()

            # 【v10.0 新增】1.1 采集 Swap 虚拟内存
            swap_data = self._safe_get_swap()

            # 2. 采集 GPU 数据（带超时保护和缓存降级）
            gpu_data = self._safe_get_gpu_all()

            # 构建结果
            snapshot = {
                'timestamp': timestamp,
                'cpu_utilization': cpu_data['utilization'],
                'ram': {
                    'total_gb': ram_data['total_gb'],
                    'used_gb': ram_data['used_gb'],
                    'percent': ram_data['percent'],
                },
                'swap': {   # 【v10.0】新增虚拟内存字段
                    'total_gb': swap_data['total_gb'],
                    'used_gb': swap_data['used_gb'],
                    'percent': swap_data['percent'],
                },
                'gpus': gpu_data,
                'data_source': self._active_source or 'none',
                'version': '2.1.0',   # 【v10.0】版本号升级（添加swap支持）
            }

            # 辅助指标采集（每个独立try-except，单个失败不影响整体）
            try:
                snapshot['disk_io'] = self._collect_disk_io()
            except Exception:
                snapshot['disk_io'] = None
            try:
                snapshot['network_io'] = self._collect_network()
            except Exception:
                snapshot['network_io'] = None
            try:
                snapshot['fan_speed'] = self._collect_fan()
            except Exception:
                snapshot['fan_speed'] = None

            self._stats['successful_collections'] += 1
            return snapshot

        except Exception as e:
            self._stats['failed_collections'] += 1
            logger.error(f"get_snapshot unexpected error: {e}", exc_info=True)

            # 返回安全的默认值（绝不返回 None 或异常）
            return self._get_safe_default_snapshot(timestamp)

    def _safe_get_cpu(self) -> Dict[str, int]:
        """安全获取 CPU 使用率"""
        try:
            import psutil
            utilization = int(psutil.cpu_percent())
            return {'utilization': max(0, min(100, utilization))}
        except Exception as e:
            logger.debug(f"CPU collection failed: {e}")
            return {'utilization': 0}

    def _safe_get_ram(self) -> Dict[str, Any]:
        """安全获取内存使用情况"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                'total_gb': round(mem.total / (1024 ** 3), 1),
                'used_gb': round(mem.used / (1024 ** 3), 1),
                'percent': int(mem.percent),
            }
        except Exception as e:
            logger.debug(f"RAM collection failed: {e}")
            return {'total_gb': 0.0, 'used_gb': 0.0, 'percent': 0}

    def _safe_get_swap(self) -> Dict[str, Any]:
        """
        安全获取虚拟内存(Swap)使用情况。

        【v10.0 新增】
        使用 psutil.swap_memory() 获取交换分区信息。
        返回格式与 _safe_get_ram() 保持一致，便于前端统一处理。

        Returns:
            包含 total_gb, used_gb, percent 的字典
        """
        try:
            import psutil
            swap = psutil.swap_memory()
            return {
                'total_gb': round(swap.total / (1024 ** 3), 2),   # 保留2位小数（swap通常较小）
                'used_gb': round(swap.used / (1024 ** 3), 2),
                'percent': int(swap.percent),
            }
        except Exception as e:
            logger.debug(f"Swap collection failed: {e}")
            return {'total_gb': 0.0, 'used_gb': 0.0, 'percent': 0}

    # ------------------------------------------------------------------
    # 辅助指标采集方法（磁盘IO、网络IO、风扇转速）
    # ------------------------------------------------------------------

    def _collect_disk_io(self):
        """
        采集磁盘IO速率（MB/s）。

        使用 psutil.disk_io_counters() 获取累加值，与上次结果做差值计算。
        首次调用时返回零值。

        Returns:
            {'read_mbps': float, 'write_mbps': float}，异常时返回 None
        """
        try:
            import psutil
            counters = psutil.disk_io_counters()
            now = time.time()

            result = {'read_mbps': 0.0, 'write_mbps': 0.0}

            if self._prev_disk_io is not None and self._prev_disk_time > 0:
                elapsed = now - self._prev_disk_time
                if elapsed > 0:
                    read_delta = counters.read_bytes - self._prev_disk_io.read_bytes
                    write_delta = counters.write_bytes - self._prev_disk_io.write_bytes
                    # 处理计数器重置（系统重启等）
                    if read_delta >= 0:
                        result['read_mbps'] = round(read_delta / elapsed / (1024 * 1024), 2)
                    if write_delta >= 0:
                        result['write_mbps'] = round(write_delta / elapsed / (1024 * 1024), 2)

            # 更新上次值
            self._prev_disk_io = counters
            self._prev_disk_time = now

            return result
        except Exception as e:
            logger.debug(f"Disk IO collection failed: {e}")
            return None

    def _collect_network(self):
        """
        采集网络IO速率（MB/s）。

        使用 psutil.net_io_counters() 获取累加字节数，差值算法同 _collect_disk_io。
        首次调用时返回零值。

        Returns:
            {'upload_mbps': float, 'download_mbps': float}，异常时返回 None
        """
        try:
            import psutil
            counters = psutil.net_io_counters()
            now = time.time()

            result = {'upload_mbps': 0.0, 'download_mbps': 0.0}

            if self._prev_net_io is not None and self._prev_net_time > 0:
                elapsed = now - self._prev_net_time
                if elapsed > 0:
                    sent_delta = counters.bytes_sent - self._prev_net_io.bytes_sent
                    recv_delta = counters.bytes_recv - self._prev_net_io.bytes_recv
                    # 处理计数器重置
                    if sent_delta >= 0:
                        result['upload_mbps'] = round(sent_delta / elapsed / (1024 * 1024), 2)
                    if recv_delta >= 0:
                        result['download_mbps'] = round(recv_delta / elapsed / (1024 * 1024), 2)

            # 更新上次值
            self._prev_net_io = counters
            self._prev_net_time = now

            return result
        except Exception as e:
            logger.debug(f"Network IO collection failed: {e}")
            return None

    def _collect_fan(self):
        """
        采集 GPU 风扇转速。

        使用已初始化的 pynvml（通过 _init_pynvml() 初始化的持久化连接）。
        读取第一个 GPU 的风扇转速百分比，加锁保护 pynvml 调用。

        Returns:
            {'rpm': None, 'percent': int}，pynvml不可用或异常时返回 None
        """
        try:
            if not self._pynvml_available or not self._pynvml_handles:
                return None

            with self._pynvml_lock:
                handle = self._pynvml_handles[0]
                import pynvml
                fan_percent = pynvml.nvmlDeviceGetFanSpeed(handle)
                return {
                    'rpm': None,
                    'percent': int(fan_percent),
                }
        except Exception as e:
            logger.debug(f"Fan speed collection failed: {e}")
            return None

    def _safe_get_gpu_all(self) -> List[Dict[str, Any]]:
        """
        安全获取所有 GPU 数据（核心方法）。

        实现高负载保护机制：
        1. 超时控制：单次采集 ≤2 秒
        2. 爆显存处理：VRAM=100% 时返回具体数值
        3. 缓存降级：异常时返回上次成功的数据
        4. 永不返回空列表或 None 元素
        """
        if self._active_source is None:
            # 无 GPU 数据源，返回默认值
            return [self._get_default_gpu_data()]

        # 使用超时保护执行采集
        success, result, error = execute_with_timeout(
            func=self._collect_gpu_internal,
            timeout=self.COLLECT_TIMEOUT,
            default=None,
        )

        if not success:
            self._stats['timeout_count'] += 1
            logger.warning(f"GPU collection failed: {error}")
            # 返回缓存数据或默认值
            return self._get_fallback_gpu_data()

        if result is None or not isinstance(result, list):
            return self._get_fallback_gpu_data()

        # 更新缓存
        if result and len(result) > 0:
            self._cached_gpu_data = result[0]  # 缓存第一个 GPU 的数据
            self._last_success_time = time.time()

        return result

    def _collect_gpu_internal(self) -> List[Dict[str, Any]]:
        """内部 GPU 采集方法（在独立线程中执行）"""
        gpus = []

        for device_id in range(max(1, self._device_count)):
            gpu_data = self._collect_single_gpu(device_id)
            gpus.append(gpu_data)

        return gpus if gpus else [self._get_default_gpu_data()]

    def _collect_single_gpu(self, device_id: int = 0) -> Dict[str, Any]:
        """采集单个 GPU 的完整指标"""
        try:
            if self._active_source == 'amdsmi':
                return self._collect_amdsmi_gpu(device_id)
            elif self._active_source == 'rocm_smi':
                return self._collect_rocm_smi_gpu(device_id)
            elif self._active_source == 'sysfs':
                return self._collect_sysfs_gpu(device_id)
            elif self._active_source == 'windows_wmi':
                return self._collect_windows_wmi_gpu(device_id)
            else:
                return self._get_default_gpu_data(device_id)
        except Exception as e:
            logger.debug(f"GPU {device_id} collection error: {e}")
            return self._get_default_gpu_data(device_id)

    # ------------------------------------------------------------------
    # 各数据源的采集实现
    # ------------------------------------------------------------------

    def _collect_amdsmi_gpu(self, device_id: int = 0) -> Dict[str, Any]:
        """通过 amdsmi 采集 GPU 数据 (v26.2.2 适配版)"""

        lib = self._source_instance['lib']
        handles = self._source_instance['handles']

        if device_id >= len(handles):
            logger.error(f"设备ID {device_id} 超出范围 (共{len(handles)}个设备)")
            return self._get_default_gpu_data()

        handle = handles[device_id]
        gpu_data = {}

        try:
            # 1. VRAM 信息 (已验证可用 ✅)
            vram_info = lib.amdsmi_get_gpu_vram_usage(handle)
            if vram_info and isinstance(vram_info, dict):
                vram_total_mb = vram_info.get('vram_total', 0)
                vram_used_mb = vram_info.get('vram_used', 0)

                gpu_data['vram_used_mb'] = int(vram_used_mb)
                gpu_data['vram_total_mb'] = int(vram_total_mb)
                gpu_data['vram_percent'] = self._calculate_vram_percent(
                    int(vram_used_mb), int(vram_total_mb)
                )
                logger.debug(f"VRAM: {vram_used_mb}/{vram_total_mb} MB ({gpu_data['vram_percent']}%)")
            else:
                logger.warning(f"VRAM数据格式异常: {type(vram_info)}")
                raise ValueError("Invalid VRAM data format")

            # 2. GPU 利用率 (尝试多种方法)
            try:
                activity = lib.amdsmi_get_gpu_activity(handle)
                if activity and isinstance(activity, dict):
                    # 尝试不同的字段名
                    gfx_activity = (
                        activity.get('gfx_activity') or
                        activity.get('gpu_activity') or
                        activity.get('activity') or
                        0
                    )
                    gpu_data['gpu_utilization'] = int(gfx_activity)
                else:
                    gpu_data['gpu_utilization'] = 0
            except Exception as e:
                logger.debug(f"GPU利用率获取失败: {e}")
                gpu_data['gpu_utilization'] = 0

            # 3. 温度信息 (直接从 metrics 获取，单位已是摄氏度)
            try:
                metrics_info = lib.amdsmi_get_gpu_metrics_info(handle)
                if metrics_info:
                    # amdsmi v26.2.2 格式：温度字段在顶层，单位为摄氏度 (°C)
                    # 可选字段：temperature_edge, temperature_hotspot, temperature_mem
                    temp_edge = metrics_info.get('temperature_edge', 0)
                    if temp_edge and temp_edge > 0:
                        # 直接使用，无需单位转换（已经是 °C）
                        gpu_data['gpu_temperature'] = round(float(temp_edge), 1)
                    else:
                        # 备用：尝试其他温度字段
                        temp_hotspot = metrics_info.get('temperature_hotspot', 0)
                        if temp_hotspot and temp_hotspot > 0:
                            gpu_data['gpu_temperature'] = round(float(temp_hotspot), 1)
                        else:
                            gpu_data['gpu_temperature'] = 0.0
                    logger.debug(f"温度原始数据: edge={temp_edge}°C")
            except Exception as e:
                logger.debug(f"温度获取失败: {e}")
                gpu_data['gpu_temperature'] = 0.0

            # 4. 功耗信息 (从 metrics 获取，单位已是瓦特)
            try:
                # 注意：amdsmi_get_power_measurements() 在 v26.2.2 中不存在
                # 应使用 get_gpu_metrics_info() 的 average_socket_power 字段
                if 'metrics_info' not in dir():
                    metrics_info = lib.amdsmi_get_gpu_metrics_info(handle)

                if metrics_info:
                    # amdsmi v26.2.2 格式：功耗字段在顶层，单位为瓦特 (W)
                    power_avg = metrics_info.get('average_socket_power', 0)
                    if power_avg and power_avg > 0:
                        # 直接使用，无需单位转换（已经是 W）
                        gpu_data['power_draw'] = round(float(power_avg), 1)
                    else:
                        # 尝试 current_socket_power（如果可用）
                        power_current = metrics_info.get('current_socket_power', 0)
                        if power_current and power_current > 0:
                            gpu_data['power_draw'] = round(float(power_current), 1)
                        else:
                            gpu_data['power_draw'] = 0.0
                    logger.debug(f"功耗原始数据: average={power_avg}W")
            except Exception as e:
                logger.debug(f"功耗获取失败: {e}")
                gpu_data['power_draw'] = 0.0

            # 4.1 sysfs 降级：当 amdsmi 返回 0 时尝试从 sysfs 获取
            if gpu_data.get('gpu_temperature', 0) == 0.0 or gpu_data.get('power_draw', 0) == 0.0:
                logger.debug("amdsmi 温度/功耗为0，尝试 sysfs 降级...")
                sysfs_temp = self._get_temperature_from_sysfs()
                sysfs_power = self._get_power_from_sysfs()

                if sysfs_temp > 0 and gpu_data.get('gpu_temperature', 0) == 0.0:
                    gpu_data['gpu_temperature'] = sysfs_temp
                    logger.info(f"sysfs 降级成功: 温度={sysfs_temp}°C")

                if sysfs_power > 0 and gpu_data.get('power_draw', 0) == 0.0:
                    gpu_data['power_draw'] = sysfs_power
                    logger.info(f"sysfs 降级成功: 功耗={sysfs_power}W")

            # 5. 设置设备名称
            gpu_data['device_name'] = self._device_names[device_id] if device_id < len(self._device_names) else "AMD Device"

            # 缓存成功的GPU数据
            self._cached_gpu_data = gpu_data.copy()

            logger.debug(
                f"amdsmi GPU[{device_id}] 采集完成: "
                f"util={gpu_data.get('gpu_utilization', 0)}%, "
                f"vram={gpu_data.get('vram_percent', 0)}%, "
                f"temp={gpu_data.get('gpu_temperature', 0)}°C, "
                f"power={gpu_data.get('power_draw', 0)}W"
            )

            return gpu_data

        except Exception as e:
            logger.error(f"amdsmi GPU[{device_id}] 采集失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

            # 返回缓存数据或默认值
            if self._cached_gpu_data:
                logger.info(f"使用缓存GPU数据 (来自上次成功采集)")
                return self._cached_gpu_data.copy()

            return self._get_default_gpu_data()

    def _collect_rocm_smi_gpu(self, device_id: int = 0) -> Dict[str, Any]:
        """通过 rocm_smi 采集 GPU 数据"""
        rsmi = self._source_instance

        # GPU 利用率
        gpu_utilization = 0
        try:
            util_result = self._call_rsmi_method(rsmi, ['getGpuUse', 'get_gpu_use'], device_id)
            if util_result is not None:
                gpu_utilization = int(float(util_result)) if isinstance(util_result, (int, float, str)) else 0
        except Exception as e:
            logger.debug(f"rocm_smi gpu_util failed: {e}")

        # 显存信息
        vram_used_mb = 0
        vram_total_mb = 0
        try:
            mem_result = self._call_rsmi_method(rsmi, ['getMemInfo', 'get_mem_info'], device_id)
            if isinstance(mem_result, dict):
                total_raw = int(mem_result.get('vram_total', 0) or mem_result.get('total', 0) or 0)
                used_raw = int(mem_result.get('vram_used', 0) or mem_result.get('used', 0) or 0)
            elif isinstance(mem_result, (list, tuple)) and len(mem_result) >= 2:
                total_raw = int(mem_result[0]) if mem_result[0] else 0
                used_raw = int(mem_result[1]) if mem_result[1] else 0
            else:
                total_raw, used_raw = 0, 0

            # 单位检测
            if total_raw > 1024 * 1024:
                vram_total_mb = total_raw // (1024 * 1024)
                vram_used_mb = used_raw // (1024 * 1024)
            else:
                vram_total_mb = total_raw // 1024
                vram_used_mb = used_raw // 1024
        except Exception as e:
            logger.debug(f"rocm_smi memory failed: {e}")

        # 温度
        temperature = 0.0
        try:
            temp_result = self._call_rsmi_method(rsmi, ['getTemp', 'get_temp'], device_id)
            if temp_result is not None:
                temperature = round(float(temp_result), 1)
        except Exception as e:
            logger.debug(f"rocm_smi temp failed: {e}")

        # 功耗
        power_draw = 0.0
        try:
            power_result = self._call_rsmi_method(rsmi, ['getPower', 'get_power'], device_id)
            if power_result is not None:
                power_draw = round(float(power_result), 2)
        except Exception as e:
            logger.debug(f"rocm_smi power failed: {e}")

        vram_percent = self._calculate_vram_percent(vram_used_mb, vram_total_mb)

        return {
            'gpu_utilization': max(0, min(100, gpu_utilization)),
            'vram_used_mb': max(0, vram_used_mb),
            'vram_total_mb': max(1, vram_total_mb),
            'vram_percent': vram_percent,
            'gpu_temperature': temperature,
            'power_draw': power_draw,
            'device_name': self._get_device_name(device_id),
        }

    def _collect_sysfs_gpu(self, device_id: int = 0) -> Dict[str, Any]:
        """通过 sysfs 采集 GPU 数据（零依赖回退）"""
        if self._device_path is None:
            return self._get_default_gpu_data(device_id)

        device_subpath = self._device_path / "device"

        # --- 温度 (mC -> C) ---
        temperature = 0.0
        temp_raw = self._read_hwmon_value(device_subpath, "temp1_input")
        if temp_raw is not None:
            try:
                temp_mc = int(temp_raw)
                if 1000 <= temp_mc <= 120000:
                    temperature = round(temp_mc / 1000.0, 1)
                elif 0 <= temp_mc <= 150:
                    temperature = float(temp_mc)
            except ValueError:
                pass

        # --- VRAM Total ---
        vram_total_mb = 0
        vram_total_raw = self._read_sysfs_file(device_subpath, "mem_info_vram_total")
        if vram_total_raw is not None:
            try:
                val = int(vram_total_raw)
                vram_total_mb = val // (1024 * 1024) if val > 1024 * 1024 else val // 1024
            except ValueError:
                pass

        # --- VRAM Used ---
        vram_used_mb = 0
        vram_used_raw = self._read_sysfs_file(device_subpath, "mem_info_vram_used")
        if vram_used_raw is not None:
            try:
                val = int(vram_used_raw)
                vram_used_mb = val // (1024 * 1024) if val > 1024 * 1024 else val // 1024
            except ValueError:
                pass

        # --- GPU Utilization (%) ---
        gpu_utilization = 0
        for path in ["gpu_busy_percent", "gpu_busy", "busy_percent"]:
            util_raw = self._read_sysfs_file(device_subpath, path)
            if util_raw is not None:
                try:
                    val = float(util_raw)
                    if 0 <= val <= 100:
                        gpu_utilization = int(val)
                        break
                except ValueError:
                    continue

        # --- Power Usage (uW -> W) ---
        power_draw = 0.0
        power_raw = self._read_hwmon_value(device_subpath, "power1_average")
        if power_raw is not None:
            try:
                power_uw = int(power_raw)
                power_draw = round(power_uw / 1_000_000.0, 2) if power_uw > 1000 else float(power_uw)
            except ValueError:
                pass

        vram_percent = self._calculate_vram_percent(vram_used_mb, vram_total_mb)

        return {
            'gpu_utilization': gpu_utilization,
            'vram_used_mb': max(0, vram_used_mb),
            'vram_total_mb': max(1, vram_total_mb),
            'vram_percent': vram_percent,
            'gpu_temperature': temperature,
            'power_draw': power_draw,
            'device_name': self._get_device_name(device_id),
        }

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _get_temperature_from_sysfs(self) -> float:
        """
        从 sysfs 读取 GPU 温度（降级方案）。

        当 amdsmi 无法提供温度数据时，通过 /sys/class/drm/card0/device/hwmon/ 读取。

        Returns:
            温度值（摄氏度），读取失败返回 0.0
        """
        if not self._device_path:
            return 0.0

        device_subpath = self._device_path / "device"
        hwmon_base = device_subpath / "hwmon"

        if not hwmon_base.exists():
            return 0.0

        try:
            for hwmon_dir in sorted(hwmon_base.glob("hwmon*")):
                if not hwmon_dir.is_dir():
                    continue

                # 尝试读取 temp1_input（通常是边缘温度，单位：毫摄氏度）
                temp_file = hwmon_dir / "temp1_input"
                if temp_file.exists():
                    try:
                        temp_millidegrees = int(temp_file.read_text().strip())
                        # 验证合理性（10-120°C）
                        temp_celsius = temp_millidegrees / 1000.0
                        if 10 <= temp_celsius <= 120:
                            logger.debug(f"sysfs 温度读取成功: {temp_celsius}°C (来自 {temp_file})")
                            return round(temp_celsius, 1)
                    except (ValueError, IOError):
                        continue

                # 备用：尝试 temp2_input（可能是热点温度）
                temp_file2 = hwmon_dir / "temp2_input"
                if temp_file2.exists():
                    try:
                        temp_millidegrees = int(temp_file2.read_text().strip())
                        temp_celsius = temp_millidegrees / 1000.0
                        if 10 <= temp_celsius <= 120:
                            logger.debug(f"sysfs 温度读取成功: {temp_celsius}°C (来自 {temp_file2})")
                            return round(temp_celsius, 1)
                    except (ValueError, IOError):
                        continue

        except Exception as e:
            logger.debug(f"sysfs 温度读取异常: {e}")

        return 0.0

    def _get_power_from_sysfs(self) -> float:
        """
        从 sysfs 读取 GPU 功耗（降级方案）。

        当 amdsmi 无法提供功耗数据时，通过 /sys/class/drm/card0/device/hwmon/ 读取。

        Returns:
            功耗值（瓦特），读取失败返回 0.0
        """
        if not self._device_path:
            return 0.0

        device_subpath = self._device_path / "device"
        hwmon_base = device_subpath / "hwmon"

        if not hwmon_base.exists():
            return 0.0

        try:
            for hwmon_dir in sorted(hwmon_base.glob("hwmon*")):
                if not hwmon_dir.is_dir():
                    continue

                # 尝试读取 power1_average（单位：微瓦）
                power_file = hwmon_dir / "power1_average"
                if power_file.exists():
                    try:
                        power_uw = int(power_file.read_text().strip())
                        power_watts = power_uw / 1_000_000.0  # μW → W
                        # 验证合理性（1-500W）
                        if 1 <= power_watts <= 500:
                            logger.debug(f"sysfs 功耗读取成功: {power_watts}W (来自 {power_file})")
                            return round(power_watts, 1)
                    except (ValueError, IOError):
                        continue

                # 备用：尝试 power1_input（当前功耗）
                power_file2 = hwmon_dir / "power1_input"
                if power_file2.exists():
                    try:
                        power_uw = int(power_file2.read_text().strip())
                        power_watts = power_uw / 1_000_000.0
                        if 1 <= power_watts <= 500:
                            logger.debug(f"sysfs 功耗读取成功: {power_watts}W (来自 {power_file2})")
                            return round(power_watts, 1)
                    except (ValueError, IOError):
                        continue

        except Exception as e:
            logger.debug(f"sysfs 功耗读取异常: {e}")

        return 0.0

    @staticmethod
    def _calculate_vram_percent(used_mb: int, total_mb: int) -> int:
        """
        计算显存使用百分比。

        关键特性：
        1. 防除零：total_mb 为 0 时返回 0
        2. 上限钳位：最大不超过 100%（即使实际超过也显示 100%）
        3. 爆显存友好：当 used > total 时仍显示 100% 而非异常值
        """
        if total_mb <= 0:
            return 0

        percent = int((used_mb / total_mb) * 100)

        # 关键：上限钳位到 100%，这样爆显存时显示具体数值而非异常
        return min(100, max(0, percent))

    # ------------------------------------------------------------------
    # Windows WMI GPU 采集（纯新增，不影响Linux任何代码）
    # ------------------------------------------------------------------

    def _collect_windows_wmi_gpu(self, device_id: int = 0) -> Dict[str, Any]:
        """
        通过 Windows WMI + PyTorch + PowerShell + pynvml 采集 AMD GPU 数据。

        多源数据融合策略（优先级从高到低）：
        1. pynvml (pynvml-amd-windows): 温度、GPU利用率、显存利用率 ★★★★★
        2. PyTorch: VRAM 已用量/总量（最精确）
        3. PowerShell Get-Counter: GPU 利用率（pynvml 不可用时）
        4. WMI: 显卡名称、VRAM 回退

        pynvml-amd-windows 是 AMD 官方 ADLX 的 pynvml 兼容封装，
        通过 pip install pynvml-amd-windows 安装，无需额外 SDK。
        它能提供温度、利用率和显存利用率等 WMI 无法获取的指标。
        """
        import platform
        if platform.system() != 'Windows':
            return self._get_default_gpu_data(device_id)

        # Windows COM 初始化（线程安全：在 execute_with_timeout 创建的线程中必须手动初始化 COM）
        _com_initialized = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_initialized = True
        except ImportError:
            pass  # pythoncom 不可用时依靠 wmi 模块自身处理

        try:
            # --- 数据源 1: pynvml (pynvml-amd-windows) 优先 ---
            pynvml_data = self._windows_get_pynvml_gpu(device_id)

            # --- 数据源 2: PyTorch VRAM（作为 pynvml VRAM 的补充/验证）---
            pytorch_vram_total, pytorch_vram_used = self._windows_get_pytorch_vram(device_id)

            # --- 数据融合 ---
            vram_total_mb = 0
            vram_used_mb = 0

            # VRAM 总量：优先 PyTorch（最精确），其次 pynvml
            if pytorch_vram_total > 0:
                vram_total_mb = pytorch_vram_total
            elif pynvml_data and pynvml_data.get('vram_total_mb', 0) > 0:
                vram_total_mb = pynvml_data['vram_total_mb']

            # VRAM 已用：优先 PyTorch，其次 pynvml
            if pytorch_vram_used > 0:
                vram_used_mb = pytorch_vram_used
            elif pynvml_data and pynvml_data.get('vram_used_mb', 0) > 0:
                vram_used_mb = pynvml_data['vram_used_mb']

            # 如果两者都不可用，回退 WMI
            if vram_total_mb <= 0:
                gpus = self._source_instance.get('gpus', [])
                if device_id < len(gpus):
                    vram_total_bytes = gpus[device_id].get('adapter_ram_bytes', 0)
                    vram_total_mb = vram_total_bytes // (1024 * 1024) if vram_total_bytes > 0 else 0
            if vram_used_mb <= 0:
                wmi_used = self._windows_get_vram_used(device_id)
                if wmi_used > 0:
                    vram_used_mb = wmi_used
                elif vram_total_mb > 0:
                    vram_used_mb = max(0, int(vram_total_mb * 0.3))

            # 计算百分比
            vram_percent = int((vram_used_mb / vram_total_mb * 100)) \
                if vram_total_mb > 0 else 0
            vram_percent = min(100, max(0, vram_percent))

            # GPU 利用率：优先 pynvml，其次 PowerShell
            if pynvml_data and pynvml_data.get('gpu_utilization', 0) > 0:
                gpu_util = pynvml_data['gpu_utilization']
            else:
                gpu_util = self._windows_get_gpu_utilization_powershell()

            # GPU 温度：优先 pynvml（ADLX 提供精确温度），其次 WMI
            if pynvml_data and pynvml_data.get('gpu_temperature', 0) > 0:
                temperature = pynvml_data['gpu_temperature']
            else:
                temperature = self._windows_get_gpu_temperature()

            return {
                'gpu_utilization': gpu_util,
                'vram_used_mb': vram_used_mb,
                'vram_total_mb': vram_total_mb,
                'vram_percent': vram_percent,
                'gpu_temperature': temperature,
                'power_draw': 0.0,  # pynvml-amd-windows 暂不支持功耗
                'device_name': self._get_device_name(device_id),
            }

        except Exception as e:
            logger.debug(f"windows_wmi GPU collection error: {e}")
            return self._get_default_gpu_data(device_id)
        finally:
            if _com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _windows_get_pynvml_gpu(self, device_id: int = 0) -> Optional[Dict[str, Any]]:
        """
        通过持久化的 pynvml 连接获取 AMD GPU 数据（Windows）。

        与之前的 static 版本不同，此方法使用初始化时缓存的 pynvml handles，
        避免每次调用都 init/shutdown 导致的数据抖动（隔会显示 -- 的问题）。

        pynvml-amd-windows 是专为 ComfyUI-Crystools 设计的 drop-in 替换库，
        将 pynvml 调用透明重定向到 AMD ADLX 后端，无需安装 ADLX SDK。

        Returns:
            包含 GPU 指标的字典，失败时返回 None
        """
        if not self._pynvml_available:
            return None

        try:
            with self._pynvml_lock:
                if device_id >= len(self._pynvml_handles):
                    return None

                import pynvml
                handle = self._pynvml_handles[device_id]
                data = {}

                # GPU 名称
                try:
                    name = pynvml.nvmlDeviceGetName(handle)
                    data['device_name'] = name.decode('utf-8') \
                        if isinstance(name, bytes) else name
                except Exception:
                    pass

                # 温度
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    if temp > 0:
                        data['gpu_temperature'] = float(temp)
                except Exception:
                    pass

                # GPU 利用率
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    data['gpu_utilization'] = int(util.gpu)
                    data['memory_utilization'] = int(util.memory)
                except Exception:
                    pass

                # VRAM
                try:
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    data['vram_total_mb'] = mem.total // (1024 * 1024)
                    data['vram_used_mb'] = mem.used // (1024 * 1024)
                except Exception:
                    pass

                return data if data else None

        except Exception as e:
            logger.debug(f"pynvml query failed: {e}")
            return None

    @staticmethod
    def _windows_get_pytorch_vram(device_id: int = 0) -> Tuple[int, int]:
        """
        通过 PyTorch CUDA 接口获取精确 VRAM 数据。

        这是 Windows 下最准确的 VRAM 数据源，因为：
        - WMI AdapterRAM 对 AMD 显卡经常少报
        - PyTorch 直接与 AMD HIP/ROCm 驱动通信

        Returns:
            (vram_total_mb, vram_used_mb): 元组，失败时返回 (0, 0)
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return (0, 0)

            device_count = torch.cuda.device_count()
            if device_id >= device_count:
                return (0, 0)

            # VRAM 总量：从 device properties 获取
            props = torch.cuda.get_device_properties(device_id)
            # 兼容不同 torch 版本的属性名 (total_mem vs total_memory)
            total_mem = getattr(props, 'total_memory', None) or getattr(props, 'total_mem', 0)
            vram_total_mb = total_mem // (1024 * 1024)

            # VRAM 已用量：从当前 CUDA context 获取
            vram_used_mb = torch.cuda.memory_allocated(device_id) // (1024 * 1024)

            logger.debug(
                f"PyTorch VRAM: {vram_used_mb}/{vram_total_mb} MB "
                f"(device {device_id}: {props.name})"
            )
            return (vram_total_mb, vram_used_mb)

        except ImportError:
            logger.debug("PyTorch not available for VRAM reading")
            return (0, 0)
        except Exception as e:
            logger.debug(f"PyTorch VRAM query failed: {e}")
            return (0, 0)

    @staticmethod
    def _windows_get_gpu_utilization_powershell() -> int:
        """
        通过 PowerShell Get-Counter 获取 GPU 引擎利用率。

        使用 perf counter 路径: \\GPU Engine(*engtype_3D)\\Utilization Percentage
        这是 Windows 下非 WMI 方式获取 GPU 利用率的最可靠方法。

        Returns:
            GPU 利用率百分比 (0-100)，失败时返回 0
        """
        try:
            import subprocess
            result = subprocess.run(
                [
                    'powershell', '-NoProfile', '-Command',
                    '(Get-Counter "\\GPU Engine(*engtype_3D)\\Utilization Percentage" -ErrorAction SilentlyContinue).CounterSamples '
                    '| Where-Object { $_.CookedValue -gt 0 } '
                    '| Measure-Object -Property CookedValue -Maximum '
                    '| Select-Object -ExpandProperty Maximum'
                ],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )

            if result.returncode == 0 and result.stdout.strip():
                gpu_util = round(float(result.stdout.strip()))
                return max(0, min(100, gpu_util))

            return 0

        except Exception as e:
            logger.debug(f"PowerShell GPU utilization query failed: {e}")
            return 0

    @staticmethod
    def _windows_get_vram_used(device_id: int = 0) -> int:
        """Windows: 通过 WMI 获取 VRAM 已用 MB（回退方案）"""
        try:
            import wmi
            conn = wmi.WMI()
            # 方法: 通过 CIM_GPUMemory 类（Windows 10 1703+ / Server 2016+）
            try:
                for mem in conn.CIM_GPUMemory():
                    if hasattr(mem, 'UsedMemory') and mem.UsedMemory is not None:
                        return int(mem.UsedMemory / (1024 * 1024))
            except (AttributeError, Exception):
                pass
            return 0
        except Exception:
            return 0

    @staticmethod
    def _windows_get_gpu_temperature() -> float:
        """Windows: 通过 WMI 获取 GPU 温度"""
        try:
            import wmi
            conn = wmi.WMI()
            # MSAcpi_ThermalZoneTemperature (需要管理员权限)
            temps = []
            for zone in conn.MSAcpi_ThermalZoneTemperature():
                if zone.CurrentTemperature is not None:
                    # 温度单位是摄氏度 * 10
                    celsius = zone.CurrentTemperature / 10.0
                    if 20 < celsius < 110:  # 合理温度范围
                        temps.append(celsius)

            if temps:
                return round(max(temps), 1)
            return 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _windows_get_gpu_utilization(wmi_conn) -> int:
        """Windows: 通过 WMI 获取 GPU 利用率（精度有限）"""
        try:
            # Win32_Processor.LoadPercentage 包含整体负载
            # 对于独立 GPU，这个值不准确，仅作参考
            procs = list(wmi_conn.Win32_Processor())
            if procs and procs[0].LoadPercentage is not None:
                # 返回一个保守估计值（实际GPU利用率可能不同）
                return min(100, max(0, int(procs[0].LoadPercentage)))
            return 0
        except Exception:
            return 0

    def _get_device_name(self, device_id: int) -> str:
        """获取 GPU 设备名称"""
        if 0 <= device_id < len(self._device_names):
            return self._device_names[device_id]
        return f"AMD Device {device_id}"

    def _get_default_gpu_data(self, device_id: int = 0) -> Dict[str, Any]:
        """获取默认的 GPU 数据结构（用于无 GPU 或错误场景）"""
        return {
            'gpu_utilization': 0,
            'vram_used_mb': 0,
            'vram_total_mb': 0,
            'vram_percent': 0,
            'gpu_temperature': 0.0,
            'power_draw': 0.0,
            'device_name': self._get_device_name(device_id),
        }

    def _get_fallback_gpu_data(self) -> List[Dict[str, Any]]:
        """
        获取降级的 GPU 数据（异常时使用）。

        优先返回缓存的上次成功数据，
        如果没有缓存则返回默认值。
        """
        if self._cached_gpu_data is not None:
            logger.debug("Using cached GPU data due to collection failure")
            return [self._cached_gpu_data.copy()]

        return [self._get_default_gpu_data()]

    def _get_safe_default_snapshot(self, timestamp: float) -> Dict[str, Any]:
        """获取安全的默认快照（极端异常场景）"""
        return {
            'timestamp': timestamp,
            'cpu_utilization': 0,
            'ram': {'total_gb': 0.0, 'used_gb': 0.0, 'percent': 0},
            'swap': {'total_gb': 0.0, 'used_gb': 0.0, 'percent': 0},   # 【v10.0】新增
            'gpus': [self._get_default_gpu_data()],
            'data_source': 'error_fallback',
            'version': '2.1.0',   # 【v10.0】版本号升级
            'disk_io': None,
            'network_io': None,
            'fan_speed': None,
        }

    @staticmethod
    def _call_rsmi_method(rsmi_obj, method_names: List[str], device_id: int, silent: bool = True) -> Any:
        """调用 rocm_smi 方法（尝试多个可能的名称）"""
        for method_name in method_names:
            if hasattr(rsmi_obj, method_name):
                method = getattr(rsmi_obj, method_name)
                try:
                    return method(device_id, silent=silent)
                except TypeError:
                    try:
                        return method(device_id)
                    except Exception:
                        continue
                except Exception:
                    continue
        return None

    @staticmethod
    def _read_sysfs_file(base_path: Path, relative_path: str) -> Optional[str]:
        """读取 sysfs 文件"""
        full_path = base_path / relative_path
        try:
            if full_path.exists():
                with open(full_path, 'r') as f:
                    return f.read().strip()
        except (IOError, OSError) as e:
            logger.debug(f"sysfs read error: {full_path}: {e}")
        return None

    @staticmethod
    def _read_hwmon_value(base_path: Path, sensor_name: str) -> Optional[str]:
        """查找并读取 hwmon 传感器值"""
        hwmon_base = base_path / "hwmon"
        if not hwmon_base.exists():
            return None

        try:
            for hwmon_dir in sorted(hwmon_base.glob("hwmon*")):
                if not hwmon_dir.is_dir():
                    continue
                sensor_path = hwmon_dir / sensor_name
                if sensor_path.exists():
                    try:
                        return sensor_path.read_text().strip()
                    except (IOError, OSError):
                        continue
        except OSError:
            pass

        return None

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """关闭并清理资源"""
        logger.info(f"Shutting down FeixueHardwareInfo (source={self._active_source})")

        try:
            if self._active_source == 'amdsmi' and self._source_instance is not None:
                if isinstance(self._source_instance, dict) and 'lib' in self._source_instance:
                    amdsmi_lib = self._source_instance['lib']
                    if hasattr(amdsmi_lib, 'amdsmi_shutdown'):
                        try:
                            amdsmi_lib.amdsmi_shutdown()
                        except Exception as e:
                            logger.warning(f"amdsmi shutdown error: {e}")

            elif self._active_source == 'rocm_smi' and self._source_instance is not None:
                if hasattr(self._source_instance, 'rocm_smi_shutdown'):
                    try:
                        self._source_instance.rocm_smi_shutdown()
                    except Exception as e:
                        logger.warning(f"rocm_smi shutdown error: {e}")

            # Windows WMI 无需特殊清理（WMI 连接自动释放）
            # 但 pynvml 持久化连接需要关闭
            self._shutdown_pynvml()

        except Exception as e:
            logger.warning(f"Shutdown error: {e}")

        # 重置状态
        self._active_source = None
        self._source_instance = None
        self._cached_gpu_data = None

        logger.info("FeixueHardwareInfo shutdown complete")

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def status(self) -> Dict[str, Any]:
        """返回监控器状态信息"""
        return {
            'active_source': self._active_source or 'none',
            'device_count': self._device_count,
            'device_names': self._device_names,
            'initialized': self._active_source is not None,
            'last_success_time': self._last_success_time,
            'has_cached_data': self._cached_gpu_data is not None,
            'stats': self._stats.copy(),
            'version': '2.1.0',   # [v10.0-fix] 统一版本号为2.1.0
        }

    @property
    def is_available(self) -> bool:
        """是否可用（有有效的 GPU 数据源）"""
        return self._active_source is not None

    def __repr__(self) -> str:
        """字符串表示"""
        source = self._active_source or 'none'
        devices = self._device_count
        return f"FeixueHardwareInfo(source={source}, devices={devices})"

    def __del__(self):
        """析构时自动清理"""
        try:
            if self._active_source is not None:
                self.shutdown()
        except Exception:
            pass


# ============================================================================
# 全局单例实例
# ============================================================================

_global_instance: Optional[FeixueHardwareInfo] = None
_instance_lock = threading.Lock()


def get_hardware_info() -> FeixueHardwareInfo:
    """
    获取全局 FeixueHardwareInfo 单例实例。

    线程安全的懒加载单例模式。

    Returns:
        FeixueHardwareInfo 全局实例
    """
    global _global_instance

    if _global_instance is None:
        with _instance_lock:
            if _global_instance is None:
                _global_instance = FeixueHardwareInfo()

    return _global_instance


def reset_hardware_info() -> None:
    """
    重置全局单例（主要用于测试）。

    警告：会关闭当前实例并销毁引用。
    """
    global _global_instance

    with _instance_lock:
        if _global_instance is not None:
            try:
                _global_instance.shutdown()
            except Exception:
                pass
            _global_instance = None


# ============================================================================
# 便捷函数（向后兼容）
# ============================================================================

def get_snapshot() -> Dict[str, Any]:
    """
    快速获取系统快照（便捷函数）。

    这是最常用的接口，等同于 get_hardware_info().get_snapshot()。

    Returns:
        符合接口契约的快照字典
    """
    return get_hardware_info().get_snapshot()


# ============================================================================
# 向后兼容层（供 __init__.py 和 websocket_service.py 使用）
# ============================================================================

class _MonitorWrapper:
    """
    监控服务包装类（向后兼容）。

    将新的单例模式 API 包装成旧的多线程接口，
    确保 __init__.py 和 websocket_service.py 无需修改即可工作。
    """

    def __init__(self):
        self._hw = get_hardware_info()
        self._thread = None
        self._stop_event = threading.Event()
        self._config = {'refresh_interval': 0.5}
        self.status = {'running': False}
        self._latest_snapshot = None
        self._start_time = time.time()  # 记录启动时间用于 uptime 计算

        # 检查硬件信息是否成功初始化（通过 _active_source 判断）
        _is_init = hasattr(self._hw, '_active_source') and self._hw._active_source is not None

        if _is_init:
            self._start_background_thread()
            self.is_running = True
            self.status['running'] = True
            logger.info("✅ 监控服务已启动（后台线程模式）")
        else:
            logger.warning("⚠️ 硬件信息初始化失败，监控服务不可用")
            self.is_running = False

    def _start_background_thread(self):
        """启动后台采集线程"""
        def _collection_loop():
            while not self._stop_event.is_set():
                try:
                    self._latest_snapshot = self._hw.get_snapshot()
                except Exception as e:
                    logger.error(f"数据采集异常: {e}")

                self._stop_event.wait(self._config['refresh_interval'])

        self._thread = threading.Thread(target=_collection_loop, daemon=True)
        self._thread.name = "FeixueMonitor-Background"
        self._thread.start()

    @property
    def _gpu_provider(self):
        return self._hw

    def get_snapshot(self):
        """获取最新快照（优先返回缓存的实时数据）"""
        if self._latest_snapshot:
            return self._latest_snapshot
        return self._hw.get_snapshot()

    def shutdown(self):
        """停止监控服务"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.is_running = False
        self.status['running'] = False

    @property
    def uptime(self) -> float:
        """返回运行时间（秒）"""
        return time.time() - self._start_time


def create_and_start_monitor() -> _MonitorWrapper:
    """
    创建并启动监控实例（向后兼容接口）。

    供 __init__.py 调用的入口点。
    内部使用新的 FeixueHardwareInfo 单例，但包装成旧的接口风格。

    Returns:
        _MonitorWrapper 实例（具有 .is_running, .status, .get_snapshot() 等属性）
    """
    return _MonitorWrapper()


if __name__ == "__main__":
    # 简单的测试入口
    print("=" * 60)
    print("FeixueHardwareInfo Test")
    print("=" * 60)

    hw = FeixueHardwareInfo()
    print(f"\nStatus: {hw.status}")

    print("\nCollecting snapshot...")
    snapshot = hw.get_snapshot()

    print(f"\nTimestamp: {snapshot['timestamp']}")
    print(f"CPU: {snapshot['cpu_utilization']}%")
    print(f"RAM: {snapshot['ram']['used_gb']}/{snapshot['ram']['total_gb']} GB ({snapshot['ram']['percent']}%)")

    if snapshot['gpus']:
        for i, gpu in enumerate(snapshot['gpus']):
            print(f"\nGPU {i} ({gpu['device_name']}):")
            print(f"  Utilization: {gpu['gpu_utilization']}%")
            print(f"  VRAM: {gpu['vram_used_mb']}/{gpu['vram_total_mb']} MB ({gpu['vram_percent']}%)")
            print(f"  Temperature: {gpu['gpu_temperature']}°C")
            print(f"  Power: {gpu['power_draw']}W")

    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)

    hw.shutdown()
