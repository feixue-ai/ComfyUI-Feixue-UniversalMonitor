"""
ComfyUI-Feixue-UniversalMonitor - 飞雪通用监测器 V2.5
====================================================

✨ 世界顶级胶囊UI系统（极简/科技/玻璃态三套方案）
🎯 实时GPU/CPU/内存监控 + Cyberpunk风格面板
🔧 AMD/NVIDIA双GPU支持 + PRED智能预测系统
💫 ComfyUI Manager一键安装兼容

功能：
- 实时监测 ComfyUI 工作流执行状态
- 三套世界级UI方案可切换（极简主义/赛博朋克/玻璃态）
- 毛玻璃顶部菜单栏 + 实时FPS监控
- 实时GPU/CPU/内存监控（后端服务）
- AMD GPU三级Fallback策略（amdsmi → rocm_smi_lib → sysfs）

作者: Feixue (飞雪)
版本: 2.5.0 (World-Class Capsule UI)
"""

__version__ = "2.5.0"
__author__ = "Feixue (飞雪)"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./web"

print("[飞雪监测器] ✅ 插件加载完成 (V2.5 World-Class Capsule UI)")

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
        gpu_info = "None"
        if hasattr(_monitor, '_gpu_provider') and _monitor._gpu_provider:
            gpu_info = f"{_monitor._gpu_provider.name} ({_monitor._gpu_provider.get_device_name(0)})"
        
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

from aiohttp import web
from server import PromptServer
import time as _time


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

        # 将 MonitorSnapshot 转换为前端友好的 JSON 格式
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

        # 预测数据（如果有）
        if snapshot.prediction:
            pred = snapshot.prediction
            data["prediction"] = {
                "success_rate": pred.success_rate,
                "risk_level": pred.risk_level,
                "peak_vram_estimate_mb": pred.peak_vram_estimate,
                "confidence": pred.confidence,
                "recommendations": pred.recommendations,
            }
        else:
            data["prediction"] = None

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


print("[飞雪监测器] ✅ HTTP API 路由已注册 (ComfyUI 标准装饰器方式):")
print("    GET /feixue_monitor/snapshot - 获取监控数据")
print("    GET /feixue_monitor/status   - 获取服务状态")

