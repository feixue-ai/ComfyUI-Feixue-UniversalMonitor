"""
ComfyUI-Feixue-UniversalMonitor - 跨平台系统日志读取器

职责：
1. 按平台读取系统日志（Linux dmesg / Windows Event Log / macOS kernel log）。
2. 过滤 GPU/显示/驱动相关事件与错误模式。
3. 结合 snapshot_persistence 分析崩溃前硬件趋势。
4. 为手动诊断模式 B 生成 DiagReport。

设计约束：
- 所有外部命令带超时保护，避免阻塞 ComfyUI 主流程。
- 无权限时诚实降级，不编造日志证据。
- 快照趋势分析结果明确标注为"基于监控快照的推测"。

版本: 1.0.0
作者: Feixue
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from .diagnoser import DiagReport, _detect_language
from .snapshot_persistence import read_recent_snapshots

# 崩溃分类标签（与 DiagReport 新结构对齐）
_CRASH_CATEGORY_LABELS = {
    "zh": "崩溃/掉驱动",
    "en": "Crash/Driver Failure",
}

logger = logging.getLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

DEFAULT_COMMAND_TIMEOUT = 5.0
DMESG_TIMEOUT = 3.0
WEVTUTIL_TIMEOUT = 5.0
MACOS_LOG_TIMEOUT = 5.0

# 用于 dmesg / macOS log 过滤的 GPU 相关关键词
GPU_KEYWORDS = (
    "amdgpu", "nvidia", "nouveau", "i915", "iris", "radeon",
    "gpu", "drm", "tdr", "reset", "fault", "timeout", "ring", "gfx",
    "display", "driver", "livekernel", "nvrm", "xid",
)

# Linux 已知崩溃模式
LINUX_PATTERNS = [
    {"label": "amdgpu_ring_timeout", "pattern": re.compile(r"amdgpu\s+ring\s+\w+\s+timeout", re.IGNORECASE)},
    {"label": "amdgpu_job_timedout", "pattern": re.compile(r"amdgpu_job_timedout|job\s+timed\s*out", re.IGNORECASE)},
    {"label": "gpu_reset", "pattern": re.compile(r"GPU\s+reset", re.IGNORECASE)},
    {"label": "gpu_fault", "pattern": re.compile(r"GPU\s+fault", re.IGNORECASE)},
    {"label": "ring_gfx_timeout", "pattern": re.compile(r"ring\s+gfx\s+timeout", re.IGNORECASE)},
    # NVIDIA / nouveau
    {
        "label": "nvrm_xid",
        "pattern": re.compile(
            r"NVRM:\s+Xid\s*(?:\(PCI:[^)]+\))?:?\s*\b(?:13|31|43|45|48|56|62|74|79|95|109)\b",
            re.IGNORECASE,
        ),
    },
    {"label": "nvrm_xid_pci", "pattern": re.compile(r"NVRM:\s+Xid\s+\(PCI:0000", re.IGNORECASE)},
    {"label": "nvrm_gpu_at", "pattern": re.compile(r"NVRM:\s+GPU\s+at", re.IGNORECASE)},
    {
        "label": "nouveau_error",
        "pattern": re.compile(
            r"nouveau.*(?:fifo|fail|error|lockup|gr:|PGRAPH|channel|Xid)",
            re.IGNORECASE,
        ),
    },
]

# Windows 已知崩溃模式（EventID 也会在 wevtutil / pywin32 输出中体现）
WINDOWS_PATTERNS = [
    {"label": "tdr_event_4101", "pattern": re.compile(r"Event\s*ID\s*[:=]?\s*4101|\b4101\b", re.IGNORECASE)},
    {"label": "display_driver_tdr", "pattern": re.compile(r"Display\s+driver\s+stopped\s+responding", re.IGNORECASE)},
    {"label": "tdr", "pattern": re.compile(r"\bTDR\b|timeout\s+detection\s+and\s+recovery", re.IGNORECASE)},
    {"label": "live_kernel_report", "pattern": re.compile(r"LiveKernelReports", re.IGNORECASE)},
]

# 通用崩溃模式
GENERIC_PATTERNS = [
    {"label": "gpu_fault", "pattern": re.compile(r"GPU\s+fault", re.IGNORECASE)},
    {"label": "ring_gfx_timeout", "pattern": re.compile(r"ring\s+gfx\s+timeout", re.IGNORECASE)},
]


# ============================================================================
# 工具函数
# ============================================================================


def _run_command(cmd: List[str], timeout: float = DEFAULT_COMMAND_TIMEOUT) -> Tuple[int, str, str]:
    """带超时保护执行外部命令，返回 (returncode, stdout, stderr)。

    任何异常都被捕获，避免阻塞或崩溃调用方。
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        stderr = e.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return -1, stdout, f"command timed out after {timeout}s\n{stderr}"
    except Exception as e:
        return -1, "", str(e)


