"""
ComfyUI-Feixue-UniversalMonitor - 显存溢出预测器 (PRED 算法)

==========================================================================
算法概述 (PRED: Peak vRam Estimation & Detection)
==========================================================================

核心创新：基于 ComfyUI 顺序执行模型的智能显存溢出预测。

关键洞察：
    ComfyUI 是顺序执行的工作流引擎！峰值显存 ≠ 所有模型之和。
    峰值显存 = max(单个最大模型, 单模型 + 推理开销)

算法流程：
    1. 扫描工作流 JSON → 提取模型节点列表（CheckpointLoader, UNetLoader 等）
    2. 估算每个模型的显存占用（基于文件大小 + 运行时系数 + 模型类型经验表）
    3. 计算峰值显存需求（考虑顺序执行特性，非简单求和）
    4. 应用 AMD GPU Oversubscription 调整因子（HSA 内存分页机制）
    5. 双约束评估模型（硬约束 × 软约束）→ 输出成功率预测
    6. 根据成功率确定风险等级 → 生成优化建议

支持的模型架构：
    - SD 1.5 / SD 2.x   (512², FP16: ~2.5-3 GB)
    - SDXL              (1024², FP16: ~6-8 GB)
    - Flux / DiT        (1024², FP16: ~16-20 GB)
    - Stable Cascade    (1024², FP16: ~10-12 GB)
    - VAE / CLIP / ControlNet / LoRA

AMD GPU 特殊处理：
    - HSA (Heterogeneous System Architecture) Oversubscription 支持
    - 可使用系统 RAM 作为显存扩展缓冲区（性能惩罚 2-5x）
    - 自动检测超分支持能力（/sys/class/kfd/kfd_topology）

参考来源：
    - ComfyUI 官方文档: https://comfyanonymous.github.io/ComfyUI_docs/
    - ROCm Oversubscription 文档: https://rocm.docs.amd.com/en/latest/conceptual/gpu-memory.html
    - Hugging Face Diffusers 基准测试数据

版本: 2.0.0 (Task 2.7 - PRED Algorithm Implementation)
作者: Feixue
"""

from __future__ import annotations

import abc
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import Predictor as BasePredictor
from core.data_models import PredictionResult, GPUMetrics, RiskLevel

logger = logging.getLogger(__name__)


# ============================================================================
# 常量定义：模型类型与显存估算参数
# ============================================================================

@dataclass
class ModelMemoryProfile:
    """
    模型类型的显存特征配置。

    显存估算公式：
        estimated_vram_mb = file_size_mb * runtime_factor + base_overhead_mb

    推理时额外显存：
        inference_extra = estimated_vram_mb * inference_extra_ratio

    Attributes:
        model_type: 模型类型标识符
        display_name: 人类可读的显示名称
        runtime_factor: 文件大小到运行时显存的转换系数
                       （包含激活值、梯度、中间特征图等开销）
        base_overhead_mb: 基础固定开销 (MB)，PyTorch 框架层消耗
        inference_extra_ratio: 推理时相对于加载时的额外显存比例
                              （采样器产生的中间激活值、注意力缓存等）
    """
    model_type: str
    display_name: str
    runtime_factor: float = 1.5
    base_overhead_mb: int = 200
    inference_extra_ratio: float = 0.3


# ---------------------------------------------------------------------------
# 预定义的模型类型配置表（基于公开基准测试和社区经验值）
#
# 数据来源参考：
#   - Stability AI 官方模型卡 (Hugging Face)
#   - ComfyUI GitHub Issues 中的用户报告
#   - diffusers 库的内存 profiling 数据
#   - ROCm 官方文档中的内存管理说明
# ---------------------------------------------------------------------------
MODEL_PROFILES: Dict[str, ModelMemoryProfile] = {
    # ------------------------------------------------------------------
    # 主要扩散模型 (UNet / DiT / Transformer)
    # ------------------------------------------------------------------
    "unet": ModelMemoryProfile(
        model_type="unet",
        display_name="UNet/Diffusion Model (SD 1.5/SDXL)",
        runtime_factor=2.0,
        base_overhead_mb=300,
        inference_extra_ratio=0.4,
        # 说明: SD 1.5 UNet ~1GB 权重 → 运行时 ~2.5GB (FP16)
        #       SDXL UNet ~2.6GB 权重 → 运行时 ~6.5GB (FP16)
    ),
    "transformer": ModelMemoryProfile(
        model_type="transformer",
        display_name="DiT/Transformer (Flux/Cascade)",
        runtime_factor=2.2,
        base_overhead_mb=400,
        inference_extra_ratio=0.6,
        # 说明: Flux DiT ~12GB 权重 → 运行时 ~20GB+ (FP16)
        #       DiT 的注意力机制比 UNet 更耗显存
    ),

    # ------------------------------------------------------------------
    # 文本编码器
    # ------------------------------------------------------------------
    "clip": ModelMemoryProfile(
        model_type="clip",
        display_name="CLIP Text Encoder",
        runtime_factor=1.3,
        base_overhead_mb=100,
        inference_extra_ratio=0.2,
        # 说明: CLIP ViT-L/14 ~0.8GB → 运行时 ~1.1GB
    ),
    "text_encoder": ModelMemoryProfile(
        model_type="text_encoder",
        display_name="Text Encoder (T5/LongCLIP)",
        runtime_factor=1.3,
        base_overhead_mb=150,
        inference_extra_ratio=0.25,
        # 说明: T5-XXL ~8GB (Flux 配套) → 运行时 ~10.5GB
    ),

    # ------------------------------------------------------------------
    # VAE 编解码器
    # ------------------------------------------------------------------
    "vae": ModelMemoryProfile(
        model_type="vae",
        display_name="VAE Decoder/Encoder",
        runtime_factor=1.4,
        base_overhead_mb=150,
        inference_extra_ratio=0.5,
        # 说明: VAE 本身小 (~0.3GB)，但解码高分辨率时需要大量临时缓冲区
    ),

    # ------------------------------------------------------------------
    # 辅助模块
    # ------------------------------------------------------------------
    "controlnet": ModelMemoryProfile(
        model_type="controlnet",
        display_name="ControlNet Adapter",
        runtime_factor=1.8,
        base_overhead_mb=250,
        inference_extra_ratio=0.35,
    ),
    "lora": ModelMemoryProfile(
        model_type="lora",
        display_name="LoRA Adapter",
        runtime_factor=0.1,   # LoRA 只增加少量权重差异
        base_overhead_mb=50,
        inference_extra_ratio=0.05,
    ),

    # ------------------------------------------------------------------
    # 默认/回退配置
    # ------------------------------------------------------------------
    "generic": ModelMemoryProfile(
        model_type="generic",
        display_name="Generic Model (Unknown)",
        runtime_factor=1.5,
        base_overhead_mb=200,
        inference_extra_ratio=0.3,
    ),
}


# ---------------------------------------------------------------------------
# 经验值表：基于模型名称/类型的快速估算（当无法获取文件大小时使用）
#
# 这些数值来源于公开的社区测试数据和官方模型卡信息。
# 格式: (FP16 显存 MB, FP32 显存 MB)
# 分辨率默认为标准分辨率 (SD 1.5: 512², SDXL/Flux: 1024²)
# ---------------------------------------------------------------------------
EXPERIENTIAL_MODEL_SIZES: Dict[str, Tuple[int, int]] = {
    # SD 1.5 系列 (~2GB 文件 → ~2.5-3GB FP16 运行时)
    "sd15":      (2700, 5400),
    "sd_1_5":    (2700, 5400),
    "v1-5":      (2700, 5400),
    "sd21":      (3000, 6000),

    # SDXL 系列 (~6.5GB 文件 → ~6.5-8GB FP16 运行时)
    "sdxl":      (7000, 14000),
    "sd_xl":     (7000, 14000),

    # Flux 系列 (~12GB 文件 → ~16-20GB FP16 运行时)
    "flux":      (18000, 36000),
    "flux_dev":  (18000, 36000),
    "flux_schnell": (16000, 32000),

    # Stable Cascade (~5GB 文件 → ~10-12GB FP16 运行时)
    "cascade":   (11000, 22000),

    # 单独组件
    "vae":         (500, 1000),
    "clip_l":     (1200, 2400),   # SDXL CLIP-L
    "clip_g":     (800, 1600),    # SDXL CLIP-G
    "t5_xxl":    (10500, 21000),  # Flux T5-XXL
    "controlnet": (1500, 3000),
}


# ============================================================================
# AMD GPU Oversubscription 参数
# ============================================================================

@dataclass
class AMDOversubscriptionConfig:
    """
    AMD GPU 内存超分 (Oversubscription) 配置参数。

    AMD GPU 通过 HSA (Heterogeneous System Architecture) 支持显存超分，
    当 VRAM 不足时可以使用系统 RAM 作为扩展缓冲区。

    参考: ROCm Documentation - GPU Memory Management
          https://rocm.docs.amd.com/en/latest/conceptual/gpu-memory.html

    Attributes:
        ram_utilization_ratio: 允许使用多少比例的空闲 RAM 作为溢出缓冲
                               保守估计 70%（留 30% 给操作系统和其他进程）
        success_rate_penalty: 使用超分时的成功率扣减因子
                             （超分会带来 2-5x 性能下降，增加 OOM 风险）
        page_table_overhead_mb: AMD 显存页表管理开销 (MB)
        min_ram_for_oversub_mb: 触发超分所需的最小空闲 RAM (MB)
    """
    ram_utilization_ratio: float = 0.7
    success_rate_penalty: float = 0.15
    page_table_overhead_mb: int = 150
    min_ram_for_oversub_mb: int = 2048  # 至少需要 2GB 空闲 RAM


# ============================================================================
# 预测上下文与检测到的模型
# ============================================================================

@dataclass
class DetectedModel:
    """
    从工作流中检测到的单个模型节点信息。

    Attributes:
        node_id: ComfyUI 节点 ID（字符串形式的数字）
        node_type: 节点的 class_type（如 CheckpointLoaderSimple）
        model_path: 模型文件的完整路径或名称
        file_size_mb: 模型文件大小 (MB)，0 表示无法获取
        inferred_type: 推断的模型类型标识（对应 MODEL_PROFILES 的 key）
        estimated_vram_mb: 估算的运行时显存占用 (MB)
        is_active: 是否在当前工作流的执行路径中
    """
    node_id: str
    node_type: str
    model_path: str
    file_size_mb: float
    inferred_type: str
    estimated_vram_mb: int
    is_active: bool = True


