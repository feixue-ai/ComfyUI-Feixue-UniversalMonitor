"""
ComfyUI-Feixue-UniversalMonitor - 飞雪通用监测器
============================================

功能：
- 实时监测 ComfyUI 工作流执行状态
- Premium UI 5 色 × 5 风格悬浮监控栏
- 实时 GPU/CPU/内存监控（后端服务）
- WebSocket / HTTP 双通道实时数据推送

作者: Feixue Team
版本: 3.40.10 (Linux AMD SMI Native Bridge)
"""

__version__ = "3.40.10"
__author__ = "Feixue Team"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./web"

print("[飞雪监测器] ✅ 插件加载完成 (v3.40.10 Linux AMD SMI 原生 Bridge)")
print("[飞雪监测器] 🙋 欢迎开发者参与维护，详见 MAINTAINER_GUIDE.md / README.md")

# ============================================================================
# 获取插件根目录并防止 core 包被其他插件 shadow
# ============================================================================
import os
import sys

_FEIXUE_ROOT = os.path.dirname(os.path.abspath(__file__))

# ComfyUI 多个 custom node 共用 sys.path，其他插件（如 comfyui_workflow_assistant）
# 也有 core 包，会 shadow 我们的 core。启动前清理非本插件的 core 缓存，
# 并把本插件根目录放到 sys.path 最前面，确保 from core.xxx 一定解析到我们的模块。
_core_prefixes = {'core', 'core.'}
for _mod_name in list(sys.modules.keys()):
    if _mod_name in _core_prefixes or _mod_name.startswith('core.'):
        _mod = sys.modules.get(_mod_name)
        if _mod is not None:
            _mod_file = getattr(_mod, '__file__', None)
            if _mod_file is None or not _mod_file.startswith(_FEIXUE_ROOT + os.sep):
                del sys.modules[_mod_name]

if _FEIXUE_ROOT in sys.path:
    sys.path.remove(_FEIXUE_ROOT)
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
        gpu_source = _monitor.status.get('gpu_source') or 'none'
        device_count = _monitor.status.get('device_count', 0)
        gpu_available = _monitor.status.get('gpu_available', False)

        print(f"[飞雪监测器] ✅ 后端监控已启动")
        print(f"[飞雪监测器]    - CPU/RAM采集器: 运行中")
        print(f"[飞雪监测器]    - GPU数据源: {gpu_source} (可用: {gpu_available}, 设备数: {device_count})")
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
# DIAG 诊断引擎初始化
# ============================================================================

_diag_engine = None
_last_diag_report = None

try:
    from core.diagnoser import DiagEngine

    _diag_engine = DiagEngine()
    print(f"[飞雪监测器] ✅ DIAG 诊断引擎已初始化 (词库版本: {_diag_engine.version})")
except Exception as _diag_engine_init_err:
    print(f"[飞雪监测器] ⚠️ DIAG 诊断引擎初始化失败（非致命）: {_diag_engine_init_err}")
    import traceback

    print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
    _diag_engine = None


# ============================================================================
# 公共 API：供其他模块或前端获取监控数据
# ============================================================================

def get_monitor():
    """获取监控实例"""
    return _monitor


def get_monitor_status():
    """获取监控状态（供前端状态查询）"""
    if _monitor is None:
        return {'running': False, 'error': 'monitor not initialized'}
    return _monitor.status


def get_snapshot():
    """获取最新的系统监控快照"""
    if _monitor is None:
        return None
    try:
        return _monitor.get_snapshot()
    except Exception:
        return None


# ============================================================================
# HTTP API 端点 - 为前端提供数据访问接口
# 使用 ComfyUI 标准方式：@PromptServer.instance.routes 装饰器
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


# ============================================================================
# 禁止浏览器缓存本插件前端脚本，确保 extension.js 每次都能加载最新版本
# ============================================================================

