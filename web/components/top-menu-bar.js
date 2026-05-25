/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - Top Menu Bar (顶部菜单栏监控胶囊)
 * ============================================================================
 *
 * 固定在 ComfyUI 顶部菜单栏右侧的 7 个实时监控指标胶囊组件。
 *
 * 功能特性：
 * - 渲染 7 个 MetricCard（PRED / CPU / RAM / GPU / VRAM / RSV / PWR）
 * - 响应式布局（Flexbox，小屏幕 < 1200px 自动隐藏次要指标 RSV/PWR）
 * - 实时数据更新（通过 DataService 事件驱动）
 * - 悬停 Tooltip 详情展示（历史趋势 Sparkline + 统计信息）
 * - 点击事件（展开 HoverPanel 或显示详情）
 * - 颜色编码（绿 < 60% / 黄 60-80% / 红 > 80%）
 * - 毛玻璃背景 + 入场动画
 *
 * 7 个监控指标：
 * ┌─────────────────────────────────────────────────────────────┐
 * │ [📊 PRED 85.5%] [🔲 CPU 45.2%] [💾 RAM 62.1%] [⚡ GPU 78%] │
 * │ [🎮 VRAM 60%]   [🔄 RSV 2.1GB]  [🔋 PWR 180W]            │
 * └─────────────────────────────────────────────────────────────┘
 *
 * 数据流：
 *   DataService (WebSocket/Polling)
 *     → emit('data', snapshot)
 *       → TopMenuBar.update(data)
 *         → MetricCard.updateValue(value) × 7
 *           → DOM 更新 + 颜色状态切换
 *
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

// =============================================================================
// CSS Styles (Injected once at module load time)
// =============================================================================

/**
 * TopMenuBar 和 MetricCard 的完整样式定义。
 * 使用 Design Tokens 变量保持主题一致性。
 * 通过一次性注入 <style> 标签避免外部 CSS 文件依赖。
 *
 * 样式组织结构：
 * 1. 容器 (.fxm-topmenubar) - 毛玻璃背景、固定定位、入场动画
 * 2. 单个指标卡片 (.fxm-metric-card) - 胶囊形状、悬停效果
 * 3. 内部元素（图标/标签/数值/单位）- 排版与对齐
 * 4. 状态颜色 (.fxm-status-low/medium/high) - 阈值颜色编码
 * 5. Tooltip 弹出层 (.fxm-tooltip) - 玻璃面板、统计信息
 * 6. 响应式断点 (< 1200px 隐藏次要指标)
 * 7. 动画关键帧 (slideInRight, fadeIn)
 * 8. 无障碍 (prefers-reduced-motion)
 * @private
 */