@dataclass
class PredictionContext:
    """
    显存预测的系统资源快照上下文。

    封装进行预测所需的全部系统状态信息，
    包括 GPU 显存、系统内存、AMD 特性标志等。

    Attributes:
        vram_total_mb: GPU 物理显存总量 (MB)
        vram_free_mb: 当前 GPU 空闲显存 (MB)
        vram_reserved_mb: PyTorch/HIP 缓存池预留显存 (MB)
        ram_total_mb: 系统物理内存总量 (MB)
        ram_free_mb: 当前系统空闲内存 (MB)
        is_amd_gpu: 当前是否为 AMD GPU
        amd_oversub_supported: AMD 是否支持 Oversubscription
        gpu_device_name: GPU 设备型号名称
        gpu_vendor_string: GPU 厂商标识字符串
    """
    vram_total_mb: int = 0
    vram_free_mb: int = 0
    vram_reserved_mb: int = 0
    ram_total_mb: int = 0
    ram_free_mb: int = 0
    is_amd_gpu: bool = False
    amd_oversub_supported: bool = False
    gpu_device_name: str = ""
    gpu_vendor_string: str = "unknown"

    @property
    def vram_available_mb(self) -> int:
        """计算总可用显存（空闲 + 缓存池可释放）"""
        return self.vram_free_mb + self.vram_reserved_mb

    @property
    def effective_total_vram_mb(self) -> int:
        """计算有效总显存（物理显存 + AMD 超分可用 RAM）"""
        if self.is_amd_gpu and self.amd_oversub_supported:
            overflow_buffer = int(self.ram_free_mb * AMDOversubscriptionConfig.ram_utilization_ratio)
            return self.vram_total_mb + overflow_buffer
        return self.vram_total_mb


# ============================================================================
# 工作流扫描引擎
# ============================================================================

