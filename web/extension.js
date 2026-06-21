/**
 * ComfyUI-Feixue-UniversalMonitor - Premium UI v3.25
 *
 * 设计原则：不透明实底背景 + 发光边框灯条 + 药丸/胶囊形状 + 3D圆柱横截面效果 + CSS芯片图标 + 渐变状态条 + 5色主题系统
 * @version 3.25
 */

(function() {
    'use strict';

    console.log('[飞雪监测器] 🚀 Premium UI v3.25 启动...');

    // ============================================================
    // 配置常量（保留核心配置不变）
    // ============================================================
    const CONFIG = {
        version: '3.25',
        updateInterval: 2000,

        // 状态阈值配置（绝对不能改）
        thresholds: {
            normal: 70,    // < 70% 绿色
            warning: 90,   // 70-90% 黄色
            danger: 100,   // > 90% 红色
        },
    };

    // ============================================================
    // 数据缓存和状态管理（原样保留）
    // ============================================================
    let cachedData = null;
    let lastFetchTime = 0;
    let backendAvailable = false;

    const CACHE_CONFIG = {
        ttl: 1500,           // 缓存有效期 1.5秒
        timeout: 3000,       // 请求超时 3秒
        maxRetries: 3,       // 最大重试次数
    };

    // ============================================================
    // 核心：数据获取与标准化（原样保留，一字不改）
    // ============================================================

    /**
     * 从后端获取原始数据
     *
     * **关键修复**：
     * - 支持后端新格式: { cpu_utilization, ram: {...}, gpus: [...] }
     * - 兼容旧格式: { cpu: {...}, gpu: {...}, ram: {...} }
     * - 不再强制要求 data.cpu 字段存在
     *
     * @async
     * @returns {Promise<Object|null>} 后端原始数据
     */
    async function fetchFromBackend() {
        const now = Date.now();

        // 缓存命中检查
        if (cachedData && (now - lastFetchTime) < CACHE_CONFIG.ttl) {
            return cachedData;
        }

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), CACHE_CONFIG.timeout);

            const response = await fetch('/feixue_monitor/snapshot', {
                method: 'GET',
                signal: controller.signal,
                headers: { 'Accept': 'application/json' }
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                if (response.status === 503) {
                    backendAvailable = false;
                    return null;
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            // 验证数据有效性
            if (!data || data.error) {
                throw new Error(data.error || 'Invalid data');
            }

            // ★★★ 关键修复：支持新旧两种格式 ★★★
            // 新格式 (FeixueHardwareInfo v2.0): { cpu_utilization, gpus: [...], ram: {...} }
            // 旧格式 (MonitorSnapshot): { cpu: {...}, gpu: {...}, ram: {...} }
            const isNewFormat = data.cpu_utilization !== undefined ||
                               (data.gpus && Array.isArray(data.gpus));
            const isOldFormat = data.cpu !== undefined || data.gpu !== undefined;

            if (!isNewFormat && !isOldFormat) {
                console.warn('[飞雪监测器] 后端数据格式无法识别:', Object.keys(data));
                throw new Error('Unrecognized data format');
            }

            // 更新缓存
            cachedData = data;
            lastFetchTime = now;
            backendAvailable = true;

            // 详细日志记录
            console.log('[飞雪监测器] ✓ 收到后端数据 (格式:', isNewFormat ? 'NEW' : 'OLD', ')', {
                cpu: data.cpu_utilization ?? data?.cpu?.utilization,
                ram_percent: data.ram?.percent,
                gpu_util: data.gpus?.[0]?.gpu_utilization ?? data?.gpu?.utilization,
                vram_percent: data.gpus?.[0]?.vram_percent,
                source: data.data_source,
            });

            return data;

        } catch (error) {
            console.warn('[飞雪监测器] 数据获取失败:', error.message);
            backendAvailable = false;
            return null;
        }
    }

    /**
     * 将缓存的后端原始数据重新解析为标准内部格式
     * 用于后端暂不可用时从缓存恢复显示，避免高负载时全屏 --
     * @param {Object} rawData - 缓存的 fetchFromBackend 原始返回值
     * @returns {Object} 标准化的系统监控数据
     */
    function _parseRawToStandard(rawData) {
        if (!rawData) return getEmptyData('error');
        const isNewFormat = rawData.cpu_utilization !== undefined;

        if (isNewFormat) {
            const gpu0 = (rawData.gpus && rawData.gpus.length > 0) ? rawData.gpus[0] : null;
            return {
                timestamp: rawData.timestamp || Date.now(),
                cpu: { usage: rawData.cpu_utilization },
                ram: {
                    total: rawData.ram?.total_gb,
                    used: rawData.ram?.used_gb,
                    percent: rawData.ram?.percent,
                },
                gpu: {
                    usage: gpu0?.gpu_utilization,
                    vram_used: gpu0?.vram_used_mb,
                    vram_total: gpu0?.vram_total_mb,
                    vram_percent: gpu0?.vram_percent,
                    temperature: gpu0?.gpu_temperature,
                    power_draw: gpu0?.power_draw,
                },
                swap: {
                    used_gb: rawData.swap?.used_gb || rawData.ram?.swap_used_gb || null,
                    percent: rawData.swap?.percent || rawData.ram?.swap_percent || rawData.swap_percent || null,
                },
                data_source: rawData.data_source || 'cached',
                _backend_available: false,  // 标记为缓存数据
                _format: 'new',
                network_io: rawData.network_io || null,
                disk_io: rawData.disk_io || null,
            };
        } else {
            return {
                timestamp: rawData.timestamp || Date.now(),
                cpu: { usage: rawData.cpu?.utilization },
                ram: {
                    total: rawData.ram?.total_gb,
                    used: rawData.ram?.used_gb,
                    percent: rawData.ram?.percent,
                },
                gpu: {
                    usage: rawData.gpu?.utilization,
                    vram_used: rawData.gpu?.vram_used_mb,
                    vram_total: rawData.gpu?.vram_total_mb,
                    vram_percent: rawData.gpu?.vram_percent,
                    temperature: rawData.gpu?.temperature,
                    power_draw: rawData.power?.current_power_w,
                },
                swap: {
                    percent: rawData.ram?.swap_percent,
                    used_gb: rawData.ram?.swap_used_gb || rawData.swap?.used_gb || null,
                },
                data_source: rawData.data_source || 'cached',
                _backend_available: false,
                _format: 'old',
                network_io: rawData.network_io || null,
                disk_io: rawData.disk_io || null,
            };
        }
    }

    /**
     * 统一数据采集和标准化接口
     *
     * **核心改进**：
     * - 自动检测新旧格式并统一转换
     * - 输出标准化的内部数据结构
     * - 完全移除 prediction 字段
     *
     * @async
     * @returns {Promise<Object>} 标准化的系统监控数据
     */
    async function collectSystemData() {
        try {
            const realData = await fetchFromBackend();

            if (!realData) {
                // 后端不可用：优先使用缓存数据（高负载时不闪 --）
                // 只有完全没有历史数据时才返回空结构
                if (cachedData && Object.keys(cachedData).length > 2) {
                    console.debug('[飞雪监测器] 使用缓存数据（后端暂不可用）');
                    // 从缓存重新解析，确保格式一致
                    return _parseRawToStandard(cachedData);
                }
                return getEmptyData('unavailable');
            }

            // ★★★ 格式自适应解析 ★=======
            const isNewFormat = realData.cpu_utilization !== undefined;

            if (isNewFormat) {
                // ===== 新格式解析 (FeixueHardwareInfo v2.0) =====
                const gpu0 = (realData.gpus && realData.gpus.length > 0) ? realData.gpus[0] : null;
                const parsed = {
                    timestamp: realData.timestamp || Date.now(),
                    cpu: { usage: realData.cpu_utilization },
                    ram: {
                        total: realData.ram?.total_gb,
                        used: realData.ram?.used_gb,
                        percent: realData.ram?.percent,
                    },
                    gpu: {
                        usage: gpu0?.gpu_utilization,
                        vram_used: gpu0?.vram_used_mb,
                        vram_total: gpu0?.vram_total_mb,
                        vram_percent: gpu0?.vram_percent,
                        temperature: gpu0?.gpu_temperature,
                        power_draw: gpu0?.power_draw,
                    },
                    swap: {
                        used_gb: realData.swap?.used_gb || realData.ram?.swap_used_gb || null,
                        percent: realData.swap?.percent || realData.ram?.swap_percent || realData.swap_percent || null,
                    },
                    data_source: realData.data_source || 'backend-api',
                    _backend_available: true,
                    _format: 'new',
                    network_io: realData.network_io || null,
                    disk_io: realData.disk_io || null,
                };
                return parsed;
            } else {
                // ===== 旧格式解析 (MonitorSnapshot) =====
                return {
                    timestamp: realData.timestamp || Date.now(),

                    cpu: {
                        usage: realData.cpu?.utilization,
                    },

                    ram: {
                        total: realData.ram?.total_gb,
                        used: realData.ram?.used_gb,
                        percent: realData.ram?.percent,
                    },

                    gpu: {
                        usage: realData.gpu?.utilization,
                        vram_used: realData.gpu?.vram_used_mb,
                        vram_total: realData.gpu?.vram_total_mb,
                        vram_percent: realData.gpu?.vram_percent,
                        temperature: realData.gpu?.temperature,
                        power_draw: realData.power?.current_power_w,
                    },

                    swap: {
                        percent: realData.ram?.swap_percent,
                        used_gb: realData.ram?.swap_used_gb || realData.swap?.used_gb || null,
                    },

                    data_source: realData.data_source || 'backend-api',
                    _backend_available: true,
                    _format: 'old',

                    // 网络与磁盘IO（透传原始字段供系统详情使用）
                    network_io: realData.network_io || null,
                    disk_io: realData.disk_io || null,
                };
            }

        } catch (e) {
            console.error('[飞雪监测器] ❌ 数据采集异常:', e);
            return getEmptyData('error');
        }
    }

    /**
     * 获取空数据结构（后端不可用时）
     * @param {string} reason - 原因标识
     * @returns {Object} 空数据对象
     */
    function getEmptyData(reason) {
        return {
            timestamp: Date.now(),
            cpu: { usage: null },
            ram: { total: null, used: null, percent: null },
            gpu: { usage: null, vram_used: null, vram_total: null, vram_percent: null, temperature: null, power_draw: null },
            swap: { percent: null },
            data_source: reason,
            _backend_available: false,
            network_io: null,
            disk_io: null,
        };
    }

    /**
     * 从嵌套对象中安全获取值
     * 支持路径如 "gpu.vram_percent", "gpus[0].gpu_utilization"
     *
     * @param {Object} obj - 源对象
     * @param {string} path - 属性路径
     * @returns {*} 值或 undefined
     */
    function getValueByPath(obj, path) {
        if (!obj || !path) return undefined;

        const keys = path.replace(/\[(\w+)\]/g, '.$1').split('.');
        let current = obj;

        for (const key of keys) {
            if (current === null || current === undefined) return undefined;
            current = current[key];
        }

        return current;
    }

    // ============================================================
    // 数据防乱码处理工具函数
    // ============================================================

    /** 已知乱码/无效文本黑名单 */
    const GARBAGE_PATTERNS = ['英国', 'N/A', '赵瑶金', 'undefined', 'null', 'NaN', 'Infinity'];

    /**
     * 清理数值，过滤乱码和无效值
     * @param {*} val - 原始值
     * @returns {number|null} 清理后的数值或 null
     */
    function sanitizeValue(val) {
        if (val === null || val === undefined) return null;

        // 转为字符串检查乱码
        const strVal = String(val).trim();

        // 检查是否是已知乱码
        for (const garbage of GARBAGE_PATTERNS) {
            if (strVal.includes(garbage)) return null;
        }

        // 尝试转为数字
        const num = Number(val);
        if (isNaN(num) || !isFinite(num)) return null;

        // 合理范围检查（百分比 0-100+，温度 0-150）
        return num;
    }

    /**
     * 过滤最终显示文本中的乱码（防止 GB 被渲染为"英国"等问题）
     * @param {string} text - 待显示文本
     * @returns {string} 安全的显示文本
     */
    function sanitizeDisplayText(text) {
        if (!text) return '--';
        let result = String(text).trim();
        for (const garbage of GARBAGE_PATTERNS) {
            if (result.includes(garbage)) {
                result = result.replace(garbage, '').trim();
            }
        }
        // 如果清洗后为空或只剩单位符号，返回 --
        if (!result || /^[\s%GB°C]*$/.test(result)) return '--';
        return result;
    }

    /**
     * 获取安全的显示文本
     * @param {*} val - 原始值
     * @param {string} fallback - 默认显示文本
     * @returns {string} 安全的显示文本
     */
    function safeDisplay(val, fallback) {
        const cleaned = sanitizeValue(val);
        if (cleaned !== null) return String(cleaned);
        return fallback || '--';
    }

    // ============================================================
    // Premium UI v3.25 — 5 主题系统
    // ============================================================

    // ============================================================
    // 拖拽状态
    // ============================================================
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let barStartLeft = 0;
    let barStartTop = 0;
    let isDragEnabled = false;        // Drag Mode开关控制：false=不可拖拽(默认), true=可拖拽
    let savedBarLeft = null;          // localStorage 记忆位置
    let savedBarTop = null;

    /** 当前风格（与 switchStyle 共用） */
    let currentStyle = 'neu';

    // ============================================================
    // CSS 注入 — Premium UI v3.25 内联样式
    // ============================================================

    /**
     * 内联注入 Premium UI CSS v19.0 - 5套主题完整样式
     * Neu(拟物白) / Ind(钛金仪) / Retro(复古终端) / Lux(珠宝柜) / Cyber(量子核)
     */
    function injectPremiumCSS() {
        // 避免重复注入
        const existing = document.getElementById('fxm-emerald-css');
        if (existing) {
            existing.remove();
            console.log('[飞雪监测器] 🗑️ 已清除旧版CSS');
        }

        const style = document.createElement('style');
        style.id = 'fxm-emerald-css';
        style.setAttribute('data-version', '19.0');
        style.textContent = `

    /* 通用隐藏类 */
    .style-hidden { display: none !important; }

    /* === neu的全部CSS（从v10-neu-fragment.html升级）=== */

/* ============================================
   FEIXUE MONITOR v10 - Neu v2 "Aurora Ceramic"
   世界级新拟物设计系统 · 极光陶瓷版
   物理隐喻：悬浮在空中的高级哑光陶瓷 plaque
   ============================================ */

/* ============================================
   1. CSS变量系统 (Design Tokens)
   集中管理所有主题色彩和尺寸
   ============================================ */
:root {
    /* ★ 核心法则: 同色原则 (Monochromatic Base)
       所有元素基色完全相同，这是Neumorphism的核心！*/
    --neu-base-color: #e0e5ec;

    /* 文字颜色系统 */
    --neu-text-primary: #4a5568;
    --neu-text-secondary: #a0aec0;
    --neu-text-accent: #2d3748;
    --neu-text-muted: rgba(113, 128, 150, 0.75);

    /* 警告/危险颜色 */
    --neu-color-warning: #d69e2e;
    --neu-color-danger: #c53030;

    /* 主渐变色（Aurora默认）*/
    --neu-gradient-primary: linear-gradient(
        90deg,
        #00f2fe 0%,
        #4facfe 25%,
        #a855f7 50%,
        #ec4899 75%,
        #00f2fe 100%
    );

    /* 指标专用渐变色 */
    --neu-gradient-gpu: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
    --neu-gradient-vram: linear-gradient(135deg, #a855f7 0%, #7c3aed 100%);
    --neu-gradient-cpu: linear-gradient(135deg, #38a169 0%, #22c55e 100%);
    --neu-gradient-ram: linear-gradient(135deg, #805ad5 0%, #6366f1 100%);
    --neu-gradient-swap: linear-gradient(135deg, #dd6b20 0%, #f97316 100%);
    --neu-gradient-temp: linear-gradient(135deg, #c53030 0%, #ef4444 100%);

    /* ★★★ 双光源对角阴影系统（核心！）
       左上亮光源 + 右下暗光源 = 真实物理光照感 */

    /* 外凸阴影 - 大型容器（Panel/Dock）*/
    --neu-shadow-convex-large:
        12px 12px 24px rgb(163, 177, 198, 0.6),
        -12px -12px 24px rgba(255, 255, 255, 0.85);

    /* 外凸阴影 - 中型元素（Card/Chip）*/
    --neu-shadow-convex-medium:
        7px 7px 14px rgb(163, 177, 198, 0.5),
        -7px -7px 14px rgba(255, 255, 255, 0.82);

    /* 外凸阴影 - 小型元素（Button/Badge）*/
    --neu-shadow-convex-small:
        4px 4px 10px rgb(163, 177, 198, 0.45),
        -4px -4px 10px rgba(255, 255, 255, 0.8);

    /* 内凹阴影 - 按压态/输入框/进度槽
       使用inset让元素看起来"陷入"表面*/
    --neu-shadow-concave:
        inset 5px 5px 10px rgb(163, 177, 198, 0.65),
        inset -5px -5px 10px rgba(255, 255, 255, 0.92);

    /* 微凹阴影 - 迷你进度条轨道*/
    --neu-shadow-concave-mini:
        inset 2px 2px 5px rgb(163, 177, 198, 0.55),
        inset -2px -2px 5px rgba(255, 255, 255, 0.88);

    /* Hover增强阴影 */
    --neu-shadow-hover-large:
        16px 16px 32px rgb(163, 177, 198, 0.65),
        -16px -16px 32px rgba(255, 255, 255, 0.9);

    --neu-shadow-hover-medium:
        10px 10px 18px rgb(163, 177, 198, 0.55),
        -10px -10px 18px rgba(255, 255, 255, 0.88);

    /* 尺寸令牌 (Design Tokens) */
    --neu-dock-height: 60px;
    --neu-dock-width: 800px;
    --neu-panel-width: 340px;
    --neu-panel-radius: 24px;
    --neu-card-radius: 18px;
    --neu-header-radius: 16px;
    --neu-button-radius: 12px;
    --neu-chip-radius: 14px;

    /* 字体系统 */
    --neu-font-ui: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --neu-font-mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
    --neu-font-size-xs: 10px;
    --neu-font-size-sm: 11px;
    --neu-font-size-base: 13px;
    --neu-font-size-lg: 15px;
    --neu-font-size-xl: 18px;

    /* 间距系统（4px网格）*/
    --neu-space-xs: 4px;
    --neu-space-sm: 8px;
    --neu-space-md: 12px;
    --neu-space-lg: 16px;
    --neu-space-xl: 20px;
    --neu-space-xxl: 24px;

    /* 过渡动画时长 */
    --neu-transition-fast: 0.2s ease;
    --neu-transition-normal: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    --neu-transition-slow: 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

/* ============================================
   2. 五种世界级主题色彩定义
   每个主题都有独特的色彩性格
   ============================================ */

/* Theme 1: Aurora（极光·青花瓷）- 默认 */
[data-neu-theme="aurora"] {
    --neu-base-color: #e0e5ec;
    --neu-shadow-dark-color: rgb(163, 177, 198);
    --neu-gradient-primary: linear-gradient(90deg, #00f2fe 0%, #4facfe 25%, #a855f7 50%, #ec4899 75%, #00f2fe 100%);
    --neu-text-primary: #4a5568;
    --neu-text-secondary: #a0aec0;
}

/* Theme 2: Ocean（深海·静谧蓝）*/
[data-neu-theme="ocean"] {
    --neu-base-color: #e8f4f8;
    --neu-shadow-dark-color: rgb(140, 170, 190);
    --neu-gradient-primary: linear-gradient(90deg, #0077b6 0%, #00b4d8 50%, #90e0ef 100%);
    --neu-text-primary: #2c5282;
    --neu-text-secondary: #4299e1;
}

/* Theme 3: Sunset（暮光·琥珀金）*/
[data-neu-theme="sunset"] {
    --neu-base-color: #faf6f0;
    --neu-shadow-dark-color: rgb(180, 160, 140);
    --neu-gradient-primary: linear-gradient(90deg, #ff6b35 0%, #f7931e 50%, #ffd23f 100%);
    --neu-text-primary: #7b341e;
    --neu-text-secondary: #c05621;
}

/* Theme 4: Forest（森林·翡翠绿）*/
[data-neu-theme="forest"] {
    --neu-base-color: #f0f5f1;
    --neu-shadow-dark-color: rgb(140, 165, 150);
    --neu-gradient-primary: linear-gradient(90deg, #2d6a4f 0%, #40916c 50%, #74c69d 100%);
    --neu-text-primary: #276749;
    --neu-text-secondary: #38a169;
}

/* Theme 5: Midnight（午夜·极光紫）*/
[data-neu-theme="midnight"] {
    --neu-base-color: #d0d5dc;
    --neu-shadow-dark-color: rgb(130, 140, 155);
    --neu-gradient-primary: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
    --neu-text-primary: #374151;
    --neu-text-secondary: #6b7280;
}

/* 动态更新阴影颜色（跟随主题变化）*/
[data-neu-theme="aurora"] {
    --neu-shadow-convex-large: 12px 12px 24px rgba(163, 177, 198, 0.6), -12px -12px 24px rgba(255, 255, 255, 0.85);
    --neu-shadow-convex-medium: 7px 7px 14px rgba(163, 177, 198, 0.5), -7px -7px 14px rgba(255, 255, 255, 0.82);
    --neu-shadow-convex-small: 4px 4px 10px rgba(163, 177, 198, 0.45), -4px -4px 10px rgba(255, 255, 255, 0.8);
    --neu-shadow-concave: inset 5px 5px 10px rgba(163, 177, 198, 0.65), inset -5px -5px 10px rgba(255, 255, 255, 0.92);
    --neu-shadow-concave-mini: inset 2px 2px 5px rgba(163, 177, 198, 0.55), inset -2px -2px 5px rgba(255, 255, 255, 0.88);
    --neu-shadow-hover-large: 16px 16px 32px rgba(163, 177, 198, 0.65), -16px -16px 32px rgba(255, 255, 255, 0.9);
    --neu-shadow-hover-medium: 10px 10px 18px rgba(163, 177, 198, 0.55), -10px -10px 18px rgba(255, 255, 255, 0.88);
}

[data-neu-theme="ocean"] {
    --neu-shadow-convex-large: 12px 12px 24px rgba(140, 170, 190, 0.55), -12px -12px 24px rgba(255, 255, 255, 0.9);
    --neu-shadow-convex-medium: 7px 7px 14px rgba(140, 170, 190, 0.45), -7px -7px 14px rgba(255, 255, 255, 0.88);
    --neu-shadow-convex-small: 4px 4px 10px rgba(140, 170, 190, 0.4), -4px -4px 10px rgba(255, 255, 255, 0.86);
    --neu-shadow-concave: inset 5px 5px 10px rgba(140, 170, 190, 0.6), inset -5px -5px 10px rgba(255, 255, 255, 0.94);
    --neu-shadow-concave-mini: inset 2px 2px 5px rgba(140, 170, 190, 0.5), inset -2px -2px 5px rgba(255, 255, 255, 0.91);
    --neu-shadow-hover-large: 16px 16px 32px rgba(140, 170, 190, 0.6), -16px -16px 32px rgba(255, 255, 255, 0.92);
    --neu-shadow-hover-medium: 10px 10px 18px rgba(140, 170, 190, 0.5), -10px -10px 18px rgba(255, 255, 255, 0.9);
}

[data-neu-theme="sunset"] {
    --neu-shadow-convex-large: 12px 12px 24px rgba(180, 160, 140, 0.55), -12px -12px 24px rgba(255, 255, 255, 0.94);
    --neu-shadow-convex-medium: 7px 7px 14px rgba(180, 160, 140, 0.45), -7px -7px 14px rgba(255, 255, 255, 0.92);
    --neu-shadow-convex-small: 4px 4px 10px rgba(180, 160, 140, 0.4), -4px -4px 10px rgba(255, 255, 255, 0.9);
    --neu-shadow-concave: inset 5px 5px 10px rgba(180, 160, 140, 0.6), inset -5px -5px 10px rgba(255, 255, 255, 0.96);
    --neu-shadow-concave-mini: inset 2px 2px 5px rgba(180, 160, 140, 0.5), inset -2px -2px 5px rgba(255, 255, 255, 0.94);
    --neu-shadow-hover-large: 16px 16px 32px rgba(180, 160, 140, 0.6), -16px -16px 32px rgba(255, 255, 255, 0.96);
    --neu-shadow-hover-medium: 10px 10px 18px rgba(180, 160, 140, 0.5), -10px -10px 18px rgba(255, 255, 255, 0.94);
}

[data-neu-theme="forest"] {
    --neu-shadow-convex-large: 12px 12px 24px rgba(140, 165, 150, 0.55), -12px -12px 24px rgba(255, 255, 255, 0.9);
    --neu-shadow-convex-medium: 7px 7px 14px rgba(140, 165, 150, 0.45), -7px -7px 14px rgba(255, 255, 255, 0.88);
    --neu-shadow-convex-small: 4px 4px 10px rgba(140, 165, 150, 0.4), -4px -4px 10px rgba(255, 255, 255, 0.86);
    --neu-shadow-concave: inset 5px 5px 10px rgba(140, 165, 150, 0.6), inset -5px -5px 10px rgba(255, 255, 255, 0.94);
    --neu-shadow-concave-mini: inset 2px 2px 5px rgba(140, 165, 150, 0.5), inset -2px -2px 5px rgba(255, 255, 255, 0.91);
    --neu-shadow-hover-large: 16px 16px 32px rgba(140, 165, 150, 0.6), -16px -16px 32px rgba(255, 255, 255, 0.92);
    --neu-shadow-hover-medium: 10px 10px 18px rgba(140, 165, 150, 0.5), -10px -10px 18px rgba(255, 255, 255, 0.9);
}

[data-neu-theme="midnight"] {
    --neu-shadow-convex-large: 12px 12px 24px rgba(130, 140, 155, 0.55), -12px -12px 24px rgba(255, 255, 255, 0.88);
    --neu-shadow-convex-medium: 7px 7px 14px rgba(130, 140, 155, 0.45), -7px -7px 14px rgba(255, 255, 255, 0.86);
    --neu-shadow-convex-small: 4px 4px 10px rgba(130, 140, 155, 0.4), -4px -4px 10px rgba(255, 255, 255, 0.84);
    --neu-shadow-concave: inset 5px 5px 10px rgba(130, 140, 155, 0.6), inset -5px -5px 10px rgba(255, 255, 255, 0.92);
    --neu-shadow-concave-mini: inset 2px 2px 5px rgba(130, 140, 155, 0.5), inset -2px -2px 5px rgba(255, 255, 255, 0.89);
    --neu-shadow-hover-large: 16px 16px 32px rgba(130, 140, 155, 0.6), -16px -16px 32px rgba(255, 255, 255, 0.9);
    --neu-shadow-hover-medium: 10px 10px 18px rgba(130, 140, 155, 0.5), -10px -10px 18px rgba(255, 255, 255, 0.88);
}

/* ============================================
   3. 全局重置与基础样式
   ============================================ */


body {
    font-family: var(--neu-font-ui);
    background-color: var(--neu-base-color);
    color: var(--neu-text-primary);
    line-height: 1.5;
    min-height: 100vh;
    transition: background-color 0.5s cubic-bezier(0.4, 0, 0.2, 1),
                color 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* ============================================
   4. DOCK 组件 - 监测条主容器
   扁长胶囊形，720x60px，fixed定位居中
   ============================================ */
#neu-dock {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    width: var(--neu-dock-width);
    height: var(--neu-dock-height);
    z-index: 99999;
    display: flex;
    align-items: center;
    gap: var(--neu-space-md);
    padding: 0 var(--neu-space-lg);

    /* 纯色陶瓷底（无渐变底色！）*/
    background-color: var(--neu-base-color);
    border-radius: 30px;

    /* 柔和弥散阴影 + 强横截面倒角：1px 上/左高光 + 下/右暗边，营造厚陶瓷边缘 */
    box-shadow:
        /* 外部悬浮阴影 */
        0 14px 36px rgba(0, 0, 0, 0.11),
        0 5px 14px rgba(0, 0, 0, 0.07),
        /* 上沿/左沿高光（横截面亮面）*/
        inset 0 1px 0 rgba(255, 255, 255, 0.72),
        inset 1px 0 0 rgba(255, 255, 255, 0.45),
        /* 下沿/右沿暗边（厚度阴影）*/
        inset 0 -1px 0 rgba(0, 0, 0, 0.08),
        inset -1px 0 0 rgba(0, 0, 0, 0.05),
        /* 内凹倒角 */
        inset 0 2px 3px rgba(255, 255, 255, 0.25),
        inset 0 -2px 3px rgba(0, 0, 0, 0.03);

    border: 1px solid rgba(255, 255, 255, 0.22);

    /* 平滑过渡（用于主题切换）*/
    transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);

    user-select: none;
}

#neu-dock:hover {
    box-shadow:
        0 18px 44px rgba(0, 0, 0, 0.13),
        0 7px 18px rgba(0, 0, 0, 0.09),
        inset 0 1px 0 rgba(255, 255, 255, 0.78),
        inset 1px 0 0 rgba(255, 255, 255, 0.50),
        inset 0 -1px 0 rgba(0, 0, 0, 0.09),
        inset -1px 0 0 rgba(0, 0, 0, 0.06),
        inset 0 2px 3px rgba(255, 255, 255, 0.28),
        inset 0 -2px 3px rgba(0, 0, 0, 0.04);
}

/* 左侧 ~1mm 横截面高光 — 模拟陶瓷 plaque 左边缘受光 */
#neu-dock::before {
    content: '';
    position: absolute;
    left: 2px;
    top: 12%;
    bottom: 12%;
    width: 3px;
    background: linear-gradient(180deg,
        transparent 0%,
        rgba(255, 255, 255, 0.65) 15%,
        rgba(255, 255, 255, 0.90) 50%,
        rgba(255, 255, 255, 0.65) 85%,
        transparent 100%);
    border-radius: 2px;
    box-shadow: 0 0 5px rgba(255, 255, 255, 0.30);
    pointer-events: none;
}

/* 拖拽手柄 - 6个小凹点组成的圆点组 */
.neu-dock-handle {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    width: 28px;
    height: 40px;
    cursor: grab;
    flex-shrink: 0;
}

.neu-dock-handle:active {
    cursor: grabbing;
}

.neu-handle-dot {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background-color: var(--neu-base-color);
    box-shadow: var(--neu-shadow-concave-mini);
}

/* 单个指标模块 - 微凸小矩形 */
.neu-metric-chip {
    display: grid;
    grid-template-columns: auto 1fr;
    grid-template-rows: auto auto;
    gap: 2px 6px;
    height: 44px;
    padding: 6px 12px;
    background-color: var(--neu-base-color);
    border-radius: var(--neu-chip-radius);

    /* 强微凸立体感：外凸阴影 + 横截面高光/暗边 */
    box-shadow:
        var(--neu-shadow-convex-medium),
        /* 上/左高光边 */
        inset 0 1px 0 rgba(255, 255, 255, 0.65),
        inset 1px 0 0 rgba(255, 255, 255, 0.40),
        /* 下/右暗边 */
        inset 0 -1px 0 rgba(0, 0, 0, 0.06),
        inset -1px 0 0 rgba(0, 0, 0, 0.04);

    cursor: default;
    transition: all 0.25s ease;
    user-select: none;
    white-space: nowrap;
    position: relative;
    flex: 1;
    min-width: 90px;
    max-width: 110px;
}

.neu-metric-chip:hover {
    transform: translateY(-3px) scale(1.02);
    box-shadow:
        var(--neu-shadow-hover-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.72),
        inset 1px 0 0 rgba(255, 255, 255, 0.45),
        inset 0 -1px 0 rgba(0, 0, 0, 0.07),
        inset -1px 0 0 rgba(0, 0, 0, 0.05);
}

.neu-metric-chip:active,
.neu-metric-chip.pressed {
    transform: translateY(0) scale(0.98);
    box-shadow:
        var(--neu-shadow-concave),
        inset 0 1px 0 rgba(0, 0, 0, 0.04),
        inset 1px 0 0 rgba(0, 0, 0, 0.03),
        inset 0 -1px 0 rgba(255, 255, 255, 0.35),
        inset -1px 0 0 rgba(255, 255, 255, 0.22);
}

/* 芯片图标 */
.neu-chip-icon {
    font-size: 14px;
    line-height: 1;
    grid-row: 1 / 3;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.85;
}

/* 芯片标签 */
.neu-chip-label {
    font-size: var(--neu-font-size-xs);
    font-weight: 600;
    color: var(--neu-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    transition: color 0.5s ease;
}

/* 芯片数值 - JetBrains Mono等宽字体 */
.neu-chip-value {
    font-size: 13px;
    font-weight: 700;
    font-family: var(--neu-font-mono);
    color: var(--neu-text-primary);
    justify-self: end;
    transition: color 0.5s ease;
    font-variant-numeric: tabular-nums;
}

/* 数值分类型纯色（对齐shili参考样本，稳定可靠）*/
.neu-metric-chip[data-type="gpu"] .neu-chip-value { color: #d69e2e; }
.neu-metric-chip[data-type="vram"] .neu-chip-value { color: #3182ce; }
.neu-metric-chip[data-type="cpu"] .neu-chip-value { color: #38a169; }
.neu-metric-chip[data-type="ram"] .neu-chip-value { color: #805ad5; }
.neu-metric-chip[data-type="swap"] .neu-chip-value { color: #dd6b20; }
.neu-metric-chip[data-type="temp"] .neu-chip-value { color: #c53030; }

/* 迷你进度条 - 内凹槽(mini inset) + 渐变填充(4px高) */
.neu-chip-progress-track {
    grid-column: 1 / -1;
    height: 4px;
    background-color: var(--neu-base-color);
    border-radius: 2px;

    /* 微凹槽体 - 让进度条有"嵌入"感*/
    box-shadow:
        var(--neu-shadow-concave-mini),
        inset 1px 1px 0 rgba(255, 255, 255, 0.25),
        inset -1px -1px 0 rgba(0, 0, 0, 0.08);

    overflow: hidden;
    position: relative;
    transition: all 0.5s ease;
}

.neu-chip-progress-fill {
    height: 100%;
    background: var(--neu-gradient-primary);
    background-size: 200% 100%;
    border-radius: 2px;
    transition: width 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55);
    position: relative;
}

/* 流动渐变动画*/
@keyframes neu-flow-gradient {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

.neu-chip-progress-fill {
    animation: neu-flow-gradient 4s ease infinite;
}

/* 设置按钮 - 与Dock同材质 */
.neu-settings-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    flex-shrink: 0;
    background-color: var(--neu-base-color);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow:
        var(--neu-shadow-convex-small),
        /* 横截面高光 */
        inset 0 1px 0 rgba(255, 255, 255, 0.65),
        inset 1px 0 0 rgba(255, 255, 255, 0.40),
        /* 横截面暗边 */
        inset 0 -1px 0 rgba(0, 0, 0, 0.06),
        inset -1px 0 0 rgba(0, 0, 0, 0.04);
    cursor: pointer;
    transition: all 0.25s ease;
    border: none;
    outline: none;
    font-size: 16px;
    color: var(--neu-text-secondary);
}

.neu-settings-btn:hover {
    transform: scale(1.08) rotate(45deg);
    box-shadow:
        var(--neu-shadow-hover-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.72),
        inset 1px 0 0 rgba(255, 255, 255, 0.45),
        inset 0 -1px 0 rgba(0, 0, 0, 0.07),
        inset -1px 0 0 rgba(0, 0, 0, 0.05);
    color: var(--neu-text-primary);
}

.neu-settings-btn:active {
    transform: scale(0.96) rotate(45deg);
    box-shadow:
        var(--neu-shadow-concave),
        inset 0 1px 0 rgba(0, 0, 0, 0.04),
        inset 1px 0 0 rgba(0, 0, 0, 0.03),
        inset 0 -1px 0 rgba(255, 255, 255, 0.35),
        inset -1px 0 0 rgba(255, 255, 255, 0.22);
}

/* ============================================
   5. PANEL 组件 - 控制面板
   完全复用monitor-panel.html的可折叠布局
   固定定位右上角，340px宽
   ============================================ */
#neu-panel {
    position: fixed;
    top: 85px;
    right: 20px;
    width: var(--neu-panel-width);
    max-height: calc(100vh - 105px);
    overflow-y: auto;
    z-index: 99999;
    padding: var(--neu-space-xl);

    /* 陶瓷面板底色*/
    background-color: var(--neu-base-color);
    border-radius: var(--neu-panel-radius);

    /* 强立体感：弥散阴影 + 1px 横截面高光/暗边 + 内凹倒角 */
    box-shadow:
        /* 外部悬浮阴影 */
        0 22px 55px rgba(0, 0, 0, 0.15),
        0 8px 22px rgba(0, 0, 0, 0.10),
        /* 上沿/左沿横截面高光 */
        inset 0 1px 0 rgba(255, 255, 255, 0.75),
        inset 1px 0 0 rgba(255, 255, 255, 0.48),
        /* 下沿/右沿厚度暗边 */
        inset 0 -1px 0 rgba(0, 0, 0, 0.09),
        inset -1px 0 0 rgba(0, 0, 0, 0.06),
        /* 内凹倒角 */
        inset 0 2px 4px rgba(255, 255, 255, 0.28),
        inset 0 -2px 4px rgba(0, 0, 0, 0.04);

    /* 降低与深色背景的对比跳变，同时保留面板浮起感 */
    border: 1px solid rgba(255, 255, 255, 0.16);

    /* 平滑过渡*/
    transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);

    /* 自定义滚动条*/
    scrollbar-width: thin;
    scrollbar-color: var(--neu-text-muted) transparent;
}

#neu-panel::-webkit-scrollbar {
    width: 6px;
}

#neu-panel::-webkit-scrollbar-track {
    background: transparent;
}

#neu-panel::-webkit-scrollbar-thumb {
    background-color: var(--neu-text-muted);
    border-radius: 3px;
}

/* 面板左侧 ~1mm 横截面高光 — 与 Dock 形成统一光照方向 */
#neu-panel::before {
    content: '';
    position: absolute;
    left: 2px;
    top: 8%;
    bottom: 8%;
    width: 3px;
    background: linear-gradient(180deg,
        transparent 0%,
        rgba(255, 255, 255, 0.55) 12%,
        rgba(255, 255, 255, 0.85) 50%,
        rgba(255, 255, 255, 0.55) 88%,
        transparent 100%);
    border-radius: 2px;
    box-shadow: 0 0 5px rgba(255, 255, 255, 0.25);
    pointer-events: none;
}

/* Panel Header - 品牌区域 */
.neu-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--neu-space-xl);
    padding-bottom: var(--neu-space-lg);
    border-bottom: 1px solid rgba(163, 177, 198, 0.25);
}

.neu-header-brand {
    display: flex;
    align-items: center;
    gap: 10px;
}

.neu-brand-icon {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: var(--neu-gradient-primary);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    box-shadow:
        var(--neu-shadow-convex-small),
        inset 1px 1px 0 rgba(255, 255, 255, 0.45),
        inset -1px -1px 0 rgba(0, 0, 0, 0.10);
    color: white;
}

.neu-brand-text h1 {
    font-size: var(--neu-font-size-lg);
    font-weight: 700;
    color: var(--neu-text-primary);
    letter-spacing: 0.5px;
    line-height: 1.2;
    transition: color 0.5s ease;
}

.neu-brand-text span {
    font-size: var(--neu-font-size-xs);
    color: var(--neu-text-muted);
    font-family: var(--neu-font-mono);
    font-weight: 500;
}

.neu-header-actions {
    display: flex;
    gap: 8px;
}

.neu-action-btn {
    width: 30px;
    height: 30px;
    border-radius: 8px;
    border: none;
    background-color: var(--neu-base-color);
    color: var(--neu-text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    box-shadow:
        var(--neu-shadow-convex-small),
        inset 0 1px 0 rgba(255, 255, 255, 0.65),
        inset 1px 0 0 rgba(255, 255, 255, 0.40),
        inset 0 -1px 0 rgba(0, 0, 0, 0.06),
        inset -1px 0 0 rgba(0, 0, 0, 0.04);
    transition: all 0.25s ease;
}

.neu-action-btn:hover {
    transform: translateY(-2px);
    box-shadow:
        var(--neu-shadow-hover-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.72),
        inset 1px 0 0 rgba(255, 255, 255, 0.45),
        inset 0 -1px 0 rgba(0, 0, 0, 0.07),
        inset -1px 0 0 rgba(0, 0, 0, 0.05);
    color: var(--neu-text-primary);
}

.neu-action-btn:active {
    box-shadow:
        var(--neu-shadow-concave),
        inset 0 1px 0 rgba(0, 0, 0, 0.04),
        inset 1px 0 0 rgba(0, 0, 0, 0.03),
        inset 0 -1px 0 rgba(255, 255, 255, 0.35),
        inset -1px 0 0 rgba(255, 255, 255, 0.22);
    transform: scale(0.95);
}

/* 核心指标区 - 3列大数字卡片 */
.neu-metrics-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: var(--neu-space-lg);
}

.neu-metric-card {
    background-color: var(--neu-base-color);
    border-radius: var(--neu-card-radius);
    padding: 12px 8px;
    box-shadow:
        var(--neu-shadow-convex-medium),
        /* 上/左高光边 */
        inset 0 1px 0 rgba(255, 255, 255, 0.70),
        inset 1px 0 0 rgba(255, 255, 255, 0.42),
        /* 下/右暗边 */
        inset 0 -1px 0 rgba(0, 0, 0, 0.07),
        inset -1px 0 0 rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.22);
    text-align: center;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
}

.neu-metric-card:hover {
    transform: translateY(-3px);
    box-shadow:
        var(--neu-shadow-hover-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.78),
        inset 1px 0 0 rgba(255, 255, 255, 0.48),
        inset 0 -1px 0 rgba(0, 0, 0, 0.08),
        inset -1px 0 0 rgba(0, 0, 0, 0.06);
}

/* 卡片顶部彩色条 */
.neu-metric-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--metric-color, var(--neu-gradient-primary));
    opacity: 0.85;
}

.neu-metric-label {
    font-size: 9px;
    font-weight: 600;
    color: var(--neu-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 4px;
}

.neu-metric-value {
    font-size: 22px;
    font-weight: 700;
    font-family: var(--neu-font-mono);
    color: var(--metric-color, var(--neu-text-primary));
    line-height: 1;
    margin-bottom: 4px;
}

.neu-metric-unit {
    font-size: 11px;
    font-weight: 500;
    color: var(--neu-text-secondary);
}

.neu-metric-trend {
    height: 24px;
    margin-top: 4px;
    opacity: 0.65;
}

/* 指标颜色映射 */
.neu-metric-card[data-metric="gpu"] { --metric-color: #00d4ff; }
.neu-metric-card[data-metric="cpu"] { --metric-color: #38a169; }
.neu-metric-card[data-metric="ram"] { --metric-color: #805ad5; }

/* 可折叠详情区 - Accordion机制 */
.neu-detail-section {
    margin-bottom: var(--neu-space-lg);
}

.neu-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    background-color: var(--neu-base-color);
    border-radius: var(--neu-header-radius);
    box-shadow:
        var(--neu-shadow-convex-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.70),
        inset 1px 0 0 rgba(255, 255, 255, 0.42),
        inset 0 -1px 0 rgba(0, 0, 0, 0.07),
        inset -1px 0 0 rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.22);
    cursor: pointer;
    transition: all 0.25s ease;
    user-select: none;
}

.neu-section-header:hover {
    box-shadow:
        var(--neu-shadow-hover-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.78),
        inset 1px 0 0 rgba(255, 255, 255, 0.48),
        inset 0 -1px 0 rgba(0, 0, 0, 0.08),
        inset -1px 0 0 rgba(0, 0, 0, 0.06);
}

.neu-section-title {
    font-size: var(--neu-font-size-sm);
    font-weight: 700;
    color: var(--neu-text-secondary);
    text-transform: uppercase;
    letter-spacing: 1px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.neu-section-icon {
    font-size: 14px;
}

.neu-section-toggle {
    font-size: 12px;
    color: var(--neu-text-muted);
    transition: transform 0.3s ease;
}

.neu-section-header.collapsed .neu-section-toggle {
    transform: rotate(-90deg);
}

.neu-section-content {
    margin-top: 12px;
    display: grid;
    gap: 12px;
    animation: neu-slideDown 0.3s ease-out;
}

.neu-section-header.collapsed + .neu-section-content {
    display: none;
}

@keyframes neu-slideDown {
    from {
        opacity: 0;
        transform: translateY(-8px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* 进度条行 */
.neu-progress-row {
    background-color: var(--neu-base-color);
    border-radius: 12px;
    padding: 12px 14px;
    box-shadow:
        var(--neu-shadow-convex-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.70),
        inset 1px 0 0 rgba(255, 255, 255, 0.42),
        inset 0 -1px 0 rgba(0, 0, 0, 0.07),
        inset -1px 0 0 rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.22);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.neu-progress-row:hover {
    box-shadow:
        var(--neu-shadow-hover-medium),
        inset 0 1px 0 rgba(255, 255, 255, 0.78),
        inset 1px 0 0 rgba(255, 255, 255, 0.48),
        inset 0 -1px 0 rgba(0, 0, 0, 0.08),
        inset -1px 0 0 rgba(0, 0, 0, 0.06);
    transform: translateY(-1px);
}

.neu-progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.neu-progress-label {
    font-size: var(--neu-font-size-sm);
    font-weight: 600;
    color: var(--neu-text-primary);
    display: flex;
    align-items: center;
    gap: 6px;
}

.neu-progress-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: var(--dot-color, var(--neu-text-secondary));
}

.neu-progress-badge {
    font-size: var(--neu-font-size-xs);
    font-weight: 700;
    font-family: var(--neu-font-mono);
    padding: 3px 8px;
    border-radius: 6px;
    background-color: var(--neu-base-color);
    box-shadow: var(--neu-shadow-concave);
    color: var(--badge-color, var(--neu-text-primary));
}

/* 进度条轨道 - 沉浸式凹槽体 */
.neu-progress-track {
    height: 14px;
    background-color: var(--neu-base-color);
    border-radius: 10px;
    overflow: hidden;
    box-shadow:
        var(--neu-shadow-concave),
        inset 0 1px 2px rgba(0, 0, 0, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.08);
    position: relative;
}

.neu-progress-fill {
    height: 100%;
    /* 统一使用 Premium Demo 同款 Aurora 多色流动渐变 */
    background: var(--neu-gradient-primary, linear-gradient(90deg, #00f2fe 0%, #4facfe 25%, #a855f7 50%, #ec4899 75%, #00f2fe 100%));
    background-size: 200% 100%;
    border-radius: 10px;
    /* 流动渐变动画 */
    animation: neu-flow-gradient 4s ease infinite;
    /* 内发光 + 底部暗边，营造玻璃/金属质感 */
    box-shadow:
        inset 0 1px 2px rgba(255, 255, 255, 0.55),
        inset 0 -1px 2px rgba(0, 0, 0, 0.16),
        0 0 8px rgba(79, 172, 254, 0.18);
    transition: width 0.4s cubic-bezier(0.68, -0.55, 0.265, 1.55);
    position: relative;
}

/* 光泽层叠加 - 进度条顶部高光带 */
.neu-progress-fill::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 8%;
    right: 8%;
    height: 3px;
    background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(255, 255, 255, 0.85) 40%,
        rgba(255, 255, 255, 0.5) 60%,
        transparent 100%
    );
    border-radius: 2px;
    filter: blur(1px);
    pointer-events: none;
}

/* 进度条点缀/徽章颜色映射 - 保留指标可读性，填充层统一使用 Aurora 流动渐变 */
.neu-progress-row[data-type="gpu"] { --dot-color: #00d4ff; --badge-color: #00d4ff; }
.neu-progress-row[data-type="vram"] { --dot-color: #a855f7; --badge-color: #a855f7; }
.neu-progress-row[data-type="cpu"] { --dot-color: #38a169; --badge-color: #38a169; }
.neu-progress-row[data-type="ram"] { --dot-color: #805ad5; --badge-color: #805ad5; }
.neu-progress-row[data-type="swap"] { --dot-color: #dd6b20; --badge-color: #dd6b20; }
.neu-progress-row[data-type="temp"] { --dot-color: #c53030; --badge-color: #c53030; }

/* IO信息行 */
.neu-details-grid {
    display: grid;
    gap: 8px;
}

.neu-detail-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    background-color: var(--neu-base-color);
    border-radius: 10px;
    box-shadow:
        var(--neu-shadow-convex-small),
        inset 0 1px 0 rgba(255, 255, 255, 0.65),
        inset 1px 0 0 rgba(255, 255, 255, 0.40),
        inset 0 -1px 0 rgba(0, 0, 0, 0.06),
        inset -1px 0 0 rgba(0, 0, 0, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.20);
    font-size: var(--neu-font-size-sm);
}

.neu-detail-left {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--neu-text-secondary);
}

.neu-detail-icon {
    font-size: 13px;
}

.neu-detail-right {
    font-family: var(--neu-font-mono);
    font-size: var(--neu-font-size-xs);
    color: var(--neu-text-primary);
    font-weight: 600;
}

/* 设置与控制区 */
.neu-settings-section {
    margin-top: var(--neu-space-lg);
    padding-top: var(--neu-space-lg);
    border-top: 1px solid rgba(163, 177, 198, 0.25);
}

.neu-settings-group {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.neu-setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    background-color: var(--neu-base-color);
    border-radius: 10px;
    box-shadow: var(--neu-shadow-convex-medium);
    border: 1px solid rgba(255, 255, 255, 0.2);
}

.neu-setting-label {
    font-size: var(--neu-font-size-sm);
    font-weight: 600;
    color: var(--neu-text-primary);
}

/* Toggle开关 - iOS风格 */
.neu-toggle-switch {
    width: 48px;
    height: 26px;
    border-radius: 13px;
    position: relative;
    cursor: pointer;
    transition: all 0.3s ease;
    border: none;
    outline: none;
    background-color: var(--neu-base-color);
    box-shadow: var(--neu-shadow-concave);
    z-index: 999;
    pointer-events: auto;
}

.neu-toggle-switch.active {
    background: var(--neu-gradient-primary);
    box-shadow: var(--neu-shadow-convex-small);
}

.neu-toggle-thumb {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    position: absolute;
    top: 3px;
    left: 3px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    background-color: var(--neu-base-color);
    box-shadow: var(--neu-shadow-convex-small);
}

.neu-toggle-switch.active .neu-toggle-thumb {
    left: 25px;
    background-color: #ffffff;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

/* Radio组 - 5个胶囊按钮 */
.neu-radio-group {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.neu-radio-btn {
    padding: 6px 14px;
    font-size: var(--neu-font-size-xs);
    font-weight: 600;
    border-radius: 20px;
    cursor: pointer;
    transition: all 0.25s ease;
    border: none;
    outline: none;
    background-color: var(--neu-base-color);
    color: var(--neu-text-secondary);
    box-shadow: var(--neu-shadow-concave);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.neu-radio-btn:hover {
    box-shadow: var(--neu-shadow-convex-medium);
    color: var(--neu-text-primary);
}

.neu-radio-btn.active {
    background: var(--neu-gradient-primary);
    color: #ffffff;
    box-shadow: var(--neu-shadow-convex-small);
    font-weight: 700;
}

/* 底部状态栏 */
.neu-panel-footer {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid rgba(163, 177, 198, 0.25);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 9px;
    color: var(--neu-text-muted);
    font-family: var(--neu-font-mono);
}

.neu-footer-left {
    display: flex;
    align-items: center;
    gap: 6px;
}

.neu-status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: #38a169;
    animation: neu-pulse-status 2s ease-in-out infinite;
}

@keyframes neu-pulse-status {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

/* ============================================
   6. 响应式设计
   ============================================ */
@media (max-width: 900px) {
    :root {
        --neu-dock-width: 95vw;
        --neu-panel-width: 320px;
    }

    #neu-dock {
        flex-wrap: wrap;
        height: auto;
        min-height: var(--neu-dock-height);
        padding: var(--neu-space-md);
        gap: var(--neu-space-sm);
    }

    .neu-metric-chip {
        min-width: calc(33% - 8px);
        max-width: calc(33% - 8px);
    }

    #neu-panel {
        right: 10px;
        width: calc(100vw - 20px);
        max-width: 360px;
    }
}

@media (max-width: 600px) {
    .neu-metrics-grid {
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
    }

    .neu-metric-card {
        padding: 10px 6px;
    }

    .neu-metric-value {
        font-size: 18px;
    }

    #neu-panel {
        width: calc(100vw - 32px);
        padding: 16px;
    }
}

/* ============================================
   7. 无障碍增强
   ============================================ */
.neu-toggle-switch:focus-visible,
.neu-radio-btn:focus-visible,
.neu-action-btn:focus-visible,
.neu-settings-btn:focus-visible,
.neu-section-header:focus-visible {
    outline: 2px solid rgba(79, 172, 254, 0.6);
    outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
    
}


    /* === ind的全部CSS（从v9-ind-fragment.html的style标签复制）=== */

    /* ============================================
       航空级钛合金设计系统 (Ind)
       Aviation-Grade Titanium Alloy Instrument Panel
       ============================================ */

    :root {
      /* 钛合金色系 */
      --ind-titanium-base: #8a9298;
      --ind-titanium-light: #b8c0c6;
      --ind-titanium-dark: #5a6268;
      --ind-titanium-deep: #3a4248;
      --ind-titanium-shine: #d0d8de;

      /* CNC加工特征 */
      --ind-bevel-thickness: 4px;
      --ind-screw-size: 12px;
      --ind-recess-depth: 3px;

      /* 指示灯颜色 */
      --ind-amber: #ffaa00;
      --ind-cyan: #00ddff;
      --ind-red: #ff3344;
      --ind-green: #00ff66;

      /* 功能色 */
      --ind-text-primary: #e8eef2;
      --ind-text-secondary: #9aa4ac;
      --ind-glow-amber: rgba(255, 170, 0, 0.6);
      --ind-glow-cyan: rgba(0, 221, 255, 0.5);
    }

    body.ind-active {
      background: linear-gradient(135deg, #1a1f24 0%, #0d1117 50%, #151a20 100%);
      font-family: 'Courier New', monospace;
      overflow-x: hidden;
      position: relative;
    }

    /* 背景网格 - 模拟航空器仪表盘背景 */
    body.ind-active::before {
      content: '';
      position: fixed;
      inset: 0;
      background-image:
        radial-gradient(circle at 1px 1px, rgba(138, 146, 152, 0.03) 1px, transparent 0);
      background-size: 20px 20px;
      pointer-events: none;
      z-index: 0;
    }

    /* ============================================
       DOCK - 主监测条（顶部居中横排）
       ============================================ */

    #ind-dock {
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 99999;
      display: flex;
      align-items: center;
      gap: 0;
      flex-wrap: nowrap;
      overflow: visible;

      /* 钛合金基板 */
      background: linear-gradient(
        180deg,
        var(--ind-titanium-shine) 0%,
        var(--ind-titanium-base) 15%,
        var(--ind-titanium-dark) 85%,
        var(--ind-titanium-deep) 100%
      );

      /* 拉丝纹理 */
      background-image:
        repeating-linear-gradient(
          90deg,
          transparent,
          transparent 1px,
          rgba(255, 255, 255, 0.02) 1px,
          rgba(255, 255, 255, 0.02) 2px
        ),
        linear-gradient(
          180deg,
          var(--ind-titanium-shine) 0%,
          var(--ind-titanium-base) 15%,
          var(--ind-titanium-dark) 85%,
          var(--ind-titanium-deep) 100%
        );

      border-radius: 8px;
      padding: 12px 16px;

      /* 真实厚度感 - 7层硬阴影技术 */
      box-shadow:
        /* 上边缘高光 */
        inset 0 1px 0 rgba(255, 255, 255, 0.4),
        inset 0 -1px 0 rgba(0, 0, 0, 0.3),
        /* 主投影 */
        0 4px 0 var(--ind-titanium-deep),
        0 6px 0 #2a3238,
        0 8px 0 #1a2228,
        0 10px 12px rgba(0, 0, 0, 0.6),
        0 14px 20px rgba(0, 0, 0, 0.4);

      /* CNC铣削边框 */
      border: 1px solid var(--ind-titanium-dark);
      border-top-color: var(--ind-titanium-light);
      border-bottom-color: var(--ind-titanium-deep);
    }

    /* Dock厚度截面（侧边） */
    #ind-dock::before {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      bottom: -10px;
      height: 10px;
      background: linear-gradient(
        180deg,
        var(--ind-titanium-deep) 0%,
        #2a3238 40%,
        #1a2228 100%
      );
      border-radius: 0 0 6px 6px;
      pointer-events: none;
      z-index: -1;
    }

    /* ============================================
       螺丝固定系统
       ============================================ */

    .ind-screw {
      position: absolute;
      width: var(--ind-screw-size);
      height: var(--ind-screw-size);
      background: radial-gradient(
        circle at 30% 30%,
        var(--ind-titanium-light) 0%,
        var(--ind-titanium-base) 50%,
        var(--ind-titanium-dark) 100%
      );
      border-radius: 50%;
      border: 1px solid var(--ind-titanium-deep);
      box-shadow:
        inset 0 1px 2px rgba(255, 255, 255, 0.3),
        0 1px 2px rgba(0, 0, 0, 0.4);
    }

    /* 十字槽 */
    .ind-screw::after {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      width: 7px;
      height: 7px;
      transform: translate(-50%, -50%);
      background:
        linear-gradient(45deg, transparent 45%, var(--ind-titanium-deep) 45%, var(--ind-titanium-deep) 55%, transparent 55%),
        linear-gradient(-45deg, transparent 45%, var(--ind-titanium-deep) 45%, var(--ind-titanium-deep) 55%, transparent 55%);
    }

    /* Dock螺丝位置 */
    #ind-dock .ind-screw.tl { top: 6px; left: 6px; }
    #ind-dock .ind-screw.tr { top: 6px; right: 6px; }
    #ind-dock .ind-screw.bl { bottom: 6px; left: 6px; }
    #ind-dock .ind-screw.br { bottom: 6px; right: 6px; }

    /* ============================================
       拖拽手柄
       ============================================ */

    .ind-drag-handle {
      width: 28px;
      height: 48px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      gap: 3px;
      margin-right: 12px;
      cursor: grab;
      position: relative;
    }

    .ind-drag-handle:active {
      cursor: grabbing;
    }

    /* 防滑纹理线条 */
    .ind-drag-line {
      width: 18px;
      height: 2px;
      background: linear-gradient(
        90deg,
        transparent 0%,
        var(--ind-titanium-dark) 20%,
        var(--ind-titanium-base) 50%,
        var(--ind-titanium-dark) 80%,
        transparent 100%
      );
      border-radius: 1px;
      box-shadow: inset 0 1px 0 rgba(0, 0, 0, 0.3);
    }

    /* ============================================
       监测指标单元（VU表风格）
       ============================================ */

    .ind-metric {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      padding: 0 10px;
      position: relative;
    }

    /* 分隔线 */
    .ind-metric:not(:last-child)::after {
      content: '';
      position: absolute;
      right: 0;
      top: 50%;
      transform: translateY(-50%);
      width: 1px;
      height: 70%;
      background: linear-gradient(
        180deg,
        transparent 0%,
        var(--ind-titanium-dark) 20%,
        var(--ind-titanium-base) 50%,
        var(--ind-titanium-dark) 80%,
        transparent 100%
      );
    }

    .ind-metric-label {
      font-size: 9px;
      font-weight: bold;
      color: var(--ind-text-secondary);
      text-transform: uppercase;
      letter-spacing: 1px;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    }

    .ind-metric-value {
      font-size: 13px;
      font-weight: bold;
      color: var(--ind-text-primary);
      text-shadow: 0 0 8px var(--ind-glow-cyan);
      min-width: 42px;
      text-align: center;
    }

    /* VU表进度条容器 */
    .ind-vu-meter {
      width: 60px;
      height: 8px;
      background: #1a1f24;
      border-radius: 2px;
      position: relative;
      overflow: hidden;
      box-shadow:
        inset 0 1px 3px rgba(0, 0, 0, 0.8),
        0 1px 0 rgba(255, 255, 255, 0.1);
      border: 1px solid var(--ind-titanium-deep);
    }

    /* VU表LED分段 */
    .ind-vu-segment {
      height: 100%;
      float: left;
      transition: all 0.15s ease;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
    }

    .ind-vu-segment.green {
      background: linear-gradient(180deg, var(--ind-accent-color, #00ff66) 0%, color-mix(in srgb, var(--ind-accent-color, #00ff66) 80%, #000) 100%);
      box-shadow: 0 0 4px color-mix(in srgb, var(--ind-accent-color, #00ff66) 40%, transparent);
    }

    .ind-vu-segment.amber {
      background: linear-gradient(180deg, #ffaa00 0%, #dd8800 100%);
      box-shadow: 0 0 4px rgba(255, 170, 0, 0.4);
    }

    .ind-vu-segment.red {
      background: linear-gradient(180deg, #ff3344 0%, #dd2233 100%);
      box-shadow: 0 0 4px rgba(255, 51, 68, 0.4);
      animation: ind-pulse-red 1s ease-in-out infinite;
    }

    @keyframes ind-pulse-red {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.7; }
    }

    /* ============================================
       温度显示（特殊样式）
       ============================================ */

    .ind-temp-display {
      display: flex;
      align-items: baseline;
      gap: 2px;
    }

    .ind-temp-value {
      font-size: 16px;
      font-weight: bold;
      color: var(--ind-amber);
      text-shadow: 0 0 10px var(--ind-glow-amber);
    }

    .ind-temp-unit {
      font-size: 11px;
      color: var(--ind-text-secondary);
    }

    /* 温度指示条 */
    .ind-temp-bar {
      width: 40px;
      height: 4px;
      background: linear-gradient(
        90deg,
        var(--ind-green) 0%,
        var(--ind-amber) 50%,
        var(--ind-red) 100%
      );
      border-radius: 2px;
      position: relative;
      box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.5);
    }

    .ind-temp-indicator {
      position: absolute;
      top: -2px;
      width: 2px;
      height: 8px;
      background: white;
      box-shadow: 0 0 6px white;
      transition: left 0.3s ease;
    }

    /* ============================================
       设置按钮（金属旋钮）
       ============================================ */

    .ind-settings-btn {
      width: 32px;
      height: 32px;
      margin-left: 12px;
      background: radial-gradient(
        circle at 35% 35%,
        var(--ind-titanium-light) 0%,
        var(--ind-titanium-base) 40%,
        var(--ind-titanium-dark) 100%
      );
      border-radius: 50%;
      border: 2px solid var(--ind-titanium-deep);
      cursor: pointer;
      position: relative;
      box-shadow:
        inset 0 2px 4px rgba(255, 255, 255, 0.3),
        inset 0 -2px 4px rgba(0, 0, 0, 0.3),
        0 2px 4px rgba(0, 0, 0, 0.4);
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .ind-settings-btn:hover {
      transform: scale(1.05);
      box-shadow:
        inset 0 2px 4px rgba(255, 255, 255, 0.3),
        inset 0 -2px 4px rgba(0, 0, 0, 0.3),
        0 2px 6px rgba(0, 0, 0, 0.5),
        0 0 12px color-mix(in srgb, var(--ind-accent-color, var(--ind-cyan)) 50%, transparent);
    }

    .ind-settings-btn:active {
      transform: scale(0.95);
    }

    /* 齿轮图标 */
    .ind-settings-btn::before {
      content: '\\2699';
      font-size: 16px;
      color: var(--ind-text-secondary);
      filter: drop-shadow(0 1px 1px rgba(0, 0, 0, 0.5));
    }

    /* ============================================
       PANEL - 控制面板（右侧纵向）
       ============================================ */

    #ind-panel {
      position: fixed;
      top: 80px;
      right: 20px;
      width: 320px;
      z-index: 99999;

      /* 钛合金基板 */
      background: linear-gradient(
        135deg,
        var(--ind-titanium-shine) 0%,
        var(--ind-titanium-base) 20%,
        var(--ind-titanium-dark) 80%,
        var(--ind-titanium-deep) 100%
      );

      /* 拉丝纹理 */
      background-image:
        repeating-linear-gradient(
          90deg,
          transparent,
          transparent 1px,
          rgba(255, 255, 255, 0.015) 1px,
          rgba(255, 255, 255, 0.015) 2px
        ),
        linear-gradient(
          135deg,
          var(--ind-titanium-shine) 0%,
          var(--ind-titanium-base) 20%,
          var(--ind-titanium-dark) 80%,
          var(--ind-titanium-deep) 100%
        );

      border-radius: 12px;
      padding: 20px;

      /* 真实厚度感 */
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.35),
        inset 0 -1px 0 rgba(0, 0, 0, 0.4),
        0 8px 0 var(--ind-titanium-deep),
        0 10px 0 #2a3238,
        0 12px 0 #1a2228,
        0 16px 24px rgba(0, 0, 0, 0.6),
        0 20px 32px rgba(0, 0, 0, 0.4);

      border: 1px solid var(--ind-titanium-dark);
      border-top-color: var(--ind-titanium-light);
      border-left-color: var(--ind-titanium-light);
      border-bottom-color: var(--ind-titanium-deep);
      border-right-color: var(--ind-titanium-deep);
    }

    /* Panel厚度截面 */
    #ind-panel::before {
      content: '';
      position: absolute;
      bottom: -16px;
      left: 4px;
      right: 4px;
      height: 16px;
      background: linear-gradient(
        180deg,
        var(--ind-titanium-deep) 0%,
        #2a3238 50%,
        #1a2228 100%
      );
      border-radius: 0 0 8px 8px;
      pointer-events: none;
      z-index: -1;
    }

    /* Panel螺丝位置 */
    #ind-panel .ind-screw.tl { top: 10px; left: 10px; }
    #ind-panel .ind-screw.tr { top: 10px; right: 10px; }
    #ind-panel .ind-screw.bl { bottom: 10px; left: 10px; }
    #ind-panel .ind-screw.br { bottom: 10px; right: 10px; }

    /* ============================================
       CNC下沉窗口（嵌入式显示区域）
       ============================================ */

    .ind-recess-window {
      background: linear-gradient(
        180deg,
        #0a0d10 0%,
        #12171c 50%,
        #0a0d10 100%
      );
      border-radius: 6px;
      padding: 14px;
      margin-bottom: 14px;
      position: relative;

      /* 下沉效果 */
      box-shadow:
        inset 0 2px 4px rgba(0, 0, 0, 0.8),
        inset 0 -1px 0 rgba(255, 255, 255, 0.05),
        0 1px 0 rgba(255, 255, 255, 0.1);

      border: 2px solid var(--ind-titanium-deep);
      border-top-color: #1a2228;
      border-bottom-color: #0a0d10;
    }

    /* 窗口标题栏 */
    .ind-window-title {
      font-size: 10px;
      font-weight: bold;
      color: var(--ind-accent-color, var(--ind-cyan));
      text-transform: uppercase;
      letter-spacing: 2px;
      margin-bottom: 10px;
      padding-bottom: 6px;
      border-bottom: 1px solid color-mix(in srgb, var(--ind-accent-color, var(--ind-cyan)) 20%, transparent);
      text-shadow: 0 0 8px color-mix(in srgb, var(--ind-accent-color, var(--ind-cyan)) 50%, transparent);
    }

    /* ============================================
       风格选择按钮组
       ============================================ */

    .ind-style-buttons {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 6px;
      margin-bottom: 8px;
    }

    .ind-style-btn {
      padding: 8px 4px;
      font-size: 9px;
      font-weight: bold;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--ind-text-secondary);
      background: linear-gradient(
        180deg,
        var(--ind-titanium-base) 0%,
        var(--ind-titanium-dark) 100%
      );
      border: 1px solid var(--ind-titanium-deep);
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s ease;
      text-align: center;
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.2),
        0 2px 3px rgba(0, 0, 0, 0.3);
    }

    .ind-style-btn:hover {
      background: linear-gradient(
        180deg,
        var(--ind-titanium-light) 0%,
        var(--ind-titanium-base) 100%
      );
      color: var(--ind-text-primary);
      transform: translateY(-1px);
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.3),
        0 3px 5px rgba(0, 0, 0, 0.4);
    }

    .ind-style-btn.active {
      background: linear-gradient(
        180deg,
        var(--ind-accent-color, var(--ind-cyan)) 0%,
        color-mix(in srgb, var(--ind-accent-color, var(--ind-cyan)) 60%, #000) 100%
      );
      color: #000;
      box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.4),
        0 0 12px color-mix(in srgb, var(--ind-accent-color, var(--ind-cyan)) 50%, transparent),
        0 2px 4px rgba(0, 0, 0, 0.3);
      text-shadow: none;
    }

    /* ============================================
       色彩主题选择
       ============================================ */

    .ind-theme-swatches {
      display: flex;
      gap: 8px;
      justify-content: center;
      margin-bottom: 8px;
    }

    .ind-swatch {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      cursor: pointer;
      position: relative;
      transition: all 0.25s ease;
      border: 3px solid var(--ind-titanium-dark);
      box-shadow:
        inset 0 2px 4px rgba(255, 255, 255, 0.2),
        0 2px 4px rgba(0, 0, 0, 0.4);
    }

    .ind-swatch:hover {
      transform: scale(1.15);
      box-shadow:
        inset 0 2px 4px rgba(255, 255, 255, 0.3),
        0 2px 8px rgba(0, 0, 0, 0.5),
        0 0 16px currentColor;
    }

    .ind-swatch.active {
      border-color: white;
      box-shadow:
        inset 0 2px 4px rgba(255, 255, 255, 0.3),
        0 0 20px currentColor,
        0 0 8px var(--ind-accent-color, currentColor),
        0 2px 6px rgba(0, 0, 0, 0.4);
      transform: scale(1.15);
    }

    .ind-swatch.active::after {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 8px;
      height: 8px;
      background: white;
      border-radius: 50%;
      box-shadow: 0 0 6px white;
    }

    /* 主题色定义 */
    .ind-swatch.cyan { background: linear-gradient(135deg, #00ddff, #0099bb); color: #00ddff; }
    .ind-swatch.amber { background: linear-gradient(135deg, #ffaa00, #dd8800); color: #ffaa00; }
    .ind-swatch.red { background: linear-gradient(135deg, #ff3344, #dd2233); color: #ff3344; }
    .ind-swatch.green { background: linear-gradient(135deg, #00ff66, #00cc52); color: #00ff66; }
    .ind-swatch.purple { background: linear-gradient(135deg, #aa66ff, #8844dd); color: #aa66ff; }

    /* ============================================
       详细进度条区域
       ============================================ */

    .ind-detail-meter {
      margin-bottom: 10px;
    }

    .ind-detail-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }

    .ind-detail-label {
      font-size: 10px;
      font-weight: bold;
      color: var(--ind-text-secondary);
      width: 50px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .ind-detail-bar-container {
      flex: 1;
      height: 12px;
      background: #0a0d10;
      border-radius: 3px;
      position: relative;
      overflow: hidden;
      box-shadow:
        inset 0 1px 3px rgba(0, 0, 0, 0.8),
        0 1px 0 rgba(255, 255, 255, 0.05);
      border: 1px solid var(--ind-titanium-deep);
    }

    .ind-detail-bar {
      height: 100%;
      border-radius: 2px;
      transition: width 0.4s ease;
      position: relative;
    }

    .ind-detail-bar.gpu {
      background: linear-gradient(90deg, var(--ind-accent-color, #00ddff), color-mix(in srgb, var(--ind-accent-color, #00ddff) 50%, transparent));
      box-shadow: 0 0 10px color-mix(in srgb, var(--ind-accent-color, #00ddff) 50%, transparent);
    }

    .ind-detail-bar.vram,
    .ind-detail-bar.cpu,
    .ind-detail-bar.ram,
    .ind-detail-bar.swap {
      background: linear-gradient(90deg, var(--ind-accent-color, #00ddff), color-mix(in srgb, var(--ind-accent-color, #00ddff) 50%, transparent));
      box-shadow: 0 0 10px color-mix(in srgb, var(--ind-accent-color, #00ddff) 50%, transparent);
    }

    /* 进度条刻度线 */
    .ind-detail-bar-container::before {
      content: '';
      position: absolute;
      inset: 0;
      background: repeating-linear-gradient(
        90deg,
        transparent 0px,
        transparent 19px,
        rgba(255, 255, 255, 0.05) 19px,
        rgba(255, 255, 255, 0.05) 20px
      );
      pointer-events: none;
    }

    .ind-detail-value {
      font-size: 10px;
      font-weight: bold;
      color: var(--ind-text-primary);
      width: 38px;
      text-align: right;
      text-shadow: 0 0 4px currentColor;
    }

    /* ============================================
       DISK IO / NETWORK IO
       ============================================ */

    .ind-io-section {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 10px;
    }

    .ind-io-box {
      background: rgba(0, 0, 0, 0.3);
      border-radius: 4px;
      padding: 10px;
      border: 1px solid var(--ind-titanium-deep);
    }

    .ind-io-title {
      font-size: 9px;
      font-weight: bold;
      color: var(--ind-amber);
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 6px;
      text-shadow: 0 0 6px var(--ind-glow-amber);
    }

    .ind-io-stats {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .ind-io-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 10px;
    }

    .ind-io-direction {
      color: var(--ind-text-secondary);
      font-weight: bold;
    }

    .ind-io-direction.up { color: var(--ind-green); }
    .ind-io-direction.down { color: var(--ind-cyan); }

    .ind-io-value {
      color: var(--text-primary);
      font-family: 'Courier New', monospace;
      font-weight: bold;
    }

    /* ============================================
       Toggle开关（工业金属风格）
       ============================================ */

    .ind-toggle-section {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 10px;
    }

    .ind-toggle-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .ind-toggle-label {
      font-size: 11px;
      font-weight: bold;
      color: var(--ind-text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .ind-toggle {
      width: 44px;
      height: 22px;
      background: linear-gradient(
        180deg,
        var(--ind-titanium-dark) 0%,
        var(--ind-titanium-deep) 100%
      );
      border-radius: 11px;
      position: relative;
      cursor: pointer;
      border: 2px solid var(--ind-titanium-deep);
      box-shadow:
        inset 0 2px 4px rgba(0, 0, 0, 0.6),
        0 1px 2px rgba(0, 0, 0, 0.3);
      transition: all 0.3s ease;
      z-index: 999;
      pointer-events: auto;
    }

    .ind-toggle-knob {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 14px;
      height: 14px;
      background: radial-gradient(
        circle at 35% 35%,
        var(--ind-titanium-light) 0%,
        var(--ind-titanium-base) 50%,
        var(--ind-titanium-dark) 100%
      );
      border-radius: 50%;
      transition: all 0.3s cubic-bezier(0.5, -0.2, 0.3, 1.2);
      box-shadow:
        inset 0 1px 2px rgba(255, 255, 255, 0.3),
        0 1px 2px rgba(0, 0, 0, 0.4);
    }

    .ind-toggle.active {
      background: linear-gradient(
        180deg,
        var(--ind-accent-color, var(--ind-cyan)) 0%,
        color-mix(in srgb, var(--ind-accent-color, #00ddff) 70%, #000) 100%
      );
      border-color: var(--ind-accent-color, #00ddff);
      box-shadow:
        inset 0 2px 4px rgba(0, 0, 0, 0.25),
        0 0 16px color-mix(in srgb, var(--ind-accent-color, #00ddff) 50%, transparent),
        0 0 4px var(--ind-accent-color, #00ddff);
    }

    .ind-toggle.active .ind-toggle-knob {
      left: 24px;
      background: radial-gradient(
        circle at 35% 35%,
        #ffffff 0%,
        #eeeeee 50%,
        #cccccc 100%
      );
      box-shadow:
        0 0 12px color-mix(in srgb, var(--ind-accent-color, #00ddff) 60%, transparent),
        0 0 4px #fff,
        0 1px 2px rgba(0, 0, 0, 0.3);
    }

    /* ============================================
       版本信息 & AMD SMI
       ============================================ */

    .ind-info-section {
      background: rgba(0, 0, 0, 0.2);
      border-radius: 4px;
      padding: 10px;
      border: 1px solid var(--ind-titanium-deep);
      margin-bottom: 10px;
    }

    .ind-version {
      font-size: 9px;
      color: var(--ind-text-secondary);
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .ind-version-badge {
      background: linear-gradient(180deg, var(--ind-cyan), #007799);
      color: #000;
      padding: 2px 8px;
      border-radius: 3px;
      font-weight: bold;
      font-size: 8px;
      letter-spacing: 1px;
      box-shadow: 0 0 8px var(--ind-glow-cyan);
    }

    .ind-amd-smi {
      font-size: 9px;
      color: var(--ind-amber);
      font-family: 'Courier New', monospace;
      line-height: 1.5;
      padding: 8px;
      background: rgba(0, 0, 0, 0.4);
      border-radius: 3px;
      border-left: 3px solid var(--ind-amber);
      box-shadow: inset 0 0 10px rgba(255, 170, 0, 0.1);
    }

    /* ============================================
       LED状态指示灯
       ============================================ */

    .ind-led {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 4px;
      animation: ind-led-blink 2s ease-in-out infinite;
    }

    .ind-led.green {
      background: var(--ind-accent-color, var(--ind-green));
      box-shadow: 0 0 6px var(--ind-accent-color, var(--ind-green));
    }

    .ind-led.amber {
      background: var(--ind-amber);
      box-shadow: 0 0 6px var(--ind-amber);
    }

    .ind-led.red {
      background: var(--ind-red);
      box-shadow: 0 0 6px var(--ind-red);
      animation: ind-led-blink-fast 0.5s ease-in-out infinite;
    }

    @keyframes ind-led-blink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }

    @keyframes ind-led-blink-fast {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.3; }
    }

    /* ============================================
       响应式调整
       ============================================ */

    @media (max-width: 1400px) {
      #ind-dock {
        transform: translateX(-50%) scale(0.9);
      }

      #ind-panel {
        transform: scale(0.9);
        transform-origin: top right;
      }
    }

    @media (max-width: 1200px) {
      #ind-dock {
        transform: translateX(-50%) scale(0.85);
        padding: 10px 12px;
      }

      #ind-panel {
        width: 280px;
        transform: scale(0.85);
        transform-origin: top right;
      }
    }


    /* === retro的全部CSS（从v9-retro-fragment.html的style标签复制，但删除retro-boot-sequence相关）=== */

    /* ============================================
       RETRO TERMINAL MONITOR SYSTEM (Retro)
       CRT + VFD + LED Hybrid Display Technology
       ============================================ */

    @import url('https://fonts.googleapis.com/css2?family=VT323&family=IBM+Plex+Mono:wght@400;700&display=swap');

    :root {
      /* Phosphor Color Themes (5 Types) */
      --phosphor-green-primary: #00FF41;
      --phosphor-green-glow: rgba(0, 255, 65, 0.6);
      --phosphor-green-dim: #00CC33;

      --phosphor-purple-primary: #BF5FFF;
      --phosphor-purple-glow: rgba(191, 95, 255, 0.6);
      --phosphor-purple-dim: #9940CC;

      --phosphor-amber-primary: #FFB000;
      --phosphor-amber-glow: rgba(255, 176, 0, 0.6);
      --phosphor-amber-dim: #CC8D00;

      --phosphor-cyan-primary: #00FFFF;
      --phosphor-cyan-glow: rgba(0, 255, 255, 0.6);
      --phosphor-cyan-dim: #00CCCC;

      --phosphor-pink-primary: #FF6EC7;
      --phosphor-pink-glow: rgba(255, 110, 199, 0.6);
      --phosphor-pink-dim: #CC589F;

      /* Active Theme (Default: Green) */
      --retro-primary: var(--phosphor-green-primary);
      --retro-glow: var(--phosphor-green-glow);
      --retro-dim: var(--phosphor-green-dim);

      /* Phosphor Switch Variables (for switchColor dynamic override) */
      --retro-phosphor-primary: #00FF41;
      --retro-phosphor-glow: rgba(0,255,65,0.4);
      --retro-phosphor-text: #00FF41;
      --retro-phosphor-dim: #00CC33;

      /* Physical Chassis Colors */
      --chassis-dark: #1a1c23;
      --chassis-mid: #252830;
      --chassis-light: #33364a;
      --chassis-border: #44485f;

      /* Screen Well (Deep Background) */
      --screen-deep: #08090c;
      --screen-mid: #0d0f14;
      --screen-surface: #12141a;

      /* Typography */
      --mono-display: 'VT323', monospace;
      --mono-body: 'IBM Plex Mono', monospace;

      /* Spacing & Sizing */
      --dock-height: 52px;
      --panel-width: 320px;
      --border-radius-chassis: 12px;
      --border-radius-screen: 8px;
    }

    body.retro-active {
      background: #0a0b0e;
      font-family: var(--mono-body);
      color: var(--retro-phosphor-primary, var(--retro-primary));
      overflow-x: hidden;
      min-height: 100vh;
    }

    /* ============================================
       SHARED PHYSICAL CHASSIS COMPONENTS
       ============================================ */

    .retro-container {
      position: relative;
      background: linear-gradient(
        145deg,
        var(--chassis-mid) 0%,
        var(--chassis-dark) 50%,
        #15171e 100%
      );
      border-radius: var(--border-radius-chassis);
      border: 2px solid var(--chassis-border);
      box-shadow:
        /* Outer shadow - heavy depth */
        0 8px 24px rgba(0, 0, 0, 0.7),
        0 2px 6px rgba(0, 0, 0, 0.5),
        /* Inner bevel - chassis thickness */
        inset 0 1px 0 rgba(255, 255, 255, 0.05),
        inset 0 -1px 0 rgba(0, 0, 0, 0.3),
        /* 极弱的磷光边缘描边，避免左侧溢出片状光 */
        0 0 0 1px color-mix(in srgb, var(--retro-phosphor-glow, var(--retro-glow)) 12%, transparent),
        inset 0 0 20px color-mix(in srgb, var(--retro-phosphor-glow, var(--retro-glow)) 3%, transparent);
      padding: 10px;
      z-index: 1000;
    }

    /* Screw Decorations (Physical Authenticity) */
    .retro-screw {
      position: absolute;
      width: 12px;
      height: 12px;
      background: radial-gradient(
        circle at 40% 40%,
        #666 0%,
        #333 60%,
        #111 100%
      );
      border-radius: 50%;
      border: 1px solid #222;
      box-shadow:
        inset 0 1px 2px rgba(255, 255, 255, 0.15),
        0 1px 2px rgba(0, 0, 0, 0.5);
      z-index: 10;
    }

    .retro-screw::after {
      content: '';
      position: absolute;
      top: 50%;
      left: 50%;
      width: 8px;
      height: 1.5px;
      background: #111;
      transform: translate(-50%, -50%) rotate(45deg);
      box-shadow: 0 0 0 0.5px rgba(255, 255, 255, 0.05);
    }

    .screw-tl { top: 6px; left: 6px; }
    .screw-tr { top: 6px; right: 6px; transform: rotate(90deg); }
    .screw-bl { bottom: 6px; left: 6px; transform: rotate(-90deg); }
    .screw-br { bottom: 6px; right: 6px; transform: rotate(180deg); }

    /* Screen Well (Embedded Deep Display) */
    .retro-screen-well {
      position: relative;
      background: radial-gradient(
        ellipse at center,
        var(--screen-surface) 0%,
        var(--screen-mid) 70%,
        var(--screen-deep) 100%
      );
      border-radius: var(--border-radius-screen);
      border: 3px solid #0a0b0d;
      box-shadow:
        /* Deep well shadow */
        inset 0 4px 12px rgba(0, 0, 0, 0.9),
        inset 0 0 20px rgba(0, 0, 0, 0.95),
        /* Edge highlight */
        0 0 1px rgba(255, 255, 255, 0.03);
      overflow: hidden;
    }

    /* Glass Reflection Layer */
    .retro-glass-reflection {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 50;
      background:
        /* Subtle glare from top-left */
        radial-gradient(
          ellipse at 25% 15%,
          rgba(255, 255, 255, 0.04) 0%,
          transparent 50%
        ),
        /* Vignette darkening at edges */
        radial-gradient(
          ellipse at center,
          transparent 50%,
          rgba(0, 0, 0, 0.4) 100%
        );
    }

    /* Scanline Overlay */
    /* 减弱条纹对比度，使其成为背景氛围 */
    .retro-scanlines {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 45;
      background: repeating-linear-gradient(
        to bottom,
        transparent 0px,
        transparent 3px,
        color-mix(in srgb, var(--retro-phosphor-primary, var(--retro-primary)) 6%, transparent) 3px,
        color-mix(in srgb, var(--retro-phosphor-primary, var(--retro-primary)) 6%, transparent) 4px
      );
      opacity: 0.35;
    }

    /* Sweeping Scan Beam Animation */
    .retro-scan-beam {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 8%;
      background: linear-gradient(
        to bottom,
        transparent,
        var(--retro-phosphor-glow, var(--retro-glow)),
        transparent
      );
      opacity: 0.06;
      animation: retroScanBeam 6s linear infinite;
      pointer-events: none;
      z-index: 46;
    }

    @keyframes retroScanBeam {
      0% { transform: translateY(-10%); }
      100% { transform: translateY(1200%); }
    }

    /* Phosphor Text Glow Effect */
    .retro-phosphor-text {
      font-family: var(--mono-display);
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow:
        0 0 4px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 8px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 16px rgba(0, 0, 0, 0.8);
      letter-spacing: 0.5px;
    }

    /* Flicker Animation for Living Feel */
    @keyframes retroFlicker {
      0%, 100% { opacity: 1; }
      92% { opacity: 1; }
      93% { opacity: 0.96; }
      94% { opacity: 1; }
      97% { opacity: 0.98; }
      98% { opacity: 0.94; }
      99% { opacity: 1; }
    }

    .retro-flicker {
      animation: retroFlicker 4s infinite;
    }

    /* NOTE: retroBootOn keyframes and .retro-boot-sequence class have been REMOVED
       to fix blank page issue (animation started from opacity: 0) */

    /* ============================================
       DOCK COMPONENT (Horizontal Status Bar)
       ============================================ */

    #retro-dock {
      position: fixed;
      top: 20px;
      left: 50%;
      transform: translateX(-50%);
      z-index: 99999;
      min-width: 900px;
      max-width: 1400px;
    }

    .retro-dock-inner {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      white-space: nowrap;
    }

    /* Drag Handle */
    .retro-drag-handle {
      display: flex;
      flex-direction: column;
      gap: 3px;
      padding: 6px 8px;
      cursor: grab;
      user-select: none;
      opacity: 0.6;
      transition: opacity 0.2s;
    }

    .retro-drag-handle:hover {
      opacity: 1;
    }

    .retro-drag-handle:active {
      cursor: grabbing;
    }

    .retro-drag-line {
      width: 20px;
      height: 2px;
      background: var(--retro-phosphor-dim, var(--retro-dim));
      box-shadow: 0 0 4px var(--retro-phosphor-glow, var(--retro-glow));
      margin: 2px 0;
      border-radius: 1px;
    }

    /* Metric Item in Dock */
    .retro-metric {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 8px;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid rgba(255, 255, 255, 0.04);
      border-radius: 4px;
      min-width: 120px;
    }

    .retro-metric-label {
      font-family: var(--mono-display);
      font-size: 16px;
      font-weight: bold;
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow:
        0 0 6px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 12px rgba(0, 0, 0, 0.9);
      min-width: 42px;
    }

    .retro-metric-value {
      font-family: var(--mono-display);
      font-size: 14px;
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow:
        0 0 4px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 10px rgba(0, 0, 0, 0.9);
      min-width: 38px;
      text-align: right;
    }

    /* LED Bar Progress Indicator */
    .retro-led-bar {
      display: flex;
      gap: 2px;
      align-items: flex-end;
      height: 18px;
      width: 48px;
    }

    .retro-led-segment {
      width: 4px;
      height: 100%;
      /* 使用当前磷光色的暗色版本作为未激活段背景，随颜色主题变化 */
      background: var(--retro-phosphor-dim, var(--retro-dim));
      border-radius: 1px;
      box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.5);
      transition: all 0.3s ease;
      opacity: 0.32;
    }

    .retro-led-segment.active {
      opacity: 1;
      background: var(--retro-phosphor-primary, var(--retro-primary));
      box-shadow:
        0 0 6px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 14px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 22px var(--retro-phosphor-glow, var(--retro-glow));
    }

    /* Temperature Display (follows selected phosphor) */
    .retro-temp-value {
      font-family: var(--mono-display);
      font-size: 15px;
      font-weight: bold;
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow:
        0 0 6px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 12px var(--retro-phosphor-glow, var(--retro-glow));
      padding: 2px 6px;
      border: 1px solid var(--retro-phosphor-dim, var(--retro-dim));
      border-radius: 3px;
      background: var(--retro-phosphor-glow, rgba(0, 255, 65, 0.08));
    }

    /* Settings Gear Icon */
    .retro-settings-btn {
      padding: 6px 10px;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 4px;
      cursor: pointer;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      font-size: 18px;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .retro-settings-btn:hover {
      color: var(--retro-phosphor-primary, var(--retro-primary));
      border-color: var(--retro-phosphor-dim, var(--retro-dim));
      box-shadow: 0 0 8px var(--retro-phosphor-glow, var(--retro-glow));
    }

    /* ============================================
       PANEL COMPONENT (Control Dashboard)
       ============================================ */

    #retro-panel {
      position: fixed;
      top: 80px;
      right: 20px;
      width: var(--panel-width);
      z-index: 99999;
    }

    .retro-panel-inner {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 12px;
      max-height: calc(100vh - 140px);
      overflow-y: auto;
      position: relative;
      z-index: 60; /* 必须高于所有装饰层(glass-reflection z:50, scanlines z:45) */
    }

    /* Panel Section Divider */
    .retro-section {
      border-bottom: 1px dashed rgba(255, 255, 255, 0.06);
      padding-bottom: 10px;
    }

    .reto-section:last-child {
      border-bottom: none;
    }

    /* Style Buttons Row */
    .retro-style-row {
      display: flex;
      gap: 6px;
      margin-bottom: 8px;
    }

    .retro-style-btn {
      flex: 1;
      padding: 8px 4px;
      font-family: var(--mono-display);
      font-size: 13px;
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 4px;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      cursor: pointer;
      transition: all 0.2s;
      text-align: center;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .retro-style-btn:hover {
      background: rgba(0, 0, 0, 0.6);
      color: var(--retro-phosphor-primary, var(--retro-primary));
      border-color: var(--retro-phosphor-dim, var(--retro-dim));
    }

    .retro-style-btn.active {
      background: var(--retro-phosphor-primary, var(--retro-primary));
      color: var(--screen-deep);
      font-weight: bold;
      box-shadow: 0 0 12px var(--retro-phosphor-glow, var(--retro-glow));
      text-shadow: none;
      border-color: var(--retro-phosphor-primary, var(--retro-primary));
    }

    /* Color Palette Blocks (Visual Impact!) */
    .retro-color-palette {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 6px;
      margin-bottom: 10px;
    }

    .retro-color-block {
      aspect-ratio: 1;
      border-radius: 4px;
      cursor: pointer;
      border: 2px solid transparent;
      transition: all 0.25s ease;
      position: relative;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
    }

    .reto-color-block:hover {
      transform: scale(1.1);
      z-index: 5;
    }

    .retro-color-block.active {
      border-color: #fff;
      transform: scale(1.08);
      box-shadow:
        0 0 16px currentColor,
        0 4px 16px rgba(0, 0, 0, 0.6);
    }

    .retro-color-block::after {
      content: '';
      position: absolute;
      inset: 0;
      background: linear-gradient(
        135deg,
        rgba(255, 255, 255, 0.2) 0%,
        transparent 50%
      );
      border-radius: 2px;
      pointer-events: none;
    }

    .color-green { background: linear-gradient(135deg, #00FF41, #00CC33); color: #00FF41; }
    .color-purple { background: linear-gradient(135deg, #BF5FFF, #9940CC); color: #BF5FFF; }
    .color-amber { background: linear-gradient(135deg, #FFB000, #CC8D00); color: #FFB000; }
    .color-cyan { background: linear-gradient(135deg, #00FFFF, #00CCCC); color: #00FFFF; }
    .color-pink { background: linear-gradient(135deg, #FF6EC7, #CC589F); color: #FF6EC7; }

    /* Detailed Progress Bars (VFD Segment Style) */
    .retro-progress-group {
      display: flex;
      flex-direction: column;
      gap: 8px;
      position: relative;
      z-index: 2;
    }

    /* 减弱 VFD 网格纹理，避免喧宾夺主；颜色仍随磷光主题同步 */
    .retro-panel-vfd-grid {
      position: relative;
      padding: 10px;
      border-radius: 4px;
      border: 1px solid color-mix(in srgb, var(--retro-phosphor-dim, var(--retro-dim)) 12%, transparent);
      background-image:
        linear-gradient(to right, color-mix(in srgb, var(--retro-phosphor-glow, var(--retro-glow)) 4%, transparent) 1px, transparent 1px),
        linear-gradient(to bottom, color-mix(in srgb, var(--retro-phosphor-glow, var(--retro-glow)) 4%, transparent) 1px, transparent 1px);
      background-size: 10px 10px;
      box-shadow: inset 0 0 10px color-mix(in srgb, var(--retro-phosphor-glow, var(--retro-glow)) 5%, transparent);
    }

    .reto-progress-item {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .reto-progress-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-family: var(--mono-display);
      font-size: 14px;
    }

    .reto-progress-label {
      color: var(--retro-phosphor-dim, var(--retro-dim));
      text-shadow: 0 0 4px var(--retro-phosphor-glow, var(--retro-glow));
    }

    .reto-progress-value {
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow: 0 0 6px var(--retro-phosphor-glow, var(--retro-glow));
      font-weight: bold;
    }

    /* VFD-style Progress Bar Track */
    .reto-vfd-track {
      position: relative;
      height: 14px;
      background: rgba(0, 0, 0, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 2px;
      overflow: hidden;
      box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.8);
    }

    .reto-vfd-fill {
      height: 100%;
      background: linear-gradient(
        90deg,
        var(--retro-phosphor-text) 0%,
        var(--retro-phosphor-primary) 100%
      );
      box-shadow:
        0 0 10px var(--retro-phosphor-glow),
        0 0 18px var(--retro-phosphor-glow),
        inset 0 1px 0 rgba(255, 255, 255, 0.2);
      transition: width 0.4s ease;
      position: relative;
    }

    /* Segmented fill effect */
    .reto-vfd-fill::before {
      content: '';
      position: absolute;
      inset: 0;
      background: repeating-linear-gradient(
        90deg,
        transparent 0px,
        transparent 3px,
        rgba(0, 0, 0, 0.15) 3px,
        rgba(0, 0, 0, 0.15) 4px
      );
    }

    /* IO Metrics Section */
    .retro-io-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }

    .retro-io-card {
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 4px;
      padding: 8px;
    }

    .retro-io-title {
      font-family: var(--mono-display);
      font-size: 11px;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 4px;
      opacity: 0.7;
    }

    .retro-io-values {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-family: var(--mono-display);
      font-size: 13px;
    }

    .retro-io-line {
      display: flex;
      justify-content: space-between;
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow: 0 0 4px var(--retro-phosphor-glow, var(--retro-glow));
    }

    /* Toggle Switches (Retro Rocker Style) */
    .retro-toggle-row {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .retro-toggle-item {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .retro-toggle-label {
      font-family: var(--mono-display);
      font-size: 12px;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .retro-rocker-switch {
      position: relative;
      width: 44px;
      height: 22px;
      background: rgba(0, 0, 0, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 11px;
      cursor: pointer;
      overflow: hidden;
      box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.6);
    }

    .retro-rocker-knob {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 16px;
      height: 16px;
      background: linear-gradient(135deg, #555, #222);
      border-radius: 50%;
      box-shadow:
        0 1px 3px rgba(0, 0, 0, 0.5),
        inset 0 1px 0 rgba(255, 255, 255, 0.1);
      transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .retro-rocker-switch.on .retro-rocker-knob {
      transform: translateX(22px);
      background: linear-gradient(135deg, var(--retro-phosphor-primary, var(--retro-primary)), var(--retro-phosphor-dim, var(--retro-dim)));
      box-shadow:
        0 0 8px var(--retro-phosphor-glow, var(--retro-glow)),
        0 1px 3px rgba(0, 0, 0, 0.5);
    }

    /* ON/OFF Labels inside switch */
    .retro-rocker-switch::before {
      content: 'OFF';
      position: absolute;
      left: 4px;
      top: 50%;
      transform: translateY(-50%);
      font-family: var(--mono-display);
      font-size: 8px;
      color: #555;
      z-index: 0;
    }

    .retro-rocker-switch.on::before {
      content: 'ON';
      left: auto;
      right: 4px;
      color: var(--retro-phosphor-primary, var(--retro-primary));
      text-shadow: 0 0 4px var(--retro-phosphor-glow, var(--retro-glow));
    }

    /* Retro Control Row & Toggle Switch (Panel Inline) */
    .retro-control-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 6px 8px;
      background: rgba(0, 0, 0, 0.25);
      border-radius: 3px;
      border: 1px solid rgba(255, 255, 255, 0.04);
      margin-bottom: 5px;
    }

    .retro-control-label {
      font-family: var(--mono-display);
      font-size: 11px;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .retro-toggle-switch {
      position: relative;
      width: 40px;
      height: 20px;
      background: rgba(0, 0, 0, 0.55);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      cursor: pointer;
      transition: all 0.25s ease;
      box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
      flex-shrink: 0;
      z-index: 999;
      pointer-events: auto;
    }

    .retro-toggle-switch.active {
      background: var(--retro-phosphor-glow, rgba(0, 255, 65, 0.25));
      border-color: var(--retro-phosphor-primary, var(--retro-primary));
      box-shadow:
        inset 0 1px 3px rgba(0, 0, 0, 0.25),
        0 0 14px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 3px var(--retro-phosphor-glow, var(--retro-glow));
    }

    .retro-toggle-thumb {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 14px;
      height: 14px;
      background: linear-gradient(135deg, #666, #333);
      border-radius: 50%;
      transition: transform 0.25s cubic-bezier(0.68, -0.55, 0.265, 1.55);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
    }

    .retro-toggle-switch.active .retro-toggle-thumb {
      transform: translateX(20px);
      background: linear-gradient(135deg, var(--retro-phosphor-primary, var(--retro-primary)), var(--retro-phosphor-dim, var(--retro-dim)));
      box-shadow:
        0 0 10px var(--retro-phosphor-glow, var(--retro-glow)),
        0 0 3px var(--retro-phosphor-primary, var(--retro-primary));
    }

    /* Version Info */
    .retro-version-info {
      font-family: var(--mono-display);
      font-size: 11px;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      text-align: center;
      padding: 6px;
      background: rgba(0, 0, 0, 0.25);
      border-radius: 3px;
      border: 1px dashed rgba(255, 255, 255, 0.04);
      opacity: 0.7;
      letter-spacing: 1px;
    }

    /* AMD SMI Link */
    .retro-amd-smi {
      font-family: var(--mono-display);
      font-size: 12px;
      color: var(--retro-phosphor-dim, var(--retro-dim));
      text-align: center;
      padding: 8px;
      background: rgba(0, 0, 0, 0.2);
      border: 1px solid rgba(255, 255, 255, 0.04);
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s;
      text-decoration: none;
      display: block;
    }

    .retro-amd-smi:hover {
      color: var(--retro-phosphor-primary, var(--retro-primary));
      border-color: var(--retro-phosphor-dim, var(--retro-dim));
      box-shadow: 0 0 8px var(--retro-phosphor-glow, var(--retro-glow));
    }

    /* Scrollbar Styling (for panel) */
    .retro-panel-inner::-webkit-scrollbar {
      width: 6px;
    }

    .retro-panel-inner::-webkit-scrollbar-track {
      background: rgba(0, 0, 0, 0.3);
      border-radius: 3px;
    }

    .retro-panel-inner::-webkit-scrollbar-thumb {
      background: var(--retro-phosphor-dim, var(--retro-dim));
      border-radius: 3px;
      box-shadow: 0 0 4px var(--retro-phosphor-glow, var(--retro-glow));
    }

    /* ============================================
       THEME-SPECIFIC OVERRIDES
       ============================================ */

    [data-theme="green"] {
      --retro-primary: var(--phosphor-green-primary);
      --retro-glow: var(--phosphor-green-glow);
      --retro-dim: var(--phosphor-green-dim);
    }

    [data-theme="purple"] {
      --retro-primary: var(--phosphor-purple-primary);
      --retro-glow: var(--phosphor-purple-glow);
      --retro-dim: var(--phosphor-purple-dim);
    }

    [data-theme="amber"] {
      --retro-primary: var(--phosphor-amber-primary);
      --retro-glow: var(--phosphor-amber-glow);
      --retro-dim: var(--phosphor-amber-dim);
    }

    [data-theme="cyan"] {
      --retro-primary: var(--phosphor-cyan-primary);
      --retro-glow: var(--phosphor-cyan-glow);
      --retro-dim: var(--phosphor-cyan-dim);
    }

    [data-theme="pink"] {
      --retro-primary: var(--phosphor-pink-primary);
      --retro-glow: var(--phosphor-pink-glow);
      --retro-dim: var(--phosphor-pink-dim);
    }

    /* ============================================
       ANIMATIONS & MICRO-INTERACTIONS
       ============================================ */

    @keyframes retroPulseGlow {
      0%, 100% { box-shadow: 0 0 8px var(--retro-phosphor-glow, var(--retro-glow)); }
      50% { box-shadow: 0 0 16px var(--retro-phosphor-glow, var(--retro-glow)), 0 0 24px var(--retro-phosphor-glow, var(--retro-glow)); }
    }

    .retro-pulse {
      animation: retroPulseGlow 2s ease-in-out infinite;
    }

    /* LED segment blink for active data */
    @keyframes retroLedBlink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }

    .retro-led-blink {
      animation: retroLedBlink 1s step-end infinite;
    }

    /* Data value update flash */
    @keyframes retroDataFlash {
      0% { color: #fff; text-shadow: 0 0 12px currentColor; }
      100% { color: var(--retro-phosphor-primary, var(--retro-primary)); text-shadow: 0 0 6px var(--retro-phosphor-glow, var(--retro-glow)); }
    }

    .retro-data-flash {
      animation: retroDataFlash 0.3s ease-out;
    }


    /* === lux的全部CSS（从v10-lux-fragment.html升级）=== */

/* ============================================
   FEIXUE MONITOR v10 - Lux v2 "Precision Instrument"
   世界级精密仪器设计系统
   物理隐喻：多层复合材质仪器面板
   类似高端医疗设备/实验室仪器/航空仪表盘
   ============================================ */

/* ============================================
   1. CSS变量系统 - 宝石色调色板 + 材质令牌
   ============================================ */
:root {
    /* --- 宝石金色调色板 --- */
    --lux-gold: #d4af37;
    --lux-gold-light: #f4e4bc;
    --lux-gold-mid: #c9a227;
    --lux-gold-dark: #a08020;
    --lux-gold-deep: #806010;

    /* --- 钛金属灰色系 --- */
    --lux-titanium: #3d424d;
    --lux-titanium-light: #5a6070;
    --lux-titanium-dark: #2a2d35;

    /* --- 光学玻璃材质 --- */
    --lux-glass-bg: rgba(255, 255, 255, 0.08);
    --lux-glass-border: rgba(255, 255, 255, 0.15);
    --lux-glass-highlight: rgba(255, 255, 255, 0.25);
    --lux-glass-shadow: rgba(0, 0, 0, 0.3);

    /* --- 宝石色彩系统（6个监测模块专用）--- */
    /* GPU → 青蓝玻璃 */
    --lux-sapphire: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
    --lux-sapphire-glow: rgba(0, 212, 255, 0.35);
    /* VRAM → 紫罗兰玻璃 */
    --lux-amethyst: linear-gradient(135deg, #a855f7 0%, #7c3aed 100%);
    --lux-amethyst-glow: rgba(168, 85, 247, 0.35);
    /* CPU → 翡翠玻璃 */
    --lux-emerald: linear-gradient(135deg, #34d399 0%, #059669 100%);
    --lux-emerald-glow: rgba(52, 211, 153, 0.35);
    /* RAM → 琥珀玻璃 */
    --lux-topaz: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
    --lux-topaz-glow: rgba(251, 191, 36, 0.35);
    /* SWAP → 玫瑰玻璃 */
    --lux-rose: linear-gradient(135deg, #fb7185 0%, #e11d48 100%);
    --lux-rose-glow: rgba(251, 113, 133, 0.35);
    /* TEMP → 红宝石玻璃 */
    --lux-ruby: linear-gradient(135deg, #f87171 0%, #dc2626 100%);
    --lux-ruby-glow: rgba(248, 113, 113, 0.35);

    /* --- 文字颜色 --- */
    --lux-text-primary: #e0e6ed;
    --lux-text-secondary: #8892a0;
    --lux-text-muted: #6b7280;
    --lux-text-gold: var(--lux-gold-light);

    /* --- 尺寸令牌 --- */
    --lux-dock-width: 920px; /* Phase 6 fix: 进一步加宽，确保手柄+6模块+温度+设置按钮完整显示 */
    --lux-dock-height: 70px;
    --lux-panel-width: 360px;
    --lux-panel-height: auto;
    --lux-radius-dock: 16px;
    --lux-radius-panel: 18px;
    --lux-radius-card: 12px;
    --lux-radius-button: 8px;

    /* --- 字体系统 --- */
    --lux-font-ui: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --lux-font-mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;

    /* --- 间距系统 --- */
    --lux-space-xs: 4px;
    --lux-space-sm: 8px;
    --lux-space-md: 12px;
    --lux-space-lg: 16px;
    --lux-space-xl: 20px;

    /* --- 过渡动画 --- */
    --lux-transition-fast: 0.2s ease;
    --lux-transition-normal: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    --lux-transition-slow: 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* ============================================
   2. 全局基础样式
   ============================================ */


body {
    font-family: var(--lux-font-ui);
    background: linear-gradient(135deg, #1a1d24 0%, #0d1117 50%, #161b22 100%);
    color: var(--lux-text-primary);
    min-height: 100vh;
    line-height: 1.5;
    overflow-x: hidden;
}

/* 背景环境光效果 */
body::before {
    content: '';
    position: fixed;
    top: -200px;
    left: 50%;
    transform: translateX(-50%);
    width: 800px;
    height: 500px;
    background: radial-gradient(ellipse, color-mix(in srgb, var(--lux-gold) 6%, transparent) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}

/* ============================================
   3. DOCK 组件 - 精密仪器监测条
   Layer 1-5 复合材质结构
   尺寸：740x70px，fixed定位居中
   ============================================ */
#lux-dock {
    position: fixed;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    width: var(--lux-dock-width);
    max-width: calc(100vw - 16px); /* Phase 6 fix: 限制最大宽度，防止在小视口溢出 */
    height: var(--lux-dock-height);
    z-index: 99999;
    display: flex;
    align-items: center;
    flex-wrap: nowrap; /* Phase 6 fix: 禁止换行，避免只显示 3 个模块 */
    gap: 0;
    padding: 8px 14px;
    border-radius: var(--lux-radius-dock);

    /* Layer 1: 拉丝钛金属底座 */
    background:
        /* 拉丝纹理 */
        repeating-linear-gradient(
            90deg,
            transparent,
            transparent 2px,
            rgba(255, 255, 255, 0.02) 2px,
            rgba(255, 255, 255, 0.02) 4px
        ),
        /* 主体渐变 */
        linear-gradient(135deg, #2c2f36 0%, #3d424d 50%, #2a2d35 100%);

    /* 多层阴影：厚度感 + 金色描边 */
    box-shadow:
        /* 底部深色投影（厚度感）*/
        0 20px 40px rgba(0, 0, 0, 0.5),
        0 8px 16px rgba(0, 0, 0, 0.3),
        /* 金色细线描边 */
        0 0 0 1px color-mix(in srgb, var(--lux-gold) 30%, transparent),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);

    /* 平滑过渡 */
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);

    user-select: none;
    position: relative;
    overflow: visible;
}

/* Layer 5: 光学镀膜反光（极微妙）*/
#lux-dock::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: conic-gradient(
        from 225deg at 45% 45%,
        rgba(255, 250, 240, 0.04) 0deg,
        transparent 60deg,
        rgba(255, 245, 220, 0.03) 120deg,
        transparent 180deg,
        rgba(255, 255, 255, 0.02) 240deg,
        transparent 300deg,
        rgba(255, 250, 240, 0.04) 360deg
    );
    pointer-events: none;
    mix-blend-mode: overlay;
    opacity: 0.8;
}

#lux-dock:hover {
    box-shadow:
        0 25px 50px rgba(0, 0, 0, 0.55),
        0 10px 20px rgba(0, 0, 0, 0.35),
        0 0 0 1.5px color-mix(in srgb, var(--lux-gold) 40%, transparent),
        inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

/* 拖拽手柄 - 顶部横条纹风格 */
.lux-dock-handle {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    width: 20px;
    height: 44px;
    cursor: grab;
    flex-shrink: 0;
    margin-right: 8px;
}

.lux-dock-handle:active {
    cursor: grabbing;
}

.lux-handle-line {
    width: 16px;
    height: 2px;
    background: color-mix(in srgb, var(--lux-gold) 40%, transparent);
    border-radius: 1px;
}

/* Layer 2: CNC雕刻凹槽（容纳6个监测模块）*/
.lux-module-slot {
    position: relative;
    flex: 1 0 118px; /* Phase 6 fix: 允许增长但禁止收缩，保证 6 个模块不被挤压 */
    height: 52px;
    margin: 0 3px;
    padding: 4px;
    border-radius: 10px;

    /* CNC凹槽深阴影 */
    box-shadow:
        inset 3px 3px 8px rgba(0, 0, 0, 0.6),
        inset -1px -1px 4px rgba(255, 255, 255, 0.03);

    /* 凹槽底色 */
    background: rgba(0, 0, 0, 0.3);

    /* CNC铣削斜面边框 */
    border: 1px solid color-mix(in srgb, var(--lux-gold) 15%, transparent);

    transition: all 0.3s ease;
}

.lux-module-slot:hover {
    border-color: color-mix(in srgb, var(--lux-gold) 30%, transparent);
    box-shadow:
        inset 3px 3px 8px rgba(0, 0, 0, 0.55),
        inset -1px -1px 4px rgba(255, 255, 255, 0.04),
        0 0 12px color-mix(in srgb, var(--lux-gold) 10%, transparent);
}

/* Layer 3: 光学玻璃监测模块 × 6 */
.lux-glass-module {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 10px;
    border-radius: 8px;

    /* 半透明毛玻璃材质 */
    backdrop-filter: blur(12px) saturate(150%);
    -webkit-backdrop-filter: blur(12px) saturate(150%);

    /* 玻璃背景 */
    background: var(--glass-color, var(--lux-glass-bg));

    /* 极细高光线（top/left白色，bottom/right深色）*/
    border:
        1px solid rgba(255, 255, 255, 0.18),
        1px solid transparent;

    /* 内部微弱发光 */
    box-shadow:
        0 2px 8px var(--glass-glow, var(--lux-glass-shadow)),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);

    transition: all 0.3s ease;
    cursor: default;
    position: relative;
    overflow: hidden;
}

/* Hover: 玻璃亮度提升 + 轻微上浮 */
.lux-glass-module:hover {
    background: rgba(255, 255, 255, 0.12);
    transform: translateY(-2px);
    box-shadow:
        0 6px 16px var(--glass-glow, var(--lux-glass-shadow)),
        inset 0 1px 0 rgba(255, 255, 255, 0.18),
        0 0 20px var(--module-glow, rgba(212, 175, 55, 0.15));
}

/* 各模块色彩不同 */
.lux-module-slot[data-type="gpu"] .lux-glass-module { --glass-color: rgba(0, 212, 255, 0.08); --glass-glow: rgba(0, 212, 255, 0.25); --module-glow: rgba(0, 212, 255, 0.2); }
.lux-module-slot[data-type="vram"] .lux-glass-module { --glass-color: rgba(168, 85, 247, 0.08); --glass-glow: rgba(168, 85, 247, 0.25); --module-glow: rgba(168, 85, 247, 0.2); }
.lux-module-slot[data-type="cpu"] .lux-glass-module { --glass-color: rgba(52, 211, 153, 0.08); --glass-glow: rgba(52, 211, 153, 0.25); --module-glow: rgba(52, 211, 153, 0.2); }
.lux-module-slot[data-type="ram"] .lux-glass-module { --glass-color: rgba(251, 191, 36, 0.08); --glass-glow: rgba(251, 191, 36, 0.25); --module-glow: rgba(251, 191, 36, 0.2); }
.lux-module-slot[data-type="swap"] .lux-glass-module { --glass-color: rgba(251, 113, 133, 0.08); --glass-glow: rgba(251, 113, 133, 0.25); --module-glow: rgba(251, 113, 133, 0.2); }
.lux-module-slot[data-type="temp"] .lux-glass-module { --glass-color: rgba(248, 113, 113, 0.08); --glass-glow: rgba(248, 113, 113, 0.25); --module-glow: rgba(248, 113, 113, 0.2); }

/* 模块图标 - 发光效果 */
.lux-module-icon {
    font-size: 16px;
    line-height: 1;
    filter: drop-shadow(0 0 6px currentColor);
    opacity: 0.9;
}

.lux-module-slot[data-type="gpu"] .lux-module-icon { color: #00d4ff; }
.lux-module-slot[data-type="vram"] .lux-module-icon { color: #a855f7; }
.lux-module-slot[data-type="cpu"] .lux-module-icon { color: #34d399; }
.lux-module-slot[data-type="ram"] .lux-module-icon { color: #fbbf24; }
.lux-module-slot[data-type="swap"] .lux-module-icon { color: #fb7185; }
.lux-module-slot[data-type="temp"] .lux-module-icon { color: #f87171; }

/* 模块标签 */
.lux-module-label {
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--lux-text-secondary);
    white-space: nowrap;
}

/* 模块数值 - 大号等宽字体，白色清晰可读 */
.lux-module-value {
    font-size: 15px;
    font-weight: 700;
    font-family: var(--lux-font-mono);
    color: #ffffff;
    text-shadow: 0 0 8px rgba(255, 255, 255, 0.3);
    min-width: 38px;
    text-align: right;
    font-variant-numeric: tabular-nums;
}

/* 迷你进度条 - 玻璃内部填充（渐变色，带微光）*/
.lux-mini-progress {
    width: 46px;
    height: 5px;
    border-radius: 3px;
    background: rgba(0, 0, 0, 0.4);
    overflow: hidden;
    position: relative;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.4);
}

.lux-mini-progress-fill {
    height: 100%;
    border-radius: 3px;
    background: var(--progress-gradient, var(--lux-sapphire));
    transition: width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
    position: relative;
    box-shadow: 0 0 6px var(--progress-glow, var(--lux-sapphire-glow));
}

/* 微光流动动画 */
.lux-mini-progress-fill::after {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 60%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.4), transparent);
    animation: lux-shimmer-flow 2.5s ease-in-out infinite;
    border-radius: inherit;
}

@keyframes lux-shimmer-flow {
    0% { left: -60%; }
    100% { left: 160%; }
}

/* 各模块进度条渐变 */
.lux-module-slot[data-type="gpu"] .lux-mini-progress-fill { --progress-gradient: var(--lux-sapphire); --progress-glow: var(--lux-sapphire-glow); }
.lux-module-slot[data-type="vram"] .lux-mini-progress-fill { --progress-gradient: var(--lux-amethyst); --progress-glow: var(--lux-amethyst-glow); }
.lux-module-slot[data-type="cpu"] .lux-mini-progress-fill { --progress-gradient: var(--lux-emerald); --progress-glow: var(--lux-emerald-glow); }
.lux-module-slot[data-type="ram"] .lux-mini-progress-fill { --progress-gradient: var(--lux-topaz); --progress-glow: var(--lux-topaz-glow); }
.lux-module-slot[data-type="swap"] .lux-mini-progress-fill { --progress-gradient: var(--lux-rose); --progress-glow: var(--lux-rose-glow); }
.lux-module-slot[data-type="temp"] .lux-mini-progress-fill { --progress-gradient: var(--lux-ruby); --progress-glow: var(--lux-ruby-glow); }

/* 设置按钮 - 金属质感按钮（Flex 项目，独占 dock 右侧空间，避免覆盖 temp 模块） */
.lux-settings-btn {
    position: relative;
    z-index: 20;
    width: 32px;
    height: 32px;
    margin-left: 8px;
    border-radius: var(--lux-radius-button);
    flex-shrink: 0;
    background: linear-gradient(145deg, var(--lux-gold-light), var(--lux-gold-mid));
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.3s ease;
    border: none;
    outline: none;
    box-shadow:
        0 3px 8px rgba(0, 0, 0, 0.4),
        inset 0 1px 0 rgba(255, 255, 255, 0.5);
    font-size: 15px;
    color: var(--lux-titanium-dark);
}

.lux-settings-btn:hover {
    transform: rotate(60deg) scale(1.08);
    box-shadow:
        0 5px 14px rgba(0, 0, 0, 0.5),
        inset 0 1px 0 rgba(255, 255, 255, 0.6),
        0 0 16px color-mix(in srgb, var(--lux-gold) 30%, transparent);
}

.lux-settings-btn:active {
    transform: rotate(60deg) scale(0.95);
}

/* ============================================
   4. PANEL 组件 - 仪器面板
   与Dock一致的仪器面板风格
   尺寸：360x520px（自适应高度）
   ============================================ */
#lux-panel {
    position: fixed;
    top: 85px;
    right: 20px;
    width: var(--lux-panel-width);
    max-height: calc(100vh - 105px);
    overflow-y: auto;
    z-index: 99999;
    padding: var(--lux-space-lg);

    /* 与Dock一致的拉丝金属底座 */
    background:
        repeating-linear-gradient(
            90deg,
            transparent,
            transparent 2px,
            rgba(255, 255, 255, 0.02) 2px,
            rgba(255, 255, 255, 0.02) 4px
        ),
        linear-gradient(165deg, #2c2f36 0%, #3d424d 50%, #2a2d35 100%);

    border-radius: var(--lux-radius-panel);

    /* 多层阴影 + 金色描边 */
    box-shadow:
        0 25px 60px rgba(0, 0, 0, 0.6),
        0 10px 24px rgba(0, 0, 0, 0.4),
        0 0 0 1px color-mix(in srgb, var(--lux-gold) 25%, transparent),
        inset 0 1px 0 rgba(255, 255, 255, 0.08);

    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);

    /* 自定义滚动条 */
    scrollbar-width: thin;
    scrollbar-color: var(--lux-gold-dark) transparent;

    /* 注意：保持 position: fixed，不要覆盖为 relative */
    overflow-y: auto;
    overflow-x: hidden;
}

/* Panel光学镀膜反光 */
#lux-panel::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: conic-gradient(
        from 180deg at 30% 20%,
        rgba(255, 250, 240, 0.035) 0deg,
        transparent 45deg,
        rgba(255, 240, 220, 0.025) 90deg,
        transparent 135deg,
        rgba(250, 235, 218, 0.03) 180deg,
        transparent 225deg,
        rgba(255, 248, 238, 0.035) 270deg,
        transparent 315deg,
        rgba(255, 250, 240, 0.035) 360deg
    );
    pointer-events: none;
    mix-blend-mode: overlay;
    opacity: 0.7;
}

#lux-panel::-webkit-scrollbar {
    width: 6px;
}

#lux-panel::-webkit-scrollbar-track {
    background: transparent;
}

#lux-panel::-webkit-scrollbar-thumb {
    background-color: var(--lux-gold-dark);
    border-radius: 3px;
}

/* Layer 4: 金属铭牌区域（标题栏）*/
.lux-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--lux-space-xl);
    padding: var(--lux-space-md) var(--lux-space-lg);
    background: linear-gradient(145deg, rgba(61, 66, 77, 0.6), rgba(42, 45, 53, 0.8));
    border-radius: var(--lux-radius-card);
    border: 1px solid color-mix(in srgb, var(--lux-gold) 20%, transparent);
    box-shadow:
        0 4px 12px rgba(0, 0, 0, 0.3),
        inset 0 1px 0 rgba(255, 255, 255, 0.06);

    position: relative;
    z-index: 1;
}

.lux-brand-text h1 {
    font-size: var(--lux-font-size-lg);
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--lux-gold-light);
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
    line-height: 1.2;
}

.lux-brand-text span {
    font-size: 10px;
    color: var(--lux-gold);
    font-family: var(--lux-font-mono);
    font-weight: 500;
    letter-spacing: 1px;
}

.lux-header-actions {
    display: flex;
    gap: 6px;
}

.lux-action-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    border: 1px solid color-mix(in srgb, var(--lux-gold) 20%, transparent);
    background: linear-gradient(145deg, rgba(90, 96, 112, 0.4), rgba(42, 45, 53, 0.6));
    color: var(--lux-gold);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
    transition: all 0.25s ease;
}

.lux-action-btn:hover {
    background: linear-gradient(145deg, color-mix(in srgb, var(--lux-gold) 20%, transparent), color-mix(in srgb, var(--lux-gold) 15%, transparent));
    border-color: color-mix(in srgb, var(--lux-gold) 40%, transparent);
    box-shadow: 0 0 12px color-mix(in srgb, var(--lux-gold) 20%, transparent);
    transform: translateY(-1px);
}

.lux-action-btn:active {
    transform: scale(0.95);
}

/* 核心指标区 - 玻璃卡片式布局 */
.lux-metrics-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: var(--lux-space-lg);
    position: relative;
    z-index: 1;
}

.lux-metric-card {
    backdrop-filter: blur(10px) saturate(140%);
    -webkit-backdrop-filter: blur(10px) saturate(140%);
    background: rgba(255, 255, 255, 0.06);
    border-radius: var(--lux-radius-card);
    padding: 12px 8px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    text-align: center;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.lux-metric-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--card-accent, var(--lux-gold));
    opacity: 0.8;
}

.lux-metric-card:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-3px);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3), 0 0 16px var(--card-glow, rgba(212, 175, 55, 0.1));
}

.lux-metric-label {
    font-size: 9px;
    font-weight: 700;
    color: var(--lux-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 4px;
}

.lux-metric-value {
    font-size: 22px;
    font-weight: 700;
    font-family: var(--lux-font-mono);
    color: #ffffff;
    line-height: 1;
    margin-bottom: 4px;
    text-shadow: 0 0 10px var(--card-accent, rgba(255, 255, 255, 0.2));
}

.lux-metric-unit {
    font-size: 11px;
    font-weight: 500;
    color: var(--lux-text-secondary);
}

.lux-metric-trend {
    height: 24px;
    margin-top: 4px;
    opacity: 0.6;
}

.lux-metric-card[data-metric="gpu"] { --card-accent: var(--lux-gold); --card-glow: color-mix(in srgb, var(--lux-gold) 15%, transparent); }
.lux-metric-card[data-metric="cpu"] { --card-accent: var(--lux-gold); --card-glow: color-mix(in srgb, var(--lux-gold) 15%, transparent); }
.lux-metric-card[data-metric="ram"] { --card-accent: var(--lux-gold); --card-glow: color-mix(in srgb, var(--lux-gold) 15%, transparent); }

/* 可折叠详情区 - Accordion机制 */
.lux-detail-section {
    margin-bottom: var(--lux-space-lg);
    position: relative;
    z-index: 1;
}

.lux-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    backdrop-filter: blur(8px) saturate(120%);
    -webkit-backdrop-filter: blur(8px) saturate(120%);
    background: rgba(255, 255, 255, 0.05);
    border-radius: var(--lux-radius-card);
    border: 1px solid color-mix(in srgb, var(--lux-gold) 15%, transparent);
    cursor: pointer;
    transition: all 0.25s ease;
    user-select: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.lux-section-header:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: color-mix(in srgb, var(--lux-gold) 25%, transparent);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25), 0 0 12px color-mix(in srgb, var(--lux-gold) 8%, transparent);
}

.lux-section-title {
    font-size: var(--lux-font-size-sm);
    font-weight: 700;
    color: var(--lux-gold-light);
    text-transform: uppercase;
    letter-spacing: 1.2px;
    display: flex;
    align-items: center;
    gap: 8px;
    text-shadow: 0 0 8px color-mix(in srgb, var(--lux-gold) 25%, transparent);
}

.lux-section-icon {
    font-size: 14px;
    opacity: 0.8;
}

.lux-section-toggle {
    font-size: 11px;
    color: var(--lux-gold);
    transition: transform 0.3s ease;
}

.lux-section-header.collapsed .lux-section-toggle {
    transform: rotate(-90deg);
}

.lux-section-content {
    margin-top: 12px;
    display: grid;
    gap: 12px;
    animation: lux-slideDown 0.3s ease-out;
}

.lux-section-header.collapsed + .lux-section-content {
    display: none;
}

@keyframes lux-slideDown {
    from {
        opacity: 0;
        transform: translateY(-8px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* 进度条行 - 玻璃卡片样式 */
.lux-progress-row {
    backdrop-filter: blur(8px) saturate(120%);
    -webkit-backdrop-filter: blur(8px) saturate(120%);
    background: rgba(255, 255, 255, 0.05);
    border-radius: var(--lux-radius-card);
    padding: 12px 14px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.lux-progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.lux-progress-label {
    font-size: var(--lux-font-size-sm);
    font-weight: 600;
    color: var(--lux-text-primary);
    display: flex;
    align-items: center;
    gap: 6px;
}

.lux-progress-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dot-color, var(--lux-gold));
    box-shadow: 0 0 6px var(--dot-color, var(--lux-gold));
}

.lux-progress-badge {
    font-size: var(--lux-font-size-xs);
    font-weight: 700;
    font-family: var(--lux-font-mono);
    padding: 3px 8px;
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.3);
    color: var(--badge-color, var(--lux-gold-light));
    border: 1px solid color-mix(in srgb, var(--lux-gold) 20%, transparent);
}

/* 进度条轨道 - 仪器风格 */
.lux-progress-track {
    height: 8px;
    background: rgba(0, 0, 0, 0.4);
    border-radius: 4px;
    overflow: hidden;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
    position: relative;
    border: 1px solid rgba(255, 255, 255, 0.05);
}

.lux-progress-fill {
    height: 100%;
    background: var(--fill-gradient, linear-gradient(90deg, var(--lux-gold), var(--lux-gold-mid)));
    border-radius: 4px;
    transition: width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
    position: relative;
    box-shadow: 0 0 8px color-mix(in srgb, var(--lux-gold) 35%, transparent);
}

/* 进度条颜色映射 - 统一绑定到主题金色调 */
.lux-progress-row[data-type="gpu"],
.lux-progress-row[data-type="vram"],
.lux-progress-row[data-type="cpu"],
.lux-progress-row[data-type="ram"],
.lux-progress-row[data-type="swap"],
.lux-progress-row[data-type="temp"] {
    --dot-color: var(--lux-gold);
    --badge-color: var(--lux-gold-light);
    --fill-gradient: linear-gradient(90deg, var(--lux-gold), var(--lux-gold-mid));
    --fill-glow: color-mix(in srgb, var(--lux-gold) 35%, transparent);
}

/* IO信息行 */
.lux-details-grid {
    display: grid;
    gap: 8px;
}

.lux-detail-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    backdrop-filter: blur(8px) saturate(120%);
    -webkit-backdrop-filter: blur(8px) saturate(120%);
    background: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    font-size: var(--lux-font-size-sm);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}

.lux-detail-left {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--lux-text-secondary);
}

.lux-detail-icon {
    font-size: 13px;
    opacity: 0.8;
}

.lux-detail-right {
    font-family: var(--lux-font-mono);
    font-size: var(--lux-font-size-xs);
    color: var(--lux-text-primary);
    font-weight: 600;
}

/* 设置与控制区 */
.lux-settings-section {
    margin-top: var(--lux-space-lg);
    padding-top: var(--lux-space-lg);
    border-top: 1px solid color-mix(in srgb, var(--lux-gold) 15%, transparent);
    position: relative;
    z-index: 1;
}

.lux-settings-group {
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.lux-setting-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    backdrop-filter: blur(8px) saturate(120%);
    -webkit-backdrop-filter: blur(8px) saturate(120%);
    background: rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}

.lux-setting-label {
    font-size: var(--lux-font-size-sm);
    font-weight: 600;
    color: var(--lux-text-primary);
}

/* Toggle开关 - 航空拨动开关样式（非iOS toggle）*/
.lux-toggle-switch {
    width: 52px;
    height: 26px;
    border-radius: 13px;
    position: relative;
    cursor: pointer;
    transition: all 0.3s ease;
    border: none;
    outline: none;
    background: rgba(0, 0, 0, 0.4);
    box-shadow:
        inset 0 2px 4px rgba(0, 0, 0, 0.5),
        0 1px 0 rgba(255, 255, 255, 0.05);
    z-index: 999;
    pointer-events: auto;
}

.lux-toggle-switch.active {
    background: linear-gradient(135deg, var(--lux-gold), var(--lux-gold-mid));
    box-shadow:
        inset 0 2px 4px rgba(0, 0, 0, 0.25),
        0 0 18px color-mix(in srgb, var(--lux-gold) 45%, transparent),
        0 0 4px color-mix(in srgb, var(--lux-gold) 60%, transparent);
}

.lux-toggle-thumb {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    position: absolute;
    top: 3px;
    left: 3px;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    background: linear-gradient(145deg, var(--lux-titanium-light), var(--lux-titanium));
    box-shadow:
        0 2px 4px rgba(0, 0, 0, 0.4),
        inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.lux-toggle-switch.active .lux-toggle-thumb {
    left: 29px;
    background: linear-gradient(145deg, #ffffff, var(--lux-gold-light));
    box-shadow:
        0 2px 6px rgba(212, 175, 55, 0.4),
        0 0 8px rgba(255, 255, 255, 0.2);
}

/* Radio组 - 宝石色调色盘（扁平矩形）*/
.lux-radio-group {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.lux-radio-btn {
    padding: 6px 14px;
    font-size: var(--lux-font-size-xs);
    font-weight: 600;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.25s ease;
    border: 1px solid rgba(212, 175, 55, 0.2);
    outline: none;
    background: rgba(255, 255, 255, 0.05);
    color: var(--lux-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-family: var(--lux-font-ui);
}

.lux-radio-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: color-mix(in srgb, var(--lux-gold) 35%, transparent);
    color: var(--lux-text-primary);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.lux-radio-btn.active {
    background: linear-gradient(135deg, var(--lux-gold), var(--lux-gold-mid));
    color: var(--lux-titanium-dark);
    border-color: var(--lux-gold);
    box-shadow:
        0 2px 8px color-mix(in srgb, var(--lux-gold) 30%, transparent),
        0 0 12px color-mix(in srgb, var(--lux-gold) 15%, transparent);
    font-weight: 700;
}

/* Phase 6: Lux Panel 主题切换 chip 布局与金属质感，active/hover 随 --lux-gold* 变化 */
.lux-style-chips {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.lux-style-chip[data-target] {
    padding: 6px 12px;
    font-size: var(--lux-font-size-xs);
    font-weight: 600;
    border-radius: var(--lux-radius-button);
    cursor: pointer;
    transition: all 0.25s ease;
    border: 1px solid color-mix(in srgb, var(--lux-gold) 25%, transparent);
    outline: none;
    background:
        linear-gradient(145deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0.03));
    color: var(--lux-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-family: var(--lux-font-ui);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.08),
        0 2px 4px rgba(0, 0, 0, 0.25);
}

.lux-style-chip[data-target]:hover {
    background:
        linear-gradient(145deg, color-mix(in srgb, var(--lux-gold) 18%, transparent), color-mix(in srgb, var(--lux-gold) 8%, transparent));
    border-color: color-mix(in srgb, var(--lux-gold) 50%, transparent);
    color: var(--lux-text-primary);
    box-shadow:
        0 2px 8px rgba(0, 0, 0, 0.3),
        0 0 10px color-mix(in srgb, var(--lux-gold) 18%, transparent);
    transform: translateY(-1px);
}

.lux-style-chip[data-target].active {
    background: linear-gradient(135deg, var(--lux-gold), var(--lux-gold-mid));
    color: var(--lux-titanium-dark);
    border-color: var(--lux-gold);
    box-shadow:
        0 2px 8px color-mix(in srgb, var(--lux-gold) 35%, transparent),
        0 0 14px color-mix(in srgb, var(--lux-gold) 22%, transparent),
        inset 0 1px 0 rgba(255, 255, 255, 0.35);
    font-weight: 700;
}

/* 通知区域 */
.lux-notification-area {
    margin-top: 16px;
    padding: 12px 14px;
    backdrop-filter: blur(8px) saturate(120%);
    -webkit-backdrop-filter: blur(8px) saturate(120%);
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    border-left: 3px solid var(--lux-gold);
    border: 1px solid color-mix(in srgb, var(--lux-gold) 15%, transparent);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.lux-notification-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}

.lux-notification-title {
    font-size: var(--lux-font-size-xs);
    font-weight: 700;
    color: var(--lux-gold);
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

.lux-notification-badge {
    font-size: 9px;
    padding: 2px 8px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--lux-gold), var(--lux-gold-mid));
    color: var(--lux-titanium-dark);
    font-weight: 600;
}

.lux-notification-text {
    font-size: var(--lux-font-size-sm);
    color: var(--lux-text-primary);
    line-height: 1.5;
}

/* 底部状态栏 */
.lux-panel-footer {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid color-mix(in srgb, var(--lux-gold) 15%, transparent);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 9px;
    color: var(--lux-text-muted);
    font-family: var(--lux-font-mono);
    position: relative;
    z-index: 1;
}

.lux-footer-left {
    display: flex;
    align-items: center;
    gap: 6px;
}

/* Layer 4: 状态LED指示灯（绿色常亮 + 微弱脉冲）*/
.lux-status-led {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--lux-gold);
    box-shadow:
        0 0 6px var(--lux-gold),
        0 0 12px color-mix(in srgb, var(--lux-gold) 40%, transparent);
    animation: lux-led-pulse 2s ease-in-out infinite;
}

@keyframes lux-led-pulse {
    0%, 100% {
        opacity: 1;
        box-shadow: 0 0 6px var(--lux-gold), 0 0 12px color-mix(in srgb, var(--lux-gold) 40%, transparent);
    }
    50% {
        opacity: 0.65;
        box-shadow: 0 0 4px var(--lux-gold), 0 0 8px color-mix(in srgb, var(--lux-gold) 25%, transparent);
    }
}

/* ============================================
   5. 响应式设计
   ============================================ */
@media (max-width: 900px) {
    :root {
        --lux-dock-width: 95vw;
        --lux-panel-width: 320px;
    }

    /* Phase 6 fix: 在 824px 左右保持单行，压缩模块尺寸 */
    #lux-dock {
        flex-wrap: nowrap;
        height: var(--lux-dock-height);
        padding: 6px 8px;
    }

    .lux-dock-handle {
        width: 16px;
        height: 36px;
        margin-right: 4px;
    }

    .lux-module-slot {
        flex: 1 0 96px;
        min-width: 90px;
        margin: 0 2px;
        padding: 3px;
    }

    .lux-glass-module {
        padding: 0 6px;
        gap: 4px;
    }

    .lux-module-icon {
        font-size: 13px;
    }

    .lux-module-label {
        font-size: 7px;
        letter-spacing: 0.4px;
    }

    .lux-module-value {
        font-size: 12px;
        min-width: 30px;
    }

    .lux-mini-progress {
        width: 34px;
        height: 4px;
    }

    .lux-settings-btn {
        width: 26px;
        height: 26px;
        font-size: 12px;
        margin-left: 4px;
    }

    #lux-panel {
        right: 10px;
        width: calc(100vw - 20px);
        max-width: 380px;
    }
}

@media (max-width: 600px) {
    .lux-metrics-grid {
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
    }

    .lux-metric-card {
        padding: 10px 6px;
    }

    .lux-metric-value {
        font-size: 18px;
    }

    #lux-panel {
        width: calc(100vw - 32px);
        padding: var(--lux-space-md);
    }
}

/* ============================================
   6. 无障碍增强
   ============================================ */
.lux-toggle-switch:focus-visible,
.lux-radio-btn:focus-visible,
.lux-action-btn:focus-visible,
.lux-settings-btn:focus-visible,
.lux-section-header:focus-visible {
    outline: 2px solid rgba(212, 175, 55, 0.6);
    outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
    
}


        /* === Cyber v6 "Orbital Command" (轨道指挥中心) 全部CSS === */

/* ============================================
   FEIXUE MONITOR v14 - Cyber v6 "Orbital Command"
   轨道指挥中心 / 微型飞船仪表盘 / 深空HUD监测器

   物理隐喻：一艘悬浮在ComfyUI画布上方的微型指挥舱
   核心特征：飞船形态 / 内凹驾驶舱 / 侧翼引擎舱 / 精确HUD发光 / 强立体感 / 零光晕
   ============================================ */

/* ============================================
   1. CSS变量系统 (Design Tokens)
   ============================================ */
:root {
    /* 深空船体色 — 切换颜色时保持不变 */
    --cyber-hull-top: #3a3d48;
    --cyber-hull-mid: #23252d;
    --cyber-hull-bot: #121319;
    --cyber-hull-shadow: #050608;

    /* HUD信号色 — switchColor 会覆盖 primary/secondary */
    --cyber-primary: #00e5ff;
    --cyber-primary-rgb: 0, 229, 255;
    --cyber-secondary: #ff7b00;
    --cyber-secondary-rgb: 255, 123, 0;
    --cyber-led: #00ff88;
    --cyber-led-rgb: 0, 255, 136;

    /* 状态辅助色 */
    --cyber-success: #00ff88;
    --cyber-warning: #ffb800;
    --cyber-danger: #ff3355;

    /* 文字颜色 */
    --cyber-text: #eef1f8;
    --cyber-text-dim: #7d8294;

    /* 驾驶舱深色 */
    --cyber-cockpit-top: #0b0c12;
    --cyber-cockpit-mid: #13151c;

    /* 尺寸令牌 */
    --cyber-dock-width: 920px;
    --cyber-dock-height: 92px;
    --cyber-panel-width: 390px;

    /* 字体系统 */
    --cyber-font-ui: 'Segoe UI', 'Roboto', 'SF Mono', Consolas, monospace;
    --cyber-font-mono: 'SF Mono', 'Roboto Mono', Consolas, monospace;
}

/* ============================================
   2. 全局基础样式
   ============================================ */
body.cyber-active {
    font-family: var(--cyber-font-ui);
    color: var(--cyber-text);
    line-height: 1.45;
}

/* ============================================
   3. DOCK 组件 — 轨道指挥舱
   ============================================ */
#cyber-dock {
    position: fixed;
    top: 18px;
    left: 50%;
    transform: translateX(-50%);
    width: var(--cyber-dock-width);
    max-width: calc(100vw - 16px);
    height: var(--cyber-dock-height);
    z-index: 99999;
    display: flex;
    align-items: center;
    box-sizing: border-box;
    padding: 0 78px;
    user-select: none;
    transition: transform 0.2s ease;
}

#cyber-dock:hover {
    transform: translateX(-50%) translateY(-2px);
}

/* 飞船主体外壳 — CNC钛金铣削质感 */
.cyber-hull {
    position: absolute;
    inset: 0;
    border-radius: 46px;
    background:
        /* 顶部高光带 */
        radial-gradient(ellipse at 50% 0%, rgba(255,255,255,0.18) 0%, transparent 45%),
        linear-gradient(180deg,
            var(--cyber-hull-top) 0%,
            var(--cyber-hull-mid) 40%,
            var(--cyber-hull-bot) 100%);
    border: 1px solid #525766;
    box-shadow:
        /* 顶部锐利高光 */
        inset 0 1px 0 rgba(255,255,255,0.45),
        /* 上沿倒角亮面 */
        inset 0 2px 1px rgba(255,255,255,0.12),
        /* 两侧厚度阴影 */
        inset 3px 0 4px rgba(0,0,0,0.55),
        inset -3px 0 4px rgba(0,0,0,0.55),
        /* 底部硬阴影 */
        inset 0 -2px 0 rgba(0,0,0,0.8),
        /* 下沿厚度 */
        inset 0 -1px 0 rgba(0,0,0,0.95),
        /* 下方悬浮接触影 */
        0 22px 50px rgba(0,0,0,0.85),
        0 10px 22px rgba(0,0,0,0.55);
    overflow: hidden;
}

/* 船体表面微拉丝纹理 */
.cyber-hull::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
        repeating-linear-gradient(0deg,
            transparent 0px,
            transparent 1px,
            rgba(255,255,255,0.018) 1px,
            rgba(255,255,255,0.018) 2px);
    pointer-events: none;
}

/* 顶部舱脊高光 */
.cyber-hull::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 10%;
    right: 10%;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        rgba(255,255,255,0.28) 20%,
        rgba(255,255,255,0.65) 50%,
        rgba(255,255,255,0.28) 80%,
        transparent 100%);
    pointer-events: none;
}

/* 两侧推进翼 — 立体引擎舱 */
.cyber-wing {
    position: absolute;
    top: 50%;
    width: 72px;
    height: 82px;
    transform: translateY(-50%);
    background:
        linear-gradient(180deg, #3a3d48 0%, #22242c 50%, #121319 100%);
    border: 1px solid #5a5e6e;
    box-shadow:
        /* 外沿高光 */
        inset 0 1px 0 rgba(255,255,255,0.22),
        inset 0 2px 1px rgba(255,255,255,0.06),
        /* 内侧机身衔接阴影 */
        inset -3px 0 5px rgba(0,0,0,0.65),
        inset 3px 0 5px rgba(0,0,0,0.55),
        /* 底部厚度 */
        inset 0 -2px 0 rgba(0,0,0,0.8),
        /* 外部悬浮影 */
        0 8px 18px rgba(0,0,0,0.75);
    pointer-events: none;
    z-index: -1;
}
.cyber-wing.left {
    left: -38px;
    clip-path: polygon(100% 0%, 100% 100%, 0% 85%, 0% 15%);
    border-radius: 14px 0 0 14px;
}
.cyber-wing.right {
    right: -38px;
    clip-path: polygon(0% 0%, 0% 100%, 100% 85%, 100% 15%);
    border-radius: 0 14px 14px 0;
}

/* 机翼表面散热格栅纹理 */
.cyber-wing::after {
    content: '';
    position: absolute;
    inset: 8px 10px;
    background:
        repeating-linear-gradient(0deg,
            transparent 0px,
            transparent 3px,
            rgba(0,0,0,0.18) 3px,
            rgba(0,0,0,0.18) 4px,
            transparent 4px,
            transparent 7px);
    opacity: 0.7;
    pointer-events: none;
}

/* 内凹驾驶舱窗口 — 深空HUD深腔 */
.cyber-cockpit {
    position: relative;
    flex: 1;
    height: 58px;
    margin: 0 16px;
    border-radius: 29px;
    background:
        /* 舱内顶部环境反光 */
        radial-gradient(ellipse at 50% 0%, rgba(var(--cyber-primary-rgb), 0.12) 0%, transparent 55%),
        /* 内凹径向渐变 */
        radial-gradient(ellipse at 50% 30%, rgba(255,255,255,0.03) 0%, transparent 60%),
        linear-gradient(180deg,
            #0a0b10 0%,
            var(--cyber-cockpit-top) 25%,
            var(--cyber-cockpit-mid) 50%,
            var(--cyber-cockpit-top) 75%,
            #0a0b10 100%);
    border: 1px solid rgba(255,255,255,0.08);
    box-shadow:
        /* 深腔内阴影 */
        inset 0 4px 14px rgba(0,0,0,0.95),
        inset 0 2px 6px rgba(0,0,0,0.9),
        /* 内沿高光 */
        inset 0 1px 0 rgba(255,255,255,0.06),
        /* 外沿机身凸起 */
        0 1px 0 rgba(255,255,255,0.1),
        0 3px 5px rgba(0,0,0,0.4);
    overflow: hidden;
    display: flex;
    align-items: center;
    z-index: 1;
}

/* 驾驶舱顶部HUD光晕 */
.cyber-cockpit::before {
    content: '';
    position: absolute;
    top: 0;
    left: 12%;
    right: 12%;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        rgba(var(--cyber-primary-rgb), 0.7) 30%,
        rgba(var(--cyber-primary-rgb), 0.7) 70%,
        transparent 100%);
    pointer-events: none;
}

/* 驾驶舱底部内沿阴影 */
.cyber-cockpit::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 5%;
    right: 5%;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        rgba(0,0,0,0.5) 30%,
        rgba(0,0,0,0.5) 70%,
        transparent 100%);
    pointer-events: none;
}

/* 六个数据舱 — 微凸仪表格 */
.cyber-pod {
    position: relative;
    flex: 1 1 0;
    min-width: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    padding: 4px 2px;
    box-sizing: border-box;
    border-right: 1px solid rgba(0,0,0,0.4);
    background:
        linear-gradient(180deg,
            rgba(255,255,255,0.03) 0%,
            transparent 20%,
            transparent 80%,
            rgba(0,0,0,0.18) 100%);
    transition: background 0.2s ease;
}
.cyber-pod:last-child {
    border-right: none;
}
.cyber-pod:hover {
    background:
        linear-gradient(180deg,
            rgba(255,255,255,0.05) 0%,
            transparent 20%,
            transparent 80%,
            rgba(0,0,0,0.12) 100%);
}

/* 每个舱顶部信号色条 */
.cyber-pod::before {
    content: '';
    position: absolute;
    top: 8px;
    left: 18%;
    right: 18%;
    height: 2px;
    background: var(--pod-accent, var(--cyber-primary));
    border-radius: 1px;
    opacity: 0.85;
}

/* pod颜色映射 */
.cyber-pod[data-type="gpu"]  { --pod-accent: var(--cyber-primary); }
.cyber-pod[data-type="vram"] { --pod-accent: var(--cyber-secondary); }
.cyber-pod[data-type="cpu"]  { --pod-accent: var(--cyber-success); }
.cyber-pod[data-type="ram"]  { --pod-accent: var(--cyber-secondary); }
.cyber-pod[data-type="swap"] { --pod-accent: var(--cyber-warning); }
.cyber-pod[data-type="temp"] { --pod-accent: var(--cyber-danger); }

.cyber-pod-icon {
    font-size: 12px;
    line-height: 1;
    color: var(--cyber-text-dim);
    flex-shrink: 0;
}
.cyber-pod-label {
    font-size: 7px;
    font-weight: 800;
    color: var(--cyber-text-dim);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    white-space: nowrap;
}
.cyber-pod-value {
    font-size: 15px;
    font-weight: 700;
    font-family: var(--cyber-font-mono);
    font-variant-numeric: tabular-nums;
    color: var(--pod-accent, var(--cyber-text));
    min-width: 36px;
    text-align: center;
    line-height: 1;
}
.cyber-pod-unit {
    font-size: 7px;
    font-weight: 600;
    color: var(--cyber-text-dim);
    margin-left: 1px;
}
.cyber-pod-bar {
    width: 70%;
    height: 3px;
    background: rgba(0,0,0,0.55);
    border-radius: 1px;
    overflow: hidden;
    margin-top: 2px;
    border: 1px solid rgba(0,0,0,0.4);
}
.cyber-pod-bar-fill {
    height: 100%;
    border-radius: 1px;
    background: linear-gradient(90deg,
        var(--pod-accent, var(--cyber-primary)) 0%,
        rgba(255,255,255,0.7) 100%);
    transition: width 0.5s ease;
}

/* 左侧系统状态灯 */
.cyber-status-led {
    position: absolute;
    left: 26px;
    top: 50%;
    transform: translateY(-50%);
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background:
        radial-gradient(circle at 35% 35%, rgba(255,255,255,0.9) 0%, var(--cyber-led) 40%, #006622 100%);
    border: 1px solid rgba(0,0,0,0.5);
    box-shadow:
        0 0 0 1px rgba(0,0,0,0.4),
        inset 0 -1px 1px rgba(0,0,0,0.5);
    z-index: 2;
}

/* 拖拽手柄 */
.cyber-handle {
    position: absolute;
    left: 44px;
    top: 50%;
    transform: translateY(-50%);
    width: 22px;
    height: 40px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    cursor: grab;
    z-index: 2;
}
.cyber-handle:active {
    cursor: grabbing;
}
.cyber-handle-ridge {
    width: 14px;
    height: 2px;
    background: rgba(255,255,255,0.18);
    border-radius: 1px;
    box-shadow: 0 1px 1px rgba(0,0,0,0.5);
}

/* 右侧设置按钮 */
.cyber-settings {
    position: absolute;
    right: 22px;
    top: 50%;
    transform: translateY(-50%);
    width: 34px;
    height: 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    cursor: pointer;
    color: var(--cyber-text-dim);
    font-size: 16px;
    background:
        radial-gradient(circle at 30% 30%, #3c3f4d 0%, #1e2028 100%);
    border: 1px solid #525666;
    box-shadow:
        0 3px 6px rgba(0,0,0,0.55),
        inset 0 1px 0 rgba(255,255,255,0.18),
        inset 0 -1px 0 rgba(0,0,0,0.5);
    z-index: 2;
    outline: none;
    transition: all 0.2s ease;
}
.cyber-settings:hover {
    color: var(--cyber-primary);
    border-color: var(--cyber-primary);
    transform: translateY(-50%) rotate(45deg);
}

/* ============================================
   4. PANEL 组件 — 轨道指挥舱控制面板
   ============================================ */
#cyber-panel {
    position: fixed;
    top: 118px;
    right: 20px;
    width: var(--cyber-panel-width);
    max-height: calc(100vh - 140px);
    overflow-y: auto;
    z-index: 99999;
    padding: 24px;
    box-sizing: border-box;
    border-radius: 26px;
    background:
        /* 顶部环境反光 */
        radial-gradient(ellipse at 50% 0%, rgba(var(--cyber-primary-rgb), 0.06) 0%, transparent 45%),
        linear-gradient(180deg, #2d2f38 0%, #1e2028 50%, #131419 100%);
    border: 1px solid #525766;
    box-shadow:
        /* 外框高光 */
        inset 0 1px 0 rgba(255,255,255,0.28),
        /* 上沿倒角 */
        inset 0 2px 1px rgba(255,255,255,0.08),
        /* 两侧厚度阴影 */
        inset 2px 0 3px rgba(0,0,0,0.55),
        inset -2px 0 3px rgba(0,0,0,0.55),
        /* 底部硬阴影 */
        inset 0 -2px 0 rgba(0,0,0,0.75),
        /* 外部悬浮影 */
        0 20px 48px rgba(0,0,0,0.85),
        0 10px 22px rgba(0,0,0,0.55);
    scrollbar-width: thin;
    scrollbar-color: var(--cyber-text-dim) transparent;
}

#cyber-panel::-webkit-scrollbar { width: 5px; }
#cyber-panel::-webkit-scrollbar-track { background: transparent; }
#cyber-panel::-webkit-scrollbar-thumb { background-color: var(--cyber-text-dim); border-radius: 2px; }

/* 面板顶部舱脊高光 */
#cyber-panel::before {
    content: '';
    position: absolute;
    top: 2px;
    left: 10%;
    right: 10%;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        rgba(255,255,255,0.25) 20%,
        rgba(255,255,255,0.55) 50%,
        rgba(255,255,255,0.25) 80%,
        transparent 100%);
    pointer-events: none;
}

/* 面板底部内沿阴影 */
#cyber-panel::after {
    content: '';
    position: absolute;
    bottom: 1px;
    left: 8%;
    right: 8%;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        rgba(0,0,0,0.4) 20%,
        rgba(0,0,0,0.4) 80%,
        transparent 100%);
    pointer-events: none;
}

.cyber-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 18px;
    padding-bottom: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}

.cyber-panel-title {
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--cyber-text);
    font-family: var(--cyber-font-mono);
}

.cyber-panel-clock {
    font-size: 12px;
    font-family: var(--cyber-font-mono);
    color: var(--cyber-text-dim);
}

/* 核心指标卡片网格 */
.cyber-metrics-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 20px;
}

.cyber-metric-card {
    position: relative;
    background:
        linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(0,0,0,0.1) 100%);
    border-radius: 14px;
    padding: 14px 6px;
    text-align: center;
    border: 1px solid rgba(255,255,255,0.06);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.06),
        inset 0 -1px 0 rgba(0,0,0,0.4),
        0 3px 6px rgba(0,0,0,0.35);
    transition: all 0.2s ease;
    overflow: hidden;
}
.cyber-metric-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 20%;
    right: 20%;
    height: 2px;
    background: var(--card-accent, var(--cyber-primary));
    opacity: 0.8;
}
.cyber-metric-card[data-metric="gpu"] { --card-accent: var(--cyber-primary); }
.cyber-metric-card[data-metric="cpu"] { --card-accent: var(--cyber-success); }
.cyber-metric-card[data-metric="ram"] { --card-accent: var(--cyber-secondary); }

.cyber-metric-card:hover {
    transform: translateY(-2px);
}

.cyber-metric-label {
    font-size: 8px;
    font-weight: 800;
    color: var(--cyber-text-dim);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 6px;
}

.cyber-metric-value {
    font-size: 22px;
    font-weight: 700;
    font-family: var(--cyber-font-mono);
    font-variant-numeric: tabular-nums;
    color: var(--card-accent, var(--cyber-text));
    line-height: 1;
}

.cyber-metric-unit {
    font-size: 10px;
    font-weight: 600;
    color: var(--cyber-text-dim);
}

/* 可折叠详情区 */
.cyber-detail-section { margin-bottom: 18px; }

.cyber-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    background: rgba(0,0,0,0.15);
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.05);
    border-left: 3px solid var(--section-accent, var(--cyber-primary));
    cursor: pointer;
    transition: all 0.2s ease;
    user-select: none;
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.04),
        inset 0 -1px 0 rgba(0,0,0,0.25);
}
.cyber-section-header:hover {
    border-color: rgba(255,255,255,0.1);
}

.cyber-section-title {
    font-size: 10px;
    font-weight: 700;
    color: var(--cyber-text-dim);
    text-transform: uppercase;
    letter-spacing: 1px;
    display: flex;
    align-items: center;
    gap: 6px;
}

.cyber-section-icon { font-size: 12px; opacity: 0.8; }

.cyber-section-toggle {
    font-size: 10px;
    color: var(--cyber-text-dim);
    transition: transform 0.3s ease;
}

.cyber-section-header.collapsed .cyber-section-toggle { transform: rotate(-90deg); }

.cyber-section-content {
    margin-top: 10px;
    display: grid;
    gap: 10px;
    animation: cyber-slideDown 0.25s ease-out;
}

.cyber-section-header.collapsed + .cyber-section-content { display: none; }

@keyframes cyber-slideDown {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* 进度条行 */
.cyber-progress-row {
    background: rgba(0,0,0,0.12);
    border-radius: 12px;
    padding: 10px 12px;
    border: 1px solid rgba(255,255,255,0.05);
    border-left: 2px solid var(--row-accent, var(--cyber-primary));
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.03),
        0 2px 4px rgba(0,0,0,0.25);
}

.cyber-progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.cyber-progress-label {
    font-size: 10px;
    font-weight: 700;
    color: var(--cyber-text);
    display: flex;
    align-items: center;
    gap: 6px;
}

.cyber-progress-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--row-accent, var(--cyber-primary));
    border: 1px solid rgba(0,0,0,0.4);
}

.cyber-progress-badge {
    font-size: 10px;
    font-weight: 700;
    font-family: var(--cyber-font-mono);
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(0,0,0,0.3);
    color: var(--row-accent, var(--cyber-primary));
    border: 1px solid rgba(255,255,255,0.05);
}

.cyber-progress-track {
    height: 6px;
    background: rgba(0,0,0,0.4);
    border-radius: 3px;
    overflow: hidden;
    position: relative;
    border: 1px solid rgba(0,0,0,0.4);
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.5);
}

.cyber-progress-fill {
    height: 100%;
    border-radius: 3px;
    background: linear-gradient(90deg,
        var(--fill-start, var(--cyber-primary)) 0%,
        var(--fill-end, var(--cyber-secondary)) 100%);
    transition: width 0.5s ease;
    border-right: 1px solid rgba(255,255,255,0.2);
}

.cyber-progress-row[data-type="gpu"]  { --row-accent: var(--cyber-primary);   --fill-start: var(--cyber-primary);   --fill-end: var(--cyber-secondary); }
.cyber-progress-row[data-type="vram"] { --row-accent: var(--cyber-secondary); --fill-start: var(--cyber-secondary); --fill-end: var(--cyber-primary); }
.cyber-progress-row[data-type="cpu"]  { --row-accent: var(--cyber-success);   --fill-start: var(--cyber-success);   --fill-end: var(--cyber-primary); }
.cyber-progress-row[data-type="ram"]  { --row-accent: var(--cyber-secondary); --fill-start: var(--cyber-secondary); --fill-end: var(--cyber-primary); }
.cyber-progress-row[data-type="swap"] { --row-accent: var(--cyber-warning);   --fill-start: var(--cyber-warning);   --fill-end: var(--cyber-primary); }
.cyber-progress-row[data-type="temp"] { --row-accent: var(--cyber-danger);    --fill-start: var(--cyber-danger);    --fill-end: var(--cyber-secondary); }

/* IO信息行 */
.cyber-details-grid { display: grid; gap: 8px; }

.cyber-detail-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: rgba(0,0,0,0.12);
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.04);
    font-size: 10px;
}

.cyber-detail-left {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--cyber-text-dim);
}

.cyber-detail-icon { font-size: 12px; opacity: 0.8; }

.cyber-detail-right {
    font-family: var(--cyber-font-mono);
    font-size: 10px;
    color: var(--cyber-text);
    font-weight: 600;
}

/* 控制区 */
.cyber-controls-section {
    margin-top: 20px;
    padding-top: 18px;
    border-top: 1px solid rgba(255,255,255,0.08);
}

.cyber-control-group {
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.cyber-control-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: rgba(0,0,0,0.12);
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.04);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.04),
        inset 0 -1px 0 rgba(0,0,0,0.25);
}

.cyber-control-label {
    font-size: 10px;
    font-weight: 700;
    color: var(--cyber-text);
    letter-spacing: 0.5px;
}

/* Toggle开关 — 飞船拨杆 */
.cyber-toggle-switch {
    width: 44px;
    height: 22px;
    border-radius: 11px;
    position: relative;
    cursor: pointer;
    transition: all 0.25s ease;
    border: 1px solid #3a3e52;
    outline: none;
    background: #0d0e12;
    box-shadow:
        inset 0 1px 3px rgba(0,0,0,0.7),
        inset 0 1px 0 rgba(255,255,255,0.04);
    z-index: 999;
    pointer-events: auto;
}

.cyber-toggle-switch.active {
    background: #12141a;
    border-color: var(--cyber-primary);
    box-shadow:
        inset 0 1px 2px rgba(0,0,0,0.5),
        0 0 4px rgba(var(--cyber-primary-rgb), 0.25);
}

.cyber-toggle-thumb {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    position: absolute;
    top: 2px;
    left: 3px;
    transition: all 0.25s cubic-bezier(0.68, -0.55, 0.265, 1.55);
    background:
        radial-gradient(circle at 30% 30%, #5a6075 0%, #2d3040 100%);
    border: 1px solid #6a7085;
    box-shadow:
        0 2px 3px rgba(0,0,0,0.5),
        inset 0 1px 0 rgba(255,255,255,0.2);
}

.cyber-toggle-switch.active .cyber-toggle-thumb {
    left: 23px;
    background:
        radial-gradient(circle at 30% 30%, var(--cyber-primary) 0%, #006a75 100%);
    border-color: var(--cyber-primary);
}

/* 模式/颜色切换栏 */
.cyber-control-bar,
.cyber-color-bar {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 10px 12px;
    margin-top: 12px;
    background: rgba(0,0,0,0.12);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 12px;
    flex-wrap: wrap;
}

.cyber-mode-label {
    font-family: var(--cyber-font-mono);
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--cyber-text-dim);
    white-space: nowrap;
}

/* 驾驶舱按钮 */
.cyber-mode-btn,
.cyber-color-btn {
    font-family: var(--cyber-font-mono);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-size: 9px;
    font-weight: 700;
    padding: 5px 10px;
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s ease;
    white-space: nowrap;
    background:
        linear-gradient(180deg, #2c2f3a 0%, #1a1c24 100%);
    border: 1px solid #464a5a;
    color: var(--cyber-text-dim);
    box-shadow:
        0 2px 3px rgba(0,0,0,0.35),
        inset 0 1px 0 rgba(255,255,255,0.08);
}

.cyber-mode-btn:hover,
.cyber-color-btn:hover {
    color: var(--cyber-text);
    border-color: var(--cyber-text-dim);
    background:
        linear-gradient(180deg, #35394a 0%, #20232c 100%);
}

.cyber-mode-btn.active,
.cyber-color-btn.active {
    color: var(--cyber-primary);
    background:
        linear-gradient(180deg, #1a1c26 0%, #12131a 100%);
    border-color: var(--cyber-primary);
    box-shadow:
        inset 0 1px 2px rgba(0,0,0,0.4),
        0 0 4px rgba(var(--cyber-primary-rgb), 0.2);
}

.cyber-color-btn { color: var(--chip-color, var(--cyber-primary)); border-color: #464a5a; }
.cyber-color-btn.active { color: var(--cyber-primary); border-color: var(--cyber-primary); }

/* 底部状态栏 */
.cyber-status-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    margin-top: 14px;
    font-family: var(--cyber-font-mono);
    font-size: 9px;
    color: var(--cyber-text-dim);
    border-top: 1px solid rgba(255,255,255,0.08);
    letter-spacing: 1px;
}

/* ============================================
   5. 关键帧动画
   ============================================ */
@keyframes cyber-flow {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* ============================================
   6. 响应式设计
   ============================================ */
@media (max-width: 900px) {
    :root {
        --cyber-dock-width: 98vw;
        --cyber-panel-width: 320px;
    }

    #cyber-dock {
        height: 78px;
        padding: 0 52px;
    }

    .cyber-cockpit {
        height: 50px;
        margin: 0 8px;
        border-radius: 25px;
    }

    .cyber-wing {
        width: 52px;
        height: 64px;
    }
    .cyber-wing.left { left: -24px; }
    .cyber-wing.right { right: -24px; }

    .cyber-status-led { left: 18px; width: 7px; height: 7px; }
    .cyber-handle { left: 34px; width: 18px; }
    .cyber-settings { right: 14px; width: 30px; height: 30px; font-size: 14px; }

    .cyber-pod-value { font-size: 13px; min-width: 30px; }
    .cyber-pod-bar { width: 75%; }

    #cyber-panel {
        right: 10px;
        width: calc(100vw - 20px);
        max-width: 360px;
        padding: 18px;
    }
}

@media (max-width: 680px) {
    #cyber-dock {
        height: auto;
        min-height: 78px;
        padding: 10px 46px;
    }

    .cyber-cockpit {
        height: auto;
        min-height: 58px;
        padding: 6px 0;
        flex-wrap: wrap;
    }

    .cyber-pod {
        flex: 1 1 calc(33.33% - 2px);
        min-width: calc(33.33% - 2px);
        height: 52px;
        border-bottom: 1px solid rgba(0,0,0,0.35);
    }

    .cyber-pod:nth-child(3) { border-right: none; }
    .cyber-pod:nth-child(n+4) { border-bottom: none; }

    .cyber-metrics-grid { gap: 6px; }
    .cyber-metric-value { font-size: 18px; }

    #cyber-panel {
        width: calc(100vw - 32px);
        padding: 16px;
    }
}

/* ============================================
   7. 无障碍增强
   ============================================ */
.cyber-toggle-switch:focus-visible,
.cyber-mode-btn:focus-visible,
.cyber-color-btn:focus-visible,
.cyber-settings:focus-visible,
.cyber-section-header:focus-visible {
    outline: 2px solid var(--cyber-primary);
    outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
    .cyber-pod-bar-fill,
    .cyber-progress-fill { animation: none; }
}

  
`;

        document.head.appendChild(style);
        console.log('[飞雪监测器] ✅ Premium CSS injected (5 themes)');
    }

    // ============================================================
    // 5主题系统常量定义 — Premium UI v3.25
    // ============================================================

    /** 有效风格列表 */
    const VALID_STYLES = ['neu', 'ind', 'retro', 'lux', 'cyber'];

    // ============================================================
    // i18n 国际化标签映射
    // ============================================================
    const I18N_MAPS = {
        zh: {
            // Dock / 核心指标标签（保持简短，避免溢出）
            gpu: 'GPU', cpu: 'CPU', ram: '内存', vram: '显存',
            swap: 'SWAP', temp: '温度',
            core_metrics: '核心性能指标',
            // 面板分区标题
            performance: '性能监控', memory: '内存状态', system: '系统信息',
            gpu_vram_details: 'GPU 与显存详情', system_resources: '系统资源',
            io_network: 'I/O 与网络',
            // 进度条/详情标签
            core_usage: '核心占用', vram_usage: '显存占用', temperature: '温度',
            cpu_usage: 'CPU 占用', physical_ram: '物理内存', swap_memory: '交换内存',
            disks_io: '磁盘 I/O', network_io: '网络 I/O',
            disk_read: '读取', disk_write: '写入',
            net_up: '上传', net_down: '下载',
            // 设置项
            sound_alert: '声音提示', drag_mode: '拖拽模式', theme: '主题',
            color: '色彩', settings: '设置', settings_panel: '设置面板', close: '关闭',
            // 风格名称
            theme_name_neu: '拟物白', theme_name_ind: '钛金仪', theme_name_retro: '复古终端',
            theme_name_lux: '珠宝柜', theme_name_cyber: '量子核', theme_name_capsule: '翡翠胶囊',
            // 状态/来源
            source_prefix: '来源: ', detecting: '检测中...',
            plugin_active: 'ComfyUI 插件运行中',
            workflow_status: '工作流状态',
            // 通用
            load: '负载', usage: '占用', usage_rate: '使用率',
            // 工具提示
            drag_move: '拖拽移动', system_normal: '系统正常'
        },
        en: {
            gpu: 'GPU', cpu: 'CPU', ram: 'RAM', vram: 'VRAM',
            swap: 'SWAP', temp: 'TEMP',
            core_metrics: 'Core Metrics',
            performance: 'PERFORMANCE', memory: 'MEMORY', system: 'SYSTEM',
            gpu_vram_details: 'GPU & VRAM Details', system_resources: 'System Resources',
            io_network: 'I/O & Network',
            core_usage: 'Core Usage', vram_usage: 'VRAM Usage', temperature: 'Temperature',
            cpu_usage: 'CPU Usage', physical_ram: 'Physical RAM', swap_memory: 'Swap Memory',
            disks_io: 'Disks I/O', network_io: 'Network IO',
            disk_read: 'Read', disk_write: 'Write',
            net_up: 'Upload', net_down: 'Download',
            sound_alert: 'Sound Alert', drag_mode: 'Drag Mode', theme: 'Theme',
            color: 'Color', settings: 'Settings', settings_panel: 'Settings Panel', close: 'Close',
            theme_name_neu: 'Neu', theme_name_ind: 'Ind', theme_name_retro: 'Retro',
            theme_name_lux: 'Lux', theme_name_cyber: 'Cyber', theme_name_capsule: 'Capsule',
            source_prefix: 'Source: ', detecting: 'Detecting...',
            plugin_active: 'ComfyUI Plugin Active',
            workflow_status: 'Workflow Status',
            load: 'Load', usage: 'Usage', usage_rate: 'Usage',
            drag_move: 'Drag to move', system_normal: 'System normal'
        }
    };

    /** 当前语言（根据浏览器检测） */
    const FXM_LANG = (navigator.language || 'en').startsWith('zh') ? 'zh' : 'en';

    /** 获取i18n文本 */
    function t(key) {
        const map = I18N_MAPS[FXM_LANG] || I18N_MAPS.en;
        return map[key] !== undefined ? map[key] : (I18N_MAPS.en[key] !== undefined ? I18N_MAPS.en[key] : key);
    }

    /** 有效颜色白名单（Neu子主题色） */
    const COLOR_WHITELIST = ['aurora', 'ocean', 'sunset', 'forest', 'midnight'];

    /** 颜色映射表：CSS变量值 */
    const COLOR_MAPS = {
        aurora:   { base: '#e0e5ec', name: '极光陶瓷' },
        ocean:    { base: '#e4e8ed', name: '深海蓝' },
        sunset:   { base: '#ede9e4', name: '落日暖' },
        forest:   { base: '#e8f0e8', name: '森林绿' },
        midnight: { base: '#d8dde8', name: '午夜黑' }
    };

    /** 风格→CSS类名映射 + 显示信息 */
    const THEME_CLASS_MAP = {
        neu:   { dockClass: 'neu-dock', panelClass: 'neu-panel', bodyClass: 'neu-active', name: '拟物白' },
        ind:   { dockClass: 'ind-dock',  panelClass: 'ind-panel',  bodyClass: 'ind-active',  name: '钛金仪' },
        retro: { dockClass: 'retro-dock',panelClass: 'retro-panel',bodyClass: 'retro-active',name: '复古终端' },
        lux:   { dockClass: 'lux-dock',  panelClass: 'lux-panel',  bodyClass: 'lux-active',  name: '珠宝柜' },
        cyber: { dockClass: 'cyber-dock',panelClass: 'cyber-panel',bodyClass: 'cyber-active',name: '量子核' }
    };

    /** 当前激活的风格（复用L457声明的currentStyle变量） */
    // let currentStyle = 'neu'; // 已在上方声明，此处不重复

    /** 当前激活的颜色方案（仅Neu风格使用） */
    let currentColor = 'aurora';

    // ============================================================
    // 拖拽状态（新5主题系统）
    // 注意：isDragging, dragStartX, dragStartY, barStartLeft, barStartTop, savedBarLeft, savedBarTop
    //       均已在L429~436声明，此处不重复声明以避免SyntaxError
    // ============================================================

    // ============================================================
    // Dock DOM 创建 — 为全部5种风格创建Dock容器
    // ============================================================

    /**
     * 创建所有5个风格的Dock DOM并挂载到document.body
     * 每个Dock包含6个指标项(GPU/VRAM/CPU/RAM/SWAP/TEMP) + 设置按钮
     * 默认仅显示currentStyle对应的Dock，其余添加style-hidden类
     */
    function createAllDockPanels() {
        const metrics = [
            { type: 'gpu', label: t('gpu'), icon: '\u{1F3AE}', unit: '%' },
            { type: 'vram', label: t('vram'), icon: '\u{1F4BE}', unit: 'GB' },
            { type: 'cpu', label: t('cpu'), icon: '\u26A1', unit: '%' },
            { type: 'ram', label: t('ram'), icon: '\u{1F4E0}', unit: '%' },
            { type: 'swap', label: t('swap'), icon: '\u{1F504}', unit: 'GB' },
            { type: 'temp', label: t('temp'), icon: '\u{1F321}', unit: '\u00B0C' }
        ];

        VALID_STYLES.forEach(style => {
            const dock = document.createElement('div');
            dock.id = style + '-dock';
            if (style !== 'neu') dock.classList.add('style-hidden');

            // 根据不同风格设置不同的基础class
            switch (style) {
                case 'neu':
                    dock.className = 'neu-dock';
                    buildNeuDock(dock, metrics);
                    break;
                case 'ind':
                    dock.className = 'ind-dock style-hidden';
                    buildIndDock(dock, metrics);
                    break;
                case 'retro':
                    dock.className = 'retro-container retro-dock style-hidden';
                    buildRetroDock(dock, metrics);
                    break;
                case 'lux':
                    dock.className = 'lux-dock';
                    buildLuxDock(dock, metrics);
                    break;
                case 'cyber':
                    dock.className = 'cyber-dock';
                    buildCyberDock(dock, metrics);
                    break;
            }

            document.body.appendChild(dock);
        });

        console.log(`[飞雪监测器] ✅ 已创建 ${VALID_STYLES.length} 个Dock面板 (${VALID_STYLES.join(', ')})`);
    }

    /** Neu Dock 内部构建（拟物白）*/
    function buildNeuDock(dock, metrics) {
        // 拖拽手柄
        const handle = document.createElement('div');
        handle.className = 'neu-dock-handle';
        handle.title = t('drag_move');
        for (let i = 0; i < 6; i++) {
            const dot = document.createElement('span');
            dot.className = 'neu-handle-dot';
            handle.appendChild(dot);
        }
        dock.appendChild(handle);

        // 指标芯片
        metrics.forEach(m => {
            const chip = document.createElement('div');
            chip.className = 'neu-metric-chip';
            chip.setAttribute('data-type', m.type);
            chip.title = m.label;

            const icon = document.createElement('span');
            icon.className = 'neu-chip-icon';
            icon.textContent = m.icon;

            const label = document.createElement('span');
            label.className = 'neu-chip-label';
            label.textContent = m.label;

            const value = document.createElement('span');
            value.className = 'neu-chip-value';
            value.id = 'neu-chip-' + m.type + '-value';
            value.textContent = '--';

            const track = document.createElement('div');
            track.className = 'neu-chip-progress-track';
            const fill = document.createElement('div');
            fill.className = 'neu-chip-progress-fill';
            fill.id = 'neu-chip-' + m.type + '-progress';
            fill.style.width = '0%';
            track.appendChild(fill);

            chip.appendChild(icon);
            chip.appendChild(label);
            chip.appendChild(value);
            chip.appendChild(track);
            dock.appendChild(chip);
        });

        // 设置按钮
        const btn = document.createElement('button');
        btn.className = 'neu-settings-btn';
        btn.id = 'neu-settingsBtn';
        btn.title = t('settings_panel');
        btn.textContent = '\u2699';
        btn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel(currentStyle); });
        dock.appendChild(btn);
    }

    /** Ind Dock 内部构建（钛金仪）*/
    function buildIndDock(dock, metrics) {
        // 四角螺丝
        ['tl','tr','bl','br'].forEach(pos => {
            const screw = document.createElement('div');
            screw.className = 'ind-screw ' + pos;
            dock.appendChild(screw);
        });

        // 拖拽手柄
        const handle = document.createElement('div');
        handle.className = 'ind-drag-handle';
        handle.title = t('drag_move');
        for (let i = 0; i < 5; i++) {
            const line = document.createElement('div');
            line.className = 'ind-drag-line';
            handle.appendChild(line);
        }
        dock.appendChild(handle);

        // VU仪表指标
        metrics.forEach(m => {
            const metric = document.createElement('div');
            metric.className = 'ind-metric';

            const label = document.createElement('span');
            label.className = 'ind-metric-label';
            label.textContent = m.label;

            if (m.type === 'temp') {
                // 温度特殊显示
                const tempDisp = document.createElement('div');
                tempDisp.className = 'ind-temp-display';
                const tVal = document.createElement('span');
                tVal.className = 'ind-temp-value';
                tVal.id = 'ind-temp-value';
                tVal.textContent = '--';
                const tUnit = document.createElement('span');
                tUnit.className = 'ind-temp-unit';
                tUnit.textContent = '\u00B0C';
                tempDisp.appendChild(tVal);
                tempDisp.appendChild(tUnit);

                const tempBar = document.createElement('div');
                tempBar.className = 'ind-temp-bar';
                const ind = document.createElement('div');
                ind.className = 'ind-temp-indicator';
                ind.id = 'ind-temp-indicator';
                ind.style.left = '0%';
                tempBar.appendChild(ind);

                metric.appendChild(label);
                metric.appendChild(tempDisp);
                metric.appendChild(tempBar);
            } else {
                const value = document.createElement('span');
                value.className = 'ind-metric-value';
                value.id = 'ind-' + m.type + '-value';
                value.textContent = '--';

                const vuMeter = document.createElement('div');
                vuMeter.className = 'ind-vu-meter';
                [100, 100, 100, 100, 0, 0].forEach((w, i) => {
                    const seg = document.createElement('div');
                    seg.className = 'ind-vu-segment';
                    if (i < 2) seg.classList.add('green');
                    else if (i < 3) seg.classList.add('amber');
                    else if (i < 4) seg.classList.add('red');
                    seg.style.width = w + '%';
                    vuMeter.appendChild(seg);
                });
                // 用一个fill元素代替多段
                vuMeter.innerHTML = '';
                const fillSeg = document.createElement('div');
                fillSeg.className = 'ind-vu-segment green';
                fillSeg.id = 'ind-' + m.type + '-vu-fill';
                fillSeg.style.width = '0%';
                vuMeter.appendChild(fillSeg);

                metric.appendChild(label);
                metric.appendChild(value);
                metric.appendChild(vuMeter);
            }

            dock.appendChild(metric);
        });

        // 设置按钮
        const btn = document.createElement('button');
        btn.className = 'ind-settings-btn';
        btn.title = t('settings');
        btn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel(currentStyle); });
        dock.appendChild(btn);
    }

    /** Retro Dock 内部构建（复古终端）*/
    function buildRetroDock(dock, metrics) {
        // 四角螺丝
        ['screw-tl','screw-tr','screw-bl','screw-br'].forEach(cls => {
            const screw = document.createElement('div');
            screw.className = 'retro-screw ' + cls;
            dock.appendChild(screw);
        });

        // 屏幕容器
        const screenWell = document.createElement('div');
        screenWell.className = 'retro-screen-well';

        // 扫描线等效果
        const scanlines = document.createElement('div');
        scanlines.className = 'retro-scanlines';
        const scanBeam = document.createElement('div');
        scanBeam.className = 'retro-scan-beam';
        const glassReflect = document.createElement('div');
        glassReflect.className = 'retro-glass-reflection';

        const inner = document.createElement('div');
        inner.className = 'retro-dock-inner retro-flicker';

        // 拖拽手柄
        const handle = document.createElement('div');
        handle.className = 'retro-drag-handle';
        handle.title = 'DRAG TO MOVE';
        for (let i = 0; i < 3; i++) {
            const line = document.createElement('div');
            line.className = 'retro-drag-line';
            handle.appendChild(line);
        }
        inner.appendChild(handle);

        // LED指标
        metrics.forEach(m => {
            const metric = document.createElement('div');
            metric.className = 'retro-metric';
            metric.setAttribute('data-type', m.type);

            const label = document.createElement('span');
            label.className = 'retro-metric-label';
            label.textContent = m.label;

            if (m.type === 'temp') {
                const val = document.createElement('span');
                val.className = 'retro-temp-value';
                val.id = 'retro-temp-value';
                val.textContent = '--\u00B0C';
                metric.appendChild(label);
                metric.appendChild(val);
            } else {
                const value = document.createElement('span');
                value.className = 'retro-metric-value';
                value.id = 'retro-' + m.type + '-value';
                value.textContent = '--%';

                const ledBar = document.createElement('div');
                ledBar.className = 'retro-led-bar';
                for (let i = 0; i < 8; i++) {
                    const seg = document.createElement('div');
                    seg.className = 'retro-led-segment';
                    ledBar.appendChild(seg);
                }

                metric.appendChild(label);
                metric.appendChild(value);
                metric.appendChild(ledBar);
            }

            inner.appendChild(metric);
        });

        // 设置按钮
        const btn = document.createElement('button');
        btn.className = 'retro-settings-btn';
        btn.title = t('settings');
        btn.textContent = '\u{1F527}';
        btn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel(currentStyle); });
        inner.appendChild(btn);

        screenWell.appendChild(scanlines);
        screenWell.appendChild(scanBeam);
        screenWell.appendChild(glassReflect);
        screenWell.appendChild(inner);
        dock.appendChild(screenWell);
    }

    /** Lux Dock 内部构建（珠宝柜）*/
    function buildLuxDock(dock, metrics) {
        // 拖拽手柄
        const handle = document.createElement('div');
        handle.className = 'lux-dock-handle';
        handle.title = t('drag_move');
        for (let i = 0; i < 3; i++) {
            const line = document.createElement('span');
            line.className = 'lux-handle-line';
            handle.appendChild(line);
        }
        dock.appendChild(handle);

        // 光学玻璃模块
        metrics.forEach(m => {
            const slot = document.createElement('div');
            slot.className = 'lux-module-slot';
            slot.setAttribute('data-type', m.type);

            const module = document.createElement('div');
            module.className = 'lux-glass-module';

            const icon = document.createElement('span');
            icon.className = 'lux-module-icon';
            icon.textContent = m.icon;

            const info = document.createElement('div');
            info.style.cssText = 'flex:1;display:flex;flex-direction:column;gap:2px;';

            const topRow = document.createElement('div');
            topRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';
            const modLabel = document.createElement('span');
            modLabel.className = 'lux-module-label';
            modLabel.textContent = m.label;
            const modValue = document.createElement('span');
            modValue.className = 'lux-module-value';
            modValue.id = 'lux-chip-' + m.type + '-value';
            modValue.textContent = '--';
            topRow.appendChild(modLabel);
            topRow.appendChild(modValue);

            const miniProg = document.createElement('div');
            miniProg.className = 'lux-mini-progress';
            const progFill = document.createElement('div');
            progFill.className = 'lux-mini-progress-fill';
            progFill.id = 'lux-chip-' + m.type + '-progress';
            progFill.style.width = '0%';
            miniProg.appendChild(progFill);

            info.appendChild(topRow);
            info.appendChild(miniProg);
            module.appendChild(icon);
            module.appendChild(info);
            slot.appendChild(module);
            dock.appendChild(slot);
        });

        // 设置按钮
        const btn = document.createElement('button');
        btn.className = 'lux-settings-btn';
        btn.id = 'lux-settingsBtn';
        btn.title = t('settings_panel');
        btn.textContent = '\u2699';
        btn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel(currentStyle); });
        dock.appendChild(btn);
    }

    /** Cyber Dock 内部构建（Orbital Command 轨道指挥中心 / 微型飞船仪表盘） */
    function buildCyberDock(dock, metrics) {
        // 1. 飞船钛金外壳
        const hull = document.createElement('div');
        hull.className = 'cyber-hull';
        dock.appendChild(hull);

        // 2. 两侧推进翼（机翼）
        const wingLeft = document.createElement('div');
        wingLeft.className = 'cyber-wing left';
        dock.appendChild(wingLeft);
        const wingRight = document.createElement('div');
        wingRight.className = 'cyber-wing right';
        dock.appendChild(wingRight);

        // 3. 系统状态 LED
        const led = document.createElement('div');
        led.className = 'cyber-status-led';
        led.title = t('system_normal');
        dock.appendChild(led);

        // 4. 拖拽手柄
        const handle = document.createElement('div');
        handle.className = 'cyber-handle';
        handle.title = t('drag_move');
        for (let i = 0; i < 4; i++) {
            const ridge = document.createElement('span');
            ridge.className = 'cyber-handle-ridge';
            handle.appendChild(ridge);
        }
        dock.appendChild(handle);

        // 5. 内凹驾驶舱（容纳六个数据舱）
        const cockpit = document.createElement('div');
        cockpit.className = 'cyber-cockpit';

        metrics.forEach(m => {
            const pod = document.createElement('div');
            pod.className = 'cyber-pod';
            pod.setAttribute('data-type', m.type);

            const icon = document.createElement('span');
            icon.className = 'cyber-pod-icon';
            icon.textContent = m.icon;

            const label = document.createElement('span');
            label.className = 'cyber-pod-label';
            label.textContent = m.label;

            const valueWrap = document.createElement('div');
            valueWrap.style.display = 'flex';
            valueWrap.style.alignItems = 'baseline';
            valueWrap.style.justifyContent = 'center';
            valueWrap.style.gap = '1px';

            const value = document.createElement('span');
            value.className = 'cyber-pod-value';
            value.id = 'cyber-chip-' + m.type + '-value';
            value.textContent = '--';

            const unit = document.createElement('span');
            unit.className = 'cyber-pod-unit';
            unit.textContent = m.type === 'temp' ? '\u00B0C' : (m.type === 'swap' ? 'GB' : '%');

            valueWrap.appendChild(value);
            valueWrap.appendChild(unit);

            const bar = document.createElement('div');
            bar.className = 'cyber-pod-bar';
            const barFill = document.createElement('div');
            barFill.className = 'cyber-pod-bar-fill';
            barFill.id = 'cyber-chip-' + m.type + '-progress';
            barFill.style.width = '0%';
            bar.appendChild(barFill);

            pod.appendChild(icon);
            pod.appendChild(label);
            pod.appendChild(valueWrap);
            pod.appendChild(bar);
            cockpit.appendChild(pod);
        });

        dock.appendChild(cockpit);

        // 6. 设置按钮
        const btn = document.createElement('button');
        btn.className = 'cyber-settings';
        btn.id = 'cyber-settingsBtn';
        btn.title = t('settings_panel');
        btn.textContent = '\u2699';
        btn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel(currentStyle); });
        dock.appendChild(btn);
    }

    // ============================================================
    // Panel DOM 创建 — 为全部5种风格创建控制面板
    // ============================================================

    /**
     * 创建所有5个风格的Panel DOM并挂载到document.body
     * 每个Panel包含：标题栏、指标卡片、详情区、设置区、状态栏
     * 默认隐藏，通过togglePanel()切换可见性
     */
    function createAllPanelPanels() {
        VALID_STYLES.forEach(style => {
            const panel = document.createElement('div');
            panel.id = style + '-panel';
            panel.classList.add('style-hidden');

            switch (style) {
                case 'neu':
                    panel.className = 'neu-panel style-hidden';
                    buildNeuPanel(panel);
                    break;
                case 'ind':
                    panel.className = 'ind-panel style-hidden';
                    buildIndPanel(panel);
                    break;
                case 'retro':
                    panel.className = 'retro-container retro-panel style-hidden';
                    buildRetroPanel(panel);
                    break;
                case 'lux':
                    panel.className = 'lux-panel style-hidden';
                    buildLuxPanel(panel);
                    break;
                case 'cyber':
                    panel.className = 'cyber-panel style-hidden';
                    buildCyberPanel(panel);
                    break;
            }

            document.body.appendChild(panel);
        });

        console.log(`[飞雪监测器] ✅ 已创建 ${VALID_STYLES.length} 个控制面板`);

        // 为所有主题的 section-header 绑定折叠点击事件
        const headerSelectors = [
            '.neu-section-header',
            '.lux-section-header',
            '.cyber-section-header'
        ];
        headerSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(header => {
                header.addEventListener('click', function(e) {
                    e.stopPropagation();
                    this.classList.toggle('collapsed');
                    const toggle = this.querySelector('[class*="toggle"]');
                    if (toggle) {
                        const isCollapsed = this.classList.contains('collapsed');
                        toggle.style.transform = isCollapsed ? 'rotate(-90deg)' : '';
                    }
                });
                header.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        this.click();
                    }
                });
            });
        });
    }

    /** 构建Neu Panel内容 */
    function buildNeuPanel(panel) {
        panel.innerHTML =
            '<div class="neu-panel-header">' +
                '<div class="neu-header-brand">' +
                    '<div class="neu-brand-icon">\u2744</div>' +
                    '<div class="neu-brand-text"><h1>FEIXUE MONITOR</h1><span>v3.25</span></div>' +
                '</div>' +
                '<div class="neu-header-actions">' +
                    '<button class="neu-action-btn" id="neu-minimizeBtn" title="' + t('close') + '">&#x2014;</button>' +
                    '<button class="neu-action-btn neu-close-btn" id="neu-closeBtn" title="' + t('close') + '">&times;</button>' +
                '</div>' +
            '</div>' +
            '<div class="neu-metrics-grid" role="region" aria-label="' + t('core_metrics') + '">' +
                '<div class="neu-metric-card" data-metric="gpu">' +
                    '<div class="neu-metric-label">' + t('gpu') + ' ' + t('load') + '</div>' +
                    '<div class="neu-metric-value"><span id="np-gpu-val">--</span><span class="neu-metric-unit">%</span></div>' +
                    '<svg class="neu-metric-trend" viewBox="0 0 80 24" preserveAspectRatio="none"><polyline fill="none" stroke="#00d4ff" stroke-width="2" points="0,20 12,18 24,19 36,15 48,17 60,14 72,16 80,12"/></svg>' +
                '</div>' +
                '<div class="neu-metric-card" data-metric="cpu">' +
                    '<div class="neu-metric-label">' + t('cpu') + ' ' + t('usage') + '</div>' +
                    '<div class="neu-metric-value"><span id="np-cpu-val">--</span><span class="neu-metric-unit">%</span></div>' +
                    '<svg class="neu-metric-trend" viewBox="0 0 80 24" preserveAspectRatio="none"><polyline fill="none" stroke="#38a169" stroke-width="2" points="0,18 12,16 24,17 36,14 48,15 60,13 72,14 80,11"/></svg>' +
                '</div>' +
                '<div class="neu-metric-card" data-metric="ram">' +
                    '<div class="neu-metric-label">' + t('ram') + '</div>' +
                    '<div class="neu-metric-value"><span id="np-ram-val">--</span><span class="neu-metric-unit">%</span></div>' +
                    '<svg class="neu-metric-trend" viewBox="0 0 80 24" preserveAspectRatio="none"><polyline fill="none" stroke="#805ad5" stroke-width="2" points="0,8 12,9 24,7 36,10 48,8 60,9 72,7 80,6"/></svg>' +
                '</div>' +
            '</div>' +
            // Detail Section 1: GPU & VRAM Details (默认展开)
            '<section class="neu-detail-section">' +
                '<div class="neu-section-header" role="button" tabindex="0" aria-expanded="true">' +
                    '<div class="neu-section-title"><span class="neu-section-icon">\u{1F3AE}</span>' + t('gpu_vram_details') + '</div>' +
                    '<span class="neu-section-toggle">&#x25BC;</span>' +
                '</div>' +
                '<div class="neu-section-content">' +
                    '<div class="neu-progress-row" data-type="gpu">' +
                        '<div class="neu-progress-header">' +
                            '<span class="neu-progress-label"><span class="neu-progress-dot"></span>' + t('core_usage') + '</span>' +
                            '<span class="neu-progress-badge" id="np-gpu-pb-badge">--%</span>' +
                        '</div>' +
                        '<div class="neu-progress-track" role="progressbar"><div class="neu-progress-fill" id="np-gpu-pb" style="width:0%"></div></div>' +
                    '</div>' +
                    '<div class="neu-progress-row" data-type="vram">' +
                        '<div class="neu-progress-header">' +
                            '<span class="neu-progress-label"><span class="neu-progress-dot"></span>' + t('vram_usage') + '</span>' +
                            '<span class="neu-progress-badge" id="np-vram-pb-badge">--%</span>' +
                        '</div>' +
                        '<div class="neu-progress-track" role="progressbar"><div class="neu-progress-fill" id="np-vram-pb" style="width:0%"></div></div>' +
                    '</div>' +
                    '<div class="neu-progress-row" data-type="temp">' +
                        '<div class="neu-progress-header">' +
                            '<span class="neu-progress-label"><span class="neu-progress-dot"></span>' + t('temperature') + '</span>' +
                            '<span class="neu-progress-badge" id="np-temp-pb-badge">--\u00B0C</span>' +
                        '</div>' +
                        '<div class="neu-progress-track" role="progressbar"><div class="neu-progress-fill" id="np-temp-pb" style="width:0%"></div></div>' +
                    '</div>' +
                '</div>' +
            '</section>' +
            // Detail Section 2: System Resources (默认收起)
            '<section class="neu-detail-section">' +
                '<div class="neu-section-header collapsed" role="button" tabindex="0" aria-expanded="false">' +
                    '<div class="neu-section-title"><span class="neu-section-icon">&#x26A1;</span>' + t('system_resources') + '</div>' +
                    '<span class="neu-section-toggle">&#x25BC;</span>' +
                '</div>' +
                '<div class="neu-section-content">' +
                    '<div class="neu-progress-row" data-type="cpu">' +
                        '<div class="neu-progress-header">' +
                            '<span class="neu-progress-label"><span class="neu-progress-dot"></span>' + t('cpu_usage') + '</span>' +
                            '<span class="neu-progress-badge" id="np-cpu-pb-badge">--%</span>' +
                        '</div>' +
                        '<div class="neu-progress-track" role="progressbar"><div class="neu-progress-fill" id="np-cpu-pb" style="width:0%"></div></div>' +
                    '</div>' +
                    '<div class="neu-progress-row" data-type="ram">' +
                        '<div class="neu-progress-header">' +
                            '<span class="neu-progress-label"><span class="neu-progress-dot"></span>' + t('physical_ram') + '</span>' +
                            '<span class="neu-progress-badge" id="np-ram-pb-badge">--%</span>' +
                        '</div>' +
                        '<div class="neu-progress-track" role="progressbar"><div class="neu-progress-fill" id="np-ram-pb" style="width:0%"></div></div>' +
                    '</div>' +
                    '<div class="neu-progress-row" data-type="swap">' +
                        '<div class="neu-progress-header">' +
                            '<span class="neu-progress-label"><span class="neu-progress-dot"></span>' + t('swap_memory') + '</span>' +
                            '<span class="neu-progress-badge" id="np-swap-pb-badge">-- GB</span>' +
                        '</div>' +
                        '<div class="neu-progress-track" role="progressbar"><div class="neu-progress-fill" id="np-swap-pb" style="width:0%"></div></div>' +
                    '</div>' +
                '</div>' +
            '</section>' +
            // Detail Section 3: I/O & Network (默认收起)
            '<section class="neu-detail-section">' +
                '<div class="neu-section-header collapsed" role="button" tabindex="0" aria-expanded="false">' +
                    '<div class="neu-section-title"><span class="neu-section-icon">\u{1F5A5}</span>' + t('io_network') + '</div>' +
                    '<span class="neu-section-toggle">&#x25BC;</span>' +
                '</div>' +
                '<div class="neu-section-content">' +
                    '<div class="neu-details-grid">' +
                        '<div class="neu-detail-item">' +
                            '<div class="neu-detail-left"><span class="neu-detail-icon">\u{1F4BE}</span><span>' + t('disks_io') + '</span></div>' +
                            '<span class="neu-detail-right" id="np-disk-detail">R: -- / W: -- MB/s</span>' +
                        '</div>' +
                        '<div class="neu-detail-item">' +
                            '<div class="neu-detail-left"><span class="neu-detail-icon">\u{1F310}</span><span>' + t('network_io') + '</span></div>' +
                            '<span class="neu-detail-right" id="np-net-detail">\u2191 -- / \u2193 -- MB/s</span>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</section>' +
            // Settings Section
            '<div class="neu-settings-section">' +
                '<div class="neu-settings-group">' +
                    // Sound Alert Toggle
                    '<div class="neu-setting-row">' +
                        '<label class="neu-setting-label" for="neu-soundToggle">' + t('sound_alert') + '</label>' +
                        '<button class="neu-toggle-switch active" id="neu-soundToggle" role="switch" aria-checked="true" aria-label="' + t('sound_alert') + '"><span class="neu-toggle-thumb"></span></button>' +
                    '</div>' +
                    // Drag Mode Toggle
                    '<div class="neu-setting-row">' +
                        '<label class="neu-setting-label" for="neu-dragToggle">' + t('drag_mode') + '</label>' +
                        '<button class="neu-toggle-switch" id="neu-dragToggle" role="switch" aria-checked="false" aria-label="' + t('drag_mode') + '"><span class="neu-toggle-thumb"></span></button>' +
                    '</div>' +
                    // Theme Selection
                    '<div class="neu-setting-row"><label class="neu-setting-label">' + t('theme') + '</label>' +
                        '<div class="neu-radio-group" role="radiogroup" aria-label="' + t('theme') + '">' +
                            VALID_STYLES.map((s,i) => '<button class="neu-radio-btn'+(s==='neu'?' active':'')+'" data-target="'+s+'" role="radio">'+s.charAt(0).toUpperCase()+s.slice(1)+'</button>').join('') +
                        '</div>' +
                    '</div>' +
                    // Color Selection
                    '<div class="neu-setting-row"><label class="neu-setting-label">' + t('color') + '</label>' +
                        '<div class="neu-radio-group" role="radiogroup" aria-label="' + t('color') + '">' +
                            COLOR_WHITELIST.map(c => '<button class="neu-radio-btn'+(c==='aurora'?' active':'')+'" data-color="'+c+'" role="radio">'+c.charAt(0).toUpperCase()+c.slice(1)+'</button>').join('') +
                        '</div>' +
                    '</div>' +
                '</div>' +
            '</div>' +
            // Footer
            '<footer class="neu-panel-footer">' +
                '<div class="neu-footer-left"><span class="neu-status-dot"></span><span id="np-source-text">' + t('plugin_active') + '</span></div>' +
                '<span>v3.25 Build 2026.06.22</span>' +
            '</footer>';

        // 绑定关闭按钮
        const closeBtn = panel.querySelector('#neu-closeBtn');
        if (closeBtn) closeBtn.addEventListener('click', () => togglePanel('neu'));

        // 绑定最小化按钮
        const minimizeBtn = panel.querySelector('#neu-minimizeBtn');
        if (minimizeBtn) {
            minimizeBtn.addEventListener('click', function() {
                const neuPanel = document.getElementById('neu-panel');
                if (neuPanel) {
                    neuPanel.style.transition = 'all 0.3s ease';
                    neuPanel.classList.toggle('neu-minimized');
                }
            });
        }

        // 绑定风格按钮
        panel.querySelectorAll('[data-target]').forEach(btn => {
            btn.addEventListener('click', () => switchStyle(btn.dataset.target));
        });

        // 绑定颜色按钮
        panel.querySelectorAll('[data-color]').forEach(btn => {
            btn.addEventListener('click', () => switchColor(btn.dataset.color));
        });

        // Sound Alert toggle
        const soundToggle = panel.querySelector('#neu-soundToggle');
        if (soundToggle) {
            soundToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Neu Sound Alert:', isActive);
                if (typeof window.FxMonitorSound !== 'undefined') {
                    window.FxMonitorSound.setEnabled(isActive);
                    syncSoundToggles();
                }
            });
            // 防止拖拽系统拦截toggle点击
            soundToggle.addEventListener('mousedown', e => e.stopPropagation());
            soundToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }

        // Drag Mode toggle — 锁定位置语义（OFF=锁定不可拖拽, ON=允许拖拽）
        const dragToggle = panel.querySelector('#neu-dragToggle');
        if (dragToggle) {
            dragToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                isDragEnabled = isActive;
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Neu Drag Mode:', isActive);
                const dock = document.getElementById('neu-dock');
                if (dock) {
                    const handle = dock.querySelector('.neu-dock-handle');
                    if (handle) handle.style.pointerEvents = isActive ? 'auto' : 'none';
                    if (!isActive) resetDockPosition(dock); // 关闭 Drag Mode 时 dock 自动归位
                }
            });
            // 防止拖拽系统拦截toggle点击
            dragToggle.addEventListener('mousedown', e => e.stopPropagation());
            dragToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }
    }

    /** 构建Ind Panel内容 */
    function buildIndPanel(panel) {
        panel.innerHTML =
            // 四角螺丝
            '<div class="ind-screw tl"></div><div class="ind-screw tr"></div><div class="ind-screw bl"></div><div class="ind-screw br"></div>' +
            // 模块1: 风格选择窗口
            '<div class="ind-recess-window"><div class="ind-window-title">// ' + t('theme') + '</div><div class="ind-style-buttons">' +
                VALID_STYLES.map(s => '<button class="ind-style-btn'+(s==='ind'?' active':'')+'" data-target="'+s+'">'+t('theme_name_'+s)+'</button>').join('') +
            '</div></div>' +
            // 模块2: 色彩主题色块
            '<div class="ind-recess-window"><div class="ind-window-title">// ' + t('color') + '</div><div class="ind-theme-swatches">' +
                '<div class="ind-swatch cyan active" title="' + t('color') + '" data-color="cyan"></div>' +
                '<div class="ind-swatch amber" title="' + t('color') + '" data-color="amber"></div>' +
                '<div class="ind-swatch red" title="' + t('color') + '" data-color="red"></div>' +
                '<div class="ind-swatch green" title="' + t('color') + '" data-color="green"></div>' +
                '<div class="ind-swatch purple" title="' + t('color') + '" data-color="purple"></div>' +
            '</div></div>' +
            // 模块3: 系统负载详情进度条
            '<div class="ind-recess-window"><div class="ind-window-title">// ' + t('system_resources') + '</div><div class="ind-detail-meter">' +
                '<div class="ind-detail-row"><span class="ind-detail-label">' + t('gpu') + '</span><div class="ind-detail-bar-container"><div class="ind-detail-bar gpu" id="idp-gpu-bar" style="width:0%"></div></div><span class="ind-detail-value" id="idp-gpu-val" style="color:var(--ind-accent-color, #00ddff);">--%</span></div>' +
                '<div class="ind-detail-row"><span class="ind-detail-label">' + t('vram') + '</span><div class="ind-detail-bar-container"><div class="ind-detail-bar vram" id="idp-vram-bar" style="width:0%"></div></div><span class="ind-detail-value" id="idp-vram-val" style="color:var(--ind-accent-color, #00ddff);">--%</span></div>' +
                '<div class="ind-detail-row"><span class="ind-detail-label">' + t('cpu') + '</span><div class="ind-detail-bar-container"><div class="ind-detail-bar cpu" id="idp-cpu-bar" style="width:0%"></div></div><span class="ind-detail-value" id="idp-cpu-val" style="color:var(--ind-accent-color, #00ddff);">--%</span></div>' +
                '<div class="ind-detail-row"><span class="ind-detail-label">' + t('ram') + '</span><div class="ind-detail-bar-container"><div class="ind-detail-bar ram" id="idp-ram-bar" style="width:0%"></div></div><span class="ind-detail-value" id="idp-ram-val" style="color:var(--ind-accent-color, #00ddff);">--%</span></div>' +
                '<div class="ind-detail-row"><span class="ind-detail-label">' + t('swap') + '</span><div class="ind-detail-bar-container"><div class="ind-detail-bar swap" id="idp-swap-bar" style="width:0%"></div></div><span class="ind-detail-value" id="idp-swap-val" style="color:var(--ind-accent-color, #00ddff);">-- GB</span></div>' +
            '</div></div>' +
            // 模块4: I/O 监控
            '<div class="ind-recess-window"><div class="ind-window-title">// ' + t('io_network') + '</div><div class="ind-io-section">' +
                '<div class="ind-io-box"><div class="ind-io-title"><span class="ind-led green"></span>' + t('disks_io') + '</div><div class="ind-io-stats">' +
                    '<div class="ind-io-row"><span class="ind-io-direction up">' + t('disk_read') + '</span><span class="ind-io-value" id="idp-disk-read">-- MB/s</span></div>' +
                    '<div class="ind-io-row"><span class="ind-io-direction down">' + t('disk_write') + '</span><span class="ind-io-value" id="idp-disk-write">-- MB/s</span></div>' +
                '</div></div>' +
                '<div class="ind-io-box"><div class="ind-io-title"><span class="ind-led amber"></span>' + t('network_io') + '</div><div class="ind-io-stats">' +
                    '<div class="ind-io-row"><span class="ind-io-direction down">' + t('net_down') + '</span><span class="ind-io-value" id="idp-net-down">-- MB/s</span></div>' +
                    '<div class="ind-io-row"><span class="ind-io-direction up">' + t('net_up') + '</span><span class="ind-io-value" id="idp-net-up">-- MB/s</span></div>' +
                '</div></div>' +
            '</div></div>' +
            // 模块5: 控制选项 Toggle
            '<div class="ind-recess-window"><div class="ind-window-title">// ' + t('settings') + '</div><div class="ind-toggle-section">' +
                '<div class="ind-toggle-row"><span class="ind-toggle-label">' + t('sound_alert') + '</span><button class="ind-toggle active" id="ind-soundToggle" role="switch" aria-checked="true"><div class="ind-toggle-knob"></div></button></div>' +
                '<div class="ind-toggle-row"><span class="ind-toggle-label">' + t('drag_mode') + '</span><button class="ind-toggle" id="ind-dragToggle" role="switch" aria-checked="false"><div class="ind-toggle-knob"></div></button></div>' +
            '</div></div>' +
            // 模块6: 系统信息
            '<div class="ind-recess-window"><div class="ind-window-title">// ' + t('system') + '</div><div class="ind-info-section">' +
                '<div class="ind-version"><span><span class="ind-led green"></span>FEIXUE MONITOR v3.25</span><span class="ind-version-badge">STABLE</span></div>' +
                '<div class="ind-amd-smi" id="ind-amd-smi-info">&gt; amdsmi --info<br/>GPU: ' + t('detecting') + '<br/>Driver: --<br/>VBIOS: --<br/>' + t('temp') + ': --°C | Power: --W<br/>Clock: -- MHz / -- MHz</div>' +
            '</div></div>';

        // 事件绑定: [data-target] 按钮 → switchStyle()
        panel.querySelectorAll('[data-target]').forEach(btn => {
            btn.addEventListener('click', () => switchStyle(btn.dataset.target));
        });

        // 事件绑定: .ind-swatch → 切换 CSS 变量
        panel.querySelectorAll('.ind-swatch').forEach(swatch => {
            swatch.addEventListener('click', function() {
                switchColor(this.dataset.color);
            });
        });

        // 事件绑定: #ind-soundToggle → 绑定音频系统
        const soundToggle = panel.querySelector('#ind-soundToggle');
        if (soundToggle) {
            soundToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Ind Sound Alert:', isActive);
                if (typeof window.FxMonitorSound !== 'undefined') {
                    window.FxMonitorSound.setEnabled(isActive);
                    syncSoundToggles();
                }
            });
            // 防止拖拽系统拦截toggle点击
            soundToggle.addEventListener('mousedown', e => e.stopPropagation());
            soundToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }

        // 事件绑定: #ind-dragToggle → 锁定位置语义
        const dragToggle = panel.querySelector('#ind-dragToggle');
        if (dragToggle) {
            dragToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                isDragEnabled = isActive;
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Ind Drag Mode:', isActive);
                const dock = document.getElementById('ind-dock');
                if (dock) {
                    const handle = dock.querySelector('.ind-drag-handle');
                    if (handle) handle.style.pointerEvents = isActive ? 'auto' : 'none';
                    if (!isActive) resetDockPosition(dock); // 关闭 Drag Mode 时 dock 自动归位
                }
            });
            // 防止拖拽系统拦截toggle点击
            dragToggle.addEventListener('mousedown', e => e.stopPropagation());
            dragToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }
    }

    /** 构建Retro Panel内容 - 完整6模块版 */
    function buildRetroPanel(panel) {
        panel.innerHTML =
            '<div class="retro-screw screw-tl"></div><div class="retro-screw screw-tr"></div>' +
            '<div class="retro-screw screw-bl"></div><div class="retro-screw screw-br"></div>' +
            '<div class="retro-screen-well"><div class="retro-scanlines"></div>' +
            '<div class="retro-scan-beam" style="animation-delay:1s;"></div>' +
            '<div class="retro-glass-reflection"></div>' +
            '<div class="retro-panel-inner retro-flicker">' +
            // 模块1: Style Buttons (大写英文)
            '<div class="retro-section"><div class="retro-style-row">' +
                VALID_STYLES.map(s => '<button class="retro-style-btn'+(s==='retro'?' active':'')+'" data-target="'+s+'">'+s.toUpperCase()+'</button>').join('') +
            '</div></div>' +
            // 模块2: Color Palette (磷光色块)
            '<div class="retro-section"><div class="retro-color-palette">' +
                '<div class="retro-color-block color-green active" data-color="green" title="P1 PHOSPHOR GREEN"></div>' +
                '<div class="retro-color-block color-purple" data-color="purple" title="P43 RARE EARTH PURPLE"></div>' +
                '<div class="retro-color-block color-amber" data-color="amber" title="P22 AMBER"></div>' +
                '<div class="retro-color-block color-cyan" data-color="cyan" title="P39 CYAN"></div>' +
                '<div class="retro-color-block color-pink" data-color="pink" title="CUSTOM PINK"></div>' +
            '</div></div>' +
            // 模块3: VFD Progress Bars
            '<div class="retro-section retro-panel-vfd-grid"><div class="retro-progress-group">' +
                '<div class="reto-progress-item"><div class="reto-progress-header"><span class="reto-progress-label">' + t('gpu') + ' ' + t('load') + '</span><span class="reto-progress-value" id="rp-gpu-val">--%</span></div><div class="reto-vfd-track"><div class="reto-vfd-fill" id="rp-gpu-pb" style="width:0%"></div></div></div>' +
                '<div class="reto-progress-item"><div class="reto-progress-header"><span class="reto-progress-label">' + t('vram') + '</span><span class="reto-progress-value" id="rp-vram-val">--%</span></div><div class="reto-vfd-track"><div class="reto-vfd-fill" id="rp-vram-pb" style="width:0%"></div></div></div>' +
                '<div class="reto-progress-item"><div class="reto-progress-header"><span class="reto-progress-label">' + t('cpu') + ' ' + t('usage_rate') + '</span><span class="reto-progress-value" id="rp-cpu-val">--%</span></div><div class="reto-vfd-track"><div class="reto-vfd-fill" id="rp-cpu-pb" style="width:0%"></div></div></div>' +
                '<div class="reto-progress-item"><div class="reto-progress-header"><span class="reto-progress-label">' + t('ram') + '</span><span class="reto-progress-value" id="rp-ram-val">--%</span></div><div class="reto-vfd-track"><div class="reto-vfd-fill" id="rp-ram-pb" style="width:0%"></div></div></div>' +
                '<div class="reto-progress-item"><div class="reto-progress-header"><span class="reto-progress-label">' + t('swap') + '</span><span class="reto-progress-value" id="rp-swap-val">--%</span></div><div class="reto-vfd-track"><div class="reto-vfd-fill" id="rp-swap-pb" style="width:0%"></div></div></div>' +
            '</div></div>' +
            // 模块4: I/O Cards
            '<div class="retro-section"><div class="retro-io-grid">' +
                '<div class="retro-io-card"><div class="retro-io-title">' + t('disks_io') + '</div><div class="retro-io-values"><div class="retro-io-line"><span>' + t('disk_read') + '</span><span id="rp-disk-read">-- MB/s</span></div><div class="retro-io-line"><span>' + t('disk_write') + '</span><span id="rp-disk-write">-- MB/s</span></div></div></div>' +
                '<div class="retro-io-card"><div class="retro-io-title">' + t('network_io') + '</div><div class="retro-io-values"><div class="retro-io-line"><span>' + t('net_down') + '</span><span id="rp-net-down">-- MB/s</span></div><div class="retro-io-line"><span>' + t('net_up') + '</span><span id="rp-net-up">-- MB/s</span></div></div></div>' +
            '</div></div>' +
            // 模块5: Control Toggles
            '<div class="retro-section"><div class="retro-control-row" style="display:flex;align-items:center;justify-content:center;gap:24px;"><label class="retro-control-label">' + t('sound_alert') + '</label><button class="retro-toggle-switch active" id="retro-soundToggle" role="switch" aria-checked="true"><span class="retro-toggle-thumb"></span></button><label class="retro-control-label">' + t('drag_mode') + '</label><button class="retro-toggle-switch" id="retro-dragToggle" role="switch" aria-checked="false"><span class="retro-toggle-thumb"></span></button></div></div>' +
            // V19 Footer
            '<div style="text-align:center;padding:8px 0;font-family:var(--mono-display);font-size:11px;color:var(--retro-phosphor-dim, var(--retro-dim));line-height:1.6;"><div>FEIXUE MONITOR v3.25</div><div>' + (FXM_LANG === 'zh' ? '复古终端版' : 'RETRO TERMINAL') + '</div><div>Build 2026.06.22</div></div>' +
            '<div class="retro-source-text" id="retro-source-text">[ AMD SMI ]</div>' +
            '</div></div>';

        // 事件绑定: [data-target] 按钮 → switchStyle()
        panel.querySelectorAll('[data-target]').forEach(btn => {
            btn.addEventListener('click', () => switchStyle(btn.dataset.target));
        });

        // Color blocks
        panel.querySelectorAll('.retro-color-block').forEach(block => {
            block.addEventListener('click', function() {
                switchColor(this.dataset.color);
            });
        });

        // Sound Toggle
        const st = panel.querySelector('#retro-soundToggle');
        if (st) st.addEventListener('click', function() {
            this.classList.toggle('active');
            const isActive = this.classList.contains('active');
            this.setAttribute('aria-checked', isActive.toString());
            console.log('[飞雪监测器] Retro Sound Alert:', isActive);
            if (window.FxMonitorSound) window.FxMonitorSound.setEnabled(isActive);
            syncSoundToggles();
        });
        // 防止拖拽系统拦截toggle点击
        if (st) {
            st.addEventListener('mousedown', e => e.stopPropagation());
            st.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }

        // Drag Toggle
        const dt = panel.querySelector('#retro-dragToggle');
        if (dt) dt.addEventListener('click', function() {
            this.classList.toggle('active');
            const isActive = this.classList.contains('active');
            isDragEnabled = isActive;
            this.setAttribute('aria-checked', isActive.toString());
            console.log('[飞雪监测器] Retro Drag Mode:', isActive);
            const dock = document.getElementById('retro-dock');
            if (dock) {
                const handle = dock.querySelector('.retro-drag-handle');
                if (handle) handle.style.pointerEvents = isActive ? 'auto' : 'none';
                if (!isActive) resetDockPosition(dock); // 关闭 Drag Mode 时 dock 自动归位
            }
        });
        // 防止拖拽系统拦截toggle点击
        if (dt) {
            dt.addEventListener('mousedown', e => e.stopPropagation());
            dt.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }
    }

    /** 构建Lux Panel内容 */
    function buildLuxPanel(panel) {
        panel.innerHTML =
            '<div class="lux-panel-header"><div class="lux-brand-text"><h1>SYSTEM MONITOR</h1><span>v3.25</span></div>' +
                '<div class="lux-header-actions"><button class="lux-action-btn lux-close-btn" title="' + t('close') + '">&times;</button></div></div>' +
            '<div class="lux-metrics-grid"><div class="lux-metric-card"><div class="lux-metric-label">' + t('gpu') + ' ' + t('load') + '</div><div class="lux-metric-value"><span id="lp-gpu-val">--</span>%</div></div>' +
                '<div class="lux-metric-card"><div class="lux-metric-label">' + t('cpu') + ' ' + t('usage') + '</div><div class="lux-metric-value"><span id="lp-cpu-val">--</span>%</div></div>' +
                '<div class="lux-metric-card"><div class="lux-metric-label">' + t('ram') + '</div><div class="lux-metric-value"><span id="lp-ram-val">--</span>%</div></div></div>' +
            '<div class="lux-detail-section"><div class="lux-section-header"><div class="lux-section-title">' + t('performance') + '</div></div><div class="lux-section-content">' +
                '<div class="lux-progress-row"><div class="lux-progress-header"><span class="lux-progress-label">' + t('core_usage') + '</span><span class="lux-progress-badge" id="lp-gpu-badge">--%</span></div>' +
                    '<div class="lux-progress-track"><div class="lux-progress-fill" id="lp-gpu-pb" style="width:0%"></div></div></div>' +
                '<div class="lux-progress-row"><div class="lux-progress-header"><span class="lux-progress-label">' + t('vram_usage') + '</span><span class="lux-progress-badge" id="lp-vram-badge">--%</span></div>' +
                    '<div class="lux-progress-track"><div class="lux-progress-fill" id="lp-vram-pb" style="width:0%"></div></div></div>' +
                '<div class="lux-progress-row"><div class="lux-progress-header"><span class="lux-progress-label">' + t('temperature') + '</span><span class="lux-progress-badge" id="lp-temp-badge">--\u00B0C</span></div>' +
                    '<div class="lux-progress-track"><div class="lux-progress-fill" id="lp-temp-pb" style="width:0%"></div></div></div>' +
            '</div></div>' +
            '<div class="lux-detail-section"><div class="lux-section-header collapsed"><div class="lux-section-title">' + t('memory') + '</div></div><div class="lux-section-content">' +
                '<div class="lux-progress-row"><div class="lux-progress-header"><span class="lux-progress-label">' + t('ram') + '</span><span class="lux-progress-badge" id="lp-ram-badge">--%</span></div>' +
                    '<div class="lux-progress-track"><div class="lux-progress-fill" id="lp-ram-pb" style="width:0%"></div></div></div>' +
                '<div class="lux-progress-row"><div class="lux-progress-header"><span class="lux-progress-label">' + t('swap') + '</span><span class="lux-progress-badge" id="lp-swap-badge">-- GB</span></div>' +
                    '<div class="lux-progress-track"><div class="lux-progress-fill" id="lp-swap-pb" style="width:0%"></div></div></div>' +
            '</div></div>' +
            '<section class="lux-detail-section"><div class="lux-section-header collapsed" role="button" tabindex="0" aria-expanded="false"><div class="lux-section-title"><span class="lux-section-icon">&#x1F5A5;</span>' + t('system') + '</div><span class="lux-section-toggle">&#x25BC;</span></div><div class="lux-section-content"><div class="lux-details-grid">' +
                '<div class="lux-detail-item"><div class="lux-detail-left"><span class="lux-detail-icon">&#x1F4BE;</span><span>' + t('disks_io') + '</span></div><span class="lux-detail-right" id="lp-disk-detail">R: -- / W: -- MB/s</span></div>' +
                '<div class="lux-detail-item"><div class="lux-detail-left"><span class="lux-detail-icon">&#x1F310;</span><span>' + t('network_io') + '</span></div><span class="lux-detail-right" id="lp-net-detail">↑ -- / ↓ -- MB/s</span></div>' +
            '</div></div></section>' +
            '<div class="lux-settings-area"><div class="lux-style-chips">' +
                VALID_STYLES.map(s => '<button class="lux-style-chip'+(s==='lux'?' active':'')+'" data-target="'+s+'">'+s.charAt(0).toUpperCase()+s.slice(1)+'</button>').join('') +
            '</div>' +
            '<div class="lux-color-chips" style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">' +
                COLOR_WHITELIST.map(c => '<button class="lux-style-chip'+(c==='aurora'?' active':'')+'" data-color="'+c+'" style="font-size:10px;padding:4px 10px;background:'+COLOR_MAPS[c].base+';color:#4a5568;border-radius:8px;border:none;cursor:pointer;font-weight:600;">'+c.charAt(0).toUpperCase()+c.slice(1)+'</button>').join('') +
            '</div></div>' +
            '<div class="lux-settings-area" style="margin-top:8px;"><div style="display:flex;flex-direction:column;gap:10px;">' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:rgba(212,175,55,0.08);border-radius:10px;border:1px solid rgba(212,175,55,0.2);"><span style="color:#d4af37;font-size:11px;font-weight:600;">' + t('sound_alert') + '</span>' +
                    '<button class="lux-toggle-switch active" id="lux-soundToggle" role="switch" aria-checked="true" aria-label="' + t('sound_alert') + '"><span class="lux-toggle-thumb"></span></button>' +
                '</div>' +
                '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:rgba(212,175,55,0.08);border-radius:10px;border:1px solid rgba(212,175,55,0.2);"><span style="color:#d4af37;font-size:11px;font-weight:600;">' + t('drag_mode') + '</span>' +
                    '<button class="lux-toggle-switch" id="lux-dragToggle" role="switch" aria-checked="false" aria-label="' + t('drag_mode') + '"><span class="lux-toggle-thumb"></span></button>' +
                '</div>' +
            '</div></div>' +
            '<footer class="lux-footer"><span id="lux-source-text">' + t('plugin_active') + '</span><span>v3.25 Build 2026.06.22</span></footer>';

        panel.querySelector('.lux-close-btn').addEventListener('click', () => togglePanel('lux'));
        panel.querySelectorAll('[data-target]').forEach(btn => {
            btn.addEventListener('click', () => switchStyle(btn.dataset.target));
        });
        panel.querySelectorAll('[data-color]').forEach(btn => {
            btn.addEventListener('click', () => switchColor(btn.dataset.color));
        });

        // Sound Alert toggle
        const soundToggle = panel.querySelector('#lux-soundToggle');
        if (soundToggle) {
            soundToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Lux Sound Alert:', isActive);
                if (typeof window.FxMonitorSound !== 'undefined') {
                    window.FxMonitorSound.setEnabled(isActive);
                    syncSoundToggles();
                }
            });
            // 防止拖拽系统拦截toggle点击
            soundToggle.addEventListener('mousedown', e => e.stopPropagation());
            soundToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }

        // Drag Mode toggle — 锁定位置语义
        const dragToggle = panel.querySelector('#lux-dragToggle');
        if (dragToggle) {
            dragToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                isDragEnabled = isActive;
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Lux Drag Mode:', isActive);
                const dock = document.getElementById('lux-dock');
                if (dock) {
                    const handle = dock.querySelector('.lux-dock-handle');
                    if (handle) handle.style.pointerEvents = isActive ? 'auto' : 'none';
                    if (!isActive) resetDockPosition(dock); // 关闭 Drag Mode 时 dock 自动归位
                }
            });
            // 防止拖拽系统拦截toggle点击
            dragToggle.addEventListener('mousedown', e => e.stopPropagation());
            dragToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }
    }

    /** 构建Cyber Panel内容（Orbital Command 轨道指挥中心） */
    function buildCyberPanel(panel) {
        // 钛金主题色卡，与 switchColor cyberTones 保持一致
        const cyberChipColors = {
            aurora:   '#00f0ff',
            ocean:    '#00b8d4',
            sunset:   '#ff6b35',
            forest:   '#00c853',
            midnight: '#d500f9'
        };

        panel.innerHTML =
            '<div class="cyber-panel-header">' +
                '<span class="cyber-panel-title">SYSTEM MONITOR</span>' +
                '<div style="display:flex;align-items:center;gap:10px;">' +
                    '<span class="cyber-panel-clock" id="cyber-clock">--:--:--</span>' +
                    '<button class="cyber-mode-btn" id="cyber-closeBtn" title="' + t('close') + '" aria-label="' + t('close') + '">&#x2715;</button>' +
                '</div>' +
            '</div>' +
            '<div class="cyber-metrics-grid">' +
                '<div class="cyber-metric-card" data-metric="gpu"><div class="cyber-metric-label">' + t('gpu') + ' ' + t('load') + '</div><div class="cyber-metric-value"><span id="cp-gpu-val">--</span><span class="cyber-metric-unit">%</span></div></div>' +
                '<div class="cyber-metric-card" data-metric="cpu"><div class="cyber-metric-label">' + t('cpu') + ' ' + t('usage') + '</div><div class="cyber-metric-value"><span id="cp-cpu-val">--</span><span class="cyber-metric-unit">%</span></div></div>' +
                '<div class="cyber-metric-card" data-metric="ram"><div class="cyber-metric-label">' + t('ram') + '</div><div class="cyber-metric-value"><span id="cp-ram-val">--</span><span class="cyber-metric-unit">%</span></div></div>' +
            '</div>' +
            '<div class="cyber-detail-section">' +
                '<div class="cyber-section-header" role="button" tabindex="0" aria-expanded="true"><div class="cyber-section-title"><span class="cyber-section-icon">&#x25B6;</span>' + t('performance') + '</div><span class="cyber-section-toggle">&#x25BC;</span></div>' +
                '<div class="cyber-section-content">' +
                    '<div class="cyber-progress-row" data-type="gpu"><div class="cyber-progress-header"><span class="cyber-progress-label"><span class="cyber-progress-dot"></span>' + t('core_usage') + '</span><span class="cyber-progress-badge" id="cp-gpu-badge">--%</span></div><div class="cyber-progress-track"><div class="cyber-progress-fill" id="cp-gpu-pb" style="width:0%"></div></div></div>' +
                    '<div class="cyber-progress-row" data-type="vram"><div class="cyber-progress-header"><span class="cyber-progress-label"><span class="cyber-progress-dot"></span>' + t('vram_usage') + '</span><span class="cyber-progress-badge" id="cp-vram-badge">--%</span></div><div class="cyber-progress-track"><div class="cyber-progress-fill" id="cp-vram-pb" style="width:0%"></div></div></div>' +
                    '<div class="cyber-progress-row" data-type="temp"><div class="cyber-progress-header"><span class="cyber-progress-label"><span class="cyber-progress-dot"></span>' + t('temperature') + '</span><span class="cyber-progress-badge" id="cp-temp-badge">--\u00B0C</span></div><div class="cyber-progress-track"><div class="cyber-progress-fill" id="cp-temp-pb" style="width:0%"></div></div></div>' +
                '</div>' +
            '</div>' +
            '<div class="cyber-detail-section">' +
                '<div class="cyber-section-header collapsed" role="button" tabindex="0" aria-expanded="false"><div class="cyber-section-title"><span class="cyber-section-icon">&#x1F4E0;</span>' + t('memory') + '</div><span class="cyber-section-toggle">&#x25BC;</span></div>' +
                '<div class="cyber-section-content">' +
                    '<div class="cyber-progress-row" data-type="cpu"><div class="cyber-progress-header"><span class="cyber-progress-label"><span class="cyber-progress-dot"></span>' + t('cpu_usage') + '</span><span class="cyber-progress-badge" id="cp-cpu-badge">--%</span></div><div class="cyber-progress-track"><div class="cyber-progress-fill" id="cp-cpu-pb" style="width:0%"></div></div></div>' +
                    '<div class="cyber-progress-row" data-type="swap"><div class="cyber-progress-header"><span class="cyber-progress-label"><span class="cyber-progress-dot"></span>' + t('swap') + '</span><span class="cyber-progress-badge" id="cp-swap-badge">-- GB</span></div><div class="cyber-progress-track"><div class="cyber-progress-fill" id="cp-swap-pb" style="width:0%"></div></div></div>' +
                '</div>' +
            '</div>' +
            '<section class="cyber-detail-section">' +
                '<div class="cyber-section-header collapsed" role="button" tabindex="0" aria-expanded="false"><div class="cyber-section-title"><span class="cyber-section-icon">&#x1F5A5;</span>' + t('system') + '</div><span class="cyber-section-toggle">&#x25BC;</span></div>' +
                '<div class="cyber-section-content"><div class="cyber-details-grid">' +
                    '<div class="cyber-detail-item"><div class="cyber-detail-left"><span class="cyber-detail-icon">&#x1F4BE;</span><span>' + t('disks_io') + '</span></div><span class="cyber-detail-right" id="cp-disk-detail">R: -- / W: -- MB/s</span></div>' +
                    '<div class="cyber-detail-item"><div class="cyber-detail-left"><span class="cyber-detail-icon">&#x1F310;</span><span>' + t('network_io') + '</span></div><span class="cyber-detail-right" id="cp-net-detail">↑ -- / ↓ -- MB/s</span></div>' +
                '</div></div>' +
            '</section>' +
            '<div class="cyber-control-bar"><span class="cyber-mode-label">' + t('theme') + ':</span>' +
                VALID_STYLES.map(s => '<button class="cyber-mode-btn'+(s==='cyber'?' active':'')+'" data-target="'+s+'">'+s.toUpperCase()+'</button>').join('') +
            '</div>' +
            '<div class="cyber-color-bar"><span class="cyber-mode-label">' + t('color') + ':</span>' +
                COLOR_WHITELIST.map(c => '<button class="cyber-color-btn'+(c==='aurora'?' active':'')+'" data-color="'+c+'" style="--chip-color:'+(cyberChipColors[c] || '#00f0ff')+'">'+c.toUpperCase()+'</button>').join('') +
            '</div>' +
            '<div class="cyber-controls-section"><div class="cyber-control-group">' +
                '<div class="cyber-control-row"><label class="cyber-control-label" for="cyber-soundToggle">' + t('sound_alert') + '</label>' +
                    '<button class="cyber-toggle-switch active" id="cyber-soundToggle" role="switch" aria-checked="true" aria-label="' + t('sound_alert') + '"><span class="cyber-toggle-thumb"></span></button>' +
                '</div>' +
                '<div class="cyber-control-row"><label class="cyber-control-label" for="cyber-dragToggle">' + t('drag_mode') + '</label>' +
                    '<button class="cyber-toggle-switch" id="cyber-dragToggle" role="switch" aria-checked="false" aria-label="' + t('drag_mode') + '"><span class="cyber-toggle-thumb"></span></button>' +
                '</div>' +
            '</div></div>' +
            '<div class="cyber-status-bar"><span id="cyber-source-text">' + t('plugin_active') + '</span><span>v3.25 Build 2026.06.22</span></div>';

        // 主题切换按钮
        panel.querySelectorAll('[data-target]').forEach(btn => {
            btn.addEventListener('click', () => switchStyle(btn.dataset.target));
        });

        // 颜色切换按钮
        panel.querySelectorAll('[data-color]').forEach(btn => {
            btn.addEventListener('click', () => switchColor(btn.dataset.color));
        });

        // 关闭面板按钮
        const closeBtn = panel.querySelector('#cyber-closeBtn');
        if (closeBtn) {
            closeBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePanel('cyber'); });
        }

        // 可折叠分区标题点击展开/收起：由 createAllPanelPanels() 中的全局监听器统一处理
        panel.querySelectorAll('.cyber-section-header').forEach(header => {
            // 防止拖拽系统拦截折叠标题点击
            header.addEventListener('mousedown', e => e.stopPropagation());
        });

        // Sound Alert toggle
        const soundToggle = panel.querySelector('#cyber-soundToggle');
        if (soundToggle) {
            soundToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Cyber Sound Alert:', isActive);
                if (typeof window.FxMonitorSound !== 'undefined') {
                    window.FxMonitorSound.setEnabled(isActive);
                    syncSoundToggles();
                }
            });
            // 防止拖拽系统拦截toggle点击
            soundToggle.addEventListener('mousedown', e => e.stopPropagation());
            soundToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }

        // Drag Mode toggle — 锁定位置语义
        const dragToggle = panel.querySelector('#cyber-dragToggle');
        if (dragToggle) {
            dragToggle.addEventListener('click', function() {
                this.classList.toggle('active');
                const isActive = this.classList.contains('active');
                isDragEnabled = isActive;
                this.setAttribute('aria-checked', isActive.toString());
                console.log('[飞雪监测器] Cyber Drag Mode:', isActive);
                const dock = document.getElementById('cyber-dock');
                if (dock) {
                    const handle = dock.querySelector('.cyber-handle');
                    if (handle) handle.style.pointerEvents = isActive ? 'auto' : 'none';
                    if (!isActive) resetDockPosition(dock); // 关闭 Drag Mode 时 dock 自动归位
                }
            });
            // 防止拖拽系统拦截toggle点击
            dragToggle.addEventListener('mousedown', e => e.stopPropagation());
            dragToggle.addEventListener('touchstart', e => e.stopPropagation(), {passive: true});
        }
    }

    // ============================================================
    // 风格/颜色切换函数
    // ============================================================

    /**
     * 切换到目标风格
     * @param {string} target - 目标风格名，必须是 VALID_STYLES 之一
     */
    function switchStyle(target) {
        if (!target || !VALID_STYLES.includes(target)) {
            console.warn('[飞雪监测器] ⚠️ 无效风格:', target);
            return;
        }

        // 隐藏所有dock和panel
        VALID_STYLES.forEach(s => {
            const dock = document.getElementById(s + '-dock');
            const panel = document.getElementById(s + '-panel');
            if (dock) dock.classList.add('style-hidden');
            if (panel) panel.classList.add('style-hidden');
        });

        // 显示目标dock和panel
        const targetDock = document.getElementById(target + '-dock');
        const targetPanel = document.getElementById(target + '-panel');
        if (targetDock) targetDock.classList.remove('style-hidden');
        if (targetPanel) targetPanel.classList.remove('style-hidden');

        // 更新body class
        document.body.classList.remove(...VALID_STYLES.map(s => s + '-active'));
        document.body.classList.add(target + '-active');

        // 更新所有风格按钮的active状态
        document.querySelectorAll('[data-target]').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-target') === target);
        });

        currentStyle = target;

        // 持久化
        try {
            localStorage.setItem('fxm_current_style', target);
        } catch(e) { /* ignore */ }

        // 重新绑定拖拽到新激活的 dock（解决主题切换后拖拽失效问题）
        const newDock = document.getElementById(currentStyle + '-dock');
        if (newDock) {
            unbindDrag();
            bindDragToDock(newDock, currentStyle);
            // 主题切换后重置到默认顶部居中，避免旧主题保存的位置影响新主题
            try { localStorage.removeItem('fxm_drag_pos_' + currentStyle); } catch(e) {}
            resetDockPosition(newDock);
        }

        // 同步声音开关状态到新显示的主题面板
        syncSoundToggles();

        console.log(`[飞雪监测器] ✨ 风格已切换为: ${t('theme_name_' + target)} (${target})`);
    }

    /**
     * 切换颜色方案（主要影响Neu风格的base color）
     * @param {string} color - COLOR_WHITELIST 中的颜色名
     */
    function switchColor(color) {
        if (!color) return;

        // 颜色别名映射：允许非WHITELIST颜色名通过
        const COLOR_ALIAS_MAP = {
            green: 'aurora', purple: 'midnight', amber: 'sunset',
            cyan: 'ocean', pink: 'forest', red: 'sunset',
        };

        // 解析后的颜色（用于WHITELIST验证和Neu主题）
        const resolvedColor = COLOR_ALIAS_MAP[color] || color;

        if (!COLOR_WHITELIST.includes(resolvedColor)) {
            console.warn('[飞雪监测器] ⚠️ 未知颜色:', color);
            return;
        }
        currentColor = resolvedColor;  // 用resolvedColor更新状态

        // === Neu主题: data-neu-theme 属性（保持原有逻辑）===
        document.body.setAttribute('data-neu-theme', resolvedColor);

        // === Ind主题: --ind-accent-color 变量 ===
        const indColorMap = {
            cyan: '#00ddff', aurora: '#00f2fe',
            amber: '#ffaa00', sunset: '#ffaa00', red: '#ff3344',
            green: '#00ff66', forest: '#39d98a',
            purple: '#aa66ff', midnight: '#a855f7', ocean: '#4facfe', pink: '#ff66cc'
        };
        if (currentStyle === 'ind') {
            const indColor = indColorMap[color] || indColorMap[resolvedColor] || '#00ddff';
            document.documentElement.style.setProperty('--ind-accent-color', indColor);
            // 同步更新swatch选中态（优先匹配原始颜色名）
            document.querySelectorAll('.ind-swatch').forEach(s => s.classList.remove('active'));
            let activeSwatch = document.querySelector('.ind-swatch[data-color="' + color + '"]');
            if (!activeSwatch) {
                // 若白名单颜色无对应swatch，按近似基础色回退
                const fallbackMap = { aurora: 'cyan', ocean: 'cyan', sunset: 'amber', forest: 'green', midnight: 'purple', pink: 'red' };
                const fallbackColor = fallbackMap[color];
                if (fallbackColor) activeSwatch = document.querySelector('.ind-swatch[data-color="' + fallbackColor + '"]');
            }
            if (activeSwatch) activeSwatch.classList.add('active');
        }

        // === Retro主题: 磷光色变量组 ===
        const retroPhosphorMap = {
            green:  { primary: '#00FF41', glow: 'rgba(0,255,65,0.4)', text: '#00FF41', dim: '#00CC33' },
            purple: { primary: '#aa66ff', glow: 'rgba(170,102,255,0.4)', text: '#aa66ff', dim: '#8844cc' },
            amber:  { primary: '#ffaa00', glow: 'rgba(255,170,0,0.4)', text: '#ffaa00', dim: '#cc8800' },
            cyan:   { primary: '#00ddff', glow: 'rgba(0,221,255,0.4)', text: '#00ddff', dim: '#00aacc' },
            pink:   { primary: '#ff3399', glow: 'rgba(255,51,153,0.4)', text: '#ff3399', dim: '#cc2277' }
        };
        if (currentStyle === 'retro') {
            const pc = retroPhosphorMap[color] || retroPhosphorMap.green;
            document.documentElement.style.setProperty('--retro-phosphor-primary', pc.primary);
            document.documentElement.style.setProperty('--retro-phosphor-glow', pc.glow);
            document.documentElement.style.setProperty('--retro-phosphor-text', pc.text);
            document.documentElement.style.setProperty('--retro-phosphor-dim', pc.dim);
            // 更新色块选中态
            document.querySelectorAll('.retro-color-block').forEach(b => b.classList.remove('active'));
            const activeBlock = document.querySelector('.retro-color-block[data-color="' + color + '"]');
            if (activeBlock) activeBlock.classList.add('active');
        }

        // === Lux主题: 宝石色调 ===
        const luxJewelTones = {
            aurora: { gold: '#d4af37', light: '#f5e6a3', mid: '#b8960c' },
            ocean:  { gold: '#4a90d9', light: '#a8cde8', mid: '#2d6a9e' },
            sunset: { gold: '#e07a2f', light: '#f5c8a0', mid: '#a85a18' },
            forest: { gold: '#5a9e44', light: '#b8dba8', mid: '#3d7a28' },
            midnight:{ gold: '#8b6cc5', light: '#c4b8e0', mid: '#5e4899' }
        };
        if (currentStyle === 'lux') {
            const lt = luxJewelTones[resolvedColor] || luxJewelTones.aurora;
            document.documentElement.style.setProperty('--lux-gold', lt.gold);
            document.documentElement.style.setProperty('--lux-gold-light', lt.light);
            document.documentElement.style.setProperty('--lux-gold-mid', lt.mid);
        }

        // === Cyber主题: 重型钛金机架霓虹色调 ===
        // 只改变 pod 跑马灯线、氛围灯管、进度条、按钮 active 的颜色；机架钛金金属色保持不变
        const cyberTones = {
            aurora:   { primary: '#00f0ff', primaryRgb: '0, 240, 255',   secondary: '#ff00a0', secondaryRgb: '255, 0, 160' },
            ocean:    { primary: '#00b8d4', primaryRgb: '0, 184, 212',   secondary: '#006064', secondaryRgb: '0, 96, 100' },
            sunset:   { primary: '#ff6b35', primaryRgb: '255, 107, 53',  secondary: '#ff9100', secondaryRgb: '255, 145, 0' },
            forest:   { primary: '#00c853', primaryRgb: '0, 200, 83',    secondary: '#1b5e20', secondaryRgb: '27, 94, 32' },
            midnight: { primary: '#d500f9', primaryRgb: '213, 0, 249',   secondary: '#311b92', secondaryRgb: '49, 27, 146' }
        };
        if (currentStyle === 'cyber') {
            const ct = cyberTones[resolvedColor] || cyberTones.aurora;
            document.documentElement.style.setProperty('--cyber-primary', ct.primary);
            document.documentElement.style.setProperty('--cyber-primary-rgb', ct.primaryRgb);
            document.documentElement.style.setProperty('--cyber-secondary', ct.secondary);
            document.documentElement.style.setProperty('--cyber-secondary-rgb', ct.secondaryRgb);
        }

        // 更新Neu颜色按钮active状态
        document.querySelectorAll('[data-color]').forEach(btn => {
            const btnColor = btn.getAttribute('data-color');
            btn.classList.toggle('active', btnColor === color || btnColor === resolvedColor);
        });

        try { localStorage.setItem('fxm_current_color', color); } catch(e) {}
        const colorName = (COLOR_MAPS[resolvedColor] && COLOR_MAPS[resolvedColor].name) || color;
        console.log(`[飞雪监测器] 🎨 颜色已切换为: ${colorName} (${currentStyle})`);
    }

    /**
     * 安全获取风格名（不在列表中则回退到默认）
     * @param {string} style - 输入风格名
     * @returns {string} 安全的风格名
     */
    function getSafeStyle(style) {
        if (!style || !VALID_STYLES.includes(style)) return 'neu';
        return style;
    }

    /**
     * 切换指定风格的面板显隐
     * @param {string} style - 风格名
     */
    function togglePanel(style) {
        const safeStyle = getSafeStyle(style);
        const panel = document.getElementById(safeStyle + '-panel');
        if (!panel) return;

        const isVisible = !panel.classList.contains('style-hidden');
        if (isVisible) {
            panel.classList.add('style-hidden');
        } else {
            panel.classList.remove('style-hidden');
            // 同时确保其他面板隐藏
            VALID_STYLES.forEach(s => {
                if (s !== safeStyle) {
                    const p = document.getElementById(s + '-panel');
                    if (p) p.classList.add('style-hidden');
                }
            });
        }

        console.log(`[飞雪监测器] 面板[${safeStyle}]: ${isVisible ? '收起' : '展开'}`);
    }

    // ============================================================
    // 数据渲染 — 将数据渲染到当前激活风格的DOM
    // ============================================================

    /**
     * 根据当前激活的风格渲染数据到对应DOM
     * 统一入口：根据currentStyle分发到各风格的更新逻辑
     *
     * @param {Object} data - 标准化后的系统数据（来自collectSystemData）
     */
    function renderToCurrentTheme(data) {
        if (!data) {
            console.warn('[飞雪监测器] ⚠️ 无数据可渲染');
            return;
        }
        window._fxmLastData = data;

        requestAnimationFrame(() => {
            switch (currentStyle) {
                case 'neu':   renderNeuData(data); break;
                case 'ind':   renderIndData(data); break;
                case 'retro': renderRetroData(data); break;
                case 'lux':   renderLuxData(data); break;
                case 'cyber': renderCyberData(data); break;
                default:      renderNeuData(data); break;
            }

            // 始终更新系统详情（磁盘、网络）
            updateSystemDetails(cachedData);
        });
    }

    /** 渲染数据到Neu风格DOM */
    function renderNeuData(data) {
        const gpu = sanitizeValue(data.gpu?.usage);
        const vramPct = sanitizeValue(data.gpu?.vram_percent);
        const vramMB = sanitizeValue(data.gpu?.vram_used);
        const vramTotalMB = sanitizeValue(data.gpu?.vram_total);
        const cpu = sanitizeValue(data.cpu?.usage);
        const ram = sanitizeValue(data.ram?.percent);
        const swapGB = sanitizeValue(data.swap?.used_gb);
        const swapPct = sanitizeValue(data.swap?.percent) || 0;
        const temp = sanitizeValue(data.gpu?.temperature);
        const diskRead = sanitizeValue(data.disk_io?.read_mbps);
        const diskWrite = sanitizeValue(data.disk_io?.write_mbps);
        const netUp = sanitizeValue(data.network_io?.upload_mbps);
        const netDown = sanitizeValue(data.network_io?.download_mbps);

        // Dock chips
        setElText('neu-chip-gpu-value', gpu !== null ? Math.round(gpu) + '%' : '--');
        setElWidth('neu-chip-gpu-progress', gpu !== null ? Math.min(gpu, 100) : 0);

        if (vramMB !== null) {
            setElText('neu-chip-vram-value', (vramMB / 1024).toFixed(1) + 'GB');
        } else {
            setElText('neu-chip-vram-value', '--');
        }
        setElWidth('neu-chip-vram-progress', vramPct !== null ? Math.min(vramPct, 100) : 0);

        setElText('neu-chip-cpu-value', cpu !== null ? Math.round(cpu) + '%' : '--');
        setElWidth('neu-chip-cpu-progress', cpu !== null ? Math.min(cpu, 100) : 0);

        setElText('neu-chip-ram-value', ram !== null ? Math.round(ram) + '%' : '--');
        setElWidth('neu-chip-ram-progress', ram !== null ? Math.min(ram, 100) : 0);

        if (swapGB !== null && swapGB > 0) {
            setElText('neu-chip-swap-value', swapGB.toFixed(1));
        } else {
            setElText('neu-chip-swap-value', '0.0');
        }
        setElWidth('neu-chip-swap-progress', Math.min(swapPct, 100));

        setElText('neu-chip-temp-value', temp !== null ? Math.round(temp) + '\u00B0C' : '--');

        // Panel metric cards
        setElText('np-gpu-val', gpu !== null ? Math.round(gpu) : '--');
        setElText('np-cpu-val', cpu !== null ? Math.round(cpu) : '--');
        setElText('np-ram-val', ram !== null ? Math.round(ram) : '--');

        // Detail Section 1: GPU & VRAM - Progress bars + badges
        setElWidth('np-gpu-pb', gpu !== null ? Math.min(gpu, 100) : 0);
        setElText('np-gpu-pb-badge', gpu !== null ? Math.round(gpu) + '%' : '--%');

        setElWidth('np-vram-pb', vramPct !== null ? Math.min(vramPct, 100) : 0);
        if (vramMB !== null && vramTotalMB !== null) {
            setElText('np-vram-pb-badge', (vramMB / 1024).toFixed(1) + '/' + (vramTotalMB / 1024).toFixed(0) + 'GB');
        } else if (vramMB !== null) {
            setElText('np-vram-pb-badge', (vramMB / 1024).toFixed(1) + 'GB');
        } else {
            setElText('np-vram-pb-badge', '--');
        }

        // Temperature progress (scale 0-100°C to 0-100%)
        const tempPct = temp !== null ? Math.min(Math.max((temp - 20) / 80 * 100, 0), 100) : 0;
        setElWidth('np-temp-pb', tempPct);
        setElText('np-temp-pb-badge', temp !== null ? Math.round(temp) + '\u00B0C' : '--\u00B0C');

        // Detail Section 2: System Resources - Progress bars + badges
        setElWidth('np-cpu-pb', cpu !== null ? Math.min(cpu, 100) : 0);
        setElText('np-cpu-pb-badge', cpu !== null ? Math.round(cpu) + '%' : '--%');

        setElWidth('np-ram-pb', ram !== null ? Math.min(ram, 100) : 0);
        setElText('np-ram-pb-badge', ram !== null ? Math.round(ram) + '%' : '--%');

        setElWidth('np-swap-pb', Math.min(swapPct, 100));
        setElText('np-swap-pb-badge', swapGB !== null && swapGB > 0 ? swapGB.toFixed(1) + ' GB' : '-- GB');

        // Detail Section 3: I/O & Network details
        if (diskRead !== null && diskWrite !== null) {
            setElText('np-disk-detail', 'R: ' + diskRead.toFixed(1) + ' / W: ' + diskWrite.toFixed(1) + ' MB/s');
        }
        if (netUp !== null && netDown !== null) {
            setElText('np-net-detail', '\u2191 ' + netUp.toFixed(1) + ' / \u2193 ' + netDown.toFixed(1) + ' MB/s');
        }

        // Source text
        updateSourceText('np-source-text', data);

        // 声音警报：GPU>90% 或 温度>85°C 时播放警告音
        if ((gpu !== null && gpu > 90) || (temp !== null && temp > 85)) {
            if (typeof window.FxMonitorSound !== 'undefined') {
                window.FxMonitorSound.play();
            }
        }
    }

    /** 渲染数据到Ind风格DOM */
    function renderIndData(data) {
        const sanitizeValue = (v) => (v === null || v === undefined || isNaN(v)) ? null : v;
        const gpu = sanitizeValue(data.gpu?.usage);
        const cpu = sanitizeValue(data.cpu?.usage);
        const ram = sanitizeValue(data.ram?.percent);
        const vramPct = sanitizeValue(data.gpu?.vram_percent);
        const vramMB = sanitizeValue(data.gpu?.vram_used);
        const vramTotalMB = sanitizeValue(data.gpu?.vram_total);
        const temp = sanitizeValue(data.gpu?.temperature);
        const swapGB = sanitizeValue(data.swap?.used_gb);
        const swapPct = sanitizeValue(data.swap?.percent) || 0;

        // Detail bars
        setElWidth('idp-gpu-bar', gpu !== null ? Math.min(gpu, 100) : 0);
        setElText('idp-gpu-val', gpu !== null ? Math.round(gpu) + '%' : '--%');
        setElWidth('idp-vram-bar', vramPct !== null ? Math.min(vramPct, 100) : 0);
        if (vramMB !== null && vramTotalMB !== null) {
            setElText('idp-vram-val', (vramMB / 1024).toFixed(1) + '/' + (vramTotalMB / 1024).toFixed(0) + 'GB');
        } else if (vramMB !== null) {
            setElText('idp-vram-val', (vramMB / 1024).toFixed(1) + 'GB');
        } else {
            setElText('idp-vram-val', '--');
        }
        setElWidth('idp-cpu-bar', cpu !== null ? Math.min(cpu, 100) : 0);
        setElText('idp-cpu-val', cpu !== null ? Math.round(cpu) + '%' : '--%');
        setElWidth('idp-ram-bar', ram !== null ? Math.min(ram, 100) : 0);
        setElText('idp-ram-val', ram !== null ? Math.round(ram) + '%' : '--%');
        setElWidth('idp-swap-bar', Math.min(swapPct, 100));
        setElText('idp-swap-val', swapGB !== null && swapGB > 0 ? swapGB.toFixed(1) + ' GB' : '-- GB');

        // Dock VU metrics (ind-gpu-value, ind-gpu-vu-fill, etc.)
        setElText('ind-swap-value', swapGB !== null && swapGB > 0 ? swapGB.toFixed(1) : '--');
        setElWidth('ind-swap-vu-fill', Math.min(swapPct, 100));

        setElText('ind-gpu-value', gpu !== null ? Math.round(gpu) + '%' : '--%');
        setElWidth('ind-gpu-vu-fill', gpu !== null ? Math.min(gpu, 100) : 0);
        setElText('ind-vram-value', vramMB !== null ? (vramMB / 1024).toFixed(1) + 'GB' : '--');
        setElWidth('ind-vram-vu-fill', vramPct !== null ? Math.min(vramPct, 100) : 0);
        setElText('ind-cpu-value', cpu !== null ? Math.round(cpu) + '%' : '--%');
        setElWidth('ind-cpu-vu-fill', cpu !== null ? Math.min(cpu, 100) : 0);
        setElText('ind-ram-value', ram !== null ? Math.round(ram) + '%' : '--%');
        setElWidth('ind-ram-vu-fill', ram !== null ? Math.min(ram, 100) : 0);

        // Dock temperature indicator (uses left, not width)
        setElText('ind-temp-value', temp !== null ? Math.round(temp) : '--');
        const tempIndicator = document.getElementById('ind-temp-indicator');
        if (tempIndicator) {
            if (temp !== null) {
                const tempPct = Math.min(Math.max((temp - 20) / 80 * 100, 0), 100);
                tempIndicator.style.left = tempPct + '%';
            } else {
                tempIndicator.style.left = '0%';
            }
        }

        // IO stats
        const disk = data.disk_io;
        const net = data.network_io;
        if (disk) {
            if (disk.read_mbps !== undefined) setElText('idp-disk-read', disk.read_mbps.toFixed(1) + ' MB/s');
            if (disk.write_mbps !== undefined) setElText('idp-disk-write', disk.write_mbps.toFixed(1) + ' MB/s');
        }
        if (net) {
            if (net.download_mbps !== undefined) setElText('idp-net-down', net.download_mbps.toFixed(1) + ' MB/s');
            if (net.upload_mbps !== undefined) setElText('idp-net-up', net.upload_mbps.toFixed(1) + ' MB/s');
        }

        // AMD SMI info
        const smiInfo = document.getElementById('ind-amd-smi-info');
        if (smiInfo && data.gpu) {
            let lines = ['> amdsmi --info'];
            if (data.gpu.name) lines.push('GPU: ' + data.gpu.name);
            if (data.gpu.driver_version) lines.push('Driver: ' + data.gpu.driver_version);
            if (data.gpu.vbios_version) lines.push('VBIOS: ' + data.gpu.vbios_version);
            if (temp !== null) lines.push('Temp: ' + Math.round(temp) + '°C | Power: ' + (data.gpu.power_draw || '--') + 'W');
            if (data.gpu.clock_core) lines.push('Clock: ' + data.gpu.clock_core + ' MHz / ' + (data.gpu.clock_mem || '--') + ' MHz');
            smiInfo.innerHTML = lines.join('<br/>');
        }
    }

    /** 渲染数据到Retro风格DOM */
    function renderRetroData(data) {
        const sanitizeValue = (v) => (v === null || v === undefined || isNaN(v)) ? null : v;
        const gpu = sanitizeValue(data.gpu?.usage);
        const cpu = sanitizeValue(data.cpu?.usage);
        const ram = sanitizeValue(data.ram?.percent);
        const vramPct = sanitizeValue(data.gpu?.vram_percent);
        const vramMB = sanitizeValue(data.gpu?.vram_used);
        const vramTotalMB = sanitizeValue(data.gpu?.vram_total);
        const temp = sanitizeValue(data.gpu?.temperature);
        const swapGB = sanitizeValue(data.swap?.used_gb);
        const swapPct = sanitizeValue(data.swap?.percent) || 0;

        // Panel VFD progress bars
        setElWidth('rp-gpu-pb', gpu !== null ? Math.min(gpu, 100) : 0);
        setElText('rp-gpu-val', gpu !== null ? Math.round(gpu) + '%' : '--%');
        setElWidth('rp-vram-pb', vramPct !== null ? Math.min(vramPct, 100) : 0);
        if (vramMB !== null && vramTotalMB !== null) {
            setElText('rp-vram-val', (vramMB / 1024).toFixed(1) + '/' + (vramTotalMB / 1024).toFixed(0) + 'GB');
        } else if (vramMB !== null) {
            setElText('rp-vram-val', (vramMB / 1024).toFixed(1) + 'GB');
        } else {
            setElText('rp-vram-val', '--');
        }
        setElWidth('rp-cpu-pb', cpu !== null ? Math.min(cpu, 100) : 0);
        setElText('rp-cpu-val', cpu !== null ? Math.round(cpu) + '%' : '--%');
        setElWidth('rp-ram-pb', ram !== null ? Math.min(ram, 100) : 0);
        setElText('rp-ram-val', ram !== null ? Math.round(ram) + '%' : '--%');
        setElWidth('rp-swap-pb', Math.min(swapPct, 100));
        setElText('rp-swap-val', swapGB !== null && swapGB > 0 ? swapGB.toFixed(1) + ' GB' : '-- GB');

        // IO cards
        const disk = data.disk_io;
        const net = data.network_io;
        if (disk) {
            if (disk.read_mbps !== undefined) setElText('rp-disk-read', disk.read_mbps.toFixed(1) + ' MB/s');
            if (disk.write_mbps !== undefined) setElText('rp-disk-write', disk.write_mbps.toFixed(1) + ' MB/s');
        }
        if (net) {
            if (net.download_mbps !== undefined) setElText('rp-net-down', net.download_mbps.toFixed(1) + ' MB/s');
            if (net.upload_mbps !== undefined) setElText('rp-net-up', net.upload_mbps.toFixed(1) + ' MB/s');
        }

        // Dock LED bars activation (terminal removed)
        const ledMetrics = [
            { type: 'gpu', value: gpu },
            { type: 'vram', value: vramPct },
            { type: 'cpu', value: cpu },
            { type: 'ram', value: ram },
            { type: 'swap', value: swapPct }
        ];
        ledMetrics.forEach(m => {
            const bar = document.querySelector('.retro-metric[data-type="' + m.type + '"] .retro-led-bar');
            if (bar) {
                const segments = bar.querySelectorAll('.retro-led-segment');
                const activeCount = m.value !== null ? Math.round((m.value / 100) * segments.length) : 0;
                segments.forEach((seg, i) => seg.classList.toggle('active', i < activeCount));
            }
        });

        // Dock SWAP 数值
        setElText('retro-swap-value', swapGB !== null && swapGB > 0 ? swapGB.toFixed(1) + ' GB' : '-- GB');

        // Dock芯片数值更新（retro前缀，由buildRetroDock创建）
        const dockGpuVal = document.getElementById('retro-gpu-value');
        if (dockGpuVal) dockGpuVal.textContent = gpu !== null ? Math.round(gpu) + '%' : '--%';
        const dockVramVal = document.getElementById('retro-vram-value');
        if (dockVramVal) dockVramVal.textContent = vramMB !== null ? (vramMB / 1024).toFixed(1) + 'GB' : '--';
        const dockCpuVal = document.getElementById('retro-cpu-value');
        if (dockCpuVal) dockCpuVal.textContent = cpu !== null ? Math.round(cpu) + '%' : '--%';
        const dockRamVal = document.getElementById('retro-ram-value');
        if (dockRamVal) dockRamVal.textContent = ram !== null ? Math.round(ram) + '%' : '--%';
        const dockTempVal = document.getElementById('retro-temp-value');
        if (dockTempVal) dockTempVal.textContent = temp !== null ? Math.round(temp) + '\u00B0C' : '--\u00B0C';

        updateSourceText('retro-source-text', data);
    }

    /** 渲染数据到Lux风格DOM */
    function renderLuxData(data) {
        const gpu = sanitizeValue(data.gpu?.usage);
        const vramPct = sanitizeValue(data.gpu?.vram_percent);
        const vramMB = sanitizeValue(data.gpu?.vram_used);
        const vramTotalMB = sanitizeValue(data.gpu?.vram_total);
        const cpu = sanitizeValue(data.cpu?.usage);
        const ram = sanitizeValue(data.ram?.percent);
        const temp = sanitizeValue(data.gpu?.temperature);

        // Dock modules
        setElText('lux-chip-gpu-value', gpu !== null ? Math.round(gpu) + '%' : '--');
        setElWidth('lux-chip-gpu-progress', gpu !== null ? Math.min(gpu, 100) : 0);
        setElText('lux-chip-vram-value', vramMB !== null ? (vramMB / 1024).toFixed(1) + 'GB' : '--');
        setElWidth('lux-chip-vram-progress', vramPct !== null ? Math.min(vramPct, 100) : 0);
        setElText('lux-chip-cpu-value', cpu !== null ? Math.round(cpu) + '%' : '--');
        setElWidth('lux-chip-cpu-progress', cpu !== null ? Math.min(cpu, 100) : 0);
        setElText('lux-chip-ram-value', ram !== null ? Math.round(ram) + '%' : '--');
        setElWidth('lux-chip-ram-progress', ram !== null ? Math.min(ram, 100) : 0);

        const luxSwapGB = sanitizeValue(data.swap?.used_gb);
        const luxSwapPct = sanitizeValue(data.swap?.percent) || 0;
        setElText('lux-chip-swap-value', luxSwapGB !== null && luxSwapGB > 0 ? luxSwapGB.toFixed(1) : '0.0');
        setElWidth('lux-chip-swap-progress', Math.min(luxSwapPct, 100));

        // 修复 Lux Dock 温度不显示
        setElText('lux-chip-temp-value', temp !== null ? Math.round(temp) + '\u00B0C' : '--\u00B0C');
        setElWidth('lux-chip-temp-progress', temp !== null ? Math.min(Math.max(temp, 0), 100) : 0);

        // Panel cards & progress bars
        setElText('lp-gpu-val', gpu !== null ? Math.round(gpu) : '--');
        setElText('lp-gpu-badge', gpu !== null ? Math.round(gpu) + '%' : '--%');
        setElWidth('lp-gpu-pb', gpu !== null ? Math.min(gpu, 100) : 0);

        if (vramMB !== null && vramTotalMB !== null) {
            setElText('lp-vram-badge', (vramMB / 1024).toFixed(1) + '/' + (vramTotalMB / 1024).toFixed(0) + 'GB');
        } else if (vramMB !== null) {
            setElText('lp-vram-badge', (vramMB / 1024).toFixed(1) + 'GB');
        } else {
            setElText('lp-vram-badge', '--');
        }
        setElWidth('lp-vram-pb', vramPct !== null ? Math.min(vramPct, 100) : 0);

        setElText('lp-cpu-val', cpu !== null ? Math.round(cpu) : '--');
        setElText('lp-ram-val', ram !== null ? Math.round(ram) : '--');
        setElText('lp-ram-badge', ram !== null ? Math.round(ram) + '%' : '--%');
        setElWidth('lp-ram-pb', ram !== null ? Math.min(ram, 100) : 0);

        setElText('lp-temp-badge', temp !== null ? Math.round(temp) + '\u00B0C' : '--\u00B0C');
        setElWidth('lp-temp-pb', temp !== null ? Math.min(Math.max(temp, 0), 100) : 0);

        setElText('lp-swap-badge', luxSwapGB !== null && luxSwapGB > 0 ? luxSwapGB.toFixed(1) + ' GB' : '0.0 GB');
        setElWidth('lp-swap-pb', Math.min(luxSwapPct, 100));

        // SYSTEM: Disks I/O + Network IO
        const luxDiskRead = sanitizeValue(data.disk_io?.read_mbps);
        const luxDiskWrite = sanitizeValue(data.disk_io?.write_mbps);
        const luxNetUp = sanitizeValue(data.network_io?.upload_mbps);
        const luxNetDown = sanitizeValue(data.network_io?.download_mbps);
        if (luxDiskRead !== null && luxDiskWrite !== null) {
            setElText('lp-disk-detail', 'R: ' + luxDiskRead.toFixed(1) + ' / W: ' + luxDiskWrite.toFixed(1) + ' MB/s');
        }
        if (luxNetUp !== null && luxNetDown !== null) {
            setElText('lp-net-detail', '\u2191 ' + luxNetUp.toFixed(1) + ' / \u2193 ' + luxNetDown.toFixed(1) + ' MB/s');
        }

        updateSourceText('lux-source-text', data);
    }

    /** 渲染数据到Cyber风格DOM（Orbital Command 轨道指挥中心） */
    function renderCyberData(data) {
        const gpu = sanitizeValue(data.gpu?.usage);
        const vramPct = sanitizeValue(data.gpu?.vram_percent);
        const vramMB = sanitizeValue(data.gpu?.vram_used);
        const vramTotalMB = sanitizeValue(data.gpu?.vram_total);
        const cpu = sanitizeValue(data.cpu?.usage);
        const ram = sanitizeValue(data.ram?.percent);
        const swapGB = sanitizeValue(data.swap?.used_gb);
        const swapPct = sanitizeValue(data.swap?.percent) || 0;
        const temp = sanitizeValue(data.gpu?.temperature);

        // Dock 六个太空舱：GPU / VRAM / CPU / RAM / SWAP / TEMP
        // 数值单独显示，单位由 DOM 中的 .cyber-pod-unit 提供
        setElText('cyber-chip-gpu-value', gpu !== null ? Math.round(gpu) : '--');
        setElWidth('cyber-chip-gpu-progress', gpu !== null ? Math.min(gpu, 100) : 0);
        setElText('cyber-chip-vram-value', vramMB !== null ? (vramMB / 1024).toFixed(1) : '--');
        setElWidth('cyber-chip-vram-progress', vramPct !== null ? Math.min(vramPct, 100) : 0);
        setElText('cyber-chip-cpu-value', cpu !== null ? Math.round(cpu) : '--');
        setElWidth('cyber-chip-cpu-progress', cpu !== null ? Math.min(cpu, 100) : 0);
        setElText('cyber-chip-ram-value', ram !== null ? Math.round(ram) : '--');
        setElWidth('cyber-chip-ram-progress', ram !== null ? Math.min(ram, 100) : 0);

        if (swapGB !== null && swapGB > 0) {
            setElText('cyber-chip-swap-value', swapGB.toFixed(1));
        } else {
            setElText('cyber-chip-swap-value', '0.0');
        }
        setElWidth('cyber-chip-swap-progress', Math.min(swapPct, 100));
        setElText('cyber-chip-temp-value', temp !== null ? Math.round(temp) : '--');
        setElWidth('cyber-chip-temp-progress', temp !== null ? Math.min(Math.max(temp, 0), 100) : 0);

        // Panel 核心指标卡片
        setElText('cp-gpu-val', gpu !== null ? Math.round(gpu) : '--');
        setElText('cp-gpu-badge', gpu !== null ? Math.round(gpu) + '%' : '--%');
        setElWidth('cp-gpu-pb', gpu !== null ? Math.min(gpu, 100) : 0);

        if (vramMB !== null && vramTotalMB !== null) {
            setElText('cp-vram-badge', (vramMB / 1024).toFixed(1) + '/' + (vramTotalMB / 1024).toFixed(0) + 'GB');
        } else if (vramMB !== null) {
            setElText('cp-vram-badge', (vramMB / 1024).toFixed(1) + 'GB');
        } else {
            setElText('cp-vram-badge', '--');
        }
        setElWidth('cp-vram-pb', vramPct !== null ? Math.min(vramPct, 100) : 0);

        setElText('cp-cpu-val', cpu !== null ? Math.round(cpu) : '--');
        setElText('cp-cpu-badge', cpu !== null ? Math.round(cpu) + '%' : '--%');
        setElWidth('cp-cpu-pb', cpu !== null ? Math.min(cpu, 100) : 0);

        setElText('cp-ram-val', ram !== null ? Math.round(ram) : '--');
        setElText('cp-swap-badge', swapGB !== null && swapGB > 0 ? swapGB.toFixed(1) + ' GB' : '0.0 GB');
        setElWidth('cp-swap-pb', Math.min(swapPct, 100));

        setElText('cp-temp-badge', temp !== null ? Math.round(temp) + '\u00B0C' : '--\u00B0C');
        setElWidth('cp-temp-pb', temp !== null ? Math.min(Math.max(temp, 0), 100) : 0);

        // Cyber 时钟
        const clockEl = document.getElementById('cyber-clock');
        if (clockEl) {
            const now = new Date();
            clockEl.textContent = now.toTimeString().substring(0, 8);
        }

        updateSourceText('cyber-source-text', data);
    }

    // ============================================================
    // 辅助工具函数
    // ============================================================

    /**
     * 安全设置元素文本内容
     * @param {string} elId - 元素ID
     * @param {string} text - 文本内容
     */
    function setElText(elId, text) {
        const el = document.getElementById(elId);
        if (el) el.textContent = sanitizeDisplayText(text);
    }

    /**
     * 安全设置元素宽度样式
     * @param {string} elId - 元素ID
     * @param {number} pct - 百分比数值
     */
    function setElWidth(elId, pct) {
        const el = document.getElementById(elId);
        if (el) el.style.width = Math.max(0, Math.min(pct, 100)) + '%';
    }

    /**
     * 更新来源文本（带粘性缓存防闪烁）
     * @param {string} elId - 来源文本元素ID
     * @param {Object} data - 系统数据
     */
    function updateSourceText(elId, data) {
        const el = document.getElementById(elId);
        if (!el) return;

        if (!window._fxm_lastKnownSource) window._fxm_lastKnownSource = null;

        let newText;
        const SOURCE_NAMES = {
            'windows_wmi': 'Windows (WMI)',
            'amdsmi': 'AMD SMI',
            'rocm_smi': 'ROCm SMI',
            'sysfs': 'Linux sysfs',
            'error_fallback': 'Fallback',
            'none': 'None'
        };

        if (backendAvailable && data.data_source) {
            window._fxm_lastKnownSource = data.data_source;
            newText = t('source_prefix') + (SOURCE_NAMES[data.data_source] || data.data_source);
        } else if (window._fxm_lastKnownSource) {
            newText = t('source_prefix') + (SOURCE_NAMES[window._fxm_lastKnownSource] || window._fxm_lastKnownSource);
        } else {
            newText = t('source_prefix') + t('detecting');
        }

        if (el.textContent !== newText) el.textContent = newText;
    }

    /**
     * 迁移V3旧配置到V4新格式
     * 处理localStorage中的旧key名映射：
     * - fxm_emerald_theme_v13 → fxm_current_style (theme概念已合并到style)
     * - fxm_style_v31 → fxm_current_style
     */
    function migrateV3Config() {
        try {
            // 检查是否已有V4格式配置，有则跳过迁移
            if (localStorage.getItem('fxm_current_style')) {
                console.log('[飞雪监测器] ♻️ V4配置已存在，跳过迁移');
                return;
            }

            // 尝试从旧key迁移style偏好
            const oldStyle = localStorage.getItem('fxm_style_v31');
            if (oldStyle && VALID_STYLES.includes(oldStyle)) {
                localStorage.setItem('fxm_current_style', oldStyle);
                console.log(`[飞雪监测器] ♻️ 已迁移风格配置: ${oldStyle} → fxm_current_style`);
            }

            // 尝试迁移旧color偏好
            const oldColor = localStorage.getItem('fxm_neu_color');
            if (oldColor && COLOR_WHITELIST.includes(oldColor)) {
                currentColor = oldColor;
                console.log(`[飞雪监测器] ♻️ 已迁移颜色配置: ${oldColor}`);
            }

            // 清理旧key（可选，保留不删也兼容）
            // localStorage.removeItem('fxm_emerald_theme_v13');
            // localStorage.removeItem('fxm_style_v31');

        } catch(e) {
            console.warn('[飞雪监测器] ⚠️ V3配置迁移失败:', e.message);
        }
    }

    /**
     * 更新系统详情区域（磁盘、网络）
     * @param {Object} rawData - WebSocket/REST 推送的原始 snapshot 数据
     */
    function updateSystemDetails(rawData) {
        if (!rawData) return;

        const diskVal = document.getElementById('fxm-disk-value');
        const netVal = document.getElementById('fxm-net-value');

        if (diskVal) {
            const disk = rawData.disk_io;
            if (disk && disk.read_mbps !== undefined && disk.write_mbps !== undefined) {
                diskVal.textContent = 'R ' + disk.read_mbps.toFixed(1) + ' / W ' + disk.write_mbps.toFixed(1) + ' MB/s';
                diskVal.classList.remove('na');
            } else {
                diskVal.textContent = 'N/A';
                diskVal.classList.add('na');
            }
        }

        if (netVal) {
            const net = rawData.network_io;
            if (net && net.upload_mbps !== undefined && net.download_mbps !== undefined) {
                netVal.textContent = '\u2191 ' + net.upload_mbps.toFixed(1) + ' \u2193 ' + net.download_mbps.toFixed(1) + ' MB/s';
                netVal.classList.remove('na');
            } else {
                netVal.textContent = 'N/A';
                netVal.classList.add('na');
            }
        }
    }

    // ============================================================
    // 主更新循环（使用新的renderToCurrentTheme替代旧的updateAllCapsules）
    // ============================================================

    /** @type {number|null} 定时器 ID */
    let updateTimer = null;

    /**
     * 主更新循环 — Premium UI v3.25
     * 使用 renderToCurrentTheme(data) 替代旧的 updateAllCapsules(data)
     */
    async function mainUpdateLoop() {
        try {
            // 1. 采集数据
            const data = await collectSystemData();

            // 2. 渲染到当前激活风格的DOM（核心改动点！）
            renderToCurrentTheme(data);

        } catch (e) {
            console.error('[飞雪监测器] ❌ 更新循环异常:', e);
        }

        // 安排下一次更新
        updateTimer = setTimeout(mainUpdateLoop, CONFIG.updateInterval);
    }

    /**
     * 启动数据更新循环（供init调用）
     */
    function startDataLoop() {
        if (updateTimer) clearTimeout(updateTimer);
        mainUpdateLoop();
    }

    // ============================================================
    // 初始化 — Premium UI v3.25 启动流程
    // ============================================================

    /**
     * 初始化并启动监测器（Premium UI v3.25）
     *
     * 启动流程：
     * 1. 注入CSS
     * 2. 创建所有Dock和Panel DOM
     * 3. 迁移V3配置
     * 4. 恢复并切换到默认主题
     * 5. 如果有缓存数据立即渲染
     * 6. 启动数据更新循环
     * 7. 初始化拖拽
     */
    async function init() {
        console.log('[飞雪监测器] 🚀 Premium UI v3.25 启动...');
        try {
            // 1. 注入新CSS
            injectPremiumCSS();

            // 2. 创建所有Dock和Panel DOM
            createAllDockPanels();
            createAllPanelPanels();

            // 2.1 同步所有声音开关到持久化状态
            syncSoundToggles();

            // 3. 迁移V3配置
            migrateV3Config();

            // 4. 恢复并切换到默认主题
            const savedStyle = localStorage.getItem('fxm_current_style') || 'neu';
            switchStyle(savedStyle);

            // 5. 恢复颜色方案
            const savedColor = localStorage.getItem('fxm_current_color') || 'aurora';
            switchColor(savedColor);

            // 6. 如果有缓存数据，立即渲染一次
            if (cachedData) {
                renderToCurrentTheme(cachedData);
            }

            // 7. 启动数据更新循环
            startDataLoop();

            // 8. 初始化拖拽
            initDrag();

            // 9. 阻止浏览器自动翻译监测器界面文字
            const fxmSelectors = '#neu-dock,#ind-dock,#retro-dock,#lux-dock,#cyber-dock,#neu-panel,#ind-panel,#retro-panel,#lux-panel,#cyber-panel';
            document.querySelectorAll(fxmSelectors).forEach(el => el.setAttribute('translate', 'no'));
            if (typeof MutationObserver !== 'undefined') {
                new MutationObserver(() => {
                    document.querySelectorAll(fxmSelectors).forEach(el => el.setAttribute('translate', 'no'));
                }).observe(document.body, { childList: true, subtree: true });
            }

            console.log('[飞雪监测器] ✅ Premium UI v3.25 initialized successfully!');
        } catch(e) {
            console.error('[飞雪监测器] ❌ Init failed:', e);
        }
    }

    // ============================================================
    // 音频系统 — Web Audio API 提示音
    // ============================================================

    /**
     * 全局音频管理对象
     * 使用 Web Audio API 生成短促 beep 提示音
     */
    const SOUND_ENABLED_KEY = 'fxm_sound_enabled';
    function getInitialSoundEnabled() {
        try {
            const saved = localStorage.getItem(SOUND_ENABLED_KEY);
            return saved === null ? true : saved === 'true';
        } catch(e) {
            return true;
        }
    }
    window.FxMonitorSound = {
        _ctx: null,
        _enabled: getInitialSoundEnabled(),

        /**
         * 初始化音频上下文（需用户交互后调用）
         */
        init: function() {
            try {
                this._ctx = new (window.AudioContext || window.webkitAudioContext)();
                console.log('[飞雪监测器] 🎵 音频系统初始化成功');
            } catch(e) {
                console.warn('[飞雪监测器] ⚠️ 音频系统初始化失败:', e);
            }
        },

        /**
         * 播放提示音（短促双音 beeps）
         */
        play: function() {
            if (!this._enabled) return;
            // 工作流可能在用户未点击 toggle 前完成，自动初始化音频上下文
            if (!this._ctx) {
                this.init();
            }
            if (!this._ctx) return;
            try {
                const ctx = this._ctx;

                // 第一个 beep (高音)
                const osc1 = ctx.createOscillator();
                const gain1 = ctx.createGain();
                osc1.type = 'sine';
                osc1.frequency.setValueAtTime(880, ctx.currentTime); // A5
                gain1.gain.setValueAtTime(0.3, ctx.currentTime);
                gain1.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
                osc1.connect(gain1);
                gain1.connect(ctx.destination);
                osc1.start(ctx.currentTime);
                osc1.stop(ctx.currentTime + 0.15);

                // 第二个 beep (更高音) 延迟播放
                const osc2 = ctx.createOscillator();
                const gain2 = ctx.createGain();
                osc2.type = 'sine';
                osc2.frequency.setValueAtTime(1320, ctx.currentTime + 0.2); // E6
                gain2.gain.setValueAtTime(0.3, ctx.currentTime + 0.2);
                gain2.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
                osc2.connect(gain2);
                gain2.connect(ctx.destination);
                osc2.start(ctx.currentTime + 0.2);
                osc2.stop(ctx.currentTime + 0.35);

            } catch(e) {
                console.warn('[飞雪监测器] ⚠️ 提示音播放失败:', e);
            }
        },

        /**
         * 设置启用/禁用状态
         */
        setEnabled: function(enabled) {
            this._enabled = !!enabled;
            // 持久化状态，保证主题切换后一致
            try { localStorage.setItem(SOUND_ENABLED_KEY, this._enabled.toString()); } catch(e) {}
            // 首次启用时尝试初始化 AudioContext（需要用户交互）
            if (this._enabled && !this._ctx) {
                this.init();
            }
            // 如果音频上下文因浏览器策略被挂起，尝试恢复
            if (this._enabled && this._ctx && this._ctx.state === 'suspended') {
                this._ctx.resume().catch(() => {});
            }
            console.log('[飞雪监测器] 🔊 Sound Alert:', this._enabled ? 'ON' : 'OFF');
            return this._enabled;
        },

        /**
         * 用户首次交互时调用，解锁 AudioContext
         */
        unlock: function() {
            if (!this._ctx) this.init();
            if (this._ctx && this._ctx.state === 'suspended') {
                this._ctx.resume().catch(() => {});
            }
        }
    };

    /**
     * 同步所有主题面板中的声音提示开关 UI 到全局 FxMonitorSound._enabled 状态
     */
    function syncSoundToggles() {
        const isEnabled = window.FxMonitorSound ? window.FxMonitorSound._enabled : true;
        const toggles = document.querySelectorAll('#neu-soundToggle, #ind-soundToggle, #retro-soundToggle, #lux-soundToggle, #cyber-soundToggle');
        toggles.forEach(toggle => {
            toggle.classList.toggle('active', isEnabled);
            toggle.setAttribute('aria-checked', isEnabled.toString());
        });
    }

    // ============================================================
    // 拖拽功能（动态绑定当前激活的Dock — 支持主题切换后重绑定）
    // ============================================================

    /**
     * 关闭 Drag Mode 时将当前 dock 平滑归位到默认顶部
     */
    function resetDockPosition(dockEl) {
        if (!dockEl) return;
        dockEl.style.transition = 'top 0.3s ease, left 0.3s ease, transform 0.3s ease';
        dockEl.style.top = '12px';
        dockEl.style.left = '50%';
        dockEl.style.transform = 'translateX(-50%)';
        setTimeout(() => { dockEl.style.transition = ''; }, 300);
    }

    /**
     * 解除当前 dock 的拖拽绑定
     * 通过标记禁用拖拽，避免复杂的引用管理
     */
    function unbindDrag() {
        isDragging = false;
    }

    /**
     * 绑定拖拽到指定 dock 元素（可在主题切换后重复调用）
     * @param {HTMLElement} dockEl - 目标 dock DOM 元素
     * @param {string} styleName - 风格名，用于 localStorage key
     */
    function bindDragToDock(dockEl, styleName) {
        if (!dockEl) return;

        // 从 localStorage 恢复位置
        const dragKey = 'fxm_drag_pos_' + styleName;
        const savedPos = localStorage.getItem(dragKey);
        if (savedPos) {
            try {
                const pos = JSON.parse(savedPos);
                if (typeof pos.left === 'number' && typeof pos.top === 'number') {
                    savedBarLeft = pos.left;
                    savedBarTop = pos.top;
                    applyDockPosition(dockEl, pos.left, pos.top);
                }
            } catch(e) {}
        }

        // 查找手柄
        const handleSelectors = [
            '.neu-dock-handle', '.ind-drag-handle', '.retro-drag-handle',
            '.lux-dock-handle', '.cyber-handle'
        ];
        let dragHandle = null;
        for (const sel of handleSelectors) {
            dragHandle = dockEl.querySelector(sel);
            if (dragHandle) break;
        }
        if (!dragHandle) dragHandle = dockEl;

        // mousedown - 使用命名函数以便后续可以 removeEventListener（如果需要）
        function onMouseDown(e) {
            // ★ Drag Mode开关控制：关闭时禁止拖拽
            if (!isDragEnabled) return;

            const tag = e.target.tagName;
            if (tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'LABEL') return;
            if (e.target.closest('button, .neu-radio-btn, .ind-style-btn, .retro-style-btn, .lux-style-chip, .cyber-mode-btn, .ind-toggle, .retro-toggle-switch, .lux-toggle-switch, .cyber-toggle-switch, .neu-toggle-switch, [role="switch"]')) return;

            e.preventDefault();
            isDragging = true;
            dragStartX = e.clientX;
            dragStartY = e.clientY;
            const rect = dockEl.getBoundingClientRect();
            barStartLeft = rect.left;
            barStartTop = rect.top;
            dockEl.style.transition = 'none';
            dockEl.classList.add('fx-dragging');
        }

        function onMouseMove(e) {
            if (!isDragging) return;
            const dx = e.clientX - dragStartX;
            const dy = e.clientY - dragStartY;
            let newLeft = barStartLeft + dx;
            let newTop = barStartTop + dy;
            const maxLeft = window.innerWidth - dockEl.offsetWidth - 16;
            const maxTop = window.innerHeight - dockEl.offsetHeight - 16;
            newLeft = Math.max(8, Math.min(newLeft, maxLeft));
            newTop = Math.max(40, Math.min(newTop, maxTop));
            applyDockPosition(dockEl, newLeft, newTop);
            savedBarLeft = newLeft;
            savedBarTop = newTop;
        }

        function onMouseUp() {
            if (!isDragging) return;
            isDragging = false;
            dockEl.classList.remove('fx-dragging');
            dockEl.style.transition = '';
            // Drag Mode 关闭时不保存位置，避免恢复时被移动过的位置
            if (isDragEnabled && savedBarLeft !== null && savedBarTop !== null) {
                localStorage.setItem(dragKey, JSON.stringify({ left: savedBarLeft, top: savedBarTop }));
            }
        }

        dragHandle.addEventListener('mousedown', onMouseDown);
        // 根据全局 Drag Mode 状态初始化拖拽手柄 pointer-events
        if (dragHandle && dragHandle !== dockEl) {
            dragHandle.style.pointerEvents = isDragEnabled ? 'auto' : 'none';
        }
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    }

    /** 向后兼容别名 */
    function initDrag() {
        const activeDock = document.getElementById(currentStyle + '-dock');
        bindDragToDock(activeDock, currentStyle);
    }

    /**
     * 应用Dock位置
     * @param {HTMLElement} dock - Dock元素
     * @param {number} left - 左偏移
     * @param {number} top - 上偏移
     */
    function applyDockPosition(dock, left, top) {
        dock.style.left = left + 'px';
        dock.style.top = top + 'px';
        dock.style.transform = 'none';
        dock.style.transition = 'none';
    }

    // ============================================================
    // 导出全局对象供外部访问和调试
    // ============================================================

    window.FeixueMonitor = {
        version: CONFIG.version,
        getCurrentStyle: () => currentStyle,
        setStyle: switchStyle,
        switchColor: switchColor,
        togglePanel: togglePanel,
        refresh: () => fetchFromBackend().then(d => renderToCurrentTheme(d)),
        getSnapshot: () => fetchFromBackend()
    };

    console.log('[飞雪监测器] 📦 全局对象已导出: window.FeixueMonitor (v3.25)');

    // ============================================================
    // ComfyUI 工作流完成/出错声音提示
    // ============================================================

    /**
     * 注册 ComfyUI 工作流事件监听，在工作流完成或出错时播放提示音
     */
    function registerComfyUIEventListeners() {
        const api =
            window.comfyAPI?.api?.api ||
            window.app?.api ||
            null;

        if (!api || typeof api.addEventListener !== 'function') {
            // API 尚未就绪，稍后重试
            setTimeout(registerComfyUIEventListeners, 1000);
            return;
        }

        api.addEventListener('executed', function() {
            console.log('[飞雪监测器] 工作流完成，播放提示音');
            if (window.FxMonitorSound && window.FxMonitorSound._enabled) {
                window.FxMonitorSound.play();
            }
        });

        api.addEventListener('execution_error', function() {
            console.log('[飞雪监测器] 工作流出错，播放提示音');
            if (window.FxMonitorSound && window.FxMonitorSound._enabled) {
                window.FxMonitorSound.play();
            }
        });

        console.log('[飞雪监测器] 🔔 ComfyUI 工作流事件监听已注册');
    }

    // 首次用户交互时解锁音频上下文（浏览器自动播放策略要求）
    document.addEventListener('click', function onFirstClick() {
        if (window.FxMonitorSound) window.FxMonitorSound.unlock();
        document.removeEventListener('click', onFirstClick);
    }, { once: true });

    // 启动 ComfyUI 事件监听注册（兼容 API 延迟加载）
    registerComfyUIEventListeners();

    // DOM 加载完成后启动
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM 已经就绪
        init();
    }

})();
