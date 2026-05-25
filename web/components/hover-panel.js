/**
 * ============================================================================
 * ComfyUI-Feixue-UniversalMonitor - HoverPanel (悬浮监控面板)
 * ============================================================================
 *
 * 核心UI组件 -- Cyberpunk 2077 风格的悬浮监控面板。
 *
 * 功能特性：
 * - 三种状态机：EXPANDED (展开) <-> COLLAPSED (折叠) <-> HIDDEN (隐藏)
 * - 高性能自由拖拽（transform: translate，60fps）
 * - 位置持久化（localStorage 存储 x, y）
 * - 四宫格概览卡片（CPU / RAM / GPU / VRAM）
 * - PRED 预测结果详细卡片
 * - 实时数据更新（requestAnimationFrame 批量渲染）
 * - 键盘快捷键支持（Escape 关闭、双击标题栏切换）
 * - 入场/退场动画（CSS Animation + spring 曲线）
 *
 * 状态机转换图：
 *   EXPANDED <---> COLLAPSED <---> HIDDEN
 *     ^  |            |  |           |
 *     |  +--collapse--+  +---close---+
 *     |                                   |
 *     +------------ expand ---------------+
 *                                         |
 *                    (via TopMenuBar) -----+
 *
 * 布局结构：
 * ┌──────────────────────────────────────────┐
 * │ ■ Universal Monitor        [−] [×]      │ ← 标题栏 (可拖拽)
 * ├──────────────────────────────────────────┤
 * │ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
 * │ │ CPU  │ │ RAM  │ │ GPU  │ │ VRAM │    │ ← 四宫格概览
 * │ │45.2% │ │50.0% │ │75.5% │ │60.0%│    │
 * │ └──────┘ └──────┘ └──────┘ └──────┘    │
 * │                                          │
 * │ ┌──────────────────────────────────────┐ │
 * │ │  PREDICTION RESULT                   │ │ ← PRED 卡片
 * │ │      ██████████████░░  85.5%         │ │
 * │ │      Risk: MEDIUM RISK               │ │
 * │ └──────────────────────────────────────┘ │
 * ├──────────────────────────────────────────┤
 * │ Last Update: 2s ago  | Source: amdsmi   │ ← 底部信息栏
 * └──────────────────────────────────────────┘
 *
 * @author Feixue
 * @version 1.0.0
 * @license MIT
 * ============================================================================
 */

'use strict';

// =============================================================================
// HoverPanel Class
// =============================================================================

/**
 * 悬浮监控面板（核心 UI 组件）。
 *
 * 这是 UniversalMonitor 项目的门面组件，负责：
 * 1. 构建完整的 DOM 结构（标题栏 + 四宫格 + PRED卡 + 底部栏）
 * 2. 管理面板状态（展开/折叠/隐藏）及过渡动画
 * 3. 处理用户交互（拖拽、按钮点击、键盘事件）
 * 4. 接收并渲染实时数据（来自 DataService 的 WebSocket 推送）
 * 5. 持久化用户偏好（位置、状态到 localStorage）
 *
 * @class HoverPanel
 * @example
 * import { HoverPanel } from './components/hover-panel.js';
 * import { globalEventBus } from './core/event-emitter.js';
 * import config from './core/config-manager.js';
 * import { DataService } from './services/websocket-service.js';
 *
 * const panel = new HoverPanel({
 *   container: document.body,
 *   eventBus: globalEventBus,
 *   config: config,
 *   dataService: dataService
 * });
 *
 * panel.init();
 */
class HoverPanel {
  // ---------------------------------------------------------------------------
  // Constructor
  // ---------------------------------------------------------------------------

  /**
   * 创建 HoverPanel 实例。
   *
   * @param {Object} [options={}] - 配置选项。
   * @param {HTMLElement} [options.container=document.body] - 面板挂载容器。
   * @param {EventEmitter} [options.eventBus=null] - 全局事件总线实例。
   * @param {ConfigManager} [options.config=null] - 配置管理器实例。
   * @param {DataService} [options.dataService=null] - 数据服务实例。
   */
  constructor(options = {}) {
    /**
     * 面板挂载的 DOM 容器。
     * @type {HTMLElement}
     */
    this.container = options.container || document.body;

    /**
     * 全局事件总线引用。
     * 用于发射 panel:* 事件和监听 data:update 事件。
     * @type {EventEmitter|null}
     */
    this.eventBus = options.eventBus || null;

    /**
     * 配置管理器引用。
     * 用于读取/写入 panelState 和 position 配置。
     * @type {ConfigManager|null}
     */
    this.config = options.config || null;

    /**
     * 数据服务引用。
     * 用于注册 data 事件监听器获取实时硬件数据。
     * @type {DataService|null}
     */
    this.dataService = options.dataService || null;

    // -------------------------------------------------------------------------
    // Internal State
    // -------------------------------------------------------------------------

    /**
     * 当前面板状态。
     * @type {'expanded'|'collapsed'|'hidden'}
     * @private
     */
    this._state = 'hidden'; // 默认隐藏，点击胶囊才显示

    /**
     * 面板位置坐标（相对于视口左上角）。
     * @type {{ x: number, y: number }}
     * @private
     */
    this._position = { x: 20, y: 60 };

    /**
     * 是否正在拖拽中。
     * @type {boolean}
     * @private
     */
    this._isDragging = false;

    /**
     * 拖拽偏移量（鼠标按下时记录）。
     * @type {{ x: number, y: number }}
     * @private
     */
    this._dragOffset = { x: 0, y: 0 };

    // -------------------------------------------------------------------------
    // DOM References
    // -------------------------------------------------------------------------

    /**
     * 主面板元素引用。
     * @type {HTMLElement|null}
     * @private
     */
    this._element = null;

    /**
     * 标题栏元素引用。
     * @type {HTMLElement|null}
     * @private
     */
    this._header = null;

    /**
     * 主体内容区元素引用。
     * @type {HTMLElement|null}
     * @private
     */
    this._body = null;

    /**
     * 底部信息栏元素引用。
     * @type {HTMLElement|null}
     * @private
     */
    this._footer = null;

    /**
     * 四宫格卡片元素映射表。
     * key: 'cpu' | 'ram' | 'gpu' | 'vram'
     * value: HTMLElement
     * @type {Object.<string, HTMLElement>}
     * @private
     */
    this._gridCards = {};

    /**
     * PRED 预测卡片元素引用。
     * @type {HTMLElement|null}
     * @private
     */
    this._predCard = null;

    // -------------------------------------------------------------------------
    // Data & Rendering
    // -------------------------------------------------------------------------

    /**
     * 当前缓存的最新数据快照。
     * 用于差量比较以减少不必要的 DOM 更新。
     * @type {Object|null}
     * @private
     */
    this._currentData = null;

    /**
     * requestAnimationFrame ID，用于取消未执行的渲染帧。
     * @type {number|null}
     * @private
     */
    this._animationFrameId = null;

    /**
     * 上次数据更新的时间戳（秒级 Unix 时间戳）。
     * 用于计算 "Xs ago" 相对时间显示。
     * @type {number|null}
     * @private
     */
    this._lastUpdateTimestamp = null;

    /**
     * 定时刷新底部时间显示的 setInterval ID。
     * @type {number|null}
     * @private
     */
    this._timeUpdateIntervalId = null;

    // -------------------------------------------------------------------------
    // Bind `this` Context
    // -------------------------------------------------------------------------
    // 将所有事件处理函数绑定到当前实例，
    // 避免在作为事件回调时 `this` 指向丢失。

    this._handleMouseDown = this._handleMouseDown.bind(this);
    this._handleMouseMove = this._handleMouseMove.bind(this);
    this._handleMouseUp = this._handleMouseUp.bind(this);
    this._handleKeyDown = this._handleKeyDown.bind(this);
    this._handleDoubleClick = this._handleDoubleClick.bind(this);
    this._onDataUpdate = this._onDataUpdate.bind(this);
  }