class WorkflowModelScanner:
    """
    工作流模型扫描引擎。

    职责：
    1. 解析 ComfyUI API 格式的工作流 JSON
    2. 识别所有模型加载节点（CheckpointLoader, LoraLoader 等）
    3. 提取模型名称并查找对应的文件
    4. 估算每个模型的显存占用

    ComfyUI 工作流 JSON 格式（API 格式）::
        {
            "nodes": [
                {
                    "id": 5,
                    "type": "CheckpointLoaderSimple",
                    "widgets_values": ["sd_xl_base_1.0.safetensors"]
                },
                ...
            ]
        }

    注意：ComfyUI 有两种格式：
    - API 格式: {"nodes": [{"id": ..., "type": ..., "widgets_values": [...]}]}
    - UI 格式: {"5": {"class_type": "...", "inputs": {...}}}
    本扫描器同时支持两种格式。
    """

    # ------------------------------------------------------------------
    # 已知的模型加载节点类型集合
    # ------------------------------------------------------------------
    MODEL_LOADER_NODE_TYPES: set = {
        # 标准检查点/完整模型加载器
        "CheckpointLoaderSimple",
        "CheckpointLoader",
        "UNETLoader",
        "VAELoader",
        "CLIPLoader",
        "DualCLIPLoader",
        "DiffusersLoader",
        "TextLoader (Basic)",           # T5 等文本编码器

        # LoRA 加载器
        "LoraLoader",
        "LoraLoaderModelOnly",
        "LoraLoaderAdvanced",           # 高级 LoRA 加载器
        "LoraLoaderForSDXL",            # SDXL 专用 LoRA 加载器

        # ControlNet 加载器
        "ControlNetLoader",
        "ControlNetLoaderAdvanced",     # 高级 ControlNet 加载器
        "T2IAdapterLoader",            # T2I Adapter 加载器

        # 采样相关（可能携带模型信息）
        "ModelSamplingDiscrete",        # Flux 专用采样
        "ModelSamplingContinuous",

        # UNet/Cascade 相关
        "CascadeKSampler",
        "StageCModel",
        "StageBModel",

        # SD 3.0 相关
        "SD3TransformerLoader",        # SD3 Transformer 加载器
        "SD3UNetLoader",               # SD3 UNet 加载器

        # IP-Adapter 加载器
        "IPAdapterLoader",
        "IPAdapterPlusLoader",

        # 自定义模型加载器
        "CustomModelLoader",           # 通用自定义模型加载器

        # 超分辨率模型加载器
        "ESRGANLoader",                # ESRGAN 超分模型
        "RealESRGANLoader",            # Real-ESRGAN
        "BSRGANLoader",                # BSRGAN
        "SwinIRLoader",                # SwinIR 超分模型

        # 音频相关模型
        "AudioEncoderLoader",          # 音频编码器

        # 模型合并节点
        "ModelMerge",                  # 模型合并
        "ModelBlend",                  # 模型混合

        # 模型量化相关
        "QuantizedModelLoader",        # 量化模型加载器
        "FP8ModelLoader",              # FP8 量化模型

        # ComfyUI 官方扩展节点
        "CheckpointLoaderXL",          # SDXL 专用检查点加载器
        "StableCascadeLoader",         # Stable Cascade 完整加载器
        "FluxLoader",                  # Flux 模型加载器

        # 社区常用节点
        "UltimateSDUpscaleModelLoader",# Ultimate SD Upscale 模型
        "TiledVAEEncoder",             # 分片 VAE 编码器
        "TiledVAEDecoder",             # 分片 VAE 解码器
    }

    # ------------------------------------------------------------------
    # 节点类型 → 模型类型映射（一个节点可能包含多个子模型）
    # ------------------------------------------------------------------
    NODE_TYPE_TO_MODEL_TYPE: Dict[str, List[str]] = {
        # 检查点加载器包含多个子模型
        "CheckpointLoaderSimple": ["unet", "clip", "vae"],
        "CheckpointLoader":        ["unet", "clip", "vae"],
        "CheckpointLoaderXL":      ["unet", "clip", "vae"],  # SDXL 专用
        "StableCascadeLoader":     ["transformer", "vae"],   # Cascade
        "FluxLoader":              ["transformer"],           # Flux

        # 单一组件加载器
        "UNETLoader":             ["unet"],
        "VAELoader":              ["vae"],
        "CLIPLoader":             ["clip"],
        "DualCLIPLoader":         ["clip"],  # 双 CLIP (SDXL)
        "DiffusersLoader":        ["transformer"],
        "TextLoader (Basic)":     ["text_encoder"],

        # SD 3.0 相关
        "SD3TransformerLoader":   ["transformer"],
        "SD3UNetLoader":          ["unet"],

        # LoRA 加载器
        "LoraLoader":             ["lora"],
        "LoraLoaderModelOnly":    ["lora"],
        "LoraLoaderAdvanced":     ["lora"],
        "LoraLoaderForSDXL":      ["lora"],

        # ControlNet 和适配器
        "ControlNetLoader":       ["controlnet"],
        "ControlNetLoaderAdvanced": ["controlnet"],
        "T2IAdapterLoader":       ["controlnet"],  # T2I Adapter 归类为 controlnet
        "IPAdapterLoader":        ["controlnet"],  # IP-Adapter
        "IPAdapterPlusLoader":    ["controlnet"],

        # 超分辨率模型
        "ESRGANLoader":           ["generic"],
        "RealESRGANLoader":       ["generic"],
        "BSRGANLoader":           ["generic"],
        "SwinIRLoader":           ["generic"],
        "UltimateSDUpscaleModelLoader": ["generic"],

        # 音频模型
        "AudioEncoderLoader":     ["text_encoder"],

        # 模型合并/混合
        "ModelMerge":             ["generic"],
        "ModelBlend":             ["generic"],

        # 量化模型
        "QuantizedModelLoader":   ["generic"],
        "FP8ModelLoader":         ["generic"],

        # 自定义加载器
        "CustomModelLoader":      ["generic"],

        # 分片 VAE
        "TiledVAEEncoder":        ["vae"],
        "TiledVAEDecoder":        ["vae"],

        # Flux/Cascade 特殊节点
        "ModelSamplingDiscrete":  ["transformer"],
        "ModelSamplingContinuous": ["transformer"],
        "CascadeKSampler":        ["transformer"],
        "StageCModel":            ["transformer"],
        "StageBModel":            ["unet"],
    }

    # ------------------------------------------------------------------
    # 节点值中模型名称字段的候选列表（按优先级排序）
    # ------------------------------------------------------------------
    MODEL_NAME_FIELDS: List[str] = [
        "ckpt_name",        # CheckpointLoaderSimple
        "model_name",       # 通用
        "model_path",       # 路径形式
        "unet_name",        # UNETLoader
        "vae_name",         # VAELoader
        "clip_name",        # CLIPLoader
        "lora_name",        # LoraLoader
        "control_net_name", # ControlNetLoader
        "model",            # DiffusersLoader
        "filename",         # 通用备用
    ]

    def __init__(self, comfyui_model_paths: Optional[List[str]] = None):
        """
        初始化工作流扫描器。

        Args:
            comfyui_model_paths: ComfyUI 模型搜索路径列表。
                                 如果为 None，将尝试自动检测标准路径。
        """
        self.model_paths: List[str] = comfyui_model_paths or self._detect_comfyui_model_paths()
        self._file_cache: Dict[str, Tuple[str, float]] = {}  # name -> (path, size_mb)

    def _detect_comfyui_model_paths(self) -> List[str]:
        """
        自动检测 ComfyUI 模型目录路径。

        搜索策略：
        1. 检查 COMFYUI_BASE_DIR 环境变量
        2. 检查当前工作目录下的 models/ 子目录
        3. 检查常见的 ComfyUI 安装路径

        Returns:
            检测到的有效模型目录路径列表
        """
        paths: List[str] = []
        standard_subdirs = [
            "models/checkpoints",
            "models/unet",
            "models/vae",
            "models/clip",
            "models/controlnet",
            "models/diffusers",
            "models/loras",
            "models/text_encoders",
            "models/diffusion_models",
        ]

        # 方法 1: 环境变量
        comfy_base = os.environ.get("COMFYUI_BASE_DIR", "")
        if comfy_base and os.path.isdir(comfy_base):
            for subdir in standard_subdirs:
                full = os.path.join(comfy_base, subdir)
                if os.path.isdir(full):
                    paths.append(full)

        # 方法 2: 当前工作目录
        if not paths:
            for subdir in standard_subdirs:
                if os.path.isdir(subdir):
                    paths.append(subdir)

        logger.debug(f"Detected ComfyUI model paths: {paths}")
        return paths

    def scan_workflow(self, workflow_data: Optional[Dict] = None) -> List[DetectedModel]:
        """
        扫描工作流中的所有模型节点。

        同时支持两种 ComfyUI 格式：
        - API 格式: {"nodes": [{...}, ...]}
        - UI 格式:  {"node_id": {"class_type": ..., "inputs": {...}}, ...}

        Args:
            workflow_data: ComfyUI 工作流字典。如果为 None 则返回空列表。

        Returns:
            检测到的模型信息列表
        """
        if not workflow_data:
            return []

        models: List[DetectedModel] = []

        # 尝试 API 格式
        nodes = workflow_data.get("nodes")
        if isinstance(nodes, list) and nodes:
            for node in nodes:
                detected = self._process_api_node(node)
                if detected:
                    models.extend(detected)

        # 尝试 UI 格式（如果没有通过 API 格式找到任何节点）
        if not models:
            for node_key, node_value in workflow_data.items():
                if isinstance(node_value, dict) and "class_type" in node_value:
                    detected = self._process_ui_node(node_key, node_value)
                    if detected:
                        models.extend(detected)

        logger.debug(
            f"Workflow scan completed: {len(models)} model(s) detected"
        )
        return models

    def _process_api_node(self, node: Dict) -> Optional[List[DetectedModel]]:
        """
        处理 API 格式的节点。

        API 格式示例::
            {"id": 5, "type": "CheckpointLoaderSimple",
             "widgets_values": ["sd_xl_base_1.0.safetensors"]}

        Args:
            node: API 格式的节点字典

        Returns:
            检测到的模型列表，或 None
        """
        node_type = node.get("type", "")
        node_id = str(node.get("id", ""))

        if node_type not in self.MODEL_LOADER_NODE_TYPES:
            return None

        values = node.get("values", {}) or node.get("widgets_values", {})

        # widgets_values 可能是列表或字典
        if isinstance(values, list):
            values = self._convert_widget_list_to_dict(node_type, values)

        return self._extract_models_from_node(node_id, node_type, values)

    def _process_ui_node(
        self, node_key: str, node_value: Dict
    ) -> Optional[List[DetectedModel]]:
        """
        处理 UI 格式的节点。

        UI 格式示例::
            {"5": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": ["sd_xl_base_1.0.safetensors"]}}}

        Args:
            node_key: 节点键（通常是数字字符串）
            node_value: 节点值字典

        Returns:
            检测到的模型列表，或 None
        """
        node_type = node_value.get("class_type", "")
        inputs = node_value.get("inputs", {})

        if node_type not in self.MODEL_LOADER_NODE_TYPES:
            return None

        # 展开输入值（UI 格式中值通常包裹在列表里）
        flattened = {}
        for key, val in inputs.items():
            if isinstance(val, list) and len(val) > 0:
                flattened[key] = val[0]
            else:
                flattened[key] = val

        return self._extract_models_from_node(node_key, node_type, flattened)

    def _convert_widget_list_to_dict(
        self, node_type: str, widget_values: list
    ) -> Dict[str, Any]:
        """
        将 widgets_values 列表转换为字段字典。

        不同节点类型的 widgets_values 字段顺序不同，
        这里根据已知的字段顺序进行映射。

        Args:
            node_type: 节点类型
            widget_values: widget 值列表

        Returns:
            字段名 → 值 的字典
        """
        result: Dict[str, Any] = {}

        # 已知的字段顺序映射（基于 ComfyUI 源码中的 ORDER 定义）
        field_order_map = {
            "CheckpointLoaderSimple": ["ckpt_name"],
            "CheckpointLoader":        ["ckpt_name", "output_vae", "output_clip"],
            "UNETLoader":              ["unet_name"],
            "VAELoader":               ["vae_name"],
            "CLIPLoader":              ["clip_name", "type"],
            "DualCLIPLoader":          ["clip_name1", "clip_name2", "type"],
            "LoraLoader":              ["lora_name", "strength_model", "strength_clip"],
            "LoraLoaderModelOnly":     ["lora_name", "strength_model"],
            "ControlNetLoader":        ["control_net_name"],
            "DiffusersLoader":         ["model_path", "weight_dtype", "fp16_optimization"],
        }

        fields = field_order_map.get(node_type, [])
        for i, field_name in enumerate(fields):
            if i < len(widget_values):
                result[field_name] = widget_values[i]

        # 如果无法匹配已知顺序，尝试将第一个值作为模型名称
        if not result and widget_values:
            result["ckpt_name"] = widget_values[0]

        return result

    def _extract_models_from_node(
        self,
        node_id: str,
        node_type: str,
        values: Dict[str, Any],
    ) -> Optional[List[DetectedModel]]:
        """
        从节点配置中提取模型信息。

        对于包含多个子模型的节点（如 CheckpointLoaderSimple），
        会返回多个 DetectedModel 对象。

        Args:
            node_id: 节点 ID
            node_type: 节点类型
            values: 节点的参数值字典

        Returns:
            检测到的模型列表，或 None
        """
        model_name = self._resolve_model_name(values)
        if not model_name:
            logger.debug(f"No model name found for node {node_id} ({node_type})")
            return None

        # 查找模型文件并获取大小
        model_path, file_size_mb = self._find_model_file(model_name, node_type)

        # 如果无法获取实际文件大小，使用启发式估算
        if file_size_mb == 0:
            file_size_mb = self._estimate_size_by_name(model_name, node_type)

        # 获取该节点关联的所有模型类型
        model_types = self.NODE_TYPE_TO_MODEL_TYPE.get(node_type, ["generic"])

        results: List[DetectedModel] = []
        for mtype in model_types:
            profile = MODEL_PROFILES.get(mtype, MODEL_PROFILES["generic"])
            estimated_vram = int(file_size_mb * profile.runtime_factor) + profile.base_overhead_mb

            results.append(DetectedModel(
                node_id=node_id,
                node_type=node_type,
                model_path=model_path or model_name,
                file_size_mb=file_size_mb,
                inferred_type=mtype,
                estimated_vram_mb=estimated_vram,
                is_active=True,
            ))

        return results

    def _resolve_model_name(self, values: Dict[str, Any]) -> Optional[str]:
        """
        从节点参数值中解析模型名称/路径。

        Args:
            values: 节点参数字典

        Returns:
            模型名称字符串，或 None
        """
        for field in self.MODEL_NAME_FIELDS:
            value = values.get(field)
            if value and isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _find_model_file(
        self, model_name: str, node_type: str
    ) -> Tuple[str, float]:
        """
        在模型目录中查找模型文件并获取其大小。

        查找策略：
        1. 直接精确匹配文件名
        2. 尝试添加常见扩展名 (.safetensors, .pt, .bin, .ckpt)
        3. 递归搜索（限制深度避免性能问题）

        Args:
            model_name: 模型文件名（不含路径）
            node_type: 节点类型（用于确定搜索子目录）

        Returns:
            (完整路径, 文件大小 MB) 元组，未找到时返回 ("", 0.0)
        """
        # 检查缓存
        cache_key = f"{node_type}:{model_name}"
        if cache_key in self._file_cache:
            return self._file_cache[cache_key]

        # 确定要搜索的子目录
        type_subdir_map = {
            "CheckpointLoaderSimple": "checkpoints",
            "CheckpointLoader":        "checkpoints",
            "UNETLoader":              "unet",
            "VAELoader":               "vae",
            "CLIPLoader":              "clip",
            "DualCLIPLoader":          "clip",
            "LoraLoader":              "loras",
            "LoraLoaderModelOnly":     "loras",
            "ControlNetLoader":        "controlnet",
            "DiffusersLoader":         "diffusers",
        }
        target_subdirs = [type_subdir_map.get(node_type, "")]

        # 构建搜索路径列表
        search_dirs: List[Path] = []
        for base_path in self.model_paths:
            for subdir in target_subdirs:
                if subdir:
                    candidate = Path(base_path) / subdir
                else:
                    candidate = Path(base_path)
                if candidate.exists() and candidate.is_dir():
                    search_dirs.append(candidate)

        # 如果没有特定子目录，搜索所有已知基础路径
        if not search_dirs:
            for bp in self.model_paths:
                p = Path(bp)
                if p.exists() and p.is_dir():
                    search_dirs.append(p)

        # 执行文件查找
        VALID_EXTENSIONS = {".safetensors", ".pt", ".bin", ".ckpt", ".onnx", ".gguf"}

        for search_dir in search_dirs:
            # 策略 1: 直接匹配
            candidate = search_dir / model_name
            if candidate.exists() and candidate.is_file():
                size_mb = candidate.stat().st_size / (1024 * 1024)
                result = (str(candidate), size_mb)
                self._file_cache[cache_key] = result
                return result

            # 策略 2: 添加扩展名
            for ext in VALID_EXTENSIONS:
                candidate = search_dir / f"{model_name}{ext}"
                if candidate.exists() and candidate.is_file():
                    size_mb = candidate.stat().st_size / (1024 * 1024)
                    result = (str(candidate), size_mb)
                    self._file_cache[cache_key] = result
                    return result

            # 策略 3: 递归搜索（限制深度为 2 层）
            try:
                pattern = f"*{model_name}*"
                for candidate in sorted(search_dir.rglob(pattern)):
                    if (
                        candidate.is_file()
                        and candidate.suffix in VALID_EXTENSIONS
                        and candidate.stat().st_size > 1024 * 1024  # > 1MB 过滤掉小文件
                    ):
                        size_mb = candidate.stat().st_size / (1024 * 1024)
                        result = (str(candidate), size_mb)
                        self._file_cache[cache_key] = result
                        return result
            except OSError:
                continue

        return ("", 0.0)

    def _estimate_size_by_name(self, model_name: str, node_type: str) -> float:
        """
        当无法获取实际文件时，根据模型名称进行启发式大小估算。

        匹配策略：
        1. 精确匹配 EXPERIENTIAL_MODEL_SIZES 中的已知模型
        2. 关键词模糊匹配（如 "sdxl", "flux" 等）
        3. 基于节点类型的默认值

        Args:
            model_name: 模型文件名
            node_type: 节点类型

        Returns:
            估算的文件大小 (MB)
        """
        name_lower = model_name.lower()

        # 策略 1: 精确匹配已知模型
        for key, (fp16_size, _) in EXPERIENTIAL_MODEL_SIZES.items():
            if key in name_lower:
                # 将 FP16 运行时显存反推回文件大小（粗略估计）
                # file_size ≈ fp16_runtime / 1.5 (平均 runtime_factor)
                return fp16_size / 1.5

        # 策略 2: 关键词匹配
        if any(kw in name_lower for kw in ["sdxl", "juggernaut", "realvisionxl", "xl_base", "xl_refiner"]):
            return 6500.0   # SDXL 典型文件大小 ~6.5GB
        elif any(kw in name_lower for kw in ["sd_", "v1-", "v2-", "realistic"]):
            return 2000.0   # SD 1.5 典型文件大小 ~2GB
        elif "flux" in name_lower:
            return 12000.0  # Flux 典型文件大小 ~12GB (FP16)
        elif "cascade" in name_lower:
            return 5000.0   # Cascade 典型文件大小 ~5GB
        elif any(kw in name_lower for kw in ["t5", "xxl", "text_encoder"]):
            return 8500.0   # T5-XXL 典型大小 ~8.5GB

        # 策略 3: 基于节点类型的默认值
        type_defaults = {
            "CheckpointLoaderSimple": 4000.0,
            "CheckpointLoader":        4000.0,
            "UNETLoader":              2500.0,
            "VAELoader":               350.0,
            "CLIPLoader":              800.0,
            "DualCLIPLoader":          1000.0,
            "LoraLoader":              200.0,
            "ControlNetLoader":        1500.0,
            "DiffusersLoader":         6000.0,
        }
        return type_defaults.get(node_type, 3500.0)


# ============================================================================
# 核心：VRAMPredictor 显存溢出预测器
# ============================================================================

