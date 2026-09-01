"""
ComfyUI-Feixue-UniversalMonitor - DIAG 诊断引擎

职责：
1. 基于 core/diag_error_dict.py 中的词库，对 ComfyUI 报错进行正则匹配。
2. 根据系统 locale 自动选择翻译语言（无匹配时 fallback 英文）。
3. 结合 system_snapshot 中的 GPU 显存信息，生成差异化建议。
4. 提供 DiagReport 数据类，供 WebSocket 推送和前端展示。

设计约束：
- 诊断为纯事后分析，不预判、不轮询。
- 首次匹配时才解析对应语言的翻译与建议（懒解析）。
- CPU 占用极低，不影响 ComfyUI 主流程。

版本: 1.0.0
作者: Feixue
"""

from __future__ import annotations

import dataclasses
import locale
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .diag_error_dict import (
    DEFAULT_LANGUAGE,
    ERROR_DICT,
    ERROR_DICT_VERSION,
    SUPPORTED_LANGUAGES,
    _pick_suggestions,
)
from . import snapshot_persistence

logger = logging.getLogger(__name__)

# ============================================================================
# 数据模型
# ============================================================================

# 错误分类 -> 多语言标签（与 HealthReport 保持统一风格）
CATEGORY_LABELS: Dict[str, Dict[str, str]] = {
    "oom": {"zh": "显存不足", "en": "Out of Memory"},
    "model_missing": {"zh": "模型缺失", "en": "Model Missing"},
    "dtype_mismatch": {"zh": "数据类型不匹配", "en": "DType Mismatch"},
    "shape_mismatch": {"zh": "维度/形状不匹配", "en": "Shape Mismatch"},
    "import_error": {"zh": "导入错误", "en": "Import Error"},
    "device_mismatch": {"zh": "设备不匹配", "en": "Device Mismatch"},
    "node_not_found": {"zh": "节点缺失", "en": "Node Not Found"},
    "connection_error": {"zh": "连接错误", "en": "Connection Error"},
    "workflow_validation": {"zh": "工作流校验", "en": "Workflow Validation"},
    "execution_error": {"zh": "执行错误", "en": "Execution Error"},
    "runtime_error": {"zh": "运行时错误", "en": "Runtime Error"},
    "unknown": {"zh": "未识别错误", "en": "Unknown Error"},
    "health_check": {"zh": "环境健康检查", "en": "Health Check"},
    "crash": {"zh": "崩溃/黑屏/掉驱动", "en": "Crash / Black Screen / Driver Lost"},
}