  // ---------------------------------------------------------------------------
  // Lifecycle: init() / render() / destroy()
  // ---------------------------------------------------------------------------

  /**
   * 初始化面板组件。
   *
   * 执行以下步骤：
   * 1. 从 ConfigManager 恢复保存的面板状态和位置
   * 2. 构建完整的 DOM 结构并插入容器
   * 3. 绑定所有事件监听器
   * 4. 注册 DataService 数据更新回调
   * 5. 启动时间戳自动刷新定时器
   * 6. 播放入场动画
   *
   * @returns {HoverPanel} 此实例（支持链式调用）。
   * @throws {Error} 如果 container 不是有效 DOM 元素。
   *
   * @example
   * panel.init();
   */
  init() {
    if (!this.container || !(this.container instanceof HTMLElement)) {
      throw new Error('HoverPanel.init(): container must be a valid HTMLElement');
    }

    // 1. 恢复持久化的状态和位置
    this._loadSavedState();

    // 2. 构建 DOM
    this.render();

    // 3. 绑定事件
    this._bindEvents();

    // 4. 注册数据源监听
    this._bindDataSource();

    // 5. 启动时间刷新定时器（每秒更新一次 "Xs ago" 显示）
    this._startTimeUpdater();

    // 6. 发射初始化完成事件
    this.eventBus?.emit('panel:ready', {
      state: this._state,
      position: { ...this._position }
    });

    console.log(
      `[HoverPanel] Initialized (state=${this._state}, ` +
      `pos=${this._position.x},${this._position.y})`
    );

    return this;
  }

  /**
   * 渲染面板完整 DOM 结构到容器中。
   *
   * 构建顺序：
   * 1. 创建主容器 div.fxm-hover-panel
   * 2. 构建标题栏（图标 + 名称 + 控制按钮）
   * 3. 构建主体区域（四宫格 + PRED 卡片）
   * 4. 构建底部信息栏
   * 5. 组装并插入 DOM
   * 6. 应用位置 + 播放入场动画
   */
  render() {
    // ====== 1. 主容器 ======
    this._element = document.createElement('div');
    this._element.className = `fxm-hover-panel fxm-glass-panel${this._state === 'hidden' ? ' fxm-hidden' : ''}`;
    this._element.setAttribute('role', 'dialog');
    this._element.setAttribute('aria-label', 'Hardware Monitor Panel');
    this._element.setAttribute('tabindex', '-1'); // 允许接收键盘焦点

    // 应用保存的位置
    this._applyPosition();

    // ====== 2. 标题栏 ======
    this._header = this._createHeader();

    // ====== 3. 主体区域 ======
    this._body = this._createBody();

    // ====== 4. 底部信息栏 ======
    this._footer = this._createFooter();

    // ====== 5. 组装 DOM ======
    this._element.appendChild(this._header);
    this._element.appendChild(this._body);
    this._element.appendChild(this._footer);

    // ====== 6. 插入容器 ======
    this.container.appendChild(this._element);

    // ====== 7. 入场动画 ======
    this._playEntranceAnimation();
  }

  /**
   * 销毁面板实例，释放所有资源。
   *
   * 清理清单：
   * - 移除所有 DOM 事件监听器
   * - 取消所有 requestAnimationFrame / setInterval 定时器
   * - 取消 DataService 数据监听
   * - 从 DOM 中移除面板元素
   * - 清空所有内部引用（防止内存泄漏）
   */
  destroy() {
    console.log('[HoverPanel] Destroying...');

    // 1. 取消未完成的 rAF 渲染帧
    if (this._animationFrameId !== null) {
      cancelAnimationFrame(this._animationFrameId);
      this._animationFrameId = null;
    }

    // 2. 停止时间刷新定时器
    if (this._timeUpdateIntervalId !== null) {
      clearInterval(this._timeUpdateIntervalId);
      this._timeUpdateIntervalId = null;
    }

    // 3. 解绑 DOM 事件
    this._unbindEvents();

    // 4. 取消数据源监听
    if (this.dataService) {
      try {
        this.dataService.off('data', this._onDataUpdate);
      } catch (_) {
        // 忽略解绑错误
      }
    }

    // 5. 从 DOM 移除
    if (this._element && this._element.parentNode) {
      this._element.parentNode.removeChild(this._element);
    }

    // 6. 清空引用
    this._element = null;
    this._header = null;
    this._body = null;
    this._footer = null;
    this._gridCards = {};
    this._predCard = null;
    this._currentData = null;
    this.eventBus = null;
    this.dataService = null;

    console.log('[HoverPanel] Destroyed, all resources cleaned up');
  }

  // ---------------------------------------------------------------------------
  // State Control (状态控制)
  // ---------------------------------------------------------------------------

  /**
   * 展开面板（显示完整的四宫格 + PRED 卡片 + 底部栏）。
   * 触发 CSS maxHeight/opacity 过渡动画（300ms ease-out）。
   */
  expand() {
    if (this._state === 'expanded') return;
    this._setState('expanded');
  }

  /**
   * 折叠面板（仅保留标题栏可见）。
   * 主体区域通过 maxHeight:0 + opacity:0 动画隐藏。
   */
  collapse() {
    if (this._state === 'collapsed') return;
    this._setState('collapsed');
  }

  /**
   * 关闭面板（完全隐藏，释放屏幕空间）。
   * 同时通知 TopMenuBar 显示"重新打开"按钮。
   */
  close() {
    if (this._state === 'hidden') return;
    this._setState('hidden');
  }

  /**
   * 在 expanded 和 collapsed 之间切换。
   * 如果当前为 hidden 则先展开。
   */
  toggle() {
    if (this._state === 'hidden') {
      this.expand();
    } else if (this._state === 'expanded') {
      this.collapse();
    } else {
      this.expand();
    }
  }

  /**
   * 从 hidden 状态重新显示面板。
   * 由 TopMenuBar 的"Show Monitor"按钮调用。
   */
  show() {
    if (this._state !== 'hidden') return;
    this._setState('expanded');
  }

  /**
   * 获取当前面板状态的只读副本。
   * @type {'expanded'|'collapsed'|'hidden'}
   * @readonly
   */
  get state() {
    return this._state;
  }

  // ---------------------------------------------------------------------------
  // Position Management (位置管理)
  // ---------------------------------------------------------------------------

  /**
   * 设置面板位置并立即应用到 DOM。
   *
   * @param {number} x - X 坐标（像素，相对于视口左边缘）。
   * @param {number} y - Y 坐标（像素，相对于视口上边缘）。
   */
  setPosition(x, y) {
    this._position = { x: Math.round(x), y: Math.round(y) };
    this._applyPosition();
  }

  /**
   * 获取当前位置的浅拷贝。
   * @returns {{ x: number, y: number }} 当前位置坐标。
   */
  getPosition() {
    return { ...this._position };
  }

  /**
   * 将当前位置持久化到 localStorage。
   * 通过 ConfigManager 的 position 路径存储。
   */
  savePosition() {
    if (this.config) {
      try {
        this.config.set('position', { ...this._position });
      } catch (error) {
        console.warn('[HoverPanel] Failed to save position:', error);
      }
    } else {
      // Fallback: 直接使用 localStorage
      try {
        localStorage.setItem(
          'fxm_panel_position',
          JSON.stringify(this._position)
        );
      } catch (_) {
        // 存储满或隐私模式，静默失败
      }
    }
  }