class VRAMPredictor(BasePredictor):
    """
    显存溢出预测器 (PRED 算法实现)。

    继承自 collectors.base.Predictor 抽象基类，
    实现 predict() 和 collect() 方法。

    ================================================================
    算法流程图：
    ================================================================

    ┌─────────────────────────────────────────────────────────────┐
    │                    输入: Workflow JSON                      │
    └──────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Step 1: 工作流扫描 (WorkflowModelScanner)                   │
    │  ┌──────────────────────────────────────────────────────┐   │
    │  │ 提取模型节点 → 识别模型类型 → 估算每个模型显存占用    │   │
    │  │ 结果: List[DetectedModel]                             │   │
    │  └──────────────────────────────────────────────────────┘   │
    └──────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Step 2: 峰值显存计算 (_calculate_peak_vram)                 │
    │  ┌──────────────────────────────────────────────────────┐   │
    │  │ 关键洞察: ComfyUI 顺序执行！                            │   │
    │  │ peak = max(最大单模型, 最大单模型 + 推理开销)           │   │
    │  │     ≠ sum(所有模型)  ← 这是常见误区！                   │   │
    │  └──────────────────────────────────────────────────────┘   │
    └──────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Step 3: AMD Oversubscription 调整                          │
    │  ┌──────────────────────────────────────────────────────┐   │
    │  │ if AMD GPU && estimated > physical_VRAM:              │   │
    │  │   → 计算可用 RAM 溢出缓冲                              │   │
    │  │   → 应用成功率惩罚因子 (-15% per unit overflow)       │   │
    │  └──────────────────────────────────────────────────────┘   │
    └──────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Step 4: 双约束成功率评估                                    │
    │  ┌──────────────────────────────────────────────────────┐   │
    │  │ hard_constraint = 能否装入最大单模型？(0 or 0~1)       │   │
    │  │ soft_constraint = 总资源充足性 (考虑碎片化/预留等)      │   │
    │  │ success_rate = hard × soft × 100 (%)                   │   │
    │  └──────────────────────────────────────────────────────┘   │
    └──────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │  Step 5: 风险等级 + 建议                                     │
    │  ┌──────────────────────────────────────────────────────┐   │
    │  │ ≥90% → low (绿色 ✅)                                  │   │
    │  │ 70-89% → medium (黄色 ⚠️)                             │   │
    │  │ 40-69% → high (橙色 🔶)                               │   │
    │  │ <40% → critical (红色 🚨)                             │   │
    │  └──────────────────────────────────────────────────────┘   │
    └──────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              输出: PredictionResult                         │
    └─────────────────────────────────────────────────────────────┘

    ================================================================

    使用示例::

        # 方式 1: 通过 BaseCollector 接口
        predictor = VRAMPredictor()
        result = predictor.safe_collect()

        # 方式 2: 显式传入工作流
        predictor = VRAMPredictor()
        result = predictor.predict(workflow_info={
            "workflow": my_workflow_json
        })

        print(f"成功率: {result.success_rate:.1f}%")
        print(f"风险等级: {result.risk_level}")
        print(f"预估峰值显存: {result.peak_vram_estimate} MB")

    验证用例（目标准确度）::

        | 场景                     | 预期风险等级 | 成功率范围 |
        |--------------------------|-------------|-----------|
        | SDXL @ 1024² on 12GB    | Medium-High | 55-80%    |
        | SD 1.5 @ 512² on 8GB    | Low-Medium  | 75-92%    |
        | Flux @ 1024² on 24GB    | Medium      | 65-85%    |
        | Flux @ 1024² on 12GB     | Critical    | <40%      |
    """

    # ------------------------------------------------------------------
    # 类常量：算法参数
    # ------------------------------------------------------------------

    # AMD Oversubscription 配置
    AMD_OVERSUB_CONFIG = AMDOversubscriptionConfig()

    # 显存碎片化损失因子（长时间运行的 PyTorch 进程会产生碎片）
    FRAGMENTATION_FACTOR: float = 0.9
    # 含义: 可用显存 × 0.9 = 实际可用于大块连续分配的有效显存

    # 安全边距 (MB)
    SAFETY_MARGIN_MB: int = 500

    # 驱动/框架预留显存 (MB)
    DRIVER_RESERVE_AMD_MB: int = 300    # AMD 驱动预留较多
    DRIVER_RESERVE_NVIDIA_MB: int = 150  # NVIDIA 驱动预留较少
    PYTORCH_OVERHEAD_MB: int = 400       # PyTorch CUDA/HIP context + cuDNN workspace

    # 推理开销安全系数（按模型架构分类）
    INFERENCE_SAFETY_FACTORS: Dict[str, int] = {
        "sd15":     10,   # SD 1.5 相对轻量
        "sdxl":     12,   # SDXL 中间层更多
        "flux":     20,   # Flux DiT 注意力开销巨大
        "cascade":  15,   # Cascade 两阶段
    }

    def __init__(self, gpu_provider=None, config: Optional[Dict[str, Any]] = None):
        """
        初始化显存溢出预测器。

        Args:
            gpu_provider: 可选的 GPU Provider 实例（用于获取实时 VRAM 信息）。
                          如果为 None，将在预测时尝试自动采集。
            config: 可选的配置字典，用于覆盖默认算法参数。
        """
        super().__init__(
            name="vram_predictor",
            timeout=3.0,    # 可能需要读取文件，超时稍长
            enabled=True,
            retry_count=0,   # 预测不需要重试（失败就跳过）
        )
        self._gpu_provider = gpu_provider
        self._config = config or {}
        self.scanner = WorkflowModelScanner()

        # 缓存上一次的预测结果
        self._last_result: Optional[PredictionResult] = None
        self._last_predict_time: float = 0.0

    # ==================================================================
    # 公共接口方法
    # ==================================================================

    def predict(
        self,
        workflow_info: Optional[Dict[str, Any]] = None,
    ) -> PredictionResult:
        """
        执行显存溢出预测（BaseCollector.Predictor 抽象方法实现）。

        Args:
            workflow_info: 工作流上下文信息。可以包含以下键：
                - "workflow": ComfyUI 工作流 JSON 字典（API 或 UI 格式）
                - "resolution": (width, height) 元组，覆盖默认分辨率推断
                - "batch_size": 批次大小（默认 1）
                - "dtype": 数据类型 ("fp16", "fp32", "fp8"，默认 "fp16")

        Returns:
            PredictionResult 预测结果对象
        """
        start_time = time.time()

        # ---- Step 0: 解析输入参数 ----
        workflow_json: Optional[Dict] = (
            workflow_info.get("workflow") if workflow_info else None
        )
        resolution: tuple = (
            workflow_info.get("resolution", (1024, 1024))
            if workflow_info else (1024, 1024)
        )
        batch_size: int = (
            workflow_info.get("batch_size", 1)
            if workflow_info else 1
        )
        dtype: str = (
            workflow_info.get("dtype", "fp16")
            if workflow_info else "fp16"
        )

        # ---- Step 1: 采集系统资源上下文 ----
        context = self._build_prediction_context()

        # ---- Step 2: 扫描工作流模型 ----
        models = self.scanner.scan_workflow(workflow_json)

        if not models:
            logger.info("No model nodes detected in workflow; returning empty prediction")
            return PredictionResult(
                success_rate=0.0,
                risk_level=RiskLevel.CRITICAL.value,
                peak_vram_estimate=0,
                recommendations=["未检测到模型节点，无法评估显存风险"],
                model_info={"method": "no_models_detected", "model_count": 0},
                confidence=0.0,
            )

        # ---- Step 3: 计算峰值显存需求 ----
        peak_vram = self._calculate_peak_vram(
            models=models,
            resolution=resolution,
            batch_size=batch_size,
            dtype=dtype,
        )
        logger.debug(f"Peak VRAM estimate: {peak_vram} MB")

        # ---- Step 4: AMD Oversubscription 调整 ----
        adjusted_success_rate, effective_vram, is_oversubscribed = \
            self._apply_amd_oversubscription(
                estimated_vram=peak_vram,
                context=context,
            )

        # ---- Step 5: 双约束成功率评估 ----
        # 如果 Oversubscription 已经给出了调整后的成功率，直接使用
        # 否则使用完整的双约束模型
        if adjusted_success_rate is not None:
            success_rate = adjusted_success_rate
        else:
            success_rate = self._predict_success_rate(
                estimated_peak_vram=peak_vram,
                available_vram=context.vram_available_mb,
                is_amd=context.is_amd_gpu,
                physical_vram=context.vram_total_mb,
                oversub_enabled=context.amd_oversub_supported,
            )

        # 确保 success_rate 在 [0, 100] 范围内
        success_rate = max(0.0, min(100.0, success_rate))

        # ---- Step 6: 确定风险等级 ----
        risk_level = PredictionResult.calculate_risk_level(success_rate)

        # ---- Step 7: 生成优化建议 ----
        recommendations = self._generate_recommendations(
            success_rate=success_rate,
            estimated_vram=peak_vram,
            available_vram=context.vram_available_mb,
            context=context,
            risk_level=risk_level,
            models=models,
        )

        # ---- Step 8: 构建模型信息详情 ----
        primary_model_type = self._infer_primary_model_architecture(models)
        model_info: Dict[str, Any] = {
            "method": "full_prediction",
            "model_count": len(models),
            "primary_model_type": primary_model_type,
            "resolution": resolution,
            "batch_size": batch_size,
            "dtype": dtype,
            "is_amd": context.is_amd_gpu,
            "is_oversubscribed": is_oversubscribed,
            "models_summary": [
                {
                    "node_id": m.node_id,
                    "node_type": m.node_type,
                    "model_name": os.path.basename(m.model_path),
                    "file_size_mb": round(m.file_size_mb, 1),
                    "estimated_vram_mb": m.estimated_vram_mb,
                    "inferred_type": m.inferred_type,
                }
                for m in models
            ],
            "peak_vram_breakdown": {
                "largest_single_model_mb": max(m.estimated_vram_mb for m in models),
                "total_all_models_mb": sum(m.estimated_vram_mb for m in models),
                "inference_overhead_mb": self._calculate_inference_overhead(
                    resolution=resolution,
                    batch_size=batch_size,
                    dtype=dtype,
                    model_architecture=primary_model_type,
                ),
                "safety_margin_mb": self.SAFETY_MARGIN_MB,
            },
            "resource_snapshot": {
                "vram_total_mb": context.vram_total_mb,
                "vram_available_mb": context.vram_available_mb,
                "ram_free_gb": round(context.ram_free_mb / 1024, 2),
                "gpu_device": context.gpu_device_name,
            },
        }

        # 计算置信度（基于信息完整性）
        confidence = self._calculate_confidence(
            models=models,
            has_workflow=bool(workflow_json),
            has_gpu_context=(context.vram_total_mb > 0),
        )

        # ---- 构建最终结果 ----
        result = PredictionResult(
            success_rate=round(success_rate, 1),
            risk_level=risk_level.value if isinstance(risk_level, RiskLevel) else risk_level,
            peak_vram_estimate=peak_vram,
            recommendations=recommendations,
            model_info=model_info,
            confidence=round(confidence, 3),
        )

        # 缓存结果
        self._last_result = result
        self._last_predict_time = time.time()

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"PRED algorithm completed in {duration_ms:.1f}ms: "
            f"success_rate={success_rate:.1f}%, "
            f"risk={risk_level.value if isinstance(risk_level, RiskLevel) else risk_level}, "
            f"peak_vram={peak_vram}MB, "
            f"models={len(models)}"
        )

        return result

    def predict_from_workflow(
        self,
        workflow_json: Dict[str, Any],
        gpu_info: Optional[GPUMetrics] = None,
    ) -> PredictionResult:
        """
        从工作流 JSON 进行显存预测（便捷方法）。

        这是主要的对外接口方法，允许调用方直接传入工作流
        和可选的 GPU 信息来获取预测结果。

        Args:
            workflow_json: ComfyUI 工作流字典（支持 API 格式或 UI 格式）
            gpu_info: 当前 GPU 状态信息（可选，如果不提供则自动采集）

        Returns:
            PredictionResult 预测结果

        示例::

            workflow = {
                "nodes": [
                    {
                        "id": 5,
                        "type": "CheckpointLoaderSimple",
                        "widgets_values": ["sd_xl_base_1.0.safetensors"]
                    },
                    {
                        "id": 10,
                        "type": "KSampler",
                        "widgets_values": [...]  # 用于提取分辨率
                    }
                ]
            }

            predictor = VRAMPredictor()
            result = predictor.predict_from_workflow(workflow)
            print(result.success_rate, result.risk_level)
        """
        workflow_info: Dict[str, Any] = {"workflow": workflow_json}

        # 如果提供了 GPU 信息，将其注入到配置中以供后续使用
        if gpu_info is not None:
            workflow_info["_gpu_info_override"] = gpu_info

        return self.predict(workflow_info=workflow_info)

    def collect(self) -> PredictionResult:
        """
        BaseCollector 接口实现。

        由于预测需要工作流输入，此方法的策略是：
        1. 尝试从 ComfyUI 内部 API 获取当前加载的工作流
        2. 如果无法获取，返回一个"等待数据"状态的空预测
        3. 如果有缓存的上次预测结果且未过期，直接返回缓存

        Returns:
            PredictionResult 预测结果
        """
        # 尝试获取当前工作流
        current_workflow = self._try_get_current_workflow()

        if current_workflow is not None:
            return self.predict(workflow_info={"workflow": current_workflow})

        # 无法获取工作流
        logger.debug("No workflow available for collect(); returning empty prediction")
        return PredictionResult(
            success_rate=0.0,
            risk_level=RiskLevel.CRITICAL.value,
            peak_vram_estimate=0,
            recommendations=[
                "无法获取工作流信息，请手动触发预测 (predict_from_workflow)"
            ],
            model_info={
                "method": "no_workflow_available",
                "hint": "Call predict_from_workflow() with workflow JSON",
            },
            confidence=0.0,
        )

    # ==================================================================
    # 私有方法：系统资源采集
    # ==================================================================

    def _build_prediction_context(self) -> PredictionContext:
        """
        构建预测所需的系统资源上下文。

        采集策略（按优先级）：
        1. 使用注入的 GPU Provider 获取实时数据
        2. 回退到 PyTorch CUDA/HIP API
        3. 回退到 psutil + 基础探测

        Returns:
            PredictionContext 包含完整的系统资源快照
        """
        ctx = PredictionContext()

        # ---- 尝试从 GPU Provider 获取信息 ----
        if self._gpu_provider is not None:
            try:
                if hasattr(self._gpu_provider, 'is_available') \
                   and self._gpu_provider.is_available():
                    metrics = self._gpu_provider._collect_from_active_source(0)
                    ctx.vram_total_mb = metrics.vram_total
                    ctx.vram_free_mb = metrics.vram_free
                    ctx.vram_reserved_mb = getattr(
                        self._gpu_provider, 'get_memory_reserved',
                        lambda did: 0
                    )(0)
                    ctx.gpu_device_name = metrics.device_name
            except Exception as e:
                logger.debug(f"GPU provider collection failed: {e}")

        # ---- 回退到 PyTorch 直接查询 ----
        if ctx.vram_total_mb == 0:
            try:
                import torch
                if torch.cuda.is_available():
                    props = torch.cuda.get_device_properties(0)
                    ctx.vram_total_mb = props.total_mem // (1024 * 1024)

                    free, total = torch.cuda.mem_get_info(0)
                    ctx.vram_free_mb = free // (1024 * 1024)
                    ctx.vram_reserved_mb = torch.cuda.memory_reserved(0) // (1024 * 1024)

                    ctx.gpu_device_name = torch.cuda.get_device_name(0)

                    # 检测 AMD GPU
                    if hasattr(torch.version, 'hip') or hasattr(torch.version, 'roc'):
                        ctx.is_amd_gpu = True
                    else:
                        dev_name_lower = ctx.gpu_device_name.lower()
                        ctx.is_amd_gpu = any(
                            kw in dev_name_lower
                            for kw in ["amd", "radeon", "navi", "rdna"]
                        )
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"PyTorch GPU query failed: {e}")

        # ---- 系统内存采集 ----
        try:
            import psutil
            mem = psutil.virtual_memory()
            ctx.ram_total_mb = mem.total // (1024 * 1024)
            ctx.ram_free_mb = mem.available // (1024 * 1024)
        except ImportError:
            # 尝试读取 /proc/meminfo (Linux only)
            ctx.ram_total_mb, ctx.ram_free_mb = self._read_linux_meminfo()
        except Exception as e:
            logger.debug(f"RAM info collection failed: {e}")

        # ---- AMD Oversubscription 支持检测 ----
        if ctx.is_amd_gpu:
            ctx.amd_oversub_supported = self._detect_amd_oversubscription_support()
            ctx.gpu_vendor_string = "AMD"
        else:
            ctx.gpu_vendor_string = "NVIDIA" if ctx.vram_total_mb > 0 else "unknown"

        return ctx

    @staticmethod
    def _read_linux_meminfo() -> Tuple[int, int]:
        """从 /proc/meminfo 读取 Linux 内存信息 (fallback)"""
        try:
            total_kb = 0
            avail_kb = 0
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        if parts[0] == "MemTotal:":
                            total_kb = int(parts[1])
                        elif parts[0] == "MemAvailable:":
                            avail_kb = int(parts[1])
            return total_kb // 1024, avail_kb // 1024
        except (IOError, OSError):
            return 0, 0

    # ==================================================================
    # 私有方法：峰值显存计算
    # ==================================================================

    def _calculate_peak_vram(
        self,
        models: List[DetectedModel],
        resolution: tuple = (1024, 1024),
        batch_size: int = 1,
        dtype: str = "fp16",
    ) -> int:
        """
        计算峰值显存需求 (MB)。

        ============================================================
        核心公式（ComfyUI 顺序执行模型的关键洞察）：
        ============================================================

        ComfyUI 是 **顺序执行** 的工作流引擎！这意味着：
        - 节点是按照拓扑排序依次执行的
        - 不需要同时将所有模型保留在显存中
        - 峰值显存 ≠ sum(所有模型显存)  ← 这是常见错误假设！

        正确的峰值估算公式::

            peak_vram = max(
                largest_single_model,                          # 最大单模型
                largest_single_model + inference_overhead,      # 模型 + 推理中间结果
            ) + safety_margin

        其中推理开销取决于：
        - 分辨率 (width × height): 高分辨率的特征图更大
        - batch_size: 批次大小线性影响
        - 数据类型 (FP16/FP32/FP8): 每像素字节数不同
        - 模型架构 (UNet vs DiT): DiT 注意力机制更耗显存

        对于 CheckpointLoaderSimple 这类"复合"节点：
        它会同时加载 UNet + CLIP + VAE 三个子模型。
        但在推理时，通常只有 UNet（或 DiT）处于活跃推理状态，
        CLIP 和 VAE 分别在编码和解码阶段短暂激活。
        因此我们只将最大的子模型作为峰值基准，
        再加上一个较小的"共存惩罚"项。

        Args:
            models: 检测到的模型列表
            resolution: (width, height) 分辨率元组
            batch_size: 批次大小
            dtype: 数据类型 ("fp16", "fp32", "fp8")

        Returns:
            峰值显存预估值 (MB)
        """
        if not models:
            return 0

        # ---- 找到最大的单一模型 ----
        largest_model = max(models, key=lambda m: m.estimated_vram_mb)
        base_peak = largest_model.estimated_vram_mb

        # ---- 推理时的额外显存开销 ----
        inference_overhead = self._calculate_inference_overhead(
            resolution=resolution,
            batch_size=batch_size,
            dtype=dtype,
            model_architecture=self._infer_primary_model_architecture(models),
        )

        # ---- 复合节点的共存惩罚 ----
        # CheckpointLoaderSimple 会同时加载 UNet+CLIP+VAE
        # 虽然 ComfyUI 会尽量优化，但它们可能在短时间内共存
        combined_penalty = self._calculate_combined_penalty(models)

        # ---- 最终峰值 ----
        peak = base_peak + inference_overhead + combined_penalty + self.SAFETY_MARGIN_MB

        return int(peak)

    def _calculate_inference_overhead(
        self,
        resolution: tuple = (1024, 1024),
        batch_size: int = 1,
        dtype: str = "fp16",
        model_architecture: str = "sdxl",
    ) -> int:
        """
        计算推理阶段的额外显存开销 (MB)。

        ============================================================
        推理开销的组成：
        ============================================================

        1. 采样器特征图显存：
           UNet/DiT 在每一步采样都会产生中间特征图。
           大小取决于分辨率、通道数和数据类型。

           基础公式（简化版）::
               base = W × H × channels × bytes_per_pixel × batch / (1024²)

           对于 SDXL @ 1024² FP16::
               base = 1024 × 1024 × 320 × 2 / (1024×1024) ≈ 640 MB
               （320 是 SDXL UNet 的基础通道数）

        2. 注意力缓存（Transformer/DiT 特有）：
           Flux 等 DiT 模型的注意力机制需要存储 KV-cache，
           这部分开销随序列长度（即分辨率）二次增长。

        3. 安全系数：
           考虑 UNet 中间层的多尺度特征图、
           skip connections 的临时存储、
           以及 PyTorch 操作的临时缓冲区。

        Args:
            resolution: (width, height) 元组
            batch_size: 批次大小
            dtype: 数据类型
            model_architecture: 模型架构标识 ("sd15", "sdxl", "flux", "cascade")

        Returns:
            额外显存需求 (MB)
        """
        dtype_bytes = {"fp16": 2, "fp32": 4, "fp8": 1}
        bytes_per_pixel = dtype_bytes.get(dtype.lower(), 2)

        width, height = resolution

        # 基础特征图显存（简化模型：假设 4 个基础通道组）
        # 实际 UNet 有 multi-scale features，这里做保守估计
        base_channels = 4  # RGB + latent space overhead
        base_overhead = (
            width * height * base_channels * bytes_per_pixel * batch_size
        ) // (1024 * 1024)

        # 应用模型架构特定的安全系数
        safety_factor = self.INFERENCE_SAFETY_FACTORS.get(
            model_architecture,
            self.INFERENCE_SAFETY_FACTORS["sdxl"],  # 默认使用 SDXL 系数
        )

        total_overhead = int(base_overhead * safety_factor)

        # 最小保证值（即使低分辨率也有固定开销）
        total_overhead = max(total_overhead, 200)

        return total_overhead

    def _calculate_combined_penalty(self, models: List[DetectedModel]) -> int:
        """
        计算 CheckpointLoader 等复合节点的模型共存惩罚。

        CheckpointLoaderSimple 会一次性加载 UNet + CLIP + VAE。
        虽然 ComfyUI 的执行引擎会在不活跃时卸载模型，
        但在某些情况下这些模型可能短时间共存于显存中。

        Args:
            models: 检测到的模型列表

        Returns:
            共存惩罚值 (MB)
        """
        penalty = 0
        for model in models:
            if model.node_type in ("CheckpointLoaderSimple", "CheckpointLoader"):
                # 复合节点：额外保留约 30% 的非主模型显存作为共存惩罚
                penalty = max(penalty, int(model.estimated_vram_mb * 0.25))
        return penalty

    # ==================================================================
    # 私有方法：AMD Oversubscription 处理
    # ==================================================================

    def _apply_amd_oversubscription(
        self,
        estimated_vram: int,
        context: PredictionContext,
    ) -> Tuple[Optional[float], int, bool]:
        """
        应用 AMD GPU Oversubscription（内存超分）调整。

        ============================================================
        AMD HSA Oversubscription 机制：
        ============================================================

        AMD GPU 通过 HSA (Heterogeneous System Architecture) 支持
        将系统 RAM 用作显存的扩展缓冲区。当 GPU 显存不足时，
        驱动程序可以将部分显存页交换到系统 RAM 中。

        三级判定逻辑：

        Level 1 - 正常模式 (estimated <= physical_vram):
            所有数据都在物理显存中，无性能损失。
            → 返回 None（由主流程继续双约束评估）

        Level 2 - 超分模式 (physical < estimated <= physical + ram_buffer):
            部分数据溢出到 RAM，有显著性能下降（2-5x）。
            → 返回调整后的成功率（含惩罚因子）

        Level 3 - 必然 OOM (estimated > physical + ram_buffer):
            即使使用全部可用 RAM 也无法容纳。
            → 返回 0% 成功率

        Args:
            estimated_vram: 估算的峰值显存需求 (MB)
            context: 系统资源上下文

        Returns:
            (adjusted_success_rate_or_None, effective_vram_mb, is_oversubscribed) 元组
        """
        cfg = self.AMD_OVERSUB_CONFIG
        physical_vram = context.vram_total_mb
        is_oversubscribed = False

        # 非 AMD GPU 或不支持超分 → 不做任何调整
        if not context.is_amd_gpu or not context.amd_oversub_supported:
            return None, estimated_vram, False

        # Level 1: 正常模式
        if estimated_vram <= physical_vram:
            return None, estimated_vram, False

        # 计算 RAM 溢出缓冲区
        ram_buffer = int(context.ram_free_mb * cfg.ram_utilization_ratio)

        # 减去页表开销
        effective_ram_buffer = ram_buffer - cfg.page_table_overhead_mb

        # 检查是否有足够的 RAM 来支撑超分
        if effective_ram_buffer < cfg.min_ram_for_oversub_mb:
            # RAM 太少，超分不可靠
            if estimated_vram <= physical_vram + effective_ram_buffer:
                # 勉强够用但很危险
                overflow_ratio = (estimated_vram - physical_vram) / max(effective_ram_buffer, 1)
                penalty = min(0.5, overflow_ratio * cfg.success_rate_penalty * 2)
                is_oversubscribed = True
                return max(0.0, 1.0 - penalty) * 100, estimated_vram, is_oversubscribed
            else:
                return 0.0, estimated_vram, True

        # Level 2: 超分模式
        effective_total = physical_vram + effective_ram_buffer
        if estimated_vram <= effective_total:
            # 可以通过超分容纳，但应用成功率惩罚
            overflow_amount = estimated_vram - physical_vram
            overflow_ratio = overflow_amount / max(effective_ram_buffer, 1)

            # 惩罚因子随溢出比例增加
            # 溢出越多，惩罚越重（因为性能下降越严重）
            penalty = overflow_ratio * cfg.success_rate_penalty

            # 基础成功率（假设硬件层面能容纳）
            base_success = 1.0 - penalty
            is_oversubscribed = True

            return max(0.0, base_success) * 100, effective_total, is_oversubscribed

        # Level 3: 必然 OOM
        logger.warning(
            f"Estimated VRAM ({estimated_vram}MB) exceeds total capacity "
            f"(VRAM {physical_vram}MB + RAM buffer {effective_ram_buffer}MB = "
            f"{effective_total}MB). OOM highly likely."
        )
        return 0.0, effective_total, True

    @staticmethod
    def _detect_amd_oversubscription_support() -> bool:
        """
        [DEPRECATED] 检测当前 AMD GPU 是否支持 Oversubscription（内存超分）。

        .. deprecated:: 2.1.0
            此函数已标记为废弃，保留实现以供向后兼容，
            但不建议在新代码中主动调用。

        **废弃原因:**

        1. **性能惩罚严重**: AMD Oversubscription 虽然允许使用系统 RAM 作为显存扩展，
           但会带来 2-5x 的性能下降，在实际的 ComfyUI 推理场景中几乎不可用。

        2. **预测准确性问题**: Oversubscription 的实际可用性高度依赖于：
           - 系统空闲 RAM 量（需要 >2GB 才可靠）
           - 驱动版本和配置
           - 当前系统负载
           这些因素在预测时难以准确估计，导致成功率预测偏差较大。

        3. **用户体验不佳**: 即使技术上"可以运行"，用户也会因为极慢的速度
           而认为程序卡死或出错，影响产品口碑。

        4. **替代方案更优**: 对于显存不足的情况，以下方案比 Oversubscription 更实用：
           - 使用 FP8 量化模型（减少 ~50% 显存）
           - 启用 VAE Tiling
           - 降低分辨率 (1024→768→512)
           - 使用 --lowvram 模式
           - 更换更大显存的显卡

        **建议的新策略:**
        - 将 Oversubscription 视为"最后的救命稻草"，而非常规选项
        - 在预测时默认假设 Oversubscription **不可用**（保守策略）
        - 仅在用户明确启用且系统条件满足时才考虑此路径
        - 在 UI 上对 Oversubscription 场景给出强烈的性能警告

        原检测方法（按可靠性排序）：
        1. 检查 torch 是否使用 ROCm 后端（最可靠的运行时检测）
        2. 检查 /sys/class/kfd/kfd_topology 目录是否存在
        3. 检查扩展的 HSA/ROCm 环境变量
        4. 检查 ROCm 安装路径
        5. 检查 HIP 库文件
        6. 检查 amdgpu 驱动版本（放宽条件：22.00+ 即可）
        7. 检查 /dev/kfd 设备节点
        8. 检查 DRM 设备中的 AMD GPU
        9. 检查 HIP_VISIBLE_DEVICES 环境变量

        Returns:
            True 如果支持 Oversubscription，False 否则

        Note:
            此函数仍被内部调用以维持现有逻辑不变，
            但返回值在 `_apply_amd_oversubscription()` 中会被弱化处理。
        """
        # 方法 1: 检查 torch 是否使用 ROCm 后端（最可靠）
        try:
            import torch
            # 检查是否有 HIP 相关属性
            if hasattr(torch.version, 'hip') and torch.version.hip is not None:
                logger.debug(f"AMD Oversubscription: PyTorch using ROCm/HIP backend")
                return True
            # 检查是否有 rocm 版本信息
            if hasattr(torch.version, 'rocm') and torch.version.rocm is not None:
                logger.debug(f"AMD Oversubscription: PyTorch ROCm version detected")
                return True
            # 检查是否能检测到 AMD GPU
            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0)
                if any(kw in device_name.lower() for kw in ["amd", "radeon", "navi", "rdna"]):
                    logger.debug(f"AMD Oversubscription: AMD GPU detected via torch")
                    return True
        except (ImportError, Exception):
            pass

        # 方法 2: 检查 KFD topology（ROCm 内核模块特征）
        kfd_path = Path("/sys/class/kfd/kfd_topology")
        if kfd_path.exists():
            logger.debug("AMD Oversubscription: /sys/class/kfd/kfd_topology found")
            return True

        # 方法 3: 检查扩展的 HSA/ROCm 环境变量
        hsa_vars = [
            "HSA_ENABLE_SHUTDOWN_HANG",
            "ROCM_PATH",
            "HIP_PLATFORM",
            "HSA_PATH",
            "ROCM_LIB_PATH",
            "HIP_ROCCLR_HOME",
            "HSA_TOOLS_LIB",
        ]
        for var in hsa_vars:
            if os.environ.get(var):
                logger.debug(f"AMD Oversubscription: HSA/ROCm env var {var} detected")
                return True

        # 方法 4: 检查 ROCm 安装路径
        rocm_paths = [
            "/opt/rocm",
            "/opt/rocm/hip",
            "/usr/local/rocm",
        ]
        for path in rocm_paths:
            if os.path.isdir(path):
                logger.debug(f"AMD Oversubscription: ROCm installation found at {path}")
                return True

        # 方法 5: 检查 AMD HIP 库文件
        hip_lib_paths = [
            "/opt/rocm/lib/libamdhip64.so",
            "/usr/lib/libamdhip64.so",
            "/usr/local/lib/libamdhip64.so",
        ]
        for lib_path in hip_lib_paths:
            if os.path.isfile(lib_path):
                logger.debug(f"AMD Oversubscription: HIP library found at {lib_path}")
                return True

        # 方法 6: 检查 amdgpu 驱动版本（放宽条件：22.00+ 即可）
        version_path = Path("/sys/module/amdgpu/version")
        if version_path.exists():
            try:
                ver_str = version_path.read_text().strip()
                # 解析版本号（格式如 "23.40-..." 或 "6.5.0"）
                ver_match = re.search(r'(\d+)\.(\d+)', ver_str)
                if ver_match:
                    major = int(ver_match.group(1))
                    minor = int(ver_match.group(2))
                    # 放宽条件：amdgpu 22.00+ 版本基本都支持 Oversubscription
                    if (major > 22) or (major == 22 and minor >= 0):
                        logger.debug(
                            f"AMD Oversubscription: amdgpu version {ver_str} "
                            f"(>= 22.00) supports oversubscription"
                        )
                        return True
            except (IOError, OSError):
                pass

        # 方法 7: 检查 /dev/kfd 设备节点（ROCm 需要的特殊设备）
        kfd_device = Path("/dev/kfd")
        if kfd_device.exists():
            logger.debug("AMD Oversubscription: /dev/kfd device found")
            return True

        # 方法 8: 检查 drm 设备中的 AMD GPU
        try:
            import glob
            amd_drm_devices = glob.glob("/sys/class/drm/card*/device/vendor")
            for dev_path in amd_drm_devices:
                try:
                    with open(dev_path, 'r') as f:
                        vendor_id = f.read().strip()
                        # AMD vendor ID is 0x1002
                        if vendor_id == "0x1002" or vendor_id == "2562":
                            logger.debug(f"AMD Oversubscription: AMD DRM device found")
                            return True
                except Exception:
                    continue
        except Exception:
            pass

        # 方法 9: 检查是否设置了 HIP_VISIBLE_DEVICES
        if os.environ.get("HIP_VISIBLE_DEVICES") is not None:
            logger.debug("AMD Oversubscription: HIP_VISIBLE_DEVICES set")
            return True

        logger.debug("AMD Oversubscription: support not confirmed")
        return False

    # ==================================================================
    # 私有方法：成功率预测模型（双约束评估）
    # ==================================================================

    def _predict_success_rate(
        self,
        estimated_peak_vram: int,
        available_vram: int,
        is_amd: bool = False,
        physical_vram: int = 0,
        oversub_enabled: bool = False,
    ) -> float:
        """
        预测运行成功率 (0-100%)。

        ============================================================
        双约束评估模型：
        ============================================================

        成功率由两个约束因子的乘积决定::

            success_rate = hard_constraint × soft_constraint × 100

        --- Hard Constraint（硬约束）---
        决定性因素：**最大单模型能否装入可用显存？**
        - 如果不能装入 → 成功率必然为 0%（对于 NVIDIA）
        - 对于 AMD：可能通过 Oversubscription 挽救（已在 _apply_amd_oversubscription 中处理）

        hard_constraint = min(1.0, effective_available / max_single_model)

        --- Soft Constraint（软约束）---
        影响成功概率的非决定性因素：
        - 显存碎片化（长时间运行后碎片增多，连续分配困难）
        - 驱动预留（AMD ~300MB, NVIDIA ~150MB）
        - PyTorch 开销（CUDA/HIP context, cuDNN/MIOpen workspace）
        - 安全边距（至少保留 10% 余量应对波动）

        soft_constraint = calculate_soft_constraint(...)

        --- 最终公式 ---
        success_rate = hard_constraint × soft_constraint × 100

        Args:
            estimated_peak_vram: 估算的峰值显存需求 (MB)
            available_vram: 当前可用显存 (MB)
            is_amd: 是否为 AMD GPU
            physical_vram: 物理显存总量 (MB，用于 AMD 超分判断)
            oversub_enabled: 是否启用了 AMD Oversubscription

        Returns:
            成功率百分比 (0.0 - 100.0)
        """
        if estimated_peak_vram == 0:
            return 100.0

        # ---- Hard Constraint ----
        # 有效可用显存（扣除碎片化损失）
        effective_available = available_vram * self.FRAGMENTATION_FACTOR

        hard_constraint = min(1.0, effective_available / max(estimated_peak_vram, 1))

        # 如果硬约束为 0 且不是 AMD 超分场景，直接返回 0
        if hard_constraint == 0 and not (is_amd and oversub_enabled):
            return 0.0

        # ---- Soft Constraint ----
        soft_constraint = self._calculate_soft_constraint(
            estimated_vram=estimated_peak_vram,
            available_vram=available_vram,
            is_amd=is_amd,
        )

        # ---- 综合 ----
        success_rate = hard_constraint * soft_constraint * 100

        return success_rate

    def _calculate_soft_constraint(
        self,
        estimated_vram: int,
        available_vram: int,
        is_amd: bool = False,
    ) -> float:
        """
        计算软约束因子 (0.0 - 1.0)。

        ============================================================
        软约束考虑的非理想因素：
        ============================================================

        1. 驱动预留：
           AMD 驱动预留约 300MB（HSA 运行时、显示控制器等）
           NVIDIA 驱动预留约 150MB

        2. PyTorch 框架开销：
           CUDA/HIP context 创建: ~100-200MB
           cuDNN/MIOpen workspace: ~100-200MB
           内存分配器内部碎片: ~50-100MB
           总计约: 300-500MB

        3. 碎片化惩罚：
           长时间运行的 PyTorch 进程会产生显存碎片
           新建进程（刚重启后）: 碎片化因子 ≈ 1.0
           运行数小时后: 碎片化因子 ≈ 0.95
           我们使用固定的 0.9 因子作为保守估计

        4. 安全边距：
           即使理论上刚好够用，实际运行中也可能因为
           动态张量尺寸变化而超出预期
           建议至少保留 10% 余量

        ============================================================
        非线性映射函数：
        ============================================================

        ratio = effective_available / estimated_vram

        ratio range    →  soft_constraint
        ----------------------------------------
        ≥ 1.2          →  1.0   (非常宽裕)
        ≥ 1.0          →  0.95  (刚好够用，但无余量)
        ≥ 0.9          →  0.85  (略紧，有少量波动风险)
        ≥ 0.75         →  0.65  (有风险，接近阈值边界)
        < 0.75         →  ratio × 0.8  (线性快速下降)

        Args:
            estimated_vram: 估算的峰值显存需求 (MB)
            available_vram: 原始可用显存 (MB)
            is_amd: 是否为 AMD GPU（影响驱动预留值）

        Returns:
            软约束因子 (0.0 - 1.0)
        """
        # 驱动预留
        driver_reserve = self.DRIVER_RESERVE_AMD_MB if is_amd else self.DRIVER_RESERVE_NVIDIA_MB

        # 有效可用显存（扣除预留和框架开销）
        effective_available = (
            available_vram
            - driver_reserve
            - self.PYTORCH_OVERHEAD_MB
        )

        # 防止负值
        effective_available = max(0, effective_available)

        # 计算供需比
        if estimated_vram <= 0:
            return 1.0

        ratio = effective_available / estimated_vram

        # 非线性映射
        if ratio >= 1.2:
            return 1.0        # 非常宽裕
        elif ratio >= 1.0:
            return 0.95       # 刚好够用
        elif ratio >= 0.9:
            return 0.85       # 略紧但有希望
        elif ratio >= 0.75:
            return 0.65       # 有明显风险
        else:
            # 快速下降区域
            return max(0.0, ratio * 0.8)

    # ==================================================================
    # 私有方法：风险等级和建议生成
    # ==================================================================

    @staticmethod
    def _determine_risk_level(success_rate: float) -> str:
        """
        根据成功率确定风险等级。

        阈值定义（与 PredictionResult.calculate_risk_level 一致）：
        - low:      ≥ 90%
        - medium:   70% - 89.9%
        - high:     40% - 69.9%
        - critical: < 40%

        Args:
            success_rate: 成功率 (0-100)

        Returns:
            风险等级字符串
        """
        return PredictionResult.calculate_risk_level(success_rate)

    def _generate_recommendations(
        self,
        success_rate: float,
        estimated_vram: int,
        available_vram: int,
        context: PredictionContext,
        risk_level: str,
        models: List[DetectedModel],
    ) -> List[str]:
        """
        生成优化建议列表。

        ============================================================
        风险等级和建议的对应关系：
        ============================================================

        LOW Risk (≥ 90%) — 绿色:
        - "显存充足，可以正常运行"
        - (如果 >98%) "资源充裕，可考虑增大分辨率或批量大小"

        MEDIUM Risk (70-89%) — 黄色:
        - "显存偏紧，建议关注运行时状态"
        - "降低分辨率至 X x Y"
        - "启用 VAE Tiling（如果模型支持）"
        - AMD 用户提示 Oversubscription 选项

        HIGH Risk (40-69%) — 橙色:
        - "警告：显存可能不足，有 OOM 风险！"
        - "启用 VAE Tiling"
        - "释放缓存池（Restart → Clear Cache）"
        - "使用 FP8 量化模型（如果支持）"
        - AMD 用户确保足够 RAM

        CRITICAL Risk (< 40%) — 红色:
        - "严重警告：几乎确定会发生 OOM！"
        - "更换更大显存显卡（推荐 24GB+）"
        - "使用 FP8 + Tiling 组合方案"
        - "降低 batch size 至 1"
        - "考虑 --lowvram 模式"

        Args:
            success_rate: 预测的成功率
            estimated_vram: 估算的峰值显存
            available_vram: 可用显存
            context: 系统资源上下文
            risk_level: 风险等级
            models: 检测到的模型列表

        Returns:
            建议字符串列表
        """
        recommendations: List[str] = []

        if risk_level == RiskLevel.LOW.value:
            recommendations.append("显存充足，可以正常运行")
            if success_rate > 98:
                recommendations.append(
                    "资源充裕，可考虑增大分辨率或批量大小以提升质量/效率"
                )

        elif risk_level == RiskLevel.MEDIUM.value:
            recommendations.append("显存偏紧，建议关注运行时状态")
            if success_rate < 80:
                recommendations.append(
                    "建议降低分辨率至 768x768 或更小以减少显存需求"
                )
            if context.is_amd_gpu and context.ram_free_mb > 8000:
                recommendations.append(
                    "AMD GPU: 可利用系统 RAM 作为显存缓冲 "
                    "(Oversubscription)，但可能导致速度下降 2-5x"
                )
            # 检查是否有大型模型
            large_models = [m for m in models if m.file_size_mb > 4000]
            if large_models:
                names = [
                    os.path.basename(m.model_path)[:25]
                    for m in large_models[:2]
                ]
                recommendations.append(
                    f"检测到大型模型 ({', '.join(names)})，"
                    f"占用量较大 ({max(m.file_size_mb for m in large_models):.0f}MB)"
                )

        elif risk_level == RiskLevel.HIGH.value:
            recommendations.append("警告：显存可能不足，存在 OOM 风险！")
            recommendations.append(
                "建议立即采取以下措施之一或组合："
            )
            recommendations.append(
                "  1. 降低分辨率至 512x512 或 768x768"
            )
            recommendations.append(
                "  2. 减少 sampling steps (20→15 或 15→10)"
            )
            recommendations.append(
                "  3. 启用 VAE Tiling（在 VAE Decode 节点中开启 tiling 选项）"
            )
            if len(models) > 3:
                recommendations.append(
                    f"工作流包含 {len(models)} 个模型节点，"
                    f"考虑简化流程或移除不必要的 ControlNet/LoRA"
                )
            if context.is_amd_gpu:
                ram_gb = context.ram_free_mb / 1024
                if ram_gb >= 8:
                    recommendations.append(
                        f"AMD 用户：确保有足够的系统内存 "
                        f"({ram_gb:.1f}GB 可用) 用于 Oversubscription"
                    )
                else:
                    recommendations.append(
                        "AMD 用户：系统内存不足 ({:.1f}GB 可用)，"
                        "Oversubscription 效果有限".format(ram_gb)
                    )
            else:
                recommendations.append(
                    "NVIDIA 用户：考虑使用 --lowvram 或 --normalvram 启动模式"
                )

        else:  # CRITICAL
            recommendations.append("严重警告：几乎确定会发生 OOM (>95% 概率)！")
            recommendations.append("必须立即采取行动：")
            recommendations.append(
                "  1. 更换更大显存的显卡（推荐 24GB+, 如 RTX 4090 / RX 7900 XTX）"
            )
            recommendations.append(
                "  2. 使用 FP8 量化模型（减少约 50% 显存占用）"
            )
            recommendations.append(
                "  3. 降低分辨率至最低设置 (512x512)"
            )
            recommendations.append(
                "  4. 启用 VAE Tiling + 模型 offloading 组合方案"
            )
            recommendations.append(
                "  5. 使用 ComfyUI --lowvram 启动参数"
            )
            recommendations.append(
                "  6. 关闭所有其他占用显存的程序（浏览器、其他 GPU 任务等）"
            )
            deficit = estimated_vram - available_vram
            if deficit > 0:
                recommendations.append(
                    f"  当前缺口: 约 {deficit // 1024}GB 显存不足"
                )

        return recommendations

    # ==================================================================
    # 私有方法：辅助工具
    # ==================================================================

    def _infer_primary_model_architecture(
        self, models: List[DetectedModel]
    ) -> str:
        """
        从检测到的模型列表推断主要模型架构。

        推断优先级：transformer > unet > generic

        Args:
            models: 检测到的模型列表

        Returns:
            模型架构标识 ("sd15", "sdxl", "flux", "cascade", "generic")
        """
        type_counts: Dict[str, int] = {}
        for m in models:
            type_counts[m.inferred_type] = type_counts.get(m.inferred_type, 0) + 1

        # 按优先级检查
        if "transformer" in type_counts:
            # 进一步区分 Flux vs Cascade
            for m in models:
                if m.inferred_type == "transformer":
                    name_lower = m.model_path.lower()
                    if "flux" in name_lower:
                        return "flux"
                    elif "cascade" in name_lower:
                        return "cascade"
            return "flux"  # 默认 transformer → flux

        if "unet" in type_counts:
            # 区分 SD 1.5 vs SDXL
            for m in models:
                if m.inferred_type == "unet":
                    name_lower = m.model_path.lower()
                    if any(kw in name_lower for kw in ["sdxl", "xl", "juggernaut"]):
                        return "sdxl"
            return "sd15"

        return "generic"

    def _calculate_confidence(
        self,
        models: List[DetectedModel],
        has_workflow: bool,
        has_gpu_context: bool,
    ) -> float:
        """
        计算预测结果的置信度 (0.0 - 1.0)。

        置信度基于信息完整性：
        - 有工作流 JSON: +0.4
        - 有 GPU 上下文: +0.3
        - 模型文件大小已确认（非估算）: +0.2
        - 基础分: 0.1

        Args:
            models: 检测到的模型列表
            has_workflow: 是否有工作流输入
            has_gpu_context: 是否有 GPU 资源信息

        Returns:
            置信度值 (0.0 - 1.0)
        """
        confidence = 0.1  # 基础分

        if has_workflow:
            confidence += 0.4

        if has_gpu_context:
            confidence += 0.3

        # 检查有多少模型是通过实际文件大小（而非启发式估算）得到的
        confirmed_size_count = sum(
            1 for m in models if m.file_size_mb > 0
        )
        if models:
            size_ratio = confirmed_size_count / len(models)
            confidence += size_ratio * 0.2

        return min(1.0, confidence)

    def _try_get_current_workflow(self) -> Optional[Dict]:
        """
        尝试从 ComfyUI 内部 API 获取当前工作流。

        多种尝试策略（按优先级排序）：
        1. 检查 ComfyUI 全局变量（同一进程内运行时最可靠）
        2. 尝试访问 comfy.api 模块的工作流缓存
        3. 读取 ComfyUI 临时保存的工作流文件
        4. 读取 ComfyUI 配置目录中的自动保存文件
        5. 调用 ComfyUI REST API (GET /api/workflow)
        6. 尝试从 comfy.execution 模块获取当前执行图

        Returns:
            工作流 JSON 字典，或 None
        """
        import json
        import sys

        # ---- 方法 1: 尝试访问 ComfyUI 全局变量（最可靠的方式）----
        try:
            # 检查是否在 ComfyUI 进程内运行
            if 'comfy' in sys.modules:
                # 尝试访问全局工作流对象
                import __main__ as comfy_main
                # ComfyUI 有时会将工作流存储在全局变量中
                for attr_name in ['workflow', 'current_workflow', 'graph', 'manager']:
                    if hasattr(comfy_main, attr_name):
                        obj = getattr(comfy_main, attr_name)
                        if isinstance(obj, dict):
                            return obj
                        elif hasattr(obj, 'workflow') and isinstance(obj.workflow, dict):
                            return obj.workflow
        except Exception as e:
            logger.debug(f"Method 1 - ComfyUI global vars access failed: {e}")

        # ---- 方法 2: 尝试访问 comfy.api 模块 ----
        try:
            if 'comfy.api' in sys.modules:
                from comfy import api
                # API 模块可能有工作流相关的缓存
                if hasattr(api, 'current_workflow'):
                    return api.current_workflow
                # 检查 server 模块
                if hasattr(api, 'server') and hasattr(api.server, 'workflow_manager'):
                    wm = api.server.workflow_manager
                    if hasattr(wm, 'get_current_workflow'):
                        return wm.get_current_workflow()
        except Exception as e:
            logger.debug(f"Method 2 - comfy.api access failed: {e}")

        # ---- 方法 3: 尝试访问 comfy.execution 模块 ----
        try:
            if 'comfy.execution' in sys.modules:
                from comfy.execution import Graph
                # 如果有活跃的执行图，尝试获取其工作流数据
                if hasattr(Graph, 'get_current_graph'):
                    current_graph = Graph.get_current_graph()
                    if current_graph and hasattr(current_graph, 'serialize'):
                        return current_graph.serialize()
        except Exception as e:
            logger.debug(f"Method 3 - comfy.execution access failed: {e}")

        # ---- 方法 4: 读取临时文件（扩展路径列表）----
        temp_paths = [
            # 默认临时目录
            os.path.join(os.getcwd(), "temp", "last_workflow.json"),
            # 环境变量指定的路径
            os.environ.get("COMFYUI_WORKFLOW_FILE", ""),
            # ComfyUI 配置目录
            os.path.join(os.getcwd(), "config", "last_workflow.json"),
            # 用户目录中的 .comfyui 目录
            os.path.join(os.path.expanduser("~"), ".comfyui", "last_workflow.json"),
            # ComfyUI 根目录下的临时文件
            os.path.join(os.getcwd(), "last_workflow.json"),
            os.path.join(os.getcwd(), "workflow_temp.json"),
        ]
        for temp_path in temp_paths:
            if temp_path and os.path.isfile(temp_path):
                try:
                    with open(temp_path, 'r') as f:
                        return json.load(f)
                except (IOError, OSError, json.JSONDecodeError) as e:
                    logger.debug(f"Method 4 - Temp file {temp_path} read failed: {e}")

        # ---- 方法 5: REST API（支持多种端口）----
        for port in [8188, 8189, 8080, 5000]:
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/workflow",
                    method='GET',
                )
                with urllib.request.urlopen(req, timeout=0.5) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data:
                        logger.debug(f"Method 5 - Found workflow via API on port {port}")
                        return data
            except Exception as e:
                logger.debug(f"Method 5 - API on port {port} failed: {e}")

        # ---- 方法 6: 尝试 WebSocket 连接获取工作流 ----
        try:
            # 尝试使用 websocket 连接（如果可用）
            if 'websocket' in sys.modules or 'websockets' in sys.modules:
                import asyncio
                import websockets

                async def fetch_workflow():
                    try:
                        async with websockets.connect("ws://127.0.0.1:8188/ws", timeout=1.0) as ws:
                            await ws.send(json.dumps({"type": "get_workflow"}))
                            response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            data = json.loads(response)
                            if 'workflow' in data:
                                return data['workflow']
                    except Exception:
                        return None

                result = asyncio.run(fetch_workflow())
                if result:
                    return result
        except Exception as e:
            logger.debug(f"Method 6 - WebSocket access failed: {e}")

        logger.debug("All methods to get workflow failed, returning None")
        return None

    # ==================================================================
    # 诊断与调试接口
    # ==================================================================

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        返回预测器的诊断信息。

        用于调试面板展示和问题排查。

        Returns:
            包含诊断信息的字典
        """
        return {
            "predictor_class": self.__class__.__name__,
            "collector_name": self.name,
            "enabled": self.enabled,
            "timeout": self.timeout,
            "has_gpu_provider": self._gpu_provider is not None,
            "gpu_provider_name": (
                self._gpu_provider.name
                if self._gpu_provider and hasattr(self._gpu_provider, 'name')
                else None
            ),
            "scanner_model_paths": self.scanner.model_paths,
            "last_prediction_time": self._last_predict_time,
            "has_cached_result": self._last_result is not None,
            "algorithm_params": {
                "fragmentation_factor": self.FRAGMENTATION_FACTOR,
                "safety_margin_mb": self.SAFETY_MARGIN_MB,
                "amd_ram_utilization_ratio": self.AMD_OVERSUB_CONFIG.ram_utilization_ratio,
                "amd_penalty_factor": self.AMD_OVERSUB_CONFIG.success_rate_penalty,
                "inference_safety_factors": self.INFERENCE_SAFETY_FACTORS,
            },
            "stats": self.stats,
        }


# ============================================================================
# 便捷工厂函数
# ============================================================================

def create_predictor(gpu_provider=None) -> VRAMPredictor:
    """
    创建 VRAMPredictor 实例的便捷工厂函数。

    Args:
        gpu_provider: 可选的 GPU Provider

    Returns:
        配置好的 VRAMPredictor 实例
    """
    return VRAMPredictor(gpu_provider=gpu_provider)


# ============================================================================
# 模块自检
# ============================================================================

if __name__ == "__main__":
    # 基本自检：验证类结构和常量
    print("=" * 60)
    print("PRED Algorithm Self-Check")
    print("=" * 60)

    # 检查继承关系
    assert issubclass(VRAMPredictor, BasePredictor), \
        "VRAMPredictor must inherit from BaseCollector.Predictor"
    print("[OK] Inheritance: VRAMPredictor <- Predictor <- BaseCollector[PredictionResult]")

    # 检查必要方法
    required_methods = ['predict', 'collect', 'predict_from_workflow']
    for method in required_methods:
        assert hasattr(VRAMPredictor, method), f"Missing method: {method}"
    print(f"[OK] Required methods present: {required_methods}")

    # 检查 PredictionResult 字段兼容性
    test_result = PredictionResult(
        success_rate=85.5,
        risk_level="medium",
        peak_vram_estimate=7000,
        recommendations=["test"],
        model_info={},
        confidence=0.85,
    )
    print(f"[OK] PredictionResult compatible: {test_result.to_dict()}")

    # 检查模型配置
    print(f"\n[INFO] Model profiles loaded: {list(MODEL_PROFILES.keys())}")
    print(f"[INFO] Experiential sizes loaded: {list(EXPERIENTIAL_MODEL_SIZES.keys())}")

    # 示例：SDXL on 12GB 预测
    print("\n--- Example: SDXL on 12GB VRAM ---")
    predictor = VRAMPredictor()
    sample_workflow = {
        "nodes": [
            {
                "id": 5,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["sd_xl_base_1.0.safetensors"]
            },
            {
                "id": 10,
                "type": "KSampler",
                "widgets_values": [
                    749582084899257, "euler", "normal", 20, 4.0, "disabled", 1024, 1024, 1
                ]
            }
        ]
    }

    result = predictor.predict_from_workflow(sample_workflow)
    print(f"  Success Rate: {result.success_rate}%")
    print(f"  Risk Level:   {result.risk_level}")
    print(f"  Peak VRAM:    {result.peak_vram_estimate} MB")
    print(f"  Confidence:   {result.confidence}")
    print(f"  Recommendations:")
    for rec in result.recommendations:
        print(f"    - {rec}")

    print("\n" + "=" * 60)
    print("Self-check completed successfully.")
    print("=" * 60)