@web.middleware
async def _feixue_no_cache_middleware(request, handler):
    """为 extension.js / extension.core.js 等前端脚本添加无缓存响应头。"""
    response = await handler(request)
    try:
        path = request.path or ""
        if path.endswith("extension.js") or path.endswith("extension.core.js"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers.pop("Expires", None)
            response.headers["Expires"] = "0"
    except Exception:
        # 响应头设置失败不应影响正常请求
        pass
    return response


try:
    _fxm_app = getattr(PromptServer, "instance", None)
    _fxm_app = getattr(_fxm_app, "app", None) if _fxm_app is not None else None
    if _fxm_app is not None:
        # 避免重复注册
        if not any(
            getattr(m, "__name__", None) == _feixue_no_cache_middleware.__name__
            for m in _fxm_app.middlewares
        ):
            _fxm_app.middlewares.append(_feixue_no_cache_middleware)
            print("[飞雪监测器] ✅ 已禁用 extension.js 浏览器缓存")
except Exception as _fxm_middleware_err:
    print(f"[飞雪监测器] ⚠️ 禁用缓存中间件注册失败（非致命）: {_fxm_middleware_err}")


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


# ============================================================================
# 手动诊断模式 C：环境健康检查 API
# ============================================================================

try:
    from core.health_check import health_check as _run_health_check

    @PromptServer.instance.routes.post('/feixue_monitor/diag/health')
    async def handle_diag_health(request):
        """
        触发环境健康检查。

        请求体（可选）:
            {
                "workflow": { ... },            # 当前工作流 JSON，用于节点缺失检查
                "language": "zh"                # 报告语言，默认 "zh"
                "extra_missing_types": [...]    # 前端收集的缺失节点/节点包名列表
                "scope": "workflow"             # "workflow" | "environment" | "full"
            }

        返回:
            HealthReport JSON（category="health_check"）
        """
        try:
            workflow = None
            language = "zh"
            extra_missing_types = None
            scope = None
            try:
                body = await request.json()
                if isinstance(body, dict):
                    workflow = body.get("workflow")
                    lang = body.get("language") or body.get("client_language")
                    if isinstance(lang, str) and lang:
                        language = lang.strip().lower()
                    extra = body.get("extra_missing_types")
                    if isinstance(extra, list):
                        extra_missing_types = [
                            str(x).strip() for x in extra
                            if isinstance(x, str) and str(x).strip()
                        ]
                    scope = body.get("scope")
                    if isinstance(scope, str) and scope:
                        scope = scope.strip().lower()
            except Exception:
                pass

            loop = asyncio.get_event_loop()
            report = await loop.run_in_executor(
                None,
                lambda: _run_health_check(
                    workflow=workflow,
                    language=language,
                    extra_missing_types=extra_missing_types,
                    scope=scope,
                ),
            )
            global _last_diag_report
            _last_diag_report = report.to_dict()
            return web.json_response(_last_diag_report)
        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/health API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to run health check",
            }, status=500)

    _HEALTH_API_AVAILABLE = True
except Exception as _health_check_import_err:
    print(f"[飞雪监测器] ⚠️ 健康检查模块导入失败: {_health_check_import_err}")
    _HEALTH_API_AVAILABLE = False


# ============================================================================
# 手动诊断模式 A：当前工作流报错诊断 API
# ============================================================================

