"""
UniversalMonitor - 全功能硬件监视器主控制器

这是整个监控系统的"大脑"，负责：
- 生命周期管理（初始化、启动、运行、停止）
- 数据聚合（调度所有采集器，组装 MonitorSnapshot）
- 配置热更新（监听配置变化，动态调整参数）
- API 服务（为前端提供数据访问接口）

设计理念：
- 单例模式（全局唯一实例）
- 生命周期管理（支持 with 语句）
- 自动资源清理（atexit 钩子）
- 线程安全（所有公共方法都是线程安全的）

架构示意：
┌─────────────────────────────────────┐
│         UniversalMonitor            │
│  ┌───────────┐  ┌────────────────┐  │
│  │ ConfigMgr │  │ CollectorReg   │  │
│  └───────────┘  └────────────────┘  │
│  ┌─────────────────────────────┐    │
│  │   NonBlockingScheduler       │    │
│  │  ┌─────┐ ┌─────┐ ┌────────┐  │    │
│  │  │ CPU │ │ RAM │ │  GPU   │  │    │
│  │  └─────┘ └─────┘ └────────┘  │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │     ThreadSafeCache          │    │
│  │   (latest_snapshot)           │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘

使用方式：
    # 方式 1: 上下文管理器（推荐）
    with UniversalMonitor() as monitor:
        snapshot = monitor.get_snapshot()
    
    # 方式 2: 手动管理
    monitor = UniversalMonitor.get_instance()
    monitor.start()
    try:
        data = monitor.get_latest('gpu')
    finally:
        monitor.stop()
"""

import threading
import time
import atexit
import logging
from typing import Optional, Dict, Any, List, Type, Union
from dataclasses import dataclass

from .data_models import (
    MonitorSnapshot,
    GPUMetrics,
    CPUMetrics,
    RAMMetrics,
    PredictionResult,
    PowerMetrics,
    log_limiter
)
from config.config_manager import ConfigManager, get_config_manager
from collectors.base import CollectorRegistry, BaseCollector, BaseGPUProvider
from utils.thread_safe import NonBlockingCollectorScheduler, ThreadSafeCache


@dataclass
class MonitorStatus:
    """监控器状态数据类"""
    running: bool
    uptime: float
    start_time: Optional[float]
    config: Dict[str, Any]
    collectors: Dict[str, Dict]
    gpu_provider: Optional[Dict]
    scheduler: Optional[Dict]
    last_error: Optional[str]
    version: str


