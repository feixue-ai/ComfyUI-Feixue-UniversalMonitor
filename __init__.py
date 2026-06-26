"""
ComfyUI-Feixue-UniversalMonitor - 飞雪通用监测器
============================================

功能：
- 实时监测 ComfyUI 工作流执行状态
- Premium UI 5 色 × 5 风格悬浮监控栏
- 实时 GPU/CPU/内存监控（后端服务）
- WebSocket / HTTP 双通道实时数据推送

作者: Feixue Team
版本: 3.40.1 (ADLX Bridge + Tiered Fallback)
"""

__version__ = "3.40.1"
__author__ = "Feixue Team"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./web"

print("[飞雪监测器] ✅ 插件加载完成 (v3.40.1 ADLX Bridge + 字段级降级)")

# ============================================================================
# 获取插件根目录（用于导入 core 模块）
# ============================================================================
import os
import sys
_FEIXUE_ROOT = os.path.dirname(os.path.abspath(__file__))
if _FEIXUE_ROOT not in sys.path:
    sys.path.insert(0, _FEIXUE_ROOT)

# ============================================================================
# 启动后端监控服务（非致命，失败不影响 ComfyUI 主流程）
# ============================================================================
_monitor = None

try:
    from core.monitor import create_and_start_monitor
    
    # 创建并启动监控实例（后台守护线程运行）
    _monitor = create_and_start_monitor()
    
    if _monitor and _monitor.is_running:
        # 获取 GPU 信息用于日志显示
        gpu_info = "Unknown"
        if hasattr(_monitor, '_gpu_provider') and _monitor._gpu_provider:
            _provider = _monitor._gpu_provider
            source_name = getattr(_provider, '_active_source', 'unknown')
            device_name = "N/A"
            try:
                device_name = _provider.get_device_name(0)
            except Exception:
                pass
            gpu_info = f"{source_name} ({device_name})"

        print(f"[飞雪监测器] ✅ 后端监控已启动 (GPU: {gpu_info})")
        print(f"[飞雪监测器]    - CPU/RAM采集器: 运行中")
        print(f"[飞雪监测器]    - 采集间隔: {_monitor._config.get('refresh_interval', 1.0)}s")
        print(f"[飞雪监测器]    - 状态: {_monitor.status.get('running', False)}")
    else:
        print("[飞雪监测器] ⚠️ 后端监控启动异常（监控实例未正常运行）")
        _monitor = None

except ImportError as e:
    print(f"[飞雪监测器] ⚠️ 后端监控模块导入失败（可能缺少依赖）: {e}")
    print("[飞雪监测器]    插件将继续运行，但监控功能不可用")
except Exception as e:
    print(f"[飞雪监测器] ⚠️ 后端监控启动失败（非致命）: {e}")
    import traceback
    print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
    _monitor = None


# ============================================================================
# 公共 API：供其他模块或前端获取监控数据
# ============================================================================

def get_monitor():
    """
    获取当前监控实例。
    
    Returns:
        UniversalMonitor 实例，如果未启动则返回 None
        
    Example::
        from ComfyUI-Feixue-UniversalMonitor import get_monitor
        monitor = get_monitor()
        if monitor:
            snapshot = monitor.get_snapshot()
    """
    return _monitor


def get_snapshot():
    """
    获取最新的系统监控快照。
    
    Returns:
        MonitorSnapshot 对象，包含 CPU/RAM/GPU 数据
        如果监控未运行则返回 None
        
    Example::
        from ComfyUI-Feixue-UniversalMonitor import get_snapshot
        snapshot = get_snapshot()
        if snapshot and snapshot.cpu_metrics:
            print(f"CPU: {snapshot.cpu_metrics.cpu_utilization}%")
    """
    if _monitor is None:
        return None
    try:
        return _monitor.get_snapshot()
    except Exception:
        return None


# ============================================================================
# HTTP API 端点 - 为前端提供数据访问接口（Task 2: 前后端数据通道）
# 使用 ComfyUI 标准方式：@PromptServer.instance.routes 装饰器（20+ 插件验证）
# ============================================================================