try:
    from core.diagnoser import DiagEngine

    try:
        from core.websocket_service import get_last_execution_error as _get_last_execution_error
        from core.websocket_service import get_last_diag_report as _get_last_diag_report
    except Exception:
        _get_last_execution_error = None  # type: ignore
        _get_last_diag_report = None  # type: ignore

    @PromptServer.instance.routes.post('/feixue_monitor/diag/text')
    async def handle_diag_text(request):
        """
        对用户粘贴的任意报错文本进行词库匹配诊断（支持英文/中文/混合文本）。

        请求体 JSON:
            {
                "text": "CUDA out of memory ...",
                "system_snapshot": { ... }   // 可选，默认使用当前监控快照
                "language": "zh"              // 可选，报告语言，默认自动检测
            }

        返回:
            DiagReport JSON（统一报告结构）
        """
        try:
            body = {}
            try:
                body = await request.json()
                if not isinstance(body, dict):
                    body = {}
            except Exception:
                body = {}

            text = body.get("text")
            if not isinstance(text, str) or not text.strip():
                return web.json_response({
                    "status": "error",
                    "error": "Missing or empty 'text' field",
                    "message": "请求体必须包含非空的 'text' 字段（支持英文、中文或混合报错文本）",
                }, status=400)

            # 优先使用请求传入的系统快照，否则回退到当前监控快照
            system_snapshot = body.get("system_snapshot")
            if not isinstance(system_snapshot, dict):
                system_snapshot = get_snapshot() or {}

            # 语言偏好：显式 language 优先，client_language 次之
            language = body.get("language") or body.get("client_language")
            if isinstance(language, str) and language:
                language = language.strip().lower()
                system_snapshot["client_language"] = language

            if _diag_engine is None:
                return web.json_response({
                    "status": "error",
                    "error": "DIAG engine not initialized",
                    "message": "DIAG 引擎未初始化",
                }, status=503)

            global _last_diag_report
            report = _diag_engine.diagnose_text(text, system_snapshot, language=language)
            _last_diag_report = report.to_dict()
            return web.json_response(_last_diag_report)

        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/text API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to diagnose text",
            }, status=500)

    @PromptServer.instance.routes.get('/feixue_monitor/diag/last_error')
    async def handle_diag_last_error(request):
        """
        对最近一次缓存的 ComfyUI execution_error 事件进行诊断并返回统一报告。

        返回:
            DiagReport JSON（统一报告结构）
        """
        try:
            last_error = None
            if _get_last_execution_error is not None:
                last_error = _get_last_execution_error()

            if last_error is None:
                # 无报错时返回一个状态为 ok 的统一结构
                return web.json_response({
                    "status": "ok",
                    "severity": "ok",
                    "category": "unknown",
                    "category_label": "无报错",
                    "title": "暂无最近报错",
                    "explanation": "当前没有缓存的 ComfyUI 报错，请先运行一次工作流。",
                    "suggestions": [],
                    "raw_error": "",
                    "error_node": None,
                    "language": "zh",
                    "timestamp": _time.time(),
                    "system_context": {},
                    "matched": False,
                    "node_info": {},
                    "message": "暂无最近报错，请先运行一次工作流",
                })

            if _diag_engine is None:
                return web.json_response({
                    "status": "error",
                    "error": "DIAG engine not initialized",
                    "message": "DIAG 引擎未初始化",
                }, status=503)

            global _last_diag_report
            system_snapshot = get_snapshot() or {}
            report = _diag_engine.diagnose(last_error, system_snapshot)
            _last_diag_report = report.to_dict()
            # 同时返回原始 error，方便前端做二次处理或展示
            return web.json_response({
                "has_error": True,
                "error": last_error,
                "report": _last_diag_report,
            })

        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/last_error API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to get last execution error",
            }, status=500)

    _DIAG_TEXT_API_AVAILABLE = True
except Exception as _diag_text_import_err:
    print(f"[飞雪监测器] ⚠️ 诊断文本模块导入失败: {_diag_text_import_err}")
    _DIAG_TEXT_API_AVAILABLE = False


# ============================================================================
# 手动诊断模式 B：崩溃/黑屏/掉驱动诊断 API
# ============================================================================

try:
    from core.log_reader import LogReader

    @PromptServer.instance.routes.post('/feixue_monitor/diag/crash')
    async def handle_diag_crash(request):
        """
        触发崩溃/黑屏/掉驱动诊断。

        按平台读取系统日志（Linux dmesg / Windows Event Log / macOS kernel log），
        结合监控快照趋势生成 DiagReport。无权限时自动降级为仅快照分析。

        请求体 JSON（可选）:
            { "language": "zh" }  # 报告语言，默认自动检测

        返回:
            DiagReport JSON（category="crash"）
        """
        try:
            body = {}
            try:
                body = await request.json()
                if not isinstance(body, dict):
                    body = {}
            except Exception:
                body = {}

            language = body.get("language") or body.get("client_language")
            loop = asyncio.get_event_loop()
            reader = LogReader(language=language)
            report = await loop.run_in_executor(
                None,
                reader.manual_diagnose_crash,
            )
            global _last_diag_report
            _last_diag_report = report.to_dict()
            return web.json_response(_last_diag_report)
        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/crash API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to run crash diagnosis",
            }, status=500)

    _CRASH_API_AVAILABLE = True
except Exception as _crash_check_import_err:
    print(f"[飞雪监测器] ⚠️ 崩溃诊断模块导入失败: {_crash_check_import_err}")
    _CRASH_API_AVAILABLE = False


def _get_current_diag_report():
    """获取最近一次诊断报告（自动诊断与手动诊断中取时间戳最新者）。"""
    auto_report = _get_last_diag_report() if _get_last_diag_report is not None else None
    manual_report = _last_diag_report
    if auto_report is None:
        return manual_report
    if manual_report is None:
        return auto_report
    return (
        auto_report
        if auto_report.get("timestamp", 0) >= manual_report.get("timestamp", 0)
        else manual_report
    )