class UniversalMonitor:
    """
    全功能硬件监视器主控制器。
    
    设计理念：
    - 单例模式（全局唯一实例）
    - 生命周期管理（支持 with 语句）
    - 自动资源清理（atexit 钩子）
    - 线程安全（所有公共方法都是线程安全的）
    
    Attributes:
        _instance: 单例实例
        _lock: 线程锁（用于单例模式的双重检查锁定）
        _config: 配置管理器实例
        _registry: 采集器注册表
        _scheduler: 非阻塞调度器
        _snapshot_cache: 快照缓存
        _cpu_collector: CPU 采集器
        _ram_collector: RAM 采集器
        _gpu_collector: GPU 采集器
        _predictor: VRAM 预测器
        _gpu_provider: GPU 提供者
        _running: 运行状态标志
        _start_time: 启动时间戳
        _last_error: 最后一次错误
        logger: 日志记录器
    """
    
    _instance: Optional['UniversalMonitor'] = None
    _lock = threading.Lock()
    _initialized = False
    
    def __new__(cls, config_path: Optional[str] = None) -> 'UniversalMonitor':
        """
        创建单例实例（线程安全的双重检查锁定）。
        
        Args:
            config_path: 配置文件路径（None 则使用默认路径）
            
        Returns:
            UniversalMonitor 单例实例
        """
        if cls._instance is None:
            with cls._lock:
                # 双重检查：另一个线程可能在我们等待锁的时候已经创建了实例
                if cls._instance is None:
                    instance = super().__new__(cls)
                    cls._instance = instance
        return cls._instance
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化监控系统（但不启动采集）。
        
        注意：由于单例模式，多次调用 __init__ 只会执行一次真正的初始化。
        
        Args:
            config_path: 配置文件路径（None 则使用默认路径）
        """
        # 防止重复初始化
        if UniversalMonitor._initialized:
            return
        
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing UniversalMonitor...")
        
        try:
            # 初始化配置管理器
            self._config: ConfigManager = get_config_manager(config_path)
            
            # 初始化注册表
            self._registry: CollectorRegistry = CollectorRegistry.get_instance()
            
            # 调度和缓存（延迟初始化）
            self._scheduler: Optional[NonBlockingCollectorScheduler] = None
            self._snapshot_cache: Optional[ThreadSafeCache] = None
            
            # 组件引用（延迟初始化）
            self._cpu_collector: Optional[BaseCollector] = None
            self._ram_collector: Optional[BaseCollector] = None
            self._gpu_collector: Optional[BaseCollector] = None
            self._predictor: Optional[Any] = None
            self._gpu_provider: Optional[BaseGPUProvider] = None
            
            # 状态变量
            self._running: bool = False
            self._start_time: Optional[float] = None
            self._last_error: Optional[Exception] = None
            
            # 配置监听器引用（用于后续移除）
            self._config_listener: Optional[Any] = None
            
            UniversalMonitor._initialized = True
            self.logger.info("UniversalMonitor initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize UniversalMonitor: {e}")
            raise
    
    @classmethod
    def get_instance(cls, config_path: Optional[str] = None) -> 'UniversalMonitor':
        """
        获取单例实例（线程安全）。
        
        这是获取 UniversalMonitor 实例的推荐方式。
        
        Args:
            config_path: 配置文件路径（仅在首次创建时有效）
            
        Returns:
            UniversalMonitor 单例实例
        """
        return cls(config_path)
    
    @classmethod
    def reset_instance(cls) -> None:
        """
        重置单例实例（主要用于测试）。
        
        警告：此方法会停止当前运行的监控器并销毁实例。
        不应在生产代码中使用。
        """
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.stop()
                except Exception:
                    pass
                cls._instance = None
                cls._initialized = False
    
    def start(self) -> None:
        """
        启动监控系统。
        
        流程：
        1. 读取配置
        2. 初始化所有采集器和 Provider
        3. 注册到 CollectorRegistry
        4. 启动 NonBlockingScheduler 后台线程
        5. 设置配置热更新监听
        6. 注册 atexit 清理钩子
        
        Raises:
            RuntimeError: 如果启动过程中发生错误
        """
        if self._running:
            self.logger.warning("Monitor already running, ignoring start() call")
            return
        
        self.logger.info("=" * 60)
        self.logger.info("Starting UniversalMonitor...")
        self.logger.info("=" * 60)
        
        try:
            # 步骤 1: 加载配置
            self._load_configuration()
            
            # 步骤 2: 初始化 GPU Provider（平台自适应）
            # 注意：必须在采集器（尤其是预测器）之前初始化
            self._initialize_gpu_provider()
            
            # 步骤 3: 初始化所有采集器
            self._initialize_collectors()
            
            # 步骤 4: 创建并配置调度器
            self._setup_scheduler()
            
            # 步骤 5: 启动后台线程
            self._scheduler.start()
            self._running = True
            self._start_time = time.time()
            
            # 步骤 6: 设置配置热更新监听
            self._setup_config_watching()
            
            # 步骤 7: 初始化快照缓存
            self._snapshot_cache = ThreadSafeCache(default_ttl=5.0)
            
            # 步骤 8: 注册 atexit 清理钩子
            atexit.register(self._cleanup_at_exit)
            
            # 步骤 9: 执行自检
            self._run_self_test()
            
            interval = self._config.get("refresh_interval", 1.0)
            self.logger.info(f"✓ UniversalMonitor started successfully (interval={interval}s)")
            self.logger.info(f"  - CPU Collector: {'✓' if self._cpu_collector else '✗'}")
            self.logger.info(f"  - RAM Collector: {'✓' if self._ram_collector else '✗'}")
            self.logger.info(f"  - GPU Provider: {'✓ ' + self._gpu_provider.name if self._gpu_provider else '✗'}")
            self.logger.info(f"  - Predictor: {'✓' if self._predictor else '✗'}")
            
        except Exception as e:
            self._last_error = e
            self.logger.error(f"Failed to start UniversalMonitor: {e}")
            # 尝试部分清理
            self._partial_cleanup()
            raise RuntimeError(f"Failed to start UniversalMonitor: {e}") from e
    
    def stop(self) -> None:
        """
        优雅停止监控系统。
        
        流程：
        1. 停止调度器后台线程
        2. 移除配置监听器
        3. 关闭所有 Provider
        4. 清理注册表中的所有采集器
        5. 清理缓存
        6. 重置状态
        """
        if not self._running:
            self.logger.debug("Monitor not running, ignoring stop() call")
            return
        
        self.logger.info("Stopping UniversalMonitor...")
        
        try:
            # 步骤 1: 停止调度器
            if self._scheduler is not None:
                try:
                    self._scheduler.stop()
                    self.logger.debug("Scheduler stopped")
                except Exception as e:
                    self.logger.warning(f"Error stopping scheduler: {e}")
            
            # 步骤 2: 移除配置监听器
            if self._config_listener is not None:
                try:
                    # 假设 ConfigManager 有 removeListener 方法
                    if hasattr(self._config, 'removeListener'):
                        self._config.removeListener(self._config_listener)
                except Exception as e:
                    self.logger.warning(f"Error removing config listener: {e}")
                self._config_listener = None
            
            # 步骤 3: 关闭 GPU Provider
            if self._gpu_provider is not None:
                try:
                    self._gpu_provider.shutdown()
                    self.logger.debug("GPU provider shut down")
                except Exception as e:
                    self.logger.warning(f"Error shutting down GPU provider: {e}")
            
            # 步骤 4: 清理注册表
            try:
                self._registry.shutdown_all()
                self.logger.debug("All collectors shut down")
            except Exception as e:
                self.logger.warning(f"Error shutting down collectors: {e}")
            
            # 步骤 5: 清理缓存
            if self._snapshot_cache is not None:
                self._snapshot_cache.clear()
            
            # 步骤 6: 重置状态
            self._running = False
            self._start_time = None
            
            # 移除 atexit 钩子（防止重复调用）
            try:
                atexit.unregister(self._cleanup_at_exit)
            except ValueError:
                pass  # 钩子未注册
            
            self.logger.info("✓ UniversalMonitor stopped successfully")
            
        except Exception as e:
            self._last_error = e
            self.logger.error(f"Error during stop: {e}")
            raise
    
    def _cleanup_at_exit(self) -> None:
        """atexit 清理回调"""
        self.logger.debug("Executing atexit cleanup...")
        try:
            self.stop()
        except Exception as e:
            self.logger.error(f"Error in atexit cleanup: {e}")
    
    def _partial_cleanup(self) -> None:
        """启动失败时的部分清理"""
        try:
            if self._scheduler is not None:
                self._scheduler.stop()
            if self._gpu_provider is not None:
                self._gpu_provider.shutdown()
            self._registry.shutdown_all()
        except Exception as e:
            self.logger.warning(f"Error in partial cleanup: {e}")
    
    def __enter__(self) -> 'UniversalMonitor':
        """
        上下文管理器入口。
        
        Returns:
            self: UniversalMonitor 实例
        """
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        上下文管理器出口。
        
        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪
            
        Returns:
            bool: False（不吞掉异常）
        """
        self.stop()
        return False  # 不吞掉异常
    
    # ==================== 初始化方法 ====================
    
    def _load_configuration(self) -> None:
        """加载和验证配置"""
        self.logger.debug("Loading configuration...")
        try:
            # 后端不需要 EventEmitter
            self._config.init(eventEmitter=None)
            
            # 验证关键配置项
            required_configs = ['refresh_interval']
            for key in required_configs:
                value = self._config.get(key)
                if value is None:
                    self.logger.warning(f"Missing config key: {key}, using default")
            
            self.logger.debug("Configuration loaded successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _initialize_collectors(self) -> None:
        """
        初始化所有数据采集器。
        
        初始化顺序：
        1. CPU 采集器（总是启用）
        2. RAM 采集器（总是启用）
        3. VRAM 预测器（根据配置决定是否启用）
        """
        self.logger.debug("Initializing collectors...")
        
        try:
            # 导入采集器模块（局部导入避免循环依赖）
            from collectors.cpu_collector import CPUCollector
            from collectors.memory_collector import RAMCollector
            
            # 1. CPU 采集器（总是启用）
            self.logger.debug("Initializing CPU collector...")
            self._cpu_collector = CPUCollector()
            self._registry.register_collector('cpu', self._cpu_collector)
            self.logger.debug("✓ CPU collector initialized")
            
            # 2. RAM 采集器（总是启用）
            self.logger.debug("Initializing RAM collector...")
            self._ram_collector = RAMCollector()
            self._registry.register_collector('ram', self._ram_collector)
            self.logger.debug("✓ RAM collector initialized")
            
            # 3. PRED 预测器（根据配置决定是否启用）
            prediction_enabled = self._config.get("prediction_enabled", True)
            if prediction_enabled:
                self._initialize_predictor()
            else:
                self.logger.info("Prediction disabled by config")
            
            self.logger.debug("All collectors initialized successfully")
            
        except ImportError as e:
            self.logger.error(f"Failed to import collector module: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Failed to initialize collectors: {e}")
            raise
    
    def _initialize_predictor(self) -> None:
        """初始化 VRAM 预测器"""
        try:
            from collectors.predictor import VRAMPredictor
            
            self.logger.debug("Initializing VRAM predictor...")
            self._predictor = VRAMPredictor(gpu_provider=self._gpu_provider)
            self._registry.register_collector('predictor', self._predictor)
            self.logger.debug("✓ VRAM predictor initialized")
            
        except ImportError as e:
            self.logger.warning(f"Could not import VRAMPredictor: {e}")
            self._predictor = None
        except Exception as e:
            self.logger.warning(f"Failed to initialize predictor: {e}")
            self._predictor = None
    
    def _initialize_gpu_provider(self) -> None:
        """
        初始化 GPU Provider（平台自适应选择）。
        
        选择逻辑：
        1. 检测平台 (Linux/Windows/Mac)
        2. 检测 GPU 厂商 (AMD/NVIDIA/Intel)
        3. 根据平台+厂商组合选择最佳 Provider
        """
        self.logger.debug("Initializing GPU provider...")
        
        try:
            # 延迟导入平台检测模块
            from utils.platform_detect import get_platform, detect_gpu_vendor
            
            platform_name = get_platform()
            vendor = detect_gpu_vendor()
            
            self.logger.info(f"Detected environment: {platform_name} + {vendor}")
            
            # 根据平台和厂商选择 Provider
            if vendor == "amd":
                if platform_name == "linux":
                    from providers.amd.linux_amd import AMDLinuxProvider
                    self._gpu_provider = AMDLinuxProvider()
                    self.logger.info("Selected AMD Linux provider")
                    
                elif platform_name == "windows":
                    from providers.amd.windows_amd import AMDWindowsProvider
                    self._gpu_provider = AMDWindowsProvider()
                    self.logger.info("Selected AMD Windows provider")
                    
                else:
                    self.logger.warning(f"No AMD provider for platform: {platform_name}")
                    
            elif vendor == "nvidia":
                # TODO: 实现 NvidiaSMIProvider (后续版本)
                self.logger.info("NVIDIA GPU detected, using generic provider (future implementation)")
                
            elif vendor == "intel":
                # TODO: 实现 IntelProvider (后续版本)
                self.logger.info("Intel GPU detected, using generic provider (future implementation)")
                
            else:
                self.logger.info(f"No specific provider for vendor '{vendor}', skipping GPU monitoring")
            
            # 尝试初始化选定的 Provider
            if self._gpu_provider is not None:
                if self._gpu_provider.initialize():
                    self._registry.register_gpu_provider(self._gpu_provider)
                    self.logger.info(f"✓ GPU provider initialized: {self._gpu_provider.name}")
                    
                    # 如果预测器已经初始化但没有 GPU Provider，重新初始化
                    if self._predictor and hasattr(self._predictor, '_gpu_provider'):
                        if self._predictor._gpu_provider is None:
                            self._predictor._gpu_provider = self._gpu_provider
                            self.logger.debug("Updated predictor with GPU provider")
                else:
                    self.logger.warning(f"✗ GPU provider failed to initialize: {self._gpu_provider.name}")
                    self._gpu_provider = None
                    
        except ImportError as e:
            self.logger.warning(f"Could not import platform detection or GPU provider: {e}")
            self._gpu_provider = None
        except Exception as e:
            self.logger.error(f"Error initializing GPU provider: {e}")
            self._gpu_provider = None
    
    def _setup_scheduler(self) -> None:
        """创建并配置非阻塞调度器"""
        self.logger.debug("Setting up scheduler...")
        
        try:
            interval = self._config.get("refresh_interval", 1.0)
            
            # 创建调度器实例
            self._scheduler = NonBlockingCollectorScheduler(interval=interval)
            
            # 注册所有采集器到调度器
            self._register_collectors_to_scheduler()
            
            self.logger.debug(f"✓ Scheduler created (interval={interval}s)")
            
        except Exception as e:
            self.logger.error(f"Failed to setup scheduler: {e}")
            raise
    
    def _register_collectors_to_scheduler(self) -> None:
        """将所有已初始化的采集器注册到调度器"""
        if self._scheduler is None:
            self.logger.warning("Cannot register collectors: scheduler not initialized")
            return
        
        registered_count = 0
        
        # 注册 CPU 采集器（传递 safe_collect 方法）
        if self._cpu_collector is not None:
            self._scheduler.register_collector('cpu', self._cpu_collector.safe_collect)
            registered_count += 1
        
        # 注册 RAM 采集器
        if self._ram_collector is not None:
            self._scheduler.register_collector('ram', self._ram_collector.safe_collect)
            registered_count += 1
        
        # 注册预测器
        if self._predictor is not None:
            self._scheduler.register_collector('predictor', self._predictor.safe_collect)
            registered_count += 1
        
        self.logger.debug(f"Registered {registered_count} collectors to scheduler")
    
    # ==================== 配置热更新 ====================
    
    def _setup_config_watching(self) -> None:
        """设置配置热更新监听"""
        
        def on_config_changed() -> None:
            """
            配置变更回调。
            """
            self.logger.info("Configuration changed")
        
        # 注册监听器（使用 ConfigManager 的 add_watcher 方法）
        try:
            self._config.add_watcher(on_config_changed)
            self._config_listener = on_config_changed
            self.logger.debug("Config watcher installed")
        except Exception as e:
            self.logger.warning(f"Could not setup config watching: {e}")
    
    def _handle_config_change(self, key: str) -> None:
        """
        处理单个配置项变更。
        
        Args:
            key: 变更的配置键
        """
        if key == "refresh_interval":
            # 动态调整采集间隔
            new_interval = self._config.get("refresh_interval", 1.0)
            self.logger.info(f"Refresh interval changed to {new_interval}s")
            
            if self._scheduler is not None:
                # 注意：NonBlockingScheduler 目前不支持动态修改 interval
                # 这里记录日志，用户需要重启才能生效
                self.logger.warning(
                    "Dynamic interval change requires restart. "
                    "Call stop() then start() to apply new interval."
                )
                
        elif key == "prediction_enabled":
            # 动态开关预测器
            enabled = self._config.get("prediction_enabled", True)
            
            if enabled and self._predictor is None:
                self.logger.info("Prediction enabled, initializing predictor...")
                self._initialize_predictor()
                # 重新注册到调度器
                if self._scheduler is not None and self._predictor is not None:
                    self._scheduler.add_collector('predictor', self._predictor)
                    
            elif not enabled and self._predictor is not None:
                self.logger.info("Prediction enabled, removing predictor...")
                self._registry.unregister_collector('predictor')
                if self._scheduler is not None:
                    self._scheduler.remove_collector('predictor')
                self._predictor = None
                
        elif key.startswith("gpu."):
            # GPU 相关配置变更
            self.logger.info(f"GPU config changed: {key}, may require restart")
            
        else:
            self.logger.debug(f"Ignoring config change for: {key}")
    
    # ==================== 数据访问接口 ====================
    
    def get_snapshot(self) -> MonitorSnapshot:
        """
        获取最新的完整快照。
        
        这是前端 API 主要调用的方法。该方法会：
        1. 从调度器缓存读取各采集器最新数据
        2. 组装成 MonitorSnapshot 对象
        3. 写入 snapshot_cache（供 API 层读取）
        4. 返回快照
        
        Returns:
            MonitorSnapshot: 包含所有监控数据的完整快照
            
        Raises:
            RuntimeError: 如果监控器未启动
        """
        if not self._running:
            raise RuntimeError("Monitor not started. Call start() first.")
        
        now = time.time()
        
        try:
            # 采集各组件数据
            cpu_metrics = self._get_collector_data('cpu', CPUMetrics)
            ram_metrics = self._get_collector_data('ram', RAMMetrics)
            gpu_metrics = self._get_gpu_data()
            prediction = self._get_prediction_data()
            power_metrics = self._get_power_data()  # TODO: 后续实现
            
            # 组装快照
            snapshot = MonitorSnapshot(
                timestamp=now,
                gpu_metrics=gpu_metrics,
                cpu_metrics=cpu_metrics,
                ram_metrics=ram_metrics,
                power_metrics=power_metrics,
                prediction=prediction,
                data_source=self._gpu_provider.name if self._gpu_provider else "none",
                version="1.0.0"
            )
            
            # 校验数据合理性
            if hasattr(snapshot, 'validate') and not snapshot.validate():
                # 使用频率限制器，避免刷屏
                if log_limiter.should_log("snapshot_validation_failed"):
                    self.logger.warning("Snapshot validation failed, returning partial data")
            
            # 缓存最新快照
            if self._snapshot_cache is not None:
                self._snapshot_cache.set('latest', snapshot)
            
            return snapshot
            
        except Exception as e:
            self._last_error = e
            self.logger.error(f"Error collecting snapshot: {e}")
            # 返回部分数据的快照而不是抛出异常
            return self._create_error_snapshot(now, str(e))
    
    def _get_collector_data(self, name: str, expected_type: Type):
        """
        安全地从调度器获取采集器数据。
        
        优先从调度器缓存读取，失败则降级为直接同步调用。
        
        Args:
            name: 采集器名称
            expected_type: 期望的数据类型
            
        Returns:
            采集的数据，或 None（如果获取失败）
        """
        # 方式 1: 从调度器缓存读取（非阻塞）
        if self._scheduler is not None:
            try:
                data = self._scheduler.get_latest(name)
                if data is not None:
                    return data
            except Exception as e:
                self.logger.debug(f"Failed to get {name} from scheduler: {e}")
        
        # 方式 2: 降级为直接调用采集器（同步，但保证有数据）
        collector = self._registry.get_collector(name)
        if collector is not None:
            try:
                return collector.safe_collect(default=None)
            except Exception as e:
                self.logger.warning(f"Direct collection failed for {name}: {e}")
        
        return None
    
    def _get_gpu_data(self) -> Optional[GPUMetrics]:
        """
        获取 GPU 数据（如果可用）。
        
        Returns:
            GPUMetrics: GPU 指标数据，或 None（如果不可用）
        """
        if self._gpu_provider is None or not self._gpu_provider.is_available():
            return None
        
        try:
            # 尝试从活跃源采集
            if hasattr(self._gpu_provider, '_collect_from_active_source'):
                return self._gpu_provider._collect_from_active_source(0)
            elif hasattr(self._gpu_provider, 'collect'):
                result = self._gpu_provider.collect()
                if isinstance(result, GPUMetrics):
                    return result
                elif isinstance(result, dict):
                    return GPUMetrics(**result)
                else:
                    self.logger.warning(f"Unexpected GPU data type: {type(result)}")
                    return None
            else:
                self.logger.debug("GPU provider has no collect method")
                return None
                
        except Exception as e:
            self.logger.debug(f"GPU collection failed: {e}")
            return None
    
    def _get_prediction_data(self) -> Optional[PredictionResult]:
        """
        获取预测数据（如果可用）。
        
        Returns:
            PredictionResult: 预测结果，或 None（如果不可用）
        """
        if self._predictor is None:
            return None
        
        try:
            data = self._get_collector_data('predictor', PredictionResult)
            if data is not None:
                return data
        except Exception as e:
            self.logger.debug(f"Prediction collection failed: {e}")
        
        return None
    
    def _get_power_data(self) -> Optional[PowerMetrics]:
        """
        获取功耗数据（预留接口）。
        
        TODO: 后续版本实现 PowerCollector
        
        Returns:
            PowerMetrics: 功耗指标，或 None
        """
        # TODO: 实现功耗采集
        return None
    
    def _create_error_snapshot(self, timestamp: float, error_msg: str) -> MonitorSnapshot:
        """
        创建错误状态的快照（包含部分可用数据）。
        
        Args:
            timestamp: 时间戳
            error_msg: 错误信息
            
        Returns:
            MonitorSnapshot: 包含部分数据的快照
        """
        return MonitorSnapshot(
            timestamp=timestamp,
            gpu_metrics=None,
            cpu_metrics=self._get_collector_data('cpu', CPUMetrics),
            ram_metrics=self._get_collector_data('ram', RAMMetrics),
            power_metrics=None,
            prediction=None,
            data_source="error",
            version="1.0.0",
            error=error_msg
        )
    
    def get_latest(self, metric_name: str) -> Any:
        """
        获取某个特定指标的最新值。
        
        Args:
            metric_name: 指标名称 ('cpu', 'ram', 'gpu', 'predictor')
            
        Returns:
            该指标的最新数据，或 None（如果不存在）
        """
        if not self._running:
            self.logger.warning(f"Cannot get_latest('{metric_name}'): monitor not running")
            return None
        
        if self._scheduler is not None:
            try:
                return self._scheduler.get_latest(metric_name)
            except Exception as e:
                self.logger.warning(f"Failed to get latest '{metric_name}': {e}")
        
        return None
    
    def get_cached_snapshot(self) -> Optional[MonitorSnapshot]:
        """
        从缓存获取最新的快照（不触发新的采集）。
        
        适用于高频访问场景，避免重复采集开销。
        
        Returns:
            MonitorSnapshot: 缓存的快照，或 None（如果没有缓存）
        """
        if self._snapshot_cache is not None:
            try:
                return self._snapshot_cache.get('latest')
            except Exception as e:
                self.logger.debug(f"Failed to get cached snapshot: {e}")
        return None
    
    # ==================== 状态查询接口 ====================
    
    @property
    def is_running(self) -> bool:
        """
        是否正在运行。
        
        Returns:
            bool: True 表示正在运行
        """
        return self._running
    
    @property
    def uptime(self) -> float:
        """
        运行时长（秒）。
        
        Returns:
            float: 运行时长（秒），如果未运行则返回 0.0
        """
        if self._start_time is not None:
            return time.time() - self._start_time
        return 0.0
    
    @property
    def status(self) -> Dict[str, Any]:
        """
        完整状态报告（用于调试和 /status API）。
        
        Returns:
            dict: 包含详细状态信息的字典
        """
        # 收集采集器状态
        collectors_status = {}
        try:
            all_collectors = self._registry.get_all_collectors()
            for name, collector in all_collectors.items():
                if collector is not None:
                    collectors_status[name] = {
                        'stats': getattr(collector, 'stats', {}),
                        'enabled': getattr(collector, 'enabled', True)
                    }
        except Exception as e:
            self.logger.debug(f"Error getting collector stats: {e}")
            collectors_status = {'error': str(e)}
        
        # GPU Provider 状态
        gpu_status = None
        if self._gpu_provider is not None:
            try:
                gpu_status = {
                    'name': getattr(self._gpu_provider, 'name', 'unknown'),
                    'available': getattr(self._gpu_provider, 'is_available', lambda: False)(),
                    'info': getattr(self._gpu_provider, 'info', None)
                }
            except Exception as e:
                gpu_status = {'error': str(e)}
        
        # 调度器状态
        scheduler_status = None
        if self._scheduler is not None:
            try:
                scheduler_status = getattr(self._scheduler, 'stats', None)
            except Exception:
                scheduler_status = None
        
        return {
            'running': self._running,
            'uptime': round(self.uptime, 2),
            'start_time': self._start_time,
            'config': {
                'refresh_interval': self._config.get("refresh_interval", 1.0),
                'prediction_enabled': self._config.get("prediction_enabled", True),
            },
            'collectors': collectors_status,
            'gpu_provider': gpu_status,
            'scheduler': scheduler_status,
            'last_error': str(self._last_error) if self._last_error else None,
            'version': '1.0.0'
        }
    
    # ==================== 自检和诊断 ====================
    
    def _run_self_test(self) -> bool:
        """
        运行自检程序，验证各组件是否正常工作。
        
        Returns:
            bool: True 表示自检通过
        """
        self.logger.info("Running self-test...")
        
        all_passed = True
        
        # 测试 CPU 采集器
        if self._cpu_collector is not None:
            try:
                test_data = self._cpu_collector.safe_collect(default=None)
                if test_data is not None:
                    self.logger.info(f"  ✓ CPU collector: OK ({test_data})")
                else:
                    self.logger.warning("  ✗ CPU collector: returned None")
                    all_passed = False
            except Exception as e:
                self.logger.error(f"  ✗ CPU collector: ERROR - {e}")
                all_passed = False
        else:
            self.logger.warning("  ✗ CPU collector: not initialized")
            all_passed = False
        
        # 测试 RAM 采集器
        if self._ram_collector is not None:
            try:
                test_data = self._ram_collector.safe_collect(default=None)
                if test_data is not None:
                    self.logger.info(f"  ✓ RAM collector: OK ({test_data})")
                else:
                    self.logger.warning("  ✗ RAM collector: returned None")
                    all_passed = False
            except Exception as e:
                self.logger.error(f"  ✗ RAM collector: ERROR - {e}")
                all_passed = False
        else:
            self.logger.warning("  ✗ RAM collector: not initialized")
            all_passed = False
        
        # 测试 GPU Provider
        if self._gpu_provider is not None:
            try:
                available = self._gpu_provider.is_available()
                if available:
                    self.logger.info(f"  ✓ GPU provider: OK ({self._gpu_provider.name})")
                else:
                    self.logger.warning(f"  ⚠ GPU provider: not available ({self._gpu_provider.name})")
            except Exception as e:
                self.logger.error(f"  ✗ GPU provider: ERROR - {e}")
                all_passed = False
        else:
            self.logger.info("  ○ GPU provider: not configured (optional)")
        
        # 测试调度器
        if self._scheduler is not None:
            try:
                stats = getattr(self._scheduler, 'stats', {})
                self.logger.info(f"  ✓ Scheduler: OK (stats: {stats})")
            except Exception as e:
                self.logger.error(f"  ✗ Scheduler: ERROR - {e}")
                all_passed = False
        else:
            self.logger.error("  ✗ Scheduler: not initialized")
            all_passed = False
        
        if all_passed:
            self.logger.info("✓ Self-test passed")
        else:
            self.logger.warning("⚠ Self-test completed with warnings/errors")
        
        return all_passed
    
    def run_diagnostics(self) -> Dict[str, Any]:
        """
        运行完整诊断，返回详细的系统信息。
        
        用于调试和问题排查。
        
        Returns:
            dict: 包含诊断信息的字典
        """
        diagnostics = {
            'timestamp': time.time(),
            'monitor': {
                'running': self._running,
                'uptime': self.uptime,
                'version': '1.0.0',
                'thread_id': threading.current_thread().ident
            },
            'components': {},
            'system': {}
        }
        
        # 诊断各组件
        components = {}
        
        # ConfigManager
        try:
            components['config'] = {
                'loaded': self._config is not None,
                'keys': list(self._config._config.keys()) if hasattr(self._config, '_config') else []
            }
        except Exception as e:
            components['config'] = {'error': str(e)}
        
        # Registry
        try:
            components['registry'] = {
                'collector_count': len(self._registry.get_all_collectors()),
                'collectors': list(self._registry.get_all_collectors().keys())
            }
        except Exception as e:
            components['registry'] = {'error': str(e)}
        
        # Scheduler
        try:
            if self._scheduler is not None:
                components['scheduler'] = {
                    'interval': getattr(self._scheduler, '_interval', 'unknown'),
                    'running': getattr(self._scheduler, '_running', False),
                    'collector_count': len(getattr(self._scheduler, '_collectors', {}))
                }
        except Exception as e:
            components['scheduler'] = {'error': str(e)}
        
        diagnostics['components'] = components
        
        # 系统信息
        try:
            import platform
            import os
            
            diagnostics['system'] = {
                'platform': platform.platform(),
                'python_version': platform.python_version(),
                'pid': os.getpid(),
                'working_dir': os.getcwd(),
                'thread_count': threading.active_count()
            }
        except Exception as e:
            diagnostics['system'] = {'error': str(e)}
        
        return diagnostics
    
    # ==================== 辅助方法 ====================
    
    def force_refresh(self) -> MonitorSnapshot:
        """
        强制立即刷新所有采集器并返回新快照。
        
        忽略缓存，强制重新采集。适用于需要实时数据的场景。
        
        Returns:
            MonitorSnapshot: 最新采集的快照
        """
        if not self._running:
            raise RuntimeError("Monitor not started. Call start() first.")
        
        self.logger.debug("Force refreshing all collectors...")
        
        # 触发调度器立即采集（如果支持）
        if self._scheduler is not None and hasattr(self._scheduler, 'force_collect'):
            try:
                self._scheduler.force_collect()
            except Exception as e:
                self.logger.warning(f"Force collect failed: {e}")
        
        # 清除缓存
        if self._snapshot_cache is not None:
            self._snapshot_cache.invalidate('latest')
        
        # 获取新快照
        return self.get_snapshot()
    
    def reload_config(self) -> None:
        """
        重新加载配置文件。
        
        触发配置管理器重新读取配置文件，并应用变更。
        """
        self.logger.info("Reloading configuration...")
        try:
            if hasattr(self._config, 'reload'):
                self._config.reload()
                self.logger.info("Configuration reloaded successfully")
            else:
                self.logger.warning("ConfigManager does not support reload()")
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {e}")
            raise
    
    def __repr__(self) -> str:
        """返回对象的字符串表示"""
        status = "RUNNING" if self._running else "STOPPED"
        uptime_str = f"{self.uptime:.1f}s" if self._running else "N/A"
        return (
            f"UniversalMonitor("
            f"status={status}, "
            f"uptime={uptime_str}, "
            f"gpu={'✓' if self._gpu_provider else '✗'}, "
            f"predictor={'✓' if self._predictor else '✗'})"
        )
    
    def __del__(self):
        """析构函数，确保资源被释放"""
        try:
            if self._running:
                self.logger.warning(
                    "UniversalMonitor was deleted without calling stop(). "
                    "Use 'with' statement or call stop() explicitly."
                )
                self.stop()
        except Exception:
            pass  # 析构函数中不应抛出异常


# ==================== 便捷函数 ====================

def get_monitor(config_path: Optional[str] = None) -> UniversalMonitor:
    """
    获取 UniversalMonitor 实例的便捷函数。
    
    这是最常用的入口点，推荐在应用代码中使用。
    
    Args:
        config_path: 可选的配置文件路径
        
    Returns:
        UniversalMonitor: 监控器实例
        
    示例：
        >>> monitor = get_monitor()
        >>> monitor.start()
        >>> snapshot = monitor.get_snapshot()
        >>> monitor.stop()
    """
    return UniversalMonitor.get_instance(config_path)


def create_and_start_monitor(config_path: Optional[str] = None) -> UniversalMonitor:
    """
    创建并启动监控器的便捷函数。
    
    适用于快速启动场景。
    
    Args:
        config_path: 可选的配置文件路径
        
    Returns:
        UniversalMonitor: 已启动的监控器实例
        
    示例：
        >>> with create_and_start_monitor() as monitor:
        ...     snapshot = monitor.get_snapshot()
        ...     print(snapshot.cpu_metrics)
    """
    monitor = UniversalMonitor.get_instance(config_path)
    monitor.start()
    return monitor