import asyncio
import math
from aiohttp import web
from server import PromptServer
import time as _time

try:
    from core.memory_cleaner import free_memory
except Exception as _memory_cleaner_err:
    print(f"[飞雪监测器] ⚠️ 内存清理模块导入失败: {_memory_cleaner_err}")
    free_memory = None


@PromptServer.instance.routes.get('/feixue_monitor/snapshot')
async def handle_snapshot(request):
    """
    处理 /feixue_monitor/snapshot 请求

    返回最新的系统监控数据，JSON 格式。

    Args:
        request: aiohttp 请求对象

    Returns:
        JSON Response: 包含 CPU/RAM/GPU 数据的字典
    """
    try:
        # 获取最新快照
        snapshot = get_snapshot()

        if snapshot is None:
            # 监控服务未运行
            return web.json_response({
                "error": "Monitor not running",
                "message": "Backend monitor service is not available",
                "timestamp": _time.time(),
                "status": "unavailable"
            }, status=503)

        # 兼容新旧两种返回格式
        # 新格式 (dict): 直接来自 FeixueHardwareInfo.get_snapshot()
        # 旧格式 (object): MonitorSnapshot 对象（已弃用）
        if isinstance(snapshot, dict):
            # 新格式：直接返回（已是前端友好的 JSON 结构）
            snapshot["status"] = "ok"
            snapshot["api_version"] = "2.0"
            return web.json_response(snapshot)

        # 旧格式：MonitorSnapshot 对象转换（向后兼容）
        data = {
            "timestamp": snapshot.timestamp,
            "status": "ok",
            "data_source": snapshot.data_source,
            "version": snapshot.version,
        }

        # CPU 数据
        if snapshot.cpu_metrics:
            data["cpu"] = {
                "utilization": snapshot.cpu_metrics.cpu_utilization,
                "cores": snapshot.cpu_metrics.cpu_count,
                "freq_mhz": snapshot.cpu_metrics.cpu_freq,
                "per_core_usage": snapshot.cpu_metrics.per_core_usage,
            }
        else:
            data["cpu"] = None

        # RAM 数据
        if snapshot.ram_metrics:
            # 转换 MB 为 GB（前端更友好）
            data["ram"] = {
                "total_gb": round(snapshot.ram_metrics.ram_total / 1024, 2),
                "used_gb": round(snapshot.ram_metrics.ram_used / 1024, 2),
                "percent": snapshot.ram_metrics.ram_percent,
                "free_gb": round(snapshot.ram_metrics.ram_free / 1024, 2),
                "swap_percent": snapshot.ram_metrics.swap_percent,
            }
        else:
            data["ram"] = None

        # GPU 数据
        if snapshot.gpu_metrics:
            gpu = snapshot.gpu_metrics
            data["gpu"] = {
                "utilization": gpu.gpu_utilization,
                "vram_used_mb": gpu.vram_used,
                "vram_total_mb": gpu.vram_total,
                "vram_used_gb": round(gpu.vram_used / 1024, 2),
                "vram_total_gb": round(gpu.vram_total / 1024, 2),
                "vram_percent": gpu.vram_percent,
                "temperature": gpu.temperature,
                "device_name": gpu.device_name or "Unknown GPU",
                "device_id": gpu.device_id,
                "power_usage_w": gpu.power_usage,
                "clock_speed_mhz": gpu.clock_speed,
            }
        else:
            data["gpu"] = None

        # 功耗数据（如果有）
        if snapshot.power_metrics:
            power = snapshot.power_metrics
            data["power"] = {
                "current_power_w": power.current_power,
                "limit_power_w": power.limit_power,
                "average_power_w": power.average_power,
                "power_percent": power.power_percent,
            }
        else:
            data["power"] = None

        return web.json_response(data)

    except Exception as e:
        # 异常安全：任何错误都不会导致崩溃
        print(f"[飞雪监测器] ⚠️ API 错误: {e}")
        import traceback
        print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")

        return web.json_response({
            "error": str(e),
            "message": "Internal server error while collecting snapshot",
            "timestamp": _time.time(),
            "status": "error"
        }, status=500)