const TOPMENUBAR_CSS = `
/* ==========================================================================
   1. Top Menu Bar Container (顶部菜单栏容器)
   ========================================================================== */

.fxm-topmenubar {
  display: flex;
  align-items: center;
  gap: var(--fxm-space-1, 4px);
  padding: var(--fxm-space-1, 4px) var(--fxm-space-2, 8px);
  position: fixed;
  top: var(--fxm-space-2, 8px);
  right: 200px;
  z-index: var(--fxm-z-top-menu-bar, 1000);
  font-family: var(--fxm-font-mono, 'JetBrains Mono', monospace);
  font-size: var(--fxm-font-size-xs, 10px);

  /* Glassmorphism background */
  background: var(--fxm-glass-bg, rgba(17, 24, 39, 0.85));
  backdrop-filter: var(--fxm-glass-blur, blur(20px));
  -webkit-backdrop-filter: var(--fxm-glass-blur, blur(20px));
  border: 1px solid var(--fxm-glass-border, rgba(255, 255, 255, 0.08));
  border-radius: var(--fxm-radius-full, 9999px);

  /* Prevent layout shift with fixed dimensions */
  min-height: var(--fxm-topmenu-capsule-h, 28px);
  box-sizing: border-box;

  /* Subtle shadow for depth */
  box-shadow:
    0 2px 8px rgba(0, 0, 0, 0.25),
    0 0 0 1px rgba(255, 255, 255, 0.04);

  /* Entry animation */
  animation: fxm-tmb-slideInRight 0.35s var(--fxm-ease-out-back, cubic-bezier(0.16, 1, 0.3, 1)) both;

  /* User select disabled for app-like feel */
  user-select: none;
  -webkit-user-select: none;

  /* Hide by default until init() completes */
  opacity: 0;
}

.fxm-topmenubar.fxm-visible {
  opacity: 1;
}

/* Hidden state */
.fxm-topmenubar.fxm-hidden {
  display: none !important;
}

/* ==========================================================================
   2. Metric Card (单个指标胶囊卡片)
   ========================================================================== */

.fxm-metric-card {
  display: inline-flex;
  align-items: center;
  gap: var(--fxm-space-1, 4px);
  padding: 2px var(--fxm-space-2, 8px);
  border-radius: var(--fxm-radius-full, 9999px);
  cursor: pointer;
  position: relative;
  white-space: nowrap;
  line-height: 1.2;

  /* Smooth transitions */
  transition:
    background-color var(--fxm-duration-fast, 150ms) var(--fxm-ease-out, cubic-bezier(0, 0, 0.2, 1)),
    transform var(--fxm-duration-fast, 150ms) var(--fxm-ease-out, cubic-bezier(0, 0, 0.2, 1)),
    box-shadow var(--fxm-duration-fast, 150ms) var(--fxm-ease-out, cubic-bezier(0, 0, 0.2, 1));

  /* Default transparent background */
  background-color: transparent;
}

/* Hover state */
.fxm-metric-card:hover {
  background-color: rgba(255, 255, 255, 0.08);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* Active/pressed state */
.fxm-metric-card:active {
  transform: translateY(0);
  background-color: rgba(255, 255, 255, 0.12);
}

/* Focus state for keyboard navigation */
.fxm-metric-card:focus-visible {
  outline: 2px solid var(--fxm-focus-ring-color, rgba(0, 212, 255, 0.6));
  outline-offset: 2px;
}

/* Hidden card (data-driven visibility) */
.fxm-metric-card.fxm-card-hidden {
  display: none !important;
}

/* ==========================================================================
   3. Card Internal Elements (卡片内部元素)
   ========================================================================== */

/* Icon */
.fxm-metric-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--fxm-topmenu-icon-size, 14px);
  height: var(--fxm-topmenu-icon-size, 14px);
  font-size: var(--fxm-topmenu-icon-size, 14px);
  line-height: 1;
  flex-shrink: 0;
  opacity: 0.85;
  transition: opacity var(--fxm-duration-fast, 150ms) ease;
}

.fxm-metric-card:hover .fxm-metric-icon {
  opacity: 1;
}

/* Label (PRED, CPU, RAM, etc.) */
.fxm-metric-label {
  font-weight: var(--fxm-font-weight-semibold, 600);
  font-size: var(--fxm-font-size-xs, 10px);
  letter-spacing: var(--fxm-letter-spacing-label, 1px);
  text-transform: uppercase;
  color: var(--fxm-text-secondary, #94a3b8);
  flex-shrink: 0;
  transition: color var(--fxm-duration-fast, 150ms) ease;
}

/* Value (numeric display) */
.fxm-metric-value {
  font-weight: var(--fxm-font-weight-bold, 700);
  font-size: var(--fxm-font-size-sm, 12px);
  font-variant-numeric: tabular-nums;
  min-width: 2.2em;
  text-align: right;
  color: var(--fxm-text-primary, #f1f5f9);

  /* Smooth value color transition */
  transition: color var(--fxm-duration-normal, 250ms) ease;
}

/* Unit suffix (%, W, MB, etc.) */
.fxm-metric-unit {
  font-weight: var(--fxm-font-weight-normal, 400);
  font-size: var(--fxm-font-size-xs, 10px);
  color: var(--fxm-text-muted, #64748b);
  flex-shrink: 0;
  min-width: 1em;
}

/* Status indicator dot (small circle before value) */
.fxm-metric-indicator {
  width: var(--fxm-topmenu-indicator, 6px);
  height: var(--fxm-topmenu-indicator, 6px);
  border-radius: 50%;
  flex-shrink: 0;
  transition:
    background-color var(--fxm-duration-instant, 50ms) ease,
    box-shadow var(--fxm-duration-normal, 250ms) ease;
}

/* ==========================================================================
   4. Status Color Classes (状态颜色编码)
   Thresholds: Low < 60%, Medium 60-80%, High > 80%
   Special: PRED uses risk levels (Low/Med/High/Crit)
   ========================================================================== */

.fxm-status-low {
  color: var(--fxm-success, #22c55e) !important;
}

.fxm-status-low .fxm-metric-indicator {
  background-color: var(--fxm-success, #22c55e);
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
}

.fxm-status-medium {
  color: var(--fxm-warning, #eab308) !important;
}

.fxm-status-medium .fxm-metric-indicator {
  background-color: var(--fxm-warning, #eab308);
  box-shadow: 0 0 6px rgba(234, 179, 8, 0.4);
}

.fxm-status-high {
  color: var(--fxm-danger, #ef4444) !important;
}

.fxm-status-high .fxm-metric-indicator {
  background-color: var(--fxm-danger, #ef4444);
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.4);
  animation: fxm-tmb-pulse 1.5s ease-in-out infinite;
}

/* No-data placeholder */
.fxm-status-none {
  color: var(--fxm-text-disabled, #475569) !important;
}

.fxm-status-none .fxm-metric-indicator {
  background-color: var(--fxm-text-muted, #64748b);
}

/* Per-metric accent colors for label/icon tinting */
.fxm-metric-pred { --card-accent: var(--fxm-metric-pred-color, var(--fxm-accent-blue, #00d4ff)); }
.fxm-metric-cpu  { --card-accent: var(--fxm-metric-cpu-color, var(--fxm-accent-purple, #a855f7)); }
.fxm-metric-ram  { --card-accent: var(--fxm-metric-ram-color, var(--fxm-accent-cyan, #06b6d4)); }
.fxm-metric-gpu  { --card-accent: var(--fxm-metric-gpu-color, var(--fxm-success, #22c55e)); }
.fxm-metric-vram { --card-accent: var(--fxm-metric-vram-color, var(--fxm-accent-pink, #ec4899)); }
.fxm-metric-rsv  { --card-accent: var(--fxm-metric-rsv-color, var(--fxm-warning, #eab308)); }
.fxm-metric-pwr  { --card-accent: var(--fxm-metric-pwr-color, var(--fxm-danger, #ef4444)); }

.fxm-metric-card .fxm-metric-label {
  color: var(--card-accent, var(--fxm-text-secondary, #94a3b8));
}

/* ==========================================================================
   5. Tooltip Popup (悬停详情弹出层)
   ========================================================================== */

.fxm-tooltip {
  position: absolute;
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%) scaleY(0.9);
  transform-origin: top center;

  min-width: 220px;
  max-width: 280px;
  padding: var(--fxm-space-3, 12px);
  z-index: var(--fxm-z-tooltip-sparkline, 1100);

  /* Glass panel styling */
  background: var(--fxm-glass-bg, rgba(17, 24, 39, 0.95));
  backdrop-filter: var(--fxm-glass-blur-heavy, blur(30px) saturate(180%));
  -webkit-backdrop-filter: var(--fxm-glass-blur-heavy, blur(30px) saturate(180%));
  border: 1px solid var(--fxm-border-subtle, rgba(255, 255, 255, 0.10));
  border-radius: var(--fxm-radius-tooltip, 8px);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.45),
    0 0 0 1px rgba(255, 255, 255, 0.04),
    var(--fxm-glow-primary, 0 0 20px rgba(0, 212, 255, 0.08));

  pointer-events: auto;
  opacity: 0;
  visibility: hidden;

  transition:
    opacity var(--fxm-duration-normal, 250ms) var(--fxm-ease-out, cubic-bezier(0, 0, 0.2, 1)),
    transform var(--fxm-duration-normal, 250ms) var(--fxm-ease-out-back, cubic-bezier(0.16, 1, 0.3, 1)),
    visibility 0s linear var(--fxm-duration-normal, 250ms);
}

/* Tooltip visible state */
.fxm-tooltip.fxm-tooltip-visible {
  opacity: 1;
  visibility: visible;
  transform: translateX(-50%) scaleY(1);

  transition:
    opacity var(--fxm-duration-normal, 250ms) var(--fxm-ease-out, cubic-bezier(0, 0, 0.2, 1)),
    transform var(--fxm-duration-normal, 250ms) var(--fxm-ease-out-back, cubic-bezier(0.16, 1, 0.3, 1)),
    visibility 0s linear 0s;
}

/* Tooltip arrow (CSS triangle) */
.fxm-tooltip::before {
  content: '';
  position: absolute;
  top: -5px;
  left: 50%;
  transform: translateX(-50%) rotate(45deg);
  width: 10px;
  height: 10px;
  background: var(--fxm-glass-bg, rgba(17, 24, 39, 0.95));
  border-left: 1px solid var(--fxm-border-subtle, rgba(255, 255, 255, 0.10));
  border-top: 1px solid var(--fxm-border-subtle, rgba(255, 255, 255, 0.10));
}

/* Tooltip header (title + badge) */
.fxm-tooltip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--fxm-space-2, 8px);
  padding-bottom: var(--fxm-space-2, 8px);
  border-bottom: 1px solid var(--fxm-border-default, rgba(255, 255, 255, 0.06));
}

.fxm-tooltip-title {
  font-weight: var(--fxm-font-weight-semibold, 600);
  font-size: var(--fxm-font-size-sm, 12px);
  color: var(--fxm-text-primary, #f1f5f9);
  letter-spacing: var(--fxm-letter-spacing-label, 1px);
  text-transform: uppercase;
}

/* Risk level badge */
.fxm-tooltip-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: var(--fxm-radius-full, 9999px);
  font-size: 9px;
  font-weight: var(--fxm-font-weight-semibold, 600);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.fxm-badge-low    { background: rgba(34, 197, 94, 0.15); color: var(--fxm-success, #22c55e); }
.fxm-badge-medium { background: rgba(234, 179, 8, 0.15);  color: var(--fxm-warning, #eab308); }
.fxm-badge-high   { background: rgba(239, 68, 68, 0.15);  color: var(--fxm-danger, #ef4444); }
.fxm-badge-crit   { background: rgba(239, 68, 68, 0.25);  color: #ff6b6b; }

/* Tooltip current value (large display) */
.fxm-tooltip-value {
  font-size: var(--fxm-font-size-xl, 20px);
  font-weight: var(--fxm-font-weight-bold, 700);
  font-variant-numeric: tabular-nums;
  color: var(--fxm-text-primary, #f1f5f9);
  margin-bottom: var(--fxm-space-2, 8px);
  line-height: 1.2;
}

/* Tooltip sparkline canvas container */
.fxm-tooltip-chart-wrap {
  position: relative;
  width: 100%;
  height: 70px;
  margin-bottom: var(--fxm-space-2, 8px);
  border-radius: var(--fxm-radius-sm, 4px);
  overflow: hidden;
  background: rgba(0, 0, 0, 0.2);
}

.fxm-tooltip-chart {
  display: block;
  width: 100%;
  height: 100%;
}

/* Tooltip statistics row */
.fxm-tooltip-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--fxm-space-2, 8px);
  padding-top: var(--fxm-space-2, 8px);
  border-top: 1px solid var(--fxm-border-default, rgba(255, 255, 255, 0.06));
  margin-bottom: var(--fxm-space-2, 8px);
}

.fxm-tooltip-stat {
  text-align: center;
}

.fxm-tooltip-stat-label {
  display: block;
  font-size: 9px;
  color: var(--fxm-text-muted, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}

.fxm-tooltip-stat-value {
  font-size: var(--fxm-font-size-sm, 12px);
  font-weight: var(--fxm-font-weight-semibold, 600);
  font-variant-numeric: tabular-nums;
  color: var(--fxm-text-secondary, #94a3b8);
}

/* Tooltip footer (source info) */
.fxm-tooltip-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: var(--fxm-space-1, 4px);
  border-top: 1px solid var(--fxm-border-default, rgba(255, 255, 255, 0.06));
  font-size: 9px;
  color: var(--fxm-text-muted, #64748b);
}

/* ==========================================================================
   6. Responsive Breakpoints (响应式断点)
   ========================================================================== */

@media (max-width: 1200px) {
  .fxm-metric-card[data-metric="rsv"],
  .fxm-metric-card[data-metric="pwr"] {
    display: none !important;
  }
}

@media (max-width: 900px) {
  .fxm-topmenubar {
    right: 120px;
    gap: 2px;
    padding: 2px 6px;
  }

  .fxm-metric-card {
    padding: 2px 6px;
  }

  .fxm-metric-label {
    display: none;
  }
}

@media (max-width: 600px) {
  .fxm-topmenubar {
    right: 8px;
    top: 4px;
  }

  .fxm-metric-unit {
    display: none;
  }
}

/* ==========================================================================
   7. Keyframe Animations (关键帧动画)
   ========================================================================== */

@keyframes fxm-tmb-slideInRight {
  from {
    opacity: 0;
    transform: translateX(30px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes fxm-tmb-fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes fxm-tmb-pulse {
  0%, 100% {
    box-shadow: 0 0 6px rgba(239, 68, 68, 0.4);
  }
  50% {
    box-shadow: 0 0 12px rgba(239, 68, 68, 0.65), 0 0 20px rgba(239, 68, 68, 0.25);
  }
}

/* ==========================================================================
   8. Accessibility (无障碍)
   ========================================================================== */

@media (prefers-reduced-motion: reduce) {
  .fxm-topmenubar {
    animation: none;
    opacity: 1;
  }

  .fxm-metric-card,
  .fxm-tooltip,
  .fxm-metric-value,
  .fxm-metric-icon,
  .fxm-metric-indicator {
    transition: none !important;
  }

  .fxm-status-high .fxm-metric-indicator {
    animation: none;
  }

  .fxm-tooltip {
    transition: opacity 0s linear, visibility 0s linear !important;
    transform: translateX(-50%) scaleY(1) !important;
  }

  .fxm-tooltip.fxm-tooltip-visible {
    transform: translateX(-50%) scaleY(1) !important;
  }
}
`;

// =============================================================================
// MetricCard Class (单个指标胶囊卡片)
// =============================================================================

/**
 * 单个指标卡片（胶囊样式）。
 *
 * 每个 MetricCard 负责渲染一个监控指标的当前值，包括：
 * - 图标 + 标签 + 数值 + 单位的 DOM 结构
 * - 数值更新（带平滑过渡动画）
 * - 状态颜色切换（基于阈值：低/中/高负载）
 * - 悬停 Tooltip 显示（含趋势图和统计信息）
 *
 * 生命周期由父级 TopMenuBar 管理（创建 -> updateValue -> destroy）。
 *
 * @class MetricCard
 * @example
 * const card = new MetricCard({
 *   id: 'cpu',
 *   label: 'CPU',
 *   icon: '\uD83D\uDDFB',
 *   colorVar: '--fxm-metric-cpu-color',
 *   dataPath: 'cpu_metrics.cpu_utilization',
 *   unit: '%',
 *   thresholds: { low: 60, medium: 80 }
 * });
 * card.render();
 * card.updateValue(45.2);
 */
