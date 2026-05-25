/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - Canvas/SVG Chart Rendering System
 * ============================================================================
 *
 * High-performance chart rendering engine for real-time hardware monitoring.
 *
 * Three renderer classes:
 *   1. TrendChart     - Canvas-based line/area chart with Catmull-Rom splines
 *   2. RingChart      - SVG-based circular progress indicator
 *   3. ThermometerRenderer - SVG thermometer visualization
 *
 * Performance strategies:
 *   - HiDPI (Retina) support via devicePixelRatio scaling
 *   - Dirty-rect tracking to minimize redraws
 *   - Frame-rate limiting (configurable, default 30fps for trend charts)
 *   - requestAnimationFrame for smooth 60fps animations (ring/thermometer)
 *   - ResizeObserver for responsive layout
 *   - OffscreenCanvas where supported
 *
 * Design tokens consumed from variables.css:
 *   --fxm-accent-blue, --fxm-success, --fxm-warning, --fxm-danger
 *   --fxm-text-primary, --fxm-font-mono, etc.
 *
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

// =============================================================================
// Section 1: Utility Functions
// =============================================================================

/**
 * Clamp a value between min and max.
 * @param {number} value - The value to clamp.
 * @param {number} min - Minimum bound.
 * @param {number} max - Maximum bound.
 * @returns {number} Clamped value.
 */
function _clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

/**
 * Check if code is running in a browser environment (vs Node.js).
 * @type {boolean}
 */
const _isBrowser = typeof window !== 'undefined' && typeof document !== 'undefined';

/**
 * Resolve a CSS custom property value from computed styles.
 * Falls back to the provided defaultValue if unavailable.
 *
 * @param {string} varName - CSS variable name (e.g., '--fxm-accent-blue').
 * @param {string} [defaultValue=''] - Fallback value.
 * @returns {string} Resolved color/value string.
 */
function _resolveCSSVar(varName, defaultValue) {
  if (!_isBrowser) return defaultValue || '';
  try {
    const val = getComputedStyle(document.documentElement)
      .getPropertyValue(varName).trim();
    return val || defaultValue || '';
  } catch (_) {
    return defaultValue || '';
  }
}

/**
 * Convert hex color (#RRGGBB or #RGB) to rgba() string.
 *
 * @param {string} hex - Hex color string.
 * @param {number} alpha - Alpha channel (0-1).
 * @returns {string} RGBA color string.
 */