@PromptServer.instance.routes.get('/feixue_monitor/status')
async def handle_status(request):
    """
    处理 /feixue_monitor/status 请求

    返回监控服务的健康状态。

    Args:
        request: aiohttp 请求对象

    Returns:
        JSON Response: 服务状态信息
    """
    try:
        if _monitor is None or not _monitor.is_running:
            return web.json_response({
                "status": "unavailable",
                "running": False,
                "uptime_seconds": 0,
                "version": __version__,
                "message": "Monitor service is not running"
            })

        # 获取详细状态
        status_info = _monitor.status

        return web.json_response({
            "status": "running",
            "running": True,
            "uptime_seconds": round(_monitor.uptime, 2),
            "version": __version__,
            "config": status_info.get('config', {}),
            "gpu_provider": status_info.get('gpu_provider'),
            "collectors_count": len(status_info.get('collectors', {})),
            "last_error": status_info.get('last_error'),
            "message": "Monitor service is operational"
        })

    except Exception as e:
        return web.json_response({
            "status": "error",
            "error": str(e),
            "version": __version__
        }, status=500)


@PromptServer.instance.routes.post('/feixue_monitor/free_memory')
async def handle_free_memory(request):
    """
    处理 /feixue_monitor/free_memory 请求

    支持两种清理模式：
    - 'ram': 仅整理 RAM（gc.collect + Linux malloc_trim），不触碰 ComfyUI 模型/缓存。
    - 'deep': 深度清理，通过 ComfyUI PromptServer 设置队列标志，让 ComfyUI 在安全时机卸载模型并释放显存，再 gc.collect。

    请求体 JSON 示例：{"mode": "ram"}

    Args:
        request: aiohttp 请求对象

    Returns:
        JSON Response: 清理结果字典
    """
    try:
        if free_memory is None:
            return web.json_response({
                "success": False,
                "error": "Memory cleaner not available",
                "message": "Memory cleaner module failed to load",
            }, status=503)

        # 读取请求体，解析 mode（默认 'ram'）
        mode = "ram"
        try:
            body = await request.json()
            if isinstance(body, dict):
                mode = str(body.get("mode", "ram")).strip().lower()
        except Exception:
            mode = "ram"

        if mode not in ("ram", "deep"):
            return web.json_response({
                "success": False,
                "error": "Invalid mode",
                "message": f"mode 必须是 'ram' 或 'deep'，收到: {mode}",
            }, status=400)

        result = free_memory(mode=mode)
        status = 200 if result.get("success") else 500
        return web.json_response(result, status=status)

    except Exception as e:
        print(f"[飞雪监测器] ⚠️ free_memory API 未捕获异常: {e}")
        import traceback
        print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")

        return web.json_response({
            "success": False,
            "error": str(e),
            "message": "Unexpected error during memory cleanup",
        }, status=500)


@PromptServer.instance.routes.get('/feixue_monitor/queue_status')
async def handle_queue_status(request):
    """
    处理 /feixue_monitor/queue_status 请求

    返回 ComfyUI 当前队列状态，便于前端判断是否可以安全触发自动清理。

    Args:
        request: aiohttp 请求对象

    Returns:
        JSON Response: { "exec_info": { "queue_remaining": int } }
    """
    try:
        prompt_server = PromptServer.instance
        queue_info = prompt_server.get_queue_info()

        return web.json_response({
            "status": "ok",
            "queue_remaining": queue_info.get("exec_info", {}).get("queue_remaining", 0),
            "exec_info": queue_info.get("exec_info", {}),
            "timestamp": _time.time(),
        })

    except Exception as e:
        print(f"[飞雪监测器] ⚠️ queue_status API 错误: {e}")
        import traceback
        print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")

        return web.json_response({
            "status": "error",
            "error": str(e),
            "queue_remaining": None,
            "message": "Failed to get queue status",
        }, status=500)


print("[飞雪监测器] ✅ HTTP API 路由已注册 (ComfyUI 标准装饰器方式):")
print("    GET  /feixue_monitor/snapshot    - 获取监控数据")
print("    GET  /feixue_monitor/status      - 获取服务状态")
print("    GET  /feixue_monitor/queue_status- 获取队列状态")
print("    POST /feixue_monitor/free_memory - 执行内存清理")