# ============================================================================
# DIAG 状态与配置 API
# ============================================================================

try:
    from config.config_manager import get_config_manager
    from core.websocket_service import is_diag_hook_installed

    @PromptServer.instance.routes.get('/feixue_monitor/diag/status')
    async def handle_diag_status(request):
        """
        获取当前 DIAG 诊断状态。

        返回 DIAG 开关状态、通知方式、词库版本、最近一次诊断报告以及最近缓存的报错。
        """
        try:
            cfg = get_config_manager()
            enabled = bool(cfg.get("diag.enabled", True))
            notification = cfg.get("diag.notification", ["panel"])
            if not isinstance(notification, list):
                notification = ["panel"]

            if _diag_engine is None:
                return web.json_response({
                    "status": "unavailable",
                    "enabled": False,
                    "notification": notification,
                    "diag": {"enabled": enabled, "notification": notification},
                    "error_dict_version": None,
                    "has_report": False,
                    "report": None,
                    "last_error": None,
                    "hook_installed": is_diag_hook_installed(),
                    "message": "DIAG engine not initialized",
                }, status=503)

            last_error = None
            if _get_last_execution_error is not None:
                last_error = _get_last_execution_error()

            report = _get_current_diag_report()
            last_auto_report = _get_last_diag_report() if _get_last_diag_report is not None else None

            return web.json_response({
                "status": "ok" if enabled else "disabled",
                "enabled": enabled,
                "notification": notification,
                "diag": {"enabled": enabled, "notification": notification},
                "error_dict_version": _diag_engine.version,
                "has_report": report is not None,
                "report": report,
                "last_auto_report": last_auto_report,
                "last_error": last_error,
                "hook_installed": is_diag_hook_installed(),
                "timestamp": _time.time(),
                "message": "DIAG engine is ready" if enabled else "DIAG is disabled",
            })
        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/status API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to get DIAG status",
            }, status=500)

    @PromptServer.instance.routes.post('/feixue_monitor/diag/config')
    async def handle_diag_config(request):
        """
        更新 DIAG 配置。

        请求体 JSON 支持两种格式：
            { "enabled": false, "notification": ["panel"] }
        或
            { "diag": { "enabled": false, ... } }

        仅接受已知的 DIAG 配置项，其他字段会被忽略。
        """
        try:
            body = {}
            try:
                body = await request.json()
                if not isinstance(body, dict):
                    body = {}
            except Exception:
                body = {}

            diag_cfg = body.get("diag") if isinstance(body.get("diag"), dict) else body
            if not isinstance(diag_cfg, dict):
                return web.json_response({
                    "status": "error",
                    "error": "Invalid request body",
                    "message": "请求体必须是包含 DIAG 配置项的 JSON 对象",
                }, status=400)

            known_keys = {
                "enabled",
                "notification",
                "error_dict_version",
                "snapshot_ring_path",
                "snapshot_ring_max_entries",
            }

            cfg = get_config_manager()
            updated = {}
            rejected = []
            for key, value in diag_cfg.items():
                if key not in known_keys:
                    continue
                full_key = f"diag.{key}"
                if not cfg._validate_type(full_key, value):
                    rejected.append(key)
                    continue
                cfg.set(full_key, value)
                updated[key] = value

            if rejected:
                return web.json_response({
                    "status": "error",
                    "error": "Invalid config value type",
                    "rejected_keys": rejected,
                    "message": "部分 DIAG 配置项类型校验失败",
                }, status=400)

            if not updated and diag_cfg:
                return web.json_response({
                    "status": "error",
                    "error": "No valid DIAG config keys",
                    "message": "未提供有效的 DIAG 配置项",
                }, status=400)

            cfg.save()

            # DIAG WebSocket 钩子始终安装用于缓存真实报错；
            # enabled 开关仅控制是否自动向前端推送 feixue.diag 报告，
            # 因此关闭开关时也不应卸载钩子，否则用户手动点击"诊断最近报错"
            # 将无法打捞到 ComfyUI 的 execution_error。
            if "enabled" in updated and updated["enabled"]:
                try:
                    from core.websocket_service import install_diag_websocket_hook
                    install_diag_websocket_hook()
                except Exception as _diag_hook_err:
                    print(f"[飞雪监测器] ⚠️ DIAG WebSocket 钩子安装失败: {_diag_hook_err}")
                    import traceback
                    print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")

            return web.json_response({
                "status": "ok",
                "updated": updated,
                "diag": cfg.get("diag"),
                "hook_installed": is_diag_hook_installed(),
                "message": "DIAG configuration saved",
            })
        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/config API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to save DIAG config",
            }, status=500)

    @PromptServer.instance.routes.get('/feixue_monitor/diag/error_dict_version')
    async def handle_diag_error_dict_version(request):
        """
        获取当前 DIAG 错误词库版本号。
        """
        try:
            if _diag_engine is None:
                return web.json_response({
                    "status": "unavailable",
                    "version": None,
                    "error_dict_version": None,
                    "message": "DIAG engine not initialized",
                }, status=503)

            version = _diag_engine.version
            return web.json_response({
                "status": "ok",
                "version": version,
                "error_dict_version": version,
                "message": "Error dictionary version retrieved",
            })
        except Exception as e:
            print(f"[飞雪监测器] ⚠️ diag/error_dict_version API 错误: {e}")
            import traceback
            print(f"[飞雪监测器]    详细错误: {traceback.format_exc()}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "message": "Failed to get error dictionary version",
            }, status=500)

    _DIAG_STATUS_API_AVAILABLE = True