  /**
   * 从 localStorage 加载保存的位置。
   * 如果没有保存过则使用默认值 (20, 60)。
   *
   * @private
   */
  _loadPosition() {
    let saved = null;

    // 优先从 ConfigManager 读取
    if (this.config && this.config.isReady) {
      saved = this.config.get('position');
    }

    // Fallback: 直接从 localStorage 读取
    if (!saved) {
      try {
        const raw = localStorage.getItem('fxm_panel_position');
        if (raw) {
          saved = JSON.parse(raw);
        }
      } catch (_) {
        // 解析失败，使用默认值
      }
    }

    if (saved && typeof saved.x === 'number' && typeof saved.y === 'number') {
      // 边界安全检查
      this._position = {
        x: Math.max(0, Math.min(saved.x, window.innerWidth - 200)),
        y: Math.max(0, Math.min(saved.y, window.innerHeight - 100))
      };
    }
  }

  /**
   * 使用 transform: translate() 将位置应用到面板元素。
   *
   * 为什么不用 top/left？
   * - top/left 会触发浏览器 reflow（重排），需要重新计算布局
   * - transform 只触发 composite（合成），在 GPU 合成线程完成
   * - 性能差异：transform 比 top/left 快约 10 倍以上
   *
   * @private
   */
  _applyPosition() {
    if (!this._element) return;
    this._element.style.transform =
      `translate(${this._position.x}px, ${this._position.y}px)`;
  }

  // ---------------------------------------------------------------------------
  // Data Update (数据更新与渲染)
  // ---------------------------------------------------------------------------

  /**
   * 外部调用的数据更新入口。
   *
   * 由 DataService 的 'data' 事件触发。使用 requestAnimationFrame
   * 进行批量 DOM 更新，确保：
   * - 同一帧内多次调用只执行一次渲染
   * - 渲染发生在浏览器下一次绘制前（避免视觉闪烁）
   * - 数据变化时才实际操作 DOM（Diff 优化）
   *
   * @param {Object} data - 完整的数据快照，包含 cpu_metrics, ram_metrics,
   *                        gpu_metrics, prediction, timestamp 等字段。
   */
  update(data) {
    if (!data) return;

    // 取消上一帧未执行的渲染（防抖）
    if (this._animationFrameId !== null) {
      cancelAnimationFrame(this._animationFrameId);
    }

    // 记录最新时间戳
    if (data.timestamp) {
      this._lastUpdateTimestamp = data.timestamp;
    }

    // 安排在下一帧批量渲染
    this._animationFrameId = requestAnimationFrame(() => {
      this._animationFrameId = null;
      this._performRender(data);
    });
  }

  /**
   * 内部方法：执行实际的 DOM 渲染更新。
   *
   * 渲染顺序（按视觉重要性排列）：
   * 1. PRED 预测结果卡片
   * 2. 趋势图（更新历史数据并绘制）
   * 3. 系统信息卡片
   * 4. 底部信息栏（时间戳 + 数据源）
   *
   * @param {Object} data - 数据快照。
   * @private
   */
  _performRender(data) {
    this._renderPredictionCard(data);
    this._renderChart(data);
    this._renderSystemInfo(data);
    this._renderFooter(data);

    // 缓存当前数据用于后续 Diff 比较
    this._currentData = data;
  }

  // ---------------------------------------------------------------------------
  // DOM Factory Methods (DOM 构建工厂方法)
  // ---------------------------------------------------------------------------

  /**
   * 创建标题栏 DOM 元素。
   *
   * 结构：
   * <div class="fxm-panel-header">
   *   <div class="fxm-panel-title">       <!-- 左侧：图标 + 名称 -->
   *     <span class="fxm-panel-icon">■</span>
   *     <span class="fxm-panel-name">Universal Monitor</span>
   *   </div>
   *   <div class="fxm-panel-controls">    <!-- 右侧：折叠 + 关闭按钮 -->
   *     <button class="fxm-btn fxm-btn-collapse" aria-label="Collapse">−</button>
   *     <button class="fxm-btn fxm-btn-close" aria-label="Close">×</button>
   *   </div>
   * </div>
   *
   * @returns {HTMLElement} 标题栏元素。
   * @private
   */
  _createHeader() {
    const header = document.createElement('div');
    header.className = 'fxm-panel-header';

    header.innerHTML = `
      <div class="fxm-panel-title">
        <span class="fxm-panel-icon" aria-hidden="true">&#9632;</span>
        <span class="fxm-panel-name">Universal Monitor</span>
      </div>
      <div class="fxm-panel-controls">
        <button type="button"
                class="fxm-btn fxm-btn-collapse"
                aria-label="Collapse panel"
                title="Collapse"
                tabindex="0">&#8722;</button>
        <button type="button"
                class="fxm-btn fxm-btn-close"
                aria-label="Close panel"
                title="Close"
                tabindex="0">&times;</button>
      </div>
    `;

    return header;
  }

  /**
   * 创建主体内容区域 DOM 元素。
   *
   * 包含：
   * 1. PRED 预测结果卡片（核心功能）
   * 2. 实时趋势图（Canvas 折线图）
   * 3. 系统信息详情卡片
   *
   * @returns {HTMLElement} 主体区域元素。
   * @private
   */
  _createBody() {
    const body = document.createElement('div');
    body.className = 'fxm-panel-body';

    // --- PRED 卡片 ---
    this._predCard = this._createPredictionCard();

    // --- 趋势图组件 ---
    this._chartContainer = this._createChartContainer();

    // --- 系统信息卡片 ---
    this._systemInfoCard = this._createSystemInfoCard();

    body.appendChild(this._predCard);
    body.appendChild(this._chartContainer);
    body.appendChild(this._systemInfoCard);

    return body;
  }

  /**
   * 创建单个四宫格指标卡片。
   *
   * 每个卡片的结构：
   * <div class="fxm-grid-card fxm-grid-{type}">
   *   <div class="fxm-grid-card-header">
   *     <span class="fxm-grid-icon">{icon}</span>
   *     <span class="fxm-grid-label">{label}</span>
   *   </div>
   *   <div class="fxm-grid-value">{value}</div>     <!-- 大号数值 -->
   *   <div class="fxm-grid-unit">%</div>             <!-- 单位 -->
   *   <div class="fxm-grid-progress">              <!-- 进度条 -->
   *     <div class="fxm-grid-progress-bar"></div>
   *   </div>
   *   <div class="fxm-grid-status"></div>          <!-- 状态指示灯 -->
   * </div>
   *
   * @param {string} metricType - 指标类型: 'cpu' | 'ram' | 'gpu' | 'vram'
   * @returns {HTMLElement} 卡片元素。
   * @private
   */
  _createGridCard(metricType) {
    const card = document.createElement('div');
    card.className = `fxm-grid-card fxm-grid-${metricType}`;

    /** 各指标类型的图标和标签配置 */
    const config = {
      cpu:  { icon: '\u{1F5A5}\uFE0F', label: 'CPU' },   // 🖥️
      ram:  { icon: '\u{1F4BE}', label: 'RAM' },         // 💾
      gpu:  { icon: '\u26A1', label: 'GPU' },             // ⚡
      vram: { icon: '\u{1F3AE}', label: 'VRAM' },         // 🎮
    };

    const { icon, label } = config[metricType] || { icon: '?', label: metricType.toUpperCase() };

    card.innerHTML = `
      <div class="fxm-grid-card-header">
        <span class="fxm-grid-icon" aria-hidden="true">${icon}</span>
        <span class="fxm-grid-label">${label}</span>
      </div>
      <div class="fxm-grid-value" aria-live="polite">--</div>
      <div class="fxm-grid-unit">%</div>
      <div class="fxm-grid-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
        <div class="fxm-grid-progress-bar"></div>
      </div>
      <div class="fxm-grid-status fxm-status-unknown" aria-hidden="true"></div>
    `;

    return card;
  }