# ============================================================================
# WebSocket 实时推送服务 (Task: HTTP轮询 -> WebSocket升级)
# ============================================================================
# 使用 ComfyUI 原生 WebSocket 推送机制（send_sync）
# 参考 ComfyUI-Crystools 的 CMonitor.MonitorLoop() 实现
# ============================================================================

_monitor_service = None

try:
    from core.websocket_service import FeixueMonitorService, get_monitor_service

    # 创建全局 WebSocket 监控服务实例
    _monitor_service = get_monitor_service()

    if _monitor_service:
        print("[飞雪监测器] ✅ WebSocket监控服务实例已创建")
        print(f"[飞雪监测器]    默认刷新率: {_monitor_service.rate}s")

        # 异步启动监控循环
        # 使用 asyncio.create_task 在后台运行，不阻塞主线程
        async def _start_websocket_monitor():
            """异步启动 WebSocket 监控循环"""
            try:
                await _monitor_service.start_monitor_loop()
            except Exception as e:
                print(f"[飞雪监测器] ⚠️ WebSocket监控循环异常退出: {e}")

        # 获取当前事件循环（优先运行中的循环，避免弃用警告）
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop_policy().get_event_loop()

        # 创建后台任务
        monitor_task = loop.create_task(_start_websocket_monitor())
        _monitor_service._monitor_task = monitor_task  # 保存任务引用用于停止

        print("[飞雪监测器] ✅ WebSocket监控服务已启动（后台异步运行）")
        print(f"[飞雪监测器]    推送事件类型: 'feixue.monitor'")
        print(f"[飞雪监测器]    刷新率范围: {_monitor_service.MIN_RATE}s - {_monitor_service.MAX_RATE}s")
        print(f"[飞雪监测器]    数据源: FeixueHardwareInfo.get_snapshot()")

except ImportError as e:
    print(f"[飞雪监测器] ⚠️ WebSocket服务模块导入失败: {e}")
    print("[飞雪监测器]    将仅使用HTTP API模式")
    _monitor_service = None
except Exception as e:
    print(f"[飞雪监测器] ⚠️ WebSocket服务启动失败（非致命）: {e}")
    import traceback
    print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
    _monitor_service = None


# ============================================================================
# WebSocket 服务控制 API 端点
# ============================================================================

@PromptServer.instance.routes.get('/feixue_monitor/rate')
async def handle_rate(request):
    """
    处理 /feixue_monitor/rate 请求

    支持两种模式：
    - GET（无参数）：返回当前刷新率
    - GET?rate=X.X：设置新的刷新率

    Args:
        request: aiohttp 请求对象

    Returns:
        JSON Response: 当前/新设置的刷新率信息
    """
    try:
        params = request.rel_url.query

        if 'rate' in params:
            # 设置新模式
            if _monitor_service is None:
                return web.json_response({
                    "error": "WebSocket service not available",
                    "message": "Monitor service is not running",
                    "status": "unavailable"
                }, status=503)

            try:
                new_rate = float(params['rate'])
            except ValueError:
                return web.json_response({
                    "error": "Invalid rate value",
                    "message": "Rate must be a float number",
                    "status": "error"
                }, status=400)

            # API 层边界校验：限制在合理范围 0.1-60 秒，并排除 NaN/inf
            if not math.isfinite(new_rate) or new_rate < 0.1 or new_rate > 60.0:
                print(
                    f"[飞雪监测器] 请求的刷新率 {new_rate}s 超出 API 允许范围，"
                    f"已钳位到 [0.1, 60.0]"
                )
            new_rate = max(0.1, min(new_rate, 60.0))

            # 调用服务设置方法（会自动钳位到服务自身的合法范围）
            actual_rate = _monitor_service.set_rate(new_rate)

            return web.json_response({
                "status": "ok",
                "action": "set",
                "requested_rate": new_rate,
                "actual_rate": actual_rate,
                "frequency_hz": round(1 / actual_rate, 2),
                "message": f"Refresh rate set to {actual_rate}s ({1/actual_rate:.1f} Hz)"
            })

        else:
            # 查询模式：返回当前刷新率和统计信息
            if _monitor_service is None:
                return web.json_response({
                    "status": "unavailable",
                    "running": False,
                    "current_rate": None,
                    "message": "WebSocket service not available"
                }, status=503)

            stats = _monitor_service.stats

            return web.json_response({
                "status": "running" if _monitor_service.is_running else "stopped",
                "running": _monitor_service.is_running,
                "current_rate": _monitor_service.rate,
                "frequency_hz": round(1 / _monitor_service.rate, 2),
                "min_rate": _monitor_service.MIN_RATE,
                "max_rate": _monitor_service.MAX_RATE,
                "stats": {
                    "total_pushes": stats['total_pushes'],
                    "successful_pushes": stats['successful_pushes'],
                    "failed_pushes": stats['failed_pushes'],
                    "success_rate": stats['success_rate'],
                    "uptime_seconds": stats['uptime_seconds'],
                },
                "message": f"Current rate: {_monitor_service.rate}s"
            })

    except Exception as e:
        print(f"[飞雪监测器] ⚠️ Rate API 错误: {e}")
        import traceback
        print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")

        return web.json_response({
            "error": str(e),
            "message": "Internal server error",
            "status": "error"
        }, status=500)