except Exception as _diag_status_import_err:
    print(f"[飞雪监测器] ⚠️ DIAG 状态/配置 API 导入失败: {_diag_status_import_err}")
    _DIAG_STATUS_API_AVAILABLE = False


print("[飞雪监测器] ✅ HTTP API 路由已注册 (ComfyUI 标准装饰器方式):")
print("    GET  /feixue_monitor/snapshot       - 获取监控数据")
print("    GET  /feixue_monitor/status         - 获取服务状态")
print("    GET  /feixue_monitor/queue_status   - 获取队列状态")
print("    POST /feixue_monitor/free_memory    - 执行内存清理")
if _HEALTH_API_AVAILABLE:
    print("    POST /feixue_monitor/diag/health    - 环境健康检查")
if _DIAG_TEXT_API_AVAILABLE:
    print("    POST /feixue_monitor/diag/text      - 手动诊断：报错文本诊断")
    print("    GET  /feixue_monitor/diag/last_error - 手动诊断：获取最近报错")
if _CRASH_API_AVAILABLE:
    print("    POST /feixue_monitor/diag/crash     - 手动诊断：崩溃/黑屏/掉驱动")
if _DIAG_STATUS_API_AVAILABLE:
    print("    GET  /feixue_monitor/diag/status    - DIAG 状态")
    print("    POST /feixue_monitor/diag/config    - 更新 DIAG 配置")
    print("    GET  /feixue_monitor/diag/error_dict_version - 词库版本")


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
print("    GET  /feixue_monitor/snapshot       - 获取监控数据（HTTP降级）")
print("    GET  /feixue_monitor/status         - 获取后端服务状态")
print("    GET  /feixue_monitor/queue_status   - 获取队列状态")
print("    POST /feixue_monitor/free_memory    - 执行内存清理")
if _HEALTH_API_AVAILABLE:
    print("    POST /feixue_monitor/diag/health    - 环境健康检查")
if _DIAG_TEXT_API_AVAILABLE:
    print("    POST /feixue_monitor/diag/text      - 手动诊断：报错文本诊断")
    print("    GET  /feixue_monitor/diag/last_error - 手动诊断：获取最近报错")
if _CRASH_API_AVAILABLE:
    print("    POST /feixue_monitor/diag/crash     - 手动诊断：崩溃/黑屏/掉驱动")
if _DIAG_STATUS_API_AVAILABLE:
    print("    GET  /feixue_monitor/diag/status    - DIAG 状态")
    print("    POST /feixue_monitor/diag/config    - 更新 DIAG 配置")
    print("    GET  /feixue_monitor/diag/error_dict_version - 词库版本")
if _monitor_service:
    print("    GET /feixue_monitor/rate            - 获取/设置刷新率")
    print("    GET /feixue_monitor/ws_status       - WebSocket服务状态")
print("    🌐 WebSocket: feixue.monitor 事件（实时推送）")