  /**
   * 创建 PRED 预测结果卡片。
   *
   * 这是面板中最复杂也是最重要的卡片，
   * 直接体现项目的核心创新价值 -- AI 推理成功率预测。
   *
   * 结构：
   * <div class="fxm-pred-card">
   *   <div class="fxm-pred-header">  <!-- 标题行 -->
   *     <span class="fxm-pred-icon">📊</span>
   *     <span>PREDICTION RESULT</span>
   *   </div>
   *   <div class="fxm-pred-body">
   *     <div class="fxm-pred-rate">    <!-- 成功率大字 -->
   *       <span class="fxm-pred-value">--</span>
   *       <span>% Success Rate</span>
   *     </div>
   *     <div class="fxm-pred-meter">  <!-- 进度仪表盘 -->
   *       <div class="fxm-pred-meter-fill"></div>
   *       <div class="fxm-pred-meter-markers"><!-- 阈值标记 --></div>
   *     </div>
   *     <div class="fxm-pred-risk">   <!-- 风险等级 Badge -->
   *       <span class="fxm-risk-badge">Detecting...</span>
   *     </div>
   *     <div class="fxm-pred-recommendations"> <!-- 建议列表 -->
   *       <ul class="fxm-rec-list"><li>Waiting...</li></ul>
   *     </div>
   *   </div>
   * </div>
   *
   * @returns {HTMLElement} PRED 卡片元素。
   * @private
   */
  _createPredictionCard() {
    const card = document.createElement('div');
    card.className = 'fxm-pred-card';

    card.innerHTML = `
      <div class="fxm-pred-header">
        <span class="fxm-pred-icon" aria-hidden="true">&#128202;</span>
        <span class="fxm-pred-title">PREDICTION RESULT</span>
      </div>
      <div class="fxm-pred-body">
        <div class="fxm-pred-rate">
          <span class="fxm-pred-value" aria-live="polite">--</span>
          <span class="fxm-pred-unit">% Success Rate</span>
        </div>
        <div class="fxm-pred-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <div class="fxm-pred-meter-fill"></div>
          <div class="fxm-pred-meter-markers">
            <span style="left: 40%" title="Low risk threshold">&#9679;</span>
            <span style="left: 70%" title="Medium risk threshold">&#9679;</span>
            <span style="left: 90%" title="High risk threshold">&#9679;</span>
          </div>
        </div>
        <div class="fxm-pred-risk">
          <span class="fxm-risk-badge fxm-risk-unknown">Detecting...</span>
        </div>
        <div class="fxm-pred-recommendations">
          <ul class="fxm-rec-list">
            <li>Waiting for workflow data...</li>
          </ul>
        </div>
      </div>
    `;

    return card;
  }

  /**
   * 创建实时趋势图容器。
   * 根据 SPEC.MD 第 423-434 行规范实现：
   * - 使用 Canvas 绘制折线图
   * - Catmull-Rom 样条插值（平滑曲线）
   * - 渐变色描边（起点 #00d4ff → 终点 #a855f7）
   * - 线下方半透明渐变填充
   * - 网格线：极淡水平虚线
   *
   * @returns {HTMLElement} 趋势图容器元素。
   * @private
   */
  _createChartContainer() {
    const container = document.createElement('div');
    container.className = 'fxm-chart-container';

    container.innerHTML = `
      <div class="fxm-chart-header">
        <span class="fxm-chart-icon" aria-hidden="true">&#128200;</span>
        <span class="fxm-chart-title">Real-time Trends</span>
        <div class="fxm-chart-legend">
          <span class="fxm-legend-item fxm-legend-cpu">
            <span class="fxm-legend-dot"></span>
            <span class="fxm-legend-label">CPU</span>
          </span>
          <span class="fxm-legend-item fxm-legend-gpu">
            <span class="fxm-legend-dot"></span>
            <span class="fxm-legend-label">GPU</span>
          </span>
        </div>
      </div>
      <div class="fxm-chart-canvas-wrap">
        <canvas class="fxm-chart-canvas" width="340" height="150"></canvas>
      </div>
      <div class="fxm-chart-stats">
        <div class="fxm-chart-stat">
          <span class="fxm-stat-label">Avg CPU</span>
          <span class="fxm-stat-value">--</span>
        </div>
        <div class="fxm-chart-stat">
          <span class="fxm-stat-label">Avg GPU</span>
          <span class="fxm-stat-value">--</span>
        </div>
        <div class="fxm-chart-stat">
          <span class="fxm-stat-label">Peak VRAM</span>
          <span class="fxm-stat-value">--</span>
        </div>
      </div>
    `;

    // 获取 Canvas 引用
    this._chartCanvas = container.querySelector('.fxm-chart-canvas');
    
    // 初始化历史数据缓冲区
    this._chartHistory = {
      cpu: [],
      gpu: [],
      vram: []
    };

    return container;
  }

  /**
   * 创建系统信息详情卡片。
   * 展示详细的硬件指标信息。
   *
   * @returns {HTMLElement} 系统信息卡片元素。
   * @private
   */
  _createSystemInfoCard() {
    const card = document.createElement('div');
    card.className = 'fxm-system-info-card';

    card.innerHTML = `
      <div class="fxm-system-header">
        <span class="fxm-system-icon" aria-hidden="true">&#128187;</span>
        <span class="fxm-system-title">System Info</span>
      </div>
      <div class="fxm-system-grid">
        <div class="fxm-system-item">
          <span class="fxm-system-label">CPU</span>
          <span class="fxm-system-value" data-metric="cpu">--</span>
          <span class="fxm-system-unit">%</span>
        </div>
        <div class="fxm-system-item">
          <span class="fxm-system-label">RAM</span>
          <span class="fxm-system-value" data-metric="ram">--</span>
          <span class="fxm-system-unit">%</span>
        </div>
        <div class="fxm-system-item">
          <span class="fxm-system-label">GPU</span>
          <span class="fxm-system-value" data-metric="gpu">--</span>
          <span class="fxm-system-unit">%</span>
        </div>
        <div class="fxm-system-item">
          <span class="fxm-system-label">VRAM</span>
          <span class="fxm-system-value" data-metric="vram">--</span>
          <span class="fxm-system-unit">%</span>
        </div>
        <div class="fxm-system-item">
          <span class="fxm-system-label">Power</span>
          <span class="fxm-system-value" data-metric="power">--</span>
          <span class="fxm-system-unit">W</span>
        </div>
        <div class="fxm-system-item">
          <span class="fxm-system-label">Temp</span>
          <span class="fxm-system-value" data-metric="temp">--</span>
          <span class="fxm-system-unit">C</span>
        </div>
      </div>
    `;

    return card;
  }