@dataclasses.dataclass
class DiagReport:
    """诊断报告数据类。

    统一字段设计，让前端能清晰展示"错误节点、错误类型、说明、建议"。
    同时保留少量旧字段（matched / node_info）以兼顾向后兼容。

    Attributes:
        error_node: 报错节点信息 {node_id, node_type, display_title} 或 null
        category: 错误分类英文键
        category_label: 错误分类翻译标签
        title: 翻译后的错误标题
        explanation: 翻译后的详细说明
        suggestions: 按优先级排序的建议列表（字符串）
        raw_error: 原始报错文本
        status: 报告状态 "ok" | "error" | "warning"
        severity: 严重程度 "ok" | "error" | "warning"
        language: 报告语言代码
        timestamp: 诊断时间戳
        system_context: 精简系统快照
        matched: 是否匹配到已知错误（向后兼容）
        node_info: 原始节点信息（向后兼容）
        source: 报告来源，用于前端区分 backend_execution_error / manual_text / frontend_graph / health_check
    """

    error_node: Optional[Dict[str, Any]] = None
    category: str = "unknown"
    category_label: str = ""
    title: str = ""
    explanation: str = ""
    suggestions: List[str] = dataclasses.field(default_factory=list)
    raw_error: str = ""
    status: str = "ok"
    severity: str = "ok"
    language: str = "en"
    timestamp: float = 0.0
    system_context: Dict[str, Any] = dataclasses.field(default_factory=dict)
    matched: bool = False
    node_info: Dict[str, Any] = dataclasses.field(default_factory=dict)
    source: str = "backend_execution_error"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，便于 JSON 序列化。"""
        return dataclasses.asdict(self)


# ============================================================================
# 工具函数
# ============================================================================


def _detect_language() -> str:
    """根据系统 locale 自动检测语言，无匹配时 fallback 英文。

    注意：浏览器语言由前端通过 API 传入 system_snapshot 中的
    `client_language` 字段覆盖，本函数仅在未提供时兜底使用。
    """
    loc: Optional[str] = None
    try:
        loc = locale.getlocale()[0]
        if not loc:
            loc = locale.getdefaultlocale()[0]
    except Exception:
        pass

    if loc:
        loc_norm = loc.lower().replace("_", "-")
        for lang in SUPPORTED_LANGUAGES:
            if loc_norm.startswith(lang):
                return lang
        # 中文变体统一归到 zh
        if loc_norm.startswith("zh"):
            return "zh"

    return DEFAULT_LANGUAGE


def _extract_client_language(snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
    """从系统快照中提取前端传入的客户端语言。"""
    if not snapshot:
        return None
    # 优先使用前端传入的 client_language
    client_lang = snapshot.get("client_language")
    if isinstance(client_lang, str) and client_lang:
        return client_lang.split("-")[0].lower()
    return None


def _resolve_language(
    snapshot: Optional[Dict[str, Any]],
    language: Optional[str] = None,
) -> str:
    """确定报告语言。

    优先级：
    1. 调用方显式传入的 language
    2. system_snapshot 中的 client_language（前端传入）
    3. 系统 locale 兜底
    4. 默认语言 fallback
    """
    # 1. 显式 language 优先
    if isinstance(language, str) and language:
        lang_norm = language.split("-")[0].lower()
        if lang_norm in SUPPORTED_LANGUAGES:
            return lang_norm
        if lang_norm.startswith("zh"):
            return "zh"

    # 2. 前端传入的 client_language
    client_lang = _extract_client_language(snapshot)
    if client_lang and client_lang in SUPPORTED_LANGUAGES:
        return client_lang
    if client_lang and client_lang.startswith("zh"):
        return "zh"

    # 3. 系统 locale 兜底（不再作为唯一决定因素）
    return _detect_language()


def _extract_platform(snapshot: Optional[Dict[str, Any]]) -> Optional[str]:
    """从系统快照中提取平台信息，未提供时回退到 Python 运行时平台。"""
    if not snapshot:
        return None

    # 优先使用快照中的 platform 字段（由 monitor.py 或前端传入）
    platform = snapshot.get("platform")
    if isinstance(platform, str) and platform:
        return platform

    # 兼容前端可能传入的 os 字段
    os_value = snapshot.get("os")
    if isinstance(os_value, str) and os_value:
        return os_value

    return None


def _detect_runtime_platform() -> str:
    """检测当前 Python 运行时平台，返回与 platform 谓词一致的值。"""
    try:
        import platform as _platform

        system = _platform.system()
        if system == "Windows":
            return "Windows"
        if system == "Linux":
            return "Linux"
        if system == "Darwin":
            return "Darwin"
        return system
    except Exception:
        return ""


def _extract_vram_total_mb(snapshot: Optional[Dict[str, Any]]) -> Optional[int]:
    """从系统快照中提取 GPU 总显存（MB）。

    兼容两种常见结构：
    - MonitorSnapshot.to_dict(): {"gpu": {"vram_total": int, ...}}
    - 前端/websocket 简化格式: {"gpus": [{"vram_total_mb": int, ...}]}
    """
    if not snapshot:
        return None

    # 格式 1：单卡对象
    gpu = snapshot.get("gpu")
    if isinstance(gpu, dict):
        for key in ("vram_total", "vram_total_mb", "total_vram"):
            value = gpu.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)

    # 格式 2：多卡列表，取首张卡
    gpus = snapshot.get("gpus")
    if isinstance(gpus, list) and gpus:
        first = gpus[0]
        if isinstance(first, dict):
            for key in ("vram_total_mb", "vram_total", "total_vram"):
                value = first.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    return int(value)

    return None


def _extract_peak_vram_mb(
    snapshot_history: List[Dict[str, Any]],
) -> tuple[Optional[float], Optional[float]]:
    """从历史快照中提取 VRAM 使用峰值（MB）和百分比峰值。

    兼容两种常见结构：
    - MonitorSnapshot.to_dict(): {"gpu": {"vram_used": int, "vram_percent": float, ...}}
    - 前端/websocket 简化格式: {"gpus": [{"vram_used_mb": int, "vram_percent": float, ...}]}

    Args:
        snapshot_history: 历史快照列表

    Returns:
        (peak_vram_used_mb, peak_vram_percent)，无有效 GPU 数据时返回 (None, None)
    """
    peak_used: Optional[float] = None
    peak_percent: Optional[float] = None

    for snap in snapshot_history:
        if not isinstance(snap, dict):
            continue

        gpu = snap.get("gpu")
        if not isinstance(gpu, dict):
            gpus = snap.get("gpus")
            if isinstance(gpus, list) and gpus:
                gpu = gpus[0]
        if not isinstance(gpu, dict):
            continue

        used = gpu.get("vram_used_mb")
        if used is None:
            used = gpu.get("vram_used")
        if isinstance(used, (int, float)) and used >= 0:
            if peak_used is None or used > peak_used:
                peak_used = float(used)

        pct = gpu.get("vram_percent")
        if isinstance(pct, (int, float)) and pct >= 0:
            if peak_percent is None or pct > peak_percent:
                peak_percent = float(pct)

    return peak_used, peak_percent


def _compile_patterns(error_entry: Dict[str, Any]) -> List[re.Pattern[str]]:
    """将错误条目的正则字符串编译为 Pattern 对象（带缓存）。"""
    cache = getattr(_compile_patterns, "_cache", None)
    if cache is None:
        cache = {}
        setattr(_compile_patterns, "_cache", cache)

    key = id(error_entry)
    if key not in cache:
        cache[key] = [re.compile(p, re.IGNORECASE) for p in error_entry.get("patterns", [])]
    return cache[key]


def _extract_error_text(event: Dict[str, Any]) -> str:
    """从 execution_error 事件中提取用于匹配的文本（支持中文字符与 bytes 解码）。

    提取优先级：
    1. exception_message
    2. traceback 最后一行（通常是实际错误）
    3. error_type 等显式错误标记（如 DIAG 测试器节点传入）
    4. 其余字段（递归收集字符串/bytes）

    注意：跳过 current_inputs，避免普通输入字符串干扰错误模式匹配。
    """
    parts: List[str] = []

    if isinstance(event, dict):
        # 1. exception_message 优先
        msg = event.get("exception_message")
        if isinstance(msg, str) and msg:
            parts.append(msg)

        # 2. traceback 最后一行
        tb = event.get("traceback")
        if isinstance(tb, (list, tuple)) and tb:
            last_line = str(tb[-1]).strip()
            if last_line:
                parts.append(last_line)

        # 3. 显式错误类型标记（如 DIAG 测试器节点传入的 error_type），
        #    放在较前面以便词库优先识别 OOM / node_not_found 等明确分类。
        error_type = event.get("error_type")
        if isinstance(error_type, str) and error_type:
            parts.append(error_type)

        # 4. 其他字段
        def _collect_rest(value: Any) -> None:
            if isinstance(value, str) and value:
                parts.append(value)
            elif isinstance(value, bytes):
                text = value.decode("utf-8", errors="ignore")
                if text:
                    parts.append(text)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    _collect_rest(item)
            elif isinstance(value, dict):
                for v in value.values():
                    _collect_rest(v)

        for key, value in event.items():
            if key in ("exception_message", "traceback", "current_inputs", "error_type"):
                continue
            _collect_rest(value)

        return "\n".join(parts)

    # 兼容非字典输入：递归收集所有字符串
    def _collect_all(value: Any) -> None:
        if isinstance(value, str) and value:
            parts.append(value)
        elif isinstance(value, bytes):
            text = value.decode("utf-8", errors="ignore")
            if text:
                parts.append(text)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _collect_all(item)
        elif isinstance(value, dict):
            for v in value.values():
                _collect_all(v)

    _collect_all(event)
    return "\n".join(parts)


# 不可争议的 OOM 显式标记 -> 对应 error_key（优先于 connection/validation 类模式）
_EXPLICIT_OOM_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    # 英文
    (re.compile(r"CUDA out of memory", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"torch\.cuda\.OutOfMemoryError", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"CUDA error:\s*out of memory", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"RuntimeError:\s*CUDA out of memory", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"hipError_t::hipOutOfMemory", re.IGNORECASE), "rocm_oom"),
    (re.compile(r"HIP out of memory", re.IGNORECASE), "rocm_oom"),
    (re.compile(r"ROCm out of memory", re.IGNORECASE), "rocm_oom"),
    (re.compile(r"RuntimeError:\s*out of memory.*hip", re.IGNORECASE), "rocm_oom"),
    (re.compile(r"MPS out of memory", re.IGNORECASE), "mps_oom"),
    (re.compile(r"Metal out of memory", re.IGNORECASE), "mps_oom"),
    (re.compile(r"RuntimeError:\s*out of memory.*mps", re.IGNORECASE), "mps_oom"),
    # 中文 OOM（ComfyUI 中文界面常见）
    (re.compile(r"CUDA\s*[内存显存]\s*不足", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"GPU\s*[内存显存]\s*不足", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"(?:显存|内存|VRAM)\s*不足", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"尝试分配\s*[\d.]+\s*[KMGT]?i?B.*(?:可用|剩余|不足)", re.IGNORECASE), "cuda_oom"),
    (re.compile(r"PyTorch.*(?:内存|显存)\s*不足", re.IGNORECASE), "cuda_oom"),
    # 兜底：GPU 上下文下的通用 RuntimeError out of memory
    (re.compile(r"RuntimeError:\s*out of memory", re.IGNORECASE), "oom"),
]


# OOM 条目优先级：具体的 GPU 后端优先，通用 OOM 最后
_OOM_KEY_PRIORITY = ("cuda_oom", "rocm_oom", "mps_oom", "oom")


def _detect_explicit_oom(
    text: str,
    error_dict: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """若文本中包含不可争议的 OOM 标记，返回对应 OOM 词库条目。

    该检查在遍历 ERROR_DICT 之前执行，确保 CUDA/HIP/MPS OOM 等明确场景
    不会被 workflow connection / input_slot 等宽泛模式截获。
    """
    if not isinstance(text, str) or not text:
        return None

    matched_keys: Set[str] = set()
    for pattern, error_key in _EXPLICIT_OOM_PATTERNS:
        if pattern.search(text):
            matched_keys.add(error_key)

    if not matched_keys:
        return None

    chosen_key = next((key for key in _OOM_KEY_PRIORITY if key in matched_keys), "oom")
    for entry in error_dict:
        if entry.get("error_key") == chosen_key:
            return entry
    return None


def _extract_missing_node_type(text: str) -> Optional[str]:
    """从 node_not_found 类报错文本中提取缺失的节点类型名（兼容中文节点类型名）。"""
    patterns = [
        r"Cannot find node class\s*['\"]?([^'\"\n\s]+)['\"]?",
        r"Node class\s*['\"]?([^'\"\n\s]+)['\"]?\s*not found",
        r"Unknown node type\s*['\"]?([^'\"\n\s]+)['\"]?",
        r"Node not found\s*['\"]?([^'\"\n\s]+)['\"]?",
        r"节点类型[^：:]*[：:]\s*['\"]?([^'\"\n]+)",
        r"节点类型\s+['\"]?([^'\"\n：:]+)['\"]?",
        r"缺失节点[^：:]*[：:]\s*['\"]?([^'\"\n]+)",
        r"未知节点类型[^：:]*[：:]\s*['\"]?([^'\"\n]+)",
        r"['\"]?(was-node-list-create)['\"]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return None


def _extract_missing_model_path(text: str) -> Optional[str]:
    """从 model_not_found / checkpoint_loading_failed 类报错文本中提取模型路径（兼容中文路径）。"""
    patterns = [
        r"[Cc]annot find model\s*['\"]?([^'\"\n]+)['\"]?",
        r"[Mm]odel not found[.:]?\s*['\"]?([^'\"\n]+)['\"]?",
        r"[Ff]ailed to load checkpoint\s*['\"]?([^'\"\n]+)['\"]?",
        r"[Ee]rror loading checkpoint\s*['\"]?([^'\"\n]+)['\"]?",
        r"No such file or directory:\s*['\"]?([^'\"\n]+)['\"]?",
        r"模型路径\s*[：:]?\s*['\"]?([^'\"\n]+)['\"]?",
        r"模型文件\s*[：:]?\s*['\"]?([^'\"\n]+)['\"]?",
        r"缺失模型\s*[：:]?\s*['\"]?([^'\"\n]+)['\"]?",
        r"['\"]?(models[/\\][^'\"\n]+)['\"]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate
    return None


def _extract_model_subdir_and_filename(model_path: str) -> Tuple[str, str]:
    """从模型路径中提取 models/ 子目录名和文件名，便于给出精准建议。"""
    normalized = model_path.replace("\\", "/")
    if "models/" in normalized:
        after = normalized.split("models/", 1)[1]
        parts = [p for p in after.split("/") if p]
        if len(parts) >= 2:
            return parts[0], parts[-1]
        if parts:
            return parts[0], parts[-1]
    filename = normalized.split("/")[-1]
    return "", filename


def _extract_shape_mismatch_details(text: str) -> Optional[str]:
    """从 shape_mismatch 类报错文本中提取关键维度信息。"""
    patterns = [
        r"The size of tensor[^\n]+",
        r"mat1 and mat2 shapes[^\n]+",
        r"shape mismatch[^\n]*",
        r"size mismatch[^\n]*",
        r"Expected.*size.*got[^\n]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None


def _extract_node_id_from_traceback(text: str) -> Optional[str]:
    """从 traceback 文本中解析节点 ID。"""
    patterns = [
        r"节点\s*ID\s*[:：]\s*([^\s,\n]+)",
        r"node\s+id\s*[:：]\s*([^\s,\n]+)",
        r"node_id['\"]?\s*[:=]\s*['\"]?([^\s,\n'\"]+)",
        r"current_node['\"]?\s*[:=]\s*['\"]?([^\s,\n'\"]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_node_type_from_traceback(text: str) -> Optional[str]:
    """从 traceback 文本中解析节点类型/class_type。"""
    patterns = [
        r"节点\s*类\s*型\s*[:：]\s*([^\s,\n]+)",
        r"节点类型\s*[:：]\s*([^\s,\n]+)",
        r"node\s+type\s*[:：]\s*([^\s,\n]+)",
        r"class_type['\"]?\s*[:=]\s*['\"]?([^\s,\n'\"]+)",
        r"NODE_CLASS_MAPPINGS\s*\[\s*['\"]([^'\"]+)['\"]\s*\]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_model_filename(text: str) -> Optional[str]:
    """从报错文本中提取模型文件名（含扩展名）。"""
    pattern = r"[^\s'\"\\/]+\.(safetensors|ckpt|pt|pth|bin|gguf|onnx)(?=[\s'\"\\]|$)"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return None


def _build_node_info(event: Dict[str, Any]) -> Dict[str, Any]:
    """从 execution_error 事件构建结构化节点信息。

    返回对象同时包含 error_node（前端展示用）与 node_info（向后兼容）。
    只要事件本身、traceback 或报错文本中能提取到节点信息，就保留 error_node，
    不再因为错误文本里出现 "input" / "validate" 等词而丢弃节点信息。
    """
    text = _extract_error_text(event)
    node_info: Dict[str, Any] = {}

    # 1. 顶层字段
    node_id = event.get("node_id")
    node_type = event.get("node_type")
    current_node = event.get("current_node")
    exception_type = event.get("exception_type")

    if node_id is not None:
        node_info["node_id"] = node_id
    if node_type is not None:
        node_info["node_type"] = node_type
    if current_node is not None:
        node_info["current_node"] = current_node
    if exception_type is not None:
        node_info["exception_type"] = exception_type

    # 2. 从 traceback 中解析补充信息
    tb_node_id = _extract_node_id_from_traceback(text)
    tb_node_type = _extract_node_type_from_traceback(text)

    if tb_node_id and node_id is None:
        node_info["node_id"] = tb_node_id
        node_id = tb_node_id
    if tb_node_type and node_type is None:
        node_info["node_type"] = tb_node_type
        node_type = tb_node_type

    # 3. 提取关键上下文（缺失节点、模型、维度、模型文件名）
    missing_node = _extract_missing_node_type(text)
    if missing_node:
        node_info["missing_node_type"] = missing_node

    missing_model = _extract_missing_model_path(text)
    if missing_model:
        node_info["missing_model_path"] = missing_model

    shape_detail = _extract_shape_mismatch_details(text)
    if shape_detail:
        node_info["shape_detail"] = shape_detail

    model_filename = _extract_model_filename(text)
    if model_filename:
        node_info["model_filename"] = model_filename

    # 4. 组装 error_node（前端主展示字段）
    # 只要 event / traceback / 缺失节点名中任意一项能定位到节点，就保留。
    effective_node_id = node_id or current_node or tb_node_id
    effective_node_type = node_type or tb_node_type or missing_node
    error_node: Optional[Dict[str, Any]] = None
    if effective_node_id or effective_node_type:
        error_node = {
            "node_id": effective_node_id if effective_node_id else None,
            "node_type": effective_node_type if effective_node_type else None,
            "display_title": effective_node_type or effective_node_id,
        }

    node_info["error_node"] = error_node
    return node_info


# ============================================================================
# 诊断引擎
# ============================================================================


class DiagEngine:
    """DIAG 诊断引擎。

    基于词库对 ComfyUI 报错进行事后分析，生成结构化诊断报告。
    支持自动语言检测与显存容量感知的差异化建议。

    Usage:
        engine = DiagEngine()
        report = engine.diagnose(execution_error_event, system_snapshot)
        # 或对用户粘贴的文本诊断
        report = engine.diagnose_text("CUDA out of memory", system_snapshot)
    """

    def __init__(self, language: Optional[str] = None):
        """初始化诊断引擎。

        Args:
            language: 强制指定报告语言（如 "zh"/"en"）。为 None 时自动检测。
        """
        self._forced_language = language
        self._error_dict = ERROR_DICT
        self._version = ERROR_DICT_VERSION

    @property
    def version(self) -> str:
        """词库版本号。"""
        return self._version

    def diagnose(
        self,
        execution_error_event: Dict[str, Any],
        system_snapshot: Optional[Dict[str, Any]] = None,
        language: Optional[str] = None,
        prompt_id: Optional[str] = None,
    ) -> DiagReport:
        """对 ComfyUI execution_error 事件进行诊断。

        Args:
            execution_error_event: ComfyUI WebSocket 推送的 execution_error 事件。
            system_snapshot: 诊断时刻的系统快照（可选），用于显存差异化建议。
            language: 报告语言（如 "zh"/"en"）。未提供时优先使用 system_snapshot
                中的 client_language，最后 fallback 到系统 locale。
            prompt_id: 当前执行流的 prompt_id（由 WebSocket execution_start 缓存）。

        Returns:
            DiagReport 诊断报告。
        """
        if not isinstance(execution_error_event, dict):
            logger.warning("[DIAG] execution_error_event 不是字典，降级为空事件")
            execution_error_event = {}

        text = _extract_error_text(execution_error_event)
        node_info = _build_node_info(execution_error_event)

        return self._diagnose_internal(
            text=text,
            node_info=node_info,
            system_snapshot=system_snapshot or {},
            language=language,
            prompt_id=prompt_id,
        )

    def diagnose_text(
        self,
        text: str,
        system_snapshot: Optional[Dict[str, Any]] = None,
        language: Optional[str] = None,
    ) -> DiagReport:
        """对任意报错文本进行词库匹配诊断。

        Args:
            text: 报错文本。
            system_snapshot: 诊断时刻的系统快照（可选）。
            language: 报告语言（如 "zh"/"en"）。未提供时按 client_language / locale 推导。

        Returns:
            DiagReport 诊断报告。
        """
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        return self._diagnose_internal(
            text=text,
            node_info={},
            system_snapshot=system_snapshot or {},
            language=language,
            source="manual_text",
        )

    def _diagnose_internal(
        self,
        text: str,
        node_info: Dict[str, Any],
        system_snapshot: Dict[str, Any],
        language: Optional[str] = None,
        prompt_id: Optional[str] = None,
        source: str = "backend_execution_error",
    ) -> DiagReport:
        """内部诊断逻辑：遍历词库匹配并生成报告。"""
        language = self._forced_language or _resolve_language(system_snapshot, language)
        if language not in SUPPORTED_LANGUAGES:
            language = DEFAULT_LANGUAGE

        vram_total_mb = _extract_vram_total_mb(system_snapshot)
        platform = _extract_platform(system_snapshot) or _detect_runtime_platform()

        # 将 prompt_id 注入快照，供后续精简上下文使用
        if prompt_id is not None:
            system_snapshot = dict(system_snapshot)
            system_snapshot["prompt_id"] = prompt_id

        # 1. 显式 OOM 标记优先：命中不可争议的 CUDA/HIP/MPS OOM 关键字时，
        #    直接返回 OOM 分类，避免被 workflow connection / input_slot 等
        #    宽泛模式误分类。
        explicit_oom_entry = _detect_explicit_oom(text, self._error_dict)
        if explicit_oom_entry is not None:
            return self._build_report(
                entry=explicit_oom_entry,
                matched=True,
                text=text,
                node_info=node_info,
                system_snapshot=system_snapshot,
                language=language,
                vram_total_mb=vram_total_mb,
                platform=platform,
                source=source,
            )

        # 2. 遍历词库，按顺序优先匹配第一个命中项
        for entry in self._error_dict:
            patterns = _compile_patterns(entry)
            if not patterns:
                continue
            for pattern in patterns:
                if pattern.search(text):
                    return self._build_report(
                        entry=entry,
                        matched=True,
                        text=text,
                        node_info=node_info,
                        system_snapshot=system_snapshot,
                        language=language,
                        vram_total_mb=vram_total_mb,
                        platform=platform,
                        source=source,
                    )

        # 3. 未匹配到任何已知错误
        return self._build_unknown_report(
            text=text,
            node_info=node_info,
            system_snapshot=system_snapshot,
            language=language,
            source=source,
        )

    def _category_to_status(self, category: str) -> str:
        """根据分类决定报告状态。"""
        if category in ("connection_error",):
            return "warning"
        return "error"

    def _category_to_severity(self, category: str, matched: bool) -> str:
        """根据分类与是否匹配决定严重程度。"""
        if not matched or category == "unknown":
            return "warning"
        if category in ("oom", "model_missing", "device_mismatch", "execution_error"):
            return "error"
        return "warning"

    def _build_category_label(self, category: str, language: str) -> str:
        """生成分类翻译标签。"""
        labels = CATEGORY_LABELS.get(category, CATEGORY_LABELS["unknown"])
        return labels.get(language) or labels.get(DEFAULT_LANGUAGE, category)

    def _build_system_context(
        self,
        system_snapshot: Dict[str, Any],
        category: str,
    ) -> Dict[str, Any]:
        """构建精简的系统上下文快照。

        仅保留对前端展示与问题定位最有价值的字段，避免报告臃肿。
        """
        context: Dict[str, Any] = {"timestamp": system_snapshot.get("timestamp", time.time())}

        # 执行上下文（prompt_id 由 WebSocket 钩子传入）
        execution_context: Dict[str, Any] = {}
        if "prompt_id" in system_snapshot:
            execution_context["prompt_id"] = system_snapshot["prompt_id"]
        if execution_context:
            context["execution_context"] = execution_context

        for key in ("client_language", "platform", "python_version", "comfyui_version"):
            if key in system_snapshot:
                context[key] = system_snapshot[key]

        # GPU 信息
        gpu = system_snapshot.get("gpu")
        if isinstance(gpu, dict):
            context["gpu"] = {
                k: gpu[k]
                for k in ("device_name", "vram_total_mb", "vram_used_mb", "vram_percent")
                if k in gpu
            }
        gpus = system_snapshot.get("gpus")
        if isinstance(gpus, list) and gpus:
            context["gpus"] = [
                {
                    k: g[k]
                    for k in ("device_name", "vram_total_mb", "vram_used_mb", "vram_percent")
                    if k in g
                }
                for g in gpus
                if isinstance(g, dict)
            ]

        # 内存 / CPU
        ram = system_snapshot.get("ram")
        if isinstance(ram, dict):
            context["ram"] = {
                k: ram[k]
                for k in ("total_gb", "used_gb", "percent")
                if k in ram
            }
        cpu = system_snapshot.get("cpu")
        if isinstance(cpu, dict):
            context["cpu"] = {k: cpu[k] for k in ("utilization",) if k in cpu}
        if "cpu_utilization" in system_snapshot:
            context["cpu_utilization"] = system_snapshot["cpu_utilization"]

        # OOM 场景追加峰值显存
        if category == "oom":
            for key in ("peak_vram_used_mb", "peak_vram_percent"):
                if key in system_snapshot:
                    context[key] = system_snapshot[key]

        return context

    def _filter_suggestions(self, suggestions: List[str]) -> List[str]:
        """过滤掉有害或明显无关的建议，并去除重复/被包含的条目。"""
        harmful_keywords = [
            "rm -rf",
            "delete system",
            "format ",
            "registry editor",
            "disable antivirus",
        ]
        filtered: List[str] = []
        for s in suggestions:
            if not isinstance(s, str) or not s.strip():
                continue
            lower = s.lower()
            if any(kw in lower for kw in harmful_keywords):
                continue
            filtered.append(s)

        # 语义去重：若一条建议被另一条更详细的建议包含（前缀相同），保留更详细的
        normalized = [item.strip().lower().rstrip("。！.!;；") for item in filtered]
        keep = [True] * len(filtered)
        for i in range(len(filtered)):
            ni = normalized[i]
            if not ni:
                keep[i] = False
                continue
            for j in range(len(filtered)):
                if i == j:
                    continue
                nj = normalized[j]
                if not nj:
                    continue
                if i > j and ni == nj:
                    keep[i] = False
                    break
                if len(ni) < len(nj) and nj.startswith(ni):
                    keep[i] = False
                    break
        return [filtered[i] for i in range(len(filtered)) if keep[i]]

    def _build_report(
        self,
        entry: Dict[str, Any],
        matched: bool,
        text: str,
        node_info: Dict[str, Any],
        system_snapshot: Dict[str, Any],
        language: str,
        vram_total_mb: Optional[int],
        platform: Optional[str] = None,
        source: str = "backend_execution_error",
    ) -> DiagReport:
        """根据匹配到的词库条目生成统一诊断报告。"""
        translations = entry.get("translations", {})
        lang_trans = translations.get(language)
        if not lang_trans:
            # 懒加载 fallback：无对应语言时回退英文
            lang_trans = translations.get(DEFAULT_LANGUAGE, {})

        title = lang_trans.get("title", entry.get("error_key", ""))
        explanation = lang_trans.get("explanation", "")

        suggestions_map = entry.get("suggestions", {})
        suggestion_items = suggestions_map.get(language) or suggestions_map.get(DEFAULT_LANGUAGE, [])
        suggestions = _pick_suggestions(suggestion_items, vram_total_mb, platform)

        category = entry.get("category", "unknown")

        # 根据提取到的关键信息补充最具体的优先级建议
        missing_node = node_info.get("missing_node_type")
        missing_model = node_info.get("missing_model_path")
        shape_detail = node_info.get("shape_detail")

        # 根据提取到的关键信息生成最具体的单条建议；
        # 用户要求每个错误只给一条最准确的动作，因此当能提取到节点/模型/形状细节时，
        # 直接用具体建议覆盖词库中的通用建议。
        specific = None
        if category == "node_not_found" and missing_node:
            if language == "zh":
                specific = f"请在 ComfyUI Manager 中搜索并安装 {missing_node} 节点包，然后完全重启 ComfyUI。"
            else:
                specific = f"Search for and install the {missing_node} node package in ComfyUI Manager, then fully restart ComfyUI."

        if category == "model_missing" and missing_model:
            subdir, filename = _extract_model_subdir_and_filename(missing_model)
            if language == "zh":
                if subdir:
                    specific = f"请下载 {filename} 模型并放入 ComfyUI/models/{subdir} 目录，然后重启 ComfyUI。"
                else:
                    specific = f"请下载 {filename} 模型并放入 ComfyUI/models 下对应子目录，然后重启 ComfyUI。"
            else:
                if subdir:
                    specific = f"Download the {filename} model and place it in ComfyUI/models/{subdir}, then restart ComfyUI."
                else:
                    specific = f"Download the {filename} model and place it in the correct ComfyUI/models subdirectory, then restart ComfyUI."

        if category in ("dtype_mismatch", "shape_mismatch") and shape_detail:
            if language == "zh":
                specific = f"检查模型版本是否与工作流匹配，Latent 尺寸是否一致。冲突细节：{shape_detail}"
            else:
                specific = f"Check that the model version matches the workflow and the Latent size is consistent. Detail: {shape_detail}"

        if specific is not None:
            suggestions = [specific]

        # 过滤建议，确保无有害/无关内容
        suggestions = self._filter_suggestions(suggestions)

        # 严格限制建议数量：每个错误只保留一条最优先的可执行建议。
        # 过多可能性会让新手无所适从，必须聚焦在最能解决问题的动作上。
        MAX_SUGGESTIONS = 1
        if len(suggestions) > MAX_SUGGESTIONS:
            suggestions = suggestions[:MAX_SUGGESTIONS]

        # OOM 场景追加历史峰值显存
        report_snapshot = dict(system_snapshot)
        if category == "oom":
            try:
                recent_snaps = snapshot_persistence.read_recent_snapshots(seconds=60)
                peak_used, peak_percent = _extract_peak_vram_mb(recent_snaps)
                if peak_used is not None:
                    report_snapshot["peak_vram_used_mb"] = peak_used
                if peak_percent is not None:
                    report_snapshot["peak_vram_percent"] = peak_percent
            except Exception:
                # 读取历史快照失败时静默降级，不影响主诊断流程
                pass

        status = self._category_to_status(category)
        severity = self._category_to_severity(category, matched=matched)

        return DiagReport(
            error_node=node_info.get("error_node"),
            category=category,
            category_label=self._build_category_label(category, language),
            title=title,
            explanation=explanation,
            suggestions=suggestions,
            raw_error=text,
            status=status,
            severity=severity,
            language=language,
            timestamp=time.time(),
            system_context=self._build_system_context(report_snapshot, category),
            matched=matched,
            node_info=node_info,
            source=source,
        )

    def _guess_unknown_hint(self, text: str, language: str) -> str:
        """从未命中词库的报错文本中提取一个最高置信度的方向提示。

        未知错误不应给出多个可能性，否则用户会无所适从。这里只在文本包含
        非常明确的关键词时才给出一条精简提示，且用词保守（"涉及"而非"就是"）。
        """
        lowered = (text or "").lower()

        # 按置信度从高到低排列，命中即返回，避免列出多个方向。
        if language == "zh":
            clues = [
                ("out of memory|cuda out of memory|hip out of memory|rocm out of memory|vram|显存不足|内存不足|oom", "报错中涉及显存/内存不足（OOM）相关关键词。"),
                ("no module named|modulenotfounderror|cannot import name|找不到模块", "报错中涉及 Python 依赖缺失相关关键词。"),
                ("cannot find model|model not found|checkpoint|safetensors|ckpt|lora|vae|unet", "报错中涉及模型文件缺失或损坏相关关键词。"),
                ("connection refused|connection timed out|urlopen|getaddrinfo|temporary failure in name resolution|下载失败|下载超时|网络错误", "报错中涉及网络/下载连接相关关键词。"),
                ("permission denied|access is denied|权限|拒绝访问", "报错中涉及文件/目录权限相关关键词。"),
            ]
        else:
            clues = [
                ("out of memory|cuda out of memory|hip out of memory|rocm out of memory|vram|oom", "The error text involves VRAM/RAM OOM keywords."),
                ("no module named|modulenotfounderror|cannot import name", "The error text involves missing Python dependency keywords."),
                ("cannot find model|model not found|checkpoint|safetensors|ckpt|lora|vae|unet", "The error text involves model file missing or corruption keywords."),
                ("connection refused|connection timed out|urlopen|getaddrinfo|temporary failure in name resolution", "The error text involves network/download connection keywords."),
                ("permission denied|access is denied", "The error text involves file/directory permission keywords."),
            ]

        for pattern, hint in clues:
            if any(p in lowered for p in pattern.split("|")):
                return hint
        return ""

    def _build_unknown_report(
        self,
        text: str,
        node_info: Dict[str, Any],
        system_snapshot: Dict[str, Any],
        language: str,
        source: str = "backend_execution_error",
    ) -> DiagReport:
        """生成未识别错误的兜底报告。

        未知错误不再罗列多种可能，只保留原始错误并给出一条最明确的下一步动作：
        查看原始报错。这样避免让用户在十几个猜测中自行验证。
        """
        hint = self._guess_unknown_hint(text, language)
        if language == "zh":
            title = "未识别的错误"
            explanation = (
                "当前报错暂未命中已知词库条目，我们已完整保留原始错误信息。"
                "请先在下方「原始报错」区域查看完整堆栈，通常堆栈末尾一行就是真正原因。"
            )
            if hint:
                explanation += "\n" + hint
            suggestions = [
                "查看原始报错：展开下方「原始报错」区域，从堆栈最后一行向上定位真正报错的节点与文件。",
            ]
        else:
            title = "Unknown Error"
            explanation = (
                "The current error did not match any known entry in the diagnostic dictionary. "
                "The original error text has been preserved. Please expand the raw error area below; "
                "usually the last line of the traceback is the real cause."
            )
            if hint:
                explanation += "\n" + hint
            suggestions = [
                "Review the raw error: expand the raw error area below and locate the failing node/file from the last traceback line upward.",
            ]

        suggestions = self._filter_suggestions(suggestions)

        return DiagReport(
            error_node=node_info.get("error_node"),
            category="unknown",
            category_label=self._build_category_label("unknown", language),
            title=title,
            explanation=explanation,
            suggestions=suggestions,
            raw_error=text,
            status="error",
            severity="warning",
            language=language,
            timestamp=time.time(),
            system_context=self._build_system_context(system_snapshot, "unknown"),
            matched=False,
            node_info=node_info,
            source=source,
        )


# ============================================================================
# 便捷接口
# ============================================================================


def diagnose_text(
    text: str,
    system_snapshot: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
) -> DiagReport:
    """一键诊断文本便捷函数。"""
    engine = DiagEngine(language=language)
    return engine.diagnose_text(text, system_snapshot)