def _is_permission_error(stderr: str, returncode: int) -> bool:
    """根据 stderr 与返回码判断是否为权限不足。"""
    if returncode == 0:
        return False
    text = (stderr or "").lower()
    return any(kw in text for kw in (
        "permission", "not permitted", "access is denied", "denied",
        "operation not permitted", "requires administrator",
    ))


# ============================================================================
# 日志读取器
# ============================================================================


class LogReader:
    """跨平台系统日志读取器。

    按当前平台读取系统日志、匹配已知崩溃模式，并结合监控快照趋势生成
    崩溃/黑屏/掉驱动诊断报告。
    """

    def __init__(self, language: Optional[str] = None):
        """初始化日志读取器。

        Args:
            language: 报告语言（"zh"/"en"）。为 None 时自动检测。
        """
        lang = language or _detect_language()
        self.language = lang if lang in ("zh", "en") else "en"

    # -------------------------------------------------------------------------
    # 平台日志读取
    # -------------------------------------------------------------------------

    def read_dmesg(self) -> Tuple[str, Optional[str]]:
        """Linux 下读取 dmesg 并过滤 GPU 相关行。

        Returns:
            (log_output, permission_issue)
            permission_issue 为 "no_permission" 时表示无权限；否则为 None。
        """
        if not sys.platform.startswith("linux"):
            return "", None

        rc, stdout, stderr = _run_command(["dmesg"], timeout=DMESG_TIMEOUT)
        if rc != 0:
            if _is_permission_error(stderr, rc):
                return "", "no_permission"
            logger.debug(f"dmesg read failed: rc={rc} stderr={stderr[:200]}")
            return "", None

        lines = [
            line for line in stdout.splitlines()
            if any(kw in line.lower() for kw in GPU_KEYWORDS)
        ]
        return "\n".join(lines), None

    def read_windows_event_log(self) -> Tuple[str, Optional[str]]:
        """Windows 下读取 System/Application 事件日志中的 GPU/显示/驱动事件。

        优先使用 pywin32；未安装或失败时降级为 wevtutil 命令行；
        权限不足时返回 no_permission 标记。

        Returns:
            (log_output, permission_issue)
        """
        if sys.platform != "win32":
            return "", None

        # 优先 pywin32
        try:
            return self._read_windows_with_pywin32()
        except Exception as e:
            logger.debug(f"pywin32 event log read failed: {e}")

        # 降级 wevtutil
        return self._read_windows_with_wevtutil()

    def _read_windows_with_pywin32(self) -> Tuple[str, Optional[str]]:
        """使用 pywin32 读取 Windows 事件日志。"""
        import win32evtlog
        import win32evtlogutil

        event_ids = {4101, 4109, 13, 14}
        output_lines: List[str] = []
        max_events = 200

        for log_type in ("System", "Application"):
            hand = None
            try:
                hand = win32evtlog.OpenEventLog(None, log_type)
                flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
                read_count = 0
                while read_count < max_events:
                    events = win32evtlog.ReadEventLog(hand, flags, 0)
                    if not events:
                        break
                    for event in events:
                        read_count += 1
                        eid = event.EventID & 0xFFFF
                        if eid not in event_ids:
                            continue
                        try:
                            msg = win32evtlogutil.SafeFormatMessage(event, log_type)
                        except Exception:
                            msg = str(event.StringInserts) if event.StringInserts else ""
                        src = event.SourceName or ""
                        ts = event.TimeGenerated.Format() if event.TimeGenerated else ""
                        output_lines.append(
                            f"[{log_type}] EventID={eid} Source={src} Time={ts} {msg}"
                        )
                    if read_count >= max_events:
                        break
            except Exception as e:
                err_str = str(e).lower()
                if any(kw in err_str for kw in ("access", "permission", "denied")):
                    return "", "no_permission"
                logger.debug(f"Read {log_type} event log failed: {e}")
                continue
            finally:
                if hand is not None:
                    try:
                        win32evtlog.CloseEventLog(hand)
                    except Exception:
                        pass

        return "\n".join(output_lines), None

    def _read_windows_with_wevtutil(self) -> Tuple[str, Optional[str]]:
        """使用 wevtutil 命令行读取 Windows 事件日志。"""
        query = (
            '*[System[('
            'EventID=4101 or EventID=4109 or EventID=13 or EventID=14'
            ')]]'
        )
        rc, stdout, stderr = _run_command(
            ["wevtutil", "qe", "System", f"/q:{query}", "/f:text", "/c:50"],
            timeout=WEVTUTIL_TIMEOUT,
        )
        if rc != 0:
            if _is_permission_error(stderr, rc):
                return "", "no_permission"
            logger.debug(f"wevtutil failed: rc={rc} stderr={stderr[:200]}")
            return "", None
        return stdout, None

    def read_macos_log(self) -> Tuple[str, Optional[str]]:
        """macOS 下使用 log show 尽力读取 kernel 日志并过滤 GPU 相关行。

        Returns:
            (log_output, permission_issue)
        """
        if sys.platform != "darwin":
            return "", None

        rc, stdout, stderr = _run_command(
            ["log", "show", "--predicate", 'process == "kernel"', "--last", "5m"],
            timeout=MACOS_LOG_TIMEOUT,
        )
        if rc != 0:
            logger.debug(f"macOS log show failed: rc={rc} stderr={stderr[:200]}")
            return "", None

        lines = [
            line for line in stdout.splitlines()
            if any(kw in line.lower() for kw in GPU_KEYWORDS)
        ]
        return "\n".join(lines), None

    def read_system_log(self) -> Tuple[str, Optional[str]]:
        """按当前平台 dispatch 到对应日志读取方法。"""
        plat = sys.platform
        if plat.startswith("linux"):
            return self.read_dmesg()
        if plat == "win32":
            return self.read_windows_event_log()
        if plat == "darwin":
            return self.read_macos_log()
        return "", None

    # -------------------------------------------------------------------------
    # 快照趋势分析
    # -------------------------------------------------------------------------

    def read_snapshot_trend(self) -> Dict[str, Any]:
        """读取快照环形缓冲区，分析最近 30 秒 VRAM/利用率/温度趋势。

        Returns:
            包含以下字段的字典：
            - available: 是否有快照数据
            - snapshots_count: 快照条数
            - high_load_detected: 是否检测到高负载（VRAM>=95% + 利用率>=99% + 温度>85C）
            - high_load_count: 满足高负载条件的快照数
            - sequence_interrupted: 快照序列是否突然中断（最后一条快照距今 >60s）
            - sudden_crash_suspected: 是否疑似硬件级别重置
            - last_snapshot_age_seconds: 最后一条快照距现在秒数
            - max_vram_percent / max_gpu_utilization / max_temperature: 区间内峰值
            - note: 结果说明标记
        """
        snapshots = read_recent_snapshots(seconds=30.0)
        base = {
            "available": False,
            "snapshots_count": 0,
            "high_load_detected": False,
            "high_load_count": 0,
            "sequence_interrupted": False,
            "sudden_crash_suspected": False,
            "last_snapshot_age_seconds": None,
            "max_vram_percent": None,
            "max_gpu_utilization": None,
            "max_temperature": None,
            "note": "no_recent_snapshots",
        }
        if not snapshots:
            return base

        max_vram = 0.0
        max_util = 0.0
        max_temp = 0.0
        high_load_count = 0
        last_ts = snapshots[-1].get("timestamp", 0)
        now = time.time()
        age = (now - last_ts) if last_ts else None

        for snap in snapshots:
            vram_pct = self._extract_vram_percent(snap)
            util = self._extract_gpu_utilization(snap)
            temp = self._extract_temperature(snap)

            if vram_pct is not None:
                max_vram = max(max_vram, vram_pct)
            if util is not None:
                max_util = max(max_util, util)
            if temp is not None:
                max_temp = max(max_temp, temp)

            if (
                vram_pct is not None and vram_pct >= 95.0
                and util is not None and util >= 99.0
                and temp is not None and temp > 85.0
            ):
                high_load_count += 1

        high_load_detected = high_load_count >= 1
        # 若最后一条快照已过去 60 秒以上，认为监控序列突然中断（可能进程已崩溃/退出）
        sequence_interrupted = age is not None and age > 60.0
        sudden_crash_suspected = high_load_detected and sequence_interrupted

        return {
            **base,
            "available": True,
            "snapshots_count": len(snapshots),
            "high_load_detected": high_load_detected,
            "high_load_count": high_load_count,
            "sequence_interrupted": sequence_interrupted,
            "sudden_crash_suspected": sudden_crash_suspected,
            "last_snapshot_age_seconds": age,
            "max_vram_percent": max_vram if max_vram > 0 else None,
            "max_gpu_utilization": max_util if max_util > 0 else None,
            "max_temperature": max_temp if max_temp > 0 else None,
            "note": "snapshot_based_speculation",
        }

    def _extract_vram_percent(self, snapshot: Dict[str, Any]) -> Optional[float]:
        """从快照中提取显存使用百分比。"""
        gpu = snapshot.get("gpu")
        if isinstance(gpu, dict):
            v = gpu.get("vram_percent")
            if isinstance(v, (int, float)):
                return float(v)
            used = gpu.get("vram_used_mb")
            total = gpu.get("vram_total_mb")
            if isinstance(used, (int, float)) and isinstance(total, (int, float)) and total > 0:
                return (used / total) * 100.0

        gpus = snapshot.get("gpus")
        if isinstance(gpus, list) and gpus:
            return self._extract_vram_percent({"gpu": gpus[0]})
        return None

    def _extract_gpu_utilization(self, snapshot: Dict[str, Any]) -> Optional[float]:
        """从快照中提取 GPU 利用率。"""
        gpu = snapshot.get("gpu")
        if isinstance(gpu, dict):
            for key in ("utilization", "gpu_utilization"):
                v = gpu.get(key)
                if isinstance(v, (int, float)):
                    return float(v)

        gpus = snapshot.get("gpus")
        if isinstance(gpus, list) and gpus:
            return self._extract_gpu_utilization({"gpu": gpus[0]})
        return None

    def _extract_temperature(self, snapshot: Dict[str, Any]) -> Optional[float]:
        """从快照中提取 GPU 温度。"""
        gpu = snapshot.get("gpu")
        if isinstance(gpu, dict):
            v = gpu.get("temperature")
            if isinstance(v, (int, float)):
                return float(v)

        gpus = snapshot.get("gpus")
        if isinstance(gpus, list) and gpus:
            return self._extract_temperature({"gpu": gpus[0]})
        return None

    # -------------------------------------------------------------------------
    # 模式匹配
    # -------------------------------------------------------------------------

    def search_crash_patterns(self, log_output: str) -> List[Dict[str, Any]]:
        """在日志输出中按平台搜索已知崩溃模式。

        Args:
            log_output: 日志文本。

        Returns:
            命中的模式列表，每项包含 label、matched_text、start、end。
        """
        if not log_output:
            return []

        patterns: List[Dict[str, Any]] = list(GENERIC_PATTERNS)
        if sys.platform.startswith("linux"):
            patterns.extend(LINUX_PATTERNS)
        elif sys.platform == "win32":
            patterns.extend(WINDOWS_PATTERNS)

        findings: List[Dict[str, Any]] = []
        for entry in patterns:
            for match in entry["pattern"].finditer(log_output):
                findings.append({
                    "label": entry["label"],
                    "matched_text": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                })

        # 按 label + 文本去重
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        for f in findings:
            key = (f["label"], f["matched_text"])
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique

    # -------------------------------------------------------------------------
    # 综合诊断
    # -------------------------------------------------------------------------

    def manual_diagnose_crash(self) -> DiagReport:
        """整合平台检测、日志读取、模式匹配、快照趋势，生成崩溃诊断报告。"""
        log_output, permission_issue = self.read_system_log()
        findings = self.search_crash_patterns(log_output)
        trend = self.read_snapshot_trend()
        return self._build_crash_report(log_output, permission_issue, findings, trend)

    def _build_crash_report(
        self,
        log_output: str,
        permission_issue: Optional[str],
        findings: List[Dict[str, Any]],
        trend: Dict[str, Any],
    ) -> DiagReport:
        """根据日志与快照证据构造 DiagReport。"""
        language = self.language
        has_log_evidence = bool(findings)
        has_snapshot_evidence = trend.get("sudden_crash_suspected", False)
        matched = has_log_evidence or has_snapshot_evidence

        # NVIDIA / nouveau 崩溃模式识别（Linux 专属，用于生成差异化建议）
        nvidia_labels = {"nvrm_xid", "nvrm_xid_pci", "nvrm_gpu_at", "nouveau_error"}
        nvidia_findings = [f for f in findings if f["label"] in nvidia_labels]
        has_nvidia_crash = bool(nvidia_findings)
        nvidia_xid_codes = sorted({
            m.group(1)
            for f in nvidia_findings
            for m in [re.search(r"Xid(?:\s*\(PCI:[^)]+\))?:?\s*(\d+)", f["matched_text"], re.IGNORECASE)]
            if m
        })

        if language == "zh":
            title = "检测到疑似显卡崩溃/掉驱动线索" if matched else "未找到明确的崩溃线索"
            explanation_parts: List[str] = []

            if permission_issue == "no_permission":
                explanation_parts.append(
                    "当前没有足够权限读取系统日志，已降级为仅分析监控快照。"
                )
                if sys.platform.startswith("linux"):
                    explanation_parts.append(
                        "Linux 用户可手动运行 `sudo dmesg | tail -50` 或 `journalctl -k` 查看内核日志。"
                    )
                elif sys.platform == "win32":
                    explanation_parts.append(
                        "Windows 用户请以管理员身份运行 ComfyUI，以便读取事件日志。"
                    )

            if has_log_evidence:
                labels = sorted({f["label"] for f in findings})
                explanation_parts.append(
                    f"在系统日志中发现 {len(findings)} 处可疑记录，涉及模式：{', '.join(labels)}。"
                )
                if has_nvidia_crash:
                    code_str = f"（Xid {', '.join(nvidia_xid_codes)}）" if nvidia_xid_codes else ""
                    if any(f["label"] == "nouveau_error" for f in nvidia_findings):
                        explanation_parts.append(
                            f"检测到 nouveau 开源驱动错误{code_str}，通常与 NVIDIA 显卡驱动或硬件稳定性有关。"
                        )
                    else:
                        explanation_parts.append(
                            f"检测到 NVIDIA 内核驱动错误{code_str}，通常由显卡硬件、驱动版本、供电或 PCIe 连接不稳定导致。"
                        )
            elif not permission_issue:
                explanation_parts.append("系统日志中未匹配到已知的 GPU/显示/驱动崩溃模式。")

            if has_snapshot_evidence:
                explanation_parts.append(
                    "基于监控快照的推测：崩溃前 30 秒内出现显存>=95%、利用率 100%、温度>85C "
                    "且快照序列突然中断，疑似显卡过载导致的硬件级别重置。此结论仅为推测，非最终定论。"
                )
            elif trend.get("high_load_detected"):
                explanation_parts.append(
                    "监控快照显示崩溃前显卡处于高负载状态，但序列未明显中断，"
                    "不能直接判定为硬件级别重置（基于监控快照的推测）。"
                )

            if not explanation_parts:
                explanation = "未在系统日志和监控快照中找到明确线索。如果问题持续，请检查驱动版本、散热与电源。"
            else:
                explanation = " ".join(explanation_parts)

            suggestions = [
                "检查显卡驱动版本，确保安装最新稳定版（NVIDIA / AMD / Intel 各自官网）。",
                "清理显卡灰尘、检查散热器与机箱风道，确保高负载时温度可控。",
                "在 ComfyUI 中降低批次大小、分辨率或模型精度以减小显存压力。",
                "如果频繁出现 TDR/黑屏，尝试在系统电源选项中关闭 PCI Express 链接状态电源管理。",
                "查看系统日志原文（Linux: dmesg / journalctl -k；Windows: 事件查看器）获取更完整信息。",
            ]
            if has_nvidia_crash:
                suggestions = [
                    "更新 NVIDIA 显卡驱动到最新稳定版，或回退到经过验证的稳定版本。",
                    "检查显卡温度、供电接口与电源功率，确保高负载下稳定。",
                    "降低 GPU 负载（减小批次/分辨率/模型精度）以减少触发概率。",
                    "禁用显卡超频（包括 BIOS、Afterburner 等第三方工具设置）。",
                    "检查 PCIe 插槽与供电线连接，必要时重新插拔显卡或更换线材。",
                ] + suggestions
            if permission_issue == "no_permission":
                if sys.platform.startswith("linux"):
                    suggestions.insert(0, "使用 `sudo dmesg | tail -50` 或 `journalctl -k` 手动查看内核日志。")
                elif sys.platform == "win32":
                    suggestions.insert(0, "请以管理员身份运行 ComfyUI 以读取 Windows 事件日志。")
        else:
            title = "Suspected GPU crash / driver failure detected" if matched else "No clear crash clues found"
            explanation_parts = []

            if permission_issue == "no_permission":
                explanation_parts.append(
                    "Insufficient permission to read system logs; degraded to snapshot-only analysis."
                )
                if sys.platform.startswith("linux"):
                    explanation_parts.append(
                        "On Linux, run `sudo dmesg | tail -50` or `journalctl -k` manually."
                    )
                elif sys.platform == "win32":
                    explanation_parts.append(
                        "On Windows, please run ComfyUI as administrator to read the Event Log."
                    )

            if has_log_evidence:
                labels = sorted({f["label"] for f in findings})
                explanation_parts.append(
                    f"Found {len(findings)} suspicious records in system logs, patterns: {', '.join(labels)}."
                )
                if has_nvidia_crash:
                    code_str = f" (Xid {', '.join(nvidia_xid_codes)})" if nvidia_xid_codes else ""
                    if any(f["label"] == "nouveau_error" for f in nvidia_findings):
                        explanation_parts.append(
                            f"Detected nouveau open-source driver error{code_str}, "
                            "usually related to NVIDIA driver or hardware stability."
                        )
                    else:
                        explanation_parts.append(
                            f"Detected NVIDIA kernel driver error{code_str}, "
                            "typically caused by GPU hardware, driver version, power delivery or PCIe instability."
                        )
            elif not permission_issue:
                explanation_parts.append(
                    "No known GPU/Display/Driver crash patterns matched in system logs."
                )

            if has_snapshot_evidence:
                explanation_parts.append(
                    "Snapshot-based speculation: within 30 seconds before the crash, VRAM >=95%, "
                    "utilization 100%, temperature >85C and the snapshot sequence abruptly stopped. "
                    "This suggests a possible hardware-level reset caused by GPU overload, "
                    "but it is only a speculation, not a conclusion."
                )
            elif trend.get("high_load_detected"):
                explanation_parts.append(
                    "Snapshots show the GPU was under high load before the incident, but the sequence "
                    "did not clearly interrupt. A hardware-level reset cannot be directly concluded "
                    "(snapshot-based speculation)."
                )

            if not explanation_parts:
                explanation = (
                    "No clear clues found in logs or snapshots. If the issue persists, "
                    "check drivers, cooling and PSU."
                )
            else:
                explanation = " ".join(explanation_parts)

            suggestions = [
                "Check GPU driver version and install the latest stable release from the vendor website.",
                "Clean GPU dust, verify heatsink and case airflow to keep temperature under control.",
                "Reduce batch size, resolution or model precision in ComfyUI to lower VRAM pressure.",
                "If TDR/black screen occurs frequently, try disabling PCI Express Link State Power Management.",
                "Review full system logs (Linux: dmesg/journalctl -k; Windows: Event Viewer) for complete information.",
            ]
            if has_nvidia_crash:
                suggestions = [
                    "Update the NVIDIA graphics driver to the latest stable release, or roll back to a known stable version.",
                    "Check GPU temperature, power connectors and PSU wattage to ensure stability under load.",
                    "Reduce GPU workload (smaller batch/resolution/model precision) to lower the chance of triggering the issue.",
                    "Disable GPU overclocking (including BIOS or third-party tools such as Afterburner).",
                    "Inspect the PCIe slot and power cables; reseat the GPU or replace cables if necessary.",
                ] + suggestions
            if permission_issue == "no_permission":
                if sys.platform.startswith("linux"):
                    suggestions.insert(
                        0, "Run `sudo dmesg | tail -50` or `journalctl -k` to inspect kernel logs manually."
                    )
                elif sys.platform == "win32":
                    suggestions.insert(
                        0, "Run ComfyUI as administrator to read the Windows Event Log."
                    )

        system_context = {
            "snapshot_trend": trend,
            "crash_findings": findings,
            "permission_issue": permission_issue,
        }

        status = "error" if matched else "warning"
        severity = "error" if matched else "warning"
        category_label = _CRASH_CATEGORY_LABELS.get(language, _CRASH_CATEGORY_LABELS["en"])

        # 确保 suggestions 是字符串列表（过滤空值并转字符串）
        suggestions = [str(s) for s in suggestions if isinstance(s, (str,)) and s.strip()]

        return DiagReport(
            error_node=None,
            matched=matched,
            category="crash",
            category_label=category_label,
            status=status,
            severity=severity,
            title=title,
            explanation=explanation,
            suggestions=suggestions,
            raw_error=log_output,
            node_info={"system_snapshot": system_context},
            system_context=system_context,
            language=language,
            timestamp=time.time(),
        )


# ============================================================================
# 便捷接口
# ============================================================================


def manual_diagnose_crash(language: Optional[str] = None) -> DiagReport:
    """一键触发崩溃/黑屏/掉驱动诊断。"""
    reader = LogReader(language=language)
    return reader.manual_diagnose_crash()
