/**
 * ComfyUI-Feixue-UniversalMonitor - Emerald Capsule v3.0.1
 *
 * 设计原则：不透明实底背景 + 发光边框灯条 + 药丸/胶囊形状 + 3D圆柱横截面效果 + CSS芯片图标 + 渐变状态条 + 5色主题系统
 * @version 3.0.1-EmeraldCapsule
 */

(function() {
    'use strict';

    console.log('[飞雪监测器] 🚀 Emerald Capsule v3.0.1 启动...');

    // ============================================================
    // 配置常量（保留核心配置不变）
    // ============================================================
    const CONFIG = {
        version: '3.0.1-EmeraldCapsule',
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
                // 后端不可用
                return getEmptyData('unavailable');
            }

            // ★★★ 格式自适应解析 ★=======
            const isNewFormat = realData.cpu_utilization !== undefined;

            if (isNewFormat) {
                // ===== 新格式解析 (FeixueHardwareInfo v2.0) =====
                const gpu0 = (realData.gpus && realData.gpus.length > 0) ? realData.gpus[0] : null;

                return {
                    timestamp: realData.timestamp || Date.now(),

                    // CPU - 新格式直接是顶层字段
                    cpu: {
                        usage: realData.cpu_utilization,
                    },

                    // RAM - 新旧格式相同
                    ram: {
                        total: realData.ram?.total_gb,
                        used: realData.ram?.used_gb,
                        percent: realData.ram?.percent,
                    },

                    // GPU - 新格式在 gpus[0] 下
                    gpu: {
                        usage: gpu0?.gpu_utilization,
                        vram_used: gpu0?.vram_used_mb,
                        vram_total: gpu0?.vram_total_mb,
                        vram_percent: gpu0?.vram_percent,
                        temperature: gpu0?.gpu_temperature,
                        power_draw: gpu0?.power_draw,
                    },

                    // Swap/虚拟内存 — 显示GB占用
                    swap: {
                        used_gb: realData.swap?.used_gb
                                || realData.ram?.swap_used_gb
                                || null,
                        percent: realData.swap?.percent
                              || realData.ram?.swap_percent
                              || realData.swap_percent
                              || null,
                    },

                    // 元数据
                    data_source: realData.data_source || 'backend-api',
                    _backend_available: true,
                    _format: 'new',
                };
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
    // 五主题系统 — Emerald Capsule v13.0
    // ============================================================

    /** 当前激活的主题 */
    let currentTheme = 'emerald';

    // ============================================================
    // 拖拽状态
    // ============================================================
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let barStartLeft = 0;
    let barStartTop = 0;
    let dragEnabled = false;          // 拖拽开关状态
    let savedBarLeft = null;          // localStorage 记忆位置
    let savedBarTop = null;
    const DRAG_STORAGE_KEY = 'feixue_monitor_bar_pos';

    /** 五主题定义 */
    const THEMES = {
        'emerald':   { name: '翡翠绿', color: '#00D080', primary: '#00D080', secondary: '#00A068', light: '#4FFFBF', rgb: '0,208,128' },
        'purple':    { name: '赛博紫', color: '#B04DFF', primary: '#B04DFF', secondary: '#7C3AED', light: '#E0B3FF', rgb: '176,77,255' },
        'amber':     { name: '琥珀金', color: '#FFB800', primary: '#FFB800', secondary: '#CC8800', light: '#FFE060', rgb: '255,184,0' },
        'blue':      { name: '极光蓝', color: '#00B4D8', primary: '#00B4D8', secondary: '#0077B6', light: '#90E0EF', rgb: '0,180,216' },
        'pink':      { name: '樱花粉', color: '#FF6B9D', primary: '#FF6B9D', secondary: '#C9184A', light: '#FFB3D0', rgb: '255,107,157' },
    };

    /** 多风格预设定义 */
    const STYLES = {
        'capsule':   { name: '翡翠胶囊', className: 'fx-style-capsule', desc: '药丸形·霓虹发光' },
        'titanium':  { name: '赛博钛金', className: 'fx-style-titanium', desc: '拉丝金属·虹彩流光' },
        'biolume':   { name: '生物发光', className: 'fx-style-biolume', desc: '微生物脉动·有机光效' },
        'blueprint': { name: '结构蓝图', className: 'fx-style-blueprint', desc: '等距线框·双色蓝图' },
        'pixel':     { name: '极简像素', className: 'fx-style-pixel', desc: '像素字体·方块进度' },
    };

    let currentStyle = 'capsule';

    /**
     * 应用主题到所有需要同步的元素
     * @param {string} themeKey - 主题标识符
     */
    function applyTheme(themeKey) {
        if (!THEMES[themeKey]) {
            console.warn('[飞雪监测器] ⚠️ 未知主题:', themeKey);
            return;
        }

        currentTheme = themeKey;

        // 更新 Dock 容器的 data-fx-theme 属性
        const dock = document.getElementById('fx-capsule-dock');
        if (dock) {
            dock.setAttribute('data-fx-theme', themeKey);
        }

        // 同步更新悬浮面板的主题属性
        const panel = document.getElementById('fxm-floating-panel');
        if (panel) {
            panel.setAttribute('data-fx-theme', themeKey);
        }

        // 保存到 localStorage
        try {
            localStorage.setItem('fxm_emerald_theme_v13', themeKey);
        } catch (e) {
            console.warn('[飞雪监测器] ⚠️ 无法保存主题偏好:', e.message);
        }

        // 更新按钮 active 状态
        syncThemeButtons(themeKey);

        console.log(`[飞雪监测器] 🎨 主题已切换为: ${THEMES[themeKey].name}`);
    }

    /**
     * 从 localStorage 恢复已保存的主题
     */
    function restoreTheme() {
        try {
            const savedTheme = localStorage.getItem('fxm_emerald_theme_v13');
            if (savedTheme && THEMES[savedTheme]) {
                applyTheme(savedTheme);
                console.log(`[飞雪监测器] ♻️ 已恢复主题: ${THEMES[savedTheme].name}`);
            } else {
                // 使用默认主题
                applyTheme('emerald');
            }
        } catch (e) {
            console.warn('[飞雪监测器] ⚠️ 恢复主题失败，使用默认值');
            applyTheme('emerald');
        }
    }

    /**
     * 同步所有主题按钮的 active 状态
     * @param {string} activeTheme - 当前激活的主题key
     */
    function syncThemeButtons(activeTheme) {
        // 更新循环按钮显示
        const dot = document.getElementById('fxm-theme-dot');
        const name = document.getElementById('fxm-theme-name');
        const theme = THEMES[activeTheme];
        if (dot && theme) {
            dot.style.background = theme.color;
        }
        if (name && theme) {
            name.textContent = theme.name;
        }
        // 兼容旧的芯片按钮
        const btns = document.querySelectorAll('.fx-theme-btn[data-theme], .fxm-theme-chip[data-theme]');
        btns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.theme === activeTheme);
        });
    }

    /**
     * 应用风格预设到 dock 和 panel
     * @param {string} styleKey - 风格标识符
     */
    function applyStyle(styleKey) {
        if (!STYLES[styleKey]) {
            console.warn('[飞雪监测器] ⚠️ 未知风格:', styleKey);
            return;
        }

        currentStyle = styleKey;

        // 更新 Dock 容器的 data-fx-style 属性
        const dock = document.getElementById('fx-capsule-dock');
        if (dock) {
            dock.setAttribute('data-fx-style', styleKey);
        }

        // 同步更新悬浮面板的风格属性
        const panel = document.getElementById('fxm-floating-panel');
        if (panel) {
            panel.setAttribute('data-fx-style', styleKey);
        }

        // 保存到 localStorage
        try {
            localStorage.setItem('fxm_style_v31', styleKey);
        } catch (e) {
            console.warn('[飞雪监测器] ⚠️ 无法保存风格偏好:', e.message);
        }

        // 更新按钮 active 状态
        syncStyleButtons(styleKey);

        console.log(`[飞雪监测器] 🎨 风格已切换为: ${STYLES[styleKey].name}`);
    }

    /**
     * 从 localStorage 恢复已保存的风格
     */
    function restoreStyle() {
        try {
            const savedStyle = localStorage.getItem('fxm_style_v31');
            if (savedStyle && STYLES[savedStyle]) {
                applyStyle(savedStyle);
                console.log(`[飞雪监测器] ♻️ 已恢复风格: ${STYLES[savedStyle].name}`);
            }
            // 如果没有保存的风格，保持默认 capsule（不额外设置属性）
        } catch (e) {
            console.warn('[飞雪监测器] ⚠️ 恢复风格失败，使用默认值');
        }
    }

    /**
     * 同步所有风格按钮的 active 状态
     * @param {string} activeStyle - 当前激活的风格key
     */
    function syncStyleButtons(activeStyle) {
        // 更新循环按钮显示
        const name = document.getElementById('fxm-style-name');
        const style = STYLES[activeStyle];
        if (name && style) {
            name.textContent = style.name;
        }
        // 兼容旧的芯片按钮
        const chips = document.querySelectorAll('.fxm-style-chip[data-style]');
        chips.forEach(chip => {
            chip.classList.toggle('active', chip.dataset.style === activeStyle);
        });
    }

    // ============================================================
    // CSS 注入 — Emerald Capsule v13.0 内联样式
    // ============================================================

    /**
     * 内联注入翡翠胶囊系统 CSS v13.0 全部样式
     * 使用 <style> 标签直接写入，避免 ComfyUI 扩展路径问题
     */
    function injectGemstoneCSS() {
        // 避免重复注入
        const existing = document.getElementById('fxm-emerald-css');
        if (existing) {
            existing.remove();
            console.log('[飞雪监测器] 🗑️ 已清除旧版CSS');
        }

        const style = document.createElement('style');
        style.id = 'fxm-emerald-css';
        style.setAttribute('data-version', '13.0');
        style.textContent = `
/* ============================================
   飞雪监测器 - Emerald Capsule UI v13.0 (内联)
   设计原则：不透明实底 + 发光边框 + 药丸形状 + 3D圆柱效果 + CSS芯片图标
   ============================================ */

/* ---------- CSS变量系统：默认 emerald 翡翠绿主题 ---------- */
:root {
    --fx-primary: #00D080;
    --fx-secondary: #00A068;
    --fx-light: #4FFFBF;
    --fx-glow: rgba(0, 208, 128, 0.25);
    --fx-glow-soft: rgba(0, 208, 128, 0.15);
    --fx-glow-diffuse: rgba(0, 208, 128, 0.06);
    --fx-rgb: 0, 208, 128;
    --fx-border-color: rgba(0, 208, 128, 0.30);
    --fx-shadow-glow: 0 0 20px rgba(0, 208, 128, 0.08);
    --fx-shadow-glow-large: 0 0 40px rgba(0, 208, 128, 0.04);
    --fx-text-accent: #00D080;
}

/* ---------- 赛博紫 Purple ---------- */
[data-fx-theme="purple"] {
    --fx-primary: #B04DFF; --fx-secondary: #7C3AED; --fx-light: #E0B3FF;
    --fx-glow: rgba(176, 77, 255, 0.25); --fx-glow-soft: rgba(176, 77, 255, 0.15); --fx-glow-diffuse: rgba(176, 77, 255, 0.06);
    --fx-rgb: 176, 77, 255; --fx-border-color: rgba(176, 77, 255, 0.30);
    --fx-shadow-glow: 0 0 20px rgba(176, 77, 255, 0.08); --fx-shadow-glow-large: 0 0 40px rgba(176, 77, 255, 0.04);
    --fx-text-accent: #B04DFF;
}

/* ---------- 琥珀金 Amber ---------- */
[data-fx-theme="amber"] {
    --fx-primary: #FFB800; --fx-secondary: #CC8800; --fx-light: #FFE060;
    --fx-glow: rgba(255, 184, 0, 0.25); --fx-glow-soft: rgba(255, 184, 0, 0.15); --fx-glow-diffuse: rgba(255, 184, 0, 0.06);
    --fx-rgb: 255, 184, 0; --fx-border-color: rgba(255, 184, 0, 0.30);
    --fx-shadow-glow: 0 0 20px rgba(255, 184, 0, 0.08); --fx-shadow-glow-large: 0 0 40px rgba(255, 184, 0, 0.04);
    --fx-text-accent: #FFB800;
}

/* ---------- 极光蓝 Blue ---------- */
[data-fx-theme="blue"] {
    --fx-primary: #00B4D8; --fx-secondary: #0077B6; --fx-light: #90E0EF;
    --fx-glow: rgba(0, 180, 216, 0.25); --fx-glow-soft: rgba(0, 180, 216, 0.15); --fx-glow-diffuse: rgba(0, 180, 216, 0.06);
    --fx-rgb: 0, 180, 216; --fx-border-color: rgba(0, 180, 216, 0.30);
    --fx-shadow-glow: 0 0 20px rgba(0, 180, 216, 0.08); --fx-shadow-glow-large: 0 0 40px rgba(0, 180, 216, 0.04);
    --fx-text-accent: #00B4D8;
}

/* ---------- 樱花粉 Pink ---------- */
[data-fx-theme="pink"] {
    --fx-primary: #FF6B9D; --fx-secondary: #C9184A; --fx-light: #FFB3D0;
    --fx-glow: rgba(255, 107, 157, 0.25); --fx-glow-soft: rgba(255, 107, 157, 0.15); --fx-glow-diffuse: rgba(255, 107, 157, 0.06);
    --fx-rgb: 255, 107, 157; --fx-border-color: rgba(255, 107, 157, 0.30);
    --fx-shadow-glow: 0 0 20px rgba(255, 107, 157, 0.08); --fx-shadow-glow-large: 0 0 40px rgba(255, 107, 157, 0.04);
    --fx-text-accent: #FF6B9D;
}

/* ============================================
   顶部栏容器
   ============================================ */
.fx-top-bar {
    position: fixed;
    top: 8px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 9000;
    pointer-events: none;
}
.fx-top-bar > * {
    pointer-events: auto;
}

/* 拖拽模式：dock 可被拖动 */
.fx-capsule-dock.fx-draggable {
    cursor: grab;
}
.fx-capsule-dock.fx-draggable:active {
    cursor: grabbing;
}
.fx-top-bar.fx-dragging {
    transition: none !important;
}

/* ============================================
   核心容器：Capsule Dock 胶囊形药丸底座
   不透明实底背景！禁止 backdrop-filter！
   ============================================ */
.fx-capsule-dock {
    display: flex;
    align-items: center;
    gap: 6px;             /* 紧凑间距 */
    padding: 8px 14px;    /* 收窄上下8px 左右14px */
    border-radius: 999px; /* 完美药丸形 */
    max-width: 900px;     /* 匹配 demo 样本最大宽度 */
    background: rgba(18, 24, 31, 0.82);
    backdrop-filter: blur(12px) saturate(1.15);
    -webkit-backdrop-filter: blur(12px) saturate(1.15);
    border: 1px solid rgba(var(--fx-rgb), 0.25);
    box-shadow:
        0 0 4px rgba(var(--fx-rgb), 0.20),
        0 0 12px rgba(var(--fx-rgb), 0.10),
        0 0 30px rgba(var(--fx-rgb), 0.04),
        0 8px 32px rgba(0, 0, 0, 0.25),
        inset 0 1px 0 rgba(255, 255, 255, 0.06),
        inset 0 -1px 0 rgba(0, 0, 0, 0.12);
    position: relative;
    overflow: hidden;
    transition: all 0.4s ease;
    animation: fxFadeInUp 0.6s ease-out both;
}

/* 3D 圆柱横截面效果 — 左侧区域 */
.fx-capsule-dock::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 120px;
    height: 100%;
    border-radius: 50% 0 0 50%;
    background: linear-gradient(
        to bottom,
        rgba(255, 255, 255, 0.60) 0%,
        rgba(255, 255, 255, 0.30) 5%,
        var(--fx-light) 15%,
        var(--fx-primary) 35%,
        var(--fx-secondary) 65%,
        rgba(0, 0, 0, 0.35) 85%,
        rgba(0, 0, 0, 0.48) 95%,
        rgba(0, 0, 0, 0.55) 100%
    );
    opacity: 0.92;
    z-index: 1;
    pointer-events: none;
    transition: all 0.4s ease;
}

@keyframes fxFadeInUp {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}

/* ============================================
   指标项 Metric Item
   ============================================ */
.fx-metric-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 6px 5px;     /* 收窄更紧凑 */
    background: rgba(22, 27, 34, 0.9);
    border-radius: 12px;   /* v13样本一致 */
    min-width: 80px;      /* v13样本对齐：从90→80 */
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
    z-index: 2;
    animation: fxFadeInUp 0.5s ease-out backwards;
}
.fx-metric-item:nth-child(2) { animation-delay: 0.08s; }
.fx-metric-item:nth-child(4) { animation-delay: 0.16s; }
.fx-metric-item:nth-child(6) { animation-delay: 0.24s; }
.fx-metric-item:nth-child(8) { animation-delay: 0.32s; }
.fx-metric-item:nth-child(10) { animation-delay: 0.40s; }
.fx-metric-item:nth-child(12) { animation-delay: 0.48s; }

/* 第一个指标项特殊处理：为左侧3D圆柱效果留空间 */
.fx-metric-item:first-child {
    padding-left: 28px;
    border-radius: 16px 12px 12px 16px;
}

.fx-metric-item:hover {
    transform: translateY(-1px);
    background: rgba(30, 36, 46, 0.95);
    border: 1px solid var(--fx-light);
    box-shadow:
        0 4px 12px rgba(0, 0, 0, 0.3),
        0 0 8px var(--fx-glow-diffuse);
}

/* 危险状态 */
.fx-metric--danger .fx-progress-fill {
    background: linear-gradient(90deg, #ff2a2a, #ff6666) !important;
    box-shadow: 0 0 10px rgba(255,42,42,0.65), 0 0 20px rgba(255,42,42,0.35) !important;
}
.fx-metric--danger .fx-metric-value {
    color: #ff6666 !important;
    text-shadow: 0 0 10px rgba(255,42,42,0.6), 0 0 20px rgba(255,42,42,0.3) !important;
}

/* ============================================
   渐变进度条 Progress Bar
   ============================================ */
.fx-progress-bar {
    width: 100%;
    height: 3px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 2px;
    margin-bottom: 5px;
    overflow: hidden;
    position: relative;
}

.fx-progress-fill {
    height: 100%;
    border-radius: 2px;
    max-width: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--fx-secondary), var(--fx-primary), var(--fx-light));
    box-shadow: 0 0 6px rgba(var(--fx-rgb), 0.20);
    position: relative;
    transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

/* liquidShine 光泽动画 */
.fx-progress-fill::after {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.50), transparent);
    animation: fxLiquidShine 2.5s infinite;
}
@keyframes fxLiquidShine {
    0% { left: -100%; }
    100% { left: 200%; }
}

/* ============================================
   指标内容区域 Metric Content
   ============================================ */
.fx-metric-content {
    display: flex;
    align-items: center;
    gap: 5px;
    width: 100%;
}

.fx-metric-icon {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
}

.fx-metric-info {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    min-width: 0;
}

.fx-metric-label {
    font-size: 9px;        /* v13样本对齐：从10→9 */
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    white-space: nowrap;
    line-height: 1;
}

.fx-metric-value {
    font-size: 13px;       /* v13样本对齐：从15→13 */
    font-weight: 800;
    font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
    color: var(--fx-text-accent);
    letter-spacing: -0.02em;
    line-height: 1.2;
    text-shadow:
        0 0 8px var(--fx-glow-soft),
        0 0 16px var(--fx-glow-diffuse);
}

/* 数值单位 */
.fx-metric-unit {
    font-size: 9px;         /* v13样本对齐：从10→9 */
    font-weight: 600;
    font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
    color: #8b949e;
    letter-spacing: 0;
    line-height: 1;
    margin-left: 1px;
}

/* 数值+单位行（内联显示） */
.fx-metric-value-row {
    display: inline-flex;
    align-items: baseline;
    gap: 1px;
    line-height: 1.2;
}

/* ============================================
   CSS芯片图标系统 — 6个纯CSS绘制图标
   ============================================ */

/* GPU 图标 — 显卡芯片 (18x13px) */
.fx-icon-gpu {
    width: 18px;
    height: 13px;
    background: linear-gradient(135deg, var(--fx-primary), var(--fx-secondary));
    border-radius: 2px;
    position: relative;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.25),
        inset 0 -2px 0 rgba(0, 0, 0, 0.25),
        0 0 6px var(--fx-glow-soft),
        0 0 12px var(--fx-glow-diffuse);
}
.fx-icon-gpu::before {
    content: '';
    position: absolute;
    top: 2px; left: 2px; right: 2px; bottom: 2px;
    background:
        radial-gradient(circle at 25% 25%, var(--fx-light) 1px, transparent 1px),
        radial-gradient(circle at 75% 25%, var(--fx-light) 1px, transparent 1px),
        radial-gradient(circle at 25% 75%, var(--fx-light) 1px, transparent 1px),
        radial-gradient(circle at 75% 75%, var(--fx-light) 1px, transparent 1px);
}

/* VRAM 图标 — 内存颗粒 (16x11px) */
.fx-icon-vram {
    width: 16px;
    height: 11px;
    background: linear-gradient(180deg, var(--fx-light), var(--fx-primary));
    border-radius: 2px;
    position: relative;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.30),
        inset 0 -1px 0 rgba(0, 0, 0, 0.25),
        0 0 5px var(--fx-glow-soft),
        0 0 10px var(--fx-glow-diffuse);
}
.fx-icon-vram::before {
    content: '';
    position: absolute;
    top: 1px; left: 1px; right: 1px;
    height: 2px;
    background: rgba(255, 255, 255, 0.40);
    border-radius: 1px;
}

/* CPU 图标 — 处理器 (14x14px) */
.fx-icon-cpu {
    width: 14px;
    height: 14px;
    background: linear-gradient(135deg, var(--fx-primary), var(--fx-secondary));
    border-radius: 2px;
    position: relative;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.25),
        inset 0 -1px 0 rgba(0, 0, 0, 0.20),
        0 0 5px var(--fx-glow-soft),
        0 0 10px var(--fx-glow-diffuse);
}
.fx-icon-cpu::before {
    content: '';
    position: absolute;
    top: 3px; left: 3px; right: 3px; bottom: 3px;
    background: #12181f;
    border-radius: 1px;
}
.fx-icon-cpu::after {
    content: '';
    position: absolute;
    top: 5px; left: 5px; right: 5px; bottom: 5px;
    background: linear-gradient(135deg, var(--fx-light), var(--fx-primary));
    border-radius: 1px;
}

/* RAM 图标 — 内存条 (18x10px) */
.fx-icon-ram {
    width: 18px;
    height: 10px;
    background: linear-gradient(180deg, var(--fx-light), var(--fx-secondary));
    border-radius: 2px;
    position: relative;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.25),
        inset 0 -1px 0 rgba(0, 0, 0, 0.20),
        0 0 5px var(--fx-glow-soft),
        0 0 10px var(--fx-glow-diffuse);
}
.fx-icon-ram::before {
    content: '';
    position: absolute;
    bottom: -3px; left: 2px; right: 2px;
    height: 3px;
    background: repeating-linear-gradient(90deg, var(--fx-primary) 0px, var(--fx-primary) 2px, transparent 2px, transparent 3px);
}

/* Swap 图标 — 存储 (16x14px) */
.fx-icon-swap {
    width: 16px;
    height: 14px;
    background: linear-gradient(180deg, var(--fx-light), var(--fx-secondary));
    border-radius: 50% 50% 3px 3px;
    position: relative;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.25),
        inset 0 -1px 0 rgba(0, 0, 0, 0.20),
        0 0 5px var(--fx-glow-soft),
        0 0 10px var(--fx-glow-diffuse);
}
.fx-icon-swap::before {
    content: '';
    position: absolute;
    top: 4px; left: 3px; right: 3px;
    height: 1px;
    background: rgba(0, 0, 0, 0.20);
}
.fx-icon-swap::after {
    content: '';
    position: absolute;
    top: 7px; left: 5px; right: 5px;
    height: 1px;
    background: rgba(0, 0, 0, 0.20);
}

/* Temp 图标 — 温度计 (10x16px) */
.fx-icon-temp {
    width: 10px;
    height: 16px;
    background: linear-gradient(to bottom, var(--fx-light), var(--fx-primary), var(--fx-secondary));
    border-radius: 5px 5px 3px 3px;
    position: relative;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.25),
        inset 0 -1px 0 rgba(0, 0, 0, 0.20),
        0 0 5px var(--fx-glow-soft),
        0 0 10px var(--fx-glow-diffuse);
}
.fx-icon-temp::after {
    content: '';
    position: absolute;
    bottom: -4px; left: 1px; right: 1px;
    height: 5px;
    background: var(--fx-primary);
    border-radius: 50%;
}

/* ============================================
   设置按钮 Settings Button
   ============================================ */
.fx-settings-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    min-width: 40px;
    background: transparent;
    border: none;
    color: #8b949e;
    font-size: 18px;
    cursor: pointer;
    transition: all 0.3s ease;
    border-radius: 12px;
    padding: 8px;
    z-index: 2;
    position: relative;
}
.fx-settings-btn:hover {
    color: var(--fx-primary);
    background: rgba(var(--fx-rgb), 0.10);
    transform: rotate(90deg);
}

/* ============================================
   底部温度栏 Bottom Bar
   ============================================ */
.fxm-bottom-bar {
    position: fixed;
    bottom: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 9000;
    pointer-events: none;
}
.fxm-bottom-bar > * {
    pointer-events: auto;
}
.fxm-bottom-dock {
    display: inline-flex;
    align-items: center;
    gap: 0;
    padding: 14px 20px;
    border-radius: 14px;
    background: rgba(18, 24, 31, 0.85);
    backdrop-filter: blur(12px) saturate(1.15);
    -webkit-backdrop-filter: blur(12px) saturate(1.15);
    border: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow:
        0 12px 48px rgba(0, 0, 0, 0.45),
        0 0 4px rgba(var(--fx-rgb), 0.10),
        inset 0 1px 0 rgba(255, 255, 255, 0.05);
    transition: all 0.3s ease;
    position: relative;
    animation: fxFadeInUpBottom 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) both;
    animation-delay: 100ms;
}
.fxm-bottom-dock::before {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: radial-gradient(ellipse at 50% 0%, var(--fx-glow-diffuse) 0%, transparent 55%);
    z-index: -1;
    pointer-events: none;
}
@keyframes fxFadeInUpBottom {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}

.fxm-temp-item {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    padding: 8px 16px;
    min-width: 140px;
    border-radius: 12px;
    transition: all 0.25s ease;
    background: transparent;
    border: none;
    animation: fxFadeInUpBottom 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.fxm-temp-item:first-child { animation-delay: 150ms; }
.fxm-temp-item:last-child { animation-delay: 200ms; }
.fxm-temp-item:hover {
    background: rgba(255, 255, 255, 0.03);
}

.fxm-temp-label {
    font-size: 11px;
    font-weight: 600;
    color: #8b949e;
    white-space: nowrap;
    letter-spacing: 0.4px;
    line-height: 1;
    text-transform: uppercase;
    margin-bottom: 6px;
}

.fxm-temp-value-wrapper {
    display: flex;
    align-items: baseline;
    gap: 3px;
    margin-bottom: 8px;
}

.fxm-temp-value {
    color: var(--fx-text-accent);
    font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
    font-size: 20px;
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.02em;
    text-shadow:
        0 0 10px var(--fx-glow-soft),
        0 0 20px var(--fx-glow-diffuse),
        0 0 30px var(--fx-glow-diffuse);
}

.fxm-temp-unit {
    color: #8b949e;
    font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
    font-size: 12px;
    font-weight: 500;
    line-height: 1;
}

.fxm-temp-progress-wrapper {
    width: 100%;
    height: 6px;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 3px;
    overflow: hidden;
    position: relative;
}

.fxm-temp-progress-bar {
    height: 100%;
    border-radius: 3px;
    max-width: 100%;
    width: 0%;
    position: relative;
    background: linear-gradient(90deg, var(--fx-secondary), var(--fx-primary), var(--fx-light));
    box-shadow: 0 0 8px rgba(var(--fx-rgb), 0.2);
    transition: width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.fxm-temp-progress-bar::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.55) 30%, rgba(255,255,255,0.30) 50%, transparent 70%);
    animation: fxLiquidShineBottom 2.0s ease-in-out infinite;
    pointer-events: none;
}
@keyframes fxLiquidShineBottom {
    0%,100%{transform:translateX(-100%)} 50%{transform:translateX(100%)}
}

.fxm-bottom-divider {
    width: 1px;
    height: 40px;
    background: linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.14) 30%, rgba(255,255,255,0.14) 70%, transparent 100%);
    margin: 0 16px;
}

/* ============================================
   悬浮面板 Floating Panel — 黑曜石毛玻璃风格
   深邃半透明 + backdrop-filter + 玻璃边缘高光
   ============================================ */
.fxm-floating-panel {
    position: fixed !important;
    top: 60px !important;
    right: 12px !important;
    width: 320px !important;
    max-height: 75vh;
    z-index: 1050 !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    background: rgba(10, 14, 20, 0.88) !important;
    backdrop-filter: blur(20px) saturate(1.3) !important;
    -webkit-backdrop-filter: blur(20px) saturate(1.3) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    box-shadow:
        0 0 0 1px rgba(255, 255, 255, 0.03) inset,
        0 1px 0 rgba(255, 255, 255, 0.04) inset,
        0 16px 48px rgba(0, 0, 0, 0.55),
        0 4px 12px rgba(0, 0, 0, 0.30) !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    font-size: 13px !important;
    color: #e6edf3 !important;
    user-select: none !important;
    line-height: 1.6 !important;
    display: flex !important;
    flex-direction: column !important;
    transition: opacity 0.3s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), visibility 0.3s ease !important;
}
/* 玻璃顶部高光线 */
.fxm-floating-panel::before {
    content: '';
    position: absolute;
    top: 0; left: 16px; right: 16px;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent);
    z-index: 2;
    pointer-events: none;
}
.fxm-floating-panel > * {
    position: relative;
    z-index: 1;
}
.fxm-floating-panel.fxm-hidden {
    opacity: 0 !important;
    pointer-events: none !important;
    visibility: hidden !important;
    transform: translateY(-12px) scale(0.96) !important;
}
.fxm-floating-panel.fxm-visible {
    opacity: 1 !important;
    visibility: visible !important;
    transform: translateY(0) scale(1) !important;
}

/* 面板标题栏 Header — 毛玻璃通透感 */
.fxm-panel-header {
    padding: 14px 16px 10px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: transparent;
}
.fxm-panel-title-wrapper {
    display: flex;
    align-items: center;
    gap: 10px;
}
.fxm-panel-title {
    font-size: 15px !important;
    font-weight: 700 !important;
    color: #e6edf3 !important;
    letter-spacing: 0.3px;
}
.fxm-panel-version {
    font-size: 11px !important;
    color: var(--fx-text-accent) !important;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
}
.fxm-btn {
    cursor: pointer;
    background: none;
    border: none;
    color: inherit;
    font-size: 18px;
    padding: 4px 8px;
}
.fxm-btn-close {
    width: 32px;
    height: 32px;
    border: 1px solid rgba(255,255,255,0.06);
    background: rgba(255, 255, 255, 0.03);
    color: #8b949e;
    border-radius: 8px;
    cursor: pointer;
    font-size: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.3s ease;
}
.fxm-btn-close:hover {
    background: rgba(239, 68, 68, 0.20);
    color: #ef4444;
    border-color: rgba(239, 68, 68, 0.30);
}

/* 面板内容区 Body */
.fxm-panel-content {
    padding: 12px 16px 14px 16px;
    flex: 1;
    overflow-y: auto;
}
.fxm-panel-glass-accent {
    height: 2px;
    width: 100%;
    background: linear-gradient(90deg, transparent 0%, var(--fx-primary) 15%, var(--fx-light) 50%, var(--fx-primary) 85%, transparent 100%);
    border-radius: 1px;
    opacity: 0.45;
    margin-bottom: 16px;
    box-shadow: none;
}

/* 主题切换区 Theme Section */
.fxm-theme-section {
    margin-bottom: 18px;
}
.fxm-section-label {
    font-size: 11px !important;
    font-weight: 600 !important;
    color: #8b949e !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
}
.fxm-section-icon {
    font-size: 12px;
    color: var(--fx-primary);
}

/* 拖拽开关 — 工业方形拨动开关 */
.fxm-toggle-section {
    margin-bottom: 18px;
}
.fxm-toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.06);
}
.fxm-toggle-label {
    font-size: 12px !important;
    color: #c9d1d9 !important;
    display: flex;
    align-items: center;
    gap: 8px;
}
.fxm-toggle-icon {
    font-size: 14px;
    color: var(--fx-primary);
}
/* 工业方形拨动开关 */
.fxm-toggle-switch {
    position: relative;
    width: 40px;
    height: 22px;
    flex-shrink: 0;
}
.fxm-toggle-switch input {
    opacity: 0;
    width: 0;
    height: 0;
}
.fxm-toggle-slider {
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background: #1c2128;
    border-radius: 3px;
    border: 1px solid rgba(255, 255, 255, 0.10);
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.4);
    transition: all 0.25s ease;
}
.fxm-toggle-slider::before {
    content: '';
    position: absolute;
    height: 14px;
    width: 14px;
    left: 3px;
    bottom: 3px;
    background: #555;
    border-radius: 2px;
    border: 1px solid rgba(255, 255, 255, 0.10);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
    transition: all 0.25s ease;
}
.fxm-toggle-switch input:checked + .fxm-toggle-slider {
    background: var(--fx-primary);
    border-color: rgba(var(--fx-rgb), 0.4);
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.3), 0 0 8px rgba(var(--fx-rgb), 0.15);
}
.fxm-toggle-switch input:checked + .fxm-toggle-slider::before {
    transform: translateX(18px);
    background: #fff;
    border-color: rgba(255, 255, 255, 0.3);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

.fxm-button-group {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

/* 主题切换按钮 Theme Buttons */
.fx-theme-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 10px;
    border: 2px solid transparent;
    background: #161b22;
    color: #e6edf3 !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    cursor: pointer;
    transition: all 0.3s ease;
    flex: 1;
    min-width: auto;
}
.fx-theme-btn:hover {
    transform: translateY(-2px);
}
.fx-theme-btn.active {
    border-color: currentColor;
    box-shadow: 0 4px 12px rgba(var(--fx-rgb), 0.30);
}

.fx-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    box-shadow: 0 0 6px currentColor;
    flex-shrink: 0;
}

/* 主题芯片按钮（网格布局） */
.fxm-theme-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.fxm-theme-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.10);
    background: rgba(255, 255, 255, 0.04);
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 11px !important;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.65) !important;
}
.fxm-theme-chip:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.20);
    transform: translateY(-1px);
}
.fxm-theme-chip.active {
    background: rgba(255, 255, 255, 0.12);
    border-color: var(--fx-primary);
    color: #fff !important;
    box-shadow: 0 0 12px rgba(var(--fx-rgb), 0.30);
}
.fxm-chip-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.fxm-chip-name {
    white-space: nowrap;
    letter-spacing: 0.2px;
}

/* ---------- 风格预设区域 ---------- */
.fxm-style-section {
    margin-bottom: 18px;
}
.fxm-style-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}
.fxm-style-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border-radius: 20px;
    border: 1px solid rgba(255, 255, 255, 0.10);
    background: rgba(255, 255, 255, 0.04);
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 11px !important;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.65) !important;
}
.fxm-style-chip:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.20);
    transform: translateY(-1px);
}
.fxm-style-chip.active {
    background: rgba(255, 255, 255, 0.12);
    border-color: var(--fx-primary);
    color: #fff !important;
    box-shadow: 0 0 12px rgba(var(--fx-rgb), 0.30);
}

/* ========== 系统详情区域 ========== */
.fxm-system-details {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid rgba(var(--fx-rgb), 0.10);
}
.fxm-detail-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    font-size: 11px;
    color: rgba(255,255,255,0.7);
}
.fxm-detail-icon {
    width: 18px;
    text-align: center;
    font-size: 12px;
    color: var(--fx-primary);
    opacity: 0.7;
}
.fxm-detail-label {
    width: 32px;
    color: rgba(255,255,255,0.5);
    flex-shrink: 0;
}
.fxm-detail-value {
    font-family: 'Consolas', 'Menlo', monospace;
    color: rgba(255,255,255,0.85);
    font-size: 11px;
}
.fxm-detail-value.na {
    color: rgba(255,255,255,0.3);
    font-style: italic;
}

/* 数据卡片 Data Cards — 微玻璃卡片 */
.fxm-data-cards {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 14px;
}
.fxm-data-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
    padding: 12px 14px;
    transition: all 0.25s ease;
}
.fxm-data-card:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(var(--fx-rgb), 0.25);
    transform: translateY(-1px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}
.fxm-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
}
.fxm-card-icon {
    font-size: 16px;
    color: var(--fx-primary);
    text-shadow: 0 0 6px var(--fx-glow-soft);
}
.fxm-card-title {
    font-size: 13px !important;
    font-weight: 700 !important;
    color: #e6edf3 !important;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.fxm-card-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.fxm-card-metric {
    display: flex;
    align-items: center;
    gap: 12px;
}
.fxm-card-label {
    font-size: 11px !important;
    font-weight: 500 !important;
    color: #8b949e !important;
    min-width: 60px;
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}
.fxm-card-progress {
    flex: 1;
    height: 8px;
    background: rgba(0, 0, 0, 0.30);
    border-radius: 3px;
    overflow: hidden;
    position: relative;
    box-shadow:
        inset 0 1px 3px rgba(0, 0, 0, 0.5),
        inset 0 -1px 0 rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.05);
}
.fxm-card-progress-bar {
    height: 100%;
    border-radius: 2px;
    max-width: 100%;
    width: 0%;
    position: relative;
    background: linear-gradient(180deg,
        rgba(255,255,255,0.15) 0%,
        transparent 30%,
        transparent 70%,
        rgba(0,0,0,0.15) 100%
    ),
    linear-gradient(90deg, var(--fx-secondary), var(--fx-primary), var(--fx-light));
    background-size: 100% 100%, 200% 100%;
    box-shadow:
        0 0 6px rgba(var(--fx-rgb), 0.15),
        inset 0 1px 0 rgba(255,255,255,0.15);
    transition: width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
    animation: fx-card-gradient-drift 3s ease-in-out infinite;
}
@keyframes fx-card-gradient-drift {
    0%, 100% { background-position: 0 0, 0 0; }
    50% { background-position: 0 0, -100% 0; }
}
.fxm-card-progress-bar::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.35) 35%, rgba(255,255,255,0.15) 50%, transparent 65%);
    animation: fxLiquidShinePanel 2.5s ease-in-out infinite;
    pointer-events: none;
}
@keyframes fxLiquidShinePanel {
    0%,100%{transform:translateX(-100%)} 50%{transform:translateX(100%)}
}
.fxm-card-value {
    font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    min-width: 55px;
    text-align: right;
    flex-shrink: 0;
    color: var(--fx-text-accent) !important;
    text-shadow: 0 0 8px var(--fx-glow-soft);
}

/* 底部状态栏 Footer Status Bar — 玻璃效果 */
.fxm-status-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 20px;
    margin-top: 4px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    background: rgba(0, 0, 0, 0.20);
    font-size: 10px !important;
    color: #8b949e !important;
    font-family: 'JetBrains Mono', monospace;
}
.fxm-status-item {
    display: flex;
    align-items: center;
    gap: 6px;
}
.fxm-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--fx-primary);
    box-shadow: 0 0 6px rgba(var(--fx-rgb), 0.3);
    animation: fxStatusPulse 2s ease-in-out infinite;
}
@keyframes fxStatusPulse {
    0%,100%{opacity:0.6;transform:scale(1)} 50%{opacity:1;transform:scale(1.15)}
}

/* ============================================
   响应式设计
   ============================================ */
@media (max-width: 768px) {
    .fx-capsule-dock {
        padding: 8px 12px;
    }
    .fx-metric-item {
        padding: 6px 4px;
        min-width: 56px;
    }
    .fx-metric-item:first-child {
        padding-left: 20px;
    }
    .fxm-floating-panel {
        width: 320px !important;
        right: 8px !important;
    }
}
/* ============================================
   风格预设 - 每种风格完全重新设计，视觉差异巨大
   核心原则：不同风格必须从形状、材质、边框、背景等
   多方面完全区分，不能仅靠颜色变化
   ============================================ */

/* ==========================================================
   风格1：翡翠胶囊 Capsule（默认）
   药丸形 + 3D圆柱左侧光效 + 霓虹发光边框
   这是唯一保留 ::before 伪元素（动车车头）的风格
   ========================================================== */
.fx-capsule-dock[data-fx-style="capsule"] {
    border-radius: 999px;
    background: rgba(18, 24, 31, 0.82);
    backdrop-filter: blur(12px) saturate(1.15);
    -webkit-backdrop-filter: blur(12px) saturate(1.15);
    border: 1px solid rgba(var(--fx-rgb), 0.25);
    box-shadow:
        0 0 4px rgba(var(--fx-rgb), 0.20),
        0 0 12px rgba(var(--fx-rgb), 0.10),
        0 0 30px rgba(var(--fx-rgb), 0.04),
        0 8px 32px rgba(0, 0, 0, 0.25),
        inset 0 1px 0 rgba(255, 255, 255, 0.06),
        inset 0 -1px 0 rgba(0, 0, 0, 0.12);
    padding: 8px 14px;
    gap: 6px;
    overflow: hidden;
}
/* 胶囊专属：3D圆柱横截面 ::before（动车车头）*/
.fx-capsule-dock[data-fx-style="capsule"]::before {
    display: block;
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 120px;
    height: 100%;
    border-radius: 50% 0 0 50%;
    background: linear-gradient(
        to bottom,
        rgba(255,255,255,0.60) 0%,
        rgba(255,255,255,0.30) 5%,
        var(--fx-light) 15%,
        var(--fx-primary) 35%,
        var(--fx-secondary) 65%,
        rgba(0,0,0,0.35) 85%,
        rgba(0,0,0,0.48) 95%,
        rgba(0,0,0,0.55) 100%
    );
    opacity: 0.92;
    z-index: 1;
    pointer-events: none;
}
[data-fx-style="capsule"] .fx-metric-item {
    background: rgba(22,27,34,0.9);
    border-radius: 12px;
    border: none;
    padding: 6px 5px;
    box-shadow: none;
}
[data-fx-style="capsule"] .fx-metric-item:first-child {
    padding-left: 28px;
    border-radius: 16px 12px 12px 16px;
}
[data-fx-style="capsule"] .fx-metric-item:hover {
    background: rgba(30,36,46,0.95);
    border: 1px solid var(--fx-light);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3), 0 0 8px var(--fx-glow-diffuse);
    transform: translateY(-1px);
}
[data-fx-style="capsule"] .fx-progress-fill {
    background: linear-gradient(90deg, var(--fx-secondary), var(--fx-primary), var(--fx-light));
    border-radius: 2px;
    box-shadow: 0 0 6px rgba(var(--fx-rgb), 0.20);
}
[data-fx-style="capsule"] .fx-progress-bar {
    background: rgba(255,255,255,0.08);
    border-radius: 2px;
}
[data-fx-style="capsule"] .fx-metric-value {
    color: var(--fx-text-accent);
    font-size: 13px;
    text-shadow: 0 0 8px var(--fx-glow-soft), 0 0 16px var(--fx-glow-diffuse);
}
[data-fx-style="capsule"] .fx-metric-label {
    color: #8b949e;
    font-size: 9px;
}

/* ==========================================================
   风格2：赛博钛金 Titanium
   完全隐藏 ::before，方形硬朗拉丝金属面板 + 铆钉边框
   与胶囊风格从形状到材质完全不同
   ========================================================== */
.fx-capsule-dock[data-fx-style="titanium"] {
    border-radius: 3px;
    background: linear-gradient(180deg, #2a2a32 0%, #1a1a22 40%, #22222c 100%);
    border: 1px solid #3a3a44;
    box-shadow:
        0 2px 12px rgba(0,0,0,0.5),
        inset 0 2px 0 rgba(255,255,255,0.06),
        inset 0 -2px 0 rgba(0,0,0,0.3);
    padding: 6px 10px;
    gap: 3px;
    overflow: visible;
}
/* 钛金：完全隐藏 ::before 动车车头 */
.fx-capsule-dock[data-fx-style="titanium"]::before {
    display: none !important;
}
[data-fx-style="titanium"] .fx-metric-item {
    background: linear-gradient(180deg, #1e1e28 0%, #181820 100%);
    border-radius: 2px;
    border: 1px solid #3a3a44;
    padding: 5px 7px;
    box-shadow: inset 0 2px 0 rgba(255,255,255,0.04), 0 1px 3px rgba(0,0,0,0.3);
}
[data-fx-style="titanium"] .fx-metric-item:first-child {
    border-radius: 2px;
    padding-left: 7px;
}
[data-fx-style="titanium"] .fx-metric-item:hover {
    background: linear-gradient(180deg, #282838 0%, #202028 100%);
    border-color: #555;
    box-shadow: inset 0 2px 0 rgba(255,255,255,0.06), 0 2px 8px rgba(0,0,0,0.5);
    transform: none;
}
[data-fx-style="titanium"] .fx-progress-fill {
    background: linear-gradient(90deg, #555, #888, #aaa);
    background-size: 200% 100%;
    border-radius: 0;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 0 6px rgba(255,255,255,0.1);
    animation: fx-titanium-flow 2.5s linear infinite;
}
[data-fx-style="titanium"] .fx-progress-bar {
    background: #111;
    border-radius: 0;
    border: 1px solid #333;
}
[data-fx-style="titanium"] .fx-progress-fill::after { animation: none; }
[data-fx-style="titanium"] .fx-metric-value {
    color: #ddd;
    font-size: 12px;
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
    font-weight: 700;
}
[data-fx-style="titanium"] .fx-metric-label {
    color: #888;
    font-size: 9px;
    letter-spacing: 1px;
}
@keyframes fx-titanium-flow { to { background-position: -200% 0; } }

/* ==========================================================
   风格3：生物发光 Biolume
   完全隐藏 ::before，大圆角有机半透明胶状体 + 脉动呼吸光效
   每个指标项都是独立的发光细胞体
   ========================================================== */
.fx-capsule-dock[data-fx-style="biolume"] {
    border-radius: 24px;
    background: transparent;
    border: none;
    box-shadow: none;
    padding: 4px 8px;
    gap: 8px;
    overflow: visible;
}
/* 生物发光：完全隐藏 ::before 动车车头 */
.fx-capsule-dock[data-fx-style="biolume"]::before {
    display: none !important;
}
[data-fx-style="biolume"] .fx-metric-item {
    background: radial-gradient(ellipse at 50% 30%, rgba(20,20,50,0.7) 0%, rgba(5,5,15,0.9) 100%);
    border-radius: 16px;
    border: 1px solid rgba(var(--fx-rgb), 0.3);
    padding: 8px 10px;
    box-shadow:
        0 0 14px rgba(var(--fx-rgb), 0.2),
        0 0 28px rgba(var(--fx-rgb), 0.08),
        inset 0 0 12px rgba(var(--fx-rgb), 0.06);
    animation: fx-biolume-breathe 3s ease-in-out infinite;
}
[data-fx-style="biolume"] .fx-metric-item:nth-child(2) { animation-delay: 0.4s; }
[data-fx-style="biolume"] .fx-metric-item:nth-child(3) { animation-delay: 0.8s; }
[data-fx-style="biolume"] .fx-metric-item:nth-child(4) { animation-delay: 1.2s; }
[data-fx-style="biolume"] .fx-metric-item:nth-child(5) { animation-delay: 1.6s; }
[data-fx-style="biolume"] .fx-metric-item:nth-child(6) { animation-delay: 2.0s; }
[data-fx-style="biolume"] .fx-metric-item:first-child {
    border-radius: 16px;
    padding-left: 10px;
}
[data-fx-style="biolume"] .fx-metric-item:hover {
    background: radial-gradient(ellipse at 50% 30%, rgba(40,40,80,0.8) 0%, rgba(10,10,30,0.95) 100%);
    border-color: rgba(var(--fx-rgb), 0.7);
    box-shadow:
        0 0 24px rgba(var(--fx-rgb), 0.22),
        0 0 48px rgba(var(--fx-rgb), 0.08),
        inset 0 0 20px rgba(var(--fx-rgb), 0.08);
    transform: translateY(-2px) scale(1.04);
}
[data-fx-style="biolume"] .fx-progress-fill {
    background: radial-gradient(circle at 30% 50%, rgba(var(--fx-rgb), 0.9) 0%, transparent 60%),
                radial-gradient(circle at 70% 50%, rgba(var(--fx-rgb), 0.6) 0%, transparent 50%);
    border-radius: 4px;
    box-shadow: 0 0 10px rgba(var(--fx-rgb), 0.22);
    animation: fx-biolume-shift 3s ease-in-out infinite;
}
[data-fx-style="biolume"] .fx-progress-bar {
    background: rgba(255,255,255,0.03);
    border-radius: 4px;
}
[data-fx-style="biolume"] .fx-metric-value {
    color: rgba(255,255,255,0.9);
    font-size: 13px;
    text-shadow: 0 0 10px rgba(var(--fx-rgb), 0.25), 0 0 20px rgba(var(--fx-rgb), 0.10);
}
[data-fx-style="biolume"] .fx-metric-label {
    color: rgba(255,255,255,0.35);
    font-size: 9px;
}
@keyframes fx-biolume-shift {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
}
@keyframes fx-biolume-breathe {
    0%, 100% { box-shadow: 0 0 14px rgba(var(--fx-rgb), 0.2), 0 0 28px rgba(var(--fx-rgb), 0.08), inset 0 0 12px rgba(var(--fx-rgb), 0.06); }
    50% { box-shadow: 0 0 22px rgba(var(--fx-rgb), 0.20), 0 0 40px rgba(var(--fx-rgb), 0.08), inset 0 0 18px rgba(var(--fx-rgb), 0.08); }
}

/* ==========================================================
   风格4：结构蓝图 Blueprint
   隐藏 ::before，纯白底工程图纸 + 主题色响应
   边框/图标/进度条均跟随当前主题色变化
   ========================================================== */
.fx-capsule-dock[data-fx-style="blueprint"] {
    border-radius: 0;
    background: #f0f0e8;
    border: 2px solid var(--fx-primary);
    box-shadow:
        3px 3px 0 rgba(0,0,0,0.10),
        inset 0 0 0 2px rgba(var(--fx-rgb), 0.06);
    padding: 6px 10px;
    gap: 3px;
    overflow: visible;
}
.fx-capsule-dock[data-fx-style="blueprint"]::before {
    display: none !important;
}
[data-fx-style="blueprint"] .fx-metric-item {
    background: rgba(255,255,255,0.85);
    border-radius: 0;
    border: 1px solid var(--fx-primary);
    padding: 5px 7px;
    box-shadow: none;
    position: relative;
}
/* 蓝图每个指标项左上角主题色标记 */
[data-fx-style="blueprint"] .fx-metric-item::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 4px;
    background: var(--fx-light);
}
[data-fx-style="blueprint"] .fx-metric-item:first-child {
    border-radius: 0;
    padding-left: 7px;
    border-left: 2px solid var(--fx-secondary);
}
[data-fx-style="blueprint"] .fx-metric-item:hover {
    background: rgba(var(--fx-rgb), 0.04);
    border-color: var(--fx-secondary);
    box-shadow: 2px 2px 0 rgba(0,0,0,0.08);
    transform: none;
}
[data-fx-style="blueprint"] .fx-progress-fill {
    background: repeating-linear-gradient(90deg, var(--fx-primary) 0, var(--fx-primary) 3px, transparent 3px, transparent 5px);
    border-radius: 0;
    box-shadow: none;
    animation: none;
}
[data-fx-style="blueprint"] .fx-progress-fill::after { animation: none; }
[data-fx-style="blueprint"] .fx-progress-bar {
    background: rgba(0,0,0,0.05);
    border-radius: 0;
    border: 1px solid rgba(var(--fx-rgb), 0.20);
}
[data-fx-style="blueprint"] .fx-metric-value {
    color: #1a1a2e;
    font-size: 12px;
    text-shadow: none;
    font-weight: 700;
    font-family: 'JetBrains Mono', 'Courier New', monospace;
}
[data-fx-style="blueprint"] .fx-metric-label {
    color: #4a5568;
    font-size: 8px;
    text-shadow: none;
    font-weight: 600;
    letter-spacing: 1px;
}
/* 蓝图图标：使用主题色变量，随主题切换而变化 */
[data-fx-style="blueprint"] .fx-icon-gpu {
    background: linear-gradient(135deg, var(--fx-primary), var(--fx-secondary)) !important;
    box-shadow: none !important;
}
[data-fx-style="blueprint"] .fx-icon-gpu::before {
    background:
        radial-gradient(circle at 25% 25%, var(--fx-light) 1px, transparent 1px),
        radial-gradient(circle at 75% 25%, var(--fx-light) 1px, transparent 1px),
        radial-gradient(circle at 25% 75%, var(--fx-light) 1px, transparent 1px),
        radial-gradient(circle at 75% 75%, var(--fx-light) 1px, transparent 1px);
}
[data-fx-style="blueprint"] .fx-icon-vram {
    background: linear-gradient(180deg, var(--fx-light), var(--fx-primary)) !important;
    box-shadow: none !important;
}
[data-fx-style="blueprint"] .fx-icon-vram::before {
    background: rgba(0,0,0,0.15) !important;
}
[data-fx-style="blueprint"] .fx-icon-cpu {
    background: linear-gradient(135deg, var(--fx-primary), var(--fx-secondary)) !important;
    box-shadow: none !important;
}
[data-fx-style="blueprint"] .fx-icon-cpu::before {
    background: #f0f0e8 !important;
}
[data-fx-style="blueprint"] .fx-icon-cpu::after {
    background: linear-gradient(135deg, var(--fx-light), var(--fx-primary)) !important;
}
[data-fx-style="blueprint"] .fx-icon-ram {
    background: linear-gradient(180deg, var(--fx-light), var(--fx-secondary)) !important;
    box-shadow: none !important;
}
[data-fx-style="blueprint"] .fx-icon-ram::before {
    background: repeating-linear-gradient(90deg, var(--fx-primary) 0px, var(--fx-primary) 2px, transparent 2px, transparent 3px) !important;
}
[data-fx-style="blueprint"] .fx-icon-swap {
    background: linear-gradient(180deg, var(--fx-light), var(--fx-secondary)) !important;
    box-shadow: none !important;
}
[data-fx-style="blueprint"] .fx-icon-swap::before,
[data-fx-style="blueprint"] .fx-icon-swap::after {
    background: rgba(0,0,0,0.15) !important;
}
[data-fx-style="blueprint"] .fx-icon-temp {
    background: linear-gradient(to bottom, var(--fx-light), var(--fx-primary), var(--fx-secondary)) !important;
    box-shadow: none !important;
}
[data-fx-style="blueprint"] .fx-icon-temp::after {
    background: var(--fx-primary) !important;
}
/* 蓝图数值无发光 */
[data-fx-style="blueprint"] .fx-metric-value {
    text-shadow: none !important;
}

/* ==========================================================
   风格5：极简像素 Pixel
   隐藏 ::before，纯方形无圆角 + 等宽像素字体 + 无动画
   复古终端/CRT监视器风格
   ========================================================== */
.fx-capsule-dock[data-fx-style="pixel"] {
    border-radius: 0;
    background: #0a0a0a;
    border: 2px solid #333;
    box-shadow: inset 0 0 0 1px #1a1a1a, 0 0 0 1px #000;
    padding: 2px 4px;
    gap: 2px;
    overflow: visible;
    font-family: 'Courier New', 'Consolas', monospace;
}
.fx-capsule-dock[data-fx-style="pixel"]::before {
    display: none !important;
}
[data-fx-style="pixel"] .fx-metric-item {
    background: #0d0d0d;
    border-radius: 0;
    border: 1px solid #2a2a2a;
    padding: 3px 5px;
    box-shadow: none;
    font-family: 'Courier New', 'Consolas', monospace;
}
[data-fx-style="pixel"] .fx-metric-item:first-child {
    border-radius: 0;
    padding-left: 5px;
    border-left: 2px solid var(--fx-primary);
}
[data-fx-style="pixel"] .fx-metric-item:hover {
    background: #111;
    border-color: var(--fx-primary);
    box-shadow: none;
    transform: none;
}
[data-fx-style="pixel"] .fx-progress-fill {
    background: var(--fx-primary);
    border-radius: 0;
    box-shadow: none;
    animation: none;
}
[data-fx-style="pixel"] .fx-progress-fill::after { animation: none; }
[data-fx-style="pixel"] .fx-progress-bar {
    background: #1a1a1a;
    border-radius: 0;
    border: 1px solid #222;
}
[data-fx-style="pixel"] .fx-metric-value {
    font-family: 'Courier New', 'Consolas', monospace;
    font-size: 10px;
    color: var(--fx-primary);
    text-shadow: none;
    font-weight: 700;
}
[data-fx-style="pixel"] .fx-metric-label {
    font-family: 'Courier New', 'Consolas', monospace;
    font-size: 8px;
    color: #666;
    text-shadow: none;
    letter-spacing: 0;
    text-transform: none;
}

/* ---------- 悬浮面板：循环切换按钮 ---------- */
.fxm-cycle-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 0;
}
.fxm-cycle-btn {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: 1px solid rgba(255,255,255,0.2);
    background: rgba(255,255,255,0.05);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
    flex-shrink: 0;
}
.fxm-cycle-btn:hover {
    border-color: var(--fx-primary);
    background: rgba(255,255,255,0.1);
}
.fxm-cycle-dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    display: block;
}
.fxm-cycle-icon {
    font-size: 14px;
}
.fxm-cycle-name {
    font-size: 12px;
    color: rgba(255,255,255,0.8);
    font-weight: 500;
}
`;

        document.head.appendChild(style);
        console.log('[飞雪监测器] ✅ Emerald Capsule CSS v13.0 已内联注入 (' + (style.textContent.length) + ' bytes)');
    }

    // ============================================================
    // UI 创建：顶部栏（Emerald Capsule v13.0 结构）
    // ============================================================

    /** 6个指标定义（严格顺序）— icon 改为 CSS class name */
    const METRIC_DEFS = [
        { key: 'gpu',         label: 'GPU',  iconClass: 'fx-icon-gpu',  unit: '%' },
        { key: 'vram',        label: 'VRAM', iconClass: 'fx-icon-vram', unit: 'GB' },
        { key: 'cpu',         label: 'CPU',  iconClass: 'fx-icon-cpu',  unit: '%' },
        { key: 'ram',         label: 'RAM',  iconClass: 'fx-icon-ram',  unit: '%' },
        { key: 'swap',        label: 'SWAP', iconClass: 'fx-icon-swap', unit: 'GB' },
        { key: 'temperature', label: 'TEMP', iconClass: 'fx-icon-temp', unit: '\u00B0C' },
    ];

    /**
     * 创建完整的顶部栏 DOM 结构
     * 匹配 v13.0 CSS 选择器：.fx-top-bar > .fx-capsule-dock > .fx-metric-item
     */
    function createTopBar() {
        // 顶部栏容器
        const topBar = document.createElement('div');
        topBar.className = 'fx-top-bar';
        topBar.id = 'fx-top-bar';

        // Dock 容器（胶囊形药丸底座）
        const dock = document.createElement('div');
        dock.className = 'fx-capsule-dock';
        dock.id = 'fx-capsule-dock';
        dock.setAttribute('data-fx-theme', 'emerald');

        // 创建6个胶囊指标
        METRIC_DEFS.forEach((metric) => {
            // 创建单个指标项
            const item = createMetricItem(metric);
            dock.appendChild(item);
        });

        // 设置按钮
        const settingsBtn = createSettingsButton();
        dock.appendChild(settingsBtn);

        topBar.appendChild(dock);
        document.body.appendChild(topBar);

        console.log(`[飞雪监测器] ✅ 顶栏已创建 (${METRIC_DEFS.length} 个翡翠胶囊)`);

        return topBar;
    }

    /**
     * 创建单个指标项元素
     * 结构精确匹配 v13.0 CSS：
     * .fx-metric-item[data-metric]
     *   > .fx-progress-bar > .fx-progress-fill
     *   > .fx-metric-content
     *     > .fx-metric-icon > .fx-icon-xxx
     *     > .fx-metric-info
     *       > .fx-metric-label
     *       > .fx-metric-value
     *
     * @param {Object} metric - 指标定义 { key, label, iconClass, unit }
     * @returns {HTMLElement}
     */
    function createMetricItem(metric) {
        const item = document.createElement('div');
        item.className = 'fx-metric-item';
        item.setAttribute('data-metric', metric.key);
        item.setAttribute('role', 'group');
        item.setAttribute('aria-label', `${metric.label} 监控`);

        // 渐变进度条
        const progressBar = document.createElement('div');
        progressBar.className = 'fx-progress-bar';

        const progressFill = document.createElement('div');
        progressFill.className = 'fx-progress-fill';
        progressFill.style.width = '0%';
        progressBar.appendChild(progressFill);

        // 内容区
        const content = document.createElement('div');
        content.className = 'fx-metric-content';

        // 图标容器（CSS绘制芯片图标）
        const iconDiv = document.createElement('div');
        iconDiv.className = 'fx-metric-icon';

        const chipIcon = document.createElement('div');
        chipIcon.className = metric.iconClass;
        chipIcon.setAttribute('aria-hidden', 'true');
        iconDiv.appendChild(chipIcon);

        // 信息区
        const infoDiv = document.createElement('div');
        infoDiv.className = 'fx-metric-info';

        // 标签
        const labelSpan = document.createElement('span');
        labelSpan.className = 'fx-metric-label';
        labelSpan.textContent = metric.label;

        // 数值（含单位内联）
        const valueWrapper = document.createElement('span');
        valueWrapper.className = 'fx-metric-value-row';

        const valueSpan = document.createElement('span');
        valueSpan.className = 'fx-metric-value';
        valueSpan.textContent = '--';

        // 单位
        const unitSpan = document.createElement('span');
        unitSpan.className = 'fx-metric-unit';
        unitSpan.textContent = metric.unit;

        valueWrapper.appendChild(valueSpan);
        valueWrapper.appendChild(unitSpan);

        infoDiv.appendChild(labelSpan);
        infoDiv.appendChild(valueWrapper);

        content.appendChild(iconDiv);
        content.appendChild(infoDiv);

        item.appendChild(progressBar);
        item.appendChild(content);

        return item;
    }

    /**
     * 创建设置按钮
     * @returns {HTMLElement}
     */
    function createSettingsButton() {
        const btn = document.createElement('button');
        btn.className = 'fx-settings-btn';
        btn.id = 'fx-settings-btn';
        btn.innerHTML = '\u2699'; // ⚙
        btn.setAttribute('aria-label', '打开详细监控面板');
        btn.title = '详细监控面板';

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleFloatingPanel();
        });

        return btn;
    }

    // ============================================================
    // 底部温度栏（GPU/CPU 温度）
    // ============================================================

    /**
     * 创建底部温度栏
     * 匹配 v13.0 CSS：.fxm-bottom-bar > .fxm-bottom-dock > .fxm-temp-item
     */
    function createBottomBar() {
        const bottomBar = document.createElement('div');
        bottomBar.className = 'fxm-bottom-bar';
        bottomBar.id = 'fxm-bottom-bar';

        const bottomDock = document.createElement('div');
        bottomDock.className = 'fxm-bottom-dock';
        bottomDock.id = 'fxm-bottom-dock';

        // GPU 温度项
        const gpuTempItem = createTempItem('fxm-gpu-temp-item', 'GPU温度', 'fxm-gpu-temp-value', 'fxm-gpu-temp-progress');
        bottomDock.appendChild(gpuTempItem);

        // 分隔线
        const divider = document.createElement('div');
        divider.className = 'fxm-bottom-divider';
        bottomDock.appendChild(divider);

        // CPU 温度项
        const cpuTempItem = createTempItem('fxm-cpu-temp-item', 'CPU温度', 'fxm-cpu-temp-value', 'fxm-cpu-temp-progress');
        bottomDock.appendChild(cpuTempItem);

        bottomBar.appendChild(bottomDock);
        document.body.appendChild(bottomBar);

        console.log('[飞雪监测器] ✅ 底部温度栏已创建');

        return bottomBar;
    }

    /**
     * 创建单个温度显示项
     * @param {string} itemId - 项ID
     * @param {string} labelText - 标签文字
     * @param {string} valueId - 数值span ID
     * @param {string} progressId - 进度条 ID
     * @returns {HTMLElement}
     */
    function createTempItem(itemId, labelText, valueId, progressId) {
        const item = document.createElement('div');
        item.className = 'fxm-temp-item';
        item.id = itemId;

        // 标签
        const label = document.createElement('span');
        label.className = 'fxm-temp-label';
        label.textContent = labelText;

        // 数值容器
        const valueWrapper = document.createElement('div');
        valueWrapper.className = 'fxm-temp-value-wrapper';

        const value = document.createElement('span');
        value.className = 'fxm-temp-value';
        value.id = valueId;
        value.textContent = '--';

        const unit = document.createElement('span');
        unit.className = 'fxm-temp-unit';
        unit.textContent = '\u00B0C'; // °C

        valueWrapper.appendChild(value);
        valueWrapper.appendChild(unit);

        // 进度条容器
        const progressWrapper = document.createElement('div');
        progressWrapper.className = 'fxm-temp-progress-wrapper';

        const progressBar = document.createElement('div');
        progressBar.className = 'fxm-temp-progress-bar';
        progressBar.id = progressId;
        progressBar.style.width = '0%';

        progressWrapper.appendChild(progressBar);

        item.appendChild(label);
        item.appendChild(valueWrapper);
        item.appendChild(progressWrapper);

        return item;
    }

    // ============================================================
    // 悬浮面板（Floating Panel）- Emerald Capsule v13.0
    // ============================================================

    let floatingPanel = null;
    let isPanelVisible = false;
    let dragInitialized = false;       // 防止重复初始化拖拽

    /**
     * 切换悬浮面板显示状态
     */
    function toggleFloatingPanel() {
        if (!floatingPanel) {
            createFloatingPanel();
            // 首次创建面板后初始化拖拽功能
            if (!dragInitialized) {
                dragInitialized = true;
                initDrag();
            }
        }

        isPanelVisible = !isPanelVisible;

        if (isPanelVisible) {
            floatingPanel.classList.remove('fxm-hidden');
            floatingPanel.classList.add('fxm-visible');
            // 更新面板数据
            updateFloatingPanelData(cachedData);
        } else {
            floatingPanel.classList.remove('fxm-visible');
            floatingPanel.classList.add('fxm-hidden');
        }

        console.log(`[飞雪监测器] 悬浮面板: ${isPanelVisible ? '展开' : '收起'}`);
    }

    /**
     * 创建悬浮面板（Emerald Capsule v13.0 结构）
     * 匹配 CSS 类名：.fxm-floating-panel / .fxm-panel-header 等
     */
    function createFloatingPanel() {
        const panel = document.createElement('div');
        panel.className = 'fxm-floating-panel fxm-hidden';
        panel.id = 'fxm-floating-panel';
        panel.setAttribute('data-fx-theme', currentTheme);

        panel.innerHTML = `
            <div class="fxm-panel-header">
                <div class="fxm-panel-title-wrapper">
                    <span class="fxm-panel-title">飞雪监测器</span>
                    <span class="fxm-panel-version">v3.0</span>
                </div>
                <button class="fxm-btn fxm-btn-close" aria-label="关闭面板" title="关闭">&times;</button>
            </div>

            <div class="fxm-panel-content">
                <div class="fxm-panel-glass-accent"></div>

                <div class="fxm-theme-section">
                    <div class="fxm-section-label">🎨 外观</div>
                    <div class="fxm-cycle-row">
                        <button class="fxm-cycle-btn" id="fxm-theme-cycle" title="切换颜色主题">
                            <span class="fxm-cycle-dot" id="fxm-theme-dot"></span>
                        </button>
                        <span class="fxm-cycle-name" id="fxm-theme-name">翡翠绿</span>
                        <button class="fxm-cycle-btn" id="fxm-style-cycle" title="切换风格预设" style="margin-left:16px">
                            <span class="fxm-cycle-icon">🎨</span>
                        </button>
                        <span class="fxm-cycle-name" id="fxm-style-name">翡翠胶囊</span>
                    </div>
                </div>

                <!-- 系统详情 -->
                <div class="fxm-system-details">
                    <div class="fxm-section-label">📊 系统详情</div>
                    <div class="fxm-detail-row" id="fxm-disk-row">
                        <span class="fxm-detail-icon">💾</span>
                        <span class="fxm-detail-label">磁盘</span>
                        <span class="fxm-detail-value" id="fxm-disk-value">--</span>
                    </div>
                    <div class="fxm-detail-row" id="fxm-net-row">
                        <span class="fxm-detail-icon">🌐</span>
                        <span class="fxm-detail-label">网络</span>
                        <span class="fxm-detail-value" id="fxm-net-value">--</span>
                    </div>
                </div>

                <!-- 拖拽开关 -->
                <div class="fxm-toggle-section">
                    <div class="fxm-section-label">🖱️ 面板位置</div>
                    <div class="fxm-toggle-row">
                        <span class="fxm-toggle-label">
                            <span class="fxm-toggle-icon">\u{2702}</span>启用拖拽
                        </span>
                        <label class="fxm-toggle-switch">
                            <input type="checkbox" id="fxm-drag-toggle">
                            <span class="fxm-toggle-slider"></span>
                        </label>
                    </div>
                </div>

                <!-- 数据卡片区域 -->
                <div class="fxm-data-cards" id="fxm-data-cards">
                    <!-- GPU 卡片 -->
                    <div class="fxm-data-card">
                        <div class="fxm-card-header">
                            <span class="fxm-card-title"><div class="fx-icon-gpu" style="transform:scale(1.2);display:inline-block;"></div>显卡信息</span>
                        </div>
                        <div class="fxm-card-content">
                            <div class="fxm-card-metric">
                                <span class="fxm-card-label">利用率</span>
                                <div class="fxm-card-progress"><div class="fxm-card-progress-bar" id="fp-card-gpu-util-pb"></div></div>
                                <span class="fxm-card-value" id="fp-card-gpu-util">--%</span>
                            </div>
                            <div class="fxm-card-metric">
                                <span class="fxm-card-label">显存占用</span>
                                <div class="fxm-card-progress"><div class="fxm-card-progress-bar" id="fp-card-vram-pb"></div></div>
                                <span class="fxm-card-value" id="fp-card-vram">--%</span>
                            </div>
                            <div class="fxm-card-metric">
                                <span class="fxm-card-label">温度</span>
                                <div class="fxm-card-progress"><div class="fxm-card-progress-bar" id="fp-card-gpu-temp-pb"></div></div>
                                <span class="fxm-card-value" id="fp-card-gpu-temp">--\u00B0C</span>
                            </div>
                        </div>
                    </div>

                    <!-- CPU & 内存卡片 -->
                    <div class="fxm-data-card">
                        <div class="fxm-card-header">
                            <span class="fxm-card-title"><div class="fx-icon-cpu" style="transform:scale(1.2);display:inline-block;"></div>处理器与内存</span>
                        </div>
                        <div class="fxm-card-content">
                            <div class="fxm-card-metric">
                                <span class="fxm-card-label">CPU 占用</span>
                                <div class="fxm-card-progress"><div class="fxm-card-progress-bar" id="fp-card-cpu-pb"></div></div>
                                <span class="fxm-card-value" id="fp-card-cpu">--%</span>
                            </div>
                            <div class="fxm-card-metric">
                                <span class="fxm-card-label">物理内存</span>
                                <div class="fxm-card-progress"><div class="fxm-card-progress-bar" id="fp-card-ram-pb"></div></div>
                                <span class="fxm-card-value" id="fp-card-ram">--%</span>
                            </div>
                            <div class="fxm-card-metric">
                                <span class="fxm-card-label">虚拟内存</span>
                                <div class="fxm-card-progress"><div class="fxm-card-progress-bar" id="fp-card-swap-pb"></div></div>
                                <span class="fxm-card-value" id="fp-card-swap">--%</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 状态栏 -->
                <div class="fxm-status-bar">
                    <span class="fxm-status-item"><span class="fxm-status-dot"></span><span id="fp-source-text">检测中...</span></span>
                    <span>飞雪监测器 v3.0</span>
                </div>
            </div>
        `;

        // ---- 绑定事件 ----

        // 关闭按钮
        const closeBtn = panel.querySelector('.fxm-btn-close');
        closeBtn.addEventListener('click', () => {
            toggleFloatingPanel();
        });

        // ESC 键关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && isPanelVisible) {
                toggleFloatingPanel();
            }
        });

        document.body.appendChild(panel);
        floatingPanel = panel;

        // 初始化主题循环按钮
        const themeCycleBtn = panel.querySelector('#fxm-theme-cycle');
        if (themeCycleBtn) {
            themeCycleBtn.addEventListener('click', () => {
                const themeKeys = Object.keys(THEMES);
                const currentIndex = themeKeys.indexOf(currentTheme);
                const nextKey = themeKeys[(currentIndex + 1) % themeKeys.length];
                applyTheme(nextKey);
            });
        }

        // 初始化风格循环按钮
        const styleCycleBtn = panel.querySelector('#fxm-style-cycle');
        if (styleCycleBtn) {
            styleCycleBtn.addEventListener('click', () => {
                const styleKeys = Object.keys(STYLES);
                const currentIndex = styleKeys.indexOf(currentStyle);
                const nextKey = styleKeys[(currentIndex + 1) % styleKeys.length];
                applyStyle(nextKey);
            });
        }

        // 同步当前主题和风格的循环按钮显示
        syncThemeButtons(currentTheme);
        syncStyleButtons(currentStyle);

        console.log('[飞雪监测器] ✅ 悬浮面板已创建 (Emerald Capsule v13.0)');
    }

    // ============================================================
    // 数据更新函数
    // ============================================================

    /**
     * 批量更新所有指标项的数据
     * 查询选择器：.fx-metric-item[data-metric="xxx"]
     *
     * @param {Object} data - 标准化后的系统数据
     */
    function updateAllCapsules(data) {
        if (!data) {
            console.warn('[飞雪监测器] ⚠️ 无数据可更新');
            return;
        }

        requestAnimationFrame(() => {
            const items = document.querySelectorAll('.fx-metric-item[data-metric]');
            let updatedCount = 0;

            items.forEach((item) => {
                const metricKey = item.dataset.metric;
                const valueEl = item.querySelector('.fx-metric-value');
                const statusFillEl = item.querySelector('.fx-progress-fill');

                if (!valueEl || !statusFillEl) return;

                // 根据 metricKey 提取对应数值
                let rawValue = null;
                let displayText = '--';
                let percentForBar = 0;
                let isDanger = false;

                switch (metricKey) {
                    case 'gpu':
                        rawValue = sanitizeValue(data.gpu?.usage);
                        if (rawValue !== null) {
                            displayText = Math.round(rawValue).toString();
                            percentForBar = Math.min(rawValue, 100);
                            isDanger = rawValue >= CONFIG.thresholds.danger;
                        }
                        break;

                    case 'vram':
                        // 显存显示 GB 单位（vram_used 为 MB，需转换为 GB）
                        const vramUsedMB = sanitizeValue(data.gpu?.vram_used);
                        const vramPercent = sanitizeValue(data.gpu?.vram_percent);
                        if (vramUsedMB !== null) {
                            // MB -> GB，保留一位小数
                            displayText = (vramUsedMB / 1024).toFixed(1);
                            percentForBar = (vramPercent !== null) ? Math.min(vramPercent, 100) : 0;
                            isDanger = (vramPercent !== null && vramPercent >= CONFIG.thresholds.danger);
                        } else if (vramPercent !== null) {
                            displayText = '--';
                            percentForBar = Math.min(vramPercent, 100);
                            isDanger = vramPercent >= CONFIG.thresholds.danger;
                        }
                        break;

                    case 'cpu':
                        rawValue = sanitizeValue(data.cpu?.usage);
                        if (rawValue !== null) {
                            displayText = Math.round(rawValue).toString();
                            percentForBar = Math.min(rawValue, 100);
                            isDanger = rawValue >= CONFIG.thresholds.danger;
                        }
                        break;

                    case 'ram':
                        rawValue = sanitizeValue(data.ram?.percent);
                        if (rawValue !== null) {
                            displayText = Math.round(rawValue).toString();
                            percentForBar = Math.min(rawValue, 100);
                            isDanger = rawValue >= CONFIG.thresholds.danger;
                        }
                        break;

                    case 'swap':
                        // 虚拟内存：显示GB占用，进度条用百分比
                        rawValue = sanitizeValue(data.swap?.used_gb);
                        if (rawValue === null) {
                            rawValue = sanitizeValue(getValueByPath(data, 'swap.used'))
                                      || sanitizeValue(getValueByPath(data, 'ram.swap_used_gb'))
                                      || sanitizeValue(getValueByPath(data, 'swap.total_gb'));
                        }
                        // 进度条仍用百分比
                        percentForBar = Math.min(
                            sanitizeValue(data.swap?.percent) || 0, 100
                        );
                        // 防止误取到percent值（percent通常<100，而used_gb可能>=1）
                        // 如果rawValue等于percent且<100，说明可能取错了，强制为null走fallback显示0
                        if (rawValue !== null && rawValue < 2 && rawValue === sanitizeValue(data.swap?.percent)) {
                            console.warn('[飞雪监测器] ⚠️ SWAP值异常（可能是percent而非GB）:', rawValue, '→ 重置为0');
                            rawValue = 0;
                        }
                        if (rawValue !== null && rawValue > 0) {
                            displayText = rawValue.toFixed(1);
                            isDanger = percentForBar >= CONFIG.thresholds.danger;
                        } else {
                            // 所有路径均无数据时显示 0 而非 --
                            displayText = '0';
                            percentForBar = 0;
                        }
                        break;

                    case 'temperature':
                        rawValue = sanitizeValue(data.gpu?.temperature);
                        if (rawValue !== null) {
                            displayText = Math.round(rawValue).toString();
                            // 温度进度条：假设 0-100°C 映射到 0-100%
                            percentForBar = Math.min(Math.max(rawValue, 0), 100);
                            // 温度危险阈值：>85°C 视为危险
                            isDanger = rawValue > 85;
                        }
                        break;

                    default:
                        console.warn(`[飞雪监测器] 未知指标: ${metricKey}`);
                        return;
                }

                // 更新数值文本（过滤乱码如"英国"）
                valueEl.textContent = sanitizeDisplayText(displayText);

                // 更新渐变进度条宽度
                statusFillEl.style.width = percentForBar + '%';

                // 危险状态处理 (>90% 或温度>85°C)
                if (isDanger) {
                    item.classList.add('fx-metric--danger');
                } else {
                    item.classList.remove('fx-metric--danger');
                }

                updatedCount++;
            });

            if (updatedCount > 0) {
                console.log(`[飞雪监测器] ✨ 已更新 ${updatedCount}/${items.length} 个翡翠胶囊`);
            }
        });
    }

    /**
     * 更新底部温度栏数据
     * @param {Object} data - 标准化后的系统数据
     */
    function updateBottomBarData(data) {
        if (!data) return;

        requestAnimationFrame(() => {
            // GPU 温度
            const gpuTempValueEl = document.getElementById('fxm-gpu-temp-value');
            const gpuTempProgressEl = document.getElementById('fxm-gpu-temp-progress');

            if (gpuTempValueEl && gpuTempProgressEl) {
                const gpuTemp = sanitizeValue(data.gpu?.temperature);
                if (gpuTemp !== null) {
                    gpuTempValueEl.textContent = Math.round(gpuTemp).toString();
                    gpuTempProgressEl.style.width = Math.min(Math.max(gpuTemp, 0), 100) + '%';
                } else {
                    gpuTempValueEl.textContent = '--';
                    gpuTempProgressEl.style.width = '0%';
                }
            }

            // CPU 温度（当前后端可能不提供独立CPU温度，尝试从数据中获取）
            const cpuTempValueEl = document.getElementById('fxm-cpu-temp-value');
            const cpuTempProgressEl = document.getElementById('fxm-cpu-temp-progress');

            if (cpuTempValueEl && cpuTempProgressEl) {
                // 尝试获取 CPU 温度（如果后端支持），否则显示 --
                // 注意：当前 collectSystemData 不包含 cpu.temperature，这里预留扩展点
                const cpuTemp = sanitizeValue(data.cpu?.temperature);
                if (cpuTemp !== null) {
                    cpuTempValueEl.textContent = Math.round(cpuTemp).toString();
                    cpuTempProgressEl.style.width = Math.min(Math.max(cpuTemp, 0), 100) + '%';
                } else {
                    cpuTempValueEl.textContent = '--';
                    cpuTempProgressEl.style.width = '0%';
                }
            }
        });
    }

    /**
     * 更新悬浮面板数据（v13.0 选择器）
     * @param {Object} data - 标准化后的系统数据
     */
    function updateFloatingPanelData(data) {
        if (!floatingPanel || !data) return;

        requestAnimationFrame(() => {
            // ---- GPU 卡片数据 ----
            updateCardMetric('fp-card-gpu-util', 'fp-card-gpu-util-pb', data.gpu?.usage, '%', 100);
            updateCardMetric('fp-card-vram', 'fp-card-vram-pb', data.gpu?.vram_percent, '%', 100);

            // GPU 温度（特殊处理：单位 °C，映射到 0-100% 进度条）
            const gpuTempEl = document.getElementById('fp-card-gpu-temp');
            const gpuTempPbEl = document.getElementById('fp-card-gpu-temp-pb');
            if (gpuTempEl && gpuTempPbEl) {
                const temp = sanitizeValue(data.gpu?.temperature);
                if (temp !== null) {
                    gpuTempEl.textContent = Math.round(temp) + '\u00B0C';
                    gpuTempPbEl.style.width = Math.min(Math.max(temp, 0), 100) + '%';
                } else {
                    gpuTempEl.textContent = '--\u00B0C';
                    gpuTempPbEl.style.width = '0%';
                }
            }

            // ---- CPU & 内存卡片数据 ----
            updateCardMetric('fp-card-cpu', 'fp-card-cpu-pb', data.cpu?.usage, '%', 100);
            updateCardMetric('fp-card-ram', 'fp-card-ram-pb', data.ram?.percent, '%', 100);
            updateCardMetric('fp-card-swap', 'fp-card-swap-pb', data.swap?.used_gb, 'GB', 100);

            // ---- 状态栏（带缓存，避免文本闪烁） ----
            const sourceTextEl = document.getElementById('fp-source-text');
            if (sourceTextEl) {
                let newSourceText;
                if (backendAvailable) {
                    const SOURCE_NAMES = {
                        'windows_wmi': 'Windows (WMI)',
                        'amdsmi': 'AMD SMI',
                        'rocm_smi': 'ROCm SMI',
                        'sysfs': 'Linux sysfs',
                        'error_fallback': 'Fallback',
                        'none': 'None',
                    };
                    const src = data.data_source || 'Connected';
                    const friendly = SOURCE_NAMES[src] || src;
                    newSourceText = `Source: ${friendly}`;
                } else {
                    newSourceText = 'Source: Disconnected';
                }
                // 只在文本真正变化时才更新 DOM
                if (sourceTextEl.textContent !== newSourceText) {
                    sourceTextEl.textContent = newSourceText;
                }
            }
        });
    }

    /**
     * 辅助函数：更新卡片中的单个度量项
     * @param {string} valueId - 数值元素 ID
     * @param {string} progressId - 进度条元素 ID
     * @param {*} rawValue - 原始数值
     * @param {string} unit - 单位字符串
     * @param {number} maxPercent - 最大百分比（用于进度条映射）
     */
    function updateCardMetric(valueId, progressId, rawValue, unit, maxPercent) {
        const valueEl = document.getElementById(valueId);
        const progressEl = document.getElementById(progressId);

        if (!valueEl || !progressEl) return;

        const cleaned = sanitizeValue(rawValue);
        if (cleaned !== null) {
            valueEl.textContent = Math.round(cleaned) + unit;
            progressEl.style.width = Math.min(cleaned, maxPercent) + '%';
        } else {
            valueEl.textContent = '--' + unit;
            progressEl.style.width = '0%';
        }
    }

    // ============================================================
    // 主循环和初始化
    // ============================================================

    /** @type {number|null} 定时器 ID */
    let updateTimer = null;

    /**
     * 更新系统详情区域（磁盘、网络）
     * @param {Object} rawData - WebSocket/REST 推送的原始 snapshot 数据
     */
    function updateSystemDetails(rawData) {
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

    /**
     * 主更新循环
     */
    async function mainUpdateLoop() {
        try {
            // 1. 采集数据
            const data = await collectSystemData();

            // 2. 更新顶栏翡翠胶囊
            updateAllCapsules(data);

            // 3. [已禁用] 更新底部温度栏
            // updateBottomBarData(data);

            // 4. 如果悬浮面板可见，同步更新面板数据
            if (isPanelVisible && floatingPanel) {
                updateFloatingPanelData(data);
            }

            // 5. 更新系统详情（磁盘、网络）
            updateSystemDetails(cachedData);

        } catch (e) {
            console.error('[飞雪监测器] ❌ 更新循环异常:', e);
        }

        // 安排下一次更新
        updateTimer = setTimeout(mainUpdateLoop, CONFIG.updateInterval);
    }

    /**
     * 初始化并启动监测器
     *
     * 启动流程：
     * 1. 注入 CSS（Emerald Capsule v13.0 内联样式）
     * 2. 创建顶部栏
     * 3. 创建底部温度栏
     * 4. 恢复已保存的主题
     * 5. 启动数据更新循环
     */
    async function init() {
        console.log('[飞雪监测器] 🚀 Emerald Capsule v13.0 启动...');

        try {
            // 1. 注入 CSS（Emerald Capsule v13.0 内联样式）
            injectGemstoneCSS();

            // 2. 创建顶部栏
            createTopBar();

            // 3. [已禁用] 创建底部温度栏
            // createBottomBar();

            // 4. 恢复已保存的主题
            restoreTheme();

            // 4.1 恢复已保存的风格
            restoreStyle();

            // 4.6 从 localStorage 恢复拖拽位置（面板未打开时也能还原）
            const savedPos = localStorage.getItem(DRAG_STORAGE_KEY);
            if (savedPos) {
                try {
                    const pos = JSON.parse(savedPos);
                    if (typeof pos.left === 'number' && typeof pos.top === 'number') {
                        const topBar = document.querySelector('.fx-top-bar');
                        if (topBar) {
                            topBar.style.left = pos.left + 'px';
                            topBar.style.top = pos.top + 'px';
                            topBar.style.transform = 'none';
                            topBar.style.transition = 'none';
                            savedBarLeft = pos.left;
                            savedBarTop = pos.top;
                        }
                    }
                } catch (e) { /* ignore */ }
            }

            // 5. 启动数据更新循环
            await mainUpdateLoop();

            console.log('[飞雪监测器] ✅ 启动完成 (v' + CONFIG.version + ')');

        } catch (e) {
            console.error('[飞雪监测器] ❌ 初始化失败:', e);
        }
    }

    // ============================================================
    // 拖拽功能
    // ============================================================

    /**
     * 初始化拖拽功能
     * - 监听面板中的拖拽开关
     * - 加载 localStorage 中的保存位置
     * - 绑定 mousedown/mousemove/mouseup 事件
     */
    function initDrag() {
        const topBar = document.querySelector('.fx-top-bar');
        const dock = document.querySelector('.fx-capsule-dock');
        const toggleEl = document.getElementById('fxm-drag-toggle');
        if (!topBar || !dock || !toggleEl) return;

        // 1. 从 localStorage 恢复拖拽开关状态
        const savedEnabled = localStorage.getItem('feixue_drag_enabled');
        if (savedEnabled === 'true') {
            dragEnabled = true;
            toggleEl.checked = true;
            dock.classList.add('fx-draggable');
        }

        // 2. 从 localStorage 恢复位置
        const savedPos = localStorage.getItem(DRAG_STORAGE_KEY);
        if (savedPos) {
            try {
                const pos = JSON.parse(savedPos);
                if (typeof pos.left === 'number' && typeof pos.top === 'number') {
                    savedBarLeft = pos.left;
                    savedBarTop = pos.top;
                    applyBarPosition(pos.left, pos.top);
                }
            } catch (e) { /* ignore parse error */ }
        }

        // 3. 拖拽开关事件
        toggleEl.addEventListener('change', function() {
            dragEnabled = this.checked;
            localStorage.setItem('feixue_drag_enabled', dragEnabled ? 'true' : 'false');

            if (dragEnabled) {
                dock.classList.add('fx-draggable');
            } else {
                dock.classList.remove('fx-draggable');
                // 关闭拖拽时重置居中
                resetBarToCenter();
                localStorage.removeItem(DRAG_STORAGE_KEY);
                savedBarLeft = null;
                savedBarTop = null;
            }
        });

        // 4. mousedown: 开始拖拽（只在 dock 上且启用了拖拽时）
        dock.addEventListener('mousedown', function(e) {
            if (!dragEnabled) return;

            // 排除交互元素：按钮、输入框、可点击的指标项
            const tag = e.target.tagName;
            if (tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'LABEL') return;
            if (e.target.closest('.fx-settings-btn, .fxm-toggle-switch, .fx-theme-btn, .fxm-theme-chip, .fxm-style-chip')) return;

            e.preventDefault();
            isDragging = true;
            dragStartX = e.clientX;
            dragStartY = e.clientY;

            const rect = topBar.getBoundingClientRect();
            barStartLeft = rect.left;
            barStartTop = rect.top;

            topBar.classList.add('fx-dragging');
            topBar.style.transition = 'none';
        });

        // 5. mousemove: 更新位置
        document.addEventListener('mousemove', function(e) {
            if (!isDragging) return;

            const dx = e.clientX - dragStartX;
            const dy = e.clientY - dragStartY;
            let newLeft = barStartLeft + dx;
            let newTop = barStartTop + dy;

            // 边界限制
            const maxLeft = window.innerWidth - dock.offsetWidth - 16;
            const maxTop = window.innerHeight - dock.offsetHeight - 16;
            newLeft = Math.max(8, Math.min(newLeft, maxLeft));
            newTop = Math.max(40, Math.min(newTop, maxTop));  // 顶部留 40px 给 ComfyUI 菜单栏

            topBar.style.left = newLeft + 'px';
            topBar.style.top = newTop + 'px';
            topBar.style.transform = 'none';

            savedBarLeft = newLeft;
            savedBarTop = newTop;
        });

        // 6. mouseup: 结束拖拽，保存位置
        document.addEventListener('mouseup', function() {
            if (!isDragging) return;
            isDragging = false;
            topBar.classList.remove('fx-dragging');

            if (savedBarLeft !== null && savedBarTop !== null) {
                localStorage.setItem(DRAG_STORAGE_KEY, JSON.stringify({
                    left: savedBarLeft,
                    top: savedBarTop
                }));
            }
        });
    }

    /**
     * 应用 bar 位置
     */
    function applyBarPosition(left, top) {
        const topBar = document.querySelector('.fx-top-bar');
        if (!topBar) return;
        topBar.style.left = left + 'px';
        topBar.style.top = top + 'px';
        topBar.style.transform = 'none';
        topBar.style.transition = 'none';
    }

    /**
     * 重置 bar 到居中位置
     */
    function resetBarToCenter() {
        const topBar = document.querySelector('.fx-top-bar');
        if (!topBar) return;
        topBar.style.left = '50%';
        topBar.style.top = '8px';
        topBar.style.transform = 'translateX(-50%)';
        topBar.style.transition = '0.4s ease';
    }

    // ============================================================
    // 导出全局对象供外部访问和调试
    // ============================================================

    window.FeixueMonitor = {
        version: CONFIG.version,
        config: CONFIG,

        // 状态查询
        isInitialized: true,
        isRunning: backendAvailable,
        lastUpdate: () => lastFetchTime,
        cachedData: () => cachedData,

        // 手动触发更新
        refresh: mainUpdateLoop,

        // 主题控制
        getCurrentTheme: () => currentTheme,
        setTheme: applyTheme,

        // 风格控制
        getCurrentStyle: () => currentStyle,
        setStyle: applyStyle,
        getStyleList: () => STYLES,
    };

    console.log('[飞雪监测器] 📦 全局对象已导出: window.FeixueMonitor');

    // DOM 加载完成后启动
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM 已经就绪
        init();
    }

})();
