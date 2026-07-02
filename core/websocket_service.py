"""
FeixueMonitorService - 飞雪监测器 WebSocket 实时推送服务

参考 ComfyUI-Crystools 的 CMonitor.MonitorLoop() 设计理念，
实现低延迟（<100ms）的实时硬件监控数据推送。

核心特性：
1. asyncio 非阻塞监控循环（不占用主线程）
2. 通过 PromptServer.send_sync() 推送数据到所有连接的客户端
3. 支持动态调整刷新率（0.25s - 10s）
4. 异常自动恢复机制（出错后 1 秒重试）
5. 内置心跳检测和客户端管理
6. 与现有 HTTP API 完全兼容

接口契约：
- 推送事件类型: 'feixue.monitor'
- 数据格式: FeixueHardwareInfo.get_snapshot() 返回的字典
- 心跳响应: {type: 'pong', timestamp: <client_timestamp>}

Version: 3.40.7 (WebSocket Real-time)
Author: Feixue Team
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

# 配置日志
logger = logging.getLogger('FeixueMonitor')


class FeixueMonitorService:
    """
    WebSocket 实时监控服务

    参考 Crystools 的 CMonitor 实现，但针对飞雪监测器架构进行了优化：
    - 使用 asyncio 替代线程（更好的性能和资源利用）
    - 通过 ComfyUI 的 send_sync API 推送（原生支持多客户端）
    - 支持动态刷新率调整
    - 完善的错误恢复机制

    使用示例::

        # 创建服务实例
        service = FeixueMonitorService(rate=1.0)

        # 在异步上下文中启动
        await service.start_monitor_loop()

        # 动态调整刷新率
        service.set_rate(0.5)  # 500ms 刷新一次

        # 停止服务
        service.stop()
    """

    # 刷新率限制（秒）
    MIN_RATE = 0.25   # 最快 4Hz (250ms)
    MAX_RATE = 10.0   # 最慢 0.1Hz (10s)
    DEFAULT_RATE = 1.0  # 默认 1Hz (1s)

    # 错误恢复配置
    ERROR_RETRY_DELAY = 1.0  # 出错后等待时间（秒）

    # 增量更新（Delta）配置
    DELTA_ENABLED = True               # 是否启用增量推送
    DELTA_RATE_THRESHOLD = 1.0         # 刷新率 ≤ 此值时启用 delta（高频模式，秒）
    DELTA_CHANGE_THRESHOLD = 2.0       # 数值变化小于此百分比时发送 delta（0-100）

    # 反压感知配置
    SLOW_SEND_THRESHOLD_MS = 100.0     # 单次发送超过此值视为慢发送（毫秒）
    BACKOFF_MULTIPLIER = 1.5           # 慢发送时有效间隔的乘数
    BACKOFF_DECAY = 0.9                # 快发送时有效间隔的衰减系数
    BACKOFF_MAX_INTERVAL = 5.0         # 反压状态下最大有效间隔（秒）

    def __init__(self, rate: float = DEFAULT_RATE):
        """
        初始化 WebSocket 监控服务

        Args:
            rate: 初始刷新率（秒），范围 [MIN_RATE, MAX_RATE]
        """
        self._rate = self._clamp_rate(rate)

        # 状态标志
        self._stop_event: Optional[asyncio.Event] = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

        # 增量更新状态
        self._last_snapshot: Optional[Dict[str, Any]] = None
        self._delta_enabled = self.DELTA_ENABLED
        self._delta_change_threshold = self.DELTA_CHANGE_THRESHOLD

        # 反压感知状态
        self._effective_interval = self._rate
        self._backoff_active = False

        # WebSocket 连接健康统计
        self._ws_health = {
            'last_send_time': None,          # 上次发送完成时间戳
            'last_send_duration_ms': 0.0,    # 上次发送耗时（毫秒）
            'consecutive_slow_sends': 0,     # 连续慢发送次数
        }

        # 统计信息
        self._stats = {
            'total_pushes': 0,
            'successful_pushes': 0,
            'failed_pushes': 0,
            'errors': 0,
            'start_time': None,
            'last_push_time': None,
            'delta_pushes': 0,               # 增量推送次数
        }

        logger.info(
            f"[飞雪] FeixueMonitorService initialized with rate={self.rate}s"
        )

    @property
    def rate(self) -> float:
        """当前刷新率（秒），读取线程安全"""
        return self._rate

    async def start_monitor_loop(self) -> None:
        """
        启动监控循环

        这是主要的服务入口，参考 Crystools CMonitor.MonitorLoop() 实现：
        1. 创建 asyncio Event 用于优雅停止
        2. 进入无限循环采集数据并推送
        3. 异常时自动恢复

        注意：
        - 此方法应在异步上下文中调用（如 loop.create_task()）
        - 调用后会阻塞当前协程直到 stop() 被调用
        """
        if self._running:
            logger.warning("[飞雪] Monitor loop already running, ignoring duplicate start")
            return

        # 初始化停止事件
        self._stop_event = asyncio.Event()
        self._running = True

        # 重置统计信息
        self._stats['start_time'] = time.time()
        self._stats['total_pushes'] = 0
        self._stats['successful_pushes'] = 0
        self._stats['failed_pushes'] = 0
        self._stats['errors'] = 0
        self._stats['delta_pushes'] = 0

        # 重置增量/反压状态
        self._last_snapshot = None
        self._effective_interval = self._rate
        self._backoff_active = False
        self._ws_health = {
            'last_send_time': None,
            'last_send_duration_ms': 0.0,
            'consecutive_slow_sends': 0,
        }

        logger.info(f"[飞雪] ✅ WebSocket监控服务已启动")
        logger.info(f"[飞雪]    刷新率: {self.rate}s ({1/self.rate:.1f} Hz)")
        logger.info(f"[飞雪]    数据源: FeixueHardwareInfo.get_snapshot()")

        try:
            # 主监控循环
            while not self._stop_event.is_set():
                try:
                    # 单次采集+推送
                    await self._collect_and_push()

                    # 等待下一次采集（使用受反压调节后的有效间隔）
                    await asyncio.sleep(self._effective_interval)

                except asyncio.CancelledError:
                    # 任务被取消（正常停止流程）
                    logger.info("[飞雪] Monitor loop cancelled")
                    break

                except Exception as e:
                    # 异常处理：记录错误并等待重试
                    self._stats['errors'] += 1
                    logger.error(f"[飞雪] ⚠️ 监控循环异常: {e}", exc_info=True)

                    # 出错后等待一段时间再重试
                    await asyncio.sleep(self.ERROR_RETRY_DELAY)

        finally:
            # 循环结束清理
            self._running = False
            self._log_final_stats()

    async def _collect_and_push(self) -> None:
        """
        单次数据采集和推送

        流程：
        1. 调用 get_snapshot() 获取系统快照
        2. 通过 send_sync() 推送到所有客户端
        3. 更新统计信息
        """
        from .monitor import get_snapshot

        start_time = time.time()

        try:
            # 1. 采集数据（get_snapshot 保证永不失败）
            data = get_snapshot()

            # 2. 推送到客户端
            push_success = await self.send_message(data)

            # 3. 更新统计
            self._stats['total_pushes'] += 1
            if push_success:
                self._stats['successful_pushes'] += 1
            else:
                self._stats['failed_pushes'] += 1

            self._stats['last_push_time'] = time.time()

            # 性能日志（每 100 次输出一次）
            if self._stats['total_pushes'] % 100 == 0:
                elapsed = self._stats['last_push_time'] - start_time
                logger.debug(
                    f"[飞雪] Push #{self._stats['total_pushes']} "
                    f"took {elapsed*1000:.1f}ms"
                )

        except asyncio.CancelledError:
            # 任务取消时重新抛出，避免阻止服务正常停止
            raise
        except Exception as e:
            # 极端情况下的异常保护：记录错误但不向上抛出，
            # 确保外层监控循环不会因单次采集/推送失败而退出。
            self._stats['errors'] += 1
            logger.error(f"[飞雪] 数据采集/推送失败: {e}", exc_info=True)

    async def send_message(self, data: Dict[str, Any]) -> bool:
        """
        发送数据到所有连接的 WebSocket 客户端

        使用 ComfyUI 标准的 send_sync API 推送消息。
        所有订阅了 'feixue.monitor' 事件的客户端都会收到此消息。

        核心改进：
        1. 同步的 send_sync() 被 offload 到线程池，避免阻塞 asyncio 事件循环。
        2. 高频模式下支持增量（delta）推送，只发送变化的数值字段。
        3. 记录发送耗时，检测慢发送并自动反压。

        Args:
            data: 要发送的数据字典（通常为 get_snapshot() 返回值）

        Returns:
            bool: 是否成功发送（True=成功, False=失败）
        """
        # 决定发送完整快照还是增量 delta
        payload, is_delta = self._prepare_payload(data)

        # 将同步 send_sync 放到默认 executor，避免阻塞事件循环
        loop = asyncio.get_running_loop()
        send_start = time.time()
        try:
            push_success = await loop.run_in_executor(None, self._sync_send, payload)
        except Exception as e:
            logger.warning(f"[飞雪] 异步发送异常: {e}")
            push_success = False

        send_duration_ms = (time.time() - send_start) * 1000.0

        # 更新连接健康统计与反压状态
        self._update_ws_health(send_duration_ms)

        # 发送成功后更新上次完整快照，并统计增量推送
        if push_success:
            self._last_snapshot = data
            if is_delta:
                self._stats['delta_pushes'] += 1

        return push_success

    def _sync_send(self, payload: Dict[str, Any]) -> bool:
        """
        实际执行同步 send_sync 的函数（运行在线程池中）。

        保持原有错误处理和日志风格，仅在 executor 内执行。
        """
        try:
            # 动态导入避免循环依赖
            from server import PromptServer

            # 检查 PromptServer 是否可用
            if not hasattr(PromptServer, 'instance'):
                logger.debug("[飞雪] PromptServer.instance not available")
                return False

            server_instance = PromptServer.instance
            if server_instance is None:
                logger.debug("[飞雪] PromptServer.instance is None")
                return False

            # 使用 send_sync 推送消息到所有客户端
            # 事件类型: 'feixue.monitor'
            # 前端 WebSocketService 会监听此事件
            server_instance.send_sync('feixue.monitor', payload)

            return True

        except Exception as e:
            logger.warning(f"[飞雪] 消息推送失败: {e}")
            return False

    def _prepare_payload(
        self,
        data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool]:
        """
        根据增量策略决定最终发送的 payload。

        Returns:
            (payload, is_delta): payload 为要发送的字典，is_delta 表示是否为增量。
        """
        # 不满足增量条件时直接发送完整快照（向后兼容）
        if (
            not self._delta_enabled
            or self._rate > self.DELTA_RATE_THRESHOLD
            or self._last_snapshot is None
        ):
            return data, False

        changed, max_change = self._compute_numeric_delta(self._last_snapshot, data)

        # 变化超过阈值时回退到完整快照，保证前端拿到完整上下文
        if max_change > self._delta_change_threshold:
            return data, False

        # 发送增量包
        return {
            'delta': True,
            'changed': changed,
            'ts': data.get('timestamp', time.time()),
        }, True

    def _compute_numeric_delta(
        self,
        old: Dict[str, Any],
        new: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], float]:
        """
        比较两次快照中数值字段的差异。

        Returns:
            (changed_dict, max_change_percent):
            - changed_dict: 仅包含变化字段的嵌套结构
            - max_change_percent: 所有数值字段中的最大相对变化百分比
        """
        changed: Dict[str, Any] = {}
        max_change = 0.0

        # GPU 列表长度变化视为重大变化
        old_gpus = old.get('gpus') or []
        new_gpus = new.get('gpus') or []
        if len(old_gpus) != len(new_gpus):
            return {}, 100.0

        # CPU 利用率（百分比字段使用绝对百分点变化）
        cpu_change = self._numeric_change_pct(
            old.get('cpu_utilization'), new.get('cpu_utilization'),
            absolute_mode=True
        )
        if cpu_change > 0:
            changed['cpu_utilization'] = new['cpu_utilization']
        max_change = max(max_change, cpu_change)

        # RAM
        ram_changed, ram_max = self._dict_delta(
            old.get('ram'), new.get('ram'),
            ('total_gb', 'used_gb', 'percent'),
            absolute_keys=('percent',)
        )
        if ram_changed:
            changed['ram'] = ram_changed
        max_change = max(max_change, ram_max)

        # Swap
        swap_changed, swap_max = self._dict_delta(
            old.get('swap'), new.get('swap'),
            ('total_gb', 'used_gb', 'percent'),
            absolute_keys=('percent',)
        )
        if swap_changed:
            changed['swap'] = swap_changed
        max_change = max(max_change, swap_max)

        # GPUs
        gpu_changed_list: List[Dict[str, Any]] = []
        for g_old, g_new in zip(old_gpus, new_gpus):
            gpu_changed, gpu_max = self._dict_delta(
                g_old, g_new,
                ('gpu_utilization', 'vram_used_mb', 'vram_total_mb',
                 'vram_percent', 'gpu_temperature', 'power_draw'),
                absolute_keys=('gpu_utilization', 'vram_percent')
            )
            gpu_changed_list.append(gpu_changed)
            max_change = max(max_change, gpu_max)
        if any(gpu_changed_list):
            changed['gpus'] = gpu_changed_list

        # 磁盘 IO
        disk_changed, disk_max = self._dict_delta(
            old.get('disk_io'), new.get('disk_io'), ('read_mbps', 'write_mbps')
        )
        if disk_changed:
            changed['disk_io'] = disk_changed
        max_change = max(max_change, disk_max)

        # 网络 IO
        net_changed, net_max = self._dict_delta(
            old.get('network_io'), new.get('network_io'),
            ('upload_mbps', 'download_mbps')
        )
        if net_changed:
            changed['network_io'] = net_changed
        max_change = max(max_change, net_max)

        return changed, max_change

    @staticmethod
    def _dict_delta(
        old: Optional[Dict[str, Any]],
        new: Optional[Dict[str, Any]],
        keys: Tuple[str, ...],
        absolute_keys: Tuple[str, ...] = (),
    ) -> Tuple[Dict[str, Any], float]:
        """
        比较两个字典中指定数值字段的差异。

        Args:
            absolute_keys: 使用绝对变化（百分点/绝对值）而非相对变化的字段名。
        """
        changed: Dict[str, Any] = {}
        max_change = 0.0
        old = old or {}
        new = new or {}

        for key in keys:
            # 如果当前快照里没有该字段，说明该指标不可用，不应计入变化
            if key not in new:
                continue
            change = FeixueMonitorService._numeric_change_pct(
                old.get(key), new.get(key),
                absolute_mode=key in absolute_keys
            )
            if change > 0:
                changed[key] = new[key]
            max_change = max(max_change, change)

        return changed, max_change

    @staticmethod
    def _numeric_change_pct(
        old_value: Any,
        new_value: Any,
        absolute_mode: bool = False,
    ) -> float:
        """
        计算两个数值的变化量。

        - 两端都为 None 视为 0% 变化（指标同时不可用，不算变化）
        - 仅一端为 None 视为 100% 变化（指标从无到有或从有到无）
        - 相等视为 0% 变化
        - absolute_mode=True 时返回绝对差值（适用于百分比字段）
        - absolute_mode=False 时返回相对变化百分比（适用于绝对量字段）
        """
        if old_value is None and new_value is None:
            return 0.0
        if old_value is None or new_value is None:
            return 100.0
        try:
            old_f = float(old_value)
            new_f = float(new_value)
        except (TypeError, ValueError):
            return 100.0

        if old_f == new_f:
            return 0.0

        if absolute_mode:
            return abs(new_f - old_f)

        denom = max(abs(old_f), abs(new_f), 1.0)
        return abs(new_f - old_f) / denom * 100.0

    def _update_ws_health(self, send_duration_ms: float) -> None:
        """
        根据本次发送耗时更新连接健康统计和反压间隔。
        """
        now = time.time()
        self._ws_health['last_send_time'] = now
        self._ws_health['last_send_duration_ms'] = round(send_duration_ms, 2)

        if send_duration_ms > self.SLOW_SEND_THRESHOLD_MS:
            self._ws_health['consecutive_slow_sends'] += 1
            self._backoff_active = True
            old_interval = self._effective_interval
            self._effective_interval = min(
                self._effective_interval * self.BACKOFF_MULTIPLIER,
                self.BACKOFF_MAX_INTERVAL,
            )
            logger.warning(
                f"[飞雪] WebSocket 发送耗时 {send_duration_ms:.1f}ms 超过阈值 "
                f"{self.SLOW_SEND_THRESHOLD_MS:.0f}ms，"
                f"连续慢发送={self._ws_health['consecutive_slow_sends']}，"
                f"有效发送间隔 {old_interval:.2f}s -> {self._effective_interval:.2f}s"
            )
        else:
            self._ws_health['consecutive_slow_sends'] = 0
            if self._backoff_active:
                old_interval = self._effective_interval
                self._effective_interval = max(
                    self._rate,
                    self._effective_interval * self.BACKOFF_DECAY,
                )
                if self._effective_interval <= self._rate:
                    self._effective_interval = self._rate
                    self._backoff_active = False
                logger.debug(
                    f"[飞雪] WebSocket 发送恢复，有效发送间隔 "
                    f"{old_interval:.2f}s -> {self._effective_interval:.2f}s"
                )

    def get_ws_stats(self) -> Dict[str, Any]:
        """
        获取 WebSocket 连接健康统计。

        Returns:
            包含 last_send_time、last_send_duration_ms、consecutive_slow_sends
            以及当前反压状态的字典。
        """
        return {
            **self._ws_health,
            'effective_interval': self._effective_interval,
            'backoff_active': self._backoff_active,
            'rate': self._rate,
            'delta_enabled': self._delta_enabled,
        }

    def stop(self) -> None:
        """
        停止监控循环

        此方法是线程安全的，可以从任何地方调用。
        调用后会触发监控循环在下一个迭代点退出。
        """
        if not self._running:
            logger.debug("[飞雪] Monitor service not running, nothing to stop")
            return

        # 设置停止事件
        if self._stop_event is not None and not self._stop_event.is_set():
            self._stop_event.set()
            logger.info("[飞雪] 🛑 Stop signal sent to monitor loop")

        # 取消任务（如果有）
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            logger.debug("[飞雪] Monitor task cancelled")

        self._running = False
        logger.info("[飞雪] ✅ WebSocket监控服务已停止")

    def set_rate(self, rate: float) -> float:
        """
        动态调整刷新率

        可以在运行时随时调用此方法调整数据推送频率。
        新的刷新率会在下一次循环迭代时生效。

        Args:
            rate: 新的刷新率（秒），会被钳位到 [MIN_RATE, MAX_RATE]

        Returns:
            float: 实际设置的刷新率（经过钳位后的值）

        Example::

            # 设置为 500ms（高频模式，适合实时监控）
            service.set_rate(0.5)

            # 设置为 5s（低频模式，适合省电场景）
            service.set_rate(5.0)
        """
        old_rate = self.rate
        self._rate = self._clamp_rate(rate)

        # 未处于反压状态时，同步调整有效发送间隔
        if not self._backoff_active:
            self._effective_interval = self._rate

        logger.info(
            f"[飞雪] 刷新率已调整: {old_rate}s -> {self.rate}s "
            f"({1/self.rate:.1f} Hz)"
        )

        return self.rate

    @property
    def is_running(self) -> bool:
        """服务是否正在运行"""
        return self._running

    @property
    def stats(self) -> Dict[str, Any]:
        """获取统计信息快照"""
        current_time = time.time()
        uptime = (
            current_time - self._stats['start_time']
            if self._stats['start_time']
            else 0
        )

        return {
            **self._stats,
            'uptime_seconds': round(uptime, 2),
            'current_rate': self.rate,
            'is_running': self._running,
            'success_rate': (
                round(self._stats['successful_pushes'] / max(1, self._stats['total_pushes']) * 100, 2)
                if self._stats['total_pushes'] > 0
                else 0
            ),
        }

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp_rate(rate: float) -> float:
        """
        将刷新率钳位到合法范围

        Args:
            rate: 输入刷新率

        Returns:
            钳位后的刷新率
        """
        return max(FeixueMonitorService.MIN_RATE, min(rate, FeixueMonitorService.MAX_RATE))

    def _log_final_stats(self) -> None:
        """输出最终统计信息"""
        stats = self.stats
        logger.info(f"[飞雪] === 监控服务统计 ===")
        logger.info(f"[飞雪] 运行时长: {stats['uptime_seconds']:.1f}s")
        logger.info(f"[飞雪] 总推送次数: {stats['total_pushes']}")
        logger.info(f"[飞雪] 成功: {stats['successful_pushes']}")
        logger.info(f"[飞雪] 失败: {stats['failed_pushes']}")
        logger.info(f"[飞雪] 错误数: {stats['errors']}")
        logger.info(f"[飞雪] 成功率: {stats['success_rate']}%")
        logger.info(f"[飞雪] ===================")

    def __repr__(self) -> str:
        """字符串表示"""
        status = "运行中" if self._running else "已停止"
        return (
            f"FeixueMonitorService(status={status}, "
            f"rate={self.rate}s, "
            f"pushes={self._stats['total_pushes']})"
        )


# ============================================================================
# 全局单例实例
# ============================================================================

_global_service: Optional[FeixueMonitorService] = None


def get_monitor_service() -> FeixueMonitorService:
    """
    获取全局 FeixueMonitorService 单例实例

    Returns:
        FeixueMonitorService 全局实例
    """
    global _global_service

    if _global_service is None:
        _global_service = FeixueMonitorService(rate=FeixueMonitorService.DEFAULT_RATE)

    return _global_service


def reset_monitor_service() -> None:
    """
    重置全局单例（主要用于测试）

    警告：会停止当前服务并销毁引用
    """
    global _global_service

    if _global_service is not None:
        try:
            _global_service.stop()
        except Exception:
            pass
        _global_service = None


if __name__ == "__main__":
    # 测试入口
    import sys

    print("=" * 60)
    print("FeixueMonitorService Test")
    print("=" * 60)

    async def test_monitor():
        service = FeixueMonitorService(rate=1.0)

        print(f"\nInitial state: {service}")
        print(f"Is running: {service.is_running}")

        # 测试刷新率调整
        service.set_rate(0.5)
        print(f"After set_rate(0.5): rate={service.rate}")

        service.set_rate(15.0)  # 超出上限
        print(f"After set_rate(15.0): rate={service.rate} (should be clamped)")

        service.set_rate(0.1)  # 低于下限
        print(f"After set_rate(0.1): rate={service.rate} (should be clamped)")

        print("\nStarting monitor loop for 3 seconds...")
        print("(Will collect data but won't have PromptServer to push to)")

        # 创建任务运行 3 秒后停止
        task = asyncio.create_task(service.start_monitor_loop())
        await asyncio.sleep(3)
        service.stop()

        try:
            await task
        except asyncio.CancelledError:
            pass

        print(f"\nFinal stats:")
        for key, value in service.stats.items():
            print(f"  {key}: {value}")

        print("\n" + "=" * 60)
        print("Test completed!")
        print("=" * 60)

    # 运行测试
    asyncio.run(test_monitor())
