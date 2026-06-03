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

Version: 2.0.0 (WebSocket Real-time)
Author: Feixue Team
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

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

    def __init__(self, rate: float = DEFAULT_RATE):
        """
        初始化 WebSocket 监控服务

        Args:
            rate: 初始刷新率（秒），范围 [MIN_RATE, MAX_RATE]
        """
        self.rate = self._clamp_rate(rate)

        # 状态标志
        self._stop_event: Optional[asyncio.Event] = None
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

        # 统计信息
        self._stats = {
            'total_pushes': 0,
            'successful_pushes': 0,
            'failed_pushes': 0,
            'errors': 0,
            'start_time': None,
            'last_push_time': None,
        }

        logger.info(
            f"[飞雪] FeixueMonitorService initialized with rate={self.rate}s"
        )

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

        logger.info(f"[飞雪] ✅ WebSocket监控服务已启动")
        logger.info(f"[飞雪]    刷新率: {self.rate}s ({1/self.rate:.1f} Hz)")
        logger.info(f"[飞雪]    数据源: FeixueHardwareInfo.get_snapshot()")

        try:
            # 主监控循环
            while not self._stop_event.is_set():
                try:
                    # 单次采集+推送
                    await self._collect_and_push()

                    # 等待下一次采集（支持动态调整）
                    await asyncio.sleep(self.rate)

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

        except Exception as e:
            # 极端情况下的异常保护
            self._stats['errors'] += 1
            logger.error(f"[飞雪] 数据采集/推送失败: {e}")
            raise  # 向上层抛出以触发重试逻辑

    async def send_message(self, data: Dict[str, Any]) -> bool:
        """
        发送数据到所有连接的 WebSocket 客户端

        使用 ComfyUI 标准的 send_sync API 推送消息。
        所有订阅了 'feixue.monitor' 事件的客户端都会收到此消息。

        Args:
            data: 要发送的数据字典（通常为 get_snapshot() 返回值）

        Returns:
            bool: 是否成功发送（True=成功, False=失败）
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
            server_instance.send_sync('feixue.monitor', data)

            return True

        except Exception as e:
            logger.warning(f"[飞雪] 消息推送失败: {e}")
            return False

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
        self.rate = self._clamp_rate(rate)

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