class MetricCard {
  // ---------------------------------------------------------------------------
  // Constructor
  // ---------------------------------------------------------------------------

  /**
   * 创建 MetricCard 实例。
   *
   * @param {Object} options - 配置选项。
   * @param {string} options.id - 唯一标识符 ('pred' | 'cpu' | 'ram' | 'gpu' | 'vram' | 'rsv' | 'pwr')。
   * @param {string} options.label - 显示标签 ('PRED' | 'CPU' | 'RAM' | ...)。
   * @param {string} [options.icon=''] - Unicode 图标或 SVG 字符串。
   * @param {string} options.colorVar - CSS 变量名 ('--fxm-metric-pred-color')。
   * @param {string} options.dataPath - 数据路径 ('prediction.success_rate')。
   * @param {string} [options.unit='%'] - 单位后缀 ('%', '\u00B0C', 'W', 'MB')。
   * @param {Function} [options.formatter] - 自定义数值格式化函数。
   * @param {boolean} [options.visible=true] - 是否默认可见。
   * @param {Object} [options.thresholds={ low: 60, medium: 80 }] - 颜色阈值配置。
   */
  constructor(options = {}) {
    /**
     * 唯一标识符。
     * @type {string}
     */
    this.id = options.id || '';

    /**
     * 显示标签（大写缩写）。
     * @type {string}
     */
    this.label = options.label || '';

    /**
     * Unicode 图标字符。
     * @type {string}
     */
    this.icon = options.icon || '';

    /**
     * CSS 自定义属性变量名，用于获取指标专属颜色。
     * @type {string}
     */
    this.colorVar = options.colorVar || '--fxm-accent-blue';

    /**
     * 数据对象中的点分访问路径。
     * 例：'cpu_metrics.cpu_utilization'
     * @type {string}
     */
    this.dataPath = options.dataPath || '';

    /**
     * 单位后缀。
     * @type {string}
     */
    this.unit = options.unit || '%';

    /**
     * 自定义数值格式化函数。默认使用 _defaultFormatter。
     * @type {Function}
     */
    this.formatter = options.formatter || this._defaultFormatter.bind(this);

    /**
     * 是否默认可见（可通过 data 驱动动态切换）。
     * @type {boolean}
     */
    this.visible = options.visible !== false;

    /**
     * 颜色编码阈值。
     * - low: < thresholds.low (绿色/正常)
     * - medium: >= low && < medium (黄色/中等)
     * - high: >= medium (红色/警告)
     * @type {{ low: number, medium: number }}
     */
    this.thresholds = options.thresholds || { low: 60, medium: 80 };

    // -------------------------------------------------------------------------
    // DOM References (render() 后赋值)
    // -------------------------------------------------------------------------

    /** @type {HTMLElement|null} 卡片根元素 */
    this._element = null;

    /** @type {HTMLElement|null} 数值显示元素 */
    this._valueEl = null;

    /** @type {HTMLElement|null} 标签显示元素 */
    this._labelEl = null;

    /** @type {HTMLElement|null} 图标显示元素 */
    this._iconEl = null;

    /** @type {HTMLElement|null} 单位显示元素 */
    this._unitEl = null;

    /** @type {HTMLElement|null} 状态指示灯元素 */
    this._indicatorEl = null;

    /** @type {HTMLElement|null} Tooltip 元素 */
    this._tooltip = null;

    // -------------------------------------------------------------------------
    // Internal State
    // -------------------------------------------------------------------------

    /** @type {*} 当前显示的原始值 */
    this._currentValue = null;

    /** @type {string} 当前状态类名 ('low' | 'medium' | 'high' | 'none') */
    this._currentStatus = 'none';

    /** @type {number|null} Tooltip 延迟显示定时器 ID */
    this._tooltipTimer = null;

    /** @type {boolean} Tooltip 当前是否处于可见状态 */
    this._tooltipVisible = false;

    /** @type {Function|null} Bound event handlers (for cleanup) */
    this._boundMouseEnter = null;
    this._boundMouseLeave = null;
    this._boundClick = null;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * 创建并返回卡片的 DOM 结构。
   * 内部构建完整的 HTML 片段并缓存各子元素的引用。
   *
   * @returns {HTMLElement} 卡片根元素 (<div class="fxm-metric-card">)。
   */
  render() {
    if (this._element) {
      console.warn(`[MetricCard] render() called twice for "${this.id}", returning existing element`);
      return this._element;
    }

    // Build DOM structure
    this._element = document.createElement('div');
    this._element.className = `fxm-metric-card fxm-metric-${this.id}`;
    this._element.setAttribute('data-metric', this.id);
    this._element.setAttribute('role', 'button');
    this._element.setAttribute('tabindex', '0');
    this._element.setAttribute('aria-label', `${this.label} metric: loading`);

    // Indicator dot
    this._indicatorEl = document.createElement('span');
    this._indicatorEl.className = 'fxm-metric-indicator';
    this._indicatorEl.setAttribute('aria-hidden', 'true');

    // Icon
    this._iconEl = document.createElement('span');
    this._iconEl.className = 'fxm-metric-icon';
    this._iconEl.textContent = this.icon;
    this._iconEl.setAttribute('aria-hidden', 'true');

    // Label
    this._labelEl = document.createElement('span');
    this._labelEl.className = 'fxm-metric-label';
    this._labelEl.textContent = this.label;

    // Value
    this._valueEl = document.createElement('span');
    this._valueEl.className = 'fxm-metric-value';
    this._valueEl.textContent = '--';

    // Unit
    this._unitEl = document.createElement('span');
    this._unitEl.className = 'fxm-metric-unit';
    this._unitEl.textContent = this.unit;

    // Assemble children: indicator | icon | label | value | unit
    this._element.appendChild(this._indicatorEl);
    this._element.appendChild(this._iconEl);
    this._element.appendChild(this._labelEl);
    this._element.appendChild(this._valueEl);
    this._element.appendChild(this._unitEl);

    // Set initial status class
    this._applyStatusClass('none');

    // Bind interaction events (stored for cleanup)
    this._bindEvents();

    return this._element;
  }

  /**
   * 更新数值显示。
   * 支持平滑过渡动画（CSS transition 控制 opacity/color 变化）。
   * 当值未变化时跳过 DOM 写入以优化性能。
   *
   * @param {*} value - 新数值（通常为 number，也支持 string 或 null）。
   * @param {boolean} [animate=true] - 是否启用过渡动画。
   */
  updateValue(value, animate = true) {
    if (!this._valueEl) return;

    // Skip update if value hasn't changed (performance optimization)
    if (value === this._currentValue && value !== null && value !== undefined) {
      return;
    }

    this._currentValue = value;

    // Format and set text content
    const formatted = this.formatter(value);
    this._valueEl.textContent = formatted;

    // Update accessibility label
    if (this._element) {
      this._element.setAttribute(
        'aria-label',
        `${this.label}: ${formatted}${this.unit}`
      );
    }
  }

  /**
   * 根据数值更新状态颜色类。
   * 使用阈值系统判断负载等级：
   * - value < low    => 'low'    (绿色/正常)
   * - value >= medium=> 'high'   (红色/警告)
   * - 其他           => 'medium' (黄色/中等)
   * - null/undefined => 'none'   (灰色/无数据)
   *
   * @param {*} value - 用于判断状态的数值。
   */
  updateStatus(value) {
    if (!this._element) return;

    const status = this._determineStatus(value);

    // Skip if status unchanged (avoid unnecessary DOM writes)
    if (status === this._currentStatus) return;

    this._currentStatus = status;
    this._applyStatusClass(status);
  }

  /**
   * 显示 Tooltip 详情弹出层。
   * 由 TopMenuBar 在 mouseenter 延迟后调用。
   *
   * @param {Object} tooltipData - Tooltip 内容数据。
   * @param {Array} tooltipData.history - 历史数据点数组 [{value, timestamp}, ...]。
   * @param {Object} tooltipData.stats - 统计信息 {current, min, max, avg, count}。
   * @param {string} [tooltipData.dataSource='N/A'] - 数据源标识。
   */
  showTooltip(tooltipData) {
    if (!this._element || this._tooltipVisible) return;

    // Create tooltip element if not exists
    if (!this._tooltip) {
      this._tooltip = this._buildTooltipDOM();
    }

    // Populate dynamic content
    this._populateTooltipContent(tooltipData);

    // Show with CSS transition
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        // Double rAF ensures browser has painted the initial hidden state
        if (this._tooltip) {
          this._tooltip.classList.add('fxm-tooltip-visible');
          this._tooltipVisible = true;
        }
      });
    });
  }

  /**
   * 隐藏 Tooltip 弹出层。
   * 带 CSS 过渡动画延迟移除 DOM 类。
   */
  hideTooltip() {
    if (!this._tooltip || !this._tooltipVisible) return;

    this._tooltip.classList.remove('fxm-tooltip-visible');
    this._tooltipVisible = false;

    // Remove from DOM after transition completes (allow reuse)
    const tooltip = this._tooltip;
    setTimeout(() => {
      if (tooltip && !this._tooltipVisible && tooltip.parentNode) {
        tooltip.remove();
        this._tooltip = null;
      }
    }, 300);
  }

  /**
   * 销毁卡片实例。
   * 清理所有事件监听器、定时器引用和 DOM 元素。
   * 必须在组件卸载时调用以防止内存泄漏。
   */
  destroy() {
    // Clear tooltip timer
    this._clearTooltipTimer();

    // Hide and remove tooltip
    if (this._tooltip) {
      this._tooltip.remove();
      this._tooltip = null;
    }

    // Unbind events
    this._unbindEvents();

    // Remove DOM element
    if (this._element && this._element.parentNode) {
      this._element.parentNode.removeChild(this._element);
    }

    // Clear references
    this._element = null;
    this._valueEl = null;
    this._labelEl = null;
    this._iconEl = null;
    this._unitEl = null;
    this._indicatorEl = null;
    this._currentValue = null;
  }

  // ---------------------------------------------------------------------------
  // Getters
  // ---------------------------------------------------------------------------

  /**
   * 卡片根 DOM 元素。
   * @type {HTMLElement|null}
   */
  get element() {
    return this._element;
  }

  /**
   * 当前显示值。
   * @type {*}
   */
  get currentValue() {
    return this._currentValue;
  }

  /**
   * Tooltip 是否可见。
   * @type {boolean}
   */
  get isTooltipVisible() {
    return this._tooltipVisible;
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Event Binding
  // ---------------------------------------------------------------------------

  /**
   * 绑定用户交互事件（mouseenter/mouseleave/click）。
   * 所有 handler 都绑定到实例方法以确保 cleanup 时能正确移除。
   * @private
   */
  _bindEvents() {
    if (!this._element) return;

    this._boundMouseEnter = this._handleMouseEnter.bind(this);
    this._boundMouseLeave = this._handleMouseLeave.bind(this);
    this._boundClick = this._handleClick.bind(this);

    this._element.addEventListener('mouseenter', this._boundMouseEnter);
    this._element.addEventListener('mouseleave', this._boundMouseLeave);
    this._element.addEventListener('click', this._boundClick);
    this._element.addEventListener('keydown', this._handleKeyDown.bind(this));
  }

  /**
   * 解绑所有用户交互事件。
   * 与 _bindEvents() 对称调用，防止内存泄漏。
   * @private
   */
  _unbindEvents() {
    if (!this._element) return;

    if (this._boundMouseEnter) {
      this._element.removeEventListener('mouseenter', this._boundMouseEnter);
      this._boundMouseEnter = null;
    }
    if (this._boundMouseLeave) {
      this._element.removeEventListener('mouseleave', this._boundMouseLeave);
      this._boundMouseLeave = null;
    }
    if (this._boundClick) {
      this._element.removeEventListener('click', this._boundClick);
      this._boundClick = null;
    }
  }

  /**
   * 处理鼠标进入事件。
   * 启动 500ms 延迟计时器后通知父级显示 Tooltip。
   * @param {MouseEvent} e - 鼠标事件对象。
   * @private
   */
  _handleMouseEnter(e) {
    this._clearTooltipTimer();

    // Dispatch custom event to parent TopMenuBar
    // Parent will call showTooltip() after delay
    this._dispatchMetricEvent('metric:mouseenter', {
      metricId: this.id,
      card: this,
      originalEvent: e
    });
  }

  /**
   * 处理鼠标离开事件。
   * 立即取消待执行的 Tooltip 显示并隐藏已打开的 Tooltip。
   * @param {MouseEvent} e - 鼠标事件对象。
   * @private
   */
  _handleMouseLeave(e) {
    this._clearTooltipTimer();
    this.hideTooltip();

    this._dispatchMetricEvent('metric:mouseleave', {
      metricId: this.id,
      card: this,
      originalEvent: e
    });
  }

  /**
   * 处理点击事件。
   * 触发 metric:click 事件供父级 TopMenuBar 处理（如展开 HoverPanel）。
   * @param {MouseEvent} e - 点击事件对象。
   * @private
   */
  _handleClick(e) {
    this._dispatchMetricEvent('metric:click', {
      metricId: this.id,
      card: this,
      value: this._currentValue,
      originalEvent: e
    });
  }

  /**
   * 处理键盘事件（Enter/Space 触发点击）。
   * @param {KeyboardEvent} e - 键盘事件对象。
   * @private
   */
  _handleKeyDown(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      this._handleClick(e);
    }
  }

  /**
   * 向父级元素派发自定义事件。
   * 使用冒泡机制让 TopMenuBar 可以统一监听所有子卡片的事件。
   *
   * @param {string} eventName - 事件名称。
   * @param {Object} detail - 事件详情数据。
   * @private
   */
  _dispatchMetricEvent(eventName, detail) {
    if (!this._element) return;
    const event = new CustomEvent(eventName, {
      bubbles: true,
      detail: detail
    });
    this._element.dispatchEvent(event);
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Tooltip Construction
  // ---------------------------------------------------------------------------

  /**
   * 构建 Tooltip DOM 结构（静态骨架）。
   * 返回的元素不包含动态内容，由 _populateTooltipContent() 填充。
   *
   * @returns {HTMLElement} Tooltip 根元素。
   * @private
   */
  _buildTooltipDOM() {
    const tooltip = document.createElement('div');
    tooltip.className = 'fxm-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.setAttribute('aria-live', 'polite');

    tooltip.innerHTML = `
      <div class="fxm-tooltip-header">
        <span class="fxm-tooltip-title">${this._escapeHtml(this.label)}</span>
        <span class="fxm-tooltip-badge"></span>
      </div>
      <div class="fxm-tooltip-value"></div>
      <div class="fxm-tooltip-chart-wrap">
        <canvas class="fxm-tooltip-chart" width="220" height="70"></canvas>
      </div>
      <div class="fxm-tooltip-stats">
        <div class="fxm-tooltip-stat">
          <span class="fxm-tooltip-stat-label">Min</span>
          <span class="fxm-tooltip-stat-value" data-stat="min">--</span>
        </div>
        <div class="fxm-tooltip-stat">
          <span class="fxm-tooltip-stat-label">Max</span>
          <span class="fxm-tooltip-stat-value" data-stat="max">--</span>
        </div>
        <div class="fxm-tooltip-stat">
          <span class="fxm-tooltip-stat-label">Avg</span>
          <span class="fxm-tooltip-stat-value" data-stat="avg">--</span>
        </div>
      </div>
      <div class="fxm-tooltip-footer">
        <span class="fxm-tooltip-source">Source: --</span>
        <span class="fxm-tooltip-time">--</span>
      </div>
    `;

    // Append to card element (positioned relative to card)
    this._element.appendChild(tooltip);

    return tooltip;
  }

  /**
   * 用实际数据填充 Tooltip 动态内容。
   * 包括：当前值、风险等级 Badge、统计信息、Sparkline 趋势图。
   *
   * @param {Object} data - Tooltip 数据对象。
   * @param {Array} data.history - 历史数据点。
   * @param {Object} data.stats - 统计信息。
   * @param {string} [data.dataSource] - 数据源标识。
   * @private
   */
  _populateTooltipContent(data) {
    if (!this._tooltip) return;

    const history = data.history || [];
    const stats = data.stats || {};
    const dataSource = data.dataSource || 'N/A';

    // Update title badge with risk level
    const badge = this._tooltip.querySelector('.fxm-tooltip-badge');
    if (badge) {
      const riskLevel = this._getRiskLevel(stats.current);
      const riskLabel = this._getRiskLabel(riskLevel);
      badge.className = `fxm-tooltip-badge fxm-badge-${riskLevel}`;
      badge.textContent = riskLabel;
    }

    // Update current value
    const valueEl = this._tooltip.querySelector('.fxm-tooltip-value');
    if (valueEl) {
      valueEl.textContent = `${this.formatter(stats.current)}${this.unit}`;
      // Apply status color to the large value
      valueEl.style.color = this._getStatusColor(stats.current);
    }

    // Update statistics
    const statEls = this._tooltip.querySelectorAll('[data-stat]');
    statEls.forEach((el) => {
      const key = el.getAttribute('data-stat');
      if (stats[key] !== undefined && stats[key] !== null) {
        el.textContent = typeof stats[key] === 'number'
          ? stats[key].toFixed(1)
          : stats[key];
      } else {
        el.textContent = '--';
      }
    });

    // Update source info
    const sourceEl = this._tooltip.querySelector('.fxm-tooltip-source');
    if (sourceEl) {
      sourceEl.textContent = `Source: ${dataSource}`;
    }

    // Update timestamp
    const timeEl = this._tooltip.querySelector('.fxm-tooltip-time');
    if (timeEl) {
      timeEl.textContent = `Updated: ${new Date().toLocaleTimeString()}`;
    }

    // Draw sparkline chart
    const canvas = this._tooltip.querySelector('.fxm-tooltip-chart');
    if (canvas && history.length > 1) {
      const values = history.map(h => h.value).filter(v => v != null);
      if (values.length > 1) {
        this._drawSparkline(canvas, values);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Sparkline Drawing
  // ---------------------------------------------------------------------------

  /**
   * 在 Canvas 上绘制迷你趋势折线图（Sparkline）。
   * 使用 Canvas 2D API 绘制折线 + 渐变填充区域。
   *
   * @param {HTMLCanvasElement} canvas - 目标 Canvas 元素。
   * @param {Array<number>} values - 数值序列（至少 2 个点）。
   * @private
   */
  _drawSparkline(canvas, values) {
    if (!canvas || values.length < 2) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Handle HiDPI displays
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.width;
    const height = rect.height || canvas.height;

    // Set actual canvas size (for sharpness on retina)
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.scale(dpr, dpr);

    // Clear canvas
    ctx.clearRect(0, 0, width, height);

    // Calculate data range
    const validValues = values.filter(v => typeof v === 'number' && !isNaN(v));
    if (validValues.length < 2) return;

    const minVal = Math.min(...validValues);
    const maxVal = Math.max(...validValues);
    const range = maxVal - minVal || 1;

    // Padding for visual breathing room
    const padTop = height * 0.1;
    const padBottom = height * 0.1;
    const drawHeight = height - padTop - padBottom;

    // Resolve the metric's accent color from CSS variable
    let strokeColor = '#00d4ff'; // fallback
    try {
      const computedColor = getComputedStyle(document.documentElement)
        .getPropertyValue(this.colorVar).trim();
      if (computedColor) {
        strokeColor = computedColor;
      }
    } catch (_) {
      // Use fallback color
    }

    // ---- Draw filled area gradient ----
    ctx.beginPath();
    validValues.forEach((val, i) => {
      const x = (i / (validValues.length - 1)) * width;
      const y = padTop + drawHeight - ((val - minVal) / range) * drawHeight;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    // Close path along bottom edge for fill
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();

    // Gradient fill (transparent at bottom)
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    try {
      const colorRgba = this._hexToRgba(strokeColor, 0.2);
      gradient.addColorStop(0, colorRgba);
      gradient.addColorStop(1, this._hexToRgba(strokeColor, 0));
    } catch (_) {
      gradient.addColorStop(0, 'rgba(0, 212, 255, 0.2)');
      gradient.addColorStop(1, 'rgba(0, 212, 255, 0)');
    }
    ctx.fillStyle = gradient;
    ctx.fill();

    // ---- Draw line stroke ----
    ctx.beginPath();
    validValues.forEach((val, i) => {
      const x = (i / (validValues.length - 1)) * width;
      const y = padTop + drawHeight - ((val - minVal) / range) * drawHeight;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();

    // ---- Draw end point dot ----
    const lastVal = validValues[validValues.length - 1];
    const lastX = width;
    const lastY = padTop + drawHeight - ((lastVal - minVal) / range) * drawHeight;

    ctx.beginPath();
    ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
    ctx.fillStyle = strokeColor;
    ctx.fill();

    // Glow effect on last point
    ctx.beginPath();
    ctx.arc(lastX, lastY, 5, 0, Math.PI * 2);
    ctx.fillStyle = this._hexToRgba(strokeColor, 0.25);
    ctx.fill();
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Status & Formatting
  // ---------------------------------------------------------------------------

  /**
   * 判断给定值的负载等级。
   *
   * @param {*} value - 待判断的数值。
   * @returns {'none'|'low'|'medium'|'high'} 负载等级标识。
   * @private
   */
  _determineStatus(value) {
    if (value === null || value === undefined || value === '--') {
      return 'none';
    }
    if (typeof value !== 'number' || isNaN(value)) {
      return 'none';
    }
    if (value >= this.thresholds.medium) {
      return 'high';
    }
    if (value >= this.thresholds.low) {
      return 'medium';
    }
    return 'low';
  }

  /**
   * 应用状态 CSS 类到卡片元素。
   * 移除旧的状态类并添加新的状态类。
   *
   * @param {string} status - 新状态 ('none' | 'low' | 'medium' | 'high')。
   * @private
   */
  _applyStatusClass(status) {
    if (!this._element) return;

    // Remove all status classes
    this._element.classList.remove(
      'fxm-status-low',
      'fxm-status-medium',
      'fxm-status-high',
      'fxm-status-none'
    );

    // Apply new status class
    this._element.classList.add(`fxm-status-${status}`);
  }

  /**
   * 获取状态对应的 CSS 颜色值（用于 Tooltip 大号数字着色）。
   *
   * @param {*} value - 数值。
   * @returns {string} CSS 颜色字符串。
   * @private
   */
  _getStatusColor(value) {
    const status = this._determineStatus(value);
    const colorMap = {
      low: 'var(--fxm-success, #22c55e)',
      medium: 'var(--fxm-warning, #eab308)',
      high: 'var(--fxm-danger, #ef4444)',
      none: 'var(--fxm-text-disabled, #475569)'
    };
    return colorMap[status] || colorMap.none;
  }

  /**
   * 获取风险等级标识（用于 PRED 特殊处理）。
   * PRED 指标使用成功率反向映射：
   * - 高成功率 (>90%) => Low risk
   * - 中等成功率 (70-90%) => Medium risk
   * - 低成功率 (50-70%) => High risk
   * - 极低 (<50%) => Critical risk
   *
   * 对于非 PRED 指标，直接复用 _determineStatus() 结果。
   *
   * @param {*} value - 数值。
   * @returns {'low'|'medium'|'high'|'crit'} 风险等级。
   * @private
   */
  _getRiskLevel(value) {
    // Special handling for PRED (success rate based)
    if (this.id === 'pred' && typeof value === 'number') {
      if (value >= 90) return 'low';
      if (value >= 70) return 'medium';
      if (value >= 50) return 'high';
      return 'crit';
    }

    // For other metrics, map status to risk level
    const status = this._determineStatus(value);
    const mapping = { low: 'low', medium: 'medium', high: 'high', none: 'low' };
    return mapping[status] || 'low';
  }

  /**
   * 获取风险等级的可读标签文本。
   *
   * @param {string} level - 风险等级标识。
   * @returns {string} 可读标签。
   * @private
   */
  _getRiskLabel(level) {
    const labels = {
      low: 'Normal',
      medium: 'Medium',
      high: 'High',
      crit: 'Critical'
    };
    return labels[level] || 'Unknown';
  }

  /**
   * 默认数值格式化器。
   * 数字保留 1 位小数，非数字值原样返回或显示 '--'。
   *
   * @param {*} value - 待格式化的值。
   * @returns {string} 格式化后的字符串。
   * @private
   */
  _defaultFormatter(value) {
    if (value === null || value === undefined) {
      return '--';
    }
    if (typeof value === 'number') {
      return value.toFixed(1);
    }
    return String(value);
  }

  // ---------------------------------------------------------------------------
  // Private Utilities
  // ---------------------------------------------------------------------------

  /**
   * 清除 Tooltip 延迟显示定时器。
   * @private
   */
  _clearTooltipTimer() {
    if (this._tooltipTimer !== null) {
      clearTimeout(this._tooltipTimer);
      this._tooltipTimer = null;
    }
  }

  /**
   * HTML 实体转义（防 XSS）。
   *
   * @param {string} str - 待转义字符串。
   * @returns {string} 安全字符串。
   * @private
   */
  _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * 将十六进制颜色转换为 RGBA 字符串。
   *
   * @param {string} hex - 十六进制颜色（#RRGGBB 或 #RGB）。
   * @param {number} alpha - 透明度 (0-1)。
   * @returns {string} RGBA 颜色字符串。
   * @private
   */
  _hexToRgba(hex, alpha) {
    // Handle CSS variable references or named colors
    if (!hex || hex.startsWith('var(') || hex.startsWith('rgb')) {
      return `rgba(0, 212, 255, ${alpha})`;
    }

    let cleanHex = hex.replace('#', '');
    if (cleanHex.length === 3) {
      cleanHex = cleanHex.split('').map(c => c + c).join('');
    }
    if (cleanHex.length !== 6) {
      return `rgba(0, 212, 255, ${alpha})`;
    }

    const r = parseInt(cleanHex.substring(0, 2), 16);
    const g = parseInt(cleanHex.substring(2, 4), 16);
    const b = parseInt(cleanHex.substring(4, 6), 16);

    if (isNaN(r) || isNaN(g) || isNaN(b)) {
      return `rgba(0, 212, 255, ${alpha})`;
    }

    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
}


// =============================================================================
// TopMenuBar Class (顶部菜单栏主容器)
// =============================================================================

/**
 * 顶部菜单栏监控胶囊组件。
 *
 * 作为 7 个 MetricCard 的容器和管理者，负责：
 * 1. 构建 DOM 结构并注入到 ComfyUI 顶部菜单栏右侧
 * 2. 监听 DataService 的 'data' 事件并分发更新给各 MetricCard
 * 3. 管理每个指标的可见性（GPU 相关指标在无数据时自动隐藏）
 * 4. 维护历史数据缓冲区（用于 Tooltip 趋势图绘制）
 * 5. 协调 Tooltip 的显示/隐藏逻辑（500ms 延迟防误触）
 * 6. 响应窗口尺寸变化调整布局
 *
 * @class TopMenuBar
 * @example
 * import { TopMenuBar } from './components/top-menu-bar.js';
 * import { globalEventBus } from '../core/event-emitter.js';
 * import config from '../core/config-manager.js';
 * import { DataService } from '../services/websocket-service.js';
 *
 * const menuBar = new TopMenuBar({
 *   container: document.body,
 *   eventBus: globalEventBus,
 *   config: config,
 *   dataService: dataService
 * });
 *
 * menuBar.init();
 * // Later: menuBar.destroy();
 */
class TopMenuBar {
  // ---------------------------------------------------------------------------
  // Static Constants
  // ---------------------------------------------------------------------------

  /**
   * 7 个监控指标的元数据定义。
   * 每个条目包含 MetricCard 构造所需的全部参数。
   * 定义顺序决定 DOM 中的排列顺序。
   *
   * @type {ReadonlyArray<Object>}
   * @static
   * @readonly
   */
  static METRIC_DEFINITIONS = Object.freeze([
    {
      id: 'pred',
      label: 'PRED',
      icon: '\u{1F4CA}',           // 📊
      colorVar: '--fxm-metric-pred-color',
      dataPath: 'prediction.success_rate',
      unit: '%',
      thresholds: { low: 90, medium: 70 },  // Inverted for success rate
      formatter: (v) => (v == null ? '--' : Number(v).toFixed(1))
    },
    {
      id: 'cpu',
      label: 'CPU',
      icon: '\uD83D\uDDFB',           // 🔲
      colorVar: '--fxm-metric-cpu-color',
      dataPath: 'cpu_metrics.cpu_utilization',
      unit: '%',
      thresholds: { low: 60, medium: 80 }
    },
    {
      id: 'ram',
      label: 'RAM',
      icon: '\uD83D\uDCBE',           // 💾
      colorVar: '--fxm-metric-ram-color',
      dataPath: 'ram_metrics.ram_percent',
      unit: '%',
      thresholds: { low: 60, medium: 80 }
    },
    {
      id: 'gpu',
      label: 'GPU',
      icon: '\u26A1',                 // ⚡
      colorVar: '--fxm-metric-gpu-color',
      dataPath: 'gpu_metrics.gpu_utilization',
      unit: '%',
      thresholds: { low: 60, medium: 80 }
    },
    {
      id: 'vram',
      label: 'VRAM',
      icon: '\uD83C\uDFAE',           // 🎮
      colorVar: '--fxm-metric-vram-color',
      dataPath: 'gpu_metrics.vram_percent',
      unit: '%',
      thresholds: { low: 60, medium: 80 }
    },
    {
      id: 'rsv',
      label: 'RSV',
      icon: '\uD83D\uDD04',           // 🔄
      colorVar: '--fxm-metric-rsv-color',
      dataPath: 'gpu_reserved',
      unit: 'MB',
      thresholds: { low: 512, medium: 2048 },  // Memory in MB
      formatter: (v) => (v == null ? '--' : Number(v).toFixed(0))
    },
    {
      id: 'pwr',
      label: 'PWR',
      icon: '\uD83D\uDD0B',           // 🔋
      colorVar: '--fxm-metric-pwr-color',
      dataPath: 'gpu_metrics.power_usage',
      unit: 'W',
      thresholds: { low: 150, medium: 250 },  // Power in Watts
      formatter: (v) => (v == null ? '--' : Number(v).toFixed(0))
    }
  ]);

  /**
   * 历史缓冲区最大长度（数据点数）。
   * 60 个点 @ ~1Hz 采样率 = 约 60 秒历史数据。
   * @type {number}
   * @static
   * @readonly
   */
  static MAX_HISTORY_LENGTH = 60;

  /**
   * Tooltip 显示延迟时间（毫秒）。
   * 防止鼠标快速划过时误触发 Tooltip。
   * @type {number}
   * @static
   * @readonly
   */
  static TOOLTIP_DELAY_MS = 500;

  // ---------------------------------------------------------------------------
  // Constructor
  // ---------------------------------------------------------------------------

  /**
   * 创建 TopMenuBar 实例。
   *
   * @param {Object} [options={}] - 配置选项。
   * @param {HTMLElement} [options.container=document.body] - DOM 挂载容器。
   * @param {EventEmitter} [options.eventBus=null] - 全局事件总线（用于监听 data 事件）。
   * @param {ConfigManager} [options.config=null] - 配置管理器（读取 metrics 可见性设置）。
   * @param {DataService} [options.dataService=null] - 数据服务（自动注册 data 监听）。
   * @param {number} [options.rightOffset=200] - 距离视口右边缘的偏移量（像素）。
   */
  constructor(options = {}) {
    /**
     * DOM 挂载容器。
     * @type {HTMLElement}
     */
    this.container = options.container || document.body;

    /**
     * 全局事件总线实例。
     * @type {EventEmitter|null}
     */
    this.eventBus = options.eventBus || null;

    /**
     * 配置管理器实例。
     * @type {ConfigManager|null}
     */
    this.config = options.config || null;

    /**
     * 数据服务实例。
     * @type {DataService|null}
     */
    this.dataService = options.dataService || null;

    /**
     * 距离右边缘偏移量（ComfyUI 菜单栏宽度约 200px）。
     * @type {number}
     */
    this._rightOffset = options.rightOffset || 200;

    // -------------------------------------------------------------------------
    // DOM References
    // -------------------------------------------------------------------------

    /** @type {HTMLElement|null} 根容器元素 (#fxm-topmenubar) */
    this._element = null;

    /** @type {Object<string, MetricCard>} 指标卡片映射表 */
    this._metricCards = {};

    /** @type {HTMLStyleElement|null} 注入的 <style> 元素引用 */
    this._styleEl = null;

    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------

    /** @type {boolean} 组件是否可见 */
    this._visible = true;

    /** @type {Object|null} 最新收到的完整数据快照 */
    this._currentData = null;

    /**
     * 历史数据缓冲区。
     * 结构：{ pred: [{value, timestamp}, ...], cpu: [...], ... }
     * 用于 Tooltip Sparkline 趋势图绘制。
     * @type {Object<string, Array<{value: number, timestamp: number}>>}
     */
    this._historyBuffer = {};

    /**
     * 最大历史数据点数（滑动窗口大小）。
     * @type {number}
     */
    this._maxHistoryLength = TopMenuBar.MAX_HISTORY_LENGTH;

    // -------------------------------------------------------------------------
    // Animation & Performance
    // -------------------------------------------------------------------------

    /** @type {boolean} 是否启用动画效果 */
    this._animationEnabled = true;

    /** @type {number|null} requestAnimationFrame ID (for batch updates) */
    this._updateAnimationId = null;

    /** @type {boolean} 是否有待处理的批量更新 */
    this._pendingUpdate = false;

    /** @type {number|null} 性能计时：上次更新耗时 (ms) */
    this._lastUpdateTime = 0;

    // -------------------------------------------------------------------------
    // Tooltip State
    // -------------------------------------------------------------------------

    /** @type {Object<string, number>} 各卡片 Tooltip 定时器 ID 映射 */
    this._tooltipTimers = {};

    /** @type {string|null} 当前活跃 Tooltip 的 metric ID */
    this._activeTooltipMetric = null;

    // -------------------------------------------------------------------------
    // Event Handler References (for cleanup)
    // -------------------------------------------------------------------------

    this._boundDataHandler = null;
    this._boundMetricMouseEnter = null;
    this._boundMetricMouseLeave = null;
    this._boundOutsideClick = null;
    this._boundResizeHandler = null;
    this._boundConfigChangeHandler = null;

    /** @type {boolean} 是否已完成初始化 */
    this._initialized = false;
  }

  // ---------------------------------------------------------------------------
  // Lifecycle: Initialization
  // ---------------------------------------------------------------------------

  /**
   * 初始化组件并渲染到 DOM。
   *
   * 执行步骤：
   * 1. 注入 CSS 样式（仅首次调用时注入一次）
   * 2. 创建根容器 DOM 元素
   * 3. 根据 METRIC_DEFINITIONS 创建 7 个 MetricCard 子组件
   * 4. 使用 DocumentFragment 批量插入减少回流
   * 5. 注册 DataService 的 data 事件监听
   * 6. 注册全局事件（config change, resize, outside click）
   * 7. 应用初始可见性状态
   *
   * @returns {TopMenuBar} this（支持链式调用）。
   * @throws {Error} 如果 container 不存在或不是有效 HTMLElement。
   */
  init() {
    if (this._initialized) {
      console.warn('[TopMenuBar] init() called multiple times, skipping');
      return this;
    }

    // Validate container
    if (!this.container || !(this.container instanceof HTMLElement)) {
      throw new Error(
        '[TopMenuBar] init(): container must be a valid HTMLElement. ' +
        `Got: ${typeof this.container}`
      );
    }

    // Step 1: Inject CSS styles (once per page load)
    this._injectStyles();

    // Step 2: Create root container element
    this._createElement();

    // Step 3: Create MetricCard instances
    this._createMetricCards();

    // Step 4: Register event listeners
    this._registerEventListeners();

    // Step 5: Apply initial visibility
    this._applyVisibility();

    this._initialized = true;

    console.log(
      `[TopMenuBar] Initialized with ${Object.keys(this._metricCards).length} metrics`
    );

    return this;
  }

  // ---------------------------------------------------------------------------
  // Lifecycle: Destruction
  // ---------------------------------------------------------------------------

  /**
   * 销毁组件，释放所有资源。
   *
   * 清理清单：
   * 1. 取消所有待执行的 requestAnimationFrame
   * 2. 清除所有 Tooltip 定时器
   * 3. 销毁所有 MetricCard 子组件（含 DOM 移除和事件解绑）
   * 4. 从 DataService / EventBus 移除 data 事件监听
   * 5. 移除全局事件监听（click, resize, config change）
   * 6. 移除根 DOM 元素
   * 7. 移除注入的 <style> 元素
   * 8. 清空所有内部引用（防止悬挂引用导致内存泄漏）
   */
  destroy() {
    if (!this._initialized) return;

    console.log('[TopMenuBar] Destroying...');

    // Cancel pending animations
    if (this._updateAnimationId !== null) {
      cancelAnimationFrame(this._updateAnimationId);
      this._updateAnimationId = null;
    }

    // Clear all tooltip timers
    this._clearAllTooltipTimers();

    // Destroy all metric cards
    for (const id of Object.keys(this._metricCards)) {
      try {
        this._metricCards[id].destroy();
      } catch (error) {
        console.warn(`[TopMenuBar] Error destroying metric card "${id}":`, error);
      }
    }
    this._metricCards = {};

    // Unregister event listeners
    this._unregisterEventListeners();

    // Remove root element from DOM
    if (this._element && this._element.parentNode) {
      this._element.parentNode.removeChild(this._element);
    }
    this._element = null;

    // Remove injected style element
    if (this._styleEl && this._styleEl.parentNode) {
      this._styleEl.parentNode.removeChild(this._styleEl);
    }
    this._styleEl = null;

    // Clear internal state
    this._historyBuffer = {};
    this._currentData = null;
    this._pendingUpdate = false;
    this._initialized = false;

    console.log('[TopMenuBar] Destroyed completely');
  }

  // ---------------------------------------------------------------------------
  // Visibility Control
  // ---------------------------------------------------------------------------

  /**
   * 显示菜单栏。
   * 移除隐藏类并通过 CSS transition 平滑显现。
   */
  show() {
    this._visible = true;
    this._applyVisibility();
  }

  /**
   * 隐藏菜单栏。
   * 添加隐藏类使组件从渲染树中移除。
   */
  hide() {
    this._visible = false;
    this._applyVisibility();
  }

  /**
   * 切换显示/隐藏状态。
   * @returns {boolean} 切换后的可见状态。
   */
  toggle() {
    this._visible = !this._visible;
    this._applyVisibility();
    return this._visible;
  }

  // ---------------------------------------------------------------------------
  // Data Update Interface
  // ---------------------------------------------------------------------------

  /**
   * 更新所有指标的数据显示。
   *
   * 此方法是数据更新的主入口，可被以下方式触发：
   * - DataService 的 'data' 事件（自动监听）
   * - 外部手动调用（测试或强制刷新场景）
   *
   * 更新流程：
   * 1. 缓存最新数据快照
   * 2. 遍历 METRIC_DEFINITIONS 提取各指标值
   * 3. 动态判断指标可见性（GPU/RSV/PWR 在数据不可用时隐藏）
   * 4. 批量更新各 MetricCard（使用 rAF 合并写操作）
   * 5. 更新历史缓冲区（滑动窗口）
   *
   * @param {Object} data - 完整的数据快照对象（来自 WebSocket/Polling）。
   *                         预期结构见 METRIC_DEFINITIONS[].dataPath。
   */
  update(data) {
    if (!this._initialized || !data) return;

    const startTime = performance.now();

    // Cache latest data
    this._currentData = data;

    // Process each metric definition
    for (const def of TopMenuBar.METRIC_DEFINITIONS) {
      const card = this._metricCards[def.id];
      if (!card) continue;

      // Determine visibility based on data availability
      const visibility = this._determineVisibility(def, data);

      // Apply visibility
      if (visibility.visible) {
        card.element?.classList.remove('fxm-card-hidden');
      } else {
        card.element?.classList.add('fxm-card-hidden');
      }

      // Extract value using dot-path
      let value;
      if (visibility.customExtractor) {
        value = visibility.customExtractor(data);
      } else {
        value = this._getValueByPath(data, def.dataPath);
      }

      // Update card display
      card.updateValue(value);
      card.updateStatus(value);

      // Update history buffer for tooltip sparkline
      this._updateHistoryBuffer(def.id, value);
    }

    // Track performance
    const elapsed = performance.now() - startTime;
    this._lastUpdateTime = elapsed;

    if (elapsed > 5) {
      console.warn(
        `[TopMenuBar] Slow update: ${elapsed.toFixed(2)}ms (target < 5ms)`
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Getters
  // ---------------------------------------------------------------------------

  /**
   * 根 DOM 元素引用。
   * @type {HTMLElement|null}
   */
  get element() {
    return this._element;
  }

  /**
   * 组件是否已初始化完成。
   * @type {boolean}
   */
  get isInitialized() {
    return this._initialized;
  }

  /**
   * 组件是否当前可见。
   * @type {boolean}
   */
  get isVisible() {
    return this._visible;
  }

  /**
   * 获取所有 MetricCard 实例的只读映射。
   * @type {Readonly<Object<string, MetricCard>>}
   */
  get metricCards() {
    return Object.freeze({ ...this._metricCards });
  }

  /**
   * 获取最新的性能统计信息。
   * @type {Object}
   */
  get performanceStats() {
    return {
      lastUpdateTimeMs: this._lastUpdateTime,
      historyBufferSize: Object.keys(this._historyBuffer).reduce(
        (sum, key) => sum + (this._historyBuffer[key]?.length || 0),
        0
      ),
      activeCards: Object.keys(this._metricCards).filter(
        id => !this._metricCards[id].element?.classList.contains('fxm-card-hidden')
      ).length,
      totalCards: Object.keys(this._metricCards).length
    };
  }

  // ---------------------------------------------------------------------------
  // Private Methods - DOM Creation
  // ---------------------------------------------------------------------------

  /**
   * 注入组件 CSS 样式到文档 <head>。
   * 使用 data-fxm-component 属性标记避免重复注入。
   * @private
   */
  _injectStyles() {
    // Check if already injected
    const existing = document.querySelector('style[data-fxm-component="top-menu-bar"]');
    if (existing) return;

    this._styleEl = document.createElement('style');
    this._styleEl.setAttribute('data-fxm-component', 'top-menu-bar');
    this._styleEl.setAttribute('type', 'text/css');
    this._styleEl.textContent = TOPMENUBAR_CSS;

    document.head.appendChild(this._styleEl);
  }

  /**
   * 创建根容器 DOM 元素。
   * 设置基础属性、样式和 ARIA 标签。
   * @private
   */
  _createElement() {
    this._element = document.createElement('div');
    this._element.id = 'fxm-topmenubar';
    this._element.className = 'fxm-topmenubar';
    this._element.setAttribute('role', 'toolbar');
    this._element.setAttribute('aria-label', 'System Monitor Metrics');

    // Apply right offset
    this._element.style.right = `${this._rightOffset}px`;

    // Append to container
    this.container.appendChild(this._element);
  }

  /**
   * 根据 METRIC_DEFINITIONS 创建所有 MetricCard 子组件。
   * 使用 DocumentFragment 批量插入以最小化 DOM 回流。
   * @private
   */
  _createMetricCards() {
    const fragment = document.createDocumentFragment();

    for (const def of TopMenuBar.METRIC_DEFINITIONS) {
      // Check user config for individual metric visibility override
      const configVisible = this._getConfigMetricVisibility(def.id);

      const card = new MetricCard({
        id: def.id,
        label: def.label,
        icon: def.icon,
        colorVar: def.colorVar,
        dataPath: def.dataPath,
        unit: def.unit,
        formatter: def.formatter || undefined,
        visible: configVisible,
        thresholds: def.thresholds
      });

      // Render and append to fragment
      fragment.appendChild(card.render());

      // Store reference
      this._metricCards[def.id] = card;
    }

    // Batch insert into DOM
    this._element.appendChild(fragment);
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Event Management
  // ---------------------------------------------------------------------------

  /**
   * 注册所有事件监听器。
   * 包括：数据更新、子卡片交互、全局事件。
   * @private
   */
  _registerEventListeners() {
    // 1. Data service listener (real-time updates)
    if (this.dataService && typeof this.dataService.on === 'function') {
      this._boundDataHandler = (data) => this.update(data);
      this.dataService.on('data', this._boundDataHandler);
    }

    // Also listen via eventBus if available (alternative path)
    if (this.eventBus && typeof this.eventBus.on === 'function') {
      // Listen for data events through global bus as well
      if (!this._boundDataHandler) {
        this._boundDataHandler = (data) => this.update(data);
      }
      this.eventBus.on('monitor:data', this._boundDataHandler);
    }

    // 2. Metric card interaction events (delegated to root element)
    this._boundMetricMouseEnter = (e) => this._onMetricMouseEnter(e);
    this._boundMetricMouseLeave = (e) => this._onMetricMouseLeave(e);

    if (this._element) {
      this._element.addEventListener('metric:mouseenter', this._boundMetricMouseEnter);
      this._element.addEventListener('metric:mouseleave', this._boundMetricMouseLeave);
      this._element.addEventListener('metric:click', (e) => {
        this._onMetricClick(e);
      });
    }

    // 3. Outside click to close tooltips
    this._boundOutsideClick = (e) => this._onOutsideClick(e);
    document.addEventListener('click', this._boundOutsideClick);

    // 4. Window resize for responsive adjustments
    this._boundResizeHandler = () => this._onWindowResize();
    window.addEventListener('resize', this._boundResizeHandler);

    // 5. Config changes (user toggles metric visibility)
    if (this.eventBus) {
      this._boundConfigChangeHandler = (eventData) => this._onConfigChange(eventData);
      this.eventBus.on('config:change', this._boundConfigChangeHandler);
    }
  }

  /**
   * 注销所有事件监听器。
   * 与 _registerEventListeners() 完全对称，确保零内存泄漏。
   * @private
   */
  _unregisterEventListeners() {
    // 1. Data service
    if (this.dataService && this._boundDataHandler) {
      this.dataService.off('data', this._boundDataHandler);
    }

    // 1b. Event bus
    if (this.eventBus && this._boundDataHandler) {
      this.eventBus.off('monitor:data', this._boundDataHandler);
    }

    // 2. Delegated events on root element
    if (this._element) {
      if (this._boundMetricMouseEnter) {
        this._element.removeEventListener('metric:mouseenter', this._boundMetricMouseEnter);
      }
      if (this._boundMetricMouseLeave) {
        this._element.removeEventListener('metric:mouseleave', this._boundMetricMouseLeave);
      }
    }

    // 3. Outside click
    if (this._boundOutsideClick) {
      document.removeEventListener('click', this._boundOutsideClick);
    }

    // 4. Resize
    if (this._boundResizeHandler) {
      window.removeEventListener('resize', this._boundResizeHandler);
    }

    // 5. Config change
    if (this.eventBus && this._boundConfigChangeHandler) {
      this.eventBus.off('config:change', this._boundConfigChangeHandler);
    }

    // Clear references
    this._boundDataHandler = null;
    this._boundMetricMouseEnter = null;
    this._boundMetricMouseLeave = null;
    this._boundOutsideClick = null;
    this._boundResizeHandler = null;
    this._boundConfigChangeHandler = null;
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Event Handlers
  // ---------------------------------------------------------------------------

  /**
   * 处理子卡片的 mouseenter 事件。
   * 启动 TOOLTIP_DELAY_MS (500ms) 延迟后显示 Tooltip。
   *
   * @param {CustomEvent} e - metric:mouseenter 自定义事件。
   * @private
   */
  _onMetricMouseEnter(e) {
    const { metricId } = e.detail || {};
    if (!metricId) return;

    // Clear any existing timer for this metric
    this._clearTooltipTimer(metricId);

    // Start delayed show
    this._tooltipTimers[metricId] = setTimeout(() => {
      this._showTooltipForMetric(metricId);
      this._tooltipTimers[metricId] = null;
    }, TopMenuBar.TOOLTIP_DELAY_MS);
  }

  /**
   * 处理子卡片的 mouseleave 事件。
   * 取消待执行的 Tooltip 显示并立即隐藏该指标的 Tooltip。
   *
   * @param {CustomEvent} e - metric:mouseleave 自定义事件。
   * @private
   */
  _onMetricMouseLeave(e) {
    const { metricId } = e.detail || {};
    if (!metricId) return;

    // Cancel pending show
    this._clearTooltipTimer(metricId);

    // Hide immediately if showing
    if (this._activeTooltipMetric === metricId) {
      const card = this._metricCards[metricId];
      if (card) {
        card.hideTooltip();
      }
      this._activeTooltipMetric = null;
    }
  }

  /**
   * 处理子卡片的 click 事件。
   * 派发全局 menubar:metric:click 事件供 HoverPanel 等消费者响应。
   * 点击胶囊时触发显示 HoverPanel。
   *
   * @param {CustomEvent} e - metric:click 自定义事件。
   * @private
   */
  _onMetricClick(e) {
    const { metricId, value } = e.detail || {};
    if (!metricId) return;

    // Emit to event bus for other components (e.g., HoverPanel expand)
    if (this.eventBus) {
      this.eventBus.emit('menubar:metric:click', {
        metricId,
        value,
        source: 'topmenubar'
      });
      
      // 触发 HoverPanel 显示事件
      this.eventBus.emit('panel:show', {
        source: 'topmenubar',
        triggerMetric: metricId
      });
    }

    // Hide any open tooltip on click
    if (this._activeTooltipMetric) {
      const activeCard = this._metricCards[this._activeTooltipMetric];
      if (activeCard) {
        activeCard.hideTooltip();
      }
      this._activeTooltipMetric = null;
    }
  }

  /**
   * 处理点击组件外部区域的事件。
   * 关闭当前打开的所有 Tooltip。
   *
   * @param {MouseEvent} e - 全局 click 事件。
   * @private
   */
  _onOutsideClick(e) {
    if (!this._element || !this._activeTooltipMetric) return;

    // Check if click is outside our component
    const target = e.target;
    if (!this._element.contains(target)) {
      const activeCard = this._metricCards[this._activeTooltipMetric];
      if (activeCard) {
        activeCard.hideTooltip();
      }
      this._activeTooltipMetric = null;
    }
  }

  /**
   * 处理窗口 resize 事件。
   * 可在此处添加额外的响应式逻辑（如动态调整位置）。
   * 主要响应逻辑通过 CSS media queries 实现。
   * @private
   */
  _onWindowResize() {
    // CSS handles most responsive behavior via media queries.
    // This hook is available for JS-level adjustments if needed.

    // Example: adjust right offset on very small screens
    if (window.innerWidth < 600 && this._element) {
      this._element.style.right = '8px';
    } else if (this._element) {
      this._element.style.right = `${this._rightOffset}px`;
    }
  }

  /**
   * 处理配置变更事件。
   * 当用户通过 UI 修改了某个指标的可见性设置时，
   * 动态更新对应 MetricCard 的显示/隐藏状态。
   *
   * @param {Object} eventData - 配置变更事件数据。
   * @private
   */
  _onConfigChange(eventData) {
    if (!eventData || !eventData.path) return;

    // Only respond to metrics.*.visible changes
    const match = eventData.path.match(/^metrics\.(\w+)\.visible$/);
    if (!match) return;

    const metricId = match[1];
    const card = this._metricCards[metricId];
    if (!card) return;

    if (eventData.value === true) {
      card.element?.classList.remove('fxm-card-hidden');
    } else if (eventData.value === false) {
      card.element?.classList.add('fxm-card-hidden');
      // Also hide its tooltip if open
      card.hideTooltip();
    }
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Tooltip Management
  // ---------------------------------------------------------------------------

  /**
   * 为指定指标显示 Tooltip。
   * 收集历史数据和统计信息后传递给 MetricCard.showTooltip()。
   *
   * @param {string} metricId - 指标 ID。
   * @private
   */
  _showTooltipForMetric(metricId) {
    const card = this._metricCards[metricId];
    if (!card) return;

    // Gather history data
    const history = this._historyBuffer[metricId] || [];

    // Calculate statistics
    const values = history
      .map(h => h.value)
      .filter(v => v != null && typeof v === 'number');

    const stats = {
      current: values.length > 0 ? values[values.length - 1] : null,
      min: values.length > 0 ? Math.min(...values) : null,
      max: values.length > 0 ? Math.max(...values) : null,
      avg: values.length > 0
        ? values.reduce((a, b) => a + b, 0) / values.length
        : null,
      count: values.length
    };

    // Build tooltip data payload
    const tooltipData = {
      history,
      stats,
      dataSource: this._currentData?.data_source || this._currentData?.source || 'N/A'
    };

    // Show tooltip on the card
    card.showTooltip(tooltipData);

    // Track active tooltip
    this._activeTooltipMetric = metricId;
  }

  /**
   * 清除指定指标的 Tooltip 延迟定时器。
   *
   * @param {string} metricId - 指标 ID。
   * @private
   */
  _clearTooltipTimer(metricId) {
    if (this._tooltipTimers[metricId] !== undefined && this._tooltipTimers[metricId] !== null) {
      clearTimeout(this._tooltipTimers[metricId]);
      this._tooltipTimers[metricId] = null;
    }
  }

  /**
   * 清除所有指标的 Tooltip 定时器。
   * @private
   */
  _clearAllTooltipTimers() {
    for (const id of Object.keys(this._tooltipTimers)) {
      this._clearTooltipTimer(id);
    }
    this._tooltipTimers = {};
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Data Extraction & Visibility
  // ---------------------------------------------------------------------------

  /**
   * 安全地按点分路径提取嵌套对象值。
   *
   * 例：_getValueByPath(data, 'cpu_metrics.cpu_utilization') → 45.2
   *
   * @param {Object} obj - 目标对象。
   * @param {string} path - 点分路径（如 'gpu_metrics.vram_percent'）。
   * @returns {*} 提取到的值，路径不存在时返回 undefined。
   * @private
   */
  _getValueByPath(obj, path) {
    if (!obj || !path) return undefined;
    return path.split('.').reduce((acc, key) => acc?.[key], obj);
  }

  /**
   * 根据数据可用性动态确定指标的可见性。
   *
   * 规则：
   * - GPU/VRAM: 需要 gpu_metrics 对象存在且不为 null
   * - RSV: 需要 gpu_reserved 字段有定义（PyTorch CUDA 缓存）
   * - PWR: 需要 gpu_metrics.power_usage 有值（硬件需支持功耗查询）
   * - PRED/CPU/RAM: 始终可见（核心指标）
   *
   * @param {Object} def - 指标定义对象（来自 METRIC_DEFINITIONS）。
   * @param {Object} data - 完整数据快照。
   * @returns {{ visible: boolean, customExtractor?: Function }} 可见性及可选提取器。
   * @private
   */
  _determineVisibility(def, data) {
    switch (def.id) {
      case 'gpu':
      case 'vram':
        return {
          visible: data.gpu_metrics !== null && data.gpu_metrics !== undefined
        };

      case 'rsv':
        return {
          visible: data.gpu_reserved !== undefined && data.gpu_reserved !== null
        };

      case 'pwr':
        return {
          visible: data.gpu_metrics?.power_usage !== null &&
                  data.gpu_metrics?.power_usage !== undefined
        };

      case 'pred':
      case 'cpu':
      case 'ram':
      default:
        return { visible: true };
    }
  }

  /**
   * 从 ConfigManager 读取用户对指定指标可见性的偏好设置。
   *
   * @param {string} metricId - 指标 ID。
   * @returns {boolean} 用户配置的可见性（默认 true）。
   * @private
   */
  _getConfigMetricVisibility(metricId) {
    if (!this.config || !this.config.isReady) return true;

    try {
      const visible = this.config.get(`metrics.${metricId}.visible`);
      return visible !== false; // default true unless explicitly false
    } catch (error) {
      return true;
    }
  }

  // ---------------------------------------------------------------------------
  // Private Methods - History Buffer Management
  // ---------------------------------------------------------------------------

  /**
   * 更新历史数据缓冲区（滑动窗口机制）。
   * 保留最近 _maxHistoryLength 个数据点，超出部分从头部移除。
   * 用于 Tooltip Sparkline 趋势图绘制。
   *
   * @param {string} metricId - 指标 ID。
   * @param {*} value - 当前值。
   * @private
   */
  _updateHistoryBuffer(metricId, value) {
    if (!this._historyBuffer[metricId]) {
      this._historyBuffer[metricId] = [];
    }

    const buffer = this._historyBuffer[metricId];

    // Append new data point
    buffer.push({
      value: value,
      timestamp: Date.now()
    });

    // Enforce sliding window (remove oldest entries)
    while (buffer.length > this._maxHistoryLength) {
      buffer.shift();
    }
  }

  // ---------------------------------------------------------------------------
  // Private Methods - Visibility Application
  // ---------------------------------------------------------------------------

  /**
   * 将内部 _visible 状态同步到 DOM。
   * 通过 CSS 类控制显隐（而非 display:none 以保留动画能力）。
   * @private
   */
  _applyVisibility() {
    if (!this._element) return;

    if (this._visible) {
      this._element.classList.remove('fxm-hidden');
      this._element.classList.add('fxm-visible');
    } else {
      this._element.classList.remove('fxm-visible');
      this._element.classList.add('fxm-hidden');
    }
  }
}


// =============================================================================
// Exports
// =============================================================================

export { TopMenuBar, MetricCard };
export default TopMenuBar;