@PromptServer.instance.routes.get('/feixue_monitor/ws_status')
async def handle_ws_status(request):
    """
    处理 /feixue_monitor/ws_status 请求

    返回 WebSocket 服务的详细状态和统计信息。

    Args:
        request: aiohttp 请求对象

    Returns:
        JSON Response: WebSocket 服务状态
    """
    try:
        if _monitor_service is None:
            return web.json_response({
                "status": "unavailable",
                "service_exists": False,
                "version": __version__,
                "message": "WebSocket service not initialized"
            })

        # 获取完整统计信息
        stats = _monitor_service.stats

        return web.json_response({
            "status": "running" if _monitor_service.is_running else "stopped",
            "service_exists": True,
            "is_running": _monitor_service.is_running,
            "version": __version__,
            "config": {
                "current_rate": _monitor_service.rate,
                "frequency_hz": round(1 / _monitor_service.rate, 2),
                "min_rate": _monitor_service.MIN_RATE,
                "max_rate": _monitor_service.MAX_RATE,
            },
            "performance": {
                "total_pushes": stats['total_pushes'],
                "successful_pushes": stats['successful_pushes'],
                "failed_pushes": stats['failed_pushes'],
                "errors": stats['errors'],
                "success_rate_percent": stats['success_rate'],
                "uptime_seconds": stats['uptime_seconds'],
                "last_push_time": stats['last_push_time'],
            },
            "data_source": "FeixueHardwareInfo.get_snapshot()",
            "push_event_type": "feixue.monitor",
            "message": "WebSocket service operational" if _monitor_service.is_running else "WebSocket service stopped"
        })

    except Exception as e:
        return web.json_response({
            "status": "error",
            "error": str(e),
            "version": __version__
        }, status=500)


print("\n[飞雪监测器] ✅ WebSocket API 路由已注册:")
if _monitor_service:
    print("    GET /feixue_monitor/rate      - 获取/设置刷新率")
    print("    GET /feixue_monitor/ws_status  - 获取WebSocket服务状态")
else:
    print("    ⚠️ WebSocket服务未启用（将使用HTTP降级模式）")

print("\n[飞雪监测器] 📡 完整API列表:")
print("    GET  /feixue_monitor/snapshot    - 获取监控数据（HTTP降级）")
print("    GET  /feixue_monitor/status      - 获取后端服务状态")
print("    GET  /feixue_monitor/queue_status- 获取队列状态")
print("    POST /feixue_monitor/free_memory - 执行内存清理")
if _monitor_service:
    print("    GET /feixue_monitor/rate         - 获取/设置刷新率")
    print("    GET /feixue_monitor/ws_status    - WebSocket服务状态")
print("    🌐 WebSocket: feixue.monitor 事件（实时推送）")