  /**
   * 创建底部信息栏 DOM 元素。
   *
   * 包含三段信息：
   * - 最后更新时间（相对时间格式："2s ago"）
   * - 数据来源标识（如 "amdsmi (ROCm 6.0)"）
   * - 版本号
   *
   * @returns {HTMLElement} 底部栏元素。
   * @private
   */
  _createFooter() {
    const footer = document.createElement('div');
    footer.className = 'fxm-panel-footer';

    footer.innerHTML = `
      <span class="fxm-footer-update">Last Update: --</span>
      <span class="fxm-footer-separator" aria-hidden="true">|</span>
      <span class="fxm-footer-source">Source: Detecting...</span>
      <span class="fxm-footer-separator" aria-hidden="true">|</span>
      <span class="fxm-footer-version">v1.0.0</span>
    `;

    return footer;
  }

  // ---------------------------------------------------------------------------
  // Render Methods (各子区域的渲染逻辑)
  // ---------------------------------------------------------------------------

  /**
   * 渲染四宫格概览卡片数据。
   *
   * 从 data 对象中提取 CPU/RAM/GPU/VRAM 的利用率数据，
   * 分别更新对应卡片的数值、进度条和状态颜色。
   *
   * @param {Object} data - 数据快照。
   * @private
   */
  _renderGridCards(data) {
    // CPU 利用率
    this._updateGridCard(
      'cpu',
      data.cpu_metrics?.cpu_utilization ?? null,
      '%'
    );

    // RAM 使用率
    this._updateGridCard(
      'ram',
      data.ram_metrics?.ram_percent ?? null,
      '%'
    );

    // GPU 利用率
    this._updateGridCard(
      'gpu',
      data.gpu_metrics?.gpu_utilization ?? null,
      '%'
    );

    // VRAM 使用率
    this._updateGridCard(
      'vram',
      data.gpu_metrics?.vram_percent ?? null,
      '%'
    );
  }

  /**
   * 更新单个四宫格卡片的数据显示。
   *
   * 性能优化策略：
   * - 使用 textContent 而非 innerHTML（避免 HTML 解析开销）
   * - 数值使用 toFixed(1) 保持等宽数字对齐
   * - 进度条 clamp 到 [0, 100] 防止溢出
   * - 状态颜色根据阈值分级（low < 60 / medium < 85 / high >= 85）
   *
   * @param {string} type - 卡片类型标识 ('cpu'|'ram'|'gpu'|'vram')
   * @param {number|null} value - 要显示的数值（null 表示无数据）
   * @param {string} unit - 单位后缀
   * @private
   */
  _updateGridCard(type, value, unit) {
    const card = this._gridCards[type];
    if (!card) return;

    const valueEl = card.querySelector('.fxm-grid-value');
    const progressBar = card.querySelector('.fxm-grid-progress-bar');
    const progressContainer = card.querySelector('.fxm-grid-progress');
    const statusEl = card.querySelector('.fxm-grid-status');

    if (value !== null && value !== undefined) {
      // 更新数值文本
      valueEl.textContent = value.toFixed(1);

      // 更新进度条宽度（clamp 到合法范围）
      const clampedValue = Math.min(100, Math.max(0, value));
      progressBar.style.width = clampedValue + '%';

      // 更新 ARIA 属性（无障碍支持）
      if (progressContainer) {
        progressContainer.setAttribute('aria-valuenow', clampedValue.toFixed(1));
      }

      // 更新状态指示灯颜色
      statusEl.className = 'fxm-grid-status ' + this._getStatusClass(clampedValue);
    } else {
      // 无数据显示占位符
      valueEl.textContent = '--';
      progressBar.style.width = '0%';
      statusEl.className = 'fxm-grid-status fxm-status-unknown';
    }
  }

  /**
   * 渲染 PRED 预测结果卡片数据。
   *
   * 更新内容：
   * - 成功率百分比（大号渐变文字）
   * - 进度仪表盘填充宽度 + 颜色
   * - 风险等级 Badge 文字和样式
   * - 优化建议列表
   *
   * @param {Object} data - 数据快照。
   * @private
   */
  _renderPredictionCard(data) {
    const pred = data.prediction;
    if (!pred) return;

    // --- 成功率 ---
    const rateEl = this._predCard.querySelector('.fxm-pred-value');
    if (rateEl && pred.success_rate !== undefined && pred.success_rate !== null) {
      rateEl.textContent = pred.success_rate.toFixed(1);
    }

    // --- 进度仪表盘 ---
    const meterFill = this._predCard.querySelector('.fxm-pred-meter-fill');
    const meterContainer = this._predCard.querySelector('.fxm-pred-meter');
    if (meterFill && pred.success_rate !== undefined) {
      const rate = Math.min(100, Math.max(0, pred.success_rate));
      meterFill.style.width = rate + '%';
      meterFill.className =
        'fxm-pred-meter-fill ' + this._getRiskClass(pred.risk_level);

      if (meterContainer) {
        meterContainer.setAttribute('aria-valuenow', rate.toFixed(1));
      }
    }

    // --- 风险等级 Badge ---
    const badgeEl = this._predCard.querySelector('.fxm-risk-badge');
    if (badgeEl && pred.risk_level) {
      const level = String(pred.risk_level).toUpperCase();
      badgeEl.textContent = level + ' RISK';
      badgeEl.className = `fxm-risk-badge fxm-risk-${String(pred.risk_level).toLowerCase()}`;
    }

    // --- 优化建议列表 ---
    const recList = this._predCard.querySelector('.fxm-rec-list');
    if (recList && pred.recommendations && Array.isArray(pred.recommendations)) {
      // 使用 innerHTML 是安全的：recommendations 来自后端可信数据
      recList.innerHTML = pred.recommendations
        .map((rec) => `<li>${this._escapeHtml(String(rec))}</li>`)
        .join('');
    }
  }

  /**
   * 渲染实时趋势图。
   * 更新历史数据缓冲区并绘制 Canvas 折线图。
   *
   * @param {Object} data - 数据快照。
   * @private
   */
  _renderChart(data) {
    if (!this._chartCanvas || !this._chartHistory) return;

    // 更新历史数据缓冲区
    const cpuValue = data.cpu_metrics?.cpu_utilization;
    const gpuValue = data.gpu_metrics?.gpu_utilization;
    const vramValue = data.gpu_metrics?.vram_percent;

    if (cpuValue !== undefined && cpuValue !== null) {
      this._chartHistory.cpu.push(cpuValue);
      if (this._chartHistory.cpu.length > 60) {
        this._chartHistory.cpu.shift();
      }
    }
    if (gpuValue !== undefined && gpuValue !== null) {
      this._chartHistory.gpu.push(gpuValue);
      if (this._chartHistory.gpu.length > 60) {
        this._chartHistory.gpu.shift();
      }
    }
    if (vramValue !== undefined && vramValue !== null) {
      this._chartHistory.vram.push(vramValue);
      if (this._chartHistory.vram.length > 60) {
        this._chartHistory.vram.shift();
      }
    }

    // 绘制趋势图
    this._drawChart();

    // 更新统计信息
    this._updateChartStats();
  }

  /**
   * 在 Canvas 上绘制趋势折线图。
   * 根据 SPEC.MD 第 423-434 行规范实现。
   *
   * @private
   */
  _drawChart() {
    if (!this._chartCanvas) return;

    const ctx = this._chartCanvas.getContext('2d');
    if (!ctx) return;

    // 处理 HiDPI 显示
    const dpr = window.devicePixelRatio || 1;
    const rect = this._chartCanvas.getBoundingClientRect();
    const width = rect.width || this._chartCanvas.width;
    const height = rect.height || this._chartCanvas.height;

    this._chartCanvas.width = Math.round(width * dpr);
    this._chartCanvas.height = Math.round(height * dpr);
    ctx.scale(dpr, dpr);

    // 清除画布
    ctx.clearRect(0, 0, width, height);

    // 绘制网格线
    this._drawGrid(ctx, width, height);

    // 绘制 CPU 曲线
    if (this._chartHistory.cpu.length > 1) {
      this._drawLine(ctx, this._chartHistory.cpu, width, height, '#00d4ff');
    }

    // 绘制 GPU 曲线
    if (this._chartHistory.gpu.length > 1) {
      this._drawLine(ctx, this._chartHistory.gpu, width, height, '#a855f7');
    }
  }