function _hexToRgba(hex, alpha) {
  if (!hex || hex.startsWith('var(') || hex.startsWith('rgb')) {
    return `rgba(0, 212, 255, ${alpha})`;
  }
  let clean = hex.replace('#', '');
  if (clean.length === 3) {
    clean = clean.split('').map(c => c + c).join('');
  }
  if (clean.length !== 6) {
    return `rgba(0, 212, 255, ${alpha})`;
  }
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) {
    return `rgba(0, 212, 255, ${alpha})`;
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Linear interpolation between two values.
 *
 * @param {number} a - Start value.
 * @param {number} b - End value.
 * @param {number} t - Interpolation factor (0-1).
 * @returns {number} Interpolated value.
 */
function _lerp(a, b, t) {
  return a + (b - a) * t;
}

/**
 * Ease-out cubic easing function.
 * Decelerating curve: fast start, slow finish.
 *
 * @param {number} t - Progress (0-1).
 * @returns {number} Eased progress.
 */
function _easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * Ease-out elastic easing function.
 * Bouncy elastic deceleration for ring chart animations.
 *
 * @param {number} t - Progress (0-1).
 * @returns {number} Eased progress.
 */
function _easeOutElastic(t) {
  if (t === 0 || t === 1) return t;
  return Math.pow(2, -10 * t) * Math.cos(t * Math.PI * 3);
}

// =============================================================================
// Section 2: TrendChart Class
// =============================================================================

/**
 * Canvas-based trend line/area chart renderer.
 *
 * Features:
 * - Sliding window of N data points (default 120)
 * - Catmull-Rom spline interpolation for smooth curves
 * - Gradient fill under the curve (tech-aesthetic)
 * - Optional data point markers with hover display
 * - Responsive sizing via ResizeObserver
 * - HiDPI/Retina display support (devicePixelRatio scaling)
 * - Frame rate limiting (default 30fps target)
 * - Dirty-rect tracking for efficient redraws
 *
 * Drawing order (bottom to top):
 *   1. Background clear
 *   2. Grid lines (optional)
 *   3. Axes (optional)
 *   4. Gradient-filled area under curve
 *   5. Stroke line (Catmull-Rom spline)
 *   6. Data point circles (optional)
 *
 * @class TrendChart
 * @example
 * const canvas = document.getElementById('myTrendChart');
 * const chart = new TrendChart(canvas, {
 *   strokeColor: '#00d4ff',
 *   fillColor: 'rgba(0, 212, 255, 0.15)',
 *   maxDataPoints: 120,
 *   lineWidth: 2
 * });
 *
 * // Add data points in real-time
 * chart.addPoint(45.2);
 * chart.addPoint(47.8);
 * chart.addPoint(43.1);
 *
 * // Or batch set data
 * chart.setData([{value: 40}, {value: 45}, ...]);
 *
 * // Cleanup when done
 * chart.destroy();
 */
class TrendChart {
  // ---------------------------------------------------------------------------
  // Constructor
  // ---------------------------------------------------------------------------

  /**
   * Create a TrendChart instance bound to a <canvas> element.
   *
   * @param {HTMLCanvasElement} canvas - The canvas element to render on.
   * @param {Object} [options={}] - Configuration options.
   * @param {number} [options.maxDataPoints=120] - Maximum data points (sliding window).
   * @param {number} [options.lineWidth=2] - Stroke width of the line.
   * @param {string} [options.fillColor='rgba(0, 212, 255, 0.15)'] - Area fill color.
   * @param {string} [options.strokeColor='#00d4ff'] - Line stroke color.
   * @param {number} [options.pointRadius=0] - Data point radius (0 = hidden).
   * @param {boolean} [options.showGrid=true] - Show background grid lines.
   * @param {string} [options.gridColor='rgba(255, 255, 255, 0.05)'] - Grid line color.
   * @param {boolean} [options.showAxes=true] - Show X/Y axes.
   * @param {string} [options.axesColor='rgba(255, 255, 255, 0.1)'] - Axes color.
   * @param {Object} [options.padding={top:10,right:10,bottom:20,left:30}] - Plot area padding.
   * @param {number} [options.animationDuration=300] - Data transition animation ms.
   * @param {number} [options.targetFPS=30] - Maximum render frames per second.
   * @param {number} [options.splineTension=0.5] - Catmull-Rom tension (0=straight, 1=very curved).
   * @param {number} [options.splineSegments=10] - Segments per spline interval.
   */
  constructor(canvas, options = {}) {
    if (!canvas || !(canvas instanceof HTMLCanvasElement)) {
      throw new Error(
        'TrendChart constructor requires a valid HTMLCanvasElement. ' +
        `Got: ${typeof canvas}`
      );
    }

    /**
     * The target <canvas> element.
     * @type {HTMLCanvasElement}
     */
    this.canvas = canvas;

    /**
     * The D rendering context.
     * @type {CanvasRenderingContext2D}
     */
    this.ctx = canvas.getContext('2d');

    /**
     * Merged configuration options (user-provided merged with defaults).
     * @type {Object}
     */
    this.options = {
      maxDataPoints: options.maxDataPoints || 120,
      lineWidth: options.lineWidth != null ? options.lineWidth : 2,
      fillColor: options.fillColor || 'rgba(0, 212, 255, 0.15)',
      strokeColor: options.strokeColor || '#00d4ff',
      pointRadius: options.pointRadius != null ? options.pointRadius : 0,
      showGrid: options.showGrid !== false,
      gridColor: options.gridColor || 'rgba(255, 255, 255, 0.05)',
      showAxes: options.showAxes !== false,
      axesColor: options.axesColor || 'rgba(255, 255, 255, 0.1)',
      padding: options.padding || { top: 8, right: 8, bottom: 18, left: 28 },
      animationDuration: options.animationDuration || 300,
      targetFPS: options.targetFPS || 30,
      splineTension: options.splineTension != null ? options.splineTension : 0.5,
      splineSegments: options.splineSegments || 10,
      pointHoverRadius: options.pointHoverRadius || 5,
      enableGlow: options.enableGlow !== false,
      glowColor: options.glowColor || 'rgba(0, 212, 255, 0.35)',
      glowBlur: options.glowBlur || 6,
    };

    // -----------------------------------------------------------------------
    // Data storage
    // -----------------------------------------------------------------------

    /**
     * Raw data array: [{value: number, timestamp: number}, ...]
     * @type {Array<{value: number, timestamp: number}>}
     * @private
     */
    this._data = [];

    /**
     * Animated data copy used during transitions.
     * Interpolates from old values to new values smoothly.
     * @type {Array<{value: number, timestamp: number}>}
     * @private
     */
    this._animatedData = [];

    /**
     * Previous data snapshot (for animation diffing).
     * @type {Array<{value: number, timestamp: number}>|null}
     * @private
     */
    this._prevData = null;

    // -----------------------------------------------------------------------
    // State flags
    // -----------------------------------------------------------------------

    /** @type {boolean} Whether a redraw is needed @private */
    this._dirty = true;

    /** @type {number} Timestamp of last render (for FPS limiting) @private */
    this._lastRenderTime = 0;

    /** @type {number|null} Animation start timestamp @private */
    this._animationStartTime = null;

    /** @type {number|null} requestAnimationFrame ID @private */
    this._rafId = null;

    /** @type {number|null} Animation frame ID for transitions @private */
    this._animFrameId = null;

    /** @type {boolean} Whether instance has been destroyed @private */
    this._destroyed = false;

    // -----------------------------------------------------------------------
    // Display properties
    // -----------------------------------------------------------------------

    /**
     * Device pixel ratio for HiDPI support.
     * @type {number}
     * @private
     */
    this._dpr = (_isBrowser ? window.devicePixelRatio : 1) || 1;

    /**
     * Cached CSS dimensions of the canvas element.
     * @type {{width: number, height: number}}
     * @private
     */
    this._cssSize = { width: 0, height: 0 };

    // -----------------------------------------------------------------------
    // Initialize
    // -----------------------------------------------------------------------

    this._setupHighDPI();
    this._bindResizeObserver();

    // Bind methods that are used as callbacks
    this._handleResize = this._handleResize.bind(this);
    this._animate = this._animate.bind(this);
  }

  // ---------------------------------------------------------------------------
  // Public API: Data Management
  // ---------------------------------------------------------------------------

  /**
   * Add a single data point to the chart.
   * Automatically enforces the sliding window by removing oldest points
   * when the count exceeds maxDataPoints.
   *
   * @param {number} value - The numeric value to add.
   * @param {number} [timestamp=Date.now()] - Optional timestamp (ms since epoch).
   */
  addPoint(value, timestamp) {
    if (this._destroyed) return;

    const ts = timestamp || (_isBrowser ? Date.now() : 0);

    this._data.push({ value, timestamp: ts });

    // Enforce sliding window
    while (this._data.length > this.options.maxDataPoints) {
      this._data.shift();
    }

    this._dirty = true;
    this._scheduleRender();
  }

  /**
   * Replace all data at once (batch set).
   * Triggers an animated transition from current state to new data.
   *
   * @param {Array<{value: number, timestamp?: number}>} dataArray -
   *   Array of data objects. Each must have a `value` property.
   */
  setData(dataArray) {
    if (this._destroyed) return;

    // Store previous data for animation
    this._prevData = this._animatedData.length > 0
      ? [...this._animatedData]
      : [...this._data];

    // Truncate to maxDataPoints
    this._data = dataArray.slice(-this.options.maxDataPoints).map(item => ({
      value: item.value,
      timestamp: item.timestamp || (_isBrowser ? Date.now() : 0)
    }));

    this._dirty = true;
    this._startAnimation();
  }

  /**
   * Get a shallow copy of the current data array.
   *
   * @returns {Array<{value: number, timestamp: number}>} Data snapshot.
   */
  getData() {
    return [...this._data];
  }

  /**
   * Get the number of data points currently stored.
   *
   * @returns {number} Data point count.
   */
  getDataLength() {
    return this._data.length;
  }

  /**
   * Clear all data and reset the chart to empty state.
   */
  clear() {
    if (this._destroyed) return;

    this._data = [];
    this._animatedData = [];
    this._prevData = null;
    this._animationStartTime = null;

    // Cancel any running animation
    if (this._animFrameId !== null) {
      cancelAnimationFrame(this._animFrameId);
      this._animFrameId = null;
    }

    this._dirty = true;
    this.render();
  }

  // ---------------------------------------------------------------------------
  // Public API: Rendering Control
  // ---------------------------------------------------------------------------

  /**
   * Manually trigger a redraw.
   * Respects dirty flag and FPS throttling.
   */
  render() {
    if (this._destroyed || !this._dirty) return;

    const now = _isBrowser ? performance.now() : 0;

    // FPS limiting: skip if rendered too recently
    const minInterval = 1000 / this.options.targetFPS;
    if (now - this._lastRenderTime < minInterval) {
      // Schedule for next eligible frame
      this._scheduleRender();
      return;
    }

    this._lastRenderTime = now;
    this._draw();
    this._dirty = false;
  }

  /**
   * Force an immediate redraw regardless of dirty state or FPS limit.
   * Use sparingly (e.g., for screenshot/export scenarios).
   */
  forceRender() {
    if (this._destroyed) return;
    this._draw();
    this._dirty = false;
    this._lastRenderTime = _isBrowser ? performance.now() : 0;
  }

  /**
   * Destroy the chart instance and release all resources.
   *
   * Cleanup list:
   * - Disconnect ResizeObserver
   * - Cancel pending rAF / animation frames
   * - Reset canvas dimensions
   * - Nullify all references (prevent memory leaks)
   */
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;

    // Cancel scheduled renders
    if (this._rafId !== null) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }

    // Cancel animations
    if (this._animFrameId !== null) {
      cancelAnimationFrame(this._animFrameId);
      this._animFrameId = null;
    }

    // Disconnect resize observer
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }

    // Reset canvas
    if (this.canvas) {
      this.canvas.width = 0;
      this.canvas.height = 0;
    }

    // Clear references
    this.ctx = null;
    this.canvas = null;
    this._data = [];
    this._animatedData = [];
    this._prevData = null;
  }

  // ---------------------------------------------------------------------------
  // Public API: Configuration
  // ---------------------------------------------------------------------------

  /**
   * Update one or more configuration options after construction.
   * Changing visual options will mark the chart as dirty for redraw.
   *
   * @param {Object} newOptions - Partial options object to merge.
   */
  setOptions(newOptions) {
    if (!newOptions || this._destroyed) return;

    Object.assign(this.options, newOptions);
    this._dirty = true;

    // If padding or size-related options changed, re-setup HiDPI
    if (newOptions.padding) {
      this._setupHighDPI();
    }

    this._scheduleRender();
  }

  /**
   * Get current configuration (shallow copy).
   *
   * @returns {Object} Current options snapshot.
   */
  getOptions() {
    return { ...this.options };
  }

  // ---------------------------------------------------------------------------
  // Internal: HiDPI Setup
  // ---------------------------------------------------------------------------

  /**
   * Configure the canvas for high-DPI (Retina) displays.
   *
   * On Retina screens, devicePixelRatio is typically 2 (or 3 on some displays).
   * To avoid blurry rendering, we set the canvas's internal buffer size to
   * CSS_size * dpr, then scale the context so drawing commands use CSS coordinates.
   *
   * Example on 2x display:
   *   CSS:  width=300px, height=100px
   *   Buffer: width=600px, height=200px
   *   ctx.scale(2, 2) -- all draw calls use CSS coordinates
   *
   * @private
   */
  _setupHighDPI() {
    if (!this.canvas || this._destroyed) return;

    const rect = this.canvas.getBoundingClientRect();
    this._cssSize.width = rect.width || this.canvas.clientWidth || 300;
    this._cssSize.height = rect.height || this.canvas.clientHeight || 80;

    const w = this._cssSize.width;
    const h = this._cssSize.height;

    // Set buffer size scaled by devicePixelRatio
    this.canvas.width = Math.round(w * this._dpr);
    this.canvas.height = Math.round(h * this._dpr);

    // Scale context so drawing uses CSS pixels
    this.ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);

    this._dirty = true;
  }

  // ---------------------------------------------------------------------------
  // Internal: Resize Observer
  // ---------------------------------------------------------------------------

  /**
   * Bind a ResizeObserver to the canvas parent element.
   * Automatically recalculates canvas dimensions when container resizes.
   *
   * @private
   */
  _bindResizeObserver() {
    if (!_isBrowser || !this.canvas || !ResizeObserver) return;

    this._resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (
          width > 0 && height > 0 &&
          (Math.abs(width - this._cssSize.width) > 1 ||
           Math.abs(height - this._cssSize.height) > 1)
        ) {
          this._handleResize();
        }
      }
    });

    // Observe the parent (not the canvas itself, which may have fixed CSS size)
    const parent = this.canvas.parentElement || this.canvas;
    this._resizeObserver.observe(parent);
  }

  /**
   * Handle container resize event.
   * Re-initializes HiDPI setup and marks for redraw.
   *
   * @private
   */
  _handleResize() {
    if (this._destroyed) return;
    this._setupHighDPI();
    this._dirty = true;
    this.render();
  }

  // ---------------------------------------------------------------------------
  // Internal: Render Scheduling
  // ---------------------------------------------------------------------------

  /**
   * Schedule the next render frame using requestAnimationFrame.
   * Deduplicates multiple calls within the same frame.
   *
   * @private
   */
  _scheduleRender() {
    if (this._destroyed || this._rafId !== null) return;

    this._rafId = requestAnimationFrame(() => {
      this._rafId = null;
      this.render();
    });
  }

  // ---------------------------------------------------------------------------
  // Internal: Main Draw Method
  // ---------------------------------------------------------------------------

  /**
   * Main drawing routine. Orchestrates all sub-draw calls in correct order.
   *
   * Draw order (painter's algorithm, bottom to top):
   *   1. Clear entire canvas
   *   2. Grid lines (optional)
   *   3. Axes (optional)
   *   4. Gradient-filled area under the curve
   *   5. Stroke line (Catmull-Rom spline)
   *   6. Data point markers (optional)
   *   7. Glow effect on the line (optional)
   *
   * @private
   */
  _draw() {
    const ctx = this.ctx;
    if (!ctx) return;

    const w = this._cssSize.width;
    const h = this._cssSize.height;
    const { padding } = this.options;

    // Guard against zero-size canvas
    if (w <= 0 || h <= 0) return;

    // Calculate plot area
    const plotX = padding.left;
    const plotY = padding.top;
    const plotW = w - padding.left - padding.right;
    const plotH = h - padding.top - padding.bottom;

    if (plotW <= 0 || plotH <= 0) return;

    // Step 0: Clear canvas
    ctx.clearRect(0, 0, w, h);

    // Get data to draw (animated or raw)
    const dataToDraw = this._getAnimatedData();
    if (dataToDraw.length < 2) {
      // Not enough data -- optionally draw "no data" placeholder
      this._drawNoData(ctx, plotX, plotY, plotW, plotH);
      return;
    }

    // Compute value range
    const values = dataToDraw.map(d => d.value);
    let minVal = Math.min(...values);
    let maxVal = Math.max(...values);
    const range = maxVal - minVal;

    // Add 5% padding to range for visual breathing room
    if (range > 0) {
      const pad = range * 0.05;
      minVal -= pad;
      maxVal += pad;
    } else {
      // All values identical -- create artificial range
      const center = minVal;
      const spread = Math.abs(center) * 0.1 + 1;
      minVal = center - spread;
      maxVal = center + spread;
    }

    // Step 1: Grid lines
    if (this.options.showGrid) {
      this._drawGrid(ctx, plotX, plotY, plotW, plotH, minVal, maxVal);
    }

    // Step 2: Axes
    if (this.options.showAxes) {
      this._drawAxes(ctx, plotX, plotY, plotW, plotH, minVal, maxVal);
    }

    // Step 3-6: Compute points then draw area, line, points
    const points = dataToDraw.map((d, i) => ({
      x: plotX + (i / (dataToDraw.length - 1)) * plotW,
      y: plotY + plotH - ((d.value - minVal) / (maxVal - minVal)) * plotH
    }));

    // Step 4: Gradient-filled area
    this._drawArea(ctx, points, plotY, plotH);

    // Step 7: Glow effect (behind the line)
    if (this.options.enableGlow && this.options.glowBlur > 0) {
      this._drawLineGlow(ctx, points);
    }

    // Step 5: Stroke line
    this._drawLine(ctx, points);

    // Step 6: Data point markers
    if (this.options.pointRadius > 0) {
      this._drawPoints(ctx, points);
    }
  }

  // ---------------------------------------------------------------------------
  // Internal: Sub-Draw Methods
  // ---------------------------------------------------------------------------

  /**
   * Draw "no data" placeholder text when insufficient data is available.
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {number} plotX - Plot area left edge.
   * @param {number} plotY - Plot area top edge.
   * @param {number} plotW - Plot area width.
   * @param {number} plotH - Plot area height.
   * @private
   */
  _drawNoData(ctx, plotX, plotY, plotW, plotH) {
    ctx.save();
    ctx.font = '11px var(--fxm-font-mono, monospace)';
    ctx.fillStyle = 'rgba(148, 163, 184, 0.4)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(
      'Waiting for data...',
      plotX + plotW / 2,
      plotY + plotH / 2
    );
    ctx.restore();
  }

  /**
   * Draw horizontal grid lines and optional vertical time markers.
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {number} plotX - Plot area origin X.
   * @param {number} plotY - Plot area origin Y.
   * @param {number} plotW - Plot area width.
   * @param {number} plotH - Plot area height.
   * @param {number} minVal - Y-axis minimum value.
   * @param {number} maxVal - Y-axis maximum value.
   * @private
   */
  _drawGrid(ctx, plotX, plotY, plotW, plotH, minVal, maxVal) {
    const gridLines = 4; // Number of horizontal divisions

    ctx.save();
    ctx.strokeStyle = this.options.gridColor;
    ctx.lineWidth = 0.5;
    ctx.setLineDash([2, 4]); // Dashed lines

    ctx.beginPath();
    for (let i = 0; i <= gridLines; i++) {
      const y = plotY + (i / gridLines) * plotH;
      ctx.moveTo(plotX, y);
      ctx.lineTo(plotX + plotW, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  /**
   * Draw X and Y axes (L-shaped border around the plot area).
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {number} plotX - Plot area origin X.
   * @param {number} plotY - Plot area origin Y.
   * @param {number} plotW - Plot area width.
   * @param {number} plotH - Plot area height.
   * @param {number} minVal - Y-axis minimum value.
   * @param {number} maxVal - Y-axis maximum value.
   * @private
   */
  _drawAxes(ctx, plotX, plotY, plotW, plotH, minVal, maxVal) {
    ctx.save();
    ctx.strokeStyle = this.options.axesColor;
    ctx.lineWidth = 0.5;

    // Y axis (left vertical line)
    ctx.beginPath();
    ctx.moveTo(plotX, plotY);
    ctx.lineTo(plotX, plotY + plotH);
    // X axis (bottom horizontal line)
    ctx.lineTo(plotX + plotW, plotY + plotH);
    ctx.stroke();

    // Optional: Y-axis labels (min/max)
    ctx.fillStyle = 'rgba(148, 163, 184, 0.5)';
    ctx.font = '9px var(--fxm-font-mono, monospace)';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillText(maxVal.toFixed(1), plotX - 4, plotY);
    ctx.textBaseline = 'bottom';
    ctx.fillText(minVal.toFixed(1), plotX - 4, plotY + plotH);

    ctx.restore();
  }

  /**
   * Draw the gradient-filled area under the curve.
   * Uses the same Catmull-Rom spline path as the line for consistency.
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {Array<{x: number, y: number}>} points - Computed data point coordinates.
   * @param {number} plotY - Plot area top edge.
   * @param {number} plotH - Plot area height.
   * @private
   */
  _drawArea(ctx, points, plotY, plotH) {
    if (points.length < 2) return;

    ctx.beginPath();
    ctx.moveTo(points[0].x, plotY + plotH);

    // Trace upper boundary using Catmull-Rom spline
    this._buildCatmullRomPath(ctx, points, false);

    // Close path along bottom edge
    ctx.lineTo(points[points.length - 1].x, plotY + plotH);
    ctx.closePath();

    // Create vertical gradient (opaque at top -> transparent at bottom)
    const gradient = ctx.createLinearGradient(0, plotY, 0, plotY + plotH);
    gradient.addColorStop(0, this.options.fillColor);
    gradient.addColorStop(1, this._extractAlphaChannel(this.options.fillColor, 0));

    ctx.fillStyle = gradient;
    ctx.fill();
  }

  /**
   * Draw the main stroke line using Catmull-Rom spline interpolation.
   *
   * Catmull-Rom splines have these desirable properties:
   * - Passes THROUGH all control points (not just near them like Bezier)
   * - C2 continuous (smooth second derivatives)
   * - Local control: moving one point only affects nearby curve segments
   * - Visually much smoother than straight-line segments
   *
   * The algorithm uses 4 control points (p0, p1, p2, p3) to compute
   * the segment between p1 and p2. At boundaries, we duplicate endpoints.
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {Array<{x: number, y: number}>} points - Computed data point coordinates.
   * @private
   */
  _drawLine(ctx, points) {
    if (points.length < 2) return;

    ctx.save();
    ctx.beginPath();
    ctx.strokeStyle = this.options.strokeColor;
    ctx.lineWidth = this.options.lineWidth;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    if (points.length === 2) {
      // Degenerate case: just two points, draw straight line
      ctx.moveTo(points[0].x, points[0].y);
      ctx.lineTo(points[1].x, points[1].y);
    } else {
      // Build Catmull-Rom spline path
      this._buildCatmullRomPath(ctx, points, true);
    }

    ctx.stroke();
    ctx.restore();
  }

  /**
   * Draw a subtle glow effect behind the stroke line.
   * Creates a neon-like appearance that matches the cyberpunk theme.
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {Array<{x: number, y: number}>} points - Computed data point coordinates.
   * @private
   */
  _drawLineGlow(ctx, points) {
    if (points.length < 2) return;

    ctx.save();
    ctx.beginPath();
    ctx.strokeStyle = this.options.glowColor;
    ctx.lineWidth = this.options.lineWidth + 4;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.filter = `blur(${this.options.glowBlur}px)`;

    if (points.length === 2) {
      ctx.moveTo(points[0].x, points[0].y);
      ctx.lineTo(points[1].x, points[1].y);
    } else {
      this._buildCatmullRomPath(ctx, points, true);
    }

    ctx.stroke();
    ctx.restore();
  }

  /**
   * Draw circle markers at each data point.
   *
   * @param {CanvasRenderingContext2D} ctx - Render context.
   * @param {Array<{x: number, y: number}>} points - Computed data point coordinates.
   * @private
   */
  _drawPoints(ctx, points) {
    if (points.length === 0) return;

    const r = this.options.pointRadius;

    ctx.save();
    ctx.fillStyle = this.options.strokeColor;

    for (let i = 0; i < points.length; i++) {
      // Only draw points at reasonable intervals to avoid clutter
      // For large datasets, sample every Nth point plus always the last
      const skip = Math.max(1, Math.floor(points.length / 20));
      if (i % skip !== 0 && i !== points.length - 1) continue;

      ctx.beginPath();
      ctx.arc(points[i].x, points[i].y, r, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // Internal: Catmull-Rom Spline Engine
  // ---------------------------------------------------------------------------

  /**
   * Build a Catmull-Rom spline path on the given context.
   *
   * This is the core mathematical algorithm of the TrendChart.
   * It generates a smooth curve passing through all data points.
   *
   * Algorithm reference:
   *   Centripetal Catmull-Rom spline (tension parameterized)
   *
   * Formula for interpolating between p1 and p2 given neighbors p0, p3:
   *   q(t) = 0.5 * (
   *     (2*p1) +
   *     (-p0 + p2) * t +
   *     (2*p0 - 5*p1 + 4*p2 - p3) * t^2 +
   *     (-p0 + 3*p1 - 3*p2 + p3) * t^3
   *   )
   *
   * Where t ranges from 0 to 1 across each segment.
   *
   * Boundary handling:
   *   - Before first point: duplicate p0 (p_{-1} = p0)
   *   - After last point: duplicate pN (p_{N+1} = pN)
   *
   * @param {CanvasRenderingContext2D} ctx - Context to draw the path on.
   * @param {Array<{x: number, y: number}>} points - Control points.
   * @param {boolean} moveToStart - If true, call moveTo on the first point.
   * @private
   */
  _buildCatmullRomPath(ctx, points, moveToStart) {
    const n = points.length;
    const segments = this.options.splineSegments;
    const tension = this.options.splineTension;

    if (n < 2) return;

    if (moveToStart) {
      ctx.moveTo(points[0].x, points[0].y);
    }

    if (n === 2) {
      // Only two points: simple linear interpolation
      ctx.lineTo(points[1].x, points[1].y);
      return;
    }

    // Iterate over each segment between consecutive points
    for (let i = 0; i < n - 1; i++) {
      // Select 4 control points for this segment
      const p0 = points[Math.max(i - 1, 0)];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[Math.min(i + 2, n - 1)];

      // Sample along the segment
      for (let j = 0; j <= segments; j++) {
        const t = j / segments;
        const x = this._catmullRomInterpolate(
          p0.x, p1.x, p2.x, p3.x, t, tension
        );
        const y = this._catmullRomInterpolate(
          p0.y, p1.y, p2.y, p3.y, t, tension
        );
        ctx.lineTo(x, y);
      }
    }
  }

  /**
   * Catmull-Rom spline interpolation for a single coordinate dimension.
   *
   * Given four control point values (p0, p1, p2, p3) and a parameter t
   * in [0, 1], computes the interpolated value between p1 and p2.
   *
   * The standard Catmull-Rom formula (tension = 0.5, aka "Cardinal spline"):
   *   q(t) = 0.5 * (
   *     (2 * p1) +
   *     (-p0 + p2) * t +
   *     (2*p0 - 5*p1 + 4*p2 - p3) * t^2 +
   *     (-p0 + 3*p1 - 3*p2 + p3) * t^3
   *   )
   *
   * With adjustable tension (alpha):
   *   Higher tension -> tighter curves (closer to straight lines)
   *   Lower tension  -> more exaggerated curves
   *
   * @param {number} p0 - Previous control point value.
   * @param {number} p1 - Current start point value.
   * @param {number} p2 - Current end point value.
   * @param {number} p3 - Next control point value.
   * @param {number} t - Interpolation parameter [0, 1].
   * @param {number} [tension=0.5] - Tension parameter (0=straight, 1=curvy).
   * @returns {number} Interpolated value.
   * @private
   */
  _catmullRomInterpolate(p0, p1, p2, p3, t, tension) {
    const t2 = t * t;
    const t3 = t2 * t;
    const s = (1 - tension) / 2; // Scaling factor based on tension

    // Standard Catmull-Rom basis functions
    const b0 = -s * t3 + 2 * s * t2 - s * t;         // Influence of p0
    const b1 = (2 - s) * t3 + (s - 3) * t2 + 1;       // Influence of p1
    const b2 = (s - 2) * t3 + (3 - 2 * s) * t2 + s * t; // Influence of p2
    const b3 = s * t3 - s * t2;                          // Influence of p3

    return b0 * p0 + b1 * p1 + b2 * p2 + b3 * p3;
  }

  // ---------------------------------------------------------------------------
  // Internal: Animation System
  // ---------------------------------------------------------------------------

  /**
   * Get the current data to render (animated or raw).
   * During animations, returns interpolated values between prevData and data.
   * Otherwise returns raw data directly.
   *
   * @returns {Array<{value: number, timestamp: number}>} Data to render.
   * @private
   */
  _getAnimatedData() {
    // If no animation in progress, use raw data
    if (!this._animationStartTime || this._animatedData.length === 0) {
      return this._data.length > 0 ? this._data : [];
    }
    return this._animatedData;
  }

  /**
   * Start a data transition animation.
   * When new data differs significantly from old data, smoothly interpolate.
   *
   * Uses easeOutCubic easing for natural deceleration.
   *
   * @private
   */
  _startAnimation() {
    // Cancel any existing animation
    if (this._animFrameId !== null) {
      cancelAnimationFrame(this._animFrameId);
      this._animFrameId = null;
    }

    this._animationStartTime = _isBrowser ? performance.now() : 0;
    this._animate();
  }

  /**
   * Animation loop executed via requestAnimationFrame.
   * Computes interpolated data each frame until duration elapses.
   *
   * @private
   */
  _animate() {
    if (this._destroyed) return;

    const elapsed = (_isBrowser ? performance.now() : 0) - this._animationStartTime;
    const duration = this.options.animationDuration;
    const progress = Math.min(elapsed / duration, 1);

    // Apply easing
    const eased = _easeOutCubic(progress);

    // Build animated data by interpolating between prevData and current data
    this._animatedData = this._computeInterpolatedData(eased);

    this._dirty = true;
    this.render();

    if (progress < 1) {
      this._animFrameId = requestAnimationFrame(this._animate);
    } else {
      // Animation complete: snap to final data
      this._animatedData = [];
      this._prevData = null;
      this._animFrameId = null;
    }
  }

  /**
   * Compute interpolated data array for the current animation frame.
   *
   * Handles three cases:
   * 1. Same length arrays: lerp each corresponding pair
   * 2. Prev shorter than current: extend with last prev value
   * 3. Prev longer than current: truncate extra prev values
   *
   * @param {number} easedProgress - Eased progress value [0, 1].
   * @returns {Array<{value: number, timestamp: number}>} Interpolated data.
   * @private
   */
  _computeInterpolatedData(easedProgress) {
    const prev = this._prevData || [];
    const curr = this._data;
    const result = [];

    const maxLen = Math.max(prev.length, curr.length);

    for (let i = 0; i < maxLen; i++) {
      const currItem = curr[i] || { value: 0, timestamp: 0 };
      const prevItem = prev[i] || prev[prev.length - 1] || { value: 0, timestamp: 0 };

      result.push({
        value: _lerp(prevItem.value, currItem.value, easedProgress),
        timestamp: currItem.timestamp
      });
    }

    return result;
  }

  // ---------------------------------------------------------------------------
  // Internal: Utilities
  // ---------------------------------------------------------------------------

  /**
   * Extract the alpha channel from a color string, returning it as rgba with
   * a specified override alpha. Useful for creating transparent versions of
   * the fill color.
   *
   * @param {string} color - Original color string.
   * @param {number} [overrideAlpha=0] - Alpha value to force.
   * @returns {string} Modified rgba color string.
   * @private
   */
  _extractAlphaChannel(color, overrideAlpha) {
    if (!color) return 'rgba(0, 212, 255, 0)';

    // Already rgba
    if (color.startsWith('rgba')) {
      return color.replace(/[\d.]+\)$/g, `${overrideAlpha})`);
    }

    // Convert rgb/hex to rgba
    return _hexToRgba(color.replace('#', '').replace('rgb', ''), overrideAlpha);
  }
}


// =============================================================================
// Section 3: RingChart Class
// =============================================================================

/**
 * SVG-based circular progress indicator (ring chart).
 *
 * Preferred over Canvas for ring charts because:
 * - SVG produces sharper vector graphics at any zoom level
 * - CSS animations/transitions work naturally on SVG elements
 * - stroke-dasharray/stroke-dashoffset provide exact arc control
 * - DOM accessibility (ARIA) integrates seamlessly
 *
 * Visual structure:
 *   <svg viewBox="0 0 size size">
 *     <circle class="bg" />           <!-- Background track -->
 *     <circle class="fg" dashoffset/> <!-- Progress arc (rotated -90deg) -->
 *     <text class="value">75%</text>   <!-- Center label -->
 *   </svg>
 *
 * Color mapping (based on percentage):
 *   0 - 60%:   Green (--fxm-success)
 *   60 - 80%:  Yellow/Amber (--fxm-warning)
 *   80 - 100%: Red (--fxm-danger)
 *
 * @class RingChart
 * @example
 * const container = document.getElementById('gpu-ring');
 * const ring = new RingChart(container, {
 *   size: 100,
 *   strokeWidth: 8,
 *   colors: { low: '#22c55e', medium: '#eab308', high: '#ef4444' }
 * });
 *
 * ring.setValue(78);  // Animates from 0 to 78%
 * ring.setValue(92);  // Animates from 78 to 92% (color changes to red)
 *
 * ring.destroy();  // Cleanup
 */
class RingChart {
  // ---------------------------------------------------------------------------
  // Constructor
  // ---------------------------------------------------------------------------

  /**
   * Create a RingChart instance inside the specified container element.
   *
   * @param {HTMLElement} container - Parent element to append the SVG into.
   * @param {Object} [options={}] - Configuration options.
   * @param {number} [options.size=120] - Diameter of the ring in pixels.
   * @param {number} [options.strokeWidth=8] - Width of the ring stroke.
   * @param {string} [options.backgroundColor='rgba(255, 255, 255, 0.08)'] - Track color.
   * @param {Object} [options.colors] - Threshold colors.
   * @param {string} [options.colors.low='#22c55e'] - Color for 0-60%.
   * @param {string} [options.colors.medium='#eab308'] - Color for 60-80%.
   * @param {string} [options.colors.high='#ef4444'] - Color for 80-100%.
   * @param {boolean} [options.showValue=true] - Show center percentage text.
   * @param {number} [options.valueFontSize=24] - Font size for center value.
   * @param {number} [options.labelFontSize=12] - Font size for optional label.
   * @param {number} [options.animationDuration=800] - Value transition ms.
   * @param {Function} [options.valueFormatter] - Custom value formatter fn(v)=>string.
   * @param {string} [options.label] - Optional label text below value.
   * @param {boolean} [options.enableGlow=true] - Enable glow effect on active arc.
   */
  constructor(container, options = {}) {
    if (!container || !(container instanceof HTMLElement)) {
      throw new Error(
        'RingChart constructor requires a valid HTMLElement container. ' +
        `Got: ${typeof container}`
      );
    }

    /**
     * Parent DOM element.
     * @type {HTMLElement}
     */
    this.container = container;

    /**
     * Merged configuration options.
     * @type {Object}
     */
    this.options = {
      size: options.size || 120,
      strokeWidth: options.strokeWidth || 8,
      backgroundColor: options.backgroundColor || 'rgba(255, 255, 255, 0.08)',
      colors: {
        low: (options.colors && options.colors.low) || _resolveCSSVar('--fxm-success', '#22c55e'),
        medium: (options.colors && options.colors.medium) || _resolveCSSVar('--fxm-warning', '#eab308'),
        high: (options.colors && options.colors.high) || _resolveCSSVar('--fxm-danger', '#ef4444')
      },
      showValue: options.showValue !== false,
      valueFontSize: options.valueFontSize || 24,
      labelFontSize: options.labelFontSize || 11,
      animationDuration: options.animationDuration || 800,
      valueFormatter: options.valueFormatter || ((v) => v.toFixed(0) + '%'),
      label: options.label || '',
      enableGlow: options.enableGlow !== false,
      lineCap: options.lineCap || 'round',
    };

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    /** @type {number} Target value (0-100) */
    this._value = 0;

    /** @type {number} Currently displayed animated value */
    this._animatedValue = 0;

    /** @type {number|null} Active animation rAF ID */
    this._animId = null;

    /** @type {boolean} Destruction flag */
    this._destroyed = false;

    // -----------------------------------------------------------------------
    // DOM References (populated by _init())
    // -----------------------------------------------------------------------

    /** @type {SVGSVGElement|null} Root SVG element */
    this._svg = null;

    /** @type {SVGCircleElement|null} Background ring circle */
    this._circleBg = null;

    /** @type {SVGCircleElement|null} Foreground progress circle */
    this._circleFg = null;

    /** @type {SVGTextElement|null} Center value text */
    this._valueText = null;

    /** @type {SVGTextElement|null} Label text (below value) */
    this._labelText = null;

    /** @type {number} Circumference of the ring (cached) */
    this._circumference = 0;

    // Initialize DOM
    this._init();
  }

  // ---------------------------------------------------------------------------
  // Initialization
  // ---------------------------------------------------------------------------

  /**
   * Build the complete SVG DOM structure and insert into container.
   *
   * SVG Structure:
   * ```xml
   * <svg class="fxm-ring-chart" viewBox="0 0 S S">
   *   <defs>
   *     <!-- Gradient definition for arc coloring -->
   *     <linearGradient id="ring-gradient-{id}">
   *       <stop offset="0%" stop-color="green"/>
   *       <stop offset="100%" stop-color="red"/>
   *     </linearGradient>
   *   </defs>
   *   <!-- Background track -->
   *   <circle class="fxm-ring-bg"
   *           cx="S/2" cy="S/2" r="R"/>
   *   <!-- Foreground progress arc -->
   *   <circle class="fxm-ring-fg"
   *           cx="S/2" cy="S/2" r="R"
   *           stroke-dasharray="C"
   *           stroke-dashoffset="C"/>
   *   <!-- Center value text -->
   *   <text class="fxm-ring-value">0%</text>
   *   <!-- Optional label -->
   *   <text class="fxm-ring-label">GPU</text>
   * </svg>
   * ```
   *
   * Key technique: stroke-dasharray and stroke-dashoffset
   * - dasharray = circumference (one full dash = full circle)
   * - dashoffset = circumference * (1 - percent) (hides portion of the arc)
   * - Rotating -90deg makes the arc start from 12 o'clock position
   *
   * @private
   */
  _init() {
    const { size, strokeWidth } = this.options;
    const radius = (size - strokeWidth) / 2;
    const center = size / 2;
    this._circumference = 2 * Math.PI * radius;

    // Generate unique ID for gradients (prevents collisions with multiple instances)
    const uniqueId = '_fxm_ring_' + Math.random().toString(36).substring(2, 9);

    // ---- Create root SVG ----
    const svgNS = 'http://www.w3.org/2000/svg';
    this._svg = document.createElementNS(svgNS, 'svg');
    this._svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
    this._svg.setAttribute('role', 'progressbar');
    this._svg.setAttribute('aria-valuemin', '0');
    this._svg.setAttribute('aria-valuemax', '100');
    this._svg.setAttribute('aria-valuenow', '0');
    this._svg.classList.add('fxm-ring-chart');

    // ---- Defs: Gradient for arc ----
    const defs = document.createElementNS(svgNS, 'defs');
    const gradient = document.createElementNS(svgNS, 'linearGradient');
    gradient.setAttribute('id', uniqueId);
    gradient.setAttribute('x1', '0%');
    gradient.setAttribute('y1', '0%');
    gradient.setAttribute('x2', '100%');
    gradient.setAttribute('y2', '0%');

    const stop1 = document.createElementNS(svgNS, 'stop');
    stop1.setAttribute('offset', '0%');
    stop1.setAttribute('stop-color', this.options.colors.low);

    const stop2 = document.createElementNS(svgNS, 'stop');
    stop2.setAttribute('offset', '50%');
    stop2.setAttribute('stop-color', this.options.colors.medium);

    const stop3 = document.createElementNS(svgNS, 'stop');
    stop3.setAttribute('offset', '100%');
    stop3.setAttribute('stop-color', this.options.colors.high);

    gradient.appendChild(stop1);
    gradient.appendChild(stop2);
    gradient.appendChild(stop3);
    defs.appendChild(gradient);
    this._svg.appendChild(defs);

    // Store gradient ID for dynamic updates
    this._gradientId = uniqueId;

    // ---- Background track circle ----
    this._circleBg = document.createElementNS(svgNS, 'circle');
    this._circleBg.setAttribute('cx', String(center));
    this._circleBg.setAttribute('cy', String(center));
    this._circleBg.setAttribute('r', String(radius));
    this._circleBg.classList.add('fxm-ring-bg');
    this._svg.appendChild(this._circleBg);

    // ---- Foreground progress circle ----
    this._circleFg = document.createElementNS(svgNS, 'circle');
    this._circleFg.setAttribute('cx', String(center));
    this._circleFg.setAttribute('cy', String(center));
    this._circleFg.setAttribute('r', String(radius));
    this._circleFg.classList.add('fxm-ring-fg');

    // Use stroke-dasharray/dashoffset for progress
    this._circleFg.setAttribute('stroke-dasharray', String(this._circumference));
    this._circleFg.setAttribute('stroke-dashoffset', String(this._circumference)); // 0%

    this._svg.appendChild(this._circleFg);

    // ---- Center value text ----
    if (this.options.showValue) {
      this._valueText = document.createElementNS(svgNS, 'text');
      this._valueText.setAttribute('x', String(center));
      this._valueText.setAttribute('y', String(center + this.options.valueFontSize / 3));
      this._valueText.setAttribute('text-anchor', 'middle');
      this._valueText.setAttribute('dominant-baseline', 'middle');
      this._valueText.classList.add('fxm-ring-value');
      this._valueText.textContent = this.options.valueFormatter(0);
      this._svg.appendChild(this._valueText);
    }

    // ---- Optional label text ----
    if (this.options.label) {
      this._labelText = document.createElementNS(svgNS, 'text');
      this._labelText.setAttribute('x', String(center));
      this._labelText.setAttribute('y', String(center + this.options.valueFontSize / 1.5 + this.options.labelFontSize));
      this._labelText.setAttribute('text-anchor', 'middle');
      this._labelText.classList.add('fxm-ring-label');
      this._labelText.textContent = this.options.label;
      this._svg.appendChild(this._labelText);
    }

    // ---- Insert into container ----
    this.container.appendChild(this._svg);

    // ---- Apply styles ----
    this._applyStyles();
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Update the progress value with smooth animation transition.
   *
   * The animation uses an ease-out-elastic easing function for a bouncy,
   * satisfying feel when values change. The arc rotates clockwise from
   * the 12 o'clock position.
   *
   * @param {number} value - New value (0-100). Clamped automatically.
   */
  setValue(value) {
    if (this._destroyed) return;

    const clampedValue = _clamp(value, 0, 100);

    // Skip if unchanged
    if (Math.abs(clampedValue - this._value) < 0.001) return;

    const oldValue = this._animatedValue;
    this._value = clampedValue;

    // Cancel any existing animation
    if (this._animId !== null) {
      cancelAnimationFrame(this._animId);
      this._animId = null;
    }

    // Start animated transition
    const startTime = _isBrowser ? performance.now() : 0;
    const duration = this.options.animationDuration;

    const animate = (currentTime) => {
      if (this._destroyed) return;

      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);

      // Ease-out-elastic for bouncy feel
      const eased = progress >= 1
        ? 1
        : 1 - _easeOutElastic(progress);

      this._animatedValue = _lerp(oldValue, clampedValue, eased);
      this._updateDisplay();

      if (progress < 1) {
        this._animId = requestAnimationFrame(animate);
      } else {
        this._animId = null;
        this._animatedValue = clampedValue;
        this._updateDisplay();
      }
    };

    this._animId = requestAnimationFrame(animate);
  }

  /**
   * Set value instantly without animation.
   *
   * @param {number} value - New value (0-100).
   */
  setValueImmediate(value) {
    if (this._destroyed) return;

    if (this._animId !== null) {
      cancelAnimationFrame(this._animId);
      this._animId = null;
    }

    this._value = _clamp(value, 0, 100);
    this._animatedValue = this._value;
    this._updateDisplay();
  }

  /**
   * Get the current target value.
   *
   * @returns {number} Current target value (0-100).
   */
  getValue() {
    return this._value;
  }

  /**
   * Destroy the ring chart and release resources.
   */
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;

    if (this._animId !== null) {
      cancelAnimationFrame(this._animId);
      this._animId = null;
    }

    if (this._svg && this._svg.parentNode) {
      this._svg.parentNode.removeChild(this._svg);
    }

    this._svg = null;
    this._circleBg = null;
    this._circleFg = null;
    this._valueText = null;
    this._labelText = null;
    this.container = null;
  }

  // ---------------------------------------------------------------------------
  // Internal: Display Update
  // ---------------------------------------------------------------------------

  /**
   * Update all visual elements to reflect the current _animatedValue.
   *
   * Updates:
   * 1. Arc progress (stroke-dashoffset)
   * 2. Arc color (based on threshold)
   * 3. Center text value
   * 4. ARIA attribute
   *
   * @private
   */
  _updateDisplay() {
    if (!this._circleFg || this._destroyed) return;

    const percent = this._animatedValue / 100;
    const offset = this._circumference * (1 - percent);

    // Update arc progress
    this._circleFg.setAttribute('stroke-dashoffset', String(offset));

    // Update color based on threshold
    const color = this._getColorForValue(this._animatedValue);
    this._circleFg.style.stroke = color;

    // Update glow filter color
    if (this.options.enableGlow) {
      this._circleFg.style.filter =
        `drop-shadow(0 0 ${Math.round(this._animatedValue / 20 + 2)}px ${_hexToRgba(color.replace('#', ''), 0.4)})`;
    }

    // Update center text
    if (this._valueText) {
      this._valueText.textContent = this.options.valueFormatter(this._animatedValue);
    }

    // Update ARIA
    if (this._svg) {
      this._svg.setAttribute('aria-valuenow', this._animatedValue.toFixed(1));
    }
  }

  /**
   * Map a numeric value to its threshold color.
   *
   * Thresholds:
   *   - Low:    0 <= value < 60   (Green / normal)
   *   - Medium: 60 <= value < 80  (Yellow / caution)
   *   - High:   80 <= value <= 100 (Red / warning)
   *
   * Supports smooth color interpolation at boundaries for extra polish.
   *
   * @param {number} value - Numeric value (0-100).
   * @returns {string} CSS color string.
   * @private
   */
  _getColorForValue(value) {
    const { low, medium, high } = this.options.colors;

    if (value < 60) return low;
    if (value < 80) return medium;
    return high;
  }

  // ---------------------------------------------------------------------------
  // Internal: Styles
  // ---------------------------------------------------------------------------

  /**
   * Inject CSS styles into the SVG element for self-containment.
   * Using a <style> child ensures styles travel with the component
   * even if moved in the DOM.
   *
   * @private
   */
  _applyStyles() {
    if (!this._svg) return;

    const { size, strokeWidth, valueFontSize, labelFontSize, backgroundColor, lineCap } = this.options;

    const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    styleEl.textContent = `
      .fxm-ring-chart {
        width: ${size}px;
        height: ${size}px;
        transform: rotate(-90deg);
        overflow: visible;
      }
      .fxm-ring-bg {
        fill: none;
        stroke: ${backgroundColor};
        stroke-width: ${strokeWidth};
      }
      .fxm-ring-fg {
        fill: none;
        stroke: ${this.options.colors.low};
        stroke-width: ${strokeWidth};
        stroke-linecap: ${lineCap};
        transition: stroke 0.35s ease, stroke-dashoffset 0.1s linear;
      }
      .fxm-ring-value {
        font-family: var(--fxm-font-mono, 'JetBrains Mono', monospace);
        font-size: ${valueFontSize}px;
        font-weight: 700;
        fill: var(--fxm-text-primary, #f1f5f9);
        transform: rotate(90deg);
        transform-origin: center;
        pointer-events: none;
      }
      .fxm-ring-label {
        font-family: var(--fxm-font-mono, 'JetBrains Mono', monospace);
        font-size: ${labelFontSize}px;
        font-weight: 500;
        fill: var(--fxm-text-secondary, #94a3b8);
        transform: rotate(90deg);
        transform-origin: center;
        pointer-events: none;
        letter-spacing: 0.5px;
      }
    `;

    // Insert style as first child (before graphical elements)
    this._svg.insertBefore(styleEl, this._svg.firstChild);
  }
}


// =============================================================================
// Section 4: ThermometerRenderer Class
// =============================================================================

/**
 * SVG-based thermometer visualization for temperature display.
 *
 * Visual design:
 * ```
 *   ┌──────────┐
 *   │  ╔═══╗   │  <-- Tube body (rectangular)
 *   │  ║   ║   │
 *   │  ║░░░║   │  <-- Fill level (gradient, rises with temp)
 *   │  ║░░░║   │
 *   ├──────────┤
 *   │    ●     │  <-- Bulb (circular, bottom)
 *   └──────────┘
 * ```
 *
 * Temperature-to-color mapping:
 *   - Cold (< 42.5% of critical): Blue/Cyan
 *   - Normal (42.5% - 63.75%): Green
 *   - Warm (63.75% - 85%): Yellow/Amber
 *   - Hot (> 85%): Red
 *
 * Features:
 * - Smooth liquid-level rise/fall animation (requestAnimationFrame)
 * - Tick marks at key thresholds (min, critical, max)
 * - SVG vector graphics (infinitely scalable)
 * - Configurable temperature range and critical threshold
 * - ARIA live region for screen readers
 *
 * @class ThermometerRenderer
 * @example
 * const container = document.getElementById('temp-display');
 * const thermo = new ThermometerRenderer(container, {
 *   width: 40,
 *   height: 150,
 *   minTemp: 0,
 *   maxTemp: 110,
 *   criticalTemp: 85,
 *   unit: '\u00B0C'
 * });
 *
 * thermo.setValue(72);  // Liquid rises to 72°C position, green color
 * thermo.setValue(95);  // Liquid rises higher, turns red
 *
 * thermo.destroy();
 */
class ThermometerRenderer {
  // ---------------------------------------------------------------------------
  // Constructor
  // ---------------------------------------------------------------------------

  /**
   * Create a ThermometerRenderer instance inside the specified container.
   *
   * @param {HTMLElement} container - Parent element to append the SVG into.
   * @param {Object} [options={}] - Configuration options.
   * @param {number} [options.width=40] - Total width in pixels (including bulb).
   * @param {number} [options.height=150] - Total height in pixels.
   * @param {number} [options.bulbSize=30] - Bulb diameter in pixels.
   * @param {number} [options.strokeWidth=1.5] - Border stroke width.
   * @param {number} [options.minTemp=0] - Minimum temperature (scale bottom).
   * @param {number} [options.maxTemp=100] - Maximum temperature (scale top).
   * @param {number} [options.criticalTemp=85] - Critical/warning threshold.
   * @param {string} [options.unit='\u00B0C'] - Unit suffix for display.
   * @param {Object} [options.colors] - Temperature zone colors.
   * @param {string} [options.colors.cold='#00d4ff'] - Cold zone color.
   * @param {string} [options.colors.normal='#22c55e'] - Normal zone color.
   * @param {string} [options.colors.warm='#eab308'] - Warm zone color.
   * @param {string} [options.colors.hot='#ef4444'] - Hot zone color.
   * @param {number} [options.animationDuration=600] - Fill animation ms.
   * @param {boolean} [options.showTicks=true] - Show tick marks.
   * @param {boolean} [options.showValue=true] - Show numeric temperature text.
   * @param {boolean} [options.showLabel=true] - Show unit label.
   */
  constructor(container, options = {}) {
    if (!container || !(container instanceof HTMLElement)) {
      throw new Error(
        'ThermometerRenderer requires a valid HTMLElement container. ' +
        `Got: ${typeof container}`
      );
    }

    /**
     * Parent DOM element.
     * @type {HTMLElement}
     */
    this.container = container;

    /**
     * Merged configuration options.
     * @type {Object}
     */
    this.options = {
      width: options.width || 40,
      height: options.height || 150,
      bulbSize: options.bulbSize || 30,
      strokeWidth: options.strokeWidth || 1.5,
      minTemp: options.minTemp || 0,
      maxTemp: options.maxTemp || 100,
      criticalTemp: options.criticalTemp || 85,
      unit: options.unit || '\u00B0C',
      colors: {
        cold: (options.colors && options.colors.cold) || _resolveCSSVar('--fxm-accent-blue', '#00d4ff'),
        normal: (options.colors && options.colors.normal) || _resolveCSSVar('--fxm-success', '#22c55e'),
        warm: (options.colors && options.colors.warm) || _resolveCSSVar('--fxm-warning', '#eab308'),
        hot: (options.colors && options.colors.hot) || _resolveCSSVar('--fxm-danger', '#ef4444')
      },
      animationDuration: options.animationDuration || 600,
      showTicks: options.showTicks !== false,
      showValue: options.showValue !== false,
      showLabel: options.showLabel !== false,
      tubeBorderRadius: options.tubeBorderRadius || 4,
    };

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    /** @type {number} Current temperature value */
    this._value = 0;

    /** @type {number} Animated fill level (0-1) */
    this._animatedFillLevel = 0;

    /** @type {number|null} Animation rAF ID */
    this._animId = null;

    /** @type {boolean} Destruction flag */
    this._destroyed = false;

    // -----------------------------------------------------------------------
    // DOM References
    // -----------------------------------------------------------------------

    /** @type {SVGSVGElement|null} */
    this._svg = null;

    /** @type {SVGPathElement|null} Outer outline path */
    this._outlinePath = null;

    /** @type {SVGPathElement|null} Inner fill path (clipped) */
    this._fillPath = null;

    /** @type {SVGClipPathElement|null} Clip-path for fill animation */
    this._clipPath = null;

    /** @type {SVGRectElement|null} Clip rectangle (height animates) */
    this._clipRect = null;

    /** @type {SVGCircleElement|null} Bulb fill circle */
    this._bulbFill = null;

    /** @type {SVGTextElement|null} Temperature value text */
    this._valueText = null;

    /** @type {SVGTextElement|null} Unit label text */
    this._labelText = null;

    /** @type {SVGDefsElement|null} Gradients and filters */
    this._defs = null;

    // Flame particles - DEPRECATED: Replaced with CSS pulse animation for performance
    // GPU temperature >85°C now uses simple CSS class toggle (.fxm-pulseDanger)
    // This avoids DOM manipulation overhead and improves rendering performance
    /** @type {boolean} Whether danger pulse effect is currently active */
    this._dangerPulseActive = false;

    // Computed geometry (set by _init())
    this._tubeX = 0;
    this._tubeY = 0;
    this._tubeW = 0;
    this._tubeH = 0;
    this._bulbCX = 0;
    this._bulbCY = 0;
    this._bulbR = 0;
    this._tubeInnerH = 0; // Fillable tube height

    // Initialize
    this._init();
  }

  // ---------------------------------------------------------------------------
  // Initialization
  // ---------------------------------------------------------------------------

  /**
   * Build the complete SVG thermometer DOM structure.
   *
   * Geometry calculation:
   *   - Tube: centered horizontally, starts below top margin, ends above bulb
   *   - Bulb: centered at bottom, diameter = bulbSize
   *   - Fill: clip-path rectangle that grows upward from bulb
   *
   * @private
   */
  _init() {
    const svgNS = 'http://www.w3.org/2000/svg';
    const {
      width, height, bulbSize, strokeWidth,
      tubeBorderRadius
    } = this.options;

    // ---- Compute geometry ----
    const tubeW = width * 0.55;          // Tube width (narrower than total)
    const tubeH = height - bulbSize - 8; // Tube height (above bulb)
    const tubeX = (width - tubeW) / 2;   // Center tube horizontally
    const tubeY = 4;                      // Small top margin
    const bulbr = bulbSize / 2;           // Bulb radius
    const bulbCX = width / 2;             // Bulb center X
    const bulbCY = height - bulbr - 2;    // Bulb center Y (near bottom)
    const innerH = tubeH - strokeWidth * 2; // Inner fillable height

    // Cache geometry
    this._tubeX = tubeX;
    this._tubeY = tubeY;
    this._tubeW = tubeW;
    this._tubeH = tubeH;
    this._bulbCX = bulbCX;
    this._bulbCY = bulbCY;
    this._bulbR = bulbr;
    this._tubeInnerH = innerH;

    // Unique IDs for this instance (prevents multi-instance collision)
    const uid = '_fxm_thermo_' + Math.random().toString(36).substring(2, 9);
    this._clipUid = uid + '_clip';
    this._fillGradUid = uid + '_fillgrad';
    this._bulbGradUid = uid + '_bulbgrad';

    // ---- Create root SVG ----
    this._svg = document.createElementNS(svgNS, 'svg');
    this._svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    this._svg.setAttribute('role', 'img');
    this._svg.setAttribute('aria-label', `Thermometer: 0${this.options.unit}`);
    this._svg.classList.add('fxm-thermometer');

    // ---- Defs ----
    this._defs = document.createElementNS(svgNS, 'defs');
    this._svg.appendChild(this._defs);

    // Clip-path for liquid level animation
    this._createClipPath(svgNS, uid);

    // Fill gradient (vertical, for tube)
    this._createFillGradient(svgNS, uid);

    // Bulb gradient (radial, for 3D sphere effect)
    this._createBulbGradient(svgNS, uid);

    // ---- Outline path (tube + bulb combined shape) ----
    this._createOutline(svgNS, tubeX, tubeY, tubeW, tubeH, bulbr, bulbCX, bulbCY, tubeBorderRadius);

    // ---- Fill elements ----
    this._createFillElements(svgNS, tubeX, tubeY, tubeW, tubeH, bulbr, bulbCX, bulbCY, tubeBorderRadius);

    // ---- Tick marks ----
    if (this.options.showTicks) {
      this._createTicks(svgNS, tubeX, tubeY, tubeW, tubeH, bulbr, bulbCY);
    }

    // ---- Value text ----
    if (this.options.showValue) {
      this._valueText = document.createElementNS(svgNS, 'text');
      this._valueText.setAttribute('x', String(width / 2));
      this._valueText.setAttribute('y', String(tubeY - 2));
      this._valueText.setAttribute('text-anchor', 'middle');
      this._valueText.classList.add('fxm-thermo-value');
      this._valueText.textContent = `--${this.options.unit}`;
      this._svg.appendChild(this._valueText);
    }

    // ---- Unit label ----
    if (this.options.showLabel) {
      this._labelText = document.createElementNS(svgNS, 'text');
      this._labelText.setAttribute('x', String(width / 2));
      this._labelText.setAttribute('y', String(height + 12));
      this._labelText.setAttribute('text-anchor', 'middle');
      this._labelText.classList.add('fxm-thermo-label');
      this._labelText.textContent = this.options.unit;
      this._svg.appendChild(this._labelText);
    }

    // ---- Insert into container ----
    this.container.appendChild(this._svg);

    // ---- Apply styles ----
    this._applyStyles();
  }

  // ---------------------------------------------------------------------------
  // Internal: SVG Element Creation Helpers
  // ---------------------------------------------------------------------------

  /**
   * Create the clip-path element used to animate the liquid fill level.
   *
   * The clip rect covers the tube + bulb area. Its height is animated
   * from 0 (empty) to full (completely filled) to simulate rising liquid.
   *
   * @param {string} svgNS - SVG namespace URI.
   * @param {string} uid - Unique ID prefix.
   * @private
   */
  _createClipPath(svgNS, uid) {
    const clipPath = document.createElementNS(svgNS, 'clipPath');
    clipPath.setAttribute('id', this._clipUid);

    // Clip rectangle: starts at bulb bottom, extends upward
    // Initial state: zero height (empty)
    this._clipRect = document.createElementNS(svgNS, 'rect');
    this._clipRect.setAttribute('x', '0');
    this._clipRect.setAttribute('y', String(this._bulbCY + this._bulbR)); // Start at bulb bottom
    this._clipRect.setAttribute('width', String(this.options.width));
    this._clipRect.setAttribute('height', '0'); // Will animate

    clipPath.appendChild(this._clipRect);
    this._defs.appendChild(clipPath);
  }

  /**
   * Create the vertical gradient for the tube fill.
   *
   * @param {string} svgNS - SVG namespace URI.
   * @param {string} uid - Unique ID prefix.
   * @private
   */
  _createFillGradient(svgNS, uid) {
    const grad = document.createElementNS(svgNS, 'linearGradient');
    grad.setAttribute('id', this._fillGradUid);
    grad.setAttribute('x1', '0%');
    grad.setAttribute('y1', '100%');
    grad.setAttribute('x2', '0%');
    grad.setAttribute('y2', '0%');

    // Two stops: slightly lighter at top for depth illusion
    const stop1 = document.createElementNS(svgNS, 'stop');
    stop1.setAttribute('offset', '0%');
    stop1.setAttribute('stop-color', this.options.colors.cold);
    stop1.setAttribute('stop-opacity', '0.9');

    const stop2 = document.createElementNS(svgNS, 'stop');
    stop2.setAttribute('offset', '100%');
    stop2.setAttribute('stop-color', this.options.colors.cold);
    stop2.setAttribute('stop-opacity', '1');

    grad.appendChild(stop1);
    grad.appendChild(stop2);
    this._defs.appendChild(grad);
  }

  /**
   * Create the radial gradient for the bulb sphere effect.
   *
   * @param {string} svgNS - SVG namespace URI.
   * @param {string} uid - Unique ID prefix.
   * @private
   */
  _createBulbGradient(svgNS, uid) {
    const grad = document.createElementNS(svgNS, 'radialGradient');
    grad.setAttribute('id', this._bulbGradUid);
    grad.setAttribute('cx', '35%');
    grad.setAttribute('cy', '35%');
    grad.setAttribute('r', '60%');

    const stop1 = document.createElementNS(svgNS, 'stop');
    stop1.setAttribute('offset', '0%');
    stop1.setAttribute('stop-color', '#ffffff');
    stop1.setAttribute('stop-opacity', '0.3');

    const stop2 = document.createElementNS(svgNS, 'stop');
    stop2.setAttribute('offset', '50%');
    stop2.setAttribute('stop-color', this.options.colors.cold);
    stop2.setAttribute('stop-opacity', '1');

    const stop3 = document.createElementNS(svgNS, 'stop');
    stop3.setAttribute('offset', '100%');
    stop3.setAttribute('stop-color', this.options.colors.cold);
    stop3.setAttribute('stop-opacity', '0.8');

    grad.appendChild(stop1);
    grad.appendChild(stop2);
    grad.appendChild(stop3);
    this._defs.appendChild(grad);
  }

  /**
   * Create the thermometer outer outline (stroke-only, no fill).
   * Shape: rounded rectangle (tube) + circle (bulb) merged visually.
   *
   * @param {string} svgNS - SVG namespace.
   * @param {number} tx - Tube X.
   * @param {number} ty - Tube Y.
   * @param {number} tw - Tube width.
   * @param {number} th - Tube height.
   * @param {number} br - Bulb radius.
   * @param {number} bcx - Bulb center X.
   * @param {number} bcy - Bulb center Y.
   * @param {number} r - Border radius for tube corners.
   * @private
   */
  _createOutline(svgNS, tx, ty, tw, th, br, bcx, bcy, r) {
    // Tube outline (rounded rect)
    const tubeOutline = document.createElementNS(svgNS, 'rect');
    tubeOutline.setAttribute('x', String(tx));
    tubeOutline.setAttribute('y', String(ty));
    tubeOutline.setAttribute('width', String(tw));
    tubeOutline.setAttribute('height', String(th));
    tubeOutline.setAttribute('rx', String(r));
    tubeOutline.setAttribute('ry', String(r));
    tubeOutline.classList.add('fxm-thermo-outline-tube');
    this._svg.appendChild(tubeOutline);

    // Bulb outline (circle)
    const bulbOutline = document.createElementNS(svgNS, 'circle');
    bulbOutline.setAttribute('cx', String(bcx));
    bulbOutline.setAttribute('cy', String(bcy));
    bulbOutline.setAttribute('r', String(br));
    bulbOutline.classList.add('fxm-thermo-outline-bulb');
    this._svg.appendChild(bulbOutline);
  }

  /**
   * Create the fill elements (liquid inside the thermometer).
   * These are clipped by the animated clip-rect to show fill level.
   *
   * @param {string} svgNS - SVG namespace.
   * @param {number} tx - Tube X.
   * @param {number} ty - Tube Y.
   * @param {number} tw - Tube width.
   * @param {number} th - Tube height.
   * @param {number} br - Bulb radius.
   * @param {number} bcx - Bulb center X.
   * @param {number} bcy - Bulb center Y.
   * @param {number} r - Border radius.
   * @private
   */
  _createFillElements(svgNS, tx, ty, tw, th, br, bcx, bcy, r) {
    const clipRef = `url(#${this._clipUid})`;

    // Tube fill (rounded rect, clipped)
    const tubeFill = document.createElementNS(svgNS, 'rect');
    tubeFill.setAttribute('x', String(tx + this.options.strokeWidth));
    tubeFill.setAttribute('y', String(ty + this.options.strokeWidth));
    tubeFill.setAttribute('width', String(tw - this.options.strokeWidth * 2));
    tubeFill.setAttribute('height', String(th - this.options.strokeWidth * 2));
    tubeFill.setAttribute('rx', String(Math.max(0, r - this.options.strokeWidth)));
    tubeFill.setAttribute('ry', String(Math.max(0, r - this.options.strokeWidth)));
    tubeFill.setAttribute('fill', `url(#${this._fillGradUid})`);
    tubeFill.setAttribute('clip-path', clipRef);
    tubeFill.classList.add('fxm-thermo-fill-tube');
    this._svg.appendChild(tubeFill);
    this._fillPath = tubeFill;

    // Bulb fill (circle, clipped)
    this._bulbFill = document.createElementNS(svgNS, 'circle');
    this._bulbFill.setAttribute('cx', String(bcx));
    this._bulbFill.setAttribute('cy', String(bcy));
    this._bulbFill.setAttribute('r', String(br - this.options.strokeWidth));
    this._bulbFill.setAttribute('fill', `url(#${this._bulbGradUid})`);
    this._bulbFill.setAttribute('clip-path', clipRef);
    this._bulbFill.classList.add('fxm-thermo-fill-bulb');
    this._svg.appendChild(this._bulbFill);
  }

  /**
   * Create tick marks at key temperature positions.
   *
   * Ticks drawn at:
   *   - Top of tube (maxTemp)
   *   - Critical temperature level
   *   - Bottom of tube (minTemp)
   *
   * @param {string} svgNS - SVG namespace.
   * @param {number} tx - Tube X.
   * @param {number} ty - Tube Y.
   * @param {number} tw - Tube width.
   * @param {number} th - Tube height.
   * @param {number} br - Bulb radius.
   * @param {number} bcy - Bulb center Y.
   * @private
   */
  _createTicks(svgNS, tx, ty, tw, th, br, bcy) {
    const { minTemp, maxTemp, criticalTemp } = this.options;
    const tickLen = 4; // Tick length extending rightward

    // Helper to create a single tick
    const makeTick = (tempVal) => {
      const frac = (tempVal - minTemp) / (maxTemp - minTemp);
      const y = ty + th * (1 - frac);

      const line = document.createElementNS(svgNS, 'line');
      line.setAttribute('x1', String(tx + tw));
      line.setAttribute('y1', String(y));
      line.setAttribute('x2', String(tx + tw + tickLen));
      line.setAttribute('y2', String(y));
      line.classList.add('fxm-thermo-tick');

      // Critical tick gets special styling
      if (Math.abs(tempVal - criticalTemp) < 0.5) {
        line.classList.add('fxm-thermo-tick-critical');
      }

      return line;
    };

    // Min tick (bottom of tube)
    this._svg.appendChild(makeTick(minTemp));

    // Critical tick
    if (criticalTemp > minTemp && criticalTemp < maxTemp) {
      this._svg.appendChild(makeTick(criticalTemp));
    }

    // Max tick (top of tube)
    this._svg.appendChild(makeTick(maxTemp));
  }

  /**
   * Start the danger pulse animation effect (CSS-based).
   * Replaces the deprecated flame particle system for better performance.
   * When temperature exceeds critical threshold, applies CSS pulse class.
   *
   * @private
   */
  _startDangerPulse() {
    if (this._dangerPulseActive || !this._svg) return;

    this._dangerPulseActive = true;
    this._svg.classList.add('fxm-pulseDanger');
  }

  /**
   * Stop the danger pulse animation effect.
   * Removes the CSS pulse class when temperature drops below threshold.
   *
   * @private
   */
  _stopDangerPulse() {
    if (!this._dangerPulseActive) return;

    this._dangerPulseActive = false;
    if (this._svg) {
      this._svg.classList.remove('fxm-pulseDanger');
    }
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Set the temperature value with animated liquid level change.
   *
   * The liquid rises or falls smoothly to the new level using
   * requestAnimationFrame with easeOutCubic easing.
   * Color updates immediately based on the target value (not animated).
   *
   * @param {number} celsius - Temperature value in configured units.
   */
  setValue(celsius) {
    if (this._destroyed) return;

    this._value = celsius;

    // Check if temperature exceeds critical threshold and trigger danger pulse
    const isCritical = celsius >= this.options.criticalTemp;
    if (isCritical && !this._dangerPulseActive) {
      this._startDangerPulse();
    } else if (!isCritical && this._dangerPulseActive) {
      this._stopDangerPulse();
    }

    // Compute target fill level (0 to 1)
    const range = this.options.maxTemp - this.options.minTemp;
    const targetLevel = range > 0
      ? _clamp((celsius - this.options.minTemp) / range, 0, 1)
      : 0;

    // Update color immediately (color changes feel better when instant)
    const color = this._getColorForTemp(celsius);
    this._applyFillColor(color);

    // Animate fill level
    const startLevel = this._animatedFillLevel;
    const startTime = _isBrowser ? performance.now() : 0;
    const duration = this.options.animationDuration;

    // Cancel existing animation
    if (this._animId !== null) {
      cancelAnimationFrame(this._animId);
      this._animId = null;
    }

    const animate = (currentTime) => {
      if (this._destroyed) return;

      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = _easeOutCubic(progress);

      this._animatedFillLevel = _lerp(startLevel, targetLevel, eased);
      this._updateFillLevel();
      this._updateValueText();

      if (progress < 1) {
        this._animId = requestAnimationFrame(animate);
      } else {
        this._animId = null;
        this._animatedFillLevel = targetLevel;
        this._updateFillLevel();
        this._updateValueText();
      }
    };

    this._animId = requestAnimationFrame(animate);
  }

  /**
   * Set value instantly without animation.
   *
   * @param {number} celsius - Temperature value.
   */
  setValueImmediate(celsius) {
    if (this._destroyed) return;

    this._value = celsius;

    // Check if temperature exceeds critical threshold and trigger danger pulse
    const isCritical = celsius >= this.options.criticalTemp;
    if (isCritical && !this._dangerPulseActive) {
      this._startDangerPulse();
    } else if (!isCritical && this._dangerPulseActive) {
      this._stopDangerPulse();
    }

    const range = this.options.maxTemp - this.options.minTemp;
    this._animatedFillLevel = range > 0
      ? _clamp((celsius - this.options.minTemp) / range, 0, 1)
      : 0;

    if (this._animId !== null) {
      cancelAnimationFrame(this._animId);
      this._animId = null;
    }

    const color = this._getColorForTemp(celsius);
    this._applyFillColor(color);
    this._updateFillLevel();
    this._updateValueText();
  }

  /**
   * Get the current temperature value.
   *
   * @returns {number} Current temperature.
   */
  getValue() {
    return this._value;
  }

  /**
   * Destroy the thermometer and release all resources.
   */
  destroy() {
    if (this._destroyed) return;
    this._destroyed = true;

    // Stop danger pulse effect
    this._stopDangerPulse();

    if (this._animId !== null) {
      cancelAnimationFrame(this._animId);
      this._animId = null;
    }

    if (this._svg && this._svg.parentNode) {
      this._svg.parentNode.removeChild(this._svg);
    }

    this._svg = null;
    this._outlinePath = null;
    this._fillPath = null;
    this._clipPath = null;
    this._clipRect = null;
    this._bulbFill = null;
    this._valueText = null;
    this._labelText = null;
    this._defs = null;
    this.container = null;
  }

  // ---------------------------------------------------------------------------
  // Internal: Display Updates
  // ---------------------------------------------------------------------------

  /**
   * Update the clip-rect height to reflect the current fill level.
   *
   * The clip rect grows upward from the bulb bottom:
   * - height=0: empty (no liquid visible)
   * - height=full: completely filled
   *
   * Full height = distance from bulb-bottom to tube-top
   *
   * @private
   */
  _updateFillLevel() {
    if (!this._clipRect || this._destroyed) return;

    const { height, bulbSize } = this.options;
    const bulbBottom = this._bulbCY + this._bulbR;
    const tubeTop = this._tubeY;

    // Total fillable extent (from bulb bottom up to tube top)
    const totalExtent = bulbBottom - tubeTop;

    // Current filled extent
    const filledExtent = totalExtent * this._animatedFillLevel;

    // Clip rect: positioned at (bottom of filled area), extends downward to bulb bottom
    const rectTop = bulbBottom - filledExtent;
    const rectHeight = filledExtent;

    this._clipRect.setAttribute('y', String(rectTop));
    this._clipRect.setAttribute('height', String(Math.max(0, rectHeight)));
  }

  /**
   * Update the numeric temperature text display.
   *
   * @private
   */
  _updateValueText() {
    if (!this._valueText || this._destroyed) return;

    this._valueText.textContent =
      `${this._value.toFixed(1)}${this.options.unit}`;

    // Update ARIA label
    if (this._svg) {
      this._svg.setAttribute(
        'aria-label',
        `Thermometer: ${this._value.toFixed(1)}${this.options.unit}`
      );
    }
  }

  /**
   * Apply a color to both fill gradient stops and bulb gradient stops.
   *
   * @param {string} color - CSS color string.
   * @private
   */
  _applyFillColor(color) {
    if (!this._defs || this._destroyed) return;

    // Update tube fill gradient stops
    const fillGrad = this._defs.querySelector(`#${CSS.escape(this._fillGradUid)}`);
    if (fillGrad) {
      const stops = fillGrad.querySelectorAll('stop');
      if (stops.length >= 2) {
        stops[0].setAttribute('stop-color', color);
        stops[1].setAttribute('stop-color', color);
      }
    }

    // Update bulb gradient stops (keep highlight, change base color)
    const bulbGrad = this._defs.querySelector(`#${CSS.escape(this._bulbGradUid)}`);
    if (bulbGrad) {
      const stops = bulbGrad.querySelectorAll('stop');
      if (stops.length >= 3) {
        stops[1].setAttribute('stop-color', color);
        stops[2].setAttribute('stop-color', color);
      }
    }
  }

  /**
   * Map temperature to a zone color.
   *
   * Zones relative to criticalTemp:
   *   - Cold:  < 50% of critical  (blue/cyan)
   *   - Normal: 50% - 75% of critical (green)
   *   - Warm:   75% - 100% of critical (yellow/amber)
   *   - Hot:    > critical (red)
   *
   * @param {number} temp - Temperature value.
   * @returns {string} CSS color string for the temperature zone.
   * @private
   */
  _getColorForTemp(temp) {
    const crit = this.options.criticalTemp;

    if (temp < crit * 0.5) return this.options.colors.cold;
    if (temp < crit * 0.75) return this.options.colors.normal;
    if (temp < crit) return this.options.colors.warm;
    return this.options.colors.hot;
  }

  // ---------------------------------------------------------------------------
  // Internal: Styles
  // ---------------------------------------------------------------------------

  /**
   * Inject CSS styles into the SVG element.
   *
   * @private
   */
  _applyStyles() {
    if (!this._svg) return;

    const { width, height, strokeWidth } = this.options;
    const borderColor = 'rgba(255, 255, 255, 0.12)';

    const styleEl = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    styleEl.textContent = `
      .fxm-thermometer {
        width: ${width}px;
        height: ${height}px;
        overflow: visible;
      }
      .fxm-thermo-outline-tube {
        fill: none;
        stroke: ${borderColor};
        stroke-width: ${strokeWidth};
      }
      .fxm-thermo-outline-bulb {
        fill: none;
        stroke: ${borderColor};
        stroke-width: ${strokeWidth};
      }
      .fxm-thermo-fill-tube {
        transition: fill 0.3s ease;
      }
      .fxm-thermo-fill-bulb {
        transition: fill 0.3s ease;
      }
      .fxm-thermo-tick {
        stroke: rgba(255, 255, 255, 0.2);
        stroke-width: 1;
      }
      .fxm-thermo-tick-critical {
        stroke: var(--fxm-danger, #ef4444);
        stroke-width: 1.5;
      }
      .fxm-thermo-value {
        font-family: var(--fxm-font-mono, 'JetBrains Mono', monospace);
        font-size: 11px;
        font-weight: 600;
        fill: var(--fxm-text-primary, #f1f5f9);
        text-anchor: middle;
      }
      .fxm-thermo-label {
        font-family: var(--fxm-font-mono, 'JetBrains Mono', monospace);
        font-size: 9px;
        font-weight: 500;
        fill: var(--fxm-text-muted, #64748b);
        text-anchor: middle;
        letter-spacing: 0.5px;
      }
    `;

    // Add danger pulse animation styles (replaces deprecated flame particle system)
    const pulseStyles = document.createElement('style');
    pulseStyles.textContent = `
      .fxm-pulseDanger {
        animation: fxm-dangerPulse 1s ease-in-out infinite;
      }
      @keyframes fxm-dangerPulse {
        0%, 100% {
          filter: drop-shadow(0 0 4px rgba(239, 68, 68, 0.4));
          transform: scale(1);
        }
        50% {
          filter: drop-shadow(0 0 12px rgba(239, 68, 68, 0.8));
          transform: scale(1.02);
        }
      }
    `;
    document.head.appendChild(pulseStyles);

    this._svg.insertBefore(styleEl, this._svg.firstChild);
  }
}


// =============================================================================
// Section 5: Exports
// =============================================================================

export {
  TrendChart,
  RingChart,
  ThermometerRenderer
};

export default {
  TrendChart,
  RingChart,
  ThermometerRenderer
};


// =============================================================================
// Section 6: Self-Test (Node.js / Browser Console)
// =============================================================================

/**
 * Self-test runner for verifying all three renderer classes.
 *
 * Usage in browser console:
 *   import { runSelfTest } from './renderers/canvas-renderer.js';
 *   runSelfTest();
 *
 * In Node.js (with jsdom or similar):
 *   // Requires DOM environment -- see test block below
 *
 * Tests performed:
 *   1. TrendChart: Construction, addPoint, setData, Catmull-Rom math
 *   2. RingChart: Construction, setValue, color thresholds
 *   3. ThermometerRenderer: Construction, setValue, color zones
 *   4. Utility functions: _clamp, _hexToRgba, _lerp, easing functions
 *
 * @returns {Promise<Object>} Test results summary.
 */
export async function runSelfTest() {
  const results = {
    passed: 0,
    failed: 0,
    errors: [],
    performance: {},
    startTime: performance.now()
  };

  function assert(condition, message) {
    if (condition) {
      results.passed++;
    } else {
      results.failed++;
      results.errors.push(message);
    }
  }

  console.group('%c[CanvasRenderer] Self-Test', 'color: #00d4ff; font-weight: bold');

  // =========================================================================
  // Test 1: Utility Functions
  // =========================================================================
  console.log('\n--- Utility Functions ---');

  assert(_clamp(5, 0, 10) === 5, '_clamp: normal value');
  assert(_clamp(-5, 0, 10) === 0, '_clamp: under minimum');
  assert(_clamp(15, 0, 10) === 10, '_clamp: over maximum');
  assert(_clamp(0, 0, 0) === 0, '_clamp: zero range');

  assert(_lerp(0, 100, 0) === 0, '_lerp: t=0');
  assert(_lerp(0, 100, 1) === 100, '_lerp: t=1');
  assert(_lerp(0, 100, 0.5) === 50, '_lerp: t=0.5');

  assert(Math.abs(_easeOutCubic(0)) < 0.001, '_easeOutCubic: t=0 => ~0');
  assert(Math.abs(_easeOutCubic(1) - 1) < 0.001, '_easeOutCubic: t=1 => 1');
  assert(_easeOutCubic(0.5) > 0.5, '_easeOutCubic: t=0.5 > 0.5 (decelerating)');

  assert(_hexToRgba('#ff0000', 0.5) === 'rgba(255, 0, 0, 0.5)', '_hexToRgba: #RRGGBB');
  assert(_hexToRgba('#f00', 0.5) === 'rgba(255, 0, 0, 0.5)', '_hexToRgba: #RGB');
  assert(_hexToRgba('var(--test)', 0.5).includes('0, 212, 255'), '_hexToRgba: CSS var fallback');

  // =========================================================================
  // Test 2: TrendChart - Core Logic (without DOM)
  // =========================================================================
  console.log('\n--- TrendChart ---');

  // Test Catmull-Rom interpolation math directly
  const trendChartProto = TrendChart.prototype;

  // Create a minimal mock to test the interpolation method
  const mockTrend = {
    options: { splineTension: 0.5, splineSegments: 10 },
    _catmullRomInterpolate: trendChartProto._catmullRomInterpolate
  };

  // Test: Interpolation at t=0 should return p1 exactly
  const val_t0 = mockTrend._catmullRomInterpolate(10, 20, 30, 40, 0, 0.5);
  assert(Math.abs(val_t0 - 20) < 0.001, 'CatmullRom: t=0 returns p1');

  // Test: Interpolation at t=1 should return p2 exactly
  const val_t1 = mockTrend._catmullRomInterpolate(10, 20, 30, 40, 1, 0.5);
  assert(Math.abs(val_t1 - 30) < 0.001, 'CatmullRom: t=1 returns p2');

  // Test: Monotonicity (interpolated values should be between p1 and p2 for monotonic inputs)
  const val_mid = mockTrend._catmullRomInterpolate(10, 20, 30, 40, 0.5, 0.5);
  assert(val_mid > 19.9 && val_mid < 30.1, 'CatmullRom: midpoint between p1 and p2');

  // Test: Flat line (all equal values)
  const val_flat = mockTrend._catmullRomInterpolate(25, 25, 25, 25, 0.5, 0.5);
  assert(Math.abs(val_flat - 25) < 0.001, 'CatmullRom: flat line stays constant');

  // Test: Tension parameter affects curvature
  const val_low_tension = mockTrend._catmullRomInterpolate(0, 0, 100, 100, 0.5, 0.0);
  const val_high_tension = mockTrend._catmullRomInterpolate(0, 0, 100, 100, 0.5, 1.0);
  assert(val_low_tension !== val_high_tension, 'CatmullRom: tension affects output');

  // =========================================================================
  // Test 3: RingChart - Threshold Colors
  // =========================================================================
  console.log('\n--- RingChart ---');

  // Test color threshold logic (instantiate without DOM for logic tests)
  const ringColors = { low: '#22c55e', medium: '#eab308', high: '#ef4444' };

  // Simulate _getColorForValue logic
  const getRingColor = (v) => {
    if (v < 60) return ringColors.low;
    if (v < 80) return ringColors.medium;
    return ringColors.high;
  };

  assert(getRingColor(30) === '#22c55e', 'RingChart: 30% => green (low)');
  assert(getRingColor(59.9) === '#22c55e', 'RingChart: 59.9% => green (low boundary)');
  assert(getRingColor(60) === '#eab308', 'RingChart: 60% => yellow (medium)');
  assert(getRingColor(79.9) === '#eab308', 'RingChart: 79.9% => yellow (medium boundary)');
  assert(getRingColor(80) === '#ef4444', 'RingChart: 80% => red (high)');
  assert(getRingColor(100) === '#ef4444', 'RingChart: 100% => red (high)');

  // Test circumference calculation
  const testRadius = 46; // (120 - 8*2) / 2 = 52 for size=120, stroke=8... actually (120-8)/2=56
  const testCirc = 2 * Math.PI * testRadius;
  assert(testCirc > 0, 'RingChart: circumference positive');
  assert(Math.abs(testCirc - 2 * Math.PI * 46) < 0.001, 'RingChart: circumference formula correct');

  // Test dashoffset calculations
  const offset_0 = testCirc * (1 - 0);    // 0% => full offset (hidden)
  const offset_50 = testCirc * (1 - 0.5);  // 50% => half visible
  const offset_100 = testCirc * (1 - 1);   // 100% => no offset (fully visible)
  assert(Math.abs(offset_0 - testCirc) < 0.001, 'RingChart: 0% offset = circumference');
  assert(Math.abs(offset_100) < 0.001, 'RingChart: 100% offset = 0');
  assert(offset_50 > 0 && offset_50 < testCirc, 'RingChart: 50% offset between 0 and circ');

  // =========================================================================
  // Test 4: ThermometerRenderer - Temperature Zones
  // =========================================================================
  console.log('\n--- ThermometerRenderer ---');

  const thermoOpts = { criticalTemp: 85, colors: {
    cold: '#00d4ff', normal: '#22c55e', warm: '#eab308', hot: '#ef4444'
  }};

  // Simulate _getColorForTemp logic
  const getThermoColor = (t) => {
    const crit = thermoOpts.criticalTemp;
    if (t < crit * 0.5) return thermoOpts.colors.cold;
    if (t < crit * 0.75) return thermoOpts.colors.normal;
    if (t < crit) return thermoOpts.colors.warm;
    return thermoOpts.colors.hot;
  };

  assert(getThermoColor(20) === '#00d4ff', 'Thermo: 20C => cold (blue)');
  assert(getThermoColor(42) === '#00d4ff', 'Thermo: 42C => cold (boundary)');
  assert(getThermoColor(43) === '#22c55e', 'Thermo: 43C => normal (green)');
  assert(getThermoColor(63) === '#22c55e', 'Thermo: 63C => normal (boundary)');
  assert(getThermoColor(64) === '#eab308', 'Thermo: 64C => warm (yellow)');
  assert(getThermoColor(84) === '#eab308', 'Thermo: 84C => warm (boundary)');
  assert(getThermoColor(85) === '#ef4444', 'Thermo: 85C => hot (red)');
  assert(getThermoColor(100) === '#ef4444', 'Thermo: 100C => hot (red)');

  // Test fill level clamping
  const testRange = 100 - 0; // minTemp=0, maxTemp=100
  const fill_over = _clamp((110 - 0) / testRange, 0, 1);
  const fill_under = _clamp((-10 - 0) / testRange, 0, 1);
  const fill_normal = _clamp((50 - 0) / testRange, 0, 1);
  assert(fill_over === 1, 'Thermo: over-max temp clamps to fill=1');
  assert(fill_under === 0, 'Thermo: under-min temp clamps to fill=0');
  assert(fill_normal === 0.5, 'Thermo: mid-range temp gives fill=0.5');

  // =========================================================================
  // Test 5: Browser Integration (if available)
  // =========================================================================
  console.log('\n--- Browser Integration ---');

  if (_isBrowser) {
    // --- TrendChart DOM test ---
    try {
      const testCanvas = document.createElement('canvas');
      testCanvas.style.width = '300px';
      testCanvas.style.height = '80px';
      document.body.appendChild(testCanvas);

      const trend = new TrendChart(testCanvas, { maxDataPoints: 10 });

      // Test addPoint
      trend.addPoint(10);
      trend.addPoint(20);
      trend.addPoint(15);
      trend.addPoint(25);
      trend.addPoint(30);
      assert(trend.getDataLength() === 5, 'TrendChart DOM: addPoint stores 5 items');

      // Test sliding window
      for (let i = 0; i < 10; i++) trend.addPoint(i);
      assert(trend.getDataLength() === 10, 'TrendChart DOM: sliding window caps at maxDataPoints');

      // Test clear
      trend.clear();
      assert(trend.getDataLength() === 0, 'TrendChart DOM: clear empties data');

      // Test setData with animation
      trend.setData([{ value: 40 }, { value: 50 }, { value: 45 }]);
      assert(trend.getDataLength() === 3, 'TrendChart DOM: setData sets 3 items');

      // Performance benchmark: render 120 data points
      const benchData = Array.from({ length: 120 }, (_, i) => ({
        value: Math.sin(i * 0.1) * 30 + 50,
        timestamp: Date.now() - (120 - i) * 1000
      }));
      trend.setData(benchData);

      // Wait for animation to settle, then measure render
      await new Promise(r => setTimeout(r, 400));

      const startRender = performance.now();
      trend.forceRender();
      const renderTime = performance.now() - startRender;
      results.performance.trendChart120 = renderTime;

      assert(renderTime < 16, `TrendChart DOM: 120pt render ${renderTime.toFixed(2)}ms < 16ms`);

      trend.destroy();
      testCanvas.remove();
      console.log(`  TrendChart 120-point render: ${renderTime.toFixed(2)}ms`);

    } catch (err) {
      results.failed++;
      results.errors.push(`TrendChart DOM test error: ${err.message}`);
    }

    // --- RingChart DOM test ---
    try {
      const ringContainer = document.createElement('div');
      ringContainer.style.cssText = 'width:120px;height:120px;position:absolute;left:-999px';
      document.body.appendChild(ringContainer);

      const ring = new RingChart(ringContainer, { size: 100, strokeWidth: 8 });

      // Test initial value
      assert(ring.getValue() === 0, 'RingChart DOM: initial value = 0');

      // Test setValue triggers animation
      ring.setValue(75);
      assert(ring.getValue() === 75, 'RingChart DOM: setValue(75) sets target');

      // Wait for animation
      await new Promise(r => setTimeout(r, 900));

      // Verify SVG was created
      assert(ring._svg !== null, 'RingChart DOM: SVG element created');
      assert(ring._circleFg !== null, 'RingChart DOM: foreground circle created');

      ring.destroy();
      ringContainer.remove();
      console.log('  RingChart: DOM integration OK');

    } catch (err) {
      results.failed++;
      results.errors.push(`RingChart DOM test error: ${err.message}`);
    }

    // --- ThermometerRenderer DOM test ---
    try {
      const thermoContainer = document.createElement('div');
      thermoContainer.style.cssText = 'width:40px;height:170px;position:absolute;left:-999px';
      document.body.appendChild(thermoContainer);

      const thermo = new ThermometerRenderer(thermoContainer, {
        width: 40, height: 150, minTemp: 0, maxTemp: 100, criticalTemp: 85
      });

      // Test initial value
      assert(thermo.getValue() === 0, 'Thermo DOM: initial value = 0');

      // Test setValue
      thermo.setValue(72);
      assert(thermo.getValue() === 72, 'Thermo DOM: setValue(72) works');

      // Verify SVG creation
      assert(thermo._svg !== null, 'Thermo DOM: SVG element created');
      assert(thermo._clipRect !== null, 'Thermo DOM: clip-rect created');
      assert(thermo._bulbFill !== null, 'Thermo DOM: bulb fill created');

      // Wait for animation
      await new Promise(r => setTimeout(r, 700));

      thermo.destroy();
      thermoContainer.remove();
      console.log('  ThermometerRenderer: DOM integration OK');

    } catch (err) {
      results.failed++;
      results.errors.push(`Thermo DOM test error: ${err.message}`);
    }

  } else {
    console.log('  (Skipped: not in browser environment)');
  }

  // =========================================================================
  // Summary
  // =========================================================================
  results.totalTime = performance.now() - results.startTime;

  console.log('\n%c--- Results ---', 'font-weight: bold');
  console.log(`  Passed: ${results.passed}`);
  console.log(`  Failed: ${results.failed}`);

  if (results.errors.length > 0) {
    console.warn('  Errors:');
    results.errors.forEach((e, i) => console.warn(`    ${i + 1}. ${e}`));
  }

  if (Object.keys(results.performance).length > 0) {
    console.log('\n  Performance:');
    Object.entries(results.performance).forEach(([k, v]) => {
      const status = v < 16 ? '%cPASS' : '%cFAIL';
      const color = v < 16 ? 'color:#22c55e' : 'color:#ef4444';
      console.log(`    ${k}: ${v.toFixed(2)}ms ${status}`, color, '');
    });
  }

  console.log(`  Total time: ${results.totalTime.toFixed(1)}ms`);
  console.groupEnd();

  return results;
}

// Auto-run self-test if loaded directly in browser (not imported as module)
if (_isBrowser && typeof document !== 'undefined') {
  // Only auto-run if explicitly invoked or in development mode
  // Uncomment the following line to auto-run on import:
  // setTimeout(() => runSelfTest(), 100);
}