  /**
   * 绘制网格线。
   *
   * @param {CanvasRenderingContext2D} ctx - Canvas 上下文。
   * @param {number} width - 画布宽度。
   * @param {number} height - 画布高度。
   * @private
   */
  _drawGrid(ctx, width, height) {
    const padding = 10;
    const drawWidth = width - padding * 2;
    const drawHeight = height - padding * 2;

    // 水平网格线（4-5条）
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);

    for (let i = 0; i <= 4; i++) {
      const y = padding + (drawHeight / 4) * i;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(width - padding, y);
      ctx.stroke();
    }

    ctx.setLineDash([]);
  }

  /**
   * 绘制单条曲线。
   *
   * @param {CanvasRenderingContext2D} ctx - Canvas 上下文。
   * @param {Array<number>} data - 数据数组。
   * @param {number} width - 画布宽度。
   * @param {number} height - 画布高度。
   * @param {string} color - 曲线颜色。
   * @private
   */
  _drawLine(ctx, data, width, height, color) {
    const padding = 10;
    const drawWidth = width - padding * 2;
    const drawHeight = height - padding * 2;

    // 计算数据范围
    const minVal = Math.min(...data);
    const maxVal = Math.max(...data);
    const range = maxVal - minVal || 1;

    // 绘制填充区域
    ctx.beginPath();
    data.forEach((val, i) => {
      const x = padding + (i / (data.length - 1)) * drawWidth;
      const y = padding + drawHeight - ((val - minVal) / range) * drawHeight;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(width - padding, height - padding);
    ctx.lineTo(padding, height - padding);
    ctx.closePath();

    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, this._hexToRgba(color, 0.2));
    gradient.addColorStop(1, this._hexToRgba(color, 0));
    ctx.fillStyle = gradient;
    ctx.fill();

    // 绘制折线
    ctx.beginPath();
    data.forEach((val, i) => {
      const x = padding + (i / (data.length - 1)) * drawWidth;
      const y = padding + drawHeight - ((val - minVal) / range) * drawHeight;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.stroke();

    // 绘制最后一个数据点
    const lastVal = data[data.length - 1];
    const lastX = width - padding;
    const lastY = padding + drawHeight - ((lastVal - minVal) / range) * drawHeight;

    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    // 发光效果
    ctx.beginPath();
    ctx.arc(lastX, lastY, 6, 0, Math.PI * 2);
    ctx.fillStyle = this._hexToRgba(color, 0.3);
    ctx.fill();
  }

  /**
   * 更新趋势图下方的统计信息。
   *
   * @private
   */
  _updateChartStats() {
    if (!this._chartContainer) return;

    const statEls = this._chartContainer.querySelectorAll('.fxm-stat-value');
    if (statEls.length < 3) return;

    // 计算平均值
    const cpuAvg = this._chartHistory.cpu.length > 0
      ? this._chartHistory.cpu.reduce((a, b) => a + b, 0) / this._chartHistory.cpu.length
      : null;
    const gpuAvg = this._chartHistory.gpu.length > 0
      ? this._chartHistory.gpu.reduce((a, b) => a + b, 0) / this._chartHistory.gpu.length
      : null;
    const vramPeak = this._chartHistory.vram.length > 0
      ? Math.max(...this._chartHistory.vram)
      : null;

    statEls[0].textContent = cpuAvg !== null ? cpuAvg.toFixed(1) + '%' : '--';
    statEls[1].textContent = gpuAvg !== null ? gpuAvg.toFixed(1) + '%' : '--';
    statEls[2].textContent = vramPeak !== null ? vramPeak.toFixed(1) + '%' : '--';
  }

  /**
   * 渲染系统信息卡片数据。
   *
   * @param {Object} data - 数据快照。
   * @private
   */
  _renderSystemInfo(data) {
    if (!this._systemInfoCard) return;

    // 更新各指标数值
    this._updateSystemMetric('cpu', data.cpu_metrics?.cpu_utilization);
    this._updateSystemMetric('ram', data.ram_metrics?.ram_percent);
    this._updateSystemMetric('gpu', data.gpu_metrics?.gpu_utilization);
    this._updateSystemMetric('vram', data.gpu_metrics?.vram_percent);
    this._updateSystemMetric('power', data.gpu_metrics?.power_usage);
    this._updateSystemMetric('temp', data.gpu_metrics?.temperature);
  }

  /**
   * 更新单个系统指标的显示。
   *
   * @param {string} metric - 指标类型。
   * @param {number|null} value - 数值。
   * @private
   */
  _updateSystemMetric(metric, value) {
    const valueEl = this._systemInfoCard?.querySelector(`[data-metric="${metric}"]`);
    if (!valueEl) return;

    if (value !== null && value !== undefined && !isNaN(value)) {
      valueEl.textContent = value.toFixed(1);
      // 根据数值设置颜色状态
      valueEl.className = 'fxm-system-value ' + this._getStatusClass(value);
    } else {
      valueEl.textContent = '--';
      valueEl.className = 'fxm-system-value';
    }
  }

  /**
   * 将十六进制颜色转换为 RGBA 字符串。
   *
   * @param {string} hex - 十六进制颜色。
   * @param {number} alpha - 透明度。
   * @returns {string} RGBA 颜色字符串。
   * @private
   */
  _hexToRgba(hex, alpha) {
    if (!hex || hex.startsWith('var(')) {
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

    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  /**
   * 渲染底部信息栏数据。
   *
   * 更新内容：
   * - 最后更新时间（相对时间格式）
   * - 数据来源标识
   *
   * @param {Object} data - 数据快照。
   * @private
   */
  _renderFooter(data) {
    // --- 最后更新时间 ---
    const updateEl = this._footer.querySelector('.fxm-footer-update');
    if (updateEl) {
      const ago = this._formatTimeAgo(this._lastUpdateTimestamp || Date.now() / 1000);
      updateEl.textContent = `Last Update: ${ago}`;
    }

    // --- 数据源 ---
    const sourceEl = this._footer.querySelector('.fxm-footer-source');
    if (sourceEl && data.data_source) {
      sourceEl.textContent = `Source: ${data.data_source}`;
    }
  }

  // ---------------------------------------------------------------------------
  // Event Handlers (事件处理器)
  // ---------------------------------------------------------------------------

  /**
   * 绑定所有 DOM 事件和数据源事件。
   *
   * 事件绑定清单：
   * - mousedown on header -> 开始拖拽
   * - mousemove on document -> 拖拽移动
   * - mouseup on document -> 结束拖拽
   * - click on collapse button -> 折叠面板
   * - click on close button -> 关闭面板
   * - dblclick on header -> 切换展开/折叠
   * - keydown on element -> Escape 关闭
   *
   * @private
   */
  _bindEvents() {
    // ---- 拖拽事件（绑定在 document 以支持拖出面板范围）----
    this._header.addEventListener('mousedown', this._handleMouseDown);
    document.addEventListener('mousemove', this._handleMouseMove);
    document.addEventListener('mouseup', this._handleMouseUp);

    // ---- 控制按钮 ----
    const collapseBtn = this._header.querySelector('.fxm-btn-collapse');
    const closeBtn = this._header.querySelector('.fxm-btn-close');

    if (collapseBtn) {
      collapseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.collapse();
      });
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.close();
      });
    }

    // ---- 双击标题栏切换展开/折叠 ----
    this._header.addEventListener('dblclick', this._handleDoubleClick);

    // ---- 键盘导航 ----
    this._element.addEventListener('keydown', this._handleKeyDown);

    // ---- 阻止面板内滚动冒泡影响页面（可选）----
    this._body.addEventListener('wheel', (e) => {
      const { scrollTop, scrollHeight, clientHeight } = this._body;
      if (
        (e.deltaY < 0 && scrollTop <= 0) ||
        (e.deltaY > 0 && scrollTop + clientHeight >= scrollHeight)
      ) {
        // 已到达边界，不阻止默认行为让外层可以滚动
      }
    }, { passive: true });

    // ---- 监听外部显示面板事件（来自 TopMenuBar 胶囊点击）----
    this._bindPanelShowEvent();
  }

  /**
   * 绑定事件总线的 'panel:show' 事件。
   * 当用户点击 TopMenuBar 的胶囊时，触发面板显示。
   *
   * @private
   */
  _bindPanelShowEvent() {
    if (this.eventBus && typeof this.eventBus.on === 'function') {
      this._boundPanelShowHandler = (eventData) => {
        if (eventData.source === 'topmenubar') {
          this.show();
        }
      };
      this.eventBus.on('panel:show', this._boundPanelShowHandler);
    }
  }

  /**
   * 解绑所有 DOM 事件监听器（用于 destroy 时防止内存泄漏）。
   *
   * @private
   */
  _unbindEvents() {
    if (this._header) {
      this._header.removeEventListener('mousedown', this._handleMouseDown);
      this._header.removeEventListener('dblclick', this._handleDoubleClick);
    }

    document.removeEventListener('mousemove', this._handleMouseMove);
    document.removeEventListener('mouseup', this._handleMouseUp);

    if (this._element) {
      this._element.removeEventListener('keydown', this._handleKeyDown);
    }

    // 解绑事件总线的 panel:show 事件
    if (this.eventBus && this._boundPanelShowHandler) {
      this.eventBus.off('panel:show', this._boundPanelShowHandler);
      this._boundPanelShowHandler = null;
    }
  }

  /**
   * 绑定 DataService 数据更新事件。
   *
   * @private
   */
  _bindDataSource() {
    if (this.dataService) {
      this.dataService.on('data', this._onDataUpdate);
    }
  }

  /**
   * DataService 数据事件的回调包装器。
   * 将原始事件数据转发给 update() 方法。
   *
   * @param {*} data - 收到的数据载荷。
   * @private
   */
  _onDataUpdate(data) {
    this.update(data);
  }

  // ---------------------------------------------------------------------------
  // Drag Implementation (高性能拖拽实现)
  // ---------------------------------------------------------------------------

  /**
   * 处理 mousedown 事件 -- 开始拖拽。
   *
   * 触发条件：
   * - 仅左键点击（button === 0）
   * - 点击位置不在控制按钮区域内
   *
   * 操作：
   * - 记录鼠标按下时的偏移量
   * - 禁用 CSS transition（避免拖拽时的延迟感）
   * - 设置 cursor: grabbing
   * - 阻止默认行为（防止文本选中）
   *
   * @param {MouseEvent} e - 鼠标事件对象。
   * @private
   */
  _handleMouseDown(e) {
    // 仅响应左键
    if (e.button !== 0) return;

    // 点击在控制按钮上时不启动拖拽
    if (e.target.closest('.fxm-panel-controls')) return;

    this._isDragging = true;

    // 记录鼠标在面板内的偏移（使拖拽起点不变）
    this._dragOffset = {
      x: e.clientX - this._position.x,
      y: e.clientY - this._position.y,
    };

    // 拖拽时禁用 transition 动画（否则会有跟随延迟）
    this._element.style.transition = 'none';
    this._element.classList.add('fxm-dragging');

    e.preventDefault(); // 防止文本被选中
  }

  /**
   * 处理 mousemove 事件 -- 拖拽移动。
   *
   * 性能关键路径 -- 每帧可能触发数十次。
   * 优化措施：
   * - 仅在 _isDragging 为 true 时执行计算
   * - 使用 transform 而非 top/left（避免 reflow）
   * - 边界 clamp 防止面板拖出可视区域
   *
   * @param {MouseEvent} e - 鼠标事件对象。
   * @private
   */
  _handleMouseMove(e) {
    if (!this._isDragging) return;
    if (!this._element) return;

    // 计算新位置
    let newX = e.clientX - this._dragOffset.x;
    let newY = e.clientY - this._dragOffset.y;

    // 边界检测：防止面板完全移出可视区域
    const rect = this._element.getBoundingClientRect();
    const maxX = window.innerWidth - Math.min(rect.width, 100); // 至少保留 100px 可见
    const maxY = window.innerHeight - 42; // 至少保留标题栏高度

    newX = Math.max(0, Math.min(newX, maxX));
    newY = Math.max(0, Math.min(newY, maxY));

    this._position = { x: newX, y: newY };
    this._applyPosition();
  }

  /**
   * 处理 mouseup 事件 -- 结束拖拽。
   *
   * 操作：
   * - 恢复 CSS transition（使后续状态切换有动画）
   * - 移除 dragging 样式类
   * - 将最终位置持久化到 localStorage
   * - 发射 position-changed 事件
   *
   * @param {MouseEvent} e - 鼠标事件对象。
   * @private
   */
  _handleMouseUp(e) {
    if (!this._isDragging) return;

    this._isDragging = false;

    // 恢复过渡动画
    if (this._element) {
      this._element.style.transition = '';
      this._element.classList.remove('fxm-dragging');
    }

    // 持久化位置
    this.savePosition();

    // 通知外部位置已变更
    this.eventBus?.emit('panel:position-changed', {
      position: { ...this._position }
    });
  }

  /**
   * 处理键盘事件。
   *
   * 支持的快捷键：
   * - Escape: 关闭面板
   *
   * @param {KeyboardEvent} e - 键盘事件对象。
   * @private
   */
  _handleKeyDown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
    }
  }

  /**
   * 处理双击标题栏事件 -- 切换展开/折叠状态。
   *
   * @private
   */
  _handleDoubleClick() {
    this.toggle();
  }

  // ---------------------------------------------------------------------------
  // State Machine (状态机实现)
  // ---------------------------------------------------------------------------

  /**
   * 内部状态切换引擎。
   *
   * 所有状态变更必须经过此方法，确保：
   * - 状态合法性检查
   * - CSS 类名的正确添加/移除
   * - DOM 属性同步更新
   * - ConfigManager 持久化
   * - 事件通知
   *
   * @param {string} newState - 目标状态: 'expanded' | 'collapsed' | 'hidden'
   * @private
   */
  _setState(newState) {
    const oldState = this._state;
    if (oldState === newState) return; // 幂等保护

    this._state = newState;

    switch (newState) {
      case 'expanded':
        this._applyExpandedState();
        break;

      case 'collapsed':
        this._applyCollapsedState();
        break;

      case 'hidden':
        this._applyHiddenState(oldState);
        break;

      default:
        console.warn(`[HoverPanel] Unknown state: ${newState}, reverting.`);
        this._state = oldState;
        return;
    }

    // 持久化状态到 ConfigManager
    if (this.config) {
      try {
        this.config.set('ui.panelState', newState);
      } catch (error) {
        console.warn('[HoverPanel] Failed to save state:', error);
      }
    }

    // 发射状态变更事件（供 TopMenuBar 等联动组件监听）
    this.eventBus?.emit('panel:state-changed', {
      from: oldState,
      to: newState,
    });

    console.log(`[HoverPanel] State: ${oldState} -> ${newState}`);
  }

  /**
   * 应用展开状态。
   * - 移除 collapsed / hidden CSS 类
   * - 主体区域恢复最大高度和不透明度
   *
   * @private
   */
  _applyExpandedState() {
    if (!this._element) return;

    this._element.classList.remove('fxm-collapsed', 'fxm-hidden');

    // 使用 scrollHeight 获取自然高度，然后设置 maxHeight 触发过渡动画
    requestAnimationFrame(() => {
      if (this._body) {
        this._body.style.maxHeight = this._body.scrollHeight + 80 + 'px'; // +80 预留 PRED 卡片空间
        this._body.style.opacity = '1';
      }
      if (this._footer) {
        this._footer.style.opacity = '1';
      }
    });
  }

  /**
   * 应用折叠状态。
   * - 添加 collapsed CSS 类
   * - 主体区域 maxHeight 收缩至 0，opacity 渐隐
   *
   * @private
   */
  _applyCollapsedState() {
    if (!this._element) return;

    this._element.classList.remove('fxm-hidden');
    this._element.classList.add('fxm-collapsed');

    if (this._body) {
      this._body.style.maxHeight = '0';
      this._body.style.opacity = '0';
    }
    if (this._footer) {
      this._footer.style.opacity = '0';
    }
  }

  /**
   * 应用隐藏状态。
   * - 移除 collapsed 类，添加 hidden 类
   * - 整体透明度归零 + 微缩放 + 右位移（退场效果）
   * - 通知 TopMenuBar 显示"重新打开"按钮
   *
   * @param {string} previousState - 之前的状态（用于日志）。
   * @private
   */
  _applyHiddenState(previousState) {
    if (!this._element) return;

    this._element.classList.remove('fxm-collapsed');
    this._element.classList.add('fxm-hidden');

    if (this._body) {
      this._body.style.maxHeight = '0';
      this._body.style.opacity = '0';
    }
    if (this._footer) {
      this._footer.style.opacity = '0';
    }

    // 通知外部组件（TopMenuBar）面板已关闭
    this.eventBus?.emit('panel:closed', {
      from: previousState,
      position: { ...this._position },
    });
  }

  // ---------------------------------------------------------------------------
  // Animation (动画系统)
  // ---------------------------------------------------------------------------

  /**
   * 播放入场动画。
   *
   * 使用 CSS Animation 实现"从右侧滑入 + 淡入 + 弹性缩放"效果。
   * 动画曲线采用 spring 类型 (cubic-bezier(0.34, 1.56, 0.64, 1))，
   * 产生轻微的弹性回弹效果，增强科技感。
   *
   * 动画结束后自动清除 animation 属性，
   * 避免影响后续 transform: translate() 拖拽定位。
   *
   * @private
   */
  _playEntranceAnimation() {
    if (!this._element) return;
    
    // 如果是隐藏状态，不播放入场动画
    if (this._state === 'hidden') return;

    this._element.style.animation =
      'fxm-slideInRight 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) forwards';

    // 动画结束后清理 animation 属性
    const cleanup = () => {
      if (this._element) {
        this._element.style.animation = '';
      }
    };

    // 使用 { once: true } 自动移除监听器（防止内存泄漏）
    this._element.addEventListener('animationend', cleanup, { once: true });

    // 安全兜底：如果 animationend 未触发（如 display:none），5s 后强制清理
    setTimeout(cleanup, 5000);
  }

  // ---------------------------------------------------------------------------
  // Utility Methods (工具方法)
  // ---------------------------------------------------------------------------

  /**
   * 从持久化存储加载保存的状态和位置。
   *
   * 加载优先级：
   * 1. ConfigManager.ui.panelState
   * 2. ConfigManager.position
   * 3. localStorage fallback keys
   *
   * @private
   */
  _loadSavedState() {
    // 加载状态
    if (this.config && this.config.isReady) {
      const savedState = this.config.get('ui.panelState');
      if (['expanded', 'collapsed', 'hidden'].includes(savedState)) {
        this._state = savedState;
        // 注意：如果是 hidden 状态，init 后仍然先渲染 expanded，
        // 然后再应用 hidden 状态（避免用户看到空白）
      }
    }

    // 加载位置
    this._loadPosition();
  }

  /**
   * 启动底部时间戳自动刷新定时器。
   *
   * 每秒更新一次 "Last Update: Xs ago" 显示，
   * 使相对时间保持准确（即使没有新数据到达）。
   *
   * @private
   */
  _startTimeUpdater() {
    // 先清理已有的定时器
    if (this._timeUpdateIntervalId !== null) {
      clearInterval(this._timeUpdateIntervalId);
    }

    this._timeUpdateIntervalId = setInterval(() => {
      if (!this._footer || this._state === 'hidden') return;

      const updateEl = this._footer.querySelector('.fxm-footer-update');
      if (updateEl && this._lastUpdateTimestamp) {
        const ago = this._formatTimeAgo(this._lastUpdateTimestamp);
        updateEl.textContent = `Last Update: ${ago}`;
      }
    }, 1000); // 每秒刷新
  }

  /**
   * 根据数值返回对应的 CSS 状态类名。
   *
   * 分级规则：
   * - 0 ~ 59:   low （绿色，正常负载）
   * - 60 ~ 84:  medium（黄色，中等负载）
   * - 85 ~ 100: high  （红色，高负载警告）
   * - 其他:     unknown（灰色，无数据）
   *
   * @param {number} value - 指标数值 (0-100)。
   * @returns {string} CSS 类名。
   * @private
   */
  _getStatusClass(value) {
    if (value === null || value === undefined || isNaN(value)) {
      return 'fxm-status-unknown';
    }
    if (value < 60) return 'fxm-status-low';
    if (value < 85) return 'fxm-status-medium';
    return 'fxm-status-high';
  }

  /**
   * 根据风险等级返回对应的 CSS 类名。
   *
   * @param {string} level - 风险等级字符串 ('low'|'medium'|'high'|'critical')。
   * @returns {string} CSS 类名。
   * @private
   */
  _getRiskClass(level) {
    const levelMap = {
      low: 'fxm-risk-low',
      medium: 'fxm-risk-medium',
      high: 'fxm-risk-high',
      critical: 'fxm-risk-critical',
    };
    return levelMap[String(level).toLowerCase()] || 'fxm-risk-unknown';
  }

  /**
   * 格式化为相对时间字符串。
   *
   * @param {number} timestamp - Unix 时间戳（秒）。
   * @returns {string} 格式化后的相对时间，如 "2s ago", "5m ago", "3h ago"。
   * @private
   */
  _formatTimeAgo(timestamp) {
    if (!timestamp) return '--';

    const seconds = Math.floor((Date.now() / 1000) - timestamp);

    if (seconds < 0) return 'just now'; // 未来时间（时钟偏差）
    if (seconds < 60) return `${seconds}s ago`;

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;

    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  /**
   * HTML 特殊字符转义（防止 XSS 注入）。
   *
   * @param {string} str - 需要转义的字符串。
   * @returns {string} 转义后的安全字符串。
   * @private
   */
  _escapeHtml(str) {
    const escapeMap = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    };
    return str.replace(/[&<>"']/g, (char) => escapeMap[char]);
  }
}

// =============================================================================
// Export
// =============================================================================

export default HoverPanel;
export { HoverPanel };
